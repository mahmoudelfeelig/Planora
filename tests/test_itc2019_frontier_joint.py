from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import time

import pytest

import benchmarks.itc2019_frontier_joint as frontier_joint_module
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
    parse_itc2019_xml,
)
from benchmarks.itc2019_frontier_joint import (
    ITC2019FrontierCheckpoint,
    ITC2019FrontierJointLimits,
    ITC2019ProvenanceHash,
    admit_frontier_checkpoint,
    create_frontier_checkpoint,
    select_final_round_frontier,
    solve_itc2019_frontier_joint,
)
from benchmarks.itc2019_preprocessing import (
    ITC2019CheckpointTime,
    ITC2019PartialCheckpoint,
    prepare_itc2019_context,
)


_PROVENANCE = {
    "instance": "1" * 64,
    "preprocessing": "2" * 64,
    "source-progress": "3" * 64,
}


def _time(
    start: int,
    *,
    days: str = "10",
    length: int = 2,
    weeks: str = "1",
) -> ITC2019TimeOption:
    return ITC2019TimeOption(days, start, length, weeks)


def _klass(
    class_id: str,
    times: tuple[ITC2019TimeOption, ...],
    room_ids: tuple[str, ...] = ("R1", "R2"),
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
    distributions: tuple[ITC2019Distribution, ...] = (),
    slots_per_day: int = 20,
) -> ITC2019Problem:
    return ITC2019Problem(
        name="frontier-joint-synthetic",
        nr_days=2,
        slots_per_day=slots_per_day,
        nr_weeks=1,
        optimization=ITC2019OptimizationWeights(),
        rooms=(
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
        source_path="frontier-joint-synthetic.xml",
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


def _placement(
    class_id: str,
    option: ITC2019TimeOption,
    room_id: str,
) -> ITC2019ClassPlacement:
    return ITC2019ClassPlacement(
        class_id, option.days, option.start, option.weeks, room_id
    )


def test_structural_frontier_uses_only_new_final_round_cut_tails() -> None:
    progress = {
        "round": 9,
        "hall_cuts": [
            [["old", 0]],
            [["C", 1], ["A", 2]],
        ],
        "hall_property_cuts": [
            {"components": ["old"]},
            {"components": ["D", "C"]},
        ],
        "last_round": {
            "round": 9,
            "new_hall_cuts": 1,
            "new_hall_property_cuts": 1,
            "total_hall_cuts": 2,
            "total_hall_property_cuts": 2,
        },
    }

    assert select_final_round_frontier(
        progress, ("old", "A", "B", "C", "D")
    ) == ("A", "C", "D")


def test_frontier_checkpoint_roundtrip_and_frozen_preprocessing_admission() -> None:
    fixed_time = _time(0)
    incumbent_open = _time(4)
    alternative_open = _time(8)
    problem = _problem(
        (
            _klass("fixed", (fixed_time,)),
            _klass("open", (incumbent_open, alternative_open)),
        )
    )
    checkpoint = create_frontier_checkpoint(
        problem,
        _checkpoint(("fixed", fixed_time), ("open", incumbent_open)),
        open_class_ids=("open",),
        provenance_hashes=_PROVENANCE,
        deadline=time.monotonic() + 5,
    )

    restored = ITC2019FrontierCheckpoint.from_dict(checkpoint.to_dict())
    context = admit_frontier_checkpoint(
        problem,
        restored,
        expected_provenance_hashes=_PROVENANCE,
        deadline=time.monotonic() + 5,
    )

    assert restored == checkpoint
    assert checkpoint.assigned_class_ids == ("fixed",)
    assert checkpoint.open_class_ids == ("open",)
    assert checkpoint.admissible_as_solution is False
    assert checkpoint.competitor_schedule_or_result_used is False
    assert checkpoint.competitor_placement_or_hint_used is False
    assert len(context.class_for("fixed").times) == 1
    assert len(context.class_for("open").times) == 2


def test_frontier_checkpoint_treats_open_incumbent_time_as_hint() -> None:
    fixed_time = _time(0)
    conflicting_open_hint = _time(0)
    legal_open_alternative = _time(4)
    problem = _problem(
        (
            _klass("fixed", (fixed_time,)),
            _klass("open", (conflicting_open_hint, legal_open_alternative)),
        ),
        distributions=(
            ITC2019Distribution(
                "SameAttendees", True, 0, ("fixed", "open")
            ),
        ),
    )

    checkpoint = create_frontier_checkpoint(
        problem,
        _checkpoint(
            ("fixed", fixed_time),
            ("open", conflicting_open_hint),
        ),
        open_class_ids=("open",),
        provenance_hashes=_PROVENANCE,
        deadline=time.monotonic() + 5,
    )
    context = admit_frontier_checkpoint(
        problem,
        checkpoint,
        expected_provenance_hashes=_PROVENANCE,
        deadline=time.monotonic() + 5,
    )

    assert checkpoint.assigned_class_ids == ("fixed",)
    assert checkpoint.open_class_ids == ("open",)
    assert len(context.class_for("fixed").times) == 1
    assert tuple(value.start for value in context.class_for("open").times) == (0, 4)

    result = solve_itc2019_frontier_joint(
        context,
        deadline=time.monotonic() + 5,
    )

    assert result.is_feasible
    assert next(
        placement.start
        for placement in result.placements
        if placement.class_id == "open"
    ) == 4


def _valid_checkpoint_payload() -> tuple[ITC2019Problem, dict[str, object]]:
    first = _time(0)
    second = _time(4)
    problem = _problem((_klass("A", (first,)), _klass("B", (second,))))
    checkpoint = create_frontier_checkpoint(
        problem,
        _checkpoint(("A", first), ("B", second)),
        open_class_ids=("B",),
        provenance_hashes=_PROVENANCE,
        deadline=time.monotonic() + 5,
    )
    return problem, checkpoint.to_dict()


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload["canonical_times"].append(  # type: ignore[union-attr]
            deepcopy(payload["canonical_times"][0])  # type: ignore[index]
        ),
        lambda payload: payload["canonical_times"].pop(),  # type: ignore[union-attr]
        lambda payload: payload["canonical_times"][0]["signature"].__setitem__(  # type: ignore[index,union-attr]
            1, 99
        ),
        lambda payload: payload["provenance_hashes"][0].__setitem__(  # type: ignore[index,union-attr]
            "sha256", "4" * 64
        ),
        lambda payload: payload["provenance_hashes"].append(  # type: ignore[union-attr]
            deepcopy(payload["provenance_hashes"][0])  # type: ignore[index]
        ),
        lambda payload: payload["open_class_ids"].append("B"),  # type: ignore[union-attr]
        lambda payload: payload.__setitem__(
            "competitor_placement_or_hint_used", True
        ),
        lambda payload: payload.__setitem__("admissible_as_solution", True),
    ),
)
def test_checkpoint_tampering_duplicates_missing_stale_and_provenance_fail_closed(
    mutation,
) -> None:
    problem, payload = _valid_checkpoint_payload()
    mutation(payload)

    with pytest.raises((TypeError, ValueError)):
        admit_frontier_checkpoint(
            problem,
            payload,
            expected_provenance_hashes=_PROVENANCE,
            deadline=time.monotonic() + 5,
        )


def test_joint_frontier_keeps_outside_time_fixed_but_moves_its_room() -> None:
    shared = _time(2)
    problem = _problem(
        (
            _klass("outside", (shared,), ("R1", "R2")),
            _klass("frontier", (shared,), ("R1",)),
        )
    )
    context = prepare_itc2019_context(
        problem,
        incumbent=(
            _placement("outside", shared, "R1"),
            _placement("frontier", shared, "R1"),
        ),
        open_class_ids=("frontier",),
        deadline=time.monotonic() + 5,
    )

    result = solve_itc2019_frontier_joint(
        context, deadline=time.monotonic() + 5
    )

    assert result.status == "FEASIBLE"
    by_id = {placement.class_id: placement for placement in result.placements}
    assert by_id["outside"].start == shared.start
    assert by_id["outside"].room_id == "R2"
    assert by_id["frontier"].room_id == "R1"


def test_required_pair_is_exact_across_the_frontier_boundary() -> None:
    outside = _time(0)
    conflicting = _time(1)
    legal = _time(4)
    problem = _problem(
        (
            _klass("outside", (outside,), ("R1",)),
            _klass("frontier", (conflicting, legal), ("R2",)),
        ),
        distributions=(
            ITC2019Distribution(
                "DifferentTime", True, 0, ("outside", "frontier")
            ),
        ),
    )
    context = prepare_itc2019_context(
        problem,
        incumbent=_checkpoint(("outside", outside), ("frontier", legal)),
        open_class_ids=("frontier",),
        deadline=time.monotonic() + 5,
    )

    result = solve_itc2019_frontier_joint(
        context, deadline=time.monotonic() + 5
    )

    assert result.status == "FEASIBLE"
    selected = {placement.class_id: placement for placement in result.placements}
    assert selected["outside"].start == 0
    assert selected["frontier"].start == 4


def test_required_group_is_exact_across_the_frontier_boundary() -> None:
    outside = _time(0, days="10")
    wrong_day = _time(0, days="01")
    same_day = _time(4, days="10")
    problem = _problem(
        (
            _klass("outside", (outside,), ("R1",)),
            _klass("frontier", (wrong_day, same_day), ("R2",)),
        ),
        distributions=(
            ITC2019Distribution("MaxDays(1)", True, 0, ("outside", "frontier")),
        ),
    )
    context = prepare_itc2019_context(
        problem,
        incumbent=_checkpoint(("outside", outside), ("frontier", same_day)),
        open_class_ids=("frontier",),
        deadline=time.monotonic() + 5,
    )

    result = solve_itc2019_frontier_joint(
        context, deadline=time.monotonic() + 5
    )

    assert result.status == "FEASIBLE"
    selected = {placement.class_id: placement for placement in result.placements}
    assert selected["frontier"].days == "10"
    assert result.group_time_rows == 2


def test_joint_deadline_and_resource_bounds_are_explicit() -> None:
    option = _time(0)
    problem = _problem((_klass("A", (option,), ("R1", "R2")),))
    context = prepare_itc2019_context(
        problem,
        incumbent=_checkpoint(("A", option)),
        open_class_ids=("A",),
        deadline=time.monotonic() + 5,
    )

    expired = solve_itc2019_frontier_joint(
        context, deadline=time.monotonic() - 1
    )
    bounded = solve_itc2019_frontier_joint(
        context,
        deadline=time.monotonic() + 5,
        limits=ITC2019FrontierJointLimits(max_placement_literals=1),
    )

    assert expired.status == "DEADLINE_EXCEEDED"
    assert bounded.status == "RESOURCE_LIMIT"
    assert bounded.failure_reason == "placement_literal_limit:2>1"


def test_required_pair_deadline_is_polled_inside_cartesian_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = tuple(_time(start, length=1) for start in range(65))
    problem = _problem(
        (
            _klass("A", options, ("R1",)),
            _klass("B", options, ("R2",)),
        ),
        distributions=(
            ITC2019Distribution("DifferentTime", True, 0, ("A", "B")),
        ),
        slots_per_day=100,
    )
    context = prepare_itc2019_context(
        problem,
        incumbent=_checkpoint(("A", options[0]), ("B", options[1])),
        open_class_ids=("A", "B"),
        deadline=time.monotonic() + 5,
    )

    class Clock:
        expired = False

        def monotonic(self) -> float:
            return 2.0 if self.expired else 0.0

    clock = Clock()
    pair_calls = 0
    real_pair_check = frontier_joint_module._pair_distribution_satisfied

    def counted_pair_check(*args, **kwargs):
        nonlocal pair_calls
        pair_calls += 1
        if pair_calls == 4_096:
            clock.expired = True
        return real_pair_check(*args, **kwargs)

    monkeypatch.setattr(frontier_joint_module, "time", clock)
    monkeypatch.setattr(
        frontier_joint_module,
        "_pair_distribution_satisfied",
        counted_pair_check,
    )

    result = solve_itc2019_frontier_joint(context, deadline=1.0)

    assert result.status == "DEADLINE_EXCEEDED"
    assert result.pair_placement_cells == 4_096
    assert pair_calls == 4_096


def test_required_group_deadline_precedes_infeasible_after_delayed_final_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _time(0, days="10")
    second_a = _time(1, days="10")
    second_b = _time(2, days="01")
    problem = _problem(
        (
            _klass("A", (first,), ("R1",)),
            _klass("B", (second_a, second_b), ("R2",)),
        ),
        distributions=(
            ITC2019Distribution("MaxDays(0)", True, 0, ("A", "B")),
        ),
    )
    context = prepare_itc2019_context(
        problem,
        incumbent=_checkpoint(("A", first), ("B", second_a)),
        open_class_ids=("A", "B"),
        deadline=time.monotonic() + 5,
    )

    class Clock:
        expired = False

        def monotonic(self) -> float:
            return 2.0 if self.expired else 0.0

    clock = Clock()
    group_calls = 0
    real_group_check = frontier_joint_module._special_distribution_units

    def delayed_group_check(*args, **kwargs):
        nonlocal group_calls
        group_calls += 1
        units = real_group_check(*args, **kwargs)
        if group_calls == 2:
            clock.expired = True
        return units

    monkeypatch.setattr(frontier_joint_module, "time", clock)
    monkeypatch.setattr(
        frontier_joint_module,
        "_special_distribution_units",
        delayed_group_check,
    )

    result = solve_itc2019_frontier_joint(context, deadline=1.0)

    assert result.status == "DEADLINE_EXCEEDED"
    assert result.group_time_rows == 2
    assert group_calls == 2
    assert not result.placements


def test_success_is_rejected_when_final_semantic_validation_crosses_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    option = _time(0)
    problem = _problem((_klass("A", (option,), ("R1",)),))
    context = prepare_itc2019_context(
        problem,
        incumbent=_checkpoint(("A", option)),
        open_class_ids=("A",),
        deadline=time.monotonic() + 5,
    )

    class Clock:
        expired = False

        def monotonic(self) -> float:
            return 2.0 if self.expired else 0.0

    clock = Clock()
    real_validation = frontier_joint_module.validate_itc2019_solution

    def expiring_validation(*args, **kwargs):
        errors = real_validation(*args, **kwargs)
        clock.expired = True
        return errors

    monkeypatch.setattr(frontier_joint_module, "time", clock)
    monkeypatch.setattr(
        frontier_joint_module,
        "validate_itc2019_solution",
        expiring_validation,
    )

    result = solve_itc2019_frontier_joint(context, deadline=1.0)

    assert result.status == "DEADLINE_EXCEEDED"
    assert not result.placements


_PINNED_PROGRESS = Path("/tmp/planora-muni-fspsx-hall-objective-v35-progress.json")
_PINNED_INSTANCE = Path(
    "data/external/itc2019-mpp-c33d15797686/raw/data/input/ITC-2019/"
    "muni-fspsx-fal17.xml"
)
_PINNED_PROGRESS_SHA256 = (
    "5cf7e3450ff96d79b3a5dbac1baa784a585b777397603d379a91513ada35cedf"
)
_PINNED_INSTANCE_SHA256 = (
    "151664dfc27f377e5048cf0bf8ad48fac350c46a7db6ca7181fed6d1933960b6"
)


@pytest.mark.skipif(
    not _PINNED_PROGRESS.is_file() or not _PINNED_INSTANCE.is_file(),
    reason="source-derived pinned v35 artifacts are unavailable",
)
def test_pinned_v35_structural_frontier_is_152_open_and_1471_fixed() -> None:
    assert sha256(_PINNED_PROGRESS.read_bytes()).hexdigest() == (
        _PINNED_PROGRESS_SHA256
    )
    assert sha256(_PINNED_INSTANCE.read_bytes()).hexdigest() == (
        _PINNED_INSTANCE_SHA256
    )
    progress = json.loads(_PINNED_PROGRESS.read_text(encoding="utf-8"))
    problem = parse_itc2019_xml(_PINNED_INSTANCE)
    class_ids = tuple(klass.id for klass in problem.classes)

    opened = select_final_round_frontier(progress, class_ids)
    fixed = tuple(class_id for class_id in class_ids if class_id not in set(opened))

    assert len(opened) == 152
    assert len(fixed) == 1471
    assert len(opened) + len(fixed) == len(class_ids)
