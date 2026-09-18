# /**
#  * Module: wayfinder.logic/__init__.py
#  * Purpose: Core tracker module for   init  ; contains format-neutral or APWorld logic used to calculate WayFinder state.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

"""WayFinder native tracker and logic engine.

WayFinder owns this tracker/logic package. Game adapters
translate their source format (native UB definitions, APWorlds, PopTracker, etc.)
into :class:`TrackerDefinition`, then :class:`LogicEngine` evaluates one
canonical state for every GUI consumer.
"""
from .engine import LogicEngine
from .logic_api import WAYFINDER_LOGIC_API, LogicSnapshot, LocationState, EntranceState, GoalState, RecalculationStats
from .dependency_graph import DependencyGraph
from .incremental import IncrementalAPWorldEvaluator
from .comparison import LogicComparisonReport, LogicDifference, compare_snapshots, compare_engines
from .model import (
    EngineSnapshot,
    EntranceDefinition,
    EventDefinition,
    LocationDefinition,
    LocationResult,
    RegionDefinition,
    TrackerDefinition,
    TrackerInput,
)
from .rules import (
    Rule,
    RuleResult,
    always,
    never,
    item,
    event,
    option,
    state_value,
    all_of,
    any_of,
    not_,
)

# Module metadata: __all__ identifies this source to callers and packaging/runtime diagnostics.
__all__ = [
    "LogicEngine", "EngineSnapshot", "EntranceDefinition", "EventDefinition",
    "LocationDefinition", "LocationResult", "RegionDefinition",
    "TrackerDefinition", "TrackerInput", "Rule", "RuleResult", "always",
    "never", "item", "event", "option", "state_value", "all_of", "any_of", "not_",
    "WAYFINDER_LOGIC_API", "LogicSnapshot", "LocationState", "EntranceState", "GoalState",
    "RecalculationStats", "DependencyGraph", "IncrementalAPWorldEvaluator",
    "LogicComparisonReport", "LogicDifference", "compare_snapshots", "compare_engines",
]

from .apworld_adapter import APAdapterSnapshot, NativeAPState, evaluate_generated_world
