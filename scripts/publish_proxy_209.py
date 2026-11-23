"""Build and publish the staged ProxyClient source for Calamus Launcher."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
from zipfile import ZipFile

from publish_launcher import audit_zip

REPO = 'CalamusClaro/Calamus-Launcher-Guest'
VERSION = '0.2.0.9'
TAG = 'calamus-proxy-v' + VERSION
ASSET = 'CalamusProxyClient_v' + VERSION + '.zip'
CATALOG = Path('Distribution/catalog.json')
WORK = Path(os.environ['RUNNER_TEMP']) / 'Proxy209'
MANIFEST = Path('Distribution/proxy-209-import.json')

def run(*args):
    return subprocess.check_output(args, text=True, encoding='utf-8')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def stage():
    spec = json.loads(MANIFEST.read_text(encoding='utf-8'))
    WORK.mkdir(exist_ok=True)
    archive = WORK / 'source.zip'
    with archive.open('wb') as output:
        for oid in spec['Blobs']:
            if not re.fullmatch(r'[0-9a-f]{40}', oid):
                raise ValueError('Invalid source object')
            blob = json.loads(run('gh', 'api', f'repos/{REPO}/git/blobs/{oid}'))
            if blob['sha'] != oid or blob['encoding'] != 'base64':
                raise ValueError('Unexpected source object')
            output.write(base64.b64decode(''.join(blob['content'].split()), validate=True))
    data = archive.read_bytes()
    if digest(data) != spec['Sha256']:
        raise ValueError('Source checksum mismatch')
    audit_zip(data)
    with ZipFile(archive) as source:
        source.extractall(WORK / 'source')

def publish():
    archive = WORK / ASSET
    data = archive.read_bytes()
    audit_zip(data)
    with ZipFile(archive) as package:
        if package.testzip() or package.read('HostVersion.txt').decode('ascii').strip() != VERSION:
            raise ValueError('Invalid package')
        package.getinfo('CalamusProxyClient.exe')
        package.getinfo('TrayWifi.ico')
    sha = digest(data)
    if subprocess.run(['gh', 'release', 'view', TAG, '--repo', REPO], capture_output=True).returncode:
        print(run('gh', 'release', 'create', TAG, str(archive), '--repo', REPO, '--target',
                  os.environ['GITHUB_SHA'], '--title', 'Calamus ProxyClient v' + VERSION,
                  '--notes', 'Discord DPI starts with ProxyClient and can be toggled in the Wi-Fi tray menu.',
                  '--latest=false'), flush=True)
    url = f'https://github.com/{REPO}/releases/download/{TAG}/{ASSET}'
    with urllib.request.urlopen(url, timeout=90) as response:
        if digest(response.read(len(data) + 1)) != sha:
            raise ValueError('Public release checksum mismatch')
    print('Verified anonymous ZIP download:', sha, flush=True)
    run('git', 'pull', '--rebase', 'origin', 'main')
    catalog = json.loads(CATALOG.read_text(encoding='utf-8-sig'))
    current = next(item for item in catalog['Apps'] if item['Id'] == 'calamus-proxy')
    if current['Version'] not in ('0.2.0.8', VERSION):
        raise ValueError('Catalog version changed')
    current.update(Version=VERSION, Repository=REPO, Tag=TAG, Asset=ASSET, Sha256=sha)
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    run('git', 'config', 'user.name', 'github-actions[bot]')
    run('git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
    run('git', 'add', str(CATALOG))
    if subprocess.run(['git', 'diff', '--cached', '--quiet']).returncode:
        print(run('git', 'commit', '-m', 'Offer ProxyClient 0.2.0.9 in Calamus Launcher'), flush=True)
        print(run('git', 'push', 'origin', 'HEAD:main'), flush=True)

if __name__ == '__main__':
    if sys.argv[1:] == ['stage']:
        stage()
    elif sys.argv[1:] == ['publish']:
        publish()
    else:
        raise ValueError('Expected stage or publish')
