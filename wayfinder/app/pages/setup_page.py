"""Provide setup page support."""
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
from wayfinder.storage import app_data_root, default_app_data_root, configured_app_data_root, set_app_data_root, validate_app_data_root

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

class SetupPageMixin:
    """Extracted callbacks that operate on WayFinderApp-owned state."""

    def _setup_storage_browse(self):
        """Handle setup storage browse."""
        current = str(self.setup_storage_path.get() or app_data_root())
        selected = filedialog.askdirectory(
            title="Choose WayFinder app-data folder",
            initialdir=current if Path(current).exists() else str(Path(current).parent),
            mustexist=False,
            parent=self.root,
        )
        if selected:
            self.setup_storage_path.set(str(Path(selected).expanduser()))
            self.setup_storage_message.set("Selection changed. Save the location to use it on the next WayFinder launch.")

    def _setup_storage_use_default(self):
        """Handle setup storage use default."""
        self.setup_storage_path.set(str(default_app_data_root()))
        self.setup_storage_message.set("Platform default selected. Save the location to apply it.")

    def _setup_storage_save(self):
        """Handle setup storage save."""
        raw = str(self.setup_storage_path.get() or "").strip()
        if not raw:
            ErrorHandler().show_warning( "Choose a folder or use the default WayFinder AppData location.", "Storage location required")
            return
        target = Path(raw).expanduser()
        ok, reason = validate_app_data_root(target)
        if not ok:
            ErrorHandler().handle_error(OSError(str(reason)), f"WayFinder cannot write to the selected folder:\n\n{target}\n\nChoose a writable folder and try again.", "Storage Error", error_code="WF-STORAGE-001")
            return
        default = default_app_data_root()
        try:
            saved = set_app_data_root(None if target.resolve() == default.resolve() else target)
        except OSError as exc:
            ErrorHandler().handle_error(exc, "WayFinder could not save the storage location. Check folder permissions and try again.", "Save Error", error_code="WF-STORAGE-002")
            return
        self.setup_storage_path.set(str(saved))
        active = app_data_root()
        try:
            changed = saved.resolve() != active.resolve()
        except OSError:
            changed = str(saved) != str(active)
        if changed:
            self.setup_storage_message.set("Saved. Restart WayFinder to activate this storage location.")
            self.setup_storage_restart_required.set(True)
            self._append_log(f"WayFinder storage location saved for next launch: {saved}")
            ErrorHandler().show_info(
                f"WayFinder will use this folder after restart:\n\n{saved}\n\nThe current session will continue using:\n{active}",
                "Storage location saved",
            )
        else:
            self.setup_storage_message.set("This is the active WayFinder storage location.")
            self.setup_storage_restart_required.set(False)
            self._append_log(f"WayFinder storage location confirmed: {saved}")



















    def _setup_set_stage(self, stage):
        # Wizard navigation must be a pure UI operation.  In particular, do not
        # rescan Archipelago/worlds/maps just because the user clicked Back or
        # Continue: that filesystem work can take long enough to block Tk.
        """Handle setup set stage."""
        self.setup_wizard_stage.set(max(1, min(7, int(stage))))
        self.setup_show_advanced.set(False)
        self.settings["wayfinder.setup_show_advanced"] = False
        self._render_setup_view(getattr(self, "_setup_readiness_cache", None))

    def _setup_toggle_advanced(self):
        """Handle setup toggle advanced."""
        self.setup_show_advanced.set(not self.setup_show_advanced.get())
        self.settings["wayfinder.setup_show_advanced"] = bool(self.setup_show_advanced.get())
        self._save_settings()
        self._render_setup_view(getattr(self, "_setup_readiness_cache", None))

    def _setup_finish_wizard(self):
        # Use the most recent background result.  The Refresh button can be used
        # to explicitly request a new scan without freezing the interface.
        """Handle setup finish wizard."""
        status = getattr(self, "_setup_readiness_cache", None)
        if status is None:
            self._refresh_setup_status_async()
            ErrorHandler().show_info( "WayFinder is checking setup readiness in the background. Try Finish again when the status card updates.", "Setup check running")
            return
        if not (status["core_ok"] and status["worlds_ok"] and status["deps_ok"]):
            ErrorHandler().show_warning( "Archipelago Core, World Catalogue, and World Dependencies must pass before setup can be finished.", "Setup not ready")
            return
        self.settings["wayfinder.setup_wizard_complete"] = True
        self.setup_show_advanced.set(False)
        self.settings["wayfinder.setup_show_advanced"] = False
        self._save_settings()
        self._render_setup_view(status)
        self._append_log("Guided WayFinder Setup completed.")

    def _setup_run_wizard_again(self):
        """Handle setup run wizard again."""
        self.settings["wayfinder.setup_wizard_complete"] = False
        self.setup_wizard_stage.set(1)
        self.setup_show_advanced.set(False)
        self._save_settings()
        self._render_setup_view(getattr(self, "_setup_readiness_cache", None))

    def _setup_add_nav_buttons(self, parent, stage, next_enabled=True, next_text="Continue"):
        """Handle setup add nav buttons."""
        nav = ttk.Frame(parent, style="Card.TFrame"); nav.pack(fill="x", pady=(14, 0))
        if stage > 1:
            ttk.Button(nav, text="Back", style="Accent.TButton", command=lambda: self._setup_set_stage(stage - 1)).pack(side="left")
        if stage < 7:
            btn = ttk.Button(nav, text=next_text, style="Accent.TButton", command=lambda: self._setup_set_stage(stage + 1)); btn.pack(side="right")
            if not next_enabled: btn.configure(state="disabled")

    def _render_setup_progress(self, parent, stage):
        """Handle render setup progress."""
        labels = ("Storage", "Core", "Worlds", "Deps", "YAMLs", "Maps", "Ready")
        row = ttk.Frame(parent); row.pack(fill="x", pady=(0, 12))
        for column, label in enumerate(labels, start=1):
            row.columnconfigure(column - 1, weight=1)
            symbol = "●" if column <= stage else "○"
            ttk.Button(row, text=f"{symbol}  {column}\n{label}", style="Nav.TButton", command=lambda n=column: self._setup_set_stage(n)).grid(row=0, column=column - 1, sticky="ew", padx=2)

    def _render_setup_wizard(self, parent, status):
        """Handle render setup wizard."""
        stage = int(self.setup_wizard_stage.get())
        self._render_setup_progress(parent, stage)
        card = ttk.Frame(parent, style="Card.TFrame", padding=(18, 16)); card.pack(fill="x")
        if stage == 1:
            ttk.Label(card, text="WELCOME TO WAYFINDER", style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(card, text="WayFinder uses a private Archipelago core and the world files required to reconstruct game logic. This wizard checks each part in order; advanced controls remain available at any time.", style="CardMuted.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(6, 12))
            ttk.Label(card, text="App data storage", style="CardHeading.TLabel").pack(anchor="w")
            ttk.Label(card, text="Choose where WayFinder stores its Archipelago core, APWorld data, player YAMLs, map packs, logs, dependencies, snapshots, and application settings. The default is %LOCALAPPDATA%\\WayFinder on Windows.", style="CardMuted.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(3, 8))

            ttk.Label(card, text="Current active location", style="CardMuted.TLabel").pack(anchor="w")
            ttk.Label(card, text=str(app_data_root()), style="Emphasis.TLabel", wraplength=1000).pack(anchor="w", pady=(2, 8))

            path_row = ttk.Frame(card, style="Card.TFrame"); path_row.pack(fill="x", pady=(0, 6))
            path_entry = ttk.Entry(path_row, textvariable=self.setup_storage_path); path_entry.pack(side="left", fill="x", expand=True)
            ttk.Button(path_row, text="Browse…", style="Accent.TButton", command=self._setup_storage_browse).pack(side="left", padx=(6, 0))
            ttk.Button(path_row, text="Use Default", style="Accent.TButton", command=self._setup_storage_use_default).pack(side="left", padx=(6, 0))

            actions = ttk.Frame(card, style="Card.TFrame"); actions.pack(fill="x", pady=(2, 0))
            ttk.Button(actions, text="Save Storage Location", style="Accent.TButton", command=self._setup_storage_save).pack(side="left")
            ttk.Button(actions, text="Open Current AppData", style="Accent.TButton", command=lambda: self._open_setup_folder(app_data_root())).pack(side="left", padx=(6, 0))
            ttk.Label(card, textvariable=self.setup_storage_message, style="CardMuted.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(8, 0))
            if self.setup_storage_restart_required.get():
                ttk.Label(card, text="Restart required before the new storage root becomes active.", style="Emphasis.TLabel").pack(anchor="w", pady=(5, 0))
            self._setup_add_nav_buttons(card, stage)
        elif stage == 2:
            ttk.Label(card, text="ARCHIPELAGO SOURCE", style="CardTitle.TLabel").pack(anchor="w")
            if status["core_ok"]:
                version = setup_backend.imported_archipelago_version() or "unknown"
                ttk.Label(card, text="✓  Archipelago Core detected", style="Emphasis.TLabel").pack(anchor="w", pady=(7, 2))
                ttk.Label(card, text=f"Version: {version}", style="CardMuted.TLabel").pack(anchor="w")
                row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x", pady=(12, 0))
                ttk.Button(row, text="Use Existing", style="Accent.TButton", command=lambda: self._setup_set_stage(3)).pack(side="left")
                ttk.Button(row, text="Update…", style="Accent.TButton", command=self._import_archipelago_source).pack(side="left", padx=(6, 0))
                ttk.Button(row, text="Check GitHub", style="Accent.TButton", command=self._check_archipelago_github).pack(side="left", padx=(6, 0))
            else:
                ttk.Label(card, text="!  Archipelago Core required", style="Emphasis.TLabel").pack(anchor="w", pady=(7, 8))
                ttk.Label(card, text="Import an Archipelago source ZIP. WayFinder stages its own private copy and does not modify the source archive.", style="CardMuted.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(0, 10))
                ttk.Button(card, text="Import Source ZIP…", style="Accent.TButton", command=self._import_archipelago_source).pack(anchor="w")
            self._setup_add_nav_buttons(card, stage, next_enabled=status["core_ok"])
        elif stage == 3:
            ttk.Label(card, text="GAME WORLDS", style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(card, text="WayFinder recognises both worlds bundled with the imported Archipelago core and custom APWorld archives. Custom worlds are optional when the game is built into Archipelago.", style="CardMuted.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(6, 12))
            total = status["builtin_world_count"] + status["custom_world_count"]
            ttk.Label(card, text=f"{'✓' if status['worlds_ok'] else '!'}  {total} worlds available", style="Emphasis.TLabel").pack(anchor="w")
            ttk.Label(card, text=f"✓  {status['builtin_world_count']} built-in worlds     ✓  {status['custom_world_count']} custom APWorlds" + (f"     !  {status['world_issue_count']} world(s) have an issue" if status["world_issue_count"] else ""), style="CardMuted.TLabel", wraplength=1000).pack(anchor="w", pady=(4, 10))
            row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
            ttk.Button(row, text="View Worlds", style="Accent.TButton", command=lambda: self.show_page("APWorlds")).pack(side="left")
            ttk.Button(row, text="Sync Custom APWorlds", style="Accent.TButton", command=self._sync_game_apworlds).pack(side="left", padx=(6, 0))
            self._setup_add_nav_buttons(card, stage, next_enabled=status["worlds_ok"])
        elif stage == 4:
            ttk.Label(card, text="WORLD DEPENDENCIES", style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(card, text="WayFinder installs Python requirements into its private dependency folder. The scan covers the imported core, built-in worlds, and custom APWorlds.", style="CardMuted.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(6, 12))
            if status["deps_ok"]:
                if status["world_dependency_failed_count"]:
                    ttk.Label(card, text="✓  Core dependencies ready", style="Emphasis.TLabel").pack(anchor="w")
                    affected=", ".join(status["dependency_affected_worlds"][:6])
                    suffix=(f" ({affected})" if affected else "")
                    ttk.Label(card, text=f"!  {status['world_dependency_failed_count']} world-specific dependency unit(s) need attention{suffix}. They only block those games; other ready games can still connect.", style="CardMuted.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(3, 10))
                else:
                    ttk.Label(card, text="✓  Dependencies ready", style="Emphasis.TLabel").pack(anchor="w")
                    ttk.Label(card, text=f"{status['dependency_installed_count']} dependency unit(s) processed successfully.", style="CardMuted.TLabel").pack(anchor="w", pady=(3, 10))
            elif status["core_dependency_failed_count"]:
                ttk.Label(card, text=f"!  {status['core_dependency_failed_count']} core dependency unit(s) failed", style="Emphasis.TLabel").pack(anchor="w", pady=(0, 10))
            elif status["dependency_failed_count"]:
                ttk.Label(card, text=f"!  {status['dependency_failed_count']} dependency unit(s) failed", style="Emphasis.TLabel").pack(anchor="w", pady=(0, 10))
            else:
                ttk.Label(card, text="!  Dependency installation has not completed yet", style="Emphasis.TLabel").pack(anchor="w", pady=(0, 10))
            ttk.Button(card, text="Install Missing / Update Dependencies", style="Accent.TButton", command=self._install_world_dependencies).pack(anchor="w")
            self._setup_add_nav_buttons(card, stage, next_enabled=status["deps_ok"])
        elif stage == 5:
            ttk.Label(card, text="PLAYER YAMLS", style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(card, text="Player YAMLs let WayFinder reconstruct the exact options used for your slot. A missing YAML does not automatically mean approximate logic: some APWorlds can reconstruct exact logic from slot data alone.", style="CardMuted.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(6, 12))
            slot = self.name_var.get().strip() if hasattr(self, "name_var") else ""
            ttk.Label(card, text=f"{status['yaml_count']} YAML(s) found.", style="Emphasis.TLabel").pack(anchor="w")
            ttk.Label(card, text=f"Current slot: {slot or 'Not entered'}", style="CardMuted.TLabel").pack(anchor="w", pady=(4, 2))
            if status["yaml_match"]:
                ttk.Label(card, text=f"✓  Matching YAML: {status['yaml_match'].name}", style="Emphasis.TLabel").pack(anchor="w", pady=(2, 8))
            elif slot:
                ttk.Label(card, text="!  No matching YAML", style="Emphasis.TLabel").pack(anchor="w", pady=(2, 2))
                ttk.Label(card, text="You can still connect. WayFinder will report whether the connected APWorld can reconstruct exact logic from slot data alone.", style="CardMuted.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(0, 8))
            row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
            ttk.Button(row, text="Sync Player YAMLs", style="Accent.TButton", command=self._sync_player_yamls_setup).pack(side="left")
            ttk.Button(row, text="Open Player YAMLs", style="Accent.TButton", command=lambda: self._open_setup_folder(setup_backend.PLAYERS_DIR)).pack(side="left", padx=(6, 0))
            self._setup_add_nav_buttons(card, stage)
        elif stage == 6:
            ttk.Label(card, text="MAP PACKS", style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(card, text="Maps are optional visual aids and never block Connect. Install them now or skip this stage and add them later from Installed Maps.", style="CardMuted.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(6, 12))
            ttk.Label(card, text=f"{status['map_game_count']} installed game(s) • {status['map_count']} map(s)", style="Emphasis.TLabel").pack(anchor="w", pady=(0, 10))
            names = [str(getattr(pack, "display_name", "") or getattr(pack, "game", "") or "Map Pack") for pack in status["map_packs"][:8]]
            if names: ttk.Label(card, text="✓  " + "    ✓  ".join(names), style="CardMuted.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(0, 10))
            row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
            ttk.Button(row, text="Install Map Pack…", style="Accent.TButton", command=self._install_map_pack).pack(side="left")
            ttk.Button(row, text="Open Installed Maps", style="Accent.TButton", command=lambda: self.show_page("Installed Maps")).pack(side="left", padx=(6, 0))
            self._setup_add_nav_buttons(card, stage, next_text="Skip for Now / Continue")
        else:
            ttk.Label(card, text="WAYFINDER SELF-TEST", style="CardTitle.TLabel").pack(anchor="w")
            try:
                from wayfinder.runtime import snapshot as _snapshot_codec
                snapshot_ok = bool(_snapshot_codec)
            except Exception:
                snapshot_ok = False
            checks = (("Archipelago core", status["core_ok"]), ("World catalogue", status["worlds_ok"]), ("Python dependencies", status["deps_ok"]), ("Native runtime", bool(self.install_ok)), ("Snapshot codec", snapshot_ok), ("Map system", True))
            all_ok = all(value for _, value in checks)
            for label, value in checks: ttk.Label(card, text=f"{'✓' if value else '!'}  {label}", style="Emphasis.TLabel" if value else "CardMuted.TLabel").pack(anchor="w", pady=2)
            ttk.Label(card, text="Everything is ready." if all_ok else "Resolve the failed required checks before finishing setup.", style="CardMuted.TLabel", wraplength=1000).pack(anchor="w", pady=(10, 12))
            row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
            ttk.Button(row, text="Back", style="Accent.TButton", command=lambda: self._setup_set_stage(6)).pack(side="left")
            finish = ttk.Button(row, text="Finish Setup", style="Accent.TButton", command=self._setup_finish_wizard); finish.pack(side="right")
            if not all_ok: finish.configure(state="disabled")

    def _render_setup_advanced(self, parent, status):
        """Handle render setup advanced."""
        card = ttk.Frame(parent, style="Card.TFrame", padding=(14, 12)); card.pack(fill="x", pady=(10, 0))
        ttk.Label(card, text="ADVANCED SETUP", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(card, text="Manual setup and maintenance controls.", style="CardMuted.TLabel").pack(anchor="w", pady=(3, 8))
        row1 = ttk.Frame(card, style="Card.TFrame"); row1.pack(fill="x", pady=(0, 6))
        for text, command in (("Import Core", self._import_archipelago_source), ("Sync Worlds", self._sync_game_apworlds), ("Install Dependencies", self._install_world_dependencies), ("Sync YAMLs", self._sync_player_yamls_setup)):
            ttk.Button(row1, text=text, style="Accent.TButton", command=command).pack(side="left", padx=(0, 6))
        row2 = ttk.Frame(card, style="Card.TFrame"); row2.pack(fill="x")
        ttk.Button(row2, text="Install Map Pack", style="Accent.TButton", command=self._install_map_pack).pack(side="left")
        ttk.Button(row2, text="Open Installed Maps", style="Accent.TButton", command=lambda: self.show_page("Installed Maps")).pack(side="left", padx=(6, 0))
        ttk.Button(row2, text="Select Archipelago Installation", style="Accent.TButton", command=self._select_archipelago_install).pack(side="left", padx=(6, 0))
        ttk.Button(row2, text="Open AppData", style="Accent.TButton", command=lambda: self._open_setup_folder(setup_backend.APP_DATA_ROOT)).pack(side="left", padx=(6, 0))

    def _render_setup_maintenance(self, parent, status):
        """Handle render setup maintenance."""
        ttk.Label(parent, text="SETUP & MAINTENANCE", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(parent, text="Your guided setup is complete. Use this page for updates, resyncs, and maintenance without losing manual control.", style="CardMuted.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(5, 10))
        summary = ttk.Frame(parent, style="Card.TFrame", padding=(14, 12)); summary.pack(fill="x", pady=(0, 10))
        rows = (("Archipelago Core", "Up to date" if status["core_ok"] else "Required", status["core_ok"]), ("Worlds", f"{status['builtin_world_count'] + status['custom_world_count']} available", status["worlds_ok"]), ("Dependencies", "Ready" if status["deps_ok"] else "Needs attention", status["deps_ok"]), ("YAMLs", f"{status['yaml_count']} files", True), ("Maps", f"{status['map_game_count']} games • {status['map_count']} maps", True))
        for label, value, ok in rows:
            line = ttk.Frame(summary, style="Card.TFrame"); line.pack(fill="x", pady=2)
            ttk.Label(line, text=f"{'✓' if ok else '!'}  {label}", style="Emphasis.TLabel", width=24).pack(side="left")
            ttk.Label(line, text=value, style="CardMuted.TLabel").pack(side="left")
        ttk.Button(parent, text="Run Setup Wizard Again", style="Accent.TButton", command=self._setup_run_wizard_again).pack(anchor="w")
        self._render_setup_advanced(parent, status)

    def _render_setup_view(self, status=None):
        """Handle render setup view."""
        if not hasattr(self, "setup_wizard_body"): return
        status = status or getattr(self, "_setup_readiness_cache", None)
        if status is None:
            # During the very first background scan keep the existing placeholder
            # instead of falling back to a synchronous source-tree scan.
            return
        for child in self.setup_wizard_body.winfo_children(): child.destroy()
        if bool(self.settings.get("wayfinder.setup_wizard_complete", False)):
            self._render_setup_maintenance(self.setup_wizard_body, status)
        else:
            self._render_setup_wizard(self.setup_wizard_body, status)
            if self.setup_show_advanced.get(): self._render_setup_advanced(self.setup_wizard_body, status)

    def _build_wayfinder_setup(self):
        """Handle build wayfinder setup."""
        p = self._page("WayFinder Setup")
        header = ttk.Frame(p); header.pack(fill="x", pady=(4, 10))
        ttk.Label(header, text="WayFinder Setup", style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="Advanced Setup", style="Accent.TButton", command=self._setup_toggle_advanced).pack(side="right")
        ttk.Button(header, text="Refresh", style="Accent.TButton", command=self._refresh_setup_status_async).pack(side="right", padx=(0, 6))
        state_card = ttk.Frame(p, style="Card.TFrame", padding=(14, 10)); state_card.pack(fill="x", pady=(0, 10))
        ttk.Label(state_card, textvariable=self.setup_status_var, style="Emphasis.TLabel", wraplength=1000, justify="left").pack(anchor="w")
        for var in (self.setup_core_var, self.setup_worlds_var, self.setup_dependencies_var, self.setup_yamls_var, self.setup_maps_var):
            ttk.Label(state_card, textvariable=var, style="CardMuted.TLabel", wraplength=1000).pack(anchor="w", pady=1)
        self.setup_wizard_body = ttk.Frame(p); self.setup_wizard_body.pack(fill="both", expand=True)
        # Do not scan the Archipelago source tree while Tk is constructing the window.
        # app.py schedules _refresh_setup_status_async() after the window is alive.
        ttk.Label(self.setup_wizard_body, text="Checking installed components in the background…", style="CardMuted.TLabel").pack(anchor="w", padx=4, pady=8)

