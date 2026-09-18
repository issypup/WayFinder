"""Provide appearance support."""
# /**
#  * Module: wayfinder/app/ui/appearance.py
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

# /**
#  * Function: _atomic_write_json
#  * Purpose: Persist settings safely using a temporary file and atomic replace.
#  */
def _atomic_write_json(path: Path, data: Any, *, backup: bool = True) -> None:
    """Write JSON atomically so interrupted settings saves cannot corrupt the file."""
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
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            _ignored("intentional best-effort fallback")

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

class AppearanceMixin:
    """Provide appearance mixin behavior."""
    def _load_settings(self):
        """Internal helper for load settings; kept private so callers use the higher-level component API."""
        # Loop variable(s): `candidate` (candidate); each iteration represents the next value from the iterable below.
        for candidate in (SETTINGS_PATH, SETTINGS_PATH.with_suffix(SETTINGS_PATH.suffix + ".bak")):
            try:
                # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
                data=json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError, UnicodeError):
                continue
        return {}
    def _save_settings(self):
        # Merge instead of replacing the file: WayFinder Setup stores the Archipelago
        # install path in the same settings file.
        """Internal helper for save settings; kept private so callers use the higher-level component API."""
        try:
            # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
                data = {}
        except (OSError, json.JSONDecodeError, UnicodeError):
            # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
            data = {}
        data.update({
            "geometry": self.root.geometry(),
            "theme": "WayFinder Dark",
            "font_size": self.font_size.get(),
            "active_tab": getattr(self,"current_page","Dashboard"),
            "wayfinder.setup_intro_seen": True,
            "wayfinder.setup_wizard_complete": bool(self.settings.get("wayfinder.setup_wizard_complete", False)),
            "wayfinder.setup_show_advanced": bool(self.setup_show_advanced.get()) if hasattr(self, "setup_show_advanced") else False,
            "check_mode": self.check_mode.get(),
            "check_area": self.check_area.get() if hasattr(self,"check_area") else "All areas",
            "check_search": self.check_search.get() if hasattr(self,"check_search") else "",
            "check_unchecked_only": bool(self.check_unchecked_only.get()) if hasattr(self,"check_unchecked_only") else False,
            "check_hinted_only": bool(self.check_hinted_only.get()) if hasattr(self,"check_hinted_only") else False,
            "check_progression_only": bool(self.check_progression_only.get()) if hasattr(self,"check_progression_only") else False,
            "check_sort_column": getattr(self,"check_sort_column","Check"),
            "check_sort_reverse": bool(getattr(self,"check_sort_reverse",False)),
            "check_group": self.check_group.get() if hasattr(self,"check_group") else "None",
            "check_column_widths": {c:int(self.check_tree.column(c,"width")) for c in self.check_tree["columns"]} if hasattr(self,"check_tree") else {},
            "inventory_mode": self.inventory_mode.get(),
            "map_zoom": int(self.map_zoom.get()),
            "map_show_reachable": bool(self.map_status_visible["reachable"].get()),
            "map_show_glitched": bool(self.map_status_visible["glitched"].get()),
            "map_show_out_of_logic": bool(self.map_status_visible["out_of_logic"].get()),
            "map_show_checked": bool(self.map_status_visible["checked"].get()),
            "map_show_ignored": bool(self.map_status_visible["ignored"].get()),
            "map_show_non_progression": bool(self.map_status_visible["non_progression"].get()),
            "map_show_unknown": bool(self.map_status_visible["unknown"].get()),
            "map_show_labels": bool(self.map_show_labels.get()),
            "map_show_tooltips": bool(self.map_show_tooltips.get()),
            "map_hide_checked_groups": bool(self.map_hide_checked_groups.get()),
            "map_show_minimap": bool(self.map_show_minimap.get()),
            "map_highlight_search": bool(self.map_highlight_search.get()),
            "map_marker_size": self.map_marker_size.get(),
            "map_semantic_zoom": bool(self.map_semantic_zoom.get()),
            "route_strategy": self.route_strategy.get(),
            "personal_route_region_weight": float(self.personal_route_region_weight.get()),
            "personal_route_requirement_penalty": float(self.personal_route_requirement_penalty.get()),
            "path_collapse_satisfied": bool(self.path_collapse_satisfied.get()),
            "map_selection_memory": self.map_selection_memory,
            "active_map_pack_choice": self.active_map_pack_choice.get(),
            "map_variant_memory": self.map_variant_memory,
            "map_view_memory": self.map_view_memory,
            "map_filter_memory": self.map_filter_memory,
            "map_pack_fingerprints": self.map_pack_fingerprints,
            "location_notes": dict(self.settings.get("location_notes", {}) or {}),
            "ignored_locations_by_scope": {str(k): sorted({str(n) for n in (v or []) if str(n).strip()}) for k, v in self.ignored_locations_by_scope.items()},
            "game": "",
            "server": self._connection_server_value() if hasattr(self, "server_host_var") else (self.server_var.get().strip() if hasattr(self, "server_var") else self.initial_server) if hasattr(self, "server_var") else self.initial_server,
            "slot_name": self.name_var.get().strip() if hasattr(self, "name_var") else self.initial_name,
            "password": self.password_var.get() if hasattr(self, "password_var") else self.initial_password,
        })
        try: _atomic_write_json(SETTINGS_PATH, data, backup=True)
        except OSError as exc: self._append_log(f"Could not atomically save settings: {exc!r}") if hasattr(self,"log_lines") else None
    def _palette(self):
        """Return WayFinder's unified dark interface with pink/coral accents.

        The application keeps the near-black/navy surfaces and restrained borders
        from the unified dark redesign, while restoring WayFinder's pink/coral
        identity for selections, primary actions, focused fields and highlights.
        All pages consume the same shared palette so controls remain consistent.
        """
        return dict(
            bg="#24151d", panel="#301b25", sidebar="#3a202d", card="#432633",
            card_alt="#52303e", fg="#fff4f6", muted="#d9b9c3", tree="#2b1821",
            select="#b84f70", accent="#ef7896", accent_hover="#ff91aa",
            accent_soft="#633044", border="#754052", border_soft="#57303e",
            success="#73c9a0", warning="#efb66d", danger="#f06f7d",
            info="#f39ab0"
        )
    def _configure_style(self):
        """Configure the shared Universal-Tracker-inspired WayFinder theme."""
        p=self._palette(); fs=self.font_size.get() if hasattr(self,"font_size") else 10
        self.root.configure(bg=p["bg"]); style=ttk.Style(self.root)
        try: style.theme_use("clam")
        except tk.TclError: _ignored("intentional best-effort fallback")

        # Foundations / surfaces.
        style.configure("TFrame",background=p["bg"])
        style.configure("Panel.TFrame",background=p["panel"])
        style.configure("Sidebar.TFrame",background=p["sidebar"])
        style.configure("Card.TFrame",background=p["card"],bordercolor=p["border"],borderwidth=1,relief="solid")
        style.configure("CardAlt.TFrame",background=p["card_alt"],bordercolor=p["border"],borderwidth=1,relief="solid")

        # Typography.
        style.configure("TLabel",background=p["bg"],foreground=p["fg"],font=("Segoe UI",fs))
        style.configure("Panel.TLabel",background=p["panel"],foreground=p["fg"],font=("Segoe UI",fs))
        style.configure("Sidebar.TLabel",background=p["sidebar"],foreground=p["fg"],font=("Segoe UI",fs))
        style.configure("Muted.TLabel",background=p["bg"],foreground=p["muted"],font=("Segoe UI",fs))
        style.configure("Title.TLabel",background=p["bg"],foreground=p["fg"],font=("Segoe UI Semibold",fs+12))
        style.configure("PanelTitle.TLabel",background=p["panel"],foreground=p["fg"],font=("Segoe UI Semibold",fs+4))
        style.configure("Section.TLabel",background=p["sidebar"],foreground=p["muted"],font=("Segoe UI Semibold",max(8,fs-1)))
        style.configure("CardTitle.TLabel",background=p["card"],foreground=p["muted"],font=("Segoe UI Semibold",max(8,fs-1)))
        style.configure("CardHeading.TLabel",background=p["card"],foreground=p["fg"],font=("Segoe UI Semibold",fs+2))
        style.configure("CardValue.TLabel",background=p["card"],foreground=p["fg"],font=("Segoe UI Semibold",fs+8))
        style.configure("CardMuted.TLabel",background=p["card"],foreground=p["muted"],font=("Segoe UI",fs))
        style.configure("CardAltTitle.TLabel",background=p["card_alt"],foreground=p["muted"],font=("Segoe UI Semibold",max(8,fs-1)))
        style.configure("CardAltMuted.TLabel",background=p["card_alt"],foreground=p["muted"],font=("Segoe UI",fs))
        style.configure("Emphasis.TLabel",background=p["bg"],foreground=p["success"],font=("Segoe UI Semibold",fs))

        # Buttons: dark, bordered controls with WayFinder pink/coral action states.
        style.configure("TButton",background=p["card"],foreground=p["fg"],bordercolor=p["border"],lightcolor=p["card"],darkcolor=p["card"],padding=(11,7),relief="flat",font=("Segoe UI",fs))
        style.map("TButton",background=[("pressed",p["accent_soft"]),("active",p["card_alt"]),("disabled",p["panel"])],foreground=[("disabled",p["muted"])],bordercolor=[("focus",p["accent"]),("active",p["accent"])])
        style.configure("Accent.TButton",background=p["accent"],foreground="#ffffff",bordercolor=p["accent"],lightcolor=p["accent"],darkcolor=p["accent"],padding=(12,7),relief="flat",font=("Segoe UI Semibold",fs))
        style.map("Accent.TButton",background=[("pressed",p["select"]),("active",p["accent_hover"]),("!disabled",p["accent"])],foreground=[("!disabled","#ffffff")],bordercolor=[("!disabled",p["accent"])])
        style.configure("Toolbar.TButton",background=p["bg"],foreground=p["fg"],bordercolor=p["border"],padding=(11,7),relief="flat",font=("Segoe UI",fs))
        style.map("Toolbar.TButton",background=[("active",p["card"])],bordercolor=[("active",p["accent"]),("focus",p["accent"])])

        # Navigation rail.
        style.configure("Nav.TButton",background=p["sidebar"],foreground=p["fg"],anchor="w",padding=(13,10),borderwidth=0,relief="flat",font=("Segoe UI",fs))
        style.map("Nav.TButton",background=[("active",p["accent_soft"])],foreground=[("active",p["fg"])])
        style.configure("NavActive.TButton",background=p["select"],foreground="#ffffff",anchor="w",padding=(13,10),borderwidth=0,relief="flat",font=("Segoe UI Semibold",fs))
        style.map("NavActive.TButton",background=[("active",p["select"]), ("!disabled",p["select"])],foreground=[("!disabled","#ffffff")])

        # Input controls.
        for widget_style in ("TEntry","TCombobox","TSpinbox"):
            style.configure(widget_style,fieldbackground=p["card"],background=p["card"],foreground=p["fg"],insertcolor=p["fg"],bordercolor=p["border"],lightcolor=p["border"],darkcolor=p["border"],padding=6,font=("Segoe UI",fs))
        # Highlighted text-entry style used on the run controls and check filters.
        # It keeps the field dark/readable while using the same pink/coral border/focus
        # language as WayFinder's primary action buttons.
        style.configure("Accent.TEntry",fieldbackground=p["accent_soft"],background=p["accent_soft"],foreground=p["fg"],insertcolor=p["fg"],bordercolor=p["accent"],lightcolor=p["accent"],darkcolor=p["accent"],padding=6,font=("Segoe UI",fs))
        style.map("Accent.TEntry",fieldbackground=[("readonly",p["accent_soft"]),("disabled",p["panel"])],foreground=[("readonly",p["fg"]),("disabled",p["muted"])],bordercolor=[("focus",p["accent_hover"]),("!focus",p["accent"])])
        style.map("TCombobox",fieldbackground=[("readonly",p["card"])],background=[("readonly",p["card"])],foreground=[("readonly",p["fg"])],selectbackground=[("readonly",p["select"])],selectforeground=[("readonly",p["fg"])],bordercolor=[("focus",p["accent"])])
        style.map("TSpinbox",fieldbackground=[("readonly",p["card"])],foreground=[("readonly",p["fg"])],bordercolor=[("focus",p["accent"])])
        self.root.option_add("*TCombobox*Listbox.background", p["card"])
        self.root.option_add("*TCombobox*Listbox.foreground", p["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", p["select"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", p["fg"])

        # Tables / notebooks / separators / progress bars.
        style.configure("Treeview",background=p["tree"],fieldbackground=p["tree"],foreground=p["fg"],rowheight=max(29,fs*3),borderwidth=1,relief="flat",bordercolor=p["border"],font=("Segoe UI",fs))
        style.map("Treeview",background=[("selected",p["select"])],foreground=[("selected","#ffffff")])
        style.configure("Treeview.Heading",background=p["card_alt"],foreground=p["fg"],bordercolor=p["border"],relief="flat",padding=(8,7),font=("Segoe UI Semibold",max(8,fs-1)))
        style.map("Treeview.Heading",background=[("active",p["accent_soft"])])
        style.configure("Emphasis.Treeview",background=p["tree"],fieldbackground=p["tree"],foreground=p["success"],rowheight=max(29,fs*3),borderwidth=1,bordercolor=p["border"],font=("Segoe UI Semibold",fs))
        style.map("Emphasis.Treeview",background=[("selected",p["select"])],foreground=[("selected","#ffffff")])
        style.configure("MapName.TCombobox",fieldbackground=p["card"],background=p["card"],foreground=p["success"],arrowcolor=p["fg"],bordercolor=p["border"],padding=6,font=("Segoe UI Semibold",fs))
        style.map("MapName.TCombobox",fieldbackground=[("readonly",p["card"])],background=[("readonly",p["card"])],foreground=[("readonly",p["success"])],selectbackground=[("readonly",p["select"])],selectforeground=[("readonly","#ffffff")])
        style.configure("TNotebook",background=p["bg"],borderwidth=0)
        style.configure("TNotebook.Tab",background=p["panel"],foreground=p["muted"],padding=(12,8),font=("Segoe UI",fs))
        style.map("TNotebook.Tab",background=[("selected",p["card_alt"]),("active",p["accent_soft"])],foreground=[("selected",p["fg"])])
        style.configure("TSeparator",background=p["border"] )
        style.configure("Horizontal.TProgressbar",troughcolor=p["panel"],background=p["accent"],bordercolor=p["border"],lightcolor=p["accent"],darkcolor=p["accent"])

        # KPI cards and option controls.
        style.configure("Kpi.TFrame",background=p["card"],bordercolor=p["border"],borderwidth=1,relief="solid")
        style.configure("KpiLabel.TLabel",background=p["card"],foreground=p["muted"],font=("Segoe UI Semibold",max(8,fs-1)))
        style.configure("KpiValue.TLabel",background=p["card"],foreground=p["fg"],font=("Segoe UI Semibold",fs+10))
        style.configure("TLabelframe",background=p["bg"],bordercolor=p["border"],relief="solid")
        style.configure("TLabelframe.Label",background=p["bg"],foreground=p["muted"],font=("Segoe UI Semibold",fs))
        style.configure("TCheckbutton",background=p["bg"],foreground=p["fg"],font=("Segoe UI",fs))
        style.map("TCheckbutton",background=[("active",p["bg"])],foreground=[("disabled",p["muted"]),("!disabled",p["fg"])])
        style.configure("TRadiobutton",background=p["bg"],foreground=p["fg"],font=("Segoe UI",fs))
        style.configure("Card.TCheckbutton",background=p["card"],foreground=p["fg"],font=("Segoe UI",fs),padding=(2,2))
        style.map("Card.TCheckbutton",background=[("active",p["card"]),("!disabled",p["card"])],foreground=[("!disabled",p["fg"])])
        style.configure("CardAlt.TCheckbutton",background=p["card_alt"],foreground=p["fg"],font=("Segoe UI",fs),padding=(2,2))
        style.map("CardAlt.TCheckbutton",background=[("active",p["card_alt"]),("!disabled",p["card_alt"])],foreground=[("disabled",p["muted"]),("!disabled",p["fg"])])

        # Classic Tk widgets and native-style menus cannot inherit ttk rules.
        self.root.option_add("*Font", ("Segoe UI", fs))
        self.root.option_add("*Menu.font", ("Segoe UI", fs))
        self.root.option_add("*Menu.background", p["panel"])
        self.root.option_add("*Menu.foreground", p["fg"])
        self.root.option_add("*Menu.activeBackground", p["select"])
        self.root.option_add("*Menu.activeForeground", "#ffffff")
        self.root.option_add("*Menu.borderWidth", 1)
        self.root.option_add("*Menu.relief", "flat")
        self.root.option_add("*Text.background", p["tree"])
        self.root.option_add("*Text.foreground", p["fg"])
        self.root.option_add("*Text.insertBackground", p["fg"])
        self.root.option_add("*Listbox.background", p["tree"])
        self.root.option_add("*Listbox.foreground", p["fg"])
        self.root.option_add("*Listbox.selectBackground", p["select"])
        self.root.option_add("*Listbox.selectForeground", "#ffffff")
    def _install_styled_messageboxes(self):
        """Route tkinter message boxes through WayFinder-themed transient dialogs."""
        def themed_dialog(title, message, *, kind="info", parent=None, question=False, **_kwargs):
            """Handle themed dialog."""
            owner = parent or self.root
            p = self._palette()
            result = {"value": False if question else "ok"}
            top = tk.Toplevel(owner)
            top.title(str(title or "WayFinder"))
            top.configure(bg=p["bg"])
            top.transient(owner)
            top.resizable(False, False)
            try:
                top.grab_set()
            except tk.TclError:
                _ignored("intentional best-effort fallback")

            shell = ttk.Frame(top, style="Card.TFrame", padding=(18, 16))
            shell.pack(fill="both", expand=True, padx=12, pady=12)
            heading = {"error":"ERROR", "warning":"WARNING", "question":"CONFIRM", "info":"WAYFINDER"}.get(kind, "WAYFINDER")
            ttk.Label(shell, text=heading, style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(shell, text=str(title or "WayFinder"), style="CardHeading.TLabel", wraplength=620, justify="left").pack(anchor="w", pady=(3, 9))
            ttk.Label(shell, text=str(message), style="CardMuted.TLabel", wraplength=620, justify="left").pack(anchor="w")
            buttons = ttk.Frame(shell, style="Card.TFrame")
            buttons.pack(fill="x", pady=(16, 0))

            def close(value):
                """Handle close."""
                result["value"] = value
                try:
                    top.grab_release()
                except tk.TclError:
                    _ignored("intentional best-effort fallback")
                top.destroy()

            if question:
                ttk.Button(buttons, text="No", command=lambda: close(False)).pack(side="right")
                yes = ttk.Button(buttons, text="Yes", style="Accent.TButton", command=lambda: close(True))
                yes.pack(side="right", padx=(0, 7))
                yes.focus_set()
                top.bind("<Return>", lambda _e: close(True))
                top.bind("<Escape>", lambda _e: close(False))
                top.protocol("WM_DELETE_WINDOW", lambda: close(False))
            else:
                ok = ttk.Button(buttons, text="OK", style="Accent.TButton", command=lambda: close("ok"))
                ok.pack(side="right")
                ok.focus_set()
                top.bind("<Return>", lambda _e: close("ok"))
                top.bind("<Escape>", lambda _e: close("ok"))
                top.protocol("WM_DELETE_WINDOW", lambda: close("ok"))

            top.update_idletasks()
            try:
                x = owner.winfo_rootx() + max(0, (owner.winfo_width() - top.winfo_reqwidth()) // 2)
                y = owner.winfo_rooty() + max(0, (owner.winfo_height() - top.winfo_reqheight()) // 2)
                top.geometry(f"+{x}+{y}")
            except tk.TclError:
                _ignored("intentional best-effort fallback")
            top.wait_window()
            return result["value"]

        messagebox.showinfo = lambda title, message, **kw: themed_dialog(title, message, kind="info", **kw)
        messagebox.showwarning = lambda title, message, **kw: themed_dialog(title, message, kind="warning", **kw)
        messagebox.showerror = lambda title, message, **kw: themed_dialog(title, message, kind="error", **kw)
        messagebox.askyesno = lambda title, message, **kw: themed_dialog(title, message, kind="question", question=True, **kw)
    def _apply_scaling(self):
        """Apply the received scaling update to local GUI state and dependent widgets."""
        try: self.root.tk.call("tk","scaling",max(0.8,min(1.8,self.font_size.get()/10)))
        except Exception: _ignored("intentional best-effort fallback")
    def _build_menu(self):
        """Native menu for WayFinder text sizing. WayFinder Dark is the fixed theme."""
        # Variable(s): `menubar` (menubar); named state retained for the surrounding calculation or subsequent calls.
        menubar = tk.Menu(self.root)
        # Variable(s): `view` (view); named state retained for the surrounding calculation or subsequent calls.
        view = tk.Menu(menubar, tearoff=False)
        # Variable(s): `font_menu` (font menu); named state retained for the surrounding calculation or subsequent calls.
        font_menu = tk.Menu(view, tearoff=False)
        # Loop variable(s): `size` (size); each iteration represents the next value from the iterable below.
        for size in range(8, 17):
            font_menu.add_radiobutton(label=f"{size} pt", variable=self.font_size, value=size, command=self._refresh_theme)
        view.add_cascade(label="Font size", menu=font_menu)
        view.add_separator()
        view.add_command(label="Smaller font", accelerator="Ctrl+-", command=lambda:self._adjust_font(-1))
        view.add_command(label="Reset font", accelerator="Ctrl+0", command=self._reset_font)
        view.add_command(label="Larger font", accelerator="Ctrl++", command=lambda:self._adjust_font(1))
        menubar.add_cascade(label="View", menu=view)
        self.root.configure(menu=menubar)
        self.root.bind_all("<Control-minus>", lambda _e:self._adjust_font(-1))
        self.root.bind_all("<Control-KP_Subtract>", lambda _e:self._adjust_font(-1))
        self.root.bind_all("<Control-0>", lambda _e:self._reset_font())
        self.root.bind_all("<Control-plus>", lambda _e:self._adjust_font(1))
        self.root.bind_all("<Control-equal>", lambda _e:self._adjust_font(1))
        self.root.bind_all("<Control-KP_Add>", lambda _e:self._adjust_font(1))
    def _adjust_font(self, delta):
        """Internal helper for adjust font; kept private so callers use the higher-level component API."""
        self.font_size.set(max(8, min(16, int(self.font_size.get()) + delta)))
        self._refresh_theme()
    def _reset_font(self):
        """Internal helper for reset font; kept private so callers use the higher-level component API."""
        self.font_size.set(10)
        self._refresh_theme()
    def _refresh_theme(self):
        """Reconfigure widget styling after the selected theme changes."""
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        self._configure_style(); self._apply_scaling(); p=self._palette()
        # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
        for name in ("graph_canvas","path_canvas"):
            if hasattr(self,name): getattr(self,name).configure(bg=p["panel"])
        if hasattr(self,"sidebar_canvas"): self.sidebar_canvas.configure(bg=p.get("sidebar",p["panel"]))
        if hasattr(self,"map_canvas"): self.map_canvas.configure(bg=p["panel"])
        if hasattr(self,"log_text"):
            self.log_text.configure(bg=p["panel"],fg=p["fg"],insertbackground=p["fg"],font=("Segoe UI",self.font_size.get()),highlightbackground=p["border"],highlightcolor=p["accent"])
            self._configure_log_tags(self.log_text)
        if hasattr(self,"ap_log_text"):
            self.ap_log_text.configure(bg=p["panel"],fg=p["fg"],insertbackground=p["fg"],font=("Segoe UI",self.font_size.get()),highlightbackground=p["border"],highlightcolor=p["accent"])
            self._configure_log_tags(self.ap_log_text)
        self._draw_graph()
