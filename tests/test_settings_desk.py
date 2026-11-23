import shutil
import subprocess
import unittest
from pathlib import Path
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]


class SettingsDeskTests(unittest.TestCase):
    def test_forms_are_preserved_without_duplicate_ids(self):
        class Ids(HTMLParser):
            def __init__(self):
                super().__init__()
                self.ids = []
            def handle_starttag(self, tag, attrs):
                self.ids.extend(value for key, value in attrs if key == 'id')
        html = (ROOT / 'templates/dashboard.html').read_text()
        parser = Ids()
        parser.feed(html)
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        for item in ('routeProvider', 'anthropic-provider-list', 'openai-provider-list',
                     'crossConversationRecallEnabled', 'ocrModel', 'diaryMergeModel'):
            self.assertIn(item, parser.ids)
        self.assertNotIn('project-about-panel', html)
        for page in ('suppliers', 'supplier-route', 'supplier-openai', 'supplier-anthropic', 'recall', 'settings'):
            self.assertIn('section-' + page, parser.ids)
        self.assertNotIn('class="settings-paper-ball"', html)
        self.assertNotIn('class="settings-popup"', html)
        self.assertNotIn('settings-microwave', html)

    @unittest.skipUnless(shutil.which('node'), 'Node.js required')
    def test_activation_keeps_keys_and_rolls_back_failure(self):
        harness = r"""
const assert = require('node:assert/strict');
const document = {addEventListener: () => {}};
const controls = [{disabled:false}];
const byId = () => ({querySelectorAll: () => controls});
const anthropicProviderProfiles = [{id:1,name:'original',api_url:'https://example.test',is_active:false}];
const openAiProviderProfiles = [];
let message='',reloads=0,calls=[];
const showAnthropicProviderMsg = text => {message=text;};
const showOpenAiProviderMsg = showAnthropicProviderMsg;
const loadAnthropicProviders = async () => {reloads++;};
const loadOpenAiProviders = loadAnthropicProviders;
let saveDashboardJson = async (url, options) => {calls.push({url,...options});};
"""
        assertions = r"""
(async()=>{
await setSettingsProviderActive('anthropic',1,true);
assert.equal(calls[0].url,'/api/anthropic-providers/1/activate');
assert.equal(calls[0].method,'POST');
assert.equal(calls[0].body,undefined);
assert.equal(reloads,1);
await setSettingsProviderActive('anthropic',1,false);
assert.deepEqual(JSON.parse(calls[1].body),{name:'original',api_url:'https://example.test',is_active:false});
saveDashboardJson = async () => {throw new Error('offline');};
await setSettingsProviderActive('anthropic',1,true);
assert.equal(anthropicProviderProfiles[0].is_active,false);
assert.equal(controls[0].disabled,false);
assert.match(message,/保存失败/);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        result = subprocess.run(['node','-'], input=harness + (ROOT / 'static/js/settings-desk.js').read_text() + assertions,
                                text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout + result.stderr)
