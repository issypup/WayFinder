"""Activate installed libraries and their normal .pth startup hooks at runtime.

Installation never executes these hooks. Activation happens only in the tracker
process before importing the installed libraries, like Python site-packages.
"""
import os
from pathlib import Path
import site
import sys

_activated = set()
_dll_handles = []
_dll_directories = []


def _native_directories(root: Path):
    """Return managed directories that can participate in Windows DLL loading."""
    candidates = {root}
    pywin32 = root / "pywin32_system32"
    if pywin32.is_dir():
        candidates.add(pywin32)
    try:
        for native in root.rglob("*"):
            if native.is_file() and native.suffix.casefold() in {".pyd", ".dll"}:
                candidates.add(native.parent)
    except OSError:
        pass
    return sorted(candidates, key=lambda p: (len(p.parts), str(p).casefold()))


def _activate_windows_native_search(root: Path):
    """Expose managed native-library folders to frozen and normal Python."""
    if os.name != "nt":
        return

    directories = _native_directories(root)
    # os.add_dll_directory is the primary CPython 3.8+ mechanism. Keep every
    # handle alive for the runtime lifetime or Windows removes the directory.
    for candidate in directories:
        text = str(candidate)
        if text in _dll_directories:
            continue
        try:
            _dll_handles.append(os.add_dll_directory(text))
            _dll_directories.append(text)
        except (FileNotFoundError, OSError):
            pass

    # Frozen applications can load a .pyd successfully and then have that
    # extension (or a DLL it loads itself) use the process PATH to resolve a
    # sibling DLL. PyInstaller's one-file bootstrap does not know about
    # WayFinder's external managed package tree, so mirror the same directories
    # into PATH. This is deliberately generic rather than APWorld-specific.
    current = os.environ.get("PATH", "")
    existing = {p.casefold() for p in current.split(os.pathsep) if p}
    prepend = []
    for candidate in directories:
        text = str(candidate)
        if text.casefold() not in existing:
            prepend.append(text)
            existing.add(text.casefold())
    if prepend:
        os.environ["PATH"] = os.pathsep.join(prepend + ([current] if current else []))


def activate_dependencies(target, position=1):
    root_path = Path(target).resolve()
    root = str(root_path)
    if root not in sys.path:
        sys.path.insert(position, root)

    # Refresh native search paths even after Python-path activation. Managed
    # packages may have been installed/updated since the runtime first started.
    _activate_windows_native_search(root_path)
    if root in _activated:
        return

    before = list(sys.path)
    site.addsitedir(root)
    added = [p for p in sys.path if p not in before]
    # Preserve the old application/core ordering, but keep installed .pth paths
    # beside their package root rather than behind bundled fallback packages.
    sys.path[:] = before
    offset = sys.path.index(root) + 1
    sys.path[offset:offset] = added
    _activated.add(root)
