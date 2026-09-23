"""Provide test user initiated connect persistence support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_startup_does_not_restore_persisted_tracker_snapshot():
    """Handle test startup does not restore persisted tracker snapshot."""
    source = (ROOT / "wayfinder" / "app" / "app.py").read_text(encoding="utf-8")
    init_start = source.index("    def __init__(self, initial_server")
    run_start = source.index("    def run", init_start)
    init_block = source[init_start:run_start]
    assert "self._restore_persisted_snapshot()" not in init_block
    assert "Previous tracker snapshot was not loaded" in init_block


def test_persisted_snapshot_helper_cannot_restore_live_connection_state_if_used_manually():
    """Handle test persisted snapshot helper cannot restore live connection state if used manually."""
    source = combined_app_source()
    start = source.index("def _restore_persisted_snapshot")
    end = source.index("def _persist_location_notes", start) if "def _persist_location_notes" in source[start:] else start + 8000
    block = source[start:end]
    assert "snap.connected=False" in block


def test_only_explicit_connect_wakes_initial_runtime_transport():
    """Handle test only explicit connect wakes initial runtime transport."""
    source = (ROOT / "wayfinder" / "connection" / "runtime_client.py").read_text(encoding="utf-8")
    start = source.index("    def _send(self, payload")
    end = source.index("    # /**", start + 20)
    block = source[start:end]
    assert 'not self._ever_connected and cmd == "connect"' in block
    assert 'cmd in {"connect", "console"}' not in block
    assert 'if not self._ever_connected:\n                    self._start_transport_retry()' not in block


def test_entrypoint_boot_version_matches_package_version():
    """Handle test entrypoint boot version matches package version."""
    package_version = (ROOT / "wayfinder" / "__init__.py").read_text(encoding="utf-8")
    entrypoint = (ROOT / "run_wayfinder.py").read_text(encoding="utf-8")
    import re
    version_source = (ROOT / "wayfinder" / "version.py").read_text(encoding="utf-8")
    version = re.search(r'WAYFINDER_VERSION = "([^"]+)"', version_source).group(1)
    assert 'from wayfinder.version import WAYFINDER_VERSION' in entrypoint
    assert 'APP_VERSION = WAYFINDER_VERSION' in entrypoint
