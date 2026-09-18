"""Provide engine support."""
# /**
#  * Module: wayfinder.logic/engine.py
#  * Purpose: Core tracker module for engine; contains format-neutral or APWorld logic used to calculate WayFinder state.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping

from .model import EngineSnapshot, LocationResult, TrackerDefinition, TrackerInput
from .logic_api import WAYFINDER_LOGIC_API, LogicSnapshot, LocationState, EntranceState, RecalculationStats


# /**
#  * Class: _Context
#  * Purpose: Encapsulate the Context responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class _Context:
    # Variable(s): `inventory` (inventory); named state retained for the surrounding calculation or subsequent calls.
    """Provide context behavior."""
    inventory: Mapping[str, int]
    # Variable(s): `events` (events); named state retained for the surrounding calculation or subsequent calls.
    events: set[str]
    # Variable(s): `options` (options); named state retained for the surrounding calculation or subsequent calls.
    options: Mapping[str, Any]
    # Variable(s): `state_values` (state values); named state retained for the surrounding calculation or subsequent calls.
    state_values: Mapping[str, Any]


# /**
#  * Class: LogicEngine
#  * Purpose: Encapsulate the LogicEngine responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
class LogicEngine:
    """WayFinder's format-neutral reachability engine.

    Evaluation is deliberately fixed-point based: discover regions, sweep
    reachable events, then repeat until neither changes.  This is the behaviour
    we need from a tracker, but it is now owned by UB and produces reason trees
    instead of opaque booleans.
    """

    # Constant(s): `MAX_ITERATIONS`; shared configuration value(s) intentionally kept stable within this module.
    MAX_ITERATIONS = 512

    # /**
    #  * Function: __init__
    #  * Purpose: Initialize this object and establish its required runtime state.
    #  * @param definition: Definition supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def __init__(self, definition: TrackerDefinition):
        """Handle init."""
        self.definition = definition
        # Variable(s): `errors` (errors); named state retained for the surrounding calculation or subsequent calls.
        errors = definition.validate()
        if errors:
            raise ValueError("Invalid tracker definition: " + "; ".join(errors))

    # /**
    #  * Function: evaluate
    #  * Purpose: Perform the evaluate operation while keeping the surrounding subsystem state consistent.
    #  * @param tracker_input: Tracker input supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def evaluate(self, tracker_input: TrackerInput | None = None) -> EngineSnapshot:
        # Variable(s): `source_region_name` (source region name); named state retained for the surrounding calculation or subsequent calls.
        """Handle evaluate."""
        source_region_name = tracker_input or TrackerInput()
        # Variable(s): `inventory` (inventory); named state retained for the surrounding calculation or subsequent calls.
        inventory = Counter(source_region_name.inventory)
        # Variable(s): `events` (events); named state retained for the surrounding calculation or subsequent calls.
        events = set(source_region_name.known_events)
        # Variable(s): `reachable_regions` (reachable regions); named state retained for the surrounding calculation or subsequent calls.
        reachable_regions = {name for name, region in self.definition.regions.items() if region.starting}
        # Variable(s): `reachable_entrances` (reachable entrances); named state retained for the surrounding calculation or subsequent calls.
        reachable_entrances: set[str] = set()
        # Variable(s): `unresolved_entrances` (unresolved entrances); named state retained for the surrounding calculation or subsequent calls.
        unresolved_entrances: set[str] = set()
        # Variable(s): `warnings` (warnings); named state retained for the surrounding calculation or subsequent calls.
        warnings: list[str] = []

        # Loop variable(s): `iteration` (iteration); each iteration represents the next value from the iterable below.
        for iteration in range(1, self.MAX_ITERATIONS + 1):
            # Variable(s): `changed` (changed); named state retained for the surrounding calculation or subsequent calls.
            changed = False
            # Variable(s): `evaluation_context` (evaluation context); named state retained for the surrounding calculation or subsequent calls.
            evaluation_context = _Context(inventory, events, source_region_name.options, source_region_name.state_values)

            # Region/entrance traversal. Iterate locally because one newly opened
            # region can reveal another entrance in the same event-sweep pass.
            # Variable(s): `traversal_changed` (traversal changed); named state retained for the surrounding calculation or subsequent calls.
            traversal_changed = True
            while traversal_changed:
                # Variable(s): `traversal_changed` (traversal changed); named state retained for the surrounding calculation or subsequent calls.
                traversal_changed = False
                # Loop variable(s): `entrance` (entrance); each iteration represents the next value from the iterable below.
                for entrance in self.definition.entrances:
                    if entrance.source_region not in reachable_regions:
                        continue
                    # Variable(s): `result` (result); named state retained for the surrounding calculation or subsequent calls.
                    result = entrance.rule.evaluate(evaluation_context)
                    if result.satisfied is not True:
                        continue
                    reachable_entrances.add(entrance.name)
                    # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
                    target = source_region_name.entrance_connections.get(entrance.name, entrance.target_region)
                    if target is None:
                        unresolved_entrances.add(entrance.name)
                        continue
                    unresolved_entrances.discard(entrance.name)
                    if target not in self.definition.regions:
                        warnings.append(f"Entrance {entrance.name!r} resolved to unknown region {target!r}")
                        continue
                    if target not in reachable_regions:
                        reachable_regions.add(target)
                        # Variable(s): `traversal_changed` (traversal changed); named state retained for the surrounding calculation or subsequent calls.
                        traversal_changed = True
                        # Variable(s): `changed` (changed); named state retained for the surrounding calculation or subsequent calls.
                        changed = True

            # Event sweep. Event grants are kept separate from item inventory so
            # adapters can preserve AP event semantics rather than faking items.
            # Loop variable(s): `event` (event); each iteration represents the next value from the iterable below.
            for event in self.definition.events.values():
                if event.region not in reachable_regions or event.granted_event in events:
                    continue
                # Variable(s): `result` (result); named state retained for the surrounding calculation or subsequent calls.
                result = event.rule.evaluate(evaluation_context)
                if result.satisfied is True:
                    events.add(event.granted_event)
                    # Variable(s): `changed` (changed); named state retained for the surrounding calculation or subsequent calls.
                    changed = True

            if not changed:
                break
        else:
            warnings.append(f"Logic failed to stabilize after {self.MAX_ITERATIONS} iterations")
            # Variable(s): `iteration` (iteration); named state retained for the surrounding calculation or subsequent calls.
            iteration = self.MAX_ITERATIONS

        # Variable(s): `evaluation_context` (evaluation context); named state retained for the surrounding calculation or subsequent calls.
        evaluation_context = _Context(inventory, events, source_region_name.options, source_region_name.state_values)
        # Variable(s): `locations` (locations); named state retained for the surrounding calculation or subsequent calls.
        locations: dict[str, LocationResult] = {}
        # Loop variable(s): `location` (location); each iteration represents the next value from the iterable below.
        for location in self.definition.locations.values():
            # Variable(s): `checked` (checked); named state retained for the surrounding calculation or subsequent calls.
            checked = location.name in source_region_name.checked_locations
            if checked:
                locations[location.name] = LocationResult(location.name, location.region, "checked", True)
                continue
            if location.name in source_region_name.ignored_locations:
                locations[location.name] = LocationResult(location.name, location.region, "ignored", False)
                continue
            if location.region not in reachable_regions:
                locations[location.name] = LocationResult(location.name, location.region, "out_of_logic", False)
                continue
            # Variable(s): `result` (result); named state retained for the surrounding calculation or subsequent calls.
            result = location.rule.evaluate(evaluation_context)
            if result.satisfied is True:
                # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
                status = "reachable"
                # Variable(s): `reason` (reason); named state retained for the surrounding calculation or subsequent calls.
                reason = ""
            elif result.satisfied is False:
                # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
                status = "out_of_logic"
                # Variable(s): `reason` (reason); named state retained for the surrounding calculation or subsequent calls.
                reason = ""
            else:
                # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
                status = "unknown"
                # Variable(s): `reason` (reason); named state retained for the surrounding calculation or subsequent calls.
                reason = result.error or result.detail or "rule could not be resolved"
            locations[location.name] = LocationResult(location.name, location.region, status, False, result, reason)

        return EngineSnapshot(
            game=self.definition.game,
            reachable_regions=reachable_regions,
            reachable_entrances=reachable_entrances,
            unresolved_entrances=unresolved_entrances,
            events=events,
            locations=locations,
            warnings=list(dict.fromkeys(warnings)),
            iterations=iteration,
        )
    # /**
    #  * Function: evaluate_api
    #  * Purpose: Evaluate API object against the current tracker state.
    #  * @param tracker_input: Tracker input supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def evaluate_api(self, tracker_input: TrackerInput | None = None) -> LogicSnapshot:
        """Evaluate and return the stable WayFinder Logic API v1 snapshot.

        GUI/runtime consumers should prefer this interface over engine-private
        structures so a future evaluator can be replaced without UI changes.
        """
        # Variable(s): `source_region_name` (source region name); named state retained for the surrounding calculation or subsequent calls.
        source_region_name = tracker_input or TrackerInput()
        # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
        raw = self.evaluate(source_region_name)
        # Variable(s): `locations` (locations); named state retained for the surrounding calculation or subsequent calls.
        locations = {
            name: LocationState(
                name=name, region=result.region, status=result.status,
                reachable=result.status == "reachable", checked=result.checked,
                reasons=tuple(result.rule.missing_labels()) if result.rule else (),
                unknown_reason=result.unknown_reason,
            )
            for name, result in raw.locations.items()
        }
        # Variable(s): `entrances` (entrances); named state retained for the surrounding calculation or subsequent calls.
        entrances = {
            entrance.name: EntranceState(
                name=entrance.name, source_region=entrance.source_region,
                target_region=str(source_region_name.entrance_connections.get(entrance.name, entrance.target_region) or ""),
                status=("unresolved" if entrance.name in raw.unresolved_entrances else "reachable" if entrance.name in raw.reachable_entrances else "blocked"),
                reachable=entrance.name in raw.reachable_entrances,
            )
            for entrance in self.definition.entrances
        }
        return LogicSnapshot(
            api_version=WAYFINDER_LOGIC_API, game=raw.game,
            reachable_regions=frozenset(raw.reachable_regions), events=frozenset(raw.events),
            locations=locations, entrances=entrances, warnings=tuple(raw.warnings),
            stats=RecalculationStats(mode="full", trigger="evaluate_api", nodes_evaluated=len(locations) + len(entrances) + len(self.definition.events)),
            raw=raw,
        )
