import json
from itertools import product
import unittest
from unittest.mock import AsyncMock, patch

import main


class FrontendToolPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_at_tool_response_does_not_lose_assistant(self):
        call = {'id': 'frontend-1', 'type': 'function', 'function': {
            'name': 'frontend_reply', 'arguments': json.dumps({'text': 'sent reply'})}}

        class Response:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def aiter_lines(self):
                yield 'data: ' + json.dumps({'choices': [{'delta': {
                    'tool_calls': [{'index': 0, **call}]}, 'finish_reason': None}]})
                yield 'data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}]})
                yield 'data: [DONE]'

            async def aiter_bytes(self):
                events = [
                    {'type': 'content_block_start', 'content_block': {
                        'type': 'tool_use', 'id': 'frontend-1', 'name': 'frontend_reply', 'input': {}}},
                    {'type': 'content_block_delta', 'delta': {
                        'type': 'input_json_delta', 'partial_json': json.dumps({'text': 'sent reply'})}},
                    {'type': 'content_block_stop'},
                    {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use'}},
                ]
                yield ''.join('data: ' + json.dumps(event) + '\n' for event in events).encode()

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def stream(self, *args, **kwargs):
                return Response()

        for provider, close_at in product(('openai', 'anthropic'), ('tool_calls', 'done')):
            with self.subTest(provider=provider, close_at=close_at):
                save = AsyncMock()
                dispatch = AsyncMock()
                with patch.object(main.httpx, 'AsyncClient', return_value=Client()), \
                     patch.object(main, '_save_ctx', save), \
                     patch.object(main, '_save_tool_context_rows', AsyncMock()), \
                     patch.object(main, '_record_token_usage', AsyncMock()), \
                     patch.object(main, 'dispatch_tool_call', dispatch):
                    stream_fn = (main.stream_openai_with_tool_loop if provider == 'openai'
                                 else main.stream_with_tool_loop)
                    stream = stream_fn(
                        {}, {'model': 'test', 'messages': [{'role': 'user', 'content': 'hello'}]},
                        7, 'hello', 'test', frontend_tool_names={'frontend_reply'},
                        api_url='https://fixture.test/v1/chat/completions')
                    try:
                        async for chunk in stream:
                            if (close_at == 'done' and chunk == 'data: [DONE]\n\n') or (
                                close_at == 'tool_calls' and '"tool_calls": [' in chunk
                            ):
                                break
                    finally:
                        # Simulate the frontend closing immediately, without asking
                        # the generator for another chunk after its terminal event.
                        await stream.aclose()
                save.assert_awaited_once_with(
                    7, 'assistant', '[tool_calls]',
                    content_json=[{'type': 'tool_use', 'id': 'frontend-1',
                                   'name': 'frontend_reply', 'input': {'text': 'sent reply'}}])
                dispatch.assert_not_awaited()
