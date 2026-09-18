"""Provide test setup aware startup support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_entrypoint_does_not_start_runtime_before_gui_setup():
    """Handle test entrypoint does not start runtime before gui setup."""
    source = (ROOT / "run_wayfinder.py").read_text(encoding="utf-8")
    main = source[source.index("def main"): ]
    assert "if core_ready():" not in main
    assert "run_gui()" in main

def test_setup_states_are_excluded_from_watchdog():
    """Handle test setup states are excluded from watchdog."""
    source = combined_app_source()
    assert 'self.startup_stage = "setup_check"' in source
    assert '{"setup_check", "setup_required", "setup_ready"}' in source
    assert "Native runtime startup deferred until required setup is complete." in source

def test_connect_starts_runtime_after_readiness_check():
    """Handle test connect starts runtime after readiness check."""
    source = combined_app_source()
    assert 'if not self._ensure_local_runtime_started():' in source
    assert 'self._startup_enter("waiting_runtime")' in source

def test_runtime_transport_is_strictly_lazy_until_connect():
    """Handle test runtime transport is strictly lazy until connect."""
    runtime_source = (ROOT / "wayfinder" / "connection" / "runtime_client.py").read_text(encoding="utf-8")
    init_block = runtime_source[runtime_source.index("    def __init__(self, snapshot_sink"):runtime_source.index("    # /**\n    #  * Function: installation_info")]
    assert "self._start_transport_retry()" not in init_block
    assert '"Idle until Connect is requested"' in runtime_source

    app_source = combined_app_source()
    assert 'self.runtime_client_transport_state = "idle"' in app_source
    assert 'self._runtime_state_name = "OFFLINE"' in app_source
    assert 'elif self.runtime_client_transport_state=="idle": ut_text="Not started"' in app_source
