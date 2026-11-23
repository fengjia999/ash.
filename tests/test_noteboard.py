import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import main
import database
import noteboard
import test_gateway_backup


class NoteboardTests(unittest.IsolatedAsyncioTestCase):
    def note(self):
        return {"id": 1, "title": "窗边", "content": "花开了。", "author": "assistant", "revision": 2,
                "created_at": datetime(2026, 10, 26, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 10, 26, tzinfo=timezone.utc)}

    async def test_tool_validates_and_creates_assistant_note_without_model_calls(self):
        create = AsyncMock(return_value=self.note())
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(noteboard, "create_note", create):
            for invalid in ({}, {"content": " "}, {"content": "x" * 12001}, {"content": "ok", "title": "x" * 81}):
                self.assertTrue((await main.dispatch_tool_call("create_note", invalid)).startswith("Error:"))
            create.assert_not_awaited()
            result = json.loads(await main.dispatch_tool_call("create_note", {"content": " 花开了。 ", "title": " 窗边 "}))
            self.assertEqual(result, {"id": 1, "title": "窗边", "saved": True})
            self.assertEqual(create.await_args.args[1], "assistant")
            self.assertEqual(create.await_args.args[0].content, "花开了。")
        with patch.object(main, "MEMORY_ENABLED", False), patch.object(noteboard, "create_note", create):
            self.assertIn("not enabled", await main.dispatch_tool_call("create_note", {"content": "x"}))

    def test_tools_are_owned_by_gateway_and_frozen_snapshots_get_one_current_schema(self):
        foreign = [{"type": "function", "function": {"name": "create_note", "description": "other", "parameters": {}}}]
        with patch.object(main, "MEMORY_ENABLED", True):
            tools, frontend = main.merge_frontend_tools(foreign)
            self.assertEqual(sum(t["name"] == "create_note" for t in tools), 1)
            self.assertNotIn("create_note", frontend)
            old = [{"name": "create_note", "description": "old", "input_schema": {}}]
            synced = main._sync_builtin_memory_tools(old)
            self.assertEqual([t for t in synced if t["name"] == "create_note"], noteboard.TOOLS)
            self.assertNotIn("create_note", main._filter_frontend_tool_names(["create_note"]))

    async def test_database_edits_require_revision_and_preserve_author(self):
        conn = MagicMock(); conn.fetchrow = AsyncMock(return_value=self.note())
        conn.fetch = AsyncMock(return_value=[self.note()])
        pool = test_gateway_backup.GatewayBackupTests._pool_with_connection(conn)
        with patch.object(noteboard, "get_pool", AsyncMock(return_value=pool)):
            data = await noteboard.list_notes()
            self.assertEqual(data["notes"][0]["created_at"], "2026-10-26T00:00:00+00:00")
            await noteboard.add_note(noteboard.NoteText(content="我的纸条"))
            self.assertEqual(conn.fetchrow.await_args.args[1:], ("", "我的纸条", "user"))
            await noteboard.edit_note(1, noteboard.NoteEdit(content="后来写的", revision=2))
            query, *args = conn.fetchrow.await_args.args
            self.assertIn("revision=$4", query)
            self.assertNotIn("author=", query)
            self.assertEqual(args, [1, "", "后来写的", 2])
            conn.fetchrow.return_value = None
            response = await noteboard.edit_note(1, noteboard.NoteEdit(content="过期修改", revision=1))
            self.assertEqual(response.status_code, 409)
            response = await noteboard.delete_note(1, 1)
            self.assertEqual(response.status_code, 409)

    async def test_endpoints_use_dashboard_login_csrf_and_validation(self):
        with patch.object(main, "DASHBOARD_PASSWORD", "test"), patch.object(main, "DASHBOARD_COOKIE_SECURE", False):
            cookie, csrf = main._create_dashboard_session()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
                self.assertEqual((await client.get('/api/noteboard')).status_code, 401)
                client.cookies.set(main._DASHBOARD_SESSION_COOKIE, cookie)
                self.assertEqual((await client.post('/api/noteboard', json={"content": "hi"})).status_code, 403)
                client.headers['X-CSRF-Token'] = csrf
                self.assertEqual((await client.post('/api/noteboard', json={"content": " "})).status_code, 422)
                with patch.object(noteboard, "create_note", AsyncMock(return_value=noteboard.public_note(self.note()))) as create:
                    response = await client.post('/api/noteboard', json={"content": "hello", "author": "assistant"})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(create.await_args.args[1], "user")

    def test_backup_includes_note_text_but_not_browser_positions(self):
        self.assertIn("cover_notes", database.GATEWAY_BACKUP_INSERT_ORDER)
        self.assertIn("cover_notes", database.GATEWAY_BACKUP_DELETE_ORDER)
        self.assertNotIn("cover_notes", database.GATEWAY_BACKUP_MESSAGE_SECTIONS)
        self.assertNotIn("x", database.GATEWAY_BACKUP_TABLES["cover_notes"]["columns"])
        self.assertEqual(main.GATEWAY_BACKUP_SCHEMA_VERSION, 21)

    async def test_new_backup_restores_notes_and_legacy_backup_has_empty_notes(self):
        for version in (19, 20, 21):
            note = noteboard.public_note(self.note())
            payload = {"kind": "memory_gateway_backup", "schema_version": version,
                       **{key: [] for key in database.GATEWAY_BACKUP_TABLES}}
            if version >= 20:
                payload["cover_notes"] = [note]
            else:
                del payload["cover_notes"]
            request = MagicMock(); request.json = AsyncMock(return_value=payload)
            restore = AsyncMock(return_value={"cover_notes": int(version >= 20)})
            with patch.object(main, "MEMORY_ENABLED", True), patch.object(main, "restore_gateway_backup_data", restore):
                response = await main.import_memories(request, include_messages=False)
                self.assertEqual(response["status"], "done")
                self.assertEqual(restore.await_args.args[0]["cover_notes"], [note] if version >= 20 else [])
