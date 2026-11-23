import json
import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import database
import diary_monthly as monthly
import main

REQUEST_ID = '7a64c058-f9ca-4f64-931d-1bf8f5461650'


def connection(conn):
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock()
    conn.transaction.return_value.__aenter__ = AsyncMock()
    conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
    return patch.object(database, 'get_pool', AsyncMock(return_value=pool))


class MonthlyTests(unittest.IsolatedAsyncioTestCase):
    def test_month_boundaries_and_invalid_values(self):
        self.assertEqual(monthly.month_range('2026-12'), (date(2026, 12, 1), date(2027, 1, 1)))
        for month in ['2026-00', '2026-13', '0000-01', '26-01', '2026-1', 'invalid']:
            with self.assertRaises(ValueError):
                monthly.month_range(month)

    def test_prompt_keeps_diary_perspectives_and_only_returns_summary(self):
        messages = monthly.messages('2026-10', [
            {'title': '记录', 'content': '我想去旅行', 'metadata': {'author_role': 'user'}},
            {'title': '记录二', 'content': '我记下这件事'},
        ], {'assistant_name': 'Ash', 'user_name': '小明'})
        self.assertIn('你是Ash', messages[0]['content'])
        sources = json.loads(messages[1]['content'])
        self.assertEqual([d['author_role'] for d in sources], ['user', 'assistant'])
        self.assertEqual(monthly.response_text({'choices': [{'message': {'content': ' 本月总结 '}, 'finish_reason': 'stop'}]}), '本月总结')
        for payload in [{}, {'choices': [{'message': {'content': '部分'}, 'finish_reason': 'length'}]},
                        {'choices': [{'message': {'content': ''}, 'finish_reason': 'stop'}]}]:
            with self.assertRaises(ValueError):
                monthly.response_text(payload)

    async def test_running_or_replayed_request_does_not_call_model_again(self):
        for status in ['running', 'completed', 'failed']:
            conn = MagicMock(execute=AsyncMock(), fetchrow=AsyncMock(return_value={
                'month': '2026-10', 'content': '已保存总结', 'request_id': REQUEST_ID,
                'status': status, 'error': '',
            }), fetch=AsyncMock())
            with connection(conn):
                job, sources = await monthly.start('2026-10', REQUEST_ID)
            self.assertIsNone(sources)
            conn.fetch.assert_not_awaited()
            self.assertEqual(job['content'], '已保存总结')

    async def test_full_month_has_no_thirty_diary_cap_and_filters_fragments(self):
        diaries = [{'id': i, 'content': '记录', 'metadata': {'entry_kind': 'diary'}} for i in range(1, 40)]
        conn = MagicMock(execute=AsyncMock(), fetchrow=AsyncMock(side_effect=[None, {
            'month': '2026-10', 'content': '', 'request_id': REQUEST_ID, 'status': 'running', 'error': '',
        }]), fetch=AsyncMock(return_value=diaries + [{'id': 50, 'metadata': {'entry_kind': 'fragment'}}]))
        with connection(conn):
            _, sources = await monthly.start('2026-10', REQUEST_ID)
        self.assertEqual(len(sources), 39)
        self.assertEqual(conn.fetch.call_args.args[1:], (date(2026, 10, 1), date(2026, 11, 1)))

    async def test_generation_failure_keeps_previous_summary(self):
        job = {'month': '2026-10', 'request_id': REQUEST_ID}
        runtime = {'api_url': 'https://example.test', 'api_key': 'test', 'model': 'test'}
        with patch.object(main, '_identity_presets_for_background_prompt', AsyncMock(side_effect=TimeoutError)), patch.object(
            monthly, 'finish', AsyncMock()
        ) as finish, patch.object(main, '_record_token_usage', AsyncMock()):
            await main._run_diary_month(job, [], runtime)
        self.assertIsNone(finish.call_args.args[2])
        self.assertIn('超时', finish.call_args.args[3])

    async def test_persona_long_wait_and_save_retry_do_not_repeat_paid_call(self):
        job = {'month': '2026-10', 'request_id': REQUEST_ID}
        runtime = {'api_url': 'https://example.test/v1', 'api_key': 'test', 'model': 'test'}
        response = MagicMock()
        response.json.return_value = {'choices': [{'message': {'content': '这个月，我们约好了下次旅行。'}, 'finish_reason': 'stop'}]}
        client = MagicMock(post=AsyncMock(return_value=response))
        with patch.object(main, '_identity_presets_for_background_prompt', AsyncMock(return_value={
            'assistant_name': 'Ash', 'user_name': '小明'
        })), patch.object(main, 'build_system_prompt', AsyncMock(return_value='主人格：我是{{assistant_name}}，熟悉{{user_name}}。')), patch.object(
            main, 'get_http_client', AsyncMock(return_value=client)
        ), patch.object(monthly, 'finish', AsyncMock(side_effect=[RuntimeError('db unavailable'), None])) as finish, patch.object(
            main, '_record_token_usage', AsyncMock()
        ), patch.object(main.asyncio, 'sleep', AsyncMock()):
            await main._run_diary_month(job, [], runtime)
        client.post.assert_awaited_once()
        sent = client.post.call_args.kwargs
        self.assertEqual(sent['timeout'].read, 900)
        self.assertGreater(monthly.JOB_LEASE_SECONDS, monthly.JOB_TIMEOUT_SECONDS)
        self.assertGreater(monthly.JOB_TIMEOUT_SECONDS, sent['timeout'].read)
        system = sent['json']['messages'][0]['content']
        self.assertTrue(system.startswith('主人格：我是Ash，熟悉小明。'))
        self.assertIn('正在总结Ash和小明', system)
        self.assertIn('有纪念意义', system)
        self.assertIn('互动偏好和细节也尽量保留', system)
        self.assertEqual(finish.await_count, 2)
        self.assertEqual(finish.call_args.args[2], '这个月，我们约好了下次旅行。')
        self.assertEqual(finish.call_args.args[3], '')
