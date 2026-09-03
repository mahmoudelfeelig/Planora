from __future__ import annotations

"""Bounded exact-frontier and relocate/swap alternation for ITC-2007 CTT.

The exact neighborhoods and local moves are established timetabling
techniques.  This module provides a general, deadline-coordinated acceptance
boundary: every exact frontier is followed by a cheap total-objective polish,
component regressions are allowed only when the official total strictly
improves, and no candidate escapes without full hard validation and an
independent official rescore.
"""

import copy
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from benchmarks.itc2007 import ITC2007Score, score_itc2007_instance_schedule
from core.itc2007_compactness_frontier import (
    optimize_itc2007_compactness_frontier,
)
from core.itc2007_compound_search import _CompoundState
from core.itc2007_stability_ejection import optimize_itc2007_stability_ejection
from core.projected_time_search import itc2007_fixed_time_room_cp_eligibility
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]
ExactOptimizer = Callable[..., Any]

DEFAULT_MAX_CYCLES = 2
DEFAULT_MAX_EXACT_SECONDS_PER_STAGE = 1.25
DEFAULT_MAX_POLISH_SEARCH_SECONDS = 0.25
DEFAULT_MAX_POLISH_PASSES_PER_STAGE = 2
DEFAULT_MAX_RELOCATE_CHECKS = 100_000
DEFAULT_MAX_SWAP_CHECKS = 50_000
DEFAULT_MAX_POLISH_SHORTLIST = 24
DEFAULT_COMPLETION_RESERVE_SECONDS = 0.03


@dataclass(frozen=True)
class ExactFrontierStage:
    """One exact optimizer and its maximum wall-clock slice per cycle."""

    name: str
    optimizer: ExactOptimizer = field(repr=False, compare=False)
    max_seconds: float = DEFAULT_MAX_EXACT_SECONDS_PER_STAGE
    options: Mapping[str, Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )


@dataclass
class FrontierAlternationTelemetry:
    seed: int
    stages: list[dict[str, Any]] = field(default_factory=list)
    component_trajectory: list[dict[str, Any]] = field(default_factory=list)
    accepted_sources: list[str] = field(default_factory=list)
    validation_calls: int = 0
    independent_rescores: int = 0
    exact_frontier_calls: int = 0
    polish_calls: int = 0
    accepted_exact_frontiers: int = 0
    accepted_polish_moves: int = 0
    relocate_checks: int = 0
    swap_checks: int = 0
    timing: dict[str, float | int | bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FrontierAlternationResult:
    status: str
    schedule: Schedule
    improved: bool
    initial_score: ITC2007Score | None
    final_score: ITC2007Score | None
    telemetry: FrontierAlternationTelemetry
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


@dataclass(frozen=True)
class _CheapCandidate:
    schedule: Schedule = field(compare=False, repr=False)
    predicted_score: ITC2007Score
    move: dict[str, Any] = field(compare=False)


@dataclass(frozen=True)
class _CheapSearchBatch:
    candidates: tuple[_CheapCandidate, ...]
    relocate_checks: int
    swap_checks: int
    search_deadline_reached: bool


class _FailClosed(Exception):
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


def _score_row(source: str, score: ITC2007Score) -> dict[str, Any]:
    return {"source": str(source), **score.to_dict()}


def _helper_overrun_seconds(result: Any) -> float:
    direct = getattr(result, "deadline_overrun_seconds", None)
    if direct is not None:
        try:
            return max(0.0, float(direct))
        except (TypeError, ValueError):
            return float("inf")
    telemetry = getattr(result, "telemetry", None)
    timing = getattr(telemetry, "timing", {}) if telemetry is not None else {}
    try:
        return max(
            0.0,
            float((timing or {}).get("deadline_overrun_seconds", 0.0)),
        )
    except (AttributeError, TypeError, ValueError):
        return float("inf")


def default_itc2007_exact_frontiers(
    *,
    max_seconds_per_stage: float = DEFAULT_MAX_EXACT_SECONDS_PER_STAGE,
) -> tuple[ExactFrontierStage, ...]:
    """Return representation-derived exact stages with bounded neighborhoods."""

    seconds = float(max_seconds_per_stage)
    per_target = max(0.01, min(0.75, seconds))
    reserve = max(0.0, min(0.03, seconds * 0.10))
    return (
        ExactFrontierStage(
            name="stability_ejection",
            optimizer=optimize_itc2007_stability_ejection,
            max_seconds=seconds,
            options={
                "max_target_courses": 4,
                "max_frontier_courses": 16,
                "max_frontier_activities": 56,
                "max_frontier_depth": 1,
                "max_moved_activities": 24,
                "max_solve_seconds": seconds,
                "max_seconds_per_target": per_target,
                "completion_reserve_seconds": reserve,
            },
        ),
        ExactFrontierStage(
            name="compactness_frontier",
            optimizer=optimize_itc2007_compactness_frontier,
            max_seconds=seconds,
            options={
                "max_target_courses": 16,
                "max_frontier_courses": 12,
                "max_frontier_activities": 56,
                "max_frontier_depth": 2,
                "max_moved_activities": 24,
                "max_solve_seconds": seconds,
                "max_seconds_per_target": per_target,
                "completion_reserve_seconds": reserve,
            },
        ),
    )


def _candidate_rank(
    candidate: _CheapCandidate,
    incumbent: ITC2007Score,
) -> tuple[Any, ...]:
    score = candidate.predicted_score
    component_regression = sum(
        max(0, int(after) - int(before))
        for after, before in (
            (score.room_capacity, incumbent.room_capacity),
            (score.minimum_working_days, incumbent.minimum_working_days),
            (score.curriculum_compactness, incumbent.curriculum_compactness),
            (score.room_stability, incumbent.room_stability),
        )
    )
    move = candidate.move
    return (
        int(score.total),
        int(component_regression),
        0 if str(move.get("kind")) == "relocate" else 1,
        tuple((str(key), repr(value)) for key, value in sorted(move.items())),
    )


def _find_relocate_swap_candidates(
    inst: Instance,
    schedule: Schedule,
    incumbent_score: ITC2007Score,
    *,
    deadline: float,
    max_relocate_checks: int,
    max_swap_checks: int,
    max_shortlist: int,
) -> _CheapSearchBatch:
    """Build a deterministic shortlist using exact incremental total scores."""

    state = _CompoundState(inst, _copy_schedule(schedule))
    if state.initial_score != incumbent_score:
        raise RuntimeError("polish_incumbent_score_disagreement")
    if time.perf_counter() >= float(deadline):
        return _CheapSearchBatch((), 0, 0, True)

    candidates: list[_CheapCandidate] = []
    seen_layouts: set[tuple[tuple[Any, ...], ...]] = set()
    relocate_checks = 0
    swap_checks = 0
    deadline_reached = False
    all_rooms = tuple(sorted(int(room_id) for room_id in inst.rooms))
    periods, rooms, by_period = state.arrays({}, {})
    occupancy = {
        (int(periods[index]), int(rooms[index])): int(index)
        for index in range(len(state.activity_ids))
    }

    def retain(
        period_override: Mapping[int, int],
        room_override: Mapping[int, int],
        predicted: ITC2007Score,
        move: dict[str, Any],
    ) -> None:
        if int(predicted.total) >= int(incumbent_score.total):
            return
        layout = tuple(
            sorted(
                (
                    int(index),
                    int(period_override.get(index, state.base_period[index])),
                    int(room_override.get(index, state.base_room[index])),
                )
                for index in set(period_override) | set(room_override)
            )
        )
        if layout in seen_layouts:
            return
        seen_layouts.add(layout)
        candidates.append(
            _CheapCandidate(
                schedule=state.materialize(period_override, room_override),
                predicted_score=predicted,
                move=move,
            )
        )
        if len(candidates) > int(max_shortlist) * 2:
            candidates.sort(key=lambda row: _candidate_rank(row, incumbent_score))
            del candidates[int(max_shortlist) :]

    if int(max_relocate_checks) > 0:
        stop_relocates = False
        for index in range(len(state.activity_ids)):
            if stop_relocates:
                break
            if time.perf_counter() >= float(deadline):
                deadline_reached = True
                break
            source_period = int(periods[index])
            source_room = int(rooms[index])
            for target_period in range(state.period_count):
                if time.perf_counter() >= float(deadline):
                    deadline_reached = True
                    stop_relocates = True
                    break
                if (
                    target_period == source_period
                    or target_period in state.forbidden[index]
                ):
                    continue
                if any(
                    other in state.conflicts[index]
                    or state.course_code[other] == state.course_code[index]
                    for other in by_period[target_period]
                ):
                    continue
                for target_room in all_rooms:
                    if (
                        occupancy.get((int(target_period), int(target_room)))
                        is not None
                    ):
                        continue
                    if relocate_checks >= int(max_relocate_checks):
                        stop_relocates = True
                        break
                    relocate_checks += 1
                    period_override = {int(index): int(target_period)}
                    room_override = (
                        {int(index): int(target_room)}
                        if int(target_room) != source_room
                        else {}
                    )
                    predicted = state.score_overrides(
                        period_override,
                        room_override,
                    )
                    retain(
                        period_override,
                        room_override,
                        predicted,
                        {
                            "kind": "relocate",
                            "activity_id": int(state.activity_ids[index]),
                            "from_period": source_period,
                            "to_period": int(target_period),
                            "from_room": source_room,
                            "to_room": int(target_room),
                        },
                    )
                if stop_relocates:
                    break

    if int(max_swap_checks) > 0 and not deadline_reached:
        stop_swaps = False
        for left in range(len(state.activity_ids)):
            if stop_swaps:
                break
            if time.perf_counter() >= float(deadline):
                deadline_reached = True
                break
            for right in range(left + 1, len(state.activity_ids)):
                if time.perf_counter() >= float(deadline):
                    deadline_reached = True
                    stop_swaps = True
                    break
                if swap_checks >= int(max_swap_checks):
                    stop_swaps = True
                    break
                if not state.swap_feasible(left, right, periods, by_period):
                    continue
                swap_checks += 1
                period_override, room_override = state.compose_swap(
                    left,
                    right,
                    periods,
                    rooms,
                    {},
                    {},
                )
                predicted = state.score_overrides(period_override, room_override)
                retain(
                    period_override,
                    room_override,
                    predicted,
                    {
                        "kind": "swap",
                        "left_activity_id": int(state.activity_ids[left]),
                        "right_activity_id": int(state.activity_ids[right]),
                        "left_from_period": int(periods[left]),
                        "right_from_period": int(periods[right]),
                        "left_from_room": int(rooms[left]),
                        "right_from_room": int(rooms[right]),
                    },
                )

    candidates.sort(key=lambda row: _candidate_rank(row, incumbent_score))
    return _CheapSearchBatch(
        candidates=tuple(candidates[: int(max_shortlist)]),
        relocate_checks=int(relocate_checks),
        swap_checks=int(swap_checks),
        search_deadline_reached=bool(deadline_reached),
    )


def optimize_itc2007_frontier_alternation(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float,
    seed: int = 0,
    exact_frontiers: Sequence[ExactFrontierStage] | None = None,
    max_cycles: int = DEFAULT_MAX_CYCLES,
    max_exact_seconds_per_stage: float = DEFAULT_MAX_EXACT_SECONDS_PER_STAGE,
    max_polish_search_seconds: float = DEFAULT_MAX_POLISH_SEARCH_SECONDS,
    max_polish_passes_per_stage: int = DEFAULT_MAX_POLISH_PASSES_PER_STAGE,
    max_relocate_checks: int = DEFAULT_MAX_RELOCATE_CHECKS,
    max_swap_checks: int = DEFAULT_MAX_SWAP_CHECKS,
    max_polish_shortlist: int = DEFAULT_MAX_POLISH_SHORTLIST,
    completion_reserve_seconds: float = DEFAULT_COMPLETION_RESERVE_SECONDS,
    validator: Validator | None = None,
) -> FrontierAlternationResult:
    """Alternate bounded exact frontiers with cheap strict-total polishing.

    The routine has no benchmark-specific target score or entity identifiers.
    Exact helpers receive isolated copies, and every accepted helper or local
    candidate is independently hard-validated and officially rescored.  Any
    global deadline crossing, collaborator mutation, or score disagreement
    discards the complete run and returns the caller's exact incumbent.
    """

    started = time.perf_counter()
    original = _copy_schedule(schedule) if isinstance(schedule, Mapping) else {}
    current = _copy_schedule(original)
    validation_fn = validator or _default_validator
    telemetry = FrontierAlternationTelemetry(seed=int(seed))
    initial_score: ITC2007Score | None = None
    current_score: ITC2007Score | None = None
    eligibility_reasons: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()
    search_deadline = float(deadline)

    def finish(
        status: str,
        *,
        force_original: bool = False,
        error: str | None = None,
        errors: Sequence[str] = (),
    ) -> FrontierAlternationResult:
        nonlocal validation_errors
        if errors:
            validation_errors = tuple(str(value) for value in errors)[:20]
        strictly_improved = bool(
            not force_original
            and initial_score is not None
            and current_score is not None
            and int(current_score.total) < int(initial_score.total)
        )
        returned = _copy_schedule(current if strictly_improved else original)
        finished = time.perf_counter()
        overrun = max(0.0, float(finished) - float(deadline))
        if overrun > 0.0:
            strictly_improved = False
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
        return FrontierAlternationResult(
            status=str(status),
            schedule=returned,
            improved=bool(strictly_improved),
            initial_score=initial_score,
            final_score=current_score if strictly_improved else initial_score,
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

    def run_polish(label: str, cycle_index: int) -> bool:
        nonlocal current, current_score
        if (
            current_score is None
            or int(max_polish_passes_per_stage) <= 0
            or int(current_score.total) <= 0
        ):
            return False
        accepted_any = False
        for pass_index in range(int(max_polish_passes_per_stage)):
            now = time.perf_counter()
            if now >= float(search_deadline):
                break
            polish_deadline = min(
                float(search_deadline),
                now + float(max_polish_search_seconds),
            )
            stage_started = now
            stage: dict[str, Any] = {
                "name": str(label),
                "kind": "relocate_swap_polish",
                "cycle": int(cycle_index + 1),
                "pass": int(pass_index + 1),
                "started_at_seconds": float(stage_started),
                "effective_deadline_seconds": float(polish_deadline),
                "accepted": False,
                "before_score": current_score.to_dict(),
            }
            telemetry.stages.append(stage)
            telemetry.polish_calls += 1
            try:
                batch = _find_relocate_swap_candidates(
                    inst,
                    _copy_schedule(current),
                    current_score,
                    deadline=float(polish_deadline),
                    max_relocate_checks=int(max_relocate_checks),
                    max_swap_checks=int(max_swap_checks),
                    max_shortlist=int(max_polish_shortlist),
                )
            except Exception as exc:
                raise _FailClosed(
                    "error",
                    error=f"relocate_swap_polish:{type(exc).__name__}:{exc}",
                ) from exc
            telemetry.relocate_checks += int(batch.relocate_checks)
            telemetry.swap_checks += int(batch.swap_checks)
            stage.update(
                {
                    "relocate_checks": int(batch.relocate_checks),
                    "swap_checks": int(batch.swap_checks),
                    "shortlisted_candidates": len(batch.candidates),
                    "search_deadline_reached": bool(batch.search_deadline_reached),
                }
            )
            accepted = False
            for candidate_index, candidate in enumerate(batch.candidates):
                check_global_deadline()
                candidate_errors, official = validate_and_rescore(
                    candidate.schedule,
                    context="relocate_swap_polish",
                )
                if candidate_errors:
                    stage.setdefault("rejected_candidates", []).append(
                        {
                            "candidate_index": int(candidate_index),
                            "reason": "invalid_candidate",
                            "validation_errors": list(candidate_errors[:10]),
                        }
                    )
                    continue
                assert official is not None
                if official != candidate.predicted_score:
                    raise _FailClosed(
                        "error",
                        error=(
                            "relocate_swap_polish:"
                            "incremental_official_score_disagreement"
                        ),
                    )
                if int(official.total) >= int(current_score.total):
                    stage.setdefault("rejected_candidates", []).append(
                        {
                            "candidate_index": int(candidate_index),
                            "reason": "not_strictly_better",
                            "official_score": official.to_dict(),
                        }
                    )
                    continue
                current = _copy_schedule(candidate.schedule)
                current_score = official
                telemetry.accepted_polish_moves += 1
                telemetry.accepted_sources.append("relocate_swap_polish")
                telemetry.component_trajectory.append(
                    _score_row("relocate_swap_polish", official)
                )
                stage.update(
                    {
                        "accepted": True,
                        "status": "improved",
                        "accepted_move": copy.deepcopy(candidate.move),
                        "after_score": official.to_dict(),
                        "component_regression_accepted": any(
                            int(after) > int(before)
                            for after, before in (
                                (
                                    official.room_capacity,
                                    stage["before_score"]["room_capacity"],
                                ),
                                (
                                    official.minimum_working_days,
                                    stage["before_score"]["minimum_working_days"],
                                ),
                                (
                                    official.curriculum_compactness,
                                    stage["before_score"]["curriculum_compactness"],
                                ),
                                (
                                    official.room_stability,
                                    stage["before_score"]["room_stability"],
                                ),
                            )
                        ),
                    }
                )
                accepted = True
                accepted_any = True
                break
            if not accepted:
                stage["status"] = "no_improvement"
            stage["finished_at_seconds"] = float(time.perf_counter())
            stage["elapsed_seconds"] = float(
                stage["finished_at_seconds"] - stage_started
            )
            if not accepted:
                break
        return bool(accepted_any)

    def run_exact(
        spec: ExactFrontierStage,
        cycle_index: int,
        stage_index: int,
    ) -> bool:
        nonlocal current, current_score
        assert current_score is not None
        now = time.perf_counter()
        if now >= float(search_deadline):
            return False
        stage_deadline = min(
            float(search_deadline),
            now + float(spec.max_seconds),
        )
        stage_seed = int(seed) + cycle_index * 1_000_003 + stage_index * 104_729
        stage: dict[str, Any] = {
            "name": str(spec.name),
            "kind": "exact_frontier",
            "cycle": int(cycle_index + 1),
            "started_at_seconds": float(now),
            "effective_deadline_seconds": float(stage_deadline),
            "seed": int(stage_seed),
            "accepted": False,
            "before_score": current_score.to_dict(),
        }
        telemetry.stages.append(stage)
        telemetry.exact_frontier_calls += 1

        stage_input = _copy_schedule(current)
        stage_snapshot = _copy_schedule(stage_input)
        try:
            helper_result = spec.optimizer(
                inst,
                stage_input,
                deadline=float(stage_deadline),
                seed=int(stage_seed),
                **dict(spec.options),
            )
        except Exception as exc:
            raise _FailClosed(
                "error",
                error=f"{spec.name}:helper_error:{type(exc).__name__}:{exc}",
            ) from exc
        if stage_input != stage_snapshot:
            raise _FailClosed(
                "error",
                error=f"{spec.name}:helper_mutated_incumbent",
            )
        check_global_deadline()

        helper_status = str(getattr(helper_result, "status", "unknown"))
        stage["helper_status"] = helper_status
        stage["helper_improved"] = bool(getattr(helper_result, "improved", False))
        helper_overrun = _helper_overrun_seconds(helper_result)
        stage["helper_deadline_overrun_seconds"] = float(helper_overrun)
        if helper_status == "error":
            helper_error = getattr(helper_result, "error", None)
            raise _FailClosed(
                "error",
                error=f"{spec.name}:helper_error:{helper_error or 'unspecified'}",
            )
        if (
            time.perf_counter() >= float(stage_deadline)
            or bool(getattr(helper_result, "deadline_exhausted", False))
            or helper_overrun > 0.0
        ):
            stage["status"] = "rejected_helper_deadline"
            stage["finished_at_seconds"] = float(time.perf_counter())
            stage["elapsed_seconds"] = float(stage["finished_at_seconds"] - now)
            return False
        if not bool(getattr(helper_result, "improved", False)):
            stage["status"] = "no_improvement"
            stage["finished_at_seconds"] = float(time.perf_counter())
            stage["elapsed_seconds"] = float(stage["finished_at_seconds"] - now)
            return False

        reported_initial = getattr(helper_result, "initial_score", None)
        if reported_initial is not None and reported_initial != current_score:
            raise _FailClosed(
                "error",
                error=f"{spec.name}:helper_incumbent_score_disagreement",
            )
        raw_candidate = getattr(helper_result, "schedule", None)
        if not isinstance(raw_candidate, Mapping):
            stage["status"] = "invalid_candidate_shape"
            return False
        candidate_errors, official = validate_and_rescore(
            raw_candidate,
            context=str(spec.name),
        )
        if candidate_errors:
            stage["status"] = "invalid_candidate"
            stage["validation_errors"] = list(candidate_errors[:10])
            stage["finished_at_seconds"] = float(time.perf_counter())
            stage["elapsed_seconds"] = float(stage["finished_at_seconds"] - now)
            return False
        assert official is not None
        reported_final = getattr(helper_result, "final_score", None)
        if reported_final is not None and reported_final != official:
            raise _FailClosed(
                "error",
                error=f"{spec.name}:helper_official_score_disagreement",
            )
        if int(official.total) >= int(current_score.total):
            stage["status"] = "not_strictly_better"
            stage["official_score"] = official.to_dict()
            stage["finished_at_seconds"] = float(time.perf_counter())
            stage["elapsed_seconds"] = float(stage["finished_at_seconds"] - now)
            return False

        current = _copy_schedule(raw_candidate)
        current_score = official
        telemetry.accepted_exact_frontiers += 1
        telemetry.accepted_sources.append(str(spec.name))
        telemetry.component_trajectory.append(_score_row(str(spec.name), official))
        stage.update(
            {
                "accepted": True,
                "status": "improved",
                "after_score": official.to_dict(),
            }
        )
        stage["finished_at_seconds"] = float(time.perf_counter())
        stage["elapsed_seconds"] = float(stage["finished_at_seconds"] - now)
        return True

    try:
        if started >= float(deadline):
            return finish("deadline_exhausted", force_original=True)
        bounds_valid = bool(
            int(max_cycles) >= 1
            and float(max_exact_seconds_per_stage) > 0.0
            and float(max_polish_search_seconds) > 0.0
            and int(max_polish_passes_per_stage) >= 0
            and int(max_relocate_checks) >= 0
            and int(max_swap_checks) >= 0
            and int(max_polish_shortlist) >= 1
            and float(completion_reserve_seconds) >= 0.0
        )
        if not bounds_valid:
            eligibility_reasons = ("search_bounds_invalid",)
            return finish("ineligible", force_original=True)

        frontiers = tuple(
            exact_frontiers
            if exact_frontiers is not None
            else default_itc2007_exact_frontiers(
                max_seconds_per_stage=float(max_exact_seconds_per_stage)
            )
        )
        names = [str(spec.name) for spec in frontiers]
        if any(
            not str(spec.name).strip()
            or not callable(spec.optimizer)
            or float(spec.max_seconds) <= 0.0
            or {"deadline", "seed"}.intersection(spec.options)
            for spec in frontiers
        ) or len(names) != len(set(names)):
            eligibility_reasons = ("exact_frontier_spec_invalid",)
            return finish("ineligible", force_original=True)

        try:
            eligible, raw_reasons = itc2007_fixed_time_room_cp_eligibility(
                inst,
                original,
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
        current_score = initial_score
        telemetry.component_trajectory.append(_score_row("incumbent", initial_score))
        if int(initial_score.total) <= 0:
            return finish("no_improvement")

        now = time.perf_counter()
        available = max(0.0, float(deadline) - now)
        completion_reserve = min(
            float(completion_reserve_seconds),
            available * 0.25,
        )
        search_deadline = float(deadline) - completion_reserve

        for cycle_index in range(int(max_cycles)):
            if time.perf_counter() >= float(search_deadline):
                break
            cycle_improved = run_polish(
                f"cycle_{cycle_index + 1}_initial_polish",
                cycle_index,
            )
            if current_score is not None and int(current_score.total) <= 0:
                break
            for stage_index, spec in enumerate(frontiers):
                if time.perf_counter() >= float(search_deadline):
                    break
                accepted = run_exact(spec, cycle_index, stage_index)
                cycle_improved = bool(cycle_improved or accepted)
                if accepted:
                    polished = run_polish(
                        f"cycle_{cycle_index + 1}_after_{spec.name}",
                        cycle_index,
                    )
                    cycle_improved = bool(cycle_improved or polished)
                if current_score is not None and int(current_score.total) <= 0:
                    break
            if not cycle_improved:
                break
            if current_score is not None and int(current_score.total) <= 0:
                break

        return finish(
            "improved"
            if initial_score is not None
            and current_score is not None
            and int(current_score.total) < int(initial_score.total)
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
    "DEFAULT_MAX_CYCLES",
    "DEFAULT_MAX_EXACT_SECONDS_PER_STAGE",
    "DEFAULT_MAX_POLISH_PASSES_PER_STAGE",
    "DEFAULT_MAX_POLISH_SEARCH_SECONDS",
    "DEFAULT_MAX_POLISH_SHORTLIST",
    "DEFAULT_MAX_RELOCATE_CHECKS",
    "DEFAULT_MAX_SWAP_CHECKS",
    "ExactFrontierStage",
    "FrontierAlternationResult",
    "FrontierAlternationTelemetry",
    "default_itc2007_exact_frontiers",
    "optimize_itc2007_frontier_alternation",
]
