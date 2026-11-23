import re
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node.js is required')
class ContextOperationTests(unittest.TestCase):
    def run_script(self, test):
        source = (Path(__file__).resolve().parents[1] / 'templates/context.html').read_text()
        source = source.split('<script>\nconst CSRF_TOKEN', 1)[1].split('// ── 启动 ──', 1)[0]
        source = 'const CSRF_TOKEN' + re.sub(r'{{.*?}}', 'null', source)
        prompts = (Path(__file__).resolve().parents[1] / 'static/js/conversation-prompts.js').read_text()
        prompts = prompts.split('// Prompt state\n', 1)[1].split('// Public editor actions', 1)[0]
        prompts = prompts.replace('let promptConversationId = null;\n', '').replace('promptConversationId', 'currentConvId')
        source += '\n' + prompts
        harness = r"""
const assert = require('node:assert/strict');
const elements = new Map();
const document = {
  addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
  getElementById(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {textContent: '', disabled: false, dataset:{}, addEventListener() {},
        classList: {add(c) {classes.add(c);}, remove(c) {classes.delete(c);}, contains(c) {return classes.has(c);}}});
    }
    return elements.get(id);
  }
};
const window = {location: {origin: 'http://test'}, parent: {postMessage() {}}};
"""
        result = subprocess.run(['node', '-'], input=harness + source + '\n(async()=>{\n' + test
                                + '\n})().catch(e=>{console.error(e);process.exitCode=1;});',
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_failed_confirmation_stays_open_and_deduplicates_submission(self):
        self.run_script(r"""
let finish, calls = 0;
showConfirm('删除', '确定删除？', () => {calls++; return new Promise((_, reject) => {finish = reject;});});
const btn = document.getElementById('confirmBtn');
const first = btn.onclick();
await btn.onclick();
hideModal('confirmModal');
assert.equal(calls, 1);
assert.equal(btn.disabled, true);
assert.equal(document.getElementById('confirmModal').classList.contains('show'), true);
finish(new Error('database busy'));
await first;
assert.equal(btn.disabled, false);
assert.equal(document.getElementById('confirmModal').classList.contains('show'), true);
assert.ok(document.getElementById('confirmText').textContent.includes('database busy'));
showConfirm('重试', '确定？', async () => {});
await btn.onclick();
assert.equal(document.getElementById('confirmModal').classList.contains('show'), false);
""")

    def test_delete_captures_target_and_does_not_wait_for_list_refresh(self):
        self.run_script(r"""
const requests = [];
fetch = async url => {requests.push(url); return new Response(JSON.stringify({status: 'ok'}));};
loadConversations = () => new Promise(() => {});
menuTargetConvId = 17;
menuAction('delete');
menuTargetConvId = 18;
await document.getElementById('confirmBtn').onclick();
assert.deepEqual(requests, ['/api/conversations/17']);
assert.equal(document.getElementById('confirmModal').classList.contains('show'), false);
""")

    def test_non_successful_response_is_not_reported_as_success(self):
        self.run_script(r"""
fetch = async () => new Response(JSON.stringify({error: 'permission denied'}), {status: 403});
await assert.rejects(apiJson('/api/conversations/1', {method: 'DELETE'}), /permission denied/);
fetch = async () => new Response(JSON.stringify({error: 'conflict'}));
await assert.rejects(apiJson('/api/conversations/1'), /conflict/);
""")

    def test_prompt_add_updates_list_immediately_and_collapses_editor(self):
        self.run_script(r"""
esc = value => String(value || '');
currentConvId = 7;
resetExtraPromptEditor();
document.getElementById('extraPromptTitle').value = '手动提示';
document.getElementById('extraPromptContent').value = '很长的正文'.repeat(1000);
let calls=0, finish;
fetch = (url, options) => {
  calls++;
  assert.equal(url, '/api/conversations/7/extra-prompts');
  assert.equal(options.method, 'POST');
  return new Promise(resolve => {finish=resolve;});
};
const saving = saveExtraPrompt();
await saveExtraPrompt();
assert.equal(calls,1);
finish(new Response(JSON.stringify({prompt:{id:31,title:'手动提示',content:'正文',locked:true}})));
await saving;
assert.equal(extraPromptBundle.prompts.length,1);
assert.equal(document.getElementById('extraPromptEditor').open,false);
const list=document.getElementById('extraPromptBlocks').innerHTML;
assert.ok(list.includes('<details ontoggle='));
assert.ok(list.includes('手动提示'));
assert.ok(!list.includes('<details open'));
assert.match(document.getElementById('extraPromptStatus').textContent,/已保存.*锁定/);
assert.equal(extraPromptMutationBusy,false);
""")

    def test_prompt_edit_error_keeps_draft_and_updates_saved_copy_on_retry(self):
        self.run_script(r"""
esc = value => String(value || '');
currentConvId = 7;
extraPromptBundle.prompts = [{id:31,title:'旧标题',content:'旧正文',locked:false}];
editExtraPrompt(31);
document.getElementById('extraPromptContent').value = '新正文';
fetch = async () => new Response(JSON.stringify({error:'database busy'}),{status:500});
await saveExtraPrompt();
assert.equal(document.getElementById('extraPromptContent').value,'新正文');
assert.equal(editingExtraPromptId,31);
assert.equal(extraPromptBundle.prompts[0].content,'旧正文');
assert.equal(document.getElementById('extraPromptEditor').open,true);
assert.match(document.getElementById('extraPromptStatus').textContent,/database busy/);
fetch = async (url,options) => {
  assert.equal(url,'/api/conversations/7/extra-prompts/31');
  assert.equal(options.method,'PUT');
  return new Response(JSON.stringify({prompt:{id:31,title:'旧标题',content:'新正文',locked:false}}));
};
await saveExtraPrompt();
assert.equal(extraPromptBundle.prompts.length,1);
assert.equal(extraPromptBundle.prompts[0].content,'新正文');
assert.equal(document.getElementById('extraPromptEditor').open,false);
""")

    def test_slow_prompt_save_does_not_clear_another_conversation_or_new_draft(self):
        self.run_script(r"""
esc = value => String(value || '');
currentConvId=7;
resetExtraPromptEditor();
document.getElementById('extraPromptContent').value='first';
let finish;
fetch=()=>new Promise(resolve=>{finish=resolve;});
let pending=saveExtraPrompt();
currentConvId=8;
resetExtraPromptEditor();
document.getElementById('extraPromptContent').value='conversation 8 draft';
finish(new Response(JSON.stringify({prompt:{id:31,content:'first'}})));
await pending;
assert.equal(extraPromptBundle.prompts.length,0);
assert.equal(document.getElementById('extraPromptContent').value,'conversation 8 draft');
pending=saveExtraPrompt();
document.getElementById('extraPromptContent').value='newer draft';
extraPromptEditorVersion++;
finish(new Response(JSON.stringify({prompt:{id:32,content:'conversation 8 draft'}})));
await pending;
assert.equal(extraPromptBundle.prompts[0].id,32);
assert.equal(document.getElementById('extraPromptContent').value,'newer draft');
assert.equal(document.getElementById('extraPromptEditor').open,true);
""")

    def test_stale_prompt_load_cannot_hide_newly_added_prompt(self):
        self.run_script(r"""
esc = value => String(value || '');
currentConvId=7;
resetExtraPromptEditor();
document.getElementById('extraPromptContent').value='new';
let finishOld;
fetch = async (url,options) => options.method === 'POST'
  ? new Response(JSON.stringify({prompt:{id:31,content:'new'}}))
  : new Promise(resolve=>{finishOld=resolve;});
const loading = loadExtraPrompts();
await saveExtraPrompt();
finishOld(new Response(JSON.stringify({sources:[],prompts:[],injections:[]})));
await loading;
assert.equal(extraPromptBundle.prompts[0].id,31);
assert.ok(document.getElementById('extraPromptBlocks').innerHTML.includes('提示词 #31'));
""")

    def test_failed_prompt_toggle_and_delete_do_not_change_saved_state(self):
        self.run_script(r"""
esc = value => String(value || '');
global.confirm=()=>true;
currentConvId=7;
extraPromptBundle.prompts=[{id:31,content:'正文',locked:true}];
fetch=async()=>new Response(JSON.stringify({error:'服务暂不可用'}),{status:503});
await toggleExtraPrompt(31);
assert.equal(extraPromptBundle.prompts[0].locked,true);
assert.match(document.getElementById('extraPromptStatus').textContent,/服务暂不可用/);
await deleteExtraPrompt(31);
assert.equal(extraPromptBundle.prompts.length,1);
assert.equal(extraPromptMutationBusy,false);
fetch=async(url,options)=>new Response(JSON.stringify(options.method==='PUT'
 ? {prompt:{id:31,content:'正文',locked:false}}
 : {status:'ok'}));
await toggleExtraPrompt(31);
assert.equal(extraPromptBundle.prompts[0].locked,false);
await deleteExtraPrompt(31);
assert.equal(extraPromptBundle.prompts.length,0);
""")

    def test_folded_prompt_text_is_only_mounted_when_opened(self):
        self.run_script(r"""
esc = value => String(value || '');
const content='LAZY_BODY_SENTINEL'.repeat(1000);
extraPromptBundle={sources:[{id:4,content}],prompts:[{id:31,title:'标题',content}],injections:[]};
renderExtraPrompts();
assert.ok(!document.getElementById('extraPromptBlocks').innerHTML.includes('LAZY_BODY_SENTINEL'));
assert.ok(!document.getElementById('extraPromptSources').innerHTML.includes('LAZY_BODY_SENTINEL'));
const body={textContent:''};
const details={open:false,dataset:{},querySelector:()=>body};
renderExtraPromptBody(details,'prompt',31);
assert.equal(body.textContent,'');
details.open=true;
renderExtraPromptBody(details,'prompt',31);
assert.equal(body.textContent,content);
assert.equal(details.dataset.loaded,'true');
const area={value:''};
renderExtraPromptBody({open:true,dataset:{},querySelector:()=>area},'source',4);
assert.equal(area.value,content);
""")

    def test_folded_history_does_not_create_hundreds_of_hidden_cards(self):
        self.run_script(r"""
esc = value => String(value || '');
let created=0;
const rows=[];
document.createElement=()=>{created++;return {dataset:{},setAttribute(){},classList:{add(){}}};};
document.createDocumentFragment=()=>({appendChild:node=>rows.push(node)});
document.getElementById('convList').replaceChildren=()=>{};
const conversations=Array.from({length:500},(_,i)=>({id:i+1,name:'会话',created_at:'2026-10-01'}));
await renderConversationList(conversations,conversationListGeneration);
assert.equal(created,0);
printedHistoryExpanded=true;
await renderConversationList(conversations,conversationListGeneration);
assert.equal(rows.filter(row=>row.dataset.conversationId).length,500);
""")
