from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from itertools import product
from pathlib import Path
import random
import time
from types import SimpleNamespace

import pytest

import benchmarks.itc2019_sparse_joint as sparse_joint
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
    ITC2019Travel,
    ITC2019Unavailable,
    _distribution_spec,
    _pair_distribution_satisfied,
    _special_distribution_units,
    parse_itc2019_solution,
    parse_itc2019_xml,
    validate_itc2019_solution,
    validate_itc2019_solution_document,
    write_itc2019_solution,
)
from benchmarks.itc2019_sparse_joint import (
    _max_breaks_violation_units,
    _pair_satisfied,
    _semantic_placement,
    construct_itc2019_sparse_joint,
    estimate_itc2019_sparse_joint_scale,
    itc2019_sparse_joint_admission_reason,
    should_construct_itc2019_sparse_joint,
)
from benchmarks.itc2019_decomposed import solve_itc2019_decomposed


def _klass(
    class_id: str,
    *,
    times: tuple[ITC2019TimeOption, ...],
    room_ids: tuple[str, ...] = ("R1",),
    room_required: bool = True,
) -> ITC2019Class:
    return ITC2019Class(
        id=class_id,
        limit=10,
        parent_id=None,
        room_required=room_required,
        time_options=times,
        room_options=tuple(ITC2019RoomOption(room_id) for room_id in room_ids),
    )


def _problem(
    classes: tuple[ITC2019Class, ...],
    *,
    rooms: tuple[ITC2019Room, ...] | None = None,
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
        name="sparse-joint-synthetic",
        nr_days=2,
        slots_per_day=12,
        nr_weeks=2,
        optimization=ITC2019OptimizationWeights(),
        rooms=rooms
        or (
            ITC2019Room("R1", 100, (), ()),
            ITC2019Room("R2", 100, (), ()),
        ),
        courses=courses,
        distributions=distributions,
        students=students,
        source_path="sparse-joint-synthetic.xml",
    )


def _time(
    days: str,
    start: int,
    length: int = 2,
    weeks: str = "11",
) -> ITC2019TimeOption:
    return ITC2019TimeOption(days, start, length, weeks)


def test_semantic_and_scale_admission_fail_closed_without_instance_routing() -> None:
    klass = _klass("A", times=(_time("10", 0), _time("01", 2)))
    problem = _problem((klass,))

    estimate = estimate_itc2019_sparse_joint_scale(problem)

    assert estimate.admitted
    assert estimate.placement_literals == 2
    assert should_construct_itc2019_sparse_joint(problem)
    assert (
        itc2019_sparse_joint_admission_reason(problem, max_placement_literals=1)
        == "sparse_joint_placement_literal_limit:2>1"
    )

    grouped = replace(
        problem,
        distributions=(ITC2019Distribution("MaxDays(1)", True, 0, ("A",)),),
    )
    assert (
        itc2019_sparse_joint_admission_reason(grouped)
        == "sparse_joint_required_distribution_not_supported:MaxDays"
    )

    with_students = replace(
        problem,
        students=(ITC2019Student("student-1", ("course-A",)),),
    )
    assert (
        itc2019_sparse_joint_admission_reason(with_students)
        == "sparse_joint_requires_timetable_only_problem"
    )


def test_sparse_joint_scale_estimate_does_not_materialize_placements(
    monkeypatch,
) -> None:
    klass = _klass("A", times=(_time("10", 0), _time("01", 2)))
    problem = _problem((klass,))
    monkeypatch.setattr(
        sparse_joint,
        "_LegalPlacement",
        lambda *_args, **_kwargs: pytest.fail(
            "scale-only admission must not materialize placement objects"
        ),
    )

    estimate = estimate_itc2019_sparse_joint_scale(problem)

    assert estimate.admitted
    assert estimate.placement_literals == 2


def test_roomless_and_unavailable_room_time_values_are_exact() -> None:
    rooms = (
        ITC2019Room(
            "R1",
            100,
            (),
            (ITC2019Unavailable("10", 0, 2, "11"),),
        ),
    )
    roomed = _klass("A", times=(_time("10", 0), _time("10", 4)))
    roomless = _klass(
        "B",
        times=(_time("10", 0),),
        room_ids=(),
        room_required=False,
    )
    problem = _problem((roomed, roomless), rooms=rooms)
    snapshot = problem.to_dict()
    diagnostics: dict[str, object] = {}

    placements = construct_itc2019_sparse_joint(
        problem,
        deadline=time.monotonic() + 3.0,
        workers=7,
        random_seed=17,
        diagnostics=diagnostics,
    )

    assert placements is not None
    by_class = {placement.class_id: placement for placement in placements}
    assert by_class["A"].start == 4
    assert by_class["A"].room_id == "R1"
    assert by_class["B"].room_id is None
    assert diagnostics["illegal_room_time_pairs_filtered"] == 1
    assert diagnostics["effective_workers"] == 1
    assert diagnostics["status"] == "FEASIBLE"
    assert problem.to_dict() == snapshot
    with pytest.raises(FrozenInstanceError):
        placements[0].start = 9  # type: ignore[misc]


def test_ordered_asymmetric_travel_is_preserved_when_support_rows_swap_sides() -> None:
    rooms = (
        ITC2019Room("R1", 100, (ITC2019Travel("R2", 3),), ()),
        ITC2019Room("R2", 100, (ITC2019Travel("R1", 1),), ()),
    )
    first = _klass("A", times=(_time("10", 0), _time("10", 2)))
    second = _klass("B", times=(_time("10", 5),), room_ids=("R2",))
    problem = _problem(
        (first, second),
        rooms=rooms,
        distributions=(ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),),
    )

    placements = construct_itc2019_sparse_joint(
        problem,
        deadline=time.monotonic() + 3.0,
        random_seed=17,
    )

    assert placements is not None
    assert {item.class_id: item for item in placements}["A"].start == 0
    assert validate_itc2019_solution(problem, placements, {}) == []


def test_compact_pair_arithmetic_matches_the_independent_official_predicate() -> None:
    typed_rules = (
        "SameStart",
        "SameTime",
        "DifferentTime",
        "SameDays",
        "DifferentDays",
        "SameWeeks",
        "DifferentWeeks",
        "SameRoom",
        "DifferentRoom",
        "Overlap",
        "NotOverlap",
        "SameAttendees",
        "Precedence",
        "WorkDay(6)",
        "MinGap(2)",
    )
    values = (
        (_time("10", 0, 2, "11"), "R1"),
        (_time("10", 3, 3, "10"), "R2"),
        (_time("01", 1, 2, "01"), None),
        (_time("11", 5, 2, "11"), "R1"),
    )
    travel = {("R1", "R2"): 3, ("R2", "R1"): 1}

    for constraint_type, (first_raw, second_raw) in product(
        typed_rules, product(values, repeat=2)
    ):
        base, parameters = _distribution_spec(constraint_type)
        first_time, first_room = first_raw
        second_time, second_room = second_raw
        compact_first = _semantic_placement(first_time, first_room, (0,))
        compact_second = _semantic_placement(second_time, second_room, (1,))
        official_first = ITC2019ClassPlacement(
            "A",
            first_time.days,
            first_time.start,
            first_time.weeks,
            first_room,
        )
        official_second = ITC2019ClassPlacement(
            "B",
            second_time.days,
            second_time.start,
            second_time.weeks,
            second_room,
        )

        assert _pair_satisfied(
            base,
            parameters,
            compact_first,
            compact_second,
            travel,
        ) == _pair_distribution_satisfied(
            base,
            parameters,
            official_first,
            first_time,
            official_second,
            second_time,
            travel,
        )


def test_max_breaks_arithmetic_matches_independent_validator_on_random_tuples() -> None:
    rng = random.Random(20260819)
    problem = _problem((_klass("seed", times=(_time("10", 0),)),))

    for _case in range(500):
        class_ids = tuple(f"C{index}" for index in range(rng.randint(1, 5)))
        resolved = {
            class_id: _time(
                rng.choice(("10", "01", "11")),
                rng.randrange(0, 10),
                rng.randrange(1, 4),
                rng.choice(("10", "01", "11")),
            )
            for class_id in class_ids
        }
        parameters = (rng.randrange(0, 4), rng.randrange(0, 4))

        assert _max_breaks_violation_units(
            problem,
            parameters,
            class_ids,
            resolved,
        ) == _special_distribution_units(
            problem,
            "MaxBreaks",
            parameters,
            class_ids,
            resolved,
        )


def test_max_breaks_table_selects_only_valid_time_tuples_and_fails_closed() -> None:
    first = _klass("A", times=(_time("10", 0),), room_ids=("R1",))
    second = _klass(
        "B",
        times=(_time("10", 2), _time("10", 5)),
        room_ids=("R2",),
    )
    distribution = ITC2019Distribution(
        "MaxBreaks(0,0)",
        True,
        0,
        ("A", "B"),
    )
    problem = _problem((first, second), distributions=(distribution,))
    diagnostics: dict[str, object] = {}

    placements = construct_itc2019_sparse_joint(
        problem,
        deadline=time.monotonic() + 3.0,
        diagnostics=diagnostics,
    )

    assert placements is not None
    assert {item.class_id: item for item in placements}["B"].start == 2
    assert diagnostics["required_group_relations"] == 1
    assert diagnostics["group_semantic_cells"] == 2
    assert diagnostics["group_semantic_evaluations"] == 2
    assert diagnostics["group_forbidden_rows"] == 1
    assert validate_itc2019_solution(problem, placements, {}) == []
    assert (
        itc2019_sparse_joint_admission_reason(
            problem,
            max_group_semantic_cells=1,
        )
        == "sparse_joint_group_semantic_cell_limit:2>1"
    )

    impossible = _problem(
        (
            first,
            _klass("B", times=(_time("10", 5),), room_ids=("R2",)),
        ),
        distributions=(distribution,),
    )
    impossible_diagnostics: dict[str, object] = {}
    assert (
        construct_itc2019_sparse_joint(
            impossible,
            deadline=time.monotonic() + 3.0,
            diagnostics=impossible_diagnostics,
        )
        is None
    )
    assert impossible_diagnostics["solver_status"] == "INFEASIBLE"


def test_expired_deadline_and_model_invalidity_never_expose_partial_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _problem((_klass("A", times=(_time("10", 0),)),))
    snapshot = problem.to_dict()
    diagnostics: dict[str, object] = {}

    assert (
        construct_itc2019_sparse_joint(
            problem,
            deadline=time.monotonic() - 1.0,
            diagnostics=diagnostics,
        )
        is None
    )
    assert diagnostics["status"] == "DEADLINE_EXCEEDED"
    assert problem.to_dict() == snapshot

    monkeypatch.setattr(
        "benchmarks.itc2019_sparse_joint.cp_model.CpModel.validate",
        lambda _model: "forced model error",
    )
    diagnostics = {}
    assert (
        construct_itc2019_sparse_joint(
            problem,
            deadline=time.monotonic() + 3.0,
            diagnostics=diagnostics,
        )
        is None
    )
    assert diagnostics["status"] == "MODEL_INVALID"
    assert diagnostics["model_validation_error"] == "forced model error"


def test_late_solver_result_is_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _problem((_klass("A", times=(_time("10", 0),)),))
    actual_monotonic = time.monotonic
    deadline = actual_monotonic() + 3.0
    solver_returned = False
    original_solve = __import__(
        "benchmarks.itc2019_sparse_joint", fromlist=["cp_model"]
    ).cp_model.CpSolver.solve

    def solve_then_expire(solver, model):
        nonlocal solver_returned
        status = original_solve(solver, model)
        solver_returned = True
        return status

    def controlled_monotonic() -> float:
        return deadline + 1.0 if solver_returned else actual_monotonic()

    monkeypatch.setattr(
        "benchmarks.itc2019_sparse_joint.cp_model.CpSolver.solve",
        solve_then_expire,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_sparse_joint.time.monotonic",
        controlled_monotonic,
    )
    diagnostics: dict[str, object] = {}

    placements = construct_itc2019_sparse_joint(
        problem,
        deadline=deadline,
        diagnostics=diagnostics,
    )

    assert placements is None
    assert diagnostics["status"] == "DEADLINE_EXCEEDED"
    assert diagnostics["stage"] == "search"


def test_complete_sparse_route_serializes_to_a_document_valid_solution(
    tmp_path,
) -> None:
    first = _klass("A", times=(_time("10", 0), _time("01", 0)))
    second = _klass("B", times=(_time("10", 4),), room_ids=("R2",))
    problem = _problem(
        (first, second),
        distributions=(ITC2019Distribution("DifferentDays", True, 0, ("A", "B")),),
    )

    placements = construct_itc2019_sparse_joint(
        problem,
        deadline=time.monotonic() + 3.0,
        random_seed=17,
    )

    assert placements is not None
    destination = write_itc2019_solution(
        problem, placements, {}, tmp_path / "solution.xml"
    )
    reparsed = parse_itc2019_solution(destination)
    assert validate_itc2019_solution_document(problem, reparsed) == []


@pytest.mark.slow
def test_corrected_organizer_pu_d5_scale_is_admitted_when_cached() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "external"
        / "itc2019-mpp-c33d15797686"
        / "raw"
        / "data"
        / "input"
        / "ITC-2019"
        / "pu-d5-spr17.xml"
    )
    if not source.is_file():
        pytest.skip("cached corrected organizer PU-D5 instance is not present")
    parsed = parse_itc2019_xml(source)
    by_id = {klass.id: klass for klass in parsed.classes}
    if tuple(by_id[class_id].limit for class_id in ("995", "996", "997")) != (
        46,
        46,
        46,
    ):
        pytest.skip("cached PU-D5 is the withdrawn capacity-infeasible revision")

    problem = replace(parsed, students=())
    estimate = estimate_itc2019_sparse_joint_scale(problem)

    assert estimate.admitted
    assert estimate.placement_literals == 78_830
    assert estimate.required_group_relations == 15
    assert estimate.group_semantic_cells == 3_437
    assert should_construct_itc2019_sparse_joint(problem)


def test_decomposed_dispatch_uses_sparse_joint_after_established_routes_decline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _problem((_klass("A", times=(_time("10", 0),)),))
    expected = (ITC2019ClassPlacement("A", "10", 0, "11", "R1"),)

    for predicate in (
        "should_construct_itc2019_grouped_calendar",
        "should_construct_itc2019_generalized_occurrences",
        "should_construct_itc2019_globally",
        "should_construct_itc2019_resource_seed",
    ):
        monkeypatch.setattr(
            f"benchmarks.itc2019_decomposed.{predicate}", lambda _problem: False
        )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.estimate_itc2019_sparse_joint_scale",
        lambda _problem: SimpleNamespace(admitted=True, required_pair_relations=1_000),
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.construct_itc2019_sparse_joint",
        lambda _problem, **_kwargs: expected,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.construct_itc2019_decomposed",
        lambda *_args, **_kwargs: pytest.fail("legacy constructor must not run"),
    )

    result = solve_itc2019_decomposed(
        problem,
        time_limit_seconds=2.0,
        workers=1,
        random_seed=17,
    )

    assert result.status == "FEASIBLE"
    assert result.formulation == "sparse_joint_placement_sat_v1"
    assert result.placements == expected
