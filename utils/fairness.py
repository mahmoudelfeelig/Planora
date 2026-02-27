from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

from utils.domain import Instance


Schedule = Dict[int, Dict[str, Any]]


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
            }
        )

    group_rows.sort(key=lambda row: (-float(row["fairness_score"]), int(row["id"])))
    staff_rows.sort(key=lambda row: (-float(row["fairness_score"]), int(row["id"])))

    summary = {
        "groups": {
            "count": int(len(group_rows)),
            "mean_fairness_score": float(
                round(
                    sum(float(r["fairness_score"]) for r in group_rows) / float(max(1, len(group_rows))),
                    2,
                )
            ),
            "worst": group_rows[:5],
        },
        "staff": {
            "count": int(len(staff_rows)),
            "mean_fairness_score": float(
                round(
                    sum(float(r["fairness_score"]) for r in staff_rows) / float(max(1, len(staff_rows))),
                    2,
                )
            ),
            "worst": staff_rows[:5],
        },
    }
    return {
        "groups": group_rows,
        "staff": staff_rows,
        "summary": summary,
    }
