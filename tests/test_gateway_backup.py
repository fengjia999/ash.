import unittest
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import database
import main


BACKUP_SECTIONS = {
    section: []
    for section in database.GATEWAY_BACKUP_TABLES
}


class GatewayBackupTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _pool_with_connection(conn):
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock(return_value=None)
        transaction.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=transaction)
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=acquire)
        return pool

    async def test_export_contains_standing_memory_and_conversations(self):
        data = {
            **BACKUP_SECTIONS,
            "standing_memory_blocks": [{"id": 1, "content": "core"}],
            "conversations": [{"id": 7, "name": "会话"}],
            "context_messages": [{"id": 9, "conversation_id": 7}],
        }
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "export_gateway_backup_data", AsyncMock(return_value=data)
        ):
            response = await main.export_memories()
            result = json.loads(response.body)

        self.assertEqual("memory_gateway_backup", result["kind"])
        self.assertEqual(9, result["schema_version"])
        self.assertEqual(data["standing_memory_blocks"], result["standing_memory_blocks"])
        self.assertEqual(data["conversations"], result["conversations"])
        self.assertEqual(data["context_messages"], result["context_messages"])
        self.assertNotIn("session_archives", result)
        self.assertNotIn("conversation_summaries", result)
        self.assertIn(
            "memory-gateway-backup.json",
            response.headers["content-disposition"],
        )

    async def test_full_backup_import_uses_atomic_restore_path(self):
        request = MagicMock()
        payload = {
            "kind": "memory_gateway_backup",
            "schema_version": 2,
            **BACKUP_SECTIONS,
        }
        request.json = AsyncMock(return_value=payload)
        restore = AsyncMock(return_value={
            "standing_memory_blocks": 3,
            "conversations": 2,
            "context_messages": 18,
        })

        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "restore_gateway_backup_data", restore
        ):
            result = await main.import_memories(request)

        self.assertEqual("memory_gateway_backup", result["kind"])
        self.assertEqual(3, result["restored"]["standing_memory_blocks"])
        restore.assert_awaited_once_with(payload)

    async def test_unknown_full_backup_version_is_rejected(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "kind": "memory_gateway_backup",
            "schema_version": 999,
        })

        with patch.object(main, "MEMORY_ENABLED", True):
            response = await main.import_memories(request)

        self.assertEqual(400, response.status_code)

    async def test_current_backup_version_is_accepted(self):
        request = MagicMock()
        payload = {
            "kind": "memory_gateway_backup",
            "schema_version": 9,
            **BACKUP_SECTIONS,
        }
        request.json = AsyncMock(return_value=payload)
        restore = AsyncMock(return_value={})

        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "restore_gateway_backup_data", restore
        ):
            result = await main.import_memories(request)

        self.assertEqual("done", result["status"])
        restore.assert_awaited_once_with(payload)

    async def test_restore_requires_every_core_section(self):
        incomplete = {
            section: []
            for section in database.GATEWAY_BACKUP_TABLES
            if section != "standing_memory_blocks"
        }

        with self.assertRaisesRegex(ValueError, "standing_memory_blocks"):
            await database.restore_gateway_backup_data(incomplete)

    def test_dashboard_distinguishes_full_backup_from_legacy_import(self):
        root = Path(__file__).resolve().parents[1]
        script = (
            root / "static" / "js" / "dashboard.js"
        ).read_text(encoding="utf-8")
        dashboard = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn('parsed.kind === "memory_gateway_backup"', script)
        self.assertIn(
            "SUPPORTED_BACKUP_SCHEMA_VERSIONS = [2, 3, 4, 5, 6, 7, 8, 9]",
            script,
        )
        self.assertIn(
            "SUPPORTED_BACKUP_SCHEMA_VERSIONS.includes(parsed.schema_version)",
            script,
        )
        self.assertIn("不支持的完整备份版本", script)
        self.assertIn("完整恢复会覆盖当前提示词、记忆、后台任务和全部会话", script)
        self.assertIn('window.location.assign("/export/memories")', script)
        self.assertNotIn("token=", script)
        self.assertNotIn('data-section="archives"', dashboard)
        self.assertNotIn('id="section-archives"', dashboard)
        self.assertIn('class="nav-item active" data-section="conversations"', dashboard)
        self.assertIn('class="tab active" data-tab="json">完整恢复', dashboard)
        self.assertIn('data-tab="text">旧碎片', dashboard)
        self.assertIn("提示词 · 记忆 · 后台任务 · 会话", dashboard)
        self.assertIn("导入碎片录", dashboard)

    def test_backup_uses_context_page_handoff_summaries(self):
        conversation_columns = database.GATEWAY_BACKUP_TABLES["conversations"]["columns"]
        self.assertIn("handoff_draft", conversation_columns)
        self.assertIn("handoff_summary", conversation_columns)
        self.assertNotIn("conversation_summaries", database.GATEWAY_BACKUP_TABLES)
        self.assertNotIn("session_archives", database.GATEWAY_BACKUP_TABLES)

    def test_backup_contains_long_term_memory_section(self):
        spec = database.GATEWAY_BACKUP_TABLES["long_term_memories"]
        self.assertEqual("long_term_memories", spec["table"])
        self.assertEqual(
            (
                "id", "title", "keywords", "summary", "content", "memory_date",
                "priority", "enabled", "metadata", "created_at",
            ),
            spec["columns"],
        )
        self.assertIn("memory_date", spec["columns"])
        self.assertIn("metadata", spec["columns"])
        self.assertIn("created_at", spec["columns"])
        self.assertNotIn("updated_at", spec["columns"])

        pending_spec = database.GATEWAY_BACKUP_TABLES["long_term_memory_proposals"]
        self.assertEqual("long_term_memory_proposals", pending_spec["table"])
        self.assertIn("summary", pending_spec["columns"])
        self.assertIn("operation", pending_spec["columns"])
        self.assertIn("target_memory_id", pending_spec["columns"])

    def test_backup_contains_prompts_background_jobs_and_forgetting_queue(self):
        prompt_spec = database.GATEWAY_BACKUP_TABLES["prompt_sections"]
        self.assertIn("content", prompt_spec["columns"])
        self.assertFalse(prompt_spec["sequence"])

        extraction_spec = database.GATEWAY_BACKUP_TABLES["memory_extraction_jobs"]
        self.assertIn("snapshot", extraction_spec["json"])
        self.assertIn("legacy_snapshot", extraction_spec["json"])

        forgetting_spec = database.GATEWAY_BACKUP_TABLES["fragment_forgetting_pending"]
        self.assertEqual("memory_id ASC", forgetting_spec["order_by"])
        self.assertFalse(forgetting_spec["sequence"])

        self.assertLess(
            database.GATEWAY_BACKUP_DELETE_ORDER.index("fragment_forgetting_pending"),
            database.GATEWAY_BACKUP_DELETE_ORDER.index("long_term_memories"),
        )
        self.assertLess(
            database.GATEWAY_BACKUP_INSERT_ORDER.index("long_term_memories"),
            database.GATEWAY_BACKUP_INSERT_ORDER.index("fragment_forgetting_pending"),
        )

    async def test_export_supports_backup_tables_without_an_id_column(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        pool = self._pool_with_connection(conn)

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            result = await database.export_gateway_backup_data()

        self.assertEqual(set(database.GATEWAY_BACKUP_TABLES), set(result))
        queries = [call.args[0] for call in conn.fetch.await_args_list]
        self.assertTrue(any("FROM prompt_sections ORDER BY priority DESC, section_key ASC" in query
                            for query in queries))
        self.assertTrue(any("FROM fragment_forgetting_pending ORDER BY memory_id ASC" in query
                            for query in queries))

    async def test_restore_requeues_in_progress_extraction_jobs(self):
        conn = MagicMock()
        conn.execute = AsyncMock(return_value="OK")
        conn.fetch = AsyncMock(return_value=[])
        conn.fetchval = AsyncMock(return_value=8)
        pool = self._pool_with_connection(conn)

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            await database.restore_gateway_backup_data(dict(BACKUP_SECTIONS))

        queries = [call.args[0] for call in conn.execute.await_args_list]
        requeue = next(query for query in queries
                       if "UPDATE memory_extraction_jobs" in query and "lease_token = NULL" in query)
        self.assertIn("status = 'pending'", requeue)
        self.assertNotIn("string_agg", "\n".join(queries))

    async def test_version_8_restore_initializes_new_backup_sections(self):
        request = MagicMock()
        payload = {
            "kind": "memory_gateway_backup",
            "schema_version": 8,
            **{
                section: []
                for section in database.GATEWAY_BACKUP_TABLES
                if section not in main.GATEWAY_BACKUP_V9_SECTIONS
            },
        }
        request.json = AsyncMock(return_value=payload)
        restore = AsyncMock(return_value={})

        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "restore_gateway_backup_data", restore
        ):
            result = await main.import_memories(request)

        self.assertEqual("done", result["status"])
        restored_payload = restore.await_args.args[0]
        for section in main.GATEWAY_BACKUP_V9_SECTIONS:
            self.assertEqual([], restored_payload[section])


if __name__ == "__main__":
    unittest.main()
