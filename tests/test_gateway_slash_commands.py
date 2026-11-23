import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import database
import main


class GatewayCommandParsingTests(unittest.TestCase):
    def test_registered_command_is_parsed_from_complete_last_user_turn(self):
        parsed = main._parse_gateway_command([
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "/message(12)"},
        ])

        self.assertEqual("message", parsed["name"])
        self.assertEqual("(12)", parsed["argument"])

    def test_unknown_escaped_and_mixed_media_messages_are_not_commands(self):
        self.assertIsNone(main._parse_gateway_command([
            {"role": "user", "content": "/not-a-gateway-command"},
        ]))
        self.assertIsNone(main._parse_gateway_command([
            {"role": "user", "content": "//compact"},
        ]))
        self.assertIsNone(main._parse_gateway_command([{
            "role": "user",
            "content": [
                {"type": "text", "text": "/compact"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,eA=="}},
            ],
        }]))

    def test_stream_response_is_openai_compatible_and_ends_with_done(self):
        async def collect():
            return [
                chunk async for chunk in
                main._stream_gateway_command_response("test-model", "命令成功")
            ]

        chunks = __import__("asyncio").run(collect())
        payloads = [json.loads(chunk.removeprefix("data: ")) for chunk in chunks[:-1]]
        self.assertEqual("assistant", payloads[0]["choices"][0]["delta"]["role"])
        self.assertEqual("命令成功", payloads[1]["choices"][0]["delta"]["content"])
        self.assertEqual("stop", payloads[2]["choices"][0]["finish_reason"])
        self.assertEqual("data: [DONE]\n\n", chunks[-1])


class GatewayCommandExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_retired_diary_commands_are_not_registered(self):
        for command in ("/diary", "/yes", "/no"):
            self.assertIsNone(main._parse_gateway_command([
                {"role": "user", "content": command},
            ]))

    async def test_message_freezes_exact_last_visible_chat_messages(self):
        rows = [
            {"id": 1, "role": "user", "content": "one", "hidden": False, "content_json": None},
            {"id": 2, "role": "assistant", "content": "tool", "hidden": False,
             "content_json": [{"type": "tool_use"}]},
            {"id": 3, "role": "assistant", "content": "two", "hidden": False, "content_json": None},
            {"id": 4, "role": "user", "content": "hidden", "hidden": True, "content_json": None},
            {"id": 5, "role": "user", "content": "three", "hidden": False, "content_json": None},
        ]
        save_selection = AsyncMock(return_value=[3, 5])
        with patch.object(main, "CONTEXT_MANAGED", True), patch.object(
            main, "get_context_messages", AsyncMock(return_value=rows)
        ), patch.object(
            main, "set_conversation_handoff_message_ids", save_selection
        ):
            selected = await main._gateway_select_messages(7, 2)

        self.assertEqual([3, 5], [row["id"] for row in selected])
        save_selection.assert_awaited_once_with(7, [3, 5])

    async def test_compact_redo_reuses_saved_message_snapshot(self):
        rows = [
            {"id": 1, "role": "user", "content": "one", "hidden": False},
            {"id": 2, "role": "assistant", "content": "two", "hidden": False},
            {"id": 3, "role": "user", "content": "new", "hidden": False},
        ]
        generate = AsyncMock(return_value="重新生成的摘要")
        save = AsyncMock(return_value=4)
        conv = {"id": 7, "handoff_summary_through_message_id": 2}
        with patch.object(main, "CONTEXT_MANAGED", True), patch.object(
            main, "MEMORY_ORGANIZER_ENABLED", True
        ), patch.object(
            main, "get_context_messages", AsyncMock(return_value=rows)
        ), patch.object(
            main, "get_conversation_handoff_summary", AsyncMock(return_value="旧交接摘要")
        ), patch.object(
            main, "_load_handoff_summary_runtime", AsyncMock(return_value={"model": "summary-model"})
        ), patch.object(
            main, "_generate_handoff_summary", generate
        ), patch.object(
            main, "save_conversation_handoff_command_summary", save
        ):
            result = await main._gateway_generate_compact(
                conv, redo=True, instruction="更精简"
            )

        self.assertEqual(("重新生成的摘要", 4, 2), result)
        self.assertEqual([1, 2], [row["id"] for row in generate.await_args.args[0]])
        self.assertEqual("旧交接摘要", generate.await_args.args[1])
        self.assertEqual("更精简", generate.await_args.kwargs["regeneration_instruction"])
        save.assert_awaited_once_with(7, "重新生成的摘要", 2)

    async def test_compact_uses_all_current_messages_not_the_rolling_window(self):
        rows = [
            {"id": 1, "role": "user", "content": "rolled", "hidden": False},
            {"id": 2, "role": "assistant", "content": "old", "hidden": False},
            {"id": 3, "role": "user", "content": "active", "hidden": False},
            {"id": 4, "role": "assistant", "content": "current", "hidden": False},
        ]
        generate = AsyncMock(return_value="完整摘要")
        save = AsyncMock(return_value=5)
        conv = {
            "id": 7,
            "context_mode": "window",
            "temporary_summary_through_message_id": 2,
        }
        with patch.object(main, "CONTEXT_MANAGED", True), patch.object(
            main, "MEMORY_ORGANIZER_ENABLED", True
        ), patch.object(
            main, "get_context_messages", AsyncMock(return_value=rows)
        ), patch.object(
            main, "get_conversation_handoff_summary", AsyncMock(return_value="旧交接摘要")
        ), patch.object(
            main, "_load_handoff_summary_runtime", AsyncMock(return_value={"model": "summary-model"})
        ), patch.object(
            main, "_generate_handoff_summary", generate
        ), patch.object(
            main, "save_conversation_handoff_command_summary", save
        ):
            result = await main._gateway_generate_compact(conv)

        self.assertEqual(("完整摘要", 5, 4), result)
        self.assertEqual([1, 2, 3, 4], [row["id"] for row in generate.await_args.args[0]])
        self.assertEqual(0, generate.await_args.kwargs["max_input_chars"])
        save.assert_awaited_once_with(7, "完整摘要", 4)

    async def test_compact_redo_requires_an_existing_frozen_snapshot(self):
        with patch.object(main, "CONTEXT_MANAGED", True), patch.object(
            main, "MEMORY_ORGANIZER_ENABLED", True
        ), patch.object(main, "get_context_messages", AsyncMock(return_value=[
            {"id": 1, "role": "user", "content": "one", "hidden": False},
        ])):
            with self.assertRaisesRegex(ValueError, "请先使用 /compact"):
                await main._gateway_generate_compact({"id": 7}, redo=True)

    async def test_heartbeat_toggle_preserves_interval(self):
        save = AsyncMock(return_value={
            "enabled": True,
            "interval_minutes": 42,
        })
        with patch.object(main, "_load_heartbeat_settings", AsyncMock(return_value={
            "enabled": False,
            "interval_minutes": 42,
        })), patch.object(main, "save_heartbeat_settings", save), patch.object(
            main, "get_active_conversation", AsyncMock(return_value={
                "last_route_provider": "anthropic",
            })
        ):
            text = await main._execute_gateway_command(
                {"name": "heartbeat", "argument": "on"}, None
            )

        self.assertIn("已开启", text)
        save.assert_awaited_once_with(
            enabled=True,
            interval_minutes=42,
        )

    async def test_switch_uses_persisted_summary_and_selection(self):
        source = {"id": 7, "name": "source"}
        refreshed = {
            "id": 7,
            "handoff_draft": "摘要",
            "handoff_message_ids": [11, 12],
        }
        create = AsyncMock(return_value={"id": 8, "name": "下一段"})
        with patch.object(main, "CONTEXT_MANAGED", True), patch.object(
            main, "get_active_conversation", AsyncMock(return_value=refreshed)
        ), patch.object(main, "create_conversation_from_messages", create):
            text = await main._execute_gateway_command(
                {"name": "switch", "argument": "下一段"}, source
            )

        self.assertIn("#7 → #8", text)
        self.assertIn("2 条消息", text)
        create.assert_awaited_once_with(
            7, "下一段", [11, 12], store_summary_in_flow=main.MEMORY_ENABLED,
            require_active_source=True,
        )

    async def test_switch_without_summary_or_selection_creates_blank_conversation(self):
        source = {"id": 7, "name": "source"}
        refreshed = {
            "id": 7,
            "handoff_draft": "",
            "handoff_message_ids": [],
        }
        create = AsyncMock(return_value={"id": 8, "name": "延续会话"})
        with patch.object(main, "CONTEXT_MANAGED", True), patch.object(
            main, "get_active_conversation", AsyncMock(return_value=refreshed)
        ), patch.object(main, "create_conversation_from_messages", create):
            text = await main._execute_gateway_command(
                {"name": "switch", "argument": ""}, source
            )

        self.assertIn("#7 → #8", text)
        self.assertIn("已创建空白会话", text)
        create.assert_awaited_once_with(
            7, "延续会话", [], store_summary_in_flow=main.MEMORY_ENABLED,
            require_active_source=True,
        )

    async def test_switch_count_runs_compact_and_selection_shortcut(self):
        source = {"id": 7, "name": "source"}
        refreshed = {
            "id": 7,
            "handoff_draft": "摘要",
            "handoff_message_ids": [11, 12],
        }
        generate = AsyncMock(return_value=("摘要", 3, 10))
        select = AsyncMock(return_value=[{"id": 11}, {"id": 12}])
        create = AsyncMock(return_value={"id": 8, "name": "快捷会话"})
        with patch.object(main, "CONTEXT_MANAGED", True), patch.object(
            main, "_gateway_generate_compact", generate
        ), patch.object(main, "_gateway_select_messages", select), patch.object(
            main, "get_active_conversation", AsyncMock(return_value=refreshed)
        ), patch.object(main, "create_conversation_from_messages", create):
            text = await main._execute_gateway_command(
                {"name": "switch", "argument": "2 快捷会话"}, source
            )

        generate.assert_awaited_once_with(source)
        select.assert_awaited_once_with(7, 2)
        create.assert_awaited_once_with(
            7, "快捷会话", [11, 12], store_summary_in_flow=main.MEMORY_ENABLED,
            require_active_source=True,
        )
        self.assertIn("摘要 v3", text)

    async def test_chat_route_intercepts_command_before_provider_validation(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "model": "missing-provider-model",
            "messages": [{"role": "user", "content": "/help"}],
        })
        route_loader = AsyncMock()
        with patch.object(
            main, "get_active_conversation", AsyncMock(return_value=None)
        ), patch.object(main, "_load_route_provider", route_loader), patch.object(
            main, "_execute_gateway_command", AsyncMock(return_value="命令帮助")
        ):
            response = await main.chat_completions(request)

        payload = json.loads(response.body)
        self.assertEqual(200, response.status_code)
        self.assertEqual("命令帮助", payload["choices"][0]["message"]["content"])
        route_loader.assert_not_awaited()


class GatewayCommandDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_activating_existing_conversation_stores_departing_summary(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=True)
        source = {
            "id": 7,
            "name": "离开的会话",
            "is_active": True,
            "handoff_draft": "摘要",
            "handoff_summary_version": 2,
            "handoff_summary_through_message_id": 19,
            "handoff_summary_ready_for_flow": True,
        }
        conn.fetchrow = AsyncMock(return_value=source)
        conn.execute = AsyncMock()
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock(return_value=None)
        transaction.__aexit__ = AsyncMock(return_value=False)
        conn.transaction.return_value = transaction
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire
        store = AsyncMock(return_value=31)

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(
            database, "_store_conversation_summary_in_flow", store
        ):
            await database.set_active_conversation(8)

        store.assert_awaited_once_with(conn, source)

    async def test_blank_handoff_creates_and_activates_conversation(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {
                "id": 7,
                "max_messages": 200,
                "is_active": True,
                "handoff_draft": "",
                "handoff_summary_ready_for_flow": False,
            },
            {
                "id": 8,
                "name": "延续会话",
                "max_messages": 200,
                "handoff_summary": "",
                "handoff_source_id": 7,
            },
        ])
        conn.fetch = AsyncMock(return_value=[])
        conn.execute = AsyncMock()
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock(return_value=None)
        transaction.__aexit__ = AsyncMock(return_value=False)
        conn.transaction.return_value = transaction
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            result = await database.create_conversation_from_messages(
                7, "延续会话", []
            )

        self.assertEqual(8, result["id"])
        conn.fetch.assert_not_awaited()
        executed_queries = [call.args[0] for call in conn.execute.await_args_list]
        self.assertFalse(
            any("INSERT INTO context_messages" in query for query in executed_queries)
        )

    async def test_summary_moves_to_flow_memory_without_target_handoff_injection(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {
                "id": 7,
                "name": "旧会话",
                "max_messages": 200,
                "is_active": True,
                "handoff_draft": "这是交接摘要",
                "handoff_summary_version": 3,
                "handoff_summary_through_message_id": 42,
                "handoff_summary_ready_for_flow": True,
            },
            {"id": 31},
            {
                "id": 8,
                "name": "新会话",
                "max_messages": 200,
                "handoff_summary": None,
                "handoff_source_id": 7,
            },
        ])
        conn.fetchval = AsyncMock(return_value=None)
        conn.fetch = AsyncMock(return_value=[])
        conn.execute = AsyncMock()
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock(return_value=None)
        transaction.__aexit__ = AsyncMock(return_value=False)
        conn.transaction.return_value = transaction
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            result = await database.create_conversation_from_messages(
                7, "新会话", []
            )

        self.assertEqual(31, result["flow_memory_id"])
        queries = [call.args[0] for call in conn.fetchrow.await_args_list]
        self.assertTrue(any("INSERT INTO standing_memory_blocks" in query for query in queries))
        conversation_insert = next(
            query for query in queries if "INSERT INTO conversations" in query
        )
        self.assertNotIn("(name, max_messages, handoff_summary", conversation_insert)
        flow_call = next(
            call for call in conn.fetchrow.await_args_list
            if "INSERT INTO standing_memory_blocks" in call.args[0]
        )
        self.assertEqual("旧会话", flow_call.args[1])
        self.assertEqual("这是交接摘要", flow_call.args[2])
        metadata = json.loads(flow_call.args[3])
        self.assertEqual("conversation_summary", metadata["kind"])
        self.assertEqual(42, metadata["through_message_id"])
        consume_query = next(
            call.args[0] for call in conn.execute.await_args_list
            if "SET handoff_summary_ready_for_flow = FALSE" in call.args[0]
        )
        self.assertIn("handoff_summary_version = $2", consume_query)

    async def test_browsing_an_old_conversation_does_not_store_its_summary(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=True)
        source = {
            "id": 7,
            "name": "过去的会话",
            "is_active": True,
            "handoff_draft": "历史摘要",
            "handoff_summary_version": 4,
            "handoff_summary_through_message_id": 25,
            "handoff_summary_ready_for_flow": False,
        }
        conn.fetchrow = AsyncMock(return_value=source)
        conn.execute = AsyncMock()
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock(return_value=None)
        transaction.__aexit__ = AsyncMock(return_value=False)
        conn.transaction.return_value = transaction
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire
        store = AsyncMock(return_value=31)

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(
            database, "_store_conversation_summary_in_flow", store
        ):
            await database.set_active_conversation(8)

        store.assert_not_awaited()
        self.assertFalse(any(
            "INSERT INTO standing_memory_blocks" in call.args[0]
            for call in conn.execute.await_args_list
        ))


if __name__ == "__main__":
    unittest.main()
