import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node.js is required for browser logic tests")
class DashboardNavigationTests(unittest.TestCase):
    def test_returning_to_memory_only_loads_the_visible_subview(self):
        script = (
            Path(__file__).resolve().parents[1] / "static/js/dashboard.js"
        ).read_text()
        navigation = "function switchSection(" + script.split(
            "function switchSection(", 1
        )[1].split("function switchTo(", 1)[0]
        result = subprocess.run(
            ["node", "-e", r"""
const assert = require('node:assert/strict');
const window = {};
let view = 'directory';
const calls = [];
const document = {
    querySelectorAll: () => [],
    querySelector: () => ({dataset: {standingView: view}}),
};
const closeConversationDetail = () => {};
const loadStandingMemory = () => calls.push('directory');
const loadLongTermMemory = () => calls.push('diaries');
const loadIdentityPresets = () => calls.push('identity');
const byId = () => ({getAttribute: () => null, set src(value) {calls.push('prompt');}});
""" + navigation + r"""
switchSection('standing');
assert.deepEqual(calls, ['directory']);
calls.length = 0;
view = 'long-term';
switchSection('standing');
assert.deepEqual(calls, ['directory', 'diaries']);
calls.length = 0;
view = 'fragments';
switchSection('standing');
assert.deepEqual(calls, ['directory']);
calls.length = 0;
switchSection('prompts');
assert.deepEqual(calls, ['identity', 'prompt']);
"""],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
