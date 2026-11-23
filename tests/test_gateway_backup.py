import unittest
import json
from pathlib import Path
from datetime import datetime, timezone
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

    async def test_export_omits_captures_and_preserves_saved_prompts(self):
        tables = {
            "conversation_extra_prompts": [{"id": 2, "source_id": 1, "content": "保存的内容"}],
            "extra_prompt_presets": [{"id": 3, "content": "预设"}],
        }
        async def cursor(query, **kwargs):
            table = query.split(" FROM ")[1].split()[0]
            self.assertNotEqual(table, "conversation_prompt_sources")
            for row in tables.get(table, []):
                yield row
        conn = MagicMock(cursor=MagicMock(side_effect=cursor), fetchval=AsyncMock(return_value=0))
        for include_messages in (False, True):
            with self.subTest(include_messages=include_messages), patch.object(
                database, "get_pool", AsyncMock(return_value=self._pool_with_connection(conn))
            ):
                rows = [item async for item in database.iter_gateway_backup_data(include_messages)]
            self.assertIn(("conversation_prompt_sources", None), rows)
            self.assertFalse(any(section == "conversation_prompt_sources" and row is not None for section, row in rows))
            saved = next(row for section, row in rows if section == "conversation_extra_prompts" and row)
            self.assertEqual(saved["content"], "保存的内容")
            self.assertIsNone(saved["source_id"])
            self.assertIn(("extra_prompt_presets", tables["extra_prompt_presets"][0]), rows)
        self.assertEqual(tables["conversation_extra_prompts"][0]["source_id"], 1)

    async def test_previous_v22_captures_and_saved_links_still_restore(self):
        payload = {**BACKUP_SECTIONS, "schema_version": 22,
                   "conversation_prompt_sources": [{"id": 1, "conversation_id": 7,
                       "content": "旧捕获", "content_hash": "abc", "configured": True}],
                   "conversation_extra_prompts": [{"id": 2, "conversation_id": 7,
                       "source_id": 1, "content": "保存的内容"}]}
        conn = MagicMock(execute=AsyncMock(), executemany=AsyncMock(), fetchval=AsyncMock(return_value=0))
        with patch.object(database, "get_pool", AsyncMock(return_value=self._pool_with_connection(conn))), patch.object(
            database, "_promote_flow_memory_overflow", AsyncMock()
        ):
            result = await database.restore_gateway_backup_data(payload)
        self.assertEqual(result["conversation_prompt_sources"], 1)
        self.assertEqual(result["conversation_extra_prompts"], 1)
        for call in conn.executemany.call_args_list:
            if call.args[0].startswith("INSERT INTO conversation_extra_prompts "):
                row = dict(zip(database.GATEWAY_BACKUP_TABLES["conversation_extra_prompts"]["columns"], call.args[1][0]))
                self.assertEqual(row["source_id"], 1)
                self.assertEqual(row["content"], "保存的内容")

    async def test_monthly_summary_restore_preserves_text_without_replaying_job(self):
        conn = MagicMock(executemany=AsyncMock())
        row = {'month': '2026-10', 'content': '十月的约定与偏好。',
               'request_id': '7a64c058-f9ca-4f64-931d-1bf8f5461650', 'status': 'running',
               'source_ids': [7], 'error': '', 'updated_at': '2026-10-31T12:00:00Z'}
        await database._restore_backup_section(conn, 'diary_monthly_summaries', [row])
        values = conn.executemany.call_args.args[1][0]
        restored = dict(zip(database.GATEWAY_BACKUP_TABLES['diary_monthly_summaries']['columns'], values))
        self.assertEqual(restored['content'], row['content'])
        self.assertEqual(restored['status'], 'completed')
        self.assertNotEqual(str(restored['request_id']), row['request_id'])
        self.assertEqual(json.loads(restored['source_ids']), [7])

    async def test_version_21_without_monthly_summaries_is_accepted_and_clears_old_summary(self):
        payload = {**BACKUP_SECTIONS, 'schema_version': 21}
        payload.pop('diary_monthly_summaries')
        conn = MagicMock(execute=AsyncMock(), executemany=AsyncMock(), fetchval=AsyncMock(return_value=0))
        with patch.object(database, 'get_pool', AsyncMock(return_value=self._pool_with_connection(conn))), patch.object(
            database, '_promote_flow_memory_overflow', AsyncMock()
        ):
            restored = await database.restore_gateway_backup_data(payload)
        self.assertEqual(restored['diary_monthly_summaries'], 0)
        self.assertIn('DELETE FROM diary_monthly_summaries', [c.args[0] for c in conn.execute.call_args_list])

    async def test_version_22_requires_monthly_section_before_database_access(self):
        payload = {**BACKUP_SECTIONS, 'schema_version': 22}
        payload.pop('diary_monthly_summaries')
        with patch.object(database, 'get_pool', AsyncMock()) as pool:
            with self.assertRaisesRegex(ValueError, 'diary_monthly_summaries'):
                await database.restore_gateway_backup_data(payload)
            pool.assert_not_awaited()

    async def test_export_contains_standing_memory_and_conversations(self):
        fragment = {
            "id": 12,
            "title": "",
            "content": "一条碎片记忆",
            "metadata": {
                "entry_kind": "fragment",
                "anchors": [{"message_id": 9, "quote": "完整原话"}],
            },
        }
        data = {
            **BACKUP_SECTIONS,
            "diary_monthly_summaries": [{"month": "2026-10", "content": "十月回顾"}],
            "standing_memory_blocks": [{"id": 1, "content": "core"}],
            "long_term_memories": [fragment],
            "conversations": [{"id": 7, "name": "会话"}],
            "context_messages": [{"id": 9, "conversation_id": 7}],
        }
        async def rows(**kwargs):
            yield "total", len(data["memories"])
            for section, section_rows in data.items():
                yield section, None
                for row in section_rows:
                    yield section, row

        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "iter_gateway_backup_data", rows
        ):
            response = await main.export_memories()
            result = json.loads("".join([chunk async for chunk in response.body_iterator]))

        self.assertEqual("memory_gateway_backup", result["kind"])
        self.assertEqual(22, result["schema_version"])
        self.assertEqual(data["diary_monthly_summaries"], result["diary_monthly_summaries"])
        self.assertEqual(data["standing_memory_blocks"], result["standing_memory_blocks"])
        self.assertEqual([fragment], result["long_term_memories"])
        self.assertEqual(
            "完整原话",
            result["long_term_memories"][0]["metadata"]["anchors"][0]["quote"],
        )
        self.assertEqual(data["conversations"], result["conversations"])
        self.assertEqual(data["context_messages"], result["context_messages"])
        self.assertEqual(len(data["memories"]), result["total"])
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
            result = await main.import_memories(request, include_messages=True)

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
            "schema_version": 16,
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

    async def test_version_15_prompt_sources_are_not_reinjected(self):
        payload = {
            "kind": "memory_gateway_backup",
            "schema_version": 15,
            **BACKUP_SECTIONS,
            "conversation_prompt_sources": [{
                "id": 3,
                "conversation_id": 7,
                "content": "old capture",
                "content_hash": "abc",
                "first_seen_at": None,
            }],
        }
        request = MagicMock(json=AsyncMock(return_value=payload))
        restore = AsyncMock(return_value={})

        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "restore_gateway_backup_data", restore,
        ):
            result = await main.import_memories(request, include_messages=True)

        self.assertEqual("done", result["status"])
        source = restore.await_args.args[0]["conversation_prompt_sources"][0]
        self.assertFalse(source["configured"])
        self.assertTrue(source["initial_injected"])
        self.assertIsNone(source["initial_message_id"])

    async def test_old_backup_adds_empty_raw_memory_ledger(self):
        payload = {key: value for key, value in BACKUP_SECTIONS.items() if key != 'raw_memory_ledger'}
        payload.update(kind='memory_gateway_backup', schema_version=11)
        request = MagicMock()
        request.json = AsyncMock(return_value=payload)
        restore = AsyncMock(return_value={})
        with patch.object(main, 'MEMORY_ENABLED', True), patch.object(main, 'restore_gateway_backup_data', restore):
            result = await main.import_memories(request)
        self.assertEqual('done', result['status'])
        self.assertEqual([], restore.await_args.args[0]['raw_memory_ledger'])

    async def test_restore_creates_missing_ledger_before_delete_and_preserves_legacy_rows(self):
        ledger_exists = False
        events = []
        async def execute(sql, *args):
            nonlocal ledger_exists
            if "CREATE TABLE IF NOT EXISTS raw_memory_ledger" in sql:
                ledger_exists = True
                events.append("create ledger")
            elif sql.startswith("DELETE FROM raw_memory_ledger"):
                if not ledger_exists:
                    raise database.asyncpg.UndefinedTableError('relation "raw_memory_ledger" does not exist')
                events.append("clear ledger")
        async def executemany(sql, values):
            if "INSERT INTO long_term_memories" in sql:
                events.append("restore memories")
            if "INSERT INTO raw_memory_ledger" in sql:
                if not ledger_exists:
                    raise database.asyncpg.UndefinedTableError('relation "raw_memory_ledger" does not exist')
                events.append("restore ledger")
        conn = MagicMock(execute=AsyncMock(side_effect=execute), executemany=AsyncMock(side_effect=executemany))
        pool = self._pool_with_connection(conn)
        rows = [{"source_key": "message:7:9", "memory_id": 4, "created_at": "2026-10-12T00:00:00Z"},
                {"source_key": "job:3", "memory_id": None, "created_at": "2026-10-12T00:00:00Z"}]
        payload = {**BACKUP_SECTIONS, "raw_memory_ledger": rows,
                   "long_term_memories": [{"id": 4, "content": "旧记忆"}]}
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(
            database, "_reset_backup_sequence", AsyncMock()
        ), patch.object(database, "_promote_flow_memory_overflow", AsyncMock()):
            result = await database.restore_gateway_backup_data(payload)
        self.assertEqual(["create ledger", "clear ledger", "restore memories", "restore ledger"], events)
        self.assertEqual(2, result["raw_memory_ledger"])
        insert = next(call for call in conn.executemany.await_args_list
                      if "INSERT INTO raw_memory_ledger" in call.args[0])
        self.assertEqual(["message:7:9", "job:3"], [row[0] for row in insert.args[1]])
        self.assertEqual([4, None], [row[1] for row in insert.args[1]])
        self.assertIsNone(conn.transaction.return_value.__aexit__.await_args.args[0])

    async def test_ledger_creation_failure_does_not_start_deleting_data(self):
        async def execute(sql, *args):
            if "CREATE TABLE IF NOT EXISTS raw_memory_ledger" in sql:
                raise database.asyncpg.InsufficientPrivilegeError("permission denied")
        conn = MagicMock(execute=AsyncMock(side_effect=execute))
        pool = self._pool_with_connection(conn)
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            with self.assertRaises(database.asyncpg.InsufficientPrivilegeError):
                await database.restore_gateway_backup_data(BACKUP_SECTIONS)
        self.assertFalse(any("DELETE FROM" in call.args[0] for call in conn.execute.await_args_list))
        self.assertIs(database.asyncpg.InsufficientPrivilegeError,
                      conn.transaction.return_value.__aexit__.await_args.args[0])

    async def test_export_missing_ledger_outputs_empty_section_without_aborting_snapshot(self):
        conn = MagicMock(execute=AsyncMock(), fetchval=AsyncMock(side_effect=[0, False]))
        async def cursor(sql, **kwargs):
            if "FROM raw_memory_ledger" in sql:
                raise database.asyncpg.UndefinedTableError('relation "raw_memory_ledger" does not exist')
            if "FROM long_term_memories " in sql:
                yield {"id": 4, "content": "日记保留"}
        conn.cursor = MagicMock(side_effect=cursor)
        pool = self._pool_with_connection(conn)
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(main, "MEMORY_ENABLED", True):
            response = await main.export_memories(include_messages=False)
            payload = json.loads("".join([part async for part in response.body_iterator]))
        self.assertEqual([], payload["raw_memory_ledger"])
        self.assertEqual("日记保留", payload["long_term_memories"][0]["content"])
        conn.execute.assert_not_awaited()

    async def test_export_existing_ledger_preserves_rows_and_deleted_memory_markers(self):
        conn = MagicMock(fetchval=AsyncMock(side_effect=[0, True]))
        rows = [{"source_key": "old-message", "memory_id": 4, "created_at": None},
                {"source_key": "deleted-message", "memory_id": None, "created_at": None}]
        async def cursor(sql, **kwargs):
            if "FROM raw_memory_ledger " in sql:
                for row in rows:
                    yield row
        conn.cursor = MagicMock(side_effect=cursor)
        pool = self._pool_with_connection(conn)
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(main, "MEMORY_ENABLED", True):
            response = await main.export_memories()
            payload = json.loads("".join([part async for part in response.body_iterator]))
        self.assertEqual(rows, payload["raw_memory_ledger"])

    async def test_restore_requires_every_core_section(self):
        incomplete = {
            section: []
            for section in database.GATEWAY_BACKUP_TABLES
            if section != "standing_memory_blocks"
        }

        with self.assertRaisesRegex(ValueError, "standing_memory_blocks"):
            await database.restore_gateway_backup_data(incomplete)

    async def test_legacy_backup_preserves_settings_it_did_not_contain(self):
        payload = {**BACKUP_SECTIONS, "schema_version": 20}
        for section in database.GATEWAY_BACKUP_V21_SETTINGS:
            del payload[section]
        conn = MagicMock(execute=AsyncMock(), executemany=AsyncMock(), fetchval=AsyncMock(return_value=0))
        pool = self._pool_with_connection(conn)
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(
            database, "_promote_flow_memory_overflow", AsyncMock()
        ):
            restored = await database.restore_gateway_backup_data(payload)
        queries = [call.args[0] for call in conn.execute.await_args_list]
        for section in database.GATEWAY_BACKUP_V21_SETTINGS:
            self.assertNotIn(section, restored)
            self.assertNotIn("DELETE FROM " + section, queries)

    async def test_new_backup_requires_both_settings_before_accessing_database(self):
        for section in database.GATEWAY_BACKUP_V21_SETTINGS:
            payload = {**BACKUP_SECTIONS, "schema_version": 21}
            del payload[section]
            with patch.object(database, "get_pool", AsyncMock()) as get_pool:
                with self.assertRaisesRegex(ValueError, section):
                    await database.restore_gateway_backup_data(payload)
                get_pool.assert_not_awaited()

    async def test_restores_settings_before_promoting_flow_overflow(self):
        payload = {**BACKUP_SECTIONS, "schema_version": 21,
                   "identity_presets": [{"id": 1, "user_name": "我", "assistant_name": "小灰"}],
                   "flow_memory_settings": [{"id": 1, "max_items": 37}]}
        conn = MagicMock(execute=AsyncMock(), executemany=AsyncMock(), fetchval=AsyncMock(return_value=0))
        pool = self._pool_with_connection(conn)

        async def promote(connection):
            inserts = {call.args[0].split()[2]: call.args[1] for call in connection.executemany.await_args_list}
            self.assertEqual("小灰", inserts["identity_presets"][0][2])
            self.assertEqual(37, inserts["flow_memory_settings"][0][1])

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(
            database, "_promote_flow_memory_overflow", AsyncMock(side_effect=promote)
        ):
            restored = await database.restore_gateway_backup_data(payload)
        self.assertEqual(1, restored["identity_presets"])
        self.assertEqual(1, restored["flow_memory_settings"])

    async def test_default_import_omits_messages_and_repairs_references_in_old_full_backup(self):
        payload = {
            **BACKUP_SECTIONS, "kind": "memory_gateway_backup", "schema_version": 18,
            "backup_options": {"include_messages": True},
            "conversations": [{"id": 7, "name": "旧会话", "handoff_summary": "保留的交接摘要",
                               "temporary_summary": "保留的窗口摘要", "handoff_message_ids": "[9]",
                               "handoff_summary_through_message_id": 9,
                               "temporary_summary_through_message_id": 9,
                               "heartbeat_last_user_message_id": 9, "heartbeat_count": 3,
                               "temporary_summary_claim_token": "stale"}],
            "context_messages": [{"id": 9, "conversation_id": 7, "content": "大量原文"}],
            "conversation_prompt_sources": [{"id": 1, "content": "配置的提示词", "configured": True,
                                             "initial_message_id": 9, "initial_injected": True}],
            "conversation_extra_prompts": [{"id": 2, "content": "额外提示词", "injection_count": 10}],
            "conversation_extra_prompt_injections": [{"message_id": 9}],
            "long_term_memories": [{"id": 3, "content": "保留的日记"}],
        }
        request = MagicMock(json=AsyncMock(return_value=payload))
        restore = AsyncMock(return_value={"context_messages": 0})
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(main, "restore_gateway_backup_data", restore):
            result = await main.import_memories(request)
        self.assertEqual("done", result["status"])
        imported = restore.await_args.args[0]
        self.assertEqual([], imported["context_messages"])
        self.assertEqual([], imported["conversation_extra_prompt_injections"])
        conversation = imported["conversations"][0]
        self.assertEqual("保留的交接摘要", conversation["handoff_summary"])
        self.assertEqual("保留的窗口摘要", conversation["temporary_summary"])
        self.assertEqual([], conversation["handoff_message_ids"])
        for key in ("handoff_summary_through_message_id", "temporary_summary_through_message_id",
                    "heartbeat_last_user_message_id", "temporary_summary_claim_token"):
            self.assertIsNone(conversation[key])
        self.assertEqual(0, conversation["heartbeat_count"])
        source = imported["conversation_prompt_sources"][0]
        self.assertIsNone(source["initial_message_id"])
        self.assertTrue(source["initial_injected"])
        self.assertTrue(source["configured"])
        self.assertEqual("配置的提示词", source["content"])
        self.assertEqual(0, imported["conversation_extra_prompts"][0]["injection_count"])
        self.assertEqual(payload["long_term_memories"], imported["long_term_memories"])
        self.assertEqual(9, payload["conversation_prompt_sources"][0]["initial_message_id"])
        # Explicit full restore remains available for migration and recovery.
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(main, "restore_gateway_backup_data", restore):
            await main.import_memories(request, include_messages=True)
        self.assertEqual(payload, restore.await_args.args[0])

    async def test_lightweight_export_never_reads_history_tables_and_can_be_imported(self):
        tables = {
            "identity_presets": [{"id": 1, "user_name": "我", "assistant_name": "小灰"}],
            "flow_memory_settings": [{"id": 1, "max_items": 37}],
            "cover_notes": [{"id": 18, "title": "便签", "content": "下次见 👀", "author": "assistant", "revision": 2}],
            "conversations": [{"id": 7, "name": "会话", "handoff_summary": "交接摘要",
                               "handoff_message_ids": [9], "heartbeat_last_user_message_id": 9}],
            "conversation_prompt_sources": [{"id": 1, "configured": True, "initial_message_id": 9,
                                             "initial_injected": True}],
            "long_term_memories": [{"id": 2, "content": "日记"}],
            "context_messages": [{"id": 9, "content": "不应读取的原文"}],
            "conversation_extra_prompt_injections": [{"id": 3, "message_id": 9}],
        }
        conn = MagicMock(fetchval=AsyncMock(return_value=0))
        async def cursor(query, **kwargs):
            table = query.split(" FROM ")[1].split()[0]
            if table in database.GATEWAY_BACKUP_MESSAGE_SECTIONS:
                self.fail("lightweight export must not query historical messages")
            for row in tables.get(table, []):
                yield row
        conn.cursor = MagicMock(side_effect=cursor)
        pool = self._pool_with_connection(conn)
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(main, "MEMORY_ENABLED", True):
            response = await main.export_memories(include_messages=False)
            payload = json.loads("".join([part async for part in response.body_iterator]))
        self.assertFalse(payload["backup_options"]["include_messages"])
        self.assertEqual([], payload["context_messages"])
        self.assertEqual([], payload["conversation_extra_prompt_injections"])
        self.assertEqual("交接摘要", payload["conversations"][0]["handoff_summary"])
        self.assertEqual([], payload["conversations"][0]["handoff_message_ids"])
        self.assertEqual([], payload["conversation_prompt_sources"])
        self.assertEqual(tables["long_term_memories"], payload["long_term_memories"])
        for section in ("identity_presets", "flow_memory_settings", "cover_notes"):
            self.assertEqual(tables[section], payload[section])
        self.assertTrue(set(database.GATEWAY_BACKUP_TABLES).issubset(payload))
        restore = AsyncMock(return_value={"context_messages": 0})
        request = MagicMock(json=AsyncMock(return_value=payload))
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(main, "restore_gateway_backup_data", restore):
            result = await main.import_memories(request)
        self.assertEqual("done", result["status"])
        self.assertEqual([], restore.await_args.args[0]["context_messages"])

    async def test_omitting_history_does_not_hide_incomplete_backup_sections(self):
        payload = {**BACKUP_SECTIONS}
        del payload["conversations"]
        filtered = database.gateway_backup_without_messages(payload)
        with self.assertRaisesRegex(ValueError, "conversations"):
            await database.restore_gateway_backup_data(filtered)

    def test_dashboard_distinguishes_full_backup_from_legacy_import(self):
        root = Path(__file__).resolve().parents[1]
        script = (
            root / "static" / "js" / "dashboard.js"
        ).read_text(encoding="utf-8")
        dashboard = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn('parsed.kind === "memory_gateway_backup"', script)
        self.assertIn(
            "SUPPORTED_BACKUP_SCHEMA_VERSIONS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]",
            script,
        )
        self.assertIn(
            "SUPPORTED_BACKUP_SCHEMA_VERSIONS.includes(parsed.schema_version)",
            script,
        )
        self.assertIn("不支持的完整备份版本", script)
        self.assertIn("完整恢复会覆盖当前提示词、记忆、备份中包含的设置、后台任务和全部会话", script)
        self.assertIn('byId("export-download-frame").src = "/export/memories?include_messages=" + includeMessages', script)
        self.assertIn('/api/export-progress/', script)
        self.assertNotIn("token=", script)
        self.assertNotIn('data-section="archives"', dashboard)
        self.assertNotIn('id="section-archives"', dashboard)
        self.assertIn('id="section-conversations"', dashboard)
        self.assertIn('<h2>完整恢复</h2>', dashboard)
        self.assertIn('id="tab-json" class="tab-panel active"', dashboard)
        self.assertNotIn('data-tab="text">旧碎片', dashboard)
        self.assertIn("提示词 · 记忆 · 后台任务 · 会话", dashboard)
        self.assertNotIn("导入碎片录", dashboard)
        self.assertNotIn("碎片记忆", dashboard)
        self.assertIn('metadata.entry_kind !== "fragment"', script)
        self.assertNotIn("standingData.overview || {}).fragment_count", script)

    def test_backup_uses_context_page_handoff_summaries(self):
        conversation_columns = database.GATEWAY_BACKUP_TABLES["conversations"]["columns"]
        self.assertIn("handoff_draft", conversation_columns)
        self.assertIn("handoff_summary", conversation_columns)
        self.assertIn("temporary_summary_trigger_tokens", conversation_columns)
        self.assertEqual(
            8000,
            database.GATEWAY_BACKUP_TABLES["conversations"]["defaults"]
            ["temporary_summary_trigger_tokens"],
        )
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

    def test_backup_contains_prompts(self):
        prompt_spec = database.GATEWAY_BACKUP_TABLES["prompt_sections"]
        self.assertIn("content", prompt_spec["columns"])
        self.assertFalse(prompt_spec["sequence"])

    async def test_export_supports_backup_tables_without_an_id_column(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=0)
        async def empty_cursor():
            if False:
                yield None
        conn.cursor = MagicMock(side_effect=lambda *args, **kwargs: empty_cursor())
        pool = self._pool_with_connection(conn)

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            result = [item async for item in database.iter_gateway_backup_data()]

        self.assertEqual(set(database.GATEWAY_BACKUP_TABLES), {section for section, _ in result} - {"total"})
        queries = [call.args[0] for call in conn.cursor.call_args_list]
        self.assertTrue(any("FROM prompt_sections ORDER BY priority DESC, section_key ASC" in query
                            for query in queries))
        self.assertTrue(all(call.kwargs["prefetch"] == 128 for call in conn.cursor.call_args_list))
        conn.fetch.assert_not_called()

    async def test_database_export_keeps_fragment_content_and_anchors(self):
        fragment = {
            "id": 12,
            "title": "",
            "keywords": [],
            "summary": "",
            "content": "一条碎片记忆",
            "memory_date": None,
            "priority": 0,
            "enabled": True,
            "metadata": {
                "entry_kind": "fragment",
                "anchors": [{"message_id": 9, "quote": "完整原话"}],
            },
            "created_at": None,
        }
        conn = MagicMock()

        async def fetch(query):
            if "FROM long_term_memories" in query:
                return [fragment]
            return []

        async def cursor(query, prefetch):
            for row in await fetch(query):
                yield row
        conn.cursor = MagicMock(side_effect=cursor)
        conn.fetchval = AsyncMock(return_value=0)
        pool = self._pool_with_connection(conn)

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            result = [item async for item in database.iter_gateway_backup_data()]

        fragments = [row for section, row in result if section == "long_term_memories" and row is not None]
        self.assertEqual([fragment], fragments)
        self.assertEqual(
            "完整原话",
            fragments[0]["metadata"]["anchors"][0]["quote"],
        )

    async def test_streaming_export_does_not_read_a_table_before_response_consumption(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=1)
        consumed = []

        async def cursor(query, prefetch):
            if "FROM memories " in query:
                consumed.append("read")
                yield {"id": 1, "content": "中文", "created_at": datetime(2026, 9, 29, tzinfo=timezone.utc)}

        conn.cursor = MagicMock(side_effect=cursor)
        pool = self._pool_with_connection(conn)
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(main, "MEMORY_ENABLED", True):
            response = await main.export_memories()
            self.assertEqual([], consumed)
            body = "".join([part async for part in response.body_iterator])

        self.assertEqual(["read"], consumed)
        self.assertEqual("中文", json.loads(body)["memories"][0]["content"])
        self.assertEqual("2026-09-29T00:00:00+00:00", json.loads(body)["memories"][0]["created_at"])
        self.assertEqual(1, json.loads(body)["total"])


    async def test_old_backup_clears_stale_extraction_queue(self):
        payload = {"kind": "memory_gateway_backup", "schema_version": 17,
                   **{key: [] for key in database.GATEWAY_BACKUP_TABLES if key != "nocturne_extraction_jobs"}}
        request = MagicMock(json=AsyncMock(return_value=payload))
        restore = AsyncMock(return_value={})
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(main, "restore_gateway_backup_data", restore):
            result = await main.import_memories(request)
        self.assertEqual("done", result["status"])
        self.assertEqual([], restore.await_args.args[0]["nocturne_extraction_jobs"])

    async def test_restore_retains_job_provenance_and_invalidates_inflight_claim(self):
        job = {"flow_memory_id": 31, "source_key": "ash-job-stable", "summary": "摘要",
               "items": [{"content": "记忆"}], "next_index": 2, "status": "processing", "attempts": 2,
               "retry_at": None, "updated_at": None}
        conn = MagicMock(execute=AsyncMock(), executemany=AsyncMock())
        pool = self._pool_with_connection(conn)
        data = {**BACKUP_SECTIONS, "nocturne_extraction_jobs": [job]}
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(
            database, "_reset_backup_sequence", AsyncMock()
        ), patch.object(database, "_promote_flow_memory_overflow", AsyncMock()):
            result = await database.restore_gateway_backup_data(data)
        self.assertEqual(1, result["nocturne_extraction_jobs"])
        calls = conn.execute.await_args_list
        self.assertEqual(database.NOCTURNE_EXTRACTION_LOCK, calls[1].args[1])
        insert = next(call for call in conn.executemany.await_args_list if "INSERT INTO nocturne_extraction_jobs" in call.args[0])
        self.assertEqual("ash-job-stable", insert.args[1][0][1])
        self.assertEqual([{"content": "记忆"}], json.loads(insert.args[1][0][3]))
        self.assertNotIn("lease_token", insert.args[0])
        self.assertTrue(any("lease_token = NULL" in call.args[0] and "WHERE status = 'processing'" in call.args[0] for call in calls))

    async def test_large_message_restore_batches_without_losing_content_or_types(self):
        conn = MagicMock(execute=AsyncMock(), executemany=AsyncMock())
        rows = [{"id": i, "conversation_id": 7, "role": "user", "content": f"原文 {i}",
                 "created_at": "2026-10-12T12:30:00Z", "content_json": [{"text": f"原文 {i}"}],
                 "hidden": False, "affects_activity": True} for i in range(405)]
        result = await database._restore_backup_section(conn, "context_messages", rows)
        self.assertEqual(405, result)
        batches = [call.args[1] for call in conn.executemany.await_args_list]
        self.assertEqual([200, 200, 5], [len(batch) for batch in batches])
        restored = [values for batch in batches for values in batch]
        self.assertEqual(list(range(405)), [values[0] for values in restored])
        for i, values in enumerate(restored):
            self.assertEqual(f"原文 {i}", values[3])
            self.assertEqual(datetime(2026, 10, 12, 12, 30, tzinfo=timezone.utc), values[4])
            self.assertEqual([{"text": f"原文 {i}"}], json.loads(values[5]))
            self.assertEqual([None, False, True], values[6:])
        conn.execute.assert_not_awaited()

    async def test_deferred_parent_links_are_restored_after_all_rows(self):
        conn = MagicMock(executemany=AsyncMock())
        rows = [{"id": 2, "parent_id": 1}, {"id": 1, "parent_id": None}]
        await database._restore_backup_section(conn, "standing_memory_blocks", rows)
        calls = conn.executemany.await_args_list
        self.assertEqual(2, len(calls))
        self.assertIn("INSERT INTO standing_memory_blocks", calls[0].args[0])
        self.assertNotIn("parent_id", calls[0].args[0])
        self.assertIn("UPDATE standing_memory_blocks SET parent_id", calls[1].args[0])
        self.assertEqual([(1, 2)], calls[1].args[1])

    async def test_lock_timeout_exits_transaction_before_any_data_is_deleted(self):
        async def execute(sql, *args):
            if "pg_advisory_xact_lock" in sql:
                raise database.asyncpg.LockNotAvailableError("lock timeout")
        conn = MagicMock(execute=AsyncMock(side_effect=execute))
        pool = self._pool_with_connection(conn)
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            with self.assertRaisesRegex(ValueError, "30 秒.*回滚"):
                await database.restore_gateway_backup_data(BACKUP_SECTIONS)
        self.assertFalse(any("DELETE FROM" in call.args[0] for call in conn.execute.await_args_list))
        error_type = conn.transaction.return_value.__aexit__.await_args.args[0]
        self.assertIs(database.asyncpg.LockNotAvailableError, error_type)

    async def test_failed_batch_unwinds_transaction_and_does_not_report_success(self):
        conn = MagicMock(execute=AsyncMock(), executemany=AsyncMock(side_effect=RuntimeError("invalid row")))
        pool = self._pool_with_connection(conn)
        payload = {**BACKUP_SECTIONS, "context_messages": [{"id": 7}]}
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            with self.assertRaisesRegex(RuntimeError, "invalid row"):
                await database.restore_gateway_backup_data(payload)
        self.assertIs(RuntimeError, conn.transaction.return_value.__aexit__.await_args.args[0])

    async def test_total_deadline_cancels_write_and_unwinds_transaction(self):
        import asyncio
        real_timeout = asyncio.timeout
        async def slow_write(*args):
            await asyncio.sleep(1)
        conn = MagicMock(execute=AsyncMock(), executemany=AsyncMock(side_effect=slow_write))
        pool = self._pool_with_connection(conn)
        payload = {**BACKUP_SECTIONS, "context_messages": [{"id": 7}]}
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(
            database.asyncio, "timeout", side_effect=lambda seconds: real_timeout(.01)
        ):
            with self.assertRaisesRegex(ValueError, "10 分钟.*核对数据"):
                await database.restore_gateway_backup_data(payload)
        self.assertIs(asyncio.CancelledError, conn.transaction.return_value.__aexit__.await_args.args[0])


class StreamingBackupLifecycleTests(unittest.IsolatedAsyncioTestCase):
    _pool_with_connection = staticmethod(GatewayBackupTests._pool_with_connection)
    async def test_export_batches_utf8_chunks_without_changing_backup_contents(self):
        records = [{"id": i, "content": "中文正文" * 20} for i in range(2000)]
        records.insert(0, {"id": -1, "content": "长消息" * 30000})
        consumed = []
        async def rows(**kwargs):
            yield "total", len(records)
            yield "memories", None
            for row in records:
                consumed.append(row["id"])
                yield "memories", row
        sent = []
        async def send(message):
            if message["type"] == "http.response.start":
                self.assertEqual([], consumed)
            sent.append(message)
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(main, "iter_gateway_backup_data", rows):
            response = await main.export_memories()
            await response.stream_response(send)
        chunks = [message["body"] for message in sent if message["type"] == "http.response.body"]
        self.assertLess(len(chunks), 20)
        self.assertEqual(records, json.loads(b"".join(chunks))["memories"])
        self.assertLessEqual(sum(len(chunk) > 64 * 1024 for chunk in chunks), 1)
        self.assertEqual("no", response.headers["x-accel-buffering"])
        self.assertIn("no-transform", response.headers["cache-control"])

    async def test_disconnect_during_batched_send_releases_database_snapshot(self):
        conn = MagicMock(fetchval=AsyncMock(return_value=10000))
        consumed = []
        async def cursor(*args, **kwargs):
            for i in range(10000):
                consumed.append(i)
                yield {"id": i, "content": "x" * 1024}
        conn.cursor = MagicMock(side_effect=cursor)
        pool = self._pool_with_connection(conn)
        bodies = 0
        async def send(message):
            nonlocal bodies
            if message["type"] == "http.response.body":
                bodies += 1
                if bodies == 2:
                    raise OSError("download disconnected")
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(main, "MEMORY_ENABLED", True):
            response = await main.export_memories()
            with self.assertRaises(OSError):
                await response.stream_response(send)
        self.assertLess(len(consumed), 128)
        conn.transaction.return_value.__aexit__.assert_awaited_once()
        pool.acquire.return_value.__aexit__.assert_awaited_once()

    # Only the lifecycle cases below need a real ASGI send/disconnect sequence.
    async def test_disconnect_closes_snapshot_and_releases_connection(self):
        import asyncio
        import anyio
        sent = asyncio.Event()
        conn = MagicMock(fetchval=AsyncMock(return_value=0))
        pool = self._pool_with_connection(conn)
        cleanup = []

        async def transaction_exit(*args):
            await anyio.sleep(0)
            cleanup.append('transaction')

        async def acquire_exit(*args):
            await anyio.sleep(0)
            cleanup.append('connection')

        conn.transaction.return_value.__aexit__.side_effect = transaction_exit
        pool.acquire.return_value.__aexit__.side_effect = acquire_exit

        async def send(message):
            if message['type'] == 'http.response.body':
                sent.set()
                await anyio.sleep_forever()

        async def receive():
            await sent.wait()
            return {'type': 'http.disconnect'}

        with patch.object(database, 'get_pool', AsyncMock(return_value=pool)), patch.object(main, 'MEMORY_ENABLED', True):
            response = await main.export_memories()
            await asyncio.wait_for(response({'type': 'http'}, receive, send), 1)
        self.assertEqual(['transaction', 'connection'], cleanup)
        conn.transaction.assert_called_once_with(isolation='repeatable_read', readonly=True)
        conn.cursor.assert_not_called()

    async def test_initial_database_error_does_not_send_success_headers(self):
        conn = MagicMock(fetchval=AsyncMock(side_effect=RuntimeError('unavailable')))
        pool = self._pool_with_connection(conn)
        send = AsyncMock()
        with patch.object(database, 'get_pool', AsyncMock(return_value=pool)), patch.object(main, 'MEMORY_ENABLED', True):
            response = await main.export_memories()
            with self.assertRaises(RuntimeError):
                await response.stream_response(send)
        send.assert_not_awaited()
        conn.transaction.return_value.__aexit__.assert_awaited_once()
        pool.acquire.return_value.__aexit__.assert_awaited_once()

    async def test_send_error_closes_database_iterator_immediately(self):
        closed = []

        async def rows(**kwargs):
            try:
                yield 'total', 0
                yield 'memories', None
            finally:
                closed.append(True)

        async def send(message):
            if message['type'] == 'http.response.body':
                raise OSError('disconnected')

        with patch.object(main, 'iter_gateway_backup_data', rows), patch.object(main, 'MEMORY_ENABLED', True):
            response = await main.export_memories()
            with self.assertRaises(OSError):
                await response.stream_response(send)
        self.assertEqual([True], closed)

    async def test_database_error_leaves_incomplete_json_and_closes_snapshot(self):
        conn = MagicMock(fetchval=AsyncMock(return_value=1))

        async def cursor(*args, **kwargs):
            yield {'id': 1, 'content': 'first'}
            raise RuntimeError('query failed')

        conn.cursor = MagicMock(side_effect=cursor)
        pool = self._pool_with_connection(conn)
        chunks = []
        with patch.object(database, 'get_pool', AsyncMock(return_value=pool)), patch.object(main, 'MEMORY_ENABLED', True):
            response = await main.export_memories()
            with self.assertRaises(RuntimeError):
                async for chunk in response.body_iterator:
                    chunks.append(chunk)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(''.join(chunks))
        conn.transaction.return_value.__aexit__.assert_awaited_once()
        pool.acquire.return_value.__aexit__.assert_awaited_once()

    async def test_streamed_backup_roundtrips_through_existing_import(self):
        data = {**BACKUP_SECTIONS, 'memories': [
            {'id': 1, 'content': '中文"\\\n'}, {'id': 2, 'content': 'second'}],
            'identity_presets': [{'id': 1, 'user_name': '我', 'assistant_name': '小灰'}],
            'flow_memory_settings': [{'id': 1, 'max_items': 37}],
            'cover_notes': [{'id': 18, 'title': '便签', 'content': '下次见 👀', 'author': 'assistant', 'revision': 2}],
            'context_messages': [{'id': 3, 'conversation_id': 4, 'content_json': [{'type': 'text', 'text': '原文'}]}]}

        async def rows(**kwargs):
            yield 'total', 2
            for section, values in data.items():
                yield section, None
                for value in values:
                    yield section, value

        with patch.object(main, 'iter_gateway_backup_data', rows), patch.object(main, 'MEMORY_ENABLED', True):
            response = await main.export_memories()
            payload = json.loads(''.join([chunk async for chunk in response.body_iterator]))
            restore = AsyncMock(return_value={})
            request = MagicMock(json=AsyncMock(return_value=payload))
            with patch.object(main, 'restore_gateway_backup_data', restore):
                result = await main.import_memories(request, include_messages=True)
        self.assertEqual('done', result['status'])
        for section, values in data.items():
            self.assertEqual(values, restore.await_args.args[0][section])
        script = Path('static/js/dashboard.js').read_text()
        import re
        versions = json.loads(re.search(r'SUPPORTED_BACKUP_SCHEMA_VERSIONS = (\[[^;]+\])', script).group(1))
        self.assertIn(payload['schema_version'], versions)

    async def test_partial_consumption_does_not_prefetch_whole_table(self):
        consumed = []
        conn = MagicMock(fetchval=AsyncMock(return_value=10000))

        async def cursor(*args, **kwargs):
            for i in range(10000):
                consumed.append(i)
                yield {'id': i}

        conn.cursor = MagicMock(side_effect=cursor)
        pool = self._pool_with_connection(conn)
        with patch.object(database, 'get_pool', AsyncMock(return_value=pool)), patch.object(main, 'MEMORY_ENABLED', True):
            response = await main.export_memories()
            while not consumed:
                await anext(response.body_iterator)
            self.assertEqual([0], consumed)
            await response.body_iterator.aclose()
        conn.transaction.return_value.__aexit__.assert_awaited_once()
        pool.acquire.return_value.__aexit__.assert_awaited_once()


class BackupProgressTests(unittest.IsolatedAsyncioTestCase):
    _pool_with_connection = staticmethod(GatewayBackupTests._pool_with_connection)

    def setUp(self):
        import backup_progress
        import uuid
        self.enterContext(patch.dict(backup_progress._exports, {}, clear=True))
        self.export_id = uuid.uuid4().hex
        self.request = MagicMock()
        self.request.state.dashboard_session = {"nonce": "session-a"}

    async def test_progress_survives_query_failure_without_exposing_sql(self):
        import backup_progress
        conn = MagicMock(fetchval=AsyncMock(side_effect=database.asyncpg.QueryCanceledError("private SQL and secret")))
        pool = self._pool_with_connection(conn)
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(main, "MEMORY_ENABLED", True):
            response = await main.export_memories(export_id=self.export_id, request=self.request)
            with self.assertRaises(database.asyncpg.QueryCanceledError):
                await response.stream_response(AsyncMock())
        progress = backup_progress.get_export(self.export_id, "session-a")
        self.assertEqual("failed", progress["status"])
        self.assertEqual("counting", progress["section"])
        self.assertEqual("QueryCanceledError", progress["error"])
        self.assertNotIn("secret", json.dumps(progress))
        self.assertIsNone(backup_progress.get_export(self.export_id, "session-b"))
        conn.transaction.return_value.__aexit__.assert_awaited_once()

    async def test_progress_is_readable_while_counting_and_after_disconnect(self):
        import asyncio
        import backup_progress
        entered = asyncio.Event()
        async def blocked_query(*args):
            entered.set()
            await asyncio.Future()
        conn = MagicMock(fetchval=AsyncMock(side_effect=blocked_query))
        pool = self._pool_with_connection(conn)
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(main, "MEMORY_ENABLED", True):
            response = await main.export_memories(export_id=self.export_id, request=self.request)
            task = asyncio.create_task(response.stream_response(AsyncMock()))
            await asyncio.wait_for(entered.wait(), 1)
            progress = await main.api_export_progress(self.export_id, self.request)
            self.assertEqual("counting", json.loads(progress.body)["section"])
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual("interrupted", backup_progress.get_export(self.export_id, "session-a")["status"])
        pool.acquire.return_value.__aexit__.assert_awaited_once()

    async def test_completed_progress_tracks_rows_and_sent_bytes(self):
        import backup_progress
        conn = MagicMock(fetchval=AsyncMock(return_value=1))
        async def cursor(query, **kwargs):
            if "FROM memories " in query:
                yield {"id": 1, "content": "正文"}
        conn.cursor = MagicMock(side_effect=cursor)
        pool = self._pool_with_connection(conn)
        send = AsyncMock()
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(main, "MEMORY_ENABLED", True):
            response = await main.export_memories(export_id=self.export_id, request=self.request)
            await response.stream_response(send)
        progress = backup_progress.get_export(self.export_id, "session-a")
        bodies = [call.args[0]["body"] for call in send.await_args_list if call.args[0]["type"] == "http.response.body"]
        self.assertEqual("completed", progress["status"])
        self.assertEqual(2, progress["rows"])
        self.assertEqual(sum(map(len, bodies)), progress["bytes_sent"])
        self.assertEqual("正文", json.loads(b"".join(bodies))["memories"][0]["content"])
        self.assertEqual([{"id": 1, "max_items": database.FLOW_MEMORY_DEFAULT_MAX_ITEMS, "updated_at": None}],
                         json.loads(b"".join(bodies))["flow_memory_settings"])

    def test_progress_storage_is_bounded_and_expires(self):
        import backup_progress
        for i in range(33):
            backup_progress.start_export(str(i), "session-a")
        self.assertEqual(32, len(backup_progress._exports))
        self.assertIsNone(backup_progress.get_export("0", "session-a"))
        backup_progress._exports["32"].started -= 3601
        self.assertIsNone(backup_progress.get_export("32", "session-a"))

    async def test_browser_can_request_the_same_download_url_again(self):
        import backup_progress
        async def rows(**options):
            yield "total", 0
            yield "memories", None
        with patch.object(main, "iter_gateway_backup_data", rows), patch.object(main, "MEMORY_ENABLED", True):
            for _ in range(2):
                response = await main.export_memories(export_id=self.export_id, request=self.request)
                self.assertIsInstance(response, main.BackupStreamingResponse)
                send = AsyncMock()
                await response.stream_response(send)
                bodies = [call.args[0]["body"] for call in send.await_args_list
                          if call.args[0]["type"] == "http.response.body"]
                self.assertEqual([], json.loads(b"".join(bodies))["memories"])
                self.assertEqual("completed", backup_progress.get_export(self.export_id, "session-a")["status"])

    def test_repeated_download_has_independent_progress_and_keeps_session_privacy(self):
        import backup_progress
        earlier = backup_progress.start_export(self.export_id, "session-a")
        latest = backup_progress.start_export(self.export_id, "session-a")
        latest.status = "completed"
        latest.bytes_sent = 123
        earlier.status = "interrupted"
        earlier.bytes_sent = 1
        self.assertEqual("completed", backup_progress.get_export(self.export_id, "session-a")["status"])
        self.assertEqual(123, backup_progress.get_export(self.export_id, "session-a")["bytes_sent"])
        with self.assertRaises(ValueError):
            backup_progress.start_export(self.export_id, "session-b")
        self.assertIsNone(backup_progress.get_export(self.export_id, "session-b"))
        self.assertIs(backup_progress._exports[self.export_id], latest)


if __name__ == "__main__":
    unittest.main()
