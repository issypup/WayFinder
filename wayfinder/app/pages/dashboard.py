"""Provide dashboard support."""
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

class DashboardPageMixin:
    """Extracted callbacks that operate on WayFinderApp-owned state."""
    def _build_dashboard(self):
        """Construct the dashboard UI/data structure and attach its callbacks."""
        p=self._page("Dashboard")
        ttk.Label(p,text="Tracker Overview",style="Title.TLabel").pack(anchor="w",pady=(4,10))

        # Keep connection/session controls with the rest of the current-run information.
        connection=ttk.Frame(p,style="Card.TFrame",padding=(12,10))
        connection.pack(fill="x",pady=(0,10))
        ttk.Label(connection,text="CONNECTION",style="CardTitle.TLabel").pack(anchor="w",pady=(0,7))
        connection_row=ttk.Frame(connection,style="Card.TFrame")
        connection_row.pack(fill="x")
        for label,var,width in (("Server",self.server_host_var,24),("Port",self.server_port_var,7),("Slot",self.name_var,18),("Game",self.game_var,22)):
            ttk.Label(connection_row,text=label,style="CardMuted.TLabel").pack(side="left",padx=(0,4))
            ent=ttk.Entry(connection_row,textvariable=var,width=width,state="readonly" if label=="Game" else "normal",style="Accent.TEntry")
            ent.pack(side="left",padx=(0,10))
            if label=="Game":
                self.game_entry=ent
                ToolTip(ent,"The game is detected from the connected Archipelago slot and clears on disconnect.")
        self.connect_btn=ttk.Button(connection_row,text="Connect",style="Accent.TButton",command=self._connect_disconnect_clicked)
        self.connect_btn.pack(side="left",padx=(2,0))
        ToolTip(self.connect_btn,"Connect or disconnect the persistent WayFinder native runtime without restarting the app.")
        self.clear_saved_btn=ttk.Button(connection_row,text="Clear Saved Data for Server + Slot",style="Accent.TButton",command=self._clear_saved_connection_data)
        self.clear_saved_btn.pack(side="left",padx=(8,0))
        ToolTip(self.clear_saved_btn,"Clear WayFinder's persisted tracker state for the currently entered server and slot.")

        # PREPARING WAYFINDER provides a truthful staged view of connection and world construction.
        self.preparation_card=ttk.Frame(p,style="Card.TFrame",padding=(12,10))
        self.preparation_card.pack(fill="x",pady=(0,10))
        ttk.Label(self.preparation_card,text="PREPARING WAYFINDER",style="CardTitle.TLabel").pack(anchor="w")
        self.preparation_summary=tk.StringVar(value="Press Connect to begin world preparation.")
        ttk.Label(self.preparation_card,textvariable=self.preparation_summary,style="CardHeading.TLabel",wraplength=1050,justify="left").pack(anchor="w",pady=(4,7))
        self.preparation_progress=tk.DoubleVar(value=0.0)
        self.preparation_progressbar=ttk.Progressbar(self.preparation_card,variable=self.preparation_progress,maximum=100,mode="determinate")
        self.preparation_progressbar.pack(fill="x",pady=(0,7))
        self.preparation_stage_vars=[]
        stage_names=("Connection","Authentication","Game detection","APWorld preparation","Dependencies","Seed reconstruction","Logic","Initial state","Map","Ready")
        stage_grid=ttk.Frame(self.preparation_card,style="Card.TFrame"); stage_grid.pack(fill="x")
        for i,name in enumerate(stage_names):
            var=tk.StringVar(value=f"○ {name}")
            self.preparation_stage_vars.append(var)
            ttk.Label(stage_grid,textvariable=var,style="CardMuted.TLabel",wraplength=500,justify="left").grid(row=i//2,column=i%2,sticky="w",padx=(0,24),pady=1)
        stage_grid.columnconfigure(0,weight=1); stage_grid.columnconfigure(1,weight=1)
        self.preparation_detail=tk.StringVar(value="")
        ttk.Label(self.preparation_card,textvariable=self.preparation_detail,style="CardMuted.TLabel",wraplength=1050,justify="left").pack(anchor="w",pady=(7,0))

        lifecycle=ttk.Frame(p,style="Card.TFrame",padding=(12,10)); lifecycle.pack(fill="x",pady=(0,10))
        ttk.Label(lifecycle,text="RUN LIFECYCLE",style="CardTitle.TLabel").pack(anchor="w",pady=(0,6))
        self.dashboard_lifecycle_vars=[]
        for label in ("CONNECTED TO ARCHIPELAGO","GAME IDENTIFIED","APWORLD LOADED","SEED RECONSTRUCTED","LOGIC EVALUATED","MAP READY","TRACKING"):
            var=tk.StringVar(value=f"○ {label}")
            self.dashboard_lifecycle_vars.append(var)
            ttk.Label(lifecycle,textvariable=var,style="CardHeading.TLabel").pack(anchor="w",pady=1)

        # Primary at-a-glance KPIs.
        kpis=ttk.Frame(p); kpis.pack(fill="x",pady=(0,12))
        for title,key in [("Reachable","reach"),("Checked","checked"),("Progression","prog"),("Go-mode","go")]:
            card=ttk.Frame(kpis,style="Kpi.TFrame",padding=(14,10)); card.pack(side="left",fill="x",expand=True,padx=(0,8))
            ttk.Label(card,text=title.upper(),style="KpiLabel.TLabel").pack(anchor="w")
            ttk.Label(card,textvariable=self.stat_vars[key],style="KpiValue.TLabel").pack(anchor="w",pady=(2,0))

        # RUN OVERVIEW is intentionally structured into labelled values rather than a prose dump.
        overview=ttk.Frame(p,style="Card.TFrame",padding=(12,10)); overview.pack(fill="x",pady=(0,10))
        ttk.Label(overview,text="RUN OVERVIEW",style="CardTitle.TLabel").pack(anchor="w",pady=(0,8))
        self.dashboard_overview=tk.StringVar(value="")  # retained for compatibility with older callers
        self.dashboard_overview_vars={name:tk.StringVar(value="—") for name in (
            "game","slot","area","start","goal","compat","checks","reachable","out_logic","hints","progression","snapshot"
        )}
        overview_grid=ttk.Frame(overview,style="Card.TFrame"); overview_grid.pack(fill="x")
        for col in range(4): overview_grid.columnconfigure(col,weight=1,uniform="runoverview")
        overview_fields=(
            ("GAME","game"),("SLOT","slot"),("CURRENT AREA","area"),("STARTING AREA","start"),
            ("GOAL","goal"),("LOGIC COMPATIBILITY","compat"),("CHECKS COMPLETED","checks"),("REACHABLE","reachable"),
            ("OUT OF LOGIC","out_logic"),("HINTS","hints"),("PROGRESSION ITEMS","progression"),("LAST LOGIC SNAPSHOT","snapshot"),
        )
        for i,(label,key) in enumerate(overview_fields):
            cell=ttk.Frame(overview_grid,style="Card.TFrame",padding=(0,3))
            cell.grid(row=i//4,column=i%4,sticky="nsew",padx=(0,16),pady=(0,5))
            ttk.Label(cell,text=label,style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(cell,textvariable=self.dashboard_overview_vars[key],style="CardHeading.TLabel",wraplength=250,justify="left").pack(anchor="w",pady=(1,0))

        # LIVE + TRACKER STATUS uses a separate card so runtime health is visually distinct from run identity.
        live=ttk.Frame(p,style="Card.TFrame",padding=(12,10)); live.pack(fill="x",pady=(0,10))
        ttk.Label(live,text="LIVE + TRACKER STATUS",style="CardTitle.TLabel").pack(anchor="w",pady=(0,8))
        self.dashboard_live_status=tk.StringVar(value="")  # retained for compatibility with older callers
        self.dashboard_live_vars={name:tk.StringVar(value="—") for name in (
            "connection","startup","engine","server","logic","updated","missing","glitch","events","regions"
        )}
        live_grid=ttk.Frame(live,style="Card.TFrame"); live_grid.pack(fill="x")
        for col in range(3): live_grid.columnconfigure(col,weight=1,uniform="livestatus")
        live_fields=(
            ("CONNECTION","connection"),("STARTUP","startup"),("ENGINE","engine"),
            ("SERVER","server"),("LOGIC","logic"),("UPDATED","updated"),
        )
        for i,(label,key) in enumerate(live_fields):
            cell=ttk.Frame(live_grid,style="Card.TFrame",padding=(0,3))
            cell.grid(row=i//3,column=i%3,sticky="nsew",padx=(0,18),pady=(0,6))
            ttk.Label(cell,text=label,style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(cell,textvariable=self.dashboard_live_vars[key],style="CardHeading.TLabel",wraplength=340,justify="left").pack(anchor="w",pady=(1,0))

        ttk.Separator(live).pack(fill="x",pady=(5,7))
        tracker_metrics=ttk.Frame(live,style="Card.TFrame"); tracker_metrics.pack(fill="x")
        for col in range(4): tracker_metrics.columnconfigure(col,weight=1,uniform="trackermetric")
        for i,(label,key) in enumerate((("MISSING","missing"),("GLITCH-ONLY","glitch"),("EVENTS","events"),("REACHABLE REGIONS","regions"))):
            cell=ttk.Frame(tracker_metrics,style="Card.TFrame")
            cell.grid(row=0,column=i,sticky="ew",padx=(0,18))
            ttk.Label(cell,text=label,style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(cell,textvariable=self.dashboard_live_vars[key],style="CardHeading.TLabel").pack(anchor="w",pady=(1,0))

        run_actions=ttk.Frame(overview,style="Card.TFrame")
        run_actions.pack(fill="x",pady=(10,0))
        self.refresh_btn=ttk.Button(run_actions,text="Refresh State",style="Accent.TButton",command=self.refresh_state_clicked)
        self.refresh_btn.pack(side="left")
        ToolTip(self.refresh_btn,"Ask the WayFinder native runtime to recalculate and publish its current state.")
        ttk.Button(run_actions,text="I’m Stuck?",style="Accent.TButton",command=lambda:self.show_page("I’m Stuck?")).pack(side="right")

        goal_card=ttk.Frame(p,style="Card.TFrame",padding=10); goal_card.pack(fill="x",pady=(0,10))
        ttk.Label(goal_card,text="ROUTE-AWARE GOAL",style="CardTitle.TLabel").pack(anchor="w")
        self.goal_route_summary=tk.StringVar(value="Goal route unavailable until logic is connected.")
        ttk.Label(goal_card,textvariable=self.goal_route_summary,style="CardValue.TLabel",wraplength=1000,justify="left").pack(side="left",fill="x",expand=True,pady=(5,0))
        ttk.Button(goal_card,text="Open Goal Route",style="Accent.TButton",command=self._open_goal_route).pack(side="right",padx=(8,0))

        recent=ttk.Frame(p,style="Card.TFrame",padding=10); recent.pack(fill="both",expand=True)
        ttk.Label(recent,text="RECENT CHANGES",style="CardTitle.TLabel").pack(anchor="w",pady=(0,6))
        self.recent_tree=ttk.Treeview(recent,columns=("Time","Type","Change"),show="headings")
        for c,w in [("Time",90),("Type",110),("Change",700)]: self.recent_tree.heading(c,text=c); self.recent_tree.column(c,width=w,anchor="w")
        self.recent_tree.pack(fill="both",expand=True)

    def _replace_run_context(self, snapshot=None, *, server="", slot="", game="", team=0, seed=""):
        """Replace all transient run-owned state at an identity/seed boundary."""
        if snapshot is not None:
            server=str(getattr(snapshot,"server","") or "")
            slot=str(getattr(snapshot,"slot_name","") or "")
            game=str(getattr(snapshot,"game","") or "")
            team=int(getattr(snapshot,"team",0) or 0)
            seed=str((getattr(snapshot,"seed_identity",{}) or {}).get("id","") or "")
        self.run_context=RunContext(server=server,team=team,slot=slot,game=game,seed=seed,logic_generation=getattr(self,"_snapshot_ui_refresh_generation",0))
        return self.run_context

    def _sync_run_context_from_ui(self):
        """Mirror current transient selections into the current RunContext."""
        ctx=getattr(self,"run_context",None)
        if not ctx:return
        try: ctx.current_area=str(self._dashboard_current_area() or "")
        except Exception: _ignored("intentional best-effort fallback")
        try:
            md=self._current_map_def(); ctx.current_map=str(getattr(md,"title","") or getattr(md,"name","") or "") if md else ""
        except Exception: _ignored("intentional best-effort fallback")
        ctx.selected_check=str(getattr(self,"map_selected_location","") or "")
        ctx.route=getattr(self,"current_path",None)
        ctx.logic_generation=int(getattr(self,"_snapshot_ui_refresh_generation",0) or 0)

    def _update_dashboard_lifecycle(self):
        """Present one connected-run lifecycle instead of unrelated status labels."""
        vars_=getattr(self,"dashboard_lifecycle_vars",None)
        if not vars_:return
        s=self.snapshot; prep=dict(getattr(self,"_world_preparation_status",{}) or {})
        step=int(prep.get("step",0) or 0); state=str(prep.get("state","") or "")
        connected=bool(getattr(s,"connected",False) or self._ap_connection_state=="connected")
        game=bool(getattr(s,"game","") or prep.get("game"))
        apworld=step>=4 or bool(getattr(self,"_world_preparation_facts",{}).get("apworld"))
        seed=step>=6 or bool(getattr(self,"_world_preparation_complete",{}))
        logic=step>=8 or bool(getattr(s,"locations",[]))
        # MAP READY describes tracker/map compatibility, not whether the user has
        # visited the Map tab and caused its background image to be uploaded to Tk.
        # World preparation already performs the pack match at step 9/10.
        prep_complete=dict(getattr(self,"_world_preparation_complete",{}) or {})
        map_ready=bool(
            prep.get("map_installed", False)
            or prep_complete.get("map_installed", False)
            or (getattr(self,"active_map_pack",None) and getattr(self,"map_background_key",None))
        )
        tracking=bool(getattr(s,"connected",False) and getattr(s,"updated_at","") and not self._state_is_stale)
        done=[connected,game,apworld,seed,logic,map_ready,tracking]
        active_index=None
        if self._ap_connection_state in {"connecting","waiting_for_server"}: active_index=0
        elif connected and not game: active_index=1
        elif game and not apworld: active_index=2
        elif apworld and not seed: active_index=3
        elif seed and not logic: active_index=4
        elif logic and not map_ready and getattr(self,"active_map_pack",None): active_index=5
        elif logic and not tracking: active_index=6
        labels=("CONNECTED TO ARCHIPELAGO","GAME IDENTIFIED","APWORLD LOADED","SEED RECONSTRUCTED","LOGIC EVALUATED","MAP READY","TRACKING")
        failed=state=="failed"
        degraded=(logic and not getattr(s,"reachability_available",True)) or self._state_is_stale
        for i,(var,label) in enumerate(zip(vars_,labels)):
            marker="✓" if done[i] else "○"
            if active_index==i: marker="⟳"
            if failed and active_index==i: marker="✕"
            elif degraded and i in {4,6}: marker="!"
            if i==5 and logic and not getattr(self,"active_map_pack",None): marker="!"
            var.set(f"{marker} {label}")

    def _update_diagnostic_timings(self):
        """Handle update diagnostic timings."""
        if not hasattr(self,"diag_fields"):return
        view=dict(getattr(self,"_world_preparation_complete",{}) or getattr(self,"_world_preparation_status",{}) or {})
        timings=dict(view.get("timings",{}) or {})
        aliases={
            "time_auth":"authentication",
            "time_discovery":"apworld",
            "time_dependencies":"dependencies",
            "time_reconstruction":"reconstructing",
            "time_logic":"logic",
            "time_snapshot":"initial_state",
        }
        for key,phase in aliases.items():
            value=timings.get(phase)
            self.diag_fields[key].set(f"{float(value):.3f}s" if isinstance(value,(int,float)) else "—")
        runtime_start=getattr(self,"_timing_runtime_start_seconds",None)
        self.diag_fields["time_runtime"].set(f"{runtime_start:.3f}s" if isinstance(runtime_start,(int,float)) else "—")
        map_t=getattr(self,"_last_map_render_seconds",None); marker_t=getattr(self,"_last_marker_update_seconds",None)
        self.diag_fields["time_map"].set(f"{map_t:.3f}s" if isinstance(map_t,(int,float)) else "—")
        self.diag_fields["time_markers"].set(f"{marker_t:.3f}s" if isinstance(marker_t,(int,float)) else "—")
        calc=dict(getattr(self.snapshot,"calculation_timings_ms",{}) or {})
        if isinstance(calc.get("logic_evaluation"),(int,float)):
            self.diag_fields["time_logic"].set(f"{float(calc['logic_evaluation'])/1000.0:.3f}s")
        if isinstance(calc.get("snapshot_build"),(int,float)):
            self.diag_fields["time_snapshot"].set(f"{float(calc['snapshot_build'])/1000.0:.3f}s")
        if calc or self._map_performance_ms:
            labels=(
                ("apworld_catalog_scan","APWorld catalogue"),("apworld_import","APWorld import"),("dependency_validation","Dependency validation"),
                ("yaml_lookup","YAML lookup"),("generate_main","Generate.main"),("multiworld_construction","MultiWorld construction"),
                ("rule_reconstruction","Rule reconstruction"),("logic_evaluation","Snapshot evaluation"),("snapshot_build","Snapshot build"),
            )
            parts=[f"{label} {float(calc[key]):.1f}ms" for key,label in labels if isinstance(calc.get(key),(int,float))]
            map_labels=(("map_pack_parse","Map-pack parse"),("map_selection","Map selection"),("source_decode","Source decode"),("scale_cache","Scale/cache retrieval"),("tk_upload","Tk image upload"),("marker_generation","Marker generation"),("marker_state_update","Marker state update"))
            parts.extend(f"{label} {float(self._map_performance_ms[key]):.1f}ms" for key,label in map_labels if isinstance(self._map_performance_ms.get(key),(int,float)))
            self.diag_fields["performance_detail"].set(" • ".join(parts) if parts else "—")
        else:
            self.diag_fields["performance_detail"].set("—")

    def _prep_debug(self, source, **extra):
        """Emit compact preparation-state diagnostics to the persisted boot/latest log."""
        try:
            status=dict(getattr(self,"_world_preparation_status",{}) or {})
            complete=dict(getattr(self,"_world_preparation_complete",{}) or {})
            snap=getattr(self,"snapshot",None)
            locations=list(getattr(snap,"locations",[]) or []) if snap is not None else []
            reachable=sum(1 for x in locations if getattr(x,"status","")=="reachable")
            fields={
                "source":source,
                "runtime":str(getattr(self,"_runtime_state_name","") or ""),
                "ap":str(getattr(self,"_ap_connection_state","") or ""),
                "status":f"{status.get('state','-')}:{int(status.get('step',0) or 0)}/10",
                "complete":f"{complete.get('state','-')}:{int(complete.get('step',0) or 0)}/10",
                "snapshot_connected":bool(getattr(snap,"connected",False)),
                "snapshot_origin":str(getattr(self,"_state_origin",getattr(snap,"state_origin","") if snap else "") or ""),
                "snapshot_stale":bool(getattr(self,"_state_is_stale",getattr(snap,"stale",False) if snap else False)),
                "game":str(getattr(snap,"game","") or ""),
                "slot":str(getattr(snap,"slot_name","") or ""),
                "locations":len(locations),
                "reachable":reachable,
                "reachability_available":bool(getattr(snap,"reachability_available",True)) if snap else False,
            }
            fields.update(extra)
            signature=tuple((k,repr(v)) for k,v in fields.items())
            if source=="dashboard_render" and signature==getattr(self,"_prep_debug_last_render",None):
                return
            if source=="dashboard_render": self._prep_debug_last_render=signature
            text=" ".join(f"{k}={v!r}" for k,v in fields.items())
            self._append_log("[PREP-DEBUG] "+text, category="GUI", level="INFO")
        except Exception as exc:
            try: self._append_log(f"[PREP-DEBUG] diagnostic emission failed: {type(exc).__name__}: {exc}", category="GUI", level="WARNING")
            except Exception: pass

    def _update_preparation_panel(self):
        """Handle update preparation panel."""
        if not hasattr(self,"preparation_summary"):
            return
        status=dict(getattr(self,"_world_preparation_status",{}) or {})
        complete=dict(getattr(self,"_world_preparation_complete",{}) or {})
        if not status and not complete:
            self.preparation_summary.set("Press Connect to begin world preparation.")
            return
        view=complete if complete.get("state")=="complete" and status.get("state")!="running" else status
        step=max(0,min(10,int(view.get("step",0) or 0)))
        state=str(view.get("state","running") or "running")
        message=str(view.get("message","") or "Preparing WayFinder")
        self._prep_debug("dashboard_render", view_state=state, view_step=step, view_message=message)
        game=str(view.get("game","") or getattr(self.snapshot,"game","") or "")
        slot=str(view.get("slot","") or getattr(self.snapshot,"slot_name","") or self.name_var.get() or "")
        stage_names=("Connection","Authentication","Game detection","APWorld preparation","Dependencies","Seed reconstruction","Logic","Initial state","Map","Ready")
        for i,(name,var) in enumerate(zip(stage_names,self.preparation_stage_vars),start=1):
            if state=="failed" and i==step: marker="✕"
            elif state=="cancelled" and i==step: marker="!"
            elif i < step or (state=="complete" and i<=step): marker="✓"
            elif i==step and state=="running": marker="⟳"
            else: marker="○"
            var.set(f"{marker} {name}")
        # The preparation card represents the ten-stage WayFinder lifecycle, so
        # its progress bar must follow the live stage counter rather than the
        # per-stage progress payload (or the final completion snapshot).  The
        # latter remains 0/10 until WORLD READY and made the GUI appear stuck.
        overall_total=max(1,int(view.get("total",10) or 10))
        overall_step=max(0,min(overall_total,int(view.get("step",0) or 0)))
        self.preparation_progressbar.stop()
        self.preparation_progressbar.configure(mode="determinate")
        self.preparation_progress.set(max(0.0,min(100.0,100.0*float(overall_step)/float(overall_total))))
        identity=" • ".join(x for x in (game,slot) if x)
        if state=="complete":
            logic_quality="Exact" if view.get("exact_logic") else "Approximate"
            map_text=("Installed" if view.get("map_installed") else "Not installed")
            self.preparation_summary.set(
                f"WORLD READY\nGame {game or '—'}   •   Slot {slot or '—'}   •   Logic {logic_quality}   •   Logic source {view.get('logic_source','Unknown')}\n"
                f"APWorld Compatible   •   Locations {int(view.get('locations',0) or 0)}   •   Reachable {int(view.get('reachable',0) or 0)}   •   Map {map_text}   •   Prepared in {float(view.get('elapsed',0.0) or 0.0):.2f}s"
            )
        else:
            self.preparation_summary.set(message + (("\n" + identity) if identity else ""))
        details=[]
        details.append(f"{overall_step} / {overall_total}")
        if "duration" in view: details.append(f"This stage: {float(view['duration']):.2f}s")
        if "elapsed" in view: details.append(f"Elapsed: {float(view['elapsed']):.2f}s")
        if "cache_hit" in view:
            cache_duration=float(view.get("reconstruction_duration",0.0) or 0.0)
            details.append(("APWorld reconstruction: Loaded from seed cache" if view.get("cache_hit") else "APWorld reconstruction: Built from APWorld") + (f" {cache_duration:.2f}s" if cache_duration else ""))
        if view.get("logic_source"): details.append(f"Logic source: {view['logic_source']}")
        managed_deps=view.get("managed_dependency_count", complete.get("managed_dependency_count"))
        declared_deps=view.get("dependency_count", complete.get("dependency_count"))
        if isinstance(managed_deps,(int,float)):
            dep_text=f"Dependencies: {int(managed_deps)} managed package{'s' if int(managed_deps) != 1 else ''} available"
            if isinstance(declared_deps,(int,float)) and int(declared_deps):
                dep_text += f" • {int(declared_deps)} APWorld requirement{'s' if int(declared_deps) != 1 else ''} verified"
            details.append(dep_text)
        if complete.get("map_cache"): details.append(f"Map image: {complete['map_cache']}")
        self.preparation_detail.set(" • ".join(details))
        self._update_dashboard_lifecycle()
        self._update_diagnostic_timings()

    def _finish_world_preparation_in_gui(self, snapshot):
        """Handle finish world preparation in gui."""
        status=dict(getattr(self,"_world_preparation_status",{}) or {})
        self._prep_debug("finish_enter", incoming_connected=bool(getattr(snapshot,"connected",False)), incoming_locations=len(getattr(snapshot,"locations",[]) or []))
        if not snapshot.connected or status.get("state") == "failed":
            return
        # A live authoritative snapshot is definitive evidence that preparation
        # succeeded.  Some runtimes close the step-7 preparation task with a
        # ``cancelled`` status as snapshot syncing takes ownership; that is not
        # a failed world build and must not poison the Dashboard state machine.
        if status.get("state") == "cancelled":
            origin = str(getattr(self, "_state_origin", getattr(snapshot, "state_origin", "")) or "").casefold()
            stale = bool(getattr(self, "_state_is_stale", getattr(snapshot, "stale", False)))
            reachability = bool(getattr(snapshot, "reachability_available", True))
            if origin == "live" and not stale and reachability:
                status["state"] = "running"
                self._world_preparation_status = dict(status)
                self._prep_debug("cancelled_recovered_from_live_snapshot", recovered_step=int(status.get("step", 0) or 0))
            else:
                self._prep_debug("finish_cancelled_not_recoverable", snapshot_origin=origin, snapshot_stale=stale, reachability_available=reachability)
                return
        # The validated live snapshot is stronger evidence than the ordering of
        # world_preparation status packets.  IPC can deliver the snapshot while
        # the Dashboard still holds step 7 (Logic), so promote Initial state here
        # instead of waiting forever for a status packet that may arrive later.
        if int(status.get("step",0) or 0) < 8:
            reachable_now=len([x for x in snapshot.locations if x.status=="reachable"])
            status.update(phase="initial_state",step=8,total=10,state="running",
                          message="Tracker initial state received",progress_mode="determinate",
                          progress_current=len(snapshot.locations),progress_total=max(1,len(snapshot.locations)),
                          locations=len(snapshot.locations),reachable=reachable_now)
            self._world_preparation_status=dict(status)
            self._prep_debug("finish_initial_state", promoted_step=8)
            self._update_preparation_panel()
        live={x.name for x in snapshot.locations}
        pack,matches=self._preferred_map_pack(live,snapshot.game)
        marker_total=len(getattr(pack,"markers",[]) or []) if pack else 0
        map_message=(f"Compatible map pack: {pack.display_name}" if pack else "No compatible map pack installed — tracker remains usable")
        map_status=dict(status,phase="map",step=9,total=10,message=map_message,state="running",progress_mode="determinate",progress_current=marker_total,progress_total=max(1,marker_total),map_installed=bool(pack),map_markers=marker_total)
        self._world_preparation_status=map_status; self._prep_debug("finish_map", promoted_step=9, map_installed=bool(pack), marker_total=marker_total); self._update_preparation_panel()
        reachable=len([x for x in snapshot.locations if x.status=="reachable"])
        compatibility=getattr(snapshot,"compatibility",{}) or {}
        logic_source=str(compatibility.get("Logic source","Unknown"))
        exact_text=str(compatibility.get("Exact seed logic",""))
        exact=exact_text.startswith("Available")
        elapsed=float(status.get("elapsed",0.0) or 0.0)
        facts=dict(getattr(self,"_world_preparation_facts",{}) or {})
        final=dict(map_status)
        final.update(facts)
        final.update(phase="ready",step=10,total=10,state="complete",message=f"{reachable} locations reachable",progress_mode="determinate",progress_current=1,progress_total=1,logic_source=logic_source,exact_logic=exact,elapsed=max(elapsed,float(facts.get("elapsed",0.0) or 0.0)),map_cache=self._last_map_cache_detail,map_name=(pack.display_name if pack else "Not installed"),locations=len(snapshot.locations),reachable=reachable)
        self._world_preparation_status=final; self._world_preparation_complete=dict(final)
        self._prep_debug("finish_ready", promoted_step=10, final_state="complete")
        self._update_preparation_panel()

    def _dashboard_current_area(self):
        """Return the player's live runtime area, independent of map browsing."""
        snapshot_game=str(getattr(self.snapshot,"game","") or "").strip().casefold()
        map_game=str(getattr(self,"map_last_game","") or "").strip().casefold()
        if not snapshot_game or map_game != snapshot_game:
            return "Unknown"
        target=str(getattr(self,"map_last_runtime_target","") or "").strip()
        if target:
            return target
        # If map-title resolution fails, the fetched value from the subscribed
        # APWorld current-map DataStorage key is still authoritative player area.
        # Never substitute the manually browsed map selector here.
        key=str(getattr(self.snapshot,"map_page_setting_key","") or "").strip()
        raw=getattr(self.snapshot,"raw_map_page_datastorage_value",None)
        if key and raw is not None and not isinstance(raw,(dict,list,tuple,set)):
            value=str(raw).strip()
            if value:
                return value
        return "Unknown"

    def _refresh_dashboard_overview(self):
        """Refresh the structured dashboard overview from the latest available state."""
        self._update_dashboard_lifecycle()
        if not hasattr(self,"dashboard_overview_vars"): return
        if not bool(getattr(self, "_user_connect_requested", False)):
            self.dashboard_overview.set("")
            self.dashboard_live_status.set("")
            for var in self.dashboard_overview_vars.values(): var.set("—")
            for var in self.dashboard_live_vars.values(): var.set("—")
            return

        s=self.snapshot; locs=s.locations or []
        checked=sum(x.status=="checked" for x in locs)
        reachable=sum(x.status=="reachable" for x in locs)
        blocked=sum(x.status=="out_of_logic" for x in locs)
        hints=getattr(s,"hints",[]) or []
        reachable_hints=sum(1 for h in hints if any(x.name==h.get("location") and x.status=="reachable" for x in locs))
        prog=sum(x.count for x in s.inventory if x.progression)
        current_area=self._dashboard_current_area()
        goal=(s.goal_detail or {}); goal_status="Complete / go-mode" if goal.get("satisfied") else "Not complete"
        compat="OK" if not s.logic_warnings and not s.unsupported_state_calls else f"{len(s.logic_warnings)+len(s.unsupported_state_calls)} warning(s)"

        values={
            "game":s.game or "—", "slot":s.slot_name or "—", "area":current_area,
            "start":s.starting_location or "Unknown", "goal":goal_status, "compat":compat,
            "checks":f"{checked} / {len(locs)}", "reachable":str(reachable), "out_logic":str(blocked),
            "hints":f"{len(hints)} total • {reachable_hints} reachable", "progression":str(prog),
            "snapshot":s.updated_at or "—",
        }
        for key,value in values.items(): self.dashboard_overview_vars[key].set(value)
        self.dashboard_overview.set(" • ".join(f"{k}: {v}" for k,v in values.items()))

        def clean(prefix, text):
            """Handle clean."""
            text=str(text or "").strip()
            if text.lower().startswith(prefix.lower()+":"):
                return text.split(":",1)[1].strip()
            return text or "—"
        connection=clean("Connection", self.live_connection.get())
        if connection.startswith("● "): connection=connection[2:]
        # Preserve the aggregate tracker line for diagnostics/export compatibility while the GUI renders each value separately.
        tracker_line=(
            f"Reachable: {self.stat_vars['reach'].get()}   •   Missing: {self.stat_vars['missing'].get()}   •   "
            f"Checked: {self.stat_vars['checked'].get()}   •   Progression: {self.stat_vars['prog'].get()}   •   "
            f"Glitch-only: {self.stat_vars['glitch'].get()}   •   Events: {self.stat_vars['events'].get()}   •   "
            f"Reachable regions: {self.stat_vars['regions'].get()}   •   Go-mode: {self.stat_vars['go'].get()}"
        )
        live_values={
            "connection":connection,
            "startup":clean("Startup",self.live_startup.get()),
            "engine":clean("Engine",self.live_ut.get()),
            "server":clean("Server",self.live_server.get()),
            "logic":clean("Logic",self.live_recalc.get()).replace("\n"," • "),
            "updated":clean("Updated",self.live_updated.get()),
            "missing":self.stat_vars["missing"].get(),
            "glitch":self.stat_vars["glitch"].get(),
            "events":self.stat_vars["events"].get(),
            "regions":self.stat_vars["regions"].get(),
        }
        if self._ap_connection_message:
            live_values["connection"] += " • " + self._ap_connection_message
        for key,value in live_values.items(): self.dashboard_live_vars[key].set(value or "—")
        self.dashboard_live_status.set(" • ".join(f"{k}: {v}" for k,v in live_values.items()) + "\n" + tracker_line)

