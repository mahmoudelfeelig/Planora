from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time
from xml.etree import ElementTree

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
    ITC2019SectioningResult,
    ITC2019Student,
    ITC2019Subpart,
    ITC2019TimeOption,
    ITC2019Travel,
    ITC2019Unavailable,
    estimate_itc2019_factorized_scale,
    evaluate_itc2019_distributions,
    parse_itc2019_solution,
    parse_itc2019_xml,
    score_itc2019_solution,
    solve_itc2019_native,
    solve_itc2019_student_sectioning,
    validate_itc2019_solution,
    validate_itc2019_solution_document,
    write_itc2019_solution,
)
from benchmarks.itc2019_decomposed import solve_itc2019_decomposed
from benchmarks.itc2019_global_components import (
    construct_itc2019_global_components,
    itc2019_global_component_admission_reason,
    should_construct_itc2019_globally,
)


def _klass(
    class_id: str,
    *,
    days: str,
    start: int,
    length: int,
    weeks: str,
    room: str,
    time_penalty: int = 0,
    room_penalty: int = 0,
    alternatives: tuple[ITC2019TimeOption, ...] = (),
) -> ITC2019Class:
    return ITC2019Class(
        id=class_id,
        limit=10,
        parent_id=None,
        room_required=True,
        time_options=alternatives
        or (
            ITC2019TimeOption(
                days=days,
                start=start,
                length=length,
                weeks=weeks,
                penalty=time_penalty,
            ),
        ),
        room_options=(ITC2019RoomOption(room_id=room, penalty=room_penalty),),
    )


def _problem(
    classes: tuple[ITC2019Class, ...],
    *,
    distributions: tuple[ITC2019Distribution, ...] = (),
    students: tuple[ITC2019Student, ...] = (),
) -> ITC2019Problem:
    courses = tuple(
        ITC2019Course(
            id=f"course-{klass.id}",
            configurations=(
                ITC2019Configuration(
                    id=f"config-{klass.id}",
                    subparts=(
                        ITC2019Subpart(id=f"subpart-{klass.id}", classes=(klass,)),
                    ),
                ),
            ),
        )
        for klass in classes
    )
    return ITC2019Problem(
        name="native-toy",
        nr_days=2,
        slots_per_day=20,
        nr_weeks=2,
        optimization=ITC2019OptimizationWeights(
            time=2,
            room=3,
            distribution=5,
            student=7,
        ),
        rooms=(
            ITC2019Room(
                id="R1",
                capacity=100,
                travel=(ITC2019Travel(room_id="R2", value=3),),
                unavailable=(),
            ),
            ITC2019Room(id="R2", capacity=100, travel=(), unavailable=()),
        ),
        courses=courses,
        distributions=distributions,
        students=students,
        source_path="native-toy.xml",
    )


def _scoring_fixture() -> tuple[ITC2019Problem, tuple[ITC2019ClassPlacement, ...]]:
    classes = (
        _klass(
            "A",
            days="10",
            start=0,
            length=2,
            weeks="11",
            room="R1",
            time_penalty=1,
            room_penalty=2,
        ),
        _klass(
            "B", days="10", start=4, length=2, weeks="11", room="R2", room_penalty=1
        ),
        _klass("C", days="10", start=8, length=2, weeks="11", room="R1"),
        _klass("D", days="01", start=0, length=8, weeks="10", room="R2"),
        _klass("E", days="01", start=12, length=2, weeks="01", room="R1"),
        _klass("F", days="10", start=1, length=2, weeks="11", room="R2"),
    )
    problem = _problem(classes)
    placements = tuple(
        ITC2019ClassPlacement(
            class_id=klass.id,
            days=klass.time_options[0].days,
            start=klass.time_options[0].start,
            weeks=klass.time_options[0].weeks,
            room_id=klass.room_options[0].room_id,
        )
        for klass in classes
    )
    return problem, placements


@pytest.mark.parametrize(
    ("constraint_type", "class_ids", "expected_units"),
    (
        ("SameStart", ("A", "B"), 1),
        ("SameTime", ("A", "D"), 0),
        ("DifferentTime", ("A", "F"), 1),
        ("SameDays", ("A", "B"), 0),
        ("DifferentDays", ("A", "D"), 0),
        ("SameWeeks", ("A", "B"), 0),
        ("DifferentWeeks", ("D", "E"), 0),
        ("SameRoom", ("A", "B"), 1),
        ("DifferentRoom", ("A", "C"), 1),
        ("Overlap", ("A", "F"), 0),
        ("NotOverlap", ("A", "F"), 1),
        ("SameAttendees", ("A", "B"), 1),
        ("Precedence", ("B", "A"), 1),
        ("WorkDay(5)", ("A", "B"), 1),
        ("MinGap(3)", ("A", "B"), 1),
        ("MaxDays(1)", ("A", "D"), 1),
        ("MaxDayLoad(4)", ("A", "B", "C"), 4),
        ("MaxBreaks(0,1)", ("A", "B", "C"), 4),
        ("MaxBlock(5,2)", ("A", "B", "C"), 2),
        ("MaxBlock(5,2)", ("D",), 0),
    ),
)
def test_all_official_distribution_families_have_independent_arithmetic(
    constraint_type: str,
    class_ids: tuple[str, ...],
    expected_units: int,
) -> None:
    problem, placements = _scoring_fixture()
    distribution = ITC2019Distribution(
        type=constraint_type,
        required=False,
        penalty=3,
        class_ids=class_ids,
    )
    score = evaluate_itc2019_distributions(
        replace(problem, distributions=(distribution,)),
        placements,
    )[0]

    assert score.violation_units == expected_units
    if constraint_type.startswith(("MaxDayLoad", "MaxBreaks", "MaxBlock")):
        assert score.penalty == 3 * expected_units // problem.nr_weeks
    else:
        assert score.penalty == 3 * expected_units


def test_official_weighted_objective_uses_components_then_instance_weights() -> None:
    problem, placements = _scoring_fixture()
    problem = replace(
        problem,
        distributions=(
            ITC2019Distribution("SameStart", False, 2, ("A", "B")),
            ITC2019Distribution("SameAttendees", False, 4, ("A", "B")),
            ITC2019Distribution("MaxDayLoad(4)", False, 3, ("A", "B", "C")),
            ITC2019Distribution("MaxBreaks(0,1)", False, 3, ("A", "B", "C")),
            ITC2019Distribution("MaxBlock(5,2)", False, 3, ("A", "B", "C")),
            ITC2019Distribution("MaxDays(1)", False, 5, ("A", "D")),
        ),
    )

    score = score_itc2019_solution(problem, placements, {})

    assert score.to_dict() == {
        "time": 1,
        "room": 3,
        "distribution": 26,
        "student": 0,
        "weighted_time": 2,
        "weighted_room": 9,
        "weighted_distribution": 130,
        "weighted_student": 0,
        "total": 141,
    }


def test_indistinguishable_time_options_use_the_minimum_published_penalty() -> None:
    klass = _klass(
        "A",
        days="10",
        start=3,
        length=2,
        weeks="11",
        room="R1",
        alternatives=(
            ITC2019TimeOption("10", 3, 2, "11", penalty=8),
            ITC2019TimeOption("10", 3, 2, "11", penalty=0),
        ),
    )
    problem = _problem((klass,))
    placements = (ITC2019ClassPlacement("A", "10", 3, "11", "R1"),)

    assert score_itc2019_solution(problem, placements, {}).time == 0

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        random_seed=23,
    )

    assert result.status == "OPTIMAL"
    assert result.objective is not None
    assert result.objective.time == 0
    assert result.placements == placements


@pytest.mark.parametrize(
    "constraint_type",
    ("MaxDayLoad(3)", "MaxBreaks(0,1)", "MaxBlock(5,2)"),
)
def test_group_penalty_divides_once_after_aggregating_all_weeks(
    constraint_type: str,
) -> None:
    problem, placements = _scoring_fixture()
    distribution = ITC2019Distribution(
        constraint_type,
        False,
        1,
        ("A", "B"),
    )

    score = evaluate_itc2019_distributions(
        replace(problem, distributions=(distribution,)),
        placements,
    )[0]

    assert score.violation_units == 2
    assert score.penalty == 1


def test_pairwise_soft_penalty_counts_every_unordered_class_pair() -> None:
    problem, placements = _scoring_fixture()
    distribution = ITC2019Distribution(
        "SameStart",
        False,
        2,
        ("A", "B", "C"),
    )

    score = evaluate_itc2019_distributions(
        replace(problem, distributions=(distribution,)),
        placements,
    )[0]

    assert score.violation_units == 3
    assert score.penalty == 6


def test_max_block_uses_unique_time_intervals_for_coincident_classes() -> None:
    first = _klass("A", days="10", start=0, length=2, weeks="11", room="R1")
    second = _klass("B", days="10", start=0, length=2, weeks="11", room="R2")
    distribution = ITC2019Distribution("MaxBlock(1,0)", False, 5, ("A", "B"))
    problem = _problem((first, second), distributions=(distribution,))
    placements = (
        ITC2019ClassPlacement("A", "10", 0, "11", "R1"),
        ITC2019ClassPlacement("B", "10", 0, "11", "R2"),
    )

    score = evaluate_itc2019_distributions(problem, placements)[0]

    assert score.violation_units == 0
    assert score.penalty == 0


def test_complete_validator_rejects_required_distribution_violation() -> None:
    problem, placements = _scoring_fixture()
    problem = replace(
        problem,
        distributions=(ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),),
    )

    errors = validate_itc2019_solution(problem, placements, {})

    assert errors == ["required distribution 1 (SameAttendees) has 1 violation unit(s)"]


def test_native_solver_jointly_places_and_sections_with_exact_objective() -> None:
    first = _klass("A", days="10", start=0, length=2, weeks="11", room="R1")
    second = _klass(
        "B",
        days="10",
        start=0,
        length=2,
        weeks="11",
        room="R1",
        alternatives=(
            ITC2019TimeOption("10", 0, 2, "11", penalty=0),
            ITC2019TimeOption("10", 2, 2, "11", penalty=3),
        ),
    )
    distributions = (
        ITC2019Distribution("NotOverlap", True, 0, ("A", "B")),
        ITC2019Distribution("MaxDays(1)", True, 0, ("A", "B")),
        ITC2019Distribution("MaxDayLoad(4)", True, 0, ("A", "B")),
        ITC2019Distribution("MaxBreaks(0,0)", True, 0, ("A", "B")),
        ITC2019Distribution("MaxBlock(4,0)", True, 0, ("A", "B")),
    )
    student = ITC2019Student("S", ("course-A", "course-B"))
    problem = _problem(
        (first, second), distributions=distributions, students=(student,)
    )

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=5.0,
        workers=1,
        random_seed=19,
    )

    assert result.status == "OPTIMAL"
    assert result.is_feasible
    assert result.objective is not None
    assert result.objective.total == 6
    assert result.student_classes == {"S": ("A", "B")}
    assert {placement.class_id for placement in result.placements} == {"A", "B"}
    assert not validate_itc2019_solution(
        problem,
        result.placements,
        result.student_classes,
    )
    assert result.deterministic_seed == 19
    assert result.workers == 1


def test_native_solver_optimizes_student_conflicts_against_time_penalties() -> None:
    first = _klass("A", days="10", start=0, length=2, weeks="11", room="R1")
    second = _klass(
        "B",
        days="10",
        start=0,
        length=2,
        weeks="11",
        room="R2",
        alternatives=(
            ITC2019TimeOption("10", 0, 2, "11", penalty=0),
            ITC2019TimeOption("10", 5, 2, "11", penalty=1),
        ),
    )
    student = ITC2019Student("S", ("course-A", "course-B"))
    problem = _problem((first, second), students=(student,))

    result = solve_itc2019_native(problem, time_limit_seconds=5.0, workers=1)

    assert result.status == "OPTIMAL"
    assert result.objective is not None
    assert result.objective.student == 0
    assert result.objective.time == 1
    assert result.objective.total == 2
    assert (
        next(
            placement.start
            for placement in result.placements
            if placement.class_id == "B"
        )
        == 5
    )


def test_auto_dispatch_uses_cartesian_for_small_twenty_class_problem() -> None:
    room_ids = ("R1", "R2", "R3", "R4")
    classes = tuple(
        replace(
            _klass(
                str(index + 1),
                days="10",
                start=index,
                length=1,
                weeks="11",
                room="R1",
            ),
            room_options=tuple(ITC2019RoomOption(room_id) for room_id in room_ids),
        )
        for index in range(20)
    )
    problem = replace(
        _problem(classes),
        rooms=tuple(ITC2019Room(room_id, 100, (), ()) for room_id in room_ids),
    )

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=3.0,
        workers=1,
        random_seed=17,
    )

    assert result.is_feasible
    assert len(result.placements) == 20
    assert result.requested_formulation == "auto"
    assert result.effective_formulation == "cartesian"
    assert result.formulation == "cartesian_joint_v1"
    assert result.formulation_selection_reason == (
        "cartesian_domain_and_scale_guards_admitted"
    )
    assert result.raw_cartesian_domain_values == 80
    assert result.auto_cartesian_domain_threshold == 50_000


def test_auto_dispatch_matches_cartesian_free_constant_distribution_matrices() -> None:
    first = _klass(
        "A",
        days="10",
        start=0,
        length=1,
        weeks="11",
        room="R1",
        alternatives=(
            ITC2019TimeOption("10", 0, 1, "11"),
            ITC2019TimeOption("10", 2, 1, "11"),
        ),
    )
    second = _klass(
        "B",
        days="01",
        start=0,
        length=1,
        weeks="11",
        room="R2",
        alternatives=(
            ITC2019TimeOption("01", 0, 1, "11"),
            ITC2019TimeOption("01", 2, 1, "11"),
        ),
    )
    problem = _problem(
        (first, second),
        distributions=(
            ITC2019Distribution("DifferentDays", True, 0, ("A", "B")),
            ITC2019Distribution("DifferentDays", True, 0, ("A", "B")),
        ),
    )

    explicit = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        max_pair_matrix_cells=4,
        formulation="cartesian",
    )
    automatic = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        max_pair_matrix_cells=4,
    )

    assert explicit.status == automatic.status == "OPTIMAL"
    assert automatic.effective_formulation == "cartesian"
    assert automatic.formulation_selection_reason == (
        "cartesian_domain_and_scale_guards_admitted"
    )


def test_cartesian_constant_distribution_matrix_obeys_preallocation_ceiling() -> None:
    import benchmarks.itc2019 as itc2019

    first = _klass(
        "A",
        days="10",
        start=0,
        length=1,
        weeks="11",
        room="R1",
        alternatives=tuple(
            ITC2019TimeOption("10", start, 1, "11") for start in range(5)
        ),
    )
    second = _klass(
        "B",
        days="01",
        start=0,
        length=1,
        weeks="11",
        room="R2",
    )
    problem = _problem(
        (first, second),
        distributions=(ITC2019Distribution("DifferentDays", True, 0, ("A", "B")),),
    )

    estimate = itc2019._estimate_itc2019_auto_dispatch(
        problem,
        max_pair_matrix_cells=4,
        max_group_table_rows=1,
        deadline=float("inf"),
    )
    explicit = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        max_pair_matrix_cells=4,
        formulation="cartesian",
    )
    automatic = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        max_pair_matrix_cells=4,
    )

    assert not estimate.cartesian_admitted
    assert estimate.selection_reason == "cartesian_pair_matrix_guard_exceeded"
    assert explicit.status == "UNSUPPORTED_MODEL_SCALE"
    assert explicit.unsupported_reasons == (
        "exact pair matrices require more than 4 cells",
    )
    assert automatic.effective_formulation == "decomposed"
    assert automatic.is_feasible
    assert automatic.formulation_selection_reason == (
        "decomposed_sparse_semantics_admitted"
    )


def test_auto_dispatch_matches_cartesian_free_constant_student_matrices() -> None:
    def klass(class_id: str, days: str, room: str) -> ITC2019Class:
        return _klass(
            class_id,
            days=days,
            start=0,
            length=1,
            weeks="11",
            room=room,
            alternatives=(
                ITC2019TimeOption(days, 0, 1, "11"),
                ITC2019TimeOption(days, 2, 1, "11"),
            ),
        )

    problem = _problem(
        (
            klass("A", "10", "R1"),
            klass("B", "01", "R2"),
            klass("C", "10", "R1"),
            klass("D", "01", "R2"),
        ),
        students=(
            ITC2019Student("S1", ("course-A", "course-B")),
            ITC2019Student("S2", ("course-C", "course-D")),
        ),
    )

    explicit = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        max_pair_matrix_cells=4,
        formulation="cartesian",
    )
    automatic = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        max_pair_matrix_cells=4,
    )

    assert explicit.status == automatic.status == "OPTIMAL"
    assert automatic.effective_formulation == "cartesian"
    assert automatic.formulation_selection_reason == (
        "cartesian_domain_and_scale_guards_admitted"
    )


def test_cartesian_constant_student_matrix_obeys_preallocation_ceiling() -> None:
    import benchmarks.itc2019 as itc2019

    first = _klass(
        "A",
        days="10",
        start=0,
        length=1,
        weeks="11",
        room="R1",
        alternatives=tuple(
            ITC2019TimeOption("10", start, 1, "11") for start in range(5)
        ),
    )
    second = _klass(
        "B",
        days="01",
        start=0,
        length=1,
        weeks="11",
        room="R2",
    )
    problem = _problem(
        (first, second),
        students=(ITC2019Student("S", ("course-A", "course-B")),),
    )

    estimate = itc2019._estimate_itc2019_auto_dispatch(
        problem,
        max_pair_matrix_cells=4,
        max_group_table_rows=1,
        deadline=float("inf"),
    )
    explicit = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        max_pair_matrix_cells=4,
        formulation="cartesian",
    )
    automatic = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        max_pair_matrix_cells=4,
    )

    assert not estimate.cartesian_admitted
    assert estimate.selection_reason == "cartesian_pair_matrix_guard_exceeded"
    assert explicit.status == "UNSUPPORTED_MODEL_SCALE"
    assert explicit.unsupported_reasons == (
        "exact pair matrices require more than 4 cells",
    )
    assert automatic.effective_formulation == "decomposed"
    assert automatic.is_feasible
    assert automatic.formulation_selection_reason == (
        "decomposed_sparse_semantics_admitted"
    )


def test_cartesian_student_matrix_guard_charges_first_seen_pair_once() -> None:
    import benchmarks.itc2019 as itc2019

    options = (
        ITC2019TimeOption("10", 0, 1, "11"),
        ITC2019TimeOption("10", 2, 1, "11"),
    )
    problem = _problem(
        (
            _klass(
                "A",
                days="10",
                start=0,
                length=1,
                weeks="11",
                room="R1",
                alternatives=options,
            ),
            _klass(
                "B",
                days="10",
                start=0,
                length=1,
                weeks="11",
                room="R1",
                alternatives=options,
            ),
        ),
        students=(
            ITC2019Student("S1", ("course-A", "course-B")),
            ITC2019Student("S2", ("course-A", "course-B")),
        ),
    )

    estimate = itc2019._estimate_itc2019_auto_dispatch(
        problem,
        max_pair_matrix_cells=4,
        max_group_table_rows=1,
        deadline=float("inf"),
    )
    explicit = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        max_pair_matrix_cells=4,
        formulation="cartesian",
    )
    automatic = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        max_pair_matrix_cells=4,
    )

    assert estimate.cartesian_admitted
    assert explicit.status == automatic.status == "OPTIMAL"
    assert automatic.effective_formulation == "cartesian"
    assert automatic.formulation_selection_reason == (
        "cartesian_domain_and_scale_guards_admitted"
    )


def test_auto_dispatch_nonconstant_pair_matrix_budget_boundary() -> None:
    import benchmarks.itc2019 as itc2019

    options = (
        ITC2019TimeOption("10", 0, 1, "11"),
        ITC2019TimeOption("10", 2, 1, "11"),
    )
    problem = _problem(
        (
            _klass(
                "A",
                days="10",
                start=0,
                length=1,
                weeks="11",
                room="R1",
                alternatives=options,
            ),
            _klass(
                "B",
                days="10",
                start=0,
                length=1,
                weeks="11",
                room="R2",
                alternatives=options,
            ),
        ),
        distributions=(ITC2019Distribution("SameStart", True, 0, ("A", "B")),),
    )

    admitted_estimate = itc2019._estimate_itc2019_auto_dispatch(
        problem,
        max_pair_matrix_cells=4,
        max_group_table_rows=1,
        deadline=float("inf"),
    )
    rejected_estimate = itc2019._estimate_itc2019_auto_dispatch(
        problem,
        max_pair_matrix_cells=3,
        max_group_table_rows=1,
        deadline=float("inf"),
    )
    admitted_explicit = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        max_pair_matrix_cells=4,
        formulation="cartesian",
    )
    rejected_explicit = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        max_pair_matrix_cells=3,
        formulation="cartesian",
    )
    admitted = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        max_pair_matrix_cells=4,
    )
    rejected = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        max_pair_matrix_cells=3,
    )

    assert admitted_estimate.cartesian_admitted
    assert not rejected_estimate.cartesian_admitted
    assert rejected_estimate.selection_reason == (
        "cartesian_pair_matrix_guard_exceeded"
    )
    assert admitted_explicit.status == "OPTIMAL"
    assert rejected_explicit.status == "UNSUPPORTED_MODEL_SCALE"
    assert rejected_explicit.unsupported_reasons == (
        "exact pair matrices require more than 3 cells",
    )
    assert admitted.status == "OPTIMAL"
    assert admitted.effective_formulation == "cartesian"
    assert rejected.effective_formulation == "decomposed"
    assert (
        rejected.formulation_selection_reason == "decomposed_sparse_semantics_admitted"
    )


def test_auto_dispatch_uses_decomposed_above_raw_cartesian_threshold() -> None:
    times = tuple(
        ITC2019TimeOption(days, start, 1, weeks)
        for days in ("10", "01", "11")
        for weeks in ("10", "01", "11")
        for start in range(20)
    )
    room_ids = tuple(f"R{index}" for index in range(300))
    klass = replace(
        _klass(
            "A",
            days="10",
            start=0,
            length=1,
            weeks="11",
            room=room_ids[0],
            alternatives=times,
        ),
        room_options=tuple(ITC2019RoomOption(room_id) for room_id in room_ids),
    )
    problem = replace(
        _problem((klass,)),
        rooms=tuple(ITC2019Room(room_id, 100, (), ()) for room_id in room_ids),
    )

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=3.0,
        workers=1,
        random_seed=17,
    )

    assert result.is_feasible
    assert result.requested_formulation == "auto"
    assert result.effective_formulation == "decomposed"
    assert result.formulation == "decomposed_time_room_repair_v1"
    assert result.formulation_selection_reason == "decomposed_sparse_semantics_admitted"
    assert result.raw_cartesian_domain_values == 54_000
    assert result.auto_cartesian_domain_threshold == 50_000


def test_auto_dispatch_threshold_is_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import benchmarks.itc2019 as itc2019

    problem = _problem(
        (_klass("A", days="10", start=0, length=1, weeks="11", room="R1"),)
    )
    monkeypatch.setattr(
        itc2019,
        "_raw_cartesian_domain_values",
        lambda _problem, *, deadline: 50_000,
    )
    at_boundary = itc2019._estimate_itc2019_auto_dispatch(
        problem,
        max_pair_matrix_cells=1,
        max_group_table_rows=1,
        deadline=float("inf"),
    )
    monkeypatch.setattr(
        itc2019,
        "_raw_cartesian_domain_values",
        lambda _problem, *, deadline: 50_001,
    )
    above_boundary = itc2019._estimate_itc2019_auto_dispatch(
        problem,
        max_pair_matrix_cells=1,
        max_group_table_rows=1,
        deadline=float("inf"),
    )

    assert at_boundary.cartesian_admitted
    assert at_boundary.selection_reason == (
        "cartesian_domain_and_scale_guards_admitted"
    )
    assert not above_boundary.cartesian_admitted
    assert above_boundary.selection_reason == (
        "raw_cartesian_domain_exceeds_auto_threshold"
    )


def test_auto_dispatch_estimate_and_solver_share_one_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import benchmarks.itc2019 as itc2019

    problem = _problem(
        (_klass("A", days="10", start=0, length=1, weeks="11", room="R1"),)
    )
    moments = iter((100.0, 101.0, 102.0))
    monkeypatch.setattr(itc2019.time, "monotonic", lambda: next(moments))
    monkeypatch.setattr(
        itc2019,
        "_estimate_itc2019_auto_dispatch",
        lambda *args, **kwargs: itc2019._ITC2019AutoDispatchEstimate(
            raw_cartesian_domain_values=1,
            cartesian_admitted=True,
            selection_reason="cartesian_domain_and_scale_guards_admitted",
        ),
    )
    observed: dict[str, float] = {}

    def fake_cartesian(*args: object, **kwargs: object) -> object:
        observed["time_limit_seconds"] = float(kwargs["time_limit_seconds"])
        return itc2019.ITC2019NativeSolveResult(
            status="OPTIMAL",
            placements=(),
            student_classes={},
            objective=None,
            best_bound=0.0,
            wall_time_seconds=0.5,
            model_build_seconds=0.25,
            solver_wall_time_seconds=0.25,
            conflicts=0,
            branches=0,
            deterministic_seed=17,
            workers=1,
        )

    monkeypatch.setattr(itc2019, "_solve_itc2019_native_cartesian", fake_cartesian)

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=10.0,
        workers=1,
        random_seed=17,
    )

    assert observed["time_limit_seconds"] == 9.0
    assert result.wall_time_seconds == 2.0
    assert result.model_build_seconds == 1.25


def test_auto_dispatch_fails_closed_when_estimate_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import benchmarks.itc2019 as itc2019

    problem = _problem(
        (_klass("A", days="10", start=0, length=1, weeks="11", room="R1"),)
    )

    def expired(*args: object, **kwargs: object) -> object:
        raise TimeoutError

    monkeypatch.setattr(itc2019, "_estimate_itc2019_auto_dispatch", expired)

    result = solve_itc2019_native(problem, time_limit_seconds=1.0)

    assert result.status == "DEADLINE_EXCEEDED"
    assert not result.placements
    assert result.requested_formulation == "auto"
    assert result.effective_formulation == "not_started"
    assert result.formulation == "not_started"
    assert result.sectioning_mode == "not_started"
    assert result.formulation_selection_reason == (
        "auto_dispatch_estimate_deadline_exceeded"
    )


def test_auto_dispatch_distinguishes_budget_exhaustion_after_estimate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import benchmarks.itc2019 as itc2019

    problem = _problem(
        (_klass("A", days="10", start=0, length=1, weeks="11", room="R1"),)
    )
    moments = iter((100.0, 111.0, 112.0))
    monkeypatch.setattr(itc2019.time, "monotonic", lambda: next(moments))
    monkeypatch.setattr(
        itc2019,
        "_estimate_itc2019_auto_dispatch",
        lambda *args, **kwargs: itc2019._ITC2019AutoDispatchEstimate(
            raw_cartesian_domain_values=1,
            cartesian_admitted=True,
            selection_reason="cartesian_domain_and_scale_guards_admitted",
        ),
    )

    result = solve_itc2019_native(problem, time_limit_seconds=10.0)

    assert result.status == "DEADLINE_EXCEEDED"
    assert result.requested_formulation == "auto"
    assert result.effective_formulation == "not_started"
    assert result.formulation == "not_started"
    assert result.sectioning_mode == "not_started"
    assert result.formulation_selection_reason == (
        "auto_dispatch_budget_exhausted_after_estimate"
    )
    assert result.raw_cartesian_domain_values == 1


def test_factorized_solver_keeps_time_predicates_independent_of_room_domains() -> None:
    times = (
        ITC2019TimeOption("10", 0, 2, "11", penalty=0),
        ITC2019TimeOption("10", 4, 2, "11", penalty=1),
    )
    first = replace(
        _klass(
            "A",
            days="10",
            start=0,
            length=2,
            weeks="11",
            room="R1",
            alternatives=times,
        ),
        room_options=(ITC2019RoomOption("R1"), ITC2019RoomOption("R2")),
    )
    second = replace(
        _klass(
            "B",
            days="10",
            start=0,
            length=2,
            weeks="11",
            room="R3",
            alternatives=times,
        ),
        room_options=(ITC2019RoomOption("R3"), ITC2019RoomOption("R4")),
    )
    problem = _problem(
        (first, second),
        distributions=(ITC2019Distribution("SameStart", True, 0, ("A", "B")),),
    )
    problem = replace(
        problem,
        rooms=(
            *problem.rooms,
            ITC2019Room("R3", 100, (), ()),
            ITC2019Room("R4", 100, (), ()),
        ),
    )

    factorized = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        max_pair_matrix_cells=4,
        formulation="factorized",
    )
    cartesian = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        max_pair_matrix_cells=4,
        formulation="cartesian",
    )

    assert factorized.status == "OPTIMAL"
    assert factorized.formulation == "factorized_domains_v2"
    assert factorized.time_domain_values == 4
    assert factorized.room_domain_values == 4
    assert factorized.predicate_table_cells == 4
    assert factorized.sparse_room_constraints == 0
    assert factorized.objective is not None
    assert not validate_itc2019_solution(
        problem,
        factorized.placements,
        factorized.student_classes,
    )
    assert cartesian.status == "UNSUPPORTED_MODEL_SCALE"


def test_sparse_room_resources_scale_by_recurring_meeting_occurrences() -> None:
    times = tuple(ITC2019TimeOption("10", start, 1, "11") for start in range(12))
    first = replace(
        _klass(
            "A",
            days="10",
            start=0,
            length=1,
            weeks="11",
            room="R1",
            alternatives=times,
        ),
        room_options=(ITC2019RoomOption("R1"), ITC2019RoomOption("R2")),
    )
    second = replace(
        _klass(
            "B",
            days="10",
            start=0,
            length=1,
            weeks="11",
            room="R1",
            alternatives=times,
        ),
        room_options=(ITC2019RoomOption("R1"), ITC2019RoomOption("R2")),
    )
    problem = _problem((first, second))

    estimate = estimate_itc2019_factorized_scale(
        problem,
        max_pair_matrix_cells=1,
        max_sparse_room_constraints=49,
    )

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=3.0,
        max_pair_matrix_cells=1,
        max_sparse_room_constraints=49,
        formulation="factorized",
    )

    assert result.status == "OPTIMAL"
    assert estimate.admitted
    assert estimate.factorized_domain_values == 28
    assert estimate.cartesian_domain_values == 48
    assert estimate.sparse_room_constraints == 49
    assert result.predicate_table_cells == 0
    # 2 classes x 12 alternatives x 2 active weeks, plus one NoOverlap2D.
    assert result.sparse_room_constraints == 49
    assert not validate_itc2019_solution(
        problem,
        result.placements,
        result.student_classes,
    )


def test_sparse_same_room_relation_avoids_dense_room_matrix() -> None:
    first = replace(
        _klass("A", days="10", start=0, length=1, weeks="11", room="R1"),
        room_options=(ITC2019RoomOption("R1"), ITC2019RoomOption("R2")),
    )
    second = replace(
        _klass("B", days="10", start=2, length=1, weeks="11", room="R1"),
        room_options=(ITC2019RoomOption("R1"), ITC2019RoomOption("R2")),
    )
    problem = _problem(
        (first, second),
        distributions=(ITC2019Distribution("SameRoom", True, 0, ("A", "B")),),
    )

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=3.0,
        max_pair_matrix_cells=1,
        max_sparse_room_constraints=6,
        formulation="factorized",
    )

    assert result.status == "OPTIMAL"
    assert result.predicate_table_cells == 0
    # Four meeting rectangles, one NoOverlap2D, and one exact room relation.
    assert result.sparse_room_constraints == 6
    assert len({placement.room_id for placement in result.placements}) == 1


def test_room_resources_merge_overlapping_unavailability_exactly() -> None:
    klass = _klass(
        "A",
        days="10",
        start=0,
        length=1,
        weeks="11",
        room="R1",
        alternatives=(
            ITC2019TimeOption("10", 0, 1, "11"),
            ITC2019TimeOption("10", 5, 1, "11", penalty=1),
        ),
    )
    problem = _problem((klass,))
    problem = replace(
        problem,
        rooms=(
            replace(
                problem.rooms[0],
                unavailable=(
                    ITC2019Unavailable("10", 0, 2, "11"),
                    ITC2019Unavailable("10", 1, 2, "11"),
                ),
            ),
            problem.rooms[1],
        ),
    )

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=3.0,
        max_pair_matrix_cells=1,
        max_sparse_room_constraints=7,
        formulation="factorized",
    )

    assert result.status == "OPTIMAL"
    # Four optional meeting rectangles, two merged fixed blocks, one NoOverlap2D.
    assert result.sparse_room_constraints == 7
    assert result.placements[0].start == 5
    assert not validate_itc2019_solution(
        problem,
        result.placements,
        result.student_classes,
    )


def test_room_resources_allow_same_time_in_distinct_selected_rooms() -> None:
    classes = tuple(
        replace(
            _klass(
                class_id,
                days="10",
                start=3,
                length=4,
                weeks="11",
                room="R1",
            ),
            room_options=(ITC2019RoomOption("R1"), ITC2019RoomOption("R2")),
        )
        for class_id in ("A", "B")
    )

    result = solve_itc2019_native(
        _problem(classes),
        time_limit_seconds=3.0,
        max_pair_matrix_cells=1,
        formulation="factorized",
    )

    assert result.status == "OPTIMAL"
    assert {placement.start for placement in result.placements} == {3}
    assert len({placement.room_id for placement in result.placements}) == 2


def test_room_resources_do_not_conflict_across_disjoint_week_masks() -> None:
    classes = (
        _klass("A", days="10", start=3, length=4, weeks="10", room="R1"),
        _klass("B", days="10", start=3, length=4, weeks="01", room="R1"),
    )

    result = solve_itc2019_native(
        _problem(classes),
        time_limit_seconds=3.0,
        max_pair_matrix_cells=1,
        formulation="factorized",
    )

    assert result.status == "OPTIMAL"
    assert {placement.room_id for placement in result.placements} == {"R1"}
    assert {placement.start for placement in result.placements} == {3}


def test_room_resources_enforce_multislot_overlap_on_every_day_and_week() -> None:
    first = _klass("A", days="11", start=2, length=4, weeks="11", room="R1")
    second = _klass(
        "B",
        days="11",
        start=5,
        length=2,
        weeks="11",
        room="R1",
        alternatives=(
            ITC2019TimeOption("11", 5, 2, "11"),
            ITC2019TimeOption("11", 6, 2, "11", penalty=1),
        ),
    )

    result = solve_itc2019_native(
        _problem((first, second)),
        time_limit_seconds=3.0,
        max_pair_matrix_cells=1,
        formulation="factorized",
    )

    assert result.status == "OPTIMAL"
    assert {placement.class_id: placement.start for placement in result.placements} == {
        "A": 2,
        "B": 6,
    }


def test_room_resources_reject_partial_unavailability_overlap() -> None:
    klass = _klass(
        "A",
        days="10",
        start=0,
        length=4,
        weeks="10",
        room="R1",
        alternatives=(
            ITC2019TimeOption("10", 0, 4, "10"),
            ITC2019TimeOption("10", 5, 4, "10", penalty=1),
        ),
    )
    problem = _problem((klass,))
    problem = replace(
        problem,
        rooms=(
            replace(
                problem.rooms[0],
                unavailable=(ITC2019Unavailable("10", 3, 2, "10"),),
            ),
            problem.rooms[1],
        ),
    )

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=3.0,
        max_pair_matrix_cells=1,
        formulation="factorized",
    )

    assert result.status == "OPTIMAL"
    assert result.placements[0].start == 5
    assert not validate_itc2019_solution(
        problem,
        result.placements,
        result.student_classes,
    )


def test_factorized_and_cartesian_joint_models_have_the_same_exact_optimum() -> None:
    first = replace(
        _klass(
            "A",
            days="10",
            start=0,
            length=2,
            weeks="11",
            room="R1",
            alternatives=(
                ITC2019TimeOption("10", 0, 2, "11", penalty=0),
                ITC2019TimeOption("10", 4, 2, "11", penalty=2),
            ),
        ),
        room_options=(ITC2019RoomOption("R1"), ITC2019RoomOption("R2", 1)),
    )
    second = replace(
        _klass(
            "B",
            days="10",
            start=0,
            length=2,
            weeks="11",
            room="R2",
            alternatives=(
                ITC2019TimeOption("10", 0, 2, "11", penalty=0),
                ITC2019TimeOption("10", 4, 2, "11", penalty=2),
            ),
        ),
        room_options=(ITC2019RoomOption("R1", 1), ITC2019RoomOption("R2")),
    )
    problem = _problem(
        (first, second),
        distributions=(ITC2019Distribution("SameAttendees", False, 3, ("A", "B")),),
        students=(ITC2019Student("S", ("course-A", "course-B")),),
    )

    factorized = solve_itc2019_native(
        problem,
        time_limit_seconds=5.0,
        workers=1,
        formulation="factorized",
    )
    cartesian = solve_itc2019_native(
        problem,
        time_limit_seconds=5.0,
        workers=1,
        formulation="cartesian",
    )

    assert factorized.status == cartesian.status == "OPTIMAL"
    assert factorized.requested_formulation == "factorized"
    assert factorized.effective_formulation == "factorized"
    assert factorized.formulation_selection_reason == "explicit_factorized"
    assert cartesian.requested_formulation == "cartesian"
    assert cartesian.effective_formulation == "cartesian"
    assert cartesian.formulation_selection_reason == "explicit_cartesian"
    assert factorized.objective is not None
    assert cartesian.objective is not None
    assert factorized.objective.to_dict() == cartesian.objective.to_dict()
    assert not validate_itc2019_solution(
        problem,
        factorized.placements,
        factorized.student_classes,
    )


def test_factorized_same_attendees_preserves_distinct_asymmetric_travel_semantics() -> (
    None
):
    later = _klass("A", days="10", start=5, length=2, weeks="11", room="R1")
    earlier = _klass("B", days="10", start=0, length=2, weeks="11", room="R2")
    problem = _problem(
        (later, earlier),
        distributions=(ITC2019Distribution("SameAttendees", False, 2, ("A", "B")),),
        students=(ITC2019Student("S", ("course-A", "course-B")),),
    )
    problem = replace(
        problem,
        rooms=(
            ITC2019Room("R1", 100, (ITC2019Travel("R2", 5),), ()),
            ITC2019Room("R2", 100, (ITC2019Travel("R1", 0),), ()),
        ),
    )

    factorized = solve_itc2019_native(
        problem,
        time_limit_seconds=3.0,
        workers=1,
        formulation="factorized",
    )
    cartesian = solve_itc2019_native(
        problem,
        time_limit_seconds=3.0,
        workers=1,
        formulation="cartesian",
    )

    assert factorized.status == cartesian.status == "OPTIMAL"
    assert factorized.objective is not None
    assert cartesian.objective is not None
    assert factorized.objective.to_dict() == cartesian.objective.to_dict()
    assert factorized.objective.distribution == 2
    assert factorized.objective.student == 0


@pytest.mark.parametrize(
    ("constraint_type", "first", "second"),
    (
        (
            "SameStart",
            ITC2019TimeOption("10", 1, 2, "10"),
            ITC2019TimeOption("01", 2, 3, "01"),
        ),
        (
            "SameTime",
            ITC2019TimeOption("10", 0, 6, "10"),
            ITC2019TimeOption("01", 2, 2, "01"),
        ),
        (
            "DifferentTime",
            ITC2019TimeOption("10", 0, 4, "10"),
            ITC2019TimeOption("01", 2, 4, "01"),
        ),
        (
            "SameDays",
            ITC2019TimeOption("10", 0, 2, "10"),
            ITC2019TimeOption("11", 7, 2, "01"),
        ),
        (
            "DifferentDays",
            ITC2019TimeOption("10", 0, 2, "10"),
            ITC2019TimeOption("11", 7, 2, "01"),
        ),
        (
            "SameWeeks",
            ITC2019TimeOption("10", 0, 2, "10"),
            ITC2019TimeOption("01", 7, 2, "11"),
        ),
        (
            "DifferentWeeks",
            ITC2019TimeOption("10", 0, 2, "10"),
            ITC2019TimeOption("01", 7, 2, "11"),
        ),
        (
            "Overlap",
            ITC2019TimeOption("10", 0, 4, "11"),
            ITC2019TimeOption("11", 2, 4, "10"),
        ),
        (
            "NotOverlap",
            ITC2019TimeOption("10", 0, 4, "11"),
            ITC2019TimeOption("11", 2, 4, "10"),
        ),
        (
            "Precedence",
            ITC2019TimeOption("10", 0, 2, "01"),
            ITC2019TimeOption("01", 7, 2, "10"),
        ),
        (
            "WorkDay(4)",
            ITC2019TimeOption("10", 0, 2, "11"),
            ITC2019TimeOption("11", 5, 2, "10"),
        ),
        (
            "MinGap(3)",
            ITC2019TimeOption("10", 0, 2, "11"),
            ITC2019TimeOption("11", 4, 2, "10"),
        ),
    ),
)
def test_sparse_time_predicates_match_independent_evaluator_with_live_domains(
    constraint_type: str,
    first: ITC2019TimeOption,
    second: ITC2019TimeOption,
) -> None:
    def alternatives(selected: ITC2019TimeOption) -> tuple[ITC2019TimeOption, ...]:
        decoy_days = "01" if selected.days != "01" else "10"
        decoy_weeks = "01" if selected.weeks != "01" else "10"
        decoy_start = min(selected.start + 8, 17)
        return (
            selected,
            ITC2019TimeOption(
                decoy_days,
                decoy_start,
                min(selected.length, 20 - decoy_start),
                decoy_weeks,
                penalty=100,
            ),
        )

    classes = tuple(
        replace(
            _klass(
                class_id,
                days=selected.days,
                start=selected.start,
                length=selected.length,
                weeks=selected.weeks,
                room="R1",
                alternatives=alternatives(selected),
            ),
            room_required=False,
            room_options=(),
        )
        for class_id, selected in (("A", first), ("B", second))
    )
    problem = _problem(
        classes,
        distributions=(ITC2019Distribution(constraint_type, False, 2, ("A", "B")),),
    )

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        formulation="factorized",
    )
    cartesian = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        formulation="cartesian",
    )

    assert result.status == "OPTIMAL"
    assert cartesian.status == "OPTIMAL"
    assert result.objective is not None
    assert cartesian.objective is not None
    placements = {placement.class_id: placement for placement in result.placements}
    assert (placements["A"].days, placements["A"].start, placements["A"].weeks) == (
        first.days,
        first.start,
        first.weeks,
    )
    assert (placements["B"].days, placements["B"].start, placements["B"].weeks) == (
        second.days,
        second.start,
        second.weeks,
    )
    independent = evaluate_itc2019_distributions(problem, result.placements)[0]
    assert result.objective.distribution == independent.penalty
    assert result.objective.to_dict() == cartesian.objective.to_dict()


@pytest.mark.parametrize("constraint_type", ("MaxBreaks(0,0)", "MaxBlock(3,0)"))
def test_sparse_group_encoding_matches_evaluator_on_every_tiny_assignment(
    constraint_type: str,
) -> None:
    candidates = (
        ITC2019TimeOption("10", 0, 2, "11"),
        ITC2019TimeOption("10", 2, 2, "11"),
        ITC2019TimeOption("10", 6, 2, "10"),
        ITC2019TimeOption("01", 1, 5, "01"),
    )
    for first_index, first in enumerate(candidates):
        for second_index, second in enumerate(candidates):
            classes = tuple(
                replace(
                    _klass(
                        class_id,
                        days=selected.days,
                        start=selected.start,
                        length=selected.length,
                        weeks=selected.weeks,
                        room="R1",
                        alternatives=tuple(
                            replace(
                                option,
                                penalty=(0 if index == selected_index else 100),
                            )
                            for index, option in enumerate(candidates)
                        ),
                    ),
                    room_required=False,
                    room_options=(),
                )
                for class_id, selected, selected_index in (
                    ("A", first, first_index),
                    ("B", second, second_index),
                )
            )
            problem = _problem(
                classes,
                distributions=(
                    ITC2019Distribution(
                        constraint_type,
                        False,
                        3,
                        ("A", "B"),
                    ),
                ),
            )
            expected_placements = (
                ITC2019ClassPlacement("A", first.days, first.start, first.weeks, None),
                ITC2019ClassPlacement(
                    "B", second.days, second.start, second.weeks, None
                ),
            )
            expected = evaluate_itc2019_distributions(
                problem,
                expected_placements,
            )[0]

            result = solve_itc2019_native(
                problem,
                time_limit_seconds=2.0,
                workers=1,
                formulation="factorized",
            )

            assert result.status == "OPTIMAL"
            assert result.objective is not None
            assert result.placements == expected_placements
            assert result.objective.distribution == expected.penalty


@pytest.mark.parametrize("constraint_type", ("MaxBreaks(0,0)", "MaxBlock(3,0)"))
def test_sparse_required_group_encoding_matches_every_tiny_assignment(
    constraint_type: str,
) -> None:
    candidates = (
        ITC2019TimeOption("10", 0, 2, "11"),
        ITC2019TimeOption("10", 2, 2, "11"),
        ITC2019TimeOption("10", 6, 2, "10"),
        ITC2019TimeOption("01", 1, 5, "01"),
    )
    for first in candidates:
        for second in candidates:
            classes = tuple(
                replace(
                    _klass(
                        class_id,
                        days=selected.days,
                        start=selected.start,
                        length=selected.length,
                        weeks=selected.weeks,
                        room="R1",
                        alternatives=(selected,),
                    ),
                    room_required=False,
                    room_options=(),
                )
                for class_id, selected in (("A", first), ("B", second))
            )
            problem = _problem(
                classes,
                distributions=(
                    ITC2019Distribution(
                        constraint_type,
                        True,
                        0,
                        ("A", "B"),
                    ),
                ),
            )
            placements = (
                ITC2019ClassPlacement("A", first.days, first.start, first.weeks, None),
                ITC2019ClassPlacement(
                    "B", second.days, second.start, second.weeks, None
                ),
            )
            violation_units = evaluate_itc2019_distributions(
                problem,
                placements,
            )[0].violation_units

            result = solve_itc2019_native(
                problem,
                time_limit_seconds=2.0,
                workers=1,
                formulation="factorized",
            )

            assert result.status == (
                "OPTIMAL" if violation_units == 0 else "INFEASIBLE"
            )


def test_large_joint_sectioning_estimate_uses_validated_exact_staging() -> None:
    classes = (
        _klass("A", days="10", start=0, length=2, weeks="11", room="R1"),
        _klass("B", days="10", start=3, length=2, weeks="11", room="R1"),
        _klass("C", days="10", start=6, length=2, weeks="11", room="R1"),
    )
    problem = _problem(
        classes,
        students=(ITC2019Student("S", ("course-A", "course-B", "course-C")),),
    )

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=5.0,
        workers=1,
        max_joint_student_conjunctions=1,
        formulation="factorized",
    )

    assert result.status == "FEASIBLE"
    assert result.sectioning_mode == "staged_exact_fixed_timetable"
    assert result.best_bound is None
    assert result.objective is not None
    assert result.student_classes == {"S": ("A", "B", "C")}
    assert not validate_itc2019_solution(
        problem,
        result.placements,
        result.student_classes,
    )


def test_native_solver_fails_closed_when_exact_group_table_exceeds_budget() -> None:
    options = (
        ITC2019TimeOption("10", 0, 2, "11"),
        ITC2019TimeOption("10", 2, 2, "11"),
    )
    first = _klass(
        "A", days="10", start=0, length=2, weeks="11", room="R1", alternatives=options
    )
    second = _klass(
        "B", days="10", start=0, length=2, weeks="11", room="R2", alternatives=options
    )
    problem = _problem(
        (first, second),
        distributions=(ITC2019Distribution("MaxBlock(4,0)", True, 0, ("A", "B")),),
    )

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        max_group_table_rows=1,
        formulation="cartesian",
    )

    assert result.status == "UNSUPPORTED_MODEL_SCALE"
    assert result.unsupported_reasons
    assert not result.placements
    assert result.requested_formulation == "cartesian"
    assert result.effective_formulation == "cartesian"
    assert result.formulation_selection_reason == "explicit_cartesian"


def test_factorized_estimate_and_builder_share_sparse_group_cell_guard() -> None:
    options = (
        ITC2019TimeOption("10", 0, 2, "11"),
        ITC2019TimeOption("10", 2, 2, "11"),
    )
    problem = _problem(
        (
            _klass(
                "A",
                days="10",
                start=0,
                length=2,
                weeks="11",
                room="R1",
                alternatives=options,
            ),
            _klass(
                "B",
                days="10",
                start=0,
                length=2,
                weeks="11",
                room="R2",
                alternatives=options,
            ),
        ),
        distributions=(ITC2019Distribution("MaxBlock(4,0)", True, 0, ("A", "B")),),
    )
    rejected = estimate_itc2019_factorized_scale(
        problem,
        max_group_table_rows=1,
    )
    accepted = estimate_itc2019_factorized_scale(
        problem,
        max_group_table_rows=200,
    )

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        max_group_table_rows=accepted.maximum_group_table_rows,
        formulation="factorized",
    )

    assert not rejected.admitted
    assert rejected.maximum_group_table_rows > 1
    assert accepted.admitted
    assert result.status == "OPTIMAL"


def test_factorized_deadline_covers_sparse_predicate_estimation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _klass("A", days="10", start=0, length=2, weeks="11", room="R1")
    second = _klass("B", days="10", start=3, length=2, weeks="11", room="R2")
    problem = _problem(
        (first, second),
        distributions=(ITC2019Distribution("NotOverlap", True, 0, ("A", "B")),),
    )
    import benchmarks.itc2019_factorized as factorized

    original = factorized._sparse_time_predicate_cells

    def expired(*args: object, **kwargs: object) -> int:
        deadline = kwargs.get("deadline")
        assert isinstance(deadline, float)
        kwargs["deadline"] = 0.0
        return original(*args, **kwargs)

    monkeypatch.setattr(factorized, "_sparse_time_predicate_cells", expired)

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        formulation="factorized",
    )

    assert result.status == "DEADLINE_EXCEEDED"
    assert not result.placements


def test_native_solver_deadline_includes_model_construction() -> None:
    problem, _placements = _scoring_fixture()

    result = solve_itc2019_native(problem, time_limit_seconds=0.000_001)

    assert result.status == "DEADLINE_EXCEEDED"
    assert not result.placements
    assert result.solver_wall_time_seconds == 0.0
    assert result.effective_formulation == "not_started"
    assert result.formulation == "not_started"
    assert result.sectioning_mode == "not_started"


@pytest.mark.parametrize(
    "constraint_type",
    ("AlmostOverlap", "WorkDay", "MaxBlock(5)", "MaxDays(-1)"),
)
def test_parser_rejects_unknown_or_malformed_distribution_semantics(
    tmp_path: Path,
    constraint_type: str,
) -> None:
    source = tmp_path / "unsupported.xml"
    source.write_text(
        f"""<problem name="bad" nrDays="1" slotsPerDay="5" nrWeeks="1">
        <rooms><room id="R" capacity="1"/></rooms>
        <courses><course id="C"><config id="G"><subpart id="S">
          <class id="A" limit="1"><room id="R"/><time days="1" start="0"
            length="1" weeks="1"/></class>
        </subpart></config></course></courses>
        <distributions><distribution type="{constraint_type}" required="true">
          <class id="A"/>
        </distribution></distributions>
        </problem>""",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"Unsupported ITC-2019 distribution type|expects [12] parameter",
    ):
        parse_itc2019_xml(source)


def test_native_solver_reports_unsupported_semantics_without_relaxing_them() -> None:
    klass = _klass("A", days="10", start=0, length=2, weeks="11", room="R1")
    problem = _problem(
        (klass,),
        distributions=(ITC2019Distribution("WorkDay", True, 0, ("A",)),),
    )

    result = solve_itc2019_native(problem, time_limit_seconds=1.0)

    assert result.status == "INVALID_PROBLEM"
    assert result.validation_errors == (
        "ITC-2019 distribution WorkDay expects 1 parameter(s), got 'WorkDay'",
    )
    assert not result.placements
    assert result.requested_formulation == "auto"
    assert result.effective_formulation == "not_started"
    assert result.formulation == "not_started"
    assert result.sectioning_mode == "not_started"
    assert result.formulation_selection_reason == "invalid_problem"


@pytest.mark.slow
def test_cached_lums_reference_solution_validates_and_scores_independently() -> None:
    root = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "external"
        / "itc2019-mpp-c33d15797686"
        / "raw"
        / "data"
    )
    problem_path = root / "input" / "ITC-2019" / "lums-sum17.xml"
    solution_path = root / "output" / "ITC-2019" / "solution-lums-sum17.xml"
    if not problem_path.is_file() or not solution_path.is_file():
        pytest.skip("pinned ITC-2019 XML cache is not present")

    problem = parse_itc2019_xml(problem_path)
    solution = parse_itc2019_solution(solution_path)

    assert not validate_itc2019_solution_document(problem, solution)
    assert score_itc2019_solution(
        problem,
        solution.placements,
        solution.student_classes,
    ).to_dict() == {
        "time": 0,
        "room": 17,
        "distribution": 0,
        "student": 0,
        "weighted_time": 0,
        "weighted_room": 17,
        "weighted_distribution": 0,
        "weighted_student": 0,
        "total": 17,
    }


@pytest.mark.slow
def test_pinned_corpus_distribution_vocabulary_is_fully_supported_when_cached() -> None:
    root = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "external"
        / "itc2019-mpp-c33d15797686"
        / "raw"
        / "data"
        / "input"
        / "ITC-2019"
    )
    paths = sorted(root.glob("*.xml"))
    if len(paths) != 36:
        pytest.skip("pinned ITC-2019 XML cache is not present")

    observed: set[str] = set()
    for path in paths:
        for _event, element in ElementTree.iterparse(path, events=("end",)):
            if element.tag.rsplit("}", 1)[-1] == "distribution":
                observed.add(element.attrib["type"].split("(", 1)[0])
            element.clear()

    assert observed == {
        "DifferentDays",
        "DifferentRoom",
        "DifferentTime",
        "DifferentWeeks",
        "MaxBlock",
        "MaxBreaks",
        "MaxDayLoad",
        "MaxDays",
        "MinGap",
        "NotOverlap",
        "Overlap",
        "Precedence",
        "SameAttendees",
        "SameDays",
        "SameRoom",
        "SameStart",
        "SameTime",
        "SameWeeks",
        "WorkDay",
    }


def test_decomposed_pair_only_constructor_returns_valid_complete_solution() -> None:
    alternatives = (
        ITC2019TimeOption(days="10", start=0, length=2, weeks="11"),
        ITC2019TimeOption(days="10", start=5, length=2, weeks="11"),
    )
    problem = _problem(
        (
            _klass(
                "A",
                days="10",
                start=0,
                length=2,
                weeks="11",
                room="R1",
                alternatives=alternatives,
            ),
            _klass(
                "B",
                days="10",
                start=0,
                length=2,
                weeks="11",
                room="R1",
                alternatives=alternatives,
            ),
        ),
        distributions=(
            ITC2019Distribution(
                type="NotOverlap",
                required=True,
                penalty=0,
                class_ids=("A", "B"),
            ),
        ),
    )

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        random_seed=17,
        formulation="decomposed",
    )

    assert result.is_feasible
    assert result.status == "FEASIBLE"
    assert result.requested_formulation == "decomposed"
    assert result.effective_formulation == "decomposed"
    assert not validate_itc2019_solution(problem, result.placements, {})


def test_decomposed_constructor_encodes_required_time_and_room_pair_semantics() -> None:
    alternatives = (
        ITC2019TimeOption(days="10", start=0, length=2, weeks="11"),
        ITC2019TimeOption(days="10", start=5, length=2, weeks="11"),
    )
    problem = _problem(
        (
            replace(
                _klass(
                    "A",
                    days="10",
                    start=0,
                    length=2,
                    weeks="11",
                    room="R1",
                    alternatives=alternatives,
                ),
                room_options=(
                    ITC2019RoomOption(room_id="R1", penalty=0),
                    ITC2019RoomOption(room_id="R2", penalty=1),
                ),
            ),
            replace(
                _klass(
                    "B",
                    days="10",
                    start=0,
                    length=2,
                    weeks="11",
                    room="R2",
                    alternatives=alternatives,
                ),
                room_options=(
                    ITC2019RoomOption(room_id="R1", penalty=1),
                    ITC2019RoomOption(room_id="R2", penalty=0),
                ),
            ),
        ),
        distributions=(
            ITC2019Distribution(
                type="SameTime",
                required=True,
                penalty=0,
                class_ids=("A", "B"),
            ),
            ITC2019Distribution(
                type="DifferentRoom",
                required=True,
                penalty=0,
                class_ids=("A", "B"),
            ),
        ),
    )

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        random_seed=17,
        formulation="decomposed",
    )

    assert result.is_feasible
    by_class = {placement.class_id: placement for placement in result.placements}
    assert by_class["A"].start == by_class["B"].start
    assert by_class["A"].room_id != by_class["B"].room_id
    assert not validate_itc2019_solution(problem, result.placements, {})


def test_decomposed_constructor_supports_required_group_semantics() -> None:
    problem = _problem(
        (
            _klass("A", days="10", start=0, length=2, weeks="11", room="R1"),
            _klass("B", days="10", start=0, length=2, weeks="11", room="R2"),
        ),
        distributions=(
            ITC2019Distribution(
                type="MaxDays(1)",
                required=True,
                penalty=0,
                class_ids=("A", "B"),
            ),
        ),
    )

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        random_seed=17,
        formulation="decomposed",
    )

    assert result.is_feasible
    assert not validate_itc2019_solution(problem, result.placements, {})


def test_decomposed_constructor_runs_exact_post_timetable_sectioning() -> None:
    problem = _problem(
        (_klass("A", days="10", start=0, length=2, weeks="11", room="R1"),),
        students=(ITC2019Student(id="S", course_ids=("course-A",)),),
    )

    result = solve_itc2019_native(
        problem,
        time_limit_seconds=3.0,
        workers=1,
        random_seed=17,
        formulation="decomposed",
    )

    assert result.is_feasible
    assert result.sectioning_mode == "post_timetable_exact"
    assert result.student_classes == {"S": ("A",)}
    assert not validate_itc2019_solution(
        problem, result.placements, result.student_classes
    )


def test_student_sectioning_retains_hard_feasible_assignment_when_objective_build_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import benchmarks.itc2019 as itc2019

    problem = _problem(
        (_klass("A", days="10", start=0, length=2, weeks="11", room="R1"),),
        students=(ITC2019Student(id="S", course_ids=("course-A",)),),
    )
    placements = (
        ITC2019ClassPlacement(
            class_id="A", days="10", start=0, weeks="11", room_id="R1"
        ),
    )
    monkeypatch.setattr(
        itc2019,
        "_eligible_student_class_pairs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()),
    )

    result = solve_itc2019_student_sectioning(
        problem,
        placements,
        time_limit_seconds=2.0,
        workers=1,
        random_seed=17,
    )

    assert result.is_feasible
    assert result.student_classes == {"S": ("A",)}
    assert result.student_conflicts is None


def test_student_sectioning_capacity_constructor_preserves_configuration_parents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import benchmarks.itc2019 as itc2019

    lecture_one = replace(
        _klass("L1", days="10", start=0, length=1, weeks="11", room="R1"),
        limit=1,
    )
    tutorial_one = replace(
        _klass("T1", days="10", start=2, length=1, weeks="11", room="R1"),
        limit=1,
        parent_id="L1",
    )
    lecture_two = replace(
        _klass("L2", days="10", start=4, length=1, weeks="11", room="R1"),
        limit=2,
    )
    tutorial_two_a = replace(
        _klass("T2A", days="10", start=6, length=1, weeks="11", room="R1"),
        limit=1,
        parent_id="L2",
    )
    tutorial_two_b = replace(
        _klass("T2B", days="10", start=8, length=1, weeks="11", room="R1"),
        limit=1,
        parent_id="L2",
    )
    course = ITC2019Course(
        id="C",
        configurations=(
            ITC2019Configuration(
                id="CFG1",
                subparts=(
                    ITC2019Subpart(id="L1-SP", classes=(lecture_one,)),
                    ITC2019Subpart(id="T1-SP", classes=(tutorial_one,)),
                ),
            ),
            ITC2019Configuration(
                id="CFG2",
                subparts=(
                    ITC2019Subpart(id="L2-SP", classes=(lecture_two,)),
                    ITC2019Subpart(
                        id="T2-SP", classes=(tutorial_two_a, tutorial_two_b)
                    ),
                ),
            ),
        ),
    )
    students = tuple(
        ITC2019Student(id=f"S{index}", course_ids=("C",)) for index in range(3)
    )
    all_classes = (
        lecture_one,
        tutorial_one,
        lecture_two,
        tutorial_two_a,
        tutorial_two_b,
    )
    problem = replace(_problem(all_classes), courses=(course,), students=students)
    placements = tuple(
        ITC2019ClassPlacement(
            class_id=klass.id,
            days=klass.time_options[0].days,
            start=klass.time_options[0].start,
            weeks=klass.time_options[0].weeks,
            room_id="R1",
        )
        for klass in all_classes
    )
    monkeypatch.setattr(itc2019, "ITC2019_SECTIONING_CP_ENROLLMENT_THRESHOLD", 0)
    monkeypatch.setattr(
        itc2019.cp_model,
        "CpModel",
        lambda: (_ for _ in ()).throw(AssertionError("CP model was materialized")),
    )

    result = solve_itc2019_student_sectioning(
        problem,
        placements,
        time_limit_seconds=2.0,
        workers=1,
        random_seed=17,
    )

    assert result.is_feasible
    assert not validate_itc2019_solution(problem, placements, result.student_classes)
    assert sum("L1" in classes for classes in result.student_classes.values()) == 1
    assert sum("L2" in classes for classes in result.student_classes.values()) == 2


def test_student_sectioning_feasibility_first_only_skips_soft_cp_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import benchmarks.itc2019 as itc2019

    problem = _problem(
        (_klass("A", days="10", start=0, length=2, weeks="11", room="R1"),),
        students=(ITC2019Student(id="S", course_ids=("course-A",)),),
    )
    problem_before = problem.to_dict()
    placements = (
        ITC2019ClassPlacement(
            class_id="A", days="10", start=0, weeks="11", room_id="R1"
        ),
    )
    monkeypatch.setattr(
        itc2019.cp_model,
        "CpModel",
        lambda: (_ for _ in ()).throw(AssertionError("soft CP model was materialized")),
    )

    result = solve_itc2019_student_sectioning(
        problem,
        placements,
        time_limit_seconds=2.0,
        workers=1,
        random_seed=17,
        feasibility_first_only=True,
    )

    assert result.is_feasible
    assert result.student_classes == {"S": ("A",)}
    assert result.student_conflicts is None
    assert problem.to_dict() == problem_before
    assert not validate_itc2019_solution(problem, placements, result.student_classes)


def test_student_sectioning_rejects_invalid_capacity_constructor_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import benchmarks.itc2019 as itc2019

    problem = _problem(
        (_klass("A", days="10", start=0, length=2, weeks="11", room="R1"),),
        students=(ITC2019Student(id="S", course_ids=("course-A",)),),
    )
    placements = (
        ITC2019ClassPlacement(
            class_id="A", days="10", start=0, weeks="11", room_id="R1"
        ),
    )
    monkeypatch.setattr(
        itc2019,
        "_capacity_first_student_sectioning",
        lambda *_args, **_kwargs: {"S": ()},
    )

    result = solve_itc2019_student_sectioning(
        problem,
        placements,
        time_limit_seconds=2.0,
        workers=1,
        random_seed=17,
    )

    assert result.is_feasible
    assert result.student_classes == {"S": ("A",)}
    assert not validate_itc2019_solution(problem, placements, result.student_classes)


def test_decomposed_student_path_uses_concrete_sectioning_for_quality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import benchmarks.itc2019_decomposed as decomposed
    import benchmarks.itc2019_decomposed_quality as quality

    alternatives = (
        ITC2019TimeOption(days="10", start=0, length=2, weeks="11", penalty=9),
        ITC2019TimeOption(days="10", start=4, length=2, weeks="11", penalty=0),
    )
    problem = _problem(
        (
            _klass(
                "A",
                days="10",
                start=0,
                length=2,
                weeks="11",
                room="R1",
                alternatives=alternatives,
            ),
        ),
        students=(ITC2019Student(id="S", course_ids=("course-A",)),),
    )
    initial = (
        ITC2019ClassPlacement(
            class_id="A", days="10", start=0, weeks="11", room_id="R1"
        ),
    )
    improved = (
        ITC2019ClassPlacement(
            class_id="A", days="10", start=4, weeks="11", room_id="R1"
        ),
    )
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        decomposed,
        "construct_itc2019_decomposed",
        lambda *_args, **_kwargs: initial,
    )

    def section(*_args: object, **kwargs: object) -> ITC2019SectioningResult:
        observed["sectioning_limit"] = kwargs["time_limit_seconds"]
        observed["feasibility_first_only"] = kwargs["feasibility_first_only"]
        return ITC2019SectioningResult(
            status="FEASIBLE",
            student_classes={"S": ("A",)},
            student_conflicts=0,
            weighted_objective=0,
            best_bound=None,
            wall_time_seconds=0.0,
        )

    def improve(
        _problem: ITC2019Problem,
        _placements: object,
        student_classes: object,
        **_kwargs: object,
    ) -> tuple[ITC2019ClassPlacement, ...]:
        observed["student_classes"] = student_classes
        return improved

    monkeypatch.setattr(decomposed, "solve_itc2019_student_sectioning", section)
    monkeypatch.setattr(quality, "improve_itc2019_decomposed", improve)

    result = decomposed.solve_itc2019_decomposed(
        problem,
        time_limit_seconds=20.0,
        workers=1,
        random_seed=17,
    )

    assert result.is_feasible
    assert result.placements == improved
    assert observed["student_classes"] == {"S": ("A",)}
    assert float(observed["sectioning_limit"]) <= 16.0
    assert observed["feasibility_first_only"] is True


def test_decomposed_quality_uses_bounded_checkpoint_slice(monkeypatch) -> None:
    from benchmarks import itc2019_decomposed as decomposed
    from benchmarks import itc2019_decomposed_quality as quality

    problem = _problem(
        (_klass("A", days="10", start=0, length=2, weeks="11", room="R1"),)
    )
    incumbent = (ITC2019ClassPlacement("A", "10", 0, "11", "R1"),)
    observed: dict[str, float] = {}
    monkeypatch.setattr(
        decomposed,
        "construct_itc2019_decomposed",
        lambda *_args, **_kwargs: incumbent,
    )
    monkeypatch.setattr(
        decomposed,
        "should_construct_itc2019_generalized_occurrences",
        lambda _problem: False,
    )
    monkeypatch.setattr(
        decomposed, "should_construct_itc2019_globally", lambda _problem: False
    )

    started = time.monotonic()

    def improve(*_args: object, **kwargs: object):
        observed["deadline"] = float(kwargs["deadline"])
        return incumbent

    monkeypatch.setattr(quality, "improve_itc2019_decomposed", improve)

    result = decomposed.solve_itc2019_decomposed(
        problem,
        time_limit_seconds=120.0,
        workers=1,
        random_seed=17,
    )

    assert result.is_feasible
    assert observed["deadline"] - started <= 45.5


def test_decomposed_quality_prices_realized_student_conflicts() -> None:
    from benchmarks.itc2019_decomposed_quality import improve_itc2019_decomposed

    second_times = (
        ITC2019TimeOption(days="10", start=0, length=2, weeks="11", penalty=0),
        ITC2019TimeOption(days="10", start=5, length=2, weeks="11", penalty=1),
    )
    problem = _problem(
        (
            _klass("A", days="10", start=0, length=2, weeks="11", room="R1"),
            _klass(
                "B",
                days="10",
                start=0,
                length=2,
                weeks="11",
                room="R2",
                alternatives=second_times,
            ),
        ),
        students=(ITC2019Student(id="S", course_ids=("course-A", "course-B")),),
    )
    placements = (
        ITC2019ClassPlacement(
            class_id="A", days="10", start=0, weeks="11", room_id="R1"
        ),
        ITC2019ClassPlacement(
            class_id="B", days="10", start=0, weeks="11", room_id="R2"
        ),
    )
    student_classes = {"S": ("A", "B")}

    improved = improve_itc2019_decomposed(
        problem,
        placements,
        student_classes,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
    )

    before = score_itc2019_solution(problem, placements, student_classes)
    after = score_itc2019_solution(problem, improved, student_classes)
    assert before.student == 1
    assert after.student == 0
    assert after.total < before.total


def test_decomposed_quality_preserves_required_group_semantics() -> None:
    from benchmarks.itc2019_decomposed_quality import improve_itc2019_decomposed

    second_times = (
        ITC2019TimeOption(days="10", start=4, length=2, weeks="11", penalty=5),
        ITC2019TimeOption(days="01", start=4, length=2, weeks="11", penalty=0),
    )
    problem = _problem(
        (
            _klass("A", days="10", start=0, length=2, weeks="11", room="R1"),
            _klass(
                "B",
                days="10",
                start=4,
                length=2,
                weeks="11",
                room="R2",
                alternatives=second_times,
            ),
        ),
        distributions=(
            ITC2019Distribution(
                type="MaxDays(1)", required=True, penalty=0, class_ids=("A", "B")
            ),
        ),
    )
    placements = (
        ITC2019ClassPlacement(
            class_id="A", days="10", start=0, weeks="11", room_id="R1"
        ),
        ITC2019ClassPlacement(
            class_id="B", days="10", start=4, weeks="11", room_id="R2"
        ),
    )

    improved = improve_itc2019_decomposed(
        problem,
        placements,
        {},
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
    )

    assert not validate_itc2019_solution(problem, improved, {})
    assert next(item for item in improved if item.class_id == "B").days == "10"


def test_decomposed_quality_preconditions_rooms_with_soft_room_rules() -> None:
    from benchmarks.itc2019_decomposed_quality import improve_itc2019_decomposed

    first = replace(
        _klass("A", days="10", start=0, length=2, weeks="11", room="R1"),
        room_options=(
            ITC2019RoomOption(room_id="R1", penalty=4),
            ITC2019RoomOption(room_id="R2", penalty=0),
        ),
    )
    second = replace(
        _klass("B", days="10", start=4, length=2, weeks="11", room="R2"),
        room_options=(
            ITC2019RoomOption(room_id="R1", penalty=0),
            ITC2019RoomOption(room_id="R2", penalty=4),
        ),
    )
    problem = _problem(
        (first, second),
        distributions=(
            ITC2019Distribution(
                type="SameRoom",
                required=False,
                penalty=10,
                class_ids=("A", "B"),
            ),
        ),
    )
    placements = (
        ITC2019ClassPlacement("A", "10", 0, "11", "R1"),
        ITC2019ClassPlacement("B", "10", 4, "11", "R2"),
    )
    diagnostics: dict[str, object] = {}

    improved = improve_itc2019_decomposed(
        problem,
        placements,
        {},
        deadline=time.monotonic() + 15.0,
        workers=1,
        random_seed=17,
        diagnostics=diagnostics,
    )

    before = score_itc2019_solution(problem, placements, {})
    after = score_itc2019_solution(problem, improved, {})
    assert after.total < before.total
    assert after.distribution == 0
    assert diagnostics["post_early_room_score"] == after.total


def test_decomposed_constructor_combines_reversed_pair_rules() -> None:
    from benchmarks.itc2019_decomposed import construct_itc2019_decomposed

    first_times = (
        ITC2019TimeOption(days="10", start=0, length=1, weeks="11", penalty=0),
        ITC2019TimeOption(days="10", start=4, length=1, weeks="11", penalty=1),
    )
    problem = _problem(
        (
            _klass(
                "A",
                days="10",
                start=0,
                length=1,
                weeks="11",
                room="R1",
                alternatives=first_times,
            ),
            _klass("B", days="10", start=2, length=1, weeks="11", room="R2"),
        ),
        distributions=(
            ITC2019Distribution(
                type="SameDays", required=True, penalty=0, class_ids=("A", "B")
            ),
            ITC2019Distribution(
                type="Precedence", required=True, penalty=0, class_ids=("B", "A")
            ),
        ),
    )

    placements = construct_itc2019_decomposed(
        problem,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
        joint_construction=True,
    )

    assert placements is not None
    assert not validate_itc2019_solution(problem, placements, {})
    assert next(item for item in placements if item.class_id == "A").start == 4


def test_decomposed_joint_repair_can_move_a_hard_time_feasible_seed() -> None:
    from benchmarks.itc2019_decomposed import construct_itc2019_decomposed

    shared_room = _klass("A", days="10", start=0, length=1, weeks="11", room="R1")
    movable = _klass(
        "B",
        days="10",
        start=0,
        length=1,
        weeks="11",
        room="R1",
        alternatives=(
            ITC2019TimeOption("10", 0, 1, "11", penalty=0),
            ITC2019TimeOption("10", 4, 1, "11", penalty=1),
        ),
    )
    # More than 200 classes selects the staged time seed used by the large
    # competition instances.  The roomless fillers do not constrain A or B.
    fillers = tuple(
        replace(
            _klass(
                f"roomless-{index}",
                days="01",
                start=8,
                length=1,
                weeks="11",
                room="R2",
            ),
            room_required=False,
            room_options=(),
        )
        for index in range(199)
    )
    problem = _problem((shared_room, movable, *fillers))
    diagnostics: dict[str, object] = {}

    placements = construct_itc2019_decomposed(
        problem,
        deadline=time.monotonic() + 12.0,
        workers=1,
        random_seed=17,
        joint_construction=True,
        objective_problem=replace(
            problem,
            students=(ITC2019Student("S", ("course-A",)),),
        ),
        diagnostics=diagnostics,
    )

    assert placements is not None
    assert diagnostics["time_min_conflicts_best"] == 0
    assert diagnostics["joint_min_conflicts_best"] == 0
    assert not validate_itc2019_solution(problem, placements, {})
    by_class = {placement.class_id: placement for placement in placements}
    assert by_class["A"].start != by_class["B"].start


def test_decomposed_room_hints_skip_deduplicated_constants() -> None:
    from ortools.sat.python import cp_model

    from benchmarks.itc2019_decomposed import _add_room_assignment_hint

    model = cp_model.CpModel()
    first = model.new_constant(0)
    second = model.new_constant(0)

    _add_room_assignment_hint(model, first, 0, (0,))
    _add_room_assignment_hint(model, second, 0, (0,))

    assert model.validate() == ""


def test_global_components_jointly_enforce_recurrence_rooms_and_travel() -> None:
    first = _klass("A", days="10", start=0, length=2, weeks="11", room="R1")
    second = replace(
        _klass(
            "B",
            days="10",
            start=2,
            length=1,
            weeks="11",
            room="R2",
        ),
        time_options=(
            ITC2019TimeOption("10", 2, 1, "11"),
            ITC2019TimeOption("10", 5, 1, "11"),
        ),
    )
    room_limited = replace(
        _klass(
            "C",
            days="10",
            start=0,
            length=1,
            weeks="11",
            room="R1",
        ),
        time_options=(
            ITC2019TimeOption("10", 0, 1, "11"),
            ITC2019TimeOption("10", 10, 1, "11"),
            ITC2019TimeOption("10", 12, 1, "11"),
        ),
    )
    day_end = _klass("D", days="10", start=18, length=2, weeks="11", room="R1")
    next_day = _klass("E", days="01", start=0, length=1, weeks="11", room="R2")
    problem = _problem(
        (first, second, room_limited, day_end, next_day),
        distributions=(
            ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),
            ITC2019Distribution("SameAttendees", True, 0, ("D", "E")),
        ),
    )
    problem = replace(
        problem,
        rooms=(
            replace(
                problem.rooms[0],
                unavailable=(ITC2019Unavailable("10", 10, 1, "11"),),
            ),
            problem.rooms[1],
        ),
    )

    diagnostics = {}
    placements = construct_itc2019_global_components(
        problem,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
        diagnostics=diagnostics,
    )

    assert placements is not None
    assert validate_itc2019_solution(problem, placements, {}) == []
    by_id = {placement.class_id: placement for placement in placements}
    assert by_id["B"].start == 5
    assert by_id["C"].start == 12
    assert diagnostics["validation_errors"] == ()


def test_global_components_union_overlapping_room_unavailability() -> None:
    klass = replace(
        _klass("A", days="10", start=0, length=2, weeks="11", room="R1"),
        time_options=(
            ITC2019TimeOption("10", 0, 2, "11"),
            ITC2019TimeOption("10", 10, 2, "11"),
        ),
    )
    problem = _problem((klass,))
    problem = replace(
        problem,
        rooms=(
            replace(
                problem.rooms[0],
                unavailable=(
                    ITC2019Unavailable("10", 0, 4, "11"),
                    ITC2019Unavailable("10", 2, 4, "11"),
                ),
            ),
            problem.rooms[1],
        ),
    )

    diagnostics = {}
    placements = construct_itc2019_global_components(
        problem,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
        diagnostics=diagnostics,
    )

    assert placements is not None
    assert validate_itc2019_solution(problem, placements, {}) == []
    assert placements[0].start == 10
    assert diagnostics["unavailable_rectangles"] == 2


def test_global_components_use_proven_recurring_rectangle_envelope() -> None:
    def recurring_problem(weeks: int) -> ITC2019Problem:
        classes = tuple(
            replace(
                _klass(
                    str(index),
                    days="10",
                    start=0,
                    length=1,
                    weeks="1" * weeks,
                    room="R1",
                )
            )
            for index in range(500)
        )
        return replace(_problem(classes), nr_weeks=weeks)

    assert should_construct_itc2019_globally(recurring_problem(20))
    assert not should_construct_itc2019_globally(recurring_problem(21))


def test_global_components_preserve_shifted_recurrence_precedence_and_travel() -> None:
    first = replace(
        _klass("A", days="10", start=0, length=2, weeks="110", room="R1"),
        time_options=(
            ITC2019TimeOption("10", 0, 2, "110"),
            ITC2019TimeOption("10", 10, 2, "011"),
        ),
    )
    second = replace(
        _klass("B", days="10", start=2, length=1, weeks="011", room="R2"),
        time_options=(
            ITC2019TimeOption("10", 2, 1, "011"),
            ITC2019TimeOption("10", 5, 1, "011"),
        ),
    )
    problem = replace(
        _problem(
            (first, second),
            distributions=(
                ITC2019Distribution("Precedence", True, 0, ("A", "B")),
                ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),
            ),
        ),
        nr_weeks=3,
    )

    placements = construct_itc2019_global_components(
        problem,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
    )

    assert placements is not None
    assert validate_itc2019_solution(problem, placements, {}) == []
    by_id = {placement.class_id: placement for placement in placements}
    assert by_id["A"].weeks == "110"
    assert by_id["B"].start == 5


def test_decomposed_global_route_writes_a_validator_clean_document(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    problem = _problem(
        (_klass("A", days="10", start=0, length=1, weeks="11", room="R1"),)
    )
    candidate = (
        ITC2019ClassPlacement("A", days="10", start=0, weeks="11", room_id="R1"),
    )
    invalid_quality_candidate = (
        ITC2019ClassPlacement("A", days="01", start=0, weeks="11", room_id="R1"),
    )
    quality_observed = {}
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.should_construct_itc2019_globally",
        lambda received: received is problem,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.construct_itc2019_global_components",
        lambda received, **_kwargs: candidate if received is problem else None,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.improve_itc2019_global_recurrence",
        lambda received, placements, _students, **kwargs: (
            quality_observed.update(
                {
                    "problem": received,
                    "placements": tuple(placements),
                    "deadline": kwargs["deadline"],
                }
            )
            or invalid_quality_candidate
        ),
    )

    result = solve_itc2019_decomposed(
        problem,
        time_limit_seconds=10.0,
        workers=1,
        random_seed=17,
    )
    output = write_itc2019_solution(
        problem,
        result.placements,
        result.student_classes,
        tmp_path / "global-route.xml",
        metadata={"formulation": result.formulation},
    )
    document = parse_itc2019_solution(output)

    assert result.is_feasible
    assert result.formulation == "global_recurring_component_v1"
    assert result.placements == candidate
    assert quality_observed["problem"] is problem
    assert quality_observed["placements"] == candidate
    assert quality_observed["deadline"] > time.monotonic()
    assert validate_itc2019_solution_document(problem, document) == []


def test_global_components_obey_expired_absolute_deadline() -> None:
    problem = _problem(
        (_klass("A", days="10", start=0, length=1, weeks="11", room="R1"),)
    )
    diagnostics = {}

    placements = construct_itc2019_global_components(
        problem,
        deadline=time.monotonic() - 0.001,
        workers=1,
        random_seed=17,
        diagnostics=diagnostics,
    )

    assert placements is None
    assert diagnostics["deadline_exhausted"] is True


def test_global_components_fail_closed_for_unsupported_hard_semantics() -> None:
    problem = _problem(
        (_klass("A", days="10", start=0, length=1, weeks="11", room="R1"),),
        distributions=(ITC2019Distribution("MaxDays(1)", True, 0, ("A",)),),
    )
    diagnostics = {}

    placements = construct_itc2019_global_components(
        problem,
        deadline=time.monotonic() + 2.0,
        workers=1,
        random_seed=17,
        diagnostics=diagnostics,
    )

    assert placements is None
    assert itc2019_global_component_admission_reason(problem) == (
        "global_component_required_distribution_not_supported:MaxDays"
    )
    assert diagnostics["admission_reason"] == (
        "global_component_required_distribution_not_supported:MaxDays"
    )
