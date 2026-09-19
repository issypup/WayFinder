"""Provide connection controller support."""
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

import base64
import hashlib
import io
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from typing import Any
from difflib import SequenceMatcher
from datetime import datetime
from dataclasses import asdict

try:
    from PIL import Image, ImageTk
    Image.MAX_IMAGE_PIXELS = None
except (ImportError, OSError):
    Image = ImageTk = None

from wayfinder.connection.runtime_client import Snapshot, InventoryEntry, LocationEntry, PathResult, RuleNode, WayFinderRuntimeClient
from wayfinder.app.core.context import RunContext
from wayfinder.connection.memory import get_record, clear_server_slot, normalize_server
from wayfinder.maps.packs import discover_packs, best_pack, load_pack_variant, default_pack_dir, portable_pack_dir, install_pack_archive, related_archive_for_folder, game_pack_dir, TRACKER_PACK_API_VERSION, ZOOM_CACHE_LEVELS, cached_map_path, build_pack_zoom_cache, remove_pack_zoom_cache, validate_pack_archive, validate_pack_folder, install_validated_pack, enforce_map_cache_limit, persist_zoom_image_async
from wayfinder.maps.assets import LARGE_MAP_PIXELS, open_pack_image, remember_image, cached_image, render_result, asset_key, TiledMapPhoto, draw_map_photo
from wayfinder.maps.converter import convert_poptracker_pack, convert_ut_pack, detect_map_pack_archive_format
from wayfinder.diagnostics import CATEGORIES, sanitize, register_secret, make_record, format_record
from wayfinder.maps.intelligence import check_evidence
from wayfinder.connection.identity import validate_snapshot
from wayfinder.logic.progression_intelligence import detect_unlock_impact, waiting_analysis, route_score, build_progression_graph
from wayfinder.logic.solver_intelligence import normalized_kind, rank_or_branches, path_cycles, dead_route_reasons, provenance_rows, reconstruction_audit, searchable_entries, remote_dependency_lines, goal_target
import wayfinder.setup as setup_backend

# Shared app-level constants/helpers are imported lazily to avoid a circular import at
# module import time. They are looked up only when a callback actually executes.
def _app_globals():
    """Handle app globals."""
    from wayfinder.app import app as _app
    return _app

def _g(name):
    """Handle g."""
    return getattr(_app_globals(), name)


STATUS_VISUALS = {
    "reachable": {"label": "Reachable", "symbol": "●", "color": "#2f9e6f"},
    "glitched": {"label": "Glitch-only", "symbol": "⚡", "color": "#9b4fc4"},
    "out_of_logic": {"label": "Out of logic", "symbol": "◆", "color": "#d05b5b"},
    "checked": {"label": "Checked", "symbol": "✓", "color": "#7f8a91"},
    "ignored": {"label": "Ignored", "symbol": "—", "color": "#8c9499"},
    "non_progression": {"label": "Non-progression / untracked", "symbol": "○", "color": "#9a8f72"},
    "unknown": {"label": "Unknown", "symbol": "?", "color": "#71869a"},
}

from wayfinder.storage import app_data_root
from wayfinder.utils.error_handler import ErrorHandler

APP_DATA_ROOT = app_data_root()
SETTINGS_PATH = APP_DATA_ROOT / "settings.json"
STATE_PATH = APP_DATA_ROOT / "last_snapshot.json"

def _atomic_write_json(path: Path, data: Any, *, backup: bool = True) -> None:
    # Keep persistence semantics identical to app.py without importing it circularly.
    """Handle atomic write json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}-{threading.get_ident()}")
    if backup and path.exists():
        try:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        except OSError:
            _ignored("intentional best-effort fallback")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try: tmp.unlink(missing_ok=True)
        except OSError: _ignored("intentional best-effort fallback")

class ToolTip:
    """Provide tool tip behavior."""
    def __init__(self, widget: tk.Widget, text: str):
        """Handle init."""
        self.widget, self.text, self.tip = widget, text, None
        self._after_id = None
        
        
    def _schedule_show(self, _e=None):
        """Handle schedule show."""
        if self.tip or self._after_id or not self.text: return
        self._after_id = self.widget.after(550, self._show)
    def _show(self, _e=None):
        """Handle show."""
        self._after_id = None
        if self.tip or not self.text: return
        self.tip = tk.Toplevel(self.widget); self.tip.wm_overrideredirect(True)
        x = self.widget.winfo_rootx() + 16; y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg="#432633", fg="#edf3f8", padx=9, pady=6, relief="solid", bd=1, justify="left", wraplength=340).pack()
    def _hide(self, _e=None):
        """Handle hide."""
        if self._after_id is not None:
            try: self.widget.after_cancel(self._after_id)
            except tk.TclError: _ignored("intentional best-effort fallback")
            self._after_id = None
        if self.tip: self.tip.destroy(); self.tip = None

class ConnectionControllerMixin:
    """Extracted callbacks that operate on WayFinderApp-owned state."""

    def _connection_error_handler(self) -> ErrorHandler:
        """Handle connection error handler."""
        handler = ErrorHandler()
        handler.set_root(getattr(self, "root", None))
        return handler

    def _validate_connection_details(self, server: str, slot: str) -> tuple[bool, str]:
        """Validate user-entered connection details before runtime operations."""
        if not server:
            return False, "Enter the Archipelago server address before connecting."
        if not slot:
            return False, "Enter your Archipelago slot name before connecting."
        host, port = self._split_server_port(server)
        if not host or host in {"ws://", "wss://"}:
            return False, "Enter a valid Archipelago server address."
        if port:
            try:
                port_number = int(port)
            except ValueError:
                return False, "Enter a numeric server port between 1 and 65535."
            if not 1 <= port_number <= 65535:
                return False, "Enter a server port between 1 and 65535."
        if any(ch in slot for ch in "\r\n\0"):
            return False, "The slot name contains invalid characters."
        return True, ""
    def _split_server_port(self, value):
        # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
        """Handle split server port."""
        value=str(value or "").strip()
        if not value:
            return "", ""

        # Preserve the websocket scheme in the Server control while keeping the
        # numeric port in its own Port control.  Runtime snapshots commonly use
        # values such as ``ws://127.0.0.1:38281``; counting ':' on the raw string
        # mistakes the scheme separator for part of the host.
        # Variable(s): `scheme` (scheme); named state retained for the surrounding calculation or subsequent calls.
        scheme = ""
        # Variable(s): `remainder` (remainder); named state retained for the surrounding calculation or subsequent calls.
        remainder = value
        if "://" in value:
            # Variable(s): `scheme` (scheme), `remainder` (remainder); named state retained for the surrounding calculation or subsequent calls.
            scheme, remainder = value.split("://", 1)
            scheme += "://"

        # Bracketed IPv6, with or without a websocket scheme.
        if remainder.startswith("[") and "]:" in remainder:
            # Variable(s): `host` (host), `port` (port); named state retained for the surrounding calculation or subsequent calls.
            host, port = remainder.rsplit(":", 1)
            if port.isdigit():
                return scheme + host, port

        # Ordinary hostname / IPv4 plus numeric port.
        if remainder.count(":") == 1:
            # Variable(s): `host` (host), `port` (port); named state retained for the surrounding calculation or subsequent calls.
            host, port = remainder.rsplit(":", 1)
            if port.isdigit():
                return scheme + host, port

        return value, ""

    def _connection_server_value(self):
        # Variable(s): `host` (host); named state retained for the surrounding calculation or subsequent calls.
        """Handle connection server value."""
        host=self.server_host_var.get().strip() if hasattr(self,"server_host_var") else ""
        # Variable(s): `port` (port); named state retained for the surrounding calculation or subsequent calls.
        port=self.server_port_var.get().strip() if hasattr(self,"server_port_var") else ""
        # Variable(s): `port` (port); named state retained for the surrounding calculation or subsequent calls.
        port = port or "38281"
        return f"{host}:{port}" if host else ""

    def _connect_disconnect_clicked(self):
        # The button text/state is allowed to reflect a newer runtime connection
        # event than the last fully-applied snapshot.  Treat either source as
        # authoritative for a manual Disconnect so a stale snapshot cannot turn
        # a visible Disconnect button into an accidental Connect action.
        """Handle connect disconnect clicked."""
        button_requests_disconnect = False
        try:
            button_requests_disconnect = str(self.connect_btn.cget("text")).strip().casefold().startswith("disconnect")
        except (AttributeError, tk.TclError) as exc:
            self._connection_error_handler().logger.debug("Connection button state unavailable; using runtime state", exc_info=exc)
        runtime_reports_connected = str(getattr(self, "_ap_connection_state", "") or "").casefold() == "connected"
        if bool(getattr(self.snapshot,"connected",False)) or button_requests_disconnect or runtime_reports_connected:
            self._manual_disconnect_pending = True
            self._ap_connection_state = "disconnected"
            self._ap_connection_message = ""
            self._world_preparation_status = {}
            self._world_preparation_message = ""
            self._world_preparation_complete = {}
            self._last_map_cache_detail = "Not loaded"
            accepted = self.runtime_client.disconnect()
            self.connect_btn.configure(state="disabled", text="Disconnecting…")
            if accepted is False:
                self._append_log("Disconnect requested, but the native runtime is unavailable; the request could not be delivered.")
            else:
                self._append_log("Disconnect requested; disconnecting from Archipelago while keeping the WayFinder runtime available.")
            return
        # Variable(s): `server` (server); named state retained for the surrounding calculation or subsequent calls.
        server=self._connection_server_value()
        # Variable(s): `slot` (slot); named state retained for the surrounding calculation or subsequent calls.
        slot=self.name_var.get().strip()
        valid, validation_message = self._validate_connection_details(server, slot)
        if not valid:
            self._connection_error_handler().show_warning(validation_message, "Connection Error", "WF-CONN-001")
            return
        # Connecting must never rescan the Archipelago source tree on Tk's event thread.
        readiness = getattr(self, "_setup_readiness_cache", None)
        if readiness is None:
            self._refresh_setup_status_async()
            self._connection_error_handler().show_info("WayFinder is checking the installed Archipelago source and dependencies in the background. Try Connect again after setup status finishes refreshing.", "Connection Status", "WF-CONN-002")
            return
        missing=[]
        if not readiness["core_ok"]: missing.append("Archipelago Core")
        if not readiness["worlds_ok"]: missing.append("World Catalogue")
        if not readiness["deps_ok"]: missing.append("World Dependencies")
        if missing:
            self._connection_error_handler().handle_error(
                RuntimeError("Missing required setup components: " + ", ".join(missing)),
                "Connection cannot start until the listed setup components are installed or synced:\n\n• " + "\n• ".join(missing) + "\n\nOpen WayFinder Setup and complete these items.",
                "Connection Error", error_code="WF-CONN-003"
            )
            if missing == ["World Dependencies"] and hasattr(self, "_open_setup_stage"):
                self._open_setup_stage(4)
            else:
                self.show_page("WayFinder Setup")
            return
        if not readiness["yaml_match"]:
            if not messagebox.askyesno(
                "Matching player YAML not found",
                f"No player YAML matching slot {slot!r} was found.\n\nWayFinder can still connect. The connected APWorld may be able to reconstruct exact logic from slot data alone; WayFinder will report the reconstruction quality after the world is prepared.\n\nConnect anyway?"
            ):
                return
        # From this point onward the user has deliberately initiated a run, so
        # connection/runtime progress is allowed to appear in the dashboard.
        self._ap_connection_state = "connecting"
        self._ap_connection_message = ""
        self._world_preparation_status = {}
        self._world_preparation_message = ""
        self._world_preparation_complete = {}
        self._world_preparation_facts = {}
        self._last_map_cache_detail = "Not loaded"
        self._world_preparation_message = ''; self._world_preparation_status = {}
        for stage in ('waiting_ap_connection', 'first_snapshot'):
            self.startup_completed.discard(stage)
            self.startup_timed_out.discard(stage)
        self.startup_stage = 'waiting_ap_connection'
        self.startup_stage_started_at = time.monotonic()
        self._user_connect_requested = True
        self._refresh_dashboard_overview()
        if not self._ensure_local_runtime_started():
            self._user_connect_requested = False
            self._refresh_dashboard_overview()
            return
        self._manual_disconnect_pending = False
        # Variable(s): `old_identity` (old identity); named state retained for the surrounding calculation or subsequent calls.
        old_identity=self._runtime_identity
        # Variable(s): `requested_game` (requested game); named state retained for the surrounding calculation or subsequent calls.
        requested_game=""
        # A deliberate connection switch must not display the previous slot's
        # locations while the new AP connection is negotiating.
        self.run_context = RunContext(server=server, slot=slot, game=requested_game)
        self.snapshot=Snapshot(server=server, slot_name=slot, game=requested_game, connected=False, stale=False, stale_reason="", reachability_available=False, events_available=False)
        self.previous_snapshot=Snapshot()
        self._state_origin="none"; self._state_is_stale=False; self._state_stale_reason=""
        self.logic_status='waiting'; self.logic_status_message='Waiting for Archipelago authentication' 
        self._runtime_identity=None
        self._clear_game_specific_ui_state(old_identity, (server.casefold(),0,slot.casefold(),requested_game.casefold()), preserve_history=False)
        self._map_canonical_marker_state.clear(); self._map_marker_visual_state.clear(); self._map_last_statuses={}
        self._refresh_checks(); self._refresh_inventory(); self._refresh_ignored(); self._refresh_map_from_snapshot(); self._update_live_panel()
        handler = self._connection_error_handler()
        handler.logger.info("Connection request validated: server=%s slot=%s", server, slot)
        try:
            password = self.password_var.get()
            register_secret(password)
            handler.logger.info("Submitting connection request to native runtime")
            self.runtime_client.connect(server, slot, password)
            self.connect_btn.configure(state="disabled", text="Connecting…")
            self._save_settings()
            self._append_log(f"Connecting to {server} as {slot}…")
            handler.logger.info("Connection request queued successfully: server=%s slot=%s", server, slot)
        except (OSError, RuntimeError, ValueError, tk.TclError) as exc:
            self._user_connect_requested = False
            self._ap_connection_state = "disconnected"
            self._refresh_dashboard_overview()
            handler.handle_error(
                exc,
                "WayFinder could not start the connection. Check the server address, slot name, and runtime status, then try again.",
                "Connection Error",
                error_code="WF-CONN-004",
            )

    def connect_clicked(self):
        """Handle connect clicked as part of the WayFinder workflow."""
        self._connection_error_handler().show_info("WayFinder owns the Archipelago connection and manages its native runtime automatically.", "Connection Status")

    def disconnect_clicked(self):
        """Handle legacy/secondary disconnect controls through the same manual path."""
        self._manual_disconnect_pending = True
        self._ap_connection_state = "disconnected"
        self._ap_connection_message = ""
        self._world_preparation_status = {}
        self._world_preparation_message = ""
        self._world_preparation_complete = {}
        self._last_map_cache_detail = "Not loaded"
        self._append_log("GUI requested disconnect from the current Archipelago slot.")
        if hasattr(self, "disconnect_btn"):
            self.disconnect_btn.configure(state="disabled")
        if hasattr(self, "refresh_btn"):
            self.refresh_btn.configure(state="disabled")
        accepted = self.runtime_client.disconnect()
        if accepted is False:
            self._append_log("Disconnect request could not be delivered because the native runtime is unavailable.")

    def refresh_state_clicked(self):
        """Start one guarded refresh; overlapping clicks are ignored until completion/timeout."""
        if self._closing or self.recalculating or self._active_refresh_id:
            self._append_log("Refresh State ignored because a refresh is already running.")
            return
        self.recalculating = True
        self.logic_status = "recalculating"
        self.logic_status_message = ""
        self._active_refresh_id = self.runtime_client.refresh_state()
        self._latest_refresh_id = self._active_refresh_id
        self._timed_out_refresh_id = 0
        if self._refresh_timeout_after_id is not None:
            try: self.root.after_cancel(self._refresh_timeout_after_id)
            except (tk.TclError, RuntimeError): _ignored("Tk timer was already unavailable during cleanup")
        self._refresh_timeout_after_id = self.root.after(35000, lambda rid=self._active_refresh_id: self._refresh_timed_out(rid))
        self._update_live_panel()
        self._append_log(f"GUI requested manual state refresh #{self._active_refresh_id}.")

    def _refresh_timed_out(self, refresh_id: int):
        """Handle refresh timed out."""
        if self._closing or refresh_id != self._active_refresh_id:
            return
        self.recalculating = False
        self.logic_status = "timeout"
        self.logic_status_message = "Refresh request exceeded 35s; previous live snapshot retained"
        # A manual refresh timeout does not mean the native runtime disconnected and does not
        # invalidate the previous successfully published live snapshot.
        self._active_refresh_id = 0
        self._timed_out_refresh_id = refresh_id
        self._refresh_timeout_after_id = None
        self._append_log(
            f"Manual state refresh #{refresh_id} exceeded 35 seconds; "
            "the previous live snapshot remains displayed."
        )
        self._update_live_panel()

    def _finish_refresh(self, refresh_id: int, state: str = "complete", message: str = ""):
        """Handle finish refresh."""
        if refresh_id and refresh_id != self._latest_refresh_id:
            self._append_log(f"Ignored stale refresh completion #{refresh_id}; newest refresh is #{self._latest_refresh_id}.")
            return False
        if refresh_id and refresh_id == self._timed_out_refresh_id:
            self._append_log(f"Ignored late completion for timed-out refresh #{refresh_id}.")
            return False
        if refresh_id and self._active_refresh_id and refresh_id != self._active_refresh_id:
            self._append_log(f"Ignored stale refresh completion #{refresh_id}; active refresh is #{self._active_refresh_id}.")
            return False
        if self._refresh_timeout_after_id is not None:
            try: self.root.after_cancel(self._refresh_timeout_after_id)
            except (tk.TclError, RuntimeError): _ignored("Tk timer was already unavailable during cleanup")
        self._refresh_timeout_after_id = None
        self.recalculating = False
        self._active_refresh_id = 0
        self.logic_status = "idle" if state == "complete" else "error"
        self.logic_status_message = message
        if state == "complete":
            self._state_is_stale=False
            self._state_stale_reason=""
        # A failed manual refresh leaves the previous live snapshot intact.
        # Only a real AP disconnect or persisted restore marks state stale.
        return True

