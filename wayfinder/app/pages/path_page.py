"""Provide path page support."""
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

class PathPageMixin:
    """Extracted callbacks that operate on WayFinderApp-owned state."""
    def _build_stuck(self):
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        """Handle build stuck."""
        p=self._page("I’m Stuck?")
        # Variable(s): `h` (height/handle value (context dependent)); named state retained for the surrounding calculation or subsequent calls.
        h=ttk.Frame(p); h.pack(fill="x",pady=(4,8))
        ttk.Label(h,text="I’m Stuck? — Progression Helper",style="Title.TLabel").pack(side="left")
        ttk.Button(h,text="Refresh Recommendations",style="Accent.TButton",command=self._refresh_stuck).pack(side="right")
        self.stuck_summary=tk.StringVar(value="Connect to Archipelago to analyse reachable destinations.")
        ttk.Label(p,textvariable=self.stuck_summary,style="Muted.TLabel",wraplength=1050,justify="left").pack(anchor="w",pady=(0,8))
        self.stuck_tree=ttk.Treeview(p,columns=("Destination","Useful","Map","Why"),show="headings")
        # Loop variable(s): `c` (c), `w` (width/widget value (context dependent)); each iteration represents the next value from the iterable below.
        for c,w in (("Destination",280),("Useful",80),("Map",220),("Why",460)):
            self.stuck_tree.heading(c,text=c); self.stuck_tree.column(c,width=w,anchor="w")
        self.stuck_tree.pack(fill="both",expand=True)
        self.stuck_tree.bind("<Double-1>",lambda _e:self._open_stuck_map())
        # Variable(s): `row` (row); named state retained for the surrounding calculation or subsequent calls.
        row=ttk.Frame(p); row.pack(fill="x",pady=(8,0))
        ttk.Button(row,text="Show on Map",style="Accent.TButton",command=self._open_stuck_map).pack(side="left")
        ttk.Button(row,text="Open in Path Explorer",style="Accent.TButton",command=self._open_stuck_path).pack(side="left",padx=6)
        ttk.Label(row,text="Uses WayFinder native reachability and progression ranking.",style="Muted.TLabel").pack(side="right")

    def _refresh_stuck(self):
        """Handle refresh stuck."""
        if not hasattr(self,'stuck_tree'): return
        self._clear_tree(self.stuck_tree)
        # Variable(s): `reachable` (reachable); named state retained for the surrounding calculation or subsequent calls.
        reachable=[x for x in self.snapshot.locations if x.status=='reachable' and not x.ignored]
        # Variable(s): `pack` (pack); named state retained for the surrounding calculation or subsequent calls.
        pack=self.active_map_pack
        # Variable(s): `by_region` (by region); named state retained for the surrounding calculation or subsequent calls.
        by_region={}
        # Loop variable(s): `loc` (loc); each iteration represents the next value from the iterable below.
        for loc in reachable:
            # Variable(s): `region` (region); named state retained for the surrounding calculation or subsequent calls.
            region=(loc.region or '').strip() or 'Other reachable checks'
            by_region.setdefault(region,[]).append(loc)
        # Variable(s): `rows` (rows); named state retained for the surrounding calculation or subsequent calls.
        rows=[]
        # Loop variable(s): `region` (region), `locs` (locs); each iteration represents the next value from the iterable below.
        for region,locs in by_region.items():
            # Variable(s): `maps` (maps); named state retained for the surrounding calculation or subsequent calls.
            maps=[]
            if pack:
                # Loop variable(s): `loc` (loc); each iteration represents the next value from the iterable below.
                for loc in locs:
                    # Loop variable(s): `marker` (marker); each iteration represents the next value from the iterable below.
                    for marker in pack.markers_by_location.get(loc.name,()):
                        if marker.map_name not in maps: maps.append(marker.map_name)
            # Variable(s): `hinted` (hinted); named state retained for the surrounding calculation or subsequent calls.
            hinted=sum(1 for x in locs if x.hinted)
            # Variable(s): `hint_rows` (hint rows); named state retained for the surrounding calculation or subsequent calls.
            hint_rows=[h for h in getattr(self.snapshot,"hints",[]) or [] if h.get("location") in {x.name for x in locs}]
            # Variable(s): `prog_hints` (prog hints); named state retained for the surrounding calculation or subsequent calls.
            prog_hints=sum(1 for h in hint_rows if int(h.get("item_flags",0) or 0) & 5)
            # Variable(s): `priority` (priority); named state retained for the surrounding calculation or subsequent calls.
            priority=sum(1 for h in hint_rows if str(h.get("status",""))=="priority")
            # Variable(s): `boss_names` (boss names); named state retained for the surrounding calculation or subsequent calls.
            boss_names=set((getattr(self.snapshot,"location_name_groups",{}) or {}).get("Bosses",[])); bosses=sum(1 for x in locs if x.name in boss_names)
            # Variable(s): `score` (score); named state retained for the surrounding calculation or subsequent calls.
            score=len(locs)*10 + hinted*4 + prog_hints*15 + priority*12 + bosses*5
            # Variable(s): `why` (why); named state retained for the surrounding calculation or subsequent calls.
            why=f"{len(locs)} reachable unchecked check{'s' if len(locs)!=1 else ''}"
            if prog_hints: why+=f" • {prog_hints} progression hint{'s' if prog_hints!=1 else ''}"
            elif hinted: why+=f" • {hinted} hinted"
            if priority: why+=f" • {priority} priority"
            if bosses: why+=f" • {bosses} boss{'es' if bosses!=1 else ''}"
            # Variable(s): `map_display` (map display); named state retained for the surrounding calculation or subsequent calls.
            map_display='—'
            if maps and pack:
                # Variable(s): `map_display` (map display); named state retained for the surrounding calculation or subsequent calls.
                map_display=next((md.title for md in pack.maps if md.name==maps[0]),maps[0])
            rows.append((score,region,locs,map_display,why))
        rows.sort(key=lambda r:(-r[0],-len(r[2]),r[1].casefold()))
        self._stuck_recommendations=rows
        # Variable(s): `useful` (useful); named state retained for the surrounding calculation or subsequent calls.
        useful=sum(len(r[2]) for r in rows)
        wait=waiting_analysis(self.snapshot)
        if not rows:
            detail=(" • Blockers: "+"; ".join(wait.blockers[:4])) if wait.blockers else ""
            self.stuck_summary.set(f"What am I waiting for? {wait.summary}{detail}")
        else:
            self.stuck_summary.set(f"{len(rows)} useful destination{'s' if len(rows)!=1 else ''} available • {useful} reachable unchecked checks. Highest-density reachable areas are shown first.")
        # Loop variable(s): `score` (score), `region` (region), `locs` (locs), `map_name` (map name), `why` (why); each iteration represents the next value from the iterable below.
        for score,region,locs,map_name,why in rows:
            self.stuck_tree.insert('', 'end', values=(region,len(locs),map_name,why))

    def _selected_stuck(self):
        """Handle selected stuck."""
        if not hasattr(self,'stuck_tree'): return None
        # Variable(s): `sel` (sel); named state retained for the surrounding calculation or subsequent calls.
        sel=self.stuck_tree.selection()
        if not sel: return None
        # Variable(s): `region` (region); named state retained for the surrounding calculation or subsequent calls.
        region=self.stuck_tree.item(sel[0],'values')[0]
        return next((r for r in self._stuck_recommendations if r[1]==region),None)

    def _open_stuck_map(self):
        # Variable(s): `row` (row); named state retained for the surrounding calculation or subsequent calls.
        """Handle open stuck map."""
        row=self._selected_stuck()
        if not row: return
        # Variable(s): `_score` (score), `_region` (region), `locs` (locs), `map_name` (map name), `_why` (why); named state retained for the surrounding calculation or subsequent calls.
        _score,_region,locs,map_name,_why=row
        # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
        target=locs[0].name if locs else ''
        self._focus_location_on_map(target, switch_to_map=True)

    def _open_stuck_path(self):
        # Variable(s): `row` (row); named state retained for the surrounding calculation or subsequent calls.
        """Handle open stuck path."""
        row=self._selected_stuck()
        if row and row[2]: self.open_path(row[2][0].name)

    def _build_progression_graph(self):
        """Handle build progression graph."""
        p=self._page("Progression Graph")
        h=ttk.Frame(p); h.pack(fill="x",pady=(4,8)); ttk.Label(h,text="Progression / Dependency Graph",style="Title.TLabel").pack(side="left")
        ttk.Button(h,text="Refresh",style="Accent.TButton",command=self._refresh_progression_graph).pack(side="right")
        self.progression_graph_summary=tk.StringVar(value="Connect to build the known dependency graph.")
        ttk.Label(p,textvariable=self.progression_graph_summary,style="Muted.TLabel",wraplength=1050,justify="left").pack(anchor="w",pady=(0,8))
        self.progression_graph_tree=ttk.Treeview(p,columns=("Type","Node","Status","Depends / Connects To"),show="headings")
        for c,w in (("Type",100),("Node",310),("Status",120),("Depends / Connects To",500)):
            self.progression_graph_tree.heading(c,text=c); self.progression_graph_tree.column(c,width=w,anchor="w")
        self.progression_graph_tree.pack(fill="both",expand=True)
        self.progression_graph_tree.bind("<Double-1>",lambda _e:self._open_progression_graph_selection())

    def _refresh_progression_graph(self):
        """Handle refresh progression graph."""
        if not hasattr(self,"progression_graph_tree"): return
        self._clear_tree(self.progression_graph_tree); model=build_progression_graph(self.snapshot)
        outgoing={}
        for edge in model.edges: outgoing.setdefault(edge.source,[]).append(f"{edge.label} → {edge.target.split(':',1)[-1]}")
        for node in sorted(model.nodes,key=lambda n:(n.kind,n.label.casefold())):
            self.progression_graph_tree.insert('', 'end', values=(node.kind.title(),node.label,node.status,"; ".join(outgoing.get(node.key,())[:5])))
        self.progression_graph_summary.set(f"{len(model.nodes)} known nodes • {len(model.edges)} known dependency/containment edges. Only live APWorld/runtime knowledge is shown; spoiler-only edges are never inferred.")

    def _open_progression_graph_selection(self):
        """Handle open progression graph selection."""
        vals=self.progression_graph_tree.item(self.progression_graph_tree.selection()[0],"values") if self.progression_graph_tree.selection() else ()
        if not vals:return
        kind,name=str(vals[0]).casefold(),str(vals[1])
        if kind=="location": self.open_path(name)
        elif kind=="region":
            loc=next((x for x in self.snapshot.locations if x.region==name and x.status!='checked'),None)
            if loc:self._focus_location_on_map(loc.name,True)

    def _refresh_route_goal(self):
        """Handle refresh route goal."""
        if not hasattr(self,"goal_route_summary"): return
        goal=self.snapshot.goal_detail or {}; wait=waiting_analysis(self.snapshot)
        name=str(goal.get("name") or goal.get("module") or "Goal")
        if goal.get("satisfied"): text=f"Goal: {name} • reachable / satisfied."
        else:
            missing=goal.get("missing",[]) if isinstance(goal.get("missing",[]),list) else []
            missing_text=" → ".join(str(x) for x in missing[:6]) or ("; ".join(wait.blockers[:4]) if wait.blockers else "route blockers are not structurally exposed")
            text=f"Goal: {name} • not yet reachable • Missing: {missing_text} • Waiting context: {wait.state}."
        self.goal_route_summary.set(text)

    def _open_goal_route(self):
        """Handle open goal route."""
        goal=self.snapshot.goal_detail or {}; target=str(goal.get("location") or goal.get("target") or goal.get("name") or "").strip()
        if target and any(x.name==target for x in self.snapshot.locations): self.open_path(target)
        else:
            blocked=[x for x in self.snapshot.locations if x.status!='checked']
            if blocked:self.open_path(blocked[-1].name)

    def _build_path(self):
        """Construct the path UI/data structure and attach its callbacks."""
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        p=self._page("Path Explorer"); h=ttk.Frame(p); h.pack(fill="x",pady=(4,6)); ttk.Label(h,text="Logical Path Explorer",style="Title.TLabel").pack(side="left")
        self.back_btn=ttk.Button(h,style="Accent.TButton",text="←",width=3,command=self.path_back); self.back_btn.pack(side="right",padx=2); self.forward_btn=ttk.Button(h,style="Accent.TButton",text="→",width=3,command=self.path_forward); self.forward_btn.pack(side="right",padx=2)
        # Variable(s): `row` (row); named state retained for the surrounding calculation or subsequent calls.
        row=ttk.Frame(p); row.pack(fill="x",pady=(0,6)); self.path_var=tk.StringVar(); self.path_selector=ttk.Combobox(row,textvariable=self.path_var,state="normal"); self.path_selector.pack(side="left",fill="x",expand=True); self.path_selector.bind("<Return>",lambda _e:self.open_path(self.path_var.get())); self.path_selector.bind("<<ComboboxSelected>>",lambda _e:self.open_path(self.path_var.get())); ToolTip(self.path_selector,"Choose any known check, or type part of its name. Double-clicking a check on the Checks page selects it here automatically."); ttk.Button(row,style="Accent.TButton",text="Show Path",command=lambda:self.open_path(self.path_var.get())).pack(side="left",padx=(8,0)); self.route_strategy_box=ttk.Combobox(row,textvariable=self.route_strategy,state="readonly",width=23,values=("Fastest route","Fewest requirements","Most checks along route","Personal")); self.route_strategy_box.pack(side="left",padx=(6,0)); self.route_strategy_box.bind("<<ComboboxSelected>>",lambda _e:self._render_path(self.current_path) if self.current_path else None); ttk.Button(row,style="Accent.TButton",text="Route weights…",command=self._edit_route_weights).pack(side="left",padx=(4,0)); ttk.Button(row,style="Accent.TButton",text="Copy",command=self.copy_path).pack(side="left",padx=4); ttk.Button(row,style="Accent.TButton",text="Open Solver Output",command=self.open_solver_output).pack(side="left",padx=(0,4)); ttk.Button(row,style="Accent.TButton",text="Export",command=self.export_path).pack(side="left")
        tools=ttk.Frame(p); tools.pack(fill="x",pady=(0,6)); ttk.Button(tools,style="Accent.TButton",text="Goal Route",command=self._solver_goal_route).pack(side="left"); ttk.Button(tools,style="Accent.TButton",text="What Am I Waiting For?",command=self._solver_waiting_report).pack(side="left",padx=4); ttk.Button(tools,style="Accent.TButton",text="Reconstruction Audit",command=self._solver_reconstruction_audit).pack(side="left",padx=4); ttk.Checkbutton(tools,text="Collapse satisfied branches",variable=self.path_collapse_satisfied,command=lambda:self._render_path(self.current_path) if self.current_path else None).pack(side="left",padx=(12,4)); ttk.Label(tools,text="Search graph:",style="Muted.TLabel").pack(side="left",padx=(12,4)); entry=ttk.Entry(tools,textvariable=self.path_search_var,width=24); entry.pack(side="left"); entry.bind("<Return>",lambda _e:self._solver_search_graph()); ttk.Button(tools,style="Accent.TButton",text="Find",command=self._solver_search_graph).pack(side="left",padx=4)
        self.breadcrumb_var=tk.StringVar(value="—"); ttk.Label(p,textvariable=self.breadcrumb_var,style="Muted.TLabel",wraplength=1000).pack(anchor="w",pady=(0,4)); self.path_status=tk.StringVar(value="Choose a location to visualize its logical route and requirements."); ttk.Label(p,textvariable=self.path_status,style="Muted.TLabel").pack(anchor="w",pady=(0,6))
        # Variable(s): `nb` (nb); named state retained for the surrounding calculation or subsequent calls.
        nb=ttk.Notebook(p); nb.pack(fill="both",expand=True); graph_frame=ttk.Frame(nb); detail_frame=ttk.Frame(nb); nb.add(graph_frame,text="Graph"); nb.add(detail_frame,text="Step Details")
        # Variable(s): `graph_wrap` (graph wrap); named state retained for the surrounding calculation or subsequent calls.
        graph_wrap=ttk.Frame(graph_frame); graph_wrap.pack(fill="both",expand=True)
        # Variable(s): `graph_sb` (graph sb); named state retained for the surrounding calculation or subsequent calls.
        self.graph_canvas=tk.Canvas(graph_wrap,bg=self._palette()["panel"],highlightthickness=0); graph_sb=ttk.Scrollbar(graph_wrap,orient="vertical",command=self.graph_canvas.yview); graph_sb.pack(side="right",fill="y"); self.graph_canvas.pack(side="left",fill="both",expand=True); self.graph_canvas.configure(yscrollcommand=graph_sb.set); self.graph_canvas.bind("<Configure>",lambda _e:self._draw_graph())
        # Variable(s): `wrap` (wrap); named state retained for the surrounding calculation or subsequent calls.
        wrap=ttk.Frame(detail_frame,style="Panel.TFrame"); wrap.pack(fill="both",expand=True); self.path_canvas=tk.Canvas(wrap,bg=self._palette()["panel"],highlightthickness=0); sb=ttk.Scrollbar(wrap,orient="vertical",command=self.path_canvas.yview); sb.pack(side="right",fill="y"); self.path_canvas.pack(side="left",fill="both",expand=True); self.path_canvas.configure(yscrollcommand=sb.set)
        self.path_inner=ttk.Frame(self.path_canvas,style="Panel.TFrame"); self.path_window=self.path_canvas.create_window((0,0),window=self.path_inner,anchor="nw"); self.path_inner.bind("<Configure>",lambda _e:self.path_canvas.configure(scrollregion=self.path_canvas.bbox("all"))); self.path_canvas.bind("<Configure>",lambda e:self.path_canvas.itemconfigure(self.path_window,width=e.width))

    def open_path(self,target,add_history=True):
        """Request and display logical path analysis for the selected target."""
        # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
        target=(target or "").strip()
        if not target:return
        self.map_selected_location=target
        if hasattr(self,"map_canvas"): self._refresh_map_markers()
        if add_history:
            if self.history_index < len(self.history)-1:self.history=self.history[:self.history_index+1]
            if not self.history or self.history[-1]!=target:self.history.append(target)
            self.history_index=len(self.history)-1
        self.path_var.set(target); self.show_page("Path Explorer"); self.path_status.set(f"Building logical path for {target}…"); self.breadcrumb_var.set("Recalculating route…")
        # Variable(s): `req_holder` (req holder); named state retained for the surrounding calculation or subsequent calls.
        req_holder={"id":0}
        # /**
        #  * Function: deliver
        #  * Purpose: Perform the deliver operation while keeping the surrounding subsystem state consistent.
        #  * @param result: Result supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        def deliver(result):
            """Handle deliver."""
            if not self._closing: self.events.put(("path_guarded", (req_holder["id"], result)))
        req_holder["id"]=self.runtime_client.request_path(target, deliver, timeout=15.0)
        self._active_path_request=req_holder["id"]
        self._update_history_buttons()

    def path_back(self):
        """Move backward through path-analysis navigation history."""
        if self.history_index>0:self.history_index-=1; self.open_path(self.history[self.history_index],False); self._update_history_buttons()

    def path_forward(self):
        """Move forward through path-analysis navigation history."""
        if self.history_index<len(self.history)-1:self.history_index+=1; self.open_path(self.history[self.history_index],False); self._update_history_buttons()

    def _update_history_buttons(self):
        """Internal helper for update history buttons; kept private so callers use the higher-level component API."""
        self.back_btn.configure(state="normal" if self.history_index>0 else "disabled"); self.forward_btn.configure(state="normal" if 0<=self.history_index<len(self.history)-1 else "disabled")

    def _solver_goal_route(self):
        """Open the best known APWorld goal/completion location in Path Explorer."""
        target=goal_target(self.snapshot)
        if target:
            self.open_path(target); return
        goal=self.snapshot.goal_detail or {}
        missing=goal.get("missing",[]) if isinstance(goal,dict) else []
        message="WayFinder could not yet map the APWorld goal to a concrete location or event."
        if missing:
            readable=[]
            for row in missing:
                if isinstance(row,dict):
                    name=str(row.get("name") or row.get("kind") or "Requirement")
                    detail=str(row.get("detail") or "").strip()
                    readable.append(f"{name}" + (f" — {detail}" if detail else ""))
                else:
                    readable.append(str(row))
            message += "\n\nKnown remaining goal requirements:\n• " + "\n• ".join(readable)
        options=goal.get("goal_options",{}) if isinstance(goal,dict) else {}
        if options:
            message += "\n\nResolved goal option(s):\n• " + "\n• ".join(f"{k}: {v}" for k,v in options.items())
        message += "\n\nWayFinder checked the generated APWorld completion condition, event/item producers, and resolved YAML goal options."
        ErrorHandler().show_info(message, "Goal Route")

    def _solver_waiting_report(self):
        """Explain whether remaining progression is local, remote, hinted, or unknown."""
        report=waiting_analysis(self.snapshot)
        lines=[report.summary,"",f"State: {report.state.upper()}"]
        if report.blockers: lines += ["","Known blockers:"]+[f"• {x}" for x in report.blockers]
        if report.hinted_sources: lines += ["","Hinted sources:"]+[f"• {x}" for x in report.hinted_sources]
        if report.remote_sources: lines += ["","Remote/multiworld context:"]+[f"• {x}" for x in report.remote_sources]
        if report.unknown_count: lines += ["",f"Unknown/untracked remaining checks: {report.unknown_count}"]
        if self.current_path:
            remote=remote_dependency_lines(self.snapshot,self.current_path)
            if remote: lines += ["","Remote dependencies on current solver route:"]+[f"• {x}" for x in remote]
        ErrorHandler().show_info("\n".join(lines), "What Am I Waiting For?")

    def _solver_reconstruction_audit(self):
        """Handle solver reconstruction audit."""
        if not self.current_path:
            ErrorHandler().show_info("Open a solver path first.", "APWorld Reconstruction Audit"); return
        findings=reconstruction_audit(self.current_path)
        provenance=provenance_rows(self.current_path)
        lines=["APWorld reconstruction audit",""]
        lines += (["Findings:"]+[f"• {x}" for x in findings]) if findings else ["No obvious reconstruction gaps were detected in this path."]
        lines += ["","Per-step provenance:"] + [f"• {x}" for x in provenance]
        ErrorHandler().show_info("\n".join(lines), "APWorld Reconstruction Audit")

    def _solver_search_graph(self):
        """Handle solver search graph."""
        query=self.path_search_var.get().strip().casefold()
        if not self.current_path or not query:
            return
        matches=[(label,kind) for label,kind in searchable_entries(self.current_path) if query in label.casefold() or query in kind.casefold()]
        if not matches:
            self.path_status.set(f"No solver graph nodes match {self.path_search_var.get()!r}."); return
        self.path_status.set(f"Graph search: {len(matches)} match(es) for {self.path_search_var.get()!r}: " + "; ".join(f"{kind} {label}" for label,kind in matches[:8]))
        self._draw_graph()

    def _render_path(self,result:PathResult):
        """Render a completed path result into text, graph, and rule-detail views."""
        self.current_path=result
        # Loop variable(s): `child` (child); each iteration represents the next value from the iterable below.
        for child in self.path_inner.winfo_children():child.destroy()
        if not result.found:
            self.path_status.set(result.error or f"Could not find {result.target}."); self.breadcrumb_var.set("—"); self._draw_graph(); self._draw_route_overlay(); return
        # Variable(s): `mode` (mode); named state retained for the surrounding calculation or subsequent calls.
        mode="Glitch logic" if result.using_glitches else "Normal logic"
        # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
        status=f"{result.target} • {mode} • {'Reachable' if result.reachable else 'Not reachable'}"
        if not result.reachable:
            status += " • Red steps/requirements are the current blockers"
        score,score_detail=route_score(result,self.route_strategy.get(),{"region_weight":self.personal_route_region_weight.get(),"requirement_penalty":self.personal_route_requirement_penalty.get()}); status += f" • {self.route_strategy.get()}: {score_detail}"
        cycles=path_cycles(result); dead=dead_route_reasons(result); remote=remote_dependency_lines(self.snapshot,result)
        if cycles: status += f" • CYCLE WARNING: {len(cycles)}"
        if dead: status += f" • Dead/downstream route warnings: {len(dead)}"
        if remote: status += f" • Remote dependency hints: {len(remote)}"
        self.path_status.set(status)
        # Variable(s): `crumbs` (crumbs); named state retained for the surrounding calculation or subsequent calls.
        crumbs=[]
        # Loop variable(s): `step` (step); each iteration represents the next value from the iterable below.
        for step in result.steps:
            # Loop variable(s): `r` (r); each iteration represents the next value from the iterable below.
            for r in (step.source_region,step.target_region):
                if r and (not crumbs or crumbs[-1]!=r):crumbs.append(r)
        # Variable(s): `crumbs` (crumbs); named state retained for the surrounding calculation or subsequent calls.
        if not crumbs:crumbs=[s.title for s in result.steps]
        self.breadcrumb_var.set(" > ".join(crumbs+[result.target] if crumbs and crumbs[-1]!=result.target else crumbs))
        # Loop variable(s): `idx` (index), `step` (step); each iteration represents the next value from the iterable below.
        for idx,step in enumerate(result.steps,1):
            # Variable(s): `card` (card); named state retained for the surrounding calculation or subsequent calls.
            card=ttk.Frame(self.path_inner,style="Card.TFrame",padding=11); card.pack(fill="x",padx=8,pady=5); mark="✓" if step.reachable is True else ("✕" if step.reachable is False else "•"); ttk.Label(card,text=f"{mark}  {idx}. {step.title}",style="CardHeading.TLabel").pack(anchor="w")
            if step.tree:self._render_rule_node(card,step.tree,0)
            elif step.tokens:ttk.Label(card,text=" ".join(str(t.get("text",t)) if isinstance(t,dict) else str(t) for t in step.tokens),style="CardTitle.TLabel",wraplength=900,justify="left").pack(anchor="w",pady=(6,0))
        self._draw_graph(); self._draw_route_overlay(); self._write_solver_output()

    def _rule_visual_root(self,node):
        """Remove opaque one-child wrappers so the meaningful boolean tree is visible."""
        # Variable(s): `cur` (cur); named state retained for the surrounding calculation or subsequent calls.
        cur=node
        while cur and (cur.kind or "").upper() not in ("OR","ANY","AND","ALL","COUNT","ATLEAST") and len(cur.children)==1:
            # Variable(s): `cur` (cur); named state retained for the surrounding calculation or subsequent calls.
            cur=cur.children[0]
        return cur

    def _rule_diagram_height(self,node):
        """Estimate the vertical canvas space needed for a recursive rule diagram."""
        # Variable(s): `node` (node); named state retained for the surrounding calculation or subsequent calls.
        node=self._rule_visual_root(node)
        if not node:return 0
        # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
        kind=(node.kind or "RULE").upper()
        if kind in ("OR","ANY","AND","ALL","COUNT","ATLEAST") and node.children:
            # Variable(s): `child_heights` (child heights); named state retained for the surrounding calculation or subsequent calls.
            child_heights=[self._rule_diagram_height(ch) for ch in node.children]
            return max(68,sum(child_heights)+14*max(0,len(child_heights)-1))
        if node.children:
            # Variable(s): `child_heights` (child heights); named state retained for the surrounding calculation or subsequent calls.
            child_heights=[self._rule_diagram_height(ch) for ch in node.children]
            return max(64,sum(child_heights)+12*max(0,len(child_heights)-1))
        return 64

    def _rule_visual_state(self,node):
        """Return the semantic state that the rule diagram should display.

        COUNT/comparison nodes are recomputed from their structured operator so the
        graph cannot show a colour that disagrees with the visible ``Have`` /
        ``Required`` expression. Boolean groups are then derived from those child
        states. Unknown/opaque nodes keep the runtime-provided state.
        """
        if node is None:
            return None
        kind=normalized_kind(getattr(node,"kind","") or "RULE")
        children=list(getattr(node,"children",None) or [])

        if kind == "COUNT" and getattr(node,"have",None) is not None and getattr(node,"required",None) is not None:
            have=getattr(node,"have")
            required=getattr(node,"required")
            operator=str(getattr(node,"operator",None) or ">=").strip()
            comparisons={
                ">=": lambda a,b:a>=b, ">": lambda a,b:a>b,
                "<=": lambda a,b:a<=b, "<": lambda a,b:a<b,
                "==": lambda a,b:a==b, "=": lambda a,b:a==b,
                "!=": lambda a,b:a!=b,
            }
            try:
                fn=comparisons.get(operator)
                if fn is not None:
                    return bool(fn(have,required))
            except TypeError:
                _ignored("intentional best-effort fallback")

        if children:
            states=[self._rule_visual_state(ch) for ch in children]
            known=[state for state in states if state is not None]
            if kind == "ALL":
                if any(state is False for state in known):
                    return False
                if len(known)==len(states) and all(state is True for state in known):
                    return True
                return None
            if kind == "ANY":
                if any(state is True for state in known):
                    return True
                if len(known)==len(states) and all(state is False for state in known):
                    return False
                return None
            if kind == "COUNT" and getattr(node,"required",None) is not None:
                required=int(getattr(node,"required") or 0)
                passed=sum(1 for state in states if state is True)
                if passed >= required:
                    return True
                unknown=sum(1 for state in states if state is None)
                if passed + unknown < required:
                    return False
                return None

        state=getattr(node,"satisfied",None)
        return state if state in (True,False) else None

    def _rule_node_caption(self,node):
        """Build the short human-readable caption displayed for a rule-tree node."""
        # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
        kind=normalized_kind(node.kind or "RULE")
        if kind == "ANY":
            # Variable(s): `passed` (passed); named state retained for the surrounding calculation or subsequent calls.
            passed=sum(1 for ch in node.children if self._rule_visual_state(ch) is True)
            return f"OR\nANY ONE  {passed}/{len(node.children)}"
        if kind == "ALL":
            # Variable(s): `passed` (passed); named state retained for the surrounding calculation or subsequent calls.
            passed=sum(1 for ch in node.children if self._rule_visual_state(ch) is True)
            return f"AND\nALL REQUIRED  {passed}/{len(node.children)}"
        if kind == "COUNT":
            # COUNT nodes must identify the thing being counted.  Older runtime
            # snapshots may still carry a generic detail string, so build the
            # display from the structured label/have/required fields whenever
            # they are available.
            counted=(node.label or "item").strip()
            if node.have is not None and node.required is not None:
                operator=(node.operator or ">=").strip()
                return f"COUNT\n{counted}\nHave: {node.have}   •   Required: {operator} {node.required}"
            detail=(node.detail or "").strip()
            return f"COUNT\n{counted}\n{detail}".strip()
        # Variable(s): `label` (label); named state retained for the surrounding calculation or subsequent calls.
        label=(node.label or kind).strip()
        # Variable(s): `detail` (detail); named state retained for the surrounding calculation or subsequent calls.
        detail=(node.detail or "").strip()
        if detail:
            return f"{kind}: {label}\n{detail}"
        return f"{kind}: {label}"

    def _draw_rule_diagram(self,canvas,node,left,top,right,tags=()):
        """Draw a real branching rule tree, left-to-right, and return its height."""
        # Variable(s): `node` (node); named state retained for the surrounding calculation or subsequent calls.
        node=self._rule_visual_root(node)
        if not node:return 0
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        p=self._palette(); green=p["success"]; red=p["danger"]; amber=p["warning"]
        neutral=p.get("border",p["muted"])
        # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
        kind=(node.kind or "RULE").upper(); h=self._rule_diagram_height(node)
        visual_state=self._rule_visual_state(node)
        state_color=green if visual_state is True else red if visual_state is False else amber
        # Variable(s): `is_group` (is group); named state retained for the surrounding calculation or subsequent calls.
        is_group=kind in ("OR","ANY","AND","ALL","COUNT","ATLEAST") and bool(node.children)
        # Boolean grouping boxes remain neutral so status colours only describe
        # actual semantic state, not container chrome. Their state is shown by a
        # small status marker in the top-right corner.
        color=neutral if is_group else state_color
        # Variable(s): `box_w` (box w); named state retained for the surrounding calculation or subsequent calls.
        box_w=150 if is_group else min(320,max(220,right-left-8))
        # Variable(s): `box_h` (box h); named state retained for the surrounding calculation or subsequent calls.
        box_h=54 if is_group else (68 if normalized_kind(node.kind or "RULE") == "COUNT" else 58)
        # Variable(s): `cy` (cy); named state retained for the surrounding calculation or subsequent calls.
        cy=top+h/2; y1=cy-box_h/2; y2=cy+box_h/2
        # Variable(s): `x1` (first x-coordinate); named state retained for the surrounding calculation or subsequent calls.
        x1=left; x2=min(left+box_w,right)
        node_fill=p["accent_soft"] if is_group else p["card_alt"]
        canvas.create_rectangle(x1,y1,x2,y2,fill=node_fill,outline=color,width=2,tags=tags)
        canvas.create_text((x1+x2)/2,cy,text=self._rule_node_caption(node),fill=p["fg"],font=("Segoe UI Semibold",max(9,self.font_size.get() if is_group else self.font_size.get()-1)),width=max(100,x2-x1-12),justify="center",tags=tags)
        if is_group:
            marker_r=5
            canvas.create_oval(x2-marker_r-7,y1+7,x2+marker_r-7,y1+7+marker_r*2,fill=state_color,outline="",tags=tags)
        if not node.children:return h

        # Variable(s): `next_left` (next left); named state retained for the surrounding calculation or subsequent calls.
        next_left=min(left+190,right-220)
        # Variable(s): `child_heights` (child heights); named state retained for the surrounding calculation or subsequent calls.
        child_heights=[self._rule_diagram_height(ch) for ch in node.children]
        # Variable(s): `total` (total); named state retained for the surrounding calculation or subsequent calls.
        total=sum(child_heights)+14*max(0,len(child_heights)-1)
        # Variable(s): `child_top` (child top); named state retained for the surrounding calculation or subsequent calls.
        child_top=top+(h-total)/2
        # Variable(s): `centers` (centers); named state retained for the surrounding calculation or subsequent calls.
        centers=[]
        # Loop variable(s): `ch` (ch), `ch_h` (ch h); each iteration represents the next value from the iterable below.
        for ch,ch_h in zip(node.children,child_heights):
            centers.append(child_top+ch_h/2)
            child_top+=ch_h+14
        if centers:
            # Variable(s): `bus_x` (bus x); named state retained for the surrounding calculation or subsequent calls.
            bus_x=min(x2+20,next_left-18)
            canvas.create_line(x2,cy,bus_x,cy,fill=neutral if is_group else state_color,width=2,tags=tags)
            if len(centers)>1:
                canvas.create_line(bus_x,min(centers),bus_x,max(centers),fill=p["muted"],width=2,tags=tags)
            # Variable(s): `child_top` (child top); named state retained for the surrounding calculation or subsequent calls.
            child_top=top+(h-total)/2
            # Loop variable(s): `ch` (ch), `ch_h` (ch h), `ch_cy` (ch cy); each iteration represents the next value from the iterable below.
            for ch,ch_h,ch_cy in zip(node.children,child_heights,centers):
                # Variable(s): `branch_color` (branch color); named state retained for the surrounding calculation or subsequent calls.
                child_state=self._rule_visual_state(ch)
                branch_color=green if child_state is True else red if child_state is False else amber
                canvas.create_line(bus_x,ch_cy,next_left,ch_cy,fill=branch_color,width=2,arrow="last",tags=tags)
                self._draw_rule_diagram(canvas,ch,next_left,child_top,right,tags)
                child_top+=ch_h+14
        return h

    def _walk_rule_nodes(self,node):
        """Handle walk rule nodes."""
        if node is None:return []
        rows=[node]
        for child in getattr(node,"children",[]) or []: rows.extend(self._walk_rule_nodes(child))
        return rows

    def _draw_graph(self):
        """Draw the high-level route graph for the current path result."""
        if not hasattr(self,"graph_canvas"):return
        # Variable(s): `c` (c); named state retained for the surrounding calculation or subsequent calls.
        c=self.graph_canvas;c.delete("all"); result=self.current_path
        if not result or not result.found:
            c.create_text(30,30,anchor="nw",text="No path loaded.",fill=self._palette()["muted"],font=("Segoe UI",self.font_size.get()));return
        # Variable(s): `width` (width); named state retained for the surrounding calculation or subsequent calls.
        width=max(c.winfo_width(),760); cx=width//2; y=35; box_w=min(760,width-70)
        # Variable(s): `prev_bottom` (prev bottom); named state retained for the surrounding calculation or subsequent calls.
        prev_bottom=None
        # Loop variable(s): `i` (index), `step` (step); each iteration represents the next value from the iterable below.
        for i,step in enumerate(result.steps):
            # Variable(s): `tree` (tree); named state retained for the surrounding calculation or subsequent calls.
            tree=self._rule_visual_root(step.tree) if step.tree else None
            # Variable(s): `diagram_h` (diagram h); named state retained for the surrounding calculation or subsequent calls.
            diagram_h=self._rule_diagram_height(tree) if tree else 0
            # Variable(s): `box_h` (box h); named state retained for the surrounding calculation or subsequent calls.
            box_h=70+(diagram_h+18 if diagram_h else 0)
            # Variable(s): `color` (color); named state retained for the surrounding calculation or subsequent calls.
            color=STATUS_VISUALS["reachable"]["color"] if step.reachable is True else STATUS_VISUALS["out_of_logic"]["color"] if step.reachable is False else STATUS_VISUALS["glitched"]["color"]
            if prev_bottom is not None:
                c.create_line(cx,prev_bottom,cx,y-8,fill=color,width=3,arrow="last")
            # Variable(s): `x1` (first x-coordinate); named state retained for the surrounding calculation or subsequent calls.
            x1=cx-box_w//2;x2=cx+box_w//2;y1=y;y2=y+box_h; tag=f"step{i}"
            query=self.path_search_var.get().strip().casefold() if hasattr(self,"path_search_var") else ""
            search_text=" ".join([step.title,step.kind]+[str(getattr(n,"label","")) for n in ([*self._walk_rule_nodes(tree)] if tree else [])]).casefold()
            highlight=bool(query and query in search_text)
            c.create_rectangle(x1,y1,x2,y2,fill=self._palette()["card"],outline=color,width=5 if highlight else 2,tags=(tag,))
            # Variable(s): `title` (title); named state retained for the surrounding calculation or subsequent calls.
            title=("✓  " if step.reachable is True else "✕  " if step.reachable is False else "•  ")+step.title
            c.create_text(cx,y+20,text=title,fill=self._palette()["fg"],font=("Segoe UI Semibold",self.font_size.get()),width=box_w-30,tags=(tag,))
            # Variable(s): `region` (region); named state retained for the surrounding calculation or subsequent calls.
            region=step.target_region or step.source_region
            c.create_text(cx,y+44,text=region or step.kind,fill=self._palette()["muted"],font=("Segoe UI",max(8,self.font_size.get()-1)),tags=(tag,))
            if tree:
                self._draw_rule_diagram(c,tree,x1+26,y+66,x2-26,tags=(tag,))
            # Variable(s): `prev_bottom` (prev bottom); named state retained for the surrounding calculation or subsequent calls.
            c.tag_bind(tag,"<Button-1>",lambda _e,idx=i:self._show_graph_step(idx)); prev_bottom=y2;y+=box_h+38
        c.configure(scrollregion=(0,0,width,y+30))

    def _show_graph_step(self,index):
        """Display detailed rule information for the graph step selected by the user."""
        if not self.current_path or index>=len(self.current_path.steps):return
        # Variable(s): `step` (step); named state retained for the surrounding calculation or subsequent calls.
        step=self.current_path.steps[index]
        # Variable(s): `win` (window); named state retained for the surrounding calculation or subsequent calls.
        win=tk.Toplevel(self.root); win.configure(bg=self._palette()["bg"]); win.title(step.title); win.transient(self.root); win.geometry("900x520")
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        p=self._palette(); win.configure(bg=p["bg"])
        ttk.Label(win,text=step.title,style="Title.TLabel",wraplength=840).pack(anchor="w",padx=18,pady=(16,4))
        ttk.Label(win,text="Requirement diagram",style="Muted.TLabel").pack(anchor="w",padx=18,pady=(0,8))
        # Variable(s): `wrap` (wrap); named state retained for the surrounding calculation or subsequent calls.
        wrap=ttk.Frame(win); wrap.pack(fill="both",expand=True,padx=14,pady=(0,14))
        # Variable(s): `canvas` (canvas); named state retained for the surrounding calculation or subsequent calls.
        canvas=tk.Canvas(wrap,bg=p["panel"],highlightthickness=0); vs=ttk.Scrollbar(wrap,orient="vertical",command=canvas.yview); hs=ttk.Scrollbar(wrap,orient="horizontal",command=canvas.xview)
        vs.pack(side="right",fill="y"); hs.pack(side="bottom",fill="x"); canvas.pack(side="left",fill="both",expand=True); canvas.configure(yscrollcommand=vs.set,xscrollcommand=hs.set)
        # Variable(s): `tree` (tree); named state retained for the surrounding calculation or subsequent calls.
        tree=self._rule_visual_root(step.tree) if step.tree else None
        if tree:
            # Variable(s): `h` (height/handle value (context dependent)); named state retained for the surrounding calculation or subsequent calls.
            h=max(120,self._rule_diagram_height(tree)+30); self._draw_rule_diagram(canvas,tree,24,20,1220); canvas.configure(scrollregion=(0,0,1260,h))
        else:
            canvas.create_text(24,24,anchor="nw",text="No structured rule details.",fill=p["muted"],font=("Segoe UI",self.font_size.get()))
            canvas.configure(scrollregion=(0,0,850,100))

    def _render_rule_node(self,parent,node:RuleNode,depth:int):
        # Boolean expressions are much easier to understand as a branch diagram than as nested prose.
        """Render one rule node and its descendants as structured text."""
        # Variable(s): `tree` (tree); named state retained for the surrounding calculation or subsequent calls.
        tree=self._rule_visual_root(node)
        if depth==0 and tree:
            # Variable(s): `h` (height/handle value (context dependent)); named state retained for the surrounding calculation or subsequent calls.
            h=max(58,self._rule_diagram_height(tree)+14)
            # Variable(s): `canvas` (canvas); named state retained for the surrounding calculation or subsequent calls.
            canvas=tk.Canvas(parent,height=h,bg=self._palette()["card"],highlightthickness=0)
            canvas.pack(fill="x",pady=(8,2))
            canvas.bind("<Configure>",lambda e,n=tree,cv=canvas:self._redraw_detail_rule_canvas(cv,n,e.width))
            return
        # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
        kind=(node.kind or "RULE").upper(); symbol="✓" if node.satisfied is True else ("✕" if node.satisfied is False else "•")
        # Variable(s): `label` (label); named state retained for the surrounding calculation or subsequent calls.
        label=f"{symbol} {kind}: {node.label}"+(f"   {node.detail}" if node.detail else "")
        ttk.Label(parent,text=label,style="CardTitle.TLabel",font=("Segoe UI",max(8,self.font_size.get()-1)),wraplength=920,justify="left").pack(anchor="w",padx=(depth*12,0),pady=1)
        # Loop variable(s): `ch` (ch); each iteration represents the next value from the iterable below.
        for ch in node.children:self._render_rule_node(parent,ch,depth+1)

    def _redraw_detail_rule_canvas(self,canvas,node,width):
        """Redraw the selected rule tree when the detail canvas changes size/state."""
        canvas.delete("all")
        # Variable(s): `w` (width/widget value (context dependent)); named state retained for the surrounding calculation or subsequent calls.
        w=max(640,width)
        # Variable(s): `h` (height/handle value (context dependent)); named state retained for the surrounding calculation or subsequent calls.
        h=max(58,self._rule_diagram_height(node)+14)
        canvas.configure(height=h,scrollregion=(0,0,w,h))
        self._draw_rule_diagram(canvas,node,12,7,w-12)

    def _rule_text(self,node,depth=0):
        """Convert a rule tree into copy/export-friendly plain text."""
        if not node:return "No structured requirement tree available."
        # Variable(s): `symbol` (symbol); named state retained for the surrounding calculation or subsequent calls.
        symbol="✓" if node.satisfied is True else "✕" if node.satisfied is False else "•"
        # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
        kind=(node.kind or "RULE").upper()
        # Variable(s): `head` (head); named state retained for the surrounding calculation or subsequent calls.
        if kind in ("OR","ANY"): head=f"{'  '*depth}{symbol} OR — ANY ONE"
        # Variable(s): `head` (head); named state retained for the surrounding calculation or subsequent calls.
        elif kind in ("AND","ALL"): head=f"{'  '*depth}{symbol} AND — ALL REQUIRED"
        # Variable(s): `head` (head); named state retained for the surrounding calculation or subsequent calls.
        else: head=f"{'  '*depth}{symbol} {kind}: {node.label}"
        if node.kind == "item_count" and node.have is not None and node.operator:
            head += f" — {node.label}: have {node.have}, need {node.operator} {node.required}"
        elif node.detail:head+=f" ({node.detail})"
        children=rank_or_branches(node)
        if self.path_collapse_satisfied.get() and depth>0 and node.satisfied is True and children:
            return head + " [satisfied branch collapsed]"
        return "\n".join([head]+[self._rule_text(ch,depth+1) for ch in children])

    def _path_text(self,markdown=False):
        """Build the complete plain-text representation of a path-analysis result."""
        # Variable(s): `r` (r); named state retained for the surrounding calculation or subsequent calls.
        r=self.current_path
        if not r:return "No path loaded."
        # Variable(s): `lines` (lines); named state retained for the surrounding calculation or subsequent calls.
        lines=[f"# {r.target}" if markdown else r.target,f"Logic: {'Glitch' if r.using_glitches else 'Normal'} | {'Reachable' if r.reachable else 'Not reachable'}",""]
        # Mark the first currently actionable blocker separately from requirements
        # that only become relevant after that blocker is cleared.
        first_blocker = next((i for i, step in enumerate(r.steps) if step.kind != "region" and step.reachable is False), None)
        for i,s in enumerate(r.steps,1):
            if first_blocker is not None and (i - 1) == first_blocker:
                lines.append("BLOCKING NOW" if not markdown else "### Blocking now")
            elif first_blocker is not None and (i - 1) > first_blocker and s.kind == "entrance":
                if not any(x in lines for x in ("LATER REQUIREMENTS ON THIS ROUTE", "### Later requirements on this route")):
                    lines.append("LATER REQUIREMENTS ON THIS ROUTE" if not markdown else "### Later requirements on this route")
            elif s.kind == "location" and first_blocker is not None and (i - 1) > first_blocker:
                lines.append("DESTINATION REQUIREMENTS" if not markdown else "### Destination requirements")
            lines.append(f"{'## ' if markdown else ''}{i}. {s.title}")
            lines.append(self._rule_text(s.tree)); lines.append("")
        return "\n".join(lines)

    def _solver_output_text(self):
        """Build a deliberately verbose, shareable solver diagnostic transcript."""
        result=self.current_path
        generated=datetime.now().astimezone().isoformat(timespec="seconds")
        lines=["WayFinder solver output",f"Generated: {generated}",f"WayFinder: {GUI_VERSION}",""]
        if not result:
            lines.append("No path loaded.")
            return "\n".join(lines)+"\n"
        lines.extend([
            f"Target: {result.target}",
            f"Found: {bool(result.found)}",
            f"Reachable: {bool(result.reachable)}",
            f"Logic mode: {'glitch' if result.using_glitches else 'normal'}",
        ])
        if getattr(result,"error",""): lines.append(f"Error: {result.error}")
        cycles=path_cycles(result); dead=dead_route_reasons(result); remote=remote_dependency_lines(self.snapshot,result); audit=reconstruction_audit(result); provenance=provenance_rows(result)
        lines.extend(["", "Solver intelligence:", "Rule normalization: ALL / ANY / COUNT / EVENT / REGION / OPTION / COMPARISON / UNKNOWN"])
        lines.append("OR branch ranking: enabled (fewest missing predicates, then missing quantity, then branch complexity).")
        lines.append("Cycle detection: " + ("; ".join(cycles) if cycles else "no cycle detected on selected route"))
        lines.append("Dead-route detection: " + ("; ".join(dead) if dead else "no downstream/dead-route warning"))
        lines.append("Remote dependency awareness: " + ("; ".join(remote) if remote else "no remote dependency proven by available hint metadata"))
        lines.extend(["", "Per-step provenance:"] + ([f"- {x}" for x in provenance] if provenance else ["- none available"]))
        lines.extend(["", "APWorld reconstruction audit:"] + ([f"- {x}" for x in audit] if audit else ["- no obvious reconstruction gap detected on this route"]))
        lines.extend(["", "Rendered solver path:", self._path_text(False), "", "Raw path result:"])
        try:
            lines.append(json.dumps(asdict(result),indent=2,ensure_ascii=False,default=str))
        except Exception as exc:
            lines.append(f"Raw serialization unavailable: {exc}")
            lines.append(repr(result))
        return "\n".join(lines)+"\n"

    def _solver_output_paths(self):
        """Return the stable latest path and a timestamped history path."""
        output_dir=APP_DATA_ROOT / "logs" / "solver"
        output_dir.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S_%f")
        return output_dir / "solver-output.txt", output_dir / f"solver-output-{stamp}.txt"

    def _write_solver_output(self):
        """Automatically persist every completed Path Explorer solver result as text."""
        if not self.current_path:return None
        try:
            latest,history=self._solver_output_paths(); text=self._solver_output_text()
            latest.write_text(text,encoding="utf-8"); history.write_text(text,encoding="utf-8")
            self._latest_solver_output_path=latest
            return latest
        except Exception as exc:
            self._append_log(f"Solver output write failed: {exc}")
            return None

    def open_solver_output(self):
        """Open the latest automatically generated solver transcript."""
        path=getattr(self,"_latest_solver_output_path",None)
        if not path or not Path(path).exists(): path=self._write_solver_output()
        if not path:return
        try:
            if os.name=="nt": os.startfile(str(path))
            elif sys.platform=="darwin": subprocess.Popen(["open",str(path)])
            else: subprocess.Popen(["xdg-open",str(path)])
        except Exception as exc:
            ErrorHandler().handle_error(exc, "WayFinder could not open the solver output. Check the output folder permissions and try again.", "Open Output Error", error_code="WF-SOLVER-001")

    def copy_path(self):
        """Copy the current logical-path explanation to the system clipboard."""
        # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
        text=self._path_text(False); self.root.clipboard_clear(); self.root.clipboard_append(text)

    def export_path(self):
        """Export the current logical-path explanation to a user-selected text file."""
        if not self.current_path:return
        # Variable(s): `path` (path); named state retained for the surrounding calculation or subsequent calls.
        path=filedialog.asksaveasfilename(defaultextension=".md",filetypes=[("Markdown","*.md"),("Text","*.txt")],initialfile="logical-path.md")
        if path:Path(path).write_text(self._path_text(path.lower().endswith(".md")),encoding="utf-8")

