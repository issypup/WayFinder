# WayFinder Project Structure & Dependency Guide

> Generated from the source tree for **WayFinder unknown** by `tools/generate_project_structure.py`.

# Purpose of this document

This is the maintainers’ map of the repository. The dependency information below is generated from Python AST imports, so absolute imports remain absolute, relative imports are resolved against their real package, and reverse importer lists come from the same dependency graph.

# High-level dependency direction

```text
run_wayfinder.py
      │
      ▼
wayfinder.app.app  (composition root)
  ├──► app.pages / app.ui / app.controllers / app.map
  ├──► connection / logic / maps / setup / storage
  └──► runtime transport/process orchestration

Lower-level packages (`connection`, `logic`, `maps`, `runtime`, `setup`, `storage`) must not import `wayfinder.app.*`.
`app.map` is below `app.pages.map_page`; it must not import `app.pages.*`.
Cross-domain lower-level dependencies such as runtime → connection/logic are allowed when explicitly required.
```

## Architectural safeguards

- ✅ No forbidden upward GUI dependencies detected.
- ⚠ Direct reciprocal import pairs: `wayfinder.utils` ⇄ `wayfinder.utils.error_handler`

# Folder map

```text
wayfinder/
├── app/
│   ├── controllers/
│   │   ├── __init__.py
│   │   ├── connection_controller.py
│   │   ├── map_controller.py
│   │   ├── setup_controller.py
│   │   └── snapshot_controller.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── context.py
│   │   └── source_layout.py
│   ├── map/
│   │   ├── __init__.py
│   │   ├── map_interactions.py
│   │   ├── map_markers.py
│   │   ├── map_navigation.py
│   │   ├── map_pack_manager.py
│   │   ├── map_popout.py
│   │   ├── map_rendering.py
│   │   ├── map_routes.py
│   │   └── map_shared.py
│   ├── pages/
│   │   ├── __init__.py
│   │   ├── checks_page.py
│   │   ├── dashboard.py
│   │   ├── diagnostics_page.py
│   │   ├── hints_page.py
│   │   ├── map_page.py
│   │   ├── path_page.py
│   │   └── setup_page.py
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── ap_inspector_ui.py
│   │   ├── appearance.py
│   │   ├── apworld_ui.py
│   │   ├── log_page.py
│   │   ├── logic_tools.py
│   │   ├── reliability_ui.py
│   │   ├── search_ui.py
│   │   ├── shell.py
│   │   └── tracker_panels.py
│   ├── __init__.py
│   └── app.py
├── connection/
│   ├── __init__.py
│   ├── ap_inspector.py
│   ├── identity.py
│   ├── memory.py
│   ├── protocol.py
│   └── runtime_client.py
├── logic/
│   ├── __init__.py
│   ├── apworld_adapter.py
│   ├── apworld_probe.py
│   ├── comparison.py
│   ├── dependency_graph.py
│   ├── engine.py
│   ├── incremental.py
│   ├── logic_api.py
│   ├── model.py
│   ├── native_pack.py
│   ├── progression_intelligence.py
│   ├── rule_explanation.py
│   ├── rules.py
│   └── solver_intelligence.py
├── maps/
│   ├── __init__.py
│   ├── assets.py
│   ├── converter.py
│   ├── intelligence.py
│   ├── interpretation.py
│   └── packs.py
├── runtime/
│   ├── __init__.py
│   ├── ap_protocol.py
│   ├── apworld_catalog.py
│   ├── apworld_compatibility.py
│   ├── bundled_wheels.py
│   ├── dependency_manager.py
│   ├── dependency_path.py
│   ├── dependency_progress.py
│   ├── native_reliability.py
│   ├── process_manager.py
│   ├── reliability.py
│   ├── server.py
│   ├── snapshot.py
│   ├── source_recipes.py
│   ├── wheel_installer.py
│   ├── world_builder.py
│   └── world_loader.py
├── setup/
│   ├── __init__.py
│   ├── archipelago_core.py
│   ├── dependencies.py
│   ├── player_yamls.py
│   └── worlds.py
├── utils/
│   ├── __init__.py
│   ├── decorators.py
│   ├── error_handler.py
│   └── ignored.py
├── __init__.py
├── diagnostics.py
├── storage.py
└── version.py
pytest/
├── .pytest_cache/
│   ├── v/
│   │   └── cache/
│   │       ├── lastfailed
│   │       └── nodeids
│   ├── .gitignore
│   ├── CACHEDIR.TAG
│   └── README.md
├── tests/
│   ├── test_alternate_marker_position_dedupe_01442.py
│   ├── test_ap_protocol_inspector_01454.py
│   ├── test_appearance_settings_atomic_write_01473.py
│   ├── test_apworld_catalog_01453.py
│   ├── test_apworld_current_map_fallback.py
│   ├── test_bundled_native_wheels.py
│   ├── test_compact_run_overview.py
│   ├── test_comparison_aware_prog_items.py
│   ├── test_complex_poptracker_maps_01434.py
│   ├── test_connection_preparation_01457.py
│   ├── test_cross_game_current_area_01459.py
│   ├── test_current_area_independent_map_browsing.py
│   ├── test_dashboard_action_frame_cleanup.py
│   ├── test_dashboard_blank_until_connect.py
│   ├── test_dashboard_connection_controls.py
│   ├── test_dashboard_context_ui_01465.py
│   ├── test_dashboard_status_cleanup.py
│   ├── test_dependency_diagnostics.py
│   ├── test_dependency_progress.py
│   ├── test_diagnostics_logging.py
│   ├── test_entrypoint_dispatch.py
│   ├── test_error_handler_utility_100.py
│   ├── test_exit_vanilla_assignment_01438.py
│   ├── test_first_launch_setup.py
│   ├── test_font_size_setting.py
│   ├── test_frlg_strength_and_checked_state_01443.py
│   ├── test_generic_nonprogression_map_status_01439.py
│   ├── test_generic_poptracker_live_map_conversion.py
│   ├── test_generic_untracked_map_status_01441.py
│   ├── test_goal_backtracking_01419.py
│   ├── test_grouped_marker_status_resolution_01436.py
│   ├── test_hint_subscription.py
│   ├── test_hints_logic_snapshot.py
│   ├── test_id_aware_seed_filter_01440.py
│   ├── test_ignored_persistence.py
│   ├── test_installed_maps_manager.py
│   ├── test_light_theme_row_highlights.py
│   ├── test_live_map_switch.py
│   ├── test_logic_api_incremental.py
│   ├── test_logic_engine_tab_removed_01423.py
│   ├── test_logic_explanations.py
│   ├── test_logic_map_hardening_01448.py
│   ├── test_logic_source_classification_01461.py
│   ├── test_manual_disconnect_delivery.py
│   ├── test_map_area_progress_palette.py
│   ├── test_map_autofollow_snapshot.py
│   ├── test_map_legend_controls_01474.py
│   ├── test_map_marker_collision_spread.py
│   ├── test_map_pack_auto_convert_install_01431.py
│   ├── test_map_performance.py
│   ├── test_map_popout_and_rendering.py
│   ├── test_map_reload_loop_01456.py
│   ├── test_map_responsiveness_01458.py
│   ├── test_name_emphasis_theme.py
│   ├── test_native_source_and_paths.py
│   ├── test_native_tracker.py
│   ├── test_negated_count_normalization_01421.py
│   ├── test_no_launcher_module.py
│   ├── test_pack_converter_tab.py
│   ├── test_performance_optimisation_01466.py
│   ├── test_player_position.py
│   ├── test_player_yaml_option_preservation_01446.py
│   ├── test_poptracker_entrance_boolean_status_01433.py
│   ├── test_poptracker_entrance_region_bridge_01430.py
│   ├── test_poptracker_entrance_semantics_01428.py
│   ├── test_poptracker_hosted_item_markers.py
│   ├── test_poptracker_variants_01427.py
│   ├── test_progression_graph_live_status_01422.py
│   ├── test_progression_intelligence.py
│   ├── test_project_layout.py
│   ├── test_project_structure_dependencies_01476.py
│   ├── test_pytest_output_detail.py
│   ├── test_pytest_runner_layout.py
│   ├── test_reliability_seed_intelligence.py
│   ├── test_requirements_file.py
│   ├── test_responsive_snapshot_pipeline_01447.py
│   ├── test_rift_rule_reconstruction_01432.py
│   ├── test_rule_graph_state_colors_01420.py
│   ├── test_rule_intelligence_01455.py
│   ├── test_runtime_child_command.py
│   ├── test_scrollable_tabs.py
│   ├── test_settings_annotation_compatibility.py
│   ├── test_setup_async_lifecycle_01462.py
│   ├── test_setup_aware_startup.py
│   ├── test_shared_tracker_interpretation_01437.py
│   ├── test_single_app_setup.py
│   ├── test_sleeping_host_connection_handling.py
│   ├── test_solver_intelligence_01411.py
│   ├── test_storage_location_01472.py
│   ├── test_unified_package_layout.py
│   ├── test_unified_typography.py
│   ├── test_user_initiated_connect_persistence.py
│   ├── test_wheel_installer.py
│   ├── test_world_preparation_ui_01464.py
│   └── test_zoom_floor_01475.py
├── conftest.py
└── pytest.ini
tools/
└── generate_project_structure.py
run_wayfinder.py
run_pytests.py
requirements.txt
BUILD-SINGLE-EXE.bat
PROJECT_STRUCTURE.md
```

# Root package services

### `wayfinder/storage.py`
# Central WayFinder application-data storage configuration.
- **Module:** `wayfinder.storage`
- **Exports:** `APP_DATA_ROOT`, `BOOTSTRAP_SETTINGS_PATH`, `STORAGE_KEY`, `app_data_root`, `configured_app_data_root`, `default_app_data_root`, `load_bootstrap_settings`, `save_bootstrap_settings`, `set_app_data_root`, `validate_app_data_root`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `json`, `os`, `pathlib`, `tempfile`
- **Import-time importers:** `wayfinder.app.app`, `wayfinder.app.controllers.connection_controller`, `wayfinder.app.controllers.map_controller`, `wayfinder.app.controllers.setup_controller`, `wayfinder.app.controllers.snapshot_controller`, `wayfinder.app.map.map_pack_manager`, `wayfinder.app.map.map_shared`, `wayfinder.app.pages.checks_page`, `wayfinder.app.pages.dashboard`, `wayfinder.app.pages.diagnostics_page`, `wayfinder.app.pages.hints_page`, `wayfinder.app.pages.path_page`, `wayfinder.app.pages.setup_page`, `wayfinder.app.ui.appearance`, `wayfinder.app.ui.log_page`, `wayfinder.app.ui.logic_tools`, `wayfinder.app.ui.search_ui`, `wayfinder.app.ui.shell`, `wayfinder.app.ui.tracker_panels`, `wayfinder.connection.memory`, `wayfinder.maps.packs`, `wayfinder.runtime.server`, `wayfinder.setup.archipelago_core`
- **Lazy/local importers:** `wayfinder.app.ui.reliability_ui`, `wayfinder.runtime.world_builder`
- **Dependency direction:** One-way at import-time level.

# `wayfinder/app/` — Application composition and GUI packages

### `wayfinder/app/__init__.py`
# WayFinder Tkinter application package.
- **Module:** `wayfinder.app`
- **Exports:** `WayFinderApp`
- **Import-time internal imports:** `wayfinder.app.app`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/app/app.py`
# Tkinter front end for the WayFinder native tracker interface.
- **Module:** `wayfinder.app.app`
- **Exports:** `APP_DATA_ROOT`, `GUI_VERSION`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `ToolTip`, `WayFinderApp`
- **Import-time internal imports:** `wayfinder`, `wayfinder.app.controllers.connection_controller`, `wayfinder.app.controllers.map_controller`, `wayfinder.app.controllers.setup_controller`, `wayfinder.app.controllers.snapshot_controller`, `wayfinder.app.core.context`, `wayfinder.app.map.map_pack_manager`, `wayfinder.app.pages.checks_page`, `wayfinder.app.pages.dashboard`, `wayfinder.app.pages.diagnostics_page`, `wayfinder.app.pages.hints_page`, `wayfinder.app.pages.map_page`, `wayfinder.app.pages.path_page`, `wayfinder.app.pages.setup_page`, `wayfinder.app.ui.appearance`, `wayfinder.app.ui.log_page`, `wayfinder.app.ui.logic_tools`, `wayfinder.app.ui.reliability_ui`, `wayfinder.app.ui.search_ui`, `wayfinder.app.ui.shell`, `wayfinder.app.ui.tracker_panels`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.error_handler`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `PIL`, `base64`, `ctypes`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app`
- **Lazy/local importers:** `wayfinder.app.controllers.connection_controller`, `wayfinder.app.controllers.map_controller`, `wayfinder.app.controllers.setup_controller`, `wayfinder.app.controllers.snapshot_controller`, `wayfinder.app.map.map_shared`, `wayfinder.app.pages.checks_page`, `wayfinder.app.pages.dashboard`, `wayfinder.app.pages.diagnostics_page`, `wayfinder.app.pages.hints_page`, `wayfinder.app.pages.path_page`, `wayfinder.app.pages.setup_page`
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

## `wayfinder/app/core/` — Shared GUI contracts and developer support.

### `wayfinder/app/core/__init__.py`
# Shared GUI context and source-layout support used across app packages.
- **Module:** `wayfinder.app.core`
- **Exports:** _No declared public definitions/constants detected._
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/core/context.py`
# Shared application context models.
- **Module:** `wayfinder.app.core.context`
- **Exports:** `RunContext`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `dataclasses`, `typing`
- **Import-time importers:** `wayfinder.app.app`, `wayfinder.app.controllers.connection_controller`, `wayfinder.app.controllers.map_controller`, `wayfinder.app.controllers.setup_controller`, `wayfinder.app.controllers.snapshot_controller`, `wayfinder.app.map.map_shared`, `wayfinder.app.pages.checks_page`, `wayfinder.app.pages.dashboard`, `wayfinder.app.pages.diagnostics_page`, `wayfinder.app.pages.hints_page`, `wayfinder.app.pages.path_page`, `wayfinder.app.pages.setup_page`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/core/source_layout.py`
# Developer helpers for locating GUI source after the app.py decomposition.
- **Module:** `wayfinder.app.core.source_layout`
- **Exports:** `combined_app_source`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `pathlib`
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

## `wayfinder/app/controllers/` — GUI orchestration and lifecycle controllers.

### `wayfinder/app/controllers/__init__.py`
# Controller mixins for WayFinder GUI orchestration.
- **Module:** `wayfinder.app.controllers`
- **Exports:** _No declared public definitions/constants detected._
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/controllers/connection_controller.py`
# Provide connection controller support.
- **Module:** `wayfinder.app.controllers.connection_controller`
- **Exports:** `APP_DATA_ROOT`, `ConnectionControllerMixin`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `ToolTip`
- **Import-time internal imports:** `wayfinder.app.core.context`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.error_handler`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.app.app`
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import time; lazy/runtime back-reference(s) to `wayfinder.app.app`. This is runtime coupling, not an import-time cycle.

### `wayfinder/app/controllers/map_controller.py`
# Provide map controller support.
- **Module:** `wayfinder.app.controllers.map_controller`
- **Exports:** `APP_DATA_ROOT`, `MapControllerMixin`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`
- **Import-time internal imports:** `wayfinder.app.core.context`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.app.app`
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `types`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import time; lazy/runtime back-reference(s) to `wayfinder.app.app`. This is runtime coupling, not an import-time cycle.

### `wayfinder/app/controllers/setup_controller.py`
# Provide setup controller support.
- **Module:** `wayfinder.app.controllers.setup_controller`
- **Exports:** `APP_DATA_ROOT`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `SetupControllerMixin`
- **Import-time internal imports:** `wayfinder.app.core.context`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.error_handler`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.app.app`, `wayfinder.runtime.apworld_catalog`, `wayfinder.runtime.dependency_manager`, `wayfinder.runtime.dependency_progress`, `wayfinder.runtime.process_manager`
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`, `webbrowser`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import time; lazy/runtime back-reference(s) to `wayfinder.app.app`. This is runtime coupling, not an import-time cycle.

### `wayfinder/app/controllers/snapshot_controller.py`
# Provide snapshot controller support.
- **Module:** `wayfinder.app.controllers.snapshot_controller`
- **Exports:** `APP_DATA_ROOT`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `SnapshotControllerMixin`, `ToolTip`
- **Import-time internal imports:** `wayfinder.app.core.context`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.error_handler`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.app.app`
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `traceback`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import time; lazy/runtime back-reference(s) to `wayfinder.app.app`. This is runtime coupling, not an import-time cycle.

## `wayfinder/app/pages/` — Top-level navigation pages.

### `wayfinder/app/pages/__init__.py`
# WayFinder top-level GUI page mixins.
- **Module:** `wayfinder.app.pages`
- **Exports:** _No declared public definitions/constants detected._
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/pages/checks_page.py`
# Provide checks page support.
- **Module:** `wayfinder.app.pages.checks_page`
- **Exports:** `APP_DATA_ROOT`, `ChecksPageMixin`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `ToolTip`
- **Import-time internal imports:** `wayfinder.app.core.context`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.error_handler`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.app.app`
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import time; lazy/runtime back-reference(s) to `wayfinder.app.app`. This is runtime coupling, not an import-time cycle.

### `wayfinder/app/pages/dashboard.py`
# Provide dashboard support.
- **Module:** `wayfinder.app.pages.dashboard`
- **Exports:** `APP_DATA_ROOT`, `DashboardPageMixin`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `ToolTip`
- **Import-time internal imports:** `wayfinder.app.core.context`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.app.app`
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import time; lazy/runtime back-reference(s) to `wayfinder.app.app`. This is runtime coupling, not an import-time cycle.

### `wayfinder/app/pages/diagnostics_page.py`
# Provide diagnostics page support.
- **Module:** `wayfinder.app.pages.diagnostics_page`
- **Exports:** `APP_DATA_ROOT`, `DiagnosticsPageMixin`, `GUI_VERSION`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `ToolTip`
- **Import-time internal imports:** `wayfinder`, `wayfinder.app.core.context`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.app.app`
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import time; lazy/runtime back-reference(s) to `wayfinder.app.app`. This is runtime coupling, not an import-time cycle.

### `wayfinder/app/pages/hints_page.py`
# Provide hints page support.
- **Module:** `wayfinder.app.pages.hints_page`
- **Exports:** `APP_DATA_ROOT`, `HintsPageMixin`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `ToolTip`
- **Import-time internal imports:** `wayfinder.app.core.context`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.app.app`
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import time; lazy/runtime back-reference(s) to `wayfinder.app.app`. This is runtime coupling, not an import-time cycle.

### `wayfinder/app/pages/map_page.py`
# Provide map page support.
- **Module:** `wayfinder.app.pages.map_page`
- **Exports:** `MapPageMixin`
- **Import-time internal imports:** `wayfinder.app.map.map_interactions`, `wayfinder.app.map.map_markers`, `wayfinder.app.map.map_navigation`, `wayfinder.app.map.map_popout`, `wayfinder.app.map.map_rendering`, `wayfinder.app.map.map_routes`, `wayfinder.app.map.map_shared`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/pages/path_page.py`
# Provide path page support.
- **Module:** `wayfinder.app.pages.path_page`
- **Exports:** `APP_DATA_ROOT`, `GUI_VERSION`, `PathPageMixin`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `ToolTip`
- **Import-time internal imports:** `wayfinder`, `wayfinder.app.core.context`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.error_handler`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.app.app`
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import time; lazy/runtime back-reference(s) to `wayfinder.app.app`. This is runtime coupling, not an import-time cycle.

### `wayfinder/app/pages/setup_page.py`
# Provide setup page support.
- **Module:** `wayfinder.app.pages.setup_page`
- **Exports:** `APP_DATA_ROOT`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `SetupPageMixin`, `ToolTip`
- **Import-time internal imports:** `wayfinder.app.core.context`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.error_handler`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.app.app`, `wayfinder.runtime.snapshot`
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import time; lazy/runtime back-reference(s) to `wayfinder.app.app`. This is runtime coupling, not an import-time cycle.

## `wayfinder/app/ui/` — Reusable Tk shell, styles, panels, and dialogs.

### `wayfinder/app/ui/__init__.py`
# Reusable WayFinder GUI shell, styling, panels, and dialogs.
- **Module:** `wayfinder.app.ui`
- **Exports:** _No declared public definitions/constants detected._
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/ui/ap_inspector_ui.py`
# Connection inspector with packet evidence and paged value browsers.
- **Module:** `wayfinder.app.ui.ap_inspector_ui`
- **Exports:** `APInspectorUI`
- **Import-time internal imports:** `wayfinder.connection.ap_inspector`, `wayfinder.diagnostics`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `json`, `time`, `tkinter`
- **Import-time importers:** `wayfinder.app.ui.apworld_ui`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/ui/appearance.py`
# Provide appearance support.
- **Module:** `wayfinder.app.ui.appearance`
- **Exports:** `APP_DATA_ROOT`, `AppearanceMixin`, `FONT_FAMILY`, `FONT_FAMILY_MONO`, `FONT_FAMILY_SEMIBOLD`, `FONT_SIZE_DEFAULT`, `FONT_SIZE_MAX`, `FONT_SIZE_MIN`, `GUI_VERSION`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `TK_STANDARD_FONTS`, `ToolTip`, `apply_named_fonts`, `clamp_font_size`, `font_specs`
- **Import-time internal imports:** `wayfinder`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/ui/apworld_ui.py`
# Provide apworld ui support.
- **Module:** `wayfinder.app.ui.apworld_ui`
- **Exports:** `APWorldUI`
- **Import-time internal imports:** `wayfinder`, `wayfinder.app.ui.ap_inspector_ui`, `wayfinder.diagnostics`, `wayfinder.runtime.apworld_catalog`, `wayfinder.runtime.apworld_compatibility`, `wayfinder.setup`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `json`, `pathlib`, `queue`, `threading`, `tkinter`
- **Import-time importers:** `wayfinder.app.ui.reliability_ui`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/ui/log_page.py`
# Provide log page support.
- **Module:** `wayfinder.app.ui.log_page`
- **Exports:** `APP_DATA_ROOT`, `GUI_VERSION`, `LogPageMixin`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `ToolTip`
- **Import-time internal imports:** `wayfinder`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/ui/logic_tools.py`
# Provide logic tools support.
- **Module:** `wayfinder.app.ui.logic_tools`
- **Exports:** `APP_DATA_ROOT`, `GUI_VERSION`, `LogicToolsMixin`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `ToolTip`
- **Import-time internal imports:** `wayfinder`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.error_handler`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.logic.rule_explanation`
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/ui/reliability_ui.py`
# Seed and component-health UI, and supervised runtime recovery.
- **Module:** `wayfinder.app.ui.reliability_ui`
- **Exports:** `ReliabilityUI`
- **Import-time internal imports:** `wayfinder.app.ui.apworld_ui`, `wayfinder.connection.identity`, `wayfinder.diagnostics`, `wayfinder.maps.intelligence`, `wayfinder.runtime.reliability`
- **Lazy/local internal imports:** `wayfinder.runtime.process_manager`, `wayfinder.storage`
- **External / standard-library imports:** `json`, `pathlib`, `time`, `tkinter`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/ui/search_ui.py`
# Provide search ui support.
- **Module:** `wayfinder.app.ui.search_ui`
- **Exports:** `APP_DATA_ROOT`, `GUI_VERSION`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `SearchUiMixin`, `ToolTip`
- **Import-time internal imports:** `wayfinder`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/ui/shell.py`
# Provide shell support.
- **Module:** `wayfinder.app.ui.shell`
- **Exports:** `APP_DATA_ROOT`, `GUI_VERSION`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `ShellMixin`, `ToolTip`
- **Import-time internal imports:** `wayfinder`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/ui/tracker_panels.py`
# Provide tracker panels support.
- **Module:** `wayfinder.app.ui.tracker_panels`
- **Exports:** `APP_DATA_ROOT`, `GUI_VERSION`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `ToolTip`, `TrackerPanelsMixin`
- **Import-time internal imports:** `wayfinder`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.error_handler`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

## `wayfinder/app/map/` — Map presentation, rendering, marker, navigation, and interaction subsystem.

### `wayfinder/app/map/__init__.py`
# WayFinder map presentation, navigation, rendering, and pack-management UI.
- **Module:** `wayfinder.app.map`
- **Exports:** _No declared public definitions/constants detected._
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/map/map_interactions.py`
# Provide map interactions support.
- **Module:** `wayfinder.app.map.map_interactions`
- **Exports:** `MapInteractionsMixin`
- **Import-time internal imports:** `wayfinder.app.map.map_shared`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** `wayfinder.app.pages.map_page`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/map/map_markers.py`
# Provide map markers support.
- **Module:** `wayfinder.app.map.map_markers`
- **Exports:** `MapMarkersMixin`
- **Import-time internal imports:** `wayfinder.app.map.map_shared`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `math`
- **Import-time importers:** `wayfinder.app.pages.map_page`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/map/map_navigation.py`
# Provide map navigation support.
- **Module:** `wayfinder.app.map.map_navigation`
- **Exports:** `MapNavigationMixin`
- **Import-time internal imports:** `wayfinder.app.map.map_shared`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `PIL`
- **Import-time importers:** `wayfinder.app.pages.map_page`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/map/map_pack_manager.py`
# Provide map pack manager support.
- **Module:** `wayfinder.app.map.map_pack_manager`
- **Exports:** `APP_DATA_ROOT`, `GUI_VERSION`, `MapPackManagerMixin`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `ToolTip`
- **Import-time internal imports:** `wayfinder`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.error_handler`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app.app`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/map/map_popout.py`
# Provide map popout support.
- **Module:** `wayfinder.app.map.map_popout`
- **Exports:** `MapPopoutMixin`
- **Import-time internal imports:** `wayfinder.app.map.map_shared`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** `wayfinder.app.pages.map_page`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/map/map_rendering.py`
# Provide map rendering support.
- **Module:** `wayfinder.app.map.map_rendering`
- **Exports:** `MapRenderingMixin`
- **Import-time internal imports:** `wayfinder.app.map.map_shared`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** `wayfinder.app.pages.map_page`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/map/map_routes.py`
# Provide map routes support.
- **Module:** `wayfinder.app.map.map_routes`
- **Exports:** `MapRoutesMixin`
- **Import-time internal imports:** `wayfinder.app.map.map_shared`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** `wayfinder.app.pages.map_page`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

### `wayfinder/app/map/map_shared.py`
# Provide map shared support.
- **Module:** `wayfinder.app.map.map_shared`
- **Exports:** `APP_DATA_ROOT`, `SETTINGS_PATH`, `STATE_PATH`, `STATUS_VISUALS`, `ToolTip`
- **Import-time internal imports:** `wayfinder.app.core.context`, `wayfinder.connection.identity`, `wayfinder.connection.memory`, `wayfinder.connection.runtime_client`, `wayfinder.diagnostics`, `wayfinder.logic.progression_intelligence`, `wayfinder.logic.solver_intelligence`, `wayfinder.maps.assets`, `wayfinder.maps.converter`, `wayfinder.maps.intelligence`, `wayfinder.maps.packs`, `wayfinder.setup`, `wayfinder.storage`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.app.app`
- **External / standard-library imports:** `PIL`, `base64`, `dataclasses`, `datetime`, `difflib`, `hashlib`, `io`, `json`, `os`, `pathlib`, `queue`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `tkinter`, `typing`
- **Import-time importers:** `wayfinder.app.map.map_interactions`, `wayfinder.app.map.map_markers`, `wayfinder.app.map.map_navigation`, `wayfinder.app.map.map_popout`, `wayfinder.app.map.map_rendering`, `wayfinder.app.map.map_routes`, `wayfinder.app.pages.map_page`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`.

# `wayfinder/connection/` — Connection subsystem

### `wayfinder/connection/__init__.py`
# WayFinder runtime transport and connection-state helpers.
- **Module:** `wayfinder.connection`
- **Exports:** _No declared public definitions/constants detected._
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/connection/ap_inspector.py`
# Bounded, redacted AP packet evidence, independent of reconstructed logic.
- **Module:** `wayfinder.connection.ap_inspector`
- **Exports:** `APInspector`, `PACKETS`, `browse`, `preview`
- **Import-time internal imports:** `wayfinder.diagnostics`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `collections`, `itertools`, `json`, `time`, `uuid`
- **Import-time importers:** `wayfinder.app.ui.ap_inspector_ui`, `wayfinder.runtime.ap_protocol`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/connection/identity.py`
# Seed-scoped identity and snapshot validation shared by runtime and GUI.
- **Module:** `wayfinder.connection.identity`
- **Exports:** `IDENTITY_FIELDS`, `SnapshotGate`, `fingerprint`, `normal_server`, `seed_identity`, `validate_identity`, `validate_snapshot`, `world_version`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `functools`, `hashlib`, `json`, `pathlib`, `sys`, `urllib`
- **Import-time importers:** `wayfinder.app.app`, `wayfinder.app.controllers.connection_controller`, `wayfinder.app.controllers.map_controller`, `wayfinder.app.controllers.setup_controller`, `wayfinder.app.controllers.snapshot_controller`, `wayfinder.app.map.map_pack_manager`, `wayfinder.app.map.map_shared`, `wayfinder.app.pages.checks_page`, `wayfinder.app.pages.dashboard`, `wayfinder.app.pages.diagnostics_page`, `wayfinder.app.pages.hints_page`, `wayfinder.app.pages.path_page`, `wayfinder.app.pages.setup_page`, `wayfinder.app.ui.appearance`, `wayfinder.app.ui.log_page`, `wayfinder.app.ui.logic_tools`, `wayfinder.app.ui.reliability_ui`, `wayfinder.app.ui.search_ui`, `wayfinder.app.ui.shell`, `wayfinder.app.ui.tracker_panels`, `wayfinder.connection.runtime_client`, `wayfinder.runtime.native_reliability`
- **Lazy/local importers:** `wayfinder.runtime.apworld_compatibility`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/connection/memory.py`
# Provide memory support.
- **Module:** `wayfinder.connection.memory`
- **Exports:** `START_CAVEATS`, `START_DIAGNOSTICS`, `START_KEYS`, `UNRESOLVED`, `clear_server_slot`, `find_option_attribute`, `get_record`, `identity_key`, `load_all`, `memory_path`, `normalize_server`, `remember_start`, `resolved_start`, `save_all`, `start_keys_for_game`, `start_resolution_diagnostic`
- **Import-time internal imports:** `wayfinder.storage`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `json`, `os`, `pathlib`, `re`, `shutil`, `typing`
- **Import-time importers:** `wayfinder.app.app`, `wayfinder.app.controllers.connection_controller`, `wayfinder.app.controllers.map_controller`, `wayfinder.app.controllers.setup_controller`, `wayfinder.app.controllers.snapshot_controller`, `wayfinder.app.map.map_pack_manager`, `wayfinder.app.map.map_shared`, `wayfinder.app.pages.checks_page`, `wayfinder.app.pages.dashboard`, `wayfinder.app.pages.diagnostics_page`, `wayfinder.app.pages.hints_page`, `wayfinder.app.pages.path_page`, `wayfinder.app.pages.setup_page`, `wayfinder.app.ui.appearance`, `wayfinder.app.ui.log_page`, `wayfinder.app.ui.logic_tools`, `wayfinder.app.ui.search_ui`, `wayfinder.app.ui.shell`, `wayfinder.app.ui.tracker_panels`, `wayfinder.setup.archipelago_core`
- **Lazy/local importers:** `wayfinder.runtime.snapshot`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/connection/protocol.py`
# Shared WayFinder IPC protocol model (GUI and injected runtime).
- **Module:** `wayfinder.connection.protocol`
- **Exports:** `CAPABILITIES`, `ERROR_CODES`, `LEGACY_PROTOCOLS`, `MAX_MESSAGE_BYTES`, `PROTOCOL_MAX`, `PROTOCOL_MIN`, `PROTOCOL_VERSION`, `SNAPSHOT_COMPRESS_THRESHOLD`, `decode_snapshot`, `encode_snapshot`, `error_payload`, `request_id`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `base64`, `json`, `time`, `zlib`
- **Import-time importers:** `wayfinder.connection.runtime_client`, `wayfinder.runtime.native_reliability`, `wayfinder.runtime.server`
- **Lazy/local importers:** `wayfinder.runtime.apworld_compatibility`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/connection/runtime_client.py`
# Socket transport used by the standalone visual GUI.
- **Module:** `wayfinder.connection.runtime_client`
- **Exports:** `HEARTBEAT_INTERVAL`, `HEARTBEAT_TIMEOUT`, `InventoryEntry`, `LocationEntry`, `PathResult`, `PathStep`, `RuleNode`, `Snapshot`, `WayFinderRuntimeClient`
- **Import-time internal imports:** `wayfinder.connection.identity`, `wayfinder.connection.protocol`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `dataclasses`, `json`, `os`, `socket`, `threading`, `time`, `typing`, `uuid`
- **Import-time importers:** `wayfinder.app.app`, `wayfinder.app.controllers.connection_controller`, `wayfinder.app.controllers.map_controller`, `wayfinder.app.controllers.setup_controller`, `wayfinder.app.controllers.snapshot_controller`, `wayfinder.app.map.map_pack_manager`, `wayfinder.app.map.map_shared`, `wayfinder.app.pages.checks_page`, `wayfinder.app.pages.dashboard`, `wayfinder.app.pages.diagnostics_page`, `wayfinder.app.pages.hints_page`, `wayfinder.app.pages.path_page`, `wayfinder.app.pages.setup_page`, `wayfinder.app.ui.appearance`, `wayfinder.app.ui.log_page`, `wayfinder.app.ui.logic_tools`, `wayfinder.app.ui.search_ui`, `wayfinder.app.ui.shell`, `wayfinder.app.ui.tracker_panels`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

# `wayfinder/logic/` — Logic subsystem

### `wayfinder/logic/__init__.py`
# WayFinder native tracker and logic engine.
- **Module:** `wayfinder.logic`
- **Exports:** `DependencyGraph`, `EngineSnapshot`, `EntranceDefinition`, `EntranceState`, `EventDefinition`, `GoalState`, `IncrementalAPWorldEvaluator`, `LocationDefinition`, `LocationResult`, `LocationState`, `LogicComparisonReport`, `LogicDifference`, `LogicEngine`, `LogicSnapshot`, `RecalculationStats`, `RegionDefinition`, `Rule`, `RuleResult`, `TrackerDefinition`, `TrackerInput`, `WAYFINDER_LOGIC_API`, `all_of`, `always`, `any_of`, `compare_engines`, `compare_snapshots`, `event`, `item`, `never`, `not_`, `option`, `state_value`
- **Import-time internal imports:** `wayfinder.logic.apworld_adapter`, `wayfinder.logic.comparison`, `wayfinder.logic.dependency_graph`, `wayfinder.logic.engine`, `wayfinder.logic.incremental`, `wayfinder.logic.logic_api`, `wayfinder.logic.model`, `wayfinder.logic.rules`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/logic/apworld_adapter.py`
# Provide apworld adapter support.
- **Module:** `wayfinder.logic.apworld_adapter`
- **Exports:** `APAdapterSnapshot`, `NativeAPState`, `UnsupportedStateOperation`, `evaluate_generated_world`, `trace_access_rule`
- **Import-time internal imports:** `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.diagnostics`, `wayfinder.logic.rule_explanation`
- **External / standard-library imports:** `BaseClasses`, `collections`, `dataclasses`, `functools`, `heapq`, `inspect`, `itertools`, `os`, `sys`, `traceback`, `typing`
- **Import-time importers:** `wayfinder.logic`, `wayfinder.logic.incremental`, `wayfinder.runtime.snapshot`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/logic/apworld_probe.py`
# Safe, non-importing APWorld reconnaissance for native-adapter development.
- **Module:** `wayfinder.logic.apworld_probe`
- **Exports:** `APWorldProbe`, `inspect_apworld`
- **Import-time internal imports:** `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `ast`, `dataclasses`, `json`, `pathlib`, `zipfile`
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/logic/comparison.py`
# Provide comparison support.
- **Module:** `wayfinder.logic.comparison`
- **Exports:** `LogicComparisonReport`, `LogicDifference`, `compare_engines`, `compare_snapshots`
- **Import-time internal imports:** `wayfinder.logic.logic_api`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `dataclasses`, `typing`
- **Import-time importers:** `wayfinder.logic`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/logic/dependency_graph.py`
# Provide dependency graph support.
- **Module:** `wayfinder.logic.dependency_graph`
- **Exports:** `DependencyGraph`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `dataclasses`, `typing`
- **Import-time importers:** `wayfinder.logic`, `wayfinder.logic.incremental`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/logic/engine.py`
# Provide engine support.
- **Module:** `wayfinder.logic.engine`
- **Exports:** `LogicEngine`
- **Import-time internal imports:** `wayfinder.logic.logic_api`, `wayfinder.logic.model`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `collections`, `dataclasses`, `typing`
- **Import-time importers:** `wayfinder.logic`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/logic/incremental.py`
# Provide incremental support.
- **Module:** `wayfinder.logic.incremental`
- **Exports:** `IncrementalAPWorldEvaluator`, `IncrementalResult`
- **Import-time internal imports:** `wayfinder.logic.apworld_adapter`, `wayfinder.logic.dependency_graph`, `wayfinder.logic.logic_api`
- **Lazy/local internal imports:** `wayfinder.logic.rule_explanation`
- **External / standard-library imports:** `collections`, `copy`, `dataclasses`, `typing`
- **Import-time importers:** `wayfinder.logic`, `wayfinder.runtime.snapshot`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/logic/logic_api.py`
# Provide logic api support.
- **Module:** `wayfinder.logic.logic_api`
- **Exports:** `EntranceState`, `GoalState`, `LocationState`, `LogicSnapshot`, `RecalculationStats`, `WAYFINDER_LOGIC_API`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `dataclasses`, `typing`
- **Import-time importers:** `wayfinder.logic`, `wayfinder.logic.comparison`, `wayfinder.logic.engine`, `wayfinder.logic.incremental`, `wayfinder.runtime.snapshot`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/logic/model.py`
# Provide model support.
- **Module:** `wayfinder.logic.model`
- **Exports:** `EngineSnapshot`, `EntranceDefinition`, `EventDefinition`, `LocationDefinition`, `LocationResult`, `RegionDefinition`, `TrackerDefinition`, `TrackerInput`
- **Import-time internal imports:** `wayfinder.logic.rules`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `collections`, `dataclasses`, `typing`
- **Import-time importers:** `wayfinder.logic`, `wayfinder.logic.engine`, `wayfinder.logic.native_pack`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/logic/native_pack.py`
# Loader for the first WayFinder-native tracker definition format.
- **Module:** `wayfinder.logic.native_pack`
- **Exports:** `load_definition`, `parse_rule`
- **Import-time internal imports:** `wayfinder.logic.model`, `wayfinder.logic.rules`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `json`, `pathlib`, `typing`
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/logic/progression_intelligence.py`
# Shared progression intelligence for WayFinder GUI features.
- **Module:** `wayfinder.logic.progression_intelligence`
- **Exports:** `GraphEdge`, `GraphNode`, `ProgressionGraphModel`, `UnlockImpact`, `WaitingAnalysis`, `build_progression_graph`, `detect_unlock_impact`, `route_score`, `waiting_analysis`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `dataclasses`, `typing`
- **Import-time importers:** `wayfinder.app.app`, `wayfinder.app.controllers.connection_controller`, `wayfinder.app.controllers.map_controller`, `wayfinder.app.controllers.setup_controller`, `wayfinder.app.controllers.snapshot_controller`, `wayfinder.app.map.map_pack_manager`, `wayfinder.app.map.map_shared`, `wayfinder.app.pages.checks_page`, `wayfinder.app.pages.dashboard`, `wayfinder.app.pages.diagnostics_page`, `wayfinder.app.pages.hints_page`, `wayfinder.app.pages.path_page`, `wayfinder.app.pages.setup_page`, `wayfinder.app.ui.appearance`, `wayfinder.app.ui.log_page`, `wayfinder.app.ui.logic_tools`, `wayfinder.app.ui.search_ui`, `wayfinder.app.ui.shell`, `wayfinder.app.ui.tracker_panels`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/logic/rule_explanation.py`
# Bounded, non-executing explanations of APWorld Python rules.
- **Module:** `wayfinder.logic.rule_explanation`
- **Exports:** `Analyzer`, `annotate_events`, `compare`, `display_tree`, `explain`, `explanation_lines`, `impossible`, `negate`, `uncertain_regions`, `walk`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** `wayfinder.diagnostics`
- **External / standard-library imports:** `ast`, `functools`, `inspect`, `textwrap`, `zipfile`
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** `wayfinder.app.ui.logic_tools`, `wayfinder.logic.apworld_adapter`, `wayfinder.logic.incremental`, `wayfinder.runtime.server`, `wayfinder.runtime.snapshot`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/logic/rules.py`
# Provide rules support.
- **Module:** `wayfinder.logic.rules`
- **Exports:** `AllRule`, `AnyRule`, `ConstantRule`, `EventRule`, `ItemRule`, `NotRule`, `Rule`, `RuleContext`, `RuleResult`, `ValueRule`, `all_of`, `always`, `any_of`, `event`, `item`, `never`, `not_`, `option`, `state_value`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `dataclasses`, `typing`
- **Import-time importers:** `wayfinder.logic`, `wayfinder.logic.model`, `wayfinder.logic.native_pack`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/logic/solver_intelligence.py`
# Higher-level analysis helpers for WayFinder's Path Explorer.
- **Module:** `wayfinder.logic.solver_intelligence`
- **Exports:** `NORMAL_KINDS`, `branch_cost`, `dead_route_reasons`, `goal_target`, `normalized_kind`, `path_cycles`, `provenance_rows`, `rank_or_branches`, `reconstruction_audit`, `remote_dependency_lines`, `searchable_entries`, `walk_rules`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `dataclasses`, `typing`
- **Import-time importers:** `wayfinder.app.app`, `wayfinder.app.controllers.connection_controller`, `wayfinder.app.controllers.map_controller`, `wayfinder.app.controllers.setup_controller`, `wayfinder.app.controllers.snapshot_controller`, `wayfinder.app.map.map_pack_manager`, `wayfinder.app.map.map_shared`, `wayfinder.app.pages.checks_page`, `wayfinder.app.pages.dashboard`, `wayfinder.app.pages.diagnostics_page`, `wayfinder.app.pages.hints_page`, `wayfinder.app.pages.path_page`, `wayfinder.app.pages.setup_page`, `wayfinder.app.ui.appearance`, `wayfinder.app.ui.log_page`, `wayfinder.app.ui.logic_tools`, `wayfinder.app.ui.search_ui`, `wayfinder.app.ui.shell`, `wayfinder.app.ui.tracker_panels`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

# `wayfinder/maps/` — Map data subsystem

### `wayfinder/maps/__init__.py`
# WayFinder map-pack and conversion services.
- **Module:** `wayfinder.maps`
- **Exports:** _No declared public definitions/constants detected._
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/maps/assets.py`
# Bounded map asset caches and streaming image access.
- **Module:** `wayfinder.maps.assets`
- **Exports:** `IMAGE_CACHE_BYTES`, `LARGE_MAP_PIXELS`, `TiledMapPhoto`, `asset_key`, `cached_image`, `draw_map_photo`, `file_signature`, `image_bytes`, `image_hash`, `open_pack_image`, `remember_image`, `render_result`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `PIL`, `collections`, `contextlib`, `functools`, `hashlib`, `pathlib`, `zipfile`
- **Import-time importers:** `wayfinder.app.app`, `wayfinder.app.controllers.connection_controller`, `wayfinder.app.controllers.map_controller`, `wayfinder.app.controllers.setup_controller`, `wayfinder.app.controllers.snapshot_controller`, `wayfinder.app.map.map_pack_manager`, `wayfinder.app.map.map_shared`, `wayfinder.app.pages.checks_page`, `wayfinder.app.pages.dashboard`, `wayfinder.app.pages.diagnostics_page`, `wayfinder.app.pages.hints_page`, `wayfinder.app.pages.path_page`, `wayfinder.app.pages.setup_page`, `wayfinder.app.ui.appearance`, `wayfinder.app.ui.log_page`, `wayfinder.app.ui.logic_tools`, `wayfinder.app.ui.search_ui`, `wayfinder.app.ui.shell`, `wayfinder.app.ui.tracker_panels`, `wayfinder.maps.packs`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/maps/converter.py`
# Map-pack conversion helpers for WayFinder.
- **Module:** `wayfinder.maps.converter`
- **Exports:** `ConversionResult`, `WAYFINDER_PACK_FORMAT`, `WAYFINDER_PACK_VERSION`, `convert_map_pack`, `convert_poptracker_pack`, `convert_ut_pack`, `detect_map_pack_archive_format`
- **Import-time internal imports:** `wayfinder.maps.interpretation`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `dataclasses`, `json`, `pathlib`, `re`, `shutil`, `tempfile`, `typing`, `zipfile`
- **Import-time importers:** `wayfinder.app.app`, `wayfinder.app.controllers.connection_controller`, `wayfinder.app.controllers.map_controller`, `wayfinder.app.controllers.setup_controller`, `wayfinder.app.controllers.snapshot_controller`, `wayfinder.app.map.map_pack_manager`, `wayfinder.app.map.map_shared`, `wayfinder.app.pages.checks_page`, `wayfinder.app.pages.dashboard`, `wayfinder.app.pages.diagnostics_page`, `wayfinder.app.pages.hints_page`, `wayfinder.app.pages.path_page`, `wayfinder.app.pages.setup_page`, `wayfinder.app.ui.appearance`, `wayfinder.app.ui.log_page`, `wayfinder.app.ui.logic_tools`, `wayfinder.app.ui.search_ui`, `wayfinder.app.ui.shell`, `wayfinder.app.ui.tracker_panels`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/maps/intelligence.py`
# Conservative map coverage reports and evidence-based check filters.
- **Module:** `wayfinder.maps.intelligence`
- **Exports:** `check_evidence`, `map_intelligence`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `collections`
- **Import-time importers:** `wayfinder.app.app`, `wayfinder.app.controllers.connection_controller`, `wayfinder.app.controllers.map_controller`, `wayfinder.app.controllers.setup_controller`, `wayfinder.app.controllers.snapshot_controller`, `wayfinder.app.map.map_pack_manager`, `wayfinder.app.map.map_shared`, `wayfinder.app.pages.checks_page`, `wayfinder.app.pages.dashboard`, `wayfinder.app.pages.diagnostics_page`, `wayfinder.app.pages.hints_page`, `wayfinder.app.pages.path_page`, `wayfinder.app.pages.setup_page`, `wayfinder.app.ui.appearance`, `wayfinder.app.ui.log_page`, `wayfinder.app.ui.logic_tools`, `wayfinder.app.ui.reliability_ui`, `wayfinder.app.ui.search_ui`, `wayfinder.app.ui.shell`, `wayfinder.app.ui.tracker_panels`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/maps/interpretation.py`
# Shared tracker-pack interpretation primitives.
- **Module:** `wayfinder.maps.interpretation`
- **Exports:** `NORMALIZED_SCHEMA_NAME`, `NORMALIZED_SCHEMA_VERSION`, `extract_lua_location_id_mapping`, `iter_marker_records`, `loads_compatible_json`, `normalize_location_ids`, `read_compatible_json`, `strip_json_comments`, `strip_trailing_commas`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `json`, `pathlib`, `re`, `typing`
- **Import-time importers:** `wayfinder.maps.converter`, `wayfinder.maps.packs`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/maps/packs.py`
# WayFinder map-pack discovery and parsing.
- **Module:** `wayfinder.maps.packs`
- **Exports:** `DEFAULT_MAP_CACHE_LIMIT_BYTES`, `MAP_METADATA_CACHE_VERSION`, `MapDefinition`, `MapMarker`, `MapPack`, `PackValidationResult`, `SPATIAL_INDEX_CELL`, `TRACKER_PACK_API_VERSION`, `ZOOM_CACHE_LEVELS`, `ZOOM_CACHE_VERSION`, `best_pack`, `build_pack_zoom_cache`, `cached_map_path`, `default_pack_dir`, `discover_packs`, `enforce_map_cache_limit`, `game_pack_dir`, `install_pack_archive`, `install_validated_pack`, `load_pack_variant`, `map_cache_root`, `pack_dirs`, `persist_zoom_image_async`, `portable_pack_dir`, `related_archive_for_folder`, `remove_pack_zoom_cache`, `validate_pack_archive`, `validate_pack_folder`
- **Import-time internal imports:** `wayfinder.maps.assets`, `wayfinder.maps.interpretation`, `wayfinder.storage`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `PIL`, `collections`, `copy`, `dataclasses`, `hashlib`, `importlib`, `inspect`, `json`, `os`, `pathlib`, `re`, `shutil`, `sys`, `tempfile`, `threading`, `time`, `typing`, `zipfile`
- **Import-time importers:** `wayfinder.app.app`, `wayfinder.app.controllers.connection_controller`, `wayfinder.app.controllers.map_controller`, `wayfinder.app.controllers.setup_controller`, `wayfinder.app.controllers.snapshot_controller`, `wayfinder.app.map.map_pack_manager`, `wayfinder.app.map.map_shared`, `wayfinder.app.pages.checks_page`, `wayfinder.app.pages.dashboard`, `wayfinder.app.pages.diagnostics_page`, `wayfinder.app.pages.hints_page`, `wayfinder.app.pages.path_page`, `wayfinder.app.pages.setup_page`, `wayfinder.app.ui.appearance`, `wayfinder.app.ui.log_page`, `wayfinder.app.ui.logic_tools`, `wayfinder.app.ui.search_ui`, `wayfinder.app.ui.shell`, `wayfinder.app.ui.tracker_panels`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

# `wayfinder/runtime/` — Runtime subsystem

### `wayfinder/runtime/__init__.py`
# WayFinder-owned Archipelago tracker runtime.
- **Module:** `wayfinder.runtime`
- **Exports:** `RUNTIME_VERSION`
- **Import-time internal imports:** `wayfinder.version`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** `wayfinder.runtime.server`, `wayfinder.runtime.snapshot`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/ap_protocol.py`
# AP inspection and read-only refresh operations on the AP asyncio loop.
- **Module:** `wayfinder.runtime.ap_protocol`
- **Exports:** `APProtocol`, `install_packet_observer`
- **Import-time internal imports:** `wayfinder.connection.ap_inspector`, `wayfinder.diagnostics`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `asyncio`, `functools`, `time`
- **Import-time importers:** `wayfinder.runtime.native_reliability`
- **Lazy/local importers:** `wayfinder.runtime.server`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/apworld_catalog.py`
# Import-free APWorld inventory and content identities.
- **Module:** `wayfinder.runtime.apworld_catalog`
- **Exports:** `STAGES`, `WorldRecord`, `atomic_copy`, `atomic_json`, `content_hash`, `core_version`, `discover`, `inspect_world`, `inventory`, `normal_game`, `select_world`, `version_tuple`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** `wayfinder.runtime.dependency_manager`
- **External / standard-library imports:** `ast`, `dataclasses`, `hashlib`, `json`, `os`, `pathlib`, `re`, `shutil`, `tempfile`, `zipfile`
- **Import-time importers:** `wayfinder.app.ui.apworld_ui`, `wayfinder.runtime.apworld_compatibility`
- **Lazy/local importers:** `wayfinder.app.controllers.setup_controller`, `wayfinder.runtime.native_reliability`, `wayfinder.runtime.world_loader`, `wayfinder.setup.archipelago_core`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/apworld_compatibility.py`
# APWorld preflight, isolated compatibility tests and reconstruction caching.
- **Module:** `wayfinder.runtime.apworld_compatibility`
- **Exports:** `COMPATIBILITY_TESTER_VERSION`, `CORE_GENERATED`, `ReconstructionCache`, `compatibility_child`, `dependency_preflight`, `environment_identity`, `persist_exception`, `reconstruction_key`, `report_directory`, `require_dependencies`, `run_compatibility_test`, `save_report`, `tree_fingerprint`
- **Import-time internal imports:** `wayfinder`, `wayfinder.diagnostics`, `wayfinder.runtime.apworld_catalog`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.connection.identity`, `wayfinder.connection.protocol`, `wayfinder.runtime.bundled_wheels`, `wayfinder.runtime.process_manager`, `wayfinder.runtime.server`, `wayfinder.runtime.snapshot`, `wayfinder.runtime.source_recipes`, `wayfinder.runtime.world_builder`, `wayfinder.runtime.world_loader`, `wayfinder.setup`
- **External / standard-library imports:** `collections`, `hashlib`, `importlib`, `json`, `os`, `packaging.requirements`, `packaging.utils`, `pathlib`, `subprocess`, `sys`, `threading`, `time`, `traceback`, `types`, `uuid`
- **Import-time importers:** `wayfinder.app.ui.apworld_ui`
- **Lazy/local importers:** `wayfinder.runtime.native_reliability`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/bundled_wheels.py`
# Resolve WayFinder-hosted native wheels without bundling them in the app.
- **Module:** `wayfinder.runtime.bundled_wheels`
- **Exports:** `GITHUB_RAW_ROOT`, `NATIVE_NAMES`, `manifest_entries`, `remote_candidates`, `source_entry`
- **Import-time internal imports:** `wayfinder.runtime.source_recipes`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `packaging.utils`, `re`
- **Import-time importers:** `wayfinder.runtime.wheel_installer`
- **Lazy/local importers:** `wayfinder.runtime.apworld_compatibility`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/dependency_manager.py`
# Provide dependency manager support.
- **Module:** `wayfinder.runtime.dependency_manager`
- **Exports:** `AP_INTERNAL`, `COMMON_IMPORT_TO_DIST`, `DependencyScan`, `REQ_RE`, `VCS_IMPORT_REQUIREMENTS`, `dependency_report_ok`, `format_dependency_failure_report`, `install_all_dependencies`, `load_dependency_report`, `scan_dependencies`, `write_scan_report`
- **Import-time internal imports:** `wayfinder.diagnostics`, `wayfinder.runtime.wheel_installer`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `ast`, `dataclasses`, `json`, `os`, `packaging.requirements`, `packaging.utils`, `pathlib`, `re`, `shutil`, `sys`, `tempfile`, `typing`, `zipfile`
- **Import-time importers:** `wayfinder.setup`, `wayfinder.setup.dependencies`
- **Lazy/local importers:** `wayfinder.app.controllers.setup_controller`, `wayfinder.runtime.apworld_catalog`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/dependency_path.py`
# Activate installed libraries and their normal .pth startup hooks at runtime.
- **Module:** `wayfinder.runtime.dependency_path`
- **Exports:** `activate_dependencies`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `os`, `pathlib`, `site`, `sys`
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** `wayfinder.runtime.server`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/dependency_progress.py`
# Bounded worker-to-GUI progress delivery without calling Tk from a worker.
- **Module:** `wayfinder.runtime.dependency_progress`
- **Exports:** `DependencyProgress`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `threading`
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** `wayfinder.app.controllers.setup_controller`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/native_reliability.py`
# Native runtime reliability operations, independent of the AP asyncio loop.
- **Module:** `wayfinder.runtime.native_reliability`
- **Exports:** `NativeReliability`
- **Import-time internal imports:** `wayfinder.connection.identity`, `wayfinder.connection.protocol`, `wayfinder.diagnostics`, `wayfinder.runtime.ap_protocol`, `wayfinder.runtime.reliability`
- **Lazy/local internal imports:** `wayfinder.runtime.apworld_catalog`, `wayfinder.runtime.apworld_compatibility`, `wayfinder.runtime.snapshot`, `wayfinder.runtime.world_builder`, `wayfinder.runtime.world_loader`, `wayfinder.setup`
- **External / standard-library imports:** `asyncio`, `copy`, `importlib`, `json`, `pathlib`, `time`, `traceback`, `uuid`
- **Import-time importers:** `wayfinder.runtime.server`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/process_manager.py`
# Internal WayFinder runtime worker process management.
- **Module:** `wayfinder.runtime.process_manager`
- **Exports:** `allocate_ipc_port`, `internal_child_command`, `start_native_runtime`, `stop_process`
- **Import-time internal imports:** `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `os`, `pathlib`, `socket`, `subprocess`, `sys`
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** `wayfinder.app.controllers.setup_controller`, `wayfinder.app.ui.reliability_ui`, `wayfinder.runtime.apworld_compatibility`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/reliability.py`
# Provide reliability support.
- **Module:** `wayfinder.runtime.reliability`
- **Exports:** `COMPONENTS`, `Cancelled`, `HealthState`, `JobToken`, `RuntimeJobs`, `STATES`
- **Import-time internal imports:** `wayfinder.utils.ignored`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `collections`, `threading`, `time`, `uuid`
- **Import-time importers:** `wayfinder.app.ui.reliability_ui`, `wayfinder.runtime.native_reliability`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/server.py`
# Provide server support.
- **Module:** `wayfinder.runtime.server`
- **Exports:** `NativeRuntime`, `run_runtime`
- **Import-time internal imports:** `wayfinder.connection.protocol`, `wayfinder.diagnostics`, `wayfinder.runtime`, `wayfinder.runtime.native_reliability`, `wayfinder.runtime.snapshot`, `wayfinder.runtime.world_builder`, `wayfinder.runtime.world_loader`, `wayfinder.storage`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.logic.rule_explanation`, `wayfinder.runtime.ap_protocol`, `wayfinder.runtime.dependency_path`
- **External / standard-library imports:** `CommonClient`, `NetUtils`, `Utils`, `asyncio`, `collections`, `json`, `logging`, `os`, `pathlib`, `socket`, `ssl`, `sys`, `threading`, `time`, `types`, `typing`, `uuid`
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** `wayfinder.runtime.apworld_compatibility`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/snapshot.py`
# Provide snapshot support.
- **Module:** `wayfinder.runtime.snapshot`
- **Exports:** `build_snapshot`
- **Import-time internal imports:** `wayfinder.logic.apworld_adapter`, `wayfinder.logic.incremental`, `wayfinder.logic.logic_api`, `wayfinder.runtime`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.connection.memory`, `wayfinder.logic.rule_explanation`
- **External / standard-library imports:** `Utils`, `collections`, `hashlib`, `pathlib`, `re`, `time`, `types`, `typing`
- **Import-time importers:** `wayfinder.runtime.server`
- **Lazy/local importers:** `wayfinder.app.pages.setup_page`, `wayfinder.runtime.apworld_compatibility`, `wayfinder.runtime.native_reliability`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/source_recipes.py`
# Audited, checksum-pinned pure-Python layouts; never interpret setup/build code.
- **Module:** `wayfinder.runtime.source_recipes`
- **Exports:** `RECIPES`, `source_candidate`, `source_matches`, `source_payload`
- **Import-time internal imports:** _None._
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `base64`, `csv`, `email`, `hashlib`, `io`, `json`, `re`, `stat`, `tarfile`, `zipfile`
- **Import-time importers:** `wayfinder.runtime.bundled_wheels`, `wayfinder.runtime.wheel_installer`
- **Lazy/local importers:** `wayfinder.runtime.apworld_compatibility`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/wheel_installer.py`
# Wheel-only dependency installation; never executes package build/install code.
- **Module:** `wayfinder.runtime.wheel_installer`
- **Exports:** `FileRequirement`, `InstallError`, `ResolutionError`, `WheelInstaller`, `read_requirements`, `runtime_diagnostics`
- **Import-time internal imports:** `wayfinder.runtime.bundled_wheels`, `wayfinder.runtime.source_recipes`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** `base64`, `csv`, `email`, `hashlib`, `importlib`, `io`, `json`, `os`, `packaging.markers`, `packaging.requirements`, `packaging.specifiers`, `packaging.tags`, `packaging.utils`, `packaging.version`, `pathlib`, `re`, `shutil`, `stat`, `sys`, `tempfile`, `urllib`, `zipfile`
- **Import-time importers:** `wayfinder.runtime.dependency_manager`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/world_builder.py`
# Provide world builder support.
- **Module:** `wayfinder.runtime.world_builder`
- **Exports:** `BuiltWorld`, `build_world`
- **Import-time internal imports:** `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.storage`
- **External / standard-library imports:** `BaseClasses`, `Generate`, `dataclasses`, `json`, `logging`, `os`, `pathlib`, `re`, `settings`, `sys`, `tempfile`, `time`, `typing`, `worlds`, `worlds.AutoWorld`, `worlds.generic.Rules`, `yaml`, `zipfile`
- **Import-time importers:** `wayfinder.runtime.server`
- **Lazy/local importers:** `wayfinder.runtime.apworld_compatibility`, `wayfinder.runtime.native_reliability`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/runtime/world_loader.py`
# Provide world loader support.
- **Module:** `wayfinder.runtime.world_loader`
- **Exports:** `ensure_game_loaded`, `install_minimal_worlds_package`
- **Import-time internal imports:** `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.runtime.apworld_catalog`
- **External / standard-library imports:** `ast`, `importlib`, `json`, `logging`, `os`, `pathlib`, `sys`, `types`, `typing`, `worlds.AutoWorld`, `zipfile`, `zipimport`
- **Import-time importers:** `wayfinder.runtime.server`
- **Lazy/local importers:** `wayfinder.runtime.apworld_compatibility`, `wayfinder.runtime.native_reliability`
- **Dependency direction:** One-way at import-time level.

# `wayfinder/setup/` — Setup subsystem

### `wayfinder/setup/__init__.py`
# WayFinder setup services.
- **Module:** `wayfinder.setup`
- **Exports:** `APP_DATA_ROOT`, `AP_CORE_MANIFEST`, `AP_CORE_ROOT`, `AP_CORE_SOURCE`, `AP_SOURCE_ARCHIVE`, `DEFAULT_AP_PORT`, `DEPENDENCIES_DIR`, `DEPENDENCY_REPORT`, `LOGS_DIR`, `MAP_PACK_DIR`, `PLAYERS_DIR`, `_players_source`, `archipelago_candidates`, `compose_server`, `core_ready`, `dependency_report_ok`, `find_archipelago`, `find_matching_player_yaml`, `github_latest_archipelago_release`, `import_archipelago_core`, `imported_archipelago_version`, `is_archipelago`, `load_dependency_report`, `load_settings`, `save_settings`, `split_server_port`, `sync_custom_worlds`, `sync_player_yamls`
- **Import-time internal imports:** `wayfinder.runtime.dependency_manager`, `wayfinder.setup.archipelago_core`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** `wayfinder.app.app`, `wayfinder.app.controllers.connection_controller`, `wayfinder.app.controllers.map_controller`, `wayfinder.app.controllers.setup_controller`, `wayfinder.app.controllers.snapshot_controller`, `wayfinder.app.map.map_pack_manager`, `wayfinder.app.map.map_shared`, `wayfinder.app.pages.checks_page`, `wayfinder.app.pages.dashboard`, `wayfinder.app.pages.diagnostics_page`, `wayfinder.app.pages.hints_page`, `wayfinder.app.pages.path_page`, `wayfinder.app.pages.setup_page`, `wayfinder.app.ui.appearance`, `wayfinder.app.ui.apworld_ui`, `wayfinder.app.ui.log_page`, `wayfinder.app.ui.logic_tools`, `wayfinder.app.ui.search_ui`, `wayfinder.app.ui.shell`, `wayfinder.app.ui.tracker_panels`
- **Lazy/local importers:** `wayfinder.runtime.apworld_compatibility`, `wayfinder.runtime.native_reliability`
- **Dependency direction:** One-way at import-time level.

### `wayfinder/setup/archipelago_core.py`
# Shared Archipelago/setup backend used by the WayFinder application.
- **Module:** `wayfinder.setup.archipelago_core`
- **Exports:** `APP_DATA_ROOT`, `APP_VERSION`, `AP_CORE_MANIFEST`, `AP_CORE_ROOT`, `AP_CORE_SOURCE`, `AP_SOURCE_ARCHIVE`, `ARCHIPELAGO_RELEASE_API`, `DEFAULT_AP_PORT`, `DEPENDENCIES_DIR`, `DEPENDENCY_REPORT`, `LOGS_DIR`, `MAP_PACK_DIR`, `PLAYERS_DIR`, `PROJECT_CREATOR`, `PROJECT_FULL_NAME`, `PROJECT_NAME`, `RESOURCE_ROOT`, `SETTINGS_PATH`, `SYNC_MANIFEST_NAME`, `YAML_SYNC_MANIFEST_NAME`, `archipelago_candidates`, `compose_server`, `core_ready`, `find_archipelago`, `find_matching_player_yaml`, `github_latest_archipelago_release`, `import_archipelago_core`, `imported_archipelago_version`, `is_archipelago`, `load_settings`, `resource_root`, `save_settings`, `split_server_port`, `sync_custom_worlds`, `sync_player_yamls`
- **Import-time internal imports:** `wayfinder`, `wayfinder.connection.memory`, `wayfinder.storage`, `wayfinder.utils.ignored`
- **Lazy/local internal imports:** `wayfinder.runtime.apworld_catalog`
- **External / standard-library imports:** `json`, `os`, `pathlib`, `re`, `shutil`, `socket`, `subprocess`, `sys`, `tempfile`, `threading`, `urllib`, `webbrowser`, `zipfile`
- **Import-time importers:** `wayfinder.setup`, `wayfinder.setup.dependencies`, `wayfinder.setup.player_yamls`, `wayfinder.setup.worlds`
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/setup/dependencies.py`
# World dependency installation paths and helpers.
- **Module:** `wayfinder.setup.dependencies`
- **Exports:** `AP_CORE_SOURCE`, `DEPENDENCIES_DIR`, `DEPENDENCY_REPORT`, `dependency_report_ok`, `format_dependency_failure_report`, `install_all_dependencies`, `load_dependency_report`
- **Import-time internal imports:** `wayfinder.runtime.dependency_manager`, `wayfinder.setup.archipelago_core`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/setup/player_yamls.py`
# Player YAML discovery and synchronization helpers.
- **Module:** `wayfinder.setup.player_yamls`
- **Exports:** `AP_CORE_SOURCE`, `PLAYERS_DIR`, `_players_source`, `find_matching_player_yaml`, `sync_player_yamls`
- **Import-time internal imports:** `wayfinder.setup.archipelago_core`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

### `wayfinder/setup/worlds.py`
# Game APWorld synchronization helpers.
- **Module:** `wayfinder.setup.worlds`
- **Exports:** `AP_CORE_SOURCE`, `SYNC_MANIFEST_NAME`, `find_archipelago`, `is_archipelago`, `sync_custom_worlds`
- **Import-time internal imports:** `wayfinder.setup.archipelago_core`
- **Lazy/local internal imports:** _None._
- **External / standard-library imports:** _None._
- **Import-time importers:** _No import-time production-module importers detected._
- **Lazy/local importers:** _None._
- **Dependency direction:** One-way at import-time level.

# Root-level files

- `run_wayfinder.py` — primary Python entrypoint and role dispatcher.
- `run_pytests.py` — repository test runner with per-file output.
- `requirements.txt` — runtime Python dependencies.
- `BUILD-SINGLE-EXE.bat` — Windows executable build helper.
- `tools/generate_project_structure.py` — regenerates this document from the real source/import graph.

# Dependency interpretation legend

- **A → B**: A imports/uses B directly; B does not directly import A.
- **A ⇄ B**: reciprocal direct imports; avoid because import order/test isolation become fragile.
- **Implicit GUI coupling**: mixins can call methods/read state supplied by another mixin through `WayFinderApp` even without a Python import edge.
- **Composition dependency**: `app.py` intentionally imports many components because it assembles the application; those components should not import `app.py` back.

# Regeneration

Run `python tools/generate_project_structure.py --check` to verify the document is current, or run it without `--check` to rewrite `PROJECT_STRUCTURE.md`.
