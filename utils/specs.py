from __future__ import annotations

from typing import Iterable

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


def validate_schedule_against_instance(inst: Instance, schedule: dict[int, dict], *, strict_rooms: bool = True) -> list[str]:
    """
    Validate a full schedule against hard constraints. Returns a list of errors.
    """
    errors: list[str] = []
    flags = getattr(inst, "hard_constraints", {}) or {}

    def _flag(name: str, default: bool = True) -> bool:
        raw = flags.get(name, default) if isinstance(flags, dict) else default
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return default
        return str(raw).strip().lower() not in ("0", "false", "no")

    # Week-1 lectures only
    if _flag("week1_lectures_only", True) and inst.weeks:
        first_week = min(int(w) for w in inst.weeks)
        for a_id, info in schedule.items():
            if int(info.get("week")) == first_week and info.get("kind") in ("TUT", "LAB"):
                errors.append(f"A{a_id} violates week-1 lectures-only rule")

    # Bounds + staff role/competency + availability
    for a_id, info in schedule.items():
        if a_id not in inst.activities:
            errors.append(f"A{a_id} not present in instance")
            continue
        act = inst.activities[a_id]
        day = info.get("day")
        slot = int(info.get("slot", -1))
        dur = int(info.get("duration", -1))
        week = int(info.get("week", -1))
        staff_id = info.get("staff_id")
        room_id = info.get("room_id")

        if day not in inst.days:
            errors.append(f"A{a_id} invalid day {day}")
        if slot < 0 or slot + dur > inst.slots_per_day:
            errors.append(f"A{a_id} invalid slot range {slot}+{dur}")
        if dur != act.duration:
            errors.append(f"A{a_id} duration mismatch {dur} != {act.duration}")
        if week != act.week:
            errors.append(f"A{a_id} week mismatch {week} != {act.week}")

        if staff_id is None or int(staff_id) not in inst.staff:
            errors.append(f"A{a_id} invalid staff {staff_id}")
        else:
            staff = inst.staff[int(staff_id)]
            if act.kind == "LEC" and not staff.is_prof:
                errors.append(f"A{a_id} lecture assigned to non-prof staff {staff_id}")
            if act.kind != "LEC" and staff.is_prof:
                errors.append(f"A{a_id} tutorial/lab assigned to professor {staff_id}")
            if act.course_id not in getattr(staff, "can_teach_courses", set()):
                errors.append(f"A{a_id} staff {staff_id} cannot teach course {act.course_id}")
            if day not in getattr(staff, "available_days", set()):
                errors.append(f"A{a_id} staff {staff_id} unavailable on {day}")

        if strict_rooms:
            if room_id is None:
                errors.append(f"A{a_id} missing room assignment")
            elif int(room_id) not in inst.rooms:
                errors.append(f"A{a_id} invalid room {room_id}")
            else:
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
                if _flag("enforce_room_availability", True) and isinstance(avail, set):
                    for off in range(dur):
                        if (day, slot + off) not in avail:
                            errors.append(f"A{a_id} room {room_id} unavailable at {day} slot {slot + off}")
                            break

    # Overlap checks
    group_occ: dict[tuple[int, int, str, int], int] = {}
    staff_occ: dict[tuple[int, int, str, int], int] = {}
    room_occ: dict[tuple[int, int, str, int], int] = {}

    for a_id, info in schedule.items():
        if a_id not in inst.activities:
            continue
        w = int(info.get("week"))
        d = info.get("day")
        s0 = int(info.get("slot"))
        dur = int(info.get("duration"))
        staff_id = info.get("staff_id")
        room_id = info.get("room_id")

        for off in range(dur):
            s = s0 + off
            if staff_id is not None:
                key = (int(staff_id), w, d, s)
                if key in staff_occ and staff_occ[key] != a_id:
                    errors.append(f"Staff overlap at week {w} {d} slot {s} (A{a_id})")
                staff_occ[key] = a_id
            for g_id in info.get("group_ids", []) or []:
                key = (int(g_id), w, d, s)
                if key in group_occ and group_occ[key] != a_id:
                    errors.append(f"Group overlap at week {w} {d} slot {s} (A{a_id})")
                group_occ[key] = a_id
            if strict_rooms and room_id is not None:
                key = (int(room_id), w, d, s)
                if key in room_occ and room_occ[key] != a_id:
                    errors.append(f"Room overlap at week {w} {d} slot {s} (A{a_id})")
                room_occ[key] = a_id

    if _flag("enforce_block_professor_rules", True):
        # Block staff: at most two teaching days per week
        for s_id, staff in inst.staff.items():
            if not (getattr(staff, "blocks_only", False) or getattr(staff, "prefers_block", False)):
                continue
            for w in inst.weeks:
                days_used = set()
                for a_id, info in schedule.items():
                    if info.get("staff_id") == s_id and int(info.get("week")) == int(w):
                        days_used.add(info.get("day"))
                if len(days_used) > 2:
                    errors.append(f"Staff {s_id} exceeds 2 teaching days in week {w}")

        # Block-only professors: single contiguous 2–3 slot block per course/week
        for s_id, staff in inst.staff.items():
            if not getattr(staff, "blocks_only", False):
                continue
            for w in inst.weeks:
                courses_here = {
                    inst.activities[a_id].course_id
                    for a_id, info in schedule.items()
                    if int(info.get("week")) == int(w)
                    and inst.activities[a_id].kind == "LEC"
                    and inst.activities[a_id].prof_id == s_id
                }
                for c_id in courses_here:
                    slots_by_day: dict[str, list[int]] = {}
                    total = 0
                    for a_id, info in schedule.items():
                        act = inst.activities.get(a_id)
                        if act is None:
                            continue
                        if act.week != int(w) or act.kind != "LEC" or act.prof_id != s_id or act.course_id != c_id:
                            continue
                        d = info.get("day")
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
                for a_id, info in schedule.items():
                    if info.get("staff_id") != s_id or int(info.get("week")) != int(w):
                        continue
                    dur = int(info.get("duration"))
                    week_load += dur
                    day_loads[info.get("day")] += dur
                if max_week is not None and week_load > int(max_week):
                    errors.append(f"Staff {s_id} week {w} exceeds weekly cap {max_week}")
                if max_day is not None:
                    for d, load in day_loads.items():
                        if load > int(max_day):
                            errors.append(f"Staff {s_id} day {d} week {w} exceeds daily cap {max_day}")

    return errors
