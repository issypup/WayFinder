"""Provide test logic explanations support."""
# /**
#  * Module: tests/test_logic_explanations.py
#  * Purpose: Regression tests for test logic explanations; documents expected behavior so future refactors remain compatible.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from collections import Counter
from types import SimpleNamespace
from wayfinder.logic.apworld_adapter import trace_access_rule


# /**
#  * Function: test_trace_records_missing_item_and_module
#  * Purpose: Perform the test trace records missing item and module operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_trace_records_missing_item_and_module():
    # Variable(s): `obj` (object); named state retained for the surrounding calculation or subsequent calls.
    """Handle test trace records missing item and module."""
    obj=SimpleNamespace(access_rule=lambda state: state.has("Fire",1) or state.has("Wind",1))
    # Variable(s): `d` (d); named state retained for the surrounding calculation or subsequent calls.
    d=trace_access_rule(obj,player=1,inventory=Counter(),reachable_regions={"Start"},events=set(),groups={},multiworld=None)
    assert d["satisfied"] is False
    assert {x["name"] for x in d["missing"]} == {"Fire","Wind"}
    assert d["module"]


# /**
#  * Function: test_trace_records_satisfied_item
#  * Purpose: Perform the test trace records satisfied item operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_trace_records_satisfied_item():
    # Variable(s): `obj` (object); named state retained for the surrounding calculation or subsequent calls.
    """Handle test trace records satisfied item."""
    obj=SimpleNamespace(access_rule=lambda state: state.has("Fire",1))
    # Variable(s): `d` (d); named state retained for the surrounding calculation or subsequent calls.
    d=trace_access_rule(obj,player=1,inventory=Counter({"Fire":1}),reachable_regions={"Start"},events=set(),groups={},multiworld=None)
    assert d["satisfied"] is True
    assert d["consulted"][0]["name"] == "Fire"


def _direct_prog_items_helper(state):
    """Handle direct prog items helper."""
    return state.prog_items[1]["Fire"] >= 2


def test_trace_direct_prog_items_helper_is_not_opaque():
    """Handle test trace direct prog items helper is not opaque."""
    obj = SimpleNamespace(access_rule=_direct_prog_items_helper)
    d = trace_access_rule(obj, player=1, inventory=Counter({"Fire": 1}), reachable_regions={"Start"}, events=set(), groups={}, multiworld=None)
    assert d["satisfied"] is False
    assert any(x["kind"] == "item_count" and x["name"] == "Fire" for x in d["consulted"])
    assert any(x["kind"] == "helper" and x["name"] == "_direct_prog_items_helper" for x in d["consulted"])
    assert not any(x["kind"] == "opaque" for x in d["consulted"])


def test_framework_default_rule_is_unconditional_not_opaque():
    """Handle test framework default rule is unconditional not opaque."""
    def fake_default(state):
        """Handle fake default."""
        return True
    # Make the callable look like Archipelago's generic BaseClasses default rule.
    fake_default.__code__ = fake_default.__code__.replace(co_filename=r"C:\\Archipelago\\BaseClasses.py")
    obj = SimpleNamespace(access_rule=fake_default)
    d = trace_access_rule(obj, player=1, inventory=Counter(), reachable_regions={"Start"}, events=set(), groups={}, multiworld=None)
    assert any(x["kind"] == "unconditional" for x in d["consulted"])
    assert not any(x["kind"] == "opaque" for x in d["consulted"])


def test_rule_path_walkback_inherits_entrance_predicates():
    """Handle test rule path walkback inherits entrance predicates."""
    from wayfinder.logic.apworld_adapter import _route_rule_rows_for_region
    entrance_details = [
        {
            "name": "Start -> Cave",
            "source_region": "Start",
            "target_region": "Cave",
            "satisfied": False,
            "consulted": [{"kind": "item", "name": "Key", "result": False, "detail": "need 1"}],
        },
        {
            "name": "Cave -> Shrine",
            "source_region": "Cave",
            "target_region": "Shrine",
            "satisfied": True,
            "consulted": [],
        },
    ]
    rows, chain = _route_rule_rows_for_region("Shrine", {"Start"}, entrance_details)
    assert [step["name"] for step in chain] == ["Start -> Cave", "Cave -> Shrine"]
    assert any(row["kind"] == "item" and row["name"] == "Key" for row in rows)
