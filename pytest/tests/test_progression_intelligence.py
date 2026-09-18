"""Provide test progression intelligence support."""
from types import SimpleNamespace
from wayfinder.logic.progression_intelligence import detect_unlock_impact, waiting_analysis, route_score, build_progression_graph

def loc(name,status,region="R",ignored=False,unknown_reason=""):
    """Handle loc."""
    return SimpleNamespace(name=name,status=status,region=region,ignored=ignored,unknown_reason=unknown_reason)

def item(name,count,source_player=""):
    """Handle item."""
    return SimpleNamespace(name=name,count=count,progression=True,event=False,manual=False,source_player=source_player)

def snap(**kw):
    """Handle snap."""
    base=dict(inventory=[],locations=[],entrance_details=[],goal_detail={},hints=[],slot_name="P1",in_logic_regions=[],rule_details={},events=[])
    base.update(kw); return SimpleNamespace(**base)

def test_item_unlock_delta_is_observed_not_guessed():
    """Handle test item unlock delta is observed not guessed."""
    a=snap(inventory=[item("Key",0)],locations=[loc("Chest","out_of_logic")])
    b=snap(inventory=[item("Key",1)],locations=[loc("Chest","reachable")])
    impact=detect_unlock_impact(a,b)[0]
    assert impact.item=="Key" and impact.newly_reachable_locations==("Chest",)

def test_waiting_analysis_reports_local_exhaustion():
    """Handle test waiting analysis reports local exhaustion."""
    s=snap(locations=[loc("Blocked","out_of_logic",unknown_reason="Need Key")])
    w=waiting_analysis(s)
    assert w.state=="unknown" and "Need Key" in w.blockers

def test_route_scoring_is_strategy_sensitive():
    """Handle test route scoring is strategy sensitive."""
    step=SimpleNamespace(source_region="A",target_region="B",tree=None)
    path=SimpleNamespace(steps=[step,step])
    assert route_score(path,"fastest")[0] == -2
    assert route_score(path,"most checks along route")[0] > route_score(path,"fastest")[0]

def test_progression_graph_contains_regions_and_locations():
    """Handle test progression graph contains regions and locations."""
    g=build_progression_graph(snap(locations=[loc("Chest","reachable","Forest")],in_logic_regions=["Forest"]))
    keys={n.key for n in g.nodes}
    assert "region:Forest" in keys and "location:Chest" in keys
