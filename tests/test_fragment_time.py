import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import main
import memory_fragments as fragments


class FragmentTimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_fragment_uses_only_its_own_turns_in_local_time(self):
        turns = [
            dict(id=n, user_id=n-1, user_text='当时', assistant_text='我记得。',
                 recorded_at=datetime(2026, 11, day, 18, 30, tzinfo=timezone.utc))
            for n, day in [(2, 18), (4, 20)]]
        item = dict(content='我记得那场雨。', categories=['日常'])
        model = AsyncMock(return_value=[dict(item, turn_ids=[4]), dict(item, turn_ids=[2])])
        conn = AsyncMock()
        conn.fetch.return_value = []
        with patch.object(fragments.db, 'TIMEZONE_HOURS', 8):
            await fragments.consolidate(conn, turns, model, '1')
        writes = conn.fetchval.await_args_list
        self.assertEqual('2026-11-21 02:30', model.await_args.args[0][1]['recorded_at'])
        self.assertEqual('【2026-11-21 02:30】我记得那场雨。', writes[0].args[1])
        self.assertEqual([3, 4], json.loads(writes[0].args[4])['sources'])
        self.assertEqual('【2026-11-19 02:30】我记得那场雨。', writes[1].args[1])
        self.assertIn(writes[0].args[1], fragments.pack([dict(id=1, content=writes[0].args[1])], 200))

        for ids in [[], [20]]:
            model.return_value = [dict(item, turn_ids=ids)]
            with self.assertRaisesRegex(ValueError, '轮次'):
                await fragments.consolidate(conn, turns, model, '1')

    async def test_review_keeps_earliest_known_time_and_leaves_undated_memory_undated(self):
        conn = AsyncMock()
        dated = dict(id=2, content='【2026-10-01 12:34】我记得。', tags=['日常'], metadata={})
        manual = dict(id=1, content='我记得。', tags=['日常'], metadata={})
        conn.fetch.return_value = [manual, dated]
        item = dict(content='【2099-01-01 00:00】我记得了。', categories=['日常'], turn_ids=[])
        for parents, expected in [([1, 2], '【2026-10-01 12:34】我记得了。'), ([1], '我记得了。')]:
            conn.execute.reset_mock()
            await fragments.consolidate(conn, [], AsyncMock(return_value=[dict(item, merge_ids=parents)]),
                                        'mcp', pending=manual)
            self.assertEqual(expected, conn.execute.await_args_list[0].args[2])

    async def test_edit_keeps_time_unless_explicitly_corrected(self):
        original = '【2026-11-19 12:34】我记得。'
        for text, expected in [('我想起来了。', '【2026-11-19 12:34】我想起来了。'),
                               ('【2026-11-18 12:34】我想起来了。', '【2026-11-18 12:34】我想起来了。')]:
            request = MagicMock(method='PUT')
            request.json = AsyncMock(return_value=dict(original_content=original, original_categories=['日常'],
                                                        content=text, categories=['日常']))
            pool = AsyncMock()
            pool.fetchval.return_value = 1
            with patch.object(main, 'MEMORY_ENABLED', True), patch.object(main.db, 'get_pool', AsyncMock(return_value=pool)):
                await main.change_manual_fragment(1, request)
            self.assertEqual(expected, pool.fetchval.await_args.args[4])
