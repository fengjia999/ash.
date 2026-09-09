import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import main
import memory_extraction as extraction


class EvidenceTests(unittest.TestCase):
    def test_snapshot_excludes_copied_messages_and_tool_material(self):
        rows = [
            {'id': 1, 'role': 'user', 'content': '明年想搬家'},
            {'id': 2, 'role': 'user', 'content': '旧记忆', 'kind': 'handoff_copy'},
            {'id': 3, 'role': 'assistant', 'content_json': [
                {'type': 'thinking', 'thinking': '秘密'},
                {'type': 'tool_use', 'name': 'search_memory'},
                {'type': 'text', 'text': '还没决定日期？'},
            ]},
            {'id': 4, 'role': 'user', 'content': 'hidden', 'hidden': True},
        ]
        self.assertEqual(extraction.conversation_snapshot(rows), [
            {'id': 1, 'role': 'user', 'content': '明年想搬家'},
            {'id': 3, 'role': 'assistant', 'content': '还没决定日期？'},
        ])

    def test_snapshot_exposes_source_time_as_gateway_local_absolute_time(self):
        rows = [{
            'id': 1,
            'role': 'user',
            'content': '今晚提醒我',
            'created_at': datetime(2026, 9, 9, 18, 30, tzinfo=timezone.utc),
        }]
        with patch.object(extraction, 'TIMEZONE_HOURS', 8):
            snapshot = extraction.conversation_snapshot(rows)
        self.assertEqual('2026-09-10T02:30:00+08:00', snapshot[0]['created_at'])

    def test_quotes_verified_against_exact_message_and_speaker(self):
        rows = [{'id': 1, 'role': 'user', 'content': '我现在喜欢早起散步。'}]
        payload = {'fragments': [{'memory_date': '2026-09-09',
                    'content': '用户现在喜欢早起散步。',
                    'anchors': [{'message_id': 1, 'quote': '喜欢早起散步'}]}]}
        result = extraction.validate_fragments(payload, rows, 7)
        self.assertEqual('2026-09-09：用户现在喜欢早起散步。', result[0]['content'])
        self.assertEqual(result[0]['anchors'][0]['role'], 'user')
        self.assertEqual(result[0]['anchors'][0]['conversation_id'], 7)
        payload['fragments'][0]['anchors'][0]['quote'] = '每天五点起床'
        with self.assertRaises(ValueError):
            extraction.validate_fragments(payload, rows, 7)
        payload['fragments'][0]['anchors'] = []
        with self.assertRaises(ValueError):
            extraction.validate_fragments(payload, rows, 7)

    def test_fragment_requires_a_valid_absolute_date(self):
        rows = [{'id': 1, 'role': 'user', 'content': '我喜欢散步'}]
        fragment = {
            'memory_date': '明天',
            'content': '用户喜欢散步。',
            'anchors': [{'message_id': 1, 'quote': '喜欢散步'}],
        }
        with self.assertRaisesRegex(ValueError, 'YYYY-MM-DD'):
            extraction.validate_fragments({'fragments': [fragment]}, rows, 7)

    def test_batches_keep_every_message_and_allow_no_new_memories(self):
        rows = [{'id': i, 'content': 'x' * 20} for i in range(5)]
        self.assertEqual([r for batch in extraction.batches(rows, 30) for r in batch], rows)
        self.assertEqual(extraction.validate_fragments({'fragments': []}, [], 7), [])


class ExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_freezes_source_and_does_not_invoke_model(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[{'id': 3, 'role': 'user', 'content': '喜欢安静'}])
        conn.execute = AsyncMock()
        await extraction.enqueue_extraction(conn, 7, 8)
        args = conn.execute.await_args.args
        self.assertEqual((7, 8), args[1:3])
        self.assertEqual('喜欢安静', json.loads(args[3])[0]['content'])

    async def test_completion_writes_fragment_with_anchors_in_transaction(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=1)
        conn.execute = AsyncMock()
        transaction = conn.transaction.return_value
        transaction.__aenter__ = AsyncMock()
        transaction.__aexit__ = AsyncMock()
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock()
        anchor = {'conversation_id': 7, 'message_id': 3, 'role': 'user', 'quote': '喜欢安静'}
        fragment = {'content': '用户喜欢安静。', 'anchors': [anchor]}
        with patch.object(extraction, 'get_pool', AsyncMock(return_value=pool)):
            await extraction.finish_job({'id': 1, 'lease_token': 'owned',
                                         'source_conversation_id': 7}, [fragment, fragment])
        transaction.__aenter__.assert_awaited_once()
        self.assertEqual(2, conn.execute.await_count)  # one fragment + job completion
        metadata = json.loads(conn.execute.await_args_list[0].args[2])
        self.assertEqual('fragment', metadata['entry_kind'])
        self.assertEqual([anchor], metadata['anchors'])
        self.assertIn("status = 'completed'", conn.execute.await_args_list[1].args[0])

    async def test_model_receives_persona_memory_and_evidence_and_returns_anchors(self):
        response = MagicMock()
        response.json.return_value = {'choices': [{'message': {'content': json.dumps({
            'fragments': [{'memory_date': '2026-09-09',
                           'content': '用户想学钢琴。', 'anchors': [
                {'message_id': 4, 'quote': '想学钢琴'}]}],
            'legacy_scores': [{'id': 9, 'importance': .8}],
        }, ensure_ascii=False)}}]}
        client = MagicMock()
        client.post = AsyncMock(return_value=response)
        job = {
            'id': 2, 'source_conversation_id': 7,
            'snapshot': [{'id': 4, 'role': 'user', 'content': '我想学钢琴。'}],
            'legacy_snapshot': [{'id': 9, 'content': '过去的偏好'}],
        }
        with (patch.object(main, '_load_long_term_summary_runtime', AsyncMock(return_value={
            'api_url': 'https://example.test/v1', 'api_key': 'key', 'model': 'extractor',
        })), patch.object(main, 'build_system_prompt', AsyncMock(return_value='主人格及记忆规则')),
            patch.object(main, '_build_standing_memory_prompt', AsyncMock(return_value='已有常驻记忆')),
            patch.object(main, 'get_long_term_memories', AsyncMock(return_value=[])),
            patch.object(main, 'get_http_client', AsyncMock(return_value=client)),
            patch.object(main, '_record_token_usage', AsyncMock())):
            result = await main._extract_conversation_memories(job)
        messages = client.post.await_args.kwargs['json']['messages']
        self.assertIn('主人格及记忆规则', messages[0]['content'])
        self.assertIn('已有常驻记忆', messages[0]['content'])
        self.assertIn('我想学钢琴', messages[1]['content'])
        self.assertIn('default_memory_date', messages[1]['content'])
        self.assertEqual('2026-09-09：用户想学钢琴。', result[0]['content'])
        self.assertEqual(result[0]['anchors'][0]['message_id'], 4)
        self.assertEqual({9: .8}, job['_legacy_scores'])
        self.assertEqual(job['legacy_snapshot'], json.loads(messages[1]['content'])['legacy_unscored'])

    async def test_completed_job_cannot_write_twice(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=None)
        conn.execute = AsyncMock()
        conn.transaction.return_value.__aenter__ = AsyncMock()
        conn.transaction.return_value.__aexit__ = AsyncMock()
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock()
        with patch.object(extraction, 'get_pool', AsyncMock(return_value=pool)):
            await extraction.finish_job({'id': 1, 'lease_token': 'expired'}, [
                {'content': '不得重复写入', 'anchors': []},
            ])
        conn.execute.assert_not_awaited()
