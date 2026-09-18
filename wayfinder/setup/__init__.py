"""WayFinder setup services.

This package replaces the former launcher module. WayFinder is now a single
user-facing application; these modules only provide internal setup services.
"""

from .archipelago_core import (
    APP_DATA_ROOT,
    AP_CORE_ROOT,
    AP_CORE_SOURCE,
    AP_SOURCE_ARCHIVE,
    AP_CORE_MANIFEST,
    PLAYERS_DIR,
    MAP_PACK_DIR,
    LOGS_DIR,
    DEPENDENCIES_DIR,
    DEPENDENCY_REPORT,
    load_settings,
    save_settings,
    is_archipelago,
    archipelago_candidates,
    find_archipelago,
    import_archipelago_core,
    imported_archipelago_version,
    github_latest_archipelago_release,
    core_ready,
    split_server_port,
    compose_server,
    DEFAULT_AP_PORT,
    _players_source,
    find_matching_player_yaml,
    sync_player_yamls,
    sync_custom_worlds,
)

from wayfinder.runtime.dependency_manager import dependency_report_ok, load_dependency_report

__all__ = [
    "APP_DATA_ROOT","AP_CORE_ROOT","AP_CORE_SOURCE","AP_SOURCE_ARCHIVE",
    "AP_CORE_MANIFEST","PLAYERS_DIR","MAP_PACK_DIR","LOGS_DIR",
    "DEPENDENCIES_DIR","DEPENDENCY_REPORT","load_settings","save_settings",
    "is_archipelago","archipelago_candidates","find_archipelago",
    "import_archipelago_core","imported_archipelago_version",
    "github_latest_archipelago_release","core_ready","split_server_port",
    "compose_server","DEFAULT_AP_PORT","_players_source",
    "find_matching_player_yaml","sync_player_yamls","sync_custom_worlds",
    "dependency_report_ok","load_dependency_report",
]
