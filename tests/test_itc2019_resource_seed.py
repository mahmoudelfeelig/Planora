from __future__ import annotations

from dataclasses import replace
from itertools import product
import time

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
    _pair_distribution_satisfied,
    parse_itc2019_solution,
    validate_itc2019_solution_document,
    write_itc2019_solution,
)
from benchmarks.itc2019_decomposed import solve_itc2019_decomposed
from benchmarks.itc2019_resource_seed import (
    _Edge,
    _TimeValue,
    _compatible,
    construct_itc2019_resource_seed,
    itc2019_resource_seed_admission_reason,
    should_construct_itc2019_resource_seed,
)


def _class(class_id: str) -> ITC2019Class:
    return ITC2019Class(
        id=class_id,
        limit=20,
        parent_id=None,
        room_required=True,
        time_options=(
            ITC2019TimeOption("10", 0, 2, "11", penalty=1),
            ITC2019TimeOption("01", 0, 2, "11", penalty=2),
        ),
        room_options=(ITC2019RoomOption("R1"), ITC2019RoomOption("R2")),
    )


def _problem() -> ITC2019Problem:
    classes = (_class("A"), _class("B"))
    return ITC2019Problem(
        name="resource-seed-toy",
        nr_days=2,
        slots_per_day=8,
        nr_weeks=2,
        optimization=ITC2019OptimizationWeights(),
        rooms=(
            ITC2019Room("R1", 30, (), ()),
            ITC2019Room("R2", 30, (), ()),
        ),
        courses=tuple(
            ITC2019Course(
                f"course-{klass.id}",
                (
                    ITC2019Configuration(
                        f"configuration-{klass.id}",
                        (ITC2019Subpart(f"subpart-{klass.id}", (klass,)),),
                    ),
                ),
            )
            for klass in classes
        ),
        distributions=(
            ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),
            ITC2019Distribution("NotOverlap", True, 0, ("A", "B")),
            ITC2019Distribution("DifferentDays", True, 0, ("A", "B")),
            ITC2019Distribution("SameStart", True, 0, ("A", "B")),
            ITC2019Distribution("MinGap(1)", True, 0, ("A", "B")),
        ),
        students=(),
        source_path="resource-seed-toy.xml",
    )


def test_resource_seed_admission_and_deadline_fail_closed() -> None:
    problem = _problem()
    assert itc2019_resource_seed_admission_reason(problem) is None

    multi_day = replace(
        problem.classes[0],
        time_options=(ITC2019TimeOption("11", 0, 2, "11"),),
    )
    rejected = replace(
        problem,
        courses=(
            ITC2019Course(
                "rejected-course",
                (
                    ITC2019Configuration(
                        "rejected-configuration",
                        (ITC2019Subpart("rejected-subpart", (multi_day,)),),
                    ),
                ),
            ),
            problem.courses[1],
        ),
    )
    assert (
        itc2019_resource_seed_admission_reason(rejected)
        == "resource_seed_requires_single_day_options:A"
    )

    diagnostics = {}
    assert (
        construct_itc2019_resource_seed(
            problem,
            deadline=time.monotonic() - 0.001,
            workers=1,
            random_seed=17,
            diagnostics=diagnostics,
        )
        is None
    )
    assert diagnostics["deadline_exhausted"] is True


def test_resource_seed_exact_pair_extensions_match_official_evaluator() -> None:
    options = tuple(
        ITC2019TimeOption(
            "".join("1" if index == day else "0" for index in range(3)),
            start,
            length,
            weeks,
        )
        for day, weeks, start, length in product(
            range(3), ("001", "011", "101", "111"), range(3), range(1, 3)
        )
    )
    for left_time, right_time in product(options, repeat=2):
        left = _TimeValue(
            0,
            left_time.days.index("1"),
            left_time.start,
            left_time.start + left_time.length,
            int(left_time.weeks, 2),
            left_time.weeks.index("1"),
            0,
        )
        right = _TimeValue(
            0,
            right_time.days.index("1"),
            right_time.start,
            right_time.start + right_time.length,
            int(right_time.weeks, 2),
            right_time.weeks.index("1"),
            0,
        )
        left_placement = ITC2019ClassPlacement(
            "A", left_time.days, left_time.start, left_time.weeks
        )
        right_placement = ITC2019ClassPlacement(
            "B", right_time.days, right_time.start, right_time.weeks
        )
        for base, parameters in (
            ("NotOverlap", ()),
            ("DifferentDays", ()),
            ("SameStart", ()),
            ("MinGap", (2,)),
        ):
            assert _compatible(_Edge(0, 1, base, parameters), left, right) == (
                _pair_distribution_satisfied(
                    base,
                    parameters,
                    left_placement,
                    left_time,
                    right_placement,
                    right_time,
                    {},
                )
            )


def _sized_problem(class_count: int, options_per_class: int) -> ITC2019Problem:
    times = tuple(
        ITC2019TimeOption("10", start, 1, "11") for start in range(options_per_class)
    )
    classes = tuple(
        replace(_class(str(index)), time_options=times) for index in range(class_count)
    )
    return replace(
        _problem(),
        courses=tuple(
            ITC2019Course(
                f"course-{klass.id}",
                (
                    ITC2019Configuration(
                        f"configuration-{klass.id}",
                        (ITC2019Subpart(f"subpart-{klass.id}", (klass,)),),
                    ),
                ),
            )
            for klass in classes
        ),
        distributions=(),
    )


def test_resource_seed_uses_conservative_proven_scale_envelope() -> None:
    assert should_construct_itc2019_resource_seed(_sized_problem(500, 20))
    assert should_construct_itc2019_resource_seed(_sized_problem(1_000, 10))
    assert not should_construct_itc2019_resource_seed(_sized_problem(499, 21))
    assert not should_construct_itc2019_resource_seed(_sized_problem(1_001, 10))
    assert not should_construct_itc2019_resource_seed(
        replace(
            _sized_problem(500, 20),
            rooms=tuple(ITC2019Room(f"R{index}", 30, (), ()) for index in range(65)),
        )
    )


def test_resource_seed_route_is_first_feasible_and_document_valid(
    monkeypatch, tmp_path
) -> None:
    problem = _problem()
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.should_construct_itc2019_grouped_calendar",
        lambda _problem: False,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.should_construct_itc2019_generalized_occurrences",
        lambda _problem: False,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.should_construct_itc2019_globally",
        lambda _problem: False,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.should_construct_itc2019_resource_seed",
        lambda received: received is problem,
    )

    from benchmarks import itc2019_resource_seed as resource_seed

    real_solver = resource_seed.cp_model.CpSolver
    observed_solvers = []

    def solver_factory():
        solver = real_solver()
        observed_solvers.append(solver)
        return solver

    monkeypatch.setattr(resource_seed.cp_model, "CpSolver", solver_factory)
    result = solve_itc2019_decomposed(
        problem,
        time_limit_seconds=5.0,
        workers=1,
        random_seed=17,
    )

    assert result.is_feasible
    assert result.formulation == "resource_conflict_seed_v1"
    assert observed_solvers
    assert all(
        solver.parameters.stop_after_first_solution for solver in observed_solvers
    )
    output = write_itc2019_solution(
        problem,
        result.placements,
        result.student_classes,
        tmp_path / "resource-seed.xml",
        metadata={"formulation": result.formulation},
    )
    assert (
        validate_itc2019_solution_document(problem, parse_itc2019_solution(output))
        == []
    )


def test_resource_seed_route_uses_remaining_time_for_realized_quality(
    monkeypatch,
) -> None:
    problem = replace(
        _problem(),
        students=(ITC2019Student("S", ("course-A", "course-B")),),
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.should_construct_itc2019_grouped_calendar",
        lambda _problem: False,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.should_construct_itc2019_generalized_occurrences",
        lambda _problem: False,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.should_construct_itc2019_globally",
        lambda _problem: False,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.should_construct_itc2019_resource_seed",
        lambda _problem: True,
    )
    observed = {}

    def quality(problem, placements, student_classes, **kwargs):
        observed["problem"] = problem
        observed["placements"] = tuple(placements)
        observed["student_classes"] = dict(student_classes)
        observed["deadline"] = kwargs["deadline"]
        return tuple(placements)

    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed_quality.improve_itc2019_decomposed",
        quality,
    )

    result = solve_itc2019_decomposed(
        problem,
        time_limit_seconds=20.0,
        workers=1,
        random_seed=17,
    )

    assert result.is_feasible
    assert result.formulation == "resource_conflict_seed_v1"
    assert observed["problem"] is problem
    assert observed["placements"] == result.placements
    assert observed["student_classes"] == result.student_classes
    assert observed["deadline"] > time.monotonic()
