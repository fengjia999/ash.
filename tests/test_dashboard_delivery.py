import gzip
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.responses import Response
from dashboard_delivery import DashboardGZipMiddleware
from test_gateway_auth import make_request
import main


class DashboardDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def deliver(self, path, content_type, chunks, method="GET", headers=()):
        sent = []

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", content_type.encode()), *headers]})
            for index, chunk in enumerate(chunks):
                await send({"type": "http.response.body", "body": chunk,
                            "more_body": index < len(chunks) - 1})

        async def send(message):
            sent.append(message)

        async def receive():
            return {"type": "http.disconnect"}

        scope = {"type": "http", "path": path, "method": method,
                 "headers": [(b"accept-encoding", b"gzip")]}
        await DashboardGZipMiddleware(app, minimum_size=1000, compresslevel=4)(scope, receive, send)
        return dict(sent[0]["headers"]), [message["body"] for message in sent[1:]]

    async def test_html_css_and_json_are_compressed_and_lossless(self):
        body = ("长文本用于验证压缩后内容完整。" * 500).encode()
        for path, mime in (("/dashboard", "text/html"), ("/static/css/dashboard.css", "text/css"),
                           ("/api/conversations", "application/json")):
            with self.subTest(path=path):
                headers, chunks = await self.deliver(path, mime, [body[:1500], body[1500:]])
                compressed = b"".join(chunks)
                self.assertEqual(b"gzip", headers[b"content-encoding"])
                self.assertIn(b"Accept-Encoding", headers[b"vary"])
                self.assertEqual(body, gzip.decompress(compressed))
                self.assertLess(len(compressed), len(body) // 5)

    async def test_streams_writes_binary_assets_and_no_transform_are_untouched(self):
        chunks = [b"data: first\n\n", b"data: [DONE]\n\n"]
        cases = (
            ("/api/events", "text/event-stream", "GET", ()),
            ("/api/conversations/7/chat", "text/event-stream", "POST", ()),
            ("/v1/chat/completions", "text/event-stream", "GET", ()),
            ("/export/memories", "application/json", "GET", ()),
            ("/static/font.woff2", "font/woff2", "GET", ()),
            ("/static/image.webp", "image/webp", "GET", ()),
            ("/api/data", "application/json", "GET", ((b"cache-control", b"no-transform"),)),
        )
        for path, mime, method, extra in cases:
            with self.subTest(path=path):
                headers, received = await self.deliver(path, mime, chunks, method, extra)
                self.assertNotIn(b"content-encoding", headers)
                self.assertEqual(chunks, received)

    async def test_small_json_does_not_incur_compression(self):
        headers, chunks = await self.deliver("/api/status", "application/json", [b"{}"])
        self.assertNotIn(b"content-encoding", headers)
        self.assertEqual([b"{}"], chunks)

    async def test_only_successful_versioned_static_assets_get_long_cache(self):
        for code in (200, 304, 404, 500):
            async def serve(request):
                return Response(status_code=code)
            response = await main.gateway_auth_middleware(
                make_request("/static/js/dashboard.js", query_string=b"v=12345"), serve)
            if code in {200, 304}:
                self.assertIn("immutable", response.headers["cache-control"])
            else:
                self.assertNotIn("cache-control", response.headers)

    async def test_unversioned_assets_still_revalidate_and_fonts_have_bounded_cache(self):
        async def serve(request):
            return Response()
        plain = await main.gateway_auth_middleware(make_request("/static/js/dashboard.js"), serve)
        self.assertNotIn("cache-control", plain.headers)
        font = await main.gateway_auth_middleware(make_request("/static/fonts/wenkai/a.woff2"), serve)
        self.assertEqual("public, max-age=86400", font.headers["cache-control"])

    def test_shared_parent_and_frame_assets_have_the_same_version(self):
        common = dict(request=MagicMock(), static_version=123, chat_version=456,
                      csrf_token="test", initial_conversation_id=0, show_created_modal=False)
        dashboard = main.templates.env.get_template("dashboard.html").render(**common)
        context = main.templates.env.get_template("context.html").render(embedded="list", **common)
        for path in ("fonts/wenkai.css", "js/theme.js", "js/usage-paper.js", "css/night.css"):
            url = f"/static/{path}?v=123"
            self.assertIn(url, dashboard)
            self.assertIn(url, context)


if __name__ == "__main__":
    unittest.main()
