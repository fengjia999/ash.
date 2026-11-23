import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import main


class ChatThinkingTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_validates_and_preserves_effort(self):
        config={'provider':'anthropic','model':'claude-opus-4-6','api_url':'https://example.test/v1','api_key':'secret','thinking_effort':'medium'}
        saved=AsyncMock(side_effect=lambda **kw:kw)
        with patch.object(main,'save_route_settings',saved):
            result=await main.api_update_route_settings(MagicMock(json=AsyncMock(return_value=config)))
        self.assertEqual('medium',result['thinking_effort'])
        saved.assert_awaited_once_with(**config)
        with self.assertRaises(ValueError):
            await main._api_configuration_values({**config,'thinking_effort':'ultra'})

    def test_adaptive_levels_override_disabled_environment(self):
        for effort in ('auto','low','medium','high','max'):
            body={'model':'claude-opus-4-6','max_tokens':8192,'temperature':.5}
            with patch.object(main,'THINKING_MODE','off'):
                main._apply_chat_thinking(body,False,effort)
            self.assertEqual('adaptive',body['thinking']['type'])
            self.assertNotIn('budget_tokens',body['thinking'])
            self.assertNotIn('temperature',body)
            if effort=='auto':self.assertNotIn('output_config',body)
            else:self.assertEqual(effort,body['output_config']['effort'])

    def test_older_claude_uses_budget_and_leaves_reply_room(self):
        for effort,budget in [('low',1024),('medium',4096),('high',8192),('max',16384)]:
            body={'model':'claude-sonnet-4-5','max_tokens':4096}
            main._apply_chat_thinking(body,False,effort)
            self.assertEqual(budget,body['thinking']['budget_tokens'])
            self.assertGreater(body['max_tokens'],budget)

    def test_heartbeat_uses_frozen_chat_effort_after_settings_change(self):
        for level in ('auto','low','medium','high','max'):
            snapshot=main._chat_thinking_snapshot('claude-opus-4-6',False,level,{},'https://example.test/v1/messages')
            heartbeat={'model':'claude-opus-4-6','max_tokens':1024}
            with patch.object(main,'THINKING_EFFORT','high'):
                main._apply_thinking(heartbeat,heartbeat['model'])
            main._restore_heartbeat_thinking(heartbeat,snapshot,False)
            self.assertEqual(snapshot['thinking'],heartbeat['thinking'])
            self.assertEqual(snapshot.get('output_config'),heartbeat.get('output_config'))

    def test_openai_heartbeat_auto_snapshot_does_not_enable_env_reasoning(self):
        snapshot=main._chat_thinking_snapshot('gpt-5.6',True,'auto',{},'https://api.openai.com/v1/chat/completions')
        body={'model':'gpt-5.6','reasoning_effort':'low'}
        main._restore_heartbeat_thinking(body,snapshot,True)
        with patch.object(main,'OPENAI_REASONING',True):
            prepared=main._prepare_openai_chat_body(body,'https://api.openai.com/v1/chat/completions')
        self.assertNotIn('reasoning_effort',prepared)

    def test_openai_auto_ignores_env_without_leaking_internal_fields(self):
        body={'model':'gpt-5.6','messages':[]}
        main._apply_chat_thinking(body,True,'auto')
        with patch.object(main,'OPENAI_REASONING',True):
            prepared=main._prepare_openai_chat_body(body,'https://api.openai.com/v1/chat/completions')
        self.assertNotIn('reasoning_effort',prepared)
        self.assertNotIn('_thinking_effort_setting',prepared)
        main._apply_chat_thinking(body,True,'max')
        self.assertEqual('max',body['reasoning_effort'])
        routed=main._prepare_openai_chat_body(body,'https://openrouter.ai/api/v1/chat/completions')
        self.assertEqual('max',routed['reasoning']['effort'])
        self.assertNotIn('_thinking_effort_setting',routed)
