import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import Request
from fastapi.responses import JSONResponse

import main
import httpx


def make_request(path, method="GET", headers=None, query_string=b"", body=b""):
    raw_headers = [
        (str(key).lower().encode("latin-1"), str(value).encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": query_string,
        "headers": raw_headers,
        "client": ("127.0.0.1", 1234),
        "server": ("example.test", 443),
    }, receive)


async def accepted(_request):
    return JSONResponse({"accepted": True})


class GatewayDualAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_identity_sticker_is_served_as_webp_and_revalidated(self):
        path = "/static/images/identity-companions.0a482df39a3a.webp"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                     base_url="http://test") as client:
            response = await client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['content-type'], 'image/webp')
            self.assertLess(len(response.content), 300000)
            self.assertIn('immutable', response.headers['cache-control'])
            cached = await client.get(path, headers={'If-None-Match': response.headers['etag']})
            self.assertEqual(cached.status_code, 304)
            self.assertIn('immutable', cached.headers['cache-control'])

    async def test_identity_sticker_cache_is_immutable_only_for_success(self):
        path = "/static/images/identity-companions.0a482df39a3a.webp"
        for code in (200, 304, 404, 503):
            async def serve(_request):
                return JSONResponse({}, status_code=code)
            response = await main.gateway_auth_middleware(make_request(path), serve)
            if code in (200, 304):
                self.assertEqual(response.headers['cache-control'],
                                 'public, max-age=31536000, immutable')
            else:
                self.assertNotIn('cache-control', response.headers)

    async def test_public_health_reports_database_degradation(self):
        with patch.object(main, "MEMORY_ENABLED", True), patch.object(
            main,
            "get_all_memories_count",
            AsyncMock(side_effect=RuntimeError("database unavailable")),
        ):
            result = await main.health_check()

        self.assertEqual("degraded", result["status"])
        self.assertEqual("unavailable", result["database_status"])
        self.assertNotIn("database unavailable", str(result))

    async def test_program_api_accepts_only_bearer_header(self):
        with patch.object(main, "GATEWAY_SECRET", "api-secret"):
            accepted_response = await main.gateway_auth_middleware(
                make_request("/v1/models", headers={
                    "Authorization": "Bearer api-secret",
                }),
                accepted,
            )
            query_response = await main.gateway_auth_middleware(
                make_request("/v1/models", query_string=b"token=api-secret"),
                accepted,
            )
            raw_response = await main.gateway_auth_middleware(
                make_request("/v1/models", headers={"Authorization": "api-secret"}),
                accepted,
            )

        self.assertEqual(200, accepted_response.status_code)
        self.assertEqual(401, query_response.status_code)
        self.assertEqual(401, raw_response.status_code)

    async def test_dashboard_cookie_and_csrf_are_independent_from_gateway_secret(self):
        with patch.object(main, "DASHBOARD_PASSWORD", "dashboard-password"):
            session_value, csrf = main._create_dashboard_session()
            cookie = f"{main._DASHBOARD_SESSION_COOKIE}={session_value}"
            get_response = await main.gateway_auth_middleware(
                make_request("/api/conversations", headers={"Cookie": cookie}),
                accepted,
            )
            missing_csrf = await main.gateway_auth_middleware(
                make_request("/api/conversations", method="POST", headers={"Cookie": cookie}),
                accepted,
            )
            post_response = await main.gateway_auth_middleware(
                make_request("/api/conversations", method="POST", headers={
                    "Cookie": cookie,
                    "X-CSRF-Token": csrf,
                }),
                accepted,
            )

        self.assertEqual(200, get_response.status_code)
        self.assertEqual(403, missing_csrf.status_code)
        self.assertEqual(200, post_response.status_code)

    async def test_login_sets_httponly_session_cookie(self):
        body = json.dumps({"password": "dashboard-password"}).encode("utf-8")
        request = make_request(
            "/auth/login", method="POST",
            headers={"Content-Type": "application/json"}, body=body,
        )
        with patch.object(main, "DASHBOARD_PASSWORD", "dashboard-password"), patch.object(
            main, "DASHBOARD_COOKIE_SECURE", True
        ):
            response = await main.dashboard_login(request)

        cookie = response.headers.get("set-cookie", "")
        self.assertEqual(200, response.status_code)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=strict", cookie)

    async def test_dashboard_page_redirects_to_login_without_cookie(self):
        with patch.object(main, "DASHBOARD_PASSWORD", "dashboard-password"):
            response = await main.gateway_auth_middleware(
                make_request("/dashboard"), accepted
            )

        self.assertEqual(303, response.status_code)
        self.assertEqual("/login", response.headers["location"])


if __name__ == "__main__":
    unittest.main()
