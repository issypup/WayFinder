"""Locate release-built native wheels; no compiler or package manager at runtime."""
import json
from pathlib import Path
import re
import sys

from packaging.utils import canonicalize_name, parse_wheel_filename

from .source_recipes import source_matches


def payload_root():
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / 'native_wheels'
    return Path(__file__).resolve().parents[2] / 'native_wheels'


def manifest_entries():
    root = payload_root()
    path = root / 'manifest.json'
    if not path.is_file():
        raise ValueError('WayFinder native wheel manifest is missing. Restore native_wheels and rebuild the application.')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1:
        raise ValueError('Unsupported WayFinder native wheel manifest version')
    entries = []
    for item in manifest['wheels']:
        filename = item['filename']
        if not re.fullmatch(r'[A-Za-z0-9_.+-]+\.whl', filename):
            raise ValueError('Unsafe native wheel filename in manifest')
        name, version, _, tags = parse_wheel_filename(filename)
        if name != canonicalize_name(item['name']) or str(version) != item['version']:
            raise ValueError('Native wheel manifest identity mismatch')
        if not re.fullmatch(r'[0-9a-f]{64}', item['sha256']):
            raise ValueError('Invalid native wheel checksum in manifest')
        entries.append(dict(name=name, version=version, tags=tags, filename=filename,
                            source=item['source'], bundled_path=root / filename,
                            digests={'sha256': item['sha256']}))
    return entries


def bundled_candidates(name, requirements, tag_ranks):
    # Only these exact upstream projects use the bundled-native path. Missing
    # payloads must fail explicitly, not silently fall back to a source build.
    if name not in {'pyfastbti', 'pyfasttextureutils', 'pyfastyaz0yay0'}:
        return None
    candidates = []
    for entry in manifest_entries():
        if entry['name'] != name:
            continue
        if any(r.extras or (r.url and not source_matches(entry, r.url)) for r in requirements):
            continue
        ranks = [tag_ranks[t] for t in entry['tags'] if t in tag_ranks]
        if not ranks:
            continue
        if not entry['bundled_path'].is_file():
            raise ValueError(f'Bundled native wheel is missing: {entry["filename"]}. Restore the release payload and rebuild.')
        candidates.append((entry['version'], -min(ranks), entry))
    return candidates


def source_entry(name, requirement):
    """Expected source identity for APWorld's installed-provenance check."""
    if name not in {'pyfastbti', 'pyfasttextureutils', 'pyfastyaz0yay0'}:
        return None
    return next((entry for entry in manifest_entries()
                 if entry['name'] == name and source_matches(entry, requirement.url)), None)
