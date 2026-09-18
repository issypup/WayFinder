"""Provide test unified package layout support."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "wayfinder"

def test_single_wayfinder_package_owns_internal_subsystems():
    """Handle test single wayfinder package owns internal subsystems."""
    assert PACKAGE.is_dir()
    for name in ("app", "connection", "maps", "runtime", "setup", "logic"):
        assert (PACKAGE / name / "__init__.py").is_file()

def test_legacy_wayfinder_packages_are_gone():
    """Handle test legacy wayfinder packages are gone."""
    for name in ("wayfinder_gui", "wayfinder_runtime", "wayfinder_setup", "wayfinder_tracker"):
        assert not (ROOT / name).exists()

def test_root_entrypoint_targets_unified_package():
    """Handle test root entrypoint targets unified package."""
    source = (ROOT / "run_wayfinder.py").read_text(encoding="utf-8")
    assert "from wayfinder.setup import" in source
    assert "from wayfinder.runtime.process_manager import" in source
    assert "from wayfinder.app import WayFinderApp" in source

def test_pyinstaller_collects_one_wayfinder_package():
    """Handle test pyinstaller collects one wayfinder package."""
    source = (ROOT / "BUILD-SINGLE-EXE.bat").read_text(encoding="utf-8")
    assert "--collect-submodules wayfinder ^" in source
    assert "--collect-submodules wayfinder_gui" not in source
    assert "--collect-submodules wayfinder_runtime" not in source
    assert "--collect-submodules wayfinder_tracker" not in source
    assert "--collect-submodules wayfinder_setup" not in source
