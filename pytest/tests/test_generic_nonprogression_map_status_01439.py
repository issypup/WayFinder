"""Provide test generic nonprogression map status 01439 support."""

from pathlib import Path
from types import SimpleNamespace

from wayfinder.app.app import WayFinderApp


def _loc(status="unknown", reason="", ignored=False):
    """Handle loc."""
    return SimpleNamespace(status=status, unknown_reason=reason, ignored=ignored)


def test_absent_reconstructed_graph_is_distinct_map_status():
    """Handle test absent reconstructed graph is distinct map status."""
    app = WayFinderApp.__new__(WayFinderApp)
    loc = _loc(
        "unknown",
        "Server location is not present in the reconstructed APWorld graph."
    )
    assert app._map_effective_location_status(loc) == "non_progression"


def test_other_unknowns_remain_unknown():
    """Handle test other unknowns remain unknown."""
    app = WayFinderApp.__new__(WayFinderApp)
    assert app._map_effective_location_status(
        _loc("unknown", "Exact logic unavailable — matching player YAML is missing.")
    ) == "unknown"


def test_real_logic_statuses_are_preserved():
    """Handle test real logic statuses are preserved."""
    app = WayFinderApp.__new__(WayFinderApp)
    assert app._map_effective_location_status(_loc("reachable")) == "reachable"
    assert app._map_effective_location_status(_loc("out_of_logic")) == "out_of_logic"
    assert app._map_effective_location_status(_loc("checked")) == "checked"
    assert app._map_effective_location_status(_loc("reachable", ignored=True)) == "ignored"


def test_map_ui_exposes_nonprogression_filter_and_visual():
    """Handle test map ui exposes nonprogression filter and visual."""
    source = (Path(__file__).parents[2] / "wayfinder" / "app" / "app.py").read_text(encoding="utf-8")
    assert '"non_progression": tk.BooleanVar' in source
    assert '"Non-progression / untracked"' in source
    assert '"map_show_non_progression"' in source
