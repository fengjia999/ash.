import asyncio
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import main


class HeartbeatSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.wakeup = asyncio.Event()
        self.stack.enter_context(patch.object(main, '_heartbeat_wakeup', self.wakeup))
        self.stack.enter_context(patch.object(main, '_heartbeat_task', None))
        self.stack.enter_context(patch.object(main, 'CONTEXT_MANAGED', True))
        self.stack.enter_context(patch.object(main, 'HEARTBEAT_CHECK_INTERVAL', 3600))
        self.log = self.stack.enter_context(patch('builtins.print'))
        self.settings = {'enabled': False, 'interval_minutes': 45}
        self.conv = {'id': 7}
        self.runtime = {'ready': True, 'route': 'openai', 'route_name': 'OpenAI',
                        'provider_name': 'fixture', 'model': 'fixture-model'}
        old = datetime.now(timezone.utc) - timedelta(minutes=60)
        self.rows = [
            {'id': 1, 'role': 'user', 'created_at': old, 'content': 'private content'},
            {'id': 2, 'role': 'assistant', 'created_at': old, 'content': 'private reply'},
        ]
        for name, result in [('_load_heartbeat_settings', self.settings),
                             ('get_active_conversation', self.conv),
                             ('_heartbeat_runtime', self.runtime),
                             ('get_context_messages', self.rows),
                             ('try_claim_heartbeat', 'fixture-claim'),
                             ('release_heartbeat_claim', None)]:
            self.stack.enter_context(patch.object(main, name, AsyncMock(return_value=result)))
        self.fire = self.stack.enter_context(patch.object(main, '_fire_heartbeat', AsyncMock()))

    async def start_worker(self):
        self.wakeup.set()
        task = asyncio.create_task(main.heartbeat_loop())
        self.stack.enter_context(patch.object(main, '_heartbeat_task', task))
        self.addAsyncCleanup(self.stop_worker, task)
        return task

    async def stop_worker(self, task):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_dashboard_enable_after_disabled_start_dispatches_without_poll_delay(self):
        first_check = asyncio.Event()
        original = main.heartbeat_check

        async def check():
            await original()
            first_check.set()

        self.stack.enter_context(patch.object(main, 'heartbeat_check', check))
        dispatched = asyncio.Event()
        self.fire.side_effect = lambda *args: dispatched.set()
        await self.start_worker()
        await asyncio.wait_for(first_check.wait(), 2)
        self.fire.assert_not_awaited()

        async def save(**values):
            self.settings.update(values)
            return dict(self.settings)

        self.stack.enter_context(patch.object(main, 'save_heartbeat_settings', AsyncMock(side_effect=save)))
        request = MagicMock()
        request.json = AsyncMock(return_value={'enabled': True, 'interval_minutes': 45})
        result = await main.api_update_heartbeat_settings(request)
        self.assertTrue(result['enabled'])
        await asyncio.wait_for(dispatched.wait(), 2)
        self.fire.assert_awaited_once()
        main.release_heartbeat_claim.assert_awaited_once_with(7, 'fixture-claim')
        logs = '\n'.join(str(call) for call in self.log.call_args_list)
        self.assertIn('check enabled=False', logs)
        self.assertIn('settings saved, enabled=True', logs)
        self.assertIn('dispatching conv=7', logs)
        self.assertNotIn('private content', logs)

    async def test_setting_change_during_check_is_not_lost(self):
        entered, finish, again = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = 0

        async def check():
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await finish.wait()
            else:
                again.set()

        self.stack.enter_context(patch.object(main, 'heartbeat_check', check))
        await self.start_worker()
        await asyncio.wait_for(entered.wait(), 2)
        main._wake_heartbeat({'enabled': True, 'interval_minutes': 45})
        finish.set()
        await asyncio.wait_for(again.wait(), 2)
        self.assertEqual(calls, 2)

    async def test_periodic_poll_picks_up_changes_from_another_worker(self):
        self.stack.enter_context(patch.object(main, 'HEARTBEAT_CHECK_INTERVAL', 1))
        first_check, dispatched = asyncio.Event(), asyncio.Event()
        original = main.heartbeat_check

        async def check():
            await original()
            first_check.set()

        self.stack.enter_context(patch.object(main, 'heartbeat_check', check))
        self.fire.side_effect = lambda *args: dispatched.set()
        await self.start_worker()
        await asyncio.wait_for(first_check.wait(), 2)
        self.settings['enabled'] = True
        # Another process cannot signal this process's event; polling must remain.
        await asyncio.wait_for(dispatched.wait(), 5)
        self.fire.assert_awaited_once()

    async def test_failed_save_does_not_wake_worker(self):
        self.stack.enter_context(patch.object(main, 'save_heartbeat_settings', AsyncMock(side_effect=RuntimeError('offline'))))
        request = MagicMock()
        request.json = AsyncMock(return_value={'enabled': True, 'interval_minutes': 45})
        with self.assertRaises(RuntimeError):
            await main.api_update_heartbeat_settings(request)
        self.assertFalse(self.wakeup.is_set())

    async def test_unfinished_tool_round_stays_blocked_with_explanation(self):
        self.settings['enabled'] = True
        self.rows[-1].update(role='tool', kind='tool_event')
        await main.heartbeat_check()
        self.fire.assert_not_awaited()
        logs = '\n'.join(str(call) for call in self.log.call_args_list)
        self.assertIn('conversation turn unfinished', logs)
        self.assertIn('last_role=tool', logs)
        self.assertNotIn('private reply', logs)

    async def test_recent_assistant_reply_still_waits(self):
        self.settings['enabled'] = True
        self.rows[-1]['created_at'] = datetime.now(timezone.utc)
        await main.heartbeat_check()
        self.fire.assert_not_awaited()
        self.assertIn('last reply=', str(self.log.call_args_list))

    async def test_claim_conflict_does_not_dispatch_and_is_logged(self):
        self.settings['enabled'] = True
        main.try_claim_heartbeat.return_value = None
        await main.heartbeat_check()
        self.fire.assert_not_awaited()
        self.assertIn('claim held or conversation changed', str(self.log.call_args_list))
