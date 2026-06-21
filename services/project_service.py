from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from services.database_service import load_project_db, save_project_db
from utils.io import read_scenario, write_scenario


def save_legacy_project(
    path: str | Path,
    inst,
    schedule: Dict[int, Dict[str, Any]],
    *,
    meta: Dict[str, Any] | None = None,
) -> None:
    suffix = str(Path(path).suffix).lower()
    if suffix in {".db", ".sqlite", ".sqlite3"}:
        save_project_db(path, inst, schedule, meta=meta)
        return
    write_scenario(path, inst, schedule, meta=meta)


def load_legacy_project(path: str | Path) -> Tuple[Any, Dict[int, Dict[str, Any]], Dict[str, Any]]:
    suffix = str(Path(path).suffix).lower()
    if suffix in {".db", ".sqlite", ".sqlite3"}:
        return load_project_db(path)
    return read_scenario(path)
