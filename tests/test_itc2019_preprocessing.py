from __future__ import annotations

from dataclasses import FrozenInstanceError
import time

import pytest

import benchmarks.itc2019_preprocessing as preprocessing
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
    ITC2019Unavailable,
)
from benchmarks.itc2019_preprocessing import (
    ITC2019CheckpointTime,
    ITC2019Occurrence,
    ITC2019PartialCheckpoint,
    prepare_itc2019_context,
    validate_itc2019_partial_checkpoint,
)


def _time(
    days: str,
    start: int,
    length: int = 2,
    weeks: str = "111",
    penalty: int = 0,
) -> ITC2019TimeOption:
    return ITC2019TimeOption(days, start, length, weeks, penalty)


def _klass(
    class_id: str,
    *,
    times: tuple[ITC2019TimeOption, ...],
    room_ids: tuple[str, ...] = ("R1", "R2"),
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
) -> ITC2019Problem:
    return ITC2019Problem(
        name="preprocessing-synthetic",
        nr_days=3,
        slots_per_day=20,
        nr_weeks=3,
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
        source_path="preprocessing-synthetic.xml",
    )


def _checkpoint_entry(
    class_id: str,
    option: ITC2019TimeOption,
) -> ITC2019CheckpointTime:
    return ITC2019CheckpointTime(
        class_id,
        (option.days, option.start, option.length, option.weeks),
    )


def test_canonical_time_signatures_keep_the_least_penalty_duplicate() -> None:
    duplicate_high = _time("101", 3, 2, "101", penalty=9)
    duplicate_low = _time("101", 3, 2, "101", penalty=2)
    distinct = _time("010", 8, 1, "010", penalty=4)
    problem = _problem(
        (_klass("A", times=(duplicate_high, duplicate_low, distinct)),)
    )

    context = prepare_itc2019_context(
        problem,
        incumbent=None,
        open_class_ids=("A",),
        deadline=time.monotonic() + 5,
    )

    prepared = context.class_for("A")
    assert tuple(value.signature for value in prepared.times) == (
        ("101", 3, 2, "101"),
        ("010", 8, 1, "010"),
    )
    assert prepared.times[0].penalty == 2
    assert prepared.times[0].source_ordinal == 1
    assert tuple(prepared.times[0].occurrences()) == (
        ITC2019Occurrence(0, 0, 3, 5),
        ITC2019Occurrence(0, 2, 3, 5),
        ITC2019Occurrence(2, 0, 3, 5),
        ITC2019Occurrence(2, 2, 3, 5),
    )


def test_prepared_context_retains_every_distribution_and_raw_membership() -> None:
    classes = tuple(
        _klass(class_id, times=(_time("100", index * 3),))
        for index, class_id in enumerate(("A", "B", "C"))
    )
    types = (
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
        "WorkDay(8)",
        "MinGap(2)",
        "MaxDays(2)",
        "MaxDayLoad(5)",
        "MaxBreaks(1,2)",
        "MaxBlock(6,1)",
    )
    distributions = tuple(
        ITC2019Distribution(
            constraint_type,
            index % 2 == 0,
            index + 1,
            ("A", "B", "A", "C"),
        )
        for index, constraint_type in enumerate(types)
    )
    problem = _problem(classes, distributions=distributions)

    context = prepare_itc2019_context(
        problem,
        incumbent=None,
        open_class_ids=("A", "B", "C"),
        deadline=time.monotonic() + 5,
    )

    assert tuple(item.constraint_type for item in context.distributions) == types
    assert all(
        item.raw_class_ids == ("A", "B", "A", "C")
        for item in context.distributions
    )
    assert all(item.class_ids == ("A", "B", "C") for item in context.distributions)
    assert context.distributions[-1].base == "MaxBlock"
    assert context.distributions[-1].parameters == (6, 1)
    assert tuple(item.required for item in context.distributions) == tuple(
        index % 2 == 0 for index in range(len(types))
    )


def test_unavailability_is_per_time_and_roomless_classes_use_none() -> None:
    rooms = (
        ITC2019Room(
            "R1",
            100,
            (),
            (ITC2019Unavailable("100", 1, 3, "101"),),
        ),
        ITC2019Room("R2", 100, (), ()),
    )
    roomed = _klass(
        "A",
        times=(_time("100", 2, 2, "001"), _time("010", 2, 2, "001")),
    )
    roomless = _klass(
        "B",
        times=(_time("100", 2, 2, "001"),),
        room_ids=(),
        room_required=False,
    )
    problem = _problem((roomed, roomless), rooms=rooms)

    context = prepare_itc2019_context(
        problem,
        incumbent=None,
        open_class_ids=("A", "B"),
        deadline=time.monotonic() + 5,
    )

    assert context.class_for("A").times[0].legal_room_ids == ("R2",)
    assert context.class_for("A").times[1].legal_room_ids == ("R1", "R2")
    assert tuple(room.room_id for room in context.class_for("B").rooms) == (None,)
    assert context.class_for("B").times[0].legal_room_ids == (None,)


def test_streamed_and_full_materialization_are_exactly_equivalent() -> None:
    first = _time("100", 0)
    second = _time("010", 4)
    problem = _problem(
        (_klass("A", times=(first, second)), _klass("B", times=(second, first))),
        distributions=(
            ITC2019Distribution("SameDays", False, 3, ("A", "B")),
        ),
    )
    checkpoint = ITC2019PartialCheckpoint((_checkpoint_entry("A", first),))

    streamed = prepare_itc2019_context(
        problem,
        incumbent=checkpoint,
        open_class_ids=("B",),
        deadline=time.monotonic() + 5,
        materialization="streamed",
    )
    full = prepare_itc2019_context(
        problem,
        incumbent=checkpoint,
        open_class_ids=("B",),
        deadline=time.monotonic() + 5,
        materialization="full",
    )

    assert streamed == full
    with pytest.raises(FrozenInstanceError):
        streamed.classes = ()


def test_checkpoint_is_immutable_and_uses_length_bearing_signatures() -> None:
    option = _time("100", 2, 3, "011", penalty=7)
    problem = _problem((_klass("A", times=(option,)),))
    placements = (
        ITC2019ClassPlacement("A", "100", 2, "011", room_id="R1"),
    )

    checkpoint = ITC2019PartialCheckpoint.from_placements(problem, placements)

    assert checkpoint.times == (
        ITC2019CheckpointTime("A", ("100", 2, 3, "011")),
    )
    assert validate_itc2019_partial_checkpoint(problem, checkpoint) == ()
    with pytest.raises(FrozenInstanceError):
        checkpoint.times = ()
    assert placements[0].room_id == "R1"


def test_fixed_checkpoint_freezes_only_time_and_keeps_every_room_movable() -> None:
    fixed_time = _time("100", 2, 2, "111")
    rooms = (
        ITC2019Room(
            "R1",
            100,
            (),
            (ITC2019Unavailable("100", 2, 2, "111"),),
        ),
        ITC2019Room("R2", 100, (), ()),
    )
    problem = _problem((_klass("A", times=(fixed_time,)),), rooms=rooms)
    incumbent = (
        ITC2019ClassPlacement("A", "100", 2, "111", room_id="R1"),
    )

    context = prepare_itc2019_context(
        problem,
        incumbent=incumbent,
        open_class_ids=(),
        deadline=time.monotonic() + 5,
    )

    assert context.fixed_checkpoint == ITC2019PartialCheckpoint(
        (_checkpoint_entry("A", fixed_time),)
    )
    assert not hasattr(context.fixed_checkpoint.times[0], "room_id")
    assert tuple(room.room_id for room in context.class_for("A").rooms) == (
        "R1",
        "R2",
    )
    assert context.class_for("A").times[0].legal_room_ids == ("R2",)


def test_optional_room_hints_check_local_legality_but_not_global_occupancy() -> None:
    option = _time("100", 2)
    rooms = (
        ITC2019Room(
            "R1",
            100,
            (),
            (ITC2019Unavailable("100", 2, 2, "111"),),
        ),
        ITC2019Room("R2", 100, (), ()),
    )
    problem = _problem(
        (_klass("A", times=(option,)), _klass("B", times=(option,))), rooms=rooms
    )
    checkpoint = ITC2019PartialCheckpoint(
        (_checkpoint_entry("A", option), _checkpoint_entry("B", option))
    )

    assert validate_itc2019_partial_checkpoint(
        problem,
        checkpoint,
        room_hints={"A": "R2", "B": "R2"},
    ) == ()
    assert validate_itc2019_partial_checkpoint(
        problem,
        checkpoint,
        room_hints={"A": "R1"},
    ) == ("room hint R1 for class A is unavailable at its time",)


def test_partial_hard_distribution_checks_only_fully_fixed_relations() -> None:
    first = _time("100", 0)
    overlapping = _time("100", 1)
    problem = _problem(
        (_klass("A", times=(first,)), _klass("B", times=(overlapping,))),
        distributions=(ITC2019Distribution("NotOverlap", True, 0, ("A", "B")),),
    )
    first_only = ITC2019PartialCheckpoint((_checkpoint_entry("A", first),))

    assert validate_itc2019_partial_checkpoint(
        problem,
        first_only,
        open_class_ids=("B",),
    ) == ()
    complete = ITC2019PartialCheckpoint(
        (_checkpoint_entry("A", first), _checkpoint_entry("B", overlapping))
    )
    assert validate_itc2019_partial_checkpoint(problem, complete) == (
        "checkpoint violates required NotOverlap: A, B",
    )


def test_open_checkpoint_entries_are_hints_not_fixed_distribution_state() -> None:
    fixed = _time("100", 0, 2)
    conflicting_hint = _time("100", 1, 2)
    feasible_alternative = _time("100", 4, 2)
    problem = _problem(
        (
            _klass("A", times=(fixed,)),
            _klass("B", times=(conflicting_hint, feasible_alternative)),
        ),
        distributions=(ITC2019Distribution("NotOverlap", True, 0, ("A", "B")),),
    )
    full_incumbent = ITC2019PartialCheckpoint(
        (
            _checkpoint_entry("A", fixed),
            _checkpoint_entry("B", conflicting_hint),
        )
    )

    assert validate_itc2019_partial_checkpoint(
        problem,
        full_incumbent,
        open_class_ids=("B",),
    ) == ()
    assert validate_itc2019_partial_checkpoint(problem, full_incumbent) == (
        "checkpoint violates required NotOverlap: A, B",
    )

    context = prepare_itc2019_context(
        problem,
        incumbent=full_incumbent,
        open_class_ids=("B",),
        deadline=time.monotonic() + 5,
    )
    assert context.fixed_checkpoint.times == (_checkpoint_entry("A", fixed),)
    assert tuple(value.signature for value in context.class_for("B").times) == (
        ("100", 1, 2, "111"),
        ("100", 4, 2, "111"),
    )


@pytest.mark.parametrize(
    ("constraint_type", "times"),
    (
        ("MaxDays(1)", (_time("100", 0), _time("010", 0))),
        ("MaxDayLoad(3)", (_time("100", 0), _time("100", 4))),
        ("MaxBreaks(0,0)", (_time("100", 0), _time("100", 4))),
        ("MaxBlock(3,2)", (_time("100", 0, 2), _time("100", 3, 2))),
    ),
)
def test_complete_grouped_checkpoint_uses_official_semantics(
    constraint_type: str,
    times: tuple[ITC2019TimeOption, ITC2019TimeOption],
) -> None:
    first, second = times
    problem = _problem(
        (_klass("A", times=(first,)), _klass("B", times=(second,))),
        distributions=(
            ITC2019Distribution(constraint_type, True, 0, ("A", "B", "A")),
        ),
    )
    checkpoint = ITC2019PartialCheckpoint(
        (_checkpoint_entry("A", first), _checkpoint_entry("B", second))
    )

    errors = validate_itc2019_partial_checkpoint(problem, checkpoint)

    assert len(errors) == 1
    assert errors[0].startswith(
        f"checkpoint violates required {constraint_type}:"
    )


def test_room_only_required_distribution_stays_for_the_room_phase() -> None:
    option = _time("100", 0)
    problem = _problem(
        (_klass("A", times=(option,)), _klass("B", times=(option,))),
        distributions=(
            ITC2019Distribution("DifferentRoom", True, 0, ("A", "B")),
        ),
    )
    checkpoint = ITC2019PartialCheckpoint(
        (_checkpoint_entry("A", option), _checkpoint_entry("B", option))
    )

    assert validate_itc2019_partial_checkpoint(problem, checkpoint) == ()
    context = prepare_itc2019_context(
        problem,
        incumbent=checkpoint,
        open_class_ids=(),
        deadline=time.monotonic() + 5,
    )
    assert context.distributions[0].base == "DifferentRoom"
    assert context.distributions[0].required


def test_same_attendees_uses_an_existential_movable_legal_room_pair() -> None:
    first = _time("100", 0, 2)
    second = _time("100", 3, 2)
    rooms = (
        ITC2019Room("R1", 100, (ITC2019Travel("R2", 3),), ()),
        ITC2019Room("R2", 100, (), ()),
    )
    required = (
        ITC2019Distribution("SameAttendees", True, 0, ("A", "B")),
    )
    forced_problem = _problem(
        (
            _klass("A", times=(first,), room_ids=("R1",)),
            _klass("B", times=(second,), room_ids=("R2",)),
        ),
        rooms=rooms,
        distributions=required,
    )
    checkpoint = ITC2019PartialCheckpoint(
        (_checkpoint_entry("A", first), _checkpoint_entry("B", second))
    )

    assert validate_itc2019_partial_checkpoint(forced_problem, checkpoint) == (
        "checkpoint violates required SameAttendees: A, B",
    )

    movable_problem = _problem(
        (
            _klass("A", times=(first,), room_ids=("R1", "R2")),
            _klass("B", times=(second,), room_ids=("R1", "R2")),
        ),
        rooms=rooms,
        distributions=required,
    )
    assert validate_itc2019_partial_checkpoint(
        movable_problem,
        checkpoint,
        room_hints={"A": "R1", "B": "R2"},
    ) == ()

    overlap_problem = _problem(
        (
            _klass("A", times=(first,), room_ids=("R1", "R2")),
            _klass("B", times=(_time("100", 1, 2),), room_ids=("R1", "R2")),
        ),
        rooms=rooms,
        distributions=required,
    )
    overlap_checkpoint = ITC2019PartialCheckpoint(
        (
            _checkpoint_entry("A", first),
            _checkpoint_entry("B", _time("100", 1, 2)),
        )
    )
    assert validate_itc2019_partial_checkpoint(
        overlap_problem, overlap_checkpoint
    ) == ("checkpoint violates required SameAttendees: A, B",)


def test_fixed_required_room_time_with_zero_legal_rooms_fails_closed() -> None:
    option = _time("100", 2, 2)
    rooms = (
        ITC2019Room(
            "R1",
            100,
            (),
            (ITC2019Unavailable("100", 2, 2, "111"),),
        ),
    )
    problem = _problem(
        (_klass("A", times=(option,), room_ids=("R1",)),), rooms=rooms
    )
    checkpoint = ITC2019PartialCheckpoint((_checkpoint_entry("A", option),))

    assert validate_itc2019_partial_checkpoint(problem, checkpoint) == (
        "checkpoint class A required-room time has no legal rooms",
    )
    with pytest.raises(ValueError, match="required-room time has no legal rooms"):
        prepare_itc2019_context(
            problem,
            incumbent=checkpoint,
            open_class_ids=(),
            deadline=time.monotonic() + 5,
        )


def test_open_time_pruning_rejects_only_when_every_room_choice_is_wiped() -> None:
    blocked = _time("100", 2, 2)
    legal = _time("010", 7, 2)
    rooms = (
        ITC2019Room(
            "R1",
            100,
            (),
            (
                ITC2019Unavailable("100", 2, 2, "111"),
                ITC2019Unavailable("010", 7, 2, "111"),
            ),
        ),
    )
    wiped = _problem(
        (_klass("A", times=(blocked, legal), room_ids=("R1",)),), rooms=rooms
    )

    with pytest.raises(
        ValueError, match="open class A has no legal time-room alternatives"
    ):
        prepare_itc2019_context(
            wiped,
            incumbent=None,
            open_class_ids=("A",),
            deadline=time.monotonic() + 5,
        )

    partly_legal_rooms = (
        ITC2019Room(
            "R1",
            100,
            (),
            (ITC2019Unavailable("100", 2, 2, "111"),),
        ),
    )
    partly_legal = _problem(
        (_klass("A", times=(blocked, legal), room_ids=("R1",)),),
        rooms=partly_legal_rooms,
    )
    context = prepare_itc2019_context(
        partly_legal,
        incumbent=None,
        open_class_ids=("A",),
        deadline=time.monotonic() + 5,
    )
    assert tuple(value.signature for value in context.class_for("A").times) == (
        ("010", 7, 2, "111"),
    )


def test_checkpoint_deadline_is_checked_after_final_distribution_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    option = _time("100", 0)
    problem = _problem(
        (_klass("A", times=(option,)),),
        distributions=(ITC2019Distribution("MaxDays(1)", True, 0, ("A",)),),
    )
    checkpoint = ITC2019PartialCheckpoint((_checkpoint_entry("A", option),))
    clock = {"now": 0.0}
    original_check_deadline = preprocessing._check_deadline

    def expire_after_distribution(
        deadline: float | None, operation: str
    ) -> None:
        original_check_deadline(deadline, operation)
        if operation == "checkpoint distribution validation":
            clock["now"] = 11.0

    monkeypatch.setattr(preprocessing.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        preprocessing, "_check_deadline", expire_after_distribution
    )

    with pytest.raises(TimeoutError, match="completion"):
        validate_itc2019_partial_checkpoint(
            problem,
            checkpoint,
            deadline=10.0,
        )


def test_checkpoint_rejects_stale_lengths_duplicates_and_missing_fixed_classes() -> None:
    option = _time("100", 1, 2)
    problem = _problem(
        (_klass("A", times=(option,)), _klass("B", times=(option,)))
    )
    stale = ITC2019PartialCheckpoint(
        (
            ITC2019CheckpointTime("A", ("100", 1, 3, "111")),
            ITC2019CheckpointTime("A", ("100", 1, 2, "111")),
        )
    )

    errors = validate_itc2019_partial_checkpoint(
        problem,
        stale,
        open_class_ids=(),
    )

    assert "checkpoint contains duplicate classes: A" in errors
    assert "checkpoint is missing fixed classes: B" in errors
    assert "checkpoint class A time signature is outside its domain" in errors


def test_preparation_fails_closed_for_deadlines_and_frontier_identity() -> None:
    option = _time("100", 0)
    problem = _problem((_klass("A", times=(option,)),))

    with pytest.raises(TimeoutError, match="context admission"):
        prepare_itc2019_context(
            problem,
            incumbent=None,
            open_class_ids=("A",),
            deadline=time.monotonic() - 1,
        )
    with pytest.raises(ValueError, match="duplicates"):
        prepare_itc2019_context(
            problem,
            incumbent=None,
            open_class_ids=("A", "A"),
            deadline=time.monotonic() + 5,
        )
    with pytest.raises(ValueError, match="unknown classes"):
        prepare_itc2019_context(
            problem,
            incumbent=None,
            open_class_ids=("unknown",),
            deadline=time.monotonic() + 5,
        )
    with pytest.raises(ValueError, match="materialization"):
        prepare_itc2019_context(
            problem,
            incumbent=None,
            open_class_ids=("A",),
            deadline=time.monotonic() + 5,
            materialization="other",  # type: ignore[arg-type]
        )

    duplicate_checkpoint = ITC2019PartialCheckpoint(
        (_checkpoint_entry("A", option), _checkpoint_entry("A", option))
    )
    with pytest.raises(ValueError, match="duplicate classes: A"):
        prepare_itc2019_context(
            problem,
            incumbent=duplicate_checkpoint,
            open_class_ids=("A",),
            deadline=time.monotonic() + 5,
        )
    stale_checkpoint = ITC2019PartialCheckpoint(
        (ITC2019CheckpointTime("A", ("100", 0, 3, "111")),)
    )
    with pytest.raises(ValueError, match="outside the class domain for: A"):
        prepare_itc2019_context(
            problem,
            incumbent=stale_checkpoint,
            open_class_ids=("A",),
            deadline=time.monotonic() + 5,
        )
