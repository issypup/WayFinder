"""Provide test performance optimisation 01466 support."""
from wayfinder.app.core.source_layout import combined_app_source
import json
import time
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from wayfinder.maps import packs
from wayfinder.logic.incremental import IncrementalAPWorldEvaluator


def _write_pack(root: Path, *, maps=1):
    """Handle write pack."""
    (root / "maps").mkdir(parents=True)
    (root / "locations").mkdir()
    defs=[]
    for index in range(maps):
        name="world" if index == 1 else f"area{index}"
        title="World Map" if index == 1 else f"Area {index}"
        image=f"map{index}.png"
        defs.append({"name": name, "title": title, "img": image})
        Image.new("RGB", (32, 24), "red").save(root / image)
    (root / "maps" / "maps.json").write_text(json.dumps(defs), encoding="utf-8")
    (root / "locations" / "checks.json").write_text(json.dumps([
        {"name": "Check", "map_locations": [{"map": defs[0]["name"], "x": 4, "y": 5}]}
    ]), encoding="utf-8")


def test_core_zoom_cache_is_demand_driven():
    """Handle test core zoom cache is demand driven."""
    assert packs.ZOOM_CACHE_LEVELS == (2, 5, 10, 15, 20, 25, 50, 75, 100, 125, 150, 175, 200)


def test_compiled_metadata_cache_survives_memory_cache_clear(tmp_path, monkeypatch):
    """Handle test compiled metadata cache survives memory cache clear."""
    root=tmp_path / "pack"
    _write_pack(root)
    monkeypatch.setattr(packs, "map_cache_root", lambda: tmp_path / "cache")
    packs._PARSED_PACK_CACHE.clear()
    first=packs._parse_pack(root)
    assert first is not None
    assert getattr(first, "metadata_cache_hit", False) is False
    packs._PARSED_PACK_CACHE.clear()
    with patch.object(packs, "_parse_pack_uncached", side_effect=AssertionError("source metadata reparsed")):
        second=packs._parse_pack(root)
    assert second is not None
    assert getattr(second, "metadata_cache_hit", False) is True
    assert second.maps[0].name == first.maps[0].name
    assert second.marker_spatial_index


def test_metadata_cache_invalidates_when_pack_changes(tmp_path, monkeypatch):
    """Handle test metadata cache invalidates when pack changes."""
    root=tmp_path / "pack"
    _write_pack(root)
    monkeypatch.setattr(packs, "map_cache_root", lambda: tmp_path / "cache")
    packs._PARSED_PACK_CACHE.clear()
    assert packs._parse_pack(root).maps[0].title == "Area 0"
    time.sleep(0.002)
    payload=json.loads((root / "maps" / "maps.json").read_text())
    payload[0]["title"]="Changed"
    (root / "maps" / "maps.json").write_text(json.dumps(payload), encoding="utf-8")
    packs._PARSED_PACK_CACHE.clear()
    assert packs._parse_pack(root).maps[0].title == "Changed"


def test_install_cache_prioritises_default_and_overview_maps(tmp_path, monkeypatch):
    """Handle test install cache prioritises default and overview maps."""
    root=tmp_path / "pack"
    _write_pack(root, maps=3)
    monkeypatch.setattr(packs, "map_cache_root", lambda: tmp_path / "cache")
    packs._PARSED_PACK_CACHE.clear()
    done,total=packs.build_pack_zoom_cache(root)
    assert (done,total) == (len(packs.ZOOM_CACHE_LEVELS) * 2, len(packs.ZOOM_CACHE_LEVELS) * 2)
    manifest=json.loads(packs._cache_manifest_path(root).read_text(encoding="utf-8"))
    lazy={row["map"] for row in manifest["deferred_maps"] if row.get("reason") == "lazy-on-demand"}
    assert "area2" in lazy
    assert packs.cached_map_path(root, "map2.png", 100).exists() is False


def test_incremental_evaluator_uses_static_metadata_reuse_source_contract():
    # This intentionally guards the architecture, not a particular APWorld: live
    # incremental evaluation must not return to deepcopying the full rule graph.
    """Handle test incremental evaluator uses static metadata reuse source contract."""
    source=Path(IncrementalAPWorldEvaluator.__module__.replace(".", "/") + ".py")
    text=Path(__file__).parents[2].joinpath(source).read_text(encoding="utf-8")
    assert "snapshot = copy(self._last)" in text
    assert "snapshot.rule_details = dict(self._last.rule_details)" in text
    assert "deepcopy(self._last)" not in text


def test_dependency_reverse_index_drops_stale_dependencies():
    """Handle test dependency reverse index drops stale dependencies."""
    from wayfinder.logic.dependency_graph import DependencyGraph
    graph=DependencyGraph()
    graph.add("location:X", {"item:Hookshot", "item:Bombs"})
    graph.add("location:X", {"item:Hookshot"})
    assert graph.affected({"item:Bombs"}) == set()
    assert graph.affected({"item:Hookshot"}) == {"location:X"}


def test_uncommon_zoom_is_persisted_asynchronously(tmp_path, monkeypatch):
    """Handle test uncommon zoom is persisted asynchronously."""
    root=tmp_path / "pack"
    _write_pack(root)
    monkeypatch.setattr(packs, "map_cache_root", lambda: tmp_path / "cache")
    image=Image.new("RGBA", (13, 9), "blue")
    assert packs.persist_zoom_image_async(root, "map0.png", 75, image)
    target=packs.cached_map_path(root, "map0.png", 75)
    deadline=time.time()+5
    while time.time() < deadline and not target.is_file():
        time.sleep(0.02)
    assert target.is_file()
    with Image.open(target) as opened:
        assert opened.size == (13, 9)


def test_marker_creation_is_chunked_in_production_source():
    """Handle test marker creation is chunked in production source."""
    text=combined_app_source()
    assert "start_index+100" in text
    assert "preparing markers {end_index}/{len(markers)}" in text
