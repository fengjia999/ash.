import unittest
from pathlib import Path


class LegacyFragmentLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.dashboard = (root / "templates" / "dashboard.html").read_text(
            encoding="utf-8"
        )
        cls.script = (root / "static" / "js" / "dashboard.js").read_text(
            encoding="utf-8"
        )

    def test_fragment_entry_and_section_start_hidden(self):
        self.assertIn('data-section="manage" hidden', self.dashboard)
        self.assertIn('id="section-manage" class="section" hidden', self.dashboard)
        self.assertIn('class="fragment-ledger"', self.dashboard)

    def test_fragment_ledger_has_no_management_controls(self):
        section = self.dashboard.split('id="section-manage"', 1)[1].split(
            "</section>", 1
        )[0]
        for legacy_control in (
            "searchBox",
            "dateFilter",
            "sortSelect",
            "selectAll",
            "batchSave",
            "batchDelete",
        ):
            self.assertNotIn(legacy_control, section)

        ledger_source = self.script.split("// 旧记忆碎片录（只读）", 1)[1].split(
            "function showMsg", 1
        )[0]
        self.assertNotIn('method: "PUT"', ledger_source)
        self.assertNotIn('method: "DELETE"', ledger_source)
        self.assertIn("fragment-month", ledger_source)
        self.assertIn("fragment-entry-paper", ledger_source)

    def test_empty_imported_fragment_set_hides_entry(self):
        self.assertIn("setFragmentLedgerVisibility(allMemories.length > 0)", self.script)
        self.assertIn("nav.hidden = !hasFragments", self.script)
        self.assertGreaterEqual(self.script.count("await loadMemories()"), 2)


if __name__ == "__main__":
    unittest.main()
