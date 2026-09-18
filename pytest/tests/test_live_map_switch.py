"""Provide test live map switch support."""
# /**
#  * Module: tests/test_live_map_switch.py
#  * Purpose: Regression tests for test live map switch; documents expected behavior so future refactors remain compatible.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from types import SimpleNamespace

from wayfinder.runtime.snapshot import _live_map_page_state
from wayfinder.runtime.world_builder import _map_switch_capability


# /**
#  * Function: test_reads_apworld_tracker_map_switch_metadata
#  * Purpose: Perform the test reads apworld tracker map switch metadata operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_reads_apworld_tracker_map_switch_metadata():
    # /**
    #  * Function: map_page_index
    #  * Purpose: Perform the map page index operation while keeping the surrounding subsystem state consistent.
    #  * @param value: Value supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    """Handle test reads apworld tracker map switch metadata."""
    def map_page_index(value):
        """Handle map page index."""
        return {2: 0, 3: 1, 4: 2}.get(value, 0)

    # Variable(s): `world` (world); named state retained for the surrounding calculation or subsequent calls.
    world = SimpleNamespace(
        tracker_world={
            "map_page_setting_key": "Slot:{player}:lwn_map",
            "map_page_index": map_page_index,
        }
    )
    # Variable(s): `key` (key), `hook` (hook); named state retained for the surrounding calculation or subsequent calls.
    key, hook = _map_switch_capability(world)
    assert key == "Slot:{player}:lwn_map"
    assert hook(3) == 1


# /**
#  * Function: test_live_datastorage_value_becomes_map_index
#  * Purpose: Perform the test live datastorage value becomes map index operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_live_datastorage_value_becomes_map_index():
    # Variable(s): `built` (built); named state retained for the surrounding calculation or subsequent calls.
    """Handle test live datastorage value becomes map index."""
    built = SimpleNamespace(
        resolved_map_page_setting_key="Slot:1:lwn_map",
        map_page_index_hook=lambda value: {2: 0, 3: 1, 4: 2, 5: 3}.get(value, 0),
    )
    # Variable(s): `ctx` (context); named state retained for the surrounding calculation or subsequent calls.
    ctx = SimpleNamespace(stored_data={"Slot:1:lwn_map": 4})
    # Variable(s): `key` (key), `raw` (raw value), `idx` (index); named state retained for the surrounding calculation or subsequent calls.
    key, raw, idx = _live_map_page_state(ctx, built)
    assert key == "Slot:1:lwn_map"
    assert raw == 4
    assert idx == 2
