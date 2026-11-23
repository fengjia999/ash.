import copy
import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import httpx
import social_connections as social
import bot_connections as store
import main
from social_runtime import SocialRuntime
from test_gateway_auth import make_request

@asynccontextmanager
async def transaction():
    yield object()

def request(path='',data=None):
    return make_request('/api/bot-connections/'+path,method='POST',body=json.dumps(data or {}).encode())

class SocialConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_check_reports_safe_stage_details(self):
        for code,expected in [('feishu_endpoint_platform_1000040345','重新填写同一应用'),('feishu_endpoint_platform_1000040343','平台错误码 1000040343'),('feishu_ws_handshake_timeout','WebSocket 握手超时'),('feishu_endpoint_dns','DNS'),('secret-value','')]:
            with patch.object(store,'load',AsyncMock(return_value={})),patch.object(social.runtimes['feishu'],'status',AsyncMock(return_value={'status':'error','error':code})):
                result=await social.check('feishu')
            if expected:self.assertIn(expected,result['error'])
            else:self.assertEqual(result['error'],'')

    async def test_platform_switch_updates_runtime_and_clears_old_binding(self):
        original={**social.defaults('feishu'),'app_id':'cli_0123456789abcdef','app_secret':'private-secret','allowed_users':['owner'],'setup_session':'old','setup_until':123456}
        save=AsyncMock()
        with patch.object(store,'managed_update',transaction),patch.object(store,'load',AsyncMock(return_value=original)),patch.object(store,'save',save):
            result=await social.update('feishu',request(data={'feishu_domain':'lark','app_secret':''}))
        config=save.await_args.args[0]
        self.assertEqual(result['connection']['feishu_domain'],'lark')
        self.assertEqual(config['app_secret'],'private-secret')
        self.assertEqual(config['allowed_users'],[])
        self.assertEqual(config['setup_session'],'')
        self.assertEqual(config['setup_until'],0)
        self.assertEqual(social.runtimes['feishu'].payload(config)['feishuDomain'],'lark')
        self.assertNotIn('private-secret',json.dumps(result))

    async def test_invalid_platform_is_rejected_without_loading_credentials(self):
        with patch.object(store,'load',AsyncMock()) as load:
            for provider,value in [('feishu','https://other.test'),('feishu',None),('weixin','lark')]:
                self.assertEqual((await social.update(provider,request(data={'feishu_domain':value}))).status_code,400)
        load.assert_not_awaited()

    async def test_slow_qr_generation_remains_pending(self):
        session=uuid4()
        with patch.object(store,'load',AsyncMock(return_value={'setup_session':str(session)})),patch.object(social.runtimes['weixin'],'request',AsyncMock(return_value={'status':'creating'})):
            result=await social.check_setup('weixin',session,request())
        self.assertEqual(result['status'],'creating')

    async def test_feishu_save_preserves_secret_and_clears_binding_on_app_change(self):
        original={**social.defaults('feishu'),'app_id':'cli_0123456789abcdef','app_secret':'private-secret','allowed_users':['owner']}
        saved=AsyncMock()
        with patch.object(store,'managed_update',transaction),patch.object(store,'load',AsyncMock(side_effect=lambda *a,**kw:copy.deepcopy(original))),patch.object(store,'save',saved):
            result=await social.update('feishu',request(data={'app_id':original['app_id'],'app_secret':'','enabled':True}))
            self.assertEqual(saved.await_args.args[0]['app_secret'],'private-secret')
            self.assertNotIn('private-secret',json.dumps(result))
            result=await social.update('feishu',request(data={'app_id':'cli_abcdef0123456789','app_secret':'new-secret'}))
            self.assertEqual(saved.await_args.args[0]['allowed_users'],[])
            self.assertNotIn('new-secret',json.dumps(result))

    async def test_confirmed_weixin_login_is_saved_but_credentials_are_not_returned(self):
        session=uuid4();config={**social.defaults('weixin'),'setup_session':str(session)}
        result={'status':'authorized','owner':'owner','bot_id':'bot','bot_token':'private-token','base_url':'https://ilinkai.weixin.qq.com'}
        save=AsyncMock()
        with patch.object(store,'managed_update',transaction),patch.object(store,'load',AsyncMock(return_value=config)),patch.object(store,'save',save),patch.object(social.runtimes['weixin'],'request',AsyncMock(return_value=result)):
            public=await social.check_setup('weixin',session,request())
        self.assertEqual(save.await_args.args[0]['bot_token'],'private-token')
        self.assertTrue(public['connection']['enabled'])
        self.assertNotIn('private-token',json.dumps(public))
        self.assertNotIn('allowed_users',public['connection'])

    async def test_cancelled_setup_and_untrusted_base_never_save_credentials(self):
        session=uuid4()
        with patch.object(store,'load',AsyncMock(return_value={'setup_session':''})),patch.object(social.runtimes['weixin'],'request',AsyncMock()) as remote:
            self.assertEqual(await social.check_setup('weixin',session,request()),{'status':'expired'})
            remote.assert_not_awaited()
        config={**social.defaults('weixin'),'setup_session':str(session)}
        result={'status':'authorized','owner':'owner','bot_id':'bot','bot_token':'secret','base_url':'http://127.0.0.1'}
        with patch.object(store,'load',AsyncMock(return_value=config)),patch.object(store,'save',AsyncMock()) as save,patch.object(social.runtimes['weixin'],'request',AsyncMock(return_value=result)):
            self.assertEqual((await social.check_setup('weixin',session,request())).status_code,400)
            save.assert_not_awaited()

    async def test_start_setup_tracks_session_and_uses_runtime_without_secrets_in_response(self):
        saved={};session=str(uuid4())
        async def save(config,*args,**kwargs):saved.clear();saved.update(copy.deepcopy(config))
        runtime=social.runtimes['weixin']
        with patch.object(store,'managed_update',transaction),patch.object(store,'load',AsyncMock(side_effect=lambda *a,**kw:copy.deepcopy(saved) or None)),patch.object(store,'save',AsyncMock(side_effect=save)),patch.object(runtime,'read_info',side_effect=lambda:{'port':1234,'revision':saved.get('revision')}),patch.object(runtime,'request',AsyncMock(return_value={'id':session,'status':'creating'})):
            result=await social.start_setup('weixin',request())
        self.assertEqual(saved['setup_session'],session)
        self.assertNotIn(saved['gateway_token'],json.dumps(result))
        self.assertTrue(runtime.should_run(saved))
        self.assertTrue(runtime.payload(saved)['setupEnabled'])

    async def test_provider_credentials_are_isolated_and_disabled_tools_disappear(self):
        configs={p:{**social.defaults(p),'enabled':True,'allowed_users':['owner']} for p in ('feishu','weixin')}
        async def load(*args,provider='imessage',**kwargs):return configs.get(provider)
        with patch.object(store,'load',load):
            for provider in configs:self.assertTrue(await store.authorize(configs[provider]['gateway_token']))
            self.assertFalse(await store.authorize('ash_bot_qq:not-the-same-token'))
        old=main.BUILTIN_NOTIFICATION_TOOLS[:]
        try:
            with patch.object(store,'load',load),patch.object(store.database,'DATABASE_URL','test'),patch.object(main,'PHOTON_NOTIFY_URL',''):
                await main.refresh_notification_tools()
                names={tool['name'] for tool in main.BUILTIN_NOTIFICATION_TOOLS}
                self.assertEqual(names,{'send_feishu_notification','send_weixin_notification'})
                configs['weixin']['enabled']=False
                await main.refresh_notification_tools()
                self.assertEqual([t['name'] for t in main.BUILTIN_NOTIFICATION_TOOLS],['send_feishu_notification'])
        finally:main.BUILTIN_NOTIFICATION_TOOLS[:]=old

class SocialRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_disabled_components_boot_without_external_connections(self):
        import asyncio
        for provider in ('feishu','weixin'):
            runtime=SocialRuntime(provider)
            with tempfile.TemporaryDirectory() as folder:
                runtime.directory=Path(folder)
                try:
                    await runtime.launch(social.defaults(provider))
                    async with asyncio.timeout(12):
                        while not runtime.read_info().get('port'):
                            if runtime.process.returncode is not None:self.fail('component exited')
                            await asyncio.sleep(.05)
                    self.assertEqual((await runtime.request('GET','/api/connection'))['status'],'disabled')
                    with self.assertRaises(httpx.HTTPStatusError):await runtime.request('POST','/notify',{'text':'must not send'})
                    with self.assertRaises(httpx.HTTPStatusError):await runtime.request('POST','/setup',{})
                finally:await runtime.stop_child()
