# /**
#  * Module: wayfinder.logic/apworld_probe.py
#  * Purpose: Core tracker module for apworld probe; contains format-neutral or APWorld logic used to calculate WayFinder state.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

"""Safe, non-importing APWorld reconnaissance for native-adapter development."""
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

import ast
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


# /**
#  * Class: APWorldProbe
#  * Purpose: Encapsulate the APWorldProbe responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class APWorldProbe:
    # Variable(s): `path` (path); named state retained for the surrounding calculation or subsequent calls.
    """Provide a p world probe behavior."""
    path: str
    # Variable(s): `package` (package); named state retained for the surrounding calculation or subsequent calls.
    package: str = ""
    # Variable(s): `game` (game); named state retained for the surrounding calculation or subsequent calls.
    game: str = ""
    # Variable(s): `files` (files); named state retained for the surrounding calculation or subsequent calls.
    files: list[str] = field(default_factory=list)
    # Variable(s): `tracker_files` (tracker files); named state retained for the surrounding calculation or subsequent calls.
    tracker_files: list[str] = field(default_factory=list)
    # Variable(s): `has_rules` (has rules); named state retained for the surrounding calculation or subsequent calls.
    has_rules: bool = False
    # Variable(s): `has_regions` (has regions); named state retained for the surrounding calculation or subsequent calls.
    has_regions: bool = False
    # Variable(s): `has_legacy_tracker_module` (has legacy tracker module); named state retained for the surrounding calculation or subsequent calls.
    has_legacy_tracker_module: bool = False
    # Variable(s): `world_attributes` (world attributes); named state retained for the surrounding calculation or subsequent calls.
    world_attributes: dict[str, str] = field(default_factory=dict)


# /**
#  * Function: inspect_apworld
#  * Purpose: Perform the inspect apworld operation while keeping the surrounding subsystem state consistent.
#  * @param path: Path supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def inspect_apworld(path: str | Path) -> APWorldProbe:
    # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
    """Handle inspect apworld."""
    p = Path(path)
    # Variable(s): `probe` (probe); named state retained for the surrounding calculation or subsequent calls.
    probe = APWorldProbe(str(p))
    # Variable(s): `zf` (ZIP archive handle); named state retained for the surrounding calculation or subsequent calls.
    with zipfile.ZipFile(p) as zf:
        # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
        names = [n for n in zf.namelist() if not n.endswith("/")]
        probe.files = names
        # Variable(s): `packages` (packages); named state retained for the surrounding calculation or subsequent calls.
        packages = {n.split("/", 1)[0] for n in names if "/" in n}
        probe.package = sorted(packages)[0] if packages else ""
        # Variable(s): `prefix` (prefix); named state retained for the surrounding calculation or subsequent calls.
        prefix = probe.package + "/" if probe.package else ""
        probe.tracker_files = [n for n in names if "/tracker/" in n or n.endswith("/tracker.py") or n.endswith("/universal_tracker.py")]
        probe.has_rules = any(n.lower().endswith(("rules.py", "rule.py")) for n in names)
        probe.has_regions = any(n.lower().endswith(("regions.py", "region.py")) for n in names)
        probe.has_legacy_tracker_module = any(n.endswith("/universal_tracker.py") for n in names)
        # Variable(s): `meta_name` (meta name); named state retained for the surrounding calculation or subsequent calls.
        meta_name = prefix + "archipelago.json"
        if meta_name in names:
            try:
                # Variable(s): `meta` (meta); named state retained for the surrounding calculation or subsequent calls.
                meta = json.loads(zf.read(meta_name).decode("utf-8"))
                probe.game = str(meta.get("game", meta.get("name", "")) or "")
            except Exception:
                _ignored("intentional best-effort fallback")
        # Variable(s): `init_name` (init name); named state retained for the surrounding calculation or subsequent calls.
        init_name = prefix + "__init__.py"
        if init_name in names:
            try:
                # Variable(s): `tree` (tree); named state retained for the surrounding calculation or subsequent calls.
                tree = ast.parse(zf.read(init_name).decode("utf-8", "replace"))
                # Loop variable(s): `node` (node); each iteration represents the next value from the iterable below.
                for node in tree.body:
                    if isinstance(node, ast.ClassDef):
                        # Loop variable(s): `stmt` (stmt); each iteration represents the next value from the iterable below.
                        for stmt in node.body:
                            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                                # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
                                target = stmt.targets[0] if isinstance(stmt, ast.Assign) and stmt.targets else getattr(stmt, "target", None)
                                if isinstance(target, ast.Name) and target.id in {"game", "ut_can_gen_without_yaml", "disable_ut", "glitches_item_name"}:
                                    # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
                                    value = getattr(stmt, "value", None)
                                    try:
                                        # Variable(s): `literal` (literal); named state retained for the surrounding calculation or subsequent calls.
                                        literal = ast.literal_eval(value)
                                    except Exception:
                                        continue
                                    probe.world_attributes[target.id] = repr(literal)
                                    if target.id == "game" and not probe.game:
                                        probe.game = str(literal)
            except Exception:
                _ignored("intentional best-effort fallback")
    return probe
