"""Provide test map legend controls 01474 support."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _source(path: str) -> str:
    """Handle source."""
    return (ROOT / path).read_text(encoding="utf-8")


def test_map_page_has_grouped_legend_and_control_cards():
    """Handle test map page has grouped legend and control cards."""
    source = _source("wayfinder/app/pages/map_page.py")
    assert 'text="Legend"' in source
    assert 'text="Map Controls"' in source
    assert 'text="DISPLAY"' in source
    assert 'text="NAVIGATION"' in source
    assert 'text="MARKERS"' in source
    assert 'style="CardAlt.TCheckbutton"' in source


def test_theme_defines_card_alt_map_control_styles():
    """Handle test theme defines card alt map control styles."""
    source = _source("wayfinder/app/ui/appearance.py")
    assert 'style.configure("CardAltTitle.TLabel"' in source
    assert 'style.configure("CardAltMuted.TLabel"' in source
    assert 'style.configure("CardAlt.TCheckbutton"' in source
