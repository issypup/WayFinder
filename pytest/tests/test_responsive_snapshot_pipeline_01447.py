"""Provide test responsive snapshot pipeline 01447 support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = combined_app_source()


def test_snapshot_persistence_has_dedicated_worker():
    """Handle test snapshot persistence has dedicated worker."""
    assert "WayFinder-Snapshot-Persist" in APP
    assert "_snapshot_persist_queue = queue.Queue(maxsize=1)" in APP
    assert "def _snapshot_persist_worker_loop" in APP


def test_persist_snapshot_only_queues_from_gui_thread():
    """Handle test persist snapshot only queues from gui thread."""
    start = APP.index("    def _persist_snapshot(self, snap: Snapshot) -> None:")
    end = APP.index("    def _snapshot_persist_worker_loop", start)
    body = APP[start:end]
    assert "put_nowait(snap)" in body
    assert "_atomic_write_json" not in body


def test_snapshot_ui_refresh_is_cooperatively_batched():
    """Handle test snapshot ui refresh is cooperatively batched."""
    assert "def _schedule_snapshot_ui_refresh" in APP
    assert "self.root.after(0, run_batch)" in APP
    assert "self.root.after(1, run_batch, index + 1)" in APP
    assert "self._schedule_snapshot_ui_refresh()" in APP
