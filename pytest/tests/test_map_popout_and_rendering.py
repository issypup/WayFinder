"""Provide test map popout and rendering support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path


def _source():
    """Handle source."""
    return combined_app_source()


def test_map_render_worker_and_progress_present():
    """Handle test map render worker and progress present."""
    src=_source()
    assert "WayFinder-Map-Render" in src
    assert "preparing map in background" in src
    assert "map_render_progress" in src


def test_location_labels_override_semantic_zoom_hiding():
    """Handle test location labels override semantic zoom hiding."""
    src=_source()
    assert 'visible and self.map_show_labels.get() else "hidden"' in src

def test_popout_is_live_and_does_not_use_postscript_snapshot():
    """Handle test popout is live and does not use postscript snapshot."""
    src=_source()
    start=src.index("    def _popout_map(self):")
    end=src.index("    def _draw_route_overlay(self):", start)
    block=src[start:end]
    assert "postscript(" not in block
    assert "_refresh_popout_map" in block
    assert "LEGEND  •  click to hide / show" in block
    assert "MAP OPTIONS" in block
    assert "map_area_progress_scale" in block
