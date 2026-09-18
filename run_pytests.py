#!/usr/bin/env python3
"""Run WayFinder's pytest suite without local pytest/ package shadowing."""

# sig:kuro:pluralchat

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Handle main."""
    project_root = Path(__file__).resolve().parent
    pytest_root = project_root / "pytest"
    tests_dir = pytest_root / "tests"
    pytest_ini = pytest_root / "pytest.ini"

    print("WayFinder pytest runner")
    print(f"Root:   {project_root}")
    print(f"Python: {sys.executable}")

    if not tests_dir.is_dir():
        print(f"ERROR: tests directory not found: {tests_dir}", file=sys.stderr)
        return 2
    if not pytest_ini.is_file():
        print(f"ERROR: pytest.ini not found: {pytest_ini}", file=sys.stderr)
        return 2

    command = [
        sys.executable, "-m", "pytest",
        "-c", str(pytest_ini),
        str(tests_dir),
        *sys.argv[1:],
    ]
    print("Command:", " ".join(str(part) for part in command))
    print()

    try:
        # IMPORTANT: do not run the child from project_root. The repository
        # has a folder named pytest/, which would otherwise shadow the real
        # installed pytest package on Python's import path.
        completed = subprocess.run(command, cwd=project_root.parent, check=False)
    except KeyboardInterrupt:
        return 130

    if completed.returncode == 0:
        print("\nWayFinder tests PASSED.")
    else:
        print(f"\nWayFinder tests FAILED (exit code {completed.returncode}).", file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
