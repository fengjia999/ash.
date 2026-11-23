"""Local Bot runtime discovery shared by the VPS installer and supervisors."""
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / '.runtime' / 'bots.json'


def find_node():
    try:
        value = json.loads(STATE_FILE.read_text())
        node = value.get('node', '')
        if isinstance(node, str) and Path(node).is_file() and os.access(node, os.X_OK):
            return node
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return shutil.which('node')


def node_environment(node):
    env = {key: value for key, value in os.environ.items()
           if key in {'PATH', 'LANG', 'TZ', 'HOME', 'NODE_EXTRA_CA_CERTS'}}
    env['PATH'] = str(Path(node).parent) + os.pathsep + env.get('PATH', '')
    return env


def missing_component(provider, entry, node):
    if not node:
        return 'node_missing'
    if not entry.is_file():
        return 'component_not_built'
    folder = ROOT / 'integrations' / ('photon' if provider == 'imessage' else 'social' if provider in ('feishu', 'weixin') else provider)
    packages = ['@spectrum-ts/core', '@spectrum-ts/imessage', 'sharp'] if provider == 'imessage' else [
        '@tencent-connect/qqbot-nodejs', '@tencent-connect/qqbot-connector', 'qrcode']
    if provider in ('feishu', 'weixin'):
        packages = ['@larksuiteoapi/node-sdk', 'qrcode']
    if any(not (folder / 'node_modules' / package / 'package.json').is_file() for package in packages):
        return 'dependencies_missing'
    return ''


def installation_error(provider, code):
    names = {'imessage': 'iMessage', 'qq': 'QQ', 'feishu': '飞书', 'weixin': '微信'}
    reasons = {'node_missing': '缺少 Node.js', 'component_not_built': '组件尚未构建',
               'dependencies_missing': '组件依赖尚未安装', 'runtime_missing': '组件尚未安装'}
    if code not in reasons:
        return ''
    return f"{names.get(provider, provider)} {reasons[code]}。请在 Ash 目录运行：python3 scripts/setup_bots.py"


def learn_gateway_port(config, request):
    # The ASGI listener, not the public Host header or reverse proxy's port.
    server = request.scope.get('server')
    if isinstance(server, (tuple, list)) and len(server) == 2:
        port = server[1]
        if type(port) is int and 0 < port < 65536:
            config['gateway_port'] = port
