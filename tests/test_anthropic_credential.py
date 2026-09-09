import unittest
from unittest.mock import AsyncMock, patch

from fastapi.responses import JSONResponse

import main
import database


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class AnthropicCredentialTests(unittest.IsolatedAsyncioTestCase):
    def test_gateway_backup_excludes_credential_table(self):
        backup_tables = {
            spec["table"] for spec in database.GATEWAY_BACKUP_TABLES.values()
        }
        self.assertNotIn("anthropic_credentials", backup_tables)

    async def test_dashboard_key_takes_precedence_over_environment(self):
        with (
            patch.object(main, "API_KEY", "environment-key"),
            patch.object(
                main,
                "get_anthropic_credentials",
                AsyncMock(return_value={"api_key": "dashboard-key"}),
            ),
        ):
            self.assertEqual("dashboard-key", await main._load_anthropic_api_key())

    async def test_environment_remains_compatibility_fallback(self):
        with (
            patch.object(main, "API_KEY", "environment-key"),
            patch.object(
                main,
                "get_anthropic_credentials",
                AsyncMock(return_value={"api_key": ""}),
            ),
        ):
            self.assertEqual("environment-key", await main._load_anthropic_api_key())

    async def test_public_status_never_returns_plaintext_key(self):
        with patch.object(
            main,
            "get_anthropic_credentials",
            AsyncMock(return_value={"api_key": "do-not-return", "updated_at": None}),
        ):
            status = await main._anthropic_credential_public_status()

        self.assertEqual("database", status["source"])
        self.assertTrue(status["stored_in_dashboard"])
        self.assertNotIn("do-not-return", repr(status))
        self.assertNotIn("api_key", status)

    async def test_dashboard_save_strips_key_and_returns_only_status(self):
        save = AsyncMock(return_value={"api_key": "new-secret", "updated_at": None})
        with (
            patch.object(main, "save_anthropic_api_key", save),
            patch.object(
                main,
                "get_anthropic_credentials",
                AsyncMock(return_value={"api_key": "new-secret", "updated_at": None}),
            ),
        ):
            result = await main.api_set_anthropic_credential(
                FakeRequest({"api_key": "  new-secret  "})
            )

        save.assert_awaited_once_with("new-secret")
        self.assertEqual("ok", result["status"])
        self.assertNotIn("new-secret", repr(result))

    async def test_dashboard_rejects_empty_key(self):
        response = await main.api_set_anthropic_credential(
            FakeRequest({"api_key": "  "})
        )
        self.assertIsInstance(response, JSONResponse)
        self.assertEqual(400, response.status_code)

    async def test_dashboard_delete_reports_environment_fallback(self):
        with (
            patch.object(main, "API_KEY", "environment-key"),
            patch.object(main, "delete_anthropic_api_key", AsyncMock(return_value=True)),
            patch.object(
                main,
                "get_anthropic_credentials",
                AsyncMock(return_value={"api_key": "", "updated_at": None}),
            ),
        ):
            result = await main.api_delete_anthropic_credential()

        self.assertTrue(result["deleted"])
        self.assertEqual("environment", result["source"])

    def test_headers_accept_resolved_dashboard_key(self):
        with patch.object(
            main,
            "ANTHROPIC_API_URL",
            "https://api.anthropic.com/v1/messages",
        ):
            headers = main._anthropic_headers("dashboard-key")
        self.assertEqual("dashboard-key", headers["x-api-key"])


if __name__ == "__main__":
    unittest.main()
