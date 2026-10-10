"""Seed-scoped player knowledge for randomized entrance destinations."""
from __future__ import annotations
import json, os, time
from pathlib import Path
from typing import Any
from ..storage import app_data_root

SCHEMA = 1


def _root() -> Path:
    return app_data_root() / "entrance_knowledge"


def _path(seed_key: str) -> Path:
    safe = "".join(ch for ch in str(seed_key) if ch.isalnum() or ch in "-_") or "unknown"
    return _root() / f"{safe}.json"


def load(seed_key: str) -> dict[str, dict[str, Any]]:
    try:
        data=json.loads(_path(seed_key).read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA or data.get("seed_key") != seed_key:
            return {}
        rows=data.get("entrances",{})
        return rows if isinstance(rows,dict) else {}
    except (OSError,ValueError,UnicodeError,AttributeError):
        return {}


def save(seed_key: str, rows: dict[str, dict[str, Any]]) -> None:
    root=_root(); root.mkdir(parents=True,exist_ok=True)
    path=_path(seed_key); tmp=path.with_suffix(".json.tmp")
    payload={"schema":SCHEMA,"seed_key":seed_key,"updated_at":time.time(),"entrances":rows,"mode":get_mode(seed_key)}
    tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    os.replace(tmp,path)


def set_destination(seed_key: str, entrance: str, destination: str, *, source: str = "player") -> None:
    rows=load(seed_key)
    rows[str(entrance)]={"destination":str(destination),"source":str(source),"updated_at":time.time()}
    save(seed_key,rows)


def forget(seed_key: str, entrance: str) -> None:
    rows=load(seed_key)
    rows.pop(str(entrance),None)
    save(seed_key,rows)


def known_destination(rows: dict[str, dict[str, Any]], entrance: str) -> tuple[str,str]:
    row=rows.get(str(entrance),{}) if isinstance(rows,dict) else {}
    return str(row.get("destination","") or ""), str(row.get("source","") or "")


MODES = ("user_specifies", "automatic_discovery")


def get_mode(seed_key: str) -> str:
    """Read the seed-scoped spoiler-safe discovery preference."""
    try:
        data = json.loads(_path(seed_key).read_text(encoding="utf-8"))
        mode = data.get("mode", MODES[0])
        return mode if mode in MODES else MODES[0]
    except (OSError, ValueError, AttributeError, UnicodeError):
        return MODES[0]


def set_mode(seed_key: str, mode: str) -> None:
    if mode not in MODES:
        raise ValueError("Invalid entrance discovery mode")
    rows = load(seed_key)
    save(seed_key, rows)
    path = _path(seed_key)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["mode"] = mode
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def visible_knowledge(rows: dict, mode: str) -> dict:
    """Manual knowledge is always visible; observed knowledge only in auto mode."""
    return {name: row for name, row in rows.items()
            if row.get("source", "player") == "player"
            or (mode == "automatic_discovery" and row.get("source") == "observed")}
