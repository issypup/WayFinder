"""Internal WayFinder runtime worker process management.

WayFinder remains one user-facing application/EXE. The native logic runtime
is a hidden child process so APWorld imports, asyncio, and logic failures are
isolated from Tkinter.
"""

from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

import os
import socket
import subprocess
import sys
from pathlib import Path


def allocate_ipc_port() -> int:
    """Reserve an available localhost TCP port for GUI/runtime IPC."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def internal_child_command(mode: str, *args: str) -> list[str]:
    """Build a command that re-enters the same WayFinder executable."""
    if getattr(sys, "frozen", False):
        return [sys.executable, mode, *args]
    return [sys.executable, str(Path(__file__).resolve().parents[2] / "run_wayfinder.py"), mode, *args]


def start_native_runtime(port: int, ap_core_root: str | Path, players_path: str | Path, *, env: dict[str, str] | None = None) -> subprocess.Popen:
    """Start the hidden native runtime worker process."""
    child_env = dict(os.environ if env is None else env)
    child_env["WF_RUNTIME_PORT"] = str(port)
    command = internal_child_command("--native-runtime", str(port), str(ap_core_root), str(players_path))
    return subprocess.Popen(command, env=child_env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def stop_process(process: subprocess.Popen | None) -> None:
    """Terminate an owned worker process when it is still running."""
    if process is None:
        return
    try:
        if process.poll() is None:
            process.terminate()
    except Exception:
        _ignored("intentional best-effort fallback")
