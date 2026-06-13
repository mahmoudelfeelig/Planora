from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

from utils.domain import Instance


def _activity_staff_id(inst: Instance, activity_id: int) -> int:
    act = inst.activities[int(activity_id)]
    return int(act.prof_id if act.kind == "LEC" else act.ta_id)


def eligible_room_ids_for_activity(inst: Instance, activity_id: int) -> List[int]:
    act = inst.activities[int(activity_id)]
    need = sum(
        int(inst.groups[int(g_id)].size)
        for g_id in act.group_ids
        if int(g_id) in inst.groups
    )
    out: List[int] = []
    for room_id, room in inst.rooms.items():
        if int(room.capacity) < int(need):
            continue
        if act.kind == "LEC" and room.room_type == "LECTURE":
            out.append(int(room_id))
        elif act.kind == "TUT" and room.room_type in {"TUTORIAL", "LECTURE"}:
            out.append(int(room_id))
        elif act.kind == "LAB":
            tag = str(getattr(act, "requires_specialization", "") or "").strip()
            if tag:
                if room.room_type == "SPECIALIZED_LAB" and tag in set(room.specialization_tags or []):
                    out.append(int(room_id))
            elif room.room_type in {"COMPUTER_LAB", "SPECIALIZED_LAB"}:
                out.append(int(room_id))
    return sorted(out)


def estimate_cp_model_scale(inst: Instance) -> Dict[str, Any]:
    starts = 0
    room_candidates = 0
    smallest_domains: List[Dict[str, Any]] = []
    for a_id, act in inst.activities.items():
        allowed_start_count = 0
        for day in inst.days:
            staff = inst.staff.get(_activity_staff_id(inst, int(a_id)))
            if staff is not None and day not in set(staff.available_days):
                continue
            allowed_start_count += max(0, int(inst.slots_per_day) - int(act.duration) + 1)
        rooms = eligible_room_ids_for_activity(inst, int(a_id))
        starts += int(allowed_start_count)
        room_candidates += len(rooms)
        smallest_domains.append(
            {
                "activity_id": int(a_id),
                "kind": str(act.kind),
                "week": int(act.week),
                "start_domain": int(allowed_start_count),
                "room_domain": int(len(rooms)),
            }
        )
    smallest_domains.sort(key=lambda row: (int(row["start_domain"]), int(row["room_domain"]), int(row["activity_id"])))

    conflict_edges = 0
    by_week_group: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    by_week_staff: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for a_id, act in inst.activities.items():
        for g_id in act.group_ids:
            by_week_group[(int(act.week), int(g_id))].append(int(a_id))
        by_week_staff[(int(act.week), _activity_staff_id(inst, int(a_id)))].append(int(a_id))
    for bucket in list(by_week_group.values()) + list(by_week_staff.values()):
        n = len(set(bucket))
        if n > 1:
            conflict_edges += n * (n - 1) // 2

    return {
        "activities": int(len(inst.activities)),
        "rooms": int(len(inst.rooms)),
        "weeks": int(len(inst.weeks)),
        "days": int(len(inst.days)),
        "slots_per_day": int(inst.slots_per_day),
        "estimated_start_literals": int(starts),
        "estimated_cp_room_candidates": int(room_candidates),
        "estimated_cp_room_intervals": int(room_candidates),
        "estimated_conflict_edges": int(conflict_edges),
        "smallest_domains": smallest_domains[:12],
    }


def recommend_solver_profile(inst: Instance) -> Dict[str, Any]:
    scale = estimate_cp_model_scale(inst)
    activities = int(scale["activities"])
    room_candidates = int(scale["estimated_cp_room_candidates"])
    if activities >= 1000 or room_candidates >= 50000:
        return {
            "profile": "university_fast",
            "room_mode": "greedy",
            "objective_profile": "fast_feasible",
            "reason": "large activity or room-candidate count; solve times first and assign rooms separately",
        }
    if activities >= 350 or room_candidates >= 12000:
        return {
            "profile": "university_quality",
            "room_mode": "greedy",
            "objective_profile": "balanced",
            "reason": "medium-large case; decoupled rooming with bounded quality improvement",
        }
    return {
        "profile": "verification",
        "room_mode": "cp_rooms",
        "objective_profile": "balanced",
        "reason": "small enough for strict room variables",
    }


def build_decomposition_plan(inst: Instance) -> Dict[str, Any]:
    by_week: List[Dict[str, Any]] = []
    for week in sorted(int(w) for w in inst.weeks):
        act_ids = [int(a_id) for a_id, act in inst.activities.items() if int(act.week) == int(week)]
        staff = {_activity_staff_id(inst, a_id) for a_id in act_ids}
        groups = {
            int(g_id)
            for a_id in act_ids
            for g_id in inst.activities[int(a_id)].group_ids
        }
        by_week.append(
            {
                "week": int(week),
                "activities": int(len(act_ids)),
                "staff": int(len(staff)),
                "groups": int(len(groups)),
            }
        )

    by_program: List[Dict[str, Any]] = []
    for program_id, program in inst.programs.items():
        group_ids = {int(g_id) for g_id in getattr(program, "group_ids", []) or []}
        course_ids = {int(c_id) for c_id in getattr(program, "course_ids", []) or []}
        act_ids = [
            int(a_id)
            for a_id, act in inst.activities.items()
            if int(act.course_id) in course_ids or bool(group_ids & {int(g) for g in act.group_ids})
        ]
        staff = {_activity_staff_id(inst, a_id) for a_id in act_ids}
        by_program.append(
            {
                "program_id": int(program_id),
                "name": str(program.name),
                "activities": int(len(act_ids)),
                "staff": int(len(staff)),
                "groups": int(len(group_ids)),
            }
        )
    by_program.sort(key=lambda row: (-int(row["activities"]), int(row["program_id"])))

    return {
        "recommended_order": [
            "solve_or_relax_by_week",
            "room_assignment_by_slot",
            "repair_cross_program_staff_conflicts",
            "local_search_quality_pass",
        ],
        "week_blocks": by_week,
        "program_blocks": by_program,
    }


def build_feasibility_certificate(inst: Instance) -> Dict[str, Any]:
    scale = estimate_cp_model_scale(inst)
    room_missing: List[Dict[str, Any]] = []
    room_scarcity: List[Dict[str, Any]] = []
    for a_id in sorted(inst.activities):
        rooms = eligible_room_ids_for_activity(inst, int(a_id))
        act = inst.activities[int(a_id)]
        if not rooms:
            room_missing.append(
                {
                    "activity_id": int(a_id),
                    "kind": str(act.kind),
                    "week": int(act.week),
                    "course_id": int(act.course_id),
                }
            )
        elif len(rooms) <= 2:
            room_scarcity.append(
                {
                    "activity_id": int(a_id),
                    "kind": str(act.kind),
                    "week": int(act.week),
                    "eligible_rooms": int(len(rooms)),
                }
            )

    week_capacity = len(inst.days) * int(inst.slots_per_day)
    group_pressure: List[Dict[str, Any]] = []
    for g_id, group in inst.groups.items():
        for week in inst.weeks:
            load = sum(
                int(act.duration)
                for act in inst.activities.values()
                if int(act.week) == int(week) and int(g_id) in {int(g) for g in act.group_ids}
            )
            group_pressure.append(
                {
                    "group_id": int(g_id),
                    "name": str(group.name),
                    "week": int(week),
                    "load": int(load),
                    "capacity": int(week_capacity),
                    "utilization": float(load / week_capacity) if week_capacity else 0.0,
                }
            )
    group_pressure.sort(key=lambda row: (-float(row["utilization"]), -int(row["load"]), int(row["group_id"])))

    staff_pressure: List[Dict[str, Any]] = []
    for staff_id, staff in inst.staff.items():
        for week in inst.weeks:
            load = sum(
                int(act.duration)
                for a_id, act in inst.activities.items()
                if int(act.week) == int(week) and _activity_staff_id(inst, int(a_id)) == int(staff_id)
            )
            cap = getattr(staff, "max_slots_per_week", None)
            staff_pressure.append(
                {
                    "staff_id": int(staff_id),
                    "name": str(staff.name),
                    "week": int(week),
                    "load": int(load),
                    "cap": None if cap is None else int(cap),
                    "utilization": None if cap in (None, 0) else float(load / int(cap)),
                }
            )
    staff_pressure.sort(
        key=lambda row: (
            -float(row["utilization"] if row["utilization"] is not None else 0.0),
            -int(row["load"]),
            int(row["staff_id"]),
        )
    )

    return {
        "scale": scale,
        "recommendation": recommend_solver_profile(inst),
        "decomposition": build_decomposition_plan(inst),
        "room_missing": room_missing[:20],
        "room_scarcity": room_scarcity[:20],
        "group_pressure": group_pressure[:12],
        "staff_pressure": staff_pressure[:12],
    }

