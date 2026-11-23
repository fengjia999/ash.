import copy
import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import main
import database


MODEL = 'claude-opus-4-6'
MARKER = {'type': 'ephemeral', 'ttl': '1h'}


def canonical(messages):
    result = main._strip_cache_control_for_fingerprint(messages)
    for message in result:
        if isinstance(message['content'], str):
            message['content'] = [{'type': 'text', 'text': message['content']}]
    return result


def marked_indices(body):
    return [i for i, m in enumerate(body['messages'])
            if isinstance(m['content'], list) and any(b.get('cache_control') for b in m['content'])]


class FullContextCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {'PROMPT_CACHE_ENABLED': True,
                            'PROMPT_CACHE_MESSAGE_MODELS': {MODEL}, 'CONTEXT_MANAGED': True,
                            '_MESSAGE_CACHE_SEEN_BY_SCOPE': {},
                            '_MESSAGE_CACHE_SEEN_ORDER_BY_SCOPE': {}}.items():
            self.stack.enter_context(patch.object(main, name, value))
        self.system = [{'type': 'text', 'text': 'core', 'cache_control': MARKER},
                       {'type': 'text', 'text': 'flow', 'cache_control': MARKER}]

    async def test_chat_heartbeat_tools_hidden_activity_and_chat_share_prefix(self):
        history = [{'role': 'user', 'content': 'start'}]
        # A long existing history must not rely on the provider's lookback window.
        for i in range(25):
            history.extend([{'role': 'assistant', 'content': 'reply ' + str(i)},
                            {'role': 'user', 'content': 'question ' + str(i)}])
        system, history = main._freeze_managed_turn_context(
            self.system + [{'type': 'text', 'text': 'recall for this turn'}], history)
        body = {'model': MODEL, 'system': system,
                'tools': [{'name': 'lookup', 'input_schema': {'type': 'object'}}]}
        chat = main._anthropic_body_for_request(body, history, stream=False, cache_scope_id=7)
        old_anchor = main._latest_cache_anchor(7)
        history.append({'role': 'assistant', 'content': 'last answer'})
        # Database JSON replay must preserve the exact request prefix.
        history = main._rebuild_messages_from_rows([
            {'role': m['role'], 'content': m['content'] if isinstance(m['content'], str) else '',
             'content_json': json.dumps(m['content']) if isinstance(m['content'], list) else None}
            for m in history])
        history = main._compact_old_tool_results(history)
        renewal = main._latest_durable_cache_anchor(history)
        trigger = {'role': 'user', 'content': '<proactive_check>now</proactive_check>'}
        client = MagicMock()
        responses = []
        for i in range(2):
            response = MagicMock(status_code=200)
            response.json.return_value = {'stop_reason': 'tool_use', 'usage': {}, 'content': [
                {'type': 'tool_use', 'id': 't' + str(i), 'name': 'lookup', 'input': {'i': i}}]}
            responses.append(response)
        final = MagicMock(status_code=200)
        final.json.return_value = {'stop_reason': 'end_turn', 'usage': {},
                                  'content': [{'type': 'text', 'text': 'done'}]}
        client.post = AsyncMock(side_effect=responses + [final])
        with patch.object(main, 'get_http_client', AsyncMock(return_value=client)), patch.object(
            main, 'dispatch_tool_call', AsyncMock(return_value='tool result')
        ), patch.object(main, '_record_token_usage', AsyncMock()):
            await main.handle_tool_loop({}, {**body, 'messages': history + [trigger]},
                session_id=7, route='heartbeat', cache_mode='renew',
                cache_anchor_fingerprint=old_anchor, cache_renewal_fingerprint=renewal)
        requests = [call.kwargs['json'] for call in client.post.await_args_list]
        self.assertEqual(canonical(chat['messages']), canonical(requests[0]['messages'][:-2]))
        for request in requests:
            self.assertEqual(request['system'], chat['system'])
            self.assertEqual(request['tools'], chat['tools'])
            self.assertEqual(canonical(history), canonical(request['messages'][:len(history)]))
            self.assertIn(len(history) - 1, marked_indices(request))
            self.assertLessEqual(len(marked_indices(request)) + 2, 4)
        for previous, current in zip(requests, requests[1:]):
            self.assertEqual(canonical(previous['messages']),
                             canonical(current['messages'][:len(previous['messages'])]))
        # Only the durable history endpoint is persisted, never transient tool data.
        main._seed_persisted_cache_anchor({'id': 7, 'cache_anchor_fingerprint': renewal})
        hidden = {'role': 'assistant', 'content': database._heartbeat_activity_context_text({
            'id': 1, 'tool_events': [{'name': 'lookup', 'input': {}, 'result': 'result', 'ok': True}],
            'final_text': 'done'})}
        next_system, next_history = main._freeze_managed_turn_context(
            self.system + [{'type': 'text', 'text': 'new recall'}],
            history + [hidden, {'role': 'user', 'content': 'back'}])
        next_chat = main._anthropic_body_for_request(
            {**body, 'system': next_system}, next_history, stream=False, cache_scope_id=7)
        self.assertIn(len(history) - 1, marked_indices(next_chat))
        self.assertEqual(canonical(history), canonical(next_chat['messages'][:len(history)]))

    def test_managed_dynamic_context_precedes_and_labels_current_message(self):
        system, history = main._freeze_managed_turn_context(
            self.system + [{'type': 'text', 'text': '自动召回内容'}],
            [{'role': 'user', 'content': '用户真正说的话'}],
        )

        self.assertEqual(self.system, system)
        blocks = history[0]['content']
        self.assertEqual(2, len(blocks))
        self.assertTrue(blocks[0]['text'].startswith('自动召回内容'))
        self.assertIn('自动召回内容', blocks[0]['text'])
        self.assertTrue(blocks[0]['text'].endswith('【当前消息】'))
        self.assertEqual('用户真正说的话', blocks[1]['text'])

    def test_managed_dynamic_context_keeps_multimodal_user_content_after_boundary(self):
        original = [
            {'type': 'text', 'text': '看看这张图'},
            {'type': 'image', 'source': {'type': 'base64', 'data': 'abc'}},
        ]
        _system, history = main._freeze_managed_turn_context(
            self.system + [{'type': 'text', 'text': '后台资料'}],
            [{'role': 'user', 'content': original}],
        )

        self.assertTrue(history[0]['content'][0]['text'].endswith('【当前消息】'))
        self.assertEqual(original, history[0]['content'][1:])

    def test_managed_tool_history_never_rewrites_old_results(self):
        messages = [{'role': 'user', 'content': [{'type': 'tool_result',
                     'tool_use_id': str(i), 'content': 'full result ' + str(i)}]} for i in range(40)]
        before = copy.deepcopy(messages)
        with patch.object(main, 'TOOL_HISTORY_EVENT_LIMIT', 2):
            self.assertEqual(before, main._compact_old_tool_results(messages))
        self.assertEqual(before, messages)

    def test_chat_explicitly_reuses_tool_result_anchor(self):
        result = {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 't', 'content': 'full'}]}
        main._seed_persisted_cache_anchor({'id': 8, 'cache_anchor_fingerprint': main._message_anchor_fingerprint(result)})
        history = [{'role': 'user', 'content': 'old'}, result] + [
            {'role': 'assistant', 'content': 'activity ' + str(i)} for i in range(25)]
        history.append({'role': 'user', 'content': 'back'})
        request = main._anthropic_body_for_request({'model': MODEL, 'system': self.system},
            history, stream=False, cache_scope_id=8)
        self.assertIn(1, marked_indices(request))

    async def test_claim_failure_cannot_publish_a_renewed_anchor(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=False)
        conn.execute = AsyncMock()
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        with patch.object(database, 'get_pool', AsyncMock(return_value=pool)):
            result = await database.finish_heartbeat_silently(7, 'stale', 1, 2,
                                                            cache_anchor_fingerprint='new')
        self.assertFalse(result)
        conn.execute.assert_not_awaited()
