"""Provide test goal backtracking 01419 support."""
from types import SimpleNamespace

from wayfinder.logic.solver_intelligence import goal_target


def test_goal_target_backtracks_missing_item_to_event_source():
    """Handle test goal target backtracks missing item to event source."""
    snapshot=SimpleNamespace(
        goal_detail={
            "missing":[{"kind":"item","name":"Victory","result":False}],
            "sources":[{"item":"Victory","location":"Defeat Final Boss","region":"Abyss","event":True}],
        },
        event_details=[],
        locations=[],
    )
    assert goal_target(snapshot)=="Defeat Final Boss"


def test_goal_target_uses_event_metadata_for_older_snapshot():
    """Handle test goal target uses event metadata for older snapshot."""
    snapshot=SimpleNamespace(
        goal_detail={"missing":[{"kind":"item","name":"Victory","result":False}]},
        event_details=[{"name":"Victory Event","event_item":"Victory","region":"Goal"}],
        locations=[],
    )
    assert goal_target(snapshot)=="Victory Event"


def test_goal_target_yaml_goal_option_is_fallback_only():
    """Handle test goal target yaml goal option is fallback only."""
    snapshot=SimpleNamespace(
        goal_detail={"missing":[],"goal_options":{"goal":"defeat_nobeta"}},
        event_details=[],
        locations=[SimpleNamespace(name="Abyss - Defeat Nobeta")],
    )
    assert goal_target(snapshot)=="Abyss - Defeat Nobeta"
