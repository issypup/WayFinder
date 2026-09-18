"""Provide test cross game current area 01459 support."""
from types import SimpleNamespace
from unittest.mock import Mock

from wayfinder.app.app import WayFinderApp
from wayfinder.connection.runtime_client import Snapshot


def test_dashboard_rejects_selected_area_from_previous_game():
    """Handle test dashboard rejects selected area from previous game."""
    app=WayFinderApp.__new__(WayFinderApp)
    app.snapshot=Snapshot(game="Game B")
    app.map_last_game="Game A"
    app.active_map_pack=SimpleNamespace(maps_by_title={"Old Area":object()})
    app.map_selector_var=Mock()
    app.map_selector_var.get.return_value="Old Area"

    assert app._dashboard_current_area() == "Unknown"


def test_dashboard_accepts_selected_area_from_current_game():
    """Handle test dashboard accepts selected area from current game."""
    app=WayFinderApp.__new__(WayFinderApp)
    app.snapshot=Snapshot(game="Game B")
    app.map_last_game="Game B"
    app.active_map_pack=SimpleNamespace(maps_by_title={"New Area":object()})
    app.map_selector_var=Mock()
    app.map_selector_var.get.return_value="New Area"

    assert app._dashboard_current_area() == "New Area"


def test_identity_change_clears_previous_game_map_state():
    """Handle test identity change clears previous game map state."""
    app=WayFinderApp.__new__(WayFinderApp)
    app.current_path=object()
    app._active_path_request=7
    app.map_selected_location="Old Check"
    app.active_map_pack=object()
    app.map_last_game="Game A"
    app.map_last_runtime_target="Old Area"
    app.map_selector_var=Mock()
    app.map_selector=Mock()
    app.map_current_area=Mock()
    app._stuck_recommendations=["Old recommendation"]
    app.inventory_deltas=[]
    app.recent_changes=[]
    app.history=[]
    app.history_index=-1
    app._append_log=Mock()

    app._clear_game_specific_ui_state(("host",0,"slot","game a"),("host",0,"slot","game b"))

    assert app.active_map_pack is None
    assert app.map_last_game == ""
    assert app.map_last_runtime_target is None
    app.map_selector_var.set.assert_called_once_with("")
    app.map_selector.configure.assert_called_once_with(values=())
    app.map_current_area.set.assert_called_once_with("Current area: —")
