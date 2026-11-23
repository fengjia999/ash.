import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import main
import database


class FiniteContextTests(unittest.IsolatedAsyncioTestCase):
    def test_window_excludes_only_messages_already_folded_into_summary(self):
        rows = [
            {"id": 10, "role": "user", "content": "old"},
            {"id": 11, "role": "assistant", "content": "old answer"},
            {"id": 12, "role": "user", "content": "new"},
            {"id": 13, "role": "assistant", "content": "new answer"},
        ]

        active = main._active_context_rows(rows, {
            "context_mode": "window",
            "temporary_summary_through_message_id": 11,
        })

        self.assertEqual(rows[2:], active)

    def test_window_excludes_unsummarized_rows_outside_fixed_token_budget(self):
        rows = [
            {"id": index, "role": "user" if index % 2 else "assistant",
             "content": str(index), "content_json": None}
            for index in range(1, 13)
        ]

        with patch.object(
            database, "_rolling_context_token_estimate", return_value=500
        ):
            active = main._active_context_rows(rows, {
                "context_mode": "window",
                "context_window_tokens": 2000,
            })

        self.assertEqual([9, 10, 11, 12], [row["id"] for row in active])

    async def test_finite_prompt_orders_cached_summary_before_uncached_recall(self):
        with patch.object(main, "get_all_sections", AsyncMock(return_value=[
            {"key": "Core", "content": "CORE"},
            {"key": "Interaction", "content": "INTERACTION"},
        ])), patch.object(
            main, "_build_standing_memory_cache_blocks",
            AsyncMock(return_value=("FIXED", "TIMELINE")),
        ), patch.object(
            main, "build_dynamic_turn_block", AsyncMock(return_value="AUTO RECALL")
        ), patch.object(main, "PROMPT_CACHE_ENABLED", True):
            blocks = await main.build_system_prompt_with_memories(
                "hello", [], 7, conversation={
                    "context_mode": "window",
                    "temporary_summary_every_n_messages": 10,
                    "temporary_summary": "此前的质感与重点",
                },
            )

        self.assertEqual(["1h", "1h", "1h", "1h"], [
            block["cache_control"]["ttl"] for block in blocks[:4]
        ])
        self.assertEqual("CORE", blocks[0]["text"])
        self.assertEqual("FIXED", blocks[1]["text"])
        self.assertEqual("INTERACTION", blocks[2]["text"])
        self.assertEqual("TIMELINE", blocks[3]["text"])
        self.assertIn("此前的质感与重点", blocks[4]["text"])
        self.assertNotIn("cache_control", blocks[4])
        self.assertEqual("AUTO RECALL", blocks[5]["text"])
        self.assertNotIn("cache_control", blocks[5])

        conversation_messages = [{"role": "user", "content": "hello"}]
        anthropic_body = main._anthropic_body_for_request({
            "model": "claude-sonnet-4-5",
            "system": blocks,
            "_disable_message_cache": True,
        }, conversation_messages, stream=False)
        self.assertEqual("AUTO RECALL", anthropic_body["system"][-1]["text"])
        self.assertNotIn("AUTO RECALL", str(anthropic_body["messages"]))

        openai_messages = [{
            "role": "system",
            "content": main._system_to_openai_content(blocks, explicit_cache=True),
        }, *conversation_messages]
        self.assertEqual("AUTO RECALL", openai_messages[0]["content"][-1]["text"])
        self.assertNotIn("prompt_cache_breakpoint", openai_messages[0]["content"][-1])
        self.assertNotIn("AUTO RECALL", str(openai_messages[1:]))

    async def test_finite_cache_layers_isolate_flow_memory_changes(self):
        flow = "FLOW ONE"

        async def memory_blocks():
            return "FIXED", flow

        with patch.object(main, "get_all_sections", AsyncMock(return_value=[
            {"key": "Core", "content": "CORE"},
            {"key": "Interaction", "content": "INTERACTION"},
        ])), patch.object(
            main, "_build_standing_memory_cache_blocks", side_effect=memory_blocks
        ), patch.object(
            main, "build_dynamic_turn_block", AsyncMock(return_value="")
        ), patch.object(main, "PROMPT_CACHE_ENABLED", True):
            first = await main.build_system_prompt_with_memories(
                "hello", [], 7, conversation={"context_mode": "window"}
            )
            flow = "FLOW TWO"
            second = await main.build_system_prompt_with_memories(
                "hello", [], 7, conversation={"context_mode": "window"}
            )

        self.assertEqual(4, main._count_cache_control_blocks(first))
        self.assertEqual(4, main._count_cache_control_blocks(second))
        self.assertEqual(first[0]["text"], second[0]["text"])
        self.assertEqual(first[1]["text"], second[1]["text"])
        self.assertEqual(first[2]["text"], second[2]["text"])
        self.assertNotEqual(first[3]["text"], second[3]["text"])

    def test_finite_anthropic_request_disables_only_message_cache(self):
        system = [
            {"type": "text", "text": "fixed", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"type": "text", "text": "temporary"},
            {"type": "text", "text": "recall"},
        ]
        body = main._anthropic_body_for_request({
            "model": "claude-sonnet-4-5",
            "system": system,
            "messages": [{"role": "user", "content": [{
                "type": "text", "text": "latest",
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }]}],
            "_disable_message_cache": True,
        }, [{"role": "user", "content": [{
            "type": "text", "text": "latest",
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }]}], stream=False)

        self.assertEqual(system, body["system"])
        self.assertNotIn("_disable_message_cache", body)
        self.assertEqual(
            [{"type": "text", "text": "latest"}],
            body["messages"][0]["content"],
        )

    def test_finite_openai_cache_marks_system_but_not_conversation(self):
        body = {"model": "gpt-5.6", "messages": [
            {"role": "system", "content": [{
                "type": "text", "text": "fixed",
                "prompt_cache_breakpoint": {"mode": "explicit"},
            }]},
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "latest"},
        ]}

        main._inject_openai_explicit_cache(body, include_message=False)

        self.assertEqual({"mode": "explicit"}, body["prompt_cache_options"])
        self.assertFalse(any(
            isinstance(message.get("content"), list)
            and any(block.get("prompt_cache_breakpoint") for block in message["content"])
            for message in body["messages"][1:]
        ))

    async def test_conversation_settings_api_saves_finite_mode(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "name": "有限会话",
            "context_mode": "window",
            "context_window_tokens": 32000,
            "temporary_summary_trigger_tokens": 4000,
        })
        update = AsyncMock()
        with patch.object(
            main, "get_conversation_context_metadata", AsyncMock(return_value={
                "context_mode": "full",
                "context_window_tokens": 32000,
            })
        ), patch.object(main, "update_conversation", update):
            response = await main.api_update_conversation(7, request)

        self.assertEqual("ok", response["status"])
        update.assert_awaited_once_with(
            7,
            name="有限会话",
            context_mode="window",
            context_window_tokens=32000,
            temporary_summary_trigger_tokens=4000,
        )

    async def test_conversation_settings_accepts_one_thousand_token_window(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "context_mode": "window",
            "context_window_tokens": 1000,
        })
        update = AsyncMock()
        with patch.object(
            main, "get_conversation_context_metadata", AsyncMock(return_value={
                "context_mode": "full",
                "context_window_tokens": 32000,
            })
        ), patch.object(main, "update_conversation", update):
            response = await main.api_update_conversation(7, request)

        self.assertEqual("ok", response["status"])
        self.assertEqual(1000, response["context_window_tokens"])
        update.assert_awaited_once_with(
            7,
            name=None,
            context_mode="window",
            context_window_tokens=1000,
            temporary_summary_trigger_tokens=8000,
        )

    async def test_maintenance_generates_temporary_summary(self):
        batch = {
            "token": "claim",
            "through_id": 12,
            "current_summary": "旧摘要",
            "messages": [{"id": 12, "role": "assistant", "content": "新消息"}],
            "rolling_messages": [
                {"id": 12, "role": "assistant", "content": "新消息"}
            ],
        }
        finish = AsyncMock(return_value=True)
        with patch.object(
            main, "claim_temporary_summary_batch", AsyncMock(side_effect=[batch, None])
        ), patch.object(
            main, "_load_temporary_summary_runtime", AsyncMock(return_value={"model": "summary"})
        ), patch.object(
            main, "_generate_handoff_summary", AsyncMock(return_value="新临时摘要")
        ) as generate, patch.object(
            main, "finish_temporary_summary", finish
        ), patch.object(main, "MEMORY_ENABLED", True):
            await main._run_conversation_maintenance(7)

        self.assertTrue(generate.await_args.kwargs["temporary"])
        self.assertEqual(0, generate.await_args.kwargs["max_input_chars"])
        self.assertEqual(batch["rolling_messages"], generate.await_args.args[0])
        finish.assert_awaited_once_with(7, "claim", "新临时摘要", 12)

    async def test_roll_claims_oldest_complete_exchange_by_token_budget(self):
        rows = [
            {"id": index, "role": "user" if index % 2 else "assistant",
             "content": str(index), "content_json": None}
            for index in range(1, 21)
        ]
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={
            "id": 7,
            "context_mode": "window",
            "context_window_tokens": 2000,
            "temporary_summary_trigger_tokens": 4000,
            "temporary_summary": "旧摘要",
            "temporary_summary_through_message_id": None,
            "temporary_summary_claim_token": None,
            "temporary_summary_claimed_at": None,
        })
        conn.fetch = AsyncMock(return_value=rows)
        conn.execute = AsyncMock(return_value="UPDATE 1")
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock()
        transaction.__aexit__ = AsyncMock(return_value=False)
        conn.transaction.return_value = transaction
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(
            database, "_rolling_context_token_estimate",
            return_value=500,
        ):
            batch = await database.claim_temporary_summary_batch(7)

        self.assertEqual(8, batch["through_id"])
        self.assertEqual(4000, batch["source_tokens"])
        self.assertEqual(rows, batch["messages"])
        self.assertEqual(rows[:8], batch["rolling_messages"])

    async def test_roll_waits_until_rolled_out_rows_reach_summary_threshold(self):
        rows = [
            {"id": index, "role": "user" if index % 2 else "assistant",
             "content": str(index), "content_json": None}
            for index in range(1, 13)
        ]
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={
            "id": 7,
            "context_mode": "window",
            "context_window_tokens": 2000,
            "temporary_summary_trigger_tokens": 5000,
            "temporary_summary": "",
            "temporary_summary_through_message_id": None,
            "temporary_summary_claim_token": None,
            "temporary_summary_claimed_at": None,
        })
        conn.fetch = AsyncMock(return_value=rows)
        conn.execute = AsyncMock()
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock()
        transaction.__aexit__ = AsyncMock(return_value=False)
        conn.transaction.return_value = transaction
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)), patch.object(
            database, "_rolling_context_token_estimate", return_value=500,
        ):
            batch = await database.claim_temporary_summary_batch(7)

        self.assertIsNone(batch)
        conn.execute.assert_not_awaited()

    def test_unlimited_summary_render_keeps_the_start_of_full_context(self):
        messages = [
            {"role": "user", "content": "最早消息"},
            {"role": "assistant", "content": "x" * 30000},
            {"role": "user", "content": "最新消息"},
        ]
        rendered = main._render_frontend_context_for_organizer(messages, 0)
        self.assertIn("最早消息", rendered)
        self.assertIn("最新消息", rendered)

    def test_background_transcript_uses_runtime_identity_preset(self):
        rendered = main._render_frontend_context_for_organizer(
            [
                {"role": "user", "content": "还记得吗"},
                {"role": "assistant", "content": "我记得"},
            ],
            identity_presets={"user_name": "对方示例"},
        )

        self.assertIn("【对方示例】还记得吗", rendered)
        self.assertIn("【我】我记得", rendered)
        self.assertNotIn("【用户】", rendered)

    def test_temporary_summary_output_is_capped_at_three_thousand_tokens(self):
        body = main._summary_completion_body(
            "https://example.com/v1", "summary-model", [],
            max_tokens=main.TEMPORARY_SUMMARY_MAX_TOKENS,
        )
        self.assertGreaterEqual(body["max_tokens"], 1000)
        self.assertLessEqual(body["max_tokens"], 3000)
        self.assertIn("目标长度为 800 字符", main.TEMPORARY_SUMMARY_PROMPT)
        self.assertIn("重要互动必须尽可能保留", main.TEMPORARY_SUMMARY_PROMPT)
        self.assertIn("不压缩上文定义的重要互动", main.TEMPORARY_SUMMARY_PROMPT)

    def test_conversation_menu_exposes_summary_and_settings_exposes_token_waterline(self):
        page = (Path(__file__).resolve().parents[1] / "templates" / "context.html").read_text()
        self.assertIn('id="contextModeFull"', page)
        self.assertIn('id="contextModeWindow"', page)
        self.assertIn('id="contextWindowTokens"', page)
        self.assertIn('id="contextWindowTokens" min="1000"', page)
        self.assertIn('id="temporarySummaryTriggerTokens" min="1000"', page)
        self.assertNotIn('id="temporarySummaryEvery"', page)
        self.assertIn('id="temporarySummaryMenuItem"', page)
        self.assertIn("menuAction('summary')", page)
        settings_markup = page.split('id="editConvModal"', 1)[1].split(
            'id="temporarySummaryModal"', 1
        )[0]
        self.assertNotIn("openTemporarySummaryEditor", settings_markup)
        self.assertNotIn("摘要分支", page)
        self.assertIn('id="temporarySummaryModal"', page)
        self.assertIn('id="generateTemporarySummaryBtn"', page)
        self.assertIn("function openTemporarySummaryEditor()", page)
        self.assertIn("function generateTemporarySummary()", page)
        self.assertIn("function saveTemporarySummary()", page)
        self.assertNotIn('id="memoryExtractionEvery"', page)

    async def test_temporary_summary_api_reads_and_updates_independently(self):
        get_metadata = AsyncMock(return_value={
            "id": 7,
            "temporary_summary": "当前摘要",
            "temporary_summary_through_message_id": 42,
        })
        with patch.object(main, "get_conversation_context_metadata", get_metadata):
            result = await main.api_get_temporary_summary(7)

        self.assertEqual("当前摘要", result["summary"])
        self.assertEqual(42, result["through_message_id"])
        request = MagicMock()
        request.json = AsyncMock(return_value={"summary": "手动修订"})
        update = AsyncMock(return_value={
            "id": 7,
            "temporary_summary": "手动修订",
            "temporary_summary_through_message_id": 42,
        })
        with patch.object(main, "set_conversation_temporary_summary", update):
            saved = await main.api_update_temporary_summary(7, request)

        self.assertEqual("手动修订", saved["summary"])
        self.assertEqual(42, saved["through_message_id"])
        update.assert_awaited_once_with(7, "手动修订")

    async def test_temporary_summary_can_be_regenerated_from_messages_before_active_window(self):
        conversation = {
            "id": 7,
            "temporary_summary": "上一版摘要",
            "temporary_summary_through_message_id": 10,
        }
        messages = [
            {"id": 9, "role": "user", "content": "已经折叠"},
            {"id": 11, "role": "user", "content": "新问题"},
            {"id": 12, "role": "assistant", "content": "新回答"},
        ]
        generate = AsyncMock(return_value="手动生成的新摘要")
        save = AsyncMock(return_value={
            "temporary_summary": "手动生成的新摘要",
            "temporary_summary_through_message_id": 10,
        })
        with patch.object(
            main, "get_conversation_context_metadata",
            AsyncMock(return_value=conversation),
        ), patch.object(
            main, "get_context_messages", AsyncMock(return_value=messages),
        ), patch.object(
            main, "_load_temporary_summary_runtime",
            AsyncMock(return_value={"model": "summary-model"}),
        ), patch.object(
            main, "_generate_handoff_summary", generate,
        ), patch.object(
            main, "set_conversation_temporary_summary", save,
        ):
            result = await main.api_generate_temporary_summary(7)

        self.assertEqual("手动生成的新摘要", result["summary"])
        self.assertEqual(messages[:1], generate.await_args.args[0])
        self.assertEqual("上一版摘要", generate.await_args.args[1])
        self.assertTrue(generate.await_args.kwargs["temporary"])
        self.assertEqual(0, generate.await_args.kwargs["max_input_chars"])
        save.assert_awaited_once_with(7, "手动生成的新摘要")

    async def test_clearing_temporary_summary_restores_folded_source_cursor(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={
            "id": 7,
            "temporary_summary": "",
            "temporary_summary_through_message_id": None,
        })
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            result = await database.set_conversation_temporary_summary(7, "")

        query = conn.fetchrow.await_args.args[0]
        self.assertIn("WHEN $2 = '' THEN NULL", query)
        self.assertIn("temporary_summary_claim_token = NULL", query)
        self.assertIsNone(result["temporary_summary_through_message_id"])


if __name__ == "__main__":
    unittest.main()
