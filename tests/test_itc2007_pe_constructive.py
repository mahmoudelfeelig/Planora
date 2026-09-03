from __future__ import annotations

import time

from benchmarks.itc2007_pe import (
    TIMESLOTS,
    ITC2007PEAssignment,
    ITC2007PEProblem,
    validate_itc2007_pe_solution,
)
from benchmarks.itc2007_pe_constructive import (
    construct_itc2007_pe_dsat,
    repair_itc2007_pe_assignment,
)


def _problem() -> ITC2007PEProblem:
    return ITC2007PEProblem(
        name="pe-dynamic-constructor",
        events=6,
        rooms=2,
        features=2,
        students=5,
        room_capacities=(3, 3),
        student_events=(
            (True, True, False, False, False, False),
            (False, True, True, False, False, False),
            (False, False, True, True, False, False),
            (False, False, False, True, True, False),
            (False, False, False, False, True, True),
        ),
        room_features=((True, False), (False, True)),
        event_features=(
            (True, False),
            (False, True),
            (True, False),
            (False, True),
            (True, False),
            (False, True),
        ),
        event_availability=tuple(
            tuple(slot < 4 for slot in range(TIMESLOTS)) for _ in range(6)
        ),
        precedence=tuple(tuple(0 for _ in range(6)) for _ in range(6)),
    )


def _precedence_trap_problem() -> ITC2007PEProblem:
    return ITC2007PEProblem(
        name="pe-precedence-trap",
        events=2,
        rooms=1,
        features=0,
        students=2,
        room_capacities=(2,),
        student_events=((True, True), (False, True)),
        room_features=((),),
        event_features=((), ()),
        event_availability=tuple(
            tuple(slot < 2 for slot in range(TIMESLOTS)) for _ in range(2)
        ),
        precedence=((0, 1), (-1, 0)),
    )


def test_dynamic_constructor_returns_complete_independently_valid_schedule() -> None:
    problem = _problem()

    assignments, telemetry = construct_itc2007_pe_dsat(
        problem,
        deadline=time.perf_counter() + 1.0,
        seed=17,
        attempts=3,
    )

    validation = validate_itc2007_pe_solution(problem, assignments)
    assert validation.feasible
    assert validation.score.distance_to_feasibility == 0
    assert telemetry.best_distance == 0
    assert telemetry.matching_calls > 0
    assert all(row.placed for row in assignments)


def test_dynamic_constructor_deadline_path_is_fail_closed() -> None:
    problem = _problem()

    assignments, telemetry = construct_itc2007_pe_dsat(
        problem,
        deadline=time.perf_counter(),
        seed=3,
        attempts=4,
    )

    validation = validate_itc2007_pe_solution(problem, assignments)
    assert validation.feasible
    assert telemetry.deadline_exhausted
    assert len(assignments) == problem.events


def test_dynamic_constructor_propagates_precedence_windows_before_ranking() -> None:
    problem = _precedence_trap_problem()

    assignments, telemetry = construct_itc2007_pe_dsat(
        problem,
        deadline=time.perf_counter() + 1.0,
        seed=0,
        attempts=1,
    )

    validation = validate_itc2007_pe_solution(problem, assignments)
    assert validation.feasible
    assert validation.score.distance_to_feasibility == 0
    assert assignments[0].timeslot == 0
    assert assignments[1].timeslot == 1
    assert telemetry.best_distance == 0


def test_post_projected_repair_accepts_only_lexicographic_improvement() -> None:
    problem = _problem()
    initial = (
        ITC2007PEAssignment(0, 0, 0),
        ITC2007PEAssignment(1, 1, 1),
        ITC2007PEAssignment(2, 2, 0),
        ITC2007PEAssignment(3, 3, 1),
        ITC2007PEAssignment(4, 1, 0),
        ITC2007PEAssignment(5, -1, -1),
    )
    initial_validation = validate_itc2007_pe_solution(problem, initial)
    assert initial_validation.feasible
    assert initial_validation.score.distance_to_feasibility > 0

    repaired, telemetry = repair_itc2007_pe_assignment(
        problem,
        initial,
        deadline=time.perf_counter() + 1.0,
    )

    validation = validate_itc2007_pe_solution(problem, repaired)
    assert validation.feasible
    assert telemetry["accepted"]
    assert telemetry["final_distance"] < telemetry["initial_distance"]
    assert validation.score.lexicographic < initial_validation.score.lexicographic
