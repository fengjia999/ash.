import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class PromptSaveFeedbackTests(unittest.TestCase):
    def test_saved_status_local_content_failure_and_duplicate_clicks(self):
        html = (Path(__file__).resolve().parents[1] / 'templates/prompt.html').read_text()
        function = html.split('async function saveEdit(key) {', 1)[1].split('// === 预览 ===', 1)[0]
        harness = r"""
const assert=require('node:assert/strict');
const API_BASE='';
const promptSectionsByKey=new Map([['core',{content:'Old prompt'}]]);
const status={textContent:'',dataset:{}};
const textarea={value:'New prompt',disabled:false};
const reason={value:'Manual correction',disabled:false};
const saveButton={textContent:'Save',disabled:false};
const cancelButton={disabled:false};
const content={textContent:'Old prompt'},meta={textContent:'10 chars'};
const card={querySelector:s=>({'.section-content':content,'.section-meta':meta,'.btn-edit':{focus:()=>{}}}[s])};
const controls=[textarea,reason,saveButton,cancelButton];
const area={dataset:{},querySelectorAll:()=>controls,querySelector:()=>saveButton,closest:()=>card};
const nodes={'textarea-core':textarea,'reason-core':reason,'edit-core':area,'save-status-core':status};
const document={getElementById:id=>nodes[id]};
let closes=0,calls=0,finish;
const closeEdit=()=>{closes++;};
const setTimeout=()=>1,clearTimeout=()=>{};
let authFetch=async(url,options)=>{
 calls++; assert.equal(url,'/api/prompt/core');
 assert.deepEqual(JSON.parse(options.body),{content:'New prompt',reason:'Manual correction',edited_by:'manual'});
 return new Promise(resolve=>{finish=resolve;});
};
"""
        assertions = r"""
(async()=>{
const pending=saveEdit('core');
assert.equal(status.dataset.state,'saving');
assert.ok(controls.every(c=>c.disabled));
await saveEdit('core');assert.equal(calls,1);
finish({ok:true,json:async()=>({ok:true,chars:10})});await pending;
assert.equal(status.dataset.state,'saved');assert.match(status.textContent,/已保存/);
assert.equal(content.textContent,'New prompt');assert.equal(closes,1);
assert.equal(promptSectionsByKey.get('core').content,'New prompt');
assert.ok(controls.every(c=>!c.disabled));
textarea.value='Another unsaved draft';
authFetch=async()=>({ok:false,status:500,json:async()=>({})});
await saveEdit('core');
assert.equal(status.dataset.state,'error');assert.match(status.textContent,/500/);
assert.equal(textarea.value,'Another unsaved draft');assert.equal(content.textContent,'New prompt');
assert.equal(closes,1);assert.ok(controls.every(c=>!c.disabled));
authFetch=async()=>{throw Object.assign(new Error(),{name:'AbortError'});};
await saveEdit('core');assert.match(status.textContent,/请求超时/);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        result = subprocess.run(['node', '-'], input=harness + 'async function saveEdit(key) {' + function + assertions,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
