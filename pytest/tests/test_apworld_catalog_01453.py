"""Provide test apworld catalog 01453 support."""
import json
import sys
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from wayfinder.runtime import apworld_catalog as catalog
from wayfinder.runtime import apworld_compatibility as compatibility


def world(root, name='demo', game='Demo', version='1.0.0', **manifest):
    """Handle world."""
    folder = root / 'custom_worlds'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name + '.apworld')
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(name + '/__init__.py', "raise RuntimeError('Discovery must not execute me')")
        archive.writestr('archipelago.json', json.dumps(dict(game=game, world_version=version, **manifest)))
    (root / 'Utils.py').write_text('__version__ = "0.6.7"', encoding='utf-8')
    return path


def test_canonical_manifest_never_executes_python_or_uses_container_version(tmp_path):
    """Handle test canonical manifest never executes python or uses container version."""
    path = world(tmp_path, version='2.3.4', compatible_version=7)
    record = catalog.inspect_world(path)
    assert record.game == 'Demo'
    assert record.version == '2.3.4'
    assert record.module == 'demo'
    assert record.state == 'Manifest'
    assert not record.error


def test_unversioned_manifest_not_container_version(tmp_path):
    """Handle test unversioned manifest not container version."""
    path = world(tmp_path)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('package/__init__.py', '')
        archive.writestr('archipelago.json', json.dumps({'game':'Demo','version':7,'compatible_version':7}))
    record = catalog.inspect_world(path)
    assert record.version == '' and record.module == 'package'


def test_broken_archive_and_invalid_manifest_do_not_block_good_world(tmp_path):
    """Handle test broken archive and invalid manifest do not block good world."""
    good = world(tmp_path)
    (good.parent / 'broken.apworld').write_bytes(b'broken')
    invalid = world(tmp_path, 'invalid', version='latest')
    records = catalog.discover(tmp_path)
    assert len(records) == 3
    assert sum(bool(r.error) for r in records) == 2
    assert catalog.select_world('Demo', tmp_path).path == str(good.resolve())


def test_duplicate_selection_highest_compatible_version(tmp_path):
    """Handle test duplicate selection highest compatible version."""
    world(tmp_path, 'a', version='1.0.0')
    best = world(tmp_path, 'b', version='2.10.0', minimum_ap_version='0.6.0', maximum_ap_version='0.6.9')
    world(tmp_path, 'c', version='3.0.0', minimum_ap_version='0.7.0')
    assert catalog.select_world('Demo', tmp_path).path == str(best.resolve())
    records = catalog.discover(tmp_path)
    assert all(r.duplicate_count == 2 for r in records)
    assert sum(r.selected for r in records) == 1


def test_aliases_normalization_and_ambiguous_fallback(tmp_path):
    """Handle test aliases normalization and ambiguous fallback."""
    world(tmp_path, game='Demo: Game', aliases=['Old Title'])
    assert catalog.select_world('Old Title', tmp_path).game == 'Demo: Game'
    assert catalog.select_world('demo game', tmp_path).game == 'Demo: Game'
    world(tmp_path, 'other', game='Other', aliases=['Old Title'])
    with pytest.raises(RuntimeError, match='Ambiguous'):
        catalog.select_world('Old Title', tmp_path)


def test_directory_and_worlds_folder_archive_discovery(tmp_path):
    """Handle test directory and worlds folder archive discovery."""
    path = world(tmp_path)
    folder = tmp_path / 'worlds'
    folder.mkdir()
    path.rename(folder / path.name)
    legacy = folder / 'legacy'
    legacy.mkdir()
    (legacy / '__init__.py').write_text('class World:\n    game = "Legacy"\n', encoding='utf-8')
    assert {r.game for r in catalog.discover(tmp_path)} == {'Demo', 'Legacy'}


def test_source_to_runtime_stale_hash_comparison(tmp_path):
    """Handle test source to runtime stale hash comparison."""
    external, runtime = tmp_path / 'external', tmp_path / 'runtime'
    source = world(external)
    target = world(runtime)
    catalog.atomic_copy(source, target)
    assert all(r.sync_state == 'Matching' for r in catalog.inventory(runtime, external))
    world(external, version='2.0.0')
    assert all(r.sync_state == 'Stale copy' for r in catalog.inventory(runtime, external))
    catalog.atomic_copy(source, target)
    assert all(r.sync_state == 'Matching' for r in catalog.inventory(runtime, external))


def test_atomic_copy_preserves_last_good_on_replace_failure(tmp_path, monkeypatch):
    """Handle test atomic copy preserves last good on replace failure."""
    source, destination = tmp_path / 'source', tmp_path / 'destination'
    source.write_bytes(b'new'); destination.write_bytes(b'old')
    def fail(*args):
        """Handle fail."""
        assert destination.read_bytes() == b'old'
        raise OSError('busy')
    monkeypatch.setattr(catalog.os, 'replace', fail)
    with pytest.raises(OSError):
        catalog.atomic_copy(source, destination)
    assert destination.read_bytes() == b'old'
    assert len(list(tmp_path.iterdir())) == 2


def test_dependency_requirements_ownership_nested_includes_and_markers(tmp_path):
    """Handle test dependency requirements ownership nested includes and markers."""
    path = world(tmp_path)
    with zipfile.ZipFile(path, 'a') as archive:
        archive.writestr('demo/requirements.txt', '-r dependencies.txt\npackaging>=1\n')
        archive.writestr('demo/dependencies.txt', 'wayfinder-nonexistent-package>=4\nnot-on-this-host; python_version < "1"\n')
    record = catalog.inspect_world(path)
    results = compatibility.dependency_preflight(record)
    assert all(r['owner'] == 'Demo' for r in results)
    assert {r['state'] for r in results} == {'Ready', 'Missing', 'Not required on this platform'}
    with pytest.raises(RuntimeError, match='wayfinder-nonexistent-package'):
        compatibility.require_dependencies(record)


def test_unsafe_requirements_include_is_isolated(tmp_path):
    """Handle test unsafe requirements include is isolated."""
    path = world(tmp_path)
    with zipfile.ZipFile(path, 'a') as archive:
        archive.writestr('demo/requirements.txt', '-r ../../outside.txt')
    record = catalog.inspect_world(path)
    assert not record.compatible and 'Unsafe' in record.error


def test_reconstruction_key_invalidates_for_world_core_deps_and_seed(tmp_path):
    """Handle test reconstruction key invalidates for world core deps and seed."""
    core, deps = tmp_path / 'core', tmp_path / 'dependencies'
    deps.mkdir()
    record = catalog.inspect_world(world(core))
    first = compatibility.reconstruction_key(record, core, deps, {'seed':'A','connection':'1'})
    assert first == compatibility.reconstruction_key(record, core, deps, {'connection':'1','seed':'A'})
    assert first != compatibility.reconstruction_key(record, core, deps, {'seed':'B','connection':'1'})
    (deps / 'package.py').write_text('value=1', encoding='utf-8')
    second = compatibility.reconstruction_key(record, core, deps, {'seed':'A','connection':'1'})
    assert first != second
    (core / 'BaseClasses.py').write_text('value=2', encoding='utf-8')
    third = compatibility.reconstruction_key(record, core, deps, {'seed':'A','connection':'1'})
    assert second != third
    record.sha256 = 'changed-world'
    assert third != compatibility.reconstruction_key(record, core, deps, {'seed':'A','connection':'1'})


def test_graph_cache_is_bounded_and_does_not_cache_failures():
    """Handle test graph cache is bounded and does not cache failures."""
    cache = compatibility.ReconstructionCache(1)
    first, hit = cache.get_or_build('a', object)
    assert not hit
    assert cache.get_or_build('a', object) == (first, True)
    cache.get_or_build('b', object)
    assert 'a' not in cache.entries
    with pytest.raises(ValueError):
        cache.get_or_build('c', lambda: (_ for _ in ()).throw(ValueError('failed')))
    assert 'c' not in cache.entries


def test_complete_traceback_persisted_with_secrets_redacted(tmp_path, monkeypatch):
    """Handle test complete traceback persisted with secrets redacted."""
    monkeypatch.setattr(compatibility, 'report_directory', lambda: tmp_path)
    try:
        raise RuntimeError('password=hunter2 token=private')
    except RuntimeError as exc:
        path = compatibility.persist_exception(exc, game='Demo')
    report = json.loads(Path(path).read_text(encoding='utf-8'))
    assert 'RuntimeError' in report['traceback'] and 'raise RuntimeError' in report['traceback']
    assert 'hunter2' not in json.dumps(report) and 'private' not in json.dumps(report)


def test_crashed_child_does_not_block_next_test(tmp_path, monkeypatch):
    """Handle test crashed child does not block next test."""
    record = catalog.inspect_world(world(tmp_path))
    monkeypatch.setattr(compatibility, 'report_directory', lambda: tmp_path / 'reports')
    from wayfinder.runtime import process_manager
    monkeypatch.setattr(process_manager, 'internal_child_command', lambda *args: [sys.executable, '-c', 'import os; os._exit(9)'])
    failed = compatibility.run_compatibility_test(record, tmp_path, tmp_path / 'deps')
    assert 'crashed' in failed['outcome']
    code = "import json,sys;from pathlib import Path;r=json.loads(Path(sys.argv[1]).read_text());Path(r['report']).write_text(json.dumps(dict(r,path=r['world'],outcome='Passed (default profile)',stages=['Discovered'])))"
    monkeypatch.setattr(process_manager, 'internal_child_command', lambda mode, path: [sys.executable, '-c', code, path])
    passed = compatibility.run_compatibility_test(record, tmp_path, tmp_path / 'deps')
    assert passed['outcome'].startswith('Passed')
    assert not Path(failed['report_path']).exists() and Path(passed['report_path']).exists()


@pytest.mark.parametrize('cancelled', [False, True])
def test_child_timeout_and_cancel_are_bounded(tmp_path, monkeypatch, cancelled):
    """Handle test child timeout and cancel are bounded."""
    record = catalog.inspect_world(world(tmp_path))
    monkeypatch.setattr(compatibility, 'report_directory', lambda: tmp_path / 'reports')
    from wayfinder.runtime import process_manager
    monkeypatch.setattr(process_manager, 'internal_child_command', lambda *args: [sys.executable, '-c', 'import time; time.sleep(60)'])
    cancel = threading.Event()
    if cancelled:
        cancel.set()
    report = compatibility.run_compatibility_test(record, tmp_path, tmp_path / 'deps', cancel, timeout=.1)
    assert report['outcome'] == ('Cancelled' if cancelled else 'Timed out')


def test_loader_imports_only_selected_world_and_refuses_hot_replacement(tmp_path):
    """Handle test loader imports only selected world and refuses hot replacement."""
    from wayfinder.runtime.world_loader import install_minimal_worlds_package, ensure_game_loaded
    folder = tmp_path / 'worlds'
    folder.mkdir()
    (folder / 'AutoWorld.py').write_text('class AutoWorldRegister:\n    world_types = {}\n', encoding='utf-8')
    old = world(tmp_path, 'old', version='1.0.0')
    chosen = world(tmp_path, 'chosen', version='2.0.0')
    with zipfile.ZipFile(chosen, 'w') as archive:
        archive.writestr('chosen/archipelago.json', json.dumps({'game':'Demo','world_version':'2.0.0'}))
        archive.writestr('chosen/__init__.py', "from worlds.AutoWorld import AutoWorldRegister\nclass World:\n    game='Demo'\nAutoWorldRegister.world_types['Demo']=World\n")
    saved = {k:v for k,v in sys.modules.items() if k == 'worlds' or k.startswith('worlds.')}
    try:
        install_minimal_worlds_package(tmp_path)
        loaded = ensure_game_loaded('demo', tmp_path)
        assert loaded._wayfinder_source_path == str(chosen.resolve())
        assert 'worlds.old' not in sys.modules
        with zipfile.ZipFile(chosen, 'a') as archive:
            archive.writestr('chosen/new.txt', 'changed')
        with pytest.raises(RuntimeError, match='Restart'):
            ensure_game_loaded('Demo', tmp_path)
    finally:
        for key in list(sys.modules):
            if key == 'worlds' or key.startswith('worlds.'):
                del sys.modules[key]
        sys.modules.update(saved)


@pytest.mark.parametrize('logic_error', [False, True])
def test_compatibility_stages_include_logic_and_snapshot_validation(tmp_path, monkeypatch, logic_error):
    """Handle test compatibility stages include logic and snapshot validation."""
    path = world(tmp_path)
    request = dict(id='test', world=str(path), core=str(tmp_path), dependencies=str(tmp_path / 'deps'), report=str(tmp_path / 'report.json'))
    request_path = tmp_path / 'request.json'
    request_path.write_text(json.dumps(request), encoding='utf-8')
    from wayfinder.runtime import server, world_loader, world_builder, snapshot
    monkeypatch.setattr(server.NativeRuntime, 'bootstrap_ap', lambda self: None)
    monkeypatch.setattr(world_loader, 'ensure_game_loaded', lambda *args, **kw: None)
    built = SimpleNamespace(multiworld=SimpleNamespace(get_regions=lambda p:[object()],get_locations=lambda p:[]),
                            world=SimpleNamespace(location_id_to_name={}),player=1,slot_name='Test',warnings=[])
    monkeypatch.setattr(world_builder, 'build_world', lambda *args, **kw: built)
    monkeypatch.setattr(snapshot, '_evaluate_logic_sets', lambda **kw:(SimpleNamespace(errors=['broken rule'] if logic_error else []),None,''))
    calls = []
    def build_snapshot(*args, **kw):
        """Return build snapshot."""
        calls.append(True)
        return dict(connected=False,locations=[],inventory=[],snapshot_sequence=1,game=args[0].game,slot_name=args[0].auth,team=0,server='')
    monkeypatch.setattr(snapshot, 'build_snapshot', build_snapshot)
    result = compatibility.compatibility_child(request_path)
    report = json.loads(Path(request['report']).read_text(encoding='utf-8'))
    if logic_error:
        assert result == 1 and 'broken rule' in report['traceback']
        assert report['stages'][-1] == 'Imported'
    else:
        assert result == 0 and report['stages'] == list(catalog.STAGES[:-1])
        assert report['snapshot_validation'] == 'Passed' and calls
        assert 'Active' not in report['stages']


def test_world_system_exit_does_not_kill_job_queue():
    """Handle test world system exit does not kill job queue."""
    from wayfinder.runtime.reliability import RuntimeJobs
    errors = []
    done = threading.Event()
    jobs = RuntimeJobs(lambda token, exc: errors.append(exc))
    try:
        jobs.submit('world', lambda token: (_ for _ in ()).throw(SystemExit(2)))
        jobs.submit('next', lambda token: done.set())
        assert done.wait(2)
        assert isinstance(errors[0], SystemExit)
    finally:
        jobs.close()


def test_dependency_preflight_reports_declared_ownership_only(tmp_path):
    """Handle test dependency extras follow transitive ownership."""
    deps = tmp_path / 'deps'
    for name, metadata in [('parent-1.0.dist-info','Name: parent\nVersion: 1.0\nProvides-Extra: extra\nRequires-Dist: child>=2; extra == "extra"\n'),
                           ('child-2.1.dist-info','Name: child\nVersion: 2.1\n')]:
        folder = deps / name
        folder.mkdir(parents=True)
        (folder / 'METADATA').write_text('Metadata-Version: 2.1\n' + metadata, encoding='utf-8')
    record = catalog.WorldRecord('test', game='Demo', requirements=[dict(owner='Demo', requirement='parent[extra]>=1', file='requirements.txt')])
    results = compatibility.require_dependencies(record, deps)
    assert len(results) == 1
    assert results[0]['owner'] == 'Demo' and results[0]['state'] == 'Ready'
    assert results[0]['requirement'] == 'parent[extra]>=1'
