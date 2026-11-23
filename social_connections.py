"""Dashboard-owned Feishu and Weixin setup; credentials stay on the server."""
import asyncio
import re
import secrets
import time
from typing import Literal
from uuid import UUID
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import bot_connections as store
from bot_runtime_tools import installation_error, learn_gateway_port
from social_runtime import runtimes

Provider = Literal['feishu', 'weixin']
router = APIRouter(prefix='/api/bot-connections')

def defaults(provider):
    return {'enabled': False, 'feishu_domain': 'feishu', 'app_id': '', 'app_secret': '', 'bot_token': '', 'bot_id': '',
            'base_url': 'https://ilinkai.weixin.qq.com', 'allowed_users': [], 'setup_until': 0,
            'time_enabled': True, 'debounce_seconds': 30, 'revision': secrets.token_hex(16),
            'gateway_token': f'ash_bot_{provider}:' + secrets.token_urlsafe(32)}

def public(config):
    return {key: config.get(key, default) for key, default in {
        'enabled': False, 'feishu_domain': 'feishu', 'app_id': '', 'bot_id': '', 'time_enabled': True, 'debounce_seconds': 30
    }.items()} | {'owner_bound': bool(config.get('allowed_users')), 'app_secret_configured': bool(config.get('app_secret'))}

def fail(message, status=400):
    return JSONResponse(status_code=status, content={'error': message})

def feishu_error(code):
    if not isinstance(code,str): return ''
    known={
        'feishu_endpoint_platform_1000040345':'平台拒绝长连接请求（1000040345）；请检查飞书 / Lark 选择，并重新填写同一应用的 App ID 和 App Secret 后保存',
        'feishu_endpoint_dns':'无法解析长连接服务地址（DNS）',
        'feishu_endpoint_timeout':'获取长连接地址超时',
        'feishu_endpoint_network':'获取长连接地址时网络连接失败',
        'feishu_endpoint_invalid':'平台返回的长连接地址无效',
        'feishu_endpoint_failed':'获取长连接地址失败',
        'feishu_ws_handshake_failed':'已获取连接地址，但 WebSocket 握手失败',
        'feishu_ws_handshake_timeout':'已获取连接地址，但 WebSocket 握手超时（15 秒）',
    }
    if code in known: return known[code]
    match=re.fullmatch(r'feishu_endpoint_(platform|http)_(-?[0-9]{1,16})',code)
    if match:
        label='平台错误码' if match[1]=='platform' else 'HTTP'
        return f'获取长连接地址失败（{label} {match[2]}）'
    return ''

async def body(request):
    import json
    raw=await request.body()
    if len(raw)>8192: raise ValueError()
    data=json.loads(raw or b'{}')
    if not isinstance(data,dict): raise ValueError()
    return data

def weixin_base(value):
    url=urlsplit(value)
    if (url.scheme!='https' or not url.hostname or not (url.hostname=='ilinkai.weixin.qq.com' or url.hostname.endswith('.ilinkai.weixin.qq.com'))
        or url.username or url.password or url.port not in (None,443) or url.path not in ('','/') or url.query or url.fragment):
        raise ValueError()
    return 'https://' + url.hostname

@router.get('/{provider}')
async def get_config(provider: Provider):
    config=await store.load(provider=provider)
    return {'connection': public(config or defaults(provider)), 'saved': bool(config and (config.get('app_id') or config.get('bot_token')))}

@router.put('/{provider}')
async def update(provider: Provider, request: Request):
    try:
        data=await body(request)
        allowed={'enabled','time_enabled','debounce_seconds'} | ({'app_id','app_secret','feishu_domain'} if provider=='feishu' else set())
        if not data or set(data)-allowed: raise ValueError()
        if 'feishu_domain' in data and data['feishu_domain'] not in ('feishu','lark'): raise ValueError()
        for key in ('enabled','time_enabled'):
            if key in data and type(data[key]) is not bool: raise ValueError()
        if 'debounce_seconds' in data and (type(data['debounce_seconds']) is not int or not 0<=data['debounce_seconds']<=300): raise ValueError()
        for key in ('app_id','app_secret'):
            if key in data and (not isinstance(data[key],str) or len(data[key])>2000 or any(ord(c)<32 for c in data[key])): raise ValueError()
        if 'app_id' in data and not re.fullmatch(r'cli_[0-9a-fA-F]{16}',data['app_id']): raise ValueError()
    except (ValueError,TypeError): return fail('请检查连接设置')
    async with store.managed_update() as conn:
        config=await store.load(conn,provider=provider) or defaults(provider)
        app_changed='app_id' in data and data['app_id']!=config.get('app_id')
        domain_changed='feishu_domain' in data and data['feishu_domain']!=config.get('feishu_domain','feishu')
        if app_changed: config['app_secret']=''
        if app_changed or domain_changed:
            config.update(allowed_users=[],setup_session='',setup_until=0)
        if not data.get('app_secret'): data.pop('app_secret',None)
        config.update(data)
        if provider=='feishu' and (not config.get('app_id') or not config.get('app_secret')): return fail('请填写 App ID 和 App Secret')
        if provider=='weixin' and not config.get('bot_token'): return fail('请先扫码连接微信',409)
        learn_gateway_port(config,request)
        config['revision']=secrets.token_hex(16)
        await store.save(config,conn,provider=provider)
    runtimes[provider].wakeup.set()
    return {'connection':public(config),'saved':True}

@router.post('/{provider}/check')
async def check(provider: Provider):
    config=await store.load(provider=provider)
    state=await runtimes[provider].status(config)
    codes={'connection_failed':('连接失败，请检查飞书 / Lark 选择、凭据及平台配置' if provider=='feishu' else '连接失败，请检查网络或重新扫码'),'transport_unavailable':'连接已中断，请重连',
           'session_expired':'微信登录已失效，请重新扫码','gateway_unavailable':'Ash 暂时无法回复',
           'send_failed':'平台未接受消息，请检查应用权限', 'owner_unbound':'请先绑定聊天账号'}
    detail=state.get('error')
    return {'status':state.get('status','error'),'error':installation_error(provider,detail) or (feishu_error(detail) if provider=='feishu' else '') or codes.get(detail,'')}

@router.post('/{provider}/reconnect')
async def reconnect(provider: Provider, request: Request):
    async with store.managed_update() as conn:
        config=await store.load(conn,provider=provider)
        if not config or not (config.get('app_secret') if provider=='feishu' else config.get('bot_token')): return fail('请先完成连接设置',409)
        learn_gateway_port(config,request)
        config.update(enabled=True,revision=secrets.token_hex(16))
        await store.save(config,conn,provider=provider)
    runtimes[provider].wakeup.set()
    return {'status':'connecting'}

@router.post('/{provider}/setup')
async def start_setup(provider: Provider, request: Request):
    async with store.managed_update() as conn:
        config=await store.load(conn,provider=provider) or defaults(provider)
        if provider=='feishu' and not config.get('app_secret'): return fail('先保存应用凭据，再绑定账号',409)
        learn_gateway_port(config,request)
        # Feishu needs its event connection during pairing. No unbound messages reach Ash.
        config.update(setup_until=time.time()+600,revision=secrets.token_hex(16),setup_session='')
        await store.save(config,conn,provider=provider)
    runtime=runtimes[provider]; runtime.wakeup.set()
    try:
        async with asyncio.timeout(15):
            while True:
                info=runtime.read_info()
                if installation_error(provider,info.get('error')): return fail(installation_error(provider,info.get('error')),503)
                if info.get('port') and info.get('revision')==config['revision']: break
                await asyncio.sleep(.1)
            result=await runtime.request('POST','/setup',{})
            session=str(UUID(result['id']))
        async with store.managed_update() as conn:
            current=await store.load(conn,provider=provider)
            if not current or current['revision']!=config['revision']: return fail('设置已变化，请重试',409)
            current['setup_session']=session
            await store.save(current,conn,provider=provider)
        return {'id':session,'code':result.get('code',''),'image':result.get('image',''),'status':result.get('status','waiting')}
    except (TimeoutError,RuntimeError,httpx.HTTPError,ValueError,KeyError): return fail('暂时无法开始连接，请重试',503)

@router.post('/{provider}/setup/{session}/check')
async def check_setup(provider: Provider, session: UUID, request: Request):
    config=await store.load(provider=provider)
    if not config or config.get('setup_session')!=str(session): return {'status':'expired'}
    try:
        data=await body(request)
        code=data.get('verify_code','')
        if not isinstance(code,str) or (code and not re.fullmatch(r'[0-9]{4,12}',code)): return fail('请输入手机上显示的验证码')
        result=await runtimes[provider].request('POST','/setup/'+str(session),{'verify_code':code})
    except (ValueError,RuntimeError,httpx.HTTPError): return fail('连接中断，请重新开始',503)
    if result.get('status')!='authorized':
        status=result.get('status')
        return {'status':status if status in ('creating','waiting','scanned','need_verifycode','expired','failed') else 'failed',
                'image':result.get('image',''),'code':result.get('code','')}
    try:
        owner=result['owner']
        if not isinstance(owner,str) or not owner or len(owner)>256 or any(ord(c)<32 for c in owner): raise ValueError()
        fields={'allowed_users':[owner]}
        if provider=='weixin':
            for key in ('bot_token','bot_id'):
                value=result[key]
                if not isinstance(value,str) or not value or len(value)>4096 or any(ord(c)<32 for c in value): raise ValueError()
                fields[key]=value
            fields['base_url']=weixin_base(result['base_url'])
    except (KeyError,ValueError,TypeError): return fail('授权信息无效，请重试')
    async with store.managed_update() as conn:
        current=await store.load(conn,provider=provider)
        if not current or current.get('setup_session')!=str(session): return {'status':'expired'}
        current.update(fields,enabled=True,setup_until=0,setup_session='',revision=secrets.token_hex(16))
        await store.save(current,conn,provider=provider)
    runtimes[provider].wakeup.set()
    return {'status':'authorized','connection':public(current)}

@router.delete('/{provider}/setup/{session}')
async def cancel_setup(provider: Provider, session: UUID):
    async with store.managed_update() as conn:
        config=await store.load(conn,provider=provider)
        if config and config.get('setup_session')==str(session):
            config.update(setup_session='',setup_until=0,revision=secrets.token_hex(16))
            await store.save(config,conn,provider=provider)
    try: await runtimes[provider].request('DELETE','/setup/'+str(session))
    except (RuntimeError,httpx.HTTPError): pass
    runtimes[provider].wakeup.set()
    return {'status':'cancelled'}
