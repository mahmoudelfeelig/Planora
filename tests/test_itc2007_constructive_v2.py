from __future__ import annotations

import time

import pytest

from benchmarks.itc2007 import (
    ITC2007Course,
    ITC2007Problem,
    ITC2007Room,
    convert_itc2007_to_instance,
    score_itc2007_instance_schedule,
)
from core.itc2007_constructive_v2 import construct_itc2007_schedule_v2
from utils.specs import validate_schedule_against_instance


def _instance(
    *,
    name: str,
    days: int,
    periods_per_day: int,
    courses: tuple[ITC2007Course, ...],
    room_capacities: tuple[int, ...],
    curricula: dict[str, tuple[str, ...]] | None = None,
    unavailability: tuple[tuple[str, int, int], ...] = (),
):
    return convert_itc2007_to_instance(
        ITC2007Problem(
            name=name,
            days=days,
            periods_per_day=periods_per_day,
            courses=courses,
            rooms=tuple(
                ITC2007Room(name=f"R{index}", capacity=capacity)
                for index, capacity in enumerate(room_capacities)
            ),
            curricula=curricula or {},
            unavailability=unavailability,
        )
    )


def _period(inst, row: dict) -> int:
    return inst.days.index(str(row["day"])) * inst.slots_per_day + int(row["slot"])


def test_v2_is_deterministic_valid_and_reports_the_selected_start() -> None:
    inst = _instance(
        name="v2-deterministic",
        days=3,
        periods_per_day=3,
        courses=(
            ITC2007Course("A", "T0", 2, 2, 28),
            ITC2007Course("B", "T0", 2, 2, 18),
            ITC2007Course("C", "T1", 2, 2, 35),
            ITC2007Course("D", "T2", 2, 2, 12),
            ITC2007Course("E", "T3", 1, 1, 22),
        ),
        room_capacities=(20, 30, 40),
        curricula={
            "Q0": ("A", "C", "D"),
            "Q1": ("B", "C", "E"),
        },
    )

    results = [
        construct_itc2007_schedule_v2(
            inst,
            deadline=time.perf_counter() + 1.0,
            seed=41,
            max_starts=3,
        )
        for _ in range(2)
    ]

    assert results[0].schedule == results[1].schedule
    assert results[0].feasible and results[1].feasible
    assert (
        validate_schedule_against_instance(
            inst,
            results[0].schedule,
            strict_rooms=True,
            require_all_activities=True,
        )
        == []
    )
    assert results[0].attempts == 3
    assert sum(bool(row["selected"]) for row in results[0].attempt_telemetry) == 1
    selected = next(row for row in results[0].attempt_telemetry if row["selected"])
    feasible_scores = [
        int(row["official_score"]["total"])
        for row in results[0].attempt_telemetry
        if row["status"] == "feasible"
    ]
    assert selected["official_score"]["total"] == min(feasible_scores)
    assert selected["return_score_verified"] is True
    assert (
        selected["official_score"]["total"]
        == score_itc2007_instance_schedule(inst, results[0].schedule).total
    )


def test_v2_uses_hall_feasibility_when_room_domains_differ() -> None:
    inst = _instance(
        name="v2-hall",
        days=1,
        periods_per_day=2,
        courses=(
            ITC2007Course("LARGE-A", "TA", 1, 1, 25),
            ITC2007Course("LARGE-B", "TB", 1, 1, 25),
            ITC2007Course("SMALL", "TC", 1, 1, 8),
        ),
        room_capacities=(10, 30),
    )
    inst.hard_constraints["enforce_room_capacity"] = True

    result = construct_itc2007_schedule_v2(
        inst,
        deadline=time.perf_counter() + 1.0,
        seed=7,
        max_starts=2,
    )

    assert result.feasible
    assert (
        validate_schedule_against_instance(
            inst,
            result.schedule,
            strict_rooms=True,
            require_all_activities=True,
        )
        == []
    )
    by_code = {
        inst.courses[inst.activities[activity_id].course_id].code: _period(inst, row)
        for activity_id, row in result.schedule.items()
    }
    assert by_code["LARGE-A"] != by_code["LARGE-B"]
    assert any(row["hall_checks"] > 0 for row in result.attempt_telemetry)


def test_v2_mwd_guidance_spreads_repeated_lectures_across_days() -> None:
    inst = _instance(
        name="v2-mwd",
        days=2,
        periods_per_day=2,
        courses=(ITC2007Course("A", "TA", 2, 2, 10),),
        room_capacities=(20,),
    )

    result = construct_itc2007_schedule_v2(
        inst,
        deadline=time.perf_counter() + 0.5,
        seed=3,
        max_starts=1,
        strategies=("spread",),
    )

    assert result.feasible
    assert {str(row["day"]) for row in result.schedule.values()} == {"D0", "D1"}
    assert (
        score_itc2007_instance_schedule(inst, result.schedule).minimum_working_days == 0
    )


def test_v2_fails_closed_for_deadline_and_validator_rejection() -> None:
    inst = _instance(
        name="v2-fail-closed",
        days=1,
        periods_per_day=2,
        courses=(ITC2007Course("A", "TA", 1, 1, 10),),
        room_capacities=(20,),
    )

    expired = construct_itc2007_schedule_v2(
        inst,
        deadline=time.perf_counter() - 0.001,
        seed=1,
    )
    rejected = construct_itc2007_schedule_v2(
        inst,
        deadline=time.perf_counter() + 0.5,
        seed=1,
        max_starts=1,
        validator=lambda _inst, _schedule: ("external rejection",),
    )

    assert expired.schedule is None
    assert expired.status == "deadline_exhausted"
    assert expired.attempts == 0
    assert expired.deadline_exhausted
    assert rejected.schedule is None
    assert rejected.status == "invalid_candidate"
    assert rejected.attempt_telemetry[0]["validation_errors"] == ["external rejection"]


def test_v2_completes_a_dense_general_conflict_fixture_within_its_deadline() -> None:
    courses = tuple(
        ITC2007Course(
            name=f"C{index}",
            teacher=f"T{index % 10}",
            lectures=2,
            minimum_working_days=2,
            students=10 + index % 35,
        )
        for index in range(30)
    )
    curricula = {
        f"Q{index}": tuple(f"C{(index * 3 + offset) % 30}" for offset in range(5))
        for index in range(12)
    }
    inst = _instance(
        name="v2-dense",
        days=5,
        periods_per_day=5,
        courses=courses,
        room_capacities=(20, 30, 40, 50),
        curricula=curricula,
    )
    deadline = time.perf_counter() + 1.0

    result = construct_itc2007_schedule_v2(
        inst,
        deadline=deadline,
        seed=17,
        max_starts=4,
    )

    assert result.feasible, result.to_dict()
    assert result.elapsed_seconds < 1.0
    assert result.deadline_exhausted is False
    assert len(result.schedule) == 60
    assert (
        validate_schedule_against_instance(
            inst,
            result.schedule,
            strict_rooms=True,
            require_all_activities=True,
        )
        == []
    )


@pytest.mark.timing_sensitive
def test_v2_incumbent_first_budgeting_does_not_truncate_every_large_start() -> None:
    courses = tuple(
        ITC2007Course(
            name=f"C{index}",
            teacher=f"T{index % 35}",
            lectures=3,
            minimum_working_days=2,
            students=15 + (index * 13) % 80,
        )
        for index in range(80)
    )
    curricula = {
        f"Q{index}": tuple(f"C{(index * 7 + offset * 11) % 80}" for offset in range(5))
        for index in range(40)
    }
    inst = _instance(
        name="v2-large-start-admission",
        days=5,
        periods_per_day=9,
        courses=courses,
        room_capacities=tuple(25 + 5 * index for index in range(15)),
        curricula=curricula,
    )

    result = construct_itc2007_schedule_v2(
        inst,
        deadline=time.perf_counter() + 1.0,
        seed=17,
        max_starts=4,
    )

    assert result.feasible, result.to_dict()
    assert len(result.schedule) == 240
    selected = next(row for row in result.attempt_telemetry if row["selected"])
    assert selected["starts_requested"] == 4
    assert selected["starts_completed"] == result.attempts
    assert (
        validate_schedule_against_instance(
            inst,
            result.schedule,
            strict_rooms=True,
            require_all_activities=True,
        )
        == []
    )
