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


def _write_coupled_pressure_problem(tmp_path: Path) -> Path:
    path = tmp_path / "coupled-pressure.exam"
    path.write_text(
        dedent(
            """\
            [Exams:4]
            60, 0, 1, 2, 3, 4, 5
            60, 6, 7, 8, 9
            60, 10, 11, 12, 13, 14, 15
            60, 16, 17, 18, 19
            [Periods:2]
            01:06:2026, 09:00:00, 120, 0
            01:06:2026, 12:00:00, 120, 0
            [Rooms:2]
            10, 0
            10, 50
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


def _write_streamed_pressure_problem(tmp_path: Path) -> Path:
    path = tmp_path / "streamed-pressure.exam"
    exams = "\n".join(f"60, {student}" for student in range(12))
    periods = "\n".join(f"{day:02d}:06:2026, 09:00:00, 120, 0" for day in range(1, 8))
    path.write_text(
        dedent(
            f"""\
            [Exams:12]
            {exams}
            [Periods:7]
            {periods}
            [Rooms:2]
            1, 0
            1, 50
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


def _write_negative_temporal_sweep_problem(tmp_path: Path) -> Path:
    path = tmp_path / "negative-temporal-sweep.exam"
    path.write_text(
        dedent(
            """\
            [Exams:2]
            60, 0
            60, 0
            [Periods:3]
            01:06:2026, 09:00:00, 120, 50
            02:06:2026, 09:00:00, 120, 0
            03:06:2026, 09:00:00, 120, 0
            [Rooms:2]
            1, 0
            1, 50
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


def test_negative_temporal_sweep_accepts_exact_repacked_single_move(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_negative_temporal_sweep_problem(tmp_path))
    original = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 1, 0),
    )
    before = validate_itc2007_exam_solution(problem, original)

    assignments, after, telemetry = exam_solver._polish_exam_periods(
        problem,
        original,
        deadline=time.perf_counter() + 1.0,
        max_rounds=2,
        max_units_per_round=1,
        max_targets_per_unit=1,
        max_exchange_candidates=0,
    )

    assert before.feasible
    assert before.objective.total == 50
    assert after.feasible
    assert after.hard.total == 0
    assert after.objective.total == 0
    assert assignments != original
    assert telemetry["accepted_negative_temporal_moves"] == 1
    assert telemetry["negative_temporal_sweep_attempts"] >= 1


def test_negative_temporal_sweep_expiry_fails_closed(tmp_path: Path) -> None:
    problem = parse_itc2007_exam(_write_negative_temporal_sweep_problem(tmp_path))
    original = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 1, 0),
    )
    before = validate_itc2007_exam_solution(problem, original)

    assignments, after, telemetry = exam_solver._polish_exam_periods(
        problem,
        original,
        deadline=time.perf_counter() - 1.0,
        max_exchange_candidates=0,
    )

    assert assignments == original
    assert after == before
    assert telemetry["accepted_negative_temporal_moves"] == 0


def test_coupled_period_room_lns_removes_penalized_room_pressure(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_coupled_pressure_problem(tmp_path))
    original = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 0, 1),
        ITC2007ExamAssignment(2, 1, 0),
        ITC2007ExamAssignment(3, 1, 1),
    )
    before = validate_itc2007_exam_solution(problem, original)

    assignments, after, telemetry = exam_solver._optimize_exam_period_room_neighborhood(
        problem,
        original,
        deadline=time.perf_counter() + 2.0,
        seed=17,
    )

    assert before.feasible
    assert before.objective.room_penalty == 100
    assert after.feasible
    assert after.hard.total == 0
    assert after.objective.room_penalty == 0
    assert after.objective.total == 0
    assert {row.exam for row in assignments} == {0, 1, 2, 3}
    assert telemetry["accepted"] is True
    assert telemetry["score_before"] == 100
    assert telemetry["score_after"] == 0


def test_coupled_period_room_lns_expiry_returns_exact_incumbent(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_coupled_pressure_problem(tmp_path))
    original = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 0, 1),
        ITC2007ExamAssignment(2, 1, 0),
        ITC2007ExamAssignment(3, 1, 1),
    )
    before = validate_itc2007_exam_solution(problem, original)

    assignments, validation, telemetry = (
        exam_solver._optimize_exam_period_room_neighborhood(
            problem,
            original,
            deadline=time.perf_counter() - 1.0,
            seed=17,
        )
    )

    assert assignments == original
    assert validation == before
    assert validation.feasible
    assert telemetry["accepted"] is False
    assert telemetry["status"] == "not_run"


def test_solve_path_invokes_coupled_lns_for_initial_assignments(
    tmp_path: Path,
    monkeypatch,
) -> None:
    problem = parse_itc2007_exam(_write_coupled_pressure_problem(tmp_path))
    original = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 0, 1),
        ITC2007ExamAssignment(2, 1, 0),
        ITC2007ExamAssignment(3, 1, 1),
    )
    observed = {}

    def capture(active_problem, assignments, *, deadline, seed, period_radius, workers):
        observed.update(
            {
                "problem": active_problem,
                "deadline": deadline,
                "seed": seed,
                "period_radius": period_radius,
                "workers": workers,
            }
        )
        rows = tuple(assignments)
        validation = validate_itc2007_exam_solution(active_problem, rows)
        return rows, validation, {"accepted": False, "status": "captured"}

    monkeypatch.setattr(
        exam_solver,
        "_optimize_exam_period_room_neighborhood",
        capture,
    )
    result = exam_solver.solve_itc2007_exam(
        problem,
        time_limit_seconds=2.0,
        seed=23,
        workers=1,
        initial_assignments=original,
        coupled_lns_period_radius=5,
    )

    assert result.assignments == original
    assert result.validation.feasible
    assert result.status == "feasible_initial_assignments"
    assert result.telemetry["strategy"] == ("incumbent_hinted_coupled_period_room_lns")
    assert result.telemetry["coupled_lns"]["status"] == "captured"
    assert observed["problem"] is problem
    assert observed["deadline"] > time.perf_counter()
    assert observed["seed"] == 23
    assert observed["period_radius"] == 5
    assert observed["workers"] == 1


def test_cold_projected_solve_uses_reserved_coupled_lns_tail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    problem = parse_itc2007_exam(_write_coupled_pressure_problem(tmp_path))
    original = (
        ITC2007ExamAssignment(0, 0, 0),
        ITC2007ExamAssignment(1, 0, 1),
        ITC2007ExamAssignment(2, 1, 0),
        ITC2007ExamAssignment(3, 1, 1),
    )
    validation = validate_itc2007_exam_solution(problem, original)
    observed = {}

    monkeypatch.setattr(
        exam_solver,
        "_projected_exam_prebuild_admission",
        lambda *_args, **_kwargs: {
            "admitted": False,
            "work_units": 1,
            "build_window_seconds": 0.0,
            "estimated_build_seconds": 1.0,
            "admission_units_per_second": 1.0,
            "fixed_seconds": 0.0,
        },
    )
    monkeypatch.setattr(
        exam_solver,
        "_construct_itc2007_exam_incumbent",
        lambda *_args, **_kwargs: exam_solver._ExamConstructiveResult(
            assignments=original,
            validation=validation,
            telemetry={"objective": validation.objective.total},
        ),
    )

    def capture(active_problem, assignments, *, deadline, seed, period_radius, workers):
        observed.update(
            {
                "problem": active_problem,
                "deadline": deadline,
                "seed": seed,
                "period_radius": period_radius,
                "workers": workers,
            }
        )
        rows = tuple(assignments)
        return rows, validation, {"accepted": False, "status": "captured-cold"}

    monkeypatch.setattr(
        exam_solver,
        "_optimize_exam_period_room_neighborhood",
        capture,
    )
    result = exam_solver.solve_itc2007_exam(
        problem,
        time_limit_seconds=30.0,
        seed=29,
        workers=1,
        max_exact_exams=0,
    )

    assert result.assignments == original
    assert result.validation.feasible
    assert result.status == "feasible_constructive"
    assert result.telemetry["constructive"]["coupled_lns"]["status"] == (
        "captured-cold"
    )
    assert result.telemetry["deadline_policy"]["coupled_lns_reserve_seconds"] > 0
    assert observed["problem"] is problem
    assert observed["deadline"] > time.perf_counter()
    assert observed["seed"] == 29
    assert observed["period_radius"] == 3
    assert observed["workers"] == 1


def test_streamed_pressure_blocks_strictly_improve_small_exact_boundary(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_streamed_pressure_problem(tmp_path))
    original = tuple(
        ITC2007ExamAssignment(exam, exam // 2, exam % 2) for exam in range(12)
    )
    before = validate_itc2007_exam_solution(problem, original)

    assignments, after, telemetry = exam_solver._polish_exam_pressure_blocks(
        problem,
        original,
        deadline=time.perf_counter() + 1.0,
        seed=17,
        workers=1,
    )

    assert before.feasible
    assert before.objective.total == 300
    assert after.feasible
    assert after.hard.total == 0
    assert after.objective.total < before.objective.total
    assert len(assignments) == len(original)
    assert telemetry["accepted"] is True
    assert telemetry["accepted_blocks"] >= 1


def test_streamed_pressure_blocks_expiry_returns_exact_incumbent(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_streamed_pressure_problem(tmp_path))
    original = tuple(
        ITC2007ExamAssignment(exam, exam // 2, exam % 2) for exam in range(12)
    )
    before = validate_itc2007_exam_solution(problem, original)

    assignments, validation, telemetry = exam_solver._polish_exam_pressure_blocks(
        problem,
        original,
        deadline=time.perf_counter() - 1.0,
        seed=17,
        workers=1,
    )

    assert assignments == original
    assert validation == before
    assert telemetry["accepted"] is False
    assert telemetry["attempted_blocks"] == 0


def test_constructive_path_invokes_streamed_pressure_tail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    problem = parse_itc2007_exam(_write_streamed_pressure_problem(tmp_path))
    observed = {}

    def room_passthrough(active_problem, assignments, **_kwargs):
        rows = tuple(assignments)
        return rows, validate_itc2007_exam_solution(active_problem, rows), {}

    def period_passthrough(active_problem, assignments, **_kwargs):
        rows = tuple(assignments)
        return rows, validate_itc2007_exam_solution(active_problem, rows), {}

    def capture(active_problem, assignments, *, deadline, seed, workers):
        rows = tuple(assignments)
        validation = validate_itc2007_exam_solution(active_problem, rows)
        observed.update(
            {
                "problem": active_problem,
                "deadline": deadline,
                "seed": seed,
                "workers": workers,
            }
        )
        return rows, validation, {"accepted": False, "status": "captured"}

    monkeypatch.setattr(exam_solver, "_polish_fixed_period_rooms", room_passthrough)
    monkeypatch.setattr(exam_solver, "_polish_exam_periods", period_passthrough)
    monkeypatch.setattr(exam_solver, "_polish_exam_pressure_blocks", capture)
    eligible_periods = {
        exam_id: tuple(range(len(problem.periods)))
        for exam_id in range(len(problem.exams))
    }

    result = exam_solver._construct_itc2007_exam_incumbent(
        problem,
        eligible_periods=eligible_periods,
        deadline=time.perf_counter() + 2.0,
        seed=23,
    )

    assert result is not None
    assert result.validation.feasible
    assert result.telemetry["pressure_block_polish"]["status"] == "captured"
    assert observed["problem"] is problem
    assert observed["deadline"] > time.perf_counter()
    assert observed["seed"] == 23
    assert observed["workers"] == 1
