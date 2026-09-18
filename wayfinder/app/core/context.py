"""Shared application context models.

These types are intentionally independent from Tk widgets so page and controller
modules can exchange run-scoped state without importing the monolithic app module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunContext:
    """Transient state owned by one Archipelago run identity."""

    server: str = ""
    team: int = 0
    slot: str = ""
    game: str = ""
    seed: str = ""
    current_area: str = ""
    current_map: str = ""
    selected_check: str = ""
    map_camera: tuple[float, float, int] | None = None
    route: Any = None
    hint_cache: dict = field(default_factory=dict)
    logic_generation: int = 0

    @property
    def identity(self):
        """Handle identity."""
        return (
            self.server.strip().casefold(),
            int(self.team or 0),
            self.slot.strip().casefold(),
            self.game.strip().casefold(),
        )
