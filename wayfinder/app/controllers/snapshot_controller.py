"""Provide snapshot controller support."""
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored
from wayfinder.utils.error_handler import ErrorHandler

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
except Exception:
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

class SnapshotControllerMixin:
    """Extracted callbacks that operate on WayFinderApp-owned state."""
    def _persist_snapshot(self, snap: Snapshot) -> None:
        """Queue the newest last-good snapshot for background persistence.

        Disk JSON encoding/fsync is deliberately never performed from Tk's event
        thread.  The queue is size one because an older pending snapshot has no
        recovery value once a newer last-good state exists.
        """
        if not snap.connected or snap.error or not snap.locations or self._closing:
            return
        try:
            while True:
                self._snapshot_persist_queue.get_nowait()
        except queue.Empty:
            _ignored("intentional best-effort fallback")
        try:
            self._snapshot_persist_queue.put_nowait(snap)
        except queue.Full:
            # A racing producer won between the drain and put.  Keeping that
            # newest queued snapshot is preferable to blocking Tk.
            _ignored("intentional best-effort fallback")

    def _snapshot_persist_worker_loop(self) -> None:
        """Persist snapshots away from Tk so Connect never waits on disk I/O."""
        while True:
            try:
                snap = self._snapshot_persist_queue.get()
            except Exception:
                return
            if snap is None:
                return
            try:
                payload = asdict(snap)
                payload["state_origin"] = "persisted"
                payload["stale"] = True
                payload["stale_reason"] = "Loaded from the previous WayFinder session"
                _atomic_write_json(STATE_PATH, payload, backup=True)
            except Exception as exc:
                if not self._closing:
                    self.events.put(("log", f"Could not persist last-good snapshot in background: {exc!r}"))

    def _schedule_snapshot_ui_refresh(self) -> None:
        """Repaint snapshot-driven pages in cooperative Tk-sized batches.

        Tk widgets are not thread-safe, so their mutation must remain on the GUI
        thread.  Splitting the work across short callbacks gives Tcl/Tk a chance
        to service redraw, movement, button and close events between expensive
        tree/map/graph refreshes.
        """
        if self._closing:
            return
        self._snapshot_ui_refresh_generation += 1
        generation = self._snapshot_ui_refresh_generation
        if self._snapshot_ui_refresh_after_id is not None:
            try:
                self.root.after_cancel(self._snapshot_ui_refresh_after_id)
            except Exception:
                _ignored("intentional best-effort fallback")
            self._snapshot_ui_refresh_after_id = None

        # Put the cheap, user-visible live surfaces first.  Previously map refresh
        # lived in batch 5; a burst of AP snapshots could continually supersede
        # the cooperative refresh generation before batch 5 ran, leaving checked
        # markers stale until the Map tab was reopened.  Marker refresh is already
        # delta/in-place and does not re-decode the background.
        batches = (
            (self._update_live_panel, self._refresh_dashboard_overview, self._refresh_map_from_snapshot, self._refresh_checks),
            (self._refresh_path_selector, self._refresh_inventory, self._refresh_hints, self._refresh_combined_inventory),
            (self._refresh_events, self._refresh_entrances, self._refresh_ignored, self._refresh_recent),
            (self._refresh_compatibility, self._refresh_logic_engine, self._refresh_map_group_popup),
            (self._refresh_stuck, self._refresh_progression_graph, self._refresh_route_goal),
        )

        def run_batch(index: int = 0) -> None:
            """Handle run batch."""
            if self._closing or generation != self._snapshot_ui_refresh_generation:
                return
            if index >= len(batches):
                self._snapshot_ui_refresh_after_id = None
                return
            for callback in batches[index]:
                if self._closing or generation != self._snapshot_ui_refresh_generation:
                    return
                try:
                    callback()
                except (AttributeError, KeyError, tk.TclError):
                    # Some optional pages/widgets may not exist during startup or
                    # teardown.  Match the former monolithic refresh's tolerance.
                    _ignored("intentional best-effort fallback")
            self._snapshot_ui_refresh_after_id = self.root.after(1, run_batch, index + 1)

        self._snapshot_ui_refresh_after_id = self.root.after(0, run_batch)

    def _restore_persisted_snapshot(self) -> None:
        # Loop variable(s): `candidate` (candidate); each iteration represents the next value from the iterable below.
        """Handle restore persisted snapshot."""
        for candidate in (STATE_PATH, STATE_PATH.with_suffix(STATE_PATH.suffix + ".bak")):
            try:
                # Variable(s): `d` (d); named state retained for the surrounding calculation or subsequent calls.
                d=json.loads(candidate.read_text(encoding="utf-8"))
                if not isinstance(d,dict): continue
                # Variable(s): `saved_server` (saved server); named state retained for the surrounding calculation or subsequent calls.
                saved_server=str(d.get("server","") or "").strip().casefold().rstrip("/")
                # Variable(s): `saved_slot` (saved slot); named state retained for the surrounding calculation or subsequent calls.
                saved_slot=str(d.get("slot_name","") or "").strip().casefold()
                # Variable(s): `wanted_server` (wanted server); named state retained for the surrounding calculation or subsequent calls.
                wanted_server=str(self.initial_server or "").strip().casefold().rstrip("/")
                # Variable(s): `wanted_slot` (wanted slot); named state retained for the surrounding calculation or subsequent calls.
                wanted_slot=str(self.initial_name or "").strip().casefold()
                if wanted_server and wanted_slot and (saved_server != wanted_server or saved_slot != wanted_slot):
                    self._append_log(
                        f"Ignored persisted snapshot for different connection: "
                        f"{d.get('slot_name','?')} @ {d.get('server','?')}."
                    )
                    continue
                d["inventory"]=[InventoryEntry(**x) for x in d.get("inventory",[]) if isinstance(x,dict)]
                d["locations"]=[LocationEntry(**x) for x in d.get("locations",[]) if isinstance(x,dict)]
                # Variable(s): `allowed` (allowed); named state retained for the surrounding calculation or subsequent calls.
                allowed=set(Snapshot.__dataclass_fields__)
                # Variable(s): `snap` (snap); named state retained for the surrounding calculation or subsequent calls.
                snap=Snapshot(**{k:v for k,v in d.items() if k in allowed})
                # Persisted snapshots are display-only history.  A previous
                # session may have been connected when this snapshot was saved,
                # but process/network connection state must never survive an app
                # restart.  Keeping connected=True here made the dashboard render
                # Disconnect on launch and clicking it accidentally woke the lazy
                # runtime transport.
                snap.connected=False
                snap.state_origin="persisted"; snap.stale=True
                snap.stale_reason=snap.stale_reason or "Loaded from previous WayFinder session"
                self.snapshot=snap
                self._state_origin="persisted"; self._state_is_stale=True; self._state_stale_reason=snap.stale_reason
                self._last_logic_success_epoch=float(getattr(snap,"last_logic_success_epoch",0.0) or 0.0)
                self._runtime_identity=(str(snap.server or "").strip().casefold(), int(getattr(snap,"team",0) or 0), str(snap.slot_name or "").strip().casefold(), str(snap.game or "").strip().casefold())
                self._append_log("Restored last-good tracker snapshot from persistence; marked STALE until the native runtime confirms it.")
                try:
                    self._refresh_checks(); self._refresh_inventory(); self._refresh_hints(); self._refresh_combined_inventory(); self._refresh_events(); self._refresh_entrances(); self._refresh_ignored(); self._refresh_map_from_snapshot(); self._refresh_stuck(); self._refresh_progression_graph(); self._refresh_route_goal(); self._refresh_dashboard_overview()
                    self.stat_vars["reach"].set(str(len(snap.reachable))); self.stat_vars["missing"].set(str(snap.missing_count)); self.stat_vars["checked"].set(str(snap.checked_count)); self.stat_vars["prog"].set(str(sum(1 for x in snap.inventory if x.progression)))
                except (AttributeError, KeyError, tk.TclError):
                    _ignored("intentional best-effort fallback")
                return
            except (OSError,json.JSONDecodeError,UnicodeError,TypeError,ValueError):
                continue

    def _logic_age_text(self) -> str:
        """Handle logic age text."""
        if not self._last_logic_success_epoch:
            return "never"
        # Variable(s): `age` (age); named state retained for the surrounding calculation or subsequent calls.
        age=max(0,int(time.time()-self._last_logic_success_epoch))
        if age < 60: return f"{age}s ago"
        if age < 3600: return f"{age//60}m {age%60}s ago"
        return f"{age//3600}h {(age%3600)//60}m ago"

    def _age_status_tick(self):
        """Handle age status tick."""
        if self._closing: return
        self._update_live_panel()
        self.root.after(1000,self._age_status_tick)

    def _snapshot_from_thread(self,snap):
        """Handle snapshot from thread."""
        if not self._closing: self.events.put(("snapshot",snap))

    def _log_from_thread(self,text):
        """Handle log from thread."""
        if not self._closing: self.events.put(("log",str(text)))

    def _status_from_thread(self,name,value):
        """Handle status from thread."""
        if not self._closing: self.events.put(("status",(name,value)))

    def _drain_events(self):
        """Drain queued runtime events and apply them from Tk's event thread."""
        if self._closing:
            return
        try:
            while not self._closing:
                # Variable(s): `kind` (kind), `payload` (payload); named state retained for the surrounding calculation or subsequent calls.
                kind,payload=self.events.get_nowait()
                if kind=="snapshot":
                    try:
                        self._apply_snapshot(payload)
                    except Exception as exc:
                        import traceback
                        try:
                            self._append_log(f"Snapshot UI apply failed: {type(exc).__name__}: {exc}", category="GUI", level="ERROR")
                        except Exception:
                            pass
                        print(f"[GUI] snapshot apply failed: {type(exc).__name__}: {exc}", flush=True)
                        traceback.print_exc()
                elif kind=="log": self._append_log(payload)
                elif kind=="path": self._render_path(payload)
                elif kind=="path_guarded":
                    # Variable(s): `req_id` (req id), `result` (result); named state retained for the surrounding calculation or subsequent calls.
                    req_id,result=payload
                    if req_id==self._active_path_request:
                        self._active_path_request=0; self._render_path(result)
                elif kind=="status": self._apply_status(*payload)
                elif kind=="map_render_done": self._finish_map_render(*payload)
                elif kind=="map_render_failed": self._map_render_failed(*payload)
                elif kind=="map_install_stage":
                    # Variable(s): `text` (text), `_done` (done), `_total` (total); named state retained for the surrounding calculation or subsequent calls.
                    text,_done,_total=payload
                    if self._map_install_status_var is not None: self._map_install_status_var.set(text)
                elif kind=="map_install_progress": self._set_map_install_progress(*payload)
                elif kind=="map_install_log": self._append_log(payload)
                elif kind=="map_validation_report":
                    self._last_pack_validation_report=payload.report()
                    if hasattr(self,"diag_validation"):
                        self.diag_validation.set("Map-pack diagnostics: "+payload.summary())
                        if hasattr(self,"diag_fields"): self.diag_fields["validation"].set(payload.summary())
                elif kind=="map_install_done": self._finish_map_pack_install(*payload)
                elif kind=="map_install_failed":
                    self._close_map_install_progress()
                    ErrorHandler().handle_error(RuntimeError(str(payload)), "WayFinder could not install the map pack. Validate the pack and check Diagnostics for details.", "Map Pack Error", error_code="WF-MAP-001")
        except queue.Empty: _ignored("intentional best-effort fallback")
        if not self._closing:
            self.root.after(50,self._drain_events)

    def _apply_status(self,name,value):
        """Handle apply status."""
        self._feature_status(name,value)
        """Apply the received status update to local GUI state and dependent widgets."""
        if name=="recalculating":
            if not value and self._active_refresh_id:
                # Completion is correlated by refresh_status/snapshot; a stale bool cannot end a newer request.
                _ignored("intentional best-effort fallback")
            else:
                self.recalculating=bool(value)
        elif name=="refresh_status" and isinstance(value, dict):
            # Variable(s): `rid` (rid); named state retained for the surrounding calculation or subsequent calls.
            rid=int(value.get("id", 0) or 0); state=str(value.get("state", "")); message=str(value.get("message", "") or "")
            if state in {"complete", "failed"}:
                self._finish_refresh(rid, state, message)
            elif state=="running" and (not self._active_refresh_id or rid==self._active_refresh_id):
                self.recalculating=True; self.logic_status="recalculating"
        elif name=="refresh_phase":
            # Variable(s): `info` (info); named state retained for the surrounding calculation or subsequent calls.
            info=value if isinstance(value,dict) else {}
            # Variable(s): `rid` (rid); named state retained for the surrounding calculation or subsequent calls.
            rid=int(info.get("id",0) or 0)
            if not self._active_refresh_id or rid==self._active_refresh_id:
                self._refresh_phase_name=str(info.get("phase","idle") or "idle")
                self.logic_status_message=f"Refresh #{rid}: {self._refresh_phase_name}"
        elif name=="runtime_state":
            # Variable(s): `info` (info); named state retained for the surrounding calculation or subsequent calls.
            info=value if isinstance(value,dict) else {}
            self._runtime_state_name=str(info.get("current",self._runtime_state_name))
            # Variable(s): `hist` (hist); named state retained for the surrounding calculation or subsequent calls.
            hist=info.get("history",[])
            if isinstance(hist,list): self._runtime_transition_history=hist[-32:]
            # Variable(s): `tr` (tr); named state retained for the surrounding calculation or subsequent calls.
            tr=info.get("transition")
            if isinstance(tr,dict):
                self._append_log(f"[Runtime state #{tr.get('seq','?')}] {tr.get('from','?')} → {tr.get('to','?')} — {tr.get('reason','')}")
        elif name=="state_stale":
            # Variable(s): `info` (info); named state retained for the surrounding calculation or subsequent calls.
            info=value if isinstance(value,dict) else {}
            self._state_is_stale=bool(info.get("stale",True))
            self._state_stale_reason=str(info.get("reason","") or "")
            if self._state_is_stale:
                self.logic_status="stale"; self.logic_status_message=self._state_stale_reason or "Showing cached state"
        elif name=="event_sweep_error":
            if value:
                self.logic_status="error"
                self.logic_status_message=f"Event sweep failed: {value}"
                self._append_log(f"[Logic Events] Event sweep failed: {value}")
                if hasattr(self,"event_availability"):
                    self.event_availability.set(f"Events: sweep failed — {value}")
        elif name=="logic_update_error":
            if value:
                self.logic_status="error"
                self.logic_status_message=f"Logic update failed: {value}"
        elif name=="ap_connection_state":
            info=value if isinstance(value,dict) else {"state": str(value or ""), "message": ""}
            self._ap_connection_state=str(info.get("state", "") or "")
            self._ap_connection_message=str(info.get("message", "") or "")
            if self._ap_connection_state == "connected":
                if getattr(self, '_manual_disconnect_pending', False):
                    self._ap_connection_state = 'disconnected'
                    return
                self._ap_connection_message=""
                self._startup_complete('waiting_ap_connection')
                self._startup_enter('first_snapshot')
            self._update_live_panel()
        elif name == 'world_preparation':
            if isinstance(value, dict):
                # Status messages and the first snapshot travel independently over IPC.
                # A delayed runtime preparation message must never regress a Dashboard
                # that the GUI has already promoted to WORLD READY from that snapshot.
                complete = dict(getattr(self, '_world_preparation_complete', {}) or {})
                incoming_state = str(value.get('state', '') or '')
                incoming_step = int(value.get('step', 0) or 0)
                if hasattr(self, '_prep_debug'):
                    self._prep_debug("world_preparation_incoming", incoming_state=incoming_state, incoming_step=incoming_step, incoming_total=int(value.get('total',0) or 0), incoming_phase=str(value.get('phase','') or ''), incoming_message=str(value.get('message','') or ''))
                current = dict(getattr(self, '_world_preparation_status', {}) or {})
                current_state = str(current.get('state', '') or '')
                current_step = int(current.get('step', 0) or 0)
                if complete.get('state') == 'complete' and incoming_step <= int(complete.get('step', 10) or 10):
                    if hasattr(self, '_prep_debug'):
                        self._prep_debug("regression_ignored", incoming_state=incoming_state, incoming_step=incoming_step, completed_step=int(complete.get('step',10) or 10), reason="world_already_ready")
                    return
                # Preparation stages are monotonic.  Late informational packets
                # (for example APWorld located at step 4 after dependencies at
                # step 5) may update facts, but must not move the visible state
                # machine backwards.
                if incoming_state == 'running' and current_state == 'running' and incoming_step < current_step:
                    if hasattr(self, '_prep_debug'):
                        self._prep_debug("regression_ignored", incoming_state=incoming_state, incoming_step=incoming_step, current_step=current_step, reason="lower_step")
                    for fact in ('game','slot','cache_hit','logic_source','exact_logic','elapsed','apworld','apworld_path','apworld_source','apworld_version','identification','dependency_count','managed_dependency_count','locations','reachable','timings'):
                        if fact in value:
                            self._world_preparation_facts[fact]=value.get(fact)
                    return
                # The runtime can emit ``cancelled`` for the step-7 preparation
                # task when it hands off to snapshot syncing.  SYNCING/TRACKING
                # means the world build is continuing successfully, so retain
                # the running step until the authoritative snapshot promotes it.
                runtime_state = str(getattr(self, '_runtime_state', '') or '').upper()
                if incoming_state == 'cancelled' and incoming_step >= 7 and runtime_state in {'SYNCING','TRACKING'}:
                    if hasattr(self, '_prep_debug'):
                        self._prep_debug("provisional_cancel_ignored", incoming_state=incoming_state, incoming_step=incoming_step, current_step=current_step, runtime_state=runtime_state)
                    return
                self._world_preparation_status = dict(value)
                for fact in ('game','slot','cache_hit','logic_source','exact_logic','elapsed','apworld','apworld_path','apworld_source','apworld_version','identification','dependency_count','managed_dependency_count','locations','reachable','timings'):
                    if fact in value:
                        self._world_preparation_facts[fact]=value.get(fact)
                if value.get('phase')=='reconstructing' and 'duration' in value:
                    self._world_preparation_facts['reconstruction_duration']=value.get('duration')
                message = str(value.get('message', '') or '')
                step = int(value.get('step', 0) or 0); total = int(value.get('total', 0) or 0); state = str(value.get('state', '') or '')
                prefix = f"{step}/{total} • " if step and total else ""
                self._world_preparation_message = prefix + message if message else state.replace('_',' ').title()
            else:
                # Backward compatibility with older runtimes that emitted text.
                self._world_preparation_status = {'message': str(value or ''), 'state': 'running'}
                self._world_preparation_message = str(value or '')
            self._update_preparation_panel()
            self._update_live_panel()
        elif name=="runtime_available" and not bool(value):
            self.recalculating=False; self._active_refresh_id=0
            self.logic_status="error"; self.logic_status_message="Native runtime unavailable"
        elif name=="engine_version" and value and str(value)!="unknown":
            self.runtime_engine_version=str(value)
        elif name=="ap_version" and value and str(value)!="unknown":
            self.runtime_ap_version=str(value)
        elif name=="integration_version" and value and str(value)!="unknown":
            self.runtime_integration_version=str(value)
        elif name=="apworld_generated_by" and value and str(value)!="unknown":
            self.runtime_apworld_generated_by=str(value)
        elif name=="runtime_transport":
            # Variable(s): `previous` (previous); named state retained for the surrounding calculation or subsequent calls.
            previous=self.runtime_client_transport_state
            self.runtime_client_transport_state=str(value)
            # This is only the localhost GUI ↔ embedded-runtime IPC link. A
            # transient reconnect must not be presented as the Archipelago connection
            # disconnecting from the Archipelago server.
            if str(value) in {"reconnecting","disconnected","starting"} and previous != str(value):
                self._append_log(f"[Internal UI link] {value}; retaining the last live tracker snapshot.")
            if str(value)=="connected":
                if self._timing_runtime_start_seconds is None:
                    self._timing_runtime_start_seconds=max(0.0,time.perf_counter()-self._gui_started_at)
                self._startup_complete("waiting_runtime")
                self._startup_complete("runtime_connected")
                self._update_diagnostic_timings()
                self._startup_enter("context_attached")
        elif name in {"runtime_startup_stage", "startup_stage"}:
            # Variable(s): `runtime_stage` (runtime stage); named state retained for the surrounding calculation or subsequent calls.
            runtime_stage=str(value or "")
            # Any stage at/after context_ready proves the native context exists.
            # Do not leave the watchdog parked on the older waiting_runtime stage.
            if runtime_stage in {"context_ready", "ready", "connecting_archipelago"}:
                self._startup_complete("waiting_runtime")
                self._startup_complete("runtime_connected")
                self._startup_complete("context_attached")
                if not self.snapshot.connected:
                    self._startup_enter("waiting_ap_connection")
        elif name=="live_context" and str(value)=="attached":
            self._startup_complete("waiting_runtime")
            self._startup_complete("runtime_connected")
            self._startup_complete("context_attached")
            if not self.snapshot.connected:
                self._startup_enter("waiting_ap_connection")
        self._update_live_panel()

    def _apply_snapshot(self,s:Snapshot):
        """Validate ordering/identity before replacing the last known-good GUI snapshot."""
        if self._closing:
            return
        try:
            data=dict(vars(s),locations=[vars(x) for x in s.locations],inventory=[vars(x) for x in s.inventory])
            validate_snapshot(data,bool(getattr(s,"seed_identity",{})))
            gate=getattr(self.runtime_client,"_seed_gate",None)
            if s.connection_id and gate and (s.connection_id!=gate.connection_id or (s.connected and s.seed_identity.get("id")!=gate.expected_seed)):
                raise ValueError("Snapshot belongs to an obsolete seed or connection")
        except (ValueError,TypeError) as exc:
            self._append_log(str(exc),category="SNAPSHOT",level="WARNING");return
        # A manually requested disconnect is different from a network drop. Keep
        # the last useful tracker data visible as STALE, but immediately flip the
        # user-visible connection state to disconnected so the button becomes
        # Connect and the connection fields remain editable.
        if not s.connected and self.snapshot.locations and not s.locations and not s.inventory:
            self.recalculating=False; self._active_refresh_id=0
            if self._manual_disconnect_pending:
                self.snapshot.connected=False
                self.snapshot.stale=True
                self.snapshot.stale_reason="Manually disconnected from Archipelago; showing previous valid tracker state"
                self._manual_disconnect_pending=False
                self._state_is_stale=True
                self._state_stale_reason=self.snapshot.stale_reason
                self.logic_status="stale"; self.logic_status_message=self._state_stale_reason
                self._append_log("Manual Archipelago disconnect confirmed; previous tracker state retained as STALE and connection fields unlocked.")
                self._update_live_panel()
                return
            self._state_is_stale=True
            self._state_stale_reason="Native runtime lost the Archipelago connection; showing previous valid snapshot"
            self.logic_status="stale"; self.logic_status_message=self._state_stale_reason
            self._append_log("Archipelago connection changed; retained previous valid snapshot and UI selection as STALE.")
            self._update_live_panel()
            return
        if s.error and not s.game and not s.slot_name and not s.locations and not s.inventory:
            self.recalculating=False; self._active_refresh_id=0
            self.logic_status="error"; self.logic_status_message=s.error
            self._append_log(s.error)
            self._update_live_panel()
            return
        # Variable(s): `runtime_id` (runtime id); named state retained for the surrounding calculation or subsequent calls.
        runtime_id=str(getattr(s, "runtime_id", "") or "")
        # Variable(s): `seq` (seq); named state retained for the surrounding calculation or subsequent calls.
        seq=int(getattr(s, "snapshot_sequence", 0) or 0)
        if seq and runtime_id == self._snapshot_runtime_id and seq <= self._last_snapshot_sequence:
            self._append_log(f"Rejected out-of-sequence snapshot #{seq}; last accepted was #{self._last_snapshot_sequence}.")
            return
        # Variable(s): `identity` (identity); named state retained for the surrounding calculation or subsequent calls.
        identity=(str(s.server or "").strip().casefold(), int(getattr(s,"team",0) or 0), str(s.slot_name or "").strip().casefold(), str(s.game or "").strip().casefold())
        if s.connected and self.snapshot.connected and self.snapshot.locations and not s.locations and not s.error and identity == self._runtime_identity:
            self.logic_status="error"; self.logic_status_message="Empty snapshot rejected"
            self._append_log("Rejected an unexpected empty connected snapshot; keeping the last good state.")
            self._update_live_panel(); return
        # Variable(s): `rid` (rid); named state retained for the surrounding calculation or subsequent calls.
        rid=int(getattr(s,"refresh_id",0) or 0)
        if rid and rid != self._latest_refresh_id:
            self._append_log(f"Ignored stale refresh snapshot #{rid}; newest refresh is #{self._latest_refresh_id}.")
            return
        if rid and rid == self._timed_out_refresh_id:
            self._append_log(f"Ignored late snapshot for timed-out refresh #{rid}; keeping the last good state.")
            return
        if rid and self._active_refresh_id and rid != self._active_refresh_id:
            self._append_log(f"Ignored stale refresh snapshot #{rid}; active refresh is #{self._active_refresh_id}.")
            return
        old_seed=getattr(self.snapshot,"seed_identity",{}).get("id")
        new_seed=s.seed_identity.get("id")
        if old_seed and new_seed and old_seed!=new_seed:
            self._clear_game_specific_ui_state(self._runtime_identity,identity,preserve_history=False)
            self._replace_run_context(s)
        self._snapshot_runtime_id=runtime_id
        if seq:self._last_snapshot_sequence=seq
        if self._runtime_identity and identity != self._runtime_identity:
            self._clear_game_specific_ui_state(self._runtime_identity, identity)
            self._replace_run_context(s)
        if any(identity):
            self._runtime_identity=identity
            if getattr(self,"run_context",RunContext()).identity != identity:
                self._replace_run_context(s)
        # Variable(s): `pkg` (pkg); named state retained for the surrounding calculation or subsequent calls.
        pkg=str(getattr(s,"data_package_signature","") or "")
        if self._data_package_signature and pkg and pkg != self._data_package_signature:
            self._append_log("Archipelago datapackage signature changed; rebuilt GUI location/item indexes from the new snapshot.")
            self._clear_game_specific_ui_state(self._runtime_identity, self._runtime_identity, preserve_history=False)
        if pkg: self._data_package_signature=pkg
        # Never replace a populated good snapshot with a suspicious empty conversion for the same live identity.
        if rid: self._finish_refresh(rid, "complete")
        elif self.recalculating and not self._active_refresh_id:
            self.recalculating=False; self.logic_status="idle"; self.logic_status_message=""
        if "context_attached" not in self.startup_completed:
            # A real snapshot can only be produced from the native runtime context,
            # so this safely recovers if the earlier status event arrived before
            # the visual client connected.
            self._startup_complete("context_attached")
        if s.connected:
            self._startup_complete("waiting_ap_connection")
        if "first_snapshot" not in self.startup_completed:
            self._startup_complete("first_snapshot")
            self.startup_stage = "ready"
            self._append_log("Startup complete: first WayFinder native snapshot received.")
        # Variable(s): `replacing_persisted` (replacing persisted); named state retained for the surrounding calculation or subsequent calls.
        replacing_persisted = (
            self._state_origin == "persisted"
            and str(getattr(s,"state_origin","live") or "live") == "live"
            and not bool(getattr(s,"stale",False))
        )
        if replacing_persisted:
            # Persisted data is display-only startup scaffolding. The first real
            # native snapshot is a hard authority boundary: do not diff/merge/cache
            # against old checked/reachable/ignored state.
            self._append_log("First live native snapshot superseded the restored STALE snapshot in full.")
            self.previous_snapshot=Snapshot()
            self._map_canonical_marker_state.clear(); self._map_marker_visual_state.clear(); self._map_last_statuses={}
            self.map_selected_location=""; self._close_map_group_popup()
            self.inventory_deltas.clear(); self.recent_changes.clear()

        if s.connected and str(getattr(s, "state_origin", "live") or "live") == "live":
            self._restore_ignored_locations_for_snapshot(s)

        # Track new hints and hint-state transitions across accepted live snapshots.
        # Variable(s): `now_hint` (now hint); named state retained for the surrounding calculation or subsequent calls.
        now_hint=time.monotonic()
        # Variable(s): `incoming_hints` (incoming hints); named state retained for the surrounding calculation or subsequent calls.
        incoming_hints=getattr(s,"hints",[]) or []
        # Loop variable(s): `h` (height/handle value (context dependent)); each iteration represents the next value from the iterable below.
        for h in incoming_hints:
            # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
            key=(str(h.get("item","")),str(h.get("location","")),str(h.get("receiving_player","")),str(h.get("finding_player","")))
            # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
            status=str(h.get("status","unspecified") or "unspecified")
            if key not in self._hint_seen_keys:
                self._hint_seen_keys.add(key); self._hint_recent_until[key]=now_hint+8.0
            elif self._hint_last_status.get(key) not in (None,status):
                self._hint_changed_until[key]=now_hint+8.0
                self.recent_changes.insert(0,(datetime.now().strftime("%H:%M:%S"),"Hint",f"{key[0]} @ {key[1]}: {self._hint_last_status.get(key)} → {status}"))
            self._hint_last_status[key]=status
        if not replacing_persisted:
            self.previous_snapshot=self.snapshot
        self.snapshot=s
        # The Dashboard lifecycle reads self.snapshot and the GUI stale-state flags.
        # Update those authoritative fields before completing GUI preparation;
        # otherwise _finish_world_preparation_in_gui() renders step 10 against the
        # previous/placeholder snapshot and can leave LOGIC EVALUATED stuck on !
        # even though the newly accepted native snapshot has exact reachability.
        self._state_origin=str(getattr(s,"state_origin","live") or "live")
        self._state_is_stale=bool(getattr(s,"stale",False))
        self._state_stale_reason=str(getattr(s,"stale_reason","") or "")
        self._last_logic_success_epoch=float(getattr(s,"last_logic_success_epoch",0.0) or time.time())
        if hasattr(self, '_prep_debug'):
            self._prep_debug("snapshot_before_finish", accepted_sequence=int(getattr(s,"snapshot_sequence",0) or 0), accepted_updated_at=str(getattr(s,"updated_at","") or ""))
        self._finish_world_preparation_in_gui(s)
        if hasattr(self, '_prep_debug'):
            self._prep_debug("snapshot_after_finish", accepted_sequence=int(getattr(s,"snapshot_sequence",0) or 0))
        if self._state_origin=="live" and not self._state_is_stale:
            self.logic_status="idle"; self.logic_status_message=""
            self._persist_snapshot(s)
        # Variable(s): `old_logic` (old logic); named state retained for the surrounding calculation or subsequent calls.
        old_logic=(tuple((x.name,x.count) for x in self.previous_snapshot.inventory), tuple(self.previous_snapshot.events), tuple((x.name,x.status) for x in self.previous_snapshot.locations))
        # Variable(s): `new_logic` (new logic); named state retained for the surrounding calculation or subsequent calls.
        new_logic=(tuple((x.name,x.count) for x in s.inventory), tuple(s.events), tuple((x.name,x.status) for x in s.locations))
        if old_logic != new_logic and self.current_path is not None:
            self.current_path=None
            try:
                self.path_status.set("Tracker state changed; reopen the path to recalculate it.")
                self.breadcrumb_var.set("Path invalidated by logic/inventory change")
            except Exception: _ignored("intentional best-effort fallback")
        # Variable(s): `start_diag` (start diag); named state retained for the surrounding calculation or subsequent calls.
        start_diag=(s.game, s.starting_location, s.starting_location_option, repr(s.starting_location_raw), s.starting_location_source)
        if s.starting_location and start_diag != self._last_start_location_diag:
            self._last_start_location_diag=start_diag
            self._append_log(
                f"[Start Resolution] {s.game or 'Unknown game'}: FOUND "
                f"{s.starting_location_option or 'start'}={s.starting_location_raw!r} -> "
                f"{s.starting_location} (source: {s.starting_location_source or 'runtime snapshot'})."
            )
        self._record_recent_changes(self.previous_snapshot,s)
        self._schedule_snapshot_ui_refresh()
        self.stat_vars["reach"].set(str(len(s.reachable)) if getattr(s,"reachability_available",True) else "N/A"); self.stat_vars["missing"].set(str(s.missing_count)); self.stat_vars["checked"].set(str(s.checked_count)); self.stat_vars["prog"].set(str(sum(1 for x in s.inventory if x.progression))); self.stat_vars["glitch"].set(str(len(s.glitched))); self.stat_vars["events"].set(str(len(s.events)) if getattr(s,"events_available",True) else "N/A"); self.stat_vars["regions"].set(str(len(s.in_logic_regions)) if getattr(s,"reachability_available",True) else "N/A"); self.stat_vars["go"].set(s.go_mode)
        # Variable(s): `position_state` (position state); named state retained for the surrounding calculation or subsequent calls.
        position_state=("available" if getattr(s,"player_position_available",False) else "no current position" if getattr(s,"player_position_supported",False) else "not exposed by game")
        # Variable(s): `origin` (origin); named state retained for the surrounding calculation or subsequent calls.
        origin=("PERSISTED" if self._state_origin=="persisted" else "LIVE NATIVE" if self._state_origin=="live" else "NONE")
        # Variable(s): `freshness` (freshness); named state retained for the surrounding calculation or subsequent calls.
        freshness=("STALE" if self._state_is_stale else "CURRENT")
        self.diag_summary.set(f"Runtime: {self._runtime_state_name}   •   State: {origin} / {freshness}   •   Refresh phase: {self._refresh_phase_name}   •   Connection: {'connected' if s.connected else 'disconnected'}   •   Reachability: {'available' if getattr(s,'reachability_available',True) else 'unavailable'}   •   Events: {'available' if getattr(s,'events_available',True) else 'unavailable'}   •   Last successful logic calculation: {self._logic_age_text()}   •   Snapshot #{getattr(s,'snapshot_sequence',0) or '—'}")
        # Variable(s): `unknown_count` (unknown count); named state retained for the surrounding calculation or subsequent calls.
        unknown_count=sum(1 for x in s.locations if x.status=="unknown")
        # Variable(s): `warning_count` (warning count); named state retained for the surrounding calculation or subsequent calls.
        warning_count=len(getattr(s,"logic_warnings",[]) or [])
        self.diag_native_compare.set(
            f"Native engine: {getattr(s,'engine_version','unknown')}   •   "
            f"Reachable: {len(getattr(s,'normal_reachable_locations',[]) or [])}   •   "
            f"Regions: {len(getattr(s,'current_reachable_regions',[]) or s.in_logic_regions)}   •   "
            f"Events: {len(getattr(s,'current_events',[]) or s.events)}   •   "
            f"Unknown: {unknown_count}   •   Compatibility warnings: {warning_count}"
        )
        if hasattr(self,"diag_fields"):
            diag_values={
                "runtime":self._runtime_state_name, "state":f"{origin} / {freshness}", "refresh":self._refresh_phase_name,
                "connection":"Connected" if s.connected else "Disconnected",
                "reachability":"Available" if getattr(s,"reachability_available",True) else "Unavailable",
                "event_availability":"Available" if getattr(s,"events_available",True) else "Unavailable",
                "last_logic":self._logic_age_text(), "snapshot":f"#{getattr(s,'snapshot_sequence',0) or '—'}",
                "engine":getattr(s,"engine_version","unknown"),
                "native_reachable":str(len(getattr(s,"normal_reachable_locations",[]) or [])),
                "regions":str(len(getattr(s,"current_reachable_regions",[]) or s.in_logic_regions)),
                "events":str(len(getattr(s,"current_events",[]) or s.events)),
                "unknown":str(unknown_count), "warnings":str(warning_count),
            }
            for key,value in diag_values.items(): self.diag_fields[key].set(value)

    def _clear_game_specific_ui_state(self, old_identity, new_identity, preserve_history=False):
        """Discard selections/results that are unsafe to carry across slot/game/datapackage changes."""
        self.current_path=None
        self._active_path_request=0
        self.map_selected_location=""
        # Map selection is presentation state tied to the previous game.  The
        # Map page may be hidden (and therefore deferred) during connection, so
        # clear it here instead of waiting for the next map render.
        self.active_map_pack=None
        self.map_last_game=""
        self.map_last_runtime_target=None
        if hasattr(self,"map_selector_var"):
            self.map_selector_var.set("")
        if hasattr(self,"map_selector"):
            self.map_selector.configure(values=())
        if hasattr(self,"map_current_area"):
            self.map_current_area.set("Current area: —")
        self._stuck_recommendations=[]
        try:
            server,team,slot,game=new_identity or ("",0,"","")
            self.run_context=RunContext(server=str(server or ""),team=int(team or 0),slot=str(slot or ""),game=str(game or ""))
        except Exception:
            self.run_context=RunContext()
        self.inventory_deltas.clear()
        self.recent_changes.clear()
        if not preserve_history:
            self.history=[]; self.history_index=-1
        try:
            self.path_status.set("Choose a location to analyse.")
            self.breadcrumb_var.set("")
        except Exception:
            _ignored("intentional best-effort fallback")
        self._append_log(f"Cleared game-specific UI state for runtime identity change: {old_identity} -> {new_identity}.")

    def _startup_complete(self, stage):
        """Handle startup complete."""
        if stage not in self.startup_completed:
            self.startup_completed.add(stage)
            self._append_log(f"Startup stage complete: {stage.replace('_', ' ')}.")
        self._update_live_panel()

    def _startup_watchdog_tick(self):
        # Setup states intentionally wait for the user and must never time out.
        """Handle startup watchdog tick."""
        if self.startup_stage in {"setup_check", "setup_required", "setup_ready"}:
            self.root.after(500, self._startup_watchdog_tick)
            return
        if self.startup_stage != "ready":
            # Variable(s): `threshold` (threshold); named state retained for the surrounding calculation or subsequent calls.
            threshold = self.startup_timeout_seconds.get(self.startup_stage, 30.0)
            # Variable(s): `elapsed` (elapsed); named state retained for the surrounding calculation or subsequent calls.
            elapsed = time.monotonic() - self.startup_stage_started_at
            if elapsed >= threshold and self.startup_stage not in self.startup_timed_out:
                self.startup_timed_out.add(self.startup_stage)
                # Variable(s): `human` (human); named state retained for the surrounding calculation or subsequent calls.
                human = self._startup_stage_label()
                if self.startup_stage == 'first_snapshot' and self._ap_connection_state == 'connected':
                    phase = getattr(self, '_world_preparation_message', '') or 'preparing the first snapshot'
                    self._append_log(f'Archipelago is connected; world preparation is still running: {phase}.')
                    self._update_live_panel()
                    self.root.after(500, self._startup_watchdog_tick)
                    return
                if self.startup_stage == "waiting_ap_connection":
                    # Variable(s): `server` (server); named state retained for the surrounding calculation or subsequent calls.
                    server=self._connection_server_value().strip() if hasattr(self, "server_host_var") else ""
                    # Variable(s): `slot` (slot); named state retained for the surrounding calculation or subsequent calls.
                    slot=self.name_var.get().strip() if hasattr(self, "name_var") else ""
                    # Variable(s): `detail` (detail); named state retained for the surrounding calculation or subsequent calls.
                    detail=f"server={server or 'missing'}, slot={slot or 'missing'}"
                    self._append_log(f"Archipelago connection still pending after {threshold:.0f}s ({detail}). The native runtime is ready and will continue retrying; you can also verify the server/slot or press Connect again.")
                else:
                    self._append_log(f"WayFinder startup is still pending after {threshold:.0f}s while waiting for {human.lower()}. The runtime transport will keep retrying; no process was killed or restarted.")
                if hasattr(self, "diag_summary"):
                    self.diag_summary.set(f"Startup watchdog warning: {human} timed out after {threshold:.0f}s. See log below for the exact stalled stage.")
                self._update_live_panel()
            self.root.after(500, self._startup_watchdog_tick)

