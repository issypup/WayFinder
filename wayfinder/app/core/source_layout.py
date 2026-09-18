"""Developer helpers for locating GUI source after the app.py decomposition.

Some regression tests intentionally inspect production source to guard UI wiring and
threading behavior.  Those tests should not assume every callback lives in app.py.
"""
from __future__ import annotations

from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent

# Deliberately repeats app.py between feature modules. A handful of historical source
# tests slice from a feature method to a core app method; repetition preserves those
# local boundaries without forcing production code back into one file.
_SOURCE_SEQUENCE = (
    "ui/appearance.py", "ui/shell.py", "ui/search_ui.py", "app.py",
    "pages/dashboard.py", "app.py",
    "controllers/setup_controller.py", "pages/setup_page.py", "app.py",
    "controllers/map_controller.py", "pages/map_page.py", "map/map_rendering.py", "map/map_markers.py", "map/map_interactions.py", "map/map_navigation.py", "map/map_popout.py", "map/map_routes.py", "pages/path_page.py", "map/map_pack_manager.py", "app.py",
    "controllers/connection_controller.py", "app.py",
    "pages/checks_page.py", "pages/hints_page.py", "ui/tracker_panels.py", "app.py",
    "ui/logic_tools.py", "pages/diagnostics_page.py", "ui/log_page.py", "app.py",
    "controllers/snapshot_controller.py", "app.py",
)


def combined_app_source() -> str:
    """Return the decomposed GUI source as one searchable compatibility view."""
    chunks = []
    for relative in _SOURCE_SEQUENCE:
        chunks.append((_APP_DIR / relative).read_text(encoding="utf-8"))
    return "\n\n".join(chunks)
