import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node.js is required for browser logic tests")
class ConversationSwitchRaceTests(unittest.TestCase):
    def test_switches_are_ordered_and_frame_reload_does_not_activate(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (root / "static/js/dashboard.js").read_text()
        context = (root / "templates/context.html").read_text()
        activation = dashboard.split("function requestConversationActivation(", 1)[1]
        activation = "function requestConversationActivation(" + activation.split(
            "function openConversationDetail(", 1
        )[0]
        startup = context.split("// ── 启动 ──", 1)[1].split(
            "window.addEventListener", 1
        )[0]
        script = r"""
const assert = require('node:assert/strict');
let conversationActivationQueue = Promise.resolve();
let conversationActivationGeneration = 0;
const frame = {dataset: {}};
const byId = () => frame;
const requests = [];
const errors = [];
const alert = message => errors.push(message);
const authFetch = url => new Promise(resolve => requests.push({url, resolve}));
const flush = () => new Promise(resolve => setImmediate(resolve));
const ok = {ok: true, json: async () => ({})};
""" + activation + r"""
(async () => {
    requestConversationActivation(1);
    await flush();
    requestConversationActivation(2);
    requestConversationActivation(3);
    await flush();
    assert.deepEqual(requests.map(r => r.url), ['/api/conversations/1/activate']);
    requests[0].resolve(ok);
    await flush();
    assert.deepEqual(requests.map(r => r.url), [
        '/api/conversations/1/activate', '/api/conversations/3/activate'
    ]);
    requests[1].resolve(ok);
    await conversationActivationQueue;
    assert.equal(frame.dataset.conversationId, '3');
    assert.equal(new URLSearchParams(frame.dataset.contextSrc.split('?')[1]).get('conversation_id'), '3');

    requestConversationActivation(4);
    await flush();
    requests[2].resolve({ok: false, json: async () => ({error: 'failed'})});
    await conversationActivationQueue;
    assert.equal(errors.length, 1);
    requestConversationActivation(5);
    await flush();
    assert.equal(requests[3].url, '/api/conversations/5/activate');
    requests[3].resolve(ok);
    await conversationActivationQueue;

    const CONTEXT_EMBED_MODE = 'detail';
    const INITIAL_CONVERSATION_ID = 3;
    const SHOW_CREATED_MODAL = false;
    const window = {parent: {requestConversationActivation}};
    const setRole = () => {};
    const selectConv = (id, activate) => {
        assert.equal(id, 3);
        assert.equal(activate, false, 'iframe reload must not reactivate its conversation');
        return Promise.resolve(true);
    };
""" + startup + r"""
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
