"""Provide test frlg strength and checked state 01443 support."""
from collections import Counter
from types import SimpleNamespace

from wayfinder.logic.apworld_adapter import NativeAPState
from wayfinder.runtime.snapshot import _checked_location_names
from wayfinder.runtime.world_builder import _install_world_rule_safety_guards


class FakeMultiWorld:
    """Provide fake multi world behavior."""
    def __init__(self, entrances):
        """Handle init."""
        self.entrances = entrances

    def get_entrance(self, name, player):
        """Return get entrance."""
        if name not in self.entrances:
            raise KeyError(name)
        return self.entrances[name]


def _frlg_world(*, remove_badge_requirement=()):
    """Handle frlg world."""
    return SimpleNamespace(
        game="Pokemon FireRed and LeafGreen",
        options=SimpleNamespace(
            route_12_boulders=SimpleNamespace(value=True),
            remove_badge_requirement=SimpleNamespace(value=set(remove_badge_requirement)),
        ),
    )


def test_route12_boulder_guard_requires_rainbow_badge():
    """Handle test route12 boulder guard requires rainbow badge."""
    entrance = SimpleNamespace(access_rule=lambda state: True)
    mw = FakeMultiWorld({"Route 11 East Exit": entrance})
    installed = _install_world_rule_safety_guards(_frlg_world(), mw, 1)
    assert "Route 11 East Exit" in installed

    inventory = Counter({"HM04 Strength": 1, "TM Case": 1, "Teach Strength": 1})
    state = NativeAPState(1, inventory, set(), set(), {}, None)
    assert entrance.access_rule(state) is False

    inventory["Rainbow Badge"] = 1
    state = NativeAPState(1, inventory, set(), set(), {}, None)
    assert entrance.access_rule(state) is True


def test_route12_boulder_guard_honors_removed_strength_badge_requirement():
    """Handle test route12 boulder guard honors removed strength badge requirement."""
    entrance = SimpleNamespace(access_rule=lambda state: True)
    mw = FakeMultiWorld({"Route 12 North Exit": entrance})
    _install_world_rule_safety_guards(_frlg_world(remove_badge_requirement={"Strength"}), mw, 1)
    inventory = Counter({"HM04 Strength": 1, "TM Case": 1, "Teach Strength": 1})
    state = NativeAPState(1, inventory, set(), set(), {}, None)
    assert entrance.access_rule(state) is True


def test_checked_names_fall_back_to_live_server_datapackage_when_ids_differ():
    """Handle test checked names fall back to live server datapackage when ids differ."""
    ctx = SimpleNamespace(
        game="Example Game",
        location_names={"Example Game": {9001: "Already Completed Check"}},
    )
    reconstructed = {1001: "Already Completed Check"}
    names = _checked_location_names(ctx, reconstructed, {9001})
    assert "Already Completed Check" in names


def test_checked_names_still_support_matching_reconstructed_ids():
    """Handle test checked names still support matching reconstructed ids."""
    ctx = SimpleNamespace(game="Example Game", location_names={"Example Game": {1001: "Check A"}})
    assert _checked_location_names(ctx, {1001: "Check A"}, {1001}) == {"Check A"}
