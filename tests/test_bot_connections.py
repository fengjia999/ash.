import json
import unittest
from unittest.mock import AsyncMock, patch

import bot_connections as bots
import main
from test_gateway_auth import make_request


def fields(**updates):
    return {"enabled": True,
            "project_id": "project", "project_secret": "photon-key", "home_user": "+8613800000000",
            "allowed_users": [], **updates}


class BotConnectionTests(unittest.IsolatedAsyncioTestCase):
    def test_credentials_are_preserved_but_never_returned(self):
        config = bots.merged_config(bots.ConnectionInput(**fields()), None)
        self.assertEqual(config["allowed_users"], [config["home_user"]])
        self.assertTrue(config["gateway_token"].startswith("ash_bot_"))
        updated = bots.merged_config(bots.ConnectionInput(**fields(project_secret="", enabled=False)), config)
        self.assertEqual(updated["project_secret"], "photon-key")
        self.assertEqual(updated["gateway_token"], config["gateway_token"])
        public = json.dumps(bots.public(updated))
        for key in bots.SECRET_FIELDS:
            self.assertNotIn(updated[key], public)
        self.assertIn('"project_secret_configured": true', public)

    def test_validates_required_fields_and_allowlist_before_any_changes(self):
        with self.assertRaisesRegex(ValueError, "启用前"):
            bots.merged_config(bots.ConnectionInput(**fields(project_secret="")), None)
        with self.assertRaises(ValueError):
            bots.merged_config(bots.ConnectionInput(**fields(allowed_users=["x\ny"])), None)
        with self.assertRaises(ValueError):
            bots.merged_config(bots.ConnectionInput(**fields(project_secret="x\ny")), None)

    async def test_save_only_persists_to_ash_and_wakes_the_internal_runtime(self):
        with patch.object(bots, "load", AsyncMock(return_value=None)), patch.object(bots, "save", AsyncMock()) as save:
            result = await bots.apply_connection(bots.ConnectionInput(**fields()), object())
        self.assertTrue(result["queued"])
        config = save.await_args.args[0]
        self.assertEqual(config["project_id"], "project")
        self.assertTrue(config["gateway_token"].startswith("ash_bot_"))
        self.assertNotIn("photon-key", json.dumps(result))
        self.assertNotIn("gateway_token", result["connection"])
        self.assertNotIn("bridge_url", result["connection"])

    async def test_disabling_revokes_bot_auth_and_overrides_legacy_notifications(self):
        config = bots.merged_config(bots.ConnectionInput(**fields()), None)
        with patch.object(bots, "load", AsyncMock(return_value=config)) as load, patch.object(bots.runtime, "endpoint", AsyncMock(return_value=("http://127.0.0.1:12345/notify", "internal-key"))):
            self.assertTrue(await bots.authorize(config["gateway_token"]))
            self.assertFalse(await bots.authorize("ash_bot_wrong"))
            self.assertEqual(await bots.notification_config("old-url", "old-key"), ("http://127.0.0.1:12345/notify", "internal-key"))
            config["enabled"] = False
            self.assertFalse(await bots.authorize(config["gateway_token"]))
            self.assertEqual(await bots.notification_config("old-url", "old-key"), ("", ""))
            load.return_value = None
            self.assertEqual(await bots.notification_config("old-url", "old-key"), ("old-url", "old-key"))

    async def test_bot_credential_only_grants_chat_routes_and_never_dashboard_access(self):
        token = "ash_bot_dedicated"
        with patch.object(main, "GATEWAY_SECRET", ""), patch.object(main, "DASHBOARD_PASSWORD", "dashboard"), patch.object(
            bots, "authorize", AsyncMock(return_value=True)) as auth:
            for path in ("/v1/chat/completions", "/v1/models"):
                result = await main.gateway_auth_middleware(make_request(path, headers={"Authorization": "Bearer " + token}), AsyncMock(return_value="allowed"))
                self.assertEqual(result, "allowed")
            for path in ("/v1/admin", "/api/bot-connections/imessage"):
                result = await main.gateway_auth_middleware(make_request(path, headers={"Authorization": "Bearer " + token}), AsyncMock(return_value="allowed"))
                self.assertEqual(result.status_code, 401)
            self.assertEqual(auth.await_count, 2)

    async def test_validation_errors_do_not_echo_secret_input(self):
        result = await bots.put_connection(make_request("/api/bot-connections/imessage", method="PUT", body=json.dumps(fields(project_secret="sensitive" * 1000)).encode()))
        self.assertEqual(result.status_code, 400)
        self.assertNotIn("sensitive", result.body.decode())

    async def test_check_status_whitelists_internal_payload(self):
        config = bots.merged_config(bots.ConnectionInput(**fields()), None)
        with patch.object(bots, "load", AsyncMock(return_value=config)), patch.object(bots.runtime, "status", AsyncMock(return_value={
                "status": "connected", "projectSecret": "do-not-return", "error": "untrusted diagnostic"})):
            result = await bots.check_connection()
        self.assertEqual(result["status"], "connected")
        self.assertNotIn("do-not-return", json.dumps(result))
        self.assertNotIn("untrusted", json.dumps(result))

    async def test_catalog_has_future_slots_and_only_safe_connection_summaries(self):
        config = bots.merged_config(bots.ConnectionInput(**fields()), None)
        with patch.object(bots, "load", AsyncMock(return_value=config)):
            result = await bots.list_connections()
        self.assertEqual([item["id"] for item in result["providers"]], ["imessage", "qq", "weixin", "feishu"])
        self.assertEqual([item["id"] for item in result["providers"] if item["available"]], ["imessage", "qq", "weixin", "feishu"])
        self.assertEqual(result["connections"][0]["account"], config["home_user"])
        self.assertNotIn(config["project_secret"], json.dumps(result))
        self.assertNotIn(config["gateway_token"], json.dumps(result))
        with patch.object(bots, "load", AsyncMock(return_value=None)):
            self.assertEqual((await bots.list_connections())["connections"], [])
