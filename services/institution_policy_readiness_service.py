from __future__ import annotations

from collections import Counter
from typing import Any

from utils.distribution_constraints import (
    distribution_capability_report,
    normalize_distribution_type,
)
from utils.domain import Instance


def _active_group_ids(inst: Instance) -> set[int]:
    return {
        int(group_id)
        for activity in inst.activities.values()
        for group_id in activity.group_ids
        if int(group_id) in inst.groups
    }


def _coverage(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 1.0


def evaluate_institution_policy_readiness(inst: Instance) -> dict[str, Any]:
    """Explain whether configured policy semantics have enough source data.

    A solver flag is not evidence that an institution supplied the underlying
    calendar, travel, availability, or demand data.  This report keeps those
    two questions separate and is safe to expose in research artifacts or an
    administrator preflight.
    """

    policy = dict(getattr(inst, "institutional_policy", {}) or {})
    hard = dict(getattr(inst, "hard_constraints", {}) or {})
    demand_policy = dict(getattr(inst, "demand_policy", {}) or {"mode": "nominal"})
    checks: list[dict[str, Any]] = []

    def add(
        check_id: str,
        label: str,
        status: str,
        *,
        enforcement: str,
        evidence: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        checks.append(
            {
                "id": str(check_id),
                "label": str(label),
                "status": str(status),
                "enforcement": str(enforcement),
                "evidence": str(evidence),
                "details": dict(details or {}),
            }
        )

    if hard.get("enforce_room_capacity", False):
        capacities = [int(room.capacity) for room in inst.rooms.values()]
        sizes = [int(inst.groups[group_id].size) for group_id in _active_group_ids(inst)]
        complete = bool(capacities and sizes and min(capacities) > 0 and min(sizes) >= 0)
        add(
            "room_capacity",
            "Room capacity",
            "pass" if complete else "missing",
            enforcement="hard",
            evidence="Room capacities and active-group enrollment are present."
            if complete
            else "Hard capacity is enabled but positive room capacity and enrollment data are incomplete.",
            details={"rooms": len(capacities), "active_groups": len(sizes)},
        )
    else:
        add(
            "room_capacity",
            "Room capacity",
            "not_enabled",
            enforcement="none",
            evidence="Room overflow is not configured as a hard institutional rule.",
        )

    if hard.get("enforce_room_availability", False):
        explicit = sum(room.availability is not None for room in inst.rooms.values())
        status = "pass" if explicit == len(inst.rooms) and explicit > 0 else "warning"
        add(
            "room_availability",
            "Room availability",
            status,
            enforcement="hard",
            evidence=(
                "Every room has an explicit availability domain."
                if status == "pass"
                else "Rooms without an explicit domain are treated as always available; confirm that this is intentional."
            ),
            details={
                "explicit_rooms": int(explicit),
                "total_rooms": len(inst.rooms),
                "coverage": _coverage(explicit, len(inst.rooms)),
            },
        )
    else:
        add(
            "room_availability",
            "Room availability",
            "not_enabled",
            enforcement="none",
            evidence="Room availability filtering is disabled.",
        )

    if hard.get("enforce_calendar_rules", False):
        configured = bool(getattr(inst, "calendar_rules", {}) or {})
        add(
            "calendar_rules",
            "Academic calendar",
            "pass" if configured else "missing",
            enforcement="hard",
            evidence="Calendar blackout rules are present."
            if configured
            else "Calendar enforcement is enabled but no blackout or holiday rules were supplied.",
        )
    else:
        add(
            "calendar_rules",
            "Academic calendar",
            "not_enabled",
            enforcement="none",
            evidence="Calendar blackout enforcement is disabled.",
        )

    if hard.get("enforce_building_closures", False):
        configured = bool(getattr(inst, "room_closures", []) or [])
        add(
            "building_closures",
            "Building closures",
            "pass" if configured else "missing",
            enforcement="hard",
            evidence="At least one explicit closure rule is present."
            if configured
            else "Closure enforcement is enabled but no closure dataset was supplied.",
        )
    else:
        add(
            "building_closures",
            "Building closures",
            "not_enabled",
            enforcement="none",
            evidence="Building-closure enforcement is disabled.",
        )

    if hard.get("enforce_travel_time_buffers", False):
        rules = dict(getattr(inst, "travel_time_rules", {}) or {})
        located = sum(bool(room.campus and room.building) for room in inst.rooms.values())
        complete = bool(rules) and located == len(inst.rooms) and located > 0
        add(
            "travel_time_buffers",
            "Travel-time buffers",
            "pass" if complete else "missing",
            enforcement="hard",
            evidence=(
                "Travel rules and campus/building locations cover every room."
                if complete
                else "Travel enforcement needs nonempty buffer rules and campus/building data for every room."
            ),
            details={
                "rules": sorted(rules),
                "located_rooms": int(located),
                "total_rooms": len(inst.rooms),
            },
        )
    else:
        add(
            "travel_time_buffers",
            "Travel-time buffers",
            "not_enabled",
            enforcement="none",
            evidence="Travel-time enforcement is disabled.",
        )

    if hard.get("enforce_standard_start_slots", False):
        raw_value = policy.get("standard_start_slots") or []
        raw_starts = list(raw_value) if isinstance(raw_value, (list, tuple, set)) else []
        valid_starts = sorted(
            {
                int(value)
                for value in raw_starts
                if isinstance(value, int) and 0 <= int(value) < int(inst.slots_per_day)
            }
        )
        complete = bool(valid_starts) and len(valid_starts) == len(raw_starts)
        add(
            "standard_start_slots",
            "Standard start times",
            "pass" if complete else "missing",
            enforcement="hard",
            evidence="A valid institution start-slot domain is present."
            if complete
            else "Standard-start enforcement is enabled but the configured slot list is empty or invalid.",
            details={"slots": valid_starts},
        )
    else:
        add(
            "standard_start_slots",
            "Standard start times",
            "not_enabled",
            enforcement="none",
            evidence="Nonstandard starts are permitted by this preset.",
        )

    active_groups = _active_group_ids(inst)
    demand_mode = str(demand_policy.get("mode") or "nominal").strip().lower()
    if demand_mode in {"quantile", "worst_case"}:
        covered = sum(
            bool(getattr(inst.groups[group_id], "demand_scenarios", {}) or {})
            for group_id in active_groups
        )
        ratio = _coverage(covered, len(active_groups))
        status = "pass" if ratio == 1.0 else "missing" if covered == 0 else "warning"
        add(
            "demand_scenarios",
            "Enrollment scenarios",
            status,
            enforcement="room-demand domain",
            evidence=(
                "Every active group has named enrollment scenarios."
                if status == "pass"
                else "Scenario-based demand falls back to nominal values for groups without forecasts."
            ),
            details={"mode": demand_mode, "covered_groups": covered, "active_groups": len(active_groups), "coverage": ratio},
        )
    elif demand_mode == "budgeted":
        covered = sum(int(inst.groups[group_id].demand_deviation) > 0 for group_id in active_groups)
        ratio = _coverage(covered, len(active_groups))
        gamma = float(demand_policy.get("gamma", 0.0) or 0.0)
        complete = ratio == 1.0 and gamma > 0.0
        add(
            "demand_deviations",
            "Budgeted enrollment uncertainty",
            "pass" if complete else "missing",
            enforcement="room-demand domain",
            evidence=(
                "Every active group has a positive deviation and the uncertainty budget is positive."
                if complete
                else "Budgeted demand needs positive group deviations and a positive gamma value."
            ),
            details={"gamma": gamma, "covered_groups": covered, "active_groups": len(active_groups), "coverage": ratio},
        )
    else:
        add(
            "nominal_demand",
            "Nominal enrollment demand",
            "pass",
            enforcement="room-demand domain",
            evidence="Current group enrollment is used without a forecast claim.",
            details={"mode": demand_mode},
        )

    prime = policy.get("prime_time") or {}
    if prime:
        complete = bool(prime.get("days") and prime.get("slots") and prime.get("share_cap") is not None)
        add(
            "prime_time",
            "Prime-time allocation",
            "pass" if complete else "missing",
            enforcement="diagnostic_only",
            evidence=(
                "Prime-time windows and share target are available for reporting; the CP objective does not enforce the cap."
                if complete
                else "Prime-time reporting needs days, slots, and a share cap."
            ),
        )

    if policy.get("room_target_fill") is not None:
        try:
            room_target = float(policy["room_target_fill"])
        except (TypeError, ValueError):
            room_target = -1.0
        valid_target = 0.0 <= room_target <= 1.0
        add(
            "room_target_fill",
            "Room-fill target",
            "pass" if valid_target else "missing",
            enforcement="diagnostic_only",
            evidence=(
                "The target is reported as a metric and is not a hard lower-bound constraint."
                if valid_target
                else "Room-fill targets must be a ratio between zero and one."
            ),
            details={"target": room_target},
        )

    distribution = distribution_capability_report(inst)
    hard_cp_unsupported: list[str] = []
    for constraint in getattr(inst, "distribution_constraints", []) or []:
        if not bool(constraint.required):
            continue
        try:
            kind = normalize_distribution_type(constraint.constraint_type)
        except ValueError:
            hard_cp_unsupported.append(str(constraint.id))
            continue
        if kind not in set(distribution["hard_cp_types"]):
            hard_cp_unsupported.append(str(constraint.id))
    if distribution["total"]:
        unsupported = len(distribution["unsupported"]) + len(hard_cp_unsupported)
        add(
            "distribution_constraints",
            "Institution distribution constraints",
            "pass" if unsupported == 0 else "unsupported",
            enforcement="hard_or_soft_by_constraint",
            evidence="Every imported constraint has an exact validation and hard-CP path."
            if unsupported == 0
            else "One or more imported hard constraints lack a CP compilation and must not be silently weakened.",
            details={
                "total": int(distribution["total"]),
                "parser_unsupported": list(distribution["unsupported"]),
                "hard_cp_unsupported_ids": hard_cp_unsupported,
            },
        )

    known_missing = [
        str(value)
        for value in policy.get("known_missing_evidence", []) or []
        if str(value).strip()
    ]
    if known_missing:
        add(
            "institution_evidence",
            "Institutional evidence and sign-off",
            "missing",
            enforcement="governance",
            evidence="The preset declares unresolved institutional evidence requirements.",
            details={"items": known_missing},
        )
    elif not bool(policy.get("institution_approved", False)):
        add(
            "institution_evidence",
            "Institutional evidence and sign-off",
            "warning",
            enforcement="governance",
            evidence="No institution-approved sign-off is attached to this policy.",
        )
    else:
        add(
            "institution_evidence",
            "Institutional evidence and sign-off",
            "pass",
            enforcement="governance",
            evidence="The policy marks institutional sign-off as complete; retain the approving artifact in release evidence.",
        )

    counts = Counter(str(check["status"]) for check in checks)
    semantic_blockers = [
        check
        for check in checks
        if check["status"] in {"missing", "unsupported"}
        and check["enforcement"] != "governance"
    ]
    governance_ready = bool(policy.get("institution_approved", False)) and not known_missing
    return {
        "schema_version": 1,
        "policy_id": str(policy.get("policy_id") or "custom"),
        "evidence_status": str(policy.get("evidence_status") or "not supplied"),
        "research_semantics_ready": not semantic_blockers,
        "institutional_use_ready": bool(not semantic_blockers and governance_ready),
        "summary": {
            "checks": len(checks),
            "pass": int(counts["pass"]),
            "warning": int(counts["warning"]),
            "missing": int(counts["missing"]),
            "unsupported": int(counts["unsupported"]),
            "not_enabled": int(counts["not_enabled"]),
        },
        "checks": checks,
    }
