from __future__ import annotations

import time
from pathlib import Path

import pytest

from benchmarks.itc2019 import (
    ITC2019Class,
    ITC2019ClassPlacement,
    ITC2019Configuration,
    ITC2019Course,
    ITC2019Distribution,
    ITC2019OptimizationWeights,
    ITC2019Problem,
    ITC2019Room,
    ITC2019RoomOption,
    ITC2019Student,
    ITC2019Subpart,
    ITC2019TimeOption,
    parse_itc2019_solution,
    validate_itc2019_solution,
    validate_itc2019_solution_document,
    write_itc2019_solution,
)
from benchmarks.itc2019_decomposed import solve_itc2019_decomposed
from benchmarks.itc2019_generalized_occurrences import (
    construct_itc2019_generalized_occurrences,
    itc2019_generalized_occurrence_admission_reason,
)


def _class(
    class_id: str,
    options: tuple[ITC2019TimeOption, ...],
) -> ITC2019Class:
    return ITC2019Class(
        id=class_id,
        limit=10,
        parent_id=None,
        room_required=True,
        time_options=options,
        room_options=(ITC2019RoomOption(room_id="R1"),),
    )


def _problem(
    *,
    distributions: tuple[ITC2019Distribution, ...] = (),
    students: tuple[ITC2019Student, ...] = (),
) -> ITC2019Problem:
    first = _class(
        "A",
        (ITC2019TimeOption(days="11", start=0, length=2, weeks="1"),),
    )
    second = _class(
        "B",
        (
            ITC2019TimeOption(days="11", start=0, length=2, weeks="1"),
            ITC2019TimeOption(days="11", start=2, length=3, weeks="1"),
        ),
    )
    return ITC2019Problem(
        name="generalized-occurrence-toy",
        nr_days=2,
        slots_per_day=10,
        nr_weeks=1,
        optimization=ITC2019OptimizationWeights(),
        rooms=(ITC2019Room(id="R1", capacity=100, travel=(), unavailable=()),),
        courses=tuple(
            ITC2019Course(
                id=f"course-{klass.id}",
                configurations=(
                    ITC2019Configuration(
                        id=f"configuration-{klass.id}",
                        subparts=(
                            ITC2019Subpart(id=f"subpart-{klass.id}", classes=(klass,)),
                        ),
                    ),
                ),
            )
            for klass in (first, second)
        ),
        distributions=distributions,
        students=students,
        source_path="generalized-occurrence-toy.xml",
    )


def test_generalized_occurrences_enforce_every_selected_day_and_variable_duration():
    problem = _problem(
        distributions=(
            ITC2019Distribution(
                type="SameAttendees",
                required=True,
                penalty=0,
                class_ids=("A", "B"),
            ),
        )
    )
    diagnostics = {}

    placements = construct_itc2019_generalized_occurrences(
        problem,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=7,
        diagnostics=diagnostics,
    )

    assert placements is not None
    assert validate_itc2019_solution(problem, placements, {}) == []
    by_class = {placement.class_id: placement for placement in placements}
    assert by_class["A"].days == by_class["B"].days == "11"
    assert by_class["B"].start == 2
    assert diagnostics["option_occurrences"] == 6
    assert diagnostics["validation_errors"] == ()


def test_generalized_occurrence_admission_fails_closed_on_unsupported_semantics():
    problem = _problem(
        distributions=(
            ITC2019Distribution(
                type="SameRoom",
                required=True,
                penalty=0,
                class_ids=("A", "B"),
            ),
        )
    )

    assert itc2019_generalized_occurrence_admission_reason(problem) == (
        "generalized_occurrence_required_distribution_not_supported:SameRoom"
    )
    assert (
        construct_itc2019_generalized_occurrences(
            problem,
            deadline=time.monotonic() + 5.0,
            workers=1,
            random_seed=7,
        )
        is None
    )


def test_generalized_occurrence_admission_fails_closed_on_students():
    problem = _problem(students=(ITC2019Student(id="S1", course_ids=()),))

    assert (
        itc2019_generalized_occurrence_admission_reason(problem)
        == "generalized_occurrence_students_not_supported"
    )


def test_generalized_occurrence_constructor_observes_expired_deadline():
    diagnostics = {}

    placements = construct_itc2019_generalized_occurrences(
        _problem(),
        deadline=time.monotonic() - 1.0,
        workers=1,
        random_seed=7,
        diagnostics=diagnostics,
    )

    assert placements is None
    assert diagnostics["deadline_exhausted"] is True


def test_decomposed_routes_generalized_occurrences_and_round_trips_document(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    problem = _problem(
        distributions=(
            ITC2019Distribution(
                type="SameAttendees",
                required=True,
                penalty=0,
                class_ids=("A", "B"),
            ),
        )
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed."
        "should_construct_itc2019_generalized_occurrences",
        lambda received: received is problem,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.should_construct_itc2019_globally",
        lambda _received: False,
    )

    result = solve_itc2019_decomposed(
        problem,
        time_limit_seconds=10.0,
        workers=1,
        random_seed=7,
    )
    output = write_itc2019_solution(
        problem,
        result.placements,
        result.student_classes,
        tmp_path / "generalized-route.xml",
        metadata={"formulation": result.formulation},
    )
    document = parse_itc2019_solution(output)

    assert result.is_feasible
    assert result.formulation == "generalized_occurrence_global_v1"
    assert validate_itc2019_solution_document(problem, document) == []


def test_decomposed_rejection_preserves_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch,
):
    problem = _problem()
    candidate = (
        ITC2019ClassPlacement("A", days="11", start=0, weeks="1", room_id="R1"),
        ITC2019ClassPlacement("B", days="11", start=2, weeks="1", room_id="R1"),
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed."
        "should_construct_itc2019_generalized_occurrences",
        lambda _received: False,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.should_construct_itc2019_globally",
        lambda _received: False,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.construct_itc2019_generalized_occurrences",
        lambda *_args, **_kwargs: pytest.fail(
            "rejected generalized constructor must not run"
        ),
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.construct_itc2019_decomposed",
        lambda received, **_kwargs: candidate if received is problem else None,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed_quality.improve_itc2019_decomposed",
        lambda _problem, incumbent, _students, **_kwargs: tuple(incumbent),
    )

    result = solve_itc2019_decomposed(
        problem,
        time_limit_seconds=7.0,
        workers=1,
        random_seed=7,
    )

    assert result.is_feasible
    assert result.formulation == "decomposed_time_room_repair_v1"
    assert result.placements == candidate
