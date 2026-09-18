"""Provide test complex poptracker maps 01434 support."""
from pathlib import Path

from wayfinder.maps.converter import _extract_poptracker_location_id_mapping
from wayfinder.maps.packs import MapMarker, _flatten_locations


def test_hexadecimal_poptracker_location_ids_are_imported(tmp_path):
    """Handle test hexadecimal poptracker location ids are imported."""
    mapping = tmp_path / "scripts" / "autotracking" / "location_mapping.lua"
    mapping.parent.mkdir(parents=True)
    mapping.write_text('[0x238125] = "@Triforce Salvaging/Greatfish Isle - Sunken Triforce 1/Salvage"\n', encoding="utf-8")

    result = _extract_poptracker_location_id_mapping(tmp_path)
    assert result["Triforce Salvaging/Greatfish Isle - Sunken Triforce 1/Salvage"] == 0x238125


def test_ref_only_sections_create_dungeon_map_markers_with_ids():
    """Handle test ref only sections create dungeon map markers with ids."""
    raw = [{
        "name": "Dragon Roost Cavern Dungeon",
        "children": [{
            "name": "First Room",
            "children": [{
                "sections": [{"ref": "Dragon Roost Cavern/First Room"}],
                "map_locations": [{"map": "drc", "x": 238, "y": 480}],
            }],
        }],
    }]
    markers = []
    _flatten_locations(raw, markers, {"Dragon Roost Cavern/First Room": 0x238038})

    assert len(markers) == 1
    marker = markers[0]
    assert marker.map_name == "drc"
    assert marker.location_name == "First Room"
    assert marker.section_names == ("First Room",)
    assert marker.section_refs == ("Dragon Roost Cavern/First Room",)
    assert marker.section_ids == ((0x238038,),)


def test_auxiliary_exit_marker_is_preserved_as_synthetic():
    """Handle test auxiliary exit marker is preserved as synthetic."""
    markers = []
    _flatten_locations([{
        "name": "Dragon Roost Cavern",
        "sections": [{"name": "Entered", "hosted_item": "Dragon Roost Cavern"}],
        "map_locations": [{"map": "exits", "x": 605, "y": 70}],
    }], markers, {})

    assert len(markers) == 1
    assert markers[0].location_name == "Dragon Roost Cavern"
    assert markers[0].is_exit_marker
    assert markers[0].is_synthetic_marker


def test_map_visibility_rules_are_preserved():
    """Handle test map visibility rules are preserved."""
    markers = []
    _flatten_locations([{
        "name": "Star Island - Cave",
        "sections": [{}],
        "map_locations": [{
            "map": "seachart",
            "x": 139,
            "y": 38,
            "restrict_visibility_rules": ["setting_show_precise_sea_locations"],
        }],
    }], markers, {"Star Island - Cave": 123})

    assert len(markers) == 1
    assert markers[0].map_visibility_rules == ({
        "kind": "restrict_visibility_rules",
        "rule": "setting_show_precise_sea_locations",
    },)


def test_salvage_marker_keeps_useful_owner_label_and_section_id():
    """Handle test salvage marker keeps useful owner label and section id."""
    markers = []
    _flatten_locations([{
        "name": "Greatfish Isle - Sunken Triforce 1",
        "sections": [{"name": "Salvage"}],
        "map_locations": [{"map": "salvage", "x": 171, "y": 392}],
    }], markers, {"Greatfish Isle - Sunken Triforce 1/Salvage": 0x238125})

    assert len(markers) == 1
    assert markers[0].location_name == "Greatfish Isle - Sunken Triforce 1"
    assert markers[0].section_names == ("Salvage",)
    assert markers[0].section_ids == ((0x238125,),)
