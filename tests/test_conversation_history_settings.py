import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import main
import database


class ConversationHistorySettingsTests(unittest.IsolatedAsyncioTestCase):
    def test_public_settings_never_expose_keys(self):
        result = main._public_conversation_model_settings({
            "search_enabled": True,
            "embedding_api_url": "https://embed.example/v1/embeddings",
            "embedding_model": "embed-model",
            "embedding_api_key": "embedding-secret",
            "long_term_recall_limit": 12,
            "title_enabled": True,
            "title_provider_id": 3,
            "title_api_url": "https://title.example/v1/chat/completions",
            "title_model": "title-model",
            "title_api_key": "title-secret",
            "handoff_provider_id": 8,
            "handoff_model": "handoff-model",
            "long_term_summary_provider_id": 9,
            "long_term_summary_model": "long-term-model",
            "long_term_summary_configured": True,
        })

        self.assertNotIn("embedding_api_key", result)
        self.assertNotIn("title_api_key", result)
        self.assertNotIn("title_api_url", result)
        self.assertTrue(result["embedding_api_key_configured"])
        self.assertEqual(12, result["long_term_recall_limit"])
        self.assertEqual(
            main.LONG_TERM_RECALL_MAX_TOKENS,
            result["long_term_recall_token_budget"],
        )
        self.assertEqual(3, result["title_provider_id"])
        self.assertEqual(8, result["handoff_provider_id"])
        self.assertEqual("handoff-model", result["handoff_effective_model"])
        self.assertEqual(9, result["long_term_summary_provider_id"])
        self.assertEqual(
            "long-term-model", result["long_term_summary_effective_model"]
        )
        self.assertTrue(result["long_term_summary_configured"])
        self.assertTrue(result["title_legacy_configured"])

    def test_public_settings_use_saved_recall_token_budget(self):
        result = main._public_conversation_model_settings({
            "long_term_recall_token_budget": 3072,
        })

        self.assertEqual(3072, result["long_term_recall_token_budget"])

    async def test_blank_embedding_key_is_preserved_and_title_uses_provider(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "search_enabled": True,
            "embedding_api_url": "https://embed.example/v1/embeddings",
            "embedding_model": "embed-model",
            "embedding_api_key": "",
            "long_term_recall_limit": 10 ** 12,
            "title_enabled": True,
            "title_provider_id": 4,
            "title_model": "title-model",
            "handoff_provider_id": 5,
            "handoff_model": "handoff-model",
            "long_term_summary_provider_id": 6,
            "long_term_summary_model": "long-term-model",
        })
        save = AsyncMock(return_value={
            "search_enabled": True,
            "embedding_api_url": "https://embed.example/v1/embeddings",
            "embedding_model": "embed-model",
            "embedding_api_key": "old-embedding-key",
            "long_term_recall_limit": 10 ** 12,
            "title_enabled": True,
            "title_provider_id": 4,
            "title_model": "title-model",
        })
        with patch.object(main, "get_conversation_model_settings", AsyncMock(
            return_value={
                "embedding_api_key": "old-embedding-key",
            }
        )), patch.object(
            main, "get_openai_provider_profile",
            AsyncMock(return_value={"id": 4, "api_url": "https://title.example/v1", "api_key": "key"}),
        ), patch.object(main, "save_conversation_model_settings", save):
            response = await main.api_update_conversation_model_settings(request)

        self.assertEqual("ok", response["status"])
        self.assertIsNone(save.await_args.kwargs["embedding_api_key"])
        self.assertEqual(10 ** 12, save.await_args.kwargs["long_term_recall_limit"])
        self.assertEqual(
            main.LONG_TERM_RECALL_MAX_TOKENS,
            save.await_args.kwargs["long_term_recall_token_budget"],
        )
        self.assertEqual(4, save.await_args.kwargs["title_provider_id"])
        self.assertEqual(5, save.await_args.kwargs["handoff_provider_id"])
        self.assertEqual("handoff-model", save.await_args.kwargs["handoff_model"])
        self.assertEqual(6, save.await_args.kwargs["long_term_summary_provider_id"])
        self.assertEqual(
            "long-term-model",
            save.await_args.kwargs["long_term_summary_model"],
        )
        self.assertTrue(
            save.await_args.kwargs["long_term_summary_configured"]
        )

    async def test_recall_token_budget_must_stay_within_supported_range(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "search_enabled": False,
            "title_enabled": False,
            "long_term_recall_token_budget": 8001,
        })
        save = AsyncMock()
        with patch.object(
            main,
            "get_conversation_model_settings",
            AsyncMock(return_value={}),
        ), patch.object(main, "save_conversation_model_settings", save):
            response = await main.api_update_conversation_model_settings(request)

        self.assertEqual(400, response.status_code)
        save.assert_not_awaited()

    async def test_handoff_summary_runtime_uses_saved_provider_and_model(self):
        provider = {
            "id": 9,
            "api_url": "https://handoff.example/v1",
            "api_key": "handoff-key",
        }
        with patch.object(
            main, "get_conversation_model_settings", AsyncMock(return_value={
                "handoff_provider_id": 9,
                "handoff_model": "handoff-model",
            })
        ), patch.object(
            main, "get_openai_provider_profile", AsyncMock(return_value=provider)
        ):
            runtime = await main._load_handoff_summary_runtime()

        self.assertEqual("handoff-model", runtime["model"])
        self.assertEqual("https://handoff.example/v1", runtime["api_url"])
        self.assertEqual("handoff-key", runtime["api_key"])
        self.assertEqual("preset", runtime["source"])

    async def test_handoff_summary_model_can_override_environment_without_restart(self):
        with patch.object(
            main, "get_conversation_model_settings", AsyncMock(return_value={
                "handoff_provider_id": None,
                "handoff_model": "new-model",
            })
        ), patch.object(
            main, "MEMORY_ORGANIZER_API_URL", "https://environment.example/v1"
        ), patch.object(main, "MEMORY_ORGANIZER_API_KEY", "environment-key"):
            runtime = await main._load_handoff_summary_runtime()

        self.assertEqual("new-model", runtime["model"])
        self.assertEqual("environment", runtime["source"])

    async def test_long_term_summary_runtime_uses_its_own_provider_and_model(self):
        provider = {
            "id": 10,
            "api_url": "https://long-term.example/v1",
            "api_key": "long-term-key",
        }
        with patch.object(
            main, "get_conversation_model_settings", AsyncMock(return_value={
                "handoff_provider_id": 9,
                "handoff_model": "handoff-model",
                "long_term_summary_provider_id": 10,
                "long_term_summary_model": "long-term-model",
                "long_term_summary_configured": True,
            })
        ), patch.object(
            main, "get_openai_provider_profile", AsyncMock(return_value=provider)
        ):
            runtime = await main._load_long_term_summary_runtime()

        self.assertEqual("long-term-model", runtime["model"])
        self.assertEqual("https://long-term.example/v1", runtime["api_url"])
        self.assertEqual("long-term-key", runtime["api_key"])
        self.assertEqual("preset", runtime["source"])

    async def test_unconfigured_long_term_summary_preserves_handoff_fallback(self):
        provider = {
            "id": 9,
            "api_url": "https://handoff.example/v1",
            "api_key": "handoff-key",
        }
        with patch.object(
            main, "get_conversation_model_settings", AsyncMock(return_value={
                "handoff_provider_id": 9,
                "handoff_model": "handoff-model",
                "long_term_summary_configured": False,
            })
        ), patch.object(
            main, "get_openai_provider_profile", AsyncMock(return_value=provider)
        ):
            runtime = await main._load_long_term_summary_runtime()

        self.assertEqual("handoff-model", runtime["model"])
        self.assertEqual("handoff-fallback", runtime["source"])

    async def test_selected_title_provider_supplies_url_and_key(self):
        provider = {
            "id": 7,
            "api_url": "https://provider.example/v1/chat/completions",
            "api_key": "provider-key",
        }
        with patch.object(
            main, "get_openai_provider_profile", AsyncMock(return_value=provider)
        ):
            result = await main._load_title_openai_provider({
                "title_provider_id": 7,
                "title_api_url": "https://legacy.example/v1",
                "title_api_key": "legacy-key",
            })

        self.assertEqual(provider, result)

    def test_title_is_limited_and_date_prefix_is_removed_before_storage_prefix(self):
        self.assertEqual("关于记忆网关的讨论与", main._clean_generated_title(
            "2026-08-02 12:30 关于记忆网关的讨论与实现细节"
        ))

    def test_context_ui_groups_existing_conversations_without_writing_dates(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / "templates" / "context.html").read_text(encoding="utf-8")
        database = (root / "database.py").read_text(encoding="utf-8")

        self.assertIn("divider.className = 'conv-month'", page)
        self.assertIn("conversationStatusDates", page)
        self.assertIn('class="conv-heading"', page)
        self.assertNotIn("conversationStatusTitle", page)
        self.assertIn("MIN(created_at) AS started_at", database)
        self.assertIn("MAX(created_at) AS last_message_at", database)

        dashboard = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn('id="historyTitleProvider"', dashboard)
        self.assertIn('id="handoffSummaryProvider"', dashboard)
        self.assertIn('id="handoffSummaryModel"', dashboard)
        self.assertIn('id="longTermSummaryProvider"', dashboard)
        self.assertIn('id="longTermSummaryModel"', dashboard)
        self.assertNotIn('id="historyTitleUrl"', dashboard)
        self.assertNotIn('id="historyTitleKey"', dashboard)
        self.assertIn("已生成的摘要已显示，可手动保存", page)
        self.assertIn("返回无效响应", page)

    def test_new_conversation_prefers_generated_title_and_keeps_manual_rename(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / "templates" / "context.html").read_text(encoding="utf-8")

        self.assertNotIn('id="newName"', page)
        self.assertIn("JSON.stringify({name: '新会话'})", page)
        self.assertIn('id="createdConvModal"', page)
        self.assertIn("🟠", page)
        self.assertIn("🔵", page)
        self.assertFalse(main._is_auto_title_placeholder("我自己改的标题"))

    def test_title_update_does_not_touch_cache_or_activity_columns(self):
        source = Path(main.__file__).read_text(encoding="utf-8")
        update = source.split("UPDATE conversations\n                SET name = $2", 1)[1]
        update = update.split('"""', 1)[0]
        self.assertNotIn("updated_at", update)
        self.assertNotIn("cache_anchor", update)
        self.assertNotIn("last_anthropic_tools", update)

    def test_history_chunks_keep_messages_whole(self):
        messages = [
            {"id": 1, "role": "user", "content": "甲" * 30},
            {"id": 2, "role": "assistant", "content": "乙" * 30},
            {"id": 3, "role": "user", "content": "丙" * 30},
        ]
        chunks = database._conversation_chunks(messages, max_chars=80)

        self.assertGreaterEqual(len(chunks), 2)
        for chunk in chunks:
            for message in chunk["messages"]:
                original = next(item for item in messages if item["id"] == message["id"])
                self.assertEqual(original["content"], message["content"])

    def test_search_output_is_compact_and_hides_ranking_scores(self):
        output = main._format_history_search_results([{
            "conversation_id": 7,
            "title": "旧会话",
            "started_at": "2026-07-01 10:00:00",
            "last_message_at": "2026-07-01 10:30:00",
            "score": 0.999,
            "matches": [{
                "messages": [
                    {"id": 11, "role": "user", "content": "完整的用户消息"},
                    {"id": 12, "role": "assistant", "content": "完整的助手消息"},
                ],
            }],
        }])

        self.assertIn("会话 #7｜旧会话", output)
        self.assertIn("用户：完整的用户消息", output)
        self.assertIn("展开位置：message #11", output)
        self.assertNotIn("0.999", output)
        self.assertNotIn("score", output.lower())

    async def test_search_dispatch_excludes_active_conversation(self):
        with patch.object(
            main, "get_conversation_model_settings", AsyncMock(return_value={
                "search_enabled": True,
            })
        ), patch.object(
            main, "get_active_conversation", AsyncMock(return_value={"id": 19})
        ), patch.object(
            main, "search_conversation_history", AsyncMock(return_value=[])
        ) as search:
            result = await main.dispatch_tool_call(
                "search_conversation_history", {"query": "关键词"}
            )

        self.assertEqual("没有找到相关的历史会话。", result)
        self.assertEqual(19, search.await_args.kwargs["current_conversation_id"])

    def test_history_tools_do_not_change_user_message_building(self):
        names = {tool["name"] for tool in main.BUILTIN_HISTORY_TOOLS}
        self.assertEqual({"search_conversation_history"}, names)
        source = Path(main.__file__).read_text(encoding="utf-8")
        dispatch = source.split("async def dispatch_tool_call", 1)[1].split(
            "def _tool_result_succeeded", 1
        )[0]
        self.assertNotIn("_append_text_to_latest_user", dispatch)


if __name__ == "__main__":
    unittest.main()
