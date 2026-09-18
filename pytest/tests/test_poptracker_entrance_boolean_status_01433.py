"""Provide test poptracker entrance boolean status 01433 support."""
from types import SimpleNamespace


def _make_app(snapshot):
    """Handle make app."""
    from wayfinder.app.app import WayFinderApp
    app = object.__new__(WayFinderApp)
    app.snapshot = snapshot
    return app


def test_direct_name_match_false_reachable_is_out_of_logic_without_text_status():
    """Handle test direct name match false reachable is out of logic without text status."""
    completion = SimpleNamespace(name="Act Completion (Train Rush)", region="Train Rush", status="out_of_logic", ignored=False)
    snapshot = SimpleNamespace(
        locations=[completion],
        entrance_details=[{
            "name": "Train Rush",
            "source_region": "Dead Bird Studio",
            "target_region": "Train Rush",
            "reachable": False,
            "source_reachable": True,
        }],
        current_reachable_regions=["Dead Bird Studio"],
        reachability_available=True,
    )
    marker = SimpleNamespace(
        location_name="Act 4 - Train Rush",
        member_names=("Can Enter", "Can Complete"),
        section_ids=((), (12345,)),
    )
    app = _make_app(snapshot)
    app._map_marker_member_location = lambda marker,index,state=None: completion if index == 1 else None
    assert app._map_entrance_marker_status(marker) == "out_of_logic"
    assert app._map_entrance_section_status(marker, 0, {}) == "out_of_logic"


def test_time_rift_name_match_false_reachable_is_out_of_logic_without_text_status():
    """Handle test time rift name match false reachable is out of logic without text status."""
    completion = SimpleNamespace(name="Act Completion (Time Rift - The Moon)", region="Time Rift - The Moon", status="out_of_logic", ignored=False)
    snapshot = SimpleNamespace(
        locations=[completion],
        entrance_details=[{
            "name": "Time Rift - The Moon Portal - Entrance 1",
            "source_region": "The Moon",
            "target_region": "Time Rift - The Moon",
            "reachable": False,
            "source_reachable": True,
        }],
        current_reachable_regions=["The Moon"],
        reachability_available=True,
    )
    marker = SimpleNamespace(
        location_name="Time Rift - The Moon",
        member_names=("Can Enter", "Can Complete"),
        section_ids=((), (23456,)),
    )
    app = _make_app(snapshot)
    app._map_marker_member_location = lambda marker,index,state=None: completion if index == 1 else None
    assert app._map_entrance_marker_status(marker) == "out_of_logic"
    assert app._map_entrance_section_status(marker, 0, {}) == "out_of_logic"
