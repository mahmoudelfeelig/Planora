from __future__ import annotations

import time

import pytest

import benchmarks.itc2019_room_oracle as room_oracle
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
    ITC2019Travel,
)
from benchmarks.itc2019_preprocessing import (
    ITC2019CheckpointTime,
    ITC2019PartialCheckpoint,
    prepare_itc2019_context,
)
from benchmarks.itc2019_room_oracle import (
    ITC2019RoomOracleLimits,
    maximal_half_open_interval_cliques,
    solve_itc2019_room_oracle,
)


def _time(
    start: int,
    *,
    days: str = "1",
    length: int = 2,
    weeks: str = "1",
) -> ITC2019TimeOption:
    return ITC2019TimeOption(days, start, length, weeks)


def _klass(
    class_id: str,
    times: tuple[ITC2019TimeOption, ...],
    room_ids: tuple[str, ...],
) -> ITC2019Class:
    return ITC2019Class(
        id=class_id,
        limit=10,
        parent_id=None,
        room_required=True,
        time_options=times,
        room_options=tuple(ITC2019RoomOption(room_id) for room_id in room_ids),
    )


def _problem(
    classes: tuple[ITC2019Class, ...],
    *,
    rooms: tuple[ITC2019Room, ...] | None = None,
    distributions: tuple[ITC2019Distribution, ...] = (),
) -> ITC2019Problem:
    return ITC2019Problem(
        name="room-oracle-synthetic",
        nr_days=1,
        slots_per_day=20,
        nr_weeks=1,
        optimization=ITC2019OptimizationWeights(),
        rooms=rooms
        or (
            ITC2019Room("R1", 100, (), ()),
            ITC2019Room("R2", 100, (), ()),
        ),
        courses=tuple(
            ITC2019Course(
                id=f"course-{klass.id}",
                configurations=(
                    ITC2019Configuration(
                        id=f"config-{klass.id}",
                        subparts=(
                            ITC2019Subpart(
                                id=f"subpart-{klass.id}", classes=(klass,)
                            ),
                        ),
                    ),
                ),
            )
            for klass in classes
        ),
        distributions=distributions,
        students=(),
        source_path="room-oracle-synthetic.xml",
    )


def _placement(
    class_id: str,
    option: ITC2019TimeOption,
    room_id: str,
) -> ITC2019ClassPlacement:
    return ITC2019ClassPlacement(
        class_id, option.days, option.start, option.weeks, room_id
    )


def _checkpoint(
    *rows: tuple[str, ITC2019TimeOption],
) -> ITC2019PartialCheckpoint:
    return ITC2019PartialCheckpoint(
        tuple(
            ITC2019CheckpointTime(
                class_id,
                (option.days, option.start, option.length, option.weeks),
            )
            for class_id, option in rows
        )
    )


def test_maximal_half_open_cliques_are_deterministic_and_touching_is_legal() -> None:
    assert maximal_half_open_interval_cliques(
        (
            (0, 4, "A"),
            (1, 3, "B"),
            (3, 5, "C"),
            (5, 7, "D"),
        )
    ) == (("A", "B"), ("A", "C"))


def test_fixed_outside_time_does_not_fix_its_room() -> None:
    shared = _time(2)
    problem = _problem(
        (
            _klass("outside", (shared,), ("R1", "R2")),
            _klass("frontier", (shared,), ("R1",)),
        )
    )
    incumbent = (
        _placement("outside", shared, "R1"),
        _placement("frontier", shared, "R1"),
    )
    context = prepare_itc2019_context(
        problem,
        incumbent=incumbent,
        open_class_ids=("frontier",),
        deadline=time.monotonic() + 5,
    )

    result = solve_itc2019_room_oracle(
        context,
        _checkpoint(("outside", shared), ("frontier", shared)),
        deadline=time.monotonic() + 5,
    )

    assert result.status == "FEASIBLE"
    assert result.certificate is not None
    assert dict(result.certificate.rooms) == {"outside": "R2", "frontier": "R1"}
    assert result.certificate.competitor_schedule_or_result_used is False
    assert result.certificate.competitor_placement_or_hint_used is False


def test_required_cross_boundary_room_travel_semantics_produce_a_core() -> None:
    first = _time(0, length=2)
    second = _time(3, length=2)
    rooms = (
        ITC2019Room("R1", 100, (ITC2019Travel("R2", 2),), ()),
        ITC2019Room("R2", 100, (), ()),
    )
    problem = _problem(
        (
            _klass("outside", (first,), ("R1",)),
            _klass("frontier", (second,), ("R2",)),
        ),
        rooms=rooms,
        distributions=(
            ITC2019Distribution(
                "SameAttendees", True, 0, ("outside", "frontier")
            ),
        ),
    )
    context = prepare_itc2019_context(
        problem,
        incumbent=_checkpoint(("outside", first), ("frontier", second)),
        open_class_ids=("frontier",),
        deadline=time.monotonic() + 5,
    )

    result = solve_itc2019_room_oracle(
        context,
        _checkpoint(("outside", first), ("frontier", second)),
        deadline=time.monotonic() + 5,
    )

    assert result.status == "INFEASIBLE"
    assert result.core is not None
    assert result.core.class_ids == ("outside", "frontier")


def test_required_group_violation_is_a_source_order_structural_core() -> None:
    first = _time(0, days="1")
    second = _time(4, days="1")
    problem = _problem(
        (
            _klass("outside", (first,), ("R1",)),
            _klass("frontier", (second,), ("R2",)),
        ),
        distributions=(
            ITC2019Distribution("MaxDayLoad(3)", True, 0, ("frontier", "outside")),
        ),
    )
    context = prepare_itc2019_context(
        problem,
        incumbent=_checkpoint(("outside", first), ("frontier", second)),
        open_class_ids=("frontier",),
        deadline=time.monotonic() + 5,
    )

    result = solve_itc2019_room_oracle(
        context,
        _checkpoint(("outside", first), ("frontier", second)),
        deadline=time.monotonic() + 5,
    )

    assert result.status == "INFEASIBLE"
    assert result.core is not None
    assert result.core.class_ids == ("outside", "frontier")
    assert result.core.distribution_ordinals == (0,)
    assert result.core.kind == "required_group_time_violation"


def test_group_evaluation_deadline_takes_precedence_over_infeasibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    option = _time(0)
    problem = _problem(
        (_klass("A", (option,), ("R1",)),),
        distributions=(
            ITC2019Distribution("MaxDays(0)", True, 0, ("A",)),
        ),
    )
    checkpoint = _checkpoint(("A", option))
    context = prepare_itc2019_context(
        problem,
        incumbent=checkpoint,
        open_class_ids=("A",),
        deadline=time.monotonic() + 5,
    )

    def delayed_violation(*_args, **_kwargs) -> int:
        time.sleep(0.05)
        return 1

    monkeypatch.setattr(
        room_oracle, "_special_distribution_units", delayed_violation
    )
    result = solve_itc2019_room_oracle(
        context,
        checkpoint,
        deadline=time.monotonic() + 0.01,
    )

    assert result.status == "DEADLINE_EXCEEDED"
    assert result.core is None


@pytest.mark.parametrize(
    ("selected", "message"),
    (
        (ITC2019PartialCheckpoint(), "incomplete"),
        (
            ITC2019PartialCheckpoint(
                (
                    ITC2019CheckpointTime("A", ("1", 0, 2, "1")),
                    ITC2019CheckpointTime("A", ("1", 0, 2, "1")),
                )
            ),
            "duplicate",
        ),
        (
            ITC2019PartialCheckpoint(
                (ITC2019CheckpointTime("A", ("1", 99, 2, "1")),)
            ),
            "stale",
        ),
    ),
)
def test_time_admission_fails_closed(
    selected: ITC2019PartialCheckpoint,
    message: str,
) -> None:
    option = _time(0)
    problem = _problem((_klass("A", (option,), ("R1",)),))
    context = prepare_itc2019_context(
        problem,
        incumbent=_checkpoint(("A", option)),
        open_class_ids=("A",),
        deadline=time.monotonic() + 5,
    )

    with pytest.raises(ValueError, match=message):
        solve_itc2019_room_oracle(
            context, selected, deadline=time.monotonic() + 5
        )


def test_deadline_and_resource_limits_are_explicit_not_infeasible() -> None:
    option = _time(0)
    problem = _problem((_klass("A", (option,), ("R1", "R2")),))
    checkpoint = _checkpoint(("A", option))
    context = prepare_itc2019_context(
        problem,
        incumbent=checkpoint,
        open_class_ids=("A",),
        deadline=time.monotonic() + 5,
    )

    expired = solve_itc2019_room_oracle(
        context, checkpoint, deadline=time.monotonic() - 1
    )
    bounded = solve_itc2019_room_oracle(
        context,
        checkpoint,
        deadline=time.monotonic() + 5,
        limits=ITC2019RoomOracleLimits(max_room_selectors=1),
    )

    assert expired.status == "DEADLINE_EXCEEDED"
    assert bounded.status == "RESOURCE_LIMIT"
    assert bounded.failure_reason == "room_selector_limit:2>1"
    assert expired.core is None
    assert bounded.core is None
