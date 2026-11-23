import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import database
import diary_merge
import main
import conversation_recall
from diary_author import diary_author_fields, diary_author_role


def memory(role="user"):
    return {"id": 1, "title": "海边", "content": "我今天去了海边。", "keywords": ["海边"],
            "memory_date": "2026-10-02", "metadata": {"entry_kind": "diary", "author_role": role}}


def request(data):
    result = MagicMock()
    result.json = AsyncMock(return_value=data)
    return result


class DiaryAuthorTests(unittest.IsolatedAsyncioTestCase):
    def test_legacy_author_and_dynamic_identity_names(self):
        self.assertEqual(diary_author_role({}), "assistant")
        self.assertEqual(diary_author_role({"metadata": '{"author_role":"user"}'}), "user")
        self.assertEqual(diary_author_fields(memory(), {"user_name": "小雨"}),
                         {"author_role": "user", "author_name": "小雨"})
        self.assertEqual(diary_author_fields(memory())['author_name'], "{{user_name}}")
        self.assertEqual(diary_author_fields({}, {})['author_name'], "{{assistant_name}}")

    async def test_model_search_and_each_read_page_identify_author(self):
        for role, name in (("user", "小雨"), ("assistant", "Ash")):
            with ExitStack() as stack:
                for key, value in {
                    "get_conversation_model_settings": AsyncMock(return_value={"search_enabled": False,
                        "embedding_api_url": "https://embedding.test/v1",
                        "embedding_model": "test", "embedding_api_key": "key"}),
                    "search_long_term_memory_summaries": AsyncMock(return_value=[memory(role)]),
                    "get_long_term_memory": AsyncMock(return_value=memory(role)),
                    "get_identity_presets": AsyncMock(return_value={"user_name": "小雨", "assistant_name": "Ash"}),
                    "LONG_TERM_MEMORY_READ_MAX_CHARS": 3,
                }.items():
                    stack.enter_context(patch.object(main, key, value))
                found = json.loads(await main.dispatch_tool_call("search_diary", {"query": "海边"}))
                for entry in [found["entries"][0],
                              json.loads(await main.dispatch_tool_call("read_diary", {"id": 1})),
                              json.loads(await main.dispatch_tool_call("read_diary", {"id": 1, "offset": 3}))]:
                    self.assertEqual(list(entry)[:2], ["author_role", "author_name"])
                    self.assertEqual(entry["author_role"], role)
                    self.assertEqual(entry["author_name"], name)
                self.assertNotIn("content", found["entries"][0])

    async def test_create_and_relabel_existing_diary(self):
        create = AsyncMock(return_value=memory())
        update = AsyncMock(return_value=memory())
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main, "create_long_term_memory", create
        ), patch.object(main, "update_long_term_memory", update), patch.object(
            main, "get_long_term_memory", AsyncMock(return_value=memory("assistant"))
        ):
            result = await main.api_create_long_term_memory(request({
                "title": "海边", "content": "我今天去了海边。", "author_role": "user"}))
            self.assertEqual(result["diary"]["author_role"], "user")
            self.assertEqual(create.await_args.kwargs["metadata"]["author_role"], "user")
            await main.api_update_long_term_memory(1, request({"author_role": "user"}))
            self.assertEqual(update.await_args.kwargs["author_role"], "user")
            await main.api_update_long_term_memory(1, request({"keywords": ["旅行"]}))
            self.assertIsNone(update.await_args.kwargs["author_role"])
            for invalid in (None, "system", "", {}, []):
                bad = await main.api_update_long_term_memory(1, request({"author_role": invalid}))
                self.assertEqual(bad.status_code, 400)
                bad = await main.api_create_long_term_memory(request({"author_role": invalid}))
                self.assertEqual(bad.status_code, 400)

    async def test_database_author_edit_merges_metadata_and_preserves_omitted_author(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=memory())
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            await database.update_long_term_memory(1, "海边", [], "正文", author_role="user")
            sql, *args = conn.fetchrow.await_args.args
            self.assertIn("THEN metadata", sql)
            self.assertIn("|| jsonb_build_object('author_role'", sql)
            self.assertEqual(args[-1], "user")
            await database.update_long_term_memory(1, "海边", [], "正文")
            self.assertIsNone(conn.fetchrow.await_args.args[-1])

    async def test_user_diary_merge_preserves_author_and_rejects_mixed_authors(self):
        first, second = memory(), {**memory(), "id": 2}
        self.assertEqual(diary_merge.validate_sources([first, second]), "2026-10-02")
        with self.assertRaisesRegex(ValueError, "同一作者"):
            diary_merge.validate_sources([first, {**memory("assistant"), "id": 2}])
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[first, second])
        conn.fetchrow = AsyncMock(return_value=memory())
        conn.execute = AsyncMock()
        sources = [diary_merge.snapshot(m) for m in (first, second)]
        result = await diary_merge.apply_merge(conn, {
            "id": 3, "title": "合并", "content": "我去了海边。", "memory_date": "2026-10-02"
        }, sources)
        self.assertEqual(result["operation"], "merge")
        self.assertEqual(json.loads(conn.fetchrow.await_args.args[-1])["author_role"], "user")
        conn.fetchrow.reset_mock()
        conn.fetch.return_value = [first, {**second, "metadata": {"author_role": "assistant"}}]
        self.assertIn("error", await diary_merge.apply_merge(conn, {}, sources))
        conn.fetchrow.assert_not_awaited()

    def test_automatic_recall_keeps_user_diary_author_under_budget(self):
        block, _, _ = conversation_recall.pack([], 1000, [{
            **memory(), "author_role": "user", "author_name": "小雨",
        }])
        self.assertIn('author_role', block)
        self.assertIn('user', block)
        self.assertIn('小雨', block)
        self.assertNotIn('我今天去了海边', block)
        self.assertLessEqual(len(block), 1000)

    async def test_compact_request_has_assistant_author_but_temporary_summary_stays_separate(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": "小雨告诉我，她去了海边。"},
                                                   "finish_reason": "stop"}]}
        client = MagicMock()
        client.post = AsyncMock(return_value=response)
        with ExitStack() as stack:
            for key, value in {
                "build_system_prompt": AsyncMock(return_value=""),
                "get_standing_memory_blocks": AsyncMock(return_value=[]),
                "get_identity_presets": AsyncMock(return_value={"user_name": "小雨", "assistant_name": "Ash"}),
                "get_http_client": AsyncMock(return_value=client),
                "_record_token_usage": AsyncMock(),
            }.items():
                stack.enter_context(patch.object(main, key, value))
            for temporary in (False, True):
                await main._generate_handoff_summary(
                    [{"role": "user", "content": "我去了海边。"}],
                    runtime={"api_url": "https://example.test/v1", "api_key": "test", "model": "test"},
                    temporary=temporary,
                )
                messages = client.post.await_args.kwargs["json"]["messages"]
                system = messages[0]["content"]
                context = messages[1]["content"]
                self.assertEqual("主要围绕用户分享的事情" in system, not temporary)
                self.assertEqual("<diary_author>" in context, not temporary)
                if not temporary:
                    self.assertIn("Ash", context)
                    self.assertIn("小雨", context)
                    self.assertIn("「我」始终是助手", system)
