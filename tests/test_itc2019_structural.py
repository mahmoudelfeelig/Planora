from __future__ import annotations

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
    ITC2019Subpart,
    ITC2019TimeOption,
    validate_itc2019_solution,
)
from benchmarks.itc2019_decomposed import construct_itc2019_decomposed
from benchmarks.itc2019_structural import (
    construct_itc2019_structural,
    itc2019_structural_admission_reason,
)


def _class(class_id: str, starts: tuple[int, ...]) -> ITC2019Class:
    return ITC2019Class(
        id=class_id,
        limit=10,
        parent_id=None,
        room_required=True,
        time_options=tuple(
            ITC2019TimeOption(
                days="10",
                start=start,
                length=4,
                weeks="11",
            )
            for start in starts
        ),
        room_options=(ITC2019RoomOption(room_id="R1"),),
    )


def _problem(
    classes: tuple[ITC2019Class, ...],
    distributions: tuple[ITC2019Distribution, ...] = (),
) -> ITC2019Problem:
    return ITC2019Problem(
        name="structural-toy",
        nr_days=2,
        slots_per_day=20,
        nr_weeks=2,
        optimization=ITC2019OptimizationWeights(),
        rooms=(
            ITC2019Room(
                id="R1",
                capacity=100,
                travel=(),
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
        distributions=distributions,
        students=(),
        source_path="structural-toy.xml",
    )


def test_structural_constructor_enforces_same_room_resource_nonoverlap():
    first = _class("A", (0,))
    second = _class("B", (0, 4))
    problem = _problem(
        (first, second),
        (
            ITC2019Distribution(
                type="SameRoom",
                required=True,
                penalty=0,
                class_ids=("A", "B"),
            ),
        ),
    )
    diagnostics = {}

    candidate = construct_itc2019_structural(
        problem,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
        time_hints={"A": first.time_options[0], "B": second.time_options[0]},
        diagnostics=diagnostics,
    )

    assert candidate is not None
    assert validate_itc2019_solution(problem, candidate, {}) == []
    by_class = {placement.class_id: placement for placement in candidate}
    assert by_class["A"].room_id == by_class["B"].room_id == "R1"
    assert by_class["B"].start == 4
    assert diagnostics["implied_same_room_nonoverlap"] == 1
    assert diagnostics["validation_error_count"] == 0
    assert diagnostics["finalization_headroom_seconds"] >= 1.0


def test_structural_constructor_enforces_fixed_room_resource_nonoverlap():
    first = _class("A", (0,))
    second = _class("B", (0, 4))
    problem = _problem((first, second))
    diagnostics = {}

    candidate = construct_itc2019_structural(
        problem,
        deadline=time.monotonic() + 5.0,
        workers=1,
        random_seed=17,
        time_hints={"A": first.time_options[0], "B": second.time_options[0]},
        diagnostics=diagnostics,
    )

    assert candidate is not None
    assert validate_itc2019_solution(problem, candidate, {}) == []
    by_class = {placement.class_id: placement for placement in candidate}
    assert by_class["B"].start == 4
    assert diagnostics["implied_fixed_room_nonoverlap"] == 1


def test_structural_admission_rejects_non_singleton_calendar_representation():
    klass = _class("A", (0,))
    invalid = ITC2019Class(
        id=klass.id,
        limit=klass.limit,
        parent_id=klass.parent_id,
        room_required=klass.room_required,
        time_options=(ITC2019TimeOption(days="11", start=0, length=4, weeks="11"),),
        room_options=klass.room_options,
    )

    assert (
        itc2019_structural_admission_reason(_problem((invalid,)))
        == "structural_non_singleton_day:A"
    )


def test_decomposed_uses_structural_constructor_only_through_admission(monkeypatch):
    first = _class("A", (0,))
    second = _class("B", (4,))
    problem = _problem((first, second))
    candidate = (
        ITC2019ClassPlacement(
            class_id="A", days="10", start=0, weeks="11", room_id="R1"
        ),
        ITC2019ClassPlacement(
            class_id="B", days="10", start=4, weeks="11", room_id="R1"
        ),
    )
    observed = {}

    def fake_constructor(received, **kwargs):
        observed["problem"] = received
        observed["deadline"] = kwargs["deadline"]
        return candidate

    monkeypatch.setattr(
        "benchmarks.itc2019_structural.should_construct_itc2019_structurally",
        lambda received: received is problem,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_structural.construct_itc2019_structural",
        fake_constructor,
    )

    result = construct_itc2019_decomposed(
        problem,
        deadline=time.monotonic() + 3.0,
        workers=1,
        random_seed=17,
        joint_construction=True,
    )

    assert result == candidate
    assert observed["problem"] is problem
    assert observed["deadline"] > time.monotonic()


def test_decomposed_structural_routing_fails_closed_without_legacy_fallback(
    monkeypatch,
):
    problem = _problem((_class("A", (0,)), _class("B", (4,))))
    diagnostics = {}

    monkeypatch.setattr(
        "benchmarks.itc2019_structural.should_construct_itc2019_structurally",
        lambda received: received is problem,
    )
    monkeypatch.setattr(
        "benchmarks.itc2019_structural.construct_itc2019_structural",
        lambda received, **kwargs: None,
    )

    result = construct_itc2019_decomposed(
        problem,
        deadline=time.monotonic() + 3.0,
        workers=1,
        random_seed=17,
        joint_construction=True,
        diagnostics=diagnostics,
    )

    assert result is None
    assert diagnostics["structural_failed_closed"] is True
    assert "time_min_conflicts_best" not in diagnostics
