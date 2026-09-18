"""Release payload selection, integrity, frozen layout and native behavior."""
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest
from packaging.requirements import Requirement
from packaging.tags import Tag

from wayfinder.runtime import bundled_wheels
from wayfinder.runtime.wheel_installer import InstallError, WheelInstaller


def requirements():
    return [Requirement(f"{e['name']} @ git+https://github.com/{e['source']['repo']}.git@{e['source']['commit']}")
            for e in bundled_wheels.manifest_entries()]


def test_release_native_payload_installs_offline_and_records_sources(tmp_path, monkeypatch):
    installer = WheelInstaller(tmp_path / 'packages', tags=[Tag('cp313', 'cp313', 'win_amd64')],
        environment={'python_full_version': '3.13.5', 'python_version': '3.13', 'sys_platform': 'win32'})
    def no_network(*args):
        raise AssertionError('Bundled native wheels must not require a network or source build')
    monkeypatch.setattr(installer, 'fetch', no_network)
    installer.install(requirements())
    for entry in bundled_wheels.manifest_entries():
        assert (installer.target / (entry['name'] + '.cp313-win_amd64.pyd')).is_file()
        folder = installer.target / (entry['name'] + '-' + str(entry['version']) + '.dist-info')
        provenance = json.loads((folder / 'direct_url.json').read_text())
        assert provenance['vcs_info']['commit_id'] == entry['source']['commit']
        assert provenance['wayfinder_archive_sha256'] == entry['source']['sha256']
        assert (folder / 'licenses/LICENSE.txt').is_file()
 

def test_native_source_provenance_passes_preflight(tmp_path):
    pytest.importorskip('tkinter', reason='APWorld preflight imports GUI helpers')
    from wayfinder.runtime.apworld_compatibility import dependency_preflight
    installer = WheelInstaller(tmp_path / 'packages', tags=[Tag('cp313', 'cp313', 'win_amd64')],
        environment={'python_full_version': '3.13.5', 'python_version': '3.13', 'sys_platform': 'win32'})
    installer.install(requirements())
    record = SimpleNamespace(requirements=[{'requirement': str(req)} for req in requirements()])
    assert all(item['state'] == 'Ready' for item in dependency_preflight(record, installer.target))


def test_other_python_and_platform_tags_are_rejected(tmp_path):
    installer = WheelInstaller(tmp_path / 'packages', tags=[Tag('cp314', 'cp314', 'win_amd64')])
    with pytest.raises(InstallError, match='No compatible wheel'):
        installer.install(requirements())


def test_different_native_source_pin_is_not_substituted(tmp_path):
    installer = WheelInstaller(tmp_path / 'packages', tags=[Tag('cp313', 'cp313', 'win_amd64')])
    with pytest.raises(InstallError, match='No compatible wheel'):
        installer.install([Requirement('PyFastYaz0Yay0 @ git+https://github.com/LagoLunatic/PyFastYaz0Yay0.git@' + '0'*40)])


def test_frozen_payload_layout(tmp_path, monkeypatch):
    source = bundled_wheels.payload_root()
    shutil.copytree(source, tmp_path / 'native_wheels')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    assert bundled_wheels.payload_root() == tmp_path / 'native_wheels'
    assert len(bundled_wheels.manifest_entries()) == 3
    for entry in bundled_wheels.manifest_entries():
        assert hashlib.sha256(entry['bundled_path'].read_bytes()).hexdigest() == entry['digests']['sha256']


def test_corrupt_bundled_wheel_fails_before_install(tmp_path, monkeypatch):
    source = bundled_wheels.payload_root()
    shutil.copytree(source, tmp_path / 'native_wheels')
    monkeypatch.setattr(bundled_wheels, 'payload_root', lambda: tmp_path / 'native_wheels')
    entry = bundled_wheels.manifest_entries()[0]
    entry['bundled_path'].write_bytes(b'corrupt payload')
    installer = WheelInstaller(tmp_path / 'packages', tags=[Tag('cp313', 'cp313', 'win_amd64')],
        environment={'python_full_version': '3.13.5', 'python_version': '3.13', 'sys_platform': 'win32'})
    with pytest.raises(InstallError, match='SHA256 mismatch'):
        installer.install(requirements())
    assert not installer.target.exists()


def test_missing_release_wheel_has_actionable_error(tmp_path, monkeypatch):
    source = bundled_wheels.payload_root()
    shutil.copytree(source, tmp_path / 'native_wheels')
    monkeypatch.setattr(bundled_wheels, 'payload_root', lambda: tmp_path / 'native_wheels')
    bundled_wheels.manifest_entries()[0]['bundled_path'].unlink()
    installer = WheelInstaller(tmp_path / 'packages', tags=[Tag('cp313', 'cp313', 'win_amd64')])
    with pytest.raises(ValueError, match='Bundled native wheel is missing'):
        installer.install(requirements())


@pytest.mark.skipif(sys.version_info[:2] != (3, 13) or sys.platform != 'win32', reason='Release native ABI is Windows CPython 3.13')
def test_real_native_compression_and_image_functions(tmp_path, monkeypatch):
    installer = WheelInstaller(tmp_path / 'packages')
    installer.install(requirements())
    monkeypatch.syspath_prepend(str(installer.target))
    yaz = importlib.import_module('pyfastyaz0yay0')
    bti = importlib.import_module('pyfastbti')
    texture = importlib.import_module('pyfasttextureutils')
    for module in (yaz, bti, texture):
        assert Path(module.__file__).is_relative_to(installer.target)
    samples = [b'a', bytes(range(256)), b'WayFinder' * 128, bytes(range(251)) * 8]
    for sample in samples:
        assert yaz.decompress_yaz0(yaz.compress_yaz0(sample, 0x1000)) == sample
        assert yaz.decompress_yay0(yaz.compress_yay0(sample, 0x1000)) == sample
    colors = [(0, 0, 0, 255), (255, 255, 255, 255)]
    assert set(bti.get_best_cmpr_key_colors(colors)) == set(colors)
    assert texture.color_exchange(bytes([255, 0, 0, 255]), (255, 0, 0), (0, 255, 0), None, False, False) == bytes([0, 255, 0, 255])
    with pytest.raises(TypeError):
        texture.color_exchange(b'bad', (255, 0, 0), (0, 255, 0), None, False, False)
