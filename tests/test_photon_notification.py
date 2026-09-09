import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import main


class PhotonNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_notification_posts_to_configured_bridge(self):
        response = MagicMock(status_code=200, text='{"ok":true}')
        client = MagicMock()
        client.post = AsyncMock(return_value=response)

        with patch.object(main, "PHOTON_NOTIFY_URL", "https://bridge.example/notify"), patch.object(
            main, "PHOTON_NOTIFY_SECRET", "bridge-secret"
        ), patch.object(main, "get_http_client", AsyncMock(return_value=client)):
            result = await main.dispatch_tool_call(
                "send_imessage_notification",
                {"text": "第一行\n第二行", "effect": "loud"},
            )

        self.assertEqual("iMessage notification delivered", result)
        client.post.assert_awaited_once_with(
            "https://bridge.example/notify",
            headers={
                "Authorization": "Bearer bridge-secret",
                "Content-Type": "application/json",
            },
            json={"text": "第一行\n第二行", "effect": "loud"},
            timeout=30,
        )

    async def test_notification_rejects_missing_configuration(self):
        with patch.object(main, "PHOTON_NOTIFY_URL", ""), patch.object(
            main, "PHOTON_NOTIFY_SECRET", ""
        ):
            result = await main.dispatch_tool_call(
                "send_imessage_notification", {"text": "hello"}
            )

        self.assertTrue(result.startswith("Error:"))

    async def test_notification_rejects_empty_text(self):
        with patch.object(main, "PHOTON_NOTIFY_URL", "https://bridge.example/notify"), patch.object(
            main, "PHOTON_NOTIFY_SECRET", "bridge-secret"
        ):
            result = await main.dispatch_tool_call(
                "send_imessage_notification", {"text": "   "}
            )

        self.assertEqual("Error: notification text is required", result)
