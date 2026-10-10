"""Persistent, serialization-safe seed model cache.

This cache intentionally stores only static/descriptive data and dependency
indexes. APWorld objects and access-rule closures remain runtime-owned and are
never pickled.
"""
from __future__ import annotations
import json, os, time
from pathlib import Path
from typing import Any
from ..storage import app_data_root

SCHEMA = 1

def cache_dir() -> Path:
    return app_data_root() / "seed_models"

def cache_path(key: str) -> Path:
    return cache_dir() / (str(key) + ".json")

def load(key: str) -> dict[str, Any] | None:
    path=cache_path(key)
    try:
        data=json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA or data.get("key") != key:
            return None
        return data
    except (OSError, ValueError, UnicodeError, AttributeError):
        return None

def save(key: str, model: dict[str, Any]) -> str:
    folder=cache_dir(); folder.mkdir(parents=True,exist_ok=True)
    path=cache_path(key); tmp=path.with_suffix(".json.tmp")
    payload=dict(model)
    payload.update(schema=SCHEMA,key=key,saved_at=time.time())
    tmp.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")),encoding="utf-8")
    os.replace(tmp,path)
    # Keep a bounded recent set.
    entries=sorted(folder.glob("*.json"),key=lambda p:p.stat().st_mtime,reverse=True)
    for stale in entries[32:]:
        try: stale.unlink()
        except OSError: pass
    return str(path)

def from_built(built: Any, snapshot: dict[str, Any] | None = None, dependency_graph: dict[str, Any] | None = None) -> dict[str, Any]:
    multiworld=built.multiworld; player=int(built.player)
    regions=[]
    for region in multiworld.get_regions(player):
        regions.append(str(getattr(region,"name","")))
    locations=[]
    for loc in multiworld.get_locations(player):
        address=getattr(loc,"address",None)
        if not isinstance(address,int): continue
        locations.append({
            "id":address,
            "name":str(getattr(loc,"name","")),
            "region":str(getattr(getattr(loc,"parent_region",None),"name","") or ""),
        })
    entrances=[]
    for region in multiworld.get_regions(player):
        for entrance in getattr(region,"exits",()) or ():
            entrances.append({
                "name":str(getattr(entrance,"name","")),
                "from":str(getattr(region,"name","")),
                "to":str(getattr(getattr(entrance,"connected_region",None),"name","") or ""),
            })
    result={
        "game":str(getattr(built,"game","")),
        "slot_name":str(getattr(built,"slot_name","")),
        "logic_source":str(getattr(built,"logic_source","")),
        "exact_logic":bool(getattr(built,"exact_logic",False)),
        "regions":sorted(set(regions),key=str.casefold),
        "locations":sorted(locations,key=lambda r:(r["region"].casefold(),r["name"].casefold())),
        "entrances":sorted(entrances,key=lambda r:(r["from"].casefold(),r["name"].casefold())),
        "dependency_graph":dependency_graph or {},
    }
    if snapshot:
        # Static rule descriptions are safe JSON and useful to secondary UI while
        # live reachability is being refreshed. Never persist live inventory/checks.
        result["static_rule_details"]=snapshot.get("rule_details",{})
        result["static_entrance_details"]=snapshot.get("entrance_details",[])
        result["static_event_details"]=snapshot.get("event_details",[])
    return result
