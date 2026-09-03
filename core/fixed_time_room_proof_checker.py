from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Hashable, Mapping, Sequence

from utils.demand import required_capacity
from utils.distribution_constraints import normalize_distribution_type
from utils.domain import Instance
from utils.schedule_rules import hard_flag, room_is_available


PeriodKey = tuple[int, str, int]
SupportKey = tuple[Hashable, ...]
ROOM_PROOF_SCHEMA_VERSION = "planora.fixed_time_room_oracle.v1"
MATCHING_METHOD = "dense_rectangular_hungarian"
MATCHING_COMPLEXITY = "O(A^2 * R) for A <= R"


@dataclass(frozen=True)
class FixedTimeRoomProofVerification:
    """Independent integrity/replay result for unsigned room-oracle telemetry.

    A valid result means the serialized mathematical claims replay against the
    supplied instance and incumbent. It is not a signature, timestamp, source
    attestation, or substitute for an official external benchmark validator.
    """

    valid: bool
    errors: tuple[str, ...] = ()
    candidate_schedule: dict[int, dict[str, Any]] | None = None
    capacity_lower_bound: int | None = None
    room_lower_bound: int | None = None


@dataclass(frozen=True)
class _ObjectiveSpec:
    objective_id: str
    capacity_weight: int
    stability_weight: int
    students_by_course: Mapping[int, int]
    support_keys_by_activity: Mapping[int, tuple[SupportKey, ...]]


@dataclass(frozen=True)
class _RoomTerms:
    objective_id: str
    capacity: int
    stability: int

    @property
    def total(self) -> int:
        return int(self.capacity) + int(self.stability)


@dataclass(frozen=True)
class _CertificateReplay:
    valid: bool
    primal_cost: int | None = None


def _is_int(value: object) -> bool:
    return type(value) is int


def _is_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _fixed_time_digest(schedule: Mapping[int, Mapping[str, Any]]) -> str:
    """Independent implementation of the v1 fixed-time transcript digest."""

    digest = hashlib.sha256()
    digest.update(b"PLANORA_FIXED_TIME_V1;")

    def update_token(tag: bytes, value: object) -> None:
        encoded = str(value).encode("utf-8")
        digest.update(tag)
        digest.update(str(len(encoded)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded)
        digest.update(b";")

    for activity_id in sorted(schedule):
        row = schedule[int(activity_id)]
        update_token(b"A", int(activity_id))
        update_token(b"W", int(row["week"]))
        update_token(b"D", str(row["day"]))
        update_token(b"S", int(row["slot"]))
        update_token(b"L", int(row["duration"]))
        digest.update(b"Z;")
    return digest.hexdigest()


def _domain_digest(
    activity_ids: Sequence[int],
    edges: Mapping[int, Mapping[int, int]],
) -> str:
    """Independent implementation of the certificate's v1 edge transcript."""

    digest = hashlib.sha256()

    def update_integer(value: int) -> None:
        token = str(int(value)).encode("ascii")
        digest.update(str(len(token)).encode("ascii"))
        digest.update(b":")
        digest.update(token)
        digest.update(b";")

    for activity_id in activity_ids:
        digest.update(b"A")
        update_integer(int(activity_id))
        for room_id, cost in sorted(edges[int(activity_id)].items()):
            digest.update(b"E")
            update_integer(int(room_id))
            update_integer(int(cost))
        digest.update(b"Z")
    return digest.hexdigest()


def _objective_digest(spec: _ObjectiveSpec) -> str:
    payload = {
        "objective_id": str(spec.objective_id),
        "capacity_weight": int(spec.capacity_weight),
        "stability_weight": int(spec.stability_weight),
        "students_by_course": [
            [int(course_id), int(value)]
            for course_id, value in sorted(spec.students_by_course.items())
        ],
        "support_keys_by_activity": [
            [int(activity_id), [[value for value in key] for key in keys]]
            for activity_id, keys in sorted(spec.support_keys_by_activity.items())
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _room_semantics_digest(
    periods: Sequence[PeriodKey],
    by_period: Mapping[PeriodKey, Sequence[int]],
    domains: Mapping[int, Sequence[int]],
    capacity_costs: Mapping[tuple[int, int], int],
) -> str:
    payload = [
        [
            [int(period[0]), str(period[1]), int(period[2])],
            [
                [
                    int(activity_id),
                    [
                        [
                            int(room_id),
                            int(capacity_costs[(int(activity_id), int(room_id))]),
                        ]
                        for room_id in domains[int(activity_id)]
                    ],
                ]
                for activity_id in by_period[period]
            ],
        ]
        for period in periods
    ]
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _objective_spec(inst: Instance) -> tuple[_ObjectiveSpec | None, list[str]]:
    errors: list[str] = []
    sla = getattr(inst, "sla_targets", {}) or {}
    family = str(sla.get("benchmark_family", ""))
    activities = {int(key): value for key, value in inst.activities.items()}
    if family.startswith("ITC-2007"):
        metadata = sla.get("itc2007")
        if not isinstance(metadata, dict):
            return None, ["objective:itc2007_metadata_missing"]
        weights = metadata.get("objective_weights")
        students = metadata.get("course_students")
        if not isinstance(weights, dict):
            errors.append("objective:itc2007_weights_missing")
            weights = {}
        if not isinstance(students, dict):
            errors.append("objective:itc2007_course_students_missing")
            students = {}
        try:
            capacity_weight = int(weights.get("room_capacity", 1))
            stability_weight = int(weights.get("room_stability", 1))
        except (TypeError, ValueError):
            return None, [*errors, "objective:itc2007_weight_invalid"]
        if capacity_weight < 0 or stability_weight < 0:
            errors.append("objective:negative_weight")
        students_by_course: dict[int, int] = {}
        for course_id, course in inst.courses.items():
            try:
                students_by_course[int(course_id)] = int(students[str(course.code)])
            except (KeyError, TypeError, ValueError):
                errors.append(f"objective:student_count_invalid:{course_id}")
        support = {
            activity_id: (("course", int(activity.course_id)),)
            for activity_id, activity in activities.items()
        }
        return (
            _ObjectiveSpec(
                "itc2007_official",
                int(capacity_weight),
                int(stability_weight),
                students_by_course,
                support,
            ),
            errors,
        )

    raw_weight = (getattr(inst, "soft_weights", {}) or {}).get(
        "room_consistency", 1
    )
    try:
        stability_weight = int(raw_weight)
    except (TypeError, ValueError):
        return None, ["objective:generic_room_consistency_weight_invalid"]
    if stability_weight < 0:
        errors.append("objective:negative_weight")
    support = {
        activity_id: tuple(
            (
                "course_group_kind",
                int(activity.course_id),
                int(group_id),
                str(activity.kind),
            )
            for group_id in sorted({int(value) for value in activity.group_ids})
        )
        for activity_id, activity in activities.items()
    }
    return (
        _ObjectiveSpec(
            "planora_generic",
            0,
            int(stability_weight),
            {},
            support,
        ),
        errors,
    )


def _has_effective_clusters(inst: Instance) -> bool:
    by_key: Counter[tuple[str, int, str]] = Counter()
    for activity in inst.activities.values():
        if activity.cluster_key:
            by_key[
                (str(activity.cluster_key), int(activity.week), str(activity.kind))
            ] += 1
    if any(count >= 2 for count in by_key.values()):
        return True
    for course_id, course in inst.courses.items():
        shared_groups = {
            int(value) for value in (course.share_lecture_group_ids or [])
        }
        if not shared_groups:
            continue
        by_week: Counter[int] = Counter()
        for activity in inst.activities.values():
            if (
                int(activity.course_id) == int(course_id)
                and str(activity.kind) == "LEC"
                and len(activity.group_ids) == 1
                and int(activity.group_ids[0]) in shared_groups
            ):
                by_week[int(activity.week)] += 1
        if any(count >= 2 for count in by_week.values()):
            return True
    return False


def _normalize_incumbent(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    errors: list[str],
) -> dict[int, dict[str, Any]]:
    normalized: dict[int, dict[str, Any]] = {}
    for raw_activity_id, raw_row in schedule.items():
        try:
            activity_id = int(raw_activity_id)
        except (TypeError, ValueError):
            errors.append("incumbent:activity_id_invalid")
            continue
        if activity_id in normalized:
            errors.append(f"incumbent:duplicate_activity:{activity_id}")
            continue
        if not isinstance(raw_row, Mapping):
            errors.append(f"incumbent:row_invalid:{activity_id}")
            continue
        normalized[activity_id] = dict(raw_row)
    expected = {int(value) for value in inst.activities}
    if set(normalized) != expected:
        errors.append("incumbent:activity_set_mismatch")
    for activity_id in sorted(expected & set(normalized)):
        row = normalized[activity_id]
        activity = inst.activities[activity_id]
        try:
            week = int(row["week"])
            day = str(row["day"])
            slot = int(row["slot"])
            duration = int(row["duration"])
            room_id = int(row["room_id"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"incumbent:row_incomplete:{activity_id}")
            continue
        if week != int(activity.week):
            errors.append(f"incumbent:week_mismatch:{activity_id}")
        if day not in {str(value) for value in inst.days}:
            errors.append(f"incumbent:day_invalid:{activity_id}")
        if slot < 0 or slot >= int(inst.slots_per_day):
            errors.append(f"incumbent:slot_invalid:{activity_id}")
        if duration != int(activity.duration):
            errors.append(f"incumbent:duration_mismatch:{activity_id}")
        if room_id not in inst.rooms:
            errors.append(f"incumbent:room_invalid:{activity_id}")
    return normalized


def _eligibility_errors(
    inst: Instance,
    incumbent: Mapping[int, Mapping[str, Any]],
    spec: _ObjectiveSpec,
) -> list[str]:
    errors: list[str] = []
    if not inst.rooms:
        errors.append("eligibility:no_rooms")
    if spec.objective_id == "planora_generic" and (
        str(getattr(inst, "objective_profile", "") or "").strip().lower()
        == "fairness_first"
    ):
        errors.append("eligibility:fairness_first_not_modeled")
    if _has_effective_clusters(inst):
        errors.append("eligibility:co_location_cluster")
    if hard_flag(inst, "force_repeat_weekly_pattern", False):
        errors.append("eligibility:repeat_week_room_coupling")
    if hard_flag(inst, "enforce_travel_time_buffers", True):
        try:
            if any(
                int(value or 0) > 0
                for value in (getattr(inst, "travel_time_rules", {}) or {}).values()
            ):
                errors.append("eligibility:travel_room_coupling")
        except (TypeError, ValueError):
            errors.append("eligibility:travel_rule_invalid")
    for constraint in getattr(inst, "distribution_constraints", []) or []:
        try:
            kind = normalize_distribution_type(constraint.constraint_type)
        except ValueError:
            errors.append(f"eligibility:unknown_distribution:{constraint.id}")
            continue
        if kind in {"same_room", "different_room"}:
            errors.append(f"eligibility:room_distribution:{constraint.id}")
    support_period_counts: Counter[tuple[SupportKey, PeriodKey]] = Counter()
    for activity_id, activity in inst.activities.items():
        if int(activity.duration) != 1:
            errors.append(f"eligibility:non_unit_duration:{activity_id}")
        row = incumbent.get(int(activity_id))
        if row is None:
            continue
        try:
            period = (int(row["week"]), str(row["day"]), int(row["slot"]))
            if int(row["duration"]) != 1:
                errors.append(f"eligibility:schedule_non_unit:{activity_id}")
        except (KeyError, TypeError, ValueError):
            continue
        for key in spec.support_keys_by_activity.get(int(activity_id), ()):
            support_period_counts[(key, period)] += 1
    for (key, period), count in support_period_counts.items():
        if int(count) > 1:
            errors.append(
                f"eligibility:repeated_support:{period!r}:{key!r}"
            )
    return errors


def _candidate_rooms(
    inst: Instance,
    activity_id: int,
    period: PeriodKey,
) -> tuple[int, ...]:
    activity = inst.activities[int(activity_id)]
    needed = int(required_capacity(inst, activity.group_ids))
    enforce_capacity = hard_flag(inst, "enforce_room_capacity", True)
    locked = (getattr(inst, "locked_activities", {}) or {}).get(int(activity_id), {})
    locked_room = None
    if isinstance(locked, dict) and locked.get("room_id") is not None:
        locked_room = int(locked["room_id"])
    candidates: list[int] = []
    for raw_room_id, room in sorted(inst.rooms.items()):
        room_id = int(raw_room_id)
        if locked_room is not None and room_id != locked_room:
            continue
        if str(activity.kind) == "LAB":
            if room.room_type not in {"SPECIALIZED_LAB", "COMPUTER_LAB"}:
                continue
            specialization = getattr(activity, "requires_specialization", None)
            if specialization and (
                room.room_type != "SPECIALIZED_LAB"
                or specialization
                not in (getattr(room, "specialization_tags", set()) or set())
            ):
                continue
        elif str(activity.kind) == "TUT":
            if room.room_type not in {"TUTORIAL", "LECTURE"}:
                continue
        elif room.room_type != "LECTURE":
            continue
        if enforce_capacity and int(room.capacity) < needed:
            continue
        if not room_is_available(
            inst,
            room_id,
            week=int(period[0]),
            day=str(period[1]),
            start_slot=int(period[2]),
            dur=1,
        ):
            continue
        candidates.append(room_id)
    return tuple(candidates)


def _build_room_semantics(
    inst: Instance,
    incumbent: Mapping[int, Mapping[str, Any]],
    spec: _ObjectiveSpec,
) -> tuple[
    tuple[PeriodKey, ...],
    dict[PeriodKey, tuple[int, ...]],
    dict[int, tuple[int, ...]],
    dict[tuple[int, int], int],
    list[str],
]:
    by_period_lists: dict[PeriodKey, list[int]] = defaultdict(list)
    domains: dict[int, tuple[int, ...]] = {}
    capacity_costs: dict[tuple[int, int], int] = {}
    errors: list[str] = []
    for activity_id, activity in sorted(inst.activities.items()):
        row = incumbent[int(activity_id)]
        period = (int(row["week"]), str(row["day"]), int(row["slot"]))
        by_period_lists[period].append(int(activity_id))
        room_ids = _candidate_rooms(inst, int(activity_id), period)
        domains[int(activity_id)] = room_ids
        if not room_ids:
            errors.append(f"domain:empty:{activity_id}")
        if int(row["room_id"]) not in room_ids:
            errors.append(f"domain:incumbent_room_outside:{activity_id}")
        for room_id in room_ids:
            capacity_cost = 0
            if spec.objective_id == "itc2007_official":
                capacity_cost = int(spec.capacity_weight) * max(
                    0,
                    int(spec.students_by_course[int(activity.course_id)])
                    - int(inst.rooms[int(room_id)].capacity),
                )
            capacity_costs[(int(activity_id), int(room_id))] = int(capacity_cost)
    periods = tuple(sorted(by_period_lists))
    by_period = {
        period: tuple(sorted(activity_ids))
        for period, activity_ids in by_period_lists.items()
    }
    return periods, by_period, domains, capacity_costs, errors


def _score_terms(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    spec: _ObjectiveSpec,
) -> _RoomTerms:
    capacity = 0
    if spec.objective_id == "itc2007_official":
        for activity_id, row in schedule.items():
            course_id = int(inst.activities[int(activity_id)].course_id)
            room_id = int(row["room_id"])
            capacity += int(spec.capacity_weight) * max(
                0,
                int(spec.students_by_course[course_id])
                - int(inst.rooms[room_id].capacity),
            )
    key_rooms: dict[SupportKey, set[int]] = defaultdict(set)
    for activity_id, row in schedule.items():
        room_id = int(row["room_id"])
        for key in spec.support_keys_by_activity[int(activity_id)]:
            key_rooms[key].add(room_id)
    stability = int(spec.stability_weight) * sum(
        max(0, len(room_ids) - 1) for room_ids in key_rooms.values()
    )
    return _RoomTerms(str(spec.objective_id), int(capacity), int(stability))


def _canonical_terms(
    inst: Instance,
    schedule: dict[int, dict[str, Any]],
    objective_id: str,
) -> _RoomTerms:
    if objective_id == "itc2007_official":
        from benchmarks.itc2007 import score_itc2007_instance_schedule

        score = score_itc2007_instance_schedule(inst, schedule)
        return _RoomTerms(
            objective_id,
            int(score.room_capacity),
            int(score.room_stability),
        )
    from services.quality_service import compute_penalty_breakdown

    breakdown = compute_penalty_breakdown(inst, schedule)
    return _RoomTerms(
        objective_id,
        0,
        int(breakdown.get("room_consistency", 0)),
    )


def _parse_period(value: object) -> PeriodKey | None:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or not _is_int(value[0])
        or not isinstance(value[1], str)
        or not _is_int(value[2])
    ):
        return None
    return int(value[0]), str(value[1]), int(value[2])


def _parse_integer_pairs(
    value: object,
    *,
    label: str,
    errors: list[str],
) -> list[tuple[int, int]] | None:
    if not isinstance(value, list):
        errors.append(f"{label}:not_list")
        return None
    parsed: list[tuple[int, int]] = []
    for index, row in enumerate(value):
        if (
            not isinstance(row, list)
            or len(row) != 2
            or not _is_int(row[0])
            or not _is_int(row[1])
        ):
            errors.append(f"{label}:row_invalid:{index}")
            return None
        parsed.append((int(row[0]), int(row[1])))
    return parsed


def _replay_certificate(
    certificate: object,
    expected_period: PeriodKey,
    expected_activity_ids: Sequence[int],
    expected_edges: Mapping[int, Mapping[int, int]],
    *,
    label: str,
    errors: list[str],
) -> _CertificateReplay:
    if not isinstance(certificate, Mapping):
        errors.append(f"{label}:not_object")
        return _CertificateReplay(False)
    required = {
        "period",
        "activity_ids",
        "room_ids",
        "assignments",
        "row_potentials",
        "room_potentials",
        "primal_cost",
        "dual_cost",
        "domain_digest",
        "candidate_edges",
        "method",
        "complexity",
        "checked",
    }
    if set(certificate) != required:
        errors.append(f"{label}:schema_mismatch")
    period = _parse_period(certificate.get("period"))
    if period != expected_period:
        errors.append(f"{label}:period_mismatch")
    raw_activity_ids = certificate.get("activity_ids")
    if not isinstance(raw_activity_ids, list) or any(
        not _is_int(value) for value in raw_activity_ids
    ):
        errors.append(f"{label}:activity_ids_invalid")
        activity_ids: tuple[int, ...] = ()
    else:
        activity_ids = tuple(int(value) for value in raw_activity_ids)
    if activity_ids != tuple(expected_activity_ids):
        errors.append(f"{label}:activity_set_mismatch")
    if len(set(activity_ids)) != len(activity_ids):
        errors.append(f"{label}:duplicate_activity_id")
    expected_rooms = tuple(
        sorted(
            {
                int(room_id)
                for activity_id in expected_activity_ids
                for room_id in expected_edges[int(activity_id)]
            }
        )
    )
    raw_room_ids = certificate.get("room_ids")
    if not isinstance(raw_room_ids, list) or any(
        not _is_int(value) for value in raw_room_ids
    ):
        errors.append(f"{label}:room_ids_invalid")
        room_ids: tuple[int, ...] = ()
    else:
        room_ids = tuple(int(value) for value in raw_room_ids)
    if room_ids != expected_rooms:
        errors.append(f"{label}:room_set_mismatch")
    if len(set(room_ids)) != len(room_ids):
        errors.append(f"{label}:duplicate_room_id")
    if certificate.get("method") != MATCHING_METHOD:
        errors.append(f"{label}:method_mismatch")
    if certificate.get("complexity") != MATCHING_COMPLEXITY:
        errors.append(f"{label}:complexity_mismatch")
    if certificate.get("checked") is not True:
        errors.append(f"{label}:builder_checked_flag_not_true")

    expected_context = [
        [
            int(activity_id),
            [
                [int(room_id), int(cost)]
                for room_id, cost in sorted(expected_edges[int(activity_id)].items())
            ],
        ]
        for activity_id in expected_activity_ids
    ]
    raw_context = certificate.get("candidate_edges")
    if raw_context != expected_context:
        errors.append(f"{label}:candidate_edge_context_mismatch")
    if isinstance(raw_context, list):
        context_activities: list[int] = []
        for row_index, row in enumerate(raw_context):
            if (
                not isinstance(row, list)
                or len(row) != 2
                or not _is_int(row[0])
                or not isinstance(row[1], list)
            ):
                errors.append(f"{label}:candidate_edge_row_invalid:{row_index}")
                continue
            activity_id = int(row[0])
            context_activities.append(activity_id)
            context_rooms: list[int] = []
            for edge_index, edge in enumerate(row[1]):
                if (
                    not isinstance(edge, list)
                    or len(edge) != 2
                    or not _is_int(edge[0])
                    or not _is_int(edge[1])
                ):
                    errors.append(
                        f"{label}:candidate_edge_invalid:{row_index}:{edge_index}"
                    )
                    continue
                context_rooms.append(int(edge[0]))
            if len(set(context_rooms)) != len(context_rooms):
                errors.append(f"{label}:duplicate_candidate_room:{activity_id}")
        if len(set(context_activities)) != len(context_activities):
            errors.append(f"{label}:duplicate_candidate_activity")

    expected_digest = _domain_digest(expected_activity_ids, expected_edges)
    if certificate.get("domain_digest") != expected_digest:
        errors.append(f"{label}:domain_digest_mismatch")
    assignments = _parse_integer_pairs(
        certificate.get("assignments"),
        label=f"{label}:assignments",
        errors=errors,
    )
    row_potentials = _parse_integer_pairs(
        certificate.get("row_potentials"),
        label=f"{label}:row_potentials",
        errors=errors,
    )
    room_potentials = _parse_integer_pairs(
        certificate.get("room_potentials"),
        label=f"{label}:room_potentials",
        errors=errors,
    )
    if assignments is None or row_potentials is None or room_potentials is None:
        return _CertificateReplay(False)
    assignment_activity_ids = [activity_id for activity_id, _ in assignments]
    assigned_rooms = [room_id for _, room_id in assignments]
    if len(set(assignment_activity_ids)) != len(assignment_activity_ids):
        errors.append(f"{label}:duplicate_assignment_activity")
    if set(assignment_activity_ids) != set(expected_activity_ids):
        errors.append(f"{label}:assignment_not_left_perfect")
    if tuple(assignment_activity_ids) != tuple(expected_activity_ids):
        errors.append(f"{label}:assignment_order_noncanonical")
    if len(set(assigned_rooms)) != len(assigned_rooms):
        errors.append(f"{label}:assignment_reuses_room")
    assignment_map = dict(assignments)
    primal = 0
    for activity_id in expected_activity_ids:
        room_id = assignment_map.get(int(activity_id))
        if room_id is None or room_id not in expected_edges[int(activity_id)]:
            errors.append(f"{label}:forbidden_assignment:{activity_id}:{room_id}")
            continue
        primal += int(expected_edges[int(activity_id)][int(room_id)])

    row_keys = [key for key, _ in row_potentials]
    room_keys = [key for key, _ in room_potentials]
    if len(set(row_keys)) != len(row_keys):
        errors.append(f"{label}:duplicate_row_potential")
    if len(set(room_keys)) != len(room_keys):
        errors.append(f"{label}:duplicate_room_potential")
    if set(row_keys) != set(expected_activity_ids):
        errors.append(f"{label}:row_potential_set_mismatch")
    if tuple(row_keys) != tuple(expected_activity_ids):
        errors.append(f"{label}:row_potential_order_noncanonical")
    if set(room_keys) != set(expected_rooms):
        errors.append(f"{label}:room_potential_set_mismatch")
    if tuple(room_keys) != tuple(expected_rooms):
        errors.append(f"{label}:room_potential_order_noncanonical")
    row_duals = dict(row_potentials)
    room_duals = dict(room_potentials)
    for room_id, value in room_potentials:
        if int(value) > 0:
            errors.append(f"{label}:positive_room_potential:{room_id}")
    for activity_id in expected_activity_ids:
        if int(activity_id) not in row_duals:
            continue
        for room_id, cost in expected_edges[int(activity_id)].items():
            if int(room_id) not in room_duals:
                continue
            if int(row_duals[int(activity_id)]) + int(room_duals[int(room_id)]) > int(
                cost
            ):
                errors.append(f"{label}:dual_infeasible:{activity_id}:{room_id}")
    for activity_id, room_id in assignments:
        if (
            activity_id in row_duals
            and room_id in room_duals
            and room_id in expected_edges.get(activity_id, {})
            and int(row_duals[activity_id]) + int(room_duals[room_id])
            != int(expected_edges[activity_id][room_id])
        ):
            errors.append(f"{label}:matched_edge_not_tight:{activity_id}:{room_id}")
    dual = sum(value for _, value in row_potentials) + sum(
        value for _, value in room_potentials
    )
    if not _is_int(certificate.get("primal_cost")):
        errors.append(f"{label}:primal_cost_invalid")
    elif int(certificate["primal_cost"]) != int(primal):
        errors.append(f"{label}:primal_cost_mismatch")
    if not _is_int(certificate.get("dual_cost")):
        errors.append(f"{label}:dual_cost_invalid")
    elif int(certificate["dual_cost"]) != int(dual):
        errors.append(f"{label}:dual_cost_mismatch")
    if int(primal) != int(dual):
        errors.append(f"{label}:primal_dual_gap")
    return _CertificateReplay(True, int(primal))


def _replay_hall_witness(
    witness: object,
    by_period: Mapping[PeriodKey, Sequence[int]],
    capacity_edges: Mapping[PeriodKey, Mapping[int, Mapping[int, int]]],
    *,
    label: str,
    errors: list[str],
) -> PeriodKey | None:
    if not isinstance(witness, Mapping):
        errors.append(f"{label}:not_object")
        return None
    required = {
        "period",
        "activity_ids",
        "candidate_room_ids",
        "deficiency",
        "domain_digest",
        "proof_rule",
    }
    if set(witness) != required:
        errors.append(f"{label}:schema_mismatch")
    period = _parse_period(witness.get("period"))
    if period is None or period not in by_period:
        errors.append(f"{label}:period_invalid")
        return period
    raw_activities = witness.get("activity_ids")
    raw_rooms = witness.get("candidate_room_ids")
    if not isinstance(raw_activities, list) or any(
        not _is_int(value) for value in raw_activities
    ):
        errors.append(f"{label}:activity_ids_invalid")
        return period
    if not isinstance(raw_rooms, list) or any(not _is_int(value) for value in raw_rooms):
        errors.append(f"{label}:room_ids_invalid")
        return period
    activities = tuple(int(value) for value in raw_activities)
    rooms = tuple(int(value) for value in raw_rooms)
    if not activities or len(set(activities)) != len(activities):
        errors.append(f"{label}:activity_subset_invalid")
    if not set(activities).issubset(set(by_period[period])):
        errors.append(f"{label}:activity_outside_period")
    if len(set(rooms)) != len(rooms):
        errors.append(f"{label}:duplicate_room")
    edges = capacity_edges[period]
    neighborhood = tuple(
        sorted(
            {
                int(room_id)
                for activity_id in activities
                for room_id in edges.get(int(activity_id), {})
            }
        )
    )
    if rooms != neighborhood:
        errors.append(f"{label}:hall_neighborhood_mismatch")
    deficiency = len(activities) - len(neighborhood)
    if not _is_int(witness.get("deficiency")):
        errors.append(f"{label}:deficiency_invalid")
    elif int(witness["deficiency"]) != int(deficiency) or deficiency <= 0:
        errors.append(f"{label}:deficiency_mismatch")
    if witness.get("proof_rule") != "hall_neighborhood_deficiency":
        errors.append(f"{label}:proof_rule_mismatch")
    expected_digest = _domain_digest(by_period[period], edges)
    if witness.get("domain_digest") != expected_digest:
        errors.append(f"{label}:domain_digest_mismatch")
    return period


def _parse_terms(
    value: object,
    spec: _ObjectiveSpec,
    *,
    label: str,
    errors: list[str],
) -> _RoomTerms | None:
    stability_name = (
        "room_stability"
        if spec.objective_id == "itc2007_official"
        else "room_consistency"
    )
    expected_keys = {"objective_id", "room_capacity", stability_name, "room_total"}
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        errors.append(f"{label}:schema_mismatch")
        return None
    if value.get("objective_id") != spec.objective_id:
        errors.append(f"{label}:objective_id_mismatch")
    for key in ("room_capacity", stability_name, "room_total"):
        if not _is_int(value.get(key)):
            errors.append(f"{label}:{key}_invalid")
            return None
    terms = _RoomTerms(
        spec.objective_id,
        int(value["room_capacity"]),
        int(value[stability_name]),
    )
    if int(value["room_total"]) != terms.total:
        errors.append(f"{label}:total_arithmetic_mismatch")
    return terms


def _validate_certificate_container(
    payload: Mapping[str, Any],
    name: str,
    errors: list[str],
) -> list[Any]:
    raw = payload.get(f"{name}_certificates")
    if not isinstance(raw, list):
        errors.append(f"{name}:certificates_not_list")
        raw = []
    count = payload.get(f"{name}_certificate_count")
    if not _is_int(count) or int(count) != len(raw):
        errors.append(f"{name}:certificate_count_mismatch")
    expected_status = "not_applicable" if not raw else "internally_replayed"
    if payload.get(f"{name}_certificate_status") != expected_status:
        errors.append(f"{name}:certificate_status_mismatch")
    expected_checked: bool | None = None if not raw else True
    if payload.get(f"{name}_certificates_checked") is not expected_checked:
        errors.append(f"{name}:certificates_checked_semantics_mismatch")
    return list(raw)


def _validate_timing(
    timing: object,
    *,
    claim_bearing: bool,
    status: str,
    errors: list[str],
) -> None:
    if not isinstance(timing, Mapping):
        errors.append("timing:not_object")
        return
    common = {
        "elapsed_seconds",
        "deadline_overrun_seconds",
        "deadline_supplied",
        "deadline_budget_seconds",
        "deadline_remaining_seconds",
    }
    if not common.issubset(timing):
        errors.append("timing:required_field_missing")
        return
    elapsed = timing.get("elapsed_seconds")
    overrun = timing.get("deadline_overrun_seconds")
    if (
        not _is_number(elapsed)
        or not math.isfinite(float(elapsed))
        or float(elapsed) < 0
    ):
        errors.append("timing:elapsed_invalid")
        return
    if (
        not _is_number(overrun)
        or not math.isfinite(float(overrun))
        or float(overrun) < 0
    ):
        errors.append("timing:overrun_invalid")
        return
    supplied = timing.get("deadline_supplied")
    if type(supplied) is not bool:
        errors.append("timing:deadline_supplied_invalid")
        return
    budget = timing.get("deadline_budget_seconds")
    remaining = timing.get("deadline_remaining_seconds")
    if supplied:
        if not _is_number(budget) or not math.isfinite(float(budget)):
            errors.append("timing:deadline_budget_invalid")
        if (
            not _is_number(remaining)
            or not math.isfinite(float(remaining))
            or float(remaining) < 0
        ):
            errors.append("timing:deadline_remaining_invalid")
        if _is_number(budget) and _is_number(remaining):
            replayed_budget = float(elapsed) + float(remaining) - float(overrun)
            tolerance = max(1e-6, abs(float(budget)) * 1e-9)
            if abs(float(budget) - replayed_budget) > tolerance:
                errors.append("timing:deadline_arithmetic_mismatch")
            if float(remaining) > 0 and float(overrun) > 0:
                errors.append("timing:remaining_and_overrun")
    elif budget is not None or remaining is not None or float(overrun) != 0.0:
        errors.append("timing:no_deadline_semantics_mismatch")
    phase_names = (
        "eligibility_seconds",
        "matching_seconds",
        "coordinate_seconds",
        "validation_seconds",
    )
    if claim_bearing and not set(phase_names).issubset(timing):
        errors.append("timing:phase_field_missing")
    if set(phase_names).issubset(timing):
        phases: list[float] = []
        for name in phase_names:
            value = timing.get(name)
            if (
                not _is_number(value)
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                errors.append(f"timing:{name}_invalid")
            else:
                phases.append(float(value))
        if len(phases) == len(phase_names) and sum(phases) > float(elapsed) + 1e-5:
            errors.append("timing:phase_sum_exceeds_elapsed")
    if claim_bearing and float(overrun) > 0:
        errors.append("timing:late_claim_bearing_result")
    if status == "deadline_exhausted" and float(overrun) <= 0 and supplied:
        # A deadline may be observed exactly at the boundary; zero remains
        # possible only within timer resolution, so do not reject it.
        pass


def verify_fixed_time_room_oracle_result(
    inst: Instance,
    incumbent_schedule: Mapping[int, Mapping[str, Any]],
    serialized_result: Mapping[str, Any],
) -> FixedTimeRoomProofVerification:
    """Replay serialized fixed-time room-oracle claims without using the oracle.

    The checker intentionally does not import or call the oracle builder, its
    Hungarian implementation, its digest helper, or its certificate verifier.
    It reconstructs the candidate by applying the compact serialized room
    assignment to the caller-supplied incumbent's immutable time coordinates.
    """

    errors: list[str] = []
    candidate: dict[int, dict[str, Any]] | None = None
    replayed_capacity_lower_bound: int | None = None
    replayed_room_lower_bound: int | None = None
    try:
        if not isinstance(serialized_result, Mapping):
            return FixedTimeRoomProofVerification(False, ("result:not_object",))
        required_fields = {
            "proof_schema_version",
            "proof_integrity",
            "status",
            "eligibility",
            "improved",
            "incumbent_terms",
            "candidate_terms",
            "capacity_lower_bound",
            "stability_lower_bound",
            "room_lower_bound",
            "global_optimal",
            "one_period_local_optimal",
            "proof_status",
            "proof_scope",
            "selected_start",
            "candidate_room_assignment",
            "incumbent_fixed_time_digest",
            "candidate_fixed_time_digest",
            "objective_digest",
            "room_semantics_digest",
            "capacity_certificate_count",
            "capacity_certificate_status",
            "capacity_certificates_checked",
            "capacity_certificates",
            "local_certificate_count",
            "local_certificate_status",
            "local_certificates_checked",
            "local_certificates",
            "hall_witnesses",
            "objective_parity_checked",
            "objective_parity",
            "validation_attempted",
            "validation_errors",
            "fixed_starts_preserved",
            "sweeps",
            "accepted_blocks",
            "timing",
            "error",
        }
        missing = sorted(required_fields - set(serialized_result))
        if missing:
            errors.extend(f"result:missing_field:{name}" for name in missing)
        if serialized_result.get("proof_schema_version") != ROOM_PROOF_SCHEMA_VERSION:
            errors.append("result:proof_schema_version_mismatch")
        if (
            serialized_result.get("proof_integrity")
            != "unsigned_replayable_certificate"
        ):
            errors.append("result:proof_integrity_mismatch")
        status = serialized_result.get("status")
        allowed_statuses = {
            "improved",
            "no_improvement",
            "ineligible",
            "invalid_incumbent",
            "infeasible",
            "deadline_exhausted",
            "certificate_failure",
            "objective_mismatch",
            "validation_failed",
        }
        if not isinstance(status, str) or status not in allowed_statuses:
            errors.append("result:status_invalid")
            status = "invalid"
        claim_bearing = status in {"improved", "no_improvement"}
        for field in (
            "improved",
            "global_optimal",
            "one_period_local_optimal",
            "objective_parity_checked",
            "validation_attempted",
        ):
            if type(serialized_result.get(field)) is not bool:
                errors.append(f"result:{field}_invalid")
        _validate_timing(
            serialized_result.get("timing"),
            claim_bearing=claim_bearing,
            status=str(status),
            errors=errors,
        )
        capacity_certificates = _validate_certificate_container(
            serialized_result, "capacity", errors
        )
        local_certificates = _validate_certificate_container(
            serialized_result, "local", errors
        )
        hall_witnesses = serialized_result.get("hall_witnesses")
        if not isinstance(hall_witnesses, list):
            errors.append("hall:witnesses_not_list")
            hall_witnesses = []

        incumbent = _normalize_incumbent(inst, incumbent_schedule, errors)
        spec, objective_errors = _objective_spec(inst)
        errors.extend(objective_errors)
        if spec is None or set(incumbent) != {int(value) for value in inst.activities}:
            return FixedTimeRoomProofVerification(False, tuple(dict.fromkeys(errors)))
        eligibility_errors = _eligibility_errors(inst, incumbent, spec)
        periods, by_period, domains, capacity_costs, domain_errors = (
            _build_room_semantics(inst, incumbent, spec)
        )
        capacity_edges = {
            period: {
                int(activity_id): {
                    int(room_id): int(capacity_costs[(int(activity_id), int(room_id))])
                    for room_id in domains[int(activity_id)]
                }
                for activity_id in by_period[period]
            }
            for period in periods
        }

        eligibility = serialized_result.get("eligibility")
        expected_eligibility_fields = {
            "eligible",
            "objective_id",
            "structural_class",
            "reasons",
            "activity_count",
            "period_count",
            "room_count",
            "capacity_weight",
            "stability_weight",
        }
        if not isinstance(eligibility, Mapping):
            errors.append("eligibility:not_object")
            eligibility = {}
        elif set(eligibility) != expected_eligibility_fields:
            errors.append("eligibility:schema_mismatch")
        if claim_bearing:
            if eligibility_errors or domain_errors:
                errors.append("eligibility:reconstructed_ineligible")
            if eligibility.get("eligible") is not True:
                errors.append("eligibility:claim_not_eligible")
            if eligibility.get("reasons") != []:
                errors.append("eligibility:claim_reasons_not_empty")
            expected_values = {
                "objective_id": spec.objective_id,
                "structural_class": "unit_duration_fixed_time_injective_room_assignment",
                "activity_count": len(inst.activities),
                "period_count": len(periods),
                "room_count": len(inst.rooms),
                "capacity_weight": spec.capacity_weight,
                "stability_weight": spec.stability_weight,
            }
            for key, expected in expected_values.items():
                if key in {
                    "activity_count",
                    "period_count",
                    "room_count",
                    "capacity_weight",
                    "stability_weight",
                } and not _is_int(eligibility.get(key)):
                    errors.append(f"eligibility:{key}_type_invalid")
                if eligibility.get(key) != expected:
                    errors.append(f"eligibility:{key}_mismatch")
            if type(eligibility.get("eligible")) is not bool:
                errors.append("eligibility:eligible_type_invalid")

        from utils.specs import validate_schedule_against_instance

        incumbent_validation = validate_schedule_against_instance(
            inst,
            incumbent,
            strict_rooms=True,
            require_all_activities=True,
        )
        if incumbent_validation:
            errors.append("incumbent:canonical_validation_failed")

        expected_fixed_digest = _fixed_time_digest(incumbent)
        if claim_bearing:
            if (
                serialized_result.get("incumbent_fixed_time_digest")
                != expected_fixed_digest
            ):
                errors.append("digest:incumbent_fixed_time_mismatch")
            if serialized_result.get("objective_digest") != _objective_digest(spec):
                errors.append("digest:objective_mismatch")
            if serialized_result.get("room_semantics_digest") != _room_semantics_digest(
                periods,
                by_period,
                domains,
                capacity_costs,
            ):
                errors.append("digest:room_semantics_mismatch")

        assignment_rows = serialized_result.get("candidate_room_assignment")
        if claim_bearing:
            parsed_assignment = _parse_integer_pairs(
                assignment_rows,
                label="candidate_assignment",
                errors=errors,
            )
            if parsed_assignment is None:
                parsed_assignment = []
            activity_ids = [activity_id for activity_id, _ in parsed_assignment]
            if len(set(activity_ids)) != len(activity_ids):
                errors.append("candidate_assignment:duplicate_activity")
            if activity_ids != sorted(inst.activities):
                errors.append("candidate_assignment:activity_set_or_order_mismatch")
            candidate = {activity_id: dict(row) for activity_id, row in incumbent.items()}
            for activity_id, room_id in parsed_assignment:
                if activity_id not in candidate:
                    errors.append(f"candidate_assignment:unknown_activity:{activity_id}")
                    continue
                if room_id not in inst.rooms:
                    errors.append(f"candidate_assignment:unknown_room:{activity_id}:{room_id}")
                    continue
                if room_id not in domains.get(int(activity_id), ()):
                    errors.append(
                        f"candidate_assignment:room_outside_domain:{activity_id}:{room_id}"
                    )
                    continue
                candidate[activity_id]["room_id"] = int(room_id)
            if _fixed_time_digest(candidate) != expected_fixed_digest:
                errors.append("candidate:fixed_starts_changed")
            if (
                serialized_result.get("candidate_fixed_time_digest")
                != expected_fixed_digest
            ):
                errors.append("digest:candidate_fixed_time_mismatch")
            candidate_validation = validate_schedule_against_instance(
                inst,
                candidate,
                strict_rooms=True,
                require_all_activities=True,
            )
            if candidate_validation:
                errors.append("candidate:canonical_validation_failed")
        elif assignment_rows is not None:
            errors.append("candidate_assignment:present_for_nonclaim_result")

        capacity_by_period: dict[PeriodKey, Any] = {}
        capacity_sum = 0
        for index, certificate in enumerate(capacity_certificates):
            period = (
                _parse_period(certificate.get("period"))
                if isinstance(certificate, Mapping)
                else None
            )
            if period is None or period not in by_period:
                errors.append(f"capacity[{index}]:period_unknown")
                continue
            if period in capacity_by_period:
                errors.append(f"capacity[{index}]:duplicate_period")
                continue
            capacity_by_period[period] = certificate
            replay = _replay_certificate(
                certificate,
                period,
                by_period[period],
                capacity_edges[period],
                label=f"capacity[{index}]",
                errors=errors,
            )
            if replay.primal_cost is not None:
                capacity_sum += int(replay.primal_cost)
        if claim_bearing and set(capacity_by_period) != set(periods):
            errors.append("capacity:period_partition_incomplete")
        if claim_bearing:
            replayed_capacity_lower_bound = int(capacity_sum)
            raw_capacity_lb = serialized_result.get("capacity_lower_bound")
            if not _is_int(raw_capacity_lb) or int(raw_capacity_lb) != int(capacity_sum):
                errors.append("lower_bound:capacity_mismatch")

        hall_periods: set[PeriodKey] = set()
        for index, witness in enumerate(hall_witnesses):
            period = _replay_hall_witness(
                witness,
                by_period,
                capacity_edges,
                label=f"hall[{index}]",
                errors=errors,
            )
            if period is not None:
                if period in hall_periods:
                    errors.append(f"hall[{index}]:duplicate_period")
                hall_periods.add(period)
        if claim_bearing and hall_witnesses:
            errors.append("hall:witness_present_for_feasible_claim")
        if status == "infeasible" and not hall_witnesses:
            errors.append("hall:missing_for_infeasible_status")

        if claim_bearing and candidate is not None:
            incumbent_terms = _score_terms(inst, incumbent, spec)
            candidate_terms = _score_terms(inst, candidate, spec)
            canonical_incumbent = _canonical_terms(inst, incumbent, spec.objective_id)
            canonical_candidate = _canonical_terms(inst, candidate, spec.objective_id)
            if incumbent_terms != canonical_incumbent:
                errors.append("objective:incumbent_canonical_parity_failed")
            if candidate_terms != canonical_candidate:
                errors.append("objective:candidate_canonical_parity_failed")
            serialized_incumbent_terms = _parse_terms(
                serialized_result.get("incumbent_terms"),
                spec,
                label="incumbent_terms",
                errors=errors,
            )
            serialized_candidate_terms = _parse_terms(
                serialized_result.get("candidate_terms"),
                spec,
                label="candidate_terms",
                errors=errors,
            )
            if serialized_incumbent_terms != incumbent_terms:
                errors.append("incumbent_terms:replay_mismatch")
            if serialized_candidate_terms != candidate_terms:
                errors.append("candidate_terms:replay_mismatch")

            by_key_period: dict[SupportKey, Counter[PeriodKey]] = defaultdict(Counter)
            for activity_id, row in incumbent.items():
                period = (int(row["week"]), str(row["day"]), int(row["slot"]))
                for key in spec.support_keys_by_activity[int(activity_id)]:
                    by_key_period[key][period] += 1
            stability_lower_bound = int(spec.stability_weight) * sum(
                max(0, max(counts.values(), default=0) - 1)
                for counts in by_key_period.values()
            )
            if not _is_int(serialized_result.get("stability_lower_bound")) or int(
                serialized_result["stability_lower_bound"]
            ) != int(stability_lower_bound):
                errors.append("lower_bound:stability_mismatch")
            replayed_room_lower_bound = int(capacity_sum) + int(stability_lower_bound)
            if not _is_int(serialized_result.get("room_lower_bound")) or int(
                serialized_result["room_lower_bound"]
            ) != replayed_room_lower_bound:
                errors.append("lower_bound:room_mismatch")
            if candidate_terms.total < replayed_room_lower_bound:
                errors.append("lower_bound:violated_by_candidate")

            improved = candidate_terms.total < incumbent_terms.total
            if candidate_terms.total > incumbent_terms.total:
                errors.append("objective:candidate_worsens_incumbent")
            if serialized_result.get("improved") is not improved:
                errors.append("result:improved_flag_mismatch")
            if status != ("improved" if improved else "no_improvement"):
                errors.append("result:status_objective_mismatch")
            global_optimal = candidate_terms.total == replayed_room_lower_bound
            if serialized_result.get("global_optimal") is not global_optimal:
                errors.append("proof:global_optimal_flag_mismatch")

            local_flag = serialized_result.get("one_period_local_optimal") is True
            local_by_period: dict[PeriodKey, Any] = {}
            if local_flag:
                counts: dict[SupportKey, Counter[int]] = defaultdict(Counter)
                for activity_id, row in candidate.items():
                    for key in spec.support_keys_by_activity[int(activity_id)]:
                        counts[key][int(row["room_id"])] += 1
                for index, certificate in enumerate(local_certificates):
                    period = (
                        _parse_period(certificate.get("period"))
                        if isinstance(certificate, Mapping)
                        else None
                    )
                    if period is None or period not in by_period:
                        errors.append(f"local[{index}]:period_unknown")
                        continue
                    if period in local_by_period:
                        errors.append(f"local[{index}]:duplicate_period")
                        continue
                    local_by_period[period] = certificate
                    block_counts: dict[SupportKey, Counter[int]] = defaultdict(Counter)
                    touched_keys: set[SupportKey] = set()
                    for activity_id in by_period[period]:
                        room_id = int(candidate[int(activity_id)]["room_id"])
                        for key in spec.support_keys_by_activity[int(activity_id)]:
                            touched_keys.add(key)
                            block_counts[key][room_id] += 1
                    outside_rooms = {
                        key: {
                            room_id
                            for room_id, count in counts[key].items()
                            if int(count) - int(block_counts[key].get(room_id, 0)) > 0
                        }
                        for key in touched_keys
                    }
                    local_edges: dict[int, dict[int, int]] = {}
                    for activity_id in by_period[period]:
                        row_edges: dict[int, int] = {}
                        for room_id in domains[int(activity_id)]:
                            cost = int(capacity_costs[(int(activity_id), int(room_id))])
                            for key in spec.support_keys_by_activity[int(activity_id)]:
                                outside = outside_rooms[key]
                                if outside and int(room_id) not in outside:
                                    cost += int(spec.stability_weight)
                            row_edges[int(room_id)] = int(cost)
                        local_edges[int(activity_id)] = row_edges
                    replay = _replay_certificate(
                        certificate,
                        period,
                        by_period[period],
                        local_edges,
                        label=f"local[{index}]",
                        errors=errors,
                    )
                    current_block_cost = sum(
                        int(local_edges[int(activity_id)][int(candidate[int(activity_id)]["room_id"])])
                        for activity_id in by_period[period]
                    )
                    if replay.primal_cost != int(current_block_cost):
                        errors.append(f"local[{index}]:not_no_change_optimum")
                if set(local_by_period) != set(periods):
                    errors.append("local:period_partition_incomplete")
                if not _is_int(serialized_result.get("sweeps")) or int(
                    serialized_result["sweeps"]
                ) < 1:
                    errors.append("local:sweep_count_invalid")
            elif local_certificates:
                errors.append("local:certificates_without_local_claim")

            expected_proof_status = (
                "global_optimal"
                if global_optimal
                else "one_period_local_optimal"
                if local_flag
                else "no_proof"
            )
            if serialized_result.get("proof_status") != expected_proof_status:
                errors.append("proof:status_mismatch")
            if serialized_result.get("proof_scope") != "fixed_time_room_assignment":
                errors.append("proof:scope_mismatch")
            if serialized_result.get("objective_parity_checked") is not True:
                errors.append("objective:parity_not_checked")
            if serialized_result.get("objective_parity") is not True:
                errors.append("objective:parity_not_true")
            if serialized_result.get("validation_attempted") is not True:
                errors.append("validation:not_attempted")
            if serialized_result.get("validation_errors") != []:
                errors.append("validation:serialized_errors_not_empty")
            if serialized_result.get("fixed_starts_preserved") is not True:
                errors.append("candidate:fixed_starts_flag_not_true")
            if not _is_int(serialized_result.get("accepted_blocks")) or int(
                serialized_result["accepted_blocks"]
            ) < 0:
                errors.append("result:accepted_blocks_invalid")
            if not _is_int(serialized_result.get("sweeps")) or int(
                serialized_result["sweeps"]
            ) < 0:
                errors.append("result:sweeps_invalid")
            allowed_starts = {
                "incumbent",
                "capacity_lower_bound",
                "incumbent_forward",
                "incumbent_reverse",
                "capacity_forward",
            }
            if serialized_result.get("selected_start") not in allowed_starts:
                errors.append("result:selected_start_invalid")
            if local_flag and serialized_result.get("selected_start") not in {
                "incumbent_forward",
                "incumbent_reverse",
                "capacity_forward",
            }:
                errors.append("local:selected_start_not_coordinate_descent")
        else:
            if serialized_result.get("improved") is not False:
                errors.append("result:nonclaim_improved_true")
            if serialized_result.get("global_optimal") is not False:
                errors.append("result:nonclaim_global_optimal_true")
            if serialized_result.get("one_period_local_optimal") is not False:
                errors.append("result:nonclaim_local_optimal_true")
            if serialized_result.get("proof_status") != "no_proof":
                errors.append("result:nonclaim_proof_status")
            if serialized_result.get("proof_scope") != "fixed_time_room_assignment":
                errors.append("result:proof_scope_mismatch")

        return FixedTimeRoomProofVerification(
            valid=not errors,
            errors=tuple(dict.fromkeys(errors)),
            candidate_schedule=candidate if not errors else None,
            capacity_lower_bound=(
                replayed_capacity_lower_bound if not errors else None
            ),
            room_lower_bound=replayed_room_lower_bound if not errors else None,
        )
    except Exception as exc:  # fail closed on malformed or inconsistent input
        errors.append(f"checker_internal:{type(exc).__name__}:{exc}")
        return FixedTimeRoomProofVerification(False, tuple(dict.fromkeys(errors)))
