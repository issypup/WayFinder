"""Provide tracker panels support."""
# /**
#  * Module: wayfinder/app/ui/tracker_panels.py
#  * Purpose: Extracted WayFinderApp mixin; keeps one GUI responsibility isolated from the composition root.
#  */
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored
from wayfinder.utils.error_handler import ErrorHandler

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

class TrackerPanelsMixin:
    """Provide tracker panels mixin behavior."""
    def _build_inventory(self):
        """Construct the inventory UI/data structure and attach its callbacks."""
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        p=self._page("Inventory"); h=ttk.Frame(p); h.pack(fill="x",pady=(4,8)); ttk.Label(h,text="Inventory",style="Title.TLabel").pack(side="left")
        # Variable(s): `mode` (mode); named state retained for the surrounding calculation or subsequent calls.
        mode=ttk.Combobox(h,textvariable=self.inventory_mode,state="readonly",width=16,values=("All","Progression","Events","Manual")); mode.pack(side="right",padx=(8,0)); mode.bind("<<ComboboxSelected>>",lambda _e:self._refresh_inventory())
        self.inv_search=tk.StringVar(); ttk.Entry(h,textvariable=self.inv_search,width=30).pack(side="right"); self.inv_search.trace_add("write",lambda *_:self._refresh_inventory())
        self.inv_tree=ttk.Treeview(p,columns=("Item","Count","Type"),show="headings");
        # Loop variable(s): `c` (c), `w` (width/widget value (context dependent)); each iteration represents the next value from the iterable below.
        for c,w in [("Item",530),("Count",90),("Type",280)]: self.inv_tree.heading(c,text=c); self.inv_tree.column(c,width=w,anchor="w")
        self.inv_tree.pack(fill="both",expand=True); self.inv_tree.bind("<Double-1>",lambda _e:self._show_item_unlock())
        self.inv_tree.tag_configure("recent_item", foreground=self._palette()["success"], font=("Segoe UI Semibold", self.font_size.get()))
        ToolTip(mode,"Progression items are items classified as logic-relevant by the connected APWorld. Event and Manual items are shown separately.")
    def _show_item_unlock(self):
        """Handle show item unlock."""
        if not hasattr(self,"inv_tree") or not self.inv_tree.selection(): return
        name=str(self.inv_tree.item(self.inv_tree.selection()[0],"values")[0])
        impact=next((x for x in self.last_unlock_impacts if x.item==name),None)
        if not impact:
            ErrorHandler().show_info(f"No unlock transition for {name} was observed in the most recent snapshot delta.\n\nWayFinder only attributes changes it actually observed; it does not guess from spoiler data.", "What did this item unlock?"); return
        lines=[f"{impact.item} +{impact.count_delta}",f"Newly reachable checks: {len(impact.newly_reachable_locations)}",f"Newly reachable regions: {len(impact.newly_reachable_regions)}",f"Newly reachable entrances: {len(impact.newly_reachable_entrances)}"]
        if impact.goal_changed: lines.append("Goal state became satisfied.")
        if impact.newly_reachable_locations: lines.append("\nChecks:\n• "+"\n• ".join(impact.newly_reachable_locations[:20]))
        if impact.newly_reachable_regions: lines.append("\nRegions: "+", ".join(impact.newly_reachable_regions))
        ErrorHandler().show_info("\n".join(lines), "What did this item unlock?")
    def _edit_route_weights(self):
        """Handle edit route weights."""
        top=tk.Toplevel(self.root); top.title("Personal Route Scoring"); top.transient(self.root); top.grab_set()
        ttk.Label(top,text="Tune how Personal route scoring values route structure.",style="CardTitle.TLabel").grid(row=0,column=0,columnspan=2,padx=14,pady=(14,8),sticky="w")
        ttk.Label(top,text="Region transition value").grid(row=1,column=0,padx=14,pady=6,sticky="w"); ttk.Spinbox(top,from_=0,to=10,increment=.1,textvariable=self.personal_route_region_weight,width=8).grid(row=1,column=1,padx=14,pady=6)
        ttk.Label(top,text="Requirement penalty").grid(row=2,column=0,padx=14,pady=6,sticky="w"); ttk.Spinbox(top,from_=0,to=10,increment=.1,textvariable=self.personal_route_requirement_penalty,width=8).grid(row=2,column=1,padx=14,pady=6)
        def done(): self._save_settings(); top.destroy(); self._render_path(self.current_path) if self.current_path else None
        ttk.Button(top,text="Apply",style="Accent.TButton",command=done).grid(row=3,column=0,columnspan=2,pady=(8,14))
    def _entrance_context_menu(self,event):
        """Handle entrance context menu."""
        row=self.entrance_tree.identify_row(event.y)
        if not row:return
        self.entrance_tree.selection_set(row); vals=self.entrance_tree.item(row,"values"); target=str(vals[2]) if len(vals)>2 else ""
        loc=next((x for x in self.snapshot.locations if x.region==target and x.status!='checked'),None)
        menu=tk.Menu(self.root,tearoff=False)
        menu.add_command(label="Show destination on Map",state="normal" if loc else "disabled",command=lambda:self._focus_location_on_map(loc.name,True) if loc else None)
        menu.add_command(label="Open destination in Path Explorer",state="normal" if loc else "disabled",command=lambda:self.open_path(loc.name) if loc else None)
        menu.add_command(label="Open Progression Graph",command=lambda:self.show_page("Progression Graph"))
        menu.tk_popup(event.x_root,event.y_root)
    def _build_events(self):
        """Construct the events UI/data structure and attach its callbacks."""
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        p=self._page("Events"); h=ttk.Frame(p); h.pack(fill="x",pady=(4,8)); ttk.Label(h,text="Logic Events",style="Title.TLabel").pack(side="left"); self.event_search=tk.StringVar(); ttk.Entry(h,textvariable=self.event_search,width=30).pack(side="right"); self.event_search.trace_add("write",lambda *_:self._refresh_events())
        self.event_availability=tk.StringVar(value="Events: waiting for native tracker state"); ttk.Label(p,textvariable=self.event_availability,style="Muted.TLabel").pack(anchor="w",pady=(0,3))
        ttk.Label(p,text="Events are authoritative WayFinder native sweep results. WayFinder commands remain available from the Log page.",style="Muted.TLabel",wraplength=1000).pack(anchor="w",pady=(0,6))
        self.event_tree=ttk.Treeview(p,columns=("Event","Location"),show="headings"); self.event_tree.heading("Event",text="Event"); self.event_tree.heading("Location",text="Event location"); self.event_tree.column("Event",width=520,anchor="w"); self.event_tree.column("Location",width=420,anchor="w"); self.event_tree.pack(fill="both",expand=True)
    def _build_entrances(self):
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        """Handle build entrances."""
        p=self._page("Entrances"); h=ttk.Frame(p); h.pack(fill="x",pady=(4,8)); ttk.Label(h,text="Entrances & Traversal",style="Title.TLabel").pack(side="left")
        # Variable(s): `e` (e); named state retained for the surrounding calculation or subsequent calls.
        self.entrance_search=tk.StringVar(); e=ttk.Entry(h,textvariable=self.entrance_search,width=32); e.pack(side="right"); e.bind("<KeyRelease>",lambda _e:self._refresh_entrances())
        self.entrance_tree=ttk.Treeview(p,columns=("Entrance","Source","Destination","Status","Requirements"),show="headings")
        # Loop variable(s): `c` (c), `w` (width/widget value (context dependent)); each iteration represents the next value from the iterable below.
        for c,w in (("Entrance",330),("Source",220),("Destination",220),("Status",110),("Requirements",380)): self.entrance_tree.heading(c,text=c); self.entrance_tree.column(c,width=w,anchor="w")
        self.entrance_tree.pack(fill="both",expand=True); self.entrance_tree.bind("<Double-1>",self._entrance_open_path); self.entrance_tree.bind("<Button-3>",self._entrance_context_menu)
        self.entrance_summary=tk.StringVar(value="Waiting for generated entrance graph."); ttk.Label(p,textvariable=self.entrance_summary,style="Muted.TLabel").pack(anchor="w",pady=(6,0))
    def _refresh_entrances(self):
        """Handle refresh entrances."""
        if not hasattr(self,"entrance_tree"): return
        # Variable(s): `q` (q); named state retained for the surrounding calculation or subsequent calls.
        self._clear_tree(self.entrance_tree); q=self.entrance_search.get().strip().casefold() if hasattr(self,"entrance_search") else ""
        # Variable(s): `rows` (rows); named state retained for the surrounding calculation or subsequent calls.
        rows=getattr(self.snapshot,"entrance_details",[]) or []; reachable=0
        # Loop variable(s): `d` (d); each iteration represents the next value from the iterable below.
        for d in rows:
            # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
            status="Reachable" if d.get("reachable") else "Inaccessible"; reachable+=int(bool(d.get("reachable")))
            # Variable(s): `missing` (missing); named state retained for the surrounding calculation or subsequent calls.
            missing=d.get("missing",[]) or []; req="; ".join(f"{x.get('name')}: {x.get('detail','missing')}" for x in missing[:3]) or ("Satisfied" if d.get("satisfied") else "Rule blocked")
            # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
            text=f"{d.get('name','')} {d.get('source_region','')} {d.get('target_region','')} {req}".casefold()
            if q and q not in text: continue
            self.entrance_tree.insert("","end",values=(d.get("name",""),d.get("source_region",""),d.get("target_region",""),status,req))
        self.entrance_summary.set(f"{reachable}/{len(rows)} entrances currently reachable • {len(rows)-reachable} inaccessible/unresolved")
    def _entrance_open_path(self,_e=None):
        """Handle entrance open path."""
        if not self.entrance_tree.selection(): return
        # Variable(s): `vals` (vals); named state retained for the surrounding calculation or subsequent calls.
        vals=self.entrance_tree.item(self.entrance_tree.selection()[0],"values"); target=vals[2] if len(vals)>2 else ""
        # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
        loc=next((x for x in self.snapshot.locations if x.region==target),None)
        if loc: self.open_path(loc.name)
    def _refresh_path_selector(self):
        """Recompute and redraw the path selector view from the current application state."""
        if not hasattr(self,"path_selector"): return
        # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
        names=sorted((loc.name for loc in self.snapshot.locations),key=str.casefold)
        self.path_selector.configure(values=names)
    def _refresh_inventory(self):
        """Recompute and redraw the inventory view from the current application state."""
        # Variable(s): `mode` (mode); named state retained for the surrounding calculation or subsequent calls.
        self._clear_tree(self.inv_tree); mode=self.inventory_mode.get(); q=self.inv_search.get().strip()
        # Variable(s): `now_mono` (now mono); named state retained for the surrounding calculation or subsequent calls.
        now_mono=time.monotonic()
        self.inventory_deltas={name:value for name,value in self.inventory_deltas.items() if value[1] > now_mono}
        # Loop variable(s): `item` (item); each iteration represents the next value from the iterable below.
        for item in self.snapshot.inventory:
            if mode=="Progression" and not item.progression: continue
            if mode=="Events" and not item.event: continue
            if mode=="Manual" and not item.manual: continue
            # Variable(s): `tags` (tags); named state retained for the surrounding calculation or subsequent calls.
            tags=[]
            if item.progression: tags.append("PROGRESSION")
            if item.event: tags.append("EVENT")
            if item.manual: tags.append("MANUAL")
            if q and not self._fuzzy_match(q,f"{item.name} {' '.join(tags)}"): continue
            # Variable(s): `delta_info` (delta info); named state retained for the surrounding calculation or subsequent calls.
            delta_info=self.inventory_deltas.get(item.name)
            # Variable(s): `delta` (delta); named state retained for the surrounding calculation or subsequent calls.
            delta=delta_info[0] if delta_info else 0
            # Variable(s): `count_text` (count text); named state retained for the surrounding calculation or subsequent calls.
            count_text=f"{item.count}  (+{delta})" if delta>0 else str(item.count)
            # Variable(s): `row_tags` (row tags); named state retained for the surrounding calculation or subsequent calls.
            row_tags=("recent_item",) if delta>0 else ()
            self.inv_tree.insert("","end",values=(item.name,count_text," • ".join(tags) or "Normal"),tags=row_tags)
    def _refresh_events(self):
        """Recompute and redraw the events view from the current application state."""
        # Variable(s): `q` (q); named state retained for the surrounding calculation or subsequent calls.
        self._clear_tree(self.event_tree); q=self.event_search.get().strip() if hasattr(self,"event_search") else ""
        if hasattr(self,"event_availability"):
            if getattr(self.snapshot,"event_sweep_error",""):
                self.event_availability.set(f"Events: sweep failed — {self.snapshot.event_sweep_error}")
            elif not getattr(self.snapshot,"events_available",True):
                self.event_availability.set("Events: unavailable from this APWorld/native state")
            elif getattr(self.snapshot,"logic_warnings",[]):
                self.event_availability.set(f"Events: {len(self.snapshot.events)} active • {len(self.snapshot.logic_warnings)} logic diagnostic warning(s)")
            elif self.snapshot.events:
                self.event_availability.set(f"Events: {len(self.snapshot.events)} active")
            else:
                self.event_availability.set("Events: available — 0 active")
        # Variable(s): `locs` (locs); named state retained for the surrounding calculation or subsequent calls.
        locs=self.snapshot.event_locations
        # Loop variable(s): `i` (index), `event` (event); each iteration represents the next value from the iterable below.
        for i,event in enumerate(self.snapshot.events):
            if q and not self._fuzzy_match(q,event): continue
            self.event_tree.insert("","end",values=(event,locs[i] if i<len(locs) else ""))
    def _refresh_recent(self): self._clear_tree(self.recent_tree); [self.recent_tree.insert("","end",values=x) for x in self.recent_changes]
    def _record_recent_changes(self,old:Snapshot,new:Snapshot):
        """Compare snapshots and record newly changed checks/items for recent activity."""
        if not old.connected and not old.inventory and not old.locations: return
        # Variable(s): `now` (now); named state retained for the surrounding calculation or subsequent calls.
        self.last_unlock_impacts=list(detect_unlock_impact(old,new))
        now=datetime.now().strftime("%H:%M:%S"); old_items={x.name:x.count for x in old.inventory}; new_items={x.name:x.count for x in new.inventory}
        # Loop variable(s): `name` (name), `count` (count); each iteration represents the next value from the iterable below.
        for name,count in new_items.items():
            # Variable(s): `delta` (delta); named state retained for the surrounding calculation or subsequent calls.
            delta=count-old_items.get(name,0)
            if delta>0:
                impact=next((x for x in self.last_unlock_impacts if x.item==name),None)
                unlock=(f" • unlocked {len(impact.newly_reachable_locations)} check(s), {len(impact.newly_reachable_regions)} region(s), {len(impact.newly_reachable_entrances)} entrance(s)" if impact else "")
                self.recent_changes.insert(0,(now,"Item",f"+{delta} {name} (now {count}){unlock}"))
                # Variable(s): `previous_delta` (previous delta); named state retained for the surrounding calculation or subsequent calls.
                previous_delta=self.inventory_deltas.get(name,(0,0.0))[0]
                self.inventory_deltas[name]=(previous_delta+delta,time.monotonic()+6.0)
                self.root.after(6200,self._refresh_inventory)
        # Variable(s): `old_status` (old status); named state retained for the surrounding calculation or subsequent calls.
        old_status={x.name:x.status for x in old.locations}
        # Loop variable(s): `x` (horizontal x-coordinate); each iteration represents the next value from the iterable below.
        for x in new.locations:
            if x.name in old_status and old_status[x.name]!=x.status:self.recent_changes.insert(0,(now,"Check",f"{x.name}: {old_status[x.name]} → {x.status}"))
        self.recent_changes=self.recent_changes[:100]
    @staticmethod
    def _clear_tree(tree):
        """Remove every row from a ttk Treeview."""
        # Loop variable(s): `i` (index); each iteration represents the next value from the iterable below.
        for i in tree.get_children():tree.delete(i)
    def _selected_value(self,tree,index=0):
        """Return the primary value from the currently selected tree row, if any."""
        # Variable(s): `sel` (sel); named state retained for the surrounding calculation or subsequent calls.
        sel=tree.selection();
        if not sel:return ""
        # Variable(s): `vals` (vals); named state retained for the surrounding calculation or subsequent calls.
        vals=tree.item(sel[0],"values"); return vals[index] if vals and index<len(vals) else ""
