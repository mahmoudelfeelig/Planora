from __future__ import annotations

import tracemalloc

import pytest
from ortools.sat.python import cp_model

from benchmarks.itc2019_decomposed import (
    _BoundedPredicateCache,
    _add_streamed_forbidden_assignments,
    _adaptive_construction_stage_cap,
    _build_compact_allowed_option_masks,
    _construction_stage_window,
    _iter_forbidden_option_pairs,
)


@pytest.mark.parametrize(
    ("budget", "base", "share", "expected"),
    (
        (120.0, 15.0, 0.20, 15.0),
        (120.0, 45.0, 0.25, 45.0),
        (600.0, 15.0, 0.20, 111.0),
        (600.0, 45.0, 0.25, 165.0),
        (2_000.0, 45.0, 0.25, 300.0),
    ),
)
def test_extended_budget_only_expands_time_above_published_condition(
    budget: float,
    base: float,
    share: float,
    expected: float,
) -> None:
    assert (
        _adaptive_construction_stage_cap(
            budget,
            base_cap_seconds=base,
            extended_budget_share=share,
        )
        == expected
    )


def test_extended_budget_cap_rejects_nonpositive_available_time() -> None:
    assert (
        _adaptive_construction_stage_cap(
            0.0,
            base_cap_seconds=45.0,
            extended_budget_share=0.25,
        )
        == 0.0
    )


@pytest.mark.parametrize(
    ("budget", "base", "share", "minimum", "expected_budget"),
    (
        (120.0, 15.0, 0.20, 2.0, 15.0),
        (120.0, 45.0, 0.25, 5.0, 45.0),
        (600.0, 15.0, 0.20, 2.0, 111.0),
        (600.0, 45.0, 0.25, 5.0, 165.0),
    ),
)
def test_construction_stage_call_site_contract_preserves_absolute_reserve(
    budget: float,
    base: float,
    share: float,
    minimum: float,
    expected_budget: float,
) -> None:
    stage_started = 1_000.0
    absolute_deadline = stage_started + budget

    stage_budget, repair_deadline = _construction_stage_window(
        total_budget_seconds=budget,
        stage_started=stage_started,
        absolute_deadline=absolute_deadline,
        base_cap_seconds=base,
        extended_budget_share=share,
        minimum_stage_seconds=minimum,
    )

    assert stage_budget == expected_budget
    assert stage_budget <= 300.0
    assert repair_deadline <= absolute_deadline - 0.05
    assert repair_deadline == stage_started + expected_budget


def test_compact_option_masks_match_independent_cartesian_oracle() -> None:
    first_size = 7
    second_size = 11

    def predicate(first_index: int, second_index: int) -> bool:
        return (first_index * 5 + second_index * 3) % 7 not in {0, 2}

    expected = tuple(
        sum(
            1 << second_index
            for second_index in range(second_size)
            if predicate(first_index, second_index)
        )
        for first_index in range(first_size)
    )

    assert _build_compact_allowed_option_masks(
        first_size,
        second_size,
        predicate,
        deadline=1.0,
        clock=lambda: 0.0,
    ) == expected


def test_compact_option_masks_do_not_retain_cartesian_cells() -> None:
    first_size = 512
    second_size = 512

    tracemalloc.start()
    try:
        rows = _build_compact_allowed_option_masks(
            first_size,
            second_size,
            lambda first, second: (first + second) % 3 == 0,
            deadline=1.0,
            clock=lambda: 0.0,
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert len(rows) == first_size
    assert all(isinstance(row, int) for row in rows)
    # A retained 512 x 512 Python bool/tuple matrix is many megabytes.  The
    # compact builder owns only 512 integer masks plus transient scalar state.
    assert peak < 1_000_000


def test_forbidden_pairs_stream_in_legacy_order_without_materializing() -> None:
    rows = (0b10101, 0b01010, 0)
    second_size = 5
    expected = [
        (first_index, second_index)
        for first_index, allowed in enumerate(rows)
        for second_index in range(second_size)
        if not allowed & (1 << second_index)
    ]

    streamed = _iter_forbidden_option_pairs(
        rows,
        second_size,
        deadline=1.0,
        clock=lambda: 0.0,
    )
    assert iter(streamed) is streamed
    assert list(streamed) == expected


def test_streamed_forbidden_table_serializes_identically_to_legacy_table() -> None:
    rows = (0b00101, 0b11100, 0b01010)
    second_size = 5
    legacy = [
        (first_index, second_index)
        for first_index, allowed in enumerate(rows)
        for second_index in range(second_size)
        if not allowed & (1 << second_index)
    ]

    def serialized_model(forbidden, *, streamed: bool) -> str:
        model = cp_model.CpModel()
        first = model.new_int_var(0, len(rows) - 1, "first")
        second = model.new_int_var(0, second_size - 1, "second")
        if streamed:
            _add_streamed_forbidden_assignments(model, (first, second), forbidden)
        else:
            model.add_forbidden_assignments((first, second), forbidden)
        return str(model.proto)

    streamed = _iter_forbidden_option_pairs(
        rows,
        second_size,
        deadline=1.0,
        clock=lambda: 0.0,
    )
    assert serialized_model(streamed, streamed=True) == serialized_model(
        legacy, streamed=False
    )


def test_streamed_empty_forbidden_table_preserves_legacy_constraint_order() -> None:
    def serialized_model(*, streamed: bool) -> str:
        model = cp_model.CpModel()
        first = model.new_int_var(0, 2, "first")
        second = model.new_int_var(0, 3, "second")
        if streamed:
            added = _add_streamed_forbidden_assignments(model, (first, second), iter(()))
            assert added is True
        else:
            model.add_forbidden_assignments((first, second), [])
        model.add(first != second)
        return str(model.proto)

    assert serialized_model(streamed=True) == serialized_model(streamed=False)


def test_predicate_cache_is_bounded_and_fail_closed() -> None:
    cache = _BoundedPredicateCache(max_entries=3)
    calls: list[int] = []

    for value in range(8):
        assert cache.resolve(value, lambda value=value: calls.append(value) or value * 2) == (
            value * 2
        )
        assert len(cache) <= 3

    assert calls == list(range(8))
    assert cache.resolve(7, lambda: pytest.fail("cached value was recomputed")) == 14

    def fail() -> bool:
        raise TimeoutError("synthetic deadline")

    with pytest.raises(TimeoutError, match="synthetic deadline"):
        cache.resolve("failure", fail)
    assert "failure" not in cache


def test_streaming_helpers_enforce_cooperative_deadlines() -> None:
    with pytest.raises(TimeoutError, match="option-mask build"):
        _build_compact_allowed_option_masks(
            2,
            2,
            lambda _first, _second: True,
            deadline=0.0,
            clock=lambda: 0.0,
        )

    with pytest.raises(TimeoutError, match="time-predicate build"):
        next(
            _iter_forbidden_option_pairs(
                (0,),
                1,
                deadline=0.0,
                clock=lambda: 0.0,
            )
        )
