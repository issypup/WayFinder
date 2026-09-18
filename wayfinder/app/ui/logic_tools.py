"""Provide logic tools support."""
# /**
#  * Module: wayfinder/app/ui/logic_tools.py
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

class LogicToolsMixin:
    """Provide logic tools mixin behavior."""
    def _record_logic_regression(self):
        """Handle record logic regression."""
        s=self.snapshot
        record={"time":datetime.now().isoformat(timespec="seconds"),"game":s.game,"slot":s.slot_name,"sequence":s.snapshot_sequence,"reachable":sorted(getattr(s,"normal_reachable_locations",[]) or []),"glitch":sorted(getattr(s,"glitch_reachable_locations",[]) or []),"regions":sorted(getattr(s,"current_reachable_regions",[]) or getattr(s,"in_logic_regions",[]) or []),"goal":dict(s.goal_detail or {}),"warnings":list(s.logic_warnings or []),"unsupported":list(s.unsupported_state_calls or [])}
        self.logic_regression_records.append(record); self.logic_regression_records=self.logic_regression_records[-100:]
        if len(self.logic_regression_records)>1:
            a,b=self.logic_regression_records[-2:]; lost=sorted(set(a["reachable"])-set(b["reachable"])); gained=sorted(set(b["reachable"])-set(a["reachable"]))
            self.logic_detail.set(f"Regression #{len(self.logic_regression_records)} recorded • gained {len(gained)} reachable • lost {len(lost)} reachable"+(f" • LOST: {', '.join(lost[:6])}" if lost else ""))
        else:self.logic_detail.set("Regression baseline recorded. Record again after a logic/state change to compare.")
    def _export_logic_regressions(self):
        """Handle export logic regressions."""
        if not self.logic_regression_records: self._record_logic_regression()
        path=filedialog.asksaveasfilename(title="Export Logic Regression Records",defaultextension=".json",filetypes=[("JSON","*.json")],initialfile="wayfinder-logic-regressions.json")
        if path: Path(path).write_text(json.dumps(sanitize(self.logic_regression_records),indent=2,ensure_ascii=False),encoding="utf-8")
    def _build_logic_engine(self):
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        """Handle build logic engine."""
        p=self._page("Logic Engine"); ttk.Label(p,text="WayFinder Native Logic Engine",style="Title.TLabel").pack(anchor="w",pady=(4,6))
        self.compare_summary=tk.StringVar(value="Waiting for the first native logic snapshot."); ttk.Label(p,textvariable=self.compare_summary,style="Muted.TLabel",wraplength=1050,justify="left").pack(anchor="w",pady=(0,6))
        # Variable(s): `filt` (filt); named state retained for the surrounding calculation or subsequent calls.
        filt=ttk.Frame(p); filt.pack(fill="x",pady=(0,6)); ttk.Label(filt,text="Search location / area / rule:").pack(side="left"); self.logic_filter=tk.StringVar(); e=ttk.Entry(filt,textvariable=self.logic_filter); e.pack(side="left",fill="x",expand=True,padx=6); e.bind("<KeyRelease>",lambda _e:self._refresh_logic_engine()); ttk.Button(filt,style="Accent.TButton",text="Export regression",command=self._export_logic_regressions).pack(side="right",padx=(6,0)); ttk.Button(filt,style="Accent.TButton",text="Record regression",command=self._record_logic_regression).pack(side="right",padx=(6,0)); ttk.Button(filt,style="Accent.TButton",text="Go-mode requirements",command=self._show_goal_requirements).pack(side="right")
        self.compare_tree=ttk.Treeview(p,columns=("Type","Detail","Result","Module"),show="headings");
        # Loop variable(s): `c` (c), `w` (width/widget value (context dependent)); each iteration represents the next value from the iterable below.
        for c,w in (("Type",170),("Detail",530),("Result",130),("Module",260)): self.compare_tree.heading(c,text=c); self.compare_tree.column(c,width=w,anchor="w")
        self.compare_tree.pack(fill="both",expand=True); self.compare_tree.bind("<Double-1>",self._logic_row_open)
        self.logic_detail=tk.StringVar(value="Double-click a location/entrance/event to inspect the predicates its APWorld rule consulted."); ttk.Label(p,textvariable=self.logic_detail,style="Muted.TLabel",wraplength=1050,justify="left").pack(anchor="w",pady=(6,0)); self._refresh_logic_engine()
    def _refresh_logic_engine(self):
        """Handle refresh logic engine."""
        if not hasattr(self,"compare_tree"): return
        # Variable(s): `s` (s); named state retained for the surrounding calculation or subsequent calls.
        self._clear_tree(self.compare_tree); s=self.snapshot
        if not getattr(s,"updated_at",""): self.compare_summary.set("Waiting for the first native logic snapshot."); return
        # Variable(s): `normal` (normal); named state retained for the surrounding calculation or subsequent calls.
        normal=set(getattr(s,"normal_reachable_locations",[]) or []); glitch=set(getattr(s,"glitch_reachable_locations",[]) or []); rules=getattr(s,"rule_details",{}) or {}; entrances=getattr(s,"entrance_details",[]) or []; events=getattr(s,"event_details",[]) or []
        self.compare_summary.set(f"Engine {s.engine_version} • Reachable {len(normal)} • Glitch-only {len(glitch)} • Regions {len(s.current_reachable_regions or s.in_logic_regions)} • Rules {len(rules)} • Entrances {len(entrances)} • Events {len(events)} • Unsupported APIs {len(s.unsupported_state_calls)}")
        # Variable(s): `q` (q); named state retained for the surrounding calculation or subsequent calls.
        q=self.logic_filter.get().strip().casefold(); rows=[]
        # Variable(s): `goal` (goal); named state retained for the surrounding calculation or subsequent calls.
        goal=s.goal_detail or {}; rows.append(("Completion condition","Goal / go-mode","LOGIC ERROR" if goal.get("error") else "SATISFIED" if goal.get("satisfied") else "NOT YET",goal.get("module","")))
        # Loop variable(s): `name` (name), `d` (d); each iteration represents the next value from the iterable below.
        for name,d in rules.items():
            # Variable(s): `result` (result); named state retained for the surrounding calculation or subsequent calls.
            loc = next((x for x in s.locations if x.name == name), None)
            result = 'Unknown / logic error' if d.get('error') else 'Unknown' if getattr(loc, 'status', '') == 'unknown' else 'Impossible rule' if d.get('impossible_rule') else 'Reachable' if name in normal else 'Glitch' if name in glitch else 'Blocked' 
            # Variable(s): `miss` (miss); named state retained for the surrounding calculation or subsequent calls.
            miss=d.get("missing",[]) or []; detail=name + ((" • missing: "+", ".join(x.get("name","") for x in miss[:4])) if miss else "")
            rows.append(("Location rule",detail,result,d.get("module","")))
        # Loop variable(s): `d` (d); each iteration represents the next value from the iterable below.
        for d in entrances: rows.append(("Entrance rule",f"{d.get('name','')} • {d.get('source_region','')} → {d.get('target_region','')}","Logic error" if d.get("error") else "Impossible rule" if d.get("impossible_rule") else "Reachable" if d.get("reachable") else "Blocked",d.get("module","")))
        # Loop variable(s): `d` (d); each iteration represents the next value from the iterable below.
        for d in events: rows.append(("Event rule",f"{d.get('name','')} → {d.get('event_item','')}","Logic error" if d.get("error") else "Impossible rule" if d.get("impossible_rule") else "Swept" if d.get("swept") else "Pending",d.get("module","")))
        # Loop variable(s): `x` (horizontal x-coordinate); each iteration represents the next value from the iterable below.
        for x in s.unsupported_state_calls: rows.append(("Unsupported API",str(x),"ERROR","NativeAPState"))
        # Loop variable(s): `kind` (kind), `detail` (detail), `result` (result), `module` (module); each iteration represents the next value from the iterable below.
        for kind,detail,result,module in rows:
            if q and q not in f"{kind} {detail} {result} {module}".casefold(): continue
            self.compare_tree.insert("","end",values=(kind,detail,result,module))
    def _logic_row_open(self,_e=None):
        """Handle logic row open."""
        if not self.compare_tree.selection(): return
        # Variable(s): `vals` (vals); named state retained for the surrounding calculation or subsequent calls.
        vals=self.compare_tree.item(self.compare_tree.selection()[0],"values"); kind,detail=vals[0],vals[1]; name=str(detail).split(" • ",1)[0]
        if kind=="Completion condition": self._show_goal_requirements()
        elif kind=="Location rule": self._show_logic_explanation(name,False)
        elif kind=="Entrance rule":
            # Variable(s): `d` (d); named state retained for the surrounding calculation or subsequent calls.
            d=next((x for x in self.snapshot.entrance_details if x.get("name")==name),{}); self._show_rule_dialog(name,d)
        elif kind=="Event rule":
            # Variable(s): `d` (d); named state retained for the surrounding calculation or subsequent calls.
            d=next((x for x in self.snapshot.event_details if x.get("name")==name),{}); self._show_rule_dialog(name,d)
    def _show_logic_text(self, title, lines):
        """Handle show logic text."""
        from tkinter.scrolledtext import ScrolledText
        from wayfinder.diagnostics import sanitize
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry('950x680')
        viewer = ScrolledText(window, wrap='word', padx=12, pady=12)
        viewer.pack(fill='both', expand=True)
        viewer.insert('1.0', '\n'.join(sanitize(lines)))
        viewer.configure(state='disabled')
        ttk.Button(window, text='Close', command=window.destroy).pack(pady=6)
    def _show_rule_dialog(self,title,d,missing_only=False):
        # Variable(s): `consulted` (consulted); named state retained for the surrounding calculation or subsequent calls.
        """Handle show rule dialog."""
        consulted=d.get("consulted",[]) or []; missing=d.get("missing",[]) or []; rows=missing if missing_only else consulted
        # Variable(s): `lines` (lines); named state retained for the surrounding calculation or subsequent calls.
        lines=[f"Result: {'UNKNOWN — LOGIC ERROR' if d.get('error') else 'SATISFIED' if d.get('satisfied') else 'BLOCKED'}",f"Rule module: {d.get('module','unknown')}"]
        if d.get("error"): lines.append(f"Error: {d['error']}")
        lines.append("\nMissing requirements:" if missing_only else "\nConsulted predicates:")
        if not rows: lines.append("• No traceable CollectionState predicates. The APWorld rule may use an opaque helper/direct prog_items access.")
        # Loop variable(s): `x` (horizontal x-coordinate); each iteration represents the next value from the iterable below.
        for x in rows: lines.append(f"• {'✓' if x.get('result') else '✗'} {x.get('kind')}: {x.get('name')} — {x.get('detail','')}")
        from wayfinder.logic.rule_explanation import explanation_lines
        lines.extend(explanation_lines(d))
        self._show_logic_text(title, lines)
    def _show_logic_explanation(self,name,missing_only=False):
        # A location access rule is only one part of final APWorld reachability.
        """Handle show logic explanation."""
        d=(getattr(self.snapshot,"rule_details",{}) or {}).get(name)
        if not d:
            ErrorHandler().show_info(f"No generated APWorld rule record is available for {name}.", "Logic explanation"); return
        normal=set(getattr(self.snapshot,"normal_reachable_locations",[]) or [])
        glitch=set(getattr(self.snapshot,"glitch_reachable_locations",[]) or [])
        loc = next((x for x in self.snapshot.locations if getattr(x, 'name', '') == name), None)
        overall = ('UNKNOWN — ' + getattr(loc, 'unknown_reason', 'Logic unavailable')) if getattr(loc, 'status', '') == 'unknown' else 'REACHABLE' if name in normal else 'GLITCH-ONLY' if name in glitch else 'BLOCKED'
        if d.get('error'): overall = 'UNKNOWN — LOGIC ERROR'
        
        parent_region=str(getattr(loc, "region", "") or "")
        for row in (getattr(self.snapshot,"locations",[]) or []):
            if isinstance(row,dict) and row.get("name")==name:
                parent_region=str(row.get("region","") or ""); break
        reachable_regions=set(getattr(self.snapshot,"current_reachable_regions",[]) or getattr(self.snapshot,"in_logic_regions",[]) or [])
        region_reachable=(parent_region in reachable_regions) if parent_region else None
        consulted=d.get("consulted",[]) or []; missing=d.get("missing",[]) or []; rows=missing if missing_only else consulted
        local_satisfied=bool(d.get("satisfied"))
        lines=[f"Overall status: {overall}",f"Location rule: {'UNKNOWN — LOGIC ERROR' if d.get('error') else 'SATISFIED' if local_satisfied else 'BLOCKED'}",f"Rule module: {d.get('module','unknown')}"]
        if parent_region: lines.append(f"Parent region: {parent_region} — {'REACHABLE' if region_reachable else 'BLOCKED'}")
        if overall=="BLOCKED" and local_satisfied:
            if parent_region and region_reachable is False: lines.append("\nWhy blocked: The location rule passes, but its parent region is not currently reachable through the APWorld entrance/region graph.")
            else: lines.append("\nWhy blocked: The location rule passes, but another part of the APWorld reachability path is currently blocking access.")
        if d.get("error"): lines.append(f"Error: {d['error']}")
        lines.append("\nMissing requirements:" if missing_only else "\nConsulted predicates:")
        if not rows: lines.append("• No traceable CollectionState predicates. The APWorld rule may use an opaque helper/direct prog_items access.")
        for x in rows: lines.append(f"• {'✓' if x.get('result') else '✗'} {x.get('kind')}: {x.get('name')} — {x.get('detail','')}")
        from wayfinder.logic.rule_explanation import explanation_lines
        lines.extend(explanation_lines(d))
        self._show_logic_text(("Missing requirements — " if missing_only else "Why — ")+name, lines)
    def _show_goal_requirements(self): self._show_rule_dialog("Go-mode / Completion Condition",getattr(self.snapshot,"goal_detail",{}) or {},True)
    def _show_datastorage_index(self):
        """Show cheap DataStorage metadata and fetch values only when the user asks to inspect one."""
        top = tk.Toplevel(self.root)
        top.configure(bg=self._palette()["bg"])
        top.title("DataStorage Index")
        top.geometry("920x560")

        ttk.Label(top, text="DataStorage Index", style="Title.TLabel").pack(anchor="w", padx=10, pady=(10, 2))
        ttk.Label(
            top,
            text="Values are fetched on demand. Double-click a row, or select it and choose View Selected.",
            style="Muted.TLabel",
        ).pack(anchor="w", padx=10, pady=(0, 8))

        search_value = tk.StringVar()
        search_entry = ttk.Entry(top, textvariable=search_value)
        search_entry.pack(fill="x", padx=10, pady=(0, 6))

        tree = ttk.Treeview(top, columns=("Key", "Type", "Size"), show="headings", selectmode="browse")
        for column_name, width in (("Key", 640), ("Type", 140), ("Size", 100)):
            tree.heading(column_name, text=column_name)
            tree.column(column_name, width=width, anchor="w")
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        actions = ttk.Frame(top)
        actions.pack(fill="x", padx=10, pady=(0, 10))
        view_button = ttk.Button(actions, text="View Selected", state="disabled")
        view_button.pack(side="left")
        ttk.Button(actions, text="Close", command=top.destroy).pack(side="right")

        def selected_key() -> str:
            """Handle selected key."""
            selection = tree.selection()
            if not selection:
                return ""
            values = tree.item(selection[0], "values")
            return str(values[0]) if values else ""

        def update_button(*_args) -> None:
            """Handle update button."""
            view_button.configure(state="normal" if selected_key() else "disabled")

        def view_selected(*_args) -> None:
            """Handle view selected."""
            key = selected_key()
            if key:
                self._show_datastorage_value(key, parent=top)

        def fill(*_args) -> None:
            """Handle fill."""
            self._clear_tree(tree)
            needle = search_value.get().casefold().strip()
            for row in self.snapshot.datastorage_index or []:
                key = str(row.get("key", ""))
                if needle and needle not in key.casefold():
                    continue
                tree.insert("", "end", values=(key, row.get("type", ""), row.get("size", -1)))
            update_button()

        view_button.configure(command=view_selected)
        tree.bind("<<TreeviewSelect>>", update_button)
        tree.bind("<Double-1>", view_selected)
        tree.bind("<Return>", view_selected)
        search_value.trace_add("write", fill)
        fill()
        search_entry.focus_set()
    def _show_datastorage_value(self, key: str, parent=None):
        """Open a viewer for one live DataStorage value without bloating tracker snapshots."""
        viewer = tk.Toplevel(parent or self.root)
        viewer.configure(bg=self._palette()["bg"])
        viewer.title(f"DataStorage Value — {key}")
        viewer.geometry("1000x680")

        title = ttk.Label(viewer, text=key, style="Title.TLabel")
        title.pack(anchor="w", padx=10, pady=(10, 2))

        status_text = tk.StringVar(value="Requesting current value from the WayFinder runtime…")
        ttk.Label(viewer, textvariable=status_text, style="Muted.TLabel").pack(anchor="w", padx=10, pady=(0, 8))

        notebook = ttk.Notebook(viewer)
        notebook.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        structured_frame = ttk.Frame(notebook)
        raw_frame = ttk.Frame(notebook)
        notebook.add(structured_frame, text="Structured")
        notebook.add(raw_frame, text="Raw JSON")

        value_tree = ttk.Treeview(
            structured_frame,
            columns=("Type", "Value"),
            show="tree headings",
        )
        value_tree.heading("#0", text="Key / Index")
        value_tree.heading("Type", text="Type")
        value_tree.heading("Value", text="Value")
        value_tree.column("#0", width=360, anchor="w")
        value_tree.column("Type", width=110, anchor="w")
        value_tree.column("Value", width=500, anchor="w")
        value_tree.pack(side="left", fill="both", expand=True)

        tree_scroll = ttk.Scrollbar(structured_frame, orient="vertical", command=value_tree.yview)
        tree_scroll.pack(side="right", fill="y")
        value_tree.configure(yscrollcommand=tree_scroll.set)

        raw_text = tk.Text(raw_frame, wrap="none", bg=self._palette()["panel"], fg=self._palette()["fg"], insertbackground=self._palette()["fg"], font=("Segoe UI",self.font_size.get()), relief="flat", highlightthickness=1, highlightbackground=self._palette()["border"], highlightcolor=self._palette()["accent"], padx=8, pady=8)
        raw_text.pack(side="left", fill="both", expand=True)
        raw_y = ttk.Scrollbar(raw_frame, orient="vertical", command=raw_text.yview)
        raw_y.pack(side="right", fill="y")
        raw_text.configure(yscrollcommand=raw_y.set)

        actions = ttk.Frame(viewer)
        actions.pack(fill="x", padx=10, pady=(0, 10))
        copy_button = ttk.Button(actions, text="Copy JSON", state="disabled")
        copy_button.pack(side="left")
        ttk.Button(actions, text="Close", command=viewer.destroy).pack(side="right")

        state = {"json": ""}

        def scalar_text(value: Any) -> str:
            """Handle scalar text."""
            if value is None:
                return "null"
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value)

        def add_rows(value: Any, parent_id: str = "") -> None:
            """Handle add rows."""
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    child_type = type(child_value).__name__
                    is_container = isinstance(child_value, (dict, list))
                    summary = (
                        f"{len(child_value)} entr{'y' if len(child_value) == 1 else 'ies'}"
                        if is_container else scalar_text(child_value)
                    )
                    node_id = value_tree.insert(
                        parent_id, "end", text=str(child_key), values=(child_type, summary), open=False
                    )
                    if is_container:
                        add_rows(child_value, node_id)
            elif isinstance(value, list):
                for index, child_value in enumerate(value):
                    child_type = type(child_value).__name__
                    is_container = isinstance(child_value, (dict, list))
                    summary = (
                        f"{len(child_value)} entr{'y' if len(child_value) == 1 else 'ies'}"
                        if is_container else scalar_text(child_value)
                    )
                    node_id = value_tree.insert(
                        parent_id, "end", text=f"[{index}]", values=(child_type, summary), open=False
                    )
                    if is_container:
                        add_rows(child_value, node_id)
            else:
                value_tree.insert(parent_id, "end", text=key, values=(type(value).__name__, scalar_text(value)))

        def populate(payload: dict[str, Any]) -> None:
            """Handle populate."""
            if not viewer.winfo_exists():
                return
            self._clear_tree(value_tree)
            raw_text.configure(state="normal")
            raw_text.delete("1.0", "end")

            if not payload.get("found"):
                error = str(payload.get("error", "DataStorage value is unavailable."))
                status_text.set(error)
                raw_text.insert("1.0", error)
                raw_text.configure(state="disabled")
                copy_button.configure(state="disabled")
                return

            value = payload.get("value")
            truncated = bool(payload.get("truncated"))
            value_type = str(payload.get("value_type", type(value).__name__))
            status_text.set(
                f"Live {value_type} value"
                + (" • display truncated by safety limit" if truncated else "")
            )
            add_rows(value)
            pretty = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
            state["json"] = pretty
            raw_text.insert("1.0", pretty)
            raw_text.configure(state="disabled")
            copy_button.configure(state="normal")

        def receive(payload: dict[str, Any]) -> None:
            """Handle receive."""
            try:
                self.root.after(0, lambda: populate(payload))
            except Exception:
                _ignored("intentional best-effort fallback")

        def copy_json() -> None:
            """Handle copy json."""
            text = state.get("json", "")
            if not text:
                return
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

        copy_button.configure(command=copy_json)
        self.runtime_client.request_datastorage_value(key, receive)
