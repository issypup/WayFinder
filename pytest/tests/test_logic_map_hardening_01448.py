"""Provide test logic map hardening 01448 support."""
from pathlib import Path
from types import SimpleNamespace

from wayfinder.app.app import WayFinderApp


def _app(snapshot):
    """Handle app."""
    app = WayFinderApp.__new__(WayFinderApp)
    app.snapshot = snapshot
    return app


def test_frlg_native_crosscheck_runs_after_location_population():
    """Regression: location intersection must not happen while the set is empty."""
    source = (Path(__file__).parents[2] / "wayfinder" / "logic" / "apworld_adapter.py").read_text(encoding="utf-8")
    fn = source[source.index("def evaluate_generated_world"):]
    location_add = fn.index("result.reachable_locations.add(lname)")
    native_crosscheck = fn.index("_apply_frlg_native_reachability_crosscheck(", location_add)
    assert native_crosscheck > location_add


def test_ambiguous_fuzzy_entrance_label_does_not_pick_first_match():
    """Handle test ambiguous fuzzy entrance label does not pick first match."""
    snapshot = SimpleNamespace(
        locations=[],
        entrance_details=[
            {"name": "Dark Cave North Entrance", "source_region": "Route 9", "target_region": "Dark Cave", "reachable": True},
            {"name": "Ice Cave South Entrance", "source_region": "Route 10", "target_region": "Ice Cave", "reachable": False},
        ],
        current_reachable_regions=[],
        reachability_available=True,
    )
    marker = SimpleNamespace(location_name="Cave", member_names=("Can Enter",), section_ids=((),))
    assert _app(snapshot)._map_entrance_marker_status(marker) == "unknown"


def test_unique_meaningful_fuzzy_entrance_label_is_still_supported():
    """Handle test unique meaningful fuzzy entrance label is still supported."""
    snapshot = SimpleNamespace(
        locations=[],
        entrance_details=[
            {"name": "The Moon Portal Entrance 1", "source_region": "The Moon", "target_region": "Moon Rift", "reachable": True},
            {"name": "Gallery Lobby", "source_region": "Gallery", "target_region": "Lobby", "reachable": False},
        ],
        current_reachable_regions=[],
        reachability_available=True,
    )
    marker = SimpleNamespace(location_name="Moon Portal", member_names=("Can Enter",), section_ids=((),))
    assert _app(snapshot)._map_entrance_marker_status(marker) == "reachable"


def test_adapter_rule_failure_remains_unknown_on_map():
    """Handle test adapter rule failure remains unknown on map."""
    loc = SimpleNamespace(
        status="unknown",
        unknown_reason="Location Example Check: AttributeError: custom state helper is unavailable",
        ignored=False,
    )
    assert _app(SimpleNamespace())._map_effective_location_status(loc) == "unknown"


def test_server_only_location_remains_non_progression():
    """Handle test server only location remains non progression."""
    loc = SimpleNamespace(
        status="unknown",
        unknown_reason="Server location is not present in the reconstructed APWorld graph.",
        ignored=False,
    )
    assert _app(SimpleNamespace())._map_effective_location_status(loc) == "non_progression"
