"""Publish only pre-approved clean release ZIPs; no cross-repository credentials."""
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

REPO = 'CalamusClaro/Calamus-Launcher-Guest'
IDS = {'calamus-emoji-studio', 'calamus-capture', 'slayerlog', 'calamus-whisper', 'calamus-emoji-studio', 'calamus-launcher'}

def run(*args):
    result = subprocess.run(args, check=True, capture_output=True, text=True, encoding='utf-8')
    return result.stdout

def digest(data):
    return hashlib.sha256(data).hexdigest()

def audit_zip(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        forbidden = {'github-auth.dpapi', 'access-v1.json', 'state-v2.json', 'state-v3-extras.json', 'subscription.dat', 'nodes.dat', 'chrome-bridge.json', 'runtime.json'}
        for info in archive.infolist():
            name = info.filename.replace('\\', '/')
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or ':' in name or path.name.lower() in forbidden or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe or personal file in release ZIP')
            if path.suffix.lower() == '.dpapi':
                raise ValueError('Personal encrypted data in release ZIP')
            if path.suffix.lower() in {'.cs', '.ps1', '.py', '.json', '.txt', '.md', '.js'} and info.file_size < 2_000_000:
                text = archive.read(info).decode('utf-8', errors='ignore')
                if re.search(r'github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{30,}', text):
                    raise ValueError('Possible credential in release text')

def main():
    manifest = json.loads(Path('Distribution/emoji-import.json').read_text(encoding='utf-8-sig'))
    imports = manifest['Imports']
    ids = [item['Package']['Id'] for item in imports]
    if ids != ['calamus-emoji-studio']:
        raise ValueError('Only Emoji Studio is allowed in this publisher')
    if not all(item.get('ArtifactUrl') for item in imports):
        print('Transfer URLs removed after successful publication. Existing releases remain available; provide fresh approved imports for another publication.', flush=True)
        return
    staging = Path(tempfile.mkdtemp(prefix='CalamusGuest-'))
    for item in imports:
        package = item['Package']
        if package['Repository'] != REPO or not re.fullmatch(r'[A-Za-z0-9._-]+\.zip', package['Asset']) or not re.fullmatch(r'[A-Za-z0-9._-]+', package['Tag']):
            raise ValueError('Invalid target package')
        parsed = urllib.parse.urlsplit(item['ArtifactUrl'])
        if parsed.scheme != 'https' or not parsed.hostname.endswith('.oaiusercontent.com'):
            raise ValueError('Unexpected staging host')
        # No GitHub token is sent to the staging host. These temporary URLs
        # contain only inspected build artefacts and expire after transfer.
        with urllib.request.urlopen(item['ArtifactUrl'], timeout=90) as response:
            wrapper = response.read(1_610_612_737)
        if len(wrapper) > 1_610_612_736:
            raise ValueError('Staging archive exceeds limit')
        if digest(wrapper) != item['ArtifactSha256']:
            raise ValueError('Build artefact checksum mismatch')
        with zipfile.ZipFile(io.BytesIO(wrapper)) as archive:
            data = archive.read(item['ArtifactEntry'])
        if digest(data) != package['Sha256'].lower():
            raise ValueError('Release ZIP checksum mismatch')
        audit_zip(data)
        (staging / package['Asset']).write_bytes(data)
        print('Verified:', package['Name'], package['Version'], flush=True)

    # The approved package passes verification before the first public upload.
    for item in sorted(imports, key=lambda x: x['Package']['Id'] == 'calamus-launcher'):
        package = item['Package']
        tag, asset = package['Tag'], package['Asset']
        exists = subprocess.run(['gh', 'release', 'view', tag, '--repo', REPO], capture_output=True).returncode == 0
        if exists:
            check = staging / ('existing-' + package['Id'])
            check.mkdir()
            run('gh', 'release', 'download', tag, '--repo', REPO, '--pattern', asset, '--dir', str(check))
            if digest((check / asset).read_bytes()) != package['Sha256'].lower():
                raise ValueError('Published release is immutable; use a new version')
        else:
            run('gh', 'release', 'create', tag, str(staging / asset), '--repo', REPO, '--target', os.environ['GITHUB_SHA'], '--title', package['Name'] + ' v' + package['Version'], '--notes', 'Verified clean Windows package for Calamus Launcher. No author credentials or personal data included.', '--latest' if package['Id'] == 'calamus-launcher' else '--latest=false')

    run('git', 'pull', '--rebase', 'origin', 'main')
    catalogue = json.loads(Path('Distribution/catalog.json').read_text(encoding='utf-8-sig'))
    package = imports[0]['Package']
    public_url = 'https://github.com/' + REPO + '/releases/download/' + package['Tag'] + '/' + package['Asset']
    with urllib.request.urlopen(public_url, timeout=90) as response:
        public_bytes = response.read()
    if digest(public_bytes) != package['Sha256'].lower():
        raise ValueError('Anonymous public package verification failed')
    print('Anonymous release download and checksum passed', flush=True)
    found = [i for i, app in enumerate(catalogue['Apps']) if app['Id'] == 'calamus-emoji-studio']
    if len(found) != 1:
        raise ValueError('Expected exactly one existing guest Emoji Studio record')
    catalogue['Apps'][found[0]] = package
    manifest['Imports'][0].pop('ArtifactUrl', None)
    Path('Distribution/emoji-import.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    Path('Distribution/catalog.json').write_text(json.dumps(catalogue, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    run('git', 'config', 'user.name', 'github-actions[bot]')
    run('git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
    run('git', 'add', 'Distribution/catalog.json', 'Distribution/emoji-import.json')
    if subprocess.run(['git', 'diff', '--cached', '--quiet']).returncode != 0:
        run('git', 'commit', '-m', 'Publish verified Emoji Studio update')
        run('git', 'push', 'origin', 'HEAD:main')
    print('Guest catalogue published successfully', flush=True)

if __name__ == '__main__':
    main()
