"""Shared progression intelligence for WayFinder GUI features.

This module deliberately consumes GUI/runtime snapshots without importing Tk.  The
same conservative analysis feeds unlock impact, Goal, I'm Stuck?, progression graph,
multiworld context and route scoring.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

@dataclass(frozen=True)
class UnlockImpact:
    """Provide unlock impact behavior."""
    item: str
    count_delta: int
    newly_reachable_locations: tuple[str, ...] = ()
    newly_reachable_regions: tuple[str, ...] = ()
    newly_reachable_entrances: tuple[str, ...] = ()
    goal_changed: bool = False

@dataclass(frozen=True)
class WaitingAnalysis:
    """Provide waiting analysis behavior."""
    state: str
    summary: str
    blockers: tuple[str, ...] = ()
    remote_sources: tuple[str, ...] = ()
    hinted_sources: tuple[str, ...] = ()
    unknown_count: int = 0

@dataclass(frozen=True)
class GraphNode:
    """Provide graph node behavior."""
    key: str
    kind: str
    label: str
    status: str = "unknown"

@dataclass(frozen=True)
class GraphEdge:
    """Provide graph edge behavior."""
    source: str
    target: str
    label: str = "requires"

@dataclass(frozen=True)
class ProgressionGraphModel:
    """Provide progression graph model behavior."""
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()


def _inventory(snapshot: Any) -> dict[str, int]:
    """Handle inventory."""
    return {str(x.name): int(x.count) for x in (getattr(snapshot, "inventory", None) or [])}


def _locations(snapshot: Any) -> dict[str, Any]:
    """Handle locations."""
    return {str(x.name): x for x in (getattr(snapshot, "locations", None) or [])}


def detect_unlock_impact(previous: Any, current: Any) -> tuple[UnlockImpact, ...]:
    """Handle detect unlock impact."""
    before_inv, after_inv = _inventory(previous), _inventory(current)
    before_locs, after_locs = _locations(previous), _locations(current)
    newly = tuple(sorted(name for name, loc in after_locs.items()
                         if getattr(loc, "status", "") == "reachable"
                         and getattr(before_locs.get(name), "status", "") != "reachable"))
    before_regions = {getattr(x, "region", "") for x in before_locs.values() if getattr(x, "status", "") == "reachable"}
    after_regions = {getattr(x, "region", "") for x in after_locs.values() if getattr(x, "status", "") == "reachable"}
    new_regions = tuple(sorted(x for x in after_regions - before_regions if x))
    before_ent = {str(x.get("name", "")): str(x.get("status", "")) for x in (getattr(previous, "entrance_details", None) or []) if isinstance(x, dict)}
    new_ent = tuple(sorted(str(x.get("name", "")) for x in (getattr(current, "entrance_details", None) or [])
                           if isinstance(x, dict) and str(x.get("status", "")) in {"reachable", "resolved", "connected"}
                           and before_ent.get(str(x.get("name", ""))) not in {"reachable", "resolved", "connected"}))
    bg = bool((getattr(previous, "goal_detail", None) or {}).get("satisfied"))
    ag = bool((getattr(current, "goal_detail", None) or {}).get("satisfied"))
    changed_items = [(name, count - before_inv.get(name, 0)) for name, count in after_inv.items() if count > before_inv.get(name, 0)]
    if not changed_items:
        return ()
    # A snapshot is atomic, so when several items arrive between snapshots exact causal
    # attribution is unknowable without speculative re-evaluation. Report the shared delta.
    return tuple(UnlockImpact(name, delta, newly, new_regions, new_ent, (not bg and ag)) for name, delta in changed_items)


def waiting_analysis(snapshot: Any) -> WaitingAnalysis:
    """Handle waiting analysis."""
    locs = [x for x in (getattr(snapshot, "locations", None) or []) if not getattr(x, "ignored", False) and getattr(x, "status", "") != "checked"]
    reachable = [x for x in locs if getattr(x, "status", "") == "reachable"]
    if reachable:
        return WaitingAnalysis("local", f"{len(reachable)} local unchecked check(s) are reachable; local progression is not exhausted.")
    hints = getattr(snapshot, "hints", None) or []
    hinted = tuple(sorted({str(h.get("location")) for h in hints if isinstance(h, dict) and h.get("location")}))
    remote = tuple(sorted({str(getattr(x, "source_player", "")) for x in (getattr(snapshot, "inventory", None) or []) if getattr(x, "source_player", "") and str(getattr(x, "source_player", "")) != str(getattr(snapshot, "slot_name", ""))}))
    blockers: list[str] = []
    for loc in locs:
        reason = str(getattr(loc, "unknown_reason", "") or "").strip()
        if reason and reason not in blockers:
            blockers.append(reason)
    goal = getattr(snapshot, "goal_detail", None) or {}
    for value in goal.get("missing", []) if isinstance(goal.get("missing", []), list) else []:
        text = str(value).strip()
        if text and text not in blockers:
            blockers.append(text)
    unknown = sum(1 for x in locs if getattr(x, "status", "") in {"unknown", "untracked", ""})
    if unknown:
        return WaitingAnalysis('unknown', 'Progression cannot be determined while check logic is unknown; inspect the reported reasons.', tuple(blockers[:12]), remote[:12], hinted[:12], unknown)
    if hinted:
        state = "hinted"
        summary = "Local progression is exhausted; useful known information exists in hints."
    elif remote:
        state = "remote"
        summary = "Local progression is exhausted; received-item history shows multiworld/remote progression context."
    else:
        state = "unknown"
        summary = "Local progression is exhausted and no safe known source of the next progression is exposed yet."
    return WaitingAnalysis(state, summary, tuple(blockers[:12]), remote[:12], hinted[:12], unknown)


def route_score(path: Any, strategy: str = "fastest", personal: dict[str, float] | None = None) -> tuple[float, str]:
    """Handle route score."""
    steps = list(getattr(path, "steps", None) or [])
    requirement_count = 0
    region_count = 0
    for step in steps:
        if getattr(step, "source_region", "") or getattr(step, "target_region", ""):
            region_count += 1
        tree = getattr(step, "tree", None)
        if tree is not None:
            stack = [tree]
            while stack:
                node = stack.pop(); stack.extend(getattr(node, "children", None) or [])
                if not (getattr(node, "children", None) or []): requirement_count += 1
    strategy = str(strategy or "fastest").casefold()
    personal = personal or {}
    if strategy == "fewest requirements":
        score = -float(requirement_count)
    elif strategy == "most checks along route":
        score = float(region_count * personal.get("region_weight", 1.0) - requirement_count * .15)
    elif strategy == "personal":
        score = float(region_count * personal.get("region_weight", 1.0) - requirement_count * personal.get("requirement_penalty", .5) - len(steps) * personal.get("step_penalty", .25))
    else:
        score = -float(len(steps))
    return score, f"{len(steps)} steps • {requirement_count} requirements • {region_count} region transitions"


def build_progression_graph(snapshot: Any) -> ProgressionGraphModel:
    """Return build progression graph."""
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    def add(kind: str, label: str, status: str = "unknown") -> str:
        """Handle add."""
        key = f"{kind}:{label}"; nodes.setdefault(key, GraphNode(key, kind, label, status)); return key
    # Locations and their regions are directly known.
    for loc in getattr(snapshot, "locations", None) or []:
        lkey = add("location", str(loc.name), str(getattr(loc, "status", "unknown")))
        region = str(getattr(loc, "region", "") or "")
        if region:
            reachable_regions = set(getattr(snapshot, "current_reachable_regions", None) or getattr(snapshot, "in_logic_regions", None) or [])
            rkey = add("region", region, "reachable" if region in reachable_regions else "blocked")
            edges.append(GraphEdge(rkey, lkey, "contains"))
    # Structured rule detail is the safe source for explicit dependencies.
    for target, detail in (getattr(snapshot, "rule_details", None) or {}).items():
        target_key = add("location", str(target), str(getattr(_locations(snapshot).get(str(target)), "status", "unknown")))
        tokens = detail.get("tokens", []) if isinstance(detail, dict) else []
        for token in tokens if isinstance(tokens, list) else []:
            if not isinstance(token, dict): continue
            text = str(token.get("text", "") or token.get("label", "")).strip()
            kind = str(token.get("kind", "item") or "item").casefold()
            if text and kind in {"item", "event", "region", "entrance"}:
                edges.append(GraphEdge(add(kind, text), target_key))
    for ent in getattr(snapshot, "entrance_details", None) or []:
        if not isinstance(ent, dict):
            continue
        name = str(ent.get("name", "") or ent.get("entrance", "")).strip()
        if not name:
            continue

        # The native logic engine exposes the authoritative live result as a
        # boolean ``reachable`` field.  Older progression-graph code looked only
        # for a textual ``status`` field, which entrance_details normally does
        # not contain, so every entrance was rendered as ``unknown`` even while
        # the Logic Engine tab correctly showed Reachable/Blocked.
        explicit_status = str(ent.get("status", "") or "").strip().casefold()
        if explicit_status and explicit_status not in {"unknown", "untracked"}:
            entrance_status = explicit_status
        elif isinstance(ent.get("reachable"), bool):
            entrance_status = "reachable" if ent.get("reachable") else "blocked"
        elif isinstance(ent.get("satisfied"), bool):
            entrance_status = "reachable" if ent.get("satisfied") else "blocked"
        else:
            entrance_status = "unknown"

        ekey = add("entrance", name, entrance_status)
        source = str(ent.get("source_region", "") or ent.get("source", "")).strip()
        target = str(ent.get("target_region", "") or ent.get("target", "")).strip()
        if source:
            edges.append(GraphEdge(add("region", source), ekey, "leads via"))
        if target:
            edges.append(GraphEdge(ekey, add("region", target), "opens"))

    # Prefer structured event_details when available so the graph mirrors the
    # Logic Engine tab's Swept/Pending state instead of treating every known
    # event as satisfied.
    event_details = getattr(snapshot, "event_details", None) or []
    seen_events: set[str] = set()
    for ev in event_details:
        if not isinstance(ev, dict):
            continue
        name = str(ev.get("name", "") or ev.get("event_item", "")).strip()
        if not name:
            continue
        seen_events.add(name)
        if isinstance(ev.get("swept"), bool):
            event_status = "satisfied" if ev.get("swept") else "pending"
        elif isinstance(ev.get("satisfied"), bool):
            event_status = "satisfied" if ev.get("satisfied") else "pending"
        else:
            event_status = str(ev.get("status", "unknown") or "unknown").casefold()
        add("event", name, event_status)

    for ev in getattr(snapshot, "events", None) or []:
        name = str(ev)
        if name not in seen_events:
            add("event", name, "satisfied")
    goal = getattr(snapshot, "goal_detail", None) or {}
    if goal:
        gkey = add("goal", str(goal.get("name") or goal.get("module") or "Goal"), "satisfied" if goal.get("satisfied") else "blocked")
        for missing in goal.get("missing", []) if isinstance(goal.get("missing", []), list) else []:
            edges.append(GraphEdge(add("item", str(missing)), gkey))
    return ProgressionGraphModel(tuple(nodes.values()), tuple(edges))
