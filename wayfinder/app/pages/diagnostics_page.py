"""Provide diagnostics page support."""
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
from wayfinder import __version__
GUI_VERSION = __version__

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

class DiagnosticsPageMixin:
    """Extracted callbacks that operate on WayFinderApp-owned state."""
    def _build_diagnostics(self):
        """Build diagnostics for the WayFinder native runtime."""
        p=self._page("Diagnostics")
        h=ttk.Frame(p); h.pack(fill="x",pady=(4,8))
        ttk.Label(h,text="Diagnostics / Error Console",style="Title.TLabel").pack(side="left")
        ttk.Button(h,text="Copy Log",style="Accent.TButton",command=self.copy_log).pack(side="right")
        ttk.Button(h,text="Clear",style="Accent.TButton",command=self.clear_log).pack(side="right",padx=5)

        # Legacy aggregate strings are retained for compatibility; the visible UI below uses
        # dedicated values so each diagnostic has a stable place and label.
        self.diag_validation=tk.StringVar(value="Map-pack validation: not run")
        self.diag_summary=tk.StringVar(value="Runtime: not started")
        self.diag_versions=tk.StringVar(value=f"WayFinder Engine: unknown   •   WayFinder: {GUI_VERSION}   •   Archipelago core: unknown")
        self.diag_runtime=tk.StringVar(value=f"Runtime source: {os.environ.get('WAYFINDER_RUNTIME_SOURCE','bundled/unknown')}   •   Target game: {os.environ.get('WAYFINDER_TARGET_GAME','unknown')}")
        self.diag_runtime_log=tk.StringVar(value=f"WayFinder debug log: {os.environ.get('WAYFINDER_DEBUG_LOG', str(Path.home() / 'WayFinder-debug.log'))}")
        self.diag_startup=tk.StringVar(value="Startup: Setup ready; waiting for Connect")
        self.diag_native_compare=tk.StringVar(value="Native engine: not started")
        self.diag_fields={name:tk.StringVar(value="—") for name in (
            "runtime","state","refresh","connection","reachability","event_availability","last_logic","snapshot",
            "engine","native_reachable","regions","events","unknown","warnings",
            "apworld_game","apworld_generator","apworld_state",
            "wayfinder","ap_core","runtime_source","target_game","ui_link","validation","debug_log","startup",
            "time_runtime","time_auth","time_discovery","time_dependencies","time_reconstruction","time_logic","time_snapshot","time_map","time_markers","performance_detail"
        )}

        status_card=ttk.Frame(p,style="Card.TFrame",padding=(12,10)); status_card.pack(fill="x",pady=(0,8))
        ttk.Label(status_card,text="RUNTIME + LOGIC STATUS",style="CardTitle.TLabel").pack(anchor="w",pady=(0,8))

        def section(title, fields, columns=4):
            """Handle section."""
            ttk.Label(status_card,text=title,style="CardHeading.TLabel").pack(anchor="w",pady=(4,4))
            grid=ttk.Frame(status_card,style="Card.TFrame"); grid.pack(fill="x",pady=(0,5))
            for col in range(columns): grid.columnconfigure(col,weight=1,uniform=title)
            for i,(label,key) in enumerate(fields):
                cell=ttk.Frame(grid,style="Card.TFrame",padding=(0,2))
                cell.grid(row=i//columns,column=i%columns,sticky="nsew",padx=(0,16),pady=(0,4))
                ttk.Label(cell,text=label,style="CardTitle.TLabel").pack(anchor="w")
                ttk.Label(cell,textvariable=self.diag_fields[key],style="CardHeading.TLabel",wraplength=255,justify="left").pack(anchor="w",pady=(1,0))

        section("Runtime",(("RUNTIME STATE","runtime"),("STATE SOURCE","state"),("REFRESH PHASE","refresh"),("CONNECTION","connection"),
                           ("REACHABILITY","reachability"),("EVENT DATA","event_availability"),("LAST SUCCESSFUL LOGIC","last_logic"),("SNAPSHOT","snapshot")))
        ttk.Separator(status_card).pack(fill="x",pady=(2,5))
        section("Native logic engine",(("ENGINE VERSION","engine"),("REACHABLE","native_reachable"),("REGIONS","regions"),("EVENTS","events"),
                                       ("UNKNOWN","unknown"),("COMPATIBILITY WARNINGS","warnings")),columns=3)
        ttk.Separator(status_card).pack(fill="x",pady=(2,5))
        section("APWorld", (("GAME", "apworld_game"), ("GENERATED BY", "apworld_generator"), ("WORLD / LOGIC STATE", "apworld_state")), columns=3)
        ttk.Separator(status_card).pack(fill="x",pady=(2,5))
        section("Performance timings",(("RUNTIME STARTUP","time_runtime"),("AP AUTHENTICATION","time_auth"),("APWORLD DISCOVERY","time_discovery"),
                                       ("DEPENDENCY CHECK","time_dependencies"),("WORLD RECONSTRUCTION","time_reconstruction"),("LOGIC EVALUATION","time_logic"),
                                       ("SNAPSHOT BUILD","time_snapshot"),("MAP IMAGE LOAD","time_map"),("MARKER UPDATE","time_markers")),columns=3)
        perf_detail=ttk.Frame(status_card,style="Card.TFrame"); perf_detail.pack(fill="x",pady=(0,5))
        ttk.Label(perf_detail,text="DETAILED PIPELINE",style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(perf_detail,textvariable=self.diag_fields["performance_detail"],style="CardMuted.TLabel",wraplength=940,justify="left").pack(anchor="w",pady=(2,0))
        section("Environment",(("WAYFINDER","wayfinder"),("ARCHIPELAGO CORE","ap_core"),("RUNTIME SOURCE","runtime_source"),
                               ("TARGET GAME","target_game"),("INTERNAL UI LINK","ui_link")),columns=3)

        details=ttk.Frame(status_card,style="Card.TFrame"); details.pack(fill="x",pady=(4,0)); details.columnconfigure(1,weight=1)
        for row,(label,key) in enumerate((("MAP-PACK VALIDATION","validation"),("DEBUG LOG","debug_log"),("STARTUP PROGRESS","startup"))):
            ttk.Label(details,text=label,style="CardTitle.TLabel").grid(row=row,column=0,sticky="nw",padx=(0,14),pady=3)
            ttk.Label(details,textvariable=self.diag_fields[key],style="CardMuted.TLabel",wraplength=900,justify="left").grid(row=row,column=1,sticky="w",pady=3)

        health=ttk.Frame(p,style="Card.TFrame",padding=10); health.pack(fill="x",pady=(0,8))
        ttk.Label(health,text="COMPONENT STATUS • Green: ready • Amber: waiting / degraded • Red: failed",style="CardTitle.TLabel").pack(anchor="w")
        self.component_labels = {}
        row=ttk.Frame(health,style="Card.TFrame"); row.pack(fill="x")
        for i, name in enumerate(CATEGORIES):
            label=ttk.Label(row,text=f"● {name}: waiting",wraplength=240)
            label.grid(row=i//4,column=i%4,sticky="w",padx=8,pady=5)
            row.columnconfigure(i%4,weight=1)
            self.component_labels[name]=label
        errors=ttk.Frame(p,style="Card.TFrame",padding=10); errors.pack(fill="x",pady=(0,8))
        ttk.Label(errors,text="RECENT ERRORS • Latest 50",style="CardTitle.TLabel").pack(anchor="w")
        self.recent_errors_text=tk.Text(errors,height=5,wrap="word",bg=self._palette()["panel"],fg=self._palette()["fg"])
        self.recent_errors_text.pack(fill="x")
        self._refresh_recent_errors()
        self._refresh_component_diagnostics()
        console_card=ttk.Frame(p,style="Card.TFrame",padding=8); console_card.pack(fill="both",expand=True)
        ttk.Label(console_card,text="DIAGNOSTIC CONSOLE",style="CardTitle.TLabel").pack(anchor="w",pady=(0,6))
        self.log_text=tk.Text(console_card,bg=self._palette()["panel"],fg=self._palette()["fg"],insertbackground=self._palette()["fg"],relief="flat",wrap="word",font="WayFinderBody",highlightthickness=1,highlightbackground=self._palette()["accent"],highlightcolor=self._palette()["accent_hover"],padx=8,pady=8)
        self.log_text.pack(fill="both",expand=True)
        self._configure_log_tags(self.log_text)
        self.log_text.configure(state="disabled")

    def _refresh_recent_errors(self):
        """Handle refresh recent errors."""
        if not hasattr(self, "recent_errors_text"):
            return
        widget=self.recent_errors_text
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        records=getattr(self,"recent_errors",[])
        widget.insert("end", "\n".join(format_record(r) for r in reversed(records)) or "No recent errors.")
        widget.configure(state="disabled")

    def _refresh_component_diagnostics(self):
        # Hidden diagnostics used to keep doing disk/log scans and widget updates every
        # second.  On Tk this competes with pointer/hover events even when the page
        # is not visible.  Keep hidden-page maintenance lightweight.
        """Handle refresh component diagnostics."""
        if getattr(self, "current_page", None) != "Diagnostics":
            self.root.after(5000, self._refresh_component_diagnostics)
            return
        if getattr(self,"_closing",False) or not hasattr(self,"component_labels"):
            return
        s=self.snapshot
        runtime=str(getattr(self,"_runtime_state_name","idle"))
        connected=bool(s.connected) or getattr(self, '_ap_connection_state', '') == 'connected'
        live=connected and getattr(self,"_state_origin","")=="live"
        logic=live and bool(getattr(s,"reachability_available",False))
        def state(ok, detail, failed=False):
            """Handle state."""
            return ("#d94b4b" if failed else "#2c9b68" if ok else "#d28a28", detail)
        values={
            "RUNTIME":state((getattr(self,"startup_stage","")=="ready" or runtime.lower() in ("ready","connected","running","live")),runtime,any(x in runtime.lower() for x in ("fail","error","crash"))),
            "AP":state(connected,"Connected" if connected else "Disconnected"),
            "LOGIC":state(logic,"Available" if logic else "Waiting / unavailable"),
            "MAP":state(bool(getattr(self,"active_map_pack",None)),"Loaded" if getattr(self,"active_map_pack",None) else "No active pack"),
            "APWORLD":state(logic,"World built" if logic else "Waiting for world"),
            "DEPENDENCY":state(False,"Not checked"),
            "SNAPSHOT":state(live,"Live" if live else "Waiting / cached"),
            "GUI":state(True,"Responsive"),
        }
        # Installer completion/failure is more informative than guessing readiness.
        dep=next((r for r in reversed(getattr(self,"log_records",[])) if r["category"]=="DEPENDENCY"),None)
        report = setup_backend.load_dependency_report(setup_backend.DEPENDENCY_REPORT)
        results = report.get("results", [])
        if results:
            failed = any(item.get("status") == "failed" for item in results)
            values["DEPENDENCY"] = state(report.get("install_success") is True,"Installation failed" if failed else "Installed" if report.get("install_success") is True else "Incomplete",failed)
        if dep and dep["level"] == "ERROR":
            values["DEPENDENCY"]=state("complete" in dep["message"].lower() or "success" in dep["message"].lower(),dep["level"].title(),dep["level"]=="ERROR")
        for name in CATEGORIES:
            latest=next((r for r in reversed(getattr(self,"log_records",[])) if r["category"]==name),None)
            if latest and latest["level"]=="ERROR":
                values[name]=state(False,"Recent error — see below",True)
        for name,(color,detail) in values.items():
            self.component_labels[name].configure(text=sanitize(f"● {name}: {detail}"),foreground=color)
        self.diag_fields["apworld_game"].set(sanitize(s.game or "Not selected"))
        self.diag_fields["apworld_generator"].set(sanitize(str(getattr(self,"runtime_apworld_generated_by","unknown"))))
        self.diag_fields["apworld_state"].set("World built / logic available" if logic else "Waiting for live world / logic")
        self.root.after(1000,self._refresh_component_diagnostics)

    def _build_compatibility(self):
        """Show only compatibility checks relevant to the merged runtime."""
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        p=self._page("APWorld Compatibility")
        ttk.Label(p,text="APWorld Compatibility",style="Title.TLabel").pack(anchor="w",pady=(4,8))
        self.compat_summary=tk.StringVar(value="Waiting for the native runtime and first live snapshot.")
        ttk.Label(p,textvariable=self.compat_summary,style="Muted.TLabel",wraplength=1000,justify="left").pack(anchor="w",pady=(0,8))
        self.compat_world_summary=tk.StringVar(value="No connected APWorld yet.")
        ttk.Label(p,textvariable=self.compat_world_summary,style="CardHeading.TLabel",wraplength=1000,justify="left").pack(anchor="w",pady=(0,8))
        self.compat_tree=ttk.Treeview(p,columns=("Hook","Status"),show="headings")
        self.compat_tree.heading("Hook",text="Capability")
        self.compat_tree.heading("Status",text="Status")
        self.compat_tree.column("Hook",width=520,anchor="w")
        self.compat_tree.column("Status",width=420,anchor="w")
        self.compat_tree.pack(fill="both",expand=True)
        why=ttk.Frame(p,style="Card.TFrame",padding=(10,8)); why.pack(fill="x",pady=(8,0))
        ttk.Label(why,text="WHY ISN'T THIS FULL COMPATIBILITY?",style="CardTitle.TLabel").pack(anchor="w")
        self.compat_missing=tk.StringVar(value="Waiting for a connected world.")
        ttk.Label(why,textvariable=self.compat_missing,style="CardMuted.TLabel",wraplength=1000,justify="left").pack(anchor="w",pady=(4,0))
        # Variable(s): `actions` (actions); named state retained for the surrounding calculation or subsequent calls.
        actions=ttk.Frame(p); actions.pack(fill="x",pady=(6,0)); ttk.Button(actions,style="Accent.TButton",text="Copy Compatibility Report",command=self._copy_compat_report).pack(side="left"); ttk.Button(actions,style="Accent.TButton",text="Save Diagnostic Bundle…",command=self._save_diagnostic_bundle).pack(side="left",padx=6); ttk.Button(actions,style="Accent.TButton",text="DataStorage Index…",command=self._show_datastorage_index).pack(side="left")
        ttk.Label(actions,text="DataStorage values are never serialized here; only key/type/size metadata is included.",style="Muted.TLabel").pack(side="right")
        self._refresh_compatibility()

    def _copy_compat_report(self):
        # Variable(s): `lines` (lines); named state retained for the surrounding calculation or subsequent calls.
        """Handle copy compat report."""
        lines=[f"WayFinder {GUI_VERSION} — {self.snapshot.game} / {self.snapshot.slot_name}"]
        lines += [f"{k}: {v}" for k,v in (self.snapshot.compatibility or {}).items()]
        lines += [f"DataStorage: {x.get('key')} [{x.get('type')}, size={x.get('size')}]" for x in (self.snapshot.datastorage_index or [])]
        self.root.clipboard_clear(); self.root.clipboard_append(sanitize("\n".join(lines)))

    def _save_diagnostic_bundle(self):
        # Variable(s): `path` (path); named state retained for the surrounding calculation or subsequent calls.
        """Handle save diagnostic bundle."""
        path=filedialog.asksaveasfilename(title="Save WayFinder diagnostic bundle",defaultextension=".json",filetypes=[("JSON","*.json")],initialfile=f"WayFinder-{self.snapshot.game or 'diagnostic'}.json")
        if not path:return
        # Variable(s): `safe` (safe); named state retained for the surrounding calculation or subsequent calls.
        safe={"wayfinder_version":GUI_VERSION,"game":self.snapshot.game,"slot":self.snapshot.slot_name,"updated_at":self.snapshot.updated_at,"compatibility":self.snapshot.compatibility,"logic_warnings":self.snapshot.logic_warnings,"unsupported_state_calls":self.snapshot.unsupported_state_calls,"goal_detail":self.snapshot.goal_detail,"entrance_details":self.snapshot.entrance_details,"event_details":self.snapshot.event_details,"rule_details":self.snapshot.rule_details,"datastorage_index":self.snapshot.datastorage_index}
        Path(path).write_text(json.dumps(sanitize(dict(safe, logs=getattr(self,"log_records",[]), recent_errors=getattr(self,"recent_errors",[]))),indent=2,ensure_ascii=False),encoding="utf-8")

    def _refresh_compatibility(self):
        """Refresh connected-world APWorld compatibility with actionable capability detail."""
        if not hasattr(self,"compat_tree"):
            return
        s=self.snapshot
        live_hooks=dict(getattr(s,"compatibility",{}) or {})
        facts=dict(getattr(self,"_world_preparation_facts",{}) or {})
        context_live=bool(s.updated_at or s.connected or live_hooks)
        snapshot_live=bool(s.updated_at and s.locations)
        game=str(s.game or facts.get("game") or "—")
        source=str(facts.get("apworld_path") or facts.get("apworld") or "Waiting for APWorld")
        version=str(facts.get("apworld_version") or "Not declared")
        identification=str(facts.get("identification") or "Not reported")
        dep_count=facts.get("dependency_count")
        managed_dep_count=facts.get("managed_dependency_count")
        if isinstance(managed_dep_count,(int,float)):
            declared = int(dep_count) if isinstance(dep_count,(int,float)) else 0
            dep_status = f"✓ {int(managed_dep_count)} managed packages available"
            if declared:
                dep_status += f" • {declared} APWorld requirement{'s' if declared != 1 else ''} verified"
            else:
                dep_status += " • no APWorld-specific requirements"
        elif isinstance(dep_count,(int,float)):
            dep_status = (f"✓ {int(dep_count)} APWorld requirement{'s' if int(dep_count) != 1 else ''} verified"
                          if int(dep_count) else "✓ No APWorld-specific dependencies required")
        else:
            dep_status="Waiting for dependency report"
        exact_status=str(live_hooks.get("Exact seed logic","Waiting for live snapshot"))
        logic_source=str(live_hooks.get("Logic source",facts.get("logic_source") or "Waiting"))
        reconstruction=("✓ Supported" if exact_status.startswith("Available") else "! Approximate" if exact_status.startswith("Unavailable") else "○ Waiting")
        map_support=str(live_hooks.get("Live map switching","Not reported"))
        position_support=str(live_hooks.get("Live player position","Not reported"))
        entrance_support=str(live_hooks.get("Entrance tracking","Not reported"))
        reachable_support=str(live_hooks.get("Reachable locations","Not reported"))
        critical_missing=[]
        if exact_status.startswith("Unavailable"): critical_missing.append("authoritative seed reconstruction")
        if str(reachable_support).casefold().startswith(("unavailable","not reported","waiting")): critical_missing.append("reachable-location logic")
        if not context_live: critical_missing.append("live runtime context")
        compatibility_level="FULL" if not critical_missing and snapshot_live else "PARTIAL" if context_live else "WAITING"

        if hasattr(self,"compat_world_summary"):
            self.compat_world_summary.set(
                f"APWorld {game}\nSource {source}   •   Version {version}   •   Identification {identification}\n"
                f"Dependencies {dep_status}   •   Reconstruction {reconstruction}   •   Logic source {logic_source}   •   Compatibility {compatibility_level}"
            )
        if hasattr(self,"compat_missing"):
            self.compat_missing.set("Nothing critical is missing. Optional capabilities may still be unexposed by the APWorld." if not critical_missing else "Missing: " + "; ".join(critical_missing) + ".")

        rows={
            "APWorld": game,
            "Source": source,
            "Version": version,
            "Identification": identification,
            "Dependencies": dep_status,
            "Reconstruction": reconstruction,
            "Logic source": logic_source,
            "Live map support": ("✓ "+map_support if map_support.startswith("Supported") else "○ "+map_support),
            "Player position support": ("✓ "+position_support if position_support.startswith("Supported") else "○ "+position_support),
            "Entrance metadata": ("✓ "+entrance_support if not entrance_support.startswith(("Not","Waiting","Unavailable")) else "○ "+entrance_support),
            "Compatibility": compatibility_level,
            "Runtime source": os.environ.get("WAYFINDER_RUNTIME_SOURCE","bundled/unknown"),
            "Native engine version": (s.engine_version if s.engine_version!="unknown" else self.runtime_engine_version),
            "Live logic snapshot": ("Live" if snapshot_live and not self._state_is_stale else "Stale / previous valid snapshot" if self._state_is_stale else "Waiting"),
        }
        hook_names=[
            "Current world","CollectionState","Logic YAML","Exact seed logic","Reachable locations","Reachable regions",
            "Events","Glitch-only logic","Manual items","Ignored locations","Logical path data","Native explanation API",
            "Structured rule objects","Live map switching","Live player position","Hints DataStorage","Entrance tracking",
            "Location groups","Item groups","Goal detection","Unsupported CollectionState APIs",
        ]
        for name in hook_names:
            if name not in rows:
                rows[name]=live_hooks.get(name,"Waiting for live snapshot" if not context_live else "Not reported")
        self._clear_tree(self.compat_tree)
        for name,status in rows.items():
            self.compat_tree.insert("","end",values=(name,status))
        self.compat_summary.set(f"WayFinder {GUI_VERSION} • {game} • Compatibility {compatibility_level}. Capability rows below come from the connected APWorld/runtime, not a generic game profile.")

