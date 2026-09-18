"""Provide test connection preparation 01457 support."""
import asyncio
import json
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from wayfinder.app.app import WayFinderApp
from wayfinder.connection.runtime_client import Snapshot
from wayfinder.runtime import apworld_catalog as catalog
from wayfinder.runtime import apworld_compatibility as compatibility
from wayfinder.runtime.native_reliability import NativeReliability
from wayfinder.runtime.server import NativeRuntime


def ui():
    """Handle ui."""
    app = object.__new__(WayFinderApp)
    app.snapshot = Snapshot()
    app._feature_status = Mock()
    app._update_live_panel = Mock()
    app._append_log = Mock()
    app.startup_stage = 'waiting_ap_connection'
    app.startup_completed = set()
    app.startup_timed_out = set()
    app.startup_stage_started_at = time.monotonic() - 31
    app.startup_timeout_seconds = {}
    app.root = Mock()
    return app


def test_authentication_completes_connection_stage_before_snapshot():
    """Handle test authentication completes connection stage before snapshot."""
    app = ui()
    app._apply_status('ap_connection_state', {'state': 'connected', 'message': ''})
    assert app.startup_stage == 'first_snapshot'
    assert 'waiting_ap_connection' in app.startup_completed
    assert not app.snapshot.connected  # No fabricated world data or seed identity.
    assert not app.snapshot.locations
    app._update_live_panel.assert_called()


def test_slow_reconstruction_is_not_connection_timeout():
    """Handle test slow reconstruction is not connection timeout."""
    app = ui()
    app._apply_status('ap_connection_state', {'state': 'connected'})
    app._apply_status('world_preparation', 'Verifying core and dependency files')
    app.startup_stage_started_at -= 31
    app._startup_watchdog_tick()
    messages = ' '.join(call.args[0] for call in app._append_log.call_args_list)
    assert 'connection still pending' not in messages
    assert 'Archipelago is connected' in messages
    assert 'Verifying core' in messages


def test_late_connected_event_does_not_undo_manual_disconnect():
    """Handle test late connected event does not undo manual disconnect."""
    app = ui(); app._manual_disconnect_pending = True
    app._apply_status('ap_connection_state', {'state': 'connected'})
    assert app._ap_connection_state == 'disconnected'
    assert 'waiting_ap_connection' not in app.startup_completed


def world(root, name, game, version='1.0.0'):
    """Handle world."""
    folder = root / 'custom_worlds'; folder.mkdir(exist_ok=True)
    path = folder / (name + '.apworld')
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(name + '/__init__.py', 'raise RuntimeError("Never import during discovery")')
        archive.writestr('archipelago.json', json.dumps({'game': game, 'world_version': version}))
    return path


def test_selection_hashes_and_scans_dependencies_only_for_selected_game(tmp_path, monkeypatch):
    """Handle test selection hashes and scans dependencies only for selected game."""
    wanted = world(tmp_path, 'demo', 'Demo')
    world(tmp_path, 'unrelated', 'Another Game')
    hashes = []
    original = catalog.content_hash
    def hashed(path):
        """Handle hashed."""
        hashes.append(Path(path).name)
        return original(path)
    monkeypatch.setattr(catalog, 'content_hash', hashed)
    record = catalog.select_world('Demo', tmp_path)
    assert record.path == str(wanted.resolve())
    assert record.sha256
    assert hashes == ['demo.apworld']


def test_full_inventory_keeps_hashes_and_dependency_ownership(tmp_path):
    """Handle test full inventory keeps hashes and dependency ownership."""
    path = world(tmp_path, 'demo', 'Demo')
    with zipfile.ZipFile(path, 'a') as archive:
        archive.writestr('demo/requirements.txt', 'packaging>=20')
    record = catalog.discover(tmp_path)[0]
    assert record.sha256
    assert record.requirements[0]['owner'] == 'Demo'


def test_broken_duplicate_falls_back_to_valid_version(tmp_path):
    """Handle test broken duplicate falls back to valid version."""
    good = world(tmp_path, 'old', 'Demo')
    bad = world(tmp_path, 'new', 'Demo', '2.0.0')
    with zipfile.ZipFile(bad, 'a') as archive:
        archive.writestr('new/requirements.txt', '-r ../../outside.txt')
    assert catalog.select_world('Demo', tmp_path).path == str(good.resolve())


def test_fingerprint_prunes_excluded_directories_and_detects_changes(tmp_path, monkeypatch):
    """Handle test fingerprint prunes excluded directories and detects changes."""
    (tmp_path / 'keep.py').write_text('first')
    (tmp_path / 'custom_worlds').mkdir()
    (tmp_path / 'custom_worlds' / 'ignored.py').write_text('ignore')
    visited = []
    original = compatibility.os.walk
    def walked(*args, **kwargs):
        """Handle walked."""
        for row in original(*args, **kwargs):
            visited.append(Path(row[0]).name)
            yield row
    monkeypatch.setattr(compatibility.os, 'walk', walked)
    first = compatibility.tree_fingerprint(tmp_path, ('custom_worlds',))
    assert 'custom_worlds' not in visited
    (tmp_path / 'keep.py').write_text('second')
    assert compatibility.tree_fingerprint(tmp_path, ('custom_worlds',)) != first


def test_reconstruction_key_reuses_verified_environment_without_rescanning(monkeypatch):
    """Handle test reconstruction key reuses verified environment without rescanning."""
    monkeypatch.setattr(compatibility, 'tree_fingerprint', Mock(side_effect=AssertionError('rescanned')))
    record = SimpleNamespace(sha256='world')
    first = compatibility.reconstruction_key(record, '.', '.', {'slot': 1}, environment={'core': 'a', 'dependencies': 'd'})
    assert first != compatibility.reconstruction_key(record, '.', '.', {'slot': 2}, environment={'core': 'a', 'dependencies': 'd'})
    assert first != compatibility.reconstruction_key(record, '.', '.', {'slot': 1}, environment={'core': 'b', 'dependencies': 'd'})


def test_old_world_subscription_callback_is_discarded():
    """Handle test old world subscription callback is discarded."""
    runtime = object.__new__(NativeReliability)
    runtime.connection_id = 'new'; runtime.built = object()
    runtime._subscribe_map_page_if_available = Mock()
    runtime._subscribe_player_position_if_available = Mock()
    runtime.queue_snapshot = Mock()
    runtime._finish_world_subscriptions('old', runtime.built)
    runtime._finish_world_subscriptions('new', object())
    runtime._subscribe_map_page_if_available.assert_not_called()
    runtime.queue_snapshot.assert_not_called()


def test_reconstruction_schedules_subscriptions_on_ap_event_loop(monkeypatch):
    """Handle test reconstruction schedules subscriptions on ap event loop."""
    async def scenario():
        """Handle scenario."""
        runtime = NativeRuntime(0, '.')
        runtime.loop = asyncio.get_running_loop()
        runtime.ctx = SimpleNamespace(game='Demo', auth='Player', slot=1, team=0, server_address='fixture')
        runtime.slot_data = {}
        runtime.send = Mock()
        monkeypatch.setattr('wayfinder.runtime.apworld_catalog.select_world', lambda *a: SimpleNamespace(path='demo', game='Demo', sha256='hash', manifest={}))
        monkeypatch.setattr('wayfinder.runtime.apworld_compatibility.require_dependencies', lambda *a: [])
        monkeypatch.setattr('wayfinder.runtime.apworld_compatibility.environment_identity', lambda *a: {})
        monkeypatch.setattr('wayfinder.runtime.apworld_compatibility.reconstruction_key', lambda *a, **kw: 'key')
        monkeypatch.setattr('wayfinder.runtime.apworld_compatibility.save_report', lambda *a: None)
        monkeypatch.setattr('wayfinder.runtime.world_loader.ensure_game_loaded', lambda *a, **kw: SimpleNamespace(game='Demo'))
        builder_threads = []
        def build(*args, **kwargs):
            """Handle build."""
            builder_threads.append(threading.get_ident())
            return SimpleNamespace(world=SimpleNamespace(), warnings=[], exact_logic=True)
        monkeypatch.setattr('wayfinder.runtime.world_builder.build_world', build)
        done = asyncio.Event(); called = []
        def subscribe():
            """Handle subscribe."""
            assert asyncio.get_running_loop() is runtime.loop
            called.append(threading.get_ident())
        runtime._subscribe_map_page_if_available = subscribe
        runtime._subscribe_player_position_if_available = subscribe
        runtime.queue_snapshot = done.set
        try:
            runtime.rebuild_world()
            await asyncio.wait_for(done.wait(), 5)
            assert called == [threading.get_ident()] * 2
            assert builder_threads[0] != threading.get_ident()
        finally:
            runtime.jobs.close()
    asyncio.run(scenario())
