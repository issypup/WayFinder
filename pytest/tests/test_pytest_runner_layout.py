"""Provide test pytest runner layout support."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def test_runner_avoids_local_pytest_shadowing():
    """Handle test runner avoids local pytest shadowing."""
    source=(ROOT/"run_pytests.py").read_text(encoding="utf-8")
    assert "cwd=project_root.parent" in source
    assert "str(pytest_ini)" in source
    assert "str(tests_dir)" in source
