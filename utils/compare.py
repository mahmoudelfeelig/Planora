from __future__ import annotations

import json
import csv
from pathlib import Path
from typing import Any, Dict, List, Tuple


def compare_schedules(
    base: Dict[int, Dict[str, Any]],
    other: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Compare two schedules by activity id and return summary stats.
    """
    base_ids = set(base.keys())
    other_ids = set(other.keys())
    shared = sorted(base_ids & other_ids)

    missing_in_other = sorted(base_ids - other_ids)
    missing_in_base = sorted(other_ids - base_ids)

    changed_time = 0
    changed_day = 0
    changed_slot = 0
    changed_room = 0
    changed_staff = 0

    moved_activity_ids: List[int] = []
    day_changes: List[Tuple[int, str, str]] = []
    slot_changes: List[Tuple[int, int, int]] = []
    room_changes: List[Tuple[int, int | None, int | None]] = []
    staff_changes: List[Tuple[int, int | None, int | None]] = []

    group_move_counts: Dict[int, int] = {}
    staff_move_counts: Dict[int, int] = {}

    for a_id in shared:
        b = base[a_id]
        o = other[a_id]

        b_day = b.get("day")
        o_day = o.get("day")
        b_slot = b.get("slot")
        o_slot = o.get("slot")

        if b_day != o_day or b_slot != o_slot:
            changed_time += 1
            moved_activity_ids.append(a_id)
            if b_day != o_day:
                changed_day += 1
                day_changes.append((a_id, b_day, o_day))
            if b_slot != o_slot:
                changed_slot += 1
                slot_changes.append((a_id, int(b_slot), int(o_slot)))

            for g_id in b.get("group_ids", []) or []:
                gid = int(g_id)
                group_move_counts[gid] = group_move_counts.get(gid, 0) + 1
            staff_id = b.get("staff_id")
            if staff_id is not None:
                sid = int(staff_id)
                staff_move_counts[sid] = staff_move_counts.get(sid, 0) + 1

        if b.get("room_id") != o.get("room_id"):
            changed_room += 1
            room_changes.append((a_id, b.get("room_id"), o.get("room_id")))

        if b.get("staff_id") != o.get("staff_id"):
            changed_staff += 1
            staff_changes.append((a_id, b.get("staff_id"), o.get("staff_id")))

    return {
        "shared": len(shared),
        "missing_in_other": missing_in_other,
        "missing_in_base": missing_in_base,
        "changed_time": changed_time,
        "changed_day": changed_day,
        "changed_slot": changed_slot,
        "changed_room": changed_room,
        "changed_staff": changed_staff,
        "moved_activity_ids": moved_activity_ids,
        "day_changes": day_changes,
        "slot_changes": slot_changes,
        "room_changes": room_changes,
        "staff_changes": staff_changes,
        "group_move_counts": group_move_counts,
        "staff_move_counts": staff_move_counts,
    }


def write_comparison_report(path: str | Path, summary: Dict[str, Any]) -> None:
    path = Path(path)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return
    if path.suffix.lower() == ".csv":
        rows: List[Tuple[str, Any]] = [
            ("shared", summary.get("shared", 0)),
            ("missing_in_other", len(summary.get("missing_in_other", []))),
            ("missing_in_base", len(summary.get("missing_in_base", []))),
            ("changed_time", summary.get("changed_time", 0)),
            ("changed_day", summary.get("changed_day", 0)),
            ("changed_slot", summary.get("changed_slot", 0)),
            ("changed_room", summary.get("changed_room", 0)),
            ("changed_staff", summary.get("changed_staff", 0)),
        ]
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["metric", "value"])
            writer.writerows(rows)
        return
    raise ValueError(f"Unsupported report format: {path.suffix}")
