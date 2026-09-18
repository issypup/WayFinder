"""Developer-only: build pinned PyFast wheels with MSVC, without package managers.

Run from an x64 MSVC developer command prompt with a full CPython 3.13 install:
    py -3.13 tools/build_native_wheels.py
Users receive the resulting native_wheels directory; no compiler runs at runtime.
"""

# sig:kuro:pluralchat

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = {
    'PyFastBTI': dict(module='pyfastbti', version='1.0', major=1,
        commit='13b24b028b62d199740044f15085f70878ea80a4',
        sha256='c87b4286d09a8043f985d02fde2021503e182244b19278d73c5962d67474c904'),
    'PyFastTextureUtils': dict(module='pyfasttextureutils', version='1.0', major=1,
        commit='ec40de927daa6b59485e34ea01b8bab1ecd1a31a',
        sha256='183f207d9e046dc2b2a728f9a3bbe1226af6a18c139921a78467c59234fac2b2'),
    'PyFastYaz0Yay0': dict(module='pyfastyaz0yay0', version='2.0', major=2,
        commit='2adb8a8c00d98f98f245e0304094a0610203a82e',
        sha256='d65309d442bcdf9d1d384eef444fbbdea9fe5145f273d8ee67f3ec01fdb17b50'),
}


def compiler_environment(vcvars):
    if not vcvars:
        if not shutil.which('cl.exe'):
            raise RuntimeError('Use an x64 MSVC developer prompt or provide --vcvars path/to/vcvars64.bat')
        return os.environ.copy()
    vcvars = str(Path(vcvars).resolve())
    if any(c in vcvars for c in '"\r\n%&|<>^'):
        raise ValueError('Unsupported characters in vcvars path')
    command = f'call "{vcvars}" >nul && set'
    # cmd.exe uses its own quote rules, not the C-runtime argument quoting used
    # by subprocess list arguments. The sole interpolated path is validated above.
    result = subprocess.run('cmd.exe /d /s /c "' + command + '"', check=True, capture_output=True, text=True)
    env = os.environ.copy()
    env.update(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line and not line.startswith('='))
    return env


def package_wheel(name, config, binary, license_bytes, compiler):
    module, version = config['module'], config['version']
    dist = f'{module}-{version}.dist-info'
    source = dict(repo='LagoLunatic/' + name, commit=config['commit'], revision=config['commit'],
                  version=version, sha256=config['sha256'])
    metadata = f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\nRequires-Python: >=3.13,<3.14\nLicense: MIT\n'
    provenance = dict(url='https://github.com/' + source['repo'],
                      vcs_info=dict(vcs='git', requested_revision=config['commit'], commit_id=config['commit']),
                      wayfinder_archive_sha256=config['sha256'])
    files = {
        module + '.cp313-win_amd64.pyd': binary,
        dist + '/METADATA': metadata.encode(),
        dist + '/WHEEL': b'Wheel-Version: 1.0\nGenerator: WayFinder MSVC native builder\nRoot-Is-Purelib: false\nTag: cp313-cp313-win_amd64\n',
        dist + '/licenses/LICENSE.txt': license_bytes,
        dist + '/direct_url.json': json.dumps(provenance, sort_keys=True).encode(),
        dist + '/wayfinder_build.json': json.dumps(dict(compiler=compiler, source=source,
            python_abi='cp313', platform='win_amd64', source_modified=False), sort_keys=True).encode(),
    }
    record = io.StringIO(newline='')
    writer = csv.writer(record)
    for path, data in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        writer.writerow((path, 'sha256=' + digest, len(data)))
    writer.writerow((dist + '/RECORD', '', ''))
    files[dist + '/RECORD'] = record.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, data in sorted(files.items()):
            info = zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    data = output.getvalue()
    return data, dict(name=module, version=version, filename=f'{module}-{version}-cp313-cp313-win_amd64.whl',
                      sha256=hashlib.sha256(data).hexdigest(), source=source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-root', type=Path, default=Path(sys.base_prefix))
    parser.add_argument('--sources', type=Path, help='Optional cache containing the three source ZIPs')
    parser.add_argument('--vcvars', help='Path to vcvars64.bat')
    parser.add_argument('--output', type=Path, default=ROOT / 'native_wheels')
    args = parser.parse_args()
    python_root = args.python_root.resolve()
    if not (python_root / 'libs/python313.lib').is_file():
        raise RuntimeError('Python 3.13 development headers/libs are required only when rebuilding these wheels')
    patchlevel = (python_root / 'include/patchlevel.h').read_text()
    if '#define PY_MINOR_VERSION        13' not in patchlevel:
        raise RuntimeError('Expected Python 3.13 development headers')
    env = compiler_environment(args.vcvars)
    compiler = shutil.which('cl.exe', path=env.get('Path', env.get('PATH', '')))
    if not compiler:
        raise RuntimeError('MSVC cl.exe is missing from the developer environment')
    banner = subprocess.run([compiler], env=env, capture_output=True, text=True)
    compiler_version = next((line for line in (banner.stdout + banner.stderr).splitlines()
                             if 'Compiler Version' in line), '')
    if 'x64' not in compiler_version:
        raise RuntimeError('The x64 compiler target is required')
    built = []
    with tempfile.TemporaryDirectory(prefix='wayfinder_native_build_') as temporary:
        work = Path(temporary)
        for name, config in PROJECTS.items():
            cached = args.sources / (name + '.zip') if args.sources else None
            if cached and cached.is_file():
                data = cached.read_bytes()
            else:
                url = f'https://api.github.com/repos/LagoLunatic/{name}/zipball/{config["commit"]}'
                with urlopen(Request(url, headers={'User-Agent': 'WayFinder-native-build'}), timeout=45) as response:
                    data = response.read(16 * 1024 * 1024)
            if hashlib.sha256(data).hexdigest() != config['sha256']:
                raise RuntimeError(f'Source checksum mismatch: {name}')
            folder = work / name
            folder.mkdir()
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if archive.comment.decode() != config['commit']:
                    raise RuntimeError('Source commit mismatch')
                source_name = next(p for p in archive.namelist() if p.endswith('/' + config['module'] + '.c'))
                license_name = next(p for p in archive.namelist() if p.endswith('/LICENSE.txt'))
                source = folder / (config['module'] + '.c')
                source.write_bytes(archive.read(source_name))
                license_bytes = archive.read(license_name)
            binary = folder / (config['module'] + '.cp313-win_amd64.pyd')
            command = [compiler, '/nologo', '/LD', '/O2', '/MD', '/std:c11', '/DNDEBUG',
                       f'/DMAJOR_VERSION={config["major"]}', '/DMINOR_VERSION=0',
                       '/I' + str(python_root / 'include'), str(source), '/Fe:' + str(binary),
                       '/link', '/LIBPATH:' + str(python_root / 'libs'), 'python313.lib', '/MACHINE:X64', '/Brepro']
            result = subprocess.run(command, cwd=folder, env=env, capture_output=True, text=True)
            print(result.stdout + result.stderr, flush=True)
            result.check_returncode()
            wheel, entry = package_wheel(name, config, binary.read_bytes(), license_bytes, compiler_version)
            built.append((wheel, entry))
    args.output.mkdir(parents=True, exist_ok=True)
    for wheel, entry in built:
        (args.output / entry['filename']).write_bytes(wheel)
    manifest = dict(schema_version=1, wheels=[entry for _, entry in built])
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
