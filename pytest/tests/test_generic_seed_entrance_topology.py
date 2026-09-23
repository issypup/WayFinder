from types import SimpleNamespace

from wayfinder.runtime.world_builder import _apply_seed_entrance_topology, _slot_data_entrance_mappings


def _graph():
    wrong = SimpleNamespace(name="Wrong")
    right = SimpleNamespace(name="Right")
    entrance = SimpleNamespace(name="Portal A -> Wrong", connected_region=wrong)
    source = SimpleNamespace(name="Source", player=1, exits=[entrance])
    wrong.player = right.player = 1
    wrong.exits = right.exits = []
    return SimpleNamespace(regions=[source, wrong, right]), entrance


def test_generic_seed_mapping_replaces_regenerated_destination():
    multiworld, entrance = _graph()
    changed = _apply_seed_entrance_topology(multiworld, 1, {"entrances": {"Portal A": "Right"}})
    assert entrance.connected_region.name == "Right"
    assert changed and "Portal A" in changed[0]


def test_unrelated_dict_is_not_treated_as_topology():
    multiworld, entrance = _graph()
    assert _apply_seed_entrance_topology(multiworld, 1, {"hints": {"Portal A": "Right"}}) == []
    assert entrance.connected_region.name == "Wrong"


def test_mapping_requires_real_entrance_and_region_names():
    multiworld, entrance = _graph()
    assert _apply_seed_entrance_topology(multiworld, 1, {"warp_mapping": {"Unknown": "Nowhere"}}) == []
    assert entrance.connected_region.name == "Wrong"


def test_detects_common_generic_topology_container_names():
    found = _slot_data_entrance_mappings({"portal_connections": {"A": "B"}, "other": {"C": "D"}})
    assert found == [("portal_connections", {"A": "B"})]
