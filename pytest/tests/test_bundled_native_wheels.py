"""WayFinder-hosted native wheel selection, download and integrity behavior."""
import hashlib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.tags import Tag

from wayfinder.runtime import bundled_wheels
from wayfinder.runtime.wheel_installer import InstallError, WheelInstaller


def requirements():
    return [Requirement(f"{e['name']} @ git+https://github.com/{e['source']['repo']}.git@{e['source']['commit']}")
            for e in bundled_wheels.manifest_entries()]


def local_fetcher():
    root = Path(__file__).resolve().parents[2] / 'native_wheels'
    def fetch(url, limit):
        path = root / url.rsplit('/', 1)[-1]
        data = path.read_bytes()
        assert len(data) <= limit
        return data
    return fetch


def test_native_candidates_point_to_wayfinder_github():
    entries = bundled_wheels.manifest_entries()
    assert len(entries) == 3
    for entry in entries:
        assert entry['url'].startswith('https://raw.githubusercontent.com/issypup/WayFinder/main/native_wheels/')
        assert 'bundled_path' not in entry
        assert hashlib.sha256((Path(__file__).resolve().parents[2] / 'native_wheels' / entry['filename']).read_bytes()).hexdigest() == entry['digests']['sha256']


def test_hosted_native_wheels_download_then_use_cache(tmp_path, monkeypatch):
    installer = WheelInstaller(tmp_path / 'packages', tags=[Tag('cp313', 'cp313', 'win_amd64')],
        environment={'python_full_version': '3.13.5', 'python_version': '3.13', 'sys_platform': 'win32'})
    fetch = local_fetcher()
    calls = []
    monkeypatch.setattr(installer, 'fetch', lambda url, limit: (calls.append(url), fetch(url, limit))[1])
    installer.install(requirements())
    assert len(calls) == 3
    assert all('raw.githubusercontent.com/issypup/WayFinder/main/native_wheels/' in url for url in calls)

    # A fresh resolver sharing the same cache must not download the wheel payloads again.
    cached = WheelInstaller(tmp_path / 'packages', tags=[Tag('cp313', 'cp313', 'win_amd64')],
        environment={'python_full_version': '3.13.5', 'python_version': '3.13', 'sys_platform': 'win32'})
    monkeypatch.setattr(cached, 'fetch', lambda *args: (_ for _ in ()).throw(AssertionError('cache should avoid download')))
    cached.install(requirements())


def test_corrupt_download_fails_sha256_before_install(tmp_path, monkeypatch):
    installer = WheelInstaller(tmp_path / 'packages', tags=[Tag('cp313', 'cp313', 'win_amd64')],
        environment={'python_full_version': '3.13.5', 'python_version': '3.13', 'sys_platform': 'win32'})
    monkeypatch.setattr(installer, 'fetch', lambda *args: b'corrupt payload')
    with pytest.raises(InstallError, match='SHA256 mismatch'):
        installer.install(requirements())
    assert not installer.target.exists()


def test_other_python_and_platform_tags_are_rejected(tmp_path):
    installer = WheelInstaller(tmp_path / 'packages', tags=[Tag('cp314', 'cp314', 'win_amd64')])
    with pytest.raises(InstallError, match='No compatible wheel'):
        installer.install(requirements())


def test_different_native_source_pin_is_not_substituted(tmp_path):
    installer = WheelInstaller(tmp_path / 'packages', tags=[Tag('cp313', 'cp313', 'win_amd64')])
    with pytest.raises(InstallError, match='No compatible wheel'):
        installer.install([Requirement('PyFastYaz0Yay0 @ git+https://github.com/LagoLunatic/PyFastYaz0Yay0.git@' + '0'*40)])
