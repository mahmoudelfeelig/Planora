from __future__ import annotations

"""Deterministic isolated-curriculum and minimum-day adjacency descent.

The operator derives every candidate from the incumbent representation.  An
isolated curriculum lecture admits moves that place either the lecture or one
of its curriculum peers into an adjacent slot.  A minimum-working-days deficit
admits moves into missing days.  Feasible time moves are ranked in official
units together with incumbent-majority room support, then one exact per-period
room matching and an independently validated official rescore form the atomic
acceptance boundary.
"""

import copy
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from benchmarks.itc2007 import (
    ITC2007Score,
    canonicalize_itc2007_schedule,
    score_itc2007_instance_schedule,
)
from core.itc2007_feedback_search import (
    _install_actual_majorities,
    _majority_aware_room_lift,
)
from core.projected_time_search import (
    _ITCProjectedState,
    _fast_coordinate_room_lift,
    itc2007_fixed_time_room_cp_eligibility,
)
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]

DEFAULT_MAX_MOVES = 24
MINIMUM_COMPLETION_RESERVE_SECONDS = 0.08
DEFAULT_COMPLETION_RESERVE_SECONDS = 0.09
_ROOT_SCAN_BASE_SECONDS = 0.004
_ROOT_SCAN_SECONDS_PER_TARGET = 0.000_060
_ROOT_SCAN_OBSERVED_SAFETY_FACTOR = 1.35


@dataclass(frozen=True)
class RootedAdjacencyEligibility:
    """Exact admission result for exchangeable imported ITC-2007 lectures."""

    eligible: bool
    reasons: tuple[str, ...]
    canonical_schedule: Schedule | None


@dataclass(frozen=True)
class RootedAdjacencyMove:
    activity_id: int
    course_code: str
    source_period: int
    target_period: int
    time_delta: int
    room_support_delta: int
    scalar_delta: int
    projected_score: int
    room_support_score: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RootedAdjacencyTelemetry:
    seed: int
    canonicalized_input: bool = False
    root_iterations_started: int = 0
    root_iterations: int = 0
    root_iterations_discarded: int = 0
    root_activities_considered: int = 0
    target_periods_considered: int = 0
    candidates_evaluated: int = 0
    accepted_moves: int = 0
    completed_checkpoint_moves: int = 0
    initial_projected_score: int | None = None
    initial_room_support_score: int | None = None
    final_projected_score: int | None = None
    final_room_support_score: int | None = None
    lift_status: str = "not_started"
    coordinate_status: str = "not_started"
    termination_reason: str = "not_started"
    validation_calls: int = 0
    independent_rescores: int = 0
    estimated_next_scan_seconds: float | None = None
    max_completed_scan_seconds: float = 0.0
    iteration_trace: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    timing: dict[str, float | int | bool | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RootedAdjacencyResult:
    status: str
    schedule: Schedule
    improved: bool
    initial_score: ITC2007Score | None
    final_score: ITC2007Score | None
    telemetry: RootedAdjacencyTelemetry
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


def _copy_schedule(
    schedule: Mapping[int, Mapping[str, Any]],
) -> Schedule:
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


def itc2007_rooted_adjacency_eligibility(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
) -> RootedAdjacencyEligibility:
    """Fail closed unless the rooted operator can canonicalize lecture ids.

    Fixed-time room optimization can safely admit some enriched instances
    because it does not exchange activity identities.  Rooted time search does
    exchange synthetic lecture ids within a course, so its admission boundary
    must additionally satisfy the importer's strict canonicalization contract.
    The returned canonical schedule is the exact representation the optimizer
    must use, preventing service admission and helper execution from drifting.
    """

    eligible, raw_reasons = itc2007_fixed_time_room_cp_eligibility(inst, schedule)
    reasons = [str(value) for value in raw_reasons]
    if not eligible:
        return RootedAdjacencyEligibility(
            eligible=False,
            reasons=tuple(dict.fromkeys(reasons)),
            canonical_schedule=None,
        )
    try:
        canonical = canonicalize_itc2007_schedule(inst, _copy_schedule(schedule))
    except Exception:
        reasons.append("itc2007_lectures_not_exchangeable")
        return RootedAdjacencyEligibility(
            eligible=False,
            reasons=tuple(dict.fromkeys(reasons)),
            canonical_schedule=None,
        )
    return RootedAdjacencyEligibility(
        eligible=True,
        reasons=(),
        canonical_schedule=canonical,
    )


def _adjacent_periods(
    period: int,
    *,
    slots_per_day: int,
) -> tuple[int, ...]:
    day = int(period) // int(slots_per_day)
    return tuple(
        candidate
        for candidate in (int(period) - 1, int(period) + 1)
        if candidate >= 0 and candidate // int(slots_per_day) == int(day)
    )


def _rooted_target_periods(
    state: _ITCProjectedState,
) -> dict[int, tuple[int, ...]]:
    """Return deterministic representation-derived activity/period targets."""

    targets: dict[int, set[int]] = defaultdict(set)
    for (curriculum, day), penalty in sorted(state.curriculum_day_penalty.items()):
        if int(penalty) <= 0:
            continue
        members = tuple(sorted(state.events_by_curriculum[curriculum]))
        occupied = {
            int(state.assignment[activity_id])
            for activity_id in members
            if (int(state.assignment[activity_id]) // state.slots_per_day == int(day))
        }
        for activity_id in members:
            period = int(state.assignment[activity_id])
            if period // state.slots_per_day != int(day):
                continue
            slot = period % state.slots_per_day
            isolated = bool(
                (slot == 0 or period - 1 not in occupied)
                and (slot + 1 >= state.slots_per_day or period + 1 not in occupied)
            )
            if not isolated:
                continue

            # A curriculum peer may move next to the isolated lecture.
            for member in members:
                targets[int(member)].update(
                    _adjacent_periods(
                        period,
                        slots_per_day=state.slots_per_day,
                    )
                )

            # Or the isolated lecture may move next to any curriculum peer.
            for other in members:
                other_period = int(state.assignment[other])
                targets[int(activity_id)].update(
                    _adjacent_periods(
                        other_period,
                        slots_per_day=state.slots_per_day,
                    )
                )

    for code, penalty in sorted(state.course_penalty.items()):
        if int(penalty) <= 0:
            continue
        activities = tuple(sorted(state.events_by_course[code]))
        used_days = {
            int(state.assignment[activity_id]) // state.slots_per_day
            for activity_id in activities
        }
        missing_days = sorted(set(range(len(state.inst.days))) - used_days)
        for activity_id in activities:
            for day in missing_days:
                targets[int(activity_id)].update(
                    range(
                        int(day) * state.slots_per_day,
                        (int(day) + 1) * state.slots_per_day,
                    )
                )

    return {
        int(activity_id): tuple(sorted(int(period) for period in periods))
        for activity_id, periods in sorted(targets.items())
        if periods
    }


def _estimated_root_scan_seconds(
    target_count: int,
    completed_scans: Sequence[tuple[int, float]],
) -> float:
    """Estimate one complete deterministic frontier scan with headroom."""

    count = max(1, int(target_count))
    structural_floor = float(
        _ROOT_SCAN_BASE_SECONDS + count * _ROOT_SCAN_SECONDS_PER_TARGET
    )
    if not completed_scans:
        return structural_floor
    observed_scaled = max(
        float(elapsed_seconds)
        * float(count)
        / float(max(1, int(completed_target_count)))
        for completed_target_count, elapsed_seconds in completed_scans[-4:]
    )
    return max(
        structural_floor,
        float(observed_scaled) * _ROOT_SCAN_OBSERVED_SAFETY_FACTOR,
    )


def optimize_itc2007_rooted_adjacency(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float,
    seed: int = 0,
    max_moves: int = DEFAULT_MAX_MOVES,
    completion_reserve_seconds: float = DEFAULT_COMPLETION_RESERVE_SECONDS,
    coordinate_room_sweeps: int = 16,
    validator: Validator | None = None,
) -> RootedAdjacencyResult:
    """Run an atomic rooted time descent and exact room-support lift.

    No intermediate schedule is exposed.  The complete lifted candidate must
    finish before the absolute deadline, pass the independent validator, and
    strictly improve a fresh official-component rescore or the exact incumbent
    is returned.
    """

    started = time.perf_counter()
    original = _copy_schedule(schedule) if isinstance(schedule, Mapping) else {}
    telemetry = RootedAdjacencyTelemetry(seed=int(seed))
    validation_fn = validator or _default_validator
    initial_score: ITC2007Score | None = None
    candidate_score: ITC2007Score | None = None
    candidate: Schedule | None = None
    effective_completion_reserve = max(
        MINIMUM_COMPLETION_RESERVE_SECONDS,
        max(0.0, float(completion_reserve_seconds)),
    )
    search_deadline = max(
        float(started),
        float(deadline) - float(effective_completion_reserve),
    )

    def finish(
        status: str,
        *,
        validation_errors: Sequence[str] = (),
        eligibility_reasons: Sequence[str] = (),
        error: str | None = None,
        helper_exhausted: bool = False,
    ) -> RootedAdjacencyResult:
        finished = time.perf_counter()
        overrun = max(0.0, float(finished) - float(deadline))
        improvement_ready = bool(
            candidate is not None
            and initial_score is not None
            and candidate_score is not None
            and int(candidate_score.total) < int(initial_score.total)
        )
        improvement_admissible = bool(
            improvement_ready
            and not bool(helper_exhausted)
            and overrun == 0.0
            and finished < float(deadline)
        )
        selected = _copy_schedule(
            candidate if improvement_admissible and candidate is not None else original
        )
        finished = time.perf_counter()
        overrun = max(0.0, float(finished) - float(deadline))
        improved = bool(
            improvement_admissible and overrun == 0.0 and finished < float(deadline)
        )
        if improvement_admissible and not improved:
            selected = _copy_schedule(original)
            finished = time.perf_counter()
            overrun = max(0.0, float(finished) - float(deadline))
        telemetry.timing = {
            "started_at_seconds": float(started),
            "search_deadline_seconds": float(search_deadline),
            "absolute_deadline_seconds": float(deadline),
            "finished_at_seconds": float(finished),
            "elapsed_seconds": float(finished - started),
            "budget_seconds": max(0.0, float(deadline) - float(started)),
            "completion_reserve_seconds": float(effective_completion_reserve),
            "deadline_remaining_seconds": max(0.0, float(deadline) - float(finished)),
            "deadline_overrun_seconds": float(overrun),
        }
        deadline_failed = bool(
            helper_exhausted or overrun > 0.0 or finished >= float(deadline)
        )
        effective_status = "deadline_exhausted" if deadline_failed else str(status)
        return RootedAdjacencyResult(
            status=effective_status,
            schedule=selected,
            improved=bool(improved),
            initial_score=initial_score,
            final_score=candidate_score if improved else initial_score,
            telemetry=telemetry,
            validation_errors=tuple(str(value) for value in validation_errors)[:20],
            eligibility_reasons=tuple(str(value) for value in eligibility_reasons),
            deadline_exhausted=bool(
                deadline_failed or effective_status == "deadline_exhausted"
            ),
            deadline_overrun_seconds=float(overrun),
            error=error,
        )

    try:
        if time.perf_counter() >= float(deadline):
            telemetry.termination_reason = "deadline_before_validation"
            return finish("deadline_exhausted", helper_exhausted=True)
        if (
            int(max_moves) < 1
            or float(completion_reserve_seconds) < 0.0
            or int(coordinate_room_sweeps) < 1
        ):
            return finish(
                "ineligible",
                eligibility_reasons=("invalid_search_bounds",),
            )
        eligibility = itc2007_rooted_adjacency_eligibility(
            inst,
            original,
        )
        if not eligibility.eligible or eligibility.canonical_schedule is None:
            return finish(
                "ineligible",
                eligibility_reasons=eligibility.reasons,
            )
        canonical = eligibility.canonical_schedule
        telemetry.canonicalized_input = bool(canonical != original)
        if time.perf_counter() >= float(deadline):
            telemetry.termination_reason = "deadline_during_eligibility"
            return finish("deadline_exhausted", helper_exhausted=True)

        telemetry.validation_calls += 1
        incumbent_errors = tuple(str(value) for value in validation_fn(inst, original))
        if time.perf_counter() >= float(deadline):
            telemetry.termination_reason = "deadline_during_validation"
            return finish("deadline_exhausted", helper_exhausted=True)
        if incumbent_errors:
            return finish(
                "invalid_incumbent",
                validation_errors=incumbent_errors,
            )

        initial_score = score_itc2007_instance_schedule(inst, original)
        telemetry.independent_rescores += 1
        state = _ITCProjectedState(inst, canonical, seed=int(seed))
        primary_rooms = _install_actual_majorities(state, canonical)
        telemetry.initial_projected_score = int(state.score)
        telemetry.initial_room_support_score = int(state.stability_proxy)

        available = max(0.0, float(deadline) - time.perf_counter())
        reserve = float(effective_completion_reserve)
        if available <= float(reserve):
            telemetry.termination_reason = "insufficient_completion_reserve"
            return finish("no_improvement")
        telemetry.termination_reason = "local_optimum"
        completed_scans: list[tuple[int, float]] = []

        for iteration in range(1, int(max_moves) + 1):
            telemetry.root_iterations_started += 1
            iteration_started = time.perf_counter()
            target_map = _rooted_target_periods(state)
            target_count = sum(len(periods) for periods in target_map.values())
            scan_estimate = _estimated_root_scan_seconds(
                int(target_count),
                completed_scans,
            )
            telemetry.estimated_next_scan_seconds = float(scan_estimate)
            admission_checked = time.perf_counter()
            iteration_row: dict[str, Any] = {
                "iteration": int(iteration),
                "target_activities": int(len(target_map)),
                "target_periods": int(target_count),
                "estimated_scan_seconds": float(scan_estimate),
                "remaining_before_scan_seconds": max(
                    0.0,
                    float(search_deadline) - float(admission_checked),
                ),
            }
            if not target_map:
                telemetry.termination_reason = "no_rooted_penalties"
                iteration_row["status"] = "no_rooted_penalties"
                telemetry.iteration_trace.append(iteration_row)
                break
            if float(admission_checked) + float(scan_estimate) > float(search_deadline):
                telemetry.termination_reason = "checkpoint_reserve_reached"
                iteration_row["status"] = "not_started_reserve"
                telemetry.iteration_trace.append(iteration_row)
                break

            chosen: (
                tuple[
                    tuple[int, int, int, int, int],
                    int,
                    int,
                    int,
                    int,
                    int,
                    int,
                ]
                | None
            ) = None
            scan_started = time.perf_counter()
            scan_candidates = 0
            for activity_id, target_periods in target_map.items():
                source_period = int(state.assignment[activity_id])
                for target_period in target_periods:
                    if int(target_period) == int(source_period):
                        continue
                    move = {int(activity_id): int(target_period)}
                    if not state.feasible(move):
                        continue
                    time_delta = int(state.delta(move))
                    support_delta = int(state.stability_proxy_delta(move))
                    scalar_delta = int(time_delta + support_delta)
                    key = (
                        int(scalar_delta),
                        int(time_delta),
                        int(support_delta),
                        int(activity_id),
                        int(target_period),
                    )
                    scan_candidates += 1
                    row = (
                        key,
                        int(activity_id),
                        int(source_period),
                        int(target_period),
                        int(time_delta),
                        int(support_delta),
                        int(scalar_delta),
                    )
                    if chosen is None or key < chosen[0]:
                        chosen = row

            scan_finished = time.perf_counter()
            scan_elapsed = float(scan_finished) - float(scan_started)
            completed_scans.append((int(target_count), float(scan_elapsed)))
            telemetry.root_iterations += 1
            telemetry.root_activities_considered += len(target_map)
            telemetry.target_periods_considered += int(target_count)
            telemetry.candidates_evaluated += int(scan_candidates)
            telemetry.max_completed_scan_seconds = max(
                float(telemetry.max_completed_scan_seconds),
                float(scan_elapsed),
            )
            iteration_row.update(
                {
                    "scan_elapsed_seconds": float(scan_elapsed),
                    "candidates_evaluated": int(scan_candidates),
                    "completed_at_seconds": float(scan_finished),
                }
            )
            if float(scan_finished) > float(search_deadline):
                telemetry.root_iterations_discarded += 1
                telemetry.termination_reason = "completed_scan_reserve_reached"
                iteration_row["status"] = "completed_not_applied_reserve"
                telemetry.iteration_trace.append(iteration_row)
                break
            if chosen is None or int(chosen[-1]) >= 0:
                telemetry.termination_reason = "rooted_local_optimum"
                iteration_row["status"] = "local_optimum"
                telemetry.iteration_trace.append(iteration_row)
                break

            (
                _key,
                activity_id,
                source_period,
                target_period,
                time_delta,
                support_delta,
                scalar_delta,
            ) = chosen
            state.apply({int(activity_id): int(target_period)})
            telemetry.accepted_moves += 1
            telemetry.completed_checkpoint_moves = int(telemetry.accepted_moves)
            iteration_row.update(
                {
                    "status": "accepted_checkpoint",
                    "activity_id": int(activity_id),
                    "target_period": int(target_period),
                    "elapsed_seconds": float(
                        time.perf_counter() - float(iteration_started)
                    ),
                }
            )
            telemetry.iteration_trace.append(iteration_row)
            telemetry.trace.append(
                RootedAdjacencyMove(
                    activity_id=int(activity_id),
                    course_code=str(state.course_code[activity_id]),
                    source_period=int(source_period),
                    target_period=int(target_period),
                    time_delta=int(time_delta),
                    room_support_delta=int(support_delta),
                    scalar_delta=int(scalar_delta),
                    projected_score=int(state.score),
                    room_support_score=int(state.stability_proxy),
                ).to_dict()
            )
        else:
            telemetry.termination_reason = "move_limit"

        telemetry.final_projected_score = int(state.score)
        telemetry.final_room_support_score = int(state.stability_proxy)
        if telemetry.accepted_moves <= 0:
            return finish("no_improvement")

        lifted, lift_status = _majority_aware_room_lift(
            inst,
            state.materialize(),
            primary_rooms,
            deadline=float(deadline),
        )
        telemetry.lift_status = str(lift_status)
        if lifted is None or str(lift_status) == "deadline_exhausted":
            telemetry.termination_reason = "room_lift_deadline_exhausted"
            return finish("deadline_exhausted", helper_exhausted=True)

        candidate, coordinate_status = _fast_coordinate_room_lift(
            inst,
            lifted,
            deadline=float(deadline),
            max_sweeps=int(coordinate_room_sweeps),
        )
        telemetry.coordinate_status = str(coordinate_status)
        if str(coordinate_status) == "deadline_exhausted":
            telemetry.termination_reason = "coordinate_lift_deadline_exhausted"
            candidate = None
            return finish("deadline_exhausted", helper_exhausted=True)
        if time.perf_counter() >= float(deadline):
            telemetry.termination_reason = "deadline_before_acceptance"
            candidate = None
            return finish("deadline_exhausted", helper_exhausted=True)

        telemetry.validation_calls += 1
        candidate_errors = tuple(str(value) for value in validation_fn(inst, candidate))
        if time.perf_counter() >= float(deadline):
            telemetry.termination_reason = "deadline_during_candidate_validation"
            candidate = None
            return finish("deadline_exhausted", helper_exhausted=True)
        if candidate_errors:
            candidate = None
            return finish(
                "invalid_candidate",
                validation_errors=candidate_errors,
            )

        candidate_score = score_itc2007_instance_schedule(inst, candidate)
        telemetry.independent_rescores += 1
        if time.perf_counter() >= float(deadline):
            telemetry.termination_reason = "deadline_during_official_rescore"
            candidate = None
            return finish("deadline_exhausted", helper_exhausted=True)
        if int(candidate_score.total) >= int(initial_score.total):
            candidate = None
            return finish("no_improvement")
        telemetry.termination_reason = "strict_official_improvement"
        return finish("improved")
    except Exception as exc:
        candidate = None
        return finish("error", error=f"{type(exc).__name__}:{exc}")


__all__ = [
    "RootedAdjacencyEligibility",
    "RootedAdjacencyMove",
    "RootedAdjacencyResult",
    "RootedAdjacencyTelemetry",
    "itc2007_rooted_adjacency_eligibility",
    "optimize_itc2007_rooted_adjacency",
]
