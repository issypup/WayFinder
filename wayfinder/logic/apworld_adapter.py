"""Provide apworld adapter support."""
# /**
#  * Module: wayfinder.logic/apworld_adapter.py
#  * Purpose: Core tracker module for apworld adapter; contains format-neutral or APWorld logic used to calculate WayFinder state.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

"""Compatibility adapter from a generated Archipelago MultiWorld to UB native logic.

This deliberately uses WayFinder native reachability.  It consumes the
already-generated APWorld graph/rules and evaluates them with a small
WayFinder-owned state proxy.  Unsupported state API calls become explicit
adapter errors instead of silently changing logic.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable
import inspect
import os
import sys


# /**
#  * Class: UnsupportedStateOperation
#  * Purpose: Encapsulate the UnsupportedStateOperation responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
class UnsupportedStateOperation(RuntimeError):
    """Raised when an APWorld rule requests unsupported state behaviour."""


# /**
#  * Class: APAdapterSnapshot
#  * Purpose: Encapsulate the APAdapterSnapshot responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class APAdapterSnapshot:
    # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
    """Provide a p adapter snapshot behavior."""
    game: str = ""
    # Variable(s): `player` (player); named state retained for the surrounding calculation or subsequent calls.
    player: int = 1
    # Variable(s): `reachable_regions` (reachable regions); named state retained for the surrounding calculation or subsequent calls.
    reachable_regions: set[str] = field(default_factory=set)
    # Variable(s): `reachable_entrances` (reachable entrances); named state retained for the surrounding calculation or subsequent calls.
    reachable_entrances: set[str] = field(default_factory=set)
    # Variable(s): `reachable_locations` (reachable locations); named state retained for the surrounding calculation or subsequent calls.
    reachable_locations: set[str] = field(default_factory=set)
    # Variable(s): `checked_locations` (checked locations); named state retained for the surrounding calculation or subsequent calls.
    checked_locations: set[str] = field(default_factory=set)
    # Variable(s): `events` (events); named state retained for the surrounding calculation or subsequent calls.
    events: set[str] = field(default_factory=set)
    # Variable(s): `errors` (errors); named state retained for the surrounding calculation or subsequent calls.
    errors: list[str] = field(default_factory=list)
    # Variable(s): `iterations` (iterations); named state retained for the surrounding calculation or subsequent calls.
    iterations: int = 0
    # Variable(s): `rule_details` (rule details); named state retained for the surrounding calculation or subsequent calls.
    rule_details: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Variable(s): `entrance_details` (entrance details); named state retained for the surrounding calculation or subsequent calls.
    entrance_details: list[dict[str, Any]] = field(default_factory=list)
    # Variable(s): `event_details` (event details); named state retained for the surrounding calculation or subsequent calls.
    event_details: list[dict[str, Any]] = field(default_factory=list)
    # Variable(s): `unsupported_state_calls` (unsupported state calls); named state retained for the surrounding calculation or subsequent calls.
    unsupported_state_calls: list[str] = field(default_factory=list)


class _TracingCount(int):
    """Integer-like AP item count that records how the APWorld compares it."""
    def __new__(cls, value: int, item: Any, trace: list[dict[str, Any]] | None):
        """Handle new."""
        obj = int.__new__(cls, int(value))
        obj._wayfinder_item = str(item)
        obj._wayfinder_trace = trace
        return obj

    def _record_comparison(self, operator: str, required: Any, result: bool) -> bool:
        """Handle record comparison."""
        try:
            required_value = int(required)
        except Exception:
            required_value = required
        row = {
            "kind": "item_count", "name": self._wayfinder_item, "result": bool(result),
            "have": int(self), "required": required_value, "operator": operator,
            "detail": f"{self._wayfinder_item}: have {int(self)}, need {operator} {required_value}",
        }
        trace = self._wayfinder_trace
        if trace is not None:
            # A direct read is recorded first so bare truthiness still has a trace.
            # Once the value is compared, replace that weaker observation with the
            # exact predicate instead of showing duplicate rows in the explanation.
            trace[:] = [x for x in trace if not (
                x.get("kind") == "item_count" and x.get("name") == self._wayfinder_item
                and x.get("operator") is None
            )]
            if row not in trace:
                trace.append(row)
        return bool(result)

    def __bool__(self):
        """Handle bool."""
        return self._record_comparison(">", 0, int(self) > 0)
    def __ge__(self, other): return self._record_comparison(">=", other, int(self) >= other)
    def __gt__(self, other): return self._record_comparison(">", other, int(self) > other)
    def __le__(self, other): return self._record_comparison("<=", other, int(self) <= other)
    def __lt__(self, other): return self._record_comparison("<", other, int(self) < other)
    def __eq__(self, other): return self._record_comparison("==", other, int(self) == other)
    def __ne__(self, other): return self._record_comparison("!=", other, int(self) != other)


class _TracingProgItemsCounter(Counter):
    """Counter compatible with CollectionState.prog_items that records direct helper reads."""
    def __init__(self, values: dict[str, int], trace: list[dict[str, Any]] | None):
        """Handle init."""
        super().__init__(values)
        self._wayfinder_trace = trace

    def _tracked(self, item: Any, value: int) -> _TracingCount:
        """Handle tracked."""
        row = {"kind": "item_count", "name": str(item), "result": bool(value),
               "have": int(value), "required": 1, "operator": None,
               "detail": f"{item}: have {int(value)}, need >= 1"}
        if self._wayfinder_trace is not None and row not in self._wayfinder_trace:
            self._wayfinder_trace.append(row)
        return _TracingCount(int(value), item, self._wayfinder_trace)

    def __getitem__(self, item: Any) -> int:
        """Handle getitem."""
        return self._tracked(item, super().__getitem__(item))

    def get(self, item: Any, default: Any = None) -> Any:
        """Handle get."""
        value = super().get(item, default)
        if isinstance(value, (int, bool)):
            return self._tracked(item, int(value))
        return value


def _rule_identity(rule: Any) -> dict[str, Any]:
    """Best-effort source identity for generated APWorld callables."""
    result = {"name": str(getattr(rule, "__qualname__", None) or getattr(rule, "__name__", None) or type(rule).__name__)}
    if not inspect.isroutine(rule):
        import functools
        rule = rule.func if isinstance(rule, functools.partial) else getattr(type(rule), '__call__', rule)
    try:
        result["file"] = str(inspect.getsourcefile(rule) or inspect.getfile(rule) or "")
    except Exception:
        result["file"] = ""
    try:
        result["line"] = int(inspect.getsourcelines(rule)[1])
    except Exception:
        result["line"] = int(getattr(getattr(rule, "__code__", None), "co_firstlineno", 0))
    return result

def _is_archipelago_framework_rule(identity: dict[str, Any]) -> bool:
    """Return True when a callable comes from AP's generic framework, not a world rule.

    Location/Entrance objects start with permissive lambdas defined in BaseClasses.py.
    Treating those lambdas as opaque APWorld helpers is misleading: they mean there is
    no *local* predicate, and any real requirement lives on the region path behind it.
    """
    filename = os.path.basename(str(identity.get("file", "") or "").replace("\\", "/")).lower()
    return filename in {"baseclasses.py", "autoworld.py"}


def _route_rule_rows_for_region(target_region: str, starting_regions: set[str], entrance_details: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Walk backwards from a region and choose the most actionable structural route.

    A region can have several incoming entrances (Time Rifts are a good example).  A
    plain shortest-path BFS used to choose an arbitrary alphabetic branch and then
    merge that branch's requirements into the destination explanation.  This could
    make a Mafia Town rift appear to require unrelated Alpine Skyline progression.

    Prefer routes whose *source regions* are already reachable, then routes with fewer
    currently-blocked entrances, then shorter routes.  This keeps inherited destination
    requirements scoped to the route the live graph says is closest to actionable.
    """
    import heapq
    import itertools

    target_region = str(target_region or "")
    if not target_region or target_region in starting_regions:
        return [], []

    incoming: dict[str, list[dict[str, Any]]] = {}
    for detail in entrance_details:
        target = str(detail.get("target_region", "") or "")
        source = str(detail.get("source_region", "") or "")
        if target and source:
            incoming.setdefault(target, []).append(detail)

    # Priority tuple: unreachable-source count, blocked-entrance count, path length,
    # stable lexical tie-breaker, monotonic serial.  Each chain is start->target ordered.
    serial = itertools.count()
    queue: list[tuple[int, int, int, str, int, str, list[dict[str, Any]]]] = [
        (0, 0, 0, "", next(serial), target_region, [])
    ]
    best: dict[str, tuple[int, int, int]] = {target_region: (0, 0, 0)}
    selected_chain: list[dict[str, Any]] | None = None

    while queue:
        unreachable_sources, blocked_steps, length, _tie, _serial, region_name, reverse_chain = heapq.heappop(queue)
        if region_name in starting_regions:
            selected_chain = reverse_chain
            break
        current_score = (unreachable_sources, blocked_steps, length)
        if current_score != best.get(region_name):
            continue
        for entrance in sorted(incoming.get(region_name, []), key=lambda row: str(row.get("name", ""))):
            source = str(entrance.get("source_region", "") or "")
            if not source:
                continue
            chain = [entrance] + reverse_chain
            next_unreachable = unreachable_sources + (0 if bool(entrance.get("source_reachable", False)) else 1)
            next_blocked = blocked_steps + (0 if bool(entrance.get("satisfied", entrance.get("reachable", False))) else 1)
            next_length = length + 1
            score = (next_unreachable, next_blocked, next_length)
            previous = best.get(source)
            if previous is None or score < previous:
                best[source] = score
                heapq.heappush(queue, (*score, str(entrance.get("name", "")), next(serial), source, chain))

    if not selected_chain:
        return [], []

    rows: list[dict[str, Any]] = []
    for step in selected_chain:
        step_name = str(step.get("name", "") or f"{step.get('source_region','')} -> {step.get('target_region','')}")
        rows.append({
            "kind": "route_step",
            "name": step_name,
            "result": bool(step.get("satisfied", step.get("reachable", False))),
            "detail": f"Region path: {step.get('source_region','')} → {step.get('target_region','')}",
        })
        for predicate in step.get("consulted", []) or []:
            if predicate.get("kind") in {"opaque", "unconditional"}:
                continue
            inherited = dict(predicate)
            inherited["detail"] = (str(inherited.get("detail", "")) + f" [via entrance: {step_name}]").strip()
            if inherited not in rows:
                rows.append(inherited)
    return rows, selected_chain


# /**
#  * Class: NativeAPState
#  * Purpose: Encapsulate the NativeAPState responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
class NativeAPState:
    """Subset of CollectionState used by common APWorld access rules."""

    # /**
    #  * Function: __init__
    #  * Purpose: Initialize this object and establish its required runtime state.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param inventory: Inventory supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param reachable_regions: Reachable regions supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param events: Events supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param groups: Groups supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param multiworld: Multiworld supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param trace: Trace supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def __init__(self, player: int, inventory: Counter[str], reachable_regions: set[str], events: set[str], groups: dict[str, set[str]] | None = None, multiworld: Any = None, trace: list[dict[str, Any]] | None = None):
        """Handle init."""
        self.player = player
        self.inventory = inventory
        self.reachable_regions = reachable_regions
        self.events = events
        self.groups = groups or {}
        self.multiworld = multiworld
        self._reach_guard: set[tuple[str, str]] = set()
        self.trace = trace
        # Match Archipelago CollectionState's public shape exactly.  AP 0.6.x
        # exposes prog_items as {player_id: Counter({item_name: count})}.
        # Some APWorld helper libraries (including rule_builder used by Little
        # Witch Nobeta) read prog_items directly rather than calling state.has().
        # The old tuple-key mapping made every such Has(...) rule appear false.
        self.prog_items = {player: _TracingProgItemsCounter({name: count for name, count in inventory.items() if count}, trace)}

    # /**
    #  * Function: _record
    #  * Purpose: Perform the record operation while keeping the surrounding subsystem state consistent.
    #  * @param kind: Kind supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param name: Name supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param result: Result supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param detail: Detail supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _record(self, kind: str, name: str, result: Any, detail: str = "") -> None:
        """Handle record."""
        if self.trace is not None:
            self.trace.append({"kind": kind, "name": str(name), "result": bool(result) if isinstance(result, bool) else result, "detail": detail})

    # /**
    #  * Function: count
    #  * Purpose: Perform the count operation while keeping the surrounding subsystem state consistent.
    #  * @param item: Item supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def count(self, item: str, player: int | None = None) -> int:
        # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
        """Handle count."""
        value = int(self.inventory.get(str(item), 0))
        self._record("item_count", str(item), value, f"have {value}")
        return value

    # /**
    #  * Function: has
    #  * Purpose: Perform the has operation while keeping the surrounding subsystem state consistent.
    #  * @param item: Item supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param count: Count supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def has(self, item: str, player: int | None = None, count: int = 1) -> bool:
        # Variable(s): `have` (have); named state retained for the surrounding calculation or subsequent calls.
        """Handle has."""
        have = int(self.inventory.get(str(item), 0)); need = int(count); ok = have >= need
        self._record("item", str(item), ok, f"have {have}, need {need}")
        return ok

    # /**
    #  * Function: has_all
    #  * Purpose: Determine whether the current state contains or satisfies all.
    #  * @param items: Items supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def has_all(self, items: Iterable[str], player: int | None = None) -> bool:
        """Return has all."""
        return all(self.has(x, player) for x in items)

    # /**
    #  * Function: has_any
    #  * Purpose: Determine whether the current state contains or satisfies any.
    #  * @param items: Items supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def has_any(self, items: Iterable[str], player: int | None = None) -> bool:
        """Return has any."""
        return any(self.has(x, player) for x in items)

    # /**
    #  * Function: has_all_counts
    #  * Purpose: Determine whether the current state contains or satisfies all counts.
    #  * @param items: Items supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def has_all_counts(self, items: dict[str, int], player: int | None = None) -> bool:
        """Return has all counts."""
        return all(self.has(name, player, count) for name, count in items.items())

    # /**
    #  * Function: has_from_list
    #  * Purpose: Determine whether the current state contains or satisfies from list.
    #  * @param items: Items supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param count: Count supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def has_from_list(self, items: Iterable[str], player: int | None = None, count: int = 1) -> bool:
        """Return has from list."""
        return sum(self.count(x, player) for x in items) >= int(count)

    # /**
    #  * Function: has_from_list_unique
    #  * Purpose: Determine whether the current state contains or satisfies from list unique.
    #  * @param items: Items supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param count: Count supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def has_from_list_unique(self, items: Iterable[str], player: int | None = None, count: int = 1) -> bool:
        """Return has from list unique."""
        return sum(1 for x in items if self.has(x, player)) >= int(count)

    # /**
    #  * Function: count_from_list
    #  * Purpose: Perform the count from list operation while keeping the surrounding subsystem state consistent.
    #  * @param items: Items supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def count_from_list(self, items: Iterable[str], player: int | None = None) -> int:
        """Handle count from list."""
        return sum(self.count(x, player) for x in items)

    # /**
    #  * Function: count_from_list_unique
    #  * Purpose: Perform the count from list unique operation while keeping the surrounding subsystem state consistent.
    #  * @param items: Items supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def count_from_list_unique(self, items: Iterable[str], player: int | None = None) -> int:
        """Handle count from list unique."""
        return sum(1 for x in items if self.has(x, player))

    # /**
    #  * Function: count_group
    #  * Purpose: Perform the count group operation while keeping the surrounding subsystem state consistent.
    #  * @param group: Group supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def count_group(self, group: str, player: int | None = None) -> int:
        """Handle count group."""
        return self.count_from_list(self.groups.get(str(group), set()), player)

    # /**
    #  * Function: has_group
    #  * Purpose: Determine whether the current state contains or satisfies group.
    #  * @param group: Group supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param count: Count supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def has_group(self, group: str, player: int | None = None, count: int = 1) -> bool:
        """Return has group."""
        return self.count_group(group, player) >= int(count)

    # /**
    #  * Function: has_group_unique
    #  * Purpose: Determine whether the current state contains or satisfies group unique.
    #  * @param group: Group supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param count: Count supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def has_group_unique(self, group: str, player: int | None = None, count: int = 1) -> bool:
        """Return has group unique."""
        return self.count_from_list_unique(self.groups.get(str(group), set()), player) >= int(count)

    # /**
    #  * Function: can_reach
    #  * Purpose: Perform the can reach operation while keeping the surrounding subsystem state consistent.
    #  * @param spot: Spot supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param resolution_hint: Resolution hint supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def can_reach(self, spot: Any, resolution_hint: str | None = None, player: int | None = None) -> bool:
        """Compatibility implementation for common APWorld recursive reach calls.

        Region reachability comes from WayFinder's graph fixed point. For a
        Location or Entrance, WayFinder resolves the object from the generated
        MultiWorld and evaluates its parent/source region plus access rule. Cycles are
        rejected deterministically instead of recursing forever.
        """
        if hasattr(spot, "name"):
            # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
            name = str(getattr(spot, "name"))
            # Variable(s): `obj` (object); named state retained for the surrounding calculation or subsequent calls.
            obj = spot
        else:
            # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
            name = str(spot)
            # Variable(s): `obj` (object); named state retained for the surrounding calculation or subsequent calls.
            obj = None
        # Variable(s): `hint` (hint); named state retained for the surrounding calculation or subsequent calls.
        hint = resolution_hint or (type(obj).__name__ if obj is not None else "Region")
        if hint == "Region":
            ok = name in self.reachable_regions
            self._record("region", name, ok, "reachable" if ok else "not reachable")
            return ok
        # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
        key = (str(hint), name)
        if key in self._reach_guard:
            self._record("region", name, False, f"Recursive can_reach({hint}) cycle was rejected")
            return False
        self._reach_guard.add(key)
        try:
            if obj is None and self.multiworld is not None:
                try:
                    if hint == "Location":
                        # Variable(s): `obj` (object); named state retained for the surrounding calculation or subsequent calls.
                        obj = self.multiworld.get_location(name, player or self.player)
                    elif hint == "Entrance":
                        # Variable(s): `obj` (object); named state retained for the surrounding calculation or subsequent calls.
                        obj = self.multiworld.get_entrance(name, player or self.player)
                except Exception:
                    # Variable(s): `obj` (object); named state retained for the surrounding calculation or subsequent calls.
                    obj = None
            if obj is None:
                self._record("unsupported", name, False, f"can_reach({hint}) target could not be resolved")
                return False
            if hint in {"Location", "Entrance"}:
                # APWorlds frequently gate Time Rifts and similar entrances with
                # state.can_reach(<completion location>, "Location", player).  The
                # old adapter evaluated that call but recorded nothing, causing the
                # containing lambda to be reported as OPAQUE.  Record both the parent
                # region and final reach predicate while still allowing nested access
                # rules to contribute their own item/event traces.
                region = str(getattr(getattr(obj, "parent_region", None), "name", "") or "")
                parent_ok = region in self.reachable_regions
                if not parent_ok:
                    self._record("region", region or name, False, f"Parent region for {hint} {name!r} is not reachable")
                    return False
                rule_ok = bool(getattr(obj, "access_rule", lambda _s: True)(self))
                self._record("region", name, rule_ok, f"Can reach {hint} {name!r} (parent region: {region})")
                return rule_ok
            self._record("unsupported", name, False, f"Unsupported can_reach resolution hint: {hint}")
            return False
        finally:
            self._reach_guard.discard(key)

    # /**
    #  * Function: can_reach_region
    #  * Purpose: Perform the can reach region operation while keeping the surrounding subsystem state consistent.
    #  * @param region: Region supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def can_reach_region(self, region: str, player: int | None = None) -> bool:
        # Variable(s): `ok` (ok); named state retained for the surrounding calculation or subsequent calls.
        """Return can reach region."""
        ok = str(region) in self.reachable_regions
        self._record("region", str(region), ok, "reachable" if ok else "not reachable")
        return ok

    # /**
    #  * Function: __getattr__
    #  * Purpose: Perform the getattr operation while keeping the surrounding subsystem state consistent.
    #  * @param name: Name supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def __getattr__(self, name: str) -> Any:
        """Handle getattr."""
        self._record("unsupported", name, False, f"CollectionState.{name}")
        raise UnsupportedStateOperation(f"CollectionState.{name} is not implemented by native AP adapter")


# /**
#  * Function: _access_ok
#  * Purpose: Perform the access ok operation while keeping the surrounding subsystem state consistent.
#  * @param obj: Object supplied by the caller; see type hints and call sites for domain constraints.
#  * @param state: State supplied by the caller; see type hints and call sites for domain constraints.
#  * @param errors: Errors supplied by the caller; see type hints and call sites for domain constraints.
#  * @param label: Label supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _access_ok(obj: Any, state: NativeAPState, errors: list[str], label: str) -> bool:
    # Variable(s): `rule` (rule); named state retained for the surrounding calculation or subsequent calls.
    """Handle access ok."""
    rule = getattr(obj, "access_rule", None)
    if not callable(rule):
        return True
    try:
        # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
        value = rule(state)
        if isinstance(value, bool):
            return value
        errors.append(f"{label}: access_rule returned non-boolean {type(value).__name__}")
        return False
    except Exception as exc:
        # Variable(s): `msg` (message); named state retained for the surrounding calculation or subsequent calls.
        msg = f"{label}: {type(exc).__name__}: {exc}"
        if msg not in errors:
            errors.append(msg)
        return False


# /**
#  * Function: _starting_regions
#  * Purpose: Perform the starting regions operation while keeping the surrounding subsystem state consistent.
#  * @param multiworld: Multiworld supplied by the caller; see type hints and call sites for domain constraints.
#  * @param world: World supplied by the caller; see type hints and call sites for domain constraints.
#  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
#  * @param regions: Regions supplied by the caller; see type hints and call sites for domain constraints.
#  * @param errors: Errors supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _starting_regions(multiworld: Any, world: Any, player: int, regions: list[Any], errors: list[str] | None = None) -> set[str]:
    """Return the APWorld-authoritative origin region(s).

    Archipelago's ``World.origin_region_name`` defaults to ``Menu`` but many
    worlds deliberately override it, and some (including Little Witch Nobeta)
    set it dynamically from slot options during ``connect_entrances``.  Native
    traversal must seed from that value rather than assuming the graph has a
    root node.
    """
    # Variable(s): `region_names` (region names); named state retained for the surrounding calculation or subsequent calls.
    region_names = {str(getattr(r, "name", "") or "") for r in regions}
    # Variable(s): `origin` (origin); named state retained for the surrounding calculation or subsequent calls.
    origin = str(getattr(world, "origin_region_name", "") or "")
    if origin:
        if origin in region_names:
            return {origin}
        if errors is not None:
            errors.append(f"Origin region {origin!r} was declared by the APWorld but is absent from the generated graph")

    # Compatibility fallback for worlds which do not expose a usable origin.
    # Variable(s): `menu` (menu); named state retained for the surrounding calculation or subsequent calls.
    menu = {name for name in region_names if name == "Menu"}
    if menu:
        return menu
    # Variable(s): `incoming` (incoming); named state retained for the surrounding calculation or subsequent calls.
    incoming: set[str] = set()
    # Loop variable(s): `region` (region); each iteration represents the next value from the iterable below.
    for region in regions:
        # Loop variable(s): `ent` (ent); each iteration represents the next value from the iterable below.
        for ent in getattr(region, "exits", []) or []:
            # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
            target = getattr(ent, "connected_region", None)
            if target is not None:
                incoming.add(str(getattr(target, "name", "")))
    # Variable(s): `roots` (roots); named state retained for the surrounding calculation or subsequent calls.
    roots = {str(getattr(r, "name", "")) for r in regions if str(getattr(r, "name", "")) not in incoming}
    return {x for x in roots if x}


def _apply_frlg_native_reachability_crosscheck(*, result: APAdapterSnapshot, multiworld: Any, world: Any, player: int, inventory: Counter[str]) -> None:
    """Conservatively cross-check FRLG reachability with Archipelago's CollectionState.

    Pokemon FireRed/LeafGreen exposes a dense graph with option-filtered roadblocks,
    HM/badge helpers, Cycling Road bicycle requirements, and randomized starting
    towns.  WayFinder's lightweight state adapter is useful for explanations, but
    the AP core's CollectionState is the authoritative reachability implementation.
    Intersecting with it prevents a permissive reconstructed path from making an
    entire downstream area (notably Route 12/Fuchsia) appear reachable.

    This function can only remove reachability; it never makes a check or region
    more permissive.  If the native cross-check cannot be constructed, WayFinder
    retains the normal adapter result and records the diagnostic instead.
    """
    if str(getattr(world, "game", "") or "") != "Pokemon FireRed and LeafGreen":
        return

    try:
        from BaseClasses import CollectionState

        native_state = CollectionState(multiworld)

        # CollectionState normally includes precollected items already. Add only
        # the deficit represented by the live server inventory so start inventory
        # is not accidentally counted twice.
        for item_name, wanted_count in Counter(inventory).items():
            try:
                current_count = int(native_state.count(str(item_name), player))
            except Exception:
                current_count = 0
            for _ in range(max(0, int(wanted_count) - current_count)):
                native_state.collect(world.create_item(str(item_name)), True)

        # Sweep AP event locations (e.g. generated progression flags) before
        # asking the native graph which regions and locations are reachable.
        sweep = getattr(native_state, "sweep_for_advancements", None)
        if callable(sweep):
            sweep()

        native_regions: set[str] = set()
        native_locations: set[str] = set()
        native_entrances: set[str] = set()

        for region in getattr(multiworld, "regions", []) or []:
            if int(getattr(region, "player", player) or player) != player:
                continue
            region_name = str(getattr(region, "name", "") or "")
            try:
                region_ok = bool(region.can_reach(native_state))
            except Exception:
                region_ok = False
            if region_ok:
                native_regions.add(region_name)

            for entrance in getattr(region, "exits", []) or []:
                entrance_name = str(getattr(entrance, "name", "") or "")
                try:
                    if bool(entrance.can_reach(native_state)):
                        native_entrances.add(entrance_name)
                except Exception:
                    _ignored("intentional best-effort fallback")

            for location in getattr(region, "locations", []) or []:
                if getattr(location, "address", None) is None:
                    continue
                location_name = str(getattr(location, "name", "") or "")
                try:
                    if bool(location.can_reach(native_state)):
                        native_locations.add(location_name)
                except Exception:
                    _ignored("intentional best-effort fallback")

        result.reachable_regions.intersection_update(native_regions)
        result.reachable_locations.intersection_update(native_locations)
        result.reachable_entrances.intersection_update(native_entrances)
    except Exception as exc:
        message = f"FRLG native reachability cross-check unavailable: {type(exc).__name__}: {exc}"
        if message not in result.errors:
            result.errors.append(message)


# /**
#  * Function: _item_groups
#  * Purpose: Perform the item groups operation while keeping the surrounding subsystem state consistent.
#  * @param world: World supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _item_groups(world: Any) -> dict[str, set[str]]:
    # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
    """Handle item groups."""
    raw = getattr(world, "item_name_groups", {}) or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): {str(x) for x in v} for k, v in raw.items() if isinstance(v, (set, list, tuple, frozenset))}


# /**
#  * Function: trace_access_rule
#  * Purpose: Perform the trace access rule operation while keeping the surrounding subsystem state consistent.
#  * @param obj: Object supplied by the caller; see type hints and call sites for domain constraints.
#  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
#  * @param inventory: Inventory supplied by the caller; see type hints and call sites for domain constraints.
#  * @param reachable_regions: Reachable regions supplied by the caller; see type hints and call sites for domain constraints.
#  * @param events: Events supplied by the caller; see type hints and call sites for domain constraints.
#  * @param groups: Groups supplied by the caller; see type hints and call sites for domain constraints.
#  * @param multiworld: Multiworld supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def trace_access_rule(obj: Any, *, player: int, inventory: Counter[str], reachable_regions: set[str], events: set[str], groups: dict[str, set[str]], multiworld: Any) -> dict[str, Any]:
    """Evaluate one AP callable while recording observable CollectionState predicates.

    Arbitrary Python callables do not expose a lossless AST, so this reports the
    predicates the rule actually consulted. This is authoritative for state API
    calls and deliberately labels opaque/direct helper access as such.
    """
    # Variable(s): `trace` (trace); named state retained for the surrounding calculation or subsequent calls.
    trace: list[dict[str, Any]] = []
    # Variable(s): `state` (state); named state retained for the surrounding calculation or subsequent calls.
    state = NativeAPState(player, Counter(inventory), set(reachable_regions), set(events), groups, multiworld, trace=trace)
    # Variable(s): `rule` (rule); named state retained for the surrounding calculation or subsequent calls.
    rule = getattr(obj, "access_rule", None)
    # Variable(s): `module` (module); named state retained for the surrounding calculation or subsequent calls.
    module = str(getattr(rule, "__module__", "") or getattr(type(obj), "__module__", "") or "unknown")
    helper_calls: list[dict[str, Any]] = []
    rule_identity = _rule_identity(rule) if callable(rule) else {}
    rule_file = rule_identity.get("file", "")

    # Collect actual returns from helpers across APWorld modules, with no locals.
    active_frames = {}
    def _profile(frame, event, arg):
        """Handle profile."""
        filename = str(frame.f_code.co_filename)
        module_name = str(frame.f_globals.get('__name__', ''))
        relevant = filename == rule_file or module_name.startswith(('worlds.', 'rule_builder.'))
        if event == 'call' and relevant and len(helper_calls) < 128:
            row = {'kind': 'helper', 'name': getattr(frame.f_code, 'co_qualname', frame.f_code.co_name),
                   'result': None, 'file': filename, 'line': frame.f_lineno,
                   'detail': f'APWorld function at {filename}:{frame.f_lineno}'}
            helper_calls.append(row)
            active_frames[id(frame)] = row
        elif event == 'return':
            row = active_frames.pop(id(frame), None)
            if row is not None:
                row['result'] = arg if type(arg) is bool else None
                row['return_type'] = type(arg).__name__

    error_record = {}
    previous_profile = sys.getprofile()
    try:
        if callable(rule):
            sys.setprofile(_profile)
        # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
        value = True if not callable(rule) else rule(state)
        # Variable(s): `satisfied` (satisfied); named state retained for the surrounding calculation or subsequent calls.
        satisfied = bool(value) if isinstance(value, bool) else False
        # Variable(s): `error` (error); named state retained for the surrounding calculation or subsequent calls.
        error = "" if isinstance(value, bool) else f"Rule returned {type(value).__name__}, expected bool"
    except Exception as exc:
        # Variable(s): `satisfied` (satisfied); named state retained for the surrounding calculation or subsequent calls.
        satisfied = False; error = f"{type(exc).__name__}: {exc}"
        import traceback
        error_record = {'code': 'UNRESOLVABLE_HELPER' if isinstance(exc, (NameError, AttributeError, RecursionError, UnsupportedStateOperation)) else 'RULE_EXCEPTION',
                        'type': type(exc).__name__, 'message': str(exc),
                        'frames': [{'file': f.filename, 'line': f.lineno, 'function': f.name}
                                   for f in traceback.extract_tb(exc.__traceback__)[-32:]]}
    finally:
        if callable(rule):
            sys.setprofile(previous_profile)
    # Variable(s): `missing` (missing); named state retained for the surrounding calculation or subsequent calls.
    missing = []
    # Variable(s): `consulted` (consulted); named state retained for the surrounding calculation or subsequent calls.
    consulted = []
    # Loop variable(s): `row` (row); each iteration represents the next value from the iterable below.
    for row in trace:
        if row not in consulted: consulted.append(row)
        if row.get("kind") in {"item", "item_count", "region"} and row.get("result") is False:
            missing.append(row)
        if row.get("kind") == "unsupported":
            missing.append(row)
    # Helper frames explain which APWorld predicate path was executed.  Direct
    # prog_items reads are now captured by _TracingProgItemsCounter above, so a
    # helper is no longer labelled opaque merely because it bypasses state.has().
    if trace:
        for helper in helper_calls:
            if helper not in consulted:
                consulted.append(helper)
    if not trace and callable(rule):
        if _is_archipelago_framework_rule(rule_identity):
            # BaseClasses' default lambda is an unconditional local rule, not an
            # opaque world helper.  The explanation post-pass can walk backwards
            # through parent-region entrances to recover the actual route rules.
            detail = "No local access predicate; using Archipelago's default framework rule."
            if rule_identity.get("file"):
                detail += f" Framework: {rule_identity['file']}:{rule_identity.get('line', 0)}."
            consulted.append({"kind":"unconditional", "name":"No local requirement", "result":satisfied, "detail":detail})
        else:
            detail = "Rule executed without an observable CollectionState/prog_items predicate."
            if rule_identity.get("file"):
                detail += f" Rule origin: {rule_identity['file']}:{rule_identity.get('line', 0)}."
            consulted.append({"kind":"opaque", "name":rule_identity.get("name", "APWorld helper"), "result":satisfied, "detail":detail})
    from wayfinder.logic.rule_explanation import explain
    from wayfinder.diagnostics import sanitize
    analysis = explain(rule, player=player, inventory=inventory,
                       reachable_regions=reachable_regions, events=events, groups=groups)
    if not error and not satisfied:
        unresolved = [r.get('detail', r.get('name', '')) for r in trace if r.get('kind') == 'unsupported']
        if unresolved:
            error = '; '.join(unresolved)
            error_record = {'code': 'UNRESOLVABLE_HELPER', 'message': error}
    if error and not error_record:
        error_record = {'code': 'NON_BOOLEAN_RULE', 'message': error}
    # A static proof must agree with actual execution before it is presented.
    if satisfied:
        analysis['impossible_rule'] = False
    return sanitize({"satisfied": satisfied, "module": module, "consulted": consulted,
                     "missing": missing, "error": error, "rule_identity": rule_identity,
                     "helper_trace": helper_calls, "evaluation_error": error_record,
                     "logic_state": 'ERROR' if error else 'SATISFIED' if satisfied else 'BLOCKED',
                     **analysis})


# /**
#  * Function: evaluate_generated_world
#  * Purpose: Evaluate generated world against the current tracker state.
#  * @param multiworld: Multiworld supplied by the caller; see type hints and call sites for domain constraints.
#  * @param world: World supplied by the caller; see type hints and call sites for domain constraints.
#  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
#  * @param inventory: Inventory supplied by the caller; see type hints and call sites for domain constraints.
#  * @param checked_location_names: Checked location names supplied by the caller; see type hints and call sites for domain constraints.
#  * @param known_events: Known events supplied by the caller; see type hints and call sites for domain constraints.
#  * @param max_iterations: Max iterations supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def evaluate_generated_world(*, multiworld: Any, world: Any, player: int, inventory: Counter[str], checked_location_names: set[str] | None = None, known_events: set[str] | None = None, max_iterations: int = 512) -> APAdapterSnapshot:
    # Variable(s): `regions` (regions); named state retained for the surrounding calculation or subsequent calls.
    """Handle evaluate generated world."""
    regions = [r for r in (getattr(multiworld, "regions", []) or []) if int(getattr(r, "player", player) or player) == player]
    # Variable(s): `result` (result); named state retained for the surrounding calculation or subsequent calls.
    result = APAdapterSnapshot(game=str(getattr(world, "game", "") or ""), player=player)
    result.checked_locations = set(checked_location_names or set())
    result.events = set(known_events or set())
    result.reachable_regions = _starting_regions(multiworld, world, player, regions, result.errors)
    # Variable(s): `groups` (groups); named state retained for the surrounding calculation or subsequent calls.
    groups = _item_groups(world)

    # Loop variable(s): `iteration` (iteration); each iteration represents the next value from the iterable below.
    for iteration in range(1, max_iterations + 1):
        # Variable(s): `changed` (changed); named state retained for the surrounding calculation or subsequent calls.
        changed = False
        # Variable(s): `state` (state); named state retained for the surrounding calculation or subsequent calls.
        state = NativeAPState(player, inventory, result.reachable_regions, result.events, groups, multiworld)

        # Region traversal to a local fixed point.
        # Variable(s): `traversal_changed` (traversal changed); named state retained for the surrounding calculation or subsequent calls.
        traversal_changed = True
        while traversal_changed:
            # Variable(s): `traversal_changed` (traversal changed); named state retained for the surrounding calculation or subsequent calls.
            traversal_changed = False
            # Loop variable(s): `region` (region); each iteration represents the next value from the iterable below.
            for region in regions:
                # Variable(s): `source` (source); named state retained for the surrounding calculation or subsequent calls.
                source = str(getattr(region, "name", "") or "")
                if source not in result.reachable_regions:
                    continue
                # Loop variable(s): `ent` (ent); each iteration represents the next value from the iterable below.
                for ent in getattr(region, "exits", []) or []:
                    # Variable(s): `target_obj` (target obj); named state retained for the surrounding calculation or subsequent calls.
                    target_obj = getattr(ent, "connected_region", None)
                    # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
                    target = str(getattr(target_obj, "name", "") or "") if target_obj is not None else ""
                    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
                    name = str(getattr(ent, "name", "") or f"{source} -> {target}")
                    if not target:
                        continue
                    if _access_ok(ent, state, result.errors, f"Entrance {name}"):
                        result.reachable_entrances.add(name)
                        if target not in result.reachable_regions:
                            result.reachable_regions.add(target)
                            # Variable(s): `traversal_changed` (traversal changed), `changed` (changed); named state retained for the surrounding calculation or subsequent calls.
                            traversal_changed = changed = True

        # Variable(s): `state` (state); named state retained for the surrounding calculation or subsequent calls.
        state = NativeAPState(player, inventory, result.reachable_regions, result.events, groups, multiworld)
        # AP event locations have no address and a locked item. Sweep them and
        # add the event item to both the event set and rule-visible inventory.
        # Loop variable(s): `region` (region); each iteration represents the next value from the iterable below.
        for region in regions:
            # Variable(s): `rname` (rname); named state retained for the surrounding calculation or subsequent calls.
            rname = str(getattr(region, "name", "") or "")
            if rname not in result.reachable_regions:
                continue
            # Loop variable(s): `loc` (loc); each iteration represents the next value from the iterable below.
            for loc in getattr(region, "locations", []) or []:
                if getattr(loc, "address", None) is not None:
                    continue
                # Variable(s): `item_obj` (item obj); named state retained for the surrounding calculation or subsequent calls.
                item_obj = getattr(loc, "item", None)
                # Variable(s): `item_name` (item name); named state retained for the surrounding calculation or subsequent calls.
                item_name = str(getattr(item_obj, "name", "") or "")
                if not item_name or item_name in result.events:
                    continue
                # Variable(s): `lname` (lname); named state retained for the surrounding calculation or subsequent calls.
                lname = str(getattr(loc, "name", "") or "")
                if _access_ok(loc, state, result.errors, f"Event {lname}"):
                    result.events.add(item_name)
                    inventory[item_name] += 1
                    # Variable(s): `changed` (changed); named state retained for the surrounding calculation or subsequent calls.
                    changed = True

        if not changed:
            result.iterations = iteration
            break
    else:
        result.iterations = max_iterations
        result.errors.append(f"Native AP adapter did not stabilize after {max_iterations} iterations")

    # Compute ordinary location reachability before applying the FRLG native
    # CollectionState cross-check.  The cross-check intersects all three final
    # reachability sets (regions, entrances, locations), so running it before
    # this location pass would make the location intersection a no-op and allow
    # lightweight-adapter false positives to be added afterwards.

    # Variable(s): `state` (state); named state retained for the surrounding calculation or subsequent calls.
    state = NativeAPState(player, inventory, result.reachable_regions, result.events, groups, multiworld)
    # Loop variable(s): `region` (region); each iteration represents the next value from the iterable below.
    for region in regions:
        # Variable(s): `rname` (rname); named state retained for the surrounding calculation or subsequent calls.
        rname = str(getattr(region, "name", "") or "")
        if rname not in result.reachable_regions:
            continue
        # Loop variable(s): `loc` (loc); each iteration represents the next value from the iterable below.
        for loc in getattr(region, "locations", []) or []:
            if getattr(loc, "address", None) is None:
                continue
            # Variable(s): `lname` (lname); named state retained for the surrounding calculation or subsequent calls.
            lname = str(getattr(loc, "name", "") or "")
            if lname in result.checked_locations:
                continue
            if _access_ok(loc, state, result.errors, f"Location {lname}"):
                result.reachable_locations.add(lname)

    # FRLG's generated world rules can depend on CollectionState behaviour that
    # the lightweight NativeAPState adapter intentionally approximates. Apply
    # the native result last so it is authoritative for regions, entrances and
    # individual checks.
    _apply_frlg_native_reachability_crosscheck(
        result=result, multiworld=multiworld, world=world, player=player, inventory=inventory
    )

    # Build explanation records after reachability stabilizes. These are kept
    # separate from traversal so diagnostics cannot affect authoritative logic.
    # Variable(s): `final_inventory` (final inventory); named state retained for the surrounding calculation or subsequent calls.
    final_inventory = Counter(inventory)
    # Variable(s): `final_state_regions` (final state regions); named state retained for the surrounding calculation or subsequent calls.
    final_state_regions = set(result.reachable_regions)
    # Loop variable(s): `region` (region); each iteration represents the next value from the iterable below.
    for region in regions:
        # Variable(s): `source` (source); named state retained for the surrounding calculation or subsequent calls.
        source = str(getattr(region, "name", "") or "")
        # Loop variable(s): `ent` (ent); each iteration represents the next value from the iterable below.
        for ent in getattr(region, "exits", []) or []:
            # Variable(s): `target_obj` (target obj); named state retained for the surrounding calculation or subsequent calls.
            target_obj = getattr(ent, "connected_region", None)
            # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
            target = str(getattr(target_obj, "name", "") or "") if target_obj is not None else ""
            # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
            name = str(getattr(ent, "name", "") or f"{source} -> {target}")
            # Variable(s): `detail` (detail); named state retained for the surrounding calculation or subsequent calls.
            detail = trace_access_rule(ent, player=player, inventory=final_inventory, reachable_regions=final_state_regions, events=result.events, groups=groups, multiworld=multiworld)
            detail.update({"name":name,"source_region":source,"target_region":target,"source_reachable":source in final_state_regions,"reachable":name in result.reachable_entrances,"kind":"entrance"})
            result.entrance_details.append(detail)
        # Loop variable(s): `loc` (loc); each iteration represents the next value from the iterable below.
        for loc in getattr(region, "locations", []) or []:
            # Variable(s): `lname` (lname); named state retained for the surrounding calculation or subsequent calls.
            lname = str(getattr(loc, "name", "") or "")
            # Variable(s): `detail` (detail); named state retained for the surrounding calculation or subsequent calls.
            detail = trace_access_rule(loc, player=player, inventory=final_inventory, reachable_regions=final_state_regions, events=result.events, groups=groups, multiworld=multiworld)
            detail.update({"name":lname,"region":source,"kind":"event" if getattr(loc,"address",None) is None else "location"})
            if getattr(loc,"address",None) is None:
                # Variable(s): `item_name` (item name); named state retained for the surrounding calculation or subsequent calls.
                item_name=str(getattr(getattr(loc,"item",None),"name","") or "")
                detail["event_item"]=item_name; detail["swept"]=item_name in result.events
                result.event_details.append(detail)
            else:
                detail["reachable"]=lname in result.reachable_locations
                result.rule_details[lname]=detail
    # Explanation walk-back: locations with AP's default local rule inherit the
    # requirements of the entrance chain that reaches their parent region.  This
    # stops BaseClasses.py's permissive lambda from appearing as a fake opaque
    # requirement and lets Path/Logic views show the actual solver route instead.
    starting_regions = _starting_regions(multiworld, world, player, regions, [])
    for location_name, detail in result.rule_details.items():
        consulted_rows = list(detail.get("consulted", []) or [])
        only_unconditional = bool(consulted_rows) and all(row.get("kind") == "unconditional" for row in consulted_rows)
        if not only_unconditional:
            continue
        region_name = str(detail.get("region", "") or "")
        inherited_rows, route_chain = _route_rule_rows_for_region(region_name, starting_regions, result.entrance_details)
        if inherited_rows:
            detail["consulted"] = inherited_rows
            detail["missing"] = [row for row in inherited_rows if row.get("kind") in {"item", "region", "unsupported"} and row.get("result") is False]
            detail["rule_origin"] = {"kind": "region_path", "region": region_name}
            detail["route_rule_path"] = [
                {"name": row.get("name", ""), "source_region": row.get("source_region", ""), "target_region": row.get("target_region", ""), "satisfied": row.get("satisfied", False)}
                for row in route_chain
            ]
        elif region_name in starting_regions:
            detail["consulted"] = [{
                "kind": "unconditional",
                "name": "Starting region",
                "result": True,
                "detail": f"{region_name} is a starting region; this location has no additional local requirement.",
            }]
            detail["rule_origin"] = {"kind": "starting_region", "region": region_name}

    from wayfinder.logic.rule_explanation import annotate_events
    annotate_events([*result.rule_details.values(), *result.entrance_details, *result.event_details],
                    {d.get('event_item') for d in result.event_details})
    result.unsupported_state_calls = sorted({str(x) for x in result.errors if "CollectionState." in str(x) and "not implemented" in str(x)})
    return result
