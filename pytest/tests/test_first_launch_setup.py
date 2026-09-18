"""Provide test first launch setup support."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = (ROOT / "wayfinder" / "app" / "app.py").read_text(encoding="utf-8")
SHELL = (ROOT / "wayfinder" / "app" / "ui" / "shell.py").read_text(encoding="utf-8")
APPEARANCE = (ROOT / "wayfinder" / "app" / "ui" / "appearance.py").read_text(encoding="utf-8")

def test_first_launch_opens_wayfinder_setup():
    """Handle test first launch opens wayfinder setup."""
    assert 'self._first_setup_launch = not bool(self.settings.get("wayfinder.setup_intro_seen", False))' in APP
    assert 'if self._first_setup_launch:' in SHELL
    assert 'self.show_page("WayFinder Setup")' in SHELL
    assert 'self.settings["wayfinder.setup_intro_seen"] = True' in SHELL

def test_subsequent_launches_restore_last_active_tab():
    """Handle test subsequent launches restore last active tab."""
    assert 'remembered_tab=self.settings.get("active_tab","Dashboard")' in SHELL
    assert 'self.show_page(remembered_tab if remembered_tab in self.pages else "Dashboard")' in SHELL
    assert '"wayfinder.setup_intro_seen": True' in APPEARANCE
