import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import main

class QQNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_visibility_tracks_connection(self):
        original=main.BUILTIN_NOTIFICATION_TOOLS[:]
        try:
            for enabled in (True, False):
                async def load(provider='imessage'):
                    return {'enabled':enabled,'allowed_users':['owner']} if provider=='qq' else {'enabled':False}
                with patch.object(main.bot_connections.database,'DATABASE_URL','test'), patch.object(main.bot_connections,'load',load):
                    await main.refresh_notification_tools()
                self.assertEqual([t['name'] for t in main.BUILTIN_NOTIFICATION_TOOLS],['send_qq_notification'] if enabled else [])
                self.assertTrue(main.is_builtin_tool('send_qq_notification'))
        finally:
            main.BUILTIN_NOTIFICATION_TOOLS[:]=original

    async def test_delivery_bound_to_runtime_and_errors_are_not_success(self):
        client=MagicMock(post=AsyncMock())
        for code,ok,expected in [(200,True,'QQ notification delivered'),(403,False,'Error:'),(200,False,'Error:')]:
            client.post.return_value=MagicMock(status_code=code,json=lambda:{'ok':ok})
            with patch.object(main.bot_connections.database,'DATABASE_URL','test'),patch.object(main.bot_connections,'load',AsyncMock(return_value={'enabled':True,'allowed_users':['owner']})),patch.object(main.qq_connections.runtime,'endpoint',AsyncMock(return_value=('http://127.0.0.1:1234/notify','secret'))),patch.object(main,'get_http_client',AsyncMock(return_value=client)):
                result=await main.dispatch_tool_call('send_qq_notification',{'text':'hello','recipient':'other'})
            self.assertTrue(result.startswith(expected))
            self.assertEqual(client.post.await_args.kwargs['json'],{'text':'hello'})

    async def test_disabled_or_invalid_never_sends(self):
        with patch.object(main.bot_connections.database,'DATABASE_URL','test'),patch.object(main.bot_connections,'load',AsyncMock(return_value={'enabled':False})),patch.object(main,'get_http_client',AsyncMock()) as client:
            for text in ('hello','',None,'x'*12001):
                result=await main.dispatch_tool_call('send_qq_notification',{'text':text})
                self.assertTrue(result.startswith('Error:'))
            client.assert_not_awaited()
