"""Provide map controller support."""
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

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


class MapControllerMixin:
    """Non-rendering orchestration extracted from map_page.py."""
    def _map_connection_key(self, snapshot=None):
        """Stable per-game/server/port key for remembered map selection."""
        # Variable(s): `s` (s); named state retained for the surrounding calculation or subsequent calls.
        s=snapshot or self.snapshot
        # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
        game=str(getattr(s, "game", "") or "").strip()
        # Variable(s): `server` (server); named state retained for the surrounding calculation or subsequent calls.
        server=str(getattr(s, "server", "") or (self.server_var.get() if hasattr(self, "server_var") else "") or "").strip()
        # Variable(s): `slot` (slot); named state retained for the surrounding calculation or subsequent calls.
        slot=str(getattr(s, "slot_name", "") or (self.name_var.get() if hasattr(self, "name_var") else "") or "").strip()
        if not game or not server or not slot:
            return ""
        return f"{game.casefold()}|{server.casefold()}|{slot.casefold()}"
    def _map_game_key(self, snapshot=None):
        # Variable(s): `s` (s); named state retained for the surrounding calculation or subsequent calls.
        """Handle map game key."""
        s=snapshot or self.snapshot
        return str(getattr(s, "game", "") or "").strip().casefold()
    def _map_view_key(self, pack=None, md=None):
        # Variable(s): `pack` (pack); named state retained for the surrounding calculation or subsequent calls.
        """Handle map view key."""
        pack=pack or self.active_map_pack
        # Variable(s): `md` (metadata); named state retained for the surrounding calculation or subsequent calls.
        md=md or self._current_map_def()
        if not pack or not md:
            return ""
        return f"{str(pack.source).casefold()}|{md.name.casefold()}"
    def _remember_map_view(self):
        """Handle remember map view."""
        if not hasattr(self, "map_canvas"):
            return
        # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
        key=self._map_view_key()
        if not key:
            return
        try:
            self.map_view_memory[key]={
                "zoom": int(self.map_zoom.get()),
                "x": float(self.map_canvas.xview()[0]),
                "y": float(self.map_canvas.yview()[0]),
            }
        except (tk.TclError, ValueError, TypeError):
            _ignored("intentional best-effort fallback")
    def _restore_map_view(self, pack=None, md=None):
        # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
        """Handle restore map view."""
        key=self._map_view_key(pack, md)
        # Variable(s): `rec` (rec); named state retained for the surrounding calculation or subsequent calls.
        rec=self.map_view_memory.get(key, {}) if key else {}
        if not isinstance(rec, dict):
            return None
        try:
            # Variable(s): `zoom` (zoom); named state retained for the surrounding calculation or subsequent calls.
            zoom=int(rec.get("zoom", self.map_zoom.get()))
            if zoom in ZOOM_CACHE_LEVELS:
                self.map_zoom.set(zoom)
            return (float(rec.get("x", 0.0)), float(rec.get("y", 0.0)))
        except (TypeError, ValueError):
            return None
    def _remember_game_filters(self):
        # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
        """Handle remember game filters."""
        key=self._map_game_key()
        if not key:
            return
        self.map_filter_memory[key]={
            name: bool(var.get()) for name,var in self.map_status_visible.items()
        } | {
            "labels": bool(self.map_show_labels.get()),
            "tooltips": bool(self.map_show_tooltips.get()),
            "hide_checked_groups": bool(self.map_hide_checked_groups.get()),
        }
    def _restore_game_filters(self):
        # Variable(s): `rec` (rec); named state retained for the surrounding calculation or subsequent calls.
        """Handle restore game filters."""
        rec=self.map_filter_memory.get(self._map_game_key(), {})
        if not isinstance(rec, dict):
            return
        # Loop variable(s): `name` (name), `var` (var); each iteration represents the next value from the iterable below.
        for name,var in self.map_status_visible.items():
            if name in rec:
                var.set(bool(rec[name]))
        if "labels" in rec: self.map_show_labels.set(bool(rec["labels"]))
        if "tooltips" in rec: self.map_show_tooltips.set(bool(rec["tooltips"]))
        if "hide_checked_groups" in rec: self.map_hide_checked_groups.set(bool(rec["hide_checked_groups"]))
    def _remember_current_map(self):
        # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
        """Handle remember current map."""
        key=self._map_connection_key()
        # Variable(s): `title` (title); named state retained for the surrounding calculation or subsequent calls.
        title=self.map_selector_var.get().strip() if hasattr(self, "map_selector_var") else ""
        if key and title:
            self.map_selection_memory[key]=title
    def _map_selected_by_user(self, _event=None):
        """Handle map selected by user."""
        old=getattr(self,"_map_last_user_title","")
        new=self.map_selector_var.get().strip()
        if old and old!=new and (not self.map_navigation_history or self.map_navigation_history[-1][0]!=old):
            self.map_navigation_history.append((old,self.map_selected_location,int(self.map_zoom.get()),self.map_canvas.xview()[0],self.map_canvas.yview()[0])); self.map_navigation_index=len(self.map_navigation_history)-1
        self._map_last_user_title=new
        self._push_map_history()
        self._remember_map_view()
        self._remember_current_map()
        self._restore_map_view()

        # Update the area label/progress immediately on user selection instead
        # of waiting for another runtime snapshot to arrive.
        self._refresh_current_area_progress()
        self._refresh_dashboard_overview()

        # A tracker pack may mix large regional maps with a much smaller
        # overview/world map.  Render the selected map first, then enlarge
        # genuinely small images to the best supported fit zoom.
        self._map_auto_fit_small_pending = True
        self._request_map_render(preserve_view=False,delay=60)
    def _ut_ordered_map_titles(self, pack, snapshot=None):
        """Return map titles using tracker-pack group order first, then PopTracker layout order."""
        if not pack:
            return []
        # Variable(s): `s` (s); named state retained for the surrounding calculation or subsequent calls.
        s=snapshot or self.snapshot
        # Variable(s): `by_name` (by name); named state retained for the surrounding calculation or subsequent calls.
        by_name={m.name:m.title for m in pack.maps}
        # Variable(s): `by_title` (by title); named state retained for the surrounding calculation or subsequent calls.
        by_title={m.title:m.title for m in pack.maps}
        # Variable(s): `requested` (requested); named state retained for the surrounding calculation or subsequent calls.
        requested=list(getattr(s, "map_order", []) or []) or list(getattr(pack, "map_order", []) or [])
        # Variable(s): `ordered` (ordered); named state retained for the surrounding calculation or subsequent calls.
        ordered=[]
        # Loop variable(s): `raw` (raw value); each iteration represents the next value from the iterable below.
        for raw in requested:
            # Variable(s): `title` (title); named state retained for the surrounding calculation or subsequent calls.
            title=by_name.get(str(raw)) or by_title.get(str(raw))
            if title and title not in ordered: ordered.append(title)
        ordered.extend(m.title for m in pack.maps if m.title not in ordered)
        return ordered
    def _ut_map_page_title(self, pack, snapshot=None):
        # Variable(s): `s` (s); named state retained for the surrounding calculation or subsequent calls.
        """Handle ut map page title."""
        s=snapshot or self.snapshot
        # Variable(s): `raw_idx` (raw idx); named state retained for the surrounding calculation or subsequent calls.
        raw_idx=getattr(s,"map_page_index",-1)
        try:
            # Variable(s): `idx` (index); named state retained for the surrounding calculation or subsequent calls.
            idx=int(raw_idx) if raw_idx is not None else -1
        except (TypeError, ValueError):
            # Variable(s): `idx` (index); named state retained for the surrounding calculation or subsequent calls.
            idx=-1
        if pack and 0 <= idx < len(pack.maps):
            return pack.maps[idx].title
        return ""
    def _map_display_name(self, canonical):
        # Variable(s): `aliases` (aliases); named state retained for the surrounding calculation or subsequent calls.
        """Handle map display name."""
        aliases=getattr(self.snapshot,"location_aliases",{}) or {}
        # Variable(s): `alias` (alias); named state retained for the surrounding calculation or subsequent calls.
        alias=aliases.get(canonical, "") if isinstance(aliases,dict) else ""
        return f"{canonical} ({alias})" if alias and alias != canonical else canonical
    def _resolve_map_location_name(self, name, state=None):
        """Resolve map/PopTracker aliases back to the canonical live AP location name."""
        # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
        raw=str(name or "").strip()
        if not raw: return raw
        # Variable(s): `state` (state); named state retained for the surrounding calculation or subsequent calls.
        state=state or {x.name:x for x in self.snapshot.locations}
        if raw in state: return raw
        # Variable(s): `folded` (folded); named state retained for the surrounding calculation or subsequent calls.
        folded={str(k).strip().casefold():k for k in state}
        # Variable(s): `hit` (hit); named state retained for the surrounding calculation or subsequent calls.
        hit=folded.get(raw.casefold())
        if hit: return hit
        # Variable(s): `aliases` (aliases); named state retained for the surrounding calculation or subsequent calls.
        aliases=getattr(self.snapshot,"location_aliases",{}) or {}
        if isinstance(aliases,dict):
            # Loop variable(s): `canonical` (canonical), `alias` (alias); each iteration represents the next value from the iterable below.
            for canonical,alias in aliases.items():
                if str(alias).strip().casefold()==raw.casefold() and canonical in state:
                    return canonical
        # Variable(s): `mapping` (mapping); named state retained for the surrounding calculation or subsequent calls.
        mapping=getattr(self.snapshot,"poptracker_name_mapping",{}) or {}
        if isinstance(mapping,dict):
            # Some APWorlds use both canonical->PopTracker and PopTracker->canonical forms.
            # Loop variable(s): `key` (key), `value` (value); each iteration represents the next value from the iterable below.
            for key,value in mapping.items():
                # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
                candidates=value if isinstance(value,(list,tuple,set)) else (value,)
                if str(key).strip().casefold()==raw.casefold():
                    # Loop variable(s): `candidate` (candidate); each iteration represents the next value from the iterable below.
                    for candidate in candidates:
                        # Variable(s): `c` (c); named state retained for the surrounding calculation or subsequent calls.
                        c=str(candidate).strip(); resolved=folded.get(c.casefold())
                        if resolved: return resolved
                if any(str(v).strip().casefold()==raw.casefold() for v in candidates):
                    # Variable(s): `resolved` (resolved); named state retained for the surrounding calculation or subsequent calls.
                    resolved=folded.get(str(key).strip().casefold())
                    if resolved: return resolved
        return raw
    def _map_location(self, name, state=None, ap_ids=None):
        # Variable(s): `state` (state); named state retained for the surrounding calculation or subsequent calls.
        """Handle map location."""
        state=state or {x.name:x for x in self.snapshot.locations}
        if ap_ids:
            # Variable(s): `wanted` (wanted); named state retained for the surrounding calculation or subsequent calls.
            wanted=set()
            # Variable(s): `values` (values); named state retained for the surrounding calculation or subsequent calls.
            values=ap_ids if isinstance(ap_ids,(list,tuple,set)) else (ap_ids,)
            # Loop variable(s): `value` (value); each iteration represents the next value from the iterable below.
            for value in values:
                try: wanted.add(int(value))
                except (TypeError, ValueError): _ignored("intentional best-effort fallback")
            if wanted:
                # Loop variable(s): `loc` (loc); each iteration represents the next value from the iterable below.
                for loc in self.snapshot.locations:
                    # Variable(s): `address` (address); named state retained for the surrounding calculation or subsequent calls.
                    try: address=int(getattr(loc,"address",None))
                    except (TypeError, ValueError): continue
                    if address in wanted:
                        return loc
        return state.get(self._resolve_map_location_name(name,state))
    def _map_entrance_marker_status(self, marker):
        """Resolve a PopTracker entrance-map marker against native entrance state.

        Entrance overview markers are not AP locations.  We first try to associate
        their human-readable label with the native APWorld entrance graph.  If no
        reliable association exists, the marker deliberately remains visible as
        ``unknown`` instead of being hidden as a location that is not in this seed.
        """
        label=str(getattr(marker, "location_name", "") or "").strip()
        if not label:
            return "unknown"
        def norm(value):
            """Handle norm."""
            import re
            text=str(value or "").strip().casefold()
            text=re.sub(r"^(act\s+\d+|finale|secret finale|time rift)\s*-\s*", "", text)
            return re.sub(r"[^a-z0-9]+", " ", text).strip()
        wanted=norm(label)
        best=None

        # Rank label matches instead of accepting the first substring hit.
        # Exact native entrance names are strongest, followed by exact target
        # and source regions.  Fuzzy containment is retained only when it
        # produces one unique best candidate; ambiguous labels such as "Cave",
        # "Tower" or "Route" deliberately fall through to the structural
        # completion-location bridge (or Unknown) rather than inheriting an
        # unrelated entrance's state.
        ranked_matches=[]
        for detail in getattr(self.snapshot, "entrance_details", []) or []:
            if not isinstance(detail,dict):
                continue
            normalized_name=norm(detail.get("name"))
            normalized_source=norm(detail.get("source_region"))
            normalized_target=norm(detail.get("target_region"))
            score=0
            if wanted:
                if wanted == normalized_name:
                    score=400
                elif wanted == normalized_target:
                    score=350
                elif wanted == normalized_source:
                    score=300
                else:
                    fuzzy_values=[value for value in (normalized_name, normalized_target, normalized_source) if value]
                    # Require a meaningful label for containment matching. Short
                    # generic words create far too many false associations.
                    wanted_tokens=wanted.split()
                    if len(wanted) >= 6 and (len(wanted_tokens) >= 2 or len(wanted) >= 10):
                        if any(wanted in value or value in wanted for value in fuzzy_values):
                            score=100
            if score:
                ranked_matches.append((score, detail))

        if ranked_matches:
            highest=max(score for score,_ in ranked_matches)
            winners=[detail for score,detail in ranked_matches if score == highest]
            if len(winners) == 1:
                best=winners[0]
        if best is None:
            # PopTracker display labels frequently do not match APWorld entrance
            # names (acts, portals and Time Rifts are common examples).  When the
            # converter mapped this marker's ``Can Complete`` section to a real
            # Archipelago location, use that location's parent region as the
            # authoritative bridge into the native region/entrance graph.
            #
            # This is intentionally generic: a completion location inside an
            # entrance's destination region gives us a stable structural identity
            # even when the pack calls the entrance something completely different.
            names=getattr(marker, "member_names", ()) or ()
            complete_index=next((i for i,name in enumerate(names) if str(name or "").strip().casefold()=="can complete"), -1)
            if complete_index >= 0:
                live_state={x.name:x for x in getattr(self.snapshot,"locations",[]) or []}
                completion_location=self._map_marker_member_location(marker,complete_index,live_state)
                target_region=str(getattr(completion_location,"region","") or "").strip() if completion_location is not None else ""
                if target_region:
                    incoming=[]
                    for detail in getattr(self.snapshot,"entrance_details",[]) or []:
                        if not isinstance(detail,dict):
                            continue
                        if str(detail.get("target_region","") or "").strip().casefold()==target_region.casefold():
                            incoming.append(detail)
                    if incoming:
                        if any(bool(row.get("reachable")) or str(row.get("status","") or "").strip().casefold()=="reachable" for row in incoming):
                            return "reachable"
                        if all(str(row.get("status","") or "").strip().casefold() in {"blocked","unreachable"} or not bool(row.get("reachable")) for row in incoming):
                            return "out_of_logic"
                    reachable_regions={str(region or "").strip().casefold() for region in getattr(self.snapshot,"current_reachable_regions",[]) or []}
                    if target_region.casefold() in reachable_regions:
                        return "reachable"
                    if bool(getattr(self.snapshot,"reachability_available",False)):
                        return "out_of_logic"
            return "unknown"
        status=str(best.get("status", "") or "").strip().casefold()
        if bool(best.get("reachable")) or status=="reachable":
            return "reachable"
        # Native entrance_details always carry an authoritative boolean
        # ``reachable`` field, but they do not necessarily carry a textual
        # status such as ``blocked``.  Treat an explicit False as
        # Out of Logic whenever native reachability is available; otherwise
        # valid blocked entrances would incorrectly fall through to Unknown.
        if ("reachable" in best and best.get("reachable") is False and
                bool(getattr(self.snapshot,"reachability_available",False))):
            return "out_of_logic"
        if status in {"blocked", "unreachable", "out_of_logic"}:
            return "out_of_logic"
        return "unknown"
    def _map_entrance_section_status(self, marker, index, state=None):
        """Return live semantic state for an entrance marker section.

        ``Can Enter`` is the native entrance reachability itself. ``Can Complete``
        uses a converted AP completion-location ID when the PopTracker pack exposes
        one. If the section has no extra access rule (common for free-roam acts),
        completion follows entrance reachability. Arbitrary unresolved PopTracker
        Lua rules remain ``unknown`` rather than being guessed.
        """
        names=getattr(marker, "member_names", ()) or ()
        if index < 0 or index >= len(names):
            return "unknown"
        role=str(names[index] or "").strip().casefold()
        entrance_status=self._map_entrance_marker_status(marker)
        if role == "can enter":
            return entrance_status
        if role != "can complete":
            return "unknown"

        state=state or {x.name:x for x in self.snapshot.locations}
        loc=self._map_marker_member_location(marker,index,state)
        if loc is not None:
            status=("ignored" if getattr(loc,"ignored",False) else str(getattr(loc,"status","") or "unknown"))
            return status if status in {"reachable","glitched","out_of_logic","checked","ignored","unknown"} else "unknown"

        rules=getattr(marker,"section_access_rules",()) or ()
        section_rules=rules[index] if index < len(rules) else []
        if not section_rules:
            return entrance_status
        return "unknown"
    @staticmethod
    def _map_entrance_section_status_label(status):
        """Handle map entrance section status label."""
        status=str(status or "unknown").strip().casefold()
        if status == "checked":
            return "Completed"
        return status.replace("_", " ").title()
    def _map_marker_member_location(self, marker, index, state=None):
        # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
        """Handle map marker member location."""
        names=marker.member_names
        if index < 0 or index >= len(names): return None
        # Variable(s): `ids` (ids); named state retained for the surrounding calculation or subsequent calls.
        ids=()
        # Variable(s): `section_ids` (section ids); named state retained for the surrounding calculation or subsequent calls.
        section_ids=getattr(marker,"section_ids",()) or ()
        # Variable(s): `ids` (ids); named state retained for the surrounding calculation or subsequent calls.
        if index < len(section_ids): ids=section_ids[index]
        return self._map_location(names[index], state, ids)
    def _map_effective_location_status(self, loc):
        """Return the map-facing status for a live location.

        Some APWorlds intentionally omit optional/non-progression checks from the
        reconstructed logic graph even though the server still advertises those
        checks.  That is not the same thing as an uninterpretable Unknown marker.
        Treat this specific, generic reconstruction condition as a distinct map
        state while preserving the authoritative runtime status everywhere else.
        """
        if loc is None:
            return "unknown"
        if bool(getattr(loc, "ignored", False)):
            return "ignored"
        status=str(getattr(loc, "status", "unknown") or "unknown")
        reason=str(getattr(loc, "unknown_reason", "") or "")
        if status == "unknown":
            # A server-advertised check that reconstruction intentionally did
            # not include is a known untracked/non-progression map entry.  By
            # contrast, an adapter exception means the rule could not be
            # evaluated and must remain Unknown; presenting that as
            # Non-progression would falsely imply a semantic classification.
            if reason.startswith("Server location is not present in the reconstructed APWorld graph"):
                return "non_progression"
        return status if status in {
            "reachable", "glitched", "out_of_logic", "checked", "ignored",
            "non_progression", "unknown"
        } else "unknown"
    def _map_hidden_members(self, md):
        """Handle map hidden members."""
        if not md: return set()
        # Variable(s): `values` (values); named state retained for the surrounding calculation or subsequent calls.
        values=[]
        # Loop variable(s): `attr` (attr); each iteration represents the next value from the iterable below.
        for attr in ("hidden_map_locations","hidden_map_entrances","hidden_map_events"):
            # Variable(s): `hidden` (hidden); named state retained for the surrounding calculation or subsequent calls.
            hidden=getattr(self.snapshot,attr,{}) or {}
            if isinstance(hidden,dict): values.extend(hidden.get(md.name, hidden.get(md.title, [])) or [])
        return {str(x) for x in values}
    def _choose_map_for_pack(self, pack, names, snapshot=None, prefer_hook=True):
        """Choose hook-selected map first, then remembered connection map, then first map."""
        if not pack or not names:
            return ""
        # Variable(s): `s` (s); named state retained for the surrounding calculation or subsequent calls.
        s=snapshot or self.snapshot
        # Variable(s): `ut_title` (ut title); named state retained for the surrounding calculation or subsequent calls.
        ut_title=self._ut_map_page_title(pack,s)
        if ut_title in names:
            return ut_title
        if prefer_hook and pack.has_python and pack.python_api_compatible:
            # Variable(s): `hooked` (hooked); named state retained for the surrounding calculation or subsequent calls.
            hooked=pack.resolve_current_map(s, getattr(s, 'raw_map_page_datastorage_value', None))
            if hooked in names:
                return hooked
            if pack.python_error:
                self._append_log(f"Map-pack hook warning for {pack.display_name}: {pack.python_error}")
        # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
        key=self._map_connection_key(s)
        # Variable(s): `remembered` (remembered); named state retained for the surrounding calculation or subsequent calls.
        remembered=self.map_selection_memory.get(key, "") if key else ""
        if remembered in names:
            return remembered
        # Variable(s): `current` (current); named state retained for the surrounding calculation or subsequent calls.
        current=self.map_selector_var.get() if hasattr(self, "map_selector_var") else ""
        if current in names:
            return current
        return names[0]
    def _map_pack_fingerprint(self, pack):
        """Handle map pack fingerprint."""
        if not pack:
            return ""
        # Variable(s): `h` (height/handle value (context dependent)); named state retained for the surrounding calculation or subsequent calls.
        h=hashlib.sha256()
        try:
            # Variable(s): `source` (source); named state retained for the surrounding calculation or subsequent calls.
            source=Path(pack.source)
            h.update(str(source.resolve()).casefold().encode("utf-8","replace"))
            # Variable(s): `files` (files); named state retained for the surrounding calculation or subsequent calls.
            files=[]
            if source.is_dir():
                # Loop variable(s): `pattern` (pattern); each iteration represents the next value from the iterable below.
                for pattern in ("maps/maps.json","locations/*.json","ut_locations/*.json","__init__.py"):
                    files.extend(source.glob(pattern))
            else:
                # Variable(s): `files` (files); named state retained for the surrounding calculation or subsequent calls.
                files=[source]
            # Loop variable(s): `p` (p); each iteration represents the next value from the iterable below.
            for p in sorted(set(files), key=lambda x:str(x).casefold()):
                try:
                    # Variable(s): `st` (st); named state retained for the surrounding calculation or subsequent calls.
                    st=p.stat(); h.update(str(p.relative_to(source) if source.is_dir() else p.name).encode()); h.update(f"{st.st_size}:{st.st_mtime_ns}".encode())
                except OSError:
                    continue
        except Exception:
            return str(pack.source)
        return h.hexdigest()
    def _invalidate_changed_pack_state(self, pack):
        """Handle invalidate changed pack state."""
        if not pack:
            return
        # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
        game=self._map_game_key() or str(self.snapshot.game or "").strip().casefold()
        # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
        key=f"{game}|{str(pack.source).casefold()}"
        # Variable(s): `fresh` (fresh); named state retained for the surrounding calculation or subsequent calls.
        fresh=self._map_pack_fingerprint(pack)
        # Variable(s): `previous` (previous); named state retained for the surrounding calculation or subsequent calls.
        previous=self.map_pack_fingerprints.get(key)
        self.map_pack_fingerprints[key]=fresh
        if previous and previous != fresh:
            self._append_log(f"Map pack changed on disk: {pack.display_name}; invalidated stale map selection, marker/group, and view references.")
            self.map_selected_location=""; self._close_map_group_popup()
            self._map_marker_items.clear(); self._map_marker_visual_state.clear(); self._map_canonical_marker_state.clear(); self._map_last_statuses={}
            self._map_marker_layout_key=None; self.map_background_key=None; self.map_photo=None
            # Variable(s): `prefix` (prefix); named state retained for the surrounding calculation or subsequent calls.
            prefix=(game+"|") if game else ""
            if prefix:
                # Loop variable(s): `k` (key); each iteration represents the next value from the iterable below.
                for k in list(self.map_selection_memory):
                    if k.startswith(prefix): self.map_selection_memory.pop(k,None)
            # Variable(s): `src_prefix` (src prefix); named state retained for the surrounding calculation or subsequent calls.
            src_prefix=str(pack.source).casefold()+"|"
            # Loop variable(s): `k` (key); each iteration represents the next value from the iterable below.
            for k in list(self.map_view_memory):
                if k.startswith(src_prefix): self.map_view_memory.pop(k,None)
    def _map_variant_key(self, pack):
        """Handle map variant key."""
        try:
            return str(pack.source.resolve())
        except Exception:
            return str(pack.source)
    def _apply_selected_map_variant(self, pack):
        """Return pack parsed with the user's persisted variant selection."""
        if not pack or not getattr(pack, "variants", None):
            if hasattr(self, "map_variant_selector"):
                self.map_variant_choice.set("Auto")
                self.map_variant_selector.configure(values=("Auto",), state="disabled")
            return pack
        key=self._map_variant_key(pack)
        saved=str(self.map_variant_memory.get(key, "Auto") or "Auto")
        display_to_uid={name:uid for uid,name in pack.variants.items()}
        uid_to_display=dict(pack.variants)
        if saved != "Auto" and saved not in display_to_uid:
            saved="Auto"
        requested_uid=(pack.default_variant_uid if saved == "Auto" else display_to_uid.get(saved, pack.default_variant_uid))
        selected=load_pack_variant(pack, requested_uid)
        if hasattr(self, "map_variant_selector"):
            values=("Auto",)+tuple(uid_to_display.values())
            self.map_variant_selector.configure(values=values,state="readonly")
            self.map_variant_choice.set(saved)
        return selected
    def _map_variant_selected(self, _event=None):
        """Handle map variant selected."""
        pack=self.active_map_pack
        if not pack or not getattr(pack, "variants", None):
            return
        key=self._map_variant_key(pack)
        self.map_variant_memory[key]=self.map_variant_choice.get() or "Auto"
        self._save_settings()
        self.map_last_game=""
        self.map_last_runtime_target=None
        self._scan_map_packs()
    def _scan_map_packs(self):
        """Discover installed map packs without blocking Tk; stale results are discarded."""
        generation = int(getattr(self, "_map_pack_scan_generation", 0)) + 1
        self._map_pack_scan_generation = generation
        pending = getattr(self, "_map_pack_scan_after_id", None)
        if pending is not None:
            try: self.root.after_cancel(pending)
            except Exception: _ignored("intentional best-effort fallback")
        if hasattr(self, "map_status"): self.map_status.set("Scanning installed map packs in background…")
        self._map_pack_scan_after_id = self.root.after(40, lambda g=generation: self._start_map_pack_scan(g))

    def _start_map_pack_scan(self, generation):
        """Handle start map pack scan."""
        self._map_pack_scan_after_id = None
        if getattr(self, "_closing", False) or generation != getattr(self, "_map_pack_scan_generation", 0): return
        result_queue = queue.Queue(maxsize=1); started = time.perf_counter()
        def worker():
            """Handle worker."""
            try: result_queue.put(("ok", discover_packs(), round((time.perf_counter()-started)*1000.0,3)))
            except Exception as exc: result_queue.put(("error", exc, round((time.perf_counter()-started)*1000.0,3)))
        threading.Thread(target=worker,name="WayFinder-map-pack-scan",daemon=True).start()
        self.root.after(25, lambda g=generation,q=result_queue:self._poll_map_pack_scan(g,q))

    def _poll_map_pack_scan(self, generation, result_queue):
        """Handle poll map pack scan."""
        if getattr(self, "_closing", False): return
        try: kind,payload,elapsed_ms=result_queue.get_nowait()
        except queue.Empty:
            if generation == getattr(self,"_map_pack_scan_generation",0): self.root.after(25,lambda g=generation,q=result_queue:self._poll_map_pack_scan(g,q))
            return
        if generation != getattr(self,"_map_pack_scan_generation",0): return
        self._map_performance_ms["map_pack_parse"]=elapsed_ms
        if kind == "error":
            self._append_log(f"Map-pack discovery failed: {payload}")
            if hasattr(self,"map_status"): self.map_status.set("Map-pack discovery failed — see Log for details.")
            return
        self._apply_discovered_map_packs(payload)

    def _apply_discovered_map_packs(self, packs):
        """Apply completed background discovery on the Tk main thread."""
        self.map_packs=list(packs or [])
        live={x.name for x in self.snapshot.locations}
        # Installed map packs are user-controlled. Do not disable a pack because
        # optional validation/diagnostic checks dislike its structure or artwork.
        # Variable(s): `pack` (pack), `matches` (matches); named state retained for the surrounding calculation or subsequent calls.
        selection_started=time.perf_counter()
        pack,matches=self._preferred_map_pack(live,self.snapshot.game)
        pack=self._apply_selected_map_variant(pack)
        self._map_performance_ms["map_selection"]=round((time.perf_counter()-selection_started)*1000.0,3)
        if pack:
            matches=len(pack.location_names & live) if live else 0
        self.active_map_pack=pack
        if hasattr(self,"installed_maps_tree"): self._refresh_installed_maps_page()
        if pack: self._invalidate_changed_pack_state(pack)
        if pack and live:
            # Diagnose only concrete marker members using the exact same ID-aware
            # resolver as the renderer. ``pack.location_names`` also contains
            # owner/group/display labels, so subtracting it from live AP names
            # produced large false-positive "will be hidden" reports even when
            # the marker's attached AP ID resolved perfectly.
            state={location.name:location for location in (self.snapshot.locations or [])}
            unresolved_members=[]
            seen_unresolved=set()
            for marker in pack.markers:
                if getattr(marker, "is_synthetic_marker", False):
                    continue
                for member_index,member_name in enumerate(marker.member_names):
                    if self._map_marker_member_location(marker, member_index, state) is not None:
                        continue
                    label=str(member_name or marker.location_name or "").strip()
                    if label and label not in seen_unresolved:
                        seen_unresolved.add(label)
                        unresolved_members.append(label)
            if unresolved_members:
                self._append_log(
                    f"Tracker-pack seed filter: {len(unresolved_members)} concrete map check reference(s) "
                    "could not be matched to the current generated seed by AP ID/name and will be hidden: "
                    + ", ".join(unresolved_members[:12])
                    + (" …" if len(unresolved_members)>12 else "")
                )
        if pack and pack.has_python:
            pack.load_python()
            if pack.python_error:
                self._append_log(f"Map-pack Python for {pack.display_name}: {pack.python_error}")
            else:
                self._append_log((f"Loaded tracker-pack Python API v{pack.python_api_version}: {pack.display_name}" if pack.python_api_version is not None else f"Loaded native tracker-pack Python: {pack.display_name}"))
        if not pack:
            if hasattr(self,"map_canvas"): self.map_canvas.delete("all")
            self._map_marker_items.clear(); self._map_marker_visual_state.clear(); self._map_marker_layout_key=None
            if hasattr(self,"map_selector"): self.map_selector.configure(values=()); self.map_selector_var.set("")
            if hasattr(self,"map_variant_selector"):
                self.map_variant_choice.set("Auto"); self.map_variant_selector.configure(values=("Auto",),state="disabled")
            if hasattr(self,"map_status"):
                # Variable(s): `detail` (detail); named state retained for the surrounding calculation or subsequent calls.
                detail=f"{len(self.map_packs)} pack(s) installed, but none match this game's live locations." if self.map_packs else "No map packs are installed yet."
                self.map_status.set(detail+f"  Library: {default_pack_dir()}")
            if hasattr(self,"map_location_counter"): self.map_location_counter.set("Locations: 0 / 0 visible")
            return
        # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
        names=self._ut_ordered_map_titles(pack,self.snapshot); self.map_selector.configure(values=names)
        # Variable(s): `chosen` (chosen); named state retained for the surrounding calculation or subsequent calls.
        chosen=self._choose_map_for_pack(pack,names,self.snapshot,prefer_hook=True)
        if chosen: self.map_selector_var.set(chosen)
        # Variable(s): `api` (API object); named state retained for the surrounding calculation or subsequent calls.
        api=(f" • Pack API v{pack.python_api_version}" if pack.has_python and pack.python_api_compatible and pack.python_api_version is not None else (" • Native tracker Python" if pack.has_python and pack.python_api_compatible else (" • Python hooks disabled" if pack.has_python else "")))
        variant_text=(f"  •  Variant: {pack.variants.get(pack.variant_uid, pack.variant_uid)}" if getattr(pack,"variants",None) else "")
        self.map_status.set(f"{pack.display_name}{variant_text}  •  {matches} live locations matched  •  {len(pack.maps)} maps  •  {len(pack.markers)} markers{api}")
        self._render_map()
    def _runtime_map_target(self, pack, names, snapshot=None):
        """Return the map currently reported by runtime/pack hooks, if any."""
        if not pack or not names:
            return None
        s=snapshot or self.snapshot
        ut_title=self._ut_map_page_title(pack,s)
        if ut_title in names:
            return ut_title
        if pack.has_python and pack.python_api_compatible:
            hooked=pack.resolve_current_map(s, getattr(s, 'raw_map_page_datastorage_value', None))
            if hooked in names:
                return hooked
            if pack.python_error:
                self._append_log(f"Map-pack hook warning for {pack.display_name}: {pack.python_error}")
        return None
    def _preferred_map_pack(self, live, game):
        """Return the user-selected map pack, or automatic best-match selection."""
        choice=str(self.active_map_pack_choice.get() if hasattr(self,"active_map_pack_choice") else "Auto").strip()
        if not choice or choice == "Auto":
            return best_pack(self.map_packs,live,game)
        for pack in self.map_packs:
            label=f"{pack.display_name}  [{pack.source.name}]"
            if choice == label or choice == pack.display_name or choice == str(pack.source):
                matches=len(pack.location_names & live) if live else 0
                return pack,matches
        # If a previously selected pack was removed, safely fall back to Auto.
        if hasattr(self,"active_map_pack_choice"):
            self.active_map_pack_choice.set("Auto")
        return best_pack(self.map_packs,live,game)

