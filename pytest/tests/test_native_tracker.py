"""Provide test native tracker support."""
# /**
#  * Module: tests/test_native_tracker.py
#  * Purpose: Regression tests for test native tracker; documents expected behavior so future refactors remain compatible.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from wayfinder.logic import (
    EntranceDefinition, EventDefinition, LocationDefinition, LogicEngine,
    RegionDefinition, TrackerDefinition, TrackerInput, all_of, event, item, option,
)
from wayfinder.logic.native_pack import load_definition


# /**
#  * Class: NativeTrackerTests
#  * Purpose: Encapsulate the NativeTrackerTests responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
class NativeTrackerTests(unittest.TestCase):
    # /**
    #  * Function: make_world
    #  * Purpose: Perform the make world operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    """Provide native tracker tests behavior."""
    def make_world(self):
        # Variable(s): `d` (d); named state retained for the surrounding calculation or subsequent calls.
        """Return make world."""
        d = TrackerDefinition("Example")
        d.regions = {
            "Menu": RegionDefinition("Menu", starting=True),
            "Shrine": RegionDefinition("Shrine"),
            "Upper Shrine": RegionDefinition("Upper Shrine"),
        }
        d.entrances = [
            EntranceDefinition("Begin", "Menu", "Shrine"),
            EntranceDefinition("Climb", "Shrine", "Upper Shrine", item("Double Jump")),
        ]
        d.events["Switch"] = EventDefinition("Switch", "Shrine", item("Key"), grants="Switch On")
        d.locations["Chest"] = LocationDefinition("Chest", "Shrine")
        d.locations["High Chest"] = LocationDefinition("High Chest", "Upper Shrine", all_of(event("Switch On"), option("hard_logic", False)))
        return d

    # /**
    #  * Function: test_reachability_and_event_sweep
    #  * Purpose: Perform the test reachability and event sweep operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def test_reachability_and_event_sweep(self):
        # Variable(s): `engine` (engine); named state retained for the surrounding calculation or subsequent calls.
        """Handle test reachability and event sweep."""
        engine = LogicEngine(self.make_world())
        # Variable(s): `snap` (snap); named state retained for the surrounding calculation or subsequent calls.
        snap = engine.evaluate(TrackerInput(inventory=Counter({"Key": 1, "Double Jump": 1}), options={"hard_logic": False}))
        self.assertEqual({"Menu", "Shrine", "Upper Shrine"}, snap.reachable_regions)
        self.assertIn("Switch On", snap.events)
        self.assertEqual("reachable", snap.locations["High Chest"].status)

    # /**
    #  * Function: test_explanation_missing_item
    #  * Purpose: Perform the test explanation missing item operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def test_explanation_missing_item(self):
        # Variable(s): `snap` (snap); named state retained for the surrounding calculation or subsequent calls.
        """Handle test explanation missing item."""
        snap = LogicEngine(self.make_world()).evaluate(TrackerInput(options={"hard_logic": False}))
        self.assertEqual("out_of_logic", snap.locations["High Chest"].status)
        self.assertNotIn("Upper Shrine", snap.reachable_regions)

    # /**
    #  * Function: test_unknown_option_is_not_false
    #  * Purpose: Perform the test unknown option is not false operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def test_unknown_option_is_not_false(self):
        # Variable(s): `d` (d); named state retained for the surrounding calculation or subsequent calls.
        """Handle test unknown option is not false."""
        d = self.make_world()
        d.locations["Option Chest"] = LocationDefinition("Option Chest", "Shrine", option("mode", "open"))
        # Variable(s): `snap` (snap); named state retained for the surrounding calculation or subsequent calls.
        snap = LogicEngine(d).evaluate()
        # Variable(s): `result` (result); named state retained for the surrounding calculation or subsequent calls.
        result = snap.locations["Option Chest"]
        self.assertEqual("unknown", result.status)
        self.assertIn("unavailable", result.unknown_reason)

    # /**
    #  * Function: test_deferred_entrance
    #  * Purpose: Perform the test deferred entrance operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def test_deferred_entrance(self):
        # Variable(s): `d` (d); named state retained for the surrounding calculation or subsequent calls.
        """Handle test deferred entrance."""
        d = TrackerDefinition("Deferred")
        d.regions = {"Start": RegionDefinition("Start", True), "A": RegionDefinition("A")}
        d.entrances = [EntranceDefinition("Portal", "Start", None)]
        # Variable(s): `engine` (engine); named state retained for the surrounding calculation or subsequent calls.
        engine = LogicEngine(d)
        # Variable(s): `unresolved` (unresolved); named state retained for the surrounding calculation or subsequent calls.
        unresolved = engine.evaluate()
        self.assertIn("Portal", unresolved.unresolved_entrances)
        # Variable(s): `resolved` (resolved); named state retained for the surrounding calculation or subsequent calls.
        resolved = engine.evaluate(TrackerInput(entrance_connections={"Portal": "A"}))
        self.assertIn("A", resolved.reachable_regions)

    # /**
    #  * Function: test_native_json_loader
    #  * Purpose: Perform the test native json loader operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def test_native_json_loader(self):
        # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
        """Handle test native json loader."""
        data = {
            "game": "Pack", "schema_version": 1,
            "regions": [{"name": "Start", "starting": True}],
            "locations": [{"name": "Check", "region": "Start", "rule": {"item": "Key"}}]
        }
        # Variable(s): `td` (td); named state retained for the surrounding calculation or subsequent calls.
        with tempfile.TemporaryDirectory() as td:
            # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
            p = Path(td) / "tracker.json"
            p.write_text(json.dumps(data), encoding="utf-8")
            # Variable(s): `definition` (definition); named state retained for the surrounding calculation or subsequent calls.
            definition = load_definition(p)
            # Variable(s): `snap` (snap); named state retained for the surrounding calculation or subsequent calls.
            snap = LogicEngine(definition).evaluate(TrackerInput(inventory=Counter({"Key": 1})))
            self.assertEqual("reachable", snap.locations["Check"].status)


if __name__ == "__main__":
    unittest.main()


# /**
#  * Function: test_apworld_adapter_basic_graph_and_event_sweep
#  * Purpose: Perform the test apworld adapter basic graph and event sweep operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_apworld_adapter_basic_graph_and_event_sweep():
    """Handle test apworld adapter basic graph and event sweep."""
    from types import SimpleNamespace
    from collections import Counter
    from wayfinder.logic.apworld_adapter import evaluate_generated_world

    # /**
    #  * Function: reg
    #  * Purpose: Perform the reg operation while keeping the surrounding subsystem state consistent.
    #  * @param name: Name supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def reg(name):
        """Handle reg."""
        return SimpleNamespace(name=name, player=1, exits=[], locations=[])
    # Variable(s): `menu` (menu), `field` (field), `cave` (cave); named state retained for the surrounding calculation or subsequent calls.
    menu, field, cave = reg('Menu'), reg('Field'), reg('Cave')
    # Variable(s): `e1` (e1); named state retained for the surrounding calculation or subsequent calls.
    e1 = SimpleNamespace(name='Menu -> Field', connected_region=field, access_rule=lambda s: True)
    # Variable(s): `e2` (e2); named state retained for the surrounding calculation or subsequent calls.
    e2 = SimpleNamespace(name='Field -> Cave', connected_region=cave, access_rule=lambda s: s.has('Key', 1))
    menu.exits=[e1]; field.exits=[e2]
    # Variable(s): `event_item` (event item); named state retained for the surrounding calculation or subsequent calls.
    event_item=SimpleNamespace(name='Key')
    # Variable(s): `event_loc` (event loc); named state retained for the surrounding calculation or subsequent calls.
    event_loc=SimpleNamespace(name='Find Key', address=None, item=event_item, access_rule=lambda s: True)
    # Variable(s): `chest` (chest); named state retained for the surrounding calculation or subsequent calls.
    chest=SimpleNamespace(name='Cave Chest', address=1001, item=None, access_rule=lambda s: s.has('Key',1))
    field.locations=[event_loc]; cave.locations=[chest]
    # Variable(s): `mw` (mw); named state retained for the surrounding calculation or subsequent calls.
    mw=SimpleNamespace(regions=[menu,field,cave])
    # Variable(s): `world` (world); named state retained for the surrounding calculation or subsequent calls.
    world=SimpleNamespace(game='Example', item_name_groups={})
    # Variable(s): `snap` (snap); named state retained for the surrounding calculation or subsequent calls.
    snap=evaluate_generated_world(multiworld=mw, world=world, player=1, inventory=Counter())
    assert snap.reachable_regions == {'Menu','Field','Cave'}
    assert 'Key' in snap.events
    assert 'Cave Chest' in snap.reachable_locations
    assert not snap.errors


# /**
#  * Function: test_apworld_adapter_reports_unsupported_state_api
#  * Purpose: Perform the test apworld adapter reports unsupported state api operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_apworld_adapter_reports_unsupported_state_api():
    """Handle test apworld adapter reports unsupported state api."""
    from types import SimpleNamespace
    from collections import Counter
    from wayfinder.logic.apworld_adapter import evaluate_generated_world
    # Variable(s): `menu` (menu); named state retained for the surrounding calculation or subsequent calls.
    menu=SimpleNamespace(name='Menu', player=1, exits=[], locations=[])
    # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
    loc=SimpleNamespace(name='Odd Check', address=7, item=None, access_rule=lambda s: s.some_world_specific_method())
    menu.locations=[loc]
    # Variable(s): `mw` (mw); named state retained for the surrounding calculation or subsequent calls.
    mw=SimpleNamespace(regions=[menu])
    # Variable(s): `world` (world); named state retained for the surrounding calculation or subsequent calls.
    world=SimpleNamespace(game='Example', item_name_groups={})
    # Variable(s): `snap` (snap); named state retained for the surrounding calculation or subsequent calls.
    snap=evaluate_generated_world(multiworld=mw, world=world, player=1, inventory=Counter())
    assert 'Odd Check' not in snap.reachable_locations
    assert any('some_world_specific_method' in e for e in snap.errors)


# /**
#  * Function: test_dependency_scanner_covers_builtin_and_custom_worlds
#  * Purpose: Perform the test dependency scanner covers builtin and custom worlds operation while keeping the surrounding subsystem state consistent.
#  * @param tmp_path: Tmp path supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_dependency_scanner_covers_builtin_and_custom_worlds(tmp_path):
    """Handle test dependency scanner covers builtin and custom worlds."""
    import zipfile
    from wayfinder.runtime.dependency_manager import scan_dependencies

    # Variable(s): `ap` (ap); named state retained for the surrounding calculation or subsequent calls.
    ap = tmp_path / "ap"
    (ap / "worlds" / "zillion").mkdir(parents=True)
    (ap / "custom_worlds").mkdir(parents=True)
    (ap / "requirements.txt").write_text("schema==0.7.8\n", encoding="utf-8")
    (ap / "worlds" / "zillion" / "__init__.py").write_text("", encoding="utf-8")
    (ap / "worlds" / "zillion" / "requirements.txt").write_text("zilliandomizer>=0.9\n", encoding="utf-8")
    # Variable(s): `custom` (custom); named state retained for the surrounding calculation or subsequent calls.
    custom = ap / "custom_worlds" / "example.apworld"
    # Variable(s): `zf` (ZIP archive handle); named state retained for the surrounding calculation or subsequent calls.
    with zipfile.ZipFile(custom, "w") as zf:
        zf.writestr("example/__init__.py", "import attr\n")
        zf.writestr("example/requirements.txt", "requests>=2\n")

    # Variable(s): `scan` (scan), `work` (work); named state retained for the surrounding calculation or subsequent calls.
    scan, work = scan_dependencies(ap)
    try:
        assert scan.core_requirements
        assert any("zillion" in path for path in scan.builtin_requirement_files)
        assert scan.custom_requirement_files
        assert "attrs" in scan.custom_inferred_packages
        assert scan.custom_worlds == 1
        assert scan.builtin_worlds == 1
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)


# /**
#  * Function: test_ap_adapter_uses_world_origin_region_for_non_menu_cycle
#  * Purpose: Perform the test ap adapter uses world origin region for non menu cycle operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_ap_adapter_uses_world_origin_region_for_non_menu_cycle():
    """Handle test ap adapter uses world origin region for non menu cycle."""
    from collections import Counter
    from types import SimpleNamespace
    from wayfinder.logic.apworld_adapter import evaluate_generated_world

    # /**
    #  * Class: Entrance
    #  * Purpose: Encapsulate the Entrance responsibilities and state used by this module.
    #  * @state: Instance attributes hold the durable state needed by this responsibility.
    #  */
    class Entrance:
        # /**
        #  * Function: __init__
        #  * Purpose: Initialize this object and establish its required runtime state.
        #  * @param name: Name supplied by the caller; see type hints and call sites for domain constraints.
        #  * @param parent: Parent supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        """Provide entrance behavior."""
        def __init__(self, name, parent):
            """Handle init."""
            self.name = name
            self.parent_region = parent
            self.connected_region = None
            self.access_rule = lambda state: True

    # /**
    #  * Class: Region
    #  * Purpose: Encapsulate the Region responsibilities and state used by this module.
    #  * @state: Instance attributes hold the durable state needed by this responsibility.
    #  */
    class Region:
        # /**
        #  * Function: __init__
        #  * Purpose: Initialize this object and establish its required runtime state.
        #  * @param name: Name supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        """Provide region behavior."""
        def __init__(self, name):
            """Handle init."""
            self.name = name
            self.player = 1
            self.exits = []
            self.locations = []

    # Variable(s): `shrine` (shrine); named state retained for the surrounding calculation or subsequent calls.
    shrine = Region("Shrine - Start")
    # Variable(s): `underground` (underground); named state retained for the surrounding calculation or subsequent calls.
    underground = Region("Underground")
    # Variable(s): `a` (a); named state retained for the surrounding calculation or subsequent calls.
    a = Entrance("Shrine -> Underground", shrine)
    # Variable(s): `b` (b); named state retained for the surrounding calculation or subsequent calls.
    b = Entrance("Underground -> Shrine", underground)
    a.connected_region = underground
    b.connected_region = shrine
    shrine.exits.append(a)
    underground.exits.append(b)

    # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
    loc = SimpleNamespace(
        name="Shrine Check", address=123, parent_region=shrine,
        access_rule=lambda state: True,
    )
    shrine.locations.append(loc)
    # Variable(s): `multiworld` (multiworld); named state retained for the surrounding calculation or subsequent calls.
    multiworld = SimpleNamespace(regions=[shrine, underground])
    # Variable(s): `world` (world); named state retained for the surrounding calculation or subsequent calls.
    world = SimpleNamespace(game="Origin Test", origin_region_name="Shrine - Start", item_name_groups={})

    # Variable(s): `snap` (snap); named state retained for the surrounding calculation or subsequent calls.
    snap = evaluate_generated_world(
        multiworld=multiworld, world=world, player=1, inventory=Counter()
    )
    assert "Shrine - Start" in snap.reachable_regions
    assert "Underground" in snap.reachable_regions
    assert "Shrine Check" in snap.reachable_locations


# /**
#  * Function: test_snapshot_logic_sets_support_apworld_glitch_capability_item
#  * Purpose: Perform the test snapshot logic sets support apworld glitch capability item operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_snapshot_logic_sets_support_apworld_glitch_capability_item():
    """Handle test snapshot logic sets support apworld glitch capability item."""
    from collections import Counter
    from types import SimpleNamespace
    from wayfinder.runtime.snapshot import _evaluate_logic_sets

    # Variable(s): `region` (region); named state retained for the surrounding calculation or subsequent calls.
    region = SimpleNamespace(name="Start", player=1, exits=[], locations=[])
    # Variable(s): `normal` (normal); named state retained for the surrounding calculation or subsequent calls.
    normal = SimpleNamespace(name="Normal Check", address=1, parent_region=region, access_rule=lambda s: True)
    # Variable(s): `glitch` (glitch); named state retained for the surrounding calculation or subsequent calls.
    glitch = SimpleNamespace(name="Glitch Check", address=2, parent_region=region, access_rule=lambda s: s.has("__WF_GLITCHES__", 1))
    region.locations = [normal, glitch]
    # Variable(s): `multiworld` (multiworld); named state retained for the surrounding calculation or subsequent calls.
    multiworld = SimpleNamespace(regions=[region])
    # Variable(s): `world` (world); named state retained for the surrounding calculation or subsequent calls.
    world = SimpleNamespace(game="Glitch Test", origin_region_name="Start", item_name_groups={}, glitches_item_name="__WF_GLITCHES__")

    # Variable(s): `normal_result` (normal result), `glitch_result` (glitch result), `capability` (capability); named state retained for the surrounding calculation or subsequent calls.
    normal_result, glitch_result, capability = _evaluate_logic_sets(
        multiworld=multiworld, world=world, player=1, inventory=Counter(), checked_names=set()
    )
    assert capability == "__WF_GLITCHES__"
    assert normal_result.reachable_locations == {"Normal Check"}
    assert glitch_result is not None
    assert glitch_result.reachable_locations == {"Normal Check", "Glitch Check"}


# /**
#  * Function: test_snapshot_logic_sets_do_not_invent_glitch_logic_without_apworld_capability
#  * Purpose: Perform the test snapshot logic sets do not invent glitch logic without apworld capability operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_snapshot_logic_sets_do_not_invent_glitch_logic_without_apworld_capability():
    """Handle test snapshot logic sets do not invent glitch logic without apworld capability."""
    from collections import Counter
    from types import SimpleNamespace
    from wayfinder.runtime.snapshot import _evaluate_logic_sets

    # Variable(s): `region` (region); named state retained for the surrounding calculation or subsequent calls.
    region = SimpleNamespace(name="Start", player=1, exits=[], locations=[])
    region.locations = [SimpleNamespace(name="Check", address=1, parent_region=region, access_rule=lambda s: False)]
    # Variable(s): `multiworld` (multiworld); named state retained for the surrounding calculation or subsequent calls.
    multiworld = SimpleNamespace(regions=[region])
    # Variable(s): `world` (world); named state retained for the surrounding calculation or subsequent calls.
    world = SimpleNamespace(game="No Glitch API", origin_region_name="Start", item_name_groups={})
    # Variable(s): `normal_result` (normal result), `glitch_result` (glitch result), `capability` (capability); named state retained for the surrounding calculation or subsequent calls.
    normal_result, glitch_result, capability = _evaluate_logic_sets(
        multiworld=multiworld, world=world, player=1, inventory=Counter(), checked_names=set()
    )
    assert normal_result.reachable_locations == set()
    assert glitch_result is None
    assert capability == ""


# /**
#  * Function: test_slot_data_overrides_rerolled_yaml_option
#  * Purpose: Perform the test slot data overrides rerolled yaml option operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_slot_data_overrides_rerolled_yaml_option():
    """Handle test slot data overrides rerolled yaml option."""
    from wayfinder.runtime.world_builder import _apply_slot_data_option_overrides

    # /**
    #  * Class: FakeChoice
    #  * Purpose: Encapsulate the FakeChoice responsibilities and state used by this module.
    #  * @state: Instance attributes hold the durable state needed by this responsibility.
    #  */
    class FakeChoice:
        # /**
        #  * Function: __init__
        #  * Purpose: Initialize this object and establish its required runtime state.
        #  * @param value: Value supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        """Provide fake choice behavior."""
        def __init__(self, value):
            """Handle init."""
            self.value = value

        # /**
        #  * Function: from_any
        #  * Purpose: Perform the from any operation while keeping the surrounding subsystem state consistent.
        #  * @param value: Value supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        @classmethod
        def from_any(cls, value):
            """Handle from any."""
            return cls(int(value))

    # /**
    #  * Class: FakeOptions
    #  * Purpose: Encapsulate the FakeOptions responsibilities and state used by this module.
    #  * @state: Instance attributes hold the durable state needed by this responsibility.
    #  */
    class FakeOptions:
        # Variable(s): `starting_area` (starting area); named state retained for the surrounding calculation or subsequent calls.
        """Provide fake options behavior."""
        starting_area = FakeChoice(2)  # locally re-rolled to Lava Ruins

    # /**
    #  * Class: FakeWorld
    #  * Purpose: Encapsulate the FakeWorld responsibilities and state used by this module.
    #  * @state: Instance attributes hold the durable state needed by this responsibility.
    #  */
    class FakeWorld:
        # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
        """Provide fake world behavior."""
        game = "Little Witch Nobeta"
        # Variable(s): `options` (options); named state retained for the surrounding calculation or subsequent calls.
        options = FakeOptions()

    # Variable(s): `changed` (changed); named state retained for the surrounding calculation or subsequent calls.
    changed = _apply_slot_data_option_overrides(FakeWorld(), {"starting_area": 0, "world_version": "x"})
    assert FakeWorld.options.starting_area.value == 0
    assert changed == {"starting_area": (2, 0)}


# /**
#  * Function: test_poptracker_conversion_to_wayfinder
#  * Purpose: Perform the test poptracker conversion to wayfinder operation while keeping the surrounding subsystem state consistent.
#  * @param tmp_path: Tmp path supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_poptracker_conversion_to_wayfinder(tmp_path):
    """Handle test poptracker conversion to wayfinder."""
    import json, zipfile
    from wayfinder.maps.converter import convert_poptracker_pack

    # Variable(s): `source` (source); named state retained for the surrounding calculation or subsequent calls.
    source=tmp_path/'pop.zip'
    # Variable(s): `zf` (ZIP archive handle); named state retained for the surrounding calculation or subsequent calls.
    with zipfile.ZipFile(source,'w') as zf:
        zf.writestr('Pack/manifest.json', json.dumps({'name':'Test Pop Pack'}))
        zf.writestr('Pack/maps/maps.json', json.dumps([{'name':'start','img':'maps/start.png','title':'Start'}]))
        zf.writestr('Pack/maps/start.png', b'not-a-real-image-but-copied')
        zf.writestr('Pack/locations/main.json', json.dumps([{'name':'Chest','map_locations':[{'map':'start','x':10,'y':20}]}]))
    # Variable(s): `output` (output); named state retained for the surrounding calculation or subsequent calls.
    output=tmp_path/'converted.zip'
    # Variable(s): `result` (result); named state retained for the surrounding calculation or subsequent calls.
    result=convert_poptracker_pack(source, output)
    assert result.maps == 1
    assert result.location_files == 1
    # Variable(s): `zf` (ZIP archive handle); named state retained for the surrounding calculation or subsequent calls.
    with zipfile.ZipFile(output) as zf:
        # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
        names=set(zf.namelist())
        assert 'wayfinder_pack.json' in names
        assert 'maps/maps.json' in names
        assert 'maps/start.png' in names
        assert 'locations/main.json' in names
        # Variable(s): `meta` (meta); named state retained for the surrounding calculation or subsequent calls.
        meta=json.loads(zf.read('wayfinder_pack.json'))
        assert meta['source_format'] == 'PopTracker'


# /**
#  * Function: test_ut_conversion_preserves_ut_locations
#  * Purpose: Perform the test ut conversion preserves ut locations operation while keeping the surrounding subsystem state consistent.
#  * @param tmp_path: Tmp path supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_ut_conversion_preserves_ut_locations(tmp_path):
    """Handle test ut conversion preserves ut locations."""
    import json, zipfile
    from wayfinder.maps.converter import convert_ut_pack

    # Variable(s): `source` (source); named state retained for the surrounding calculation or subsequent calls.
    source=tmp_path/'ut.zip'
    # Variable(s): `zf` (ZIP archive handle); named state retained for the surrounding calculation or subsequent calls.
    with zipfile.ZipFile(source,'w') as zf:
        zf.writestr('maps/maps.json', json.dumps([{'name':'map','img':'maps/map.png'}]))
        zf.writestr('maps/map.png', b'image')
        zf.writestr('ut_locations/checks.json', json.dumps([{'name':'Check','map_locations':[{'map':'map','x':1,'y':2}]}]))
    # Variable(s): `output` (output); named state retained for the surrounding calculation or subsequent calls.
    output=tmp_path/'ut-wayfinder.zip'
    # Variable(s): `result` (result); named state retained for the surrounding calculation or subsequent calls.
    result=convert_ut_pack(source, output)
    assert result.location_files == 1
    # Variable(s): `zf` (ZIP archive handle); named state retained for the surrounding calculation or subsequent calls.
    with zipfile.ZipFile(output) as zf:
        assert 'ut_locations/checks.json' in zf.namelist()
        # Variable(s): `meta` (meta); named state retained for the surrounding calculation or subsequent calls.
        meta=json.loads(zf.read('wayfinder_pack.json'))
        assert meta['source_format'] == 'WayFinder Legacy Pack'


# /**
#  * Function: test_native_ap_state_matches_archipelago_prog_items_shape
#  * Purpose: Perform the test native ap state matches archipelago prog items shape operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_native_ap_state_matches_archipelago_prog_items_shape():
    """Handle test native ap state matches archipelago prog items shape."""
    from collections import Counter
    from types import SimpleNamespace
    from wayfinder.logic.apworld_adapter import evaluate_generated_world

    # Variable(s): `start` (start); named state retained for the surrounding calculation or subsequent calls.
    start = SimpleNamespace(name="Shrine - Start", player=1, exits=[], locations=[])
    # Variable(s): `after` (after); named state retained for the surrounding calculation or subsequent calls.
    after = SimpleNamespace(name="Shrine - After first magic switch", player=1, exits=[], locations=[])
    # Mimic APWorld helper libraries that inspect CollectionState.prog_items
    # directly instead of calling state.has().
    # Variable(s): `entrance` (entrance); named state retained for the surrounding calculation or subsequent calls.
    entrance = SimpleNamespace(
        name="Shrine barrier",
        connected_region=after,
        access_rule=lambda state: state.prog_items[1]["Shrine First Magic Barrier"] >= 1,
    )
    start.exits = [entrance]
    # Variable(s): `check` (check); named state retained for the surrounding calculation or subsequent calls.
    check = SimpleNamespace(
        name="Shrine - 3. Copper Coin in Grand Hall statue barrier",
        address=1003, parent_region=after, item=None, access_rule=lambda state: True,
    )
    after.locations = [check]
    # Variable(s): `multiworld` (multiworld); named state retained for the surrounding calculation or subsequent calls.
    multiworld = SimpleNamespace(regions=[start, after])
    # Variable(s): `world` (world); named state retained for the surrounding calculation or subsequent calls.
    world = SimpleNamespace(
        game="Little Witch Nobeta",
        origin_region_name="Shrine - Start",
        item_name_groups={},
    )

    # Variable(s): `snap` (snap); named state retained for the surrounding calculation or subsequent calls.
    snap = evaluate_generated_world(
        multiworld=multiworld, world=world, player=1,
        inventory=Counter({"Shrine First Magic Barrier": 1}),
    )
    assert "Shrine - After first magic switch" in snap.reachable_regions
    assert "Shrine - 3. Copper Coin in Grand Hall statue barrier" in snap.reachable_locations
    assert not snap.errors


def test_poptracker_conversion_accepts_comments_and_trailing_commas(tmp_path):
    """Handle test poptracker conversion accepts comments and trailing commas."""
    import json, zipfile
    from wayfinder.maps.converter import convert_poptracker_pack

    source = tmp_path / "relaxed-poptracker.zip"
    with zipfile.ZipFile(source, "w") as zf:
        zf.writestr(
            "Pack/manifest.json",
            '{\n  // pack name\n  "name": "Relaxed Pack",\n}\n',
        )
        zf.writestr(
            "Pack/maps/maps.json",
            '[\n  {"name":"start","img":"maps/start.png","title":"Start",}, // map\n]\n',
        )
        zf.writestr("Pack/maps/start.png", b"image")
        zf.writestr(
            "Pack/locations/main.json",
            '[\n  {\n    "name": "URL // is data, not a comment",\n    "map_locations": [{"map":"start","x":10,"y":20,}],\n  },\n]\n',
        )

    output = tmp_path / "converted.zip"
    result = convert_poptracker_pack(source, output)

    assert result.maps == 1
    assert result.location_files == 1
    assert any("compatibility parsing" in warning for warning in result.warnings)
    assert any("locations/main.json" in warning for warning in result.warnings)
    with zipfile.ZipFile(output) as zf:
        converted_locations = json.loads(zf.read("locations/main.json"))
        assert converted_locations[0]["name"] == "URL // is data, not a comment"


def test_poptracker_conversion_reports_malformed_filename_and_position(tmp_path):
    """Handle test poptracker conversion reports malformed filename and position."""
    import json, zipfile
    import pytest
    from wayfinder.maps.converter import convert_poptracker_pack

    source = tmp_path / "broken-poptracker.zip"
    with zipfile.ZipFile(source, "w") as zf:
        zf.writestr("Pack/manifest.json", json.dumps({"name": "Broken Pack"}))
        zf.writestr("Pack/maps/maps.json", json.dumps([{"name":"start","img":"maps/start.png"}]))
        zf.writestr("Pack/maps/start.png", b"image")
        zf.writestr("Pack/locations/main.json", '[{"name":"Chest", broken: true}]')

    with pytest.raises(ValueError) as exc_info:
        convert_poptracker_pack(source, tmp_path / "converted.zip")

    message = str(exc_info.value)
    assert "locations/main.json" in message
    assert "line 1" in message
    assert "column" in message


def test_poptracker_converter_imports_nested_autotracking_location_ids(tmp_path):
    """Nested PopTracker sections should resolve through Lua AP location IDs."""
    import json
    import zipfile
    from pathlib import Path
    from wayfinder.maps.converter import convert_poptracker_pack
    from wayfinder.maps.packs import _parse_pack

    source = tmp_path / "nested-poptracker.zip"
    output = tmp_path / "nested-wayfinder.zip"
    with zipfile.ZipFile(source, "w") as zf:
        zf.writestr("Pack/manifest.json", json.dumps({"name": "Nested Test"}))
        zf.writestr(
            "Pack/maps/maps.json",
            json.dumps([{"name": "world", "img": "images/maps/world.png", "title": "World"}]),
        )
        zf.writestr("Pack/images/maps/world.png", b"image")
        zf.writestr(
            "Pack/locations/world.json",
            json.dumps([
                {
                    "name": "World",
                    "children": [
                        {
                            "name": "Act One",
                            "children": [
                                {
                                    "name": "Deep Group",
                                    "sections": [{"name": "Yarn"}, {"name": "Time Piece"}],
                                    "map_locations": [{"map": "world", "x": 10, "y": 20}],
                                }
                            ],
                        }
                    ],
                }
            ]),
        )
        zf.writestr(
            "Pack/scripts/autotracking/location_mapping.lua",
            'LOCATION_MAPPING = {\n'
            '  [12345] = "@World/Act One/Deep Group/Yarn",\n'
            '  [12346] = "@World/Act One/Deep Group/Time Piece",\n'
            '  -- [99999] = "@World/Act One/Deep Group/Disabled",\n'
            '}\n',
        )

    result = convert_poptracker_pack(source, output)
    assert any("autotracking location ID" in warning for warning in result.warnings)
    with zipfile.ZipFile(output) as zf:
        mapping = json.loads(zf.read("packbash_location_ids.json"))
    assert mapping["World/Act One/Deep Group/Yarn"] == 12345
    assert mapping["World/Act One/Deep Group/Time Piece"] == 12346
    assert "World/Act One/Deep Group/Disabled" not in mapping

    pack = _parse_pack(Path(output))
    assert pack is not None
    markers = pack.markers_by_map["world"]
    assert len(markers) == 1
    assert markers[0].member_names == ("Yarn", "Time Piece")
    assert markers[0].section_ids == ((12345,), (12346,))


def test_deferred_entrance_compatibility_mode_is_string_off():
    """WayFinder exposes the deferred-entrance compatibility hook using its string contract."""
    source = (Path(__file__).parents[2] / "wayfinder" / "runtime" / "world_builder.py").read_text(encoding="utf-8")
    assert 'multiworld.enforce_deferred_connections = "off"' in source
    assert "multiworld.enforce_deferred_connections = 1" not in source
