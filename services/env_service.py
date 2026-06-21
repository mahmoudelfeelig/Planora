from __future__ import annotations

import os
from pathlib import Path


def env_value(name: str, default: str = "") -> str:
    """Read an environment value, with Docker/Kubernetes-style *_FILE support."""
    raw = os.environ.get(name)
    if raw not in {None, ""}:
        return str(raw)
    file_name = os.environ.get(f"{name}_FILE")
    if not file_name:
        return default
    path = Path(file_name)
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"{name}_FILE points to an unreadable secret file: {path}") from exc


def env_bool(name: str, default: bool = False) -> bool:
    raw = env_value(name, "")
    if raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
