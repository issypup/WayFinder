# WayFinder

**WayFinder** is a standalone desktop tracker, map viewer, and
logic-analysis application for [Archipelago](https://archipelago.gg/)
multiworld randomizers.

WayFinder provides its own native tracking, logic
reconstruction, map integration, progression analysis, diagnostics, and
Archipelago runtime integration in one application.

> **Current version:** 1.0.0\
> **Recommended development/build Python:** Python 3.13\
> **Primary entry point:** `run_wayfinder.py`

------------------------------------------------------------------------

## What WayFinder Does

WayFinder connects to an Archipelago multiworld session and turns the
information available from the server, the installed APWorld, player
configuration, and map packs into a live view of the player's seed.

Its main purpose is to answer questions such as:

-   What checks can I currently reach?
-   Which checks have already been completed?
-   Why is a location reachable or unreachable?
-   What item, event, entrance, or requirement am I missing?
-   Which region am I currently in?
-   Where should I look next?
-   How do I reach a particular location or goal?
-   Is the installed APWorld compatible with WayFinder?
-   What logic did the APWorld actually generate for this seed?

WayFinder also provides interactive maps via converted Poptracker and Universal Tracker map packs. that can update alongside the
connected Archipelago session.

------------------------------------------------------------------------

## Major Features

### Native Archipelago Tracking

WayFinder connects directly to Archipelago and maintains its own
representation of the current player state.

It tracks information including:

-   received items;
-   checked locations;
-   available locations;
-   slot data;
-   hints;
-   entrances;
-   events;
-   DataStorage information;
-   current player area where supported;
-   player position where supported;
-   connection and runtime state.


------------------------------------------------------------------------

### Native Logic Reconstruction

WayFinder can load the game's APWorld and reconstruct its logic inside
an isolated native runtime.

This allows WayFinder to evaluate the same kinds of rules used by the
Archipelago world implementation, including:

-   regions;
-   entrances;
-   locations;
-   item requirements;
-   event requirements;
-   AND/OR conditions;
-   item counts;
-   option-dependent rules;
-   progression state;
-   goal requirements.

The resulting logic snapshot is then consumed by the main GUI rather
than executing arbitrary APWorld logic directly inside the interface
process.

This separation helps keep the UI responsive and provides a clearer
boundary between the application and imported Archipelago/APWorld code.

------------------------------------------------------------------------

### Reachability Explanations

WayFinder does more than display whether a check is reachable.

The logic analysis tools can inspect **why** a location is or is not
available and can expose requirements such as:

-   missing items;
-   insufficient item counts;
-   inaccessible entrances;
-   unmet events;
-   blocked regions;
-   nested rule conditions.

This information is used throughout features such as the Checks page,
Progression Graph, Path Explorer, and **I'm Stuck?** tools.

------------------------------------------------------------------------

### Interactive Maps

WayFinder supports installable map packs and can associate maps with
games.

Depending on the map pack and APWorld, maps can provide:

-   check markers;
-   checked/unchecked state;
-   reachability state;
-   entrance markers;
-   region switching;
-   automatic current-map selection;
-   player position;
-   route overlays;
-   grouped or overlapping marker handling;
-   map pop-outs;
-   zooming and navigation.

WayFinder includes support for interpreting PopTracker-style map packs, Unviersal Tracker-style map packs and contains a map-pack conversion layer for supported formats.

The **Installed Maps** page can be used to install, validate, rescan,
select, and manage map packs.

------------------------------------------------------------------------

### Automatic Map Following

When sufficient information is available, WayFinder can determine the
player's current area from the connected game/APWorld and automatically
display the corresponding map.

Map packs can also be linked to a game so the appropriate pack can be
selected automatically when that game is connected.

------------------------------------------------------------------------

### Checks

The Checks page provides a live view of locations in the current seed.

Checks can be filtered and inspected to determine their current status
and logic requirements.

WayFinder synchronises collected checks from Archipelago and updates the
corresponding state in the tracker and map.

------------------------------------------------------------------------

### Search, Hints & Inventory

WayFinder provides tools for inspecting the current seed without needing
to manually search through raw Archipelago data.

These include:

-   location search;
-   inventory inspection;
-   progression information;
-   Archipelago hints;
-   logic-aware search results.

------------------------------------------------------------------------

### I'm Stuck?

The **I'm Stuck?** feature uses the current logic state to help identify
useful places to investigate.

Rather than simply displaying every unchecked location, it can use
WayFinder's progression information to find currently relevant
destinations and expose the reasoning behind them.

------------------------------------------------------------------------

### Path Explorer

Path Explorer walks backwards through WayFinder's reconstructed region
and entrance logic to explain how a target can be reached.

Where map information is available, route information can also be
displayed as an overlay.

------------------------------------------------------------------------

### Progression Graph

The Progression Graph visualises reconstructed logic as connected
requirements.

It can represent structures such as:

-   AND conditions;
-   OR conditions;
-   item counts;
-   regions;
-   entrances;
-   locations;
-   progression requirements.

This is particularly useful when diagnosing complex APWorld rules.

* There may still be flaws in some logic and any issues found I would love to have reported. through the generated log files and screenshots of the issue.

------------------------------------------------------------------------

### APWorld Compatibility Testing

APWorlds vary considerably in how they implement Archipelago logic.

WayFinder therefore includes compatibility testing and diagnostics for
installed APWorlds.

The compatibility system can inspect an APWorld separately and report
whether its modules, dependencies, and relevant world structures can be
loaded successfully.

Custom APWorlds are supported and can take precedence over built-in
Archipelago worlds where appropriate.

------------------------------------------------------------------------

### Diagnostics and Logging

WayFinder includes extensive runtime diagnostics intended to make
APWorld, connection, dependency, logic, and map problems easier to
investigate.

The current build keeps a stable current log rather than accumulating a
large number of boot logs.

On Windows, the default log location is:

``` text
%LOCALAPPDATA%\WayFinder\logs\latest.log
```

The current process ID is stored at:

``` text
%LOCALAPPDATA%\WayFinder\logs\latest.pid
```

Additional diagnostic and compatibility information is available from
inside the application.

------------------------------------------------------------------------

## How WayFinder Works

At a high level, WayFinder consists of three cooperating parts:

``` text
Archipelago Server
        │
        ▼
WayFinder Connection Layer
        │
        ├──────────────► GUI / Maps / Checks / Hints
        │
        ▼
Native Runtime Process
        │
        ▼
Archipelago Source + APWorld
        │
        ▼
Reconstructed Logic Snapshot
        │
        ▼
WayFinder Logic / Progression Analysis
```

### 1. Connection Layer

The main application establishes the Archipelago connection and receives
live session information.

### 2. Native Runtime

WayFinder starts an isolated runtime process when it needs to
reconstruct game logic.

The runtime imports the Archipelago source and appropriate APWorld
supplied through WayFinder Setup.

### 3. Logic Snapshot

The runtime converts relevant world state into data that WayFinder can
safely consume.

### 4. Application Analysis

WayFinder's own logic, map, progression, and diagnostic components
consume that state to update the interface.

The application therefore remains WayFinder-owned while still being able
to understand game-specific Archipelago logic.

------------------------------------------------------------------------

## Repository Layout

The main source tree is organised roughly as follows:

``` text
WayFinder/
│
├── assets/
│   ├── sidebar/               # Sidebar icons
│   ├── wayfinder.ico          # Windows application icon
│   └── wayfinder_icon_master.png
│
├── pytest/
│   ├── tests/                 # Automated test suite
│   ├── conftest.py
│   └── pytest.ini
│
├── tools/
│   ├── build_native_wheels.py
│   ├── generate_project_structure.py
│   └── verify_native_wheels.py
│
├── wayfinder/
│   ├── app/                   # Main desktop application
│   │   ├── controllers/       # Application controllers
│   │   ├── core/              # Shared application state/core code
│   │   ├── map/               # GUI map integration
│   │   ├── pages/             # Main application pages
│   │   └── ui/                # Shared UI components
│   │
│   ├── connection/            # Archipelago connection handling
│   ├── logic/                 # Logic and progression analysis
│   ├── maps/                  # Map-pack interpretation
│   ├── runtime/               # Isolated native runtime
│   ├── setup/                 # Setup and installation management
│   ├── utils/                 # Shared utilities
│   ├── diagnostics.py
│   ├── storage.py
│   └── version.py
│
├── BUILD-SINGLE-EXE.bat       # Windows EXE build script
├── PROJECT_STRUCTURE.md       # Detailed generated project structure
├── requirements.txt           # Local development requirements
├── run_pytests.py             # Test runner
└── run_wayfinder.py           # Main WayFinder entry point
```

For a much more detailed breakdown of the source tree, see
`PROJECT_STRUCTURE.md`.

------------------------------------------------------------------------

# Installation and First-Time Setup

## Requirements

For running WayFinder from source, use:

-   Windows;
-   **Python 3.13**;
-   pip;
-   the dependencies listed in `requirements.txt`.

The packaged EXE is intended for end users who do not want to run
WayFinder directly through Python.

Archipelago source, APWorlds, world-specific dependencies, player YAMLs,
and maps are managed separately through **WayFinder Setup**.

------------------------------------------------------------------------

## Running WayFinder From Source

Clone or download the repository and open a terminal in its root
directory.

### 1. Install the development requirements

Using the Python launcher on Windows:

``` powershell
py -3.13 -m pip install -r requirements.txt
```

### 2. Start WayFinder

Run:

``` powershell
py -3.13 .\run_wayfinder.py
```

**`run_wayfinder.py` is the canonical application entry point.**

Do not launch individual files inside `wayfinder/app/` directly.

The same entry point is also used internally for isolated runtime and
dependency-installer child processes.

------------------------------------------------------------------------

# WayFinder Setup

The first-time setup process prepares the external resources WayFinder
needs.

The Setup page covers the following areas:

### Storage

Select where WayFinder should keep its application data.

On Windows the default location is:

``` text
%LOCALAPPDATA%\WayFinder
```

### Archipelago Core

Import or select the Archipelago source .zip from github.com/ArchipelagoMW/Archipelago/releases used by WayFinder's native
runtime.

WayFinder deliberately does not embed the complete Archipelago source
into its own repository or executable.

### Game APWorlds

WayFinder scans the imported Archipelago world catalogue and any
supported custom APWorlds.

### World Dependencies

Individual APWorlds can require Python packages beyond WayFinder's own
dependencies.

WayFinder's dependency manager detects and installs these into its
managed environment rather than expecting every dependency to be
globally installed by the user.

### Player YAMLs

Player YAML files can be supplied to help WayFinder reconstruct the
exact options used to generate a slot.

A YAML is not always mandatory: some APWorlds expose enough information
through slot data for WayFinder to reconstruct the relevant state
without one.

### Maps

Map packs can be installed and associated with supported games.

### Ready

Once the required core components pass validation, WayFinder can start
its native runtime and connect to the requested Archipelago session.

------------------------------------------------------------------------

# Connecting to Archipelago

Connection settings are available from WayFinder's connection interface.

Typical connection information consists of:

``` text
Server / Host
Port
Slot
Password (when required)
```

A commonly used local Archipelago server address, for example, is:

``` text
127.0.0.1:38281
```

Use the host and port belonging to your own Archipelago room/server.

WayFinder does not need to connect during application startup. The
runtime and seed preparation are initiated when required by the
connection workflow.

------------------------------------------------------------------------

# Building `WayFinder.exe`

WayFinder includes a Windows build script:

``` text
BUILD-SINGLE-EXE.bat
```

The script is the recommended way to produce the release executable.

## Build Requirements

The build machine must have:

-   Windows;
-   Python **3.13**;
-   the `py` Python launcher;
-   pip;
-   internet access when build dependencies need to be installed.

From the repository root, run:

``` powershell
.\BUILD-SINGLE-EXE.bat
```

or double-click:

``` text
BUILD-SINGLE-EXE.bat
```

------------------------------------------------------------------------

## What the Build Script Does

The build process performs four main stages.

### 1. Installs Build and Runtime Dependencies

The script uses Python 3.13 and installs/upgrades the packages needed
for the packaged application, including PyInstaller and WayFinder's
packaged runtime dependencies.

### 2. Cleans Previous Build Output

The following previous build output is removed:

``` text
build\
release\
WayFinder.spec
```

The build also checks that obsolete integration/runtime files are not
present.

### 3. Builds the Single Executable

PyInstaller builds:

``` text
release\WayFinder.exe
```

The current configuration uses:

``` text
--onefile
--console
```

This produces a single executable and retains the live debug console.

The application icon is taken from:

``` text
assets\wayfinder.ico
```

Required WayFinder assets and Python packages are collected into the
build automatically.

### 4. Cleans Temporary Build Files

After a successful build, temporary PyInstaller output is removed and
the `release` directory is opened.

The final executable is:

``` text
release\WayFinder.exe
```

------------------------------------------------------------------------

## Important Build Note

The EXE contains the **WayFinder application, native tracker/logic
engine, and native runtime adapter**.

The complete Archipelago core/game source is **not** bundled into the
executable.

Users import the Archipelago source through WayFinder Setup at runtime.

This keeps the WayFinder application build separate from the collection
of Archipelago game worlds it may be asked to inspect.

------------------------------------------------------------------------

# Running Tests

WayFinder contains a substantial pytest suite covering areas such as:

-   native tracking;
-   connection preparation;
-   APWorld discovery;
-   map conversion;
-   map rendering;
-   live map switching;
-   logic explanations;
-   progression analysis;
-   entrance handling;
-   dependency management;
-   setup;
-   UI behaviour;
-   diagnostics;
-   packaging.

The repository provides its own test runner:

``` powershell
py -3.13 .\run_pytests.py
```

Tests can also be run directly with pytest where appropriate.

------------------------------------------------------------------------

# Application Data

Unless a different storage location is selected, WayFinder uses:

``` text
%LOCALAPPDATA%\WayFinder
```

This area is used for managed application data such as:

-   settings;
-   imported/setup resources;
-   APWorld information;
-   player configuration;
-   installed maps;
-   managed Python packages;
-   compatibility reports;
-   diagnostics;
-   logs;
-   solver output.

Users should generally manage these resources through WayFinder rather
than editing generated files manually.

------------------------------------------------------------------------

# Dependency Management

There are two different kinds of dependencies in a WayFinder
installation.

## WayFinder Dependencies

These are packages needed by WayFinder itself.

For source development they are installed from:

``` text
requirements.txt
```

## APWorld Dependencies

These belong to individual Archipelago game worlds.

They are handled by WayFinder's **World Dependencies** setup stage and
are deliberately not all placed in the root development requirements
file.

This separation prevents the base WayFinder environment from having to
contain the dependency set for every APWorld in existence.

------------------------------------------------------------------------

# Custom APWorlds

WayFinder is designed to work with both the standard worlds in an
imported Archipelago source tree and compatible custom APWorlds.

Because APWorlds can contain arbitrary game-specific Python logic and
dependencies, compatibility is not guaranteed for every world.

Use WayFinder's APWorld testing, compatibility, runtime-health, and
diagnostics tools when adding or updating a world.

------------------------------------------------------------------------

# Map Packs

Map packs are separate from APWorlds.

An APWorld defines the game's Archipelago behaviour and logic, while a
map pack tells WayFinder how to present locations and regions visually.

A map pack can contain information such as:

-   maps/images;
-   regions;
-   location markers;
-   entrance markers;
-   marker groups;
-   map transitions;
-   tracker IDs;
-   automatic region information.

WayFinder's interpretation layer attempts to resolve map-pack
identifiers against the actual locations and state reported by the
connected Archipelago game.

Because community map packs can differ significantly in structure,
WayFinder includes validation and compatibility logic rather than
assuming every pack uses exactly the same format.

------------------------------------------------------------------------

# Debugging Problems

If WayFinder fails to connect, load an APWorld, reconstruct logic,
install dependencies, or display a map correctly, start with:

``` text
%LOCALAPPDATA%\WayFinder\logs\latest.log
```

Useful information can also be found in the application's:

-   Log page;
-   Diagnostics page;
-   Runtime Health page;
-   APWorld Compatibility tools;
-   AP Connection inspector.

When reporting a bug, include:

1.  the WayFinder version;
2.  the game/APWorld and its version;
3.  whether the APWorld is built-in or custom;
4.  the relevant `latest.log`;
5.  what you expected to happen;
6.  what actually happened;
7.  steps that reproduce the issue;
8.  screenshots where the problem is visual.

Avoid publishing passwords or other private connection information in
public bug reports.

------------------------------------------------------------------------

# Development Notes

## Version Information

WayFinder's application version is sourced from:

``` text
wayfinder/version.py
```

Code that needs the WayFinder version should use the central version
definition rather than introducing another hard-coded version string.

------------------------------------------------------------------------

## Entry-Point Roles

`run_wayfinder.py` is not only the GUI launcher.

The executable can re-enter the same entry point for internal process
roles, including:

``` text
--native-runtime
--install-dependencies
--test-apworld
```

These are internal implementation details and normally do not need to be
launched manually.

------------------------------------------------------------------------

## Generated Project Documentation

The repository includes:

``` text
PROJECT_STRUCTURE.md
```

This contains a much more detailed inventory of the project and is
useful when navigating the codebase.

The associated generator is located at:

``` text
tools\generate_project_structure.py
```

------------------------------------------------------------------------

# Design Goals

WayFinder is being developed around several core principles:

**Native tracking**\
WayFinder understands Archipelago sessions.

**Game independence**\
Game-specific behaviour should come from APWorlds and map packs rather
than being hard-coded into the main application wherever possible.

**Explainable logic**\
A tracker should be able to explain *why* something is or is not
available, not only display a colour.

**Useful diagnostics**\
APWorlds are complex and community-developed. Failures should produce
actionable information rather than silently disappearing.

**Managed setup**\
Players should not need to manually construct complicated Python
environments for each APWorld.

**Live behaviour**\
Checks, maps, entrances, hints, inventory, and progression state should
react to the connected Archipelago session without requiring manual
refreshes.

------------------------------------------------------------------------

# Project Status

WayFinder is under active development.

Although the project has reached the **1.0.0** version line,
Archipelago's APWorld ecosystem is extremely varied. Some games and map
packs may require compatibility work, additional dependencies, or
special interpretation before every WayFinder feature is available.

Compatibility reports and reproducible bug reports are therefore
particularly valuable.

------------------------------------------------------------------------

# Contributing

Contributions are welcome.

When making changes:

1.  keep game-specific behaviour out of generic systems where practical;
2.  preserve the separation between the GUI and isolated native runtime;
3.  add or update tests for behavioural changes;
4.  run the test suite before submitting changes;
5.  avoid silently swallowing exceptions;
6.  keep version information centralised;
7.  include diagnostics for failure paths that users may need to report.

Run the test suite with:

``` powershell
py -3.13 .\run_pytests.py
```

For larger architectural changes, `PROJECT_STRUCTURE.md` is a useful
starting point for understanding dependencies between modules.

------------------------------------------------------------------------

# Quick Start

For developers running from source:

``` powershell
git clone <repository-url>
cd WayFinder
py -3.13 -m pip install -r requirements.txt
py -3.13 .\run_wayfinder.py
```

For a release build:

``` powershell
.\BUILD-SINGLE-EXE.bat
```

The resulting application will be:

``` text
release\WayFinder.exe
```

Then open WayFinder, complete **WayFinder Setup**, connect to your
Archipelago session, and select or install a compatible map pack if you
want map tracking.

------------------------------------------------------------------------

## License

Add the project's licence information here if/when a licence is included
in the repository.

------------------------------------------------------------------------

**WayFinder --- native Archipelago tracking, mapping, and logic
analysis.**
