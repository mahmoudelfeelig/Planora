from __future__ import annotations

import os
import copy
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from services.contracts import ImproveOptions, SolveOptions
from services.export_service import export_csv
from services.quality_service import (
    SOFT_WEIGHT_DEFAULTS,
    compute_penalty_breakdown,
    rank_penalty_drivers,
)
from services.solver_service import improve_schedule, solve_instance
from utils.generator import instance_to_json
from utils.specs import validate_schedule_against_instance


def normalize_schedule(schedule: Dict[Any, Dict[str, Any]] | None) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for raw_id, raw_info in dict(schedule or {}).items():
        info = dict(raw_info or {})
        if "week" in info:
            info["week"] = int(info["week"])
        if "slot" in info:
            info["slot"] = int(info["slot"])
        if "duration" in info:
            info["duration"] = int(info["duration"])
        if info.get("room_id") is not None:
            info["room_id"] = int(info["room_id"])
        if info.get("staff_id") is not None:
            info["staff_id"] = int(info["staff_id"])
        if "course_id" in info:
            info["course_id"] = int(info["course_id"])
        info["group_ids"] = [int(g) for g in (info.get("group_ids") or [])]
        if "day" in info:
            info["day"] = str(info["day"])
        if "kind" in info:
            info["kind"] = str(info["kind"])
        out[int(raw_id)] = info
    return out


def build_focused_improve_instance(inst, term: str):
    term = str(term or "").strip()
    if not term:
        return inst
    if term not in SOFT_WEIGHT_DEFAULTS:
        raise ValueError(f"Unknown improvement focus term: {term}")
    focused = copy.deepcopy(inst)
    weights = dict(SOFT_WEIGHT_DEFAULTS)
    weights.update(
        {
            str(k): int(v)
            for k, v in dict(getattr(inst, "soft_weights", {}) or {}).items()
            if str(k) in SOFT_WEIGHT_DEFAULTS
        }
    )
    weights[str(term)] = max(1, int(weights.get(str(term), SOFT_WEIGHT_DEFAULTS[str(term)]))) * 10
    focused.soft_weights = weights
    return focused


def focus_penalty_activity_ids(
    inst,
    schedule: Dict[Any, Dict[str, Any]],
    term: str,
    *,
    limit: int = 80,
) -> List[int]:
    term = str(term or "").strip()
    if term not in SOFT_WEIGHT_DEFAULTS:
        return []
    schedule_i = normalize_schedule(schedule)
    ids: Set[int] = set()

    by_group_week_day: Dict[Tuple[int, int, str], List[int]] = {}
    by_group_week: Dict[Tuple[int, int], List[int]] = {}
    by_course_group_kind: Dict[Tuple[int, int, str], List[int]] = {}
    by_course_group_week_kind: Dict[Tuple[int, int, int, str], List[int]] = {}
    for a_id, info in schedule_i.items():
        week = int(info.get("week", 0))
        day = str(info.get("day", ""))
        kind = str(info.get("kind", ""))
        course_id = int(info.get("course_id", 0))
        for g_raw in info.get("group_ids", []) or []:
            g_id = int(g_raw)
            by_group_week_day.setdefault((g_id, week, day), []).append(int(a_id))
            by_group_week.setdefault((g_id, week), []).append(int(a_id))
            by_course_group_kind.setdefault((course_id, g_id, kind), []).append(int(a_id))
            by_course_group_week_kind.setdefault((course_id, g_id, week, kind), []).append(int(a_id))

    if term in {"thin_day", "single_slot", "stud_gaps", "late_start"}:
        for (_g_id, _week, _day), act_ids in by_group_week_day.items():
            occ = [0 for _ in range(int(inst.slots_per_day))]
            members_by_slot: Dict[int, Set[int]] = {}
            for a_id in act_ids:
                info = schedule_i[int(a_id)]
                start = int(info.get("slot", 0))
                dur = int(info.get("duration", 1))
                for slot in range(start, min(int(inst.slots_per_day), start + dur)):
                    occ[slot] = 1
                    members_by_slot.setdefault(int(slot), set()).add(int(a_id))
            load = sum(occ)
            blocks = 0
            prev = 0
            for value in occ:
                if value and not prev:
                    blocks += 1
                prev = value
            first = next((idx for idx, value in enumerate(occ) if value), None)
            if (
                (term == "thin_day" and load == 2)
                or (term == "single_slot" and load == 1)
                or (term == "stud_gaps" and blocks > 1)
                or (term == "late_start" and first is not None and int(first) >= 2)
            ):
                ids.update(int(a_id) for slot_ids in members_by_slot.values() for a_id in slot_ids)
    elif term in {"active_days", "stud_free_days", "stud_free_mf", "stability"}:
        for (_g_id, _week), act_ids in by_group_week.items():
            ids.update(int(a_id) for a_id in act_ids)
    elif term == "same_kind_week":
        for (_course, _group, _week, kind), act_ids in by_course_group_week_kind.items():
            if kind in {"LEC", "TUT"} and len(set(int(a) for a in act_ids)) > 1:
                ids.update(int(a_id) for a_id in act_ids)
    elif term == "room_consistency":
        for (_course, _group, _kind), act_ids in by_course_group_kind.items():
            rooms = {
                schedule_i[int(a_id)].get("room_id")
                for a_id in act_ids
                if schedule_i[int(a_id)].get("room_id") is not None
            }
            if len(rooms) > 1:
                ids.update(int(a_id) for a_id in act_ids)
    elif term == "staff_free_day":
        by_staff_week: Dict[Tuple[int, int], List[int]] = {}
        for a_id, info in schedule_i.items():
            staff_id = info.get("staff_id")
            if staff_id is not None:
                by_staff_week.setdefault((int(staff_id), int(info.get("week", 0))), []).append(int(a_id))
        for (_staff, _week), act_ids in by_staff_week.items():
            ids.update(int(a_id) for a_id in act_ids)

    ranked = sorted(
        ids,
        key=lambda a_id: (
            int(schedule_i[int(a_id)].get("week", 0)),
            str(schedule_i[int(a_id)].get("day", "")),
            int(schedule_i[int(a_id)].get("slot", 0)),
            int(a_id),
        ),
    )
    return ranked[: max(1, int(limit))]


def score_schedule(inst, schedule: Dict[Any, Dict[str, Any]], *, driver_limit: int = 12) -> Dict[str, Any]:
    schedule_i = normalize_schedule(schedule)
    hard_conflicts = validate_schedule_against_instance(
        inst,
        schedule_i,
        strict_rooms=True,
        require_all_activities=True,
    )
    breakdown = compute_penalty_breakdown(inst, schedule_i)
    return {
        "soft_penalty": int(breakdown.get("total", 0)),
        "breakdown": dict(breakdown),
        "drivers": rank_penalty_drivers(inst, schedule_i, limit=int(driver_limit)),
        "hard_conflicts": list(hard_conflicts),
        "hard_conflict_count": int(len(hard_conflicts)),
    }


def improve_schedule_shared(
    inst,
    schedule: Dict[Any, Dict[str, Any]],
    options: ImproveOptions,
    *,
    focus_term: str = "",
    progress_hook=None,
    stop_hook=None,
) -> Dict[str, Any]:
    base_schedule = normalize_schedule(schedule)
    focused_inst = build_focused_improve_instance(inst, focus_term)
    before = score_schedule(focused_inst, base_schedule)
    progress_events: List[Dict[str, Any]] = []

    def _progress(iteration: int, best_penalty: int, current_penalty: int) -> None:
        event = {
            "iteration": int(iteration),
            "best_penalty": int(best_penalty),
            "current_penalty": int(current_penalty),
        }
        maximum = max(10, int(os.environ.get("PLANORA_MAX_PROGRESS_EVENTS", "1000")))
        if len(progress_events) < maximum:
            progress_events.append(event)
        else:
            progress_events[-1] = event
        if progress_hook is not None:
            progress_hook(int(iteration), int(best_penalty), int(current_penalty))

    improved = improve_schedule(
        focused_inst,
        base_schedule,
        options,
        progress_hook=_progress,
        stop_hook=stop_hook,
    )
    after = score_schedule(focused_inst, improved)
    global_after = score_schedule(inst, improved)
    return {
        "schedule": improved,
        "before": before,
        "after": after,
        "global_after": global_after,
        "focus_term": str(focus_term or ""),
        "meta": {
            "iterations": int(options.iterations),
            "max_seconds": options.max_seconds,
            "focus_term": str(focus_term or ""),
            "progress_every": int(options.progress_every),
            "progress_events": progress_events,
        },
    }


def cp_sat_polish_shared(
    inst,
    schedule: Dict[Any, Dict[str, Any]],
    options: SolveOptions,
    *,
    focus_term: str,
    affected_limit: int = 100,
) -> Dict[str, Any]:
    base_schedule = normalize_schedule(schedule)
    affected = focus_penalty_activity_ids(
        inst,
        base_schedule,
        focus_term,
        limit=int(affected_limit),
    )
    if not affected:
        raise ValueError(f"No activities found for focus term: {focus_term}")
    result = solve_instance(
        inst,
        SolveOptions(
            **{
                **dict(options.__dict__),
                "base_schedule": base_schedule,
                "affected_activity_ids": list(affected),
                "freeze_unaffected": True,
                "use_objective": True,
                "retry_without_objective": True,
            }
        ),
    )
    return {
        "status": int(result.status),
        "raw_status": int(result.raw_status),
        "schedule": result.schedule,
        "hard_conflicts": list(result.hard_conflicts),
        "meta": dict(result.meta or {}),
        "focus_term": str(focus_term),
        "affected_activity_ids": list(affected),
    }


def export_schedule_csv_text(inst, schedule: Dict[Any, Dict[str, Any]], path: str | Path) -> str:
    export_csv(inst, normalize_schedule(schedule), path)
    return Path(path).read_text(encoding="utf-8")


def move_activity_shared(
    inst,
    schedule: Dict[Any, Dict[str, Any]],
    *,
    activity_id: int,
    week: int | None = None,
    day: str | None = None,
    slot: int | None = None,
    room_id: int | None = None,
    staff_id: int | None = None,
    enforce_hard_conflict_free: bool = True,
) -> Dict[str, Any]:
    moved = normalize_schedule(schedule)
    a_id = int(activity_id)
    if a_id not in moved:
        raise ValueError(f"Unknown activity_id: {a_id}")
    info = dict(moved[a_id])
    if week is not None:
        info["week"] = int(week)
    if day is not None:
        info["day"] = str(day)
    if slot is not None:
        info["slot"] = int(slot)
    if room_id is not None:
        info["room_id"] = int(room_id)
    if staff_id is not None:
        info["staff_id"] = int(staff_id)
    moved[a_id] = info
    conflicts = validate_schedule_against_instance(
        inst,
        moved,
        strict_rooms=True,
        require_all_activities=True,
    )
    if conflicts and bool(enforce_hard_conflict_free):
        return {
            "ok": False,
            "schedule": normalize_schedule(schedule),
            "hard_conflicts": list(conflicts),
            "score": score_schedule(inst, schedule),
        }
    return {
        "ok": True,
        "schedule": moved,
        "hard_conflicts": list(conflicts),
        "score": score_schedule(inst, moved),
    }


def candidate_move_deltas_shared(
    inst,
    schedule: Dict[Any, Dict[str, Any]],
    *,
    activity_id: int,
    week: int | None = None,
    room_id: int | None = None,
    staff_id: int | None = None,
    limit: int | None = None,
) -> Dict[str, Any]:
    schedule_i = normalize_schedule(schedule)
    a_id = int(activity_id)
    if a_id not in schedule_i:
        raise ValueError(f"Unknown activity_id: {a_id}")
    info = dict(schedule_i[a_id])
    target_week = int(week if week is not None else info.get("week", 0))
    target_room = int(room_id if room_id is not None else info.get("room_id", 0) or 0)
    target_staff = int(staff_id if staff_id is not None else info.get("staff_id", 0) or 0)
    duration = max(1, int(info.get("duration", 1) or 1))
    base_score = score_schedule(inst, schedule_i)
    base_penalty = int(base_score.get("soft_penalty", 0))
    rows: List[Dict[str, Any]] = []
    checked = 0
    for day in list(getattr(inst, "days", []) or []):
        for slot in range(0, max(0, int(inst.slots_per_day) - duration + 1)):
            if limit is not None and checked >= int(limit):
                break
            checked += 1
            result = move_activity_shared(
                inst,
                schedule_i,
                activity_id=a_id,
                week=target_week,
                day=str(day),
                slot=int(slot),
                room_id=target_room if target_room else None,
                staff_id=target_staff if target_staff else None,
                enforce_hard_conflict_free=False,
            )
            score = dict(result.get("score") or {})
            conflicts = list(result.get("hard_conflicts") or [])
            soft_penalty = int(score.get("soft_penalty", base_penalty))
            rows.append(
                {
                    "activity_id": a_id,
                    "week": target_week,
                    "day": str(day),
                    "slot": int(slot),
                    "room_id": target_room if target_room else None,
                    "staff_id": target_staff if target_staff else None,
                    "soft_penalty": soft_penalty,
                    "delta": int(soft_penalty - base_penalty),
                    "hard_conflict_count": int(len(conflicts)),
                    "hard_conflicts": conflicts[:5],
                    "ok": len(conflicts) == 0,
                }
            )
        if limit is not None and checked >= int(limit):
            break
    rows.sort(key=lambda row: (not bool(row["ok"]), int(row["delta"]), str(row["day"]), int(row["slot"])))
    return {
        "activity_id": a_id,
        "base_score": base_score,
        "targets": rows,
    }


def set_activity_lock_shared(
    inst,
    schedule: Dict[Any, Dict[str, Any]],
    *,
    activity_id: int,
    fields: List[str] | None = None,
) -> Dict[str, Any]:
    schedule_i = normalize_schedule(schedule)
    a_id = int(activity_id)
    if a_id not in schedule_i:
        raise ValueError(f"Unknown activity_id: {a_id}")
    lock_fields = [str(f) for f in (fields or ["day", "slot", "room_id"])]
    lock: Dict[str, Any] = {}
    for field in lock_fields:
        if field in schedule_i[a_id]:
            lock[field] = schedule_i[a_id][field]
    locks = {
        int(k): dict(v)
        for k, v in dict(getattr(inst, "locked_activities", {}) or {}).items()
        if isinstance(v, dict)
    }
    locks[a_id] = lock
    inst.locked_activities = locks
    return {
        "instance": instance_to_json(inst),
        "schedule": schedule_i,
        "locked_activities": dict(locks),
    }


def clear_activity_lock_shared(inst, schedule: Dict[Any, Dict[str, Any]], *, activity_id: int | None = None) -> Dict[str, Any]:
    schedule_i = normalize_schedule(schedule)
    locks = {
        int(k): dict(v)
        for k, v in dict(getattr(inst, "locked_activities", {}) or {}).items()
        if isinstance(v, dict)
    }
    if activity_id is None:
        locks = {}
    else:
        locks.pop(int(activity_id), None)
    inst.locked_activities = locks
    return {
        "instance": instance_to_json(inst),
        "schedule": schedule_i,
        "locked_activities": dict(locks),
    }


def workspace_payload(inst, schedule: Dict[Any, Dict[str, Any]] | None = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"instance": instance_to_json(inst)}
    if schedule is not None:
        payload["schedule"] = normalize_schedule(schedule)
    return payload
