import json
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import database
import main


class LongTermMemoryTests(unittest.TestCase):
    def test_flow_provenance_classifies_existing_rows_as_diaries(self):
        self.assertEqual(
            "diary",
            database.long_term_memory_kind({
                "metadata": {"source_flow_memory_id": 42},
            }),
        )
        self.assertEqual(
            "diary",
            database.long_term_memory_kind({"metadata": {}}),
        )
        self.assertEqual(
            "diary",
            database.long_term_memory_kind({
                "metadata": {
                    "source_flow_memory_id": 42,
                    "entry_kind": "diary",
                },
            }),
        )

    def test_long_term_directory_sorts_oldest_date_first(self):
        memories = [
            {"id": 3, "title": "后来", "memory_date": "2026-07-30"},
            {"id": 2, "title": "同日第二篇", "memory_date": "2026-07-29"},
            {"id": 1, "title": "同日第一篇", "memory_date": "2026-07-29"},
        ]

        ordered = sorted(memories, key=database._long_term_memory_sort_key)

        self.assertEqual([1, 2, 3], [memory["id"] for memory in ordered])

    def test_title_date_is_used_for_legacy_memory_sorting(self):
        memories = [
            {"id": 1, "title": "2026-07-30 后来"},
            {"id": 2, "title": "2026-07-28 更早"},
        ]

        ordered = sorted(memories, key=database._long_term_memory_sort_key)

        self.assertEqual([2, 1], [memory["id"] for memory in ordered])

    def test_unsummarized_promoted_memory_indexes_its_body(self):
        text = database._long_term_embedding_text({
            "title": "不应参与搜索的旧标题",
            "summary": "",
            "keywords": [],
            "content": "正文中的独特暗号",
            "metadata": {"entry_kind": "fragment"},
        })

        self.assertIn("正文中的独特暗号", text)
        self.assertNotIn("旧标题", text)

    def test_diary_search_indexes_body_even_when_a_search_hint_exists(self):
        text = database._long_term_embedding_text({
            "title": "一篇日记",
            "summary": "短提示",
            "keywords": [],
            "content": "正文中的独特暗号",
        })

        self.assertIn("短提示", text)
        self.assertIn("正文中的独特暗号", text)

    def test_dashboard_has_separate_long_term_editor(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

        self.assertIn('data-standing-view="long-term"', dashboard)
        self.assertIn('id="long-term-memory-title"', dashboard)
        self.assertIn('id="long-term-memory-date"', dashboard)
        self.assertIn('id="long-term-memory-summary-preview"', dashboard)
        self.assertIn('id="long-term-summary-modal"', dashboard)
        self.assertIn('id="long-term-summary-content"', dashboard)
        self.assertNotIn('id="long-term-summary-generate"', dashboard)
        self.assertIn('id="long-term-memory-content"', dashboard)
        self.assertIn('id="long-term-pending-list"', dashboard)
        self.assertIn('id="long-term-select-toggle"', dashboard)
        self.assertIn('id="long-term-selection-toolbar"', dashboard)
        self.assertIn('id="long-term-delete-selected"', dashboard)
        self.assertNotIn('data-standing-view="rules"', dashboard)
        self.assertNotIn('id="memory-tool-prompt-content"', dashboard)
        self.assertIn('authFetch("/api/diaries"', script)
        self.assertNotIn('/api/memory-tool-prompt', script)
        self.assertIn("approveLongTermMemoryProposal", script)
        self.assertIn("rejectLongTermMemoryProposal", script)
        self.assertIn("longTermMemoryDate", script)
        self.assertIn("compareLongTermMemoriesNewestFirst", script)
        self.assertIn("return rightDate.localeCompare(leftDate)", script)
        self.assertIn(
            ".sort(compareLongTermMemoriesNewestFirst)",
            script,
        )
        self.assertIn("long-term-month", script)
        self.assertNotIn("generateLongTermSummary", script)
        self.assertIn("toggleLongTermSelectionMode", script)
        self.assertIn("deleteSelectedLongTermMemories", script)
        self.assertIn('authFetch("/api/diaries/batch-delete"', script)
        self.assertNotIn('authFetch("/api/diaries/summary"', script)
        self.assertIn('" 篇待关键词"', script)
        self.assertIn(
            'input[type="date"]::-webkit-calendar-picker-indicator',
            (root / "static" / "css" / "dashboard.css").read_text(encoding="utf-8"),
        )
        self.assertIn('class="long-term-date-icon"', dashboard)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", (
            root / "static" / "css" / "dashboard.css"
        ).read_text(encoding="utf-8"))

    def test_ltm_exposes_one_step_fragment_search_and_two_step_diary_tools(self):
        tool_names = {tool["name"] for tool in main.BUILTIN_MEMORY_TOOLS}
        self.assertTrue({
            "search_memory", "search_diary", "read_diary",
        }.issubset(tool_names))
        self.assertNotIn("read_memory", tool_names)
        self.assertIn("read_memory", main.RETIRED_MODEL_TOOL_NAMES)
        self.assertNotIn("create_long_term_memory", tool_names)
        self.assertNotIn("edit_long_term_memory", tool_names)
        self.assertNotIn("delete_long_term_memory", tool_names)
        read_tool = next(
            tool for tool in main.BUILTIN_MEMORY_TOOLS
            if tool["name"] == "read_diary"
        )
        self.assertEqual(["id"], read_tool["input_schema"]["required"])
        self.assertNotIn("query", read_tool["input_schema"]["properties"])


class LongTermMemoryPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_prompt_preview_preserves_section_and_memory_order(self):
        with patch.object(
            main,
            "get_all_sections",
            AsyncMock(return_value=[
                {"key": "identity", "content": "IDENTITY"},
                {"key": "style", "content": "STYLE"},
            ]),
        ), patch.object(
            main,
            "_build_standing_memory_cache_blocks",
            AsyncMock(return_value=("FIXED", "FLOW")),
        ):
            preview = await main._build_prompt_splice_preview()

        self.assertEqual(
            ["prompt:identity", "prompt:style", "fixed_memory", "flow_memory"],
            [section["id"] for section in preview["sections"]],
        )
        self.assertEqual("IDENTITY\n\nSTYLE\n\nFIXED\n\nFLOW", preview["content"])

    async def test_diary_model_creates_long_term_pending_proposal(self):
        create_pending = AsyncMock(return_value={"id": 51})
        with patch.object(
            main,
            "_call_memory_organizer_model",
            AsyncMock(return_value=[
                {
                    "action": "new",
                    "title": "今天的日记",
                    "keywords": ["心情", "进展"],
                    "content": "今天完成了一次重要调整。",
                },
                {"action": "ignore"},
            ]),
        ), patch.object(
            main,
            "create_pending_long_term_memory_operation",
            create_pending,
        ):
            created = await main._create_recent_diary_long_term_drafts([
                {"role": "user", "content": "最近的对话"},
            ])

        self.assertEqual(1, created)
        create_pending.assert_awaited_once_with(
            "create",
            title="今天的日记",
            summary="心情；进展",
            content="今天完成了一次重要调整。",
            metadata={"entry_kind": "diary"},
        )

    def test_diary_action_lives_in_long_term_view(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "templates" / "dashboard.html").read_text(
            encoding="utf-8"
        )
        script = (root / "static" / "js" / "dashboard.js").read_text(
            encoding="utf-8"
        )
        directory = dashboard.split('id="standing-view-directory"', 1)[1].split(
            'id="standing-view-long-term"', 1
        )[0]
        long_term = dashboard.split('id="standing-view-long-term"', 1)[1].split(
            '</section>', 1
        )[0]

        self.assertNotIn("long-term-diary-btn", directory)
        self.assertIn("long-term-diary-btn", long_term)
        self.assertIn("/api/diaries/draft", script)
        self.assertNotIn("/api/standing-memory/recent-diary", script)

    async def test_standing_memory_is_in_cached_system_and_user_messages_are_untouched(self):
        user_messages = [{"role": "user", "content": "clean user message"}]
        standing_builder = AsyncMock(return_value=("FIXED", "FLOW"))
        with patch.object(main, "PROMPT_CACHE_ENABLED", True), patch.object(
            main, "get_all_sections", AsyncMock(return_value=[
                {"key": "Identity", "content": "CORE"},
                {"key": "Interaction", "content": "INTERACTION"},
            ])
        ), patch.object(
            main, "_build_standing_memory_cache_blocks", standing_builder
        ), patch.object(
            main, "build_dynamic_turn_block", AsyncMock(return_value="")
        ):
            system = await main.build_system_prompt_with_memories(
                "clean user message",
                user_messages,
                conv_id=7,
            )

        self.assertEqual("clean user message", user_messages[0]["content"])
        self.assertEqual(2, len(system))
        self.assertEqual("CORE\n\nFIXED", system[0]["text"])
        self.assertEqual("FLOW\n\nINTERACTION", system[1]["text"])
        standing_builder.assert_awaited_once_with()
        self.assertEqual(
            {"type": "ephemeral", "ttl": "1h"},
            system[0]["cache_control"],
        )
        self.assertEqual(
            {"type": "ephemeral", "ttl": "1h"},
            system[1]["cache_control"],
        )

    async def test_standing_prompt_does_not_contain_long_term_directory(self):
        with patch.object(
            main,
            "get_standing_memory_blocks",
            AsyncMock(return_value=[{
                "id": 4,
                "content": "常驻内容",
                "status": "active",
                "inject_enabled": True,
            }]),
        ):
            prompt = await main._build_standing_memory_prompt()

        self.assertIn("<content>常驻内容</content>", prompt)
        self.assertNotIn("Memory Access", prompt)
        self.assertNotIn("read_diary", prompt)
        self.assertNotIn("long_term_memory_catalog", prompt)
        self.assertNotIn("## Long-term Memories", prompt)

    async def test_search_diary_returns_keywords_without_body(self):
        search = AsyncMock(return_value=[{
            "id": 12,
            "title": "第一次搬家",
            "keywords": ["搬家", "纸箱"],
            "memory_date": "2026-08-11",
            "content": "不应出现在列表结果里的正文",
        }])
        with patch.object(
            main, "get_conversation_model_settings",
            AsyncMock(return_value={"search_enabled": True}),
        ), patch.object(main, "search_long_term_memory_summaries", search):
            result = json.loads(await main.dispatch_tool_call(
                "search_diary", {"query": "纸箱", "limit": 4}
            ))

        search.assert_awaited_once_with(
            "纸箱", {"search_enabled": True}, 4, entry_kind="diary"
        )
        self.assertEqual("第一次搬家", result["entries"][0]["title"])
        self.assertEqual(["搬家", "纸箱"], result["entries"][0]["keywords"])
        self.assertNotIn("search_hint", result["entries"][0])
        self.assertNotIn("content", result["entries"][0])

    async def test_search_tools_require_query(self):
        result = await main.dispatch_tool_call("search_memory", {})

        self.assertEqual("Error: query is required", result)

    async def test_search_memory_only_searches_fragments(self):
        settings = {"search_enabled": True}
        search = AsyncMock(return_value=[{
            "id": 9,
            "title": "雨夜",
            "content": "约定了暗号。",
            "memory_date": "2026-08-01",
        }])
        with patch.object(
            main, "get_conversation_model_settings", AsyncMock(return_value=settings)
        ), patch.object(main, "search_long_term_memory_summaries", search):
            result = json.loads(await main.dispatch_tool_call(
                "search_memory", {"query": "那个暗号", "limit": 4}
            ))

        search.assert_awaited_once_with(
            "那个暗号", settings, 4, entry_kind="fragment"
        )
        self.assertEqual("那个暗号", result["query"])
        self.assertEqual(9, result["entries"][0]["id"])
        self.assertEqual("约定了暗号。", result["entries"][0]["content"])
        self.assertNotIn("title", result["entries"][0])
        self.assertNotIn("memory_date", result["entries"][0])

    async def test_vector_recall_is_xml_background_context_without_body(self):
        search = AsyncMock(return_value=[{
            "id": 3,
            "title": "A < B & C",
            "content": "x < y，后来有了 a & b 的梗。",
        }])
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main,
            "get_conversation_model_settings",
            AsyncMock(return_value={"search_enabled": True, "long_term_recall_limit": 7}),
        ), patch.object(main, "search_long_term_memory_summaries", search):
            block = await main._build_long_term_recall_block("想起旧事")

        search.assert_awaited_once()
        self.assertEqual(main.LONG_TERM_RECALL_CANDIDATE_LIMIT, search.await_args.args[2])
        self.assertIn('role="background_context"', block)
        self.assertIn('<memory_recall source="system">', block)
        self.assertIn("此消息为碎片记忆召回", block)
        self.assertTrue(block.endswith("</memory_recall>"))
        self.assertIn("<recalled_memory_fragments", block)
        self.assertIn('<memory_fragment id="3">', block)
        self.assertNotIn("recalled_long_term_memories", block)
        self.assertIn(
            "<description>从日记旧摘要或会话中提取的碎片记忆；每条内容都可直接使用</description>",
            block,
        )
        self.assertNotIn("这不是用户说的话", block)
        self.assertNotIn("<title>", block)
        self.assertNotIn("<memory_date>", block)
        self.assertIn("<content>x &lt; y，后来有了 a &amp; b 的梗。</content>", block)

    async def test_vector_recall_uses_token_budget_instead_of_item_count(self):
        first = {"id": 1, "content": "甲" * 120}
        second = {"id": 2, "content": "乙" * 120}
        search = AsyncMock(return_value=[first])
        settings = {"search_enabled": True, "long_term_recall_limit": 1}
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "get_conversation_model_settings", AsyncMock(return_value=settings)
        ), patch.object(main, "search_long_term_memory_summaries", search):
            one_memory_block = await main._build_long_term_recall_block("旧事")
            budget = main._estimate_recall_tokens(one_memory_block)
            search.return_value = [first, second]
            settings["long_term_recall_token_budget"] = budget
            block = await main._build_long_term_recall_block("旧事")

        self.assertIn('<memory_fragment id="1">', block)
        self.assertNotIn('<memory_fragment id="2">', block)
        self.assertLessEqual(main._estimate_recall_tokens(block), budget)
        self.assertEqual(
            main.LONG_TERM_RECALL_CANDIDATE_LIMIT,
            search.await_args.args[2],
        )

    async def test_oversized_top_recall_is_truncated_to_budget(self):
        search = AsyncMock(return_value=[{
            "id": 7,
            "title": "仍然最相关",
            "content": "很长的摘要" * 500,
        }])
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main,
            "get_conversation_model_settings",
            AsyncMock(return_value={
                "search_enabled": True,
                "long_term_recall_token_budget": 256,
            }),
        ), patch.object(
            main, "search_long_term_memory_summaries", search
        ):
            block = await main._build_long_term_recall_block("旧事")

        self.assertIn('<memory_fragment id="7">', block)
        self.assertIn("…</content>", block)
        self.assertLessEqual(main._estimate_recall_tokens(block), 256)

    def test_auto_recall_query_uses_latest_three_conversation_turns(self):
        messages = [
            {"role": "user", "content": "第一轮用户"},
            {"role": "assistant", "content": "第一轮助手"},
            {"role": "user", "content": "第二轮用户提到了雨夜"},
            {"role": "assistant", "content": "第二轮助手提到了暗号"},
            {"role": "user", "content": "第三轮用户继续追问"},
            {"role": "assistant", "content": "第三轮助手回应"},
            {"role": "user", "content": "后来呢"},
        ]

        query = main._build_auto_recall_query("后来呢", messages)

        self.assertNotIn("第一轮用户", query)
        self.assertNotIn("第一轮助手", query)
        self.assertIn("用户：第二轮用户提到了雨夜", query)
        self.assertIn("助手：第二轮助手提到了暗号", query)
        self.assertIn("用户：后来呢", query)

    async def test_long_term_recall_searches_with_conversation_query_only(self):
        search = AsyncMock(return_value=[{
            "id": 6,
            "title": "雨夜",
            "content": "约定了暗号。",
        }])
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main,
            "get_conversation_model_settings",
            AsyncMock(return_value={"search_enabled": True, "long_term_recall_limit": 3}),
        ), patch.object(main, "search_long_term_memory_summaries", search):
            block = await main._build_long_term_recall_block(
                "后来呢",
                "用户：之前说到雨夜\n\n助手：约定了暗号\n\n用户：后来呢",
            )

        self.assertEqual(
            "用户：之前说到雨夜\n\n助手：约定了暗号\n\n用户：后来呢",
            search.await_args.args[0],
        )
        self.assertNotIn("之前说到雨夜", block)
        self.assertIn("<content>约定了暗号。</content>", block)

    async def test_generated_summary_uses_long_term_model_and_persona(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"content": [
                {"type": "text", "text": "一段贴合角色口吻的摘要。"},
            ]}}],
            "usage": {},
        }
        client = MagicMock()
        client.post = AsyncMock(return_value=response)
        build_persona = AsyncMock(return_value="温柔、克制地叙述。")
        with patch.object(
            main,
            "_load_long_term_summary_runtime",
            AsyncMock(return_value={
                "api_url": "https://memory.example/v1",
                "api_key": "secret",
                "model": "memory-model",
            }),
        ), patch.object(
            main, "MEMORY_ORGANIZER_MAX_TOKENS", 6000,
        ), patch.object(
            main, "build_system_prompt", build_persona
        ), patch.object(
            main, "get_http_client", AsyncMock(return_value=client)
        ), patch.object(main, "_record_token_usage", AsyncMock()):
            summary = await main._generate_long_term_memory_summary("雨夜", "那天约定了暗号。")

        self.assertEqual("一段贴合角色口吻的摘要。", summary)
        self.assertEqual(6000, client.post.await_args.kwargs["json"]["max_tokens"])
        build_persona.assert_awaited_once_with(
            include_sections=["Identity", "Interaction"]
        )
        system = client.post.await_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("<persona_context", system)
        self.assertIn("温柔、克制地叙述。", system)
        self.assertIn("不要把人格提示词本身写入摘要", system)

    async def test_failed_visible_summary_records_billed_usage(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "choices": [{
                "message": {"content": []},
                "finish_reason": "length",
            }],
            "usage": {"prompt_tokens": 20, "completion_tokens": 30},
        }
        client = MagicMock()
        client.post = AsyncMock(return_value=response)
        record_usage = AsyncMock()
        with patch.object(
            main,
            "_load_long_term_summary_runtime",
            AsyncMock(return_value={
                "api_url": "https://memory.example/v1",
                "api_key": "secret",
                "model": "memory-model",
            }),
        ), patch.object(
            main, "MEMORY_ORGANIZER_MAX_TOKENS", 6000,
        ), patch.object(
            main, "build_system_prompt", AsyncMock(return_value="")
        ), patch.object(
            main, "get_http_client", AsyncMock(return_value=client)
        ), patch.object(main, "_record_token_usage", record_usage):
            with self.assertRaisesRegex(RuntimeError, "finish_reason=length"):
                await main._generate_long_term_memory_summary("雨夜", "约定了暗号。")

        record_usage.assert_awaited_once()
        self.assertFalse(record_usage.await_args.args[5])
        self.assertEqual(20, record_usage.await_args.args[6]["input_tokens"])
        self.assertEqual(30, record_usage.await_args.args[6]["output_tokens"])

    async def test_diary_api_ignores_retired_summary_field(self):
        create = AsyncMock(return_value={"id": 1})
        create_request = MagicMock()
        create_request.json = AsyncMock(return_value={
            "title": "雨夜",
            "summary": "雨夜里约定了一个暗号。",
            "content": "完整正文",
        })
        update = AsyncMock(return_value={"id": 1})
        update_request = MagicMock()
        update_request.json = AsyncMock(return_value={
            "title": "雨夜",
            "summary": "更新后的摘要。",
            "content": "完整正文",
        })
        current = {
            "id": 1,
            "title": "雨夜",
            "summary": "旧摘要",
            "content": "完整正文",
            "memory_date": "2026-08-01",
            "priority": 7,
            "enabled": False,
        }

        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "create_long_term_memory", create
        ), patch.object(
            main, "get_long_term_memory", AsyncMock(return_value=current)
        ), patch.object(main, "update_long_term_memory", update):
            await main.api_create_long_term_memory(create_request)
            await main.api_update_long_term_memory(1, update_request)

        self.assertEqual([], create.await_args.kwargs["keywords"])
        self.assertIsNone(create.await_args.kwargs["summary"])
        self.assertIsNone(update.await_args.kwargs["keywords"])
        self.assertIsNone(update.await_args.kwargs["summary"])
        self.assertEqual(7, update.await_args.kwargs["priority"])
        self.assertFalse(update.await_args.kwargs["enabled"])
        self.assertEqual("2026-08-01", update.await_args.kwargs["memory_date"])

    def test_public_diary_contract_hides_legacy_field_names(self):
        diary = main._public_diary({
            "id": 7,
            "memory_date": "2026-09-06",
            "title": "今天",
            "summary": "旧摘要",
        })
        proposal = main._public_diary_proposal({
            "id": 8,
            "target_memory_id": 7,
            "memory_date": "2026-09-06",
        })

        self.assertEqual("2026-09-06", diary["diary_date"])
        self.assertNotIn("memory_date", diary)
        self.assertNotIn("summary", diary)
        self.assertEqual(7, proposal["target_diary_id"])
        self.assertNotIn("target_memory_id", proposal)

    def test_openapi_exposes_diary_routes_and_hides_legacy_routes(self):
        paths = main.app.openapi()["paths"]
        self.assertIn("/api/diaries", paths)
        self.assertIn("/api/diaries/{memory_id}", paths)
        self.assertIn("/api/standing-memory/{block_id}/to-diary", paths)
        self.assertFalse(any("long-term-memory" in path for path in paths))

    async def test_batch_delete_api_deduplicates_ids_and_reports_deleted_count(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={"ids": [9, 3, 9, 7]})
        delete_batch = AsyncMock(return_value=[3, 7])

        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "delete_long_term_memories_batch", delete_batch
        ):
            result = await main.api_delete_long_term_memories_batch(request)

        delete_batch.assert_awaited_once_with([3, 7, 9])
        self.assertEqual(3, result["requested"])
        self.assertEqual(2, result["deleted"])
        self.assertEqual([3, 7], result["deleted_ids"])

    def test_vector_recall_stays_after_cache_anchor(self):
        dynamic = '<recalled_diaries role="background_context">召回</recalled_diaries>'
        with patch.object(main, "PROMPT_CACHE_ENABLED", True), patch.object(
            main, "PROMPT_CACHE_MESSAGE_MODELS", {"claude-opus-4-6"}
        ):
            cached = main._inject_message_prompt_cache(
                [
                    {"role": "user", "content": "稳定问题"},
                    {"role": "assistant", "content": "稳定回答"},
                    {"role": "user", "content": "当前问题"},
                ],
                "claude-opus-4-6",
                dynamic_text=dynamic,
                cache_scope_id="long-term-recall-test",
            )

        self.assertTrue(any(
            isinstance(block, dict) and block.get("cache_control")
            for block in cached[0]["content"]
        ))
        self.assertTrue(cached[-1]["content"].endswith(dynamic))
        self.assertNotIn("cache_control", cached[-1])

    async def test_retired_read_memory_remains_compatible_with_old_tool_rounds(self):
        memory = {
            "id": 12,
            "title": "事件",
            "summary": "项目摘要",
            "memory_date": "2026-08-11",
            "content": "ABCDEFGHIJ",
            "enabled": True,
            "metadata": {"entry_kind": "fragment"},
        }
        with patch.object(
            main, "get_long_term_memory", AsyncMock(return_value=memory)
        ), patch.object(main, "LONG_TERM_MEMORY_READ_MAX_CHARS", 5):
            first = json.loads(await main.dispatch_tool_call(
                "read_memory", {"id": 12}
            ))
            second = json.loads(await main.dispatch_tool_call(
                "read_memory", {"id": 12, "offset": 5}
            ))

        self.assertEqual("ABCDE", first["content"])
        self.assertEqual(5, first["next_offset"])
        self.assertEqual("FGHIJ", second["content"])
        self.assertIsNone(second["next_offset"])
        self.assertEqual(10, first["total_chars"])
        self.assertEqual("项目摘要", first["summary"])

    async def test_read_diary_rejects_a_fragment_id(self):
        memory = {
            "id": 12,
            "title": "旧会话",
            "content": "原始会话摘要",
            "metadata": {"entry_kind": "fragment"},
        }
        with patch.object(
            main, "get_long_term_memory", AsyncMock(return_value=memory)
        ):
            result = await main.dispatch_tool_call("read_diary", {"id": 12})

            self.assertEqual("Error: diary entry not found", result)

    def test_public_fragment_has_only_id_and_text(self):
        fragment = main._public_memory_fragment({
            "id": 9,
            "title": "错误标题",
            "content": "2025 年初，约定了暗号。",
            "memory_date": "2026-08-11",
        })

        self.assertEqual({
            "id": 9,
            "content": "2025 年初，约定了暗号。",
        }, fragment)

    async def test_read_tool_reads_legacy_disabled_memory(self):
        with patch.object(
            main,
            "get_long_term_memory", AsyncMock(return_value={
                "id": 4,
                "title": "旧记录",
                "keywords": [],
                "content": "仍然可以读取",
                "enabled": False,
            }),
        ):
            result = json.loads(await main.dispatch_tool_call(
                "read_diary", {"id": 4},
            ))

        self.assertEqual("仍然可以读取", result["content"])

    def test_read_result_is_durable_but_not_a_cache_anchor(self):
        tool_id = "ltm-read-1"
        assistant = [{
            "type": "tool_use",
            "id": tool_id,
            "name": "read_diary",
            "input": {"id": 12},
        }]
        results = [{
            "type": "tool_result",
            "tool_use_id": tool_id,
            "content": "LONG BODY",
        }]
        internal_ids = deque(maxlen=200)
        with patch.object(main, "_internal_memory_tool_call_ids", internal_ids):
            main._remember_internal_memory_tool_call_id(tool_id)
            rows = main._durable_anthropic_tool_rows(assistant, results)
            self.assertEqual(["assistant", "tool"], [row["role"] for row in rows])
            self.assertEqual(tool_id, rows[0]["content_json"][0]["id"])
            self.assertEqual(
                "LONG BODY", rows[1]["content_json"][0]["content"]
            )
            result_message = {"role": "user", "content": results}
            self.assertTrue(main._is_internal_memory_tool_result_message(result_message))
            with patch.object(main, "PROMPT_CACHE_ENABLED", True), patch.object(
                main, "PROMPT_CACHE_MESSAGE_MODELS", {"claude-opus-4-6"}
            ):
                body = main._anthropic_body_for_request(
                    {
                        "model": "claude-opus-4-6",
                        "system": [{
                            "type": "text",
                            "text": "STABLE",
                            "cache_control": {"type": "ephemeral", "ttl": "1h"},
                        }],
                        "messages": [],
                    },
                    [
                        {"role": "user", "content": "question"},
                        {"role": "assistant", "content": assistant},
                        result_message,
                    ],
                    stream=False,
                    cache_scope_id="ltm-read-cache-test",
                )

        self.assertNotIn("cache_control", body["messages"][-1]["content"][0])

    def test_memory_tool_round_remains_visible_on_following_turn(self):
        rows = main._durable_anthropic_tool_rows(
            [{
                "type": "tool_use",
                "id": "pending-1",
                "name": "create_memory",
                "input": {"content": "今天完成了发布"},
            }],
            [{
                "type": "tool_result",
                "tool_use_id": "pending-1",
                "content": '{"status":"pending","proposal_id":17}',
            }],
        )

        rebuilt = main._strip_internal_tool_plumbing_for_history(
            main._rebuild_messages_from_rows(rows)
        )

        self.assertEqual("create_memory", rebuilt[0]["content"][0]["name"])
        self.assertEqual(
            '{"status":"pending","proposal_id":17}',
            rebuilt[1]["content"][0]["content"],
        )

    def test_legacy_injected_body_is_removed_from_model_history(self):
        activation = (
            '<long_term_memory_activation id="7" version="0123456789abcdef">'
            "旧版本注入的完整正文</long_term_memory_activation>"
        )
        cleaned = main._strip_internal_tool_plumbing_for_history([
            {"role": "user", "content": "真实问题"},
            {"role": "user", "content": activation},
            {"role": "assistant", "content": "回复"},
        ])

        self.assertEqual(2, len(cleaned))
        self.assertNotIn("旧版本注入的完整正文", str(cleaned))

    def test_dashboard_has_no_long_term_injection_toggle(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
        self.assertNotIn('id="long-term-memory-enabled"', dashboard)
        self.assertNotIn("启用召回", dashboard)
        self.assertNotIn("目录优先级", dashboard)
        self.assertNotIn('id="long-term-memory-priority"', dashboard)
        self.assertNotIn("加入模型目录", dashboard)
        self.assertNotIn("输入关键词后按 Enter 添加", dashboard)
        self.assertIn('id="long-term-summary-modal"', dashboard)
        self.assertNotIn("生成摘要", dashboard)
        self.assertIn("关键词", dashboard)
        self.assertIn("long-term-summary-preview", script)
        self.assertNotIn('byId("long-term-memory-enabled")', script)
        self.assertNotIn('byId("long-term-memory-priority")', script)

    def test_dashboard_preview_loads_the_actual_model_memory_context(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "templates" / "dashboard.html").read_text(
            encoding="utf-8"
        )
        script = (root / "static" / "js" / "dashboard.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("全部提示词拼接", dashboard)
        self.assertIn('id="prompt-splice-panel"', dashboard)
        settings = dashboard.split('id="section-settings"', 1)[1].split(
            'id="section-quotes"', 1
        )[0]
        self.assertIn("prompt-splice-panel", settings)
        self.assertNotIn("模型上下文", dashboard)
        self.assertNotIn("模型实际看到的记忆上下文", dashboard)
        self.assertIn('/api/prompt/splice-preview', script)
        self.assertIn("handlePromptPreviewToggle", script)
        self.assertNotIn("MemoryContext", script)
        self.assertNotIn("function renderStandingOverview()", script)

    async def test_prompt_preview_places_interaction_after_memories(self):
        with patch.object(main, "get_all_sections", AsyncMock(return_value=[
            {"key": "Identity", "content": "IDENTITY"},
            {"key": "Interaction", "content": "INTERACTION"},
        ])), patch.object(
            main, "_build_standing_memory_cache_blocks",
            AsyncMock(return_value=("FIXED", "FLOW")),
        ):
            preview = await main._build_prompt_splice_preview()

        self.assertEqual(
            ["prompt:Identity", "fixed_memory", "flow_memory", "prompt:Interaction"],
            [section["id"] for section in preview["sections"]],
        )
        self.assertLess(preview["content"].index("FLOW"), preview["content"].index("INTERACTION"))


class PendingLongTermMemoryDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_delete_uses_one_query_and_returns_deleted_ids(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[{"id": 8}, {"id": 3}])
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            deleted = await database.delete_long_term_memories_batch([8, 3, 8])

        query = conn.fetch.await_args.args[0]
        self.assertIn("DELETE FROM long_term_memories", query)
        self.assertIn("id = ANY($1::int[])", query)
        self.assertEqual([3, 8], conn.fetch.await_args.args[1])
        self.assertEqual([3, 8], deleted)

    async def test_summary_only_update_preserves_legacy_keywords(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={
            "id": 2,
            "title": "目录标题",
            "keywords": ["旧关键词"],
            "summary": "新的自然语言摘要。",
            "content": "完整正文",
        })
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            result = await database.update_long_term_memory(
                2,
                title="目录标题",
                keywords=None,
                summary="新的自然语言摘要。",
                content="完整正文",
            )

        query = conn.fetchrow.await_args.args[0]
        self.assertIn("keywords = COALESCE($3::jsonb, keywords)", query)
        self.assertIsNone(conn.fetchrow.await_args.args[3])
        self.assertEqual("新的自然语言摘要。", conn.fetchrow.await_args.args[4])
        self.assertEqual(["旧关键词"], result["keywords"])

    async def test_recent_catalog_query_has_no_app_cap_and_never_selects_content(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[{
            "id": 2,
            "title": "目录标题",
            "keywords": ["关键词"],
        }])
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            result = await database.get_recent_long_term_memory_catalog(10 ** 12)

        query = conn.fetch.await_args.args[0]
        selected = query.split("FROM long_term_memories", 1)[0]
        self.assertNotIn("content", selected)
        self.assertNotIn("WHERE enabled", query)
        self.assertIn("ORDER BY memory_date DESC NULLS LAST, id DESC", query)
        self.assertIn("LIMIT $1", query)
        self.assertEqual(10 ** 12, conn.fetch.await_args.args[1])
        self.assertNotIn("ORDER BY priority", query)
        self.assertEqual("目录标题", result[0]["title"])

    async def test_approve_edit_updates_target_then_removes_proposal(self):
        class AsyncContext:
            def __init__(self, value=None):
                self.value = value

            async def __aenter__(self):
                return self.value

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class Connection:
            def transaction(self):
                return AsyncContext()

            async def fetchrow(self, query, *args):
                if "FROM long_term_memory_proposals" in query:
                    return {
                        "id": 41,
                        "operation": "edit",
                        "target_memory_id": 12,
                        "title": "新标题",
                        "keywords": ["新关键词"],
                        "content": "新正文",
                    }
                if "SELECT * FROM long_term_memories" in query:
                    return {"id": 12, "title": "旧标题"}
                if "UPDATE long_term_memories" in query:
                    return {
                        "id": 12,
                        "title": args[1],
                        "keywords": ["新关键词"],
                        "content": args[3],
                    }
                raise AssertionError(query)

            async def execute(self, query, *args):
                self.deleted_proposal_id = args[0]
                return "DELETE 1"

        connection = Connection()

        class Pool:
            def acquire(self):
                return AsyncContext(connection)

        with patch.object(database, "get_pool", AsyncMock(return_value=Pool())):
            result = await database.apply_pending_long_term_memory_operation(41)

        self.assertEqual("edit", result["operation"])
        self.assertEqual(12, result["memory"]["id"])
        self.assertEqual(41, connection.deleted_proposal_id)


class LongTermMemoryRecallDatabaseTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _pool_with_connection(conn):
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire
        return pool

    def test_embedding_config_hash_changes_with_url_but_not_api_key(self):
        base = {
            "embedding_api_url": "https://embed-a.example/v1",
            "embedding_model": "shared-model-name",
            "embedding_api_key": "first-key",
        }
        rotated_key = {**base, "embedding_api_key": "second-key"}
        changed_url = {
            **base,
            "embedding_api_url": "https://embed-b.example/v1",
        }

        self.assertEqual(
            database._long_term_embedding_config_hash(base),
            database._long_term_embedding_config_hash(rotated_key),
        )
        self.assertNotEqual(
            database._long_term_embedding_config_hash(base),
            database._long_term_embedding_config_hash(changed_url),
        )

    async def test_refresh_persists_and_queries_embedding_config_hash(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(side_effect=[
            [{"id": 7, "title": "一次远足", "keywords": ["山路"]}],
            [],
        ])
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock(return_value=None)
        transaction.__aexit__ = AsyncMock(return_value=False)
        conn.transaction.return_value = transaction
        conn.execute = AsyncMock(return_value="OK")
        settings = {
            "embedding_api_url": "https://embed.example/v1",
            "embedding_model": "embed-model",
            "embedding_api_key": "secret",
        }
        config_hash = database._long_term_embedding_config_hash(settings)

        with patch.object(
            database, "get_pool", AsyncMock(return_value=self._pool_with_connection(conn))
        ), patch.object(
            database,
            "_embed_conversation_chunks",
            AsyncMock(return_value=[[1.0, 0.0]]),
        ):
            await database.refresh_long_term_memory_embeddings(settings)

        existing_query = conn.fetch.await_args_list[1]
        self.assertIn("embedding_config_hash = $2", existing_query.args[0])
        self.assertEqual(("embed-model", config_hash), existing_query.args[1:])
        insert_call = next(
            call for call in conn.execute.await_args_list
            if "INSERT INTO long_term_memory_embeddings" in call.args[0]
        )
        self.assertEqual(config_hash, insert_call.args[-1])

    async def test_search_schedules_refresh_and_filters_weak_semantic_matches(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[
            {
                "id": 1,
                "title": "完全无关",
                "keywords": [],
                "memory_date": None,
                "embedding": [0.2, 0.98],
            },
            {
                "id": 2,
                "title": "语义相关",
                "keywords": [],
                "memory_date": None,
                "embedding": [1.0, 0.0],
            },
            {
                "id": 3,
                "title": "project 记录",
                "keywords": [],
                "memory_date": None,
                "embedding": [0.2, 0.98],
            },
        ])
        settings = {
            "embedding_api_url": "https://embed.example/v1",
            "embedding_model": "embed-model",
            "embedding_api_key": "secret",
        }
        schedule = MagicMock(return_value=True)
        with patch.object(
            database, "get_pool", AsyncMock(return_value=self._pool_with_connection(conn))
        ), patch.object(
            database,
            "_embed_conversation_chunks",
            AsyncMock(return_value=[[1.0, 0.0]]),
        ), patch.object(
            database, "schedule_long_term_memory_embedding_refresh", schedule
        ), patch.object(database, "LONG_TERM_RECALL_MIN_SEMANTIC_SCORE", 0.35):
            result = await database.search_long_term_memory_summaries(
                "remember project", settings, 10
            )

        schedule.assert_called_once_with(settings)
        self.assertEqual([2, 3], [item["id"] for item in result])
        search_call = conn.fetch.await_args
        self.assertIn("e.embedding_config_hash = $2", search_call.args[0])
        self.assertEqual(
            database._long_term_embedding_config_hash(settings),
            search_call.args[2],
        )

    async def test_query_embedding_timeout_falls_back_to_keywords(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[{
            "id": 9,
            "title": "project 记录",
            "keywords": [],
            "memory_date": None,
            "embedding": [1.0, 0.0],
        }])
        settings = {
            "embedding_api_url": "https://embed.example/v1",
            "embedding_model": "embed-model",
            "embedding_api_key": "secret",
        }

        async def slow_embedding(*_args, **_kwargs):
            import asyncio
            await asyncio.sleep(1)

        with patch.object(
            database, "get_pool", AsyncMock(return_value=self._pool_with_connection(conn))
        ), patch.object(
            database, "_embed_conversation_chunks", slow_embedding
        ), patch.object(
            database, "schedule_long_term_memory_embedding_refresh", MagicMock()
        ), patch.object(database, "LONG_TERM_RECALL_EMBEDDING_TIMEOUT", 0.001):
            result = await database.search_long_term_memory_summaries(
                "project", settings, 5
            )

        self.assertEqual([9], [item["id"] for item in result])


if __name__ == "__main__":
    unittest.main()
