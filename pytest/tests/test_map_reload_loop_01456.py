"""Render lifecycle regressions: refreshes must not restart the same image."""
import queue
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from wayfinder.app.app import WayFinderApp
from wayfinder.maps.assets import asset_key


def app_fixture(tmp_path):
    """Handle app fixture."""
    Image.new('RGB', (40, 30), 'red').save(tmp_path / 'map.png')
    pack = SimpleNamespace(source=tmp_path)
    md = SimpleNamespace(title='Okun Shrine', image='map.png')
    app = object.__new__(WayFinderApp)
    app._closing = False
    app.root = Mock()
    app.current_page = 'Map'
    app.active_map_pack = pack
    app._current_map_def = lambda: md
    app.map_canvas = Mock()
    app.map_canvas.xview.return_value = (0.0, 1.0)
    app.map_canvas.yview.return_value = (0.0, 1.0)
    app.map_zoom = Mock(); app.map_zoom.get.return_value = 50
    app.map_status = Mock()
    app.map_render_progress = Mock()
    app._map_popout_render_progress = None
    app._map_zoom_after_id = None
    app.map_render_generation = 0
    app.map_rendering_key = None
    app.map_background_key = None
    app.map_photo = None
    app.map_photo_cache = {}
    app._map_render_condition = threading.Condition()
    app._map_render_pending = None
    return app, pack, md


def test_completed_image_refresh_uses_same_versioned_key(tmp_path):
    """Handle test completed image refresh uses same versioned key."""
    app, pack, md = app_fixture(tmp_path)
    app.map_background_key = asset_key(pack, md.image, 50)
    app.map_photo = object()
    app._request_map_render = Mock()
    # Reaching marker processing proves that a ready image was recognized.
    app._ensure_map_marker_items = Mock(side_effect=RuntimeError('markers reached'))
    for _ in range(5):
        with pytest.raises(RuntimeError, match='markers reached'):
            app._refresh_map_markers()
    app._request_map_render.assert_not_called()


def test_refresh_does_not_interrupt_inflight_image(tmp_path):
    """Handle test refresh does not interrupt inflight image."""
    app, pack, md = app_fixture(tmp_path)
    app.map_rendering_key = asset_key(pack, md.image, 50)
    app._request_map_render = Mock()
    for _ in range(20): app._refresh_map_markers()
    app._request_map_render.assert_not_called()


def test_duplicate_requests_do_not_postpone_debounce(tmp_path):
    """Handle test duplicate requests do not postpone debounce."""
    app, _, _ = app_fixture(tmp_path)
    for _ in range(20): app._request_map_render()
    assert app.map_render_generation == 1
    assert app.root.after.call_count == 1
    app.root.after_cancel.assert_not_called()


def test_duplicate_requests_preserve_running_generation(tmp_path):
    """Handle test duplicate requests preserve running generation."""
    app, pack, md = app_fixture(tmp_path)
    app._render_map()
    generation = app.map_render_generation
    pending = app._map_render_pending
    for _ in range(20):
        app._request_map_render()
        app._render_map()
    assert app.map_render_generation == generation
    assert app._map_render_pending is pending
    assert app.map_rendering_key == asset_key(pack, md.image, 50)


def test_zoom_change_supersedes_old_image_and_rejects_old_completion(tmp_path):
    """Handle test zoom change supersedes old image and rejects old completion."""
    app, pack, md = app_fixture(tmp_path)
    app._render_map()
    old = app._map_render_pending
    app.map_zoom.get.return_value = 75
    app._request_map_render()
    app._run_requested_map_render(True)
    assert app.map_rendering_key == asset_key(pack, md.image, 75)
    app._apply_map_photo = Mock()
    app._finish_map_render(old[0], old[1], ('pil', None), 0, 0, True)
    app._apply_map_photo.assert_not_called()


def test_failure_stays_visible_until_explicit_retry(tmp_path):
    """Handle test failure stays visible until explicit retry."""
    app, _, _ = app_fixture(tmp_path)
    app._append_log = Mock()
    app._render_map()
    generation = app.map_render_generation
    app._map_render_failed(generation, ValueError('bad image'))
    assert 'Could not render' in app.map_status.set.call_args.args[0]
    for _ in range(10): app._refresh_map_markers()
    app.root.after.assert_not_called()
    app._request_map_render()
    assert app._map_failed_key is None
    assert app.root.after.call_count == 1


def test_changed_asset_requests_fresh_render(tmp_path):
    """Handle test changed asset requests fresh render."""
    app, pack, md = app_fixture(tmp_path)
    app.map_background_key = asset_key(pack, md.image, 50)
    app.map_photo = object()
    Image.new('RGB', (41, 31), 'blue').save(tmp_path / 'map.png')
    app._request_map_render = Mock()
    app._refresh_map_markers()
    app._request_map_render.assert_called_once()


def test_worker_delivers_image_without_interactive_disk_compression(tmp_path, monkeypatch):
    """Handle test worker delivers image without interactive disk compression."""
    from wayfinder.maps import packs
    app, pack, md = app_fixture(tmp_path)
    monkeypatch.setattr(packs, 'map_cache_root', lambda: tmp_path / 'cache')
    app.events = queue.Queue()
    app.map_scaled_cache = {}; app.map_source_cache = {}
    app._map_scaled_cache_lock = threading.Lock()
    app._map_source_cache_lock = threading.Lock()
    def no_interactive_save(*args, **kwargs):
        """Handle no interactive save."""
        raise AssertionError('PNG compression must not delay the next render')
    monkeypatch.setattr(Image.Image, 'save', no_interactive_save)
    app._render_map()
    worker = threading.Thread(target=app._map_render_worker_loop, daemon=True)
    worker.start()
    try:
        kind, payload = app.events.get(timeout=1)
        assert kind == 'map_render_done'
        assert payload[2][1].size == (20, 15)
    finally:
        with app._map_render_condition:
            app._closing = True
            app._map_render_condition.notify_all()
        worker.join(10)
    assert not worker.is_alive()
