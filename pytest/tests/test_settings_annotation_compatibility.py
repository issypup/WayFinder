"""Provide test settings annotation compatibility support."""
from pathlib import Path


def test_world_builder_installs_python314_instance_annotation_compatibility():
    """Handle test world builder installs python314 instance annotation compatibility."""
    source = (Path(__file__).parents[2] / "wayfinder" / "runtime" / "world_builder.py").read_text(encoding="utf-8")
    assert 'attribute_name == "__annotations__"' in source
    assert 'object.__getattribute__(instance, "__class__")' in source
    assert 'group_base.__getattribute__ = _wayfinder_group_getattribute' in source
    assert '_wayfinder_annotations_compat' in source


def test_world_builder_preserves_deferred_annotations_and_empty_fallback(monkeypatch):
    """Handle test world builder preserves deferred annotations and empty fallback."""
    import sys
    import types
    from wayfinder.runtime.world_builder import _install_archipelago_settings_annotation_compatibility
    module = types.ModuleType('settings')
    exec('class Group: pass\nclass Settings(Group):\n    option: int = 42\n', module.__dict__)
    monkeypatch.setitem(sys.modules, 'settings', module)
    _install_archipelago_settings_annotation_compatibility()
    assert module.Settings().__annotations__ == {'option': int}
    assert module.Group().__annotations__ == {}
    _install_archipelago_settings_annotation_compatibility()
    assert module.Settings().__annotations__ == {'option': int}
