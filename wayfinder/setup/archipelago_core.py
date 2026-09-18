#!/usr/bin/env python3
# /**
#  * Module: wayfinder/setup/archipelago_core.py
#  * Purpose: Archipelago source/setup helpers used by the WayFinder application.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

"""Shared Archipelago/setup backend used by the WayFinder application.

This module contains no user-facing launcher window. It owns reusable setup
helpers for Archipelago source staging, APWorld/YAML sync, version checks, and
persistent setup paths.
"""
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import zipfile
import re
import urllib.request
import urllib.error
import webbrowser
from pathlib import Path

from wayfinder import __version__
from wayfinder.connection.memory import clear_server_slot, normalize_server

# Constant(s): `APP_VERSION`; shared configuration value(s) intentionally kept stable within this module.
APP_VERSION = __version__
# Constant(s): `PROJECT_NAME`; shared configuration value(s) intentionally kept stable within this module.
PROJECT_NAME = "WayFinder"
# Constant(s): `PROJECT_FULL_NAME`; shared configuration value(s) intentionally kept stable within this module.
PROJECT_FULL_NAME = "WayFinder — Logic-Aware Tracker"
# Constant(s): `PROJECT_CREATOR`; shared configuration value(s) intentionally kept stable within this module.
PROJECT_CREATOR = "Kuro"
# Constant(s): `SETTINGS_PATH`; shared configuration value(s) intentionally kept stable within this module.
from wayfinder.storage import BOOTSTRAP_SETTINGS_PATH, app_data_root

SETTINGS_PATH = BOOTSTRAP_SETTINGS_PATH


# /**
#  * Function: resource_root
#  * Purpose: Perform the resource root operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def resource_root() -> Path:
    """Handle resource root."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


# /**
#  * Function: app_data_root
#  * Purpose: Perform the app data root operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
# Constant(s): `RESOURCE_ROOT`; shared configuration value(s) intentionally kept stable within this module.
RESOURCE_ROOT = resource_root()
# Constant(s): `APP_DATA_ROOT`; shared configuration value(s) intentionally kept stable within this module.
APP_DATA_ROOT = app_data_root()
# Constant(s): `AP_CORE_ROOT`; shared configuration value(s) intentionally kept stable within this module.
AP_CORE_ROOT = APP_DATA_ROOT / "archipelago_core"
# Constant(s): `AP_CORE_SOURCE`; shared configuration value(s) intentionally kept stable within this module.
AP_CORE_SOURCE = AP_CORE_ROOT / "source"
# Constant(s): `AP_SOURCE_ARCHIVE`; shared configuration value(s) intentionally kept stable within this module.
AP_SOURCE_ARCHIVE = AP_CORE_ROOT / "source.zip"
# Constant(s): `AP_CORE_MANIFEST`; shared configuration value(s) intentionally kept stable within this module.
AP_CORE_MANIFEST = AP_CORE_ROOT / "manifest.json"
# Constant(s): `PLAYERS_DIR`; shared configuration value(s) intentionally kept stable within this module.
PLAYERS_DIR = APP_DATA_ROOT / "players"
# Constant(s): `MAP_PACK_DIR`; shared configuration value(s) intentionally kept stable within this module.
MAP_PACK_DIR = APP_DATA_ROOT / "map_packs"
# Constant(s): `LOGS_DIR`; shared configuration value(s) intentionally kept stable within this module.
LOGS_DIR = APP_DATA_ROOT / "logs"
# Constant(s): `DEPENDENCIES_DIR`; shared configuration value(s) intentionally kept stable within this module.
DEPENDENCIES_DIR = APP_DATA_ROOT / "python_packages"
# Constant(s): `DEPENDENCY_REPORT`; shared configuration value(s) intentionally kept stable within this module.
DEPENDENCY_REPORT = APP_DATA_ROOT / "dependencies.json"
# Constant(s): `SYNC_MANIFEST_NAME`; shared configuration value(s) intentionally kept stable within this module.
SYNC_MANIFEST_NAME = ".wayfinder_synced_apworlds.json"
# Constant(s): `YAML_SYNC_MANIFEST_NAME`; shared configuration value(s) intentionally kept stable within this module.
YAML_SYNC_MANIFEST_NAME = ".wayfinder_synced_yamls.json"
# Constant(s): `ARCHIPELAGO_RELEASE_API`; shared configuration value(s) intentionally kept stable within this module.
ARCHIPELAGO_RELEASE_API = "https://api.github.com/repos/ArchipelagoMW/Archipelago/releases/latest"


# /**
#  * Function: load_settings
#  * Purpose: Load settings data and convert it into the form expected by WayFinder.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def load_settings() -> dict:
    """Return load settings."""
    try:
        # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# /**
#  * Function: save_settings
#  * Purpose: Persist settings data while preserving the caller-facing behavior.
#  * @param data: Data supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def save_settings(data: dict) -> None:
    """Handle save settings."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Variable(s): `tmp` (temporary value); named state retained for the surrounding calculation or subsequent calls.
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, SETTINGS_PATH)


# /**
#  * Function: is_archipelago
#  * Purpose: Determine whether archipelago is true for the supplied state.
#  * @param root: Root supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def is_archipelago(root: Path) -> bool:
    """Return is archipelago."""
    return root.is_dir() and (root / "custom_worlds").is_dir()


# /**
#  * Function: archipelago_candidates
#  * Purpose: Perform the archipelago candidates operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def archipelago_candidates() -> list[Path]:
    # Variable(s): `out` (out); named state retained for the surrounding calculation or subsequent calls.
    """Handle archipelago candidates."""
    out: list[Path] = []
    # Loop variable(s): `env` (env); each iteration represents the next value from the iterable below.
    for env in ("PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA", "APPDATA"):
        # Variable(s): `base` (base); named state retained for the surrounding calculation or subsequent calls.
        base = os.environ.get(env)
        if base:
            out.extend([Path(base) / "Archipelago", Path(base) / "Programs" / "Archipelago"])
    out.extend([Path.home() / "Archipelago", Path.cwd() / "Archipelago"])
    # Variable(s): `unique` (unique); named state retained for the surrounding calculation or subsequent calls.
    unique: list[Path] = []
    # Loop variable(s): `p` (p); each iteration represents the next value from the iterable below.
    for p in out:
        if p not in unique and is_archipelago(p):
            unique.append(p)
    return unique


# /**
#  * Function: find_archipelago
#  * Purpose: Locate archipelago using the available runtime data.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def find_archipelago() -> Path | None:
    # Variable(s): `settings` (settings); named state retained for the surrounding calculation or subsequent calls.
    """Return find archipelago."""
    settings = load_settings()
    # Variable(s): `configured` (configured); named state retained for the surrounding calculation or subsequent calls.
    configured = settings.get("archipelago_root")
    if configured and is_archipelago(Path(configured)):
        return Path(configured)
    # Variable(s): `found` (found); named state retained for the surrounding calculation or subsequent calls.
    found = archipelago_candidates()
    return found[0] if found else None


# /**
#  * Function: _archive_root
#  * Purpose: Perform the archive root operation while keeping the surrounding subsystem state consistent.
#  * @param zf: Zip archive handle supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _archive_root(zf: zipfile.ZipFile) -> str:
    # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
    """Handle archive root."""
    names = [n for n in zf.namelist() if n and not n.endswith("/")]
    # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
    candidates = []
    # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
    for name in names:
        if name.endswith("/CommonClient.py") or name == "CommonClient.py":
            candidates.append(name[:-len("CommonClient.py")].rstrip("/"))
    if not candidates:
        raise RuntimeError("This ZIP does not look like Archipelago source: CommonClient.py was not found.")
    return min(candidates, key=len)


# /**
#  * Function: import_archipelago_core
#  * Purpose: Perform the import archipelago core operation while keeping the surrounding subsystem state consistent.
#  * @param source_zip: Source zip supplied by the caller; see type hints and call sites for domain constraints.
#  * @param progress: Progress supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def import_archipelago_core(source_zip: Path, progress=None) -> dict:
    """Stage the Archipelago core while excluding standalone tracker worlds."""
    AP_CORE_ROOT.mkdir(parents=True, exist_ok=True)
    # Variable(s): `stage` (stage); named state retained for the surrounding calculation or subsequent calls.
    stage = Path(tempfile.mkdtemp(prefix="wayfinder_ap_core_"))
    try:
        # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
        target = stage / "source"
        target.mkdir(parents=True, exist_ok=True)
        # Variable(s): `zf` (ZIP archive handle); named state retained for the surrounding calculation or subsequent calls.
        with zipfile.ZipFile(source_zip, "r") as zf:
            # Variable(s): `prefix` (prefix); named state retained for the surrounding calculation or subsequent calls.
            prefix = _archive_root(zf)
            # Variable(s): `prefix_slash` (prefix slash); named state retained for the surrounding calculation or subsequent calls.
            prefix_slash = prefix + "/" if prefix else ""
            # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
            candidates = []
            # Loop variable(s): `info` (info); each iteration represents the next value from the iterable below.
            for info in zf.infolist():
                # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
                name = info.filename.replace("\\", "/")
                if not name.startswith(prefix_slash):
                    continue
                # Variable(s): `rel` (rel); named state retained for the surrounding calculation or subsequent calls.
                rel = name[len(prefix_slash):].lstrip("/")
                if not rel or rel.endswith("/"):
                    continue
                # Variable(s): `parts` (parts); named state retained for the surrounding calculation or subsequent calls.
                parts = Path(rel).parts
                if len(parts) >= 2 and parts[0] == "worlds" and parts[1] in {"tracker", "tracker_addons"}:
                    continue
                if rel.lower().endswith("tracker.apworld"):
                    continue
                candidates.append((info, rel))
            # Variable(s): `total` (total); named state retained for the surrounding calculation or subsequent calls.
            total = max(1, len(candidates) + 4)
            # Variable(s): `done` (done); named state retained for the surrounding calculation or subsequent calls.
            done = 0
            if progress:
                progress(done, total, "Scanning Archipelago source…")
            # Loop variable(s): `info` (info), `rel` (rel); each iteration represents the next value from the iterable below.
            for info, rel in candidates:
                # Variable(s): `dest` (dest); named state retained for the surrounding calculation or subsequent calls.
                dest = target / rel
                # Variable(s): `resolved` (resolved); named state retained for the surrounding calculation or subsequent calls.
                resolved = dest.resolve()
                if target.resolve() not in resolved.parents:
                    raise RuntimeError(f"Unsafe path in source ZIP: {rel}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                # Variable(s): `src` (source), `dst` (destination); named state retained for the surrounding calculation or subsequent calls.
                with zf.open(info) as src, dest.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                done += 1
                if progress and (done == 1 or done % 50 == 0 or done == len(candidates)):
                    progress(done, total, f"Extracting Archipelago core… {rel}")
        done += 1
        if progress: progress(done, total, "Validating Archipelago core…")
        # Variable(s): `required` (required); named state retained for the surrounding calculation or subsequent calls.
        required = [target / "CommonClient.py", target / "BaseClasses.py", target / "Generate.py", target / "worlds" / "AutoWorld.py"]
        if not all(p.is_file() for p in required):
            raise RuntimeError("The selected archive does not contain a complete Archipelago core source tree.")
        done += 1
        if progress: progress(done, total, "Preparing WayFinder runtime shims…")
        # Belt-and-suspenders: ensure excluded tracker folders cannot survive an update.
        shutil.rmtree(target / "worlds" / "tracker", ignore_errors=True)
        shutil.rmtree(target / "worlds" / "tracker_addons", ignore_errors=True)

        # CommonClient.py and Generate.py call ModuleUpdate.update() at import
        # time.  The stock updater scans every bundled world's requirements and
        # can prompt for unrelated packages.  WayFinder manages only the
        # dependencies its native runtime actually needs, so stage a no-op shim.
        (target / "ModuleUpdate.py").write_text(
            '"""WayFinder shim: AP automatic dependency updates are disabled."""\n'
            'update_ran = True\n'
            'requirements_files = set()\n'
            'def update(*args, **kwargs):\n'
            '    return None\n',
            encoding="utf-8",
        )

        done += 1
        if progress: progress(done, total, "Backing up previous Archipelago core…")
        if AP_CORE_SOURCE.exists():
            # Variable(s): `backup` (backup); named state retained for the surrounding calculation or subsequent calls.
            backup = AP_CORE_ROOT / "previous_source"
            shutil.rmtree(backup, ignore_errors=True)
            AP_CORE_SOURCE.rename(backup)
        shutil.move(str(target), str(AP_CORE_SOURCE))
        shutil.copy2(source_zip, AP_SOURCE_ARCHIVE)
        # Variable(s): `manifest` (manifest); named state retained for the surrounding calculation or subsequent calls.
        manifest = {
            "wayfinder_version": APP_VERSION,
            "source_archive": source_zip.name,
            "tracker_world_staged": False,
            "tracker_addons_staged": False,
        }
        AP_CORE_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if progress: progress(total, total, "Archipelago core ready")
        return manifest
    finally:
        shutil.rmtree(stage, ignore_errors=True)


# /**
#  * Function: _sync_manifest_path
#  * Purpose: Perform the sync manifest path operation while keeping the surrounding subsystem state consistent.
#  * @param destination: Destination supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _sync_manifest_path(destination: Path) -> Path:
    """Handle sync manifest path."""
    return destination / SYNC_MANIFEST_NAME


# /**
#  * Function: _load_synced_names
#  * Purpose: Load synced names data and convert it into the form expected by WayFinder.
#  * @param destination: Destination supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _load_synced_names(destination: Path) -> set[str]:
    """Return APWorld filenames previously mirrored from an external install.

    APWorlds that came from the imported Archipelago source archive are *not*
    listed here.  Keeping those two origins separate lets Sync APWorlds Now
    remove stale external mirrors without deleting APWorlds that were already
    bundled in the imported source ZIP.
    """
    try:
        # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
        data = json.loads(_sync_manifest_path(destination).read_text(encoding="utf-8"))
    except Exception:
        return set()
    # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
    names = data.get("external_apworlds", []) if isinstance(data, dict) else []
    return {str(name) for name in names if isinstance(name, str) and name.lower().endswith(".apworld")}


# /**
#  * Function: _save_synced_names
#  * Purpose: Persist synced names data while preserving the caller-facing behavior.
#  * @param destination: Destination supplied by the caller; see type hints and call sites for domain constraints.
#  * @param names: Names supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _save_synced_names(destination: Path, names: set[str]) -> None:
    # Variable(s): `path` (path); named state retained for the surrounding calculation or subsequent calls.
    """Handle save synced names."""
    path = _sync_manifest_path(destination)
    # Variable(s): `tmp` (temporary value); named state retained for the surrounding calculation or subsequent calls.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"external_apworlds": sorted(names, key=str.casefold)}, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# /**
#  * Function: _allowed_game_apworld
#  * Purpose: Perform the allowed game apworld operation while keeping the surrounding subsystem state consistent.
#  * @param path: Path supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _allowed_game_apworld(path: Path) -> bool:
    # Variable(s): `low` (low); named state retained for the surrounding calculation or subsequent calls.
    """Handle allowed game apworld."""
    low = path.name.casefold()
    return not ("tracker" in low or low in {"wayfinder.apworld", "trackervisual.apworld"})


# /**
#  * Function: sync_custom_worlds
#  * Purpose: Perform the sync custom worlds operation while keeping the surrounding subsystem state consistent.
#  * @param ap_root: Ap root supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def sync_custom_worlds(ap_root: Path | None) -> int:
    """Mirror external custom APWorlds without destroying imported ones.

    The imported Archipelago source ZIP may itself contain ``custom_worlds``.
    Older WayFinder builds extracted those files and then immediately deleted
    them during the automatic sync whenever no separately detected Archipelago
    install was available.  We now track only files copied from the external
    install and only replace/remove that tracked set.

    The returned count is the number of usable APWorlds now present in the
    staged runtime, regardless of whether they came from the source ZIP or the
    external Archipelago custom_worlds folder.
    """
    # Variable(s): `destination` (destination); named state retained for the surrounding calculation or subsequent calls.
    destination = AP_CORE_SOURCE / "custom_worlds"
    destination.mkdir(parents=True, exist_ok=True)

    # Variable(s): `previous_external` (previous external); named state retained for the surrounding calculation or subsequent calls.
    previous_external = _load_synced_names(destination)
    # Variable(s): `current_external` (current external); named state retained for the surrounding calculation or subsequent calls.
    current_external: set[str] = set()

    if ap_root and is_archipelago(ap_root):
        # Variable(s): `source_root` (source root); named state retained for the surrounding calculation or subsequent calls.
        source_root = ap_root / "custom_worlds"
        # Variable(s): `source_names` (source names); named state retained for the surrounding calculation or subsequent calls.
        source_names = {source.name for source in source_root.glob("*.apworld") if _allowed_game_apworld(source)}

        # Loop variable(s): `source` (source); each iteration represents the next value from the iterable below.
        for source in source_root.glob("*.apworld"):
            if not _allowed_game_apworld(source):
                continue
            from ..runtime.apworld_catalog import atomic_copy
            atomic_copy(source, destination / source.name)
            current_external.add(source.name)
            # If a later copy fails, the successfully replaced files still have
            # durable ownership and can be cleaned up on the next sync.
            _save_synced_names(destination, previous_external | current_external)
        # Remove only stale files that WayFinder previously mirrored from this
        # external source.  Never blanket-delete destination/*.apworld because
        # some of those belong to the imported source archive itself.
        # Loop variable(s): `stale_name` (stale name); each iteration represents the next value from the iterable below.
        for stale_name in previous_external - source_names:
            try:
                (destination / stale_name).unlink()
            except FileNotFoundError:
                _ignored("intentional best-effort fallback")
            except OSError:
                _ignored("intentional best-effort fallback")

    else:
        # No external installation is configured/detected.  Preserve any
        # APWorlds that arrived in the imported source ZIP.  Forget the old
        # external mirror ownership so a later source import cannot have its
        # files removed just because they reuse an old filename.
        # Variable(s): `current_external` (current external); named state retained for the surrounding calculation or subsequent calls.
        current_external = set()

    _save_synced_names(destination, current_external)
    return sum(1 for path in destination.glob("*.apworld") if _allowed_game_apworld(path))



# /**
#  * Function: _players_source
#  * Purpose: Perform the players source operation while keeping the surrounding subsystem state consistent.
#  * @param ap_root: Ap root supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _players_source(ap_root: Path | None) -> Path | None:
    """Handle players source."""
    if not ap_root:
        return None
    # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
    for name in ("Players", "players"):
        # Variable(s): `candidate` (candidate); named state retained for the surrounding calculation or subsequent calls.
        candidate = ap_root / name
        if candidate.is_dir():
            return candidate
    return None


# /**
#  * Function: _yaml_sync_manifest_path
#  * Purpose: Perform the yaml sync manifest path operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _yaml_sync_manifest_path() -> Path:
    """Handle yaml sync manifest path."""
    return PLAYERS_DIR / YAML_SYNC_MANIFEST_NAME


# /**
#  * Function: _load_synced_yaml_names
#  * Purpose: Load synced yaml names data and convert it into the form expected by WayFinder.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _load_synced_yaml_names() -> set[str]:
    """Handle load synced yaml names."""
    try:
        # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
        data = json.loads(_yaml_sync_manifest_path().read_text(encoding="utf-8"))
    except Exception:
        return set()
    # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
    names = data.get("external_yamls", []) if isinstance(data, dict) else []
    return {str(x) for x in names if isinstance(x, str) and str(x).lower().endswith((".yaml", ".yml"))}


# /**
#  * Function: _save_synced_yaml_names
#  * Purpose: Persist synced yaml names data while preserving the caller-facing behavior.
#  * @param names: Names supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _save_synced_yaml_names(names: set[str]) -> None:
    """Handle save synced yaml names."""
    PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
    # Variable(s): `path` (path); named state retained for the surrounding calculation or subsequent calls.
    path = _yaml_sync_manifest_path()
    # Variable(s): `tmp` (temporary value); named state retained for the surrounding calculation or subsequent calls.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"external_yamls": sorted(names, key=str.casefold)}, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# /**
#  * Function: sync_player_yamls
#  * Purpose: Perform the sync player yamls operation while keeping the surrounding subsystem state consistent.
#  * @param ap_root: Ap root supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def sync_player_yamls(ap_root: Path | None) -> int:
    """Mirror player YAMLs from the selected Archipelago Players folder.

    Only files previously mirrored by WayFinder are removed. Manually supplied
    YAMLs in WayFinder/players are preserved. Both .yaml and .yml are accepted.
    """
    PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
    # Variable(s): `previous` (previous); named state retained for the surrounding calculation or subsequent calls.
    previous = _load_synced_yaml_names()
    # Variable(s): `current` (current); named state retained for the surrounding calculation or subsequent calls.
    current: set[str] = set()
    # Variable(s): `source_root` (source root); named state retained for the surrounding calculation or subsequent calls.
    source_root = _players_source(ap_root)
    if source_root:
        # Only sync actual player YAMLs. Archipelago's Players/Templates tree
        # contains generation templates, not generated/player configuration.
        # Never copy from, descend into, or consider any Templates directory.
        # Variable(s): `sources` (sources); named state retained for the surrounding calculation or subsequent calls.
        sources = [
            p for p in source_root.rglob("*")
            if p.is_file()
            and p.suffix.casefold() in {".yaml", ".yml"}
            and not any(part.casefold() in {"template", "templates"} for part in p.relative_to(source_root).parts[:-1])
        ]
        # Variable(s): `source_names` (source names); named state retained for the surrounding calculation or subsequent calls.
        source_names = {p.name for p in sources}
        # Loop variable(s): `stale` (stale); each iteration represents the next value from the iterable below.
        for stale in previous - source_names:
            try:
                (PLAYERS_DIR / stale).unlink()
            except OSError:
                _ignored("intentional best-effort fallback")
        # Loop variable(s): `source` (source); each iteration represents the next value from the iterable below.
        for source in sources:
            # Player filenames are normally unique. If nested folders contain a
            # duplicate, prefer the first copied file and leave a manual file alone.
            # Variable(s): `dest` (dest); named state retained for the surrounding calculation or subsequent calls.
            dest = PLAYERS_DIR / source.name
            shutil.copy2(source, dest)
            current.add(source.name)
    _save_synced_yaml_names(current)
    return sum(1 for p in PLAYERS_DIR.iterdir() if p.is_file() and p.suffix.casefold() in {".yaml", ".yml"})


# /**
#  * Function: _yaml_declared_name
#  * Purpose: Perform the yaml declared name operation while keeping the surrounding subsystem state consistent.
#  * @param path: Path supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _yaml_declared_name(path: Path) -> str:
    """Handle yaml declared name."""
    try:
        # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    # Archipelago player files use a top-level `name:` field. This deliberately
    # avoids importing YAML in the setup backend just to identify the slot file.
    # Variable(s): `match` (match); named state retained for the surrounding calculation or subsequent calls.
    match = re.search(r"(?mi)^name\s*:\s*([^#\r\n]+)", text)
    if not match:
        return ""
    return match.group(1).strip().strip('"\'').strip()


# /**
#  * Function: find_matching_player_yaml
#  * Purpose: Locate matching player yaml using the available runtime data.
#  * @param folder: Folder supplied by the caller; see type hints and call sites for domain constraints.
#  * @param slot_name: Slot name supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def find_matching_player_yaml(folder: Path, slot_name: str) -> Path | None:
    # Variable(s): `slot` (slot); named state retained for the surrounding calculation or subsequent calls.
    """Return find matching player yaml."""
    slot = str(slot_name or "").strip()
    if not slot or not folder.is_dir():
        return None
    # Variable(s): `files` (files); named state retained for the surrounding calculation or subsequent calls.
    files = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.casefold() in {".yaml", ".yml"}), key=lambda p: p.name.casefold())
    # Loop variable(s): `path` (path); each iteration represents the next value from the iterable below.
    for path in files:
        if path.stem.casefold() == slot.casefold():
            return path
    # Loop variable(s): `path` (path); each iteration represents the next value from the iterable below.
    for path in files:
        if _yaml_declared_name(path).casefold() == slot.casefold():
            return path
    return None


# /**
#  * Function: imported_archipelago_version
#  * Purpose: Perform the imported archipelago version operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def imported_archipelago_version() -> str:
    # Variable(s): `utils` (utils); named state retained for the surrounding calculation or subsequent calls.
    """Handle imported archipelago version."""
    utils = AP_CORE_SOURCE / "Utils.py"
    try:
        # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
        text = utils.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    # Variable(s): `match` (match); named state retained for the surrounding calculation or subsequent calls.
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)', text, re.MULTILINE)
    return match.group(1).strip() if match else ""


# /**
#  * Function: _version_key
#  * Purpose: Perform the version key operation while keeping the surrounding subsystem state consistent.
#  * @param value: Value supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _version_key(value: str) -> tuple[int, ...]:
    # Variable(s): `nums` (nums); named state retained for the surrounding calculation or subsequent calls.
    """Handle version key."""
    nums = re.findall(r"\d+", str(value or ""))
    return tuple(int(n) for n in nums[:4])


# /**
#  * Function: github_latest_archipelago_release
#  * Purpose: Perform the github latest archipelago release operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def github_latest_archipelago_release() -> dict:
    # Variable(s): `req` (requirement); named state retained for the surrounding calculation or subsequent calls.
    """Handle github latest archipelago release."""
    req = urllib.request.Request(ARCHIPELAGO_RELEASE_API, headers={"User-Agent": f"WayFinder/{APP_VERSION}", "Accept": "application/vnd.github+json"})
    # Variable(s): `response` (response); named state retained for the surrounding calculation or subsequent calls.
    with urllib.request.urlopen(req, timeout=12) as response:
        # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict) or not data.get("tag_name"):
        raise RuntimeError("GitHub returned an unexpected release response.")
    return data

# /**
#  * Function: core_ready
#  * Purpose: Perform the core ready operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def core_ready() -> bool:
    """Handle core ready."""
    return (AP_CORE_SOURCE / "CommonClient.py").is_file() and (AP_CORE_SOURCE / "worlds" / "AutoWorld.py").is_file() \
        and not (AP_CORE_SOURCE / "worlds" / "tracker").exists()


# /**
#  * Function: allocate_port
#  * Purpose: Perform the allocate port operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */

# /**
#  * Function: child_command
#  * Purpose: Perform the child command operation while keeping the surrounding subsystem state consistent.
#  * @param mode: Mode supplied by the caller; see type hints and call sites for domain constraints.
#  * @param args: Args supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */

DEFAULT_AP_PORT = "38281"


# /**
#  * Function: split_server_port
#  * Purpose: Perform the split server port operation while keeping the surrounding subsystem state consistent.
#  * @param value: Value supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def split_server_port(value: str) -> tuple[str, str]:
    """Split a saved server address into host and optional port for WayFinder connection fields."""
    # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
    value = str(value or "").strip()
    # Loop variable(s): `prefix` (prefix); each iteration represents the next value from the iterable below.
    for prefix in ("ws://", "wss://"):
        if value.lower().startswith(prefix):
            # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
            value = value[len(prefix):]
            break
    # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
    value = value.rstrip("/")
    if not value:
        return "", ""
    if value.startswith("[") and "]:" in value:
        # Variable(s): `host` (host), `port` (port); named state retained for the surrounding calculation or subsequent calls.
        host, port = value.rsplit(":", 1)
        return host, port if port.isdigit() else ""
    # Normal hostnames/IPv4 may carry a saved port. Older WayFinder builds could
    # accidentally persist it twice (host:38281:38281); collapse repeated
    # trailing numeric ports while leaving IPv6 bracket syntax alone.
    # Variable(s): `parts` (parts); named state retained for the surrounding calculation or subsequent calls.
    parts = value.split(":")
    if len(parts) >= 2 and parts[-1].isdigit():
        # Variable(s): `port` (port); named state retained for the surrounding calculation or subsequent calls.
        port = parts[-1]
        # Variable(s): `host_parts` (host parts); named state retained for the surrounding calculation or subsequent calls.
        host_parts = parts[:-1]
        while len(host_parts) >= 2 and host_parts[-1].isdigit() and host_parts[-1] == port:
            host_parts.pop()
        # Variable(s): `host` (host); named state retained for the surrounding calculation or subsequent calls.
        host = ":".join(host_parts)
        if host and ":" not in host:
            return host, port
    return value, ""


# /**
#  * Function: compose_server
#  * Purpose: Perform the compose server operation while keeping the surrounding subsystem state consistent.
#  * @param host: Host supplied by the caller; see type hints and call sites for domain constraints.
#  * @param port: Port supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def compose_server(host: str, port: str = "") -> str:
    """Build the AP server passed to the runtime; blank port means AP default 38281."""
    # Variable(s): `host` (host); named state retained for the surrounding calculation or subsequent calls.
    host = str(host or "").strip().rstrip("/")
    # Variable(s): `port` (port); named state retained for the surrounding calculation or subsequent calls.
    port = str(port or "").strip() or DEFAULT_AP_PORT
    if not host:
        return ""
    # Respect a fully-qualified server supplied in the host box while still
    # replacing/adding the dedicated connection port field.
    # Variable(s): `scheme` (scheme); named state retained for the surrounding calculation or subsequent calls.
    scheme = ""
    # Variable(s): `lower` (lower); named state retained for the surrounding calculation or subsequent calls.
    lower = host.lower()
    if lower.startswith("ws://"):
        # Variable(s): `scheme` (scheme), `host` (host); named state retained for the surrounding calculation or subsequent calls.
        scheme, host = "ws://", host[5:]
    elif lower.startswith("wss://"):
        # Variable(s): `scheme` (scheme), `host` (host); named state retained for the surrounding calculation or subsequent calls.
        scheme, host = "wss://", host[6:]
    # Variable(s): `saved_host` (saved host), `saved_port` (saved port); named state retained for the surrounding calculation or subsequent calls.
    saved_host, saved_port = split_server_port(host)
    if saved_port:
        # Variable(s): `host` (host); named state retained for the surrounding calculation or subsequent calls.
        host = saved_host
    return f"{scheme}{host}:{port}"
