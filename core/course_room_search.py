from __future__ import annotations

import copy
import hashlib
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from benchmarks.itc2007 import ITC2007Score, score_itc2007_instance_schedule
from core.fixed_time_room_oracle import (
    RoomOracleDeadline,
    assess_fixed_time_room_eligibility,
    solve_period_additive_projection,
)
from core.room_decomposition import candidate_rooms_for_members
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
PeriodKey = tuple[int, str, int]
Validator = Callable[[Instance, dict[int, dict[str, Any]]], Sequence[str]]
_START_FIELDS = ("week", "day", "slot", "duration")
_OFFICIAL_WEIGHTS = {
    "room_capacity": 1,
    "minimum_working_days": 5,
    "curriculum_compactness": 2,
    "room_stability": 1,
}


class CourseRoomSearchDeadline(RuntimeError):
    """Raised internally when the bounded search exhausts its deadline."""


class _CandidateValidationFailure(RuntimeError):
    def __init__(self, errors: Iterable[str]) -> None:
        self.errors = tuple(str(error) for error in errors)
        super().__init__("; ".join(self.errors[:5]))


@dataclass(frozen=True)
class CourseRoomSearchEligibility:
    eligible: bool
    reasons: tuple[str, ...] = ()
    objective_id: str | None = None
    structural_class: str = "itc2007_fixed_time_course_room_coloring"
    activity_count: int = 0
    course_count: int = 0
    room_count: int = 0
    period_count: int = 0
    domain_edges: int = 0
    courses_with_common_room: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass
class CourseRoomSearchTelemetry:
    seed: int
    courses_colored: int = 0
    period_matchings: int = 0
    chain_passes: int = 0
    chain_attempts: int = 0
    chain_paths_found: int = 0
    chain_activities_moved: int = 0
    chain_displacements: int = 0
    maximum_chain_length: int = 0
    candidates_evaluated: int = 0
    candidates_pruned_by_room_bound: int = 0
    independent_rescores: int = 0
    validation_calls: int = 0
    accepted_improvements: int = 0
    accepted_by_phase: dict[str, int] = field(default_factory=dict)
    primary_rooms: dict[int, int] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)
    timing: dict[str, float | int | bool | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": int(self.seed),
            "courses_colored": int(self.courses_colored),
            "period_matchings": int(self.period_matchings),
            "chain_passes": int(self.chain_passes),
            "chain_attempts": int(self.chain_attempts),
            "chain_paths_found": int(self.chain_paths_found),
            "chain_activities_moved": int(self.chain_activities_moved),
            "chain_displacements": int(self.chain_displacements),
            "maximum_chain_length": int(self.maximum_chain_length),
            "candidates_evaluated": int(self.candidates_evaluated),
            "candidates_pruned_by_room_bound": int(
                self.candidates_pruned_by_room_bound
            ),
            "independent_rescores": int(self.independent_rescores),
            "validation_calls": int(self.validation_calls),
            "accepted_improvements": int(self.accepted_improvements),
            "accepted_by_phase": dict(self.accepted_by_phase),
            "primary_rooms": {
                str(course_id): int(room_id)
                for course_id, room_id in sorted(self.primary_rooms.items())
            },
            "trace": list(self.trace),
            "timing": dict(self.timing),
        }


@dataclass
class CourseRoomSearchResult:
    status: str
    schedule: dict[Any, Any]
    eligibility: CourseRoomSearchEligibility
    improved: bool = False
    initial_score: ITC2007Score | None = None
    final_score: ITC2007Score | None = None
    fixed_starts_preserved: bool = True
    validation_errors: tuple[str, ...] = ()
    telemetry: CourseRoomSearchTelemetry = field(
        default_factory=lambda: CourseRoomSearchTelemetry(seed=0)
    )
    error: str | None = None

    @property
    def best_schedule(self) -> dict[Any, Any]:
        """Compatibility alias used by the other optimizer result objects."""

        return self.schedule

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "improved": bool(self.improved),
            "initial_score": (
                None if self.initial_score is None else self.initial_score.to_dict()
            ),
            "final_score": (
                None if self.final_score is None else self.final_score.to_dict()
            ),
            "improvement": (
                0
                if self.initial_score is None or self.final_score is None
                else int(self.initial_score.total - self.final_score.total)
            ),
            "fixed_starts_preserved": bool(self.fixed_starts_preserved),
            "eligibility": self.eligibility.to_dict(),
            "validation_errors": list(self.validation_errors),
            "telemetry": self.telemetry.to_dict(),
            "error": self.error,
        }


def _check_deadline(deadline: float | None, stage: str) -> None:
    if deadline is not None and time.perf_counter() >= float(deadline):
        raise CourseRoomSearchDeadline(f"Deadline exhausted during {stage}")


def _copy_schedule(schedule: Mapping[Any, Any]) -> dict[Any, Any]:
    return copy.deepcopy(dict(schedule))


def _normalized_schedule(schedule: Mapping[Any, Any]) -> Schedule:
    normalized: Schedule = {}
    for raw_activity_id, raw_row in schedule.items():
        activity_id = int(raw_activity_id)
        if activity_id in normalized:
            raise ValueError("schedule_activity_id_collision")
        if not isinstance(raw_row, Mapping):
            raise ValueError(f"schedule_row_invalid:{activity_id}")
        normalized[activity_id] = dict(raw_row)
    return normalized


def _default_validator(inst: Instance, schedule: Schedule) -> Sequence[str]:
    return validate_schedule_against_instance(
        inst,
        schedule,
        strict_rooms=True,
        require_all_activities=True,
    )


def _period(row: Mapping[str, Any]) -> PeriodKey:
    return int(row["week"]), str(row["day"]), int(row["slot"])


def _stable_rank(seed: int, namespace: str, value: object) -> int:
    digest = hashlib.sha256(
        f"{int(seed)}\0{namespace}\0{value!r}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _starts_preserved(
    incumbent: Mapping[int, Mapping[str, Any]],
    candidate: Mapping[int, Mapping[str, Any]],
) -> bool:
    if set(incumbent) != set(candidate):
        return False
    return all(
        tuple(incumbent[activity_id].get(field) for field in _START_FIELDS)
        == tuple(candidate[activity_id].get(field) for field in _START_FIELDS)
        for activity_id in incumbent
    )


def _only_rooms_changed(
    incumbent: Mapping[int, Mapping[str, Any]],
    candidate: Mapping[int, Mapping[str, Any]],
) -> bool:
    if set(incumbent) != set(candidate):
        return False
    for activity_id in incumbent:
        left = {
            key: value
            for key, value in incumbent[activity_id].items()
            if key != "room_id"
        }
        right = {
            key: value
            for key, value in candidate[activity_id].items()
            if key != "room_id"
        }
        if left != right:
            return False
    return True


def assess_course_room_search_eligibility(
    inst: Instance,
    schedule: Mapping[Any, Any],
    *,
    deadline: float | None = None,
) -> CourseRoomSearchEligibility:
    """Fail-closed structural predicate for the course-room search.

    The first implementation deliberately targets lossless ITC-2007 imports.
    This keeps candidate acceptance tied to the official four-term objective
    instead of silently applying an ITC-specific heuristic to general models.
    """

    _check_deadline(deadline, "course-room eligibility")
    reasons: list[str] = []
    if not isinstance(schedule, Mapping):
        return CourseRoomSearchEligibility(
            eligible=False,
            reasons=("schedule_not_mapping",),
            activity_count=len(getattr(inst, "activities", {}) or {}),
            course_count=len(getattr(inst, "courses", {}) or {}),
            room_count=len(getattr(inst, "rooms", {}) or {}),
        )

    try:
        base = assess_fixed_time_room_eligibility(
            inst,
            schedule,
            deadline=deadline,
        )
    except RoomOracleDeadline as exc:
        raise CourseRoomSearchDeadline(str(exc)) from exc
    reasons.extend(base.reasons)

    sla = getattr(inst, "sla_targets", {}) or {}
    metadata = sla.get("itc2007")
    if not str(sla.get("benchmark_family", "")).startswith("ITC-2007"):
        reasons.append("requires_lossless_itc2007_import")
    if base.objective_id != "itc2007_official":
        reasons.append("requires_itc2007_official_objective")
    if not isinstance(metadata, Mapping):
        reasons.append("itc2007_metadata_missing")
        metadata = {}
    if len(getattr(inst, "weeks", []) or []) != 1:
        reasons.append("requires_single_week")
    if any(str(activity.kind) != "LEC" for activity in inst.activities.values()):
        reasons.append("requires_itc2007_lecture_activities")

    course_codes = [str(course.code) for course in inst.courses.values()]
    if len(set(course_codes)) != len(course_codes):
        reasons.append("course_codes_not_unique")
    if any(
        int(activity.course_id) not in inst.courses
        for activity in inst.activities.values()
    ):
        reasons.append("activity_references_unknown_course")

    raw_weights = metadata.get("objective_weights")
    if not isinstance(raw_weights, Mapping):
        reasons.append("itc2007_objective_weights_missing")
    else:
        try:
            weights = {name: int(raw_weights[name]) for name in _OFFICIAL_WEIGHTS}
        except (KeyError, TypeError, ValueError):
            reasons.append("itc2007_objective_weights_invalid")
        else:
            if weights != _OFFICIAL_WEIGHTS:
                reasons.append("itc2007_objective_weights_nonstandard")

    for field_name in ("course_students", "minimum_working_days", "curricula"):
        if not isinstance(metadata.get(field_name), Mapping):
            reasons.append(f"itc2007_{field_name}_missing")
    raw_students = metadata.get("course_students")
    raw_minimum_days = metadata.get("minimum_working_days")
    if isinstance(raw_students, Mapping):
        missing = sorted(set(course_codes) - {str(key) for key in raw_students})
        if missing:
            reasons.append("itc2007_course_students_incomplete")
    if isinstance(raw_minimum_days, Mapping):
        missing = sorted(set(course_codes) - {str(key) for key in raw_minimum_days})
        if missing:
            reasons.append("itc2007_minimum_working_days_incomplete")

    unique_reasons = tuple(dict.fromkeys(reasons))
    return CourseRoomSearchEligibility(
        eligible=not unique_reasons,
        reasons=unique_reasons,
        objective_id=base.objective_id,
        activity_count=len(inst.activities),
        course_count=len(inst.courses),
        room_count=len(inst.rooms),
        period_count=int(base.period_count),
    )


def _room_domains(
    inst: Instance,
    schedule: Schedule,
    *,
    deadline: float | None,
) -> tuple[
    dict[int, tuple[int, ...]],
    dict[PeriodKey, tuple[int, ...]],
    tuple[str, ...],
]:
    domains: dict[int, tuple[int, ...]] = {}
    period_lists: dict[PeriodKey, list[int]] = defaultdict(list)
    reasons: list[str] = []
    for activity_id in sorted(inst.activities):
        _check_deadline(deadline, "room-domain construction")
        row = schedule[int(activity_id)]
        period = _period(row)
        activity = inst.activities[int(activity_id)]
        domain = candidate_rooms_for_members(
            inst,
            (int(activity_id),),
            week=int(period[0]),
            day=str(period[1]),
            start_slot=int(period[2]),
            duration=int(activity.duration),
        )
        _check_deadline(deadline, "room-domain construction")
        domains[int(activity_id)] = tuple(int(room_id) for room_id in domain)
        period_lists[period].append(int(activity_id))
        if not domain:
            reasons.append(f"empty_room_domain:{activity_id}")
        try:
            incumbent_room = int(row["room_id"])
        except (KeyError, TypeError, ValueError):
            reasons.append(f"incumbent_room_invalid:{activity_id}")
        else:
            if incumbent_room not in domain:
                reasons.append(f"incumbent_room_outside_domain:{activity_id}")

    by_period = {
        period: tuple(sorted(activity_ids))
        for period, activity_ids in period_lists.items()
    }
    if not reasons:
        for period, activity_ids in sorted(by_period.items()):
            _check_deadline(deadline, "room-domain matching check")
            projection = solve_period_additive_projection(
                period,
                activity_ids,
                {
                    activity_id: [(room_id, 0) for room_id in domains[activity_id]]
                    for activity_id in activity_ids
                },
                deadline=deadline,
            )
            if not projection.feasible:
                reasons.append(
                    f"room_domain_hall_deficiency:{period[0]}:{period[1]}:{period[2]}"
                )
    return domains, by_period, tuple(dict.fromkeys(reasons))


def _course_activities(inst: Instance) -> dict[int, tuple[int, ...]]:
    grouped: dict[int, list[int]] = defaultdict(list)
    for activity_id, activity in inst.activities.items():
        grouped[int(activity.course_id)].append(int(activity_id))
    return {
        course_id: tuple(sorted(activity_ids))
        for course_id, activity_ids in grouped.items()
    }


def _common_domains(
    by_course: Mapping[int, tuple[int, ...]],
    domains: Mapping[int, tuple[int, ...]],
) -> dict[int, tuple[int, ...]]:
    common: dict[int, tuple[int, ...]] = {}
    for course_id, activity_ids in by_course.items():
        if not activity_ids:
            common[int(course_id)] = ()
            continue
        intersection = set(domains[activity_ids[0]])
        for activity_id in activity_ids[1:]:
            intersection.intersection_update(domains[activity_id])
        common[int(course_id)] = tuple(sorted(int(value) for value in intersection))
    return common


def _students_and_weights(inst: Instance) -> tuple[dict[int, int], int, int]:
    metadata = dict(inst.sla_targets["itc2007"])
    raw_students = dict(metadata["course_students"])
    weights = dict(metadata["objective_weights"])
    students = {
        int(course_id): int(raw_students[str(course.code)])
        for course_id, course in inst.courses.items()
    }
    return (
        students,
        int(weights["room_capacity"]),
        int(weights["room_stability"]),
    )


def _capacity_cost(
    inst: Instance,
    activity_id: int,
    room_id: int,
    students: Mapping[int, int],
    capacity_weight: int,
) -> int:
    course_id = int(inst.activities[int(activity_id)].course_id)
    return int(capacity_weight) * max(
        0,
        int(students[course_id]) - int(inst.rooms[int(room_id)].capacity),
    )


def _course_overlap_graph(
    inst: Instance,
    schedule: Schedule,
    by_course: Mapping[int, tuple[int, ...]],
) -> dict[int, set[int]]:
    periods = {
        course_id: {_period(schedule[activity_id]) for activity_id in activity_ids}
        for course_id, activity_ids in by_course.items()
    }
    graph = {int(course_id): set() for course_id in by_course}
    course_ids = sorted(by_course)
    for index, left in enumerate(course_ids):
        for right in course_ids[index + 1 :]:
            if periods[left] & periods[right]:
                graph[left].add(int(right))
                graph[right].add(int(left))
    return graph


def _color_courses(
    inst: Instance,
    schedule: Schedule,
    by_course: Mapping[int, tuple[int, ...]],
    common_domains: Mapping[int, tuple[int, ...]],
    *,
    students: Mapping[int, int],
    capacity_weight: int,
    seed: int,
    deadline: float | None,
) -> dict[int, int]:
    graph = _course_overlap_graph(inst, schedule, by_course)
    primary: dict[int, int] = {}
    uncolored = set(int(course_id) for course_id in by_course)
    while uncolored:
        _check_deadline(deadline, "course coloring")

        def course_key(course_id: int) -> tuple[Any, ...]:
            neighbor_colors = {
                primary[neighbor]
                for neighbor in graph[course_id]
                if neighbor in primary
            }
            domain_size = len(common_domains[course_id])
            return (
                -len(neighbor_colors),
                -len(graph[course_id]),
                domain_size if domain_size else len(inst.rooms) + 1,
                -len(by_course[course_id]),
                _stable_rank(seed, "course", course_id),
                int(course_id),
            )

        course_id = min(uncolored, key=course_key)
        candidates = tuple(common_domains[course_id])
        if candidates:
            neighbor_rooms = {
                primary[neighbor]
                for neighbor in graph[course_id]
                if neighbor in primary
            }
            collision_free = tuple(
                room_id for room_id in candidates if room_id not in neighbor_rooms
            )
            considered = collision_free or candidates
            incumbent_counts = Counter(
                int(schedule[activity_id]["room_id"])
                for activity_id in by_course[course_id]
            )

            def room_key(room_id: int) -> tuple[int, int, int, int, int]:
                capacity = sum(
                    _capacity_cost(
                        inst,
                        activity_id,
                        room_id,
                        students,
                        capacity_weight,
                    )
                    for activity_id in by_course[course_id]
                )
                neighbor_collisions = sum(
                    1
                    for neighbor in graph[course_id]
                    if primary.get(neighbor) == int(room_id)
                )
                return (
                    int(capacity),
                    int(neighbor_collisions),
                    -int(incumbent_counts.get(int(room_id), 0)),
                    int(room_id),
                    _stable_rank(seed, f"primary:{course_id}", room_id),
                )

            primary[int(course_id)] = int(min(considered, key=room_key))
        uncolored.remove(int(course_id))
    return primary


def _construct_colored_schedule(
    inst: Instance,
    incumbent: Schedule,
    by_period: Mapping[PeriodKey, tuple[int, ...]],
    domains: Mapping[int, tuple[int, ...]],
    primary: Mapping[int, int],
    *,
    students: Mapping[int, int],
    capacity_weight: int,
    stability_weight: int,
    deadline: float | None,
) -> Schedule:
    candidate = _copy_schedule(incumbent)
    for period, activity_ids in sorted(by_period.items()):
        _check_deadline(deadline, "colored period matching")
        edges: dict[int, list[tuple[int, int]]] = {}
        for activity_id in activity_ids:
            course_id = int(inst.activities[activity_id].course_id)
            preferred = primary.get(course_id)
            edges[activity_id] = [
                (
                    int(room_id),
                    _capacity_cost(
                        inst,
                        activity_id,
                        int(room_id),
                        students,
                        capacity_weight,
                    )
                    + (0 if preferred == int(room_id) else int(stability_weight)),
                )
                for room_id in domains[activity_id]
            ]
        projection = solve_period_additive_projection(
            period,
            activity_ids,
            edges,
            deadline=deadline,
        )
        if not projection.feasible or projection.certificate is None:
            raise ValueError(
                f"colored_period_matching_infeasible:{period[0]}:{period[1]}:{period[2]}"
            )
        for activity_id, room_id in projection.certificate.assignments:
            candidate[int(activity_id)]["room_id"] = int(room_id)
    return candidate


def _period_occupancy(schedule: Schedule, period: PeriodKey) -> dict[int, int]:
    return {
        int(row["room_id"]): int(activity_id)
        for activity_id, row in schedule.items()
        if _period(row) == period
    }


def _preferred_rooms_for_activity(
    inst: Instance,
    schedule: Schedule,
    activity_id: int,
    domains: Mapping[int, tuple[int, ...]],
    *,
    students: Mapping[int, int],
    capacity_weight: int,
    seed: int,
) -> tuple[int, ...]:
    course_id = int(inst.activities[int(activity_id)].course_id)
    course_counts = Counter(
        int(row["room_id"])
        for other_id, row in schedule.items()
        if int(inst.activities[int(other_id)].course_id) == course_id
    )
    return tuple(
        sorted(
            domains[int(activity_id)],
            key=lambda room_id: (
                _capacity_cost(
                    inst,
                    int(activity_id),
                    int(room_id),
                    students,
                    capacity_weight,
                ),
                -int(course_counts.get(int(room_id), 0)),
                int(room_id),
                _stable_rank(seed, f"chain:{activity_id}", room_id),
            ),
        )
    )


def _find_ejection_chain(
    inst: Instance,
    schedule: Schedule,
    pivot_activity_id: int,
    target_room_id: int,
    domains: Mapping[int, tuple[int, ...]],
    *,
    students: Mapping[int, int],
    capacity_weight: int,
    seed: int,
    max_chain_length: int,
    deadline: float | None,
) -> dict[int, int] | None:
    """Find a bounded alternating room path for one fixed period.

    The final room may be empty or the pivot's original room, so this supports
    both ejection paths and cyclic swaps without ever changing a start.
    """

    pivot_activity_id = int(pivot_activity_id)
    target_room_id = int(target_room_id)
    if target_room_id not in domains[pivot_activity_id]:
        return None
    period = _period(schedule[pivot_activity_id])
    occupancy = _period_occupancy(schedule, period)
    pivot_room = int(schedule[pivot_activity_id]["room_id"])

    def visit(
        moving_activity_id: int,
        desired_room_id: int,
        assignments: dict[int, int],
        visited_rooms: set[int],
    ) -> dict[int, int] | None:
        _check_deadline(deadline, "stability ejection chain")
        if desired_room_id not in domains[moving_activity_id]:
            return None
        next_assignments = dict(assignments)
        next_assignments[int(moving_activity_id)] = int(desired_room_id)
        if len(next_assignments) > max_chain_length:
            return None
        occupant = occupancy.get(int(desired_room_id))
        if occupant is None:
            return next_assignments
        if int(occupant) == pivot_activity_id:
            return next_assignments if int(desired_room_id) == pivot_room else None
        if int(occupant) in next_assignments:
            return None

        alternatives = _preferred_rooms_for_activity(
            inst,
            schedule,
            int(occupant),
            domains,
            students=students,
            capacity_weight=capacity_weight,
            seed=seed,
        )
        for alternate_room in alternatives:
            _check_deadline(deadline, "stability ejection chain")
            if int(alternate_room) == int(desired_room_id):
                continue
            if (
                int(alternate_room) in visited_rooms
                and int(alternate_room) != pivot_room
            ):
                continue
            result = visit(
                int(occupant),
                int(alternate_room),
                next_assignments,
                {*visited_rooms, int(alternate_room)},
            )
            if result is not None:
                return result
        return None

    return visit(
        pivot_activity_id,
        target_room_id,
        {},
        {target_room_id},
    )


def _apply_room_moves(schedule: Schedule, moves: Mapping[int, int]) -> Schedule:
    candidate = _copy_schedule(schedule)
    for activity_id, room_id in moves.items():
        candidate[int(activity_id)]["room_id"] = int(room_id)
    return candidate


def _target_rooms(
    inst: Instance,
    schedule: Schedule,
    course_id: int,
    common_domain: tuple[int, ...],
    by_course: Mapping[int, tuple[int, ...]],
    *,
    students: Mapping[int, int],
    capacity_weight: int,
    seed: int,
) -> tuple[int, ...]:
    counts = Counter(
        int(schedule[activity_id]["room_id"])
        for activity_id in by_course[int(course_id)]
    )
    return tuple(
        sorted(
            common_domain,
            key=lambda room_id: (
                sum(
                    _capacity_cost(
                        inst,
                        activity_id,
                        int(room_id),
                        students,
                        capacity_weight,
                    )
                    for activity_id in by_course[int(course_id)]
                ),
                -int(counts.get(int(room_id), 0)),
                int(room_id),
                _stable_rank(seed, f"target:{course_id}", room_id),
            ),
        )
    )


def _record_trace(
    telemetry: CourseRoomSearchTelemetry,
    payload: Mapping[str, Any],
) -> None:
    if len(telemetry.trace) < 256:
        telemetry.trace.append(dict(payload))


def _fast_room_objective(inst: Instance, schedule: Schedule) -> int:
    """Exact room-only objective used solely as a safe rejection filter.

    Fixed starts make minimum-working-days and curriculum compactness constant.
    A candidate that does not improve this capacity-plus-stability value cannot
    improve the official four-term objective. Promising candidates are still
    validated and rescored by the independent canonical implementations.
    """

    students, capacity_weight, stability_weight = _students_and_weights(inst)
    capacity = sum(
        _capacity_cost(
            inst,
            int(activity_id),
            int(row["room_id"]),
            students,
            capacity_weight,
        )
        for activity_id, row in schedule.items()
    )
    rooms_by_course: dict[int, set[int]] = defaultdict(set)
    for activity_id, row in schedule.items():
        course_id = int(inst.activities[int(activity_id)].course_id)
        rooms_by_course[course_id].add(int(row["room_id"]))
    stability = int(stability_weight) * sum(
        max(0, len(room_ids) - 1) for room_ids in rooms_by_course.values()
    )
    return int(capacity) + int(stability)


def _evaluate_candidate(
    inst: Instance,
    incumbent: Schedule,
    candidate: Schedule,
    incumbent_score: ITC2007Score,
    *,
    phase: str,
    validator: Validator,
    telemetry: CourseRoomSearchTelemetry,
    deadline: float | None,
) -> tuple[bool, ITC2007Score]:
    _check_deadline(deadline, f"{phase} candidate validation")
    telemetry.candidates_evaluated += 1
    if not _only_rooms_changed(incumbent, candidate):
        raise _CandidateValidationFailure(("candidate_changed_non_room_fields",))
    if not _starts_preserved(incumbent, candidate):
        raise _CandidateValidationFailure(("candidate_changed_fixed_starts",))
    incumbent_room_objective = _fast_room_objective(inst, incumbent)
    candidate_room_objective = _fast_room_objective(inst, candidate)
    _check_deadline(deadline, f"{phase} room-bound scoring")
    if int(candidate_room_objective) >= int(incumbent_room_objective):
        telemetry.candidates_pruned_by_room_bound += 1
        _record_trace(
            telemetry,
            {
                "phase": str(phase),
                "before": int(incumbent_score.total),
                "after": None,
                "room_objective_before": int(incumbent_room_objective),
                "room_objective_after": int(candidate_room_objective),
                "delta": 0,
                "accepted": False,
                "reason": "non_improving_exact_room_bound",
            },
        )
        return False, incumbent_score
    telemetry.validation_calls += 1
    errors = tuple(str(error) for error in validator(inst, candidate))
    _check_deadline(deadline, f"{phase} candidate validation")
    if errors:
        raise _CandidateValidationFailure(errors)
    telemetry.independent_rescores += 1
    candidate_score = score_itc2007_instance_schedule(inst, candidate)
    _check_deadline(deadline, f"{phase} independent scoring")
    accepted = int(candidate_score.total) < int(incumbent_score.total)
    _record_trace(
        telemetry,
        {
            "phase": str(phase),
            "before": int(incumbent_score.total),
            "after": int(candidate_score.total),
            "delta": int(incumbent_score.total - candidate_score.total),
            "accepted": bool(accepted),
        },
    )
    if accepted:
        telemetry.accepted_improvements += 1
        telemetry.accepted_by_phase[str(phase)] = (
            int(telemetry.accepted_by_phase.get(str(phase), 0)) + 1
        )
    return accepted, candidate_score


def _run_ejection_search(
    inst: Instance,
    initial_schedule: Schedule,
    initial_score: ITC2007Score,
    by_course: Mapping[int, tuple[int, ...]],
    common_domains: Mapping[int, tuple[int, ...]],
    domains: Mapping[int, tuple[int, ...]],
    *,
    students: Mapping[int, int],
    capacity_weight: int,
    seed: int,
    max_chain_length: int,
    max_chain_attempts: int,
    max_chain_passes: int,
    validator: Validator,
    telemetry: CourseRoomSearchTelemetry,
    deadline: float | None,
) -> tuple[Schedule, ITC2007Score]:
    current = _copy_schedule(initial_schedule)
    current_score = initial_score
    ordered_courses = sorted(
        by_course,
        key=lambda course_id: (
            -len(
                {
                    int(current[activity_id]["room_id"])
                    for activity_id in by_course[course_id]
                }
            ),
            int(course_id),
            _stable_rank(seed, "chain-course", course_id),
        ),
    )

    for pass_index in range(max(0, int(max_chain_passes))):
        _check_deadline(deadline, "stability ejection pass")
        telemetry.chain_passes += 1
        accepted_this_pass = False
        for course_id in ordered_courses:
            _check_deadline(deadline, "stability ejection course")
            if telemetry.chain_attempts >= int(max_chain_attempts):
                return current, current_score
            activity_ids = by_course[int(course_id)]
            if len(activity_ids) < 2 or not common_domains[int(course_id)]:
                continue
            targets = _target_rooms(
                inst,
                current,
                int(course_id),
                common_domains[int(course_id)],
                by_course,
                students=students,
                capacity_weight=capacity_weight,
                seed=seed + pass_index,
            )
            for target_room in targets:
                _check_deadline(deadline, "stability ejection target")
                if telemetry.chain_attempts >= int(max_chain_attempts):
                    return current, current_score
                pivots = tuple(
                    activity_id
                    for activity_id in activity_ids
                    if int(current[activity_id]["room_id"]) != int(target_room)
                )
                if not pivots:
                    continue

                batch = _copy_schedule(current)
                batch_moves: dict[int, int] = {}
                batch_complete = True
                for pivot_activity_id in pivots:
                    chain = _find_ejection_chain(
                        inst,
                        batch,
                        int(pivot_activity_id),
                        int(target_room),
                        domains,
                        students=students,
                        capacity_weight=capacity_weight,
                        seed=seed + pass_index,
                        max_chain_length=max_chain_length,
                        deadline=deadline,
                    )
                    if chain is None:
                        batch_complete = False
                        break
                    telemetry.chain_paths_found += 1
                    telemetry.maximum_chain_length = max(
                        int(telemetry.maximum_chain_length), len(chain)
                    )
                    telemetry.chain_activities_moved += len(chain)
                    telemetry.chain_displacements += max(0, len(chain) - 1)
                    batch_moves.update(chain)
                    batch = _apply_room_moves(batch, chain)

                if batch_complete and batch_moves:
                    telemetry.chain_attempts += 1
                    accepted, candidate_score = _evaluate_candidate(
                        inst,
                        current,
                        batch,
                        current_score,
                        phase="course_ejection_batch",
                        validator=validator,
                        telemetry=telemetry,
                        deadline=deadline,
                    )
                    if accepted:
                        current = batch
                        current_score = candidate_score
                        accepted_this_pass = True
                        break

                for pivot_activity_id in pivots:
                    _check_deadline(deadline, "stability ejection fallback")
                    if telemetry.chain_attempts >= int(max_chain_attempts):
                        return current, current_score
                    chain = _find_ejection_chain(
                        inst,
                        current,
                        int(pivot_activity_id),
                        int(target_room),
                        domains,
                        students=students,
                        capacity_weight=capacity_weight,
                        seed=seed + pass_index,
                        max_chain_length=max_chain_length,
                        deadline=deadline,
                    )
                    if chain is None:
                        continue
                    telemetry.chain_paths_found += 1
                    telemetry.maximum_chain_length = max(
                        int(telemetry.maximum_chain_length), len(chain)
                    )
                    telemetry.chain_activities_moved += len(chain)
                    telemetry.chain_displacements += max(0, len(chain) - 1)
                    telemetry.chain_attempts += 1
                    candidate = _apply_room_moves(current, chain)
                    accepted, candidate_score = _evaluate_candidate(
                        inst,
                        current,
                        candidate,
                        current_score,
                        phase="single_ejection_chain",
                        validator=validator,
                        telemetry=telemetry,
                        deadline=deadline,
                    )
                    if accepted:
                        current = candidate
                        current_score = candidate_score
                        accepted_this_pass = True
                        break
                if accepted_this_pass:
                    break
            if accepted_this_pass:
                break
        if not accepted_this_pass:
            break
    return current, current_score


def optimize_course_rooms(
    inst: Instance,
    schedule: Mapping[Any, Any],
    *,
    deadline: float | None = None,
    seed: int = 0,
    run_constructive: bool = True,
    run_ejection_chains: bool = True,
    max_chain_length: int = 4,
    max_chain_attempts: int = 128,
    max_chain_passes: int = 8,
    validator: Validator | None = None,
) -> CourseRoomSearchResult:
    """Improve an ITC-2007 fixed-time room assignment without moving starts.

    Course-level DSATUR coloring supplies preferred rooms to exact per-period
    matchings. A bounded alternating-path search then consolidates course rooms
    by ejecting other lectures when necessary. The public boundary is
    fail-closed: invalid, late, ineligible, errored, and non-improving calls all
    return the original incumbent, never an unchecked partial candidate.
    """

    started = time.perf_counter()
    original = _copy_schedule(schedule) if isinstance(schedule, Mapping) else {}
    telemetry = CourseRoomSearchTelemetry(seed=int(seed))
    empty_eligibility = CourseRoomSearchEligibility(
        eligible=False,
        activity_count=len(getattr(inst, "activities", {}) or {}),
        course_count=len(getattr(inst, "courses", {}) or {}),
        room_count=len(getattr(inst, "rooms", {}) or {}),
    )
    active_eligibility = empty_eligibility
    initial_score: ITC2007Score | None = None

    def finish(
        status: str,
        eligibility: CourseRoomSearchEligibility,
        *,
        candidate: Schedule | None = None,
        candidate_score: ITC2007Score | None = None,
        improved: bool = False,
        validation_errors: Iterable[str] = (),
        error: str | None = None,
    ) -> CourseRoomSearchResult:
        finished = time.perf_counter()
        telemetry.timing = {
            "elapsed_seconds": float(finished - started),
            "deadline_supplied": deadline is not None,
            "deadline_budget_seconds": (
                None if deadline is None else float(deadline) - float(started)
            ),
            "deadline_remaining_seconds": (
                None
                if deadline is None
                else max(0.0, float(deadline) - float(finished))
            ),
            "deadline_overrun_seconds": (
                0.0 if deadline is None else max(0.0, float(finished) - float(deadline))
            ),
        }
        selected = candidate if improved and candidate is not None else original
        selected_score = (
            candidate_score
            if improved and candidate_score is not None
            else initial_score
        )
        return CourseRoomSearchResult(
            status=str(status),
            schedule=selected,
            eligibility=eligibility,
            improved=bool(improved),
            initial_score=initial_score,
            final_score=selected_score,
            fixed_starts_preserved=True,
            validation_errors=tuple(str(value) for value in validation_errors)[:20],
            telemetry=telemetry,
            error=error,
        )

    try:
        if int(max_chain_length) < 1:
            return finish(
                "ineligible",
                replace(
                    empty_eligibility,
                    reasons=("max_chain_length_must_be_positive",),
                ),
            )
        if int(max_chain_attempts) < 0 or int(max_chain_passes) < 0:
            return finish(
                "ineligible",
                replace(
                    empty_eligibility,
                    reasons=("chain_bounds_must_be_nonnegative",),
                ),
            )

        eligibility = assess_course_room_search_eligibility(
            inst,
            schedule,
            deadline=deadline,
        )
        active_eligibility = eligibility
        if not eligibility.eligible:
            return finish("ineligible", eligibility)
        incumbent = _normalized_schedule(schedule)
        _check_deadline(deadline, "incumbent validation")
        validation_fn = validator or _default_validator
        telemetry.validation_calls += 1
        incumbent_errors = tuple(str(error) for error in validation_fn(inst, incumbent))
        _check_deadline(deadline, "incumbent validation")
        if incumbent_errors:
            return finish(
                "invalid_incumbent",
                eligibility,
                validation_errors=incumbent_errors,
            )
        initial_score = score_itc2007_instance_schedule(inst, incumbent)
        _check_deadline(deadline, "incumbent independent scoring")

        domains, by_period, domain_reasons = _room_domains(
            inst,
            incumbent,
            deadline=deadline,
        )
        by_course = _course_activities(inst)
        common_domains = _common_domains(by_course, domains)
        eligibility = replace(
            eligibility,
            eligible=not domain_reasons,
            reasons=domain_reasons,
            domain_edges=sum(len(domain) for domain in domains.values()),
            courses_with_common_room=sum(
                1 for domain in common_domains.values() if domain
            ),
        )
        active_eligibility = eligibility
        if domain_reasons:
            return finish("ineligible", eligibility)

        students, capacity_weight, stability_weight = _students_and_weights(inst)
        current = _copy_schedule(incumbent)
        current_score = initial_score
        if run_constructive:
            primary = _color_courses(
                inst,
                incumbent,
                by_course,
                common_domains,
                students=students,
                capacity_weight=capacity_weight,
                seed=int(seed),
                deadline=deadline,
            )
            telemetry.primary_rooms = dict(primary)
            telemetry.courses_colored = len(primary)
            colored = _construct_colored_schedule(
                inst,
                incumbent,
                by_period,
                domains,
                primary,
                students=students,
                capacity_weight=capacity_weight,
                stability_weight=stability_weight,
                deadline=deadline,
            )
            telemetry.period_matchings = len(by_period)
            if colored != incumbent:
                accepted, colored_score = _evaluate_candidate(
                    inst,
                    incumbent,
                    colored,
                    current_score,
                    phase="course_coloring",
                    validator=validation_fn,
                    telemetry=telemetry,
                    deadline=deadline,
                )
                if accepted:
                    current = colored
                    current_score = colored_score

        if run_ejection_chains and int(max_chain_attempts) > 0:
            current, current_score = _run_ejection_search(
                inst,
                current,
                current_score,
                by_course,
                common_domains,
                domains,
                students=students,
                capacity_weight=capacity_weight,
                seed=int(seed),
                max_chain_length=int(max_chain_length),
                max_chain_attempts=int(max_chain_attempts),
                max_chain_passes=int(max_chain_passes),
                validator=validation_fn,
                telemetry=telemetry,
                deadline=deadline,
            )

        _check_deadline(deadline, "final acceptance")
        improved = int(current_score.total) < int(initial_score.total)
        if not improved:
            return finish("no_improvement", eligibility)
        if not _starts_preserved(incumbent, current):
            raise _CandidateValidationFailure(("final_candidate_changed_fixed_starts",))
        return finish(
            "improved",
            eligibility,
            candidate=current,
            candidate_score=current_score,
            improved=True,
        )
    except (CourseRoomSearchDeadline, RoomOracleDeadline) as exc:
        return finish(
            "deadline_exhausted",
            active_eligibility,
            error=str(exc),
        )
    except _CandidateValidationFailure as exc:
        return finish(
            "validation_failed",
            active_eligibility,
            validation_errors=exc.errors,
            error=str(exc),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return finish(
            "error",
            active_eligibility,
            error=f"{type(exc).__name__}: {exc}",
        )
