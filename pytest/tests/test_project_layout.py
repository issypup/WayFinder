"""Provide test project layout support."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_boot_logging_is_in_entrypoint_not_separate_module():
    """Handle test boot logging is in entrypoint not separate module."""
    assert not (ROOT / "boot_logging.py").exists()
    source = (ROOT / "run_wayfinder.py").read_text(encoding="utf-8")
    assert "def initialize_boot_logging(" in source
    assert "BOOT_LOG_PATH = initialize_boot_logging(APP_VERSION)" in source

def test_pytest_files_are_grouped_under_pytest_folder():
    """Handle test pytest files are grouped under pytest folder."""
    assert (ROOT / "pytest" / "pytest.ini").is_file()
    assert (ROOT / "pytest" / "tests").is_dir()
    assert not (ROOT / "pytest.ini").exists()
    assert not (ROOT / "tests").exists()
