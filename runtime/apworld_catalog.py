"""Import-free APWorld inventory and content identities.

An archive's container version is deliberately distinct from world_version.
Discovery never executes a world's Python code.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path, PurePosixPath

STAGES = ('Discovered', 'Manifest', 'Synced', 'Dependencies', 'Imported', 'Reconstructed', 'Active')


def content_hash(path):
    """Handle content hash."""
    path = Path(path)
    digest = hashlib.sha256()
    files = [path] if path.is_file() else sorted(p for p in path.rglob('*') if p.is_file()
        and not any(part in {'__pycache__', '.git'} for part in p.parts) and p.suffix != '.pyc')
    for item in files:
        if item != path:
            digest.update(item.relative_to(path).as_posix().encode())
        with item.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path, value):
    """Handle atomic json."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_copy(source, destination):
    """Keep the last complete copy if copying or verification fails."""
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + destination.name, dir=destination.parent)
    os.close(fd)
    try:
        before = content_hash(source)
        shutil.copy2(source, temporary)
        if content_hash(temporary) != before or content_hash(source) != before:
            raise OSError('APWorld changed during sync: ' + source.name)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def version_tuple(value):
    """Handle version tuple."""
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', str(value or ''))
    return tuple(map(int, match.groups())) if match else (-1, -1, -1)


def core_version(root):
    """Read the installed Archipelago core version without importing Archipelago.

    WayFinder normally receives the ``.../archipelago_core/source`` directory,
    but older settings and diagnostics can point at its parent.  Archipelago's
    Utils.py has also used both a literal ``__version__`` and related core
    version assignments over time.  Keep discovery import-free and tolerate
    those layouts so APWorld compatibility does not become "version unknown".
    """
    root = Path(root)
    candidates = [root / 'Utils.py', root / 'source' / 'Utils.py']
    version_names = {'core_version', '__version__'}
    for utils_path in candidates:
        try:
            text = utils_path.read_text(encoding='utf-8-sig')
            tree = ast.parse(text)
            values = {}
            for node in tree.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [target.id for target in targets if isinstance(target, ast.Name)]
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    # Handles aliases such as ``core_version = __version__``.
                    if isinstance(node.value, ast.Name):
                        value = values.get(node.value.id)
                    else:
                        value = None
                for name in names:
                    if value is not None:
                        values[name] = value
            for name in version_names:
                value = str(values.get(name, '') or '')
                match = re.search(r'(?<!\d)(\d+\.\d+\.\d+)(?!\d)', value)
                if match:
                    return match.group(1)
            # Last-resort static match for unusual but still literal source.
            match = re.search(r'(?m)^\s*(?:core_version|__version__)\s*(?::[^=]+)?=\s*[\"\'](\d+\.\d+\.\d+)[\"\']', text)
            if match:
                return match.group(1)
        except (OSError, SyntaxError, UnicodeError):
            continue
    return ''


def normal_game(value):
    """Handle normal game."""
    return re.sub(r'[^a-z0-9]', '', str(value).casefold())


@dataclass
class WorldRecord:
    """Provide world record behavior."""
    path: str
    source: str = 'WayFinder'
    game: str = ''
    module: str = ''
    version: str = ''
    sha256: str = ''
    manifest: dict = field(default_factory=dict)
    aliases: list = field(default_factory=list)
    requirements: list = field(default_factory=list)
    state: str = 'Discovered'
    error: str = ''
    compatible: bool = True
    selected: bool = False
    duplicate_count: int = 0
    mirror_path: str = ''
    mirror_hash: str = ''
    sync_state: str = ''

    def to_dict(self):
        """Handle to dict."""
        return asdict(self)


def inspect_world(path, source='WayFinder', ap_version='', *, details=True):
    """Handle inspect world."""
    record = WorldRecord(str(Path(path).resolve()), source=source)
    archive = None
    try:
        path = Path(path)
        record.sha256 = content_hash(path) if details else ""
        if path.is_dir():
            names = sorted(p.relative_to(path).as_posix() for p in path.rglob('*') if p.is_file())
            read = lambda name: (path / name).read_text(encoding='utf-8-sig')
            record.module = path.name
        else:
            archive = zipfile.ZipFile(path)
            names = sorted(archive.namelist())
            read = lambda name: archive.read(name).decode('utf-8-sig')
            roots = [n.split('/')[0] for n in names if n.count('/') == 1 and n.endswith('/__init__.py')]
            if len(set(roots)) != 1:
                raise ValueError('Expected one top-level Python package')
            record.module = roots[0]
        manifests = [n for n in names if n == 'archipelago.json' or n == record.module + '/archipelago.json']
        for name in manifests:
            manifest = json.loads(read(name))
            if not isinstance(manifest, dict):
                raise ValueError('Manifest must be a JSON object')
            if record.game and manifest.get('game') and record.game != manifest['game']:
                raise ValueError('Conflicting manifest game identities')
            record.manifest.update(manifest)
            record.game = record.manifest.get('game', '')
        if record.manifest:
            if not isinstance(record.game, str) or not record.game.strip():
                raise ValueError('Manifest requires a nonempty game name')
            record.state = 'Manifest'
            record.version = str(record.manifest.get('world_version', ''))
            for key in ('world_version', 'minimum_ap_version', 'maximum_ap_version'):
                if key in record.manifest and version_tuple(record.manifest[key]) == (-1, -1, -1):
                    raise ValueError('Invalid ' + key + ': expected major.minor.build')
            aliases = record.manifest.get('game_aliases', record.manifest.get('aliases', []))
            record.aliases = [v for v in aliases if isinstance(v, str)] if isinstance(aliases, list) else []
        else:
            # Legacy worlds have no manifest. Literal assignments are safe to inspect.
            for name in sorted((n for n in names if n.endswith('.py')), key=lambda n: (not n.endswith('__init__.py'), n)):
                try:
                    for node in ast.walk(ast.parse(read(name))):
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
                        if any(isinstance(t, ast.Name) and t.id == 'game' for t in targets):
                            value = ast.literal_eval(node.value)
                            if isinstance(value, str) and value:
                                record.game = value
                                break
                except (SyntaxError, ValueError, UnicodeError):
                    continue
                if record.game:
                    break
            if not record.game:
                # Some built-in Archipelago worlds keep their public game name in
                # a constants module and reference it from the World subclass, e.g.
                # ``game = OTHER.game_name`` (shapez in Archipelago 0.6.7).  That is
                # still statically discoverable without importing the world.
                # Collect literal ``game_name`` constants across the package and
                # accept the value only when it is unambiguous.
                game_name_literals = set()
                for name in (n for n in names if n.endswith('.py')):
                    try:
                        tree = ast.parse(read(name))
                    except (SyntaxError, UnicodeError):
                        continue
                    for node in ast.walk(tree):
                        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                            continue
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        if not any(
                            (isinstance(target, ast.Name) and target.id == 'game_name')
                            or (isinstance(target, ast.Attribute) and target.attr == 'game_name')
                            for target in targets
                        ):
                            continue
                        try:
                            value = ast.literal_eval(node.value)
                        except (ValueError, TypeError):
                            continue
                        if isinstance(value, str) and value.strip():
                            game_name_literals.add(value.strip())
                if len(game_name_literals) == 1:
                    record.game = next(iter(game_name_literals))
                elif len(game_name_literals) > 1:
                    raise ValueError('Ambiguous static game_name identities: ' + ', '.join(sorted(game_name_literals)))
            if not record.game:
                raise ValueError('No manifest or statically resolvable game identity found')
        if details:
            seen = set()
            def requirements(name):
                """Handle requirements."""
                if name in seen:
                    return
                seen.add(name)
                for line in read(name).splitlines():
                    line = re.split(r'\s+#', line, maxsplit=1)[0].strip()
                    if not line or line.startswith('#'):
                        continue
                    if line.startswith(('-r ', '--requirement ')):
                        child = PurePosixPath(name).parent / line.split(maxsplit=1)[1]
                        if '..' in child.parts or child.is_absolute():
                            raise ValueError('Unsafe requirements include: ' + str(child))
                        requirements(str(child))
                    else:
                        record.requirements.append({'owner': record.game, 'requirement': line, 'file': name})
            for name in names:
                if PurePosixPath(name).name == 'requirements.txt':
                    requirements(name)
            # Undeclared imports are advisory: AST cannot tell optional/client-only
            # code from a dependency required for reconstruction.
            from .dependency_manager import _iter_python_imports, _is_stdlib, _available_in_core, COMMON_IMPORT_TO_DIST, AP_INTERNAL
            imported = set()
            vendor = {record.module}
            for name in names:
                parts = PurePosixPath(name).parts
                vendor.update(parts[:-1])
                if name.endswith('.py'):
                    vendor.add(PurePosixPath(name).stem)
                    try:
                        imported.update(_iter_python_imports(read(name)))
                    except UnicodeError:
                        continue
            declared_names = {re.split(r'[<>=!~\[; @]', r['requirement'], maxsplit=1)[0].lower().replace('_','-') for r in record.requirements}
            for module in sorted(imported - vendor - AP_INTERNAL):
                if _is_stdlib(module) or _available_in_core(module, path.parent.parent):
                    continue
                distribution = COMMON_IMPORT_TO_DIST.get(module, module)
                if distribution.lower().replace('_','-') not in declared_names:
                    record.requirements.append(dict(owner=record.game, requirement=distribution, file='Python import: '+module, advisory=True))
        for key, op in (('minimum_ap_version', lambda a,b:a<b), ('maximum_ap_version', lambda a,b:a>b)):
            bound = record.manifest.get(key)
            if bound and (not ap_version or op(version_tuple(ap_version), version_tuple(bound))):
                record.compatible = False
                record.error = f'Core {ap_version or "version unknown"}: requires {key} {bound}'
    except Exception as exc:
        record.compatible = False
        record.error = f'{type(exc).__name__}: {exc}'
        record.state = 'Error'
    finally:
        if archive:
            archive.close()
    return record


def discover(root, source='WayFinder', *, details=True, ap_version=None, progress=None, progress_offset=0, progress_total=None):
    """Handle discover."""
    root = Path(root)
    records = []
    candidates = []
    for folder in (root / 'worlds', root / 'custom_worlds'):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.name.startswith(('_', '.')) or path.name in {'generic', 'tracker', 'tracker_addons'}:
                continue
            if path.suffix.casefold() == '.apworld' or (path.is_dir() and (path / '__init__.py').is_file()):
                candidates.append(path)
    total = progress_total or max(1, len(candidates))
    for local_index, path in enumerate(candidates, 1):
        absolute_index = progress_offset + local_index
        if progress:
            progress(absolute_index, total, f'Reading manifest + hashing: {path.name}', source)
        records.append(inspect_world(path, source, ap_version if ap_version is not None else core_version(root), details=details))
    for record in records:
        siblings = [r for r in records if r.game == record.game and r.game]
        record.duplicate_count = max(0, len(siblings) - 1)
        eligible = [r for r in siblings if r.compatible]
        if eligible:
            winner = max(eligible, key=lambda r: (version_tuple(r.version), Path(r.path).suffix == '.apworld', r.path.casefold()))
            winner.selected = True
    return records


def select_world(game, root, selected_path=None):
    """Handle select world."""
    records = discover(root, details=False)
    if selected_path:
        matches = [r for r in records if Path(r.path).resolve() == Path(selected_path).resolve()]
    else:
        matches = [r for r in records if r.game == game]
        if not matches:
            matches = [r for r in records if normal_game(game) in {normal_game(r.game), *(normal_game(a) for a in r.aliases)}]
        if len({r.game for r in matches}) > 1:
            raise RuntimeError('Ambiguous APWorld alias: ' + game)
    eligible = [r for r in matches if r.compatible]
    if not eligible:
        raise RuntimeError('No compatible APWorld for ' + game + ': ' + ('; '.join(r.error for r in matches) or 'no matching identity'))
    failures = []
    for winner in sorted(eligible, key=lambda r: (version_tuple(r.version), Path(r.path).suffix == '.apworld', r.path.casefold()), reverse=True):
        selected = inspect_world(winner.path, winner.source, core_version(root))
        if selected.compatible and selected.game == winner.game:
            return selected
        failures.append(selected.error or 'APWorld identity changed during selection')
    raise RuntimeError('Selected APWorld failed inspection: ' + '; '.join(failures))


def inventory(runtime_root, external_root=None, progress=None):
    # Compatibility is always against the Archipelago Core that WayFinder will
    # actually execute.  The external installation is only a source/mirror and
    # may be a packaged install whose root does not expose Utils.py directly.
    # Using its path for version discovery caused valid custom APWorlds to be
    # reported as "Core version unknown" even though WayFinder's staged Core
    # had a perfectly usable version.
    """Handle inventory."""
    runtime_ap_version = core_version(runtime_root)
    def candidate_count(root):
        """Handle candidate count."""
        if not root:
            return 0
        root = Path(root)
        count = 0
        for folder in (root / 'worlds', root / 'custom_worlds'):
            if not folder.is_dir():
                continue
            for path in folder.iterdir():
                if path.name.startswith(('_', '.')) or path.name in {'generic', 'tracker', 'tracker_addons'}:
                    continue
                if path.suffix.casefold() == '.apworld' or (path.is_dir() and (path / '__init__.py').is_file()):
                    count += 1
        return count
    same_root = not external_root or Path(external_root).resolve() == Path(runtime_root).resolve()
    runtime_count = candidate_count(runtime_root)
    external_count = 0 if same_root else candidate_count(external_root)
    total_count = max(1, runtime_count + external_count)
    runtime = discover(runtime_root, ap_version=runtime_ap_version, progress=progress, progress_offset=0, progress_total=total_count)
    external = discover(external_root, 'Archipelago', ap_version=runtime_ap_version, progress=progress, progress_offset=runtime_count, progress_total=total_count) if not same_root else []
    for record in external:
        # Sync preserves filenames; distinguish duplicate versions from their mirrors.
        peers = [r for r in runtime if Path(r.path).name == Path(record.path).name]
        if len(peers) == 1:
            record.mirror_path, record.mirror_hash = peers[0].path, peers[0].sha256
            record.sync_state = 'Matching' if record.sha256 == record.mirror_hash else 'Stale copy'
            peers[0].mirror_path, peers[0].mirror_hash = record.path, record.sha256
            peers[0].sync_state = record.sync_state
            if record.sync_state == 'Matching':
                record.state = 'Synced' if record.compatible else record.state
                peers[0].state = 'Synced' if peers[0].compatible else peers[0].state
        else:
            record.sync_state = 'Not staged'

    combined = runtime + external
    # Discovery happens in two roots, so selecting a winner independently in
    # each root can make two versions of the same game both look selected (for
    # example a newer bundled Muse Dash plus an older custom Muse Dash).  Treat
    # mirrored source/runtime copies as one logical candidate and then select
    # the newest compatible version across the complete environment.
    for item in combined:
        item.selected = False
    for game in sorted({item.game for item in combined if item.game}):
        candidates = [item for item in combined if item.game == game and item.compatible]
        if not candidates:
            continue
        # Prefer the WayFinder runtime record when the same exact hash/version
        # exists in both roots; it is the copy reconstruction will execute.
        unique = {}
        for item in candidates:
            key = (item.version, item.sha256)
            previous = unique.get(key)
            if previous is None or (previous.source != 'WayFinder' and item.source == 'WayFinder'):
                unique[key] = item
        # Explicit custom APWorlds take precedence over a bundled Core world
        # with the same game identity.  Users install custom_worlds intentionally,
        # so a newer bundled implementation must not silently shadow that choice.
        # Version ordering is applied *within* the same installation class.
        def selection_key(item):
            """Handle selection key."""
            path = Path(item.path)
            is_custom = path.suffix.casefold() == '.apworld' or 'custom_worlds' in {part.casefold() for part in path.parts}
            return (is_custom, version_tuple(item.version), item.source == 'WayFinder', path.suffix.casefold() == '.apworld', item.path.casefold())

        winner = max(unique.values(), key=selection_key)
        winner.selected = True

        # A matching external/runtime pair is one logical installation.  Mark
        # its mirror as selected too so the UI does not call a byte-identical
        # synced source copy "shadowed".  Reconstruction still uses the runtime
        # record; this flag is presentation/catalogue state only.
        for item in candidates:
            if item is winner:
                continue
            if item.version == winner.version and item.sha256 and item.sha256 == winner.sha256:
                item.selected = True
    return combined
