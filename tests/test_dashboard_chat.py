import json
import unittest
from unittest.mock import AsyncMock, patch
import main
from test_gateway_auth import make_request, accepted

class DashboardChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_redirect_and_separate_health(self):
        self.assertEqual((await main.home()).headers['location'], '/dashboard')

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
        script = "const document={addEventListener(){}};\n" + source + r'''
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
  await assert.rejects(consumeChatStream(stream('data: {"choices":[]}\n\n'),()=>{}),/连接中断/);
  await assert.rejects(consumeChatStream(stream('data: {"error":{"message":"bad upstream"}}\n\n'),()=>{}),/bad upstream/);
})();
'''
        result = subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_model_selection_prefers_route_compatible_models(self):
        import shutil
        import subprocess
        from pathlib import Path
        if not shutil.which('node'):
            self.skipTest('Node required')
        source = (Path(__file__).resolve().parents[1] / 'static/js/context-chat.js').read_text()
        load_config = 'async function loadChatConfig(' + source.split(
            'async function loadChatConfig(', 1
        )[1].split('async function changeChatRoute(', 1)[0]
        script = r'''
const assert = require('node:assert/strict');
const elements = {
  chatRoute: {value: ''},
  chatProvider: {value: '', replaceChildren(){}, add(){}},
  chatModels: {replaceChildren(){}, appendChild(){}},
  chatModel: {value: ''},
  chatStatus: {textContent: ''},
};
const chatElement = id => elements[id] || {disabled: false};
const Option = function(text, value) { this.text = text; this.value = value; };
let chatConfigBusy = false;
let chatConfigured = false;
const updateChatAvailability = () => {};
const responses = [
  {provider: 'openai'},
  {profiles: [], effective: {name: 'env'}},
  {default_model: 'claude-sonnet-4-5', data: [{id: 'gpt-5'}]},
  {provider: 'openai'},
  {profiles: [], effective: {name: 'env'}},
  {default_model: 'claude-sonnet-4-5', data: [{id: 'gpt-5'}]},
  {provider: 'anthropic'},
  {profiles: [], effective: {name: 'env'}},
  {default_model: 'claude-sonnet-4-5', data: [{id: 'claude-sonnet-4-5'}]},
];
const chatJson = async () => responses.shift();
''' + load_config + r'''
(async () => {
  await loadChatConfig();
  assert.equal(elements.chatModel.value, 'gpt-5');
  elements.chatModel.value = 'custom/provider-model';
  await loadChatConfig();
  assert.equal(elements.chatModel.value, 'custom/provider-model');
  await loadChatConfig(true);
  assert.equal(elements.chatModel.value, 'claude-sonnet-4-5');
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
