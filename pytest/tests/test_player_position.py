"""Provide test player position support."""
# /**
#  * Module: tests/test_player_position.py
#  * Purpose: Regression tests for test player position; documents expected behavior so future refactors remain compatible.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from types import SimpleNamespace
from wayfinder.runtime.snapshot import _normalise_player_position, _live_player_position_state
from wayfinder.runtime.world_builder import _player_position_capability

# /**
#  * Function: test_position_capability_from_tracker_metadata
#  * Purpose: Perform the test position capability from tracker metadata operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_position_capability_from_tracker_metadata():
    # Variable(s): `hook` (hook); named state retained for the surrounding calculation or subsequent calls.
    """Handle test position capability from tracker metadata."""
    hook=lambda v: {"map_index": 2, "x": v[0], "y": v[1]}
    # Variable(s): `world` (world); named state retained for the surrounding calculation or subsequent calls.
    world=SimpleNamespace(tracker_world={"player_position_setting_key":"Slot:{player}:pos", "player_position":hook})
    # Variable(s): `key` (key), `found` (found); named state retained for the surrounding calculation or subsequent calls.
    key, found=_player_position_capability(world)
    assert key == "Slot:{player}:pos" and found is hook

# /**
#  * Function: test_normalise_position_dict
#  * Purpose: Perform the test normalise position dict operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_normalise_position_dict():
    # Variable(s): `idx` (index), `icons` (icons); named state retained for the surrounding calculation or subsequent calls.
    """Handle test normalise position dict."""
    idx, icons=_normalise_player_position({"map_index":1,"x":123,"y":456})
    assert idx == 1 and icons == [{"x":123.0,"y":456.0}]

# /**
#  * Function: test_live_position_from_stored_data
#  * Purpose: Perform the test live position from stored data operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_live_position_from_stored_data():
    # Variable(s): `ctx` (context); named state retained for the surrounding calculation or subsequent calls.
    """Handle test live position from stored data."""
    ctx=SimpleNamespace(stored_data={"Slot:1:pos":[10,20]})
    # Variable(s): `built` (built); named state retained for the surrounding calculation or subsequent calls.
    built=SimpleNamespace(resolved_player_position_setting_key="Slot:1:pos", player_position_hook=lambda v:{"map_index":0,"x":v[0],"y":v[1]})
    # Variable(s): `key` (key), `raw` (raw value), `idx` (index), `icons` (icons); named state retained for the surrounding calculation or subsequent calls.
    key, raw, idx, icons=_live_player_position_state(ctx,built)
    assert key == "Slot:1:pos" and idx == 0 and icons[0]["x"] == 10.0
