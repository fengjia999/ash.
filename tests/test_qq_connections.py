import copy
import json
import time
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import bot_connections as store
import qq_connections as qq
from qq_runtime import QQRuntime
from test_gateway_auth import make_request


@asynccontextmanager
async def transaction():
    yield object()


class QQConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_settings_save_without_replacing_credentials_or_enabling_connection(self):
        config={**qq.defaults(),'app_id':'12345678','app_secret':'keep-secret','allowed_users':['owner']}
        original_token=config['gateway_token']
        write=AsyncMock()
        request=make_request('/api/bot-connections/qq',method='PUT',body=b'{"time_enabled":false,"debounce_seconds":12}')
        with patch.object(store,'managed_update',transaction),patch.object(store,'load',AsyncMock(return_value=config)),patch.object(store,'save',write):
            result=await qq.update(request)
        saved=write.await_args.args[0]
        self.assertFalse(saved['enabled'])
        self.assertFalse(saved['time_enabled'])
        self.assertEqual(saved['debounce_seconds'],12)
        self.assertEqual(saved['app_secret'],'keep-secret')
        self.assertEqual(saved['gateway_token'],original_token)
        self.assertEqual(QQRuntime.payload(saved)['debounceSeconds'],12)
        self.assertFalse(QQRuntime.payload(saved)['timeEnabled'])
        self.assertNotIn('keep-secret',json.dumps(result))
        self.assertEqual(result['connection']['debounce_seconds'],12)
        with patch.object(store,'load',AsyncMock(return_value=saved)):
            reloaded=await qq.get_config()
        self.assertEqual(reloaded['connection'],result['connection'])

    async def test_reply_settings_reject_invalid_values_before_saving(self):
        for data in ({'debounce_seconds':True},{'debounce_seconds':-1},{'debounce_seconds':301},
                     {'debounce_seconds':1.5},{'time_enabled':1},{'app_secret':'oops'},{}):
            request=make_request('/api/bot-connections/qq',method='PUT',body=json.dumps(data).encode())
            with patch.object(store,'save',AsyncMock()) as write:
                result=await qq.update(request)
            self.assertEqual(result.status_code,400)
            write.assert_not_awaited()

    async def test_existing_id_still_requires_explicit_official_authorization(self):
        for value in ('', 'abc', '123'):
            if not value:
                continue
            request=make_request('/api/bot-connections/qq/qr',method='POST',body=json.dumps({'app_id':value}).encode())
            with patch.object(qq.runtime,'request',AsyncMock()) as remote:
                result=await qq.start_qr(request)
            self.assertEqual(result.status_code,400)
            remote.assert_not_awaited()

    async def test_start_qr_stores_expected_id_and_only_returns_session_id(self):
        saved={}
        session=str(uuid4())
        async def write(config,*args,**kwargs): saved.clear();saved.update(copy.deepcopy(config))
        with patch.object(store,'managed_update',transaction),patch.object(store,'load',AsyncMock(side_effect=lambda *a,**k:copy.deepcopy(saved) or None)),patch.object(store,'save',AsyncMock(side_effect=write)),patch.object(
            qq.runtime,'read_info',side_effect=lambda:{'port':1234,'revision':saved.get('revision')}),patch.object(qq.runtime,'request',AsyncMock(return_value={'id':session})):
            result=await qq.start_qr(make_request('/api/bot-connections/qq/qr',method='POST',body=b'{"app_id":"12345678"}'))
        self.assertEqual(result,{'id':session,'status':'creating'})
        self.assertEqual(saved['qr_expected_id'],'12345678')
        self.assertEqual(saved['qr_session_id'],session)
        self.assertFalse(saved['enabled'])
        self.assertNotIn('gateway_token',result)

    async def test_approved_credentials_are_saved_server_side_for_the_scanner_only(self):
        session=uuid4()
        config={**qq.defaults(),'qr_session_id':str(session),'qr_expected_id':'12345678'}
        credentials=[{'appId':'12345678','appSecret':'never-to-browser','userOpenid':'scanner-owner'}]
        write=AsyncMock()
        with patch.object(store,'managed_update',transaction),patch.object(store,'load',AsyncMock(return_value=config)),patch.object(store,'save',write),patch.object(
            qq.runtime,'request',AsyncMock(return_value={'status':'authorized','credentials':credentials})):
            result=await qq.poll_qr(session)
        stored=write.await_args.args[0]
        self.assertTrue(stored['enabled'])
        self.assertEqual(stored['allowed_users'],['scanner-owner'])
        self.assertEqual(stored['app_secret'],'never-to-browser')
        self.assertEqual(result['connection']['app_id'],'12345678')
        self.assertNotIn('never-to-browser',json.dumps(result))
        self.assertNotIn('scanner-owner',json.dumps(result))
        self.assertNotIn(stored['gateway_token'],json.dumps(result))

    async def test_wrong_bot_missing_owner_and_cancelled_sessions_never_activate(self):
        session=uuid4()
        config={**qq.defaults(),'qr_session_id':str(session),'qr_expected_id':'12345678'}
        for credentials,status in [([{'appId':'87654321','appSecret':'x','userOpenid':'owner'}],'mismatch'),
                                   ([{'appId':'12345678','appSecret':'x'}],'failed')]:
            with patch.object(store,'load',AsyncMock(return_value=config)),patch.object(store,'save',AsyncMock()) as write,patch.object(
                qq.runtime,'request',AsyncMock(return_value={'status':'authorized','credentials':credentials})):
                self.assertEqual((await qq.poll_qr(session))['status'],status)
            write.assert_not_awaited()
        with patch.object(store,'load',AsyncMock(return_value={**config,'qr_session_id':''})),patch.object(qq.runtime,'request',AsyncMock()) as remote:
            self.assertEqual(await qq.poll_qr(session),{'status':'expired'})
            remote.assert_not_awaited()

    async def test_qq_token_does_not_authenticate_against_imessage_configuration(self):
        config={**qq.defaults(),'enabled':True}
        with patch.object(store,'load',AsyncMock(return_value=config)) as load:
            self.assertTrue(await store.authorize(config['gateway_token']))
        load.assert_awaited_once_with(provider='qq')

    def test_qr_setup_runtime_is_temporary_and_stays_in_ash(self):
        runtime=QQRuntime()
        config={**qq.defaults(),'setup_until':time.time()+30}
        self.assertTrue(runtime.should_run(config))
        self.assertFalse(runtime.should_run({**config,'setup_until':0}))
        payload=runtime.payload(config)
        self.assertTrue(payload['gatewayUrl'].startswith('http://127.0.0.1:'))
        self.assertNotIn('bridge_url',payload)
