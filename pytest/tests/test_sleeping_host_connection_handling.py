"""Provide test sleeping host connection handling support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_filters_expected_connection_refusal_traceback():
    """Handle test runtime filters expected connection refusal traceback."""
    source = (ROOT / "wayfinder" / "runtime" / "server.py").read_text(encoding="utf-8")
    assert "_ArchipelagoConnectionRefusedFilter" in source
    assert "record.exc_info = None" in source
    assert "WayFinder will keep retrying automatically" in source


def test_dashboard_exposes_waiting_for_sleeping_server_state():
    """Handle test dashboard exposes waiting for sleeping server state."""
    source = combined_app_source()
    assert 'name=="ap_connection_state"' in source
    assert "Waiting for Archipelago server — automatic retry active" in source
    assert "_ap_connection_message" in source


def test_runtime_filters_ap_ws_to_wss_probe_ssl_traceback():
    """Handle test runtime filters ap ws to wss probe ssl traceback."""
    source = (ROOT / "wayfinder" / "runtime" / "server.py").read_text(encoding="utf-8")
    assert "WRONG_VERSION_NUMBER" in source
    assert "encrypted fallback" in source


def test_connection_watchdog_wording_is_nonfatal():
    """Handle test connection watchdog wording is nonfatal."""
    source = combined_app_source()
    assert "Archipelago connection still pending after" in source
    assert "The native runtime is ready and will continue retrying" in source
