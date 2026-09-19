"""Provide test zoom floor 01475 support."""
from wayfinder.maps import packs


def test_zoom_levels_reach_two_percent_and_are_ordered():
    """Handle test zoom levels reach two percent and are ordered."""
    assert packs.ZOOM_CACHE_LEVELS[0] == 2
    assert packs.ZOOM_CACHE_LEVELS == tuple(sorted(set(packs.ZOOM_CACHE_LEVELS)))
    assert 5 in packs.ZOOM_CACHE_LEVELS
    assert 25 in packs.ZOOM_CACHE_LEVELS
    assert 100 in packs.ZOOM_CACHE_LEVELS
    assert 200 in packs.ZOOM_CACHE_LEVELS


def test_zoom_cache_version_bumped_for_new_persistent_levels():
    """Handle test zoom cache version bumped for new persistent levels."""
    assert packs.ZOOM_CACHE_VERSION >= 4
