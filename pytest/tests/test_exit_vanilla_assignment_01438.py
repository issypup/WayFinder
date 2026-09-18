"""Provide test exit vanilla assignment 01438 support."""

from types import SimpleNamespace

from wayfinder.runtime.snapshot import _entrance_randomization_enabled


class Opt:
    """Provide opt behavior."""
    def __init__(self, value):
        """Handle init."""
        self.value = value


def test_entrance_rando_false_when_all_related_options_off():
    """Handle test entrance rando false when all related options off."""
    world = SimpleNamespace(options=SimpleNamespace(
        randomize_dungeon_entrances=Opt(False),
        randomize_secret_cave_entrances=Opt(0),
        randomize_miniboss_entrances=Opt(False),
        randomize_boss_entrances=Opt(False),
        randomize_secret_cave_inner_entrances=Opt(False),
        randomize_fairy_fountain_entrances=Opt(False),
    ))
    assert _entrance_randomization_enabled(world) is False


def test_entrance_rando_true_when_any_related_option_on():
    """Handle test entrance rando true when any related option on."""
    world = SimpleNamespace(options=SimpleNamespace(
        randomize_dungeon_entrances=Opt(False),
        randomize_secret_cave_entrances=Opt(True),
    ))
    assert _entrance_randomization_enabled(world) is True


def test_entrance_rando_unknown_when_world_has_no_matching_options():
    """Handle test entrance rando unknown when world has no matching options."""
    world = SimpleNamespace(options=SimpleNamespace(hero_mode=Opt(False)))
    assert _entrance_randomization_enabled(world) is None
