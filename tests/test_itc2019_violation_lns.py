from __future__ import annotations

import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

import benchmarks.itc2019_violation_lns as violation_lns
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
    score_itc2019_solution,
    validate_itc2019_solution,
)
from benchmarks.itc2019_decomposed import solve_itc2019_decomposed
from benchmarks.itc2019_violation_lns import (
    count_itc2019_student_pair_visits,
    ITC2019ViolationLNSResult,
    improve_itc2019_violation_rooted,
)


def _problem():
    rooms = tuple(ITC2019Room(f"R{index}", 30, (), ()) for index in range(3))
    classes = tuple(
        ITC2019Class(
            id=class_id,
            limit=20,
            parent_id=None,
            room_required=True,
            time_options=(
                ITC2019TimeOption("1", 0, 1, "1"),
                ITC2019TimeOption("1", 2, 1, "1"),
                ITC2019TimeOption("1", 4, 1, "1"),
            ),
            room_options=tuple(ITC2019RoomOption(room.id) for room in rooms),
        )
        for class_id in ("A", "B", "C")
    )
    courses = tuple(
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
    )
    return ITC2019Problem(
        name="violation-lns-toy",
        nr_days=1,
        slots_per_day=8,
        nr_weeks=1,
        optimization=ITC2019OptimizationWeights(),
        rooms=rooms,
        courses=courses,
        distributions=(),
        students=(ITC2019Student("S", tuple(course.id for course in courses)),),
        source_path="violation-lns-toy.xml",
    )


def _incumbent():
    return tuple(
        ITC2019ClassPlacement(class_id, "1", 0, "1", f"R{index}")
        for index, class_id in enumerate(("A", "B", "C"))
    )


def _group_problem(
    distribution_type: str,
    first_times: tuple[ITC2019TimeOption, ...],
    second_times: tuple[ITC2019TimeOption, ...],
    *,
    required: bool = False,
    with_student: bool = False,
    penalty: int = 10,
    slots_per_day: int = 8,
):
    rooms = tuple(ITC2019Room(f"G{index}", 30, (), ()) for index in range(2))
    classes = (
        ITC2019Class(
            id="A",
            limit=20,
            parent_id=None,
            room_required=True,
            time_options=first_times,
            room_options=(ITC2019RoomOption("G0"),),
        ),
        ITC2019Class(
            id="B",
            limit=20,
            parent_id=None,
            room_required=True,
            time_options=second_times,
            room_options=(ITC2019RoomOption("G1"),),
        ),
    )
    courses = tuple(
        ITC2019Course(
            f"group-course-{klass.id}",
            (
                ITC2019Configuration(
                    f"group-configuration-{klass.id}",
                    (ITC2019Subpart(f"group-subpart-{klass.id}", (klass,)),),
                ),
            ),
        )
        for klass in classes
    )
    problem = ITC2019Problem(
        name=f"violation-lns-{distribution_type}",
        nr_days=2,
        slots_per_day=slots_per_day,
        nr_weeks=1,
        optimization=ITC2019OptimizationWeights(),
        rooms=rooms,
        courses=courses,
        distributions=(
            ITC2019Distribution(
                distribution_type,
                required,
                0 if required else penalty,
                ("A", "B"),
            ),
        ),
        students=(
            (ITC2019Student("group-student", tuple(course.id for course in courses)),)
            if with_student
            else ()
        ),
        source_path=f"violation-lns-{distribution_type}.xml",
    )
    incumbent = (
        ITC2019ClassPlacement(
            "A", first_times[0].days, first_times[0].start, "1", "G0"
        ),
        ITC2019ClassPlacement(
            "B", second_times[0].days, second_times[0].start, "1", "G1"
        ),
    )
    students = {"group-student": ("A", "B")} if with_student else {}
    return problem, incumbent, students


def test_violation_rooted_lns_returns_valid_immutable_strict_improvement() -> None:
    problem = _problem()
    incumbent = _incumbent()
    student_classes = {"S": ("A", "B", "C")}
    before = score_itc2019_solution(problem, incumbent, student_classes)

    result = improve_itc2019_violation_rooted(
        problem,
        incumbent,
        student_classes,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
        max_attempts=3,
        max_accepted_passes=2,
    )

    assert incumbent == _incumbent()
    assert student_classes == {"S": ("A", "B", "C")}
    assert result.placements is not incumbent
    assert not validate_itc2019_solution(problem, result.placements, student_classes)
    assert result.objective.total < before.total
    assert result.accepted_passes >= 1
    assert all(
        evidence.candidate_total is not None
        and evidence.candidate_total < evidence.before_total
        for evidence in result.passes
        if evidence.accepted
    )


def test_violation_rooted_lns_fails_closed_without_headroom() -> None:
    problem = _problem()
    incumbent = _incumbent()
    student_classes = {"S": ("A", "B", "C")}

    result = improve_itc2019_violation_rooted(
        problem,
        incumbent,
        student_classes,
        deadline=time.monotonic() + 0.1,
        workers=1,
        random_seed=17,
    )

    assert result.placements == incumbent
    assert result.attempted_passes == 0
    assert result.stop_reason == "insufficient_headroom"


def test_student_pair_visit_counter_is_streaming_and_duplicate_safe() -> None:
    students = {
        "first": ("A", "B", "C", "A"),
        "second": ("D", "E", "F", "G"),
    }

    assert count_itc2019_student_pair_visits(students) == 9
    assert count_itc2019_student_pair_visits(students, stop_after=3) == 9


def test_student_pair_visit_counter_rejects_negative_stop_bound() -> None:
    with pytest.raises(ValueError, match="stop_after must be non-negative"):
        count_itc2019_student_pair_visits({}, stop_after=-1)


def test_violation_rooted_lns_rolls_back_candidate_rescored_after_deadline(
    monkeypatch,
) -> None:
    problem = _problem()
    incumbent = _incumbent()
    student_classes = {"S": ("A", "B", "C")}
    score_calls = 0

    def delayed_candidate_score(received_problem, placements, students):
        nonlocal score_calls
        score_calls += 1
        objective = score_itc2019_solution(
            received_problem,
            placements,
            students,
        )
        if score_calls == 2:
            time.sleep(1.1)
        return objective

    monkeypatch.setattr(
        "benchmarks.itc2019_violation_lns.score_itc2019_solution",
        delayed_candidate_score,
    )
    result = improve_itc2019_violation_rooted(
        problem,
        incumbent,
        student_classes,
        deadline=time.monotonic() + 1.0,
        workers=1,
        random_seed=17,
        max_attempts=1,
        max_accepted_passes=1,
        minimum_headroom_seconds=0.1,
    )

    assert score_calls >= 3
    assert result.placements == incumbent
    assert result.accepted_passes == 0
    assert all(not evidence.accepted for evidence in result.passes)


@pytest.mark.parametrize(
    ("distribution_type", "first_times", "second_times"),
    (
        (
            "MaxDays(1)",
            (ITC2019TimeOption("10", 0, 1, "1"),),
            (
                ITC2019TimeOption("01", 0, 1, "1"),
                ITC2019TimeOption("10", 2, 1, "1"),
            ),
        ),
        (
            "MaxDayLoad(1)",
            (ITC2019TimeOption("10", 0, 1, "1"),),
            (
                ITC2019TimeOption("10", 2, 1, "1"),
                ITC2019TimeOption("01", 0, 1, "1"),
            ),
        ),
        (
            "MaxBreaks(0,0)",
            (ITC2019TimeOption("10", 0, 1, "1"),),
            (
                ITC2019TimeOption("10", 3, 1, "1"),
                ITC2019TimeOption("10", 1, 1, "1"),
            ),
        ),
        (
            "MaxBlock(1,0)",
            (ITC2019TimeOption("10", 0, 1, "1"),),
            (
                ITC2019TimeOption("10", 1, 1, "1"),
                ITC2019TimeOption("10", 3, 1, "1"),
            ),
        ),
    ),
)
def test_violation_rooted_lns_optimizes_all_soft_group_types(
    distribution_type,
    first_times,
    second_times,
) -> None:
    problem, incumbent, students = _group_problem(
        distribution_type,
        first_times,
        second_times,
    )
    before = score_itc2019_solution(problem, incumbent, students)

    result = improve_itc2019_violation_rooted(
        problem,
        incumbent,
        students,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
        max_attempts=2,
        max_accepted_passes=1,
    )

    assert not result.validation_errors
    assert result.objective.total < before.total
    assert result.accepted_passes == 1
    assert any(evidence.group_tables >= 1 for evidence in result.passes)


def test_violation_rooted_lns_preserves_required_group_while_reducing_conflict() -> (
    None
):
    problem, incumbent, students = _group_problem(
        "MaxDays(1)",
        (
            ITC2019TimeOption("10", 0, 1, "1"),
            ITC2019TimeOption("01", 0, 1, "1"),
        ),
        (
            ITC2019TimeOption("10", 0, 1, "1"),
            ITC2019TimeOption("10", 2, 1, "1"),
            ITC2019TimeOption("01", 0, 1, "1"),
        ),
        required=True,
        with_student=True,
    )
    before = score_itc2019_solution(problem, incumbent, students)

    result = improve_itc2019_violation_rooted(
        problem,
        incumbent,
        students,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
        max_attempts=2,
        max_accepted_passes=1,
    )

    assert not validate_itc2019_solution(problem, result.placements, students)
    assert result.objective.total < before.total
    assert {placement.days for placement in result.placements} == {"10"}
    assert any(evidence.group_tables >= 1 for evidence in result.passes)


def test_violation_rooted_group_table_cap_preserves_valid_incumbent() -> None:
    times = (
        ITC2019TimeOption("10", 0, 1, "1"),
        ITC2019TimeOption("01", 0, 1, "1"),
    )
    problem, incumbent, students = _group_problem(
        "MaxDays(1)",
        times,
        tuple(reversed(times)),
    )

    result = improve_itc2019_violation_rooted(
        problem,
        incumbent,
        students,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
        max_attempts=2,
        # Two one-class time rows require four actual table cells once the
        # soft-cost column is included.  A row-count-only guard would admit it.
        max_group_table_cells=2,
    )

    assert result.placements == incumbent
    assert result.accepted_passes == 0
    assert not result.validation_errors
    assert result.stop_reason in {
        "group_table_build_failed_or_late",
        "attempt_limit",
    }


def test_group_pressure_keeps_improving_time_inside_candidate_cap() -> None:
    decoys = tuple(ITC2019TimeOption("01", start, 1, "1") for start in range(48))
    improving = ITC2019TimeOption("10", 2, 1, "1", penalty=1)
    problem, incumbent, students = _group_problem(
        "MaxDays(1)",
        (ITC2019TimeOption("10", 0, 1, "1"),),
        (*decoys, improving),
        penalty=1_000,
        slots_per_day=64,
    )
    before = score_itc2019_solution(problem, incumbent, students)

    result = improve_itc2019_violation_rooted(
        problem,
        incumbent,
        students,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
        max_attempts=2,
        max_accepted_passes=1,
    )

    assert result.objective.total < before.total
    assert (
        next(
            placement for placement in result.placements if placement.class_id == "B"
        ).days
        == "10"
    )


def test_duplicate_soft_pair_distributions_preserve_penalty_multiplicity() -> None:
    problem, incumbent, students = _group_problem(
        "NotOverlap",
        (ITC2019TimeOption("10", 0, 1, "1"),),
        (
            ITC2019TimeOption("10", 0, 1, "1"),
            ITC2019TimeOption("10", 2, 1, "1", penalty=15),
        ),
        penalty=10,
    )
    problem = replace(
        problem,
        optimization=ITC2019OptimizationWeights(
            time=4,
            room=1,
            distribution=5,
            student=5,
        ),
        distributions=problem.distributions * 2,
    )
    before = score_itc2019_solution(problem, incumbent, students)
    assert before.total == 100

    result = improve_itc2019_violation_rooted(
        problem,
        incumbent,
        students,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
        max_attempts=2,
        max_accepted_passes=1,
    )

    assert not result.validation_errors
    assert result.accepted_passes == 1
    assert result.objective.total == 60


def test_interaction_pressure_keeps_improving_unique_time_inside_candidate_cap() -> (
    None
):
    decoys = tuple(ITC2019TimeOption("1", start, 1, "1") for start in range(48))
    improving = ITC2019TimeOption("1", 49, 1, "1", penalty=1)
    problem, incumbent, students = _group_problem(
        "MaxDays(1)",
        (ITC2019TimeOption("1", 0, 49, "1"),),
        (*decoys, improving),
        with_student=True,
        penalty=0,
        slots_per_day=64,
    )
    before = score_itc2019_solution(problem, incumbent, students)
    assert before.total == 5

    result = improve_itc2019_violation_rooted(
        problem,
        incumbent,
        students,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
        max_attempts=2,
        max_accepted_passes=1,
    )

    assert not result.validation_errors
    assert result.accepted_passes == 1
    assert result.objective.total == 2
    assert (
        next(
            placement for placement in result.placements if placement.class_id == "B"
        ).start
        == 49
    )


def test_interaction_pricing_visits_outside_student_partner_once(monkeypatch) -> None:
    rooms = tuple(ITC2019Room(f"P{index}", 30, (), ()) for index in range(3))
    time_options = {
        "A": (
            ITC2019TimeOption("1", 0, 1, "1"),
            ITC2019TimeOption("1", 2, 1, "1"),
        ),
        "B": (ITC2019TimeOption("1", 0, 1, "1"),),
        "Q": (ITC2019TimeOption("1", 4, 1, "1"),),
    }
    classes = tuple(
        ITC2019Class(
            id=class_id,
            limit=20,
            parent_id=None,
            room_required=True,
            time_options=time_options[class_id],
            room_options=(ITC2019RoomOption(rooms[index].id),),
        )
        for index, class_id in enumerate(("A", "B", "Q"))
    )
    courses = tuple(
        ITC2019Course(
            f"pricing-course-{klass.id}",
            (
                ITC2019Configuration(
                    f"pricing-configuration-{klass.id}",
                    (ITC2019Subpart(f"pricing-subpart-{klass.id}", (klass,)),),
                ),
            ),
        )
        for klass in classes
    )
    problem = ITC2019Problem(
        name="violation-lns-single-pass-pricing",
        nr_days=1,
        slots_per_day=6,
        nr_weeks=1,
        optimization=ITC2019OptimizationWeights(),
        rooms=rooms,
        courses=courses,
        distributions=(),
        students=(
            ITC2019Student(
                "root-conflict",
                ("pricing-course-A", "pricing-course-B"),
            ),
            ITC2019Student(
                "outside-partner",
                ("pricing-course-A", "pricing-course-Q"),
            ),
        ),
        source_path="violation-lns-single-pass-pricing.xml",
    )
    incumbent = tuple(
        ITC2019ClassPlacement(
            class_id,
            "1",
            time_options[class_id][0].start,
            "1",
            rooms[index].id,
        )
        for index, class_id in enumerate(("A", "B", "Q"))
    )
    students = {"root-conflict": ("A", "B"), "outside-partner": ("A", "Q")}
    original = violation_lns._student_pair_conflicts
    calls = 0

    def count_student_pair_conflicts(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        violation_lns,
        "_student_pair_conflicts",
        count_student_pair_conflicts,
    )

    result = improve_itc2019_violation_rooted(
        problem,
        incumbent,
        students,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
        max_attempts=1,
        max_accepted_passes=1,
    )

    assert result.accepted_passes == 1
    assert calls == 9


@pytest.mark.parametrize("resource_route", (False, True))
@pytest.mark.parametrize("oversized_pair_visits", (False, True))
def test_student_routes_cap_broad_quality_then_call_rooted_tail(
    monkeypatch,
    resource_route,
    oversized_pair_visits,
) -> None:
    problem = _problem()
    incumbent = _incumbent()
    observed = {}

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
        lambda _problem: resource_route,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.construct_itc2019_resource_seed",
        lambda *_args, **_kwargs: incumbent,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.construct_itc2019_decomposed",
        lambda *_args, **_kwargs: incumbent,
    )

    def broad_quality(received_problem, placements, student_classes, **kwargs):
        observed["broad_started"] = time.monotonic()
        observed["broad_deadline"] = kwargs["deadline"]
        observed["broad_students"] = dict(student_classes)
        return tuple(placements)

    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed_quality.improve_itc2019_decomposed",
        broad_quality,
    )

    def rooted_quality(received_problem, placements, student_classes, **kwargs):
        observed["rooted_problem"] = received_problem
        observed["rooted_deadline"] = kwargs["deadline"]
        observed["rooted_max_attempts"] = kwargs["max_attempts"]
        observed["rooted_max_accepted_passes"] = kwargs["max_accepted_passes"]
        objective = score_itc2019_solution(
            received_problem, placements, student_classes
        )
        return ITC2019ViolationLNSResult(
            tuple(placements),
            objective,
            objective,
            0,
            0,
            (),
            (),
            "test_checkpoint",
        )

    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.improve_itc2019_violation_rooted",
        rooted_quality,
    )
    if oversized_pair_visits:
        monkeypatch.setattr(
            "benchmarks.itc2019_decomposed.count_itc2019_student_pair_visits",
            lambda *_args, **_kwargs: 200_001,
        )

    result = solve_itc2019_decomposed(
        problem,
        time_limit_seconds=60.0,
        workers=1,
        random_seed=17,
    )

    assert result.is_feasible
    assert result.formulation == (
        "resource_conflict_seed_v1"
        if resource_route
        else "decomposed_time_room_repair_v1"
    )
    assert observed["broad_students"] == result.student_classes
    assert observed["broad_deadline"] <= observed["broad_started"] + 45.1
    if oversized_pair_visits:
        assert "rooted_problem" not in observed
    else:
        assert observed["rooted_problem"] is problem
        assert observed["rooted_deadline"] > observed["broad_deadline"]
        assert observed["rooted_max_attempts"] == 24
        assert observed["rooted_max_accepted_passes"] == 6


def test_rooted_tail_compares_against_sectioned_objective_when_broad_is_skipped(
    monkeypatch,
) -> None:
    problem = _problem()
    incumbent = _incumbent()
    students = {"S": ("A", "B", "C")}
    improved = (
        ITC2019ClassPlacement("A", "1", 0, "1", "R0"),
        ITC2019ClassPlacement("B", "1", 2, "1", "R1"),
        ITC2019ClassPlacement("C", "1", 4, "1", "R2"),
    )
    assert score_itc2019_solution(problem, incumbent, students).total > 0
    improved_objective = score_itc2019_solution(problem, improved, students)
    assert improved_objective.total == 0

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
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.construct_itc2019_resource_seed",
        lambda *_args, **_kwargs: incumbent,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.solve_itc2019_student_sectioning",
        lambda *_args, **_kwargs: SimpleNamespace(
            is_feasible=True,
            status="FEASIBLE",
            student_classes=students,
            validation_errors=(),
        ),
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed_quality.improve_itc2019_decomposed",
        lambda *_args, **_kwargs: pytest.fail(
            "broad quality must be skipped below its eight-second headroom"
        ),
    )
    observed = {"rooted_called": False}

    def rooted_quality(received_problem, placements, student_classes, **_kwargs):
        observed["rooted_called"] = True
        initial = score_itc2019_solution(
            received_problem,
            placements,
            student_classes,
        )
        return ITC2019ViolationLNSResult(
            improved,
            initial,
            improved_objective,
            1,
            1,
            (),
            (),
            "test_improvement",
        )

    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.improve_itc2019_violation_rooted",
        rooted_quality,
    )

    result = solve_itc2019_decomposed(
        problem,
        time_limit_seconds=8.0,
        workers=1,
        random_seed=17,
    )

    assert observed["rooted_called"] is True
    assert result.placements == improved
    assert result.objective == improved_objective


@pytest.mark.parametrize(
    "candidate_kind",
    ("invalid", "valid_but_worse", "raises_unexpectedly"),
)
def test_rooted_tail_independently_gates_untrusted_result(
    monkeypatch,
    candidate_kind,
) -> None:
    problem = _problem()
    students = {"S": ("A", "B", "C")}
    zero_conflict = (
        ITC2019ClassPlacement("A", "1", 0, "1", "R0"),
        ITC2019ClassPlacement("B", "1", 2, "1", "R1"),
        ITC2019ClassPlacement("C", "1", 4, "1", "R2"),
    )
    conflicting = _incumbent()
    invalid = (
        ITC2019ClassPlacement("A", "1", 0, "1", "R0"),
        ITC2019ClassPlacement("B", "1", 0, "1", "R0"),
        ITC2019ClassPlacement("C", "1", 4, "1", "R2"),
    )
    if candidate_kind in {"invalid", "raises_unexpectedly"}:
        valid_incumbent = conflicting
        untrusted_candidate = invalid
    else:
        valid_incumbent = zero_conflict
        untrusted_candidate = conflicting
    incumbent_objective = score_itc2019_solution(
        problem,
        valid_incumbent,
        students,
    )
    fake_low_objective = score_itc2019_solution(problem, zero_conflict, students)
    assert fake_low_objective.total == 0

    for route in (
        "should_construct_itc2019_grouped_calendar",
        "should_construct_itc2019_generalized_occurrences",
        "should_construct_itc2019_globally",
    ):
        monkeypatch.setattr(
            f"benchmarks.itc2019_decomposed.{route}",
            lambda _problem: False,
        )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.should_construct_itc2019_resource_seed",
        lambda _problem: True,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.construct_itc2019_resource_seed",
        lambda *_args, **_kwargs: valid_incumbent,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.solve_itc2019_student_sectioning",
        lambda *_args, **_kwargs: SimpleNamespace(
            is_feasible=True,
            status="FEASIBLE",
            student_classes=students,
            validation_errors=(),
        ),
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed_quality.improve_itc2019_decomposed",
        lambda *_args, **_kwargs: pytest.fail(
            "broad quality must be skipped below its eight-second headroom"
        ),
    )
    if candidate_kind == "raises_unexpectedly":

        def rooted_tail(*_args, **_kwargs):
            raise RuntimeError("synthetic optional-tail failure")

    else:

        def rooted_tail(*_args, **_kwargs):
            return ITC2019ViolationLNSResult(
                untrusted_candidate,
                incumbent_objective,
                fake_low_objective,
                1,
                1,
                (),
                (),
                "untrusted_test_result",
            )

    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.improve_itc2019_violation_rooted",
        rooted_tail,
    )

    result = solve_itc2019_decomposed(
        problem,
        time_limit_seconds=8.0,
        workers=1,
        random_seed=17,
    )

    assert result.is_feasible
    assert result.placements == valid_incumbent
    assert result.objective == incumbent_objective
