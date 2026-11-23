import hashlib
import json
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import database
import main


class LongTermMemoryTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_approved_diary_does_not_persist_preview_summary_as_fragment_source(self):
        conn = MagicMock()
        conn.transaction.return_value.__aenter__ = AsyncMock()
        conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
        conn.fetchrow = AsyncMock(side_effect=[
            {
                "id": 41,
                "operation": "create",
                "target_memory_id": None,
                "title": "海边",
                "keywords": ["旅行", "朋友"],
                "summary": "旅行；朋友",
                "content": "和朋友去了海边。",
                "metadata": {"source_command": "diary"},
                "priority": 0,
                "enabled": True,
            },
            {
                "id": 12,
                "title": "海边",
                "keywords": ["旅行", "朋友"],
                "summary": "",
                "content": "和朋友去了海边。",
                "metadata": {"entry_kind": "diary"},
            },
        ])
        conn.execute = AsyncMock(return_value="DELETE 1")
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            result = await database.apply_pending_long_term_memory_operation(41)

        insert = conn.fetchrow.await_args_list[1]
        self.assertIn("VALUES ($1, $2::jsonb, '', $3", insert.args[0])
        metadata = json.loads(insert.args[-1])
        self.assertEqual("diary", metadata["entry_kind"])
        self.assertEqual("diary", metadata["source_command"])
        self.assertEqual("create", result["operation"])

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

    def test_unsummarized_diary_indexes_its_body(self):
        text = database._long_term_embedding_text({
            "title": "不应参与搜索的旧标题",
            "summary": "",
            "keywords": [],
            "content": "正文中的独特暗号",
        })

        self.assertIn("正文中的独特暗号", text)
        self.assertIn("旧标题", text)

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

        self.assertIn('id="diary-notebook"', dashboard)
        self.assertNotIn('data-standing-view="long-term"', dashboard)
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
        routes = {route.path for route in main.app.routes}
        self.assertNotIn('/api/diaries/summary', routes)
        self.assertNotIn('/api/long-term-memory/summary', routes)
        self.assertIn('" 篇待关键词"', script)
        self.assertIn('id="diary-calendar-month-picker"', dashboard)
        self.assertIn('type="date" aria-label="日期"', dashboard)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", (
            root / "static" / "css" / "dashboard.css"
        ).read_text(encoding="utf-8"))

    def test_fragment_view_and_extraction_controls_are_removed(self):
        dashboard = (Path(__file__).resolve().parents[1] / "templates/dashboard.html").read_text()
        for element in ("standing-view-fragments", "memory-fragment-editor-modal", "memoryExtractionProvider"):
            self.assertNotIn('id="' + element + '"', dashboard)
        self.assertIn("历史召回", dashboard)

    def test_ltm_exposes_diary_tools(self):
        tool_names = {tool["name"] for tool in main.BUILTIN_MEMORY_TOOLS}
        self.assertTrue({
            "search_diary", "read_diary",
        }.issubset(tool_names))
        self.assertTrue({
            "create_memory", "edit_memory", "delete_memory",
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
            [
                "prompt:identity", "prompt:style", "fixed_memory", "flow_memory",
            ],
            [section["id"] for section in preview["sections"]],
        )
        self.assertEqual(
            "IDENTITY\n\nSTYLE\n\nFIXED\n\nFLOW",
            preview["content"],
        )

    def test_retired_diary_draft_ui_removed(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
        self.assertNotIn("long-term-diary-btn", dashboard)
        self.assertNotIn("/api/diaries/draft", script)
        self.assertIn('id="diary-notebook"', dashboard)

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
        self.assertEqual(
            "CORE\n\nFIXED\n\nINTERACTION",
            system[0]["text"],
        )
        self.assertEqual("FLOW", system[1]["text"])
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
        settings = {"search_enabled": False, "nocturne_recall_enabled": False,
                    "embedding_api_url": "https://embedding.test/v1",
                    "embedding_model": "test", "embedding_api_key": "key"}
        with patch.object(
            main, "get_conversation_model_settings",
            AsyncMock(return_value=settings),
        ), patch.object(main, "search_long_term_memory_summaries", search):
            result = json.loads(await main.dispatch_tool_call(
                "search_diary", {"query": "纸箱", "limit": 4}
            ))

        search.assert_awaited_once_with(
            "纸箱", settings, 4
        )
        self.assertEqual("第一次搬家", result["entries"][0]["title"])
        self.assertEqual(["搬家", "纸箱"], result["entries"][0]["keywords"])
        self.assertNotIn("search_hint", result["entries"][0])
        self.assertNotIn("content", result["entries"][0])

    async def test_search_tools_require_query(self):
        result = await main.dispatch_tool_call("search_memory", {})

        self.assertEqual("Error: query is required", result)

    async def test_in_flight_legacy_search_reads_fragments(self):
        with patch.object(main,'MEMORY_ENABLED',True), patch.object(main.fragments,'search',AsyncMock(return_value=[])) as search:
            await main.dispatch_tool_call("search_memory", {"query":"那个暗号"})
        search.assert_awaited_once_with("那个暗号",[])

    def test_topic_switch_ignores_previous_long_assistant_reply(self):
        query = main._build_auto_recall_query('咖啡馆有什么偏好', [
            {'role': 'user', 'content': '聊聊钢琴'},
            {'role': 'assistant', 'content': '钢琴' * 3000},
        ])
        self.assertEqual('用户：咖啡馆有什么偏好', query)

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

    def test_auto_recall_query_ignores_persisted_system_reference_envelope(self):
        message = {"role": "user", "content": "用户真正说的话"}
        main._prepend_system_reference_to_user(message, "不应再次召回的后台资料")

        query = main._build_auto_recall_query("用户真正说的话", [message])

        self.assertEqual("用户：用户真正说的话", query)
        self.assertEqual("用户真正说的话", main._latest_plain_user_text([message]))

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

    async def test_diary_list_api_returns_only_lightweight_fields(self):
        rows = [{
            "id": 7,
            "title": "今天",
            "memory_date": "2026-09-06",
            "keywords": ["散步"],
            "content": "不应进入列表的完整正文",
            "metadata": {"merge_sources": [{"content": "很大的旧日记全文"}]},
        }]
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "get_diary_list", AsyncMock(return_value=rows)
        ):
            result = await main.api_list_long_term_memory()

        self.assertEqual({
            "diaries": [{
                "author_role": "assistant",
                "id": 7,
                "title": "今天",
                "diary_date": "2026-09-06",
                "keywords": ["散步"],
            }]
        }, result)
        self.assertNotIn("content", result["diaries"][0])
        self.assertNotIn("metadata", result["diaries"][0])

    async def test_diary_detail_api_still_returns_content_and_metadata(self):
        diary = {
            "id": 7,
            "title": "今天",
            "memory_date": "2026-09-06",
            "keywords": ["散步"],
            "content": "完整正文",
            "metadata": {"entry_kind": "diary", "merge_sources": []},
        }
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "get_long_term_memory", AsyncMock(return_value=diary)
        ):
            result = await main.api_get_long_term_memory(7)

        self.assertEqual("完整正文", result["content"])
        self.assertEqual([], result["metadata"]["merge_sources"])

    async def test_pending_api_keeps_full_proposal_and_target_for_diff(self):
        proposal = {
            "id": 9,
            "operation": "edit",
            "target_memory_id": 7,
            "memory_date": "2026-09-06",
            "title": "新标题",
            "keywords": [],
            "content": "新正文",
            "metadata": {"merge_sources": [{"content": "合并前原文"}]},
        }
        target = {
            "id": 7,
            "memory_date": "2026-09-06",
            "title": "旧标题",
            "keywords": [],
            "content": "旧正文",
            "metadata": {"entry_kind": "diary"},
        }
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "get_pending_long_term_memory_operations",
            AsyncMock(return_value=[proposal]),
        ), patch.object(
            main, "get_long_term_memory", AsyncMock(return_value=target)
        ):
            result = await main.api_list_pending_long_term_memory()

        item = result["pending"][0]
        self.assertEqual("新正文", item["content"])
        self.assertEqual("合并前原文", item["metadata"]["merge_sources"][0]["content"])
        self.assertEqual("旧正文", item["target_diary"]["content"])

    def test_openapi_exposes_diary_routes_and_hides_legacy_routes(self):
        paths = main.app.openapi()["paths"]
        self.assertIn("/api/diaries", paths)
        self.assertIn("/api/diaries/pending", paths)
        self.assertIn("/api/diaries/{memory_id}", paths)
        self.assertNotIn("/api/fragments", paths)
        self.assertNotIn("/api/fragments/{memory_id}", paths)
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

    def test_read_result_is_durable_and_can_extend_the_cache(self):
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

        self.assertEqual({"type": "ephemeral", "ttl": "1h"},
                         body["messages"][-1]["content"][0]["cache_control"])

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
        prompt_page = (root / "templates" / "prompt.html").read_text(
            encoding="utf-8"
        )
        script = (root / "static" / "js" / "dashboard.js").read_text(
            encoding="utf-8"
        )

        self.assertNotIn('id="prompt-splice-panel"', dashboard)
        self.assertIn("/api/prompt/splice-preview", prompt_page)
        self.assertIn("box.textContent = data.content", prompt_page)
        self.assertIn("data.full_prompt_chars", prompt_page)
        self.assertNotIn("<details", prompt_page.split(
            'id="panel-preview"', 1
        )[1].split('id="panel-logs"', 1)[0])
        self.assertNotIn("模型上下文", dashboard)
        self.assertNotIn("模型实际看到的记忆上下文", dashboard)
        self.assertNotIn('/api/prompt/splice-preview', script)
        self.assertNotIn("handlePromptPreviewToggle", script)
        self.assertNotIn("MemoryContext", script)
        self.assertNotIn("function renderStandingOverview()", script)

    async def test_prompt_preview_places_timeline_after_interaction(self):
        with patch.object(main, "get_all_sections", AsyncMock(return_value=[
            {"key": "Identity", "content": "IDENTITY"},
            {"key": "Interaction", "content": "INTERACTION"},
        ])), patch.object(
            main, "_build_standing_memory_cache_blocks",
            AsyncMock(return_value=("FIXED", "FLOW")),
        ):
            preview = await main._build_prompt_splice_preview()

        self.assertEqual(
            [
                "prompt:Identity", "fixed_memory",
                "prompt:Interaction", "flow_memory",
            ],
            [section["id"] for section in preview["sections"]],
        )
        self.assertLess(preview["content"].index("INTERACTION"), preview["content"].index("FLOW"))
        self.assertNotIn("回忆录", preview["content"])

    async def test_prompt_page_character_count_uses_the_full_splice(self):
        sections = [
            {"key": "Identity", "content": "IDENTITY"},
            {"key": "Interaction", "content": "INTERACTION"},
        ]
        with patch.object(
            main, "get_all_sections", AsyncMock(return_value=sections),
        ), patch.object(
            main, "_build_prompt_splice_preview",
            AsyncMock(return_value={"character_count": 1234}),
        ) as preview:
            result = await main.api_prompt()

        self.assertEqual(1234, result["full_prompt_chars"])
        self.assertEqual(len("IDENTITY\n\nINTERACTION"), result["total_chars"])
        preview.assert_awaited_once_with(sections)


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

    async def test_embedding_tasks_are_sent_only_to_jina_models(self):
        requests = []

        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {"data": [{"index": 0, "embedding": [1, 2]}]}

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def post(self, _url, **kwargs):
                requests.append(kwargs["json"])
                return Response()

        with patch.object(database.httpx, "AsyncClient", return_value=Client()):
            await database._embed_conversation_chunks(
                ["query"],
                {"embedding_model": "jina-embeddings-v3"},
                task="retrieval.query",
            )
            await database._embed_conversation_chunks(
                ["query"],
                {"embedding_model": "other-embedding-model"},
                task="retrieval.query",
            )
            await database._embed_conversation_chunks(
                ["query"],
                {"embedding_model": "jina-embeddings-v2-base-en"},
                task="retrieval.query",
            )

        self.assertEqual("retrieval.query", requests[0]["task"])
        self.assertNotIn("task", requests[1])
        self.assertNotIn("task", requests[2])

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

        embed = AsyncMock(return_value=[[1.0, 0.0]])
        with patch.object(
            database, "get_pool", AsyncMock(return_value=self._pool_with_connection(conn))
        ), patch.object(
            database,
            "_embed_conversation_chunks",
            embed,
        ):
            await database.refresh_long_term_memory_embeddings(settings)

        embed.assert_awaited_once_with(
            ["一次远足\n山路"],
            settings,
            task="retrieval.passage",
        )

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
        for row in conn.fetch.return_value:
            row['embedding_content_hash'] = hashlib.sha256(
                database._long_term_embedding_text(row).encode()
            ).hexdigest()
        settings = {
            "embedding_api_url": "https://embed.example/v1",
            "embedding_model": "embed-model",
            "embedding_api_key": "secret",
        }
        schedule = MagicMock(return_value=True)
        embed = AsyncMock(return_value=[[1.0, 0.0]])
        with patch.object(
            database, "get_pool", AsyncMock(return_value=self._pool_with_connection(conn))
        ), patch.object(
            database,
            "_embed_conversation_chunks",
            embed,
        ), patch.object(
            database, "schedule_long_term_memory_embedding_refresh", schedule
        ), patch.object(database, "LONG_TERM_RECALL_MIN_SEMANTIC_SCORE", 0.35):
            result = await database.search_long_term_memory_summaries(
                "remember project", settings, 10
            )

        schedule.assert_called_once_with(settings)
        embed.assert_awaited_once_with(
            ["remember project"],
            settings,
            task="retrieval.query",
        )
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
