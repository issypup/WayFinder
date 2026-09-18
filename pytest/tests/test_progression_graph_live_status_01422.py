"""Provide test progression graph live status 01422 support."""

from types import SimpleNamespace

from wayfinder.logic.progression_intelligence import build_progression_graph


def _snapshot(**overrides):
    """Handle snapshot."""
    base = dict(
        locations=[],
        in_logic_regions=[],
        current_reachable_regions=[],
        rule_details={},
        entrance_details=[],
        events=[],
        event_details=[],
        goal_detail={},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _nodes(model, kind):
    """Handle nodes."""
    return {n.label: n.status for n in model.nodes if n.kind == kind}


def test_entrance_status_uses_live_reachable_boolean():
    """Handle test entrance status uses live reachable boolean."""
    snap = _snapshot(entrance_details=[
        {"name": "A -> B", "source_region": "A", "target_region": "B", "reachable": True},
        {"name": "B -> C", "source_region": "B", "target_region": "C", "reachable": False},
    ])
    statuses = _nodes(build_progression_graph(snap), "entrance")
    assert statuses["A -> B"] == "reachable"
    assert statuses["B -> C"] == "blocked"


def test_explicit_non_unknown_entrance_status_wins():
    """Handle test explicit non unknown entrance status wins."""
    snap = _snapshot(entrance_details=[
        {"name": "A -> B", "status": "glitch", "reachable": False},
    ])
    statuses = _nodes(build_progression_graph(snap), "entrance")
    assert statuses["A -> B"] == "glitch"


def test_event_details_mirror_swept_pending_state():
    """Handle test event details mirror swept pending state."""
    snap = _snapshot(event_details=[
        {"name": "Boss Defeated", "swept": True},
        {"name": "Door Open", "swept": False},
    ])
    statuses = _nodes(build_progression_graph(snap), "event")
    assert statuses["Boss Defeated"] == "satisfied"
    assert statuses["Door Open"] == "pending"
