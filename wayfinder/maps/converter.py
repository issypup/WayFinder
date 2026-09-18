# /**
#  * Module: wayfinder.app/pack_converter.py
#  * Purpose: GUI module for pack converter; presents or coordinates WayFinder state without owning the underlying game logic.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

"""Map-pack conversion helpers for WayFinder.

The converter deliberately keeps conversion separate from rendering.  It accepts
common PopTracker and Universal-Tracker-style map packs, normalises the pieces
WayFinder consumes, and writes a portable WayFinder map-pack ZIP.
"""
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from .interpretation import (extract_lua_location_id_mapping, read_compatible_json)

# Constant(s): `WAYFINDER_PACK_FORMAT`; shared configuration value(s) intentionally kept stable within this module.
WAYFINDER_PACK_FORMAT = "wayfinder.map-pack"
# Constant(s): `WAYFINDER_PACK_VERSION`; shared configuration value(s) intentionally kept stable within this module.
WAYFINDER_PACK_VERSION = 1


# /**
#  * Class: ConversionResult
#  * Purpose: Encapsulate the ConversionResult responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class ConversionResult:
    # Variable(s): `output` (output); named state retained for the surrounding calculation or subsequent calls.
    """Provide conversion result behavior."""
    output: Path
    # Variable(s): `source_format` (source format); named state retained for the surrounding calculation or subsequent calls.
    source_format: str
    # Variable(s): `display_name` (display name); named state retained for the surrounding calculation or subsequent calls.
    display_name: str
    # Variable(s): `maps` (maps); named state retained for the surrounding calculation or subsequent calls.
    maps: int
    # Variable(s): `location_files` (location files); named state retained for the surrounding calculation or subsequent calls.
    location_files: int
    # Variable(s): `copied_files` (copied files); named state retained for the surrounding calculation or subsequent calls.
    copied_files: int
    # Variable(s): `warnings` (warnings); named state retained for the surrounding calculation or subsequent calls.
    warnings: tuple[str, ...] = ()


# /**
#  * Function: _read_json
#  * Purpose: Perform the read json operation while keeping the surrounding subsystem state consistent.
#  * @param path: Path supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _strip_json_comments(text: str) -> tuple[str, bool]:
    """Remove JavaScript-style comments without changing quoted JSON strings.

    PopTracker packs are often authored as JSON-with-comments even though Python's
    standard :mod:`json` module intentionally accepts only strict JSON.  This
    scanner preserves every character inside strings (including escaped quotes)
    and replaces comment characters with whitespace/newlines so parse error line
    numbers remain meaningful.
    """
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    changed = False
    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue

        if char == "/" and index + 1 < len(text):
            next_char = text[index + 1]
            if next_char == "/":
                changed = True
                output.extend((" ", " "))
                index += 2
                while index < len(text) and text[index] not in "\r\n":
                    output.append(" ")
                    index += 1
                continue
            if next_char == "*":
                changed = True
                output.extend((" ", " "))
                index += 2
                while index < len(text):
                    if index + 1 < len(text) and text[index] == "*" and text[index + 1] == "/":
                        output.extend((" ", " "))
                        index += 2
                        break
                    output.append(text[index] if text[index] in "\r\n" else " ")
                    index += 1
                continue

        output.append(char)
        index += 1
    return "".join(output), changed


def _strip_trailing_commas(text: str) -> tuple[str, bool]:
    """Remove commas immediately before ``]``/``}``, outside JSON strings."""
    characters = list(text)
    in_string = False
    escaped = False
    changed = False
    index = 0
    while index < len(characters):
        char = characters[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(characters) and characters[lookahead].isspace():
                lookahead += 1
            if lookahead < len(characters) and characters[lookahead] in "]}":
                # Use whitespace rather than deleting the comma so offsets and
                # line/column diagnostics remain as close to the source as possible.
                characters[index] = " "
                changed = True
        index += 1
    return "".join(characters), changed


def _read_json(path: Path, warnings: list[str] | None = None, root: Path | None = None) -> Any:
    """Compatibility wrapper around the shared tracker interpretation layer."""
    return read_compatible_json(path, warnings, root)


# /**
#  * Function: _safe_extract
#  * Purpose: Perform the safe extract operation while keeping the surrounding subsystem state consistent.
#  * @param zf: Zip archive handle supplied by the caller; see type hints and call sites for domain constraints.
#  * @param destination: Destination supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _safe_extract(zf: zipfile.ZipFile, destination: Path) -> None:
    # Variable(s): `base` (base); named state retained for the surrounding calculation or subsequent calls.
    """Handle safe extract."""
    base = destination.resolve()
    # Loop variable(s): `info` (info); each iteration represents the next value from the iterable below.
    for info in zf.infolist():
        # Variable(s): `rel` (rel); named state retained for the surrounding calculation or subsequent calls.
        rel = PurePosixPath(info.filename)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"Unsafe archive member: {info.filename}")
        # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
        target = (destination / Path(*rel.parts)).resolve()
        if target != base and base not in target.parents:
            raise ValueError(f"Unsafe archive member: {info.filename}")
    zf.extractall(destination)


# /**
#  * Function: _find_root
#  * Purpose: Locate root using the available runtime data.
#  * @param extracted: Extracted supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _find_root(extracted: Path) -> Path:
    """Find the smallest directory that looks like a tracker/map pack."""
    # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
    candidates: list[Path] = []
    # Loop variable(s): `maps_json` (maps json); each iteration represents the next value from the iterable below.
    for maps_json in extracted.rglob("maps.json"):
        if maps_json.parent.name.casefold() == "maps":
            candidates.append(maps_json.parent.parent)
    if candidates:
        return sorted(candidates, key=lambda p: (len(p.relative_to(extracted).parts), str(p)))[0]

    # Some PopTracker packs describe maps through a root manifest/layout but may
    # still contain a maps directory.  Prefer the manifest-bearing directory.
    # Variable(s): `manifests` (manifests); named state retained for the surrounding calculation or subsequent calls.
    manifests = list(extracted.rglob("manifest.json"))
    if manifests:
        return sorted((p.parent for p in manifests), key=lambda p: (len(p.relative_to(extracted).parts), str(p)))[0]
    raise ValueError("No maps/maps.json or PopTracker manifest.json was found in the selected pack.")


# /**
#  * Function: _normalise_maps
#  * Purpose: Perform the normalise maps operation while keeping the surrounding subsystem state consistent.
#  * @param root: Root supplied by the caller; see type hints and call sites for domain constraints.
#  * @param warnings: Warnings supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _normalise_maps(root: Path, warnings: list[str]) -> tuple[list[dict[str, Any]], set[str]]:
    # Variable(s): `path` (path); named state retained for the surrounding calculation or subsequent calls.
    """Handle normalise maps."""
    path = root / "maps" / "maps.json"
    if not path.is_file():
        raise ValueError("This pack does not contain maps/maps.json. WayFinder currently needs explicit map definitions to convert it.")
    # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
    raw = _read_json(path, warnings, root)
    if isinstance(raw, dict):
        # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
        raw = raw.get("maps", raw.get("data", []))
    if not isinstance(raw, list):
        raise ValueError("maps/maps.json does not contain a map list.")

    # Variable(s): `out` (out); named state retained for the surrounding calculation or subsequent calls.
    out: list[dict[str, Any]] = []
    # Variable(s): `image_refs` (image refs); named state retained for the surrounding calculation or subsequent calls.
    image_refs: set[str] = set()
    # Loop variable(s): `idx` (index), `entry` (entry); each iteration represents the next value from the iterable below.
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            warnings.append(f"Ignored non-object map entry #{idx + 1}.")
            continue
        # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
        name = str(entry.get("name") or entry.get("id") or "").strip()
        # Variable(s): `image` (image); named state retained for the surrounding calculation or subsequent calls.
        image = str(entry.get("img") or entry.get("image") or "").strip().replace("\\", "/")
        if not name or not image:
            warnings.append(f"Ignored map entry #{idx + 1} because it has no name or image.")
            continue
        # Variable(s): `title` (title); named state retained for the surrounding calculation or subsequent calls.
        title = str(entry.get("title") or entry.get("display_name") or name.replace("_", " ").title()).strip()
        # Variable(s): `normal` (normal); named state retained for the surrounding calculation or subsequent calls.
        normal = dict(entry)
        normal["name"] = name
        normal["img"] = image
        normal["title"] = title
        normal.pop("image", None)
        normal.setdefault("location_size", 18)
        normal.setdefault("location_border_thickness", 1)
        out.append(normal)
        image_refs.add(image)
    if not out:
        raise ValueError("No usable map definitions were found in maps/maps.json.")
    return out, image_refs


# /**
#  * Function: _copy_tree_json
#  * Purpose: Perform the copy tree json operation while keeping the surrounding subsystem state consistent.
#  * @param src: Source supplied by the caller; see type hints and call sites for domain constraints.
#  * @param dst: Destination supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _copy_tree_json(src: Path, dst: Path, warnings: list[str] | None = None, pack_root: Path | None = None) -> int:
    """Handle copy tree json."""
    if not src.is_dir():
        return 0
    # Variable(s): `count` (count); named state retained for the surrounding calculation or subsequent calls.
    count = 0
    # Loop variable(s): `path` (path); each iteration represents the next value from the iterable below.
    for path in src.rglob("*.json"):
        # Variable(s): `rel` (rel); named state retained for the surrounding calculation or subsequent calls.
        rel = path.relative_to(src)
        # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        # Re-serialise JSON so converted packs are consistently UTF-8 and also
        # fail early on malformed input instead of installing a broken pack.
        # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
        data = _read_json(path, warnings, pack_root or src)
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        count += 1
    return count



def _extract_poptracker_location_id_mapping(root: Path, warnings: list[str] | None = None) -> dict[str, Any]:
    """Compatibility wrapper around the shared tracker interpretation layer."""
    return extract_lua_location_id_mapping(root, warnings)


# /**
#  * Function: _copy_if_exists
#  * Purpose: Perform the copy if exists operation while keeping the surrounding subsystem state consistent.
#  * @param src: Source supplied by the caller; see type hints and call sites for domain constraints.
#  * @param dst: Destination supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */


def _extract_poptracker_variants(root: Path, warnings: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Read PopTracker manifest variants and describe their overlay directories.

    PopTracker variants are layered over the base pack: the base/root files remain
    available and a directory named after the variant UID can replace or add files.
    WayFinder preserves that model instead of flattening the currently active variant.
    """
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        manifest = _read_json(manifest_path, warnings, root)
    except Exception:
        return {}
    raw_variants = manifest.get("variants") if isinstance(manifest, dict) else None
    if not isinstance(raw_variants, dict):
        return {}
    variants: dict[str, dict[str, Any]] = {}
    for uid, raw in raw_variants.items():
        uid = str(uid).strip()
        if not uid:
            continue
        info = raw if isinstance(raw, dict) else {}
        display_name = str(info.get("display_name") or info.get("name") or uid.replace("_", " ").title()).strip()
        overlay = root / uid
        variants[uid] = {
            "uid": uid,
            "display_name": display_name,
            "flags": list(info.get("flags") or []) if isinstance(info.get("flags"), list) else [],
            "overlay": f"variants/{uid}" if overlay.is_dir() else "",
        }
    return variants


def _copy_variant_overlay(root: Path, uid: str, stage: Path, warnings: list[str]) -> int:
    """Copy one PopTracker variant overlay into WayFinder's variants/<uid> tree."""
    source = root / uid
    if not source.is_dir():
        return 0
    destination = stage / "variants" / uid
    copied = 0
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.casefold() == ".json":
            try:
                data = _read_json(path, warnings, root)
                target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            except Exception as exc:
                warnings.append(f"Variant {uid}: could not convert {rel.as_posix()}: {exc}")
                continue
        else:
            shutil.copy2(path, target)
        copied += 1
    return copied



def _extract_poptracker_entrance_completion_ids(
    root: Path,
    location_id_mapping: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Infer AP completion-location IDs for PopTracker ``Can Complete`` sections.

    Entrance overview maps often expose tracker-only ``Can Enter``/``Can Complete``
    sections.  ``Can Complete`` commonly points through a Lua helper rather than
    directly at an AP location.  Resolve two widely used PopTracker conventions:

    * ``$canCompleteActAt|key`` -> an internal act-completion node whose rules
      reference one or more concrete ``@tracker/path`` locations;
    * a direct ``@tracker/path`` rule on the ``Can Complete`` section itself.

    The resulting AP IDs are written against the full hierarchical section path,
    allowing WayFinder to use live native location state without executing pack Lua.
    Packs that do not use these patterns are left untouched.
    """
    if not location_id_mapping:
        return {}

    def strings(value: Any):
        """Handle strings."""
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for child in value:
                yield from strings(child)
        elif isinstance(value, dict):
            for child in value.values():
                yield from strings(child)

    direct_path_pattern = re.compile(r"@([^,\]\[]+)")
    helper_pattern = re.compile(r"\$canCompleteActAt\|\s*([^,\]\s]+)")

    def resolve_mapped_path(path: str) -> str:
        """Return resolve mapped path."""
        path = str(path or "").strip().strip("/")
        if not path:
            return ""
        if path in location_id_mapping:
            return path
        matches = [
            candidate for candidate in location_id_mapping
            if candidate.endswith("/" + path) or path.endswith("/" + candidate)
        ]
        return matches[0] if len(matches) == 1 else ""

    # First build helper-key -> concrete tracker paths from the pack's own
    # internal act-completion logic.  This is more authoritative than game-specific
    # naming guesses and works when the displayed entrance label differs from the
    # completion check path.
    completion_paths_by_key: dict[str, list[str]] = {}
    logic_root = root / "locations" / "logic"
    if logic_root.is_dir():
        for json_path in sorted(logic_root.rglob("*.json")):
            try:
                data = _read_json(json_path, warnings, root)
            except Exception:
                continue

            def collect_completion_nodes(value: Any) -> None:
                """Return collect completion nodes."""
                if isinstance(value, list):
                    for child in value:
                        collect_completion_nodes(child)
                    return
                if not isinstance(value, dict):
                    return
                key = str(value.get("name", "")).strip()
                if key and "access_rules" in value:
                    paths: list[str] = []
                    for rule_text in strings(value.get("access_rules", [])):
                        for match in direct_path_pattern.finditer(rule_text):
                            path = match.group(1).strip().strip("/")
                            resolved_path = resolve_mapped_path(path)
                            if resolved_path and resolved_path not in paths:
                                paths.append(resolved_path)
                    if paths:
                        completion_paths_by_key.setdefault(key, []).extend(
                            path for path in paths if path not in completion_paths_by_key.get(key, [])
                        )
                collect_completion_nodes(value.get("children", []))

            collect_completion_nodes(data)

    # Fall back to chapter_info.lua Act.new metadata for packs where the internal
    # completion JSON does not expose a direct mapped path.
    chapter_info_candidates = sorted(root.glob("scripts/**/chapter_info.lua"))
    act_pattern = re.compile(
        r"(?:[A-Za-z0-9_]+)\s*=\s*Act\.new\(\s*[^,]+\s*,\s*([\"'])"
        r"([^\"']+)\1\s*,\s*([\"'])[^\"']*\3\s*,\s*"
        r"(?:(?:[\"'])([^\"']+)(?:[\"'])|nil)",
        re.MULTILINE,
    )
    for lua_path in chapter_info_candidates:
        try:
            text = lua_path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        for match in act_pattern.finditer(text):
            helper_key = match.group(2).strip()
            completion_path = (match.group(4) or "").strip().lstrip("@/")
            resolved_path = resolve_mapped_path(completion_path)
            if helper_key and resolved_path:
                completion_paths_by_key.setdefault(helper_key, [])
                if resolved_path not in completion_paths_by_key[helper_key]:
                    completion_paths_by_key[helper_key].append(resolved_path)

    inferred: dict[str, Any] = {}

    def ids_for_paths(paths: list[str]) -> list[int]:
        """Handle ids for paths."""
        ids: list[int] = []
        for path in paths:
            raw = location_id_mapping.get(path)
            values = raw if isinstance(raw, (list, tuple, set)) else (raw,)
            for value in values:
                try:
                    ident = int(value)
                except (TypeError, ValueError):
                    continue
                if ident not in ids:
                    ids.append(ident)
        return ids

    def walk(value: Any, parents: tuple[str, ...] = ()) -> None:
        """Handle walk."""
        if isinstance(value, list):
            for child in value:
                walk(child, parents)
            return
        if not isinstance(value, dict):
            return
        name = str(value.get("name", "")).strip()
        node_path = parents + ((name,) if name else ())
        for section in value.get("sections", []) or []:
            if not isinstance(section, dict):
                continue
            section_name = str(section.get("name", "")).strip()
            if section_name.casefold() != "can complete":
                continue

            rule_texts = list(strings(section.get("access_rules", [])))
            completion_paths: list[str] = []
            for rule_text in rule_texts:
                helper_match = helper_pattern.search(rule_text)
                if helper_match:
                    helper_key = helper_match.group(1).strip()
                    for path in completion_paths_by_key.get(helper_key, []):
                        if path not in completion_paths:
                            completion_paths.append(path)
                for path_match in direct_path_pattern.finditer(rule_text):
                    path = path_match.group(1).strip().strip("/")
                    resolved_path = resolve_mapped_path(path)
                    if resolved_path and resolved_path not in completion_paths:
                        completion_paths.append(resolved_path)

            location_ids = ids_for_paths(completion_paths)
            if not location_ids:
                continue
            section_path = "/".join(node_path + (section_name,))
            inferred[section_path] = location_ids[0] if len(location_ids) == 1 else location_ids
        walk(value.get("children", []), node_path)

    locations_root = root / "locations"
    if locations_root.is_dir():
        for json_path in sorted(locations_root.rglob("*.json")):
            try:
                data = _read_json(json_path, warnings, root)
            except Exception:
                continue
            walk(data)

    if inferred and warnings is not None:
        warnings.append(
            f"Resolved {len(inferred)} PopTracker entrance Can Complete section(s) "
            "to Archipelago completion location IDs."
        )
    return inferred


def _audit_poptracker_entrance_semantics(
    root: Path,
    location_id_mapping: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Audit entrance-like PopTracker nodes using pack-agnostic semantic rules.

    The audit intentionally does not depend on a map being named ``Entrances``.
    Any node exposing ``Can Enter`` and/or ``Can Complete`` is inspected.  A
    ``Can Complete`` section is classified as one of:

    * ``mapped_completion`` -- the hierarchical section path resolves to one or
      more Archipelago location IDs;
    * ``inherits_entrance`` -- the section has no extra access rule, so its live
      state may safely follow entrance reachability;
    * ``unresolved_rule`` -- a rule exists but could not be reduced to an AP
      location, so WayFinder must preserve ``Unknown`` rather than guessing.

    The report is embedded into converted packs so future diagnostics can explain
    exactly what was inferred rather than relying on game-specific exceptions.
    """
    records: list[dict[str, Any]] = []

    def walk(value: Any, parents: tuple[str, ...] = ()) -> None:
        """Handle walk."""
        if isinstance(value, list):
            for child in value:
                walk(child, parents)
            return
        if not isinstance(value, dict):
            return
        name = str(value.get("name", "")).strip()
        node_path = parents + ((name,) if name else ())
        sections = [s for s in (value.get("sections", []) or []) if isinstance(s, dict)]
        section_names = {str(s.get("name", "")).strip().casefold() for s in sections}
        if section_names & {"can enter", "can complete"}:
            map_names = sorted({
                str(pos.get("map", "")).strip()
                for pos in (value.get("map_locations", []) or [])
                if isinstance(pos, dict) and str(pos.get("map", "")).strip()
            })
            record: dict[str, Any] = {
                "path": "/".join(node_path),
                "maps": map_names,
                "has_can_enter": "can enter" in section_names,
                "has_can_complete": "can complete" in section_names,
            }
            for section in sections:
                section_name = str(section.get("name", "")).strip()
                if section_name.casefold() != "can complete":
                    continue
                section_path = "/".join(node_path + (section_name,))
                mapped = location_id_mapping.get(section_path)
                rules = section.get("access_rules", []) or []
                if mapped not in (None, [], (), ""):
                    classification = "mapped_completion"
                elif not rules:
                    classification = "inherits_entrance"
                else:
                    classification = "unresolved_rule"
                record["can_complete"] = {
                    "classification": classification,
                    "section_path": section_path,
                    "location_ids": mapped if mapped is not None else [],
                    "access_rules": rules,
                }
            records.append(record)
        walk(value.get("children", []), node_path)

    locations_root = root / "locations"
    if locations_root.is_dir():
        for json_path in sorted(locations_root.rglob("*.json")):
            try:
                data = _read_json(json_path, warnings, root)
            except Exception:
                continue
            walk(data)

    counts = {"mapped_completion": 0, "inherits_entrance": 0, "unresolved_rule": 0}
    for record in records:
        classification = (record.get("can_complete") or {}).get("classification")
        if classification in counts:
            counts[classification] += 1
    report = {
        "format": "wayfinder.poptracker-entrance-semantics",
        "version": 1,
        "rules": {
            "semantic_detection": "Can Enter/Can Complete section names are authoritative even on non-Entrances maps.",
            "mapped_completion": "Use the mapped Archipelago completion location state.",
            "inherits_entrance": "If Can Complete has no extra rule and no mapped AP location, inherit entrance reachability.",
            "unresolved_rule": "If an unmapped Can Complete rule exists, preserve Unknown and report it; never guess.",
        },
        "counts": {"entrance_like_nodes": len(records), **counts},
        "entries": records,
    }
    if records and warnings is not None:
        warnings.append(
            "PopTracker entrance semantic audit: "
            f"{len(records)} entrance-like node(s); "
            f"{counts['mapped_completion']} mapped completion, "
            f"{counts['inherits_entrance']} inherited completion, "
            f"{counts['unresolved_rule']} unresolved rule(s)."
        )
        if counts["unresolved_rule"]:
            warnings.append(
                "Some PopTracker Can Complete rules could not be reduced to Archipelago locations; "
                "WayFinder will show Unknown for those sections instead of guessing."
            )
    return report

def _copy_if_exists(src: Path, dst: Path) -> bool:
    """Handle copy if exists."""
    if not src.is_file():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


# /**
#  * Function: _copy_assets
#  * Purpose: Perform the copy assets operation while keeping the surrounding subsystem state consistent.
#  * @param root: Root supplied by the caller; see type hints and call sites for domain constraints.
#  * @param stage: Stage supplied by the caller; see type hints and call sites for domain constraints.
#  * @param image_refs: Image refs supplied by the caller; see type hints and call sites for domain constraints.
#  * @param warnings: Warnings supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _copy_assets(root: Path, stage: Path, image_refs: set[str], warnings: list[str]) -> int:
    # Variable(s): `copied` (copied); named state retained for the surrounding calculation or subsequent calls.
    """Handle copy assets."""
    copied = 0
    # Loop variable(s): `rel` (rel); each iteration represents the next value from the iterable below.
    for rel in sorted(image_refs):
        # Variable(s): `rel_path` (rel path); named state retained for the surrounding calculation or subsequent calls.
        rel_path = Path(*PurePosixPath(rel).parts)
        # Variable(s): `src` (source); named state retained for the surrounding calculation or subsequent calls.
        src = root / rel_path
        if src.is_file():
            # Variable(s): `dst` (destination); named state retained for the surrounding calculation or subsequent calls.
            dst = stage / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
        else:
            warnings.append(f"Referenced map image was not found: {rel}")

    # Preserve common icon/resource directories.  They are harmless to
    # WayFinder and useful if pack support expands later.
    # Loop variable(s): `dirname` (dirname); each iteration represents the next value from the iterable below.
    for dirname in ("images", "icons", "resources"):
        # Variable(s): `src_dir` (src dir); named state retained for the surrounding calculation or subsequent calls.
        src_dir = root / dirname
        if not src_dir.is_dir():
            continue
        # Loop variable(s): `path` (path); each iteration represents the next value from the iterable below.
        for path in src_dir.rglob("*"):
            if not path.is_file():
                continue
            # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
            target = stage / dirname / path.relative_to(src_dir)
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied += 1
    return copied


# /**
#  * Function: _display_name
#  * Purpose: Perform the display name operation while keeping the surrounding subsystem state consistent.
#  * @param root: Root supplied by the caller; see type hints and call sites for domain constraints.
#  * @param fallback: Fallback supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _display_name(root: Path, fallback: str, warnings: list[str] | None = None) -> str:
    # Variable(s): `manifest` (manifest); named state retained for the surrounding calculation or subsequent calls.
    """Handle display name."""
    manifest = root / "manifest.json"
    if manifest.is_file():
        try:
            # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
            raw = _read_json(manifest, warnings, root)
            if isinstance(raw, dict):
                # Loop variable(s): `key` (key); each iteration represents the next value from the iterable below.
                for key in ("name", "display_name", "title"):
                    # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
                    value = raw.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        except Exception:
            _ignored("intentional best-effort fallback")
    return fallback


# /**
#  * Function: convert_map_pack
#  * Purpose: Perform the convert map pack operation while keeping the surrounding subsystem state consistent.
#  * @param source: Source supplied by the caller; see type hints and call sites for domain constraints.
#  * @param output: Output supplied by the caller; see type hints and call sites for domain constraints.
#  * @param source_format: Source format supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def convert_map_pack(source: Path, output: Path, source_format: str) -> ConversionResult:
    # Variable(s): `source` (source); named state retained for the surrounding calculation or subsequent calls.
    """Return convert map pack."""
    source = Path(source)
    # Variable(s): `output` (output); named state retained for the surrounding calculation or subsequent calls.
    output = Path(output)
    # Variable(s): `source_format` (source format); named state retained for the surrounding calculation or subsequent calls.
    source_format = source_format.strip().casefold()
    if source_format not in {"poptracker", "universal_tracker"}:
        raise ValueError(f"Unsupported source format: {source_format}")
    if not source.is_file():
        raise FileNotFoundError(source)
    if output.suffix.casefold() != ".zip":
        # Variable(s): `output` (output); named state retained for the surrounding calculation or subsequent calls.
        output = output.with_suffix(".zip")

    # Variable(s): `warnings` (warnings); named state retained for the surrounding calculation or subsequent calls.
    warnings: list[str] = []
    # Variable(s): `tmp` (temporary value); named state retained for the surrounding calculation or subsequent calls.
    with tempfile.TemporaryDirectory(prefix="wayfinder-pack-convert-") as tmp:
        # Variable(s): `temp` (temp); named state retained for the surrounding calculation or subsequent calls.
        temp = Path(tmp)
        # Variable(s): `extracted` (extracted); named state retained for the surrounding calculation or subsequent calls.
        extracted = temp / "source"
        # Variable(s): `stage` (stage); named state retained for the surrounding calculation or subsequent calls.
        stage = temp / "wayfinder_pack"
        extracted.mkdir()
        stage.mkdir()
        try:
            # Variable(s): `zf` (ZIP archive handle); named state retained for the surrounding calculation or subsequent calls.
            with zipfile.ZipFile(source) as zf:
                _safe_extract(zf, extracted)
        except zipfile.BadZipFile as exc:
            raise ValueError("The selected source is not a valid ZIP tracker pack.") from exc

        # Variable(s): `root` (root); named state retained for the surrounding calculation or subsequent calls.
        root = _find_root(extracted)
        poptracker_variants = _extract_poptracker_variants(root, warnings) if source_format == "poptracker" else {}
        # Variable(s): `maps` (maps), `image_refs` (image refs); named state retained for the surrounding calculation or subsequent calls.
        maps, image_refs = _normalise_maps(root, warnings)
        (stage / "maps").mkdir(parents=True, exist_ok=True)
        (stage / "maps" / "maps.json").write_text(json.dumps(maps, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        # Variable(s): `location_files` (location files); named state retained for the surrounding calculation or subsequent calls.
        location_files = 0
        # PopTracker convention is locations/. UT-compatible packs may instead
        # (or additionally) use ut_locations/. Preserve both because WayFinder's
        # normaliser understands either representation.
        location_files += _copy_tree_json(root / "locations", stage / "locations", warnings, root)
        location_files += _copy_tree_json(root / "ut_locations", stage / "ut_locations", warnings, root)
        _copy_tree_json(root / "layouts", stage / "layouts", warnings, root)
        _copy_tree_json(root / "settings", stage / "settings", warnings, root)

        # Variable(s): `copied` (copied); named state retained for the surrounding calculation or subsequent calls.
        copied = _copy_assets(root, stage, image_refs, warnings)
        if poptracker_variants:
            for variant_uid, variant_info in poptracker_variants.items():
                if variant_info.get("overlay"):
                    copied += _copy_variant_overlay(root, variant_uid, stage, warnings)
            default_variant = "standard" if "standard" in poptracker_variants else next(iter(poptracker_variants))
            variant_metadata = {
                "format": "wayfinder.map-variants",
                "version": 1,
                "default": default_variant,
                "variants": list(poptracker_variants.values()),
            }
            (stage / "wayfinder_variants.json").write_text(
                json.dumps(variant_metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            copied += 1
            warnings.append(f"Detected {len(poptracker_variants)} PopTracker variant(s): " + ", ".join(v["display_name"] for v in poptracker_variants.values()))
        # Preserve an existing path->AP-location-ID mapping, then augment it
        # from PopTracker's Lua autotracking table.  The full hierarchical path
        # is what disambiguates repeated leaf labels such as "Yarn".
        location_id_mapping: dict[str, Any] = {}
        existing_id_file = root / "packbash_location_ids.json"
        if existing_id_file.is_file():
            try:
                existing_ids = _read_json(existing_id_file, warnings, root)
                if isinstance(existing_ids, dict):
                    location_id_mapping.update(existing_ids)
            except Exception as exc:
                warnings.append(f"Could not read existing location ID mapping: {exc}")
        if source_format == "poptracker":
            extracted_ids = _extract_poptracker_location_id_mapping(root, warnings)
            for hierarchy_path, location_ids in extracted_ids.items():
                location_id_mapping.setdefault(hierarchy_path, location_ids)
            entrance_completion_ids = _extract_poptracker_entrance_completion_ids(root, location_id_mapping, warnings)
            for hierarchy_path, location_ids in entrance_completion_ids.items():
                location_id_mapping.setdefault(hierarchy_path, location_ids)
        if location_id_mapping:
            (stage / "packbash_location_ids.json").write_text(
                json.dumps(location_id_mapping, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            copied += 1

        entrance_semantic_report = {}
        if source_format == "poptracker":
            entrance_semantic_report = _audit_poptracker_entrance_semantics(root, location_id_mapping, warnings)
            if entrance_semantic_report.get("entries"):
                (stage / "wayfinder_entrance_semantics.json").write_text(
                    json.dumps(entrance_semantic_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                copied += 1

        if location_files == 0:
            warnings.append("No locations/*.json or ut_locations/*.json files were found; the converted pack will contain maps but no check markers.")

        # Variable(s): `display` (display); named state retained for the surrounding calculation or subsequent calls.
        display = _display_name(root, source.stem, warnings)
        # Variable(s): `metadata` (metadata); named state retained for the surrounding calculation or subsequent calls.
        metadata = {
            "format": WAYFINDER_PACK_FORMAT,
            "format_version": WAYFINDER_PACK_VERSION,
            "name": display,
            "source_format": "PopTracker" if source_format == "poptracker" else "Universal Tracker",
            "source_archive": source.name,
            "maps": len(maps),
            "location_files": location_files,
            "variants": len(poptracker_variants),
            "entrance_semantics": (entrance_semantic_report.get("counts", {}) if source_format == "poptracker" else {}),
            "notes": "Converted by WayFinder. The original source archive is not modified.",
        }
        (stage / "wayfinder_pack.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        output.parent.mkdir(parents=True, exist_ok=True)
        # Variable(s): `tmp_zip` (tmp zip); named state retained for the surrounding calculation or subsequent calls.
        tmp_zip = output.with_name(output.name + ".tmp")
        tmp_zip.unlink(missing_ok=True)
        # Variable(s): `zf` (ZIP archive handle); named state retained for the surrounding calculation or subsequent calls.
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            # Loop variable(s): `path` (path); each iteration represents the next value from the iterable below.
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(stage).as_posix())
        tmp_zip.replace(output)

    return ConversionResult(output, source_format, display, len(maps), location_files, copied, tuple(warnings))


# /**
#  * Function: convert_poptracker_pack
#  * Purpose: Perform the convert poptracker pack operation while keeping the surrounding subsystem state consistent.
#  * @param source: Source supplied by the caller; see type hints and call sites for domain constraints.
#  * @param output: Output supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */


def detect_map_pack_archive_format(source: Path) -> str:
    """Classify an archive before installation.

    Returns ``wayfinder`` for archives already normalized by the WayFinder
    converter, ``poptracker`` for native PopTracker packs,
    ``universal_tracker`` for legacy/native tracker packs that expose
    ``maps/maps.json``, and ``unknown`` when no supported signature is found.

    Detection intentionally checks WayFinder's own metadata marker first. A raw
    PopTracker pack may itself contain ``maps/maps.json`` (including variant
    overlays), so the presence of that file alone does *not* prove conversion.
    """
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(source)
    try:
        with zipfile.ZipFile(source) as archive:
            names = [name.replace('\\', '/').lstrip('./') for name in archive.namelist()]
    except zipfile.BadZipFile as exc:
        raise ValueError('The selected source is not a valid ZIP tracker pack.') from exc

    lowered = [name.casefold() for name in names]
    if any(name == 'wayfinder_pack.json' or name.endswith('/wayfinder_pack.json') for name in lowered):
        return 'wayfinder'

    # PopTracker's manifest is the authoritative discriminator. Check it before
    # maps/maps.json because native PopTracker packs can contain that path too.
    if any(name == 'manifest.json' or name.endswith('/manifest.json') for name in lowered):
        return 'poptracker'

    if any(name == 'maps/maps.json' or name.endswith('/maps/maps.json') for name in lowered):
        return 'universal_tracker'

    return 'unknown'

def convert_poptracker_pack(source: Path, output: Path) -> ConversionResult:
    """Return convert poptracker pack."""
    return convert_map_pack(source, output, "poptracker")


# /**
#  * Function: convert_ut_pack
#  * Purpose: Perform the convert ut pack operation while keeping the surrounding subsystem state consistent.
#  * @param source: Source supplied by the caller; see type hints and call sites for domain constraints.
#  * @param output: Output supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def convert_ut_pack(source: Path, output: Path) -> ConversionResult:
    """Return convert ut pack."""
    return convert_map_pack(source, output, "universal_tracker")
