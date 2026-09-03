from __future__ import annotations

"""Exact conflict-graph frontiers rooted in ITC-2007 MWD deficits.

Minimum-working-days repair is a standard timetabling neighborhood. This
module adds a deterministic, representation-derived root order and a bounded
exact official-objective solve over each root's direct teacher/curriculum
conflict frontier. Every candidate is accepted only after full hard validation
and an independent official rescore. Eligibility, mutation, score-parity, and
deadline boundaries fail closed to the caller's exact incumbent.
"""

import copy
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from benchmarks.itc2007 import (
    ITC2007Score,
    canonicalize_itc2007_schedule,
    score_itc2007_instance_schedule,
)
from core.itc2007_stability_ejection import (
    _AttemptDeadline,
    _Frontier,
    _State,
    _Target,
)
from core.projected_time_search import itc2007_fixed_time_room_cp_eligibility
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]

DEFAULT_MAX_TARGET_COURSES = 16
DEFAULT_MAX_FRONTIER_COURSES = 14
DEFAULT_MAX_FRONTIER_ACTIVITIES = 48
DEFAULT_MAX_MOVED_ACTIVITIES = 22
DEFAULT_MAX_SOLVE_SECONDS = 12.0
DEFAULT_MAX_SECONDS_PER_TARGET = 1.35
DEFAULT_COMPLETION_RESERVE_SECONDS = 0.04


@dataclass(frozen=True)
class MWDConflictRoot:
    course_code: str
    mwd_penalty: int
    covered_stability_penalty: int
    stability_repair_support: int
    fragmented_courses: tuple[str, ...]
    primary_rooms: tuple[int, ...]
    conflict_courses: tuple[str, ...]
    frontier_courses: tuple[str, ...]
    frontier_activity_count: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fragmented_courses"] = list(self.fragmented_courses)
        payload["primary_rooms"] = list(self.primary_rooms)
        payload["conflict_courses"] = list(self.conflict_courses)
        payload["frontier_courses"] = list(self.frontier_courses)
        return payload


@dataclass
class MWDConflictFrontierTelemetry:
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
    timing: dict[str, float | int | bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MWDConflictFrontierResult:
    status: str
    schedule: Schedule
    improved: bool
    initial_score: ITC2007Score | None
    final_score: ITC2007Score | None
    telemetry: MWDConflictFrontierTelemetry
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


def _build_roots(state: _State) -> tuple[MWDConflictRoot, ...]:
    roots: list[MWDConflictRoot] = []
    for course_code in state.activities_by_course:
        penalty = int(state._course_mwd_term(course_code))
        if penalty <= 0:
            continue
        conflicts = tuple(state.conflict_neighbors[course_code])
        frontier_courses = tuple(sorted({course_code, *conflicts}))
        frontier_course_set = set(frontier_courses)
        fragmented_courses = tuple(
            code for code in frontier_courses if state._course_stability_term(code) > 0
        )
        covered_stability_penalty = sum(
            state._course_stability_term(code) for code in fragmented_courses
        )
        stability_repair_support = sum(
            state._course_stability_term(code)
            * (
                1
                + len(
                    set(state.conflict_neighbors[code]).intersection(
                        frontier_course_set
                    )
                )
            )
            for code in fragmented_courses
        )
        frontier_activity_count = sum(
            len(state.activities_by_course[code]) for code in frontier_courses
        )
        roots.append(
            MWDConflictRoot(
                course_code=str(course_code),
                mwd_penalty=penalty,
                covered_stability_penalty=int(covered_stability_penalty),
                stability_repair_support=int(stability_repair_support),
                fragmented_courses=fragmented_courses,
                primary_rooms=tuple(state.support_by_course[course_code]),
                conflict_courses=conflicts,
                frontier_courses=frontier_courses,
                frontier_activity_count=int(frontier_activity_count),
            )
        )
    roots.sort(key=lambda root: (-int(root.mwd_penalty), str(root.course_code)))
    return tuple(roots)


def _prioritize_roots(
    roots: Sequence[MWDConflictRoot],
    *,
    max_frontier_courses: int,
    max_frontier_activities: int,
) -> tuple[MWDConflictRoot, ...]:
    """Rank bounded roots by exact cross-component repair leverage.

    The target course's MWD penalty is the primary opportunity. A fragmented
    course inside the same exact frontier adds an immediately modeled room-
    stability opportunity. The conflict closure present around fragmented
    courses measures whether the frontier exposes useful displacement chains.
    Oversized roots are screened behind every cap-eligible root so structural
    leverage never consumes solve time outside the caller's bounds.
    """

    def priority(root: MWDConflictRoot) -> tuple[Any, ...]:
        exceeds_cap = bool(
            len(root.frontier_courses) > int(max_frontier_courses)
            or int(root.frontier_activity_count) > int(max_frontier_activities)
        )
        return (
            int(exceeds_cap),
            -int(root.mwd_penalty + root.covered_stability_penalty),
            -int(root.covered_stability_penalty),
            -int(root.stability_repair_support),
            -len(root.frontier_courses),
            -int(root.frontier_activity_count),
            str(root.course_code),
        )

    return tuple(sorted(roots, key=priority))


def optimize_itc2007_mwd_conflict_frontier(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float,
    seed: int = 0,
    max_target_courses: int = DEFAULT_MAX_TARGET_COURSES,
    max_frontier_courses: int = DEFAULT_MAX_FRONTIER_COURSES,
    max_frontier_activities: int = DEFAULT_MAX_FRONTIER_ACTIVITIES,
    max_moved_activities: int = DEFAULT_MAX_MOVED_ACTIVITIES,
    max_solve_seconds: float = DEFAULT_MAX_SOLVE_SECONDS,
    max_seconds_per_target: float = DEFAULT_MAX_SECONDS_PER_TARGET,
    completion_reserve_seconds: float = DEFAULT_COMPLETION_RESERVE_SECONDS,
    validator: Validator | None = None,
) -> MWDConflictFrontierResult:
    """Try strict exact improvements rooted in MWD-deficient courses.

    A root includes every activity of the deficient course and every activity
    of its direct teacher/curriculum conflict neighbors. The exact model may
    improve any official component; the root is only a deterministic way to
    expose a useful neighborhood. No course identifier or target score is
    encoded in selection or acceptance.
    """

    started = time.perf_counter()
    original = _copy_schedule(schedule) if isinstance(schedule, Mapping) else {}
    selected: Schedule | None = None
    validation_fn = validator or _default_validator
    telemetry = MWDConflictFrontierTelemetry(seed=int(seed))
    initial_score: ITC2007Score | None = None
    final_score: ITC2007Score | None = None
    validation_errors: tuple[str, ...] = ()
    eligibility_reasons: tuple[str, ...] = ()
    search_deadline = float(deadline)

    def finish(
        status: str,
        *,
        force_original: bool = False,
        error: str | None = None,
        errors: Sequence[str] = (),
    ) -> MWDConflictFrontierResult:
        nonlocal validation_errors
        if errors:
            validation_errors = tuple(str(value) for value in errors)[:20]
        improvement_ready = bool(
            not force_original
            and selected is not None
            and initial_score is not None
            and final_score is not None
            and int(final_score.total) < int(initial_score.total)
        )
        returned = _copy_schedule(
            selected if improvement_ready and selected is not None else original
        )
        finished = time.perf_counter()
        overrun = max(0.0, float(finished) - float(deadline))
        if overrun > 0.0:
            improvement_ready = False
            returned = _copy_schedule(original)
            finished = time.perf_counter()
            overrun = max(0.0, float(finished) - float(deadline))
            status = "deadline_exhausted"
            error = None
        telemetry.timing = {
            "started_at_seconds": float(started),
            "absolute_deadline_seconds": float(deadline),
            "search_deadline_seconds": float(search_deadline),
            "requested_budget_seconds": max(0.0, float(deadline) - started),
            "elapsed_seconds": float(finished - started),
            "deadline_remaining_seconds": max(0.0, float(deadline) - finished),
            "deadline_overrun_seconds": float(overrun),
        }
        return MWDConflictFrontierResult(
            status=str(status),
            schedule=returned,
            improved=bool(improvement_ready),
            initial_score=initial_score,
            final_score=final_score if improvement_ready else initial_score,
            telemetry=telemetry,
            validation_errors=validation_errors,
            eligibility_reasons=eligibility_reasons,
            deadline_exhausted=bool(
                status == "deadline_exhausted" or finished >= float(deadline)
            ),
            deadline_overrun_seconds=float(overrun),
            error=error,
        )

    def check_global_deadline() -> None:
        if time.perf_counter() >= float(deadline):
            raise _FailClosed("deadline_exhausted")

    def validate_and_rescore(
        candidate: Mapping[int, Mapping[str, Any]],
        *,
        context: str,
    ) -> tuple[tuple[str, ...], ITC2007Score | None]:
        try:
            candidate_copy = _copy_schedule(candidate)
        except Exception as exc:
            return (f"invalid_schedule_shape:{type(exc).__name__}:{exc}",), None
        expected_ids = {int(value) for value in getattr(inst, "activities", {})}
        if set(candidate_copy) != expected_ids:
            return ("incomplete_schedule",), None

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
        check_global_deadline()
        if candidate_errors:
            return candidate_errors, None

        score_input = _copy_schedule(candidate_copy)
        score_snapshot = _copy_schedule(score_input)
        try:
            official = score_itc2007_instance_schedule(inst, score_input)
        except Exception as exc:
            raise _FailClosed(
                "error",
                error=f"{context}:official_rescore_error:{type(exc).__name__}:{exc}",
            ) from exc
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
        check_global_deadline()
        return (), official

    try:
        if started >= float(deadline):
            return finish("deadline_exhausted", force_original=True)
        bounds = (
            int(max_target_courses),
            int(max_frontier_courses),
            int(max_frontier_activities),
            int(max_moved_activities),
        )
        if (
            any(value < 1 for value in bounds)
            or float(max_solve_seconds) <= 0.0
            or float(max_seconds_per_target) <= 0.0
            or float(completion_reserve_seconds) < 0.0
        ):
            eligibility_reasons = ("search_bounds_invalid",)
            return finish("ineligible", force_original=True)

        try:
            eligible, raw_reasons = itc2007_fixed_time_room_cp_eligibility(
                inst, original
            )
        except Exception as exc:
            return finish(
                "error",
                force_original=True,
                error=f"eligibility_error:{type(exc).__name__}:{exc}",
            )
        eligibility_reasons = tuple(str(value) for value in raw_reasons)
        if not eligible:
            return finish("ineligible", force_original=True)

        incumbent_errors, official_initial = validate_and_rescore(
            original,
            context="incumbent",
        )
        if incumbent_errors:
            return finish(
                "invalid_incumbent",
                force_original=True,
                errors=incumbent_errors,
            )
        assert official_initial is not None
        initial_score = official_initial
        if int(initial_score.total) <= 0:
            return finish("no_improvement")

        canonical_input = _copy_schedule(original)
        canonical_snapshot = _copy_schedule(canonical_input)
        try:
            working = canonicalize_itc2007_schedule(inst, canonical_input)
        except Exception as exc:
            return finish(
                "ineligible",
                force_original=True,
                error=f"canonicalization_error:{type(exc).__name__}:{exc}",
            )
        if canonical_input != canonical_snapshot:
            return finish(
                "error",
                force_original=True,
                error="canonicalizer_mutated_incumbent",
            )
        check_global_deadline()

        state = _State(inst, working)
        roots = _prioritize_roots(
            _build_roots(state),
            max_frontier_courses=int(max_frontier_courses),
            max_frontier_activities=int(max_frontier_activities),
        )
        telemetry.roots = [root.to_dict() for root in roots]
        if not roots:
            return finish("no_mwd_deficits")

        now = time.perf_counter()
        available = max(0.0, float(deadline) - now)
        reserve = min(
            float(completion_reserve_seconds),
            available * 0.25,
        )
        search_deadline = min(
            float(deadline) - reserve,
            now + float(max_solve_seconds),
        )
        if time.perf_counter() >= float(search_deadline):
            return finish("deadline_exhausted", force_original=True)

        orientation_serial = 0
        for root_index, root in enumerate(roots[: int(max_target_courses)]):
            telemetry.roots_considered += 1
            if time.perf_counter() >= float(search_deadline):
                break
            if len(root.frontier_courses) > int(max_frontier_courses) or int(
                root.frontier_activity_count
            ) > int(max_frontier_activities):
                telemetry.attempts.append(
                    {
                        "root_index": int(root_index),
                        "target_course": str(root.course_code),
                        "status": "frontier_cap",
                        "frontier_course_count": len(root.frontier_courses),
                        "frontier_activity_count": int(root.frontier_activity_count),
                    }
                )
                continue

            activities = tuple(
                sorted(
                    activity_id
                    for course_code in root.frontier_courses
                    for activity_id in state.activities_by_course[course_code]
                )
            )
            for primary_room in root.primary_rooms:
                target_started = time.perf_counter()
                if target_started >= float(search_deadline):
                    break
                target_deadline = min(
                    float(search_deadline),
                    target_started + float(max_seconds_per_target),
                )
                target = _Target(
                    course_code=str(root.course_code),
                    primary_room=int(primary_room),
                    support=root.primary_rooms,
                    minority_activities=tuple(
                        activity_id
                        for activity_id in state.activities_by_course[root.course_code]
                        if state.base_room[activity_id] != int(primary_room)
                    ),
                )
                frontier = _Frontier(
                    target=target,
                    courses=root.frontier_courses,
                    activities=activities,
                    direct_room_blockers=(),
                    conflict_courses=root.conflict_courses,
                    room_displacement_courses=(),
                )
                attempt: dict[str, Any] = {
                    "root_index": int(root_index),
                    "target_course": str(root.course_code),
                    "mwd_penalty": int(root.mwd_penalty),
                    "primary_room": int(primary_room),
                    "frontier_courses": list(root.frontier_courses),
                    "frontier_activity_count": len(activities),
                    "requested_deadline_seconds": float(target_deadline),
                    "started_at_seconds": float(target_started),
                    "accepted": False,
                }
                telemetry.attempts.append(attempt)
                telemetry.roots_attempted += 1
                telemetry.frontiers_built += 1
                try:
                    model_result = state.solve_frontier(
                        frontier,
                        incumbent_score=initial_score,
                        deadline=float(target_deadline),
                        seed=int(seed) + orientation_serial,
                        max_moved_activities=int(max_moved_activities),
                    )
                    orientation_serial += 1
                    telemetry.models_solved += 1
                    attempt.update(
                        {
                            "status": str(model_result.status),
                            "model_score": model_result.model_score,
                            "solve_elapsed_seconds": float(
                                model_result.solve_elapsed_seconds
                            ),
                            "changes": [
                                change.to_dict() for change in model_result.changes
                            ],
                        }
                    )
                    if model_result.schedule is None:
                        continue
                    if time.perf_counter() >= float(target_deadline):
                        attempt["status"] = "deadline_exhausted"
                        continue

                    frontier_ids = set(frontier.activities)
                    for activity_id in state.activity_ids:
                        if activity_id not in frontier_ids:
                            model_result.schedule[activity_id] = copy.deepcopy(
                                original[activity_id]
                            )

                    candidate_errors, official = validate_and_rescore(
                        model_result.schedule,
                        context="candidate",
                    )
                    if candidate_errors:
                        attempt["status"] = "invalid_candidate"
                        attempt["validation_errors"] = list(candidate_errors[:10])
                        continue
                    assert official is not None
                    attempt["official_score"] = official.to_dict()
                    attempt["score_parity"] = model_result.model_score == int(
                        official.total
                    )
                    if not attempt["score_parity"]:
                        raise _FailClosed(
                            "error",
                            error="model_official_score_disagreement",
                        )
                    if int(official.total) >= int(initial_score.total):
                        attempt["status"] = "not_strictly_better"
                        continue

                    selected = _copy_schedule(model_result.schedule)
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
                    attempt["finished_at_seconds"] = float(time.perf_counter())
                    attempt["elapsed_seconds"] = float(
                        attempt["finished_at_seconds"] - target_started
                    )
                    attempt["deadline_overrun_seconds"] = max(
                        0.0,
                        attempt["finished_at_seconds"] - float(target_deadline),
                    )

        return finish(
            "deadline_exhausted"
            if time.perf_counter() >= float(search_deadline)
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
    "DEFAULT_COMPLETION_RESERVE_SECONDS",
    "DEFAULT_MAX_FRONTIER_ACTIVITIES",
    "DEFAULT_MAX_FRONTIER_COURSES",
    "DEFAULT_MAX_MOVED_ACTIVITIES",
    "DEFAULT_MAX_SECONDS_PER_TARGET",
    "DEFAULT_MAX_SOLVE_SECONDS",
    "DEFAULT_MAX_TARGET_COURSES",
    "MWDConflictFrontierResult",
    "MWDConflictFrontierTelemetry",
    "MWDConflictRoot",
    "optimize_itc2007_mwd_conflict_frontier",
]
