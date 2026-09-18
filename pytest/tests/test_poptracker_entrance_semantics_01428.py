"""Provide test poptracker entrance semantics 01428 support."""
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from wayfinder.app.app import WayFinderApp
from wayfinder.maps.converter import convert_poptracker_pack
from wayfinder.maps.packs import MapMarker, _parse_pack


def test_poptracker_can_complete_helper_resolves_to_ap_location_id(tmp_path):
    """Handle test poptracker can complete helper resolves to ap location id."""
    source = tmp_path / "entrance-poptracker.zip"
    output = tmp_path / "converted.zip"
    with zipfile.ZipFile(source, "w") as zf:
        zf.writestr("Pack/manifest.json", json.dumps({"name": "Entrance Semantics"}))
        zf.writestr("Pack/maps/maps.json", json.dumps([
            {"name": "entrances", "img": "images/entrances.png", "title": "Entrances"}
        ]))
        zf.writestr("Pack/images/entrances.png", b"image")
        zf.writestr("Pack/locations/entrances/chapter1.json", json.dumps([
            {
                "name": "Chapter 1 Entrances",
                "children": [
                    {
                        "name": "Act 1 - Test Act",
                        "sections": [
                            {"name": "Can Enter"},
                            {"name": "Can Complete", "access_rules": ["^$canCompleteActAt|test_act"]},
                        ],
                        "map_locations": [{"map": "entrances", "x": 10, "y": 20}],
                    }
                ],
            }
        ]))
        zf.writestr("Pack/locations/logic/act_completion.json", json.dumps([
            {
                "name": "internal_can_complete_act",
                "children": [
                    {"name": "test_act", "access_rules": ["@World/Test Act/Time Piece"]}
                ],
            }
        ]))
        # Apostrophes in double-quoted Lua paths must remain valid too.
        zf.writestr(
            "Pack/scripts/autotracking/location_mapping.lua",
            'LOCATION_MAPPING = {\n  [12345] = "@World/Test Act/Time Piece",\n  [12346] = "@World/Queen Vanessa\'s Manor/Time Piece",\n}\n',
        )

    result = convert_poptracker_pack(source, output)
    assert any("Can Complete" in warning for warning in result.warnings)
    pack = _parse_pack(Path(output))
    marker = pack.markers_by_map["entrances"][0]
    assert marker.is_entrance_marker
    assert marker.section_ids == ((), (12345,))
    assert marker.section_access_rules[0] == []
    assert marker.section_access_rules[1] == ["^$canCompleteActAt|test_act"]

    with zipfile.ZipFile(output) as zf:
        mapping = json.loads(zf.read("packbash_location_ids.json"))
    assert mapping["World/Queen Vanessa's Manor/Time Piece"] == 12346


def test_entrance_sections_use_native_enter_and_completion_location_state():
    """Handle test entrance sections use native enter and completion location state."""
    app = WayFinderApp.__new__(WayFinderApp)
    app.snapshot = SimpleNamespace(
        locations=[
            SimpleNamespace(name="Completion", address=12345, status="reachable", ignored=False),
        ],
        entrance_details=[
            {"name": "Test Act", "status": "reachable", "reachable": True},
        ],
    )
    marker = MapMarker(
        "Act 1 - Test Act",
        "entrances",
        10,
        20,
        ("Can Enter", "Can Complete"),
        ((), (12345,)),
        ([], ["^$canCompleteActAt|test_act"]),
    )
    state = {x.name: x for x in app.snapshot.locations}
    assert app._map_entrance_section_status(marker, 0, state) == "reachable"
    assert app._map_entrance_section_status(marker, 1, state) == "reachable"

    app.snapshot.locations[0].status = "checked"
    assert app._map_entrance_section_status(marker, 1, state) == "checked"
    assert app._map_entrance_section_status_label("checked") == "Completed"


def test_ruleless_can_complete_follows_entrance_state():
    """Handle test ruleless can complete follows entrance state."""
    app = WayFinderApp.__new__(WayFinderApp)
    app.snapshot = SimpleNamespace(locations=[], entrance_details=[
        {"name": "Yellow Overpass Manhole", "status": "reachable", "reachable": True},
    ])
    marker = MapMarker(
        "Yellow Overpass Manhole",
        "entrances",
        1,
        2,
        ("Can Enter", "Can Complete"),
        ((), ()),
        ([], []),
    )
    assert app._map_entrance_section_status(marker, 0, {}) == "reachable"
    assert app._map_entrance_section_status(marker, 1, {}) == "reachable"


def test_entrance_semantics_are_detected_on_nonstandard_map_names_and_audited(tmp_path):
    """Handle test entrance semantics are detected on nonstandard map names and audited."""
    source = tmp_path / "generic-portals.zip"
    output = tmp_path / "converted.zip"
    with zipfile.ZipFile(source, "w") as zf:
        zf.writestr("Pack/manifest.json", json.dumps({"name": "Generic Portals"}))
        zf.writestr("Pack/maps/maps.json", json.dumps([
            {"name": "portals", "img": "images/portals.png", "title": "Portals"}
        ]))
        zf.writestr("Pack/images/portals.png", b"image")
        zf.writestr("Pack/locations/portals.json", json.dumps([
            {
                "name": "Free Portal",
                "sections": [{"name": "Can Enter"}, {"name": "Can Complete"}],
                "map_locations": [{"map": "portals", "x": 1, "y": 2}],
            },
            {
                "name": "Rule Portal",
                "sections": [
                    {"name": "Can Enter"},
                    {"name": "Can Complete", "access_rules": ["$somePackLuaHelper|rule_portal"]},
                ],
                "map_locations": [{"map": "portals", "x": 3, "y": 4}],
            },
        ]))

    result = convert_poptracker_pack(source, output)
    pack = _parse_pack(Path(output))
    markers = pack.markers_by_map["portals"]
    assert len(markers) == 2
    assert all(marker.is_entrance_marker for marker in markers)

    with zipfile.ZipFile(output) as zf:
        audit = json.loads(zf.read("wayfinder_entrance_semantics.json"))
        metadata = json.loads(zf.read("wayfinder_pack.json"))

    assert audit["counts"]["entrance_like_nodes"] == 2
    assert audit["counts"]["inherits_entrance"] == 1
    assert audit["counts"]["unresolved_rule"] == 1
    assert metadata["entrance_semantics"]["unresolved_rule"] == 1
    assert any("entrance semantic audit" in warning.casefold() for warning in result.warnings)
