from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import benchmarks.itc2007_exam as exam_solver
from benchmarks.itc2007_exam import parse_itc2007_exam, solve_itc2007_exam


def _write_projected_problem(tmp_path: Path) -> Path:
    path = tmp_path / "projected.exam"
    path.write_text(
        dedent(
            """\
            [Exams:6]
            60, 0
            60, 0
            90, 1
            90, 1
            120, 2
            120, 2
            [Periods:3]
            01:06:2026, 09:00:00, 120, 0
            01:06:2026, 12:00:00, 120, 0
            02:06:2026, 09:00:00, 120, 0
            [Rooms:2]
            2, 0
            2, 3
            [PeriodHardConstraints]
            [RoomHardConstraints]
            0, ROOM_EXCLUSIVE
            [InstitutionalWeightings]
            TWOINAROW, 10
            TWOINADAY, 4
            PERIODSPREAD, 1
            NONMIXEDDURATIONS, 6
            FRONTLOAD, 1, 1, 7
            """
        ),
        encoding="utf-8",
    )
    return path


def test_projected_period_coloring_lifts_rooms_and_returns_independent_score(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_projected_problem(tmp_path))

    result = solve_itc2007_exam(
        problem,
        time_limit_seconds=2.0,
        seed=17,
        max_exact_exams=2,
    )

    assert result.status in {"feasible_projected", "feasible_constructive"}
    assert result.validation.feasible
    assert len(result.assignments) == len(problem.exams)
    assert result.objective_value == result.validation.objective.total
    if result.status == "feasible_projected":
        projected_components = result.validation.objective
        assert result.telemetry["projected_objective"] == (
            projected_components.two_in_a_row
            + projected_components.two_in_a_day
            + projected_components.period_spread
            + projected_components.frontload
            + projected_components.period_penalty
        )
        assert result.telemetry["hall_cuts"] > 0
    assert result.telemetry["strategy"] in {
        "projected_period_coloring_with_room_lift",
        "constructive_coloring_with_bounded_ejection",
    }
    assert result.telemetry["scale"]["solver_lane"] == "projected_period_room"
    exclusive = result.assignments[0]
    assert sum(
        assignment.period == exclusive.period and assignment.room == exclusive.room
        for assignment in result.assignments
    ) == 1


def test_projected_resource_exhaustion_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    problem = parse_itc2007_exam(_write_projected_problem(tmp_path))

    def exhaust(*args, **kwargs):
        del args, kwargs
        raise MemoryError("synthetic allocation failure")

    monkeypatch.setattr(exam_solver, "_solve_projected_itc2007_exam", exhaust)
    result = solve_itc2007_exam(
        problem,
        time_limit_seconds=1.0,
        max_exact_exams=2,
    )

    assert result.status == "resource_exhausted_during_projected_solve"
    assert result.assignments == ()
    assert not result.validation.feasible
    assert result.telemetry["resource_error"] == "MemoryError"
    assert result.telemetry["fail_closed"] is True


def test_projected_prebuild_admission_has_an_exact_budget_boundary() -> None:
    admitted = exam_solver._projected_exam_prebuild_admission(
        600,
        build_window_seconds=1.02,
        units_per_second=600.0,
        fixed_seconds=0.02,
    )
    rejected = exam_solver._projected_exam_prebuild_admission(
        600,
        build_window_seconds=1.019,
        units_per_second=600.0,
        fixed_seconds=0.02,
    )

    assert admitted["estimated_build_seconds"] == 1.02
    assert admitted["admitted"] is True
    assert rejected["admitted"] is False


def test_projected_build_estimate_is_derived_from_model_representation(
    tmp_path: Path,
) -> None:
    problem = parse_itc2007_exam(_write_projected_problem(tmp_path))
    eligible_periods = {
        exam_id: tuple(
            period_id
            for period_id, period in enumerate(problem.periods)
            if exam.duration <= period.duration
        )
        for exam_id, exam in enumerate(problem.exams)
    }

    estimate = exam_solver._estimate_projected_exam_build(
        problem,
        eligible_periods,
    )

    assert estimate["period_literals"] == sum(map(len, eligible_periods.values()))
    assert estimate["shared_pairs"] == len(problem.shared_student_counts)
    assert estimate["work_units"] == sum(
        estimate[field]
        for field in (
            "period_literals",
            "temporal_relation_units",
            "hall_capacity_term_references",
            "hall_cardinality_term_references",
            "exclusive_term_references",
        )
    )


def test_projected_prebuild_gate_extends_constructive_lane_without_building_cp(
    tmp_path: Path,
    monkeypatch,
) -> None:
    problem = parse_itc2007_exam(_write_projected_problem(tmp_path))

    def reject_prebuild(*args, **kwargs):
        del args, kwargs
        return {
            "admitted": False,
            "work_units": 1_000_000,
            "build_window_seconds": 0.1,
            "estimated_build_seconds": 2.0,
            "admission_units_per_second": 600_000.0,
            "fixed_seconds": 0.02,
        }

    class CpModelMustNotBeBuilt:
        def __init__(self):
            raise AssertionError("projected CP model should have been skipped")

    monkeypatch.setattr(
        exam_solver,
        "_projected_exam_prebuild_admission",
        reject_prebuild,
    )
    monkeypatch.setattr(exam_solver.cp_model, "CpModel", CpModelMustNotBeBuilt)

    result = solve_itc2007_exam(
        problem,
        time_limit_seconds=2.0,
        seed=17,
        workers=1,
        max_exact_exams=2,
    )

    assert result.status == "feasible_constructive"
    assert result.validation.feasible
    assert len(result.assignments) == len(problem.exams)
    assert result.telemetry["fallback_reason"] == (
        "projected_prebuild_representation_gate"
    )
    policy = result.telemetry["deadline_policy"]
    assert policy["constructive_lane_extended"] is True
    assert policy["constructive_allocated_seconds"] > policy[
        "constructive_budget_seconds"
    ]
    assert policy["projected_skipped_reason"] == "representation_prebuild_gate"
