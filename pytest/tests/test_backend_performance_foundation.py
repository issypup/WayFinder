
import json
import zipfile
from pathlib import Path

from wayfinder.runtime import apworld_catalog as catalog
from wayfinder.runtime import apworld_compatibility as compat
from wayfinder.runtime import native_dependencies as native


def test_apworld_catalog_reuses_unchanged_archive(tmp_path, monkeypatch):
    apworld=tmp_path/"demo.apworld"
    with zipfile.ZipFile(apworld,"w") as zf:
        zf.writestr("demo/__init__.py", 'class Demo:\n    game = "Demo Game"\ngame = "Demo Game"\n')
        zf.writestr("demo/archipelago.json", json.dumps({"game":"Demo Game","world_version":"1.0.0"}))
    cache=tmp_path/"catalog.json"
    monkeypatch.setattr(catalog,"_catalog_cache_path",lambda:cache)
    catalog._catalog_cache_memory=None
    first=catalog.inspect_world(apworld,ap_version="0.6.7",details=True)
    second=catalog.inspect_world(apworld,ap_version="0.6.7",details=True)
    assert not getattr(first,"_wayfinder_catalog_cache_hit",False)
    assert getattr(second,"_wayfinder_catalog_cache_hit",False)
    assert first.sha256 == second.sha256


def test_dependency_validation_reuses_unchanged_environment(tmp_path, monkeypatch):
    deps=tmp_path/"python_packages"; deps.mkdir()
    record=catalog.WorldRecord(str(tmp_path/"x.apworld"),game="Demo",sha256="abc",requirements=[])
    monkeypatch.setattr(compat,"_dependency_cache_path",lambda:tmp_path/"deps.json")
    compat._dependency_cache_memory=None
    first=compat.dependency_preflight(record,deps)
    assert first == []
    assert not getattr(record,"_wayfinder_dependency_cache_hit",False)
    second=compat.dependency_preflight(record,deps)
    assert second == []
    assert getattr(record,"_wayfinder_dependency_cache_hit",False)


def test_native_directory_index_reuses_discovery(tmp_path, monkeypatch):
    root=tmp_path/"packages"; pkg=root/"demo"; pkg.mkdir(parents=True)
    (pkg/"speedup.pyd").write_bytes(b"x")
    monkeypatch.setattr(native,"_native_discovery_index_path",lambda:tmp_path/"native-index.json")
    native._DISCOVERY_CACHE.clear()
    first=native._native_directories(root)
    assert pkg in first
    native._DISCOVERY_CACHE.clear()
    second=native._native_directories(root)
    assert second == first
