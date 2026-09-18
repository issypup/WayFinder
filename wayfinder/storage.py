"""Central WayFinder application-data storage configuration.

The active data root is chosen before the GUI imports most subsystems.  A tiny
bootstrap settings file lives outside the configurable data root so WayFinder
can always discover the user's selected location on the next launch.
"""

# sig:kuro:pluralchat

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

BOOTSTRAP_SETTINGS_PATH = Path.home() / ".wayfinder.app.json"
STORAGE_KEY = "app_data_root"


def default_app_data_root() -> Path:
    """Return WayFinder's platform-default per-user data directory."""
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "WayFinder"
    return Path.home() / ".wayfinder"


def load_bootstrap_settings() -> dict:
    """Return load bootstrap settings."""
    try:
        data = json.loads(BOOTSTRAP_SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}


def save_bootstrap_settings(data: dict) -> None:
    """Handle save bootstrap settings."""
    BOOTSTRAP_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = BOOTSTRAP_SETTINGS_PATH.with_suffix(BOOTSTRAP_SETTINGS_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, BOOTSTRAP_SETTINGS_PATH)


def configured_app_data_root() -> Path | None:
    """Return the configured custom root, or None when the default is selected."""
    raw = str(load_bootstrap_settings().get(STORAGE_KEY, "") or "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser()
    except (TypeError, ValueError, OSError):
        return None


def app_data_root() -> Path:
    """Return the effective data root for this process."""
    return configured_app_data_root() or default_app_data_root()


def validate_app_data_root(path: Path) -> tuple[bool, str]:
    """Check that *path* can be created and written without leaving test data behind."""
    try:
        candidate = Path(path).expanduser()
        candidate.mkdir(parents=True, exist_ok=True)
        if not candidate.is_dir():
            return False, "The selected path is not a directory."
        fd, probe_name = tempfile.mkstemp(prefix=".wayfinder-write-test-", dir=str(candidate))
        os.close(fd)
        Path(probe_name).unlink(missing_ok=True)
        return True, "Writable"
    except (OSError, ValueError) as exc:
        return False, str(exc)


def set_app_data_root(path: Path | None) -> Path:
    """Persist a custom root; pass None to return to the platform default.

    The change is intentionally applied on the next WayFinder launch.  Modules
    bind paths during startup, so switching them in-place could split one
    session across two storage roots.
    """
    settings = load_bootstrap_settings()
    if path is None:
        settings.pop(STORAGE_KEY, None)
        selected = default_app_data_root()
    else:
        selected = Path(path).expanduser()
        ok, reason = validate_app_data_root(selected)
        if not ok:
            raise OSError(reason)
        settings[STORAGE_KEY] = str(selected)
    save_bootstrap_settings(settings)
    return selected


APP_DATA_ROOT = app_data_root()
