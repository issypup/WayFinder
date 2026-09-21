"""Provide server support."""
# /**
#  * Module: wayfinder.runtime/server.py
#  * Purpose: Runtime module for server; bridges loaded Archipelago worlds and live server state into tracker snapshots.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

import asyncio
import json
import logging
from .native_reliability import NativeReliability
from wayfinder.diagnostics import sanitize, register_secret
import os
import socket
import ssl
import sys
import threading
import time
import types
import uuid
from pathlib import Path
from wayfinder.storage import app_data_root
from typing import Any

from wayfinder.connection.protocol import (
    CAPABILITIES, MAX_MESSAGE_BYTES, PROTOCOL_MAX, PROTOCOL_MIN, PROTOCOL_VERSION,
    encode_snapshot, error_payload,
)
from . import RUNTIME_VERSION
from .snapshot import build_snapshot
from .world_builder import build_world
from .world_loader import install_minimal_worlds_package, ensure_game_loaded

# Variable(s): `log` (log); named state retained for the surrounding calculation or subsequent calls.
log = logging.getLogger("WayFinder.Native")


class _ArchipelagoConnectionRefusedFilter(logging.Filter):
    """Turn the expected sleeping-host refusal into a concise, non-fatal log line.

    Hosted Archipelago rooms can refuse TCP connections while their web host is
    asleep. CommonClient logs that expected condition with ``logger.exception``,
    which otherwise prints a full traceback on every automatic retry. WayFinder
    keeps the retry behaviour, but removes the scary traceback and rate-limits
    the explanatory line.
    """
    def __init__(self) -> None:
        """Handle init."""
        super().__init__()
        self._last_notice = 0.0

    def filter(self, record: logging.LogRecord) -> bool:
        """Handle filter."""
        message = record.getMessage()
        exc = record.exc_info[1] if record.exc_info else None
        is_refusal = isinstance(exc, ConnectionRefusedError) or "Connection refused by the server" in message
        is_protocol_probe_failure = isinstance(exc, ssl.SSLError) and (
            "WRONG_VERSION_NUMBER" in str(exc).upper() or "WRONG VERSION NUMBER" in str(exc).upper()
        )
        if not (is_refusal or is_protocol_probe_failure):
            return True
        now = time.monotonic()
        if now - self._last_notice < 30.0:
            return False
        self._last_notice = now
        if is_protocol_probe_failure:
            record.msg = (
                "Archipelago connection negotiation is not ready yet. The AP client tried its encrypted fallback after "
                "the plain websocket handshake failed; WayFinder will keep retrying automatically."
            )
        else:
            record.msg = (
                "Archipelago server is not accepting connections yet. If this is a hosted room that has gone to sleep, "
                "open the room/site to wake it; WayFinder will keep retrying automatically."
            )
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.levelno = logging.WARNING
        record.levelname = "WARNING"
        return True


def _install_expected_connection_refusal_filter() -> None:
    """Install the refusal filter on AP/root loggers without changing other errors."""
    filter_obj = _ArchipelagoConnectionRefusedFilter()
    root_logger = logging.getLogger()
    root_logger.addFilter(filter_obj)
    for handler in root_logger.handlers:
        handler.addFilter(filter_obj)
    for logger_obj in logging.Logger.manager.loggerDict.values():
        if isinstance(logger_obj, logging.Logger):
            logger_obj.addFilter(filter_obj)
            for handler in logger_obj.handlers:
                handler.addFilter(filter_obj)



def _normalise_consulted_for_display(consulted, rule_satisfied):
    """Return display-safe predicate rows for a flattened traced rule.

    The AP adapter records comparisons as they execute, but a Python rule can
    negate those comparisons (for example ``not count < 5``).  The runtime
    route payload historically flattened every observed predicate beneath an
    AND node, which made a satisfied negated rule appear as ``0/4`` with four
    red children.

    When the *whole rule* succeeded and every observed comparison is a false,
    invertible item-count predicate, normalise each predicate to its logical
    complement.  This preserves the truth of the executed APWorld rule while
    keeping the compact AND visualisation internally consistent.  Raw adapter
    diagnostics remain unchanged; this only affects the route/explanation
    payload consumed by the GUI.
    """
    rows=[dict(row) for row in (consulted or [])]
    if not rows or rule_satisfied is not True:
        return rows

    inverse={
        "<": ">=", "<=": ">", ">": "<=", ">=": "<",
        "==": "!=", "=": "!=", "!=": "==",
    }
    invertible=[]
    for row in rows:
        kind=str(row.get("kind","")).lower()
        operator=str(row.get("operator","") or "").strip()
        if kind != "item_count" or operator not in inverse or bool(row.get("result")):
            return rows
        invertible.append((row,operator))

    for row,operator in invertible:
        new_operator=inverse[operator]
        row["operator"]=new_operator
        row["result"]=True
        name=str(row.get("name","item"))
        have=row.get("have")
        required=row.get("required")
        row["detail"]=f"{name}: have {have}, need {new_operator} {required}"
        row["display_normalized"]="negated comparison"
    return rows

# /**
#  * Class: NativeRuntime
#  * Purpose: Encapsulate the NativeRuntime responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
class NativeRuntime(NativeReliability):
    # /**
    #  * Function: __init__
    #  * Purpose: Initialize this object and establish its required runtime state.
    #  * @param runtime_port: Runtime port supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param ap_root: Ap root supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param players_path: Players path supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    """Provide native runtime behavior."""
    def __init__(self, runtime_port: int, ap_root: str, players_path: str = "") -> None:
        """Handle init."""
        self.ipc_port = int(runtime_port)
        self.ap_root = str(ap_root)
        self.players_path = str(players_path or "")
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ctx: Any = None
        self.built: Any = None
        self.slot_data: dict[str, Any] = {}
        self.ignored_names: set[str] = set()
        self.sequence = 0
        self.runtime_id = uuid.uuid4().hex
        self.session_id = uuid.uuid4().hex
        self.client: socket.socket | None = None
        self.client_lock = threading.RLock()
        self.send_lock = threading.Lock()
        self.stop = threading.Event()
        self.listener_ready = threading.Event()
        self.listener_error = ""
        self.startup_stage = "created"
        self.startup_error = ""
        self.startup_messages: list[str] = []
        self.init_reliability()

    # /**
    #  * Function: bootstrap_ap
    #  * Purpose: Perform the bootstrap ap operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def bootstrap_ap(self) -> None:
        # Variable(s): `root` (root); named state retained for the surrounding calculation or subsequent calls.
        """Handle bootstrap ap."""
        root = Path(self.ap_root)
        if not root.is_dir():
            raise RuntimeError(f"Archipelago core source is missing: {root}")
        sys.path.insert(0, str(root))
        # Dependencies installed by WayFinder Setup live outside the application so
        # they also work with the one-file EXE. Put them ahead of site-packages
        # but behind the imported Archipelago source itself.
        dep_root = app_data_root() / "python_packages"
        dep_root.mkdir(parents=True, exist_ok=True)
        from .dependency_path import activate_dependencies
        activate_dependencies(dep_root)
        self.set_startup_stage("dependency_path_ready", f"WayFinder dependency path: {dep_root}")

        # Archipelago's stock CommonClient.py and Generate.py import ModuleUpdate
        # and immediately call ModuleUpdate.update().  That routine scans the
        # requirements for every bundled world and may stop for interactive
        # installs (for example PyMemoryEditor) even though WayFinder does
        # not use those worlds.  WayFinder owns dependency management, so place
        # a tiny compatibility module in sys.modules *before* any AP import.
        # This also protects users who already imported an older AP core tree;
        # they do not need to re-import it just to receive this fix.
        # Variable(s): `module_update` (module update); named state retained for the surrounding calculation or subsequent calls.
        module_update = types.ModuleType("ModuleUpdate")
        module_update.update_ran = True
        module_update.requirements_files = set()

        # /**
        #  * Function: _wf_noop_module_update
        #  * Purpose: Perform the wf noop module update operation while keeping the surrounding subsystem state consistent.
        #  * @param args: Args supplied by the caller; see type hints and call sites for domain constraints.
        #  * @param kwargs: Kwargs supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        def _wf_noop_module_update(*args, **kwargs):
            """Handle wf noop module update."""
            return None

        module_update.update = _wf_noop_module_update
        sys.modules["ModuleUpdate"] = module_update
        self.set_startup_stage(
            "module_update_disabled",
            "Archipelago automatic dependency installer disabled; WayFinder will not scan unrelated world requirements.",
        )

        # Archipelago's stock worlds/__init__.py eagerly imports every bundled
        # and custom world.  Install a minimal package shell instead; the
        # connected game is loaded on demand after the Connected packet tells
        # us its exact game name.
        install_minimal_worlds_package(root)
        self.set_startup_stage(
            "selective_world_loader_ready",
            "Selective APWorld loader ready; unrelated game worlds will not be imported.",
        )

        # Explicit guard: WayFinder must never import the old tracker world.
        if "worlds.tracker" in sys.modules or "worlds.tracker.TrackerCore" in sys.modules:
            raise RuntimeError("Legacy tracker module was imported into WayFinder native runtime; refusing to continue")

    # /**
    #  * Function: _make_context
    #  * Purpose: Perform the make context operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _make_context(self):
        # Do not call CommonContext.__init__ here.  On large/custom Archipelago
        # installs that constructor eagerly expands the complete local data
        # package before the runtime can become ready.  We only need the small
        # network-client state at startup; the server supplies the connected
        # game's DataPackage during the normal RoomInfo handshake.
        """Handle make context."""
        from CommonClient import CommonContext, server_loop, keep_alive
        import CommonClient
        from .ap_protocol import install_packet_observer
        install_packet_observer(CommonClient)
        _install_expected_connection_refusal_filter()
        from NetUtils import JSONtoTextParser, RawJSONtoTextParser
        # Variable(s): `outer` (outer); named state retained for the surrounding calculation or subsequent calls.
        outer = self

        # /**
        #  * Class: WayFinderContext
        #  * Purpose: Encapsulate the WayFinderContext responsibilities and state used by this module.
        #  * @state: Instance attributes hold the durable state needed by this responsibility.
        #  */
        class WayFinderContext(CommonContext):
            # Variable(s): `tags` (tags); named state retained for the surrounding calculation or subsequent calls.
            """Provide way finder context behavior."""
            tags = CommonContext.tags | {"WayFinder"}
            # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
            game = ""
            # Variable(s): `items_handling` (items handling); named state retained for the surrounding calculation or subsequent calls.
            items_handling = 0b111
            # Variable(s): `want_slot_data` (want slot data); named state retained for the surrounding calculation or subsequent calls.
            want_slot_data = True

            # /**
            #  * Function: __init__
            #  * Purpose: Initialize this object and establish its required runtime state.
            #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
            #  */
            def __init__(self):
                """Handle init."""
                outer.set_startup_stage("context_network_state", "Creating lightweight WayFinder network context.")

                # Server state.  Mirrors the generic AP client contract without
                # performing the expensive eager all-world DataPackage copy.
                self.server_address = None
                # Keep CommonContext's own transport bookkeeping semantics intact.
                # Do not shadow ``server`` / ``server_task`` here: AP core uses
                # those attributes during RoomInfo -> InvalidGame -> game probing.
                # WayFinder checks instance-owned transport state explicitly when
                # deciding whether a previous session really exists.
                self.disconnected_intentionally = False
                # WayFinder-owned latch. CommonClient may temporarily set
                # disconnected_intentionally while rejecting a wrong game
                # during slot-game probing, so that AP flag cannot be used to
                # distinguish a real user Disconnect from InvalidGame.
                self._wayfinder_manual_disconnect = False
                self.username = None
                self.password = None
                self.hint_cost = None
                self.slot_info = {}
                self.permissions = {"release": "disabled", "collect": "disabled", "remaining": "disabled"}

                # Own connection/session state.
                self.finished_game = False
                self.ready = False
                self.team = None
                self.slot = None
                self.auth = None
                self.seed_name = None

                # Location/item state populated by process_server_cmd.
                self.locations_checked = set()
                self.locations_scouted = set()
                self.items_received = []
                self.missing_locations = set()
                self.checked_locations = set()
                self.server_locations = set()
                self.locations_info = {}

                # DataStorage state.
                self.stored_data = {}
                self.stored_data_notification_keys = set()

                # CommonClient interaction/event state.
                self.input_queue = asyncio.Queue()
                self.input_requests = 0
                self.player_names = {0: "Archipelago"}
                self.exit_event = asyncio.Event()
                self.watcher_event = asyncio.Event()

                outer.set_startup_stage("context_name_tables", "Preparing lightweight item/location lookup tables.")
                self.item_names = self.NameLookupDict(self, "item")
                self.location_names = self.NameLookupDict(self, "location")
                self.checksums = {}

                # Text parsers are required for PrintJSON packets.
                self.jsontotextparser = JSONtoTextParser(self)
                self.rawjsontotextparser = RawJSONtoTextParser(self)

                # Avoid CommonContext.update_data_package(network_data_package)
                # here. RoomInfo -> prepare_data_package fetches exactly the
                # games required by the connected multiworld.
                self.keep_alive_task = asyncio.create_task(keep_alive(self), name="WayFinder AP keepalive")
                self.runtime_id = outer.runtime_id
                self.slot_data = {}
                self._room_games = []
                self._game_probe_index = -1
                self._game_probe_active = False
                self._game_probe_token = 0
                outer.set_startup_stage("context_ready", "WayFinder network context created.")

            # /**
            #  * Function: prepare_data_package
            #  * Purpose: Perform the prepare data package operation while keeping the surrounding subsystem state consistent.
            #  * @param relevant_games: Relevant games supplied by the caller; see type hints and call sites for domain constraints.
            #  * @param remote_data_package_checksums: Remote data package checksums supplied by the caller; see type hints and call sites for domain constraints.
            #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
            #  */
            async def prepare_data_package(self, relevant_games, remote_data_package_checksums):
                # Keep the RoomInfo game list. AP requires the correct game name in
                # the Connect packet, but WayFinder intentionally does not
                # know the slot's game until the server accepts the login.
                """Handle prepare data package."""
                self._room_games = sorted(g for g in set(relevant_games) if g and g != "Archipelago")
                await super().prepare_data_package(relevant_games, remote_data_package_checksums)

            # /**
            #  * Function: _send_next_game_probe
            #  * Purpose: Perform the send next game probe operation while keeping the surrounding subsystem state consistent.
            #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
            #  */
            async def _send_next_game_probe(self):
                """Handle send next game probe."""
                if self._wayfinder_manual_disconnect or not self.auth or not getattr(self, "server", None):
                    return
                self._game_probe_index += 1
                if self._game_probe_index >= len(self._room_games):
                    self._game_probe_active = False
                    outer.send_status("recalculating", False)
                    outer.send_log("Could not determine the slot game: every game advertised by RoomInfo was rejected for this slot.")
                    return
                # Variable(s): `candidate` (candidate); named state retained for the surrounding calculation or subsequent calls.
                candidate = self._room_games[self._game_probe_index]
                self.game = candidate
                self._game_probe_active = True
                outer.send_log(f"Trying Archipelago slot game {self._game_probe_index + 1}/{len(self._room_games)}: {candidate}")
                self._game_probe_token += 1
                probe_token = self._game_probe_token
                probe_index = self._game_probe_index
                await self.send_connect(game=candidate)
                outer.send_log(f"Archipelago slot-game probe sent: {candidate}")
                asyncio.create_task(
                    self._watch_game_probe(probe_token, probe_index, candidate),
                    name=f"WayFinder game probe watchdog: {candidate}",
                )

            async def _watch_game_probe(self, probe_token: int, probe_index: int, candidate: str):
                """Prevent a lost InvalidGame response from stalling game discovery forever."""
                await asyncio.sleep(10.0)
                if self._wayfinder_manual_disconnect or not self._game_probe_active:
                    return
                if probe_token != self._game_probe_token or probe_index != self._game_probe_index:
                    return
                if not getattr(self, "server", None):
                    outer.send_log(f"Slot-game probe for {candidate} is waiting for the Archipelago connection to recover.")
                    return
                outer.send_log(
                    f"No response to Archipelago slot-game probe for {candidate} after 10s; trying the next RoomInfo game candidate."
                )
                await self._send_next_game_probe()

            # /**
            #  * Function: server_auth
            #  * Purpose: Perform the server auth operation while keeping the surrounding subsystem state consistent.
            #  * @param password_requested: Password requested supplied by the caller; see type hints and call sites for domain constraints.
            #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
            #  */
            async def server_auth(self, password_requested: bool = False):
                """Handle server auth."""
                if password_requested and not self.password:
                    outer.send_log("Server requires a password; supply it in WayFinder and reconnect.")
                    return
                if not self.auth:
                    return
                self._game_probe_index = -1
                await self._send_next_game_probe()

            # /**
            #  * Function: event_invalid_game
            #  * Purpose: Perform the event invalid game operation while keeping the surrounding subsystem state consistent.
            #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
            #  */
            def event_invalid_game(self):
                # CommonClient can set disconnected_intentionally as part of its
                # InvalidGame handling. That is *not* the same thing as the user
                # pressing WayFinder's Disconnect button. Only our own latch may
                # suppress a late probe response. This restores the working
                # 1/3 -> 2/3 -> 3/3 slot-game discovery sequence.
                """Handle event invalid game."""
                if self._wayfinder_manual_disconnect:
                    return
                self.disconnected_intentionally = False
                # A wrong game is expected while discovering which RoomInfo game
                # belongs to this slot. Do not tear down the websocket; try the
                # next advertised game on the same connection.
                if self._game_probe_active and self._game_probe_index + 1 < len(self._room_games):
                    asyncio.create_task(self._send_next_game_probe())
                    return
                self._game_probe_active = False
                outer.send_status("recalculating", False)
                outer.send_log("Archipelago rejected the slot/game combination; no remaining RoomInfo game candidates are available.")

            # /**
            #  * Function: on_package
            #  * Purpose: Handle the package event or callback.
            #  * @param cmd: Command supplied by the caller; see type hints and call sites for domain constraints.
            #  * @param args: Args supplied by the caller; see type hints and call sites for domain constraints.
            #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
            #  */
            async def send_msgs(self, msgs):
                """Handle send msgs."""
                socket=getattr(getattr(self,'server',None),'socket',None)
                can_send=bool(socket and getattr(socket,'open',True) and not getattr(socket,'closed',False))
                try:
                    result=await super().send_msgs(msgs)
                except Exception as exc:
                    outer.ap_inspector.issue('AP send failed: '+str(exc))
                    raise
                if can_send:
                    for packet in msgs:
                        try:outer.ap_inspector.record('OUT',packet.get('cmd','Unknown'),packet)
                        except Exception as exc:outer.ap_inspector.issue('Inspector could not summarize sent packet: '+str(exc))
                return result

            def on_package(self, cmd: str, args: dict):
                """Handle on package."""
                if cmd == "Connected":
                    self.slot_data = dict(args.get("slot_data", {}) or {})
                    outer.slot_data = self.slot_data
                    try:
                        self.game = self.slot_info[self.slot].game
                    except Exception:
                        self.game = ""
                    self._game_probe_active = False
                    self._game_probe_token += 1
                    outer.send_log(f"Connected to Archipelago as {self.auth} ({self.game}).")
                    outer.world_preparation("authentication",2,10,f"Authenticated slot {self.auth}",game=self.game,slot=self.auth,progress_mode="determinate",progress_current=1,progress_total=1)
                    outer.world_preparation("game_detection",3,10,f"Connected game: {self.game}",game=self.game,slot=self.auth,progress_mode="determinate",progress_current=1,progress_total=1)
                    outer.send_status("ap_connection_state", {"state": "connected", "message": ""})
                    outer._subscribe_hint_storage()
                    outer.transition("CONNECTED","Archipelago authenticated")
                    outer.component_health("AP Server","ready","Authenticated")
                    outer.built=None
                    outer.rebuild_world()
                    outer.publish()
                    outer.send_status("recalculating", False)
                elif cmd in {"ReceivedItems", "RoomUpdate", "LocationInfo", "Retrieved", "SetReply"}:
                    # CommonClient can still be applying the packet-owned state while
                    # on_package is running.  Publishing synchronously here freezes a
                    # context that may still contain the previous checked/item state.
                    # Defer one event-loop turn and coalesce packet bursts so the
                    # snapshot sees the final AP state and drives every GUI surface.
                    outer.queue_live_update(cmd, args)

            # /**
            #  * Function: on_print_json
            #  * Purpose: Handle the print json event or callback.
            #  * @param args: Args supplied by the caller; see type hints and call sites for domain constraints.
            #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
            #  */
            def on_print_json(self, args: dict):
                """Handle on print json."""
                try:
                    # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
                    text = self.jsontotextparser(args.get("data", []))
                except Exception:
                    # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
                    text = str(args.get("data", ""))
                if text:
                    outer.send_log(text)

        # Variable(s): `ctx` (context); named state retained for the surrounding calculation or subsequent calls.
        ctx = WayFinderContext()
        ctx._wayfinder_runtime = self
        self.ctx = ctx
        self._server_loop = server_loop
        return ctx

    # /**
    #  * Function: _subscribe_hint_storage
    #  * Purpose: Subscribe to Archipelago hint DataStorage for every visible slot on the current team.
    #  * @returns: None; subscriptions are registered on the active CommonContext.
    #  */
    def _subscribe_hint_storage(self) -> None:
        """Fetch and watch live hint sets so the Hints tab reflects AP immediately.

        Archipelago stores hints in ``_read_hints_<team>_<slot>`` keys.  Merely
        receiving/printing a Hint PrintJSON packet does not populate
        ``CommonContext.stored_data``; ``set_notify`` is what issues the initial
        Get and keeps the values current.  Watch every normal slot advertised by
        Connected so hints involving other players can also be shown.
        """
        if not self.ctx:
            return
        try:
            team = int(getattr(self.ctx, "team", 0) or 0)
            own_slot = int(getattr(self.ctx, "slot", 0) or 0)
        except Exception:
            team, own_slot = 0, 0

        slot_ids: set[int] = set()
        for raw_slot in (getattr(self.ctx, "slot_info", {}) or {}).keys():
            try:
                slot_id = int(raw_slot)
            except Exception:
                continue
            if slot_id > 0:
                slot_ids.add(slot_id)
        if own_slot > 0:
            slot_ids.add(own_slot)
        if not slot_ids:
            return

        keys = [f"_read_hints_{team}_{slot_id}" for slot_id in sorted(slot_ids)]
        try:
            self.ctx.set_notify(*keys)
            self.send_log(f"Hints DataStorage subscribed for {len(keys)} slot(s) on team {team}.")
        except Exception as exc:
            self.send_log(f"Hint DataStorage subscription failed: {type(exc).__name__}: {exc}")

    # /**
    #  * Function: rebuild_world
    #  * Purpose: Perform the rebuild world operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */

    # /**
    #  * Function: _subscribe_map_page_if_available
    #  * Purpose: Perform the subscribe map page if available operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _subscribe_map_page_if_available(self) -> None:
        """Subscribe to a game-published DataStorage current-map key, if any."""
        if not self.ctx or not self.built:
            return
        # Variable(s): `template` (template); named state retained for the surrounding calculation or subsequent calls.
        template = str(getattr(self.built, "map_page_setting_key", "") or "").strip()
        if not template:
            setattr(self.built, "resolved_map_page_setting_key", "")
            return
        try:
            # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
            key = template.format(player=int(getattr(self.ctx, "slot", 0) or 0), team=int(getattr(self.ctx, "team", 0) or 0))
        except Exception:
            # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
            key = template
        # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
        key = str(key or "").strip()
        setattr(self.built, "resolved_map_page_setting_key", key)
        if not key:
            return
        try:
            self.ctx.set_notify(key)
            self.send_log(f"Live map switching enabled from APWorld DataStorage key: {key}")
        except Exception as exc:
            self.send_log(f"Live map switching capability was advertised but could not be subscribed: {type(exc).__name__}: {exc}")

    # /**
    #  * Function: _subscribe_player_position_if_available
    #  * Purpose: Perform the subscribe player position if available operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _subscribe_player_position_if_available(self) -> None:
        """Subscribe to an APWorld-advertised live player-position key, if any."""
        if not self.ctx or not self.built:
            return
        # Variable(s): `template` (template); named state retained for the surrounding calculation or subsequent calls.
        template = str(getattr(self.built, "player_position_setting_key", "") or "").strip()
        if not template:
            setattr(self.built, "resolved_player_position_setting_key", "")
            return
        try:
            # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
            key = template.format(player=int(getattr(self.ctx, "slot", 0) or 0), team=int(getattr(self.ctx, "team", 0) or 0))
        except Exception:
            # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
            key = template
        # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
        key = str(key or "").strip()
        setattr(self.built, "resolved_player_position_setting_key", key)
        if not key:
            return
        try:
            self.ctx.set_notify(key)
            self.send_log(f"Live player-position support enabled from APWorld DataStorage key: {key}")
        except Exception as exc:
            self.send_log(f"Live player-position capability was advertised but could not be subscribed: {type(exc).__name__}: {exc}")

    # /**
    #  * Function: snapshot
    #  * Purpose: Perform the snapshot operation while keeping the surrounding subsystem state consistent.
    #  * @param refresh_id: Refresh id supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */

    # /**
    #  * Function: publish
    #  * Purpose: Perform the publish operation while keeping the surrounding subsystem state consistent.
    #  * @param refresh_id: Refresh id supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */

    # /**
    #  * Function: ap_version
    #  * Purpose: Perform the ap version operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def ap_version(self) -> str:
        """Handle ap version."""
        try:
            from Utils import __version__
            return str(__version__)
        except Exception:
            return "unknown"

    # /**
    #  * Function: hello
    #  * Purpose: Perform the hello operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def hello(self) -> dict[str, Any]:
        # Variable(s): `ready` (ready); named state retained for the surrounding calculation or subsequent calls.
        """Handle hello."""
        ready = self.startup_stage == "ready" and not self.startup_error
        # Variable(s): `checks` (checks); named state retained for the surrounding calculation or subsequent calls.
        checks = {
            "Native logic engine": "OK" if ready else "Starting",
            "Archipelago core": (f"OK - {self.ap_version()}" if ready else (f"ERROR - {self.startup_error}" if self.startup_error else f"Loading - {self.startup_stage}")),
            "Logic backend": "WayFinder Native",
            "Startup stage": self.startup_stage,
        }
        if self.startup_error:
            checks["Startup error"] = self.startup_error
        return {
            "type": "hello", "ok": True,
            "message": ("WayFinder native tracker runtime ready" if ready else "WayFinder native runtime connected"),
            "protocol_version": PROTOCOL_VERSION, "session_id": self.session_id,
            "capabilities": list(CAPABILITIES),
            "health_state":self.health.current,
            "component_health":dict(self.health.components),
            "self_test":getattr(self,"_self_test_results",{}),
            "checks": checks,
            "engine_version": RUNTIME_VERSION,
            "ap_version": self.ap_version(),
            "integration_version": RUNTIME_VERSION,
        }

    # /**
    #  * Function: send
    #  * Purpose: Perform the send operation while keeping the surrounding subsystem state consistent.
    #  * @param obj: Object supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def send(self, obj: dict[str, Any]) -> None:
        # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
        """Handle send."""
        obj = dict(obj)
        obj.setdefault('session_id', self.session_id)
        obj.setdefault('event_id', uuid.uuid4().hex)
        obj.setdefault('runtime_id', self.runtime_id)
        data = (json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        if len(data) > MAX_MESSAGE_BYTES:
            if obj.get("type")!="error":self.send_error("WF_IPC_TOO_LARGE","Runtime message exceeds IPC size limit",component="IPC")
            return
        with self.client_lock:
            # Variable(s): `sock` (sock); named state retained for the surrounding calculation or subsequent calls.
            sock = self.client
        if not sock:
            return
        try:
            with self.send_lock:
                sock.sendall(data)
        except OSError:
            _ignored("intentional best-effort fallback")

    # /**
    #  * Function: send_log
    #  * Purpose: Perform the send log operation while keeping the surrounding subsystem state consistent.
    #  * @param message: Message supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def send_log(self, message: str) -> None:
        """Handle send log."""
        self.send({"type": "log", "message": sanitize(str(message)), "session_id": self.session_id})

    # /**
    #  * Function: startup_log
    #  * Purpose: Perform the startup log operation while keeping the surrounding subsystem state consistent.
    #  * @param message: Message supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def startup_log(self, message: str) -> None:
        # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
        """Handle startup log."""
        text = sanitize(str(message))
        self.startup_messages.append(text)
        self.startup_messages = self.startup_messages[-50:]
        self.send_log(text)

    # /**
    #  * Function: set_startup_stage
    #  * Purpose: Update startup stage state in a controlled way.
    #  * @param stage: Stage supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param message: Message supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def set_startup_stage(self, stage: str, message: str = "") -> None:
        """Handle set startup stage."""
        self.startup_stage = str(stage)
        if message:
            self.startup_log(message)
        self.send_status("startup_stage", self.startup_stage)

    # /**
    #  * Function: send_status
    #  * Purpose: Perform the send status operation while keeping the surrounding subsystem state consistent.
    #  * @param name: Name supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param value: Value supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def send_status(self, name: str, value: Any) -> None:
        """Handle send status."""
        self.send({"type": "status", "name": name, "value": value, "session_id": self.session_id})

    # /**
    #  * Function: ipc_thread
    #  * Purpose: Perform the ipc thread operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def ipc_thread(self) -> None:
        # Variable(s): `listener` (listener); named state retained for the surrounding calculation or subsequent calls.
        """Handle ipc thread."""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", self.ipc_port))
            listener.listen(1)
            listener.settimeout(0.5)
            self.listener_ready.set()
        except Exception as exc:
            self.listener_error = f"{type(exc).__name__}: {exc}"
            self.listener_ready.set()
            try: listener.close()
            except OSError: _ignored("intentional best-effort fallback")
            return
        while not self.stop.is_set():
            try:
                # Variable(s): `sock` (sock), `_` (_); named state retained for the surrounding calculation or subsequent calls.
                sock, _ = listener.accept()
            except socket.timeout:
                continue
            with self.client_lock:
                if self.client:
                    try: self.client.close()
                    except OSError: _ignored("intentional best-effort fallback")
                self.client = sock
                self.session_id = uuid.uuid4().hex
            self.send(self.hello())
            # Loop variable(s): `message` (message); each iteration represents the next value from the iterable below.
            for message in self.startup_messages:
                self.send_log(message)
            if self.built:
                self.publish()
            self.client_reader(sock)
            with self.client_lock:
                if self.client is sock:
                    self.client = None
        try: listener.close()
        except OSError: _ignored("intentional best-effort fallback")

    # /**
    #  * Function: client_reader
    #  * Purpose: Perform the client reader operation while keeping the surrounding subsystem state consistent.
    #  * @param sock: Sock supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def client_reader(self, sock: socket.socket) -> None:
        """Handle client reader."""
        sock.settimeout(0.5)
        # Variable(s): `buf` (buf); named state retained for the surrounding calculation or subsequent calls.
        buf = bytearray()
        while not self.stop.is_set():
            try:
                # Variable(s): `chunk` (chunk); named state retained for the surrounding calculation or subsequent calls.
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return
            buf.extend(chunk)
            if len(buf) > MAX_MESSAGE_BYTES and b"\n" not in buf:
                return
            while b"\n" in buf:
                # Variable(s): `raw` (raw value), `_` (_), `rest` (rest); named state retained for the surrounding calculation or subsequent calls.
                raw, _, rest = buf.partition(b"\n")
                buf[:] = rest
                if not raw.strip():
                    continue
                try:
                    # Variable(s): `msg` (message); named state retained for the surrounding calculation or subsequent calls.
                    msg = json.loads(raw.decode("utf-8"))
                except Exception:
                    continue
                try:
                    if not isinstance(msg,dict):raise ValueError("IPC command must be an object")
                    self.handle_ipc_message(msg)
                except (ValueError,TypeError,KeyError) as exc:
                    self.send_error("WF_IPC_BAD_REQUEST",str(exc),component="IPC")

    # /**
    #  * Function: handle_ipc_message
    #  * Purpose: Perform the handle ipc message operation while keeping the surrounding subsystem state consistent.
    #  * @param msg: Message supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _datastorage_value_payload(self, key: str, max_items: int = 5000, max_depth: int = 12) -> dict[str, Any]:
        """Return one DataStorage value on demand without adding values to normal snapshots.

        Values can contain sets/tuples or other Archipelago objects that are not
        directly JSON serializable.  Convert only the requested value into a
        bounded JSON-safe representation so the metadata index remains cheap.
        """
        stored_data = getattr(self.ctx, "stored_data", {}) or {} if self.ctx is not None else {}
        if key not in stored_data:
            return {"key": key, "found": False, "error": "DataStorage key is not currently available."}

        remaining = [max(1, int(max_items))]
        truncated = [False]

        def convert(value: Any, depth: int = 0) -> Any:
            """Handle convert."""
            if depth > max_depth:
                truncated[0] = True
                return "<maximum depth reached>"
            if value is None or isinstance(value, (bool, int, float, str)):
                return value
            if isinstance(value, bytes):
                return value.hex()
            if remaining[0] <= 0:
                truncated[0] = True
                return "<value truncated>"
            if isinstance(value, dict):
                result: dict[str, Any] = {}
                for child_key, child_value in value.items():
                    if remaining[0] <= 0:
                        truncated[0] = True
                        break
                    remaining[0] -= 1
                    result[str(child_key)] = convert(child_value, depth + 1)
                return result
            if isinstance(value, (list, tuple, set, frozenset)):
                result_list: list[Any] = []
                sequence = value
                if isinstance(value, (set, frozenset)):
                    try:
                        sequence = sorted(value, key=lambda item: str(item).casefold())
                    except Exception:
                        sequence = list(value)
                for child_value in sequence:
                    if remaining[0] <= 0:
                        truncated[0] = True
                        break
                    remaining[0] -= 1
                    result_list.append(convert(child_value, depth + 1))
                return result_list
            try:
                return str(value)
            except Exception:
                return f"<{type(value).__name__}>"

        raw_value = stored_data[key]
        value = convert(raw_value)
        return {
            "key": key,
            "found": True,
            "value_type": type(raw_value).__name__,
            "value": value,
            "truncated": truncated[0],
        }

    def handle_ipc_message(self, msg: dict[str, Any]) -> None:
        """Handle handle ipc message."""
        try:
            # Variable(s): `version` (version); named state retained for the surrounding calculation or subsequent calls.
            version = int(msg.get("protocol_version", PROTOCOL_VERSION))
        except Exception:
            # Variable(s): `version` (version); named state retained for the surrounding calculation or subsequent calls.
            version = -1
        if not (PROTOCOL_MIN <= version <= PROTOCOL_MAX):
            self.send(error_payload("bad_protocol", f"Unsupported protocol {version}"))
            return
        # Variable(s): `cmd` (command); named state retained for the surrounding calculation or subsequent calls.
        cmd = str(msg.get("cmd", ""))
        if msg.get('session_id') and msg['session_id']!=self.session_id:
            self.send_error('WF_IPC_STALE_SESSION','Obsolete IPC session',component='IPC');return
        if cmd == "ping":
            self.send({"type": "pong", "session_id": self.session_id, "health": self.jobs.status(), "runtime_state": self.health.current, "components": self.health.components})
        elif cmd == "ap_inspect":
            if self.loop and self.loop.is_running():
                self.schedule(self.inspector_request(msg))
            else:
                self.send_status('ap_inspector_error',dict(id=msg.get('id',0),message='Native runtime is not ready'))
        elif cmd == "refresh":
            # Variable(s): `refresh_id` (refresh id); named state retained for the surrounding calculation or subsequent calls.
            refresh_id = int(msg.get("refresh_id", 0) or 0)
            self.send_status("refresh_status", {"id": refresh_id, "state": "running", "message": "Publishing current native state"})
            self.send_status("refresh_phase", {"id": refresh_id, "phase": "snapshot"})
            self.publish(refresh_id)
        elif cmd == "cancel":
            self.jobs.cancel()
            self.transition("DEGRADED","Expensive jobs cancelled; last valid state retained")
            self.send_status("recalculating",False)
        elif cmd == "connect":
            self.jobs.cancel(); self.connection_id=str(msg.get('connection_id') or uuid.uuid4().hex)
            self.schedule(self.connect_ap(str(msg.get("server", "")), str(msg.get("slot_name", "")), str(msg.get("password", ""))))
        elif cmd == "disconnect":
            self.jobs.cancel()
            self.connection_id=str(msg.get('connection_id') or self.connection_id)
            self.schedule(self.disconnect_ap())
        elif cmd == "set_ignored":
            raw_names = msg.get("names", [])
            self.ignored_names = {str(name).strip() for name in raw_names if str(name).strip()} if isinstance(raw_names, list) else set()
            self.publish()
        elif cmd == "ignore":
            self.ignored_names.add(str(msg.get("name", ""))); self.publish()
        elif cmd == "unignore":
            self.ignored_names.discard(str(msg.get("name", ""))); self.publish()
        elif cmd == "console":
            self.schedule(self.console(str(msg.get("text", ""))))
        elif cmd == "datastorage_value":
            key = str(msg.get("key", ""))
            req = int(msg.get("id", 0) or 0)
            self.send({
                "type": "datastorage_value",
                "id": req,
                "session_id": self.session_id,
                "data": self._datastorage_value_payload(key),
            })
        elif cmd == "path":
            # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
            target = str(msg.get("target", "")); req = int(msg.get("id", 0) or 0)
            self.queue_path(target,req)
        elif cmd == "shutdown":
            self.stop.set()
            if self.ctx: self.schedule(self.ctx.shutdown())
        else:
            self.send(error_payload("bad_command", f"Unknown runtime command: {cmd}"))

    # /**
    #  * Function: schedule
    #  * Purpose: Perform the schedule operation while keeping the surrounding subsystem state consistent.
    #  * @param coro: Coro supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def schedule(self, coro) -> None:
        """Handle schedule."""
        if self.loop and not self.loop.is_closed():
            asyncio.run_coroutine_threadsafe(coro, self.loop)

    # /**
    #  * Function: connect_ap
    #  * Purpose: Perform the connect ap operation while keeping the surrounding subsystem state consistent.
    #  * @param server: Server supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param slot: Slot supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param password: Password supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    async def connect_ap(self, server: str, slot: str, password: str) -> None:
        """Handle connect ap."""
        register_secret(password)
        if self.ctx is None:
            self.send_log("Cannot connect to Archipelago because the native runtime failed to initialize: " + (self.startup_error or "context unavailable"))
            return
        if not server or not slot:
            self.send_log("Server and slot name are required.")
            return

        # A Connect starts a fresh AP session, but must not route a pristine
        # startup/reconnect through the *manual* Disconnect path.  v0.10.3 did
        # that when a CommonContext default/class-level server_task was visible,
        # which latched the context disconnected just as login began.
        # Only instance-owned values count as an existing WayFinder session.
        # CommonContext exposes class/default transport attributes before the
        # first connection; treating those as live caused v0.10.3/0.10.4 to
        # disconnect a pristine startup.  Conversely, shadowing them in the
        # context broke AP's normal game-probe handshake in v0.10.5.
        # Variable(s): `ctx_dict` (ctx dict); named state retained for the surrounding calculation or subsequent calls.
        ctx_dict = getattr(self.ctx, "__dict__", {})
        # Variable(s): `current_task` (current task); named state retained for the surrounding calculation or subsequent calls.
        current_task = ctx_dict.get("server_task")
        # Variable(s): `task_is_live` (task is live); named state retained for the surrounding calculation or subsequent calls.
        task_is_live = current_task is not None and not current_task.done()
        # Variable(s): `has_live_connection` (has live connection); named state retained for the surrounding calculation or subsequent calls.
        has_live_connection = bool(ctx_dict.get("server")) or task_is_live

        # Startup already asks the runtime to connect from WF_INITIAL_* before
        # the GUI receives its first snapshot.  A second Connect command for the
        # same target can arrive while that first login is still probing the
        # slot's game.  Treat that as an idempotent duplicate, never as a request
        # to tear down the in-flight connection.  v0.10.4 interpreted the
        # duplicate as an old session and called disconnect_ap(), producing the
        # observed Connect -> Disconnect -> reconnect loop.
        # Variable(s): `current_address` (current address); named state retained for the surrounding calculation or subsequent calls.
        current_address = str(getattr(self.ctx, "server_address", "") or "").strip()
        # Variable(s): `current_auth` (current auth); named state retained for the surrounding calculation or subsequent calls.
        current_auth = str(getattr(self.ctx, "auth", "") or "").strip()
        # Variable(s): `same_server` (same server); named state retained for the surrounding calculation or subsequent calls.
        same_server = current_address.casefold().removeprefix("ws://").removeprefix("wss://") == str(server).strip().casefold().removeprefix("ws://").removeprefix("wss://")
        # Variable(s): `same_slot` (same slot); named state retained for the surrounding calculation or subsequent calls.
        same_slot = current_auth.casefold() == str(slot).strip().casefold()
        if has_live_connection and same_server and same_slot:
            self.send_log(f"Connection to {server} as {slot} is already active/in progress; ignoring duplicate Connect request.")
            return

        if has_live_connection:
            await self.disconnect_ap(publish=False)

        # Re-arm connection state only after any genuinely live old session has
        # finished cleanup.  Explicitly set all fields used by the AP auth path.
        self.jobs.cancel(); self.built=None; self.ignored_names.clear(); self.last_snapshot={}
        self.transition("CONNECTING","Connecting to Archipelago")
        self.component_health("AP Server","busy","Connecting")
        self.ctx._wayfinder_manual_disconnect = False
        self.ctx.disconnected_intentionally = False
        self.ctx.server_address = server
        self.ctx.auth = slot
        self.ctx.password = password or None
        self.ctx.server_task = asyncio.create_task(self._server_loop(self.ctx, server), name="WayFinder AP server loop")
        self.send_status("ap_connection_state", {"state": "connecting", "message": "Connecting to Archipelago…"})
        self.world_preparation("connection",1,10,"Connecting to server",game="",slot=slot,progress_mode="indeterminate")
        asyncio.create_task(self._watch_initial_archipelago_connection(server), name="WayFinder AP connection grace monitor")
        # A late connection_closed callback from an older session must never
        # leave a newly-started manual/automatic Connect in intentional-disconnect
        # mode.  The new task/address/auth are now authoritative.
        self.ctx.disconnected_intentionally = False
        self.send_status("recalculating", True)

    async def _watch_initial_archipelago_connection(self, server: str) -> None:
        """Report a slow initial connection without guessing that the room is asleep.

        A missing ``ctx.server`` shortly after Connect only means that the
        websocket handshake has not completed yet. CommonClient owns retries,
        so this monitor is deliberately informational and never degrades the
        runtime merely because a short grace period elapsed.
        """
        await asyncio.sleep(3.0)
        ctx = self.ctx
        if ctx is None or getattr(ctx, "_wayfinder_manual_disconnect", False):
            return
        if str(getattr(ctx, "server_address", "") or "").strip() != str(server).strip():
            return
        if getattr(ctx, "server", None):
            return
        message = "Still connecting to Archipelago; waiting for the websocket handshake. Automatic retry remains active."
        self.component_health("AP Server", "busy", "Connection handshake pending")
        self.send_status("ap_connection_state", {"state": "connecting", "message": message})
        self.send_log(message)

    # /**
    #  * Function: disconnect_ap
    #  * Purpose: Perform the disconnect ap operation while keeping the surrounding subsystem state consistent.
    #  * @param publish: Publish supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    async def disconnect_ap(self, *, publish: bool = True) -> None:
        """Disconnect from Archipelago without stopping the WayFinder runtime.

        CommonClient normally preserves ``server_address`` so a dropped
        connection can automatically reconnect.  A user pressing Disconnect is
        different: it must be a hard, intentional AP disconnect and must not
        immediately reconnect in the background.
        """
        if not self.ctx:
            return

        # Variable(s): `ctx` (context); named state retained for the surrounding calculation or subsequent calls.
        ctx = self.ctx
        # Set a WayFinder-owned latch before touching CommonClient transport
        # state. This is the authoritative signal used to ignore late
        # InvalidGame callbacks after a real manual disconnect.
        ctx._wayfinder_manual_disconnect = True
        self.send_log("Disconnecting from Archipelago…")
        self.send_status("ap_connection_state", {"state": "disconnected", "message": ""})

        # Set the latch *before* closing the websocket.  server_loop checks it in
        # its finally block when deciding whether to spawn server_autoreconnect.
        ctx.disconnected_intentionally = True
        try:
            ctx.cancel_autoreconnect()
        except Exception:
            _ignored("intentional best-effort fallback")

        # Clearing the saved runtime address provides a second guard against the
        # CommonClient auto-reconnect path.  WayFinder keeps the user's server
        # field, so a later manual Connect can restore it normally.
        ctx.server_address = ""

        # Capture the active connection loop before CommonClient mutates its
        # bookkeeping.  A graceful disconnect closes the websocket, but some AP
        # core versions leave server_loop alive; that loop can immediately open
        # the same address again.  Manual Disconnect must terminate that loop.
        # Variable(s): `connection_task` (connection task); named state retained for the surrounding calculation or subsequent calls.
        connection_task = getattr(ctx, "server_task", None)
        try:
            await ctx.disconnect()
        except Exception as exc:
            self.send_log(f"Archipelago disconnect reported {type(exc).__name__}: {exc}")

        # Always cancel the connection loop after the graceful close, not only on
        # exceptions.  This is the important difference between a network drop
        # (where AP auto-reconnect is desirable) and the user's Disconnect button.
        # Loop variable(s): `task` (task); each iteration represents the next value from the iterable below.
        for task in (connection_task, getattr(ctx, "server_task", None)):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    _ignored("intentional best-effort fallback")
        ctx.server_task = None
        try:
            if getattr(ctx, "server", None) and getattr(ctx.server, "socket", None):
                await ctx.server.socket.close()
        except Exception:
            _ignored("intentional best-effort fallback")
        ctx.server = None
        # Reassert these after disconnect/cancellation because CommonClient's
        # cleanup callbacks may have changed them while the socket was closing.
        ctx.disconnected_intentionally = True
        ctx.server_address = ""
        try:
            ctx.cancel_autoreconnect()
        except Exception:
            _ignored("intentional best-effort fallback")

        # CommonClient normally clears these in connection_closed(), but make the
        # user-visible state deterministic even if the transport was already
        # half-closed when Disconnect was pressed.
        try:
            ctx.reset_server_state()
        except Exception:
            ctx.server = None
            ctx.server_task = None
            ctx.auth = None
            ctx.slot = None
            ctx.team = None
        try:
            ctx.reset_session_state()
        except Exception:
            _ignored("intentional best-effort fallback")

        # The lightweight WayFinder context is intentionally not constructed via
        # CommonContext.__init__, and AP core versions differ in which fields
        # reset_* clears. Explicitly clear every identity/session field used by
        # snapshot.connected and by the GUI. This makes the disconnected snapshot
        # unambiguously disconnected instead of looking connected because an old
        # slot number survived cleanup.
        ctx.server = None
        ctx.server_task = None
        ctx.server_address = ""
        ctx.auth = None
        ctx.username = None
        ctx.slot = None
        ctx.team = None
        ctx.game = ""
        ctx.seed_name = None
        ctx._game_probe_active = False
        ctx._game_probe_index = -1
        ctx.disconnected_intentionally = True

        self.built = None
        self.slot_data = {}
        self.send_status("recalculating", False)
        self.send_log("Disconnected from Archipelago. WayFinder runtime remains ready for a manual reconnect.")
        if publish:
            self.publish()

    # /**
    #  * Function: console
    #  * Purpose: Perform the console operation while keeping the surrounding subsystem state consistent.
    #  * @param text: Text supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    async def console(self, text: str) -> None:
        # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
        """Handle console."""
        text = (text or "").strip()
        if not text:
            return
        # Variable(s): `lower` (lower); named state retained for the surrounding calculation or subsequent calls.
        lower = text.lower()
        if lower in {"/wfstatus", "/logic"}:
            # Variable(s): `snap` (snap); named state retained for the surrounding calculation or subsequent calls.
            snap = self.snapshot()
            self.send_log(f"[WayFinder] {snap.get('game') or 'Not connected'}: {len(snap.get('normal_reachable_locations', []))} reachable, {snap.get('checked_count', 0)} checked, {snap.get('missing_count', 0)} remaining.")
            return
        if lower == "/start":
            # Variable(s): `snap` (snap); named state retained for the surrounding calculation or subsequent calls.
            snap = self.snapshot(); self.send_log(f"[WayFinder] Starting Location: {snap.get('starting_location') or 'not resolved'}")
            return
        if lower == "/slotdata":
            self.send_log("[WayFinder] Slot Data: " + json.dumps(self.slot_data, sort_keys=True, ensure_ascii=False))
            return
        if lower in {"/wfhelp", "/help"}:
            self.send_log("WayFinder commands: /start /slotdata /logic /wfstatus /wfhelp")
            return
        if getattr(self.ctx, "server", None):
            await self.ctx.send_msgs([{"cmd": "Say", "text": text}])

    # /**
    #  * Function: path_result
    #  * Purpose: Perform the path result operation while keeping the surrounding subsystem state consistent.
    #  * @param target: Target supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def path_result(self, target: str) -> dict[str, Any]:
        """Build a real generated-graph route from the APWorld origin to a location."""
        # Variable(s): `snap` (snap); named state retained for the surrounding calculation or subsequent calls.
        snap = self.snapshot(); row = next((x for x in snap.get("locations", []) if x.get("name") == target), None)
        event_row = next((x for x in snap.get("event_details", []) if isinstance(x,dict) and x.get("name") == target), None)
        if row is None and event_row is not None:
            event_region=str(event_row.get("region","") or "")
            region_reachable=event_region in set(snap.get("in_logic_regions",[]) or [])
            event_satisfied=bool(event_row.get("satisfied",False))
            event_swept=bool(event_row.get("swept",False))
            row={
                "name":target,"region":event_region,"event":True,
                "status":"checked" if event_swept else "unknown" if event_row.get('error') else ("reachable" if region_reachable and event_satisfied else "out_of_logic"),
                "unknown_reason":('Logic evaluation failed: ' + event_row['error']) if event_row.get('error') else '',
            }
        if not row or self.built is None:
            return {"target": target, "found": False, "reachable": False, "error": "Location/event not found in reconstructed APWorld.", "steps": []}
        # Variable(s): `world` (world); named state retained for the surrounding calculation or subsequent calls.
        world=self.built.world; origin=str(getattr(world,"origin_region_name","") or "Menu"); target_region=str(row.get("region","") or "")
        # Variable(s): `edges` (edges); named state retained for the surrounding calculation or subsequent calls.
        edges=snap.get("entrance_details",[]) or []; adjacency={}
        # Loop variable(s): `d` (d); each iteration represents the next value from the iterable below.
        for d in edges: adjacency.setdefault(str(d.get("source_region","")),[]).append(d)
        # Prefer currently satisfied routes, then fewer transitions. If the target
        # is blocked, fall back to a structural route so missing requirements can
        # still be displayed in red rather than returning an empty path.
        from collections import deque
        # /**
        #  * Function: find_route
        #  * Purpose: Locate route using the available runtime data.
        #  * @param allow_blocked: Allow blocked supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        def find_route(allow_blocked=False):
            # Variable(s): `q` (q); named state retained for the surrounding calculation or subsequent calls.
            """Return find route."""
            q=deque([(origin,[])]); seen={origin}
            while q:
                # Variable(s): `region` (region), `path` (path); named state retained for the surrounding calculation or subsequent calls.
                region,path=q.popleft()
                if region==target_region:return path
                # Variable(s): `candidates` (candidates); named state retained for the surrounding calculation or subsequent calls.
                candidates=sorted(adjacency.get(region,[]),key=lambda d:(not bool(d.get("reachable")),str(d.get("name",""))))
                # Loop variable(s): `d` (d); each iteration represents the next value from the iterable below.
                for d in candidates:
                    if not allow_blocked and not d.get("reachable"): continue
                    # Variable(s): `nxt` (nxt); named state retained for the surrounding calculation or subsequent calls.
                    nxt=str(d.get("target_region","") or "")
                    if nxt and nxt not in seen: seen.add(nxt); q.append((nxt,path+[d]))
            return None
        # Variable(s): `route` (route); named state retained for the surrounding calculation or subsequent calls.
        route=find_route(False); structural=False
        # Variable(s): `route` (route); named state retained for the surrounding calculation or subsequent calls.
        if route is None: route=find_route(True); structural=True
        # Variable(s): `steps` (steps); named state retained for the surrounding calculation or subsequent calls.
        steps=[]
        if route is not None:
            steps.append({"kind":"region","title":origin,"reachable":True,"source_region":origin,"target_region":origin,"tokens":[]})
            # Loop variable(s): `d` (d); each iteration represents the next value from the iterable below.
            for d in route:
                # A traced rule can contain false comparisons inside a successful
                # negation (for example ``not level < 5``).  Normalise the
                # flattened display rows before building tokens/tree so the
                # visible count, colour and operator all agree with the AP rule.
                display_consulted=_normalise_consulted_for_display(d.get("consulted",[]) or [], bool(d.get("satisfied")))
                # Variable(s): `tokens` (tokens); named state retained for the surrounding calculation or subsequent calls.
                tokens=[]
                # Loop variable(s): `x` (horizontal x-coordinate); each iteration represents the next value from the iterable below.
                for x in display_consulted:
                    tokens.append({"kind":x.get("kind","rule"),"text":x.get("name",""),"satisfied":bool(x.get("result")),"detail":x.get("detail",""),**{k:x[k] for k in ("have","required","operator") if k in x}})
                steps.append({"kind":"entrance","title":d.get("name",""),"reachable":bool(d.get("reachable")),"source_region":d.get("source_region",""),"target_region":d.get("target_region",""),"tokens":tokens,"tree":{"kind":"and","label":"Entrance requirements","satisfied":bool(d.get("satisfied")),"detail":d.get("module",""),"children":[{"kind":x.get("kind","rule"),"label":x.get("name",""),"satisfied":bool(x.get("result")),"detail":x.get("detail",""),**{k:x[k] for k in ("have","required","operator") if k in x}} for x in display_consulted]}})
        # Variable(s): `rule` (rule); named state retained for the surrounding calculation or subsequent calls.
        rule=event_row if event_row is not None and bool(row.get("event")) else (snap.get("rule_details",{}) or {}).get(target,{})
        step_kind="event" if bool(row.get("event")) else "location"
        requirement_label="Event requirements" if step_kind=="event" else "Location requirements"
        target_satisfied=bool(rule.get("satisfied",row.get("status") in {"reachable","checked"}))
        from wayfinder.logic.rule_explanation import display_tree
        for step in steps:
            if step.get('kind') == 'entrance':
                match = next((x for x in edges if x.get('name') == step.get('title')), None)
                if match and match.get('normalized_rule'):
                    step['tree'] = display_tree(match)
        target_display_consulted=_normalise_consulted_for_display(rule.get("consulted",[]) or [], target_satisfied)
        steps.append({"kind":step_kind,"title":target,"reachable":row.get("status") in {"reachable","glitched","checked"},"source_region":target_region,"target_region":target_region,"tokens":[{"kind":x.get("kind","rule"),"text":x.get("name",""),"satisfied":bool(x.get("result")),"detail":x.get("detail",""),**{k:x[k] for k in ("have","required","operator") if k in x}} for x in target_display_consulted],"tree":{"kind":"and","label":requirement_label,"satisfied":target_satisfied,"detail":rule.get("module",""),"children":[{"kind":x.get("kind","rule"),"label":x.get("name",""),"satisfied":bool(x.get("result")),"detail":x.get("detail",""),**{k:x[k] for k in ("have","required","operator") if k in x}} for x in target_display_consulted]}})
        # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
        status=row.get("status"); reachable=status in {"reachable","glitched","checked"}
        if rule.get('normalized_rule'):
            steps[-1]['tree'] = display_tree(rule)
        return {"target":target,"found":True,"reachable":reachable,"using_glitches":status=="glitched","error":row.get("unknown_reason","") or ("No structural route from APWorld origin was found." if route is None else ""),"updated_at":snap.get("updated_at",""),"compatibility":{"backend":"WayFinder Native","route":"structural with blocked requirements" if structural else "reachable APWorld graph"},"steps":steps}

    # /**
    #  * Function: run
    #  * Purpose: Perform the run operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    async def run(self) -> None:
        # Bring IPC up before importing Archipelago.  If AP startup fails, the GUI
        # can still connect and receive the exact exception instead of timing out.
        """Handle run."""
        self.set_startup_stage("starting_ipc")
        threading.Thread(target=self.ipc_thread, name="WayFinder-Native-IPC", daemon=True).start()
        await asyncio.to_thread(self.listener_ready.wait, 5.0)
        if self.listener_error:
            raise RuntimeError(f"Native IPC listener failed: {self.listener_error}")
        if not self.listener_ready.is_set():
            raise RuntimeError("Native IPC listener did not become ready within 5 seconds")

        try:
            self.set_startup_stage("loading_archipelago_core", f"Loading Archipelago core from: {self.ap_root}")
            self.bootstrap_ap()
            self.set_startup_stage("creating_archipelago_context", "Archipelago core imported; creating WayFinder client context.")
            self._make_context()
            self.startup_self_test()
            self.send_status("live_context", "attached")
            # Variable(s): `initial_server` (initial server); named state retained for the surrounding calculation or subsequent calls.
            initial_server = str(os.environ.get("WF_INITIAL_SERVER", "") or "").strip()
            # Variable(s): `initial_slot` (initial slot); named state retained for the surrounding calculation or subsequent calls.
            initial_slot = str(os.environ.get("WF_INITIAL_SLOT", "") or "").strip()
            # Variable(s): `initial_password` (initial password); named state retained for the surrounding calculation or subsequent calls.
            initial_password = str(os.environ.get("WF_INITIAL_PASSWORD", "") or "")
            if initial_server and initial_slot:
                self.set_startup_stage("connecting_archipelago", f"Native runtime context ready; connecting to {initial_server} as {initial_slot}.")
                await self.connect_ap(initial_server, initial_slot, initial_password)
                self.set_startup_stage("ready", "WayFinder native runtime is ready; Archipelago connection requested automatically.")
            else:
                # Variable(s): `missing` (missing); named state retained for the surrounding calculation or subsequent calls.
                missing = []
                if not initial_server:
                    missing.append("server")
                if not initial_slot:
                    missing.append("slot name")
                self.set_startup_stage("ready", "WayFinder native runtime is ready; waiting for Archipelago connection details (missing: " + ", ".join(missing) + ").")
        except Exception as exc:
            self.startup_error = f"{type(exc).__name__}: {exc}"
            self.transition("ERROR","Startup self-test or initialization failed")
            self.send_error("WF_STARTUP_FAILED",self.startup_error,recoverable=False)
            self.set_startup_stage("startup_failed", f"NATIVE RUNTIME STARTUP FAILED: {self.startup_error}")

        while not self.stop.is_set():
            await asyncio.sleep(0.2)
            ctx=self.ctx
            live=bool(ctx and getattr(ctx,'server',None) and getattr(ctx,'slot',None))
            if getattr(self,'_network_was_connected',False) and not live and not getattr(ctx,'_wayfinder_manual_disconnect',False):
                self.component_health('AP Server','degraded','Connection lost; automatic retry continues')
                self.transition('DEGRADED','AP connection lost')
                self.send_status('state_stale',dict(stale=True,reason='AP connection lost; waiting for reconnect'))
            self._network_was_connected=live
        self.jobs.close()
        if self.ctx:
            try: await self.ctx.shutdown()
            except Exception: _ignored("intentional best-effort fallback")


# /**
#  * Function: run_runtime
#  * Purpose: Perform the run runtime operation while keeping the surrounding subsystem state consistent.
#  * @param runtime_port: Runtime port supplied by the caller; see type hints and call sites for domain constraints.
#  * @param ap_root: Ap root supplied by the caller; see type hints and call sites for domain constraints.
#  * @param players_path: Players path supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def run_runtime(runtime_port: int, ap_root: str, players_path: str = "") -> None:
    # Variable(s): `runtime` (runtime); named state retained for the surrounding calculation or subsequent calls.
    """Handle run runtime."""
    runtime = NativeRuntime(runtime_port, ap_root, players_path)
    # Variable(s): `loop` (loop); named state retained for the surrounding calculation or subsequent calls.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    runtime.loop = loop
    loop.run_until_complete(runtime.run())
