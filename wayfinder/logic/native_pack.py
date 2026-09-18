# /**
#  * Module: wayfinder.logic/native_pack.py
#  * Purpose: Core tracker module for native pack; contains format-neutral or APWorld logic used to calculate WayFinder state.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

"""Loader for the first WayFinder-native tracker definition format.

The JSON format intentionally represents logic as data so the GUI can explain
requirements. APWorld adapters can also construct the same model directly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import EntranceDefinition, EventDefinition, LocationDefinition, RegionDefinition, TrackerDefinition
from .rules import Rule, all_of, any_of, always, event, item, never, not_, option, state_value


# /**
#  * Function: parse_rule
#  * Purpose: Parse rule input into a normalized internal representation.
#  * @param raw_value: Raw value supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def parse_rule(raw_value: Any) -> Rule:
    """Return parse rule."""
    if raw_value is None or raw_value is True:
        return always()
    if raw_value is False:
        return never()
    if isinstance(raw_value, str):
        return item(raw_value)
    if not isinstance(raw_value, dict):
        raise ValueError(f"Unsupported rule value: {raw_value!r}")
    if "item" in raw_value:
        return item(str(raw_value["item"]), int(raw_value.get("count", 1)))
    if "event" in raw_value:
        return event(str(raw_value["event"]))
    if "option" in raw_value:
        return option(str(raw_value["option"]), raw_value.get("equals", True))
    if "state" in raw_value:
        return state_value(str(raw_value["state"]), raw_value.get("equals", True))
    if "all" in raw_value:
        return all_of(*(parse_rule(value) for value in raw_value["all"]))
    if "any" in raw_value:
        return any_of(*(parse_rule(value) for value in raw_value["any"]))
    if "not" in raw_value:
        return not_(parse_rule(raw_value["not"]))
    raise ValueError(f"Unknown rule object: {raw_value!r}")


# /**
#  * Function: load_definition
#  * Purpose: Load definition data and convert it into the form expected by WayFinder.
#  * @param path: Path supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def load_definition(path: str | Path) -> TrackerDefinition:
    # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
    """Return load definition."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    # Variable(s): `definition` (definition); named state retained for the surrounding calculation or subsequent calls.
    definition = TrackerDefinition(game=str(data["game"]), schema_version=int(data.get("schema_version", 1)))
    # Loop variable(s): `raw_value` (raw value); each iteration represents the next value from the iterable below.
    for raw_value in data.get("regions", []):
        # Variable(s): `region` (region); named state retained for the surrounding calculation or subsequent calls.
        region = RegionDefinition(str(raw_value["name"]), bool(raw_value.get("starting", False)))
        definition.regions[region.name] = region
    # Loop variable(s): `raw_value` (raw value); each iteration represents the next value from the iterable below.
    for raw_value in data.get("entrances", []):
        definition.entrances.append(EntranceDefinition(
            name=str(raw_value["name"]), source_region=str(raw_value["from"]),
            target_region=(None if raw_value.get("to") is None else str(raw_value.get("to"))),
            rule=parse_rule(raw_value.get("rule")), deferred_key=str(raw_value.get("deferred_key", "")),
        ))
    # Loop variable(s): `raw_value` (raw value); each iteration represents the next value from the iterable below.
    for raw_value in data.get("locations", []):
        # Variable(s): `location` (location); named state retained for the surrounding calculation or subsequent calls.
        location = LocationDefinition(str(raw_value["name"]), str(raw_value["region"]), parse_rule(raw_value.get("rule")), raw_value.get("address"), bool(raw_value.get("progression", False)))
        definition.locations[location.name] = location
    # Loop variable(s): `raw_value` (raw value); each iteration represents the next value from the iterable below.
    for raw_value in data.get("events", []):
        # Variable(s): `ev` (ev); named state retained for the surrounding calculation or subsequent calls.
        ev = EventDefinition(str(raw_value["name"]), str(raw_value["region"]), parse_rule(raw_value.get("rule")), str(raw_value.get("grants", "")))
        definition.events[ev.name] = ev
    # Variable(s): `errors` (errors); named state retained for the surrounding calculation or subsequent calls.
    errors = definition.validate()
    if errors:
        raise ValueError("Invalid native tracker pack: " + "; ".join(errors))
    return definition
