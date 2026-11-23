import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import main


class IdentityPresetApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_returns_names_and_configured_state(self):
        with patch.object(main, "get_identity_presets", AsyncMock(return_value={
            "user_name": "用户示例",
            "assistant_name": "助手示例",
        })):
            result = await main.api_get_identity_presets()

        self.assertEqual("用户示例", result["user_name"])
        self.assertEqual("助手示例", result["assistant_name"])
        self.assertTrue(result["configured"])

    async def test_save_normalizes_and_persists_both_names(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "user_name": "  用户示例  ",
            "assistant_name": " 助手示例 ",
        })
        save = AsyncMock(return_value={
            "user_name": "用户示例",
            "assistant_name": "助手示例",
        })
        with patch.object(main, "save_identity_presets", save):
            result = await main.api_update_identity_presets(request)

        save.assert_awaited_once_with("用户示例", "助手示例")
        self.assertEqual("ok", result["status"])
        self.assertTrue(result["configured"])

    async def test_save_rejects_only_one_name(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "user_name": "用户示例",
            "assistant_name": "",
        })
        save = AsyncMock()
        with patch.object(main, "save_identity_presets", save):
            response = await main.api_update_identity_presets(request)

        self.assertEqual(400, response.status_code)
        self.assertIn("同时填写两个名字", json.loads(response.body)["error"])
        save.assert_not_awaited()


class IdentityPresetPageTests(unittest.TestCase):
    def test_dashboard_has_lazy_identity_preset_page(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "templates" / "dashboard.html").read_text(
            encoding="utf-8"
        )
        script = (root / "static" / "js" / "dashboard.js").read_text(
            encoding="utf-8"
        )

        phone_shell = (root / "templates" / "phone-shell.html").read_text(encoding="utf-8")
        self.assertIn('data-phone-app="presets"', phone_shell)
        self.assertIn('id="section-presets"', dashboard)
        self.assertIn('id="identityUserName"', dashboard)
        self.assertIn('id="identityAssistantName"', dashboard)
        self.assertIn('if (name === "presets")', script)
        self.assertIn('authFetch("/api/identity-presets")', script)
        self.assertIn('saveDashboardJson("/api/identity-presets"', script)

    def test_prompt_editor_is_part_of_the_identity_page(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "templates/dashboard.html").read_text()
        preset_page = dashboard.split('id="section-presets"', 1)[1].split('</section>', 1)[0]
        self.assertIn('id="prompt-console-frame"', preset_page)
        self.assertIn('id="identity-avatar-user"', preset_page)
        self.assertIn('id="identity-avatar-assistant"', preset_page)
        self.assertIn('id="identity-avatar-user-file"', preset_page)
        self.assertNotIn('identity-explanation', preset_page)
        self.assertNotIn('data-section="prompts"', dashboard)
        self.assertNotIn('id="section-prompts"', dashboard)
        prompt = (root / "templates/prompt.html").read_text()
        for label in ('提示词段落', '完整预览', '修改日志'):
            self.assertIn('aria-label="' + label + '"', prompt)
        self.assertIn('memory-gateway-prompt-height', prompt)
        self.assertIn('prompt-paper.css', prompt)


if __name__ == "__main__":
    unittest.main()
