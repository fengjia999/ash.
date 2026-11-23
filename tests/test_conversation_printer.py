import shutil
import re
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node.js is required")
class ConversationPrinterTests(unittest.TestCase):
    def test_tap_previews_double_tap_opens_and_controls_do_not_open(self):
        template = (Path(__file__).resolve().parents[1] / "templates/context.html").read_text()
        handler = "function handleConversationTap(" + template.split(
            "function handleConversationTap(", 1
        )[1].split("function openConvMenu(", 1)[0]
        controls = "function togglePrintedHistory(" + template.split(
            "function togglePrintedHistory(", 1
        )[1].split("function updateConversationPrinter(", 1)[0]
        script = r"""
const assert = require('node:assert/strict');
let armedConversationId = null, armedConversationAt = 0;
const CONVERSATION_DOUBLE_TAP_MS = 500;
let printedHistoryExpanded = false, activePrinterConversationId = null, menuTargetConvId = null;
let now = 1000;
Date.now = () => now;
const opened = [], actions = [];
const selectConv = id => opened.push(id);
const hideConvMenu = () => {};
const menuAction = action => actions.push([menuTargetConvId, action]);
const makeElement = id => ({id, hidden: true, classes: new Set(), attrs: {},
    classList: {add(c) {this.owner.classes.add(c);}, remove(c) {this.owner.classes.delete(c);},
        toggle(c, value) {value ? this.owner.classes.add(c) : this.owner.classes.delete(c);}},
    setAttribute(k,v) {this.attrs[k]=v;}});
const elements = Object.fromEntries(['convList','sidebar','printerPower','printerHint','letter'].map(id=>[id,makeElement(id)]));
for (const e of Object.values(elements)) e.classList.owner = e;
const document = {getElementById: id => elements[id], querySelectorAll: () => [elements.letter]};
const conversationDirectory = new Map([[1,{name:'first',message_count:5,started_at:'2026-10-02'}]]);
const conversationListGeneration = 1;
const renderConversationList = () => {};
const shortDateTime = s => s;
const conversationDate = (c,key) => c[key];
const tap = {target:{closest:()=>null}};
""" + handler + controls + r"""
handleConversationTap(tap, 1, elements.letter);
assert.deepEqual(opened, []);
assert.ok(elements.letter.classes.has('previewing'));
now += 100;
handleConversationTap(tap, 1, elements.letter);
assert.deepEqual(opened, [1]);
now += 1000;
handleConversationTap(tap, 1, elements.letter);
now += 700;
handleConversationTap(tap, 1, elements.letter);
assert.deepEqual(opened, [1], 'slow taps must only preview');
now += 100;
handleConversationTap(tap, 2, elements.letter);
assert.deepEqual(opened, [1], 'different letters must not form a double tap');
handleConversationTap({target:{closest:()=>({})}}, 2, elements.letter);
assert.deepEqual(opened, [1], 'editing button must not open conversation');
togglePrintedHistory();
assert.equal(elements.convList.hidden, false);
assert.equal(elements.printerPower.attrs['aria-expanded'], 'true');
assert.equal(armedConversationId, null);
togglePrintedHistory();
assert.equal(elements.convList.hidden, true);
assert.equal(elements.printerPower.attrs['aria-expanded'], 'false');
assert.deepEqual(opened, [1], 'power control must not select or activate');
editActiveConversation();
assert.deepEqual(actions, []);
activePrinterConversationId = 1;
editActiveConversation();
assert.deepEqual(actions, [[1, 'rename']]);
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_template_starts_collapsed_and_styles_are_versioned(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates/context.html").read_text()
        self.assertIn('class="conv-list" id="convList" hidden', template)
        self.assertIn('aria-controls="convList"', template)
        self.assertIn('/static/css/conversation-paper.css?v={{ chat_version }}', template)
        self.assertIn('/static/fonts/wenkai.css?v={{ static_version }}', template)
        css = (root / 'static/css/conversation-paper.css').read_text()
        self.assertIn("'Ash WenKai'", css)
        self.assertIn("div.onkeydown = event =>", template)
        self.assertIn("div.setAttribute('aria-describedby', infoId)", template)

    def test_chinese_handwriting_assets_are_local_and_cover_titles(self):
        root = Path(__file__).resolve().parents[1]
        manifest = (root / 'static/fonts/wenkai.css').read_text()
        self.assertNotIn('https://', manifest)
        blocks = re.findall(r'@font-face\s*\{([^}]+)\}', manifest)
        self.assertEqual(len(blocks), 115)
        supported = set()
        for block in blocks:
            url = re.search(r"url\('(/static/fonts/wenkai/[^']+)'\)", block).group(1)
            asset = root / url.lstrip('/')
            self.assertEqual(asset.read_bytes()[:4], b'wOF2')
            self.assertLess(asset.stat().st_size, 150_000)
            ranges = re.search(r'unicode-range:\s*([^;]+)', block).group(1)
            for value in ranges.split(','):
                bounds = value.strip().removeprefix('U+').split('-')
                start = int(bounds[0], 16)
                end = int(bounds[-1], 16)
                supported.update(range(start, end + 1))
        self.assertTrue(set(map(ord, '窗边的晚风今天值得记住会话标题繁體中文')) <= supported)
        license_text = (root / 'static/fonts/OFL-WenKai.txt').read_text()
        self.assertIn('SIL OPEN FONT LICENSE Version 1.1', license_text)
        self.assertIn('Copyright', license_text)


if __name__ == "__main__":
    unittest.main()
