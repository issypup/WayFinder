"""Provide world loader support."""
# /**
#  * Module: wayfinder.runtime/world_loader.py
#  * Purpose: Runtime module for world loader; bridges loaded Archipelago worlds and live server state into tracker snapshots.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

"""Selective Archipelago world loading for WayFinder.

Archipelago's stock ``worlds`` package imports every bundled world and every
custom APWorld as a side effect of importing ``worlds``.  A tracker only needs
the connected game's World class.  This module installs a minimal package shell
so core modules such as CommonClient can import ``worlds.AutoWorld`` without
triggering the global scan, then locates/imports exactly one game on demand.
"""

import ast
import importlib
import importlib.abc
import importlib.machinery
import json
import logging
import os
import sys
import types
import zipfile
import zipimport
from pathlib import Path
from typing import Any, Iterable

# Variable(s): `log` (log); named state retained for the surrounding calculation or subsequent calls.
log = logging.getLogger("WayFinder.Native.WorldLoader")

# Constant(s): `_FINDER`; shared configuration value(s) intentionally kept stable within this module.
_FINDER = None
# Constant(s): `_APWORLD_SPECS`; shared configuration value(s) intentionally kept stable within this module.
_APWORLD_SPECS: dict[str, importlib.machinery.ModuleSpec | None] = {}


# /**
#  * Function: _literal_game_from_source
#  * Purpose: Perform the literal game from source operation while keeping the surrounding subsystem state consistent.
#  * @param text: Text supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _literal_game_from_source(text: str) -> str | None:
    """Best-effort static extraction of ``game = 'Name'`` without importing."""
    try:
        # Variable(s): `tree` (tree); named state retained for the surrounding calculation or subsequent calls.
        tree = ast.parse(text)
    except Exception:
        return None
    # Loop variable(s): `node` (node); each iteration represents the next value from the iterable below.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        # Variable(s): `targets` (targets); named state retained for the surrounding calculation or subsequent calls.
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(t, ast.Name) and t.id == "game" for t in targets):
            continue
        # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return None


# /**
#  * Function: _game_from_directory
#  * Purpose: Perform the game from directory operation while keeping the surrounding subsystem state consistent.
#  * @param path: Path supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _game_from_directory(path: Path) -> str | None:
    # Modern AP world manifests are preferred.
    # Loop variable(s): `manifest` (manifest); each iteration represents the next value from the iterable below.
    """Handle game from directory."""
    for manifest in path.rglob("archipelago.json"):
        try:
            # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
            data = json.loads(manifest.read_text(encoding="utf-8"))
            # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
            game = data.get("game")
            if isinstance(game, str) and game.strip():
                return game.strip()
        except Exception:
            _ignored("intentional best-effort fallback")
    # Older worlds: inspect Python source statically.  __init__.py usually owns
    # the World subclass and therefore the game literal.
    # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
    candidates = [path / "__init__.py"] + list(path.glob("*.py"))
    # Variable(s): `seen` (seen); named state retained for the surrounding calculation or subsequent calls.
    seen: set[Path] = set()
    # Loop variable(s): `source` (source); each iteration represents the next value from the iterable below.
    for source in candidates:
        if source in seen or not source.is_file():
            continue
        seen.add(source)
        try:
            # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
            game = _literal_game_from_source(source.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
            game = None
        if game:
            return game
    return None


# /**
#  * Function: _game_and_module_from_apworld
#  * Purpose: Perform the game and module from apworld operation while keeping the surrounding subsystem state consistent.
#  * @param path: Path supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _game_and_module_from_apworld(path: Path) -> tuple[str | None, str | None]:
    """Handle game and module from apworld."""
    try:
        # Variable(s): `zf` (ZIP archive handle); named state retained for the surrounding calculation or subsequent calls.
        with zipfile.ZipFile(path, "r") as zf:
            # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
            names = [n.replace("\\", "/") for n in zf.namelist()]
            # Variable(s): `manifests` (manifests); named state retained for the surrounding calculation or subsequent calls.
            manifests = [n for n in names if n.endswith("archipelago.json")]
            # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
            for name in manifests:
                try:
                    # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
                    data = json.loads(zf.read(name).decode("utf-8", errors="replace"))
                    # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
                    game = data.get("game")
                    if isinstance(game, str) and game.strip():
                        # Variable(s): `module` (module); named state retained for the surrounding calculation or subsequent calls.
                        module = name.split("/", 1)[0] if "/" in name else path.stem
                        return game.strip(), module
                except Exception:
                    _ignored("intentional best-effort fallback")
            # Legacy APWorlds may have no usable manifest.  Determine the
            # package root and statically inspect source for World.game.
            # Variable(s): `roots` (roots); named state retained for the surrounding calculation or subsequent calls.
            roots = sorted({n.split("/", 1)[0] for n in names if "/" in n and n.endswith(".py")})
            # Loop variable(s): `root` (root); each iteration represents the next value from the iterable below.
            for root in roots:
                # Variable(s): `init_name` (init name); named state retained for the surrounding calculation or subsequent calls.
                init_name = f"{root}/__init__.py"
                # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
                candidates = [init_name] if init_name in names else []
                candidates += [n for n in names if n.startswith(root + "/") and n.endswith(".py")]
                # Loop variable(s): `source_name` (source name); each iteration represents the next value from the iterable below.
                for source_name in candidates:
                    try:
                        # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
                        game = _literal_game_from_source(zf.read(source_name).decode("utf-8", errors="replace"))
                    except Exception:
                        # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
                        game = None
                    if game:
                        return game, root
    except (OSError, zipfile.BadZipFile):
        _ignored("intentional best-effort fallback")
    return None, None


# /**
#  * Class: _APWorldFinder
#  * Purpose: Encapsulate the APWorldFinder responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
class _APWorldFinder(importlib.abc.MetaPathFinder):
    # /**
    #  * Function: find_spec
    #  * Purpose: Locate spec using the available runtime data.
    #  * @param fullname: Fullname supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param path: Path supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param target: Target supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    """Provide a p world finder behavior."""
    def find_spec(self, fullname: str, path=None, target=None):
        """Return find spec."""
        return _APWORLD_SPECS.get(fullname)


# /**
#  * Function: install_minimal_worlds_package
#  * Purpose: Perform the install minimal worlds package operation while keeping the surrounding subsystem state consistent.
#  * @param ap_root: Ap root supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def install_minimal_worlds_package(ap_root: str | os.PathLike[str]) -> Any:
    """Install a side-effect-free ``worlds`` package and load AutoWorld only."""
    global _FINDER
    # Variable(s): `root` (root); named state retained for the surrounding calculation or subsequent calls.
    root = Path(ap_root).resolve()
    # Variable(s): `worlds_dir` (worlds dir); named state retained for the surrounding calculation or subsequent calls.
    worlds_dir = root / "worlds"
    if not (worlds_dir / "AutoWorld.py").is_file():
        raise RuntimeError(f"Archipelago worlds/AutoWorld.py is missing: {worlds_dir}")

    # Remove a stock worlds package if something imported it before us.  This
    # function is called before CommonClient, so normally there is nothing to
    # remove; the cleanup makes the invariant explicit.
    # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
    for name in list(sys.modules):
        if name == "worlds" or name.startswith("worlds."):
            del sys.modules[name]

    # Variable(s): `package` (package); named state retained for the surrounding calculation or subsequent calls.
    package = types.ModuleType("worlds")
    package.__file__ = str(worlds_dir / "__init__.py")
    package.__package__ = "worlds"
    package.__path__ = [str(worlds_dir)]
    # Variable(s): `spec` (spec); named state retained for the surrounding calculation or subsequent calls.
    spec = importlib.machinery.ModuleSpec("worlds", loader=None, is_package=True)
    spec.submodule_search_locations = [str(worlds_dir)]
    package.__spec__ = spec
    package.failed_world_loads = {}
    package.world_sources = []
    package.local_folder = str(worlds_dir)
    package.user_folder = str(root / "custom_worlds")
    # CommonClient only needs a mapping with a games table at import/startup.
    # The server's RoomInfo/DataPackage flow supplies the connected game's real
    # package later.
    package.network_data_package = {"games": {}}
    sys.modules["worlds"] = package

    # Variable(s): `auto` (auto); named state retained for the surrounding calculation or subsequent calls.
    auto = importlib.import_module("worlds.AutoWorld")
    package.AutoWorldRegister = auto.AutoWorldRegister

    if _FINDER is None:
        # Constant(s): `_FINDER`; shared configuration value(s) intentionally kept stable within this module.
        _FINDER = _APWorldFinder()
        sys.meta_path.insert(0, _FINDER)
    return package


# /**
#  * Function: _iter_candidates
#  * Purpose: Perform the iter candidates operation while keeping the surrounding subsystem state consistent.
#  * @param ap_root: Ap root supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _iter_candidates(ap_root: Path) -> Iterable[tuple[str, Path, str]]:
    """Yield (kind, path, module_name), without importing anything."""
    # Variable(s): `worlds_dir` (worlds dir); named state retained for the surrounding calculation or subsequent calls.
    worlds_dir = ap_root / "worlds"
    if worlds_dir.is_dir():
        # Loop variable(s): `entry` (entry); each iteration represents the next value from the iterable below.
        for entry in worlds_dir.iterdir():
            if entry.name.startswith(("_", ".")) or entry.name in {"generic"}:
                continue
            if entry.is_dir() and (entry / "__init__.py").is_file():
                yield "dir", entry, entry.name
    # Variable(s): `custom` (custom); named state retained for the surrounding calculation or subsequent calls.
    custom = ap_root / "custom_worlds"
    if custom.is_dir():
        # Loop variable(s): `entry` (entry); each iteration represents the next value from the iterable below.
        for entry in custom.glob("*.apworld"):
            yield "apworld", entry, entry.stem


# /**
#  * Function: ensure_game_loaded
#  * Purpose: Perform the ensure game loaded operation while keeping the surrounding subsystem state consistent.
#  * @param game: Game supplied by the caller; see type hints and call sites for domain constraints.
#  * @param ap_root: Ap root supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _apply_world_manifest_contract(world_cls: type, record: Any) -> type:
    """Stamp Archipelago manifest metadata onto a selectively loaded World class.

    Archipelago's normal world loader assigns ``World.world_version`` from
    ``archipelago.json``.  WayFinder bypasses the global worlds-package scan,
    so it must reproduce that loader contract before Generate validates a
    player's ``requires.game`` constraints.
    """
    manifest = dict(getattr(record, "manifest", {}) or {})
    version_text = str(manifest.get("world_version", "") or "").strip()
    if version_text:
        try:
            from Utils import tuplize_version
        except ImportError:
            # Discovery/unit-test environments may not have an AP core on
            # sys.path yet. Runtime preparation does, and therefore receives
            # Archipelago's real Version object.
            world_cls.world_version = tuple(int(part) for part in version_text.split("."))
        else:
            world_cls.world_version = tuplize_version(version_text)

    # Match Archipelago's world-facing manifest: archive/container schema
    # fields are loader metadata, not part of the World manifest contract.
    world_manifest = dict(manifest)
    world_manifest.pop("version", None)
    world_manifest.pop("compatible_version", None)
    if world_manifest:
        world_cls.manifest = world_manifest

    world_cls._wayfinder_manifest_version = version_text
    return world_cls


def ensure_game_loaded(game: str, ap_root: str | os.PathLike[str], *, selected_path=None) -> type:
    """Load exactly the World implementation that declares ``game``."""
    from worlds.AutoWorld import AutoWorldRegister

    from .apworld_catalog import select_world
    record = select_world(game, ap_root, selected_path)
    game = record.game
    if game in AutoWorldRegister.world_types:
        loaded = AutoWorldRegister.world_types[game]
        previous = getattr(loaded, '_wayfinder_source_hash', None)
        if previous and previous != record.sha256:
            raise RuntimeError('APWorld changed on disk. Restart the native runtime to load the new version.')
        return _apply_world_manifest_contract(loaded, record)
    path = Path(record.path)
    kind = 'dir' if path.is_dir() else 'apworld'
    module_name = record.module
    fullname = f"worlds.{module_name}"

    if kind == "dir":
        importlib.import_module(fullname)
    else:
        # Variable(s): `importer` (importer); named state retained for the surrounding calculation or subsequent calls.
        importer = zipimport.zipimporter(str(path))
        # Variable(s): `spec` (spec); named state retained for the surrounding calculation or subsequent calls.
        spec = importer.find_spec(fullname)
        if spec is None:
            # Some legacy APWorlds use the archive filename as their package.
            # Variable(s): `fallback` (fallback); named state retained for the surrounding calculation or subsequent calls.
            fallback = f"worlds.{path.stem}"
            # Variable(s): `spec` (spec); named state retained for the surrounding calculation or subsequent calls.
            spec = importer.find_spec(fallback)
            if spec is not None:
                # Variable(s): `fullname` (fullname); named state retained for the surrounding calculation or subsequent calls.
                fullname = fallback
        if spec is None:
            raise RuntimeError(f"Could not create an import spec for APWorld {path.name}")
        _APWORLD_SPECS[fullname] = spec
        try:
            importlib.import_module(fullname)
        finally:
            _APWORLD_SPECS.pop(fullname, None)

    if game not in AutoWorldRegister.world_types:
        raise RuntimeError(
            f"Loaded {path.name}, but it did not register the expected game {game!r}."
        )
    loaded = AutoWorldRegister.world_types[game]
    loaded._wayfinder_source_hash = record.sha256
    loaded._wayfinder_source_path = record.path
    _apply_world_manifest_contract(loaded, record)
    return loaded
