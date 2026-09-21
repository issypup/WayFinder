"""Provide model support."""
# /**
#  * Module: wayfinder.logic/model.py
#  * Purpose: Core tracker module for model; contains format-neutral or APWorld logic used to calculate WayFinder state.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping

from .rules import Rule, RuleResult, always


# /**
#  * Class: EntranceDefinition
#  * Purpose: Encapsulate the EntranceDefinition responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class EntranceDefinition:
    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
    """Provide entrance definition behavior."""
    name: str
    # Variable(s): `source_region` (source region); named state retained for the surrounding calculation or subsequent calls.
    source_region: str
    # Variable(s): `target_region` (target region); named state retained for the surrounding calculation or subsequent calls.
    target_region: str | None
    # Variable(s): `rule` (rule); named state retained for the surrounding calculation or subsequent calls.
    rule: Rule = field(default_factory=always)
    # Variable(s): `deferred_key` (deferred key); named state retained for the surrounding calculation or subsequent calls.
    deferred_key: str = ""


# /**
#  * Class: RegionDefinition
#  * Purpose: Encapsulate the RegionDefinition responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class RegionDefinition:
    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
    """Provide region definition behavior."""
    name: str
    # Variable(s): `starting` (starting); named state retained for the surrounding calculation or subsequent calls.
    starting: bool = False


# /**
#  * Class: LocationDefinition
#  * Purpose: Encapsulate the LocationDefinition responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class LocationDefinition:
    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
    """Provide location definition behavior."""
    name: str
    # Variable(s): `region` (region); named state retained for the surrounding calculation or subsequent calls.
    region: str
    # Variable(s): `rule` (rule); named state retained for the surrounding calculation or subsequent calls.
    rule: Rule = field(default_factory=always)
    # Variable(s): `address` (address); named state retained for the surrounding calculation or subsequent calls.
    address: int | None = None
    # Variable(s): `progression` (progression); named state retained for the surrounding calculation or subsequent calls.
    progression: bool = False


# /**
#  * Class: EventDefinition
#  * Purpose: Encapsulate the EventDefinition responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class EventDefinition:
    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
    """Provide event definition behavior."""
    name: str
    # Variable(s): `region` (region); named state retained for the surrounding calculation or subsequent calls.
    region: str
    # Variable(s): `rule` (rule); named state retained for the surrounding calculation or subsequent calls.
    rule: Rule = field(default_factory=always)
    # Variable(s): `grants` (grants); named state retained for the surrounding calculation or subsequent calls.
    grants: str = ""

    # /**
    #  * Function: granted_event
    #  * Purpose: Perform the granted event operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    @property
    def granted_event(self) -> str:
        """Handle granted event."""
        return self.grants or self.name


# /**
#  * Class: TrackerDefinition
#  * Purpose: Encapsulate the TrackerDefinition responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class TrackerDefinition:
    # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
    """Provide tracker definition behavior."""
    game: str
    # Variable(s): `regions` (regions); named state retained for the surrounding calculation or subsequent calls.
    regions: dict[str, RegionDefinition] = field(default_factory=dict)
    # Variable(s): `entrances` (entrances); named state retained for the surrounding calculation or subsequent calls.
    entrances: list[EntranceDefinition] = field(default_factory=list)
    # Variable(s): `locations` (locations); named state retained for the surrounding calculation or subsequent calls.
    locations: dict[str, LocationDefinition] = field(default_factory=dict)
    # Variable(s): `events` (events); named state retained for the surrounding calculation or subsequent calls.
    events: dict[str, EventDefinition] = field(default_factory=dict)
    # Variable(s): `schema_version` (schema version); named state retained for the surrounding calculation or subsequent calls.
    schema_version: int = 1

    # /**
    #  * Function: validate
    #  * Purpose: Perform the validate operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def validate(self) -> list[str]:
        # Variable(s): `errors` (errors); named state retained for the surrounding calculation or subsequent calls.
        """Handle validate."""
        errors: list[str] = []
        if not self.game.strip():
            errors.append("game name is empty")
        if not self.regions:
            errors.append("no regions defined")
        if self.regions and not any(r.starting for r in self.regions.values()):
            errors.append("no starting region defined")
        # Loop variable(s): `entrance` (entrance); each iteration represents the next value from the iterable below.
        for entrance in self.entrances:
            if entrance.source_region not in self.regions:
                errors.append(f"entrance {entrance.name!r} has unknown source region {entrance.source_region!r}")
            if entrance.target_region is not None and entrance.target_region not in self.regions:
                errors.append(f"entrance {entrance.name!r} has unknown target region {entrance.target_region!r}")
        # Loop variable(s): `location` (location); each iteration represents the next value from the iterable below.
        for location in self.locations.values():
            if location.region not in self.regions:
                errors.append(f"location {location.name!r} has unknown region {location.region!r}")
        # Loop variable(s): `event` (event); each iteration represents the next value from the iterable below.
        for event in self.events.values():
            if event.region not in self.regions:
                errors.append(f"event {event.name!r} has unknown region {event.region!r}")
        return errors


# /**
#  * Class: TrackerInput
#  * Purpose: Encapsulate the TrackerInput responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class TrackerInput:
    # Variable(s): `inventory` (inventory); named state retained for the surrounding calculation or subsequent calls.
    """Provide tracker input behavior."""
    inventory: Counter[str] = field(default_factory=Counter)
    # Variable(s): `checked_locations` (checked locations); named state retained for the surrounding calculation or subsequent calls.
    checked_locations: set[str] = field(default_factory=set)
    # Variable(s): `options` (options); named state retained for the surrounding calculation or subsequent calls.
    options: Mapping[str, Any] = field(default_factory=dict)
    # Variable(s): `state_values` (state values); named state retained for the surrounding calculation or subsequent calls.
    state_values: Mapping[str, Any] = field(default_factory=dict)
    # Variable(s): `known_events` (known events); named state retained for the surrounding calculation or subsequent calls.
    known_events: set[str] = field(default_factory=set)
    # Variable(s): `ignored_locations` (ignored locations); named state retained for the surrounding calculation or subsequent calls.
    ignored_locations: set[str] = field(default_factory=set)
    # Deferred entrance name -> resolved region name.  This mirrors the useful
    # concept natively without adopting another tracker's DataStorage implementation details.
    # Variable(s): `entrance_connections` (entrance connections); named state retained for the surrounding calculation or subsequent calls.
    entrance_connections: Mapping[str, str] = field(default_factory=dict)


# /**
#  * Class: LocationResult
#  * Purpose: Encapsulate the LocationResult responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class LocationResult:
    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
    """Provide location result behavior."""
    name: str
    # Variable(s): `region` (region); named state retained for the surrounding calculation or subsequent calls.
    region: str
    # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
    status: str
    # Variable(s): `checked` (checked); named state retained for the surrounding calculation or subsequent calls.
    checked: bool
    # Variable(s): `rule` (rule); named state retained for the surrounding calculation or subsequent calls.
    rule: RuleResult | None = None
    # Variable(s): `unknown_reason` (unknown reason); named state retained for the surrounding calculation or subsequent calls.
    unknown_reason: str = ""


# /**
#  * Class: EngineSnapshot
#  * Purpose: Encapsulate the EngineSnapshot responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class EngineSnapshot:
    # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
    """Provide engine snapshot behavior."""
    game: str
    # Variable(s): `reachable_regions` (reachable regions); named state retained for the surrounding calculation or subsequent calls.
    reachable_regions: set[str] = field(default_factory=set)
    # Variable(s): `reachable_entrances` (reachable entrances); named state retained for the surrounding calculation or subsequent calls.
    reachable_entrances: set[str] = field(default_factory=set)
    # Variable(s): `unresolved_entrances` (unresolved entrances); named state retained for the surrounding calculation or subsequent calls.
    unresolved_entrances: set[str] = field(default_factory=set)
    # Variable(s): `events` (events); named state retained for the surrounding calculation or subsequent calls.
    events: set[str] = field(default_factory=set)
    # Variable(s): `locations` (locations); named state retained for the surrounding calculation or subsequent calls.
    locations: dict[str, LocationResult] = field(default_factory=dict)
    # Variable(s): `warnings` (warnings); named state retained for the surrounding calculation or subsequent calls.
    warnings: list[str] = field(default_factory=list)
    # Variable(s): `iterations` (iterations); named state retained for the surrounding calculation or subsequent calls.
    iterations: int = 0

    # /**
    #  * Function: reachable_locations
    #  * Purpose: Perform the reachable locations operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    @property
    def reachable_locations(self) -> list[str]:
        """Handle reachable locations."""
        return [name for name, result in self.locations.items() if result.status == "reachable"]

    # /**
    #  * Function: unknown_locations
    #  * Purpose: Perform the unknown locations operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    @property
    def unknown_locations(self) -> list[str]:
        """Handle unknown locations."""
        return [name for name, result in self.locations.items() if result.status == "unknown"]
