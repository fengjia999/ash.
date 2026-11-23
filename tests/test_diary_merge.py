import json
import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import database
import diary_merge


def source(memory_id, day='2026-09-12'):
    return dict(id=memory_id, title='一天', content=f'原文{memory_id}', summary='',
                keywords=['关键词'], memory_date=date.fromisoformat(day),
                priority=0, enabled=True, metadata={})


class DiaryMergeTests(unittest.IsolatedAsyncioTestCase):
    def test_snapshot_matches_database_json_and_loaded_diary(self):
        raw = {**source(1), 'keywords': '["海边", "朋友"]', 'metadata': '{}'}
        loaded = {**raw, 'keywords': ['海边', '朋友'], 'metadata': {}, 'summary': '海边；朋友'}
        self.assertEqual(diary_merge.snapshot(raw), diary_merge.snapshot(loaded))

    async def test_approval_accepts_persisted_preview_with_raw_json_columns(self):
        rows = [{**source(i), 'keywords': '["海边", "朋友"]', 'metadata': '{}'} for i in (1, 2)]
        sources = [diary_merge.snapshot({**row, 'keywords': ['海边', '朋友'],
                                        'metadata': {}, 'summary': '海边；朋友'}) for row in rows]
        # Persist/reload as proposal JSONB, as in the real preview/approval path.
        sources = json.loads(json.dumps(sources))
        proposal = dict(id=10, title='合并', content='完整正文', keywords='["海边", "朋友"]',
                        summary='', memory_date=date(2026, 9, 12))
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=rows)
        conn.fetchrow = AsyncMock(return_value=source(3))
        conn.execute = AsyncMock()
        result = await diary_merge.apply_merge(conn, proposal, sources)
        self.assertEqual(result.get('operation'), 'merge', result)
        self.assertEqual(json.loads(conn.fetchrow.await_args.args[-1])['merge_sources'], sources)

    def test_same_day_validation_and_legacy_date(self):
        self.assertEqual(diary_merge.validate_sources([source(1), source(2)]), '2026-09-12')
        for rows in ([source(1)], [source(1), source(1)],
                     [source(1), source(2, '2026-09-11')],
                     [source(1), {**source(2), 'metadata': {'entry_kind': 'fragment'}}]):
            with self.assertRaises(ValueError):
                diary_merge.validate_sources(rows)
        self.assertEqual(diary_merge.diary_day({'title': '2026-09-12 晚上'}), '2026-09-12')

    async def test_approval_preserves_sources_and_checks_concurrent_changes(self):
        rows = [source(1), source(2)]
        sources = [diary_merge.snapshot(row) for row in rows]
        proposal = dict(id=10, title='合并', content='连贯正文', keywords=['关键词'],
                        summary='', memory_date=date(2026, 9, 12))
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=rows)
        conn.fetchrow = AsyncMock(return_value={**source(3), 'content': '连贯正文'})
        conn.execute = AsyncMock()
        result = await diary_merge.apply_merge(conn, proposal, sources)
        self.assertEqual(result['operation'], 'merge')
        self.assertIn("$3::jsonb, '', $4", conn.fetchrow.await_args.args[0])
        saved_metadata = json.loads(conn.fetchrow.await_args.args[-1])
        self.assertEqual(saved_metadata['merge_sources'], sources)
        self.assertEqual('diary', saved_metadata['entry_kind'])
        self.assertEqual(conn.execute.await_args_list[0].args[1], [1, 2])
        conn.fetchrow.reset_mock()
        conn.execute.reset_mock()
        for changed in ([rows[0]], [rows[0], {**rows[1], 'content': '刚修改'}],
                        [rows[0], {**rows[1], 'keywords': ['新关键词']} ]):
            conn.fetch.return_value = changed
            result = await diary_merge.apply_merge(conn, proposal, sources)
            self.assertIn('error', result)
            conn.fetchrow.assert_not_awaited()
            conn.execute.assert_not_awaited()

    async def test_existing_approval_routes_merge_inside_transaction(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={'metadata': {'merge_sources': []}})
        conn.transaction.return_value.__aenter__ = AsyncMock()
        conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(database, 'get_pool', AsyncMock(return_value=pool)), patch.object(
            diary_merge, 'apply_merge', AsyncMock(return_value={'operation': 'merge'})
        ) as merge:
            await database.apply_pending_long_term_memory_operation(10)
            merge.assert_awaited_once()
            conn.transaction.return_value.__aenter__.assert_awaited_once()
