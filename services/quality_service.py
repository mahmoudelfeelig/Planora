from __future__ import annotations

from typing import Any, Dict

from core.metaheuristics import LocalSearchImprover
from utils.schedule_rules import evaluate_sla_targets


SOFT_WEIGHT_DEFAULTS: Dict[str, int] = {
    "stud_free_days": 10,
    "stud_free_mf": 5,
    "stud_gaps": 5,
    "staff_free_day": 6,
    "active_days": 5,
    "late_start": 3,
    "thin_day": 3,
    "stability": 1,
    "room_consistency": 1,
    "single_slot": 6,
    "same_kind_week": 3,
}


def load_soft_weights(inst) -> Dict[str, int]:
    weights = dict(SOFT_WEIGHT_DEFAULTS)
    overrides = getattr(inst, "soft_weights", None)
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            try:
                weights[str(key)] = int(value)
            except Exception:
                continue
    return weights


def compute_penalty_breakdown(inst, schedule: Dict[int, Dict[str, Any]]) -> Dict[str, int]:
    weights = load_soft_weights(inst)
    improver = LocalSearchImprover(inst)
    total = int(improver.compute_soft_penalty(schedule))
    # Reuse the current scorer while providing a structured, explainable breakdown.
    breakdown: Dict[str, int] = {
        "total": int(total),
        "stud_free_days": 0,
        "stud_free_mf": 0,
        "stud_gaps": 0,
        "staff_free_day": 0,
        "active_days": 0,
        "late_start": 0,
        "thin_day": 0,
        "stability": 0,
        "room_consistency": 0,
        "single_slot": 0,
        "same_kind_week": 0,
    }

    days = list(inst.days)
    weeks = list(inst.weeks)
    slots = int(inst.slots_per_day)
    group_occ = {(g, w, d, s): 0 for g in inst.groups for w in weeks for d in days for s in range(slots)}
    staff_occ = {(s_id, w, d, s): 0 for s_id in inst.staff for w in weeks for d in days for s in range(slots)}
    for info in schedule.values():
        w = int(info["week"])
        d = str(info["day"])
        s0 = int(info["slot"])
        dur = int(info["duration"])
        st_id = int(info["staff_id"])
        for off in range(dur):
            s = s0 + off
            if 0 <= s < slots:
                staff_occ[(st_id, w, d, s)] = 1
                for g_id in info["group_ids"]:
                    group_occ[(int(g_id), w, d, s)] = 1

    group_day_active = {
        (g, w, d): int(any(group_occ[(g, w, d, s)] for s in range(slots)))
        for g in inst.groups for w in weeks for d in days
    }
    staff_day_active = {
        (s_id, w, d): int(any(staff_occ[(s_id, w, d, s)] for s in range(slots)))
        for s_id in inst.staff for w in weeks for d in days
    }
    workdays = [d for d in days if d in {"MON", "TUE", "WED", "THU", "FRI"}]

    for g_id, group in inst.groups.items():
        preferred = int(getattr(group, "preferred_free_days", 0) or 0)
        for w in weeks:
            free_days = sum(1 - group_day_active[(g_id, w, d)] for d in days)
            if free_days < preferred:
                breakdown["stud_free_days"] += int(weights["stud_free_days"]) * int(preferred - free_days)
            free_mf = sum(1 - group_day_active[(g_id, w, d)] for d in workdays)
            if free_mf < preferred:
                breakdown["stud_free_mf"] += int(weights["stud_free_mf"]) * int(preferred - free_mf)
            active_days = sum(group_day_active[(g_id, w, d)] for d in days)
            if active_days > 3:
                breakdown["active_days"] += int(weights["active_days"]) * int(active_days - 3)
            for d in days:
                occ = [group_occ[(g_id, w, d, s)] for s in range(slots)]
                blocks = 0
                prev = 0
                load = 0
                first_slot = None
                for idx, value in enumerate(occ):
                    if value == 1 and prev == 0:
                        blocks += 1
                    if value == 1:
                        load += 1
                        if first_slot is None:
                            first_slot = idx
                    prev = value
                if blocks > 1:
                    breakdown["stud_gaps"] += int(weights["stud_gaps"]) * int(blocks - 1)
                if load == 1:
                    breakdown["single_slot"] += int(weights["single_slot"])
                if load == 2:
                    breakdown["thin_day"] += int(weights["thin_day"])
                if load > 0 and first_slot is not None and int(first_slot) >= 2:
                    breakdown["late_start"] += int(weights["late_start"])

    for s_id in inst.staff.keys():
        for w in weeks:
            free_days = sum(1 - staff_day_active[(s_id, w, d)] for d in days)
            if free_days < 1:
                breakdown["staff_free_day"] += int(weights["staff_free_day"]) * int(1 - free_days)

    for g_id in inst.groups.keys():
        for wi in range(1, len(weeks)):
            w_prev = weeks[wi - 1]
            w_curr = weeks[wi]
            for d in days:
                if group_day_active[(g_id, w_prev, d)] != group_day_active[(g_id, w_curr, d)]:
                    breakdown["stability"] += int(weights["stability"])

    key_to_rooms = {}
    for info in schedule.values():
        c_id = int(info["course_id"])
        kind = str(info["kind"])
        room = info.get("room_id")
        for g_id in info["group_ids"]:
            key = (c_id, int(g_id), kind)
            key_to_rooms.setdefault(key, set()).add(room)
    for rooms in key_to_rooms.values():
        if None in rooms:
            continue
        if len(rooms) > 1:
            breakdown["room_consistency"] += int(weights["room_consistency"]) * int(len(rooms) - 1)

    for g_id in inst.groups.keys():
        for w in weeks:
            counts: Dict[tuple[int, str], int] = {}
            for info in schedule.values():
                if int(info["week"]) != int(w):
                    continue
                kind = str(info.get("kind", ""))
                if kind not in ("LEC", "TUT"):
                    continue
                if int(g_id) not in {int(x) for x in info.get("group_ids", [])}:
                    continue
                key = (int(info["course_id"]), kind)
                counts[key] = int(counts.get(key, 0)) + 1
            for cnt in counts.values():
                if int(cnt) > 1:
                    breakdown["same_kind_week"] += int(weights["same_kind_week"]) * int(cnt - 1)

    return breakdown


def explain_solution_ranking(
    inst,
    base_schedule: Dict[int, Dict[str, Any]],
    candidate_schedule: Dict[int, Dict[str, Any]],
    *,
    base_label: str = "base",
    candidate_label: str = "candidate",
) -> str:
    base = compute_penalty_breakdown(inst, base_schedule)
    cand = compute_penalty_breakdown(inst, candidate_schedule)
    deltas = []
    for key in base.keys():
        if key == "total":
            continue
        delta = int(cand.get(key, 0)) - int(base.get(key, 0))
        if delta != 0:
            deltas.append((abs(delta), key, delta))
    deltas.sort(reverse=True)
    if not deltas:
        return f"{candidate_label} matches {base_label} on all modeled soft-penalty terms."
    top = deltas[:4]
    parts = [
        f"{candidate_label} total {int(cand['total'])} vs {base_label} {int(base['total'])}."
    ]
    for _abs_delta, key, delta in top:
        direction = "improved" if int(delta) < 0 else "worsened"
        parts.append(f"{key}: {direction} by {abs(int(delta))}")
    return " ".join(parts)


def rank_penalty_drivers(
    inst,
    schedule: Dict[int, Dict[str, Any]],
    *,
    limit: int = 6,
) -> list[Dict[str, Any]]:
    breakdown = compute_penalty_breakdown(inst, schedule)
    total = max(1, int(breakdown.get("total", 0)))
    rows: list[Dict[str, Any]] = []
    for key, value in breakdown.items():
        if key == "total" or int(value) <= 0:
            continue
        rows.append(
            {
                "term": str(key),
                "penalty": int(value),
                "share": float(int(value) / total),
            }
        )
    rows.sort(key=lambda row: (-int(row["penalty"]), str(row["term"])))
    return rows[: max(1, int(limit))]


def evaluate_schedule_sla(inst, schedule: Dict[int, Dict[str, Any]], *, hard_conflicts: int = 0) -> Dict[str, Any]:
    breakdown = compute_penalty_breakdown(inst, schedule)
    return evaluate_sla_targets(
        inst,
        schedule,
        soft_penalty=int(breakdown.get("total", 0)),
        hard_conflicts=int(hard_conflicts),
    )
