"""Provide test hints logic snapshot support."""
# /**
#  * Module: tests/test_hints_logic_snapshot.py
#  * Purpose: Regression tests for test hints logic snapshot; documents expected behavior so future refactors remain compatible.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from types import SimpleNamespace

from wayfinder.runtime.snapshot import _live_hints


# /**
#  * Class: Lookup
#  * Purpose: Encapsulate the Lookup responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
class Lookup:
    # /**
    #  * Function: __init__
    #  * Purpose: Initialize this object and establish its required runtime state.
    #  * @param values: Values supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    """Provide lookup behavior."""
    def __init__(self, values):
        """Handle init."""
        self.values = values
    # /**
    #  * Function: __getitem__
    #  * Purpose: Perform the getitem operation while keeping the surrounding subsystem state consistent.
    #  * @param game: Game supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def __getitem__(self, game):
        """Handle getitem."""
        return self.values.get(game, {})


# /**
#  * Function: test_live_hints_reads_archipelago_datastorage_and_resolves_names
#  * Purpose: Perform the test live hints reads archipelago datastorage and resolves names operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_live_hints_reads_archipelago_datastorage_and_resolves_names():
    # Variable(s): `ctx` (context); named state retained for the surrounding calculation or subsequent calls.
    """Handle test live hints reads archipelago datastorage and resolves names."""
    ctx = SimpleNamespace(
        team=0,
        game="Little Witch Nobeta",
        stored_data={
            "_read_hints_0_1": [{
                "receiving_player": 1,
                "finding_player": 1,
                "location": 200,
                "item": 100,
                "found": False,
                "entrance": "",
                "item_flags": 1,
                "status": 30,
            }]
        },
        player_names={1: "Nobeta"},
        slot_info={1: SimpleNamespace(game="Little Witch Nobeta")},
        item_names=Lookup({"Little Witch Nobeta": {100: "Shrine First Magic Barrier"}}),
        location_names=Lookup({"Little Witch Nobeta": {200: "Shrine - First magic switch"}}),
    )
    # Variable(s): `key` (key), `rows` (rows); named state retained for the surrounding calculation or subsequent calls.
    key, rows = _live_hints(ctx, 1, {}, {})
    assert key == "_read_hints_0_1"
    assert rows == [{
        "item": "Shrine First Magic Barrier",
        "location": "Shrine - First magic switch",
        "receiving_player": "Nobeta",
        "finding_player": "Nobeta",
        "found": False,
        "status": "priority",
        "entrance": "",
        "item_flags": 1,
    }]


# /**
#  * Function: test_live_hints_found_overrides_status
#  * Purpose: Perform the test live hints found overrides status operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def test_live_hints_found_overrides_status():
    # Variable(s): `ctx` (context); named state retained for the surrounding calculation or subsequent calls.
    """Handle test live hints found overrides status."""
    ctx = SimpleNamespace(
        team=0, game="Test", stored_data={"_read_hints_0_1": [{
            "receiving_player": 1, "finding_player": 1, "location": 2,
            "item": 3, "found": True, "status": 0,
        }]}, player_names={1:"Player"}, slot_info={},
        item_names=Lookup({}), location_names=Lookup({}),
    )
    # Variable(s): `_` (_), `rows` (rows); named state retained for the surrounding calculation or subsequent calls.
    _, rows = _live_hints(ctx, 1, {3:"Item"}, {2:"Location"})
    assert rows[0]["status"] == "found"
    assert rows[0]["item"] == "Item"
    assert rows[0]["location"] == "Location"


def test_live_hints_merges_other_player_hint_keys_without_duplicates():
    """Handle test live hints merges other player hint keys without duplicates."""
    ctx = SimpleNamespace(
        team=0, game="Test",
        stored_data={
            "_read_hints_0_1": [{
                "receiving_player": 1, "finding_player": 2, "item": 3, "location": 4,
                "found": False, "status": 30, "entrance": "", "item_flags": 1,
            }],
            "_read_hints_0_2": [{
                "receiving_player": 1, "finding_player": 2, "item": 3, "location": 4,
                "found": False, "status": 30, "entrance": "", "item_flags": 1,
            }, {
                "receiving_player": 2, "finding_player": 1, "item": 5, "location": 6,
                "found": True, "status": 40, "entrance": "", "item_flags": 0,
            }],
        },
        player_names={1: "Alice", 2: "Bob"},
        slot_info={1: SimpleNamespace(game="Test"), 2: SimpleNamespace(game="Test")},
        item_names=Lookup({"Test": {3: "Item A", 5: "Item B"}}),
        location_names=Lookup({"Test": {4: "Loc A", 6: "Loc B"}}),
    )
    key, rows = _live_hints(ctx, 1, {3: "Item A", 5: "Item B"}, {4: "Loc A", 6: "Loc B"})
    assert key == "2 team hint keys"
    assert len(rows) == 2
    assert {(row["receiving_player"], row["finding_player"]) for row in rows} == {("Alice", "Bob"), ("Bob", "Alice")}

