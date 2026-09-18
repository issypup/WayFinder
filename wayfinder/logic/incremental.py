"""Provide incremental support."""
# /**
#  * Module: wayfinder.logic/incremental.py
#  * Purpose: Core tracker module for incremental; contains format-neutral or APWorld logic used to calculate WayFinder state.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from __future__ import annotations

from collections import Counter
from copy import copy
from dataclasses import dataclass
from typing import Any

from .apworld_adapter import APAdapterSnapshot, NativeAPState, _access_ok, _item_groups, evaluate_generated_world, trace_access_rule
from .dependency_graph import DependencyGraph
from .logic_api import RecalculationStats


# /**
#  * Class: IncrementalResult
#  * Purpose: Encapsulate the IncrementalResult responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class IncrementalResult:
    # Variable(s): `snapshot` (snapshot); named state retained for the surrounding calculation or subsequent calls.
    """Provide incremental result behavior."""
    snapshot: APAdapterSnapshot
    # Variable(s): `stats` (stats); named state retained for the surrounding calculation or subsequent calls.
    stats: RecalculationStats


# /**
#  * Class: IncrementalAPWorldEvaluator
#  * Purpose: Encapsulate the IncrementalAPWorldEvaluator responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
class IncrementalAPWorldEvaluator:
    """Incremental evaluator for a generated APWorld.

    Region/entrance/event changes remain conservative: if a changed dependency can
    affect traversal or event sweeping, a full fixed-point evaluation is used.
    When changes only affect terminal locations, only those locations are
    re-evaluated and the stabilized graph/events are reused.
    """

    # /**
    #  * Function: __init__
    #  * Purpose: Initialize this object and establish its required runtime state.
    #  * @param multiworld: Multiworld supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param world: World supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def __init__(self, *, multiworld: Any, world: Any, player: int):
        """Handle init."""
        self.multiworld = multiworld
        self.world = world
        self.player = int(player)
        self._last_inventory: Counter[str] | None = None
        self._last_checked: set[str] | None = None
        self._last: APAdapterSnapshot | None = None
        self._graph = DependencyGraph()

    # /**
    #  * Function: _dependency_keys
    #  * Purpose: Perform the dependency keys operation while keeping the surrounding subsystem state consistent.
    #  * @param rule_detail: Rule detail supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _dependency_keys(self, rule_detail: dict[str, Any]) -> tuple[set[str], bool]:
        # Variable(s): `dependencies` (dependencies); named state retained for the surrounding calculation or subsequent calls.
        """Handle dependency keys."""
        dependencies: set[str] = set()
        # Variable(s): `unsafe` (unsafe); named state retained for the surrounding calculation or subsequent calls.
        unsafe = False
        # Loop variable(s): `dependency_record` (dependency record); each iteration represents the next value from the iterable below.
        for dependency_record in rule_detail.get("consulted", []) or []:
            # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
            kind = str(dependency_record.get("kind", ""))
            # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
            name = str(dependency_record.get("name", ""))
            if kind in {"item", "item_count"}:
                dependencies.add(f"item:{name}")
            elif kind == "region":
                dependencies.add(f"region:{name}")
            elif kind in {"unsupported", "opaque"}:
                dependencies.add(f"{kind}:{name}")
                # Variable(s): `unsafe` (unsafe); named state retained for the surrounding calculation or subsequent calls.
                unsafe = True
        if rule_detail.get("error"):
            # Variable(s): `unsafe` (unsafe); named state retained for the surrounding calculation or subsequent calls.
            unsafe = True
        # Include predicates in short-circuited alternatives, so their displayed
        # counts and results refresh when those items change.
        from wayfinder.logic.rule_explanation import walk
        for node in walk(rule_detail.get('normalized_rule') or {}):
            if node.get('kind') in {'ITEM', 'COUNT', 'EVENT'}:
                for item in node.get('items', [node.get('label', '')]):
                    dependencies.add(f'item:{item}')
                    if node.get('kind') == 'EVENT':
                        dependencies.add(f'event:{item}')
            elif node.get('kind') == 'REGION':
                dependencies.add(f"region:{node.get('label', '')}")
        return dependencies, unsafe

    # /**
    #  * Function: _build_graph
    #  * Purpose: Build the graph representation used by the surrounding subsystem.
    #  * @param snapshot: Snapshot supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _build_graph(self, snapshot: APAdapterSnapshot) -> None:
        # Variable(s): `graph` (graph); named state retained for the surrounding calculation or subsequent calls.
        """Handle build graph."""
        graph = DependencyGraph()
        # Loop variable(s): `name` (name), `rule_detail` (rule detail); each iteration represents the next value from the iterable below.
        for name, rule_detail in (snapshot.rule_details or {}).items():
            # Variable(s): `dependencies` (dependencies), `unsafe` (unsafe); named state retained for the surrounding calculation or subsequent calls.
            dependencies, unsafe = self._dependency_keys(rule_detail)
            graph.add(f"location:{name}", dependencies, unsafe=unsafe)
        # Loop variable(s): `rule_detail` (rule detail); each iteration represents the next value from the iterable below.
        for rule_detail in snapshot.entrance_details or []:
            # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
            name = str(rule_detail.get("name", ""))
            # Variable(s): `dependencies` (dependencies), `unsafe` (unsafe); named state retained for the surrounding calculation or subsequent calls.
            dependencies, unsafe = self._dependency_keys(rule_detail)
            graph.add(f"entrance:{name}", dependencies, unsafe=unsafe)
        # Loop variable(s): `rule_detail` (rule detail); each iteration represents the next value from the iterable below.
        for rule_detail in snapshot.event_details or []:
            # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
            name = str(rule_detail.get("event_item") or rule_detail.get("name") or "")
            # Variable(s): `dependencies` (dependencies), `unsafe` (unsafe); named state retained for the surrounding calculation or subsequent calls.
            dependencies, unsafe = self._dependency_keys(rule_detail)
            graph.add(f"event:{name}", dependencies, unsafe=unsafe)
        self._graph = graph

    # /**
    #  * Function: _full
    #  * Purpose: Perform the full operation while keeping the surrounding subsystem state consistent.
    #  * @param inventory: Inventory supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param checked: Checked supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param trigger: Trigger supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param reason: Reason supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _full(self, inventory: Counter[str], checked: set[str], trigger: str, reason: str = "") -> IncrementalResult:
        # Variable(s): `snapshot` (snapshot); named state retained for the surrounding calculation or subsequent calls.
        """Handle full."""
        snapshot = evaluate_generated_world(
            multiworld=self.multiworld, world=self.world, player=self.player,
            inventory=Counter(inventory), checked_location_names=set(checked),
        )
        self._last_inventory = Counter(inventory)
        self._last_checked = set(checked)
        self._last = snapshot
        self._build_graph(snapshot)
        # Variable(s): `node_count` (node count); named state retained for the surrounding calculation or subsequent calls.
        node_count = len(snapshot.rule_details) + len(snapshot.entrance_details) + len(snapshot.event_details)
        return IncrementalResult(snapshot, RecalculationStats(
            mode="full", trigger=trigger, nodes_evaluated=node_count,
            fallback_reason=reason,
        ))

    # /**
    #  * Function: evaluate
    #  * Purpose: Perform the evaluate operation while keeping the surrounding subsystem state consistent.
    #  * @param inventory: Inventory supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param checked: Checked supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param force_full: Force full supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param trigger: Trigger supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def evaluate(self, inventory: Counter[str], checked: set[str], *, force_full: bool = False, trigger: str = "state_change") -> IncrementalResult:
        # Variable(s): `inventory` (inventory); named state retained for the surrounding calculation or subsequent calls.
        """Handle evaluate."""
        inventory = Counter(inventory)
        # Variable(s): `checked` (checked); named state retained for the surrounding calculation or subsequent calls.
        checked = set(checked)
        if force_full or self._last is None or self._last_inventory is None or self._last_checked is None:
            return self._full(inventory, checked, "manual_refresh" if force_full else "initial")

        # Variable(s): `changed_items` (changed items); named state retained for the surrounding calculation or subsequent calls.
        changed_items = {name for name in set(inventory) | set(self._last_inventory) if inventory.get(name, 0) != self._last_inventory.get(name, 0)}
        # Variable(s): `changed_checked` (changed checked); named state retained for the surrounding calculation or subsequent calls.
        changed_checked = checked ^ self._last_checked
        if not changed_items and not changed_checked:
            return IncrementalResult(self._last, RecalculationStats(mode="cached", trigger="no_change", nodes_reused=len(self._graph.node_to_dependencies)))

        # Variable(s): `changed_deps` (changed deps); named state retained for the surrounding calculation or subsequent calls.
        changed_deps = {f"item:{name}" for name in changed_items}
        # Variable(s): `affected` (affected); named state retained for the surrounding calculation or subsequent calls.
        affected = self._graph.affected(changed_deps)

        # A check-state change does not alter AP reachability rules in WayFinder;
        # it only removes/adds terminal locations from the displayed reachable set.
        # Item changes that touch traversal or event nodes can have downstream
        # effects, so use the authoritative full fixed point in those cases.
        # Variable(s): `structural_nodes` (structural nodes); named state retained for the surrounding calculation or subsequent calls.
        structural_nodes = {n for n in affected if n.startswith("entrance:") or n.startswith("event:")}
        if structural_nodes:
            return self._full(inventory, checked, trigger, "changed dependency affects traversal/event sweep")
        if changed_items and (not affected or not self._graph.is_safe_for(affected)):
            return self._full(inventory, checked, trigger, "dependency coverage is incomplete or opaque")

        # Variable(s): `snapshot` (snapshot); named state retained for the surrounding calculation or subsequent calls.
        # Static world/rule metadata is immutable between live state updates.
        # Copy only the mutable dynamic pieces instead of deep-copying every rule
        # explanation, entrance and event record for each ReceivedItems packet.
        snapshot = copy(self._last)
        snapshot.checked_locations = set(checked)
        snapshot.reachable_locations = set(self._last.reachable_locations)
        snapshot.rule_details = dict(self._last.rule_details)
        snapshot.errors = list(self._last.errors)
        # Update checked status first.
        snapshot.reachable_locations.difference_update(checked)
        # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
        for name in changed_checked:
            if name in checked:
                snapshot.reachable_locations.discard(name)

        # Variable(s): `item_groups` (item groups); named state retained for the surrounding calculation or subsequent calls.
        item_groups = _item_groups(self.world)
        # Variable(s): `effective_inventory` (effective inventory); named state retained for the surrounding calculation or subsequent calls.
        effective_inventory = Counter(inventory)
        # Full AP evaluation makes swept event items visible through CollectionState
        # inventory predicates. Preserve that exact semantic when only terminal
        # locations are being reevaluated incrementally.
        # Loop variable(s): `event_name` (event name); each iteration represents the next value from the iterable below.
        for event_name in snapshot.events:
            effective_inventory[event_name] = max(1, int(effective_inventory.get(event_name, 0)))
        # Variable(s): `state` (state); named state retained for the surrounding calculation or subsequent calls.
        state = NativeAPState(self.player, effective_inventory, set(snapshot.reachable_regions), set(snapshot.events), item_groups, self.multiworld)
        # Variable(s): `evaluated` (evaluated); named state retained for the surrounding calculation or subsequent calls.
        evaluated = 0
        # Loop variable(s): `node` (node); each iteration represents the next value from the iterable below.
        for node in sorted(affected):
            if not node.startswith("location:"):
                continue
            # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
            name = node.split(":", 1)[1]
            try:
                # Variable(s): `location` (location); named state retained for the surrounding calculation or subsequent calls.
                location = self.multiworld.get_location(name, self.player)
            except Exception:
                return self._full(inventory, checked, trigger, f"affected location {name!r} could not be resolved")
            snapshot.reachable_locations.discard(name)
            if name not in checked and _access_ok(location, state, snapshot.errors, f"Location {name}"):
                # Variable(s): `parent` (parent); named state retained for the surrounding calculation or subsequent calls.
                parent = str(getattr(getattr(location, "parent_region", None), "name", "") or "")
                if parent in snapshot.reachable_regions:
                    snapshot.reachable_locations.add(name)
            # Variable(s): `rule_detail` (rule detail); named state retained for the surrounding calculation or subsequent calls.
            rule_detail = trace_access_rule(location, player=self.player, inventory=Counter(effective_inventory), reachable_regions=set(snapshot.reachable_regions), events=set(snapshot.events), groups=item_groups, multiworld=self.multiworld)
            rule_detail.update({"name": name, "region": str(getattr(getattr(location, "parent_region", None), "name", "") or ""), "kind": "location", "reachable": name in snapshot.reachable_locations})
            snapshot.rule_details[name] = rule_detail
            # Variable(s): `dependencies` (dependencies), `unsafe` (unsafe); named state retained for the surrounding calculation or subsequent calls.
            dependencies, unsafe = self._dependency_keys(rule_detail)
            self._graph.add(node, dependencies, unsafe=unsafe)
            evaluated += 1

        # If only checks changed, newly-unchecked locations must be evaluated.
        if changed_checked and not changed_items:
            # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
            for name in changed_checked - checked:
                try:
                    # Variable(s): `location` (location); named state retained for the surrounding calculation or subsequent calls.
                    location = self.multiworld.get_location(name, self.player)
                except Exception:
                    continue
                # Variable(s): `parent` (parent); named state retained for the surrounding calculation or subsequent calls.
                parent = str(getattr(getattr(location, "parent_region", None), "name", "") or "")
                if parent in snapshot.reachable_regions and _access_ok(location, state, snapshot.errors, f"Location {name}"):
                    snapshot.reachable_locations.add(name)
                evaluated += 1

        self._last_inventory = Counter(inventory)
        self._last_checked = set(checked)
        self._last = snapshot
        # Variable(s): `total` (total); named state retained for the surrounding calculation or subsequent calls.
        total = len(self._graph.node_to_dependencies)
        return IncrementalResult(snapshot, RecalculationStats(
            mode="incremental", trigger=trigger, nodes_evaluated=evaluated,
            nodes_reused=max(0, total - evaluated), affected_nodes=tuple(sorted(affected)),
        ))
