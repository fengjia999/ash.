import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import main


class RouteSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_route_provider_is_loaded(self):
        with patch.object(
            main, "get_route_settings", AsyncMock(return_value={"provider": "openai"})
        ):
            self.assertEqual("openai", await main._load_route_provider())

    async def test_route_provider_falls_back_to_environment(self):
        with patch.object(
            main, "get_route_settings", AsyncMock(side_effect=RuntimeError("db unavailable"))
        ), patch.object(main, "ROUTE_PROVIDER", "anthropic"):
            self.assertEqual("anthropic", await main._load_route_provider())

    async def test_route_setting_is_saved(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={"provider": "openai"})
        save = AsyncMock(return_value={"provider": "openai"})

        with patch.object(main, "save_route_settings", save):
            result = await main.api_update_route_settings(request)

        self.assertEqual("ok", result["status"])
        save.assert_awaited_once_with("openai")

    async def test_invalid_route_provider_is_rejected(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={"provider": "other"})

        response = await main.api_update_route_settings(request)

        self.assertEqual(400, response.status_code)


if __name__ == "__main__":
    unittest.main()
