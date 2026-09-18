"""Provide test rule graph state colors 01420 support."""
from wayfinder.app.app import WayFinderApp
from wayfinder.connection.runtime_client import RuleNode


def app_stub():
    """Handle app stub."""
    return object.__new__(WayFinderApp)


def count(name, have, operator, required, satisfied=None):
    """Handle count."""
    return RuleNode(kind="item_count", label=name, satisfied=satisfied, have=have, required=required, operator=operator)


def test_count_visual_state_is_recomputed_from_visible_operator():
    """Handle test count visual state is recomputed from visible operator."""
    app=app_stub()
    assert app._rule_visual_state(count("Fire", 5, "<", 5, satisfied=True)) is False
    assert app._rule_visual_state(count("Arcane", 6, "<", 5, satisfied=True)) is False
    assert app._rule_visual_state(count("Wind", 5, ">=", 1, satisfied=False)) is True


def test_and_visual_state_is_derived_from_child_states():
    """Handle test and visual state is derived from child states."""
    app=app_stub()
    node=RuleNode(kind="and", label="Entrance requirements", satisfied=True, children=[
        count("Fire", 5, "<", 5, satisfied=True),
        count("Thunder", 5, "<", 5, satisfied=True),
    ])
    assert app._rule_visual_state(node) is False
    assert "0/2" in app._rule_node_caption(node)


def test_any_visual_state_uses_satisfied_branch():
    """Handle test any visual state uses satisfied branch."""
    app=app_stub()
    node=RuleNode(kind="or", label="Alternative routes", satisfied=False, children=[
        count("Fire", 5, "<", 5),
        count("Wind", 5, ">=", 1),
    ])
    assert app._rule_visual_state(node) is True
    assert "1/2" in app._rule_node_caption(node)
