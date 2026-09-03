from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from functools import cached_property
from pathlib import Path
import random
import re
import shutil
import subprocess
import tempfile
import time
from typing import Sequence

from ortools.sat.python import cp_model


SLOTS_PER_DAY = 9
DAYS = 5
TIMESLOTS = SLOTS_PER_DAY * DAYS


@dataclass(frozen=True)
class ITC2007PEProblem:
    """Native ITC-2007 post-enrolment course-timetabling instance."""

    events: int
    rooms: int
    features: int
    students: int
    room_capacities: tuple[int, ...]
    student_events: tuple[tuple[bool, ...], ...]
    room_features: tuple[tuple[bool, ...], ...]
    event_features: tuple[tuple[bool, ...], ...]
    event_availability: tuple[tuple[bool, ...], ...]
    precedence: tuple[tuple[int, ...], ...]
    name: str = ""

    @cached_property
    def event_students(self) -> tuple[tuple[int, ...], ...]:
        return tuple(
            tuple(
                student
                for student, attendances in enumerate(self.student_events)
                if attendances[event]
            )
            for event in range(self.events)
        )

    @cached_property
    def event_sizes(self) -> tuple[int, ...]:
        return tuple(len(students) for students in self.event_students)


@dataclass(frozen=True)
class ITC2007PEAssignment:
    event: int
    timeslot: int
    room: int

    @property
    def placed(self) -> bool:
        return self.timeslot >= 0 and self.room >= 0


@dataclass(frozen=True)
class ITC2007PEScore:
    """The competition's lexicographic distance/soft score."""

    distance_to_feasibility: int
    single_class_days: int
    consecutive_excess: int
    last_slot: int

    @property
    def soft_violations(self) -> int:
        return int(self.single_class_days + self.consecutive_excess + self.last_slot)

    @property
    def lexicographic(self) -> tuple[int, int]:
        return int(self.distance_to_feasibility), int(self.soft_violations)

    def to_dict(self) -> dict[str, int | list[int]]:
        payload: dict[str, int | list[int]] = asdict(self)
        payload["soft_violations"] = self.soft_violations
        payload["lexicographic"] = list(self.lexicographic)
        return payload


@dataclass(frozen=True)
class ITC2007PEValidation:
    score: ITC2007PEScore
    errors: tuple[str, ...] = ()

    @property
    def feasible(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "feasible": self.feasible,
            "hard_violations": len(self.errors),
            "errors": list(self.errors),
            "score": self.score.to_dict(),
        }


@dataclass(frozen=True)
class ITC2007PEOfficialValidation:
    """Parsed output from the official ITC-2007 PE C++ validator."""

    unsuitable_rooms: int
    unsuitable_slots: int
    ordering_problems: int
    student_clashes: int
    room_clashes: int
    unplaced_events: int
    distance_to_feasibility: int
    consecutive_excess: int
    single_class_days: int
    last_slot: int
    soft_violations: int
    returncode: int = 0
    stdout: str = field(default="", repr=False, compare=False)
    stderr: str = field(default="", repr=False, compare=False)

    @property
    def hard_violations(self) -> int:
        return int(
            self.unsuitable_rooms
            + self.unsuitable_slots
            + self.ordering_problems
            + self.student_clashes
            + self.room_clashes
        )

    @property
    def feasible(self) -> bool:
        return self.hard_violations == 0

    @property
    def lexicographic(self) -> tuple[int, int]:
        return int(self.distance_to_feasibility), int(self.soft_violations)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("stdout", None)
        payload.pop("stderr", None)
        payload["hard_violations"] = self.hard_violations
        payload["feasible"] = self.feasible
        payload["lexicographic"] = list(self.lexicographic)
        return payload


class ITC2007PEValidatorError(RuntimeError):
    """Raised when the external PE validator cannot be executed or parsed."""


@dataclass(frozen=True)
class ITC2007PESolveResult:
    assignments: tuple[ITC2007PEAssignment, ...]
    validation: ITC2007PEValidation
    status: str
    raw_status: int
    objective_value: int | None
    best_bound: int | None
    build_seconds: float
    search_seconds: float
    elapsed_seconds: float
    deadline_overrun_seconds: float
    seed: int
    workers: int
    telemetry: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "raw_status": int(self.raw_status),
            "objective_value": self.objective_value,
            "best_bound": self.best_bound,
            "build_seconds": float(self.build_seconds),
            "search_seconds": float(self.search_seconds),
            "elapsed_seconds": float(self.elapsed_seconds),
            "deadline_overrun_seconds": float(self.deadline_overrun_seconds),
            "seed": int(self.seed),
            "workers": int(self.workers),
            "validation": self.validation.to_dict(),
            "telemetry": dict(self.telemetry),
        }


class ITC2007PEDeadline(RuntimeError):
    pass


def _check_deadline(deadline: float | None, phase: str) -> None:
    if deadline is not None and time.perf_counter() >= float(deadline):
        raise ITC2007PEDeadline(f"deadline exhausted during {phase}")


def _binary_rows(
    values: Sequence[int],
    offset: int,
    rows: int,
    columns: int,
    *,
    name: str,
) -> tuple[tuple[tuple[bool, ...], ...], int]:
    output: list[tuple[bool, ...]] = []
    for row in range(rows):
        chunk = values[offset : offset + columns]
        if len(chunk) != columns:
            raise ValueError(f"ITC-2007 PE input ends inside {name} row {row}")
        if any(value not in {0, 1} for value in chunk):
            raise ValueError(f"ITC-2007 PE {name} must contain only zero or one")
        output.append(tuple(bool(value) for value in chunk))
        offset += columns
    return tuple(output), offset


def parse_itc2007_pe(path: str | Path) -> ITC2007PEProblem:
    """Parse the official dense integer ``.tim`` format without flattening it."""

    source = Path(path)
    try:
        values = [
            int(token) for token in source.read_text(encoding="utf-8-sig").split()
        ]
    except ValueError as exc:
        raise ValueError("ITC-2007 PE input contains a non-integer token") from exc
    if len(values) < 4:
        raise ValueError("ITC-2007 PE input is missing its four-value header")
    events, rooms, features, students = values[:4]
    if events <= 0 or rooms <= 0 or features < 0 or students < 0:
        raise ValueError("ITC-2007 PE header contains invalid dimensions")
    offset = 4
    capacities = tuple(values[offset : offset + rooms])
    if len(capacities) != rooms:
        raise ValueError("ITC-2007 PE input ends inside room capacities")
    if any(capacity < 0 for capacity in capacities):
        raise ValueError("ITC-2007 PE room capacities must be non-negative")
    offset += rooms
    student_events, offset = _binary_rows(
        values, offset, students, events, name="student-event matrix"
    )
    room_features, offset = _binary_rows(
        values, offset, rooms, features, name="room-feature matrix"
    )
    event_features, offset = _binary_rows(
        values, offset, events, features, name="event-feature matrix"
    )
    availability, offset = _binary_rows(
        values, offset, events, TIMESLOTS, name="event-availability matrix"
    )
    precedence_rows: list[tuple[int, ...]] = []
    for event in range(events):
        row = values[offset : offset + events]
        if len(row) != events:
            raise ValueError(f"ITC-2007 PE input ends inside precedence row {event}")
        if any(value not in {-1, 0, 1} for value in row):
            raise ValueError("ITC-2007 PE precedence values must be -1, zero, or one")
        if row[event] != 0:
            raise ValueError("ITC-2007 PE precedence diagonal must be zero")
        precedence_rows.append(tuple(row))
        offset += events
    for left in range(events):
        for right in range(left + 1, events):
            if precedence_rows[left][right] != -precedence_rows[right][left]:
                raise ValueError("ITC-2007 PE precedence matrix must be skew-symmetric")
    if offset != len(values):
        raise ValueError(
            f"ITC-2007 PE input has {len(values) - offset} trailing integers"
        )
    return ITC2007PEProblem(
        name=source.stem,
        events=events,
        rooms=rooms,
        features=features,
        students=students,
        room_capacities=capacities,
        student_events=student_events,
        room_features=room_features,
        event_features=event_features,
        event_availability=availability,
        precedence=tuple(precedence_rows),
    )


def parse_itc2007_pe_solution(
    path: str | Path,
    problem: ITC2007PEProblem,
) -> tuple[ITC2007PEAssignment, ...]:
    source = Path(path)
    try:
        values = [
            int(token) for token in source.read_text(encoding="utf-8-sig").split()
        ]
    except ValueError as exc:
        raise ValueError("ITC-2007 PE solution contains a non-integer token") from exc
    if len(values) != 2 * problem.events:
        raise ValueError(
            "ITC-2007 PE solution must contain exactly two integers per event"
        )
    return tuple(
        ITC2007PEAssignment(
            event=event,
            timeslot=values[2 * event],
            room=values[2 * event + 1],
        )
        for event in range(problem.events)
    )


def write_itc2007_pe_solution(
    path: str | Path,
    assignments: Sequence[ITC2007PEAssignment],
    *,
    problem: ITC2007PEProblem | None = None,
) -> None:
    if problem is not None and len(assignments) != problem.events:
        raise ValueError("ITC-2007 PE solution assignment count mismatch")
    expected_events = range(len(assignments))
    if [int(row.event) for row in assignments] != list(expected_events):
        raise ValueError("ITC-2007 PE solution rows must be in event order")
    Path(path).write_text(
        "".join(f"{int(row.timeslot)} {int(row.room)}\n" for row in assignments),
        encoding="utf-8",
        newline="\n",
    )


_OFFICIAL_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "unsuitable_rooms": re.compile(r"Number of unsuitable rooms\s*=\s*(\d+)"),
    "unsuitable_slots": re.compile(r"Number of unsuitable slots\s*=\s*(\d+)"),
    "ordering_problems": re.compile(r"Number of ordering problems\s*=\s*(\d+)"),
    "student_clashes": re.compile(r"Number of student clashes\s*=\s*(\d+)"),
    "room_clashes": re.compile(r"Number of room clashes\s*=\s*(\d+)"),
    "unplaced_events": re.compile(r"Number of unplaced events\s*=\s*(\d+)"),
    "distance_to_feasibility": re.compile(r"Distance to feasibility\s*=\s*(\d+)"),
    "consecutive_excess": re.compile(
        r"Penalty for students having three or more events in a row\s*=\s*(\d+)"
    ),
    "single_class_days": re.compile(
        r"Penalty for students having single events on a day\s*=\s*(\d+)"
    ),
    "last_slot": re.compile(
        r"Penalty for students having end of day events\s*=\s*(\d+)"
    ),
    "soft_violations": re.compile(r"Total soft constraint penalty\s*=\s*(\d+)"),
}


def parse_itc2007_pe_validator_output(
    stdout: str,
    *,
    returncode: int = 0,
    stderr: str = "",
) -> ITC2007PEOfficialValidation:
    values: dict[str, int] = {}
    for name, pattern in _OFFICIAL_FIELD_PATTERNS.items():
        matches = pattern.findall(stdout)
        if len(matches) != 1:
            raise ITC2007PEValidatorError(
                f"official PE validator field {name!r} occurred {len(matches)} times"
            )
        values[name] = int(matches[0])
    component_sum = (
        values["consecutive_excess"] + values["single_class_days"] + values["last_slot"]
    )
    if component_sum != values["soft_violations"]:
        raise ITC2007PEValidatorError(
            "official PE validator soft total disagrees with its components"
        )
    return ITC2007PEOfficialValidation(
        **values,
        returncode=int(returncode),
        stdout=stdout,
        stderr=stderr,
    )


def run_itc2007_pe_validator(
    executable: str | Path,
    instance_path: str | Path,
    solution_path: str | Path,
    *,
    timeout_seconds: float = 30.0,
) -> ITC2007PEOfficialValidation:
    """Run the official validator without requiring matching input basenames."""

    validator = Path(executable).resolve()
    instance = Path(instance_path).resolve()
    solution = Path(solution_path).resolve()
    if not validator.is_file():
        raise ITC2007PEValidatorError(f"validator does not exist: {validator}")
    if not instance.is_file() or not solution.is_file():
        raise ITC2007PEValidatorError("instance and solution files must exist")
    with tempfile.TemporaryDirectory(prefix="planora-pe-validator-") as directory:
        prefix = Path(directory) / "case"
        shutil.copyfile(instance, prefix.with_suffix(".tim"))
        shutil.copyfile(solution, prefix.with_suffix(".sln"))
        try:
            completed = subprocess.run(
                [str(validator), str(prefix)],
                input="\n",
                capture_output=True,
                text=True,
                timeout=max(0.1, float(timeout_seconds)),
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ITC2007PEValidatorError(
                f"official PE validator execution failed: {exc}"
            ) from exc
    if completed.returncode != 0:
        raise ITC2007PEValidatorError(
            f"official PE validator returned {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return parse_itc2007_pe_validator_output(
        completed.stdout,
        returncode=completed.returncode,
        stderr=completed.stderr,
    )


def _normalized_assignments(
    problem: ITC2007PEProblem,
    assignments: Sequence[ITC2007PEAssignment],
) -> tuple[ITC2007PEAssignment, ...]:
    if len(assignments) != problem.events:
        raise ValueError(
            f"ITC-2007 PE expected {problem.events} assignments, got {len(assignments)}"
        )
    by_event = {int(row.event): row for row in assignments}
    if set(by_event) != set(range(problem.events)) or len(by_event) != len(assignments):
        raise ValueError("ITC-2007 PE assignments must cover every event exactly once")
    return tuple(by_event[event] for event in range(problem.events))


def validate_itc2007_pe_solution(
    problem: ITC2007PEProblem,
    assignments: Sequence[ITC2007PEAssignment],
) -> ITC2007PEValidation:
    """Independently evaluate the official hard constraints and two-part score."""

    rows = _normalized_assignments(problem, assignments)
    errors: list[str] = []
    event_students = problem.event_students
    event_sizes = tuple(len(value) for value in event_students)
    placed: dict[int, ITC2007PEAssignment] = {}
    occupancy: dict[tuple[int, int], int] = {}
    student_slots: list[dict[int, int]] = [dict() for _ in range(problem.students)]

    for row in rows:
        event = int(row.event)
        slot = int(row.timeslot)
        room = int(row.room)
        if slot == -1 or room == -1:
            if (slot, room) != (-1, -1):
                errors.append(
                    f"event {event} must use either a complete placement or -1 -1"
                )
            continue
        if not 0 <= slot < TIMESLOTS:
            errors.append(f"event {event} has invalid timeslot {slot}")
            continue
        if not 0 <= room < problem.rooms:
            errors.append(f"event {event} has invalid room {room}")
            continue
        placed[event] = row
        if not problem.event_availability[event][slot]:
            errors.append(f"event {event} uses unavailable timeslot {slot}")
        if event_sizes[event] > problem.room_capacities[room]:
            errors.append(
                f"event {event} exceeds room {room} capacity "
                f"({event_sizes[event]}>{problem.room_capacities[room]})"
            )
        missing_features = [
            feature
            for feature, required in enumerate(problem.event_features[event])
            if required and not problem.room_features[room][feature]
        ]
        if missing_features:
            errors.append(
                f"event {event} room {room} lacks features {missing_features}"
            )
        key = (slot, room)
        if key in occupancy:
            errors.append(
                f"events {occupancy[key]} and {event} share room {room} at slot {slot}"
            )
        else:
            occupancy[key] = event
        for student in event_students[event]:
            if slot in student_slots[student]:
                errors.append(
                    f"student {student} attends events {student_slots[student][slot]} "
                    f"and {event} at slot {slot}"
                )
            else:
                student_slots[student][slot] = event

    precedence_pairs: set[tuple[int, int]] = set()
    for left in range(problem.events):
        for right in range(problem.events):
            relation = int(problem.precedence[left][right])
            if relation == 1:
                precedence_pairs.add((left, right))
            elif relation == -1:
                precedence_pairs.add((right, left))
    for before, after in sorted(precedence_pairs):
        if before in placed and after in placed:
            if int(placed[before].timeslot) >= int(placed[after].timeslot):
                errors.append(
                    f"precedence requires event {before} before event {after}"
                )

    distance = sum(
        event_sizes[event] for event in range(problem.events) if event not in placed
    )
    singleton = 0
    consecutive = 0
    last = 0
    for slots in student_slots:
        occupied_slots = set(slots)
        for day in range(DAYS):
            daily = [
                day * SLOTS_PER_DAY + within
                for within in range(SLOTS_PER_DAY)
                if day * SLOTS_PER_DAY + within in occupied_slots
            ]
            if len(daily) == 1:
                singleton += 1
            run = 0
            for within in range(SLOTS_PER_DAY):
                slot = day * SLOTS_PER_DAY + within
                if slot in occupied_slots:
                    run += 1
                    if run > 2:
                        consecutive += 1
                    if within == SLOTS_PER_DAY - 1:
                        last += 1
                else:
                    run = 0
    score = ITC2007PEScore(
        distance_to_feasibility=int(distance),
        single_class_days=int(singleton),
        consecutive_excess=int(consecutive),
        last_slot=int(last),
    )
    return ITC2007PEValidation(score=score, errors=tuple(errors))


def _eligible_rooms(problem: ITC2007PEProblem, event: int) -> tuple[int, ...]:
    size = problem.event_sizes[event]
    required = problem.event_features[event]
    return tuple(
        room
        for room in range(problem.rooms)
        if problem.room_capacities[room] >= size
        and all(
            not required[feature] or problem.room_features[room][feature]
            for feature in range(problem.features)
        )
    )


def _all_unplaced(problem: ITC2007PEProblem) -> tuple[ITC2007PEAssignment, ...]:
    return tuple(
        ITC2007PEAssignment(event=event, timeslot=-1, room=-1)
        for event in range(problem.events)
    )


def _student_soft_penalty(slots: set[int]) -> int:
    score = 0
    for day in range(DAYS):
        occupied = {
            slot - day * SLOTS_PER_DAY
            for slot in slots
            if day * SLOTS_PER_DAY <= slot < (day + 1) * SLOTS_PER_DAY
        }
        if len(occupied) == 1:
            score += 1
        run = 0
        for within in range(SLOTS_PER_DAY):
            if within in occupied:
                run += 1
                if run > 2:
                    score += 1
                if within == SLOTS_PER_DAY - 1:
                    score += 1
            else:
                run = 0
    return score


def _construct_itc2007_pe(
    problem: ITC2007PEProblem,
    *,
    deadline: float,
    seed: int,
    attempts: int = 3,
) -> tuple[tuple[ITC2007PEAssignment, ...], dict[str, object]]:
    """Build valid partial timetables quickly for CP hints and fallback use."""

    all_unplaced = _all_unplaced(problem)
    best = all_unplaced
    best_validation = validate_itc2007_pe_solution(problem, best)
    event_students = problem.event_students
    eligible_rooms = tuple(
        _eligible_rooms(problem, event) for event in range(problem.events)
    )
    available_slots = tuple(
        tuple(slot for slot, allowed in enumerate(row) if allowed)
        for row in problem.event_availability
    )
    conflict_degree = [0] * problem.events
    for attendances in problem.student_events:
        events = [event for event, attends in enumerate(attendances) if attends]
        for event in events:
            conflict_degree[event] += len(events) - 1
    predecessors: list[set[int]] = [set() for _ in range(problem.events)]
    successors: list[set[int]] = [set() for _ in range(problem.events)]
    for left in range(problem.events):
        for right in range(problem.events):
            relation = problem.precedence[left][right]
            if relation == 1:
                predecessors[right].add(left)
                successors[left].add(right)
            elif relation == -1:
                predecessors[left].add(right)
                successors[right].add(left)

    completed_attempts = 0
    for attempt in range(max(1, int(attempts))):
        if time.perf_counter() >= deadline:
            break
        rng = random.Random((int(seed) + 1) * 1_000_003 + attempt * 97)
        tie_break = [rng.random() for _ in range(problem.events)]
        if attempt % 3 == 0:
            order = sorted(
                range(problem.events),
                key=lambda event: (
                    len(available_slots[event]) * len(eligible_rooms[event]),
                    -problem.event_sizes[event],
                    -conflict_degree[event],
                    tie_break[event],
                ),
            )
        elif attempt % 3 == 1:
            order = sorted(
                range(problem.events),
                key=lambda event: (
                    -problem.event_sizes[event],
                    len(available_slots[event]) * len(eligible_rooms[event]),
                    -conflict_degree[event],
                    tie_break[event],
                ),
            )
        else:
            order = sorted(
                range(problem.events),
                key=lambda event: (
                    -conflict_degree[event],
                    len(available_slots[event]) * len(eligible_rooms[event]),
                    -problem.event_sizes[event],
                    tie_break[event],
                ),
            )

        rows = [ITC2007PEAssignment(event, -1, -1) for event in range(problem.events)]
        room_occupancy: set[tuple[int, int]] = set()
        student_slots: list[set[int]] = [set() for _ in range(problem.students)]
        student_scores = [0] * problem.students
        for position, event in enumerate(order):
            if position % 8 == 0 and time.perf_counter() >= deadline:
                break
            candidates: list[tuple[tuple[int, int, int, float], int, int]] = []
            for slot in available_slots[event]:
                if any(
                    slot in student_slots[student] for student in event_students[event]
                ):
                    continue
                if any(
                    rows[before].placed and rows[before].timeslot >= slot
                    for before in predecessors[event]
                ):
                    continue
                if any(
                    rows[after].placed and rows[after].timeslot <= slot
                    for after in successors[event]
                ):
                    continue
                rooms = [
                    room
                    for room in eligible_rooms[event]
                    if (slot, room) not in room_occupancy
                ]
                if not rooms:
                    continue
                delta = 0
                for student in event_students[event]:
                    updated = set(student_slots[student])
                    updated.add(slot)
                    delta += _student_soft_penalty(updated) - student_scores[student]
                room = min(
                    rooms,
                    key=lambda candidate: (
                        problem.room_capacities[candidate] - problem.event_sizes[event],
                        candidate,
                    ),
                )
                occupancy = sum(
                    1
                    for occupied_slot, _room in room_occupancy
                    if occupied_slot == slot
                )
                candidates.append(
                    (
                        (
                            delta,
                            occupancy,
                            problem.room_capacities[room] - problem.event_sizes[event],
                            rng.random(),
                        ),
                        slot,
                        room,
                    )
                )
            if not candidates:
                continue
            _rank, slot, room = min(candidates, key=lambda item: item[0])
            rows[event] = ITC2007PEAssignment(event, slot, room)
            room_occupancy.add((slot, room))
            for student in event_students[event]:
                student_slots[student].add(slot)
                student_scores[student] = _student_soft_penalty(student_slots[student])

        validation = validate_itc2007_pe_solution(problem, rows)
        if (
            validation.feasible
            and validation.score.lexicographic < best_validation.score.lexicographic
        ):
            best = tuple(rows)
            best_validation = validation
        completed_attempts += 1

    return best, {
        "attempts_requested": max(1, int(attempts)),
        "attempts_completed": completed_attempts,
        "score": list(best_validation.score.lexicographic),
        "placed_events": sum(row.placed for row in best),
    }


def _hall_room_sets(
    room_masks: Sequence[int],
    *,
    closure_limit: int = 4_096,
) -> tuple[int, ...] | None:
    """Return the exact room-set closure used by the projected room model.

    Hall constraints only need room sets that are unions of event neighbourhoods:
    a violating event set has exactly such a union as its neighbourhood.  The
    closure is normally tiny on PE instances, but is explicitly bounded so a
    feature-rich institution cannot make model construction exponential.
    """

    closure = {0}
    for mask in sorted(set(int(value) for value in room_masks if value)):
        closure.update(value | mask for value in tuple(closure))
        if len(closure) > max(1, int(closure_limit)):
            return None
    return tuple(sorted(value for value in closure if value))


def _room_matching(
    problem: ITC2007PEProblem,
    events: Sequence[int],
) -> tuple[dict[int, int] | None, int | None]:
    """Find a deterministic maximum event-to-room matching.

    When matching is impossible, the second return value is a Hall-deficient
    room neighbourhood.  It can be fed back to the projected CP model as a
    globally valid cut.
    """

    ordered = sorted(
        (int(event) for event in events),
        key=lambda event: (
            len(_eligible_rooms(problem, event)),
            -problem.event_sizes[event],
            event,
        ),
    )
    event_rooms = {event: _eligible_rooms(problem, event) for event in ordered}
    room_event: dict[int, int] = {}

    def augment(event: int, seen_rooms: set[int]) -> bool:
        for room in event_rooms[event]:
            if room in seen_rooms:
                continue
            seen_rooms.add(room)
            occupying = room_event.get(room)
            if occupying is None or augment(occupying, seen_rooms):
                room_event[room] = event
                return True
        return False

    unmatched: list[int] = []
    for event in ordered:
        if not augment(event, set()):
            unmatched.append(event)
    if not unmatched:
        return {event: room for room, event in room_event.items()}, None

    # Alternating reachability from every unmatched event gives a Hall witness:
    # reachable events A have fewer reachable neighbouring rooms N(A).
    event_room = {event: room for room, event in room_event.items()}
    reachable_events = set(unmatched)
    reachable_rooms: set[int] = set()
    queue: deque[int] = deque(unmatched)
    while queue:
        event = queue.popleft()
        matched_room = event_room.get(event)
        for room in event_rooms[event]:
            if room == matched_room or room in reachable_rooms:
                continue
            reachable_rooms.add(room)
            occupying = room_event.get(room)
            if occupying is not None and occupying not in reachable_events:
                reachable_events.add(occupying)
                queue.append(occupying)
    witness = sum(1 << room for room in reachable_rooms)
    if not witness or len(reachable_events) <= len(reachable_rooms):
        # This should be unreachable for a maximum bipartite matching.  Refuse
        # to manufacture a potentially invalid cut if the invariant is broken.
        return None, None
    return None, witness


def _projected_cp_itc2007_pe(
    problem: ITC2007PEProblem,
    initial: Sequence[ITC2007PEAssignment],
    *,
    deadline: float,
    seed: int,
    workers: int,
) -> tuple[tuple[ITC2007PEAssignment, ...], dict[str, object]]:
    """Optimize PE feasibility in the time projection with exact room cuts.

    The dense event-time-room model repeats each timeslot literal for every
    compatible room.  This projection keeps one literal per event-timeslot and
    enforces room feasibility through Hall inequalities.  A deterministic
    matching lifts the result back to rooms.  If the static Hall closure is too
    large, valid witness cuts are added between bounded CP-SAT rounds.
    """

    try:
        normalized_initial = _normalized_assignments(problem, initial)
        initial_validation = validate_itc2007_pe_solution(problem, normalized_initial)
    except ValueError:
        normalized_initial = _all_unplaced(problem)
        initial_validation = validate_itc2007_pe_solution(problem, normalized_initial)
        initial_status = "invalid_initial_replaced"
    else:
        initial_status = "initial"
        if not initial_validation.feasible:
            normalized_initial = _all_unplaced(problem)
            initial_validation = validate_itc2007_pe_solution(
                problem, normalized_initial
            )
            initial_status = "invalid_initial_replaced"
    if time.perf_counter() >= deadline:
        return normalized_initial, {
            "status": "deadline_before_projection",
            "returned_source": initial_status,
            "rounds": 0,
            "hall_mode": "not_started",
        }

    eligible_rooms = tuple(
        _eligible_rooms(problem, event) for event in range(problem.events)
    )
    event_students = problem.event_students
    room_masks = tuple(sum(1 << room for room in rooms) for rooms in eligible_rooms)
    available_slots = tuple(
        tuple(slot for slot, allowed in enumerate(row) if allowed)
        for row in problem.event_availability
    )
    model = cp_model.CpModel()
    time_slot: dict[tuple[int, int], cp_model.IntVar] = {}
    unplaced: list[cp_model.IntVar] = []
    time_vars: list[cp_model.IntVar] = []

    for event in range(problem.events):
        _check_deadline(deadline, "projected placement-domain construction")
        choices: list[cp_model.IntVar] = []
        if room_masks[event]:
            for slot in available_slots[event]:
                variable = model.NewBoolVar(f"y_e{event}_t{slot}")
                time_slot[(event, slot)] = variable
                choices.append(variable)
        missing = model.NewBoolVar(f"projected_unplaced_{event}")
        model.AddExactlyOne([*choices, missing])
        unplaced.append(missing)
        event_time = model.NewIntVar(0, TIMESLOTS, f"projected_time_{event}")
        model.Add(
            event_time
            == sum(
                slot * time_slot[(event, slot)]
                for slot in available_slots[event]
                if (event, slot) in time_slot
            )
            + TIMESLOTS * missing
        )
        time_vars.append(event_time)

    # Each student-slot constraint is a native clique over projected literals;
    # this avoids expanding tens of thousands of integer disequalities.
    student_slot_cliques = 0
    for student, attendances in enumerate(problem.student_events):
        if student % 16 == 0:
            _check_deadline(deadline, "projected student-clique construction")
        events = [event for event, attends in enumerate(attendances) if attends]
        for slot in range(TIMESLOTS):
            variables = [
                time_slot[(event, slot)]
                for event in events
                if (event, slot) in time_slot
            ]
            if len(variables) > 1:
                model.AddAtMostOne(variables)
                student_slot_cliques += 1

    precedence_pairs: set[tuple[int, int]] = set()
    for left in range(problem.events):
        for right in range(problem.events):
            relation = int(problem.precedence[left][right])
            if relation == 1:
                precedence_pairs.add((left, right))
            elif relation == -1:
                precedence_pairs.add((right, left))
    for before, after in sorted(precedence_pairs):
        model.Add(time_vars[before] < time_vars[after]).OnlyEnforceIf(
            [unplaced[before].Not(), unplaced[after].Not()]
        )

    hall_sets = _hall_room_sets(room_masks)
    hall_mode = "static_exact" if hall_sets is not None else "witness_cuts"
    static_hall_cuts = 0
    base_sets = hall_sets
    if base_sets is None:
        base_sets = tuple(sorted({mask for mask in room_masks if mask}))
        all_rooms = (1 << problem.rooms) - 1
        if all_rooms:
            base_sets = tuple(sorted({*base_sets, all_rooms}))
    for room_set_index, room_set in enumerate(base_sets):
        if room_set_index % 8 == 0:
            _check_deadline(deadline, "projected Hall-cut construction")
        capacity = int(room_set.bit_count())
        eligible_events = [
            event
            for event, mask in enumerate(room_masks)
            if mask and not mask & ~room_set
        ]
        if len(eligible_events) <= capacity:
            continue
        for slot in range(TIMESLOTS):
            variables = [
                time_slot[(event, slot)]
                for event in eligible_events
                if (event, slot) in time_slot
            ]
            if len(variables) > capacity:
                model.Add(sum(variables) <= capacity)
                static_hall_cuts += 1

    distance = sum(
        problem.event_sizes[event] * unplaced[event] for event in range(problem.events)
    )
    initial_distance = int(initial_validation.score.distance_to_feasibility)
    if initial_distance > 0:
        model.Add(distance <= initial_distance - 1)
        model.Minimize(distance)
    else:
        # Distance is already globally optimal at zero.  Avoid the historical
        # flat objective by optimizing the exact published student soft terms;
        # keep this extra model surface off the large incomplete-schedule path.
        model.Add(distance == 0)
        soft_terms: list[cp_model.LinearExprT] = []
        for student, attendances in enumerate(problem.student_events):
            if student % 16 == 0:
                _check_deadline(deadline, "projected soft-objective construction")
            events = [event for event, attends in enumerate(attendances) if attends]
            occupied: dict[int, cp_model.IntVar] = {}
            for slot in range(TIMESLOTS):
                variables = [
                    time_slot[(event, slot)]
                    for event in events
                    if (event, slot) in time_slot
                ]
                marker = model.NewBoolVar(f"projected_student_{student}_slot_{slot}")
                if variables:
                    model.Add(marker == sum(variables))
                else:
                    model.Add(marker == 0)
                occupied[slot] = marker
            for day in range(DAYS):
                daily = [
                    occupied[day * SLOTS_PER_DAY + within]
                    for within in range(SLOTS_PER_DAY)
                ]
                count = model.NewIntVar(
                    0,
                    SLOTS_PER_DAY,
                    f"projected_student_{student}_day_{day}_count",
                )
                model.Add(count == sum(daily))
                singleton = model.NewBoolVar(
                    f"projected_student_{student}_day_{day}_singleton"
                )
                model.Add(count == 1).OnlyEnforceIf(singleton)
                model.Add(count != 1).OnlyEnforceIf(singleton.Not())
                soft_terms.append(singleton)
                soft_terms.append(daily[-1])
                for within in range(SLOTS_PER_DAY - 2):
                    triple = model.NewBoolVar(
                        f"projected_student_{student}_day_{day}_triple_{within}"
                    )
                    members = daily[within : within + 3]
                    model.AddBoolAnd(members).OnlyEnforceIf(triple)
                    model.AddBoolOr([member.Not() for member in members]).OnlyEnforceIf(
                        triple.Not()
                    )
                    soft_terms.append(triple)
        model.Minimize(sum(soft_terms))
    # A bounded seeded incumbent repair gives CP-SAT a feasible target despite
    # the strict objective cut.  Removing a small conflicting neighbourhood
    # before inserting an unplaced event generalizes the constructor's
    # irrevocable choices into a one-step ejection chain.
    repair_rows = list(normalized_initial)
    repair_distance = initial_distance
    occupied_room = {
        (row.timeslot, row.room): row.event for row in repair_rows if row.placed
    }
    occupied_students: list[dict[int, int]] = [{} for _ in range(problem.students)]
    for row in repair_rows:
        if not row.placed:
            continue
        for student in event_students[row.event]:
            occupied_students[student][row.timeslot] = row.event
    predecessors: list[set[int]] = [set() for _ in range(problem.events)]
    successors: list[set[int]] = [set() for _ in range(problem.events)]
    for before, after in precedence_pairs:
        predecessors[after].add(before)
        successors[before].add(after)
    ejection_attempts = 0
    ejection_improvements = 0
    for event in sorted(
        (row.event for row in repair_rows if not row.placed),
        key=lambda candidate: (-problem.event_sizes[candidate], candidate),
    ):
        if ejection_attempts >= 256 or time.perf_counter() >= deadline:
            break
        ejection_attempts += 1
        best_move: tuple[int, int, tuple[int, ...], int] | None = None
        for slot in available_slots[event]:
            if any(
                repair_rows[before].placed and repair_rows[before].timeslot >= slot
                for before in predecessors[event]
            ) or any(
                repair_rows[after].placed and repair_rows[after].timeslot <= slot
                for after in successors[event]
            ):
                continue
            student_conflicts = {
                occupied_students[student][slot]
                for student in event_students[event]
                if slot in occupied_students[student]
            }
            for room in eligible_rooms[event]:
                conflicts = set(student_conflicts)
                room_conflict = occupied_room.get((slot, room))
                if room_conflict is not None:
                    conflicts.add(room_conflict)
                delta = (
                    sum(problem.event_sizes[value] for value in conflicts)
                    - problem.event_sizes[event]
                )
                rank = (delta, len(conflicts), slot, room)
                if delta < 0 and (
                    best_move is None
                    or rank
                    < (best_move[3], len(best_move[2]), best_move[0], best_move[1])
                ):
                    best_move = (slot, room, tuple(sorted(conflicts)), delta)
        if best_move is None:
            continue
        slot, room, conflicts, delta = best_move
        for conflict in conflicts:
            old = repair_rows[conflict]
            occupied_room.pop((old.timeslot, old.room), None)
            for student in event_students[conflict]:
                occupied_students[student].pop(old.timeslot, None)
            repair_rows[conflict] = ITC2007PEAssignment(conflict, -1, -1)
        # Ejecting an endpoint can make an already placed precedence partner
        # unconstrained, which is legal; inserting an endpoint may not violate
        # any still-placed partner because that was checked above.
        repair_rows[event] = ITC2007PEAssignment(event, slot, room)
        occupied_room[(slot, room)] = event
        for student in event_students[event]:
            occupied_students[student][slot] = event
        repair_distance += delta
        ejection_improvements += 1
    repair = tuple(repair_rows)
    repair_validation = validate_itc2007_pe_solution(problem, repair)
    if not repair_validation.feasible or repair_distance > initial_distance:
        repair = normalized_initial
        repair_distance = initial_distance
        ejection_improvements = 0
    if (
        repair_validation.feasible
        and repair_validation.score.lexicographic
        < initial_validation.score.lexicographic
    ):
        best = repair
        best_validation = repair_validation
    else:
        best = normalized_initial
        best_validation = initial_validation
    improvement_found = (
        best_validation.score.lexicographic < initial_validation.score.lexicographic
    )
    for event, row in enumerate(repair):
        for slot in available_slots[event]:
            variable = time_slot.get((event, slot))
            if variable is not None:
                model.AddHint(variable, int(row.placed and row.timeslot == slot))
        model.AddHint(unplaced[event], int(not row.placed))
        model.AddHint(time_vars[event], row.timeslot if row.placed else TIMESLOTS)

    rounds = 0
    dynamic_hall_cuts = 0
    raw_status = int(cp_model.UNKNOWN)
    best_bound: int | None = None
    search_seconds = 0.0
    invalid_lifts = 0
    while time.perf_counter() < deadline:
        rounds += 1
        remaining = max(0.0, deadline - time.perf_counter())
        if remaining <= 0.01:
            break
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(
            0.005, remaining - min(0.03, remaining * 0.02)
        )
        solver.parameters.num_search_workers = max(1, int(workers))
        solver.parameters.random_seed = int(seed) + rounds - 1
        solver.parameters.cp_model_probing_level = 0
        solver.parameters.symmetry_level = 0
        solver.parameters.max_presolve_iterations = 1
        solver.parameters.search_branching = (
            cp_model.HINT_SEARCH if initial_distance > 0 else cp_model.AUTOMATIC_SEARCH
        )
        solver.parameters.repair_hint = False
        search_started = time.perf_counter()
        raw_status = int(solver.Solve(model))
        search_seconds += time.perf_counter() - search_started
        if raw_status not in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}:
            break
        # The projected objective is a non-negative integer distance.  Some
        # OR-Tools versions can expose a tiny negative numeric bound around
        # zero on interrupted searches; never serialize that as a meaningful
        # official lower bound.
        best_bound = max(0, int(round(solver.BestObjectiveBound())))
        solver_objective = int(round(solver.ObjectiveValue()))

        slot_events: dict[int, list[int]] = defaultdict(list)
        selected_slots: list[int] = [-1] * problem.events
        for event in range(problem.events):
            for slot in available_slots[event]:
                variable = time_slot.get((event, slot))
                if variable is not None and solver.BooleanValue(variable):
                    selected_slots[event] = slot
                    slot_events[slot].append(event)
                    break
        matchings: dict[int, dict[int, int]] = {}
        witnesses: list[tuple[int, int]] = []
        for slot, events in sorted(slot_events.items()):
            matching, witness = _room_matching(problem, events)
            if matching is None:
                if witness is None:
                    witnesses = []
                    invalid_lifts += 1
                    break
                witnesses.append((slot, witness))
            else:
                matchings[slot] = matching
        if witnesses:
            for slot, room_set in witnesses:
                capacity = int(room_set.bit_count())
                variables = [
                    time_slot[(event, slot)]
                    for event, mask in enumerate(room_masks)
                    if mask and not mask & ~room_set and (event, slot) in time_slot
                ]
                if len(variables) > capacity:
                    model.Add(sum(variables) <= capacity)
                    dynamic_hall_cuts += 1
            continue
        if any(slot >= 0 and slot not in matchings for slot in selected_slots):
            break

        candidate = tuple(
            ITC2007PEAssignment(
                event=event,
                timeslot=slot,
                room=matchings[slot][event],
            )
            if slot >= 0
            else ITC2007PEAssignment(event=event, timeslot=-1, room=-1)
            for event, slot in enumerate(selected_slots)
        )
        candidate_validation = validate_itc2007_pe_solution(problem, candidate)
        if (
            candidate_validation.feasible
            and candidate_validation.score.lexicographic
            < best_validation.score.lexicographic
        ):
            best = candidate
            best_validation = candidate_validation
            improvement_found = True
        elif not candidate_validation.feasible:
            invalid_lifts += 1
        break

    status_names = {
        int(cp_model.UNKNOWN): "unknown",
        int(cp_model.MODEL_INVALID): "model_invalid",
        int(cp_model.FEASIBLE): "feasible",
        int(cp_model.INFEASIBLE): "infeasible",
        int(cp_model.OPTIMAL): "optimal",
    }
    return best, {
        "status": status_names.get(raw_status, f"status_{raw_status}"),
        "returned_source": ("projected_cp" if improvement_found else "initial"),
        "rounds": rounds,
        "hall_mode": hall_mode,
        "static_hall_cuts": static_hall_cuts,
        "dynamic_hall_cuts": dynamic_hall_cuts,
        "invalid_lifts": invalid_lifts,
        "projected_literals": len(time_slot),
        "student_slot_cliques": student_slot_cliques,
        "precedence_pairs": len(precedence_pairs),
        "initial_distance": initial_distance,
        "repair_distance": repair_distance,
        "ejection_attempts": ejection_attempts,
        "ejection_improvements": ejection_improvements,
        "final_distance": int(best_validation.score.distance_to_feasibility),
        "best_bound": best_bound,
        "solver_objective": (
            solver_objective
            if raw_status in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
            else None
        ),
        "search_seconds": float(search_seconds),
    }


def solve_itc2007_pe(
    problem: ITC2007PEProblem,
    *,
    time_limit_seconds: float,
    seed: int = 0,
    workers: int = 1,
) -> ITC2007PESolveResult:
    """Solve the native PE-CTT model under its official lexicographic objective.

    Unplaced events are legal, so the all-unplaced schedule is a valid, bounded
    fallback even when model construction or search exhausts the deadline.
    """

    started = time.perf_counter()
    deadline = started + max(0.0, float(time_limit_seconds))
    all_unplaced = _all_unplaced(problem)
    if time.perf_counter() >= deadline:
        validation = validate_itc2007_pe_solution(problem, all_unplaced)
        elapsed = time.perf_counter() - started
        return ITC2007PESolveResult(
            assignments=all_unplaced,
            validation=validation,
            status="deadline_before_construction",
            raw_status=int(cp_model.UNKNOWN),
            objective_value=None,
            best_bound=None,
            build_seconds=float(elapsed),
            search_seconds=0.0,
            elapsed_seconds=float(elapsed),
            deadline_overrun_seconds=max(0.0, time.perf_counter() - deadline),
            seed=int(seed),
            workers=max(1, int(workers)),
            telemetry={"returned_source": "all_unplaced_fallback"},
        )
    estimated_placement_literals = sum(
        sum(problem.event_availability[event]) * len(_eligible_rooms(problem, event))
        for event in range(problem.events)
    )
    scale_gated = (
        estimated_placement_literals > 15_000 or problem.students * TIMESLOTS > 10_000
    )
    constructive_telemetry: dict[str, object] = {
        "attempts_requested": 0,
        "attempts_completed": 0,
        "score": list(
            validate_itc2007_pe_solution(problem, all_unplaced).score.lexicographic
        ),
        "placed_events": 0,
    }
    fallback = all_unplaced
    if time.perf_counter() < deadline:
        constructive_budget = min(
            2.0 if scale_gated else 0.75,
            max(0.01, float(time_limit_seconds) * (0.20 if scale_gated else 0.08)),
        )
        completion_reserve = min(0.05, max(0.002, time_limit_seconds * 0.02))
        constructive_deadline = min(
            deadline - completion_reserve,
            time.perf_counter() + constructive_budget,
        )
        if scale_gated:
            # Large PE instances benefit from dynamic event ordering and exact
            # per-period rematching.  Import lazily to keep the standalone
            # parser/validator free of a module cycle.
            from benchmarks.itc2007_pe_constructive import (
                construct_itc2007_pe_dsat,
            )

            fallback, dsat_telemetry = construct_itc2007_pe_dsat(
                problem,
                deadline=float(constructive_deadline),
                seed=int(seed),
                attempts=12,
            )
            fallback_validation = validate_itc2007_pe_solution(problem, fallback)
            constructive_telemetry = {
                **asdict(dsat_telemetry),
                "strategy": "dynamic_list_coloring_with_exact_room_rematching",
                "score": list(fallback_validation.score.lexicographic),
                "placed_events": sum(row.placed for row in fallback),
            }
        else:
            fallback, constructive_telemetry = _construct_itc2007_pe(
                problem,
                deadline=float(constructive_deadline),
                seed=int(seed),
                attempts=3,
            )
    fallback_validation = validate_itc2007_pe_solution(problem, fallback)
    fallback_source = (
        "constructive_fallback"
        if any(row.placed for row in fallback)
        else "all_unplaced_fallback"
    )
    if scale_gated:
        projection_started = time.perf_counter()
        completion_reserve = min(
            1.50,
            max(0.25, float(time_limit_seconds) * 0.15),
        )
        projected_deadline = max(
            time.perf_counter(),
            deadline - completion_reserve,
        )
        projected_telemetry: dict[str, object] = {
            "status": "deadline_before_projection",
            "returned_source": "initial",
            "rounds": 0,
        }
        dense_projection_prefer_partial = bool(
            int(estimated_placement_literals) >= 30_000
            and int(fallback_validation.score.distance_to_feasibility) > 0
        )
        if time.perf_counter() < deadline:
            try:
                if dense_projection_prefer_partial:
                    # A dense projected master can spend the whole remaining
                    # budget proving no incumbent before the partial timetable
                    # has been repaired.  The latter exposes a much smaller,
                    # immediately useful insert/eject state space.  Route by
                    # representation size, not by benchmark instance name.
                    projected = fallback
                    projected_telemetry = {
                        "status": "skipped_dense_projection_for_partial_search",
                        "returned_source": "initial",
                        "rounds": 0,
                        "search_seconds": 0.0,
                        "estimated_placement_literals": int(
                            estimated_placement_literals
                        ),
                        "literal_threshold": 30_000,
                    }
                else:
                    projected, projected_telemetry = _projected_cp_itc2007_pe(
                        problem,
                        fallback,
                        deadline=projected_deadline,
                        seed=int(seed),
                        workers=max(1, int(workers)),
                    )
                repair_telemetry: dict[str, object] = {
                    "accepted": False,
                    "reason": "superseded_by_partial_local_search",
                }
                projected_telemetry["post_projected_repair"] = repair_telemetry
                local_search_telemetry: dict[str, object] = {
                    "status": "skipped_insufficient_time",
                    "improved": False,
                    "service_acceptance": {
                        "accepted": False,
                        "reason": "skipped_insufficient_time",
                    },
                }
                local_candidate_selected = False
                local_search_deadline = deadline - min(
                    0.08,
                    max(0.02, float(time_limit_seconds) * 0.008),
                )
                if time.perf_counter() < local_search_deadline:
                    from benchmarks.itc2007_pe_local_search import (
                        optimize_itc2007_pe_partial,
                    )

                    local_result = optimize_itc2007_pe_partial(
                        problem,
                        projected,
                        deadline=float(local_search_deadline),
                        seed=int(seed) + 700_001,
                        max_iterations=20_000,
                        candidate_slots=16,
                        extra_blocker_pool=7,
                    )
                    local_search_telemetry = local_result.to_dict()
                    local_overrun_seconds = max(
                        0.0,
                        time.perf_counter() - float(local_search_deadline),
                    )
                    local_search_telemetry["deadline_overrun_seconds"] = float(
                        local_overrun_seconds
                    )
                    if local_overrun_seconds > 0.0:
                        local_search_telemetry["service_acceptance"] = {
                            "accepted": False,
                            "reason": "partial_local_search_deadline_overrun",
                            "deadline_overrun_seconds": float(
                                local_overrun_seconds
                            ),
                        }
                    elif local_result.improved:
                        projected = local_result.assignments
                        local_candidate_selected = True
                    else:
                        local_search_telemetry["service_acceptance"] = {
                            "accepted": False,
                            "reason": "candidate_not_strictly_better",
                        }
                projected_validation = validate_itc2007_pe_solution(problem, projected)
                projected_accepted = bool(
                    projected_validation.feasible
                    and projected_validation.score.lexicographic
                    < fallback_validation.score.lexicographic
                )
                if projected_accepted:
                    if local_candidate_selected:
                        local_search_telemetry["service_acceptance"] = {
                            "accepted": True,
                            "reason": "strictly_improving_candidate",
                            "incumbent_score": list(
                                fallback_validation.score.lexicographic
                            ),
                            "candidate_score": list(
                                projected_validation.score.lexicographic
                            ),
                        }
                    fallback = projected
                    fallback_validation = projected_validation
                    fallback_source = (
                        "partial_local_search"
                        if local_candidate_selected
                        else "projected_cp"
                    )
                elif local_candidate_selected:
                    local_search_telemetry["service_acceptance"] = {
                        "accepted": False,
                        "reason": (
                            "candidate_validation_failed"
                            if not projected_validation.feasible
                            else "candidate_not_strictly_better"
                        ),
                        "incumbent_score": list(
                            fallback_validation.score.lexicographic
                        ),
                        "candidate_score": list(
                            projected_validation.score.lexicographic
                        ),
                    }
                projected_telemetry["partial_local_search"] = local_search_telemetry
            except Exception as exc:
                projected_telemetry = {
                    "status": "projection_failed_closed",
                    "returned_source": "initial",
                    "rounds": 0,
                    "error_type": type(exc).__name__,
                    "detail": str(exc),
                }
        finished = time.perf_counter()
        projected_search_seconds = float(projected_telemetry.get("search_seconds", 0.0))
        return ITC2007PESolveResult(
            assignments=fallback,
            validation=fallback_validation,
            status=(
                "partial_local_search_feasible"
                if fallback_source == "partial_local_search"
                else "projected_feasible"
                if fallback_source == "projected_cp"
                else "constructive_feasible"
            ),
            raw_status=int(cp_model.UNKNOWN),
            objective_value=None,
            best_bound=None,
            build_seconds=max(
                0.0,
                float(finished - started) - projected_search_seconds,
            ),
            search_seconds=projected_search_seconds,
            elapsed_seconds=float(finished - started),
            deadline_overrun_seconds=max(0.0, finished - deadline),
            seed=int(seed),
            workers=max(1, int(workers)),
            telemetry={
                "returned_source": fallback_source,
                "constructive": constructive_telemetry,
                "native_cp_skipped_reason": "scale_gate",
                "projected_cp": projected_telemetry,
                "projection_elapsed_seconds": float(finished - projection_started),
                "estimated_placement_literals": estimated_placement_literals,
                "student_slot_markers": problem.students * TIMESLOTS,
                "dense_projection_prefer_partial": bool(
                    dense_projection_prefer_partial
                ),
            },
        )
    model = cp_model.CpModel()
    placement: dict[tuple[int, int, int], cp_model.IntVar] = {}
    event_placements: list[list[tuple[int, int, cp_model.IntVar]]] = [
        [] for _ in range(problem.events)
    ]
    slot_vars: dict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)
    room_slot_vars: dict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)
    placed_vars: list[cp_model.IntVar] = []
    unplaced_vars: list[cp_model.IntVar] = []
    time_vars: list[cp_model.IntVar] = []

    try:
        for event in range(problem.events):
            _check_deadline(deadline, "placement-domain construction")
            choices: list[cp_model.IntVar] = []
            eligible_rooms = _eligible_rooms(problem, event)
            for slot, available in enumerate(problem.event_availability[event]):
                if not available:
                    continue
                for room in eligible_rooms:
                    variable = model.NewBoolVar(f"x_e{event}_t{slot}_r{room}")
                    placement[(event, slot, room)] = variable
                    event_placements[event].append((slot, room, variable))
                    choices.append(variable)
                    slot_vars[(event, slot)].append(variable)
                    room_slot_vars[(slot, room)].append(variable)
            placed = model.NewBoolVar(f"placed_{event}")
            unplaced = model.NewBoolVar(f"unplaced_{event}")
            model.AddExactlyOne([*choices, unplaced])
            model.Add(placed + unplaced == 1)
            placed_vars.append(placed)
            unplaced_vars.append(unplaced)
            time_var = model.NewIntVar(0, TIMESLOTS, f"time_{event}")
            if choices:
                model.Add(
                    time_var
                    == sum(
                        slot * variable
                        for slot, _room, variable in event_placements[event]
                    )
                    + TIMESLOTS * unplaced
                )
            else:
                model.Add(time_var == TIMESLOTS)
            time_vars.append(time_var)

        for variables in room_slot_vars.values():
            _check_deadline(deadline, "room-occupation constraints")
            model.AddAtMostOne(variables)

        conflict_pairs: set[tuple[int, int]] = set()
        for attendances in problem.student_events:
            events = [event for event, attends in enumerate(attendances) if attends]
            for index, left in enumerate(events):
                for right in events[index + 1 :]:
                    conflict_pairs.add((left, right))
        for left, right in sorted(conflict_pairs):
            _check_deadline(deadline, "student-conflict constraints")
            model.Add(time_vars[left] != time_vars[right]).OnlyEnforceIf(
                [placed_vars[left], placed_vars[right]]
            )

        precedence_pairs: set[tuple[int, int]] = set()
        for left in range(problem.events):
            for right in range(problem.events):
                relation = problem.precedence[left][right]
                if relation == 1:
                    precedence_pairs.add((left, right))
                elif relation == -1:
                    precedence_pairs.add((right, left))
        for before, after in sorted(precedence_pairs):
            _check_deadline(deadline, "precedence constraints")
            model.Add(time_vars[before] < time_vars[after]).OnlyEnforceIf(
                [placed_vars[before], placed_vars[after]]
            )

        singleton_terms: list[cp_model.IntVar] = []
        consecutive_terms: list[cp_model.IntVar] = []
        last_terms: list[cp_model.IntVar] = []
        for student, attendances in enumerate(problem.student_events):
            _check_deadline(deadline, "student-soft-objective construction")
            student_events = [
                event for event, attends in enumerate(attendances) if attends
            ]
            occupied: dict[int, cp_model.IntVar] = {}
            for slot in range(TIMESLOTS):
                variables = [
                    variable
                    for event in student_events
                    for variable in slot_vars.get((event, slot), ())
                ]
                marker = model.NewBoolVar(f"student_{student}_slot_{slot}")
                if variables:
                    model.Add(marker == sum(variables))
                else:
                    model.Add(marker == 0)
                occupied[slot] = marker
            for day in range(DAYS):
                count = model.NewIntVar(
                    0, SLOTS_PER_DAY, f"student_{student}_day_{day}_count"
                )
                model.Add(
                    count
                    == sum(
                        occupied[day * SLOTS_PER_DAY + within]
                        for within in range(SLOTS_PER_DAY)
                    )
                )
                singleton = model.NewBoolVar(f"student_{student}_day_{day}_singleton")
                model.Add(count == 1).OnlyEnforceIf(singleton)
                model.Add(count != 1).OnlyEnforceIf(singleton.Not())
                singleton_terms.append(singleton)
                last_terms.append(occupied[day * SLOTS_PER_DAY + SLOTS_PER_DAY - 1])
                for within in range(SLOTS_PER_DAY - 2):
                    triple = model.NewBoolVar(
                        f"student_{student}_day_{day}_triple_{within}"
                    )
                    members = [
                        occupied[day * SLOTS_PER_DAY + within + offset]
                        for offset in range(3)
                    ]
                    model.AddBoolAnd(members).OnlyEnforceIf(triple)
                    model.AddBoolOr([member.Not() for member in members]).OnlyEnforceIf(
                        triple.Not()
                    )
                    consecutive_terms.append(triple)

        soft_upper = max(1, problem.students * (DAYS + DAYS + DAYS * 7))
        distance = sum(
            problem.event_sizes[event] * (1 - placed_vars[event])
            for event in range(problem.events)
        )
        soft = sum(singleton_terms) + sum(consecutive_terms) + sum(last_terms)
        model.Minimize(distance * (soft_upper + 1) + soft)
        for event, row in enumerate(fallback):
            if row.placed:
                hinted = placement.get((event, int(row.timeslot), int(row.room)))
                if hinted is not None:
                    model.AddHint(hinted, 1)
                    model.AddHint(placed_vars[event], 1)
            else:
                model.AddHint(unplaced_vars[event], 1)
    except ITC2007PEDeadline:
        elapsed = time.perf_counter() - started
        return ITC2007PESolveResult(
            assignments=fallback,
            validation=fallback_validation,
            status="deadline_during_build",
            raw_status=int(cp_model.UNKNOWN),
            objective_value=None,
            best_bound=None,
            build_seconds=float(elapsed),
            search_seconds=0.0,
            elapsed_seconds=float(elapsed),
            deadline_overrun_seconds=max(0.0, time.perf_counter() - deadline),
            seed=int(seed),
            workers=int(workers),
            telemetry={
                "returned_source": fallback_source,
                "constructive": constructive_telemetry,
            },
        )

    build_seconds = time.perf_counter() - started
    remaining = max(0.0, deadline - time.perf_counter())
    if remaining <= 0:
        return ITC2007PESolveResult(
            assignments=fallback,
            validation=fallback_validation,
            status="deadline_after_build",
            raw_status=int(cp_model.UNKNOWN),
            objective_value=None,
            best_bound=None,
            build_seconds=float(build_seconds),
            search_seconds=0.0,
            elapsed_seconds=float(time.perf_counter() - started),
            deadline_overrun_seconds=max(0.0, time.perf_counter() - deadline),
            seed=int(seed),
            workers=int(workers),
            telemetry={
                "returned_source": fallback_source,
                "constructive": constructive_telemetry,
            },
        )

    solver = cp_model.CpSolver()
    margin = min(0.05, max(0.001, remaining * 0.02))
    solver.parameters.max_time_in_seconds = max(0.001, remaining - margin)
    solver.parameters.num_search_workers = max(1, int(workers))
    solver.parameters.random_seed = int(seed)
    search_started = time.perf_counter()
    raw_status = solver.Solve(model)
    search_seconds = time.perf_counter() - search_started

    assignments = fallback
    returned_source = fallback_source
    if raw_status in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        candidate: list[ITC2007PEAssignment] = []
        for event in range(problem.events):
            selected: ITC2007PEAssignment | None = None
            for slot, room, variable in event_placements[event]:
                if solver.BooleanValue(variable):
                    selected = ITC2007PEAssignment(event, slot, room)
                    break
            candidate.append(
                selected if selected is not None else ITC2007PEAssignment(event, -1, -1)
            )
        candidate_validation = validate_itc2007_pe_solution(problem, candidate)
        if (
            candidate_validation.feasible
            and candidate_validation.score.lexicographic
            <= fallback_validation.score.lexicographic
        ):
            assignments = tuple(candidate)
            fallback_validation = candidate_validation
            returned_source = "cp_sat"

    elapsed = time.perf_counter() - started
    status_name = solver.StatusName(raw_status).lower()
    if returned_source != "cp_sat" and raw_status in {
        cp_model.FEASIBLE,
        cp_model.OPTIMAL,
    }:
        status_name = "invalid_or_worse_candidate_fallback"
    return ITC2007PESolveResult(
        assignments=assignments,
        validation=fallback_validation,
        status=status_name,
        raw_status=int(raw_status),
        objective_value=(
            int(round(solver.ObjectiveValue()))
            if raw_status in {cp_model.FEASIBLE, cp_model.OPTIMAL}
            else None
        ),
        best_bound=(
            int(round(solver.BestObjectiveBound()))
            if raw_status in {cp_model.FEASIBLE, cp_model.OPTIMAL, cp_model.UNKNOWN}
            else None
        ),
        build_seconds=float(build_seconds),
        search_seconds=float(search_seconds),
        elapsed_seconds=float(elapsed),
        deadline_overrun_seconds=max(0.0, time.perf_counter() - deadline),
        seed=int(seed),
        workers=int(workers),
        telemetry={
            "returned_source": returned_source,
            "constructive": constructive_telemetry,
            "placement_literals": len(placement),
            "conflict_pairs": len(conflict_pairs),
            "precedence_pairs": len(precedence_pairs),
            "official_objective": "lexicographic(distance_to_feasibility,soft_violations)",
        },
    )


__all__ = [
    "DAYS",
    "SLOTS_PER_DAY",
    "TIMESLOTS",
    "ITC2007PEAssignment",
    "ITC2007PEOfficialValidation",
    "ITC2007PEProblem",
    "ITC2007PEScore",
    "ITC2007PESolveResult",
    "ITC2007PEValidation",
    "ITC2007PEValidatorError",
    "parse_itc2007_pe",
    "parse_itc2007_pe_solution",
    "parse_itc2007_pe_validator_output",
    "run_itc2007_pe_validator",
    "solve_itc2007_pe",
    "validate_itc2007_pe_solution",
    "write_itc2007_pe_solution",
]
