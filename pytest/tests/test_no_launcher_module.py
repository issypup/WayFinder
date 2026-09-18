"""Provide test no launcher module support."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def test_launcher_py_is_removed():
    """Handle test launcher py is removed."""
    assert not (ROOT/"launcher.py").exists()

def test_run_wayfinder_is_true_entrypoint():
    """Handle test run wayfinder is true entrypoint."""
    source=(ROOT/"run_wayfinder.py").read_text(encoding="utf-8")
    assert "def main(" in source
    assert "def run_gui(" in source
    assert "def run_native_runtime(" in source

def test_setup_is_split_into_named_modules():
    """Handle test setup is split into named modules."""
    setup=ROOT/"wayfinder"/"setup"
    assert (setup/"archipelago_core.py").is_file()
    assert (setup/"worlds.py").is_file()
    assert (setup/"player_yamls.py").is_file()
    assert (setup/"dependencies.py").is_file()
    assert (ROOT/"wayfinder"/"runtime"/"process_manager.py").is_file()
