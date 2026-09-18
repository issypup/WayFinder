"""Provide checks page support."""
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

class ChecksPageMixin:
    """Extracted callbacks that operate on WayFinderApp-owned state."""
    def _build_checks(self):
        """Build the run-oriented checks browser with quiet status styling and persistent filters."""
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        p=self._page("Checks")

        # Variable(s): `h` (height/handle value (context dependent)); named state retained for the surrounding calculation or subsequent calls.
        h=ttk.Frame(p); h.pack(fill="x",pady=(4,7))
        ttk.Label(h,text="Checks",style="Title.TLabel").pack(side="left")
        ttk.Button(h,text="Show on Map",style="Accent.TButton",command=self._show_selected_check_on_map).pack(side="left",padx=(12,0))
        ttk.Button(h,text="Path Explorer",command=self._open_selected_check).pack(side="left",padx=(6,0))
        ttk.Button(h,text="Explain Status",command=self._explain_selected_check_status).pack(side="left",padx=(6,0))

        self.check_summary=tk.StringVar(value="No checks loaded.")
        # Variable(s): `summary` (summary); named state retained for the surrounding calculation or subsequent calls.
        summary=ttk.Frame(p,style="Card.TFrame",padding=(12,9)); summary.pack(fill="x",pady=(0,7))
        ttk.Label(summary,textvariable=self.check_summary,style="CardMuted.TLabel").pack(side="left",fill="x",expand=True)

        # Variable(s): `filters` (filters); named state retained for the surrounding calculation or subsequent calls.
        filters=ttk.Frame(p,style="Card.TFrame",padding=(10,8)); filters.pack(fill="x",pady=(0,7))
        ttk.Label(filters,text="Search",style="CardMuted.TLabel").pack(side="left",padx=(0,5))
        self.check_search=tk.StringVar(value=str(self.settings.get("check_search","") or ""))
        self.check_search_entry=ttk.Entry(filters,textvariable=self.check_search,width=28,style="Accent.TEntry"); self.check_search_entry.pack(side="left",padx=(0,10))
        self.check_search.trace_add("write",lambda *_:self._refresh_checks())

        ttk.Label(filters,text="Area",style="CardMuted.TLabel").pack(side="left",padx=(0,5))
        self.check_area_box=ttk.Combobox(filters,textvariable=self.check_area,state="readonly",width=20,values=("All areas",)); self.check_area_box.pack(side="left",padx=(0,10)); self.check_area_box.bind("<<ComboboxSelected>>",lambda _e:self._refresh_checks())
        ttk.Label(filters,text="Status",style="CardMuted.TLabel").pack(side="left",padx=(0,5))
        # Variable(s): `mode` (mode); named state retained for the surrounding calculation or subsequent calls.
        mode=ttk.Combobox(filters,textvariable=self.check_mode,state="readonly",width=15,values=("All","Reachable","Blocked","Glitch","Unknown","Completed","Progression candidate","Remote dependency","Ignored")); mode.pack(side="left",padx=(0,10)); mode.bind("<<ComboboxSelected>>",lambda _e:self._refresh_checks())
        self.check_group=tk.StringVar(value=str(self.settings.get("check_group","None")))
        ttk.Label(filters,text="Group by").pack(side="left")
        grouping=ttk.Combobox(filters,textvariable=self.check_group,state="readonly",width=10,values=("None","Region","Map"));grouping.pack(side="left");grouping.bind("<<ComboboxSelected>>",lambda _e:self._refresh_checks())
        ttk.Button(filters,text="Reset",style="Accent.TButton",command=self._reset_check_filters).pack(side="right")

        # Variable(s): `toggles` (toggles); named state retained for the surrounding calculation or subsequent calls.
        toggles=ttk.Frame(p); toggles.pack(fill="x",pady=(0,7))
        ttk.Checkbutton(toggles,text="Unchecked only",variable=self.check_unchecked_only,command=self._refresh_checks).pack(side="left")
        ttk.Checkbutton(toggles,text="Hinted only",variable=self.check_hinted_only,command=self._refresh_checks).pack(side="left",padx=(12,0))
        ttk.Checkbutton(toggles,text="Progression hints only",variable=self.check_progression_only,command=self._refresh_checks).pack(side="left",padx=(12,0))
        ttk.Label(toggles,text="Location names stay neutral; status is shown in the Status column.",style="Muted.TLabel").pack(side="right")

        # Variable(s): `cols` (cols); named state retained for the surrounding calculation or subsequent calls.
        cols=("Check","Area","Status","Hint","Reason")
        self.check_tree=ttk.Treeview(p,columns=cols,show="headings",selectmode="browse",style="Emphasis.Treeview")
        # Variable(s): `widths` (widths); named state retained for the surrounding calculation or subsequent calls.
        widths=dict(self.settings.get("check_column_widths",{}) or {})
        # Variable(s): `defaults` (defaults); named state retained for the surrounding calculation or subsequent calls.
        defaults={"Check":390,"Area":220,"Status":150,"Hint":125,"Reason":420}
        self.check_sort_column=str(self.settings.get("check_sort_column","Check") or "Check")
        self.check_sort_reverse=bool(self.settings.get("check_sort_reverse",False))
        # Loop variable(s): `c` (c); each iteration represents the next value from the iterable below.
        for c in cols:
            self.check_tree.heading(c,text=c,command=lambda col=c:self._sort_checks_by(col))
            self.check_tree.column(c,width=int(widths.get(c,defaults[c])),minwidth=80,anchor="w",stretch=True)
        self.check_tree.pack(fill="both",expand=True)
        self.check_tree.bind("<Double-1>",lambda _e:self._show_selected_check_on_map())
        self.check_tree.bind("<<TreeviewSelect>>",self._check_selected)
        self.check_tree.bind("<Button-3>",self._check_context_menu)
        ToolTip(mode,"Filter by WayFinder's canonical check status. Generated checks absent from the seed are omitted rather than shown as Unknown.")

    @staticmethod
    def _status_visual(status):
        """Handle status visual."""
        return STATUS_VISUALS.get(str(status or "unknown"), STATUS_VISUALS["unknown"])

    def _check_hint_flags(self):
        # Variable(s): `flags` (flags); named state retained for the surrounding calculation or subsequent calls.
        """Handle check hint flags."""
        flags={}
        # Loop variable(s): `hint` (hint); each iteration represents the next value from the iterable below.
        for hint in (getattr(self.snapshot,"hints",[]) or []):
            # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
            name=str(hint.get("location","") or "")
            if not name: continue
            # Variable(s): `item_flags` (item flags); named state retained for the surrounding calculation or subsequent calls.
            item_flags=int(hint.get("item_flags",0) or 0)
            flags[name]={
                "progression": bool(item_flags & 1 or item_flags & 4),
                "status": str(hint.get("status","") or "").replace("_"," ").title(),
                "item": str(hint.get("item","") or ""),
            }
        return flags

    def _reset_check_filters(self):
        """Handle reset check filters."""
        self.check_search.set("")
        self.check_area.set("All areas")
        self.check_mode.set("All")
        self.check_unchecked_only.set(False)
        self.check_hinted_only.set(False)
        self.check_progression_only.set(False)
        self._refresh_checks()

    def _show_selected_check_on_map(self):
        # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
        """Handle show selected check on map."""
        name=self._selected_value(self.check_tree)
        if name: self._focus_location_on_map(name,switch_to_map=True)

    def _explain_selected_check_status(self):
        # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
        """Handle explain selected check status."""
        name=self._selected_value(self.check_tree)
        if not name: return
        # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
        loc=next((x for x in self.snapshot.locations if x.name==name),None)
        if not loc: return
        if loc.status=="unknown" and name in (getattr(self.snapshot, 'rule_details', {}) or {}):
            self._show_logic_explanation(name, False)
            return
        if loc.status=="unknown":
            # Variable(s): `reason` (reason); named state retained for the surrounding calculation or subsequent calls.
            reason=(getattr(loc,"unknown_reason","") or "WayFinder could not classify this generated check from the current native logic state.")
            ErrorHandler().show_info( f"{name}\n\nStatus: Unknown\n\nReason: {reason}", f"Unknown status — {name}")
            return
        self._show_logic_explanation(name, loc.status!="reachable")

    def _sort_checks_by(self, column):
        # First click on a new heading sorts A→Z. Repeated clicks toggle Z→A/A→Z.
        """Internal helper for sort checks by; kept private so callers use the higher-level component API."""
        if self.check_sort_column == column:
            self.check_sort_reverse = not self.check_sort_reverse
        else:
            self.check_sort_column = column
            self.check_sort_reverse = False
        self._refresh_checks()

    def _refresh_checks(self):
        """Refresh the checks browser without painting entire rows red/green."""
        if not hasattr(self,"check_tree"): return
        self._clear_tree(self.check_tree)
        # Variable(s): `mode` (mode); named state retained for the surrounding calculation or subsequent calls.
        mode=self.check_mode.get(); q=self.check_search.get().strip(); area=self.check_area.get() if hasattr(self,"check_area") else "All areas"
        # Variable(s): `mapping` (mapping); named state retained for the surrounding calculation or subsequent calls.
        progression,remote=check_evidence(self.snapshot)
        # Map coverage is presentation metadata only; the Checks list must work without an Active Map.
        group_mode=self.check_group.get() if hasattr(self,"check_group") else "None"
        coverage=self._map_coverage() if group_mode == "Map" else {"maps": {}}
        mapping={"Blocked":"out_of_logic","Glitch":"glitched","Completed":"checked","Reachable":"reachable","Glitch-only":"glitched","Out of Logic":"out_of_logic","Checked":"checked","Ignored":"ignored","Unknown":"unknown"}
        # Variable(s): `regions` (regions); named state retained for the surrounding calculation or subsequent calls.
        regions=sorted({(x.region or "Unassigned") for x in self.snapshot.locations}, key=str.casefold)
        # Variable(s): `area_values` (area values); named state retained for the surrounding calculation or subsequent calls.
        area_values=("All areas",*regions)
        if hasattr(self,"check_area_box"):
            self.check_area_box.configure(values=area_values)
            # Variable(s): `area` (area); named state retained for the surrounding calculation or subsequent calls.
            if area not in area_values: self.check_area.set("All areas"); area="All areas"

        # Variable(s): `hint_flags` (hint flags); named state retained for the surrounding calculation or subsequent calls.
        hint_flags=self._check_hint_flags()
        # Variable(s): `rows` (rows); named state retained for the surrounding calculation or subsequent calls.
        rows=[]
        # Loop variable(s): `loc` (loc); each iteration represents the next value from the iterable below.
        for loc in self.snapshot.locations:
            if mode in mapping and loc.status!=mapping[mode]:continue
            if mode=="Progression candidate" and (loc.name not in progression or loc.status=="checked"):continue
            if mode=="Remote dependency" and (loc.name not in remote or loc.status=="checked"):continue
            # Variable(s): `loc_area` (loc area); named state retained for the surrounding calculation or subsequent calls.
            loc_area=(loc.region or "Unassigned")
            if area!="All areas" and loc_area!=area: continue
            if mode not in {"Completed","Checked"} and self.check_unchecked_only.get() and loc.status=="checked": continue
            # Variable(s): `h` (height/handle value (context dependent)); named state retained for the surrounding calculation or subsequent calls.
            h=hint_flags.get(loc.name,{})
            if self.check_hinted_only.get() and not loc.hinted: continue
            if self.check_progression_only.get() and not h.get("progression",False): continue
            # Variable(s): `searchable` (searchable); named state retained for the surrounding calculation or subsequent calls.
            searchable=f"{loc.name} {loc_area} {loc.status} {getattr(loc,'unknown_reason','')} {h.get('item','')} {h.get('status','')}"
            if q and not self._fuzzy_match(q,searchable): continue
            # Variable(s): `visual` (visual); named state retained for the surrounding calculation or subsequent calls.
            visual=self._status_visual(loc.status)
            # Variable(s): `status_text` (status text); named state retained for the surrounding calculation or subsequent calls.
            status_text=f"{visual['symbol']}  {visual['label']}"
            # Variable(s): `hint_text` (hint text); named state retained for the surrounding calculation or subsequent calls.
            hint_text=""
            if loc.hinted:
                # Variable(s): `hint_text` (hint text); named state retained for the surrounding calculation or subsequent calls.
                hint_text=("★ Progression" if h.get("progression") else "★ Hinted")
                if h.get("status"): hint_text+=f" · {h['status']}"
            # Variable(s): `reason` (reason); named state retained for the surrounding calculation or subsequent calls.
            reason=getattr(loc,"unknown_reason","") if loc.status=="unknown" else ""
            detail = (getattr(self.snapshot, 'rule_details', {}) or {}).get(loc.name, {})
            if not reason and detail.get('impossible_rule'):
                reason = 'Impossible local rule: contradictory or constant-false requirements.' 
            rows.append((loc.name,loc_area,status_text,hint_text,reason,loc.status))

        # Variable(s): `indexes` (indexes); named state retained for the surrounding calculation or subsequent calls.
        indexes={"Check":0,"Area":1,"Status":2,"Hint":3,"Reason":4}
        # Variable(s): `idx` (index); named state retained for the surrounding calculation or subsequent calls.
        idx=indexes.get(self.check_sort_column,0)
        rows.sort(key=lambda row:(str(row[idx]).casefold(),str(row[0]).casefold()),reverse=self.check_sort_reverse)
        # Loop variable(s): `c` (c); each iteration represents the next value from the iterable below.
        for c in ("Check","Area","Status","Hint","Reason"):
            # Variable(s): `arrow` (arrow); named state retained for the surrounding calculation or subsequent calls.
            arrow=(" ▼" if self.check_sort_reverse else " ▲") if c==self.check_sort_column else ""
            self.check_tree.heading(c,text=c+arrow,command=lambda col=c:self._sort_checks_by(col))
        # Loop variable(s): `row` (row); each iteration represents the next value from the iterable below.
        self.check_tree.configure(show="tree headings" if group_mode!="None" else "headings")
        self.check_tree.heading("#0",text=group_mode if group_mode!="None" else "")
        self.check_tree.column("#0",width=210,stretch=False)
        groups={}
        for row in rows:
            names=coverage['maps'].get(row[0],['Unmapped']) if group_mode=="Map" else [row[1]] if group_mode=="Region" else ['']
            for group in names:
                if group and group not in groups:groups[group]=self.check_tree.insert("","end",text=group,open=True,tags=("group",))
                self.check_tree.insert(groups.get(group,""),"end",values=row[:5])

        # Variable(s): `total` (total); named state retained for the surrounding calculation or subsequent calls.
        total=len(self.snapshot.locations)
        visible=len(rows)
        filtered_status=[row[5] for row in rows]
        checked=filtered_status.count("checked")
        reachable=filtered_status.count("reachable")
        blocked=filtered_status.count("out_of_logic")
        unknown=filtered_status.count("unknown")
        untracked=filtered_status.count("non_progression")
        glitched=filtered_status.count("glitched")
        if hasattr(self,"check_summary"):
            prefix=f"{visible} locations" if visible==total else f"{visible} of {total} locations"
            self.check_summary.set(f"{prefix}   ✓ {checked} checked   ● {reachable} reachable   ● {blocked} blocked   ? {unknown} unknown   ○ {untracked} untracked" + (f"   ◇ {glitched} glitch-only" if glitched else ""))

    def _refresh_ignored(self):
        # Ignored state remains available through the Checks filter/context menu; no dedicated Manage page.
        """Recompute and redraw the ignored view from the current application state."""
        return

    def _check_selected(self,_e=None):
        """Internal helper for check selected; kept private so callers use the higher-level component API."""
        # Variable(s): `n` (n); named state retained for the surrounding calculation or subsequent calls.
        n=self._selected_value(self.check_tree)
        if n and hasattr(self,"path_var"): self.path_var.set(n)
        if n:
            self.map_selected_location=n
            if hasattr(self,"map_canvas"): self._refresh_map_markers()

    def _open_selected_check(self,_e=None):
        """Internal helper for open selected check; kept private so callers use the higher-level component API."""
        # Variable(s): `n` (n); named state retained for the surrounding calculation or subsequent calls.
        n=self._selected_value(self.check_tree); self.open_path(n) if n else None

    def _check_context_menu(self,event):
        """Context actions keep Checks, Map, Path Explorer and diagnostics linked."""
        # Variable(s): `row` (row); named state retained for the surrounding calculation or subsequent calls.
        row=self.check_tree.identify_row(event.y)
        if not row:return
        # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
        self.check_tree.selection_set(row); name=self._selected_value(self.check_tree)
        if not name:return
        # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
        loc=next((x for x in self.snapshot.locations if x.name==name),None)
        # Variable(s): `menu` (menu); named state retained for the surrounding calculation or subsequent calls.
        menu=tk.Menu(self.root,tearoff=False)
        menu.add_command(label="Show on Map",command=lambda:self._focus_location_on_map(name,switch_to_map=True))
        menu.add_command(label="Open in Path Explorer",command=lambda:self.open_path(name))
        menu.add_command(label="Explain Status",command=self._explain_selected_check_status)
        menu.add_separator()
        menu.add_command(label="Copy location name",command=lambda:(self.root.clipboard_clear(),self.root.clipboard_append(name)))
        menu.add_command(label="Personal note",command=lambda:self._personal_note(name))
        menu.add_separator()
        menu.add_command(label="Unignore" if loc and loc.ignored else "Ignore",command=(lambda:self._set_location_ignored(name,False)) if loc and loc.ignored else (lambda:self._set_location_ignored(name,True)))
        menu.tk_popup(event.x_root,event.y_root)

