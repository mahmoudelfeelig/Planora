from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


def hard_flag(inst, name: str, default: bool = True) -> bool:
    flags = getattr(inst, "hard_constraints", {}) or {}
    if not isinstance(flags, dict):
        return default
    raw = flags.get(name, default)
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    return str(raw).strip().lower() not in ("0", "false", "no")


def _closure_matches(room, closure: Dict[str, Any], *, week: int, day: str, slot: int) -> bool:
    if not isinstance(closure, dict):
        return False
    campus = str(closure.get("campus", "") or "").strip().upper()
    building = str(closure.get("building", "") or "").strip()
    floor = str(closure.get("floor", "") or "").strip()
    if campus and str(getattr(room, "campus", "") or "").strip().upper() != campus:
        return False
    if building and str(getattr(room, "building", "") or "").strip() != building:
        return False
    if floor and str(getattr(room, "floor", "") or "").strip() != floor:
        return False
    week_raw = closure.get("week")
    if week_raw not in (None, "", "ALL"):
        try:
            if int(week_raw) != int(week):
                return False
        except Exception:
            return False
    day_raw = str(closure.get("day", "") or "").strip().upper()
    if day_raw and day_raw != str(day).strip().upper():
        return False
    slots = closure.get("slots")
    if isinstance(slots, (list, tuple, set)):
        try:
            return int(slot) in {int(v) for v in slots}
        except Exception:
            return False
    if closure.get("slot") is not None:
        try:
            return int(closure.get("slot")) == int(slot)
        except Exception:
            return False
    return True


def room_is_available(
    inst,
    room_id: int,
    *,
    week: int,
    day: str,
    start_slot: int,
    dur: int,
) -> bool:
    room = inst.rooms[int(room_id)]
    if hard_flag(inst, "enforce_room_availability", True):
        avail = getattr(room, "availability", None)
        if isinstance(avail, set):
            for off in range(int(dur)):
                if (str(day), int(start_slot) + int(off)) not in avail:
                    return False

    if hard_flag(inst, "enforce_building_closures", True):
        for off in range(int(dur)):
            cur_slot = int(start_slot) + int(off)
            for closure in getattr(inst, "room_closures", []) or []:
                if _closure_matches(room, closure, week=int(week), day=str(day), slot=int(cur_slot)):
                    return False
    return True


def calendar_slot_blocked(inst, *, week: int, day: str) -> bool:
    if not hard_flag(inst, "enforce_calendar_rules", True):
        return False
    rules = getattr(inst, "calendar_rules", {}) or {}
    blackout_weeks = {int(w) for w in (rules.get("blackout_weeks") or [])}
    if int(week) in blackout_weeks:
        return True

    special = rules.get("special_weeks", {}) or {}
    if isinstance(special, dict):
        for cfg in special.values():
            if not isinstance(cfg, dict):
                continue
            try:
                cfg_week = int(cfg.get("week"))
            except Exception:
                cfg_week = None
            if cfg_week is not None and int(cfg_week) == int(week):
                blocked_days = {
                    str(v).strip().upper()
                    for v in (cfg.get("blocked_days") or [])
                    if str(v).strip()
                }
                if str(day).strip().upper() in blocked_days:
                    return True

    for token in rules.get("holiday_dates", []) or []:
        text = str(token).strip().upper()
        if not text.startswith("W") or "-" not in text:
            continue
        prefix, suffix = text.split("-", 1)
        try:
            token_week = int(prefix[1:])
        except Exception:
            continue
        if int(token_week) == int(week) and suffix == str(day).strip().upper():
            return True
    return False


def room_transition_buffer(inst, room_a, room_b) -> int:
    if not hard_flag(inst, "enforce_travel_time_buffers", True):
        return 0
    if room_a is None or room_b is None:
        return 0
    rules = getattr(inst, "travel_time_rules", {}) or {}
    same_building = int(rules.get("same_building", 0) or 0)
    cross_floor = int(rules.get("cross_floor", 0) or 0)
    cross_building = int(rules.get("cross_building", 0) or 0)
    cross_campus = int(rules.get("cross_campus", 0) or 0)
    campus_a = str(getattr(room_a, "campus", "") or "").strip().upper()
    campus_b = str(getattr(room_b, "campus", "") or "").strip().upper()
    building_a = str(getattr(room_a, "building", "") or "").strip()
    building_b = str(getattr(room_b, "building", "") or "").strip()
    floor_a = str(getattr(room_a, "floor", "") or "").strip()
    floor_b = str(getattr(room_b, "floor", "") or "").strip()
    if campus_a and campus_b and campus_a != campus_b:
        return int(cross_campus)
    if building_a and building_b and building_a == building_b and floor_a and floor_b and floor_a != floor_b:
        return int(cross_floor)
    if building_a and building_b and building_a != building_b:
        return int(cross_building)
    return int(same_building)


def precedence_violations(inst, schedule: Dict[int, Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    if not hard_flag(inst, "enforce_precedence_rules", True):
        return out
    rules = getattr(inst, "precedence_rules", []) or []
    day_index = {str(day): idx for idx, day in enumerate(getattr(inst, "days", []) or [])}
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        try:
            before_id = int(rule.get("before_activity_id"))
            after_id = int(rule.get("after_activity_id"))
        except Exception:
            continue
        before = schedule.get(int(before_id))
        after = schedule.get(int(after_id))
        if before is None or after is None:
            continue
        min_gap = int(rule.get("min_gap_slots", 0) or 0)
        before_pos = (
            int(before["week"]),
            int(day_index.get(str(before["day"]), -1)),
            int(before["slot"]),
            int(before["slot"]) + int(before["duration"]),
        )
        after_pos = (
            int(after["week"]),
            int(day_index.get(str(after["day"]), -1)),
            int(after["slot"]),
            int(after["slot"]) + int(after["duration"]),
        )
        if before_pos[:2] > after_pos[:2]:
            out.append(f"precedence A{before_id} -> A{after_id} violated (later week/day)")
            continue
        if before_pos[:2] == after_pos[:2]:
            if int(before_pos[3]) + int(min_gap) > int(after_pos[2]):
                out.append(
                    f"precedence A{before_id} -> A{after_id} violated (gap {min_gap} slots)"
                )
    return out


def travel_buffer_violations(inst, schedule: Dict[int, Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    if not hard_flag(inst, "enforce_travel_time_buffers", True):
        return out
    if not getattr(inst, "travel_time_rules", None):
        return out
    ids = sorted(int(a_id) for a_id in schedule.keys())
    day_index = {str(day): idx for idx, day in enumerate(getattr(inst, "days", []) or [])}
    for i, a_id in enumerate(ids):
        a = schedule[int(a_id)]
        for b_id in ids[i + 1 :]:
            b = schedule[int(b_id)]
            if int(a["week"]) != int(b["week"]) or str(a["day"]) != str(b["day"]):
                continue
            share_staff = int(a.get("staff_id", -1)) == int(b.get("staff_id", -2))
            share_group = bool(set(int(x) for x in a.get("group_ids", [])) & set(int(x) for x in b.get("group_ids", [])))
            if not (share_staff or share_group):
                continue
            room_a = inst.rooms.get(int(a["room_id"])) if a.get("room_id") is not None else None
            room_b = inst.rooms.get(int(b["room_id"])) if b.get("room_id") is not None else None
            buffer_slots = room_transition_buffer(inst, room_a, room_b)
            if int(buffer_slots) <= 0:
                continue
            a_end = int(a["slot"]) + int(a["duration"])
            b_end = int(b["slot"]) + int(b["duration"])
            gap = int(b["slot"]) - a_end if int(a["slot"]) <= int(b["slot"]) else int(a["slot"]) - b_end
            if gap < int(buffer_slots):
                out.append(
                    f"travel buffer violated between A{a_id} and A{b_id} "
                    f"({buffer_slots} slot buffer required)"
                )
    return out


def evaluate_sla_targets(inst, schedule: Dict[int, Dict[str, Any]], *, soft_penalty: int | None = None, hard_conflicts: int = 0) -> Dict[str, Any]:
    targets = getattr(inst, "sla_targets", {}) or {}
    result = {"targets": dict(targets), "passed": True, "violations": []}
    if not isinstance(targets, dict):
        return result
    if "max_hard_conflicts" in targets and int(hard_conflicts) > int(targets["max_hard_conflicts"]):
        result["passed"] = False
        result["violations"].append("max_hard_conflicts")
    if soft_penalty is not None and "max_soft_penalty" in targets and int(soft_penalty) > int(targets["max_soft_penalty"]):
        result["passed"] = False
        result["violations"].append("max_soft_penalty")
    return result


def generic_resource_violations(inst, schedule: Dict[int, Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    resources = getattr(inst, "generic_resources", {}) or {}
    if not resources:
        return out
    usage: Dict[Tuple[int, int, str, int], List[int]] = {}
    for a_id, info in schedule.items():
        act = getattr(inst, "activities", {}).get(int(a_id))
        if act is None:
            continue
        week = int(info.get("week", getattr(act, "week", 0)))
        day = str(info.get("day", ""))
        slot = int(info.get("slot", 0))
        dur = int(info.get("duration", getattr(act, "duration", 1)))
        for resource_id in getattr(act, "resource_ids", []) or []:
            if int(resource_id) not in resources:
                out.append(f"A{int(a_id)} references unknown generic resource {int(resource_id)}")
                continue
            resource = resources[int(resource_id)]
            avail = getattr(resource, "availability", None)
            for off in range(int(dur)):
                cur_slot = int(slot) + int(off)
                if isinstance(avail, set) and (str(day), int(cur_slot)) not in avail:
                    out.append(
                        f"A{int(a_id)} generic resource {int(resource_id)} unavailable at {day} slot {int(cur_slot)}"
                    )
                key = (int(resource_id), int(week), str(day), int(cur_slot))
                usage.setdefault(key, []).append(int(a_id))
    for (resource_id, week, day, slot), occupants in usage.items():
        resource = resources.get(int(resource_id))
        if resource is None:
            continue
        cap = max(1, int(getattr(resource, "capacity", 1) or 1))
        unique = sorted(set(int(a_id) for a_id in occupants))
        if len(unique) > cap:
            out.append(
                f"Generic resource overlap R{int(resource_id)} at W{int(week)} {day} S{int(slot) + 1}: {unique}"
            )
    return out


def generic_resources_available(
    inst,
    resource_ids: Iterable[int],
    *,
    day: str,
    start_slot: int,
    dur: int,
) -> bool:
    resources = getattr(inst, "generic_resources", {}) or {}
    for resource_id in resource_ids or []:
        resource = resources.get(int(resource_id))
        if resource is None:
            return False
        avail = getattr(resource, "availability", None)
        if isinstance(avail, set):
            for off in range(int(dur)):
                if (str(day), int(start_slot) + int(off)) not in avail:
                    return False
    return True
