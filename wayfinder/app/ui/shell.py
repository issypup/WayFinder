"""Provide shell support."""
# /**
#  * Module: wayfinder/app/ui/shell.py
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

class ShellMixin:
    """Provide shell mixin behavior."""
    def _build_ui(self):
        """Construct the ui UI/data structure and attach its callbacks."""
        # Variable(s): `body` (body); named state retained for the surrounding calculation or subsequent calls.
        self._build_topbar(); body=ttk.Frame(self.root); body.pack(fill="both",expand=True,padx=0,pady=0)

        # The left navigation used to be a fixed-height ttk.Frame. On shorter
        # displays (or with a larger GUI font) the final navigation entries
        # could fall below the bottom of the window with no way to reach them.
        # Keep the sidebar at the same visual width, but put all of its content
        # inside a vertically scrollable canvas.
        # Variable(s): `sidebar_shell` (sidebar shell); named state retained for the surrounding calculation or subsequent calls.
        sidebar_shell=ttk.Frame(body,style="Sidebar.TFrame",width=236)
        sidebar_shell.pack(side="left",fill="y",padx=(0,18))
        sidebar_shell.pack_propagate(False)
        self.sidebar_canvas=tk.Canvas(sidebar_shell,highlightthickness=0,borderwidth=0,
                                      background=self._palette()["panel"])
        self.sidebar_scrollbar=ttk.Scrollbar(sidebar_shell,orient="vertical",command=self.sidebar_canvas.yview)
        self.sidebar_canvas.configure(yscrollcommand=self.sidebar_scrollbar.set)
        self.sidebar_scrollbar.pack(side="right",fill="y")
        self.sidebar_canvas.pack(side="left",fill="both",expand=True)
        self.sidebar=ttk.Frame(self.sidebar_canvas,style="Sidebar.TFrame")
        self._sidebar_window=self.sidebar_canvas.create_window((0,0),window=self.sidebar,anchor="nw")

        # /**
        #  * Function: _sidebar_configure
        #  * Purpose: Perform the sidebar configure operation while keeping the surrounding subsystem state consistent.
        #  * @param _event: Event supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        def _sidebar_configure(_event=None):
            """Handle sidebar configure."""
            self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox("all"))

        # /**
        #  * Function: _sidebar_canvas_resize
        #  * Purpose: Perform the sidebar canvas resize operation while keeping the surrounding subsystem state consistent.
        #  * @param event: Event supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        def _sidebar_canvas_resize(event):
            # Match the inner frame to the visible canvas width so labels and
            # buttons continue to wrap/expand exactly as they did previously.
            """Handle sidebar canvas resize."""
            self.sidebar_canvas.itemconfigure(self._sidebar_window,width=event.width)

        # /**
        #  * Function: _sidebar_mousewheel
        #  * Purpose: Perform the sidebar mousewheel operation while keeping the surrounding subsystem state consistent.
        #  * @param event: Event supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        def _sidebar_mousewheel(event):
            # Only handle wheel input when the pointer is actually somewhere
            # inside the sidebar (including over its child buttons/labels).
            """Handle sidebar mousewheel."""
            try:
                # Variable(s): `widget` (widget); named state retained for the surrounding calculation or subsequent calls.
                widget=self.root.winfo_containing(event.x_root,event.y_root)
            except (KeyError, tk.TclError):
                # ttk combobox popdown windows are not Tkinter child widgets and can
                # disappear between the wheel event and winfo_containing().
                return "break"
            while widget is not None and widget is not sidebar_shell:
                # Variable(s): `widget` (widget); named state retained for the surrounding calculation or subsequent calls.
                widget=getattr(widget,"master",None)
            if widget is not sidebar_shell:
                return
            # Windows/macOS report wheel deltas; X11 commonly uses buttons 4/5.
            # Variable(s): `delta` (delta); named state retained for the surrounding calculation or subsequent calls.
            delta=getattr(event,"delta",0)
            if delta:
                self.sidebar_canvas.yview_scroll(-1 if delta > 0 else 1,"units")
            elif getattr(event,"num",None)==4:
                self.sidebar_canvas.yview_scroll(-1,"units")
            elif getattr(event,"num",None)==5:
                self.sidebar_canvas.yview_scroll(1,"units")
            return "break"

        self.sidebar.bind("<Configure>",_sidebar_configure,add="+")
        self.sidebar_canvas.bind("<Configure>",_sidebar_canvas_resize,add="+")
        # Binding globally with a pointer hit-test makes the wheel work over
        # every sidebar child without stealing wheel input from map/path pages.
        self.root.bind_all("<MouseWheel>",_sidebar_mousewheel,add="+")
        self.root.bind_all("<Button-4>",_sidebar_mousewheel,add="+")
        self.root.bind_all("<Button-5>",_sidebar_mousewheel,add="+")
        self.root.bind_all("<MouseWheel>",self._page_mousewheel,add="+")
        self.root.bind_all("<Button-4>",self._page_mousewheel,add="+")
        self.root.bind_all("<Button-5>",self._page_mousewheel,add="+")

        # Live/tracker data still uses StringVars internally, but its visible
        # presentation now belongs to the Dashboard Run Overview rather than the sidebar.
        self.live_connection=tk.StringVar()
        self.live_startup=tk.StringVar(value="Startup: Waiting for WayFinder runtime")
        self.live_ut=tk.StringVar()
        self.live_slot=tk.StringVar()
        self.live_game=tk.StringVar()
        self.live_server=tk.StringVar()
        self.live_start_location=tk.StringVar(value="Starting Location: Unknown / not resolved yet")
        self.live_recalc=tk.StringVar()
        self.live_updated=tk.StringVar()
        self.stat_vars={key:tk.StringVar(value="0") for key in ("reach","missing","checked","prog","glitch","events","regions","go")}

        self.content=ttk.Frame(body); self.content.pack(side="left",fill="both",expand=True,padx=(0,18),pady=(14,14)); self.pages={}; self.page_canvases={}
        brand=ttk.Frame(self.sidebar,style="Sidebar.TFrame")
        brand.pack(fill="x",padx=14,pady=(17,12))
        ttk.Label(brand,text="WAYFINDER",style="Sidebar.TLabel",font="WayFinderBrand").pack(anchor="w")
        ttk.Label(brand,text="Logic-aware tracker",style="Sidebar.TLabel",foreground=self._palette()["muted"]).pack(anchor="w",pady=(1,0))
        ttk.Separator(self.sidebar).pack(fill="x",padx=12,pady=(0,8))
        ttk.Label(self.sidebar,text="NAVIGATION",style="Section.TLabel").pack(anchor="w",padx=14,pady=(5,6))
        self.nav_buttons = {}
        # Variable(s): `nav_labels` (nav labels); named state retained for the surrounding calculation or subsequent calls.
        nav_labels = {"AP Connection":"AP Connection","APWorlds":"APWorlds","Seed":"Seed","Runtime Health":"Runtime Health","Map Intelligence":"Map Intelligence","Dashboard":"⌂  Dashboard","Search, Hints & Inventory":"⌕  Search, Hints & Inventory","Search":"⌕  Search","Checks":"✓  Checks","Map":"▧  Map","Installed Maps":"▤  Installed Maps","Pack Converter":"⇄  Pack Converter","WayFinder Setup":"⚙  WayFinder Setup","Path Explorer":"→  Path Explorer","I’m Stuck?":"?  I’m Stuck?","Progression Graph":"⌘  Progression Graph","Log":"≡  Log","Inventory":"□  Inventory","Events":"◇  Events","Entrances":"⇥  Entrances","Diagnostics":"⚙  Diagnostics","APWorld Compatibility":"↔  APWorld Compatibility"}
        # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
        for name in ["Dashboard","AP Connection","APWorlds","Seed","Runtime Health","Map Intelligence","Search, Hints & Inventory","Checks","Map","Installed Maps","Pack Converter","I’m Stuck?","Progression Graph","Path Explorer","Log","Events","Entrances","WayFinder Setup","Diagnostics","APWorld Compatibility"]:
            # Variable(s): `btn` (button); named state retained for the surrounding calculation or subsequent calls.
            btn = ttk.Button(self.sidebar,text=nav_labels[name],style="Nav.TButton",command=lambda n=name:self.show_page(n))
            btn.pack(fill="x",padx=8,pady=2)
            self.nav_buttons[name] = btn
        ttk.Label(self.sidebar,text="",style="Sidebar.TLabel").pack(fill="both",expand=True)
        self.version_var=tk.StringVar(value=f"Visual GUI {GUI_VERSION}"); ttk.Label(self.sidebar,textvariable=self.version_var,style="Sidebar.TLabel",foreground=self._palette()["muted"],wraplength=195).pack(fill="x",padx=12,pady=12)
        self._build_pages()
        if self._first_setup_launch:
            # First launch goes directly to setup so prerequisites are obvious.
            # Persist the introduction marker immediately; subsequent launches
            # return to the user's last active tab as normal.
            self.show_page("WayFinder Setup")
            self.settings["wayfinder.setup_intro_seen"] = True
            self._save_settings()
        else:
            remembered_tab=self.settings.get("active_tab","Dashboard")
            # Logic Engine remains internal but is no longer a user-facing tab.
            if remembered_tab == "Logic Engine":
                remembered_tab = "Dashboard"
            self.show_page(remembered_tab if remembered_tab in self.pages else "Dashboard")
    def _build_topbar(self):
        """Construct connection controls and the tracker topbar."""
        # Variable(s): `top` (top); named state retained for the surrounding calculation or subsequent calls.
        # The bar sizes itself to its text so large accessibility text sizes
        # are never clipped by a fixed pixel height.
        top=ttk.Frame(self.root,style="Panel.TFrame"); top.pack(fill="x")
        # Variable(s): `title_row` (title row); named state retained for the surrounding calculation or subsequent calls.
        title_row=ttk.Frame(top,style="Panel.TFrame"); title_row.pack(fill="x")
        ttk.Label(title_row,text="◉  WayFinder — Native Logic Tracker",style="PanelTitle.TLabel").pack(side="left",padx=14,pady=(9,6))
        # Global search remains available from Search, Hints & Inventory / Ctrl+F.
        # The former top-bar fuzzy-search field has been removed to keep connection
        # controls uncluttered.
        self.global_search=tk.StringVar()

        # Connection variables are initialized here because the top bar is built
        # before the Dashboard. Their visible controls now live on the Dashboard.
        host,port=self._split_server_port(self.initial_server)
        self.server_host_var=tk.StringVar(value=host)
        self.server_port_var=tk.StringVar(value=port or "38281")
        self.server_var=tk.StringVar(value=self.initial_server or "")
        self.name_var=tk.StringVar(value=self.initial_name or "")
        self.password_var=tk.StringVar(value=self.initial_password or "")
        self.game_var=tk.StringVar(value="")
    def _build_pages(self):
        """Construct the pages UI/data structure and attach its callbacks."""
        self._build_dashboard(); self._build_search(); self._build_search_hints_inventory(); self._build_checks(); self._build_map(); self._build_installed_maps(); self._build_pack_converter(); self._build_stuck(); self._build_progression_graph(); self._build_path(); self._build_log(); self._build_inventory(); self._build_events(); self._build_entrances(); self._build_wayfinder_setup(); self._build_diagnostics(); self._build_logic_engine(); self._build_compatibility(); self._build_seed_page(); self._build_runtime_health(); self._build_map_intelligence(); self._build_apworlds(); self._build_ap_inspector()
    def _page(self,name):
        """Create a responsive, vertically scrollable application page.

        The navigation page itself is the outer frame stored in ``self.pages``;
        builders receive the inner frame so their existing pack/grid layouts do
        not need to know about scrolling.  This keeps every tab usable on short
        displays without changing specialised scrolling inside maps, trees,
        logs, or path views.
        """
        outer=ttk.Frame(self.content)
        canvas=tk.Canvas(outer,highlightthickness=0,borderwidth=0,background=self._palette()["bg"])
        scrollbar=ttk.Scrollbar(outer,orient="vertical",command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right",fill="y")
        canvas.pack(side="left",fill="both",expand=True)
        inner=ttk.Frame(canvas)
        window=canvas.create_window((0,0),window=inner,anchor="nw")

        def update_scroll_region(_event=None):
            """Handle update scroll region."""
            canvas.configure(scrollregion=canvas.bbox("all"))

        def resize_inner(event):
            # Pages always follow the available width.  They also receive at
            # least the full viewport height so expand=True children (most
            # importantly the Map canvas) can consume otherwise-unused space.
            # If a page's natural content is taller than the viewport we keep
            # that requested height, preserving normal vertical scrolling.
            """Handle resize inner."""
            requested_height=max(1,inner.winfo_reqheight())
            canvas.itemconfigure(
                window,
                width=max(1,event.width),
                height=max(requested_height,event.height),
            )
            update_scroll_region()

        def refresh_inner_height(_event=None):
            # Content can change after the outer canvas Configure event (for
            # example map metadata, diagnostics rows, or dynamic cards).  Keep
            # the embedded page window synchronized with its natural height
            # without allowing short pages to collapse below the viewport.
            """Handle refresh inner height."""
            try:
                viewport_height=max(1,canvas.winfo_height())
                requested_height=max(1,inner.winfo_reqheight())
                canvas.itemconfigure(window,height=max(viewport_height,requested_height))
                update_scroll_region()
            except tk.TclError:
                _ignored("intentional best-effort fallback")

        inner.bind("<Configure>",refresh_inner_height,add="+")
        canvas.bind("<Configure>",resize_inner,add="+")
        self.pages[name]=outer
        self.page_canvases[name]=canvas
        return inner
    def _page_mousewheel(self,event):
        """Scroll the active page unless the pointer is over a self-scrolling widget."""
        canvas=getattr(self,"page_canvases",{}).get(getattr(self,"current_page",None))
        if canvas is None:
            return
        try:
            widget=self.root.winfo_containing(event.x_root,event.y_root)
        except (KeyError,tk.TclError):
            return
        # Preserve native wheel behaviour for controls which already own a
        # viewport (Map/graph canvases, logs, tables, listboxes, text editors).
        owner=widget
        while owner is not None and owner is not self.content:
            if owner is not canvas and isinstance(owner,(tk.Canvas,tk.Text,tk.Listbox,ttk.Treeview)):
                return
            owner=getattr(owner,"master",None)
        if owner is not self.content:
            return
        delta=getattr(event,"delta",0)
        if delta:
            canvas.yview_scroll(-1 if delta > 0 else 1,"units")
        elif getattr(event,"num",None)==4:
            canvas.yview_scroll(-1,"units")
        elif getattr(event,"num",None)==5:
            canvas.yview_scroll(1,"units")
        return "break"
    def _resume_map_page(self):
        """Reconcile deferred player movement before requesting the visible map."""
        if self._closing or self.current_page != "Map":
            return
        self._map_render_deferred = False
        self._refresh_map_from_snapshot()
        self._request_map_render(preserve_view=True, delay=0)
    def show_page(self,name):
        """Switch the interface to the page view and highlight active navigation."""
        self.current_page=name
        if name != "Map":
            self._hide_map_tooltip()
        elif hasattr(self,"map_zoom") and hasattr(self,"map_show_labels"):
            # Semantic zoom is applied during marker rendering without changing the user preference.
            _ignored("intentional best-effort fallback")
        # Loop variable(s): `f` (f); each iteration represents the next value from the iterable below.
        for f in self.pages.values(): f.pack_forget()
        self.pages[name].pack(fill="both",expand=True)
        if name=="Map Intelligence":self._refresh_map_intelligence()
        if name=="AP Connection":self._api_request()
        if name=="APWorlds" and not self.aw_busy:self._aw_refresh()
        if name == "Map" and getattr(self,"_map_render_deferred",False):
            self.root.after_idle(self._resume_map_page)
        # Loop variable(s): `nav_name` (nav name), `btn` (button); each iteration represents the next value from the iterable below.
        for nav_name, btn in getattr(self, "nav_buttons", {}).items():
            btn.configure(style="NavActive.TButton" if nav_name == name else "Nav.TButton")
    def _update_live_panel(self):
        """Refresh the compact live-status summary from the current snapshot."""
        if hasattr(self, "live_startup"):
            self.live_startup.set("Startup: " + self._startup_stage_label())
        if hasattr(self, "diag_startup"):
            self.diag_startup.set(self._startup_progress_text())
        # Variable(s): `s` (s); named state retained for the surrounding calculation or subsequent calls.
        s=self.snapshot; utv=s.engine_version if s.engine_version!='unknown' else self.runtime_engine_version; apv=s.ap_version if s.ap_version!='unknown' else self.runtime_ap_version
        ap_connected = s.connected or self._ap_connection_state == 'connected'
        if ap_connected:
            connection_text="● Connected" if s.connected else "● Connected — preparing world"
        elif self._ap_connection_state == "waiting_for_server":
            connection_text="● Waiting for Archipelago server — automatic retry active"
        elif self._ap_connection_state == "connecting":
            connection_text="● Connecting to Archipelago…"
        else:
            connection_text="● Disconnected"
        self.live_connection.set(connection_text)
        # Variable(s): `ut_text` (ut text); named state retained for the surrounding calculation or subsequent calls.
        if self.runtime_client_transport_state=="reconnecting": ut_text="Reconnecting"
        # Variable(s): `ut_text` (ut text); named state retained for the surrounding calculation or subsequent calls.
        elif self.runtime_client_transport_state=="starting" and "first_snapshot" not in self.startup_completed: ut_text="Runtime is starting"
        # Variable(s): `ut_text` (ut text); named state retained for the surrounding calculation or subsequent calls.
        elif utv!='unknown': ut_text=utv
        # Variable(s): `ut_text` (ut text); named state retained for the surrounding calculation or subsequent calls.
        elif "first_snapshot" in self.startup_completed: ut_text="Ready"
        # Variable(s): `ut_text` (ut text); named state retained for the surrounding calculation or subsequent calls.
        elif self.runtime_client_transport_state=="connected": ut_text="Runtime connected"
        # Variable(s): `ut_text` (ut text); named state retained for the surrounding calculation or subsequent calls.
        elif self.runtime_client_transport_state=="idle": ut_text="Not started"
        # Variable(s): `ut_text` (ut text); named state retained for the surrounding calculation or subsequent calls.
        else: ut_text="Unavailable"
        self.live_ut.set(f"Engine: {ut_text}"); self.live_slot.set(f"Slot: {s.slot_name or '—'}"); self.live_game.set(f"Game: {s.game or '—'}"); self.live_server.set(f"Server: {s.server or self.server_var.get() or '—'}");
        # Variable(s): `start_text` (start text); named state retained for the surrounding calculation or subsequent calls.
        start_text=str(getattr(s, "starting_location", "") or "").strip() or "Unknown / not resolved yet"
        if start_text == "Unknown / not resolved yet":
            try:
                # Variable(s): `start_server` (start server); named state retained for the surrounding calculation or subsequent calls.
                start_server=str(s.server or self.server_var.get() or "").strip()
                # Variable(s): `start_slot` (start slot); named state retained for the surrounding calculation or subsequent calls.
                start_slot=str(s.slot_name or self.name_var.get() or "").strip()
                # Variable(s): `start_game` (start game); named state retained for the surrounding calculation or subsequent calls.
                start_game=str(s.game or "").strip()
                if start_server and start_slot and start_game:
                    # Variable(s): `start_rec` (start rec); named state retained for the surrounding calculation or subsequent calls.
                    start_rec=get_record(start_server, start_slot, start_game, getattr(s,"team",0))
                    # Variable(s): `cached_start` (cached start); named state retained for the surrounding calculation or subsequent calls.
                    cached_start=start_rec.get("starting_location")
                    if cached_start is not None and str(cached_start).strip():
                        # Variable(s): `start_text` (start text); named state retained for the surrounding calculation or subsequent calls.
                        start_text=str(cached_start)
            except Exception:
                _ignored("intentional best-effort fallback")
        self.live_start_location.set(f"Starting Location: {start_text}")
        # Variable(s): `logic_text` (logic text); named state retained for the surrounding calculation or subsequent calls.
        if self._ap_connection_state == 'connected' and not s.connected:
            logic_text = '⟳ ' + (getattr(self, '_world_preparation_message', '') or 'Preparing APWorld and first snapshot')
        elif self._ap_connection_state == 'connecting' and not s.connected:
            logic_text = 'Waiting for Archipelago authentication'
        elif self.recalculating: logic_text=f"⟳ Refresh #{self._active_refresh_id} — {self._refresh_phase_name}"
        # Variable(s): `logic_text` (logic text); named state retained for the surrounding calculation or subsequent calls.
        elif self.logic_status=="timeout": logic_text="⚠ STALE — refresh timed out"
        # Variable(s): `logic_text` (logic text); named state retained for the surrounding calculation or subsequent calls.
        elif self.logic_status=="error": logic_text=f"⚠ {self.logic_status_message or 'Error'}"
        # Variable(s): `logic_text` (logic text); named state retained for the surrounding calculation or subsequent calls.
        elif self.logic_status=="stale" or self._state_is_stale: logic_text=f"⚠ STALE — {self._state_stale_reason or 'showing previous valid state'}"
        # Variable(s): `logic_text` (logic text); named state retained for the surrounding calculation or subsequent calls.
        elif not getattr(s,"reachability_available",True): logic_text="— Reachability unavailable"
        # Variable(s): `logic_text` (logic text); named state retained for the surrounding calculation or subsequent calls.
        else: logic_text="✓ Idle"
        # Variable(s): `origin` (origin); named state retained for the surrounding calculation or subsequent calls.
        origin="PERSISTED" if self._state_origin=="persisted" else "LIVE NATIVE" if self._state_origin=="live" else "NONE"
        self.live_recalc.set(f"Logic: {logic_text}\nLast successful logic: {self._logic_age_text()} • {origin}"); self.live_updated.set(f"Updated: {s.updated_at or '—'}"); self.version_var.set(f"WayFinder {GUI_VERSION}\nEngine {utv}\nArchipelago {apv}")
        if hasattr(self, "diag_versions"):
            self.diag_versions.set(
                f"Native engine: {utv}   •   WayFinder: {self.runtime_integration_version}   •   "
                f"Archipelago core: {apv}"
            )
        if hasattr(self, "diag_runtime"):
            self.diag_runtime.set(
                f"Runtime source: {os.environ.get('WAYFINDER_RUNTIME_SOURCE','bundled/unknown')}   •   "
                f"Target game: {s.game or os.environ.get('WAYFINDER_TARGET_GAME','unknown')}   •   "
                f"Internal UI link: {self.runtime_client_transport_state}"
            )
        if hasattr(self,"diag_fields"):
            self.diag_fields["wayfinder"].set(str(self.runtime_integration_version))
            self.diag_fields["ap_core"].set(str(apv))
            self.diag_fields["runtime_source"].set(os.environ.get("WAYFINDER_RUNTIME_SOURCE","bundled/unknown"))
            self.diag_fields["target_game"].set(s.game or os.environ.get("WAYFINDER_TARGET_GAME","unknown"))
            self.diag_fields["ui_link"].set(str(self.runtime_client_transport_state))
            self.diag_fields["validation"].set(self.diag_validation.get().split(":",1)[-1].strip() or "—")
            self.diag_fields["debug_log"].set(self.diag_runtime_log.get().split(":",1)[-1].strip() or "—")
            self.diag_fields["startup"].set(self.diag_startup.get().removeprefix("Startup:").strip() or "—")
        # Connected snapshots are authoritative and may populate the connection
        # controls. Once disconnected, never push stale snapshot identity back
        # into editable fields; otherwise the user's typing is overwritten on
        # every UI refresh.
        if s.connected:
            if s.server:
                # Runtime snapshots use host:port internally, while WayFinder
                # exposes Server and Port as separate editable controls.
                # Variable(s): `host` (host), `port` (port); named state retained for the surrounding calculation or subsequent calls.
                host,port=self._split_server_port(s.server)
                if host: self.server_host_var.set(host)
                if port: self.server_port_var.set(port)
                self.server_var.set(host or s.server)
            if s.slot_name: self.name_var.set(s.slot_name)
            self.game_var.set(s.game or "")
        else:
            # Never leave a stale game displayed after a manual/network
            # disconnect. The slot's game is authoritative only while live.
            self.game_var.set("")
        if hasattr(self,"connect_btn"):
            if ap_connected:
                self.connect_btn.configure(text="Disconnect",state="normal")
            elif self._ap_connection_state == 'connecting':
                self.connect_btn.configure(text="Connecting…",state="disabled")
            else:
                # Periodic UI refresh must be filesystem-free. A full readiness scan can
                # traverse hundreds of Archipelago world modules and previously froze Tk.
                ready=getattr(self, "_setup_readiness_cache", None) or {"core_ok":False,"worlds_ok":False,"deps_ok":False}
                hard_ready=ready["core_ok"] and ready["worlds_ok"] and ready["deps_ok"]
                self.connect_btn.configure(text="Connect",state="normal" if hard_ready else "disabled")
        if hasattr(self,"refresh_btn"):
            self.refresh_btn.configure(state="normal" if s.connected and not self.recalculating and not self._active_refresh_id else "disabled")
        self._refresh_dashboard_overview()
    def _startup_stage_label(self):
        # Variable(s): `labels` (labels); named state retained for the surrounding calculation or subsequent calls.
        """Handle startup stage label."""
        labels = {
            "setup_check": "Checking WayFinder Setup",
            "setup_required": "WayFinder Setup required",
            "setup_ready": "Setup ready; waiting for Connect",
            "waiting_runtime": "Waiting for native runtime",
            "runtime_connected": "Runtime connected",
            "context_attached": "Waiting for runtime context",
            "waiting_ap_connection": "Waiting for Archipelago connection",
            "first_snapshot": "Connected — preparing world and first snapshot",
            "ready": "Ready",
        }
        return labels.get(self.startup_stage, self.startup_stage.replace("_", " ").title())
    def _startup_progress_text(self):
        # Variable(s): `steps` (steps); named state retained for the surrounding calculation or subsequent calls.
        """Handle startup progress text."""
        steps = [
            ("setup_check", "Checking setup"),
            ("setup_ready", "Setup ready"),
            ("waiting_runtime", "Starting native runtime"),
            ("waiting_runtime", "Waiting for native runtime"),
            ("runtime_connected", "Internal UI link connected"),
            ("context_attached", "Runtime context attached"),
            ("waiting_ap_connection", "Archipelago connection"),
            ("first_snapshot", "First snapshot received"),
        ]
        # Variable(s): `parts` (parts); named state retained for the surrounding calculation or subsequent calls.
        parts=[]
        # Loop variable(s): `key` (key), `label` (label); each iteration represents the next value from the iterable below.
        for key,label in steps:
            if key in self.startup_completed:
                parts.append(label + " ✓")
            elif key in self.startup_timed_out:
                parts.append(label + " ⚠")
            elif key == self.startup_stage:
                parts.append(label + " …")
            else:
                parts.append(label)
        return "Startup: " + " → ".join(parts)
    def _startup_enter(self, stage):
        """Handle startup enter."""
        if self.startup_stage == "ready" or stage in self.startup_completed:
            return
        self.startup_stage = stage
        self.startup_stage_started_at = time.monotonic()
        self._update_live_panel()
    def _on_close(self):
        """Shut down workers/runtime transport cleanly before destroying Tk.

        A frozen one-file build is unpacked under a temporary ``_MEI`` directory.
        Leaving worker callbacks or open runtime resources alive while Tcl/Tk is
        being torn down can make Windows keep that directory locked and cause
        PyInstaller's "Failed to remove temporary directory" warning.
        """
        if self._closing:
            return
        self._closing = True
        if hasattr(self,"aw_cancel"): self.aw_cancel.set()
        self.map_render_generation += 1
        self.map_rendering_key = None
        # Loop variable(s): `after_id` (after id); each iteration represents the next value from the iterable below.
        for after_id in (self._map_zoom_after_id, self._map_search_after_id, self._map_single_click_after_id, self._refresh_timeout_after_id, self._snapshot_ui_refresh_after_id):
            if after_id is not None:
                try: self.root.after_cancel(after_id)
                except Exception: _ignored("intentional best-effort fallback")
        self._map_zoom_after_id = self._map_search_after_id = self._map_single_click_after_id = self._refresh_timeout_after_id = self._snapshot_ui_refresh_after_id = None
        self._save_settings()
        try:
            while True:
                self._snapshot_persist_queue.get_nowait()
        except queue.Empty:
            _ignored("intentional best-effort fallback")
        try:
            self._snapshot_persist_queue.put_nowait(None)
        except queue.Full:
            _ignored("intentional best-effort fallback")
        try:
            if hasattr(self.runtime_client, "close"):
                self.runtime_client.close()
        except Exception:
            _ignored("intentional best-effort fallback")
        try:
            proc=getattr(self,"_managed_runtime_process",None)
            if proc is not None and proc.poll() is None:
                proc.terminate()
        except Exception:
            _ignored("intentional best-effort fallback")

        # Wake and briefly join the single render worker. It is daemonized as
        # a final safety net, so shutdown can never hang on image decoding.
        with self._map_render_condition:
            self._map_render_pending = None
            self._map_render_condition.notify_all()
        try:
            self._map_render_thread.join(timeout=2.0)
        except Exception:
            _ignored("intentional best-effort fallback")
        try:
            self._snapshot_persist_thread.join(timeout=1.0)
        except Exception:
            _ignored("intentional best-effort fallback")
        try:
            if self._map_install_thread and self._map_install_thread.is_alive():
                self._map_install_thread.join(timeout=2.0)
        except Exception:
            _ignored("intentional best-effort fallback")

        # Release Tk/Pillow image references before the Tcl interpreter goes away.
        self.map_photo = None
        self.map_photo_cache.clear()
        with self._map_source_cache_lock:
            self.map_source_cache.clear()
        try:
            self.root.quit()
        except Exception:
            _ignored("intentional best-effort fallback")
        try:
            self.root.destroy()
        except tk.TclError:
            _ignored("intentional best-effort fallback")
