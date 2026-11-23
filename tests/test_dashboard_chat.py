import json
import unittest
from unittest.mock import AsyncMock, patch
import main
from test_gateway_auth import make_request, accepted

class DashboardChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_redirect_and_separate_health(self):
        self.assertEqual((await main.home()).headers['location'], '/dashboard')

    async def test_dashboard_model_timeout_returns_a_manual_entry_fallback(self):
        with patch.object(main, '_load_routed_models', AsyncMock(side_effect=TimeoutError)):
            response = await main.dashboard_chat_models()
        self.assertTrue(response['models_unavailable'])
        self.assertEqual([], response['data'])

    async def test_chat_requires_dashboard_cookie_and_csrf(self):
        with patch.object(main, 'DASHBOARD_PASSWORD', 'test'):
            value, csrf = main._create_dashboard_session()
            headers = {'Cookie': f'{main._DASHBOARD_SESSION_COOKIE}={value}'}
            path = '/api/conversations/7/chat'
            denied = await main.gateway_auth_middleware(make_request(path, 'POST', headers=headers), accepted)
            self.assertEqual(denied.status_code, 403)
            headers['X-CSRF-Token'] = csrf
            allowed = await main.gateway_auth_middleware(make_request(path, 'POST', headers=headers), accepted)
            self.assertEqual(allowed.status_code, 200)

    async def test_stale_conversation_cannot_send_even_a_command(self):
        for content in ['hello', '/switch']:
            request = make_request('/api/conversations/7/chat', 'POST', body=json.dumps({'messages':[{'role':'user','content':content}]}).encode())
            with patch.object(main, 'CONTEXT_MANAGED', True), patch.object(main, 'get_active_conversation', AsyncMock(return_value={'id':8})), patch.object(main, '_execute_gateway_command', AsyncMock()) as command:
                response = await main.dashboard_chat(7, request)
            self.assertEqual(response.status_code, 409)
            command.assert_not_awaited()

    async def test_chat_reuses_gateway_handler_without_injecting_secrets(self):
        request = make_request('/api/conversations/7/chat', 'POST', body=json.dumps({'messages':[{'role':'user','content':'hello'}]}).encode())
        with patch.object(main, 'CONTEXT_MANAGED', True), patch.object(main, 'chat_completions', AsyncMock(return_value='stream')) as handler:
            self.assertEqual(await main.dashboard_chat(7, request), 'stream')
            self.assertEqual(request.state.dashboard_conversation_id, 7)
            self.assertNotIn('authorization', request.headers)
            handler.assert_awaited_once_with(request)

    async def test_rejects_nonmanaged_or_invalid_messages(self):
        with patch.object(main, 'CONTEXT_MANAGED', False):
            self.assertEqual((await main.dashboard_chat(7, make_request('/api/conversations/7/chat','POST'))).status_code, 409)
        for body in [None, {}, {'messages':[1]}, {'messages':[{'role':'assistant','content':'hi'}]}]:
            with patch.object(main,'CONTEXT_MANAGED',True):
                response = await main.dashboard_chat(7,make_request('/api/conversations/7/chat','POST',body=json.dumps(body).encode()))
                self.assertEqual(response.status_code,400)

class ChatStreamTests(unittest.TestCase):
    def test_fragmented_unicode_sse_and_interrupted_stream(self):
        import shutil
        import subprocess
        from pathlib import Path
        if not shutil.which('node'):
            self.skipTest('Node required')
        source = (Path(__file__).resolve().parents[1] / 'static/js/context-chat.js').read_text()
        script = "const document={addEventListener(){}};const window={addEventListener(){}};\n" + source + r'''
const assert = require('node:assert/strict');
function stream(text) {
  const bytes = new TextEncoder().encode(text);
  return {body:new ReadableStream({start(controller) {
    for (let i=0;i<bytes.length;i++) controller.enqueue(bytes.slice(i,i+1));
    controller.close();
  }})};
}
(async()=>{
  let text='';
  await consumeChatStream(stream('data: {"choices":[{"delta":{"content":"你好"}}]}\r\n\r\ndata: [DONE]\r\n\r\n'),delta=>text+=delta);
  assert.equal(text,'你好');
  let thought='';
  await consumeChatStream(stream('data: {"choices":[{"delta":{"reasoning_content":"先思考"}}]}\n\ndata: {"choices":[{"delta":{"reasoning_details":[{"type":"reasoning.summary","summary":"再检查"},{"type":"reasoning.encrypted","data":"secret"}]}}]}\n\ndata: [DONE]\n\n'),()=>{},delta=>thought+=delta);
  assert.equal(thought,'先思考再检查');
  await assert.rejects(consumeChatStream(stream('data: {"choices":[]}\n\n'),()=>{}),/连接中断/);
  await assert.rejects(consumeChatStream(stream('data: {"error":{"message":"bad upstream"}}\n\n'),()=>{}),/bad upstream/);
})();
'''
        result = subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_chat_reads_server_configuration_without_changing_suppliers(self):
        import shutil
        import subprocess
        from pathlib import Path
        if not shutil.which('node'):
            self.skipTest('Node required')
        source = (Path(__file__).resolve().parents[1] / 'static/js/context-chat.js').read_text()
        loader = 'async function loadChatConfig(' + source.split('async function loadChatConfig(', 1)[1].split('// Construct Markdown nodes', 1)[0]
        script = r"""
const assert=require('node:assert/strict');
let chatConfigGeneration=0,chatConfigBusy=false,chatConfigured=false,chatEffectiveModel='';
let config={model:'fixed-chat-model',provider:'anthropic',ready:true};
const elements={chatStatus:{}};
const chatElement=id=>elements[id];
const calls=[];const chatJson=async url=>{calls.push(url);return config;};
const updateChatAvailability=()=>{};
const window={AshChatUI:{setModelLabel:model=>{elements.label=model;}}};
""" + loader + r"""
(async()=>{
 await loadChatConfig();
 assert.equal(chatEffectiveModel,'fixed-chat-model');assert.equal(chatConfigured,true);
 assert.deepEqual(calls,['/api/chat/config']);assert.equal(elements.label,'fixed-chat-model');
 config={model:'',provider:'openai',ready:false};await loadChatConfig();assert.equal(chatConfigured,false);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
