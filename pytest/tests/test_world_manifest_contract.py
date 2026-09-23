"""Regression coverage for APWorld manifest metadata stamping."""
import sys
from types import SimpleNamespace

from wayfinder.runtime.world_loader import _apply_world_manifest_contract


class FakeVersion(tuple):
    """Small AP Version stand-in used without requiring an installed AP core."""
    def as_simple_string(self):
        return ".".join(map(str, self))


def _version(text):
    return FakeVersion(int(part) for part in text.split("."))


def test_manifest_world_version_is_applied_to_world_class(monkeypatch):
    monkeypatch.setitem(sys.modules, "Utils", SimpleNamespace(tuplize_version=_version))
    world = type("DemoWorld", (), {"world_version": FakeVersion((0, 0, 0)), "manifest": {}})
    record = SimpleNamespace(manifest={
        "game": "Ship of Harkinian",
        "world_version": "1.4.1",
        "minimum_ap_version": "0.6.7",
        "version": 7,
        "compatible_version": 7,
    })

    _apply_world_manifest_contract(world, record)

    assert world.world_version == FakeVersion((1, 4, 1))
    assert world.world_version.as_simple_string() == "1.4.1"
    assert world._wayfinder_manifest_version == "1.4.1"
    assert world.manifest["world_version"] == "1.4.1"
    assert world.manifest["minimum_ap_version"] == "0.6.7"
    assert "version" not in world.manifest
    assert "compatible_version" not in world.manifest


def test_unknown_manifest_version_does_not_invent_zero_version(monkeypatch):
    monkeypatch.setitem(sys.modules, "Utils", SimpleNamespace(tuplize_version=_version))
    existing = FakeVersion((2, 3, 4))
    world = type("LegacyWorld", (), {"world_version": existing, "manifest": {}})
    record = SimpleNamespace(manifest={"game": "Legacy Game"})

    _apply_world_manifest_contract(world, record)

    assert world.world_version is existing
    assert world._wayfinder_manifest_version == ""


def test_manifest_version_supports_generator_minimum_comparison(monkeypatch):
    monkeypatch.setitem(sys.modules, "Utils", SimpleNamespace(tuplize_version=_version))
    world = type("DemoWorld", (), {"world_version": FakeVersion((0, 0, 0)), "manifest": {}})
    record = SimpleNamespace(manifest={"game": "Demo", "world_version": "1.4.1"})
    _apply_world_manifest_contract(world, record)

    assert not (_version("1.4.1") > world.world_version)
    assert _version("1.5.0") > world.world_version
    assert _version("1.4.0") < world.world_version
