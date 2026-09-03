from __future__ import annotations

import copy
import time

from benchmarks.itc2007 import (
    ITC2007Course,
    ITC2007Problem,
    ITC2007Room,
    convert_itc2007_to_instance,
    score_itc2007_instance_schedule,
)
from core import itc2007_iterative_feedback_dispatcher as dispatcher
from core.itc2007_iterative_feedback_dispatcher import (
    IterativeFeedbackBounds,
    optimize_itc2007_iterative_feedback,
)
from utils.specs import validate_schedule_against_instance


def _instance(
    *,
    name: str = "iterative-feedback",
    days: int = 1,
    periods_per_day: int = 3,
    courses: tuple[ITC2007Course, ...] = (ITC2007Course("A", "TA", 2, 1, 10),),
    room_capacities: tuple[int, ...] = (20, 20),
):
    return convert_itc2007_to_instance(
        ITC2007Problem(
            name=name,
            days=int(days),
            periods_per_day=int(periods_per_day),
            courses=courses,
            rooms=tuple(
                ITC2007Room(f"R{index}", int(capacity))
                for index, capacity in enumerate(room_capacities, start=1)
            ),
            curricula={},
            unavailability=(),
        )
    )


def _schedule(inst, placements: dict[int, tuple[int, int, int]]):
    output: dict[int, dict] = {}
    for activity_id, activity in inst.activities.items():
        day, slot, room_id = placements[int(activity_id)]
        output[int(activity_id)] = {
            "week": 1,
            "day": f"D{int(day)}",
            "slot": int(slot),
            "duration": int(activity.duration),
            "room_id": int(room_id),
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
            "source": "test",
        }
    return output


def _bounds(
    *,
    feedback_rounds: int = 0,
    feedback_iterations_per_round: int = 2,
    time_rooted_relocations: int = 0,
    component_rooted_relocations: int = 0,
    stability_collision_weight: int = 1,
    stability_proxy_mode: str = "collision_events",
) -> IterativeFeedbackBounds:
    return IterativeFeedbackBounds(
        feedback_rounds=int(feedback_rounds),
        feedback_iterations_per_round=int(feedback_iterations_per_round),
        candidate_batch_size=16,
        history_length=32,
        stagnation_limit=40,
        coordinate_room_sweeps=3,
        time_rooted_relocations=int(time_rooted_relocations),
        component_rooted_relocations=int(component_rooted_relocations),
        stability_collision_weight=int(stability_collision_weight),
        stability_proxy_mode=str(stability_proxy_mode),
    )


def test_support_weight_is_part_of_the_fixed_dispatcher_contract() -> None:
    assert _bounds(stability_collision_weight=2).validation_errors() == ()
    assert _bounds(stability_collision_weight=0).validation_errors() == (
        "nonpositive_bound:stability_collision_weight",
    )
    assert _bounds(stability_proxy_mode="fragmented_courses").validation_errors() == ()
    assert _bounds(stability_proxy_mode="unknown").validation_errors() == (
        "invalid_stability_proxy_mode",
    )


def test_component_root_reaches_a_stability_only_course() -> None:
    inst = _instance()
    incumbent = _schedule(inst, {1: (0, 0, 1), 2: (0, 1, 2)})
    original = copy.deepcopy(incumbent)
    initial = score_itc2007_instance_schedule(inst, incumbent)

    result = optimize_itc2007_iterative_feedback(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        seed=17,
        bounds=_bounds(component_rooted_relocations=1),
    )

    assert result.status == "improved"
    assert result.improved
    assert result.initial_score == initial
    assert result.final_score is not None
    assert result.final_score.total == initial.total - 1
    assert result.final_score.room_stability == 0
    assert result.telemetry.relocation_moves_accepted == 1
    accepted = [
        row for row in result.telemetry.relocation_trace if row["status"] == "accepted"
    ]
    assert [row["phase"] for row in accepted] == ["components"]
    assert incumbent == original
    assert not validate_schedule_against_instance(
        inst,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    )


def test_component_root_includes_capacity_without_time_penalties() -> None:
    inst = _instance(
        name="capacity-component-root",
        courses=(ITC2007Course("A", "TA", 1, 1, 30),),
        room_capacities=(10, 40),
    )
    incumbent = _schedule(inst, {1: (0, 0, 1)})

    result = optimize_itc2007_iterative_feedback(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        bounds=_bounds(component_rooted_relocations=1),
    )

    assert result.status == "improved"
    assert result.initial_score is not None
    assert result.final_score is not None
    assert result.initial_score.room_capacity == 20
    assert result.final_score.room_capacity == 0
    assert result.final_score.total == 0


def test_same_seed_canonicalizes_exchangeable_lecture_ids() -> None:
    inst = _instance()
    incumbent = _schedule(inst, {1: (0, 0, 1), 2: (0, 1, 2)})
    exchanged = copy.deepcopy(incumbent)
    exchanged[1], exchanged[2] = exchanged[2], exchanged[1]
    bounds = _bounds(component_rooted_relocations=1)

    left = optimize_itc2007_iterative_feedback(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        seed=991,
        bounds=bounds,
    )
    right = optimize_itc2007_iterative_feedback(
        inst,
        exchanged,
        deadline=time.perf_counter() + 0.5,
        seed=991,
        bounds=bounds,
    )

    assert left.status == right.status == "improved"
    assert left.schedule == right.schedule
    assert left.initial_score == right.initial_score
    assert left.final_score == right.final_score
    assert left.telemetry.canonicalizations == right.telemetry.canonicalizations


def test_fixed_feedback_checkpoint_replays_the_same_schedule() -> None:
    inst = _instance(
        name="fixed-feedback-checkpoint",
        days=2,
        periods_per_day=2,
        courses=(
            ITC2007Course("A", "TA", 2, 2, 10),
            ITC2007Course("B", "TB", 2, 2, 10),
        ),
    )
    incumbent = _schedule(
        inst,
        {
            1: (0, 0, 1),
            2: (0, 1, 2),
            3: (1, 0, 1),
            4: (1, 1, 2),
        },
    )
    bounds = _bounds(feedback_rounds=1, feedback_iterations_per_round=2)

    left = optimize_itc2007_iterative_feedback(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.8,
        seed=17,
        bounds=bounds,
    )
    right = optimize_itc2007_iterative_feedback(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.8,
        seed=17,
        bounds=bounds,
    )

    assert left.status == right.status
    assert left.schedule == right.schedule
    assert left.final_score == right.final_score
    assert left.telemetry.feedback_rounds_completed == 1
    assert right.telemetry.feedback_rounds_completed == 1
    assert left.telemetry.round_trace[0]["iterations"] == 2
    assert right.telemetry.round_trace[0]["iterations"] == 2
    assert left.telemetry.round_trace[0]["checkpoint_complete"] is True
    assert right.telemetry.round_trace[0]["checkpoint_complete"] is True


def test_incomplete_wall_cut_feedback_checkpoint_discards_the_chain(
    monkeypatch,
) -> None:
    inst = _instance()
    incumbent = _schedule(inst, {1: (0, 0, 1), 2: (0, 1, 2)})

    def incomplete_round(instance, schedule, **_kwargs):
        return copy.deepcopy(schedule), {
            "iterations": 1,
            "accepted_moves": 1,
            "candidates_evaluated": 4,
            "termination_reason": "deadline",
        }

    monkeypatch.setattr(dispatcher, "_run_feedback_round", incomplete_round)
    result = optimize_itc2007_iterative_feedback(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.8,
        bounds=_bounds(feedback_rounds=1, feedback_iterations_per_round=2),
    )

    assert result.status == "deadline_exhausted"
    assert result.deadline_exhausted
    assert not result.improved
    assert result.schedule == incumbent
    assert result.telemetry.feedback_rounds_completed == 0
    assert result.telemetry.round_trace[0]["status"] == "incomplete_checkpoint"


def test_mutating_validator_fails_closed_without_touching_the_incumbent() -> None:
    inst = _instance()
    incumbent = _schedule(inst, {1: (0, 0, 1), 2: (0, 1, 2)})
    original = copy.deepcopy(incumbent)
    validation_calls = 0

    def mutating_second_validation(instance, candidate):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 2:
            first = min(candidate)
            candidate[first]["slot"] = 99
        return ()

    result = optimize_itc2007_iterative_feedback(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        bounds=_bounds(component_rooted_relocations=1),
        validator=mutating_second_validation,
    )

    assert result.status == "mutation_detected"
    assert result.error == "validator_mutated_relocation_candidate"
    assert not result.improved
    assert result.schedule == original
    assert incumbent == original
    assert result.telemetry.mutation_guard_failures == 1


def test_rejected_candidate_is_not_rescored_or_exposed() -> None:
    inst = _instance()
    incumbent = _schedule(inst, {1: (0, 0, 1), 2: (0, 1, 2)})
    validation_calls = 0

    def reject_second_validation(instance, candidate):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 2:
            return ("synthetic_rejection",)
        return validate_schedule_against_instance(
            instance,
            dict(candidate),
            strict_rooms=True,
            require_all_activities=True,
        )

    result = optimize_itc2007_iterative_feedback(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        bounds=_bounds(component_rooted_relocations=1),
        validator=reject_second_validation,
    )

    assert result.status == "invalid_candidate"
    assert result.validation_errors == ("synthetic_rejection",)
    assert not result.improved
    assert result.schedule == incumbent
    assert result.telemetry.validation_calls == 2
    assert result.telemetry.independent_rescores == 1


def test_mutating_scorer_fails_closed_without_exposing_the_candidate(
    monkeypatch,
) -> None:
    inst = _instance()
    incumbent = _schedule(inst, {1: (0, 0, 1), 2: (0, 1, 2)})
    original = copy.deepcopy(incumbent)
    real_scorer = dispatcher.score_itc2007_instance_schedule
    score_calls = 0

    def mutating_second_score(instance, candidate):
        nonlocal score_calls
        score_calls += 1
        score = real_scorer(instance, candidate)
        if score_calls == 2:
            first = min(candidate)
            candidate[first]["slot"] = 99
        return score

    monkeypatch.setattr(
        dispatcher,
        "score_itc2007_instance_schedule",
        mutating_second_score,
    )
    result = optimize_itc2007_iterative_feedback(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        bounds=_bounds(component_rooted_relocations=1),
    )

    assert result.status == "mutation_detected"
    assert result.error == "scorer_mutated_relocation_candidate"
    assert not result.improved
    assert result.schedule == original
    assert incumbent == original
    assert result.telemetry.independent_rescores == 2
    assert result.telemetry.mutation_guard_failures == 1


def test_expired_deadline_returns_the_exact_incumbent_without_validation() -> None:
    inst = _instance()
    incumbent = _schedule(inst, {1: (0, 0, 1), 2: (0, 1, 2)})

    result = optimize_itc2007_iterative_feedback(
        inst,
        incumbent,
        deadline=time.perf_counter() - 0.001,
        bounds=_bounds(component_rooted_relocations=1),
    )

    assert result.status == "deadline_exhausted"
    assert result.deadline_exhausted
    assert not result.improved
    assert result.schedule == incumbent
    assert result.telemetry.validation_calls == 0
