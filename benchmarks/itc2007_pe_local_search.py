from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
import random
import time
from typing import Sequence

from benchmarks.itc2007_pe import (
    TIMESLOTS,
    ITC2007PEAssignment,
    ITC2007PEProblem,
    ITC2007PEScore,
    ITC2007PEValidation,
    _room_matching,
    validate_itc2007_pe_solution,
)


@dataclass(frozen=True)
class PEReplacementMove:
    inserted_event: int
    target_slot: int
    ejected_events: tuple[int, ...]
    distance_delta: int


@dataclass
class PEProjectedSearchResult:
    assignments: tuple[ITC2007PEAssignment, ...]
    status: str
    initial_score: ITC2007PEScore
    final_score: ITC2007PEScore
    iterations: int
    accepted_moves: int
    improving_moves: int
    barrier_moves: int
    room_matchings: int
    elapsed_seconds: float
    deadline_exhausted: bool
    atomic_repairs_attempted: int = 0
    atomic_repairs_succeeded: int = 0
    atomic_events_reinserted: int = 0
    best_trajectory: list[dict[str, object]] = field(default_factory=list)

    @property
    def improved(self) -> bool:
        return self.final_score.lexicographic < self.initial_score.lexicographic

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "improved": self.improved,
            "initial_score": self.initial_score.to_dict(),
            "final_score": self.final_score.to_dict(),
            "iterations": int(self.iterations),
            "accepted_moves": int(self.accepted_moves),
            "improving_moves": int(self.improving_moves),
            "barrier_moves": int(self.barrier_moves),
            "room_matchings": int(self.room_matchings),
            "elapsed_seconds": float(self.elapsed_seconds),
            "deadline_exhausted": bool(self.deadline_exhausted),
            "atomic_repairs_attempted": int(self.atomic_repairs_attempted),
            "atomic_repairs_succeeded": int(self.atomic_repairs_succeeded),
            "atomic_events_reinserted": int(self.atomic_events_reinserted),
            "best_trajectory": list(self.best_trajectory),
        }


def _precedence(problem: ITC2007PEProblem) -> tuple[tuple[int, ...], tuple[int, ...]]:
    predecessors: list[set[int]] = [set() for _ in range(problem.events)]
    successors: list[set[int]] = [set() for _ in range(problem.events)]
    for left in range(problem.events):
        for right in range(problem.events):
            relation = int(problem.precedence[left][right])
            if relation == 1:
                predecessors[right].add(left)
                successors[left].add(right)
            elif relation == -1:
                predecessors[left].add(right)
                successors[right].add(left)
    return (
        tuple(tuple(sorted(values)) for values in predecessors),
        tuple(tuple(sorted(values)) for values in successors),
    )


def _conflicts(problem: ITC2007PEProblem) -> tuple[frozenset[int], ...]:
    output = [set() for _ in range(problem.events)]
    for attendances in problem.student_events:
        events = [event for event, attends in enumerate(attendances) if attends]
        for index, left in enumerate(events):
            for right in events[index + 1 :]:
                output[left].add(right)
                output[right].add(left)
    return tuple(frozenset(values) for values in output)


def optimize_itc2007_pe_partial(
    problem: ITC2007PEProblem,
    initial: Sequence[ITC2007PEAssignment],
    *,
    deadline: float,
    seed: int = 0,
    history_length: int = 64,
    max_iterations: int = 20_000,
    candidate_slots: int = 16,
    extra_blocker_pool: int = 7,
    completion_reserve_seconds: float = 0.03,
    max_atomic_repair_events: int = 3,
    atomic_repair_attempts_per_iteration: int = 3,
    atomic_slot_limit: int = 12,
) -> PEProjectedSearchResult:
    """Search the partial PE timetable with atomic insert/eject replacements.

    Unplaced events are legal in ITC-2007 PE.  This search uses them as a
    controlled buffer: an insertion may atomically eject conflicting or
    room-blocking events, and late acceptance may cross a temporary distance
    barrier.  Only independently valid incumbents are retained and returned.
    """

    started = time.perf_counter()
    original = tuple(initial)
    validation = validate_itc2007_pe_solution(problem, original)
    if not validation.feasible:
        return PEProjectedSearchResult(
            assignments=original,
            status="invalid_initial",
            initial_score=validation.score,
            final_score=validation.score,
            iterations=0,
            accepted_moves=0,
            improving_moves=0,
            barrier_moves=0,
            room_matchings=0,
            elapsed_seconds=time.perf_counter() - started,
            deadline_exhausted=False,
        )
    if time.perf_counter() >= float(deadline):
        return PEProjectedSearchResult(
            assignments=original,
            status="deadline_before_search",
            initial_score=validation.score,
            final_score=validation.score,
            iterations=0,
            accepted_moves=0,
            improving_moves=0,
            barrier_moves=0,
            room_matchings=0,
            elapsed_seconds=time.perf_counter() - started,
            deadline_exhausted=True,
        )

    rng = random.Random(int(seed))
    work_deadline = max(
        float(started),
        float(deadline) - max(0.0, float(completion_reserve_seconds)),
    )
    rows = list(original)
    period_events = [set() for _ in range(TIMESLOTS)]
    for row in rows:
        if row.placed:
            period_events[int(row.timeslot)].add(int(row.event))
    conflicts = _conflicts(problem)
    predecessors, successors = _precedence(problem)
    available = tuple(
        tuple(slot for slot, allowed in enumerate(row) if allowed)
        for row in problem.event_availability
    )
    current_distance = int(validation.score.distance_to_feasibility)
    current_soft = int(validation.score.soft_violations)
    history = [current_distance] * max(4, int(history_length))
    best = original
    best_validation = validation
    best_trajectory: list[dict[str, object]] = []
    iterations = 0
    accepted = 0
    improving = 0
    barriers = 0
    room_matchings = 0
    atomic_repairs_attempted = 0
    atomic_repairs_succeeded = 0
    atomic_events_reinserted = 0
    no_accepts = 0

    def direct_atomic_repair(
        move: PEReplacementMove,
        target_matching: dict[int, int],
    ) -> tuple[
        list[ITC2007PEAssignment],
        list[set[int]],
        ITC2007PEValidation,
        tuple[int, ...],
    ] | None:
        """Insert a seed and rehome its blockers before exposing any state.

        The ordinary late-acceptance move deliberately leaves blockers
        unplaced, which is useful for strategic oscillation but can strand a
        heavy event behind several individually unattractive steps.  This
        bounded DFS instead treats the seed insertion, affected-period room
        rematching, and direct relocation of up to three blockers as one
        transaction.  No intermediate schedule is returned or admitted.
        """

        nonlocal room_matchings, atomic_repairs_attempted
        ejected = tuple(int(value) for value in move.ejected_events)
        # Preserve the cheap, already-improving insert/eject trajectory.  The
        # compound repair is for the exact barrier case where exposing the
        # first step would be distance-neutral or worse.
        if (
            int(move.distance_delta) < 0
            or not ejected
            or len(ejected) > max(0, int(max_atomic_repair_events))
        ):
            return None
        atomic_repairs_attempted += 1
        candidate_rows = list(rows)
        candidate_periods = [set(values) for values in period_events]
        for value in ejected:
            old_slot = int(candidate_rows[value].timeslot)
            if old_slot >= 0:
                candidate_periods[old_slot].discard(value)
            candidate_rows[value] = ITC2007PEAssignment(value, -1, -1)
        candidate_periods[int(move.target_slot)].add(int(move.inserted_event))
        for value, room in target_matching.items():
            candidate_rows[int(value)] = ITC2007PEAssignment(
                int(value), int(move.target_slot), int(room)
            )

        def placement_options(
            event: int,
            active_rows: list[ITC2007PEAssignment],
            active_periods: list[set[int]],
            protected: frozenset[int],
            displaced: frozenset[int],
        ) -> list[
            tuple[
                tuple[int, int, int, int],
                int,
                dict[int, int],
                tuple[int, ...],
            ]
        ]:
            nonlocal room_matchings
            options: list[
                tuple[
                    tuple[int, int, int, int],
                    int,
                    dict[int, int],
                    tuple[int, ...],
                ]
            ] = []
            for slot in available[int(event)]:
                if time.perf_counter() >= float(work_deadline):
                    break
                blockers = set(conflicts[int(event)] & active_periods[int(slot)])
                blockers.update(
                    value
                    for value in predecessors[int(event)]
                    if active_rows[value].placed
                    and int(active_rows[value].timeslot) >= int(slot)
                )
                blockers.update(
                    value
                    for value in successors[int(event)]
                    if active_rows[value].placed
                    and int(active_rows[value].timeslot) <= int(slot)
                )
                if blockers & protected:
                    continue
                if len(displaced | blockers) > max(0, int(max_atomic_repair_events)):
                    continue
                variants = [tuple(sorted(blockers))]
                base_members = tuple(
                    sorted((active_periods[int(slot)] - blockers) | {int(event)})
                )
                matching, _witness = _room_matching(problem, base_members)
                room_matchings += 1
                if matching is None:
                    extra_candidates = sorted(
                        active_periods[int(slot)] - blockers - set(protected),
                        key=lambda value: (problem.event_sizes[value], value),
                    )[:4]
                    remaining_capacity = max(
                        0,
                        int(max_atomic_repair_events)
                        - len(displaced | blockers),
                    )
                    variants.extend(
                        tuple(sorted((*blockers, *extra)))
                        for width in range(1, min(2, remaining_capacity) + 1)
                        for extra in combinations(extra_candidates, width)
                    )
                for variant in variants:
                    new_blockers = set(variant)
                    if new_blockers & protected:
                        continue
                    if len(displaced | new_blockers) > max(
                        0, int(max_atomic_repair_events)
                    ):
                        continue
                    members = tuple(
                        sorted(
                            (active_periods[int(slot)] - new_blockers)
                            | {int(event)}
                        )
                    )
                    matching, _witness = _room_matching(problem, members)
                    room_matchings += 1
                    if matching is None:
                        continue
                    options.append(
                        (
                            (
                                len(new_blockers),
                                len(active_periods[int(slot)]),
                                abs(int(slot) - int(move.target_slot)),
                                int(slot),
                            ),
                            int(slot),
                            matching,
                            tuple(sorted(new_blockers)),
                        )
                    )
                    break
            options.sort(key=lambda value: value[0])
            return options[: max(1, int(atomic_slot_limit))]

        def reinsert(
            remaining: tuple[int, ...],
            active_rows: list[ITC2007PEAssignment],
            active_periods: list[set[int]],
            protected: frozenset[int],
            displaced: frozenset[int],
        ) -> tuple[
            list[ITC2007PEAssignment],
            list[set[int]],
            frozenset[int],
        ] | None:
            if time.perf_counter() >= float(work_deadline):
                return None
            if not remaining:
                return active_rows, active_periods, displaced
            ranked: list[
                tuple[
                    tuple[int, int, int],
                    int,
                    list[
                        tuple[
                            tuple[int, int, int, int],
                            int,
                            dict[int, int],
                            tuple[int, ...],
                        ]
                    ],
                ]
            ] = []
            for event in remaining:
                options = placement_options(
                    event,
                    active_rows,
                    active_periods,
                    protected,
                    displaced,
                )
                if not options:
                    return None
                ranked.append(
                    (
                        (
                            len(options),
                            -int(problem.event_sizes[int(event)]),
                            int(event),
                        ),
                        int(event),
                        options,
                    )
                )
            _rank, event, options = min(ranked, key=lambda value: value[0])
            base_remaining = tuple(value for value in remaining if value != event)
            for _option_rank, slot, matching, new_blockers in options:
                next_rows = list(active_rows)
                next_periods = [set(values) for values in active_periods]
                for blocker in new_blockers:
                    old_slot = int(next_rows[int(blocker)].timeslot)
                    if old_slot >= 0:
                        next_periods[old_slot].discard(int(blocker))
                    next_rows[int(blocker)] = ITC2007PEAssignment(
                        int(blocker), -1, -1
                    )
                next_periods[int(slot)].add(int(event))
                for value, room in matching.items():
                    next_rows[int(value)] = ITC2007PEAssignment(
                        int(value), int(slot), int(room)
                    )
                next_remaining = tuple(
                    dict.fromkeys((*base_remaining, *new_blockers))
                )
                repaired = reinsert(
                    next_remaining,
                    next_rows,
                    next_periods,
                    protected | {int(event)},
                    displaced | set(new_blockers),
                )
                if repaired is not None:
                    return repaired
            return None

        repaired = reinsert(
            ejected,
            candidate_rows,
            candidate_periods,
            frozenset({int(move.inserted_event)}),
            frozenset(ejected),
        )
        if repaired is None or time.perf_counter() >= float(work_deadline):
            return None
        repaired_rows, repaired_periods, displaced = repaired
        repaired_validation = validate_itc2007_pe_solution(problem, repaired_rows)
        if not repaired_validation.feasible:
            return None
        return (
            repaired_rows,
            repaired_periods,
            repaired_validation,
            tuple(sorted(displaced)),
        )

    while iterations < max(1, int(max_iterations)) and time.perf_counter() < float(
        work_deadline
    ):
        iterations += 1
        unplaced = [event for event, row in enumerate(rows) if not row.placed]
        if not unplaced:
            break
        if iterations % 7 == 1:
            event = max(
                unplaced, key=lambda value: (problem.event_sizes[value], -value)
            )
        else:
            weights = [max(1, problem.event_sizes[value]) for value in unplaced]
            event = rng.choices(unplaced, weights=weights, k=1)[0]
        slots = list(available[event])
        rng.shuffle(slots)
        slots.sort(
            key=lambda slot: (
                len(conflicts[event] & period_events[slot]),
                len(period_events[slot]),
                slot,
            )
        )
        moves: list[
            tuple[tuple[int, int, int, int], PEReplacementMove, dict[int, int]]
        ] = []
        for slot in slots[: max(1, int(candidate_slots))]:
            if time.perf_counter() >= float(work_deadline):
                break
            blockers = set(conflicts[event] & period_events[slot])
            blockers.update(
                value
                for value in predecessors[event]
                if rows[value].placed and int(rows[value].timeslot) >= slot
            )
            blockers.update(
                value
                for value in successors[event]
                if rows[value].placed and int(rows[value].timeslot) <= slot
            )
            base_members = tuple(sorted((period_events[slot] - blockers) | {event}))
            matching, _witness = _room_matching(problem, base_members)
            room_matchings += 1
            blocker_variants: list[tuple[int, ...]] = [tuple(sorted(blockers))]
            if matching is None:
                extras = sorted(
                    period_events[slot] - blockers,
                    key=lambda value: (problem.event_sizes[value], value),
                )[: max(1, int(extra_blocker_pool))]
                blocker_variants.extend(
                    tuple(sorted((*blockers, *extra)))
                    for width in (1, 2)
                    for extra in combinations(extras, width)
                )
            for ejected in blocker_variants:
                if time.perf_counter() >= float(work_deadline):
                    break
                members = tuple(sorted((period_events[slot] - set(ejected)) | {event}))
                matching, _witness = _room_matching(problem, members)
                room_matchings += 1
                if matching is None:
                    continue
                delta = sum(problem.event_sizes[value] for value in ejected) - int(
                    problem.event_sizes[event]
                )
                moves.append(
                    (
                        (delta, len(ejected), slot, event),
                        PEReplacementMove(event, slot, ejected, delta),
                        matching,
                    )
                )
                break
        history_bound = history[iterations % len(history)]
        history[iterations % len(history)] = current_distance
        admissible = [
            value
            for value in moves
            if current_distance + value[1].distance_delta
            <= max(current_distance, history_bound)
        ]
        if not admissible and moves and no_accepts >= 8:
            # A bounded strategic-oscillation step: the full move is atomic and
            # remains hard-feasible, but its lexicographic distance may rise.
            admissible = sorted(moves, key=lambda value: value[0])[:1]
        if not admissible:
            no_accepts += 1
            continue

        atomic_selected = False
        for _rank, atomic_move, atomic_matching in sorted(
            moves, key=lambda value: value[0]
        )[: max(0, int(atomic_repair_attempts_per_iteration))]:
            if time.perf_counter() >= float(work_deadline):
                break
            repaired = direct_atomic_repair(atomic_move, atomic_matching)
            if repaired is None:
                continue
            (
                repaired_rows,
                repaired_periods,
                repaired_validation,
                displaced_events,
            ) = repaired
            if repaired_validation.score.lexicographic >= (
                int(current_distance),
                int(current_soft),
            ):
                continue
            rows = repaired_rows
            period_events = repaired_periods
            previous_distance = int(current_distance)
            current_distance = int(
                repaired_validation.score.distance_to_feasibility
            )
            current_soft = int(repaired_validation.score.soft_violations)
            accepted += 1
            improving += int(current_distance < previous_distance)
            barriers += int(bool(atomic_move.ejected_events))
            atomic_repairs_succeeded += 1
            atomic_events_reinserted += len(displaced_events)
            no_accepts = 0
            if (
                repaired_validation.score.lexicographic
                < best_validation.score.lexicographic
            ):
                best = tuple(rows)
                best_validation = repaired_validation
                best_trajectory.append(
                    {
                        "iteration": int(iterations),
                        "score": list(repaired_validation.score.lexicographic),
                        "move": {
                            "inserted_event": int(atomic_move.inserted_event),
                            "target_slot": int(atomic_move.target_slot),
                            "ejected_events": list(atomic_move.ejected_events),
                            "distance_delta": int(atomic_move.distance_delta),
                            "atomic_repair": True,
                            "reinserted_events": list(displaced_events),
                        },
                    }
                )
            atomic_selected = True
            break
        if atomic_selected:
            continue
        _rank, move, matching = min(admissible, key=lambda value: value[0])
        previous_distance = current_distance
        for value in move.ejected_events:
            old_slot = int(rows[value].timeslot)
            if old_slot >= 0:
                period_events[old_slot].discard(value)
            rows[value] = ITC2007PEAssignment(value, -1, -1)
        period_events[move.target_slot].add(move.inserted_event)
        for value, room in matching.items():
            rows[value] = ITC2007PEAssignment(value, move.target_slot, int(room))
        current_distance += int(move.distance_delta)
        accepted += 1
        no_accepts = 0
        if current_distance < previous_distance:
            improving += 1
        elif current_distance > previous_distance:
            barriers += 1

        if current_distance <= int(best_validation.score.distance_to_feasibility):
            candidate = tuple(rows)
            candidate_validation = validate_itc2007_pe_solution(problem, candidate)
            if not candidate_validation.feasible:
                # Never continue from an invalid incremental state.
                rows = list(best)
                period_events = [set() for _ in range(TIMESLOTS)]
                for row in rows:
                    if row.placed:
                        period_events[row.timeslot].add(row.event)
                current_distance = int(best_validation.score.distance_to_feasibility)
                current_soft = int(best_validation.score.soft_violations)
                continue
            current_soft = int(candidate_validation.score.soft_violations)
            if (
                candidate_validation.score.lexicographic
                < best_validation.score.lexicographic
            ):
                best = candidate
                best_validation = candidate_validation
                best_trajectory.append(
                    {
                        "iteration": int(iterations),
                        "score": list(candidate_validation.score.lexicographic),
                        "move": {
                            "inserted_event": int(move.inserted_event),
                            "target_slot": int(move.target_slot),
                            "ejected_events": list(move.ejected_events),
                            "distance_delta": int(move.distance_delta),
                        },
                    }
                )

    elapsed = time.perf_counter() - started
    return PEProjectedSearchResult(
        assignments=best,
        status="improved"
        if best_validation.score.lexicographic < validation.score.lexicographic
        else "no_improvement",
        initial_score=validation.score,
        final_score=best_validation.score,
        iterations=int(iterations),
        accepted_moves=int(accepted),
        improving_moves=int(improving),
        barrier_moves=int(barriers),
        room_matchings=int(room_matchings),
        elapsed_seconds=float(elapsed),
        deadline_exhausted=bool(time.perf_counter() >= float(deadline)),
        atomic_repairs_attempted=int(atomic_repairs_attempted),
        atomic_repairs_succeeded=int(atomic_repairs_succeeded),
        atomic_events_reinserted=int(atomic_events_reinserted),
        best_trajectory=best_trajectory,
    )


__all__ = [
    "PEProjectedSearchResult",
    "PEReplacementMove",
    "optimize_itc2007_pe_partial",
]
