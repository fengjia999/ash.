import json
import unittest
from contextlib import ExitStack
from itertools import product
from unittest.mock import AsyncMock, MagicMock, patch

import database
import main


class FrontendPromptSwitchTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_switch_controls_capture_and_sourced_blocks_not_reasoning(self):
        for enabled, inject, provider in product((False, True), (False, True), ('anthropic', 'openai')):
            with self.subTest(enabled=enabled, inject=inject, provider=provider), ExitStack() as stack:
                request = MagicMock()
                request.json = AsyncMock(return_value={
                    'provider': provider, 'model': 'claude-test',
                    'messages': [{'role': 'system', 'content': 'FRONTEND'},
                                 {'role': 'user', 'content': 'hello'}],
                })
                capture = AsyncMock(return_value=[{
                    'id': 1, 'content': 'FRONTEND', 'newly_captured': True,
                    'configured': False, 'initial_injected': False,
                }])
                loop = AsyncMock(return_value={
                    'content': [], 'choices': [{'message': {'content': ''}}],
                })
                record = AsyncMock()
                for key, value in {
                    'CONTEXT_MANAGED': True, 'MEMORY_ENABLED': False,
                    'get_route_settings': AsyncMock(return_value={'provider':'auto','model':''}),
                    'FORCE_STREAM': False, 'MODEL_CONTEXT_LIMIT': 0,
                    'PROMPT_CACHE_ENABLED': False,
                    'THINKING_MODE': 'budget', 'THINKING_BUDGET': 2048,
                    'OPENAI_REASONING': True, 'OPENAI_REASONING_EFFORT': 'high',
                    'get_active_conversation': AsyncMock(return_value={
                        'id': 7, 'capture_frontend_prompts': enabled,
                        'auto_inject_captured_prompts': inject,
                    }),
                    'capture_conversation_system_prompts': capture,
                    '_load_active_openai_provider': AsyncMock(return_value={
                        'api_key': 'test', 'api_url': 'https://api.openai.com/v1/chat/completions', 'name': 'test'}),
                    '_load_active_anthropic_provider': AsyncMock(return_value={
                        'api_key': 'test', 'api_url': 'https://example.test/v1/messages', 'name': 'test'}),
                    'resolve_conversation_tool_snapshot': AsyncMock(return_value=([], set())),
                    'preprocess_user_blocks_with_ocr': AsyncMock(return_value=([{'type':'text', 'text':'hello'}], None)),
                    'build_core_system_prompt_for_turn': AsyncMock(return_value='GATEWAY'),
                    'get_unlocked_conversation_extra_prompts': AsyncMock(return_value=[
                        {'id': 1, 'source_id': 1, 'content': 'SOURCED', 'position':'before', 'interval_turns':1},
                        {'id': 2, 'source_id': None, 'content': 'MANUAL', 'position':'before', 'interval_turns':1},
                    ]),
                    'save_conversation_chat_route': AsyncMock(),
                    'save_context_message': AsyncMock(return_value={'id': 10}),
                    'materialize_pending_heartbeat_activities': AsyncMock(return_value=0),
                    'get_context_messages': AsyncMock(return_value=[{
                        'id': 3, 'role': 'user', 'content': 'old question',
                        'prompt_injections': [
                            {'kind':'source', 'reference_id':1, 'position':'before', 'content':'OLD_FRONTEND'},
                            {'kind':'prompt', 'source_id':1, 'reference_id':2, 'position':'before', 'content':'OLD_SOURCED'},
                            {'kind':'prompt', 'reference_id':3, 'position':'before', 'content':'OLD_MANUAL'},
                        ],
                    }, {'id':4, 'role':'assistant', 'content':'old answer'}]),
                    'record_conversation_extra_prompt_injections': record,
                    'mark_conversation_prompt_sources_initial_injected': AsyncMock(),
                    '_save_response_tool_rows': AsyncMock(),
                    'handle_tool_loop': loop, 'handle_openai_tool_loop': loop,
                }.items():
                    stack.enter_context(patch.object(main, key, value))
                response = await main.chat_completions(request)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(capture.await_count, int(enabled))
                body = loop.await_args.args[1]
                text = json.dumps(body, ensure_ascii=False)
                self.assertEqual('FRONTEND' in text, enabled and inject)
                self.assertEqual('SOURCED' in text, enabled and inject)
                self.assertEqual('OLD_FRONTEND' in text, enabled and inject)
                self.assertEqual('OLD_SOURCED' in text, enabled and inject)
                self.assertIn('OLD_MANUAL', text)
                self.assertIn('MANUAL', text)
                self.assertIn('GATEWAY', text)
                if provider == 'anthropic':
                    self.assertEqual(body['thinking']['budget_tokens'], 2048)
                else:
                    prepared = main._prepare_openai_chat_body(body, 'https://api.openai.com/v1/chat/completions')
                    self.assertEqual(prepared['reasoning_effort'], 'high')
                    body['reasoning_effort'] = 'low'
                    self.assertEqual(main._prepare_openai_chat_body(body, 'https://api.openai.com/v1/chat/completions')['reasoning_effort'], 'low')
                self.assertEqual([p['id'] for p in record.await_args.args[1]], [1, 2] if enabled and inject else [2])

    async def test_api_accepts_partial_settings_and_rejects_nonbooleans(self):
        save = AsyncMock(return_value={'id': 7, 'capture_frontend_prompts': False})
        request = MagicMock()
        with patch.object(main, 'save_conversation_prompt_capture_settings', save):
            request.json = AsyncMock(return_value={'capture_frontend_prompts': False})
            result = await main.api_update_conversation_extra_prompt_settings(7, request)
            self.assertEqual(result['status'], 'ok')
            save.assert_awaited_once_with(7, None, capture_frontend_prompts=False)
            for data in ({}, {'capture_frontend_prompts': 'false'}, {'auto_inject_captured_prompts': None}, []):
                request.json = AsyncMock(return_value=data)
                result = await main.api_update_conversation_extra_prompt_settings(7, request)
                self.assertEqual(result.status_code, 400)

    async def test_storage_and_handoff_preserve_disabled_settings(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {'id': 7, 'max_messages': 50, 'capture_frontend_prompts': False, 'auto_inject_captured_prompts': False},
            {'id': 8},
        ])
        conn.execute = AsyncMock()
        conn.transaction.return_value.__aenter__ = AsyncMock()
        conn.transaction.return_value.__aexit__ = AsyncMock()
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock()
        with patch.object(database, 'get_pool', AsyncMock(return_value=pool)):
            await database.create_conversation_from_messages(7, 'next', [], False)
            self.assertEqual(conn.fetchrow.await_args.args[-2:], (False, False))
            conn.fetchrow = AsyncMock(return_value={'id': 7})
            await database.save_conversation_prompt_capture_settings(7, capture_frontend_prompts=False)
            sql, *args = conn.fetchrow.await_args.args
            self.assertIn('COALESCE($2, auto_inject_captured_prompts)', sql)
            self.assertIn('COALESCE($3, capture_frontend_prompts)', sql)
            self.assertEqual(args, [7, None, False])
        backup = database.GATEWAY_BACKUP_TABLES['conversations']
        self.assertIn('capture_frontend_prompts', backup['columns'])
        self.assertIs(backup['defaults']['capture_frontend_prompts'], True)

    def test_reenable_can_inject_previously_captured_but_never_injected_source(self):
        source = {'content': 'pending prompt', 'newly_captured': False,
                  'configured': False, 'initial_injected': False}
        self.assertEqual(main._initial_frontend_prompt_text([source], False), '')
        self.assertEqual(main._initial_frontend_prompt_text([source], True), 'pending prompt')
        source['initial_injected'] = True
        self.assertEqual(main._initial_frontend_prompt_text([source], True), '')

    def test_old_envelope_filter_preserves_literal_user_text_and_database_row(self):
        row = {'role':'user', 'content':'SECRET is what I wrote',
               'content_json':[{'type':'text', 'text':'SECRET' + main._CURRENT_MESSAGE_MARKER},
                               {'type':'text', 'text':'SECRET is what I wrote'}],
               'prompt_injections':[{'kind':'source', 'position':'before', 'content':'SECRET'}]}
        original = json.dumps(row)
        messages = main._rebuild_messages_from_rows([row], {'auto_inject_captured_prompts':False})
        self.assertNotIn('SECRET', messages[0]['content'][0]['text'])
        self.assertEqual(messages[0]['content'][1]['text'], 'SECRET is what I wrote')
        self.assertEqual(json.dumps(row), original)

    def test_ui_saves_both_switches_and_rolls_back_failed_save(self):
        import shutil
        import subprocess
        from pathlib import Path
        if not shutil.which('node'):
            self.skipTest('Node required')
        template = (Path(__file__).resolve().parents[1] / 'static/js/conversation-prompts.js').read_text().replace('promptConversationId', 'currentConvId')
        functions = 'function loadExtraPrompts() {' + template.split('function loadExtraPrompts() {', 1)[1].split('function usePromptSelection', 1)[0]
        harness = r'''
const assert = require('node:assert/strict');
const elements = Object.fromEntries(['captureFrontendPrompts', 'autoInjectCapturedPrompts',
    'extraPromptSources', 'extraPromptBlocks', 'extraPromptInjections', 'extraPromptStatus'].map(id => [id, {dataset:{}}]));
const document = {getElementById: id => elements[id], querySelectorAll:()=>[]};
let extraPromptMutationBusy = false;
let currentConvId = 7, extraPromptRequestVersion = 0;
let extraPromptBundle = {capture_frontend_prompts:true, auto_inject_captured_prompts:true};
const alert = () => {};
let api;
'''
        scenario = r'''
(async () => {
renderExtraPrompts();
elements.autoInjectCapturedPrompts.checked = false;
api = async (url, options) => {
    assert.equal(url, '/api/conversations/7/extra-prompt-settings');
    assert.deepEqual(JSON.parse(options.body), {capture_frontend_prompts:true, auto_inject_captured_prompts:false});
    return {ok:true, json:async () => ({status:'ok'})};
};
await saveExtraPromptCaptureSetting();
assert.equal(extraPromptBundle.auto_inject_captured_prompts, false);
elements.autoInjectCapturedPrompts.checked = true;
api = async () => ({ok:false, json:async () => ({error:'offline'})});
await saveExtraPromptCaptureSetting();
assert.equal(elements.autoInjectCapturedPrompts.checked, false);
assert.equal(elements.captureFrontendPrompts.disabled, false);
let finishOld;
api = () => new Promise(resolve => {finishOld = resolve;});
const oldRead = loadExtraPrompts();
++extraPromptRequestVersion;
extraPromptBundle = {capture_frontend_prompts:false, auto_inject_captured_prompts:false};
renderExtraPrompts();
finishOld({ok:true, json:async () => ({capture_frontend_prompts:true, auto_inject_captured_prompts:true})});
await oldRead;
assert.equal(elements.captureFrontendPrompts.checked, false);
assert.equal(elements.autoInjectCapturedPrompts.disabled, true);
})().catch(e => {console.error(e); process.exitCode = 1;});
'''
        result = subprocess.run(['node', '-'], input=harness + functions + scenario,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
