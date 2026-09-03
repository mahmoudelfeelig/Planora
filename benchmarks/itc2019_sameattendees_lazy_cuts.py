"""Exact lazy-cut controller for required ITC-2019 SameAttendees relations.

This module is intentionally independent of the production ITC-2019 solver.  It
contains no parser, model builder, corpus access, or solver dependency.  A future
integration can inject an exact relaxation solver and, optionally, an incremental
cut sink without importing this prototype from a currently sealed solve path.

The controller starts with no SameAttendees room-pair cuts.  After every solver
candidate it validates every required ordered relation with a small reference
validator.  Concrete violating assignments become canonical exact no-goods.  A
candidate is returned only after a complete clean validation pass.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class RelaxationStatus(str, Enum):
    """Terminal status reported by the injected exact relaxation solver."""

    FEASIBLE = "FEASIBLE"
    OPTIMAL = "OPTIMAL"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"


class LazyCutStatus(str, Enum):
    """Fail-closed result of the lazy-cut controller."""

    SUCCESS = "SUCCESS"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"
    DEADLINE_EXPIRED = "DEADLINE_EXPIRED"
    ITERATION_LIMIT = "ITERATION_LIMIT"
    MALFORMED_CANDIDATE = "MALFORMED_CANDIDATE"
    SOLVER_ERROR = "SOLVER_ERROR"
    VALIDATOR_ERROR = "VALIDATOR_ERROR"
    CUT_SINK_ERROR = "CUT_SINK_ERROR"
    BACKEND_CONTRACT_ERROR = "BACKEND_CONTRACT_ERROR"


@dataclass(frozen=True, slots=True)
class SameAttendeesAssignment:
    """One concrete time and room choice for a class.

    ``days`` and ``weeks`` are non-empty bit masks.  ``room_id=None`` represents
    a roomless class and has zero travel time to or from every room.
    """

    start: int
    end: int
    days: int
    weeks: int
    room_id: str | None

    def __post_init__(self) -> None:
        for label, value in (
            ("start", self.start),
            ("end", self.end),
            ("days", self.days),
            ("weeks", self.weeks),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{label} must be an integer")
        if self.start < 0:
            raise ValueError("start must be non-negative")
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        if self.days <= 0 or self.weeks <= 0:
            raise ValueError("days and weeks must be non-empty bit masks")
        if self.room_id is not None and (
            not isinstance(self.room_id, str) or not self.room_id
        ):
            raise TypeError("room_id must be a non-empty string or None")

    def audit_tuple(self) -> tuple[int, int, int, int, str]:
        """Return a total-orderable representation used in hashes and cuts."""

        return (
            self.start,
            self.end,
            self.days,
            self.weeks,
            "" if self.room_id is None else self.room_id,
        )


@dataclass(frozen=True, slots=True)
class SameAttendeesRelation:
    """One required ordered SameAttendees relation."""

    first_class_id: str
    second_class_id: str

    def __post_init__(self) -> None:
        for label, value in (
            ("first_class_id", self.first_class_id),
            ("second_class_id", self.second_class_id),
        ):
            if not isinstance(value, str) or not value:
                raise TypeError(f"{label} must be a non-empty string")
        if self.first_class_id == self.second_class_id:
            raise ValueError("a SameAttendees relation requires two classes")


@dataclass(frozen=True, slots=True)
class SameAttendeesNoGood:
    """An exact no-good for one concrete pair of class assignments.

    Members are canonicalized by class ID.  Relation identity is deliberately
    absent: repeated and reversed relations that reject the same concrete pair
    share one logically sufficient no-good.
    """

    members: tuple[
        tuple[str, SameAttendeesAssignment], tuple[str, SameAttendeesAssignment]
    ]

    @classmethod
    def from_candidate(
        cls,
        relation: SameAttendeesRelation,
        candidate: Mapping[str, SameAttendeesAssignment],
    ) -> SameAttendeesNoGood:
        first = (relation.first_class_id, candidate[relation.first_class_id])
        second = (relation.second_class_id, candidate[relation.second_class_id])
        members = tuple(sorted((first, second), key=lambda item: item[0]))
        return cls(members=(members[0], members[1]))

    def stable_key(self) -> tuple[tuple[str, tuple[int, int, int, int, str]], ...]:
        return tuple(
            (class_id, assignment.audit_tuple())
            for class_id, assignment in self.members
        )

    def rejects(self, candidate: Mapping[str, SameAttendeesAssignment]) -> bool:
        """Return whether the candidate contains this exact forbidden pair."""

        return all(
            candidate.get(class_id) == assignment
            for class_id, assignment in self.members
        )


@dataclass(frozen=True, slots=True)
class RelaxationSolveRequest:
    """Immutable input supplied to one exact relaxation solve."""

    iteration: int
    absolute_deadline: float
    no_goods: tuple[SameAttendeesNoGood, ...]


@dataclass(frozen=True, slots=True)
class RelaxationSolveResult:
    """Result returned by an injected relaxation solver."""

    status: RelaxationStatus
    candidate: Mapping[str, SameAttendeesAssignment] | None = None


class RelaxationSolver(Protocol):
    def __call__(self, request: RelaxationSolveRequest) -> RelaxationSolveResult: ...


class CutSink(Protocol):
    def __call__(self, no_good: SameAttendeesNoGood) -> None: ...


class RelationValidator(Protocol):
    def __call__(
        self,
        relation: SameAttendeesRelation,
        candidate: Mapping[str, SameAttendeesAssignment],
        travel: Mapping[tuple[str, str], int],
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class LazyCutRoundTelemetry:
    iteration: int
    solver_status: str
    candidate_sha256: str | None
    relations_checked: int
    violations_found: int
    cuts_added: int
    duplicate_cuts: int
    solve_seconds: float
    candidate_check_seconds: float
    validation_seconds: float
    cut_seconds: float


@dataclass(frozen=True, slots=True)
class LazyCutTelemetry:
    absolute_deadline: float
    elapsed_seconds: float
    solver_calls: int
    candidates_validated: int
    relations_checked: int
    violations_found: int
    cuts_added: int
    duplicate_cuts: int
    solve_seconds: float
    candidate_check_seconds: float
    validation_seconds: float
    cut_seconds: float
    rounds: tuple[LazyCutRoundTelemetry, ...]


@dataclass(frozen=True, slots=True)
class LazyCutResult:
    status: LazyCutStatus
    candidate: tuple[tuple[str, SameAttendeesAssignment], ...] | None
    no_goods: tuple[SameAttendeesNoGood, ...]
    telemetry: LazyCutTelemetry
    detail: str

    @property
    def succeeded(self) -> bool:
        return self.status is LazyCutStatus.SUCCESS


@dataclass(slots=True)
class _Totals:
    solver_calls: int = 0
    candidates_validated: int = 0
    relations_checked: int = 0
    violations_found: int = 0
    cuts_added: int = 0
    duplicate_cuts: int = 0
    solve_seconds: float = 0.0
    candidate_check_seconds: float = 0.0
    validation_seconds: float = 0.0
    cut_seconds: float = 0.0


class _AuditedClock:
    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._last: float | None = None

    def now(self) -> float:
        value = self._clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("clock must return a finite number")
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("clock must return a finite number")
        if self._last is not None and value < self._last:
            raise ValueError("clock moved backwards")
        self._last = value
        return value


def ordered_travel_time(
    origin_room_id: str | None,
    destination_room_id: str | None,
    travel: Mapping[tuple[str, str], int],
) -> int:
    """Return ITC-2019 ordered travel with reverse-key fallback.

    A direct ordered value wins.  When it is absent, the reverse value is used;
    otherwise travel is zero.  Roomless classes always have zero travel.
    """

    if origin_room_id is None or destination_room_id is None:
        return 0
    direct = travel.get((origin_room_id, destination_room_id))
    if direct is not None:
        return direct
    return travel.get((destination_room_id, origin_room_id), 0)


def same_attendees_relation_violated(
    relation: SameAttendeesRelation,
    candidate: Mapping[str, SameAttendeesAssignment],
    travel: Mapping[tuple[str, str], int],
) -> bool:
    """Independently evaluate one required ordered SameAttendees relation."""

    first = candidate[relation.first_class_id]
    second = candidate[relation.second_class_id]
    if first.days & second.days == 0 or first.weeks & second.weeks == 0:
        return False
    distance = ordered_travel_time(first.room_id, second.room_id, travel)
    forward_safe = first.end + distance <= second.start
    backward_safe = second.end + distance <= first.start
    return not (forward_safe or backward_safe)


def _validate_static_inputs(
    relations: Sequence[SameAttendeesRelation],
    travel: Mapping[tuple[str, str], int],
    max_seconds: float,
    max_iterations: int,
) -> tuple[tuple[SameAttendeesRelation, ...], dict[tuple[str, str], int]]:
    if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)):
        raise TypeError("max_seconds must be a finite positive number")
    if not math.isfinite(float(max_seconds)) or max_seconds <= 0:
        raise ValueError("max_seconds must be a finite positive number")
    if isinstance(max_iterations, bool) or not isinstance(max_iterations, int):
        raise TypeError("max_iterations must be a positive integer")
    if max_iterations <= 0:
        raise ValueError("max_iterations must be a positive integer")

    frozen_relations = tuple(relations)
    if not frozen_relations:
        raise ValueError("at least one SameAttendees relation is required")
    if not all(
        isinstance(relation, SameAttendeesRelation) for relation in frozen_relations
    ):
        raise TypeError("relations must contain SameAttendeesRelation values")

    frozen_travel: dict[tuple[str, str], int] = {}
    for key, value in travel.items():
        if (
            not isinstance(key, tuple)
            or len(key) != 2
            or not all(isinstance(part, str) and part for part in key)
        ):
            raise TypeError("travel keys must be pairs of non-empty room IDs")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TypeError("travel values must be non-negative integers")
        frozen_travel[key] = value
    return frozen_relations, frozen_travel


def _freeze_candidate(
    candidate: object,
    required_class_ids: frozenset[str],
) -> tuple[dict[str, SameAttendeesAssignment] | None, str | None]:
    if not isinstance(candidate, Mapping):
        return None, "solver candidate must be a mapping"
    frozen: dict[str, SameAttendeesAssignment] = {}
    for class_id, assignment in candidate.items():
        if not isinstance(class_id, str) or not class_id:
            return None, "candidate class IDs must be non-empty strings"
        if not isinstance(assignment, SameAttendeesAssignment):
            return None, f"candidate assignment for {class_id!r} has the wrong type"
        frozen[class_id] = assignment
    missing = sorted(required_class_ids.difference(frozen))
    if missing:
        return None, f"candidate is missing required classes: {', '.join(missing)}"
    return frozen, None


def _candidate_hash(candidate: Mapping[str, SameAttendeesAssignment]) -> str:
    rows = [
        [class_id, *candidate[class_id].audit_tuple()] for class_id in sorted(candidate)
    ]
    payload = json.dumps(rows, ensure_ascii=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _call_cancelled(
    cancellation_requested: Callable[[], bool],
) -> tuple[bool, str | None]:
    try:
        value = cancellation_requested()
    except Exception as exc:  # fail closed at an injected trust boundary
        return False, f"cancellation callback raised {type(exc).__name__}: {exc}"
    if type(value) is not bool:
        return False, "cancellation callback must return bool"
    return value, None


def run_same_attendees_lazy_cuts(
    *,
    relations: Sequence[SameAttendeesRelation],
    travel: Mapping[tuple[str, str], int],
    solve_relaxation: RelaxationSolver,
    max_seconds: float,
    add_no_good: CutSink | None = None,
    cancellation_requested: Callable[[], bool] | None = None,
    validator: RelationValidator = same_attendees_relation_violated,
    clock: Callable[[], float] = time.monotonic,
    max_iterations: int = 100_000,
) -> LazyCutResult:
    """Run exact solve--validate--cut under one absolute deadline.

    ``solve_relaxation`` must solve its requested relaxation exactly enough to
    report FEASIBLE/OPTIMAL, INFEASIBLE, or UNKNOWN.  Every request contains the
    complete canonical no-good prefix, so an incremental backend may ignore
    ``add_no_good`` while a rebuild backend can consume ``request.no_goods``.

    The function never returns a candidate for any non-success status.  A caller
    should publish only the candidate from a ``SUCCESS`` result.
    """

    frozen_relations, frozen_travel = _validate_static_inputs(
        relations, travel, max_seconds, max_iterations
    )
    required_class_ids = frozenset(
        class_id
        for relation in frozen_relations
        for class_id in (relation.first_class_id, relation.second_class_id)
    )
    cancel = cancellation_requested or (lambda: False)
    audited_clock = _AuditedClock(clock)
    started = audited_clock.now()
    deadline = started + float(max_seconds)
    totals = _Totals()
    rounds: list[LazyCutRoundTelemetry] = []
    no_goods: list[SameAttendeesNoGood] = []
    no_good_keys: set[tuple[tuple[str, tuple[int, int, int, int, str]], ...]] = set()

    def finish(
        status: LazyCutStatus,
        detail: str,
        *,
        candidate: Mapping[str, SameAttendeesAssignment] | None = None,
    ) -> LazyCutResult:
        exposed_candidate = None
        if status is LazyCutStatus.SUCCESS and candidate is not None:
            exposed_candidate = tuple(
                (key, candidate[key]) for key in sorted(candidate)
            )
        finished = audited_clock.now()
        if status is LazyCutStatus.SUCCESS and finished >= deadline:
            status = LazyCutStatus.DEADLINE_EXPIRED
            detail = "absolute deadline expired during final result construction"
            exposed_candidate = None
        telemetry = LazyCutTelemetry(
            absolute_deadline=deadline,
            elapsed_seconds=finished - started,
            solver_calls=totals.solver_calls,
            candidates_validated=totals.candidates_validated,
            relations_checked=totals.relations_checked,
            violations_found=totals.violations_found,
            cuts_added=totals.cuts_added,
            duplicate_cuts=totals.duplicate_cuts,
            solve_seconds=totals.solve_seconds,
            candidate_check_seconds=totals.candidate_check_seconds,
            validation_seconds=totals.validation_seconds,
            cut_seconds=totals.cut_seconds,
            rounds=tuple(rounds),
        )
        return LazyCutResult(
            status=status,
            candidate=exposed_candidate,
            no_goods=tuple(no_goods),
            telemetry=telemetry,
            detail=detail,
        )

    def stop_status() -> tuple[LazyCutStatus | None, str | None]:
        cancelled, cancel_error = _call_cancelled(cancel)
        if cancel_error is not None:
            return LazyCutStatus.BACKEND_CONTRACT_ERROR, cancel_error
        if cancelled:
            return LazyCutStatus.CANCELLED, "cancellation requested"
        if audited_clock.now() >= deadline:
            return LazyCutStatus.DEADLINE_EXPIRED, "absolute deadline expired"
        return None, None

    for iteration in range(1, max_iterations + 1):
        stopped, detail = stop_status()
        if stopped is not None:
            return finish(stopped, detail or stopped.value)

        request = RelaxationSolveRequest(
            iteration=iteration,
            absolute_deadline=deadline,
            no_goods=tuple(no_goods),
        )
        solve_started = audited_clock.now()
        totals.solver_calls += 1
        try:
            solve_result = solve_relaxation(request)
        except Exception as exc:  # fail closed at the solver boundary
            totals.solve_seconds += audited_clock.now() - solve_started
            return finish(
                LazyCutStatus.SOLVER_ERROR,
                f"relaxation solver raised {type(exc).__name__}: {exc}",
            )
        solve_elapsed = audited_clock.now() - solve_started
        totals.solve_seconds += solve_elapsed
        if not isinstance(solve_result, RelaxationSolveResult):
            return finish(
                LazyCutStatus.BACKEND_CONTRACT_ERROR,
                "relaxation solver returned the wrong result type",
            )
        if type(solve_result.status) is not RelaxationStatus:
            return finish(
                LazyCutStatus.BACKEND_CONTRACT_ERROR,
                "relaxation solver status must be a RelaxationStatus value",
            )

        stopped, detail = stop_status()
        if stopped is not None:
            rounds.append(
                LazyCutRoundTelemetry(
                    iteration=iteration,
                    solver_status=solve_result.status.value,
                    candidate_sha256=None,
                    relations_checked=0,
                    violations_found=0,
                    cuts_added=0,
                    duplicate_cuts=0,
                    solve_seconds=solve_elapsed,
                    candidate_check_seconds=0.0,
                    validation_seconds=0.0,
                    cut_seconds=0.0,
                )
            )
            return finish(stopped, detail or stopped.value)

        if solve_result.status in (
            RelaxationStatus.INFEASIBLE,
            RelaxationStatus.UNKNOWN,
        ):
            if solve_result.candidate is not None:
                return finish(
                    LazyCutStatus.BACKEND_CONTRACT_ERROR,
                    f"{solve_result.status.value} result must not contain a candidate",
                )
            rounds.append(
                LazyCutRoundTelemetry(
                    iteration=iteration,
                    solver_status=solve_result.status.value,
                    candidate_sha256=None,
                    relations_checked=0,
                    violations_found=0,
                    cuts_added=0,
                    duplicate_cuts=0,
                    solve_seconds=solve_elapsed,
                    candidate_check_seconds=0.0,
                    validation_seconds=0.0,
                    cut_seconds=0.0,
                )
            )
            outcome = (
                LazyCutStatus.INFEASIBLE
                if solve_result.status is RelaxationStatus.INFEASIBLE
                else LazyCutStatus.UNKNOWN
            )
            return finish(
                outcome, f"relaxation solver returned {solve_result.status.value}"
            )

        if solve_result.status not in (
            RelaxationStatus.FEASIBLE,
            RelaxationStatus.OPTIMAL,
        ):
            return finish(
                LazyCutStatus.BACKEND_CONTRACT_ERROR,
                "relaxation solver returned an unsupported status",
            )

        candidate_check_started = audited_clock.now()
        candidate, malformed = _freeze_candidate(
            solve_result.candidate, required_class_ids
        )
        candidate_check_elapsed = audited_clock.now() - candidate_check_started
        totals.candidate_check_seconds += candidate_check_elapsed
        if malformed is not None or candidate is None:
            rounds.append(
                LazyCutRoundTelemetry(
                    iteration=iteration,
                    solver_status=solve_result.status.value,
                    candidate_sha256=None,
                    relations_checked=0,
                    violations_found=0,
                    cuts_added=0,
                    duplicate_cuts=0,
                    solve_seconds=solve_elapsed,
                    candidate_check_seconds=candidate_check_elapsed,
                    validation_seconds=0.0,
                    cut_seconds=0.0,
                )
            )
            return finish(
                LazyCutStatus.MALFORMED_CANDIDATE,
                malformed or "candidate is malformed",
            )

        candidate_sha256 = _candidate_hash(candidate)
        for no_good in no_goods:
            if no_good.rejects(candidate):
                return finish(
                    LazyCutStatus.BACKEND_CONTRACT_ERROR,
                    "relaxation solver returned a candidate rejected by an existing no-good",
                )

        totals.candidates_validated += 1
        validation_started = audited_clock.now()
        violations: list[SameAttendeesNoGood] = []
        checked = 0
        validation_failure: tuple[LazyCutStatus, str] | None = None
        for relation in frozen_relations:
            stopped, detail = stop_status()
            if stopped is not None:
                validation_failure = (stopped, detail or stopped.value)
                break
            try:
                violated = validator(relation, candidate, frozen_travel)
            except (
                Exception
            ) as exc:  # fail closed at the independent validator boundary
                validation_failure = (
                    LazyCutStatus.VALIDATOR_ERROR,
                    f"validator raised {type(exc).__name__}: {exc}",
                )
                break
            if type(violated) is not bool:
                validation_failure = (
                    LazyCutStatus.VALIDATOR_ERROR,
                    "validator must return bool",
                )
                break
            checked += 1
            if violated:
                violations.append(
                    SameAttendeesNoGood.from_candidate(relation, candidate)
                )
        validation_elapsed = audited_clock.now() - validation_started
        totals.validation_seconds += validation_elapsed
        totals.relations_checked += checked
        totals.violations_found += len(violations)

        if validation_failure is not None:
            rounds.append(
                LazyCutRoundTelemetry(
                    iteration=iteration,
                    solver_status=solve_result.status.value,
                    candidate_sha256=candidate_sha256,
                    relations_checked=checked,
                    violations_found=len(violations),
                    cuts_added=0,
                    duplicate_cuts=0,
                    solve_seconds=solve_elapsed,
                    candidate_check_seconds=candidate_check_elapsed,
                    validation_seconds=validation_elapsed,
                    cut_seconds=0.0,
                )
            )
            return finish(*validation_failure)

        stopped, detail = stop_status()
        if stopped is not None:
            return finish(stopped, detail or stopped.value)

        if not violations:
            rounds.append(
                LazyCutRoundTelemetry(
                    iteration=iteration,
                    solver_status=solve_result.status.value,
                    candidate_sha256=candidate_sha256,
                    relations_checked=checked,
                    violations_found=0,
                    cuts_added=0,
                    duplicate_cuts=0,
                    solve_seconds=solve_elapsed,
                    candidate_check_seconds=candidate_check_elapsed,
                    validation_seconds=validation_elapsed,
                    cut_seconds=0.0,
                )
            )
            return finish(
                LazyCutStatus.SUCCESS,
                "candidate passed every required SameAttendees relation",
                candidate=candidate,
            )

        unique_round: dict[
            tuple[tuple[str, tuple[int, int, int, int, str]], ...],
            SameAttendeesNoGood,
        ] = {}
        duplicates = 0
        for no_good in violations:
            key = no_good.stable_key()
            if key in no_good_keys or key in unique_round:
                duplicates += 1
            else:
                unique_round[key] = no_good
        ordered_new = [unique_round[key] for key in sorted(unique_round)]
        if not ordered_new:
            return finish(
                LazyCutStatus.BACKEND_CONTRACT_ERROR,
                "violating candidate produced no new exact no-good",
            )

        cut_started = audited_clock.now()
        added_this_round = 0
        for no_good in ordered_new:
            stopped, detail = stop_status()
            if stopped is not None:
                break
            if add_no_good is not None:
                try:
                    add_no_good(no_good)
                except (
                    Exception
                ) as exc:  # fail closed at the incremental backend boundary
                    cut_elapsed = audited_clock.now() - cut_started
                    totals.cut_seconds += cut_elapsed
                    rounds.append(
                        LazyCutRoundTelemetry(
                            iteration=iteration,
                            solver_status=solve_result.status.value,
                            candidate_sha256=candidate_sha256,
                            relations_checked=checked,
                            violations_found=len(violations),
                            cuts_added=added_this_round,
                            duplicate_cuts=duplicates,
                            solve_seconds=solve_elapsed,
                            candidate_check_seconds=candidate_check_elapsed,
                            validation_seconds=validation_elapsed,
                            cut_seconds=cut_elapsed,
                        )
                    )
                    return finish(
                        LazyCutStatus.CUT_SINK_ERROR,
                        f"cut sink raised {type(exc).__name__}: {exc}",
                    )
            key = no_good.stable_key()
            no_goods.append(no_good)
            no_good_keys.add(key)
            added_this_round += 1
        cut_elapsed = audited_clock.now() - cut_started
        totals.cut_seconds += cut_elapsed
        totals.cuts_added += added_this_round
        totals.duplicate_cuts += duplicates
        rounds.append(
            LazyCutRoundTelemetry(
                iteration=iteration,
                solver_status=solve_result.status.value,
                candidate_sha256=candidate_sha256,
                relations_checked=checked,
                violations_found=len(violations),
                cuts_added=added_this_round,
                duplicate_cuts=duplicates,
                solve_seconds=solve_elapsed,
                candidate_check_seconds=candidate_check_elapsed,
                validation_seconds=validation_elapsed,
                cut_seconds=cut_elapsed,
            )
        )
        stopped, detail = stop_status()
        if stopped is not None:
            return finish(stopped, detail or stopped.value)

    return finish(
        LazyCutStatus.ITERATION_LIMIT,
        f"iteration limit {max_iterations} reached before a validated result",
    )


__all__ = [
    "CutSink",
    "LazyCutResult",
    "LazyCutRoundTelemetry",
    "LazyCutStatus",
    "LazyCutTelemetry",
    "RelationValidator",
    "RelaxationSolveRequest",
    "RelaxationSolveResult",
    "RelaxationSolver",
    "RelaxationStatus",
    "SameAttendeesAssignment",
    "SameAttendeesNoGood",
    "SameAttendeesRelation",
    "ordered_travel_time",
    "run_same_attendees_lazy_cuts",
    "same_attendees_relation_violated",
]
