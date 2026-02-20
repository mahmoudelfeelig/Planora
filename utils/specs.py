from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Any

from utils.domain import Instance

SPEC_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
SPEC_WEEKS = list(range(1, 13))
SPEC_SLOTS_PER_DAY = 5
SPEC_DURATIONS = {1, 2, 3}
SPEC_COUNTS = {12, 18, 24}
SPEC_LAB_WEEKS = {0, 12}
SPEC_LAB_DURATION = {0, 1, 2}


def _norm_days(days: Iterable[str]) -> list[str]:
    return [str(d).upper() for d in days]


def validate_instance_against_spec(inst: Instance) -> None:
    days = _norm_days(inst.days)
    if days != SPEC_DAYS:
        raise ValueError(f"Spec violation: days must be {SPEC_DAYS}, got {inst.days}")
    if int(inst.slots_per_day) != SPEC_SLOTS_PER_DAY:
        raise ValueError(f"Spec violation: slots_per_day must be {SPEC_SLOTS_PER_DAY}, got {inst.slots_per_day}")
    if sorted(int(w) for w in inst.weeks) != SPEC_WEEKS:
        raise ValueError(f"Spec violation: weeks must be {SPEC_WEEKS}, got {inst.weeks}")

    for a in inst.activities.values():
        if int(a.duration) not in SPEC_DURATIONS:
            raise ValueError(f"Spec violation: activity {a.id} duration {a.duration} not in {sorted(SPEC_DURATIONS)}")

    # Course metadata constraints
    for c in inst.courses.values():
        lec = int(getattr(c, "lecture_count", 0) or 0)
        tut = int(getattr(c, "tutorial_count", 0) or 0)
        lab_weeks = int(getattr(c, "lab_weeks", 0) or 0)
        lab_dur = int(getattr(c, "lab_duration", 0) or 0)

        if lec not in SPEC_COUNTS and lec != 0:
            raise ValueError(f"Spec violation: course {c.id} lecture_count {lec} not in {sorted(SPEC_COUNTS)}")
        if tut not in SPEC_COUNTS and tut != 0:
            raise ValueError(f"Spec violation: course {c.id} tutorial_count {tut} not in {sorted(SPEC_COUNTS)}")
        if lab_weeks not in SPEC_LAB_WEEKS:
            raise ValueError(f"Spec violation: course {c.id} lab_weeks {lab_weeks} not in {sorted(SPEC_LAB_WEEKS)}")
        if lab_dur not in SPEC_LAB_DURATION:
            raise ValueError(f"Spec violation: course {c.id} lab_duration {lab_dur} not in {sorted(SPEC_LAB_DURATION)}")
        if lab_weeks == 0 and lab_dur not in (0, 1, 2):
            raise ValueError(f"Spec violation: course {c.id} lab_duration {lab_dur} invalid for lab_weeks=0")
        if lab_weeks > 0 and lab_dur not in (1, 2):
            raise ValueError(f"Spec violation: course {c.id} lab_duration {lab_dur} invalid for lab_weeks>0")


def validate_schedule_against_instance(
    inst: Instance,
    schedule: dict[int, dict],
    *,
    strict_rooms: bool = True,
    require_all_activities: bool = False,
) -> list[str]:
    """
    Validate a full schedule against hard constraints. Returns a list of errors.
    """
    errors: list[str] = []
    flags = getattr(inst, "hard_constraints", {}) or {}
    if not isinstance(schedule, dict):
        return ["Schedule must be a mapping of activity id to assignment."]

    def _flag(name: str, default: bool = True) -> bool:
        raw = flags.get(name, default) if isinstance(flags, dict) else default
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return default
        return str(raw).strip().lower() not in ("0", "false", "no")

    def _as_int(value: Any, *, field: str, a_id: int) -> int | None:
        if value is None:
            errors.append(f"A{a_id} missing {field}")
            return None
        try:
            return int(value)
        except Exception:
            errors.append(f"A{a_id} invalid {field} {value!r}")
            return None

    parsed: dict[int, dict[str, Any]] = {}
    actual_ids: set[int] = set()

    def _ordered_pair(a_id: int, b_id: int) -> tuple[int, int]:
        return (a_id, b_id) if a_id <= b_id else (b_id, a_id)

    # Keep room-overlap validation aligned with solver semantics:
    # some activities are intentionally co-located in one room/time via cluster constraints.
    allowed_room_colocations: set[tuple[int, int]] = set()

    # Explicit ad-hoc cluster keys (used by generated cross-major co-location).
    by_key: dict[tuple[str, int, str], list[int]] = defaultdict(list)
    for a_id, act in inst.activities.items():
        key = getattr(act, "cluster_key", None)
        if key:
            by_key[(str(key), int(act.week), str(act.kind))].append(int(a_id))
    for members in by_key.values():
        uniq = sorted(set(int(a_id) for a_id in members))
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                allowed_room_colocations.add(_ordered_pair(uniq[i], uniq[j]))

    # Shared-lecture clusters (same grouping logic as solver for single-group LEC activities).
    by_ckwg: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for a_id, act in inst.activities.items():
        if str(act.kind) == "LEC" and len(act.group_ids) == 1:
            by_ckwg[(int(act.course_id), int(act.week), int(act.group_ids[0]))].append(int(a_id))
    for c_id, course in inst.courses.items():
        shared = getattr(course, "share_lecture_group_ids", None) or []
        if not shared:
            continue
        shared_set = set(int(g_id) for g_id in shared)
        by_week: dict[int, list[int]] = defaultdict(list)
        for (cc, week, g_id), ids in by_ckwg.items():
            if int(cc) == int(c_id) and int(g_id) in shared_set:
                by_week[int(week)].extend(int(a_id) for a_id in ids)
        for members in by_week.values():
            uniq = sorted(set(int(a_id) for a_id in members))
            if len(uniq) < 2:
                continue
            for i in range(len(uniq)):
                for j in range(i + 1, len(uniq)):
                    allowed_room_colocations.add(_ordered_pair(uniq[i], uniq[j]))

    def _room_overlap_allowed(a_id: int, b_id: int) -> bool:
        return _ordered_pair(int(a_id), int(b_id)) in allowed_room_colocations

    # Bounds + identity + staff/room checks
    for raw_a_id, info in schedule.items():
        try:
            a_id = int(raw_a_id)
        except Exception:
            errors.append(f"Invalid activity key {raw_a_id!r} (expected integer activity id)")
            continue
        actual_ids.add(a_id)

        if not isinstance(info, dict):
            errors.append(f"A{a_id} assignment must be a mapping")
            continue
        if a_id not in inst.activities:
            errors.append(f"A{a_id} not present in instance")
            continue

        act = inst.activities[a_id]
        day = str(info.get("day", ""))
        slot = _as_int(info.get("slot"), field="slot", a_id=a_id)
        dur = _as_int(info.get("duration"), field="duration", a_id=a_id)
        week = _as_int(info.get("week"), field="week", a_id=a_id)
        staff_id = _as_int(info.get("staff_id"), field="staff_id", a_id=a_id)
        room_id_raw = info.get("room_id")
        room_id: int | None = None
        if room_id_raw is not None:
            try:
                room_id = int(room_id_raw)
            except Exception:
                errors.append(f"A{a_id} invalid room_id {room_id_raw!r}")

        kind = str(info.get("kind", ""))
        course_id = _as_int(info.get("course_id"), field="course_id", a_id=a_id)
        groups_raw = info.get("group_ids", [])
        group_ids: list[int] = []
        if isinstance(groups_raw, (list, tuple, set)):
            for g in groups_raw:
                try:
                    group_ids.append(int(g))
                except Exception:
                    errors.append(f"A{a_id} invalid group id {g!r}")
        else:
            errors.append(f"A{a_id} group_ids must be a list/tuple/set")

        if day not in inst.days:
            errors.append(f"A{a_id} invalid day {day}")
        if week is not None and week not in set(int(w) for w in inst.weeks):
            errors.append(f"A{a_id} invalid week {week}")
        if slot is not None and dur is not None:
            if dur <= 0:
                errors.append(f"A{a_id} duration must be positive, got {dur}")
            if slot < 0 or slot + dur > inst.slots_per_day:
                errors.append(f"A{a_id} invalid slot range {slot}+{dur}")

        # Identity consistency for immutable activity fields.
        if dur is not None and dur != int(act.duration):
            errors.append(f"A{a_id} duration mismatch {dur} != {act.duration}")
        if week is not None and week != int(act.week):
            errors.append(f"A{a_id} week mismatch {week} != {act.week}")
        if kind and kind != str(act.kind):
            errors.append(f"A{a_id} kind mismatch {kind} != {act.kind}")
        if course_id is not None and course_id != int(act.course_id):
            errors.append(f"A{a_id} course_id mismatch {course_id} != {act.course_id}")
        if set(group_ids) != set(int(g) for g in act.group_ids):
            errors.append(f"A{a_id} group_ids mismatch {sorted(set(group_ids))} != {sorted(set(act.group_ids))}")
        for g_id in group_ids:
            if g_id not in inst.groups:
                errors.append(f"A{a_id} references unknown group {g_id}")
            elif int(act.course_id) not in set(int(c) for c in inst.groups[g_id].course_ids):
                errors.append(f"A{a_id} group {g_id} is not enrolled in course {act.course_id}")

        if staff_id is None or staff_id not in inst.staff:
            errors.append(f"A{a_id} invalid staff {staff_id}")
        else:
            staff = inst.staff[int(staff_id)]
            if act.kind == "LEC" and not staff.is_prof:
                errors.append(f"A{a_id} lecture assigned to non-prof staff {staff_id}")
            if act.kind != "LEC" and staff.is_prof:
                errors.append(f"A{a_id} tutorial/lab assigned to professor {staff_id}")
            if int(act.course_id) not in set(int(c) for c in getattr(staff, "can_teach_courses", set())):
                errors.append(f"A{a_id} staff {staff_id} cannot teach course {act.course_id}")
            if day not in getattr(staff, "available_days", set()):
                errors.append(f"A{a_id} staff {staff_id} unavailable on {day}")

        if room_id is None:
            if strict_rooms:
                errors.append(f"A{a_id} missing room assignment")
        elif room_id not in inst.rooms:
            errors.append(f"A{a_id} invalid room {room_id}")
        elif strict_rooms:
            room = inst.rooms[int(room_id)]
            # Eligibility by kind
            if act.kind == "LEC" and room.room_type != "LECTURE":
                errors.append(f"A{a_id} lecture in non-lecture room {room_id}")
            if act.kind == "TUT" and room.room_type not in ("TUTORIAL", "LECTURE"):
                errors.append(f"A{a_id} tutorial in invalid room {room_id}")
            if act.kind == "LAB" and room.room_type not in ("SPECIALIZED_LAB", "COMPUTER_LAB"):
                errors.append(f"A{a_id} lab in invalid room {room_id}")
            # Capacity + specialization tags
            need = sum(inst.groups[g].size for g in act.group_ids if g in inst.groups)
            if room.capacity < need:
                errors.append(f"A{a_id} room {room_id} capacity {room.capacity} < {need}")
            tag = getattr(act, "requires_specialization", None)
            if tag:
                tags = getattr(room, "specialization_tags", []) or []
                if room.room_type != "SPECIALIZED_LAB" or tag not in tags:
                    errors.append(f"A{a_id} requires lab tag {tag} but room {room_id} not matching")
            # Availability
            avail = getattr(room, "availability", None)
            if _flag("enforce_room_availability", True) and isinstance(avail, set) and slot is not None and dur is not None:
                for off in range(dur):
                    if (day, slot + off) not in avail:
                        errors.append(f"A{a_id} room {room_id} unavailable at {day} slot {slot + off}")
                        break

        if (
            week is not None
            and slot is not None
            and dur is not None
            and day in inst.days
            and dur > 0
        ):
            parsed[a_id] = {
                "week": int(week),
                "day": str(day),
                "slot": int(slot),
                "duration": int(dur),
                "staff_id": int(staff_id) if staff_id is not None else None,
                "room_id": int(room_id) if room_id is not None else None,
                "group_ids": [int(g) for g in group_ids],
                "course_id": int(course_id) if course_id is not None else None,
                "kind": str(kind),
            }

    if require_all_activities:
        expected_ids = set(int(a_id) for a_id in inst.activities.keys())
        missing_ids = sorted(expected_ids - actual_ids)
        if missing_ids:
            preview = ", ".join(f"A{a_id}" for a_id in missing_ids[:8])
            suffix = "" if len(missing_ids) <= 8 else f", ... (+{len(missing_ids) - 8} more)"
            errors.append(f"Missing assignments for activities: {preview}{suffix}")

    # Enforce activity locks, if provided.
    locks = getattr(inst, "locked_activities", {}) or {}
    if isinstance(locks, dict):
        for raw_a_id, lock in locks.items():
            try:
                a_id = int(raw_a_id)
            except Exception:
                errors.append(f"Invalid lock activity id {raw_a_id!r}")
                continue
            if a_id not in inst.activities:
                errors.append(f"Lock references unknown activity A{a_id}")
                continue
            if a_id not in parsed:
                if require_all_activities:
                    errors.append(f"A{a_id} has a lock but is missing/invalid in schedule")
                continue
            if not isinstance(lock, dict):
                errors.append(f"A{a_id} lock must be a mapping")
                continue
            current = parsed[a_id]
            if "day" in lock and "slot" in lock:
                lock_day = str(lock.get("day"))
                try:
                    lock_slot = int(lock.get("slot"))
                except Exception:
                    errors.append(f"A{a_id} lock has invalid slot {lock.get('slot')!r}")
                    lock_slot = None
                if lock_slot is not None and (
                    current["day"] != lock_day or int(current["slot"]) != int(lock_slot)
                ):
                    errors.append(
                        f"A{a_id} violates time lock ({lock_day}, S{int(lock_slot) + 1})"
                    )
            if "room_id" in lock:
                try:
                    lock_room = int(lock.get("room_id"))
                except Exception:
                    errors.append(f"A{a_id} lock has invalid room_id {lock.get('room_id')!r}")
                    lock_room = None
                if lock_room is not None and int(current.get("room_id", -1)) != int(lock_room):
                    errors.append(f"A{a_id} violates room lock (R{lock_room})")

    # Week-1 lectures only
    if _flag("week1_lectures_only", True) and inst.weeks:
        first_week = min(int(w) for w in inst.weeks)
        for a_id, info in parsed.items():
            if int(info.get("week")) == first_week and str(info.get("kind")) in ("TUT", "LAB"):
                errors.append(f"A{a_id} violates week-1 lectures-only rule")

    # Overlap checks
    group_occ: dict[tuple[int, int, str, int], int] = {}
    staff_occ: dict[tuple[int, int, str, int], int] = {}
    room_occ: dict[tuple[int, int, str, int], list[int]] = {}

    for a_id, info in parsed.items():
        w = int(info["week"])
        d = str(info["day"])
        s0 = int(info["slot"])
        dur = int(info["duration"])
        staff_id = info.get("staff_id")
        room_id = info.get("room_id")

        for off in range(dur):
            s = s0 + off
            if staff_id is not None:
                key = (int(staff_id), w, d, s)
                if key in staff_occ and staff_occ[key] != a_id:
                    b_id = int(staff_occ[key])
                    errors.append(f"Staff overlap at week {w} {d} slot {s} (A{min(a_id, b_id)}, A{max(a_id, b_id)})")
                staff_occ[key] = a_id
            for g_id in info.get("group_ids", []) or []:
                key = (int(g_id), w, d, s)
                if key in group_occ and group_occ[key] != a_id:
                    b_id = int(group_occ[key])
                    errors.append(f"Group overlap at week {w} {d} slot {s} (A{min(a_id, b_id)}, A{max(a_id, b_id)})")
                group_occ[key] = a_id
            if strict_rooms and room_id is not None:
                key = (int(room_id), w, d, s)
                occupants = room_occ.setdefault(key, [])
                for b_id in occupants:
                    if int(b_id) == int(a_id):
                        continue
                    if _room_overlap_allowed(int(a_id), int(b_id)):
                        continue
                    errors.append(
                        f"Room overlap at week {w} {d} slot {s} "
                        f"(A{min(a_id, int(b_id))}, A{max(a_id, int(b_id))})"
                    )
                if int(a_id) not in occupants:
                    occupants.append(int(a_id))

    if _flag("enforce_block_professor_rules", True):
        # Block staff: at most two teaching days per week
        for s_id, staff in inst.staff.items():
            if not (getattr(staff, "blocks_only", False) or getattr(staff, "prefers_block", False)):
                continue
            for w in inst.weeks:
                days_used = set()
                for _, info in parsed.items():
                    staff_id = info.get("staff_id")
                    if staff_id is None:
                        continue
                    if int(staff_id) == int(s_id) and int(info.get("week")) == int(w):
                        days_used.add(str(info.get("day")))
                if len(days_used) > 2:
                    errors.append(f"Staff {s_id} exceeds 2 teaching days in week {w}")

        # Block-only professors: per (staff, course, week) lecture slots must be one contiguous 2-3 slot block.
        for s_id, staff in inst.staff.items():
            if not getattr(staff, "blocks_only", False):
                continue
            for w in inst.weeks:
                courses_here = {
                    int(info.get("course_id"))
                    for info in parsed.values()
                    if int(info.get("week")) == int(w)
                    and str(info.get("kind")) == "LEC"
                    and info.get("staff_id") is not None
                    and int(info.get("staff_id")) == int(s_id)
                }
                for c_id in courses_here:
                    slots_by_day: dict[str, list[int]] = {}
                    total = 0
                    for info in parsed.values():
                        if (
                            int(info.get("week")) != int(w)
                            or str(info.get("kind")) != "LEC"
                            or info.get("staff_id") is None
                            or int(info.get("staff_id")) != int(s_id)
                            or int(info.get("course_id")) != int(c_id)
                        ):
                            continue
                        d = str(info.get("day"))
                        s0 = int(info.get("slot"))
                        dur = int(info.get("duration"))
                        total += dur
                        for off in range(dur):
                            slots_by_day.setdefault(d, []).append(s0 + off)
                    if total and not (2 <= total <= 3):
                        errors.append(f"Block prof {s_id} course {c_id} week {w}: total {total} not in [2,3]")
                    if len(slots_by_day) > 1:
                        errors.append(f"Block prof {s_id} course {c_id} week {w}: lectures span multiple days")
                    for d, slots in slots_by_day.items():
                        slots_sorted = sorted(set(slots))
                        for i in range(1, len(slots_sorted)):
                            if slots_sorted[i] != slots_sorted[i - 1] + 1:
                                errors.append(f"Block prof {s_id} course {c_id} week {w}: non-contiguous slots on {d}")

    # Load caps
    enforce_weekly = _flag("enforce_staff_weekly_caps", True)
    enforce_daily = _flag("enforce_staff_daily_caps", True)
    if enforce_weekly or enforce_daily:
        for s_id, staff in inst.staff.items():
            max_week = getattr(staff, "max_slots_per_week", None) if enforce_weekly else None
            max_day = getattr(staff, "max_slots_per_day", None) if enforce_daily else None
            if max_week is None and max_day is None:
                continue
            for w in inst.weeks:
                week_load = 0
                day_loads = {d: 0 for d in inst.days}
                for info in parsed.values():
                    staff_id = info.get("staff_id")
                    if staff_id is None:
                        continue
                    if int(staff_id) != int(s_id) or int(info.get("week")) != int(w):
                        continue
                    dur = int(info.get("duration"))
                    week_load += dur
                    day_loads[str(info.get("day"))] += dur
                if max_week is not None and week_load > int(max_week):
                    errors.append(f"Staff {s_id} week {w} exceeds weekly cap {max_week}")
                if max_day is not None:
                    for d, load in day_loads.items():
                        if load > int(max_day):
                            errors.append(f"Staff {s_id} day {d} week {w} exceeds daily cap {max_day}")

    # deterministic + deduplicated error list
    return sorted(dict.fromkeys(str(e) for e in errors))
