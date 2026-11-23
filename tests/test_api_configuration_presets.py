import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import main


def request(data):
    value = MagicMock()
    value.json = AsyncMock(return_value=data)
    return value


class ApiConfigurationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = {"provider": "openai", "api_url": "https://saved.test/v1",
                       "api_key": "saved-secret", "model": "claude-through-openai"}
        self.openai_profiles = self.enterContext(patch.object(main, "get_openai_provider_profiles", AsyncMock(return_value=[])))
        self.anthropic_profiles = self.enterContext(patch.object(main, "get_anthropic_provider_profiles", AsyncMock(return_value=[])))

    async def test_fixed_configuration_uses_the_matching_supplier_name(self):
        self.openai_profiles.return_value = [{"name": "日常供应商", "api_url": "https://saved.test/v1/chat/completions", "api_key": "saved-secret"}]
        with patch.object(main, "get_route_settings", AsyncMock(return_value=self.config)):
            fixed = await main._fixed_chat_configuration()
        self.assertEqual("日常供应商", fixed["upstream"]["name"])
        self.assertEqual(self.config["api_key"], fixed["upstream"]["api_key"])
        self.assertEqual(self.config["api_url"], fixed["upstream"]["api_url"])

    async def test_supplier_name_matching_respects_credentials_and_ambiguity(self):
        self.openai_profiles.return_value = [{"name": "另一账号", "api_url": self.config["api_url"], "api_key": "different-key"}]
        self.assertEqual("saved.test", await main._configuration_provider_name("openai", self.config))
        self.openai_profiles.return_value = [dict(self.config, name="名称一"), dict(self.config, name="名称二")]
        self.assertEqual("saved.test", await main._configuration_provider_name("openai", self.config))
        self.openai_profiles.side_effect = RuntimeError("profiles unavailable")
        self.assertEqual("saved.test", await main._configuration_provider_name("openai", self.config))

    async def test_current_configuration_shows_supplier_name_without_exposing_key(self):
        self.openai_profiles.return_value = [dict(self.config, name="日常供应商")]
        with patch.object(main, "get_route_settings", AsyncMock(return_value=self.config)):
            result = await main.api_get_route_settings()
        self.assertEqual("日常供应商", result["provider_name"])
        self.assertEqual("openai", result["provider"])
        self.assertNotIn("api_key", result)
        self.assertNotIn(self.config["api_key"], json.dumps(result))

    async def test_old_heartbeat_label_resolves_against_its_frozen_connection(self):
        self.anthropic_profiles.return_value = [{"name": "旧供应商", "api_url": "https://previous.test/v1", "api_key": "previous-secret"}]
        snapshot = {"name": "聊天配置", "api_url": "https://previous.test/v1/messages", "api_key": "previous-secret"}
        runtime = await main._heartbeat_runtime({"last_route_provider": "anthropic", "last_model": "old-model",
            "last_provider_name": "聊天配置", "last_chat_provider_snapshot": snapshot})
        self.assertEqual("旧供应商", runtime["provider_name"])
        self.assertEqual(snapshot["api_url"], runtime["provider"]["api_url"])
        self.assertEqual(snapshot["api_key"], runtime["provider"]["api_key"])
        self.assertEqual("聊天配置", snapshot["name"])

    async def test_named_heartbeat_snapshot_does_not_follow_profile_edits(self):
        runtime = await main._heartbeat_runtime({"last_route_provider": "openai", "last_model": "old-model",
            "last_provider_name": "原供应商", "last_chat_provider_snapshot": dict(self.config, name="原供应商")})
        self.assertEqual("原供应商", runtime["provider_name"])
        self.openai_profiles.assert_not_awaited()
        self.anthropic_profiles.assert_not_awaited()

    async def test_named_configuration_without_snapshot_does_not_use_environment(self):
        with patch.object(main, "_environment_openai_provider", side_effect=AssertionError("must not change connection")):
            runtime = await main._heartbeat_runtime({"last_route_provider": "openai", "last_model": "old-model",
                "last_provider_name": "原供应商", "last_provider_profile_id": None})
        self.assertFalse(runtime["ready"])

    async def test_supplier_credentials_are_reused_without_changing_saved_suppliers(self):
        for supplier_type in ("openai", "anthropic"):
            with self.subTest(supplier_type=supplier_type):
                profile = {"id": 7, "api_url": "https://supplier.test/v1", "api_key": "supplier-secret"}
                draft = {"provider": "auto", "model": "chosen-model", "source_provider_type": supplier_type,
                         "source_provider_id": 7, "api_key": "", "api_url": ""}
                with patch.object(main, "get_" + supplier_type + "_provider_profile", AsyncMock(return_value=profile)) as read, \
                     patch.object(main, "_current_api_configuration", AsyncMock()) as current:
                    result = await main._api_configuration_values(draft)
                read.assert_awaited_once_with(7)
                current.assert_not_awaited()
                self.assertEqual(result, {"provider": "auto", "model": "chosen-model",
                                          "api_url": profile["api_url"], "api_key": "supplier-secret"})

    async def test_saving_model_preset_copies_supplier_key_and_keeps_route(self):
        profile = {"api_url": "https://supplier.test/v1/messages", "api_key": "supplier-secret"}
        draft = {"name": "常用模型", "provider": "anthropic", "model": "chosen-model",
                 "source_provider_type": "anthropic", "source_provider_id": 7}
        with patch.object(main, "get_anthropic_provider_profile", AsyncMock(return_value=profile)), \
             patch.object(main, "save_api_configuration_preset", AsyncMock(return_value={"id": 9, **profile, **draft})) as save, \
             patch.object(main, "save_route_settings", AsyncMock()) as apply:
            result = await main.api_save_api_preset(request(draft))
        save.assert_awaited_once_with("常用模型", provider="anthropic", model="chosen-model", **profile)
        apply.assert_not_awaited()
        self.assertNotIn("api_key", result["preset"])

    async def test_missing_supplier_key_never_falls_back_to_another_supplier(self):
        draft = {"provider": "openai", "model": "model", "source_provider_type": "openai", "source_provider_id": 7}
        with patch.object(main, "_current_api_configuration", AsyncMock()) as current:
            for profile in (None, {"api_url": "https://supplier.test/v1", "api_key": ""}):
                with patch.object(main, "get_openai_provider_profile", AsyncMock(return_value=profile)):
                    with self.assertRaises(ValueError):
                        await main._api_configuration_values(draft)
            current.assert_not_awaited()
        for invalid in ({"source_provider_id": True}, {"source_provider_type": []}, {"source_provider_type": "invalid"}):
            with self.assertRaises(ValueError):
                await main._api_configuration_values({**draft, **invalid})

    async def test_presets_are_redacted_and_saving_does_not_apply(self):
        save = AsyncMock(return_value={"id": 4, "name": "日常", **self.config})
        with patch.object(main, "save_api_configuration_preset", save), \
             patch.object(main, "save_route_settings", AsyncMock()) as apply, \
             patch.object(main, "activate_openai_provider_profile", AsyncMock()) as activate:
            result = await main.api_save_api_preset(request({"name": "日常", **self.config}))
        save.assert_awaited_once_with("日常", **self.config)
        apply.assert_not_awaited()
        activate.assert_not_awaited()
        self.assertNotIn("api_key", result["preset"])
        self.assertEqual("openai", result["preset"]["provider"])
        self.assertEqual("••••cret", result["preset"]["api_key_hint"])

    async def test_loaded_preset_copies_its_key_once_into_current_settings(self):
        saved = {"id": 4, "name": "夜晚", **self.config}
        apply = AsyncMock(side_effect=lambda **fields: fields)
        data = {**self.config, "api_key": "", "source_preset_id": 4}
        with patch.object(main, "get_api_configuration_preset", AsyncMock(return_value=saved)), \
             patch.object(main, "save_route_settings", apply), \
             patch.object(main, "update_openai_provider_profile", AsyncMock()) as edit, \
             patch.object(main, "activate_anthropic_provider_profile", AsyncMock()) as activate:
            result = await main.api_update_route_settings(request(data))
        apply.assert_awaited_once_with(**self.config)
        edit.assert_not_awaited()
        activate.assert_not_awaited()
        self.assertNotIn("api_key", result)
        # Runtime reads the copied configuration, independently of the saved preset.
        with patch.object(main, "get_route_settings", AsyncMock(return_value=self.config)), \
             patch.object(main, "get_api_configuration_preset", AsyncMock(side_effect=AssertionError("runtime binding"))):
            fixed = await main._fixed_chat_configuration()
        self.assertTrue(fixed["uses_openai"])
        self.assertEqual("saved-secret", fixed["upstream"]["api_key"])

    async def test_deleting_preset_does_not_change_current_route_or_provider(self):
        with patch.object(main, "delete_api_configuration_preset", AsyncMock(return_value=True)), \
             patch.object(main, "save_route_settings", AsyncMock()) as apply, \
             patch.object(main, "delete_openai_provider_profile", AsyncMock()) as provider:
            self.assertEqual("ok", (await main.api_delete_api_preset(4))["status"])
        apply.assert_not_awaited()
        provider.assert_not_awaited()

    async def test_missing_preset_cannot_silently_substitute_another_key(self):
        with patch.object(main, "get_api_configuration_preset", AsyncMock(return_value=None)), \
             patch.object(main, "save_route_settings", AsyncMock()) as save:
            response = await main.api_update_route_settings(request({**self.config, "api_key": "", "source_preset_id": 4}))
        self.assertEqual(400, response.status_code)
        save.assert_not_awaited()

    async def test_models_are_fetched_from_draft_without_saving_it(self):
        read = AsyncMock(return_value={"data": [{"id": "available-model"}]})
        with patch.object(main, "_load_openai_provider_models", read), \
             patch.object(main, "_load_anthropic_provider_models", AsyncMock()) as other, \
             patch.object(main, "save_route_settings", AsyncMock()) as save:
            await main.api_configuration_models(request(self.config))
        read.assert_awaited_once_with(self.config, strict=True)
        other.assert_not_awaited()
        save.assert_not_awaited()

    async def test_model_fetch_uses_draft_url_and_protocol_and_returns_all_models(self):
        for route in ("openai", "anthropic"):
            with self.subTest(route=route):
                config = {**self.config, "provider": route, "api_url": "https://draft.test/v1/messages"}
                response = MagicMock(status_code=200)
                response.json.return_value = {"data": [{"id": "different-model"}, {"id": "other-model"}, {"id": "different-model"}]}
                client = MagicMock(get=AsyncMock(return_value=response))
                with patch.object(main, "get_http_client", AsyncMock(return_value=client)), \
                     patch.object(main, "save_route_settings", AsyncMock()) as save:
                    result = await main.api_configuration_models(request(config))
                self.assertEqual(["different-model", "other-model"], [item["id"] for item in result["data"]])
                headers = {"Authorization": "Bearer saved-secret"} if route == "openai" else {
                    "x-api-key": "saved-secret", "anthropic-version": main.ANTHROPIC_VERSION}
                client.get.assert_awaited_once_with("https://draft.test/v1/models", headers=headers, timeout=20)
                save.assert_not_awaited()

    async def test_model_fetch_reports_upstream_failures_instead_of_empty_success(self):
        cases = [(401, {"data": []}, None, "HTTP 401"),
                 (404, {}, None, "HTTP 404"),
                 (200, {"error": "saved-secret"}, None, "有效的模型列表"),
                 (200, None, ValueError("saved-secret"), "有效的模型列表"),
                 (None, None, main.httpx.ReadTimeout("saved-secret"), "超时"),
                 (None, None, main.httpx.ConnectError("saved-secret"), "无法连接")]
        for status, payload, error, message in cases:
            with self.subTest(message=message, status=status):
                response = MagicMock(status_code=status)
                response.json.return_value = payload
                if isinstance(error, ValueError):
                    response.json.side_effect = error
                    error = None
                client = MagicMock(get=AsyncMock(return_value=response, side_effect=error))
                with patch.object(main, "get_http_client", AsyncMock(return_value=client)):
                    result = await main.api_configuration_models(request(self.config))
                self.assertEqual(502, result.status_code)
                self.assertIn(message, json.loads(result.body)["error"])
                self.assertNotIn("saved-secret", result.body.decode())

    async def test_genuinely_empty_model_list_remains_successful(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"data": []}
        client = MagicMock(get=AsyncMock(return_value=response))
        with patch.object(main, "get_http_client", AsyncMock(return_value=client)):
            result = await main.api_configuration_models(request(self.config))
        self.assertEqual([], result["data"])

    async def test_old_settings_keep_their_route_and_supplier_without_migration(self):
        profile = {"id": 8, "api_key": "existing-key", "api_url": "https://existing.test/v1"}
        with patch.object(main, "get_route_settings", AsyncMock(return_value={"provider": "openai"})), \
             patch.object(main, "get_active_conversation", AsyncMock(return_value={"last_model": "previous-model"})), \
             patch.object(main, "_load_active_openai_provider", AsyncMock(return_value=profile)), \
             patch.object(main, "save_route_settings", AsyncMock()) as save:
            current = await main.api_get_route_settings()
            self.assertIsNone(await main._fixed_chat_configuration())
        self.assertEqual("openai", current["provider"])
        self.assertEqual("previous-model", current["model"])
        self.assertEqual(profile["api_url"], current["api_url"])
        save.assert_not_awaited()
        self.assertNotIn("api_key", current)

    async def test_fixed_model_list_avoids_upstream_model_discovery(self):
        with patch.object(main, "get_route_settings", AsyncMock(return_value=self.config)), \
             patch.object(main, "get_http_client", AsyncMock()) as network:
            result = await main.dashboard_chat_models()
        self.assertEqual(self.config["model"], result["default_model"])
        self.assertEqual([self.config["model"]], [item["id"] for item in result["data"]])
        network.assert_not_awaited()

    async def test_chat_ignores_client_model_and_protocol_hints_for_both_routes(self):
        for route, model in (("openai", "claude-through-openai"), ("anthropic", "gpt-through-anthropic")):
            with self.subTest(route=route), ExitStack() as stack:
                loop = AsyncMock(return_value="reply")
                other = AsyncMock()
                saved_route = AsyncMock()
                cfg = {**self.config, "provider": route, "model": model}
                for name, value in {
                    "get_route_settings": AsyncMock(return_value=cfg),
                    "get_active_conversation": AsyncMock(return_value={"id": 7, "capture_frontend_prompts": False}),
                    "resolve_conversation_tool_snapshot": AsyncMock(return_value=([], set())),
                    "is_tool_continuation": MagicMock(return_value=True),
                    "_seed_persisted_cache_anchor": MagicMock(),
                    "save_conversation_chat_route": saved_route,
                    "handle_openai_continuation": loop if route == "openai" else other,
                    "handle_tool_continuation": loop if route == "anthropic" else other,
                }.items():
                    stack.enter_context(patch.object(main, name, value))
                body = {"model": "ignore-client-model", "provider": "anthropic" if route == "openai" else "openai",
                        "route_provider": "opposite", "provider_hint": "opposite", "stream": True,
                        "messages": [{"role": "tool", "content": "result"}]}
                self.assertEqual("reply", await main.chat_completions(request(body)))
                actual = loop.await_args.args
                self.assertEqual(model, actual[0]["model"])
                self.assertEqual(model, actual[2])
                for hint in ("provider", "route_provider", "provider_hint"):
                    self.assertNotIn(hint, actual[0])
                saved_route.assert_not_awaited()
                other.assert_not_awaited()
                if route == "anthropic":
                    self.assertEqual("https://saved.test/v1/messages", actual[8])

    async def test_heartbeat_keeps_last_real_chat_snapshot_when_global_configuration_changes(self):
        with patch.object(main, "get_route_settings", AsyncMock(return_value=self.config)), \
             patch.object(main, "_environment_openai_provider", MagicMock(side_effect=AssertionError("wrong API"))):
            result = await main._heartbeat_runtime({"last_route_provider":"anthropic", "last_model":"previous-model",
                "last_provider_name":"聊天配置", "last_provider_profile_id":None,
                "last_chat_provider_snapshot":{"api_url":"https://previous.test/v1/messages", "api_key":"previous-secret"}})
        self.assertEqual("anthropic", result["route"])
        self.assertEqual("previous-model", result["model"])
        self.assertEqual("previous-secret", result["provider"]["api_key"])
        self.assertEqual("https://previous.test/v1/messages", result["provider"]["api_url"])

    async def test_legacy_fixed_chat_without_snapshot_waits_for_real_chat(self):
        with patch.object(main, "_fixed_chat_configuration", AsyncMock(side_effect=AssertionError("must not use global configuration"))):
            result = await main._heartbeat_runtime({"last_route_provider":"openai", "last_model":"old",
                                                   "last_provider_name":"聊天配置"})
        self.assertFalse(result["ready"])

    async def test_last_chat_provider_snapshot_is_persisted_with_route_and_model(self):
        import database
        provider = {"id": None, "name": "聊天配置", "source": "configuration",
                    "api_url": "https://previous.test/v1", "api_key": "previous-secret"}
        connection = MagicMock()
        connection.execute = AsyncMock()
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=connection)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(database, "get_pool", AsyncMock(return_value=pool)):
            await database.save_conversation_chat_route(7, "openai", None, "聊天配置", "old-model", provider_snapshot=provider)
        args = connection.execute.await_args.args
        self.assertIn("last_chat_provider_snapshot = $6::jsonb", args[0])
        self.assertEqual((7, "openai", None, "聊天配置", "old-model"), args[1:6])
        self.assertEqual(provider, json.loads(args[6]))

    async def test_bad_form_never_overwrites_existing_settings(self):
        for change in ({"provider": "invalid"}, {"model": ""}, {"api_url": "file:///tmp/key"}, {"api_key": 3}, {"api_key": "", "source_preset_id": True}):
            with self.subTest(change=change), patch.object(main, "save_route_settings", AsyncMock()) as save:
                response = await main.api_update_route_settings(request({**self.config, **change}))
                self.assertEqual(400, response.status_code)
                save.assert_not_awaited()
