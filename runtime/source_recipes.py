"""Audited, checksum-pinned pure-Python layouts; never interpret setup/build code.

These three revisions were inspected on 2026-09-18. Supporting another revision
requires reviewing its layout, dependencies, version generation and archive hash.
This is intentionally not a generic source-distribution installer.
"""
import base64
import csv
import hashlib
import io
import json
import re
import stat
import tarfile
import zipfile
from email.parser import BytesParser


RECIPES = {
    'mpyq': dict(version='0.2.5', package='mpyq', source='mpyq.py', license='LICENSE',
        python='>=3', dependencies=[], archive_format='tar.gz',
        sha256='30aaf5962be569f3f2b53978060cd047434ee4f5a215925dd6ff0fef04ec0007',
        download_url='https://files.pythonhosted.org/packages/ff/10/76041d97aa01e4d0f93481942b4faf5652123acdd90fbff4e40bb8d9024c/mpyq-0.2.5.tar.gz'),
    'kivymd': dict(repo='kivymd/KivyMD', revision='5ff9d0d',
        commit='5ff9d0de78260383fae0737716879781257155a8', version='2.0.1.dev0',
        sha256='24d968dcad8a1bc10ac34aaca8317dc469feee06698076a5339aa6e093dadd56',
        package='kivymd', source='kivymd', license='LICENSE', python='>=3.7',
        dependencies=['kivy>=2.3.0', 'pillow', 'materialyoucolor>=2.0.7', 'asynckivy>=0.6,<0.7']),
    'zilliandomizer': dict(repo='beauxq/zilliandomizer', revision='96d9a20f8278cee64bb4db859fbd874e0f332d36',
        commit='96d9a20f8278cee64bb4db859fbd874e0f332d36', version='0.9.1',
        sha256='48b3263b01cc49066a777f256850b74fe6f78c249f7e4f433dd9e0f0477c1d84',
        package='zilliandomizer', source='src/zilliandomizer', license='LICENSE', python='>=3.8', dependencies=[]),
    'gclib': dict(repo='LagoLunatic/gclib', revision='abae309e05a8de4c2642e903611e65b4b124e1ce',
        commit='abae309e05a8de4c2642e903611e65b4b124e1ce', version='1.0.0',
        sha256='51d56737b2e420d4707668d6ed168864254b0a446f80c0b55abbb43f6ef50311',
        package='gclib', source='gclib', license='LICENSE.txt', python='>=3.11',
        dependencies=['imagequant>=1.1.4', 'numpy>=2.2.3', 'pillow>=11.1.0',
            'PyFastBTI @ git+https://github.com/LagoLunatic/PyFastBTI.git@13b24b028b62d199740044f15085f70878ea80a4 ; extra == "speedups"',
            'PyFastTextureUtils @ git+https://github.com/LagoLunatic/PyFastTextureUtils.git@ec40de927daa6b59485e34ea01b8bab1ecd1a31a ; extra == "speedups"',
            'PyFastYaz0Yay0 @ git+https://github.com/LagoLunatic/PyFastYaz0Yay0.git@2adb8a8c00d98f98f245e0304094a0610203a82e ; extra == "speedups"']),
}


def source_matches(entry, url):
    recipe = entry.get('recipe') or entry.get('source')
    if not recipe or 'repo' not in recipe:
        return False
    match = re.fullmatch(r'git\+https://github\.com/([^/@]+/[^/@]+?)(?:\.git)?@([0-9a-fA-F]+)(?:#([^#]+))?', url)
    if not match:
        return False
    repo, revision, fragment = match.groups()
    return (repo.lower() == recipe['repo'].lower()
            and revision.lower() in {recipe['revision'], recipe['commit']}
            and fragment in (None, recipe['version']))


def source_candidate(name, requirements):
    recipe = RECIPES.get(name)
    if not recipe:
        return None
    supported_extras = {'speedups'} if name == 'gclib' else set()
    if any(set(req.extras) - supported_extras for req in requirements):
        return None
    if 'download_url' in recipe:
        if any(req.url for req in requirements):
            return None
        return dict(recipe=recipe, filename=f"{name}-{recipe['version']}.tar.gz",
                    url=recipe['download_url'], digests={'sha256': recipe['sha256']})
    entry = dict(recipe=recipe, filename=f"{name}-{recipe['commit']}.zip",
                 url=f"https://api.github.com/repos/{recipe['repo']}/zipball/{recipe['revision']}",
                 digests={'sha256': recipe['sha256']})
    return entry if all(not req.url or source_matches(entry, req.url) for req in requirements) else None


def source_payload(path, entry, safe_path):
    recipe = entry['recipe']
    name, version = recipe['package'], recipe['version']
    dist = f'{name}-{version}.dist-info'
    files = {}
    if recipe.get('archive_format') == 'tar.gz':
        with tarfile.open(path, 'r:gz') as archive:
            members = archive.getmembers()
            if sum(m.size for m in members) > 512 * 1024 * 1024:
                raise ValueError('Expanded source archive exceeds size limit')
            seen = set()
            for member in members:
                safe_path(member.name)
                if member.name in seen or not (member.isdir() or member.isfile()):
                    raise ValueError('Duplicate or non-regular source archive member')
                seen.add(member.name)
                if not member.isfile():
                    continue
                relative = member.name.removeprefix(f'{name}-{version}/')
                if relative == recipe['source']:
                    files[relative] = archive.extractfile(member).read()
                elif relative == recipe['license']:
                    files[dist + '/licenses/' + relative] = archive.extractfile(member).read()
        if recipe['source'] not in files:
            raise ValueError('Audited source module is missing')
    else:
        files = _zip_source_files(path, recipe, dist, safe_path)
    metadata = (f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n'
                f'Requires-Python: {recipe["python"]}\n'
                + ('Provides-Extra: speedups\n' if name == 'gclib' else '')
                + ''.join(f'Requires-Dist: {req}\n' for req in recipe['dependencies'])).encode()
    files[dist + '/METADATA'] = metadata
    files[dist + '/INSTALLER'] = b'wayfinder-audited-source\n'
    if 'repo' in recipe:
        provenance = {'url': 'https://github.com/' + recipe['repo'],
            'vcs_info': {'vcs': 'git', 'requested_revision': recipe['revision'], 'commit_id': recipe['commit']},
            'wayfinder_archive_sha256': recipe['sha256']}
    else:
        provenance = {'url': entry['url'], 'archive_info': {'hashes': {'sha256': recipe['sha256']}}}
    files[dist + '/direct_url.json'] = json.dumps(provenance).encode()
    record = io.StringIO(newline='')
    writer = csv.writer(record)
    for relative, data in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        writer.writerow((relative, 'sha256=' + digest, len(data)))
    writer.writerow((dist + '/RECORD', '', ''))
    files[dist + '/RECORD'] = record.getvalue().encode()
    return files, BytesParser().parsebytes(metadata)


def _zip_source_files(path, recipe, dist, safe_path):
    name = recipe['package']
    files = {}
    with zipfile.ZipFile(path) as archive:
        if archive.comment.decode('ascii') != recipe['commit']:
            raise ValueError('Source archive commit identity mismatch')
        members = [i for i in archive.infolist() if not i.is_dir()]
        if sum(i.file_size for i in members) > 512 * 1024 * 1024:
            raise ValueError('Expanded source archive exceeds size limit')
        roots = {i.filename.split('/')[0] for i in members}
        if len(roots) != 1:
            raise ValueError('Source archive must have one root directory')
        for info in members:
            safe_path(info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('Source archive symlinks are unsupported')
            relative = info.filename.split('/', 1)[1]
            if relative.startswith(recipe['source'] + '/'):
                destination = name + relative[len(recipe['source']):]
            elif relative == recipe['license']:
                destination = dist + '/licenses/' + recipe['license']
            else:
                continue
            if destination in files:
                raise ValueError('Duplicate source package path')
            files[destination] = archive.read(info)
    if not files or not any(p.startswith(name + '/') for p in files):
        raise ValueError('Audited source package directory is missing')
    return files
