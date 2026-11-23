import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import main


class OpenAiProviderProfileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        setting = patch.object(main, "get_route_settings", AsyncMock(return_value={"provider":"auto", "model":""}))
        setting.start()
        self.addCleanup(setting.stop)

    def test_public_profile_never_exposes_key(self):
        public = main._openai_provider_public({
            "id": 3,
            "name": "智谱",
            "api_url": "https://example.com/v1/chat/completions",
            "api_key": "secret-key",
            "is_active": True,
        })

        self.assertNotIn("api_key", public)
        self.assertTrue(public["api_key_configured"])
        self.assertEqual("••••-key", public["api_key_hint"])

    async def test_active_profile_wins_over_environment(self):
        profile = {
            "id": 3,
            "name": "智谱",
            "api_url": "https://example.com/v1/chat/completions",
            "api_key": "profile-key",
            "is_active": True,
        }
        with patch.object(
            main,
            "get_active_openai_provider_profile",
            AsyncMock(return_value=profile),
        ):
            result = await main._load_active_openai_provider()

        self.assertEqual("preset", result["source"])
        self.assertEqual("profile-key", result["api_key"])

    async def test_missing_active_profile_falls_back_to_environment(self):
        with patch.object(
            main,
            "get_active_openai_provider_profile",
            AsyncMock(return_value=None),
        ), patch.object(
            main, "OPENAI_API_URL", "https://env.example/v1/chat/completions"
        ), patch.object(main, "OPENAI_API_KEY", "env-key"):
            result = await main._load_active_openai_provider()

        self.assertEqual("environment", result["source"])
        self.assertEqual("env-key", result["api_key"])

    def test_models_url_is_derived_from_chat_url(self):
        self.assertEqual(
            "https://example.com/v1/models",
            main._openai_models_url(
                "https://example.com/v1/chat/completions?ignored=true"
            ),
        )

    async def test_model_list_uses_active_provider(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "object": "list",
            "data": [
                {"id": "glm-5.2", "object": "model"},
                {"id": "glm-4.5", "object": "model"},
            ],
        }
        client = MagicMock()
        client.get = AsyncMock(return_value=response)
        provider = {
            "api_url": "https://example.com/v1/chat/completions",
            "api_key": "profile-key",
        }

        with patch.object(
            main, "_load_route_provider", AsyncMock(return_value="openai")
        ), patch.object(
            main, "get_active_openai_provider_profile", AsyncMock(return_value=provider)
        ), patch.object(main, "get_http_client", AsyncMock(return_value=client)):
            result = await main.list_models()

        self.assertEqual(["glm-5.2", "glm-4.5"], [
            model["id"] for model in result["data"]
        ])
        client.get.assert_awaited_once_with(
            "https://example.com/v1/models",
            headers={"Authorization": "Bearer profile-key"},
            timeout=30,
        )

    async def test_model_list_does_not_advertise_environment_default_on_failure(self):
        response = MagicMock()
        response.status_code = 502
        client = MagicMock()
        client.get = AsyncMock(return_value=response)
        provider = {
            "api_url": "https://example.com/v1/chat/completions",
            "api_key": "profile-key",
        }

        with patch.object(
            main, "_load_route_provider", AsyncMock(return_value="openai")
        ), patch.object(
            main, "get_active_openai_provider_profile", AsyncMock(return_value=provider)
        ), patch.object(
            main, "get_http_client", AsyncMock(return_value=client)
        ), patch.object(main, "DEFAULT_MODEL", "fallback-model"):
            result = await main.list_models()

        self.assertEqual([], result["data"])

    async def test_model_list_uses_environment_provider_when_no_profile_is_active(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "data": [{"id": "openai/gpt-5", "object": "model"}],
        }
        client = MagicMock()
        client.get = AsyncMock(return_value=response)
        with patch.object(
            main, "_load_route_provider", AsyncMock(return_value="openai")
        ), patch.object(
            main, "get_active_openai_provider_profile", AsyncMock(return_value=None)
        ), patch.object(
            main, "get_http_client", AsyncMock(return_value=client)
        ), patch.object(
            main, "OPENAI_API_URL", "https://openrouter.ai/api/v1"
        ), patch.object(main, "OPENAI_API_KEY", "environment-key"
        ):
            result = await main.list_models()

        self.assertEqual(["openai/gpt-5"], [item["id"] for item in result["data"]])
        client.get.assert_awaited_once_with(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": "Bearer environment-key"},
            timeout=30,
        )

    async def test_openrouter_base_url_is_expanded_for_chat_requests(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "ok"},
            }],
            "usage": {},
        }
        client = MagicMock()
        client.post = AsyncMock(return_value=response)

        with patch.object(
            main, "get_http_client", AsyncMock(return_value=client)
        ), patch.object(main, "_record_token_usage", AsyncMock()):
            result = await main.handle_openai_tool_loop(
                {"Authorization": "Bearer key"},
                {"model": "openai/gpt-5", "messages": []},
                api_url="https://openrouter.ai/api/v1",
            )

        self.assertEqual("ok", result["choices"][0]["message"]["content"])
        self.assertEqual(
            "https://openrouter.ai/api/v1/chat/completions",
            client.post.await_args.args[0],
        )

    async def test_model_list_uses_anthropic_when_route_is_anthropic(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "data": [{"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"}],
        }
        client = MagicMock()
        client.get = AsyncMock(return_value=response)

        with patch.object(
            main, "_load_route_provider", AsyncMock(return_value="anthropic")
        ), patch.object(
            main,
            "get_anthropic_credentials",
            AsyncMock(return_value={"api_key": "dashboard-key"}),
        ), patch.object(
            main, "get_http_client", AsyncMock(return_value=client)
        ), patch.object(
            main, "ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages"
        ):
            result = await main.list_models()

        self.assertEqual(["claude-sonnet-4-6"], [item["id"] for item in result["data"]])
        self.assertEqual("anthropic", result["data"][0]["owned_by"])
        client.get.assert_awaited_once_with(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": "dashboard-key",
                "anthropic-version": main.ANTHROPIC_VERSION,
            },
            timeout=30,
        )

    async def test_auto_route_combines_current_suppliers(self):
        with patch.object(
            main, "_load_route_provider", AsyncMock(return_value="auto")
        ), patch.object(
            main,
            "_load_openai_provider_models",
            AsyncMock(return_value={
                "object": "list",
                "data": [{"id": "shared"}, {"id": "gpt-test"}],
            }),
        ), patch.object(
            main,
            "_load_anthropic_provider_models",
            AsyncMock(return_value={
                "object": "list",
                "data": [{"id": "shared"}, {"id": "claude-test"}],
            }),
        ):
            result = await main.list_models()

        self.assertEqual(
            ["shared", "gpt-test", "claude-test"],
            [item["id"] for item in result["data"]],
        )

    async def test_create_profile_can_mark_it_active(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "name": "智谱",
            "api_url": "https://example.com/v1/chat/completions",
            "api_key": "new-key",
            "is_active": True,
        })
        save = AsyncMock(return_value={
            "id": 4,
            "name": "智谱",
            "api_url": "https://example.com/v1/chat/completions",
            "api_key": "new-key",
            "is_active": True,
        })

        with patch.object(main, "save_openai_provider_profile", save):
            result = await main.api_create_openai_provider(request)

        self.assertEqual("ok", result["status"])
        save.assert_awaited_once_with(
            "智谱",
            "https://example.com/v1/chat/completions",
            "new-key",
            True,
        )
        self.assertNotIn("api_key", result["profile"])

    async def test_edit_with_blank_key_preserves_stored_key(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "name": "智谱官方",
            "api_url": "https://example.com/v1/chat/completions",
            "api_key": "",
            "is_active": True,
        })
        update = AsyncMock(return_value={
            "id": 4,
            "name": "智谱官方",
            "api_url": "https://example.com/v1/chat/completions",
            "api_key": "stored-key",
            "is_active": True,
        })

        with patch.object(main, "update_openai_provider_profile", update):
            result = await main.api_update_openai_provider(4, request)

        self.assertEqual("ok", result["status"])
        update.assert_awaited_once_with(
            4,
            "智谱官方",
            "https://example.com/v1/chat/completions",
            None,
            True,
        )

    async def test_tool_loop_uses_selected_profile_url(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "ok"},
            }],
            "usage": {},
        }
        client = MagicMock()
        client.post = AsyncMock(return_value=response)

        with patch.object(
            main, "get_http_client", AsyncMock(return_value=client)
        ), patch.object(main, "_record_token_usage", AsyncMock()):
            result = await main.handle_openai_tool_loop(
                {"Authorization": "Bearer key"},
                {"model": "test", "messages": [{"role": "user", "content": "hi"}]},
                api_url="https://selected.example/v1/chat/completions",
            )

        self.assertEqual("ok", result["choices"][0]["message"]["content"])
        self.assertEqual(
            "https://selected.example/v1/chat/completions",
            client.post.await_args.args[0],
        )

    def test_dashboard_keeps_profiles_collapsed_to_names(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
        script = (root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

        self.assertIn("OpenAI 供应商", dashboard)
        self.assertIn('id="openai-provider-list"', dashboard)
        self.assertIn('<details class="openai-provider-item', script)
        self.assertIn("provider-summary-name", script)
        self.assertIn("provider-active-mark", script)


if __name__ == "__main__":
    unittest.main()
