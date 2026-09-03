from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

from utils.domain import Instance


Schedule = Dict[int, Dict[str, Any]]


def _percentile(values: List[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * float(probability)
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _gini(values: List[float]) -> float:
    nonnegative = sorted(max(0.0, float(value)) for value in values)
    if not nonnegative or sum(nonnegative) == 0:
        return 0.0
    n = len(nonnegative)
    weighted = sum((index + 1) * value for index, value in enumerate(nonnegative))
    return (2.0 * weighted) / (n * sum(nonnegative)) - (n + 1.0) / n


def _jain_index(values: List[float]) -> float:
    nonnegative = [max(0.0, float(value)) for value in values]
    if not nonnegative or sum(value * value for value in nonnegative) == 0:
        return 1.0
    return (sum(nonnegative) ** 2) / (
        len(nonnegative) * sum(value * value for value in nonnegative)
    )


def _distribution_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    burdens = [float(row["fairness_score"]) for row in rows]
    rates = [float(row["burden_per_slot"]) for row in rows]
    return {
        "count": len(rows),
        "total_burden": float(round(sum(burdens), 4)),
        "mean_fairness_score": float(round(sum(burdens) / max(1, len(burdens)), 4)),
        "median_burden": float(round(_percentile(burdens, 0.5), 4)),
        "p90_burden": float(round(_percentile(burdens, 0.9), 4)),
        "max_burden": float(round(max(burdens, default=0.0), 4)),
        "max_burden_per_slot": float(round(max(rates, default=0.0), 6)),
        "gini_burden": float(round(_gini(burdens), 6)),
        "jain_equality_index": float(round(_jain_index(burdens), 6)),
        "worst": rows[:5],
    }


def fairness_lexicographic_key(dashboard: Dict[str, Any]) -> Tuple[float, ...]:
    """Lower is better: protect the worst-off group before reducing tail and total burden."""
    summary = dict(dashboard.get("summary", {}) or {})
    groups = dict(summary.get("groups", {}) or {})
    staff = dict(summary.get("staff", {}) or {})
    return (
        float(groups.get("max_burden", 0.0)),
        float(groups.get("p90_burden", 0.0)),
        float(groups.get("total_burden", 0.0)),
        float(staff.get("max_burden", 0.0)),
        float(staff.get("total_burden", 0.0)),
    )


def _entity_day_slots(
    schedule: Schedule,
    *,
    week: int,
    day: str,
    pred,
) -> List[Tuple[int, int]]:
    slots: List[Tuple[int, int]] = []
    for info in schedule.values():
        if int(info.get("week", -1)) != int(week):
            continue
        if str(info.get("day", "")) != str(day):
            continue
        if not pred(info):
            continue
        s0 = int(info.get("slot", 0))
        dur = int(info.get("duration", 1))
        slots.append((s0, max(1, dur)))
    return slots


def _gap_count(day_slots: List[Tuple[int, int]]) -> int:
    if not day_slots:
        return 0
    occupied: List[int] = []
    for start, dur in day_slots:
        for s in range(int(start), int(start) + int(max(1, dur))):
            occupied.append(int(s))
    occ = sorted(set(occupied))
    if len(occ) <= 1:
        return 0
    gaps = 0
    for i in range(1, len(occ)):
        if occ[i] > occ[i - 1] + 1:
            gaps += int(occ[i] - occ[i - 1] - 1)
    return int(gaps)


def _late_count(day_slots: List[Tuple[int, int]], *, late_start_slot: int = 3) -> int:
    count = 0
    for start, _dur in day_slots:
        if int(start) >= int(late_start_slot):
            count += 1
    return int(count)


def compute_fairness_dashboard(inst: Instance, schedule: Schedule) -> Dict[str, Any]:
    """
    Computes operational fairness metrics for groups and staff.
    """
    weeks = [int(w) for w in inst.weeks]
    days = [str(d) for d in inst.days]
    group_rows: List[Dict[str, Any]] = []
    staff_rows: List[Dict[str, Any]] = []

    for g_id, group in inst.groups.items():
        total_slots = 0
        active_days = 0
        single_days = 0
        gap_slots = 0
        late_events = 0
        weekly_load: Dict[int, int] = defaultdict(int)
        for w in weeks:
            for d in days:
                day_slots = _entity_day_slots(
                    schedule,
                    week=int(w),
                    day=str(d),
                    pred=lambda info, gid=int(g_id): int(gid) in set(int(x) for x in info.get("group_ids", [])),
                )
                day_load = sum(int(max(1, dur)) for _s, dur in day_slots)
                if day_load > 0:
                    active_days += 1
                    weekly_load[int(w)] += int(day_load)
                    total_slots += int(day_load)
                    if day_load == 1:
                        single_days += 1
                gap_slots += _gap_count(day_slots)
                late_events += _late_count(day_slots)
        average_weekly_load = (
            float(sum(weekly_load.values())) / float(max(1, len(weeks)))
            if weeks
            else 0.0
        )
        fairness_score = float(gap_slots + (2 * single_days) + late_events)
        group_rows.append(
            {
                "id": int(g_id),
                "name": str(group.name),
                "total_slots": int(total_slots),
                "active_days": int(active_days),
                "single_days": int(single_days),
                "gap_slots": int(gap_slots),
                "late_events": int(late_events),
                "avg_weekly_load": float(round(average_weekly_load, 2)),
                "fairness_score": float(round(fairness_score, 2)),
                "burden_per_slot": float(round(fairness_score / max(1, total_slots), 6)),
            }
        )

    for s_id, staff in inst.staff.items():
        total_slots = 0
        active_days = 0
        single_days = 0
        gap_slots = 0
        late_events = 0
        weekly_load: Dict[int, int] = defaultdict(int)
        for w in weeks:
            for d in days:
                day_slots = _entity_day_slots(
                    schedule,
                    week=int(w),
                    day=str(d),
                    pred=lambda info, sid=int(s_id): int(info.get("staff_id", -1)) == int(sid),
                )
                day_load = sum(int(max(1, dur)) for _s, dur in day_slots)
                if day_load > 0:
                    active_days += 1
                    weekly_load[int(w)] += int(day_load)
                    total_slots += int(day_load)
                    if day_load == 1:
                        single_days += 1
                gap_slots += _gap_count(day_slots)
                late_events += _late_count(day_slots)
        average_weekly_load = (
            float(sum(weekly_load.values())) / float(max(1, len(weeks)))
            if weeks
            else 0.0
        )
        fairness_score = float(gap_slots + (2 * single_days) + late_events)
        staff_rows.append(
            {
                "id": int(s_id),
                "name": str(staff.name),
                "role": "PROF" if bool(staff.is_prof) else "TA",
                "total_slots": int(total_slots),
                "active_days": int(active_days),
                "single_days": int(single_days),
                "gap_slots": int(gap_slots),
                "late_events": int(late_events),
                "avg_weekly_load": float(round(average_weekly_load, 2)),
                "fairness_score": float(round(fairness_score, 2)),
                "burden_per_slot": float(round(fairness_score / max(1, total_slots), 6)),
            }
        )

    group_rows.sort(key=lambda row: (-float(row["fairness_score"]), int(row["id"])))
    staff_rows.sort(key=lambda row: (-float(row["fairness_score"]), int(row["id"])))

    summary = {
        "groups": _distribution_summary(group_rows),
        "staff": _distribution_summary(staff_rows),
        "interpretation": {
            "burden": "Lower is better; score combines gaps, single-slot days, and late events.",
            "gini_burden": "Zero is equal; one approaches maximal inequality.",
            "jain_equality_index": "One is equal; values closer to zero are more unequal.",
        },
    }
    return {
        "groups": group_rows,
        "staff": staff_rows,
        "summary": summary,
    }
