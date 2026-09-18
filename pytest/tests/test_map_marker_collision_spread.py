"""Provide test map marker collision spread support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

APP_SOURCE = Path(__file__).resolve().parents[2] / "wayfinder" / "app" / "app.py"


def test_main_map_uses_collision_aware_display_positions():
    """Handle test main map uses collision aware display positions."""
    text=combined_app_source()
    assert "def _map_marker_display_positions" in text
    assert "display_positions=self._map_marker_display_positions(markers,factor,r)" in text
    assert "x,y=display_positions.get(idx" in text


def test_popout_map_uses_same_collision_layout_and_keeps_synthetic_markers():
    """Handle test popout map uses same collision layout and keeps synthetic markers."""
    text=combined_app_source()
    assert "popout_positions=self._map_marker_display_positions(popout_markers,factor,r)" in text
    assert 'getattr(marker,"is_exit_marker",False)' in text
