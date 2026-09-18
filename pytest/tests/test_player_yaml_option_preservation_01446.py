"""Provide test player yaml option preservation 01446 support."""
from pathlib import Path
from types import SimpleNamespace

from wayfinder.runtime.world_builder import (
    _apply_player_yaml_option_overrides,
    _read_player_yaml_game_options,
)


class ToggleLike:
    """Provide toggle like behavior."""
    def __init__(self, value=False):
        """Handle init."""
        self.value = value

    @classmethod
    def from_any(cls, value):
        """Handle from any."""
        if isinstance(value, str):
            value = value.strip().lower() in {"1", "true", "yes", "on"}
        return cls(bool(value))


class SetLike:
    """Provide set like behavior."""
    def __init__(self, value=None):
        """Handle init."""
        self.value = set(value or set())

    @classmethod
    def from_any(cls, value):
        """Handle from any."""
        return cls(value)


def test_direct_yaml_preserves_frlg_roadblock_options_before_rules(tmp_path: Path):
    """Handle test direct yaml preserves frlg roadblock options before rules."""
    yaml_path = tmp_path / "MaeFireRed.yaml"
    yaml_path.write_text(
        """name: MaeFireRed
game: Pokemon FireRed and LeafGreen
Pokemon FireRed and LeafGreen:
  route_12_boulders: true
  route_12_rocks: true
  route_16_rock: true
  remove_badge_requirement: []
  random_starting_town: random
""",
        encoding="utf-8",
    )
    values = _read_player_yaml_game_options(yaml_path, "Pokemon FireRed and LeafGreen")
    assert values["route_12_boulders"] is True
    assert values["route_12_rocks"] is True
    assert values["route_16_rock"] is True
    assert values["remove_badge_requirement"] == []
    assert "random_starting_town" not in values

    world = SimpleNamespace(
        game="Pokemon FireRed and LeafGreen",
        options=SimpleNamespace(
            route_12_boulders=ToggleLike(False),
            route_12_rocks=ToggleLike(False),
            route_16_rock=ToggleLike(False),
            remove_badge_requirement=SetLike(set()),
        ),
    )
    changed = _apply_player_yaml_option_overrides(world, values)
    assert world.options.route_12_boulders.value is True
    assert world.options.route_12_rocks.value is True
    assert world.options.route_16_rock.value is True
    assert set(world.options.remove_badge_requirement.value) == set()
    assert "route_12_boulders" in changed


def test_unknown_yaml_keys_do_not_mutate_world_options():
    """Handle test unknown yaml keys do not mutate world options."""
    world = SimpleNamespace(game="Example", options=SimpleNamespace(known=ToggleLike(False)))
    _apply_player_yaml_option_overrides(world, {"unknown": True, "known": True})
    assert world.options.known.value is True
    assert not hasattr(world.options, "unknown")
