import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import main
import memory_fragments as fragments


class FragmentPinTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_skips_pinned_pending_and_rechecks_locked_candidates(self):
        conn = AsyncMock()
        conn.fetchval.return_value = None
        conn.fetchrow.return_value = None
        complete = AsyncMock()
        self.assertFalse(await fragments.process(conn, 3, complete))
        self.assertIn('pinned IS NOT TRUE', conn.fetchrow.await_args.args[0])
        complete.assert_not_awaited()

        pending = dict(id=7, content='待整理', tags=['日常'], metadata={})
        conn.fetch.return_value = [pending]
        for parents in ([7, 8], [8, 7]):
            complete.return_value = [dict(content='合并', categories=['日常'], merge_ids=parents)]
            with self.assertRaisesRegex(ValueError, '合并来源无效'):
                await fragments.consolidate(conn, [], complete, 'mcp', pending)
            self.assertEqual([7], [item['id'] for item in complete.await_args.args[1]])
            conn.execute.assert_not_awaited()
        # A pin can commit between candidate selection and acquiring the row lock.
        stages = conn.fetch.await_args.args[0].split('SELECT id,content,tags,metadata')
        self.assertTrue(all('pinned IS NOT TRUE' in stage for stage in stages))

    async def test_manual_changes_allow_pin_and_still_check_for_conflicts(self):
        for method in ('PUT', 'DELETE'):
            request = MagicMock(method=method)
            request.json = AsyncMock(return_value=dict(original_content='原文', original_categories=['日常'],
                                                       content='修订', categories=['计划']))
            pool = AsyncMock()
            pool.fetchval.return_value = 7
            with patch.object(main, 'MEMORY_ENABLED', True), patch.object(main.db, 'get_pool', AsyncMock(return_value=pool)):
                self.assertEqual(await main.change_manual_fragment(7, request), {'id':7})
                sql = pool.fetchval.await_args.args[0]
                self.assertNotIn('pinned', sql)
                self.assertIn('content=$2 AND tags=$3', sql)
                self.assertIn("NOT metadata ? 'merged_into'", sql)
                pool.fetchval.return_value = None
                response = await main.change_manual_fragment(7, request)
            self.assertEqual(409, response.status_code)

    async def test_pin_conflict_is_reported_to_client(self):
        request = MagicMock()
        request.json = AsyncMock(return_value=dict(pinned=True, original_content='旧版本', original_categories=['日常']))
        with patch.object(main, 'update_memory_pin', AsyncMock(return_value=None)) as write:
            response = await main.api_toggle_pin(7, request)
        self.assertEqual(409, response.status_code)
        write.assert_awaited_once_with(7, True, '旧版本', ['日常'])
