from __future__ import annotations

import time

from benchmarks.itc2007_pe import (
    TIMESLOTS,
    ITC2007PEAssignment,
    ITC2007PEProblem,
    _hall_room_sets,
    _projected_cp_itc2007_pe,
    _room_matching,
    validate_itc2007_pe_solution,
)


def _room_problem() -> ITC2007PEProblem:
    return ITC2007PEProblem(
        name="projected-room-toy",
        events=3,
        rooms=2,
        features=2,
        students=3,
        room_capacities=(10, 10),
        student_events=(
            (True, False, False),
            (False, True, False),
            (False, False, True),
        ),
        room_features=((True, False), (False, True)),
        event_features=((True, False), (True, False), (False, True)),
        event_availability=tuple(
            tuple(slot < 2 for slot in range(TIMESLOTS)) for _ in range(3)
        ),
        precedence=((0, 0, 0), (0, 0, 0), (0, 0, 0)),
    )


def _soft_problem() -> ITC2007PEProblem:
    return ITC2007PEProblem(
        name="projected-soft-toy",
        events=2,
        rooms=1,
        features=0,
        students=1,
        room_capacities=(2,),
        student_events=((True, True),),
        room_features=((),),
        event_features=((), ()),
        event_availability=tuple(
            tuple(slot in {0, 1, 9} for slot in range(TIMESLOTS)) for _ in range(2)
        ),
        precedence=((0, 0), (0, 0)),
    )


def test_hall_room_set_closure_is_exact_and_bounded() -> None:
    assert _hall_room_sets((0b001, 0b010, 0b101)) == (
        0b001,
        0b010,
        0b011,
        0b101,
        0b111,
    )
    assert _hall_room_sets((0b001, 0b010), closure_limit=2) is None


def test_room_matching_returns_assignment_or_valid_hall_witness() -> None:
    problem = _room_problem()

    matching, witness = _room_matching(problem, (0, 2))
    assert witness is None
    assert matching is not None
    assert set(matching) == {0, 2}
    assert len(set(matching.values())) == 2

    matching, witness = _room_matching(problem, (0, 1, 2))
    assert matching is None
    assert witness == 0b01


def test_projected_cp_improves_distance_and_lifts_to_valid_rooms() -> None:
    problem = _room_problem()
    initial = tuple(
        ITC2007PEAssignment(event=event, timeslot=-1, room=-1)
        for event in range(problem.events)
    )

    assignments, telemetry = _projected_cp_itc2007_pe(
        problem,
        initial,
        deadline=time.perf_counter() + 2.0,
        seed=17,
        workers=1,
    )

    validation = validate_itc2007_pe_solution(problem, assignments)
    assert validation.feasible
    assert validation.score.distance_to_feasibility == 0
    assert telemetry["returned_source"] == "projected_cp"
    assert telemetry["hall_mode"] == "static_exact"
    assert telemetry["invalid_lifts"] == 0


def test_projected_cp_replaces_invalid_initial_schedule_fail_closed() -> None:
    problem = _room_problem()
    invalid = (
        ITC2007PEAssignment(event=0, timeslot=0, room=0),
        ITC2007PEAssignment(event=1, timeslot=0, room=0),
        ITC2007PEAssignment(event=2, timeslot=-1, room=-1),
    )

    assignments, telemetry = _projected_cp_itc2007_pe(
        problem,
        invalid,
        deadline=time.perf_counter(),
        seed=3,
        workers=1,
    )

    validation = validate_itc2007_pe_solution(problem, assignments)
    assert validation.feasible
    assert all(not row.placed for row in assignments)
    assert telemetry["status"] == "deadline_before_projection"
    assert telemetry["returned_source"] == "invalid_initial_replaced"


def test_projected_cp_optimizes_exact_soft_terms_when_distance_is_zero() -> None:
    problem = _soft_problem()
    initial = (
        ITC2007PEAssignment(0, 0, 0),
        ITC2007PEAssignment(1, 9, 0),
    )
    assert validate_itc2007_pe_solution(problem, initial).score.lexicographic == (0, 2)

    assignments, telemetry = _projected_cp_itc2007_pe(
        problem,
        initial,
        deadline=time.perf_counter() + 2.0,
        seed=17,
        workers=1,
    )

    validation = validate_itc2007_pe_solution(problem, assignments)
    assert validation.feasible
    assert validation.score.lexicographic == (0, 0)
    assert telemetry["returned_source"] == "projected_cp"
