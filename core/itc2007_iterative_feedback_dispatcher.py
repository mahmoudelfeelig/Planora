from __future__ import annotations

import copy
import math
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from benchmarks.itc2007 import (
    ITC2007Score,
    canonicalize_itc2007_schedule,
    score_itc2007_instance_schedule,
)
from core.itc2007_compound_search import _CompoundState
from core.itc2007_feedback_search import (
    _majority_aware_room_lift,
    _run_feedback_round,
)
from core.itc2007_rooted_adjacency import (
    itc2007_rooted_adjacency_eligibility,
)
from core.projected_time_search import (
    _fast_coordinate_room_lift,
)
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]
RootMode = Literal["time", "components"]
MutationStage = Literal["validator", "scorer"]

_DETERMINISTIC_FEEDBACK_TERMINATIONS = frozenset(
    {"iteration_checkpoint", "local_optimum", "no_candidates", "stagnation"}
)


@dataclass(frozen=True)
class IterativeFeedbackBounds:
    """Fixed work checkpoints and reserves for the deterministic dispatcher."""

    feedback_rounds: int = 5
    feedback_iterations_per_round: int = 32
    candidate_batch_size: int = 20
    history_length: int = 128
    stagnation_limit: int = 180
    coordinate_room_sweeps: int = 5
    time_rooted_relocations: int = 7
    component_rooted_relocations: int = 2
    stability_collision_weight: int = 1
    stability_proxy_mode: str = "collision_events"
    feedback_search_reserve_seconds: float = 0.38
    majority_lift_reserve_seconds: float = 0.34
    coordinate_lift_reserve_seconds: float = 0.31
    feedback_acceptance_reserve_seconds: float = 0.30
    relocation_search_reserve_seconds: float = 0.005
    relocation_acceptance_reserve_seconds: float = 0.002

    def validation_errors(self) -> tuple[str, ...]:
        integer_bounds = {
            "feedback_rounds": self.feedback_rounds,
            "feedback_iterations_per_round": self.feedback_iterations_per_round,
            "candidate_batch_size": self.candidate_batch_size,
            "history_length": self.history_length,
            "stagnation_limit": self.stagnation_limit,
            "coordinate_room_sweeps": self.coordinate_room_sweeps,
            "time_rooted_relocations": self.time_rooted_relocations,
            "component_rooted_relocations": self.component_rooted_relocations,
        }
        errors = [
            f"negative_bound:{name}"
            for name, value in integer_bounds.items()
            if int(value) < 0
        ]
        if int(self.stability_collision_weight) < 1:
            errors.append("nonpositive_bound:stability_collision_weight")
        if str(self.stability_proxy_mode) not in {
            "collision_events",
            "fragmented_courses",
        }:
            errors.append("invalid_stability_proxy_mode")
        for name in (
            "feedback_iterations_per_round",
            "candidate_batch_size",
            "history_length",
            "stagnation_limit",
            "coordinate_room_sweeps",
        ):
            if int(integer_bounds[name]) == 0:
                errors.append(f"zero_bound:{name}")

        reserves = (
            ("feedback_search", self.feedback_search_reserve_seconds),
            ("majority_lift", self.majority_lift_reserve_seconds),
            ("coordinate_lift", self.coordinate_lift_reserve_seconds),
            ("feedback_acceptance", self.feedback_acceptance_reserve_seconds),
            ("relocation_search", self.relocation_search_reserve_seconds),
            ("relocation_acceptance", self.relocation_acceptance_reserve_seconds),
        )
        for name, value in reserves:
            if not math.isfinite(float(value)) or float(value) < 0:
                errors.append(f"invalid_reserve:{name}")
        if all(math.isfinite(float(value)) for _name, value in reserves):
            values = tuple(float(value) for _name, value in reserves)
            if any(left < right for left, right in zip(values, values[1:])):
                errors.append("reserves_not_monotone")
        return tuple(errors)


@dataclass(frozen=True)
class IterativeFeedbackEligibility:
    eligible: bool
    reasons: tuple[str, ...]
    canonical_schedule: Schedule | None


@dataclass
class IterativeFeedbackTelemetry:
    seed: int
    bounds: dict[str, Any]
    feedback_rounds_completed: int = 0
    feedback_rounds_accepted: int = 0
    relocation_moves_accepted: int = 0
    canonicalizations: int = 0
    independent_rescores: int = 0
    validation_calls: int = 0
    mutation_guard_failures: int = 0
    round_trace: list[dict[str, Any]] = field(default_factory=list)
    relocation_trace: list[dict[str, Any]] = field(default_factory=list)
    timing: dict[str, float | int | bool | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IterativeFeedbackResult:
    status: str
    schedule: Schedule
    improved: bool
    initial_score: ITC2007Score | None
    final_score: ITC2007Score | None
    telemetry: IterativeFeedbackTelemetry
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
                else int(self.initial_score.total - self.final_score.total)
            ),
            "validation_errors": list(self.validation_errors),
            "eligibility_reasons": list(self.eligibility_reasons),
            "deadline_exhausted": bool(self.deadline_exhausted),
            "deadline_overrun_seconds": float(self.deadline_overrun_seconds),
            "telemetry": self.telemetry.to_dict(),
            "error": self.error,
        }


@dataclass(frozen=True)
class _RelocationCandidate:
    schedule: Schedule
    predicted_score: ITC2007Score
    checks: int
    rooted_activities: int
    activity_id: int
    source_period: int
    target_period: int
    source_room: int
    target_room: int


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


def itc2007_iterative_feedback_eligibility(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
) -> IterativeFeedbackEligibility:
    """Admit only lossless imports with exchangeable canonical lectures."""

    rooted = itc2007_rooted_adjacency_eligibility(inst, schedule)
    return IterativeFeedbackEligibility(
        eligible=bool(rooted.eligible),
        reasons=tuple(str(value) for value in rooted.reasons),
        canonical_schedule=rooted.canonical_schedule,
    )


def _course_is_rooted(
    state: _CompoundState,
    course_code: str,
    *,
    bad_curricula: set[str],
    root_mode: RootMode,
) -> bool:
    minimum_days, stability = state.base_course_terms[str(course_code)]
    if int(minimum_days) > 0:
        return True
    if state.curricula_by_course[str(course_code)] & bad_curricula:
        return True
    if root_mode == "time":
        return False
    if int(stability) > 0:
        return True
    return any(
        int(state.base_capacity_by_index[index]) > 0
        for index in state.indexes_by_course[str(course_code)]
    )


def _best_rooted_relocation(
    inst: Instance,
    schedule: Schedule,
    *,
    root_mode: RootMode,
    deadline: float,
) -> tuple[_RelocationCandidate | None, str, int, int]:
    state = _CompoundState(inst, schedule)
    periods, rooms, by_period = state.arrays({}, {})
    occupancy = {
        (int(periods[index]), int(rooms[index])): int(index)
        for index in range(len(periods))
    }
    bad_curricula = {
        str(curriculum)
        for curriculum, penalty in state.base_curriculum_terms.items()
        if int(penalty) > 0
    }
    best: (
        tuple[
            tuple[int, int, int, int, int, int, int],
            Schedule,
            ITC2007Score,
            int,
            int,
            int,
            int,
            int,
        ]
        | None
    ) = None
    checks = 0
    rooted_activities = 0

    for index in range(len(state.activity_ids)):
        if time.perf_counter() >= float(deadline):
            return None, "deadline_exhausted", checks, rooted_activities
        source_period = int(periods[index])
        source_room = int(rooms[index])
        course_code = str(state.course_code[index])
        if not _course_is_rooted(
            state,
            course_code,
            bad_curricula=bad_curricula,
            root_mode=root_mode,
        ):
            continue
        rooted_activities += 1
        room_support = Counter(
            int(rooms[other]) for other in state.indexes_by_course[course_code]
        )
        for target_period in range(state.period_count):
            if (
                target_period == source_period
                or target_period in state.forbidden[index]
                or any(
                    other in state.conflicts[index]
                    for other in by_period[target_period]
                )
            ):
                continue
            available_rooms = [
                int(room_id)
                for room_id in state.room_capacity
                if (int(target_period), int(room_id)) not in occupancy
            ]
            available_rooms.sort(
                key=lambda room_id: (
                    state.capacity_contribution(index, room_id),
                    0 if room_support[room_id] else 1,
                    0 if int(room_id) == source_room else 1,
                    int(room_id),
                )
            )
            for target_room in available_rooms[:2]:
                if time.perf_counter() >= float(deadline):
                    return None, "deadline_exhausted", checks, rooted_activities
                checks += 1
                period_override = {int(index): int(target_period)}
                room_override = (
                    {int(index): int(target_room)}
                    if int(target_room) != source_room
                    else {}
                )
                predicted = state.score_overrides(period_override, room_override)
                key = (
                    int(predicted.total),
                    int(predicted.minimum_working_days),
                    int(predicted.curriculum_compactness),
                    int(predicted.room_stability),
                    int(index),
                    int(target_period),
                    int(target_room),
                )
                if int(predicted.total) >= int(state.initial_score.total):
                    continue
                if best is None or key < best[0]:
                    best = (
                        key,
                        state.materialize(period_override, room_override),
                        predicted,
                        int(state.activity_ids[index]),
                        int(source_period),
                        int(target_period),
                        int(source_room),
                        int(target_room),
                    )

    if best is None:
        return None, "local_optimum", checks, rooted_activities
    (
        _key,
        candidate,
        predicted,
        activity_id,
        source_period,
        target_period,
        source_room,
        target_room,
    ) = best
    return (
        _RelocationCandidate(
            schedule=candidate,
            predicted_score=predicted,
            checks=int(checks),
            rooted_activities=int(rooted_activities),
            activity_id=int(activity_id),
            source_period=int(source_period),
            target_period=int(target_period),
            source_room=int(source_room),
            target_room=int(target_room),
        ),
        "candidate",
        checks,
        rooted_activities,
    )


def optimize_itc2007_iterative_feedback(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float,
    seed: int = 0,
    bounds: IterativeFeedbackBounds | None = None,
    validator: Validator | None = None,
) -> IterativeFeedbackResult:
    """Run deterministic feedback checkpoints and exact rooted relocation.

    The dispatcher deliberately uses fixed iteration and move quotas. A
    deadline that interrupts one of those checkpoints discards the entire
    candidate chain, so CPU timing cannot select a partially explored basin.
    Every accepted schedule is canonicalized, fully validated, independently
    rescored, and compared against the exact incremental prediction when one
    exists.
    """

    started = time.perf_counter()
    original = _copy_schedule(schedule) if isinstance(schedule, Mapping) else {}
    active_bounds = bounds or IterativeFeedbackBounds()
    telemetry = IterativeFeedbackTelemetry(
        seed=int(seed),
        bounds=asdict(active_bounds),
    )
    validation_fn = validator or _default_validator
    initial_score: ITC2007Score | None = None
    current_score: ITC2007Score | None = None

    def finish(
        status: str,
        *,
        current: Schedule | None = None,
        allow_current: bool = False,
        validation_errors: Sequence[str] = (),
        eligibility_reasons: Sequence[str] = (),
        error: str | None = None,
    ) -> IterativeFeedbackResult:
        nonlocal current_score
        finished = time.perf_counter()
        deadline_missed = finished >= float(deadline)
        if deadline_missed:
            status = "deadline_exhausted"
            allow_current = False
        improved = bool(
            allow_current
            and current is not None
            and initial_score is not None
            and current_score is not None
            and current_score.total < initial_score.total
        )
        selected = _copy_schedule(
            current if improved and current is not None else original
        )
        finished = time.perf_counter()
        if improved and finished >= float(deadline):
            status = "deadline_exhausted"
            improved = False
            selected = _copy_schedule(original)
            finished = time.perf_counter()
        deadline_missed = finished >= float(deadline)
        selected_score = current_score if improved else initial_score
        telemetry.timing = {
            "elapsed_seconds": float(finished - started),
            "budget_seconds": float(deadline) - float(started),
            "deadline_remaining_seconds": max(0.0, float(deadline) - finished),
            "deadline_overrun_seconds": max(0.0, finished - float(deadline)),
        }
        return IterativeFeedbackResult(
            status=str(status),
            schedule=selected,
            improved=improved,
            initial_score=initial_score,
            final_score=selected_score,
            telemetry=telemetry,
            validation_errors=tuple(str(value) for value in validation_errors)[:20],
            eligibility_reasons=tuple(str(value) for value in eligibility_reasons),
            deadline_exhausted=bool(
                deadline_missed or str(status) == "deadline_exhausted"
            ),
            deadline_overrun_seconds=max(0.0, finished - float(deadline)),
            error=error,
        )

    def canonicalize(candidate: Schedule) -> Schedule:
        output = canonicalize_itc2007_schedule(inst, candidate)
        telemetry.canonicalizations += 1
        return output

    def validate_and_score(
        candidate: Schedule,
    ) -> tuple[ITC2007Score | None, tuple[str, ...], MutationStage | None]:
        snapshot = _copy_schedule(candidate)
        telemetry.validation_calls += 1
        errors = tuple(str(value) for value in validation_fn(inst, candidate))
        if candidate != snapshot:
            telemetry.mutation_guard_failures += 1
            return None, errors, "validator"
        if errors:
            return None, errors, None
        score = score_itc2007_instance_schedule(inst, candidate)
        telemetry.independent_rescores += 1
        if candidate != snapshot:
            telemetry.mutation_guard_failures += 1
            return None, (), "scorer"
        return score, errors, None

    try:
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        bound_errors = active_bounds.validation_errors()
        if bound_errors:
            return finish("ineligible", eligibility_reasons=bound_errors)
        eligibility = itc2007_iterative_feedback_eligibility(inst, original)
        if not eligibility.eligible or eligibility.canonical_schedule is None:
            return finish(
                "ineligible",
                eligibility_reasons=eligibility.reasons,
            )
        current = eligibility.canonical_schedule
        telemetry.canonicalizations += 1
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        incumbent = _copy_schedule(original)
        initial_score, incumbent_errors, incumbent_mutation_stage = validate_and_score(
            incumbent
        )
        if incumbent_mutation_stage is not None:
            return finish(
                "mutation_detected",
                error=f"{incumbent_mutation_stage}_mutated_incumbent",
            )
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        if incumbent_errors or initial_score is None:
            return finish(
                "invalid_incumbent",
                validation_errors=incumbent_errors,
            )
        current_score = initial_score

        for round_index in range(int(active_bounds.feedback_rounds)):
            current = canonicalize(current)
            search_deadline = float(deadline) - float(
                active_bounds.feedback_search_reserve_seconds
            )
            if time.perf_counter() >= search_deadline:
                return finish("deadline_exhausted")
            round_started = time.perf_counter()
            timed, round_info = _run_feedback_round(
                inst,
                current,
                deadline=search_deadline,
                seed=int(seed) + 65_537 * (round_index + 1),
                candidate_batch_size=int(active_bounds.candidate_batch_size),
                history_length=int(active_bounds.history_length),
                stagnation_limit=int(active_bounds.stagnation_limit),
                iteration_limit=int(active_bounds.feedback_iterations_per_round),
                stability_collision_weight=int(
                    active_bounds.stability_collision_weight
                ),
                stability_proxy_mode=str(active_bounds.stability_proxy_mode),
            )
            termination = str(round_info.get("termination_reason", ""))
            iterations = int(round_info.get("iterations", 0))
            checkpoint_complete = bool(
                termination in _DETERMINISTIC_FEEDBACK_TERMINATIONS
                and (
                    termination != "iteration_checkpoint"
                    or iterations == int(active_bounds.feedback_iterations_per_round)
                )
            )
            trace = {
                "round": int(round_index + 1),
                "iterations": iterations,
                "iteration_quota": int(active_bounds.feedback_iterations_per_round),
                "termination_reason": termination,
                "checkpoint_complete": checkpoint_complete,
                "accepted_moves": int(round_info.get("accepted_moves", 0)),
                "candidates_evaluated": int(round_info.get("candidates_evaluated", 0)),
            }
            telemetry.round_trace.append(trace)
            if not checkpoint_complete or time.perf_counter() >= search_deadline:
                trace["status"] = "incomplete_checkpoint"
                return finish("deadline_exhausted")
            telemetry.feedback_rounds_completed += 1

            lift_deadline = float(deadline) - float(
                active_bounds.majority_lift_reserve_seconds
            )
            lifted, lift_status = _majority_aware_room_lift(
                inst,
                timed,
                round_info["primary_rooms"],
                deadline=lift_deadline,
            )
            trace["lift_status"] = str(lift_status)
            if (
                lifted is None
                or str(lift_status) == "deadline_exhausted"
                or time.perf_counter() >= lift_deadline
            ):
                trace["status"] = "incomplete_room_lift"
                return finish("deadline_exhausted")

            coordinate_deadline = float(deadline) - float(
                active_bounds.coordinate_lift_reserve_seconds
            )
            candidate, coordinate_status = _fast_coordinate_room_lift(
                inst,
                lifted,
                deadline=coordinate_deadline,
                max_sweeps=int(active_bounds.coordinate_room_sweeps),
            )
            trace["coordinate_status"] = str(coordinate_status)
            if (
                str(coordinate_status) == "deadline_exhausted"
                or time.perf_counter() >= coordinate_deadline
            ):
                trace["status"] = "incomplete_coordinate_lift"
                return finish("deadline_exhausted")

            candidate = canonicalize(candidate)
            candidate_score, candidate_errors, candidate_mutation_stage = (
                validate_and_score(candidate)
            )
            acceptance_deadline = float(deadline) - float(
                active_bounds.feedback_acceptance_reserve_seconds
            )
            if candidate_mutation_stage is not None:
                return finish(
                    "mutation_detected",
                    error=(f"{candidate_mutation_stage}_mutated_feedback_candidate"),
                )
            if time.perf_counter() >= acceptance_deadline:
                trace["status"] = "deadline_before_acceptance"
                return finish("deadline_exhausted")
            if candidate_errors or candidate_score is None:
                trace["status"] = "invalid_candidate"
                return finish(
                    "invalid_candidate",
                    validation_errors=candidate_errors,
                )
            trace["candidate_score"] = candidate_score.to_dict()
            trace["wall_seconds"] = float(time.perf_counter() - round_started)
            if candidate_score.total < current_score.total:
                current = candidate
                current_score = candidate_score
                telemetry.feedback_rounds_accepted += 1
                trace["status"] = "accepted"
            else:
                trace["status"] = "rejected"

        phases: tuple[tuple[RootMode, int], ...] = (
            ("time", int(active_bounds.time_rooted_relocations)),
            ("components", int(active_bounds.component_rooted_relocations)),
        )
        for root_mode, quota in phases:
            phase_completed = 0
            for move_index in range(quota):
                current = canonicalize(current)
                search_deadline = float(deadline) - float(
                    active_bounds.relocation_search_reserve_seconds
                )
                if time.perf_counter() >= search_deadline:
                    return finish("deadline_exhausted")
                move_started = time.perf_counter()
                relocation, relocation_status, checks, rooted_activities = (
                    _best_rooted_relocation(
                        inst,
                        current,
                        root_mode=root_mode,
                        deadline=search_deadline,
                    )
                )
                if relocation_status == "deadline_exhausted":
                    return finish("deadline_exhausted")
                if relocation is None:
                    telemetry.relocation_trace.append(
                        {
                            "phase": str(root_mode),
                            "move": int(move_index + 1),
                            "quota": int(quota),
                            "status": "local_optimum",
                            "checks": int(checks),
                            "rooted_activities": int(rooted_activities),
                        }
                    )
                    break

                candidate = canonicalize(relocation.schedule)
                candidate_score, candidate_errors, candidate_mutation_stage = (
                    validate_and_score(candidate)
                )
                acceptance_deadline = float(deadline) - float(
                    active_bounds.relocation_acceptance_reserve_seconds
                )
                if candidate_mutation_stage is not None:
                    return finish(
                        "mutation_detected",
                        error=(
                            f"{candidate_mutation_stage}_mutated_relocation_candidate"
                        ),
                    )
                if time.perf_counter() >= acceptance_deadline:
                    return finish("deadline_exhausted")
                if candidate_errors or candidate_score is None:
                    return finish(
                        "invalid_candidate",
                        validation_errors=candidate_errors,
                    )
                if candidate_score != relocation.predicted_score:
                    return finish(
                        "score_drift",
                        error="relocation_incremental_score_mismatch",
                    )
                if candidate_score.total >= current_score.total:
                    return finish(
                        "score_drift",
                        error="relocation_failed_strict_improvement",
                    )
                before = current_score
                current = candidate
                current_score = candidate_score
                telemetry.relocation_moves_accepted += 1
                phase_completed += 1
                telemetry.relocation_trace.append(
                    {
                        "phase": str(root_mode),
                        "move": int(move_index + 1),
                        "quota": int(quota),
                        "status": "accepted",
                        "before_score": before.to_dict(),
                        "after_score": candidate_score.to_dict(),
                        "checks": int(relocation.checks),
                        "rooted_activities": int(relocation.rooted_activities),
                        "relocation": {
                            "activity_id": int(relocation.activity_id),
                            "source_period": int(relocation.source_period),
                            "target_period": int(relocation.target_period),
                            "source_room": int(relocation.source_room),
                            "target_room": int(relocation.target_room),
                        },
                        "wall_seconds": float(time.perf_counter() - move_started),
                    }
                )
            telemetry.relocation_trace.append(
                {
                    "phase": str(root_mode),
                    "status": "checkpoint",
                    "quota": int(quota),
                    "completed_moves": int(phase_completed),
                }
            )

        if time.perf_counter() >= float(deadline) - float(
            active_bounds.relocation_acceptance_reserve_seconds
        ):
            return finish("deadline_exhausted")
        if current_score.total < initial_score.total:
            return finish("improved", current=current, allow_current=True)
        return finish("no_improvement", current=current, allow_current=True)
    except Exception as exc:
        return finish("error", error=f"{type(exc).__name__}:{exc}")


__all__ = [
    "IterativeFeedbackBounds",
    "IterativeFeedbackEligibility",
    "IterativeFeedbackResult",
    "IterativeFeedbackTelemetry",
    "itc2007_iterative_feedback_eligibility",
    "optimize_itc2007_iterative_feedback",
]
