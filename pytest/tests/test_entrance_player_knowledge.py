from wayfinder.runtime import entrance_knowledge
from wayfinder.logic.progression_intelligence import build_progression_graph
from types import SimpleNamespace


def test_seed_scoped_entrance_knowledge_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(entrance_knowledge,"_root",lambda:tmp_path/"entrances")
    entrance_knowledge.set_destination("seed-a","Hall Door","Tea Room")
    assert entrance_knowledge.known_destination(entrance_knowledge.load("seed-a"),"Hall Door")==('Tea Room','player')
    assert entrance_knowledge.load("seed-b")=={}
    entrance_knowledge.forget("seed-a","Hall Door")
    assert entrance_knowledge.load("seed-a")=={}


def test_progression_graph_does_not_spoil_unknown_destination():
    snap=SimpleNamespace(
        locations=[], rule_details={}, event_details=[], events=[],
        current_reachable_regions=["Hall"], in_logic_regions=["Hall"],
        entrance_details=[{"name":"Door A","source_region":"Hall","target_region":"Tea Room","unknown_destination":True,"reachable":False}],
    )
    graph=build_progression_graph(snap)
    assert not any(edge.source=="entrance:Door A" and edge.target=="region:Tea Room" for edge in graph.edges)


def test_progression_graph_uses_player_known_destination():
    snap=SimpleNamespace(
        locations=[], rule_details={}, event_details=[], events=[],
        current_reachable_regions=["Hall","Tea Room"], in_logic_regions=["Hall","Tea Room"],
        entrance_details=[{"name":"Door A","source_region":"Hall","target_region":"Tea Room","unknown_destination":False,"knowledge_state":"player","reachable":True}],
    )
    graph=build_progression_graph(snap)
    assert any(edge.source=="entrance:Door A" and edge.target=="region:Tea Room" for edge in graph.edges)


def test_independent_entrance_controls_do_not_hide_vanilla_categories():
    from wayfinder.runtime.snapshot import _entrance_randomization_for_name
    class Opt:
        def __init__(self,value): self.value=value
    world=SimpleNamespace(options=SimpleNamespace(
        randomize_dungeon_entrances=Opt(1),
        randomize_boss_entrances=Opt(0),
        randomize_secret_cave_entrances=Opt(0),
    ))
    assert _entrance_randomization_for_name(world,"Dungeon Entrance on Dragon Roost Island") is True
    assert _entrance_randomization_for_name(world,"Boss Entrance in Dragon Roost Cavern") is False
    assert _entrance_randomization_for_name(world,"Secret Cave Entrance on Outset Island") is False
