"""Provide log page support."""
# /**
#  * Module: wayfinder/app/ui/log_page.py
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

class LogPageMixin:
    """Provide log page mixin behavior."""
    def _build_log(self):
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        """Handle build log."""
        p=self._page("Log")
        # Variable(s): `h` (height/handle value (context dependent)); named state retained for the surrounding calculation or subsequent calls.
        h=ttk.Frame(p); h.pack(fill="x",pady=(4,8))
        ttk.Label(h,text="Archipelago / WayFinder Log",style="Title.TLabel").pack(side="left")
        ttk.Button(h,text="Clear",command=self._clear_ap_log).pack(side="right")
        intro=ttk.Frame(p,style="Card.TFrame",padding=(12,10)); intro.pack(fill="x",pady=(0,8))
        ttk.Label(intro,text="LIVE RUNTIME CONSOLE",style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            intro,
            text="Live Archipelago and WayFinder runtime messages and command responses.",
            style="CardMuted.TLabel",wraplength=1050
        ).pack(anchor="w",pady=(4,0))
        # Keep the log viewer inside the same card treatment used throughout WayFinder.
        wrap=ttk.Frame(p,style="Card.TFrame",padding=8); wrap.pack(fill="both",expand=True)
        self.ap_log_text=tk.Text(
            wrap,bg=self._palette()["panel"],fg=self._palette()["fg"],
            insertbackground=self._palette()["fg"],relief="flat",wrap="word",
            font="WayFinderBody",highlightthickness=1,
            highlightbackground=self._palette()["accent"],highlightcolor=self._palette()["accent_hover"],padx=8,pady=8
        )
        self._configure_log_tags(self.ap_log_text)
        # Variable(s): `sb` (sb); named state retained for the surrounding calculation or subsequent calls.
        sb=ttk.Scrollbar(wrap,orient="vertical",command=self.ap_log_text.yview)
        sb.pack(side="right",fill="y")
        self.ap_log_text.pack(side="left",fill="both",expand=True)
        self.ap_log_text.configure(yscrollcommand=sb.set,state="disabled")
        # Variable(s): `cmd` (command); named state retained for the surrounding calculation or subsequent calls.
        cmd=ttk.Frame(p,style="Card.TFrame",padding=(8,7)); cmd.pack(fill="x",pady=(8,0))
        self.ap_command_var=tk.StringVar()
        # Variable(s): `entry` (entry); named state retained for the surrounding calculation or subsequent calls.
        entry=ttk.Entry(cmd,textvariable=self.ap_command_var)
        entry.pack(side="left",fill="x",expand=True)
        entry.bind("<Return>",lambda _e:self._send_ap_command())
        ttk.Button(cmd,text="Send",style="Accent.TButton",command=self._send_ap_command).pack(side="left",padx=(6,0))
    def _configure_log_tags(self, widget):
        """Configure semantic colors used by Diagnostics and Log."""
        try:
            # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
            p=self._palette()
            widget.tag_configure("log_error",foreground="#d94b4b")
            widget.tag_configure("log_warn",foreground="#d28a28")
            widget.tag_configure("log_ok",foreground="#2c9b68")
            widget.tag_configure("log_command",foreground=p["accent"])
            widget.tag_configure("log_response",foreground="#6d77d9")
            widget.tag_configure("log_runtime",foreground=p["muted"])
            widget.tag_configure("log_info",foreground=p["fg"])
        except tk.TclError:
            _ignored("intentional best-effort fallback")
    @staticmethod
    def _log_tag_for_line(line):
        # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
        """Handle log tag for line."""
        value=str(line or "").casefold()
        if any(x in value for x in ("traceback", "exception", "error:", " failed", "[error")):
            return "log_error"
        if any(x in value for x in ("warning", "warn:", "stale", "timeout")):
            return "log_warn"
        if "[ut response]" in value:
            return "log_response"
        if "[command" in value or "command → ut" in value:
            return "log_command"
        if any(x in value for x in ("complete", "success", "connected", "✓", "ready")):
            return "log_ok"
        if "[runtime state" in value or "startup" in value or "transport" in value:
            return "log_runtime"
        return "log_info"
    def _append_ap_log_line(self,line):
        """Handle append ap log line."""
        if not hasattr(self,"ap_log_text"):
            return
        try:
            # Variable(s): `tag` (tag); named state retained for the surrounding calculation or subsequent calls.
            tag=self._log_tag_for_line(line)
            self.ap_log_text.configure(state="normal")
            self.ap_log_text.insert("end",sanitize(str(line))+"\n",tag)
            self.ap_log_text.see("end")
            self.ap_log_text.configure(state="disabled")
        except tk.TclError:
            _ignored("intentional best-effort fallback")
    def _clear_ap_log(self):
        """Handle clear ap log."""
        if hasattr(self,'ap_log_text'):
            self.ap_log_text.configure(state='normal'); self.ap_log_text.delete('1.0','end'); self.ap_log_text.configure(state='disabled')
    def _send_ap_command(self):
        # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
        """Handle send ap command."""
        text=self.ap_command_var.get().strip() if hasattr(self,'ap_command_var') else ''
        if not text: return
        self._append_log(f'[Command GUI → Runtime] {text}')
        self.runtime_client.send_console_command(text)
        self.ap_command_var.set('')
    def _append_log(self,text,category=None,level=None,event_id=None):
        """Append a colored diagnostic line and mirror it to the Archipelago/runtime log."""
        # Variable(s): `stamp` (stamp); named state retained for the surrounding calculation or subsequent calls.
        stamp=datetime.now().strftime("%H:%M:%S")
        # Variable(s): `line` (line); named state retained for the surrounding calculation or subsequent calls.
        register_secret(getattr(self, "initial_password", ""))
        if hasattr(self, "password_var"):
            register_secret(self.password_var.get())
        record = make_record(text, category, level)
        if event_id:record["event_id"]=event_id; record["message"]="[event "+event_id+"] "+record["message"]
        line = format_record(record)
        if not hasattr(self, "log_records"):
            self.log_records = []
        self.log_records.append(record)
        self.log_records = self.log_records[-1500:]
        if record["level"] == "ERROR":
            if not hasattr(self, "recent_errors"):
                self.recent_errors = []
            self.recent_errors.append(record)
            self.recent_errors = self.recent_errors[-50:]
            self._refresh_recent_errors()
        # stdout/stderr are tee'd by run_wayfinder.py, so every GUI diagnostic
        # line is also persisted to the current boot log.
        try:
            print(line, flush=True)
        except Exception:
            _ignored("intentional best-effort fallback")
        self.log_lines.append(line)
        self.log_lines=self.log_lines[-1500:]
        if hasattr(self,"ap_log_text"):
            self._append_ap_log_line(line)
        if hasattr(self,"log_text"):
            try:
                # Variable(s): `tag` (tag); named state retained for the surrounding calculation or subsequent calls.
                tag=self._log_tag_for_line(line)
                self.log_text.configure(state="normal")
                self.log_text.insert("end",line+"\n",tag)
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
            except tk.TclError:
                _ignored("intentional best-effort fallback")
    def copy_log(self): self.root.clipboard_clear(); self.root.clipboard_append(sanitize("\n".join(self.log_lines)))
    def clear_log(self):
        """Handle clear log."""
        self.log_records = []; self.recent_errors = []; self._refresh_recent_errors()
        self.log_lines.clear(); self.log_text.configure(state="normal");self.log_text.delete("1.0","end");self.log_text.configure(state="disabled")
