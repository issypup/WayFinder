"""Provide search ui support."""
# /**
#  * Module: wayfinder/app/ui/search_ui.py
#  * Purpose: Extracted WayFinderApp mixin; keeps one GUI responsibility isolated from the composition root.
#  */
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

import base64, hashlib, io, json, os, queue, re, shutil, subprocess, sys, tempfile, threading, time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from typing import Any
from difflib import SequenceMatcher
from datetime import datetime
from dataclasses import asdict, dataclass, field

try:
    from PIL import Image, ImageTk
    Image.MAX_IMAGE_PIXELS = None
except Exception:
    Image = ImageTk = None

from wayfinder.connection.runtime_client import Snapshot, InventoryEntry, LocationEntry, PathResult, RuleNode, WayFinderRuntimeClient
from wayfinder.connection.memory import get_record, clear_server_slot, normalize_server
from wayfinder.maps.packs import discover_packs, best_pack, load_pack_variant, default_pack_dir, portable_pack_dir, install_pack_archive, related_archive_for_folder, game_pack_dir, TRACKER_PACK_API_VERSION, ZOOM_CACHE_LEVELS, cached_map_path, build_pack_zoom_cache, remove_pack_zoom_cache, validate_pack_archive, validate_pack_folder, install_validated_pack, enforce_map_cache_limit, persist_zoom_image_async
from wayfinder.maps.assets import LARGE_MAP_PIXELS, open_pack_image, remember_image, cached_image, render_result, asset_key, TiledMapPhoto, draw_map_photo
from wayfinder.maps.converter import convert_poptracker_pack, convert_ut_pack, detect_map_pack_archive_format
from wayfinder.diagnostics import CATEGORIES, sanitize, register_secret, make_record, format_record
from wayfinder.maps.intelligence import check_evidence
from wayfinder.connection.identity import validate_snapshot
from wayfinder import __version__
from wayfinder.logic.progression_intelligence import detect_unlock_impact, waiting_analysis, route_score, build_progression_graph
from wayfinder.logic.solver_intelligence import normalized_kind, rank_or_branches, path_cycles, dead_route_reasons, provenance_rows, reconstruction_audit, searchable_entries, remote_dependency_lines, goal_target
import wayfinder.setup as setup_backend

GUI_VERSION = __version__
from wayfinder.storage import app_data_root
APP_DATA_ROOT = app_data_root()
SETTINGS_PATH = APP_DATA_ROOT / "settings.json"
STATE_PATH = APP_DATA_ROOT / "last_snapshot.json"
STATUS_VISUALS = {
    "reachable": {"label": "Reachable", "symbol": "●", "color": "#2f9e6f"},
    "glitched": {"label": "Glitch-only", "symbol": "⚡", "color": "#9b4fc4"},
    "out_of_logic": {"label": "Out of logic", "symbol": "◆", "color": "#d05b5b"},
    "checked": {"label": "Checked", "symbol": "✓", "color": "#7f8a91"},
    "ignored": {"label": "Ignored", "symbol": "—", "color": "#8c9499"},
    "non_progression": {"label": "Non-progression / untracked", "symbol": "○", "color": "#9a8f72"},
    "unknown": {"label": "Unknown", "symbol": "?", "color": "#71869a"},
}

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

class SearchUiMixin:
    """Provide search ui mixin behavior."""
    def _build_search(self):
        """Construct the search UI/data structure and attach its callbacks."""
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        p=self._page("Search"); ttk.Label(p,text="Search Everywhere",style="Title.TLabel").pack(anchor="w",pady=(4,8))
        # Variable(s): `row` (row); named state retained for the surrounding calculation or subsequent calls.
        row=ttk.Frame(p); row.pack(fill="x",pady=(0,8)); self.search_var=tk.StringVar(); e=ttk.Entry(row,textvariable=self.search_var); e.pack(side="left",fill="x",expand=True); e.bind("<Return>",lambda _e:self.run_global_search(self.search_var.get())); ttk.Button(row,text="Search",style="Accent.TButton",command=lambda:self.run_global_search(self.search_var.get())).pack(side="left",padx=(8,0)); ttk.Button(row,text="Clear",command=self._clear_global_search).pack(side="left",padx=(4,0))
        ttk.Label(p,text="Fuzzy matching is enabled, so partial or slightly mistyped names can still match.",style="Muted.TLabel").pack(anchor="w",pady=(0,8))
        self.search_tree=ttk.Treeview(p,columns=("Type","Name","Details"),show="headings");
        # Loop variable(s): `c` (c), `w` (width/widget value (context dependent)); each iteration represents the next value from the iterable below.
        for c,w in [("Type",120),("Name",500),("Details",380)]: self.search_tree.heading(c,text=c); self.search_tree.column(c,width=w,anchor="w")
        self.search_tree.pack(fill="both",expand=True); self.search_tree.bind("<Double-1>",self._open_search_result); self.search_tree.bind("<<TreeviewSelect>>",self._search_result_selected)
    def _run_combined_search(self):
        # Variable(s): `q` (q); named state retained for the surrounding calculation or subsequent calls.
        """Handle run combined search."""
        q=self.shi_search_var.get().strip(); self._clear_tree(self.shi_search_tree)
        if not q: return
        # Variable(s): `rows` (rows); named state retained for the surrounding calculation or subsequent calls.
        rows=self._collect_search_rows(q)
        # Loop variable(s): `_score` (score), `t` (t), `name` (name), `details` (details); each iteration represents the next value from the iterable below.
        for _score,t,name,details in rows: self.shi_search_tree.insert("","end",values=(t,name,details))
    def _collect_search_rows(self,q):
        # Variable(s): `q` (q); named state retained for the surrounding calculation or subsequent calls.
        """Handle collect search rows."""
        q=q.strip(); rows=[]
        # Inventory numeric expression: e.g. Key >= 2
        # Variable(s): `m` (m); named state retained for the surrounding calculation or subsequent calls.
        m=re.match(r"^(.+?)\s*(>=|<=|==|=|>|<)\s*(\d+)\s*$",q)
        if m:
            # Variable(s): `name` (name), `op` (op), `n` (n); named state retained for the surrounding calculation or subsequent calls.
            name,op,n=m.group(1).strip(),m.group(2),int(m.group(3)); ops={">=":lambda a,b:a>=b,"<=":lambda a,b:a<=b,"==":lambda a,b:a==b,"=":lambda a,b:a==b,">":lambda a,b:a>b,"<":lambda a,b:a<b}
            # Loop variable(s): `item` (item); each iteration represents the next value from the iterable below.
            for item in self.snapshot.inventory:
                if self._fuzzy_match(name,item.name) and ops[op](item.count,n): rows.append((100.0,"Item",item.name,f"Count {item.count} • expression {op} {n}"))
            return rows
        # Variable(s): `tokens` (tokens); named state retained for the surrounding calculation or subsequent calls.
        tokens=q.split(); require_reachable=any(x.casefold()=="reachable" for x in tokens)
        # Variable(s): `region_terms` (region terms); named state retained for the surrounding calculation or subsequent calls.
        region_terms=[x.split(":",1)[1] for x in tokens if x.casefold().startswith("region:") and ":" in x]
        # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
        text=" ".join(x for x in tokens if x.casefold()!="reachable" and not x.casefold().startswith("region:")).strip()
        # Variable(s): `pack` (pack); named state retained for the surrounding calculation or subsequent calls.
        pack=self.active_map_pack
        # Loop variable(s): `loc` (loc); each iteration represents the next value from the iterable below.
        for loc in self.snapshot.locations:
            if require_reachable and loc.status!="reachable": continue
            if region_terms and not all(self._fuzzy_match(term,loc.region) for term in region_terms): continue
            # Variable(s): `score` (score); named state retained for the surrounding calculation or subsequent calls.
            score=100.0 if not text else max(self._search_score(text,loc.name),self._search_score(text,loc.region)-3)
            if score>=47: rows.append((score,"Check",loc.name,f"{loc.status.replace('_',' ').title()} • {loc.region or 'No region'}"))
        # Loop variable(s): `region` (region); each iteration represents the next value from the iterable below.
        for region in sorted({x.region for x in self.snapshot.locations if x.region}):
            if region_terms and not all(self._fuzzy_match(term,region) for term in region_terms): continue
            # Variable(s): `score` (score); named state retained for the surrounding calculation or subsequent calls.
            score=100.0 if not text else self._search_score(text,region)
            if score>=47: rows.append((score-1,"Region",region,f"{sum(1 for x in self.snapshot.locations if x.region==region and x.status!='checked')} unchecked check(s)"))
        # Loop variable(s): `ev` (ev); each iteration represents the next value from the iterable below.
        for ev in self.snapshot.events:
            # Variable(s): `score` (score); named state retained for the surrounding calculation or subsequent calls.
            score=self._search_score(text or q,ev)
            if score>=47: rows.append((score-4,"Event",ev,"Logic event"))
        # Loop variable(s): `ent` (ent); each iteration represents the next value from the iterable below.
        for ent in getattr(self.snapshot,"entrances",[]) or []:
            # Variable(s): `score` (score); named state retained for the surrounding calculation or subsequent calls.
            score=self._search_score(text or q,ent)
            if score>=47: rows.append((score-5,"Entrance",ent,"World entrance"))
        # Loop variable(s): `item` (item); each iteration represents the next value from the iterable below.
        for item in self.snapshot.inventory:
            # Variable(s): `score` (score); named state retained for the surrounding calculation or subsequent calls.
            score=self._search_score(text or q,item.name)
            if score>=47: rows.append((score-3,"Item",item.name,f"Count {item.count}"))
        if pack:
            # Loop variable(s): `md` (metadata); each iteration represents the next value from the iterable below.
            for md in pack.maps:
                # Variable(s): `score` (score); named state retained for the surrounding calculation or subsequent calls.
                score=max(self._search_score(text or q,md.title),self._search_score(text or q,md.name))
                if score>=47: rows.append((score-2,"Map",md.title,f"{len(pack.markers_by_map.get(md.name,()))} marker(s)"))
        # Variable(s): `out` (out); named state retained for the surrounding calculation or subsequent calls.
        rows.sort(key=lambda r:(-r[0],r[1],r[2].casefold())); out=[]; seen=set()
        # Loop variable(s): `row` (row); each iteration represents the next value from the iterable below.
        for row in rows:
            # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
            key=(row[1],row[2])
            if key not in seen: seen.add(key); out.append(row)
        return out
    def _open_combined_search_result(self,_e=None):
        # Variable(s): `t` (t); named state retained for the surrounding calculation or subsequent calls.
        """Handle open combined search result."""
        t=self._selected_value(self.shi_search_tree,0); name=self._selected_value(self.shi_search_tree,1)
        if t=="Check": self._focus_location_on_map(name,switch_to_map=True)
        elif t=="Region":
            # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
            loc=next((x for x in self.snapshot.locations if x.region==name and x.status!='checked'),None)
            if loc:self._focus_location_on_map(loc.name,switch_to_map=True)
        elif t=="Map" and self.active_map_pack and name in self.active_map_pack.maps_by_title: self.map_selector_var.set(name); self._request_map_render(preserve_view=False,delay=20); self.show_page("Map")
        elif t=="Item": self.shi_notebook.select(2); self.shi_inv_search.set(name); self._refresh_combined_inventory()
        elif t=="Event": self.show_page("Events"); self.event_search.set(name)
    def _search_score(self,q,text):
        # Variable(s): `q` (q); named state retained for the surrounding calculation or subsequent calls.
        """Handle search score."""
        q=' '.join(q.casefold().replace('_',' ').replace('-',' ').split()); t=' '.join(text.casefold().replace('_',' ').replace('-',' ').split())
        if not q: return 0.0
        if t==q: return 100.0
        if t.startswith(q): return 92.0
        if q in t: return 84.0
        # Variable(s): `words` (words); named state retained for the surrounding calculation or subsequent calls.
        words=t.split(); ratios=[SequenceMatcher(None,q,w).ratio() for w in words]+[SequenceMatcher(None,q,t).ratio()]
        return max(ratios,default=0.0)*70.0
    def _clear_global_search(self):
        """Handle clear global search."""
        if hasattr(self,'search_var'): self.search_var.set('')
        if hasattr(self,'global_search'): self.global_search.set('')
        if hasattr(self,'search_tree'): self._clear_tree(self.search_tree)
        self.map_selected_location=''; self._refresh_map_markers()
    def _focus_global_search(self,_e=None):
        """Handle focus global search."""
        self.show_page("Search, Hints & Inventory"); self.shi_notebook.select(0)
        # Loop variable(s): `child` (child); each iteration represents the next value from the iterable below.
        for child in self.shi_notebook.nametowidget(self.shi_notebook.tabs()[0]).winfo_children():
            # Loop variable(s): `widget` (widget); each iteration represents the next value from the iterable below.
            for widget in child.winfo_children() if hasattr(child,"winfo_children") else ():
                if isinstance(widget,ttk.Entry): widget.focus_set(); return "break"
        return "break"
    def _fuzzy_match(self,q,text):
        """Handle fuzzy match."""
        return self._search_score(q,text) >= 47.0
    def run_global_search(self,q=None):
        # Variable(s): `q` (q); named state retained for the surrounding calculation or subsequent calls.
        """Handle run global search."""
        q=(q if q is not None else self.global_search.get()).strip(); self.global_search.set(q); self.search_var.set(q); self._clear_tree(self.search_tree)
        if not q:return
        # Loop variable(s): `_score` (score), `t` (t), `name` (name), `details` (details); each iteration represents the next value from the iterable below.
        for _score,t,name,details in self._collect_search_rows(q): self.search_tree.insert("","end",values=(t,name,details))
    def _search_result_selected(self,_e=None):
        """Handle search result selected."""
        if not hasattr(self,'search_tree'):return
        # Variable(s): `t` (t); named state retained for the surrounding calculation or subsequent calls.
        t=self._selected_value(self.search_tree,0); name=self._selected_value(self.search_tree,1)
        if t=='Check': self._focus_location_on_map(name,switch_to_map=False)
        elif t=='Region':
            # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
            loc=next((x for x in self.snapshot.locations if x.region==name and x.status!='checked'),None)
            if loc:self._focus_location_on_map(loc.name,switch_to_map=False)
        elif t=='Map' and self.active_map_pack and name in self.active_map_pack.maps_by_title:
            self.map_selector_var.set(name); self._request_map_render(preserve_view=False,delay=20)
    def _open_search_result(self,_e=None):
        # Variable(s): `t` (t); named state retained for the surrounding calculation or subsequent calls.
        """Handle open search result."""
        t=self._selected_value(self.search_tree,0); name=self._selected_value(self.search_tree,1)
        if t=='Check': self._focus_location_on_map(name,switch_to_map=True)
        elif t=='Region':
            # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
            loc=next((x for x in self.snapshot.locations if x.region==name and x.status!='checked'),None)
            if loc:self._focus_location_on_map(loc.name,switch_to_map=True)
        elif t=='Map':
            if self.active_map_pack and name in self.active_map_pack.maps_by_title:self.map_selector_var.set(name); self._request_map_render(preserve_view=False,delay=20); self.show_page('Map')
        elif t=='Item': self.show_page('Inventory'); self.inv_search.set(name)
        elif t=='Event': self.show_page('Events'); self.event_search.set(name)
        elif t=='Entrance': self._append_log(f"Search selected entrance: {name}")
