"""Provide test comparison aware prog items support."""
from wayfinder.logic.apworld_adapter import _TracingProgItemsCounter

def test_direct_prog_items_comparison_records_threshold_and_boolean():
    """Handle test direct prog items comparison records threshold and boolean."""
    trace=[]
    items=_TracingProgItemsCounter({"Arcane":2}, trace)
    assert items["Arcane"] >= 2
    assert trace == [{
        "kind":"item_count", "name":"Arcane", "result":True,
        "have":2, "required":2, "operator":">=",
        "detail":"Arcane: have 2, need >= 2",
    }]

def test_direct_prog_items_failed_comparison_is_false():
    """Handle test direct prog items failed comparison is false."""
    trace=[]
    items=_TracingProgItemsCounter({}, trace)
    assert not (items["Soul"] >= 1)
    assert trace[-1]["result"] is False
    assert trace[-1]["have"] == 0
    assert trace[-1]["required"] == 1
