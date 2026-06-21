from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_release_candidate(
    *,
    name: str,
    author: str,
    schedule: Dict[int, Dict[str, Any]],
    notes: str = "",
) -> Dict[str, Any]:
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("Release candidate name is required.")
    return {
        "name": clean_name,
        "author": str(author or "unknown").strip() or "unknown",
        "notes": str(notes or "").strip(),
        "created_at_utc": _utc_now(),
        "schedule": {int(a_id): dict(info) for a_id, info in schedule.items()},
        "status": "candidate",
    }


def publish_release_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(candidate or {})
    out["status"] = "published"
    out["published_at_utc"] = _utc_now()
    return out


def protect_baseline_state(
    *,
    protected: bool,
    actor: str,
    reason: str,
) -> Dict[str, Any]:
    return {
        "protected": bool(protected),
        "actor": str(actor or "unknown").strip() or "unknown",
        "reason": str(reason or "").strip(),
        "updated_at_utc": _utc_now(),
    }
