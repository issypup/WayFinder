"""Provide test logic engine tab removed 01423 support."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELL = (ROOT / 'wayfinder' / 'app' / 'ui' / 'shell.py').read_text(encoding='utf-8')

def test_logic_engine_not_in_navigation():
    """Handle test logic engine not in navigation."""
    nav_loop = SHELL[SHELL.index('for name in ['):SHELL.index('for name in [') + 500]
    assert '"Logic Engine"' not in nav_loop

def test_old_logic_engine_active_tab_falls_back_to_dashboard():
    """Handle test old logic engine active tab falls back to dashboard."""
    assert 'if remembered_tab == "Logic Engine":' in SHELL
    assert 'remembered_tab = "Dashboard"' in SHELL
