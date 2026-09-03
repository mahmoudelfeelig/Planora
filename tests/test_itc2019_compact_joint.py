from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
from itertools import product
from pathlib import Path
import time
from types import SimpleNamespace

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
    ITC2019Travel,
    ITC2019Unavailable,
    _distribution_spec,
    _pair_distribution_satisfied,
    parse_itc2019_solution,
    parse_itc2019_xml,
    validate_itc2019_solution,
    validate_itc2019_solution_document,
    write_itc2019_solution,
)
from benchmarks.itc2019_decomposed import solve_itc2019_decomposed
from benchmarks.itc2019_compact_joint import (
    _CompactTime,
    _time_pair_satisfied_without_room,
    construct_itc2019_compact_joint,
    estimate_itc2019_compact_joint_scale,
    itc2019_compact_joint_admission_reason,
    should_construct_itc2019_compact_joint,
)


def _time(
    days: str,
    start: int,
    length: int = 2,
    weeks: str = "11",
) -> ITC2019TimeOption:
    return ITC2019TimeOption(days, start, length, weeks)


def _compact_time(option: ITC2019TimeOption) -> _CompactTime:
    return _CompactTime(
        original_index=0,
        option=option,
        legal_rooms=(None,),
        day_mask=int(option.days, 2),
        week_mask=int(option.weeks, 2),
        first_day=option.days.index("1"),
        first_week=option.weeks.index("1"),
    )


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
        name="compact-joint-synthetic",
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
        source_path="compact-joint-synthetic.xml",
    )


def test_semantic_and_scale_admission_is_generic_and_fail_closed() -> None:
    problem = _problem((_klass("A", times=(_time("10", 0), _time("01", 2))),))

    estimate = estimate_itc2019_compact_joint_scale(problem)

    assert estimate.admitted
    assert estimate.placement_literals == 2
    assert estimate.admitted_time_values == 2
    assert should_construct_itc2019_compact_joint(problem)
    assert (
        itc2019_compact_joint_admission_reason(
            problem,
            max_placement_literals=1,
        )
        == "compact_joint_placement_literal_limit:2>1"
    )

    grouped = replace(
        problem,
        distributions=(ITC2019Distribution("MaxDays(1)", True, 0, ("A",)),),
    )
    assert (
        itc2019_compact_joint_admission_reason(grouped)
        == "compact_joint_required_distribution_not_supported:MaxDays"
    )
    with_students = replace(
        problem,
        students=(ITC2019Student("student-1", ("course-A",)),),
    )
    assert (
        itc2019_compact_joint_admission_reason(with_students)
        == "compact_joint_requires_timetable_only_problem"
    )


def test_time_aggregation_arithmetic_matches_independent_pair_predicate() -> None:
    typed_rules = (
        "SameStart",
        "SameTime",
        "DifferentTime",
        "SameDays",
        "DifferentDays",
        "SameWeeks",
        "DifferentWeeks",
        "Overlap",
        "NotOverlap",
        "SameAttendees",
        "Precedence",
        "WorkDay(6)",
        "MinGap(2)",
    )
    values = (
        _time("10", 0, 2, "11"),
        _time("10", 3, 3, "10"),
        _time("01", 1, 2, "01"),
        _time("11", 5, 2, "11"),
    )

    for constraint_type, (first_time, second_time) in product(
        typed_rules,
        product(values, repeat=2),
    ):
        base, parameters = _distribution_spec(constraint_type)
        first_placement = ITC2019ClassPlacement(
            "A", first_time.days, first_time.start, first_time.weeks, None
        )
        second_placement = ITC2019ClassPlacement(
            "B", second_time.days, second_time.start, second_time.weeks, None
        )
        assert _time_pair_satisfied_without_room(
            base,
            parameters,
            _compact_time(first_time),
            _compact_time(second_time),
        ) == _pair_distribution_satisfied(
            base,
            parameters,
            first_placement,
            first_time,
            second_placement,
            second_time,
            {},
        )


def test_roomless_unavailable_and_room_aggregate_relations_are_exact() -> None:
    rooms = (
        ITC2019Room(
            "R1",
            100,
            (),
            (ITC2019Unavailable("10", 0, 2, "11"),),
        ),
        ITC2019Room("R2", 100, (), ()),
    )
    roomed = _klass(
        "A",
        times=(_time("10", 0), _time("10", 4)),
        room_ids=("R1", "R2"),
    )
    fixed = _klass("B", times=(_time("10", 8),), room_ids=("R2",))
    roomless = _klass(
        "C",
        times=(_time("10", 0),),
        room_ids=(),
        room_required=False,
    )
    problem = _problem(
        (roomed, fixed, roomless),
        rooms=rooms,
        distributions=(ITC2019Distribution("SameRoom", True, 0, ("A", "B")),),
    )
    snapshot = problem.to_dict()
    diagnostics: dict[str, object] = {}

    placements = construct_itc2019_compact_joint(
        problem,
        deadline=time.monotonic() + 3.0,
        workers=7,
        random_seed=17,
        diagnostics=diagnostics,
    )

    assert placements is not None
    by_class = {placement.class_id: placement for placement in placements}
    assert by_class["A"].room_id == "R2"
    assert by_class["B"].room_id == "R2"
    assert by_class["C"].room_id is None
    assert diagnostics["illegal_room_time_pairs"] == 1
    assert diagnostics["effective_workers"] == 1
    assert diagnostics["status"] == "FEASIBLE"
    assert problem.to_dict() == snapshot
    with pytest.raises(FrozenInstanceError):
        placements[0].start = 9  # type: ignore[misc]

    different = replace(
        problem,
        distributions=(ITC2019Distribution("DifferentRoom", True, 0, ("A", "B")),),
    )
    different_placements = construct_itc2019_compact_joint(
        different,
        deadline=time.monotonic() + 3.0,
    )
    assert different_placements is not None
    different_by_class = {
        placement.class_id: placement for placement in different_placements
    }
    assert different_by_class["A"].room_id == "R1"
    assert different_by_class["B"].room_id == "R2"


def test_room_occurrence_cliques_prevent_overlap() -> None:
    first = _klass("A", times=(_time("10", 0), _time("10", 4)))
    second = _klass("B", times=(_time("10", 0),), room_ids=("R1",))
    problem = _problem((first, second))

    placements = construct_itc2019_compact_joint(
        problem,
        deadline=time.monotonic() + 3.0,
    )

    assert placements is not None
    assert {placement.class_id: placement for placement in placements}["A"].start == 4
    assert validate_itc2019_solution(problem, placements, {}) == []


def test_asymmetric_travel_uses_exact_joint_placement_conflicts() -> None:
    rooms = (
        ITC2019Room("R1", 100, (ITC2019Travel("R2", 3),), ()),
        ITC2019Room("R2", 100, (ITC2019Travel("R1", 1),), ()),
        ITC2019Room("R3", 100, (ITC2019Travel("R2", 3),), ()),
    )
    first = _klass(
        "A",
        times=(_time("10", 0), _time("10", 2)),
        room_ids=("R1", "R3"),
    )
    second = _klass("B", times=(_time("10", 5),), room_ids=("R2",))
    problem = _problem(
        (first, second),
        rooms=rooms,
        distributions=(ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),),
    )
    diagnostics: dict[str, object] = {}

    placements = construct_itc2019_compact_joint(
        problem,
        deadline=time.monotonic() + 3.0,
        diagnostics=diagnostics,
    )

    assert placements is not None
    assert {placement.class_id: placement for placement in placements}["A"].start == 0
    assert diagnostics["travel_joint_cells"] == 2
    assert diagnostics["travel_joint_conflicts"] == 2
    assert validate_itc2019_solution(problem, placements, {}) == []

    rejected: dict[str, object] = {}
    assert (
        construct_itc2019_compact_joint(
            problem,
            deadline=time.monotonic() + 3.0,
            diagnostics=rejected,
            max_travel_joint_cells=1,
        )
        is None
    )
    assert rejected["status"] == "UNSUPPORTED_MODEL_SCALE"
    assert rejected["failure_reason"] == "compact_joint_travel_cell_limit:2>1"


def test_expired_deadline_and_invalid_model_never_return_partial_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _problem((_klass("A", times=(_time("10", 0),)),))
    diagnostics: dict[str, object] = {}

    assert (
        construct_itc2019_compact_joint(
            problem,
            deadline=time.monotonic() - 1.0,
            diagnostics=diagnostics,
        )
        is None
    )
    assert diagnostics["status"] == "DEADLINE_EXCEEDED"

    monkeypatch.setattr(
        "benchmarks.itc2019_compact_joint.cp_model.CpModel.validate",
        lambda _model: "forced model error",
    )
    diagnostics = {}
    assert (
        construct_itc2019_compact_joint(
            problem,
            deadline=time.monotonic() + 3.0,
            diagnostics=diagnostics,
        )
        is None
    )
    assert diagnostics["status"] == "MODEL_INVALID"
    assert diagnostics["model_validation_error"] == "forced model error"


def test_complete_result_round_trips_as_document_valid_solution(tmp_path) -> None:
    first = _klass("A", times=(_time("10", 0), _time("01", 0)))
    second = _klass("B", times=(_time("10", 4),), room_ids=("R2",))
    problem = _problem(
        (first, second),
        distributions=(ITC2019Distribution("DifferentDays", True, 0, ("A", "B")),),
    )

    placements = construct_itc2019_compact_joint(
        problem,
        deadline=time.monotonic() + 3.0,
        random_seed=17,
    )

    assert placements is not None
    destination = write_itc2019_solution(
        problem,
        placements,
        {},
        tmp_path / "solution.xml",
    )
    reparsed = parse_itc2019_solution(destination)
    assert validate_itc2019_solution_document(problem, reparsed) == []


@pytest.mark.slow
def test_current_agh_ggis_scale_is_admitted_without_building_model() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "external"
        / "itc2019-mpp-c33d15797686"
        / "raw"
        / "data"
        / "input"
        / "ITC-2019"
        / "agh-ggis-spr17.xml"
    )
    if not source.is_file():
        pytest.skip("cached organizer AGH-GGIS instance is not present")
    input_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    if (
        input_sha256
        != "8b081a1ba0d649109e272718633d7da6c3705841ae7bbdbee51abcc27570ee5b"
    ):
        pytest.skip("cached organizer AGH-GGIS input differs from the proven revision")

    problem = replace(parse_itc2019_xml(source), students=())
    estimate = estimate_itc2019_compact_joint_scale(problem)

    assert estimate.admitted
    assert estimate.placement_literals == 287_098
    assert estimate.admitted_time_values == 41_419
    assert estimate.required_pair_relations == 22_369
    assert estimate.pair_time_cells == 13_313_976
    assert should_construct_itc2019_compact_joint(problem)


def test_decomposed_dispatch_uses_compact_joint_only_in_dense_large_regime(
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
        lambda _problem: SimpleNamespace(admitted=False, required_pair_relations=0),
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.estimate_itc2019_compact_joint_scale",
        lambda _problem: SimpleNamespace(
            admitted=True,
            placement_literals=250_000,
            required_pair_relations=1_000,
        ),
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_decomposed.construct_itc2019_compact_joint",
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
    assert result.formulation == "compact_joint_placement_sat_v1"
    assert result.placements == expected
