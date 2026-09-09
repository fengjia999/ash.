import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import database
import main


class PageLoadingAssetTests(unittest.TestCase):
    def test_section_headings_stay_horizontal_when_stats_are_long(self):
        css = (
            Path(__file__).resolve().parents[1] / "static" / "css" / "dashboard.css"
        ).read_text(encoding="utf-8")
        heading_rule = css.split(".section-header h1 {", 1)[1].split("}", 1)[0]

        self.assertIn("flex: 0 0 auto;", heading_rule)
        self.assertIn("white-space: nowrap;", heading_rule)

    def test_management_pages_have_no_render_blocking_google_fonts(self):
        root = Path(__file__).resolve().parents[1]
        sources = [
            (root / "templates" / "context.html").read_text(encoding="utf-8"),
            (root / "templates" / "dashboard.html").read_text(encoding="utf-8"),
            (root / "static" / "css" / "dashboard.css").read_text(encoding="utf-8"),
        ]

        for source in sources:
            self.assertNotIn("fonts.googleapis.com", source)

    def test_dashboard_initializes_only_the_visible_memory_section(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "static" / "js" / "dashboard.js").read_text(
            encoding="utf-8"
        )
        startup = script.split(
            'document.addEventListener("DOMContentLoaded", () => {', 1
        )[1].split("});", 1)[0]

        self.assertIn("loadConversationListFrame();", startup)
        self.assertIn(' : "conversations"', startup)
        self.assertNotIn("loadLongTermMemory();", startup)
        self.assertNotIn("loadMemoryToolPrompt();", startup)
        self.assertNotIn("loadPromptSplicePreview();", startup)
        self.assertNotIn("loadExportStats();", startup)
        self.assertNotIn("loadMemories();", startup)
        self.assertIn("/api/conversations?include_stats=true", script)
        self.assertIn('["fragments", "long-term"].includes(viewName)', script)

    def test_conversation_messages_are_loaded_in_small_pages(self):
        template = (
            Path(__file__).resolve().parents[1] / "templates" / "context.html"
        ).read_text(encoding="utf-8")

        self.assertIn("const MESSAGE_PAGE_SIZE = 50;", template)
        self.assertIn("加载更早消息", template)
        self.assertIn("messages?limit=${MESSAGE_PAGE_SIZE}", template)
        self.assertNotIn('onclick="editMsg(${m.id}', template)

    def test_dashboard_conversation_hub_keeps_list_and_detail_lazy(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "templates" / "dashboard.html").read_text(
            encoding="utf-8"
        )
        script = (root / "static" / "js" / "dashboard.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('data-section="conversations"', dashboard)
        self.assertIn('id="conversation-list-frame"', dashboard)
        self.assertIn('id="conversation-detail-frame"', dashboard)
        conversation_section = dashboard.split(
            'id="section-conversations"', 1
        )[1].split('</section>', 1)[0]
        sidebar = dashboard.split('<aside class="sidebar">', 1)[1].split(
            '</aside>', 1
        )[0]
        self.assertIn('id="conversation-list-frame"', conversation_section)
        self.assertNotIn('id="conversation-list-frame"', sidebar)
        self.assertNotIn('id="conversation-empty"', dashboard)
        self.assertNotIn('id="conversation-list-frame" src=', dashboard)
        self.assertNotIn('id="conversation-detail-frame" src=', dashboard)
        self.assertIn('frame.src = "/context?embedded=list";', script)
        self.assertIn('embedded: "detail"', script)
        self.assertIn('frame.removeAttribute("src");', script)
        self.assertNotIn("loadActiveConversation", script)

    def test_dashboard_prompt_editor_is_a_lazy_embedded_branch(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "templates" / "dashboard.html").read_text(
            encoding="utf-8"
        )
        script = (root / "static" / "js" / "dashboard.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('data-section="prompts"', dashboard)
        self.assertIn('id="section-prompts"', dashboard)
        self.assertIn('id="prompt-console-frame"', dashboard)
        self.assertNotIn('id="prompt-console-frame" class="prompt-console-frame" title="提示词编辑器" src=', dashboard)
        self.assertIn('frame.src = "/prompt?embedded=dashboard";', script)

    def test_dashboard_distinguishes_current_and_original_repositories(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "templates" / "dashboard.html").read_text(
            encoding="utf-8"
        )
        readme = (root / "README.md").read_text(encoding="utf-8")

        self.assertIn("public_repository_url", dashboard)
        self.assertIn("当前项目 · Ash", dashboard)
        self.assertIn(
            "https://github.com/garan0613/ai-memory-gateway", dashboard
        )
        self.assertIn("感谢原作者提供网关的原始框架", readme)
        self.assertIn("面向昂贵模型", readme)
        self.assertIn("MCP", readme)
        self.assertIn("https://github.com/fengjia999/Ash-public", readme)
        self.assertIn("https://github.com/fengjia999/Photon", readme)
        self.assertIn("Advanced integration", readme)

    def test_mobile_sidebar_uses_a_click_blocking_backdrop(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "templates" / "dashboard.html").read_text(
            encoding="utf-8"
        )
        css = (root / "static" / "css" / "dashboard.css").read_text(
            encoding="utf-8"
        )

        self.assertIn('class="mobile-sidebar-backdrop"', dashboard)
        self.assertIn('onclick="toggleHistorySidebar()"', dashboard)
        open_rule = css.split(
            "body.history-open .mobile-sidebar-backdrop {", 1
        )[1].split("}", 1)[0]
        self.assertIn("pointer-events:auto", open_rule.replace(" ", ""))
        self.assertNotIn("100vmax", css)

    def test_embedded_conversation_ui_preserves_existing_controls_and_sort(self):
        template = (
            Path(__file__).resolve().parents[1] / "templates" / "context.html"
        ).read_text(encoding="utf-8")

        for text in (
            "摘要", "选择", "+ 新建", "仅追加",
            "发送并触发回复", "🟠", "🔵",
        ):
            self.assertIn(text, template)
        self.assertIn(
            "conversationDate(b, 'started_at').localeCompare("
            "conversationDate(a, 'started_at')) || b.id - a.id",
            template,
        )
        self.assertIn("const MESSAGE_PAGE_SIZE = 50;", template)
        self.assertIn("function showHandoffSummary()", template)
        self.assertNotIn("整理记忆", template)
        self.assertNotIn("memory-scan", template)
        self.assertIn("function setRole(role)", template)
        self.assertIn("function send(trigger)", template)

        dashboard = (
            Path(__file__).resolve().parents[1] / "templates" / "dashboard.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn('data-standing-view="rules"', dashboard)
        self.assertNotIn("memory-tool-prompt", dashboard)

    def test_detail_view_skips_full_conversation_list(self):
        template = (
            Path(__file__).resolve().parents[1] / "templates" / "context.html"
        ).read_text(encoding="utf-8")

        startup = template.split("// ── 启动 ──", 1)[1]
        self.assertIn(
            "if (CONTEXT_EMBED_MODE === 'list') loadConversations();",
            startup,
        )

        select_conversation = template.split("function selectConv(id, activate = false) {", 1)[1].split(
            "function createMessageElement", 1
        )[0]
        self.assertNotIn("loadConversations();", select_conversation)

        load_messages = template.split("function loadMessages(convId, beforeId = null) {", 1)[
            1
        ].split("function toggleSelectionMode", 1)[0]
        self.assertNotIn("memoryScan", template)
        self.assertIn("document.createDocumentFragment()", template)
        self.assertIn("list.replaceChildren(fragment);", template)

    def test_embedded_views_render_only_their_own_navigation(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates" / "context.html").read_text(
            encoding="utf-8"
        )
        script = (root / "static" / "js" / "dashboard.js").read_text(
            encoding="utf-8"
        )
        dashboard = (root / "templates" / "dashboard.html").read_text(
            encoding="utf-8"
        )

        app_markup = template.split('{% if embedded == \'detail\' %}', 1)[1].split(
            "{% endif %}", 1
        )[0]
        list_markup = template.split('{% if embedded == \'list\' %}', 1)[1].split(
            "{% endif %}", 1
        )[0]
        self.assertIn('class="app"', app_markup)
        self.assertNotIn('id="sidebar"', app_markup)
        self.assertIn('id="sidebar"', list_markup)
        self.assertNotIn('class="app"', list_markup)
        self.assertIn("return messageLoading;", template)
        self.assertIn("postContextStatus('error'", template)
        self.assertIn("function handleConversationTap(", template)
        self.assertIn("CONVERSATION_DOUBLE_TAP_MS", template)
        self.assertIn(".conv-item.settings-visible .conv-gear", template)
        self.assertIn("memory-gateway-context-status", script)
        self.assertIn('id="conversation-list-retry"', dashboard)

        context_template = main.templates.env.get_template("context.html")
        common = {
            "request": MagicMock(),
            "csrf_token": "token",
            "initial_conversation_id": 7,
            "show_created_modal": False,
        }
        detail_page = context_template.render(embedded="detail", **common)
        list_page = context_template.render(embedded="list", **common)
        self.assertIn('class="app"', detail_page)
        self.assertNotIn('id="sidebar"', detail_page)
        self.assertIn('id="sidebar"', list_page)
        self.assertNotIn('class="app"', list_page)


class ConversationDashboardRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_directory_payload_omits_duplicate_text_but_preserves_counts(self):
        blocks = [{"id": 1, "status": "active", "layer": "core", "content": "记忆" * 10000}]
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "get_standing_memory_blocks", AsyncMock(side_effect=[blocks, [], blocks, []])
        ), patch.object(
            main, "get_long_term_memory_counts",
            AsyncMock(return_value={"memory_count": 4, "pending_count": 2}),
        ), patch.object(
            main, "get_flow_memory_settings", AsyncMock(return_value={"max_items": 8})
        ):
            full = await main.api_list_standing_memory()
            directory = await main.api_list_standing_memory(include_overview_content=False)

        self.assertIn("content", full["overview"])
        self.assertNotIn("content", directory["overview"])
        self.assertEqual(full["blocks"], directory["blocks"])
        self.assertEqual(
            {key: value for key, value in full["overview"].items() if key != "content"},
            directory["overview"],
        )

    async def test_standalone_context_page_moves_to_dashboard_conversations(self):
        request = MagicMock()
        request.query_params = {}

        response = await main.context_page(request)

        self.assertEqual(303, response.status_code)
        self.assertEqual("/dashboard#conversations", response.headers["location"])


class ConversationLoadingDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_lightweight_conversation_list_counts_only_active_messages(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            result = await database.get_all_conversations(include_message_stats=False)

        self.assertEqual([], result)
        query = conn.fetch.await_args.args[0]
        self.assertIn("CASE WHEN c.is_active", query)
        self.assertIn("m.conversation_id = c.id", query)
        self.assertNotIn("GROUP BY", query)
        self.assertNotIn("handoff_summary", query)

    def test_current_conversation_status_includes_message_count(self):
        template = (
            Path(__file__).resolve().parents[1] / "templates" / "context.html"
        ).read_text(encoding="utf-8")

        self.assertIn("`${Number(c.message_count)} 条`", template)
        self.assertIn("`已载入 ${Number(c.message_count)}", template)
        self.assertIn("总数计算中…", template)
        self.assertIn("function loadConversationStats(", template)
        self.assertIn("/message-stats", template)

    async def test_management_message_page_omits_structured_payloads(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            result = await database.get_context_message_page(7, 101, before_id=55)

        self.assertEqual([], result)
        query = conn.fetch.await_args.args[0]
        self.assertIn("NULL::JSONB AS content_json", query)
        self.assertIn("(content_json IS NOT NULL) AS has_content_json", query)
        self.assertIn("hidden = FALSE", query)
        self.assertIn("role IN ('user', 'assistant')", query)
        self.assertIn("id < $2", query)
        self.assertEqual((7, 55, 101), conn.fetch.await_args.args[1:])

    async def test_lightweight_conversation_metadata_skips_history_aggregate(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=None)
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            result = await database.get_conversation_context_metadata(
                7, include_message_stats=False
            )

        self.assertIsNone(result)
        query = conn.fetchrow.await_args.args[0]
        self.assertNotIn("LATERAL", query)
        self.assertNotIn("COUNT(", query)

    async def test_background_message_stats_count_only_visible_chat_messages(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"total_messages": 0})
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            result = await database.get_context_stats(7)

        self.assertEqual(0, result["total_messages"])
        query = conn.fetchrow.await_args.args[0]
        self.assertIn("hidden = FALSE", query)
        self.assertIn("role IN ('user', 'assistant')", query)
        self.assertIn("content_json IS NULL", query)


class ConversationLoadingApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_conversation_list_is_lightweight_unless_stats_are_requested(self):
        get_all = AsyncMock(return_value=[])
        with patch.object(main, "get_all_conversations", get_all):
            await main.api_list_conversations()
            await main.api_list_conversations(include_stats=True)

        self.assertEqual(
            [False, True],
            [call.kwargs["include_message_stats"] for call in get_all.await_args_list],
        )

    async def test_message_total_is_calculated_by_separate_endpoint(self):
        stats_loader = AsyncMock(return_value={"total_messages": 321})
        with patch.object(main, "get_context_stats", stats_loader):
            result = await main.api_get_context_message_stats(7)

        self.assertEqual({"conversation_id": 7, "total_messages": 321}, result)
        stats_loader.assert_awaited_once_with(7)

    async def test_message_page_uses_direct_conversation_metadata(self):
        now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
        messages = [{
            "id": 9,
            "conversation_id": 3,
            "role": "user",
            "content": "hello",
            "content_json": None,
            "kind": "chat",
            "hidden": False,
            "affects_activity": True,
            "created_at": now,
        }]
        metadata = {
            "id": 3,
            "name": "Conversation",
            "is_active": True,
            "handoff_summary": "saved summary",
            "handoff_draft": "saved draft",
            "created_at": now,
            "updated_at": now,
        }
        all_conversations = AsyncMock(side_effect=AssertionError("full list queried"))

        metadata_loader = AsyncMock(return_value=metadata)
        with patch.object(
            main, "get_context_messages", AsyncMock(return_value=messages)
        ), patch.object(
            main, "get_conversation_context_metadata", metadata_loader
        ), patch.object(main, "get_all_conversations", all_conversations):
            result = await main.api_get_context_messages(3)

        self.assertEqual("Conversation", result["conversation"]["name"])
        self.assertEqual(1, result["conversation"]["message_count"])
        self.assertEqual("saved summary", result["handoff_summary"])
        self.assertEqual(1, result["stats"]["total_messages"])
        metadata_loader.assert_awaited_once_with(3, include_message_stats=True)
        all_conversations.assert_not_awaited()

    async def test_message_page_returns_recent_slice_and_older_cursor(self):
        now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
        rows = [
            {
                "id": message_id,
                "conversation_id": 3,
                "role": "user",
                "content": f"message {message_id}",
                "content_json": None,
                "has_content_json": False,
                "kind": "chat",
                "hidden": False,
                "affects_activity": True,
                "created_at": now,
            }
            for message_id in (7, 8, 9)
        ]
        metadata = {
            "id": 3,
            "name": "Old conversation",
            "is_active": True,
            "handoff_summary": "",
            "handoff_draft": "",
            "message_count": None,
            "started_at": None,
            "last_message_at": None,
            "created_at": now,
            "updated_at": now,
        }
        page_loader = AsyncMock(return_value=rows)

        metadata_loader = AsyncMock(return_value=metadata)
        with patch.object(main, "get_context_message_page", page_loader), patch.object(
            main, "get_conversation_context_metadata", metadata_loader
        ), patch.object(
            main, "get_context_messages", AsyncMock(side_effect=AssertionError("full history loaded"))
        ):
            result = await main.api_get_context_messages(3, limit=2, before_id=10)

        page_loader.assert_awaited_once_with(3, 3, 10)
        self.assertEqual([8, 9], [message["id"] for message in result["messages"]])
        self.assertTrue(result["pagination"]["has_older"])
        self.assertEqual(8, result["pagination"]["next_before_id"])
        self.assertEqual(2, result["conversation"]["message_count"])
        self.assertTrue(result["conversation"]["message_count_is_partial"])
        metadata_loader.assert_awaited_once_with(3, include_message_stats=False)


if __name__ == "__main__":
    unittest.main()
