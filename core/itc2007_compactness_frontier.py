from __future__ import annotations

"""Bounded curriculum-rooted repair for ITC-2007 CTT schedules.

Curriculum ejection chains and exact CP neighborhoods are established
timetabling techniques.  This module makes no algorithmic novelty claim.  It
adds a deterministic, representation-derived root selector around isolated
curriculum lectures, reuses the exact official-objective frontier model, and
keeps validation, rescoring, mutation, and deadline boundaries fail closed.
"""

import copy
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from typing import Any

from benchmarks.itc2007 import (
    ITC2007Score,
    canonicalize_itc2007_schedule,
    score_itc2007_instance_schedule,
)
from core.itc2007_stability_ejection import (
    _AttemptDeadline,
    _State,
    _Target,
)
from core.projected_time_search import itc2007_fixed_time_room_cp_eligibility
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]

DEFAULT_MAX_TARGET_COURSES = 2
DEFAULT_MAX_FRONTIER_COURSES = 6
DEFAULT_MAX_FRONTIER_ACTIVITIES = 40
DEFAULT_MAX_FRONTIER_DEPTH = 1
DEFAULT_MAX_MOVED_ACTIVITIES = 10
DEFAULT_MAX_SOLVE_SECONDS = 0.90
DEFAULT_MAX_SECONDS_PER_TARGET = 0.42
DEFAULT_COMPLETION_RESERVE_SECONDS = 0.03


@dataclass(frozen=True)
class CompactnessRoot:
    course_code: str
    primary_room: int
    room_support: tuple[int, ...]
    isolated_activities: tuple[int, ...]
    isolated_occurrences: int
    affected_curricula: tuple[str, ...]
    affected_compactness_penalty: int
    affected_lecture_count: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["room_support"] = list(self.room_support)
        payload["isolated_activities"] = list(self.isolated_activities)
        payload["affected_curricula"] = list(self.affected_curricula)
        return payload


@dataclass
class CompactnessFrontierTelemetry:
    seed: int
    roots: list[dict[str, Any]] = field(default_factory=list)
    roots_considered: int = 0
    roots_attempted: int = 0
    frontiers_built: int = 0
    models_solved: int = 0
    validation_calls: int = 0
    independent_rescores: int = 0
    accepted_candidates: int = 0
    attempts: list[dict[str, Any]] = field(default_factory=list)
    accepted_changes: list[dict[str, Any]] = field(default_factory=list)
    timing: dict[str, float | bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompactnessFrontierResult:
    status: str
    schedule: Schedule
    improved: bool
    initial_score: ITC2007Score | None
    final_score: ITC2007Score | None
    telemetry: CompactnessFrontierTelemetry
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


def _compactness_roots(state: _State) -> tuple[tuple[CompactnessRoot, _Target], ...]:
    isolated_by_course: dict[str, set[int]] = defaultdict(set)
    occurrences_by_course: Counter[str] = Counter()
    curricula_by_course: dict[str, set[str]] = defaultdict(set)

    for curriculum, member_codes in sorted(state.curricula.items()):
        member_activities = [
            activity_id
            for code in member_codes
            for activity_id in state.activities_by_course[code]
        ]
        occupied = {state.base_period[activity_id] for activity_id in member_activities}
        for activity_id in member_activities:
            period = state.base_period[activity_id]
            slot = period % state.slots_per_day
            adjacent = (slot > 0 and period - 1 in occupied) or (
                slot + 1 < state.slots_per_day and period + 1 in occupied
            )
            if adjacent:
                continue
            code = state.course_code[activity_id]
            isolated_by_course[code].add(int(activity_id))
            occurrences_by_course[code] += 1
            curricula_by_course[code].add(str(curriculum))

    output: list[tuple[CompactnessRoot, _Target]] = []
    for code, isolated_activities in isolated_by_course.items():
        support = state.support_by_course[code]
        orientations = []
        for primary_room in support:
            orientations.append(
                _Target(
                    course_code=code,
                    primary_room=int(primary_room),
                    support=support,
                    minority_activities=tuple(
                        activity_id
                        for activity_id in state.activities_by_course[code]
                        if state.base_room[activity_id] != int(primary_room)
                    ),
                )
            )
        target = min(orientations, key=state._target_orientation_priority)
        root = CompactnessRoot(
            course_code=code,
            primary_room=int(target.primary_room),
            room_support=tuple(int(value) for value in support),
            isolated_activities=tuple(sorted(isolated_activities)),
            isolated_occurrences=int(occurrences_by_course[code]),
            affected_curricula=tuple(sorted(curricula_by_course[code])),
            affected_compactness_penalty=sum(
                state._curriculum_compactness_term(curriculum)
                for curriculum in curricula_by_course[code]
            ),
            affected_lecture_count=sum(
                len(state.activities_by_course[member_code])
                for curriculum in curricula_by_course[code]
                for member_code in state.curricula[curriculum]
            ),
        )
        output.append((root, target))

    output.sort(key=lambda value: _compactness_root_priority(value[0]))
    return tuple(output)


def _compactness_root_priority(root: CompactnessRoot) -> tuple[Any, ...]:
    """Prefer the smallest high-density compactness repair surface.

    Exact compactness frontiers become expensive when the root represents
    several isolated curriculum occurrences.  A single-occurrence root is a
    cheaper surgical entry point.  Among equally small roots, the current
    compactness cost per affected curriculum lecture estimates how much of the
    official penalty is exposed without building or solving every frontier.
    All remaining tie-breakers are stable representation fields.
    """

    compactness_density = Fraction(
        max(0, int(root.affected_compactness_penalty)),
        max(1, int(root.affected_lecture_count)),
    )
    return (
        max(0, int(root.isolated_occurrences)),
        len(root.isolated_activities),
        len(root.affected_curricula),
        -compactness_density,
        len(root.room_support),
        root.course_code,
        int(root.primary_room),
    )


def optimize_itc2007_compactness_frontier(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float,
    seed: int = 0,
    max_target_courses: int = DEFAULT_MAX_TARGET_COURSES,
    max_frontier_courses: int = DEFAULT_MAX_FRONTIER_COURSES,
    max_frontier_activities: int = DEFAULT_MAX_FRONTIER_ACTIVITIES,
    max_frontier_depth: int = DEFAULT_MAX_FRONTIER_DEPTH,
    max_moved_activities: int = DEFAULT_MAX_MOVED_ACTIVITIES,
    max_solve_seconds: float = DEFAULT_MAX_SOLVE_SECONDS,
    max_seconds_per_target: float = DEFAULT_MAX_SECONDS_PER_TARGET,
    completion_reserve_seconds: float = DEFAULT_COMPLETION_RESERVE_SECONDS,
    validator: Validator | None = None,
) -> CompactnessFrontierResult:
    """Repair isolated curriculum lectures through one atomic exact frontier.

    Roots, rooms, blocker courses, and conflict closure are all derived from
    the incumbent representation.  A candidate is returned only when the
    reused exact model agrees with a fresh official-component rescore and an
    independent hard validator accepts it before the caller's deadline.
    """

    started = time.perf_counter()
    original = _copy_schedule(schedule) if isinstance(schedule, Mapping) else {}
    telemetry = CompactnessFrontierTelemetry(seed=int(seed))
    validation_fn = validator or _default_validator
    initial_score: ITC2007Score | None = None
    final_score: ITC2007Score | None = None
    selected: Schedule | None = None
    search_deadline = float(deadline)

    def finish(
        status: str,
        *,
        errors: Sequence[str] = (),
        eligibility_reasons: Sequence[str] = (),
        error: str | None = None,
    ) -> CompactnessFrontierResult:
        improvement_ready = bool(
            selected is not None
            and initial_score is not None
            and final_score is not None
            and int(final_score.total) < int(initial_score.total)
        )
        returned = _copy_schedule(
            selected if improvement_ready and selected is not None else original
        )
        finished = time.perf_counter()
        overrun = max(0.0, finished - float(deadline))
        improved = bool(improvement_ready and overrun == 0.0)
        if improvement_ready and not improved:
            returned = _copy_schedule(original)
            finished = time.perf_counter()
            overrun = max(0.0, finished - float(deadline))
        telemetry.timing = {
            "started_at_seconds": float(started),
            "absolute_deadline_seconds": float(deadline),
            "search_deadline_seconds": float(search_deadline),
            "requested_budget_seconds": max(0.0, float(deadline) - started),
            "finished_at_seconds": float(finished),
            "elapsed_seconds": float(finished - started),
            "deadline_remaining_seconds": max(0.0, float(deadline) - finished),
            "deadline_overrun_seconds": float(overrun),
        }
        return CompactnessFrontierResult(
            status=(
                str(status)
                if improved or status != "improved"
                else "deadline_exhausted"
            ),
            schedule=returned,
            improved=improved,
            initial_score=initial_score,
            final_score=final_score if improved else initial_score,
            telemetry=telemetry,
            validation_errors=tuple(str(value) for value in errors)[:20],
            eligibility_reasons=tuple(str(value) for value in eligibility_reasons),
            deadline_exhausted=bool(finished >= float(deadline)),
            deadline_overrun_seconds=float(overrun),
            error=error,
        )

    try:
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        integer_bounds = {
            "max_target_courses": int(max_target_courses),
            "max_frontier_courses": int(max_frontier_courses),
            "max_frontier_activities": int(max_frontier_activities),
            "max_frontier_depth": int(max_frontier_depth),
            "max_moved_activities": int(max_moved_activities),
        }
        if (
            any(
                value < 1
                for key, value in integer_bounds.items()
                if key != "max_frontier_depth"
            )
            or integer_bounds["max_frontier_depth"] < 0
            or float(max_solve_seconds) <= 0.0
            or float(max_seconds_per_target) <= 0.0
            or float(completion_reserve_seconds) < 0.0
        ):
            return finish(
                "ineligible",
                eligibility_reasons=("search_bounds_must_be_positive",),
            )

        eligible, reasons = itc2007_fixed_time_room_cp_eligibility(inst, original)
        if not eligible:
            return finish("ineligible", eligibility_reasons=reasons)

        telemetry.validation_calls += 1
        incumbent_errors = tuple(str(value) for value in validation_fn(inst, original))
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        if incumbent_errors:
            return finish("invalid_incumbent", errors=incumbent_errors)

        initial_score = score_itc2007_instance_schedule(inst, original)
        if int(initial_score.curriculum_compactness) <= 0:
            return finish("no_isolated_lectures")

        working = canonicalize_itc2007_schedule(inst, original)
        state = _State(inst, working)
        roots = _compactness_roots(state)
        telemetry.roots = [root.to_dict() for root, _target in roots]
        if not roots:
            return finish("no_isolated_lectures")

        now = time.perf_counter()
        available = max(0.0, float(deadline) - now)
        reserve = min(
            max(0.0, float(completion_reserve_seconds)),
            max(0.0, available * 0.25),
        )
        search_deadline = min(
            float(deadline) - reserve,
            now + max(0.0, float(max_solve_seconds)),
        )
        if time.perf_counter() >= search_deadline:
            return finish("deadline_exhausted")

        for root_index, (root, target) in enumerate(roots[: int(max_target_courses)]):
            telemetry.roots_considered += 1
            root_started = time.perf_counter()
            if root_started >= search_deadline:
                break
            root_deadline = min(
                search_deadline,
                root_started + float(max_seconds_per_target),
            )
            attempt: dict[str, Any] = {
                "root_index": int(root_index),
                "root": root.to_dict(),
                "started_at_seconds": float(root_started),
                "requested_deadline_seconds": float(root_deadline),
                "accepted": False,
            }
            telemetry.attempts.append(attempt)
            telemetry.roots_attempted += 1
            try:
                frontier = state.build_frontier(
                    target,
                    max_courses=int(max_frontier_courses),
                    max_activities=int(max_frontier_activities),
                    max_depth=int(max_frontier_depth),
                    deadline=root_deadline,
                )
                if frontier is None:
                    attempt["status"] = "frontier_ineligible"
                    continue
                telemetry.frontiers_built += 1
                attempt.update(
                    {
                        "frontier_courses": list(frontier.courses),
                        "frontier_activity_count": len(frontier.activities),
                        "direct_room_blockers": list(frontier.direct_room_blockers),
                        "conflict_courses": list(frontier.conflict_courses),
                        "room_displacement_courses": list(
                            frontier.room_displacement_courses
                        ),
                    }
                )
                model_result = state.solve_frontier(
                    frontier,
                    incumbent_score=initial_score,
                    deadline=root_deadline,
                    seed=int(seed) + root_index * 104_729,
                    max_moved_activities=int(max_moved_activities),
                )
                telemetry.models_solved += 1
                attempt.update(
                    {
                        "status": model_result.status,
                        "model_score": model_result.model_score,
                        "solve_elapsed_seconds": float(
                            model_result.solve_elapsed_seconds
                        ),
                    }
                )
                if model_result.schedule is None:
                    continue
                if time.perf_counter() >= root_deadline:
                    attempt["status"] = "deadline_exhausted"
                    continue

                frontier_ids = set(frontier.activities)
                for activity_id in state.activity_ids:
                    if activity_id not in frontier_ids:
                        model_result.schedule[activity_id] = copy.deepcopy(
                            original[activity_id]
                        )

                telemetry.validation_calls += 1
                candidate_errors = tuple(
                    str(value) for value in validation_fn(inst, model_result.schedule)
                )
                if time.perf_counter() >= float(deadline):
                    return finish("deadline_exhausted")
                if candidate_errors:
                    attempt["status"] = "invalid_candidate"
                    attempt["validation_errors"] = list(candidate_errors[:10])
                    continue

                telemetry.independent_rescores += 1
                official = score_itc2007_instance_schedule(inst, model_result.schedule)
                attempt["official_score"] = official.to_dict()
                attempt["score_parity"] = model_result.model_score == int(
                    official.total
                )
                if time.perf_counter() >= float(deadline):
                    return finish("deadline_exhausted")
                if not attempt["score_parity"]:
                    return finish(
                        "error",
                        error="model_official_score_disagreement",
                    )
                if int(official.total) >= int(initial_score.total):
                    attempt["status"] = "no_strict_improvement"
                    continue

                selected = model_result.schedule
                final_score = official
                telemetry.accepted_candidates = 1
                telemetry.accepted_changes = [
                    change.to_dict() for change in model_result.changes
                ]
                attempt["accepted"] = True
                attempt["status"] = "improved"
                return finish("improved")
            except _AttemptDeadline:
                attempt["status"] = "deadline_exhausted"
            finally:
                root_finished = time.perf_counter()
                attempt["finished_at_seconds"] = float(root_finished)
                attempt["elapsed_seconds"] = float(root_finished - root_started)
                attempt["deadline_overrun_seconds"] = max(
                    0.0, root_finished - float(root_deadline)
                )

        return finish(
            "deadline_exhausted"
            if time.perf_counter() >= search_deadline
            else "no_improvement"
        )
    except Exception as exc:
        return finish("error", error=f"{type(exc).__name__}:{exc}")


__all__ = [
    "CompactnessFrontierResult",
    "CompactnessFrontierTelemetry",
    "CompactnessRoot",
    "optimize_itc2007_compactness_frontier",
]
