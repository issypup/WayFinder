"""Provide test dashboard context ui 01465 support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

from wayfinder.app.app import RunContext

ROOT = Path(__file__).resolve().parents[2]
APP = combined_app_source()
RUNTIME = (ROOT / 'wayfinder' / 'runtime' / 'native_reliability.py').read_text(encoding='utf-8')


def test_run_context_identity_is_one_authority_boundary():
    """Handle test run context identity is one authority boundary."""
    ctx = RunContext(server='Example.org:38281', team=2, slot='Issy', game='Slime Rancher', seed='abc')
    assert ctx.identity == ('example.org:38281', 2, 'issy', 'slime rancher')
    assert ctx.current_area == ''
    assert ctx.route is None


def test_dashboard_has_single_run_lifecycle_rows():
    """Handle test dashboard has single run lifecycle rows."""
    for label in (
        'CONNECTED TO ARCHIPELAGO', 'GAME IDENTIFIED', 'APWORLD LOADED',
        'SEED RECONSTRUCTED', 'LOGIC EVALUATED', 'MAP READY', 'TRACKING'
    ):
        assert label in APP
    for marker in ('✓', '⟳', '!', '✕', '○'):
        assert marker in APP


def test_compatibility_surfaces_apworld_provenance_and_missing_reason():
    """Handle test compatibility surfaces apworld provenance and missing reason."""
    assert 'WHY ISN\'T THIS FULL COMPATIBILITY?' in APP
    for token in ('apworld_path', 'apworld_version', 'identification', 'dependency_count'):
        assert token in APP
        assert token in RUNTIME
    assert 'Compatibility {compatibility_level}' in APP


def test_diagnostics_exposes_phase_and_map_timings():
    """Handle test diagnostics exposes phase and map timings."""
    for label in (
        'RUNTIME STARTUP', 'AP AUTHENTICATION', 'APWORLD DISCOVERY', 'DEPENDENCY CHECK',
        'WORLD RECONSTRUCTION', 'LOGIC EVALUATION', 'SNAPSHOT BUILD', 'MAP IMAGE LOAD', 'MARKER UPDATE'
    ):
        assert label in APP
    assert '_last_map_render_seconds' in APP
    assert '_last_marker_update_seconds' in APP


def test_checks_summary_is_filter_scoped_and_map_has_status_strip():
    """Handle test checks summary is filter scoped and map has status strip."""
    assert 'filtered_status=[row[5] for row in rows]' in APP
    assert 'of {total} locations' in APP
    assert 'map_load_strip' in APP
    assert 'preparing {len(getattr(pack,\'markers\',[]) or [])} markers' in APP
