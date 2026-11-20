"""Publish the verified ProxyClient tray update to the guest catalog."""
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
MANIFEST = Path('Distribution/proxy-tray-import.json')
CATALOG = Path('Distribution/catalog.json')
STAGING = Path(os.environ['RUNNER_TEMP']) / 'ProxyTrayRelease'

def run(*args):
    return subprocess.check_output(args, text=True, encoding='utf-8')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def stage(spec, package, archive):
    STAGING.mkdir(exist_ok=True)
    with archive.open('wb') as output:
        for oid in spec['Blobs']:
            if not re.fullmatch(r'[0-9a-f]{40}', oid):
                raise ValueError('Invalid package object ID')
            blob = json.loads(run('gh', 'api', f'repos/{REPO}/git/blobs/{oid}'))
            if blob['encoding'] != 'base64' or blob['sha'] != oid:
                raise ValueError('Unexpected package object')
            output.write(base64.b64decode(''.join(blob['content'].split()), validate=True))
    data = archive.read_bytes()
    if digest(data) != package['Sha256']:
        raise ValueError('ZIP checksum mismatch')
    audit_zip(data)
    with ZipFile(archive) as source:
        if source.read('HostVersion.txt').decode('ascii').strip() != package['Version']:
            raise ValueError('ZIP version mismatch')
        source.extractall(STAGING / 'test')

def publish(package, archive):
    data = archive.read_bytes()
    if digest(data) != package['Sha256']:
        raise ValueError('ZIP changed after verification')
    tag = package['Tag']
    if subprocess.run(['gh', 'release', 'view', tag, '--repo', REPO], capture_output=True).returncode:
        print(run('gh', 'release', 'create', tag, str(archive), '--repo', REPO,
                  '--target', os.environ['GITHUB_SHA'], '--title', package['Name'] + ' v' + package['Version'],
                  '--notes', 'Standard taskbar minimize. Close to tray, one-click restore and explicit exit.',
                  '--latest=false'), flush=True)
    with urllib.request.urlopen(f'https://github.com/{REPO}/releases/download/{tag}/{archive.name}', timeout=90) as response:
        if digest(response.read(len(data) + 1)) != package['Sha256']:
            raise ValueError('Public release checksum mismatch')
    print('Verified anonymous release download and SHA-256', flush=True)
    run('git', 'pull', '--rebase', 'origin', 'main')
    catalog = json.loads(CATALOG.read_text(encoding='utf-8-sig'))
    index = next(i for i, current in enumerate(catalog['Apps']) if current['Id'] == package['Id'])
    current = catalog['Apps'][index]
    if current['Version'] not in ('0.2.0.7', package['Version']):
        raise ValueError('Catalog points to a different ProxyClient version')
    catalog['Apps'][index] = package
    CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    run('git', 'config', 'user.name', 'github-actions[bot]')
    run('git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
    run('git', 'add', str(CATALOG))
    if subprocess.run(['git', 'diff', '--cached', '--quiet']).returncode:
        print(run('git', 'commit', '-m', 'Offer ProxyClient 0.2.0.8 in the guest launcher'), flush=True)
        print(run('git', 'push', 'origin', 'HEAD:main'), flush=True)

if __name__ == '__main__':
    spec = json.loads(MANIFEST.read_text(encoding='utf-8'))
    package = spec['Package']
    if package['Id'] != 'calamus-proxy' or package['Repository'] != REPO or package['Version'] != '0.2.0.8':
        raise ValueError('Unexpected package')
    if package['Asset'] != 'CalamusProxyClient_v0.2.0.8.zip' or package['Tag'] != 'calamus-proxy-v0.2.0.8':
        raise ValueError('Unexpected release destination')
    archive = STAGING / package['Asset']
    if sys.argv[1:] == ['stage']:
        stage(spec, package, archive)
    elif sys.argv[1:] == ['publish']:
        publish(package, archive)
    else:
        raise ValueError('Expected stage or publish')
