import json
import unittest
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import main
import database


class StandingMemoryManualUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_edit_updates_content_and_takes_authorship(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={"content": "用户修订后的内容"})
        saved = {
            "id": 17,
            "title": "Work context",
            "content": "用户修订后的内容",
            "status": "active",
            "source": "manual",
            "layer": "core",
            "metadata": {"fixed_section": "work_context"},
            "created_at": None,
            "updated_at": None,
        }
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "update_standing_memory_block", AsyncMock(return_value=saved)
        ) as update:
            result = await main.api_update_standing_memory(17, request)

        self.assertEqual("ok", result["status"])
        self.assertEqual("用户修订后的内容", result["block"]["content"])
        update.assert_awaited_once_with(
            17, content="用户修订后的内容", source="manual"
        )

    async def test_manual_edit_rejects_empty_content_without_touching_database(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={"content": "   "})
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "update_standing_memory_block", AsyncMock()
        ) as update:
            response = await main.api_update_standing_memory(17, request)

        self.assertEqual(400, response.status_code)
        update.assert_not_awaited()


class StandingMemoryOverviewTests(unittest.IsolatedAsyncioTestCase):
    def test_overview_uses_flat_kelivo_records_without_layer_metadata(self):
        blocks = [
            {
                "id": 1,
                "title": "Core",
                "content": "core content",
                "layer": "core",
                "status": "active",
                "inject_enabled": True,
                "parent_id": None,
            },
            {
                "id": 2,
                "title": "Recent",
                "content": "recent content",
                "created_at": "2026-08-24 12:00:00",
                "layer": "recent",
                "status": "active",
                "inject_enabled": True,
                "parent_id": None,
            },
            {
                "id": 3,
                "title": "Pending",
                "content": "must not appear",
                "layer": "ring",
                "status": "pending",
                "inject_enabled": True,
                "parent_id": None,
            },
            {
                "id": 4,
                "title": "Disabled",
                "content": "must not appear either",
                "layer": "recent",
                "status": "active",
                "inject_enabled": False,
                "parent_id": None,
            },
        ]

        content = main._render_kelivo_memory_prompt(blocks)
        overview = main._build_standing_memory_overview(blocks)

        self.assertEqual(overview["block_count"], 2)
        self.assertEqual(overview["character_count"], len(overview["content"]))
        self.assertIn("<id>1</id>\n<content>core content</content>", content)
        self.assertIn("<memory>", content)
        self.assertNotIn("fixed_memories", content)
        self.assertIn("<recent_timeline>", content)
        self.assertIn("<entered_on>2026-08-24</entered_on>", content)
        self.assertIn("<title>Recent</title>", content)
        self.assertIn("<content>recent content</content>", content)
        self.assertNotIn("read_diary", content)
        self.assertNotIn("search_conversation_history", content)
        self.assertNotIn("Core", content)
        self.assertNotIn("core_memory", content)
        self.assertNotIn("recent_memory", content)
        self.assertNotIn("must not appear", content)

    def test_pending_review_uses_field_diff_highlights(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
        styles = (root / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")

        self.assertIn("function pendingInlineDiff", script)
        self.assertIn("function renderPendingFieldDiff", script)
        self.assertIn("function renderPendingStandingMemoryCard", script)
        self.assertIn('renderPendingFieldDiff(\n        "内容"', script)
        self.assertIn("longTermMemories.find", script)
        self.assertIn("standingBlocks.find", script)
        self.assertIn("pending-diff-added", styles)
        self.assertIn("pending-diff-removed", styles)

    def test_builtin_memory_tools_expose_reads_and_pending_writes(self):
        self.assertEqual(
            [
                "create_memory", "edit_memory", "delete_memory",
                "search_diary", "read_diary",
            ],
            [tool["name"] for tool in main.BUILTIN_MEMORY_TOOLS],
        )
        self.assertEqual(
            {
                "create_memory", "edit_memory", "delete_memory",
                "search_memory", "read_memory", "search_diary",
                "read_diary", "read_long_term_memory",
                "search_conversation_history", "recall_fragments",
            },
            set(main.MEMORY_TOOL_NAMES),
        )
        self.assertTrue({"create_memory", "edit_memory", "delete_memory"}.isdisjoint(
            main.RETIRED_MODEL_TOOL_NAMES
        ))
        self.assertIn("ws_mem_write", main.RETIRED_MODEL_TOOL_NAMES)
        self.assertIn("read_long_term_memory", main.RETIRED_MODEL_TOOL_NAMES)

    def test_standing_memory_pending_flow_is_available(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "templates" / "memory-archive.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
        source = Path(main.__file__).read_text(encoding="utf-8")

        self.assertIn('id="standing-pending-section"', dashboard)
        self.assertIn('id="standing-pending-list"', dashboard)
        self.assertIn("approveStandingMemory", script)
        self.assertIn('/api/standing-memory/{block_id}/approve', source)
        self.assertEqual("pending", database._normalize_standing_status("pending"))
        self.assertEqual("active", database._normalize_standing_status(None))

    def test_dashboard_separates_fixed_and_flow_memory(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

        self.assertIn('block.layer !== "recent"', script)
        self.assertIn('block.layer === "recent"', script)
        page = (root / "templates" / "memory-archive.html").read_text(encoding="utf-8")
        self.assertIn('aria-controls="archive-fixed"', page)
        self.assertIn('aria-controls="archive-flow"', page)
        self.assertIn("保留最近", page)
        self.assertIn("saveFlowMemoryMaxItems", script)
        self.assertIn('id="archive-flow-list"', page)

    def test_flow_window_keeps_configured_number_of_recent_records(self):
        blocks = [
            {
                "id": index,
                "title": f"摘要 {index}",
                "content": "短摘要",
                "created_at": f"2026-08-{index:02d}T00:00:00+00:00",
            }
            for index in range(1, 19)
        ]

        kept, overflow = database._select_flow_memory_window(
            blocks,
            max_items=8,
            hard_tokens=150000,
        )

        self.assertEqual(list(range(18, 10, -1)), [block["id"] for block in kept])
        self.assertEqual(list(range(10, 0, -1)), [block["id"] for block in overflow])

    def test_flow_window_promotes_oldest_records_above_count_limit(self):
        blocks = [
            {"id": 3, "content": "新" * 40, "created_at": "2026-08-03"},
            {"id": 2, "content": "中" * 40, "created_at": "2026-08-02"},
            {"id": 1, "content": "旧", "created_at": "2026-08-01"},
        ]

        kept, overflow = database._select_flow_memory_window(
            blocks,
            max_items=2,
            hard_tokens=250,
        )

        self.assertEqual([3, 2], [block["id"] for block in kept])
        self.assertEqual([1], [block["id"] for block in overflow])

    def test_flow_window_promotes_minimum_suffix_above_hard_watermark(self):
        blocks = [
            {"id": 4, "content": "新" * 40, "created_at": "2026-08-04"},
            {"id": 3, "content": "次" * 40, "created_at": "2026-08-03"},
            {"id": 2, "content": "中" * 40, "created_at": "2026-08-02"},
            {"id": 1, "content": "旧" * 40, "created_at": "2026-08-01"},
        ]

        kept, overflow = database._select_flow_memory_window(
            blocks,
            max_items=16,
            hard_tokens=180,
        )

        self.assertLessEqual(
            sum(database._flow_memory_token_estimate(block) for block in kept),
            180,
        )
        self.assertEqual([4, 3], [block["id"] for block in kept])
        self.assertEqual([2, 1], [block["id"] for block in overflow])

    def test_flow_window_does_not_roll_below_count_and_hard_token_limits(self):
        blocks = [
            {"id": 3, "content": "新" * 40, "created_at": "2026-08-03"},
            {"id": 2, "content": "中" * 40, "created_at": "2026-08-02"},
            {"id": 1, "content": "旧", "created_at": "2026-08-01"},
        ]

        kept, overflow = database._select_flow_memory_window(
            blocks,
            max_items=8,
            hard_tokens=250,
        )

        self.assertEqual([3, 2, 1], [block["id"] for block in kept])
        self.assertEqual([], overflow)

    def test_flow_window_status_exposes_saved_count_limit(self):
        blocks = [
            {
                "id": 1,
                "content": "摘要" * 50,
                "created_at": "2026-08-01",
                "status": "active",
                "layer": "recent",
            },
            {
                "id": 2,
                "content": "固定记忆",
                "status": "active",
                "layer": "core",
            },
        ]

        status = database.get_flow_memory_window_status(blocks, max_items=1)

        self.assertEqual(1, status["item_count"])
        self.assertEqual(1, status["max_items"])
        self.assertEqual("full", status["state"])

    async def test_flow_memory_limit_api_saves_and_reports_promotions(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={"max_items": 5})
        save = AsyncMock(return_value={"max_items": 5, "promoted_count": 3})

        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "save_flow_memory_settings", save
        ):
            result = await main.api_update_flow_memory_settings(request)

        self.assertEqual("ok", result["status"])
        self.assertEqual(3, result["promoted_count"])
        save.assert_awaited_once_with(5)

    async def test_flow_memory_limit_api_rejects_out_of_range_count(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={"max_items": 0})

        with patch.object(main, "MEMORY_ENABLED", True):
            response = await main.api_update_flow_memory_settings(request)

        self.assertEqual(400, response.status_code)


class FlowMemoryPromotionTests(unittest.IsolatedAsyncioTestCase):
    async def test_ui_handoff_does_not_queue_extraction(self):
        request = MagicMock(json=AsyncMock(return_value={"message_ids": [1], "name": "继续"}))
        create = AsyncMock(return_value={"id": 2})
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "create_conversation_from_messages", create
        ):
            await main.api_create_handoff_conversation(1, request)
        create.assert_awaited_once_with(1, "继续", [1], store_summary_in_flow=True)

    async def test_handoff_stores_flow_without_creating_extraction_jobs(self):
        import database
        active = False
        source = {"id": 7, "name": "旧会话", "max_messages": 200, "is_active": True,
                  "handoff_draft": "摘要", "handoff_summary_ready_for_flow": True}
        conn = MagicMock(fetchrow=AsyncMock(side_effect=[source, {"id": 8, "name": "继续"}]))
        conn.execute = AsyncMock()
        @asynccontextmanager
        async def transaction():
            nonlocal active
            active = True
            try:
                yield
            finally:
                active = False
        conn.transaction.side_effect = transaction
        class Pool:
            @asynccontextmanager
            async def acquire(self):
                yield conn
        async def store(*args):
            self.assertTrue(active)
            return 31
        with patch.object(database, "get_pool", AsyncMock(return_value=Pool())), patch.object(
            database, "_store_conversation_summary_in_flow", side_effect=store
        ) as save_flow:
            result = await database.create_conversation_from_messages(7, "继续", [])
        save_flow.assert_awaited_once_with(conn, source)
        self.assertEqual(31, result["flow_memory_id"])
        self.assertFalse(active)
        self.assertFalse(any("nocturne_extraction_jobs" in call.args[0] for call in conn.execute.await_args_list))

    async def test_standing_memory_init_does_not_backfill_legacy_handoff_summaries(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            await database.init_standing_memory_tables()

        initialization_sql = "\n".join(
            call.args[0] for call in conn.execute.await_args_list
        )
        self.assertNotIn("FROM conversations AS target", initialization_sql)
        self.assertNotIn("legacy_target_conversation_id", initialization_sql)
        self.assertNotIn("旧交接摘要", initialization_sql)

    async def test_overflow_moves_directly_to_long_term_without_pending(self):
        rows = [
            {
                "id": index,
                "title": f"会话 {index} · 摘要",
                "content": f"摘要正文 {index}",
                "metadata": {"kind": "conversation_summary"},
                "created_at": datetime(2026, 8, index, tzinfo=timezone.utc),
            }
            for index in range(1, 19)
        ]
        rows[0]["title"] = "2026-07-15 会话 1 · 摘要"
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=rows)
        conn.fetchrow = AsyncMock(side_effect=[{"id": 101}, {"id": 102}])
        conn.fetchval = AsyncMock()
        conn.execute = AsyncMock()

        promoted = await database._promote_flow_memory_overflow(
            conn,
            max_items=16,
        )

        self.assertEqual([101, 102], promoted)
        insert_calls = [
            call for call in conn.fetchrow.await_args_list
            if "INSERT INTO long_term_memories" in call.args[0]
        ]
        self.assertEqual(2, len(insert_calls))
        self.assertIn("VALUES ($1, '[]'::jsonb, '', $2, $3", insert_calls[0].args[0])
        self.assertEqual("2026-07-15 会话 1 · 摘要", insert_calls[0].args[1])
        self.assertEqual("摘要正文 1", insert_calls[0].args[2])
        self.assertEqual(date(2026, 7, 15), insert_calls[0].args[3])
        metadata = json.loads(insert_calls[0].args[4])
        self.assertEqual(1, metadata["source_flow_memory_id"])
        self.assertEqual("diary", metadata["entry_kind"])
        self.assertEqual("2026-08-01", metadata["flow_entered_on"])
        self.assertEqual("title", metadata["promotion_memory_date_source"])
        executed = [call.args[0] for call in conn.execute.await_args_list]
        self.assertEqual(
            2,
            sum("DELETE FROM standing_memory_blocks" in query for query in executed),
        )
        self.assertFalse(any("long_term_memory_proposals" in query for query in executed))

class KelivoPromptOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_flow_memory_omits_timeline_with_and_without_cache(self):
        blocks = [{
            "id": 4,
            "content": "fixed memory",
            "layer": "core",
            "status": "active",
            "inject_enabled": True,
        }]
        prompt_sections = AsyncMock(return_value=[
            {"key": "Identity", "content": "CUSTOM SYSTEM"},
            {"key": "Interaction", "content": "INTERACTION"},
        ])

        for cache_enabled in (False, True):
            with self.subTest(cache_enabled=cache_enabled), patch.object(
                main, "PROMPT_CACHE_ENABLED", cache_enabled
            ), patch.object(
                main, "get_all_sections", prompt_sections
            ), patch.object(
                main, "get_standing_memory_blocks", AsyncMock(return_value=blocks)
            ), patch.object(
                main, "build_dynamic_turn_block", AsyncMock(return_value="")
            ):
                result = await main.build_system_prompt_with_memories(
                    "hello", [], conv_id=1
                )

            rendered = (
                "\n\n".join(block["text"] for block in result)
                if isinstance(result, list) else result
            )
            if cache_enabled:
                self.assertEqual(1, len(result))
            self.assertNotIn("<recent_timeline>", rendered)
            self.assertNotIn("</recent_timeline>", rendered)
            self.assertIn("fixed memory", rendered)

    async def test_core_then_memories_then_dynamic_order(self):
        blocks = [
            {
                "id": 3,
                "content": "memory body",
                "status": "active",
                "inject_enabled": True,
            },
            {
                "id": 4,
                "title": "flow",
                "content": "flow memory",
                "created_at": "2026-08-24 12:00:00",
                "layer": "recent",
                "status": "active",
                "inject_enabled": True,
            },
        ]
        prompt_sections = AsyncMock(return_value=[
            {"key": "Identity", "content": "CUSTOM SYSTEM"},
            {"key": "Interaction", "content": "INTERACTION"},
        ])
        with patch.object(main, "PROMPT_CACHE_ENABLED", False), patch.object(
            main, "get_all_sections", prompt_sections
        ), patch.object(
            main, "get_standing_memory_blocks", AsyncMock(return_value=blocks)
        ), patch.object(
            main, "build_dynamic_turn_block", AsyncMock(return_value="DYNAMIC ADDITION")
        ):
            result = await main.build_system_prompt_with_memories(
                "hello", [], conv_id=1
            )

        self.assertLess(result.index("CUSTOM SYSTEM"), result.index("## Memories"))
        self.assertLess(result.index("## Memories"), result.index("INTERACTION"))
        self.assertLess(result.index("INTERACTION"), result.index("<recent_timeline>"))
        self.assertLess(result.index("<recent_timeline>"), result.index("DYNAMIC ADDITION"))
        self.assertNotIn("回忆录", result)
        self.assertLess(result.index("INTERACTION"), result.index("DYNAMIC ADDITION"))
        prompt_sections.assert_awaited_once_with()

    async def test_cached_fixed_and_flow_memories_use_two_ordered_blocks(self):
        blocks = [
            {
                "id": 4,
                "content": "fixed memory",
                "layer": "core",
                "status": "active",
                "inject_enabled": True,
            },
            {
                "id": 5,
                "title": "flow",
                "content": "flow memory",
                "created_at": "2026-08-24 12:00:00",
                "layer": "recent",
                "status": "active",
                "inject_enabled": True,
            },
        ]
        prompt_sections = AsyncMock(return_value=[
            {"key": "Identity", "content": "CUSTOM SYSTEM"},
            {"key": "Interaction", "content": "INTERACTION"},
        ])
        with patch.object(main, "PROMPT_CACHE_ENABLED", True), patch.object(
            main, "get_all_sections", prompt_sections
        ), patch.object(
            main, "get_standing_memory_blocks", AsyncMock(return_value=blocks)
        ), patch.object(
            main, "build_dynamic_turn_block", AsyncMock(return_value="")
        ):
            result = await main.build_system_prompt_with_memories(
                "hello", [], conv_id=1
            )

        self.assertEqual(2, len(result))
        self.assertTrue(result[0]["text"].startswith("CUSTOM SYSTEM\n\n## Memories"))
        self.assertIn("fixed memory", result[0]["text"])
        self.assertIn("INTERACTION", result[0]["text"])
        self.assertNotIn("回忆录", result[0]["text"])
        self.assertIn("flow memory", result[1]["text"])
        self.assertTrue(result[1]["text"].startswith("<recent_timeline>"))
        self.assertTrue(result[1]["text"].endswith("</recent_timeline>"))
        self.assertEqual({"type": "ephemeral", "ttl": "1h"}, result[0]["cache_control"])
        self.assertEqual({"type": "ephemeral", "ttl": "1h"}, result[1]["cache_control"])
        prompt_sections.assert_awaited_once_with()


class StandingMemoryPendingToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_memory_write_tools_create_pending_proposals(self):
        upsert = AsyncMock(side_effect=[
            ({"id": 21, "status": "pending"}, True),
            ({"id": 22, "status": "pending"}, True),
            ({"id": 23, "status": "pending"}, True),
        ])
        with patch.object(main, "upsert_pending_standing_memory_operation", upsert):
            for tool_name in ("create_memory", "edit_memory", "delete_memory"):
                result = json.loads(await main.dispatch_tool_call(
                    tool_name, {"id": 8, "content": "内容"}
                ))
                self.assertEqual("pending", result["status"])
                self.assertEqual(tool_name.removesuffix("_memory"), result["operation"])
        self.assertEqual(3, upsert.await_count)

    async def test_namespaced_memory_write_uses_pending_flow(self):
        upsert = AsyncMock(return_value=({"id": 24, "status": "pending"}, True))
        with patch.object(main, "upsert_pending_standing_memory_operation", upsert):
            result = json.loads(await main.dispatch_tool_call(
                "legacy.create_memory", {"content": "需要记住"}
            ))
        self.assertEqual("pending", result["status"])
        upsert.assert_awaited_once()

    async def test_edit_approval_applies_replacement_and_removes_proposal(self):
        class AsyncContext:
            def __init__(self, value=None):
                self.value = value

            async def __aenter__(self):
                return self.value

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class Connection:
            def __init__(self):
                self.deleted_pending_id = None

            def transaction(self):
                return AsyncContext()

            async def fetchrow(self, query, *args):
                if "status = 'pending'" in query:
                    return {
                        "id": 102,
                        "status": "pending",
                        "content": "新内容",
                        "metadata": '{"pending_operation":"edit","target_block_id":7}',
                    }
                if "status = 'active'" in query:
                    return {"id": 7, "status": "active", "content": "旧内容"}
                if "SET content = $2" in query:
                    return {"id": 7, "status": "active", "content": args[1]}
                raise AssertionError(query)

            async def execute(self, query, *args):
                self.deleted_pending_id = args[0]
                return "DELETE 1"

        connection = Connection()

        class Pool:
            def acquire(self):
                return AsyncContext(connection)

        with patch.object(database, "get_pool", AsyncMock(return_value=Pool())):
            result = await database.apply_pending_standing_memory_operation(102)

        self.assertEqual("edit", result["operation"])
        self.assertEqual("新内容", result["block"]["content"])
        self.assertEqual(102, connection.deleted_pending_id)
