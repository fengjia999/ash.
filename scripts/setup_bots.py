#!/usr/bin/env python3
"""Install Ash's bundled Bot components on a native VPS, without root or Bot secrets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bot_runtime_tools import find_node, STATE_FILE

MIN_NODE = (22, 0, 0)


def version_of(node):
    try:
        value = subprocess.check_output([str(node), '--version'], text=True, timeout=10).strip()
        match = re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)', value)
        return tuple(map(int, match.groups())) if match else (0, 0, 0)
    except (OSError, subprocess.SubprocessError):
        return (0, 0, 0)


def platform_suffix():
    system = {'Linux': 'linux', 'Darwin': 'darwin'}.get(platform.system())
    arch = {'x86_64': 'x64', 'amd64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine().lower())
    if not system or not arch:
        raise RuntimeError('请先安装 Node.js 22 或更新版本，再重新执行此命令')
    if system == 'linux' and platform.libc_ver()[0] == 'musl':
        raise RuntimeError('此系统使用 musl，请先用系统包管理器安装 Node.js 22 或更新版本')
    return f'{system}-{arch}'


def fetch(url, limit):
    with urlopen(url, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError('下载文件超过预期大小，安装已停止')
    return data


def extract_checked(archive, target, prefix):
    base = target.resolve()
    package_root = base / prefix
    for member in archive.getmembers():
        path = base / member.name
        if not path.resolve().is_relative_to(package_root) or member.name.split('/')[0] != prefix:
            raise RuntimeError('Node 安装包包含无效路径')
        if member.isdev() or member.isfifo():
            raise RuntimeError('Node 安装包包含无效文件')
        if member.issym() or member.islnk():
            link = (path.parent / member.linkname) if member.issym() else base / member.linkname
            if not link.resolve().is_relative_to(package_root):
                raise RuntimeError('Node 安装包包含无效链接')
    if hasattr(tarfile, 'data_filter'):
        archive.extractall(target, filter='data')
    else:
        archive.extractall(target)


def download_node():
    suffix = platform_suffix()
    releases = json.loads(fetch('https://nodejs.org/dist/index.json', 2 * 1024 * 1024))
    versions = [item['version'] for item in releases if isinstance(item, dict)
                and re.fullmatch(r'v22\.\d+\.\d+', str(item.get('version', '')))]
    if not versions:
        raise RuntimeError('无法获取 Node 22 的发行版本')
    version = max(versions, key=lambda value: tuple(map(int, value[1:].split('.'))))
    prefix = f'node-{version}-{suffix}'
    name = prefix + '.tar.xz'
    base = f'https://nodejs.org/dist/{version}/'
    checksums = fetch(base + 'SHASUMS256.txt', 200000).decode()
    expected = next((line.split()[0] for line in checksums.splitlines()
                     if len(line.split()) == 2 and line.split()[1].lstrip('*') == name), '')
    if not re.fullmatch(r'[0-9a-fA-F]{64}', expected):
        raise RuntimeError('无法验证 Node 安装包的校验值')
    print(f'下载 Node.js {version}（安装到 Ash 目录，不修改系统 Node）', flush=True)
    content = fetch(base + name, 150 * 1024 * 1024)
    if hashlib.sha256(content).hexdigest().lower() != expected.lower():
        raise RuntimeError('Node 安装包校验失败')
    runtime = ROOT / '.runtime'
    runtime.mkdir(exist_ok=True)
    destination = runtime / prefix
    if not destination.exists():
        with tempfile.TemporaryDirectory(prefix='node-install-', dir=runtime) as temporary:
            path = Path(temporary) / name
            path.write_bytes(content)
            with tarfile.open(path, mode='r:xz') as archive:
                extract_checked(archive, Path(temporary), prefix)
            (Path(temporary) / prefix).rename(destination)
    node = destination / 'bin' / 'node'
    if version_of(node) < MIN_NODE:
        raise RuntimeError('下载的 Node 无法在此 VPS 运行，请检查系统版本')
    return str(node)


def save_node(node):
    STATE_FILE.parent.mkdir(exist_ok=True)
    target = STATE_FILE.with_suffix('.tmp')
    target.write_text(json.dumps({'node': str(Path(node).absolute())}) + '\n')
    target.replace(STATE_FILE)


def command(args, env):
    print('运行：' + ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=ROOT, env=env, check=True)


def check(node):
    okay = True
    version = version_of(node) if node else (0, 0, 0)
    if version < MIN_NODE:
        print('缺少可用的 Node.js 22+。运行：python3 scripts/setup_bots.py')
        return False
    print(f'Node.js {".".join(map(str, version))}：{node}', flush=True)
    checks = [('iMessage', 'photon', ['@spectrum-ts/core', '@spectrum-ts/imessage', 'sharp']),
              ('QQ', 'qq', ['@tencent-connect/qqbot-connector', '@tencent-connect/qqbot-nodejs', 'qrcode']),
              ('飞书 / 微信', 'social', ['@larksuiteoapi/node-sdk', 'qrcode'])]
    for label, folder, packages in checks:
        directory = ROOT / 'integrations' / folder
        entry = directory / ('dist/index.js' if folder == 'photon' else 'index.mjs')
        if not entry.is_file():
            print(f'{label}：尚未构建')
            okay = False
            continue
        code = ';'.join('await import(' + json.dumps(package) + ')' for package in packages)
        result = subprocess.run([str(node), '--input-type=module', '-e', code], cwd=directory,
                                capture_output=True, text=True, timeout=30)
        ready = result.returncode == 0
        print(f'{label}：' + ('已就绪' if ready else '依赖不可用，请重新执行安装命令'))
        okay = okay and ready
    return okay


def install():
    node = find_node()
    if not node or version_of(node) < MIN_NODE:
        node = download_node()
    env = os.environ.copy()
    env['PATH'] = str(Path(node).parent) + os.pathsep + env.get('PATH', '')
    npm = shutil.which('npm', path=env['PATH'])
    if not npm:
        raise RuntimeError('此 Node 安装不包含 npm，请安装包含 npm 的 Node.js 后重试')
    # Resolve npm with the selected Node even when systemd has a different PATH.
    command([npm, 'ci', '--include=dev', '--prefix', 'integrations/photon', '--no-audit', '--no-fund'], env)
    command([npm, 'run', 'build', '--prefix', 'integrations/photon'], env)
    command([npm, 'prune', '--omit=dev', '--prefix', 'integrations/photon', '--no-audit', '--no-fund'], env)
    command([npm, 'ci', '--omit=dev', '--ignore-scripts', '--prefix', 'integrations/qq', '--no-audit', '--no-fund'], env)
    command([npm, 'ci', '--omit=dev', '--ignore-scripts', '--prefix', 'integrations/social', '--no-audit', '--no-fund'], env)
    if not check(node):
        raise RuntimeError('组件检查未通过，请根据上方结果修复后重试')
    save_node(node)
    print('安装完成。重启 Ash 后，在 Dashboard 的 Bot 页面重连。连接配置无需重填。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='仅检查，不安装或下载')
    args = parser.parse_args()
    try:
        if args.check:
            return 0 if check(find_node()) else 1
        install()
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print('安装未完成：' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
