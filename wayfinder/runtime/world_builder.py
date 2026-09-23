"""Provide world builder support."""
# /**
#  * Module: wayfinder.runtime/world_builder.py
#  * Purpose: Runtime module for world builder; bridges loaded Archipelago worlds and live server state into tracker snapshots.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

"""Reconstruct a one-player APWorld for WayFinder.

Only generic Archipelago generation primitives are used here.  No code from
``worlds.tracker`` or ``worlds.tracker_addons`` is imported or required.
"""

import json
import logging
import os
import sys
import tempfile
import time
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wayfinder.runtime.tracker_contracts import (
    DeferredEntranceMode,
    apply_deferred_entrance_contract,
    deferred_entrances_allow_partial,
)


# /**
#  * Class: BuiltWorld
#  * Purpose: Encapsulate the BuiltWorld responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class BuiltWorld:
    # Variable(s): `multiworld` (multiworld); named state retained for the surrounding calculation or subsequent calls.
    """Provide built world behavior."""
    multiworld: Any
    # Variable(s): `world` (world); named state retained for the surrounding calculation or subsequent calls.
    world: Any
    # Variable(s): `player` (player); named state retained for the surrounding calculation or subsequent calls.
    player: int
    # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
    game: str
    # Variable(s): `slot_name` (slot name); named state retained for the surrounding calculation or subsequent calls.
    slot_name: str
    # Variable(s): `warnings` (warnings); named state retained for the surrounding calculation or subsequent calls.
    warnings: list[str]
    # Variable(s): `yaml_path` (yaml path); named state retained for the surrounding calculation or subsequent calls.
    yaml_path: str = ""
    # Variable(s): `exact_logic` (exact logic); True when reconstruction is authoritative.
    exact_logic: bool = False
    # Human-readable provenance for the reconstructed option set.
    logic_source: str = "Default options — approximate"
    # Variable(s): `map_page_setting_key` (map page setting key); named state retained for the surrounding calculation or subsequent calls.
    map_page_setting_key: str = ""
    # Variable(s): `map_page_index_hook` (map page index hook); named state retained for the surrounding calculation or subsequent calls.
    map_page_index_hook: Any = None
    # Variable(s): `player_position_setting_key` (player position setting key); named state retained for the surrounding calculation or subsequent calls.
    player_position_setting_key: str = ""
    # Variable(s): `player_position_hook` (player position hook); named state retained for the surrounding calculation or subsequent calls.
    player_position_hook: Any = None
    performance_timings_ms: dict[str, float] | None = None


def _slot_data_authoritative(world_cls: Any) -> bool:
    """Whether the APWorld explicitly supports authoritative slot-data regeneration."""
    return bool(
        getattr(world_cls, "ut_can_gen_without_yaml", False)
        or callable(getattr(world_cls, "interpret_slot_data", None))
    )


def _logic_provenance(world_cls: Any, matched_yaml: Path | None) -> tuple[bool, str]:
    """Classify reconstruction authority and expose where seed options came from."""
    if matched_yaml:
        return True, "Player YAML"
    if _slot_data_authoritative(world_cls):
        return True, "AP slot data"
    return False, "Default options — approximate"


# /**
#  * Function: _write_minimal_yaml
#  * Purpose: Perform the write minimal yaml operation while keeping the surrounding subsystem state consistent.
#  * @param folder: Folder supplied by the caller; see type hints and call sites for domain constraints.
#  * @param game: Game supplied by the caller; see type hints and call sites for domain constraints.
#  * @param slot_name: Slot name supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _write_minimal_yaml(folder: Path, game: str, slot_name: str) -> Path:
    """Handle write minimal yaml."""
    folder.mkdir(parents=True, exist_ok=True)
    # Variable(s): `path` (path); named state retained for the surrounding calculation or subsequent calls.
    path = folder / "wayfinder_player.yaml"
    # JSON is valid YAML, which keeps this dependency-free and deterministic.
    path.write_text(json.dumps({"name": slot_name, "game": game, game: {}}), encoding="utf-8")
    return path



# /**
#  * Function: _yaml_declared_name
#  * Purpose: Perform the yaml declared name operation while keeping the surrounding subsystem state consistent.
#  * @param path: Path supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _yaml_declared_name(path: Path) -> str:
    """Handle yaml declared name."""
    import re
    try:
        # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    # Variable(s): `match` (match); named state retained for the surrounding calculation or subsequent calls.
    match = re.search(r"(?mi)^name\s*:\s*([^#\r\n]+)", text)
    if not match:
        return ""
    return match.group(1).strip().strip('"\'').strip()


# /**
#  * Function: _matching_player_yaml
#  * Purpose: Perform the matching player yaml operation while keeping the surrounding subsystem state consistent.
#  * @param folder: Folder supplied by the caller; see type hints and call sites for domain constraints.
#  * @param slot_name: Slot name supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _matching_player_yaml(folder: Path, slot_name: str) -> Path | None:
    """Handle matching player yaml."""
    if not folder.is_dir():
        return None
    # Variable(s): `slot` (slot); named state retained for the surrounding calculation or subsequent calls.
    slot = str(slot_name or "").strip()
    # Variable(s): `files` (files); named state retained for the surrounding calculation or subsequent calls.
    files = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.casefold() in {".yaml", ".yml"}), key=lambda p: p.name.casefold())
    # Loop variable(s): `path` (path); each iteration represents the next value from the iterable below.
    for path in files:
        if path.stem.casefold() == slot.casefold():
            return path
    # Loop variable(s): `path` (path); each iteration represents the next value from the iterable below.
    for path in files:
        if _yaml_declared_name(path).casefold() == slot.casefold():
            return path
    return None



# /**
#  * Function: _map_switch_capability
#  * Purpose: Perform the map switch capability operation while keeping the surrounding subsystem state consistent.
#  * @param world: World supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */


def _generic_map_pack_switch_key(game: str) -> str:
    """Find a converted map pack's inferred live-map DataStorage key for this game."""
    try:
        from wayfinder.storage import app_data_root
        base = app_data_root() / "map_packs"
    except Exception:
        return ""
    if not base.exists():
        return ""

    def norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()

    wanted = norm(game)
    wanted_words = {x for x in wanted.split() if len(x) > 2}
    candidates: list[tuple[int, str]] = []

    def consider(data: Any, source_text: str) -> None:
        if not isinstance(data, dict):
            return
        key = str(data.get("datastorage_key") or "").strip()
        if not key:
            return
        declared = norm(data.get("game_name") or "")
        source_norm = norm(source_text)
        score = 0
        if wanted and wanted in source_norm:
            score += 100
        if declared and (declared == wanted or declared in wanted or wanted in declared):
            score += 80
        declared_words = {x for x in declared.split() if len(x) > 2}
        score += 10 * len(wanted_words & declared_words)
        if score:
            candidates.append((score, key))

    for meta in base.rglob("wayfinder_live_map.json"):
        try:
            consider(json.loads(meta.read_text(encoding="utf-8-sig")), str(meta))
        except (OSError, ValueError, TypeError):
            continue
    for archive in base.rglob("*.zip"):
        try:
            with zipfile.ZipFile(archive) as zf:
                names = [n for n in zf.namelist() if n.endswith("wayfinder_live_map.json")]
                for name in names:
                    consider(json.loads(zf.read(name).decode("utf-8-sig")), str(archive))
        except (OSError, ValueError, TypeError, zipfile.BadZipFile, KeyError):
            continue
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]

def _map_switch_capability(world: Any) -> tuple[str, Any]:
    """Read optional APWorld-published map switching metadata.

    WayFinder uses its own native runtime.  Some APWorlds
    nevertheless publish neutral tracker metadata on their World class (most
    commonly a ``tracker_world`` mapping) that identifies a DataStorage key
    representing the player's current map/area and an optional value->map-index
    function.  Consuming that metadata lets WayFinder follow the game without
    depending on another tracker runtime.
    """
    # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
    candidates = [getattr(world, "tracker_world", None), getattr(type(world), "tracker_world", None), world, type(world)]
    # Loop variable(s): `source` (source); each iteration represents the next value from the iterable below.
    for source in candidates:
        if source is None:
            continue
        if isinstance(source, dict):
            # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
            key = source.get("map_page_setting_key", "")
            # Variable(s): `hook` (hook); named state retained for the surrounding calculation or subsequent calls.
            hook = source.get("map_page_index")
        else:
            # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
            key = getattr(source, "map_page_setting_key", "")
            # Variable(s): `hook` (hook); named state retained for the surrounding calculation or subsequent calls.
            hook = getattr(source, "map_page_index", None)
        # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
        key = str(key or "").strip()
        if key:
            return key, hook if callable(hook) else None

    # If the APWorld does not advertise map switching itself, consume generic
    # metadata inferred when a PopTracker pack was converted.  This avoids
    # game-specific exceptions: any pack using a recognisable SetNotify +
    # ActivateTab live-region pattern can provide the runtime subscription key.
    game_name = str(getattr(world, "game", "") or getattr(type(world), "game", "") or "").strip()
    inferred_key = _generic_map_pack_switch_key(game_name)
    if inferred_key:
        return inferred_key, None
    return "", None



# /**
#  * Function: _player_position_capability
#  * Purpose: Perform the player position capability operation while keeping the surrounding subsystem state consistent.
#  * @param world: World supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _player_position_capability(world: Any) -> tuple[str, Any]:
    """Read optional APWorld-published live player-position metadata.

    This is intentionally convention-based and neutral: WayFinder never imports
    WayFinder.  A game may advertise a DataStorage key plus a hook that
    translates the live value into map pixel coordinates.  Several sensible key
    names are accepted so APWorlds can expose the capability without depending on
    a WayFinder-specific base class.
    """
    # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
    candidates = [getattr(world, "tracker_world", None), getattr(type(world), "tracker_world", None), world, type(world)]
    # Variable(s): `key_names` (key names); named state retained for the surrounding calculation or subsequent calls.
    key_names = (
        "player_position_setting_key", "player_location_setting_key",
        "current_location_setting_key", "current_position_setting_key",
    )
    # Variable(s): `hook_names` (hook names); named state retained for the surrounding calculation or subsequent calls.
    hook_names = (
        "player_position", "player_position_hook", "player_location",
        "player_location_hook", "current_position",
    )
    # Loop variable(s): `source` (source); each iteration represents the next value from the iterable below.
    for source in candidates:
        if source is None:
            continue
        if isinstance(source, dict):
            # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
            key = next((source.get(name) for name in key_names if source.get(name)), "")
            # Variable(s): `hook` (hook); named state retained for the surrounding calculation or subsequent calls.
            hook = next((source.get(name) for name in hook_names if callable(source.get(name))), None)
        else:
            # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
            key = next((getattr(source, name, "") for name in key_names if getattr(source, name, "")), "")
            # Variable(s): `hook` (hook); named state retained for the surrounding calculation or subsequent calls.
            hook = next((getattr(source, name, None) for name in hook_names if callable(getattr(source, name, None))), None)
        # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
        key = str(key or "").strip()
        if key:
            return key, hook
    return "", None

# /**
#  * Function: _generation_steps
#  * Purpose: Perform the generation steps operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _install_archipelago_settings_annotation_compatibility() -> int:
    """Make Archipelago ``settings.Group`` safe on Python 3.14+.

    Archipelago 0.6.7 still accesses type annotations through *instances* in a
    number of Group helpers (for example ``self.__annotations__``). Python 3.14
    no longer guarantees that a class annotation mapping is visible through an
    instance, so even the core ``Settings`` object can raise::

        AttributeError: 'Settings' object has no attribute '__annotations__'

    Merely assigning ``SomeGroup.__annotations__ = {}`` is therefore not enough:
    the lookup that fails is the instance lookup itself.  WayFinder installs a
    tiny compatibility shim on ``Group.__getattribute__`` which redirects only
    ``__annotations__`` to the concrete class.  Every other attribute continues
    through Archipelago's original implementation, including its Path handling.

    We also ensure currently loaded Group subclasses own an annotations mapping
    so code which explicitly inspects ``SomeGroup.__dict__`` remains compatible.
    The patch is idempotent and is deliberately limited to the local WayFinder
    runtime process; no Archipelago source files are modified on disk.
    """
    try:
        import settings as ap_settings
        group_base = getattr(ap_settings, "Group", None)
    except Exception:
        return 0
    if not isinstance(group_base, type):
        return 0

    repaired = 0

    # Python 3.14 compatibility: AP 0.6.7's Group methods ask the instance for
    # ``__annotations__``.  Intercept only that special lookup and return the
    # concrete class's mapping.  Mark the wrapper so repeated world rebuilds do
    # not stack wrappers around one another.
    original_getattribute = getattr(group_base, "__getattribute__", object.__getattribute__)
    if not getattr(original_getattribute, "_wayfinder_annotations_compat", False):
        def _wayfinder_group_getattribute(instance: Any, attribute_name: str) -> Any:
            """Handle wayfinder group getattribute."""
            if attribute_name == "__annotations__":
                concrete_class = object.__getattribute__(instance, "__class__")
                try:
                    annotations = getattr(concrete_class, "__annotations__", None)
                except Exception:
                    annotations = None
                return annotations if isinstance(annotations, dict) else {}
            return original_getattribute(instance, attribute_name)

        setattr(_wayfinder_group_getattribute, "_wayfinder_annotations_compat", True)
        group_base.__getattribute__ = _wayfinder_group_getattribute
        repaired += 1

    pending = [group_base]
    seen: set[type] = set()
    while pending:
        cls = pending.pop()
        if cls in seen:
            continue
        seen.add(cls)
        try:
            pending.extend(cls.__subclasses__())
        except Exception:
            _ignored("intentional best-effort fallback")
        if "__annotations__" not in getattr(cls, "__dict__", {}):
            try:
                # Python 3.14 stores unevaluated annotations outside __dict__.
                # Materialize them before assigning, rather than erasing actual
                # settings fields (which leaves AP's YAML dumper uninitialized).
                cls.__annotations__ = dict(getattr(cls, "__annotations__", {}) or {})
            except Exception:
                continue
            repaired += 1
    return repaired



def _read_player_yaml_game_options(yaml_path: Path | None, game: str) -> dict[str, Any]:
    """Read deterministic per-game option values directly from the matched player YAML.

    Archipelago's generation parser can reject newer/custom APWorld option keys when
    its option/trigger metadata is stale relative to the loaded APWorld.  WayFinder
    still has the matched player YAML and the selected world's concrete options
    dataclass, so preserve those values here and apply them before create_regions /
    set_rules.  Server slot_data is applied afterwards and remains authoritative.

    Meta/random values are deliberately skipped because re-resolving them would not
    reproduce the original seed.
    """
    if yaml_path is None or not yaml_path.exists():
        return {}
    try:
        import yaml
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except Exception:
        logging.getLogger(__name__).warning(
            "Could not read matched player YAML for direct option preservation: %s",
            yaml_path, exc_info=True,
        )
        return {}
    section = raw.get(game) if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        return {}

    meta_strings = {
        "random", "random-low", "random-middle", "random-high",
        "random-range-low", "random-range-middle", "random-range-high",
    }
    result: dict[str, Any] = {}
    for key, value in section.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, str) and value.strip().lower() in meta_strings:
            continue
        # Weighted option dictionaries are generation recipes rather than resolved
        # values.  Leave those to Archipelago / slot_data instead of rolling again.
        if isinstance(value, dict):
            continue
        result[key] = value
    return result


def _apply_player_yaml_option_overrides(world: Any, yaml_options: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Apply deterministic values from the matched player YAML to world.options.

    This intentionally mirrors the slot-data override path but is lower priority:
    YAML first, server slot_data second.  Unknown keys are ignored, while valid
    custom APWorld options that Archipelago's generation front-end rejected are
    restored on the concrete loaded APWorld options object.
    """
    options = getattr(world, "options", None)
    if options is None or not isinstance(yaml_options, dict):
        return {}
    changed: dict[str, tuple[Any, Any]] = {}
    for key, raw_value in yaml_options.items():
        if not isinstance(key, str) or not hasattr(options, key):
            continue
        current = getattr(options, key)
        if not hasattr(current, "value"):
            continue
        old_value = getattr(current, "value", None)
        try:
            from_any = getattr(type(current), "from_any", None)
            replacement = from_any(raw_value) if callable(from_any) else None
            if replacement is not None and hasattr(replacement, "value"):
                setattr(options, key, replacement)
                new_value = replacement.value
            else:
                current.value = raw_value
                new_value = current.value
        except Exception:
            try:
                current.value = raw_value
                new_value = current.value
            except Exception:
                logging.getLogger(__name__).warning(
                    "Could not preserve player-YAML option %s=%r for %s",
                    key, raw_value, getattr(world, "game", type(world).__name__),
                    exc_info=True,
                )
                continue
        if old_value != new_value:
            changed[key] = (old_value, new_value)
    return changed

def _generation_steps():
    """Handle generation steps."""
    from worlds.AutoWorld import World
    return [name for name in (
        "generate_early", "create_regions", "create_items", "set_rules",
        "connect_entrances", "generate_basic",
    ) if hasattr(World, name)]


# /**
#  * Function: _apply_slot_data_option_overrides
#  * Purpose: Perform the apply slot data option overrides operation while keeping the surrounding subsystem state consistent.
#  * @param world: World supplied by the caller; see type hints and call sites for domain constraints.
#  * @param slot_data: Slot data supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _apply_slot_data_option_overrides(world: Any, slot_data: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Apply server-resolved option values to a reconstructed APWorld.

    Player YAMLs may contain Archipelago meta-values such as ``random``. Running
    generation again resolves those meta-values a second time and can therefore
    produce a different local world (for example a different starting area).
    ``Connected.slot_data`` is generated from the *real* seed and many APWorlds
    expose the already-resolved option values there.  Those values must win over
    the freshly parsed YAML before any regions or rules are generated.

    Unknown slot-data keys are deliberately ignored; only actual option fields on
    the selected world's options dataclass are eligible.
    """
    # Variable(s): `options` (options); named state retained for the surrounding calculation or subsequent calls.
    options = getattr(world, "options", None)
    if options is None or not isinstance(slot_data, dict):
        return {}

    # Variable(s): `changed` (changed); named state retained for the surrounding calculation or subsequent calls.
    changed: dict[str, tuple[Any, Any]] = {}
    # Loop variable(s): `key` (key), `raw_value` (raw value); each iteration represents the next value from the iterable below.
    for key, raw_value in slot_data.items():
        if not isinstance(key, str) or not hasattr(options, key):
            continue
        # Variable(s): `current` (current); named state retained for the surrounding calculation or subsequent calls.
        current = getattr(options, key)
        if not hasattr(current, "value"):
            continue
        # Variable(s): `old_value` (old value); named state retained for the surrounding calculation or subsequent calls.
        old_value = getattr(current, "value", None)
        try:
            # Rebuild through the option class where possible so container-based
            # options (OptionSet/OptionList/etc.) retain their expected value type.
            # Variable(s): `from_any` (from any); named state retained for the surrounding calculation or subsequent calls.
            from_any = getattr(type(current), "from_any", None)
            # Variable(s): `replacement` (replacement); named state retained for the surrounding calculation or subsequent calls.
            replacement = from_any(raw_value) if callable(from_any) else None
            if replacement is not None and hasattr(replacement, "value"):
                setattr(options, key, replacement)
                # Variable(s): `new_value` (new value); named state retained for the surrounding calculation or subsequent calls.
                new_value = replacement.value
            else:
                current.value = raw_value
                # Variable(s): `new_value` (new value); named state retained for the surrounding calculation or subsequent calls.
                new_value = current.value
        except Exception:
            # Slot data originates from the APWorld itself.  If a custom option
            # cannot be reconstructed through from_any, preserve the original
            # option object and set its serialized value directly as a fallback.
            try:
                current.value = raw_value
                # Variable(s): `new_value` (new value); named state retained for the surrounding calculation or subsequent calls.
                new_value = current.value
            except Exception:
                logging.getLogger(__name__).warning(
                    "Could not apply slot-data option override %s=%r for %s",
                    key, raw_value, getattr(world, "game", type(world).__name__),
                    exc_info=True,
                )
                continue
        if old_value != new_value:
            changed[key] = (old_value, new_value)
    return changed


# /**
#  * Function: _build_multiworld
#  * Purpose: Build the multiworld representation used by the surrounding subsystem.
#  * @param args: Args supplied by the caller; see type hints and call sites for domain constraints.
#  * @param seed: Seed supplied by the caller; see type hints and call sites for domain constraints.
#  * @param game: Game supplied by the caller; see type hints and call sites for domain constraints.
#  * @param slot_data: Slot data supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _build_multiworld(args: Any, seed: Any, *, game: str, slot_data: dict[str, Any], yaml_options: dict[str, Any] | None = None, timings: dict[str, float] | None = None) -> Any:
    """Handle build multiworld."""
    from BaseClasses import CollectionState, MultiWorld
    from worlds import AutoWorld
    from worlds.generic.Rules import exclusion_rules

    # Variable(s): `multiworld` (multiworld); named state retained for the surrounding calculation or subsequent calls.
    multiworld = MultiWorld(1)
    multiworld.generation_is_fake = True
    multiworld.re_gen_passthrough = {game: slot_data}
    # Keep the tracker-facing string enum and Archipelago CollectionState
    # boolean derived from the same validated mode so the contracts cannot drift.
    deferred_entrance_mode = apply_deferred_entrance_contract(
        multiworld, DeferredEntranceMode.DISABLED
    )
    multiworld.set_seed(seed, getattr(args, "race", False), str(getattr(args, "outputname", "") or "") or None)
    multiworld.game = dict(args.game)
    multiworld.player_name = dict(args.name)
    multiworld.set_options(args)

    # IMPORTANT: the YAML is the generation recipe, but it can contain meta
    # choices such as `random`.  Re-parsing it can select different values from
    # the original seed.  The connected server's slot_data contains the resolved
    # values for APWorlds that expose them, so apply those before create_regions,
    # set_rules, connect_entrances, etc.
    # Variable(s): `world` (world); named state retained for the surrounding calculation or subsequent calls.
    world = multiworld.worlds[1]

    # Preserve deterministic values from the exact matched player YAML before any
    # APWorld generation hooks run.  This repairs custom/new option keys that the
    # Archipelago generation front-end may have rejected as unknown.
    yaml_applied = _apply_player_yaml_option_overrides(world, dict(yaml_options or {}))
    if yaml_applied:
        logging.getLogger(__name__).info(
            "Preserved %d matched player-YAML option value(s) for %s: %s",
            len(yaml_applied), game, ", ".join(
                f"{name}={new!r}" for name, (_old, new) in sorted(yaml_applied.items())
            ),
        )

    # Variable(s): `applied` (applied); named state retained for the surrounding calculation or subsequent calls.
    applied = _apply_slot_data_option_overrides(world, slot_data)
    if applied:
        logging.getLogger(__name__).info(
            "Applied %d server-resolved slot-data option override(s) for %s: %s",
            len(applied), game, ", ".join(
                f"{name}={new!r}" for name, (_old, new) in sorted(applied.items())
            ),
        )

    multiworld.state = CollectionState(
        multiworld, deferred_entrances_allow_partial(deferred_entrance_mode)
    )

    # Loop variable(s): `step` (step); each iteration represents the next value from the iterable below.
    for step in _generation_steps():
        step_started=time.perf_counter()
        AutoWorld.call_all(multiworld, step)
        if timings is not None:
            timings[f"generation.{step}"]=round((time.perf_counter()-step_started)*1000.0,3)
        if step == "set_rules":
            # Loop variable(s): `player` (player); each iteration represents the next value from the iterable below.
            for player in multiworld.player_ids:
                # Variable(s): `world` (world); named state retained for the surrounding calculation or subsequent calls.
                world = multiworld.worlds[player]
                # Variable(s): `excluded` (excluded); named state retained for the surrounding calculation or subsequent calls.
                excluded = getattr(getattr(world, "options", None), "exclude_locations", None)
                # Variable(s): `values` (values); named state retained for the surrounding calculation or subsequent calls.
                values = getattr(excluded, "value", set()) if excluded is not None else set()
                exclusion_rules(multiworld, player, values)
        if step == "generate_basic":
            break
    return multiworld


# /**
#  * Function: build_world
#  * Purpose: Build the world representation used by the surrounding subsystem.
#  * @param game: Game supplied by the caller; see type hints and call sites for domain constraints.
#  * @param slot_name: Slot name supplied by the caller; see type hints and call sites for domain constraints.
#  * @param slot_data: Slot data supplied by the caller; see type hints and call sites for domain constraints.
#  * @param player_files_path: Player files path supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */


def _slot_data_entrance_mappings(slot_data: dict[str, Any]) -> list[tuple[str, dict[str, str]]]:
    """Return conservative seed-specific entrance mappings exposed by Connected slot_data.

    APWorlds use different field names, so WayFinder does not hard-code a game.  A
    mapping is considered entrance topology only when its container key itself says
    entrance/portal/warp and its contents are string -> string pairs.  The mapping is
    still validated against the reconstructed AP graph before it can change anything.
    """
    found: list[tuple[str, dict[str, str]]] = []
    if not isinstance(slot_data, dict):
        return found
    semantic = ("entrance", "portal", "warp")
    for key, value in slot_data.items():
        label = str(key or "")
        folded = label.casefold().replace("-", "_").replace(" ", "_")
        if not any(token in folded for token in semantic) or not isinstance(value, dict):
            continue
        pairs = {str(k): str(v) for k, v in value.items() if isinstance(k, str) and isinstance(v, str) and k and v}
        if pairs:
            found.append((label, pairs))
    return found


def _apply_seed_entrance_topology(multiworld: Any, player: int, slot_data: dict[str, Any]) -> list[str]:
    """Overlay authoritative seed entrance destinations from Connected slot_data.

    Reconstruction may execute an APWorld's entrance randomizer again.  That produces
    a valid graph, but not necessarily *this seed's* graph.  When the server explicitly
    supplies an entrance mapping, match it to real AP Entrance and Region objects and
    reconnect only exact, unambiguous pairs.  Unknown/unmatched data is ignored rather
    than guessed, making this safe for APWorlds with unrelated entrance metadata.
    """
    candidates = _slot_data_entrance_mappings(slot_data)
    if not candidates:
        return []
    regions = {str(getattr(r, "name", "") or ""): r for r in getattr(multiworld, "regions", []) if getattr(r, "player", player) == player}
    entrances = []
    for region in getattr(multiworld, "regions", []):
        if getattr(region, "player", player) != player:
            continue
        entrances.extend(list(getattr(region, "exits", []) or []))

    # APWorlds often render the destination into the runtime Entrance name, e.g.
    # "Dungeon Entrance on X -> Wind Temple".  Slot data normally keys the stable
    # entrance identity, so accept that exact prefix in addition to the full name.
    by_identity: dict[str, list[Any]] = {}
    for entrance in entrances:
        full = str(getattr(entrance, "name", "") or "")
        identities = {full}
        if " -> " in full:
            identities.add(full.split(" -> ", 1)[0])
        for identity in identities:
            by_identity.setdefault(identity, []).append(entrance)

    applied: list[str] = []
    seen_objects: set[int] = set()
    for field, mapping in candidates:
        for entrance_name, target_name in mapping.items():
            matches = by_identity.get(entrance_name, [])
            target = regions.get(target_name)
            if len(matches) != 1 or target is None:
                continue
            entrance = matches[0]
            marker = id(entrance)
            if marker in seen_objects:
                continue
            seen_objects.add(marker)
            previous = str(getattr(getattr(entrance, "connected_region", None), "name", "") or "")
            if previous != target_name:
                # BaseClasses.Entrance.connect simply replaces connected_region in
                # supported AP versions; assignment is the most version-tolerant form.
                entrance.connected_region = target
            applied.append(f"{entrance_name}: {previous or '?'} -> {target_name} [{field}]")
    return applied


def _install_world_rule_safety_guards(world: Any, multiworld: Any, player: int = 1) -> list[str]:
    """Install narrow safety guards for APWorld rules known to be under-reconstructed.

    These guards never make logic more permissive. They only preserve requirements
    that are explicitly enabled in the generated world's resolved options when an
    APWorld helper/rule-builder combination can otherwise collapse to a permissive
    entrance rule in tracker reconstruction.
    """
    installed: list[str] = []
    game = str(getattr(world, "game", "") or "")
    if game != "Pokemon FireRed and LeafGreen":
        return installed

    options = getattr(world, "options", None)
    route12_boulders = getattr(options, "route_12_boulders", None) if options is not None else None
    if not bool(getattr(route12_boulders, "value", route12_boulders)):
        return installed

    removed_badges = set(getattr(getattr(options, "remove_badge_requirement", None), "value", set()) or set())
    gated_entrances = {
        "Route 11 East Exit",
        "Lavender Town South Exit",
        "Route 12 West Exit",
        "Route 12 North Exit",
        "Route 12 South Exit",
        "Route 13 North Exit",
    }

    def strength_gate(state: Any) -> bool:
        """Handle strength gate."""
        required = ("HM04 Strength", "TM Case", "Teach Strength")
        if not all(bool(state.has(item, player)) for item in required):
            return False
        if "Strength" not in removed_badges and not bool(state.has("Rainbow Badge", player)):
            return False
        return True

    for entrance_name in sorted(gated_entrances):
        try:
            entrance = multiworld.get_entrance(entrance_name, player)
        except Exception:
            continue
        original_rule = getattr(entrance, "access_rule", None)
        if not callable(original_rule):
            original_rule = lambda _state: True

        def guarded_rule(state: Any, _original=original_rule) -> bool:
            """Handle guarded rule."""
            return bool(_original(state)) and strength_gate(state)

        entrance.access_rule = guarded_rule
        installed.append(entrance_name)

    return installed

def build_world(game: str, slot_name: str, slot_data: dict[str, Any], *, player_files_path: str | os.PathLike[str] | None = None) -> BuiltWorld:
    """Build the connected game as a fake one-player generation.

    Slot-data-aware worlds normally reconstruct from ``re_gen_passthrough`` or
    ``interpret_slot_data``.  Worlds that genuinely require the player's YAML
    can use ``player_files_path``; otherwise a minimal default-options YAML is
    supplied and a compatibility warning is returned.
    """
    from Generate import main as generate_main, mystery_argparse
    from worlds.AutoWorld import AutoWorldRegister

    repaired_settings_groups = _install_archipelago_settings_annotation_compatibility()
    if repaired_settings_groups:
        logging.getLogger(__name__).info(
            "Applied Archipelago Settings annotation compatibility to %d group class(es).",
            repaired_settings_groups,
        )

    if game not in AutoWorldRegister.world_types:
        # Variable(s): `known` (known); named state retained for the surrounding calculation or subsequent calls.
        known = ", ".join(sorted(AutoWorldRegister.world_types)[:20])
        raise RuntimeError(f"APWorld for {game!r} is not loaded. Known games include: {known}")

    # Variable(s): `world_cls` (world cls); named state retained for the surrounding calculation or subsequent calls.
    world_cls = AutoWorldRegister.world_types[game]
    # Variable(s): `warnings` (warnings); named state retained for the surrounding calculation or subsequent calls.
    warnings: list[str] = []
    performance_timings_ms: dict[str, float] = {}
    # Variable(s): `slot_aware` (slot aware); named state retained for the surrounding calculation or subsequent calls.
    slot_aware = _slot_data_authoritative(world_cls)

    # Variable(s): `old_argv` (old argv); named state retained for the surrounding calculation or subsequent calls.
    old_argv = sys.argv[:]
    try:
        sys.argv = sys.argv[:1]
        # Variable(s): `td` (td); named state retained for the surrounding calculation or subsequent calls.
        with tempfile.TemporaryDirectory(prefix="wayfinder_native_world_") as td:
            # Variable(s): `temp` (temp); named state retained for the surrounding calculation or subsequent calls.
            temp = Path(td)
            # Variable(s): `chosen_folder` (chosen folder); named state retained for the surrounding calculation or subsequent calls.
            chosen_folder: Path
            # Variable(s): `supplied` (supplied); named state retained for the surrounding calculation or subsequent calls.
            supplied = Path(player_files_path).expanduser() if player_files_path else None
            # Variable(s): `matched_yaml` (matched yaml); named state retained for the surrounding calculation or subsequent calls.
            yaml_started=time.perf_counter()
            matched_yaml = _matching_player_yaml(supplied, slot_name) if supplied else None
            performance_timings_ms["yaml_lookup"]=round((time.perf_counter()-yaml_started)*1000.0,3)
            if matched_yaml:
                # Generate from only the connected slot's exact YAML. This avoids
                # unrelated player files changing multi count or option selection.
                # Variable(s): `chosen_folder` (chosen folder); named state retained for the surrounding calculation or subsequent calls.
                chosen_folder = temp / "selected_player"
                chosen_folder.mkdir(parents=True, exist_ok=True)
                # Variable(s): `selected_copy` (selected copy); named state retained for the surrounding calculation or subsequent calls.
                selected_copy = chosen_folder / matched_yaml.name
                selected_copy.write_bytes(matched_yaml.read_bytes())
            else:
                # A minimal YAML is still required by Archipelago's generation
                # entrypoint, but it is only a bootstrap container.  Slot-aware
                # APWorlds can replace those defaults authoritatively from the
                # connected slot data during reconstruction.
                chosen_folder = temp
                _write_minimal_yaml(chosen_folder, game, slot_name)
                if not slot_aware:
                    warnings.append(
                        f"Approximate logic — player YAML missing for slot {slot_name!r} and this APWorld does not advertise authoritative slot-data reconstruction. "
                        "WayFinder will keep connection/check-state tracking active, but reachability/pathfinding uses generated default options until the matching YAML is synced or supplied."
                    )

            # Variable(s): `args` (args); named state retained for the surrounding calculation or subsequent calls.
            args = mystery_argparse()
            args.player_files_path = str(chosen_folder)
            args.skip_output = True
            args.multi = 0
            try:
                # Variable(s): `g_args` (g args), `seed` (seed); named state retained for the surrounding calculation or subsequent calls.
                generate_started=time.perf_counter()
                g_args, seed = generate_main(args)
                performance_timings_ms["generate_main"]=round((time.perf_counter()-generate_started)*1000.0,3)
            except Exception as exc:
                if chosen_folder != temp:
                    raise
                raise RuntimeError(f"Archipelago generation setup failed for {game}: {exc}") from exc

            # Select the connected slot if a supplied folder contains multiple YAMLs.
            # Variable(s): `slot_id` (slot id); named state retained for the surrounding calculation or subsequent calls.
            slot_id = None
            # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
            names = getattr(g_args, "name", {}) or {}
            # Loop variable(s): `pid` (process identifier), `name` (name); each iteration represents the next value from the iterable below.
            for pid, name in names.items():
                if str(name) == str(slot_name):
                    # Variable(s): `slot_id` (slot id); named state retained for the surrounding calculation or subsequent calls.
                    slot_id = pid
                    break
            if slot_id is None:
                # Variable(s): `slot_id` (slot id); named state retained for the surrounding calculation or subsequent calls.
                slot_id = next(iter(names), 1)

            # Move the selected generated option values into player 1.
            # Loop variable(s): `option_name` (option name), `option_value` (option value); each iteration represents the next value from the iterable below.
            for option_name, option_value in list(vars(g_args).items()):
                if isinstance(option_value, dict) and slot_id in option_value:
                    setattr(g_args, option_name, {1: option_value[slot_id]})
            g_args.multi = 1
            g_args.game = {1: game}
            g_args.name = {1: slot_name}
            g_args.player_ids = {1}

            # Variable(s): `multiworld` (multiworld); named state retained for the surrounding calculation or subsequent calls.
            direct_yaml_options = _read_player_yaml_game_options(matched_yaml, game) if matched_yaml else {}
            multiworld_started=time.perf_counter()
            multiworld = _build_multiworld(
                g_args, seed, game=game, slot_data=dict(slot_data or {}), yaml_options=direct_yaml_options, timings=performance_timings_ms
            )
            performance_timings_ms["multiworld_construction"]=round((time.perf_counter()-multiworld_started)*1000.0,3)
            performance_timings_ms["rule_reconstruction"]=performance_timings_ms.get("generation.set_rules",0.0)
            # Variable(s): `world` (world); named state retained for the surrounding calculation or subsequent calls.
            world = multiworld.worlds[1]
            installed_rule_guards = _install_world_rule_safety_guards(world, multiworld, 1)
            seed_entrance_overrides = _apply_seed_entrance_topology(multiworld, 1, dict(slot_data or {}))
            if seed_entrance_overrides:
                logging.getLogger(__name__).info(
                    "Applied %d authoritative seed entrance connection(s) from Connected slot_data for %s: %s",
                    len(seed_entrance_overrides), game, "; ".join(seed_entrance_overrides),
                )
            if installed_rule_guards:
                logging.getLogger(__name__).info(
                    "Installed %d conservative APWorld rule guard(s) for %s: %s",
                    len(installed_rule_guards), game, ", ".join(installed_rule_guards),
                )

            # A number of worlds use interpret_slot_data to prepare regeneration
            # passthrough.  Give them one explicit post-construction opportunity
            # and rebuild if they return replacement passthrough data.
            # Variable(s): `interpret` (interpret); named state retained for the surrounding calculation or subsequent calls.
            interpret = getattr(world, "interpret_slot_data", None)
            if callable(interpret):
                try:
                    # Variable(s): `replacement` (replacement); named state retained for the surrounding calculation or subsequent calls.
                    replacement = interpret(dict(slot_data or {}))
                except TypeError:
                    # Variable(s): `replacement` (replacement); named state retained for the surrounding calculation or subsequent calls.
                    replacement = None
                if replacement:
                    multiworld.re_gen_passthrough = {game: replacement}
            # Variable(s): `map_key` (map key), `map_index_hook` (map index hook); named state retained for the surrounding calculation or subsequent calls.
            map_key, map_index_hook = _map_switch_capability(world)
            # Variable(s): `position_key` (position key), `position_hook` (position hook); named state retained for the surrounding calculation or subsequent calls.
            position_key, position_hook = _player_position_capability(world)
            authoritative, logic_source = _logic_provenance(world_cls, matched_yaml)
            return BuiltWorld(
                multiworld, world, 1, game, slot_name, warnings,
                yaml_path=str(matched_yaml) if matched_yaml else "",
                exact_logic=authoritative,
                logic_source=logic_source,
                map_page_setting_key=map_key,
                map_page_index_hook=map_index_hook,
                player_position_setting_key=position_key,
                player_position_hook=position_hook,
                performance_timings_ms=dict(performance_timings_ms),
            )
    finally:
        sys.argv = old_argv
