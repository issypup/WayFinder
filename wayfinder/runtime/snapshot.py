"""Provide snapshot support."""
# /**
#  * Module: wayfinder.runtime/snapshot.py
#  * Purpose: Runtime module for snapshot; bridges loaded Archipelago worlds and live server state into tracker snapshots.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

import hashlib
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from wayfinder.logic.apworld_adapter import evaluate_generated_world, NativeAPState
from wayfinder.logic.incremental import IncrementalAPWorldEvaluator
from wayfinder.logic.logic_api import WAYFINDER_LOGIC_API, RecalculationStats
from . import RUNTIME_VERSION


# /**
#  * Function: _safe_name
#  * Purpose: Perform the safe name operation while keeping the surrounding subsystem state consistent.
#  * @param mapping: Mapping supplied by the caller; see type hints and call sites for domain constraints.
#  * @param ident: Ident supplied by the caller; see type hints and call sites for domain constraints.
#  * @param fallback: Fallback supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _safe_name(mapping: Any, ident: int, fallback: str = "") -> str:
    """Handle safe name."""
    try:
        # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
        value = mapping.get(ident)
        if value:
            return str(value)
    except Exception:
        _ignored("intentional best-effort fallback")
    return fallback or str(ident)


# /**
#  * Function: _glitch_logic_item_name
#  * Purpose: Perform the glitch logic item name operation while keeping the surrounding subsystem state consistent.
#  * @param world: World supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _glitch_logic_item_name(world: Any) -> str:
    """Return an APWorld-declared pseudo-item used to enable glitch logic.

    This is a compatibility convention used by some APWorlds.  WayFinder
    evaluates the same APWorld twice: once with the real inventory and, when
    this attribute is present, once with the pseudo-item granted.  No Universal
    Tracker runtime is involved.
    """
    # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
    value = getattr(world, "glitches_item_name", "")
    return str(value or "").strip()


# /**
#  * Function: _evaluate_logic_sets
#  * Purpose: Evaluate logic sets against the current tracker state.
#  * @param multiworld: Multiworld supplied by the caller; see type hints and call sites for domain constraints.
#  * @param world: World supplied by the caller; see type hints and call sites for domain constraints.
#  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
#  * @param inventory: Inventory supplied by the caller; see type hints and call sites for domain constraints.
#  * @param checked_names: Checked names supplied by the caller; see type hints and call sites for domain constraints.
#  * @param built: Built supplied by the caller; see type hints and call sites for domain constraints.
#  * @param force_full: Force full supplied by the caller; see type hints and call sites for domain constraints.
#  * @param return_stats: Return stats supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _evaluate_logic_sets(*, multiworld: Any, world: Any, player: int, inventory: Counter[str], checked_names: set[str], built: Any = None, force_full: bool = False, return_stats: bool = False):
    """Handle evaluate logic sets."""
    if built is None:
        from types import SimpleNamespace
        # Variable(s): `built` (built); named state retained for the surrounding calculation or subsequent calls.
        built = SimpleNamespace()
    # Variable(s): `evaluator` (evaluator); named state retained for the surrounding calculation or subsequent calls.
    evaluator = getattr(built, "_wayfinder_logic_evaluator", None)
    if not isinstance(evaluator, IncrementalAPWorldEvaluator) or evaluator.multiworld is not multiworld or evaluator.world is not world or evaluator.player != int(player):
        # Variable(s): `evaluator` (evaluator); named state retained for the surrounding calculation or subsequent calls.
        evaluator = IncrementalAPWorldEvaluator(multiworld=multiworld, world=world, player=player)
        setattr(built, "_wayfinder_logic_evaluator", evaluator)
    # Variable(s): `normal_result` (normal result); named state retained for the surrounding calculation or subsequent calls.
    normal_result = evaluator.evaluate(Counter(inventory), set(checked_names), force_full=force_full, trigger="manual_refresh" if force_full else "live_state")
    # Variable(s): `normal` (normal); named state retained for the surrounding calculation or subsequent calls.
    normal = normal_result.snapshot

    # Variable(s): `glitch_item` (glitch item); named state retained for the surrounding calculation or subsequent calls.
    glitch_item = _glitch_logic_item_name(world)
    # Variable(s): `glitch` (glitch); named state retained for the surrounding calculation or subsequent calls.
    glitch = None
    # Variable(s): `glitch_stats` (glitch stats); named state retained for the surrounding calculation or subsequent calls.
    glitch_stats = RecalculationStats(mode="disabled", trigger="no_glitch_capability")
    if glitch_item:
        # Variable(s): `glitch_evaluator` (glitch evaluator); named state retained for the surrounding calculation or subsequent calls.
        glitch_evaluator = getattr(built, "_wayfinder_glitch_logic_evaluator", None)
        if not isinstance(glitch_evaluator, IncrementalAPWorldEvaluator) or glitch_evaluator.multiworld is not multiworld or glitch_evaluator.world is not world or glitch_evaluator.player != int(player):
            # Variable(s): `glitch_evaluator` (glitch evaluator); named state retained for the surrounding calculation or subsequent calls.
            glitch_evaluator = IncrementalAPWorldEvaluator(multiworld=multiworld, world=world, player=player)
            setattr(built, "_wayfinder_glitch_logic_evaluator", glitch_evaluator)
        # Variable(s): `glitch_inventory` (glitch inventory); named state retained for the surrounding calculation or subsequent calls.
        glitch_inventory = Counter(inventory)
        # A deliberately large count avoids APWorlds using has(..., count=N)
        # for their synthetic glitch capability flag.
        glitch_inventory[glitch_item] = max(999, int(glitch_inventory.get(glitch_item, 0)))
        # Variable(s): `glitch_result` (glitch result); named state retained for the surrounding calculation or subsequent calls.
        glitch_result = glitch_evaluator.evaluate(glitch_inventory, set(checked_names), force_full=force_full, trigger="manual_refresh" if force_full else "live_state")
        # Variable(s): `glitch` (glitch); named state retained for the surrounding calculation or subsequent calls.
        glitch = glitch_result.snapshot
        # Variable(s): `glitch_stats` (glitch stats); named state retained for the surrounding calculation or subsequent calls.
        glitch_stats = glitch_result.stats
    if return_stats:
        return normal, glitch, glitch_item, normal_result.stats, glitch_stats
    return normal, glitch, glitch_item




def _entrance_randomization_enabled(world: Any) -> bool | None:
    """Return whether the reconstructed world's entrance randomization is enabled.

    This is intentionally convention-based and game-neutral.  APWorld options
    whose attribute names describe entrance randomization/shuffling are treated
    as entrance-rando controls.  ``None`` means the APWorld exposes no recognizable
    control, so the UI must not assume vanilla assignments.
    """
    options = getattr(world, "options", None)
    if options is None:
        return None
    try:
        names = list(vars(options).keys())
    except Exception:
        names = [name for name in dir(options) if not str(name).startswith("_")]

    candidates: list[Any] = []
    for name in names:
        folded = re.sub(r"[^a-z0-9]+", "_", str(name).casefold()).strip("_")
        is_entrance_option = (
            ("entrance" in folded and ("random" in folded or "shuffle" in folded))
            or folded in {"entrance_rando", "entrance_shuffle"}
        )
        if not is_entrance_option:
            continue
        try:
            raw = getattr(options, name)
        except Exception:
            continue
        value = getattr(raw, "value", raw)
        candidates.append(value)

    if not candidates:
        return None

    def enabled(value: Any) -> bool:
        """Handle enabled."""
        if isinstance(value, str):
            folded = value.strip().casefold()
            if folded in {"", "0", "false", "off", "none", "disabled", "vanilla"}:
                return False
            if folded in {"1", "true", "on", "enabled", "randomized", "randomised"}:
                return True
        try:
            return bool(int(value))
        except (TypeError, ValueError):
            return bool(value)

    return any(enabled(value) for value in candidates)


# /**
#  * Function: _live_map_page_state
#  * Purpose: Perform the live map page state operation while keeping the surrounding subsystem state consistent.
#  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
#  * @param built: Built supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _live_map_page_state(ctx: Any, built: Any) -> tuple[str, Any, int]:
    """Return resolved DataStorage key, raw value, and APWorld-derived map index."""
    # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
    key = str(getattr(built, "resolved_map_page_setting_key", "") or "").strip()
    # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
    raw = None
    # Variable(s): `idx` (index); named state retained for the surrounding calculation or subsequent calls.
    idx = -1
    if not key:
        return key, raw, idx
    try:
        # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
        raw = (getattr(ctx, "stored_data", {}) or {}).get(key)
    except Exception:
        # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
        raw = None
    # Variable(s): `hook` (hook); named state retained for the surrounding calculation or subsequent calls.
    hook = getattr(built, "map_page_index_hook", None)
    if raw is not None and callable(hook):
        try:
            # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
            value = hook(raw)
            if not isinstance(value, bool):
                # Variable(s): `idx` (index); named state retained for the surrounding calculation or subsequent calls.
                idx = int(value)
        except Exception:
            # Variable(s): `idx` (index); named state retained for the surrounding calculation or subsequent calls.
            idx = -1
    elif raw is not None:
        try:
            if not isinstance(raw, bool):
                # Variable(s): `idx` (index); named state retained for the surrounding calculation or subsequent calls.
                idx = int(raw)
        except (TypeError, ValueError):
            # Variable(s): `idx` (index); named state retained for the surrounding calculation or subsequent calls.
            idx = -1
    return key, raw, idx



# /**
#  * Function: _normalise_player_position
#  * Purpose: Perform the normalise player position operation while keeping the surrounding subsystem state consistent.
#  * @param raw: Raw value supplied by the caller; see type hints and call sites for domain constraints.
#  * @param hook: Hook supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _normalise_player_position(raw: Any, hook: Any = None) -> tuple[int, list[dict[str, float]]]:
    """Translate an exposed live-position value into WayFinder map coordinates.

    Accepted hook/raw forms: {x,y,map_index}, {x,y,map}, [x,y], (x,y),
    or {map_index, icons:[{x,y}, ...]}.  Coordinates are unscaled source-image
    pixels; the GUI applies the current zoom factor.
    """
    # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
    value = raw
    if callable(hook) and raw is not None:
        try:
            # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
            value = hook(raw)
        except Exception:
            return -1, []
    # Variable(s): `map_index` (map index); named state retained for the surrounding calculation or subsequent calls.
    map_index = -1
    # Variable(s): `label` (label); named state retained for the surrounding calculation or subsequent calls.
    label = ""
    # Variable(s): `icons` (icons); named state retained for the surrounding calculation or subsequent calls.
    icons: list[dict[str, float]] = []
    if isinstance(value, dict):
        try:
            # Variable(s): `map_index` (map index); named state retained for the surrounding calculation or subsequent calls.
            map_index = int(value.get("map_index", value.get("map", -1)))
        except (TypeError, ValueError):
            # Variable(s): `map_index` (map index); named state retained for the surrounding calculation or subsequent calls.
            map_index = -1
        # Variable(s): `label` (label); named state retained for the surrounding calculation or subsequent calls.
        label = str(value.get("room", value.get("subregion", value.get("label", ""))) or "")
        # Variable(s): `raw_icons` (raw icons); named state retained for the surrounding calculation or subsequent calls.
        raw_icons = value.get("icons")
        if isinstance(raw_icons, list):
            # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
            candidates = raw_icons
        elif "x" in value and "y" in value:
            # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
            candidates = [value]
        else:
            # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
            candidates = []
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
        candidates = [{"x": value[0], "y": value[1]}]
        if len(value) >= 3:
            # Variable(s): `map_index` (map index); named state retained for the surrounding calculation or subsequent calls.
            try: map_index = int(value[2])
            except (TypeError, ValueError): _ignored("intentional best-effort fallback")
    else:
        # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
        candidates = []
    # Loop variable(s): `icon` (icon); each iteration represents the next value from the iterable below.
    for icon in candidates:
        if not isinstance(icon, dict):
            continue
        try:
            # Variable(s): `x` (horizontal x-coordinate), `y` (vertical y-coordinate); named state retained for the surrounding calculation or subsequent calls.
            x, y = float(icon.get("x")), float(icon.get("y"))
        except (TypeError, ValueError):
            continue
        if x < 0 or y < 0:
            continue
        icons.append({"x": x, "y": y})
    return map_index, icons


# /**
#  * Function: _live_player_position_state
#  * Purpose: Perform the live player position state operation while keeping the surrounding subsystem state consistent.
#  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
#  * @param built: Built supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _live_player_position_state(ctx: Any, built: Any) -> tuple[str, Any, int, list[dict[str, float]]]:
    # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
    """Handle live player position state."""
    key = str(getattr(built, "resolved_player_position_setting_key", "") or "").strip()
    if not key:
        return "", None, -1, []
    try:
        # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
        raw = (getattr(ctx, "stored_data", {}) or {}).get(key)
    except Exception:
        # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
        raw = None
    # Variable(s): `idx` (index), `icons` (icons); named state retained for the surrounding calculation or subsequent calls.
    idx, icons = _normalise_player_position(raw, getattr(built, "player_position_hook", None))
    return key, raw, idx, icons



# /**
#  * Function: _player_name
#  * Purpose: Perform the player name operation while keeping the surrounding subsystem state consistent.
#  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
#  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _player_name(ctx: Any, player: Any) -> str:
    """Handle player name."""
    try:
        return str((getattr(ctx, "player_names", {}) or {}).get(int(player), player))
    except Exception:
        return str(player)


# /**
#  * Function: _player_game
#  * Purpose: Perform the player game operation while keeping the surrounding subsystem state consistent.
#  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
#  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
#  * @param fallback: Fallback supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _player_game(ctx: Any, player: Any, fallback: str = "") -> str:
    """Handle player game."""
    try:
        # Variable(s): `info` (info); named state retained for the surrounding calculation or subsequent calls.
        info = (getattr(ctx, "slot_info", {}) or {}).get(int(player))
        # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
        game = str(getattr(info, "game", "") or "")
        if game:
            return game
    except Exception:
        _ignored("intentional best-effort fallback")
    return str(fallback or getattr(ctx, "game", "") or "")


# /**
#  * Function: _lookup_network_name
#  * Purpose: Perform the lookup network name operation while keeping the surrounding subsystem state consistent.
#  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
#  * @param kind: Kind supplied by the caller; see type hints and call sites for domain constraints.
#  * @param game: Game supplied by the caller; see type hints and call sites for domain constraints.
#  * @param ident: Ident supplied by the caller; see type hints and call sites for domain constraints.
#  * @param fallback_mapping: Fallback mapping supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _lookup_network_name(ctx: Any, kind: str, game: str, ident: Any, fallback_mapping: dict | None = None) -> str:
    """Handle lookup network name."""
    try:
        # Variable(s): `lookup` (lookup); named state retained for the surrounding calculation or subsequent calls.
        lookup = getattr(ctx, "item_names" if kind == "item" else "location_names")
        # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
        value = lookup[game].get(int(ident))
        if value:
            return str(value)
    except Exception:
        _ignored("intentional best-effort fallback")
    try:
        # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
        value = (fallback_mapping or {}).get(int(ident))
        if value:
            return str(value)
    except Exception:
        _ignored("intentional best-effort fallback")
    return str(ident)


# /**
#  * Function: _hint_status_name
#  * Purpose: Perform the hint status name operation while keeping the surrounding subsystem state consistent.
#  * @param value: Value supplied by the caller; see type hints and call sites for domain constraints.
#  * @param found: Found supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _hint_status_name(value: Any, found: bool = False) -> str:
    """Handle hint status name."""
    if found:
        return "found"
    # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
    names = {0: "unspecified", 10: "no_priority", 20: "avoid", 30: "priority", 40: "found"}
    try:
        return names.get(int(value), str(value).lower().replace("hint_", ""))
    except Exception:
        return str(value or "unspecified").lower().replace("hint_", "")


# /**
#  * Function: _live_hints
#  * Purpose: Perform the live hints operation while keeping the surrounding subsystem state consistent.
#  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
#  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
#  * @param item_id_to_name: Item id to name supplied by the caller; see type hints and call sites for domain constraints.
#  * @param location_id_to_name: Location id to name supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _live_hints(ctx: Any, player: int, item_id_to_name: dict, location_id_to_name: dict) -> tuple[str, list[dict[str, Any]]]:
    """Read and merge Archipelago hint DataStorage entries for the current team.

    WayFinder subscribes to every visible slot's hint key.  A single hint may be
    represented in more than one subscribed set, so rows are de-duplicated by
    the network identity of the hinted item/location and participating players.
    """
    team = int(getattr(ctx, "team", 0) or 0)
    own_key = f"_read_hints_{team}_{player}"
    try:
        stored_data = dict(getattr(ctx, "stored_data", {}) or {})
    except Exception:
        stored_data = {}

    prefix = f"_read_hints_{team}_"
    keys = sorted(key for key in stored_data if str(key).startswith(prefix))
    if own_key not in keys:
        keys.insert(0, own_key)

    rows_by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
    for storage_key in keys:
        raw = stored_data.get(storage_key, [])
        for hint in raw or []:
            if hasattr(hint, "_asdict"):
                hint = hint._asdict()
            if not isinstance(hint, dict):
                continue
            receiving = hint.get("receiving_player", player)
            finding = hint.get("finding_player", player)
            item_id = hint.get("item", "")
            location_id = hint.get("location", "")
            found = bool(hint.get("found", False))
            item_game = _player_game(ctx, receiving, getattr(ctx, "game", ""))
            location_game = _player_game(ctx, finding, getattr(ctx, "game", ""))
            row = {
                "item": _lookup_network_name(ctx, "item", item_game, item_id, item_id_to_name if int(receiving or 0) == player else None),
                "location": _lookup_network_name(ctx, "location", location_game, location_id, location_id_to_name if int(finding or 0) == player else None),
                "receiving_player": _player_name(ctx, receiving),
                "finding_player": _player_name(ctx, finding),
                "found": found,
                "status": _hint_status_name(hint.get("status", 0), found),
                "entrance": str(hint.get("entrance", "") or ""),
                "item_flags": int(hint.get("item_flags", 0) or 0),
            }
            identity = (
                int(receiving or 0), int(finding or 0),
                str(item_id), str(location_id), row["entrance"]
            )
            previous = rows_by_identity.get(identity)
            if previous is None:
                rows_by_identity[identity] = row
            else:
                # Prefer the most informative/latest state when the same hint is
                # present in multiple players' read sets.
                if row["found"] or (previous.get("status") == "unspecified" and row["status"] != "unspecified"):
                    rows_by_identity[identity] = row

    rows = list(rows_by_identity.values())
    rows.sort(key=lambda row: (str(row.get("receiving_player", "")), str(row.get("item", "")), str(row.get("location", ""))))
    key_description = own_key if len(keys) <= 1 else f"{len(keys)} team hint keys"
    return key_description, rows

# /**
#  * Function: _goal_detail
#  * Purpose: Perform the goal detail operation while keeping the surrounding subsystem state consistent.
#  * @param multiworld: Multiworld supplied by the caller; see type hints and call sites for domain constraints.
#  * @param world: World supplied by the caller; see type hints and call sites for domain constraints.
#  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
#  * @param inventory: Inventory supplied by the caller; see type hints and call sites for domain constraints.
#  * @param result: Result supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _goal_detail(multiworld: Any, world: Any, player: int, inventory: Counter[str], result: Any) -> dict[str, Any]:
    # Variable(s): `rule` (rule); named state retained for the surrounding calculation or subsequent calls.
    """Handle goal detail."""
    rule = (getattr(multiworld, "completion_condition", {}) or {}).get(player)
    if not callable(rule):
        return {"available": False, "satisfied": False, "module": "", "consulted": [], "missing": [], "error": "No completion condition exposed."}
    from types import SimpleNamespace
    from wayfinder.logic.apworld_adapter import trace_access_rule
    detail = trace_access_rule(SimpleNamespace(access_rule=rule), player=player,
                               inventory=Counter(inventory), reachable_regions=set(result.reachable_regions),
                               events=set(result.events), groups=getattr(world, 'item_name_groups', {}) or {},
                               multiworld=multiworld)
    trace, missing = detail['consulted'], detail['missing']
    satisfied, error = detail['satisfied'], detail['error']

    # Goal provenance/backtracking.  Archipelago completion conditions very
    # commonly reduce to an event item such as ``Victory``.  The player YAML
    # selects the world options, but the generated APWorld graph is the
    # authoritative source for where that event/item is actually produced.
    # Record those producer locations here so the GUI can route to them rather
    # than trying to treat the completion item name as a normal location name.
    missing_items={str(x.get("name") or "") for x in missing if x.get("kind")=="item" and str(x.get("name") or "")}
    sources=[]
    try:
        for loc in list(multiworld.get_locations(player)):
            item_name=str(getattr(getattr(loc,"item",None),"name","") or "")
            if not item_name or item_name not in missing_items:
                continue
            location_name=str(getattr(loc,"name","") or item_name)
            region_name=str(getattr(getattr(loc,"parent_region",None),"name","") or "")
            sources.append({
                "item": item_name,
                "location": location_name,
                "region": region_name,
                "event": getattr(loc,"address",None) is None,
                "address": getattr(loc,"address",None),
            })
    except Exception:
        _ignored("intentional best-effort fallback")

    # Preserve goal-related generated options as a secondary hint.  These are
    # the resolved APWorld option values (normally produced from the matching
    # player YAML), not a guessed interpretation of YAML text.
    goal_options={}
    try:
        options=getattr(world,"options",None)
        for option_name in dir(options) if options is not None else ():
            if "goal" not in option_name.casefold() or option_name.startswith("_"):
                continue
            option=getattr(options,option_name,None)
            if option is None or callable(option):
                continue
            value=getattr(option,"current_key",None)
            if value is None:
                value=getattr(option,"value",option)
            if isinstance(value,(str,int,float,bool)):
                goal_options[str(option_name)]=value
    except Exception:
        _ignored("intentional best-effort fallback")

    return {
        **detail, "available":True,"satisfied":satisfied,
        "module":str(getattr(rule,"__module__","") or "unknown"),
        "consulted":trace,"missing":missing,"sources":sources,
        "goal_options":goal_options,"error":error,
    }


# /**
#  * Function: _safe_datastorage_index
#  * Purpose: Perform the safe datastorage index operation while keeping the surrounding subsystem state consistent.
#  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _safe_datastorage_index(ctx: Any) -> list[dict[str, Any]]:
    # Variable(s): `rows` (rows); named state retained for the surrounding calculation or subsequent calls.
    """Handle safe datastorage index."""
    rows=[]
    # Variable(s): `items` (items); named state retained for the surrounding calculation or subsequent calls.
    try: items=list((getattr(ctx,"stored_data",{}) or {}).items())
    # Variable(s): `items` (items); named state retained for the surrounding calculation or subsequent calls.
    except Exception: items=[]
    # Loop variable(s): `key` (key), `value` (value); each iteration represents the next value from the iterable below.
    for key,value in items:
        # Variable(s): `size` (size); named state retained for the surrounding calculation or subsequent calls.
        try: size=len(value) if hasattr(value,"__len__") else 1
        # Variable(s): `size` (size); named state retained for the surrounding calculation or subsequent calls.
        except Exception: size=-1
        rows.append({"key":str(key),"type":type(value).__name__,"size":int(size) if isinstance(size,int) else -1})
    return sorted(rows,key=lambda x:x["key"].casefold())


# /**
#  * Function: build_snapshot
#  * Purpose: Build the snapshot representation used by the surrounding subsystem.
#  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
#  * @param built: Built supplied by the caller; see type hints and call sites for domain constraints.
#  * @param ignored_names: Ignored names supplied by the caller; see type hints and call sites for domain constraints.
#  * @param sequence: Sequence supplied by the caller; see type hints and call sites for domain constraints.
#  * @param refresh_id: Refresh id supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _checked_location_names(ctx: Any, location_id_to_name: dict[int, str], checked_ids: set[int]) -> set[str]:
    """Resolve live checked IDs through both reconstructed and server datapackage names."""
    names = {str(location_id_to_name[x]) for x in checked_ids if x in location_id_to_name}
    try:
        server_location_names = getattr(ctx, "location_names", {}) or {}
        game_location_names = server_location_names.get(getattr(ctx, "game", ""), {})
        for location_id in checked_ids:
            server_name = _safe_name(game_location_names, location_id)
            if server_name and str(server_name) != str(location_id):
                names.add(str(server_name))
    except Exception:
        _ignored("intentional best-effort fallback")
    return names


def build_snapshot(ctx: Any, built: Any, *, ignored_names: set[str] | None = None, sequence: int = 0, refresh_id: int = 0) -> dict[str, Any]:
    """Return build snapshot."""
    snapshot_started=time.perf_counter()
    cancel=getattr(ctx,"_wayfinder_cancel_check",lambda:None)
    cancel()
    # Variable(s): `world` (world), `multiworld` (multiworld), `player` (player); named state retained for the surrounding calculation or subsequent calls.
    world, multiworld, player = built.world, built.multiworld, built.player
    # Variable(s): `ignored_names` (ignored names); named state retained for the surrounding calculation or subsequent calls.
    ignored_names = set(ignored_names or ())
    # Variable(s): `item_id_to_name` (item id to name); named state retained for the surrounding calculation or subsequent calls.
    item_id_to_name = dict(getattr(world, "item_id_to_name", {}) or {})
    # Variable(s): `location_id_to_name` (location id to name); named state retained for the surrounding calculation or subsequent calls.
    location_id_to_name = dict(getattr(world, "location_id_to_name", {}) or {})

    # Variable(s): `inventory` (inventory); named state retained for the surrounding calculation or subsequent calls.
    inventory = Counter()
    # Variable(s): `inventory_rows` (inventory rows); named state retained for the surrounding calculation or subsequent calls.
    inventory_rows: list[dict[str, Any]] = []
    # Variable(s): `sources` (sources); named state retained for the surrounding calculation or subsequent calls.
    sources: dict[str, tuple[str, str]] = {}
    # Loop variable(s): `item` (item); each iteration represents the next value from the iterable below.
    for item in getattr(ctx, "items_received", []) or []:
        cancel()
        # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
        name = item_id_to_name.get(getattr(item, "item", None))
        if not name:
            try:
                # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
                name = ctx.item_names[ctx.game].get(item.item)
            except Exception:
                # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
                name = None
        if not name:
            continue
        inventory[str(name)] += 1
        # Variable(s): `source_player` (source player); named state retained for the surrounding calculation or subsequent calls.
        source_player = ""
        # Variable(s): `source_location` (source location); named state retained for the surrounding calculation or subsequent calls.
        source_location = ""
        try:
            # Variable(s): `source_player` (source player); named state retained for the surrounding calculation or subsequent calls.
            source_player = str(ctx.player_names.get(item.player, item.player))
            # Variable(s): `source_location` (source location); named state retained for the surrounding calculation or subsequent calls.
            source_location = _safe_name(ctx.location_names[ctx.game], item.location)
        except Exception:
            _ignored("intentional best-effort fallback")
        sources[str(name)] = (source_player, source_location)

    # Loop variable(s): `item` (item); each iteration represents the next value from the iterable below.
    for item in (getattr(multiworld, "precollected_items", {}) or {}).get(player, []) or []:
        cancel()
        # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
        name = str(getattr(item, "name", "") or "")
        if name:
            inventory[name] += 1

    # Variable(s): `checked_ids` (checked ids); named state retained for the surrounding calculation or subsequent calls.
    checked_ids = set(getattr(ctx, "checked_locations", set()) or set())
    # Variable(s): `missing_ids` (missing ids); named state retained for the surrounding calculation or subsequent calls.
    missing_ids = set(getattr(ctx, "missing_locations", set()) or set())
    # Reconcile completed checks against both the reconstructed APWorld table and
    # the live server datapackage. Some worlds/version combinations legitimately
    # use different numeric location IDs after reconstruction; the location name
    # remains the stable identity presented by Archipelago. Without this fallback
    # a completed check can incorrectly fall through to the reachable state.
    checked_names = _checked_location_names(ctx, location_id_to_name, checked_ids)

    # Variable(s): `logic_inventory` (logic inventory); named state retained for the surrounding calculation or subsequent calls.
    logic_inventory = Counter(inventory)
    # Variable(s): `result` (result), `glitch_result` (glitch result), `glitch_item_name` (glitch item name), `logic_stats` (logic stats), `glitch_logic_stats` (glitch logic stats); named state retained for the surrounding calculation or subsequent calls.
    logic_started=time.perf_counter()
    result, glitch_result, glitch_item_name, logic_stats, glitch_logic_stats = _evaluate_logic_sets(
        built=built, multiworld=multiworld, world=world, player=player,
        inventory=logic_inventory, checked_names=checked_names, force_full=bool(refresh_id), return_stats=True,
    )
    logic_evaluation_ms=round((time.perf_counter()-logic_started)*1000.0,3)
    # Variable(s): `glitch_only_locations` (glitch only locations); named state retained for the surrounding calculation or subsequent calls.
    glitch_only_locations = set()
    # Variable(s): `glitch_only_regions` (glitch only regions); named state retained for the surrounding calculation or subsequent calls.
    glitch_only_regions = set()
    # Variable(s): `glitch_errors` (glitch errors); named state retained for the surrounding calculation or subsequent calls.
    glitch_errors: list[str] = []
    if glitch_result is not None:
        # Variable(s): `glitch_only_locations` (glitch only locations); named state retained for the surrounding calculation or subsequent calls.
        glitch_only_locations = set(glitch_result.reachable_locations) - set(result.reachable_locations)
        # Variable(s): `glitch_only_regions` (glitch only regions); named state retained for the surrounding calculation or subsequent calls.
        glitch_only_regions = set(glitch_result.reachable_regions) - set(result.reachable_regions)
        # Variable(s): `glitch_errors` (glitch errors); named state retained for the surrounding calculation or subsequent calls.
        glitch_errors = [f"Glitch logic: {x}" for x in glitch_result.errors if x not in result.errors]

    # Inventory classification is presentation-only. Prefer the APWorld's own
    # item factory and fall back to progression=True when classification cannot
    # be reconstructed safely.
    # Loop variable(s): `name` (name), `count` (count); each iteration represents the next value from the iterable below.
    for name, count in sorted(inventory.items(), key=lambda kv: kv[0].casefold()):
        cancel()
        # Variable(s): `progression` (progression); named state retained for the surrounding calculation or subsequent calls.
        progression = True
        try:
            # Variable(s): `item_obj` (item obj); named state retained for the surrounding calculation or subsequent calls.
            item_obj = world.create_item(name)
            # Variable(s): `classification` (classification); named state retained for the surrounding calculation or subsequent calls.
            classification = getattr(item_obj, "classification", 0)
            # Variable(s): `progression` (progression); named state retained for the surrounding calculation or subsequent calls.
            progression = bool(int(classification) & 0b001) or bool(int(classification) & 0b100)
        except Exception:
            _ignored("intentional best-effort fallback")
        # Variable(s): `src_player` (src player), `src_location` (src location); named state retained for the surrounding calculation or subsequent calls.
        src_player, src_location = sources.get(name, ("", ""))
        inventory_rows.append({
            "name": name, "count": int(count), "progression": progression,
            "event": name in result.events, "manual": False,
            "source_player": src_player, "source_location": src_location,
        })

    # Variable(s): `locations` (locations); named state retained for the surrounding calculation or subsequent calls.
    locations: list[dict[str, Any]] = []
    # Variable(s): `seen_ids` (seen ids); named state retained for the surrounding calculation or subsequent calls.
    seen_ids: set[int] = set()
    # Variable(s): `world_locations` (world locations); named state retained for the surrounding calculation or subsequent calls.
    world_locations = list(multiworld.get_locations(player))
    # Variable(s): `adapter_error_by_location` (adapter error by location); named state retained for the surrounding calculation or subsequent calls.
    adapter_error_by_location: dict[str, str] = {}
    # Loop variable(s): `error` (error); each iteration represents the next value from the iterable below.
    for error in result.errors:
        cancel()
        if error.startswith("Location "):
            # Variable(s): `label` (label); named state retained for the surrounding calculation or subsequent calls.
            label = error[len("Location "):].split(":", 1)[0]
            adapter_error_by_location[label] = error

    # Loop variable(s): `loc` (loc); each iteration represents the next value from the iterable below.
    # Structured rule failures also cover names containing ':' and unresolved
    # state helpers, which cannot be recovered safely by parsing error strings.
    for rule_name, detail in result.rule_details.items():
        if detail.get('error'):
            adapter_error_by_location[rule_name] = 'Logic evaluation failed: ' + detail['error']
    from wayfinder.logic.rule_explanation import uncertain_regions
    region_failures = uncertain_regions(result.reachable_regions, result.entrance_details)

    for loc in world_locations:
        cancel()
        # Variable(s): `address` (address); named state retained for the surrounding calculation or subsequent calls.
        address = getattr(loc, "address", None)
        if not isinstance(address, int):
            continue
        seen_ids.add(address)
        # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
        name = str(getattr(loc, "name", location_id_to_name.get(address, address)))
        # Variable(s): `region` (region); named state retained for the surrounding calculation or subsequent calls.
        region = str(getattr(getattr(loc, "parent_region", None), "name", "") or "")
        # Variable(s): `ignored` (ignored); named state retained for the surrounding calculation or subsequent calls.
        ignored = name in ignored_names
        if address in checked_ids or name in checked_names:
            # Checked state is authoritative and must win over reachable even when
            # the reconstructed APWorld and server datapackage use different IDs.
            # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
            status = "checked"
            # Variable(s): `reason` (reason); named state retained for the surrounding calculation or subsequent calls.
            reason = ""
        elif ignored:
            # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
            status = "ignored"
            # Variable(s): `reason` (reason); named state retained for the surrounding calculation or subsequent calls.
            reason = ""
        elif not bool(getattr(built, "exact_logic", False)):
            # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
            status = "unknown"
            # Variable(s): `reason` (reason); named state retained for the surrounding calculation or subsequent calls.
            reason = f"Authoritative logic unavailable — {getattr(built, 'logic_source', 'Default options — approximate')}."
        elif name in result.reachable_locations:
            # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
            status = "reachable"
            # Variable(s): `reason` (reason); named state retained for the surrounding calculation or subsequent calls.
            reason = ""
        elif name in adapter_error_by_location:
            # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
            status = "unknown"
            # Variable(s): `reason` (reason); named state retained for the surrounding calculation or subsequent calls.
            reason = adapter_error_by_location[name]
        elif region in region_failures and name not in glitch_only_locations and result.rule_details.get(name, {}).get('satisfied', True):
            status = 'unknown'
            reason = region_failures[region]
        elif name in glitch_only_locations:
            # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
            status = "glitched"
            # Variable(s): `reason` (reason); named state retained for the surrounding calculation or subsequent calls.
            reason = "Reachable only with the APWorld-declared glitch logic capability."
        else:
            # The location exists in this generated seed but is not currently
            # reachable under the selected APWorld logic.  The map GUI renders
            # this as the red Out of Logic state.
            # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
            status = "out_of_logic"
            # Variable(s): `reason` (reason); named state retained for the surrounding calculation or subsequent calls.
            reason = ""
        locations.append({"name": name, "status": status, "region": region, "ignored": ignored, "address": address, "unknown_reason": reason})

    # Server locations absent from our reconstructed world are never silently
    # omitted: expose them as Unknown with a precise reconstruction reason.
    # Loop variable(s): `address` (address); each iteration represents the next value from the iterable below.
    for address in sorted((checked_ids | missing_ids) - seen_ids):
        cancel()
        # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
        name = location_id_to_name.get(address)
        if not name:
            # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
            try: name = ctx.location_names[ctx.game].get(address)
            # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
            except Exception: name = str(address)
        locations.append({
            "name": str(name), "status": "checked" if address in checked_ids else "unknown",
            "region": "", "ignored": False, "address": address,
            "unknown_reason": "Server location is not present in the reconstructed APWorld graph." if address not in checked_ids else "",
        })

    # Variable(s): `event_locations` (event locations); named state retained for the surrounding calculation or subsequent calls.
    event_locations = []
    # Loop variable(s): `loc` (loc); each iteration represents the next value from the iterable below.
    for loc in world_locations:
        cancel()
        if getattr(loc, "address", None) is not None:
            continue
        # Variable(s): `item_name` (item name); named state retained for the surrounding calculation or subsequent calls.
        item_name = str(getattr(getattr(loc, "item", None), "name", "") or "")
        if item_name and item_name in result.events:
            event_locations.append(str(getattr(loc, "name", "") or item_name))

    # Variable(s): `starting_location` (starting location); named state retained for the surrounding calculation or subsequent calls.
    starting_location = ""
    # Variable(s): `starting_option` (starting option); named state retained for the surrounding calculation or subsequent calls.
    starting_option = ""
    # Variable(s): `starting_raw` (starting raw); named state retained for the surrounding calculation or subsequent calls.
    starting_raw = None
    # Variable(s): `starting_source` (starting source); named state retained for the surrounding calculation or subsequent calls.
    starting_source = ""
    try:
        from wayfinder.connection.memory import resolved_start
        # Variable(s): `found` (found); named state retained for the surrounding calculation or subsequent calls.
        found = resolved_start(getattr(ctx, "slot_data", {}) or {}, ctx.game or built.game)
        if found:
            # Variable(s): `starting_option` (starting option), `starting_raw` (starting raw), `starting_location` (starting location); named state retained for the surrounding calculation or subsequent calls.
            starting_option, starting_raw, starting_location = found
            # Variable(s): `starting_source` (starting source); named state retained for the surrounding calculation or subsequent calls.
            starting_source = "Connected slot_data"
    except Exception:
        _ignored("intentional best-effort fallback")

    # Variable(s): `signature_source` (signature source); named state retained for the surrounding calculation or subsequent calls.
    signature_source = f"{ctx.game}|{len(item_id_to_name)}|{len(location_id_to_name)}"
    # Variable(s): `signature` (signature); named state retained for the surrounding calculation or subsequent calls.
    signature = hashlib.sha256(signature_source.encode()).hexdigest()[:20]
    # Variable(s): `warnings` (warnings); named state retained for the surrounding calculation or subsequent calls.
    warnings = list(getattr(built, "warnings", []) or []) + list(result.errors) + glitch_errors
    # Variable(s): `hint_storage_key` (hint storage key), `hint_rows` (hint rows); named state retained for the surrounding calculation or subsequent calls.
    hint_storage_key, hint_rows = _live_hints(ctx, player, item_id_to_name, location_id_to_name)
    # Variable(s): `hinted_location_status` (hinted location status); named state retained for the surrounding calculation or subsequent calls.
    hinted_location_status = {h["location"]: h["status"] for h in hint_rows if h.get("location")}
    # Loop variable(s): `loc_row` (loc row); each iteration represents the next value from the iterable below.
    for loc_row in locations:
        cancel()
        # Variable(s): `hint_status` (hint status); named state retained for the surrounding calculation or subsequent calls.
        hint_status = hinted_location_status.get(loc_row.get("name", ""))
        if hint_status:
            loc_row["hinted"] = True
            loc_row["hint_status"] = hint_status
    # Variable(s): `map_page_key` (map page key), `raw_map_page_value` (raw map page value), `map_page_index` (map page index); named state retained for the surrounding calculation or subsequent calls.
    map_page_key, raw_map_page_value, map_page_index = _live_map_page_state(ctx, built)
    # Variable(s): `player_position_key` (player position key), `raw_player_position` (raw player position), `player_position_map_index` (player position map index), `player_position_icons` (player position icons); named state retained for the surrounding calculation or subsequent calls.
    player_position_key, raw_player_position, player_position_map_index, player_position_icons = _live_player_position_state(ctx, built)
    # Variable(s): `player_position_label` (player position label); named state retained for the surrounding calculation or subsequent calls.
    player_position_label = ""
    try:
        # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
        value = getattr(built, "player_position_hook", None)(raw_player_position) if callable(getattr(built, "player_position_hook", None)) and raw_player_position is not None else raw_player_position
        # Variable(s): `player_position_label` (player position label); named state retained for the surrounding calculation or subsequent calls.
        if isinstance(value, dict): player_position_label = str(value.get("room", value.get("subregion", value.get("label", ""))) or "")
    except Exception: _ignored("intentional best-effort fallback")
    # Variable(s): `goal_detail` (goal detail); named state retained for the surrounding calculation or subsequent calls.
    goal_detail = _goal_detail(multiworld, world, player, logic_inventory, result)
    # Variable(s): `area_summary` (area summary); named state retained for the surrounding calculation or subsequent calls.
    from wayfinder.logic.rule_explanation import annotate_events
    annotate_events([goal_detail, *result.rule_details.values()], {d.get('event_item') for d in result.event_details})
    area_summary: dict[str, dict[str, int]] = {}
    # Loop variable(s): `row` (row); each iteration represents the next value from the iterable below.
    for row in locations:
        cancel()
        # Variable(s): `area` (area); named state retained for the surrounding calculation or subsequent calls.
        area=str(row.get("region","") or "Other")
        # Variable(s): `bucket` (bucket); named state retained for the surrounding calculation or subsequent calls.
        bucket=area_summary.setdefault(area,{"total":0,"checked":0,"reachable":0,"hinted":0,"out_of_logic":0})
        bucket["total"]+=1; bucket["checked"]+=int(row.get("status")=="checked"); bucket["reachable"]+=int(row.get("status")=="reachable"); bucket["hinted"]+=int(bool(row.get("hinted"))); bucket["out_of_logic"]+=int(row.get("status")=="out_of_logic")
    payload = {
        "connected": bool(getattr(ctx, "slot", None)),
        "game": str(getattr(ctx, "game", "") or built.game),
        "slot_name": str(getattr(ctx, "auth", "") or built.slot_name),
        "server": str(getattr(ctx, "server_address", "") or ""),
        "starting_location": starting_location,
        "starting_location_option": starting_option,
        "starting_location_raw": starting_raw,
        "starting_location_source": starting_source,
        "inventory": inventory_rows,
        "locations": locations,
        "in_logic_regions": sorted(result.reachable_regions),
        "events": sorted(result.events),
        "event_locations": sorted(event_locations),
        "manual_items": [],
        "checked_count": len(checked_ids),
        "missing_count": len(missing_ids),
        "hinted_count": len(hint_rows),
        "hints": hint_rows,
        "entrances": sorted(result.reachable_entrances),
        "entrance_randomization_enabled": _entrance_randomization_enabled(world),
        "entrance_details": result.entrance_details,
        "event_details": result.event_details,
        "rule_details": result.rule_details,
        "unsupported_state_calls": result.unsupported_state_calls,
        "goal_detail": goal_detail,
        "area_summary": area_summary,
        "datastorage_index": _safe_datastorage_index(ctx),
        "item_name_groups": {str(k): sorted(str(x) for x in v) for k,v in (getattr(world,"item_name_groups",{}) or {}).items() if isinstance(v,(set,list,tuple,frozenset))},
        "location_name_groups": {str(k): sorted(str(x) for x in v) for k,v in (getattr(world,"location_name_groups",{}) or {}).items() if isinstance(v,(set,list,tuple,frozenset))},
        "engine_version": RUNTIME_VERSION,
        "ap_version": _ap_version(),
        "go_mode": ('Unknown' if goal_detail.get('error') else 'Yes' if goal_detail.get('satisfied') else 'No') if getattr(built, "exact_logic", False) else "N/A",
        "error": "",
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "compatibility": {
            "Logic backend": "WayFinder Native",
            "APWorld": built.game,
            "Current world": f"Loaded — {built.game}",
            "Live map switching": (f"Supported — {map_page_key}" if map_page_key else "Not advertised by this APWorld"),
            "Live player position": (f"Supported — {player_position_key}" if player_position_key else "Not advertised by this APWorld"),
            "CollectionState": "WayFinder NativeAPState",
            "Logic source": getattr(built, "logic_source", "Unknown"),
            "Logic YAML": (f"{Path(built.yaml_path).name} ✓" if getattr(built, "yaml_path", "") else "Not used" if getattr(built, "logic_source", "") == "AP slot data" else "Missing"),
            "Exact seed logic": (f"Available — {getattr(built, 'logic_source', 'authoritative reconstruction')}" if getattr(built, "exact_logic", False) else "Unavailable — generated default options are approximate"),
            "Reachable locations": (f"{len(result.reachable_locations)} reported" if getattr(built, "exact_logic", False) else "Unavailable while reconstruction is approximate"),
            "Reachable regions": (f"{len(result.reachable_regions)} reported" if getattr(built, "exact_logic", False) else "Unavailable while reconstruction is approximate"),
            "Events": (f"{len(result.events)} reported" if getattr(built, "exact_logic", False) else "Unavailable while reconstruction is approximate"),
            "Logic API": f"v{WAYFINDER_LOGIC_API}",
            "Recalculation": f"{logic_stats.mode} — {logic_stats.nodes_evaluated} evaluated / {logic_stats.nodes_reused} reused",
            "Recalculation trigger": logic_stats.trigger,
            "Recalculation fallback": logic_stats.fallback_reason or "None",
            "Hints DataStorage": f"{len(hint_rows)} hint(s) — {hint_storage_key}",
            "Glitch-only logic": (
                f"Supported via APWorld capability item {glitch_item_name!r} — {len(glitch_only_locations)} glitch-only"
                if glitch_item_name else
                "No separate APWorld glitch capability advertised; configured APWorld logic remains authoritative"
            ),
            "Manual items": "Supported",
            "Ignored locations": "Supported",
            "Logical path data": "Native reachability graph available",
            "Native explanation API": "Available",
            "Structured rule objects": "APWorld callable rules with WayFinder predicate tracing",
            "Entrance tracking": f"{len(result.entrance_details)} generated entrance(s)",
            "Location groups": f"{len(getattr(world,'location_name_groups',{}) or {})} APWorld group(s)",
            "Item groups": f"{len(getattr(world,'item_name_groups',{}) or {})} APWorld group(s)",
            "Goal detection": "Available" if goal_detail.get("available") else "Not exposed",
            "Unsupported CollectionState APIs": str(len(result.unsupported_state_calls)),
        },
        "snapshot_sequence": int(sequence),
        "runtime_id": str(getattr(ctx, "runtime_id", "")),
        "refresh_id": int(refresh_id),
        "team": int(getattr(ctx, "team", 0) or 0),
        "data_package_signature": signature,
        "logic_api_version": WAYFINDER_LOGIC_API,
        "logic_recalculation": {
            "mode": logic_stats.mode, "trigger": logic_stats.trigger,
            "nodes_evaluated": logic_stats.nodes_evaluated, "nodes_reused": logic_stats.nodes_reused,
            "affected_nodes": list(logic_stats.affected_nodes), "fallback_reason": logic_stats.fallback_reason,
            "glitch_mode": glitch_logic_stats.mode,
        },
        "reachability_available": bool(getattr(built, "exact_logic", False)),
        "events_available": bool(getattr(built, "exact_logic", False)),
        "logic_warnings": warnings,
        "event_sweep_error": "",
        "unswept_events": [],
        "invalid_rule_results": [x for x in result.errors if "non-boolean" in x],
        "event_alias_collisions": [],
        "deferred_entrance_warnings": [],
        "player_position_supported": bool(player_position_key),
        "player_position_available": bool(player_position_icons),
        "player_position_setting_key": player_position_key,
        "raw_map_datastorage_value": raw_player_position,
        "player_position_map_index": player_position_map_index,
        "player_position_icons": player_position_icons,
        "player_position_label": player_position_label,
        "map_page_setting_key": map_page_key,
        "raw_map_page_datastorage_value": raw_map_page_value,
        "map_page_index": map_page_index,
        "state_origin": "native",
        "stale": False,
        "stale_reason": "",
        "last_logic_success_epoch": time.time(),
        "current_reachable_regions": sorted(result.reachable_regions),
        "current_reachable_locations": sorted(result.reachable_locations),
        "glitch_reachable_regions": sorted(glitch_only_regions),
        "current_events": sorted(result.events),
        "normal_reachable_locations": sorted(result.reachable_locations),
        "glitch_reachable_locations": sorted(glitch_only_locations),
        "calculation_timings_ms": {},
    }
    timings=dict(getattr(built,"performance_timings_ms",{}) or {})
    timings["logic_evaluation"]=logic_evaluation_ms
    timings["snapshot_build"]=round((time.perf_counter()-snapshot_started)*1000.0,3)
    payload["calculation_timings_ms"]=timings
    return payload


# /**
#  * Function: _ap_version
#  * Purpose: Perform the ap version operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _ap_version() -> str:
    """Handle ap version."""
    try:
        from Utils import __version__
        return str(__version__)
    except Exception:
        return "unknown"


# /**
#  * Function: _go_mode
#  * Purpose: Perform the go mode operation while keeping the surrounding subsystem state consistent.
#  * @param multiworld: Multiworld supplied by the caller; see type hints and call sites for domain constraints.
#  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
#  * @param inventory: Inventory supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _go_mode(multiworld: Any, player: int, inventory: Counter[str]) -> str:
    # Completion rules are APWorld callables.  Use the same WayFinder state
    # compatibility proxy that location rules use, with all currently reachable
    # regions supplied by the fixed-point evaluation where possible.
    """Handle go mode."""
    try:
        from wayfinder.logic.apworld_adapter import NativeAPState
        # Variable(s): `state` (state); named state retained for the surrounding calculation or subsequent calls.
        state = NativeAPState(player, inventory, set(), set())
        # Variable(s): `rule` (rule); named state retained for the surrounding calculation or subsequent calls.
        rule = multiworld.completion_condition.get(player)
        return "Yes" if callable(rule) and bool(rule(state)) else "No"
    except Exception:
        return "No"
