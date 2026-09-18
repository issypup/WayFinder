"""Provide test unified typography support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "wayfinder" / "app" / "app.py"

def test_wayfinder_uses_unified_segoe_typography():
    """Handle test wayfinder uses unified segoe typography."""
    source = combined_app_source()
    assert 'style.configure("TLabel"' in source
    assert 'font=("Segoe UI",fs)' in source
    assert 'style.configure("Emphasis.TLabel"' in source
    assert 'font=("Segoe UI Semibold",fs)' in source
    assert '"Arial"' not in source
    assert '"Tahoma"' not in source
    assert '"TkDefaultFont"' not in source

def test_existing_name_emphasis_stays_semibold():
    """Handle test existing name emphasis stays semibold."""
    source = combined_app_source()
    assert 'style.configure("Emphasis.Treeview"' in source
    assert 'style="MapName.TCombobox"' in source
    assert 'label_font=("Segoe UI Semibold"' in source
