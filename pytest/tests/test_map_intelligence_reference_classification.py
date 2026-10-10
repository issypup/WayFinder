from types import SimpleNamespace

from wayfinder.maps.intelligence import map_intelligence


def _snapshot():
    return SimpleNamespace(
        locations=[SimpleNamespace(name="Live Check", status="reachable", unknown_reason="")],
        entrance_details=[], hints=[], rule_details={}, slot_name="P1",
    )


def test_pack_location_id_absent_from_seed_is_not_unknown_reference():
    marker=SimpleNamespace(is_entrance_marker=False, location_name="Disabled Check", member_names=("Disabled Check",), section_ids=((12345,),), map_name="sea")
    pack=SimpleNamespace(markers=[marker], maps=[SimpleNamespace(name="sea", title="Sea")])
    report=map_intelligence(_snapshot(), pack, lambda marker,index: None)
    assert report["unknown_locations"] == []


def test_unmapped_pack_location_still_reports_unknown_reference():
    marker=SimpleNamespace(is_entrance_marker=False, location_name="Mystery", member_names=("Mystery",), section_ids=((),), map_name="sea")
    pack=SimpleNamespace(markers=[marker], maps=[SimpleNamespace(name="sea", title="Sea")])
    report=map_intelligence(_snapshot(), pack, lambda marker,index: None)
    assert report["unknown_locations"] == ["Mystery"]


def test_structural_entrance_marker_name_mismatch_is_not_reference_failure():
    marker=SimpleNamespace(is_entrance_marker=True, location_name="Pack Entrance Label", member_names=("Can Enter",), section_ids=((),), map_name="entrances")
    pack=SimpleNamespace(markers=[marker], maps=[SimpleNamespace(name="entrances", title="Entrances")])
    report=map_intelligence(_snapshot(), pack, lambda marker,index: None)
    assert report["unknown_entrances"] == []
