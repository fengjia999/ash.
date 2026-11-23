import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import database


class RawCopyQuarantineTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_term_initialization_creates_legacy_ledger_after_its_parent_table(self):
        conn = MagicMock(execute=AsyncMock())
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            await database.init_long_term_memory_tables()
        queries = [call.args[0] for call in conn.execute.await_args_list]
        parent_index = next(i for i, sql in enumerate(queries)
                            if "CREATE TABLE IF NOT EXISTS long_term_memories" in sql)
        ledger_index = next(i for i, sql in enumerate(queries)
                            if "CREATE TABLE IF NOT EXISTS raw_memory_ledger" in sql)
        self.assertLess(parent_index, ledger_index)
        self.assertIn("source_key TEXT PRIMARY KEY", queries[ledger_index])
        self.assertIn("REFERENCES long_term_memories(id) ON DELETE SET NULL", queries[ledger_index])
        self.assertTrue(any("ON raw_memory_ledger(memory_id)" in sql for sql in queries))
        self.assertFalse(any("DROP TABLE" in sql for sql in queries))

    async def test_lists_and_counts_exclude_raw_copies(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.fetchrow = AsyncMock(return_value={'memory_count': 0, 'diary_count': 0})
        conn.fetchval = AsyncMock(return_value=0)
        conn.execute = AsyncMock()
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        getters = [database.get_diary_list, database.get_long_term_memories,
                   database.get_long_term_memory_counts,
                   database.get_long_term_memory_catalog]
        with patch.object(database, 'get_pool', AsyncMock(return_value=pool)):
            for getter in getters:
                conn.reset_mock()
                await getter()
                calls = (
                    conn.fetch.await_args_list
                    + conn.fetchrow.await_args_list
                    + conn.fetchval.await_args_list
                )
                self.assertTrue(any("metadata->>'source' IS DISTINCT FROM 'raw_user_quotes'"
                                    in call.args[0] for call in calls), getter.__name__)
                conn.execute.assert_not_awaited()

    def test_removed_worker_cannot_be_enabled_and_backup_keeps_legacy_ledger(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / 'raw_memory.py').exists())
        self.assertNotIn('raw_memory_worker', (root / 'main.py').read_text())
        self.assertIn('raw_memory_ledger', database.GATEWAY_BACKUP_TABLES)
