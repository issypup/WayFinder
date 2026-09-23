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


def activate_dependencies(target, position=1):
    root = str(Path(target).resolve())
    if root not in sys.path:
        sys.path.insert(position, root)
    if root in _activated:
        return
    before = list(sys.path)
    # Retain handles: Windows native libraries must remain discoverable after
    # activation returns. pywin32's own .pth hook also runs below.
    dll_path = Path(root) / 'pywin32_system32'
    if os.name == 'nt':
        # Register managed directories that contain native binaries. This covers
        # package-local .dll/.pyd layouts without game-specific DLL rules.
        candidates = {Path(root)}
        if dll_path.is_dir(): candidates.add(dll_path)
        try:
            for native in Path(root).rglob('*'):
                if native.is_file() and native.suffix.casefold() in {'.pyd', '.dll'}:
                    candidates.add(native.parent)
        except OSError:
            pass
        for candidate in sorted(candidates, key=lambda p: (len(p.parts), str(p).casefold())):
            try: _dll_handles.append(os.add_dll_directory(str(candidate)))
            except (FileNotFoundError, OSError): pass
    site.addsitedir(root)
    added = [p for p in sys.path if p not in before]
    # Preserve the old application/core ordering, but keep installed .pth paths
    # beside their package root rather than behind bundled fallback packages.
    sys.path[:] = before
    offset = sys.path.index(root) + 1
    sys.path[offset:offset] = added
    _activated.add(root)
