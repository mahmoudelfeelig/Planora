from __future__ import annotations

"""Bounded ITC-2007 capacity-changing course-color frontier.

This module combines established course coloring, conflict-closure, and exact
CP neighborhood-search techniques.  It is an engineering composition for the
Planora solver; it is not presented as a novel optimization algorithm.

The public optimizer is deliberately fail closed.  It only runs on lossless,
single-week ITC-2007 curriculum-timetabling imports, builds a bounded movable
course frontier around a representation-derived room-color exchange, and
returns a candidate only after independent hard validation and official
rescoring prove a strict improvement.
"""

import copy
import hashlib
import math
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from ortools.sat.python import cp_model

from benchmarks.itc2007 import ITC2007Score, score_itc2007_instance_schedule
from core.room_decomposition import candidate_rooms_for_members, eligible_rooms_for_activity
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Schedule], Sequence[str]]
_OFFICIAL_WEIGHTS = {
    "room_capacity": 1,
    "minimum_working_days": 5,
    "curriculum_compactness": 2,
    "room_stability": 1,
}


class CapacityFrontierDeadline(RuntimeError):
    """Raised internally when the absolute caller deadline is exhausted."""


@dataclass(frozen=True)
class CapacityFrontierEligibility:
    eligible: bool
    reasons: tuple[str, ...] = ()
    objective_id: str | None = None
    activity_count: int = 0
    course_count: int = 0
    room_count: int = 0
    period_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class CapacityColorExchange:
    target_course_id: int
    source_room_id: int
    target_room_id: int
    donor_course_id: int
    receiver_room_id: int
    receiver_course_id: int | None
    transfer_count: int
    predicted_capacity_gain: int
    predicted_stability_gain: int
    predicted_objective_gain: int
    target_room_load_after: int
    receiver_room_load_after: int

    def to_dict(self) -> dict[str, int | None]:
        return asdict(self)


@dataclass
class CapacityFrontierTelemetry:
    seed: int
    overcapacity_courses: int = 0
    overcapacity_lectures: int = 0
    exchanges_enumerated: int = 0
    exchanges_attempted: int = 0
    exchanges_skipped_frontier_cap: int = 0
    exchanges_skipped_domain_cap: int = 0
    exchanges_skipped_model_cap: int = 0
    models_feasible: int = 0
    validation_calls: int = 0
    independent_rescores: int = 0
    maximum_frontier_courses: int = 0
    maximum_domain_edges: int = 0
    maximum_model_variables: int = 0
    accepted_exchange: dict[str, int | None] | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)
    timing: dict[str, float | int | bool | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": int(self.seed),
            "overcapacity_courses": int(self.overcapacity_courses),
            "overcapacity_lectures": int(self.overcapacity_lectures),
            "exchanges_enumerated": int(self.exchanges_enumerated),
            "exchanges_attempted": int(self.exchanges_attempted),
            "exchanges_skipped_frontier_cap": int(
                self.exchanges_skipped_frontier_cap
            ),
            "exchanges_skipped_domain_cap": int(self.exchanges_skipped_domain_cap),
            "exchanges_skipped_model_cap": int(self.exchanges_skipped_model_cap),
            "models_feasible": int(self.models_feasible),
            "validation_calls": int(self.validation_calls),
            "independent_rescores": int(self.independent_rescores),
            "maximum_frontier_courses": int(self.maximum_frontier_courses),
            "maximum_domain_edges": int(self.maximum_domain_edges),
            "maximum_model_variables": int(self.maximum_model_variables),
            "accepted_exchange": (
                None if self.accepted_exchange is None else dict(self.accepted_exchange)
            ),
            "trace": list(self.trace),
            "timing": dict(self.timing),
        }


@dataclass
class CapacityFrontierResult:
    status: str
    schedule: dict[Any, Any]
    eligibility: CapacityFrontierEligibility
    improved: bool = False
    initial_score: ITC2007Score | None = None
    final_score: ITC2007Score | None = None
    validation_errors: tuple[str, ...] = ()
    telemetry: CapacityFrontierTelemetry = field(
        default_factory=lambda: CapacityFrontierTelemetry(seed=0)
    )
    error: str | None = None

    @property
    def best_schedule(self) -> dict[Any, Any]:
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
            "eligibility": self.eligibility.to_dict(),
            "validation_errors": list(self.validation_errors),
            "telemetry": self.telemetry.to_dict(),
            "error": self.error,
        }


@dataclass(frozen=True)
class _ProblemView:
    course_code: dict[int, str]
    course_id_by_code: dict[str, int]
    activities_by_course: dict[int, tuple[int, ...]]
    students: dict[int, int]
    minimum_days: dict[int, int]
    curricula: dict[str, tuple[int, ...]]
    conflicts: dict[int, frozenset[int]]
    unavailable_periods: dict[int, frozenset[int]]
    period_by_activity: dict[int, int]
    room_by_activity: dict[int, int]
    activities_at_period: dict[int, tuple[int, ...]]
    activity_at_period_room: dict[tuple[int, int], int]
    course_room_counts: dict[int, Counter[int]]
    room_loads: Counter[int]
    period_count: int


@dataclass(frozen=True)
class _ModelOutcome:
    status: str
    candidate: Schedule | None = None
    domain_edges: int = 0
    model_variables: int = 0
    frontier_size: int = 0
    solver_wall_seconds: float = 0.0
    error: str | None = None


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


def _check_deadline(deadline: float, stage: str) -> None:
    if time.perf_counter() >= float(deadline):
        raise CapacityFrontierDeadline(f"Deadline exhausted during {stage}")


def _default_validator(inst: Instance, schedule: Schedule) -> Sequence[str]:
    return validate_schedule_against_instance(
        inst,
        schedule,
        strict_rooms=True,
        require_all_activities=True,
    )


def _materialized_schedule(inst: Instance, schedule: Schedule) -> Schedule:
    materialized = _copy_schedule(schedule)
    for activity_id, row in materialized.items():
        activity = inst.activities[int(activity_id)]
        row.setdefault("week", int(activity.week))
        row.setdefault("duration", int(activity.duration))
        row.setdefault("staff_id", int(activity.prof_id))
        row.setdefault("course_id", int(activity.course_id))
        row.setdefault("group_ids", list(activity.group_ids))
        row.setdefault("kind", str(activity.kind))
    return materialized


def _stable_rank(seed: int, value: object) -> int:
    digest = hashlib.sha256(f"{int(seed)}\0{value!r}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _period_index(inst: Instance, row: Mapping[str, Any]) -> int:
    day_index = {str(day): index for index, day in enumerate(inst.days)}
    day = str(row["day"])
    if day not in day_index:
        raise ValueError(f"schedule_day_invalid:{day}")
    slot = int(row["slot"])
    if not 0 <= slot < int(inst.slots_per_day):
        raise ValueError(f"schedule_slot_invalid:{slot}")
    return int(day_index[day] * int(inst.slots_per_day) + slot)


def _assess_eligibility(
    inst: Instance,
    schedule: Mapping[Any, Any],
    *,
    deadline: float,
) -> CapacityFrontierEligibility:
    _check_deadline(deadline, "eligibility")
    reasons: list[str] = []
    if not isinstance(schedule, Mapping):
        reasons.append("schedule_not_mapping")
    sla = getattr(inst, "sla_targets", {}) or {}
    metadata = sla.get("itc2007")
    if not str(sla.get("benchmark_family", "")).startswith("ITC-2007"):
        reasons.append("requires_lossless_itc2007_import")
    if not isinstance(metadata, Mapping):
        reasons.append("itc2007_metadata_missing")
        metadata = {}
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
    if len(getattr(inst, "weeks", []) or []) != 1 or tuple(inst.weeks) != (1,):
        reasons.append("requires_single_week_one")
    if not inst.days or int(inst.slots_per_day) <= 0:
        reasons.append("invalid_period_grid")
    if any(
        str(activity.kind) != "LEC"
        or int(activity.duration) != 1
        or int(activity.week) != 1
        for activity in inst.activities.values()
    ):
        reasons.append("requires_unit_itc2007_lectures")
    if any(str(room.room_type) != "LECTURE" for room in inst.rooms.values()):
        reasons.append("requires_lecture_rooms")
    if getattr(inst, "locked_activities", {}) or getattr(inst, "precedence_rules", []):
        reasons.append("activity_specific_constraints_unsupported")
    if getattr(inst, "distribution_constraints", []):
        reasons.append("distribution_constraints_unsupported")
    if getattr(inst, "generic_resources", {}):
        reasons.append("generic_resources_unsupported")
    if getattr(inst, "travel_time_rules", {}) or getattr(inst, "room_closures", []):
        reasons.append("travel_or_room_closure_constraints_unsupported")
    if getattr(inst, "calendar_rules", {}) or getattr(inst, "term_blocks", []):
        reasons.append("calendar_constraints_unsupported")
    if getattr(inst, "institutional_policy", {}):
        reasons.append("institutional_policy_unsupported")

    expected_ids = set(int(value) for value in inst.activities)
    try:
        actual_ids = set(int(value) for value in schedule)
    except (TypeError, ValueError):
        actual_ids = set()
        reasons.append("schedule_activity_ids_invalid")
    if actual_ids != expected_ids:
        reasons.append("requires_complete_schedule")

    course_codes = [str(course.code) for course in inst.courses.values()]
    if len(course_codes) != len(set(course_codes)):
        reasons.append("course_codes_not_unique")
    for field_name in ("course_students", "minimum_working_days", "curricula"):
        if not isinstance(metadata.get(field_name), Mapping):
            reasons.append(f"itc2007_{field_name}_missing")
    for course_id in sorted(inst.courses):
        activity_ids = sorted(
            int(activity_id)
            for activity_id, activity in inst.activities.items()
            if int(activity.course_id) == int(course_id)
        )
        if not activity_ids:
            reasons.append(f"course_without_activities:{course_id}")
            continue
        signatures = {
            (
                int(inst.activities[activity_id].prof_id),
                tuple(sorted(int(value) for value in inst.activities[activity_id].group_ids)),
                tuple(
                    sorted(
                        (str(day), int(slot))
                        for day, slot in (
                            getattr(inst, "activity_unavailability", {}) or {}
                        ).get(activity_id, set())
                    )
                ),
            )
            for activity_id in activity_ids
        }
        if len(signatures) != 1:
            reasons.append(f"course_activities_not_exchangeable:{course_id}")

    unique_reasons = tuple(dict.fromkeys(reasons))
    return CapacityFrontierEligibility(
        eligible=not unique_reasons,
        reasons=unique_reasons,
        objective_id="itc2007_official" if not unique_reasons else None,
        activity_count=len(inst.activities),
        course_count=len(inst.courses),
        room_count=len(inst.rooms),
        period_count=len(inst.days) * int(inst.slots_per_day),
    )


def _problem_view(inst: Instance, schedule: Schedule) -> _ProblemView:
    metadata = dict((getattr(inst, "sla_targets", {}) or {})["itc2007"])
    course_code = {
        int(course_id): str(course.code) for course_id, course in inst.courses.items()
    }
    course_id_by_code = {code: course_id for course_id, code in course_code.items()}
    activities_by_course_lists: dict[int, list[int]] = defaultdict(list)
    for activity_id, activity in inst.activities.items():
        activities_by_course_lists[int(activity.course_id)].append(int(activity_id))
    activities_by_course = {
        course_id: tuple(sorted(activity_ids))
        for course_id, activity_ids in activities_by_course_lists.items()
    }
    students = {
        int(course_id_by_code[str(code)]): int(value)
        for code, value in dict(metadata["course_students"]).items()
    }
    minimum_days = {
        int(course_id_by_code[str(code)]): int(value)
        for code, value in dict(metadata["minimum_working_days"]).items()
    }
    curricula = {
        str(name): tuple(int(course_id_by_code[str(code)]) for code in members)
        for name, members in dict(metadata["curricula"]).items()
    }

    conflicts_sets: dict[int, set[int]] = {
        int(course_id): set() for course_id in inst.courses
    }
    for members in curricula.values():
        for index, first in enumerate(members):
            for second in members[index + 1 :]:
                conflicts_sets[first].add(second)
                conflicts_sets[second].add(first)
    representatives = {
        course_id: inst.activities[activity_ids[0]]
        for course_id, activity_ids in activities_by_course.items()
    }
    for first in sorted(representatives):
        first_activity = representatives[first]
        first_groups = set(int(value) for value in first_activity.group_ids)
        for second in sorted(representatives):
            if second <= first:
                continue
            second_activity = representatives[second]
            if (
                int(first_activity.prof_id) == int(second_activity.prof_id)
                or first_groups.intersection(
                    int(value) for value in second_activity.group_ids
                )
            ):
                conflicts_sets[first].add(second)
                conflicts_sets[second].add(first)
    conflicts = {
        course_id: frozenset(sorted(neighbors))
        for course_id, neighbors in conflicts_sets.items()
    }

    day_index = {str(day): index for index, day in enumerate(inst.days)}
    raw_unavailability = getattr(inst, "activity_unavailability", {}) or {}
    unavailable_periods: dict[int, frozenset[int]] = {}
    for course_id, activity_ids in activities_by_course.items():
        representative = activity_ids[0]
        unavailable_periods[course_id] = frozenset(
            day_index[str(day)] * int(inst.slots_per_day) + int(slot)
            for day, slot in raw_unavailability.get(representative, set())
        )

    period_by_activity: dict[int, int] = {}
    room_by_activity: dict[int, int] = {}
    activities_at_period_lists: dict[int, list[int]] = defaultdict(list)
    activity_at_period_room: dict[tuple[int, int], int] = {}
    course_room_counts: dict[int, Counter[int]] = {
        course_id: Counter() for course_id in inst.courses
    }
    room_loads: Counter[int] = Counter()
    for activity_id in sorted(inst.activities):
        row = schedule[activity_id]
        period = _period_index(inst, row)
        room_id = int(row["room_id"])
        course_id = int(inst.activities[activity_id].course_id)
        period_by_activity[activity_id] = period
        room_by_activity[activity_id] = room_id
        activities_at_period_lists[period].append(activity_id)
        if (period, room_id) in activity_at_period_room:
            raise ValueError(f"incumbent_room_overlap:{period}:{room_id}")
        activity_at_period_room[period, room_id] = activity_id
        course_room_counts[course_id][room_id] += 1
        room_loads[room_id] += 1
    return _ProblemView(
        course_code=course_code,
        course_id_by_code=course_id_by_code,
        activities_by_course=activities_by_course,
        students=students,
        minimum_days=minimum_days,
        curricula=curricula,
        conflicts=conflicts,
        unavailable_periods=unavailable_periods,
        period_by_activity=period_by_activity,
        room_by_activity=room_by_activity,
        activities_at_period={
            period: tuple(sorted(activity_ids))
            for period, activity_ids in activities_at_period_lists.items()
        },
        activity_at_period_room=activity_at_period_room,
        course_room_counts=course_room_counts,
        room_loads=room_loads,
        period_count=len(inst.days) * int(inst.slots_per_day),
    )


def _room_penalty(view: _ProblemView, inst: Instance, course_id: int, room_id: int) -> int:
    return max(
        0,
        int(view.students[course_id]) - int(inst.rooms[room_id].capacity),
    )


def _enumerate_exchanges(
    inst: Instance,
    view: _ProblemView,
    *,
    seed: int,
    max_exchanges: int,
    deadline: float,
) -> tuple[CapacityColorExchange, ...]:
    candidates: list[CapacityColorExchange] = []
    exclusive_courses_by_room: dict[int, list[int]] = defaultdict(list)
    for course_id, counts in view.course_room_counts.items():
        if len(counts) == 1:
            room_id = next(iter(counts))
            exclusive_courses_by_room[int(room_id)].append(int(course_id))
    for values in exclusive_courses_by_room.values():
        values.sort()

    for target_course_id in sorted(view.activities_by_course):
        _check_deadline(deadline, "exchange enumeration")
        source_counts = view.course_room_counts[target_course_id]
        support = set(source_counts)
        for source_room_id in sorted(support):
            source_penalty = _room_penalty(
                view,
                inst,
                target_course_id,
                source_room_id,
            )
            if source_penalty <= 0:
                continue
            source_count = int(source_counts[source_room_id])
            for target_room_id in sorted(inst.rooms):
                if target_room_id == source_room_id:
                    continue
                target_penalty = _room_penalty(
                    view,
                    inst,
                    target_course_id,
                    target_room_id,
                )
                per_lecture_gain = int(source_penalty - target_penalty)
                if per_lecture_gain <= 0:
                    continue
                for donor_course_id in exclusive_courses_by_room.get(
                    target_room_id,
                    [],
                ):
                    if donor_course_id == target_course_id:
                        continue
                    donor_count = len(view.activities_by_course[donor_course_id])
                    for receiver_room_id in sorted(inst.rooms):
                        if receiver_room_id == target_room_id:
                            continue
                        direct_receiver_options: tuple[int | None, ...] = (
                            None,
                            *tuple(
                                course_id
                                for course_id in exclusive_courses_by_room.get(
                                    receiver_room_id,
                                    [],
                                )
                                if course_id not in {target_course_id, donor_course_id}
                            ),
                        )
                        for receiver_course_id in direct_receiver_options:
                            receiver_count = (
                                0
                                if receiver_course_id is None
                                else len(view.activities_by_course[receiver_course_id])
                            )
                            base_target_load = int(
                                view.room_loads[target_room_id]
                                - donor_count
                                + receiver_count
                            )
                            base_receiver_load = int(
                                view.room_loads[receiver_room_id]
                                - receiver_count
                                + donor_count
                            )
                            free_target_slots = int(
                                view.period_count - base_target_load
                            )
                            if (
                                free_target_slots <= 0
                                or base_receiver_load > view.period_count
                            ):
                                continue
                            max_transfer = min(source_count, free_target_slots)
                            for transfer_count in range(1, max_transfer + 1):
                                new_support = set(support)
                                if transfer_count >= source_count:
                                    new_support.discard(source_room_id)
                                new_support.add(target_room_id)
                                stability_gain = int(
                                    max(0, len(support) - 1)
                                    - max(0, len(new_support) - 1)
                                )
                                target_capacity_gain = int(
                                    transfer_count * per_lecture_gain
                                )
                                donor_change = int(
                                    donor_count
                                    * (
                                        _room_penalty(
                                            view,
                                            inst,
                                            donor_course_id,
                                            receiver_room_id,
                                        )
                                        - _room_penalty(
                                            view,
                                            inst,
                                            donor_course_id,
                                            target_room_id,
                                        )
                                    )
                                )
                                receiver_change = 0
                                if receiver_course_id is not None:
                                    receiver_change = int(
                                        receiver_count
                                        * (
                                            _room_penalty(
                                                view,
                                                inst,
                                                receiver_course_id,
                                                target_room_id,
                                            )
                                            - _room_penalty(
                                                view,
                                                inst,
                                                receiver_course_id,
                                                receiver_room_id,
                                            )
                                        )
                                    )
                                capacity_gain = int(
                                    target_capacity_gain - donor_change - receiver_change
                                )
                                objective_gain = int(capacity_gain + stability_gain)
                                if objective_gain <= 0:
                                    continue
                                candidates.append(
                                    CapacityColorExchange(
                                        target_course_id=int(target_course_id),
                                        source_room_id=int(source_room_id),
                                        target_room_id=int(target_room_id),
                                        donor_course_id=int(donor_course_id),
                                        receiver_room_id=int(receiver_room_id),
                                        receiver_course_id=(
                                            None
                                            if receiver_course_id is None
                                            else int(receiver_course_id)
                                        ),
                                        transfer_count=int(transfer_count),
                                        predicted_capacity_gain=int(capacity_gain),
                                        predicted_stability_gain=int(stability_gain),
                                        predicted_objective_gain=int(objective_gain),
                                        target_room_load_after=int(
                                            base_target_load + transfer_count
                                        ),
                                        receiver_room_load_after=int(base_receiver_load),
                                    )
                                )

    candidates.sort(
        key=lambda exchange: (
            -int(exchange.predicted_objective_gain),
            -int(exchange.predicted_capacity_gain),
            int(exchange.target_room_load_after),
            _stable_rank(int(seed), exchange),
            int(exchange.target_course_id),
            int(exchange.donor_course_id),
            -1
            if exchange.receiver_course_id is None
            else int(exchange.receiver_course_id),
        )
    )
    return tuple(candidates[: int(max_exchanges)])


def _planned_room_domains(
    view: _ProblemView,
    exchange: CapacityColorExchange,
) -> dict[int, frozenset[int]]:
    domains = {
        course_id: frozenset(int(room_id) for room_id in counts)
        for course_id, counts in view.course_room_counts.items()
    }
    target_support = set(domains[exchange.target_course_id])
    if (
        int(exchange.transfer_count)
        >= int(view.course_room_counts[exchange.target_course_id][exchange.source_room_id])
    ):
        target_support.discard(exchange.source_room_id)
    target_support.add(exchange.target_room_id)
    domains[exchange.target_course_id] = frozenset(target_support)
    domains[exchange.donor_course_id] = frozenset((exchange.receiver_room_id,))
    if exchange.receiver_course_id is not None:
        domains[exchange.receiver_course_id] = frozenset((exchange.target_room_id,))
    return domains


def _movable_closure(
    inst: Instance,
    view: _ProblemView,
    exchange: CapacityColorExchange,
    *,
    max_frontier_courses: int,
    max_frontier_depth: int,
) -> frozenset[int] | None:
    seeds = {
        int(exchange.target_course_id),
        int(exchange.donor_course_id),
    }
    if exchange.receiver_course_id is not None:
        seeds.add(int(exchange.receiver_course_id))

    # A direct target-room insertion is blocked by the incumbent occupant at
    # the same period.  These occupants are hard dependencies.  Donor and
    # receiver courses are globally recolored and retimed, so their incumbent
    # period occupants are not dependencies of the color exchange.
    blockers: set[int] = set()
    for activity_id in view.activities_by_course[exchange.target_course_id]:
        if view.room_by_activity[activity_id] != exchange.source_room_id:
            continue
        period = view.period_by_activity[activity_id]
        blocker_id = view.activity_at_period_room.get(
            (period, exchange.target_room_id)
        )
        if blocker_id is not None:
            blockers.add(int(inst.activities[blocker_id].course_id))

    closure = set(seeds) | blockers
    if len(closure) > int(max_frontier_courses):
        return None
    frontier = set(closure)
    for _depth in range(int(max_frontier_depth)):
        next_frontier: set[int] = set()
        for course_id in sorted(frontier):
            next_frontier.update(int(value) for value in view.conflicts[course_id])
        next_frontier.difference_update(closure)
        if not next_frontier:
            break
        if len(closure) + len(next_frontier) > int(max_frontier_courses):
            return None
        closure.update(next_frontier)
        frontier = next_frontier
    return frozenset(sorted(closure))


def _fixed_component_constants(
    inst: Instance,
    view: _ProblemView,
    frontier: frozenset[int],
) -> tuple[int, int, int]:
    fixed_capacity = 0
    fixed_minimum_days = 0
    fixed_stability = 0
    for course_id in sorted(set(inst.courses) - set(frontier)):
        activity_ids = view.activities_by_course[course_id]
        fixed_capacity += sum(
            _room_penalty(view, inst, course_id, view.room_by_activity[activity_id])
            for activity_id in activity_ids
        )
        days = {
            view.period_by_activity[activity_id] // int(inst.slots_per_day)
            for activity_id in activity_ids
        }
        fixed_minimum_days += 5 * max(
            0,
            int(view.minimum_days[course_id]) - len(days),
        )
        fixed_stability += max(0, len(view.course_room_counts[course_id]) - 1)
    return int(fixed_capacity), int(fixed_minimum_days), int(fixed_stability)


def _construct_candidate(
    inst: Instance,
    incumbent: Schedule,
    view: _ProblemView,
    frontier: frozenset[int],
    selected: dict[int, list[tuple[int, int]]],
) -> Schedule:
    candidate = _copy_schedule(incumbent)
    for course_id in sorted(frontier):
        activity_ids = view.activities_by_course[course_id]
        placements = sorted(selected[course_id])
        if len(placements) != len(activity_ids):
            raise ValueError(f"candidate_lecture_count_mismatch:{course_id}")
        for activity_id, (period, room_id) in zip(
            activity_ids,
            placements,
            strict=True,
        ):
            row = dict(candidate[activity_id])
            row["week"] = 1
            row["day"] = str(inst.days[period // int(inst.slots_per_day)])
            row["slot"] = int(period % int(inst.slots_per_day))
            row["duration"] = 1
            row["room_id"] = int(room_id)
            candidate[activity_id] = row
    return candidate


def _solve_exchange_model(
    inst: Instance,
    incumbent: Schedule,
    initial_score: ITC2007Score,
    view: _ProblemView,
    exchange: CapacityColorExchange,
    frontier: frozenset[int],
    *,
    deadline: float,
    seed: int,
    max_domain_edges: int,
    max_model_variables: int,
    max_exchange_solve_seconds: float,
) -> _ModelOutcome:
    _check_deadline(deadline, "frontier model setup")
    planned_domains = _planned_room_domains(view, exchange)
    fixed_courses = set(inst.courses) - set(frontier)
    fixed_courses_at_period: dict[int, set[int]] = defaultdict(set)
    fixed_room_occupancy: set[tuple[int, int]] = set()
    for course_id in fixed_courses:
        for activity_id in view.activities_by_course[course_id]:
            period = view.period_by_activity[activity_id]
            room_id = view.room_by_activity[activity_id]
            fixed_courses_at_period[period].add(int(course_id))
            fixed_room_occupancy.add((int(period), int(room_id)))

    edges: dict[int, tuple[tuple[int, int], ...]] = {}
    domain_edges = 0
    for course_id in sorted(frontier):
        representative = view.activities_by_course[course_id][0]
        allowed_static_rooms = set(eligible_rooms_for_activity(inst, representative))
        course_edges: list[tuple[int, int]] = []
        for period in range(view.period_count):
            if period in view.unavailable_periods[course_id]:
                continue
            if any(
                fixed_course in view.conflicts[course_id]
                for fixed_course in fixed_courses_at_period.get(period, set())
            ):
                continue
            day = str(inst.days[period // int(inst.slots_per_day)])
            slot = int(period % int(inst.slots_per_day))
            exact_rooms = set(
                candidate_rooms_for_members(
                    inst,
                    (representative,),
                    week=1,
                    day=day,
                    start_slot=slot,
                    duration=1,
                )
            )
            for room_id in sorted(planned_domains[course_id]):
                if (
                    room_id not in allowed_static_rooms
                    or room_id not in exact_rooms
                    or (period, room_id) in fixed_room_occupancy
                ):
                    continue
                course_edges.append((int(period), int(room_id)))
        edges[course_id] = tuple(course_edges)
        domain_edges += len(course_edges)
        if len({period for period, _room_id in course_edges}) < len(
            view.activities_by_course[course_id]
        ):
            return _ModelOutcome(
                status="domain_infeasible",
                domain_edges=int(domain_edges),
                frontier_size=len(frontier),
            )
        if domain_edges > int(max_domain_edges):
            return _ModelOutcome(
                status="domain_cap_exceeded",
                domain_edges=int(domain_edges),
                frontier_size=len(frontier),
            )

    model = cp_model.CpModel()
    placed = {
        (course_id, period, room_id): model.new_bool_var(
            f"placed_{course_id}_{period}_{room_id}"
        )
        for course_id in sorted(frontier)
        for period, room_id in edges[course_id]
    }
    used: dict[tuple[int, int], cp_model.IntVar] = {}
    for course_id in sorted(frontier):
        by_period: dict[int, list[cp_model.IntVar]] = defaultdict(list)
        for period, room_id in edges[course_id]:
            by_period[period].append(placed[course_id, period, room_id])
        for period, values in sorted(by_period.items()):
            variable = model.new_bool_var(f"used_{course_id}_{period}")
            model.add(sum(values) == variable)
            used[course_id, period] = variable
        model.add(
            sum(variable for (candidate_course, _period), variable in used.items() if candidate_course == course_id)
            == len(view.activities_by_course[course_id])
        )

    for period in range(view.period_count):
        for room_id in sorted(inst.rooms):
            values = [
                variable
                for (course_id, candidate_period, candidate_room), variable in placed.items()
                if candidate_period == period and candidate_room == room_id
            ]
            if values:
                model.add(sum(values) <= 1)
    for first in sorted(frontier):
        for second in sorted(view.conflicts[first].intersection(frontier)):
            if second <= first:
                continue
            for period in range(view.period_count):
                first_used = used.get((first, period))
                second_used = used.get((second, period))
                if first_used is not None and second_used is not None:
                    model.add(first_used + second_used <= 1)

    current_target_count = int(
        view.course_room_counts[exchange.target_course_id][exchange.target_room_id]
    )
    target_values = [
        variable
        for (course_id, _period, room_id), variable in placed.items()
        if course_id == exchange.target_course_id
        and room_id == exchange.target_room_id
    ]
    model.add(sum(target_values) >= current_target_count + exchange.transfer_count)

    fixed_capacity, fixed_minimum_days, fixed_stability = _fixed_component_constants(
        inst,
        view,
        frontier,
    )
    capacity_terms: list[Any] = [fixed_capacity]
    for (course_id, _period, room_id), variable in placed.items():
        penalty = _room_penalty(view, inst, course_id, room_id)
        if penalty:
            capacity_terms.append(int(penalty) * variable)

    minimum_days_terms: list[Any] = [fixed_minimum_days]
    for course_id in sorted(frontier):
        day_used: list[cp_model.IntVar] = []
        for day_index in range(len(inst.days)):
            variable = model.new_bool_var(f"day_used_{course_id}_{day_index}")
            values = [
                used[course_id, day_index * int(inst.slots_per_day) + slot]
                for slot in range(int(inst.slots_per_day))
                if (course_id, day_index * int(inst.slots_per_day) + slot) in used
            ]
            if values:
                model.add_max_equality(variable, values)
            else:
                model.add(variable == 0)
            day_used.append(variable)
        shortfall = model.new_int_var(
            0,
            int(view.minimum_days[course_id]),
            f"minimum_days_shortfall_{course_id}",
        )
        model.add(shortfall >= int(view.minimum_days[course_id]) - sum(day_used))
        minimum_days_terms.append(5 * shortfall)

    stability_terms: list[Any] = [fixed_stability]
    for course_id in sorted(frontier):
        room_used: list[cp_model.IntVar] = []
        for room_id in sorted(planned_domains[course_id]):
            variable = model.new_bool_var(f"room_used_{course_id}_{room_id}")
            values = [
                placed[course_id, period, room_id]
                for period, candidate_room in edges[course_id]
                if candidate_room == room_id
            ]
            if values:
                model.add_max_equality(variable, values)
            else:
                model.add(variable == 0)
            room_used.append(variable)
        stability_terms.append(sum(room_used) - 1)

    compactness_terms: list[Any] = []
    fixed_periods_by_course: dict[int, set[int]] = {
        course_id: {
            view.period_by_activity[activity_id]
            for activity_id in view.activities_by_course[course_id]
        }
        for course_id in fixed_courses
    }
    for curriculum_name, members in sorted(view.curricula.items()):
        impacted = any(course_id in frontier for course_id in members)
        if not impacted:
            for day_index in range(len(inst.days)):
                occupied = {
                    period % int(inst.slots_per_day)
                    for course_id in members
                    for period in fixed_periods_by_course.get(course_id, set())
                    if period // int(inst.slots_per_day) == day_index
                }
                compactness_terms.append(
                    2
                    * sum(
                        1
                        for slot in occupied
                        if slot - 1 not in occupied and slot + 1 not in occupied
                    )
                )
            continue
        for day_index in range(len(inst.days)):
            occupied_expressions: list[Any] = []
            for slot in range(int(inst.slots_per_day)):
                period = day_index * int(inst.slots_per_day) + slot
                fixed_occupied = int(
                    any(
                        period in fixed_periods_by_course.get(course_id, set())
                        for course_id in members
                        if course_id in fixed_courses
                    )
                )
                movable_values = [
                    used[course_id, period]
                    for course_id in members
                    if course_id in frontier and (course_id, period) in used
                ]
                occupied_expressions.append(fixed_occupied + sum(movable_values))
            for slot, occupied in enumerate(occupied_expressions):
                isolated = model.new_bool_var(
                    f"isolated_{curriculum_name}_{day_index}_{slot}"
                )
                previous = occupied_expressions[slot - 1] if slot else 0
                following = (
                    occupied_expressions[slot + 1]
                    if slot + 1 < int(inst.slots_per_day)
                    else 0
                )
                model.add(isolated <= occupied)
                model.add(isolated + previous <= 1)
                model.add(isolated + following <= 1)
                model.add(isolated >= occupied - previous - following)
                compactness_terms.append(2 * isolated)

    objective = (
        sum(capacity_terms)
        + sum(minimum_days_terms)
        + sum(compactness_terms)
        + sum(stability_terms)
    )
    model.add(objective <= int(initial_score.total) - 1)
    model.minimize(objective)

    model_variables = len(model.proto.variables)
    if model_variables > int(max_model_variables):
        return _ModelOutcome(
            status="model_cap_exceeded",
            domain_edges=int(domain_edges),
            model_variables=int(model_variables),
            frontier_size=len(frontier),
        )

    incumbent_placements = {
        (
            int(inst.activities[activity_id].course_id),
            int(view.period_by_activity[activity_id]),
            int(view.room_by_activity[activity_id]),
        )
        for course_id in frontier
        for activity_id in view.activities_by_course[course_id]
    }
    incumbent_periods = {
        (course_id, period) for course_id, period, _room_id in incumbent_placements
    }
    for key, variable in placed.items():
        model.add_hint(variable, int(key in incumbent_placements))
    for key, variable in used.items():
        model.add_hint(variable, int(key in incumbent_periods))

    _check_deadline(deadline, "frontier model solve")
    remaining = float(deadline) - time.perf_counter()
    solve_seconds = min(float(max_exchange_solve_seconds), max(0.0, remaining - 0.01))
    if solve_seconds <= 0.0:
        raise CapacityFrontierDeadline("Deadline exhausted before frontier model solve")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(solve_seconds)
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = int(seed) & 0x7FFFFFFF
    solver.parameters.stop_after_first_solution = True
    status = solver.solve(model)
    if time.perf_counter() >= float(deadline):
        raise CapacityFrontierDeadline("Deadline exhausted after frontier model solve")
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return _ModelOutcome(
            status=str(solver.status_name(status)).lower(),
            domain_edges=int(domain_edges),
            model_variables=int(model_variables),
            frontier_size=len(frontier),
            solver_wall_seconds=float(solver.wall_time),
        )

    selected: dict[int, list[tuple[int, int]]] = {
        course_id: [] for course_id in frontier
    }
    for (course_id, period, room_id), variable in placed.items():
        if solver.value(variable):
            selected[course_id].append((int(period), int(room_id)))
    candidate = _construct_candidate(inst, incumbent, view, frontier, selected)
    return _ModelOutcome(
        status="feasible",
        candidate=candidate,
        domain_edges=int(domain_edges),
        model_variables=int(model_variables),
        frontier_size=len(frontier),
        solver_wall_seconds=float(solver.wall_time),
    )


def optimize_itc2007_capacity_frontier(
    inst: Instance,
    incumbent: Mapping[Any, Any],
    *,
    deadline: float,
    seed: int = 0,
    max_exchanges: int = 8,
    max_frontier_courses: int = 16,
    max_frontier_depth: int = 1,
    max_domain_edges: int = 2_000,
    max_model_variables: int = 2_500,
    max_exchange_solve_seconds: float = 1.0,
    validator: Validator | None = None,
) -> CapacityFrontierResult:
    """Search a bounded exact capacity-changing course-color frontier.

    ``deadline`` is an absolute ``time.perf_counter()`` deadline.  All bounds
    are enforced before candidate acceptance, and every non-improving,
    invalid, oversized, timed-out, or exceptional path returns the untouched
    incumbent.
    """

    started = time.perf_counter()
    original = _copy_schedule(incumbent)
    telemetry = CapacityFrontierTelemetry(seed=int(seed))
    empty_eligibility = CapacityFrontierEligibility(
        eligible=False,
        reasons=("not_assessed",),
        activity_count=len(getattr(inst, "activities", {}) or {}),
        course_count=len(getattr(inst, "courses", {}) or {}),
        room_count=len(getattr(inst, "rooms", {}) or {}),
    )
    active_eligibility = empty_eligibility
    initial_score: ITC2007Score | None = None

    def finish(
        status: str,
        *,
        schedule: Mapping[Any, Any] | None = None,
        improved: bool = False,
        final_score: ITC2007Score | None = None,
        validation_errors: Sequence[str] = (),
        error: str | None = None,
    ) -> CapacityFrontierResult:
        selected = original if schedule is None else _copy_schedule(schedule)
        finished = time.perf_counter()
        deadline_overrun = max(0.0, finished - float(deadline))
        if improved and deadline_overrun > 0.0:
            status = "deadline_exhausted"
            selected = original
            improved = False
            final_score = initial_score
            error = "Candidate discarded because result finalization crossed deadline"
        telemetry.timing = {
            "elapsed_seconds": float(finished - started),
            "deadline_remaining_seconds": max(0.0, float(deadline) - finished),
            "deadline_overrun_seconds": float(deadline_overrun),
            "deadline_exhausted": bool(finished >= float(deadline)),
        }
        return CapacityFrontierResult(
            status=str(status),
            schedule=selected,
            eligibility=active_eligibility,
            improved=bool(improved),
            initial_score=initial_score,
            final_score=(initial_score if final_score is None else final_score),
            validation_errors=tuple(str(value) for value in validation_errors)[:20],
            telemetry=telemetry,
            error=error,
        )

    try:
        numeric_bounds = {
            "max_exchanges": int(max_exchanges),
            "max_frontier_courses": int(max_frontier_courses),
            "max_frontier_depth": int(max_frontier_depth),
            "max_domain_edges": int(max_domain_edges),
            "max_model_variables": int(max_model_variables),
        }
        invalid_bounds = [
            name
            for name, value in numeric_bounds.items()
            if value < (0 if name == "max_frontier_depth" else 1)
        ]
        if invalid_bounds or not math.isfinite(float(max_exchange_solve_seconds)) or float(
            max_exchange_solve_seconds
        ) <= 0.0:
            active_eligibility = replace(
                empty_eligibility,
                reasons=("invalid_search_bounds",),
            )
            return finish("ineligible")
        if not math.isfinite(float(deadline)):
            active_eligibility = replace(
                empty_eligibility,
                reasons=("deadline_must_be_finite",),
            )
            return finish("ineligible")
        _check_deadline(float(deadline), "entry")
        eligibility = _assess_eligibility(
            inst,
            incumbent,
            deadline=float(deadline),
        )
        active_eligibility = eligibility
        if not eligibility.eligible:
            return finish("ineligible")
        schedule = _materialized_schedule(inst, _normalized_schedule(incumbent))
        validation_fn = validator or _default_validator
        telemetry.validation_calls += 1
        incumbent_errors = tuple(
            str(error) for error in validation_fn(inst, schedule)
        )
        _check_deadline(float(deadline), "incumbent validation")
        if incumbent_errors:
            return finish(
                "invalid_incumbent",
                validation_errors=incumbent_errors,
            )
        initial_score = score_itc2007_instance_schedule(inst, schedule)
        telemetry.independent_rescores += 1
        _check_deadline(float(deadline), "incumbent official scoring")
        view = _problem_view(inst, schedule)
        telemetry.overcapacity_courses = sum(
            1
            for course_id, activity_ids in view.activities_by_course.items()
            if any(
                _room_penalty(
                    view,
                    inst,
                    course_id,
                    view.room_by_activity[activity_id],
                )
                > 0
                for activity_id in activity_ids
            )
        )
        telemetry.overcapacity_lectures = sum(
            1
            for course_id, activity_ids in view.activities_by_course.items()
            for activity_id in activity_ids
            if _room_penalty(
                view,
                inst,
                course_id,
                view.room_by_activity[activity_id],
            )
            > 0
        )
        if telemetry.overcapacity_lectures == 0:
            return finish("no_candidates")
        exchanges = _enumerate_exchanges(
            inst,
            view,
            seed=int(seed),
            max_exchanges=int(max_exchanges),
            deadline=float(deadline),
        )
        telemetry.exchanges_enumerated = len(exchanges)
        if not exchanges:
            return finish("no_candidates")

        for exchange_index, exchange in enumerate(exchanges):
            _check_deadline(float(deadline), "exchange frontier")
            frontier = _movable_closure(
                inst,
                view,
                exchange,
                max_frontier_courses=int(max_frontier_courses),
                max_frontier_depth=int(max_frontier_depth),
            )
            if frontier is None:
                telemetry.exchanges_skipped_frontier_cap += 1
                telemetry.trace.append(
                    {
                        "exchange_index": int(exchange_index),
                        "status": "frontier_cap_exceeded",
                        "exchange": exchange.to_dict(),
                    }
                )
                continue
            telemetry.exchanges_attempted += 1
            outcome = _solve_exchange_model(
                inst,
                schedule,
                initial_score,
                view,
                exchange,
                frontier,
                deadline=float(deadline),
                seed=int(seed) + exchange_index * 65_537,
                max_domain_edges=int(max_domain_edges),
                max_model_variables=int(max_model_variables),
                max_exchange_solve_seconds=float(max_exchange_solve_seconds),
            )
            telemetry.maximum_frontier_courses = max(
                telemetry.maximum_frontier_courses,
                int(outcome.frontier_size),
            )
            telemetry.maximum_domain_edges = max(
                telemetry.maximum_domain_edges,
                int(outcome.domain_edges),
            )
            telemetry.maximum_model_variables = max(
                telemetry.maximum_model_variables,
                int(outcome.model_variables),
            )
            if outcome.status == "domain_cap_exceeded":
                telemetry.exchanges_skipped_domain_cap += 1
            if outcome.status == "model_cap_exceeded":
                telemetry.exchanges_skipped_model_cap += 1
            trace_row = {
                "exchange_index": int(exchange_index),
                "status": str(outcome.status),
                "exchange": exchange.to_dict(),
                "frontier_courses": int(outcome.frontier_size),
                "domain_edges": int(outcome.domain_edges),
                "model_variables": int(outcome.model_variables),
                "solver_wall_seconds": float(outcome.solver_wall_seconds),
            }
            telemetry.trace.append(trace_row)
            if outcome.candidate is None:
                continue
            telemetry.models_feasible += 1
            _check_deadline(float(deadline), "candidate validation")
            telemetry.validation_calls += 1
            candidate_errors = tuple(
                str(error) for error in validation_fn(inst, outcome.candidate)
            )
            _check_deadline(float(deadline), "candidate validation")
            if candidate_errors:
                trace_row["status"] = "candidate_invalid"
                trace_row["validation_errors"] = list(candidate_errors[:5])
                continue
            candidate_score = score_itc2007_instance_schedule(
                inst,
                outcome.candidate,
            )
            telemetry.independent_rescores += 1
            _check_deadline(float(deadline), "candidate official scoring")
            if int(candidate_score.total) >= int(initial_score.total):
                trace_row["status"] = "candidate_not_strictly_better"
                trace_row["candidate_score"] = candidate_score.to_dict()
                continue
            trace_row["status"] = "accepted"
            trace_row["candidate_score"] = candidate_score.to_dict()
            telemetry.accepted_exchange = exchange.to_dict()
            return finish(
                "improved",
                schedule=outcome.candidate,
                improved=True,
                final_score=candidate_score,
            )
        return finish("no_improvement")
    except CapacityFrontierDeadline as exc:
        return finish("deadline_exhausted", error=str(exc))
    except (KeyError, TypeError, ValueError) as exc:
        return finish("error", error=f"{type(exc).__name__}: {exc}")


__all__ = [
    "CapacityColorExchange",
    "CapacityFrontierEligibility",
    "CapacityFrontierResult",
    "CapacityFrontierTelemetry",
    "optimize_itc2007_capacity_frontier",
]
