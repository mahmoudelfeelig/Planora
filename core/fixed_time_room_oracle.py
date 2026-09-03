from __future__ import annotations

import hashlib
import json
import time
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable, Hashable, Iterable, Mapping, Sequence

from utils.distribution_constraints import normalize_distribution_type
from utils.domain import Instance
from utils.demand import required_capacity
from utils.schedule_rules import hard_flag, room_is_available


PeriodKey = tuple[int, str, int]
SupportKey = tuple[Hashable, ...]
RoomValidator = Callable[[Instance, dict[int, dict[str, Any]]], Sequence[str]]
ROOM_PROOF_SCHEMA_VERSION = "planora.fixed_time_room_oracle.v1"


class RoomOracleDeadline(RuntimeError):
    """Raised internally when a checked polynomial block exceeds its deadline."""


class MatchingInfeasible(ValueError):
    """Raised when the activity-room graph has no left-perfect matching."""


@dataclass(frozen=True)
class MatchingVerification:
    valid: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchingCertificate:
    """Primal/dual certificate for one rectangular assignment problem.

    The certificate uses the dual of a left-perfect matching formulation. Row
    potentials are free and room potentials are non-positive because rooms have
    capacity at most one.  Feasibility, complementary slackness, and equal
    primal/dual objectives are independently replayed before a certificate is
    accepted.
    """

    period: PeriodKey | None
    activity_ids: tuple[int, ...]
    room_ids: tuple[int, ...]
    assignments: tuple[tuple[int, int], ...]
    row_potentials: tuple[tuple[int, int], ...]
    room_potentials: tuple[tuple[int, int], ...]
    primal_cost: int
    dual_cost: int
    domain_digest: str
    candidate_edges: tuple[tuple[int, tuple[tuple[int, int], ...]], ...] = ()
    method: str = "dense_rectangular_hungarian"
    checked: bool = False

    def assignment_dict(self) -> dict[int, int]:
        return {int(activity_id): int(room_id) for activity_id, room_id in self.assignments}

    def to_dict(
        self,
        *,
        include_potentials: bool = True,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        _check_deadline(deadline, "certificate serialization")
        serialized_edges: list[list[Any]] = []
        for activity_id, edges in self.candidate_edges:
            _check_deadline(deadline, "certificate serialization")
            serialized_row: list[list[int]] = []
            for room_id, cost in edges:
                _check_deadline(deadline, "certificate serialization")
                serialized_row.append([int(room_id), int(cost)])
            serialized_edges.append([int(activity_id), serialized_row])
        payload: dict[str, Any] = {
            "period": None if self.period is None else list(self.period),
            "activity_ids": list(self.activity_ids),
            "room_ids": list(self.room_ids),
            "assignments": [list(item) for item in self.assignments],
            "primal_cost": int(self.primal_cost),
            "dual_cost": int(self.dual_cost),
            "domain_digest": str(self.domain_digest),
            "method": str(self.method),
            "complexity": "O(A^2 * R) for A <= R",
            "checked": bool(self.checked),
            "candidate_edges": serialized_edges,
        }
        if include_potentials:
            payload["row_potentials"] = [list(item) for item in self.row_potentials]
            payload["room_potentials"] = [list(item) for item in self.room_potentials]
        _check_deadline(deadline, "certificate serialization")
        return payload


@dataclass(frozen=True)
class RoomOracleHallWitness:
    period: PeriodKey
    activity_ids: tuple[int, ...]
    candidate_room_ids: tuple[int, ...]
    deficiency: int
    domain_digest: str

    def to_dict(self, *, deadline: float | None = None) -> dict[str, Any]:
        _check_deadline(deadline, "Hall witness serialization")
        return {
            "period": list(self.period),
            "activity_ids": list(self.activity_ids),
            "candidate_room_ids": list(self.candidate_room_ids),
            "deficiency": int(self.deficiency),
            "domain_digest": str(self.domain_digest),
            "proof_rule": "hall_neighborhood_deficiency",
        }


@dataclass(frozen=True)
class PeriodRoomProjection:
    """Exact additive projection for one fixed period."""

    period: PeriodKey
    feasible: bool
    cost: int | None = None
    certificate: MatchingCertificate | None = None
    hall_witness: RoomOracleHallWitness | None = None

    def to_dict(self, *, deadline: float | None = None) -> dict[str, Any]:
        _check_deadline(deadline, "period projection serialization")
        payload = {
            "period": list(self.period),
            "feasible": bool(self.feasible),
            "cost": self.cost,
            "certificate": (
                None
                if self.certificate is None
                else self.certificate.to_dict(deadline=deadline)
            ),
            "hall_witness": (
                None
                if self.hall_witness is None
                else self.hall_witness.to_dict(deadline=deadline)
            ),
        }
        _check_deadline(deadline, "period projection serialization")
        return payload


@dataclass(frozen=True)
class RoomOracleEligibility:
    eligible: bool
    objective_id: str | None
    structural_class: str
    reasons: tuple[str, ...] = ()
    activity_count: int = 0
    period_count: int = 0
    room_count: int = 0
    capacity_weight: int = 0
    stability_weight: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class FixedTimeRoomTerms:
    objective_id: str
    capacity: int
    stability: int

    @property
    def total(self) -> int:
        return int(self.capacity) + int(self.stability)

    def to_dict(self) -> dict[str, Any]:
        stability_name = (
            "room_stability"
            if self.objective_id == "itc2007_official"
            else "room_consistency"
        )
        return {
            "objective_id": str(self.objective_id),
            "room_capacity": int(self.capacity),
            stability_name: int(self.stability),
            "room_total": int(self.total),
        }


@dataclass
class FixedTimeRoomOracleResult:
    status: str
    eligibility: RoomOracleEligibility
    best_schedule: dict[int, dict[str, Any]] | None = None
    improved: bool = False
    incumbent_terms: FixedTimeRoomTerms | None = None
    candidate_terms: FixedTimeRoomTerms | None = None
    capacity_lower_bound: int | None = None
    stability_lower_bound: int | None = None
    room_lower_bound: int | None = None
    global_optimal: bool = False
    one_period_local_optimal: bool = False
    proof_status: str = "no_proof"
    proof_scope: str = "fixed_time_room_assignment"
    selected_start: str = "incumbent"
    capacity_certificates: tuple[MatchingCertificate, ...] = ()
    local_certificates: tuple[MatchingCertificate, ...] = ()
    hall_witnesses: tuple[RoomOracleHallWitness, ...] = ()
    objective_parity_checked: bool = False
    objective_parity: bool | None = None
    validation_attempted: bool = False
    validation_errors: tuple[str, ...] = ()
    fixed_starts_preserved: bool | None = None
    sweeps: int = 0
    accepted_blocks: int = 0
    timing: dict[str, float | int | None] = field(default_factory=dict)
    incumbent_fixed_time_digest: str | None = None
    candidate_fixed_time_digest: str | None = None
    objective_digest: str | None = None
    room_semantics_digest: str | None = None
    error: str | None = None

    def to_dict(self, *, deadline: float | None = None) -> dict[str, Any]:
        _check_deadline(deadline, "oracle result serialization")
        capacity_certificates = [
            certificate.to_dict(deadline=deadline)
            for certificate in self.capacity_certificates
        ]
        local_certificates = [
            certificate.to_dict(deadline=deadline)
            for certificate in self.local_certificates
        ]
        payload = {
            "proof_schema_version": ROOM_PROOF_SCHEMA_VERSION,
            "proof_integrity": "unsigned_replayable_certificate",
            "status": str(self.status),
            "eligibility": self.eligibility.to_dict(),
            "improved": bool(self.improved),
            "incumbent_terms": (
                None if self.incumbent_terms is None else self.incumbent_terms.to_dict()
            ),
            "candidate_terms": (
                None if self.candidate_terms is None else self.candidate_terms.to_dict()
            ),
            "capacity_lower_bound": self.capacity_lower_bound,
            "stability_lower_bound": self.stability_lower_bound,
            "room_lower_bound": self.room_lower_bound,
            "global_optimal": bool(self.global_optimal),
            "one_period_local_optimal": bool(self.one_period_local_optimal),
            "proof_status": str(self.proof_status),
            "proof_scope": str(self.proof_scope),
            "selected_start": str(self.selected_start),
            "candidate_room_assignment": (
                None
                if self.best_schedule is None
                else [
                    [int(activity_id), int(self.best_schedule[activity_id]["room_id"])]
                    for activity_id in sorted(self.best_schedule)
                ]
            ),
            "incumbent_fixed_time_digest": self.incumbent_fixed_time_digest,
            "candidate_fixed_time_digest": self.candidate_fixed_time_digest,
            "objective_digest": self.objective_digest,
            "room_semantics_digest": self.room_semantics_digest,
            "capacity_certificate_count": len(self.capacity_certificates),
            "capacity_certificate_status": (
                "not_applicable"
                if not self.capacity_certificates
                else "internally_replayed"
                if all(certificate.checked for certificate in self.capacity_certificates)
                else "unverified"
            ),
            "capacity_certificates_checked": (
                None
                if not self.capacity_certificates
                else all(certificate.checked for certificate in self.capacity_certificates)
            ),
            "capacity_certificates": capacity_certificates,
            "local_certificate_count": len(self.local_certificates),
            "local_certificate_status": (
                "not_applicable"
                if not self.local_certificates
                else "internally_replayed"
                if all(certificate.checked for certificate in self.local_certificates)
                else "unverified"
            ),
            "local_certificates_checked": (
                None
                if not self.local_certificates
                else all(certificate.checked for certificate in self.local_certificates)
            ),
            "local_certificates": local_certificates,
            "hall_witnesses": [
                item.to_dict(deadline=deadline) for item in self.hall_witnesses
            ],
            "objective_parity_checked": bool(self.objective_parity_checked),
            "objective_parity": self.objective_parity,
            "validation_attempted": bool(self.validation_attempted),
            "validation_errors": list(self.validation_errors),
            "fixed_starts_preserved": self.fixed_starts_preserved,
            "sweeps": int(self.sweeps),
            "accepted_blocks": int(self.accepted_blocks),
            "timing": dict(self.timing),
            "error": self.error,
        }
        _check_deadline(deadline, "oracle result serialization")
        return payload


@dataclass(frozen=True)
class _ObjectiveSpec:
    objective_id: str
    capacity_weight: int
    stability_weight: int
    students_by_course: Mapping[int, int]
    support_keys_by_activity: Mapping[int, tuple[SupportKey, ...]]


@dataclass
class _CoordinateResult:
    schedule: dict[int, dict[str, Any]]
    terms: FixedTimeRoomTerms
    start_name: str
    sweeps: int
    accepted_blocks: int
    local_optimal: bool
    certificates: tuple[MatchingCertificate, ...]


def _expired(deadline: float | None) -> bool:
    return deadline is not None and time.perf_counter() >= float(deadline)


def _check_deadline(deadline: float | None, phase: str) -> None:
    if _expired(deadline):
        raise RoomOracleDeadline(f"Room oracle deadline expired during {phase}")


def _period_key(row: Mapping[str, Any]) -> PeriodKey:
    return int(row["week"]), str(row["day"]), int(row["slot"])


def _fixed_time_digest(
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float | None = None,
) -> str:
    """Bind proof telemetry to activity ids and immutable time coordinates."""

    digest = hashlib.sha256()
    digest.update(b"PLANORA_FIXED_TIME_V1;")

    def update_token(tag: bytes, value: object) -> None:
        encoded = str(value).encode("utf-8")
        digest.update(tag)
        digest.update(str(len(encoded)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded)
        digest.update(b";")

    normalized: list[tuple[int, Mapping[str, Any]]] = []
    for raw_activity_id, row in schedule.items():
        _check_deadline(deadline, "fixed-time digest")
        normalized.append((int(raw_activity_id), row))
    for activity_id, row in sorted(normalized):
        _check_deadline(deadline, "fixed-time digest")
        update_token(b"A", int(activity_id))
        update_token(b"W", int(row["week"]))
        update_token(b"D", str(row["day"]))
        update_token(b"S", int(row["slot"]))
        update_token(b"L", int(row["duration"]))
        digest.update(b"Z;")
    _check_deadline(deadline, "fixed-time digest")
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
            [
                int(activity_id),
                [[value for value in key] for key in keys],
            ]
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


def _normalized_edges(
    activity_ids: Iterable[int],
    candidate_edges: Mapping[int, Iterable[tuple[int, int]]],
    *,
    deadline: float | None = None,
) -> tuple[tuple[int, ...], tuple[int, ...], dict[int, dict[int, int]]]:
    _check_deadline(deadline, "edge normalization")
    raw_activities: list[int] = []
    for index, value in enumerate(activity_ids):
        if index % 64 == 0:
            _check_deadline(deadline, "edge normalization")
        raw_activities.append(int(value))
    activities = tuple(sorted(raw_activities))
    _check_deadline(deadline, "edge normalization")
    if len(set(activities)) != len(activities):
        raise ValueError("Matching activity ids must be unique")
    normalized: dict[int, dict[int, int]] = {}
    room_set: set[int] = set()
    edge_count = 0
    for activity_id in activities:
        _check_deadline(deadline, "edge normalization")
        room_costs: dict[int, int] = {}
        for raw_room_id, raw_cost in candidate_edges.get(int(activity_id), ()):
            edge_count += 1
            if edge_count % 64 == 0:
                _check_deadline(deadline, "edge normalization")
            room_id = int(raw_room_id)
            cost = int(raw_cost)
            if cost < 0:
                raise ValueError("The room oracle requires non-negative integer edge costs")
            if room_id in room_costs:
                raise ValueError(
                    f"Duplicate room edge for activity {activity_id} and room {room_id}"
                )
            room_costs[room_id] = cost
            room_set.add(room_id)
        normalized[int(activity_id)] = room_costs
    _check_deadline(deadline, "edge normalization")
    rooms = tuple(sorted(room_set))
    _check_deadline(deadline, "edge normalization")
    return activities, rooms, normalized


def _domain_digest(
    activities: Sequence[int],
    edges: Mapping[int, Mapping[int, int]],
    *,
    deadline: float | None = None,
) -> str:
    # Incremental encoding avoids an uninterruptible O(E) JSON allocation on
    # dense projections. Length-prefixing makes the digest unambiguous.
    digest = hashlib.sha256()

    def update_integer(value: int) -> None:
        token = str(int(value)).encode("ascii")
        digest.update(str(len(token)).encode("ascii"))
        digest.update(b":")
        digest.update(token)
        digest.update(b";")

    edge_count = 0
    for activity_id in activities:
        _check_deadline(deadline, "domain digest")
        digest.update(b"A")
        update_integer(int(activity_id))
        for room_id, cost in sorted(edges[int(activity_id)].items()):
            edge_count += 1
            if edge_count % 64 == 0:
                _check_deadline(deadline, "domain digest")
            digest.update(b"E")
            update_integer(int(room_id))
            update_integer(int(cost))
        digest.update(b"Z")
    _check_deadline(deadline, "domain digest")
    return digest.hexdigest()


def _edge_context(
    activities: Sequence[int],
    edges: Mapping[int, Mapping[int, int]],
    *,
    deadline: float | None = None,
) -> tuple[tuple[int, tuple[tuple[int, int], ...]], ...]:
    context: list[tuple[int, tuple[tuple[int, int], ...]]] = []
    for activity_id in activities:
        _check_deadline(deadline, "certificate edge-context construction")
        row: list[tuple[int, int]] = []
        for room_id, cost in sorted(edges[int(activity_id)].items()):
            _check_deadline(deadline, "certificate edge-context construction")
            row.append((int(room_id), int(cost)))
        context.append((int(activity_id), tuple(row)))
    return tuple(context)


def verify_matching_certificate(
    activity_ids: Iterable[int],
    candidate_edges: Mapping[int, Iterable[tuple[int, int]]],
    certificate: MatchingCertificate,
    *,
    deadline: float | None = None,
    expected_period: PeriodKey | None = None,
    expected_method: str = "dense_rectangular_hungarian",
) -> MatchingVerification:
    """Replay a rectangular Hungarian certificate independently."""

    errors: list[str] = []
    try:
        activities, rooms, edges = _normalized_edges(
            activity_ids,
            candidate_edges,
            deadline=deadline,
        )
    except (TypeError, ValueError) as exc:
        return MatchingVerification(False, (f"invalid_edges:{exc}",))
    if activities != tuple(certificate.activity_ids):
        errors.append("activity_set_mismatch")
    if rooms != tuple(certificate.room_ids):
        errors.append("room_set_mismatch")
    if certificate.period != expected_period:
        errors.append("period_mismatch")
    if str(certificate.method) != str(expected_method):
        errors.append("method_mismatch")
    if _domain_digest(activities, edges, deadline=deadline) != str(certificate.domain_digest):
        errors.append("domain_digest_mismatch")

    expected_edge_context = _edge_context(
        activities,
        edges,
        deadline=deadline,
    )
    if tuple(certificate.candidate_edges) != expected_edge_context:
        errors.append("candidate_edge_context_mismatch")
    if len(certificate.assignments) != len(
        {int(activity_id) for activity_id, _room_id in certificate.assignments}
    ):
        errors.append("duplicate_assignment_activity")
    assignments = certificate.assignment_dict()
    if set(assignments) != set(activities):
        errors.append("assignment_not_left_perfect")
    if len(set(assignments.values())) != len(assignments):
        errors.append("assignment_reuses_room")
    primal = 0
    for index, (activity_id, room_id) in enumerate(assignments.items()):
        if index % 64 == 0:
            _check_deadline(deadline, "certificate primal replay")
        if room_id not in edges.get(int(activity_id), {}):
            errors.append(f"forbidden_assignment:{activity_id}:{room_id}")
            continue
        primal += int(edges[int(activity_id)][int(room_id)])

    if len(certificate.row_potentials) != len(
        {int(key) for key, _value in certificate.row_potentials}
    ):
        errors.append("duplicate_row_potential")
    if len(certificate.room_potentials) != len(
        {int(key) for key, _value in certificate.room_potentials}
    ):
        errors.append("duplicate_room_potential")
    row_duals = {int(key): int(value) for key, value in certificate.row_potentials}
    room_duals = {int(key): int(value) for key, value in certificate.room_potentials}
    if set(row_duals) != set(activities):
        errors.append("row_potential_set_mismatch")
    if set(room_duals) != set(rooms):
        errors.append("room_potential_set_mismatch")
    for room_id, potential in room_duals.items():
        if int(potential) > 0:
            errors.append(f"positive_room_potential:{room_id}")
    replayed_edges = 0
    for activity_id in activities:
        _check_deadline(deadline, "certificate dual replay")
        if activity_id not in row_duals:
            continue
        for room_id, cost in edges[int(activity_id)].items():
            replayed_edges += 1
            if replayed_edges % 64 == 0:
                _check_deadline(deadline, "certificate dual replay")
            if room_id not in room_duals:
                continue
            if int(row_duals[activity_id]) + int(room_duals[room_id]) > int(cost):
                errors.append(f"dual_infeasible:{activity_id}:{room_id}")
    for index, (activity_id, room_id) in enumerate(assignments.items()):
        if index % 64 == 0:
            _check_deadline(deadline, "certificate tight-edge replay")
        if (
            activity_id in row_duals
            and room_id in room_duals
            and room_id in edges.get(activity_id, {})
            and int(row_duals[activity_id]) + int(room_duals[room_id])
            != int(edges[activity_id][room_id])
        ):
            errors.append(f"matched_edge_not_tight:{activity_id}:{room_id}")

    dual = sum(row_duals.values()) + sum(room_duals.values())
    if int(primal) != int(certificate.primal_cost):
        errors.append("primal_cost_mismatch")
    if int(dual) != int(certificate.dual_cost):
        errors.append("dual_cost_mismatch")
    if int(primal) != int(dual):
        errors.append("primal_dual_gap")
    return MatchingVerification(not errors, tuple(errors))


def solve_min_cost_matching(
    activity_ids: Iterable[int],
    candidate_edges: Mapping[int, Iterable[tuple[int, int]]],
    *,
    period: PeriodKey | None = None,
    deadline: float | None = None,
) -> MatchingCertificate:
    """Solve a left-perfect matching in deterministic polynomial time.

    A dense rectangular Hungarian shortest-augmenting-path implementation is
    used on the completed matrix in O(A^2 R) time for A activities and R rooms.
    The forbidden-edge sentinel is greater than the cost of every all-allowed
    assignment because eligible costs are non-negative. A returned certificate
    is accepted only after admissible-edge dual replay, so the sentinel is never
    part of the proof.
    """

    activities, rooms, edges = _normalized_edges(
        activity_ids,
        candidate_edges,
        deadline=deadline,
    )
    digest = _domain_digest(activities, edges, deadline=deadline)
    if not activities:
        return MatchingCertificate(
            period=period,
            activity_ids=(),
            room_ids=(),
            assignments=(),
            row_potentials=(),
            room_potentials=(),
            primal_cost=0,
            dual_cost=0,
            domain_digest=digest,
            candidate_edges=(),
            checked=True,
        )
    if len(rooms) < len(activities) or any(not edges[activity_id] for activity_id in activities):
        raise MatchingInfeasible("The room graph cannot cover every activity")
    _check_deadline(deadline, "matching setup")

    n = len(activities)
    m = len(rooms)
    max_cost = 0
    seen_costs = 0
    for activity_id in activities:
        _check_deadline(deadline, "matching cost bound")
        for cost in edges[int(activity_id)].values():
            seen_costs += 1
            if seen_costs % 64 == 0:
                _check_deadline(deadline, "matching cost bound")
            max_cost = max(max_cost, int(cost))
    forbidden_cost = int(n) * int(max_cost) + 1
    matrix: list[list[int]] = []
    matrix_cells = 0
    for activity_id in activities:
        _check_deadline(deadline, "matching matrix construction")
        row_values: list[int] = []
        for room_id in rooms:
            matrix_cells += 1
            if matrix_cells % 64 == 0:
                _check_deadline(deadline, "matching matrix construction")
            row_values.append(int(edges[activity_id].get(room_id, forbidden_cost)))
        matrix.append(row_values)

    # One-indexed implementation of the rectangular Hungarian algorithm.
    u = [0] * (n + 1)
    v = [0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)
    infinity = forbidden_cost * (n + m + 2) + 1
    for row in range(1, n + 1):
        _check_deadline(deadline, "matching augmentation")
        p[0] = row
        column0 = 0
        min_value = [infinity] * (m + 1)
        used = [False] * (m + 1)
        while True:
            _check_deadline(deadline, "matching augmentation")
            used[column0] = True
            row0 = p[column0]
            delta = infinity
            column1 = 0
            for column in range(1, m + 1):
                if column % 64 == 0:
                    _check_deadline(deadline, "matching augmentation")
                if used[column]:
                    continue
                reduced = matrix[row0 - 1][column - 1] - u[row0] - v[column]
                if reduced < min_value[column]:
                    min_value[column] = int(reduced)
                    way[column] = int(column0)
                if min_value[column] < delta:
                    delta = int(min_value[column])
                    column1 = int(column)
            if column1 == 0 or delta >= infinity:
                raise MatchingInfeasible("No augmenting path covers every activity")
            for column in range(m + 1):
                if column % 64 == 0:
                    _check_deadline(deadline, "matching dual update")
                if used[column]:
                    u[p[column]] += int(delta)
                    v[column] -= int(delta)
                else:
                    min_value[column] -= int(delta)
            column0 = int(column1)
            if p[column0] == 0:
                break
        while True:
            column1 = way[column0]
            p[column0] = p[column1]
            column0 = int(column1)
            if column0 == 0:
                break

    assigned_columns = [0] * (n + 1)
    for column in range(1, m + 1):
        if p[column] != 0:
            assigned_columns[p[column]] = int(column)
    assignments: list[tuple[int, int]] = []
    for row, activity_id in enumerate(activities, start=1):
        if row % 64 == 0:
            _check_deadline(deadline, "matching extraction")
        column = assigned_columns[row]
        if column <= 0:
            raise MatchingInfeasible("The assignment is not left-perfect")
        room_id = int(rooms[column - 1])
        if room_id not in edges[int(activity_id)]:
            raise MatchingInfeasible("Every complete-matrix optimum uses a forbidden edge")
        assignments.append((int(activity_id), room_id))

    row_potentials = tuple(
        (int(activity_id), int(u[index]))
        for index, activity_id in enumerate(activities, start=1)
    )
    room_potentials = tuple(
        (int(room_id), int(v[index]))
        for index, room_id in enumerate(rooms, start=1)
    )
    primal = sum(int(edges[activity_id][room_id]) for activity_id, room_id in assignments)
    dual = sum(value for _, value in row_potentials) + sum(
        value for _, value in room_potentials
    )
    unchecked = MatchingCertificate(
        period=period,
        activity_ids=activities,
        room_ids=rooms,
        assignments=tuple(assignments),
        row_potentials=row_potentials,
        room_potentials=room_potentials,
        primal_cost=int(primal),
        dual_cost=int(dual),
        domain_digest=digest,
        candidate_edges=_edge_context(activities, edges, deadline=deadline),
        checked=False,
    )
    _check_deadline(deadline, "certificate replay")
    verification = verify_matching_certificate(
        activities,
        candidate_edges,
        unchecked,
        deadline=deadline,
        expected_period=period,
    )
    if not verification.valid:
        raise ValueError(
            "Hungarian certificate replay failed: " + ", ".join(verification.errors)
        )
    return replace(unchecked, checked=True)


def _hall_witness(
    period: PeriodKey,
    activity_ids: Iterable[int],
    candidate_edges: Mapping[int, Iterable[tuple[int, int]]],
    *,
    deadline: float | None = None,
) -> RoomOracleHallWitness:
    activities, _rooms, costs = _normalized_edges(
        activity_ids,
        candidate_edges,
        deadline=deadline,
    )
    edges: dict[int, tuple[int, ...]] = {}
    for activity_id in activities:
        _check_deadline(deadline, "Hall graph construction")
        edges[int(activity_id)] = tuple(
            sorted(int(room_id) for room_id in costs[activity_id])
        )

    # Iterative layered augmenting paths avoid Python recursion limits on long
    # alternating chains. This is a deterministic polynomial maximum-matching
    # routine; no tighter Hopcroft-Karp complexity claim is needed here.
    activity_to_room: dict[int, int] = {}
    room_to_activity: dict[int, int] = {}
    distance: dict[int, int] = {}
    traversed_edges = 0

    def build_layers() -> bool:
        nonlocal traversed_edges
        queue: deque[int] = deque()
        distance.clear()
        for activity_id in activities:
            if int(activity_id) not in activity_to_room:
                distance[int(activity_id)] = 0
                queue.append(int(activity_id))
        found_free_room = False
        while queue:
            _check_deadline(deadline, "Hall matching BFS")
            activity_id = queue.popleft()
            for room_id in edges.get(activity_id, ()):
                traversed_edges += 1
                if traversed_edges % 256 == 0:
                    _check_deadline(deadline, "Hall matching BFS")
                matched_activity = room_to_activity.get(room_id)
                if matched_activity is None:
                    found_free_room = True
                elif matched_activity not in distance:
                    distance[matched_activity] = distance[activity_id] + 1
                    queue.append(matched_activity)
        return found_free_room

    def augment_layered(start_activity: int) -> bool:
        nonlocal traversed_edges
        path_activities = [int(start_activity)]
        path_rooms: list[int] = []
        next_edge_index = [0]
        while path_activities:
            activity_id = path_activities[-1]
            adjacency = edges.get(activity_id, ())
            descended = False
            while next_edge_index[-1] < len(adjacency):
                edge_index = next_edge_index[-1]
                next_edge_index[-1] += 1
                room_id = int(adjacency[edge_index])
                traversed_edges += 1
                if traversed_edges % 256 == 0:
                    _check_deadline(deadline, "Hall matching DFS")
                matched_activity = room_to_activity.get(room_id)
                if matched_activity is None:
                    augmenting_rooms = [*path_rooms, room_id]
                    for left_id, right_id in zip(
                        path_activities,
                        augmenting_rooms,
                        strict=True,
                    ):
                        activity_to_room[int(left_id)] = int(right_id)
                        room_to_activity[int(right_id)] = int(left_id)
                    return True
                if distance.get(matched_activity) == distance[activity_id] + 1:
                    path_rooms.append(room_id)
                    path_activities.append(int(matched_activity))
                    next_edge_index.append(0)
                    descended = True
                    break
            if descended:
                continue
            distance[activity_id] = len(activities) + 1
            path_activities.pop()
            next_edge_index.pop()
            if path_rooms:
                path_rooms.pop()
        return False

    while build_layers():
        augmented = False
        for activity_id in activities:
            _check_deadline(deadline, "Hall matching phase")
            if int(activity_id) in activity_to_room:
                continue
            if augment_layered(int(activity_id)):
                augmented = True
        if not augmented:
            break
    reachable_activities = {
        int(activity_id) for activity_id in activities if activity_id not in activity_to_room
    }
    reachable_rooms: set[int] = set()
    queue = list(sorted(reachable_activities))
    while queue:
        _check_deadline(deadline, "Hall witness extraction")
        activity_id = queue.pop()
        matched_room = activity_to_room.get(activity_id)
        for room_id in edges.get(activity_id, ()):
            if room_id == matched_room or room_id in reachable_rooms:
                continue
            reachable_rooms.add(room_id)
            matched_activity = room_to_activity.get(room_id)
            if matched_activity is not None and matched_activity not in reachable_activities:
                reachable_activities.add(matched_activity)
                queue.append(matched_activity)
    if len(reachable_activities) <= len(reachable_rooms):
        reachable_activities = set(activities)
        reachable_rooms = {room_id for row in edges.values() for room_id in row}
    deficiency = len(reachable_activities) - len(reachable_rooms)
    return RoomOracleHallWitness(
        period=period,
        activity_ids=tuple(sorted(reachable_activities)),
        candidate_room_ids=tuple(sorted(reachable_rooms)),
        deficiency=max(1, int(deficiency)),
        domain_digest=_domain_digest(activities, costs, deadline=deadline),
    )


def solve_period_additive_projection(
    period: PeriodKey,
    activity_ids: Iterable[int],
    candidate_edges: Mapping[int, Iterable[tuple[int, int]]],
    *,
    deadline: float | None = None,
) -> PeriodRoomProjection:
    """Return an exact period cost or a checkable Hall witness.

    This projection is an admissible additive room lower bound.  It deliberately
    excludes cross-period stability and therefore must not be used as final
    schedule acceptance evidence.
    """

    normalized_ids = tuple(sorted(int(value) for value in activity_ids))
    try:
        certificate = solve_min_cost_matching(
            normalized_ids,
            candidate_edges,
            period=period,
            deadline=deadline,
        )
    except MatchingInfeasible:
        return PeriodRoomProjection(
            period=period,
            feasible=False,
            hall_witness=_hall_witness(
                period,
                normalized_ids,
                candidate_edges,
                deadline=deadline,
            ),
        )
    return PeriodRoomProjection(
        period=period,
        feasible=True,
        cost=int(certificate.primal_cost),
        certificate=certificate,
    )


def _objective_spec(
    inst: Instance,
    *,
    deadline: float | None = None,
) -> tuple[_ObjectiveSpec | None, tuple[str, ...]]:
    _check_deadline(deadline, "objective inspection")
    reasons: list[str] = []
    sla = getattr(inst, "sla_targets", {}) or {}
    benchmark_family = str(sla.get("benchmark_family", ""))
    activities: dict[int, Any] = {}
    for key, value in inst.activities.items():
        _check_deadline(deadline, "objective activity normalization")
        activities[int(key)] = value
    if benchmark_family.startswith("ITC-2007"):
        metadata = sla.get("itc2007")
        if not isinstance(metadata, dict):
            return None, ("itc2007_metadata_missing",)
        weights = metadata.get("objective_weights") or {}
        try:
            capacity_weight = int(weights.get("room_capacity", 1))
            stability_weight = int(weights.get("room_stability", 1))
        except (TypeError, ValueError):
            return None, ("itc2007_room_weight_invalid",)
        if capacity_weight < 0 or stability_weight < 0:
            reasons.append("negative_room_objective_weight")
        raw_students = metadata.get("course_students")
        if not isinstance(raw_students, dict):
            reasons.append("itc2007_course_students_missing")
            raw_students = {}
        students_by_course: dict[int, int] = {}
        for course_id, course in inst.courses.items():
            _check_deadline(deadline, "ITC objective inspection")
            code = str(course.code)
            try:
                students_by_course[int(course_id)] = int(raw_students[code])
            except (KeyError, TypeError, ValueError):
                reasons.append(f"itc2007_course_students_invalid:{code}")
        support_keys: dict[int, tuple[SupportKey, ...]] = {}
        for activity_id, activity in activities.items():
            _check_deadline(deadline, "ITC support-key construction")
            support_keys[int(activity_id)] = (("course", int(activity.course_id)),)
        return (
            _ObjectiveSpec(
                objective_id="itc2007_official",
                capacity_weight=int(capacity_weight),
                stability_weight=int(stability_weight),
                students_by_course=students_by_course,
                support_keys_by_activity=support_keys,
            ),
            tuple(reasons),
        )

    try:
        consistency_weight = int(
            (getattr(inst, "soft_weights", {}) or {}).get("room_consistency", 1)
        )
    except (TypeError, ValueError):
        return None, ("generic_room_consistency_weight_invalid",)
    if consistency_weight < 0:
        reasons.append("negative_room_objective_weight")
    support_keys: dict[int, tuple[SupportKey, ...]] = {}
    for activity_id, activity in activities.items():
        _check_deadline(deadline, "generic support-key construction")
        group_ids: set[int] = set()
        for group_id in activity.group_ids:
            _check_deadline(deadline, "generic support-key construction")
            group_ids.add(int(group_id))
        support_keys[int(activity_id)] = tuple(
            ("course_group_kind", int(activity.course_id), int(group_id), str(activity.kind))
            for group_id in sorted(group_ids)
        )
    return (
        _ObjectiveSpec(
            objective_id="planora_generic",
            capacity_weight=0,
            stability_weight=int(consistency_weight),
            students_by_course={},
            support_keys_by_activity=support_keys,
        ),
        tuple(reasons),
    )


def _has_effective_clusters(
    inst: Instance,
    *,
    deadline: float | None = None,
) -> bool:
    by_key: dict[tuple[str, int, str], int] = defaultdict(int)
    for activity in inst.activities.values():
        _check_deadline(deadline, "cluster inspection")
        if activity.cluster_key:
            by_key[(str(activity.cluster_key), int(activity.week), str(activity.kind))] += 1
    if any(count >= 2 for count in by_key.values()):
        return True
    for course_id, course in inst.courses.items():
        _check_deadline(deadline, "cluster inspection")
        shared_groups = {int(value) for value in (course.share_lecture_group_ids or [])}
        if not shared_groups:
            continue
        by_week: Counter[int] = Counter()
        for activity in inst.activities.values():
            _check_deadline(deadline, "shared-lecture cluster inspection")
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


def assess_fixed_time_room_eligibility(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float | None = None,
) -> RoomOracleEligibility:
    """Return the explicit structural predicate for the polynomial room blocks."""

    _check_deadline(deadline, "eligibility")
    spec, spec_reasons = _objective_spec(inst, deadline=deadline)
    reasons = list(spec_reasons)
    if (
        spec is not None
        and spec.objective_id == "planora_generic"
        and str(getattr(inst, "objective_profile", "") or "").strip().lower()
        == "fairness_first"
    ):
        reasons.append("fairness_first_lexicographic_room_objective_not_modeled")
    normalized_schedule: dict[int, Mapping[str, Any]] = {}
    for raw_activity_id, row in schedule.items():
        _check_deadline(deadline, "schedule eligibility inspection")
        try:
            activity_id = int(raw_activity_id)
        except (TypeError, ValueError):
            reasons.append("schedule_activity_id_invalid")
            continue
        if activity_id in normalized_schedule:
            reasons.append("schedule_activity_id_collision")
        normalized_schedule[activity_id] = row
    if set(normalized_schedule) != {int(value) for value in inst.activities}:
        reasons.append("schedule_not_complete")
    if not inst.rooms:
        reasons.append("no_rooms")
    if _has_effective_clusters(inst, deadline=deadline):
        reasons.append("co_location_cluster_requires_general_room_model")
    if hard_flag(inst, "force_repeat_weekly_pattern", False):
        reasons.append("repeat_weekly_room_pattern_requires_general_room_model")

    travel_rules = getattr(inst, "travel_time_rules", {}) or {}
    if hard_flag(inst, "enforce_travel_time_buffers", True):
        try:
            if any(int(value or 0) > 0 for value in travel_rules.values()):
                reasons.append("travel_room_coupling_requires_general_room_model")
        except (TypeError, ValueError):
            reasons.append("travel_rule_invalid")

    for constraint in getattr(inst, "distribution_constraints", []) or []:
        _check_deadline(deadline, "distribution eligibility inspection")
        try:
            kind = normalize_distribution_type(constraint.constraint_type)
        except ValueError:
            reasons.append(f"distribution_constraint_unknown:{constraint.id}")
            continue
        if kind in {"same_room", "different_room"}:
            reasons.append(f"distribution_room_coupling:{constraint.id}:{kind}")

    periods: set[PeriodKey] = set()
    valid_days = {str(value) for value in inst.days}
    support_period_counts: Counter[tuple[SupportKey, PeriodKey]] = Counter()
    for activity_id, activity in inst.activities.items():
        _check_deadline(deadline, "activity eligibility inspection")
        if int(activity.duration) != 1:
            reasons.append(f"non_unit_duration:{activity_id}")
        row = normalized_schedule.get(int(activity_id))
        if not isinstance(row, Mapping):
            reasons.append(f"schedule_row_invalid:{activity_id}")
            continue
        try:
            week = int(row["week"])
            day = str(row["day"])
            slot = int(row["slot"])
            duration = int(row["duration"])
            room_id = int(row["room_id"])
        except (KeyError, TypeError, ValueError):
            reasons.append(f"schedule_row_incomplete:{activity_id}")
            continue
        if duration != 1 or duration != int(activity.duration):
            reasons.append(f"schedule_duration_mismatch:{activity_id}")
        if week != int(activity.week):
            reasons.append(f"schedule_week_mismatch:{activity_id}")
        if day not in valid_days:
            reasons.append(f"schedule_day_invalid:{activity_id}")
        if slot < 0 or slot >= int(inst.slots_per_day):
            reasons.append(f"schedule_slot_invalid:{activity_id}")
        if room_id not in inst.rooms:
            reasons.append(f"schedule_room_invalid:{activity_id}")
        period = (week, day, slot)
        periods.add(period)
        if spec is not None:
            for support_key in spec.support_keys_by_activity.get(int(activity_id), ()):
                support_period_counts[(support_key, period)] += 1

    for (support_key, period), count in sorted(
        support_period_counts.items(),
        key=lambda item: (item[0][1], repr(item[0][0])),
    ):
        _check_deadline(deadline, "support-key eligibility inspection")
        if int(count) > 1:
            reasons.append(
                "multiple_stability_support_activities_in_period:"
                f"{period[0]}:{period[1]}:{period[2]}:{support_key!r}"
            )

    unique_reasons = tuple(dict.fromkeys(reasons))
    return RoomOracleEligibility(
        eligible=not unique_reasons and spec is not None,
        objective_id=None if spec is None else str(spec.objective_id),
        structural_class="unit_duration_fixed_time_injective_room_assignment",
        reasons=unique_reasons,
        activity_count=len(inst.activities),
        period_count=len(periods),
        room_count=len(inst.rooms),
        capacity_weight=0 if spec is None else int(spec.capacity_weight),
        stability_weight=0 if spec is None else int(spec.stability_weight),
    )


def _independent_terms(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    spec: _ObjectiveSpec,
    *,
    deadline: float | None = None,
) -> FixedTimeRoomTerms:
    capacity = 0
    if spec.objective_id == "itc2007_official":
        for activity_id, row in schedule.items():
            _check_deadline(deadline, "independent capacity scoring")
            course_id = int(inst.activities[int(activity_id)].course_id)
            room_id = int(row["room_id"])
            capacity += int(spec.capacity_weight) * max(
                0,
                int(spec.students_by_course[course_id])
                - int(inst.rooms[room_id].capacity),
            )
    key_rooms: dict[SupportKey, set[int]] = defaultdict(set)
    for activity_id, row in schedule.items():
        _check_deadline(deadline, "independent stability scoring")
        room_id = int(row["room_id"])
        for key in spec.support_keys_by_activity[int(activity_id)]:
            key_rooms[key].add(room_id)
    distinct_excess = 0
    for rooms in key_rooms.values():
        _check_deadline(deadline, "independent stability scoring")
        distinct_excess += max(0, len(rooms) - 1)
    stability = int(spec.stability_weight) * int(distinct_excess)
    return FixedTimeRoomTerms(
        objective_id=str(spec.objective_id),
        capacity=int(capacity),
        stability=int(stability),
    )


def _canonical_terms(
    inst: Instance,
    schedule: dict[int, dict[str, Any]],
    objective_id: str,
    *,
    deadline: float | None = None,
) -> FixedTimeRoomTerms:
    _check_deadline(deadline, "canonical room scoring")
    if objective_id == "itc2007_official":
        from benchmarks.itc2007 import score_itc2007_instance_schedule

        score = score_itc2007_instance_schedule(inst, schedule)
        result = FixedTimeRoomTerms(
            objective_id=objective_id,
            capacity=int(score.room_capacity),
            stability=int(score.room_stability),
        )
        _check_deadline(deadline, "canonical room scoring")
        return result
    from services.quality_service import compute_penalty_breakdown

    breakdown = compute_penalty_breakdown(inst, schedule)
    result = FixedTimeRoomTerms(
        objective_id=objective_id,
        capacity=0,
        stability=int(breakdown.get("room_consistency", 0)),
    )
    _check_deadline(deadline, "canonical room scoring")
    return result


def _default_validator(
    inst: Instance,
    schedule: dict[int, dict[str, Any]],
) -> Sequence[str]:
    from utils.specs import validate_schedule_against_instance

    return validate_schedule_against_instance(
        inst,
        schedule,
        strict_rooms=True,
        require_all_activities=True,
    )


def _copy_schedule(
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float | None = None,
) -> dict[int, dict[str, Any]]:
    copied: dict[int, dict[str, Any]] = {}
    for activity_id, row in schedule.items():
        _check_deadline(deadline, "schedule copy")
        copied[int(activity_id)] = dict(row)
    return copied


def _fixed_starts_equal(
    left: Mapping[int, Mapping[str, Any]],
    right: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float | None = None,
) -> bool:
    fields = ("week", "day", "slot", "duration")
    if set(int(value) for value in left) != set(int(value) for value in right):
        return False
    for activity_id in left:
        _check_deadline(deadline, "fixed-start verification")
        if tuple(left[int(activity_id)].get(field) for field in fields) != tuple(
            right[int(activity_id)].get(field) for field in fields
        ):
            return False
    return True


def _stability_lower_bound(
    schedule: Mapping[int, Mapping[str, Any]],
    spec: _ObjectiveSpec,
    *,
    deadline: float | None = None,
) -> int:
    by_key_period: dict[SupportKey, Counter[PeriodKey]] = defaultdict(Counter)
    for activity_id, row in schedule.items():
        _check_deadline(deadline, "stability lower bound")
        period = _period_key(row)
        for key in spec.support_keys_by_activity[int(activity_id)]:
            by_key_period[key][period] += 1
    lower_bound = 0
    for counts in by_key_period.values():
        _check_deadline(deadline, "stability lower bound")
        lower_bound += max(0, max(counts.values(), default=0) - 1)
    return int(spec.stability_weight) * int(lower_bound)


def _candidate_rooms_for_unit_activity(
    inst: Instance,
    activity_id: int,
    *,
    period: PeriodKey,
    deadline: float | None,
) -> tuple[int, ...]:
    """Deadline-aware equivalent of the canonical single-activity domain."""

    _check_deadline(deadline, "room-domain construction")
    activity = inst.activities[int(activity_id)]
    needed = int(required_capacity(inst, activity.group_ids))
    _check_deadline(deadline, "room-domain construction")
    enforce_capacity = hard_flag(inst, "enforce_room_capacity", True)
    locked = (getattr(inst, "locked_activities", {}) or {}).get(int(activity_id), {})
    locked_room = None
    if isinstance(locked, dict) and locked.get("room_id") is not None:
        locked_room = int(locked["room_id"])
    candidates: list[int] = []
    for raw_room_id, room in sorted(inst.rooms.items()):
        _check_deadline(deadline, "room-domain construction")
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
    _check_deadline(deadline, "room-domain construction")
    return tuple(candidates)


def _coordinate_descent(
    inst: Instance,
    seed_schedule: dict[int, dict[str, Any]],
    *,
    spec: _ObjectiveSpec,
    domains: Mapping[int, tuple[int, ...]],
    capacity_costs: Mapping[tuple[int, int], int],
    period_order: Sequence[PeriodKey],
    start_name: str,
    deadline: float | None,
    max_sweeps: int,
) -> _CoordinateResult:
    current = _copy_schedule(seed_schedule, deadline=deadline)
    by_period: dict[PeriodKey, tuple[int, ...]] = defaultdict(tuple)
    period_lists: dict[PeriodKey, list[int]] = defaultdict(list)
    for activity_id, row in current.items():
        _check_deadline(deadline, "coordinate period indexing")
        period_lists[_period_key(row)].append(int(activity_id))
    by_period = {
        period: tuple(sorted(activity_ids))
        for period, activity_ids in period_lists.items()
    }
    counts: dict[SupportKey, Counter[int]] = defaultdict(Counter)
    for activity_id, row in current.items():
        _check_deadline(deadline, "coordinate support indexing")
        for key in spec.support_keys_by_activity[int(activity_id)]:
            counts[key][int(row["room_id"])] += 1

    accepted_blocks = 0
    completed_sweeps = 0
    audit_certificates: tuple[MatchingCertificate, ...] = ()
    local_optimal = False
    for _sweep in range(max(1, int(max_sweeps))):
        changed = False
        sweep_certificates: list[MatchingCertificate] = []
        for period in period_order:
            _check_deadline(deadline, "coordinate sweep")
            activity_ids = by_period[period]
            touched_keys = {
                key
                for activity_id in activity_ids
                for key in spec.support_keys_by_activity[int(activity_id)]
            }
            block_counts: dict[SupportKey, Counter[int]] = defaultdict(Counter)
            for activity_id in activity_ids:
                _check_deadline(deadline, "coordinate block construction")
                room_id = int(current[activity_id]["room_id"])
                for key in spec.support_keys_by_activity[int(activity_id)]:
                    block_counts[key][room_id] += 1
            outside_rooms = {
                key: {
                    room_id
                    for room_id, count in counts[key].items()
                    if int(count) - int(block_counts[key].get(room_id, 0)) > 0
                }
                for key in touched_keys
            }
            edges: dict[int, list[tuple[int, int]]] = {}
            for activity_id in activity_ids:
                _check_deadline(deadline, "coordinate edge construction")
                edge_rows: list[tuple[int, int]] = []
                for room_id in domains[int(activity_id)]:
                    _check_deadline(deadline, "coordinate edge construction")
                    cost = int(capacity_costs[(int(activity_id), int(room_id))])
                    for key in spec.support_keys_by_activity[int(activity_id)]:
                        outside = outside_rooms[key]
                        if outside and int(room_id) not in outside:
                            cost += int(spec.stability_weight)
                    edge_rows.append((int(room_id), int(cost)))
                edges[int(activity_id)] = edge_rows
            certificate = solve_min_cost_matching(
                activity_ids,
                edges,
                period=period,
                deadline=deadline,
            )
            sweep_certificates.append(certificate)
            assignment = certificate.assignment_dict()
            current_cost = 0
            for activity_id in activity_ids:
                _check_deadline(deadline, "coordinate incumbent scoring")
                current_cost += int(
                    dict(edges[activity_id])[int(current[activity_id]["room_id"])]
                )
            if int(certificate.primal_cost) >= int(current_cost):
                continue
            for activity_id in activity_ids:
                _check_deadline(deadline, "coordinate assignment update")
                previous_room = int(current[activity_id]["room_id"])
                next_room = int(assignment[activity_id])
                if previous_room == next_room:
                    continue
                for key in spec.support_keys_by_activity[int(activity_id)]:
                    counts[key][previous_room] -= 1
                    if counts[key][previous_room] <= 0:
                        del counts[key][previous_room]
                    counts[key][next_room] += 1
                current[activity_id]["room_id"] = next_room
            changed = True
            accepted_blocks += 1
        completed_sweeps += 1
        if not changed:
            local_optimal = True
            audit_certificates = tuple(sweep_certificates)
            break
    terms = _independent_terms(inst, current, spec, deadline=deadline)
    return _CoordinateResult(
        current,
        terms,
        start_name,
        completed_sweeps,
        accepted_blocks,
        local_optimal,
        audit_certificates,
    )


def _optimize_fixed_time_rooms_impl(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float | None = None,
    max_sweeps: int = 32,
    run_reverse_start: bool = True,
    run_capacity_start: bool = False,
    validator: RoomValidator | None = None,
) -> FixedTimeRoomOracleResult:
    """Optimize rooms for an eligible fixed unit-duration timetable.

    The additive capacity relaxation is solved globally and certified per
    period.  Room stability/consistency is then optimized by exact conditional
    period matchings.  A completed no-change sweep proves one-period local
    optimality; global optimality is claimed only when the returned room cost
    meets the independently valid capacity-plus-cardinality lower bound.
    """

    started = time.perf_counter()
    eligibility_started = time.perf_counter()
    eligibility = assess_fixed_time_room_eligibility(inst, schedule, deadline=deadline)
    timing: dict[str, float | int | None] = {
        "eligibility_seconds": float(time.perf_counter() - eligibility_started),
        "matching_seconds": 0.0,
        "coordinate_seconds": 0.0,
        "validation_seconds": 0.0,
        "elapsed_seconds": 0.0,
        "deadline_overrun_seconds": 0.0,
        "deadline_supplied": deadline is not None,
        "deadline_budget_seconds": (
            None if deadline is None else float(deadline) - float(started)
        ),
        "deadline_remaining_seconds": None,
    }

    def finish(result: FixedTimeRoomOracleResult) -> FixedTimeRoomOracleResult:
        finished = time.perf_counter()
        timing["elapsed_seconds"] = float(finished - started)
        timing["deadline_overrun_seconds"] = (
            0.0
            if deadline is None
            else max(0.0, finished - float(deadline))
        )
        timing["deadline_remaining_seconds"] = (
            None
            if deadline is None
            else max(0.0, float(deadline) - finished)
        )
        result.timing = dict(timing)
        return result

    if not eligibility.eligible:
        return finish(FixedTimeRoomOracleResult("ineligible", eligibility))
    if _expired(deadline):
        return finish(FixedTimeRoomOracleResult("deadline_exhausted", eligibility))
    spec, spec_reasons = _objective_spec(inst, deadline=deadline)
    if spec is None or spec_reasons:
        updated = replace(
            eligibility,
            eligible=False,
            reasons=tuple(dict.fromkeys((*eligibility.reasons, *spec_reasons))),
        )
        return finish(FixedTimeRoomOracleResult("ineligible", updated))

    incumbent = _copy_schedule(schedule, deadline=deadline)
    incumbent_fixed_time_digest = _fixed_time_digest(incumbent, deadline=deadline)
    validation_fn = validator or _default_validator
    validation_started = time.perf_counter()
    incumbent_errors = tuple(str(value) for value in validation_fn(inst, incumbent))
    _check_deadline(deadline, "incumbent validation")
    timing["validation_seconds"] = float(time.perf_counter() - validation_started)
    if incumbent_errors:
        return finish(
            FixedTimeRoomOracleResult(
                "invalid_incumbent",
                eligibility,
                validation_attempted=True,
                validation_errors=incumbent_errors[:20],
            )
        )
    if _expired(deadline):
        return finish(
            FixedTimeRoomOracleResult(
                "deadline_exhausted",
                eligibility,
                validation_attempted=True,
            )
        )

    domains: dict[int, tuple[int, ...]] = {}
    capacity_costs: dict[tuple[int, int], int] = {}
    by_period_lists: dict[PeriodKey, list[int]] = defaultdict(list)
    domain_reasons: list[str] = []
    for activity_id, activity in sorted(inst.activities.items()):
        _check_deadline(deadline, "room-domain indexing")
        row = incumbent[int(activity_id)]
        period = _period_key(row)
        by_period_lists[period].append(int(activity_id))
        room_ids = _candidate_rooms_for_unit_activity(
            inst,
            int(activity_id),
            period=period,
            deadline=deadline,
        )
        domains[int(activity_id)] = tuple(room_ids)
        if not room_ids:
            domain_reasons.append(f"empty_room_domain:{activity_id}")
        if int(row["room_id"]) not in room_ids:
            domain_reasons.append(f"incumbent_room_outside_domain:{activity_id}")
        for room_id in room_ids:
            _check_deadline(deadline, "room capacity-cost construction")
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
    objective_digest = _objective_digest(spec)
    room_semantics_digest = _room_semantics_digest(
        periods,
        by_period,
        domains,
        capacity_costs,
    )
    if domain_reasons:
        updated = replace(
            eligibility,
            eligible=False,
            reasons=tuple(dict.fromkeys((*eligibility.reasons, *domain_reasons))),
        )
        witnesses: list[RoomOracleHallWitness] = []
        for period in periods:
            _check_deadline(deadline, "empty-domain witness construction")
            edges: dict[int, list[tuple[int, int]]] = {}
            for activity_id in by_period[period]:
                edges[int(activity_id)] = []
                for room_id in domains[activity_id]:
                    _check_deadline(deadline, "empty-domain witness construction")
                    edges[int(activity_id)].append(
                        (int(room_id), int(capacity_costs[(activity_id, room_id)]))
                    )
            if any(not values for values in edges.values()):
                witnesses.append(
                    _hall_witness(
                        period,
                        by_period[period],
                        edges,
                        deadline=deadline,
                    )
                )
        return finish(
            FixedTimeRoomOracleResult(
                "ineligible",
                updated,
                hall_witnesses=tuple(witnesses),
                validation_attempted=True,
            )
        )

    incumbent_terms = _independent_terms(inst, incumbent, spec, deadline=deadline)
    canonical_incumbent = _canonical_terms(
        inst,
        incumbent,
        spec.objective_id,
        deadline=deadline,
    )
    if incumbent_terms != canonical_incumbent:
        return finish(
            FixedTimeRoomOracleResult(
                "objective_mismatch",
                eligibility,
                incumbent_terms=incumbent_terms,
                objective_parity_checked=True,
                objective_parity=False,
                validation_attempted=True,
                error=(
                    "Independent incumbent room terms do not match the canonical scorer: "
                    f"{incumbent_terms.to_dict()} != {canonical_incumbent.to_dict()}"
                ),
            )
        )

    matching_started = time.perf_counter()
    capacity_schedule = _copy_schedule(incumbent, deadline=deadline)
    capacity_certificates: list[MatchingCertificate] = []
    hall_witnesses: list[RoomOracleHallWitness] = []
    capacity_lower_bound = 0
    try:
        for period in periods:
            _check_deadline(deadline, "capacity projection construction")
            edges: dict[int, list[tuple[int, int]]] = {}
            for activity_id in by_period[period]:
                edges[int(activity_id)] = []
                for room_id in domains[activity_id]:
                    _check_deadline(deadline, "capacity projection construction")
                    edges[int(activity_id)].append(
                        (int(room_id), int(capacity_costs[(activity_id, room_id)]))
                    )
            projection = solve_period_additive_projection(
                period,
                by_period[period],
                edges,
                deadline=deadline,
            )
            if not projection.feasible or projection.certificate is None:
                if projection.hall_witness is not None:
                    hall_witnesses.append(projection.hall_witness)
                timing["matching_seconds"] = float(time.perf_counter() - matching_started)
                return finish(
                    FixedTimeRoomOracleResult(
                        "infeasible",
                        eligibility,
                        incumbent_terms=incumbent_terms,
                        hall_witnesses=tuple(hall_witnesses),
                        objective_parity_checked=True,
                        objective_parity=True,
                        validation_attempted=True,
                    )
                )
            certificate = projection.certificate
            capacity_certificates.append(certificate)
            capacity_lower_bound += int(certificate.primal_cost)
            for activity_id, room_id in certificate.assignments:
                _check_deadline(deadline, "capacity assignment extraction")
                capacity_schedule[int(activity_id)]["room_id"] = int(room_id)
    except RoomOracleDeadline:
        timing["matching_seconds"] = float(time.perf_counter() - matching_started)
        return finish(
            FixedTimeRoomOracleResult(
                "deadline_exhausted",
                eligibility,
                incumbent_terms=incumbent_terms,
                capacity_certificates=tuple(capacity_certificates),
                objective_parity_checked=True,
                objective_parity=True,
                validation_attempted=True,
            )
        )
    except (TypeError, ValueError) as exc:
        timing["matching_seconds"] = float(time.perf_counter() - matching_started)
        return finish(
            FixedTimeRoomOracleResult(
                "certificate_failure",
                eligibility,
                incumbent_terms=incumbent_terms,
                objective_parity_checked=True,
                objective_parity=True,
                validation_attempted=True,
                error=str(exc),
            )
        )
    timing["matching_seconds"] = float(time.perf_counter() - matching_started)

    stability_lower_bound = _stability_lower_bound(
        incumbent,
        spec,
        deadline=deadline,
    )
    room_lower_bound = int(capacity_lower_bound) + int(stability_lower_bound)
    capacity_terms = _independent_terms(
        inst,
        capacity_schedule,
        spec,
        deadline=deadline,
    )
    candidates: list[_CoordinateResult] = [
        _CoordinateResult(incumbent, incumbent_terms, "incumbent", 0, 0, False, ()),
        _CoordinateResult(
            capacity_schedule,
            capacity_terms,
            "capacity_lower_bound",
            0,
            0,
            False,
            (),
        ),
    ]

    coordinate_started = time.perf_counter()
    for start_name, seed_schedule, order in (
        ("incumbent_forward", incumbent, periods),
        ("incumbent_reverse", incumbent, tuple(reversed(periods))),
        ("capacity_forward", capacity_schedule, periods),
    ):
        if start_name == "incumbent_reverse" and not run_reverse_start:
            continue
        if start_name == "capacity_forward" and not run_capacity_start:
            continue
        if _expired(deadline):
            break
        try:
            candidates.append(
                _coordinate_descent(
                    inst,
                    seed_schedule,
                    spec=spec,
                    domains=domains,
                    capacity_costs=capacity_costs,
                    period_order=order,
                    start_name=start_name,
                    deadline=deadline,
                    max_sweeps=max_sweeps,
                )
            )
        except RoomOracleDeadline:
            break
        except (MatchingInfeasible, TypeError, ValueError) as exc:
            timing["coordinate_seconds"] = float(time.perf_counter() - coordinate_started)
            return finish(
                FixedTimeRoomOracleResult(
                    "certificate_failure",
                    eligibility,
                    incumbent_terms=incumbent_terms,
                    capacity_lower_bound=int(capacity_lower_bound),
                    stability_lower_bound=int(stability_lower_bound),
                    room_lower_bound=int(room_lower_bound),
                    capacity_certificates=tuple(capacity_certificates),
                    objective_parity_checked=True,
                    objective_parity=True,
                    validation_attempted=True,
                    error=str(exc),
                )
            )
    timing["coordinate_seconds"] = float(time.perf_counter() - coordinate_started)

    ranked_candidates: list[tuple[tuple[Any, ...], _CoordinateResult]] = []
    for item in candidates:
        assignment_key: list[int] = []
        for activity_id in sorted(item.schedule):
            _check_deadline(deadline, "candidate selection")
            assignment_key.append(int(item.schedule[activity_id]["room_id"]))
        ranked_candidates.append(
            (
                (
                    int(item.terms.total),
                    0 if item.local_optimal else 1,
                    0 if item.start_name == "incumbent" else 1,
                    tuple(assignment_key),
                ),
                item,
            )
        )
    selected = min(ranked_candidates, key=lambda pair: pair[0])[1]
    global_optimal = int(selected.terms.total) == int(room_lower_bound)
    local_optimal = bool(selected.local_optimal)
    proof_status = (
        "global_optimal"
        if global_optimal
        else "one_period_local_optimal"
        if local_optimal
        else "no_proof"
    )
    improved = int(selected.terms.total) < int(incumbent_terms.total)
    fixed_starts_preserved = _fixed_starts_equal(
        incumbent,
        selected.schedule,
        deadline=deadline,
    )

    validation_started = time.perf_counter()
    if _expired(deadline):
        return finish(
            FixedTimeRoomOracleResult(
                "deadline_exhausted",
                eligibility,
                incumbent_terms=incumbent_terms,
                capacity_lower_bound=int(capacity_lower_bound),
                stability_lower_bound=int(stability_lower_bound),
                room_lower_bound=int(room_lower_bound),
                capacity_certificates=tuple(capacity_certificates),
                objective_parity_checked=True,
                objective_parity=True,
                validation_attempted=True,
            )
        )
    candidate_errors = tuple(str(value) for value in validation_fn(inst, selected.schedule))
    _check_deadline(deadline, "candidate validation")
    timing["validation_seconds"] = float(timing["validation_seconds"] or 0.0) + float(
        time.perf_counter() - validation_started
    )
    canonical_candidate = _canonical_terms(
        inst,
        selected.schedule,
        spec.objective_id,
        deadline=deadline,
    )
    parity = selected.terms == canonical_candidate
    valid = not candidate_errors and fixed_starts_preserved and parity
    if not valid:
        return finish(
            FixedTimeRoomOracleResult(
                "validation_failed" if candidate_errors or not fixed_starts_preserved else "objective_mismatch",
                eligibility,
                incumbent_terms=incumbent_terms,
                candidate_terms=selected.terms,
                capacity_lower_bound=int(capacity_lower_bound),
                stability_lower_bound=int(stability_lower_bound),
                room_lower_bound=int(room_lower_bound),
                capacity_certificates=tuple(capacity_certificates),
                local_certificates=selected.certificates,
                objective_parity_checked=True,
                objective_parity=bool(parity),
                validation_attempted=True,
                validation_errors=candidate_errors[:20],
                fixed_starts_preserved=bool(fixed_starts_preserved),
                sweeps=int(selected.sweeps),
                accepted_blocks=int(selected.accepted_blocks),
                error=(
                    None
                    if parity
                    else "Independent candidate room terms do not match the canonical scorer"
                ),
            )
        )

    _check_deadline(deadline, "final oracle acceptance")
    return finish(
        FixedTimeRoomOracleResult(
            "improved" if improved else "no_improvement",
            eligibility,
            best_schedule=selected.schedule,
            improved=bool(improved),
            incumbent_terms=incumbent_terms,
            candidate_terms=selected.terms,
            capacity_lower_bound=int(capacity_lower_bound),
            stability_lower_bound=int(stability_lower_bound),
            room_lower_bound=int(room_lower_bound),
            global_optimal=bool(global_optimal),
            one_period_local_optimal=bool(local_optimal),
            proof_status=proof_status,
            selected_start=str(selected.start_name),
            capacity_certificates=tuple(capacity_certificates),
            local_certificates=selected.certificates,
            objective_parity_checked=True,
            objective_parity=True,
            validation_attempted=True,
            validation_errors=(),
            fixed_starts_preserved=True,
            sweeps=int(selected.sweeps),
            accepted_blocks=int(selected.accepted_blocks),
            incumbent_fixed_time_digest=str(incumbent_fixed_time_digest),
            candidate_fixed_time_digest=_fixed_time_digest(
                selected.schedule,
                deadline=deadline,
            ),
            objective_digest=str(objective_digest),
            room_semantics_digest=str(room_semantics_digest),
        )
    )


def optimize_fixed_time_rooms(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float | None = None,
    max_sweeps: int = 32,
    run_reverse_start: bool = True,
    run_capacity_start: bool = False,
    validator: RoomValidator | None = None,
) -> FixedTimeRoomOracleResult:
    """Deadline-safe public wrapper around the fixed-time room oracle."""

    started = time.perf_counter()
    try:
        result = _optimize_fixed_time_rooms_impl(
            inst,
            schedule,
            deadline=deadline,
            max_sweeps=max_sweeps,
            run_reverse_start=run_reverse_start,
            run_capacity_start=run_capacity_start,
            validator=validator,
        )
        _check_deadline(deadline, "public oracle acceptance")
        return result
    except RoomOracleDeadline as exc:
        finished = time.perf_counter()
        elapsed = float(finished - started)
        eligibility = RoomOracleEligibility(
            eligible=False,
            objective_id=None,
            structural_class="unit_duration_fixed_time_injective_room_assignment",
            reasons=("deadline_exhausted",),
            activity_count=len(getattr(inst, "activities", {}) or {}),
            room_count=len(getattr(inst, "rooms", {}) or {}),
        )
        return FixedTimeRoomOracleResult(
            status="deadline_exhausted",
            eligibility=eligibility,
            best_schedule=None,
            improved=False,
            proof_status="no_proof",
            validation_attempted=False,
            timing={
                "elapsed_seconds": elapsed,
                "deadline_overrun_seconds": (
                    0.0
                    if deadline is None
                    else max(0.0, finished - float(deadline))
                ),
                "deadline_supplied": deadline is not None,
                "deadline_budget_seconds": (
                    None if deadline is None else float(deadline) - float(started)
                ),
                "deadline_remaining_seconds": (
                    None
                    if deadline is None
                    else max(0.0, float(deadline) - finished)
                ),
            },
            error=str(exc),
        )
