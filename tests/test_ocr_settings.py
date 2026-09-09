import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import main


class OcrSettingsTests(unittest.IsolatedAsyncioTestCase):
    def test_public_settings_do_not_expose_api_key(self):
        public = main._public_ocr_settings({
            "enabled": True,
            "api_url": "https://ocr.example/v1/chat/completions",
            "model": "ocr-model",
            "api_key": "secret-value",
        })

        self.assertNotIn("api_key", public)
        self.assertTrue(public["api_key_configured"])
        self.assertTrue(public["api_key_hint"].endswith("alue"))

    async def test_blank_key_keeps_existing_key(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "enabled": True,
            "api_url": "https://ocr.example/v1/chat/completions",
            "model": "ocr-model",
            "api_key": "",
            "clear_api_key": False,
        })
        save = AsyncMock(return_value={
            "enabled": True,
            "api_url": "https://ocr.example/v1/chat/completions",
            "model": "ocr-model",
            "api_key": "existing-key",
        })

        with patch.object(
            main, "get_ocr_settings", AsyncMock(return_value={"api_key": "existing-key"})
        ), patch.object(main, "save_ocr_settings", save):
            result = await main.api_update_ocr_settings(request)

        self.assertEqual("ok", result["status"])
        self.assertIsNone(save.await_args.kwargs["api_key"])

    async def test_enabled_ocr_requires_complete_configuration(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "enabled": True,
            "api_url": "",
            "model": "",
            "api_key": "",
        })

        with patch.object(main, "get_ocr_settings", AsyncMock(return_value={"api_key": ""})):
            response = await main.api_update_ocr_settings(request)

        self.assertEqual(400, response.status_code)

    async def test_new_key_wins_over_clear_flag(self):
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "enabled": True,
            "api_url": "https://ocr.example/v1/chat/completions",
            "model": "ocr-model",
            "api_key": "replacement-key",
            "clear_api_key": True,
        })
        save = AsyncMock(return_value={
            "enabled": True,
            "api_url": "https://ocr.example/v1/chat/completions",
            "model": "ocr-model",
            "api_key": "replacement-key",
        })

        with patch.object(
            main, "get_ocr_settings", AsyncMock(return_value={"api_key": "existing-key"})
        ), patch.object(main, "save_ocr_settings", save):
            await main.api_update_ocr_settings(request)

        self.assertEqual("replacement-key", save.await_args.kwargs["api_key"])

    async def test_disabled_ocr_keeps_original_image_blocks(self):
        blocks = [{
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "abc"},
        }]

        with patch.object(
            main, "get_ocr_settings", AsyncMock(return_value={"enabled": False})
        ), patch.object(main, "_recognize_image_blocks", AsyncMock()) as recognize:
            processed, result = await main.preprocess_user_blocks_with_ocr(blocks)

        self.assertEqual(blocks, processed)
        self.assertIsNone(result)
        recognize.assert_not_awaited()

    async def test_enabled_ocr_replaces_images_with_derived_text(self):
        blocks = [
            {"type": "text", "text": "看看这个"},
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": "abc"},
            },
        ]
        settings = {
            "enabled": True,
            "api_url": "https://ocr.example/v1/chat/completions",
            "model": "ocr-model",
            "api_key": "key",
        }
        with patch.object(
            main, "get_ocr_settings", AsyncMock(return_value=settings)
        ), patch.object(
            main, "_recognize_image_blocks", AsyncMock(return_value="识别结果")
        ):
            processed, result = await main.preprocess_user_blocks_with_ocr(blocks)

        self.assertEqual("识别结果", result)
        self.assertEqual("看看这个", processed[0]["text"])
        self.assertIn("识别结果", processed[1]["text"])
        self.assertFalse(any(block.get("type") == "image" for block in processed))


if __name__ == "__main__":
    unittest.main()
