import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node.js is required for browser logic tests")
class DashboardSavingTests(unittest.TestCase):
    def test_save_does_not_wait_for_reload_and_stale_reads_cannot_undo_it(self):
        self.run_browser_test(r"""
    standingEditingId = 7;
    standingBlocks = [{id: 7, status: 'active', layer: 'core', title: 'title', content: 'old'}];
    elements['memory-editor-content'] = {value: 'new'};
    elements['memory-editor-save'] = {disabled: false};
    let resolveOld;
    const paths = [];
    fetch = async (url, options) => {
        paths.push(url);
        if (options.method === 'PUT') return new Response(JSON.stringify({
            block: {...standingBlocks[0], content: 'new'}
        }));
        return new Promise(resolve => { resolveOld = resolve; });
    };
    let closed = false;
    closeStandingMemoryEditor = () => { closed = true; };
    const card = {outerHTML: ''};
    document.querySelector = () => card;
    renderStandingLists = () => { throw new Error('editing must not rebuild the whole list'); };
    renderStandingStats = () => {};
    showStandingMsg = () => {};
    const oldRead = loadStandingMemory();
    await saveStandingMemory();
    assert.equal(paths.length, 2, 'saving must not request a full list refresh');
    assert.equal(closed, true);
    assert.match(card.outerHTML, /new/);
    assert.equal(elements['memory-editor-save'].disabled, false);
    resolveOld(new Response(JSON.stringify({blocks: [{id: 7, content: 'old'}]})));
    await oldRead;
    assert.equal(standingBlocks[0].content, 'new');
    assert.equal(timers.size, 0);
""")

    def test_save_errors_are_visible_inside_the_open_editor(self):
        self.run_browser_test(r"""
    elements['memory-editor-modal'] = {classList: {contains: () => true}};
    elements['memory-editor-msg'] = {innerHTML: ''};
    elements['standing-msg'] = {innerHTML: ''};
    showStandingMsg('error', '保存结果尚未确认');
    assert.match(elements['memory-editor-msg'].innerHTML, /保存结果尚未确认/);
    assert.equal(elements['standing-msg'].innerHTML, '');
    elements['long-term-memory-editor-modal'] = {classList: {contains: () => true}};
    elements['long-term-memory-editor-msg'] = {innerHTML: ''};
    elements['long-term-msg'] = {innerHTML: ''};
    showLongTermMsg('error', 'network error');
    assert.match(elements['long-term-memory-editor-msg'].innerHTML, /network error/);
    assert.equal(elements['long-term-msg'].innerHTML, '');
""")

    def test_stalled_response_body_times_out_without_losing_draft(self):
        self.run_browser_test(r"""
    standingEditingId = 7;
    standingBlocks = [{id: 7, title: 'title', content: 'old'}];
    elements['memory-editor-content'] = {value: 'unsaved draft'};
    elements['memory-editor-save'] = {disabled: false};
    let message = '';
    showStandingMsg = (_, text) => { message = text; };
    closeStandingMemoryEditor = () => { throw new Error('editor must stay open'); };
    let bodyStarted;
    const readingBody = new Promise(resolve => { bodyStarted = resolve; });
    fetch = async (_, options) => ({
        status: 200, ok: true,
        text: () => new Promise((resolve, reject) => {
            options.signal.addEventListener('abort', () => reject(new Error('aborted')));
            bodyStarted();
        }),
    });
    const save = saveStandingMemory();
    await readingBody;
    assert.equal(elements['memory-editor-save'].disabled, true);
    assert.equal(timers.size, 1);
    [...timers.values()][0]();
    await save;
    assert.match(message, /保存结果尚未确认/);
    assert.equal(elements['memory-editor-content'].value, 'unsaved draft');
    assert.equal(elements['memory-editor-save'].disabled, false);
    assert.equal(standingBlocks[0].content, 'old');
    assert.equal(timers.size, 0);
""")

    def run_browser_test(self, test):
        source = (Path(__file__).resolve().parents[1] / "static/js/dashboard.js").read_text()
        harness = r"""
const assert = require('node:assert/strict');
const elements = {};
const timers = new Map();
let nextTimer = 0;
const setTimeout = callback => { timers.set(++nextTimer, callback); return nextTimer; };
const clearTimeout = id => timers.delete(id);
const document = {
    addEventListener: () => {},
    getElementById: id => elements[id] || null,
    querySelector: () => null,
};
const window = {addEventListener: () => {}, location: {assign: () => {}}};
"""
        result = subprocess.run(
            ["node", "-e", harness + source + "\n(async () => {\n" + test
             + "\n})().catch(error => { console.error(error); process.exitCode = 1; });"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
