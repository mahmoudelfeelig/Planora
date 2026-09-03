from __future__ import annotations

"""Bounded room-first continuation for exchangeable ITC-2007 imports.

The dispatcher composes two existing, representation-derived neighborhoods:
three fixed-time room-polish cycles followed by at most four freshly rebuilt
stability-ejection passes.  Every boundary is guarded independently.  A late,
mutating, malformed, invalid, or score-inconsistent helper rolls the entire
chain back to a deep copy of the caller's exact input.
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
from core.itc2007_rooted_adjacency import (
    itc2007_rooted_adjacency_eligibility,
)
from core.itc2007_stability_ejection import (
    StabilityEjectionResult,
    optimize_itc2007_stability_ejection,
)
from core.projected_time_search import _polish_large_fixed_time_rooms
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]
Scorer = Callable[[Instance, Mapping[int, Mapping[str, Any]]], ITC2007Score]

ROOM_POLISH_MAX_SECONDS = 1.50
ROOM_POLISH_CYCLES = 3
STABILITY_PASS_COUNT = 4
STABILITY_MAX_TARGET_COURSES = 8
STABILITY_MAX_FRONTIER_COURSES = 12
STABILITY_MAX_FRONTIER_ACTIVITIES = 72
STABILITY_MAX_FRONTIER_DEPTH = 1
STABILITY_MAX_MOVED_ACTIVITIES = 14
STABILITY_MAX_SECONDS_PER_TARGET = 0.28
STABILITY_COMPLETION_RESERVE_SECONDS = 0.075
FINAL_COMPLETION_RESERVE_SECONDS = 0.10
PASS_SEED_STRIDE = 104_729


@dataclass(frozen=True)
class RoomStabilityEligibility:
    eligible: bool
    reasons: tuple[str, ...]
    canonical_schedule: Schedule | None


@dataclass
class RoomStabilityTelemetry:
    seed: int
    policy: dict[str, Any] = field(default_factory=dict)
    stages: list[dict[str, Any]] = field(default_factory=list)
    score_trajectory: list[dict[str, Any]] = field(default_factory=list)
    validation_calls: int = 0
    independent_rescores: int = 0
    canonicalizations: int = 0
    mutation_guard_failures: int = 0
    stability_passes_started: int = 0
    stability_passes_accepted: int = 0
    timing: dict[str, float | bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RoomStabilityResult:
    status: str
    schedule: Schedule
    improved: bool
    initial_score: ITC2007Score | None
    final_score: ITC2007Score | None
    telemetry: RoomStabilityTelemetry
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


def itc2007_room_stability_eligibility(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
) -> RoomStabilityEligibility:
    """Use the strict rooted/exchangeable ITC-2007 admission boundary."""

    rooted = itc2007_rooted_adjacency_eligibility(inst, schedule)
    return RoomStabilityEligibility(
        eligible=bool(rooted.eligible),
        reasons=tuple(str(value) for value in rooted.reasons),
        canonical_schedule=(
            None
            if rooted.canonical_schedule is None
            else _copy_schedule(rooted.canonical_schedule)
        ),
    )


def optimize_itc2007_room_stability(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float,
    seed: int = 0,
    validator: Validator | None = None,
    scorer: Scorer | None = None,
) -> RoomStabilityResult:
    """Run the frozen room-polish/stability chain under one absolute deadline."""

    started = time.perf_counter()
    original = _copy_schedule(schedule) if isinstance(schedule, Mapping) else {}
    current = _copy_schedule(original)
    validation_fn = validator or _default_validator
    score_fn = scorer or score_itc2007_instance_schedule
    telemetry = RoomStabilityTelemetry(
        seed=int(seed),
        policy={
            "room_polish_max_seconds": ROOM_POLISH_MAX_SECONDS,
            "room_polish_cycles": ROOM_POLISH_CYCLES,
            "stability_pass_count": STABILITY_PASS_COUNT,
            "stability_max_target_courses": STABILITY_MAX_TARGET_COURSES,
            "stability_max_frontier_courses": STABILITY_MAX_FRONTIER_COURSES,
            "stability_max_frontier_activities": STABILITY_MAX_FRONTIER_ACTIVITIES,
            "stability_max_frontier_depth": STABILITY_MAX_FRONTIER_DEPTH,
            "stability_max_moved_activities": STABILITY_MAX_MOVED_ACTIVITIES,
            "stability_max_seconds_per_target": (STABILITY_MAX_SECONDS_PER_TARGET),
            "stability_completion_reserve_seconds": (
                STABILITY_COMPLETION_RESERVE_SECONDS
            ),
            "final_completion_reserve_seconds": FINAL_COMPLETION_RESERVE_SECONDS,
            "pass_seed_stride": PASS_SEED_STRIDE,
        },
    )
    initial_score: ITC2007Score | None = None
    current_score: ITC2007Score | None = None
    eligibility_reasons: tuple[str, ...] = ()
    phase_deadline = float(deadline) - FINAL_COMPLETION_RESERVE_SECONDS

    def finish(
        status: str,
        *,
        force_original: bool = False,
        error: str | None = None,
        validation_errors: Sequence[str] = (),
    ) -> RoomStabilityResult:
        nonlocal current_score
        improvement_ready = bool(
            not force_original
            and initial_score is not None
            and current_score is not None
            and int(current_score.total) < int(initial_score.total)
        )
        selected = _copy_schedule(current if improvement_ready else original)
        finished = time.perf_counter()
        overrun = max(0.0, float(finished) - float(deadline))
        if finished >= float(deadline):
            status = "deadline_exhausted"
            improvement_ready = False
            selected = _copy_schedule(original)
            finished = time.perf_counter()
            overrun = max(0.0, float(finished) - float(deadline))
        telemetry.timing = {
            "started_at_seconds": float(started),
            "absolute_deadline_seconds": float(deadline),
            "phase_deadline_seconds": float(phase_deadline),
            "requested_budget_seconds": max(0.0, float(deadline) - started),
            "elapsed_seconds": float(finished - started),
            "deadline_remaining_seconds": max(0.0, float(deadline) - finished),
            "deadline_overrun_seconds": float(overrun),
        }
        return RoomStabilityResult(
            status=str(status),
            schedule=selected,
            improved=bool(improvement_ready),
            initial_score=initial_score,
            final_score=current_score if improvement_ready else initial_score,
            telemetry=telemetry,
            validation_errors=tuple(str(value) for value in validation_errors)[:20],
            eligibility_reasons=eligibility_reasons,
            deadline_exhausted=bool(
                str(status) == "deadline_exhausted" or finished >= float(deadline)
            ),
            deadline_overrun_seconds=float(overrun),
            error=error,
        )

    def ensure_before(cutoff: float, *, context: str) -> None:
        if time.perf_counter() >= float(cutoff):
            raise _FailClosed(
                "deadline_exhausted",
                error=f"{context}:deadline_exhausted",
            )

    def canonicalize_guarded(
        candidate: Mapping[int, Mapping[str, Any]],
        *,
        context: str,
        cutoff: float,
    ) -> Schedule:
        candidate_input = _copy_schedule(candidate)
        snapshot = _copy_schedule(candidate_input)
        try:
            canonical = canonicalize_itc2007_schedule(inst, candidate_input)
        except Exception as exc:
            raise _FailClosed(
                "error",
                error=f"{context}:canonicalization_error:{type(exc).__name__}:{exc}",
            ) from exc
        if candidate_input != snapshot:
            telemetry.mutation_guard_failures += 1
            raise _FailClosed(
                "mutation_detected",
                error=f"{context}:canonicalizer_mutated_candidate",
            )
        telemetry.canonicalizations += 1
        ensure_before(cutoff, context=context)
        return _copy_schedule(canonical)

    def invoke_validator(
        candidate: Mapping[int, Mapping[str, Any]],
        *,
        context: str,
        cutoff: float,
    ) -> tuple[str, ...]:
        validation_input = _copy_schedule(candidate)
        snapshot = _copy_schedule(validation_input)
        telemetry.validation_calls += 1
        try:
            raw_errors = validation_fn(inst, validation_input)
            errors = tuple(str(value) for value in raw_errors)
        except _FailClosed:
            raise
        except Exception as exc:
            raise _FailClosed(
                "error",
                error=f"{context}:validator_error:{type(exc).__name__}:{exc}",
            ) from exc
        if validation_input != snapshot:
            telemetry.mutation_guard_failures += 1
            raise _FailClosed(
                "mutation_detected",
                error=f"{context}:validator_mutated_candidate",
            )
        ensure_before(cutoff, context=context)
        return errors

    def invoke_scorer(
        candidate: Mapping[int, Mapping[str, Any]],
        *,
        context: str,
        cutoff: float,
    ) -> ITC2007Score:
        score_input = _copy_schedule(candidate)
        snapshot = _copy_schedule(score_input)
        try:
            official = score_fn(inst, score_input)
        except Exception as exc:
            raise _FailClosed(
                "error",
                error=f"{context}:scorer_error:{type(exc).__name__}:{exc}",
            ) from exc
        if score_input != snapshot:
            telemetry.mutation_guard_failures += 1
            raise _FailClosed(
                "mutation_detected",
                error=f"{context}:scorer_mutated_candidate",
            )
        telemetry.independent_rescores += 1
        if not isinstance(official, ITC2007Score) or not _score_is_self_consistent(
            official
        ):
            raise _FailClosed(
                "error",
                error=f"{context}:invalid_official_score",
            )
        ensure_before(cutoff, context=context)
        return official

    def validate_and_rescore(
        candidate: Mapping[int, Mapping[str, Any]],
        *,
        context: str,
        cutoff: float,
    ) -> tuple[Schedule, ITC2007Score]:
        candidate_copy = _copy_schedule(candidate)
        if set(candidate_copy) != {int(value) for value in inst.activities}:
            raise _FailClosed(
                "invalid_candidate",
                error=f"{context}:incomplete_schedule",
                validation_errors=("incomplete_schedule",),
            )
        errors = invoke_validator(candidate_copy, context=context, cutoff=cutoff)
        if errors:
            raise _FailClosed(
                "invalid_candidate",
                error=f"{context}:validation_failed",
                validation_errors=errors,
            )
        return candidate_copy, invoke_scorer(
            candidate_copy,
            context=context,
            cutoff=cutoff,
        )

    try:
        if not math.isfinite(float(deadline)) or started >= phase_deadline:
            return finish("deadline_exhausted", force_original=True)

        eligibility_input = _copy_schedule(original)
        eligibility_snapshot = _copy_schedule(eligibility_input)
        try:
            eligibility = itc2007_room_stability_eligibility(
                inst,
                eligibility_input,
            )
        except Exception as exc:
            return finish(
                "error",
                force_original=True,
                error=f"eligibility_error:{type(exc).__name__}:{exc}",
            )
        if eligibility_input != eligibility_snapshot:
            telemetry.mutation_guard_failures += 1
            return finish(
                "mutation_detected",
                force_original=True,
                error="eligibility_mutated_incumbent",
            )
        ensure_before(phase_deadline, context="eligibility")
        eligibility_reasons = tuple(str(value) for value in eligibility.reasons)
        if not eligibility.eligible or eligibility.canonical_schedule is None:
            return finish("ineligible", force_original=True)

        original_copy, source_score = validate_and_rescore(
            original,
            context="incumbent",
            cutoff=phase_deadline,
        )
        initial_score = source_score
        canonical = canonicalize_guarded(
            eligibility.canonical_schedule,
            context="incumbent_canonicalization",
            cutoff=phase_deadline,
        )
        canonical_copy, canonical_score = validate_and_rescore(
            canonical,
            context="canonical_incumbent",
            cutoff=phase_deadline,
        )
        if canonical_score != source_score:
            raise _FailClosed(
                "error",
                error="canonicalization_not_lossless",
            )
        del original_copy
        current = canonical_copy
        current_score = canonical_score
        telemetry.score_trajectory.append(
            {"source": "incumbent", **current_score.to_dict()}
        )

        room_started = time.perf_counter()
        room_deadline = min(
            phase_deadline,
            started + ROOM_POLISH_MAX_SECONDS,
        )
        ensure_before(room_deadline, context="large_fixed_time_rooms")
        room_stage: dict[str, Any] = {
            "name": "large_fixed_time_rooms",
            "accepted": False,
            "started_at_seconds": float(room_started),
            "effective_deadline_seconds": float(room_deadline),
        }
        helper_input = _copy_schedule(current)
        helper_snapshot = _copy_schedule(helper_input)

        def room_validator(
            helper_inst: Instance,
            candidate: Mapping[int, Mapping[str, Any]],
        ) -> Sequence[str]:
            if helper_inst is not inst:
                raise _FailClosed(
                    "helper_rejected",
                    error="large_fixed_time_rooms:instance_replaced",
                )
            return invoke_validator(
                candidate,
                context="large_fixed_time_rooms:helper_validator",
                cutoff=room_deadline,
            )

        raw_room_result = _polish_large_fixed_time_rooms(
            inst,
            helper_input,
            deadline=float(room_deadline),
            seed=int(seed),
            validator=room_validator,
            max_cycles=ROOM_POLISH_CYCLES,
        )
        if helper_input != helper_snapshot:
            telemetry.mutation_guard_failures += 1
            raise _FailClosed(
                "mutation_detected",
                error="large_fixed_time_rooms:helper_mutated_incumbent",
            )
        ensure_before(room_deadline, context="large_fixed_time_rooms")
        if (
            not isinstance(raw_room_result, tuple)
            or len(raw_room_result) != 2
            or not isinstance(raw_room_result[0], Mapping)
            or not isinstance(raw_room_result[1], Mapping)
        ):
            raise _FailClosed(
                "helper_rejected",
                error="large_fixed_time_rooms:malformed_result",
            )
        room_candidate, raw_room_meta = raw_room_result
        room_meta = dict(raw_room_meta)
        room_stage["helper_telemetry"] = copy.deepcopy(room_meta)
        if (
            room_meta.get("deadline_exhausted") is not False
            or int(room_meta.get("cycles_requested", -1)) != ROOM_POLISH_CYCLES
            or int(room_meta.get("cycles_completed", -1)) != ROOM_POLISH_CYCLES
        ):
            raise _FailClosed(
                "helper_rejected",
                error="large_fixed_time_rooms:incomplete_or_late",
            )
        canonical_room = canonicalize_guarded(
            room_candidate,
            context="large_fixed_time_rooms:canonicalization",
            cutoff=room_deadline,
        )
        room_copy, room_score = validate_and_rescore(
            canonical_room,
            context="large_fixed_time_rooms",
            cutoff=room_deadline,
        )
        if int(room_meta.get("final_score", -1)) != int(room_score.total):
            raise _FailClosed(
                "helper_rejected",
                error="large_fixed_time_rooms:score_disagreement",
            )
        room_stage["candidate_score"] = room_score.to_dict()
        if int(room_score.total) > int(current_score.total):
            raise _FailClosed(
                "helper_rejected",
                error="large_fixed_time_rooms:worsened_incumbent",
            )
        if int(room_score.total) < int(current_score.total):
            current = room_copy
            current_score = room_score
            room_stage["accepted"] = True
            room_stage["status"] = "accepted"
            telemetry.score_trajectory.append(
                {"source": "large_fixed_time_rooms", **room_score.to_dict()}
            )
        else:
            room_stage["status"] = "no_improvement"
        room_stage["finished_at_seconds"] = float(time.perf_counter())
        telemetry.stages.append(room_stage)

        for pass_index in range(STABILITY_PASS_COUNT):
            pass_started = time.perf_counter()
            ensure_before(phase_deadline, context=f"stability_{pass_index + 1}")
            telemetry.stability_passes_started += 1
            pass_stage: dict[str, Any] = {
                "name": f"stability_{pass_index + 1}",
                "accepted": False,
                "started_at_seconds": float(pass_started),
                "effective_deadline_seconds": float(phase_deadline),
            }
            helper_input = _copy_schedule(current)
            helper_snapshot = _copy_schedule(helper_input)

            def stability_validator(
                helper_inst: Instance,
                candidate: Mapping[int, Mapping[str, Any]],
            ) -> Sequence[str]:
                if helper_inst is not inst:
                    raise _FailClosed(
                        "helper_rejected",
                        error=f"stability_{pass_index + 1}:instance_replaced",
                    )
                return invoke_validator(
                    candidate,
                    context=f"stability_{pass_index + 1}:helper_validator",
                    cutoff=phase_deadline,
                )

            helper_result = optimize_itc2007_stability_ejection(
                inst,
                helper_input,
                deadline=float(phase_deadline),
                seed=int(seed) + pass_index * PASS_SEED_STRIDE,
                max_target_courses=STABILITY_MAX_TARGET_COURSES,
                max_frontier_courses=STABILITY_MAX_FRONTIER_COURSES,
                max_frontier_activities=STABILITY_MAX_FRONTIER_ACTIVITIES,
                max_frontier_depth=STABILITY_MAX_FRONTIER_DEPTH,
                max_moved_activities=STABILITY_MAX_MOVED_ACTIVITIES,
                max_solve_seconds=max(
                    0.01,
                    float(phase_deadline) - time.perf_counter(),
                ),
                max_seconds_per_target=STABILITY_MAX_SECONDS_PER_TARGET,
                completion_reserve_seconds=(STABILITY_COMPLETION_RESERVE_SECONDS),
                validator=stability_validator,
            )
            if helper_input != helper_snapshot:
                telemetry.mutation_guard_failures += 1
                raise _FailClosed(
                    "mutation_detected",
                    error=f"stability_{pass_index + 1}:helper_mutated_incumbent",
                )
            ensure_before(phase_deadline, context=f"stability_{pass_index + 1}")
            if not isinstance(helper_result, StabilityEjectionResult):
                raise _FailClosed(
                    "helper_rejected",
                    error=f"stability_{pass_index + 1}:malformed_result",
                )
            pass_stage["helper_result"] = helper_result.to_dict()
            helper_overrun = float(helper_result.deadline_overrun_seconds)
            if (
                helper_result.deadline_exhausted
                or not math.isfinite(helper_overrun)
                or helper_overrun != 0.0
            ):
                raise _FailClosed(
                    "helper_rejected",
                    error=f"stability_{pass_index + 1}:helper_deadline_overrun",
                )

            if helper_result.status in {"no_improvement", "no_fragmented_courses"}:
                if (
                    helper_result.improved
                    or helper_result.schedule != helper_input
                    or helper_result.initial_score != current_score
                    or helper_result.final_score != current_score
                ):
                    raise _FailClosed(
                        "helper_rejected",
                        error=f"stability_{pass_index + 1}:inconsistent_terminal",
                    )
                pass_stage["status"] = str(helper_result.status)
                pass_stage["finished_at_seconds"] = float(time.perf_counter())
                telemetry.stages.append(pass_stage)
                break

            if (
                helper_result.status != "improved"
                or not helper_result.improved
                or helper_result.initial_score != current_score
                or helper_result.final_score is None
            ):
                raise _FailClosed(
                    "helper_rejected",
                    error=f"stability_{pass_index + 1}:inconsistent_status",
                )
            canonical_candidate = canonicalize_guarded(
                helper_result.schedule,
                context=f"stability_{pass_index + 1}:canonicalization",
                cutoff=phase_deadline,
            )
            candidate_copy, candidate_score = validate_and_rescore(
                canonical_candidate,
                context=f"stability_{pass_index + 1}",
                cutoff=phase_deadline,
            )
            if candidate_score != helper_result.final_score:
                raise _FailClosed(
                    "helper_rejected",
                    error=f"stability_{pass_index + 1}:score_disagreement",
                )
            if int(candidate_score.total) >= int(current_score.total):
                raise _FailClosed(
                    "helper_rejected",
                    error=f"stability_{pass_index + 1}:not_strictly_better",
                )
            current = candidate_copy
            current_score = candidate_score
            telemetry.stability_passes_accepted += 1
            pass_stage["accepted"] = True
            pass_stage["status"] = "accepted"
            pass_stage["candidate_score"] = candidate_score.to_dict()
            pass_stage["finished_at_seconds"] = float(time.perf_counter())
            telemetry.stages.append(pass_stage)
            telemetry.score_trajectory.append(
                {
                    "source": f"stability_{pass_index + 1}",
                    **candidate_score.to_dict(),
                }
            )

        ensure_before(phase_deadline, context="final_reserve")
        final_canonical = canonicalize_guarded(
            current,
            context="final_canonicalization",
            cutoff=float(deadline),
        )
        final_copy, final_score = validate_and_rescore(
            final_canonical,
            context="final",
            cutoff=float(deadline),
        )
        if current_score is None or final_score != current_score:
            raise _FailClosed(
                "error",
                error="final_official_score_disagreement",
            )
        current = final_copy
        current_score = final_score
        return finish(
            "improved"
            if initial_score is not None
            and int(current_score.total) < int(initial_score.total)
            else "no_improvement"
        )
    except _FailClosed as exc:
        return finish(
            exc.status,
            force_original=True,
            error=exc.error,
            validation_errors=exc.validation_errors,
        )
    except Exception as exc:
        return finish(
            "error",
            force_original=True,
            error=f"{type(exc).__name__}:{exc}",
        )


__all__ = [
    "FINAL_COMPLETION_RESERVE_SECONDS",
    "PASS_SEED_STRIDE",
    "ROOM_POLISH_CYCLES",
    "ROOM_POLISH_MAX_SECONDS",
    "RoomStabilityEligibility",
    "RoomStabilityResult",
    "RoomStabilityTelemetry",
    "STABILITY_COMPLETION_RESERVE_SECONDS",
    "STABILITY_MAX_FRONTIER_ACTIVITIES",
    "STABILITY_MAX_FRONTIER_COURSES",
    "STABILITY_MAX_FRONTIER_DEPTH",
    "STABILITY_MAX_MOVED_ACTIVITIES",
    "STABILITY_MAX_SECONDS_PER_TARGET",
    "STABILITY_MAX_TARGET_COURSES",
    "STABILITY_PASS_COUNT",
    "itc2007_room_stability_eligibility",
    "optimize_itc2007_room_stability",
]
