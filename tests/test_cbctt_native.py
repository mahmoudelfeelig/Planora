from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks.cbctt import (
    CBCTTExtendedCourse,
    CBCTTExtendedProblem,
    CBCTTExtendedRoom,
)
from benchmarks.cbctt_native import (
    CBCTTAssignment,
    CBCTT_FORMULATIONS,
    assess_cbctt_native_eligibility,
    parse_cbctt_solution,
    render_cbctt_solution,
    score_cbctt_assignments,
    solve_cbctt_native,
    validate_cbctt_assignments,
    write_cbctt_solution,
)


def _scoring_problem() -> CBCTTExtendedProblem:
    return CBCTTExtendedProblem(
        name="native-score",
        days=2,
        periods_per_day=4,
        minimum_daily_lectures=2,
        maximum_daily_lectures=2,
        courses=(
            CBCTTExtendedCourse("A", "TA", 3, 2, 30, True),
            CBCTTExtendedCourse("B", "TB", 2, 2, 15, False),
            CBCTTExtendedCourse("C", "TC", 1, 1, 10, False),
        ),
        rooms=(
            CBCTTExtendedRoom("R1", 20, 0),
            CBCTTExtendedRoom("R2", 40, 1),
        ),
        curricula={"Q": ("A", "B", "C")},
        unavailability=(),
        room_constraints=(("A", "R2"), ("B", "R1")),
    )


def _scoring_assignments() -> tuple[CBCTTAssignment, ...]:
    return (
        CBCTTAssignment("A", "R1", 0, 0),
        CBCTTAssignment("A", "R1", 0, 1),
        CBCTTAssignment("A", "R2", 0, 3),
        CBCTTAssignment("B", "R1", 1, 0),
        CBCTTAssignment("B", "R1", 1, 2),
        CBCTTAssignment("C", "R2", 1, 3),
    )


def _solver_problem() -> CBCTTExtendedProblem:
    return CBCTTExtendedProblem(
        name="native-solve",
        days=2,
        periods_per_day=3,
        minimum_daily_lectures=1,
        maximum_daily_lectures=2,
        courses=(
            CBCTTExtendedCourse("A", "TA", 2, 1, 5, True),
            CBCTTExtendedCourse("B", "TB", 1, 1, 5, False),
        ),
        rooms=(
            CBCTTExtendedRoom("R1", 10, 0),
            CBCTTExtendedRoom("R2", 10, 1),
        ),
        curricula={"Q": ("A", "B")},
        unavailability=(),
        room_constraints=(("A", "R2"),),
    )


def _factorization_problem() -> CBCTTExtendedProblem:
    return CBCTTExtendedProblem(
        name="native-room-factorization",
        days=2,
        periods_per_day=3,
        minimum_daily_lectures=1,
        maximum_daily_lectures=2,
        courses=(
            CBCTTExtendedCourse("A", "TA", 2, 2, 16, False),
            CBCTTExtendedCourse("B", "TB", 2, 1, 8, False),
            CBCTTExtendedCourse("C", "TC", 1, 1, 8, False),
        ),
        rooms=(
            CBCTTExtendedRoom("R1", 20, 0),
            CBCTTExtendedRoom("R2", 20, 0),
            CBCTTExtendedRoom("R3", 20, 1),
            CBCTTExtendedRoom("R4", 20, 1),
        ),
        curricula={"Q": ("A", "B"), "Z": ("B", "C")},
        unavailability=(),
        room_constraints=(
            ("A", "R1"),
            ("A", "R2"),
            ("B", "R3"),
            ("B", "R4"),
        ),
    )


def test_formulation_table_matches_published_ud_weights() -> None:
    assert {
        name: spec.weights() for name, spec in CBCTT_FORMULATIONS.items()
    } == {
        "UD1": {
            "room_capacity": 1,
            "minimum_working_days": 5,
            "isolated_lectures": 1,
            "windows": None,
            "room_stability": None,
            "student_min_max_load": None,
            "travel_distance": None,
            "room_suitability": None,
            "double_lectures": None,
        },
        "UD2": {
            "room_capacity": 1,
            "minimum_working_days": 5,
            "isolated_lectures": 2,
            "windows": None,
            "room_stability": 1,
            "student_min_max_load": None,
            "travel_distance": None,
            "room_suitability": None,
            "double_lectures": None,
        },
        "UD3": {
            "room_capacity": 1,
            "minimum_working_days": None,
            "isolated_lectures": None,
            "windows": 4,
            "room_stability": None,
            "student_min_max_load": 2,
            "travel_distance": None,
            "room_suitability": 3,
            "double_lectures": None,
        },
        "UD4": {
            "room_capacity": 1,
            "minimum_working_days": 1,
            "isolated_lectures": None,
            "windows": 1,
            "room_stability": None,
            "student_min_max_load": 1,
            "travel_distance": None,
            "room_suitability": None,
            "double_lectures": 1,
        },
        "UD5": {
            "room_capacity": 1,
            "minimum_working_days": 5,
            "isolated_lectures": 1,
            "windows": 2,
            "room_stability": None,
            "student_min_max_load": 2,
            "travel_distance": 2,
            "room_suitability": None,
            "double_lectures": None,
        },
    }
    assert CBCTT_FORMULATIONS["UD4"].room_suitability_hard


@pytest.mark.parametrize(
    ("formulation", "expected_total"),
    [("UD1", 32), ("UD2", 35), ("UD3", 41), ("UD4", 27), ("UD5", 42)],
)
def test_native_scorer_covers_all_extension_components_and_formulations(
    formulation: str,
    expected_total: int,
) -> None:
    score = score_cbctt_assignments(
        _scoring_problem(),
        _scoring_assignments(),
        formulation=formulation,
    )

    assert score.raw_components() == {
        "room_capacity": 20,
        "minimum_working_days": 2,
        "isolated_lectures": 2,
        "windows": 2,
        "room_stability": 1,
        "student_min_max_load": 2,
        "travel_distance": 1,
        "room_suitability": 3,
        "double_lectures": 1,
    }
    assert score.total == expected_total
    assert sum(score.weighted_components().values()) == expected_total


def test_native_validation_keeps_hard_and_soft_semantics_separate() -> None:
    problem = _scoring_problem()
    assignments = _scoring_assignments()

    ud2 = validate_cbctt_assignments(problem, assignments, formulation="UD2")
    ud4 = validate_cbctt_assignments(problem, assignments, formulation="UD4")

    assert ud2.feasible
    assert ud2.hard_violations == 0
    assert ud4.hard_room_suitability_violations == 3
    assert ud4.hard_violations == 3
    assert not ud4.feasible
    assert ud4.score.room_suitability == 3
    assert "room_suitability" not in ud4.score.weighted_components()


def test_student_minimum_load_ignores_days_without_curriculum_lectures() -> None:
    problem = CBCTTExtendedProblem(
        name="zero-load-day",
        days=3,
        periods_per_day=3,
        minimum_daily_lectures=2,
        maximum_daily_lectures=3,
        courses=(CBCTTExtendedCourse("A", "TA", 1, 1, 5, False),),
        rooms=(CBCTTExtendedRoom("R", 10, 0),),
        curricula={"Q": ("A",)},
        unavailability=(),
        room_constraints=(),
    )

    score = score_cbctt_assignments(
        problem,
        (CBCTTAssignment("A", "R", 0, 0),),
        formulation="UD3",
    )

    assert score.student_min_max_load == 1


def test_native_validation_counts_conflict_occupancy_availability_and_duplicates() -> None:
    problem = replace(
        _scoring_problem(), unavailability=(("A", 0, 0),)
    )
    assignments = list(_scoring_assignments())
    assignments[3] = CBCTTAssignment("B", "R1", 0, 0)

    validation = validate_cbctt_assignments(
        problem,
        (*assignments, CBCTTAssignment("A", "R1", 0, 0)),
        formulation="UD2",
    )

    assert validation.lecture_count_violations == 1
    assert validation.duplicate_course_period_violations == 1
    assert validation.conflict_violations == 1
    assert validation.room_occupancy_violations == 2
    assert validation.availability_violations == 2
    assert not validation.feasible


def test_solution_io_round_trip_and_fail_closed_structure(tmp_path: Path) -> None:
    output = tmp_path / "native.out"
    assignments = _scoring_assignments()

    write_cbctt_solution(output, assignments)

    assert output.read_text(encoding="utf-8") == render_cbctt_solution(assignments)
    assert parse_cbctt_solution(
        output, problem=_scoring_problem(), require_complete=True
    ) == assignments

    output.write_text("missing R1 0 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown course"):
        parse_cbctt_solution(output, problem=_scoring_problem())


def test_eligibility_reports_scale_and_rejects_unsupported_or_oversized_models() -> None:
    problem = _solver_problem()

    accepted = assess_cbctt_native_eligibility(problem, formulation="UD5")
    oversized = assess_cbctt_native_eligibility(
        problem, formulation="UD5", max_assignment_variables=1
    )
    unsupported = assess_cbctt_native_eligibility(
        problem, formulation="future"
    )

    assert accepted.eligible
    assert accepted.estimated_assignment_variables > 1
    assert "soft:travel_distance" in accepted.supported_semantics
    assert not oversized.eligible
    assert any("assignment_variable_limit_exceeded" in reason for reason in oversized.reasons)
    assert not unsupported.eligible
    assert unsupported.reasons == ("unsupported_formulation:FUTURE",)


def test_exact_room_factorization_widens_assignment_scale_admission() -> None:
    problem = replace(
        _solver_problem(),
        rooms=tuple(
            CBCTTExtendedRoom(f"R{index:03d}", 10, 0)
            for index in range(100)
        ),
        room_constraints=(),
    )

    factorized = assess_cbctt_native_eligibility(
        problem,
        formulation="UD1",
        max_assignment_variables=20,
    )
    physical = assess_cbctt_native_eligibility(
        problem,
        formulation="UD1",
        max_assignment_variables=20,
        factorize_equivalent_rooms=False,
    )

    assert factorized.eligible
    assert factorized.estimated_assignment_variables == 12
    assert not physical.eligible
    assert physical.estimated_assignment_variables == 1_200


@pytest.mark.parametrize(
    ("formulation", "expected_groups"),
    (("UD1", 1), ("UD3", 2), ("UD5", 2)),
)
def test_factorized_and_physical_room_models_have_same_exact_optimum(
    formulation: str,
    expected_groups: int,
) -> None:
    problem = _factorization_problem()

    factorized = solve_cbctt_native(
        problem,
        formulation=formulation,
        time_limit_seconds=3.0,
        seed=11,
        workers=1,
    )
    physical = solve_cbctt_native(
        problem,
        formulation=formulation,
        time_limit_seconds=3.0,
        seed=11,
        workers=1,
        factorize_equivalent_rooms=False,
    )

    assert factorized.status == physical.status == "optimal"
    assert factorized.validation is not None
    assert physical.validation is not None
    assert factorized.validation.feasible
    assert physical.validation.feasible
    assert factorized.objective_value == factorized.validation.score.total
    assert physical.objective_value == physical.validation.score.total
    assert factorized.objective_value == physical.objective_value
    assert factorized.telemetry["room_factorization"] is True
    assert factorized.telemetry["room_groups"] == expected_groups
    assert physical.telemetry["room_factorization"] is False
    assert physical.telemetry["room_groups"] == len(problem.rooms)


def test_factorized_group_capacity_lifts_concurrent_courses_to_distinct_rooms() -> None:
    problem = CBCTTExtendedProblem(
        name="native-room-group-capacity",
        days=1,
        periods_per_day=1,
        minimum_daily_lectures=0,
        maximum_daily_lectures=1,
        courses=(
            CBCTTExtendedCourse("A", "TA", 1, 1, 5, False),
            CBCTTExtendedCourse("B", "TB", 1, 1, 5, False),
        ),
        rooms=(
            CBCTTExtendedRoom("R1", 10, 0),
            CBCTTExtendedRoom("R2", 10, 0),
        ),
        curricula={},
        unavailability=(),
        room_constraints=(),
    )

    result = solve_cbctt_native(
        problem,
        formulation="UD1",
        time_limit_seconds=1.0,
        workers=1,
    )

    assert result.status == "optimal"
    assert result.validation is not None and result.validation.feasible
    assert {row.room_id for row in result.assignments} == {"R1", "R2"}
    assert result.telemetry["room_groups"] == 1


@pytest.mark.parametrize("formulation", ("UD2", "UD4"))
def test_identity_sensitive_formulations_keep_physical_room_variables(
    formulation: str,
) -> None:
    problem = _factorization_problem()

    result = solve_cbctt_native(
        problem,
        formulation=formulation,
        time_limit_seconds=3.0,
        workers=1,
    )

    assert result.status == "optimal"
    assert result.validation is not None and result.validation.feasible
    assert result.telemetry["room_factorization"] is False
    assert result.telemetry["room_groups"] == len(problem.rooms)


def test_ud4_solver_enforces_hard_suitability_and_matches_independent_score() -> None:
    result = solve_cbctt_native(
        _solver_problem(),
        formulation="UD4",
        time_limit_seconds=3.0,
        seed=7,
        workers=1,
    )

    assert result.status in {"feasible", "optimal"}
    assert result.validation is not None
    assert result.validation.feasible
    assert result.objective_value == result.validation.score.total == 0
    assert result.telemetry["objective_parity"] is True
    assert all(
        not (row.course_id == "A" and row.room_id == "R2")
        for row in result.assignments
    )
    assert result.deadline_overrun_seconds < 0.1


@pytest.mark.parametrize("formulation", tuple(CBCTT_FORMULATIONS))
def test_solver_objective_matches_independent_native_scorer(
    formulation: str,
) -> None:
    result = solve_cbctt_native(
        _solver_problem(),
        formulation=formulation,
        time_limit_seconds=2.0,
        seed=3,
        workers=1,
    )

    assert result.status in {"feasible", "optimal"}
    assert result.validation is not None
    assert result.validation.feasible
    assert result.objective_value == result.validation.score.total
    assert result.telemetry["objective_parity"] is True


def test_solver_refuses_ineligible_scale_without_returning_partial_assignment() -> None:
    result = solve_cbctt_native(
        _solver_problem(),
        formulation="UD5",
        time_limit_seconds=1.0,
        max_assignment_variables=1,
    )

    assert result.status == "ineligible"
    assert result.assignments == ()
    assert result.validation is None
    assert result.telemetry["fail_closed"] is True


def test_solver_deadline_exhaustion_is_structured_and_fail_closed() -> None:
    result = solve_cbctt_native(
        _solver_problem(),
        formulation="UD2",
        time_limit_seconds=0.0,
    )

    assert result.status == "deadline_before_build"
    assert result.assignments == ()
    assert result.validation is None
    assert result.to_dict()["eligibility"]["eligible"] is True
