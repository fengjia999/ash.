import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import database


ROOT = Path(__file__).resolve().parents[1]


def pool_for(conn):
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


class ConversationReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_management_page_does_not_read_large_prompt_bodies(self):
        conn = MagicMock(fetch=AsyncMock(side_effect=[[{'id': 31, 'content': 'hello'}], []]))
        with patch.object(database, 'get_pool', AsyncMock(return_value=pool_for(conn))):
            rows = await database.get_context_message_page(7, 21)
        self.assertEqual('hello', rows[0]['content'])
        query = conn.fetch.await_args_list[1].args[0]
        for expression in ('i.content', 'p.content', 's.content'):
            self.assertNotIn(expression, query)
        self.assertEqual(2, query.count('NULL::TEXT AS content'))
        page = conn.fetch.await_args_list[0].args[0]
        self.assertIn('ORDER BY id DESC', page)
        self.assertIn('LIMIT $2', page)

    async def test_model_context_still_reads_saved_injection_bodies(self):
        conn = MagicMock(fetch=AsyncMock(return_value=[{
            'message_id': 31, 'content': 'complete original prompt', 'title': 'original',
        }]))
        rows = await database._attach_context_prompt_injections(conn, 7, [{'id': 31}])
        self.assertEqual('complete original prompt', rows[0]['prompt_injections'][0]['content'])
        self.assertIn("COALESCE(i.content, p.content, '')", conn.fetch.await_args.args[0])
        self.assertIn('s.content AS content', conn.fetch.await_args.args[0])

    async def test_visible_message_and_annotation_indexes_match_page_queries(self):
        conn = MagicMock(execute=AsyncMock(), fetchval=AsyncMock(return_value=1))
        with patch.object(database, 'get_pool', AsyncMock(return_value=pool_for(conn))):
            await database.init_context_tables()
        queries = [call.args[0] for call in conn.execute.await_args_list]
        visible = next(q for q in queries if 'idx_ctx_visible_conversation_id' in q)
        self.assertIn('(conversation_id, id DESC)', visible)
        self.assertIn('WHERE hidden = FALSE', visible)
        self.assertIn("role IN ('user', 'assistant')", visible)
        self.assertIn('(conversation_id, message_id)', next(q for q in queries if 'idx_extra_prompt_injections_message' in q))


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class ConversationLoadingUiTests(unittest.TestCase):
    def node(self, source):
        result = subprocess.run(['node', '-'], input=source, text=True, capture_output=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_slow_model_discovery_does_not_lock_chat_or_replace_typed_model(self):
        source = (ROOT / 'static/js/context-chat.js').read_text()
        functions = 'function updateChatAvailability() {' + source.split('function updateChatAvailability() {', 1)[1].split('async function changeChatRoute(', 1)[0]
        self.node(r"""
const assert=require('node:assert/strict');
const nodes=new Proxy({}, {get:(map,id)=>map[id] ||= {value:'',textContent:'',disabled:false,hidden:false,replaceChildren(){},add(){},appendChild(){}}});
const chatElement=id=>nodes[id];
const Option=function(text,value){this.text=text;this.value=value;};
let chatBusy=false,chatConfigBusy=false,chatConfigured=false,chatConfigGeneration=0;
let currentConversationOverview={is_active:true},finishModel;
const chatJson=async(url,options,timeout)=>{
 if(url==='/api/route-settings')return {provider:'openai'};
 if(url==='/api/openai-providers')return {profiles:[],effective:{name:'test'}};
 assert.equal(timeout,8000);
 return new Promise(resolve=>{finishModel=resolve;});
};
""" + functions + r"""
(async()=>{
const loading=loadChatConfig(true);
await new Promise(resolve=>setImmediate(resolve));
assert.equal(chatConfigBusy,false);
assert.equal(chatConfigured,true);
assert.equal(nodes.chatModel.disabled,false);
assert.equal(nodes.msgInput.disabled,false);
nodes.chatModel.value='manually-typed-model';
updateChatAvailability();
assert.equal(nodes.sendBtn.disabled,false);
finishModel({data:[{id:'different-model'}],default_model:'different-model'});
await loading;
assert.equal(nodes.chatModel.value,'manually-typed-model');
})().catch(e=>{console.error(e);process.exitCode=1;});
""")

    def test_unavailable_model_list_still_allows_manual_model_entry(self):
        source = (ROOT / 'static/js/context-chat.js').read_text()
        functions = 'async function loadChatConfig(' + source.split('async function loadChatConfig(', 1)[1].split('async function changeChatRoute(', 1)[0]
        self.node(r"""
const assert=require('node:assert/strict');
const nodes=new Proxy({}, {get:(map,id)=>map[id] ||= {value:'',textContent:'',replaceChildren(){},add(){},appendChild(){}}});
const chatElement=id=>nodes[id],updateChatAvailability=()=>{};
const Option=function(){};
let chatBusy=false,chatConfigBusy=false,chatConfigured=false,chatConfigGeneration=0;
const chatJson=async url=>{
 if(url==='/api/route-settings')return {provider:'openai'};
 if(url==='/api/openai-providers')return {profiles:[],effective:{name:'test'}};
 throw new Error('timeout');
};
""" + functions + r"""
(async()=>{
await loadChatConfig();
assert.equal(chatConfigured,true);
assert.equal(chatConfigBusy,false);
assert.match(nodes.chatStatus.textContent,/可直接填写/);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")

    def test_slow_frame_is_a_warning_until_the_message_request_actually_fails(self):
        source = (ROOT / 'static/js/dashboard.js').read_text()
        function = 'function setConversationFrameStatus(' + source.split('function setConversationFrameStatus(', 1)[1].split('function retryConversationFrame(', 1)[0]
        self.node(r"""
const assert=require('node:assert/strict');
const nodes=new Proxy({}, {get:(map,id)=>map[id] ||= {dataset:{},hidden:false,textContent:''}});
const byId=id=>nodes[id];
const conversationFrameTimers={list:null,detail:null};
const CONVERSATION_FRAME_TIMEOUT_MS=15000;
let slow;
const clearTimeout=()=>{},setTimeout=fn=>{slow=fn;return 1;};
""" + function + r"""
setConversationFrameStatus('detail','loading');slow();
assert.equal(nodes['conversation-detail-status'].dataset.state,'slow');
assert.equal(nodes['conversation-detail-retry'].hidden,false);
setConversationFrameStatus('detail','ready');
assert.equal(nodes['conversation-detail-status'].hidden,true);
setConversationFrameStatus('detail','error','消息读取失败');
assert.equal(nodes['conversation-detail-status'].dataset.state,'error');
assert.equal(nodes['conversation-detail-status-text'].textContent,'消息读取失败');
""")
