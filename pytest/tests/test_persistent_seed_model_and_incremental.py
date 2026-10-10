
from types import SimpleNamespace
from pathlib import Path

from wayfinder.logic.dependency_graph import DependencyGraph
from wayfinder.runtime import seed_model_cache


def test_dependency_graph_round_trip():
    graph=DependencyGraph()
    graph.add("location:Tea Room",{"item:Water Element Medal"},unsafe=False)
    graph.add("entrance:2F Stairwell",{"item:Key"},unsafe=True)
    restored=DependencyGraph.from_dict(graph.to_dict())
    assert restored.affected({"item:Water Element Medal"}) == {"location:Tea Room"}
    assert restored.affected({"item:Key"}) == {"entrance:2F Stairwell"}
    assert not restored.is_safe_for({"entrance:2F Stairwell"})


def test_seed_model_cache_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(seed_model_cache,"cache_dir",lambda:tmp_path/"seed_models")
    model={"game":"Demo","regions":["A"],"locations":[{"id":1,"name":"Check","region":"A"}],"dependency_graph":{}}
    path=seed_model_cache.save("abc",model)
    assert Path(path).is_file()
    loaded=seed_model_cache.load("abc")
    assert loaded["game"]=="Demo"
    assert loaded["locations"][0]["name"]=="Check"
    assert seed_model_cache.load("other") is None


def test_seed_model_does_not_serialize_live_inventory(tmp_path, monkeypatch):
    class MW:
        def get_regions(self,p):
            region=SimpleNamespace(name="A",exits=[])
            return [region]
        def get_locations(self,p):
            return [SimpleNamespace(address=1,name="Check",parent_region=SimpleNamespace(name="A"))]
    built=SimpleNamespace(
        multiworld=MW(),player=1,game="Demo",slot_name="Player",
        logic_source="Player YAML",exact_logic=True,
    )
    model=seed_model_cache.from_built(
        built,
        {"rule_details":{},"entrance_details":[],"event_details":[],"inventory":[{"name":"Secret Item"}],"checked_locations":[1]},
        {},
    )
    text=str(model)
    assert "Secret Item" not in text
    assert "checked_locations" not in model
