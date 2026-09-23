# /**
#  * Module: wayfinder.runtime/__init__.py
#  * Purpose: Runtime module for   init  ; bridges loaded Archipelago worlds and live server state into tracker snapshots.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

"""WayFinder-owned Archipelago tracker runtime.

This package uses the
Archipelago core/network APIs and game APWorlds, while WayFinder owns world
reconstruction, state application, reachability, event sweeping and IPC.
"""

# Constant(s): `RUNTIME_VERSION`; shared configuration value(s) intentionally kept stable within this module.
from wayfinder.version import ENGINE_VERSION

RUNTIME_VERSION = ENGINE_VERSION