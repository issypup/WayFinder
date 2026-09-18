"""Provide test rift rule reconstruction 01432 support."""
from collections import Counter
from types import SimpleNamespace

from wayfinder.logic.apworld_adapter import trace_access_rule, _route_rule_rows_for_region


def test_can_reach_location_predicate_is_traced_instead_of_opaque():
    """Handle test can reach location predicate is traced instead of opaque."""
    target = SimpleNamespace(name="Act Completion (Rift)", parent_region=SimpleNamespace(name="Rift Region"))
    target.access_rule = lambda state: True

    class Multiworld:
        """Provide multiworld behavior."""
        def get_location(self, name, player):
            """Return get location."""
            assert name == "Act Completion (Rift)"
            return target

    obj = SimpleNamespace(access_rule=lambda state: state.can_reach("Act Completion (Rift)", "Location", 1))
    detail = trace_access_rule(
        obj,
        player=1,
        inventory=Counter(),
        reachable_regions={"Rift Region"},
        events=set(),
        groups={},
        multiworld=Multiworld(),
    )
    assert detail["satisfied"] is True
    assert any(row["kind"] == "region" and row["name"] == "Act Completion (Rift)" for row in detail["consulted"])
    assert not any(row["kind"] == "opaque" for row in detail["consulted"])


def test_route_walkback_prefers_reachable_parent_branch_over_unrelated_branch():
    """Handle test route walkback prefers reachable parent branch over unrelated branch."""
    entrance_details = [
        {
            "name": "Alpine -> Rift",
            "source_region": "Alpine",
            "target_region": "Rift",
            "source_reachable": False,
            "satisfied": False,
            "consulted": [{"kind": "item", "name": "Birdhouse Cleared", "result": False, "detail": "need 1"}],
        },
        {
            "name": "Mafia Act -> Rift",
            "source_region": "Mafia Act",
            "target_region": "Rift",
            "source_reachable": True,
            "satisfied": False,
            "consulted": [{"kind": "region", "name": "Heating Up Mafia Town", "result": False, "detail": "rift unlock"}],
        },
        {
            "name": "Start -> Alpine",
            "source_region": "Start",
            "target_region": "Alpine",
            "source_reachable": True,
            "satisfied": False,
            "consulted": [{"kind": "item", "name": "Time Piece", "result": False, "detail": "need 5"}],
        },
        {
            "name": "Start -> Mafia Act",
            "source_region": "Start",
            "target_region": "Mafia Act",
            "source_reachable": True,
            "satisfied": True,
            "consulted": [],
        },
    ]
    rows, chain = _route_rule_rows_for_region("Rift", {"Start"}, entrance_details)
    assert [step["name"] for step in chain] == ["Start -> Mafia Act", "Mafia Act -> Rift"]
    names = {row.get("name") for row in rows}
    assert "Heating Up Mafia Town" in names
    assert "Birdhouse Cleared" not in names
    assert "Time Piece" not in names
