"""Provide test generic untracked map status 01441 support."""

from types import SimpleNamespace

from wayfinder.app.app import WayFinderApp


def _loc(status="unknown", reason="", ignored=False):
    """Handle loc."""
    return SimpleNamespace(status=status, unknown_reason=reason, ignored=ignored)


def test_adapter_rule_failure_remains_unknown_on_maps():
    """Handle test adapter rule failure remains unknown on maps."""
    app=WayFinderApp.__new__(WayFinderApp)
    loc=_loc(
        "unknown",
        "Location Example Check: AttributeError: custom state helper is unavailable",
    )
    assert app._map_effective_location_status(loc) == "unknown"


def test_server_only_location_is_untracked_not_unknown_on_maps():
    """Handle test server only location is untracked not unknown on maps."""
    app=WayFinderApp.__new__(WayFinderApp)
    loc=_loc(
        "unknown",
        "Server location is not present in the reconstructed APWorld graph.",
    )
    assert app._map_effective_location_status(loc) == "non_progression"


def test_missing_yaml_remains_genuine_unknown():
    """Handle test missing yaml remains genuine unknown."""
    app=WayFinderApp.__new__(WayFinderApp)
    loc=_loc(
        "unknown",
        "Exact logic unavailable — matching player YAML is missing.",
    )
    assert app._map_effective_location_status(loc) == "unknown"


def test_authoritative_statuses_are_unchanged():
    """Handle test authoritative statuses are unchanged."""
    app=WayFinderApp.__new__(WayFinderApp)
    assert app._map_effective_location_status(_loc("reachable")) == "reachable"
    assert app._map_effective_location_status(_loc("out_of_logic")) == "out_of_logic"
    assert app._map_effective_location_status(_loc("checked")) == "checked"
