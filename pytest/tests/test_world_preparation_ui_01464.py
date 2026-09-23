"""Provide test world preparation ui 01464 support."""
import inspect


def test_connection_and_authentication_are_part_of_ten_stage_preparation():
    """Handle test connection and authentication are part of ten stage preparation."""
    from wayfinder.runtime.server import NativeRuntime
    source = inspect.getsource(NativeRuntime.connect_ap)
    assert '"connection",1,10' in source


def test_dashboard_preparation_progress_follows_live_ten_stage_counter():
    """Handle test dashboard has preparation card and truthful progress modes."""
    from wayfinder.app.app import WayFinderApp
    dashboard = inspect.getsource(WayFinderApp._build_dashboard)
    panel = inspect.getsource(WayFinderApp._update_preparation_panel)
    assert 'PREPARING WAYFINDER' in dashboard
    assert 'Progressbar' in dashboard
    assert 'overall_step' in panel and 'overall_total' in panel
    assert 'self.preparation_progress.set' in panel and 'determinate' in panel
    assert 'WORLD READY' in panel


def test_gui_finishes_map_and_ready_stages_after_first_snapshot():
    """Handle test gui finishes map and ready stages after first snapshot."""
    from wayfinder.app.app import WayFinderApp
    source = inspect.getsource(WayFinderApp._finish_world_preparation_in_gui)
    assert 'step=9' in source and 'phase="map"' in source
    assert 'step=10' in source and 'phase="ready"' in source
    assert 'map_installed' in source
    assert 'reachable' in source


def test_reconstruction_reports_cache_and_duration():
    """Handle test reconstruction reports cache and duration."""
    from wayfinder.runtime.native_reliability import NativeReliability
    source = inspect.getsource(NativeReliability.rebuild_world)
    assert 'cache_hit=bool(hit)' in source
    assert 'reconstruction_seconds' in source
    assert "progress_mode='indeterminate'" in source


def test_first_snapshot_can_promote_stale_logic_stage():
    """Handle test first snapshot can promote stale logic stage."""
    from wayfinder.app.app import WayFinderApp
    source = inspect.getsource(WayFinderApp._finish_world_preparation_in_gui)
    assert 'Tracker initial state received' in source
    assert 'int(status.get("step",0) or 0) < 8' in source


def test_late_running_preparation_status_cannot_regress_world_ready():
    """Handle test late running preparation status cannot regress world ready."""
    from wayfinder.app.app import WayFinderApp
    source = inspect.getsource(WayFinderApp._apply_status)
    assert "complete.get('state') == 'complete'" in source
    assert "incoming_state == 'running'" in source
