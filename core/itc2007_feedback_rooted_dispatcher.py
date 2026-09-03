from __future__ import annotations

"""Atomic fixed-checkpoint feedback and rooted-adjacency dispatcher.

The policy composes two deterministic iterative-feedback checkpoints with one
rooted-adjacency checkpoint.  It derives every decision from the incumbent
representation: there are no instance names, benchmark scores, or target
thresholds.  Every hand-off is canonicalized, fully validated, independently
rescored, and guarded against mutation under one caller-owned absolute
deadline.  A late or incomplete checkpoint discards the entire chain.
"""

import copy
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from benchmarks.itc2007 import (
    ITC2007Score,
    canonicalize_itc2007_schedule,
    score_itc2007_instance_schedule,
)
from core.itc2007_iterative_feedback_dispatcher import (
    IterativeFeedbackBounds,
    IterativeFeedbackResult,
    itc2007_iterative_feedback_eligibility,
    optimize_itc2007_iterative_feedback,
)
from core.itc2007_rooted_adjacency import (
    RootedAdjacencyResult,
    optimize_itc2007_rooted_adjacency,
)
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]

_SEED_STRIDE = 65_537
_POST_FEEDBACK_SEED_OFFSET = 5
_DETERMINISTIC_FEEDBACK_TERMINATIONS = frozenset(
    {"iteration_checkpoint", "local_optimum", "no_candidates", "stagnation"}
)
_DETERMINISTIC_ROOTED_TERMINATIONS = frozenset({"local_optimum", "no_rooted_penalties"})


@dataclass(frozen=True)
class FeedbackRootedBounds:
    """Exact work quotas and absolute-deadline reserves for the dispatcher."""

    initial_feedback_rounds: int = 4
    post_feedback_rounds: int = 1
    feedback_iterations_per_round: int = 32
    candidate_batch_size: int = 20
    history_length: int = 128
    stagnation_limit: int = 180
    coordinate_room_sweeps: int = 5
    time_rooted_relocations: int = 2
    component_rooted_relocations: int = 2
    rooted_adjacency_moves: int = 8
    rooted_coordinate_room_sweeps: int = 4
    stability_collision_weight: int = 1
    stability_proxy_mode: str = "collision_events"
    initial_phase_tail_reserve_seconds: float = 0.50
    post_feedback_tail_reserve_seconds: float = 0.16
    final_validation_reserve_seconds: float = 0.02
    initial_feedback_search_reserve_seconds: float = 0.38
    initial_majority_lift_reserve_seconds: float = 0.34
    initial_coordinate_lift_reserve_seconds: float = 0.31
    initial_acceptance_reserve_seconds: float = 0.30
    initial_relocation_search_reserve_seconds: float = 0.005
    initial_relocation_acceptance_reserve_seconds: float = 0.002
    post_feedback_search_reserve_seconds: float = 0.12
    post_majority_lift_reserve_seconds: float = 0.10
    post_coordinate_lift_reserve_seconds: float = 0.08
    post_acceptance_reserve_seconds: float = 0.07
    post_relocation_search_reserve_seconds: float = 0.02
    post_relocation_acceptance_reserve_seconds: float = 0.01
    rooted_completion_reserve_seconds: float = 0.08

    def initial_bounds(self) -> IterativeFeedbackBounds:
        return IterativeFeedbackBounds(
            feedback_rounds=int(self.initial_feedback_rounds),
            feedback_iterations_per_round=int(self.feedback_iterations_per_round),
            candidate_batch_size=int(self.candidate_batch_size),
            history_length=int(self.history_length),
            stagnation_limit=int(self.stagnation_limit),
            coordinate_room_sweeps=int(self.coordinate_room_sweeps),
            time_rooted_relocations=int(self.time_rooted_relocations),
            component_rooted_relocations=int(self.component_rooted_relocations),
            stability_collision_weight=int(self.stability_collision_weight),
            stability_proxy_mode=str(self.stability_proxy_mode),
            feedback_search_reserve_seconds=float(
                self.initial_feedback_search_reserve_seconds
            ),
            majority_lift_reserve_seconds=float(
                self.initial_majority_lift_reserve_seconds
            ),
            coordinate_lift_reserve_seconds=float(
                self.initial_coordinate_lift_reserve_seconds
            ),
            feedback_acceptance_reserve_seconds=float(
                self.initial_acceptance_reserve_seconds
            ),
            relocation_search_reserve_seconds=float(
                self.initial_relocation_search_reserve_seconds
            ),
            relocation_acceptance_reserve_seconds=float(
                self.initial_relocation_acceptance_reserve_seconds
            ),
        )

    def post_bounds(self) -> IterativeFeedbackBounds:
        return IterativeFeedbackBounds(
            feedback_rounds=int(self.post_feedback_rounds),
            feedback_iterations_per_round=int(self.feedback_iterations_per_round),
            candidate_batch_size=int(self.candidate_batch_size),
            history_length=int(self.history_length),
            stagnation_limit=int(self.stagnation_limit),
            coordinate_room_sweeps=int(self.coordinate_room_sweeps),
            time_rooted_relocations=0,
            component_rooted_relocations=0,
            stability_collision_weight=int(self.stability_collision_weight),
            stability_proxy_mode=str(self.stability_proxy_mode),
            feedback_search_reserve_seconds=float(
                self.post_feedback_search_reserve_seconds
            ),
            majority_lift_reserve_seconds=float(
                self.post_majority_lift_reserve_seconds
            ),
            coordinate_lift_reserve_seconds=float(
                self.post_coordinate_lift_reserve_seconds
            ),
            feedback_acceptance_reserve_seconds=float(
                self.post_acceptance_reserve_seconds
            ),
            relocation_search_reserve_seconds=float(
                self.post_relocation_search_reserve_seconds
            ),
            relocation_acceptance_reserve_seconds=float(
                self.post_relocation_acceptance_reserve_seconds
            ),
        )

    def validation_errors(self) -> tuple[str, ...]:
        integer_bounds = {
            "initial_feedback_rounds": self.initial_feedback_rounds,
            "post_feedback_rounds": self.post_feedback_rounds,
            "feedback_iterations_per_round": self.feedback_iterations_per_round,
            "candidate_batch_size": self.candidate_batch_size,
            "history_length": self.history_length,
            "stagnation_limit": self.stagnation_limit,
            "coordinate_room_sweeps": self.coordinate_room_sweeps,
            "time_rooted_relocations": self.time_rooted_relocations,
            "component_rooted_relocations": self.component_rooted_relocations,
            "rooted_adjacency_moves": self.rooted_adjacency_moves,
            "rooted_coordinate_room_sweeps": (self.rooted_coordinate_room_sweeps),
        }
        errors: list[str] = []
        for name, value in integer_bounds.items():
            if int(value) < 0:
                errors.append(f"negative_bound:{name}")
        for name in (
            "initial_feedback_rounds",
            "post_feedback_rounds",
            "feedback_iterations_per_round",
            "candidate_batch_size",
            "history_length",
            "stagnation_limit",
            "coordinate_room_sweeps",
            "rooted_adjacency_moves",
            "rooted_coordinate_room_sweeps",
        ):
            if int(integer_bounds[name]) == 0:
                errors.append(f"zero_bound:{name}")

        reserve_groups = (
            (
                "tail",
                (
                    self.initial_phase_tail_reserve_seconds,
                    self.post_feedback_tail_reserve_seconds,
                    self.final_validation_reserve_seconds,
                ),
            ),
            (
                "initial",
                (
                    self.initial_feedback_search_reserve_seconds,
                    self.initial_majority_lift_reserve_seconds,
                    self.initial_coordinate_lift_reserve_seconds,
                    self.initial_acceptance_reserve_seconds,
                    self.initial_relocation_search_reserve_seconds,
                    self.initial_relocation_acceptance_reserve_seconds,
                ),
            ),
            (
                "post",
                (
                    self.post_feedback_search_reserve_seconds,
                    self.post_majority_lift_reserve_seconds,
                    self.post_coordinate_lift_reserve_seconds,
                    self.post_acceptance_reserve_seconds,
                    self.post_relocation_search_reserve_seconds,
                    self.post_relocation_acceptance_reserve_seconds,
                ),
            ),
        )
        for group, values in reserve_groups:
            if any(
                not math.isfinite(float(value)) or float(value) < 0 for value in values
            ):
                errors.append(f"invalid_reserve:{group}")
            elif any(left < right for left, right in zip(values, values[1:])):
                errors.append(f"reserves_not_monotone:{group}")
        if (
            not math.isfinite(float(self.rooted_completion_reserve_seconds))
            or float(self.rooted_completion_reserve_seconds) < 0
        ):
            errors.append("invalid_reserve:rooted_completion")
        for stage_bounds in (self.initial_bounds(), self.post_bounds()):
            errors.extend(stage_bounds.validation_errors())
        return tuple(dict.fromkeys(errors))


@dataclass
class FeedbackRootedTelemetry:
    seed: int
    bounds: dict[str, Any]
    stages: list[dict[str, Any]] = field(default_factory=list)
    canonicalizations: int = 0
    validation_calls: int = 0
    helper_validation_calls: int = 0
    independent_rescores: int = 0
    mutation_guard_failures: int = 0
    timing: dict[str, float | int | bool | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FeedbackRootedResult:
    status: str
    schedule: Schedule
    improved: bool
    initial_score: ITC2007Score | None
    final_score: ITC2007Score | None
    telemetry: FeedbackRootedTelemetry
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
            "validation_errors": list(self.validation_errors),
            "eligibility_reasons": list(self.eligibility_reasons),
            "deadline_exhausted": bool(self.deadline_exhausted),
            "deadline_overrun_seconds": float(self.deadline_overrun_seconds),
            "telemetry": self.telemetry.to_dict(),
            "error": self.error,
        }


class _FailClosed(RuntimeError):
    def __init__(
        self,
        status: str,
        *,
        error: str | None = None,
        validation_errors: Sequence[str] = (),
        eligibility_reasons: Sequence[str] = (),
    ) -> None:
        super().__init__(error or status)
        self.status = str(status)
        self.error = error
        self.validation_errors = tuple(str(value) for value in validation_errors)
        self.eligibility_reasons = tuple(str(value) for value in eligibility_reasons)


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


def _iterative_checkpoint_errors(
    result: IterativeFeedbackResult,
    bounds: IterativeFeedbackBounds,
) -> tuple[str, ...]:
    telemetry = result.telemetry
    errors: list[str] = []
    if int(telemetry.feedback_rounds_completed) != int(bounds.feedback_rounds):
        errors.append("feedback_round_count")
    if len(telemetry.round_trace) != int(bounds.feedback_rounds):
        errors.append("feedback_trace_count")
    for index, row in enumerate(telemetry.round_trace, start=1):
        termination = str(row.get("termination_reason", ""))
        iterations = int(row.get("iterations", -1))
        quota = int(row.get("iteration_quota", -1))
        complete = bool(row.get("checkpoint_complete", False))
        if int(row.get("round", -1)) != index:
            errors.append(f"feedback_round_index:{index}")
        if quota != int(bounds.feedback_iterations_per_round):
            errors.append(f"feedback_iteration_quota:{index}")
        if termination not in _DETERMINISTIC_FEEDBACK_TERMINATIONS or not complete:
            errors.append(f"feedback_incomplete:{index}")
        if termination == "iteration_checkpoint" and iterations != quota:
            errors.append(f"feedback_iteration_count:{index}")

    accepted_total = 0
    for phase, quota in (
        ("time", int(bounds.time_rooted_relocations)),
        ("components", int(bounds.component_rooted_relocations)),
    ):
        accepted = [
            row
            for row in telemetry.relocation_trace
            if str(row.get("phase", "")) == phase
            and str(row.get("status", "")) == "accepted"
        ]
        checkpoints = [
            row
            for row in telemetry.relocation_trace
            if str(row.get("phase", "")) == phase
            and str(row.get("status", "")) == "checkpoint"
        ]
        if len(checkpoints) != 1:
            errors.append(f"relocation_checkpoint_count:{phase}")
            continue
        completed = int(checkpoints[0].get("completed_moves", -1))
        recorded_quota = int(checkpoints[0].get("quota", -1))
        if recorded_quota != quota or completed != len(accepted) or completed > quota:
            errors.append(f"relocation_checkpoint_mismatch:{phase}")
        if completed < quota:
            local_optimum = any(
                str(row.get("phase", "")) == phase
                and str(row.get("status", "")) == "local_optimum"
                for row in telemetry.relocation_trace
            )
            if not local_optimum:
                errors.append(f"relocation_incomplete:{phase}")
        accepted_total += len(accepted)
    if int(telemetry.relocation_moves_accepted) != accepted_total:
        errors.append("relocation_accepted_count")
    return tuple(errors)


def _rooted_checkpoint_errors(
    result: RootedAdjacencyResult,
    *,
    max_moves: int,
) -> tuple[str, ...]:
    telemetry = result.telemetry
    errors: list[str] = []
    if int(telemetry.root_iterations_discarded) != 0:
        errors.append("rooted_discarded_scan")
    accepted = int(telemetry.accepted_moves)
    if int(telemetry.completed_checkpoint_moves) != accepted:
        errors.append("rooted_accepted_count")
    trace = list(telemetry.iteration_trace)
    terminal = str(trace[-1].get("status", "")) if trace else ""
    checkpoint_complete = bool(
        accepted == int(max_moves)
        or terminal in _DETERMINISTIC_ROOTED_TERMINATIONS
        or (
            accepted == 0
            and str(telemetry.termination_reason)
            in {"rooted_local_optimum", "no_rooted_penalties"}
        )
    )
    if not checkpoint_complete:
        errors.append("rooted_incomplete_checkpoint")
    return tuple(errors)


def optimize_itc2007_feedback_rooted(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float,
    seed: int = 0,
    bounds: FeedbackRootedBounds | None = None,
    validator: Validator | None = None,
) -> FeedbackRootedResult:
    """Run the atomic representation-derived feedback/rooted policy."""

    started = time.perf_counter()
    original = _copy_schedule(schedule) if isinstance(schedule, Mapping) else {}
    active_bounds = bounds or FeedbackRootedBounds()
    validation_fn = validator or _default_validator
    telemetry = FeedbackRootedTelemetry(
        seed=int(seed),
        bounds=asdict(active_bounds),
    )
    initial_score: ITC2007Score | None = None
    current_score: ITC2007Score | None = None
    current: Schedule | None = None

    def finish(
        status: str,
        *,
        allow_current: bool = False,
        validation_errors: Sequence[str] = (),
        eligibility_reasons: Sequence[str] = (),
        error: str | None = None,
    ) -> FeedbackRootedResult:
        finished = time.perf_counter()
        deadline_failed = bool(finished >= float(deadline))
        improved = bool(
            allow_current
            and not deadline_failed
            and current is not None
            and initial_score is not None
            and current_score is not None
            and int(current_score.total) < int(initial_score.total)
        )
        selected = _copy_schedule(
            current if improved and current is not None else original
        )
        finished = time.perf_counter()
        if improved and finished >= float(deadline):
            improved = False
            selected = _copy_schedule(original)
            finished = time.perf_counter()
        overrun = max(0.0, float(finished) - float(deadline))
        deadline_failed = bool(finished >= float(deadline))
        effective_status = "deadline_exhausted" if deadline_failed else str(status)
        telemetry.timing = {
            "started_at_seconds": float(started),
            "absolute_deadline_seconds": float(deadline),
            "finished_at_seconds": float(finished),
            "elapsed_seconds": float(finished - started),
            "budget_seconds": float(deadline) - float(started),
            "deadline_remaining_seconds": max(0.0, float(deadline) - finished),
            "deadline_overrun_seconds": float(overrun),
        }
        return FeedbackRootedResult(
            status=effective_status,
            schedule=selected,
            improved=bool(improved),
            initial_score=initial_score,
            final_score=current_score if improved else initial_score,
            telemetry=telemetry,
            validation_errors=tuple(str(value) for value in validation_errors)[:20],
            eligibility_reasons=tuple(str(value) for value in eligibility_reasons),
            deadline_exhausted=bool(
                deadline_failed or effective_status == "deadline_exhausted"
            ),
            deadline_overrun_seconds=float(overrun),
            error=error,
        )

    def canonicalize(candidate: Mapping[int, Mapping[str, Any]]) -> Schedule:
        source = _copy_schedule(candidate)
        snapshot = _copy_schedule(source)
        output = canonicalize_itc2007_schedule(inst, source)
        if source != snapshot:
            telemetry.mutation_guard_failures += 1
            raise _FailClosed(
                "mutation_detected",
                error="canonicalizer_mutated_candidate",
            )
        telemetry.canonicalizations += 1
        return _copy_schedule(output)

    def validate_and_score(
        candidate: Mapping[int, Mapping[str, Any]],
        *,
        context: str,
    ) -> tuple[tuple[str, ...], ITC2007Score | None, Schedule]:
        candidate_copy = _copy_schedule(candidate)
        validation_snapshot = _copy_schedule(candidate_copy)
        telemetry.validation_calls += 1
        try:
            errors = tuple(str(value) for value in validation_fn(inst, candidate_copy))
        except Exception as exc:
            raise _FailClosed(
                "error",
                error=f"{context}:validator_error:{type(exc).__name__}:{exc}",
            ) from exc
        if candidate_copy != validation_snapshot:
            telemetry.mutation_guard_failures += 1
            raise _FailClosed(
                "mutation_detected",
                error=f"{context}:validator_mutated_candidate",
            )
        if time.perf_counter() >= float(deadline):
            raise _FailClosed("deadline_exhausted")
        if errors:
            return errors, None, candidate_copy

        score_input = _copy_schedule(candidate_copy)
        score_snapshot = _copy_schedule(score_input)
        try:
            official = score_itc2007_instance_schedule(inst, score_input)
        except Exception as exc:
            raise _FailClosed(
                "error",
                error=f"{context}:scorer_error:{type(exc).__name__}:{exc}",
            ) from exc
        telemetry.independent_rescores += 1
        if score_input != score_snapshot:
            telemetry.mutation_guard_failures += 1
            raise _FailClosed(
                "mutation_detected",
                error=f"{context}:scorer_mutated_candidate",
            )
        if not isinstance(official, ITC2007Score) or not _score_is_self_consistent(
            official
        ):
            raise _FailClosed(
                "score_drift",
                error=f"{context}:invalid_official_score",
            )
        if time.perf_counter() >= float(deadline):
            raise _FailClosed("deadline_exhausted")
        return (), official, candidate_copy

    def guarded_helper_validator(
        state: dict[str, str | bool | None],
    ) -> Validator:
        def guarded(
            instance: Instance,
            candidate: Mapping[int, Mapping[str, Any]],
        ) -> Sequence[str]:
            snapshot = _copy_schedule(candidate)
            telemetry.helper_validation_calls += 1
            try:
                errors = tuple(
                    str(value) for value in validation_fn(instance, candidate)
                )
            except Exception as exc:
                state["error"] = f"{type(exc).__name__}:{exc}"
                raise
            if candidate != snapshot:
                state["mutation"] = True
                return ("validator_mutated_candidate",)
            return errors

        return guarded

    def run_iterative_stage(
        *,
        name: str,
        stage_deadline: float,
        stage_seed: int,
        stage_bounds: IterativeFeedbackBounds,
    ) -> None:
        nonlocal current, current_score
        assert current is not None
        assert current_score is not None
        stage: dict[str, Any] = {
            "name": str(name),
            "started_at_seconds": float(time.perf_counter()),
            "effective_deadline_seconds": float(stage_deadline),
            "seed": int(stage_seed),
            "bounds": asdict(stage_bounds),
            "accepted": False,
        }
        telemetry.stages.append(stage)
        if time.perf_counter() >= float(stage_deadline):
            stage["status"] = "not_started_deadline"
            raise _FailClosed("deadline_exhausted")

        helper_input = _copy_schedule(current)
        helper_snapshot = _copy_schedule(helper_input)
        validator_state: dict[str, str | bool | None] = {
            "mutation": False,
            "error": None,
        }
        try:
            result = optimize_itc2007_iterative_feedback(
                inst,
                helper_input,
                deadline=float(stage_deadline),
                seed=int(stage_seed),
                bounds=stage_bounds,
                validator=guarded_helper_validator(validator_state),
            )
        except Exception as exc:
            if helper_input != helper_snapshot:
                telemetry.mutation_guard_failures += 1
                stage["status"] = "helper_mutated_incumbent"
                raise _FailClosed(
                    "mutation_detected",
                    error=f"{name}:helper_mutated_incumbent",
                ) from exc
            stage["status"] = "helper_error"
            raise _FailClosed(
                "error",
                error=f"{name}:helper_error:{type(exc).__name__}:{exc}",
            ) from exc
        stage["helper"] = result.to_dict()
        if helper_input != helper_snapshot:
            telemetry.mutation_guard_failures += 1
            stage["status"] = "helper_mutated_incumbent"
            raise _FailClosed(
                "mutation_detected",
                error=f"{name}:helper_mutated_incumbent",
            )
        if bool(validator_state["mutation"]):
            telemetry.mutation_guard_failures += 1
            stage["status"] = "validator_mutated_candidate"
            raise _FailClosed(
                "mutation_detected",
                error=f"{name}:validator_mutated_candidate",
            )
        if validator_state["error"] is not None:
            stage["status"] = "validator_error"
            raise _FailClosed(
                "error",
                error=f"{name}:validator_error:{validator_state['error']}",
            )
        if result.deadline_exhausted or time.perf_counter() >= float(stage_deadline):
            stage["status"] = "deadline_exhausted"
            raise _FailClosed("deadline_exhausted")
        if result.status not in {"improved", "no_improvement"}:
            stage["status"] = "helper_rejected"
            raise _FailClosed(
                "stage_rejected",
                error=f"{name}:{result.status}:{result.error or ''}",
                validation_errors=result.validation_errors,
                eligibility_reasons=result.eligibility_reasons,
            )
        checkpoint_errors = _iterative_checkpoint_errors(result, stage_bounds)
        if checkpoint_errors:
            stage["status"] = "incomplete_checkpoint"
            stage["checkpoint_errors"] = list(checkpoint_errors)
            raise _FailClosed(
                "incomplete_checkpoint",
                error=f"{name}:{','.join(checkpoint_errors)}",
            )

        candidate = canonicalize(result.schedule)
        errors, official, candidate_copy = validate_and_score(
            candidate,
            context=name,
        )
        if errors or official is None:
            stage["status"] = "invalid_candidate"
            raise _FailClosed(
                "invalid_candidate",
                validation_errors=errors,
            )
        if time.perf_counter() >= float(stage_deadline):
            stage["status"] = "deadline_before_acceptance"
            raise _FailClosed("deadline_exhausted")
        if result.initial_score != current_score or result.final_score != official:
            stage["status"] = "score_drift"
            raise _FailClosed(
                "score_drift",
                error=f"{name}:helper_score_mismatch",
            )
        strict_gain = int(official.total) < int(current_score.total)
        if (
            int(official.total) > int(current_score.total)
            or bool(result.improved) != strict_gain
        ):
            stage["status"] = "score_drift"
            raise _FailClosed(
                "score_drift",
                error=f"{name}:helper_improvement_mismatch",
            )
        current = candidate_copy
        current_score = official
        stage["accepted"] = bool(strict_gain)
        stage["status"] = "accepted" if strict_gain else "no_improvement"
        stage["official_score"] = official.to_dict()
        stage["finished_at_seconds"] = float(time.perf_counter())

    try:
        if started >= float(deadline):
            return finish("deadline_exhausted")
        bound_errors = active_bounds.validation_errors()
        if bound_errors:
            return finish("ineligible", eligibility_reasons=bound_errors)

        eligibility_input = _copy_schedule(original)
        eligibility_snapshot = _copy_schedule(eligibility_input)
        eligibility = itc2007_iterative_feedback_eligibility(
            inst,
            eligibility_input,
        )
        if eligibility_input != eligibility_snapshot:
            telemetry.mutation_guard_failures += 1
            raise _FailClosed(
                "mutation_detected",
                error="eligibility_mutated_incumbent",
            )
        if not eligibility.eligible or eligibility.canonical_schedule is None:
            raise _FailClosed(
                "ineligible",
                eligibility_reasons=eligibility.reasons,
            )

        original_errors, original_official, _original_copy = validate_and_score(
            original,
            context="incumbent",
        )
        if original_errors or original_official is None:
            raise _FailClosed(
                "invalid_incumbent",
                validation_errors=original_errors,
            )
        initial_score = original_official
        canonical = canonicalize(eligibility.canonical_schedule)
        canonical_errors, canonical_official, canonical_copy = validate_and_score(
            canonical,
            context="canonical_incumbent",
        )
        if canonical_errors or canonical_official is None:
            raise _FailClosed(
                "invalid_incumbent",
                validation_errors=canonical_errors,
            )
        if canonical_official != initial_score:
            raise _FailClosed(
                "score_drift",
                error="canonicalization_changed_official_score",
            )
        current = canonical_copy
        current_score = canonical_official

        initial_stage_deadline = float(deadline) - float(
            active_bounds.initial_phase_tail_reserve_seconds
        )
        run_iterative_stage(
            name="initial_feedback_and_relocation",
            stage_deadline=initial_stage_deadline,
            stage_seed=int(seed),
            stage_bounds=active_bounds.initial_bounds(),
        )

        post_stage_deadline = float(deadline) - float(
            active_bounds.post_feedback_tail_reserve_seconds
        )
        run_iterative_stage(
            name="post_feedback",
            stage_deadline=post_stage_deadline,
            stage_seed=(int(seed) + _POST_FEEDBACK_SEED_OFFSET * _SEED_STRIDE),
            stage_bounds=active_bounds.post_bounds(),
        )

        assert current is not None
        assert current_score is not None
        rooted_deadline = float(deadline) - float(
            active_bounds.final_validation_reserve_seconds
        )
        rooted_stage: dict[str, Any] = {
            "name": "rooted_adjacency",
            "started_at_seconds": float(time.perf_counter()),
            "effective_deadline_seconds": float(rooted_deadline),
            "seed": int(seed),
            "accepted": False,
        }
        telemetry.stages.append(rooted_stage)
        if time.perf_counter() >= rooted_deadline:
            rooted_stage["status"] = "not_started_deadline"
            raise _FailClosed("deadline_exhausted")
        helper_input = _copy_schedule(current)
        helper_snapshot = _copy_schedule(helper_input)
        validator_state = {"mutation": False, "error": None}
        try:
            rooted = optimize_itc2007_rooted_adjacency(
                inst,
                helper_input,
                deadline=float(rooted_deadline),
                seed=int(seed),
                max_moves=int(active_bounds.rooted_adjacency_moves),
                completion_reserve_seconds=float(
                    active_bounds.rooted_completion_reserve_seconds
                ),
                coordinate_room_sweeps=int(active_bounds.rooted_coordinate_room_sweeps),
                validator=guarded_helper_validator(validator_state),
            )
        except Exception as exc:
            if helper_input != helper_snapshot:
                telemetry.mutation_guard_failures += 1
                rooted_stage["status"] = "helper_mutated_incumbent"
                raise _FailClosed(
                    "mutation_detected",
                    error="rooted_adjacency:helper_mutated_incumbent",
                ) from exc
            rooted_stage["status"] = "helper_error"
            raise _FailClosed(
                "error",
                error=f"rooted_adjacency:helper_error:{type(exc).__name__}:{exc}",
            ) from exc
        rooted_stage["helper"] = rooted.to_dict()
        if helper_input != helper_snapshot:
            telemetry.mutation_guard_failures += 1
            rooted_stage["status"] = "helper_mutated_incumbent"
            raise _FailClosed(
                "mutation_detected",
                error="rooted_adjacency:helper_mutated_incumbent",
            )
        if bool(validator_state["mutation"]):
            telemetry.mutation_guard_failures += 1
            rooted_stage["status"] = "validator_mutated_candidate"
            raise _FailClosed(
                "mutation_detected",
                error="rooted_adjacency:validator_mutated_candidate",
            )
        if validator_state["error"] is not None:
            rooted_stage["status"] = "validator_error"
            raise _FailClosed(
                "error",
                error=(f"rooted_adjacency:validator_error:{validator_state['error']}"),
            )
        if rooted.deadline_exhausted or time.perf_counter() >= rooted_deadline:
            rooted_stage["status"] = "deadline_exhausted"
            raise _FailClosed("deadline_exhausted")
        if rooted.status not in {"improved", "no_improvement"}:
            rooted_stage["status"] = "helper_rejected"
            raise _FailClosed(
                "stage_rejected",
                error=f"rooted_adjacency:{rooted.status}:{rooted.error or ''}",
                validation_errors=rooted.validation_errors,
                eligibility_reasons=rooted.eligibility_reasons,
            )
        checkpoint_errors = _rooted_checkpoint_errors(
            rooted,
            max_moves=int(active_bounds.rooted_adjacency_moves),
        )
        if checkpoint_errors:
            rooted_stage["status"] = "incomplete_checkpoint"
            rooted_stage["checkpoint_errors"] = list(checkpoint_errors)
            raise _FailClosed(
                "incomplete_checkpoint",
                error=f"rooted_adjacency:{','.join(checkpoint_errors)}",
            )

        rooted_candidate = canonicalize(rooted.schedule)
        rooted_errors, rooted_official, rooted_copy = validate_and_score(
            rooted_candidate,
            context="rooted_adjacency",
        )
        if rooted_errors or rooted_official is None:
            rooted_stage["status"] = "invalid_candidate"
            raise _FailClosed(
                "invalid_candidate",
                validation_errors=rooted_errors,
            )
        if time.perf_counter() >= rooted_deadline:
            rooted_stage["status"] = "deadline_before_acceptance"
            raise _FailClosed("deadline_exhausted")
        if (
            rooted.initial_score != current_score
            or rooted.final_score != rooted_official
        ):
            rooted_stage["status"] = "score_drift"
            raise _FailClosed(
                "score_drift",
                error="rooted_adjacency:helper_score_mismatch",
            )
        rooted_gain = int(rooted_official.total) < int(current_score.total)
        if (
            int(rooted_official.total) > int(current_score.total)
            or bool(rooted.improved) != rooted_gain
        ):
            rooted_stage["status"] = "score_drift"
            raise _FailClosed(
                "score_drift",
                error="rooted_adjacency:helper_improvement_mismatch",
            )
        current = rooted_copy
        current_score = rooted_official
        rooted_stage["accepted"] = bool(rooted_gain)
        rooted_stage["status"] = "accepted" if rooted_gain else "no_improvement"
        rooted_stage["official_score"] = rooted_official.to_dict()
        rooted_stage["finished_at_seconds"] = float(time.perf_counter())

        final_candidate = canonicalize(current)
        final_errors, final_official, final_copy = validate_and_score(
            final_candidate,
            context="final",
        )
        if final_errors or final_official is None:
            raise _FailClosed(
                "invalid_candidate",
                validation_errors=final_errors,
            )
        if final_official != current_score:
            raise _FailClosed(
                "score_drift",
                error="final_official_rescore_mismatch",
            )
        current = final_copy
        current_score = final_official
        if time.perf_counter() >= float(deadline):
            raise _FailClosed("deadline_exhausted")
        if int(current_score.total) < int(initial_score.total):
            return finish("improved", allow_current=True)
        return finish("no_improvement")
    except _FailClosed as exc:
        return finish(
            exc.status,
            validation_errors=exc.validation_errors,
            eligibility_reasons=exc.eligibility_reasons,
            error=exc.error,
        )
    except Exception as exc:
        return finish(
            "error",
            error=f"{type(exc).__name__}:{exc}",
        )


__all__ = [
    "FeedbackRootedBounds",
    "FeedbackRootedResult",
    "FeedbackRootedTelemetry",
    "optimize_itc2007_feedback_rooted",
]
