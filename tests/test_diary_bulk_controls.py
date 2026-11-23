import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DiaryBulkControlContractTests(unittest.TestCase):
    def test_diary_bulk_controls_remain_available(self):
        dashboard = (ROOT / "templates" / "dashboard.html").read_text(
            encoding="utf-8"
        )

        controls = {
            'id="long-term-select-toggle"': "toggleLongTermSelectionMode()",
            'id="long-term-select-all"': "toggleSelectAllLongTermMemories()",
            'id="long-term-generate-keywords"': "generateSelectedDiaryKeywords()",
            'id="long-term-delete-selected"': "deleteSelectedLongTermMemories()",
        }
        for element_id, handler in controls.items():
            with self.subTest(element_id=element_id):
                self.assertIn(element_id, dashboard)
                self.assertIn(handler, dashboard)

        self.assertIn('id="long-term-selection-toolbar"', dashboard)

    def test_diary_bulk_behaviors_remain_implemented(self):
        script = (ROOT / "static" / "js" / "dashboard.js").read_text(
            encoding="utf-8"
        )

        for function_name in (
            "toggleLongTermSelectionMode",
            "toggleLongTermMemorySelection",
            "toggleSelectAllLongTermMemories",
            "generateSelectedDiaryKeywords",
            "deleteSelectedLongTermMemories",
        ):
            with self.subTest(function_name=function_name):
                self.assertIn(f"function {function_name}(", script)

        for endpoint in (
            "/generate-keywords",
            "/api/diaries/batch-delete",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, script)

    def test_diary_multi_select_stays_visible_on_dark_toolbar(self):
        css = (ROOT / "static" / "css" / "phone-base.css").read_text(
            encoding="utf-8"
        )
        rule = css.rsplit(
            ".btn {",
            1,
        )[1].split("}", 1)[0]

        self.assertIn("background:var(--phone-wash);", rule)
        self.assertIn("color:var(--phone-ink);", rule)


if __name__ == "__main__":
    unittest.main()
