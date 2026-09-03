from __future__ import annotations

from pathlib import Path

from benchmarks.itc2007_pe import (
    TIMESLOTS,
    ITC2007PEAssignment,
    ITC2007PEProblem,
    parse_itc2007_pe,
    parse_itc2007_pe_solution,
    parse_itc2007_pe_validator_output,
    solve_itc2007_pe,
    validate_itc2007_pe_solution,
    write_itc2007_pe_solution,
)


def _problem() -> ITC2007PEProblem:
    availability = tuple(
        tuple(not (event == 3 and slot == 7) for slot in range(TIMESLOTS))
        for event in range(4)
    )
    return ITC2007PEProblem(
        name="pe-toy",
        events=4,
        rooms=2,
        features=2,
        students=2,
        room_capacities=(1, 2),
        student_events=(
            (True, True, True, False),
            (False, False, False, True),
        ),
        room_features=((True, False), (True, True)),
        event_features=(
            (True, False),
            (True, False),
            (False, True),
            (True, False),
        ),
        event_availability=availability,
        precedence=(
            (0, 1, 0, 0),
            (-1, 0, 0, 0),
            (0, 0, 0, 0),
            (0, 0, 0, 0),
        ),
    )


def _render_problem(problem: ITC2007PEProblem) -> str:
    values: list[int] = [
        problem.events,
        problem.rooms,
        problem.features,
        problem.students,
        *problem.room_capacities,
    ]
    for rows in (
        problem.student_events,
        problem.room_features,
        problem.event_features,
        problem.event_availability,
    ):
        values.extend(int(value) for row in rows for value in row)
    values.extend(value for row in problem.precedence for value in row)
    return "\n".join(str(value) for value in values) + "\n"


def test_dense_parser_and_solution_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "toy.tim"
    source.write_text(_render_problem(_problem()), encoding="utf-8")

    parsed = parse_itc2007_pe(source)
    assert parsed.name == "toy"
    assert parsed.events == 4
    assert parsed.event_sizes == (1, 1, 1, 1)
    assert parsed.precedence[0][1] == 1

    rows = (
        ITC2007PEAssignment(0, 0, 0),
        ITC2007PEAssignment(1, 1, 1),
        ITC2007PEAssignment(2, 2, 1),
        ITC2007PEAssignment(3, 8, 0),
    )
    solution = tmp_path / "toy.sln"
    write_itc2007_pe_solution(solution, rows, problem=parsed)
    assert parse_itc2007_pe_solution(solution, parsed) == rows


def test_independent_validator_matches_official_soft_definitions() -> None:
    rows = (
        ITC2007PEAssignment(0, 0, 0),
        ITC2007PEAssignment(1, 1, 1),
        ITC2007PEAssignment(2, 2, 1),
        ITC2007PEAssignment(3, 8, 0),
    )

    validation = validate_itc2007_pe_solution(_problem(), rows)

    assert validation.errors == ()
    assert validation.score.distance_to_feasibility == 0
    assert validation.score.single_class_days == 1
    assert validation.score.consecutive_excess == 1
    assert validation.score.last_slot == 1
    assert validation.score.lexicographic == (0, 3)


def test_validator_reports_hard_violations_and_unplaced_distance() -> None:
    invalid = (
        ITC2007PEAssignment(0, 0, 0),
        ITC2007PEAssignment(1, 0, 1),
        ITC2007PEAssignment(2, 0, 0),
        ITC2007PEAssignment(3, 7, 0),
    )
    validation = validate_itc2007_pe_solution(_problem(), invalid)
    assert any("student 0" in error for error in validation.errors)
    assert any("share room" in error for error in validation.errors)
    assert any("lacks features" in error for error in validation.errors)
    assert any("unavailable timeslot" in error for error in validation.errors)
    assert any("precedence" in error for error in validation.errors)

    unplaced = tuple(
        ITC2007PEAssignment(event, -1, -1) for event in range(_problem().events)
    )
    fallback = validate_itc2007_pe_solution(_problem(), unplaced)
    assert fallback.feasible
    assert fallback.score.distance_to_feasibility == 4
    assert fallback.score.soft_violations == 0


def test_native_cp_sat_solver_returns_a_valid_lexicographic_optimum() -> None:
    result = solve_itc2007_pe(
        _problem(),
        time_limit_seconds=3.0,
        seed=17,
        workers=1,
    )

    assert result.status == "optimal"
    assert result.validation.feasible
    # Student 1 attends exactly one event, so one single-class day is unavoidable.
    assert result.validation.score.lexicographic == (0, 1)
    assert result.telemetry["returned_source"] == "cp_sat"
    assert len(result.assignments) == _problem().events


def test_zero_budget_fails_closed_to_legal_all_unplaced_solution() -> None:
    result = solve_itc2007_pe(
        _problem(),
        time_limit_seconds=0.0,
        seed=5,
        workers=1,
    )

    assert result.status == "deadline_before_construction"
    assert result.validation.feasible
    assert result.validation.score.distance_to_feasibility == 4
    assert all(not row.placed for row in result.assignments)
    assert result.telemetry["returned_source"] == "all_unplaced_fallback"


def test_parser_rejects_invalid_precedence_value(tmp_path: Path) -> None:
    text = _render_problem(_problem()).splitlines()
    text[-1] = "2"
    source = tmp_path / "invalid.tim"
    source.write_text("\n".join(text) + "\n", encoding="utf-8")

    try:
        parse_itc2007_pe(source)
    except ValueError as exc:
        assert "precedence values" in str(exc)
    else:
        raise AssertionError("out-of-range precedence must be rejected")


def test_official_validator_output_parser_requires_component_agreement() -> None:
    stdout = """
Number of unsuitable rooms = 0
Number of unsuitable slots = 0
Number of ordering problems = 0
Number of student clashes = 0
Number of room clashes = 0
Number of unplaced events =2
Distance to feasibility = 7
Penalty for students having three or more events in a row = 3
Penalty for students having single events on a day = 4
Penalty for students having end of day events = 5
Total soft constraint penalty = 12
"""
    result = parse_itc2007_pe_validator_output(stdout)
    assert result.feasible
    assert result.lexicographic == (7, 12)
    assert result.to_dict()["hard_violations"] == 0
