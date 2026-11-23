import asyncio
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
import main
from photon_runtime import PhotonRuntime, ROOT


class PhotonRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_transport_configuration_uses_loopback_and_dedicated_credential(self):
        config = {"enabled":True,"project_id":"project","project_secret":"secret","home_user":"user@example.test",
                  "allowed_users":["user@example.test"],"gateway_token":"ash_bot_secret"}
        with patch.dict(os.environ,{"PORT":"9123"}):
            payload = PhotonRuntime.payload(config)
        self.assertEqual(payload["gatewayUrl"],"http://127.0.0.1:9123")
        self.assertEqual(payload["gatewaySecret"],"ash_bot_secret")
        self.assertNotIn("bridge_url",payload)

    async def test_status_is_disabled_without_starting_a_process(self):
        runtime = PhotonRuntime()
        self.assertEqual(await runtime.status(None),{"status":"disabled","error":""})
        self.assertIsNone(runtime.process)
        with patch.object(runtime,"read_info",return_value={"pid":os.getpid(),"port":1234,"token":"x","revision":"old"}):
            self.assertEqual(await runtime.endpoint({"revision":"new"}),("",""))

    def test_native_actions_can_join_existing_conversation_without_mutating_its_snapshot(self):
        stored = [{"name":"search_diary"},{"name":"imessage_react_to_current_message"}]
        live = [{"type":"function","function":{"name":"imessage_reply_to_current_message","parameters":{"type":"object"}}}]
        tools,names = main.imessage_request_tools(stored,{"imessage_react_to_current_message"},live)
        self.assertEqual([tool["name"] for tool in tools],["search_diary","imessage_reply_to_current_message"])
        self.assertEqual(names,{"imessage_reply_to_current_message"})
        self.assertEqual(stored[1]["name"],"imessage_react_to_current_message")
        web_tools,web_names = main.imessage_request_tools(tools,names,[])
        self.assertEqual(web_tools,[{"name":"search_diary"}])
        self.assertEqual(web_names,set())

    @unittest.skipUnless(shutil.which("node") and (ROOT / "integrations/photon/dist/index.js").is_file(), "build bundled transport first")
    async def test_bundled_process_boots_without_photon_env_and_only_listens_on_loopback(self):
        runtime = PhotonRuntime()
        with tempfile.TemporaryDirectory() as directory:
            runtime.directory = Path(directory)
            config = {"enabled":False,"project_id":"","project_secret":"","home_user":"","allowed_users":[],
                      "gateway_token":"ash_bot_test","time_enabled":True,"debounce_seconds":0,"revision":"smoke"}
            try:
                await runtime.launch(config)
                async with asyncio.timeout(15):
                    while not runtime.read_info().get("port"):
                        if runtime.process.returncode is not None:
                            self.fail("bundled process exited before ready")
                        await asyncio.sleep(.05)
                info = runtime.read_info()
                self.assertNotIn("project_secret",info)
                self.assertEqual(await runtime.request("GET","/api/connection"),{"version":1,"status":"waiting","error":""})
                async with httpx.AsyncClient(trust_env=False) as client:
                    denied = await client.get(f"http://127.0.0.1:{info['port']}/api/connection")
                    self.assertEqual(denied.status_code,401)
                self.assertEqual(await runtime.request("GET","/api/settings"),{"model":"","timeEnabled":True,"debounceSeconds":0})
            finally:
                await runtime.stop_child()
            self.assertIsNone(runtime.process)
