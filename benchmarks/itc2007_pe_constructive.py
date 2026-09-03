from __future__ import annotations

from dataclasses import dataclass
import random
import time
from typing import Sequence

from benchmarks.itc2007_pe import (
    TIMESLOTS,
    ITC2007PEAssignment,
    ITC2007PEProblem,
    _eligible_rooms,
    _room_matching,
    _student_soft_penalty,
    validate_itc2007_pe_solution,
)


@dataclass(frozen=True)
class PEConstructiveTelemetry:
    attempts: int
    completed_attempts: int
    direct_insertions: int
    repair_insertions: int
    matching_calls: int
    best_distance: int
    best_soft: int
    deadline_exhausted: bool


def _precedence(problem: ITC2007PEProblem) -> tuple[list[set[int]], list[set[int]]]:
    predecessors = [set() for _ in range(problem.events)]
    successors = [set() for _ in range(problem.events)]
    for left in range(problem.events):
        for right in range(problem.events):
            relation = int(problem.precedence[left][right])
            if relation == 1:
                predecessors[right].add(left)
                successors[left].add(right)
            elif relation == -1:
                predecessors[left].add(right)
                successors[right].add(left)
    return predecessors, successors


def _precedence_windows(
    problem: ITC2007PEProblem,
    predecessors: Sequence[set[int]],
    successors: Sequence[set[int]],
    available: Sequence[Sequence[int]],
) -> tuple[tuple[int, int], ...]:
    """Propagate static earliest/latest periods through the precedence DAG."""

    indegree = [len(values) for values in predecessors]
    queue = [event for event, degree in enumerate(indegree) if degree == 0]
    order: list[int] = []
    for event in queue:
        order.append(event)
        for successor in successors[event]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                queue.append(successor)
    if len(order) != problem.events:
        return tuple((0, TIMESLOTS - 1) for _ in range(problem.events))

    earliest = [0] * problem.events
    latest = [TIMESLOTS - 1] * problem.events
    for event in order:
        if predecessors[event]:
            earliest[event] = max(earliest[value] + 1 for value in predecessors[event])
        feasible = [slot for slot in available[event] if slot >= earliest[event]]
        if feasible:
            earliest[event] = min(feasible)
    for event in reversed(order):
        if successors[event]:
            latest[event] = min(latest[value] - 1 for value in successors[event])
        feasible = [slot for slot in available[event] if slot <= latest[event]]
        if feasible:
            latest[event] = max(feasible)
    return tuple(
        (int(earliest[event]), int(latest[event])) for event in range(problem.events)
    )


def _conflict_masks(problem: ITC2007PEProblem) -> tuple[int, ...]:
    masks = [0] * problem.events
    for attendances in problem.student_events:
        events = [event for event, attends in enumerate(attendances) if attends]
        event_mask = 0
        for event in events:
            event_mask |= 1 << event
        for event in events:
            masks[event] |= event_mask ^ (1 << event)
    return tuple(masks)


def _materialize(
    problem: ITC2007PEProblem,
    assignment: Sequence[int],
    period_events: Sequence[set[int]],
) -> tuple[ITC2007PEAssignment, ...] | None:
    rooms = [-1] * problem.events
    for slot, events in enumerate(period_events):
        if not events:
            continue
        matching, _witness = _room_matching(problem, tuple(events))
        if matching is None:
            return None
        for event, room in matching.items():
            rooms[event] = room
    return tuple(
        ITC2007PEAssignment(event, int(assignment[event]), int(rooms[event]))
        if assignment[event] >= 0
        else ITC2007PEAssignment(event, -1, -1)
        for event in range(problem.events)
    )


def _repair_unplaced_events(
    problem: ITC2007PEProblem,
    assignment: list[int],
    period_events: list[set[int]],
    *,
    conflict_masks: Sequence[int],
    predecessors: Sequence[set[int]],
    successors: Sequence[set[int]],
    available: Sequence[Sequence[int]],
    deadline: float,
) -> tuple[int, int]:
    """Insert unplaced events by relocating up to three blocking events."""

    period_masks = [sum(1 << event for event in events) for events in period_events]
    matching_calls = 0
    insertions = 0

    def remove(event: int) -> None:
        slot = int(assignment[event])
        if slot < 0:
            return
        period_events[slot].discard(event)
        period_masks[slot] &= ~(1 << event)
        assignment[event] = -1

    def add(event: int, slot: int) -> None:
        assignment[event] = int(slot)
        period_events[slot].add(event)
        period_masks[slot] |= 1 << event

    def temporal_ok(event: int, slot: int) -> bool:
        if slot not in available[event]:
            return False
        if conflict_masks[event] & period_masks[slot]:
            return False
        if any(
            assignment[value] >= 0 and assignment[value] >= slot
            for value in predecessors[event]
        ):
            return False
        return not any(
            assignment[value] >= 0 and assignment[value] <= slot
            for value in successors[event]
        )

    def room_ok(event: int, slot: int) -> bool:
        nonlocal matching_calls
        matching_calls += 1
        matching, _witness = _room_matching(
            problem,
            tuple((*period_events[slot], event)),
        )
        return matching is not None

    def relocate(blockers: tuple[int, ...], index: int, forbidden: int) -> bool:
        if index >= len(blockers):
            return True
        blocker = int(blockers[index])
        targets = sorted(
            (slot for slot in available[blocker] if slot != forbidden),
            key=lambda slot: (len(period_events[slot]), slot),
        )
        for slot in targets:
            if time.perf_counter() >= deadline:
                return False
            if not temporal_ok(blocker, slot) or not room_ok(blocker, slot):
                continue
            add(blocker, slot)
            if relocate(blockers, index + 1, forbidden):
                return True
            remove(blocker)
        return False

    ordered_unplaced = sorted(
        (event for event, slot in enumerate(assignment) if slot < 0),
        key=lambda event: (
            -problem.event_sizes[event],
            len(available[event]),
            -int(conflict_masks[event]).bit_count(),
            event,
        ),
    )
    for event in ordered_unplaced:
        if time.perf_counter() >= deadline:
            break
        candidate_slots = sorted(
            available[event],
            key=lambda slot: (
                (conflict_masks[event] & period_masks[slot]).bit_count(),
                len(period_events[slot]),
                slot,
            ),
        )
        inserted = False
        for target in candidate_slots:
            if time.perf_counter() >= deadline:
                break
            if any(
                assignment[value] >= 0 and assignment[value] >= target
                for value in predecessors[event]
            ) or any(
                assignment[value] >= 0 and assignment[value] <= target
                for value in successors[event]
            ):
                continue
            conflicts = tuple(
                sorted(
                    value
                    for value in period_events[target]
                    if conflict_masks[event] & (1 << value)
                )
            )
            blocker_sets: list[tuple[int, ...]] = []
            if len(conflicts) <= 3:
                blocker_sets.append(conflicts)
            # If conflicts alone do not release a room-domain bottleneck, try
            # moving one additional low-weight member of the target period.
            if len(conflicts) < 3:
                extras = sorted(
                    period_events[target] - set(conflicts),
                    key=lambda value: (problem.event_sizes[value], value),
                )
                blocker_sets.extend(tuple((*conflicts, extra)) for extra in extras[:8])
            seen: set[tuple[int, ...]] = set()
            for blockers in blocker_sets:
                blockers = tuple(sorted(set(blockers)))
                if blockers in seen or len(blockers) > 3:
                    continue
                seen.add(blockers)
                saved_assignment = list(assignment)
                saved_period_events = [set(values) for values in period_events]
                saved_period_masks = list(period_masks)
                for blocker in blockers:
                    remove(blocker)
                if (
                    relocate(blockers, 0, target)
                    and temporal_ok(event, target)
                    and room_ok(event, target)
                ):
                    add(event, target)
                    insertions += 1
                    inserted = True
                    break
                assignment[:] = saved_assignment
                period_events[:] = saved_period_events
                period_masks[:] = saved_period_masks
            if inserted:
                break
    return insertions, matching_calls


def construct_itc2007_pe_dsat(
    problem: ITC2007PEProblem,
    *,
    deadline: float,
    seed: int = 0,
    attempts: int = 4,
) -> tuple[tuple[ITC2007PEAssignment, ...], PEConstructiveTelemetry]:
    """Build a valid partial PE timetable by dynamic list coloring.

    The constructor chooses the next event from its live feasible-period count
    and saturation, and rematches every affected period exactly.  This avoids
    the irreversible room choices made by the legacy static-order greedy path.
    Only complete independently valid candidates are returned.
    """

    started = time.perf_counter()
    completion_reserve = min(
        0.08,
        max(0.01, (float(deadline) - started) * 0.025),
    )
    work_deadline = max(started, float(deadline) - completion_reserve)
    generation_deadline = started + max(
        0.0,
        (work_deadline - started) * 0.72,
    )
    conflict_masks = _conflict_masks(problem)
    conflict_neighbors = tuple(
        tuple(other for other in range(problem.events) if mask & (1 << other))
        for mask in conflict_masks
    )
    predecessors, successors = _precedence(problem)
    event_students = problem.event_students
    available = tuple(
        tuple(slot for slot, allowed in enumerate(row) if allowed)
        for row in problem.event_availability
    )
    static_windows = _precedence_windows(
        problem,
        predecessors,
        successors,
        available,
    )
    eligible_rooms = tuple(
        _eligible_rooms(problem, event) for event in range(problem.events)
    )
    best = tuple(ITC2007PEAssignment(event, -1, -1) for event in range(problem.events))
    best_validation = validate_itc2007_pe_solution(problem, best)
    best_assignment: list[int] | None = None
    best_period_events: list[set[int]] | None = None
    completed_attempts = 0
    direct_insertions = 0
    repair_insertions = 0
    matching_calls = 0

    requested = max(1, int(attempts))
    for attempt_index in range(requested):
        if time.perf_counter() >= generation_deadline:
            break
        rng = random.Random((int(seed) + 1) * 1_000_003 + 104_729 * attempt_index)
        assignment = [-1] * problem.events
        period_events = [set() for _ in range(TIMESLOTS)]
        period_masks = [0] * TIMESLOTS
        unassigned = set(range(problem.events))
        student_slots: list[set[int]] = [set() for _ in range(problem.students)]
        student_scores = [0] * problem.students
        saturation_slots: list[set[int]] = [set() for _ in range(problem.events)]

        def time_candidates(event: int) -> list[int]:
            static_lower, static_upper = static_windows[event]
            lower = max(
                [
                    static_lower,
                    *(
                        assignment[value] + 1
                        for value in predecessors[event]
                        if assignment[value] >= 0
                    ),
                ]
            )
            upper = min(
                [
                    static_upper,
                    *(
                        assignment[value] - 1
                        for value in successors[event]
                        if assignment[value] >= 0
                    ),
                ]
            )
            return [
                slot
                for slot in available[event]
                if lower <= slot <= upper
                and not (conflict_masks[event] & period_masks[slot])
            ]

        while unassigned and time.perf_counter() < generation_deadline:
            live: list[tuple[tuple[int, int, int, int, float], int, list[int]]] = []
            for event in unassigned:
                candidates = time_candidates(event)
                live.append(
                    (
                        (
                            # Distance-to-feasibility is the number of affected
                            # students, so event weight must dominate color
                            # scarcity.  Saturation and live list size break
                            # ties without sacrificing a large event for many
                            # tiny constrained ones.
                            -problem.event_sizes[event],
                            len(candidates),
                            -len(saturation_slots[event]),
                            -conflict_masks[event].bit_count(),
                            rng.random(),
                        ),
                        event,
                        candidates,
                    )
                )
            _rank, event, candidates = min(live, key=lambda item: item[0])
            unassigned.remove(event)
            if not candidates or not eligible_rooms[event]:
                continue
            ranked_slots: list[tuple[tuple[int, int, int, float], int]] = []
            for slot in candidates:
                if time.perf_counter() >= generation_deadline:
                    break
                soft_delta = 0
                for student in event_students[event]:
                    updated = set(student_slots[student])
                    updated.add(slot)
                    soft_delta += (
                        _student_soft_penalty(updated) - student_scores[student]
                    )
                ranked_slots.append(
                    (
                        (
                            soft_delta,
                            len(period_events[slot]),
                            slot % 9 == 8,
                            rng.random(),
                        ),
                        slot,
                    )
                )
            slot: int | None = None
            for _slot_rank, candidate_slot in sorted(
                ranked_slots, key=lambda item: item[0]
            ):
                matching_calls += 1
                matching, _witness = _room_matching(
                    problem,
                    tuple((*period_events[candidate_slot], event)),
                )
                if matching is not None:
                    slot = int(candidate_slot)
                    break
            if slot is None:
                continue
            assignment[event] = slot
            period_events[slot].add(event)
            period_masks[slot] |= 1 << event
            for student in event_students[event]:
                student_slots[student].add(slot)
                student_scores[student] = _student_soft_penalty(student_slots[student])
            for neighbor in conflict_neighbors[event]:
                if assignment[neighbor] < 0:
                    saturation_slots[neighbor].add(slot)
            direct_insertions += 1

        candidate = _materialize(problem, assignment, period_events)
        if candidate is not None:
            validation = validate_itc2007_pe_solution(problem, candidate)
            if (
                validation.feasible
                and validation.score.lexicographic < best_validation.score.lexicographic
            ):
                best = candidate
                best_validation = validation
                best_assignment = list(assignment)
                best_period_events = [set(values) for values in period_events]
        completed_attempts += 1

    if (
        best_assignment is not None
        and best_period_events is not None
        and time.perf_counter() < work_deadline
    ):
        repaired, repair_matching_calls = _repair_unplaced_events(
            problem,
            best_assignment,
            best_period_events,
            conflict_masks=conflict_masks,
            predecessors=predecessors,
            successors=successors,
            available=available,
            deadline=work_deadline,
        )
        repair_insertions += repaired
        matching_calls += repair_matching_calls
        candidate = _materialize(problem, best_assignment, best_period_events)
        if candidate is not None and time.perf_counter() < float(deadline):
            validation = validate_itc2007_pe_solution(problem, candidate)
            if (
                validation.feasible
                and validation.score.lexicographic < best_validation.score.lexicographic
            ):
                best = candidate
                best_validation = validation

    return best, PEConstructiveTelemetry(
        attempts=requested,
        completed_attempts=completed_attempts,
        direct_insertions=direct_insertions,
        repair_insertions=repair_insertions,
        matching_calls=matching_calls,
        best_distance=int(best_validation.score.distance_to_feasibility),
        best_soft=int(best_validation.score.soft_violations),
        deadline_exhausted=bool(time.perf_counter() >= float(deadline)),
    )


def repair_itc2007_pe_assignment(
    problem: ITC2007PEProblem,
    initial: Sequence[ITC2007PEAssignment],
    *,
    deadline: float,
) -> tuple[tuple[ITC2007PEAssignment, ...], dict[str, int | bool]]:
    """Apply bounded exact-room ejection repair to a valid PE incumbent."""

    original = tuple(initial)
    validation = validate_itc2007_pe_solution(problem, original)
    if not validation.feasible or len(original) != problem.events:
        return original, {
            "accepted": False,
            "repair_insertions": 0,
            "matching_calls": 0,
            "initial_distance": int(validation.score.distance_to_feasibility),
            "final_distance": int(validation.score.distance_to_feasibility),
        }
    started = time.perf_counter()
    reserve = min(0.08, max(0.01, (float(deadline) - started) * 0.05))
    work_deadline = max(started, float(deadline) - reserve)
    assignment = [int(row.timeslot) if row.placed else -1 for row in original]
    period_events = [set() for _ in range(TIMESLOTS)]
    for event, slot in enumerate(assignment):
        if slot >= 0:
            period_events[slot].add(event)
    conflict_masks = _conflict_masks(problem)
    predecessors, successors = _precedence(problem)
    available = tuple(
        tuple(slot for slot, allowed in enumerate(row) if allowed)
        for row in problem.event_availability
    )
    insertions, matching_calls = _repair_unplaced_events(
        problem,
        assignment,
        period_events,
        conflict_masks=conflict_masks,
        predecessors=predecessors,
        successors=successors,
        available=available,
        deadline=work_deadline,
    )
    candidate = _materialize(problem, assignment, period_events)
    if candidate is None or time.perf_counter() >= float(deadline):
        return original, {
            "accepted": False,
            "repair_insertions": int(insertions),
            "matching_calls": int(matching_calls),
            "initial_distance": int(validation.score.distance_to_feasibility),
            "final_distance": int(validation.score.distance_to_feasibility),
        }
    candidate_validation = validate_itc2007_pe_solution(problem, candidate)
    accepted = bool(
        candidate_validation.feasible
        and candidate_validation.score.lexicographic < validation.score.lexicographic
        and time.perf_counter() <= float(deadline)
    )
    selected = candidate if accepted else original
    selected_validation = candidate_validation if accepted else validation
    return selected, {
        "accepted": bool(accepted),
        "repair_insertions": int(insertions),
        "matching_calls": int(matching_calls),
        "initial_distance": int(validation.score.distance_to_feasibility),
        "final_distance": int(selected_validation.score.distance_to_feasibility),
    }


__all__ = [
    "PEConstructiveTelemetry",
    "construct_itc2007_pe_dsat",
    "repair_itc2007_pe_assignment",
]
