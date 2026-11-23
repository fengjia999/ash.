import json
import unittest
from unittest.mock import patch
import main


class ThinkingDiagnosticsTests(unittest.TestCase):
    def test_openrouter_effective_request_log_has_no_private_data(self):
        with patch.object(main, 'THINKING_MODE', 'auto'), patch.object(main, 'THINKING_EFFORT', 'high'), patch.object(main, 'PROMPT_CACHE_ENABLED', False):
            body = main.to_anthropic_body({'model':'claude-opus-4-6', 'messages':[
                {'role':'user','content':'PRIVATE_CHAT'}]}, resolved_tools=[])
            body['system'] = 'PRIVATE_PROMPT'
            prepared = main._anthropic_body_for_request(body, body['messages'], stream=True, api_url='https://openrouter.ai/api/v1/messages')
        with patch('builtins.print') as log:
            main._log_anthropic_thinking_request(prepared, 'https://openrouter.ai/api/v1/messages?key=PRIVATE_KEY', 7, 1)
        text = log.call_args.args[0]
        data = json.loads(text.split(' ', 1)[1])
        self.assertEqual(data['thinking_type'], 'adaptive')
        self.assertEqual(data['effort'], 'high')
        self.assertEqual(data['model'], 'anthropic/claude-opus-4.6')
        self.assertNotIn('PRIVATE', text)

    def test_response_log_distinguishes_absent_redacted_and_forwarded_thinking(self):
        for blocks, forwarded, counts in (
            ([{'type':'text','text':'PRIVATE'}], 0, (0, 0, 0)),
            ([{'type':'redacted_thinking','data':'PRIVATE'}], 0, (0, 1, 0)),
            ([{'type':'thinking','thinking':'PRIVATE'}], 7, (1, 0, 7)),
        ):
            with patch('builtins.print') as log:
                main._log_anthropic_thinking_response(blocks, 7, 1, 'test-model', forwarded)
            text = log.call_args.args[0]
            data = json.loads(text.split(' ', 1)[1])
            self.assertEqual(tuple(data[k] for k in ('thinking_blocks','redacted_thinking_blocks','forwarded_thinking_chars')), counts)
            self.assertNotIn('PRIVATE', text)
