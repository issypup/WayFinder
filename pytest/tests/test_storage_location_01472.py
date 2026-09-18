"""Provide test storage location 01472 support."""
from pathlib import Path

import wayfinder.storage as storage


def test_default_storage_has_wayfinder_directory_name():
    """Handle test default storage has wayfinder directory name."""
    assert storage.default_app_data_root().name.casefold() in {"wayfinder", ".wayfinder"}


def test_custom_storage_round_trip(monkeypatch, tmp_path):
    """Handle test custom storage round trip."""
    bootstrap = tmp_path / "bootstrap.json"
    monkeypatch.setattr(storage, "BOOTSTRAP_SETTINGS_PATH", bootstrap)
    custom = tmp_path / "custom-wayfinder-data"
    saved = storage.set_app_data_root(custom)
    assert saved == custom
    assert storage.configured_app_data_root() == custom
    assert custom.is_dir()


def test_return_to_default_removes_override(monkeypatch, tmp_path):
    """Handle test return to default removes override."""
    bootstrap = tmp_path / "bootstrap.json"
    monkeypatch.setattr(storage, "BOOTSTRAP_SETTINGS_PATH", bootstrap)
    storage.set_app_data_root(tmp_path / "custom")
    storage.set_app_data_root(None)
    assert storage.configured_app_data_root() is None
