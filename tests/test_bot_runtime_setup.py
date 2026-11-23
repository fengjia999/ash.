import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import bot_runtime_tools as runtime

spec=importlib.util.spec_from_file_location('ash_setup_bots',Path(__file__).resolve().parents[1]/'scripts/setup_bots.py')
setup=importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class BotRuntimeSetupTests(unittest.TestCase):
    def test_manifest_finds_node_even_when_service_path_cannot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            node=root/'node';node.write_text('#!/bin/sh\n');node.chmod(0o755)
            state=root/'bots.json';state.write_text(json.dumps({'node':str(node)}))
            with patch.object(runtime,'STATE_FILE',state),patch.object(runtime.shutil,'which',return_value=None):
                self.assertEqual(runtime.find_node(),str(node))
                state.write_text('{broken')
                self.assertIsNone(runtime.find_node())
            env=runtime.node_environment(str(node))
            self.assertEqual(env['PATH'].split(os.pathsep)[0],str(root))

    def test_missing_node_build_and_dependencies_have_distinct_actionable_errors(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(runtime,'ROOT',Path(directory)):
            entry=Path(directory)/'integrations/photon/dist/index.js'
            self.assertEqual(runtime.missing_component('imessage',entry,None),'node_missing')
            self.assertEqual(runtime.missing_component('imessage',entry,'/bin/node'),'component_not_built')
            entry.parent.mkdir(parents=True);entry.write_text('')
            self.assertEqual(runtime.missing_component('imessage',entry,'/bin/node'),'dependencies_missing')
            for package in ['@spectrum-ts/core','@spectrum-ts/imessage','sharp']:
                target=Path(directory)/'integrations/photon/node_modules'/package/'package.json'
                target.parent.mkdir(parents=True);target.write_text('{}')
            self.assertEqual(runtime.missing_component('imessage',entry,'/bin/node'),'')
            self.assertIn('python3 scripts/setup_bots.py',runtime.installation_error('imessage','dependencies_missing'))

    def test_bad_official_archive_checksum_is_rejected_before_unpacking(self):
        releases=json.dumps([{'version':'v22.23.4'}]).encode()
        sums=('0'*64+'  node-v22.23.4-linux-x64.tar.xz\n').encode()
        with patch.object(setup,'platform_suffix',return_value='linux-x64'),patch.object(setup,'fetch',side_effect=[releases,sums,b'corrupt archive']):
            with self.assertRaisesRegex(RuntimeError,'校验失败'):
                setup.download_node()

    def test_archive_cannot_escape_its_destination_through_paths_or_links(self):
        for name,link in [('node-v22-linux-x64/../../escape',''),('node-v22-linux-x64/bin/node','../../../escape')]:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as directory:
                stream=io.BytesIO()
                with tarfile.open(fileobj=stream,mode='w') as archive:
                    member=tarfile.TarInfo(name)
                    if link:member.type=tarfile.SYMTYPE;member.linkname=link
                    archive.addfile(member)
                stream.seek(0)
                with tarfile.open(fileobj=stream,mode='r') as archive,self.assertRaises(RuntimeError):
                    setup.extract_checked(archive,Path(directory),'node-v22-linux-x64')

    def test_install_builds_all_components_and_records_node_only_after_success(self):
        calls=[]
        with patch.object(setup,'find_node',return_value='/opt/node/bin/node'),patch.object(setup,'version_of',return_value=(22,23,4)),patch.object(
            setup.shutil,'which',return_value='/opt/node/bin/npm'),patch.object(setup,'command',side_effect=lambda args,env:calls.append((args,env))),patch.object(
            setup,'check',return_value=True),patch.object(setup,'save_node') as save:
            setup.install()
        self.assertEqual(len(calls),5)
        self.assertIn('--include=dev',calls[0][0])
        self.assertEqual(calls[1][0][1:3],['run','build'])
        self.assertIn('--omit=dev',calls[2][0])
        self.assertIn('integrations/qq',calls[3][0])
        self.assertIn('--ignore-scripts',calls[3][0])
        self.assertIn('integrations/social',calls[4][0])
        self.assertIn('--ignore-scripts',calls[4][0])
        self.assertTrue(all(env['PATH'].startswith('/opt/node/bin:') for _,env in calls))
        save.assert_called_once_with('/opt/node/bin/node')

    def test_failed_install_does_not_overwrite_runtime_discovery(self):
        with patch.object(setup,'find_node',return_value='/bin/node'),patch.object(setup,'version_of',return_value=(22,0,0)),patch.object(
            setup.shutil,'which',return_value='/bin/npm'),patch.object(setup,'command',side_effect=RuntimeError('failed build')),patch.object(setup,'save_node') as save:
            with self.assertRaises(RuntimeError):setup.install()
        save.assert_not_called()

    def test_check_only_never_downloads_or_saves_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name,entry in [('photon','dist/index.js'),('qq','index.mjs'),('social','index.mjs')]:
                path=root/'integrations'/name/entry;path.parent.mkdir(parents=True);path.write_text('')
            with patch.object(setup,'ROOT',root),patch.object(setup,'version_of',return_value=(22,0,0)),patch.object(
                setup.subprocess,'run',return_value=MagicMock(returncode=0)),patch.object(setup,'fetch') as fetch,patch.object(setup,'save_node') as save:
                self.assertTrue(setup.check('/bin/node'))
            fetch.assert_not_called();save.assert_not_called()

    def test_bot_callback_uses_the_real_vps_listener_port(self):
        from types import SimpleNamespace
        from photon_runtime import PhotonRuntime
        from qq_runtime import QQRuntime
        config={'enabled':False,'project_id':'','project_secret':'','home_user':'','app_id':'','app_secret':'','allowed_users':[],'gateway_token':'test'}
        runtime.learn_gateway_port(config,SimpleNamespace(scope={'server':('127.0.0.1',9123),'headers':[(b'host',b'public.example:443')]}))
        self.assertEqual(PhotonRuntime.payload(config)['gatewayUrl'],'http://127.0.0.1:9123')
        self.assertEqual(QQRuntime.payload(config)['gatewayUrl'],'http://127.0.0.1:9123')
