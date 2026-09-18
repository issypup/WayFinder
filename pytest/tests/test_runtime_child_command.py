"""Provide test runtime child command support."""
from pathlib import Path
import sys

from wayfinder.runtime.process_manager import internal_child_command


def test_source_runtime_child_command_targets_root_entrypoint():
    """Handle test source runtime child command targets root entrypoint."""
    command = internal_child_command("--native-runtime", "55475", "C:/AP", "C:/Players")
    expected_entrypoint = Path(__file__).resolve().parents[2] / "run_wayfinder.py"

    assert command[0] == sys.executable
    assert Path(command[1]).resolve() == expected_entrypoint.resolve()
    assert command[2] == "--native-runtime"
    assert command[3:] == ["55475", "C:/AP", "C:/Players"]
