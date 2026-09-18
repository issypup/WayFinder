"""Provide test dashboard action frame cleanup support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "wayfinder" / "app" / "app.py"

def test_dashboard_run_actions_are_direct_children_of_overview():
    """Handle test dashboard run actions are direct children of overview."""
    source = combined_app_source()
    start = source.index("def _build_dashboard(self):")
    end = source.index("def _build_search", start)
    block = source[start:end]
    assert 'actions=ttk.Frame(overview)' not in block
    assert 'ttk.Button(run_actions,text="Refresh State"' in block
    assert 'ttk.Button(run_actions,text="I’m Stuck?"' in block
