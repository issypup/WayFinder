"""Provide test appearance settings atomic write 01473 support."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_appearance_module_defines_atomic_settings_writer():
    """Handle test appearance module defines atomic settings writer."""
    source = (ROOT / "wayfinder/app/ui/appearance.py").read_text(encoding="utf-8")
    assert "def _atomic_write_json(" in source
    assert "_atomic_write_json(SETTINGS_PATH, data, backup=True)" in source


def test_appearance_atomic_writer_round_trip(tmp_path):
    """Handle test appearance atomic writer round trip."""
    from wayfinder.app.ui.appearance import _atomic_write_json
    import json

    target = tmp_path / "settings.json"
    _atomic_write_json(target, {"advanced": True}, backup=True)
    assert json.loads(target.read_text(encoding="utf-8")) == {"advanced": True}
