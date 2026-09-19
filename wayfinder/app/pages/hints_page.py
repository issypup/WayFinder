"""Provide hints page support."""
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

class HintsPageMixin:
    """Extracted callbacks that operate on WayFinderApp-owned state."""
    def _build_search_hints_inventory(self):
        """Combined Search / Hints / Inventory workspace for tracker discovery."""
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        p=self._page("Search, Hints & Inventory")
        ttk.Label(p,text="Search, Hints & Inventory",style="Title.TLabel").pack(anchor="w",pady=(4,8))
        # Variable(s): `nb` (nb); named state retained for the surrounding calculation or subsequent calls.
        nb=ttk.Notebook(p); nb.pack(fill="both",expand=True)

        # Variable(s): `search` (search); named state retained for the surrounding calculation or subsequent calls.
        search=ttk.Frame(nb); hints=ttk.Frame(nb); inv=ttk.Frame(nb)
        nb.add(search,text="Search"); nb.add(hints,text="Hints"); nb.add(inv,text="Inventory")
        self.shi_notebook=nb

        # Variable(s): `sr` (sr); named state retained for the surrounding calculation or subsequent calls.
        sr=ttk.Frame(search); sr.pack(fill="x",padx=8,pady=8)
        self.shi_search_var=tk.StringVar()
        # Variable(s): `se` (se); named state retained for the surrounding calculation or subsequent calls.
        se=ttk.Entry(sr,textvariable=self.shi_search_var); se.pack(side="left",fill="x",expand=True)
        se.bind("<Return>",lambda _e:self._run_combined_search())
        ttk.Button(sr,text="Search",style="Accent.TButton",command=self._run_combined_search).pack(side="left",padx=(8,0))
        ttk.Button(sr,text="Clear",command=lambda:(self.shi_search_var.set(""),self._clear_tree(self.shi_search_tree))).pack(side="left",padx=(4,0))
        ttk.Label(search,text="Supports fuzzy names and expressions such as Key >= 2, reachable, and region:cave.",style="Muted.TLabel").pack(anchor="w",padx=8,pady=(0,8))
        self.shi_search_tree=ttk.Treeview(search,columns=("Type","Name","Details"),show="headings")
        # Loop variable(s): `c` (c), `w` (width/widget value (context dependent)); each iteration represents the next value from the iterable below.
        for c,w in [("Type",120),("Name",470),("Details",410)]: self.shi_search_tree.heading(c,text=c); self.shi_search_tree.column(c,width=w,anchor="w")
        self.shi_search_tree.pack(fill="both",expand=True,padx=8,pady=(0,8)); self.shi_search_tree.bind("<Double-1>",self._open_combined_search_result)

        # Variable(s): `hf` (hf); named state retained for the surrounding calculation or subsequent calls.
        hf=ttk.Frame(hints); hf.pack(fill="x",padx=8,pady=8)
        # Variable(s): `he` (he); named state retained for the surrounding calculation or subsequent calls.
        self.hint_filter=tk.StringVar(); he=ttk.Entry(hf,textvariable=self.hint_filter); he.pack(side="left",fill="x",expand=True); he.bind("<KeyRelease>",lambda _e:self._refresh_hints())
        # Variable(s): `hm` (hm); named state retained for the surrounding calculation or subsequent calls.
        self.hint_mode=tk.StringVar(value="All"); hm=ttk.Combobox(hf,textvariable=self.hint_mode,state="readonly",width=18,values=("All","Unfound","Found","Reachable","Progression","Priority")); hm.pack(side="left",padx=(8,0)); hm.bind("<<ComboboxSelected>>",lambda _e:self._refresh_hints())
        ttk.Label(hf,text="Filter hints",style="Muted.TLabel").pack(side="left",padx=(8,0))
        self.hint_tree=ttk.Treeview(hints,columns=("Item","Player","Location","Finder","Status"),show="headings")
        # Loop variable(s): `c` (c), `w` (width/widget value (context dependent)); each iteration represents the next value from the iterable below.
        for c,w in [("Item",250),("Player",170),("Location",300),("Finder",170),("Status",110)]: self.hint_tree.heading(c,text=c); self.hint_tree.column(c,width=w,anchor="w")
        self.hint_tree.pack(fill="both",expand=True,padx=8,pady=(0,8)); self.hint_tree.bind("<Double-1>",self._hint_open_path); self.hint_tree.bind("<Button-3>",self._hint_context_menu); self.hint_tree.tag_configure("new_hint",foreground=self._palette()["success"],font="WayFinderSemibold"); self.hint_tree.tag_configure("changed_hint",foreground=self._palette()["warning"])
        self.hint_detail=tk.StringVar(value="Select a hint to see its details."); ttk.Label(hints,textvariable=self.hint_detail,style="Muted.TLabel",wraplength=980).pack(anchor="w",padx=8,pady=(0,8)); self.hint_tree.bind("<<TreeviewSelect>>",self._hint_selected)

        # Variable(s): `ir` (ir); named state retained for the surrounding calculation or subsequent calls.
        ir=ttk.Frame(inv); ir.pack(fill="x",padx=8,pady=8)
        # Variable(s): `ie` (ie); named state retained for the surrounding calculation or subsequent calls.
        self.shi_inv_search=tk.StringVar(); ie=ttk.Entry(ir,textvariable=self.shi_inv_search); ie.pack(side="left",fill="x",expand=True); ie.bind("<KeyRelease>",lambda _e:self._refresh_combined_inventory())
        # Variable(s): `im` (im); named state retained for the surrounding calculation or subsequent calls.
        self.shi_inventory_mode=tk.StringVar(value="All"); im=ttk.Combobox(ir,textvariable=self.shi_inventory_mode,state="readonly",width=14,values=("All","Progression","Events","Manual")); im.pack(side="left",padx=(8,0)); im.bind("<<ComboboxSelected>>",lambda _e:self._refresh_combined_inventory())
        self.shi_inv_tree=ttk.Treeview(inv,columns=("Item","Count","Type","Source Player","Source Location"),show="headings")
        # Loop variable(s): `c` (c), `w` (width/widget value (context dependent)); each iteration represents the next value from the iterable below.
        for c,w in [("Item",260),("Count",70),("Type",150),("Source Player",180),("Source Location",320)]: self.shi_inv_tree.heading(c,text=c); self.shi_inv_tree.column(c,width=w,anchor="w")
        self.shi_inv_tree.pack(fill="both",expand=True,padx=8,pady=(0,8)); self.shi_inv_tree.tag_configure("recent_item",foreground=self._palette()["success"],font="WayFinderSemibold")
        self._hint_seen_keys=set(); self._hint_last_status={}; self._hint_recent_until={}; self._hint_changed_until={}

    def _refresh_hints(self):
        """Handle refresh hints."""
        if not hasattr(self,"hint_tree"): return
        # Variable(s): `q` (q); named state retained for the surrounding calculation or subsequent calls.
        self._clear_tree(self.hint_tree); q=self.hint_filter.get().strip() if hasattr(self,"hint_filter") else ""; now=time.monotonic(); all_hints=getattr(self.snapshot,"hints",[]) or []
        try: self.shi_notebook.tab(1,text=f"Hints ({len(all_hints)})")
        except tk.TclError: _ignored("intentional best-effort fallback")
        # Loop variable(s): `h` (height/handle value (context dependent)); each iteration represents the next value from the iterable below.
        for h in all_hints:
            # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
            key=(str(h.get("item","")),str(h.get("location","")),str(h.get("receiving_player","")),str(h.get("finding_player","")))
            # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
            status=str(h.get("status","unspecified") or "unspecified")
            # Variable(s): `mode` (mode); named state retained for the surrounding calculation or subsequent calls.
            mode=self.hint_mode.get() if hasattr(self,"hint_mode") else "All"; loc=next((x for x in self.snapshot.locations if x.name==key[1]),None); flags=int(h.get("item_flags",0) or 0)
            if mode=="Found" and not h.get("found"): continue
            if mode=="Unfound" and h.get("found"): continue
            if mode=="Reachable" and (loc is None or loc.status!="reachable"): continue
            if mode=="Progression" and not (flags & 1 or flags & 4): continue
            if mode=="Priority" and status not in {"priority","avoid"}: continue
            if q and not self._fuzzy_match(q," ".join(key)): continue
            # Variable(s): `tags` (tags); named state retained for the surrounding calculation or subsequent calls.
            tags=()
            # Variable(s): `tags` (tags); named state retained for the surrounding calculation or subsequent calls.
            if self._hint_recent_until.get(key,0)>now: tags=("new_hint",)
            # Variable(s): `tags` (tags); named state retained for the surrounding calculation or subsequent calls.
            elif self._hint_changed_until.get(key,0)>now: tags=("changed_hint",)
            self.hint_tree.insert("","end",values=(key[0],key[2],key[1],key[3],status.replace("_"," ").title()),tags=tags)

    def _hint_selected(self,_e=None):
        # Variable(s): `vals` (vals); named state retained for the surrounding calculation or subsequent calls.
        """Handle hint selected."""
        vals=self.hint_tree.item(self.hint_tree.selection()[0],"values") if self.hint_tree.selection() else ()
        if vals: self.hint_detail.set(f"{vals[0]} for {vals[1]} • location: {vals[2]} • found by: {vals[3]} • status: {vals[4]}")

    def _refresh_combined_inventory(self):
        """Handle refresh combined inventory."""
        if not hasattr(self,"shi_inv_tree"): return
        # Variable(s): `q` (q); named state retained for the surrounding calculation or subsequent calls.
        self._clear_tree(self.shi_inv_tree); q=self.shi_inv_search.get().strip(); mode=self.shi_inventory_mode.get(); now=time.monotonic()
        # Loop variable(s): `item` (item); each iteration represents the next value from the iterable below.
        for item in self.snapshot.inventory:
            if mode=="Progression" and not item.progression: continue
            if mode=="Events" and not item.event: continue
            if mode=="Manual" and not item.manual: continue
            # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
            kind=" • ".join(x for x,v in (("PROGRESSION",item.progression),("EVENT",item.event),("MANUAL",item.manual)) if v) or "Normal"
            if q and not self._fuzzy_match(q,f"{item.name} {kind} {item.source_player} {item.source_location}"): continue
            # Variable(s): `delta` (delta); named state retained for the surrounding calculation or subsequent calls.
            delta=self.inventory_deltas.get(item.name,(0,0))[0] if self.inventory_deltas.get(item.name,(0,0))[1]>now else 0
            self.shi_inv_tree.insert("","end",values=(item.name,f"{item.count} (+{delta})" if delta>0 else item.count,kind,item.source_player or "—",item.source_location or "—"),tags=(("recent_item",) if delta>0 else ()))

    def _personal_note(self,name):
        # Variable(s): `top` (top); named state retained for the surrounding calculation or subsequent calls.
        """Handle personal note."""
        top=tk.Toplevel(self.root); top.configure(bg=self._palette()["bg"]); top.title(f"Note — {name}"); top.transient(self.root); shell=ttk.Frame(top,style="Card.TFrame",padding=12); shell.pack(fill="both",expand=True,padx=10,pady=10); ttk.Label(shell,text="LOCATION NOTE",style="CardTitle.TLabel").pack(anchor="w"); ttk.Label(shell,text=name,style="CardHeading.TLabel").pack(anchor="w",pady=(2,8)); text=tk.Text(shell,width=60,height=8,bg=self._palette()["panel"],fg=self._palette()["fg"],insertbackground=self._palette()["fg"],font="WayFinderBody",relief="flat",highlightthickness=1,highlightbackground=self._palette()["accent"],highlightcolor=self._palette()["accent_hover"],padx=8,pady=8); text.pack(fill="both",expand=True); notes=self.settings.setdefault("location_notes",{}); text.insert("1.0",str(notes.get(name,"")))
        # /**
        #  * Function: save
        #  * Purpose: Perform the save operation while keeping the surrounding subsystem state consistent.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        def save(): notes[name]=text.get("1.0","end").strip(); self._save_settings(); top.destroy()
        ttk.Button(shell,text="Save",style="Accent.TButton",command=save).pack(anchor="e",pady=(10,0))

    def _hint_open_path(self,_e=None):
        """Handle hint open path."""
        if not self.hint_tree.selection(): return
        # Variable(s): `vals` (vals); named state retained for the surrounding calculation or subsequent calls.
        vals=self.hint_tree.item(self.hint_tree.selection()[0],"values"); loc=vals[2] if len(vals)>2 else ""
        if loc: self.open_path(loc)

    def _hint_context_menu(self,event):
        """Handle hint context menu."""
        if not self.hint_tree.selection(): return
        # Variable(s): `vals` (vals); named state retained for the surrounding calculation or subsequent calls.
        vals=self.hint_tree.item(self.hint_tree.selection()[0],"values"); loc=vals[2] if len(vals)>2 else ""; item=vals[0] if vals else ""
        # Variable(s): `m` (m); named state retained for the surrounding calculation or subsequent calls.
        m=tk.Menu(self.root,tearoff=False); m.add_command(label="Show on Map",command=lambda:self._focus_location_on_map(loc,True)); m.add_command(label="Open in Path Explorer",command=lambda:self.open_path(loc)); m.add_command(label="Copy hint",command=lambda:self.root.clipboard_append(f"{item} — {loc}")); m.tk_popup(event.x_root,event.y_root)

