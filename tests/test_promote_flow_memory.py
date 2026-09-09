import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import main
import database


class PromoteFlowMemoryTests(unittest.IsolatedAsyncioTestCase):
    def test_promote_api_endpoint_exists(self):
        """验证提升 API 端点存在"""
        root = Path(__file__).resolve().parents[1]
        main_source = (root / "main.py").read_text(encoding="utf-8")

        self.assertIn('"/api/standing-memory/{block_id}/to-diary"', main_source)
        self.assertIn("async def api_promote_standing_to_long_term", main_source)

    def test_promote_button_in_flow_memory_cards(self):
        """验证流动记忆卡片中有提升按钮"""
        root = Path(__file__).resolve().parents[1]
        js_source = (root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

        self.assertIn("promoteFlowMemoryToLongTerm", js_source)
        self.assertIn("kelivo-icon-btn promote", js_source)
        self.assertIn("归档到日记", js_source)

    def test_promote_button_only_for_flow_zone(self):
        """验证提升按钮仅在流动区显示"""
        root = Path(__file__).resolve().parents[1]
        js_source = (root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

        # 查找 renderKelivoMemoryCard 函数
        render_func = js_source.split("function renderKelivoMemoryCard", 1)[1]
        render_func = render_func.split("\nfunction ", 1)[0]

        # 验证按钮只在 zone === "flow" 时显示
        self.assertIn('zone === "flow"', render_func)
        self.assertIn("promoteButton", render_func)

    def test_promote_button_has_icon(self):
        """验证提升按钮有向上箭头图标"""
        root = Path(__file__).resolve().parents[1]
        js_source = (root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

        # 向上箭头 SVG path
        self.assertIn('path d="M12 19V5M5 12l7-7 7 7"', js_source)

    def test_promote_button_has_style(self):
        """验证提升按钮有专门的样式"""
        root = Path(__file__).resolve().parents[1]
        css_source = (root / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")

        self.assertIn(".kelivo-icon-btn.promote", css_source)

    async def test_promote_requires_memory_enabled(self):
        """验证提升功能需要启用记忆系统"""
        with patch.object(main, "MEMORY_ENABLED", False):
            request = MagicMock()
            request.headers = {"content-type": "application/json"}
            request.json = AsyncMock(return_value={})

            response = await main.api_promote_standing_to_long_term(1, request)

            self.assertEqual("Memory system not enabled", response["error"])

    async def test_promote_validates_flow_layer(self):
        """验证只能提升流动区的记忆"""
        request = MagicMock()
        request.headers = {"content-type": "application/json"}
        request.json = AsyncMock(return_value={})

        # 模拟一个固定区的记忆
        with patch.object(main, "MEMORY_ENABLED", True), \
             patch.object(main, "get_standing_memory_block", AsyncMock(return_value={
                 "id": 1,
                 "layer": "core",  # 不是 recent
                 "title": "固定记忆",
                 "content": "这是固定区的内容",
             })):
            response = await main.api_promote_standing_to_long_term(1, request)

            self.assertEqual(400, response.status_code)
            content = response.body.decode('utf-8')
        self.assertIn("只能将流动区", content)

    async def test_promote_creates_long_term_memory(self):
        """验证提升操作创建长期记忆"""
        request = MagicMock()
        request.headers = {"content-type": "application/json"}
        request.json = AsyncMock(return_value={})

        flow_memory = {
            "id": 42,
            "layer": "recent",
            "title": "会话摘要",
            "content": "讨论了关于 AI 记忆系统的设计",
            "created_at": "2026-08-31 20:00:00",
        }

        long_term_result = {
            "id": 100,
            "title": "会话摘要",
            "summary": "",
            "content": "讨论了关于 AI 记忆系统的设计",
            "keywords": [],
        }

        with patch.object(main, "MEMORY_ENABLED", True), \
             patch.object(main, "get_standing_memory_block", AsyncMock(return_value=flow_memory)), \
             patch.object(main, "create_long_term_memory", AsyncMock(return_value=long_term_result)) as create_mock, \
             patch.object(main, "delete_standing_memory_block", AsyncMock()) as delete_mock:
            response = await main.api_promote_standing_to_long_term(42, request)

            self.assertEqual("ok", response["status"])
            self.assertEqual(100, response["diary"]["id"])
            self.assertEqual(42, response["original_block_id"])
            self.assertTrue(response["deleted_original"])
            delete_mock.assert_awaited_once_with(42)

            # 验证调用了 create_long_term_memory
            create_mock.assert_awaited_once()
            call_kwargs = create_mock.await_args.kwargs
            self.assertEqual("会话摘要", call_kwargs["title"])
            self.assertEqual("讨论了关于 AI 记忆系统的设计", call_kwargs["content"])
            self.assertEqual([], call_kwargs["keywords"])
            self.assertNotIn("original_created_at", call_kwargs["metadata"])
            self.assertIn("source_flow_memory_id", call_kwargs["metadata"])
            self.assertEqual(42, call_kwargs["metadata"]["source_flow_memory_id"])

    async def test_promote_can_preserve_original_when_requested(self):
        """验证 API 显式要求时可保留原始记忆"""
        request = MagicMock()
        request.headers = {"content-type": "application/json"}
        request.json = AsyncMock(return_value={"delete_original": False})

        flow_memory = {
            "id": 42,
            "layer": "recent",
            "title": "会话摘要",
            "content": "测试内容",
        }

        with patch.object(main, "MEMORY_ENABLED", True), \
             patch.object(main, "get_standing_memory_block", AsyncMock(return_value=flow_memory)), \
             patch.object(main, "create_long_term_memory", AsyncMock(return_value={"id": 100})), \
             patch.object(main, "delete_standing_memory_block", AsyncMock()) as delete_mock:
            response = await main.api_promote_standing_to_long_term(42, request)

            self.assertEqual("ok", response["status"])
            self.assertFalse(response["deleted_original"])
            delete_mock.assert_not_awaited()

    def test_promote_source_id_cannot_be_overridden(self):
        """验证幂等键不能被请求 metadata 覆盖"""
        root = Path(__file__).resolve().parents[1]
        main_source = (root / "main.py").read_text(encoding="utf-8")
        promote_func = main_source.split(
            "async def api_promote_standing_to_long_term", 1
        )[1].split("\ndef ", 1)[0]

        custom_metadata = promote_func.index('**(data.get("metadata") or {})')
        source_id = promote_func.index('"source_flow_memory_id": block_id')
        self.assertLess(custom_metadata, source_id)

    def test_javascript_function_confirms_before_promote(self):
        """验证 JavaScript 在提升前有确认对话框"""
        root = Path(__file__).resolve().parents[1]
        js_source = (root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

        # 查找 promoteFlowMemoryToLongTerm 函数
        promote_func = js_source.split("async function promoteFlowMemoryToLongTerm", 1)[1]
        promote_func = promote_func.split("\nasync function ", 1)[0]

        self.assertIn("confirm", promote_func)
        self.assertIn("归档到日记", promote_func)

    def test_javascript_function_refreshes_after_promote(self):
        """验证提升后刷新记忆列表"""
        root = Path(__file__).resolve().parents[1]
        js_source = (root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

        promote_func = js_source.split("async function promoteFlowMemoryToLongTerm", 1)[1]
        promote_func = promote_func.split("\nasync function ", 1)[0]

        self.assertIn("loadStandingMemory", promote_func)
        self.assertIn("loadLongTermMemory", promote_func)

    def test_javascript_prevents_duplicate_promote_requests(self):
        """连续点击时只允许一个提升请求在途中"""
        root = Path(__file__).resolve().parents[1]
        js_source = (root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
        promote_func = js_source.split(
            "async function promoteFlowMemoryToLongTerm", 1
        )[1].split("\nfunction ", 1)[0]

        self.assertIn("promotingFlowMemoryIds.has(id)", promote_func)
        self.assertIn("promotingFlowMemoryIds.add(id)", promote_func)
        self.assertIn("button.disabled = true", promote_func)
        self.assertIn("promotingFlowMemoryIds.delete(id)", promote_func)
        self.assertIn("delete_original: true", promote_func)

    async def test_database_insert_is_idempotent_for_flow_promotions(self):
        """数据库唯一索引冲突时复用已有长期记忆"""
        existing = {
            "id": 100,
            "title": "会话摘要",
            "keywords": ["会话", "摘要"],
            "summary": "会话；摘要",
            "content": "已有内容",
            "metadata": {"source_flow_memory_id": 42},
        }
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=[None, existing])
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            result = await database.create_long_term_memory(
                title="会话摘要",
                keywords=["会话", "摘要"],
                content="已有内容",
                metadata={"source_flow_memory_id": 42},
            )

        insert_query = conn.fetchrow.await_args_list[0].args[0]
        lookup_query = conn.fetchrow.await_args_list[1].args[0]
        self.assertIn("ON CONFLICT", insert_query)
        self.assertIn("DO NOTHING", insert_query)
        insert_args = conn.fetchrow.await_args_list[0].args
        self.assertEqual("会话摘要", insert_args[1])
        self.assertEqual("", insert_args[3])
        self.assertIsNone(insert_args[5])
        self.assertFalse(insert_args[9])
        self.assertIn("metadata->>'source_flow_memory_id' = $1", lookup_query)
        self.assertEqual("42", conn.fetchrow.await_args_list[1].args[1])
        self.assertEqual(100, result["id"])


if __name__ == "__main__":
    unittest.main()
