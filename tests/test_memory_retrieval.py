import copy
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import main
import memory_retrieval as retrieval


def turn(mid, text, score=.8):
    row = {'id': mid, 'conversation_id': 2, 'role': 'user', 'content': text,
           'created_at': datetime(2020, 1, 1, tzinfo=timezone.utc)}
    return {'conversation_id': 2, 'turn_id': mid, 'messages': [row], 'score': score,
            'matches': [{'message_id': mid, 'role': 'user', 'start': 0, 'end': len(text), 'text': text}]}


class RankingTests(unittest.IsolatedAsyncioTestCase):
    async def test_feedback_filters_only_matching_topic_and_source_version(self):
        candidate = turn(1, '什么东西长了五根脚趾却不是你的脚？')
        record = {'turn_id': 1, 'terms': retrieval.keyword_query_terms('五根脚趾'),
                  'source_hash': retrieval.originals.source_hash(candidate['messages'][0]), 'value': 'useless'}
        settings = {'history_recall_settings': {'hybrid_feedback': [record]}}
        with patch.object(retrieval, 'lexical_search', AsyncMock(return_value=[candidate])):
            results, diagnostics = await retrieval.retrieve('什么东西五根脚趾', settings)
        self.assertEqual([], results)
        self.assertEqual(1, diagnostics['feedback_filtered'])
        self.assertIsNone(retrieval.feedback_for('海边旅行', candidate, settings))
        edited = copy.deepcopy(candidate)
        edited['messages'][0]['content'] += '已经修改'
        self.assertIsNone(retrieval.feedback_for('五根脚趾', edited, settings))
        settings['history_recall_settings']['hybrid_feedback'].append({**record, 'value': 'reset'})
        self.assertEqual('reset', retrieval.feedback_for('五根脚趾', candidate, settings))

    async def test_useful_feedback_promotes_relevant_evidence(self):
        a, b = turn(1, '海边旅行'), turn(2, '海边旅行')
        settings = {'history_recall_settings': {'hybrid_feedback': [{
            'turn_id': 2, 'terms': retrieval.keyword_query_terms('海边旅行'),
            'source_hash': retrieval.originals.source_hash(b['messages'][0]), 'value': 'useful'}]}}
        with patch.object(retrieval, 'lexical_search', AsyncMock(return_value=[a, b])):
            results, _ = await retrieval.retrieve('海边旅行', settings)
        self.assertEqual(2, results[0]['turn_id'])

    async def test_feedback_endpoint_preserves_weights_and_validates_source(self):
        row = turn(1, '五根脚趾')['messages'][0]
        conn = MagicMock(execute=AsyncMock(), fetchrow=AsyncMock(side_effect=[row, {'history_recall_settings': {'hybrid': {'keyword': .8}}}]))
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(main.db, 'get_pool', AsyncMock(return_value=pool)):
            result = await main.save_memory_retrieval_feedback(MagicMock(json=AsyncMock(return_value={
                'query':'五根脚趾','turn_id':1,'value':'useless'})))
        self.assertEqual('useless', result['value'])
        sql, records = conn.execute.await_args.args
        self.assertIn('jsonb_set', sql)
        self.assertIn('{hybrid_feedback}', sql)
        self.assertEqual(retrieval.originals.source_hash(row), json.loads(records)[0]['source_hash'])

    async def test_longer_chinese_query_keeps_original_match_at_high_threshold(self):
        original = turn(1, '什么东西长了五根脚趾却不是你的脚？')['messages'][0]
        conn = MagicMock(execute=AsyncMock(), fetch=AsyncMock(return_value=[original]))
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(retrieval.db, 'get_pool', AsyncMock(return_value=pool)), patch.object(
            retrieval, 'reranker_configured', return_value=False
        ):
            for query in ('五根脚趾', '什么东西五根脚趾', '什么东西 五根脚趾'):
                with self.subTest(query=query):
                    results, _ = await retrieval.retrieve(query, {}, override={'min_score': .95})
                    self.assertEqual([1], [t['turn_id'] for t in results])
                    self.assertEqual(1., results[0]['score_components']['relevance'])
                    sql, keys = conn.fetch.await_args.args
                    self.assertIn(' @> ', sql)
                    self.assertNotIn('西五', keys)
                    self.assertNotIn('什么', keys)
        self.assertEqual(3, conn.fetch.await_count, 'successful precise matches avoid broad search')

    async def test_partial_keyword_query_falls_back_when_intersection_is_empty(self):
        original = turn(1, '五根脚趾')['messages'][0]
        conn = MagicMock(execute=AsyncMock(), fetch=AsyncMock(side_effect=[[], [original]]))
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(retrieval.db, 'get_pool', AsyncMock(return_value=pool)):
            result = await retrieval.lexical_search('谜语 五根脚趾')
        self.assertTrue(result)
        self.assertIn(' && ', conn.fetch.await_args.args[0])

    def test_rrf_consensus_and_no_duplicate_votes(self):
        a, b = turn(1, '苹果'), turn(2, '梨')
        result = retrieval.fuse({'keyword': [a, a, b], 'semantic': [b]}, {'keyword': .5, 'semantic': .5})
        self.assertEqual(2, result[0]['turn_id'])
        self.assertAlmostEqual(.5 / 61, result[1]['rrf'])
        self.assertEqual(1, len(result[1]['matches']))

    def test_mmr_penalizes_duplicate_against_selected(self):
        candidates = [dict(turn(1, '去年去海边旅行'), rrf=.02),
                      dict(turn(2, '去年去海边旅行', .79), rrf=.02),
                      dict(turn(3, '约定以后去山上看雪', .78), rrf=.02)]
        self.assertEqual([1, 3], [t['turn_id'] for t in retrieval.select_diverse(candidates, .5, 2)])

    def test_settings_reject_nan_and_empty_routes(self):
        for weights in ({'keyword': float('nan')}, {'semantic': True}, {'keyword': 0, 'semantic': 0}):
            with self.assertRaises(ValueError):
                retrieval.options({}, weights)

    async def test_semantic_failure_preserves_old_keyword_evidence_and_reports_degradation(self):
        with patch.object(retrieval, 'lexical_search', AsyncMock(return_value=[turn(1, '原话')])) as keyword, patch.object(
            retrieval.vectors, 'embedding_configured', return_value=True
        ), patch.object(retrieval.vectors, 'search', AsyncMock(side_effect=TimeoutError)), patch.object(
            retrieval, 'reranker_configured', return_value=False
        ):
            turns, report = await retrieval.retrieve('原话', {})
        self.assertEqual(1, turns[0]['turn_id'])
        self.assertIn('semantic:TimeoutError', report['warnings'])
        block, selected, _ = retrieval.pack(turns, 1000)
        self.assertTrue(block.startswith('<system_info>'))
        self.assertTrue(block.endswith('</system_info>'))
        self.assertIn('2020-01-01', block)
        self.assertLessEqual(len(retrieval.pack(turns, 50)[0]), 50)

    async def test_visible_evidence_and_irrelevant_candidates_are_omitted(self):
        with patch.object(retrieval, 'lexical_search', AsyncMock(return_value=[turn(1, '原话'), turn(2, '无关', .01)])):
            turns, _ = await retrieval.retrieve('问题', {}, visible_messages=[{'role': 'user', 'content': '原话'}])
        self.assertEqual([], turns)

    async def test_cross_encoder_scores_control_relevance_filter(self):
        with patch.object(retrieval, 'lexical_search', AsyncMock(return_value=[turn(1, '苹果'), turn(2, '梨')])), patch.object(
            retrieval, 'reranker_configured', return_value=True
        ), patch.object(retrieval, 'rerank', AsyncMock(return_value={0: .01, 1: .9})):
            turns, report = await retrieval.retrieve('水果', {})
        self.assertEqual([2], [t['turn_id'] for t in turns])
        self.assertEqual('cross_encoder', report['reranker'])

    async def test_preview_is_read_only_and_marks_actual_budget_selection(self):
        with patch.object(main.fragments, 'search', AsyncMock(return_value=[{'id':1,'content':'<script>片段</script>'}])), patch.object(
            main, 'get_conversation_model_settings', AsyncMock(return_value={'long_term_recall_char_budget':1000})
        ), patch.object(main, 'save_context_message', AsyncMock()) as save:
            response = await main.preview_memory_retrieval(MagicMock(json=AsyncMock(return_value={'query':'片段'})))
        save.assert_not_awaited()
        self.assertEqual(1,response['results'][0]['id'])
        self.assertIn('&lt;script&gt;', response['injection'])
        self.assertNotIn('<script>', response['injection'])

    async def test_weight_save_merges_only_hybrid_settings(self):
        conn = MagicMock(execute=AsyncMock())
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(main, 'get_conversation_model_settings', AsyncMock(return_value={})), patch.object(
            main.db, 'get_pool', AsyncMock(return_value=pool)
        ):
            result = await main.save_memory_retrieval_settings(MagicMock(json=AsyncMock(return_value={
                'weights': {'keyword': .8, 'semantic': .2}})))
        self.assertEqual(.8, result['weights']['keyword'])
        sql, weights = conn.execute.await_args.args
        self.assertIn("|| jsonb_build_object('hybrid'", sql)
        self.assertNotIn('embedding_api_key', sql)
        self.assertEqual(.2, json.loads(weights)['semantic'])

    async def test_invalid_preview_weights_do_not_run_retrieval(self):
        with patch.object(main, 'get_conversation_model_settings', AsyncMock(return_value={})), patch.object(
            retrieval, 'retrieve', AsyncMock()
        ) as search:
            response = await main.preview_memory_retrieval(MagicMock(json=AsyncMock(return_value={
                'query': '原话', 'weights': {'diversity': -1}})))
        self.assertEqual(400, response.status_code)
        search.assert_not_awaited()


class TemporaryInjectionTests(unittest.TestCase):
    def test_anthropic_cache_stops_before_suffix_even_in_tool_round(self):
        history = [{'role': 'user', 'content': '问题'}]
        before = copy.deepcopy(history)
        model = 'claude-opus-4-6'
        with patch.object(main, 'PROMPT_CACHE_ENABLED', True), patch.object(main, 'PROMPT_CACHE_MESSAGE_MODELS', {model}):
            config = {'model': model, 'system': [{'type':'text','text':'core','cache_control':{'type':'ephemeral','ttl':'1h'}}],
                      '_recall_suffix': '<system_info>原话</system_info>'}
            first = main._anthropic_body_for_request(config, history, stream=False)
            second = main._anthropic_body_for_request(config, history + [
                {'role':'assistant','content':[{'type':'tool_use','id':'t','name':'x','input':{}}]},
                {'role':'user','content':[{'type':'tool_result','tool_use_id':'t','content':'结果'}]}], stream=False)
        self.assertEqual(before, history)
        for body in (first, second):
            blocks = body['messages'][0]['content']
            self.assertIn('cache_control', blocks[0])
            self.assertNotIn('cache_control', blocks[-1])
            self.assertTrue(blocks[-1]['text'].startswith('\n\n\n<system_info>'))
            self.assertNotIn('_recall_suffix', body)
        self.assertNotIn('cache_control', second['messages'][-1]['content'][0])
