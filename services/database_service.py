from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Tuple

from utils.generator import instance_to_json
from utils.io import instance_from_json, schedule_from_rows, schedule_to_rows


def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            instance_json TEXT NOT NULL,
            schedule_json TEXT NOT NULL,
            meta_json TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def save_project_db(
    path: str | Path,
    inst,
    schedule: Dict[int, Dict[str, Any]],
    *,
    meta: Dict[str, Any] | None = None,
) -> None:
    conn = _connect(path)
    try:
        conn.execute("DELETE FROM projects WHERE id = 1")
        conn.execute(
            "INSERT INTO projects (id, instance_json, schedule_json, meta_json) VALUES (1, ?, ?, ?)",
            (
                json.dumps(instance_to_json(inst)),
                json.dumps(schedule_to_rows(schedule)),
                json.dumps(dict(meta or {})),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_project_db(path: str | Path) -> Tuple[Any, Dict[int, Dict[str, Any]], Dict[str, Any]]:
    conn = _connect(path)
    try:
        row = conn.execute(
            "SELECT instance_json, schedule_json, meta_json FROM projects WHERE id = 1"
        ).fetchone()
        if row is None:
            raise ValueError("No project saved in database.")
        inst = instance_from_json(json.loads(row[0]))
        schedule = schedule_from_rows(json.loads(row[1]))
        meta = json.loads(row[2])
        return inst, schedule, meta if isinstance(meta, dict) else {}
    finally:
        conn.close()
