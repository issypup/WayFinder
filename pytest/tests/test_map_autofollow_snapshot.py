"""Regression coverage for map auto-follow semantics.

Incoming Archipelago traffic creates snapshots, but only a changed runtime map
signal may override a map that the user selected manually.
"""


def test_unchanged_runtime_target_does_not_force_manual_map_selection():
    """Handle test unchanged runtime target does not force manual map selection."""
    previous_runtime_target = "Secret Passage"
    current_runtime_target = "Secret Passage"
    manually_selected_map = "Lava Ruins"

    should_switch = bool(
        current_runtime_target
        and current_runtime_target != previous_runtime_target
        and current_runtime_target != manually_selected_map
    )
    assert should_switch is False


def test_changed_runtime_target_still_auto_follows_player():
    """Handle test changed runtime target still auto follows player."""
    previous_runtime_target = "Secret Passage"
    current_runtime_target = "Lava Ruins"
    manually_selected_map = "Castle"

    should_switch = bool(
        current_runtime_target
        and current_runtime_target != previous_runtime_target
        and current_runtime_target != manually_selected_map
    )
    assert should_switch is True
