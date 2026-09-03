from __future__ import annotations

from collections import Counter, defaultdict
import time

from benchmarks.itc2007 import (
    ITC2007Course,
    ITC2007Problem,
    ITC2007Room,
    convert_itc2007_to_instance,
    score_itc2007_instance_schedule,
)
from core.itc2007_feedback_search import (
    _ITCProjectedState,
    _actual_majority_rooms,
    _feedback_candidate_is_admissible,
    _feedback_iteration_checkpoint,
    _fragmented_course_proxy,
    _majority_aware_room_lift,
    _official_consolidation_delta,
    _run_feedback_round,
    optimize_itc2007_feedback,
)
from core.projected_time_search import _capacity_lift
from utils.specs import validate_schedule_against_instance


def _instance(
    *,
    name: str = "feedback-search",
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


def _support_counts(state, schedule):
    support: dict[str, Counter[int]] = defaultdict(Counter)
    for activity_id, row in schedule.items():
        support[state.course_code[int(activity_id)]][int(row["room_id"])] += 1
    return support


def test_joint_consolidation_delta_matches_the_independent_official_score() -> None:
    inst = _instance()
    incumbent = _schedule(inst, {1: (0, 0, 1), 2: (0, 1, 2)})
    state = _ITCProjectedState(inst, incumbent, seed=7)
    primary = _actual_majority_rooms(inst, incumbent, state=state)
    support = _support_counts(state, incumbent)

    predicted = _official_consolidation_delta(
        inst,
        state,
        incumbent,
        support,
        activity_id=2,
        target_period=2,
        target_room=primary["A"],
    )
    candidate = {activity_id: dict(row) for activity_id, row in incumbent.items()}
    candidate[2]["slot"] = 2
    candidate[2]["room_id"] = 1
    actual = (
        score_itc2007_instance_schedule(inst, candidate).total
        - score_itc2007_instance_schedule(inst, incumbent).total
    )

    assert predicted.time == 0
    assert predicted.capacity == 0
    assert predicted.stability == -1
    assert predicted.total == actual == -1


def test_joint_consolidation_preserves_time_and_room_feasibility() -> None:
    inst = _instance()
    incumbent = _schedule(inst, {1: (0, 0, 1), 2: (0, 1, 2)})

    result = optimize_itc2007_feedback(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        max_feedback_rounds=0,
        run_consolidation=True,
    )

    assert result.status == "improved"
    assert result.improved
    assert result.initial_score is not None
    assert result.final_score is not None
    assert result.final_score.total == result.initial_score.total - 1
    assert result.telemetry.consolidation_moves == 1
    assert not validate_schedule_against_instance(
        inst,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    )
    assert {row["room_id"] for row in result.schedule.values()} == {1}
    assert {row["slot"] for row in result.schedule.values()} == {0, 2}


def test_feedback_round_returns_a_valid_strict_improvement() -> None:
    inst = _instance(
        name="time-room-feedback",
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

    result = optimize_itc2007_feedback(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.8,
        seed=17,
        max_feedback_rounds=1,
        feedback_round_seconds=0.5,
        candidate_batch_size=24,
        room_lift_reserve_seconds=0.15,
        run_consolidation=False,
    )

    assert result.status == "improved"
    assert result.initial_score is not None
    assert result.final_score is not None
    assert result.final_score.total < result.initial_score.total
    assert result.telemetry.feedback_rounds_accepted == 1
    assert not validate_schedule_against_instance(
        inst,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    )


def test_feedback_iteration_checkpoint_reports_bounds_and_preserves_deadline() -> None:
    inst = _instance(
        name="bounded-feedback",
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
    deadline = time.perf_counter() + 0.5

    _timed, telemetry = _run_feedback_round(
        inst,
        incumbent,
        deadline=deadline,
        seed=17,
        candidate_batch_size=16,
        history_length=32,
        stagnation_limit=40,
        iteration_limit=2,
    )

    assert telemetry["iterations"] <= 2
    assert telemetry["iteration_limit"] == 2
    assert telemetry["iteration_checkpoint_reached"] is True
    assert telemetry["termination_reason"] in {
        "iteration_checkpoint",
        "local_optimum",
    }
    assert time.perf_counter() < deadline
    assert _feedback_iteration_checkpoint(activity_count=256) is None
    assert _feedback_iteration_checkpoint(activity_count=257) == 96
    assert (
        _feedback_iteration_checkpoint(
            activity_count=257,
            lossless_itc2007=False,
        )
        is None
    )


def test_majority_aware_lift_preserves_primary_rooms_across_capacity_ties() -> None:
    inst = _instance(
        name="majority-capacity-tie",
        days=1,
        periods_per_day=2,
        courses=(
            ITC2007Course("A", "TA", 1, 1, 10),
            ITC2007Course("B", "TB", 2, 1, 10),
        ),
    )
    # A's actual majority is R2. The capacity-only deterministic matching uses
    # R1 for A in the second period because both rooms have equal overflow,
    # introducing an avoidable room-stability penalty.
    incumbent = _schedule(
        inst,
        {
            1: (0, 0, 1),
            2: (0, 0, 2),
            3: (0, 1, 2),
        },
    )
    timed = {activity_id: dict(row) for activity_id, row in incumbent.items()}
    timed[3]["room_id"] = 1
    primary = {"A": 1, "B": 2}

    capacity_only, status = _capacity_lift(
        inst,
        timed,
        deadline=time.perf_counter() + 0.3,
    )
    majority_aware, aware_status = _majority_aware_room_lift(
        inst,
        timed,
        primary,
        deadline=time.perf_counter() + 0.3,
    )

    assert status == "capacity_optimal_lift"
    assert capacity_only is not None
    assert aware_status == "majority_aware_optimal_lift"
    assert majority_aware is not None
    assert score_itc2007_instance_schedule(inst, capacity_only).room_capacity == 0
    assert score_itc2007_instance_schedule(inst, majority_aware).room_capacity == 0
    assert score_itc2007_instance_schedule(inst, capacity_only).room_stability == 1
    assert score_itc2007_instance_schedule(inst, majority_aware).room_stability == 0
    assert majority_aware[3]["room_id"] == 2


def test_non_improving_search_returns_the_exact_incumbent() -> None:
    inst = _instance()
    incumbent = _schedule(inst, {1: (0, 0, 1), 2: (0, 1, 1)})

    result = optimize_itc2007_feedback(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.3,
        max_feedback_rounds=0,
        run_consolidation=True,
    )

    assert result.status == "no_improvement"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.initial_score == result.final_score


def test_expired_deadline_returns_the_exact_incumbent() -> None:
    inst = _instance()
    incumbent = _schedule(inst, {1: (0, 0, 1), 2: (0, 1, 2)})

    result = optimize_itc2007_feedback(
        inst,
        incumbent,
        deadline=time.perf_counter() - 0.001,
        max_feedback_rounds=3,
    )

    assert result.status == "deadline_exhausted"
    assert result.deadline_exhausted
    assert not result.improved
    assert result.schedule == incumbent
    assert result.telemetry.validation_calls == 0


def test_scalar_feedback_crosses_a_projected_score_barrier() -> None:
    # The official-unit scalar must accept a +1 projected move when it removes
    # two incumbent-majority collisions. A lexicographic projected-first rule
    # would reject exactly this research neighborhood.
    assert _feedback_candidate_is_admissible(
        current_projected=4,
        current_collision=4,
        best_scalar=8,
        history_bound=8,
        next_projected=5,
        next_collision=2,
        tabu=False,
    )
    assert not _feedback_candidate_is_admissible(
        current_projected=4,
        current_collision=4,
        best_scalar=8,
        history_bound=8,
        next_projected=9,
        next_collision=2,
        tabu=False,
    )


def test_support_weight_can_prioritize_room_collisions_without_changing_default() -> (
    None
):
    move = {
        "current_projected": 4,
        "current_collision": 4,
        "best_scalar": 8,
        "history_bound": 8,
        "next_projected": 7,
        "next_collision": 2,
        "tabu": False,
    }

    assert not _feedback_candidate_is_admissible(**move)
    assert _feedback_candidate_is_admissible(
        **move,
        stability_collision_weight=2,
    )


def test_feedback_rejects_nonpositive_support_weight() -> None:
    inst = _instance()
    incumbent = _schedule(inst, {1: (0, 0, 1), 2: (0, 1, 2)})

    result = optimize_itc2007_feedback(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        stability_collision_weight=0,
    )

    assert result.status == "ineligible"
    assert result.eligibility_reasons == ("invalid_search_bounds",)
    assert result.schedule == incumbent


def test_fragmented_course_proxy_charges_a_repeated_support_break_once() -> None:
    inst = _instance(
        courses=(
            ITC2007Course("A", "TA", 1, 1, 10),
            ITC2007Course("B", "TB", 2, 1, 10),
        ),
    )
    schedule = _schedule(
        inst,
        {
            1: (0, 0, 1),
            2: (0, 0, 2),
            3: (0, 1, 1),
        },
    )
    state = _ITCProjectedState(inst, schedule, seed=17)
    primary = {"A": 1, "B": 1}

    assert _fragmented_course_proxy(state, state.assignment, primary) == 1
    separated = dict(state.assignment)
    separated[2] = 2
    assert _fragmented_course_proxy(state, separated, primary) == 0
