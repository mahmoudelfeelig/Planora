from __future__ import annotations

import time

import pytest

from benchmarks import itc2007_pe as pe_solver
from benchmarks import itc2007_pe_constructive as pe_constructive
from benchmarks import itc2007_pe_local_search as pe_local_search
from benchmarks.itc2007_pe import (
    TIMESLOTS,
    ITC2007PEAssignment,
    ITC2007PEProblem,
    validate_itc2007_pe_solution,
)
from benchmarks.itc2007_pe_constructive import PEConstructiveTelemetry
from benchmarks.itc2007_pe_local_search import (
    PEProjectedSearchResult,
    optimize_itc2007_pe_partial,
)


def _barrier_problem() -> ITC2007PEProblem:
    return ITC2007PEProblem(
        name="pe-atomic-barrier",
        events=3,
        rooms=1,
        features=0,
        students=8,
        room_capacities=(4,),
        student_events=(
            (True, False, False),
            (True, False, False),
            (True, False, False),
            (False, True, False),
            (False, True, False),
            (False, True, False),
            (False, True, False),
            (False, False, True),
        ),
        room_features=((),),
        event_features=((), (), ()),
        event_availability=(
            tuple(slot == 0 for slot in range(TIMESLOTS)),
            tuple(slot in {0, 1} for slot in range(TIMESLOTS)),
            tuple(slot == 1 for slot in range(TIMESLOTS)),
        ),
        precedence=((0, 0, 0), (0, 0, 0), (0, 0, 0)),
    )


def _initial() -> tuple[ITC2007PEAssignment, ...]:
    return (
        ITC2007PEAssignment(0, -1, -1),
        ITC2007PEAssignment(1, 0, 0),
        ITC2007PEAssignment(2, 1, 0),
    )


def _direct_repair_problem() -> ITC2007PEProblem:
    return ITC2007PEProblem(
        name="pe-direct-atomic-repair",
        events=2,
        rooms=1,
        features=0,
        students=4,
        room_capacities=(2,),
        student_events=(
            (True, False),
            (True, False),
            (False, True),
            (False, True),
        ),
        room_features=((),),
        event_features=((), ()),
        event_availability=(
            tuple(slot == 0 for slot in range(TIMESLOTS)),
            tuple(slot in {0, 1} for slot in range(TIMESLOTS)),
        ),
        precedence=((0, 0), (0, 0)),
    )


def _secondary_chain_problem() -> ITC2007PEProblem:
    return ITC2007PEProblem(
        name="pe-secondary-ejection-chain",
        events=3,
        rooms=1,
        features=0,
        students=6,
        room_capacities=(2,),
        student_events=(
            (True, False, False),
            (True, False, False),
            (False, True, False),
            (False, True, False),
            (False, False, True),
            (False, False, True),
        ),
        room_features=((),),
        event_features=((), (), ()),
        event_availability=(
            tuple(slot == 0 for slot in range(TIMESLOTS)),
            tuple(slot in {0, 1} for slot in range(TIMESLOTS)),
            tuple(slot in {1, 2} for slot in range(TIMESLOTS)),
        ),
        precedence=((0, 0, 0), (0, 0, 0), (0, 0, 0)),
    )


def _scale_gated_problem() -> ITC2007PEProblem:
    return ITC2007PEProblem(
        name="pe-local-telemetry",
        events=2,
        rooms=1,
        features=0,
        students=223,
        room_capacities=(1,),
        student_events=tuple(
            (student == 0, student == 1) for student in range(223)
        ),
        room_features=((),),
        event_features=((), ()),
        event_availability=tuple(
            tuple(slot in {0, 1} for slot in range(TIMESLOTS))
            for _event in range(2)
        ),
        precedence=((0, 0), (0, 0)),
    )


def _dense_scale_gated_problem() -> ITC2007PEProblem:
    events = 8
    rooms = 100
    students = 223
    return ITC2007PEProblem(
        name="pe-dense-partial-first",
        events=events,
        rooms=rooms,
        features=0,
        students=students,
        room_capacities=tuple(1 for _room in range(rooms)),
        student_events=tuple(
            tuple(student == event for event in range(events))
            for student in range(students)
        ),
        room_features=tuple(() for _room in range(rooms)),
        event_features=tuple(() for _event in range(events)),
        event_availability=tuple(
            tuple(True for _slot in range(TIMESLOTS)) for _event in range(events)
        ),
        precedence=tuple(tuple(0 for _right in range(events)) for _left in range(events)),
    )


def _constructive_telemetry(
    problem: ITC2007PEProblem,
    assignments: tuple[ITC2007PEAssignment, ...],
) -> PEConstructiveTelemetry:
    score = validate_itc2007_pe_solution(problem, assignments).score
    return PEConstructiveTelemetry(
        attempts=1,
        completed_attempts=1,
        direct_insertions=sum(row.placed for row in assignments),
        repair_insertions=0,
        matching_calls=1,
        best_distance=int(score.distance_to_feasibility),
        best_soft=int(score.soft_violations),
        deadline_exhausted=False,
    )


def _local_result(
    problem: ITC2007PEProblem,
    initial: tuple[ITC2007PEAssignment, ...],
    final: tuple[ITC2007PEAssignment, ...],
) -> PEProjectedSearchResult:
    initial_score = validate_itc2007_pe_solution(problem, initial).score
    final_score = validate_itc2007_pe_solution(problem, final).score
    return PEProjectedSearchResult(
        assignments=final,
        status=(
            "improved"
            if final_score.lexicographic < initial_score.lexicographic
            else "no_improvement"
        ),
        initial_score=initial_score,
        final_score=final_score,
        iterations=1,
        accepted_moves=int(final != initial),
        improving_moves=int(final_score.lexicographic < initial_score.lexicographic),
        barrier_moves=0,
        room_matchings=1,
        elapsed_seconds=0.0,
        deadline_exhausted=False,
    )


def test_partial_search_crosses_distance_barrier_atomically() -> None:
    problem = _barrier_problem()
    initial = _initial()
    assert (
        validate_itc2007_pe_solution(problem, initial).score.distance_to_feasibility
        == 3
    )

    result = optimize_itc2007_pe_partial(
        problem,
        initial,
        deadline=time.perf_counter() + 1.0,
        seed=17,
        max_iterations=200,
    )

    validation = validate_itc2007_pe_solution(problem, result.assignments)
    assert validation.feasible
    assert result.improved
    assert validation.score.distance_to_feasibility == 1
    assert result.barrier_moves >= 1
    assert result.best_trajectory


def test_partial_search_rehomes_room_blocker_in_one_atomic_move() -> None:
    problem = _direct_repair_problem()
    initial = (
        ITC2007PEAssignment(0, -1, -1),
        ITC2007PEAssignment(1, 0, 0),
    )

    result = optimize_itc2007_pe_partial(
        problem,
        initial,
        deadline=time.perf_counter() + 1.0,
        seed=17,
        max_iterations=20,
    )

    validation = validate_itc2007_pe_solution(problem, result.assignments)
    assert validation.feasible
    assert validation.score.distance_to_feasibility == 0
    assert result.atomic_repairs_succeeded >= 1
    assert result.atomic_events_reinserted >= 1
    assert any(
        item["move"].get("atomic_repair") is True
        for item in result.best_trajectory
    )


def test_partial_search_follows_secondary_room_ejection_chain() -> None:
    problem = _secondary_chain_problem()
    initial = (
        ITC2007PEAssignment(0, -1, -1),
        ITC2007PEAssignment(1, 0, 0),
        ITC2007PEAssignment(2, 1, 0),
    )

    result = optimize_itc2007_pe_partial(
        problem,
        initial,
        deadline=time.perf_counter() + 1.0,
        seed=17,
        max_iterations=20,
    )

    validation = validate_itc2007_pe_solution(problem, result.assignments)
    assert validation.feasible
    assert validation.score.distance_to_feasibility == 0
    assert result.atomic_repairs_succeeded >= 1
    assert result.atomic_events_reinserted >= 2
    assert sorted(row.timeslot for row in result.assignments) == [0, 1, 2]


def test_partial_search_is_deterministic_for_seed() -> None:
    problem = _barrier_problem()
    results = [
        optimize_itc2007_pe_partial(
            problem,
            _initial(),
            deadline=time.perf_counter() + 1.0,
            seed=23,
            max_iterations=200,
        )
        for _ in range(2)
    ]

    assert results[0].assignments == results[1].assignments
    assert results[0].final_score == results[1].final_score
    assert results[0].best_trajectory == results[1].best_trajectory


def test_partial_search_expired_deadline_returns_exact_incumbent() -> None:
    initial = _initial()

    result = optimize_itc2007_pe_partial(
        _barrier_problem(),
        initial,
        deadline=time.perf_counter(),
        seed=3,
    )

    assert result.assignments == initial
    assert result.status == "deadline_before_search"
    assert result.deadline_exhausted


def test_scale_gated_solver_attributes_accepted_partial_local_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _scale_gated_problem()
    projected = (
        ITC2007PEAssignment(0, 0, 0),
        ITC2007PEAssignment(1, -1, -1),
    )
    improved = (
        ITC2007PEAssignment(0, 0, 0),
        ITC2007PEAssignment(1, 1, 0),
    )
    clock = [100.0]
    monkeypatch.setattr(pe_solver.time, "perf_counter", lambda: float(clock[0]))
    monkeypatch.setattr(
        pe_constructive,
        "construct_itc2007_pe_dsat",
        lambda *_args, **_kwargs: (
            projected,
            _constructive_telemetry(problem, projected),
        ),
    )
    monkeypatch.setattr(
        pe_solver,
        "_projected_cp_itc2007_pe",
        lambda *_args, **_kwargs: (
            projected,
            {
                "status": "no_improvement",
                "returned_source": "initial",
                "rounds": 0,
                "search_seconds": 0.0,
            },
        ),
    )
    monkeypatch.setattr(
        pe_local_search,
        "optimize_itc2007_pe_partial",
        lambda *_args, **_kwargs: _local_result(problem, projected, improved),
    )

    result = pe_solver.solve_itc2007_pe(
        problem,
        time_limit_seconds=1.0,
        seed=17,
        workers=1,
    )

    acceptance = result.telemetry["projected_cp"]["partial_local_search"][
        "service_acceptance"
    ]
    assert result.assignments == improved
    assert result.telemetry["returned_source"] == "partial_local_search"
    assert result.status == "partial_local_search_feasible"
    assert acceptance["accepted"] is True
    assert acceptance["reason"] == "strictly_improving_candidate"


def test_dense_scale_gate_routes_budget_directly_to_partial_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _dense_scale_gated_problem()
    initial = tuple(
        ITC2007PEAssignment(event, -1, -1) for event in range(problem.events)
    )
    improved = tuple(
        ITC2007PEAssignment(event, 0, event)
        if event == 0
        else ITC2007PEAssignment(event, -1, -1)
        for event in range(problem.events)
    )
    projected_called = False

    monkeypatch.setattr(
        pe_constructive,
        "construct_itc2007_pe_dsat",
        lambda *_args, **_kwargs: (
            initial,
            _constructive_telemetry(problem, initial),
        ),
    )

    def projected_search(*_args, **_kwargs):
        nonlocal projected_called
        projected_called = True
        raise AssertionError("dense projected master should be skipped")

    monkeypatch.setattr(pe_solver, "_projected_cp_itc2007_pe", projected_search)
    monkeypatch.setattr(
        pe_local_search,
        "optimize_itc2007_pe_partial",
        lambda *_args, **_kwargs: _local_result(problem, initial, improved),
    )

    result = pe_solver.solve_itc2007_pe(
        problem,
        time_limit_seconds=1.0,
        seed=17,
        workers=1,
    )

    assert not projected_called
    assert result.assignments == improved
    assert result.telemetry["dense_projection_prefer_partial"] is True
    assert (
        result.telemetry["projected_cp"]["status"]
        == "skipped_dense_projection_for_partial_search"
    )
    assert result.telemetry["returned_source"] == "partial_local_search"


@pytest.mark.parametrize(
    ("overrun", "expected_reason"),
    [
        (False, "candidate_not_strictly_better"),
        (True, "partial_local_search_deadline_overrun"),
    ],
)
def test_scale_gated_solver_reports_rejected_local_candidate_reason(
    monkeypatch: pytest.MonkeyPatch,
    overrun: bool,
    expected_reason: str,
) -> None:
    problem = _scale_gated_problem()
    constructive = (
        ITC2007PEAssignment(0, -1, -1),
        ITC2007PEAssignment(1, -1, -1),
    )
    projected = (
        ITC2007PEAssignment(0, 0, 0),
        ITC2007PEAssignment(1, -1, -1),
    )
    improved = (
        ITC2007PEAssignment(0, 0, 0),
        ITC2007PEAssignment(1, 1, 0),
    )
    clock = [200.0]
    monkeypatch.setattr(pe_solver.time, "perf_counter", lambda: float(clock[0]))
    monkeypatch.setattr(
        pe_constructive,
        "construct_itc2007_pe_dsat",
        lambda *_args, **_kwargs: (
            constructive,
            _constructive_telemetry(problem, constructive),
        ),
    )
    monkeypatch.setattr(
        pe_solver,
        "_projected_cp_itc2007_pe",
        lambda *_args, **_kwargs: (
            projected,
            {
                "status": "improved",
                "returned_source": "projected_cp",
                "rounds": 1,
                "search_seconds": 0.0,
            },
        ),
    )

    def local_search(*_args, deadline: float, **_kwargs) -> PEProjectedSearchResult:
        if overrun:
            clock[0] = float(deadline) + 0.001
            return _local_result(problem, projected, improved)
        return _local_result(problem, projected, projected)

    monkeypatch.setattr(
        pe_local_search,
        "optimize_itc2007_pe_partial",
        local_search,
    )

    result = pe_solver.solve_itc2007_pe(
        problem,
        time_limit_seconds=1.0,
        seed=17,
        workers=1,
    )

    acceptance = result.telemetry["projected_cp"]["partial_local_search"][
        "service_acceptance"
    ]
    assert result.assignments == projected
    assert result.telemetry["returned_source"] == "projected_cp"
    assert result.status == "projected_feasible"
    assert acceptance["accepted"] is False
    assert acceptance["reason"] == expected_reason
