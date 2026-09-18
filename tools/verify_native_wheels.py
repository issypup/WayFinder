"""Check the release's wheel payload before building the executable."""

# sig:kuro:pluralchat

import hashlib
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from packaging.tags import sys_tags
from wayfinder.runtime.bundled_wheels import manifest_entries


def main():
    compatible = set(sys_tags())
    entries = manifest_entries()
    required = {'pyfastbti', 'pyfasttextureutils', 'pyfastyaz0yay0'}
    if {e['name'] for e in entries} != required or len(entries) != len(required):
        raise RuntimeError('Native wheel manifest must contain exactly the three required projects')
    for entry in entries:
        if not compatible.intersection(entry['tags']):
            raise RuntimeError(f"{entry['filename']} requires standard CPython 3.13 for Windows x64. Use that interpreter to build WayFinder.")
        data = entry['bundled_path'].read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['digests']['sha256']:
            raise RuntimeError('Native wheel checksum mismatch: ' + entry['filename'])
        with zipfile.ZipFile(entry['bundled_path']) as archive:
            if archive.testzip() is not None:
                raise RuntimeError('Corrupt wheel: ' + entry['filename'])
        print('Verified', entry['filename'])


if __name__ == '__main__':
    main()
