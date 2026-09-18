"""APWorld preflight, isolated compatibility tests and reconstruction caching."""
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from pathlib import Path

from .apworld_catalog import STAGES, atomic_json, content_hash, inspect_world, select_world
from ..diagnostics import sanitize
from .. import __version__ as WAYFINDER_VERSION

# Increment whenever compatibility-test semantics change. Old reports are retained
# for diagnostics, but the UI marks them stale until the APWorld is retested.
COMPATIBILITY_TESTER_VERSION = 2

CORE_GENERATED = ('custom_worlds', 'host.yaml', '_persistent_storage.yaml', 'logs', 'output')


def report_directory():
    """Handle report directory."""
    from ..setup import APP_DATA_ROOT
    return APP_DATA_ROOT / 'apworld_reports'


def dependency_preflight(record, dependency_root=None):
    """Evaluate declared requirements without importing packages or worlds."""
    from packaging.requirements import Requirement, InvalidRequirement
    from packaging.utils import canonicalize_name
    paths = ([str(dependency_root)] if dependency_root else []) + sys.path
    installed = {}
    for dist in importlib.metadata.distributions(path=paths):
        name = dist.metadata.get('Name')
        if name:
            installed.setdefault(canonicalize_name(name), dist)
    results = []
    pending = list(record.requirements)
    seen = set()
    while pending:
        entry = pending.pop(0)
        identity = (entry['requirement'], tuple(entry.get('extras_context', [])), entry.get('advisory',False))
        if identity in seen:
            continue
        seen.add(identity)
        item = dict(entry, installed='', state='Missing')
        try:
            requirement = Requirement(entry['requirement'])
            extras = entry.get('extras_context', [''])
            if requirement.marker and not any(requirement.marker.evaluate({'extra':extra}) for extra in extras):
                item['state'] = 'Not required on this platform'
            elif requirement.url:
                from .source_recipes import source_candidate
                dist = installed.get(canonicalize_name(requirement.name))
                expected = source_candidate(canonicalize_name(requirement.name), [requirement])
                if expected is None:
                    from .bundled_wheels import source_entry
                    expected = source_entry(canonicalize_name(requirement.name), requirement)
                provenance = json.loads(dist.read_text('direct_url.json') or '{}') if dist else {}
                item['installed'] = dist.version if dist else ''
                recipe = (expected.get('recipe') or expected.get('source', {})) if expected else {}
                item['state'] = ('Ready' if dist and recipe
                    and dist.version == recipe['version']
                    and provenance.get('vcs_info', {}).get('commit_id') == recipe['commit']
                    and provenance.get('url') == 'https://github.com/' + recipe['repo']
                    and provenance.get('wayfinder_archive_sha256') == recipe['sha256']
                    else 'Unverified direct URL; resolve explicitly')
            else:
                dist = installed.get(canonicalize_name(requirement.name))
                item['installed'] = dist.version if dist else ''
                if item['installed']:
                    item['state'] = 'Ready' if requirement.specifier.contains(item['installed'], prereleases=True) else 'Version mismatch'
                    # Do not recursively attribute an installed distribution's entire
                    # metadata graph (including optional/dev extras) to the APWorld.
                    # The wheel installer resolves required transitives during installation; this report
                    # intentionally shows the world's declared/direct inferred ownership.
        except (InvalidRequirement, ValueError) as exc:
            item['state'] = 'Unverified requirement: ' + str(exc)
        if entry.get('advisory'):
            item['state'] += ' (inferred import; may be optional)'
        results.append(item)
    return results


def require_dependencies(record, dependency_root=None):
    """Handle require dependencies."""
    results = dependency_preflight(record, dependency_root)
    failures = [r for r in results if not r.get('advisory') and r['state'] not in {'Ready', 'Not required on this platform'}]
    if failures:
        raise RuntimeError('Dependency preflight failed for ' + record.game + ': ' + '; '.join(r['requirement'] + ' — ' + r['state'] for r in failures))
    return results


_hash_cache = {}
_hash_lock = threading.Lock()


def tree_fingerprint(root, exclude=()):
    """Stat-indexed content cache; detect additions, removals and replaced files."""
    root = Path(root)
    excluded = {'__pycache__', '.git', *exclude}
    files = []
    if root.exists():
        for directory, folders, names in os.walk(root):
            folders[:] = sorted(name for name in folders if name not in excluded)
            files.extend(Path(directory) / name for name in names if name not in excluded and not name.endswith('.pyc'))
    files.sort()
    signature_rows = []
    for path in files:
        stat = path.stat()
        signature_rows.append((str(path.relative_to(root)), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    signature = tuple(signature_rows)
    key = (str(root.resolve()), tuple(exclude))
    with _hash_lock:
        if key in _hash_cache and _hash_cache[key][0] == signature:
            return _hash_cache[key][1]
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(content_hash(path).encode())
    result = digest.hexdigest()
    with _hash_lock:
        _hash_cache[key] = signature, result
    return result


def reconstruction_key(record, core_root, dependency_root, context, *, environment=None):
    """Handle reconstruction key."""
    if environment is not None:
        parts = dict(world=record.sha256, environment=environment, context=context)
        return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()
    distributions = sorted((d.metadata.get('Name', ''), d.version) for d in importlib.metadata.distributions())
    parts = dict(world=record.sha256, core=tree_fingerprint(core_root, CORE_GENERATED),
                 dependencies=tree_fingerprint(dependency_root), installed=distributions,
                 python=sys.version, context=context)
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def environment_identity(core_root, dependency_root):
    """Handle environment identity."""
    return dict(core=tree_fingerprint(core_root, CORE_GENERATED), dependencies=tree_fingerprint(dependency_root),
                python=sys.version, installed=sorted({(d.metadata.get('Name', ''), d.version) for d in importlib.metadata.distributions(path=[str(dependency_root)] + sys.path)}))


class ReconstructionCache:
    """Bounded, runtime-local graphs. Callers include connection identity in keys.

    Python graphs/rule closures cannot safely be pickled or copied across seeds.
    Only the runtime's serialized task worker accesses these entries.
    """
    def __init__(self, capacity=2):
        """Handle init."""
        self.entries = OrderedDict()
        self.capacity = capacity

    def get_or_build(self, key, build):
        """Return get or build."""
        if key in self.entries:
            self.entries.move_to_end(key)
            return self.entries[key], True
        value = build()
        self.entries[key] = value
        while len(self.entries) > self.capacity:
            self.entries.popitem(last=False)
        return value, False


def save_report(report, path=None):
    """Handle save report."""
    path = Path(path) if path else report_directory() / (report.get('id', uuid.uuid4().hex) + '.json')
    atomic_json(path, sanitize(report))
    return str(path)


def persist_exception(exc, **context):
    """Handle persist exception."""
    report = dict(id=uuid.uuid4().hex, time=time.time(), outcome='Failed',
                  error=str(exc), traceback=''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)), **context)
    return save_report(report)


def compatibility_child(request_path):
    """Handle compatibility child."""
    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    report = dict(id=request['id'], path=request['world'], time=time.time(), stages=[], outcome='Running',
                  tester_version=COMPATIBILITY_TESTER_VERSION, wayfinder_version=WAYFINDER_VERSION,
                  profile='Default options; no live server slot data. Actual seed compatibility requires a live reconstruction.')
    runtime = None
    def stage(name):
        """Handle stage."""
        report['stages'].append(name)
        save_report(report, request['report'])
    try:
        stage('Discovered')
        from .apworld_catalog import core_version
        record = inspect_world(request['world'], ap_version=core_version(request['core']))
        report.update(game=record.game, world_hash=record.sha256, version=record.version)
        report['environment'] = environment_identity(request['core'], request['dependencies'])
        if not record.compatible:
            raise RuntimeError(record.error)
        stage('Manifest')
        report['identity_method'] = 'archipelago.json' if record.manifest else 'Legacy literal fallback'
        staged = select_world(record.game, request['core'], request['world'])
        if staged.sha256 != record.sha256:
            raise RuntimeError('APWorld changed before testing')
        stage('Synced')
        report['dependencies'] = dependency_preflight(record, request['dependencies'])
        require_dependencies(record, request['dependencies'])
        stage('Dependencies')
        from .server import NativeRuntime
        runtime = NativeRuntime(0, request['core'], '')
        runtime.bootstrap_ap()
        from .world_loader import ensure_game_loaded
        ensure_game_loaded(record.game, request['core'], selected_path=request['world'])
        stage('Imported')
        from .world_builder import build_world
        built = build_world(record.game, 'WayFinderCompatibilityTest', {})
        regions = list(built.multiworld.get_regions(built.player))
        locations = list(built.multiworld.get_locations(built.player))
        if not regions:
            raise RuntimeError('Reconstruction produced no regions')
        if any(getattr(loc, 'parent_region', None) is None for loc in locations):
            raise RuntimeError('Reconstruction contains a location without a region')
        from collections import Counter
        from .snapshot import _evaluate_logic_sets
        normal, glitch, _ = _evaluate_logic_sets(multiworld=built.multiworld, world=built.world, player=built.player,
                             inventory=Counter(), checked_names=set(), built=built, force_full=True)
        errors = list(getattr(normal, 'errors', [])) + list(getattr(glitch, 'errors', []))
        if errors:
            raise RuntimeError('Logic evaluation errors: ' + '; '.join(map(str, errors)))
        from types import SimpleNamespace
        from .snapshot import build_snapshot
        from ..connection.identity import validate_snapshot, seed_identity
        from ..connection.protocol import encode_snapshot, decode_snapshot
        context = SimpleNamespace(game=record.game, auth=built.slot_name, slot=1, team=0, slot_data={},
                                  server_address='', seed_name='', items_received=[], checked_locations=set(),
                                  missing_locations=set(getattr(built.world, 'location_id_to_name', {})))
        snapshot = build_snapshot(context, built, sequence=1)
        snapshot.update(seed_identity=seed_identity(context,built.world), runtime_id=request['id'], snapshot_sequence=1)
        validate_snapshot(decode_snapshot(encode_snapshot(snapshot)), True)
        report['snapshot_validation'] = 'Passed'
        stage('Reconstructed')
        report.update(outcome='Passed (default profile)', regions=len(regions), locations=len(locations), warnings=built.warnings,
                      cache_key=reconstruction_key(record, request['core'], request['dependencies'], {'profile':'default'}))
    except BaseException as exc:
        report.update(outcome='Failed', error=str(exc), traceback=traceback.format_exc())
    finally:
        save_report(report, request['report'])
        if runtime:
            runtime.jobs.close()
    return 0 if report['outcome'].startswith('Passed') else 1


def _remove_previous_reports(record):
    """Remove cached reports for this exact staged APWorld before a fresh test.

    Reports are diagnostic cache entries, not authoritative test state. Removing the
    old matching hash prevents a stale failure from surviving alongside a new run.
    """
    folder = report_directory()
    if not folder.exists():
        return
    for path in folder.glob('*.json'):
        if path.name.endswith('.request.json'):
            continue
        try:
            previous = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if previous.get('path') == record.path and previous.get('world_hash') == record.sha256:
            try:
                transcript = previous.get('transcript')
                path.unlink(missing_ok=True)
                if transcript:
                    Path(transcript).unlink(missing_ok=True)
            except OSError:
                # A locked historical report must never prevent a fresh test.
                _ignored("intentional best-effort fallback")


def run_compatibility_test(record, core_root, dependency_root, cancel=None, timeout=180):
    """A new process per world; timeout/crash/abort retains completed stages."""
    from .process_manager import internal_child_command
    _remove_previous_reports(record)
    ident = uuid.uuid4().hex
    folder = report_directory()
    folder.mkdir(parents=True, exist_ok=True)
    report_path, request_path = folder / (ident + '.json'), folder / (ident + '.request.json')
    request = dict(id=ident, world=record.path, core=str(core_root), dependencies=str(dependency_root), report=str(report_path))
    atomic_json(request_path, request)
    transcript = folder / (ident + '.log')
    outcome = ''
    process = None
    try:
        with transcript.open('w', encoding='utf-8') as output:
            process = subprocess.Popen(internal_child_command('--test-apworld', str(request_path)), stdout=output,
                stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                env=dict(os.environ, PYTHONIOENCODING='utf-8'), cwd=folder)
            started = time.monotonic()
            while process.poll() is None:
                if cancel is not None and cancel.is_set():
                    outcome = 'Cancelled'
                    break
                if time.monotonic() - started > timeout:
                    outcome = 'Timed out'
                    break
                time.sleep(.1)
            if outcome:
                process.kill()
            process.wait()
    except Exception as exc:
        outcome = 'Failed to launch: ' + str(exc)
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        request_path.unlink(missing_ok=True)
    try:
        report = json.loads(report_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        report = dict(id=ident, path=record.path, game=record.game, world_hash=record.sha256, stages=[])
    if outcome or report.get('outcome') in (None, 'Running'):
        report['outcome'] = outcome or 'Process crashed (exit ' + str(process.returncode if process else '?') + ')'
    report['transcript'] = str(transcript)
    # Retain full stack traces, while applying the same secret redaction as diagnostics.
    if transcript.exists():
        transcript.write_text(sanitize(transcript.read_text(encoding='utf-8', errors='replace')), encoding='utf-8')
    save_report(report, report_path)
    report['report_path'] = str(report_path)
    return report
