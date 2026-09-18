"""Provide test logic api incremental support."""
# /**
#  * Module: tests/test_logic_api_incremental.py
#  * Purpose: Regression tests for test logic api incremental; documents expected behavior so future refactors remain compatible.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from collections import Counter
from types import SimpleNamespace

from wayfinder.logic import (
    EntranceDefinition, LocationDefinition, LogicEngine, RegionDefinition,
    TrackerDefinition, TrackerInput, WAYFINDER_LOGIC_API, item,
)
from wayfinder.logic.comparison import compare_snapshots
from wayfinder.logic.incremental import IncrementalAPWorldEvaluator


# /**
#  * Function: test_logic_api_v1_is_stable_surface
#  * Purpose: Perform the test logic api v1 is stable surface operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_logic_api_v1_is_stable_surface():
    # Variable(s): `definition` (definition); named state retained for the surrounding calculation or subsequent calls.
    """Handle test logic api v1 is stable surface."""
    definition = TrackerDefinition(
        game="API Test",
        regions={"Start": RegionDefinition("Start", starting=True)},
        locations={"Chest": LocationDefinition("Chest", "Start", item("Key"))},
    )
    # Variable(s): `snap` (snap); named state retained for the surrounding calculation or subsequent calls.
    snap = LogicEngine(definition).evaluate_api(TrackerInput(inventory=Counter({"Key": 1})))
    assert snap.api_version == WAYFINDER_LOGIC_API == 1
    assert snap.locations["Chest"].reachable is True
    assert snap.locations["Chest"].status == "reachable"


# /**
#  * Function: _fake_world
#  * Purpose: Perform the fake world operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _fake_world():
    # Variable(s): `region` (region); named state retained for the surrounding calculation or subsequent calls.
    """Handle fake world."""
    region = SimpleNamespace(name="Start", player=1, exits=[], locations=[])
    # Variable(s): `key_check` (key check); named state retained for the surrounding calculation or subsequent calls.
    key_check = SimpleNamespace(name="Key Check", address=1, parent_region=region, access_rule=lambda s: s.has("Key", 1))
    # Variable(s): `free_check` (free check); named state retained for the surrounding calculation or subsequent calls.
    free_check = SimpleNamespace(name="Free Check", address=2, parent_region=region, access_rule=lambda s: True)
    region.locations = [key_check, free_check]

    # /**
    #  * Class: MW
    #  * Purpose: Encapsulate the MW responsibilities and state used by this module.
    #  * @state: Instance attributes hold the durable state needed by this responsibility.
    #  */
    class MW(SimpleNamespace):
        # /**
        #  * Function: get_location
        #  * Purpose: Retrieve location information for the current operation.
        #  * @param name: Name supplied by the caller; see type hints and call sites for domain constraints.
        #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        """Provide m w behavior."""
        def get_location(self, name, player):
            """Return get location."""
            return {x.name: x for x in region.locations}[name]

    # Variable(s): `multiworld` (multiworld); named state retained for the surrounding calculation or subsequent calls.
    multiworld = MW(regions=[region])
    # Variable(s): `world` (world); named state retained for the surrounding calculation or subsequent calls.
    world = SimpleNamespace(game="Incremental Test", origin_region_name="Start", item_name_groups={})
    return multiworld, world


# /**
#  * Function: test_incremental_location_only_item_change_reuses_graph
#  * Purpose: Perform the test incremental location only item change reuses graph operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_incremental_location_only_item_change_reuses_graph():
    # Variable(s): `multiworld` (multiworld), `world` (world); named state retained for the surrounding calculation or subsequent calls.
    """Handle test incremental location only item change reuses graph."""
    multiworld, world = _fake_world()
    # Variable(s): `evaluator` (evaluator); named state retained for the surrounding calculation or subsequent calls.
    evaluator = IncrementalAPWorldEvaluator(multiworld=multiworld, world=world, player=1)
    # Variable(s): `first` (first); named state retained for the surrounding calculation or subsequent calls.
    first = evaluator.evaluate(Counter(), set())
    assert first.stats.mode == "full"
    # Variable(s): `second` (second); named state retained for the surrounding calculation or subsequent calls.
    second = evaluator.evaluate(Counter({"Key": 1}), set())
    assert second.stats.mode == "incremental"
    assert second.stats.nodes_evaluated == 1
    assert "Key Check" in second.snapshot.reachable_locations
    assert "Free Check" in second.snapshot.reachable_locations


# /**
#  * Function: test_incremental_opaque_dependency_falls_back_full
#  * Purpose: Perform the test incremental opaque dependency falls back full operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_incremental_direct_prog_items_dependency_is_traceable():
    # Variable(s): `region` (region); named state retained for the surrounding calculation or subsequent calls.
    """Handle test incremental direct prog items dependency is traceable."""
    region = SimpleNamespace(name="Start", player=1, exits=[], locations=[])
    # Direct prog_items access deliberately bypasses traceable state.has().
    # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
    loc = SimpleNamespace(name="Opaque Check", address=1, parent_region=region, access_rule=lambda s: s.prog_items[1]["Key"] >= 1)
    region.locations = [loc]

    # /**
    #  * Class: MW
    #  * Purpose: Encapsulate the MW responsibilities and state used by this module.
    #  * @state: Instance attributes hold the durable state needed by this responsibility.
    #  */
    class MW(SimpleNamespace):
        # /**
        #  * Function: get_location
        #  * Purpose: Retrieve location information for the current operation.
        #  * @param name: Name supplied by the caller; see type hints and call sites for domain constraints.
        #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        """Provide m w behavior."""
        def get_location(self, name, player): return loc

    # Variable(s): `evaluator` (evaluator); named state retained for the surrounding calculation or subsequent calls.
    evaluator = IncrementalAPWorldEvaluator(
        multiworld=MW(regions=[region]),
        world=SimpleNamespace(game="Opaque", origin_region_name="Start", item_name_groups={}), player=1,
    )
    evaluator.evaluate(Counter(), set())
    # Variable(s): `second` (second); named state retained for the surrounding calculation or subsequent calls.
    second = evaluator.evaluate(Counter({"Key": 1}), set())
    assert second.stats.mode == "incremental"
    assert not second.stats.fallback_reason


# /**
#  * Function: test_logic_comparison_reports_differences
#  * Purpose: Perform the test logic comparison reports differences operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_logic_comparison_reports_differences():
    # Variable(s): `definition` (definition); named state retained for the surrounding calculation or subsequent calls.
    """Handle test logic comparison reports differences."""
    definition = TrackerDefinition(
        game="Compare",
        regions={"Start": RegionDefinition("Start", starting=True)},
        locations={"Chest": LocationDefinition("Chest", "Start", item("Key"))},
    )
    # Variable(s): `engine` (engine); named state retained for the surrounding calculation or subsequent calls.
    engine = LogicEngine(definition)
    # Variable(s): `a` (a); named state retained for the surrounding calculation or subsequent calls.
    a = engine.evaluate(TrackerInput())
    # Variable(s): `b` (b); named state retained for the surrounding calculation or subsequent calls.
    b = engine.evaluate(TrackerInput(inventory=Counter({"Key": 1})))
    # Variable(s): `report` (report); named state retained for the surrounding calculation or subsequent calls.
    report = compare_snapshots(a, b, reference_name="v1", candidate_name="v2")
    assert not report.passed
    assert any(d.name == "Chest" for d in report.differences)


# /**
#  * Function: test_incremental_preserves_swept_event_items_for_location_rules
#  * Purpose: Perform the test incremental preserves swept event items for location rules operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_incremental_preserves_swept_event_items_for_location_rules():
    # Variable(s): `region` (region); named state retained for the surrounding calculation or subsequent calls.
    """Handle test incremental preserves swept event items for location rules."""
    region = SimpleNamespace(name="Start", player=1, exits=[], locations=[])
    # Variable(s): `event_item` (event item); named state retained for the surrounding calculation or subsequent calls.
    event_item = SimpleNamespace(name="Opened Gate")
    # Variable(s): `event_loc` (event loc); named state retained for the surrounding calculation or subsequent calls.
    event_loc = SimpleNamespace(name="Gate Event", address=None, item=event_item, parent_region=region, access_rule=lambda s: True)
    # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
    loc = SimpleNamespace(name="Event Check", address=3, parent_region=region, access_rule=lambda s: s.has("Opened Gate") and s.has("Key"))
    region.locations = [event_loc, loc]

    # /**
    #  * Class: MW
    #  * Purpose: Encapsulate the MW responsibilities and state used by this module.
    #  * @state: Instance attributes hold the durable state needed by this responsibility.
    #  */
    class MW(SimpleNamespace):
        # /**
        #  * Function: get_location
        #  * Purpose: Retrieve location information for the current operation.
        #  * @param name: Name supplied by the caller; see type hints and call sites for domain constraints.
        #  * @param player: Player supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        """Provide m w behavior."""
        def get_location(self, name, player): return {x.name: x for x in region.locations}[name]

    # Variable(s): `evaluator` (evaluator); named state retained for the surrounding calculation or subsequent calls.
    evaluator = IncrementalAPWorldEvaluator(
        multiworld=MW(regions=[region]),
        world=SimpleNamespace(game="Events", origin_region_name="Start", item_name_groups={}), player=1,
    )
    # Variable(s): `first` (first); named state retained for the surrounding calculation or subsequent calls.
    first = evaluator.evaluate(Counter(), set())
    assert "Opened Gate" in first.snapshot.events
    # Variable(s): `second` (second); named state retained for the surrounding calculation or subsequent calls.
    second = evaluator.evaluate(Counter({"Key": 1}), set())
    assert second.stats.mode == "incremental"
    assert "Event Check" in second.snapshot.reachable_locations
