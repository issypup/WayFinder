# /**
#  * Module: wayfinder.app/map_packs.py
#  * Purpose: GUI module for map packs; presents or coordinates WayFinder state without owning the underlying game logic.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

"""WayFinder map-pack discovery and parsing.

Supports the native tracker-pack convention used by UT-capable packs:
``maps/maps.json`` plus JSON location definitions containing ``map_locations``.
Packs may remain zipped or be extracted into the ``map_packs`` folder.
"""
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

import json
import copy
from collections import OrderedDict
from .assets import LARGE_MAP_PIXELS, open_pack_image, image_hash, file_signature
import os
import sys
import zipfile
import importlib.util
import hashlib
import time
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from wayfinder.storage import app_data_root
from typing import Any
from .interpretation import iter_marker_records, normalize_location_ids
import tempfile
import shutil
import threading
import re

# Constant(s): `TRACKER_PACK_API_VERSION`; shared configuration value(s) intentionally kept stable within this module.
TRACKER_PACK_API_VERSION = 1
# Constant(s): `_PYTHON_MODULE_CACHE`; shared configuration value(s) intentionally kept stable within this module.
_PYTHON_MODULE_CACHE: dict[str, tuple[tuple[tuple[str, int, int], ...], Any, int | None, str]] = {}

# Constant(s): `ZOOM_CACHE_LEVELS`; shared configuration value(s) intentionally kept stable within this module.
ZOOM_CACHE_LEVELS = (2, 5, 10, 15, 20, 25, 50, 75, 100, 125, 150, 175, 200)
# Constant(s): `ZOOM_CACHE_VERSION`; shared configuration value(s) intentionally kept stable within this module.
ZOOM_CACHE_VERSION = 4
# Constant(s): `_CACHE_BUILD_LOCKS`; shared configuration value(s) intentionally kept stable within this module.
_CACHE_BUILD_LOCKS: dict[str, threading.Lock] = {}
# Constant(s): `_CACHE_BUILD_LOCKS_GUARD`; shared configuration value(s) intentionally kept stable within this module.
_CACHE_BUILD_LOCKS_GUARD = threading.Lock()
# Constant(s): `_CACHE_COORDINATOR_LOCK`; shared configuration value(s) intentionally kept stable within this module.
_CACHE_COORDINATOR_LOCK = threading.Lock()
# Constant(s): `DEFAULT_MAP_CACHE_LIMIT_BYTES`; shared configuration value(s) intentionally kept stable within this module.
DEFAULT_MAP_CACHE_LIMIT_BYTES = 1024 * 1024 * 1024
# Constant(s): `SPATIAL_INDEX_CELL`; shared configuration value(s) intentionally kept stable within this module.
SPATIAL_INDEX_CELL = 256

# /**
#  * Function: map_cache_root
#  * Purpose: Perform the map cache root operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def map_cache_root() -> Path:
    """Persistent pre-rendered map cache, kept beside the per-user map-pack library."""
    return default_pack_dir().parent / "map_cache"

# /**
#  * Function: _cache_pack_key
#  * Purpose: Perform the cache pack key operation while keeping the surrounding subsystem state consistent.
#  * @param folder: Folder supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _cache_pack_key(folder: Path) -> str:
    """Handle cache pack key."""
    return folder.name + "-" + hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:12]

# /**
#  * Function: _source_image_hash
#  * Purpose: Perform the source image hash operation while keeping the surrounding subsystem state consistent.
#  * @param pack_source: Pack source supplied by the caller; see type hints and call sites for domain constraints.
#  * @param image_relative: Image relative supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _source_image_hash(pack_source: Path, image_relative: str) -> str:
    # Variable(s): `rel` (rel); named state retained for the surrounding calculation or subsequent calls.
    """Handle source image hash."""
    rel = str(image_relative).replace("\\", "/")
    # Variable(s): `path` (path); named state retained for the surrounding calculation or subsequent calls.
    path = Path(pack_source) / rel
    try:
        return image_hash(path)
    except OSError:
        return "missing"

# /**
#  * Function: cached_map_path
#  * Purpose: Perform the cached map path operation while keeping the surrounding subsystem state consistent.
#  * @param pack_source: Pack source supplied by the caller; see type hints and call sites for domain constraints.
#  * @param image_relative: Image relative supplied by the caller; see type hints and call sites for domain constraints.
#  * @param zoom: Zoom supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def cached_map_path(pack_source: Path, image_relative: str, zoom: int) -> Path:
    # Variable(s): `rel` (rel); named state retained for the surrounding calculation or subsequent calls.
    """Handle cached map path."""
    rel = Path(str(image_relative).replace("\\", "/"))
    # Variable(s): `rel_digest` (rel digest); named state retained for the surrounding calculation or subsequent calls.
    rel_digest = hashlib.sha1(str(rel).encode("utf-8")).hexdigest()[:12]
    # Variable(s): `image_hash` (image hash); named state retained for the surrounding calculation or subsequent calls.
    image_hash = _source_image_hash(Path(pack_source), image_relative)
    return map_cache_root() / _cache_pack_key(Path(pack_source)) / f"v{ZOOM_CACHE_VERSION}" / rel_digest / image_hash / f"{int(zoom):03d}.png"

# /**
#  * Function: remove_pack_zoom_cache
#  * Purpose: Perform the remove pack zoom cache operation while keeping the surrounding subsystem state consistent.
#  * @param pack_source: Pack source supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
_ON_DEMAND_CACHE_WRITES: set[str] = set()
_ON_DEMAND_CACHE_LOCK = threading.Lock()

def persist_zoom_image_async(pack_source: Path, image_relative: str, zoom: int, image: Any) -> bool:
    """Persist an uncommon zoom level after it has already been rendered for display.

    PNG compression is deliberately moved to a separate daemon thread so the
    interactive map-render worker can accept the next request immediately.
    Returns True when a new write was scheduled.
    """
    try:
        target=cached_map_path(pack_source, image_relative, int(zoom))
        if target.is_file():
            return False
        key=str(target)
        with _ON_DEMAND_CACHE_LOCK:
            if key in _ON_DEMAND_CACHE_WRITES:
                return False
            _ON_DEMAND_CACHE_WRITES.add(key)
        copy_image=image.copy()
    except Exception:
        return False
    def worker():
        """Handle worker."""
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp=target.with_suffix(target.suffix + ".tmp")
            copy_image.save(tmp, format="PNG", optimize=False)
            os.replace(tmp, target)
            enforce_map_cache_limit()
        except Exception:
            try: tmp.unlink(missing_ok=True)
            except Exception: _ignored("intentional best-effort fallback")
        finally:
            with _ON_DEMAND_CACHE_LOCK:
                _ON_DEMAND_CACHE_WRITES.discard(key)
    threading.Thread(target=worker, name="WayFinderMapCacheWrite", daemon=True).start()
    return True

def remove_pack_zoom_cache(pack_source: Path) -> None:
    """Handle remove pack zoom cache."""
    shutil.rmtree(map_cache_root() / _cache_pack_key(Path(pack_source)), ignore_errors=True)

# /**
#  * Function: _valid_cached_image
#  * Purpose: Perform the valid cached image operation while keeping the surrounding subsystem state consistent.
#  * @param path: Path supplied by the caller; see type hints and call sites for domain constraints.
#  * @param expected_size: Expected size supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _valid_cached_image(path: Path, expected_size: tuple[int,int] | None = None) -> bool:
    """Handle valid cached image."""
    if not path.is_file() or path.stat().st_size < 32:
        return False
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        # Variable(s): `im` (im); named state retained for the surrounding calculation or subsequent calls.
        with Image.open(path) as im:
            im.verify()
        if expected_size:
            # Variable(s): `im` (im); named state retained for the surrounding calculation or subsequent calls.
            with Image.open(path) as im:
                return (im.width, im.height) == expected_size
        return True
    except Exception:
        try: path.unlink(missing_ok=True)
        except OSError: _ignored("intentional best-effort fallback")
        return False


# /**
#  * Function: _cache_manifest_path
#  * Purpose: Perform the cache manifest path operation while keeping the surrounding subsystem state consistent.
#  * @param pack_source: Pack source supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _cache_manifest_path(pack_source: Path) -> Path:
    """Handle cache manifest path."""
    return map_cache_root() / _cache_pack_key(Path(pack_source)) / f"v{ZOOM_CACHE_VERSION}" / "manifest.json"

# /**
#  * Function: _atomic_json
#  * Purpose: Perform the atomic json operation while keeping the surrounding subsystem state consistent.
#  * @param path: Path supplied by the caller; see type hints and call sites for domain constraints.
#  * @param payload: Payload supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _atomic_json(path: Path, payload: Any) -> None:
    """Handle atomic json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Variable(s): `tmp` (temporary value); named state retained for the surrounding calculation or subsequent calls.
    tmp = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        # Variable(s): `fh` (file handle); named state retained for the surrounding calculation or subsequent calls.
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            _ignored("intentional best-effort fallback")

# /**
#  * Function: _cache_limit_bytes
#  * Purpose: Perform the cache limit bytes operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _cache_limit_bytes() -> int:
    # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
    """Handle cache limit bytes."""
    raw = os.environ.get("WAYFINDER_MAP_CACHE_MB", "").strip()
    if raw:
        try:
            return max(64, int(float(raw))) * 1024 * 1024
        except (TypeError, ValueError):
            _ignored("intentional best-effort fallback")
    return DEFAULT_MAP_CACHE_LIMIT_BYTES

# /**
#  * Function: _cache_size_bytes
#  * Purpose: Perform the cache size bytes operation while keeping the surrounding subsystem state consistent.
#  * @param root: Root supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _cache_size_bytes(root: Path) -> int:
    # Variable(s): `total` (total); named state retained for the surrounding calculation or subsequent calls.
    """Handle cache size bytes."""
    total = 0
    try:
        # Loop variable(s): `p` (p); each iteration represents the next value from the iterable below.
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    _ignored("intentional best-effort fallback")
    except OSError:
        _ignored("intentional best-effort fallback")
    return total

# /**
#  * Function: enforce_map_cache_limit
#  * Purpose: Perform the enforce map cache limit operation while keeping the surrounding subsystem state consistent.
#  * @param limit_bytes: Limit bytes supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def enforce_map_cache_limit(limit_bytes: int | None = None) -> tuple[int, int]:
    """Keep the persistent map cache under a bounded disk budget.

    Old source-hash generations are evicted first by oldest mtime. Current cache
    files remain valid because identity includes cache version + source hash.
    """
    # Variable(s): `root` (root); named state retained for the surrounding calculation or subsequent calls.
    root = map_cache_root()
    # Variable(s): `limit` (limit); named state retained for the surrounding calculation or subsequent calls.
    limit = int(limit_bytes or _cache_limit_bytes())
    if not root.exists():
        return (0, 0)
    # Variable(s): `before` (before); named state retained for the surrounding calculation or subsequent calls.
    before = _cache_size_bytes(root)
    if before <= limit:
        return (before, before)
    # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
    candidates = []
    # Loop variable(s): `p` (p); each iteration represents the next value from the iterable below.
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.name == "manifest.json":
            continue
        try:
            candidates.append((p.stat().st_mtime, p))
        except OSError:
            _ignored("intentional best-effort fallback")
    # Loop variable(s): `_mtime` (mtime), `p` (p); each iteration represents the next value from the iterable below.
    for _mtime, p in sorted(candidates, key=lambda x: x[0]):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            continue
        if _cache_size_bytes(root) <= limit:
            break
    # Prune empty folders afterwards.
    # Loop variable(s): `p` (p); each iteration represents the next value from the iterable below.
    for p in sorted((x for x in root.rglob("*") if x.is_dir()), key=lambda x: len(x.parts), reverse=True):
        try:
            p.rmdir()
        except OSError:
            _ignored("intentional best-effort fallback")
    # Variable(s): `after` (after); named state retained for the surrounding calculation or subsequent calls.
    after = _cache_size_bytes(root)
    return (before, after)

# /**
#  * Function: build_pack_zoom_cache
#  * Purpose: Build the pack zoom cache representation used by the surrounding subsystem.
#  * @param folder: Folder supplied by the caller; see type hints and call sites for domain constraints.
#  * @param progress: Progress supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def build_pack_zoom_cache(folder: Path, progress=None) -> tuple[int, int]:
    """Build a resumable install-time zoom cache through one coordinated worker.

    Existing valid levels are reused. Maps of 16 megapixels or more are
    recorded as deferred without decoding; their requested zoom is cached on
    first viewing. Completion refers to the non-deferred install-time levels.
    """
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
    except Exception:
        return (0, 0)

    # Variable(s): `folder` (folder); named state retained for the surrounding calculation or subsequent calls.
    folder = Path(folder)
    # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
    key = str(folder.resolve()).casefold()
    with _CACHE_BUILD_LOCKS_GUARD:
        # Variable(s): `pack_lock` (pack lock); named state retained for the surrounding calculation or subsequent calls.
        pack_lock = _CACHE_BUILD_LOCKS.setdefault(key, threading.Lock())

    with _CACHE_COORDINATOR_LOCK, pack_lock:
        # Variable(s): `pack` (pack); named state retained for the surrounding calculation or subsequent calls.
        pack = _parse_pack(folder)
        if pack is None:
            return (0, 0)

        # Installation prepares only the overview/default maps. Area maps are
        # rendered and persisted on first use, keeping installation fast and the
        # persistent cache demand-driven.
        priority=[]
        for md in pack.maps:
            title=f"{md.name} {md.title}".casefold()
            if not priority or "overview" in title or "world map" in title or title.strip()=="world":
                priority.append(md)
        seen={m.name for m in priority}
        lazy_maps=[m for m in pack.maps if m.name not in seen]
        # Variable(s): `total` (total); named state retained for the surrounding calculation or subsequent calls.
        total = len(priority) * len(ZOOM_CACHE_LEVELS)
        # Variable(s): `done` (done); named state retained for the surrounding calculation or subsequent calls.
        done = 0
        # Variable(s): `completed` (completed); named state retained for the surrounding calculation or subsequent calls.
        completed = []
        deferred = [{"map":md.name,"image":md.image,"reason":"lazy-on-demand"} for md in lazy_maps]
        # Variable(s): `manifest_path` (manifest path); named state retained for the surrounding calculation or subsequent calls.
        manifest_path = _cache_manifest_path(folder)

        # Loop variable(s): `md` (metadata); each iteration represents the next value from the iterable below.
        for md in priority:
            # Read image headers only: large maps are decoded when first viewed.
            with open_pack_image(pack, md.image) as header:
                if header.width * header.height >= LARGE_MAP_PIXELS:
                    deferred.append({"map": md.name, "image": md.image, "source_size": list(header.size)})
                    total -= len(ZOOM_CACHE_LEVELS)
                    continue
            # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
            raw = pack.read_bytes(md.image)
            # Variable(s): `source_hash` (source hash); named state retained for the surrounding calculation or subsequent calls.
            source_hash = hashlib.sha256(raw).hexdigest()[:20]
            # Variable(s): `opened` (opened); named state retained for the surrounding calculation or subsequent calls.
            with Image.open(__import__("io").BytesIO(raw)) as opened:
                # Variable(s): `source` (source); named state retained for the surrounding calculation or subsequent calls.
                source = opened.convert("RGBA")

            # Variable(s): `completed_levels` (completed levels); named state retained for the surrounding calculation or subsequent calls.
            completed_levels = []
            # Loop variable(s): `zoom` (zoom); each iteration represents the next value from the iterable below.
            for zoom in ZOOM_CACHE_LEVELS:
                # Variable(s): `factor` (factor); named state retained for the surrounding calculation or subsequent calls.
                factor = zoom / 100.0
                # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
                target = (max(1, int(source.width * factor)), max(1, int(source.height * factor)))
                # Variable(s): `out` (out); named state retained for the surrounding calculation or subsequent calls.
                out = cached_map_path(folder, md.image, zoom)

                if not _valid_cached_image(out, target):
                    out.parent.mkdir(parents=True, exist_ok=True)
                    # Variable(s): `rendered` (rendered); named state retained for the surrounding calculation or subsequent calls.
                    rendered = source if zoom == 100 else source.resize(target, Image.Resampling.BILINEAR)
                    # Variable(s): `tmp` (temporary value); named state retained for the surrounding calculation or subsequent calls.
                    tmp = out.with_name(out.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
                    try:
                        rendered.save(tmp, format="PNG", optimize=False)
                        # Variable(s): `verify_im` (verify im); named state retained for the surrounding calculation or subsequent calls.
                        with Image.open(tmp) as verify_im:
                            verify_im.verify()
                        os.replace(tmp, out)
                    finally:
                        try:
                            tmp.unlink(missing_ok=True)
                        except OSError:
                            _ignored("intentional best-effort fallback")

                if not _valid_cached_image(out, target):
                    raise IOError(f"Zoom-cache validation failed for {md.image} at {zoom}%")

                try:
                    os.utime(out, None)
                except OSError:
                    _ignored("intentional best-effort fallback")

                completed_levels.append(int(zoom))
                done += 1
                if progress:
                    progress(done, total, md.title, zoom)

            completed.append({
                "map": md.name,
                "title": md.title,
                "image": md.image,
                "source_hash": source_hash,
                "levels": completed_levels,
                "source_size": [source.width, source.height],
            })

        # Remove obsolete source-hash generations only after successful completion.
        # Variable(s): `cache_root` (cache root); named state retained for the surrounding calculation or subsequent calls.
        cache_root = map_cache_root() / _cache_pack_key(folder) / f"v{ZOOM_CACHE_VERSION}"
        # Loop variable(s): `md` (metadata); each iteration represents the next value from the iterable below.
        for md in pack.maps:
            if any(item["image"] == md.image for item in deferred):
                continue
            # Variable(s): `rel_digest` (rel digest); named state retained for the surrounding calculation or subsequent calls.
            rel_digest = hashlib.sha1(str(Path(str(md.image).replace("\\", "/"))).encode()).hexdigest()[:12]
            # Variable(s): `keep` (keep); named state retained for the surrounding calculation or subsequent calls.
            keep = _source_image_hash(folder, md.image)
            # Variable(s): `base` (base); named state retained for the surrounding calculation or subsequent calls.
            base = cache_root / rel_digest
            if base.is_dir():
                # Loop variable(s): `child` (child); each iteration represents the next value from the iterable below.
                for child in base.iterdir():
                    if child.is_dir() and child.name != keep:
                        shutil.rmtree(child, ignore_errors=True)

        # Variable(s): `manifest` (manifest); named state retained for the surrounding calculation or subsequent calls.
        manifest = {
            "cache_version": ZOOM_CACHE_VERSION,
            "pack": folder.name,
            "generated_at": time.time(),
            "levels": list(ZOOM_CACHE_LEVELS),
            "maps": completed,
            "deferred_maps": deferred,
            "complete": True,
        }
        _atomic_json(manifest_path, manifest)
        enforce_map_cache_limit()
        return done, total

# /**
#  * Class: MapDefinition
#  * Purpose: Encapsulate the MapDefinition responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class MapDefinition:
    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
    """Provide map definition behavior."""
    name: str
    # Variable(s): `image` (image); named state retained for the surrounding calculation or subsequent calls.
    image: str
    # Variable(s): `location_size` (location size); named state retained for the surrounding calculation or subsequent calls.
    location_size: float = 18.0
    # Variable(s): `location_border_thickness` (location border thickness); named state retained for the surrounding calculation or subsequent calls.
    location_border_thickness: float = 1.0
    # Variable(s): `title` (title); named state retained for the surrounding calculation or subsequent calls.
    title: str = ""

# /**
#  * Class: MapMarker
#  * Purpose: Encapsulate the MapMarker responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class MapMarker:
    # Variable(s): `location_name` (location name); named state retained for the surrounding calculation or subsequent calls.
    """Provide map marker behavior."""
    location_name: str
    # Variable(s): `map_name` (map name); named state retained for the surrounding calculation or subsequent calls.
    map_name: str
    # Variable(s): `x` (horizontal x-coordinate); named state retained for the surrounding calculation or subsequent calls.
    x: float
    # Variable(s): `y` (vertical y-coordinate); named state retained for the surrounding calculation or subsequent calls.
    y: float
    # When a UT location node owns multiple ``sections`` at one coordinate,
    # keep them as one visual area marker instead of duplicating the marker.
    # The section names remain the real Archipelago locations.
    # Variable(s): `section_names` (section names); named state retained for the surrounding calculation or subsequent calls.
    section_names: tuple[str, ...] = ()
    # AP location IDs aligned to section_names/member_names. Each member may map to one or more IDs.
    # Variable(s): `section_ids` (section ids); named state retained for the surrounding calculation or subsequent calls.
    section_ids: tuple[tuple[int, ...], ...] = ()
    # Raw PopTracker access rules aligned to section_names.  WayFinder does not
    # interpret arbitrary Lua here; this metadata lets semantic entrance sections
    # distinguish "no extra completion rule" from "rule exists but could not be resolved".
    section_access_rules: tuple[Any, ...] = ()
    # PopTracker sections may be aliases whose authoritative location identity is
    # stored in ``ref`` rather than ``name``. Keep those references aligned with
    # section_names so converted dungeon/submap markers can resolve by AP ID.
    section_refs: tuple[str, ...] = ()
    # Preserve visibility metadata instead of discarding it during normalization.
    node_visibility_rules: tuple[Any, ...] = ()
    map_visibility_rules: tuple[Any, ...] = ()
    # Sections backed by PopTracker hosted_item state are tracker checks even when
    # Archipelago does not expose a separate location ID for them.
    section_tracker_only: tuple[bool, ...] = ()

    # /**
    #  * Function: is_group
    #  * Purpose: Determine whether group is true for the supplied state.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    @property
    def is_group(self) -> bool:
        """Return is group."""
        return len(self.section_names) > 1

    @property
    def is_entrance_marker(self) -> bool:
        """Return whether this marker represents a PopTracker entrance object.

        PopTracker entrance overview maps commonly use a normal ``map_locations``
        coordinate, but the node sections are tracker-only state channels such as
        ``Can Enter`` / ``Can Complete`` rather than Archipelago locations.  Treat
        those nodes as entrances so the GUI does not discard them as locations that
        are absent from the current seed.
        """
        section_names = {name.strip().casefold() for name in self.section_names}
        entrance_sections = {"can enter", "can complete"}
        # Semantic section names are the authoritative signal.  Some PopTracker
        # packs place entrance overview objects on maps named "portals", "doors",
        # "warps", etc., so requiring the literal map name "Entrances" loses
        # valid entrance markers.  Keep the older map-name fallback for packs that
        # expose only one of the two semantic channels.
        if entrance_sections.issubset(section_names):
            return True
        return self.map_name.strip().casefold() in {"entrance", "entrances"} and bool(section_names & entrance_sections)

    # /**
    #  * Function: member_names
    #  * Purpose: Perform the member names operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    @property
    def is_exit_marker(self) -> bool:
        """Return whether this is a synthetic PopTracker exit/transition marker."""
        map_name = self.map_name.strip().casefold()
        section_names = {name.strip().casefold() for name in self.section_names}
        return map_name in {"exit", "exits"} or "entered" in section_names

    @property
    def is_synthetic_marker(self) -> bool:
        """Markers that are useful map objects even when no AP location exists."""
        return self.is_entrance_marker or self.is_exit_marker

    @property
    def member_names(self) -> tuple[str, ...]:
        """Handle member names."""
        return self.section_names or ((self.location_name,) if self.location_name else ())


def _marker_visibility_rule_sets(marker: MapMarker) -> dict[str, set[str]]:
    """Return normalized map-visibility rules grouped by PopTracker rule kind."""
    grouped: dict[str, set[str]] = {}
    for entry in getattr(marker, "map_visibility_rules", ()) or ():
        if not isinstance(entry, dict):
            continue
        kind=str(entry.get("kind", "") or "").strip()
        rule=str(entry.get("rule", "") or "").strip()
        if kind and rule:
            grouped.setdefault(kind, set()).add(rule)
    return grouped


def _markers_are_mutually_exclusive_alternates(first: MapMarker, second: MapMarker) -> bool:
    """Detect two coordinates that represent the same logical marker in alternate PT modes.

    A common PopTracker pattern places one overview coordinate with
    ``force_invisibility_rules: [setting]`` and a second precise coordinate with
    ``restrict_visibility_rules: [setting]``. Only one is intended to exist at a
    time. WayFinder does not execute arbitrary PopTracker setting state, so showing
    both creates duplicate markers.
    """
    if first.map_name != second.map_name:
        return False
    if first.location_name != second.location_name:
        return False
    if tuple(first.member_names) != tuple(second.member_names):
        return False
    if tuple(getattr(first, "section_ids", ()) or ()) != tuple(getattr(second, "section_ids", ()) or ()):
        return False
    if tuple(getattr(first, "section_refs", ()) or ()) != tuple(getattr(second, "section_refs", ()) or ()):
        return False

    a=_marker_visibility_rule_sets(first)
    b=_marker_visibility_rule_sets(second)
    return bool(
        (a.get("force_invisibility_rules", set()) & b.get("restrict_visibility_rules", set()))
        or
        (b.get("force_invisibility_rules", set()) & a.get("restrict_visibility_rules", set()))
    )


def _dedupe_alternate_marker_positions(markers: list[MapMarker]) -> list[MapMarker]:
    """Collapse mutually exclusive alternate coordinates to one default marker.

    Prefer the overview/default coordinate (the one hidden *when* a setting is
    enabled) over the setting-restricted coordinate. This mirrors PopTracker's
    normal default when WayFinder has no equivalent setting available.
    """
    result: list[MapMarker] = []
    for marker in markers:
        replacement_index = None
        for index, existing in enumerate(result):
            if _markers_are_mutually_exclusive_alternates(existing, marker):
                replacement_index = index
                break
        if replacement_index is None:
            result.append(marker)
            continue

        existing=result[replacement_index]
        existing_rules=_marker_visibility_rule_sets(existing)
        marker_rules=_marker_visibility_rule_sets(marker)
        existing_is_overview=bool(existing_rules.get("force_invisibility_rules"))
        marker_is_overview=bool(marker_rules.get("force_invisibility_rules"))
        if marker_is_overview and not existing_is_overview:
            result[replacement_index]=marker
    return result


# /**
#  * Class: MapPack
#  * Purpose: Encapsulate the MapPack responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class MapPack:
    # Variable(s): `source` (source); named state retained for the surrounding calculation or subsequent calls.
    """Provide map pack behavior."""
    source: Path
    # Variable(s): `root_prefix` (root prefix); named state retained for the surrounding calculation or subsequent calls.
    root_prefix: str
    # Variable(s): `maps` (maps); named state retained for the surrounding calculation or subsequent calls.
    maps: list[MapDefinition] = field(default_factory=list)
    # Variable(s): `markers` (markers); named state retained for the surrounding calculation or subsequent calls.
    markers: list[MapMarker] = field(default_factory=list)
    # Variable(s): `display_name` (display name); named state retained for the surrounding calculation or subsequent calls.
    display_name: str = ""
    # Variable(s): `navigation_groups` (navigation groups); named state retained for the surrounding calculation or subsequent calls.
    navigation_groups: list[Any] = field(default_factory=list)
    # Variable(s): `map_order` (map order); named state retained for the surrounding calculation or subsequent calls.
    map_order: list[str] = field(default_factory=list)
    # PopTracker/WayFinder variant metadata. The base pack is parsed as the default variant.
    variants: dict[str, str] = field(default_factory=dict)
    default_variant_uid: str = ""
    variant_uid: str = ""
    # Variable(s): `python_module` (python module); named state retained for the surrounding calculation or subsequent calls.
    python_module: Any = None
    # Variable(s): `python_error` (python error); named state retained for the surrounding calculation or subsequent calls.
    python_error: str = ""
    # None means a native/legacy UT pack with no Visual-GUI API declaration.
    # Variable(s): `python_api_version` (python api version); named state retained for the surrounding calculation or subsequent calls.
    python_api_version: int | None = None
    # Variable(s): `python_api_compatible` (python api compatible); named state retained for the surrounding calculation or subsequent calls.
    python_api_compatible: bool = True
    # Variable(s): `python_signature` (python signature); named state retained for the surrounding calculation or subsequent calls.
    python_signature: tuple[tuple[str, int, int], ...] = field(default_factory=tuple, repr=False)
    # Variable(s): `python_signature_checked_at` (python signature checked at); named state retained for the surrounding calculation or subsequent calls.
    python_signature_checked_at: float = field(default=0.0, repr=False)
    # Variable(s): `maps_by_title` (maps by title); named state retained for the surrounding calculation or subsequent calls.
    maps_by_title: dict[str, MapDefinition] = field(default_factory=dict, init=False, repr=False)
    # Variable(s): `markers_by_map` (markers by map); named state retained for the surrounding calculation or subsequent calls.
    markers_by_map: dict[str, tuple[MapMarker, ...]] = field(default_factory=dict, init=False, repr=False)
    # Variable(s): `markers_by_location` (markers by location); named state retained for the surrounding calculation or subsequent calls.
    markers_by_location: dict[str, tuple[MapMarker, ...]] = field(default_factory=dict, init=False, repr=False)
    # Variable(s): `location_names` (location names); named state retained for the surrounding calculation or subsequent calls.
    location_names: set[str] = field(default_factory=set, init=False, repr=False)
    # Variable(s): `normalized_search_names` (normalized search names); named state retained for the surrounding calculation or subsequent calls.
    normalized_search_names: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    # Variable(s): `marker_spatial_index` (marker spatial index); named state retained for the surrounding calculation or subsequent calls.
    marker_spatial_index: dict[str, dict[tuple[int, int], tuple[int, ...]]] = field(default_factory=dict, init=False, repr=False)

    # /**
    #  * Function: __post_init__
    #  * Purpose: Normalize and validate dataclass state immediately after initialization.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def __post_init__(self) -> None:
        """Build lookup indexes once when a pack is parsed."""
        # PopTracker packs can encode mutually-exclusive overview/precise
        # coordinates for the exact same logical marker. Collapse those before
        # indexing/rendering so WayFinder never displays both at once.
        self.markers = _dedupe_alternate_marker_positions(list(self.markers))
        self.maps_by_title = {m.title: m for m in self.maps}
        # Variable(s): `by_map` (by map); named state retained for the surrounding calculation or subsequent calls.
        by_map: dict[str, list[MapMarker]] = {}
        # Variable(s): `by_location` (by location); named state retained for the surrounding calculation or subsequent calls.
        by_location: dict[str, list[MapMarker]] = {}
        # Loop variable(s): `marker` (marker); each iteration represents the next value from the iterable below.
        for marker in self.markers:
            by_map.setdefault(marker.map_name, []).append(marker)
            # Index both the owning/display label and concrete section members.
            # Complex PopTracker overlays often use generic section channels such
            # as ``Salvage`` while the owning node carries the useful check name.
            indexed_names = tuple(dict.fromkeys((marker.location_name,) + tuple(marker.member_names)))
            for location_name in indexed_names:
                if location_name:
                    by_location.setdefault(location_name, []).append(marker)
        self.markers_by_map = {name: tuple(items) for name, items in by_map.items()}
        self.markers_by_location = {name: tuple(items) for name, items in by_location.items()}
        self.location_names = set(by_location)
        self.normalized_search_names = {
            name: " ".join(name.casefold().replace("_", " ").replace("-", " ").split())
            for name in self.location_names
        }
        # Variable(s): `spatial` (spatial); named state retained for the surrounding calculation or subsequent calls.
        spatial: dict[str, dict[tuple[int, int], list[int]]] = {}
        # Loop variable(s): `map_name` (map name), `items` (items); each iteration represents the next value from the iterable below.
        for map_name, items in self.markers_by_map.items():
            # Variable(s): `cells` (cells); named state retained for the surrounding calculation or subsequent calls.
            cells: dict[tuple[int, int], list[int]] = {}
            # Loop variable(s): `idx` (index), `marker` (marker); each iteration represents the next value from the iterable below.
            for idx, marker in enumerate(items):
                # Variable(s): `cell` (cell); named state retained for the surrounding calculation or subsequent calls.
                cell=(int(marker.x)//SPATIAL_INDEX_CELL, int(marker.y)//SPATIAL_INDEX_CELL)
                cells.setdefault(cell, []).append(idx)
            spatial[map_name] = {cell: tuple(indices) for cell, indices in cells.items()}
        self.marker_spatial_index = spatial

    # /**
    #  * Function: has_python
    #  * Purpose: Determine whether the current state contains or satisfies python.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    @property
    def has_python(self) -> bool:
        """Return has python."""
        return self.source.is_dir() and (self.source / "__init__.py").is_file()

    # /**
    #  * Function: _python_signature
    #  * Purpose: Perform the python signature operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _python_signature(self) -> tuple[tuple[str, int, int], ...]:
        """Fingerprint all Python files so helper-module edits trigger a reload too."""
        if not self.source.is_dir():
            return ()
        # Variable(s): `rows` (rows); named state retained for the surrounding calculation or subsequent calls.
        rows=[]
        # Loop variable(s): `path` (path); each iteration represents the next value from the iterable below.
        for path in sorted(self.source.rglob("*.py")):
            try:
                # Variable(s): `stat` (stat); named state retained for the surrounding calculation or subsequent calls.
                stat=path.stat()
                rows.append((str(path.relative_to(self.source)).replace("\\", "/"), stat.st_mtime_ns, stat.st_size))
            except OSError:
                continue
        return tuple(rows)

    # /**
    #  * Function: load_python
    #  * Purpose: Load python data and convert it into the form expected by WayFinder.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def load_python(self) -> Any:
        """Load or reuse pack Python without requiring Visual-GUI metadata.

        Legacy WayFinder-compatible packs need no TRACKER_PACK_API value.
        Their existing Python is loaded normally and recognised hooks are
        discovered dynamically. TRACKER_PACK_API is optional and is only used
        when a pack explicitly opts into versioned Visual-GUI extensions.
        """
        if not self.has_python:
            self.python_module=None; self.python_api_version=None; self.python_api_compatible=True
            return None
        # Variable(s): `init_py` (init py); named state retained for the surrounding calculation or subsequent calls.
        init_py=self.source / "__init__.py"
        # Variable(s): `resolved` (resolved); named state retained for the surrounding calculation or subsequent calls.
        resolved=str(self.source.resolve())
        # Variable(s): `now` (now); named state retained for the surrounding calculation or subsequent calls.
        now=time.monotonic()
        # Snapshot hooks can run frequently. Limit filesystem fingerprinting to
        # once per second while still automatically picking up edited pack code.
        if self.python_module is not None and (now - self.python_signature_checked_at) < 1.0:
            return self.python_module
        # Variable(s): `signature` (signature); named state retained for the surrounding calculation or subsequent calls.
        signature=self._python_signature()
        self.python_signature_checked_at=now
        self.python_signature=signature
        # Variable(s): `cached` (cached); named state retained for the surrounding calculation or subsequent calls.
        cached=_PYTHON_MODULE_CACHE.get(resolved)
        if cached is not None and cached[0] == signature:
            # Variable(s): `_` (_), `module` (module), `api_version` (api version), `error` (error); named state retained for the surrounding calculation or subsequent calls.
            _,module,api_version,error=cached
            self.python_module=module
            self.python_api_version=api_version
            self.python_api_compatible=(api_version is None or api_version <= TRACKER_PACK_API_VERSION)
            self.python_error=error
            return module

        # Variable(s): `tag` (tag); named state retained for the surrounding calculation or subsequent calls.
        tag=hashlib.sha1(resolved.encode("utf-8")).hexdigest()[:12]
        # Variable(s): `module_name` (module name); named state retained for the surrounding calculation or subsequent calls.
        module_name=f"ut_visual_map_pack_{tag}"
        # Remove the old package and its relative-imported helper modules before reload.
        # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
        for name in [n for n in tuple(sys.modules) if n == module_name or n.startswith(module_name + ".")]:
            sys.modules.pop(name, None)
        importlib.invalidate_caches()
        if cached is not None and cached[0] != signature:
            # Avoid stale timestamp-based .pyc reuse when a helper is edited very
            # quickly (including same-size edits within one filesystem tick).
            # Loop variable(s): `pyc` (pyc); each iteration represents the next value from the iterable below.
            for pyc in self.source.rglob("__pycache__/*.pyc"):
                try:
                    pyc.unlink()
                except OSError:
                    _ignored("intentional best-effort fallback")
        try:
            # Variable(s): `spec` (spec); named state retained for the surrounding calculation or subsequent calls.
            spec=importlib.util.spec_from_file_location(module_name, init_py, submodule_search_locations=[str(self.source)])
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not create module spec for {init_py}")
            # Variable(s): `module` (module); named state retained for the surrounding calculation or subsequent calls.
            module=importlib.util.module_from_spec(spec)
            sys.modules[module_name]=module
            spec.loader.exec_module(module)
            # Variable(s): `raw_api` (raw api); named state retained for the surrounding calculation or subsequent calls.
            raw_api=getattr(module, "TRACKER_PACK_API", None)
            # Variable(s): `api_version` (api version); named state retained for the surrounding calculation or subsequent calls.
            api_version=None
            # Variable(s): `error` (error); named state retained for the surrounding calculation or subsequent calls.
            error=""
            if raw_api is not None:
                try:
                    # Variable(s): `api_version` (api version); named state retained for the surrounding calculation or subsequent calls.
                    api_version=max(1, int(raw_api))
                except (TypeError, ValueError):
                    # Variable(s): `error` (error); named state retained for the surrounding calculation or subsequent calls.
                    error=f"Invalid optional TRACKER_PACK_API value {raw_api!r}; Visual-GUI-specific hooks disabled."
                    # Variable(s): `api_version` (api version); named state retained for the surrounding calculation or subsequent calls.
                    api_version=TRACKER_PACK_API_VERSION + 1
            # Variable(s): `compatible` (compatible); named state retained for the surrounding calculation or subsequent calls.
            compatible=(api_version is None or api_version <= TRACKER_PACK_API_VERSION)
            if not compatible and not error:
                # Variable(s): `error` (error); named state retained for the surrounding calculation or subsequent calls.
                error=f"Tracker Pack API {api_version} is newer than supported API {TRACKER_PACK_API_VERSION}; Visual-GUI-specific hooks disabled."
            self.python_module=module
            self.python_api_version=api_version
            self.python_api_compatible=compatible
            self.python_error=error
            _PYTHON_MODULE_CACHE[resolved]=(signature,module,api_version,error)
            return module
        except Exception as exc:
            # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
            for name in [n for n in tuple(sys.modules) if n == module_name or n.startswith(module_name + ".")]:
                sys.modules.pop(name, None)
            self.python_module=None
            self.python_api_version=None
            self.python_api_compatible=False
            self.python_error=f"{type(exc).__name__}: {exc}"
            _PYTHON_MODULE_CACHE[resolved]=(signature,None,0,self.python_error)
            return None

    # /**
    #  * Function: call_hook
    #  * Purpose: Perform the call hook operation while keeping the surrounding subsystem state consistent.
    #  * @param name: Name supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param default: Default supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param args: Args supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def call_hook(self, name: str, *args: Any, default: Any = None) -> Any:
        """Invoke an optional API hook without allowing pack failures to break the GUI."""
        # Variable(s): `module` (module); named state retained for the surrounding calculation or subsequent calls.
        module=self.load_python()
        if module is None or not self.python_api_compatible:
            return default
        # Variable(s): `hook` (hook); named state retained for the surrounding calculation or subsequent calls.
        hook=getattr(module, name, None)
        if not callable(hook):
            return default
        try:
            # Variable(s): `call_args` (call args); named state retained for the surrounding calculation or subsequent calls.
            call_args=args
            if args:
                try:
                    # Variable(s): `signature` (signature); named state retained for the surrounding calculation or subsequent calls.
                    signature=inspect.signature(hook)
                    # Prefer the richest compatible signature, then progressively
                    # fall back so old one-argument/no-argument UT hooks still work.
                    # Loop variable(s): `count` (count); each iteration represents the next value from the iterable below.
                    for count in range(len(args), -1, -1):
                        try:
                            signature.bind(*args[:count])
                            # Variable(s): `call_args` (call args); named state retained for the surrounding calculation or subsequent calls.
                            call_args=args[:count]
                            break
                        except TypeError:
                            continue
                except (ValueError, AttributeError):
                    _ignored("intentional best-effort fallback")
            return hook(*call_args)
        except Exception as exc:
            self.python_error=f"{name}: {type(exc).__name__}: {exc}"
            return default

    # /**
    #  * Function: resolve_current_map
    #  * Purpose: Perform the resolve current map operation while keeping the surrounding subsystem state consistent.
    #  * @param snapshot: Snapshot supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param raw_map_value: Raw map value supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def resolve_current_map(self, snapshot: Any, raw_map_value: Any = None) -> str | None:
        """Resolve an optional current map from recognised pack hooks.

        Existing/native UT packs require no API declaration. Legacy
        map_page_index() is supported directly; current_map(snapshot) is an
        optional Visual-GUI convenience hook.
        """
        # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
        value=self.call_hook("current_map", snapshot, raw_map_value, default=None)
        # Legacy map_page_index() hooks take the raw DataStorage
        # value as their first/only argument.  Do not pass the snapshot first: a
        # one-argument native hook would otherwise receive the snapshot object,
        # often fall back to map index 0, and force the first map (for example
        # LWN's Shrine) after unrelated tracker/check snapshots.
        if value is None and raw_map_value is not None:
            # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
            value=self.call_hook("map_page_index", raw_map_value, default=None)
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return self.maps[value].title if 0 <= value < len(self.maps) else None
        # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
        text=str(value).strip()
        if not text:
            return None
        if text in self.maps_by_title:
            return text
        # Variable(s): `folded` (folded); named state retained for the surrounding calculation or subsequent calls.
        folded=text.casefold()
        # Loop variable(s): `md` (metadata); each iteration represents the next value from the iterable below.
        for md in self.maps:
            if md.name.casefold() == folded or md.title.casefold() == folded:
                return md.title
        return None

    # /**
    #  * Function: read_bytes
    #  * Purpose: Perform the read bytes operation while keeping the surrounding subsystem state consistent.
    #  * @param relative: Relative supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def read_bytes(self, relative: str) -> bytes:
        # Variable(s): `relative` (relative); named state retained for the surrounding calculation or subsequent calls.
        """Return read bytes."""
        relative = relative.replace("\\", "/").lstrip("/")
        if self.source.is_dir():
            return (self.source / relative).read_bytes()
        # Variable(s): `zf` (ZIP archive handle); named state retained for the surrounding calculation or subsequent calls.
        with zipfile.ZipFile(self.source) as zf:
            return zf.read(self.root_prefix + relative)

# /**
#  * Function: default_pack_dir
#  * Purpose: Perform the default pack dir operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def default_pack_dir() -> Path:
    """Primary writable map-pack library used by Install Map Pack…."""
    # Variable(s): `override` (override); named state retained for the surrounding calculation or subsequent calls.
    override = os.environ.get("WF_MAP_PACKS")
    if override:
        return Path(override).expanduser()
    return app_data_root() / "map_packs"


# /**
#  * Function: portable_pack_dir
#  * Purpose: Perform the portable pack dir operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def portable_pack_dir() -> Path:
    """Backward-compatible alias for the single per-user map-pack library.

    Map packs are no longer stored or scanned beside the executable. Keeping
    this helper avoids breaking older imports while ensuring callers always
    resolve to the AppData/per-user library.
    """
    return default_pack_dir()


# /**
#  * Function: pack_dirs
#  * Purpose: Perform the pack dirs operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def pack_dirs() -> list[Path]:
    """Return only the per-user map-pack library.

    Avoiding a portable fallback prevents discovery from creating a stray
    ``map_packs`` directory beside a frozen executable.
    """
    return [default_pack_dir()]


# /**
#  * Function: _json
#  * Purpose: Perform the json operation while keeping the surrounding subsystem state consistent.
#  * @param raw: Raw value supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _json(raw: bytes) -> Any:
    """Handle json."""
    return json.loads(raw.decode("utf-8-sig"))


# /**
#  * Function: _find_zip_root
#  * Purpose: Locate zip root using the available runtime data.
#  * @param zf: Zip archive handle supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _find_zip_root(zf: zipfile.ZipFile) -> str | None:
    # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
    """Handle find zip root."""
    candidates = [n for n in zf.namelist() if n.replace("\\", "/").endswith("maps/maps.json")]
    if not candidates:
        return None
    # Variable(s): `shortest` (shortest); named state retained for the surrounding calculation or subsequent calls.
    shortest = min(candidates, key=lambda s: (s.count("/"), len(s)))
    return shortest[:-len("maps/maps.json")]


# /**
#  * Function: _normalise_location_ids
#  * Purpose: Perform the normalise location ids operation while keeping the surrounding subsystem state consistent.
#  * @param value: Value supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _normalise_location_ids(value: Any) -> tuple[int, ...]:
    """Compatibility wrapper around the shared tracker interpretation layer."""
    return normalize_location_ids(value)


# /**
#  * Function: _flatten_locations
#  * Purpose: Perform the flatten locations operation while keeping the surrounding subsystem state consistent.
#  * @param value: Value supplied by the caller; see type hints and call sites for domain constraints.
#  * @param out: Out supplied by the caller; see type hints and call sites for domain constraints.
#  * @param id_mapping: Id mapping supplied by the caller; see type hints and call sites for domain constraints.
#  * @param parents: Parents supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _flatten_locations(value: Any, out: list[MapMarker], id_mapping: dict[str, Any] | None = None, parents: tuple[str, ...] = ()) -> None:
    """Create MapMarker objects from the shared WayFinder interpretation records."""
    for record in iter_marker_records(value, id_mapping, parents):
        out.append(MapMarker(
            record["name"],
            record["map_name"],
            record["x"],
            record["y"],
            record["section_names"],
            record["location_ids"],
            record["section_access_rules"],
            record["section_refs"],
            record["visibility_rules"],
            record["map_visibility_rules"],
            section_tracker_only=record.get("section_tracker_only", ()),
        ))


# /**
#  * Function: _parse_pack
#  * Purpose: Parse pack input into a normalized internal representation.
#  * @param source: Source supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */

def _variant_metadata_from_dir(source: Path) -> tuple[dict[str, str], str, dict[str, str]]:
    """Handle variant metadata from dir."""
    path = source / "wayfinder_variants.json"
    if not path.is_file():
        return {}, "", {}
    try:
        raw = _json(path.read_bytes())
    except Exception:
        return {}, "", {}
    variants: dict[str, str] = {}
    overlays: dict[str, str] = {}
    for entry in raw.get("variants", []) if isinstance(raw, dict) else []:
        if not isinstance(entry, dict):
            continue
        uid = str(entry.get("uid") or "").strip()
        if not uid:
            continue
        variants[uid] = str(entry.get("display_name") or uid.replace("_", " ").title())
        overlays[uid] = str(entry.get("overlay") or "").strip().replace("\\", "/")
    default_uid = str(raw.get("default") or "").strip() if isinstance(raw, dict) else ""
    return variants, default_uid, overlays


def _variant_metadata_from_zip(zf: zipfile.ZipFile, root_prefix: str) -> tuple[dict[str, str], str, dict[str, str]]:
    """Handle variant metadata from zip."""
    name = root_prefix + "wayfinder_variants.json"
    if name not in zf.namelist():
        return {}, "", {}
    try:
        raw = _json(zf.read(name))
    except Exception:
        return {}, "", {}
    variants: dict[str, str] = {}
    overlays: dict[str, str] = {}
    for entry in raw.get("variants", []) if isinstance(raw, dict) else []:
        if not isinstance(entry, dict):
            continue
        uid = str(entry.get("uid") or "").strip()
        if not uid:
            continue
        variants[uid] = str(entry.get("display_name") or uid.replace("_", " ").title())
        overlays[uid] = str(entry.get("overlay") or "").strip().replace("\\", "/")
    default_uid = str(raw.get("default") or "").strip() if isinstance(raw, dict) else ""
    return variants, default_uid, overlays


_PARSED_PACK_CACHE = OrderedDict()
_PARSED_PACK_LOCK = threading.RLock()
_PARSED_PACK_BUDGET = 128 * 1024 * 1024


def _pack_signature(source):
    """Handle pack signature."""
    if source.is_dir():
        paths = sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in {".json", ".py"})
        return tuple(file_signature(p) for p in paths)
    return (file_signature(source),)


MAP_METADATA_CACHE_VERSION = 2

def _metadata_cache_path(source: Path, variant_uid: str, signature) -> Path:
    """Handle metadata cache path."""
    digest = hashlib.sha256(repr(signature).encode("utf-8")).hexdigest()[:24]
    variant = hashlib.sha1((variant_uid or "default").encode("utf-8")).hexdigest()[:10]
    return map_cache_root() / _cache_pack_key(source) / "metadata" / f"v{MAP_METADATA_CACHE_VERSION}-{variant}-{digest}.json"

def _pack_to_cache_payload(pack: MapPack) -> dict[str, Any]:
    """Handle pack to cache payload."""
    return {
        "version": MAP_METADATA_CACHE_VERSION,
        "root_prefix": pack.root_prefix,
        "display_name": pack.display_name,
        "maps": [dict(name=m.name, image=m.image, location_size=m.location_size, location_border_thickness=m.location_border_thickness, title=m.title) for m in pack.maps],
        "markers": [dict(
            location_name=m.location_name, map_name=m.map_name, x=m.x, y=m.y,
            section_names=list(m.section_names), section_ids=[list(v) for v in m.section_ids],
            section_access_rules=list(m.section_access_rules), section_refs=list(m.section_refs),
            node_visibility_rules=list(m.node_visibility_rules), map_visibility_rules=list(m.map_visibility_rules),
            section_tracker_only=list(m.section_tracker_only),
        ) for m in pack.markers],
        "navigation_groups": pack.navigation_groups, "map_order": pack.map_order,
        "variants": pack.variants, "default_variant_uid": pack.default_variant_uid, "variant_uid": pack.variant_uid,
    }

def _pack_from_cache_payload(source: Path, payload: dict[str, Any]) -> MapPack | None:
    """Handle pack from cache payload."""
    try:
        if int(payload.get("version", 0)) != MAP_METADATA_CACHE_VERSION:
            return None
        maps=[MapDefinition(**row) for row in payload.get("maps", [])]
        markers=[]
        for row in payload.get("markers", []):
            row=dict(row)
            row["section_names"]=tuple(row.get("section_names", ()))
            row["section_ids"]=tuple(tuple(int(x) for x in ids) for ids in row.get("section_ids", ()))
            row["section_access_rules"]=tuple(row.get("section_access_rules", ()))
            row["section_refs"]=tuple(row.get("section_refs", ()))
            row["node_visibility_rules"]=tuple(row.get("node_visibility_rules", ()))
            row["map_visibility_rules"]=tuple(row.get("map_visibility_rules", ()))
            row["section_tracker_only"]=tuple(bool(v) for v in row.get("section_tracker_only", ()))
            markers.append(MapMarker(**row))
        return MapPack(
            source=source, root_prefix=str(payload.get("root_prefix", "")), maps=maps, markers=markers,
            display_name=str(payload.get("display_name", "")), navigation_groups=list(payload.get("navigation_groups", [])),
            map_order=list(payload.get("map_order", [])), variants=dict(payload.get("variants", {})),
            default_variant_uid=str(payload.get("default_variant_uid", "")), variant_uid=str(payload.get("variant_uid", "")),
        )
    except Exception:
        return None

def _load_metadata_cache(source: Path, variant_uid: str, signature) -> MapPack | None:
    """Handle load metadata cache."""
    path=_metadata_cache_path(source, variant_uid, signature)
    try:
        payload=json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return _pack_from_cache_payload(source, payload)

def _save_metadata_cache(source: Path, variant_uid: str, signature, pack: MapPack) -> None:
    """Handle save metadata cache."""
    path=_metadata_cache_path(source, variant_uid, signature)
    try:
        _atomic_json(path, _pack_to_cache_payload(pack))
    except Exception:
        _ignored("intentional best-effort fallback")

def _parse_pack(source: Path, variant_uid: str | None = None) -> MapPack | None:
    """Reuse parsed definitions and indexes; return independent mutable pack state."""
    source = Path(source)
    try:
        signature = _pack_signature(source)
    except OSError:
        return None
    key = (str(source.resolve()), variant_uid or "")
    with _PARSED_PACK_LOCK:
        entry = _PARSED_PACK_CACHE.pop(key, None)
        if entry is not None and entry[0] == signature:
            _PARSED_PACK_CACHE[key] = entry
            cached=copy.deepcopy(entry[1])
            setattr(cached, "metadata_cache_hit", True)
            return cached
        parsed = _load_metadata_cache(source, variant_uid or "", signature)
        if parsed is not None:
            setattr(parsed, "metadata_cache_hit", True)
        else:
            parsed = _parse_pack_uncached(source, variant_uid)
            if parsed is not None:
                setattr(parsed, "metadata_cache_hit", False)
                _save_metadata_cache(source, variant_uid or "", signature, parsed)
        # Conservative estimate for expanded JSON objects and derived marker indexes.
        weight = sum(row[-1] for row in signature) * 12
        if parsed is not None and not source.is_dir():
            with zipfile.ZipFile(source) as archive:
                weight = sum(info.file_size for info in archive.infolist() if info.filename.lower().endswith((".json", ".py"))) * 12
        if parsed is not None:
            weight += len(parsed.markers) * 2048 + len(parsed.maps) * 4096
        if parsed is not None and weight <= _PARSED_PACK_BUDGET:
            _PARSED_PACK_CACHE[key] = (signature, copy.deepcopy(parsed), weight)
            while len(_PARSED_PACK_CACHE) > 8 or sum(e[2] for e in _PARSED_PACK_CACHE.values()) > _PARSED_PACK_BUDGET:
                _PARSED_PACK_CACHE.popitem(last=False)
        return parsed


def _parse_pack_uncached(source: Path, variant_uid: str | None = None) -> MapPack | None:
    """Handle parse pack uncached."""
    try:
        if source.is_dir():
            # Variable(s): `maps_file` (maps file); named state retained for the surrounding calculation or subsequent calls.
            maps_file = source / "maps" / "maps.json"
            if not maps_file.is_file():
                return None
            # Variable(s): `root_prefix` (root prefix); named state retained for the surrounding calculation or subsequent calls.
            root_prefix = ""
            variants, default_variant_uid, variant_overlays = _variant_metadata_from_dir(source)
            requested_variant = str(variant_uid or default_variant_uid or "").strip()
            overlay_rel = variant_overlays.get(requested_variant, "") if requested_variant else ""
            overlay_root = source / overlay_rel if overlay_rel else None
            variant_maps_file = overlay_root / "maps" / "maps.json" if overlay_root is not None else None
            # Variable(s): `maps_raw` (maps raw); named state retained for the surrounding calculation or subsequent calls.
            maps_raw = _json((variant_maps_file if variant_maps_file is not None and variant_maps_file.is_file() else maps_file).read_bytes())
            # Variable(s): `location_files` (location files); named state retained for the surrounding calculation or subsequent calls.
            location_files = list((source / "locations").glob("**/*.json")) if (source / "locations").is_dir() else []
            # Several dual PopTracker/UT packs keep UT-specific definitions here.
            location_files += list((source / "ut_locations").glob("**/*.json")) if (source / "ut_locations").is_dir() else []
            if overlay_root is not None and overlay_root.is_dir():
                location_files += list((overlay_root / "locations").glob("**/*.json")) if (overlay_root / "locations").is_dir() else []
                location_files += list((overlay_root / "ut_locations").glob("**/*.json")) if (overlay_root / "ut_locations").is_dir() else []
            # Variable(s): `raws` (raws); named state retained for the surrounding calculation or subsequent calls.
            raws = [p.read_bytes() for p in location_files]
            # Variable(s): `layout_files` (layout files); named state retained for the surrounding calculation or subsequent calls.
            layout_files = list((source / "layouts").glob("**/*.json")) if (source / "layouts").is_dir() else []
            if overlay_root is not None and (overlay_root / "layouts").is_dir():
                layout_files += list((overlay_root / "layouts").glob("**/*.json"))
            # Variable(s): `layout_raws` (layout raws); named state retained for the surrounding calculation or subsequent calls.
            layout_raws = [p.read_bytes() for p in layout_files]
            # Variable(s): `id_mapping` (id mapping); named state retained for the surrounding calculation or subsequent calls.
            id_mapping = {}
            # Variable(s): `id_file` (id file); named state retained for the surrounding calculation or subsequent calls.
            id_file = source / "packbash_location_ids.json"
            if id_file.is_file():
                try:
                    # Variable(s): `parsed_ids` (parsed ids); named state retained for the surrounding calculation or subsequent calls.
                    parsed_ids=_json(id_file.read_bytes())
                    # Variable(s): `id_mapping` (id mapping); named state retained for the surrounding calculation or subsequent calls.
                    if isinstance(parsed_ids, dict): id_mapping=parsed_ids
                except Exception:
                    # Variable(s): `id_mapping` (id mapping); named state retained for the surrounding calculation or subsequent calls.
                    id_mapping={}
        else:
            # Variable(s): `zf` (ZIP archive handle); named state retained for the surrounding calculation or subsequent calls.
            with zipfile.ZipFile(source) as zf:
                # Variable(s): `root_prefix` (root prefix); named state retained for the surrounding calculation or subsequent calls.
                root_prefix = _find_zip_root(zf)
                if root_prefix is None:
                    return None
                variants, default_variant_uid, variant_overlays = _variant_metadata_from_zip(zf, root_prefix)
                requested_variant = str(variant_uid or default_variant_uid or "").strip()
                overlay_rel = variant_overlays.get(requested_variant, "") if requested_variant else ""
                overlay_prefix = root_prefix + (overlay_rel.rstrip("/") + "/" if overlay_rel else "")
                variant_maps_name = overlay_prefix + "maps/maps.json" if overlay_rel else ""
                # Variable(s): `maps_raw` (maps raw); named state retained for the surrounding calculation or subsequent calls.
                maps_raw = _json(zf.read(variant_maps_name if variant_maps_name in zf.namelist() else root_prefix + "maps/maps.json"))
                # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
                names = [n for n in zf.namelist() if n.lower().endswith(".json") and (n.startswith(root_prefix+"locations/") or n.startswith(root_prefix+"ut_locations/"))]
                if overlay_rel:
                    names += [n for n in zf.namelist() if n.lower().endswith(".json") and (n.startswith(overlay_prefix+"locations/") or n.startswith(overlay_prefix+"ut_locations/"))]
                # Variable(s): `raws` (raws); named state retained for the surrounding calculation or subsequent calls.
                raws = [zf.read(n) for n in names]
                # Variable(s): `layout_names` (layout names); named state retained for the surrounding calculation or subsequent calls.
                layout_names = [n for n in zf.namelist() if n.lower().endswith(".json") and n.startswith(root_prefix+"layouts/")]
                if overlay_rel:
                    layout_names += [n for n in zf.namelist() if n.lower().endswith(".json") and n.startswith(overlay_prefix+"layouts/")]
                # Variable(s): `layout_raws` (layout raws); named state retained for the surrounding calculation or subsequent calls.
                layout_raws = [zf.read(n) for n in layout_names]
                # Variable(s): `id_mapping` (id mapping); named state retained for the surrounding calculation or subsequent calls.
                id_mapping = {}
                # Variable(s): `id_name` (id name); named state retained for the surrounding calculation or subsequent calls.
                id_name = root_prefix + "packbash_location_ids.json"
                if id_name in zf.namelist():
                    try:
                        # Variable(s): `parsed_ids` (parsed ids); named state retained for the surrounding calculation or subsequent calls.
                        parsed_ids=_json(zf.read(id_name))
                        # Variable(s): `id_mapping` (id mapping); named state retained for the surrounding calculation or subsequent calls.
                        if isinstance(parsed_ids, dict): id_mapping=parsed_ids
                    except Exception:
                        # Variable(s): `id_mapping` (id mapping); named state retained for the surrounding calculation or subsequent calls.
                        id_mapping={}
        if isinstance(maps_raw, dict):
            # Variable(s): `maps_raw` (maps raw); named state retained for the surrounding calculation or subsequent calls.
            maps_raw = maps_raw.get("maps", [])
        # Variable(s): `maps` (maps); named state retained for the surrounding calculation or subsequent calls.
        maps=[]
        # Loop variable(s): `m` (m); each iteration represents the next value from the iterable below.
        for m in maps_raw or []:
            if not isinstance(m, dict) or not m.get("name") or not m.get("img"):
                continue
            maps.append(MapDefinition(
                name=str(m["name"]), image=str(m["img"]),
                location_size=float(m.get("location_size", 18) or 18),
                location_border_thickness=float(m.get("location_border_thickness", 1) or 1),
                title=str(m.get("title") or str(m["name"]).replace("_", " ").title()),
            ))
        # Variable(s): `markers` (markers); named state retained for the surrounding calculation or subsequent calls.
        markers=[]
        # Loop variable(s): `raw` (raw value); each iteration represents the next value from the iterable below.
        for raw in raws:
            try: _flatten_locations(_json(raw), markers, id_mapping)
            except Exception: continue
        if not maps:
            return None
        # Compatible PopTracker layout navigation. We retain the JSON tree and
        # derive leaf map names in traversal order for map-selector ordering.
        # Variable(s): `navigation_groups` (navigation groups); named state retained for the surrounding calculation or subsequent calls.
        navigation_groups=[]
        # /**
        #  * Function: _layout_walk
        #  * Purpose: Perform the layout walk operation while keeping the surrounding subsystem state consistent.
        #  * @param node: Node supplied by the caller; see type hints and call sites for domain constraints.
        #  * @param out: Out supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        def _layout_walk(node, out):
            """Handle layout walk."""
            if isinstance(node, str):
                out.append(node); return
            if isinstance(node, list):
                # Loop variable(s): `child` (child); each iteration represents the next value from the iterable below.
                for child in node: _layout_walk(child, out)
                return
            if not isinstance(node, dict): return
            if isinstance(node.get("map"), str): out.append(node["map"])
            if isinstance(node.get("maps"), list):
                # Loop variable(s): `child` (child); each iteration represents the next value from the iterable below.
                for child in node["maps"]: _layout_walk(child, out)
            if "tabs" in node: _layout_walk(node.get("tabs"), out)
            # Loop variable(s): `key` (key), `child` (child); each iteration represents the next value from the iterable below.
            for key, child in node.items():
                if key not in {"map","maps","tabs","name","title","type"} and isinstance(child,(dict,list)):
                    _layout_walk(child, out)
        # Variable(s): `layout_order` (layout order); named state retained for the surrounding calculation or subsequent calls.
        layout_order=[]
        # Loop variable(s): `raw` (raw value); each iteration represents the next value from the iterable below.
        for raw in layout_raws:
            try:
                # Variable(s): `parsed` (parsed); named state retained for the surrounding calculation or subsequent calls.
                parsed=_json(raw); navigation_groups.append(parsed); _layout_walk(parsed, layout_order)
            except Exception:
                continue
        # Variable(s): `valid_names` (valid names); named state retained for the surrounding calculation or subsequent calls.
        valid_names={m.name for m in maps}
        # Variable(s): `layout_order` (layout order); named state retained for the surrounding calculation or subsequent calls.
        layout_order=[n for n in dict.fromkeys(layout_order) if n in valid_names]
        # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
        name=source.stem.replace("_", " ").replace("-", " ").strip()
        return MapPack(
            source=source, root_prefix=root_prefix, maps=maps, markers=markers, display_name=name,
            navigation_groups=navigation_groups, map_order=layout_order, variants=variants,
            default_variant_uid=default_variant_uid, variant_uid=(requested_variant or default_variant_uid),
        )
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError):
        return None



def load_pack_variant(pack: MapPack, variant_uid: str) -> MapPack:
    """Reload an installed pack using one of its preserved variant overlays."""
    requested = str(variant_uid or pack.default_variant_uid or "").strip()
    if pack.variants and requested not in pack.variants:
        requested = pack.default_variant_uid or next(iter(pack.variants))
    loaded = _parse_pack(pack.source, requested)
    return loaded or pack




# /**
#  * Class: PackValidationResult
#  * Purpose: Encapsulate the PackValidationResult responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class PackValidationResult:
    # Variable(s): `fatal` (fatal); named state retained for the surrounding calculation or subsequent calls.
    """Provide pack validation result behavior."""
    fatal: list[str] = field(default_factory=list)
    # Variable(s): `warnings` (warnings); named state retained for the surrounding calculation or subsequent calls.
    warnings: list[str] = field(default_factory=list)
    # Variable(s): `info` (info); named state retained for the surrounding calculation or subsequent calls.
    info: list[str] = field(default_factory=list)

    # /**
    #  * Function: ok
    #  * Purpose: Perform the ok operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    @property
    def ok(self) -> bool:
        # Map-pack diagnostics are advisory only. Installation/use is controlled
        # by the user, not by WayFinder policy checks.
        """Handle ok."""
        return True

    # /**
    #  * Function: summary
    #  * Purpose: Perform the summary operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def summary(self) -> str:
        """Handle summary."""
        return f"{len(self.fatal)} issue(s) • {len(self.warnings)} note(s) • {len(self.info)} info"

    # /**
    #  * Function: report
    #  * Purpose: Perform the report operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def report(self) -> str:
        # Variable(s): `rows` (rows); named state retained for the surrounding calculation or subsequent calls.
        """Handle report."""
        rows=["Map-Pack Diagnostics (advisory only)", self.summary(), ""]
        if self.fatal:
            rows.append("ISSUES")
            rows.extend(f"  • {x}" for x in self.fatal)
            rows.append("")
        if self.warnings:
            rows.append("NOTES")
            rows.extend(f"  • {x}" for x in self.warnings)
            rows.append("")
        if self.info:
            rows.append("INFORMATION")
            rows.extend(f"  • {x}" for x in self.info)
        return "\n".join(rows).rstrip()


# /**
#  * Function: validate_pack_folder
#  * Purpose: Perform the validate pack folder operation while keeping the surrounding subsystem state consistent.
#  * @param folder: Folder supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def validate_pack_folder(folder: Path) -> PackValidationResult:
    """Validate an extracted native UT tracker pack without executing optional Python."""
    # Variable(s): `folder` (folder); named state retained for the surrounding calculation or subsequent calls.
    folder=Path(folder)
    # Variable(s): `result` (result); named state retained for the surrounding calculation or subsequent calls.
    result=PackValidationResult()
    # Variable(s): `maps_file` (maps file); named state retained for the surrounding calculation or subsequent calls.
    maps_file=folder/'maps'/'maps.json'
    if not maps_file.is_file():
        result.fatal.append('Required file maps/maps.json is missing.')
        return result
    try:
        # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
        raw=json.loads(maps_file.read_text(encoding='utf-8-sig'))
    except Exception as exc:
        result.fatal.append(f'maps/maps.json is malformed JSON: {exc}')
        return result
    # Parse every JSON file up front so errors identify the exact file/line/column.
    # Loop variable(s): `json_path` (json path); each iteration represents the next value from the iterable below.
    for json_path in sorted(folder.rglob('*.json')):
        try:
            json.loads(json_path.read_text(encoding='utf-8-sig'))
        except json.JSONDecodeError as exc:
            # Variable(s): `rel` (rel); named state retained for the surrounding calculation or subsequent calls.
            rel=json_path.relative_to(folder)
            result.fatal.append(f'{rel}: malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}.')
        except Exception as exc:
            result.fatal.append(f'{json_path.relative_to(folder)}: could not be read: {exc}.')
    if result.fatal:
        return result
    try:
        # Variable(s): `pack` (pack); named state retained for the surrounding calculation or subsequent calls.
        pack=_parse_pack(folder)
    except Exception as exc:
        result.fatal.append(f'Tracker-pack data could not be parsed: {type(exc).__name__}: {exc}')
        return result
    if pack is None:
        result.fatal.append('No usable map definitions were found.')
        return result
    if not pack.maps:
        result.fatal.append('Pack contains no maps.')
    if not pack.markers:
        result.warnings.append('Pack contains no map markers/locations.')
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
    except Exception:
        # Variable(s): `Image` (Image); named state retained for the surrounding calculation or subsequent calls.
        Image=None
        result.warnings.append('Pillow is unavailable, so image corruption/dimensions could not be checked.')
    # Variable(s): `dims` (dims); named state retained for the surrounding calculation or subsequent calls.
    dims={}
    # Variable(s): `seen_images` (seen images); named state retained for the surrounding calculation or subsequent calls.
    seen_images=set()
    # Loop variable(s): `md` (metadata); each iteration represents the next value from the iterable below.
    for md in pack.maps:
        # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
        key=md.title.casefold()
        if key in seen_images:
            result.warnings.append(f'Duplicate map title: {md.title!r}.')
        seen_images.add(key)
        # Variable(s): `image_path` (image path); named state retained for the surrounding calculation or subsequent calls.
        image_path=folder/str(md.image).replace('\\','/')
        if not image_path.is_file():
            # Detect Windows-friendly paths whose case is wrong on case-sensitive systems.
            # Variable(s): `cur` (cur); named state retained for the surrounding calculation or subsequent calls.
            cur=folder; mismatch=False
            # Loop variable(s): `part` (part); each iteration represents the next value from the iterable below.
            for part in Path(str(md.image).replace('\\','/')).parts:
                if not cur.is_dir(): break
                # Variable(s): `matches` (matches); named state retained for the surrounding calculation or subsequent calls.
                matches=[x for x in cur.iterdir() if x.name.casefold()==part.casefold()]
                if matches:
                    # Variable(s): `mismatch` (mismatch); named state retained for the surrounding calculation or subsequent calls.
                    if matches[0].name != part: mismatch=True
                    # Variable(s): `cur` (cur); named state retained for the surrounding calculation or subsequent calls.
                    cur=matches[0]
                else: break
            if cur.is_file() and mismatch:
                result.fatal.append(f'Map {md.title!r} image path has a case-sensitive mismatch: {md.image!r}; actual path is {cur.relative_to(folder)}.')
            else:
                result.fatal.append(f'Map {md.title!r} references missing image {md.image!r}.')
            continue
        if image_path.suffix.casefold() not in {'.png','.jpg','.jpeg','.webp','.bmp','.gif'}:
            result.fatal.append(f'Map {md.title!r} uses unsupported image format: {image_path.suffix or "(none)"}.')
            continue
        if Image is not None:
            try:
                # Variable(s): `im` (im); named state retained for the surrounding calculation or subsequent calls.
                with Image.open(image_path) as im:
                    im.verify()
                # Variable(s): `im` (im); named state retained for the surrounding calculation or subsequent calls.
                with Image.open(image_path) as im:
                    dims[md.name]=(int(im.width),int(im.height))
            except Exception as exc:
                result.fatal.append(f'Map image {md.image!r} is corrupt/unreadable: {exc}.')
    # Validate marker identity without treating intentional grouped markers as
    # accidental duplicates. A single marker may legitimately represent several
    # checks at one coordinate (boss + reward, barrier + switch, trial group, etc.).
    # Variable(s): `reference_markers` (reference markers); named state retained for the surrounding calculation or subsequent calls.
    reference_markers={}
    # Variable(s): `coordinate_markers` (coordinate markers); named state retained for the surrounding calculation or subsequent calls.
    coordinate_markers={}
    # Variable(s): `known_names` (known names); named state retained for the surrounding calculation or subsequent calls.
    known_names=set()
    # Loop variable(s): `marker_index` (marker index), `marker` (marker); each iteration represents the next value from the iterable below.
    for marker_index, marker in enumerate(pack.markers):
        # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
        names=tuple(dict.fromkeys(n for n in marker.member_names if n))
        # Variable(s): `marker_identity` (marker identity); named state retained for the surrounding calculation or subsequent calls.
        marker_identity=(marker.map_name,round(marker.x,4),round(marker.y,4),marker_index)
        # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
        for name in names:
            known_names.add(name)
            reference_markers.setdefault(name,[]).append(marker_identity)
        coordinate_markers.setdefault(
            (marker.map_name,round(marker.x,4),round(marker.y,4)),[]
        ).append((marker_index,names))
        if marker.x < 0 or marker.y < 0:
            result.fatal.append(
                f'Negative marker coordinate on {marker.map_name}: '
                f'{list(names) or [marker.location_name]} at ({marker.x}, {marker.y}).'
            )
        # Variable(s): `wh` (wh); named state retained for the surrounding calculation or subsequent calls.
        wh=dims.get(marker.map_name)
        if wh and (marker.x > wh[0] or marker.y > wh[1]):
            result.fatal.append(
                f'Marker outside map boundaries on {marker.map_name}: '
                f'{list(names) or [marker.location_name]} at ({marker.x}, {marker.y}) '
                f'exceeds {wh[0]}×{wh[1]}.'
            )

    # Variable(s): `duplicate_reference_count` (duplicate reference count); named state retained for the surrounding calculation or subsequent calls.
    duplicate_reference_count=0
    # Variable(s): `duplicate_coordinate_count` (duplicate coordinate count); named state retained for the surrounding calculation or subsequent calls.
    duplicate_coordinate_count=0

    # A location shown more than once is only suspicious when it appears on
    # genuinely different marker definitions. Same-coordinate grouped/alias
    # representations are considered intentional.
    # Loop variable(s): `name` (name), `refs` (refs); each iteration represents the next value from the iterable below.
    for name, refs in sorted(reference_markers.items()):
        # Variable(s): `distinct_positions` (distinct positions); named state retained for the surrounding calculation or subsequent calls.
        distinct_positions={(map_name,x,y) for map_name,x,y,_idx in refs}
        if len(distinct_positions)>1:
            duplicate_reference_count+=1
            result.warnings.append(
                f'Location/reference {name!r} appears on {len(distinct_positions)} '
                f'different marker positions: {sorted(distinct_positions)}.'
            )

    # Coordinate collisions are only warnings when two or more separate marker
    # definitions occupy the same coordinate and their member sets do not overlap.
    # Multiple members belonging to one grouped marker are explicitly valid.
    # Loop variable(s): `map_name` (map name), `x` (horizontal x-coordinate), `y` (vertical y-coordinate), `entries` (entries); each iteration represents the next value from the iterable below.
    for (map_name,x,y), entries in sorted(coordinate_markers.items()):
        if len(entries)<=1:
            continue
        # Variable(s): `member_sets` (member sets); named state retained for the surrounding calculation or subsequent calls.
        member_sets=[set(names) for _idx,names in entries if names]
        if len(member_sets)<=1:
            continue
        # Variable(s): `overlaps` (overlaps); named state retained for the surrounding calculation or subsequent calls.
        overlaps=False
        # Loop variable(s): `i` (index), `left` (left); each iteration represents the next value from the iterable below.
        for i,left in enumerate(member_sets):
            # Loop variable(s): `right` (right); each iteration represents the next value from the iterable below.
            for right in member_sets[i+1:]:
                if left & right:
                    # Variable(s): `overlaps` (overlaps); named state retained for the surrounding calculation or subsequent calls.
                    overlaps=True
                    break
            if overlaps:
                break
        if overlaps:
            continue
        # Variable(s): `distinct` (distinct); named state retained for the surrounding calculation or subsequent calls.
        distinct=sorted(set().union(*member_sets))
        duplicate_coordinate_count+=1
        result.warnings.append(
            f'Separate marker definitions share coordinates on {map_name} at '
            f'({x}, {y}): {distinct}.'
        )

    if duplicate_reference_count==0 and duplicate_coordinate_count==0:
        result.info.append('Grouped/shared marker coordinates validated as intentional where applicable.')

    # Generic mapping/hidden-reference diagnostics used by UT/PopTracker hybrid packs.
    # Variable(s): `generated_refs` (generated refs); named state retained for the surrounding calculation or subsequent calls.
    generated_refs=set(known_names)
    # Loop variable(s): `json_path` (json path); each iteration represents the next value from the iterable below.
    for json_path in sorted(folder.rglob('*.json')):
        # Variable(s): `obj` (object); named state retained for the surrounding calculation or subsequent calls.
        try: obj=json.loads(json_path.read_text(encoding='utf-8-sig'))
        except Exception: continue
        # /**
        #  * Function: walk
        #  * Purpose: Perform the walk operation while keeping the surrounding subsystem state consistent.
        #  * @param v: Value supplied by the caller; see type hints and call sites for domain constraints.
        #  * @param path: Path supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        def walk(v,path=''):
            """Handle walk."""
            if isinstance(v,dict):
                # Loop variable(s): `k` (key), `val` (value); each iteration represents the next value from the iterable below.
                for k,val in v.items():
                    # Variable(s): `kp` (kp); named state retained for the surrounding calculation or subsequent calls.
                    kp=f'{path}.{k}' if path else str(k)
                    # Variable(s): `kl` (kl); named state retained for the surrounding calculation or subsequent calls.
                    kl=str(k).casefold()
                    if kl in {'hidden_locations','hidden_location_ids'} and isinstance(val,list):
                        # Loop variable(s): `ref` (ref); each iteration represents the next value from the iterable below.
                        for ref in val:
                            if isinstance(ref,str) and ref not in generated_refs:
                                result.warnings.append(f'{json_path.relative_to(folder)}: hidden location {ref!r} is not a defined pack location.')
                    walk(val,kp)
            elif isinstance(v,list):
                # Loop variable(s): `i` (index), `item` (item); each iteration represents the next value from the iterable below.
                for i,item in enumerate(v): walk(item,f'{path}[{i}]')
        walk(obj)
    # Optional __init__.py is syntax-checked only. Never import/execute during validation.
    # Variable(s): `init_py` (init py); named state retained for the surrounding calculation or subsequent calls.
    init_py=folder/'__init__.py'
    if init_py.is_file():
        try:
            compile(init_py.read_text(encoding='utf-8-sig'), str(init_py), 'exec')
            result.info.append('Optional __init__.py syntax is valid (not executed during validation).')
        except Exception as exc:
            result.fatal.append(f'Optional __init__.py has invalid Python syntax: {exc}.')
    else:
        result.info.append('No optional __init__.py present; this is valid.')
    result.info.append(f'{len(pack.maps)} map(s), {len(pack.markers)} marker(s), {len(known_names)} referenced location name(s).')
    return result


# /**
#  * Function: validate_pack_archive
#  * Purpose: Perform the validate pack archive operation while keeping the surrounding subsystem state consistent.
#  * @param archive: Archive supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def validate_pack_archive(archive: Path) -> tuple[PackValidationResult, Path, Path]:
    """Extract an archive to a private temp directory and validate it before installation."""
    # Variable(s): `archive` (archive); named state retained for the surrounding calculation or subsequent calls.
    archive=Path(archive)
    # Variable(s): `temp_root` (temp root); named state retained for the surrounding calculation or subsequent calls.
    temp_root=Path(tempfile.mkdtemp(prefix='wayfinder-pack-'))
    # Variable(s): `extracted` (extracted); named state retained for the surrounding calculation or subsequent calls.
    extracted=temp_root/'pack'
    extracted.mkdir(parents=True,exist_ok=True)
    try:
        # Variable(s): `zf` (ZIP archive handle); named state retained for the surrounding calculation or subsequent calls.
        with zipfile.ZipFile(archive) as zf:
            # Variable(s): `root_prefix` (root prefix); named state retained for the surrounding calculation or subsequent calls.
            root_prefix=_find_zip_root(zf)
            if root_prefix is None:
                # Variable(s): `r` (r); named state retained for the surrounding calculation or subsequent calls.
                r=PackValidationResult(fatal=['Archive does not contain maps/maps.json in a supported tracker-pack structure.'])
                return r,temp_root,extracted
            # Loop variable(s): `info` (info); each iteration represents the next value from the iterable below.
            for info in zf.infolist():
                # Variable(s): `rel` (rel); named state retained for the surrounding calculation or subsequent calls.
                rel=_safe_member_relative(info.filename,root_prefix)
                if rel is None: continue
                # Variable(s): `out` (out); named state retained for the surrounding calculation or subsequent calls.
                out=extracted/rel
                out.parent.mkdir(parents=True,exist_ok=True)
                # Variable(s): `src` (source), `dst` (destination); named state retained for the surrounding calculation or subsequent calls.
                with zf.open(info) as src, out.open('wb') as dst:
                    shutil.copyfileobj(src,dst,length=1024*1024)
        return validate_pack_folder(extracted),temp_root,extracted
    except Exception as exc:
        return PackValidationResult(fatal=[f'Archive could not be extracted: {type(exc).__name__}: {exc}']),temp_root,extracted


# /**
#  * Function: install_validated_pack
#  * Purpose: Perform the install validated pack operation while keeping the surrounding subsystem state consistent.
#  * @param extracted: Extracted supplied by the caller; see type hints and call sites for domain constraints.
#  * @param archive: Archive supplied by the caller; see type hints and call sites for domain constraints.
#  * @param destination: Destination supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def install_validated_pack(extracted: Path, archive: Path, destination: Path) -> Path:
    """Install a previously validated temporary extraction atomically."""
    # Variable(s): `destination` (destination); named state retained for the surrounding calculation or subsequent calls.
    destination=Path(destination); destination.mkdir(parents=True,exist_ok=True)
    # Variable(s): `folder` (folder); named state retained for the surrounding calculation or subsequent calls.
    folder=destination/Path(archive).stem
    # Variable(s): `staging` (staging); named state retained for the surrounding calculation or subsequent calls.
    staging=destination/(folder.name+'.installing')
    if staging.exists(): shutil.rmtree(staging,ignore_errors=True)
    shutil.copytree(extracted,staging)
    if folder.exists(): shutil.rmtree(folder,ignore_errors=True)
    staging.replace(folder)
    return folder


# /**
#  * Function: _safe_member_relative
#  * Purpose: Perform the safe member relative operation while keeping the surrounding subsystem state consistent.
#  * @param name: Name supplied by the caller; see type hints and call sites for domain constraints.
#  * @param root_prefix: Root prefix supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _safe_member_relative(name: str, root_prefix: str) -> Path | None:
    """Return a safe relative extraction path for one archive member."""
    # Variable(s): `norm` (norm); named state retained for the surrounding calculation or subsequent calls.
    norm = name.replace("\\", "/")
    if root_prefix and not norm.startswith(root_prefix):
        return None
    # Variable(s): `rel` (rel); named state retained for the surrounding calculation or subsequent calls.
    rel = norm[len(root_prefix):].lstrip("/")
    if not rel or rel.endswith("/"):
        return None
    # Variable(s): `candidate` (candidate); named state retained for the surrounding calculation or subsequent calls.
    candidate = Path(rel)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    return candidate


# /**
#  * Function: install_pack_archive
#  * Purpose: Perform the install pack archive operation while keeping the surrounding subsystem state consistent.
#  * @param archive: Archive supplied by the caller; see type hints and call sites for domain constraints.
#  * @param destination: Destination supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def install_pack_archive(archive: Path, destination: Path) -> tuple[Path | None, Path]:
    """Extract a native UT pack into the per-user library.

    A temporary copy is used when necessary, but the archive is deleted after
    successful extraction. The returned archive value is therefore ``None``
    on success.
    """
    # Variable(s): `archive` (archive); named state retained for the surrounding calculation or subsequent calls.
    archive = Path(archive)
    destination.mkdir(parents=True, exist_ok=True)
    # Variable(s): `stored` (stored); named state retained for the surrounding calculation or subsequent calls.
    stored = destination / archive.name
    # Variable(s): `copied` (copied); named state retained for the surrounding calculation or subsequent calls.
    copied = archive.resolve() != stored.resolve()
    if copied:
        import shutil
        shutil.copy2(archive, stored)
    # Variable(s): `temp` (temp); named state retained for the surrounding calculation or subsequent calls.
    temp = destination / (stored.stem + ".extracting")
    try:
        # Variable(s): `zf` (ZIP archive handle); named state retained for the surrounding calculation or subsequent calls.
        with zipfile.ZipFile(stored) as zf:
            # Variable(s): `root_prefix` (root prefix); named state retained for the surrounding calculation or subsequent calls.
            root_prefix = _find_zip_root(zf)
            if root_prefix is None:
                raise ValueError("This archive does not contain maps/maps.json")
            # Variable(s): `folder` (folder); named state retained for the surrounding calculation or subsequent calls.
            folder = destination / stored.stem
            import shutil
            if temp.exists():
                shutil.rmtree(temp)
            temp.mkdir(parents=True)
            # Loop variable(s): `info` (info); each iteration represents the next value from the iterable below.
            for info in zf.infolist():
                # Variable(s): `rel` (rel); named state retained for the surrounding calculation or subsequent calls.
                rel = _safe_member_relative(info.filename, root_prefix)
                if rel is None:
                    continue
                # Variable(s): `out` (out); named state retained for the surrounding calculation or subsequent calls.
                out = temp / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                # Variable(s): `src` (source), `dst` (destination); named state retained for the surrounding calculation or subsequent calls.
                with zf.open(info) as src, out.open("wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
            if not (temp / "maps" / "maps.json").is_file():
                raise ValueError("Map-pack extraction did not produce maps/maps.json")
            if folder.exists():
                shutil.rmtree(folder)
            temp.replace(folder)
        # The extracted folder is the installed representation; do not retain
        # an archive in the library after a successful install.
        stored.unlink(missing_ok=True)
        return None, folder
    except Exception:
        if temp.exists():
            import shutil
            shutil.rmtree(temp, ignore_errors=True)
        # Clean up only a copy we created. Never delete the user's selected
        # source archive when installation fails.
        if copied:
            stored.unlink(missing_ok=True)
        raise


# /**
#  * Function: related_archive_for_folder
#  * Purpose: Perform the related archive for folder operation while keeping the surrounding subsystem state consistent.
#  * @param folder: Folder supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def related_archive_for_folder(folder: Path) -> Path | None:
    """Return a retained archive that belongs to an extracted pack folder."""
    # Variable(s): `parent` (parent); named state retained for the surrounding calculation or subsequent calls.
    parent = folder.parent
    # Loop variable(s): `suffix` (suffix); each iteration represents the next value from the iterable below.
    for suffix in (".zip", ".pack", ".map"):
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        p = parent / (folder.name + suffix)
        if p.is_file():
            return p
    return None

# /**
#  * Function: _game_key
#  * Purpose: Perform the game key operation while keeping the surrounding subsystem state consistent.
#  * @param value: Value supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _game_key(value: str) -> str:
    """Stable comparison key for Archipelago game names used as pack folders."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


# /**
#  * Function: game_pack_dir
#  * Purpose: Perform the game pack dir operation while keeping the surrounding subsystem state consistent.
#  * @param game: Game supplied by the caller; see type hints and call sites for domain constraints.
#  * @param folder: Folder supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def game_pack_dir(game: str, folder: Path | None = None) -> Path:
    """Return the library folder for a game's installed tracker packs."""
    # Variable(s): `root` (root); named state retained for the surrounding calculation or subsequent calls.
    root = Path(folder) if folder is not None else default_pack_dir()
    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
    name = str(game or "").strip()
    # Keep the AP game name readable on disk, only replacing characters Windows
    # cannot use in a folder name.
    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
    name = re.sub(r'[<>:"/\\|?*]+', "_", name).rstrip(" .") or "Unknown Game"
    return root / name


# /**
#  * Function: discover_packs
#  * Purpose: Perform the discover packs operation while keeping the surrounding subsystem state consistent.
#  * @param folder: Folder supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def discover_packs(folder: Path | None = None) -> list[MapPack]:
    # Variable(s): `roots` (roots); named state retained for the surrounding calculation or subsequent calls.
    """Return discover packs."""
    roots = [Path(folder)] if folder is not None else pack_dirs()
    # Variable(s): `found` (found); named state retained for the surrounding calculation or subsequent calls.
    found=[]
    # Variable(s): `seen_sources` (seen sources); named state retained for the surrounding calculation or subsequent calls.
    seen_sources=set()

    # /**
    #  * Function: scan
    #  * Purpose: Perform the scan operation while keeping the surrounding subsystem state consistent.
    #  * @param current: Current supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param recurse_game_dirs: Recurse game dirs supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def scan(current: Path, recurse_game_dirs: bool) -> None:
        """Handle scan."""
        try:
            current.mkdir(parents=True, exist_ok=True)
            # Variable(s): `entries` (entries); named state retained for the surrounding calculation or subsequent calls.
            entries=sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
        except OSError:
            return
        # Variable(s): `extracted_stems` (extracted stems); named state retained for the surrounding calculation or subsequent calls.
        extracted_stems={e.name.casefold() for e in entries if e.is_dir() and (e / "maps" / "maps.json").is_file()}
        # Loop variable(s): `entry` (entry); each iteration represents the next value from the iterable below.
        for entry in entries:
            # New layout: map_packs/<Archipelago Game Name>/<pack>/...
            if entry.is_dir() and not (entry / "maps" / "maps.json").is_file():
                if recurse_game_dirs:
                    scan(entry, False)
                continue
            if entry.is_file() and entry.suffix.lower() in {".zip", ".map", ".pack"} and entry.stem.casefold() in extracted_stems:
                continue
            if not (entry.is_dir() or entry.suffix.lower() in {".zip", ".map", ".pack"}):
                continue
            # Variable(s): `source_key` (source key); named state retained for the surrounding calculation or subsequent calls.
            source_key=str(entry.resolve()).casefold()
            if source_key in seen_sources:
                continue
            # Variable(s): `pack` (pack); named state retained for the surrounding calculation or subsequent calls.
            pack=_parse_pack(entry)
            if pack:
                found.append(pack)
                seen_sources.add(source_key)

    # Loop variable(s): `root` (root); each iteration represents the next value from the iterable below.
    for root in roots:
        scan(root, True)
    return found


# /**
#  * Function: _pack_game_name
#  * Purpose: Perform the pack game name operation while keeping the surrounding subsystem state consistent.
#  * @param pack: Pack supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _pack_game_name(pack: MapPack) -> str:
    """Game name encoded by the new map_packs/<game>/<pack> layout."""
    try:
        # Variable(s): `root` (root); named state retained for the surrounding calculation or subsequent calls.
        root=default_pack_dir().resolve()
        # Variable(s): `source` (source); named state retained for the surrounding calculation or subsequent calls.
        source=pack.source.resolve()
        # Variable(s): `rel` (rel); named state retained for the surrounding calculation or subsequent calls.
        rel=source.relative_to(root)
        if len(rel.parts) >= 2:
            return rel.parts[0]
    except (OSError, ValueError):
        _ignored("intentional best-effort fallback")
    return ""


# /**
#  * Function: best_pack
#  * Purpose: Perform the best pack operation while keeping the surrounding subsystem state consistent.
#  * @param packs: Packs supplied by the caller; see type hints and call sites for domain constraints.
#  * @param live_locations: Live locations supplied by the caller; see type hints and call sites for domain constraints.
#  * @param game: Game supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def best_pack(packs: list[MapPack], live_locations: set[str], game: str = "") -> tuple[MapPack | None, int]:
    """Select by Archipelago game name first; location overlap is validation/tiebreaking.

    Packs installed in the legacy flat library still use location matching so
    existing users are not broken. Newly installed packs live under the game's
    folder and therefore do not depend on seed-specific location overlap.
    """
    # Variable(s): `wanted` (wanted); named state retained for the surrounding calculation or subsequent calls.
    wanted=_game_key(game)
    # Variable(s): `named` (named); named state retained for the surrounding calculation or subsequent calls.
    named=[]
    if wanted:
        # Variable(s): `named` (named); named state retained for the surrounding calculation or subsequent calls.
        named=[p for p in packs if _game_key(_pack_game_name(p)) == wanted]
    # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
    candidates=named if named else [p for p in packs if not _pack_game_name(p)]
    if not candidates:
        return None, 0
    if named:
        # Deterministic even when a seed has zero matching/check locations.
        # Variable(s): `best` (best); named state retained for the surrounding calculation or subsequent calls.
        best=max(candidates, key=lambda p: (len(p.location_names & live_locations), p.display_name.casefold()))
        return best, len(best.location_names & live_locations)
    if not live_locations:
        return None, 0
    # Variable(s): `best` (best); named state retained for the surrounding calculation or subsequent calls.
    best=None; score=0
    # Loop variable(s): `pack` (pack); each iteration represents the next value from the iterable below.
    for pack in candidates:
        # Variable(s): `matches` (matches); named state retained for the surrounding calculation or subsequent calls.
        matches=len(pack.location_names & live_locations)
        if matches > score:
            # Variable(s): `best` (best), `score` (score); named state retained for the surrounding calculation or subsequent calls.
            best,score=pack,matches
    return best,score
