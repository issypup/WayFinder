"""Offline wheel fixtures exercise resolution, verification and transactional writes."""
import base64
import csv
import hashlib
import io
import json
import zipfile

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.tags import cpython_tags, compatible_tags

from wayfinder.runtime.wheel_installer import InstallError, WheelInstaller, read_requirements


def wheel(name, version="1.0", requires=(), files=None, tag="py3-none-any"):
    filename = f"{name}-{version}-{tag}.whl"
    dist = f"{name}-{version}.dist-info"
    contents = {f"{name}/__init__.py": b"VALUE = 42\n", **(files or {})}
    contents[dist + "/METADATA"] = (f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n" +
                                    "".join(f"Requires-Dist: {r}\n" for r in requires)).encode()
    contents[dist + "/WHEEL"] = f"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: {tag}\n".encode()
    record = io.StringIO(newline="")
    writer = csv.writer(record)
    for path, data in contents.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow((path, "sha256=" + digest, len(data)))
    writer.writerow((dist + "/RECORD", "", ""))
    contents[dist + "/RECORD"] = record.getvalue().encode()
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as archive:
        for path, data in contents.items():
            archive.writestr(path, data)
    data = result.getvalue()
    return {"filename": filename, "url": "https://files.pythonhosted.org/" + filename,
            "packagetype": "bdist_wheel", "digests": {"sha256": hashlib.sha256(data).hexdigest()},
            "requires_python": ">=3.9", "yanked": False}, data


def installer(tmp_path, monkeypatch, fixtures):
    tags = list(cpython_tags((3, 13), abis=["cp313"], platforms=["win_amd64"]))
    tags += list(compatible_tags((3, 13), interpreter="cp313", platforms=["win_amd64"]))
    env = {**default_environment(), "python_version": "3.13", "python_full_version": "3.13.5",
           "sys_platform": "win32", "os_name": "nt", "platform_machine": "AMD64"}
    instance = WheelInstaller(tmp_path / "python_packages", tags=tags, environment=env)
    documents, calls = {}, []
    for entry, data in fixtures:
        name, version = entry["filename"].split("-")[:2]
        key = f"https://pypi.org/pypi/{name}/json"
        documents.setdefault(key, {"releases": {}})["releases"].setdefault(version, []).append(entry)
        documents[entry["url"]] = data
    def fetch(url, limit):
        calls.append(url)
        data = documents.get(url, {"releases": {}})
        return data if isinstance(data, bytes) else json.dumps(data).encode()
    monkeypatch.setattr(instance, "fetch", fetch)
    return instance, calls


def test_recursive_extras_markers_cycle_and_cache(tmp_path, monkeypatch):
    ins, calls = installer(tmp_path, monkeypatch, [
        wheel("alpha", requires=['beta[fast]>=1; sys_platform == "win32"', 'absent; sys_platform == "linux"']),
        wheel("beta", requires=['gamma; extra == "fast"', 'alpha']), wheel("gamma")])
    ins.install([Requirement("alpha")])
    assert (ins.target / "gamma/__init__.py").exists()
    assert not any("absent" in c for c in calls)
    count = len(calls)
    ins.wheels.clear()
    ins.install([Requirement("alpha")])
    assert len(calls) == count


def test_backtracking_and_prior_unit_constraints(tmp_path, monkeypatch):
    ins, _ = installer(tmp_path, monkeypatch, [wheel("alpha", "2.0", ["beta>=2"]),
        wheel("alpha", "1.0", ["beta<2"]), wheel("beta", "1.0"), wheel("beta", "2.0")])
    ins.install([Requirement("beta<2")])
    ins.install([Requirement("alpha")])
    assert (ins.target / "alpha-1.0.dist-info").exists()
    with pytest.raises(InstallError, match="conflict"):
        ins.install([Requirement("beta>=2")])
    assert (ins.target / "beta-1.0.dist-info").exists()


@pytest.mark.parametrize("tag,python,yanked", [("cp312-cp312-win_amd64", ">=3", False),
    ("cp313-cp313-manylinux_2_17_x86_64", ">=3", False), ("py3-none-any", ">=3.14", False),
    ("py3-none-any", ">=3", True)])
def test_incompatible_wheels_not_installed(tmp_path, monkeypatch, tag, python, yanked):
    entry, data = wheel("alpha", tag=tag)
    entry.update(requires_python=python, yanked=yanked)
    ins, _ = installer(tmp_path, monkeypatch, [(entry, data)])
    with pytest.raises(InstallError, match="No compatible wheel"):
        ins.install([Requirement("alpha")])
    assert not ins.target.exists()


@pytest.mark.parametrize("tag", ["cp313-cp313-win_amd64", "cp39-abi3-win_amd64", "py3-none-any"])
def test_windows_313_compatible_tags(tmp_path, monkeypatch, tag):
    ins, _ = installer(tmp_path, monkeypatch, [wheel("alpha", tag=tag)])
    ins.install([Requirement("alpha")])
    assert (ins.target / "alpha/__init__.py").exists()


@pytest.mark.parametrize("path", ["../escape", "/absolute", "C:/escape", "nul.txt"])
def test_unsafe_or_unsupported_wheel_rejected(tmp_path, monkeypatch, path):
    ins, _ = installer(tmp_path, monkeypatch, [wheel("alpha", files={path: b"bad"})])
    with pytest.raises(InstallError):
        ins.install([Requirement("alpha")])
    assert not ins.target.exists()


def test_hash_failure_and_cache_repair(tmp_path, monkeypatch):
    entry, data = wheel("alpha")
    ins, _ = installer(tmp_path, monkeypatch, [(entry, data)])
    cached = ins.cache / (entry["digests"]["sha256"] + ".whl")
    cached.write_bytes(b"corrupt cache")
    ins.install([Requirement("alpha")])
    assert cached.read_bytes() == data
    ins.wheels.clear()
    cached.unlink()
    original = ins.fetch
    monkeypatch.setattr(ins, "fetch", lambda url, limit: b"bad" if url.endswith(".whl") else original(url, limit))
    with pytest.raises(InstallError, match="SHA256"):
        ins.install([Requirement("alpha")])
    assert (ins.target / "alpha/__init__.py").exists()


def test_record_failure_even_with_correct_archive_digest(tmp_path, monkeypatch):
    entry, data = wheel("alpha")
    changed = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(changed, "w") as dest:
        for name in source.namelist():
            dest.writestr(name, b"tampered" if name.endswith("__init__.py") else source.read(name))
    data = changed.getvalue()
    entry["digests"]["sha256"] = hashlib.sha256(data).hexdigest()
    ins, _ = installer(tmp_path, monkeypatch, [(entry, data)])
    with pytest.raises(InstallError, match="RECORD verification"):
        ins.install([Requirement("alpha")])


def test_relocated_data_and_old_version_removed(tmp_path, monkeypatch):
    ins, _ = installer(tmp_path, monkeypatch, [wheel("alpha", files={"alpha-1.0.data/purelib/helper.py": b"OK=1"})])
    ins.target.mkdir()
    (ins.target / "obsolete.py").write_text("old")
    ins.install([Requirement("alpha")])
    assert (ins.target / "helper.py").exists()
    assert not (ins.target / "obsolete.py").exists()
    assert "helper.py" in (ins.target / "alpha-1.0.dist-info/RECORD").read_text()


def test_include_constraints_cycle_and_unknown_options(tmp_path):
    (tmp_path / "base.txt").write_text("alpha>=1 # comment\n-r more.txt\n-c pins.txt\n")
    (tmp_path / "more.txt").write_text("beta; python_version >= '3.13'\n")
    (tmp_path / "pins.txt").write_text("alpha<2\n")
    reqs, limits = read_requirements(tmp_path / "base.txt")
    assert len(reqs) == 2 and str(limits[0]) == "alpha<2"
    (tmp_path / "more.txt").write_text("-r base.txt\n")
    with pytest.raises(InstallError, match="cycle"):
        read_requirements(tmp_path / "base.txt")
    (tmp_path / "more.txt").write_text("--index-url https://example.org\n")
    with pytest.raises(InstallError, match="Unsupported"):
        read_requirements(tmp_path / "base.txt")


def test_source_requirement_is_explicit_failure(tmp_path, monkeypatch):
    ins, calls = installer(tmp_path, monkeypatch, [])
    with pytest.raises(InstallError, match="Source/direct URL"):
        ins.install([Requirement("alpha @ git+https://example.org/alpha")])
    assert calls == []


def test_commit_failure_keeps_old_target(tmp_path, monkeypatch):
    from pathlib import Path
    ins, _ = installer(tmp_path, monkeypatch, [wheel("alpha")])
    ins.target.mkdir()
    (ins.target / "old.py").write_text("old")
    rename = Path.rename
    def fail_stage(path, dest):
        if path.name.startswith(".wheel-stage-"):
            raise PermissionError("locked")
        return rename(path, dest)
    monkeypatch.setattr(Path, "rename", fail_stage)
    with pytest.raises(PermissionError):
        ins.install([Requirement("alpha")])
    assert (ins.target / "old.py").read_text() == "old"
    assert not (tmp_path / ".wheel-install.lock").exists()


def test_source_only_release_is_not_downloaded(tmp_path, monkeypatch):
    entry, data = wheel("alpha")
    entry["packagetype"] = "sdist"
    ins, calls = installer(tmp_path, monkeypatch, [(entry, data)])
    with pytest.raises(InstallError, match="No compatible wheel"):
        ins.install([Requirement("alpha")])
    assert not any(c.endswith(".whl") for c in calls)


def test_resolver_backtracks_from_source_only_transitive(tmp_path, monkeypatch):
    ins, _ = installer(tmp_path, monkeypatch, [wheel("alpha", "2.0", ["other @ git+https://example.org/other"]), wheel("alpha", "1.0")])
    ins.install([Requirement("alpha")])
    assert (ins.target / "alpha-1.0.dist-info").exists()


def test_extras_expand_when_later_parent_requests_them(tmp_path, monkeypatch):
    ins, _ = installer(tmp_path, monkeypatch, [wheel("alpha", requires=["beta[fast]"]),
        wheel("beta", requires=['gamma; extra == "fast"']), wheel("gamma")])
    ins.install([Requirement("beta")])
    assert not (ins.target / "gamma").exists()
    ins.install([Requirement("alpha")])
    assert (ins.target / "gamma").exists()


def test_shared_file_conflict_preserves_target(tmp_path, monkeypatch):
    ins, _ = installer(tmp_path, monkeypatch, [wheel("alpha", files={"shared.py": b"alpha"}), wheel("beta", files={"shared.py": b"beta"})])
    ins.install([Requirement("alpha")])
    with pytest.raises(InstallError, match="Conflicting wheel files"):
        ins.install([Requirement("beta")])
    assert (ins.target / "shared.py").read_bytes() == b"alpha"


def test_inactive_root_and_constraint_markers(tmp_path, monkeypatch):
    ins, calls = installer(tmp_path, monkeypatch, [wheel("alpha")])
    ins.install([Requirement('alpha'), Requirement('absent; sys_platform == "linux"')],
                [Requirement('alpha<1; sys_platform == "linux"')])
    assert not any("absent" in c for c in calls)


def test_wheel_symlink_is_rejected(tmp_path, monkeypatch):
    import stat
    entry, data = wheel("alpha")
    modified = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(modified, "w") as dest:
        for info in source.infolist():
            if info.filename.endswith("__init__.py"):
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            dest.writestr(info, source.read(info.filename))
    data = modified.getvalue()
    entry["digests"]["sha256"] = hashlib.sha256(data).hexdigest()
    ins, _ = installer(tmp_path, monkeypatch, [(entry, data)])
    with pytest.raises(InstallError, match="symlinks"):
        ins.install([Requirement("alpha")])


def test_network_errors_are_actionable(tmp_path, monkeypatch):
    from wayfinder.runtime import wheel_installer as module
    def failed(*args, **kwargs):
        raise OSError("timed out")
    monkeypatch.setattr(module, "urlopen", failed)
    ins = WheelInstaller(tmp_path / "packages")
    with pytest.raises(InstallError, match="Network/download failure"):
        ins.fetch("https://pypi.org/pypi/example/json", 1000)


def test_stale_lock_is_reported_without_modifying_target(tmp_path, monkeypatch):
    ins, _ = installer(tmp_path, monkeypatch, [wheel("alpha")])
    (tmp_path / ".wheel-install.lock").touch()
    with pytest.raises(InstallError, match="Another dependency install"):
        ins.install([Requirement("alpha")])
    assert not ins.target.exists()


def test_scripts_headers_and_pth_are_installed_without_execution(tmp_path, monkeypatch):
    ins, _ = installer(tmp_path, monkeypatch, [wheel('alpha', files={
        'alpha-1.0.data/scripts/portserver.py': b'#!python\nraise RuntimeError("must not run")',
        'alpha-1.0.data/headers/example.h': b'/* header */',
        'alpha.pth': b'import must_not_be_imported_during_install\n',
    })])
    ins.install([Requirement('alpha')])
    assert (ins.target / 'Scripts/portserver.py').exists()
    assert (ins.target / 'Include/alpha/example.h').exists()
    assert (ins.target / 'alpha.pth').exists()


def test_windows_record_paths_are_normalized_and_verified(tmp_path, monkeypatch):
    entry, data = wheel('alpha')
    changed = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(changed, 'w') as dest:
        for name in source.namelist():
            value = source.read(name)
            if name.endswith('/RECORD'):
                value = value.replace(b'/', b'\\')
            dest.writestr(name, value)
    data = changed.getvalue()
    entry['digests']['sha256'] = hashlib.sha256(data).hexdigest()
    ins, _ = installer(tmp_path, monkeypatch, [(entry, data)])
    ins.install([Requirement('alpha')])
    assert (ins.target / 'alpha/__init__.py').exists()


def test_requirement_hash_allowlist_is_enforced(tmp_path, monkeypatch):
    entry, data = wheel('alpha')
    ins, _ = installer(tmp_path, monkeypatch, [(entry, data)])
    path = tmp_path / 'requirements.txt'
    path.write_text('alpha==1.0 \\\n --hash=sha256:' + '0'*64 + ' \\\n --hash=sha256:' + entry['digests']['sha256'])
    requirements, constraints = read_requirements(path)
    ins.install(requirements, constraints)
    path.write_text('alpha==1.0 --hash=sha256:' + '0'*64)
    requirements, constraints = read_requirements(path)
    with pytest.raises(InstallError, match='conflict|SHA256 allowlist'):
        ins.install(requirements, constraints)


def test_malformed_hash_option_is_not_silently_removed(tmp_path):
    path = tmp_path / 'requirements.txt'
    path.write_text('alpha==1.0 --hash=sha256:invalid')
    with pytest.raises(InstallError, match='Invalid or unsupported requirement'):
        read_requirements(path)
