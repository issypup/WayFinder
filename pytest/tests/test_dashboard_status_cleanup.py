"""Provide test dashboard status cleanup support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

APP=Path(__file__).resolve().parents[2]/"wayfinder"/"app"/"app.py"

def test_sidebar_no_longer_contains_live_tracker_or_appearance_sections():
    """Handle test sidebar no longer contains live tracker or appearance sections."""
    source=combined_app_source()
    build=source[source.index("def _build_ui(self):"):source.index("def _split_server_port",source.index("def _build_ui(self):"))]
    assert 'text="LIVE STATUS"' not in build
    assert 'text="TRACKER STATUS"' not in build
    assert 'text="TEXT SIZE"' not in build
    assert 'ttk.Spinbox(appearance' not in build
    assert 'pt  •  Cherry Blossom' not in build

def test_topbar_has_no_refresh_or_fuzzy_search_widget():
    """Handle test topbar has no refresh or fuzzy search widget."""
    source=combined_app_source()
    block=source[source.index("def _build_topbar(self):"):source.index("def _build_pages",source.index("def _build_topbar(self):"))]
    assert 'ttk.Entry(title_row,textvariable=self.global_search' not in block
    assert 'self.refresh_btn.pack(side="right"' not in block

def test_dashboard_owns_refresh_and_merged_status():
    """Handle test dashboard owns refresh and merged status."""
    source=combined_app_source()
    block=source[source.index("def _build_dashboard(self):"):source.index("def _build_search",source.index("def _build_dashboard(self):"))]
    assert 'text="LIVE + TRACKER STATUS"' in block
    assert 'self.dashboard_live_status' in block
    assert 'self.refresh_btn=ttk.Button(run_actions,text="Refresh State"' in block
    assert "tracker_line=(" in block
