import asyncio
from pathlib import Path
import shutil
import tempfile
import unittest

import httpx
from qq_runtime import QQRuntime
from photon_runtime import ROOT
from qq_connections import defaults


@unittest.skipUnless(shutil.which('node') and (ROOT/'integrations/qq/node_modules/@tencent-connect/qqbot-nodejs/package.json').is_file(), 'install bundled QQ dependencies first')
class QQRuntimeSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_bundled_qq_component_starts_privately_without_logging_in(self):
        runtime=QQRuntime()
        with tempfile.TemporaryDirectory() as directory:
            runtime.directory=Path(directory)
            try:
                await runtime.launch(defaults())
                async with asyncio.timeout(12):
                    while not runtime.read_info().get('port'):
                        if runtime.process.returncode is not None:
                            self.fail('QQ runtime exited before ready')
                        await asyncio.sleep(.05)
                self.assertEqual(await runtime.request('GET','/api/connection'),{'status':'disabled','error':''})
                with self.assertRaises(httpx.HTTPStatusError) as rejected:
                    await runtime.request('POST','/notify',{'text':'must not send'})
                self.assertEqual(rejected.exception.response.status_code,409)
                self.assertEqual(await runtime.request('GET','/api/settings'),{'timeEnabled':True,'debounceSeconds':30})
                await runtime.request('PUT','/api/settings',{'model':'','timeEnabled':False,'debounceSeconds':12})
                self.assertEqual(await runtime.request('GET','/api/settings'),{'timeEnabled':False,'debounceSeconds':12})
                info=runtime.read_info()
                async with httpx.AsyncClient(trust_env=False) as client:
                    denied=await client.post(f"http://127.0.0.1:{info['port']}/qr",json={})
                self.assertEqual(denied.status_code,401)
                self.assertNotIn('app_secret',info)
            finally:
                await runtime.stop_child()
            self.assertIsNone(runtime.process)
