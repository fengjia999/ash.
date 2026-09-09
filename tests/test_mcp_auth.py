import json
import unittest

import main


class McpAuthTests(unittest.TestCase):
    def test_legacy_urls_remain_supported_without_auth(self):
        configs = main._load_mcp_server_configs(
            raw_configs="",
            legacy_urls="https://one.example/mcp, https://two.example/mcp",
        )

        self.assertEqual([
            {"url": "https://one.example/mcp", "bearer_token": ""},
            {"url": "https://two.example/mcp", "bearer_token": ""},
        ], configs)

    def test_json_config_supports_independent_bearer_tokens(self):
        configs = main._load_mcp_server_configs(
            raw_configs=json.dumps([
                {
                    "url": "https://terminal.example/mcp",
                    "bearer_token": "terminal-secret",
                },
                {
                    "url": "https://search.example/mcp",
                    "bearer_token": "search-secret",
                },
            ]),
            legacy_urls="",
        )

        self.assertEqual("terminal-secret", configs[0]["bearer_token"])
        self.assertEqual("search-secret", configs[1]["bearer_token"])

    def test_invalid_or_duplicate_urls_are_rejected(self):
        with self.assertRaises(ValueError):
            main._load_mcp_server_configs(
                raw_configs='[{"url":"not-a-url"}]',
                legacy_urls="",
            )
        with self.assertRaises(ValueError):
            main._load_mcp_server_configs(
                raw_configs=(
                    '[{"url":"https://same.example/mcp"},'
                    '{"url":"https://same.example/mcp"}]'
                ),
                legacy_urls="",
            )

    def test_bearer_token_is_added_only_when_configured(self):
        authenticated = main._mcp_request_headers({
            "url": "https://terminal.example/mcp",
            "bearer_token": "secret",
        })
        anonymous = main._mcp_request_headers({
            "url": "https://public.example/mcp",
            "bearer_token": "",
        })

        self.assertEqual("Bearer secret", authenticated["Authorization"])
        self.assertNotIn("Authorization", anonymous)


if __name__ == "__main__":
    unittest.main()
