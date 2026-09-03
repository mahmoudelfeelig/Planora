from __future__ import annotations

import copy
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from benchmarks.itc2007 import ITC2007Score, score_itc2007_instance_schedule
from core.projected_time_search import (
    _ITCProjectedState,
    _dense_assignment,
    _fast_coordinate_room_lift,
    itc2007_fixed_time_room_cp_eligibility,
    projected_time_search_eligibility,
)
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]


@dataclass(frozen=True)
class ConsolidationDelta:
    time: int
    capacity: int
    stability: int
    total: int


@dataclass
class ITC2007FeedbackTelemetry:
    seed: int
    feedback_rounds_requested: int
    feedback_rounds_completed: int = 0
    feedback_rounds_accepted: int = 0
    iterations: int = 0
    candidates_evaluated: int = 0
    accepted_moves: int = 0
    accepted_by_family: dict[str, int] = field(default_factory=dict)
    consolidation_candidates: int = 0
    consolidation_moves: int = 0
    consolidation_improvement: int = 0
    independent_rescores: int = 0
    validation_calls: int = 0
    round_trace: list[dict[str, Any]] = field(default_factory=list)
    consolidation_trace: list[dict[str, Any]] = field(default_factory=list)
    timing: dict[str, float | int | bool | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ITC2007FeedbackSearchResult:
    status: str
    schedule: Schedule
    improved: bool
    initial_score: ITC2007Score | None
    final_score: ITC2007Score | None
    telemetry: ITC2007FeedbackTelemetry
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


def _actual_majority_rooms(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    state: _ITCProjectedState | None = None,
) -> dict[str, int]:
    """Select each course's incumbent modal room with deterministic ties."""

    active_state = state or _ITCProjectedState(
        inst,
        _copy_schedule(schedule),
        seed=0,
    )
    support: dict[str, Counter[int]] = defaultdict(Counter)
    for activity_id, row in schedule.items():
        code = active_state.course_code[int(activity_id)]
        support[code][int(row["room_id"])] += 1
    primary: dict[str, int] = {}
    for code in sorted(active_state.events_by_course):
        counts = support[code]
        if not counts:
            raise ValueError(f"course_without_room:{code}")
        largest_support = max(counts.values())
        primary[code] = min(
            (room_id for room_id, count in counts.items() if count == largest_support),
            key=lambda room_id: (
                max(
                    0,
                    int(active_state.students[code])
                    - int(active_state.room_capacity_by_id[int(room_id)]),
                ),
                int(room_id),
            ),
        )
    return primary


def _install_actual_majorities(
    state: _ITCProjectedState,
    schedule: Mapping[int, Mapping[str, Any]],
) -> dict[str, int]:
    primary = _actual_majority_rooms(state.inst, schedule, state=state)
    state.use_stability_proxy = True
    state.primary_room = dict(primary)
    state.stability_proxy_by_period = {
        period: state._stability_proxy_for(period, None)
        for period in range(state.period_count)
    }
    state.stability_proxy = int(sum(state.stability_proxy_by_period.values()))
    return primary


def _fragmented_course_proxy(
    state: _ITCProjectedState,
    assignment: Mapping[int, int],
    primary_rooms: Mapping[str, int],
) -> int:
    """Count courses forced away from primary support by time collisions.

    A deterministic capacity-first winner is retained for each period/primary
    room collision.  Every losing course is charged once across the timetable,
    matching the cardinality shape of official room stability more closely
    than charging every displaced lecture independently.
    """

    claimants: dict[tuple[int, int], list[tuple[int, str, int]]] = defaultdict(list)
    for activity_id, period in assignment.items():
        code = str(state.course_code[int(activity_id)])
        primary = int(primary_rooms[code])
        claimants[(int(period), primary)].append(
            (-int(state.students[code]), code, int(activity_id))
        )
    fragmented: set[str] = set()
    for contenders in claimants.values():
        if len(contenders) <= 1:
            continue
        ordered = sorted(contenders)
        fragmented.update(str(code) for _demand, code, _activity in ordered[1:])
    return len(fragmented)


def _majority_aware_room_lift(
    inst: Instance,
    schedule: Schedule,
    primary_rooms: Mapping[str, int],
    *,
    deadline: float,
) -> tuple[Schedule | None, str]:
    """Exactly realize capacity plus primary-room deviations by period.

    With the universal room domains of a lossless ITC-2007 import, each
    period is an independent rectangular assignment. Charging one official
    unit when a lecture does not use its incumbent-majority room makes the
    matching objective equal to projected capacity plus the minimum number of
    primary-room collision deviations for that period.
    """

    if time.perf_counter() >= float(deadline):
        return None, "deadline_exhausted"
    if any(room.availability is not None for room in inst.rooms.values()):
        return None, "requires_universal_room_domains"
    output = _copy_schedule(schedule)
    metadata = dict(inst.sla_targets["itc2007"])
    students = {
        str(key): int(value) for key, value in dict(metadata["course_students"]).items()
    }
    room_ids = tuple(sorted(int(room_id) for room_id in inst.rooms))
    course_code = {
        int(activity_id): str(
            inst.courses[int(inst.activities[int(activity_id)].course_id)].code
        )
        for activity_id in output
    }
    by_period: dict[tuple[int, str, int], list[int]] = defaultdict(list)
    for activity_id, row in output.items():
        by_period[(int(row["week"]), str(row["day"]), int(row["slot"]))].append(
            int(activity_id)
        )
    for _period, raw_activity_ids in sorted(by_period.items()):
        if time.perf_counter() >= float(deadline):
            return None, "deadline_exhausted"
        activity_ids = tuple(sorted(raw_activity_ids))
        if len(activity_ids) > len(room_ids):
            return None, "room_projection_infeasible"
        costs: dict[tuple[int, int], int] = {}
        for activity_id in activity_ids:
            code = course_code[int(activity_id)]
            if code not in primary_rooms:
                return None, f"missing_primary_room:{code}"
            primary = int(primary_rooms[code])
            if primary not in inst.rooms:
                return None, f"invalid_primary_room:{code}"
            demand = int(students[code])
            for room_id in room_ids:
                costs[(int(activity_id), int(room_id))] = max(
                    0,
                    demand - int(inst.rooms[int(room_id)].capacity),
                ) + int(int(room_id) != primary)
        assignment = _dense_assignment(activity_ids, room_ids, costs)
        if time.perf_counter() >= float(deadline):
            return None, "deadline_exhausted"
        if len(assignment) != len(activity_ids):
            return None, "room_projection_infeasible"
        for activity_id, room_id in assignment.items():
            output[int(activity_id)]["room_id"] = int(room_id)
    return output, "majority_aware_optimal_lift"


def _feedback_candidate_is_admissible(
    *,
    current_projected: int,
    current_collision: int,
    best_scalar: int,
    history_bound: int,
    next_projected: int,
    next_collision: int,
    tabu: bool,
    stability_collision_weight: int = 1,
) -> bool:
    """Apply late acceptance to the weighted support-aware scalar."""

    weight = max(1, int(stability_collision_weight))
    current_scalar = int(current_projected) + weight * int(current_collision)
    next_scalar = int(next_projected) + weight * int(next_collision)
    aspiration = next_scalar < int(best_scalar)
    return bool(
        aspiration
        or (
            not tabu
            and (next_scalar <= int(history_bound) or next_scalar <= current_scalar)
        )
    )


def _feedback_iteration_checkpoint(
    *,
    activity_count: int,
    lossless_itc2007: bool = True,
) -> int | None:
    """Bound dense feedback rounds before their reserved room-lift tail."""

    return 96 if bool(lossless_itc2007) and int(activity_count) > 256 else None


def _run_feedback_round(
    inst: Instance,
    schedule: Schedule,
    *,
    deadline: float,
    seed: int,
    candidate_batch_size: int,
    history_length: int,
    stagnation_limit: int,
    iteration_limit: int | None = None,
    stability_collision_weight: int = 1,
    stability_proxy_mode: str = "collision_events",
) -> tuple[Schedule, dict[str, Any]]:
    started = time.perf_counter()
    state = _ITCProjectedState(inst, schedule, seed=int(seed))
    primary = _install_actual_majorities(state, schedule)
    proxy_mode = str(stability_proxy_mode)
    if proxy_mode not in {"collision_events", "fragmented_courses"}:
        raise ValueError(f"unsupported stability proxy mode: {proxy_mode}")
    current_projected = int(state.score)
    current_collision = int(
        state.stability_proxy
        if proxy_mode == "collision_events"
        else _fragmented_course_proxy(state, state.assignment, primary)
    )
    collision_weight = max(1, int(stability_collision_weight))
    current_scalar = int(current_projected + collision_weight * current_collision)
    best_key = (current_scalar, current_projected, current_collision)
    best_assignment = dict(state.assignment)
    history = [int(current_scalar)] * max(1, int(history_length))
    tabu_until: dict[int, int] = {}
    accepted_by_family: Counter[str] = Counter()
    iterations = 0
    candidates_evaluated = 0
    accepted_moves = 0
    last_best_iteration = 0
    termination_reason = "deadline"

    while (
        iteration_limit is None or iterations < int(iteration_limit)
    ) and time.perf_counter() < float(deadline):
        if iterations - last_best_iteration >= max(1, int(stagnation_limit)):
            termination_reason = "stagnation"
            break
        iterations += 1
        candidates = state.candidate_moves(limit=max(8, int(candidate_batch_size)))
        if not candidates:
            termination_reason = "no_candidates"
            break
        history_index = iterations % len(history)
        history_bound = int(history[history_index])
        chosen: tuple[dict[int, int], str, int, int, int] | None = None
        chosen_key: (
            tuple[
                int,
                int,
                int,
                int,
                str,
                tuple[tuple[int, int], ...],
            ]
            | None
        ) = None
        for move, family in candidates:
            if time.perf_counter() >= float(deadline):
                break
            projected_delta = int(state.delta(move))
            if proxy_mode == "collision_events":
                next_collision = int(
                    current_collision + state.stability_proxy_delta(move)
                )
            else:
                candidate_assignment = dict(state.assignment)
                candidate_assignment.update(
                    {int(key): int(value) for key, value in move.items()}
                )
                next_collision = int(
                    _fragmented_course_proxy(
                        state,
                        candidate_assignment,
                        primary,
                    )
                )
            candidates_evaluated += 1
            next_projected = int(current_projected + projected_delta)
            next_scalar = int(next_projected + collision_weight * next_collision)
            tabu = any(
                tabu_until.get(int(activity_id), 0) > iterations for activity_id in move
            )
            if not _feedback_candidate_is_admissible(
                current_projected=current_projected,
                current_collision=current_collision,
                best_scalar=best_key[0],
                history_bound=history_bound,
                next_projected=next_projected,
                next_collision=next_collision,
                tabu=tabu,
                stability_collision_weight=collision_weight,
            ):
                continue
            key = (
                next_scalar,
                next_projected,
                next_collision,
                len(move),
                str(family),
                tuple(sorted((int(key), int(value)) for key, value in move.items())),
            )
            if chosen_key is None or key < chosen_key:
                chosen_key = key
                chosen = (
                    {int(key): int(value) for key, value in move.items()},
                    str(family),
                    next_projected,
                    next_collision,
                    next_scalar,
                )

        history[history_index] = int(current_scalar)
        if chosen is None:
            if dict(state.assignment) != best_assignment:
                state.restore(best_assignment)
                current_projected = int(state.score)
                current_collision = int(
                    state.stability_proxy
                    if proxy_mode == "collision_events"
                    else _fragmented_course_proxy(
                        state,
                        state.assignment,
                        primary,
                    )
                )
                current_scalar = int(
                    current_projected + collision_weight * current_collision
                )
                tabu_until.clear()
                continue
            termination_reason = "local_optimum"
            break

        move, family, next_projected, next_collision, next_scalar = chosen
        state.apply(move)
        observed_proxy = int(
            state.stability_proxy
            if proxy_mode == "collision_events"
            else _fragmented_course_proxy(state, state.assignment, primary)
        )
        if state.score != next_projected or observed_proxy != next_collision:
            raise AssertionError("feedback_incremental_delta_drift")
        current_projected = int(next_projected)
        current_collision = int(next_collision)
        current_scalar = int(next_scalar)
        accepted_moves += 1
        accepted_by_family[family] += 1
        tenure = 5 + state.rng.randrange(8)
        for activity_id in move:
            tabu_until[int(activity_id)] = int(iterations + tenure)
        candidate_best_key = (
            current_scalar,
            current_projected,
            current_collision,
        )
        if candidate_best_key < best_key:
            best_key = candidate_best_key
            best_assignment = dict(state.assignment)
            last_best_iteration = int(iterations)

    if (
        termination_reason == "deadline"
        and iteration_limit is not None
        and iterations >= int(iteration_limit)
        and time.perf_counter() < float(deadline)
    ):
        termination_reason = "iteration_checkpoint"

    return state.materialize(best_assignment), {
        "seed": int(seed),
        "primary_rooms": dict(primary),
        "stability_collision_weight": int(collision_weight),
        "stability_proxy_mode": str(proxy_mode),
        "initial_projected": int(history[0]) - int(state.stability_proxy)
        if not iterations
        else None,
        "best_scalar": int(best_key[0]),
        "best_projected": int(best_key[1]),
        "best_collision": int(best_key[2]),
        "iterations": int(iterations),
        "iteration_limit": (None if iteration_limit is None else int(iteration_limit)),
        "iteration_checkpoint_reached": bool(
            iteration_limit is not None and iterations >= int(iteration_limit)
        ),
        "candidates_evaluated": int(candidates_evaluated),
        "accepted_moves": int(accepted_moves),
        "accepted_by_family": {
            str(key): int(value) for key, value in sorted(accepted_by_family.items())
        },
        "termination_reason": str(termination_reason),
        "elapsed_seconds": float(time.perf_counter() - started),
    }


def _official_consolidation_delta(
    inst: Instance,
    state: _ITCProjectedState,
    schedule: Mapping[int, Mapping[str, Any]],
    support: Mapping[str, Counter[int]],
    *,
    activity_id: int,
    target_period: int,
    target_room: int,
) -> ConsolidationDelta:
    move = {int(activity_id): int(target_period)}
    courses, curriculum_days, _periods = state._affected(move)
    before_time = sum(state.course_penalty[code] for code in courses) + sum(
        state.curriculum_day_penalty[key] for key in curriculum_days
    )
    after_time = sum(state._course_penalty_for(code, move) for code in courses) + sum(
        state._curriculum_day_penalty_for(name, day, move)
        for name, day in curriculum_days
    )
    code = state.course_code[int(activity_id)]
    old_room = int(schedule[int(activity_id)]["room_id"])
    demand = int(state.students[code])
    capacity = max(
        0,
        demand - int(inst.rooms[int(target_room)].capacity),
    ) - max(0, demand - int(inst.rooms[old_room].capacity))
    target_already_used = support[code].get(int(target_room), 0) > 0
    old_room_disappears = support[code].get(old_room, 0) == 1
    stability = int(not target_already_used) - int(old_room_disappears)
    time_delta = int(after_time - before_time)
    total = int(time_delta + capacity + stability)
    return ConsolidationDelta(
        time=time_delta,
        capacity=int(capacity),
        stability=int(stability),
        total=total,
    )


def _room_is_available(inst: Instance, room_id: int, period: int) -> bool:
    room = inst.rooms[int(room_id)]
    if room.availability is None:
        return True
    day = str(inst.days[int(period) // int(inst.slots_per_day)])
    slot = int(period) % int(inst.slots_per_day)
    return (day, slot) in room.availability


def _run_joint_consolidation(
    inst: Instance,
    schedule: Schedule,
    *,
    deadline: float,
    telemetry: ITC2007FeedbackTelemetry,
) -> Schedule:
    output = _copy_schedule(schedule)
    state = _ITCProjectedState(inst, output, seed=int(telemetry.seed))
    primary = _actual_majority_rooms(inst, output, state=state)
    support: dict[str, Counter[int]] = defaultdict(Counter)
    occupancy: dict[tuple[int, int], int] = {}
    for activity_id, row in output.items():
        code = state.course_code[int(activity_id)]
        room_id = int(row["room_id"])
        support[code][room_id] += 1
        occupancy[(int(state.assignment[int(activity_id)]), room_id)] = int(activity_id)

    while time.perf_counter() < float(deadline):
        chosen: tuple[
            tuple[int, int, int, int, int, int, int],
            int,
            int,
            int,
            ConsolidationDelta,
        ] | None = None
        for activity_id in sorted(output):
            if time.perf_counter() >= float(deadline):
                break
            code = state.course_code[int(activity_id)]
            old_room = int(output[int(activity_id)]["room_id"])
            target_room = int(primary[code])
            if old_room == target_room:
                continue
            source_period = int(state.assignment[int(activity_id)])
            for target_period in range(state.period_count):
                if target_period == source_period:
                    continue
                if (int(target_period), target_room) in occupancy:
                    continue
                if not _room_is_available(inst, target_room, target_period):
                    continue
                move = {int(activity_id): int(target_period)}
                if not state.feasible(move):
                    continue
                telemetry.consolidation_candidates += 1
                delta = _official_consolidation_delta(
                    inst,
                    state,
                    output,
                    support,
                    activity_id=int(activity_id),
                    target_period=int(target_period),
                    target_room=target_room,
                )
                if delta.total >= 0:
                    continue
                key = (
                    int(delta.total),
                    int(delta.time),
                    int(delta.capacity),
                    int(delta.stability),
                    int(activity_id),
                    int(target_period),
                    int(target_room),
                )
                if chosen is None or key < chosen[0]:
                    chosen = (
                        key,
                        int(activity_id),
                        int(target_period),
                        int(target_room),
                        delta,
                    )
        if chosen is None:
            break
        _key, activity_id, target_period, target_room, delta = chosen
        source_period = int(state.assignment[activity_id])
        old_room = int(output[activity_id]["room_id"])
        code = state.course_code[activity_id]
        state.apply({activity_id: target_period})
        output[activity_id]["day"] = str(
            inst.days[target_period // int(inst.slots_per_day)]
        )
        output[activity_id]["slot"] = int(target_period % int(inst.slots_per_day))
        output[activity_id]["room_id"] = int(target_room)
        occupancy.pop((source_period, old_room), None)
        occupancy[(target_period, target_room)] = int(activity_id)
        support[code][old_room] -= 1
        if support[code][old_room] <= 0:
            support[code].pop(old_room, None)
        support[code][target_room] += 1
        telemetry.consolidation_moves += 1
        telemetry.consolidation_improvement += int(-delta.total)
        telemetry.consolidation_trace.append(
            {
                "activity_id": int(activity_id),
                "source_period": int(source_period),
                "target_period": int(target_period),
                "source_room": int(old_room),
                "target_room": int(target_room),
                "delta": asdict(delta),
            }
        )
    return output


def optimize_itc2007_feedback(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float,
    seed: int = 0,
    max_feedback_rounds: int = 3,
    feedback_round_seconds: float = 2.0,
    candidate_batch_size: int = 48,
    history_length: int | None = None,
    stagnation_limit: int = 180,
    room_lift_reserve_seconds: float = 0.15,
    coordinate_room_sweeps: int = 8,
    stability_collision_weight: int = 1,
    stability_proxy_mode: str = "collision_events",
    run_consolidation: bool = True,
    validator: Validator | None = None,
) -> ITC2007FeedbackSearchResult:
    """Run incumbent-room feedback and strict joint consolidation fail-closed."""

    started = time.perf_counter()
    original = _copy_schedule(schedule) if isinstance(schedule, Mapping) else {}
    telemetry = ITC2007FeedbackTelemetry(
        seed=int(seed),
        feedback_rounds_requested=max(0, int(max_feedback_rounds)),
    )
    initial_score: ITC2007Score | None = None
    current_score: ITC2007Score | None = None
    validation_fn = validator or _default_validator

    def finish(
        status: str,
        *,
        current: Schedule | None = None,
        validation_errors: Sequence[str] = (),
        eligibility_reasons: Sequence[str] = (),
        error: str | None = None,
    ) -> ITC2007FeedbackSearchResult:
        finished = time.perf_counter()
        improved = bool(
            initial_score is not None
            and current_score is not None
            and current_score.total < initial_score.total
            and current is not None
        )
        selected = (
            _copy_schedule(current) if improved and current is not None else original
        )
        selected_score = current_score if improved else initial_score
        exhausted = bool(finished >= float(deadline))
        telemetry.timing = {
            "elapsed_seconds": float(finished - started),
            "budget_seconds": float(deadline) - float(started),
            "deadline_remaining_seconds": max(0.0, float(deadline) - finished),
            "deadline_overrun_seconds": max(0.0, finished - float(deadline)),
        }
        return ITC2007FeedbackSearchResult(
            status=str(status),
            schedule=selected,
            improved=improved,
            initial_score=initial_score,
            final_score=selected_score,
            telemetry=telemetry,
            validation_errors=tuple(str(value) for value in validation_errors)[:20],
            eligibility_reasons=tuple(str(value) for value in eligibility_reasons),
            deadline_exhausted=exhausted or status == "deadline_exhausted",
            deadline_overrun_seconds=max(0.0, finished - float(deadline)),
            error=error,
        )

    try:
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        if (
            int(max_feedback_rounds) < 0
            or float(feedback_round_seconds) < 0
            or int(candidate_batch_size) < 1
            or int(stagnation_limit) < 1
            or float(room_lift_reserve_seconds) < 0
            or int(coordinate_room_sweeps) < 1
            or int(stability_collision_weight) < 1
            or str(stability_proxy_mode)
            not in {"collision_events", "fragmented_courses"}
        ):
            return finish("ineligible", eligibility_reasons=("invalid_search_bounds",))
        eligible, reasons = projected_time_search_eligibility(inst, original)
        if not eligible:
            return finish("ineligible", eligibility_reasons=reasons)
        metadata = dict(inst.sla_targets["itc2007"])
        expected_weights = {
            "room_capacity": 1,
            "minimum_working_days": 5,
            "curriculum_compactness": 2,
            "room_stability": 1,
        }
        weights = {
            str(key): int(value)
            for key, value in dict(metadata.get("objective_weights") or {}).items()
        }
        if weights != expected_weights:
            return finish(
                "ineligible",
                eligibility_reasons=("requires_standard_itc2007_objective",),
            )
        telemetry.validation_calls += 1
        incumbent_errors = tuple(str(error) for error in validation_fn(inst, original))
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        if incumbent_errors:
            return finish("invalid_incumbent", validation_errors=incumbent_errors)
        initial_score = score_itc2007_instance_schedule(inst, original)
        telemetry.independent_rescores += 1
        current = _copy_schedule(original)
        current_score = initial_score
        try:
            lossless_itc2007, _lossless_reasons = (
                itc2007_fixed_time_room_cp_eligibility(inst, original)
            )
        except Exception:
            lossless_itc2007 = False

        rounds = max(0, int(max_feedback_rounds))
        for round_index in range(rounds):
            now = time.perf_counter()
            available = float(deadline) - now
            minimum_lift = max(0.01, float(room_lift_reserve_seconds))
            if available <= minimum_lift + 0.005:
                break
            round_end = min(
                float(deadline) - 0.005, now + float(feedback_round_seconds)
            )
            search_end = round_end - minimum_lift
            if search_end <= now:
                break
            timed, round_info = _run_feedback_round(
                inst,
                current,
                deadline=float(search_end),
                seed=int(seed) + 65_537 * (round_index + 1),
                candidate_batch_size=int(candidate_batch_size),
                history_length=(
                    int(history_length)
                    if history_length is not None
                    else (64 if len(inst.activities) <= 200 else 128)
                ),
                stagnation_limit=int(stagnation_limit),
                iteration_limit=_feedback_iteration_checkpoint(
                    activity_count=len(inst.activities),
                    lossless_itc2007=bool(lossless_itc2007),
                ),
                stability_collision_weight=int(stability_collision_weight),
                stability_proxy_mode=str(stability_proxy_mode),
            )
            telemetry.feedback_rounds_completed += 1
            telemetry.iterations += int(round_info["iterations"])
            telemetry.candidates_evaluated += int(round_info["candidates_evaluated"])
            telemetry.accepted_moves += int(round_info["accepted_moves"])
            for family, count in round_info["accepted_by_family"].items():
                telemetry.accepted_by_family[family] = telemetry.accepted_by_family.get(
                    family, 0
                ) + int(count)
            if time.perf_counter() >= float(round_end):
                round_info["status"] = "deadline_before_lift"
                telemetry.round_trace.append(round_info)
                continue
            lifted, lift_status = _majority_aware_room_lift(
                inst,
                timed,
                round_info["primary_rooms"],
                deadline=float(round_end),
            )
            round_info["lift_status"] = str(lift_status)
            if lifted is None or time.perf_counter() >= float(round_end):
                round_info["status"] = "lift_failed"
                telemetry.round_trace.append(round_info)
                continue
            candidate, coordinate_status = _fast_coordinate_room_lift(
                inst,
                lifted,
                deadline=float(round_end),
                max_sweeps=int(coordinate_room_sweeps),
            )
            round_info["coordinate_status"] = str(coordinate_status)
            if time.perf_counter() >= float(deadline):
                round_info["status"] = "deadline_before_acceptance"
                telemetry.round_trace.append(round_info)
                break
            candidate_score = score_itc2007_instance_schedule(inst, candidate)
            telemetry.independent_rescores += 1
            telemetry.validation_calls += 1
            candidate_errors = tuple(
                str(error) for error in validation_fn(inst, candidate)
            )
            if time.perf_counter() >= float(deadline):
                round_info["status"] = "deadline_during_validation"
                telemetry.round_trace.append(round_info)
                break
            round_info["official_score"] = int(candidate_score.total)
            round_info["validation_errors"] = list(candidate_errors[:5])
            if not candidate_errors and candidate_score.total < current_score.total:
                current = _copy_schedule(candidate)
                current_score = candidate_score
                telemetry.feedback_rounds_accepted += 1
                round_info["status"] = "accepted"
            else:
                round_info["status"] = "rejected"
            telemetry.round_trace.append(round_info)

        if run_consolidation and time.perf_counter() < float(deadline) - 0.002:
            consolidated = _run_joint_consolidation(
                inst,
                current,
                deadline=float(deadline) - 0.002,
                telemetry=telemetry,
            )
            if consolidated != current and time.perf_counter() < float(deadline):
                consolidated_score = score_itc2007_instance_schedule(inst, consolidated)
                telemetry.independent_rescores += 1
                telemetry.validation_calls += 1
                consolidated_errors = tuple(
                    str(error) for error in validation_fn(inst, consolidated)
                )
                if (
                    time.perf_counter() < float(deadline)
                    and not consolidated_errors
                    and consolidated_score.total < current_score.total
                ):
                    current = consolidated
                    current_score = consolidated_score

        if current_score.total < initial_score.total:
            return finish("improved", current=current)
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted", current=current)
        return finish("no_improvement", current=current)
    except Exception as exc:
        return finish("error", error=f"{type(exc).__name__}:{exc}")


__all__ = [
    "ConsolidationDelta",
    "ITC2007FeedbackSearchResult",
    "ITC2007FeedbackTelemetry",
    "optimize_itc2007_feedback",
]
