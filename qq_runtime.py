import os
import time

from photon_runtime import PhotonRuntime, ROOT


class QQRuntime(PhotonRuntime):
    def __init__(self):
        super().__init__("qq")

    def entrypoint(self):
        return ROOT / "integrations/qq/index.mjs"

    async def load_config(self):
        from bot_connections import load
        return await load(provider="qq")

    def should_run(self, config):
        return bool(config and (config.get("enabled") or config.get("setup_until", 0) > time.time()))

    @staticmethod
    def payload(config):
        return {"enabled": config["enabled"], "appId": config.get("app_id", ""),
                "appSecret": config.get("app_secret", ""), "allowedUsers": config.get("allowed_users", []),
                "gatewayUrl": "http://127.0.0.1:" + str(int(config.get("gateway_port") or os.getenv("PORT", "8080"))),
                "gatewaySecret": config["gateway_token"], "timeEnabled": config.get("time_enabled", True),
                "debounceSeconds": config.get("debounce_seconds", 30)}


runtime = QQRuntime()
