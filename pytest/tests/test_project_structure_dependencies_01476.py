"""Regression coverage for generated project dependency documentation."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "PROJECT_STRUCTURE.md"
GENERATOR = ROOT / "tools" / "generate_project_structure.py"


def test_project_structure_generator_is_current_and_architecture_safe():
    """Handle test project structure generator is current and architecture safe."""
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_generated_import_names_are_not_package_prefixed_stdlib():
    """Handle test generated import names are not package prefixed stdlib."""
    text = DOC.read_text(encoding="utf-8")
    bad_fragments = (
        "wayfinder.app.pages.__future__",
        "wayfinder.app.pages.tkinter",
        "wayfinder.app.pages.dataclasses",
        "wayfinder.app.wayfinder",
        "wayfinder.runtime.wayfinder",
        "wayfinder.setup.wayfinder",
    )
    for fragment in bad_fragments:
        assert fragment not in text


def test_reverse_importers_and_lazy_backrefs_are_classified_correctly():
    """Handle test reverse importers and lazy backrefs are classified correctly."""
    text = DOC.read_text(encoding="utf-8")
    dashboard = text.split("### `wayfinder/app/pages/dashboard.py`", 1)[1].split("### `", 1)[0]
    assert "**Import-time importers:** `wayfinder.app.app`" in dashboard
    assert "**Lazy/local internal imports:** `wayfinder.app.app`" in dashboard
    assert "runtime coupling, not an import-time cycle" in dashboard


def test_map_page_dependency_points_down_to_map_subsystem():
    """Handle test map page dependency points down to map subsystem."""
    text = DOC.read_text(encoding="utf-8")
    section = text.split("### `wayfinder/app/pages/map_page.py`", 1)[1].split("### `", 1)[0]
    assert "`wayfinder.app.map.map_rendering`" in section
    assert "`wayfinder.app.map.map_markers`" in section
    assert "**Import-time importers:** `wayfinder.app.app`" in section
