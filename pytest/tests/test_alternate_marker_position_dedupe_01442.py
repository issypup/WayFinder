"""Provide test alternate marker position dedupe 01442 support."""

from pathlib import Path

from wayfinder.maps.packs import (
    MapMarker,
    _dedupe_alternate_marker_positions,
    _markers_are_mutually_exclusive_alternates,
)


def marker(x, y, kind, rule="setting_precise"):
    """Handle marker."""
    return MapMarker(
        "Example Area",
        "world",
        x,
        y,
        ("Check A", "Check B"),
        ((1001,), (1002,)),
        ((), ()),
        ("", ""),
        (),
        ({"kind": kind, "rule": rule},),
    )


def test_complementary_overview_and_precise_positions_are_alternates():
    """Handle test complementary overview and precise positions are alternates."""
    overview=marker(100,100,"force_invisibility_rules")
    precise=marker(102,101,"restrict_visibility_rules")
    assert _markers_are_mutually_exclusive_alternates(overview,precise)


def test_alternate_positions_collapse_to_overview_default():
    """Handle test alternate positions collapse to overview default."""
    precise=marker(102,101,"restrict_visibility_rules")
    overview=marker(100,100,"force_invisibility_rules")
    result=_dedupe_alternate_marker_positions([precise,overview])
    assert len(result) == 1
    assert (result[0].x,result[0].y) == (100,100)


def test_same_check_can_still_exist_twice_when_not_mutually_exclusive():
    """Handle test same check can still exist twice when not mutually exclusive."""
    first=marker(100,100,"visibility_rules","rule_a")
    second=marker(300,300,"visibility_rules","rule_b")
    assert len(_dedupe_alternate_marker_positions([first,second])) == 2


def test_dedupe_is_game_neutral():
    """Handle test dedupe is game neutral."""
    source=(Path(__file__).parents[2]/"wayfinder"/"maps"/"packs.py").read_text(encoding="utf-8")
    start=source.index("def _dedupe_alternate_marker_positions")
    end=source.index("class MapPack", start)
    block=source[start:end]
    assert "Wind Waker" not in block
    assert "Windfall" not in block
