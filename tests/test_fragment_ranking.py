import math
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import database
import main
import memory_extraction


class FragmentRankingTests(unittest.TestCase):
    def test_all_five_weights_and_thirty_day_half_life(self):
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        row = {'created_at': now - timedelta(days=30), 'metadata': {
            'extraction_job_id': 1, 'source_conversation_id': 7,
            'importance': 0.8, 'entities': ['钢琴', '北京'],
        }}
        with patch.object(database, 'FRAGMENT_RECENCY_HALF_LIFE_DAYS', 30):
            score = database.fragment_recall_scores(row, '钢琴计划', 0.6, [7, 8], now)
        self.assertEqual(0.5, score['recency_score'])
        self.assertEqual(0.5, score['entity_overlap'])
        self.assertEqual(1, score['thread_affinity'])
        self.assertAlmostEqual(0.6 * .45 + .5 * .20 + .8 * .15 + .5 * .10 + .10, score['total'])

    def test_migration_does_not_reset_recency_and_missing_importance_is_neutral(self):
        row = {'created_at': datetime.now(timezone.utc), 'memory_date': '2099-01-01',
               'metadata': {'migrated_from': 'diary_summary'}}
        score = database.fragment_recall_scores(row, 'hello', .7)
        self.assertEqual(0, score['recency_score'])
        self.assertEqual(.5, score['importance'])
        self.assertEqual(0, score['thread_affinity'])

    def test_invalid_importance_or_invented_entities_rejected(self):
        messages = [{'id': 1, 'role': 'user', 'content': '我要学习钢琴'}]
        fragment = {'memory_date': '2026-09-09', 'content': '计划学习钢琴',
                    'importance': .8, 'entities': ['钢琴'],
                    'anchors': [{'message_id': 1, 'quote': '我要学习钢琴'}]}
        payload = {'fragments': [fragment]}
        self.assertEqual(.8, memory_extraction.validate_fragments(payload, messages, 7)[0]['importance'])
        fragment['importance'] = float('nan')
        with self.assertRaises(ValueError):
            memory_extraction.validate_fragments(payload, messages, 7)
        fragment['importance'] = .8
        fragment['entities'] = ['北京']
        with self.assertRaises(ValueError):
            memory_extraction.validate_fragments(payload, messages, 7)


class FragmentGateTests(unittest.IsolatedAsyncioTestCase):
    async def search(self, vectors, rows):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=rows)
        conn.fetchval = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock()
        with (patch.object(database, 'get_pool', AsyncMock(return_value=pool)),
              patch.object(database, '_embed_conversation_chunks', AsyncMock(return_value=vectors)),
              patch.object(database, 'schedule_long_term_memory_embedding_refresh', MagicMock()),
              patch.object(database, 'LONG_TERM_RECALL_MIN_SEMANTIC_SCORE', .35)):
            return await database.search_long_term_memory_summaries('钢琴', {}, 8, entry_kind='fragment')

    def row(self, id, similarity, importance=1):
        return {'id': id, 'content': '钢琴', 'created_at': datetime.now(timezone.utc),
                'embedding': [similarity, math.sqrt(1 - similarity ** 2)],
                'metadata': {'entry_kind': 'fragment', 'importance': importance,
                             'extraction_job_id': 1, 'entities': ['钢琴']}}

    async def test_keyword_match_recency_importance_cannot_bypass_gate(self):
        self.assertEqual([], await self.search([[1, 0]], [self.row(1, .34)]))

    async def test_absent_query_or_candidate_vectors_return_zero(self):
        self.assertEqual([], await self.search([None], [self.row(1, .9)]))
        row = self.row(2, .9)
        row['embedding'] = None
        self.assertEqual([], await self.search([[1, 0]], [row]))

    async def test_ranking_applies_only_after_gate_and_honors_disabled(self):
        disabled = self.row(4, 1)
        disabled['enabled'] = False
        pending = self.row(5, 1)
        pending['metadata']['forgetting_pending'] = True
        result = await self.search([[1, 0]], [self.row(1, .34), self.row(2, .8, 0),
                                            self.row(3, .8, 1), disabled, pending])
        self.assertEqual([3, 2], [row['id'] for row in result])
        self.assertAlmostEqual(.15, result[0]['score'] - result[1]['score'], places=5)

    async def test_zero_results_omit_prompt_block(self):
        with (patch.object(main, 'MEMORY_ENABLED', True),
              patch.object(main, 'get_conversation_model_settings', AsyncMock(return_value={'search_enabled': True})),
              patch.object(main, 'search_long_term_memory_summaries', AsyncMock(return_value=[]))):
            self.assertEqual('', await main._build_long_term_recall_block('无关消息'))
