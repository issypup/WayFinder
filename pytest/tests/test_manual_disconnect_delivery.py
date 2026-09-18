"""Provide test manual disconnect delivery support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_disconnect_is_queued_if_runtime_ipc_is_temporarily_unavailable():
    """Handle test disconnect is queued if runtime ipc is temporarily unavailable."""
    source = (PROJECT_ROOT / "wayfinder/connection/runtime_client.py").read_text(encoding="utf-8")
    block = source.split("def disconnect(self) -> bool:", 1)[1].split("def refresh_state", 1)[0]
    assert "if self._send(payload):" in block
    assert 'payload.get("cmd") != "disconnect"' in block or 'item.get("cmd") != "disconnect"' in block
    assert "self._queue_startup_command(payload)" in block
    assert "self._start_transport_retry()" in block


def test_new_connect_cancels_queued_emergency_disconnect():
    """Handle test new connect cancels queued emergency disconnect."""
    source = (PROJECT_ROOT / "wayfinder/connection/runtime_client.py").read_text(encoding="utf-8")
    block = source.split("def connect(self, server:", 1)[1].split("def disconnect", 1)[0]
    assert 'payload.get("cmd") != "disconnect"' in block


def test_both_gui_disconnect_paths_set_manual_disconnect_latch():
    """Handle test both gui disconnect paths set manual disconnect latch."""
    source = combined_app_source()
    primary = source.split("def _connect_disconnect_clicked(self):", 1)[1].split("def _build_topbar", 1)[0]
    secondary = source.split("def disconnect_clicked(self):", 1)[1].split("def refresh_state_clicked", 1)[0]
    assert "self._manual_disconnect_pending = True" in primary
    assert "self._manual_disconnect_pending = True" in secondary
    assert "button_requests_disconnect" in primary
