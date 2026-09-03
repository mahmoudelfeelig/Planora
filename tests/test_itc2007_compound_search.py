from __future__ import annotations

import time

from benchmarks.itc2007 import (
    ITC2007Course,
    ITC2007Problem,
    ITC2007Room,
    convert_itc2007_to_instance,
    score_itc2007_instance_schedule,
)
from core.itc2007_compound_search import optimize_itc2007_compound
from utils.specs import validate_schedule_against_instance


def _instance():
    return convert_itc2007_to_instance(
        ITC2007Problem(
            name="atomic-compound-barrier",
            days=3,
            periods_per_day=4,
            courses=(
                ITC2007Course("A", "TA", 3, 2, 10),
                ITC2007Course("B", "TB", 4, 3, 10),
                ITC2007Course("C", "TC", 3, 2, 10),
            ),
            rooms=(
                ITC2007Room("R1", 20),
                ITC2007Room("R2", 20),
            ),
            curricula={},
            unavailability=(),
        )
    )


def _by_code(inst) -> dict[str, tuple[int, ...]]:
    result: dict[str, list[int]] = {}
    for activity_id, activity in inst.activities.items():
        code = str(inst.courses[int(activity.course_id)].code)
        result.setdefault(code, []).append(int(activity_id))
    return {code: tuple(sorted(values)) for code, values in result.items()}


def _schedule(inst) -> dict[int, dict]:
    by_code = _by_code(inst)
    a1, a2, a3 = by_code["A"]
    b1, b2, b3, b4 = by_code["B"]
    c1, c2, c3 = by_code["C"]
    placement = {
        a1: (0, 0, 1),
        a2: (0, 2, 2),
        a3: (1, 2, 2),
        b1: (0, 1, 1),
        b2: (1, 0, 2),
        b3: (2, 0, 2),
        b4: (0, 2, 1),
        c1: (1, 1, 1),
        c2: (1, 3, 1),
        c3: (0, 3, 1),
    }
    output: dict[int, dict] = {}
    for activity_id, activity in inst.activities.items():
        day, slot, room_id = placement[int(activity_id)]
        output[int(activity_id)] = {
            "week": 1,
            "day": f"D{day}",
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


def test_atomic_pair_crosses_intermediate_official_barrier() -> None:
    inst = _instance()
    incumbent = _schedule(inst)
    result = optimize_itc2007_compound(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        seed=17,
    )

    assert result.status == "improved"
    assert result.improved
    assert result.initial_score is not None
    assert result.final_score is not None
    assert result.final_score.total < result.initial_score.total
    assert result.telemetry.accepted_compounds == 1
    assert result.telemetry.barrier_crossings == 1
    assert len(result.telemetry.best_trajectory) == 2
    assert (
        result.telemetry.best_trajectory[0]["intermediate_score"]["total"]
        > result.initial_score.total
    )
    assert result.telemetry.best_trajectory[0]["accepted_independently"] is False
    assert not validate_schedule_against_instance(
        inst,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    )
    assert score_itc2007_instance_schedule(inst, result.schedule) == result.final_score


def test_same_seed_replays_the_same_compound() -> None:
    inst = _instance()
    incumbent = _schedule(inst)

    left = optimize_itc2007_compound(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        seed=991,
    )
    right = optimize_itc2007_compound(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        seed=991,
    )

    assert left.status == right.status == "improved"
    assert left.schedule == right.schedule
    assert left.initial_score == right.initial_score
    assert left.final_score == right.final_score
    assert left.telemetry.best_trajectory == right.telemetry.best_trajectory


def test_expired_deadline_returns_the_exact_incumbent() -> None:
    inst = _instance()
    incumbent = _schedule(inst)

    result = optimize_itc2007_compound(
        inst,
        incumbent,
        deadline=time.perf_counter() - 0.001,
        seed=17,
    )

    assert result.status == "deadline_exhausted"
    assert result.deadline_exhausted
    assert not result.improved
    assert result.schedule == incumbent
    assert result.telemetry.validation_calls == 0


def test_deadline_crossed_in_final_validation_discards_compound() -> None:
    inst = _instance()
    incumbent = _schedule(inst)
    validation_calls = 0

    def slow_second_validation(instance, candidate):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls > 1:
            time.sleep(0.02)
        return validate_schedule_against_instance(
            instance,
            dict(candidate),
            strict_rooms=True,
            require_all_activities=True,
        )

    result = optimize_itc2007_compound(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.01,
        seed=17,
        validator=slow_second_validation,
    )

    assert result.status == "deadline_exhausted"
    assert not result.improved
    assert result.schedule == incumbent


def test_non_improving_incumbent_is_returned_unchanged() -> None:
    inst = _instance()
    incumbent = _schedule(inst)
    by_code = _by_code(inst)
    for activity_id in by_code["A"]:
        incumbent[activity_id]["room_id"] = 2
    for activity_id in by_code["B"]:
        incumbent[activity_id]["room_id"] = 1

    result = optimize_itc2007_compound(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        seed=31,
    )

    assert result.status == "no_improvement"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.initial_score == result.final_score
