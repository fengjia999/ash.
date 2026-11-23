import asyncio
import copy
import json
import unittest
from unittest.mock import AsyncMock, patch

import main
import httpx


class McpSettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.server = {"id": "one", "name": "Memory", "url": "https://example.com/mcp",
                       "bearer_token": "secret", "enabled": True}
        self.registry = [patch.object(main, name, copy.deepcopy(getattr(main, name)))
                         for name in ("_mcp_tools_anthropic", "_mcp_tools_raw", "_mcp_tool_to_server", "_mcp_status")]
        for patcher in self.registry:
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_empty_saved_configuration_does_not_restore_environment(self):
        with patch.object(main, "get_mcp_settings", AsyncMock(return_value=[])):
            self.assertEqual([], await main._effective_mcp_servers())
        with patch.object(main, "get_mcp_settings", AsyncMock(return_value=None)), patch.object(
            main, "MCP_SERVER_CONFIGS", [self.server]
        ):
            self.assertEqual("secret", (await main._effective_mcp_servers())[0]["bearer_token"])

    def test_token_preserve_replace_clear_and_redaction(self):
        item = {**self.server, "bearer_token": ""}
        normalized = main._normalize_mcp_settings([item], [self.server])
        self.assertEqual("secret", normalized[0]["bearer_token"])
        public = main._public_mcp_servers(normalized)
        self.assertTrue(public[0]["token_configured"])
        self.assertNotIn("secret", json.dumps(public))
        self.assertEqual("new", main._normalize_mcp_settings([{**item, "bearer_token": "new"}], [self.server])[0]["bearer_token"])
        self.assertEqual("", main._normalize_mcp_settings([{**item, "clear_token": True}], [self.server])[0]["bearer_token"])

    def test_invalid_configs_rejected(self):
        for items in (None, [self.server, self.server], [{**self.server, "enabled": "false"}],
                      [{**self.server, "url": "file:///tmp/tool"}],
                      [{**self.server, "url": "https://user:secret@example.com/mcp"}],
                      [{**self.server, "bearer_token": "a\nb"}]):
            with self.subTest(items=items), self.assertRaises(ValueError):
                main._normalize_mcp_settings(items, [])

    async def test_reload_publishes_complete_registry_and_skips_disabled(self):
        main._mcp_tools_anthropic = [{"name": "old"}]
        entered, release = asyncio.Event(), asyncio.Event()

        async def discover(config, **kwargs):
            entered.set()
            await release.wait()
            return [{"name": "new", "inputSchema": {"type": "object"}}]

        with patch.object(main, "_init_single_mcp", side_effect=discover) as probe:
            task = asyncio.create_task(main._reload_mcp_tools([
                self.server, {**self.server, "id": "off", "enabled": False}
            ]))
            await entered.wait()
            self.assertEqual([{"name": "old"}], main._mcp_tools_anthropic)
            release.set()
            await task
            probe.assert_awaited_once()
        self.assertEqual(["new"], list(main._mcp_tool_to_server))

    async def test_reload_preserves_existing_snapshot_but_updates_new_conversations(self):
        old = {"name": "old_external", "input_schema": {"type": "object"}}
        conv = {"id": 1, "last_anthropic_tools": [old], "last_frontend_tool_names": []}
        original = copy.deepcopy(conv)

        async def freeze(conv_id, tools, names):
            return tools, names

        with patch.object(main, "_init_single_mcp", AsyncMock(return_value=[{"name": "new_external"}])), patch.object(
            main, "freeze_conversation_tool_snapshot", side_effect=freeze
        ), patch.object(main, "MEMORY_ENABLED", False):
            await main._reload_mcp_tools([self.server])
            self.assertEqual(original, conv)
            frozen, _ = await main.resolve_conversation_tool_snapshot(conv, [])
            self.assertEqual([old], [tool for tool in frozen if tool["name"] == "old_external"])
            self.assertNotIn("new_external", [tool["name"] for tool in frozen])
            fresh, _ = await main.resolve_conversation_tool_snapshot({"id": 2}, [])
            self.assertIn("new_external", [tool["name"] for tool in fresh])
            self.assertNotIn("old_external", [tool["name"] for tool in fresh])
            self.assertIn("no MCP server", await main.call_mcp_tool("old_external", {}))

    async def test_save_persists_before_reloading_and_returns_no_tokens(self):
        request = AsyncMock()
        request.json.return_value = {"servers": [self.server]}
        with patch.object(main, "_mcp_settings_lock", asyncio.Lock()), patch.object(
            main, "get_mcp_settings", AsyncMock(return_value=[])
        ), patch.object(main, "save_mcp_settings", AsyncMock()) as save, patch.object(
            main, "_init_single_mcp", AsyncMock(return_value=[{"name": "tool"}])
        ):
            result = await main.api_save_mcp_settings(request)
            save.assert_awaited_once_with([self.server])
            self.assertEqual(["tool"], result["servers"][0]["status"]["tools"])
            self.assertNotIn("secret", json.dumps(result))

    async def test_connection_failure_and_conflict_visible(self):
        with patch.object(main, "_init_single_mcp", AsyncMock(side_effect=ValueError("初始化失败：HTTP 401"))):
            await main._reload_mcp_tools([self.server])
        self.assertIn("401", main._mcp_status["one"]["error"])
        self.assertEqual([], main._mcp_tools_anthropic)
        with patch.object(main, "_init_single_mcp", AsyncMock(return_value=[{"name": "same"}])):
            await main._reload_mcp_tools([self.server, {**self.server, "id": "two"}])
        self.assertEqual(1, len(main._mcp_tools_anthropic))
        self.assertTrue(main._mcp_status["two"]["error"])

    async def test_test_connection_does_not_persist_or_change_registry(self):
        request = AsyncMock()
        request.json.return_value = {**self.server, "bearer_token": ""}
        original = copy.deepcopy(main._mcp_tools_anthropic)
        with patch.object(main, "get_mcp_settings", AsyncMock(return_value=[self.server])), patch.object(
            main, "save_mcp_settings", AsyncMock()
        ) as save, patch.object(main, "_init_single_mcp", AsyncMock(return_value=[])) as probe:
            self.assertEqual({"tools": []}, await main.api_test_mcp_settings(request))
            self.assertEqual("secret", probe.call_args.args[0]["bearer_token"])
            save.assert_not_awaited()
        self.assertEqual(original, main._mcp_tools_anthropic)


class McpRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_route_is_registered_and_requires_dashboard_session(self):
        transport = httpx.ASGITransport(app=main.app)
        with patch.object(main, "DASHBOARD_PASSWORD", "test-password"), patch.object(
            main, "get_mcp_settings", AsyncMock(return_value=[])
        ):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                self.assertEqual(401, (await client.get("/api/mcp-settings")).status_code)
                with patch.object(main, "_verify_dashboard_session", return_value={"csrf": "test"}):
                    response = await client.get("/api/mcp-settings")
                    self.assertEqual(200, response.status_code)
                    self.assertEqual({"servers": []}, response.json())
                    self.assertEqual(403, (await client.put("/api/mcp-settings", json={"servers": []})).status_code)
