"""Provide test pytest output detail support."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_pytest_reports_result_for_each_test_python_file():
    """Handle test pytest reports result for each test python file."""
    reporter = (ROOT / "pytest" / "conftest.py").read_text(encoding="utf-8")
    assert "WayFinder Test File Results" in reporter
    assert "Path(report.nodeid.split" in reporter
    assert "tests passed" in reporter

def test_pytest_reports_test_file_summary():
    """Handle test pytest reports test file summary."""
    reporter = (ROOT / "pytest" / "conftest.py").read_text(encoding="utf-8")
    assert "Test files completed:" in reporter
    assert "Files passed:" in reporter
    assert "Files failed:" in reporter
