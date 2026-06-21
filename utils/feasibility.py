from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Tuple

from utils.domain import Instance


def _is_block_staff(staff) -> bool:
    return bool(getattr(staff, "blocks_only", False) or getattr(staff, "prefers_block", False) or getattr(staff, "is_block_prof", False))


def explain_infeasibility(inst: Instance, *, max_per_category: int = 6) -> List[str]:
    """
    Heuristic explanations for infeasible schedules. This does not guarantee completeness.
    """
    reasons: List[str] = []

    days = [d for d in inst.days if not d.upper().startswith("SUN")]
    slots = inst.slots_per_day
    if not days:
        reasons.append("No schedulable days (Sunday-only calendar).")
        return reasons

    # 1) Week-1 lectures-only
    if inst.weeks:
        first_week = min(inst.weeks)
        bad_first = [a.id for a in inst.activities.values() if a.week == first_week and a.kind in ("TUT", "LAB")]
        if bad_first:
            reasons.append(f"Week {first_week} has non-lecture activities (e.g., A{bad_first[0]}).")

    # 2) Activity duration exceeds day capacity
    too_long = [a.id for a in inst.activities.values() if a.duration > slots]
    for a_id in too_long[:max_per_category]:
        reasons.append(f"Activity A{a_id} duration exceeds day slots ({slots}).")

    # 3) Staff competency / role mismatch
    bad_staff = []
    for a in inst.activities.values():
        sid = a.prof_id if a.kind == "LEC" else a.ta_id
        staff = inst.staff.get(sid)
        if staff is None:
            bad_staff.append(f"A{a.id} missing staff id {sid}")
            continue
        if a.kind == "LEC" and not staff.is_prof:
            bad_staff.append(f"A{a.id} lecture assigned to non-prof staff {sid}")
        if a.kind != "LEC" and staff.is_prof:
            bad_staff.append(f"A{a.id} tutorial/lab assigned to professor {sid}")
        if a.course_id not in getattr(staff, "can_teach_courses", set()):
            bad_staff.append(f"A{a.id} staff {sid} cannot teach course {a.course_id}")
    for msg in bad_staff[:max_per_category]:
        reasons.append(msg)

    # 4) Staff availability -> no allowed starts
    no_start = []
    locks = getattr(inst, "locked_activities", {}) or {}
    for a in inst.activities.values():
        sid = a.prof_id if a.kind == "LEC" else a.ta_id
        staff = inst.staff.get(sid)
        if staff is None:
            continue
        avail = set(getattr(staff, "available_days", []) or [])
        avail = {d for d in avail if d in days}
        if not avail:
            no_start.append(f"A{a.id} staff {sid} has no available days in calendar")
            continue
        max_start = slots - a.duration
        if max_start < 0:
            continue
        # If locked, ensure it falls in allowed times
        fixed = locks.get(a.id) if isinstance(locks, dict) else None
        if fixed and isinstance(fixed, dict) and "day" in fixed and "slot" in fixed:
            day = str(fixed["day"])
            slot = int(fixed["slot"])
            if day not in days:
                no_start.append(f"A{a.id} locked to invalid day '{day}'")
            elif slot < 0 or slot > max_start:
                no_start.append(f"A{a.id} locked to invalid slot {slot} for duration {a.duration}")
            elif day not in avail:
                no_start.append(f"A{a.id} locked to day '{day}' outside staff availability")
            continue
    for msg in no_start[:max_per_category]:
        reasons.append(msg)

    # 4b) Locked placements can directly contradict each other before search starts.
    locked_staff: Dict[Tuple[int, int, str, int], int] = {}
    locked_group: Dict[Tuple[int, int, str, int], int] = {}
    locked_room: Dict[Tuple[int, int, str, int], int] = {}
    lock_conflicts: List[str] = []
    if isinstance(locks, dict):
        for a in inst.activities.values():
            fixed = locks.get(a.id)
            if not isinstance(fixed, dict) or "day" not in fixed or "slot" not in fixed:
                continue
            try:
                day = str(fixed["day"])
                slot0 = int(fixed["slot"])
                room_id = int(fixed["room_id"]) if fixed.get("room_id") is not None else None
            except Exception:
                continue
            staff_id = int(a.prof_id if a.kind == "LEC" else a.ta_id)
            for off in range(int(a.duration)):
                slot = slot0 + off
                s_key = (staff_id, int(a.week), day, slot)
                prev = locked_staff.get(s_key)
                if prev is not None and prev != int(a.id):
                    lock_conflicts.append(f"Locked staff overlap: A{prev} and A{a.id} at week {a.week} {day} slot {slot + 1}")
                locked_staff[s_key] = int(a.id)
                for g_id in a.group_ids:
                    g_key = (int(g_id), int(a.week), day, slot)
                    prev = locked_group.get(g_key)
                    if prev is not None and prev != int(a.id):
                        lock_conflicts.append(f"Locked group overlap: A{prev} and A{a.id} at week {a.week} {day} slot {slot + 1}")
                    locked_group[g_key] = int(a.id)
                if room_id is not None:
                    r_key = (room_id, int(a.week), day, slot)
                    prev = locked_room.get(r_key)
                    if prev is not None and prev != int(a.id):
                        lock_conflicts.append(f"Locked room overlap: A{prev} and A{a.id} in room {room_id} at week {a.week} {day} slot {slot + 1}")
                    locked_room[r_key] = int(a.id)
    for msg in lock_conflicts[:max_per_category]:
        reasons.append(msg)

    # 5) Room eligibility per activity
    room_issues = []
    for a in inst.activities.values():
        need = sum(inst.groups[g].size for g in a.group_ids if g in inst.groups)
        if a.kind == "LAB":
            req = getattr(a, "requires_specialization", None)
            lab_candidates = [r for r in inst.rooms.values() if r.room_type in ("SPECIALIZED_LAB", "COMPUTER_LAB")]
            if req:
                matches = [
                    r for r in lab_candidates
                    if r.room_type == "SPECIALIZED_LAB"
                    and req in (getattr(r, "specialization_tags", []) or [])
                    and r.capacity >= need
                ]
                if not matches:
                    room_issues.append(f"A{a.id} requires lab tag '{req}' but no matching room fits capacity {need}")
            else:
                if not any(r.capacity >= need for r in lab_candidates):
                    room_issues.append(f"A{a.id} needs lab capacity {need}, but no lab room fits")
        elif a.kind == "TUT":
            candidates = [
                r for r in inst.rooms.values()
                if r.room_type in ("TUTORIAL", "LECTURE") and r.capacity >= need
            ]
            if not candidates:
                room_issues.append(f"A{a.id} needs tutorial capacity {need}, but no eligible room fits")
        else:  # LEC
            candidates = [
                r for r in inst.rooms.values()
                if r.room_type == "LECTURE" and r.capacity >= need
            ]
            if not candidates:
                room_issues.append(f"A{a.id} needs lecture capacity {need}, but no lecture room fits")
    for msg in room_issues[:max_per_category]:
        reasons.append(msg)

    # 6) Staff weekly capacity vs required load (upper bound check)
    required_by_staff_week: Dict[Tuple[int, int], int] = defaultdict(int)
    for a in inst.activities.values():
        sid = a.prof_id if a.kind == "LEC" else a.ta_id
        required_by_staff_week[(sid, a.week)] += int(a.duration)

    for (sid, w), req in list(required_by_staff_week.items())[:max_per_category]:
        staff = inst.staff.get(sid)
        if staff is None:
            continue
        avail = set(getattr(staff, "available_days", []) or [])
        avail = {d for d in avail if d in days}
        if not avail:
            continue
        usable_days = min(len(avail), 2 if _is_block_staff(staff) else len(avail))
        daily_cap = slots if staff.max_slots_per_day is None else min(slots, int(staff.max_slots_per_day))
        cap = usable_days * daily_cap
        if staff.max_slots_per_week is not None:
            cap = min(cap, int(staff.max_slots_per_week))
        if req > cap:
            reasons.append(
                f"Staff {staff.name} week {w}: required {req} slots exceeds cap {cap}"
            )

    # 7) Group week load exceeds physical capacity
    for g_id, g in list(inst.groups.items())[:max_per_category]:
        for w in inst.weeks:
            used = 0
            for a in inst.activities.values():
                if a.week != w:
                    continue
                if g_id in a.group_ids:
                    used += a.duration
            if used > len(days) * slots:
                reasons.append(
                    f"Group {g.name} week {w} needs {used} slots (> {len(days) * slots})"
                )
                break

    # 8) Suspicious shared lecture metadata. Imported timetables often contain
    # multiple real lecture rows for the same course/week; marking them as one
    # shared lecture cluster forces impossible co-location.
    shared_rows: List[str] = []
    for c_id, course in inst.courses.items():
        shared = getattr(course, "share_lecture_group_ids", None) or []
        if not shared:
            continue
        shared_set = {int(g) for g in shared}
        by_week: Dict[int, int] = defaultdict(int)
        for a in inst.activities.values():
            if int(a.course_id) != int(c_id) or a.kind != "LEC":
                continue
            if not any(int(g) in shared_set for g in a.group_ids):
                continue
            by_week[int(a.week)] += 1
        crowded = [(w, count) for w, count in by_week.items() if int(count) > 1]
        if crowded:
            week, count = crowded[0]
            shared_rows.append(
                f"Course {course.code} has {count} shared-lecture rows in week {week}; "
                "verify share_lecture_group_ids is not falsely clustering imported rows"
            )
    for msg in shared_rows[:max_per_category]:
        reasons.append(msg)

    return reasons
