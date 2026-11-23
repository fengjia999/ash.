import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import main


class DiaryKeywordTests(unittest.IsolatedAsyncioTestCase):
    async def generate(self, output='["旅行", "海边", "朋友"]', kind='diary', updated=7, configured=True, preview=False, draft=None):
        memory = {"id": 7, "title": "周末", "content": "和朋友去海边旅行",
                  "keywords": ["旧词"], "metadata": {"entry_kind": kind}}
        response = MagicMock()
        response.json.return_value = {"choices": [{"message": {"content": output}}]}
        client = MagicMock()
        client.post = AsyncMock(return_value=response)
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=updated)
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with ExitStack() as stack:
            for name, value in {
                "MEMORY_ENABLED": True,
                "get_long_term_memory": AsyncMock(return_value=memory),
                "_identity_presets_for_background_prompt": AsyncMock(return_value={"user_name":"小雨", "assistant_name":"Ash"}),
                "_load_model_task_runtime": AsyncMock(return_value={
                    "api_url": "https://example.test/v1" if configured else "",
                    "api_key": "test" if configured else "",
                    "model": "keyword-test" if configured else "",
                }),
                "get_http_client": AsyncMock(return_value=client),
                "get_pool": AsyncMock(return_value=pool),
            }.items():
                stack.enter_context(patch.object(main, name, value))
            if preview:
                request = MagicMock()
                request.json = AsyncMock(return_value=draft if draft is not None else {
                    "title":"未保存的标题", "content":"刚刚改过的正文", "author_role":"user"})
                result = await main.api_preview_diary_keywords(request)
            else:
                result = await main.api_generate_diary_keywords(7)
        return result, client, conn

    async def test_uses_keyword_model_and_updates_only_keywords(self):
        result, client, conn = await self.generate()
        self.assertEqual(result["keywords"], ["旅行", "海边", "朋友"])
        payload = client.post.await_args.kwargs["json"]
        self.assertEqual(payload["model"], "keyword-test")
        self.assertIn("和朋友去海边旅行", payload["messages"][1]["content"])
        sql, *args = conn.fetchval.await_args.args
        self.assertIn("SET keywords = $2::jsonb", sql)
        self.assertIn("AND content = $4", sql)
        self.assertEqual(json.loads(args[4]), ["旧词"])

    async def test_invalid_model_output_preserves_existing_keywords(self):
        for output in ('not json', '{}', '["一个"]', '["旅行", 5, "朋友"]'):
            result, _, conn = await self.generate(output=output)
            self.assertEqual(result.status_code, 502)
            conn.fetchval.assert_not_awaited()

    async def test_rejects_fragments_and_missing_configuration(self):
        for kwargs, status in (({"kind": "fragment"}, 404), ({"configured": False}, 409)):
            result, client, conn = await self.generate(**kwargs)
            self.assertEqual(result.status_code, status)
            client.post.assert_not_awaited()
            conn.fetchval.assert_not_awaited()

    async def test_concurrent_edit_returns_conflict(self):
        result, _, _ = await self.generate(updated=None)
        self.assertEqual(result.status_code, 409)

    async def test_preview_uses_unsaved_text_and_author_without_database_write(self):
        result, client, conn = await self.generate(preview=True)
        self.assertEqual(result["keywords"], ["旅行", "海边", "朋友"])
        draft = json.loads(client.post.await_args.kwargs["json"]["messages"][1]["content"])
        self.assertEqual(draft["content"], "刚刚改过的正文")
        self.assertEqual(draft["title"], "未保存的标题")
        self.assertEqual(draft["author_role"], "user")
        self.assertEqual(draft["author_name"], "小雨")
        conn.fetchval.assert_not_awaited()

    async def test_preview_rejects_invalid_drafts_before_model_call(self):
        for draft in ({}, {"content":" "}, {"content":5}, {"content":"日记", "title":[]},
                      {"content":"日记", "author_role":"system"}, []):
            result, client, conn = await self.generate(preview=True, draft=draft)
            self.assertEqual(result.status_code, 400)
            client.post.assert_not_awaited()
            conn.fetchval.assert_not_awaited()

    async def test_preview_model_failure_does_not_write_keywords(self):
        result, _, conn = await self.generate(preview=True, output='not json')
        self.assertEqual(result.status_code, 502)
        conn.fetchval.assert_not_awaited()
