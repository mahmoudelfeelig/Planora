from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Any, Iterable

from utils.domain import DistributionConstraint, Instance
from utils.schedule_rules import room_transition_buffer


PAIRWISE_TYPES = frozenset(
    {
        "same_start",
        "same_time",
        "different_time",
        "same_days",
        "different_days",
        "same_weeks",
        "different_weeks",
        "overlap",
        "not_overlap",
        "same_room",
        "different_room",
        "same_attendees",
        "work_day",
        "min_gap",
    }
)
ORDERED_TYPES = frozenset({"precedence"})
AGGREGATE_TYPES = frozenset({"max_days", "max_day_load", "max_breaks", "max_block"})
SUPPORTED_TYPES = PAIRWISE_TYPES | ORDERED_TYPES | AGGREGATE_TYPES


_ALIASES = {
    "samestart": "same_start",
    "sametime": "same_time",
    "differenttime": "different_time",
    "samedays": "same_days",
    "differentdays": "different_days",
    "sameweeks": "same_weeks",
    "differentweeks": "different_weeks",
    "overlap": "overlap",
    "notoverlap": "not_overlap",
    "sameroom": "same_room",
    "differentroom": "different_room",
    "sameattendees": "same_attendees",
    "precedence": "precedence",
    "workday": "work_day",
    "mingap": "min_gap",
    "maxdays": "max_days",
    "maxdayload": "max_day_load",
    "maxbreaks": "max_breaks",
    "maxblock": "max_block",
}


@dataclass(frozen=True)
class DistributionViolation:
    constraint_id: str
    constraint_type: str
    required: bool
    units: int
    penalty: int
    activity_ids: tuple[int, ...]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_distribution_type(value: str) -> str:
    token = re.sub(r"\([^)]*\)$", "", str(value or "").strip())
    collapsed = re.sub(r"[^a-z0-9]", "", token.lower())
    if collapsed not in _ALIASES:
        raise ValueError(f"Unsupported distribution constraint type: {value}")
    return _ALIASES[collapsed]


def distribution_capability_report(inst: Instance) -> dict[str, Any]:
    counts: dict[str, int] = {}
    unsupported: list[dict[str, str]] = []
    for constraint in getattr(inst, "distribution_constraints", []) or []:
        try:
            kind = normalize_distribution_type(constraint.constraint_type)
        except ValueError as exc:
            unsupported.append({"id": str(constraint.id), "reason": str(exc)})
            continue
        counts[kind] = counts.get(kind, 0) + 1
    return {
        "total": sum(counts.values()) + len(unsupported),
        "supported": sum(counts.values()),
        "types": dict(sorted(counts.items())),
        "unsupported": unsupported,
        "exact_validation_types": sorted(SUPPORTED_TYPES),
        "hard_cp_types": sorted(
            SUPPORTED_TYPES - {"max_breaks", "max_block"}
        ),
        "soft_optimization": "local_search_and_portable_score",
    }


def _parameter(constraint: DistributionConstraint, *names: str, default: int = 0) -> int:
    parameters = constraint.parameters or {}
    for name in names:
        if name in parameters:
            return int(parameters[name])
    match = re.search(r"\(([^)]*)\)", str(constraint.constraint_type))
    if match:
        values = [part.strip() for part in match.group(1).split(",")]
        if values and values[0]:
            return int(values[0])
    return int(default)


def distribution_parameter(
    constraint: DistributionConstraint,
    *names: str,
    default: int = 0,
) -> int:
    return _parameter(constraint, *names, default=default)


def _position(inst: Instance, info: dict[str, Any]) -> tuple[int, int, int, int]:
    week_index = {int(week): index for index, week in enumerate(inst.weeks)}
    day_index = {str(day): index for index, day in enumerate(inst.days)}
    week = int(info["week"])
    day = str(info["day"])
    start = int(info["slot"])
    return week_index.get(week, week), day_index.get(day, -1), start, start + int(info["duration"])


def _overlaps(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    return left[:2] == right[:2] and left[2] < right[3] and right[2] < left[3]


def _gap(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> int:
    if left[:2] != right[:2]:
        return 10**9
    return max(right[2] - left[3], left[2] - right[3])


def pair_satisfies_distribution(
    inst: Instance,
    constraint: DistributionConstraint,
    left_info: dict[str, Any],
    right_info: dict[str, Any],
) -> bool:
    kind = normalize_distribution_type(constraint.constraint_type)
    left = _position(inst, left_info)
    right = _position(inst, right_info)
    if kind == "same_start":
        return left[2] == right[2]
    if kind == "same_time":
        return (left[2] <= right[2] and left[3] >= right[3]) or (
            right[2] <= left[2] and right[3] >= left[3]
        )
    if kind == "different_time":
        return left[3] <= right[2] or right[3] <= left[2]
    if kind == "same_days":
        return left[1] == right[1]
    if kind == "different_days":
        return left[1] != right[1]
    if kind == "same_weeks":
        return left[0] == right[0]
    if kind == "different_weeks":
        return left[0] != right[0]
    if kind == "overlap":
        return _overlaps(left, right)
    if kind == "not_overlap":
        return not _overlaps(left, right)
    if kind == "same_room":
        return left_info.get("room_id") is not None and left_info.get("room_id") == right_info.get("room_id")
    if kind == "different_room":
        return left_info.get("room_id") is not None and right_info.get("room_id") is not None and left_info.get("room_id") != right_info.get("room_id")
    if kind == "same_attendees":
        if _overlaps(left, right):
            return False
        if left[:2] != right[:2]:
            return True
        left_room = inst.rooms.get(int(left_info["room_id"])) if left_info.get("room_id") is not None else None
        right_room = inst.rooms.get(int(right_info["room_id"])) if right_info.get("room_id") is not None else None
        return _gap(left, right) >= room_transition_buffer(inst, left_room, right_room)
    if kind == "work_day":
        if left[:2] != right[:2]:
            return True
        maximum = _parameter(constraint, "slots", "maximum", "S", default=0)
        return max(left[3], right[3]) - min(left[2], right[2]) <= maximum
    if kind == "min_gap":
        minimum = _parameter(constraint, "slots", "minimum", "G", default=0)
        return _gap(left, right) >= minimum
    raise ValueError(f"{kind} is not pairwise")


def _merge_intervals(rows: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted((int(start), int(end)) for start, end in rows):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _aggregate_units(
    inst: Instance,
    constraint: DistributionConstraint,
    rows: list[dict[str, Any]],
) -> int:
    kind = normalize_distribution_type(constraint.constraint_type)
    by_day: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_day.setdefault((int(row["week"]), str(row["day"])), []).append(row)
    if kind == "max_days":
        maximum = _parameter(constraint, "days", "maximum", "D", default=0)
        by_week: dict[int, set[str]] = {}
        for week, day in by_day:
            by_week.setdefault(week, set()).add(day)
        return sum(max(0, len(days) - maximum) for days in by_week.values())
    if kind == "max_day_load":
        maximum = _parameter(constraint, "slots", "maximum", "S", default=0)
        return sum(max(0, sum(int(row["duration"]) for row in day_rows) - maximum) for day_rows in by_day.values())
    if kind == "max_breaks":
        maximum = _parameter(constraint, "breaks", "maximum", "R", default=0)
        minimum_gap = _parameter(constraint, "minimum_gap", "S", default=1)
        units = 0
        for day_rows in by_day.values():
            merged = _merge_intervals((int(row["slot"]), int(row["slot"]) + int(row["duration"])) for row in day_rows)
            breaks = sum(1 for left, right in zip(merged, merged[1:]) if right[0] - left[1] >= minimum_gap)
            units += max(0, breaks - maximum)
        return units
    if kind == "max_block":
        maximum = _parameter(constraint, "slots", "maximum", "M", default=0)
        bridge_gap = _parameter(constraint, "bridge_gap", "S", default=0)
        units = 0
        for day_rows in by_day.values():
            merged = _merge_intervals((int(row["slot"]), int(row["slot"]) + int(row["duration"])) for row in day_rows)
            blocks: list[list[int]] = []
            for start, end in merged:
                if not blocks or start - blocks[-1][1] > bridge_gap:
                    blocks.append([start, end])
                else:
                    blocks[-1][1] = end
            units += sum(max(0, end - start - maximum) for start, end in blocks)
        return units
    raise ValueError(f"{kind} is not aggregate")


def evaluate_distribution_constraints(
    inst: Instance,
    schedule: dict[int, dict[str, Any]],
    *,
    required_only: bool = False,
    constraints: Iterable[DistributionConstraint] | None = None,
) -> list[DistributionViolation]:
    violations: list[DistributionViolation] = []
    source_constraints = (
        getattr(inst, "distribution_constraints", []) or []
        if constraints is None
        else constraints
    )
    for constraint in source_constraints:
        if required_only and not bool(constraint.required):
            continue
        kind = normalize_distribution_type(constraint.constraint_type)
        activity_ids = tuple(int(value) for value in constraint.activity_ids)
        missing = tuple(activity_id for activity_id in activity_ids if activity_id not in schedule)
        if missing:
            units = len(missing)
        else:
            rows = [schedule[activity_id] for activity_id in activity_ids]
            if kind in PAIRWISE_TYPES:
                units = sum(
                    not pair_satisfies_distribution(inst, constraint, schedule[left], schedule[right])
                    for left, right in combinations(activity_ids, 2)
                )
            elif kind in ORDERED_TYPES:
                units = 0
                for left_id, right_id in zip(activity_ids, activity_ids[1:]):
                    left = _position(inst, schedule[left_id])
                    right = _position(inst, schedule[right_id])
                    minimum = _parameter(constraint, "minimum_gap", "G", default=0)
                    if left[:2] > right[:2] or (left[:2] == right[:2] and left[3] + minimum > right[2]):
                        units += 1
            else:
                units = _aggregate_units(inst, constraint, rows)
        if units:
            penalty = 0 if constraint.required else int(units) * max(0, int(constraint.penalty))
            violations.append(
                DistributionViolation(
                    constraint_id=str(constraint.id),
                    constraint_type=kind,
                    required=bool(constraint.required),
                    units=int(units),
                    penalty=int(penalty),
                    activity_ids=activity_ids,
                    message=(
                        f"Distribution constraint {constraint.id} ({kind}) is violated "
                        f"by {int(units)} unit(s)."
                    ),
                )
            )
    return violations


def distribution_penalty(inst: Instance, schedule: dict[int, dict[str, Any]]) -> int:
    return sum(
        int(violation.penalty)
        for violation in evaluate_distribution_constraints(inst, schedule)
        if not violation.required
    )


def distribution_penalty_for_constraints(
    inst: Instance,
    schedule: dict[int, dict[str, Any]],
    constraints: Iterable[DistributionConstraint],
) -> int:
    """Score only the supplied soft constraints using the canonical evaluator."""
    return sum(
        int(violation.penalty)
        for violation in evaluate_distribution_constraints(
            inst,
            schedule,
            constraints=constraints,
        )
        if not violation.required
    )
