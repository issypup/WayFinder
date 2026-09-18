"""Provide test dashboard connection controls support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "wayfinder" / "app" / "app.py"

def test_topbar_no_longer_renders_connection_controls():
    """Handle test topbar no longer renders connection controls."""
    source = combined_app_source()
    start = source.index("def _build_topbar(self):")
    end = source.index("def _build_pages", start)
    block = source[start:end]
    assert 'conn=ttk.Frame(top' not in block
    assert 'ttk.Entry(conn' not in block
    assert 'self.connect_btn=ttk.Button(conn' not in block

def test_dashboard_contains_connection_controls():
    """Handle test dashboard contains connection controls."""
    source = combined_app_source()
    start = source.index("def _build_dashboard(self):")
    end = source.index("def _build_search", start)
    block = source[start:end]
    assert 'text="CONNECTION"' in block
    assert '("Server",self.server_host_var,24)' in block
    assert '("Port",self.server_port_var,7)' in block
    assert '("Slot",self.name_var,18)' in block
    assert '("Game",self.game_var,22)' in block
    assert 'self.connect_btn=ttk.Button(connection_row,text="Connect"' in block
