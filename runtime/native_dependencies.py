"""Prepare and reuse native dependencies for dynamically loaded APWorlds.

Managed packages remain in WayFinder's normal python_packages tree and are
registered in place. Native binaries embedded in an APWorld are extracted once
to a content-addressed persistent cache and reused while that APWorld is
unchanged. PATH changes are process-local only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import zipfile
from pathlib import Path

from ..storage import app_data_root

log = logging.getLogger("WayFinder.Native.NativeDependencies")

_IS_WINDOWS = os.name == "nt"
_DLL_HANDLES: list[object] = []
_REGISTERED: set[str] = set()
_DISCOVERY_CACHE: dict[tuple[str, int, int], tuple[Path, ...]] = {}
_NATIVE_SUFFIXES = {".pyd", ".dll"}
_CACHE_SCHEMA = 1


def _register_directory(path: Path) -> bool:
    """Register one directory for this process's Windows DLL resolution."""
    if not _IS_WINDOWS or not path.is_dir():
        return False
    text = str(path.resolve())
    key = os.path.normcase(text)
    if key in _REGISTERED:
        return False
    try:
        handle = os.add_dll_directory(text)
    except (AttributeError, FileNotFoundError, OSError) as exc:
        log.debug("Native DLL directory not registered: %s (%s)", text, exc)
        return False
    _DLL_HANDLES.append(handle)
    _REGISTERED.add(key)

    # Some native libraries perform secondary LoadLibrary-style lookups against
    # PATH. This mutates only WayFinder's process environment, never Windows'
    # persistent user/system PATH.
    current = os.environ.get("PATH", "")
    existing = {os.path.normcase(p) for p in current.split(os.pathsep) if p}
    if key not in existing:
        os.environ["PATH"] = text + (os.pathsep + current if current else "")
    return True


def _tree_identity(root: Path) -> tuple[str, int, int]:
    """Return a cheap per-process identity for native-directory discovery."""
    try:
        stat = root.stat()
        return str(root.resolve()), int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return str(root.resolve()), 0, 0


def _native_directories(root: Path) -> set[Path]:
    """Find native directories, reusing discovery results while a root is unchanged."""
    if not root.exists():
        return set()
    if root.is_file():
        return {root.parent} if root.suffix.casefold() in _NATIVE_SUFFIXES else set()

    identity = _tree_identity(root)
    cached = _DISCOVERY_CACHE.get(identity)
    if cached is not None:
        return set(cached)

    result: set[Path] = set()
    try:
        for item in root.rglob("*"):
            if item.is_file() and item.suffix.casefold() in _NATIVE_SUFFIXES:
                result.add(item.parent)
    except OSError:
        pass
    _DISCOVERY_CACHE[identity] = tuple(sorted(result, key=lambda p: str(p).casefold()))
    return result


def _sha256_file(path: Path) -> str:
    """Hash an APWorld so cache reuse follows content, not filename or timestamp."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_root() -> Path:
    """Return persistent native cache under WayFinder's configured data root."""
    return app_data_root() / "native_cache"


def _manifest_path(cache_dir: Path) -> Path:
    return cache_dir / "native-index.json"


def _read_manifest(cache_dir: Path) -> dict:
    try:
        data = json.loads(_manifest_path(cache_dir).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _cache_is_valid(cache_dir: Path, digest: str, native_names: list[str]) -> bool:
    """Validate cached native payload before reusing it."""
    manifest = _read_manifest(cache_dir)
    if manifest.get("schema") != _CACHE_SCHEMA or manifest.get("sha256") != digest:
        return False
    expected = sorted(native_names)
    if sorted(manifest.get("files") or []) != expected:
        return False
    return all(cache_dir.joinpath(*Path(name).parts).is_file() for name in expected)


def _extract_apworld_native_payload(apworld: Path) -> tuple[Path | None, bool]:
    """Return persistent APWorld native cache and whether it was reused."""
    if not apworld.is_file() or apworld.suffix.casefold() != ".apworld":
        return None, False
    try:
        digest = _sha256_file(apworld)
        with zipfile.ZipFile(apworld) as zf:
            native_names = sorted({
                info.filename.replace("\\", "/").lstrip("/")
                for info in zf.infolist()
                if not info.is_dir()
                and Path(info.filename.replace("\\", "/")).suffix.casefold() in _NATIVE_SUFFIXES
                and ".." not in Path(info.filename.replace("\\", "/")).parts
            })
            if not native_names:
                return None, False

            cache_dir = _cache_root() / digest
            if _cache_is_valid(cache_dir, digest, native_names):
                return cache_dir, True

            cache_dir.parent.mkdir(parents=True, exist_ok=True)
            staging = cache_dir.with_name(cache_dir.name + ".tmp")
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)

            for name in native_names:
                target = staging.joinpath(*Path(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as source, target.open("wb") as dest:
                    shutil.copyfileobj(source, dest)

            _manifest_path(staging).write_text(json.dumps({
                "schema": _CACHE_SCHEMA,
                "sha256": digest,
                "source_name": apworld.name,
                "files": native_names,
            }, indent=2, sort_keys=True), encoding="utf-8")

            shutil.rmtree(cache_dir, ignore_errors=True)
            staging.replace(cache_dir)
            return cache_dir, False
    except (OSError, zipfile.BadZipFile) as exc:
        log.warning("Could not prepare native payload from APWorld %s: %s", apworld.name, exc)
        return None, False


def prepare_native_dependencies(*, dependency_root=None, apworld_path=None, extra_roots=()) -> dict:
    """Reuse/register native-library locations before importing an APWorld."""
    if not _IS_WINDOWS:
        return {"platform": os.name, "registered": [], "apworld_native_root": "", "apworld_cache_reused": False}

    roots: list[Path] = []
    if dependency_root:
        # Managed dependencies are already persistent and reusable. Never copy
        # them into native_cache; register their existing directories directly.
        roots.append(Path(dependency_root).resolve())
    for root in extra_roots or ():
        if root:
            roots.append(Path(root).resolve())

    apworld_native_root = None
    apworld_cache_reused = False
    if apworld_path:
        apworld = Path(apworld_path).resolve()
        if apworld.is_dir():
            roots.append(apworld)
        else:
            apworld_native_root, apworld_cache_reused = _extract_apworld_native_payload(apworld)
            if apworld_native_root:
                roots.append(apworld_native_root)
                text = str(apworld_native_root)
                if text not in sys.path:
                    sys.path.insert(0, text)

    before = set(_REGISTERED)
    discovered: set[Path] = set()
    for root in roots:
        discovered.update(_native_directories(root))

    for directory in sorted(discovered, key=lambda p: (len(p.parts), str(p).casefold())):
        _register_directory(directory)
        if apworld_native_root:
            try:
                directory.relative_to(apworld_native_root)
            except ValueError:
                pass
            else:
                text = str(directory)
                if text not in sys.path:
                    sys.path.insert(0, text)

    added = sorted([p for p in _REGISTERED if p not in before], key=str.casefold)
    if apworld_native_root:
        log.info(
            "%s APWorld native cache %s.",
            "Reused" if apworld_cache_reused else "Prepared",
            apworld_native_root,
        )
    if added:
        log.info("Registered %d new native DLL director%s.", len(added), "y" if len(added) == 1 else "ies")

    return {
        "platform": os.name,
        "registered": added,
        "apworld_native_root": str(apworld_native_root or ""),
        "apworld_cache_reused": apworld_cache_reused,
    }


def describe_native_import_failure(exc: BaseException, *, module_name="", apworld_path=None) -> str:
    """Return actionable frozen-runtime context without guessing a missing DLL."""
    details = [f"{type(exc).__name__}: {exc}"]
    if module_name:
        details.append(f"module={module_name}")
    if apworld_path:
        details.append(f"apworld={Path(apworld_path).name}")
    details.append(f"frozen={bool(getattr(sys, 'frozen', False))}")
    details.append(f"registered_native_dirs={len(_REGISTERED)}")
    return "; ".join(details)
