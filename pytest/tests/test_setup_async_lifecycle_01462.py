"""Provide test setup async lifecycle 01462 support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path
import inspect


def test_setup_io_uses_common_background_task_worker():
    """Handle test setup io uses common background task worker."""
    source = combined_app_source()
    assert "def _start_setup_task" in source
    assert 'self._start_setup_task("Archipelago core import"' in source
    assert 'self._start_setup_task("GitHub version check"' in source
    assert 'self._start_setup_task("APWorld sync"' in source
    assert 'self._start_setup_task("Player YAML sync"' in source


def test_connect_does_not_sync_apworlds_on_tk_thread():
    """Handle test connect does not sync apworlds on tk thread."""
    from wayfinder.app.app import WayFinderApp
    block = inspect.getsource(WayFinderApp._ensure_local_runtime_started)
    assert "sync_custom_worlds" not in block
    assert "_start_setup_task" in block


def test_dependency_readiness_is_core_scoped():
    """Handle test dependency readiness is core scoped."""
    from wayfinder.app.app import WayFinderApp
    block = inspect.getsource(WayFinderApp._setup_readiness)
    assert "core_failed" in block
    assert "world_failed" in block
    assert "deps_ok=bool(dependency_scan_present and not core_failed)" in block
    assert "dependency_affected_worlds" in block


def test_world_preparation_is_structured_lifecycle():
    """Handle test world preparation is structured lifecycle."""
    from wayfinder.runtime.native_reliability import NativeReliability
    helper = inspect.getsource(NativeReliability.world_preparation)
    assert "phase" in helper and "step" in helper and "total" in helper
    assert "message" in helper and "state" in helper
    assert "elapsed" in helper and "timings" in helper
    rebuild = inspect.getsource(NativeReliability.rebuild_world)
    assert "'apworld',4,10" in rebuild
    assert "'dependencies',5,10" in rebuild
    assert "'reconstructing',6,10" in rebuild
    snapshot = inspect.getsource(NativeReliability.queue_snapshot)
    assert "'logic',7,10" in snapshot
    assert "'initial_state',8,10" in snapshot


def test_no_duplicate_refresh_setup_return():
    """Handle test no duplicate refresh setup return."""
    from wayfinder.app.app import WayFinderApp
    block = inspect.getsource(WayFinderApp._refresh_setup_status)
    assert block.count("return status") == 1
