from __future__ import annotations

"""Deadline-coordinated quality tail for small ITC-2007 CTT schedules.

The tail composes established fixed-time room optimization, room-stability
ejection, capacity-changing course-color, and curriculum compactness
neighborhoods.  It makes no algorithmic novelty claim.  Its purpose is to
give those operators one absolute deadline, preserve later-stage reserves,
and enforce a fail-closed validation and official-rescore boundary after
every accepted hand-off.
"""

import copy
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from benchmarks.itc2007 import ITC2007Score, score_itc2007_instance_schedule
from core.itc2007_capacity_frontier import optimize_itc2007_capacity_frontier
from core.itc2007_compactness_frontier import (
    optimize_itc2007_compactness_frontier,
)
from core.itc2007_frontier_alternation import (
    ExactFrontierStage,
    optimize_itc2007_frontier_alternation,
)
from core.itc2007_mwd_conflict_frontier import (
    optimize_itc2007_mwd_conflict_frontier,
)
from core.itc2007_rooted_adjacency import optimize_itc2007_rooted_adjacency
from core.itc2007_stability_ejection import optimize_itc2007_stability_ejection
from core.projected_time_search import (
    itc2007_fixed_time_room_cp_eligibility,
    optimize_itc2007_fixed_time_rooms_cp,
)
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]

QUALITY_TAIL_ACTIVITY_LIMIT = 200
ROOM_CP_SECONDS = 0.75
STABILITY_CALL_SECONDS = 0.55
STABILITY_MINIMUM_SECONDS = 0.40
CAPACITY_SECONDS = 0.40
COMPACTNESS_MINIMUM_SECONDS = 0.30
COMPACTNESS_NOMINAL_SECONDS = 0.45
ROOTED_ADJACENCY_SECONDS = 0.55
ALTERNATION_SECONDS = 1.50
ALTERNATION_COMPACTNESS_SECONDS = 0.85
MWD_DRIVEN_MINIMUM_SECONDS = 1.20
MWD_TINY_SECONDS = 0.55
MWD_ROOTED_SECONDS = 0.55
MWD_SECOND_SECONDS = 1.10
MWD_COMPACTNESS_SECONDS = 0.90
MWD_POLISH_SECONDS = 0.55
MAX_STABILITY_CALLS = 2
STABILITY_FRONTIER_COURSES = 8
STABILITY_FRONTIER_ACTIVITIES = 52


@dataclass(frozen=True)
class ITC2007QualityTailEligibility:
    eligible: bool
    reasons: tuple[str, ...] = ()
    activity_count: int = 0
    activity_limit: int = QUALITY_TAIL_ACTIVITY_LIMIT

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass
class ITC2007QualityTailTelemetry:
    seed: int
    stages: list[dict[str, Any]] = field(default_factory=list)
    component_trajectory: list[dict[str, Any]] = field(default_factory=list)
    accepted_sources: list[str] = field(default_factory=list)
    validation_calls: int = 0
    independent_rescores: int = 0
    timing: dict[str, float | bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ITC2007QualityTailResult:
    status: str
    schedule: Schedule
    improved: bool
    initial_score: ITC2007Score | None
    final_score: ITC2007Score | None
    eligibility: ITC2007QualityTailEligibility
    telemetry: ITC2007QualityTailTelemetry
    accepted_source: str | None = None
    validation_errors: tuple[str, ...] = ()
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
            "eligibility": self.eligibility.to_dict(),
            "telemetry": self.telemetry.to_dict(),
            "accepted_source": self.accepted_source,
            "validation_errors": list(self.validation_errors),
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


def _fixed_starts_equal(
    left: Mapping[int, Mapping[str, Any]],
    right: Mapping[int, Mapping[str, Any]],
) -> bool:
    if {int(value) for value in left} != {int(value) for value in right}:
        return False
    fields = ("week", "day", "slot", "duration")
    return all(
        tuple(left[int(activity_id)].get(field) for field in fields)
        == tuple(right[int(activity_id)].get(field) for field in fields)
        for activity_id in left
    )


def itc2007_quality_tail_eligibility(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    activity_limit: int = QUALITY_TAIL_ACTIVITY_LIMIT,
) -> ITC2007QualityTailEligibility:
    """Admit only small, lossless official ITC-2007 CTT projections."""

    count = len(getattr(inst, "activities", {}) or {})
    reasons: list[str] = []
    try:
        eligible, helper_reasons = itc2007_fixed_time_room_cp_eligibility(
            inst, schedule
        )
        if not eligible:
            reasons.extend(str(value) for value in helper_reasons)
            if not helper_reasons:
                reasons.append("requires_lossless_itc2007_import")
    except Exception as exc:
        reasons.append(f"eligibility_error:{type(exc).__name__}:{exc}")
    if int(activity_limit) < 1:
        reasons.append("activity_limit_must_be_positive")
    elif count > int(activity_limit):
        reasons.append("activity_limit_exceeded")
    unique = tuple(dict.fromkeys(reasons))
    return ITC2007QualityTailEligibility(
        eligible=not unique,
        reasons=unique,
        activity_count=int(count),
        activity_limit=int(activity_limit),
    )


def _helper_overrun_seconds(result: Any) -> float:
    direct = getattr(result, "deadline_overrun_seconds", None)
    if direct is not None:
        return max(0.0, float(direct))
    telemetry = getattr(result, "telemetry", None)
    timing = getattr(telemetry, "timing", {}) if telemetry is not None else {}
    return max(0.0, float((timing or {}).get("deadline_overrun_seconds", 0.0)))


def optimize_itc2007_quality_tail(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float,
    seed: int = 0,
    validator: Validator | None = None,
) -> ITC2007QualityTailResult:
    """Run the bounded quality operators under one absolute deadline.

    The caller owns any final service-level reserve.  This dispatcher never
    accepts a helper result that is late, non-improving, invalid, or reports a
    deadline overrun.  Room CP alone must preserve every lecture start; the
    stability, capacity, and compactness frontiers are allowed to move times
    atomically.
    """

    started = time.perf_counter()
    original = _copy_schedule(schedule) if isinstance(schedule, Mapping) else {}
    current = _copy_schedule(original)
    validation_fn = validator or _default_validator
    telemetry = ITC2007QualityTailTelemetry(seed=int(seed))
    eligibility = itc2007_quality_tail_eligibility(inst, original)
    initial_score: ITC2007Score | None = None
    current_score: ITC2007Score | None = None
    validation_errors: tuple[str, ...] = ()
    accepted_source: str | None = None

    def finish(
        status: str,
        *,
        error: str | None = None,
        errors: Sequence[str] = (),
    ) -> ITC2007QualityTailResult:
        strictly_improved = bool(
            initial_score is not None
            and current_score is not None
            and int(current_score.total) < int(initial_score.total)
        )
        returned = _copy_schedule(current if strictly_improved else original)
        finished = time.perf_counter()
        overrun = max(0.0, float(finished) - float(deadline))
        improved = bool(strictly_improved and overrun == 0.0)
        if overrun > 0.0:
            if strictly_improved:
                returned = _copy_schedule(original)
                finished = time.perf_counter()
                overrun = max(0.0, float(finished) - float(deadline))
            status = "deadline_exhausted"
        telemetry.timing = {
            "started_at_seconds": float(started),
            "absolute_deadline_seconds": float(deadline),
            "requested_budget_seconds": max(0.0, float(deadline) - started),
            "finished_at_seconds": float(finished),
            "elapsed_seconds": float(finished - started),
            "deadline_remaining_seconds": max(0.0, float(deadline) - finished),
            "deadline_overrun_seconds": float(overrun),
        }
        return ITC2007QualityTailResult(
            status=str(
                status if improved or status != "improved" else "no_improvement"
            ),
            schedule=returned,
            improved=bool(improved),
            initial_score=initial_score,
            final_score=current_score if improved else initial_score,
            eligibility=eligibility,
            telemetry=telemetry,
            accepted_source=accepted_source if improved else None,
            validation_errors=tuple(
                str(value) for value in (errors or validation_errors)
            )[:20],
            deadline_exhausted=bool(finished >= float(deadline)),
            deadline_overrun_seconds=float(overrun),
            error=error,
        )

    def record_score(source: str, score: ITC2007Score) -> None:
        telemetry.component_trajectory.append(
            {"source": str(source), **score.to_dict()}
        )

    def run_stage(
        *,
        name: str,
        nominal_seconds: float,
        effective_deadline: float,
        helper: Callable[[Schedule, float], Any],
        require_fixed_starts: bool,
    ) -> bool:
        nonlocal current, current_score, accepted_source
        stage_started = time.perf_counter()
        requested_deadline = stage_started + max(0.0, float(nominal_seconds))
        stage: dict[str, Any] = {
            "name": str(name),
            "status": "not_started",
            "accepted": False,
            "input_score": (None if current_score is None else current_score.to_dict()),
            "requested_budget_seconds": float(nominal_seconds),
            "requested_deadline_seconds": float(requested_deadline),
            "effective_deadline_seconds": float(effective_deadline),
            "fixed_starts_required": bool(require_fixed_starts),
            "started_at_seconds": float(stage_started),
        }
        telemetry.stages.append(stage)
        if stage_started >= float(effective_deadline):
            stage["status"] = "skipped_deadline_exhausted"
            stage["finished_at_seconds"] = float(stage_started)
            stage["elapsed_seconds"] = 0.0
            stage["deadline_overrun_seconds"] = max(
                0.0, stage_started - float(effective_deadline)
            )
            return False

        incumbent = _copy_schedule(current)
        try:
            result = helper(_copy_schedule(incumbent), float(effective_deadline))
            helper_finished = time.perf_counter()
            helper_meta = result.to_dict() if hasattr(result, "to_dict") else {}
            stage["helper"] = helper_meta
            helper_overrun = _helper_overrun_seconds(result)
            observed_overrun = max(0.0, helper_finished - float(effective_deadline))
            stage["helper_deadline_overrun_seconds"] = float(helper_overrun)
            if observed_overrun > 0.0 or helper_overrun > 0.0:
                stage["status"] = "rejected_helper_deadline_overrun"
                return False
            if bool(getattr(result, "deadline_exhausted", False)):
                stage["status"] = "rejected_helper_deadline_exhausted"
                return False
            if (
                not bool(getattr(result, "improved", False))
                or str(getattr(result, "status", "unknown")) != "improved"
            ):
                stage["status"] = "no_strict_improvement"
                return False
            candidate = getattr(result, "schedule", None)
            if not isinstance(candidate, Mapping):
                stage["status"] = "rejected_missing_candidate"
                return False
            candidate_copy = _copy_schedule(candidate)
            if require_fixed_starts and not _fixed_starts_equal(
                incumbent, candidate_copy
            ):
                stage["status"] = "rejected_fixed_starts_changed"
                return False

            telemetry.validation_calls += 1
            errors = tuple(str(value) for value in validation_fn(inst, candidate_copy))
            if time.perf_counter() >= float(effective_deadline):
                stage["status"] = "rejected_dispatch_validation_overrun"
                return False
            if errors:
                stage["status"] = "rejected_dispatch_validation"
                stage["validation_errors"] = list(errors[:20])
                return False

            candidate_score = score_itc2007_instance_schedule(inst, candidate_copy)
            telemetry.independent_rescores += 1
            if time.perf_counter() >= float(effective_deadline):
                stage["status"] = "rejected_dispatch_rescore_overrun"
                return False
            if current_score is None or int(candidate_score.total) >= int(
                current_score.total
            ):
                stage["status"] = "rejected_not_strictly_better"
                stage["candidate_score"] = candidate_score.to_dict()
                return False

            current = candidate_copy
            current_score = candidate_score
            accepted_source = str(name)
            telemetry.accepted_sources.append(str(name))
            record_score(str(name), candidate_score)
            stage["status"] = "improved"
            stage["accepted"] = True
            stage["output_score"] = candidate_score.to_dict()
            return True
        except Exception as exc:
            stage["status"] = "error"
            stage["error"] = f"{type(exc).__name__}: {exc}"
            return False
        finally:
            stage_finished = time.perf_counter()
            stage["finished_at_seconds"] = float(stage_finished)
            stage["elapsed_seconds"] = float(stage_finished - stage_started)
            stage["deadline_overrun_seconds"] = max(
                0.0, stage_finished - float(effective_deadline)
            )

    try:
        if started >= float(deadline):
            return finish("deadline_exhausted")
        if not eligibility.eligible:
            return finish("ineligible")

        telemetry.validation_calls += 1
        validation_errors = tuple(str(value) for value in validation_fn(inst, current))
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        if validation_errors:
            return finish("invalid_incumbent", errors=validation_errors)

        initial_score = score_itc2007_instance_schedule(inst, current)
        telemetry.independent_rescores += 1
        current_score = initial_score
        record_score("incumbent", initial_score)
        if int(initial_score.total) <= 0:
            return finish("no_improvement")

        # MWD-heavy basins need a different trajectory from the room-only
        # residuals below.  Capacity pressure benefits from two small exact
        # MWD closures separated by rooted adjacency; without capacity
        # pressure, cheap total-objective polishing exposes the useful wider
        # MWD conflict frontier.  Both policies are representation-driven and
        # use the same strict validation/rescore hand-off as every other stage.
        available_for_upgraded_path = max(
            0.0,
            float(deadline) - time.perf_counter(),
        )
        mwd_driven_path = bool(
            current_score.minimum_working_days > 0
            and (
                current_score.room_capacity > 0
                or current_score.minimum_working_days
                >= current_score.curriculum_compactness
            )
            and available_for_upgraded_path >= float(MWD_DRIVEN_MINIMUM_SECONDS)
        )
        if mwd_driven_path and current_score.room_capacity > 0:
            mwd_boundary = min(
                float(deadline),
                time.perf_counter() + float(MWD_TINY_SECONDS),
            )
            run_stage(
                name="mwd_conflict_frontier_1",
                nominal_seconds=MWD_TINY_SECONDS,
                effective_deadline=float(mwd_boundary),
                require_fixed_starts=False,
                helper=lambda stage_incumbent,
                stage_deadline: optimize_itc2007_mwd_conflict_frontier(
                    inst,
                    stage_incumbent,
                    deadline=float(stage_deadline),
                    seed=int(seed),
                    max_target_courses=16,
                    max_frontier_courses=7,
                    max_frontier_activities=21,
                    max_moved_activities=16,
                    max_solve_seconds=max(
                        0.05,
                        float(stage_deadline) - time.perf_counter() - 0.05,
                    ),
                    max_seconds_per_target=min(
                        0.50,
                        max(
                            0.05,
                            float(stage_deadline) - time.perf_counter() - 0.05,
                        ),
                    ),
                    completion_reserve_seconds=0.04,
                ),
            )

            rooted_boundary = min(
                float(deadline),
                time.perf_counter() + float(MWD_ROOTED_SECONDS),
            )
            run_stage(
                name="rooted_adjacency",
                nominal_seconds=MWD_ROOTED_SECONDS,
                effective_deadline=float(rooted_boundary),
                require_fixed_starts=False,
                helper=lambda stage_incumbent,
                stage_deadline: optimize_itc2007_rooted_adjacency(
                    inst,
                    stage_incumbent,
                    deadline=float(stage_deadline),
                    seed=int(seed) + 104_729,
                    max_moves=32,
                    completion_reserve_seconds=0.10,
                ),
            )

            second_mwd_boundary = min(
                float(deadline),
                time.perf_counter() + float(MWD_SECOND_SECONDS),
            )
            run_stage(
                name="mwd_conflict_frontier_2",
                nominal_seconds=MWD_SECOND_SECONDS,
                effective_deadline=float(second_mwd_boundary),
                require_fixed_starts=False,
                helper=lambda stage_incumbent,
                stage_deadline: optimize_itc2007_mwd_conflict_frontier(
                    inst,
                    stage_incumbent,
                    deadline=float(stage_deadline),
                    seed=int(seed) + 209_458,
                    max_target_courses=16,
                    max_frontier_courses=7,
                    max_frontier_activities=21,
                    max_moved_activities=16,
                    max_solve_seconds=max(
                        0.05,
                        float(stage_deadline) - time.perf_counter() - 0.05,
                    ),
                    max_seconds_per_target=min(
                        0.70,
                        max(
                            0.05,
                            float(stage_deadline) - time.perf_counter() - 0.05,
                        ),
                    ),
                    completion_reserve_seconds=0.04,
                ),
            )

            if (
                current_score is not None
                and current_score.curriculum_compactness > 0
                and time.perf_counter() < float(deadline)
            ):
                compactness_boundary = min(
                    float(deadline),
                    time.perf_counter() + float(MWD_COMPACTNESS_SECONDS),
                )
                run_stage(
                    name="mwd_compactness_frontier",
                    nominal_seconds=MWD_COMPACTNESS_SECONDS,
                    effective_deadline=float(compactness_boundary),
                    require_fixed_starts=False,
                    helper=lambda stage_incumbent,
                    stage_deadline: optimize_itc2007_compactness_frontier(
                        inst,
                        stage_incumbent,
                        deadline=float(stage_deadline),
                        seed=int(seed) + 314_187,
                        max_target_courses=12,
                        max_frontier_courses=10,
                        max_frontier_activities=48,
                        max_frontier_depth=2,
                        max_moved_activities=20,
                        max_solve_seconds=max(
                            0.05,
                            float(stage_deadline) - time.perf_counter() - 0.05,
                        ),
                        max_seconds_per_target=min(
                            0.38,
                            max(
                                0.05,
                                float(stage_deadline) - time.perf_counter() - 0.05,
                            ),
                        ),
                        completion_reserve_seconds=0.04,
                    ),
                )
        elif mwd_driven_path:
            polish_boundary = min(
                float(deadline),
                time.perf_counter() + float(MWD_POLISH_SECONDS),
            )
            run_stage(
                name="mwd_initial_relocate_swap_polish",
                nominal_seconds=MWD_POLISH_SECONDS,
                effective_deadline=float(polish_boundary),
                require_fixed_starts=False,
                helper=lambda stage_incumbent,
                stage_deadline: optimize_itc2007_frontier_alternation(
                    inst,
                    stage_incumbent,
                    deadline=float(stage_deadline),
                    seed=int(seed),
                    exact_frontiers=(),
                    max_cycles=1,
                    max_polish_search_seconds=0.48,
                    max_polish_passes_per_stage=2,
                    max_relocate_checks=100_000,
                    max_swap_checks=50_000,
                    max_polish_shortlist=24,
                    completion_reserve_seconds=0.04,
                ),
            )
            if time.perf_counter() < float(deadline):
                run_stage(
                    name="mwd_conflict_frontier",
                    nominal_seconds=max(
                        0.0,
                        float(deadline) - time.perf_counter(),
                    ),
                    effective_deadline=float(deadline),
                    require_fixed_starts=False,
                    helper=lambda stage_incumbent,
                    stage_deadline: optimize_itc2007_mwd_conflict_frontier(
                        inst,
                        stage_incumbent,
                        deadline=float(stage_deadline),
                        seed=int(seed) + 104_729,
                        max_target_courses=16,
                        max_frontier_courses=14,
                        max_frontier_activities=48,
                        max_moved_activities=22,
                        max_solve_seconds=max(
                            0.05,
                            float(stage_deadline) - time.perf_counter() - 0.05,
                        ),
                        max_seconds_per_target=min(
                            0.45,
                            max(
                                0.05,
                                float(stage_deadline) - time.perf_counter() - 0.05,
                            ),
                        ),
                        completion_reserve_seconds=0.04,
                    ),
                )
        elif available_for_upgraded_path >= float(
            ROOTED_ADJACENCY_SECONDS + ALTERNATION_SECONDS
        ):
            rooted_boundary = min(
                float(deadline) - float(ALTERNATION_SECONDS),
                time.perf_counter() + float(ROOTED_ADJACENCY_SECONDS),
            )
            run_stage(
                name="rooted_adjacency",
                nominal_seconds=ROOTED_ADJACENCY_SECONDS,
                effective_deadline=float(rooted_boundary),
                require_fixed_starts=False,
                helper=lambda stage_incumbent,
                stage_deadline: optimize_itc2007_rooted_adjacency(
                    inst,
                    stage_incumbent,
                    deadline=float(stage_deadline),
                    seed=int(seed),
                    max_moves=32,
                    completion_reserve_seconds=0.10,
                ),
            )

            alternation_boundary = min(
                float(deadline),
                time.perf_counter() + float(ALTERNATION_SECONDS),
            )
            compactness_seconds = min(
                float(ALTERNATION_COMPACTNESS_SECONDS),
                max(0.10, float(alternation_boundary) - time.perf_counter() - 0.10),
            )
            run_stage(
                name="frontier_alternation",
                nominal_seconds=ALTERNATION_SECONDS,
                effective_deadline=float(alternation_boundary),
                require_fixed_starts=False,
                helper=lambda stage_incumbent,
                stage_deadline: optimize_itc2007_frontier_alternation(
                    inst,
                    stage_incumbent,
                    deadline=float(stage_deadline),
                    seed=int(seed),
                    exact_frontiers=(
                        ExactFrontierStage(
                            name="compactness_frontier",
                            optimizer=optimize_itc2007_compactness_frontier,
                            max_seconds=float(compactness_seconds),
                            options={
                                "max_target_courses": 12,
                                "max_frontier_courses": 10,
                                "max_frontier_activities": 48,
                                "max_frontier_depth": 2,
                                "max_moved_activities": 20,
                                "max_solve_seconds": float(compactness_seconds),
                                "max_seconds_per_target": min(
                                    0.65,
                                    float(compactness_seconds),
                                ),
                                "completion_reserve_seconds": 0.04,
                            },
                        ),
                    ),
                    max_cycles=1,
                    max_polish_search_seconds=0.45,
                    max_polish_passes_per_stage=2,
                    max_relocate_checks=100_000,
                    max_swap_checks=50_000,
                    max_polish_shortlist=24,
                    completion_reserve_seconds=0.10,
                ),
            )

        if mwd_driven_path:
            return finish(
                "improved"
                if current_score is not None
                and int(current_score.total) < int(initial_score.total)
                else "no_improvement"
            )

        # Room coloring changes both capacity and the representation used to
        # rank stability frontiers.  Run it before the time-moving ejections,
        # then recompute every stability target from the accepted coloring.
        # The boundaries retain two useful minimum stability slices and one
        # compactness slice while allowing an early stage to hand unused time
        # to every later component-driven stage.
        initial_capacity_reserve = (
            float(CAPACITY_SECONDS) if current_score.room_capacity > 0 else 0.0
        )
        initial_stability_reserve = (
            float(MAX_STABILITY_CALLS * STABILITY_MINIMUM_SECONDS)
            if current_score.room_stability > 0
            else 0.0
        )
        initial_compactness_reserve = (
            float(COMPACTNESS_MINIMUM_SECONDS)
            if current_score.curriculum_compactness > 0
            else 0.0
        )
        room_boundary = min(
            float(deadline),
            started + float(ROOM_CP_SECONDS),
            float(deadline)
            - float(
                initial_capacity_reserve
                + initial_stability_reserve
                + initial_compactness_reserve
            ),
        )

        if current_score.room_capacity > 0 or current_score.room_stability > 0:
            run_stage(
                name="fixed_time_room_cp",
                nominal_seconds=ROOM_CP_SECONDS,
                effective_deadline=float(room_boundary),
                require_fixed_starts=True,
                helper=lambda stage_incumbent,
                stage_deadline: optimize_itc2007_fixed_time_rooms_cp(
                    inst,
                    stage_incumbent,
                    deadline=float(stage_deadline),
                    seed=int(seed),
                ),
            )

        if current_score is not None and current_score.room_capacity > 0:
            post_capacity_stability_reserve = (
                float(MAX_STABILITY_CALLS * STABILITY_MINIMUM_SECONDS)
                if current_score.room_stability > 0
                else 0.0
            )
            post_capacity_compactness_reserve = (
                float(COMPACTNESS_MINIMUM_SECONDS)
                if current_score.curriculum_compactness > 0
                else 0.0
            )
            capacity_boundary = max(
                time.perf_counter(),
                float(deadline)
                - post_capacity_stability_reserve
                - post_capacity_compactness_reserve,
            )
            run_stage(
                name="capacity_frontier",
                nominal_seconds=CAPACITY_SECONDS,
                effective_deadline=float(capacity_boundary),
                require_fixed_starts=False,
                helper=lambda stage_incumbent,
                stage_deadline: optimize_itc2007_capacity_frontier(
                    inst,
                    stage_incumbent,
                    deadline=float(stage_deadline),
                    seed=int(seed),
                    max_exchange_solve_seconds=CAPACITY_SECONDS,
                ),
            )

        if current_score is not None and current_score.room_stability > 0:
            for call_index in range(MAX_STABILITY_CALLS):
                now = time.perf_counter()
                compactness_reserve = (
                    float(COMPACTNESS_MINIMUM_SECONDS)
                    if current_score.curriculum_compactness > 0
                    else 0.0
                )
                stability_deadline = float(deadline) - compactness_reserve
                remaining = max(0.0, stability_deadline - now)
                if remaining < float(STABILITY_MINIMUM_SECONDS):
                    break
                reserve_after = (
                    float(STABILITY_MINIMUM_SECONDS)
                    if call_index + 1 < int(MAX_STABILITY_CALLS)
                    and remaining >= float(2 * STABILITY_MINIMUM_SECONDS)
                    else 0.0
                )
                boundary = min(
                    stability_deadline - reserve_after,
                    now + float(STABILITY_CALL_SECONDS),
                )
                accepted = run_stage(
                    name=f"stability_ejection_{call_index + 1}",
                    nominal_seconds=STABILITY_CALL_SECONDS,
                    effective_deadline=float(boundary),
                    require_fixed_starts=False,
                    helper=lambda stage_incumbent, stage_deadline, offset=call_index: (
                        optimize_itc2007_stability_ejection(
                            inst,
                            stage_incumbent,
                            deadline=float(stage_deadline),
                            seed=int(seed) + offset * 65_537,
                            max_target_courses=1,
                            max_frontier_courses=STABILITY_FRONTIER_COURSES,
                            max_frontier_activities=(STABILITY_FRONTIER_ACTIVITIES),
                            max_frontier_depth=1,
                            max_moved_activities=12,
                            max_solve_seconds=STABILITY_CALL_SECONDS,
                            max_seconds_per_target=STABILITY_CALL_SECONDS,
                            completion_reserve_seconds=0.02,
                        )
                    ),
                )
                if not accepted:
                    break
                if current_score is None or current_score.room_stability <= 0:
                    break

        if (
            current_score is not None
            and current_score.curriculum_compactness > 0
            and float(deadline) - time.perf_counter()
            >= float(COMPACTNESS_MINIMUM_SECONDS)
        ):
            run_stage(
                name="compactness_frontier",
                nominal_seconds=COMPACTNESS_NOMINAL_SECONDS,
                effective_deadline=float(deadline),
                require_fixed_starts=False,
                helper=lambda stage_incumbent,
                stage_deadline: optimize_itc2007_compactness_frontier(
                    inst,
                    stage_incumbent,
                    deadline=float(stage_deadline),
                    seed=int(seed),
                ),
            )

        return finish(
            "improved"
            if initial_score is not None
            and current_score is not None
            and int(current_score.total) < int(initial_score.total)
            else "no_improvement"
        )
    except Exception as exc:
        return finish("error", error=f"{type(exc).__name__}: {exc}")


__all__ = [
    "CAPACITY_SECONDS",
    "COMPACTNESS_MINIMUM_SECONDS",
    "COMPACTNESS_NOMINAL_SECONDS",
    "ROOTED_ADJACENCY_SECONDS",
    "ALTERNATION_SECONDS",
    "ALTERNATION_COMPACTNESS_SECONDS",
    "MWD_COMPACTNESS_SECONDS",
    "MWD_DRIVEN_MINIMUM_SECONDS",
    "MWD_POLISH_SECONDS",
    "MWD_ROOTED_SECONDS",
    "MWD_SECOND_SECONDS",
    "MWD_TINY_SECONDS",
    "ITC2007QualityTailEligibility",
    "ITC2007QualityTailResult",
    "ITC2007QualityTailTelemetry",
    "MAX_STABILITY_CALLS",
    "QUALITY_TAIL_ACTIVITY_LIMIT",
    "ROOM_CP_SECONDS",
    "STABILITY_CALL_SECONDS",
    "STABILITY_FRONTIER_ACTIVITIES",
    "STABILITY_FRONTIER_COURSES",
    "STABILITY_MINIMUM_SECONDS",
    "itc2007_quality_tail_eligibility",
    "optimize_itc2007_quality_tail",
]
