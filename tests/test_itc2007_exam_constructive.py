from __future__ import annotations

from pathlib import Path
from textwrap import dedent
import time

import benchmarks.itc2007_exam as exam_solver
import pytest
from benchmarks.itc2007_exam import parse_itc2007_exam, solve_itc2007_exam


def _write_constructive_problem(tmp_path: Path) -> Path:
    path = tmp_path / "constructive.exam"
    path.write_text(
        dedent(
            """\
            [Exams:8]
            90, 0
            90, 0
            90, 1
            90, 1
            120, 2
            120, 2
            60, 3
            60, 3
            [Periods:4]
            01:06:2026, 09:00:00, 120, 0
            01:06:2026, 12:00:00, 120, 0
            02:06:2026, 09:00:00, 120, 0
            02:06:2026, 12:00:00, 120, 0
            [Rooms:2]
            2, 0
            2, 4
            [PeriodHardConstraints]
            4, AFTER, 0
            6, EXAM_COINCIDENCE, 4
            [RoomHardConstraints]
            0, ROOM_EXCLUSIVE
            [InstitutionalWeightings]
            TWOINAROW, 10
            TWOINADAY, 4
            PERIODSPREAD, 1
            NONMIXEDDURATIONS, 6
            FRONTLOAD, 2, 1, 7
            """
        ),
        encoding="utf-8",
    )
    return path


def _eligible_periods(problem):
    return {
        exam_id: tuple(
            period_id
            for period_id, period in enumerate(problem.periods)
            if exam.duration <= period.duration
        )
        for exam_id, exam in enumerate(problem.exams)
    }


def test_constructive_coloring_is_complete_hard_feasible_and_deterministic(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_constructive_problem(tmp_path))

    first = exam_solver._construct_itc2007_exam_incumbent(
        problem,
        eligible_periods=_eligible_periods(problem),
        deadline=time.perf_counter() + 2.0,
        seed=17,
    )
    second = exam_solver._construct_itc2007_exam_incumbent(
        problem,
        eligible_periods=_eligible_periods(problem),
        deadline=time.perf_counter() + 2.0,
        seed=17,
    )

    assert first is not None
    assert second is not None
    assert first.assignments == second.assignments
    assert first.validation.feasible
    assert len(first.assignments) == len(problem.exams)
    assert first.telemetry["coincidence_contractions"] == 1
    assert first.validation.objective.total == first.telemetry["objective"]
    exclusive = first.assignments[0]
    assert sum(
        assignment.period == exclusive.period and assignment.room == exclusive.room
        for assignment in first.assignments
    ) == 1
    assert first.assignments[4].period == first.assignments[6].period
    assert first.assignments[4].period > first.assignments[0].period
    budget = first.telemetry["polish_budget"]
    assert 0 < budget["room_closure_reserve_seconds"] <= 0.08
    assert 0 < budget["period_lns_reserve_seconds"] <= 0.28
    assert budget["room_polish_budget_seconds"] == pytest.approx(
        budget["available_seconds"] - budget["period_lns_reserve_seconds"]
    )
    assert budget["room_bnb_budget_seconds"] == pytest.approx(
        budget["room_polish_budget_seconds"]
        - budget["room_closure_reserve_seconds"]
    )
    assert first.telemetry["room_polish"]["closure_budget_seconds"] == (
        pytest.approx(budget["room_closure_reserve_seconds"])
    )


def test_constructive_period_polish_uses_deadline_instead_of_six_round_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = parse_itc2007_exam(_write_constructive_problem(tmp_path))
    observed: dict[str, int] = {}

    def capture_period_polish(
        active_problem,
        assignments,
        *,
        deadline: float,
        max_rounds: int = 6,
        **_kwargs,
    ):
        del deadline
        observed["max_rounds"] = int(max_rounds)
        rows = tuple(assignments)
        validation = exam_solver.validate_itc2007_exam_solution(
            active_problem,
            rows,
        )
        return rows, validation, {"accepted": False}

    monkeypatch.setattr(
        exam_solver,
        "_polish_exam_periods",
        capture_period_polish,
    )
    result = exam_solver._construct_itc2007_exam_incumbent(
        problem,
        eligible_periods=_eligible_periods(problem),
        deadline=time.perf_counter() + 2.0,
        seed=17,
    )

    assert result is not None
    assert result.validation.feasible
    assert observed["max_rounds"] == 20


def test_projected_unknown_returns_valid_constructive_incumbent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    problem = parse_itc2007_exam(_write_constructive_problem(tmp_path))
    real_solver = exam_solver.cp_model.CpSolver

    class UnknownProjectedSolver(real_solver):
        def solve(self, model, *args, **kwargs):
            del model, args, kwargs
            return exam_solver.cp_model.UNKNOWN

    monkeypatch.setattr(exam_solver.cp_model, "CpSolver", UnknownProjectedSolver)
    result = solve_itc2007_exam(
        problem,
        time_limit_seconds=2.0,
        seed=17,
        max_exact_exams=2,
    )

    assert result.status == "feasible_constructive"
    assert result.validation.feasible
    assert len(result.assignments) == len(problem.exams)
    assert result.objective_value == result.validation.objective.total
    assert result.telemetry["fallback_reason"] == "projected_unknown"
    assert result.telemetry["fail_closed"] is False


def test_expired_constructive_deadline_returns_no_partial_schedule(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_constructive_problem(tmp_path))

    result = exam_solver._construct_itc2007_exam_incumbent(
        problem,
        eligible_periods=_eligible_periods(problem),
        deadline=time.perf_counter() - 1.0,
        seed=17,
    )

    assert result is None


def test_simulated_late_projected_return_keeps_validated_incumbent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    problem = parse_itc2007_exam(_write_constructive_problem(tmp_path))
    real_solver = exam_solver.cp_model.CpSolver

    class UnknownProjectedSolver(real_solver):
        def solve(self, model, *args, **kwargs):
            del model, args, kwargs
            return exam_solver.cp_model.UNKNOWN

    monkeypatch.setattr(exam_solver.cp_model, "CpSolver", UnknownProjectedSolver)
    monkeypatch.setattr(
        exam_solver,
        "_projected_acceptance_is_timely",
        lambda *args, **kwargs: False,
    )
    result = solve_itc2007_exam(
        problem,
        time_limit_seconds=2.0,
        seed=17,
        max_exact_exams=2,
    )

    assert result.status == "feasible_constructive"
    assert result.validation.feasible
    assert len(result.assignments) == len(problem.exams)
    assert result.telemetry["fallback_reason"] == "late_projected_solver_return"
    assert result.telemetry["deadline_policy"]["projected_skipped_reason"] == (
        "late_solver_return"
    )


def test_projected_acceptance_reserve_rejects_boundary_and_late_results() -> None:
    assert exam_solver._projected_acceptance_is_timely(
        8.49,
        deadline=10.0,
        final_acceptance_reserve_seconds=1.5,
    )
    assert not exam_solver._projected_acceptance_is_timely(
        8.5,
        deadline=10.0,
        final_acceptance_reserve_seconds=1.5,
    )
    assert not exam_solver._projected_acceptance_is_timely(
        10.1,
        deadline=10.0,
        final_acceptance_reserve_seconds=0.0,
    )
