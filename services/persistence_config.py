from __future__ import annotations

import os
from pathlib import Path


SCHEMA_VERSION = 7


def default_persistence_path(root: str | Path) -> Path:
    configured = os.environ.get("PLANORA_DB_PATH")
    if configured:
        return Path(configured)
    return Path(root) / "data" / "planora.sqlite3"
