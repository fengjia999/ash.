import copy
import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import main


RECALL = '<past_conversations source="memory_gateway">仅召回资料：旧话【当前消息】</past_conversations>'
RAW_USER = '本轮用户原话，文字里包含【当前消息】，应完整保留。'
REAL_REPLY = '这是本轮真实回复，也确实谈到了旧话。'
RUNTIME = {'api_url': 'https://example.test/v1', 'api_key': 'test', 'model': 'summary-test'}


def frozen_messages():
    image = {'type': 'image', 'source': {'type': 'base64', 'data': 'abc'}}
    return main._prepend_turn_recall([
        {'role': 'user', 'content': [{'type': 'text', 'text': RAW_USER}, image]},
    ], RECALL) + [{'role': 'assistant', 'content': REAL_REPLY}]


def stored_rows():
    frozen = frozen_messages()
    return [
        {'id': 1, 'role': 'user', 'content': RAW_USER, 'hidden': False,
         'content_json': json.dumps(frozen[0]['content'], ensure_ascii=False)},
        {'id': 2, 'role': 'assistant', 'content': REAL_REPLY, 'hidden': False,
         'content_json': None},
    ]


class CompactRecallBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def assert_clean_transcript(self, text):
        self.assertIn(RAW_USER, text)
        self.assertIn(REAL_REPLY, text)
        self.assertNotIn('仅召回资料', text)
        self.assertNotIn(main._SYSTEM_REFERENCE_INTRO, text)
        self.assertNotIn('<past_conversations', text)

    def test_database_transcript_uses_raw_text_without_reading_cached_recall(self):
        rows = stored_rows()
        before = copy.deepcopy(rows)
        transcript = main._render_frontend_context_for_organizer(rows, 0)
        self.assert_clean_transcript(transcript)
        self.assertEqual(before, rows)
        self.assertIn('仅召回资料', rows[0]['content_json'])

    def test_runtime_transcript_omits_reference_but_preserves_raw_words_and_images(self):
        messages = frozen_messages()
        messages = main._prepend_extra_prompts_to_latest_user(messages, '<extra_prompt>后台参考</extra_prompt>')
        before = copy.deepcopy(messages)
        transcript = main._render_frontend_context_for_organizer(messages, 0)
        self.assert_clean_transcript(transcript)
        self.assertIn('[图片]', transcript)
        self.assertNotIn('后台参考', transcript)
        self.assertEqual(before, messages)

    def test_literal_user_markup_and_actual_assistant_quotations_are_kept(self):
        literal = main._SYSTEM_REFERENCE_INTRO + '\n\n' + RECALL + '\n\n【当前消息】\n字面内容'
        transcript = main._render_frontend_context_for_organizer([
            {'role': 'user', 'content': literal},
            {'role': 'assistant', 'content': '我实际说出了：仅召回资料。'},
        ], 0)
        self.assertIn(literal, transcript)
        self.assertIn('我实际说出了：仅召回资料。', transcript)

    async def test_compact_redo_dashboard_and_temporary_requests_have_clean_transcripts(self):
        for mode in ('compact', 'redo', 'dashboard', 'temporary'):
            with self.subTest(mode=mode), ExitStack() as stack:
                rows = stored_rows()
                rows.append({'id': 3, 'role': 'user', 'content': '隐藏内容', 'hidden': True,
                             'content_json': None})
                if mode == 'redo':
                    rows.append({'id': 4, 'role': 'user', 'content': '快照之后的新消息',
                                 'hidden': False, 'content_json': None})
                before = copy.deepcopy(rows)
                response = MagicMock(status_code=200)
                response.json.return_value = {'choices': [{'finish_reason': 'stop',
                    'message': {'content': '干净的摘要'}}]}
                client = MagicMock()
                client.post = AsyncMock(return_value=response)
                for name, value in {
                    'CONTEXT_MANAGED': True, 'MEMORY_ORGANIZER_ENABLED': True,
                    'get_context_messages': AsyncMock(return_value=rows),
                    'get_conversation_handoff_summary': AsyncMock(return_value='已有摘要'),
                    'get_conversation_context_metadata': AsyncMock(return_value={
                        'id': 7, 'temporary_summary_through_message_id': 2, 'temporary_summary': '已有摘要'}),
                    '_load_handoff_summary_runtime': AsyncMock(return_value=RUNTIME),
                    '_load_temporary_summary_runtime': AsyncMock(return_value=RUNTIME),
                    'build_system_prompt': AsyncMock(return_value='core'),
                    'get_standing_memory_blocks': AsyncMock(return_value=[]),
                    'get_identity_presets': AsyncMock(return_value={}),
                    'get_http_client': AsyncMock(return_value=client),
                    '_record_token_usage': AsyncMock(),
                    'save_conversation_handoff_command_summary': AsyncMock(return_value=1),
                    'set_conversation_handoff_draft': AsyncMock(),
                    'set_conversation_temporary_summary': AsyncMock(return_value={
                        'id': 7, 'temporary_summary': '干净的摘要', 'temporary_summary_through_message_id': 2}),
                }.items():
                    stack.enter_context(patch.object(main, name, value))
                if mode in ('compact', 'redo'):
                    result = await main._gateway_generate_compact(
                        {'id': 7, 'handoff_summary_through_message_id': 2}, redo=mode == 'redo')
                    self.assertEqual(('干净的摘要', 1, 2), result)
                elif mode == 'dashboard':
                    self.assertEqual('ok', (await main.api_generate_handoff_summary(7))['status'])
                else:
                    self.assertEqual('ok', (await main.api_generate_temporary_summary(7))['status'])
                request_text = client.post.await_args.kwargs['json']['messages'][1]['content']
                transcript = request_text.split('<conversation_transcript>\n', 1)[1].split(
                    '\n</conversation_transcript>', 1)[0]
                self.assert_clean_transcript(transcript)
                self.assertNotIn('隐藏内容', transcript)
                self.assertNotIn('快照之后的新消息', transcript)
                self.assertEqual(before, rows)

    async def test_summary_model_request_is_clean_even_from_runtime_cached_messages(self):
        messages = frozen_messages()
        before = copy.deepcopy(messages)
        response = MagicMock(status_code=200)
        response.json.return_value = {'choices': [{'finish_reason': 'stop',
                                                  'message': {'content': '干净的摘要'}}]}
        client = MagicMock()
        client.post = AsyncMock(return_value=response)
        with ExitStack() as stack:
            for name, value in {
                'build_system_prompt': AsyncMock(return_value='core'),
                'get_standing_memory_blocks': AsyncMock(return_value=[]),
                'get_identity_presets': AsyncMock(return_value={}),
                'get_http_client': AsyncMock(return_value=client),
                '_record_token_usage': AsyncMock(),
            }.items():
                stack.enter_context(patch.object(main, name, value))
            self.assertEqual('干净的摘要', await main._generate_handoff_summary(
                messages, runtime=RUNTIME, max_input_chars=0))
        self.assert_clean_transcript(client.post.await_args.kwargs['json']['messages'][1]['content'])
        self.assertEqual(before, messages)
