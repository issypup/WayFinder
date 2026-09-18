"""Provide test logic source classification 01461 support."""
from pathlib import Path

from wayfinder.runtime.world_builder import _logic_provenance, _slot_data_authoritative


class YamlOnlyWorld:
    """Provide yaml only world behavior."""
    pass


class SlotFlagWorld:
    """Provide slot flag world behavior."""
    ut_can_gen_without_yaml = True


class InterpretSlotWorld:
    """Provide interpret slot world behavior."""
    @staticmethod
    def interpret_slot_data(slot_data):
        """Handle interpret slot data."""
        return dict(slot_data)


def test_yaml_is_authoritative_logic_source():
    """Handle test yaml is authoritative logic source."""
    exact, source = _logic_provenance(YamlOnlyWorld, Path("Issy.yaml"))
    assert exact is True
    assert source == "Player YAML"


def test_slot_capabilities_are_authoritative_without_yaml():
    """Handle test slot capabilities are authoritative without yaml."""
    for world in (SlotFlagWorld, InterpretSlotWorld):
        assert _slot_data_authoritative(world) is True
        exact, source = _logic_provenance(world, None)
        assert exact is True
        assert source == "AP slot data"


def test_default_generation_is_explicitly_approximate():
    """Handle test default generation is explicitly approximate."""
    exact, source = _logic_provenance(YamlOnlyWorld, None)
    assert exact is False
    assert source == "Default options — approximate"
