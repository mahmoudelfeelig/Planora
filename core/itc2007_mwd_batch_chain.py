from __future__ import annotations

"""Deterministic batch repair for minimum-working-days basins.

The neighborhood is derived only from the incumbent representation.  Each
round selects the three highest-leverage MWD-deficient roots, expands them by
one conflict-graph hop, and solves their time placements jointly while fixed
rooms protect a feasible completion.  A deterministic room-ejection descent
then consumes the residual slice.  Every hand-off is independently validated
and rescored under one absolute deadline; late, mutating, invalid, and
non-improving candidates fail closed.
"""

import copy
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from ortools.sat.python import cp_model

from benchmarks.itc2007 import (
    ITC2007Score,
    canonicalize_itc2007_schedule,
    score_itc2007_instance_schedule,
)
from core.itc2007_stability_ejection import _State
from core.itc2007_rooted_adjacency import itc2007_rooted_adjacency_eligibility
from core.projected_time_search import (
    _course_room_ejection_descent,
)
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]

ROUND_COUNT = 2
ROOTS_PER_ROUND = 3
CONFLICT_CLOSURE_DEPTH = 1
ROUND_MAX_SECONDS = (1.05, 1.05)
ROUND_INTERNAL_RESERVE_SECONDS = 0.04
FINAL_ROOM_RESERVE_SECONDS = 0.06
FINAL_COMPLETION_RESERVE_SECONDS = 0.06
CP_SEEDS = (17, 18)


@dataclass
class MWDBatchChainTelemetry:
    seed: int
    stages: list[dict[str, Any]] = field(default_factory=list)
    component_trajectory: list[dict[str, Any]] = field(default_factory=list)
    validation_calls: int = 0
    independent_rescores: int = 0
    timing: dict[str, float | bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MWDBatchChainResult:
    status: str
    schedule: Schedule
    improved: bool
    initial_score: ITC2007Score | None
    final_score: ITC2007Score | None
    telemetry: MWDBatchChainTelemetry
    validation_errors: tuple[str, ...] = ()
    eligibility_reasons: tuple[str, ...] = ()
    deadline_exhausted: bool = False
    deadline_overrun_seconds: float = 0.0
    error: str | None = None

    @property
    def best_schedule(self) -> Schedule:
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
                else max(0, int(self.initial_score.total - self.final_score.total))
            ),
            "telemetry": self.telemetry.to_dict(),
            "validation_errors": list(self.validation_errors),
            "eligibility_reasons": list(self.eligibility_reasons),
            "deadline_exhausted": bool(self.deadline_exhausted),
            "deadline_overrun_seconds": float(self.deadline_overrun_seconds),
            "error": self.error,
        }


class _FailClosed(RuntimeError):
    def __init__(
        self,
        status: str,
        *,
        error: str | None = None,
        validation_errors: Sequence[str] = (),
    ) -> None:
        super().__init__(error or status)
        self.status = str(status)
        self.error = error
        self.validation_errors = tuple(str(value) for value in validation_errors)


def _copy_schedule(schedule: Mapping[int, Mapping[str, Any]]) -> Schedule:
    return {
        int(activity_id): copy.deepcopy(dict(row))
        for activity_id, row in schedule.items()
    }


def _default_validator(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
) -> Sequence[str]:
    return validate_schedule_against_instance(
        inst,
        dict(schedule),
        strict_rooms=True,
        require_all_activities=True,
    )


def _score_is_self_consistent(score: ITC2007Score) -> bool:
    return int(score.total) == int(
        score.room_capacity
        + score.minimum_working_days
        + score.curriculum_compactness
        + score.room_stability
    )


def _select_round_roots(state: _State) -> tuple[str, ...]:
    deficient = (
        course
        for course in state.activities_by_course
        if state._course_mwd_term(course) > 0
    )
    return tuple(
        sorted(
            deficient,
            key=lambda course: (
                -int(state._course_mwd_term(course)),
                sum(
                    len(state.activities_by_course[value])
                    for value in {course, *state.conflict_neighbors[course]}
                ),
                str(course),
            ),
        )[:ROOTS_PER_ROUND]
    )


def _round_model(
    inst: Instance,
    incumbent: Schedule,
    *,
    deadline: float,
    cp_seed: int,
) -> tuple[Schedule, dict[str, Any]]:
    started = time.perf_counter()
    state = _State(inst, incumbent)
    roots = _select_round_roots(state)
    if not roots:
        return _copy_schedule(incumbent), {
            "status": "no_mwd_deficits",
            "accepted": False,
            "roots": [],
            "elapsed_seconds": float(time.perf_counter() - started),
        }

    selected_course_set = set(roots)
    for _ in range(CONFLICT_CLOSURE_DEPTH):
        selected_course_set.update(
            neighbor
            for course in tuple(selected_course_set)
            for neighbor in state.conflict_neighbors[course]
        )
    selected_courses = tuple(sorted(selected_course_set))
    selected_activities = tuple(
        sorted(
            activity_id
            for course in selected_courses
            for activity_id in state.activities_by_course[course]
        )
    )
    selected_activity_set = set(selected_activities)
    slots_per_day = int(state.slots_per_day)

    model = cp_model.CpModel()
    x: dict[tuple[int, int], cp_model.IntVar] = {}
    for activity_id in selected_activities:
        current_period = int(state.base_period[activity_id])
        outside_conflict_periods = {
            int(state.base_period[outside_id])
            for outside_course in state.conflict_neighbors[
                state.course_code[activity_id]
            ]
            if outside_course not in selected_course_set
            for outside_id in state.activities_by_course[outside_course]
        }
        outside_room_periods = {
            int(state.base_period[outside_id])
            for outside_id in state.activity_ids
            if outside_id not in selected_activity_set
            and int(state.base_room[outside_id]) == int(state.base_room[activity_id])
        }
        allowed = tuple(
            period
            for period in range(state.period_count)
            if period not in state.forbidden[activity_id]
            and period not in outside_conflict_periods
            and period not in outside_room_periods
        )
        if current_period not in allowed:
            raise _FailClosed(
                "error",
                error=f"incumbent_period_excluded:{activity_id}",
            )
        for period in allowed:
            x[activity_id, period] = model.NewBoolVar(f"x_{activity_id}_{period}")
        model.Add(sum(x[activity_id, period] for period in allowed) == 1)
        model.AddHint(x[activity_id, current_period], 1)

    for course in selected_courses:
        for period in range(state.period_count):
            literals = [
                x[activity_id, period]
                for activity_id in state.activities_by_course[course]
                if (activity_id, period) in x
            ]
            if literals:
                model.Add(sum(literals) <= 1)
    for left_index, left in enumerate(selected_courses):
        for right in selected_courses[left_index + 1 :]:
            if right not in state.conflict_neighbors[left]:
                continue
            for period in range(state.period_count):
                literals = [
                    x[activity_id, period]
                    for activity_id in (
                        *state.activities_by_course[left],
                        *state.activities_by_course[right],
                    )
                    if (activity_id, period) in x
                ]
                if literals:
                    model.Add(sum(literals) <= 1)

    selected_by_room: dict[int, list[int]] = defaultdict(list)
    for activity_id in selected_activities:
        selected_by_room[int(state.base_room[activity_id])].append(activity_id)
    for activity_ids in selected_by_room.values():
        for period in range(state.period_count):
            literals = [
                x[activity_id, period]
                for activity_id in activity_ids
                if (activity_id, period) in x
            ]
            if literals:
                model.Add(sum(literals) <= 1)

    objective_terms: list[cp_model.LinearExpr] = []
    for course in selected_courses:
        activity_ids = state.activities_by_course[course]
        day_used: list[cp_model.IntVar] = []
        for day in range(len(state.days)):
            used = model.NewBoolVar(f"day_{course}_{day}")
            literals = [
                x[activity_id, period]
                for activity_id in activity_ids
                for period in range(
                    day * slots_per_day,
                    (day + 1) * slots_per_day,
                )
                if (activity_id, period) in x
            ]
            model.Add(sum(literals) >= used)
            model.Add(sum(literals) <= len(activity_ids) * used)
            day_used.append(used)
        deficit = model.NewIntVar(
            0,
            int(state.minimum_days[course]),
            f"mwd_{course}",
        )
        model.Add(deficit >= int(state.minimum_days[course]) - sum(day_used))
        objective_terms.append(5 * deficit)

    for curriculum, members in sorted(state.curricula.items()):
        selected_members = selected_course_set.intersection(members)
        if not selected_members:
            continue
        outside_presence = {
            int(state.base_period[activity_id])
            for course in members
            if course not in selected_course_set
            for activity_id in state.activities_by_course[course]
        }
        presence: list[int | cp_model.IntVar] = []
        for period in range(state.period_count):
            if period in outside_presence:
                presence.append(1)
                continue
            literals = [
                x[activity_id, period]
                for course in selected_members
                for activity_id in state.activities_by_course[course]
                if (activity_id, period) in x
            ]
            if not literals:
                presence.append(0)
                continue
            used = model.NewBoolVar(f"present_{curriculum}_{period}")
            model.Add(used == sum(literals))
            presence.append(used)
        for period, here in enumerate(presence):
            if isinstance(here, int) and here == 0:
                continue
            slot = period % slots_per_day
            previous = 0 if slot == 0 else presence[period - 1]
            following = 0 if slot + 1 == slots_per_day else presence[period + 1]
            isolated = model.NewBoolVar(f"isolated_{curriculum}_{period}")
            model.Add(isolated <= here)
            model.Add(isolated + previous <= 1)
            model.Add(isolated + following <= 1)
            model.Add(isolated >= here - previous - following)
            objective_terms.append(2 * isolated)

    objective = sum(objective_terms)
    affected_curricula = {
        curriculum
        for curriculum, members in state.curricula.items()
        if selected_course_set.intersection(members)
    }
    incumbent_modeled = sum(
        int(state._course_mwd_term(course)) for course in selected_courses
    )
    for curriculum in affected_curricula:
        occupied = {
            int(state.base_period[activity_id])
            for course in state.curricula[curriculum]
            for activity_id in state.activities_by_course[course]
        }
        for period in occupied:
            slot = period % slots_per_day
            if (slot == 0 or period - 1 not in occupied) and (
                slot + 1 == slots_per_day or period + 1 not in occupied
            ):
                incumbent_modeled += 2
    model.Add(objective <= int(incumbent_modeled) - 1)
    model.Minimize(objective)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(
        0.01,
        float(deadline) - time.perf_counter() - ROUND_INTERNAL_RESERVE_SECONDS,
    )
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = int(cp_seed)
    solver.parameters.cp_model_presolve = True
    solver.parameters.linearization_level = 2
    status = solver.Solve(model)
    candidate = _copy_schedule(incumbent)
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        for activity_id in selected_activities:
            assigned = next(
                period
                for (candidate_activity, period), literal in x.items()
                if candidate_activity == activity_id and solver.Value(literal)
            )
            candidate[activity_id]["day"] = str(state.days[assigned // slots_per_day])
            candidate[activity_id]["slot"] = int(assigned % slots_per_day)

    return candidate, {
        "status": solver.StatusName(status),
        "roots": list(roots),
        "selected_course_count": len(selected_courses),
        "selected_activity_count": len(selected_activities),
        "incumbent_modeled_objective": int(incumbent_modeled),
        "model_objective": (
            float(solver.ObjectiveValue())
            if status in (cp_model.FEASIBLE, cp_model.OPTIMAL)
            else None
        ),
        "model_bound": (
            float(solver.BestObjectiveBound())
            if status in (cp_model.FEASIBLE, cp_model.OPTIMAL)
            else None
        ),
        "cp_seed": int(cp_seed),
        "elapsed_seconds": float(time.perf_counter() - started),
    }


def optimize_itc2007_mwd_batch_chain(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float,
    seed: int = 0,
    validator: Validator | None = None,
) -> MWDBatchChainResult:
    """Run two canonical MWD batches and a fixed-time room continuation."""

    started = time.perf_counter()
    original = _copy_schedule(schedule) if isinstance(schedule, Mapping) else {}
    current = _copy_schedule(original)
    telemetry = MWDBatchChainTelemetry(seed=int(seed))
    validation_fn = validator or _default_validator
    initial_score: ITC2007Score | None = None
    current_score: ITC2007Score | None = None
    eligibility_reasons: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()

    def finish(
        status: str,
        *,
        force_original: bool = False,
        error: str | None = None,
        errors: Sequence[str] = (),
    ) -> MWDBatchChainResult:
        nonlocal validation_errors
        if errors:
            validation_errors = tuple(str(value) for value in errors)[:20]
        improved = bool(
            not force_original
            and initial_score is not None
            and current_score is not None
            and int(current_score.total) < int(initial_score.total)
        )
        returned = _copy_schedule(current if improved else original)
        finished = time.perf_counter()
        overrun = max(0.0, float(finished) - float(deadline))
        deadline_reached = bool(finished >= float(deadline))
        if deadline_reached:
            improved = False
            returned = _copy_schedule(original)
            status = "deadline_exhausted"
        telemetry.timing = {
            "started_at_seconds": float(started),
            "absolute_deadline_seconds": float(deadline),
            "requested_budget_seconds": max(0.0, float(deadline) - started),
            "elapsed_seconds": float(finished - started),
            "deadline_remaining_seconds": max(0.0, float(deadline) - finished),
            "deadline_overrun_seconds": float(overrun),
        }
        return MWDBatchChainResult(
            status=str(status),
            schedule=returned,
            improved=bool(improved),
            initial_score=initial_score,
            final_score=current_score if improved else initial_score,
            telemetry=telemetry,
            validation_errors=validation_errors,
            eligibility_reasons=eligibility_reasons,
            deadline_exhausted=bool(status == "deadline_exhausted" or deadline_reached),
            deadline_overrun_seconds=float(overrun),
            error=error,
        )

    def validate_and_rescore(
        candidate: Mapping[int, Mapping[str, Any]],
        *,
        context: str,
    ) -> tuple[tuple[str, ...], ITC2007Score | None, Schedule]:
        candidate_copy = _copy_schedule(candidate)
        if set(candidate_copy) != {int(value) for value in inst.activities}:
            return ("incomplete_schedule",), None, candidate_copy
        validation_input = _copy_schedule(candidate_copy)
        validation_snapshot = _copy_schedule(validation_input)
        telemetry.validation_calls += 1
        try:
            raw_errors = validation_fn(inst, validation_input)
            candidate_errors = tuple(str(value) for value in raw_errors)
        except Exception as exc:
            raise _FailClosed(
                "error",
                error=f"{context}:validator_error:{type(exc).__name__}:{exc}",
            ) from exc
        if validation_input != validation_snapshot:
            raise _FailClosed(
                "error",
                error=f"{context}:validator_mutated_candidate",
            )
        if time.perf_counter() >= float(deadline):
            raise _FailClosed("deadline_exhausted")
        if candidate_errors:
            return candidate_errors, None, candidate_copy

        score_input = _copy_schedule(candidate_copy)
        score_snapshot = _copy_schedule(score_input)
        official = score_itc2007_instance_schedule(inst, score_input)
        telemetry.independent_rescores += 1
        if score_input != score_snapshot:
            raise _FailClosed(
                "error",
                error=f"{context}:official_rescore_mutated_candidate",
            )
        if not isinstance(official, ITC2007Score) or not _score_is_self_consistent(
            official
        ):
            raise _FailClosed(
                "error",
                error=f"{context}:invalid_official_score",
            )
        if time.perf_counter() >= float(deadline):
            raise _FailClosed("deadline_exhausted")
        return (), official, candidate_copy

    try:
        if started >= float(deadline):
            return finish("deadline_exhausted", force_original=True)
        try:
            eligibility = itc2007_rooted_adjacency_eligibility(
                inst,
                original,
            )
        except Exception as exc:
            return finish(
                "error",
                force_original=True,
                error=f"eligibility_error:{type(exc).__name__}:{exc}",
            )
        eligibility_reasons = tuple(str(value) for value in eligibility.reasons)
        if not eligibility.eligible or eligibility.canonical_schedule is None:
            return finish("ineligible", force_original=True)

        incumbent_errors, initial, canonical_original = validate_and_rescore(
            eligibility.canonical_schedule,
            context="incumbent",
        )
        if incumbent_errors:
            return finish(
                "invalid_incumbent",
                force_original=True,
                errors=incumbent_errors,
            )
        assert initial is not None
        initial_score = initial
        current_score = initial
        current = canonicalize_itc2007_schedule(inst, canonical_original)
        telemetry.component_trajectory.append(
            {"source": "incumbent", **initial_score.to_dict()}
        )

        for round_index in range(ROUND_COUNT):
            now = time.perf_counter()
            remaining_reserve = (
                FINAL_ROOM_RESERVE_SECONDS + FINAL_COMPLETION_RESERVE_SECONDS
            )
            for later_index in range(round_index + 1, ROUND_COUNT):
                remaining_reserve += ROUND_MAX_SECONDS[later_index]
            stage_deadline = min(
                float(deadline) - remaining_reserve,
                now + ROUND_MAX_SECONDS[round_index],
            )
            stage: dict[str, Any] = {
                "name": f"mwd_batch_round_{round_index + 1}",
                "accepted": False,
                "started_at_seconds": float(now),
                "effective_deadline_seconds": float(stage_deadline),
            }
            if stage_deadline <= now + ROUND_INTERNAL_RESERVE_SECONDS:
                stage["status"] = "insufficient_time"
                telemetry.stages.append(stage)
                continue
            helper_input = _copy_schedule(current)
            helper_snapshot = _copy_schedule(helper_input)
            candidate, model_telemetry = _round_model(
                inst,
                helper_input,
                deadline=float(stage_deadline),
                cp_seed=CP_SEEDS[round_index],
            )
            if helper_input != helper_snapshot:
                raise _FailClosed(
                    "error",
                    error=f"{stage['name']}:helper_mutated_incumbent",
                )
            stage.update(
                {
                    key: value
                    for key, value in model_telemetry.items()
                    if key != "status"
                }
            )
            stage["helper_status"] = str(model_telemetry.get("status", "unknown"))
            if time.perf_counter() > float(stage_deadline):
                stage["status"] = "rejected_deadline_exhausted"
                stage["finished_at_seconds"] = float(time.perf_counter())
                telemetry.stages.append(stage)
                continue
            errors, score, candidate_copy = validate_and_rescore(
                candidate,
                context=stage["name"],
            )
            stage["validation_errors"] = list(errors[:10])
            stage["candidate_score"] = None if score is None else score.to_dict()
            if time.perf_counter() > float(stage_deadline):
                stage["status"] = "rejected_deadline_exhausted"
            elif errors or score is None:
                stage["status"] = "rejected_invalid"
            elif current_score is None or int(score.total) >= int(current_score.total):
                stage["status"] = "rejected_not_strictly_better"
            else:
                canonical_candidate = canonicalize_itc2007_schedule(
                    inst,
                    candidate_copy,
                )
                if time.perf_counter() > float(stage_deadline):
                    stage["status"] = "rejected_deadline_exhausted"
                else:
                    current = canonical_candidate
                    current_score = score
                    stage["accepted"] = True
                    stage["status"] = "accepted"
                    telemetry.component_trajectory.append(
                        {"source": stage["name"], **score.to_dict()}
                    )
            stage["finished_at_seconds"] = float(time.perf_counter())
            telemetry.stages.append(stage)

        room_started = time.perf_counter()
        room_deadline = float(deadline) - FINAL_COMPLETION_RESERVE_SECONDS
        room_stage: dict[str, Any] = {
            "name": "course_room_ejection_descent",
            "accepted": False,
            "started_at_seconds": float(room_started),
            "effective_deadline_seconds": float(room_deadline),
        }
        if room_deadline > room_started + 0.01:
            helper_input = _copy_schedule(current)
            helper_snapshot = _copy_schedule(helper_input)
            room_candidate, room_status, room_telemetry = _course_room_ejection_descent(
                inst,
                helper_input,
                deadline=float(room_deadline),
                max_sweeps=16,
            )
            if helper_input != helper_snapshot:
                raise _FailClosed(
                    "error",
                    error="course_room_ejection_descent:helper_mutated_incumbent",
                )
            room_stage["helper_status"] = str(room_status)
            room_stage["helper_telemetry"] = dict(room_telemetry)
            if time.perf_counter() <= float(room_deadline):
                errors, score, candidate_copy = validate_and_rescore(
                    room_candidate,
                    context="course_room_ejection_descent",
                )
                room_stage["validation_errors"] = list(errors[:10])
                room_stage["candidate_score"] = (
                    None if score is None else score.to_dict()
                )
                if time.perf_counter() > float(room_deadline):
                    room_stage["status"] = "rejected_deadline_exhausted"
                elif errors or score is None:
                    room_stage["status"] = "rejected_invalid"
                elif current_score is None or int(score.total) >= int(
                    current_score.total
                ):
                    room_stage["status"] = "rejected_not_strictly_better"
                else:
                    canonical_candidate = canonicalize_itc2007_schedule(
                        inst,
                        candidate_copy,
                    )
                    if time.perf_counter() > float(room_deadline):
                        room_stage["status"] = "rejected_deadline_exhausted"
                    else:
                        current = canonical_candidate
                        current_score = score
                        room_stage["accepted"] = True
                        room_stage["status"] = "accepted"
                        telemetry.component_trajectory.append(
                            {"source": room_stage["name"], **score.to_dict()}
                        )
            else:
                room_stage["status"] = "rejected_deadline_exhausted"
        else:
            room_stage["status"] = "insufficient_time"
        room_stage["finished_at_seconds"] = float(time.perf_counter())
        telemetry.stages.append(room_stage)

        final_errors, final_official, final_copy = validate_and_rescore(
            current,
            context="final",
        )
        if final_errors or final_official is None:
            return finish(
                "invalid_candidate",
                force_original=True,
                errors=final_errors,
            )
        if current_score is None or final_official != current_score:
            return finish(
                "error",
                force_original=True,
                error="final_official_score_disagreement",
            )
        current = canonicalize_itc2007_schedule(inst, final_copy)
        current_score = final_official
        return finish(
            "improved"
            if int(current_score.total) < int(initial_score.total)
            else "no_improvement"
        )
    except _FailClosed as exc:
        return finish(
            exc.status,
            force_original=True,
            error=exc.error,
            errors=exc.validation_errors,
        )
    except Exception as exc:
        return finish(
            "error",
            force_original=True,
            error=f"{type(exc).__name__}:{exc}",
        )


__all__ = [
    "CONFLICT_CLOSURE_DEPTH",
    "CP_SEEDS",
    "FINAL_COMPLETION_RESERVE_SECONDS",
    "FINAL_ROOM_RESERVE_SECONDS",
    "MWDBatchChainResult",
    "MWDBatchChainTelemetry",
    "ROOTS_PER_ROUND",
    "ROUND_COUNT",
    "ROUND_INTERNAL_RESERVE_SECONDS",
    "ROUND_MAX_SECONDS",
    "optimize_itc2007_mwd_batch_chain",
]
