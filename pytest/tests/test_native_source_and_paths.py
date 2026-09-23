"""Regression tests for pinned sources and runtime .pth activation."""
import hashlib
import io
import json
import sys
import tarfile
import zipfile

import pytest
from packaging.requirements import Requirement

from wayfinder.runtime import source_recipes, dependency_path
from wayfinder.runtime.wheel_installer import WheelInstaller, InstallError


def make_source(tmp_path, monkeypatch, dependencies=()):
    commit = 'a' * 40
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w') as archive:
        archive.comment = commit.encode()
        archive.writestr('repo/src/demo/__init__.py', 'VALUE = 42')
        archive.writestr('repo/src/demo/data/example.txt', 'resource')
        archive.writestr('repo/setup.py', 'raise RuntimeError("must not execute")')
        archive.writestr('repo/LICENSE', 'test license')
    data = content.getvalue()
    recipe = dict(repo='example/demo', revision=commit, commit=commit, version='1.0',
                  sha256=hashlib.sha256(data).hexdigest(), package='demo', source='src/demo',
                  license='LICENSE', python='>=3.9', dependencies=list(dependencies))
    monkeypatch.setitem(source_recipes.RECIPES, 'demo', recipe)
    installer = WheelInstaller(tmp_path / 'packages')
    monkeypatch.setattr(installer, 'fetch', lambda url, limit: data)
    return installer, recipe


def test_audited_source_retains_resources_and_provenance(tmp_path, monkeypatch):
    ins, recipe = make_source(tmp_path, monkeypatch)
    req = Requirement('demo @ git+https://github.com/example/demo.git@' + recipe['commit'])
    ins.install([req])
    assert (ins.target / 'demo/data/example.txt').read_text() == 'resource'
    assert not (ins.target / 'setup.py').exists()
    provenance = json.loads((ins.target / 'demo-1.0.dist-info/direct_url.json').read_text())
    assert provenance['vcs_info']['commit_id'] == recipe['commit']
    assert provenance['wayfinder_archive_sha256'] == recipe['sha256']


def test_different_source_revision_is_not_substituted(tmp_path, monkeypatch):
    ins, recipe = make_source(tmp_path, monkeypatch)
    with pytest.raises(InstallError, match='Source/direct URL'):
        ins.install([Requirement('demo @ git+https://github.com/example/demo@' + 'b'*40)])


def test_source_dependency_metadata_is_resolved(tmp_path, monkeypatch):
    ins, recipe = make_source(tmp_path, monkeypatch, ['missing @ git+https://github.com/example/missing@abc'])
    with pytest.raises(InstallError, match='missing'):
        ins.install([Requirement('demo @ git+https://github.com/example/demo@' + recipe['commit'])])


def test_source_hash_cannot_be_bypassed(tmp_path, monkeypatch):
    ins, recipe = make_source(tmp_path, monkeypatch)
    monkeypatch.setattr(ins, 'fetch', lambda url, limit: b'corrupt source')
    with pytest.raises(InstallError, match='SHA256 mismatch'):
        ins.install([Requirement('demo @ git+https://github.com/example/demo@' + recipe['commit'])])


def test_source_version_constraints_are_not_ignored(tmp_path, monkeypatch):
    ins, recipe = make_source(tmp_path, monkeypatch)
    with pytest.raises(InstallError):
        ins.install([Requirement('demo @ git+https://github.com/example/demo@' + recipe['commit'])], [Requirement('demo>=2')])
    assert not ins.target.exists()


def test_pth_activated_once_and_preserves_core_precedence(tmp_path, monkeypatch):
    root = tmp_path / 'packages'
    child = root / 'extra'
    child.mkdir(parents=True)
    (root / 'paths.pth').write_text('extra\nimport sys; sys._wf_hook_count = getattr(sys, "_wf_hook_count", 0) + 1\n')
    monkeypatch.setattr(sys, 'path', ['core', *sys.path])
    monkeypatch.setattr(sys, '_wf_hook_count', 0, raising=False)
    monkeypatch.setattr(dependency_path, '_activated', set())
    dependency_path.activate_dependencies(root)
    dependency_path.activate_dependencies(root)
    assert sys.path[:3] == ['core', str(root), str(child)]
    assert sys._wf_hook_count == 1


def test_audited_sdist_module_is_installed_without_setup(tmp_path, monkeypatch):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        for name, content in [('demo-1.0/demo.py', b'VALUE=42'), ('demo-1.0/LICENSE', b'license'),
                              ('demo-1.0/setup.py', b'raise RuntimeError("must not execute")')]:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    payload = data.getvalue()
    recipe = dict(version='1.0', package='demo', source='demo.py', license='LICENSE', python='>=3',
                  dependencies=[], archive_format='tar.gz', sha256=hashlib.sha256(payload).hexdigest(),
                  download_url='https://files.pythonhosted.org/demo-1.0.tar.gz')
    monkeypatch.setitem(source_recipes.RECIPES, 'demo', recipe)
    entry = dict(filename='demo-1.0.tar.gz', packagetype='sdist', url=recipe['download_url'],
                 digests={'sha256': recipe['sha256']})
    ins = WheelInstaller(tmp_path / 'packages')
    monkeypatch.setattr(ins, 'fetch', lambda url, limit: payload if url.endswith('.tar.gz')
                        else json.dumps({'releases': {'1.0': [entry]}}).encode())
    ins.install([Requirement('demo>=1')])
    assert (ins.target / 'demo.py').read_bytes() == b'VALUE=42'
    assert not (ins.target / 'setup.py').exists()


def test_unreviewed_source_extras_are_rejected(tmp_path, monkeypatch):
    ins, recipe = make_source(tmp_path, monkeypatch)
    with pytest.raises(InstallError, match='Source/direct URL'):
        ins.install([Requirement('demo[unknown] @ git+https://github.com/example/demo@' + recipe['commit'])])


def test_windows_native_activation_registers_dll_dirs_and_path(tmp_path, monkeypatch):
    root = tmp_path / "packages"
    native = root / "demo" / "bin"
    native.mkdir(parents=True)
    (native / "demo.pyd").write_bytes(b"")
    handles = []
    monkeypatch.setattr(dependency_path.os, "name", "nt")
    monkeypatch.setattr(dependency_path.os, "add_dll_directory", lambda p: handles.append(p) or object(), raising=False)
    monkeypatch.setattr(dependency_path, "_dll_handles", [])
    monkeypatch.setattr(dependency_path, "_dll_directories", [])
    monkeypatch.setenv("PATH", "C:\\Windows")
    dependency_path._activate_windows_native_search(root)
    assert str(native) in handles
    assert str(native) in dependency_path.os.environ["PATH"].split(dependency_path.os.pathsep)


def test_reactivation_refreshes_native_search_after_install(tmp_path, monkeypatch):
    root = tmp_path / "packages"
    root.mkdir()
    monkeypatch.setattr(dependency_path, "_activated", set())
    calls = []
    monkeypatch.setattr(dependency_path, "_activate_windows_native_search", lambda p: calls.append(p))
    dependency_path.activate_dependencies(root)
    dependency_path.activate_dependencies(root)
    assert calls == [root.resolve(), root.resolve()]
