import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import fragment_decay as decay
import memory_extraction as extraction
import main


class DecayRulesTests(unittest.TestCase):
    def row(self, importance=.5, days=300):
        return {'id': 1, 'content': '偏好', 'metadata': {'entry_kind': 'fragment',
            'importance': importance, 'importance_scored_at':
                (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()}}

    def test_important_memories_decay_more_slowly(self):
        self.assertLess(decay.retention(self.row(0)), decay.THRESHOLD)
        self.assertGreater(decay.retention(self.row(1)), decay.THRESHOLD)

    def test_unscored_unknown_age_and_non_fragments_are_not_forgotten(self):
        row = self.row()
        del row['metadata']['importance']
        self.assertIsNone(decay.retention(row))
        row = self.row()
        del row['metadata']['importance_scored_at']
        self.assertIsNone(decay.retention(row))
        row = self.row()
        row['metadata']['entry_kind'] = 'diary'
        self.assertIsNone(decay.retention(row))

    def test_retaining_resets_decay_clock(self):
        row = self.row(0, 1000)
        row['metadata']['retention_reset_at'] = datetime.now(timezone.utc).isoformat()
        self.assertGreater(decay.retention(row), .99)

    def test_tools_have_no_reason_field(self):
        for tool in main.BUILTIN_MEMORY_TOOLS:
            if tool['name'] in ('create_memory', 'edit_memory', 'delete_memory'):
                self.assertNotIn('reason', tool['input_schema']['properties'])

    def test_legacy_scoring_covers_exact_batch_without_reasons(self):
        batch = [{'id': 1}, {'id': 2}, {'id': 3}]
        scores = [{'id': i, 'importance': .5} for i in (1, 2, 3)]
        self.assertEqual({1: .5, 2: .5, 3: .5}, extraction.validate_legacy_scores(scores, batch))
        with self.assertRaises(ValueError):
            extraction.validate_legacy_scores(scores[:2], batch)
        with self.assertRaises(ValueError):
            extraction.validate_legacy_scores([scores[0]] * 3, batch)


class DecayPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def conn_pool(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        conn.fetch = AsyncMock()
        conn.fetchrow = AsyncMock()
        conn.transaction.return_value.__aenter__ = AsyncMock()
        conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        return conn, pool

    async def test_sweep_only_queues_never_deletes(self):
        conn, pool = self.conn_pool()
        conn.fetch.return_value = [DecayRulesTests().row(0, 300)]
        with patch.object(decay, 'get_pool', AsyncMock(return_value=pool)):
            await decay.sweep()
        sql = '\n'.join(call.args[0] for call in conn.execute.await_args_list)
        self.assertIn('INSERT INTO fragment_forgetting_pending', sql)
        self.assertNotIn('DELETE', sql)

    async def test_delete_requires_pending_and_unchanged_content(self):
        conn, pool = self.conn_pool()
        conn.fetchrow.side_effect = [{'content': '新内容'}, {'content_snapshot': '旧内容'}]
        with patch.object(decay, 'get_pool', AsyncMock(return_value=pool)):
            with self.assertRaises(ValueError):
                await decay.resolve(1, True)
        conn.execute.assert_not_awaited()

    async def test_confirm_and_retain_have_distinct_effects(self):
        for forget in (True, False):
            conn, pool = self.conn_pool()
            conn.fetchrow.side_effect = [{'content': '偏好'}, {'content_snapshot': '偏好'}]
            with patch.object(decay, 'get_pool', AsyncMock(return_value=pool)):
                self.assertTrue(await decay.resolve(1, forget))
            sql = '\n'.join(call.args[0] for call in conn.execute.await_args_list)
            self.assertEqual(forget, 'DELETE FROM long_term_memories' in sql)
            if not forget:
                self.assertIn('retention_reset_at', conn.execute.await_args_list[0].args[2])

    async def test_retries_reuse_reserved_old_scores(self):
        conn, pool = self.conn_pool()
        conn.fetchrow.return_value = {'legacy_snapshot': '[{"id":2,"content":"旧偏好"}]'}
        with patch.object(extraction, 'get_pool', AsyncMock(return_value=pool)):
            rows = await extraction.prepare_legacy({'id': 7, 'lease_token': 'token'})
        self.assertEqual(2, rows[0]['id'])
        conn.fetch.assert_not_awaited()
        conn.execute.assert_not_awaited()
