from __future__ import annotations

from dataclasses import replace
import time

from benchmarks.itc2019 import (
    ITC2019Class,
    ITC2019Configuration,
    ITC2019Course,
    ITC2019Distribution,
    ITC2019OptimizationWeights,
    ITC2019Problem,
    ITC2019Room,
    ITC2019RoomOption,
    ITC2019Subpart,
    ITC2019TimeOption,
    ITC2019Travel,
    ITC2019Unavailable,
    parse_itc2019_solution,
    validate_itc2019_solution,
    validate_itc2019_solution_document,
    write_itc2019_solution,
)
from benchmarks.itc2019_decomposed import solve_itc2019_decomposed
from benchmarks.itc2019_grouped_calendar import (
    construct_itc2019_grouped_calendar,
    itc2019_grouped_calendar_admission_reason,
    should_construct_itc2019_grouped_calendar,
)


def _class(class_id: str, start: int) -> ITC2019Class:
    return ITC2019Class(
        id=class_id,
        limit=20,
        parent_id=None,
        room_required=True,
        time_options=tuple(
            ITC2019TimeOption(
                days=days,
                start=start,
                length=2,
                weeks="11",
            )
            for days in ("10", "01")
        ),
        room_options=(
            ITC2019RoomOption("R1"),
            ITC2019RoomOption("R2"),
        ),
    )


def _problem() -> ITC2019Problem:
    classes = (_class("A", 0), _class("B", 3))
    return ITC2019Problem(
        name="grouped-calendar-toy",
        nr_days=2,
        slots_per_day=10,
        nr_weeks=2,
        optimization=ITC2019OptimizationWeights(),
        rooms=(
            ITC2019Room(
                id="R1",
                capacity=100,
                travel=(ITC2019Travel("R2", 1),),
                unavailable=(ITC2019Unavailable("11", 0, 10, "11"),),
            ),
            ITC2019Room(
                id="R2",
                capacity=100,
                travel=(ITC2019Travel("R1", 1),),
                unavailable=(),
            ),
        ),
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
            for klass in classes
        ),
        distributions=(
            ITC2019Distribution("SameDays", True, 0, ("A", "B")),
            ITC2019Distribution("MinGap(1)", True, 0, ("A", "B")),
            ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),
            ITC2019Distribution("SameRoom", True, 0, ("A", "B")),
            ITC2019Distribution("MaxDayLoad(4)", True, 0, ("A", "B")),
            ITC2019Distribution("MaxDays(1)", True, 0, ("A", "B")),
        ),
        students=(),
        source_path="grouped-calendar-toy.xml",
    )


def test_grouped_calendar_admission_is_semantic_and_fails_closed() -> None:
    problem = _problem()
    assert itc2019_grouped_calendar_admission_reason(problem) is None
    assert not should_construct_itc2019_grouped_calendar(problem)

    invalid_class = replace(
        problem.classes[0],
        time_options=(
            ITC2019TimeOption("10", 0, 2, "10"),
            ITC2019TimeOption("01", 0, 2, "01"),
        ),
    )
    invalid = replace(
        problem,
        courses=(
            ITC2019Course(
                "invalid-course",
                (
                    ITC2019Configuration(
                        "invalid-configuration",
                        (ITC2019Subpart("invalid-subpart", (invalid_class,)),),
                    ),
                ),
            ),
            problem.courses[1],
        ),
    )
    assert (
        itc2019_grouped_calendar_admission_reason(invalid)
        == "grouped_calendar_variable_week_mask:A"
    )


def test_grouped_calendar_route_writes_reparsed_validator_clean_document(
    monkeypatch, tmp_path
) -> None:
    problem = _problem()
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.should_construct_itc2019_grouped_calendar",
        lambda received: received is problem,
    )

    result = solve_itc2019_decomposed(
        problem,
        time_limit_seconds=5.0,
        workers=1,
        random_seed=17,
    )

    assert result.status in {"FEASIBLE", "OPTIMAL"}
    assert result.formulation == "grouped_calendar_joint_v1"
    assert validate_itc2019_solution(problem, result.placements, {}) == []
    assert {placement.room_id for placement in result.placements} == {"R2"}

    output = write_itc2019_solution(
        problem, result.placements, {}, tmp_path / "out.xml"
    )
    reparsed = parse_itc2019_solution(output)
    assert validate_itc2019_solution_document(problem, reparsed) == []


def test_grouped_calendar_constructor_respects_absolute_deadline() -> None:
    diagnostics = {}

    result = construct_itc2019_grouped_calendar(
        _problem(),
        deadline=time.monotonic(),
        workers=1,
        random_seed=17,
        diagnostics=diagnostics,
    )

    assert result is None
    assert diagnostics["deadline_exhausted"] is True
