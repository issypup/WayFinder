"""Provide map pack manager support."""
# /**
#  * Module: wayfinder/app/map/map_pack_manager.py
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

class MapPackManagerMixin:
    """Provide map pack manager mixin behavior."""
    def _build_pack_converter(self):
        """Build a dedicated page for converting third-party tracker packs."""
        p=self._page("Pack Converter")

        header=ttk.Frame(p)
        header.pack(fill="x",pady=(4,10))
        ttk.Label(header,text="Pack Converter",style="Title.TLabel").pack(side="left")

        intro=ttk.Frame(p,style="Card.TFrame",padding=(14,12))
        intro.pack(fill="x",pady=(0,10))
        ttk.Label(intro,text="CONVERT TRACKER PACKS",style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            intro,
            text=("Convert existing PopTracker or WayFinder-compatible map packs into WayFinder's "
                  "portable map-pack format. Conversion creates a new ZIP and leaves the source pack unchanged."),
            style="CardMuted.TLabel",wraplength=980,justify="left"
        ).pack(anchor="w",pady=(4,0))

        pop=ttk.Frame(p,style="Card.TFrame",padding=(14,12))
        pop.pack(fill="x",pady=(0,8))
        pop_text=ttk.Frame(pop,style="Card.TFrame")
        pop_text.pack(side="left",fill="x",expand=True)
        ttk.Label(pop_text,text="PopTracker → WayFinder",style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(pop_text,text="Convert a PopTracker pack ZIP into a WayFinder map pack.",style="CardMuted.TLabel").pack(anchor="w",pady=(3,0))
        ttk.Button(pop,text="Convert PopTracker Pack…",style="Accent.TButton",command=lambda:self._convert_map_pack("poptracker")).pack(side="right",padx=(12,0))

        ut=ttk.Frame(p,style="Card.TFrame",padding=(14,12))
        ut.pack(fill="x",pady=(0,8))
        ut_text=ttk.Frame(ut,style="Card.TFrame")
        ut_text.pack(side="left",fill="x",expand=True)
        ttk.Label(ut_text,text="WayFinder Legacy Pack → WayFinder",style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(ut_text,text="Convert a legacy WayFinder-compatible map pack ZIP into WayFinder's portable format.",style="CardMuted.TLabel").pack(anchor="w",pady=(3,0))
        ttk.Button(ut,text="Convert WayFinder Pack…",style="Accent.TButton",command=lambda:self._convert_map_pack("ut")).pack(side="right",padx=(12,0))

        help_card=ttk.Frame(p,style="Card.TFrame",padding=(14,12))
        help_card.pack(fill="x",pady=(4,0))
        ttk.Label(help_card,text="AFTER CONVERSION",style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            help_card,
            text=("WayFinder will offer to install the converted pack immediately. You can also keep the generated ZIP "
                  "and install it later from Installed Maps with Install Map Pack…"),
            style="CardMuted.TLabel",wraplength=980,justify="left"
        ).pack(anchor="w",pady=(4,0))
    def _convert_map_pack(self, source_kind):
        """Convert a third-party map pack to WayFinder's portable map-pack shape."""
        # Variable(s): `title` (title); named state retained for the surrounding calculation or subsequent calls.
        title = "PopTracker" if source_kind == "poptracker" else "WayFinder Legacy Pack"
        # Variable(s): `source` (source); named state retained for the surrounding calculation or subsequent calls.
        source=filedialog.askopenfilename(
            title=f"Select {title} Pack",
            filetypes=[("Tracker pack ZIP", "*.zip"), ("All files", "*.*")],
        )
        if not source:
            return
        # Variable(s): `suggested` (suggested); named state retained for the surrounding calculation or subsequent calls.
        suggested=f"{Path(source).stem}-WayFinder.zip"
        # Variable(s): `output` (output); named state retained for the surrounding calculation or subsequent calls.
        output=filedialog.asksaveasfilename(
            title=f"Save Converted WayFinder Pack",
            defaultextension=".zip",
            initialfile=suggested,
            filetypes=[("WayFinder map pack", "*.zip"), ("All files", "*.*")],
        )
        if not output:
            return
        try:
            if source_kind == "poptracker":
                # Variable(s): `result` (result); named state retained for the surrounding calculation or subsequent calls.
                result=convert_poptracker_pack(Path(source), Path(output))
            else:
                # Variable(s): `result` (result); named state retained for the surrounding calculation or subsequent calls.
                result=convert_ut_pack(Path(source), Path(output))
        except Exception as exc:
            self._append_log(f"{title} pack conversion failed: {type(exc).__name__}: {exc}")
            ErrorHandler().handle_error(exc, f"WayFinder could not convert the {title} pack. Check that the source pack is valid and try again.", "Map Pack Error", error_code="WF-MAP-002")
            return

        self._append_log(
            f"Converted {title} pack to WayFinder: {result.output.name} • "
            f"{result.maps} map(s) • {result.location_files} location file(s)."
        )
        # Variable(s): `detail` (detail); named state retained for the surrounding calculation or subsequent calls.
        detail=(
            f"Converted successfully.\n\n"
            f"Output: {result.output}\n"
            f"Maps: {result.maps}\n"
            f"Location files: {result.location_files}"
        )
        if result.warnings:
            detail += "\n\nNotes:\n" + "\n".join(f"• {w}" for w in result.warnings[:8])
        if messagebox.askyesno("Pack Converter", detail + "\n\nInstall this converted pack into WayFinder now?"):
            try:
                # Variable(s): `_stored` (stored), `folder` (folder); named state retained for the surrounding calculation or subsequent calls.
                _stored, folder=install_pack_archive(result.output, game_pack_dir(self.snapshot.game))
                self._append_log(f"Installed converted WayFinder map pack: {folder.name}")
                self.map_photo_cache.clear(); self.map_background_key=None
                with self._map_source_cache_lock: self.map_source_cache.clear()
                with self._map_scaled_cache_lock: self.map_scaled_cache.clear()
                self._scan_map_packs()
            except Exception as exc:
                ErrorHandler().handle_error(exc, f"The pack was converted but could not be installed. The converted pack was kept at:\n\n{result.output}", "Map Pack Error", error_code="WF-MAP-003")
    def _install_map_pack(self):
        """Handle install map pack."""
        if self._map_install_thread is not None and self._map_install_thread.is_alive():
            if self._map_install_progress is not None:
                try:
                    self._map_install_progress.lift()
                    self._map_install_progress.focus_force()
                except Exception:
                    _ignored("intentional best-effort fallback")
            return
        # Variable(s): `path` (path); named state retained for the surrounding calculation or subsequent calls.
        path=filedialog.askopenfilename(title="Install Tracker Map Pack",filetypes=[("Tracker packs","*.zip *.pack *.map"),("Zip files","*.zip"),("All files","*.*")])
        if not path:return
        self._show_map_install_progress(Path(path).name)
        self.map_install_button.configure(state="disabled")

        # /**
        #  * Function: worker
        #  * Purpose: Perform the worker operation while keeping the surrounding subsystem state consistent.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        def worker():
            # Variable(s): `folder` (folder); named state retained for the surrounding calculation or subsequent calls.
            """Handle worker."""
            folder=None
            conversion_temp=None
            try:
                if self._closing: return
                selected_archive = Path(path)
                archive_format = detect_map_pack_archive_format(selected_archive)
                install_archive = selected_archive
                conversion_temp = None

                if archive_format != "wayfinder":
                    if archive_format == "unknown":
                        raise ValueError(
                            "WayFinder could not identify this archive as a converted WayFinder, PopTracker, "
                            "or WayFinder-compatible map pack."
                        )
                    conversion_temp = tempfile.TemporaryDirectory(prefix="wayfinder-auto-convert-")
                    converted_archive = Path(conversion_temp.name) / f"{selected_archive.stem}-WayFinder.zip"
                    source_label = "PopTracker" if archive_format == "poptracker" else "tracker"
                    self.events.put(("map_install_stage", (f"Converting {source_label} pack for WayFinder…", None, None)))
                    self.events.put(("map_install_log", f"Map pack is not WayFinder-normalized; auto-converting {selected_archive.name} ({archive_format})."))
                    if archive_format == "poptracker":
                        conversion_result = convert_poptracker_pack(selected_archive, converted_archive)
                    else:
                        conversion_result = convert_ut_pack(selected_archive, converted_archive)
                    install_archive = conversion_result.output
                    self.events.put(("map_install_log", f"Automatic conversion complete: {conversion_result.display_name} • {conversion_result.maps} map(s) • {conversion_result.location_files} location file(s)."))
                    for warning in conversion_result.warnings:
                        self.events.put(("map_install_log", f"Converter: {warning}"))
                else:
                    self.events.put(("map_install_log", f"Map pack is already WayFinder-normalized: {selected_archive.name}"))

                self.events.put(("map_install_stage", ("Installing map pack…", None, None)))
                # Variable(s): `_stored` (stored), `folder` (folder); named state retained for the surrounding calculation or subsequent calls.
                _stored, folder = install_pack_archive(install_archive, game_pack_dir(self.snapshot.game))
                self.events.put(("map_install_log", f"Installed map pack for {self.snapshot.game or 'Unknown Game'}: {folder.name}"))
                if conversion_temp is not None:
                    conversion_temp.cleanup()
                    conversion_temp = None
                self.events.put(("map_install_log", f"Preparing persistent zoom/minimap cache for {folder.name}: {len(ZOOM_CACHE_LEVELS)} zoom levels per map…"))

                # /**
                #  * Function: progress
                #  * Purpose: Perform the progress operation while keeping the surrounding subsystem state consistent.
                #  * @param done: Done supplied by the caller; see type hints and call sites for domain constraints.
                #  * @param total: Total supplied by the caller; see type hints and call sites for domain constraints.
                #  * @param title: Title supplied by the caller; see type hints and call sites for domain constraints.
                #  * @param zoom: Zoom supplied by the caller; see type hints and call sites for domain constraints.
                #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
                #  */
                def progress(done, total, title, zoom):
                    """Handle progress."""
                    if self._closing:
                        raise RuntimeError("Map-pack cache build cancelled because WayFinder is closing.")
                    self.events.put(("map_install_progress", (done, total, title, zoom)))
                    if done == 1 or done == total or done % 5 == 0:
                        self.events.put(("map_install_log", f"Map zoom cache: {done}/{total} • {title} • {zoom}%"))

                # Variable(s): `cached_done` (cached done), `cached_total` (cached total); named state retained for the surrounding calculation or subsequent calls.
                cached_done, cached_total = build_pack_zoom_cache(folder, progress)
                # Variable(s): `before_bytes` (before bytes), `after_bytes` (after bytes); named state retained for the surrounding calculation or subsequent calls.
                before_bytes, after_bytes = enforce_map_cache_limit()
                if after_bytes < before_bytes:
                    self.events.put(("map_install_log", f"Map cache budget enforced: {before_bytes//1048576} MiB -> {after_bytes//1048576} MiB"))
                self.events.put(("map_install_done", (folder, cached_done, cached_total)))
            except Exception as exc:
                if conversion_temp is not None:
                    try:
                        conversion_temp.cleanup()
                    except Exception:
                        _ignored("intentional best-effort fallback")
                if folder is not None:
                    try:
                        import shutil as _shutil
                        _shutil.rmtree(folder, ignore_errors=True)
                        remove_pack_zoom_cache(folder)
                    except Exception:
                        _ignored("intentional best-effort fallback")
                if not self._closing:
                    self.events.put(("map_install_failed", exc))

        self._map_install_thread = threading.Thread(target=worker, name="WayFinder-Map-Pack-Install", daemon=True)
        self._map_install_thread.start()
    def _show_map_install_progress(self, archive_name):
        # Variable(s): `win` (window); named state retained for the surrounding calculation or subsequent calls.
        """Handle show map install progress."""
        win=tk.Toplevel(self.root)
        win.configure(bg=self._palette()["bg"])
        win.title("Installing Map Pack")
        win.transient(self.root)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", lambda: None)
        # Variable(s): `body` (body); named state retained for the surrounding calculation or subsequent calls.
        body=ttk.Frame(win,style="Card.TFrame",padding=18); body.pack(fill="both",expand=True,padx=12,pady=12)
        ttk.Label(body,text="INSTALLING MAP PACK",style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(body,text=archive_name,style="CardHeading.TLabel",wraplength=480).pack(anchor="w",pady=(2,12))
        self._map_install_status_var=tk.StringVar(value="Installing and extracting map pack…")
        ttk.Label(body,textvariable=self._map_install_status_var,style="CardMuted.TLabel",wraplength=480,justify="left").pack(anchor="w",pady=(0,8))
        self._map_install_progress_var=tk.DoubleVar(value=0.0)
        # Variable(s): `bar` (bar); named state retained for the surrounding calculation or subsequent calls.
        bar=ttk.Progressbar(body,variable=self._map_install_progress_var,maximum=100.0,length=480,mode="indeterminate")
        bar.pack(fill="x")
        bar.start(12)
        self._map_install_progress=win
        self._map_install_progress_bar=bar
        win.update_idletasks()
        try:
            # Variable(s): `x` (horizontal x-coordinate); named state retained for the surrounding calculation or subsequent calls.
            x=self.root.winfo_rootx()+max(0,(self.root.winfo_width()-win.winfo_reqwidth())//2)
            # Variable(s): `y` (vertical y-coordinate); named state retained for the surrounding calculation or subsequent calls.
            y=self.root.winfo_rooty()+max(0,(self.root.winfo_height()-win.winfo_reqheight())//2)
            win.geometry(f"+{x}+{y}")
        except Exception:
            _ignored("intentional best-effort fallback")
    def _set_map_install_progress(self, done, total, title, zoom):
        """Handle set map install progress."""
        if self._map_install_progress is None or not self._map_install_progress.winfo_exists():
            return
        try:
            self._map_install_progress_bar.stop()
            self._map_install_progress_bar.configure(mode="determinate")
            # Variable(s): `pct` (percentage); named state retained for the surrounding calculation or subsequent calls.
            pct=(float(done)/float(total)*100.0) if total else 0.0
            self._map_install_progress_var.set(pct)
            self._map_install_status_var.set(f"Generating cached map images… {done}/{total}\n{title} • {zoom}% zoom")
        except Exception:
            _ignored("intentional best-effort fallback")
    def _finish_map_pack_install(self, folder, cached_done, cached_total):
        """Handle finish map pack install."""
        self.map_photo_cache.clear(); self.map_background_key=None
        with self._map_source_cache_lock: self.map_source_cache.clear()
        with self._map_scaled_cache_lock: self.map_scaled_cache.clear()
        if cached_total:
            self._append_log(f"Map zoom cache complete: {cached_done}/{cached_total} images prepared for {folder.name}")
        else:
            self._append_log("Map zoom cache unavailable; maps will use runtime scaling fallback.")
        self._scan_map_packs()
        self._close_map_install_progress()
    def _close_map_install_progress(self):
        """Handle close map install progress."""
        if hasattr(self, "map_install_button"):
            try: self.map_install_button.configure(state="normal")
            except Exception: _ignored("intentional best-effort fallback")
        if self._map_install_progress is not None:
            try: self._map_install_progress.destroy()
            except Exception: _ignored("intentional best-effort fallback")
        self._map_install_progress=None
        self._map_install_thread=None
    def _open_map_pack_folder(self):
        # Variable(s): `folder` (folder); named state retained for the surrounding calculation or subsequent calls.
        """Handle open map pack folder."""
        folder=default_pack_dir(); folder.mkdir(parents=True,exist_ok=True)
        try:
            if os.name == "nt": os.startfile(str(folder))
            elif sys.platform == "darwin": subprocess.Popen(["open", str(folder)])
            else: subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            ErrorHandler().handle_error(exc, "WayFinder could not open the map-pack folder. Check folder permissions and try again.", "Map Pack Error", error_code="WF-MAP-004")
    def _remove_map_pack(self):
        # Variable(s): `pack` (pack); named state retained for the surrounding calculation or subsequent calls.
        """Handle remove map pack."""
        pack=self.active_map_pack
        if not pack:
            ErrorHandler().show_info("No compatible map pack is currently selected.", "Map Pack")
            return
        # Variable(s): `archive` (archive); named state retained for the surrounding calculation or subsequent calls.
        archive = related_archive_for_folder(pack.source) if pack.source.is_dir() else pack.source
        # Variable(s): `shown` (shown); named state retained for the surrounding calculation or subsequent calls.
        shown = f"{pack.source.name}" + (f" and {archive.name}" if archive and archive != pack.source else "")
        if not messagebox.askyesno("Remove Map Pack",f"Remove {shown}?\n\nThis deletes the installed archive and extracted map folder."):
            return
        try:
            # Variable(s): `source` (source); named state retained for the surrounding calculation or subsequent calls.
            source=pack.source
            if source.is_dir(): shutil.rmtree(source)
            else: source.unlink(missing_ok=True)
            if archive and archive != source:
                archive.unlink(missing_ok=True)
            remove_pack_zoom_cache(source)
            self.map_photo_cache.clear(); self.map_background_key=None; self.map_photo=None; self._minimap_key=None; self._minimap_photo=None
            with self._map_source_cache_lock: self.map_source_cache.clear()
            with self._map_scaled_cache_lock: self.map_scaled_cache.clear()
            self._append_log(f"Removed map pack: {shown}")
            self._scan_map_packs()
        except Exception as exc:
            ErrorHandler().handle_error(exc, "WayFinder could not remove the map pack. Close any program using its files and try again.", "Map Pack Error", error_code="WF-MAP-005")
    def _revalidate_active_map_pack(self):
        # Variable(s): `pack` (pack); named state retained for the surrounding calculation or subsequent calls.
        """Handle revalidate active map pack."""
        pack=self.active_map_pack
        if not pack or not pack.source.is_dir():
            ErrorHandler().show_info('No extracted active map pack is available to validate.', 'Map-Pack Validation'); return
        # Variable(s): `result` (result); named state retained for the surrounding calculation or subsequent calls.
        result=validate_pack_folder(pack.source); self._last_pack_validation_report=result.report()
        if hasattr(self,'diag_validation'):
            self.diag_validation.set('Map-pack diagnostics: '+result.summary())
            if hasattr(self,'diag_fields'): self.diag_fields['validation'].set(result.summary())
        self._append_log(result.report())
        ErrorHandler().show_info(result.report(), 'Map-Pack Diagnostics')
