"""Dashboard-owned transport connections. Credentials never enter exports or public responses."""
import json
from contextlib import asynccontextmanager
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

import database
from photon_runtime import runtime
from bot_runtime_tools import installation_error, learn_gateway_port

router = APIRouter(prefix="/api/bot-connections")


async def init_table():
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""CREATE TABLE IF NOT EXISTS bot_connections (
            id TEXT PRIMARY KEY, config JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")


async def load(connection=None, provider="imessage"):
    if connection is not None:
        row = await connection.fetchrow("SELECT config FROM bot_connections WHERE id = $1", provider)
        return database._json_object(row["config"]) if row else None
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT config FROM bot_connections WHERE id = $1", provider)
    return database._json_object(row["config"]) if row else None


async def save(config, connection, provider="imessage"):
    await connection.execute("""INSERT INTO bot_connections (id, config) VALUES ($1, $2::jsonb)
            ON CONFLICT (id) DO UPDATE SET config = EXCLUDED.config, updated_at = NOW()""",
            provider, json.dumps(config, ensure_ascii=False))


@asynccontextmanager
async def managed_update():
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        # Serialize Dashboard updates across workers.
        await conn.execute("SELECT pg_advisory_lock(194731, 2)")
        try:
            yield conn
        finally:
            await conn.execute("SELECT pg_advisory_unlock(194731, 2)")


def defaults():
    return {"enabled": False, "project_id": "", "project_secret": "", "home_user": "", "allowed_users": [],
            "gateway_token": "", "time_enabled": True, "debounce_seconds": 30, "revision": ""}


SECRET_FIELDS = {"project_secret", "gateway_token"}


def public(config):
    allowed = {"enabled", "project_id", "home_user", "allowed_users", "time_enabled", "debounce_seconds"}
    return {**{k: v for k, v in config.items() if k in allowed},
            "project_secret_configured": bool(config.get("project_secret"))}


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool = True
    project_id: str = Field(default="", max_length=300)
    project_secret: str = Field(default="", max_length=2000)
    home_user: str = Field(default="", max_length=200)
    allowed_users: list[str] = Field(default_factory=list, max_length=50)
    time_enabled: StrictBool = True
    debounce_seconds: int = Field(default=30, ge=0, le=300, strict=True)


def merged_config(data, previous):
    config = {**defaults(), **(previous or {})}
    values = data.model_dump()
    if not values["project_secret"].strip():
        values["project_secret"] = config.get("project_secret", "")
    for key in ("project_id", "project_secret", "home_user"):
        values[key] = values[key].strip()
        if any(ord(c) < 32 for c in values[key]):
            raise ValueError("连接信息不能包含控制字符")
    values["allowed_users"] = list(dict.fromkeys(v.strip().lower() for v in values["allowed_users"] if v.strip()))
    if not values["allowed_users"] and values["home_user"]:
        values["allowed_users"] = [values["home_user"].lower()]
    if any(len(v) > 200 or any(ord(c) < 32 for c in v) for v in values["allowed_users"]):
        raise ValueError("接收对象格式不正确")
    if values["enabled"] and not all(values.get(key) for key in ("project_id", "project_secret", "home_user", "allowed_users")):
        raise ValueError("启用前请填写 Photon 项目 ID、项目密钥、通知对象和允许聊天的对象")
    return {**config, **values, "gateway_token": config.get("gateway_token") or "ash_bot_" + secrets.token_urlsafe(32),
            "revision": secrets.token_hex(16)}


def remote_status(data):
    return {"status": str(data.get("status", "unknown"))[:40],
            "error": installation_error("imessage", data.get("error")) or {"connection_failed": "Photon 连接失败，请检查项目凭据后重连",
                      "stream_ended": "Photon 连接已断开，请重连",
                      "transport_unavailable": "iMessage 连接暂不可用，请重连"}.get(data.get("error"), "")}


async def authorize(token):
    if not token.startswith("ash_bot_"):
        return False
    provider = next((name for name in ('qq', 'feishu', 'weixin') if token.startswith(f'ash_bot_{name}:')), 'imessage')
    config = await load(provider=provider) if provider != 'imessage' else await load()
    return bool(config and config.get("enabled") and config.get("gateway_token")
                and secrets.compare_digest(token, config["gateway_token"]))


async def notification_config(legacy_url, legacy_secret):
    config = await load()
    if config is None:
        return legacy_url, legacy_secret
    return await runtime.endpoint(config) if config.get("enabled") else ("", "")


# Add providers here as their built-in transports become available. The Dashboard
# renders both the connection list and the picker from this catalog.
PROVIDERS = [
    {"id": "imessage", "name": "iMessage", "description": "Photon", "available": True, "symbol": "iM"},
    {"id": "qq", "name": "QQ", "description": "官方 Bot", "available": True, "symbol": "QQ"},
    {"id": "weixin", "name": "微信", "description": "扫码连接", "available": True, "symbol": "微"},
    {"id": "feishu", "name": "飞书", "description": "应用机器人", "available": True, "symbol": "飞"},
]


@router.get("")
async def list_connections():
    config = await load()
    connections = [{"id": "imessage", "provider": "imessage", "name": "iMessage",
                    "account": config.get("home_user", ""), "enabled": bool(config.get("enabled"))}] if config is not None else []
    qq = await load(provider="qq")
    if qq and qq.get("app_id"):
        connections.append({"id": "qq", "provider": "qq", "name": "QQ", "account": qq["app_id"], "enabled": bool(qq.get("enabled"))})
    for provider, name in [('feishu', '飞书'), ('weixin', '微信')]:
        config = await load(provider=provider)
        if config and (config.get('app_id') or config.get('bot_id')):
            connections.append({'id': provider, 'provider': provider, 'name': name,
                'account': config.get('app_id') or config.get('bot_id'), 'enabled': bool(config.get('enabled'))})
    return {"providers": PROVIDERS, "connections": connections}


@router.get("/imessage")
async def get_connection():
    config = await load()
    return {"connection": public(config or defaults()), "saved": config is not None}


@router.put("/imessage")
async def put_connection(request: Request):
    try:
        raw = await request.body()
        if len(raw) > 40000:
            raise ValueError("too large")
        data = ConnectionInput.model_validate_json(raw)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "连接配置格式不正确，请检查输入"})
    async with managed_update() as connection:
        return await apply_connection(data, connection, request)


async def apply_connection(data, connection, request=None):
    try:
        config = merged_config(data, await load(connection))
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    if request is not None:
        learn_gateway_port(config, request)
    await save(config, connection)
    runtime.wakeup.set()
    return {"connection": public(config), "saved": True, "queued": True}


@router.post("/imessage/check")
async def check_connection():
    config = await load()
    return remote_status(await runtime.status(config))


@router.post("/imessage/reconnect")
async def reconnect(request: Request):
    async with managed_update() as connection:
        config = await load(connection)
        if config is None:
            return JSONResponse(status_code=409, content={"error": "请先保存连接配置"})
        config["revision"] = secrets.token_hex(16)
        learn_gateway_port(config, request)
        await save(config, connection)
    runtime.wakeup.set()
    return {"status": "reconnecting" if config["enabled"] else "disabled"}
