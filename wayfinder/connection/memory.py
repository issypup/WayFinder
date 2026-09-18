"""Provide memory support."""
# /**
#  * Module: wayfinder.app/connection_memory.py
#  * Purpose: GUI module for connection memory; presents or coordinates WayFinder state without owning the underlying game logic.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored
import json, os, re, shutil
from pathlib import Path
from typing import Any
from wayfinder.storage import app_data_root

# Constant(s): `START_KEYS`; shared configuration value(s) intentionally kept stable within this module.
START_KEYS = (
    'starting_location','start_location','starting_area','start_area','starting_region','start_region',
    'spawn_location','spawn_area','spawn_region','starting_map','start_map','origin_map','initial_region'
)
# Constant(s): `UNRESOLVED`; shared configuration value(s) intentionally kept stable within this module.
UNRESOLVED = {'', 'random', 'randomized', 'randomised', 'any', 'none', 'default'}

# Some APWorlds expose the resolved start in slot_data using a numeric value,
# a non-standard option key, or another game-specific representation. Keep
# those exceptions here so the generic tracker/GUI does not have to guess.
# Add new worlds only when their APWorld clearly documents the slot_data field.
# Constant(s): `START_CAVEATS`; shared configuration value(s) intentionally kept stable within this module.
START_CAVEATS: dict[str, dict[str, Any]] = {
    'little witch nobeta': {
        'keys': ('starting_area',),
        'values': {0: 'Shrine', 1: 'Underground', 2: 'Lava Ruins', 3: 'Dark Tunnel'},
    },
    'mina the hollower': {
        # Mina does not use a generic "starting_area" key. ossex_start selects
        # between its two generated origins, and ability randomization may force it.
        'keys': ('ossex_start',),
        'values': {False: "Loner's Landing", True: 'Ossex City Center', 0: "Loner's Landing", 1: 'Ossex City Center'},
    },
    'flipwitch forbidden sex hex': {
        'keys': ('starting_area',),
        'values': {
            0: "Beatrice's House", 1: 'Goblin Cave', 2: 'Spirit City', 3: 'Ghost Castle',
            4: 'Jigoku', 5: 'Club Demon', 6: 'Tengoku', 7: 'Slime Citadel', 8: 'Umi Umi',
        },
    },
    'sonic adventure dx': {
        # SADX sends the *resolved* generated StartingArea separately from the
        # player's StartingLocationOption, so prefer StartingArea.
        'keys': ('StartingArea',),
        'values': {
            0: 'City Hall', 1: 'Station', 2: 'Casino', 3: 'Sewers', 4: 'Station Square Main',
            5: 'Twinkle Park Tunnel', 6: 'Hotel', 7: 'Hotel Pool', 8: 'Twinkle Park Lobby',
            9: 'Mystic Ruins Main', 10: 'Angel Island', 11: 'Ice Cave', 12: 'Past Altar',
            13: 'Past Main', 14: 'Jungle', 15: 'Final Egg Tower', 16: 'Egg Carrier Outside',
            17: 'Egg Carrier Bridge', 18: 'Egg Carrier Deck', 19: "Captain's Room", 20: 'Private Room',
            21: 'Egg Carrier Pool', 22: 'Arsenal', 23: 'Egg Carrier Inside', 24: 'Hedgehog Hammer',
            25: 'Prison Hall', 26: 'Water Tank', 27: 'Warp Hall', 28: 'Station Square Chao Garden',
            29: 'Mystic Ruins Chao Garden', 30: 'Egg Carrier Chao Garden', 31: 'Emerald Coast',
            32: 'Windy Valley', 33: 'Casinopolis', 34: 'Ice Cap', 35: 'Twinkle Park',
            36: 'Speed Highway', 37: 'Red Mountain', 38: 'Sky Deck', 39: 'Lost World',
            40: 'Final Egg', 41: 'Hot Shelter', 42: 'Chaos 0', 43: 'Egg Walker', 44: 'Chaos 2',
            45: 'Twinkle Circuit', 46: 'Chaos 4', 47: 'Egg Hornet', 48: 'Sky Chase 1',
            49: 'Sand Hill', 50: 'Beta Egg Viper', 51: 'Sky Chase 2', 52: 'Chaos 6 / Zero / Beta',
        },
    },
    'hitman world of assassination': {
        'keys': ('starting_location',),
        'values': {
            0: 'ICA Facility', 1: 'Paris', 2: 'Sapienza', 3: 'Marrakesh', 4: 'Bangkok',
            5: 'Colorado', 6: 'Hokkaido', 7: "Hawke's Bay", 8: 'Miami', 9: 'Santa Fortuna',
            10: 'Mumbai', 11: 'Whittleton Creek', 12: 'Isle of Sgail', 13: 'New York',
            14: 'Haven Island', 15: 'Dubai', 16: 'Dartmoor', 17: 'Berlin', 18: 'Chongqing',
            19: 'Mendoza', 20: 'Carpathian Mountains', 21: 'Ambrose Island',
        },
    },
}

# Games where we want an explicit diagnostic line on Connected even when the
# generic resolver is sufficient.  This keeps game-specific slot-data behaviour
# visible in Diagnostics / Error Console without making every game a caveat.
# Constant(s): `START_DIAGNOSTICS`; shared configuration value(s) intentionally kept stable within this module.
START_DIAGNOSTICS: dict[str, dict[str, Any]] = {
    'little witch nobeta': {'label': 'Little Witch Nobeta', 'keys': ('starting_area',), 'mode': 'caveat'},
    'mina the hollower': {'label': 'Mina The Hollower', 'keys': ('ossex_start',), 'mode': 'caveat'},
    'flipwitch forbidden sex hex': {'label': 'Flipwitch Forbidden Sex Hex', 'keys': ('starting_area',), 'mode': 'caveat'},
    'sonic adventure dx': {'label': 'Sonic Adventure DX', 'keys': ('StartingArea',), 'mode': 'caveat'},
    'hitman world of assassination': {'label': 'HITMAN World of Assassination', 'keys': ('starting_location',), 'mode': 'caveat'},
    'powerwash simulator': {'label': 'Powerwash Simulator', 'keys': ('starting_location',), 'mode': 'generic'},
}


# /**
#  * Function: start_keys_for_game
#  * Purpose: Perform the start keys for game operation while keeping the surrounding subsystem state consistent.
#  * @param game: Game supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def start_keys_for_game(game: str = '') -> tuple[str, ...]:
    """Return authoritative server start keys for this game, then generic fallbacks."""
    # Variable(s): `caveat` (caveat); named state retained for the surrounding calculation or subsequent calls.
    caveat=START_CAVEATS.get(str(game or '').strip().casefold())
    # Variable(s): `ordered` (ordered); named state retained for the surrounding calculation or subsequent calls.
    ordered=[]
    if caveat:
        ordered.extend(caveat.get('keys', ()) or ())
    ordered.extend(START_KEYS)
    # Variable(s): `seen` (seen); named state retained for the surrounding calculation or subsequent calls.
    seen=set(); result=[]
    # Loop variable(s): `key` (key); each iteration represents the next value from the iterable below.
    for key in ordered:
        # Variable(s): `folded` (folded); named state retained for the surrounding calculation or subsequent calls.
        folded=_fold_key(key)
        if folded in seen:
            continue
        seen.add(folded); result.append(str(key))
    return tuple(result)


# /**
#  * Function: find_option_attribute
#  * Purpose: Locate option attribute using the available runtime data.
#  * @param options: Options supplied by the caller; see type hints and call sites for domain constraints.
#  * @param candidate: Candidate supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def find_option_attribute(options: Any, candidate: str) -> str | None:
    """Find an option attribute matching a slot-data key, case/punctuation-insensitively."""
    if options is None:
        return None
    if hasattr(options, candidate):
        return candidate
    # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
    target=_fold_key(candidate)
    try:
        # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
        names=vars(options).keys()
    except Exception:
        # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
        names=dir(options)
    # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
    for name in names:
        if str(name).startswith('_'):
            continue
        if _fold_key(name) == target and hasattr(options, name):
            return str(name)
    return None


# /**
#  * Function: app_data_root
#  * Purpose: Perform the app data root operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
# /**
#  * Function: memory_path
#  * Purpose: Perform the memory path operation while keeping the surrounding subsystem state consistent.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def memory_path() -> Path:
    """Handle memory path."""
    return app_data_root() / 'server_slot_data.txt'


# /**
#  * Function: normalize_server
#  * Purpose: Perform the normalize server operation while keeping the surrounding subsystem state consistent.
#  * @param server: Server supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def normalize_server(server: str) -> str:
    # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
    """Return normalize server."""
    value = str(server or '').strip().casefold()
    # Loop variable(s): `prefix` (prefix); each iteration represents the next value from the iterable below.
    for prefix in ('archipelago://','ws://','wss://'):
        # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
        if value.startswith(prefix): value=value[len(prefix):]
    return value.rstrip('/')


# /**
#  * Function: identity_key
#  * Purpose: Perform the identity key operation while keeping the surrounding subsystem state consistent.
#  * @param server: Server supplied by the caller; see type hints and call sites for domain constraints.
#  * @param slot: Slot supplied by the caller; see type hints and call sites for domain constraints.
#  * @param game: Game supplied by the caller; see type hints and call sites for domain constraints.
#  * @param team: Team supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def identity_key(server: str, slot: str, game: str, team: int | str | None = None) -> str:
    # Variable(s): `parts` (parts); named state retained for the surrounding calculation or subsequent calls.
    """Handle identity key."""
    parts=[normalize_server(server), str(slot or '').strip().casefold(), str(game or '').strip().casefold()]
    if team is not None:
        try: parts.append(f"team:{int(team)}")
        except (TypeError, ValueError): parts.append(f"team:{str(team).strip().casefold()}")
    return '|'.join(parts)


# /**
#  * Function: load_all
#  * Purpose: Load all data and convert it into the form expected by WayFinder.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def load_all() -> dict[str, Any]:
    """Return load all."""
    try:
        # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
        data=json.loads(memory_path().read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# /**
#  * Function: save_all
#  * Purpose: Persist all data while preserving the caller-facing behavior.
#  * @param data: Data supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def save_all(data: dict[str, Any]) -> None:
    # Variable(s): `path` (path); named state retained for the surrounding calculation or subsequent calls.
    """Handle save all."""
    path=memory_path(); path.parent.mkdir(parents=True, exist_ok=True)
    # Variable(s): `tmp` (temporary value); named state retained for the surrounding calculation or subsequent calls.
    tmp=path.with_name(path.name + f".tmp-{os.getpid()}")
    if path.exists():
        try: shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        except OSError: _ignored("intentional best-effort fallback")
    try:
        # Variable(s): `fh` (file handle); named state retained for the surrounding calculation or subsequent calls.
        with tmp.open("w",encoding="utf-8",newline="\n") as fh:
            json.dump(data,fh,indent=2,ensure_ascii=False,sort_keys=True); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp,path)
    finally:
        try: tmp.unlink(missing_ok=True)
        except OSError: _ignored("intentional best-effort fallback")


# /**
#  * Function: _fold_key
#  * Purpose: Perform the fold key operation while keeping the surrounding subsystem state consistent.
#  * @param value: Value supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _fold_key(value: Any) -> str:
    """Handle fold key."""
    return re.sub(r'[^a-z0-9]+', '', str(value or '').casefold())


# /**
#  * Function: _lookup_slot_value
#  * Purpose: Perform the lookup slot value operation while keeping the surrounding subsystem state consistent.
#  * @param slot_data: Slot data supplied by the caller; see type hints and call sites for domain constraints.
#  * @param candidate: Candidate supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _lookup_slot_value(slot_data: dict[str, Any], candidate: str):
    # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
    """Handle lookup slot value."""
    target=_fold_key(candidate)
    # Loop variable(s): `key` (key), `value` (value); each iteration represents the next value from the iterable below.
    for key,value in slot_data.items():
        if _fold_key(key) == target:
            return str(key), value
    return None


# /**
#  * Function: _display_caveat_value
#  * Purpose: Perform the display caveat value operation while keeping the surrounding subsystem state consistent.
#  * @param mapping: Mapping supplied by the caller; see type hints and call sites for domain constraints.
#  * @param value: Value supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _display_caveat_value(mapping: dict[Any, str], value: Any):
    # bool is a subclass of int, so direct membership is intentional here: the
    # Mina mapping defines both bool and integer forms for JSON/runtime safety.
    """Handle display caveat value."""
    if value in mapping:
        return mapping[value]
    try:
        # Variable(s): `ivalue` (ivalue); named state retained for the surrounding calculation or subsequent calls.
        ivalue=int(value)
        if ivalue in mapping:
            return mapping[ivalue]
    except (TypeError, ValueError):
        _ignored("intentional best-effort fallback")
    return None


# /**
#  * Function: resolved_start
#  * Purpose: Perform the resolved start operation while keeping the surrounding subsystem state consistent.
#  * @param slot_data: Slot data supplied by the caller; see type hints and call sites for domain constraints.
#  * @param game: Game supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def resolved_start(slot_data: Any, game: str = ''):
    """Return (slot-key, raw-value, display-value) for a resolved start.

    Generic games are detected from common key names. Known APWorld caveats are
    checked first so non-standard fields and numeric Choice values can be shown
    as the actual generated area while preserving the raw value for UT restore.
    """
    if not isinstance(slot_data, dict): return None

    # Variable(s): `caveat` (caveat); named state retained for the surrounding calculation or subsequent calls.
    caveat=START_CAVEATS.get(str(game or '').strip().casefold())
    if caveat:
        # Loop variable(s): `candidate` (candidate); each iteration represents the next value from the iterable below.
        for candidate in caveat.get('keys', ()):
            # Variable(s): `pair` (pair); named state retained for the surrounding calculation or subsequent calls.
            pair=_lookup_slot_value(slot_data, candidate)
            if not pair: continue
            # Variable(s): `key` (key), `value` (value); named state retained for the surrounding calculation or subsequent calls.
            key,value=pair
            if value is None: continue
            if isinstance(value, str) and value.strip().casefold() in UNRESOLVED: continue
            # Variable(s): `display` (display); named state retained for the surrounding calculation or subsequent calls.
            display=_display_caveat_value(caveat.get('values', {}), value)
            if display is None:
                # Variable(s): `display` (display); named state retained for the surrounding calculation or subsequent calls.
                display=str(value)
            return key, value, display

    # Loop variable(s): `candidate` (candidate); each iteration represents the next value from the iterable below.
    for candidate in START_KEYS:
        # Variable(s): `pair` (pair); named state retained for the surrounding calculation or subsequent calls.
        pair=_lookup_slot_value(slot_data, candidate)
        if not pair: continue
        # Variable(s): `key` (key), `value` (value); named state retained for the surrounding calculation or subsequent calls.
        key,value=pair
        if isinstance(value, str) and value.strip().casefold() in UNRESOLVED: continue
        if value is None: continue
        return key, value, str(value)
    return None


# /**
#  * Function: start_resolution_diagnostic
#  * Purpose: Perform the start resolution diagnostic operation while keeping the surrounding subsystem state consistent.
#  * @param slot_data: Slot data supplied by the caller; see type hints and call sites for domain constraints.
#  * @param game: Game supplied by the caller; see type hints and call sites for domain constraints.
#  * @param found: Found supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def start_resolution_diagnostic(slot_data: Any, game: str, found: Any = None) -> str | None:
    """Return one concise Connected diagnostic for known start-data worlds."""
    # Variable(s): `game_key` (game key); named state retained for the surrounding calculation or subsequent calls.
    game_key=str(game or '').strip().casefold()
    # Variable(s): `spec` (spec); named state retained for the surrounding calculation or subsequent calls.
    spec=START_DIAGNOSTICS.get(game_key)
    if not spec:
        return None
    # Variable(s): `label` (label); named state retained for the surrounding calculation or subsequent calls.
    label=str(spec.get('label') or game or game_key)
    # Variable(s): `expected` (expected); named state retained for the surrounding calculation or subsequent calls.
    expected=tuple(spec.get('keys', ()) or ())
    # Variable(s): `mode` (mode); named state retained for the surrounding calculation or subsequent calls.
    mode=str(spec.get('mode') or 'generic')
    if not isinstance(slot_data, dict):
        return f"[Start Resolution] {label}: NOT FOUND - Connected slot_data was unavailable. Expected {', '.join(expected)}."

    # Prefer the exact result used by the resolver, but independently inspect the
    # expected fields so a missing or newly-unmapped caveat is obvious in logs.
    # Variable(s): `present` (present); named state retained for the surrounding calculation or subsequent calls.
    present=[]
    # Loop variable(s): `candidate` (candidate); each iteration represents the next value from the iterable below.
    for candidate in expected:
        # Variable(s): `pair` (pair); named state retained for the surrounding calculation or subsequent calls.
        pair=_lookup_slot_value(slot_data, candidate)
        if pair:
            present.append(pair)

    if found is not None:
        try:
            # Variable(s): `key` (key), `raw_value` (raw value), `display_value` (display value); named state retained for the surrounding calculation or subsequent calls.
            key, raw_value, display_value=found
        except Exception:
            # Variable(s): `key` (key), `raw_value` (raw value), `display_value` (display value); named state retained for the surrounding calculation or subsequent calls.
            key=raw_value=display_value=None
        if key is not None:
            # Variable(s): `caveat` (caveat); named state retained for the surrounding calculation or subsequent calls.
            caveat=START_CAVEATS.get(game_key)
            # Variable(s): `mapped` (mapped); named state retained for the surrounding calculation or subsequent calls.
            mapped=True
            if caveat and caveat.get('values'):
                # Variable(s): `mapped` (mapped); named state retained for the surrounding calculation or subsequent calls.
                mapped=_display_caveat_value(caveat.get('values', {}), raw_value) is not None
            # Variable(s): `suffix` (suffix); named state retained for the surrounding calculation or subsequent calls.
            suffix='caveat mapping' if mode == 'caveat' else 'generic readable value'
            if caveat and not mapped:
                return f"[Start Resolution] {label}: FOUND {key}={raw_value!r}, but no caveat mapping exists for this value; displaying {display_value!r}."
            return f"[Start Resolution] {label}: FOUND {key}={raw_value!r} -> {display_value} ({suffix})."

    if present:
        # Variable(s): `details` (details); named state retained for the surrounding calculation or subsequent calls.
        details=', '.join(f"{k}={v!r}" for k,v in present)
        return f"[Start Resolution] {label}: NOT RESOLVED - expected field present ({details}) but it was empty/random/unresolved or could not be interpreted."

    # Variable(s): `expected_text` (expected text); named state retained for the surrounding calculation or subsequent calls.
    expected_text=' / '.join(expected) if expected else 'a supported start field'
    # Only list start-looking keys, never dump arbitrary slot_data into diagnostics.
    # Variable(s): `startish` (startish); named state retained for the surrounding calculation or subsequent calls.
    startish=[]
    # Variable(s): `known_targets` (known targets); named state retained for the surrounding calculation or subsequent calls.
    known_targets={_fold_key(x) for x in START_KEYS}
    known_targets.update(_fold_key(x) for x in expected)
    # Loop variable(s): `key` (key), `value` (value); each iteration represents the next value from the iterable below.
    for key,value in slot_data.items():
        # Variable(s): `fk` (fk); named state retained for the surrounding calculation or subsequent calls.
        fk=_fold_key(key)
        if fk in known_targets or 'start' in fk or 'spawn' in fk or 'origin' in fk:
            startish.append(f"{key}={value!r}")
    # Variable(s): `extra` (extra); named state retained for the surrounding calculation or subsequent calls.
    extra=f" Start-like fields seen: {', '.join(startish)}." if startish else ''
    return f"[Start Resolution] {label}: NOT FOUND - expected {expected_text} was not present in Connected slot_data.{extra}"


# /**
#  * Function: get_record
#  * Purpose: Retrieve record information for the current operation.
#  * @param server: Server supplied by the caller; see type hints and call sites for domain constraints.
#  * @param slot: Slot supplied by the caller; see type hints and call sites for domain constraints.
#  * @param game: Game supplied by the caller; see type hints and call sites for domain constraints.
#  * @param team: Team supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def get_record(server: str, slot: str, game: str, team: int | str | None = None) -> dict[str, Any]:
    # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
    """Return get record."""
    data=load_all()
    # Variable(s): `rec` (rec); named state retained for the surrounding calculation or subsequent calls.
    rec=data.get(identity_key(server,slot,game,team)) if team is not None else None
    if not isinstance(rec, dict):
        # Variable(s): `team_num` (team num); named state retained for the surrounding calculation or subsequent calls.
        try: team_num=int(team) if team is not None else 0
        # Variable(s): `team_num` (team num); named state retained for the surrounding calculation or subsequent calls.
        except (TypeError, ValueError): team_num=0
        # Variable(s): `rec` (rec); named state retained for the surrounding calculation or subsequent calls.
        rec=data.get(identity_key(server,slot,game), {}) if team_num == 0 else {}
    # Variable(s): `rec` (rec); named state retained for the surrounding calculation or subsequent calls.
    rec=dict(rec or {}) if isinstance(rec, dict) else {}
    # Reject records whose embedded identity disagrees with the requested identity.
    if rec and (normalize_server(rec.get('server','')) != normalize_server(server) or str(rec.get('slot','')).strip().casefold() != str(slot or '').strip().casefold() or str(rec.get('game','')).strip().casefold() != str(game or '').strip().casefold()):
        return {}
    if team is not None and rec.get('team') is not None:
        try:
            if int(rec.get('team')) != int(team): return {}
        except (TypeError, ValueError): return {}
    return rec


# /**
#  * Function: remember_start
#  * Purpose: Perform the remember start operation while keeping the surrounding subsystem state consistent.
#  * @param server: Server supplied by the caller; see type hints and call sites for domain constraints.
#  * @param slot: Slot supplied by the caller; see type hints and call sites for domain constraints.
#  * @param game: Game supplied by the caller; see type hints and call sites for domain constraints.
#  * @param option_key: Option key supplied by the caller; see type hints and call sites for domain constraints.
#  * @param raw_value: Raw value supplied by the caller; see type hints and call sites for domain constraints.
#  * @param display_value: Display value supplied by the caller; see type hints and call sites for domain constraints.
#  * @param team: Team supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def remember_start(server: str, slot: str, game: str, option_key: str, raw_value: Any, display_value: Any | None = None, team: int | str | None = None) -> None:
    """Handle remember start."""
    if not server or not slot or not game: return
    # Variable(s): `data` (data); named state retained for the surrounding calculation or subsequent calls.
    data=load_all(); key=identity_key(server,slot,game,team); rec=dict(data.get(key, {}) or {})
    if display_value is None:
        # Variable(s): `display_value` (display value); named state retained for the surrounding calculation or subsequent calls.
        display_value=raw_value
    rec.update({
        'server':str(server), 'slot':str(slot), 'game':str(game), 'team':team,
        'starting_option':str(option_key),
        'starting_raw_value':raw_value,
        'starting_location':display_value,
    })
    data[key]=rec; save_all(data)


# /**
#  * Function: clear_server_slot
#  * Purpose: Perform the clear server slot operation while keeping the surrounding subsystem state consistent.
#  * @param server: Server supplied by the caller; see type hints and call sites for domain constraints.
#  * @param slot: Slot supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def clear_server_slot(server: str, slot: str) -> int:
    # Variable(s): `server_n` (server n); named state retained for the surrounding calculation or subsequent calls.
    """Handle clear server slot."""
    server_n=normalize_server(server); slot_n=str(slot or '').strip().casefold(); data=load_all(); removed=0
    # Loop variable(s): `key` (key), `rec` (rec); each iteration represents the next value from the iterable below.
    for key, rec in list(data.items()):
        if isinstance(rec, dict) and normalize_server(rec.get('server','')) == server_n and str(rec.get('slot','')).strip().casefold() == slot_n:
            data.pop(key, None); removed += 1
    if removed: save_all(data)
    return removed
