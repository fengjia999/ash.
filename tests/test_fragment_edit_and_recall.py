import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

import main


class FragmentEditAndRecallTests(unittest.IsolatedAsyncioTestCase):
    async def test_edit_updates_importance_only_when_supplied(self):
        original = dict(original_content='原文', original_categories=['情绪'], content='修订', categories=['日常'])
        pool = AsyncMock()
        with patch.object(main, 'MEMORY_ENABLED', True), patch.object(main.db, 'get_pool', AsyncMock(return_value=pool)):
            async def edit(**fields):
                request = MagicMock(method='PUT', json=AsyncMock(return_value={**original, **fields}))
                return await main.change_manual_fragment(9, request)

            pool.fetchval.return_value = 9
            self.assertEqual(await edit(importance=8, original_importance=3), {'id':9})
            sql, *args = pool.fetchval.await_args.args
            self.assertIn('importance=$6', sql)
            self.assertIn('importance IS NOT DISTINCT FROM $7', sql)
            self.assertEqual(args[-2:], [8, 3])
            await edit()
            self.assertNotIn('importance', pool.fetchval.await_args.args[0])
            pool.fetchval.reset_mock()
            self.assertEqual((await edit(importance=11)).status_code, 400)
            pool.fetchval.assert_not_awaited()
            pool.fetchval.return_value = None
            self.assertEqual((await edit(importance=1, original_importance=8)).status_code, 409)

    async def test_reranker_failure_preserves_candidates_and_explicit_empty_is_respected(self):
        rows = [dict(id=i, content='回忆', tags=['日常'], created_at='2026-11-19') for i in (6, 2, 8, 4)]
        client = AsyncMock()
        runtime = dict(model='test', api_url='https://example.test', api_key='key')
        with patch.object(main, '_load_model_task_runtime', AsyncMock(return_value=runtime)), \
             patch.object(main.fragments, 'search', AsyncMock(return_value=rows)), \
             patch.object(main, 'get_http_client', AsyncMock(return_value=client)):
            for content, reason, expected in [('broken', 'stop', rows[:3]), ('[99]', 'stop', rows[:3]),
                                               ('[]', 'length', rows[:3]), ('[]', 'stop', []),
                                               ('[4, 2]', 'stop', [rows[3], rows[1]])]:
                choice = {'message':{'content':content}, 'finish_reason':reason}
                client.post.return_value = MagicMock(json=lambda: {'choices':[choice]})
                self.assertEqual(await main._rank_fragment_recall('回忆'), expected)
            client.post.side_effect = httpx.ReadTimeout('test timeout')
            self.assertEqual(await main._rank_fragment_recall('回忆'), rows[:3])

            async def slow(*args, **kwargs):
                await asyncio.sleep(60)
            client.post.side_effect = slow
            self.assertEqual(await main._rank_fragment_recall('回忆', deadline=asyncio.get_running_loop().time()+.05), rows[:3])
