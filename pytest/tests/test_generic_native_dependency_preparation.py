import zipfile
from pathlib import Path
from wayfinder.runtime import native_dependencies as nd

def _reset():
    nd._DLL_HANDLES.clear()
    nd._REGISTERED.clear()
    nd._DISCOVERY_CACHE.clear()

def test_managed_packages_are_registered_in_place(tmp_path, monkeypatch):
    _reset()
    pkg=tmp_path/"python_packages"/"demo"; pkg.mkdir(parents=True)
    (pkg/"speedup.pyd").write_bytes(b"x"); (pkg/"helper.dll").write_bytes(b"x")
    handles=[]
    monkeypatch.setattr(nd,"_IS_WINDOWS",True)
    monkeypatch.setattr(nd.os,"add_dll_directory",lambda p: handles.append(p) or object(),raising=False)
    result=nd.prepare_native_dependencies(dependency_root=tmp_path/"python_packages")
    assert handles
    assert str(pkg.resolve()).casefold() in {p.casefold() for p in result["registered"]}

def test_apworld_native_cache_is_persistent_and_reused(tmp_path, monkeypatch):
    _reset()
    apworld=tmp_path/"sample.apworld"
    with zipfile.ZipFile(apworld,"w") as zf:
        zf.writestr("demo/native/speedup.pyd",b"x")
        zf.writestr("demo/native/helper.dll",b"y")
        zf.writestr("demo/data.txt",b"not extracted")
    monkeypatch.setattr(nd,"_IS_WINDOWS",True)
    monkeypatch.setattr(nd.os,"add_dll_directory",lambda p: object(),raising=False)
    monkeypatch.setattr(nd,"_cache_root",lambda: tmp_path/"native_cache")
    first=nd.prepare_native_dependencies(apworld_path=apworld)
    cached=Path(first["apworld_native_root"])
    assert first["apworld_cache_reused"] is False
    assert (cached/"demo/native/speedup.pyd").is_file()
    assert not (cached/"demo/data.txt").exists()
    nd._REGISTERED.clear()
    second=nd.prepare_native_dependencies(apworld_path=apworld)
    assert second["apworld_cache_reused"] is True
    assert second["apworld_native_root"]==str(cached)

def test_changed_apworld_gets_new_content_addressed_cache(tmp_path, monkeypatch):
    _reset()
    apworld=tmp_path/"sample.apworld"
    monkeypatch.setattr(nd,"_IS_WINDOWS",True)
    monkeypatch.setattr(nd.os,"add_dll_directory",lambda p: object(),raising=False)
    monkeypatch.setattr(nd,"_cache_root",lambda: tmp_path/"native_cache")
    with zipfile.ZipFile(apworld,"w") as zf: zf.writestr("demo/native/a.pyd",b"a")
    first=nd.prepare_native_dependencies(apworld_path=apworld)
    with zipfile.ZipFile(apworld,"w") as zf: zf.writestr("demo/native/a.pyd",b"changed")
    second=nd.prepare_native_dependencies(apworld_path=apworld)
    assert first["apworld_native_root"] != second["apworld_native_root"]
    assert second["apworld_cache_reused"] is False
