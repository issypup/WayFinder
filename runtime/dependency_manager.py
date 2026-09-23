"""Provide dependency manager support."""
# /**
#  * Module: wayfinder.runtime/dependency_manager.py
#  * Purpose: Runtime module for dependency manager; bridges loaded Archipelago worlds and live server state into tracker snapshots.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from __future__ import annotations

"""WayFinder dependency discovery and installation.

Scans Archipelago's core requirements, every bundled world's requirements.txt,
and every mirrored custom .apworld. Custom worlds without a requirements file
also receive a conservative static import scan so common undeclared Python
packages (for example ``attr`` -> ``attrs``) are included without importing the
world itself.
"""

import ast
import json
import importlib.metadata as importlib_metadata
from wayfinder.diagnostics import sanitize
import os
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from wayfinder.runtime.wheel_installer import WheelInstaller, read_requirements, runtime_diagnostics

# Constant(s): `COMMON_IMPORT_TO_DIST`; shared configuration value(s) intentionally kept stable within this module.
# Import names that are real third-party dependencies but are not published on
# PyPI under their import name.  The fallback scanner must preserve their real
# VCS source instead of attempting (and inevitably failing) a PyPI lookup by import name.
#
# gclib is deliberately installed with its ``speedups`` extra because WayFinder's
# dependency policy is to install the complete dependency set for every bundled
# and custom world.  The three PyFast projects are also mapped individually so
# an APWorld that imports one directly can still be satisfied without relying on
# gclib being present first.
VCS_IMPORT_REQUIREMENTS = {
    "gclib": "gclib[speedups] @ git+https://github.com/LagoLunatic/gclib.git",
    "pyfastbti": "PyFastBTI @ git+https://github.com/LagoLunatic/PyFastBTI.git@13b24b028b62d199740044f15085f70878ea80a4",
    "pyfasttextureutils": "PyFastTextureUtils @ git+https://github.com/LagoLunatic/PyFastTextureUtils.git@ec40de927daa6b59485e34ea01b8bab1ecd1a31a",
    "pyfastyaz0yay0": "PyFastYaz0Yay0 @ git+https://github.com/LagoLunatic/PyFastYaz0Yay0.git@2adb8a8c00d98f98f245e0304094a0610203a82e",
}

COMMON_IMPORT_TO_DIST = {
    "attr": "attrs",
    "attrs": "attrs",
    "yaml": "PyYAML",
    "maseya": "maseya-z3pr",
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "Crypto": "pycryptodome",
    "bsdiff4": "bsdiff4",
    "jellyfish": "jellyfish",
    "jinja2": "jinja2",
    "schema": "schema",
    "platformdirs": "platformdirs",
    "orjson": "orjson",
    "websockets": "websockets",
    "requests": "requests",
    "pymem": "Pymem",
    # Luigi's Mansion and other Dolphin-based worlds import the module name
    # ``dolphin_memory_engine`` while the distribution is published as
    # ``dolphin-memory-engine``.  1.3.1 switched Windows to a CPython stable-ABI
    # wheel (cp39-abi3), which is compatible with WayFinder's Python 3.13 and
    # avoids retaining older interpreter-specific native builds in the managed
    # dependency directory.
    "dolphin_memory_engine": "dolphin-memory-engine>=1.3.1",
    "pyevermizer": "pyevermizer",
    "zilliandomizer": "zilliandomizer",
    "pkg_resources": "setuptools<81",
}

# Archipelago modules and common local package names that must never be treated
# as PyPI dependencies by the fallback static scanner.
# Constant(s): `AP_INTERNAL`; shared configuration value(s) intentionally kept stable within this module.
AP_INTERNAL = {
    "BaseClasses", "CommonClient", "Generate", "Main", "NetUtils", "Options",
    "Utils", " worlds", "worlds", "Fill", "Rules", "settings", "Launcher",
    "Patch", "MultiServer", "ModuleUpdate", "entrance_rando", "rule_builder",
    "kvui", "test",
    "typing", "dataclasses", "collections", "pathlib", "functools", "itertools",
}

# Constant(s): `REQ_RE`; shared configuration value(s) intentionally kept stable within this module.
REQ_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)")

def _installed_import_index(target):
    """Map import roots to installed distributions using wheel metadata."""
    if not target or not Path(target).is_dir(): return {}
    result = {}
    try:
        for dist in importlib_metadata.distributions(path=[str(Path(target))]):
            name = dist.metadata.get("Name") or ""
            if not name: continue
            tops = {x.strip() for x in (dist.read_text("top_level.txt") or "").splitlines() if x.strip()}
            if not tops:
                for file in dist.files or ():
                    first = str(file).replace("\\", "/").split("/")[0]
                    if first.endswith(".py"): tops.add(first[:-3])
                    elif "/" in str(file).replace("\\", "/") and not first.endswith((".dist-info", ".data")): tops.add(first)
            for top in tops:
                if top.isidentifier(): result.setdefault(top, name)
    except Exception: pass
    return result

def _resolve_import_requirement(module, installed_index=None):
    """Resolve an import root without assuming import-name equals distribution-name."""
    if module in COMMON_IMPORT_TO_DIST: return COMMON_IMPORT_TO_DIST[module]
    if module.casefold() in VCS_IMPORT_REQUIREMENTS: return module.casefold()
    return (installed_index or {}).get(module, module)


# /**
#  * Class: DependencyScan
#  * Purpose: Encapsulate the DependencyScan responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class DependencyScan:
    # Variable(s): `core_requirements` (core requirements); named state retained for the surrounding calculation or subsequent calls.
    """Provide dependency scan behavior."""
    core_requirements: list[str]
    # Variable(s): `builtin_requirement_files` (builtin requirement files); named state retained for the surrounding calculation or subsequent calls.
    builtin_requirement_files: list[str]
    # Variable(s): `custom_requirement_files` (custom requirement files); named state retained for the surrounding calculation or subsequent calls.
    custom_requirement_files: list[str]
    # Variable(s): `custom_inferred_packages` (custom inferred packages); named state retained for the surrounding calculation or subsequent calls.
    custom_inferred_packages: list[str]
    # Variable(s): `custom_worlds` (custom worlds); named state retained for the surrounding calculation or subsequent calls.
    custom_worlds: int
    # Variable(s): `builtin_worlds` (builtin worlds); named state retained for the surrounding calculation or subsequent calls.
    builtin_worlds: int

    # /**
    #  * Function: requirement_file_count
    #  * Purpose: Perform the requirement file count operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    @property
    def requirement_file_count(self) -> int:
        """Handle requirement file count."""
        return len(self.core_requirements) + len(self.builtin_requirement_files) + len(self.custom_requirement_files)

    # /**
    #  * Function: to_dict
    #  * Purpose: Perform the to dict operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def to_dict(self) -> dict:
        # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
        """Handle to dict."""
        data = asdict(self)
        data["requirement_file_count"] = self.requirement_file_count
        return data


# /**
#  * Function: _iter_python_imports
#  * Purpose: Perform the iter python imports operation while keeping the surrounding subsystem state consistent.
#  * @param text: Text supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _iter_python_imports(text: str) -> set[str]:
    """Handle iter python imports."""
    try:
        # Variable(s): `tree` (tree); named state retained for the surrounding calculation or subsequent calls.
        tree = ast.parse(text)
    except Exception:
        return set()
    # Variable(s): `found` (found); named state retained for the surrounding calculation or subsequent calls.
    found: set[str] = set()
    # Loop variable(s): `node` (node); each iteration represents the next value from the iterable below.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # Loop variable(s): `alias` (alias); each iteration represents the next value from the iterable below.
            for alias in node.names:
                found.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".", 1)[0])
    return found


# /**
#  * Function: _available_in_core
#  * Purpose: Perform the available in core operation while keeping the surrounding subsystem state consistent.
#  * @param module: Module supplied by the caller; see type hints and call sites for domain constraints.
#  * @param ap_root: Ap root supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _available_in_core(module: str, ap_root: Path) -> bool:
    """Handle available in core."""
    return (ap_root / f"{module}.py").exists() or (ap_root / module).is_dir() or (ap_root / "worlds" / module).is_dir()


# /**
#  * Function: _is_stdlib
#  * Purpose: Determine whether stdlib is true for the supplied state.
#  * @param module: Module supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _is_stdlib(module: str) -> bool:
    """Handle is stdlib."""
    return module in getattr(sys, "stdlib_module_names", set()) or module in sys.builtin_module_names


# /**
#  * Function: _custom_world_scan
#  * Purpose: Perform the custom world scan operation while keeping the surrounding subsystem state consistent.
#  * @param apworld: Apworld supplied by the caller; see type hints and call sites for domain constraints.
#  * @param ap_root: Ap root supplied by the caller; see type hints and call sites for domain constraints.
#  * @param extract_root: Extract root supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _custom_world_scan(apworld: Path, ap_root: Path, extract_root: Path, installed_index=None) -> tuple[list[Path], set[str]]:
    # Variable(s): `reqs` (reqs); named state retained for the surrounding calculation or subsequent calls.
    """Handle custom world scan."""
    reqs: list[Path] = []
    # Variable(s): `inferred` (inferred); named state retained for the surrounding calculation or subsequent calls.
    inferred: set[str] = set()
    try:
        # Variable(s): `zf` (ZIP archive handle); named state retained for the surrounding calculation or subsequent calls.
        with zipfile.ZipFile(apworld, "r") as zf:
            # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
            names = [n.replace("\\", "/") for n in zf.namelist()]
            # Variable(s): `py_names` (py names); named state retained for the surrounding calculation or subsequent calls.
            py_names = [n for n in names if n.endswith(".py") and not n.startswith("__MACOSX/")]
            # Variable(s): `local_roots` (local roots); named state retained for the surrounding calculation or subsequent calls.
            local_roots = {n.split("/", 1)[0] for n in py_names if "/" in n}
            # Variable(s): `imports` (imports); named state retained for the surrounding calculation or subsequent calls.
            imports: set[str] = set()
            # Loop variable(s): `n` (n); each iteration represents the next value from the iterable below.
            for n in py_names:
                try:
                    imports.update(_iter_python_imports(zf.read(n).decode("utf-8", "replace")))
                except Exception:
                    pass
            # Loop variable(s): `module` (module); each iteration represents the next value from the iterable below.
            for module in imports:
                # Treat modules anywhere inside the APWorld as vendored/local,
                # including legacy worlds that use absolute imports from nested
                # folders (e.g. ``from edge_schema import ...``).
                # Variable(s): `local_module` (local module); named state retained for the surrounding calculation or subsequent calls.
                local_module = any(
                    n.endswith(f"/{module}.py")
                    or n.endswith(f"/{module}/__init__.py")
                    or f"/{module}/" in n
                    for n in names
                )
                if local_module or module in local_roots or module in AP_INTERNAL or _is_stdlib(module) or _available_in_core(module, ap_root):
                    continue
                # Most distributions share their import name. Known exceptions
                # are translated above. This fallback lets older APWorlds with
                # undeclared third-party imports participate in one-click setup.
                inferred.add(_resolve_import_requirement(module, installed_index))
            # Extract any declared requirements files. Preserve their containing
            # directories so relative -r includes continue to work.
            # Loop variable(s): `n` (n); each iteration represents the next value from the iterable below.
            for n in names:
                # Variable(s): `base` (base); named state retained for the surrounding calculation or subsequent calls.
                base = Path(n).name.casefold()
                if base == "requirements.txt" or (base.startswith("requirements-") and base.endswith(".txt")):
                    # Variable(s): `safe` (safe); named state retained for the surrounding calculation or subsequent calls.
                    safe = Path(*WheelInstaller.safe_path(n))
                    # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
                    target = extract_root / apworld.stem / safe
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(n))
                    reqs.append(target)
    except (OSError, zipfile.BadZipFile):
        pass
    return reqs, inferred


# /**
#  * Function: scan_dependencies
#  * Purpose: Perform the scan dependencies operation while keeping the surrounding subsystem state consistent.
#  * @param ap_root: Ap root supplied by the caller; see type hints and call sites for domain constraints.
#  * @param work_root: Work root supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def scan_dependencies(ap_root: str | os.PathLike[str], work_root: str | os.PathLike[str] | None = None) -> tuple[DependencyScan, Path]:
    # Variable(s): `root` (root); named state retained for the surrounding calculation or subsequent calls.
    """Return scan dependencies."""
    root = Path(ap_root).resolve()
    installed_index = {}
    if work_root is None:
        # Variable(s): `work` (work); named state retained for the surrounding calculation or subsequent calls.
        work = Path(tempfile.mkdtemp(prefix="wayfinder_deps_scan_"))
    else:
        # Variable(s): `work` (work); named state retained for the surrounding calculation or subsequent calls.
        work = Path(work_root).resolve()
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)

    # Variable(s): `core` (core); named state retained for the surrounding calculation or subsequent calls.
    core: list[str] = []
    # Variable(s): `root_req` (root req); named state retained for the surrounding calculation or subsequent calls.
    root_req = root / "requirements.txt"
    if root_req.is_file():
        core.append(str(root_req))

    # Variable(s): `builtins` (builtins); named state retained for the surrounding calculation or subsequent calls.
    builtins: list[str] = []
    # Variable(s): `worlds_root` (worlds root); named state retained for the surrounding calculation or subsequent calls.
    worlds_root = root / "worlds"
    # Variable(s): `builtin_worlds` (builtin worlds); named state retained for the surrounding calculation or subsequent calls.
    builtin_worlds = 0
    if worlds_root.is_dir():
        # Loop variable(s): `entry` (entry); each iteration represents the next value from the iterable below.
        for entry in worlds_root.iterdir():
            if entry.is_dir() and not entry.name.startswith((".", "_")):
                builtin_worlds += 1
        # Loop variable(s): `req` (requirement); each iteration represents the next value from the iterable below.
        for req in worlds_root.rglob("requirements.txt"):
            if "tracker" in {p.casefold() for p in req.parts}:
                continue
            builtins.append(str(req.resolve()))

    # Variable(s): `custom_files` (custom files); named state retained for the surrounding calculation or subsequent calls.
    custom_files: list[str] = []
    # Variable(s): `inferred` (inferred); named state retained for the surrounding calculation or subsequent calls.
    inferred: set[str] = set()
    # Variable(s): `custom_worlds` (custom worlds); named state retained for the surrounding calculation or subsequent calls.
    custom_worlds = 0
    # Variable(s): `custom_root` (custom root); named state retained for the surrounding calculation or subsequent calls.
    custom_root = root / "custom_worlds"
    if custom_root.is_dir():
        # Loop variable(s): `apworld` (apworld); each iteration represents the next value from the iterable below.
        for apworld in sorted(custom_root.glob("*.apworld")):
            custom_worlds += 1
            # Variable(s): `reqs` (reqs), `imports` (imports); named state retained for the surrounding calculation or subsequent calls.
            reqs, imports = _custom_world_scan(apworld, root, work / "custom_requirements", installed_index)
            custom_files.extend(str(p) for p in reqs)
            inferred.update(imports)

    # Variable(s): `scan` (scan); named state retained for the surrounding calculation or subsequent calls.
    scan = DependencyScan(
        core_requirements=sorted(core),
        builtin_requirement_files=sorted(set(builtins)),
        custom_requirement_files=sorted(set(custom_files)),
        custom_inferred_packages=sorted(inferred, key=str.casefold),
        custom_worlds=custom_worlds,
        builtin_worlds=builtin_worlds,
    )
    return scan, work


# /**
#  * Function: write_scan_report
#  * Purpose: Perform the write scan report operation while keeping the surrounding subsystem state consistent.
#  * @param scan: Scan supplied by the caller; see type hints and call sites for domain constraints.
#  * @param report_path: Report path supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def write_scan_report(scan: DependencyScan, report_path: str | os.PathLike[str]) -> None:
    # Variable(s): `path` (path); named state retained for the surrounding calculation or subsequent calls.
    """Handle write scan report."""
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scan.to_dict(), indent=2), encoding="utf-8")


# /**
#  * Function: _emit_progress
#  * Purpose: Perform the emit progress operation while keeping the surrounding subsystem state consistent.
#  * @param current: Current supplied by the caller; see type hints and call sites for domain constraints.
#  * @param total: Total supplied by the caller; see type hints and call sites for domain constraints.
#  * @param label: Label supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _emit_progress(current: int, total: int, label: str) -> None:
    # Machine-readable progress line consumed by WayFinder. Keep this on
    # stdout as well so it is preserved by boot logging / console runs.
    # Variable(s): `safe` (safe); named state retained for the surrounding calculation or subsequent calls.
    """Handle emit progress."""
    safe = str(label).replace("\n", " ").replace("\r", " ")
    print(f"WF_DEP_PROGRESS|{current}|{total}|{safe}", flush=True)


# /**
#  * Function: install_all_dependencies
#  * Purpose: Perform the install all dependencies operation while keeping the surrounding subsystem state consistent.
#  * @param ap_root: Ap root supplied by the caller; see type hints and call sites for domain constraints.
#  * @param target: Target supplied by the caller; see type hints and call sites for domain constraints.
#  * @param report_path: Report path supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _requirements_owner(kind: str, value: str, root: Path) -> str:
    """Return a useful world/source name for a dependency unit."""
    if kind == "core":
        return "Archipelago Core"
    path = Path(value)
    try:
        resolved = path.resolve()
        worlds_root = (root / "worlds").resolve()
        if worlds_root in resolved.parents:
            rel = resolved.relative_to(worlds_root)
            return rel.parts[0] if rel.parts else "Built-in world"
    except Exception:
        pass
    parts = list(path.parts)
    if "custom_requirements" in parts:
        try:
            index = parts.index("custom_requirements")
            if index + 1 < len(parts):
                return parts[index + 1]
        except Exception:
            pass
    if kind == "custom":
        return path.parent.name or path.stem
    if kind == "package":
        return "Custom APWorld import scan"
    return "World dependency"


def _classify_install_failure(output: str) -> tuple[str, str]:
    lowered = output.casefold()
    if lowered.startswith('source/direct url dependency unsupported: pyfast'):
        return 'Native extension wheel required', 'The requested PyFast revision contains compiled C code. A matching prebuilt wheel is required; WayFinder will not silently omit requested speedups.'
    for token, diagnosis, explanation in (
        ("invalid or unsupported requirement", "Requirements syntax unsupported", "The requirement line could not be parsed; no checksum comparison was performed."),
        ("unsupported requirements option", "Requirements option unsupported", "This requirements-file option is not supported by the native installer."),
        ("no compatible wheel", "Compatible wheel unavailable", "This dependency needs a wheel matching WayFinder's Python and platform. Local builds are not supported."),
        ("source/direct url", "Source dependency unsupported", "Ask the world maintainer to publish a compatible wheel on PyPI and update the requirement."),
        ("dependency conflict", "Dependency conflict", "The combined world requirements cannot be satisfied together."),
        ("network/download", "Network/download failure", "Check the connection to PyPI and retry; verified wheel downloads are cached."),
        ("verification", "Wheel integrity failure", "The wheel failed integrity validation."),
        ("sha256 mismatch", "Wheel integrity failure", "The download does not match its expected checksum."),
        ("permission", "Permission/file lock", "Close the running tracker and restart WayFinder before retrying."),
        ("winerror", "Permission/file lock", "Close the running tracker and restart WayFinder before retrying."),
    ):
        if token in lowered:
            return diagnosis, explanation
    return "Dependency installation failure", "See the captured installer output for the specific cause."


def _write_install_report(scan: DependencyScan, report_path: str | os.PathLike[str], *, success: bool, results: list[dict], target: Path) -> None:
    """Persist scan + per-unit installation results atomically enough for setup readiness."""
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = scan.to_dict()
    payload.update({
        "install_success": bool(success),
        "python_version": sys.version,
        "python_executable": sys.executable,
        "target": str(target),
        "dependency_runtime": runtime_diagnostics(target),
        "results": results,
        "failed_count": sum(1 for item in results if item.get("status") == "failed"),
    })
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(sanitize(payload), indent=2), encoding="utf-8")
    os.replace(temporary, path)


def dependency_report_ok(report_path: str | os.PathLike[str]) -> bool:
    """True only when the latest dependency run completed successfully."""
    try:
        data = json.loads(Path(report_path).read_text(encoding="utf-8"))
        return bool(data.get("install_success") is True)
    except Exception:
        return False


_DEPENDENCY_REPORT_CACHE: dict[str, tuple[tuple[int, int] | None, dict]] = {}

def load_dependency_report(report_path: str | os.PathLike[str]) -> dict:
    """Load dependency JSON only when the report file has actually changed."""
    path=Path(report_path); key=str(path.resolve())
    try:
        stat=path.stat(); signature=(int(stat.st_mtime_ns),int(stat.st_size))
    except OSError:
        signature=None
    cached=_DEPENDENCY_REPORT_CACHE.get(key)
    if cached is not None and cached[0] == signature: return cached[1]
    if signature is None: data={}
    else:
        try:
            loaded=json.loads(path.read_text(encoding="utf-8")); data=loaded if isinstance(loaded,dict) else {}
        except Exception: data={}
    _DEPENDENCY_REPORT_CACHE[key]=(signature,data)
    return data

def format_dependency_failure_report(report: dict) -> str:
    """Create a compact readable failure summary suitable for GUI copy/details."""
    failed = [item for item in report.get("results", []) if item.get("status") == "failed"]
    lines = [
        "WayFinder dependency installation failed",
        f"Python: {report.get('python_version', sys.version).splitlines()[0]}",
        f"Executable: {report.get('python_executable', sys.executable)}",
        f"Target: {report.get('target', '')}",
        f"Failed units: {len(failed)}",
        "",
    ]
    for number, item in enumerate(failed, 1):
        lines.extend([
            f"[{number}] {item.get('diagnosis', 'Dependency installation failure')}",
            f"World/source: {item.get('owner', 'Unknown')}",
            f"Dependency: {item.get('label', item.get('value', 'Unknown'))}",
            f"Exit code: {item.get('exit_code', 1)}",
            f"Command: {item.get('command', '')}",
            f"Explanation: {item.get('explanation', '')}",
            "Installer output:",
            (item.get("output") or "(no installer output was captured)").strip(),
            "",
        ])
    return "\n".join(lines).rstrip()


def install_all_dependencies(ap_root: str | os.PathLike[str], target: str | os.PathLike[str], report_path: str | os.PathLike[str] | None = None, progress_callback=None) -> int:
    """Install all discovered dependencies and preserve detailed per-unit results.

    Independent units continue after a failure so one broken APWorld does not
    hide unrelated failures. The final exit code is 1 when any unit failed.
    """
    root = Path(ap_root).resolve()
    target_path = Path(target).resolve()

    def emit_progress(current: int, total_count: int, label: str) -> None:
        """Handle emit progress."""
        _emit_progress(current, total_count, label)
        if progress_callback is not None:
            try:
                progress_callback(int(current), int(total_count), str(label))
            except Exception:
                # Progress reporting must never be able to abort installation.
                pass
    target_path.mkdir(parents=True, exist_ok=True)
    scan, work = scan_dependencies(root)
    installed_index = _installed_import_index(target_path)
    scan.custom_inferred_packages = sorted({_resolve_import_requirement(r, installed_index) for r in scan.custom_inferred_packages}, key=str.casefold)

    print(f"WayFinder dependency scan: {scan.builtin_worlds} built-in worlds, {scan.custom_worlds} custom APWorlds", flush=True)
    print(f"Declared requirement files: {scan.requirement_file_count}", flush=True)
    if scan.custom_inferred_packages:
        print("Inferred custom-world packages: " + ", ".join(scan.custom_inferred_packages), flush=True)

    # Declared requirements are authoritative. Do not add an unpinned inferred
    # source for a package already covered by an exact world/core requirement.
    declared_names = set()
    for requirement_file in scan.core_requirements + scan.builtin_requirement_files + scan.custom_requirement_files:
        try:
            declared, _ = read_requirements(requirement_file)
            declared_names.update(canonicalize_name(r.name) for r in declared)
        except Exception:
            pass  # The original unit reports the actual parsing failure below.

    units = ([("core", r) for r in scan.core_requirements]
             + [("world", r) for r in scan.builtin_requirement_files]
             + [("custom", r) for r in scan.custom_requirement_files]
             + [("package", r) for r in scan.custom_inferred_packages
                if canonicalize_name(Requirement(r).name) not in declared_names])
    results = []
    total = max(1, len(units))
    # Invalidate readiness before any network or target mutation begins.
    if report_path:
        _write_install_report(scan, report_path, success=False, results=[], target=target_path)
    installer = WheelInstaller(target_path)
    try:
        if not units:
            emit_progress(1, 1, "No dependencies required")
        for index, (kind, value) in enumerate(units, 1):
            owner = _requirements_owner(kind, value, root)
            label = f"{owner} — {value}"
            output = []

            def progress(message):
                output.append(message)
                print(message, flush=True)
                emit_progress(index - 1, total, message)

            installer.progress = progress
            emit_progress(index - 1, total, label)
            result = {"kind": kind, "value": value, "owner": owner, "label": label,
                      "command": "native-wheel-install " + value}
            try:
                if kind == "package":
                    requirements = [Requirement(VCS_IMPORT_REQUIREMENTS.get(value.casefold(), value))]
                    constraints = []
                else:
                    requirements, constraints = read_requirements(value)
                # Core pins apply to every world even if core installation failed.
                if kind != "core":
                    for core in scan.core_requirements:
                        core_requirements, core_constraints = read_requirements(core)
                        constraints.extend(core_requirements + core_constraints)
                installer.install(requirements, constraints)
                result.update(exit_code=0, status="installed")
            except Exception as exc:
                progress(f"{type(exc).__name__}: {exc}")
                diagnosis, explanation = _classify_install_failure(str(exc))
                result.update(exit_code=1, status="failed", diagnosis=diagnosis, explanation=explanation)
            result["output"] = "\n".join(output)[-20000:]
            results.append(result)
            emit_progress(index, total, label)
            if report_path:
                _write_install_report(scan, report_path, success=False, results=results, target=target_path)
        success = all(r["status"] == "installed" for r in results)
        if report_path:
            _write_install_report(scan, report_path, success=success, results=results, target=target_path)
        return 0 if success else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
