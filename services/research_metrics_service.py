from __future__ import annotations

import hashlib
import json
import math
import statistics
from typing import Any, Iterable

from services.performance_service import estimate_cp_model_scale
from services.institution_policy_readiness_service import (
    evaluate_institution_policy_readiness,
)
from utils.demand import demand_requirement
from utils.distribution_constraints import (
    distribution_capability_report,
    distribution_penalty,
    evaluate_distribution_constraints,
)
from utils.generator import instance_to_json
from utils.specs import validate_schedule_against_instance


def _summary(values: Iterable[float]) -> dict[str, float | int | None]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"count": 0, "mean": None, "median": None, "p90": None, "maximum": None}
    rank = max(0, min(len(ordered) - 1, int(math.ceil(0.90 * len(ordered))) - 1))
    return {
        "count": len(ordered),
        "mean": float(statistics.fmean(ordered)),
        "median": float(statistics.median(ordered)),
        "p90": float(ordered[rank]),
        "maximum": float(ordered[-1]),
    }


def instance_fingerprint(inst) -> str:
    payload = json.dumps(
        instance_to_json(inst),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def evaluate_research_metrics(inst, schedule: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Compute dataset-independent metrics suitable for experiment tables."""
    valid_rows = {
        int(activity_id): row
        for activity_id, row in schedule.items()
        if int(activity_id) in inst.activities and isinstance(row, dict)
    }
    room_fill: list[float] = []
    robust_served = 0
    nominal_served = 0
    scenario_total = 0
    scenario_served = 0
    occupied_room_slots: set[tuple[int, int, str, int]] = set()
    prime_rows = 0
    program_prime: dict[int, list[int]] = {}
    prime_policy = (getattr(inst, "institutional_policy", {}) or {}).get("prime_time", {}) or {}
    prime_days = {str(value) for value in prime_policy.get("days", []) or []}
    prime_slots = {int(value) for value in prime_policy.get("slots", []) or []}

    for activity_id, row in valid_rows.items():
        activity = inst.activities[activity_id]
        room_id = row.get("room_id")
        requirement = demand_requirement(inst, activity.group_ids)
        if room_id is not None and int(room_id) in inst.rooms:
            room = inst.rooms[int(room_id)]
            if int(room.capacity) > 0:
                room_fill.append(float(requirement.nominal / int(room.capacity)))
            nominal_served += int(int(room.capacity) >= int(requirement.nominal))
            robust_served += int(int(room.capacity) >= int(requirement.required))
            scenario_names = {
                str(name)
                for group_id in activity.group_ids
                for name in (getattr(inst.groups.get(int(group_id)), "demand_scenarios", {}) or {})
            }
            for scenario in scenario_names:
                demand = sum(
                    int((getattr(inst.groups[int(group_id)], "demand_scenarios", {}) or {}).get(scenario, inst.groups[int(group_id)].size))
                    for group_id in activity.group_ids
                    if int(group_id) in inst.groups
                )
                scenario_total += 1
                scenario_served += int(int(room.capacity) >= demand)
            for offset in range(int(row.get("duration", activity.duration))):
                occupied_room_slots.add(
                    (
                        int(room_id),
                        int(row["week"]),
                        str(row["day"]),
                        int(row["slot"]) + offset,
                    )
                )

        is_prime = int(str(row.get("day")) in prime_days and int(row.get("slot", -1)) in prime_slots)
        prime_rows += is_prime
        program_ids = {
            int(inst.groups[int(group_id)].program_id)
            for group_id in activity.group_ids
            if int(group_id) in inst.groups
        }
        for program_id in program_ids:
            program_prime.setdefault(program_id, []).append(is_prime)

    possible_room_slots = max(
        1,
        len(inst.rooms) * len(inst.weeks) * len(inst.days) * int(inst.slots_per_day),
    )
    program_shares = {
        str(program_id): float(sum(values) / len(values))
        for program_id, values in sorted(program_prime.items())
        if values
    }
    share_values = list(program_shares.values())
    hard_distribution = evaluate_distribution_constraints(inst, valid_rows, required_only=True)
    soft_distribution = [
        violation
        for violation in evaluate_distribution_constraints(inst, valid_rows)
        if not violation.required
    ]
    hard_errors = validate_schedule_against_instance(
        inst,
        valid_rows,
        strict_rooms=True,
        require_all_activities=True,
    )
    return {
        "schema_version": 1,
        "instance_fingerprint": instance_fingerprint(inst),
        "scale": estimate_cp_model_scale(inst),
        "completeness": float(len(valid_rows) / max(1, len(inst.activities))),
        "hard_conflict_count": len(hard_errors),
        "hard_conflicts": hard_errors[:50],
        "room": {
            "nominal_fill_ratio": _summary(room_fill),
            "time_space_utilization": float(len(occupied_room_slots) / possible_room_slots),
            "nominal_service_rate": float(nominal_served / max(1, len(valid_rows))),
            "robust_service_rate": float(robust_served / max(1, len(valid_rows))),
            "scenario_service_rate": None if scenario_total == 0 else float(scenario_served / scenario_total),
            "scenario_observations": int(scenario_total),
        },
        "prime_time": {
            "configured": bool(prime_days and prime_slots),
            "overall_share": None if not valid_rows else float(prime_rows / len(valid_rows)),
            "share_cap": prime_policy.get("share_cap"),
            "program_shares": program_shares,
            "program_share_range": None if not share_values else float(max(share_values) - min(share_values)),
        },
        "distribution_constraints": {
            "capabilities": distribution_capability_report(inst),
            "hard_violation_units": sum(int(value.units) for value in hard_distribution),
            "soft_violation_units": sum(int(value.units) for value in soft_distribution),
            "soft_penalty": int(distribution_penalty(inst, valid_rows)),
        },
        "demand_policy": dict(getattr(inst, "demand_policy", {}) or {"mode": "nominal"}),
        "institutional_policy_id": str((getattr(inst, "institutional_policy", {}) or {}).get("policy_id", "custom")),
        "institution_policy_readiness": evaluate_institution_policy_readiness(inst),
    }
