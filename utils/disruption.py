from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set, Tuple

from utils.domain import Instance


Schedule = Dict[int, Dict[str, Any]]


def _activity_role(kind: str) -> str:
    return "PROF" if str(kind).upper() == "LEC" else "TA"


def _eligible_staff_for_activity(
    inst: Instance,
    schedule: Schedule,
    a_id: int,
    *,
    blocked_staff_id: int,
    week: int,
) -> List[int]:
    info = schedule.get(int(a_id))
    act = inst.activities.get(int(a_id))
    if info is None or act is None:
        return []
    role = _activity_role(str(info.get("kind", act.kind)))
    day = str(info.get("day", ""))
    course_id = int(info.get("course_id", act.course_id))
    candidates: List[int] = []
    for sid, staff in inst.staff.items():
        sid_i = int(sid)
        if sid_i == int(blocked_staff_id):
            continue
        if role == "PROF" and not bool(staff.is_prof):
            continue
        if role == "TA" and bool(staff.is_prof):
            continue
        if int(course_id) not in set(int(c) for c in getattr(staff, "can_teach_courses", set())):
            continue
        if day and day not in set(str(d) for d in getattr(staff, "available_days", set())):
            continue
        allowed_weeks = getattr(staff, "available_weeks", None)
        if allowed_weeks is not None:
            week_set = {int(w) for w in allowed_weeks}
            if week_set and int(week) not in week_set:
                continue
        candidates.append(sid_i)
    return candidates


def _staff_week_load(schedule: Schedule, staff_id: int, week: int) -> int:
    total = 0
    for info in schedule.values():
        if int(info.get("staff_id", -1)) != int(staff_id):
            continue
        if int(info.get("week", -1)) != int(week):
            continue
        total += int(info.get("duration", 0) or 0)
    return int(total)


def apply_staff_outage_week(
    inst: Instance,
    schedule: Schedule,
    *,
    staff_id: int,
    week: int,
) -> tuple[Schedule, Set[int], Set[int]]:
    """
    Reassign activities currently taught by `staff_id` in `week` to alternative
    eligible staff when possible.
    Returns: (updated_schedule, affected_activity_ids, unresolved_activity_ids).
    """
    out: Schedule = {int(a_id): dict(info) for a_id, info in schedule.items()}
    affected: Set[int] = set()
    unresolved: Set[int] = set()
    for a_id, info in out.items():
        if int(info.get("week", -1)) != int(week):
            continue
        if int(info.get("staff_id", -1)) != int(staff_id):
            continue
        affected.add(int(a_id))
        candidates = _eligible_staff_for_activity(
            inst,
            out,
            int(a_id),
            blocked_staff_id=int(staff_id),
            week=int(week),
        )
        if not candidates:
            unresolved.add(int(a_id))
            continue
        candidates.sort(key=lambda sid: (_staff_week_load(out, int(sid), int(week)), int(sid)))
        out[int(a_id)]["staff_id"] = int(candidates[0])
    return out, affected, unresolved


def _room_fits_activity(inst: Instance, a_id: int, room_id: int, schedule: Schedule) -> bool:
    act = inst.activities.get(int(a_id))
    info = schedule.get(int(a_id))
    room = inst.rooms.get(int(room_id))
    if act is None or info is None or room is None:
        return False
    groups = [int(g) for g in info.get("group_ids", act.group_ids)]
    need = sum(int(inst.groups[g].size) for g in groups if g in inst.groups)
    if int(room.capacity) < int(need):
        return False
    kind = str(info.get("kind", act.kind)).upper()
    rtype = str(room.room_type).upper()
    if kind == "LEC" and rtype != "LECTURE":
        return False
    if kind == "TUT" and rtype not in ("LECTURE", "TUTORIAL"):
        return False
    if kind == "LAB":
        if rtype not in ("COMPUTER_LAB", "SPECIALIZED_LAB"):
            return False
        tag = getattr(act, "requires_specialization", None)
        if tag:
            tags = set(str(x).upper() for x in (room.specialization_tags or set()))
            if rtype != "SPECIALIZED_LAB" or str(tag).upper() not in tags:
                return False
    return True


def _room_has_overlap(
    schedule: Schedule,
    *,
    room_id: int,
    week: int,
    day: str,
    slot: int,
    duration: int,
    exclude_activity_id: int,
) -> bool:
    target = set(range(int(slot), int(slot) + int(duration)))
    for b_id, other in schedule.items():
        if int(b_id) == int(exclude_activity_id):
            continue
        if int(other.get("room_id", -1)) != int(room_id):
            continue
        if int(other.get("week", -1)) != int(week):
            continue
        if str(other.get("day", "")) != str(day):
            continue
        other_slots = set(
            range(int(other.get("slot", -1)), int(other.get("slot", -1)) + int(other.get("duration", 0)))
        )
        if target & other_slots:
            return True
    return False


def apply_room_outage_week(
    inst: Instance,
    schedule: Schedule,
    *,
    room_id: int,
    week: int,
) -> tuple[Schedule, Set[int], Set[int]]:
    """
    Reassign activities using `room_id` in `week` to eligible replacement rooms.
    Returns: (updated_schedule, affected_activity_ids, unresolved_activity_ids).
    """
    out: Schedule = {int(a_id): dict(info) for a_id, info in schedule.items()}
    affected: Set[int] = set()
    unresolved: Set[int] = set()
    for a_id, info in out.items():
        if int(info.get("week", -1)) != int(week):
            continue
        if int(info.get("room_id", -1)) != int(room_id):
            continue
        affected.add(int(a_id))
        best_room: int | None = None
        for rid in sorted(int(x) for x in inst.rooms.keys()):
            if int(rid) == int(room_id):
                continue
            if not _room_fits_activity(inst, int(a_id), int(rid), out):
                continue
            if _room_has_overlap(
                out,
                room_id=int(rid),
                week=int(info.get("week", week)),
                day=str(info.get("day", "")),
                slot=int(info.get("slot", 0)),
                duration=int(info.get("duration", 1)),
                exclude_activity_id=int(a_id),
            ):
                continue
            best_room = int(rid)
            break
        if best_room is None:
            unresolved.add(int(a_id))
            continue
        out[int(a_id)]["room_id"] = int(best_room)
    return out, affected, unresolved


def build_freeze_locks(
    schedule: Schedule,
    *,
    unlocked_activity_ids: Iterable[int] | None = None,
) -> Dict[int, Dict[str, int | str]]:
    unlocked = {int(a_id) for a_id in (unlocked_activity_ids or [])}
    locks: Dict[int, Dict[str, int | str]] = {}
    for a_id, info in schedule.items():
        if int(a_id) in unlocked:
            continue
        fixed: Dict[str, int | str] = {
            "day": str(info.get("day", "")),
            "slot": int(info.get("slot", 0)),
        }
        room_id = info.get("room_id")
        if room_id is not None:
            fixed["room_id"] = int(room_id)
        locks[int(a_id)] = fixed
    return locks
