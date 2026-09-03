from __future__ import annotations

import itertools
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import pytest

from benchmarks.itc2019_sameattendees_lazy_cuts import (
    LazyCutStatus,
    RelaxationSolveRequest,
    RelaxationSolveResult,
    RelaxationStatus,
    SameAttendeesAssignment,
    SameAttendeesNoGood,
    SameAttendeesRelation,
    ordered_travel_time,
    run_same_attendees_lazy_cuts,
    same_attendees_relation_violated,
)


def _assignment(
    start: int,
    end: int,
    *,
    room: str | None = "R",
    days: int = 1,
    weeks: int = 1,
) -> SameAttendeesAssignment:
    return SameAttendeesAssignment(
        start=start,
        end=end,
        days=days,
        weeks=weeks,
        room_id=room,
    )


def _independent_violation(
    relation: SameAttendeesRelation,
    candidate: Mapping[str, SameAttendeesAssignment],
    travel: Mapping[tuple[str, str], int],
) -> bool:
    first = candidate[relation.first_class_id]
    second = candidate[relation.second_class_id]
    if not (first.days & second.days) or not (first.weeks & second.weeks):
        return False
    if first.room_id is None or second.room_id is None:
        distance = 0
    elif (first.room_id, second.room_id) in travel:
        distance = travel[(first.room_id, second.room_id)]
    else:
        distance = travel.get((second.room_id, first.room_id), 0)
    return not (
        first.end + distance <= second.start or second.end + distance <= first.start
    )


@dataclass
class _ExactSyntheticBackend:
    candidates: Sequence[Mapping[str, SameAttendeesAssignment]]

    def __post_init__(self) -> None:
        self.requests: list[RelaxationSolveRequest] = []

    def __call__(self, request: RelaxationSolveRequest) -> RelaxationSolveResult:
        self.requests.append(request)
        for candidate in self.candidates:
            if not any(no_good.rejects(candidate) for no_good in request.no_goods):
                return RelaxationSolveResult(RelaxationStatus.FEASIBLE, candidate)
        return RelaxationSolveResult(RelaxationStatus.INFEASIBLE)


def _cartesian_candidates(
    domains: Mapping[str, Sequence[SameAttendeesAssignment]],
) -> tuple[dict[str, SameAttendeesAssignment], ...]:
    class_ids = tuple(sorted(domains))
    return tuple(
        dict(zip(class_ids, choices, strict=True))
        for choices in itertools.product(*(domains[class_id] for class_id in class_ids))
    )


def _eager_first_clean(
    candidates: Sequence[Mapping[str, SameAttendeesAssignment]],
    relations: Sequence[SameAttendeesRelation],
    travel: Mapping[tuple[str, str], int],
) -> Mapping[str, SameAttendeesAssignment] | None:
    return next(
        (
            candidate
            for candidate in candidates
            if all(
                not _independent_violation(relation, candidate, travel)
                for relation in relations
            )
        ),
        None,
    )


def test_first_relaxation_has_no_eager_same_attendees_cuts() -> None:
    candidate = {
        "A": _assignment(0, 2, room="RA"),
        "B": _assignment(1, 3, room="RB"),
    }
    backend = _ExactSyntheticBackend((candidate,))

    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=backend,
        max_seconds=1,
    )

    assert backend.requests[0].no_goods == ()
    assert result.status is LazyCutStatus.INFEASIBLE
    assert result.telemetry.cuts_added == 1


def test_clean_candidate_is_exposed_only_after_every_relation_is_checked() -> None:
    relations = (
        SameAttendeesRelation("A", "B"),
        SameAttendeesRelation("B", "C"),
        SameAttendeesRelation("A", "B"),
    )
    candidate = {
        "A": _assignment(0, 1),
        "B": _assignment(2, 3),
        "C": _assignment(4, 5),
    }
    checked: list[SameAttendeesRelation] = []

    def validator(
        relation: SameAttendeesRelation,
        value: Mapping[str, SameAttendeesAssignment],
        travel: Mapping[tuple[str, str], int],
    ) -> bool:
        checked.append(relation)
        return _independent_violation(relation, value, travel)

    result = run_same_attendees_lazy_cuts(
        relations=relations,
        travel={},
        solve_relaxation=_ExactSyntheticBackend((candidate,)),
        validator=validator,
        max_seconds=1,
    )

    assert result.status is LazyCutStatus.SUCCESS
    assert checked == list(relations)
    assert result.telemetry.relations_checked == len(relations)
    assert dict(result.candidate or ()) == candidate


def test_ordered_asymmetric_travel_preserves_reversed_relation_semantics() -> None:
    candidate = {
        "A": _assignment(0, 2, room="RA"),
        "B": _assignment(3, 5, room="RB"),
    }
    travel = {("RA", "RB"): 1, ("RB", "RA"): 5}

    assert not same_attendees_relation_violated(
        SameAttendeesRelation("A", "B"), candidate, travel
    )
    assert same_attendees_relation_violated(
        SameAttendeesRelation("B", "A"), candidate, travel
    )
    assert ordered_travel_time("RA", "RB", travel) == 1
    assert ordered_travel_time("RB", "RA", travel) == 5


def test_missing_direct_travel_uses_reverse_fallback() -> None:
    travel = {("RB", "RA"): 7}

    assert ordered_travel_time("RA", "RB", travel) == 7
    assert ordered_travel_time("RB", "RA", travel) == 7
    assert ordered_travel_time("RA", "RC", travel) == 0


def test_roomless_classes_have_zero_travel() -> None:
    candidate = {
        "A": _assignment(0, 2, room=None),
        "B": _assignment(2, 4, room="RB"),
    }
    relation = SameAttendeesRelation("A", "B")

    assert ordered_travel_time(None, "RB", {("RA", "RB"): 99}) == 0
    assert not same_attendees_relation_violated(relation, candidate, {("RA", "RB"): 99})


def test_disjoint_day_or_week_masks_are_safe() -> None:
    relation = SameAttendeesRelation("A", "B")
    overlap_in_time = {
        "A": _assignment(0, 4, days=1, weeks=1),
        "B": _assignment(1, 3, days=2, weeks=1),
    }
    different_week = {
        "A": _assignment(0, 4, days=1, weeks=1),
        "B": _assignment(1, 3, days=1, weeks=2),
    }

    assert not same_attendees_relation_violated(relation, overlap_in_time, {})
    assert not same_attendees_relation_violated(relation, different_week, {})


def test_repeated_and_reversed_relations_deduplicate_one_concrete_no_good() -> None:
    candidate = {
        "A": _assignment(0, 3, room="RA"),
        "B": _assignment(1, 2, room="RB"),
    }
    relations = (
        SameAttendeesRelation("A", "B"),
        SameAttendeesRelation("A", "B"),
        SameAttendeesRelation("B", "A"),
    )

    result = run_same_attendees_lazy_cuts(
        relations=relations,
        travel={("RA", "RB"): 1, ("RB", "RA"): 2},
        solve_relaxation=_ExactSyntheticBackend((candidate,)),
        max_seconds=1,
    )

    assert result.status is LazyCutStatus.INFEASIBLE
    assert result.telemetry.violations_found == 3
    assert result.telemetry.cuts_added == 1
    assert result.telemetry.duplicate_cuts == 2
    assert len(result.no_goods) == 1


def test_cycles_and_multiple_cut_rounds_converge_to_clean_candidate() -> None:
    relations = (
        SameAttendeesRelation("A", "B"),
        SameAttendeesRelation("B", "C"),
        SameAttendeesRelation("C", "A"),
    )
    candidates = (
        {
            "A": _assignment(0, 3),
            "B": _assignment(1, 2),
            "C": _assignment(4, 5),
        },
        {
            "A": _assignment(0, 1),
            "B": _assignment(2, 5),
            "C": _assignment(3, 4),
        },
        {
            "A": _assignment(0, 1),
            "B": _assignment(2, 3),
            "C": _assignment(4, 5),
        },
    )
    backend = _ExactSyntheticBackend(candidates)

    result = run_same_attendees_lazy_cuts(
        relations=relations,
        travel={},
        solve_relaxation=backend,
        max_seconds=1,
    )

    assert result.status is LazyCutStatus.SUCCESS
    assert dict(result.candidate or ()) == candidates[-1]
    assert result.telemetry.solver_calls == 3
    assert result.telemetry.cuts_added == 2
    assert tuple(len(request.no_goods) for request in backend.requests) == (0, 1, 2)


def test_cut_order_is_deterministic_and_canonical() -> None:
    candidate = {
        "A": _assignment(0, 4, room="RA"),
        "B": _assignment(1, 3, room="RB"),
        "C": _assignment(2, 5, room="RC"),
    }
    relations = (
        SameAttendeesRelation("C", "B"),
        SameAttendeesRelation("A", "C"),
        SameAttendeesRelation("B", "A"),
    )
    observed: list[SameAttendeesNoGood] = []

    first = run_same_attendees_lazy_cuts(
        relations=relations,
        travel={},
        solve_relaxation=_ExactSyntheticBackend((candidate,)),
        add_no_good=observed.append,
        max_seconds=1,
    )
    second = run_same_attendees_lazy_cuts(
        relations=relations,
        travel={},
        solve_relaxation=_ExactSyntheticBackend((candidate,)),
        max_seconds=1,
    )

    assert tuple(no_good.stable_key() for no_good in observed) == tuple(
        sorted(no_good.stable_key() for no_good in observed)
    )
    assert first.no_goods == second.no_goods
    assert [tuple(class_id for class_id, _ in cut.members) for cut in observed] == [
        ("A", "B"),
        ("A", "C"),
        ("B", "C"),
    ]


@pytest.mark.parametrize(
    ("solver_status", "expected_status"),
    (
        (RelaxationStatus.UNKNOWN, LazyCutStatus.UNKNOWN),
        (RelaxationStatus.INFEASIBLE, LazyCutStatus.INFEASIBLE),
    ),
)
def test_unknown_and_infeasible_are_propagated_without_candidate(
    solver_status: RelaxationStatus,
    expected_status: LazyCutStatus,
) -> None:
    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=lambda request: RelaxationSolveResult(solver_status),
        max_seconds=1,
    )

    assert result.status is expected_status
    assert result.candidate is None
    assert result.no_goods == ()


def test_noncandidate_status_with_candidate_fails_closed() -> None:
    candidate = {"A": _assignment(0, 1), "B": _assignment(2, 3)}

    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=lambda request: RelaxationSolveResult(
            RelaxationStatus.UNKNOWN, candidate
        ),
        max_seconds=1,
    )

    assert result.status is LazyCutStatus.BACKEND_CONTRACT_ERROR
    assert result.candidate is None


@pytest.mark.parametrize(
    ("solver_status", "candidate"),
    (
        ("FEASIBLE", {"A": _assignment(0, 1), "B": _assignment(2, 3)}),
        ("UNKNOWN", None),
    ),
)
def test_string_like_solver_status_fails_closed_without_crashing(
    solver_status: str,
    candidate: Mapping[str, SameAttendeesAssignment] | None,
) -> None:
    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=lambda request: RelaxationSolveResult(
            solver_status,  # type: ignore[arg-type]
            candidate,
        ),
        max_seconds=1,
    )

    assert result.status is LazyCutStatus.BACKEND_CONTRACT_ERROR
    assert result.candidate is None
    assert "status" in result.detail
    assert result.telemetry.solver_calls == 1


@pytest.mark.parametrize(
    ("candidate", "detail"),
    (
        (None, "mapping"),
        ({"A": _assignment(0, 1)}, "missing required classes"),
        ({"A": _assignment(0, 1), "B": object()}, "wrong type"),
        ({1: _assignment(0, 1), "A": _assignment(2, 3)}, "class IDs"),
    ),
)
def test_malformed_candidates_are_rejected_without_exposure(
    candidate: object,
    detail: str,
) -> None:
    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=lambda request: RelaxationSolveResult(
            RelaxationStatus.FEASIBLE,
            candidate,  # type: ignore[arg-type]
        ),
        max_seconds=1,
    )

    assert result.status is LazyCutStatus.MALFORMED_CANDIDATE
    assert result.candidate is None
    assert detail in result.detail
    assert result.telemetry.relations_checked == 0


def test_validator_exception_fails_closed_without_adding_partial_cuts() -> None:
    candidate = {
        "A": _assignment(0, 3),
        "B": _assignment(1, 2),
        "C": _assignment(4, 5),
    }
    calls = 0

    def validator(
        relation: SameAttendeesRelation,
        value: Mapping[str, SameAttendeesAssignment],
        travel: Mapping[tuple[str, str], int],
    ) -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("independent validation failed")
        return _independent_violation(relation, value, travel)

    result = run_same_attendees_lazy_cuts(
        relations=(
            SameAttendeesRelation("A", "B"),
            SameAttendeesRelation("B", "C"),
        ),
        travel={},
        solve_relaxation=_ExactSyntheticBackend((candidate,)),
        validator=validator,
        max_seconds=1,
    )

    assert result.status is LazyCutStatus.VALIDATOR_ERROR
    assert result.candidate is None
    assert result.no_goods == ()
    assert result.telemetry.relations_checked == 1
    assert result.telemetry.violations_found == 1


def test_non_boolean_validator_result_fails_closed() -> None:
    candidate = {"A": _assignment(0, 1), "B": _assignment(2, 3)}

    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=_ExactSyntheticBackend((candidate,)),
        validator=lambda relation, value, travel: 0,  # type: ignore[arg-type,return-value]
        max_seconds=1,
    )

    assert result.status is LazyCutStatus.VALIDATOR_ERROR
    assert result.candidate is None


def test_solver_exception_fails_closed() -> None:
    def fail(request: RelaxationSolveRequest) -> RelaxationSolveResult:
        raise RuntimeError("solver boundary failed")

    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=fail,
        max_seconds=1,
    )

    assert result.status is LazyCutStatus.SOLVER_ERROR
    assert result.candidate is None
    assert "solver boundary failed" in result.detail
    assert result.telemetry.solver_calls == 1


def test_cut_sink_exception_fails_closed_before_cut_publication() -> None:
    candidate = {"A": _assignment(0, 3), "B": _assignment(1, 2)}

    def fail(no_good: SameAttendeesNoGood) -> None:
        raise RuntimeError("incremental cut failed")

    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=_ExactSyntheticBackend((candidate,)),
        add_no_good=fail,
        max_seconds=1,
    )

    assert result.status is LazyCutStatus.CUT_SINK_ERROR
    assert result.candidate is None
    assert result.no_goods == ()


def test_backend_returning_candidate_rejected_by_existing_cut_fails_closed() -> None:
    candidate = {"A": _assignment(0, 3), "B": _assignment(1, 2)}

    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=lambda request: RelaxationSolveResult(
            RelaxationStatus.FEASIBLE, candidate
        ),
        max_seconds=1,
    )

    assert result.status is LazyCutStatus.BACKEND_CONTRACT_ERROR
    assert result.candidate is None
    assert result.telemetry.solver_calls == 2
    assert len(result.no_goods) == 1


def test_iteration_limit_is_a_non_success_result() -> None:
    candidate = {"A": _assignment(0, 3), "B": _assignment(1, 2)}

    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=_ExactSyntheticBackend((candidate,)),
        max_seconds=1,
        max_iterations=1,
    )

    assert result.status is LazyCutStatus.ITERATION_LIMIT
    assert result.candidate is None
    assert result.telemetry.cuts_added == 1


def test_cancellation_before_first_solve() -> None:
    called = False

    def solve(request: RelaxationSolveRequest) -> RelaxationSolveResult:
        nonlocal called
        called = True
        return RelaxationSolveResult(RelaxationStatus.UNKNOWN)

    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=solve,
        cancellation_requested=lambda: True,
        max_seconds=1,
    )

    assert result.status is LazyCutStatus.CANCELLED
    assert not called
    assert result.candidate is None


def test_cancellation_during_validation_stops_without_partial_cut_commit() -> None:
    candidate = {
        "A": _assignment(0, 3),
        "B": _assignment(1, 2),
        "C": _assignment(4, 5),
    }
    state = {"cancelled": False}

    def validator(
        relation: SameAttendeesRelation,
        value: Mapping[str, SameAttendeesAssignment],
        travel: Mapping[tuple[str, str], int],
    ) -> bool:
        state["cancelled"] = True
        return _independent_violation(relation, value, travel)

    result = run_same_attendees_lazy_cuts(
        relations=(
            SameAttendeesRelation("A", "B"),
            SameAttendeesRelation("B", "C"),
        ),
        travel={},
        solve_relaxation=_ExactSyntheticBackend((candidate,)),
        cancellation_requested=lambda: state["cancelled"],
        validator=validator,
        max_seconds=1,
    )

    assert result.status is LazyCutStatus.CANCELLED
    assert result.telemetry.relations_checked == 1
    assert result.telemetry.violations_found == 1
    assert result.no_goods == ()


def test_cancellation_callback_exception_fails_closed() -> None:
    def fail() -> bool:
        raise RuntimeError("cancel probe failed")

    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=lambda request: RelaxationSolveResult(
            RelaxationStatus.UNKNOWN
        ),
        cancellation_requested=fail,
        max_seconds=1,
    )

    assert result.status is LazyCutStatus.BACKEND_CONTRACT_ERROR
    assert "cancel probe failed" in result.detail


class _MutableClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def test_malformed_solver_status_at_deadline_fails_closed_without_crashing() -> None:
    clock = _MutableClock()
    candidate = {"A": _assignment(0, 1), "B": _assignment(2, 3)}

    def solve(request: RelaxationSolveRequest) -> RelaxationSolveResult:
        clock.value = 5.0
        return RelaxationSolveResult(
            "FEASIBLE",  # type: ignore[arg-type]
            candidate,
        )

    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=solve,
        max_seconds=5,
        clock=clock,
    )

    assert result.status is LazyCutStatus.BACKEND_CONTRACT_ERROR
    assert result.candidate is None
    assert "status" in result.detail
    assert result.telemetry.solver_calls == 1


def test_one_absolute_deadline_covers_solver_execution() -> None:
    clock = _MutableClock()

    def solve(request: RelaxationSolveRequest) -> RelaxationSolveResult:
        assert request.absolute_deadline == 5.0
        clock.value = 5.0
        return RelaxationSolveResult(
            RelaxationStatus.FEASIBLE,
            {"A": _assignment(0, 1), "B": _assignment(2, 3)},
        )

    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=solve,
        max_seconds=5,
        clock=clock,
    )

    assert result.status is LazyCutStatus.DEADLINE_EXPIRED
    assert result.candidate is None
    assert result.telemetry.solve_seconds == 5.0


def test_one_absolute_deadline_covers_all_relation_validation() -> None:
    clock = _MutableClock()
    candidate = {
        "A": _assignment(0, 1),
        "B": _assignment(2, 3),
        "C": _assignment(4, 5),
    }

    def validator(
        relation: SameAttendeesRelation,
        value: Mapping[str, SameAttendeesAssignment],
        travel: Mapping[tuple[str, str], int],
    ) -> bool:
        clock.value = 5.0
        return False

    result = run_same_attendees_lazy_cuts(
        relations=(
            SameAttendeesRelation("A", "B"),
            SameAttendeesRelation("B", "C"),
        ),
        travel={},
        solve_relaxation=_ExactSyntheticBackend((candidate,)),
        validator=validator,
        max_seconds=5,
        clock=clock,
    )

    assert result.status is LazyCutStatus.DEADLINE_EXPIRED
    assert result.candidate is None
    assert result.telemetry.relations_checked == 1


def test_final_result_construction_cannot_race_past_absolute_deadline() -> None:
    armed = False
    reads_after_validation = 0

    def clock() -> float:
        nonlocal reads_after_validation
        if not armed:
            return 0.0
        reads_after_validation += 1
        if reads_after_validation >= 3:
            return 5.0
        return 4.999

    def validator(
        relation: SameAttendeesRelation,
        value: Mapping[str, SameAttendeesAssignment],
        travel: Mapping[tuple[str, str], int],
    ) -> bool:
        nonlocal armed
        armed = True
        return False

    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=_ExactSyntheticBackend(
            ({"A": _assignment(0, 1), "B": _assignment(2, 3)},)
        ),
        validator=validator,
        max_seconds=5,
        clock=clock,
    )

    assert result.status is LazyCutStatus.DEADLINE_EXPIRED
    assert result.candidate is None
    assert result.telemetry.elapsed_seconds == 5.0


def test_phase_and_cut_telemetry_is_auditable() -> None:
    clock = _MutableClock()
    candidates = (
        {"A": _assignment(0, 3), "B": _assignment(1, 2)},
        {"A": _assignment(0, 1), "B": _assignment(2, 3)},
    )
    backend = _ExactSyntheticBackend(candidates)

    def solve(request: RelaxationSolveRequest) -> RelaxationSolveResult:
        clock.value += 1.0
        return backend(request)

    def validator(
        relation: SameAttendeesRelation,
        value: Mapping[str, SameAttendeesAssignment],
        travel: Mapping[tuple[str, str], int],
    ) -> bool:
        clock.value += 0.25
        return _independent_violation(relation, value, travel)

    def sink(no_good: SameAttendeesNoGood) -> None:
        clock.value += 0.5

    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=solve,
        validator=validator,
        add_no_good=sink,
        max_seconds=10,
        clock=clock,
    )

    assert result.status is LazyCutStatus.SUCCESS
    assert result.telemetry.elapsed_seconds == 3.0
    assert result.telemetry.solve_seconds == 2.0
    assert result.telemetry.validation_seconds == 0.5
    assert result.telemetry.cut_seconds == 0.5
    assert result.telemetry.candidate_check_seconds == 0.0
    assert result.telemetry.solver_calls == 2
    assert result.telemetry.candidates_validated == 2
    assert result.telemetry.relations_checked == 2
    assert result.telemetry.violations_found == 1
    assert result.telemetry.cuts_added == 1
    assert len(result.telemetry.rounds) == 2
    assert all(round_.candidate_sha256 for round_ in result.telemetry.rounds)


def test_cuts_scale_with_encountered_violations_not_room_cartesian_size() -> None:
    first_room_domain = tuple(f"A{index:02d}" for index in range(50))
    second_room_domain = tuple(f"B{index:02d}" for index in range(50))
    eager_room_pair_cartesian_size = len(first_room_domain) * len(second_room_domain)
    candidates = (
        {
            "A": _assignment(0, 4, room=first_room_domain[0]),
            "B": _assignment(1, 3, room=second_room_domain[0]),
        },
        {
            "A": _assignment(0, 4, room=first_room_domain[-1]),
            "B": _assignment(2, 3, room=second_room_domain[-1]),
        },
        {
            "A": _assignment(0, 1, room=first_room_domain[25]),
            "B": _assignment(2, 3, room=second_room_domain[25]),
        },
    )
    backend = _ExactSyntheticBackend(candidates)

    result = run_same_attendees_lazy_cuts(
        relations=(SameAttendeesRelation("A", "B"),),
        travel={},
        solve_relaxation=backend,
        max_seconds=1,
    )

    assert result.status is LazyCutStatus.SUCCESS
    assert eager_room_pair_cartesian_size == 2_500
    assert result.telemetry.violations_found == 2
    assert result.telemetry.cuts_added == 2
    assert result.telemetry.cuts_added / eager_room_pair_cartesian_size == 0.0008
    assert tuple(len(request.no_goods) for request in backend.requests) == (0, 1, 2)


def _random_assignment(
    rng: random.Random, room_ids: tuple[str, ...]
) -> SameAttendeesAssignment:
    start = rng.randrange(0, 7)
    return _assignment(
        start,
        start + rng.randrange(1, 4),
        room=rng.choice((*room_ids, None)),
        days=1 << rng.randrange(0, 3),
        weeks=1 << rng.randrange(0, 2),
    )


def _random_relations(
    rng: random.Random, class_ids: tuple[str, ...]
) -> tuple[SameAttendeesRelation, ...]:
    ordered_pairs = [pair for pair in itertools.permutations(class_ids, 2)]
    count = rng.randrange(1, min(6, len(ordered_pairs)) + 1)
    relations = [
        SameAttendeesRelation(*rng.choice(ordered_pairs)) for _ in range(count)
    ]
    if rng.random() < 0.4:
        relations.append(relations[0])
    return tuple(relations)


@pytest.mark.parametrize("seed", range(80))
def test_randomized_small_instances_match_eager_exhaustive_oracle(seed: int) -> None:
    rng = random.Random(seed)
    class_ids = tuple(chr(ord("A") + index) for index in range(rng.randrange(2, 4)))
    room_ids = ("R0", "R1", "R2")
    domains = {
        class_id: tuple(
            _random_assignment(rng, room_ids) for _ in range(rng.randrange(2, 4))
        )
        for class_id in class_ids
    }
    candidates = _cartesian_candidates(domains)
    relations = _random_relations(rng, class_ids)
    travel = {
        pair: rng.randrange(0, 4)
        for pair in itertools.permutations(room_ids, 2)
        if rng.random() < 0.65
    }
    eager = _eager_first_clean(candidates, relations, travel)
    backend = _ExactSyntheticBackend(candidates)

    result = run_same_attendees_lazy_cuts(
        relations=relations,
        travel=travel,
        solve_relaxation=backend,
        max_seconds=2,
    )

    if eager is None:
        assert result.status is LazyCutStatus.INFEASIBLE
        assert result.candidate is None
    else:
        assert result.status is LazyCutStatus.SUCCESS
        assert dict(result.candidate or ()) == eager
        assert all(
            not _independent_violation(relation, eager, travel)
            for relation in relations
        )


@pytest.mark.parametrize(
    "factory",
    (
        lambda: SameAttendeesAssignment(0, 1, 0, 1, "R"),
        lambda: SameAttendeesAssignment(0, 1, 1, 0, "R"),
        lambda: SameAttendeesAssignment(1, 1, 1, 1, "R"),
        lambda: SameAttendeesAssignment(True, 1, 1, 1, "R"),
        lambda: SameAttendeesRelation("A", "A"),
    ),
)
def test_invalid_static_values_are_rejected(factory: Callable[[], object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


@pytest.mark.parametrize("bad_travel", ({("R1", "R2"): -1}, {("R1", "R2"): True}))
def test_invalid_travel_values_are_rejected(
    bad_travel: Mapping[tuple[str, str], int],
) -> None:
    with pytest.raises(TypeError):
        run_same_attendees_lazy_cuts(
            relations=(SameAttendeesRelation("A", "B"),),
            travel=bad_travel,
            solve_relaxation=lambda request: RelaxationSolveResult(
                RelaxationStatus.UNKNOWN
            ),
            max_seconds=1,
        )
