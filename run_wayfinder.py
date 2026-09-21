#!/usr/bin/env python3
# /**
#  * Module: run_wayfinder.py
#  * Purpose: Canonical WayFinder executable entry point, early boot logger, and internal process-role dispatcher.
#  * Maintenance: Keep this file stdlib-only until boot logging is initialized.
#  */

# sig:kuro:pluralchat

"""WayFinder single-application entry point.

Normal execution opens WayFinder directly. Internal child roles re-enter this
same executable for the isolated native runtime and dependency installer.

Early boot logging intentionally lives here rather than in a separate module:
this is the one place guaranteed to execute before any WayFinder/Archipelago
imports in every application and child-process role.
"""

from __future__ import annotations

import atexit
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import TextIO
from wayfinder.diagnostics import sanitize, make_record, format_record

from wayfinder.version import WAYFINDER_VERSION

APP_VERSION = WAYFINDER_VERSION
# ---------------------------------------------------------------------------
# Early boot logging
# ---------------------------------------------------------------------------

_BOOT_LOG_LOCK = threading.RLock()
_BOOT_LOG_INITIALIZED = False
_BOOT_LOG_PATH: Path | None = None
_BOOT_LATEST_PATH: Path | None = None
_BOOT_LOG_FILES: list[TextIO] = []


def _boot_app_data_root() -> Path:
    """Return WayFinder's application-data root without importing project code."""
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "WayFinder"
    return Path.home() / ".wayfinder"


class _BootTeeStream:
    """Mirror stdout/stderr to their original stream and active boot logs."""

    def __init__(self, original: TextIO, files: list[TextIO]) -> None:
        """Handle init."""
        self.original = original
        self.files = files
        self.pending = ""

    def write(self, data: str) -> int:
        """Handle write."""
        raw = str(data)
        with _BOOT_LOG_LOCK:
            self.pending += raw
            while "\n" in self.pending:
                line, self.pending = self.pending.split("\n", 1)
                text = sanitize(line) + "\n"
                try:
                    self.original.write(text)
                    self.original.flush()
                except Exception:
                    pass
                persisted = text if any(f"[{c}]" in text for c in ("RUNTIME","AP","LOGIC","MAP","APWORLD","DEPENDENCY","SNAPSHOT","GUI")) else format_record(make_record(text)) + "\n"
                for handle in self.files:
                    try:
                        handle.write(persisted)
                        handle.flush()
                    except Exception:
                        pass
        return len(raw)

    def flush(self) -> None:
        """Handle flush."""
        with _BOOT_LOG_LOCK:
            try:
                self.original.flush()
            except Exception:
                pass
            for handle in self.files:
                try:
                    handle.flush()
                except Exception:
                    pass

    def isatty(self) -> bool:
        """Handle isatty."""
        try:
            return bool(self.original.isatty())
        except Exception:
            return False

    def fileno(self) -> int:
        """Handle fileno."""
        return self.original.fileno()

    @property
    def encoding(self):
        """Handle encoding."""
        return getattr(self.original, "encoding", "utf-8")

    @property
    def errors(self):
        """Handle errors."""
        return getattr(self.original, "errors", "replace")


def initialize_boot_logging(version: str = "unknown") -> Path:
    """Start or join the single current WayFinder log.

    WayFinder intentionally keeps only ``latest.log`` and ``latest.pid``.
    Hidden child roles inherit the same log path and append to it. Legacy
    timestamped boot logs are removed by the owner process on startup.
    """
    global _BOOT_LOG_INITIALIZED, _BOOT_LOG_PATH, _BOOT_LATEST_PATH, _BOOT_LOG_FILES

    if _BOOT_LOG_INITIALIZED and _BOOT_LOG_PATH is not None:
        return _BOOT_LOG_PATH

    inherited = os.environ.get("WF_BOOT_LOG_PATH", "").strip()
    logs_dir = _boot_app_data_root() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    latest_path = logs_dir / "latest.log"
    pid_path = logs_dir / "latest.pid"

    if inherited:
        log_path = Path(inherited)
        is_owner = False
    else:
        log_path = latest_path
        os.environ["WF_BOOT_LOG_PATH"] = str(log_path)
        is_owner = True
        for old_log in logs_dir.glob("boot-*.log"):
            try:
                old_log.unlink()
            except OSError:
                pass
        try:
            pid_path.write_text(str(os.getpid()) + "\n", encoding="utf-8")
        except OSError:
            pass

    log_path.parent.mkdir(parents=True, exist_ok=True)
    session_handle = log_path.open("w" if is_owner else "a", encoding="utf-8", buffering=1)

    _BOOT_LOG_FILES = [session_handle]
    _BOOT_LOG_PATH = log_path
    _BOOT_LATEST_PATH = latest_path
    _BOOT_LOG_INITIALIZED = True

    sys.stdout = _BootTeeStream(sys.stdout, _BOOT_LOG_FILES)  # type: ignore[assignment]
    sys.stderr = _BootTeeStream(sys.stderr, _BOOT_LOG_FILES)  # type: ignore[assignment]

    role = "app"
    if "--native-runtime" in sys.argv:
        role = "native-runtime"
    elif "--install-dependencies" in sys.argv:
        role = "dependency-installer"

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    print("=" * 78, flush=True)
    print(f"WayFinder {version} boot log", flush=True)
    print(f"Started: {now}", flush=True)
    print(f"Role: {role}", flush=True)
    print(f"PID: {os.getpid()}", flush=True)
    print(f"Python: {sys.version.replace(chr(10), ' ')}", flush=True)
    print(f"Executable: {sys.executable}", flush=True)
    print(f"Command: {' '.join(sys.argv)}", flush=True)
    print(f"Latest log: {latest_path}", flush=True)
    print(f"Latest PID: {pid_path}", flush=True)
    print("=" * 78, flush=True)

    def _close_boot_logs() -> None:
        """Flush and close the current log stream."""
        for stream in (sys.stdout, sys.stderr):
            if isinstance(stream, _BootTeeStream) and stream.pending:
                stream.write("\n")
        for handle in _BOOT_LOG_FILES:
            try:
                handle.flush()
                handle.close()
            except Exception:
                pass

    atexit.register(_close_boot_logs)
    return log_path


def current_log_path() -> Path | None:
    """Return the current WayFinder log path, if initialized."""
    return _BOOT_LOG_PATH


def latest_log_path() -> Path:
    """Return the stable path to the most recent WayFinder boot log."""
    return _BOOT_LATEST_PATH or (_boot_app_data_root() / "logs" / "latest.log")


# Initialize logging before importing WayFinder or Archipelago-facing modules.
BOOT_LOG_PATH = initialize_boot_logging(APP_VERSION)

from wayfinder.setup import (  # noqa: E402 - intentionally after boot logging
    AP_CORE_SOURCE,
    PLAYERS_DIR,
    core_ready,
    load_settings,
)
from wayfinder.runtime.process_manager import (  # noqa: E402
    allocate_ipc_port,
    start_native_runtime,
    stop_process,
)


def run_gui() -> None:
    """Open the main WayFinder GUI directly."""
    from wayfinder.app import WayFinderApp

    settings = load_settings()
    app = WayFinderApp(
        initial_server=str(settings.get("server", "") or ""),
        initial_name=str(settings.get("slot_name", "") or ""),
        initial_password=str(settings.get("password", "") or ""),
    )
    app.run()


def run_native_runtime(argv: list[str]) -> None:
    """Run the isolated native logic worker role."""
    if len(argv) < 3:
        raise SystemExit("--native-runtime requires PORT AP_CORE_ROOT [PLAYERS_PATH]")
    from wayfinder.runtime.server import run_runtime
    run_runtime(int(argv[1]), argv[2], argv[3] if len(argv) > 3 else "")


def run_dependency_installer(argv: list[str]) -> None:
    """Run the dependency installer child role."""
    if len(argv) < 3:
        raise SystemExit("--install-dependencies requires AP_CORE_ROOT TARGET [REPORT]")
    from wayfinder.runtime.dependency_manager import install_all_dependencies
    raise SystemExit(install_all_dependencies(argv[1], argv[2], argv[3] if len(argv) > 3 else None))


def main(argv: list[str] | None = None) -> None:
    """Dispatch internal roles or open the single WayFinder application."""
    arguments = list(sys.argv if argv is None else argv)

    if "--test-apworld" in arguments:
        from wayfinder.runtime.apworld_compatibility import compatibility_child
        index = arguments.index("--test-apworld")
        raise SystemExit(compatibility_child(arguments[index + 1]))

    if "--native-runtime" in arguments:
        index = arguments.index("--native-runtime")
        run_native_runtime(arguments[index:])
        return

    if "--install-dependencies" in arguments:
        index = arguments.index("--install-dependencies")
        run_dependency_installer(arguments[index:])
        return

    port = allocate_ipc_port()
    os.environ["WF_RUNTIME_PORT"] = str(port)

    # The GUI owns native-runtime startup.  This deliberately leaves the
    # runtime stopped while WayFinder Setup is incomplete; Connect starts it
    # only after all hard setup prerequisites have passed.
    run_gui()


if __name__ == "__main__":
    main()
