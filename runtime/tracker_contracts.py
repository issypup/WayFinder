"""Compatibility contracts exposed to tracker-aware APWorlds.

WayFinder does not import Universal Tracker at runtime, but some APWorlds inspect
tracker compatibility attributes on ``MultiWorld``.  Keep those contracts in
one place so their types and coupled Archipelago state cannot drift apart.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class DeferredEntranceMode(str, Enum):
    """String values used by tracker-aware APWorlds for deferred entrances."""

    FORCED = "on"
    DEFAULT = "default"
    DISABLED = "off"


def normalize_deferred_entrance_mode(value: DeferredEntranceMode | str) -> DeferredEntranceMode:
    """Return a validated deferred-entrance mode without accepting bool/int aliases."""
    if isinstance(value, DeferredEntranceMode):
        return value
    if not isinstance(value, str):
        raise TypeError(
            "deferred entrance mode must be a string enum value: 'on', 'default', or 'off'"
        )
    try:
        return DeferredEntranceMode(value)
    except ValueError as exc:
        raise ValueError(
            f"invalid deferred entrance mode {value!r}; expected 'on', 'default', or 'off'"
        ) from exc


def deferred_entrances_allow_partial(value: DeferredEntranceMode | str) -> bool:
    """Map the tracker mode to Archipelago CollectionState's boolean contract."""
    return normalize_deferred_entrance_mode(value) is not DeferredEntranceMode.DISABLED


def apply_deferred_entrance_contract(
    multiworld: Any,
    value: DeferredEntranceMode | str = DeferredEntranceMode.DISABLED,
) -> DeferredEntranceMode:
    """Expose the validated string contract on a MultiWorld and return its mode."""
    mode = normalize_deferred_entrance_mode(value)
    multiworld.enforce_deferred_connections = mode.value
    return mode
