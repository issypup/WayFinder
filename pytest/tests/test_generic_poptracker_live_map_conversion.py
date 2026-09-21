from pathlib import Path

from wayfinder.maps.converter import _poptracker_live_map_tracking


def test_generic_poptracker_live_map_tracking(tmp_path: Path):
    (tmp_path / "scripts" / "autotracking").mkdir(parents=True)
    (tmp_path / "maps").mkdir()
    (tmp_path / "locations").mkdir()
    (tmp_path / "manifest.json").write_text('{"game_name":"Example Game"}', encoding="utf-8")
    (tmp_path / "maps" / "maps.json").write_text(
        '[{"name":"AA","img":"images/maps/AlphaArea.png"},{"name":"BB","img":"images/maps/BetaZone.png"}]',
        encoding="utf-8",
    )
    (tmp_path / "locations" / "main.json").write_text(
        '[{"name":"Special Hall","children":[{"name":"Check","map_locations":[{"map":"BB","x":1,"y":1}]}]}]',
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "autotracking" / "archipelago.lua").write_text(
        '''TabMap = {\n  ["Alpha Area"] = "Alpha Area",\n  ["Special Hall"] = "Special Hall"\n}\n\nfunction update(value)\n  Tracker:UiHint("ActivateTab", TabMap[value] or value)\nend\n\nArchipelago:SetNotify({"ExampleZone_"..Archipelago.TeamNumber.."_"..Archipelago.PlayerNumber})\n''',
        encoding="utf-8",
    )
    warnings = []
    result = _poptracker_live_map_tracking(tmp_path, warnings)
    assert result["datastorage_key"] == "ExampleZone_{team}_{player}"
    assert result["value_to_map"]["Alpha Area"] == "AA"
    assert result["value_to_map"]["Special Hall"] == "BB"
    assert result["value_to_map"]["Beta Zone"] == "BB"
