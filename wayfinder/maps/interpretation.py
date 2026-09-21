"""Shared tracker-pack interpretation primitives.

This module is intentionally UI- and converter-neutral.  Both the standalone
pack converter and WayFinder's live map-pack loader import these helpers, so a
the shared map-pack structural compatibility fix has one implementation and one
set of semantics.

Runtime state (reachability, checked state, discovered entrance assignments)
does not belong here; this layer only interprets pack structure and identity.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable

NORMALIZED_SCHEMA_NAME = "wayfinder.tracker-interpretation"
NORMALIZED_SCHEMA_VERSION = 1


def strip_json_comments(text: str) -> tuple[str, bool]:
    """Remove // and /* */ comments while preserving strings and line numbers."""
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
        if char == "/" and index + 1 < len(text) and text[index + 1] == "/":
            changed = True
            output.extend((" ", " "))
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                output.append(" ")
                index += 1
            continue
        if char == "/" and index + 1 < len(text) and text[index + 1] == "*":
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


def strip_trailing_commas(text: str) -> tuple[str, bool]:
    """Remove commas immediately before ] or }, outside quoted strings."""
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
        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "]}":
                output.append(" ")
                changed = True
                index += 1
                continue
        output.append(char)
        index += 1
    return "".join(output), changed


def loads_compatible_json(text: str) -> tuple[Any, tuple[str, ...]]:
    """Parse strict JSON, then the safe PopTracker extensions we support."""
    try:
        return json.loads(text), ()
    except json.JSONDecodeError as strict_error:
        uncommented, comments = strip_json_comments(text)
        compatible, trailing = strip_trailing_commas(uncommented)
        try:
            data = json.loads(compatible)
        except json.JSONDecodeError as compatibility_error:
            raise ValueError(
                f"Could not parse JSON: line {compatibility_error.lineno}, "
                f"column {compatibility_error.colno}. {compatibility_error.msg} "
                f"(strict JSON first failed at line {strict_error.lineno}, "
                f"column {strict_error.colno})."
            ) from compatibility_error
        features = tuple(
            name for enabled, name in (
                (comments, "comments"),
                (trailing, "trailing commas"),
            ) if enabled
        )
        return data, features


def read_compatible_json(
    path: Path,
    warnings: list[str] | None = None,
    root: Path | None = None,
) -> Any:
    """Read JSON using the shared WayFinder map-pack compatibility policy."""
    text = Path(path).read_text(encoding="utf-8-sig")
    try:
        data, features = loads_compatible_json(text)
    except ValueError as exc:
        try:
            display = Path(path).relative_to(root).as_posix() if root else Path(path).name
        except ValueError:
            display = Path(path).name
        raise ValueError(f"Could not parse {display}: {exc}") from exc
    if features and warnings is not None:
        try:
            display = Path(path).relative_to(root).as_posix() if root else Path(path).name
        except ValueError:
            display = Path(path).name
        warnings.append(
            f"{display}: accepted {' and '.join(features)} using shared tracker compatibility parsing."
        )
    return data


def normalize_location_ids(value: Any) -> tuple[int, ...]:
    """Normalize scalar/list decimal or hexadecimal AP IDs into unique integers."""
    if value is None:
        return ()
    values = value if isinstance(value, (list, tuple, set)) else (value,)
    result: list[int] = []
    for raw in values:
        try:
            number = int(raw, 0) if isinstance(raw, str) else int(raw)
        except (TypeError, ValueError):
            continue
        if number not in result:
            result.append(number)
    return tuple(result)


def extract_lua_location_id_mapping(
    root: Path,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Read direct and hosted-code PopTracker AP location mappings."""
    mapping: dict[str, list[int]] = {}
    indirect: list[tuple[int, str]] = []
    entry_double = re.compile(r'\[\s*((?:0[xX][0-9a-fA-F]+)|(?:\d+))\s*\]\s*=\s*(?:\{\s*)?"([^"]+)"')
    entry_single = re.compile(r"\[\s*((?:0[xX][0-9a-fA-F]+)|(?:\d+))\s*\]\s*=\s*(?:\{\s*)?'([^']+)'")
    for path in sorted(Path(root).glob("scripts/**/location_mapping.lua")):
        try:
            lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            code = line.split("--", 1)[0]
            match = entry_double.search(code) or entry_single.search(code)
            if not match:
                continue
            location_id = int(match.group(1), 0)
            target = match.group(2).strip()
            if target.startswith("@"):
                hierarchy = target[1:].strip().strip("/")
                if hierarchy:
                    mapping.setdefault(hierarchy, []).append(location_id)
            elif target:
                indirect.append((location_id, target))

    # Some PopTracker packs map an AP location ID to a hosted tracker code
    # (e.g. SS1) and archipelago.lua then mutates the actual @location. Resolve
    # that bridge so WayFinder can use the real AP ID and collected state.
    lua_chunks: list[str] = []
    function_pattern = re.compile(r"(?ms)^\s*function\s+\w+\s*\([^\n]*\).*?(?=^\s*function\s+\w+\s*\(|\Z)")
    for path in sorted(Path(root).glob("scripts/**/*.lua")):
        if path.name == "location_mapping.lua":
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        lua_chunks.extend(function_pattern.findall(text))
    ref_pattern = re.compile("[\"'](@[^\"']+)[\"']")
    resolved_indirect = 0
    for location_id, tracker_code in indirect:
        code_patterns = (f'"{tracker_code}"', f"'{tracker_code}'")
        candidates: list[str] = []
        for chunk in lua_chunks:
            if not any(token in chunk for token in code_patterns):
                continue
            for ref in ref_pattern.findall(chunk):
                hierarchy = ref[1:].strip().strip("/")
                if hierarchy and hierarchy not in candidates:
                    candidates.append(hierarchy)
        if len(candidates) == 1:
            mapping.setdefault(candidates[0], []).append(location_id)
            resolved_indirect += 1

    normalized: dict[str, Any] = {}
    for hierarchy, ids in mapping.items():
        unique = list(dict.fromkeys(ids))
        normalized[hierarchy] = unique[0] if len(unique) == 1 else unique
    if normalized and warnings is not None:
        warnings.append(
            f"Imported {sum(len(v) if isinstance(v, list) else 1 for v in normalized.values())} "
            f"tracker autotracking location ID mapping(s) across {len(normalized)} hierarchical path(s)."
        )
        if resolved_indirect:
            warnings.append(
                f"Resolved {resolved_indirect} hosted PopTracker location mapping(s) through Lua tracker-code bridges."
            )
    return normalized


def iter_marker_records(
    value: Any,
    id_mapping: dict[str, Any] | None = None,
    parents: tuple[str, ...] = (),
) -> Iterable[dict[str, Any]]:
    """Yield normalized marker records from arbitrarily nested supported location trees.

    The record format deliberately has no dependency on WayFinder's MapMarker
    class, allowing converters and renderers to consume exactly the same
    interpretation layer.
    """
    if isinstance(value, list):
        for child in value:
            yield from iter_marker_records(child, id_mapping, parents)
        return
    if not isinstance(value, dict):
        return

    mapping = id_mapping or {}
    fallback_name = str(value.get("name", "")).strip()
    node_path = parents + ((fallback_name,) if fallback_name else ())

    sections: list[dict[str, Any]] = []
    section_names: list[str] = []
    section_refs: list[str] = []
    section_tracker_only: list[bool] = []
    for section in value.get("sections", []) or []:
        if not isinstance(section, dict):
            continue
        name = str(section.get("name", "")).strip()
        ref = str(section.get("ref", "")).strip().strip("/")
        display = name or (ref.rsplit("/", 1)[-1] if ref else "")
        if not display and not ref:
            continue
        sections.append(section)
        section_names.append(display)
        section_refs.append(ref)
        # ``hosted_item`` sections are driven by a tracker code rather than a
        # direct @path entry in some PopTracker autotracking tables. The Lua
        # location-ID extractor resolves those codes back to their owning path
        # when possible; retain this flag only as a compatibility fallback.
        section_tracker_only.append(bool(str(section.get("hosted_item", "")).strip()))

    access_rules = [section.get("access_rules", []) for section in sections]
    section_ids: list[tuple[int, ...]] = []
    for name, ref in zip(section_names, section_refs):
        lookup = ref or "/".join(node_path + (name,))
        section_ids.append(normalize_location_ids(mapping.get(lookup)))

    node_visibility = tuple(value.get("visibility_rules", []) or [])
    for position in value.get("map_locations", []) or []:
        if not isinstance(position, dict):
            continue
        map_name = str(position.get("map", "")).strip()
        if not map_name:
            continue
        try:
            x, y = float(position.get("x")), float(position.get("y"))
        except (TypeError, ValueError):
            continue

        map_visibility: list[Any] = []
        for key in ("visibility_rules", "force_invisibility_rules", "restrict_visibility_rules"):
            rules = position.get(key, []) or []
            if isinstance(rules, list):
                map_visibility.extend({"kind": key, "rule": rule} for rule in rules)
            elif rules:
                map_visibility.append({"kind": key, "rule": rules})

        display_fallback = fallback_name or (parents[-1] if parents else "")
        if section_names:
            label = display_fallback or section_names[0]
            ids = tuple(section_ids)
        elif display_fallback:
            label = display_fallback
            ids = (normalize_location_ids(mapping.get("/".join(node_path))),)
        else:
            continue

        yield {
            "name": label,
            "map_name": map_name,
            "x": x,
            "y": y,
            "section_names": tuple(section_names),
            "location_ids": ids,
            "section_access_rules": tuple(access_rules),
            "section_refs": tuple(section_refs),
            "section_tracker_only": tuple(section_tracker_only),
            "visibility_rules": node_visibility,
            "map_visibility_rules": tuple(map_visibility),
            "source_path": "/".join(node_path),
        }

    yield from iter_marker_records(value.get("children", []), mapping, node_path)
