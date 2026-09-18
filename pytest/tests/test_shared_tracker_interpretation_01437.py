"""Provide test shared tracker interpretation 01437 support."""
from pathlib import Path

from wayfinder.maps.interpretation import (
    extract_lua_location_id_mapping,
    iter_marker_records,
    loads_compatible_json,
    normalize_location_ids,
)


def test_shared_json_accepts_comments_and_trailing_commas():
    """Handle test shared json accepts comments and trailing commas."""
    data, features = loads_compatible_json('{"x": 1, // comment\n "y": 2,}')
    assert data == {"x": 1, "y": 2}
    assert "comments" in features
    assert "trailing commas" in features


def test_shared_ids_accept_decimal_and_hex():
    """Handle test shared ids accept decimal and hex."""
    assert normalize_location_ids(["10", "0x10", 10, "bad"]) == (10, 16)


def test_shared_marker_interpretation_handles_ref_and_nested_children():
    """Handle test shared marker interpretation handles ref and nested children."""
    tree = {
        "name": "Dungeon",
        "children": [{
            "name": "Room",
            "sections": [{"ref": "Dungeon/Chest"}],
            "map_locations": [{
                "map": "dungeon",
                "x": 12,
                "y": 34,
                "restrict_visibility_rules": ["setting_show"],
            }],
        }],
    }
    records = list(iter_marker_records(tree, {"Dungeon/Chest": 0x1234}))
    assert len(records) == 1
    marker = records[0]
    assert marker["name"] == "Room"
    assert marker["section_refs"] == ("Dungeon/Chest",)
    assert marker["location_ids"] == ((0x1234,),)
    assert marker["map_visibility_rules"][0]["kind"] == "restrict_visibility_rules"


def test_shared_lua_mapping_accepts_hex(tmp_path: Path):
    """Handle test shared lua mapping accepts hex."""
    script = tmp_path / "scripts" / "autotracking"
    script.mkdir(parents=True)
    (script / "location_mapping.lua").write_text(
        '[0x238125] = "@Island/Great Fairy",\n', encoding="utf-8"
    )
    mapping = extract_lua_location_id_mapping(tmp_path)
    assert mapping["Island/Great Fairy"] == 0x238125
