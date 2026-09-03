from __future__ import annotations

"""Exact aggregate room-load lower bounds for ITC-2007 CTT schedules.

The relaxation assigns each course's lecture count to rooms while retaining
the official room-capacity and room-stability costs.  It deliberately removes
period conflicts, unavailability, curricula, and minimum-working-day rules.
Consequently, its exact optimum is a valid lower bound on the complete
ITC-2007 objective.  When a hard-valid incumbent attains that bound, the
incumbent is globally optimal.
"""

import copy
import math
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from ortools.sat.python import cp_model

from benchmarks.itc2007 import ITC2007Score, score_itc2007_instance_schedule
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]

_OFFICIAL_WEIGHTS = {
    "room_capacity": 1,
    "minimum_working_days": 5,
    "curriculum_compactness": 2,
    "room_stability": 1,
}
_FINALIZATION_RESERVE_SECONDS = 0.02


@dataclass(frozen=True)
class RoomLoadEligibility:
    eligible: bool
    reasons: tuple[str, ...] = ()
    course_count: int = 0
    room_count: int = 0
    lecture_count: int = 0
    aggregate_room_slots: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class CourseRoomLoad:
    course_id: int
    course_code: str
    lecture_count: int
    room_counts: tuple[tuple[int, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_id": int(self.course_id),
            "course_code": str(self.course_code),
            "lecture_count": int(self.lecture_count),
            "room_counts": [
                [int(room_id), int(count)] for room_id, count in self.room_counts
            ],
        }


@dataclass
class RoomLoadTelemetry:
    seed: int
    model_variables: int = 0
    model_constraints: int = 0
    solver_status: str = "not_started"
    solver_wall_seconds: float = 0.0
    validation_calls: int = 0
    independent_rescores: int = 0
    certificate_replay_errors: list[str] = field(default_factory=list)
    timing: dict[str, float | bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RoomLoadCertificateResult:
    status: str
    proven: bool
    eligibility: RoomLoadEligibility
    lower_bound: int | None
    certificate_capacity_cost: int | None
    certificate_stability_cost: int | None
    certificates: tuple[CourseRoomLoad, ...]
    incumbent_score: ITC2007Score | None
    attained_global_optimum: bool
    telemetry: RoomLoadTelemetry
    validation_errors: tuple[str, ...] = ()
    deadline_exhausted: bool = False
    deadline_overrun_seconds: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "proof_status": (
                "optimal_room_load_relaxation" if self.proven else "not_proved"
            ),
            "proven": bool(self.proven),
            "eligibility": self.eligibility.to_dict(),
            "lower_bound": (
                None if self.lower_bound is None else int(self.lower_bound)
            ),
            "certificate_capacity_cost": (
                None
                if self.certificate_capacity_cost is None
                else int(self.certificate_capacity_cost)
            ),
            "certificate_stability_cost": (
                None
                if self.certificate_stability_cost is None
                else int(self.certificate_stability_cost)
            ),
            "certificates": [row.to_dict() for row in self.certificates],
            "incumbent_score": (
                None if self.incumbent_score is None else self.incumbent_score.to_dict()
            ),
            "attained_global_optimum": bool(self.attained_global_optimum),
            "telemetry": self.telemetry.to_dict(),
            "validation_errors": list(self.validation_errors),
            "deadline_exhausted": bool(self.deadline_exhausted),
            "deadline_overrun_seconds": float(self.deadline_overrun_seconds),
            "error": self.error,
        }


def _course_codes(inst: Instance) -> dict[int, str]:
    return {
        int(course_id): str(course.code) for course_id, course in inst.courses.items()
    }


def _activities_by_course(inst: Instance) -> dict[int, tuple[int, ...]]:
    rows: dict[int, list[int]] = defaultdict(list)
    for activity_id, activity in inst.activities.items():
        rows[int(activity.course_id)].append(int(activity_id))
    return {
        int(course_id): tuple(sorted(rows.get(int(course_id), [])))
        for course_id in sorted(inst.courses)
    }


def _room_slot_capacities(inst: Instance) -> dict[int, int]:
    valid_periods = {
        (str(day), int(slot))
        for day in inst.days
        for slot in range(int(inst.slots_per_day))
    }
    period_count = len(valid_periods) * len(inst.weeks)
    output: dict[int, int] = {}
    for room_id, room in inst.rooms.items():
        if room.availability is None:
            output[int(room_id)] = int(period_count)
            continue
        available = {
            (str(day), int(slot))
            for day, slot in room.availability
            if (str(day), int(slot)) in valid_periods
        }
        output[int(room_id)] = int(len(available) * len(inst.weeks))
    return output


def itc2007_room_load_eligibility(inst: Instance) -> RoomLoadEligibility:
    """Admit only instances with exact official ITC-2007 objective metadata."""

    reasons: list[str] = []
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
    if tuple(inst.weeks) != (1,):
        reasons.append("requires_single_week_one")
    if not inst.days or int(inst.slots_per_day) <= 0:
        reasons.append("invalid_period_grid")
    if not inst.courses or not inst.rooms or not inst.activities:
        reasons.append("empty_problem")
    if any(
        int(activity.week) != 1
        or int(activity.duration) != 1
        or str(activity.kind) != "LEC"
        for activity in inst.activities.values()
    ):
        reasons.append("requires_unit_itc2007_lectures")

    codes = _course_codes(inst)
    if len(codes) != len(set(codes.values())):
        reasons.append("course_codes_not_unique")
    activities = _activities_by_course(inst)
    if any(not values for values in activities.values()):
        reasons.append("course_without_activities")
    for field_name in ("course_students", "minimum_working_days", "curricula"):
        if not isinstance(metadata.get(field_name), Mapping):
            reasons.append(f"itc2007_{field_name}_missing")
    raw_students = metadata.get("course_students")
    if isinstance(raw_students, Mapping):
        try:
            students = {str(key): int(value) for key, value in raw_students.items()}
        except (TypeError, ValueError):
            reasons.append("itc2007_course_students_invalid")
        else:
            if set(students) != set(codes.values()) or any(
                value < 0 for value in students.values()
            ):
                reasons.append("itc2007_course_students_incomplete")
    if any(int(room.capacity) < 0 for room in inst.rooms.values()):
        reasons.append("room_capacity_invalid")

    room_slots = _room_slot_capacities(inst) if inst.rooms else {}
    unique_reasons = tuple(dict.fromkeys(reasons))
    return RoomLoadEligibility(
        eligible=not unique_reasons,
        reasons=unique_reasons,
        course_count=len(inst.courses),
        room_count=len(inst.rooms),
        lecture_count=len(inst.activities),
        aggregate_room_slots=sum(room_slots.values()),
    )


def _materialized_schedule(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
) -> Schedule:
    expected = {int(value) for value in inst.activities}
    actual = {int(value) for value in schedule}
    if actual != expected:
        raise ValueError("requires_complete_schedule")
    materialized: Schedule = {}
    for raw_activity_id, raw_row in schedule.items():
        activity_id = int(raw_activity_id)
        if activity_id in materialized:
            raise ValueError(f"schedule_activity_id_collision:{activity_id}")
        if not isinstance(raw_row, Mapping):
            raise ValueError(f"schedule_row_invalid:{activity_id}")
        row = copy.deepcopy(dict(raw_row))
        activity = inst.activities[activity_id]
        row.setdefault("week", int(activity.week))
        row.setdefault("duration", int(activity.duration))
        row.setdefault("staff_id", int(activity.prof_id))
        row.setdefault("course_id", int(activity.course_id))
        row.setdefault("group_ids", list(activity.group_ids))
        row.setdefault("kind", str(activity.kind))
        materialized[activity_id] = row
    return materialized


def _student_counts(inst: Instance) -> dict[int, int]:
    metadata = dict((getattr(inst, "sla_targets", {}) or {})["itc2007"])
    course_id_by_code = {
        str(course.code): int(course_id) for course_id, course in inst.courses.items()
    }
    return {
        int(course_id_by_code[str(code)]): int(count)
        for code, count in dict(metadata["course_students"]).items()
    }


def verify_itc2007_room_load_certificate(
    inst: Instance,
    certificate_rows: Sequence[Mapping[str, Any]],
    *,
    claimed_lower_bound: int,
) -> tuple[str, ...]:
    """Replay the primal aggregate assignment and its official objective."""

    errors: list[str] = []
    codes = _course_codes(inst)
    activities = _activities_by_course(inst)
    students = _student_counts(inst)
    room_slots = _room_slot_capacities(inst)
    parsed: dict[int, dict[int, int]] = {}
    for row_index, raw_row in enumerate(certificate_rows):
        if not isinstance(raw_row, Mapping):
            errors.append(f"certificate[{row_index}]:not_mapping")
            continue
        try:
            course_id = int(raw_row["course_id"])
            course_code = str(raw_row["course_code"])
            lecture_count = int(raw_row["lecture_count"])
            raw_counts = raw_row["room_counts"]
        except (KeyError, TypeError, ValueError):
            errors.append(f"certificate[{row_index}]:invalid_schema")
            continue
        if course_id in parsed:
            errors.append(f"certificate[{row_index}]:duplicate_course:{course_id}")
            continue
        if course_id not in codes:
            errors.append(f"certificate[{row_index}]:unknown_course:{course_id}")
            continue
        if course_code != codes[course_id]:
            errors.append(f"certificate[{row_index}]:course_code_mismatch")
        if lecture_count != len(activities[course_id]):
            errors.append(f"certificate[{row_index}]:lecture_count_mismatch")
        counts: dict[int, int] = {}
        if not isinstance(raw_counts, Sequence) or isinstance(raw_counts, (str, bytes)):
            errors.append(f"certificate[{row_index}]:room_counts_invalid")
            continue
        for count_index, raw_count in enumerate(raw_counts):
            try:
                room_id = int(raw_count[0])
                count = int(raw_count[1])
            except (IndexError, TypeError, ValueError):
                errors.append(
                    f"certificate[{row_index}].room_counts[{count_index}]:invalid"
                )
                continue
            if room_id in counts:
                errors.append(
                    f"certificate[{row_index}].room_counts[{count_index}]"
                    f":duplicate_room:{room_id}"
                )
                continue
            if room_id not in inst.rooms:
                errors.append(
                    f"certificate[{row_index}].room_counts[{count_index}]"
                    f":unknown_room:{room_id}"
                )
                continue
            if count <= 0:
                errors.append(
                    f"certificate[{row_index}].room_counts[{count_index}]"
                    ":count_not_positive"
                )
                continue
            counts[room_id] = count
        if sum(counts.values()) != lecture_count:
            errors.append(f"certificate[{row_index}]:room_count_total_mismatch")
        parsed[course_id] = counts

    missing = sorted(set(codes) - set(parsed))
    extra = sorted(set(parsed) - set(codes))
    if missing:
        errors.append(f"certificate:missing_courses:{missing}")
    if extra:
        errors.append(f"certificate:extra_courses:{extra}")

    loads: dict[int, int] = defaultdict(int)
    capacity_cost = 0
    stability_cost = 0
    for course_id, counts in parsed.items():
        for room_id, count in counts.items():
            loads[room_id] += count
            capacity_cost += count * max(
                0,
                int(students[course_id]) - int(inst.rooms[room_id].capacity),
            )
        stability_cost += max(0, len(counts) - 1)
    for room_id, load in sorted(loads.items()):
        if load > room_slots[room_id]:
            errors.append(
                f"certificate:room_slot_capacity_exceeded:{room_id}:{load}"
                f">{room_slots[room_id]}"
            )
    objective = int(capacity_cost + stability_cost)
    if objective != int(claimed_lower_bound):
        errors.append(
            f"certificate:objective_mismatch:{objective}!={int(claimed_lower_bound)}"
        )
    return tuple(errors)


def certify_itc2007_room_load_lower_bound(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]] | None = None,
    *,
    deadline: float,
    seed: int = 0,
    validator: Validator | None = None,
) -> RoomLoadCertificateResult:
    """Prove the exact aggregate capacity-plus-stability lower bound.

    ``deadline`` is an absolute ``time.perf_counter()`` deadline.  A lower
    bound is exposed only after CP-SAT proves optimality, the primal
    certificate replays independently, and all finalization completes before
    the caller's deadline.
    """

    started = time.perf_counter()
    telemetry = RoomLoadTelemetry(seed=int(seed))
    eligibility = itc2007_room_load_eligibility(inst)
    incumbent_score: ITC2007Score | None = None
    validation_errors: tuple[str, ...] = ()

    def finish(
        status: str,
        *,
        proven: bool = False,
        lower_bound: int | None = None,
        capacity_cost: int | None = None,
        stability_cost: int | None = None,
        certificates: Sequence[CourseRoomLoad] = (),
        attained: bool = False,
        error: str | None = None,
    ) -> RoomLoadCertificateResult:
        finished = time.perf_counter()
        overrun = max(0.0, finished - float(deadline))
        accepted_proof = bool(proven and overrun == 0.0)
        telemetry.timing = {
            "started_at_seconds": float(started),
            "absolute_deadline_seconds": float(deadline),
            "requested_budget_seconds": max(0.0, float(deadline) - started),
            "finished_at_seconds": float(finished),
            "elapsed_seconds": float(finished - started),
            "deadline_remaining_seconds": max(0.0, float(deadline) - finished),
            "deadline_overrun_seconds": float(overrun),
        }
        return RoomLoadCertificateResult(
            status=(
                str(status) if accepted_proof or not proven else "deadline_exhausted"
            ),
            proven=accepted_proof,
            eligibility=eligibility,
            lower_bound=int(lower_bound)
            if accepted_proof and lower_bound is not None
            else None,
            certificate_capacity_cost=(
                int(capacity_cost)
                if accepted_proof and capacity_cost is not None
                else None
            ),
            certificate_stability_cost=(
                int(stability_cost)
                if accepted_proof and stability_cost is not None
                else None
            ),
            certificates=tuple(certificates) if accepted_proof else (),
            incumbent_score=incumbent_score,
            attained_global_optimum=bool(accepted_proof and attained),
            telemetry=telemetry,
            validation_errors=validation_errors,
            deadline_exhausted=bool(finished >= float(deadline)),
            deadline_overrun_seconds=float(overrun),
            error=(
                error
                if accepted_proof or not proven
                else "Proof discarded because finalization crossed deadline"
            ),
        )

    try:
        if not math.isfinite(float(deadline)):
            return finish("ineligible", error="deadline_must_be_finite")
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        if not eligibility.eligible:
            return finish("ineligible")

        if schedule is not None:
            materialized = _materialized_schedule(inst, schedule)
            validation_fn = validator or (
                lambda candidate_inst, candidate_schedule: (
                    validate_schedule_against_instance(
                        candidate_inst,
                        dict(candidate_schedule),
                        strict_rooms=True,
                        require_all_activities=True,
                    )
                )
            )
            telemetry.validation_calls += 1
            validation_errors = tuple(
                str(value) for value in validation_fn(inst, materialized)
            )
            if time.perf_counter() >= float(deadline):
                return finish("deadline_exhausted")
            if validation_errors:
                return finish("invalid_incumbent")
            incumbent_score = score_itc2007_instance_schedule(inst, materialized)
            telemetry.independent_rescores += 1

        activities = _activities_by_course(inst)
        students = _student_counts(inst)
        room_slots = _room_slot_capacities(inst)
        rooms = tuple(sorted(inst.rooms))
        courses = tuple(sorted(inst.courses))
        model = cp_model.CpModel()
        counts: dict[tuple[int, int], cp_model.IntVar] = {}
        room_used: dict[tuple[int, int], cp_model.IntVar] = {}
        for course_id in courses:
            lecture_count = len(activities[course_id])
            for room_id in rooms:
                count = model.new_int_var(
                    0,
                    min(lecture_count, room_slots[room_id]),
                    f"count_{course_id}_{room_id}",
                )
                used = model.new_bool_var(f"used_{course_id}_{room_id}")
                model.add(count <= lecture_count * used)
                model.add(count >= used)
                counts[course_id, room_id] = count
                room_used[course_id, room_id] = used
            model.add(
                sum(counts[course_id, room_id] for room_id in rooms) == lecture_count
            )
        for room_id in rooms:
            model.add(
                sum(counts[course_id, room_id] for course_id in courses)
                <= room_slots[room_id]
            )

        capacity_expression = sum(
            max(
                0,
                int(students[course_id]) - int(inst.rooms[room_id].capacity),
            )
            * counts[course_id, room_id]
            for course_id in courses
            for room_id in rooms
        )
        stability_expression = sum(
            room_used[course_id, room_id] for course_id in courses for room_id in rooms
        ) - len(courses)
        model.minimize(capacity_expression + stability_expression)

        if schedule is not None:
            incumbent_counts: dict[tuple[int, int], int] = defaultdict(int)
            for activity_id, row in materialized.items():
                course_id = int(inst.activities[activity_id].course_id)
                room_id = int(row["room_id"])
                incumbent_counts[course_id, room_id] += 1
            for key, variable in counts.items():
                model.add_hint(variable, int(incumbent_counts.get(key, 0)))
            for key, variable in room_used.items():
                model.add_hint(variable, int(incumbent_counts.get(key, 0) > 0))

        telemetry.model_variables = len(model.proto.variables)
        telemetry.model_constraints = len(model.proto.constraints)
        remaining = float(deadline) - time.perf_counter()
        solve_seconds = remaining - _FINALIZATION_RESERVE_SECONDS
        if solve_seconds <= 0.0:
            return finish("deadline_exhausted")
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(solve_seconds)
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = int(seed) & 0x7FFFFFFF
        status = solver.solve(model)
        telemetry.solver_status = str(solver.status_name(status)).lower()
        telemetry.solver_wall_seconds = float(solver.wall_time)
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        if status != cp_model.OPTIMAL:
            return finish("not_proved")

        lower_bound = int(round(float(solver.objective_value)))
        best_bound = int(round(float(solver.best_objective_bound)))
        if lower_bound != best_bound:
            return finish(
                "proof_rejected",
                error=f"solver_objective_bound_mismatch:{lower_bound}!={best_bound}",
            )
        certificate_rows: list[CourseRoomLoad] = []
        capacity_cost = 0
        stability_cost = 0
        codes = _course_codes(inst)
        for course_id in courses:
            selected: list[tuple[int, int]] = []
            for room_id in rooms:
                count = int(solver.value(counts[course_id, room_id]))
                if count <= 0:
                    continue
                selected.append((int(room_id), count))
                capacity_cost += count * max(
                    0,
                    int(students[course_id]) - int(inst.rooms[room_id].capacity),
                )
            stability_cost += max(0, len(selected) - 1)
            certificate_rows.append(
                CourseRoomLoad(
                    course_id=int(course_id),
                    course_code=str(codes[course_id]),
                    lecture_count=len(activities[course_id]),
                    room_counts=tuple(selected),
                )
            )
        replay_errors = verify_itc2007_room_load_certificate(
            inst,
            [row.to_dict() for row in certificate_rows],
            claimed_lower_bound=int(lower_bound),
        )
        telemetry.certificate_replay_errors = list(replay_errors)
        if replay_errors:
            return finish(
                "proof_rejected",
                error="certificate_replay_failed",
            )
        if int(capacity_cost + stability_cost) != int(lower_bound):
            return finish(
                "proof_rejected",
                error="certificate_component_sum_mismatch",
            )
        attained = bool(
            incumbent_score is not None
            and int(incumbent_score.total) == int(lower_bound)
        )
        return finish(
            "global_optimum_certified" if attained else "lower_bound_proved",
            proven=True,
            lower_bound=int(lower_bound),
            capacity_cost=int(capacity_cost),
            stability_cost=int(stability_cost),
            certificates=certificate_rows,
            attained=attained,
        )
    except Exception as exc:
        return finish(
            "error",
            error=f"{type(exc).__name__}:{exc}",
        )
