"""Official QQ Bot authorization. Returned QQ secrets never pass through the browser."""
import asyncio
import re
import secrets
import time
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import httpx

import bot_connections as store
from qq_runtime import runtime
from bot_runtime_tools import installation_error, learn_gateway_port

router = APIRouter(prefix="/api/bot-connections/qq")


def defaults():
    return {"enabled": False, "app_id": "", "app_secret": "", "allowed_users": [], "setup_until": 0,
            "gateway_token": "ash_bot_qq:" + secrets.token_urlsafe(32), "revision": secrets.token_hex(16),
            "time_enabled": True, "debounce_seconds": 30}


def public(config):
    return {"enabled": bool(config.get("enabled")), "app_id": config.get("app_id", ""),
            "owner_bound": bool(config.get("allowed_users")),
            "time_enabled": config.get("time_enabled", True), "debounce_seconds": config.get("debounce_seconds", 30)}


def fail(message, status=400):
    return JSONResponse(status_code=status, content={"error": message})


async def request_data(request):
    body = await request.body()
    if len(body) > 4096:
        raise ValueError()
    import json
    data = json.loads(body or b"{}")
    if not isinstance(data, dict):
        raise ValueError()
    return data


@router.get("")
async def get_config():
    config = await store.load(provider="qq")
    return {"connection": public(config or {}), "saved": bool(config and config.get("app_id"))}


@router.post("/qr")
async def start_qr(request: Request):
    try:
        data = await request_data(request)
        expected = data.get("app_id", "")
        if not isinstance(expected, str) or (expected and not re.fullmatch(r"[0-9]{5,20}", expected)):
            raise ValueError()
    except (ValueError, TypeError):
        return fail("请输入正确的机器人 AppID")
    async with store.managed_update() as conn:
        config = await store.load(conn, provider="qq") or defaults()
        learn_gateway_port(config, request)
        config.update(setup_until=time.time() + 600, revision=secrets.token_hex(16), qr_expected_id=expected, qr_session_id="")
        await store.save(config, conn, provider="qq")
    runtime.wakeup.set()
    try:
        async with asyncio.timeout(12):
            while True:
                info = runtime.read_info()
                if installation_error("qq", info.get("error")):
                    return fail(installation_error("qq", info.get("error")), 503)
                if info.get("revision") == config["revision"] and info.get("port"):
                    break
                await asyncio.sleep(.1)
            result = await runtime.request("POST", "/qr", {"expectedAppId": expected})
        session = str(UUID(result["id"]))
    except (TimeoutError, RuntimeError, httpx.HTTPError, ValueError, KeyError):
        return fail("暂时无法生成二维码，请重试", 503)
    async with store.managed_update() as conn:
        current = await store.load(conn, provider="qq")
        if not current or current["revision"] != config["revision"]:
            return fail("连接设置已变化，请重新扫码", 409)
        current["qr_session_id"] = session
        await store.save(current, conn, provider="qq")
    return {"id": session, "status": "creating"}


@router.post("/qr/{session_id}/check")
async def poll_qr(session_id: UUID):
    config = await store.load(provider="qq")
    if not config or config.get("qr_session_id") != str(session_id):
        return {"status": "expired"}
    try:
        data = await runtime.request("GET", "/qr/" + str(session_id))
    except (RuntimeError, httpx.HTTPError, ValueError):
        return fail("扫码会话已中断，请重新生成二维码", 503)
    if data.get("status") == "authorized":
        # The SDK can return more than one credential; choose the exact requested bot.
        candidates = data.get("credentials", [])
        if not isinstance(candidates, list):
            candidates = []
        expected = config.get("qr_expected_id", "")
        matches = [item for item in candidates if isinstance(item, dict) and (not expected or str(item.get("appId")) == expected)]
        if not matches:
            return {"status": "mismatch", "error": "扫码授权的 Bot 与填写的 AppID 不一致"}
        credential = matches[0]
        app_id, secret, owner = (credential.get(key) for key in ("appId", "appSecret", "userOpenid"))
        if (not isinstance(app_id, str) or not re.fullmatch(r"[0-9]{5,20}", app_id)
                or not isinstance(secret, str) or not secret or len(secret) > 2000
                or not isinstance(owner, str) or not owner or len(owner) > 200
                or any(ord(c) < 32 for c in secret + owner)):
            return {"status": "failed", "error": "授权信息不完整，请重新扫码"}
        async with store.managed_update() as conn:
            current = await store.load(conn, provider="qq")
            if not current or current.get("qr_session_id") != str(session_id):
                return {"status": "expired"}
            current.update(app_id=app_id, app_secret=secret, allowed_users=[owner], enabled=True,
                           setup_until=0, revision=secrets.token_hex(16), qr_session_id="")
            await store.save(current, conn, provider="qq")
        runtime.wakeup.set()
        try:
            await runtime.request("DELETE", "/qr/" + str(session_id))
        except (RuntimeError, httpx.HTTPError):
            pass
        return {"status": "authorized", "connection": public(current)}
    status = data.get("status")
    image = data.get("image", "")
    return {"status": status if status in {"creating", "waiting", "failed", "expired"} else "failed",
            "image": image if isinstance(image, str) and image.startswith("data:image/png;base64,") and len(image) < 100000 else ""}


@router.delete("/qr/{session_id}")
async def cancel_qr(session_id: UUID):
    async with store.managed_update() as conn:
        config = await store.load(conn, provider="qq")
        if config and config.get("qr_session_id") == str(session_id):
            config.update(qr_session_id="", setup_until=0, revision=secrets.token_hex(16))
            await store.save(config, conn, provider="qq")
    try:
        await runtime.request("DELETE", "/qr/" + str(session_id))
    except (RuntimeError, httpx.HTTPError):
        pass
    runtime.wakeup.set()
    return {"status": "cancelled"}


@router.post("/check")
async def check():
    config = await store.load(provider="qq")
    state = await runtime.status(config)
    codes = {"connection_failed": "连接失败，请重新授权", "transport_unavailable": "连接已中断，请重连",
             "runtime_missing": "请更新 Ash 的 QQ 组件", "gateway_unavailable": "Ash 暂时没有回复，请稍后重试"}
    status = state.get("status")
    return {"status": status if status in {"connected", "connecting", "disabled", "error"} else "connecting",
            "error": installation_error("qq", state.get("error")) or codes.get(state.get("error"), "")}


@router.post("/reconnect")
async def reconnect(request: Request):
    async with store.managed_update() as conn:
        config = await store.load(conn, provider="qq")
        if not config or not config.get("app_id"):
            return fail("请先添加 QQ Bot", 409)
        learn_gateway_port(config, request)
        config.update(enabled=True, revision=secrets.token_hex(16))
        await store.save(config, conn, provider="qq")
    runtime.wakeup.set()
    return {"status": "connecting"}


@router.put("")
async def update(request: Request):
    try:
        data = await request_data(request)
        if not data or set(data) - {"enabled", "time_enabled", "debounce_seconds"}:
            raise ValueError()
        for key in ("enabled", "time_enabled"):
            if key in data and type(data[key]) is not bool:
                raise ValueError()
        if "debounce_seconds" in data and (type(data["debounce_seconds"]) is not int or not 0 <= data["debounce_seconds"] <= 300):
            raise ValueError()
    except (ValueError, TypeError):
        return fail("连接设置格式不正确")
    async with store.managed_update() as conn:
        config = await store.load(conn, provider="qq")
        if not config or not config.get("app_id"):
            return fail("请先添加 QQ Bot", 409)
        learn_gateway_port(config, request)
        config.update(data)
        config["revision"] = secrets.token_hex(16)
        await store.save(config, conn, provider="qq")
    runtime.wakeup.set()
    return {"connection": public(config), "saved": True}
