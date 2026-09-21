"""Regression tests for live current-area state vs manually browsed map state."""
from types import SimpleNamespace
from unittest.mock import Mock
from wayfinder.app.app import WayFinderApp
from wayfinder.connection.runtime_client import Snapshot


def test_dashboard_current_area_uses_runtime_target_not_selected_map():
    app=WayFinderApp.__new__(WayFinderApp)
    app.snapshot=Snapshot(game="Game B")
    app.map_last_game="Game B"
    app.map_last_runtime_target="Player Area"
    app.map_selector_var=Mock()
    app.map_selector_var.get.return_value="Browsed Area"
    assert app._dashboard_current_area() == "Player Area"


def test_current_area_label_uses_runtime_target_not_selected_map():
    app=WayFinderApp.__new__(WayFinderApp)
    app.snapshot=Snapshot(game="Game B")
    app.map_last_runtime_target="Player Area"
    app.map_selector_var=Mock(); app.map_selector_var.get.return_value="Browsed Area"
    app.map_current_area=Mock(); app.map_area_progress_detail=Mock(); app.map_area_progress_scale=Mock()
    app._current_map_status_counts=lambda: ({"reachable":0,"glitched":0,"out_of_logic":0,"checked":0,"ignored":0,"non_progression":0,"unknown":0},0)
    app._draw_current_area_progress=Mock()
    app._refresh_current_area_progress()
    app.map_current_area.set.assert_called_once_with("Current area: Player Area")
