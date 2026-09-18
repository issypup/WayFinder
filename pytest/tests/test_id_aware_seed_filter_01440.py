"""Provide test id aware seed filter 01440 support."""
from wayfinder.app.core.source_layout import combined_app_source

from pathlib import Path


def test_seed_filter_uses_id_aware_member_resolver():
    """Handle test seed filter uses id aware member resolver."""
    source=combined_app_source()
    block=source[source.index("if pack and live:"):source.index("if pack and pack.has_python:")]
    assert "pack.location_names-live" not in block
    assert "_map_marker_member_location(marker, member_index, state)" in block
    assert "concrete map check reference(s)" in block


def test_seed_filter_ignores_synthetic_and_owner_only_labels():
    """Handle test seed filter ignores synthetic and owner only labels."""
    source=combined_app_source()
    block=source[source.index("if pack and live:"):source.index("if pack and pack.has_python:")]
    assert 'getattr(marker, "is_synthetic_marker", False)' in block
    assert "for member_index,member_name in enumerate(marker.member_names)" in block
