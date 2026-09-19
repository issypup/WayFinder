"""Provide setup controller support."""
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


class SetupControllerMixin:
    """Non-rendering orchestration extracted from setup_page.py."""
    def _setup_world_catalog(self):
        """Return the effective world catalogue, not merely custom APWorld count.

        Discovery may contain multiple candidates for one game (for example a
        built-in world plus a custom override).  Only the selected compatible
        candidate represents an available game.  Broken/incompatible candidates
        are counted separately so they cannot accidentally make setup ready.
        """
        if not setup_backend.core_ready(): return [], 0, 0, 0
        try:
            from wayfinder.runtime.apworld_catalog import discover
            records=discover(setup_backend.AP_CORE_SOURCE,source="WayFinder Setup",details=False)
        except Exception as exc:
            self._append_log(f"Setup world catalogue scan failed: {type(exc).__name__}: {exc}"); return [],0,0,1
        builtin=custom=issues=0
        worlds_root=(setup_backend.AP_CORE_SOURCE/"worlds").resolve()
        custom_root=(setup_backend.AP_CORE_SOURCE/"custom_worlds").resolve()
        for record in records:
            compatible=bool(getattr(record,"compatible",True)) and not bool(getattr(record,"error",""))
            selected=bool(getattr(record,"selected",False))
            if not compatible:
                issues+=1
                continue
            # Only selected records are part of the effective catalogue; an
            # unselected duplicate is an alternate/overridden candidate.
            if not selected:
                continue
            try:
                path=Path(record.path).resolve()
                if path.parent==custom_root:
                    custom+=1
                elif worlds_root in path.parents or path.parent==worlds_root:
                    builtin+=1
            except Exception:
                # A compatible selected record with an unclassifiable path still
                # remains visible in the full catalogue, but is not counted as
                # usable readiness because its source cannot be verified.
                issues+=1
        return records,builtin,custom,issues
    def _setup_map_summary(self):
        """Handle setup map summary."""
        try: packs=discover_packs()
        except Exception as exc:
            self._append_log(f"Setup map scan failed: {type(exc).__name__}: {exc}"); return [],0,0
        games=set(); maps=0
        for pack in packs:
            game=str(getattr(pack,"game","") or getattr(pack,"display_name","") or "").strip()
            if game: games.add(game.casefold())
            maps+=len(getattr(pack,"maps_by_title",{}) or {})
        return packs,len(games),maps
    def _setup_readiness(self, slot_override=None):
        """Handle setup readiness."""
        core_ok=bool(setup_backend.core_ready()); records,builtin_count,custom_count,world_issue_count=self._setup_world_catalog(); worlds_ok=bool(core_ok and builtin_count+custom_count>0)
        report=setup_backend.load_dependency_report(setup_backend.DEPENDENCY_REPORT); results=list(report.get("results",[]) or [])
        failed=[x for x in results if x.get("status")=="failed"]
        core_failed=[x for x in failed if x.get("kind")=="core" or x.get("owner")=="Archipelago Core"]
        world_failed=[x for x in failed if x not in core_failed]
        # Global setup readiness should only be blocked by core/runtime
        # dependencies. Per-world dependency failures are enforced later by
        # require_dependencies() after the server identifies the selected game.
        dependency_scan_present=bool(report) and setup_backend.DEPENDENCIES_DIR.is_dir()
        deps_ok=bool(dependency_scan_present and not core_failed)
        affected_worlds=sorted({str(x.get("owner") or "Unknown world") for x in world_failed})
        slot=(str(slot_override).strip() if slot_override is not None else (self.name_var.get().strip() if hasattr(self,"name_var") else "")); yaml_match=setup_backend.find_matching_player_yaml(setup_backend.PLAYERS_DIR,slot) if slot else None
        yaml_count=sum(1 for p in setup_backend.PLAYERS_DIR.glob("*") if p.is_file() and p.suffix.casefold() in {".yaml",".yml"}) if setup_backend.PLAYERS_DIR.is_dir() else 0
        packs,map_game_count,map_count=self._setup_map_summary()
        return {"core_ok":core_ok,"world_records":records,"builtin_world_count":builtin_count,"custom_world_count":custom_count,"world_issue_count":world_issue_count,"apworld_count":custom_count,"worlds_ok":worlds_ok,"deps_ok":deps_ok,"dependency_report":report,"dependency_installed_count":sum(1 for x in results if x.get("status")=="installed"),"dependency_failed_count":len(failed),"core_dependency_failed_count":len(core_failed),"world_dependency_failed_count":len(world_failed),"dependency_affected_worlds":affected_worlds,"yaml_match":yaml_match,"yaml_count":yaml_count,"map_packs":packs,"map_game_count":map_game_count,"map_count":map_count}
    def _refresh_setup_status_async(self):
        """Run expensive catalogue/map/dependency discovery away from Tk's event thread."""
        if self._closing or getattr(self, "_setup_status_scan_running", False):
            return
        self._setup_status_scan_running = True
        slot = self.name_var.get().strip() if hasattr(self, "name_var") else ""
        result_queue = queue.Queue(maxsize=1)
        def worker():
            """Handle worker."""
            try:
                status = self._setup_readiness(slot_override=slot)
                version = setup_backend.imported_archipelago_version() or "unknown"
                result_queue.put((status, version, None))
            except BaseException as exc:
                result_queue.put((None, None, f"{type(exc).__name__}: {exc}"))
        def poll_result():
            """Handle poll result."""
            if self._closing:
                self._setup_status_scan_running = False
                return
            try:
                status, version, error = result_queue.get_nowait()
            except queue.Empty:
                self.root.after(50, poll_result)
                return
            self._setup_status_scan_running = False
            if error:
                self._append_log("Background setup readiness scan failed: " + error)
                return
            self._refresh_setup_status(status, version)
        threading.Thread(target=worker, name="WayFinder-Setup-Readiness", daemon=True).start()
        self.root.after(50, poll_result)

    def _refresh_setup_status(self, status=None, version=None):
        # UI-thread updater only. Expensive discovery belongs in _refresh_setup_status_async().
        """Handle refresh setup status."""
        status = status if status is not None else getattr(self, "_setup_readiness_cache", None)
        if status is None:
            self._refresh_setup_status_async()
            return {"core_ok": False, "worlds_ok": False, "deps_ok": False}
        self._setup_readiness_cache = status; version=version if version is not None else (setup_backend.imported_archipelago_version() or "unknown"); self.setup_core_var.set(f"Archipelago Core: {'Ready' if status['core_ok'] else 'NOT INSTALLED'}"+(f" • {version}" if status["core_ok"] else ""))
        total=status["builtin_world_count"]+status["custom_world_count"]; issues=f" • {status['world_issue_count']} issue(s)" if status["world_issue_count"] else ""; self.setup_worlds_var.set(f"Game Worlds: {total} available • {status['builtin_world_count']} built-in • {status['custom_world_count']} custom{issues}" if status["worlds_ok"] else (f"Game Worlds: NONE AVAILABLE{issues}" if issues else "Game Worlds: NONE AVAILABLE"))
        if status["deps_ok"]:
            if status["world_dependency_failed_count"]:
                self.setup_dependencies_var.set(f"World Dependencies: Core ready • {status['world_dependency_failed_count']} world-specific issue(s)")
            else:
                self.setup_dependencies_var.set("World Dependencies: Ready"+(f" • {status['dependency_installed_count']} unit(s) processed" if status["dependency_installed_count"] else ""))
        elif status["core_dependency_failed_count"]:
            self.setup_dependencies_var.set(f"World Dependencies: {status['core_dependency_failed_count']} CORE FAILURE(S) • View details in Logs")
        else: self.setup_dependencies_var.set("World Dependencies: NOT INSTALLED")
        slot=self.name_var.get().strip() if hasattr(self,"name_var") else ""; self.setup_yamls_var.set(f"Player YAMLs: matched {status['yaml_match'].name}" if slot and status["yaml_match"] else (f"Player YAMLs: no YAML matching slot {slot!r} • {status['yaml_count']} file(s) available" if slot else f"Player YAMLs: {status['yaml_count']} available • enter a Slot to check for an exact match")); self.setup_maps_var.set(f"Map Packs: {status['map_game_count']} game(s) • {status['map_count']} map(s)")
        missing=[]
        if not status["core_ok"]: missing.append("Archipelago Core")
        if not status["worlds_ok"]: missing.append("World Catalogue")
        if not status["deps_ok"]: missing.append("World Dependencies")
        self.setup_status_var.set("Ready to connect." if not missing else "Connect blocked until installed: "+", ".join(missing))
        if hasattr(self,"connect_btn") and not bool(getattr(self.snapshot,"connected",False)): self.connect_btn.configure(state="normal" if not missing else "disabled")
        if missing:
            if self.startup_stage != "setup_required":
                self.startup_stage = "setup_required"
                self.startup_stage_started_at = time.monotonic()
                self._append_log("WayFinder Setup is incomplete.")
                self._append_log("Native runtime startup deferred until required setup is complete.")
                self._append_log("Missing setup requirements: " + ", ".join(missing) + ".")
                # If dependencies are the only blocker, take the user straight to
                # the actionable World Dependencies stage instead of leaving them
                # on a page that only reports that setup is incomplete.
                if missing == ["World Dependencies"] and hasattr(self, "_open_setup_stage"):
                    self.root.after_idle(lambda: self._open_setup_stage(4))
        elif self.startup_stage in {"setup_check","setup_required"}: self.startup_stage="setup_ready"; self.startup_stage_started_at=time.monotonic(); self._append_log("WayFinder Setup prerequisites complete; native runtime will start when Connect is requested.")
        if hasattr(self,"setup_wizard_body"): self._render_setup_view(status)
        return status
    def _clear_saved_connection_data(self):
        """Handle clear saved connection data."""
        server=self._connection_server_value()
        slot=self.name_var.get().strip()
        if not server or not slot:
            ErrorHandler().show_warning("Enter the Server and Slot whose saved data you want to clear.", "Connection details required")
            return
        if not messagebox.askyesno("Clear saved tracker data",f"Clear WayFinder's saved tracker state for:\n\nServer: {server}\nSlot: {slot}\n\nThis does not delete map packs, YAMLs, or setup files."):
            return
        clear_server_slot(normalize_server(server),slot)
        self._append_log(f"Cleared saved tracker state for {server} / {slot}.")
        ErrorHandler().show_info("Saved per-server/slot tracker state was cleared.", "Saved data cleared")
    def _open_setup_folder(self,path):
        """Handle open setup folder."""
        path=Path(path); path.mkdir(parents=True,exist_ok=True)
        try:
            if os.name=="nt": os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform=="darwin": subprocess.Popen(["open",str(path)])
            else: subprocess.Popen(["xdg-open",str(path)])
        except Exception as exc:
            ErrorHandler().handle_error(exc, "WayFinder could not open that folder. Check that it still exists and that you have permission to access it.", "Open Folder Error", error_code="WF-SETUP-001")
    def _select_archipelago_install(self):
        """Handle select archipelago install."""
        chosen=filedialog.askdirectory(title="Select Archipelago installation folder")
        if not chosen:
            return
        root=Path(chosen)
        if not setup_backend.is_archipelago(root):
            ErrorHandler().handle_error(ValueError("Selected folder is missing custom_worlds"), "Select the root of a valid Archipelago installation containing the custom_worlds folder.", "Setup Error", error_code="WF-SETUP-002")
            return
        data=setup_backend.load_settings()
        data["archipelago_root"]=str(root)
        setup_backend.save_settings(data)
        self._append_log(f"Archipelago installation selected: {root}")
        self._refresh_setup_status_async()
    def _start_setup_task(self, name, worker, on_done, on_error, *, progress=None):
        """Run setup I/O on a worker thread and marshal results back to Tk."""
        active = getattr(self, "_setup_task_threads", None)
        if active is None:
            active = self._setup_task_threads = {}
        existing = active.get(name)
        if existing is not None and existing.is_alive():
            ErrorHandler().show_info( f"{name} is already running.", "Setup task already running")
            return False
        events: queue.Queue = queue.Queue()
        def emit(*payload):
            """Handle emit."""
            events.put(("progress", payload))
        def run():
            """Handle run."""
            try:
                result = worker(emit)
                events.put(("done", result))
            except BaseException as exc:
                events.put(("error", (type(exc).__name__, str(exc))))
        def poll():
            """Handle poll."""
            finished = False
            try:
                while True:
                    kind, payload = events.get_nowait()
                    if kind == "progress" and progress is not None:
                        progress(*payload)
                    elif kind == "done":
                        finished = True
                        on_done(payload)
                    elif kind == "error":
                        finished = True
                        on_error(*payload)
            except queue.Empty:
                _ignored("intentional best-effort fallback")
            if not finished:
                self.root.after(100, poll)
            else:
                active.pop(name, None)
        thread = threading.Thread(target=run, name=f"WayFinderSetup-{name.replace(' ', '-')}", daemon=True)
        active[name] = thread
        thread.start()
        self.root.after(100, poll)
        return True
    def _import_archipelago_source(self):
        """Handle import archipelago source."""
        source=filedialog.askopenfilename(title="Import / Update Archipelago Source",filetypes=[("Archipelago source ZIP","*.zip"),("All files","*.*")])
        if not source:
            return
        if not messagebox.askyesno("Import Archipelago source","Import/update WayFinder's private Archipelago core from this source ZIP?\n\nThe existing staged core will be replaced."):
            return
        top=tk.Toplevel(self.root); top.title("Importing Archipelago Core"); top.configure(bg=self._palette()["bg"]); top.transient(self.root); top.geometry("700x250"); top.resizable(False,False)
        body=ttk.Frame(top,style="Card.TFrame",padding=(18,16)); body.pack(fill="both",expand=True,padx=12,pady=12)
        ttk.Label(body,text="ARCHIPELAGO CORE IMPORT",style="CardTitle.TLabel").pack(anchor="w")
        stage_var=tk.StringVar(value="Scanning archive…"); count_var=tk.StringVar(value="Preparing import"); phase_var=tk.StringVar(value="Scanning archive  ○   Extracting  ○   Validating  ○   Preparing runtime  ○")
        ttk.Label(body,textvariable=stage_var,style="Emphasis.TLabel",wraplength=640).pack(anchor="w",pady=(10,4)); ttk.Label(body,textvariable=count_var,style="CardMuted.TLabel").pack(anchor="w",pady=(0,8))
        progress_bar=ttk.Progressbar(body,mode="determinate",maximum=100); progress_bar.pack(fill="x",pady=(2,10)); ttk.Label(body,textvariable=phase_var,style="CardMuted.TLabel",wraplength=640).pack(anchor="w")
        self.setup_status_var.set("Importing Archipelago source…")
        def progress(done,total,label):
            """Handle progress."""
            total=max(1,int(total or 1)); done=max(0,min(int(done or 0),total)); percent=int(done*100/total); lower=str(label or "").casefold()
            progress_bar["value"]=percent; stage_var.set(str(label or "Importing Archipelago core…")); count_var.set(f"{done} / {total} • {percent}%")
            scan="✓" if done>0 or any(x in lower for x in ("extract","validat","prepar","ready")) else "○"
            extract="✓" if any(x in lower for x in ("validat","prepar","backing","ready")) else ("●" if "extract" in lower else "○")
            validate="✓" if any(x in lower for x in ("prepar","backing","ready")) else ("●" if "validat" in lower else "○")
            prepare="✓" if "ready" in lower else ("●" if "prepar" in lower or "backing" in lower else "○")
            phase_var.set(f"Scanning archive  {scan}   Extracting  {extract}   Validating  {validate}   Preparing runtime  {prepare}")
        def worker(emit):
            """Handle worker."""
            manifest=setup_backend.import_archipelago_core(Path(source),progress=lambda d,t,l: emit(d,t,l))
            synced=setup_backend.sync_custom_worlds(setup_backend.find_archipelago())
            return manifest, synced
        def done(result):
            """Handle done."""
            manifest, synced=result; self._append_log(f"Imported Archipelago source: {manifest}"); self._append_log(f"Post-import custom APWorld sync: {synced} available.")
            progress_bar["value"]=100; stage_var.set("Archipelago core ready"); count_var.set("Import complete"); phase_var.set("Scanning archive  ✓   Extracting  ✓   Validating  ✓   Preparing runtime  ✓")
            self._refresh_setup_status_async(); ErrorHandler().show_info("Archipelago core was imported successfully. Continue to Worlds and Dependencies in the setup wizard.", "Archipelago source imported")
            try: top.destroy()
            except tk.TclError: _ignored("intentional best-effort fallback")
        def failed(exc_name, exc_text):
            """Handle failed."""
            self._append_log(f"Archipelago import failed: {exc_name}: {exc_text}")
            ErrorHandler().handle_error(RuntimeError(f"{exc_name}: {exc_text}"), "Archipelago source import failed. Check the selected ZIP and the setup log, then try again.", "Import Error", error_code="WF-SETUP-003"); self._refresh_setup_status_async()
            try: top.destroy()
            except tk.TclError: _ignored("intentional best-effort fallback")
        if not self._start_setup_task("Archipelago core import", worker, done, failed, progress=progress):
            top.destroy()
    def _check_archipelago_github(self):
        """Handle check archipelago github."""
        self.setup_status_var.set("Checking Archipelago GitHub release…")
        def worker(_emit):
            """Handle worker."""
            return setup_backend.github_latest_archipelago_release()
        def done(release):
            """Handle done."""
            latest=str(release.get("tag_name","") or "unknown"); current=setup_backend.imported_archipelago_version() or "not imported"; page=str(release.get("html_url","") or "")
            message=f"Imported source: {current}\nLatest release: {latest}"
            if page and messagebox.askyesno("Archipelago source version",message+"\n\nOpen the release page?"):
                import webbrowser; webbrowser.open(page)
            self._refresh_setup_status_async()
        def failed(_name, text):
            """Handle failed."""
            ErrorHandler().handle_error(RuntimeError(text), "WayFinder could not check the Archipelago release. Check your internet connection and try again.", "Network Error", error_code="WF-SETUP-004"); self._refresh_setup_status_async()
        self._start_setup_task("GitHub version check", worker, done, failed)
    def _sync_game_apworlds(self):
        """Handle sync game apworlds."""
        ap=setup_backend.find_archipelago()
        if not ap:
            ErrorHandler().show_warning("Select an Archipelago installation first so WayFinder knows where to sync custom APWorlds from.", "Archipelago installation not found")
            return
        self.setup_status_var.set("Syncing custom APWorlds…")
        def worker(_emit): return setup_backend.sync_custom_worlds(ap)
        def done(count):
            """Handle done."""
            self._append_log(f"Synced game APWorlds: {count} available."); self._refresh_setup_status_async(); ErrorHandler().show_info(f"{count} custom APWorld archive(s) were synced. Built-in worlds are read directly from the imported Archipelago core.", "Game worlds synced")
        def failed(_name,text): ErrorHandler().handle_error(RuntimeError(text), "WayFinder could not sync APWorlds. Check the selected Archipelago installation and try again.", "Sync Error", error_code="WF-SETUP-005"); self._refresh_setup_status_async()
        self._start_setup_task("APWorld sync", worker, done, failed)
    def _sync_player_yamls_setup(self):
        """Handle sync player yamls setup."""
        ap=setup_backend.find_archipelago(); source=ap if ap and setup_backend._players_source(ap) else setup_backend.AP_CORE_SOURCE
        self.setup_status_var.set("Syncing player YAMLs…")
        def worker(_emit): return setup_backend.sync_player_yamls(source)
        def done(count):
            """Handle done."""
            self._append_log(f"Synced player YAMLs: {count} available."); self._refresh_setup_status_async(); ErrorHandler().show_info(f"{count} player YAML(s) are available to WayFinder.", "Player YAMLs synced")
        def failed(_name,text): ErrorHandler().handle_error(RuntimeError(text), "WayFinder could not sync player YAMLs. Check the source installation and try again.", "Sync Error", error_code="WF-SETUP-006"); self._refresh_setup_status_async()
        self._start_setup_task("Player YAML sync", worker, done, failed)
    def _dependency_log_path(self) -> Path:
        """Return the dedicated dependency installer transcript path."""
        return setup_backend.LOGS_DIR / "dependency-install.log"
    def _write_dependency_log(self, details: str) -> Path:
        """Persist the latest dependency diagnostic text for later inspection."""
        path = self._dependency_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        details = sanitize(details)
        path.write_text(f"WayFinder dependency diagnostics\nGenerated: {timestamp}\n\n{details}\n", encoding="utf-8")
        return path
    def _open_dependency_log(self, path: Path) -> None:
        """Open the dependency log using the platform default text viewer."""
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            ErrorHandler().handle_error(exc, "WayFinder could not open the dependency log. Check the log folder permissions and try again.", "Open Log Error", error_code="WF-SETUP-007")
    def _show_dependency_failure(self, details: str, log_path: Path) -> None:
        """Handle show dependency failure."""
        details = sanitize(details)
        """Show a themed, actionable dependency failure window."""
        top = tk.Toplevel(self.root)
        top.title("Dependency installation failed")
        top.configure(bg=self._palette()["bg"])
        top.transient(self.root)
        top.geometry("820x560")
        top.minsize(650, 420)

        shell = ttk.Frame(top, style="Card.TFrame", padding=14)
        shell.pack(fill="both", expand=True, padx=12, pady=12)
        ttk.Label(shell, text="DEPENDENCY INSTALLATION FAILED", style="CardTitle.TLabel").pack(anchor="w")

        report = setup_backend.load_dependency_report(setup_backend.DEPENDENCY_REPORT)
        failures = [item for item in report.get("results", []) if item.get("status") == "failed"]
        if failures:
            first = failures[0]
            summary = (
                f"{len(failures)} dependency unit(s) failed.\n"
                f"First failure: {first.get('diagnosis', 'Dependency installation failure')}\n"
                f"World/source: {first.get('owner', 'Unknown')}\n"
                f"Dependency: {first.get('label', first.get('value', 'Unknown'))}"
            )
        else:
            summary = "The dependency installer failed. Detailed output is shown below."
        ttk.Label(shell, text=summary, style="CardHeading.TLabel", justify="left", wraplength=760).pack(anchor="w", pady=(6, 10))

        text_frame = ttk.Frame(shell, style="Panel.TFrame")
        text_frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        details_box = tk.Text(
            text_frame,
            wrap="word",
            yscrollcommand=scrollbar.set,
            bg=self._palette()["panel"],
            fg=self._palette()["fg"],
            insertbackground=self._palette()["fg"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=self._palette()["border"],
            highlightcolor=self._palette()["accent"],
            padx=10,
            pady=10,
            font="WayFinderMono",
        )
        details_box.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=details_box.yview)
        details_box.insert("1.0", details)
        details_box.configure(state="disabled")

        button_row = ttk.Frame(shell, style="Card.TFrame")
        button_row.pack(fill="x", pady=(10, 0))

        def copy_details() -> None:
            """Handle copy details."""
            self.root.clipboard_clear()
            self.root.clipboard_append(sanitize(details))
            self.setup_status_var.set("Dependency failure details copied to clipboard.")

        ttk.Button(button_row, text="Copy Details", command=copy_details).pack(side="left")
        ttk.Button(button_row, text="Open Log", command=lambda: self._open_dependency_log(log_path)).pack(side="left", padx=(6, 0))
        ttk.Button(button_row, text="Close", style="Accent.TButton", command=top.destroy).pack(side="right")
        top.grab_set()
        top.focus_set()
    def _install_world_dependencies(self):
        """Install AP/world dependencies without blocking Tk's event loop.

        Dependency resolution and wheel downloads can run for several minutes.  They therefore run
        on a dedicated worker thread; the worker reports progress through a
        queue and every widget update stays on Tk's main thread.
        """
        if not setup_backend.core_ready():
            ErrorHandler().handle_error(RuntimeError("Archipelago core not imported"), "Import Archipelago source before installing world dependencies.", "Dependency Error", error_code="WF-SETUP-008")
            return
        if getattr(self, "_dependency_install_thread", None) is not None and self._dependency_install_thread.is_alive():
            ErrorHandler().show_info( "A dependency installation is already running.", "Dependency installation")
            return
        if not messagebox.askyesno(
            "Install world dependencies",
            "Install/update dependencies required by the staged Archipelago core and game APWorlds?\n\nThis can take several minutes, but the WayFinder GUI will remain responsive.",
        ):
            return

        from wayfinder.runtime.dependency_progress import DependencyProgress
        progress_queue = DependencyProgress()
        self._dependency_progress_queue = progress_queue
        self.setup_status_var.set("Installing world dependencies…")

        top = tk.Toplevel(self.root)
        top.title("Installing World Dependencies")
        top.transient(self.root)
        top.resizable(False, False)
        try:
            top.iconbitmap(self.root.iconbitmap())
        except Exception:
            _ignored("intentional best-effort fallback")

        body = ttk.Frame(top, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Installing world dependencies", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            body,
            text="Installation is running on a background worker so WayFinder stays responsive.",
            wraplength=520,
        ).pack(anchor="w", pady=(4, 14))

        current_label = tk.StringVar(value="Scanning dependency requirements…")
        count_label = tk.StringVar(value="Preparing…")
        ttk.Label(body, textvariable=current_label, wraplength=520).pack(anchor="w", pady=(0, 6))

        overall_var = tk.DoubleVar(value=0.0)
        overall = ttk.Progressbar(body, variable=overall_var, maximum=100.0, length=520, mode="determinate")
        overall.pack(fill="x")
        ttk.Label(body, textvariable=count_label).pack(anchor="w", pady=(4, 12))

        ttk.Label(body, text="Current dependency").pack(anchor="w")
        activity = ttk.Progressbar(body, length=520, mode="indeterminate")
        activity.pack(fill="x", pady=(4, 0))
        activity.start(12)

        started_at = time.monotonic()
        elapsed_label = tk.StringVar(value="Working • elapsed 0:00")
        ttk.Label(body, textvariable=elapsed_label).pack(anchor="w", pady=(6, 0))
        # Closing this window must not destroy widgets still used by the poller.
        # Hiding it leaves installation running and completion still gets reported.
        top.protocol("WM_DELETE_WINDOW", top.withdraw)

        ttk.Label(
            body,
            text="You can continue to move or uncover this window while installation runs. Do not close WayFinder until it finishes.",
            wraplength=520,
        ).pack(anchor="w", pady=(12, 0))

        def worker():
            """Handle worker."""
            try:
                from wayfinder.runtime.dependency_manager import install_all_dependencies

                def report_progress(current, total, label):
                    """Handle report progress."""
                    progress_queue.put(("progress", current, total, label))

                code = install_all_dependencies(
                    setup_backend.AP_CORE_SOURCE,
                    setup_backend.DEPENDENCIES_DIR,
                    setup_backend.DEPENDENCY_REPORT,
                    progress_callback=report_progress,
                )
                progress_queue.put(("done", int(code or 0)))
            except BaseException as exc:
                progress_queue.put(("crash", type(exc).__name__, str(exc)))

        def finish_dialog():
            """Handle finish dialog."""
            try:
                activity.stop()
            except Exception:
                _ignored("intentional best-effort fallback")
            try:
                top.destroy()
            except Exception:
                _ignored("intentional best-effort fallback")

        def poll_progress():
            """Handle poll progress."""
            if self._closing:
                finish_dialog()
                return
            finished = False
            try:
                # Never drain an unbounded stream on Tk's thread. Intermediate
                # labels are superseded; completion/error events are preserved.
                for message in progress_queue.take():
                    kind = message[0]
                    if kind == "progress":
                        _, current, total, label = message
                        total = max(1, int(total or 1))
                        current = max(0, min(int(current or 0), total))
                        overall_var.set((current / total) * 100.0)
                        current_label.set(str(label))
                        count_label.set(f"Dependency unit {current} of {total} • {int((current / total) * 100)}%")
                    elif kind == "done":
                        finished = True
                        finish_dialog()
                        code = int(message[1] or 0)
                        from wayfinder.runtime.dependency_manager import format_dependency_failure_report
                        if code != 0:
                            report = setup_backend.load_dependency_report(setup_backend.DEPENDENCY_REPORT)
                            details = format_dependency_failure_report(report)
                            log_path = self._write_dependency_log(details)
                            self._append_log(f"Dependency installation failed; diagnostics written to {log_path}")
                            self._show_dependency_failure(details, log_path)
                        else:
                            report = setup_backend.load_dependency_report(setup_backend.DEPENDENCY_REPORT)
                            installed_count = sum(1 for item in report.get("results", []) if item.get("status") == "installed")
                            self._append_log(f"World dependency installation completed successfully ({installed_count} unit(s)).")
                            ErrorHandler().show_info(
                                f"World dependencies were installed/updated successfully.\n\n{installed_count} dependency unit(s) processed.",
                                "Dependencies installed",
                            )
                        self._refresh_setup_status_async()
                    elif kind == "crash":
                        finished = True
                        finish_dialog()
                        _, exc_name, exc_text = message
                        details = f"WayFinder dependency installer crashed before a normal report could be completed.\n\n{exc_name}: {exc_text}"
                        log_path = self._write_dependency_log(details)
                        self._append_log(f"Dependency installer crashed; diagnostics written to {log_path}")
                        self._show_dependency_failure(details, log_path)
                        self._refresh_setup_status_async()
            except queue.Empty:
                _ignored("intentional best-effort fallback")
            if not finished:
                elapsed = int(time.monotonic() - started_at)
                elapsed_label.set(f"Working • elapsed {elapsed // 60}:{elapsed % 60:02d}")
                self.root.after(100, poll_progress)

        self._dependency_install_thread = threading.Thread(target=worker, name="WayFinderDependencyInstaller", daemon=True)
        self._dependency_install_thread.start()
        self.root.after(100, poll_progress)
    def _ensure_local_runtime_started(self):
        """Start the hidden native runtime child after setup becomes ready."""
        proc=getattr(self,"_managed_runtime_process",None)
        if proc is not None and proc.poll() is None:
            return True
        port=int(os.environ.get("WF_RUNTIME_PORT","0") or 0)
        if not port:
            ErrorHandler().handle_error(RuntimeError("Internal runtime port unavailable"), "Restart WayFinder, then try the runtime test again.", "Runtime Error", error_code="WF-RUNTIME-001")
            return False
        from wayfinder.runtime.process_manager import start_native_runtime
        try:
            # APWorld mirroring is deliberately not performed here: Connect is a
            # Tk callback and large custom_worlds folders must never block it.
            # Setup & Maintenance performs that sync through _start_setup_task().
            self._startup_enter("waiting_runtime")
            self._runtime_state_name="STARTING"
            self._managed_runtime_process=start_native_runtime(port,setup_backend.AP_CORE_SOURCE,setup_backend.PLAYERS_DIR)
            self._append_log(f"Started WayFinder native runtime on local IPC port {port}.")
            return True
        except Exception as exc:
            ErrorHandler().handle_error(exc, "WayFinder could not start its native runtime. Restart WayFinder and check Diagnostics if the problem continues.", "Runtime Error", error_code="WF-RUNTIME-002")
            return False

