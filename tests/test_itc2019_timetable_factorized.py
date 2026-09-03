from __future__ import annotations

from dataclasses import replace
from itertools import product
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import Iterator, Sequence

import pytest
from ortools.sat.python import cp_model

import benchmarks.itc2019_timetable_factorized as timetable_factorized

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
    _travel_values,
    evaluate_itc2019_distributions,
    validate_itc2019_class_placements,
)
from benchmarks.itc2019_timetable_factorized import (
    ITC2019TimetableFactorizedLimits,
    SUPPORTED_REQUIRED_GROUP_DISTRIBUTIONS,
    SUPPORTED_REQUIRED_PAIR_DISTRIBUTIONS,
    build_itc2019_timetable_factorized,
    solve_itc2019_timetable_factorized,
)


PAIR_DISTRIBUTIONS = (
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
    "WorkDay(4)",
    "MinGap(1)",
)


class _CountingDistributions(Sequence[ITC2019Distribution]):
    def __init__(self, distribution: ITC2019Distribution, count: int) -> None:
        self.distribution = distribution
        self.count = count
        self.yielded = 0

    def __len__(self) -> int:
        return self.count

    def __getitem__(self, index: int) -> ITC2019Distribution:
        if index < 0:
            index += self.count
        if index < 0 or index >= self.count:
            raise IndexError(index)
        return self.distribution

    def __iter__(self) -> Iterator[ITC2019Distribution]:
        for _index in range(self.count):
            self.yielded += 1
            yield self.distribution


def _klass(
    class_id: str,
    *,
    times: tuple[ITC2019TimeOption, ...],
    rooms: tuple[str, ...] = ("R1", "R2"),
    room_required: bool = True,
) -> ITC2019Class:
    return ITC2019Class(
        id=class_id,
        limit=20,
        parent_id=None,
        room_required=room_required,
        time_options=times,
        room_options=tuple(ITC2019RoomOption(room_id) for room_id in rooms),
    )


def _problem(
    classes: tuple[ITC2019Class, ...],
    *,
    distributions: tuple[ITC2019Distribution, ...] = (),
    students: tuple[ITC2019Student, ...] = (),
    rooms: tuple[ITC2019Room, ...] | None = None,
) -> ITC2019Problem:
    courses = tuple(
        ITC2019Course(
            id=f"course-{klass.id}",
            configurations=(
                ITC2019Configuration(
                    id=f"config-{klass.id}",
                    subparts=(
                        ITC2019Subpart(
                            id=f"subpart-{klass.id}",
                            classes=(klass,),
                        ),
                    ),
                ),
            ),
        )
        for klass in classes
    )
    return ITC2019Problem(
        name="timetable-factorized-toy",
        nr_days=2,
        slots_per_day=8,
        nr_weeks=2,
        optimization=ITC2019OptimizationWeights(2, 3, 5, 7),
        rooms=rooms
        or (
            ITC2019Room(
                id="R1",
                capacity=100,
                travel=(ITC2019Travel("R2", 2),),
                unavailable=(),
            ),
            ITC2019Room(id="R2", capacity=100, travel=(), unavailable=()),
        ),
        courses=courses,
        distributions=distributions,
        students=students,
        source_path="synthetic-only.xml",
    )


def _pair_classes() -> tuple[ITC2019Class, ITC2019Class]:
    first_times = (
        ITC2019TimeOption("10", 0, 2, "10"),
        ITC2019TimeOption("01", 1, 2, "11"),
        ITC2019TimeOption("11", 4, 1, "01"),
    )
    second_times = (
        ITC2019TimeOption("10", 1, 2, "10"),
        ITC2019TimeOption("01", 4, 1, "11"),
        ITC2019TimeOption("11", 0, 1, "01"),
    )
    return (
        _klass("A", times=first_times),
        _klass("B", times=second_times),
    )


def _same_attendees_problem(
    *,
    class_rooms: dict[str, tuple[str, ...] | None],
    travel: dict[tuple[str, str], int],
    distributions: tuple[ITC2019Distribution, ...],
) -> ITC2019Problem:
    starts = {"A": 0, "B": 3, "C": 6, "D": 9}
    classes = tuple(
        _klass(
            class_id,
            times=(ITC2019TimeOption("10", starts[class_id], 1, "10"),),
            rooms=rooms or (),
            room_required=rooms is not None,
        )
        for class_id, rooms in class_rooms.items()
    )
    room_ids = sorted(
        {
            room_id
            for rooms in class_rooms.values()
            if rooms is not None
            for room_id in rooms
        }
        | {room_id for pair in travel for room_id in pair}
    )
    rooms = tuple(
        ITC2019Room(
            id=room_id,
            capacity=100,
            travel=tuple(
                ITC2019Travel(destination, value)
                for (origin, destination), value in sorted(travel.items())
                if origin == room_id
            ),
            unavailable=(),
        )
        for room_id in room_ids
    )
    return _problem(classes, distributions=distributions, rooms=rooms)


class _ChoiceCollector(cp_model.CpSolverSolutionCallback):
    def __init__(self, result) -> None:
        super().__init__()
        self.result = result
        self.assignments: set[tuple[int, int, int, int]] = set()

    def on_solution_callback(self) -> None:
        self.assignments.add(
            (
                int(self.Value(self.result.time_choices["A"])),
                int(self.Value(self.result.room_choices["A"])),
                int(self.Value(self.result.time_choices["B"])),
                int(self.Value(self.result.room_choices["B"])),
            )
        )


def _observed_assignments(problem: ITC2019Problem) -> set[tuple[int, int, int, int]]:
    result = build_itc2019_timetable_factorized(problem, time_limit_seconds=5.0)
    assert result.status == "BUILT", result
    assert result.model is not None
    collector = _ChoiceCollector(result)
    solver = cp_model.CpSolver()
    solver.parameters.enumerate_all_solutions = True
    solver.parameters.num_search_workers = 1
    status = solver.Solve(result.model, collector)
    assert status in {cp_model.OPTIMAL, cp_model.INFEASIBLE}
    return collector.assignments


def _placement(
    class_id: str,
    time_option: ITC2019TimeOption,
    room_option: ITC2019RoomOption | None,
) -> ITC2019ClassPlacement:
    return ITC2019ClassPlacement(
        class_id=class_id,
        days=time_option.days,
        start=time_option.start,
        weeks=time_option.weeks,
        room_id=room_option.room_id if room_option is not None else None,
    )


def _expected_assignments(
    problem: ITC2019Problem,
) -> set[tuple[int, int, int, int]]:
    classes = {klass.id: klass for klass in problem.classes}
    first = classes["A"]
    second = classes["B"]
    first_rooms: tuple[ITC2019RoomOption | None, ...] = (
        first.room_options if first.room_required else (None,)
    )
    second_rooms: tuple[ITC2019RoomOption | None, ...] = (
        second.room_options if second.room_required else (None,)
    )
    travel = _travel_values(problem)
    accepted: set[tuple[int, int, int, int]] = set()
    for (
        first_time_index,
        first_room_index,
        second_time_index,
        second_room_index,
    ) in product(
        range(len(first.time_options)),
        range(len(first_rooms)),
        range(len(second.time_options)),
        range(len(second_rooms)),
    ):
        first_time = first.time_options[first_time_index]
        second_time = second.time_options[second_time_index]
        first_placement = _placement("A", first_time, first_rooms[first_room_index])
        second_placement = _placement("B", second_time, second_rooms[second_room_index])
        placements = (first_placement, second_placement)
        if validate_itc2019_class_placements(problem, placements):
            continue
        satisfies_all = True
        for distribution in problem.distributions:
            if not distribution.required:
                continue
            base, parameters = _distribution_spec(distribution.type)
            class_ids = tuple(dict.fromkeys(distribution.class_ids))
            by_id = {"A": first_placement, "B": second_placement}
            times = {"A": first_time, "B": second_time}
            for left_index in range(len(class_ids)):
                for right_index in range(left_index + 1, len(class_ids)):
                    left = class_ids[left_index]
                    right = class_ids[right_index]
                    if not _pair_distribution_satisfied(
                        base,
                        parameters,
                        by_id[left],
                        times[left],
                        by_id[right],
                        times[right],
                        travel,
                    ):
                        satisfies_all = False
                        break
                if not satisfies_all:
                    break
            if not satisfies_all:
                break
        if satisfies_all:
            accepted.add(
                (
                    first_time_index,
                    first_room_index,
                    second_time_index,
                    second_room_index,
                )
            )
    return accepted


def _expected_assignments_from_full_evaluator(
    problem: ITC2019Problem,
) -> set[tuple[int, int, int, int]]:
    classes = {klass.id: klass for klass in problem.classes}
    first = classes["A"]
    second = classes["B"]
    first_rooms: tuple[ITC2019RoomOption | None, ...] = (
        first.room_options if first.room_required else (None,)
    )
    second_rooms: tuple[ITC2019RoomOption | None, ...] = (
        second.room_options if second.room_required else (None,)
    )
    accepted: set[tuple[int, int, int, int]] = set()
    for indices in product(
        range(len(first.time_options)),
        range(len(first_rooms)),
        range(len(second.time_options)),
        range(len(second_rooms)),
    ):
        first_time_index, first_room_index, second_time_index, second_room_index = (
            indices
        )
        placements = (
            _placement(
                "A",
                first.time_options[first_time_index],
                first_rooms[first_room_index],
            ),
            _placement(
                "B",
                second.time_options[second_time_index],
                second_rooms[second_room_index],
            ),
        )
        if validate_itc2019_class_placements(problem, placements):
            continue
        scores = evaluate_itc2019_distributions(problem, placements)
        if not any(score.is_hard_violation for score in scores):
            accepted.add(indices)
    return accepted


@pytest.mark.parametrize("distribution_type", PAIR_DISTRIBUTIONS)
def test_required_pair_semantics_match_legacy_exhaustively(
    distribution_type: str,
) -> None:
    classes = _pair_classes()
    problem = _problem(
        classes,
        distributions=(ITC2019Distribution(distribution_type, True, 0, ("A", "B")),),
    )

    assert _observed_assignments(problem) == _expected_assignments(problem)


def test_supported_boundary_covers_every_official_pair_distribution() -> None:
    assert SUPPORTED_REQUIRED_PAIR_DISTRIBUTIONS == {
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
        "WorkDay",
        "MinGap",
    }
    assert SUPPORTED_REQUIRED_GROUP_DISTRIBUTIONS == {"MaxBreaks"}


def test_required_max_breaks_matches_authoritative_evaluator_exhaustively() -> None:
    classes = (
        _klass(
            "A",
            times=(
                ITC2019TimeOption("10", 0, 2, "10"),
                ITC2019TimeOption("10", 4, 1, "10"),
            ),
        ),
        _klass(
            "B",
            times=(
                ITC2019TimeOption("10", 2, 2, "10"),
                ITC2019TimeOption("10", 6, 1, "10"),
            ),
        ),
    )
    problem = _problem(
        classes,
        distributions=(ITC2019Distribution("MaxBreaks(0,0)", True, 0, ("A", "B")),),
    )

    assert _observed_assignments(problem) == _expected_assignments_from_full_evaluator(
        problem
    )


def test_precedence_preserves_reversed_distribution_order() -> None:
    problem = _problem(
        _pair_classes(),
        distributions=(ITC2019Distribution("Precedence", True, 0, ("B", "A")),),
    )

    assert _observed_assignments(problem) == _expected_assignments(problem)


def test_multiple_required_rules_intersect_without_semantic_loss() -> None:
    problem = _problem(
        _pair_classes(),
        distributions=(
            ITC2019Distribution("SameDays", True, 0, ("A", "B")),
            ITC2019Distribution("DifferentTime", True, 0, ("A", "B")),
            ITC2019Distribution("DifferentRoom", True, 0, ("B", "A")),
            ITC2019Distribution("MinGap(1)", True, 0, ("A", "B")),
        ),
    )

    assert _observed_assignments(problem) == _expected_assignments(problem)


@pytest.mark.parametrize(
    ("distribution_type", "first_required", "second_required"),
    (
        ("SameRoom", False, False),
        ("DifferentRoom", False, False),
        ("SameAttendees", False, False),
        ("SameRoom", False, True),
        ("DifferentRoom", False, True),
        ("SameAttendees", False, True),
    ),
)
def test_roomless_pair_semantics_match_legacy(
    distribution_type: str,
    first_required: bool,
    second_required: bool,
) -> None:
    first, second = _pair_classes()
    first = replace(
        first,
        room_required=first_required,
        room_options=first.room_options if first_required else (),
    )
    second = replace(
        second,
        room_required=second_required,
        room_options=second.room_options if second_required else (),
    )
    problem = _problem(
        (first, second),
        distributions=(ITC2019Distribution(distribution_type, True, 0, ("A", "B")),),
    )

    assert _observed_assignments(problem) == _expected_assignments(problem)


def test_room_unavailability_and_occupancy_match_resource_validator() -> None:
    classes = (
        _klass(
            "A",
            times=(
                ITC2019TimeOption("10", 0, 2, "10"),
                ITC2019TimeOption("10", 3, 1, "10"),
            ),
            rooms=("R1",),
        ),
        _klass(
            "B",
            times=(
                ITC2019TimeOption("10", 1, 2, "10"),
                ITC2019TimeOption("10", 4, 1, "10"),
            ),
            rooms=("R1",),
        ),
    )
    rooms = (
        ITC2019Room(
            id="R1",
            capacity=100,
            travel=(),
            unavailable=(ITC2019Unavailable("10", 0, 1, "10"),),
        ),
    )
    problem = _problem(classes, rooms=rooms)

    assert _observed_assignments(problem) == _expected_assignments(problem)
    assert _observed_assignments(problem) == {
        (1, 0, 0, 0),
        (1, 0, 1, 0),
    }


def test_duplicate_domains_are_canonicalized_to_lowest_penalty() -> None:
    duplicate_times = (
        ITC2019TimeOption("10", 0, 1, "10", penalty=8),
        ITC2019TimeOption("10", 0, 1, "10", penalty=2),
    )
    duplicate_rooms = (
        ITC2019RoomOption("R1", penalty=1),
        ITC2019RoomOption("R1", penalty=1),
    )
    klass = replace(
        _klass("A", times=duplicate_times, rooms=("R1",)),
        room_options=duplicate_rooms,
    )

    result = build_itc2019_timetable_factorized(_problem((klass,)))

    assert result.status == "BUILT"
    assert result.time_domains["A"] == (duplicate_times[1],)
    assert result.room_domains["A"] == (duplicate_rooms[0],)


def test_build_is_protobuf_deterministic_and_reports_structural_telemetry() -> None:
    problem = _problem(
        _pair_classes(),
        distributions=(
            ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),
            ITC2019Distribution("SameDays", True, 0, ("A", "B")),
        ),
    )

    first = build_itc2019_timetable_factorized(
        problem,
        include_proto_fingerprint=True,
    )
    second = build_itc2019_timetable_factorized(
        problem,
        include_proto_fingerprint=True,
    )

    assert first.status == second.status == "BUILT"
    assert first.model is not None and second.model is not None
    assert str(first.model.proto) == str(second.model.proto)
    assert (
        first.telemetry.deterministic_signature
        == second.telemetry.deterministic_signature
    )
    assert first.telemetry.model_proto_sha256
    assert first.telemetry.model_proto_bytes > 0
    assert first.telemetry.model_fingerprint_mode == "canonical_proto_text_v1"
    assert first.telemetry.required_pair_distributions == 2
    assert first.telemetry.required_pair_relations == 2
    assert first.telemetry.required_group_distributions == 0
    assert first.telemetry.required_group_cells == 0
    assert first.telemetry.source_soft_distributions_excluded == 0
    assert tuple(name for name, _seconds in first.telemetry.phase_wall_seconds) == (
        "admission",
        "domains",
        "choice_variables",
        "pair_distributions",
        "group_distributions",
        "room_resources",
        "finalize_proto",
    )


def test_student_records_do_not_change_the_timetable_model() -> None:
    problem = _problem(_pair_classes())
    with_students = replace(
        problem,
        students=(
            ITC2019Student("S1", ("course-A", "course-B")),
            ITC2019Student("S2", ("course-B",)),
        ),
    )

    empty = build_itc2019_timetable_factorized(problem)
    populated = build_itc2019_timetable_factorized(with_students)

    assert empty.model is not None and populated.model is not None
    assert str(empty.model.proto) == str(populated.model.proto)
    assert empty.telemetry.deterministic_signature == (
        populated.telemetry.deterministic_signature
    )
    assert empty.telemetry.source_student_records_excluded == 0
    assert populated.telemetry.source_student_records_excluded == 2


def test_soft_distributions_are_excluded_from_feasibility_with_telemetry() -> None:
    problem = _problem(_pair_classes())
    with_soft = replace(
        problem,
        distributions=(
            ITC2019Distribution("NotOverlap", False, 7, ("A", "B")),
            ITC2019Distribution("MaxDayLoad(1)", False, 11, ("A", "B")),
        ),
    )

    empty = build_itc2019_timetable_factorized(problem)
    excluded = build_itc2019_timetable_factorized(with_soft)

    assert empty.status == excluded.status == "BUILT"
    assert empty.model is not None and excluded.model is not None
    assert str(empty.model.proto) == str(excluded.model.proto)
    assert empty.telemetry.source_soft_distributions_excluded == 0
    assert excluded.telemetry.source_soft_distributions_excluded == 2


def test_unsupported_active_semantics_fail_closed_before_model_creation() -> None:
    distribution = ITC2019Distribution("MaxDays(1)", True, 0, ("A", "B"))
    result = build_itc2019_timetable_factorized(
        _problem(_pair_classes(), distributions=(distribution,))
    )

    assert result.status == "UNSUPPORTED_SEMANTICS"
    assert result.model is None
    assert result.unsupported_reasons
    assert result.telemetry.model_variables == 0


def test_scale_limits_fail_closed() -> None:
    result = build_itc2019_timetable_factorized(
        _problem(_pair_classes()),
        limits=ITC2019TimetableFactorizedLimits(
            max_domain_values=1,
            max_required_pair_relations=1,
            max_sparse_room_constraints=1,
        ),
    )

    assert result.status == "UNSUPPORTED_MODEL_SCALE"
    assert result.model is None
    assert result.unsupported_reasons == ("factorized domain values exceed 1",)


def test_admission_deadline_interrupts_a_large_distribution_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distribution = ITC2019Distribution("SameTime", True, 0, ("A", "B"))
    distributions = _CountingDistributions(distribution, 5_000)
    problem = replace(_problem(_pair_classes()), distributions=distributions)
    clock_ticks = 0

    def advancing_monotonic() -> float:
        nonlocal clock_ticks
        clock_ticks += 1
        return clock_ticks * 0.001

    monkeypatch.setattr(timetable_factorized.time, "monotonic", advancing_monotonic)

    result = build_itc2019_timetable_factorized(
        problem,
        time_limit_seconds=0.01,
    )

    assert result.status == "DEADLINE_EXCEEDED"
    assert result.model is None
    assert distributions.yielded < len(distributions)
    assert clock_ticks < 20


def test_distribution_sequence_is_not_rescanned_after_admission() -> None:
    distribution = ITC2019Distribution("MaxDayLoad(1)", False, 7, ("A", "B"))
    distributions = _CountingDistributions(distribution, 25)
    problem = replace(_problem(_pair_classes()), distributions=distributions)

    result = build_itc2019_timetable_factorized(problem)

    assert result.status == "BUILT"
    assert result.telemetry.source_soft_distributions_excluded == 25
    assert distributions.yielded == 50


def test_short_required_group_scan_checks_an_expired_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _problem(
        _pair_classes(),
        distributions=(ITC2019Distribution("MaxBreaks(0,0)", True, 0, ("A", "B")),),
    )
    admission = timetable_factorized._build_distribution_admission(
        problem,
        deadline=float("inf"),
    )
    domains = timetable_factorized._FactorizedDomains(
        times={klass.id: klass.time_options for klass in _pair_classes()},
        rooms={klass.id: tuple(klass.room_options) for klass in _pair_classes()},
    )
    monkeypatch.setattr(timetable_factorized.time, "monotonic", lambda: 1.0)

    with pytest.raises(TimeoutError, match="group admission timed out"):
        timetable_factorized._required_group_cell_count(
            problem,
            domains,
            admission.group_requests,
            maximum_cells=100,
            deadline=0.5,
        )


@pytest.mark.parametrize("time_limit", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_build_time_limits_are_rejected(time_limit: float) -> None:
    problem = _problem(_pair_classes())

    with pytest.raises(ValueError):
        build_itc2019_timetable_factorized(
            problem,
            time_limit_seconds=time_limit,
        )
    with pytest.raises(ValueError):
        solve_itc2019_timetable_factorized(
            problem,
            build_time_limit_seconds=time_limit,
            build_only=True,
        )


@pytest.mark.parametrize(
    "distribution_type",
    (
        f"MaxBreaks({1 << 63},0)",
        f"MaxBreaks(0,{1 << 63})",
    ),
)
def test_max_breaks_rejects_values_outside_int64_safe_bounds(
    distribution_type: str,
) -> None:
    problem = _problem(
        _pair_classes(),
        distributions=(ITC2019Distribution(distribution_type, True, 0, ("A", "B")),),
    )

    result = build_itc2019_timetable_factorized(problem)

    assert result.status == "INVALID_PROBLEM"
    assert result.model is None
    assert any("CP-SAT int64-safe bound" in error for error in result.validation_errors)


def test_required_pair_relation_limit_has_an_independent_regression() -> None:
    one_time = (ITC2019TimeOption("10", 0, 1, "10"),)
    classes = tuple(_klass(class_id, times=one_time) for class_id in ("A", "B", "C"))
    result = build_itc2019_timetable_factorized(
        _problem(
            classes,
            distributions=(ITC2019Distribution("SameTime", True, 0, ("A", "B", "C")),),
        ),
        limits=ITC2019TimetableFactorizedLimits(
            max_required_pair_relations=2,
        ),
    )

    assert result.status == "UNSUPPORTED_MODEL_SCALE"
    assert result.model is None
    assert result.telemetry.required_pair_relations == 3
    assert result.unsupported_reasons == ("required pair relations exceed 2",)


def test_required_group_cell_limit_has_an_independent_regression() -> None:
    problem = _problem(
        _pair_classes(),
        distributions=(ITC2019Distribution("MaxBreaks(0,0)", True, 0, ("A", "B")),),
    )

    result = build_itc2019_timetable_factorized(
        problem,
        limits=ITC2019TimetableFactorizedLimits(max_required_group_cells=1),
    )

    assert result.status == "UNSUPPORTED_MODEL_SCALE"
    assert result.model is None
    assert result.telemetry.required_group_distributions == 1
    assert result.telemetry.required_group_cells > 1
    assert result.unsupported_reasons == ("required group cells exceed 1",)


def test_sparse_room_pair_limit_has_an_independent_regression() -> None:
    one_time = (ITC2019TimeOption("10", 0, 1, "10"),)
    classes = tuple(_klass(class_id, times=one_time) for class_id in ("A", "B", "C"))
    result = build_itc2019_timetable_factorized(
        _problem(
            classes,
            distributions=(ITC2019Distribution("SameRoom", True, 0, ("A", "B", "C")),),
        ),
        limits=ITC2019TimetableFactorizedLimits(
            max_sparse_room_constraints=1,
        ),
    )

    assert result.status == "UNSUPPORTED_MODEL_SCALE"
    assert result.model is None
    assert result.telemetry.sparse_room_constraints == 1
    assert len(result.unsupported_reasons) == 1
    assert "SameRoom relation" in result.unsupported_reasons[0]
    assert "more than 1 sparse room constraints" in result.unsupported_reasons[0]


def test_domain_limit_rejects_before_retaining_oversized_domains() -> None:
    time_options = tuple(
        ITC2019TimeOption("10", start, 1, "10") for start in range(256)
    )
    problem = replace(
        _problem((_klass("A", times=time_options, rooms=("R1",)),)),
        slots_per_day=256,
    )

    result = build_itc2019_timetable_factorized(
        problem,
        limits=ITC2019TimetableFactorizedLimits(max_domain_values=8),
    )

    assert result.status == "UNSUPPORTED_MODEL_SCALE"
    assert result.model is None
    assert result.time_domains == {}
    assert result.room_domains == {}
    assert result.telemetry.time_domain_values == 0
    assert result.telemetry.room_domain_values == 0
    assert result.unsupported_reasons == ("factorized domain values exceed 8",)


def test_same_attendees_room_pair_expansion_is_bounded_before_model_creation() -> None:
    problem = _problem(
        _pair_classes(),
        distributions=(ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),),
    )
    result = build_itc2019_timetable_factorized(
        problem,
        limits=ITC2019TimetableFactorizedLimits(max_room_pair_evaluations=3),
    )

    assert result.status == "UNSUPPORTED_MODEL_SCALE"
    assert result.model is None
    assert result.telemetry.room_pair_evaluations == 4
    assert result.unsupported_reasons == (
        "SameAttendees room-pair evaluations exceed 3",
    )


def test_same_attendees_per_pair_work_cap_rejects_before_model_creation() -> None:
    problem = _problem(
        _pair_classes(),
        distributions=(ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),),
    )
    result = build_itc2019_timetable_factorized(
        problem,
        limits=ITC2019TimetableFactorizedLimits(
            max_room_pair_evaluations_per_pair=3,
        ),
    )

    assert result.status == "UNSUPPORTED_MODEL_SCALE"
    assert result.model is None
    assert result.telemetry.room_pair_evaluations == 4
    assert result.unsupported_reasons == (
        "SameAttendees room pair A/B evaluations exceed 3",
    )


def test_room_pair_preprocessing_checks_the_deadline_inside_the_cartesian_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rooms = tuple(ITC2019RoomOption(f"R{index}") for index in range(20))
    clock_ticks = 0

    def advancing_monotonic() -> float:
        nonlocal clock_ticks
        clock_ticks += 1
        return clock_ticks * 0.001

    monkeypatch.setattr(timetable_factorized.time, "monotonic", advancing_monotonic)

    with pytest.raises(TimeoutError, match="room-pair preprocessing timed out"):
        timetable_factorized._travel_exception_count(
            rooms,
            rooms,
            {},
            reverse=False,
            deadline=0.0015,
            max_evaluations=400,
        )

    assert clock_ticks == 2


def test_same_attendees_exact_sparse_count_is_preflighted_before_model_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _problem(
        _pair_classes(),
        distributions=(ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),),
    )

    def reject_model_creation() -> None:
        raise AssertionError("CP-SAT model was created before sparse preflight")

    monkeypatch.setattr(timetable_factorized.cp_model, "CpModel", reject_model_creation)
    result = build_itc2019_timetable_factorized(
        problem,
        limits=ITC2019TimetableFactorizedLimits(max_sparse_room_constraints=2),
    )

    assert result.status == "UNSUPPORTED_MODEL_SCALE"
    assert result.model is None
    assert result.telemetry.sparse_room_constraints == 3
    assert result.unsupported_reasons == (
        "SameAttendees exact sparse room constraints exceed 2",
    )


def test_reversed_same_attendees_duplicates_share_one_proven_equivalent_room_pair() -> (
    None
):
    single = _problem(
        _pair_classes(),
        distributions=(ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),),
    )
    duplicated = replace(
        single,
        distributions=(
            ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),
            ITC2019Distribution("SameAttendees", True, 0, ("B", "A")),
        ),
    )

    single_result = build_itc2019_timetable_factorized(single)
    duplicated_result = build_itc2019_timetable_factorized(duplicated)

    assert single_result.status == duplicated_result.status == "BUILT"
    assert duplicated_result.telemetry.required_pair_relations == 1
    assert single_result.telemetry.room_pair_evaluations == 4
    assert duplicated_result.telemetry.room_pair_evaluations == 4
    assert single_result.model is not None and duplicated_result.model is not None
    assert str(single_result.model.proto) == str(duplicated_result.model.proto)


def test_asymmetric_directed_travel_preserves_reversed_same_attendees_semantics() -> (
    None
):
    problem = _same_attendees_problem(
        class_rooms={"A": ("RA",), "B": ("RB",)},
        travel={("RA", "RB"): 1, ("RB", "RA"): 5},
        distributions=(
            ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),
            ITC2019Distribution("SameAttendees", True, 0, ("B", "A")),
        ),
    )

    result = solve_itc2019_timetable_factorized(
        problem,
        build_only=False,
        solve_time_limit_seconds=1.0,
    )

    assert result.telemetry.required_pair_relations == 2
    assert result.telemetry.room_pair_evaluations == 2
    assert result.status == "INFEASIBLE"
    assert result.placements == ()


def test_symmetric_directed_travel_safely_deduplicates_reversed_relations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _same_attendees_problem(
        class_rooms={"A": ("RA",), "B": ("RB",)},
        travel={("RA", "RB"): 4, ("RB", "RA"): 4},
        distributions=(
            ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),
            ITC2019Distribution("SameAttendees", True, 0, ("B", "A")),
        ),
    )

    def reject_model_creation() -> None:
        raise AssertionError("static workload estimator created a CP-SAT model")

    monkeypatch.setattr(timetable_factorized.cp_model, "CpModel", reject_model_creation)
    workload = timetable_factorized.estimate_itc2019_timetable_same_attendees_workload(
        problem
    )

    assert workload.prepared_ordered_relations == (("A", "B"),)
    assert workload.raw_ordered_relations == 2
    assert workload.exact_ordered_duplicates_removed == 0
    assert workload.reversed_equivalent_relations_removed == 1
    assert workload.equivalence_evaluations == 1
    assert workload.room_pair_evaluations == 1
    assert workload.rejection is None


@pytest.mark.parametrize(
    "travel",
    (
        {},
        {("RA", "RB"): 2},
        {("RB", "RA"): 2},
    ),
    ids=("default-zero", "forward-only-fallback", "reverse-only-fallback"),
)
def test_missing_and_default_travel_prove_reversed_order_equivalence(
    travel: dict[tuple[str, str], int],
) -> None:
    problem = _same_attendees_problem(
        class_rooms={"A": ("RA",), "B": ("RB",)},
        travel=travel,
        distributions=(
            ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),
            ITC2019Distribution("SameAttendees", True, 0, ("B", "A")),
        ),
    )

    workload = timetable_factorized.estimate_itc2019_timetable_same_attendees_workload(
        problem
    )

    assert workload.prepared_ordered_relations == (("A", "B"),)
    assert workload.reversed_equivalent_relations_removed == 1
    assert workload.room_pair_evaluations == 1


def test_overlapping_room_domains_preserve_reversed_relation_on_one_unequal_cell() -> (
    None
):
    problem = _same_attendees_problem(
        class_rooms={"A": ("R1", "R2"), "B": ("R2", "R3")},
        travel={("R1", "R3"): 1, ("R3", "R1"): 5},
        distributions=(
            ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),
            ITC2019Distribution("SameAttendees", True, 0, ("B", "A")),
        ),
    )

    workload = timetable_factorized.estimate_itc2019_timetable_same_attendees_workload(
        problem
    )

    assert workload.prepared_ordered_relations == (("A", "B"), ("B", "A"))
    assert workload.reversed_equivalent_relations_removed == 0
    assert workload.equivalence_evaluations == 3
    assert workload.room_pair_evaluations == 8
    assert workload.exact_sparse_constraints == 4


@pytest.mark.parametrize(
    "class_rooms, expected_evaluations",
    (
        ({"A": None, "B": None}, 1),
        ({"A": None, "B": ("R1", "R2")}, 2),
    ),
    ids=("both-roomless", "one-roomless"),
)
def test_roomless_domains_safely_deduplicate_reversed_relations(
    class_rooms: dict[str, tuple[str, ...] | None],
    expected_evaluations: int,
) -> None:
    problem = _same_attendees_problem(
        class_rooms=class_rooms,
        travel={("R1", "R2"): 1, ("R2", "R1"): 9},
        distributions=(
            ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),
            ITC2019Distribution("SameAttendees", True, 0, ("B", "A")),
        ),
    )

    workload = timetable_factorized.estimate_itc2019_timetable_same_attendees_workload(
        problem
    )

    assert workload.prepared_ordered_relations == (("A", "B"),)
    assert workload.reversed_equivalent_relations_removed == 1
    assert workload.room_pair_evaluations == expected_evaluations


def test_reversed_relation_is_not_deduplicated_when_equivalence_proof_exceeds_cap() -> (
    None
):
    problem = _same_attendees_problem(
        class_rooms={"A": ("R1", "R2"), "B": ("R1", "R2")},
        travel={},
        distributions=(
            ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),
            ITC2019Distribution("SameAttendees", True, 0, ("B", "A")),
        ),
    )

    workload = timetable_factorized.estimate_itc2019_timetable_same_attendees_workload(
        problem,
        limits=ITC2019TimetableFactorizedLimits(
            max_room_pair_evaluations_per_pair=3,
        ),
    )

    assert workload.prepared_ordered_relations == (("A", "B"), ("B", "A"))
    assert workload.reversed_equivalent_relations_removed == 0
    assert workload.equivalence_evaluations == 0
    assert workload.room_pair_evaluations == 8
    assert workload.rejection == "SameAttendees room pair A/B evaluations exceed 3"


def test_mixed_duplicate_groups_prepare_one_semantically_exact_relation_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _same_attendees_problem(
        class_rooms={"A": ("RA",), "B": ("RB",), "C": ("RC",)},
        travel={
            ("RA", "RB"): 1,
            ("RB", "RA"): 5,
            ("RA", "RC"): 3,
            ("RC", "RA"): 3,
        },
        distributions=(
            ITC2019Distribution("SameAttendees", True, 0, ("A", "B", "C")),
            ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),
            ITC2019Distribution("SameAttendees", True, 0, ("C", "B", "A")),
        ),
    )

    workload = timetable_factorized.estimate_itc2019_timetable_same_attendees_workload(
        problem
    )
    encoded_relations: list[tuple[str, str]] = []
    original_same_attendees = timetable_factorized._PairEncoder.same_attendees_violation

    def record_same_attendees(
        encoder: object,
        first_id: str,
        second_id: str,
        *,
        student_travel: bool = False,
    ) -> object:
        encoded_relations.append((first_id, second_id))
        return original_same_attendees(
            encoder,
            first_id,
            second_id,
            student_travel=student_travel,
        )

    monkeypatch.setattr(
        timetable_factorized._PairEncoder,
        "same_attendees_violation",
        record_same_attendees,
    )
    result = build_itc2019_timetable_factorized(problem)

    assert workload.prepared_ordered_relations == (
        ("A", "B"),
        ("A", "C"),
        ("B", "C"),
        ("B", "A"),
    )
    assert workload.raw_ordered_relations == 7
    assert workload.exact_ordered_duplicates_removed == 1
    assert workload.reversed_equivalent_relations_removed == 2
    assert workload.equivalence_evaluations == 3
    assert workload.room_pair_evaluations == 4
    assert result.status == "BUILT"
    assert tuple(encoded_relations) == workload.prepared_ordered_relations
    assert result.telemetry.required_pair_relations == 4
    assert result.telemetry.room_pair_evaluations == workload.room_pair_evaluations


def test_empty_class_domain_is_rejected_without_a_model() -> None:
    klass = _klass("A", times=(), rooms=("R1",))

    result = build_itc2019_timetable_factorized(_problem((klass,)))

    assert result.status == "INVALID_PROBLEM"
    assert result.model is None
    assert result.validation_errors == ("class A has no time options",)


def test_build_only_mode_never_invokes_the_solver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_solve(*_args, **_kwargs):
        raise AssertionError("build-only mode invoked CP-SAT search")

    monkeypatch.setattr(cp_model.CpSolver, "solve", reject_solve)
    result = solve_itc2019_timetable_factorized(
        _problem(_pair_classes()),
        build_only=True,
    )

    assert result.status == "BUILT"
    assert result.build_only
    assert result.solver_status == "NOT_RUN"
    assert result.placements == ()


def test_solver_returns_candidate_only_after_independent_validation() -> None:
    problem = _problem(
        _pair_classes(),
        distributions=(
            ITC2019Distribution("NotOverlap", True, 0, ("A", "B")),
            ITC2019Distribution("DifferentRoom", True, 0, ("A", "B")),
        ),
    )

    result = solve_itc2019_timetable_factorized(
        problem,
        build_only=False,
        build_time_limit_seconds=5.0,
        solve_time_limit_seconds=2.0,
        workers=1,
        random_seed=7,
    )

    assert result.status == "FEASIBLE"
    assert result.solver_status == "OPTIMAL"
    assert result.has_validated_candidate
    assert len(result.placements) == 2
    assert not validate_itc2019_class_placements(problem, result.placements)
    assert not any(
        score.is_hard_violation
        for score in evaluate_itc2019_distributions(problem, result.placements)
    )


def test_independent_validation_failure_suppresses_the_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        timetable_factorized,
        "_validated_timetable_candidate",
        lambda _problem, _placements: ("independent validator rejected candidate",),
    )

    result = solve_itc2019_timetable_factorized(
        _problem(_pair_classes()),
        build_only=False,
        build_time_limit_seconds=5.0,
        solve_time_limit_seconds=2.0,
        workers=1,
        random_seed=11,
    )

    assert result.status == "VALIDATION_FAILED"
    assert result.solver_status == "OPTIMAL"
    assert result.placements == ()
    assert not result.has_validated_candidate
    assert result.validation_errors == ("independent validator rejected candidate",)


def test_model_fingerprint_is_deterministic_across_python_hash_seeds() -> None:
    source = textwrap.dedent(
        """
        from benchmarks.itc2019 import (
            ITC2019Class, ITC2019Configuration, ITC2019Course,
            ITC2019Distribution, ITC2019OptimizationWeights, ITC2019Problem,
            ITC2019Room, ITC2019RoomOption, ITC2019Subpart, ITC2019TimeOption,
        )
        from benchmarks.itc2019_timetable_factorized import (
            build_itc2019_timetable_factorized,
        )

        def klass(class_id, starts):
            return ITC2019Class(
                id=class_id,
                limit=20,
                parent_id=None,
                room_required=True,
                time_options=tuple(
                    ITC2019TimeOption("10", start, 1, "10") for start in starts
                ),
                room_options=(ITC2019RoomOption("R1"), ITC2019RoomOption("R2")),
            )

        classes = (klass("A", (0, 2)), klass("B", (1, 3)))
        courses = tuple(
            ITC2019Course(
                id=f"course-{item.id}",
                configurations=(ITC2019Configuration(
                    id=f"config-{item.id}",
                    subparts=(ITC2019Subpart(
                        id=f"subpart-{item.id}", classes=(item,)
                    ),),
                ),),
            )
            for item in classes
        )
        problem = ITC2019Problem(
            name="cross-process-synthetic",
            nr_days=2,
            slots_per_day=8,
            nr_weeks=2,
            optimization=ITC2019OptimizationWeights(2, 3, 5, 7),
            rooms=(ITC2019Room("R1", 100, (), ()), ITC2019Room("R2", 100, (), ())),
            courses=courses,
            distributions=(ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),),
            students=(),
            source_path="synthetic-only.xml",
        )
        result = build_itc2019_timetable_factorized(
            problem, include_proto_fingerprint=True
        )
        assert result.status == "BUILT"
        print(result.telemetry.model_proto_sha256)
        print(result.telemetry.model_proto_bytes)
        """
    )
    outputs: list[str] = []
    project_root = Path(__file__).resolve().parents[1]
    for seed in ("1", "987654"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-B", "-c", source],
            cwd=project_root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        outputs.append(completed.stdout)

    assert outputs[0] == outputs[1]
    fingerprint, proto_size = outputs[0].splitlines()
    assert len(fingerprint) == 64
    assert int(proto_size) > 0


def test_infeasible_room_unavailability_returns_no_candidate() -> None:
    klass = _klass(
        "A",
        times=(ITC2019TimeOption("10", 0, 2, "10"),),
        rooms=("R1",),
    )
    rooms = (
        ITC2019Room(
            id="R1",
            capacity=100,
            travel=(),
            unavailable=(ITC2019Unavailable("10", 0, 2, "10"),),
        ),
    )

    result = solve_itc2019_timetable_factorized(
        _problem((klass,), rooms=rooms),
        build_only=False,
        solve_time_limit_seconds=1.0,
    )

    assert result.status == "INFEASIBLE"
    assert not result.has_validated_candidate
    assert result.placements == ()
