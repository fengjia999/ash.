"""Own the bundled Photon transport inside Ash; no separately deployed service."""
import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile

import httpx

import database
from bot_runtime_tools import find_node, node_environment, missing_component

ROOT = Path(__file__).resolve().parent


class PhotonRuntime:
    def __init__(self, provider="imessage"):
        self.provider = provider
        namespace = hashlib.sha256(database.DATABASE_URL.encode()).hexdigest()[:16]
        self.directory = Path(tempfile.gettempdir()) / f"ash-{provider}-{os.getuid()}-{namespace}"
        self.process = None
        self.reader = None
        self.task = None
        self.lock = None
        self.info = {}
        self.applied_revision = None
        self.wakeup = asyncio.Event()

    def read_info(self):
        try:
            value = json.loads((self.directory / "runtime.json").read_text())
            os.kill(int(value["pid"]), 0)
            return value
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def publish(self, **changes):
        self.info.update(changes)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = self.directory / "runtime.json"
        temporary = target.with_suffix(".tmp")
        with open(temporary, "w", opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
            json.dump(self.info, stream)
        temporary.replace(target)

    def start(self):
        self.task = asyncio.create_task(self.supervise())

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.stop_child()
        if self.lock:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
            self.lock = None

    async def stop_child(self):
        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.process.wait(), 30)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.reader:
            await asyncio.gather(self.reader, return_exceptions=True)
        self.process = None
        self.reader = None

    async def request(self, method, path, payload=None):
        info = self.read_info()
        if not info.get("port") or not info.get("token"):
            raise RuntimeError("transport not ready")
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            response = await client.request(method, f"http://127.0.0.1:{int(info['port'])}" + path,
                headers={"Authorization": "Bearer " + info["token"]}, json=payload)
        response.raise_for_status()
        return response.json()

    async def endpoint(self, config):
        info = self.read_info()
        if info.get("revision") != config.get("revision") or not info.get("port"):
            return "", ""
        return f"http://127.0.0.1:{int(info['port'])}/notify", info.get("token", "")

    async def status(self, config):
        if not config or not config.get("enabled"):
            return {"status": "disabled", "error": ""}
        info = self.read_info()
        if info.get("error"):
            return {"status": "error", "error": info["error"]}
        if not info.get("port") or info.get("revision") != config.get("revision"):
            return {"status": "connecting", "error": ""}
        try:
            data = await self.request("GET", "/api/connection")
            return {"status": data.get("status", "connecting"), "error": data.get("error", "")}
        except (httpx.HTTPError, RuntimeError, ValueError):
            return {"status": "error", "error": "transport_unavailable"}

    @staticmethod
    def payload(config):
        port = int(config.get("gateway_port") or os.getenv("PORT", "8080"))
        return {"enabled": config["enabled"], "projectId": config["project_id"],
                "projectSecret": config["project_secret"], "homeUser": config["home_user"],
                "allowedUsers": config["allowed_users"], "gatewayUrl": f"http://127.0.0.1:{port}",
                "gatewaySecret": config["gateway_token"]}

    def entrypoint(self):
        return ROOT / "integrations/photon/dist/index.js"

    async def load_config(self):
        from bot_connections import load
        return await load()

    def should_run(self, config):
        return bool(config and config.get("enabled"))

    async def launch(self, config):
        node = find_node()
        entry = self.entrypoint()
        problem = missing_component(self.provider, entry, node)
        if problem:
            self.publish(pid=os.getpid(), port=None, error=problem, revision=config["revision"])
            return
        self.publish(pid=os.getpid(), port=None, error="", revision=None, token=secrets.token_urlsafe(32))
        bootstrap = {"connection": self.payload(config), "managementToken": self.info["token"],
                     "settings": {"model": "", "timeEnabled": config["time_enabled"], "debounceSeconds": config["debounce_seconds"]}}
        self.process = await asyncio.create_subprocess_exec(node, str(entry),
            cwd=entry.parent.parent, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=node_environment(node))
        self.reader = asyncio.create_task(self.read_output())
        self.process.stdin.write(json.dumps(bootstrap).encode())
        await self.process.stdin.drain()
        self.process.stdin.close()
        self.applied_revision = config["revision"]
        self.publish(revision=config["revision"])

    async def read_output(self):
        async for line in self.process.stdout:
            if line.startswith(b"[transport-ready]"):
                try:
                    value = json.loads(line.removeprefix(b"[transport-ready]"))
                    self.publish(port=int(value["port"]), error="")
                except (ValueError, KeyError):
                    self.publish(error="transport_unavailable")
            # The SDK may embed credentials in exceptions. Raw child output is never
            # forwarded into Ash logs or the Dashboard; status uses fixed error codes.

    async def supervise(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock = (self.directory / "owner.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            self.lock = None
            return  # Another local Ash worker owns this container's transport.
        while True:
            try:
                config = await self.load_config()
                if self.process and self.process.returncode is not None:
                    await self.stop_child()
                    self.publish(pid=os.getpid(), port=None, error="transport_unavailable")
                    # Do not automatically replay after a crash; reconnect is explicit.
                if self.process and not self.should_run(config):
                    await self.stop_child()
                    self.publish(pid=os.getpid(), port=None, error="")
                if self.should_run(config) and not self.process and self.applied_revision != config["revision"]:
                    await self.launch(config)
                elif config and self.process and self.applied_revision != config["revision"] and self.read_info().get("port"):
                    await self.request("PUT", "/api/settings", {"model": "", "timeEnabled": config["time_enabled"], "debounceSeconds": config["debounce_seconds"]})
                    await self.request("PUT", "/api/connection", self.payload(config))
                    self.applied_revision = config["revision"]
                    self.publish(revision=config["revision"], error="")
                self.wakeup.clear()
                try:
                    await asyncio.wait_for(self.wakeup.wait(), 1)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception:
                self.publish(pid=os.getpid(), error="transport_unavailable")
                await asyncio.sleep(1)


runtime = PhotonRuntime()
