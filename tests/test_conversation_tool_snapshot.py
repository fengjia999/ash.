import unittest
from unittest.mock import AsyncMock, patch

import main


class ConversationToolSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_request_freezes_merged_tools(self):
        conv = {
            "id": 7,
            "last_anthropic_tools": None,
            "last_frontend_tool_names": None,
        }
        merged = [
            {"name": "read_diary", "input_schema": {"type": "object"}},
            {"name": "search_forum", "input_schema": {"type": "object"}},
            {"name": "frontend_effect", "input_schema": {"type": "object"}},
        ]
        frontend_tools = [{
            "type": "function",
            "function": {
                "name": "frontend_effect",
                "parameters": {"type": "object"},
            },
        }]

        freeze = AsyncMock(return_value=(merged, ["frontend_effect"]))
        with (
            patch.object(main, "MEMORY_ENABLED", True),
            patch.object(main, "merge_frontend_tools", return_value=(merged, {"frontend_effect"})),
            patch.object(main, "freeze_conversation_tool_snapshot", freeze),
        ):
            tools, frontend_names = await main.resolve_conversation_tool_snapshot(
                conv, frontend_tools
            )

        self.assertEqual(
            [*main.BUILTIN_MEMORY_TOOLS, *main.noteboard.TOOLS, *main.BUILTIN_PROMPT_TOOLS,
             *main.BUILTIN_HISTORY_TOOLS, *main.BUILTIN_NOTIFICATION_TOOLS, *merged[1:]],
            tools,
        )
        self.assertEqual({"frontend_effect"}, frontend_names)
        freeze.assert_awaited_once_with(7, merged, ["frontend_effect"])
        self.assertEqual(tools, conv["last_anthropic_tools"])

    async def test_existing_snapshot_ignores_partial_or_reordered_live_tools(self):
        stored = [
            {"name": "create_memory", "input_schema": {"type": "object"}},
            {"name": "search_forum", "input_schema": {"type": "object"}},
            {"name": "play_music", "input_schema": {"type": "object"}},
        ]
        conv = {
            "id": 9,
            "last_anthropic_tools": stored,
            "last_frontend_tool_names": ["play_music"],
        }

        freeze = AsyncMock(return_value=(stored, ["play_music"]))
        with (
            patch.object(main, "MEMORY_ENABLED", True),
            patch.object(
                main,
                "merge_frontend_tools",
                side_effect=AssertionError("stored snapshots must not re-merge live tools"),
            ),
            patch.object(main, "freeze_conversation_tool_snapshot", freeze),
        ):
            tools, frontend_names = await main.resolve_conversation_tool_snapshot(
                conv, []
            )

        self.assertEqual(
            [*main.BUILTIN_MEMORY_TOOLS, *main.noteboard.TOOLS, *main.BUILTIN_PROMPT_TOOLS,
             *main.BUILTIN_HISTORY_TOOLS, *main.BUILTIN_NOTIFICATION_TOOLS, *stored[1:]],
            tools,
        )
        self.assertEqual({"play_music"}, frontend_names)
        freeze.assert_awaited_once_with(9, stored, ["play_music"])

    async def test_legacy_snapshot_refreshes_memory_tools_and_backfills_frontend_sources(self):
        stored = [
            {"name": "read_long_term_memory", "input_schema": {"type": "object"}},
            {"name": "frontend_effect", "input_schema": {"type": "object"}},
        ]
        conv = {
            "id": 11,
            "last_anthropic_tools": stored,
            "last_frontend_tool_names": None,
        }
        frontend_tools = [{
            "type": "function",
            "function": {
                "name": "frontend_effect",
                "parameters": {"type": "object"},
            },
        }]

        freeze = AsyncMock(return_value=(stored, ["read_long_term_memory", "frontend_effect"]))
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "freeze_conversation_tool_snapshot", freeze
        ):
            tools, frontend_names = await main.resolve_conversation_tool_snapshot(
                conv, frontend_tools
            )

        self.assertEqual(
            [*main.BUILTIN_MEMORY_TOOLS, *main.noteboard.TOOLS, *main.BUILTIN_PROMPT_TOOLS,
             *main.BUILTIN_HISTORY_TOOLS, *main.BUILTIN_NOTIFICATION_TOOLS, stored[1]],
            tools,
        )
        self.assertNotIn("read_long_term_memory", {tool["name"] for tool in tools})
        self.assertIn("read_diary", {tool["name"] for tool in tools})
        self.assertEqual({"frontend_effect"}, frontend_names)
        freeze.assert_awaited_once_with(11, [stored[1]], ["frontend_effect"])

    def test_resolved_tools_bypass_live_merge(self):
        frozen = [{"name": "stable_tool", "input_schema": {"type": "object"}}]
        body = {
            "model": "claude-opus-4-6",
            "messages": [{"role": "user", "content": "hello"}],
        }

        with patch.object(
            main,
            "merge_frontend_tools",
            side_effect=AssertionError("resolved tools must be used verbatim"),
        ):
            result = main.to_anthropic_body(body, resolved_tools=frozen)

        self.assertIs(frozen, result["tools"])

    def test_memory_tools_are_removed_when_memory_system_is_disabled(self):
        external = {"name": "play_music", "input_schema": {"type": "object"}}
        with patch.object(main, "MEMORY_ENABLED", False):
            tools = main._sync_builtin_memory_tools([
                main.BUILTIN_MEMORY_TOOLS[0], external,
            ])

        self.assertEqual([*main.BUILTIN_PROMPT_TOOLS,
                          *main.BUILTIN_NOTIFICATION_TOOLS, external], tools)

    def test_frontend_source_matching_handles_namespaces(self):
        self.assertTrue(
            main._is_frontend_tool_name(
                "frontend.play_music",
                {"play_music"},
            )
        )
        self.assertFalse(
            main._is_frontend_tool_name(
                "search_forum",
                {"play_music"},
            )
        )


if __name__ == "__main__":
    unittest.main()
