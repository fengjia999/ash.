import base64
import json
import unittest
from unittest.mock import AsyncMock, patch

from starlette.requests import Request
import main


# Minimal WebP fixture; a real decoder is exercised in browser checks.
WEBP = "data:image/webp;base64,UklGRiIAAABXRUJQVlA4IBYAAAAwAQCdASoBAAEADsD+JaQAA3AAAAAA"


def image_request(value):
    body = json.dumps(value).encode()
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({"type": "http", "method": "PUT", "path": "/api/identity-presets/avatar/user"}, receive)


class IdentityAvatarTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_saves_only_the_selected_role_and_get_returns_both(self):
        saved = {"user_name": "我", "assistant_name": "Ash", "user_avatar": WEBP, "assistant_avatar": ""}
        with patch.object(main, "save_identity_avatar", AsyncMock(return_value=saved)) as save:
            result = await main.api_update_identity_avatar("user", image_request({"image": WEBP}))
        save.assert_awaited_once_with("user", WEBP)
        self.assertEqual(WEBP, result["image"])
        with patch.object(main, "get_identity_presets", AsyncMock(return_value=saved)):
            data = await main.api_get_identity_presets()
        self.assertEqual(WEBP, data["user_avatar"])
        self.assertEqual("", data["assistant_avatar"])
        self.assertEqual("我", data["user_name"])

    async def test_reset_does_not_require_or_change_names(self):
        with patch.object(main, "save_identity_avatar", AsyncMock(return_value={"assistant_avatar": ""})) as save:
            result = await main.api_update_identity_avatar("assistant", image_request({"image": ""}))
        save.assert_awaited_once_with("assistant", "")
        self.assertEqual("", result["image"])

    async def test_invalid_uploads_never_reach_storage(self):
        oversize = b"\xff\xd8\xff" + b"x" * (10 * 1024) + b"\xff\xd9"
        cases = [
            ("other", {"image": WEBP}), ("user", []), ("user", {"image": None}),
            ("user", {"image": "https://example.test/avatar.jpg"}),
            ("user", {"image": "data:image/svg+xml;base64,PHN2Zz4="}),
            ("user", {"image": "data:image/webp;base64,AAAA"}),
            ("user", {"image": "data:image/jpeg;base64," + base64.b64encode(oversize).decode()}),
            ("user", {"image": "x" * 17000}),
        ]
        with patch.object(main, "save_identity_avatar", AsyncMock()) as save:
            for role, payload in cases:
                with self.subTest(role=role, payload_size=len(str(payload))):
                    response = await main.api_update_identity_avatar(role, image_request(payload))
                    self.assertEqual(400, response.status_code)
            save.assert_not_awaited()
