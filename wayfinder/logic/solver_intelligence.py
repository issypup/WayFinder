"""Higher-level analysis helpers for WayFinder's Path Explorer.

The runtime remains authoritative for reachability.  These helpers deliberately
operate on the serialized/GUI path model, adding conservative presentation and
diagnostic intelligence without inventing APWorld logic.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Iterable

NORMAL_KINDS = {
    "and": "ALL", "all": "ALL", "or": "ANY", "any": "ANY",
    "item": "ITEM", "item_count": "COUNT", "count": "COUNT", "atleast": "COUNT",
    "event": "EVENT", "region": "REGION", "entrance": "REGION",
    "option": "OPTION", "value": "OPTION", "comparison": "COMPARISON",
    "opaque": "UNKNOWN", "unconditional": "ALL", "route_step": "REGION",
}

def normalized_kind(kind: str) -> str:
    """Handle normalized kind."""
    return NORMAL_KINDS.get(str(kind or "").casefold(), str(kind or "RULE").upper())

def walk_rules(node: Any) -> Iterable[Any]:
    """Handle walk rules."""
    if node is None: return
    yield node
    for child in getattr(node, "children", None) or []:
        yield from walk_rules(child)

def branch_cost(node: Any) -> tuple[int, int, int]:
    """Rank a branch by missing leaves, missing quantity, then complexity."""
    leaves=[n for n in walk_rules(node) if not (getattr(n,"children",None) or [])]
    missing=sum(1 for n in leaves if getattr(n,"satisfied",None) is False)
    quantity=0
    for n in leaves:
        if getattr(n,"satisfied",None) is False:
            have=getattr(n,"have",None); req=getattr(n,"required",None)
            if isinstance(have,int) and isinstance(req,int): quantity += max(0,req-have)
            else: quantity += 1
    return missing, quantity, len(leaves)

def rank_or_branches(node: Any) -> list[Any]:
    """Handle rank or branches."""
    children=list(getattr(node,"children",None) or [])
    if normalized_kind(getattr(node,"kind","")) != "ANY": return children
    return sorted(children,key=branch_cost)

def path_cycles(path: Any) -> tuple[str,...]:
    """Handle path cycles."""
    seen=set(); cycles=[]
    for step in getattr(path,"steps",None) or []:
        edge=(str(getattr(step,"source_region","") or ""),str(getattr(step,"target_region","") or ""))
        if edge[0] and edge[1] and edge[0] == edge[1] and getattr(step,"kind","") == "entrance": cycles.append(f"Self-cycle: {edge[0]}")
        key=(getattr(step,"kind",""),getattr(step,"title",""),edge)
        if key in seen: cycles.append(f"Repeated solver step: {getattr(step,'title','')}")
        seen.add(key)
    # region recurrence after moving away is a stronger graph cycle signal.
    regions=[]
    for step in getattr(path,"steps",None) or []:
        r=str(getattr(step,"target_region","") or "")
        if not r: continue
        if r in regions and (not regions or regions[-1] != r): cycles.append(f"Route returns to region: {r}")
        regions.append(r)
    return tuple(dict.fromkeys(cycles))

def dead_route_reasons(path: Any) -> tuple[str,...]:
    """Handle dead route reasons."""
    reasons=[]; blocked=False
    for step in getattr(path,"steps",None) or []:
        if getattr(step,"kind","") == "region": continue
        if getattr(step,"reachable",None) is False:
            if not blocked: blocked=True
            else: reasons.append(f"{getattr(step,'title','')} is downstream of an earlier blocked step and is not currently actionable.")
    if path_cycles(path): reasons.append("The structural route contains a cycle; do not treat it as a usable progression route until the cycle is resolved.")
    return tuple(reasons)

def provenance_rows(path: Any) -> tuple[str,...]:
    """Handle provenance rows."""
    rows=[]
    for i,step in enumerate(getattr(path,"steps",None) or [],1):
        tree=getattr(step,"tree",None); module=str(getattr(tree,"detail","") or "unknown") if tree else "none"
        rows.append(f"{i}. {getattr(step,'kind','rule').upper()} — {getattr(step,'title','')} — rule origin/module: {module}")
        for node in walk_rules(tree):
            detail=str(getattr(node,"detail","") or "")
            if detail and (".py:" in detail or "helper" in detail.casefold() or "via entrance" in detail.casefold()):
                rows.append(f"   {normalized_kind(getattr(node,'kind',''))}: {getattr(node,'label','')} — {detail}")
    return tuple(rows)

def reconstruction_audit(path: Any) -> tuple[str,...]:
    """Handle reconstruction audit."""
    findings=[]
    for step in getattr(path,"steps",None) or []:
        if getattr(step,"kind","") != "location": continue
        tree=getattr(step,"tree",None)
        children=list(getattr(tree,"children",None) or []) if tree else []
        module=str(getattr(tree,"detail","") or "") if tree else ""
        if not children:
            findings.append(f"{step.title}: no structured custom predicates were reconstructed; verify whether the APWorld intentionally leaves this location unconditional.")
        elif module.casefold() in {"baseclasses", "baseclasses.py"}:
            findings.append(f"{step.title}: only Archipelago framework/default provenance is visible; a later set_rule/add_rule assignment may have been missed.")
        elif any(normalized_kind(getattr(n,"kind","")) == "UNKNOWN" for n in walk_rules(tree)):
            findings.append(f"{step.title}: at least one helper remains opaque/unknown after reconstruction.")
    return tuple(findings)

def searchable_entries(path: Any) -> tuple[tuple[str,str],...]:
    """Handle searchable entries."""
    out=[]
    for step in getattr(path,"steps",None) or []:
        out.append((str(getattr(step,"title","")),str(getattr(step,"kind","step"))))
        for n in walk_rules(getattr(step,"tree",None)):
            label=str(getattr(n,"label","") or "")
            if label: out.append((label,normalized_kind(getattr(n,"kind",""))))
    return tuple(out)

def remote_dependency_lines(snapshot: Any, path: Any) -> tuple[str,...]:
    """Conservative multiworld awareness using hints/source metadata only."""
    missing={str(getattr(n,"label","")) for s in getattr(path,"steps",None) or [] for n in walk_rules(getattr(s,"tree",None)) if getattr(n,"satisfied",None) is False}
    lines=[]
    for hint in getattr(snapshot,"hints",None) or []:
        if not isinstance(hint,dict): continue
        item=str(hint.get("item") or hint.get("item_name") or "")
        if item not in missing: continue
        finder=str(hint.get("finding_player") or hint.get("finder") or hint.get("source_player") or "")
        receiver=str(hint.get("receiving_player") or hint.get("receiver") or "")
        if finder and receiver and finder != receiver: lines.append(f"{item}: hinted as remote/multiworld progression ({finder} → {receiver}).")
        elif finder and finder != str(getattr(snapshot,"slot_name","") or ""): lines.append(f"{item}: hinted source belongs to another player ({finder}).")
    return tuple(dict.fromkeys(lines))

def goal_target(snapshot: Any) -> str:
    """Resolve the best concrete APWorld target for the completion condition.

    Resolution order is intentionally conservative:
    1. Explicit goal location exposed by the runtime/APWorld.
    2. Producer location/event for a missing completion item (for example
       ``Victory``), discovered from generated APWorld item placement.
    3. Serialized event metadata, which also covers older snapshots that do not
       yet include ``goal_detail.sources``.
    4. Goal-option text resolved from the player's generated YAML/options.
    5. The original name/module fuzzy fallback.
    """
    goal=getattr(snapshot,"goal_detail",None) or {}
    if not isinstance(goal,dict):
        return ""

    for key in ("location","target","goal_location","completion_location"):
        value=goal.get(key)
        if value:
            return str(value)

    # APWorld backtracking: a completion item/event is usually placed at a
    # concrete event location.  Prefer event producers because they represent
    # the actual completion trigger rather than a similarly named normal check.
    sources=[x for x in (goal.get("sources") or []) if isinstance(x,dict) and x.get("location")]
    if sources:
        sources.sort(key=lambda x:(not bool(x.get("event")),str(x.get("location","")).casefold()))
        return str(sources[0].get("location") or "")

    missing_items={
        str(x.get("name") or "")
        for x in (goal.get("missing") or [])
        if isinstance(x,dict) and x.get("kind")=="item" and x.get("name")
    }
    event_details=getattr(snapshot,"event_details",None) or []
    for event in event_details:
        if not isinstance(event,dict):
            continue
        if str(event.get("event_item") or "") in missing_items and event.get("name"):
            return str(event.get("name"))

    # YAML-derived generated goal options are only a fallback hint because goal
    # option schemas differ between APWorlds.  Match them against concrete event
    # and location names instead of assuming a particular option format.
    option_terms=[]
    for key,value in (goal.get("goal_options") or {}).items():
        option_terms.extend([str(key),str(value)])
    candidates=[]
    for event in event_details:
        if isinstance(event,dict) and event.get("name"):
            candidates.append(str(event.get("name")))
    candidates.extend(str(x.name) for x in (getattr(snapshot,"locations",None) or []) if getattr(x,"name",None))
    for term in option_terms:
        folded=term.casefold().replace("_"," ").strip()
        if not folded or folded in {"goal","0","1","true","false","none"}:
            continue
        match=next((name for name in candidates if folded in name.casefold()),"")
        if match:
            return match

    name=str(goal.get("name") or goal.get("module") or "")
    locations=getattr(snapshot,"locations",None) or []
    if name:
        match=next((x.name for x in locations if name.casefold() in str(x.name).casefold()),"")
        if match:
            return str(match)
    return ""
