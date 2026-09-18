# /**
#  * Module: wayfinder/app/app.py
#  * Purpose: GUI module for app; presents or coordinates WayFinder state without owning the underlying game logic.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

"""Tkinter front end for the WayFinder native tracker interface.

The GUI is intentionally presentation-only: tracker/network work happens in the
runtime transport layer and is delivered here as immutable-style snapshots and status events.
Thread-originated messages are placed onto a queue and applied on Tk's main thread
so widgets are never mutated from the runtime reader thread.
"""

from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored
from wayfinder.utils.error_handler import ErrorHandler

import base64
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import time
import threading
import tempfile
import io
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from typing import Any
from difflib import SequenceMatcher
from datetime import datetime
from dataclasses import asdict, dataclass, field

try:
    from PIL import Image, ImageTk
    # Tracker map artwork can legitimately be extremely large. WayFinder
    # intentionally permits these trusted local pack images.
    Image.MAX_IMAGE_PIXELS = None
except Exception:
    # Variable(s): `Image` (Image), `ImageTk` (ImageTk); named state retained for the surrounding calculation or subsequent calls.
    Image = ImageTk = None

from wayfinder.connection.runtime_client import Snapshot, InventoryEntry, LocationEntry, PathResult, RuleNode, WayFinderRuntimeClient
from wayfinder.connection.memory import get_record, clear_server_slot, normalize_server
from wayfinder.maps.packs import discover_packs, best_pack, load_pack_variant, default_pack_dir, portable_pack_dir, install_pack_archive, related_archive_for_folder, game_pack_dir, TRACKER_PACK_API_VERSION, ZOOM_CACHE_LEVELS, cached_map_path, build_pack_zoom_cache, remove_pack_zoom_cache, validate_pack_archive, validate_pack_folder, install_validated_pack, enforce_map_cache_limit, persist_zoom_image_async
from wayfinder.maps.assets import LARGE_MAP_PIXELS, open_pack_image, remember_image, cached_image, render_result, asset_key, TiledMapPhoto, draw_map_photo
from wayfinder.maps.converter import convert_poptracker_pack, convert_ut_pack, detect_map_pack_archive_format
from wayfinder.diagnostics import CATEGORIES, sanitize, register_secret, make_record, format_record
from wayfinder.app.ui.reliability_ui import ReliabilityUI
from wayfinder.maps.intelligence import check_evidence
from wayfinder.connection.identity import validate_snapshot
from wayfinder import __version__
from wayfinder.logic.progression_intelligence import detect_unlock_impact, waiting_analysis, route_score, build_progression_graph
from wayfinder.logic.solver_intelligence import normalized_kind, rank_or_branches, path_cycles, dead_route_reasons, provenance_rows, reconstruction_audit, searchable_entries, remote_dependency_lines, goal_target

# Setup services are provided by WayFinder's internal setup package.
import wayfinder.setup as setup_backend

# Constant(s): `GUI_VERSION`; shared configuration value(s) intentionally kept stable within this module.
GUI_VERSION = __version__
from wayfinder.storage import app_data_root
APP_DATA_ROOT = app_data_root()


from wayfinder.app.core.context import RunContext

# Constant(s): `SETTINGS_PATH`; shared configuration value(s) intentionally kept stable within this module.
SETTINGS_PATH = APP_DATA_ROOT / "settings.json"
# Constant(s): `STATE_PATH`; shared configuration value(s) intentionally kept stable within this module.
STATE_PATH = APP_DATA_ROOT / "last_snapshot.json"

# Constant(s): `STATUS_VISUALS`; shared configuration value(s) intentionally kept stable within this module.
STATUS_VISUALS = {
    "reachable": {"label": "Reachable", "symbol": "●", "color": "#2f9e6f"},
    "glitched": {"label": "Glitch-only", "symbol": "⚡", "color": "#9b4fc4"},
    "out_of_logic": {"label": "Out of logic", "symbol": "◆", "color": "#d05b5b"},
    "checked": {"label": "Checked", "symbol": "✓", "color": "#7f8a91"},
    "ignored": {"label": "Ignored", "symbol": "—", "color": "#8c9499"},
    "non_progression": {"label": "Non-progression / untracked", "symbol": "○", "color": "#9a8f72"},
    "unknown": {"label": "Unknown", "symbol": "?", "color": "#71869a"},
}

# /**
#  * Function: _atomic_write_json
#  * Purpose: Perform the atomic write json operation while keeping the surrounding subsystem state consistent.
#  * @param path: Path supplied by the caller; see type hints and call sites for domain constraints.
#  * @param data: Data supplied by the caller; see type hints and call sites for domain constraints.
#  * @param backup: Backup supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _atomic_write_json(path: Path, data: Any, *, backup: bool = True) -> None:
    """Write JSON by fsync+replace so power loss/cancellation cannot leave a half file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Variable(s): `tmp` (temporary value); named state retained for the surrounding calculation or subsequent calls.
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}-{threading.get_ident()}")
    if backup and path.exists():
        try:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        except OSError:
            _ignored("intentional best-effort fallback")
    try:
        # Variable(s): `fh` (file handle); named state retained for the surrounding calculation or subsequent calls.
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try: tmp.unlink(missing_ok=True)
        except OSError: _ignored("intentional best-effort fallback")


# ---------------------------------------------------------------------------
# Small reusable Tk helpers
# ---------------------------------------------------------------------------
# /**
#  * Class: ToolTip
#  * Purpose: Encapsulate the ToolTip responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
class ToolTip:
    """Encapsulate ToolTip behaviour and the state needed to support it."""
    # /**
    #  * Function: __init__
    #  * Purpose: Initialize this object and establish its required runtime state.
    #  * @param widget: Widget supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param text: Text supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def __init__(self, widget: tk.Widget, text: str):
        """Initialize instance state and wire the collaborators/resources required by this component."""
        self.widget, self.text, self.tip = widget, text, None
        
        
    # /**
    #  * Function: _show
    #  * Purpose: Perform the show operation while keeping the surrounding subsystem state consistent.
    #  * @param _e: E supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _show(self, _e=None):
        """Show the  user-interface element."""
        if self.tip or not self.text: return
        self.tip = tk.Toplevel(self.widget); self.tip.wm_overrideredirect(True)
        # Variable(s): `x` (horizontal x-coordinate); named state retained for the surrounding calculation or subsequent calls.
        x = self.widget.winfo_rootx() + 16; y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg="#432633", fg="#edf3f8", padx=9, pady=6,
                 relief="solid", bd=1, justify="left", wraplength=340).pack()
    # /**
    #  * Function: _hide
    #  * Purpose: Perform the hide operation while keeping the surrounding subsystem state consistent.
    #  * @param _e: E supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _hide(self, _e=None):
        """Hide the  user-interface element."""
        if self.tip: self.tip.destroy(); self.tip = None


# ---------------------------------------------------------------------------
# Main WayFinder application
# ---------------------------------------------------------------------------
# /**
#  * Class: WayFinderApp
#  * Purpose: Encapsulate the WayFinderApp responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */

# Page/controller mixins keep WayFinderApp state ownership intact while separating
# UI construction, runtime orchestration, and feature-specific callbacks.
from wayfinder.app.ui.appearance import AppearanceMixin
from wayfinder.app.ui.shell import ShellMixin
from wayfinder.app.ui.search_ui import SearchUiMixin
from wayfinder.app.map.map_pack_manager import MapPackManagerMixin
from wayfinder.app.ui.log_page import LogPageMixin
from wayfinder.app.ui.tracker_panels import TrackerPanelsMixin
from wayfinder.app.ui.logic_tools import LogicToolsMixin
from wayfinder.app.pages.dashboard import DashboardPageMixin
from wayfinder.app.pages.setup_page import SetupPageMixin
from wayfinder.app.pages.map_page import MapPageMixin
from wayfinder.app.pages.checks_page import ChecksPageMixin
from wayfinder.app.pages.hints_page import HintsPageMixin
from wayfinder.app.pages.diagnostics_page import DiagnosticsPageMixin
from wayfinder.app.pages.path_page import PathPageMixin
from wayfinder.app.controllers.connection_controller import ConnectionControllerMixin
from wayfinder.app.controllers.map_controller import MapControllerMixin
from wayfinder.app.controllers.setup_controller import SetupControllerMixin
from wayfinder.app.controllers.snapshot_controller import SnapshotControllerMixin

class WayFinderApp(
    AppearanceMixin, ShellMixin, SearchUiMixin, MapPackManagerMixin, LogPageMixin, TrackerPanelsMixin, LogicToolsMixin,
    DashboardPageMixin, SetupControllerMixin, SetupPageMixin, MapControllerMixin, MapPageMixin, ChecksPageMixin,
    HintsPageMixin, DiagnosticsPageMixin, PathPageMixin,
    ConnectionControllerMixin, SnapshotControllerMixin, ReliabilityUI
):
    """Encapsulate WayFinderApp behaviour and the state needed to support it."""
    # /**
    #  * Function: __init__
    #  * Purpose: Initialize this object and establish its required runtime state.
    #  * @param initial_server: Initial server supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param initial_name: Initial name supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param initial_password: Initial password supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def __init__(self, initial_server="", initial_name="", initial_password=""):
        """Initialize instance state and wire the collaborators/resources required by this component."""
        self.settings = self._load_settings()
        self._gui_started_at=time.perf_counter()
        self._timing_runtime_start_seconds=None
        self._first_setup_launch = not bool(self.settings.get("wayfinder.setup_intro_seen", False))

        # Give Windows a stable application identity before creating the Tk root.
        # Without this, Windows can group the process under Python/Tk and show the
        # default Tk feather even when WayFinder.exe itself has the correct icon.
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "WayFinder.LogicAwareTracker.1.0"
                )
            except (AttributeError, OSError):
                pass

        self.root = tk.Tk(); ErrorHandler().set_root(self.root); self.root.title(f"WayFinder — Logic-Aware Tracker v{GUI_VERSION}")

        # The PyInstaller --icon option only controls the executable resource.
        # Tk needs its window icon configured separately for the title bar,
        # Alt+Tab and taskbar.  default=True also applies it to child Toplevels.
        try:
            bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
            icon_ico = bundle_root / "assets" / "wayfinder.ico"
            icon_png = bundle_root / "assets" / "wayfinder_icon_master.png"
            if sys.platform == "win32" and icon_ico.is_file():
                self.root.iconbitmap(default=str(icon_ico))
            if icon_png.is_file():
                self._wayfinder_window_icon = tk.PhotoImage(file=str(icon_png))
                self.root.iconphoto(True, self._wayfinder_window_icon)
        except (tk.TclError, OSError):
            # Icon setup must never prevent WayFinder from launching.
            self._wayfinder_window_icon = None

        self.root.geometry(self.settings.get("geometry", "1360x850")); self.root.minsize(1100, 720)
        # Command-line/entrypoint values win. Otherwise reuse the last successful
        # connection so the one-file EXE can reconnect without asking every run.
        self.initial_server = initial_server or str(self.settings.get("server", "") or "")
        self.initial_name = initial_name or str(self.settings.get("slot_name", "") or "")
        self.initial_password = initial_password if initial_password else str(self.settings.get("password", "") or "")
        self.snapshot = Snapshot(); self.previous_snapshot = Snapshot(); self.current_path: PathResult | None = None
        self.runtime_engine_version = "unknown"; self.runtime_ap_version = "unknown"; self.runtime_integration_version = GUI_VERSION; self.runtime_apworld_generated_by = "unknown"; self._last_start_location_diag = None
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue(); self.log_lines: list[str] = []
        self.recent_changes: list[tuple[str, str, str]] = []
        # name -> (accumulated positive delta, expiry monotonic time)
        self.inventory_deltas: dict[str, tuple[int, float]] = {}
        self.history: list[str] = []; self.history_index = -1
        self.recalculating = False
        self.logic_status = "idle"
        self.logic_status_message = ""
        self._active_refresh_id = 0
        self._latest_refresh_id = 0
        self._timed_out_refresh_id = 0
        self._refresh_timeout_after_id = None
        self._last_snapshot_sequence = -1
        self._snapshot_runtime_id = ""
        self._runtime_identity = None
        self.run_context = RunContext()
        self._state_is_stale = False
        self._state_stale_reason = ""
        self._state_origin = "none"
        self._last_logic_success_epoch = 0.0
        self._refresh_phase_name = "idle"
        self._runtime_state_name = "OFFLINE"
        self._runtime_transition_history = []
        self._data_package_signature = ""
        self._manual_disconnect_pending = False
        self._ap_connection_state = ""
        self._ap_connection_message = ""
        self._world_preparation_status = {}
        self._world_preparation_message = ""
        self._world_preparation_complete = {}
        self._world_preparation_facts = {}
        self._last_map_cache_detail = "Not loaded"
        self._map_performance_ms = {}
        self._active_path_request = 0
        self.map_packs = []; self.active_map_pack = None; self.map_photo = None; self.map_photo_cache = {}; self.map_source_cache = {}; self.map_background_key = None; self.map_zoom = tk.IntVar(value=int(self.settings.get("map_zoom", 50))); self.map_last_game = ""; self.map_last_runtime_target = None; self.map_drag_start = None; self.map_render_generation = 0; self.map_rendering_key = None; self.runtime_client_transport_state = "idle"; self.map_selection_memory = dict(self.settings.get("map_selection_memory", {}) or {})
        self.active_map_pack_choice = tk.StringVar(value=str(self.settings.get("active_map_pack_choice", "Auto") or "Auto"))
        self.map_variant_choice = tk.StringVar(value="Auto")
        self.map_variant_memory = dict(self.settings.get("map_variant_memory", {}) or {})
        self.map_pack_fingerprints = dict(self.settings.get("map_pack_fingerprints", {}) or {})
        self.requested_game = str(self.settings.get("game", "") or "")
        self.ignored_locations_by_scope = dict(self.settings.get("ignored_locations_by_scope", {}) or {})
        self._ignored_sync_scope = ""
        self._closing = False
        # Exactly one map-render worker owns all Pillow decode/resize work.
        # The pending slot is overwritten by newer requests, so rapid zooming
        # naturally skips obsolete intermediate renders.
        self._map_render_condition = threading.Condition()
        self._map_render_pending = None
        self._map_requested_key = None
        self._map_failed_key = None
        self._map_render_thread = threading.Thread(target=self._map_render_worker_loop, name="WayFinder-Map-Render", daemon=True)
        # Large live snapshots can contain hundreds or thousands of locations.
        # Serialising that state and fsyncing it to disk on Tk's event thread
        # made the window appear frozen immediately after Connect.  Persistence
        # is presentation-independent, so keep only the newest pending snapshot
        # and write it from a dedicated worker.
        self._snapshot_persist_queue = queue.Queue(maxsize=1)
        self._snapshot_persist_thread = threading.Thread(
            target=self._snapshot_persist_worker_loop,
            name="WayFinder-Snapshot-Persist",
            daemon=True,
        )
        # Snapshot widgets still have to be mutated on Tk's owning thread.
        # Rather than repainting every page in one enormous callback, refresh
        # them in small batches and invalidate older batches when a newer
        # snapshot arrives.  This keeps input, window painting and Disconnect
        # responsive while the first live state is being displayed.
        self._snapshot_ui_refresh_generation = 0
        self._snapshot_ui_refresh_after_id = None
        self._map_source_cache_lock = threading.Lock()
        self._map_scaled_cache_lock = threading.Lock()
        self.map_scaled_cache = {}
        self._map_install_thread = None
        self._map_install_progress = None
        self._map_install_progress_var = None
        self._map_install_status_var = None
        self._map_marker_items = {}
        self._map_marker_layout_key = None
        self._map_hint_phase = False
        self._map_hint_after_id = None
        self._map_marker_visual_state = {}
        self._map_last_statuses = {}
        self._map_canonical_marker_state = {}
        self._map_changed_locations = set()
        self.map_view_memory = dict(self.settings.get("map_view_memory", {}) or {})
        self.map_filter_memory = dict(self.settings.get("map_filter_memory", {}) or {})
        self._map_group_popup = None
        self._map_group_popup_names = []
        self._map_group_popup_listbox = None
        self._map_group_popup_count_var = None
        self._map_tooltip = None
        self._map_single_click_after_id = None
        self._map_single_click_marker = None
        self._map_ignore_next_release = False
        self._map_zoom_after_id = None
        self._map_search_after_id = None
        self._map_zoom_anchor = None
        # Pop-out map is a live second view of the same map state, not a PostScript snapshot.
        self._map_popout = None
        self._map_popout_canvas = None
        self._map_popout_photo = None
        self._map_popout_status = None
        self._map_popout_location_counter = None
        self._map_popout_progress_canvas = None
        self._map_popout_progress_detail = None
        self._map_popout_render_progress = None
        self.map_selected_location = ""
        self.map_status_visible = {
            "reachable": tk.BooleanVar(value=bool(self.settings.get("map_show_reachable", True))),
            "glitched": tk.BooleanVar(value=bool(self.settings.get("map_show_glitched", True))),
            "out_of_logic": tk.BooleanVar(value=bool(self.settings.get("map_show_out_of_logic", True))),
            "checked": tk.BooleanVar(value=bool(self.settings.get("map_show_checked", True))),
            "ignored": tk.BooleanVar(value=bool(self.settings.get("map_show_ignored", True))),
            "non_progression": tk.BooleanVar(value=bool(self.settings.get("map_show_non_progression", True))),
            "unknown": tk.BooleanVar(value=bool(self.settings.get("map_show_unknown", True))),
        }
        self.map_show_labels = tk.BooleanVar(value=bool(self.settings.get("map_show_labels", False)))
        self.map_show_tooltips = tk.BooleanVar(value=bool(self.settings.get("map_show_tooltips", True)))
        self.map_hide_checked_groups = tk.BooleanVar(value=bool(self.settings.get("map_hide_checked_groups", False)))
        self.map_show_minimap = tk.BooleanVar(value=bool(self.settings.get("map_show_minimap", True)))
        self._minimap_photo = None
        self._minimap_key = None
        self._stuck_recommendations = []
        self.last_unlock_impacts = []
        self.map_route_overlay = tk.BooleanVar(value=False)
        self.map_semantic_zoom = tk.BooleanVar(value=bool(self.settings.get("map_semantic_zoom", True)))
        self.route_strategy = tk.StringVar(value=str(self.settings.get("route_strategy", "Fastest route")))
        self.personal_route_region_weight = tk.DoubleVar(value=float(self.settings.get("personal_route_region_weight", 1.0)))
        self.personal_route_requirement_penalty = tk.DoubleVar(value=float(self.settings.get("personal_route_requirement_penalty", 0.5)))
        self.path_collapse_satisfied = tk.BooleanVar(value=bool(self.settings.get("path_collapse_satisfied", True)))
        self.path_search_var = tk.StringVar(value="")
        self.map_navigation_history = []
        self.map_navigation_index = -1
        self.logic_regression_records = []
        self._last_pack_validation_report = "No map-pack validation has run this session."
        self.map_highlight_search = tk.BooleanVar(value=bool(self.settings.get("map_highlight_search", True)))
        self.map_marker_size = tk.StringVar(value=str(self.settings.get("map_marker_size", "Medium")))
        self.theme = tk.StringVar(value="WayFinder Dark"); self.font_size = tk.IntVar(value=int(self.settings.get("font_size", 10)))
        self.check_mode = tk.StringVar(value=self.settings.get("check_mode", "All"))
        self.check_area = tk.StringVar(value=self.settings.get("check_area", "All areas"))
        self.check_unchecked_only = tk.BooleanVar(value=bool(self.settings.get("check_unchecked_only", False)))
        self.check_hinted_only = tk.BooleanVar(value=bool(self.settings.get("check_hinted_only", False)))
        self.check_progression_only = tk.BooleanVar(value=bool(self.settings.get("check_progression_only", False)))
        self.inventory_mode = tk.StringVar(value=self.settings.get("inventory_mode", "All"))
        self.install_ok, self.install_message, self.install_checks = WayFinderRuntimeClient.installation_info()
        self._managed_runtime_process = None
        # Dashboard run/status details remain intentionally blank until the user
        # explicitly requests a connection in this app session.  This avoids
        # presenting defaults, cached identity fields, or runtime diagnostics as
        # though a run already exists before Connect has been pressed.
        self._user_connect_requested = False
        self.setup_status_var = tk.StringVar(value="Setup status not checked yet")
        self.setup_core_var = tk.StringVar(value="Archipelago Core: checking…")
        self.setup_worlds_var = tk.StringVar(value="Game Worlds: checking…")
        self.setup_dependencies_var = tk.StringVar(value="World Dependencies: checking…")
        self.setup_yamls_var = tk.StringVar(value="Player YAMLs: checking…")
        self.setup_maps_var = tk.StringVar(value="Map Packs: checking…")
        self.setup_wizard_stage = tk.IntVar(value=1)
        self.setup_show_advanced = tk.BooleanVar(value=bool(self.settings.get("wayfinder.setup_show_advanced", False)))
        self.setup_storage_path = tk.StringVar(value=str(APP_DATA_ROOT))
        self.setup_storage_message = tk.StringVar(value="This is the active WayFinder storage location.")
        self.setup_storage_restart_required = tk.BooleanVar(value=False)
        self.startup_started_at = time.monotonic()
        self.startup_stage = "setup_check"
        self.startup_stage_started_at = self.startup_started_at
        self.startup_timed_out: set[str] = set()
        self.startup_completed: set[str] = set()
        self.startup_timeout_seconds = {"waiting_runtime": 30.0, "runtime_connected": 20.0, "context_attached": 20.0, "first_snapshot": 30.0}
        self.runtime_client = WayFinderRuntimeClient(self._snapshot_from_thread, self._log_from_thread, self._status_from_thread)
        self._map_render_thread.start()
        self._snapshot_persist_thread.start()
        self._configure_style(); self._install_styled_messageboxes(); self._build_menu(); self._build_ui(); self._apply_scaling(); self.root.bind("<Control-f>",self._focus_global_search,add="+"); self.root.bind("<Control-l>",self._focus_global_search,add="+"); self.root.bind("<F5>",lambda _e:self.refresh_state_clicked(),add="+"); self.root.after(50, self._drain_events); self.root.after(500, self._startup_watchdog_tick)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Do not hydrate tracker data from a previous run before the user has
        # explicitly connected.  Connection fields may have been edited since
        # the snapshot was written, and showing another server/slot's state is
        # more dangerous than starting empty.  The persisted snapshot remains
        # on disk for diagnostics/recovery, but live UI state begins blank and
        # only a snapshot from the newly connected native runtime may populate it.
        self._append_log("Previous tracker snapshot was not loaded; tracker state will populate after Connect confirms the current server and slot.")
        self._update_live_panel()
        self.root.after(1000, self._age_status_tick)
        self._player_pulse_on=False; self.root.after(650,self._pulse_player_marker)
        self.root.after(250, self._refresh_setup_status_async)

    # /**
    #  * Function: run
    #  * Purpose: Perform the run operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def run(self): self.root.mainloop()
