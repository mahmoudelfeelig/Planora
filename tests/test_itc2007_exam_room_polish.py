from __future__ import annotations

from pathlib import Path
from textwrap import dedent
import time

import benchmarks.itc2007_exam as exam_solver
from benchmarks.itc2007_exam import (
    ITC2007ExamAssignment,
    parse_itc2007_exam,
    validate_itc2007_exam_solution,
)


def _write_room_problem(tmp_path: Path, *, exclusive: bool = False) -> Path:
    path = tmp_path / "room-polish.exam"
    room_constraint = "0, ROOM_EXCLUSIVE" if exclusive else ""
    path.write_text(
        dedent(
            f"""\
            [Exams:4]
            60, 0
            60, 1
            120, 2
            120, 3
            [Periods:1]
            01:06:2026, 09:00:00, 120, 0
            [Rooms:2]
            4, 0
            4, 10
            [PeriodHardConstraints]
            [RoomHardConstraints]
            {room_constraint}
            [InstitutionalWeightings]
            TWOINAROW, 0
            TWOINADAY, 0
            PERIODSPREAD, 0
            NONMIXEDDURATIONS, 5
            FRONTLOAD, 0, 0, 0
            """
        ),
        encoding="utf-8",
    )
    return path


def _suboptimal_assignment() -> tuple[ITC2007ExamAssignment, ...]:
    return (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 0, 1),
        ITC2007ExamAssignment(2, 0, 0),
        ITC2007ExamAssignment(3, 0, 1),
    )


def _write_all_period_closure_problem(tmp_path: Path) -> Path:
    path = tmp_path / "all-period-room-closure.exam"
    path.write_text(
        dedent(
            """\
            [Exams:3]
            60, 0
            60, 1
            60, 2
            [Periods:3]
            01:06:2026, 09:00:00, 120, 0
            01:06:2026, 12:00:00, 120, 0
            02:06:2026, 09:00:00, 120, 0
            [Rooms:2]
            1, 0
            1, 10
            [PeriodHardConstraints]
            [RoomHardConstraints]
            [InstitutionalWeightings]
            TWOINAROW, 0
            TWOINADAY, 0
            PERIODSPREAD, 0
            NONMIXEDDURATIONS, 0
            FRONTLOAD, 0, 0, 0
            """
        ),
        encoding="utf-8",
    )
    return path


def test_room_polish_strictly_improves_independent_score_without_moving_periods(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_room_problem(tmp_path))
    before = validate_itc2007_exam_solution(problem, _suboptimal_assignment())

    assignments, after, telemetry = exam_solver._polish_fixed_period_rooms(
        problem,
        _suboptimal_assignment(),
        deadline=time.perf_counter() + 1.0,
    )

    assert before.feasible
    assert after.feasible
    assert after.objective.total < before.objective.total
    assert after.objective.room_penalty == 0
    assert all(assignment.period == 0 for assignment in assignments)
    assert telemetry["accepted"] is True
    assert telemetry["improved_periods"] == 1
    assert telemetry["score_before"] == before.objective.total
    assert telemetry["score_after"] == after.objective.total


def test_room_polish_preserves_exclusive_room_hard_constraint(tmp_path: Path) -> None:
    problem = parse_itc2007_exam(_write_room_problem(tmp_path, exclusive=True))
    original = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 0, 1),
        ITC2007ExamAssignment(2, 0, 1),
        ITC2007ExamAssignment(3, 0, 1),
    )
    assert validate_itc2007_exam_solution(problem, original).feasible

    assignments, validation, telemetry = exam_solver._polish_fixed_period_rooms(
        problem,
        original,
        deadline=time.perf_counter() + 1.0,
    )

    assert validation.feasible
    exclusive = assignments[0]
    assert (
        sum(
            assignment.room == exclusive.room and assignment.period == exclusive.period
            for assignment in assignments
        )
        == 1
    )
    assert all(assignment.period == 0 for assignment in assignments)
    if telemetry["accepted"]:
        assert (
            validation.objective.total
            < validate_itc2007_exam_solution(problem, original).objective.total
        )


def test_room_polish_runs_cheap_closure_across_all_periods_before_bnb(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_all_period_closure_problem(tmp_path))
    original = tuple(ITC2007ExamAssignment(exam, exam, 1) for exam in range(3))
    before = validate_itc2007_exam_solution(problem, original)

    assignments, after, telemetry = exam_solver._polish_fixed_period_rooms(
        problem,
        original,
        deadline=time.perf_counter() + 1.0,
        max_nodes_per_period=1,
    )

    assert before.feasible
    assert after.feasible
    assert after.hard.total == 0
    assert after.objective.room_penalty == 0
    assert after.objective.total == before.objective.total - 30
    assert all(assignment.room == 0 for assignment in assignments)
    assert telemetry["closure_attempted_periods"] == 3
    assert telemetry["closure_complete_periods"] == 3
    assert telemetry["closure_improved_periods"] == 3
    assert telemetry["closure_moves"] == 3
    assert telemetry["closure_total_periods"] == 3
    assert telemetry["closure_coverage_complete"] is True
    assert telemetry["closure_max_moves_per_period"] == 2
    assert telemetry["closure_budget_seconds"] > 0
    assert telemetry["closure_elapsed_seconds"] >= 0
    assert telemetry["score_after_closure"] == 0
    assert telemetry["room_penalty_after_closure"] == 0
    assert telemetry["mixed_durations_after_closure"] == 0
    assert telemetry["improved_periods"] == 3


def test_room_polish_expiry_and_nonimprovement_return_exact_incumbent(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_room_problem(tmp_path))
    optimal = tuple(ITC2007ExamAssignment(exam, 0, 0) for exam in range(4))

    expired, expired_validation, expired_telemetry = (
        exam_solver._polish_fixed_period_rooms(
            problem,
            _suboptimal_assignment(),
            deadline=time.perf_counter() - 1.0,
        )
    )
    unchanged, unchanged_validation, unchanged_telemetry = (
        exam_solver._polish_fixed_period_rooms(
            problem,
            optimal,
            deadline=time.perf_counter() + 1.0,
        )
    )

    assert expired == _suboptimal_assignment()
    assert expired_validation.feasible
    assert expired_telemetry["accepted"] is False
    assert unchanged == optimal
    assert unchanged_validation.feasible
    assert unchanged_telemetry["accepted"] is False
