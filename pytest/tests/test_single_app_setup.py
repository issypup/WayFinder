"""Provide test single app setup support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
APP=ROOT/"wayfinder"/"app"/"app.py"
ENTRYPOINT=ROOT/"run_wayfinder.py"
RUN=ROOT/"run_wayfinder.py"

def test_setup_tab_contains_guided_wizard_and_advanced_maintenance():
    """Handle test setup tab contains guided wizard and advanced maintenance."""
    source=combined_app_source()
    assert '"WayFinder Setup": ("WayFinder Setup", "setup")' in source
    wizard=source[source.index("def _render_setup_progress(self,"):source.index("def _build_diagnostics",source.index("def _render_setup_progress(self,"))]
    for label in (
        "WELCOME TO WAYFINDER",
        "ARCHIPELAGO SOURCE",
        "GAME WORLDS",
        "WORLD DEPENDENCIES",
        "PLAYER YAMLS",
        "MAP PACKS",
        "WAYFINDER SELF-TEST",
        "Finish Setup",
        "SETUP & MAINTENANCE",
        "Run Setup Wizard Again",
        "ADVANCED SETUP",
    ):
        assert label in wizard
    assert '("Storage", "Core", "Worlds", "Deps", "YAMLs", "Maps", "Ready")' in wizard

def test_dashboard_has_clear_saved_server_slot_action():
    """Handle test dashboard has clear saved server slot action."""
    source=combined_app_source()
    block=source[source.index("def _build_dashboard(self):"):source.index("def _build_search",source.index("def _build_dashboard(self):"))]
    assert 'Clear Saved Data for Server + Slot' in block
    assert 'command=self._clear_saved_connection_data' in block

def test_connect_preflight_hard_blocks_setup_but_yaml_is_warning_only():
    """Handle test connect preflight hard blocks setup but yaml is warning only."""
    source=(ROOT/"wayfinder"/"app"/"controllers"/"connection_controller.py").read_text(encoding="utf-8")
    start=source.index("def _connect_disconnect_clicked(self):")
    next_def=source.find("\n    def ", start + 10)
    block=source[start:next_def if next_def != -1 else len(source)]
    assert 'missing.append("Archipelago Core")' in block
    assert 'missing.append("World Catalogue")' in block
    assert 'missing.append("World Dependencies")' in block
    assert 'if not readiness["yaml_match"]:' in block
    assert "may be able to reconstruct exact logic from slot data alone" in block
    assert "Connect anyway?" in block

def test_default_boot_opens_wayfinder_directly():
    """Handle test default boot opens wayfinder directly."""
    source=ENTRYPOINT.read_text(encoding="utf-8")
    main=source[source.rindex("def main("):]
    assert "run_gui()" in main
    assert 'os.environ["WF_RUNTIME_PORT"]' in main
    assert "allocate_ipc_port()" in main

def test_entrypoint_describes_single_application():
    """Handle test entrypoint describes single application."""
    source=RUN.read_text(encoding="utf-8")
    assert "single-application entry point" in source
