from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict, List

from services.compare_service import compare_schedule_sets


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_branch(
    *,
    name: str,
    author: str,
    description: str = "",
    base_schedule: Dict[int, Dict[str, Any]],
    current_schedule: Dict[int, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("Branch name is required.")
    current = current_schedule if current_schedule is not None else base_schedule
    return {
        "name": clean_name,
        "description": str(description or "").strip(),
        "author": str(author or "unknown").strip() or "unknown",
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "base_schedule": {int(a_id): dict(info) for a_id, info in base_schedule.items()},
        "current_schedule": {int(a_id): dict(info) for a_id, info in current.items()},
        "merge_notes": [],
    }


def update_branch(branch: Dict[str, Any], schedule: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    out = dict(branch or {})
    out["current_schedule"] = {int(a_id): dict(info) for a_id, info in schedule.items()}
    out["updated_at_utc"] = _utc_now()
    return out


def branch_merge_assistance(
    branch: Dict[str, Any],
    target_schedule: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    branch_schedule = {
        int(a_id): dict(info)
        for a_id, info in dict(branch.get("current_schedule") or {}).items()
        if isinstance(info, dict)
    }
    summary = compare_schedule_sets(target_schedule, branch_schedule)
    summary["branch_name"] = str(branch.get("name", ""))
    summary["merge_message"] = (
        f"Branch {str(branch.get('name', 'unnamed'))}: "
        f"time={int(summary.get('changed_time', 0))}, "
        f"room={int(summary.get('changed_room', 0))}, "
        f"staff={int(summary.get('changed_staff', 0))}"
    )
    return summary


def list_branch_rows(branches: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for name, branch in sorted((branches or {}).items()):
        rows.append(
            {
                "name": str(name),
                "author": str(branch.get("author", "")),
                "description": str(branch.get("description", "")),
                "updated_at_utc": str(branch.get("updated_at_utc", "")),
            }
        )
    return rows
