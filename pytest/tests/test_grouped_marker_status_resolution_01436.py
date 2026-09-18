"""Provide test grouped marker status resolution 01436 support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path


def test_group_popup_uses_id_aware_member_resolver_for_status_and_checked_count():
    """Handle test group popup uses id aware member resolver for status and checked count."""
    source = combined_app_source()
    assert 'getattr(self._map_marker_member_location(marker,index,state), "status", "") == "checked"' in source
    assert 'loc=self._map_marker_member_location(marker,index,state)' in source


def test_group_popup_selection_uses_canonical_resolved_location():
    """Handle test group popup selection uses canonical resolved location."""
    source = combined_app_source()
    assert 'canonical=getattr(loc,"name","") if loc is not None else name' in source
    assert 'self._select_map_location(canonical)' in source
    assert 'self.open_path(canonical)' in source
