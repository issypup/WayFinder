"""Provide test requirements file support."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def test_requirements_file_contains_wayfinder_dev_dependencies():
    """Handle test requirements file contains wayfinder dev dependencies."""
    text=(ROOT/"requirements.txt").read_text(encoding="utf-8")
    assert "Pillow" in text
    assert "pytest" in text
    assert "WayFinder Setup" in text
