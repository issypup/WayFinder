"""Provide test scrollable tabs support."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "wayfinder" / "app" / "ui" / "shell.py"

def test_all_top_level_pages_use_scrollable_page_factory():
    """Handle test all top level pages use scrollable page factory."""
    source = SHELL.read_text(encoding="utf-8")
    assert "self.page_canvases={}" in source
    assert "canvas=tk.Canvas(outer" in source
    assert 'ttk.Scrollbar(outer,orient="vertical",command=canvas.yview)' in source
    assert "self.pages[name]=outer" in source
    assert "self.page_canvases[name]=canvas" in source

def test_page_wheel_preserves_nested_scrolling_widgets():
    """Handle test page wheel preserves nested scrolling widgets."""
    source = SHELL.read_text(encoding="utf-8")
    assert "def _page_mousewheel(self,event):" in source
    assert "(tk.Canvas,tk.Text,tk.Listbox,ttk.Treeview)" in source

def test_short_pages_fill_the_viewport_for_expanding_children():
    """Handle test short pages fill the viewport for expanding children."""
    source = SHELL.read_text(encoding="utf-8")
    assert "height=max(requested_height,event.height)" in source
    assert "height=max(viewport_height,requested_height)" in source
    assert "def refresh_inner_height(_event=None):" in source
