import asyncio
import re
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import main
import database


class ConversationHistorySettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_conversation_model_settings_sql_matches_argument_count(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"id": 1})
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            await database.save_conversation_model_settings(
                search_enabled=False,
                embedding_api_url="",
                embedding_model="",
                embedding_api_key=None,
                long_term_recall_limit=5,
                long_term_recall_char_budget=2000,
                long_term_recall_entry_char_limit=200,
                title_enabled=False,
                title_provider_id=None,
                title_model="",
                handoff_provider_id=None,
                handoff_model="",
                temporary_summary_provider_id=None,
                temporary_summary_model="",
            )

        query, *arguments = conn.fetchrow.await_args.args
        placeholders = [int(value) for value in re.findall(r"\$(\d+)", query)]
        self.assertEqual(15, len(arguments))
        self.assertEqual(len(arguments), max(placeholders))
        self.assertNotIn("$17", query)
        # Execute the INSERT/UPSERT, rather than only counting placeholders.
        # This statement uses syntax shared by PostgreSQL and SQLite.
        with sqlite3.connect(':memory:') as sql:
            sql.create_function('NOW', 0, lambda: '2026-11-01')
            sql.execute("""CREATE TABLE conversation_model_settings (
                id INTEGER PRIMARY KEY, search_enabled BOOLEAN,
                embedding_api_url TEXT, embedding_model TEXT, embedding_api_key TEXT,
                long_term_recall_limit INTEGER, long_term_recall_char_budget INTEGER,
                long_term_recall_entry_char_limit INTEGER, title_enabled BOOLEAN,
                title_provider_id INTEGER, title_model TEXT, handoff_provider_id INTEGER,
                handoff_model TEXT, temporary_summary_provider_id INTEGER,
                temporary_summary_model TEXT, cross_conversation_recall_enabled BOOLEAN,
                updated_at TEXT, title_api_url TEXT DEFAULT '', title_api_key TEXT DEFAULT ''
            )""")
            sql.execute(query, {str(i): value for i, value in enumerate(arguments, 1)}).fetchone()
            updated = list(arguments)
            updated[2] = 'new-embedding'
            updated[3] = 'saved-secret'
            updated[-1] = True
            sql.execute(query, {str(i): value for i, value in enumerate(updated, 1)}).fetchone()
            updated[3] = None  # blank secret keeps the previously saved value
            updated[-1] = None  # omitted toggle keeps its saved state
            sql.execute(query, {str(i): value for i, value in enumerate(updated, 1)}).fetchone()
            self.assertEqual(sql.execute(
                'SELECT embedding_model, embedding_api_key, cross_conversation_recall_enabled FROM conversation_model_settings'
            ).fetchone(), ('new-embedding', 'saved-secret', 1))


    async def test_task_settings_read_repairs_missing_table_once(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(side_effect=[
            database.asyncpg.UndefinedTableError("missing"),
            [{
                "task_key": "diary_merge",
                "provider_id": 9,
                "model": "merge-model",
                "updated_at": None,
            }],
        ])
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(
            database, "get_pool", AsyncMock(return_value=pool)
        ), patch.object(
            database, "init_conversation_model_settings_table", AsyncMock()
        ) as migrate:
            result = await database.get_model_task_settings()

        migrate.assert_awaited_once_with()
        self.assertEqual("merge-model", result["diary_merge"]["model"])

    async def test_task_settings_save_repairs_missing_table_once(self):
        conn = MagicMock()
        conn.execute = AsyncMock(side_effect=[
            database.asyncpg.UndefinedTableError("missing"),
            "INSERT 0 1",
        ])
        conn.fetch = AsyncMock(return_value=[])
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock(return_value=None)
        transaction.__aexit__ = AsyncMock(return_value=False)
        conn.transaction.return_value = transaction
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(
            database, "get_pool", AsyncMock(return_value=pool)
        ), patch.object(
            database, "init_conversation_model_settings_table", AsyncMock()
        ) as migrate:
            await database.save_model_task_settings({
                "diary_merge": {"provider_id": 9, "model": "merge-model"},
            })

        migrate.assert_awaited_once_with()
        self.assertEqual(2, conn.execute.await_count)

    async def test_model_settings_database_failure_returns_json_error(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "search_enabled": False,
            "long_term_recall_char_budget": 2000,
            "long_term_recall_entry_char_limit": 200,
        })
        with patch.object(
            main, "get_conversation_model_settings", AsyncMock(return_value={})
        ), patch.object(
            main, "get_model_task_settings", AsyncMock(return_value={})
        ), patch.object(
            main, "save_conversation_model_settings",
            AsyncMock(side_effect=RuntimeError("database unavailable")),
        ):
            response = await main.api_update_conversation_model_settings(request)

        self.assertEqual(500, response.status_code)
        self.assertIn("模型配置保存失败", response.body.decode("utf-8"))
        self.assertNotIn("database unavailable", response.body.decode("utf-8"))

    async def test_model_settings_read_failure_also_returns_json_error(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "search_enabled": False,
            "long_term_recall_char_budget": 2000,
            "long_term_recall_entry_char_limit": 200,
        })
        with patch.object(
            main, "get_conversation_model_settings",
            AsyncMock(side_effect=RuntimeError("read failed")),
        ), patch.object(
            main, "get_model_task_settings", AsyncMock(return_value={})
        ):
            response = await main.api_update_conversation_model_settings(request)

        self.assertEqual(500, response.status_code)
        self.assertIn("模型配置保存失败", response.body.decode("utf-8"))
        self.assertNotIn("read failed", response.body.decode("utf-8"))

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
            "temporary_summary_provider_id": 11,
            "temporary_summary_model": "temporary-model",
        })

        self.assertNotIn("embedding_api_key", result)
        self.assertNotIn("title_api_key", result)
        self.assertNotIn("title_api_url", result)
        self.assertTrue(result["embedding_api_key_configured"])
        self.assertEqual(12, result["long_term_recall_limit"])
        self.assertEqual(
            main.LONG_TERM_RECALL_DEFAULT_CHAR_BUDGET,
            result["long_term_recall_char_budget"],
        )
        self.assertEqual(
            main.LONG_TERM_RECALL_DEFAULT_ENTRY_CHAR_LIMIT,
            result["long_term_recall_entry_char_limit"],
        )
        self.assertEqual(3, result["title_provider_id"])
        self.assertEqual(8, result["handoff_provider_id"])
        self.assertEqual("handoff-model", result["handoff_effective_model"])
        self.assertEqual(11, result["temporary_summary_provider_id"])
        self.assertEqual(
            "temporary-model", result["temporary_summary_effective_model"]
        )
        self.assertNotIn("fixed_memory_organizer_provider_id", result)
        self.assertTrue(result["title_legacy_configured"])

    def test_public_settings_use_saved_recall_character_limits(self):
        result = main._public_conversation_model_settings({
            "long_term_recall_char_budget": 3072,
            "long_term_recall_entry_char_limit": 384,
        })

        self.assertEqual(3072, result["long_term_recall_char_budget"])
        self.assertEqual(384, result["long_term_recall_entry_char_limit"])

    def test_public_settings_preserve_zero_recall_character_budget(self):
        result = main._public_conversation_model_settings({
            "long_term_recall_char_budget": 0,
        })

        self.assertEqual(0, result["long_term_recall_char_budget"])

    async def test_zero_recall_character_budget_can_be_saved(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "search_enabled": False,
            "title_enabled": False,
            "long_term_recall_char_budget": 0,
            "long_term_recall_entry_char_limit": 200,
        })
        save = AsyncMock(return_value={
            "search_enabled": False,
            "long_term_recall_char_budget": 0,
            "long_term_recall_entry_char_limit": 200,
        })
        with patch.object(
            main, "get_conversation_model_settings", AsyncMock(return_value={})
        ), patch.object(
            main, "get_model_task_settings", AsyncMock(return_value={})
        ), patch.object(main, "save_conversation_model_settings", save):
            response = await main.api_update_conversation_model_settings(request)

        self.assertEqual("ok", response["status"])
        self.assertEqual(0, save.await_args.kwargs["long_term_recall_char_budget"])
        self.assertEqual(
            200, save.await_args.kwargs["long_term_recall_entry_char_limit"]
        )

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
            "temporary_summary_provider_id": 7,
            "temporary_summary_model": "temporary-model",
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
            main, "get_model_task_settings", AsyncMock(return_value={})
        ), patch.object(
            main, "get_openai_provider_profile",
            AsyncMock(return_value={"id": 4, "api_url": "https://title.example/v1", "api_key": "key"}),
        ), patch.object(main, "save_conversation_model_settings", save):
            response = await main.api_update_conversation_model_settings(request)

        self.assertEqual("ok", response["status"])
        self.assertIsNone(save.await_args.kwargs["embedding_api_key"])
        self.assertEqual(10 ** 12, save.await_args.kwargs["long_term_recall_limit"])
        self.assertEqual(
            main.LONG_TERM_RECALL_DEFAULT_CHAR_BUDGET,
            save.await_args.kwargs["long_term_recall_char_budget"],
        )
        self.assertEqual(
            main.LONG_TERM_RECALL_DEFAULT_ENTRY_CHAR_LIMIT,
            save.await_args.kwargs["long_term_recall_entry_char_limit"],
        )
        self.assertEqual(4, save.await_args.kwargs["title_provider_id"])
        self.assertEqual(5, save.await_args.kwargs["handoff_provider_id"])
        self.assertEqual("handoff-model", save.await_args.kwargs["handoff_model"])
        self.assertEqual(
            7, save.await_args.kwargs["temporary_summary_provider_id"]
        )
        self.assertEqual(
            "temporary-model",
            save.await_args.kwargs["temporary_summary_model"],
        )

    async def test_recall_character_limits_must_stay_within_supported_range(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "search_enabled": False,
            "title_enabled": False,
            "long_term_recall_char_budget": 200001,
        })
        save = AsyncMock()
        with patch.object(
            main,
            "get_conversation_model_settings",
            AsyncMock(return_value={}),
        ), patch.object(
            main, "get_model_task_settings", AsyncMock(return_value={})
        ), patch.object(main, "save_conversation_model_settings", save):
            response = await main.api_update_conversation_model_settings(request)

        self.assertEqual(400, response.status_code)
        save.assert_not_awaited()

    async def test_per_entry_character_limit_must_be_positive(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "search_enabled": False,
            "long_term_recall_char_budget": 2000,
            "long_term_recall_entry_char_limit": 0,
        })
        save = AsyncMock()
        with patch.object(
            main,
            "get_conversation_model_settings",
            AsyncMock(return_value={}),
        ), patch.object(
            main, "get_model_task_settings", AsyncMock(return_value={})
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

    async def test_temporary_summary_runtime_uses_its_own_provider_and_model(self):
        provider = {
            "id": 12,
            "api_url": "https://temporary.example/v1",
            "api_key": "temporary-key",
        }
        with patch.object(
            main, "get_conversation_model_settings", AsyncMock(return_value={
                "handoff_provider_id": 9,
                "handoff_model": "compact-model",
                "temporary_summary_provider_id": 12,
                "temporary_summary_model": "temporary-model",
            })
        ), patch.object(
            main, "get_openai_provider_profile", AsyncMock(return_value=provider)
        ):
            runtime = await main._load_temporary_summary_runtime()

        self.assertEqual("temporary-model", runtime["model"])
        self.assertEqual("https://temporary.example/v1", runtime["api_url"])
        self.assertEqual("temporary-key", runtime["api_key"])
        self.assertEqual("preset", runtime["source"])

    def test_model_settings_ui_uses_separate_vector_and_generation_cards(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")

        self.assertIn('<h3 class="recall-section-label">自动召回</h3>', dashboard)
        self.assertIn('id="crossConversationRecallEnabled"', dashboard)
        self.assertNotIn('id="longTermRecallEntryCharLimit"', dashboard)
        self.assertNotIn('id="longTermRecallTokenBudget"', dashboard)
        self.assertNotIn('<h3>历史会话</h3>', dashboard)
        self.assertNotIn('<strong>历史搜索</strong>', dashboard)
        self.assertNotIn('id="historyTitleEnabled"', dashboard)
        self.assertIn('<summary>Compact</summary>', dashboard)
        self.assertIn('id="temporarySummaryProvider"', dashboard)
        self.assertIn('id="temporarySummaryModel"', dashboard)

    async def test_each_submitted_task_setting_is_saved_independently(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "search_enabled": False,
            "long_term_recall_char_budget": 0,
            "long_term_recall_entry_char_limit": 200,
            "diary_merge_provider_id": 16,
            "diary_merge_model": "merge-model",
        })
        save_conversation = AsyncMock(return_value={})
        save_tasks = AsyncMock(return_value={
            "diary_merge": {"provider_id": 16, "model": "merge-model"},
        })
        with patch.object(
            main, "get_conversation_model_settings", AsyncMock(return_value={})
        ), patch.object(
            main, "get_model_task_settings", AsyncMock(return_value={})
        ), patch.object(
            main, "get_openai_provider_profile", AsyncMock(return_value={
                "api_url": "https://tasks.example/v1", "api_key": "key",
            })
        ), patch.object(
            main, "save_conversation_model_settings", save_conversation
        ), patch.object(main, "save_model_task_settings", save_tasks):
            result = await main.api_update_conversation_model_settings(request)

        self.assertEqual("ok", result["status"])
        save_tasks.assert_awaited_once_with({
            "diary_merge": {"provider_id": 16, "model": "merge-model"},
        })

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

    async def test_continuation_conversation_gets_title_with_gpt5_parameters(self):
        settings = {
            # Legacy switch state is ignored once provider + model are filled.
            "title_enabled": False,
            "title_provider_id": 7,
            "title_model": "gpt-5.6",
        }
        provider = {
            "api_url": "https://api.openai.com/v1",
            "api_key": "title-key",
        }
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"id": 42, "name": "延续会话"})
        conn.fetch = AsyncMock(return_value=[
            {
                "role": "user",
                "content": "自动标题怎么了",
                "content_json": [
                    {"type": "text", "text": "[系统参考资料] 不应进入标题\n\n【当前消息】"},
                    {"type": "text", "text": "自动标题怎么了"},
                ],
            },
            {"role": "assistant", "content": "我来检查", "content_json": None},
        ])
        conn.execute = AsyncMock(return_value="UPDATE 1")
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value = acquire
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"content": "自动标题排查"}}],
        }
        client = MagicMock()
        client.post = AsyncMock(return_value=response)

        with patch.object(
            main, "get_conversation_model_settings", AsyncMock(return_value=settings)
        ), patch.object(
            main, "_load_title_openai_provider", AsyncMock(return_value=provider)
        ), patch.object(
            main, "get_pool", AsyncMock(return_value=pool)
        ), patch.object(
            main, "get_http_client", AsyncMock(return_value=client)
        ):
            await main._maybe_generate_conversation_title(42)

        request_body = client.post.await_args.kwargs["json"]
        title_query = conn.fetch.await_args.args[0]
        self.assertIn("SELECT role, content, content_json", title_query)
        self.assertIn("(role = 'user' OR content_json IS NULL)", title_query)
        self.assertIn("用户：自动标题怎么了", request_body["messages"][0]["content"])
        self.assertNotIn("不应进入标题", request_body["messages"][0]["content"])
        self.assertEqual(512, request_body["max_completion_tokens"])
        self.assertEqual("low", request_body["reasoning_effort"])
        self.assertNotIn("max_tokens", request_body)
        update_args = conn.execute.await_args.args
        self.assertRegex(update_args[2], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} 自动标题排查$")
        self.assertEqual("延续会话", update_args[3])

    async def test_title_request_retries_transient_provider_failure(self):
        success = MagicMock(status_code=200)
        client = MagicMock()
        client.post = AsyncMock(side_effect=[
            main.httpx.ReadTimeout("temporary timeout"),
            success,
        ])

        with patch.object(main.asyncio, "sleep", AsyncMock()) as sleep:
            result = await main._request_title_completion(
                client,
                "https://provider.example/v1",
                {"Authorization": "Bearer key"},
                {"model": "title-model", "messages": []},
            )

        self.assertIs(success, result)
        self.assertEqual(2, client.post.await_count)
        sleep.assert_awaited_once()

    async def test_title_scheduler_retains_and_deduplicates_running_job(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def generate(_conv_id):
            started.set()
            await release.wait()

        main._title_generation_tasks.clear()
        with patch.object(main, "_maybe_generate_conversation_title", generate):
            first = main._schedule_conversation_title(42)
            await started.wait()
            second = main._schedule_conversation_title(42)

            self.assertIs(first, second)
            self.assertIs(first, main._title_generation_tasks[42])
            release.set()
            await first
            await asyncio.sleep(0)

        self.assertNotIn(42, main._title_generation_tasks)

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
        self.assertNotIn('id="memoryExtractionProvider"', dashboard)
        self.assertNotIn('id="fixedMemoryOrganizerProvider"', dashboard)
        self.assertNotIn('id="diaryDraftProvider"', dashboard)
        self.assertNotIn('id="diarySummaryProvider"', dashboard)
        self.assertIn('id="diaryKeywordProvider"', dashboard)
        self.assertIn('id="diaryMergeProvider"', dashboard)
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
        self.assertIn("🍅 M", page)
        self.assertIn("🫐 N", page)
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

    async def test_search_dispatch_reads_only_fragments(self):
        with patch.object(main,"MEMORY_ENABLED",True), patch.object(main.fragments,"search",AsyncMock(return_value=[])) as search:
            result = await main.dispatch_tool_call(
                "recall_fragments", {"query":"关键词","categories":["计划"]},
                current_conversation_id=7,
            )
        self.assertEqual("[]",result)
        search.assert_awaited_once_with(
            "关键词", ["计划"], excluded_conversation_id=7,
        )

    def test_history_tools_do_not_change_user_message_building(self):
        names = {tool["name"] for tool in main.BUILTIN_HISTORY_TOOLS}
        self.assertEqual({"recall_fragments"}, names)
        source = Path(main.__file__).read_text(encoding="utf-8")
        dispatch = source.split("async def dispatch_tool_call", 1)[1].split(
            "def _tool_result_succeeded", 1
        )[0]
        self.assertNotIn("_append_text_to_latest_user", dispatch)


if __name__ == "__main__":
    unittest.main()


class LocalHistorySettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_enable_without_embedding_and_preserve_legacy_configuration(self):
        request = MagicMock()
        weights = {'keyword': .4, 'text': .3, 'importance': .1, 'recency': .2, 'min_score': .3}
        request.json = AsyncMock(return_value={'search_enabled': True, 'history_recall_settings': weights})
        current = {'embedding_api_url': 'https://old.example/v1', 'embedding_model': 'legacy',
                   'embedding_api_key': 'legacy-key'}
        save = AsyncMock(return_value={'search_enabled': True, 'history_recall_settings': weights})
        with patch.object(main, 'get_conversation_model_settings', AsyncMock(return_value=current)), patch.object(
            main, 'get_model_task_settings', AsyncMock(return_value={})
        ), patch.object(main, 'save_conversation_model_settings', save):
            result = await main.api_update_conversation_model_settings(request)
        assert result['status'] == 'ok'
        assert result['history_recall_settings'] == weights
        assert save.await_args.kwargs['history_recall_settings'] == weights
        assert save.await_args.kwargs['embedding_model'] == 'legacy'
        assert save.await_args.kwargs['embedding_api_url'] == 'https://old.example/v1'
        assert save.await_args.kwargs['embedding_api_key'] is None
        request.json = AsyncMock(return_value={'search_enabled': True})
        with patch.object(main, 'get_conversation_model_settings', AsyncMock(return_value={})), patch.object(
            main, 'get_model_task_settings', AsyncMock(return_value={})
        ), patch.object(main, 'save_conversation_model_settings', save):
            assert (await main.api_update_conversation_model_settings(request))['status'] == 'ok'

    async def test_reject_invalid_weights_before_saving(self):
        for value in [-.1, 1.1, float('nan'), float('inf'), True, '0.3']:
            request = MagicMock()
            request.json = AsyncMock(return_value={'history_recall_settings': {'keyword': value}})
            with patch.object(main, 'get_conversation_model_settings', AsyncMock(return_value={})), patch.object(
                main, 'get_model_task_settings', AsyncMock(return_value={})
            ), patch.object(main, 'save_conversation_model_settings', AsyncMock()) as save:
                assert (await main.api_update_conversation_model_settings(request)).status_code == 400
                save.assert_not_awaited()

    async def test_database_persists_local_settings(self):
        from conversation_recall import DEFAULT_SEARCH
        conn = MagicMock(fetchrow=AsyncMock(return_value={'id': 1}), execute=AsyncMock())
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(database, 'get_pool', AsyncMock(return_value=pool)):
            result = await database.save_conversation_model_settings(
                search_enabled=True, embedding_api_url='', embedding_model='', embedding_api_key=None,
                long_term_recall_limit=5, long_term_recall_char_budget=2000, long_term_recall_entry_char_limit=200,
                title_enabled=False, title_provider_id=None, title_model='', handoff_provider_id=None,
                handoff_model='', history_recall_settings=DEFAULT_SEARCH)
        assert result['history_recall_settings'] == DEFAULT_SEARCH
        sql, saved = conn.execute.await_args.args
        import json
        assert 'history_recall_settings = $1::jsonb' in sql
        assert json.loads(saved) == DEFAULT_SEARCH

    def test_ui_describes_fragment_recall_and_diary_vector_search(self):
        page = Path('templates/dashboard.html').read_text()
        assert 'id="crossConversationRecallEnabled"' in page
        assert 'id="historySearchEnabled"' not in page
        for key in ['keyword', 'text', 'importance', 'recency', 'min_score']:
            assert f'id="historyRecall_{key}"' not in page
        assert 'id="historyEmbeddingUrl"' in page
        assert 'id="historyEmbeddingModel"' in page
        assert 'id="historyEmbeddingKey"' in page
        assert '跨对话片段召回' in page
        assert '日记语义搜索' in page
