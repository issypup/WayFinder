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
    payload={"schema":SCHEMA,"seed_key":seed_key,"updated_at":time.time(),"entrances":rows}
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
