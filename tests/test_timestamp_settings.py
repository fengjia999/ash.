import unittest
from pathlib import Path

import main


class TimestampFeatureRemovalTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    def test_timestamp_prompt_injection_is_removed(self):
        main_source = (self.root / "main.py").read_text(encoding="utf-8")

        self.assertNotIn("_build_timestamp_block", main_source)
        self.assertNotIn("conversation_resume", main_source)
        self.assertNotIn("_last_user_message_time", main_source)

    def test_timestamp_settings_are_removed_from_backend(self):
        main_source = (self.root / "main.py").read_text(encoding="utf-8")
        db_source = (self.root / "database.py").read_text(encoding="utf-8")

        self.assertNotIn("timestamp_mode", main_source)
        self.assertNotIn("timestamp_interval_minutes", main_source)
        self.assertNotIn("timestamp_mode", db_source)
        self.assertNotIn("timestamp_interval_minutes", db_source)

    def test_timestamp_controls_are_removed_from_dashboard(self):
        dashboard = (self.root / "templates" / "dashboard.html").read_text(
            encoding="utf-8"
        )
        script = (self.root / "static" / "js" / "dashboard.js").read_text(
            encoding="utf-8"
        )
        stylesheet = (self.root / "static" / "css" / "dashboard.css").read_text(
            encoding="utf-8"
        )

        self.assertNotIn('id="timestampMode"', dashboard)
        self.assertNotIn('id="timestampInterval"', dashboard)
        self.assertNotIn('byId("timestampMode")', script)
        self.assertNotIn('byId("timestampInterval")', script)
        self.assertNotIn("conversation-timestamp", stylesheet)

    def test_public_settings_ignore_legacy_timestamp_columns(self):
        result = main._public_conversation_model_settings({
            "timestamp_mode": "always",
            "timestamp_interval_minutes": 1,
        })

        self.assertNotIn("timestamp_mode", result)
        self.assertNotIn("timestamp_interval_minutes", result)


if __name__ == "__main__":
    unittest.main()
