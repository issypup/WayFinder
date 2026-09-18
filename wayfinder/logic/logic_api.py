"""Provide logic api support."""
# /**
#  * Module: wayfinder.logic/logic_api.py
#  * Purpose: Core tracker module for logic api; contains format-neutral or APWorld logic used to calculate WayFinder state.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

# Constant(s): `WAYFINDER_LOGIC_API`; shared configuration value(s) intentionally kept stable within this module.
WAYFINDER_LOGIC_API = 1


# /**
#  * Class: LocationState
#  * Purpose: Encapsulate the LocationState responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class LocationState:
    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
    """Provide location state behavior."""
    name: str
    # Variable(s): `region` (region); named state retained for the surrounding calculation or subsequent calls.
    region: str
    # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
    status: str
    # Variable(s): `reachable` (reachable); named state retained for the surrounding calculation or subsequent calls.
    reachable: bool
    # Variable(s): `checked` (checked); named state retained for the surrounding calculation or subsequent calls.
    checked: bool = False
    # Variable(s): `reasons` (reasons); named state retained for the surrounding calculation or subsequent calls.
    reasons: tuple[str, ...] = ()
    # Variable(s): `unknown_reason` (unknown reason); named state retained for the surrounding calculation or subsequent calls.
    unknown_reason: str = ""


# /**
#  * Class: EntranceState
#  * Purpose: Encapsulate the EntranceState responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class EntranceState:
    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
    """Provide entrance state behavior."""
    name: str
    # Variable(s): `source_region` (source region); named state retained for the surrounding calculation or subsequent calls.
    source_region: str
    # Variable(s): `target_region` (target region); named state retained for the surrounding calculation or subsequent calls.
    target_region: str
    # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
    status: str
    # Variable(s): `reachable` (reachable); named state retained for the surrounding calculation or subsequent calls.
    reachable: bool
    # Variable(s): `missing` (missing); named state retained for the surrounding calculation or subsequent calls.
    missing: tuple[str, ...] = ()


# /**
#  * Class: GoalState
#  * Purpose: Encapsulate the GoalState responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class GoalState:
    # Variable(s): `available` (available); named state retained for the surrounding calculation or subsequent calls.
    """Provide goal state behavior."""
    available: bool
    # Variable(s): `reachable` (reachable); named state retained for the surrounding calculation or subsequent calls.
    reachable: bool
    # Variable(s): `missing` (missing); named state retained for the surrounding calculation or subsequent calls.
    missing: tuple[str, ...] = ()
    # Variable(s): `error` (error); named state retained for the surrounding calculation or subsequent calls.
    error: str = ""


# /**
#  * Class: RecalculationStats
#  * Purpose: Encapsulate the RecalculationStats responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class RecalculationStats:
    # Variable(s): `mode` (mode); named state retained for the surrounding calculation or subsequent calls.
    """Provide recalculation stats behavior."""
    mode: str = "full"
    # Variable(s): `trigger` (trigger); named state retained for the surrounding calculation or subsequent calls.
    trigger: str = "initial"
    # Variable(s): `nodes_evaluated` (nodes evaluated); named state retained for the surrounding calculation or subsequent calls.
    nodes_evaluated: int = 0
    # Variable(s): `nodes_reused` (nodes reused); named state retained for the surrounding calculation or subsequent calls.
    nodes_reused: int = 0
    # Variable(s): `affected_nodes` (affected nodes); named state retained for the surrounding calculation or subsequent calls.
    affected_nodes: tuple[str, ...] = ()
    # Variable(s): `fallback_reason` (fallback reason); named state retained for the surrounding calculation or subsequent calls.
    fallback_reason: str = ""


# /**
#  * Class: LogicSnapshot
#  * Purpose: Encapsulate the LogicSnapshot responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class LogicSnapshot:
    # Variable(s): `api_version` (api version); named state retained for the surrounding calculation or subsequent calls.
    """Provide logic snapshot behavior."""
    api_version: int
    # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
    game: str
    # Variable(s): `reachable_regions` (reachable regions); named state retained for the surrounding calculation or subsequent calls.
    reachable_regions: frozenset[str]
    # Variable(s): `events` (events); named state retained for the surrounding calculation or subsequent calls.
    events: frozenset[str]
    # Variable(s): `locations` (locations); named state retained for the surrounding calculation or subsequent calls.
    locations: Mapping[str, LocationState]
    # Variable(s): `entrances` (entrances); named state retained for the surrounding calculation or subsequent calls.
    entrances: Mapping[str, EntranceState] = field(default_factory=dict)
    # Variable(s): `goal` (goal); named state retained for the surrounding calculation or subsequent calls.
    goal: GoalState | None = None
    # Variable(s): `warnings` (warnings); named state retained for the surrounding calculation or subsequent calls.
    warnings: tuple[str, ...] = ()
    # Variable(s): `stats` (stats); named state retained for the surrounding calculation or subsequent calls.
    stats: RecalculationStats = field(default_factory=RecalculationStats)
    # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
    raw: Any = None
