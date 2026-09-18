"""Provide test solver intelligence 01411 support."""
from types import SimpleNamespace
from wayfinder.logic.solver_intelligence import normalized_kind, rank_or_branches, path_cycles, dead_route_reasons, reconstruction_audit, searchable_entries


def n(kind,label,ok=None,children=(),have=None,required=None):
    """Handle n."""
    return SimpleNamespace(kind=kind,label=label,satisfied=ok,children=list(children),have=have,required=required,detail="")

def test_rule_normalization_and_or_ranking():
    """Handle test rule normalization and or ranking."""
    easy=n("and","easy",False,[n("item_count","Key",False,have=0,required=1)])
    hard=n("and","hard",False,[n("item_count","A",False,have=0,required=1),n("item_count","B",False,have=0,required=1)])
    root=n("or","choice",False,[hard,easy])
    assert normalized_kind("or") == "ANY"
    assert normalized_kind("item_count") == "COUNT"
    assert rank_or_branches(root)[0].label == "easy"

def test_cycle_dead_route_and_audit():
    """Handle test cycle dead route and audit."""
    steps=[
        SimpleNamespace(kind="region",title="A",source_region="A",target_region="A",reachable=True,tree=None),
        SimpleNamespace(kind="entrance",title="A-B",source_region="A",target_region="B",reachable=False,tree=n("and","r",False)),
        SimpleNamespace(kind="entrance",title="B-A",source_region="B",target_region="A",reachable=False,tree=n("and","r",False)),
        SimpleNamespace(kind="location",title="Check",source_region="A",target_region="A",reachable=False,tree=n("and","loc",False,[])),
    ]
    path=SimpleNamespace(steps=steps)
    assert path_cycles(path)
    assert dead_route_reasons(path)
    assert reconstruction_audit(path)
    assert any(label == "Check" for label,_ in searchable_entries(path))
