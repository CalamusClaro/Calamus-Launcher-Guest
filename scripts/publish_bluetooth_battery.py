"""Publish the inspected Battery program and its compatible Launcher."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from publish_launcher import audit_zip

REPO = 'CalamusClaro/Calamus-Launcher-Guest'
APP = 'CalamusBluetoothBattery'
CATALOG = Path('Distribution/catalog.json')
MANIFEST = Path('Distribution/bluetooth-battery-import.json')

def run(*args):
    return subprocess.check_output(args, text=True, encoding='utf-8')

def sha(data):
    return hashlib.sha256(data).hexdigest()

def stage_blob_parts(spec, destination):
    with destination.open('wb') as output:
        for oid in spec['Blobs']:
            if not re.fullmatch(r'[0-9a-f]{40}', oid):
                raise ValueError('Invalid staged payload object')
            blob = json.loads(run('gh', 'api', f'repos/{REPO}/git/blobs/{oid}'))
            if blob['sha'] != oid or blob['encoding'] != 'base64':
                raise ValueError('Wrong staged payload object')
            output.write(base64.b64decode(''.join(blob['content'].split()), validate=True))
    if sha(destination.read_bytes()) != spec['Sha256']:
        raise ValueError('Staged payload checksum mismatch')

def pack_battery(overlay, work, archive):
    project = work / f'{APP}.csproj'
    project.write_text('''<Project Sdk="Microsoft.NET.Sdk">
      <PropertyGroup>
        <OutputType>WinExe</OutputType>
        <TargetFramework>net10.0-windows10.0.22621.0</TargetFramework>
        <EnableWindowsTargeting>true</EnableWindowsTargeting>
        <SupportedOSPlatformVersion>10.0.22000.0</SupportedOSPlatformVersion>
        <WindowsSdkPackageVersion>10.0.22621.57</WindowsSdkPackageVersion>
        <UseWPF>true</UseWPF>
        <UseWindowsForms>true</UseWindowsForms>
        <TargetLatestRuntimePatch>false</TargetLatestRuntimePatch>
      </PropertyGroup>
    </Project>''', encoding='utf-8')
    (work / 'Program.cs').write_text('internal static class Program { static void Main() { } }', encoding='utf-8')
    runtime = work / 'runtime'
    print(run('dotnet', 'publish', str(project), '-c', 'Release', '-r', 'win-x64',
              '--self-contained', 'true', '-o', str(runtime)), flush=True)
    with ZipFile(overlay) as app, ZipFile(archive, 'w', ZIP_DEFLATED) as result:
        expected = json.loads(app.read('payload-hashes.json'))
        included = set(app.namelist()) - {'payload-hashes.json'}
        for name, digest in expected.items():
            data = app.read(name) if name in included else (runtime / name.removeprefix(APP + '/')).read_bytes()
            if sha(data) != digest:
                raise ValueError(f'Runtime or program file differs from the inspected Windows package: {name}')
            result.writestr(ZipInfo(name), data, compress_type=ZIP_DEFLATED)

def publish(package, archive):
    data = archive.read_bytes()
    audit_zip(data)
    digest = sha(data)
    package['Sha256'] = digest
    tag = package['Tag']
    exists = subprocess.run(['gh', 'release', 'view', tag, '--repo', REPO], capture_output=True).returncode == 0
    if not exists:
        print(run('gh', 'release', 'create', tag, str(archive), '--repo', REPO, '--target',
                  os.environ['GITHUB_SHA'], '--title', package['Name'] + ' v' + package['Version'],
                  '--notes', package['Description'], '--latest=false'), flush=True)
    url = f'https://github.com/{REPO}/releases/download/{tag}/{archive.name}'
    with urllib.request.urlopen(url, timeout=100) as response:
        downloaded = response.read(len(data) + 1)
    if sha(downloaded) != digest:
        raise ValueError('Public release checksum mismatch')
    print('Verified anonymous download:', tag, digest, flush=True)

def main():
    spec = json.loads(MANIFEST.read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='calamus-battery-') as temp:
        work = Path(temp)
        launcher = spec['Launcher']['Package']
        battery = spec['BluetoothBattery']['Package']
        launcher_zip = work / launcher['Asset']
        battery_zip = work / battery['Asset']
        overlay = work / 'app.zip'
        stage_blob_parts(spec['Launcher'], launcher_zip)
        stage_blob_parts(spec['BluetoothBattery'], overlay)
        pack_battery(overlay, work, battery_zip)
        publish(battery, battery_zip)
        publish(launcher, launcher_zip)
        print(run('git', 'pull', '--rebase', 'origin', 'main'), flush=True)
        catalog = json.loads(CATALOG.read_text(encoding='utf-8-sig'))
        if catalog['Launcher']['Version'] not in ('0.7.6', launcher['Version']):
            raise ValueError('Current Launcher changed during publication')
        catalog['Launcher'] = launcher
        catalog['BluetoothBattery'] = battery
        CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(run('git', 'config', 'user.name', 'github-actions[bot]'), flush=True)
        print(run('git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'), flush=True)
        print(run('git', 'add', str(CATALOG)), flush=True)
        if subprocess.run(['git', 'diff', '--cached', '--quiet']).returncode:
            print(run('git', 'commit', '-m', 'Enable Bluetooth Battery updates in Calamus Launcher'), flush=True)
            print(run('git', 'push', 'origin', 'HEAD:main'), flush=True)

if __name__ == '__main__':
    main()
