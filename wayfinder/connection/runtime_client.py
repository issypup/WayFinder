# /**
#  * Module: wayfinder.app/runtime_client.py
#  * Purpose: GUI module for runtime client; presents or coordinates WayFinder state without owning the underlying game logic.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

"""Socket transport used by the standalone visual GUI.

This module speaks the small JSON-lines protocol exposed by the WayFinder native runtime server. It translates transport dictionaries into typed
dataclasses, retries the local runtime connection when the native tracker runtime is
still starting, and keeps GUI-facing callbacks isolated from socket details.
"""

from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

import json
import uuid
from .identity import SnapshotGate, validate_snapshot
import os
import socket
import threading
import time
from .protocol import PROTOCOL_VERSION as IPC_PROTOCOL_VERSION, PROTOCOL_MIN as IPC_PROTOCOL_MIN, PROTOCOL_MAX as IPC_PROTOCOL_MAX, MAX_MESSAGE_BYTES as MAX_WIRE_MESSAGE_BYTES, CAPABILITIES, decode_snapshot, request_id
from dataclasses import dataclass, field, fields
from typing import Any, Callable

# Constant(s): `HEARTBEAT_INTERVAL`; shared configuration value(s) intentionally kept stable within this module.
HEARTBEAT_INTERVAL = 5.0
# Constant(s): `HEARTBEAT_TIMEOUT`; shared configuration value(s) intentionally kept stable within this module.
HEARTBEAT_TIMEOUT = 12.0


# ---------------------------------------------------------------------------
# Wire-format data models
# ---------------------------------------------------------------------------
# /**
#  * Class: InventoryEntry
#  * Purpose: Encapsulate the InventoryEntry responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class InventoryEntry:
    """Encapsulate InventoryEntry behaviour and the state needed to support it."""
    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
    name: str
    # Variable(s): `count` (count); named state retained for the surrounding calculation or subsequent calls.
    count: int
    # Variable(s): `progression` (progression); named state retained for the surrounding calculation or subsequent calls.
    progression: bool = False
    # Variable(s): `event` (event); named state retained for the surrounding calculation or subsequent calls.
    event: bool = False
    # Variable(s): `manual` (manual); named state retained for the surrounding calculation or subsequent calls.
    manual: bool = False
    # Variable(s): `source_player` (source player); named state retained for the surrounding calculation or subsequent calls.
    source_player: str = ""
    # Variable(s): `source_location` (source location); named state retained for the surrounding calculation or subsequent calls.
    source_location: str = ""


# /**
#  * Class: LocationEntry
#  * Purpose: Encapsulate the LocationEntry responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class LocationEntry:
    """Encapsulate LocationEntry behaviour and the state needed to support it."""
    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
    name: str
    # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
    status: str
    # Variable(s): `region` (region); named state retained for the surrounding calculation or subsequent calls.
    region: str = ""
    # Variable(s): `hinted` (hinted); named state retained for the surrounding calculation or subsequent calls.
    hinted: bool = False
    # Variable(s): `hint_status` (hint status); named state retained for the surrounding calculation or subsequent calls.
    hint_status: str = ""
    # Variable(s): `ignored` (ignored); named state retained for the surrounding calculation or subsequent calls.
    ignored: bool = False
    # Variable(s): `address` (address); named state retained for the surrounding calculation or subsequent calls.
    address: Any = None
    # Variable(s): `unknown_reason` (unknown reason); named state retained for the surrounding calculation or subsequent calls.
    unknown_reason: str = ""


# /**
#  * Class: Snapshot
#  * Purpose: Encapsulate the Snapshot responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class Snapshot:
    """Encapsulate Snapshot behaviour and the state needed to support it."""
    # Variable(s): `connected` (connected); named state retained for the surrounding calculation or subsequent calls.
    connected: bool = False
    # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
    game: str = ""
    # Variable(s): `slot_name` (slot name); named state retained for the surrounding calculation or subsequent calls.
    slot_name: str = ""
    # Variable(s): `server` (server); named state retained for the surrounding calculation or subsequent calls.
    server: str = ""
    # Variable(s): `starting_location` (starting location); named state retained for the surrounding calculation or subsequent calls.
    starting_location: str = ""
    # Variable(s): `starting_location_option` (starting location option); named state retained for the surrounding calculation or subsequent calls.
    starting_location_option: str = ""
    # Variable(s): `starting_location_raw` (starting location raw); named state retained for the surrounding calculation or subsequent calls.
    starting_location_raw: Any = None
    # Variable(s): `starting_location_source` (starting location source); named state retained for the surrounding calculation or subsequent calls.
    starting_location_source: str = ""
    # Variable(s): `inventory` (inventory); named state retained for the surrounding calculation or subsequent calls.
    inventory: list[InventoryEntry] = field(default_factory=list)
    # Variable(s): `locations` (locations); named state retained for the surrounding calculation or subsequent calls.
    locations: list[LocationEntry] = field(default_factory=list)
    # Variable(s): `in_logic_regions` (in logic regions); named state retained for the surrounding calculation or subsequent calls.
    in_logic_regions: list[str] = field(default_factory=list)
    # Variable(s): `events` (events); named state retained for the surrounding calculation or subsequent calls.
    events: list[str] = field(default_factory=list)
    # Variable(s): `event_locations` (event locations); named state retained for the surrounding calculation or subsequent calls.
    event_locations: list[str] = field(default_factory=list)
    # Variable(s): `manual_items` (manual items); named state retained for the surrounding calculation or subsequent calls.
    manual_items: list[str] = field(default_factory=list)
    # Variable(s): `checked_count` (checked count); named state retained for the surrounding calculation or subsequent calls.
    checked_count: int = 0
    # Variable(s): `missing_count` (missing count); named state retained for the surrounding calculation or subsequent calls.
    missing_count: int = 0
    # Variable(s): `hinted_count` (hinted count); named state retained for the surrounding calculation or subsequent calls.
    hinted_count: int = 0
    # Variable(s): `hints` (hints); named state retained for the surrounding calculation or subsequent calls.
    hints: list[dict[str, Any]] = field(default_factory=list)
    # Variable(s): `entrances` (entrances); named state retained for the surrounding calculation or subsequent calls.
    entrances: list[str] = field(default_factory=list)
    # Variable(s): `entrance_details` (entrance details); named state retained for the surrounding calculation or subsequent calls.
    entrance_details: list[dict[str, Any]] = field(default_factory=list)
    # True/False when the APWorld exposes entrance-randomization options; None when unknown.
    entrance_randomization_enabled: bool | None = None
    # Variable(s): `event_details` (event details); named state retained for the surrounding calculation or subsequent calls.
    event_details: list[dict[str, Any]] = field(default_factory=list)
    # Variable(s): `rule_details` (rule details); named state retained for the surrounding calculation or subsequent calls.
    rule_details: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Variable(s): `unsupported_state_calls` (unsupported state calls); named state retained for the surrounding calculation or subsequent calls.
    unsupported_state_calls: list[str] = field(default_factory=list)
    # Variable(s): `goal_detail` (goal detail); named state retained for the surrounding calculation or subsequent calls.
    goal_detail: dict[str, Any] = field(default_factory=dict)
    # Variable(s): `area_summary` (area summary); named state retained for the surrounding calculation or subsequent calls.
    area_summary: dict[str, dict[str, int]] = field(default_factory=dict)
    # Variable(s): `datastorage_index` (datastorage index); named state retained for the surrounding calculation or subsequent calls.
    datastorage_index: list[dict[str, Any]] = field(default_factory=list)
    # Variable(s): `item_name_groups` (item name groups); named state retained for the surrounding calculation or subsequent calls.
    item_name_groups: dict[str, list[str]] = field(default_factory=dict)
    # Variable(s): `location_name_groups` (location name groups); named state retained for the surrounding calculation or subsequent calls.
    location_name_groups: dict[str, list[str]] = field(default_factory=dict)
    # Variable(s): `engine_version` (engine version); named state retained for the surrounding calculation or subsequent calls.
    engine_version: str = "unknown"
    # Variable(s): `ap_version` (ap version); named state retained for the surrounding calculation or subsequent calls.
    ap_version: str = "unknown"
    # Variable(s): `go_mode` (go mode); named state retained for the surrounding calculation or subsequent calls.
    go_mode: str = "No"
    # Variable(s): `error` (error); named state retained for the surrounding calculation or subsequent calls.
    error: str = ""
    # Variable(s): `updated_at` (updated at); named state retained for the surrounding calculation or subsequent calls.
    updated_at: str = ""
    # Variable(s): `compatibility` (compatibility); named state retained for the surrounding calculation or subsequent calls.
    compatibility: dict[str, str] = field(default_factory=dict)
    # Variable(s): `snapshot_sequence` (snapshot sequence); named state retained for the surrounding calculation or subsequent calls.
    seed_identity: dict[str, Any] = field(default_factory=dict)
    connection_id: str = ""
    event_id: str = ""
    snapshot_sequence: int = 0
    # Variable(s): `runtime_id` (runtime id); named state retained for the surrounding calculation or subsequent calls.
    runtime_id: str = ""
    # Variable(s): `refresh_id` (refresh id); named state retained for the surrounding calculation or subsequent calls.
    refresh_id: int = 0
    # Variable(s): `team` (team); named state retained for the surrounding calculation or subsequent calls.
    team: int = 0
    # Variable(s): `data_package_signature` (data package signature); named state retained for the surrounding calculation or subsequent calls.
    data_package_signature: str = ""
    # Variable(s): `logic_api_version` (logic api version); named state retained for the surrounding calculation or subsequent calls.
    logic_api_version: int = 1
    # Variable(s): `logic_recalculation` (logic recalculation); named state retained for the surrounding calculation or subsequent calls.
    logic_recalculation: dict[str, Any] = field(default_factory=dict)
    # Variable(s): `reachability_available` (reachability available); named state retained for the surrounding calculation or subsequent calls.
    reachability_available: bool = True
    # Variable(s): `events_available` (events available); named state retained for the surrounding calculation or subsequent calls.
    events_available: bool = True
    # Variable(s): `logic_warnings` (logic warnings); named state retained for the surrounding calculation or subsequent calls.
    logic_warnings: list[str] = field(default_factory=list)
    # Variable(s): `event_sweep_error` (event sweep error); named state retained for the surrounding calculation or subsequent calls.
    event_sweep_error: str = ""
    # Variable(s): `unswept_events` (unswept events); named state retained for the surrounding calculation or subsequent calls.
    unswept_events: list[str] = field(default_factory=list)
    # Variable(s): `invalid_rule_results` (invalid rule results); named state retained for the surrounding calculation or subsequent calls.
    invalid_rule_results: list[str] = field(default_factory=list)
    # Variable(s): `event_alias_collisions` (event alias collisions); named state retained for the surrounding calculation or subsequent calls.
    event_alias_collisions: list[str] = field(default_factory=list)
    # Variable(s): `deferred_entrance_warnings` (deferred entrance warnings); named state retained for the surrounding calculation or subsequent calls.
    deferred_entrance_warnings: list[str] = field(default_factory=list)
    # Variable(s): `player_position_supported` (player position supported); named state retained for the surrounding calculation or subsequent calls.
    player_position_supported: bool = False
    # Variable(s): `player_position_available` (player position available); named state retained for the surrounding calculation or subsequent calls.
    player_position_available: bool = False
    # Variable(s): `player_position_setting_key` (player position setting key); named state retained for the surrounding calculation or subsequent calls.
    player_position_setting_key: str = ""
    # Variable(s): `raw_map_datastorage_value` (raw map datastorage value); named state retained for the surrounding calculation or subsequent calls.
    raw_map_datastorage_value: Any = None
    # Variable(s): `map_page_setting_key` (map page setting key); named state retained for the surrounding calculation or subsequent calls.
    map_page_setting_key: str = ""
    # Variable(s): `raw_map_page_datastorage_value` (raw map page datastorage value); named state retained for the surrounding calculation or subsequent calls.
    raw_map_page_datastorage_value: Any = None
    # Variable(s): `map_page_index` (map page index); named state retained for the surrounding calculation or subsequent calls.
    map_page_index: int = -1
    # Variable(s): `map_page_groups` (map page groups); named state retained for the surrounding calculation or subsequent calls.
    map_page_groups: list[Any] = field(default_factory=list)
    # Variable(s): `map_order` (map order); named state retained for the surrounding calculation or subsequent calls.
    map_order: list[str] = field(default_factory=list)
    # Variable(s): `hidden_map_locations` (hidden map locations); named state retained for the surrounding calculation or subsequent calls.
    hidden_map_locations: dict[str, list[str]] = field(default_factory=dict)
    # Variable(s): `hidden_map_entrances` (hidden map entrances); named state retained for the surrounding calculation or subsequent calls.
    hidden_map_entrances: dict[str, list[str]] = field(default_factory=dict)
    # Variable(s): `hidden_map_events` (hidden map events); named state retained for the surrounding calculation or subsequent calls.
    hidden_map_events: dict[str, list[str]] = field(default_factory=dict)
    # Variable(s): `location_aliases` (location aliases); named state retained for the surrounding calculation or subsequent calls.
    location_aliases: dict[str, str] = field(default_factory=dict)
    # Variable(s): `poptracker_name_mapping` (poptracker name mapping); named state retained for the surrounding calculation or subsequent calls.
    poptracker_name_mapping: dict[str, Any] = field(default_factory=dict)
    # Variable(s): `player_position_map_index` (player position map index); named state retained for the surrounding calculation or subsequent calls.
    player_position_map_index: int = -1
    # Variable(s): `player_position_icons` (player position icons); named state retained for the surrounding calculation or subsequent calls.
    player_position_icons: list[dict[str, Any]] = field(default_factory=list)
    # Variable(s): `player_position_label` (player position label); named state retained for the surrounding calculation or subsequent calls.
    player_position_label: str = ""
    # Variable(s): `state_origin` (state origin); named state retained for the surrounding calculation or subsequent calls.
    state_origin: str = "live"
    # Variable(s): `stale` (stale); named state retained for the surrounding calculation or subsequent calls.
    stale: bool = False
    # Variable(s): `stale_reason` (stale reason); named state retained for the surrounding calculation or subsequent calls.
    stale_reason: str = ""
    # Variable(s): `last_logic_success_epoch` (last logic success epoch); named state retained for the surrounding calculation or subsequent calls.
    last_logic_success_epoch: float = 0.0
    # Variable(s): `previous_reachable_regions` (previous reachable regions); named state retained for the surrounding calculation or subsequent calls.
    previous_reachable_regions: list[str] = field(default_factory=list)
    # Variable(s): `current_reachable_regions` (current reachable regions); named state retained for the surrounding calculation or subsequent calls.
    current_reachable_regions: list[str] = field(default_factory=list)
    # Variable(s): `previous_reachable_locations` (previous reachable locations); named state retained for the surrounding calculation or subsequent calls.
    previous_reachable_locations: list[str] = field(default_factory=list)
    # Variable(s): `current_reachable_locations` (current reachable locations); named state retained for the surrounding calculation or subsequent calls.
    current_reachable_locations: list[str] = field(default_factory=list)
    # Variable(s): `previous_events` (previous events); named state retained for the surrounding calculation or subsequent calls.
    previous_events: list[str] = field(default_factory=list)
    # Variable(s): `current_events` (current events); named state retained for the surrounding calculation or subsequent calls.
    current_events: list[str] = field(default_factory=list)
    # Variable(s): `logic_change` (logic change); named state retained for the surrounding calculation or subsequent calls.
    logic_change: dict[str, Any] = field(default_factory=dict)
    # Variable(s): `logic_state_fingerprint` (logic state fingerprint); named state retained for the surrounding calculation or subsequent calls.
    logic_state_fingerprint: str = ""
    # Variable(s): `calculation_timings_ms` (calculation timings ms); named state retained for the surrounding calculation or subsequent calls.
    calculation_timings_ms: dict[str, float] = field(default_factory=dict)
    # Variable(s): `normal_reachable_locations` (normal reachable locations); named state retained for the surrounding calculation or subsequent calls.
    normal_reachable_locations: list[str] = field(default_factory=list)
    # Variable(s): `glitch_reachable_locations` (glitch reachable locations); named state retained for the surrounding calculation or subsequent calls.
    glitch_reachable_locations: list[str] = field(default_factory=list)
    
    # /**
    #  * Function: reachable
    #  * Purpose: Perform the reachable operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    @property
    def reachable(self) -> list[LocationEntry]:
        """Handle reachable as part of the WayFinder workflow."""
        return [x for x in self.locations if x.status == "reachable"]

    # /**
    #  * Function: glitched
    #  * Purpose: Perform the glitched operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    @property
    def glitched(self) -> list[LocationEntry]:
        """Handle glitched as part of the WayFinder workflow."""
        return [x for x in self.locations if x.status == "glitched"]

    # /**
    #  * Function: ignored
    #  * Purpose: Perform the ignored operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    @property
    def ignored(self) -> list[LocationEntry]:
        """Handle ignored as part of the WayFinder workflow."""
        return [x for x in self.locations if x.ignored]


# /**
#  * Class: RuleNode
#  * Purpose: Encapsulate the RuleNode responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class RuleNode:
    """Encapsulate RuleNode behaviour and the state needed to support it."""
    # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
    kind: str
    # Variable(s): `label` (label); named state retained for the surrounding calculation or subsequent calls.
    label: str
    # Variable(s): `satisfied` (satisfied); named state retained for the surrounding calculation or subsequent calls.
    satisfied: bool | None = None
    # Variable(s): `detail` (detail); named state retained for the surrounding calculation or subsequent calls.
    detail: str = ""
    have: int | None = None
    required: int | None = None
    operator: str | None = None
    # Variable(s): `children` (children); named state retained for the surrounding calculation or subsequent calls.
    children: list["RuleNode"] = field(default_factory=list)


# /**
#  * Class: PathStep
#  * Purpose: Encapsulate the PathStep responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class PathStep:
    """Encapsulate PathStep behaviour and the state needed to support it."""
    # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
    kind: str
    # Variable(s): `title` (title); named state retained for the surrounding calculation or subsequent calls.
    title: str
    # Variable(s): `tokens` (tokens); named state retained for the surrounding calculation or subsequent calls.
    tokens: list[dict[str, Any]] = field(default_factory=list)
    # Variable(s): `reachable` (reachable); named state retained for the surrounding calculation or subsequent calls.
    reachable: bool | None = None
    # Variable(s): `tree` (tree); named state retained for the surrounding calculation or subsequent calls.
    tree: RuleNode | None = None
    # Variable(s): `source_region` (source region); named state retained for the surrounding calculation or subsequent calls.
    source_region: str = ""
    # Variable(s): `target_region` (target region); named state retained for the surrounding calculation or subsequent calls.
    target_region: str = ""


# /**
#  * Class: PathResult
#  * Purpose: Encapsulate the PathResult responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class PathResult:
    """Encapsulate PathResult behaviour and the state needed to support it."""
    # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
    target: str
    # Variable(s): `found` (found); named state retained for the surrounding calculation or subsequent calls.
    found: bool
    # Variable(s): `reachable` (reachable); named state retained for the surrounding calculation or subsequent calls.
    reachable: bool = False
    # Variable(s): `using_glitches` (using glitches); named state retained for the surrounding calculation or subsequent calls.
    using_glitches: bool = False
    # Variable(s): `steps` (steps); named state retained for the surrounding calculation or subsequent calls.
    steps: list[PathStep] = field(default_factory=list)
    # Variable(s): `error` (error); named state retained for the surrounding calculation or subsequent calls.
    error: str = ""
    # Variable(s): `updated_at` (updated at); named state retained for the surrounding calculation or subsequent calls.
    updated_at: str = ""
    # Variable(s): `compatibility` (compatibility); named state retained for the surrounding calculation or subsequent calls.
    compatibility: dict[str, str] = field(default_factory=dict)


# /**
#  * Function: _rule_from_dict
#  * Purpose: Perform the rule from dict operation while keeping the surrounding subsystem state consistent.
#  * @param data: Data supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _rule_from_dict(data: Any) -> RuleNode | None:
    """Recursively convert a serialized rule tree into ``RuleNode`` objects."""
    if not isinstance(data, dict):
        return None
    return RuleNode(
        kind=str(data.get("kind", "rule")),
        label=str(data.get("label", "")),
        satisfied=data.get("satisfied"),
        detail=str(data.get("detail", "")),
        have=data.get("have"), required=data.get("required"), operator=data.get("operator"),
        children=[x for x in (_rule_from_dict(v) for v in data.get("children", [])) if x is not None],
    )


# /**
#  * Function: _known_kwargs
#  * Purpose: Perform the known kwargs operation while keeping the surrounding subsystem state consistent.
#  * @param data: Data supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _known_kwargs(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """Return only dataclass fields understood by this GUI version."""
    # Variable(s): `allowed` (allowed); named state retained for the surrounding calculation or subsequent calls.
    allowed = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in allowed}


# /**
#  * Function: _path_from_dict
#  * Purpose: Perform the path from dict operation while keeping the surrounding subsystem state consistent.
#  * @param data: Data supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _path_from_dict(data: dict[str, Any]) -> PathResult:
    """Convert a serialized path-analysis result into typed path/step objects."""
    # Variable(s): `steps` (steps); named state retained for the surrounding calculation or subsequent calls.
    steps: list[PathStep] = []
    # Variable(s): `raw_steps` (raw steps); named state retained for the surrounding calculation or subsequent calls.
    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        # Variable(s): `raw_steps` (raw steps); named state retained for the surrounding calculation or subsequent calls.
        raw_steps = []
    # Loop variable(s): `raw` (raw value); each iteration represents the next value from the iterable below.
    for raw in raw_steps:
        if not isinstance(raw, dict):
            continue
        # Variable(s): `tokens` (tokens); named state retained for the surrounding calculation or subsequent calls.
        tokens = raw.get("tokens", [])
        steps.append(PathStep(
            kind=str(raw.get("kind", "")),
            title=str(raw.get("title", "")),
            tokens=list(tokens) if isinstance(tokens, list) else [],
            reachable=raw.get("reachable"),
            tree=_rule_from_dict(raw.get("tree")),
            source_region=str(raw.get("source_region", "")),
            target_region=str(raw.get("target_region", "")),
        ))
    # Variable(s): `compat` (compat); named state retained for the surrounding calculation or subsequent calls.
    compat = data.get("compatibility", {})
    return PathResult(
        target=str(data.get("target", "")),
        found=bool(data.get("found", False)),
        reachable=bool(data.get("reachable", False)),
        using_glitches=bool(data.get("using_glitches", False)),
        steps=steps,
        error=str(data.get("error", "")),
        updated_at=str(data.get("updated_at", "")),
        compatibility=dict(compat) if isinstance(compat, dict) else {},
    )


# /**
#  * Function: _snapshot_from_dict
#  * Purpose: Perform the snapshot from dict operation while keeping the surrounding subsystem state consistent.
#  * @param data: Data supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _snapshot_from_dict(data: dict[str, Any]) -> Snapshot:
    """Convert a protocol snapshot dictionary into typed GUI-facing dataclasses."""
    # Variable(s): `raw_inv` (raw inv); named state retained for the surrounding calculation or subsequent calls.
    raw_inv = data.get("inventory", [])
    # Variable(s): `raw_locs` (raw locs); named state retained for the surrounding calculation or subsequent calls.
    raw_locs = data.get("locations", [])
    # Variable(s): `raw_inv` (raw inv); named state retained for the surrounding calculation or subsequent calls.
    if not isinstance(raw_inv, list): raw_inv = []
    # Variable(s): `raw_locs` (raw locs); named state retained for the surrounding calculation or subsequent calls.
    if not isinstance(raw_locs, list): raw_locs = []
    # Variable(s): `inv` (inventory); named state retained for the surrounding calculation or subsequent calls.
    inv = [InventoryEntry(**_known_kwargs(InventoryEntry, x)) for x in raw_inv if isinstance(x, dict) and isinstance(x.get("name"), str)]
    # Variable(s): `locs` (locs); named state retained for the surrounding calculation or subsequent calls.
    locs = [LocationEntry(**_known_kwargs(LocationEntry, x)) for x in raw_locs if isinstance(x, dict) and isinstance(x.get("name"), str) and isinstance(x.get("status"), str)]
    return Snapshot(
        connected=bool(data.get("connected", False)),
        game=str(data.get("game", "")),
        slot_name=str(data.get("slot_name", "")),
        server=str(data.get("server", "")),
        starting_location=str(data.get("starting_location", "") or ""),
        starting_location_option=str(data.get("starting_location_option", "") or ""),
        starting_location_raw=data.get("starting_location_raw"),
        starting_location_source=str(data.get("starting_location_source", "") or ""),
        inventory=inv,
        locations=locs,
        in_logic_regions=list(data.get("in_logic_regions", [])) if isinstance(data.get("in_logic_regions", []), list) else [],
        events=list(data.get("events", [])) if isinstance(data.get("events", []), list) else [],
        event_locations=list(data.get("event_locations", [])) if isinstance(data.get("event_locations", []), list) else [],
        manual_items=list(data.get("manual_items", [])) if isinstance(data.get("manual_items", []), list) else [],
        checked_count=int(data.get("checked_count", 0) or 0),
        missing_count=int(data.get("missing_count", 0) or 0),
        hinted_count=int(data.get("hinted_count", 0) or 0),
        hints=list(data.get("hints", [])) if isinstance(data.get("hints", []), list) else [],
        entrances=list(data.get("entrances", [])) if isinstance(data.get("entrances", []), list) else [],
        entrance_details=list(data.get("entrance_details", [])) if isinstance(data.get("entrance_details", []), list) else [],
        entrance_randomization_enabled=(None if data.get("entrance_randomization_enabled", None) is None else bool(data.get("entrance_randomization_enabled"))),
        event_details=list(data.get("event_details", [])) if isinstance(data.get("event_details", []), list) else [],
        rule_details=dict(data.get("rule_details", {})) if isinstance(data.get("rule_details", {}), dict) else {},
        unsupported_state_calls=list(data.get("unsupported_state_calls", [])) if isinstance(data.get("unsupported_state_calls", []), list) else [],
        goal_detail=dict(data.get("goal_detail", {})) if isinstance(data.get("goal_detail", {}), dict) else {},
        area_summary=dict(data.get("area_summary", {})) if isinstance(data.get("area_summary", {}), dict) else {},
        datastorage_index=list(data.get("datastorage_index", [])) if isinstance(data.get("datastorage_index", []), list) else [],
        item_name_groups=dict(data.get("item_name_groups", {})) if isinstance(data.get("item_name_groups", {}), dict) else {},
        location_name_groups=dict(data.get("location_name_groups", {})) if isinstance(data.get("location_name_groups", {}), dict) else {},
        engine_version=str(data.get("engine_version", "unknown")),
        ap_version=str(data.get("ap_version", "unknown")),
        go_mode=str(data.get("go_mode", "No")),
        error=str(data.get("error", "")),
        updated_at=str(data.get("updated_at", "")),
        compatibility=dict(data.get("compatibility", {})) if isinstance(data.get("compatibility", {}), dict) else {},
        seed_identity=dict(data.get("seed_identity",{}) or {}),
        connection_id=str(data.get("connection_id","") or ""),
        event_id=str(data.get("event_id","") or ""),
        snapshot_sequence=int(data.get("snapshot_sequence", 0) or 0),
        runtime_id=str(data.get("runtime_id", "") or ""),
        refresh_id=int(data.get("refresh_id", 0) or 0),
        team=int(data.get("team", 0) or 0),
        data_package_signature=str(data.get("data_package_signature", "") or ""),
        logic_api_version=int(data.get("logic_api_version", 1) or 1),
        logic_recalculation=dict(data.get("logic_recalculation", {})) if isinstance(data.get("logic_recalculation", {}), dict) else {},
        reachability_available=bool(data.get("reachability_available", True)),
        events_available=bool(data.get("events_available", True)),
        logic_warnings=list(data.get("logic_warnings", [])) if isinstance(data.get("logic_warnings", []), list) else [],
        event_sweep_error=str(data.get("event_sweep_error", "") or ""),
        unswept_events=list(data.get("unswept_events", [])) if isinstance(data.get("unswept_events", []), list) else [],
        invalid_rule_results=list(data.get("invalid_rule_results", [])) if isinstance(data.get("invalid_rule_results", []), list) else [],
        event_alias_collisions=list(data.get("event_alias_collisions", [])) if isinstance(data.get("event_alias_collisions", []), list) else [],
        deferred_entrance_warnings=list(data.get("deferred_entrance_warnings", [])) if isinstance(data.get("deferred_entrance_warnings", []), list) else [],
        player_position_supported=bool(data.get("player_position_supported", False)),
        player_position_available=bool(data.get("player_position_available", False)),
        player_position_setting_key=str(data.get("player_position_setting_key", "") or ""),
        raw_map_datastorage_value=data.get("raw_map_datastorage_value"),
        map_page_setting_key=str(data.get("map_page_setting_key", "") or ""),
        raw_map_page_datastorage_value=data.get("raw_map_page_datastorage_value"),
        map_page_index=int(data.get("map_page_index", -1) if data.get("map_page_index", -1) is not None else -1),
        map_page_groups=list(data.get("map_page_groups", [])) if isinstance(data.get("map_page_groups", []), list) else [],
        map_order=list(data.get("map_order", [])) if isinstance(data.get("map_order", []), list) else [],
        hidden_map_locations=dict(data.get("hidden_map_locations", {})) if isinstance(data.get("hidden_map_locations", {}), dict) else {},
        hidden_map_entrances=dict(data.get("hidden_map_entrances", {})) if isinstance(data.get("hidden_map_entrances", {}), dict) else {},
        hidden_map_events=dict(data.get("hidden_map_events", {})) if isinstance(data.get("hidden_map_events", {}), dict) else {},
        location_aliases=dict(data.get("location_aliases", {})) if isinstance(data.get("location_aliases", {}), dict) else {},
        poptracker_name_mapping=dict(data.get("poptracker_name_mapping", {})) if isinstance(data.get("poptracker_name_mapping", {}), dict) else {},
        player_position_map_index=int(data.get("player_position_map_index", -1) if data.get("player_position_map_index", -1) is not None else -1),
        player_position_icons=list(data.get("player_position_icons", [])) if isinstance(data.get("player_position_icons", []), list) else [],
        player_position_label=str(data.get("player_position_label", "") or ""),
        previous_reachable_regions=list(data.get("previous_reachable_regions", [])) if isinstance(data.get("previous_reachable_regions", []), list) else [],
        current_reachable_regions=list(data.get("current_reachable_regions", [])) if isinstance(data.get("current_reachable_regions", []), list) else [],
        previous_reachable_locations=list(data.get("previous_reachable_locations", [])) if isinstance(data.get("previous_reachable_locations", []), list) else [],
        current_reachable_locations=list(data.get("current_reachable_locations", [])) if isinstance(data.get("current_reachable_locations", []), list) else [],
        previous_events=list(data.get("previous_events", [])) if isinstance(data.get("previous_events", []), list) else [],
        current_events=list(data.get("current_events", [])) if isinstance(data.get("current_events", []), list) else [],
        logic_change=dict(data.get("logic_change", {})) if isinstance(data.get("logic_change", {}), dict) else {},
        logic_state_fingerprint=str(data.get("logic_state_fingerprint", "") or ""),
        calculation_timings_ms=dict(data.get("calculation_timings_ms", {})) if isinstance(data.get("calculation_timings_ms", {}), dict) else {},
        normal_reachable_locations=list(data.get("normal_reachable_locations", [])) if isinstance(data.get("normal_reachable_locations", []), list) else [],
        glitch_reachable_locations=list(data.get("glitch_reachable_locations", [])) if isinstance(data.get("glitch_reachable_locations", []), list) else [],
    )


# ---------------------------------------------------------------------------
# Local socket transport
# ---------------------------------------------------------------------------
# /**
#  * Class: WayFinderRuntimeClient
#  * Purpose: Encapsulate the WayFinderRuntimeClient responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
class WayFinderRuntimeClient:
    """Local adapter between the WayFinder GUI and WayFinder native runtime.

    The WayFinder application owns both sides. Structured JSON over localhost keeps
    the Tk GUI isolated from the native asyncio runtime.
    """

    # Variable(s): `_hello_lock` (hello lock); named state retained for the surrounding calculation or subsequent calls.
    _hello_lock = threading.Lock()
    # Variable(s): `_hello_info` (hello info); named state retained for the surrounding calculation or subsequent calls.
    _hello_info: tuple[bool, str, dict[str, str]] = (
        True,
        "WayFinder native runtime is not started",
        {"Runtime transport": "Idle until Connect is requested"},
    )

    # /**
    #  * Function: __init__
    #  * Purpose: Initialize this object and establish its required runtime state.
    #  * @param snapshot_sink: Snapshot sink supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param log_sink: Log sink supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param status_sink: Status sink supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def __init__(self, snapshot_sink: Callable[[Snapshot], None], log_sink: Callable[[str], None], status_sink: Callable[[str, Any], None] | None = None):
        """Initialize instance state and wire the collaborators/resources required by this component."""
        self.snapshot_sink = snapshot_sink
        self._seed_gate=SnapshotGate()
        self._last_connection=None
        self.log_sink = log_sink
        self.status_sink = status_sink or (lambda _name, _value: None)
        self.host = os.environ.get("WF_RUNTIME_HOST", "127.0.0.1")
        self.port = int(os.environ.get("WF_RUNTIME_PORT", "0") or 0)
        self.sock: socket.socket | None = None
        self.reader_thread: threading.Thread | None = None
        self.connect_thread: threading.Thread | None = None
        self.send_lock = threading.Lock()
        self.callbacks: dict[int, tuple[Callable[[PathResult], None], threading.Timer]] = {}
        self.datastorage_callbacks: dict[int, tuple[Callable[[dict[str, Any]], None], threading.Timer]] = {}
        self.next_id = 1
        self.closed = False
        self._connecting = False
        self._pending: list[dict[str, Any]] = []
        self._pending_limit = 64
        self._ever_connected = False
        self._transport_epoch = 0
        self._next_refresh_id = 1
        self._transport_lock = threading.RLock()
        self._session_id = ""
        self._protocol_compatible = False
        self._last_rx = time.monotonic()
        self._last_snapshot_fingerprint = ""
        self._connection_attempts = 0
        self._disconnect_reason = ""
        self._capability_last_ok: dict[str, float] = {}
        self._negotiated_capabilities: set[str] = set()
        self.heartbeat_thread: threading.Thread | None = None
        # Deliberately do NOT connect to the local runtime during GUI startup.
        # The runtime process and IPC retry loop are both user-initiated and begin
        # only when the Connect button causes a command to be sent.
        if not self.port:
            self.log_sink("Runtime IPC port was not supplied by the WayFinder application.")

    # /**
    #  * Function: installation_info
    #  * Purpose: Perform the installation info operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    @staticmethod
    def installation_info() -> tuple[bool, str, dict[str, str]]:
        """Return a small diagnostic description of this runtime transport/runtime."""
        with WayFinderRuntimeClient._hello_lock:
            return WayFinderRuntimeClient._hello_info

    # /**
    #  * Function: check_installation
    #  * Purpose: Perform the check installation operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    @staticmethod
    def check_installation() -> tuple[bool, str]:
        """Validate that the local live runtime transport can be used by the visual GUI."""
        # Variable(s): `ok` (ok), `msg` (message), `_` (_); named state retained for the surrounding calculation or subsequent calls.
        ok, msg, _ = WayFinderRuntimeClient.installation_info()
        return ok, msg

    # /**
    #  * Function: _start_transport_retry
    #  * Purpose: Perform the start transport retry operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _start_transport_retry(self) -> None:
        """Start one serialized retry worker for the injected tracker server."""
        with self._transport_lock:
            if self._connecting or self.closed:
                return
            self._connecting = True
            # Variable(s): `thread` (thread); named state retained for the surrounding calculation or subsequent calls.
            thread = threading.Thread(target=self._transport_retry_loop, name="WayFinder-Native-Connect", daemon=True)
            self.connect_thread = thread
        thread.start()

    # /**
    #  * Function: _transport_retry_loop
    #  * Purpose: Perform the transport retry loop operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _transport_retry_loop(self) -> None:
        # Archipelago can take a while to load a large custom_worlds set.  Older
        # builds gave up after 12 seconds and never retried, which made a healthy
        # runtime transport look permanently dead if startup happened to be slow.
        """Repeatedly attempt the local socket connection until connected or closed."""
        # Variable(s): `attempt` (attempt); named state retained for the surrounding calculation or subsequent calls.
        attempt = 0
        # Variable(s): `last_error` (last error); named state retained for the surrounding calculation or subsequent calls.
        last_error: Exception | None = None
        try:
            while not self.closed and self.sock is None:
                attempt += 1
                self._connection_attempts += 1
                self.status_sink("runtime_connection_attempts", self._connection_attempts)
                try:
                    # Variable(s): `s` (s); named state retained for the surrounding calculation or subsequent calls.
                    s = socket.create_connection((self.host, self.port), timeout=1.0)
                    s.settimeout(1.0)
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    with self._transport_lock:
                        if self.closed:
                            s.close()
                            return
                        self.sock = s
                        self._ever_connected = True
                        self._transport_epoch += 1
                        # Variable(s): `epoch` (epoch); named state retained for the surrounding calculation or subsequent calls.
                        epoch = self._transport_epoch
                        self._session_id = ""
                        self._protocol_compatible = False
                        self._last_rx = time.monotonic()
                        self._last_snapshot_fingerprint = ""
                    self.reader_thread = threading.Thread(target=self._reader, args=(epoch, s), name="WayFinder-Native-IPC", daemon=True)
                    self.reader_thread.start()
                    self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, args=(epoch,), name="WayFinder-Native-Heartbeat", daemon=True)
                    self.heartbeat_thread.start()
                    self.log_sink(f"Connected to WayFinder runtime on {self.host}:{self.port}; awaiting protocol handshake.")
                    self.status_sink("runtime_transport", "handshaking")
                    return
                except OSError as exc:
                    # Variable(s): `last_error` (last error); named state retained for the surrounding calculation or subsequent calls.
                    last_error = exc
                    if attempt == 1:
                        self.log_sink("Waiting for WayFinder native runtime to finish starting…")
                    elif attempt % 25 == 0:
                        self.log_sink(f"Still waiting for WayFinder runtime ({attempt} attempts; last error: {exc!r}).")
                    self.status_sink("runtime_transport", "starting")
                    time.sleep(0.4)
            if not self.closed and self.sock is None and last_error is not None:
                self.log_sink(f"Could not connect to the WayFinder runtime: {last_error!r}")
        finally:
            with self._transport_lock:
                self._connecting = False

    # /**
    #  * Function: _flush_pending
    #  * Purpose: Perform the flush pending operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _flush_pending(self) -> None:
        """Send only startup-era commands; reconnects deliberately drop stale work."""
        if not self.sock or self.closed:
            return
        with self.send_lock:
            # Variable(s): `pending` (pending); named state retained for the surrounding calculation or subsequent calls.
            pending = self._pending[:]
            self._pending.clear()
            # Loop variable(s): `payload` (payload); each iteration represents the next value from the iterable below.
            for payload in pending:
                if self.closed:
                    break
                # Variable(s): `wire` (wire); named state retained for the surrounding calculation or subsequent calls.
                wire = dict(payload)
                wire["protocol_version"] = IPC_PROTOCOL_VERSION
                wire["session_id"] = self._session_id
                wire.setdefault("request_id", request_id(wire.get("id") or wire.get("refresh_id")))
                # Variable(s): `blob` (blob); named state retained for the surrounding calculation or subsequent calls.
                blob = (json.dumps(wire, separators=(",", ":")) + "\n").encode("utf-8")
                try:
                    self.sock.sendall(blob)
                except OSError as exc:
                    self.log_sink(f"Runtime send failed while flushing queued command: {exc!r}")
                    break

    # /**
    #  * Function: _queue_startup_command
    #  * Purpose: Perform the queue startup command operation while keeping the surrounding subsystem state consistent.
    #  * @param payload: Payload supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _queue_startup_command(self, payload: dict[str, Any]) -> None:
        """Bound and deduplicate commands queued before the first runtime connection."""
        # Variable(s): `cmd` (command); named state retained for the surrounding calculation or subsequent calls.
        cmd = str(payload.get("cmd", ""))
        if cmd == "refresh":
            self._pending = [x for x in self._pending if x.get("cmd") != "refresh"]
        if len(self._pending) >= self._pending_limit:
            # Variable(s): `dropped` (dropped); named state retained for the surrounding calculation or subsequent calls.
            dropped = self._pending.pop(0)
            self.log_sink(f"Runtime pending queue full; dropped oldest {dropped.get('cmd', 'command')}.")
        self._pending.append(dict(payload))

    # /**
    #  * Function: _send
    #  * Purpose: Perform the send operation while keeping the surrounding subsystem state consistent.
    #  * @param payload: Payload supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _send(self, payload: dict[str, Any]) -> bool:
        """Serialize one protocol message; never replay failed post-connect actions."""
        if self.closed and payload.get("cmd") != "shutdown":
            return False
        # Variable(s): `cmd` (command); named state retained for the surrounding calculation or subsequent calls.
        cmd = str(payload.get("cmd", ""))
        with self._transport_lock:
            # Variable(s): `sock` (sock); named state retained for the surrounding calculation or subsequent calls.
            sock = self.sock
            # Variable(s): `compatible` (compatible); named state retained for the surrounding calculation or subsequent calls.
            compatible = self._protocol_compatible
            # Variable(s): `session_id` (session id); named state retained for the surrounding calculation or subsequent calls.
            session_id = self._session_id
        if not sock or (cmd not in {"shutdown", "ping"} and not compatible):
            # Before the first successful IPC connection, only an explicit
            # Archipelago Connect request is allowed to wake the transport.
            # Disconnect/refresh/path/etc. must remain true no-ops while the app
            # is in its setup-ready, user-not-yet-connected state.
            if cmd != "shutdown" and not self._ever_connected and cmd == "connect":
                with self.send_lock:
                    self._queue_startup_command(payload)
                self.log_sink("Runtime is still starting; queued connect.")
                self._start_transport_retry()
            elif cmd != "shutdown" and compatible is False and sock is not None:
                self.log_sink(f"Runtime handshake not accepted; dropped {cmd or 'command'}.")
            elif cmd != "shutdown":
                # Variable(s): `why` (why); named state retained for the surrounding calculation or subsequent calls.
                why = "not started" if not self._ever_connected else "reconnecting"
                self.log_sink(f"Runtime {why}; dropped {cmd or 'command'} instead of replaying stale work later.")
            return False
        # Variable(s): `wire` (wire); named state retained for the surrounding calculation or subsequent calls.
        wire = dict(payload)
        wire["protocol_version"] = IPC_PROTOCOL_VERSION
        wire["session_id"] = session_id
        wire.setdefault("request_id", request_id(wire.get("id") or wire.get("refresh_id")))
        # Variable(s): `blob` (blob); named state retained for the surrounding calculation or subsequent calls.
        blob = (json.dumps(wire, separators=(",", ":")) + "\n").encode("utf-8")
        if len(blob) > MAX_WIRE_MESSAGE_BYTES:
            self.log_sink(f"Runtime command {cmd or 'message'} exceeded the {MAX_WIRE_MESSAGE_BYTES} byte IPC limit and was dropped.")
            return False
        try:
            with self.send_lock:
                with self._transport_lock:
                    if self.sock is not sock:
                        return False
                sock.sendall(blob)
            return True
        except OSError as exc:
            self.log_sink(f"Runtime send failed: {exc!r}")
            self._drop_transport(sock, "send failure")
            return False

    # /**
    #  * Function: _drop_transport
    #  * Purpose: Perform the drop transport operation while keeping the surrounding subsystem state consistent.
    #  * @param sock: Sock supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param reason: Reason supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param reconnect: Reconnect supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _drop_transport(self, sock: socket.socket | None, reason: str, *, reconnect: bool = True) -> None:
        """Atomically retire one socket without disturbing a newer reconnect."""
        # Variable(s): `should_reconnect` (should reconnect); named state retained for the surrounding calculation or subsequent calls.
        should_reconnect = False
        with self._transport_lock:
            if sock is not None and self.sock is not sock:
                return
            # Variable(s): `old` (old); named state retained for the surrounding calculation or subsequent calls.
            old = self.sock
            self.sock = None
            self._session_id = ""
            self._protocol_compatible = False
            self._last_snapshot_fingerprint = ""
            self._disconnect_reason = reason
            self.status_sink("runtime_disconnect_reason", reason)
            # Variable(s): `should_reconnect` (should reconnect); named state retained for the surrounding calculation or subsequent calls.
            should_reconnect = reconnect and not self.closed
        if old is not None:
            try: old.shutdown(socket.SHUT_RDWR)
            except OSError: _ignored("intentional best-effort fallback")
            try: old.close()
            except OSError: _ignored("intentional best-effort fallback")
        with self.send_lock:
            self._pending.clear()
        if reconnect:
            with self._hello_lock:
                WayFinderRuntimeClient._hello_info = (
                    True,
                    "WayFinder runtime is reconnecting",
                    {"Runtime transport": "Reconnecting", "Runtime protocol": "Awaiting handshake"},
                )
        self._cancel_path_callbacks("Path request cancelled because the WayFinder runtime disconnected.")
        if should_reconnect:
            self.status_sink("recalculating", False)
            self.status_sink("runtime_available", False)
            self.status_sink("runtime_transport", "reconnecting")
            self.snapshot_sink(Snapshot(error=f"WayFinder runtime disconnected ({reason}); reconnecting…"))
            self._start_transport_retry()

    # /**
    #  * Function: _heartbeat_loop
    #  * Purpose: Perform the heartbeat loop operation while keeping the surrounding subsystem state consistent.
    #  * @param epoch: Epoch supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _heartbeat_loop(self, epoch: int) -> None:
        """Probe the localhost peer so half-open sockets are noticed promptly."""
        while not self.closed:
            time.sleep(HEARTBEAT_INTERVAL)
            with self._transport_lock:
                if epoch != self._transport_epoch or self.sock is None:
                    return
                # Variable(s): `sock` (sock); named state retained for the surrounding calculation or subsequent calls.
                sock = self.sock
                # Variable(s): `age` (age); named state retained for the surrounding calculation or subsequent calls.
                age = time.monotonic() - self._last_rx
            if age > HEARTBEAT_TIMEOUT:
                self.status_sink("runtime_watchdog",{"alive":False,"busy":False,"runtime_state":"ERROR"})
                self.log_sink(f"Runtime heartbeat timed out after {age:.1f}s; reconnecting.")
                self._drop_transport(sock, "heartbeat timeout")
                return
            if not self._send({"cmd": "ping", "epoch": epoch}):
                return

    # /**
    #  * Function: _cancel_path_callbacks
    #  * Purpose: Perform the cancel path callbacks operation while keeping the surrounding subsystem state consistent.
    #  * @param reason: Reason supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _cancel_path_callbacks(self, reason: str) -> None:
        # Variable(s): `callbacks` (callbacks); named state retained for the surrounding calculation or subsequent calls.
        """Handle cancel path callbacks."""
        callbacks = list(self.callbacks.items())
        self.callbacks.clear()
        # Loop variable(s): `_req_id` (req id), `callback` (callback), `timer` (timer); each iteration represents the next value from the iterable below.
        for _req_id, (callback, timer) in callbacks:
            try: timer.cancel()
            except Exception: _ignored("intentional best-effort fallback")
            try: callback(PathResult(target="", found=False, error=reason))
            except Exception: _ignored("intentional best-effort fallback")

    # /**
    #  * Function: _reader
    #  * Purpose: Perform the reader operation while keeping the surrounding subsystem state consistent.
    #  * @param epoch: Epoch supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param sock: Sock supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _reader(self, epoch: int, sock: socket.socket) -> None:
        """Read bounded newline-delimited JSON messages until this transport closes."""
        # Variable(s): `buffer` (buffer); named state retained for the surrounding calculation or subsequent calls.
        buffer = bytearray()
        try:
            while not self.closed:
                with self._transport_lock:
                    if epoch != self._transport_epoch or self.sock is not sock:
                        return
                try:
                    # Variable(s): `chunk` (chunk); named state retained for the surrounding calculation or subsequent calls.
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                self._last_rx = time.monotonic()
                buffer.extend(chunk)
                if len(buffer) > MAX_WIRE_MESSAGE_BYTES and b"\n" not in buffer:
                    self.log_sink("Runtime sent an unterminated IPC message larger than the allowed limit; connection dropped.")
                    break
                while True:
                    # Variable(s): `pos` (position); named state retained for the surrounding calculation or subsequent calls.
                    pos = buffer.find(b"\n")
                    if pos < 0:
                        break
                    # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
                    raw = bytes(buffer[:pos])
                    del buffer[:pos + 1]
                    if not raw.strip():
                        continue
                    if len(raw) > MAX_WIRE_MESSAGE_BYTES:
                        self.log_sink("Runtime sent an oversized IPC message; packet ignored.")
                        continue
                    try:
                        # Variable(s): `msg` (message); named state retained for the surrounding calculation or subsequent calls.
                        msg = json.loads(raw.decode("utf-8"))
                    except Exception as exc:
                        self.log_sink(f"Malformed runtime packet ignored: {exc!r}")
                        continue
                    if not isinstance(msg, dict):
                        self.log_sink("Malformed runtime packet ignored: top-level JSON value was not an object.")
                        continue
                    try:
                        self._handle_message(msg, epoch)
                    except Exception as exc:
                        self.log_sink(f"Invalid runtime message ignored: {exc!r}")
        except OSError as exc:
            if not self.closed:
                self.log_sink(f"WayFinder runtime disconnected: {exc!r}")
        finally:
            if not self.closed:
                self._drop_transport(sock, "reader closed")

    # /**
    #  * Function: _snapshot_fingerprint
    #  * Purpose: Perform the snapshot fingerprint operation while keeping the surrounding subsystem state consistent.
    #  * @param data: Data supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    @staticmethod
    def _snapshot_fingerprint(data: dict[str, Any]) -> str:
        # Variable(s): `meaningful` (meaningful); named state retained for the surrounding calculation or subsequent calls.
        """Handle snapshot fingerprint."""
        meaningful = dict(data)
        # Loop variable(s): `key` (key); each iteration represents the next value from the iterable below.
        for key in ("snapshot_sequence", "updated_at", "refresh_id", "event_id"):
            meaningful.pop(key, None)
        try:
            return json.dumps(meaningful, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        except Exception:
            return repr(meaningful)

    # /**
    #  * Function: _handle_message
    #  * Purpose: Perform the handle message operation while keeping the surrounding subsystem state consistent.
    #  * @param msg: Message supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param epoch: Epoch supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _handle_message(self, msg: dict[str, Any], epoch: int) -> None:
        """Validate and dispatch one live-server message without trusting its shape."""
        # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
        kind = msg.get("type")
        if not isinstance(kind, str):
            raise ValueError("message type is missing or not a string")
        if kind == "hello":
            # Variable(s): `raw_version` (raw version); named state retained for the surrounding calculation or subsequent calls.
            raw_version = msg.get("protocol_version")
            try:
                # Variable(s): `version` (version); named state retained for the surrounding calculation or subsequent calls.
                version = int(raw_version)
            except (TypeError, ValueError):
                # Variable(s): `version` (version); named state retained for the surrounding calculation or subsequent calls.
                version = -1
            if not (IPC_PROTOCOL_MIN <= version <= IPC_PROTOCOL_MAX):
                # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
                text = f"Incompatible WayFinder protocol: GUI supports {IPC_PROTOCOL_MIN}-{IPC_PROTOCOL_MAX}, runtime reported {raw_version!r}. Rebuild or update the WayFinder runtime."
                with self._hello_lock:
                    WayFinderRuntimeClient._hello_info = (False, text, {"Runtime protocol": "Incompatible"})
                self.status_sink("runtime_transport", "incompatible")
                self.status_sink("runtime_available", False)
                self.log_sink(text)
                with self._transport_lock:
                    # Variable(s): `sock` (sock); named state retained for the surrounding calculation or subsequent calls.
                    sock = self.sock
                self._drop_transport(sock, "incompatible protocol", reconnect=False)
                return
            # Variable(s): `session_id` (session id); named state retained for the surrounding calculation or subsequent calls.
            session_id = msg.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise ValueError("hello packet did not include a valid session_id")
            with self._transport_lock:
                if epoch != self._transport_epoch:
                    return
                self._session_id = session_id
                self._protocol_compatible = True
                self._last_snapshot_fingerprint = ""
            # Variable(s): `ok` (ok); named state retained for the surrounding calculation or subsequent calls.
            ok = bool(msg.get("ok", False))
            # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
            text = str(msg.get("message", "WayFinder runtime connected"))
            # Variable(s): `checks_raw` (checks raw); named state retained for the surrounding calculation or subsequent calls.
            checks_raw = msg.get("checks", {})
            # Variable(s): `checks` (checks); named state retained for the surrounding calculation or subsequent calls.
            checks = {str(k): str(v) for k, v in checks_raw.items()} if isinstance(checks_raw, dict) else {}
            checks["Runtime protocol"] = f"OK - v{version}"
            # Variable(s): `caps` (caps); named state retained for the surrounding calculation or subsequent calls.
            caps=msg.get("capabilities", [])
            self._negotiated_capabilities=set(str(x) for x in caps if str(x) in CAPABILITIES) if isinstance(caps,list) else set()
            # Variable(s): `now` (now); named state retained for the surrounding calculation or subsequent calls.
            now=time.time()
            # Loop variable(s): `cap` (cap); each iteration represents the next value from the iterable below.
            for cap in self._negotiated_capabilities: self._capability_last_ok[cap]=now
            self.status_sink("runtime_capabilities", sorted(self._negotiated_capabilities))
            self.status_sink("runtime_capability_last_ok", dict(self._capability_last_ok))
            self.status_sink("runtime_protocol_version", version)
            with self._hello_lock:
                WayFinderRuntimeClient._hello_info = (ok, text, checks)
            self.status_sink("engine_version", str(msg.get("engine_version", "unknown")))
            self.status_sink("ap_version", str(msg.get("ap_version", "unknown")))
            self.status_sink("integration_version", str(msg.get("integration_version", "unknown")))
            self.status_sink("apworld_generated_by", str(msg.get("apworld_generated_by", "unknown")))
            # Variable(s): `startup_stage` (startup stage); named state retained for the surrounding calculation or subsequent calls.
            startup_stage = str(checks.get("Startup stage", "") or "")
            if startup_stage:
                self.status_sink("runtime_startup_stage", startup_stage)
            if str(checks.get("Live context hook", "")).startswith("OK"):
                self.status_sink("ut_runtime_hook", "installed")
            self.status_sink("runtime_state",{"current":msg.get("health_state","READY")})
            if msg.get("component_health"):self.status_sink("component_health",msg["component_health"])
            if msg.get("self_test"):self.status_sink("runtime_self_test",msg["self_test"])
            self.status_sink("runtime_transport", "connected")
            self.log_sink(text + f" [IPC v{version}]")
            self._flush_pending()
            return
        with self._transport_lock:
            if epoch != self._transport_epoch or not self._protocol_compatible:
                return
            # Variable(s): `session_id` (session id); named state retained for the surrounding calculation or subsequent calls.
            session_id = self._session_id
        # Variable(s): `msg_session` (msg session); named state retained for the surrounding calculation or subsequent calls.
        msg_session = msg.get("session_id")
        if msg_session != session_id and (kind != "error" or msg_session is not None):
            self.log_sink(f"Ignored stale {kind} packet from a previous runtime session.")
            return
        if kind == "snapshot":
            # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
            data = decode_snapshot(msg)
            if "snapshot_zlib" in self._negotiated_capabilities:
                self._capability_last_ok["snapshot_zlib"]=time.time()
            if not isinstance(data, dict):
                raise ValueError("snapshot data is not an object")

            # Variable(s): `fingerprint` (fingerprint); named state retained for the surrounding calculation or subsequent calls.
            try:
                validate_snapshot(data)
                if "seed_identity" in self._negotiated_capabilities:
                    self._seed_gate.check(data)
            except ValueError as exc:
                self.status_sink("runtime_error",dict(error_code="WF_SNAPSHOT_REJECTED",component="Snapshot Pipeline",message=str(exc),event_id=msg.get("event_id",""),recoverable=True))
                return
            data['event_id']=str(msg.get('event_id',''))
            snapshot = _snapshot_from_dict(data)
            if "seed_identity" in self._negotiated_capabilities:self._seed_gate.commit(data)
            fingerprint = self._snapshot_fingerprint(data)
            # Variable(s): `refresh_id` (refresh id); named state retained for the surrounding calculation or subsequent calls.
            refresh_id = int(data.get("refresh_id", 0) or 0)

            # Background native-runtime publishes may legitimately be identical, so retain
            # semantic de-duplication for them. An explicit manual Refresh State,
            # however, must always reach the GUI because its fresh updated_at,
            # snapshot_sequence and refresh correlation are meaningful even when
            # logic/inventory/check state did not change.
            if refresh_id <= 0 and fingerprint == self._last_snapshot_fingerprint:
                return

            # Variable(s): `snapshot` (snapshot); named state retained for the surrounding calculation or subsequent calls.
            self._last_snapshot_fingerprint = fingerprint
            self.snapshot_sink(snapshot)
        elif kind == "log":
            self.log_sink(("[event "+str(msg["event_id"])+"] " if msg.get("event_id") else "")+str(msg.get("message", "")))
        elif kind == "status":
            # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
            name = msg.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError("status name is invalid")
            if name=='seed_identity':
                value=msg.get('value',{})
                if not self._seed_gate.announce(value.get('identity'),value.get('connection_id')):return
            self.status_sink(name, msg.get("value"))
        elif kind == "path":
            # Variable(s): `req_id` (req id); named state retained for the surrounding calculation or subsequent calls.
            req_id = int(msg.get("id", 0) or 0)
            # Variable(s): `entry` (entry); named state retained for the surrounding calculation or subsequent calls.
            entry = self.callbacks.pop(req_id, None)
            if entry:
                # Variable(s): `callback` (callback), `timer` (timer); named state retained for the surrounding calculation or subsequent calls.
                callback, timer = entry
                try: timer.cancel()
                except Exception: _ignored("intentional best-effort fallback")
                # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
                data = msg.get("data")
                callback(_path_from_dict(data if isinstance(data, dict) else {}))
        elif kind == "datastorage_value":
            req_id = int(msg.get("id", 0) or 0)
            entry = self.datastorage_callbacks.pop(req_id, None)
            if entry:
                callback, timer = entry
                try:
                    timer.cancel()
                except Exception:
                    _ignored("intentional best-effort fallback")
                data = msg.get("data")
                callback(data if isinstance(data, dict) else {"found": False, "error": "Invalid DataStorage response."})
        elif kind == "pong":
            self.status_sink("runtime_watchdog",dict(msg.get("health",{}),runtime_state=msg.get("runtime_state","READY")))
            if isinstance(msg.get('components'),dict):self.status_sink('component_health',msg['components'])
            self._capability_last_ok["heartbeat"]=time.time()
            self.status_sink("runtime_capability_last_ok", dict(self._capability_last_ok))
            return
        elif kind == "error":
            self.status_sink("runtime_error",dict(msg))
        else:
            self.log_sink(f"Ignored unknown runtime message type {kind!r}.")

    # /**
    #  * Function: connect
    #  * Purpose: Perform the connect operation while keeping the surrounding subsystem state consistent.
    #  * @param server: Server supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param slot_name: Slot name supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param password: Password supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def connect(self, server: str, slot_name: str, password: str = "") -> None:
        """Request an Archipelago connection through the WayFinder runtime."""
        # A new explicit Connect supersedes any queued emergency Disconnect that
        # was waiting for the IPC transport to recover.  Without this, a very
        # fast Disconnect -> Connect sequence could reconnect the IPC transport
        # and then immediately deliver the older disconnect command.
        with self.send_lock:
            self._pending = [payload for payload in self._pending if payload.get("cmd") != "disconnect"]
        connection=uuid.uuid4().hex
        self._seed_gate.begin(connection,server,slot_name)
        self._last_connection=(server,slot_name,password)
        self._send({"cmd": "connect", "server": server, "slot_name": slot_name, "password": password, "connection_id":connection})

    # /**
    #  * Function: disconnect
    #  * Purpose: Perform the disconnect operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def restart_connection(self):
        """Re-arm a fresh owned process connection without replaying old commands."""
        connection=self._last_connection
        with self._transport_lock:sock=self.sock
        self._drop_transport(sock,"runtime restarted",reconnect=False)
        with self.send_lock:self._pending=[]
        self._ever_connected=False
        if connection:self.connect(*connection)
        else:self._start_transport_retry()

    def disconnect(self) -> bool:
        """Request a hard manual AP disconnect and guarantee delivery to the runtime.

        Most post-connect commands are intentionally dropped while the GUI-to-runtime
        IPC transport is reconnecting because replaying stale UI actions is unsafe.
        Disconnect is different: if WayFinder loses IPC while the native runtime is
        still connected to Archipelago, dropping this command leaves the user visibly
        stuck online.  Queue exactly one disconnect and wake the IPC retry loop so the
        user's explicit request is delivered as soon as the runtime link returns.
        """
        payload = {"cmd": "disconnect"}
        self._last_connection=None
        if hasattr(self,"_seed_gate"):
            connection=uuid.uuid4().hex;self._seed_gate.begin(connection)
            payload["connection_id"]=connection
        if self._send(payload):
            return True
        if self.closed:
            return False
        with self.send_lock:
            self._pending = [item for item in self._pending if item.get("cmd") != "disconnect"]
            self._queue_startup_command(payload)
        self.log_sink("Runtime IPC unavailable; queued the manual Disconnect for guaranteed delivery.")
        self._start_transport_retry()
        return True

    # /**
    #  * Function: refresh_state
    #  * Purpose: Refresh state from the latest available state.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def refresh_state(self) -> int:
        """Request a refresh and return the request id used to reject stale completions."""
        # Variable(s): `refresh_id` (refresh id); named state retained for the surrounding calculation or subsequent calls.
        refresh_id = self._next_refresh_id
        self._next_refresh_id += 1
        self._send({"cmd": "refresh", "refresh_id": refresh_id})
        return refresh_id

    # /**
    #  * Function: request_path
    #  * Purpose: Perform the request path operation while keeping the surrounding subsystem state consistent.
    #  * @param target: Target supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param callback: Callback supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param timeout: Timeout supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def request_datastorage_value(self, key: str, callback: Callable[[dict[str, Any]], None], timeout: float = 10.0) -> int:
        """Fetch exactly one DataStorage value from the runtime for interactive inspection."""
        req_id = self.next_id
        self.next_id += 1

        def on_timeout() -> None:
            """Handle on timeout."""
            entry = self.datastorage_callbacks.pop(req_id, None)
            if not entry:
                return
            cb, _timer = entry
            try:
                cb({"key": key, "found": False, "error": f"DataStorage request timed out after {timeout:g}s."})
            except Exception:
                _ignored("intentional best-effort fallback")

        timer = threading.Timer(timeout, on_timeout)
        timer.daemon = True
        self.datastorage_callbacks[req_id] = (callback, timer)
        timer.start()
        if not self._send({"cmd": "datastorage_value", "id": req_id, "key": key}):
            entry = self.datastorage_callbacks.pop(req_id, None)
            if entry:
                _cb, pending_timer = entry
                pending_timer.cancel()
            callback({"key": key, "found": False, "error": "WayFinder runtime is not connected."})
        return req_id

    # /**
    #  * Function: request_path
    #  * Purpose: Perform the request path operation while keeping the surrounding subsystem state consistent.
    #  */
    def request_path(self, target: str, callback: Callable[[PathResult], None], timeout: float = 15.0) -> int:
        """Request asynchronous path analysis with cancellation and timeout."""
        # Variable(s): `req_id` (req id); named state retained for the surrounding calculation or subsequent calls.
        req_id = self.next_id
        self.next_id += 1
        # /**
        #  * Function: on_timeout
        #  * Purpose: Handle the timeout event or callback.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        def on_timeout() -> None:
            # Variable(s): `entry` (entry); named state retained for the surrounding calculation or subsequent calls.
            """Handle on timeout."""
            entry = self.callbacks.pop(req_id, None)
            if not entry:
                return
            # Variable(s): `cb` (callback), `_timer` (timer); named state retained for the surrounding calculation or subsequent calls.
            cb, _timer = entry
            try: cb(PathResult(target=target, found=False, error=f"Path analysis timed out after {timeout:g}s."))
            except Exception: _ignored("intentional best-effort fallback")
        # Variable(s): `timer` (timer); named state retained for the surrounding calculation or subsequent calls.
        timer = threading.Timer(timeout, on_timeout)
        timer.daemon = True
        self.callbacks[req_id] = (callback, timer)
        timer.start()
        if not self._send({"cmd": "path", "id": req_id, "target": target}):
            # Variable(s): `entry` (entry); named state retained for the surrounding calculation or subsequent calls.
            entry = self.callbacks.pop(req_id, None)
            if entry:
                # Variable(s): `_cb` (cb), `t` (t); named state retained for the surrounding calculation or subsequent calls.
                _cb, t = entry
                t.cancel()
                callback(PathResult(target=target, found=False, error="WayFinder runtime is not connected."))
        return req_id

    # /**
    #  * Function: ignore_location
    #  * Purpose: Perform the ignore location operation while keeping the surrounding subsystem state consistent.
    #  * @param name: Name supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def set_ignored_locations(self, names: list[str]) -> None:
        """Replace the native runtime ignored-location set in one operation."""
        clean = sorted({str(name).strip() for name in (names or []) if str(name).strip()})
        self._send({"cmd": "set_ignored", "names": clean})

    def ignore_location(self, name: str) -> None:
        """Mark a location ignored in the WayFinder runtime."""
        self._send({"cmd": "ignore", "name": name})

    # /**
    #  * Function: unignore_location
    #  * Purpose: Perform the unignore location operation while keeping the surrounding subsystem state consistent.
    #  * @param name: Name supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def unignore_location(self, name: str) -> None:
        """Remove a previously applied ignored-location override."""
        self._send({"cmd": "unignore", "name": name})


    # /**
    #  * Function: send_console_command
    #  * Purpose: Perform the send console command operation while keeping the surrounding subsystem state consistent.
    #  * @param text: Text supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def inspect_ap(self, action='summary', **fields):
        """Handle inspect ap."""
        return self._send(dict(cmd='ap_inspect',action=action,**fields))

    def send_console_command(self, text: str) -> None:
        """Send one command/chat line to WayFinder command processor."""
        # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
        text=(text or "").strip()
        if text:
            self._send({"cmd": "console", "text": text})

    # /**
    #  * Function: close
    #  * Purpose: Perform the close operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def close(self) -> None:
        """Stop retries and close the local runtime socket during GUI shutdown."""
        self.closed = True
        self._cancel_path_callbacks("Path request cancelled because WayFinder is closing.")
        with self.send_lock:
            self._pending.clear()
        try:
            self._send({"cmd": "shutdown"})
        except Exception:
            _ignored("intentional best-effort fallback")
        try:
            if self.sock:
                self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            _ignored("intentional best-effort fallback")
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            _ignored("intentional best-effort fallback")
        self.sock = None
        # Variable(s): `current` (current); named state retained for the surrounding calculation or subsequent calls.
        current=threading.current_thread()
        # Loop variable(s): `thread` (thread); each iteration represents the next value from the iterable below.
        for thread in (self.reader_thread, self.connect_thread, self.heartbeat_thread):
            if thread and thread is not current and thread.is_alive():
                try: thread.join(timeout=1.5)
                except Exception: _ignored("intentional best-effort fallback")
