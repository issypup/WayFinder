"""Provide test negated count normalization 01421 support."""
from wayfinder.runtime.server import _normalise_consulted_for_display


def test_successful_negated_less_than_counts_are_displayed_as_satisfied_requirements():
    """Handle test successful negated less than counts are displayed as satisfied requirements."""
    rows=[
        {"kind":"item_count","name":"Arcane","result":False,"have":6,"required":5,"operator":"<","detail":"Arcane: have 6, need < 5"},
        {"kind":"item_count","name":"Fire","result":False,"have":5,"required":5,"operator":"<","detail":"Fire: have 5, need < 5"},
        {"kind":"item_count","name":"Thunder","result":False,"have":5,"required":5,"operator":"<","detail":"Thunder: have 5, need < 5"},
        {"kind":"item_count","name":"Ice","result":False,"have":5,"required":5,"operator":"<","detail":"Ice: have 5, need < 5"},
    ]
    out=_normalise_consulted_for_display(rows, True)
    assert [row["operator"] for row in out] == [">=", ">=", ">=", ">="]
    assert all(row["result"] is True for row in out)
    assert out[0]["detail"] == "Arcane: have 6, need >= 5"
    assert out[1]["detail"] == "Fire: have 5, need >= 5"


def test_failed_rule_keeps_raw_comparison_for_diagnostics():
    """Handle test failed rule keeps raw comparison for diagnostics."""
    rows=[{"kind":"item_count","name":"Fire","result":False,"have":4,"required":5,"operator":"<"}]
    out=_normalise_consulted_for_display(rows, False)
    assert out[0]["operator"] == "<"
    assert out[0]["result"] is False


def test_mixed_trace_is_not_guessed_into_an_and_requirement():
    """Handle test mixed trace is not guessed into an and requirement."""
    rows=[
        {"kind":"item_count","name":"A","result":False,"have":0,"required":1,"operator":"<"},
        {"kind":"item_count","name":"B","result":True,"have":2,"required":1,"operator":">="},
    ]
    out=_normalise_consulted_for_display(rows, True)
    assert [row["operator"] for row in out] == ["<", ">="]
    assert [row["result"] for row in out] == [False, True]
