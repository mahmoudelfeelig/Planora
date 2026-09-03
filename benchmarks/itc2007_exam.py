from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from functools import cached_property
from html import unescape
import heapq
from pathlib import Path
import re
import subprocess
import time

from ortools.sat.python import cp_model


_SECTION_PATTERN = re.compile(r"^\[([A-Za-z]+)(?::([0-9]+))?\]$")
_COUNTED_SECTIONS = frozenset({"Exams", "Periods", "Rooms"})
_KNOWN_SECTIONS = (
    "Exams",
    "Periods",
    "Rooms",
    "PeriodHardConstraints",
    "RoomHardConstraints",
    "InstitutionalWeightings",
)
_PERIOD_CONSTRAINTS = frozenset({"AFTER", "EXAM_COINCIDENCE", "EXCLUSION"})
_ROOM_CONSTRAINTS = frozenset({"ROOM_EXCLUSIVE"})
_WEIGHT_NAMES = frozenset(
    {"TWOINAROW", "TWOINADAY", "PERIODSPREAD", "NONMIXEDDURATIONS", "FRONTLOAD"}
)


@dataclass(frozen=True)
class ITC2007Exam:
    duration: int
    students: tuple[int, ...]

    @property
    def size(self) -> int:
        return len(self.students)


@dataclass(frozen=True)
class ITC2007ExamPeriod:
    date: str
    time: str
    duration: int
    penalty: int


@dataclass(frozen=True)
class ITC2007ExamRoom:
    capacity: int
    penalty: int


@dataclass(frozen=True)
class ITC2007ExamPeriodConstraint:
    first_exam: int
    kind: str
    second_exam: int


@dataclass(frozen=True)
class ITC2007ExamRoomConstraint:
    exam: int
    kind: str = "ROOM_EXCLUSIVE"


@dataclass(frozen=True)
class ITC2007ExamWeights:
    two_in_a_row: int
    two_in_a_day: int
    period_spread: int
    non_mixed_durations: int
    frontload_largest_exams: int
    frontload_last_periods: int
    frontload_penalty: int


@dataclass(frozen=True)
class ITC2007ExamProblem:
    name: str
    exams: tuple[ITC2007Exam, ...]
    periods: tuple[ITC2007ExamPeriod, ...]
    rooms: tuple[ITC2007ExamRoom, ...]
    period_constraints: tuple[ITC2007ExamPeriodConstraint, ...]
    room_constraints: tuple[ITC2007ExamRoomConstraint, ...]
    weights: ITC2007ExamWeights

    @cached_property
    def student_exams(self) -> dict[int, tuple[int, ...]]:
        students: dict[int, list[int]] = defaultdict(list)
        for exam_id, exam in enumerate(self.exams):
            for student in exam.students:
                students[int(student)].append(exam_id)
        return {student: tuple(exams) for student, exams in students.items()}

    @cached_property
    def shared_student_counts(self) -> dict[tuple[int, int], int]:
        pairs: Counter[tuple[int, int]] = Counter()
        for exams in self.student_exams.values():
            for left_index, left in enumerate(exams):
                for right in exams[left_index + 1 :]:
                    pair = (left, right) if left < right else (right, left)
                    pairs[pair] += 1
        return dict(pairs)


@dataclass(frozen=True)
class ITC2007ExamAssignment:
    exam: int
    period: int
    room: int


@dataclass(frozen=True)
class ITC2007ExamHardScore:
    required: int
    conflicts: int
    room_occupancy: int
    period_utilisation: int
    period_related: int
    room_related: int

    @property
    def distance_to_feasibility(self) -> int:
        """Official hard-level distance (required-format failures are separate)."""

        return int(
            self.conflicts
            + self.room_occupancy
            + self.period_utilisation
            + self.period_related
            + self.room_related
        )

    @property
    def total(self) -> int:
        return int(self.required + self.distance_to_feasibility)

    def to_dict(self) -> dict[str, int]:
        payload = asdict(self)
        payload["distance_to_feasibility"] = self.distance_to_feasibility
        payload["total"] = self.total
        return payload


@dataclass(frozen=True)
class ITC2007ExamObjective:
    two_in_a_row: int
    two_in_a_day: int
    period_spread: int
    mixed_durations: int
    frontload: int
    room_penalty: int
    period_penalty: int

    @property
    def total(self) -> int:
        return int(
            self.two_in_a_row
            + self.two_in_a_day
            + self.period_spread
            + self.mixed_durations
            + self.frontload
            + self.room_penalty
            + self.period_penalty
        )

    def to_dict(self) -> dict[str, int]:
        payload = asdict(self)
        payload["total"] = self.total
        return payload


@dataclass(frozen=True)
class ITC2007ExamValidation:
    hard: ITC2007ExamHardScore
    objective: ITC2007ExamObjective
    errors: tuple[str, ...] = ()

    @property
    def feasible(self) -> bool:
        return self.hard.total == 0 and not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "feasible": self.feasible,
            "hard": self.hard.to_dict(),
            "objective": self.objective.to_dict(),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class ITC2007ExamOfficialValidation:
    conflicts: int
    room_occupancy: int
    period_utilisation: int
    period_related: int
    room_related: int
    distance_to_feasibility: int
    two_in_a_row: int
    two_in_a_day: int
    period_spread: int
    mixed_durations: int
    frontload: int
    room_penalty: int
    period_penalty: int
    overall_penalty: int
    returncode: int = 0
    stdout: str = field(default="", repr=False, compare=False)
    stderr: str = field(default="", repr=False, compare=False)

    @property
    def feasible(self) -> bool:
        return self.distance_to_feasibility == 0

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("stdout", None)
        payload.pop("stderr", None)
        payload["feasible"] = self.feasible
        return payload


class ITC2007ExamValidatorError(RuntimeError):
    """Raised when an external ITC-2007 exam validator cannot be trusted."""


@dataclass(frozen=True)
class ITC2007ExamSolveResult:
    assignments: tuple[ITC2007ExamAssignment, ...]
    validation: ITC2007ExamValidation
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


class _DeadlineExpired(RuntimeError):
    pass


def _csv_fields(line: str, *, section: str, expected: int | None = None) -> list[str]:
    fields = [field.strip() for field in line.split(",")]
    if any(not field for field in fields):
        raise ValueError(
            f"ITC-2007 exam {section} row contains an empty field: {line!r}"
        )
    if expected is not None and len(fields) != expected:
        raise ValueError(
            f"ITC-2007 exam {section} row needs {expected} fields, got {len(fields)}: {line!r}"
        )
    return fields


def _nonnegative_integer(value: str, *, field_name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"ITC-2007 exam {field_name} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"ITC-2007 exam {field_name} must be non-negative")
    return parsed


def _parse_sections(path: Path) -> dict[str, tuple[int | None, tuple[str, ...]]]:
    sections: dict[str, tuple[int | None, tuple[str, ...]]] = {}
    current_name: str | None = None
    current_count: int | None = None
    current_rows: list[str] = []

    def finish() -> None:
        nonlocal current_name, current_count, current_rows
        if current_name is None:
            return
        sections[current_name] = (current_count, tuple(current_rows))
        current_name = None
        current_count = None
        current_rows = []

    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw.strip()
        if not line:
            continue
        header = _SECTION_PATTERN.fullmatch(line)
        if header is not None:
            finish()
            name = header.group(1)
            if name not in _KNOWN_SECTIONS:
                raise ValueError(
                    f"unsupported ITC-2007 exam section {name!r} on line {line_number}"
                )
            if name in sections:
                raise ValueError(f"duplicate ITC-2007 exam section {name!r}")
            count = int(header.group(2)) if header.group(2) is not None else None
            if name in _COUNTED_SECTIONS and count is None:
                raise ValueError(f"ITC-2007 exam section {name!r} is missing its count")
            if name not in _COUNTED_SECTIONS and count is not None:
                raise ValueError(
                    f"ITC-2007 exam section {name!r} must not declare a count"
                )
            current_name = name
            current_count = count
            continue
        if current_name is None:
            raise ValueError(
                f"ITC-2007 exam content appears before a section on line {line_number}"
            )
        current_rows.append(line)
    finish()

    missing = [name for name in _KNOWN_SECTIONS if name not in sections]
    if missing:
        raise ValueError("missing ITC-2007 exam sections: " + ", ".join(missing))
    actual_order = tuple(sections)
    if actual_order != _KNOWN_SECTIONS:
        raise ValueError(
            "ITC-2007 exam sections are out of order: " + ", ".join(actual_order)
        )
    for name in _COUNTED_SECTIONS:
        count, rows = sections[name]
        if count != len(rows):
            raise ValueError(
                f"ITC-2007 exam {name} count mismatch: header={count}, parsed={len(rows)}"
            )
    return sections


def parse_itc2007_exam(path: str | Path) -> ITC2007ExamProblem:
    """Parse the official Track-1 ``.exam`` format without semantic projection."""

    source = Path(path)
    sections = _parse_sections(source)
    for section in ("Exams", "Periods", "Rooms"):
        if sections[section][0] == 0:
            raise ValueError(f"ITC-2007 exam section {section!r} must not be empty")

    exams: list[ITC2007Exam] = []
    for exam_id, line in enumerate(sections["Exams"][1]):
        fields = _csv_fields(line, section="Exams")
        duration = _nonnegative_integer(
            fields[0], field_name=f"exam {exam_id} duration"
        )
        students = tuple(
            _nonnegative_integer(value, field_name=f"exam {exam_id} student")
            for value in fields[1:]
        )
        if len(students) != len(set(students)):
            raise ValueError(f"ITC-2007 exam {exam_id} lists a student more than once")
        exams.append(ITC2007Exam(duration=duration, students=students))

    periods: list[ITC2007ExamPeriod] = []
    seen_periods: set[tuple[str, str]] = set()
    closed_dates: set[str] = set()
    current_date: str | None = None
    for period_id, line in enumerate(sections["Periods"][1]):
        fields = _csv_fields(line, section="Periods", expected=4)
        date, clock = fields[:2]
        try:
            datetime.strptime(date, "%d:%m:%Y")
            datetime.strptime(clock, "%H:%M:%S")
        except ValueError as exc:
            raise ValueError(
                f"ITC-2007 exam period {period_id} has an invalid date or time"
            ) from exc
        key = (date, clock)
        if key in seen_periods:
            raise ValueError(
                f"ITC-2007 exam period {period_id} duplicates {date} {clock}"
            )
        seen_periods.add(key)
        if current_date != date:
            if date in closed_dates:
                raise ValueError(
                    f"ITC-2007 exam date {date} appears in multiple blocks"
                )
            if current_date is not None:
                closed_dates.add(current_date)
            current_date = date
        duration = _nonnegative_integer(
            fields[2], field_name=f"period {period_id} duration"
        )
        if duration <= 0:
            raise ValueError(
                f"ITC-2007 exam period {period_id} duration must be positive"
            )
        periods.append(
            ITC2007ExamPeriod(
                date=date,
                time=clock,
                duration=duration,
                penalty=_nonnegative_integer(
                    fields[3], field_name=f"period {period_id} penalty"
                ),
            )
        )

    rooms: list[ITC2007ExamRoom] = []
    for room_id, line in enumerate(sections["Rooms"][1]):
        fields = _csv_fields(line, section="Rooms", expected=2)
        capacity = _nonnegative_integer(
            fields[0], field_name=f"room {room_id} capacity"
        )
        if capacity <= 0:
            raise ValueError(f"ITC-2007 exam room {room_id} capacity must be positive")
        rooms.append(
            ITC2007ExamRoom(
                capacity=capacity,
                penalty=_nonnegative_integer(
                    fields[1], field_name=f"room {room_id} penalty"
                ),
            )
        )

    period_constraints: list[ITC2007ExamPeriodConstraint] = []
    for line in sections["PeriodHardConstraints"][1]:
        fields = _csv_fields(line, section="PeriodHardConstraints", expected=3)
        first = _nonnegative_integer(fields[0], field_name="period-constraint exam")
        second = _nonnegative_integer(fields[2], field_name="period-constraint exam")
        kind = fields[1]
        if kind not in _PERIOD_CONSTRAINTS:
            raise ValueError(f"unknown ITC-2007 exam period constraint {kind!r}")
        if first >= len(exams) or second >= len(exams):
            raise ValueError(
                "ITC-2007 exam period constraint references an unknown exam"
            )
        period_constraints.append(
            ITC2007ExamPeriodConstraint(first_exam=first, kind=kind, second_exam=second)
        )

    room_constraints: list[ITC2007ExamRoomConstraint] = []
    for line in sections["RoomHardConstraints"][1]:
        fields = _csv_fields(line, section="RoomHardConstraints", expected=2)
        exam = _nonnegative_integer(fields[0], field_name="room-constraint exam")
        kind = fields[1]
        if kind not in _ROOM_CONSTRAINTS:
            raise ValueError(f"unknown ITC-2007 exam room constraint {kind!r}")
        if exam >= len(exams):
            raise ValueError("ITC-2007 exam room constraint references an unknown exam")
        room_constraints.append(ITC2007ExamRoomConstraint(exam=exam, kind=kind))

    raw_weights: dict[str, tuple[int, ...]] = {}
    for line in sections["InstitutionalWeightings"][1]:
        fields = _csv_fields(line, section="InstitutionalWeightings")
        name = fields[0]
        if name not in _WEIGHT_NAMES:
            raise ValueError(f"unknown ITC-2007 exam institutional weighting {name!r}")
        if name in raw_weights:
            raise ValueError(
                f"duplicate ITC-2007 exam institutional weighting {name!r}"
            )
        expected = 4 if name == "FRONTLOAD" else 2
        if len(fields) != expected:
            raise ValueError(
                f"ITC-2007 exam weighting {name} needs {expected - 1} value(s)"
            )
        raw_weights[name] = tuple(
            _nonnegative_integer(value, field_name=f"{name} value")
            for value in fields[1:]
        )
    missing_weights = sorted(_WEIGHT_NAMES - set(raw_weights))
    if missing_weights:
        raise ValueError(
            "missing ITC-2007 exam institutional weightings: "
            + ", ".join(missing_weights)
        )

    frontload = raw_weights["FRONTLOAD"]
    return ITC2007ExamProblem(
        name=source.stem,
        exams=tuple(exams),
        periods=tuple(periods),
        rooms=tuple(rooms),
        period_constraints=tuple(period_constraints),
        room_constraints=tuple(room_constraints),
        weights=ITC2007ExamWeights(
            two_in_a_row=raw_weights["TWOINAROW"][0],
            two_in_a_day=raw_weights["TWOINADAY"][0],
            period_spread=raw_weights["PERIODSPREAD"][0],
            non_mixed_durations=raw_weights["NONMIXEDDURATIONS"][0],
            frontload_largest_exams=frontload[0],
            frontload_last_periods=frontload[1],
            frontload_penalty=frontload[2],
        ),
    )


def parse_itc2007_exam_solution(
    path: str | Path,
    problem: ITC2007ExamProblem,
) -> tuple[ITC2007ExamAssignment, ...]:
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    if len(lines) != len(problem.exams):
        raise ValueError("ITC-2007 exam solution must contain exactly one row per exam")
    assignments: list[ITC2007ExamAssignment] = []
    for exam, line in enumerate(lines):
        if not line.strip():
            raise ValueError(f"ITC-2007 exam solution row {exam} is empty")
        fields = _csv_fields(line.strip(), section="solution", expected=2)
        try:
            period, room = (int(value) for value in fields)
        except ValueError as exc:
            raise ValueError(
                f"ITC-2007 exam solution row {exam} contains a non-integer"
            ) from exc
        if not 0 <= period < len(problem.periods):
            raise ValueError(
                f"ITC-2007 exam solution row {exam} has invalid period {period}"
            )
        if not 0 <= room < len(problem.rooms):
            raise ValueError(
                f"ITC-2007 exam solution row {exam} has invalid room {room}"
            )
        assignments.append(ITC2007ExamAssignment(exam=exam, period=period, room=room))
    return tuple(assignments)


def write_itc2007_exam_solution(
    path: str | Path,
    assignments: Sequence[ITC2007ExamAssignment],
    *,
    problem: ITC2007ExamProblem,
) -> None:
    if len(assignments) != len(problem.exams):
        raise ValueError("ITC-2007 exam solution assignment count mismatch")
    ordered = sorted(assignments, key=lambda row: int(row.exam))
    if [int(row.exam) for row in ordered] != list(range(len(problem.exams))):
        raise ValueError("ITC-2007 exam solution must cover every exam exactly once")
    for row in ordered:
        if not 0 <= int(row.period) < len(problem.periods):
            raise ValueError(
                f"ITC-2007 exam {row.exam} has invalid period {row.period}"
            )
        if not 0 <= int(row.room) < len(problem.rooms):
            raise ValueError(f"ITC-2007 exam {row.exam} has invalid room {row.room}")
    payload = "".join(
        f"{int(row.period)}, {int(row.room)}\r\n" for row in ordered
    ).encode("utf-8")
    Path(path).write_bytes(payload)


def _normalize_assignments(
    problem: ITC2007ExamProblem,
    assignments: Sequence[ITC2007ExamAssignment],
) -> tuple[dict[int, ITC2007ExamAssignment], list[str], int]:
    normalized: dict[int, ITC2007ExamAssignment] = {}
    errors: list[str] = []
    required = 0
    for row_number, row in enumerate(assignments, start=1):
        exam = int(row.exam)
        if not 0 <= exam < len(problem.exams):
            errors.append(f"solution row {row_number} references unknown exam {exam}")
            required += 1
            continue
        if exam in normalized:
            errors.append(f"exam {exam} is assigned more than once")
            required += 1
            continue
        period = int(row.period)
        room = int(row.room)
        if not 0 <= period < len(problem.periods):
            errors.append(f"exam {exam} has invalid period {period}")
            required += 1
            continue
        if not 0 <= room < len(problem.rooms):
            errors.append(f"exam {exam} has invalid room {room}")
            required += 1
            continue
        normalized[exam] = ITC2007ExamAssignment(exam, period, room)
    missing = sorted(set(range(len(problem.exams))) - set(normalized))
    if missing:
        errors.append("unassigned exams: " + ", ".join(str(exam) for exam in missing))
        required += len(missing)
    return normalized, errors, required


def _coincidence_is_active(
    constraint: ITC2007ExamPeriodConstraint,
    shared_counts: dict[tuple[int, int], int],
) -> bool:
    if constraint.kind != "EXAM_COINCIDENCE":
        return True
    pair = tuple(sorted((constraint.first_exam, constraint.second_exam)))
    # The official input specification explicitly ignores coincidence when the
    # two exams clash because of common enrolment.  This also makes self-lines,
    # which occur in the public corpus, harmless.
    return pair[0] != pair[1] and shared_counts.get(pair, 0) == 0


def validate_itc2007_exam_solution(
    problem: ITC2007ExamProblem,
    assignments: Sequence[ITC2007ExamAssignment],
) -> ITC2007ExamValidation:
    """Independently calculate all official hard and weighted soft components."""

    rows, errors, required = _normalize_assignments(problem, assignments)
    shared_counts = problem.shared_student_counts

    conflicts = sum(
        1
        for (left, right), count in shared_counts.items()
        if count > 0
        and left in rows
        and right in rows
        and rows[left].period == rows[right].period
    )
    for (left, right), count in sorted(shared_counts.items()):
        if (
            count > 0
            and left in rows
            and right in rows
            and rows[left].period == rows[right].period
        ):
            errors.append(
                f"exams {left} and {right} conflict in period {rows[left].period}"
            )

    room_period_exams: dict[tuple[int, int], list[int]] = defaultdict(list)
    for exam, row in rows.items():
        room_period_exams[(row.period, row.room)].append(exam)

    room_occupancy = 0
    for (period, room), exam_ids in sorted(room_period_exams.items()):
        used = sum(problem.exams[exam].size for exam in exam_ids)
        capacity = problem.rooms[room].capacity
        if used > capacity:
            room_occupancy += 1
            errors.append(
                f"room {room} capacity is exceeded in period {period} ({used}>{capacity})"
            )

    period_utilisation = 0
    for exam, row in sorted(rows.items()):
        if problem.exams[exam].duration > problem.periods[row.period].duration:
            period_utilisation += 1
            errors.append(f"exam {exam} duration exceeds period {row.period} duration")

    period_related = 0
    for constraint in problem.period_constraints:
        if not _coincidence_is_active(constraint, shared_counts):
            continue
        first = rows.get(constraint.first_exam)
        second = rows.get(constraint.second_exam)
        if first is None or second is None:
            continue
        violated = (
            (constraint.kind == "AFTER" and first.period <= second.period)
            or (constraint.kind == "EXAM_COINCIDENCE" and first.period != second.period)
            or (constraint.kind == "EXCLUSION" and first.period == second.period)
        )
        if violated:
            period_related += 1
            errors.append(
                f"{constraint.kind} is violated by exams "
                f"{constraint.first_exam} and {constraint.second_exam}"
            )

    exclusive = {constraint.exam for constraint in problem.room_constraints}
    room_related = 0
    for exam in sorted(exclusive):
        row = rows.get(exam)
        if row is None:
            continue
        occupants = room_period_exams[(row.period, row.room)]
        if len(occupants) > 1:
            room_related += 1
            errors.append(
                f"room-exclusive exam {exam} shares room {row.room} in period {row.period}"
            )

    two_in_a_row = 0
    two_in_a_day = 0
    period_spread = 0
    for (left, right), common_students in shared_counts.items():
        first = rows.get(left)
        second = rows.get(right)
        if first is None or second is None:
            continue
        low = min(first.period, second.period)
        high = max(first.period, second.period)
        distance = high - low
        same_day = problem.periods[low].date == problem.periods[high].date
        if distance == 1 and same_day:
            two_in_a_row += common_students * problem.weights.two_in_a_row
        elif distance > 1 and same_day:
            two_in_a_day += common_students * problem.weights.two_in_a_day
        if 0 < distance <= problem.weights.period_spread:
            period_spread += common_students

    mixed_durations = 0
    for exam_ids in room_period_exams.values():
        distinct = {problem.exams[exam].duration for exam in exam_ids}
        mixed_durations += max(0, len(distinct) - 1)
    mixed_durations *= problem.weights.non_mixed_durations

    largest = sorted(
        range(len(problem.exams)),
        key=lambda exam: (-problem.exams[exam].size, exam),
    )[: problem.weights.frontload_largest_exams]
    frontload_threshold = max(
        0, len(problem.periods) - problem.weights.frontload_last_periods
    )
    frontload = sum(
        problem.weights.frontload_penalty
        for exam in largest
        if exam in rows and rows[exam].period >= frontload_threshold
    )
    room_penalty = sum(problem.rooms[row.room].penalty for row in rows.values())
    period_penalty = sum(problem.periods[row.period].penalty for row in rows.values())

    hard = ITC2007ExamHardScore(
        required=required,
        conflicts=conflicts,
        room_occupancy=room_occupancy,
        period_utilisation=period_utilisation,
        period_related=period_related,
        room_related=room_related,
    )
    objective = ITC2007ExamObjective(
        two_in_a_row=two_in_a_row,
        two_in_a_day=two_in_a_day,
        period_spread=period_spread,
        mixed_durations=mixed_durations,
        frontload=frontload,
        room_penalty=room_penalty,
        period_penalty=period_penalty,
    )
    return ITC2007ExamValidation(hard=hard, objective=objective, errors=tuple(errors))


_EXTERNAL_LABELS: dict[str, tuple[str, ...]] = {
    "conflicts": ("Conflicts",),
    "room_occupancy": ("RoomOccupancy", "Room Occupancy"),
    "period_utilisation": (
        "PeriodUtilisation",
        "Period Utilisation",
        "Period Utilization",
    ),
    "period_related": ("PeriodRelated", "Period Related"),
    "room_related": ("RoomRelated", "Room Related"),
    "distance_to_feasibility": ("Distance to Feasibility",),
    "two_in_a_row": ("TwoInARow", "Two Exams in a Row"),
    "two_in_a_day": ("TwoInADay", "Two Exams in a Day"),
    "period_spread": ("PeriodSpread", "Period Spread", "WiderSpreads"),
    "mixed_durations": ("MixedDurations", "Mixed Durations", "MixDurationPenalties"),
    "frontload": ("FrontLoad", "Larger Exams Constraints", "FrontLoadPenalties"),
    "room_penalty": ("RoomPenalty", "Room Penalty", "RoomPenalties"),
    "period_penalty": ("PeriodPenalty", "Period Penalty", "PeriodPenalties"),
    "overall_penalty": ("Overall Penalty", "Overall Value"),
}


def _external_value(text: str, field_name: str) -> int:
    labels = "|".join(re.escape(label) for label in _EXTERNAL_LABELS[field_name])
    patterns = (
        re.compile(rf"(?im)^\s*(?:{labels})(?:\s+Penalty)?\s*[:=]\s*([0-9]+)\s*$"),
        re.compile(rf"(?im)^\s*(?:{labels})\s*:.*?\bpen\s*=\s*([0-9]+)\s*$"),
    )
    matches: list[str] = []
    for pattern in patterns:
        matches.extend(pattern.findall(text))
    if len(matches) != 1:
        raise ITC2007ExamValidatorError(
            f"external exam validator field {field_name!r} occurred {len(matches)} times"
        )
    return int(matches[0])


def parse_itc2007_exam_validator_output(
    stdout: str,
    *,
    returncode: int = 0,
    stderr: str = "",
) -> ITC2007ExamOfficialValidation:
    """Parse the official web labels or the equivalent CPSolver report labels."""

    normalized = unescape(re.sub(r"<[^>]*>", "\n", stdout)).replace("\xa0", " ")
    values = {name: _external_value(normalized, name) for name in _EXTERNAL_LABELS}
    hard_sum = sum(
        values[name]
        for name in (
            "conflicts",
            "room_occupancy",
            "period_utilisation",
            "period_related",
            "room_related",
        )
    )
    if hard_sum != values["distance_to_feasibility"]:
        raise ITC2007ExamValidatorError(
            "external exam validator distance disagrees with its hard components"
        )
    soft_sum = sum(
        values[name]
        for name in (
            "two_in_a_row",
            "two_in_a_day",
            "period_spread",
            "mixed_durations",
            "frontload",
            "room_penalty",
            "period_penalty",
        )
    )
    if soft_sum != values["overall_penalty"]:
        raise ITC2007ExamValidatorError(
            "external exam validator total disagrees with its soft components"
        )
    return ITC2007ExamOfficialValidation(
        **values,
        returncode=int(returncode),
        stdout=stdout,
        stderr=stderr,
    )


def run_itc2007_exam_validator(
    executable: str | Path,
    instance_path: str | Path,
    solution_path: str | Path,
    *,
    timeout_seconds: float = 30.0,
    extra_arguments: Sequence[str] = (),
) -> ITC2007ExamOfficialValidation:
    """Run an independently obtained validator accepting instance and solution paths."""

    validator = Path(executable).resolve()
    instance = Path(instance_path).resolve()
    solution = Path(solution_path).resolve()
    if not validator.is_file():
        raise ITC2007ExamValidatorError(f"validator does not exist: {validator}")
    if not instance.is_file() or not solution.is_file():
        raise ITC2007ExamValidatorError("instance and solution files must exist")
    try:
        completed = subprocess.run(
            [
                str(validator),
                *[str(argument) for argument in extra_arguments],
                str(instance),
                str(solution),
            ],
            capture_output=True,
            text=True,
            timeout=max(0.1, float(timeout_seconds)),
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ITC2007ExamValidatorError(
            f"external exam validator execution failed: {exc}"
        ) from exc
    if completed.returncode != 0:
        raise ITC2007ExamValidatorError(
            f"external exam validator returned {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return parse_itc2007_exam_validator_output(
        completed.stdout,
        returncode=completed.returncode,
        stderr=completed.stderr,
    )


def _deadline_check(deadline: float, phase: str) -> None:
    if time.perf_counter() >= deadline:
        raise _DeadlineExpired(f"deadline exhausted during {phase}")


def _empty_validation(problem: ITC2007ExamProblem) -> ITC2007ExamValidation:
    return ITC2007ExamValidation(
        hard=ITC2007ExamHardScore(
            required=len(problem.exams),
            conflicts=0,
            room_occupancy=0,
            period_utilisation=0,
            period_related=0,
            room_related=0,
        ),
        objective=ITC2007ExamObjective(
            two_in_a_row=0,
            two_in_a_day=0,
            period_spread=0,
            mixed_durations=0,
            frontload=0,
            room_penalty=0,
            period_penalty=0,
        ),
        errors=("no complete solution is available",),
    )


def _non_solution_result(
    problem: ITC2007ExamProblem,
    *,
    status: str,
    started: float,
    build_finished: float,
    deadline: float,
    seed: int,
    workers: int,
    telemetry: dict[str, object],
    raw_status: int = int(cp_model.UNKNOWN),
) -> ITC2007ExamSolveResult:
    finished = time.perf_counter()
    return ITC2007ExamSolveResult(
        assignments=(),
        validation=_empty_validation(problem),
        status=status,
        raw_status=raw_status,
        objective_value=None,
        best_bound=None,
        build_seconds=max(0.0, build_finished - started),
        search_seconds=max(0.0, finished - build_finished),
        elapsed_seconds=max(0.0, finished - started),
        deadline_overrun_seconds=max(0.0, finished - deadline),
        seed=seed,
        workers=workers,
        telemetry=telemetry,
    )


def _pack_exam_class_rooms(
    problem: ITC2007ExamProblem,
    exam_ids: Sequence[int],
    *,
    deadline: float,
    node_limit: int | None = None,
) -> tuple[dict[int, int] | None, int]:
    """Pack one fixed period exactly enough for constructive feasibility."""

    exclusive = {constraint.exam for constraint in problem.room_constraints}
    eligible_rooms = {
        exam_id: tuple(
            room_id
            for room_id, room in enumerate(problem.rooms)
            if problem.exams[exam_id].size <= room.capacity
        )
        for exam_id in exam_ids
    }
    if any(not rooms for rooms in eligible_rooms.values()):
        return None, 0
    ordered = sorted(
        exam_ids,
        key=lambda exam_id: (
            exam_id not in exclusive,
            len(eligible_rooms[exam_id]),
            -problem.exams[exam_id].size,
            exam_id,
        ),
    )
    remaining = [room.capacity for room in problem.rooms]
    contents: list[list[int]] = [[] for _ in problem.rooms]
    durations: list[set[int]] = [set() for _ in problem.rooms]
    locked = [False] * len(problem.rooms)
    selected: dict[int, int] = {}
    nodes = 0
    bounded_nodes = (
        max(20_000, 2_000 * len(ordered))
        if node_limit is None
        else max(1, int(node_limit))
    )

    def search(index: int) -> bool:
        nonlocal nodes
        nodes += 1
        if (nodes == 1 or nodes & 255 == 0) and time.perf_counter() >= deadline:
            raise _DeadlineExpired("deadline exhausted during room lift")
        if nodes > bounded_nodes:
            return False
        if index == len(ordered):
            return True
        exam_id = ordered[index]
        exam = problem.exams[exam_id]
        is_exclusive = exam_id in exclusive
        candidates: list[tuple[tuple[int, int, int, int], int]] = []
        for room_id in eligible_rooms[exam_id]:
            if locked[room_id] or exam.size > remaining[room_id]:
                continue
            if is_exclusive and contents[room_id]:
                continue
            adds_mixed_duration = int(
                bool(durations[room_id]) and exam.duration not in durations[room_id]
            )
            incremental_soft = (
                problem.rooms[room_id].penalty
                + adds_mixed_duration * problem.weights.non_mixed_durations
            )
            candidates.append(
                (
                    (
                        incremental_soft,
                        adds_mixed_duration,
                        remaining[room_id] - exam.size,
                        room_id,
                    ),
                    room_id,
                )
            )
        candidates.sort()
        symmetric_states: set[tuple[object, ...]] = set()
        for _, room_id in candidates:
            state = (
                problem.rooms[room_id].capacity,
                problem.rooms[room_id].penalty,
                remaining[room_id],
                tuple(sorted(durations[room_id])),
                locked[room_id],
                bool(contents[room_id]),
            )
            if state in symmetric_states:
                continue
            symmetric_states.add(state)
            previous_durations = set(durations[room_id])
            remaining[room_id] -= exam.size
            contents[room_id].append(exam_id)
            durations[room_id].add(exam.duration)
            locked[room_id] = is_exclusive
            selected[exam_id] = room_id
            if search(index + 1):
                return True
            selected.pop(exam_id, None)
            locked[room_id] = False
            durations[room_id] = previous_durations
            contents[room_id].pop()
            remaining[room_id] += exam.size
        return False

    try:
        packed = search(0)
    except _DeadlineExpired:
        return None, nodes
    return (dict(selected) if packed else None), nodes


def _pack_fixed_period_rooms(
    problem: ITC2007ExamProblem,
    period_by_exam: Sequence[int],
    *,
    deadline: float,
) -> tuple[dict[int, int] | None, dict[str, int]]:
    """Lift a projected period solution into rooms with bounded backtracking.

    The Track-1 room constraint is a multiple-knapsack problem inside each
    period.  Solving those independent color classes is much smaller than
    carrying an exam-period-room Cartesian product through the temporal model.
    Room-exclusive exams are placed first and lock their selected bin.
    """

    by_period: dict[int, list[int]] = defaultdict(list)
    for exam_id, period_id in enumerate(period_by_exam):
        by_period[int(period_id)].append(exam_id)
    room_by_exam: dict[int, int] = {}
    telemetry = {"periods_packed": 0, "backtrack_nodes": 0}

    for period_id in sorted(by_period):
        selected, nodes = _pack_exam_class_rooms(
            problem,
            by_period[period_id],
            deadline=deadline,
        )
        telemetry["backtrack_nodes"] += nodes
        if selected is None:
            return None, telemetry
        room_by_exam.update(selected)
        telemetry["periods_packed"] += 1
    return room_by_exam, telemetry


@dataclass(frozen=True)
class _ExamConstructiveResult:
    assignments: tuple[ITC2007ExamAssignment, ...]
    validation: ITC2007ExamValidation
    telemetry: dict[str, object]


def _constructive_incumbent_solve_result(
    problem: ITC2007ExamProblem,
    incumbent: _ExamConstructiveResult,
    *,
    started: float,
    build_finished: float,
    search_finished: float | None,
    deadline: float,
    seed: int,
    workers: int,
    fallback_reason: str,
    raw_status: int = int(cp_model.UNKNOWN),
    telemetry: dict[str, object] | None = None,
) -> ITC2007ExamSolveResult:
    finished = time.perf_counter()
    searched_until = build_finished if search_finished is None else search_finished
    payload = dict(telemetry or {})
    payload.update(
        {
            "strategy": "constructive_coloring_with_bounded_ejection",
            "constructive": dict(incumbent.telemetry),
            "fallback_reason": fallback_reason,
            "fail_closed": False,
        }
    )
    return ITC2007ExamSolveResult(
        assignments=incumbent.assignments,
        validation=incumbent.validation,
        status="feasible_constructive",
        raw_status=raw_status,
        objective_value=incumbent.validation.objective.total,
        best_bound=None,
        build_seconds=max(0.0, build_finished - started),
        search_seconds=max(0.0, searched_until - build_finished),
        elapsed_seconds=max(0.0, finished - started),
        deadline_overrun_seconds=max(0.0, finished - deadline),
        seed=seed,
        workers=workers,
        telemetry=payload,
    )


def _room_class_soft_cost(
    problem: ITC2007ExamProblem,
    exam_ids: Sequence[int],
    room_by_exam: dict[int, int],
) -> int:
    durations: dict[int, set[int]] = defaultdict(set)
    room_penalty = 0
    for exam_id in exam_ids:
        room_id = room_by_exam[exam_id]
        room_penalty += problem.rooms[room_id].penalty
        durations[room_id].add(problem.exams[exam_id].duration)
    mixed = sum(max(0, len(values) - 1) for values in durations.values())
    return int(room_penalty + mixed * problem.weights.non_mixed_durations)


def _optimize_exam_class_rooms(
    problem: ITC2007ExamProblem,
    exam_ids: Sequence[int],
    incumbent_rooms: dict[int, int],
    *,
    deadline: float,
    node_limit: int,
) -> tuple[dict[int, int], int, bool]:
    """Branch-and-bound one room color class from a feasible incumbent.

    Rebuilding the whole class makes multi-exam ejection chains implicit: a
    penalized-room occupant can move only after several other occupants have
    changed bins.  The incumbent is always retained, so deadline or node-limit
    exhaustion cannot degrade feasibility or score.
    """

    exclusive = {constraint.exam for constraint in problem.room_constraints}
    eligible_rooms = {
        exam_id: tuple(
            room_id
            for room_id, room in enumerate(problem.rooms)
            if problem.exams[exam_id].size <= room.capacity
        )
        for exam_id in exam_ids
    }
    if any(not rooms for rooms in eligible_rooms.values()):
        return dict(incumbent_rooms), 0, False
    incumbent_cost = _room_class_soft_cost(problem, exam_ids, incumbent_rooms)
    best_cost = incumbent_cost
    best_rooms = dict(incumbent_rooms)
    ordered = sorted(
        exam_ids,
        key=lambda exam_id: (
            exam_id not in exclusive,
            len(eligible_rooms[exam_id]),
            -problem.exams[exam_id].size,
            -min(problem.rooms[room_id].penalty for room_id in eligible_rooms[exam_id]),
            exam_id,
        ),
    )
    minimum_room_penalty = [
        min(problem.rooms[room_id].penalty for room_id in eligible_rooms[exam_id])
        for exam_id in ordered
    ]
    suffix_lower_bound = [0] * (len(ordered) + 1)
    for index in range(len(ordered) - 1, -1, -1):
        suffix_lower_bound[index] = (
            suffix_lower_bound[index + 1] + minimum_room_penalty[index]
        )

    remaining = [room.capacity for room in problem.rooms]
    contents: list[list[int]] = [[] for _ in problem.rooms]
    durations: list[set[int]] = [set() for _ in problem.rooms]
    locked = [False] * len(problem.rooms)
    selected: dict[int, int] = {}
    nodes = 0
    exhausted = False

    def search(index: int, partial_cost: int) -> None:
        nonlocal best_cost, best_rooms, nodes, exhausted
        nodes += 1
        if nodes > max(1, int(node_limit)):
            exhausted = True
            return
        if nodes == 1 or nodes & 127 == 0:
            if time.perf_counter() >= deadline:
                exhausted = True
                return
        if partial_cost + suffix_lower_bound[index] >= best_cost:
            return
        if index == len(ordered):
            best_cost = partial_cost
            best_rooms = dict(selected)
            return
        exam_id = ordered[index]
        exam = problem.exams[exam_id]
        is_exclusive = exam_id in exclusive
        candidates: list[tuple[tuple[int, int, int, int], int, int]] = []
        for room_id in eligible_rooms[exam_id]:
            if locked[room_id] or exam.size > remaining[room_id]:
                continue
            if is_exclusive and contents[room_id]:
                continue
            adds_duration = int(
                bool(durations[room_id]) and exam.duration not in durations[room_id]
            )
            incremental_cost = (
                problem.rooms[room_id].penalty
                + adds_duration * problem.weights.non_mixed_durations
            )
            candidates.append(
                (
                    (
                        incremental_cost,
                        adds_duration,
                        remaining[room_id] - exam.size,
                        room_id,
                    ),
                    room_id,
                    incremental_cost,
                )
            )
        candidates.sort()
        symmetric_states: set[tuple[object, ...]] = set()
        for _, room_id, incremental_cost in candidates:
            if (
                partial_cost + incremental_cost + suffix_lower_bound[index + 1]
                >= best_cost
            ):
                continue
            state = (
                problem.rooms[room_id].capacity,
                problem.rooms[room_id].penalty,
                remaining[room_id],
                tuple(sorted(durations[room_id])),
                locked[room_id],
                bool(contents[room_id]),
            )
            if state in symmetric_states:
                continue
            symmetric_states.add(state)
            previous_durations = set(durations[room_id])
            remaining[room_id] -= exam.size
            contents[room_id].append(exam_id)
            durations[room_id].add(exam.duration)
            locked[room_id] = is_exclusive
            selected[exam_id] = room_id
            search(index + 1, partial_cost + incremental_cost)
            selected.pop(exam_id, None)
            locked[room_id] = False
            durations[room_id] = previous_durations
            contents[room_id].pop()
            remaining[room_id] += exam.size
            if exhausted:
                return

    search(0, 0)
    return best_rooms, nodes, not exhausted


def _room_class_assignment_is_feasible(
    problem: ITC2007ExamProblem,
    exam_ids: Sequence[int],
    room_by_exam: dict[int, int],
) -> bool:
    """Check fixed-period room capacity and exclusivity without rescoring."""

    if any(exam_id not in room_by_exam for exam_id in exam_ids):
        return False
    contents: list[list[int]] = [[] for _ in problem.rooms]
    loads = [0] * len(problem.rooms)
    for exam_id in exam_ids:
        room_id = room_by_exam[exam_id]
        if room_id < 0 or room_id >= len(problem.rooms):
            return False
        contents[room_id].append(exam_id)
        loads[room_id] += problem.exams[exam_id].size
    if any(
        load > problem.rooms[room_id].capacity for room_id, load in enumerate(loads)
    ):
        return False
    exclusive = {constraint.exam for constraint in problem.room_constraints}
    return all(
        exam_id not in exclusive or len(contents[room_by_exam[exam_id]]) == 1
        for exam_id in exam_ids
    )


def _close_exam_class_rooms(
    problem: ITC2007ExamProblem,
    exam_ids: Sequence[int],
    incumbent_rooms: dict[int, int],
    *,
    deadline: float,
    max_moves: int = 8,
) -> tuple[dict[int, int], int, int, bool]:
    """Apply cheap strict single/swap room improvements to one period.

    This deterministic closure is deliberately small: it gives every period a
    chance before branch-and-bound focuses on the expensive residual classes.
    Every accepted intermediate mapping is hard-feasible and strictly lowers
    the exact fixed-period room/mixed-duration cost.
    """

    current = dict(incumbent_rooms)
    if not _room_class_assignment_is_feasible(problem, exam_ids, current):
        return current, 0, 0, False
    current_cost = _room_class_soft_cost(problem, exam_ids, current)
    moves = 0
    candidates = 0
    ordered = tuple(sorted(exam_ids))
    while moves < max(0, int(max_moves)):
        if time.perf_counter() >= deadline:
            return current, moves, candidates, False
        best_key: tuple[int, int, int, int] | None = None
        best_rooms: dict[int, int] | None = None

        for exam_id in ordered:
            source = current[exam_id]
            for target in range(len(problem.rooms)):
                if target == source:
                    continue
                candidates += 1
                if candidates & 63 == 0 and time.perf_counter() >= deadline:
                    return current, moves, candidates, False
                candidate = dict(current)
                candidate[exam_id] = target
                if not _room_class_assignment_is_feasible(problem, exam_ids, candidate):
                    continue
                cost = _room_class_soft_cost(problem, exam_ids, candidate)
                key = (cost, 0, exam_id, target)
                if cost < current_cost and (best_key is None or key < best_key):
                    best_key = key
                    best_rooms = candidate

        for left_index, left in enumerate(ordered):
            for right in ordered[left_index + 1 :]:
                if current[left] == current[right]:
                    continue
                candidates += 1
                if candidates & 63 == 0 and time.perf_counter() >= deadline:
                    return current, moves, candidates, False
                candidate = dict(current)
                candidate[left], candidate[right] = (
                    candidate[right],
                    candidate[left],
                )
                if not _room_class_assignment_is_feasible(problem, exam_ids, candidate):
                    continue
                cost = _room_class_soft_cost(problem, exam_ids, candidate)
                key = (cost, 1, left, right)
                if cost < current_cost and (best_key is None or key < best_key):
                    best_key = key
                    best_rooms = candidate

        if best_rooms is None or best_key is None:
            return current, moves, candidates, True
        current = best_rooms
        current_cost = best_key[0]
        moves += 1
    return current, moves, candidates, False


def _polish_fixed_period_rooms(
    problem: ITC2007ExamProblem,
    assignments: Sequence[ITC2007ExamAssignment],
    *,
    deadline: float,
    max_nodes_per_period: int = 25_000,
    closure_budget_seconds: float | None = None,
) -> tuple[tuple[ITC2007ExamAssignment, ...], ITC2007ExamValidation, dict[str, object]]:
    """Strictly improve only room assignments under an absolute deadline."""

    original = tuple(sorted(assignments, key=lambda row: row.exam))
    original_validation = validate_itc2007_exam_solution(problem, original)
    telemetry: dict[str, object] = {
        "closure_attempted_periods": 0,
        "closure_complete_periods": 0,
        "closure_improved_periods": 0,
        "closure_moves": 0,
        "closure_candidates": 0,
        "closure_total_periods": 0,
        "closure_coverage_complete": False,
        "closure_max_moves_per_period": 2,
        "closure_budget_seconds": 0.0,
        "closure_elapsed_seconds": 0.0,
        "score_after_closure": original_validation.objective.total,
        "room_penalty_after_closure": original_validation.objective.room_penalty,
        "mixed_durations_after_closure": (
            original_validation.objective.mixed_durations
        ),
        "attempted_periods": 0,
        "improved_periods": 0,
        "search_nodes": 0,
        "complete_period_searches": 0,
        "score_before": original_validation.objective.total,
        "score_after": original_validation.objective.total,
        "room_penalty_before": original_validation.objective.room_penalty,
        "room_penalty_after": original_validation.objective.room_penalty,
        "mixed_durations_before": original_validation.objective.mixed_durations,
        "mixed_durations_after": original_validation.objective.mixed_durations,
        "accepted": False,
    }
    if not original_validation.feasible or time.perf_counter() >= deadline:
        return original, original_validation, telemetry

    periods: dict[int, list[int]] = defaultdict(list)
    room_by_exam = {row.exam: row.room for row in original}
    period_by_exam = {row.exam: row.period for row in original}
    for row in original:
        periods[row.period].append(row.exam)
    telemetry["closure_total_periods"] = len(periods)

    improved_period_ids: set[int] = set()
    closure_started = time.perf_counter()
    closure_available = max(0.0, deadline - closure_started)
    requested_closure_budget = (
        min(0.08, max(0.005, 0.15 * closure_available))
        if closure_budget_seconds is None
        else max(0.0, float(closure_budget_seconds))
    )
    closure_budget = min(closure_available, requested_closure_budget)
    telemetry["closure_budget_seconds"] = closure_budget
    closure_deadline = min(
        deadline,
        closure_started + closure_budget,
    )
    closure_period_order = sorted(
        periods,
        key=lambda period_id: (
            -_room_class_soft_cost(problem, periods[period_id], room_by_exam),
            -len(periods[period_id]),
            period_id,
        ),
    )
    for period_index, period_id in enumerate(closure_period_order):
        if time.perf_counter() >= closure_deadline:
            break
        exam_ids = periods[period_id]
        incumbent_period_rooms = {
            exam_id: room_by_exam[exam_id] for exam_id in exam_ids
        }
        before = _room_class_soft_cost(problem, exam_ids, incumbent_period_rooms)
        now = time.perf_counter()
        remaining_periods = max(1, len(closure_period_order) - period_index)
        fair_slice = min(
            0.004,
            max(0.0005, max(0.0, closure_deadline - now) / remaining_periods),
        )
        closed, moves, candidates, complete = _close_exam_class_rooms(
            problem,
            exam_ids,
            incumbent_period_rooms,
            deadline=min(closure_deadline, now + fair_slice),
            max_moves=2,
        )
        telemetry["closure_attempted_periods"] = (
            int(telemetry["closure_attempted_periods"]) + 1
        )
        telemetry["closure_moves"] = int(telemetry["closure_moves"]) + moves
        telemetry["closure_candidates"] = (
            int(telemetry["closure_candidates"]) + candidates
        )
        if complete:
            telemetry["closure_complete_periods"] = (
                int(telemetry["closure_complete_periods"]) + 1
            )
        after = _room_class_soft_cost(problem, exam_ids, closed)
        if after < before:
            room_by_exam.update(closed)
            improved_period_ids.add(period_id)
            telemetry["closure_improved_periods"] = (
                int(telemetry["closure_improved_periods"]) + 1
            )

    telemetry["closure_elapsed_seconds"] = max(
        0.0, time.perf_counter() - closure_started
    )
    telemetry["closure_coverage_complete"] = bool(
        int(telemetry["closure_attempted_periods"]) == len(periods)
    )
    room_penalty_after_closure = sum(
        problem.rooms[room_by_exam[exam_id]].penalty
        for exam_id in range(len(problem.exams))
    )
    room_cost_after_closure = sum(
        _room_class_soft_cost(problem, exam_ids, room_by_exam)
        for exam_ids in periods.values()
    )
    mixed_durations_after_closure = room_cost_after_closure - room_penalty_after_closure
    telemetry.update(
        {
            "score_after_closure": (
                original_validation.objective.total
                - original_validation.objective.room_penalty
                - original_validation.objective.mixed_durations
                + room_cost_after_closure
            ),
            "room_penalty_after_closure": room_penalty_after_closure,
            "mixed_durations_after_closure": mixed_durations_after_closure,
        }
    )

    period_order = sorted(
        periods,
        key=lambda period_id: (
            -_room_class_soft_cost(problem, periods[period_id], room_by_exam),
            -len(periods[period_id]),
            period_id,
        ),
    )
    for period_id in period_order:
        if time.perf_counter() >= deadline:
            break
        exam_ids = periods[period_id]
        incumbent_period_rooms = {
            exam_id: room_by_exam[exam_id] for exam_id in exam_ids
        }
        before = _room_class_soft_cost(problem, exam_ids, incumbent_period_rooms)
        optimized, nodes, complete = _optimize_exam_class_rooms(
            problem,
            exam_ids,
            incumbent_period_rooms,
            deadline=deadline,
            node_limit=max_nodes_per_period,
        )
        telemetry["attempted_periods"] = int(telemetry["attempted_periods"]) + 1
        telemetry["search_nodes"] = int(telemetry["search_nodes"]) + nodes
        if complete:
            telemetry["complete_period_searches"] = (
                int(telemetry["complete_period_searches"]) + 1
            )
        after = _room_class_soft_cost(problem, exam_ids, optimized)
        if after < before:
            room_by_exam.update(optimized)
            improved_period_ids.add(period_id)

    telemetry["improved_periods"] = len(improved_period_ids)

    candidate = tuple(
        ITC2007ExamAssignment(
            exam=exam_id,
            period=period_by_exam[exam_id],
            room=room_by_exam[exam_id],
        )
        for exam_id in range(len(problem.exams))
    )
    candidate_validation = validate_itc2007_exam_solution(problem, candidate)
    strictly_improved = bool(
        candidate_validation.feasible
        and candidate_validation.objective.total < original_validation.objective.total
    )
    if not strictly_improved:
        return original, original_validation, telemetry
    telemetry.update(
        {
            "score_after": candidate_validation.objective.total,
            "room_penalty_after": candidate_validation.objective.room_penalty,
            "mixed_durations_after": candidate_validation.objective.mixed_durations,
            "accepted": True,
        }
    )
    return candidate, candidate_validation, telemetry


def _polish_exam_periods(
    problem: ITC2007ExamProblem,
    assignments: Sequence[ITC2007ExamAssignment],
    *,
    deadline: float,
    max_rounds: int = 6,
    max_units_per_round: int = 48,
    max_targets_per_unit: int = 10,
    max_exchange_candidates: int = 64,
    max_exchange_evaluations: int = 18,
) -> tuple[tuple[ITC2007ExamAssignment, ...], ITC2007ExamValidation, dict[str, object]]:
    """Polish period colors through room-priced atomic neighborhoods.

    Move, pair-interchange, Kempe, and ejection neighborhoods are established
    examination-timetabling techniques. This bounded implementation couples
    their temporal delta to a cached room-packing marginal, then accepts a
    candidate only after full independent scoring of the atomically repacked
    schedule. Room-burden pricing changes candidate order, not those claims.
    """

    started = time.perf_counter()
    available = max(0.0, deadline - started)
    acceptance_reserve = min(0.05, max(0.005, 0.10 * available))
    search_deadline = max(started, deadline - acceptance_reserve)
    incumbent = tuple(sorted(assignments, key=lambda row: row.exam))
    incumbent_validation = validate_itc2007_exam_solution(problem, incumbent)
    telemetry: dict[str, object] = {
        "strategy": "room_shadow_priced_atomic_lns",
        "established_neighborhoods": (
            "move",
            "kempe",
            "ejection_swap",
            "room_burden_exchange",
        ),
        "rounds": 0,
        "single_attempts": 0,
        "kempe_attempts": 0,
        "compound_attempts": 0,
        "accepted_single_moves": 0,
        "accepted_kempe_moves": 0,
        "accepted_compound_moves": 0,
        "accepted_room_burden_exchanges": 0,
        "accepted_without_spread_improvement": 0,
        "negative_temporal_sweep_candidates": 0,
        "negative_temporal_sweep_attempts": 0,
        "accepted_negative_temporal_moves": 0,
        "seed_barrier_compound_attempts": 0,
        "room_shadow_candidates": 0,
        "pricing_batch_size": 4,
        "pricing_batches": 0,
        "priced_units": 0,
        "completed_pricing_batches": 0,
        "room_pack_failures": 0,
        "room_optimization_attempts": 0,
        "room_optimization_nodes": 0,
        "complete_room_optimizations": 0,
        "late_candidates_discarded": 0,
        "room_burden_exchange": {
            "strategy": "room_burden_ranked_cross_period_exchange",
            "candidate_limit": max(0, int(max_exchange_candidates)),
            "rounds": 0,
            "burden_units": 0,
            "generated_single_candidates": 0,
            "generated_swap_candidates": 0,
            "hard_valid_candidates": 0,
            "fast_delta_candidates": 0,
            "fast_delta_cache_entries": 0,
            "candidate_evaluation_limit": max(0, int(max_exchange_evaluations)),
            "accepted_candidate_limit": 5,
            "accepted_candidate_limit_stops": 0,
            "candidate_evaluation_limit_stops": 0,
            "retained_candidates": 0,
            "evaluated_candidates": 0,
            "accepted_candidates": 0,
            "accepted_single_candidates": 0,
            "accepted_swap_candidates": 0,
            "generation_deadline_stops": 0,
            "evaluation_deadline_stops": 0,
            "generation_seconds": 0.0,
            "evaluation_seconds": 0.0,
            "allocated_seconds": 0.0,
            "score_before": incumbent_validation.objective.total,
            "score_after": incumbent_validation.objective.total,
        },
        "score_before": incumbent_validation.objective.total,
        "score_after": incumbent_validation.objective.total,
        "spread_before": incumbent_validation.objective.period_spread,
        "spread_after": incumbent_validation.objective.period_spread,
        "accepted": False,
        "acceptance_reserve_seconds": acceptance_reserve,
        "elapsed_seconds": 0.0,
    }
    if not incumbent_validation.feasible or time.perf_counter() >= deadline:
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return incumbent, incumbent_validation, telemetry
    room_burden_exchange = telemetry["room_burden_exchange"]
    if not isinstance(room_burden_exchange, dict):  # pragma: no cover - invariant
        raise AssertionError("room-burden exchange telemetry must be a mapping")

    exam_count = len(problem.exams)
    parent = list(range(exam_count))

    def find(exam_id: int) -> int:
        while parent[exam_id] != exam_id:
            parent[exam_id] = parent[parent[exam_id]]
            exam_id = parent[exam_id]
        return exam_id

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        if first_root > second_root:
            first_root, second_root = second_root, first_root
        parent[second_root] = first_root

    shared_counts = problem.shared_student_counts
    for constraint in problem.period_constraints:
        if constraint.kind == "EXAM_COINCIDENCE" and _coincidence_is_active(
            constraint, shared_counts
        ):
            union(constraint.first_exam, constraint.second_exam)
    grouped: dict[int, list[int]] = defaultdict(list)
    for exam_id in range(exam_count):
        grouped[find(exam_id)].append(exam_id)
    unit_members = tuple(
        tuple(members)
        for _, members in sorted(grouped.items(), key=lambda item: min(item[1]))
    )
    unit_by_exam = {
        exam_id: unit_id
        for unit_id, members in enumerate(unit_members)
        for exam_id in members
    }
    unit_count = len(unit_members)
    unit_domains: list[tuple[int, ...]] = []
    for members in unit_members:
        common = set(range(len(problem.periods)))
        for exam_id in members:
            common.intersection_update(
                period_id
                for period_id, period in enumerate(problem.periods)
                if problem.exams[exam_id].duration <= period.duration
            )
        unit_domains.append(tuple(sorted(common)))
    unit_domain_sets = tuple(frozenset(domain) for domain in unit_domains)

    neighbors: list[set[int]] = [set() for _ in range(unit_count)]
    pair_weights: list[dict[int, int]] = [defaultdict(int) for _ in range(unit_count)]
    for (left, right), common_students in shared_counts.items():
        if common_students <= 0:
            continue
        first_unit = unit_by_exam[left]
        second_unit = unit_by_exam[right]
        if first_unit == second_unit:
            return incumbent, incumbent_validation, telemetry
        neighbors[first_unit].add(second_unit)
        neighbors[second_unit].add(first_unit)
        pair_weights[first_unit][second_unit] += common_students
        pair_weights[second_unit][first_unit] += common_students
    predecessors: list[set[int]] = [set() for _ in range(unit_count)]
    successors: list[set[int]] = [set() for _ in range(unit_count)]
    for constraint in problem.period_constraints:
        if not _coincidence_is_active(constraint, shared_counts):
            continue
        first_unit = unit_by_exam[constraint.first_exam]
        second_unit = unit_by_exam[constraint.second_exam]
        if constraint.kind == "EXAM_COINCIDENCE":
            continue
        if first_unit == second_unit:
            return incumbent, incumbent_validation, telemetry
        neighbors[first_unit].add(second_unit)
        neighbors[second_unit].add(first_unit)
        if constraint.kind == "AFTER":
            predecessors[first_unit].add(second_unit)
            successors[second_unit].add(first_unit)

    largest = set(
        sorted(
            range(exam_count),
            key=lambda exam_id: (-problem.exams[exam_id].size, exam_id),
        )[: problem.weights.frontload_largest_exams]
    )
    frontload_threshold = max(
        0, len(problem.periods) - problem.weights.frontload_last_periods
    )

    def rebuild_state(
        rows: Sequence[ITC2007ExamAssignment],
    ) -> tuple[dict[int, int], dict[int, int], list[set[int]]]:
        row_by_exam = {row.exam: row for row in rows}
        period_by_unit = {
            unit_id: row_by_exam[members[0]].period
            for unit_id, members in enumerate(unit_members)
        }
        room_by_exam = {row.exam: row.room for row in rows}
        period_units = [set() for _ in problem.periods]
        for unit_id, period_id in period_by_unit.items():
            period_units[period_id].add(unit_id)
        return period_by_unit, room_by_exam, period_units

    def temporal_contribution(unit_id: int, period_by_unit: dict[int, int]) -> int:
        period_id = period_by_unit[unit_id]
        return sum(
            common_students
            * _temporal_pair_cost(problem, period_id, period_by_unit[neighbor])
            for neighbor, common_students in pair_weights[unit_id].items()
        )

    def unary_cost(unit_id: int, period_id: int) -> int:
        cost = 0
        for exam_id in unit_members[unit_id]:
            cost += problem.periods[period_id].penalty
            if exam_id in largest and period_id >= frontload_threshold:
                cost += problem.weights.frontload_penalty
        return cost

    def changes_are_hard_valid(
        changes: dict[int, int],
        period_by_unit: dict[int, int],
    ) -> bool:
        """Check only hard relations incident to a proposed atomic change."""

        for unit_id, period_id in changes.items():
            if period_id not in unit_domain_sets[unit_id]:
                return False
            if any(
                changes.get(neighbor, period_by_unit[neighbor]) == period_id
                for neighbor in neighbors[unit_id]
            ):
                return False
            if any(
                changes.get(predecessor, period_by_unit[predecessor]) >= period_id
                for predecessor in predecessors[unit_id]
            ):
                return False
            if any(
                changes.get(successor, period_by_unit[successor]) <= period_id
                for successor in successors[unit_id]
            ):
                return False
        return True

    delta_cache = _PeriodPolishDeltaCache(problem, unit_members, pair_weights)

    exclusive_exams = {constraint.exam for constraint in problem.room_constraints}

    def period_exam_ids(
        period_id: int,
        period_units: Sequence[set[int]],
    ) -> tuple[int, ...]:
        return tuple(
            exam_id
            for unit_id in sorted(period_units[period_id])
            for exam_id in unit_members[unit_id]
        )

    def source_room_relief(
        unit_id: int,
        period_by_unit: dict[int, int],
        room_by_exam: dict[int, int],
        period_units: Sequence[set[int]],
    ) -> int:
        """Return the exact soft cost removed from the incumbent packing."""

        source = period_by_unit[unit_id]
        before_ids = period_exam_ids(source, period_units)
        removed = set(unit_members[unit_id])
        after_ids = tuple(exam_id for exam_id in before_ids if exam_id not in removed)
        before = _room_class_soft_cost(problem, before_ids, room_by_exam)
        after = (
            _room_class_soft_cost(problem, after_ids, room_by_exam) if after_ids else 0
        )
        return max(0, before - after)

    def cache_period_room_states(
        room_by_exam: dict[int, int],
        period_units: Sequence[set[int]],
    ) -> (
        list[
            tuple[
                tuple[int, ...],
                tuple[tuple[int, ...], ...],
                tuple[frozenset[int], ...],
                tuple[bool, ...],
            ]
        ]
        | None
    ):
        states = []
        for period_id in range(len(problem.periods)):
            if period_id & 15 == 0 and time.perf_counter() >= search_deadline:
                return None
            remaining = [room.capacity for room in problem.rooms]
            contents: list[list[int]] = [[] for _ in problem.rooms]
            durations: list[set[int]] = [set() for _ in problem.rooms]
            locked = [False] * len(problem.rooms)
            for exam_id in period_exam_ids(period_id, period_units):
                room_id = room_by_exam[exam_id]
                remaining[room_id] -= problem.exams[exam_id].size
                contents[room_id].append(exam_id)
                durations[room_id].add(problem.exams[exam_id].duration)
                if exam_id in exclusive_exams:
                    locked[room_id] = True
            states.append(
                (
                    tuple(remaining),
                    tuple(tuple(values) for values in contents),
                    tuple(frozenset(values) for values in durations),
                    tuple(locked),
                )
            )
        return states

    def target_room_insertion_shadow(
        unit_id: int,
        target_period: int,
        cached_states: Sequence[
            tuple[
                tuple[int, ...],
                tuple[tuple[int, ...], ...],
                tuple[frozenset[int], ...],
                tuple[bool, ...],
            ]
        ],
    ) -> int:
        """Estimate direct insertion cost against the cached room state.

        The signal is exact when the unit has one exam and a direct insertion
        exists.  Larger coincidence units use a deterministic greedy packing;
        the result only orders candidates and never decides acceptance.
        """

        state = cached_states[target_period]
        remaining = list(state[0])
        contents = [list(values) for values in state[1]]
        durations = [set(values) for values in state[2]]
        locked = list(state[3])

        incremental = 0
        moving = sorted(
            unit_members[unit_id],
            key=lambda exam_id: (
                exam_id not in exclusive_exams,
                -problem.exams[exam_id].size,
                exam_id,
            ),
        )
        for exam_id in moving:
            exam = problem.exams[exam_id]
            is_exclusive = exam_id in exclusive_exams
            candidates: list[tuple[tuple[int, int, int], int, int]] = []
            for room_id, room in enumerate(problem.rooms):
                if locked[room_id] or exam.size > remaining[room_id]:
                    continue
                if is_exclusive and contents[room_id]:
                    continue
                adds_duration = int(
                    bool(durations[room_id]) and exam.duration not in durations[room_id]
                )
                delta = (
                    room.penalty + adds_duration * problem.weights.non_mixed_durations
                )
                candidates.append(
                    (
                        (delta, remaining[room_id] - exam.size, room_id),
                        room_id,
                        delta,
                    )
                )
            if not candidates:
                # A repack can still make this unit fit.  Keep it in the
                # neighborhood, but rank the direct-packing barrier after
                # candidates with an immediately realizable room marginal.
                fallback = max(
                    1,
                    problem.weights.non_mixed_durations,
                    max((room.penalty for room in problem.rooms), default=0),
                )
                return incremental + fallback
            _, room_id, delta = min(candidates)
            incremental += delta
            remaining[room_id] -= exam.size
            contents[room_id].append(exam_id)
            durations[room_id].add(exam.duration)
            if is_exclusive:
                locked[room_id] = True
        return incremental

    def changed_periods_are_hard_valid(
        period_by_unit: dict[int, int],
        changed_units: Sequence[int],
    ) -> bool:
        # The incumbent is already validated, so every newly violated edge or
        # precedence relation must touch a changed unit.
        for unit_id in changed_units:
            period_id = period_by_unit[unit_id]
            if period_id not in unit_domain_sets[unit_id]:
                return False
            if any(
                period_by_unit[neighbor] == period_id for neighbor in neighbors[unit_id]
            ):
                return False
            if any(
                period_by_unit[predecessor] >= period_id
                for predecessor in predecessors[unit_id]
            ):
                return False
            if any(
                period_by_unit[successor] <= period_id
                for successor in successors[unit_id]
            ):
                return False
        return True

    def evaluate_changes(
        changes: dict[int, int],
        period_by_unit: dict[int, int],
        room_by_exam: dict[int, int],
        period_units: list[set[int]],
        *,
        candidate_deadline: float | None = None,
    ) -> tuple[tuple[ITC2007ExamAssignment, ...], ITC2007ExamValidation] | None:
        effective_deadline = min(
            search_deadline,
            search_deadline if candidate_deadline is None else candidate_deadline,
        )
        if time.perf_counter() >= effective_deadline:
            return None
        candidate_periods = dict(period_by_unit)
        candidate_periods.update(changes)
        if not changed_periods_are_hard_valid(candidate_periods, tuple(changes)):
            return None
        affected = {period_by_unit[unit_id] for unit_id in changes} | set(
            changes.values()
        )
        candidate_rooms = dict(room_by_exam)
        for period_id in affected:
            for resident in period_units[period_id]:
                for exam_id in unit_members[resident]:
                    candidate_rooms.pop(exam_id, None)
        for period_id in sorted(affected):
            exam_ids = [
                exam_id
                for unit_id, assigned_period in candidate_periods.items()
                if assigned_period == period_id
                for exam_id in unit_members[unit_id]
            ]
            if not exam_ids:
                continue
            packed, _ = _pack_exam_class_rooms(
                problem,
                exam_ids,
                deadline=effective_deadline,
                node_limit=3_000,
            )
            if packed is None:
                telemetry["room_pack_failures"] = (
                    int(telemetry["room_pack_failures"]) + 1
                )
                return None
            optimized, nodes, complete = _optimize_exam_class_rooms(
                problem,
                exam_ids,
                packed,
                deadline=effective_deadline,
                node_limit=5_000,
            )
            telemetry["room_optimization_attempts"] = (
                int(telemetry["room_optimization_attempts"]) + 1
            )
            telemetry["room_optimization_nodes"] = (
                int(telemetry["room_optimization_nodes"]) + nodes
            )
            if complete:
                telemetry["complete_room_optimizations"] = (
                    int(telemetry["complete_room_optimizations"]) + 1
                )
            candidate_rooms.update(optimized)
        if time.perf_counter() >= effective_deadline:
            telemetry["late_candidates_discarded"] = (
                int(telemetry["late_candidates_discarded"]) + 1
            )
            return None
        candidate = tuple(
            ITC2007ExamAssignment(
                exam=exam_id,
                period=candidate_periods[unit_by_exam[exam_id]],
                room=candidate_rooms[exam_id],
            )
            for exam_id in range(exam_count)
        )
        validation = validate_itc2007_exam_solution(problem, candidate)
        if time.perf_counter() >= effective_deadline:
            telemetry["late_candidates_discarded"] = (
                int(telemetry["late_candidates_discarded"]) + 1
            )
            return None
        if not validation.feasible:
            return None
        return candidate, validation

    def kempe_chain_changes(
        seed_unit: int,
        target_period: int,
        period_by_unit: dict[int, int],
        *,
        max_chain_units: int = 24,
    ) -> dict[int, int] | None:
        """Build the established two-period Kempe conflict closure atomically."""

        source_period = period_by_unit[seed_unit]
        if source_period == target_period:
            return None
        changes = {seed_unit: target_period}
        queue = [seed_unit]
        while queue:
            moved = queue.pop(0)
            moved_target = changes[moved]
            opposite = source_period if moved_target == target_period else target_period
            for neighbor in sorted(neighbors[moved]):
                neighbor_period = changes.get(neighbor, period_by_unit[neighbor])
                if neighbor_period != moved_target:
                    continue
                existing = changes.get(neighbor)
                if existing is not None and existing != opposite:
                    return None
                if existing is None:
                    if period_by_unit[neighbor] not in {
                        source_period,
                        target_period,
                    }:
                        return None
                    changes[neighbor] = opposite
                    queue.append(neighbor)
                    if len(changes) > max(1, int(max_chain_units)):
                        return None
        return changes

    accepted_any = False

    def accept_if_strictly_better(
        evaluated: (
            tuple[tuple[ITC2007ExamAssignment, ...], ITC2007ExamValidation] | None
        ),
        counter: str,
    ) -> bool:
        nonlocal accepted_any, incumbent, incumbent_validation
        if evaluated is None:
            return False
        if time.perf_counter() >= deadline:
            telemetry["late_candidates_discarded"] = (
                int(telemetry["late_candidates_discarded"]) + 1
            )
            return False
        candidate, validation = evaluated
        if validation.objective.total >= incumbent_validation.objective.total:
            return False
        previous_spread = incumbent_validation.objective.period_spread
        incumbent = candidate
        incumbent_validation = validation
        telemetry[counter] = int(telemetry[counter]) + 1
        if validation.objective.period_spread >= previous_spread:
            telemetry["accepted_without_spread_improvement"] = (
                int(telemetry["accepted_without_spread_improvement"]) + 1
            )
        accepted_any = True
        return True

    for _ in range(max(0, int(max_rounds))):
        if time.perf_counter() >= search_deadline:
            break
        telemetry["rounds"] = int(telemetry["rounds"]) + 1
        period_by_unit, room_by_exam, period_units = rebuild_state(incumbent)
        source_relief_by_unit: dict[int, int] = {}
        temporal_by_unit: dict[int, int] = {}
        current_unary_by_unit: dict[int, int] = {}

        for unit_id in range(unit_count):
            if unit_id & 15 == 0 and time.perf_counter() >= search_deadline:
                break
            source = period_by_unit[unit_id]
            current_temporal = temporal_contribution(unit_id, period_by_unit)
            current_unary = unary_cost(unit_id, source)
            relief = source_room_relief(
                unit_id,
                period_by_unit,
                room_by_exam,
                period_units,
            )
            source_relief_by_unit[unit_id] = relief
            temporal_by_unit[unit_id] = current_temporal
            current_unary_by_unit[unit_id] = current_unary

        # Aggregate each unit's conflict weights by the neighbours' current
        # period. A cross-period swap can then be priced exactly without
        # rebuilding and sorting its full affected-edge set for every partner.
        # The swap correction restores the one edge whose endpoints move
        # together. This changes only ordering; full validation still accepts.
        delta_cache.reset(period_by_unit)
        hard_neighbor_counts_by_period: list[list[int]] = []
        for unit_id in range(unit_count):
            hard_counts = [0] * len(problem.periods)
            for neighbor in neighbors[unit_id]:
                hard_counts[period_by_unit[neighbor]] += 1
            hard_neighbor_counts_by_period.append(hard_counts)

        def single_change_is_hard_valid(unit_id: int, target: int) -> bool:
            if target not in unit_domain_sets[unit_id]:
                return False
            if hard_neighbor_counts_by_period[unit_id][target] > 0:
                return False
            if any(
                period_by_unit[predecessor] >= target
                for predecessor in predecessors[unit_id]
            ):
                return False
            return not any(
                period_by_unit[successor] <= target for successor in successors[unit_id]
            )

        def swap_changes_are_hard_valid(first: int, second: int) -> bool:
            first_source = period_by_unit[first]
            second_source = period_by_unit[second]
            if (
                second_source not in unit_domain_sets[first]
                or first_source not in unit_domain_sets[second]
            ):
                return False
            are_neighbors = int(second in neighbors[first])
            if (
                hard_neighbor_counts_by_period[first][second_source] - are_neighbors > 0
                or hard_neighbor_counts_by_period[second][first_source] - are_neighbors
                > 0
            ):
                return False

            def final_period(unit_id: int) -> int:
                if unit_id == first:
                    return second_source
                if unit_id == second:
                    return first_source
                return period_by_unit[unit_id]

            if any(
                final_period(predecessor) >= second_source
                for predecessor in predecessors[first]
            ) or any(
                final_period(successor) <= second_source
                for successor in successors[first]
            ):
                return False
            if any(
                final_period(predecessor) >= first_source
                for predecessor in predecessors[second]
            ):
                return False
            return not any(
                final_period(successor) <= first_source
                for successor in successors[second]
            )

        improved = False
        exchange_started = time.perf_counter()
        exchange_remaining = max(0.0, search_deadline - exchange_started)
        # Reserve a useful majority slice for the structural room-color move,
        # while leaving the established Move/Kempe/ejection stream a tail when
        # no exchange is accepted. Candidate generation has its own earlier
        # deadline so exact affected-class evaluation cannot be priced out.
        exchange_budget = min(0.85, 0.65 * exchange_remaining)
        exchange_deadline = min(
            search_deadline,
            exchange_started + exchange_budget,
        )
        # The streamed candidate order is canonical. A deterministic check
        # quota is therefore the primary generation bound; this deadline is a
        # hard safety stop for unexpectedly slow hardware.
        generation_deadline = exchange_deadline
        if (
            exchange_budget >= 0.01
            and source_relief_by_unit
            and int(room_burden_exchange["candidate_limit"]) > 0
        ):
            room_burden_exchange["rounds"] = int(room_burden_exchange["rounds"]) + 1
            room_burden_exchange["allocated_seconds"] = float(
                room_burden_exchange["allocated_seconds"]
            ) + max(0.0, exchange_deadline - exchange_started)
            direct_room_penalty = {
                unit_id: sum(
                    problem.rooms[room_by_exam[exam_id]].penalty
                    for exam_id in unit_members[unit_id]
                )
                for unit_id in source_relief_by_unit
            }
            positive_room_penalties = [
                room.penalty for room in problem.rooms if room.penalty > 0
            ]
            burden_floor = min(
                positive_room_penalties or [max(1, problem.weights.non_mixed_durations)]
            )
            exchange_unit_limit = min(
                len(source_relief_by_unit),
                max(1, min(64, 2 * int(max_units_per_round))),
            )
            burden_units = sorted(
                (
                    unit_id
                    for unit_id in source_relief_by_unit
                    if direct_room_penalty[unit_id] > 0
                    or source_relief_by_unit[unit_id] >= burden_floor
                ),
                key=lambda unit_id: (
                    -(direct_room_penalty[unit_id] + source_relief_by_unit[unit_id]),
                    -source_relief_by_unit[unit_id],
                    -temporal_by_unit[unit_id],
                    unit_id,
                ),
            )[:exchange_unit_limit]
            room_burden_exchange["burden_units"] = int(
                room_burden_exchange["burden_units"]
            ) + len(burden_units)
            burden_unit_set = set(burden_units)
            unit_sizes = {
                unit_id: sum(
                    problem.exams[exam_id].size for exam_id in unit_members[unit_id]
                )
                for unit_id in range(unit_count)
            }
            candidate_limit = int(room_burden_exchange["candidate_limit"])
            candidate_heap: list[
                tuple[
                    tuple[int, ...],
                    int,
                    tuple[int, ...],
                    str,
                    tuple[tuple[int, int], ...],
                ]
            ] = []
            candidate_serial = 0

            def retain_exchange_candidate(
                key: tuple[int, ...],
                kind: str,
                changes: dict[int, int],
            ) -> None:
                nonlocal candidate_serial
                candidate_serial += 1
                reverse_key = tuple(-value for value in key)
                item = (
                    reverse_key,
                    candidate_serial,
                    key,
                    kind,
                    tuple(sorted(changes.items())),
                )
                if len(candidate_heap) < candidate_limit:
                    heapq.heappush(candidate_heap, item)
                elif reverse_key > candidate_heap[0][0]:
                    heapq.heapreplace(candidate_heap, item)

            generation_stopped = False
            generation_checks = 0
            generation_check_limit = max(
                1,
                len(burden_units) * (sum(map(len, unit_domains)) + unit_count),
            )
            for unit_id in burden_units:
                if time.perf_counter() >= generation_deadline:
                    generation_stopped = True
                    break
                source = period_by_unit[unit_id]
                for target in unit_domains[unit_id]:
                    generation_checks += 1
                    if generation_checks > generation_check_limit:
                        generation_stopped = True
                        break
                    if (
                        generation_checks & 63 == 0
                        and time.perf_counter() >= generation_deadline
                    ):
                        generation_stopped = True
                        break
                    if target == source:
                        continue
                    changes = {unit_id: target}
                    room_burden_exchange["generated_single_candidates"] = (
                        int(room_burden_exchange["generated_single_candidates"]) + 1
                    )
                    if not single_change_is_hard_valid(unit_id, target):
                        continue
                    room_burden_exchange["hard_valid_candidates"] = (
                        int(room_burden_exchange["hard_valid_candidates"]) + 1
                    )
                    temporal_unary_delta = delta_cache.placement_delta(
                        unit_id,
                        target,
                    )
                    room_burden_exchange["fast_delta_candidates"] = (
                        int(room_burden_exchange["fast_delta_candidates"]) + 1
                    )
                    relief = source_relief_by_unit[unit_id]
                    retain_exchange_candidate(
                        (
                            temporal_unary_delta - relief,
                            temporal_unary_delta,
                            -relief,
                            1,
                            unit_id,
                            target,
                        ),
                        "single",
                        changes,
                    )
                if generation_stopped:
                    break

                for other in range(unit_count):
                    generation_checks += 1
                    if generation_checks > generation_check_limit:
                        generation_stopped = True
                        break
                    if (
                        generation_checks & 63 == 0
                        and time.perf_counter() >= generation_deadline
                    ):
                        generation_stopped = True
                        break
                    if other == unit_id:
                        continue
                    if other in burden_unit_set and other < unit_id:
                        continue
                    target = period_by_unit[other]
                    if target == source:
                        continue
                    changes = {unit_id: target, other: source}
                    room_burden_exchange["generated_swap_candidates"] = (
                        int(room_burden_exchange["generated_swap_candidates"]) + 1
                    )
                    if not swap_changes_are_hard_valid(unit_id, other):
                        continue
                    room_burden_exchange["hard_valid_candidates"] = (
                        int(room_burden_exchange["hard_valid_candidates"]) + 1
                    )
                    temporal_unary_delta = delta_cache.swap_delta(unit_id, other)
                    room_burden_exchange["fast_delta_candidates"] = (
                        int(room_burden_exchange["fast_delta_candidates"]) + 1
                    )
                    relief = source_relief_by_unit[unit_id] + source_relief_by_unit.get(
                        other, 0
                    )
                    retain_exchange_candidate(
                        (
                            temporal_unary_delta - relief,
                            temporal_unary_delta,
                            abs(unit_sizes[unit_id] - unit_sizes[other]),
                            -relief,
                            0,
                            min(unit_id, other),
                            max(unit_id, other),
                        ),
                        "swap",
                        changes,
                    )
                if generation_stopped:
                    break

            if generation_stopped:
                room_burden_exchange["generation_deadline_stops"] = (
                    int(room_burden_exchange["generation_deadline_stops"]) + 1
                )
            generation_finished = time.perf_counter()
            room_burden_exchange["fast_delta_cache_entries"] = (
                int(room_burden_exchange["fast_delta_cache_entries"])
                + delta_cache.placement_cache_entries
            )
            room_burden_exchange["generation_seconds"] = float(
                room_burden_exchange["generation_seconds"]
            ) + max(0.0, generation_finished - exchange_started)
            room_burden_exchange["retained_candidates"] = int(
                room_burden_exchange["retained_candidates"]
            ) + len(candidate_heap)

            ranked_exchange_candidates = sorted(
                (item[2], item[3], dict(item[4])) for item in candidate_heap
            )
            evaluation_started = time.perf_counter()
            for _, kind, changes in ranked_exchange_candidates:
                if int(room_burden_exchange["evaluated_candidates"]) >= int(
                    room_burden_exchange["candidate_evaluation_limit"]
                ):
                    room_burden_exchange["candidate_evaluation_limit_stops"] = (
                        int(room_burden_exchange["candidate_evaluation_limit_stops"])
                        + 1
                    )
                    break
                if time.perf_counter() >= exchange_deadline:
                    room_burden_exchange["evaluation_deadline_stops"] = (
                        int(room_burden_exchange["evaluation_deadline_stops"]) + 1
                    )
                    break
                room_burden_exchange["evaluated_candidates"] = (
                    int(room_burden_exchange["evaluated_candidates"]) + 1
                )
                attempt_counter = (
                    "single_attempts" if kind == "single" else "compound_attempts"
                )
                telemetry[attempt_counter] = int(telemetry[attempt_counter]) + 1
                evaluated = evaluate_changes(
                    changes,
                    period_by_unit,
                    room_by_exam,
                    period_units,
                    candidate_deadline=exchange_deadline,
                )
                acceptance_counter = (
                    "accepted_single_moves"
                    if kind == "single"
                    else "accepted_compound_moves"
                )
                if accept_if_strictly_better(evaluated, acceptance_counter):
                    telemetry["accepted_room_burden_exchanges"] = (
                        int(telemetry["accepted_room_burden_exchanges"]) + 1
                    )
                    room_burden_exchange["accepted_candidates"] = (
                        int(room_burden_exchange["accepted_candidates"]) + 1
                    )
                    accepted_kind = f"accepted_{kind}_candidates"
                    room_burden_exchange[accepted_kind] = (
                        int(room_burden_exchange[accepted_kind]) + 1
                    )
                    room_burden_exchange["score_after"] = (
                        incumbent_validation.objective.total
                    )
                    improved = True
                    break
            room_burden_exchange["evaluation_seconds"] = float(
                room_burden_exchange["evaluation_seconds"]
            ) + max(0.0, time.perf_counter() - evaluation_started)

        if improved:
            if int(room_burden_exchange["accepted_candidates"]) >= int(
                room_burden_exchange["accepted_candidate_limit"]
            ):
                room_burden_exchange["accepted_candidate_limit_stops"] = (
                    int(room_burden_exchange["accepted_candidate_limit_stops"]) + 1
                )
                break
            continue

        # A room-burden screen can hide a period-color move whose exact
        # temporal/unary gain pays for a temporarily more expensive affected
        # room packing.  Stream only strictly negative exact single deltas as
        # a bounded fallback, then use the same atomic room repack and full
        # independent validation as every other accepted neighborhood.
        negative_temporal_candidates: list[tuple[int, int, int]] = []
        for unit_id in range(unit_count):
            if unit_id & 31 == 0 and time.perf_counter() >= search_deadline:
                break
            source = period_by_unit[unit_id]
            for target in unit_domains[unit_id]:
                if target == source or not single_change_is_hard_valid(unit_id, target):
                    continue
                temporal_unary_delta = delta_cache.placement_delta(unit_id, target)
                if temporal_unary_delta < 0:
                    negative_temporal_candidates.append(
                        (temporal_unary_delta, unit_id, target)
                    )
        negative_temporal_candidates.sort()
        telemetry["negative_temporal_sweep_candidates"] = int(
            telemetry["negative_temporal_sweep_candidates"]
        ) + len(negative_temporal_candidates)
        for _, unit_id, target in negative_temporal_candidates:
            if time.perf_counter() >= search_deadline:
                break
            telemetry["negative_temporal_sweep_attempts"] = (
                int(telemetry["negative_temporal_sweep_attempts"]) + 1
            )
            evaluated = evaluate_changes(
                {unit_id: target},
                period_by_unit,
                room_by_exam,
                period_units,
            )
            if accept_if_strictly_better(evaluated, "accepted_negative_temporal_moves"):
                improved = True
                break
        if improved:
            continue

        cached_room_states = cache_period_room_states(room_by_exam, period_units)
        if cached_room_states is None:
            break

        # Screen on exact incumbent burden, then stream four-unit pricing
        # batches directly into the established Move/Kempe/ejection evaluator.
        # This bounds time-to-first-move; an accepted atomic candidate restarts
        # the round from its newly validated incumbent instead of pricing stale
        # candidates for the rest of the graph.
        screening_limit = min(
            unit_count,
            max(1, int(max_units_per_round)),
        )
        screened_units = sorted(
            source_relief_by_unit,
            key=lambda unit_id: (
                -(
                    temporal_by_unit[unit_id]
                    + current_unary_by_unit[unit_id]
                    + source_relief_by_unit[unit_id]
                ),
                -source_relief_by_unit[unit_id],
                -temporal_by_unit[unit_id],
                unit_id,
            ),
        )[:screening_limit]

        batch_size = 4
        for batch_start in range(0, len(screened_units), batch_size):
            if time.perf_counter() >= search_deadline:
                break
            targets_by_unit: dict[int, list[tuple[int, int, int, int]]] = {}
            unit_priority: list[tuple[tuple[int, int, int, int], int]] = []
            batch = screened_units[batch_start : batch_start + batch_size]
            priced_in_batch = 0
            telemetry["pricing_batches"] = int(telemetry["pricing_batches"]) + 1

            for unit_id in batch:
                if time.perf_counter() >= search_deadline:
                    break
                source = period_by_unit[unit_id]
                current_temporal = temporal_by_unit[unit_id]
                current_temporal_unary = (
                    current_temporal + current_unary_by_unit[unit_id]
                )
                relief = source_relief_by_unit[unit_id]
                records: list[tuple[int, int, int, int]] = []
                for target in unit_domains[unit_id]:
                    if (
                        len(records) & 15 == 0
                        and time.perf_counter() >= search_deadline
                    ):
                        break
                    if target == source:
                        continue
                    projected_temporal = sum(
                        common_students
                        * _temporal_pair_cost(
                            problem,
                            target,
                            period_by_unit[neighbor],
                        )
                        for neighbor, common_students in pair_weights[unit_id].items()
                    )
                    temporal_unary_delta = (
                        projected_temporal
                        + unary_cost(unit_id, target)
                        - current_temporal_unary
                    )
                    shadow = target_room_insertion_shadow(
                        unit_id,
                        target,
                        cached_room_states,
                    )
                    priced_delta = temporal_unary_delta + shadow - relief
                    records.append(
                        (
                            priced_delta,
                            temporal_unary_delta,
                            abs(target - source),
                            target,
                        )
                    )
                telemetry["room_shadow_candidates"] = int(
                    telemetry["room_shadow_candidates"]
                ) + len(records)
                telemetry["priced_units"] = int(telemetry["priced_units"]) + 1
                priced_in_batch += 1
                if not records:
                    continue
                records.sort()
                records = records[: max(1, int(max_targets_per_unit))]
                targets_by_unit[unit_id] = records
                unit_priority.append(
                    (
                        (
                            records[0][0],
                            -relief,
                            -current_temporal,
                            unit_id,
                        ),
                        unit_id,
                    )
                )

            if priced_in_batch == len(batch):
                telemetry["completed_pricing_batches"] = (
                    int(telemetry["completed_pricing_batches"]) + 1
                )
            ranked_units = [unit_id for _, unit_id in sorted(unit_priority)]
            for unit_id in ranked_units:
                if time.perf_counter() >= search_deadline:
                    break
                source = period_by_unit[unit_id]
                records = targets_by_unit[unit_id]
                for _, temporal_unary_delta, _, target in records:
                    if time.perf_counter() >= search_deadline:
                        break

                    # Singles use the same priced ordering as compounds.  A flat
                    # temporal move can therefore expose a strict room/mixed gain.
                    telemetry["single_attempts"] = int(telemetry["single_attempts"]) + 1
                    evaluated = evaluate_changes(
                        {unit_id: target},
                        period_by_unit,
                        room_by_exam,
                        period_units,
                    )
                    if accept_if_strictly_better(evaluated, "accepted_single_moves"):
                        improved = True
                        break

                    # Do not apply a seed-only temporal gate here.  The closure's
                    # other units can cross a local barrier while the atomically
                    # validated total objective still improves.
                    kempe_changes = kempe_chain_changes(
                        unit_id,
                        target,
                        period_by_unit,
                    )
                    if kempe_changes is not None and len(kempe_changes) > 1:
                        if temporal_unary_delta >= 0:
                            telemetry["seed_barrier_compound_attempts"] = (
                                int(telemetry["seed_barrier_compound_attempts"]) + 1
                            )
                        telemetry["kempe_attempts"] = (
                            int(telemetry["kempe_attempts"]) + 1
                        )
                        evaluated = evaluate_changes(
                            kempe_changes,
                            period_by_unit,
                            room_by_exam,
                            period_units,
                        )
                        if accept_if_strictly_better(evaluated, "accepted_kempe_moves"):
                            improved = True
                            break

                    blockers = sorted(
                        neighbor
                        for neighbor in neighbors[unit_id]
                        if period_by_unit[neighbor] == target
                    )
                    ejection_candidates = blockers[:1]
                    if not ejection_candidates:
                        ejection_candidates = sorted(
                            period_units[target],
                            key=lambda resident: (
                                -source_relief_by_unit.get(resident, 0),
                                -sum(
                                    problem.exams[exam_id].size
                                    for exam_id in unit_members[resident]
                                ),
                                resident,
                            ),
                        )[:3]
                    for ejected in ejection_candidates:
                        if time.perf_counter() >= search_deadline:
                            break
                        if temporal_unary_delta >= 0:
                            telemetry["seed_barrier_compound_attempts"] = (
                                int(telemetry["seed_barrier_compound_attempts"]) + 1
                            )
                        telemetry["compound_attempts"] = (
                            int(telemetry["compound_attempts"]) + 1
                        )
                        evaluated = evaluate_changes(
                            {unit_id: target, ejected: source},
                            period_by_unit,
                            room_by_exam,
                            period_units,
                        )
                        if accept_if_strictly_better(
                            evaluated, "accepted_compound_moves"
                        ):
                            improved = True
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break
        if not improved:
            break

    telemetry.update(
        {
            "score_after": incumbent_validation.objective.total,
            "spread_after": incumbent_validation.objective.period_spread,
            "accepted": accepted_any,
            "elapsed_seconds": max(0.0, time.perf_counter() - started),
        }
    )
    room_burden_exchange["score_after"] = incumbent_validation.objective.total
    return incumbent, incumbent_validation, telemetry


def _optimize_exam_period_room_neighborhood(
    problem: ITC2007ExamProblem,
    assignments: Sequence[ITC2007ExamAssignment],
    *,
    deadline: float,
    seed: int,
    period_radius: int = 3,
    workers: int = 1,
) -> tuple[
    tuple[ITC2007ExamAssignment, ...],
    ITC2007ExamValidation,
    dict[str, object],
]:
    """Jointly recolor periods and repack rooms near a feasible incumbent.

    The incumbent itself is always a feasible model hint.  Each coincidence
    unit may move within a bounded period radius; units currently using a
    penalized room receive the full period domain so the search can move room
    pressure across distant color classes.  The CP-SAT objective represents
    every official soft component exactly inside that domain.  A candidate is
    accepted only after the independent validator confirms complete hard
    feasibility and a strict objective reduction.
    """

    started = time.perf_counter()
    incumbent = tuple(sorted(assignments, key=lambda row: row.exam))
    incumbent_validation = validate_itc2007_exam_solution(problem, incumbent)
    telemetry: dict[str, object] = {
        "strategy": "incumbent_hinted_coupled_period_room_lns",
        "period_radius": max(0, int(period_radius)),
        "workers": max(1, int(workers)),
        "units": 0,
        "period_literals": 0,
        "placement_literals": 0,
        "pair_costs": 0,
        "status": "not_run",
        "score_before": incumbent_validation.objective.total,
        "score_after": incumbent_validation.objective.total,
        "accepted": False,
        "elapsed_seconds": 0.0,
    }
    if not incumbent_validation.feasible or time.perf_counter() >= deadline:
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return incumbent, incumbent_validation, telemetry

    search_reserve = min(0.08, max(0.01, 0.05 * (deadline - started)))
    search_deadline = deadline - search_reserve
    if time.perf_counter() >= search_deadline:
        telemetry["status"] = "insufficient_budget"
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return incumbent, incumbent_validation, telemetry

    exam_count = len(problem.exams)
    row_by_exam = {row.exam: row for row in incumbent}
    parent = list(range(exam_count))

    def find(exam_id: int) -> int:
        while parent[exam_id] != exam_id:
            parent[exam_id] = parent[parent[exam_id]]
            exam_id = parent[exam_id]
        return exam_id

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        if first_root > second_root:
            first_root, second_root = second_root, first_root
        parent[second_root] = first_root

    shared_counts = problem.shared_student_counts
    for constraint in problem.period_constraints:
        if constraint.kind == "EXAM_COINCIDENCE" and _coincidence_is_active(
            constraint, shared_counts
        ):
            union(constraint.first_exam, constraint.second_exam)
    grouped: dict[int, list[int]] = defaultdict(list)
    for exam_id in range(exam_count):
        grouped[find(exam_id)].append(exam_id)
    unit_members = tuple(
        tuple(members)
        for _, members in sorted(grouped.items(), key=lambda item: min(item[1]))
    )
    unit_by_exam = {
        exam_id: unit_id
        for unit_id, members in enumerate(unit_members)
        for exam_id in members
    }
    unit_count = len(unit_members)
    current_period = {
        unit_id: row_by_exam[members[0]].period
        for unit_id, members in enumerate(unit_members)
    }
    telemetry["units"] = unit_count

    neighbors: list[set[int]] = [set() for _ in range(unit_count)]
    pair_weights: list[dict[int, int]] = [defaultdict(int) for _ in range(unit_count)]
    for (left, right), common_students in shared_counts.items():
        if common_students <= 0:
            continue
        first_unit = unit_by_exam[left]
        second_unit = unit_by_exam[right]
        if first_unit == second_unit:
            telemetry["status"] = "coincident_conflict"
            telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
            return incumbent, incumbent_validation, telemetry
        neighbors[first_unit].add(second_unit)
        neighbors[second_unit].add(first_unit)
        pair_weights[first_unit][second_unit] += common_students
        pair_weights[second_unit][first_unit] += common_students

    predecessors: list[set[int]] = [set() for _ in range(unit_count)]
    successors: list[set[int]] = [set() for _ in range(unit_count)]
    for constraint in problem.period_constraints:
        if not _coincidence_is_active(constraint, shared_counts):
            continue
        first_unit = unit_by_exam[constraint.first_exam]
        second_unit = unit_by_exam[constraint.second_exam]
        if constraint.kind == "EXAM_COINCIDENCE":
            continue
        neighbors[first_unit].add(second_unit)
        neighbors[second_unit].add(first_unit)
        if constraint.kind == "AFTER":
            predecessors[first_unit].add(second_unit)
            successors[second_unit].add(first_unit)

    model = cp_model.CpModel()
    domains: dict[int, tuple[int, ...]] = {}
    period_var: dict[int, cp_model.IntVar] = {}
    period_use: dict[tuple[int, int], cp_model.IntVar] = {}
    day_var: dict[int, cp_model.IntVar] = {}
    day_ids: dict[str, int] = {}
    day_by_period = [
        day_ids.setdefault(period.date, len(day_ids)) for period in problem.periods
    ]
    period_radius = max(0, int(period_radius))
    for unit_id, members in enumerate(unit_members):
        if unit_id & 31 == 0 and time.perf_counter() >= search_deadline:
            telemetry["status"] = "deadline_during_period_variables"
            telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
            return incumbent, incumbent_validation, telemetry
        source = current_period[unit_id]
        full_domain = any(
            problem.rooms[row_by_exam[exam_id].room].penalty > 0 for exam_id in members
        )
        allowed = tuple(
            period_id
            for period_id, period in enumerate(problem.periods)
            if (full_domain or abs(period_id - source) <= period_radius)
            and all(
                problem.exams[exam_id].duration <= period.duration
                for exam_id in members
            )
        )
        if source not in allowed:
            telemetry["status"] = "incumbent_outside_domain"
            telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
            return incumbent, incumbent_validation, telemetry
        domains[unit_id] = allowed
        selected_period = model.new_int_var_from_domain(
            cp_model.Domain.from_values(allowed),
            f"coupled_period_u{unit_id}",
        )
        period_var[unit_id] = selected_period
        selected_day = model.new_int_var(
            0,
            max(0, len(day_ids) - 1),
            f"coupled_day_u{unit_id}",
        )
        model.add_element(selected_period, day_by_period, selected_day)
        day_var[unit_id] = selected_day
        choices = []
        for period_id in allowed:
            used = model.new_bool_var(f"coupled_use_u{unit_id}_p{period_id}")
            period_use[unit_id, period_id] = used
            model.add(selected_period == period_id).only_enforce_if(used)
            model.add(selected_period != period_id).only_enforce_if(used.negated())
            model.add_hint(used, int(period_id == source))
            choices.append(used)
        model.add_exactly_one(choices)
        model.add_hint(selected_period, source)
        telemetry["period_literals"] = int(telemetry["period_literals"]) + len(allowed)

    for first_unit in range(unit_count):
        for second_unit in neighbors[first_unit]:
            if first_unit < second_unit:
                model.add(period_var[first_unit] != period_var[second_unit])
        for predecessor in predecessors[first_unit]:
            model.add(period_var[first_unit] > period_var[predecessor])

    placement: dict[tuple[int, int, int], cp_model.IntVar] = {}
    by_room_period: dict[tuple[int, int], list[tuple[int, cp_model.IntVar]]] = (
        defaultdict(list)
    )
    by_duration: dict[tuple[int, int, int], list[cp_model.IntVar]] = defaultdict(list)
    objective_terms: list[cp_model.LinearExpr] = []
    for exam_id, exam in enumerate(problem.exams):
        if exam_id & 31 == 0 and time.perf_counter() >= search_deadline:
            telemetry["status"] = "deadline_during_placement_variables"
            telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
            return incumbent, incumbent_validation, telemetry
        unit_id = unit_by_exam[exam_id]
        all_choices = []
        for period_id in domains[unit_id]:
            period_choices = []
            for room_id, room in enumerate(problem.rooms):
                if exam.size > room.capacity:
                    continue
                selected = model.new_bool_var(
                    f"coupled_place_e{exam_id}_p{period_id}_r{room_id}"
                )
                placement[exam_id, period_id, room_id] = selected
                all_choices.append(selected)
                period_choices.append(selected)
                by_room_period[period_id, room_id].append((exam_id, selected))
                by_duration[period_id, room_id, exam.duration].append(selected)
                incumbent_row = row_by_exam[exam_id]
                model.add_hint(
                    selected,
                    int(
                        incumbent_row.period == period_id
                        and incumbent_row.room == room_id
                    ),
                )
                if room.penalty:
                    objective_terms.append(room.penalty * selected)
            model.add(sum(period_choices) == period_use[unit_id, period_id])
        model.add_exactly_one(all_choices)
        telemetry["placement_literals"] = int(telemetry["placement_literals"]) + len(
            all_choices
        )

    exclusive = {constraint.exam for constraint in problem.room_constraints}
    for (period_id, room_id), members in by_room_period.items():
        all_cell = [selected for _, selected in members]
        model.add(
            sum(problem.exams[exam_id].size * selected for exam_id, selected in members)
            <= problem.rooms[room_id].capacity
        )
        for exam_id, selected in members:
            if exam_id in exclusive:
                model.add(sum(all_cell) <= 1).only_enforce_if(selected)
        if problem.weights.non_mixed_durations:
            occupied = model.new_bool_var(f"coupled_occupied_p{period_id}_r{room_id}")
            model.add(sum(all_cell) >= occupied)
            model.add(sum(all_cell) <= len(all_cell) * occupied)
            duration_present = []
            for duration in sorted(
                {problem.exams[exam_id].duration for exam_id, _ in members}
            ):
                literals = by_duration[period_id, room_id, duration]
                if not literals:
                    continue
                present = model.new_bool_var(
                    f"coupled_duration_{duration}_p{period_id}_r{room_id}"
                )
                model.add(sum(literals) >= present)
                model.add(sum(literals) <= len(literals) * present)
                duration_present.append(present)
            objective_terms.extend(
                problem.weights.non_mixed_durations * present
                for present in duration_present
            )
            objective_terms.append(-problem.weights.non_mixed_durations * occupied)

    largest = set(
        sorted(
            range(exam_count),
            key=lambda exam_id: (-problem.exams[exam_id].size, exam_id),
        )[: problem.weights.frontload_largest_exams]
    )
    frontload_threshold = max(
        0, len(problem.periods) - problem.weights.frontload_last_periods
    )
    for unit_id, members in enumerate(unit_members):
        for period_id in domains[unit_id]:
            unary = sum(problem.periods[period_id].penalty for _ in members)
            unary += sum(
                problem.weights.frontload_penalty
                for exam_id in members
                if exam_id in largest and period_id >= frontload_threshold
            )
            if unary:
                objective_terms.append(unary * period_use[unit_id, period_id])

    for first_unit in range(unit_count):
        if first_unit & 31 == 0 and time.perf_counter() >= search_deadline:
            telemetry["status"] = "deadline_during_pair_costs"
            telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
            return incumbent, incumbent_validation, telemetry
        for second_unit, common_students in pair_weights[first_unit].items():
            if first_unit >= second_unit:
                continue
            distance = model.new_int_var(
                1,
                len(problem.periods) - 1,
                f"coupled_distance_{first_unit}_{second_unit}",
            )
            model.add_abs_equality(
                distance,
                period_var[first_unit] - period_var[second_unit],
            )
            same_day = model.new_bool_var(
                f"coupled_same_day_{first_unit}_{second_unit}"
            )
            model.add(day_var[first_unit] == day_var[second_unit]).only_enforce_if(
                same_day
            )
            model.add(day_var[first_unit] != day_var[second_unit]).only_enforce_if(
                same_day.negated()
            )
            if problem.weights.two_in_a_day:
                objective_terms.append(
                    common_students * problem.weights.two_in_a_day * same_day
                )
            if problem.weights.two_in_a_row != problem.weights.two_in_a_day:
                adjacent_same_day = model.new_bool_var(
                    f"coupled_adjacent_same_day_{first_unit}_{second_unit}"
                )
                model.add(adjacent_same_day <= same_day)
                model.add(distance == 1).only_enforce_if(adjacent_same_day)
                model.add(distance != 1).only_enforce_if(
                    [same_day, adjacent_same_day.negated()]
                )
                objective_terms.append(
                    common_students
                    * (problem.weights.two_in_a_row - problem.weights.two_in_a_day)
                    * adjacent_same_day
                )
            if problem.weights.period_spread > 0:
                within_spread = model.new_bool_var(
                    f"coupled_within_spread_{first_unit}_{second_unit}"
                )
                model.add(distance <= problem.weights.period_spread).only_enforce_if(
                    within_spread
                )
                model.add(distance > problem.weights.period_spread).only_enforce_if(
                    within_spread.negated()
                )
                objective_terms.append(common_students * within_spread)
            telemetry["pair_costs"] = int(telemetry["pair_costs"]) + 1

    incumbent_total = incumbent_validation.objective.total
    model.add(sum(objective_terms) <= incumbent_total)
    model.minimize(sum(objective_terms))
    remaining = search_deadline - time.perf_counter()
    if remaining <= 0:
        telemetry["status"] = "deadline_before_search"
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return incumbent, incumbent_validation, telemetry
    solver = cp_model.CpSolver()
    solver_return_reserve = min(0.25, max(0.02, 0.02 * remaining))
    solver.parameters.max_time_in_seconds = max(
        0.001,
        remaining - solver_return_reserve,
    )
    solver.parameters.num_search_workers = max(1, int(workers))
    solver.parameters.random_seed = int(seed)
    solver.parameters.randomize_search = True
    solver.parameters.use_lns_only = True
    raw_status = solver.solve(model)
    telemetry["status"] = solver.status_name(raw_status)
    telemetry["solver_return_reserve_seconds"] = solver_return_reserve
    if raw_status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        telemetry["solver_objective"] = int(round(solver.objective_value))
        telemetry["solver_best_bound"] = int(round(solver.best_objective_bound))
    if raw_status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return incumbent, incumbent_validation, telemetry
    if time.perf_counter() >= search_deadline:
        telemetry["status"] = "late_solver_return"
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return incumbent, incumbent_validation, telemetry

    candidate = []
    for exam_id in range(exam_count):
        unit_id = unit_by_exam[exam_id]
        period_id = int(solver.value(period_var[unit_id]))
        room_id = next(
            room_id
            for room_id in range(len(problem.rooms))
            if (exam_id, period_id, room_id) in placement
            and solver.value(placement[exam_id, period_id, room_id])
        )
        candidate.append(ITC2007ExamAssignment(exam_id, period_id, room_id))
    candidate_rows = tuple(candidate)
    candidate_validation = validate_itc2007_exam_solution(problem, candidate_rows)
    if time.perf_counter() >= deadline:
        telemetry["status"] = "late_validation"
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return incumbent, incumbent_validation, telemetry
    if (
        not candidate_validation.feasible
        or candidate_validation.objective.total >= incumbent_total
    ):
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return incumbent, incumbent_validation, telemetry
    telemetry.update(
        {
            "score_after": candidate_validation.objective.total,
            "accepted": True,
            "elapsed_seconds": max(0.0, time.perf_counter() - started),
        }
    )
    return candidate_rows, candidate_validation, telemetry


def _polish_exam_pressure_blocks(
    problem: ITC2007ExamProblem,
    assignments: Sequence[ITC2007ExamAssignment],
    *,
    deadline: float,
    seed: int,
    workers: int = 1,
) -> tuple[
    tuple[ITC2007ExamAssignment, ...],
    ITC2007ExamValidation,
    dict[str, object],
]:
    """Stream small exact period/room blocks under a short tail budget.

    Only the penalized-room coincidence units, two large-room blockers per
    period, or a few mixed-duration outliers are variable in each block.  All
    other exams remain as an exact fixed boundary.  This keeps a useful joint
    period/room neighborhood small enough for deterministic one-worker runs.
    """

    started = time.perf_counter()
    incumbent = tuple(sorted(assignments, key=lambda row: row.exam))
    incumbent_validation = validate_itc2007_exam_solution(problem, incumbent)
    telemetry: dict[str, object] = {
        "strategy": "streamed_pressure_block_coupled_lns",
        "score_before": incumbent_validation.objective.total,
        "score_after": incumbent_validation.objective.total,
        "candidate_blocks": 0,
        "attempted_blocks": 0,
        "accepted_blocks": 0,
        "optimal_blocks": 0,
        "selected_units": 0,
        "elapsed_seconds": 0.0,
        "accepted": False,
    }
    if not incumbent_validation.feasible or time.perf_counter() >= deadline:
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return incumbent, incumbent_validation, telemetry
    acceptance_reserve = min(0.04, max(0.01, 0.03 * (deadline - started)))
    search_deadline = deadline - acceptance_reserve
    telemetry["acceptance_reserve_seconds"] = acceptance_reserve
    if time.perf_counter() >= search_deadline:
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return incumbent, incumbent_validation, telemetry

    exam_count = len(problem.exams)
    parent = list(range(exam_count))

    def find(exam_id: int) -> int:
        while parent[exam_id] != exam_id:
            parent[exam_id] = parent[parent[exam_id]]
            exam_id = parent[exam_id]
        return exam_id

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        if first_root > second_root:
            first_root, second_root = second_root, first_root
        parent[second_root] = first_root

    shared_counts = problem.shared_student_counts
    for constraint in problem.period_constraints:
        if constraint.kind == "EXAM_COINCIDENCE" and _coincidence_is_active(
            constraint, shared_counts
        ):
            union(constraint.first_exam, constraint.second_exam)
    grouped: dict[int, list[int]] = defaultdict(list)
    for exam_id in range(exam_count):
        grouped[find(exam_id)].append(exam_id)
    unit_members = tuple(
        tuple(members)
        for _, members in sorted(grouped.items(), key=lambda item: min(item[1]))
    )
    unit_by_exam = {
        exam_id: unit_id
        for unit_id, members in enumerate(unit_members)
        for exam_id in members
    }
    unit_count = len(unit_members)
    neighbors: list[set[int]] = [set() for _ in range(unit_count)]
    pair_weights: list[dict[int, int]] = [defaultdict(int) for _ in range(unit_count)]
    for (left, right), common_students in shared_counts.items():
        if common_students <= 0:
            continue
        first_unit = unit_by_exam[left]
        second_unit = unit_by_exam[right]
        if first_unit == second_unit:
            telemetry["status"] = "coincident_conflict"
            telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
            return incumbent, incumbent_validation, telemetry
        neighbors[first_unit].add(second_unit)
        neighbors[second_unit].add(first_unit)
        pair_weights[first_unit][second_unit] += common_students
        pair_weights[second_unit][first_unit] += common_students
    predecessors: list[set[int]] = [set() for _ in range(unit_count)]
    successors: list[set[int]] = [set() for _ in range(unit_count)]
    for constraint in problem.period_constraints:
        if not _coincidence_is_active(constraint, shared_counts):
            continue
        first_unit = unit_by_exam[constraint.first_exam]
        second_unit = unit_by_exam[constraint.second_exam]
        if constraint.kind == "EXAM_COINCIDENCE":
            continue
        neighbors[first_unit].add(second_unit)
        neighbors[second_unit].add(first_unit)
        if constraint.kind == "AFTER":
            predecessors[first_unit].add(second_unit)
            successors[second_unit].add(first_unit)

    exclusive = {constraint.exam for constraint in problem.room_constraints}
    largest = set(
        sorted(
            range(exam_count),
            key=lambda exam_id: (-problem.exams[exam_id].size, exam_id),
        )[: problem.weights.frontload_largest_exams]
    )
    frontload_threshold = max(
        0, len(problem.periods) - problem.weights.frontload_last_periods
    )
    day_ids: dict[str, int] = {}
    day_by_period = tuple(
        day_ids.setdefault(period.date, len(day_ids)) for period in problem.periods
    )

    def period_metrics(
        rows: Sequence[ITC2007ExamAssignment],
    ) -> tuple[
        dict[int, list[ITC2007ExamAssignment]],
        dict[int, int],
        dict[int, int],
        dict[int, int],
    ]:
        by_period: dict[int, list[ITC2007ExamAssignment]] = defaultdict(list)
        for row in rows:
            by_period[row.period].append(row)
        loads = {
            period_id: sum(problem.exams[row.exam].size for row in period_rows)
            for period_id, period_rows in by_period.items()
        }
        room_pressure = {
            period_id: sum(problem.rooms[row.room].penalty for row in period_rows)
            for period_id, period_rows in by_period.items()
        }
        mixed_pressure: dict[int, int] = {}
        for period_id, period_rows in by_period.items():
            durations: dict[int, set[int]] = defaultdict(set)
            for row in period_rows:
                durations[row.room].add(problem.exams[row.exam].duration)
            mixed_pressure[period_id] = sum(
                max(0, len(values) - 1) for values in durations.values()
            )
        return by_period, loads, room_pressure, mixed_pressure

    def candidate_blocks(
        rows: Sequence[ITC2007ExamAssignment],
    ) -> list[tuple[tuple[int, ...], bool]]:
        _, loads, room_pressure, mixed_pressure = period_metrics(rows)
        pressure = [
            period_id
            for period_id in range(len(problem.periods))
            if room_pressure.get(period_id, 0) > 0
        ]
        relief = sorted(
            range(len(problem.periods)),
            key=lambda period_id: (
                problem.periods[period_id].penalty > 0,
                room_pressure.get(period_id, 0) > 0,
                loads.get(period_id, 0),
                mixed_pressure.get(period_id, 0),
                period_id,
            ),
        )
        orders = [
            sorted(
                pressure,
                key=lambda period_id: (
                    loads.get(period_id, 0),
                    -room_pressure.get(period_id, 0),
                    period_id,
                ),
            ),
            sorted(pressure),
        ]
        raw: list[tuple[tuple[int, ...], bool, tuple[int, ...]]] = []
        pressure_raw: list[tuple[tuple[int, ...], bool, tuple[int, ...]]] = []
        relief_pool = relief[:4]
        for order_index, order in enumerate(orders):
            for offset in range(0, len(order), 5):
                sources = order[offset : offset + 5]
                if len(sources) < 5 or not relief_pool:
                    continue
                chunk_index = offset // 5
                target = relief_pool[(chunk_index + 2 * order_index) % len(relief_pool)]
                block = tuple(sorted({*sources, target}))
                if len(block) != 6:
                    continue
                load_key = sum(loads.get(period_id, 0) for period_id in block)
                pressure_raw.append(
                    (
                        block,
                        False,
                        (
                            0,
                            load_key,
                            order_index,
                            chunk_index,
                        ),
                    )
                )
        raw.extend(sorted(pressure_raw, key=lambda item: item[2])[:10])
        mixed_periods = [
            period_id
            for period_id in range(len(problem.periods))
            if mixed_pressure.get(period_id, 0) > 0
        ]
        for mixed_order in (
            sorted(
                mixed_periods,
                key=lambda period_id: (
                    -mixed_pressure.get(period_id, 0),
                    loads.get(period_id, 0),
                    period_id,
                ),
            ),
            sorted(mixed_periods),
        ):
            for offset in range(0, len(mixed_order), 6):
                block = tuple(sorted(mixed_order[offset : offset + 6]))
                if len(block) == 6:
                    raw.append((block, True, (1, offset // 6, 0, 0)))
        seen: set[tuple[tuple[int, ...], bool]] = set()
        ordered: list[tuple[tuple[int, ...], bool]] = []
        for block, mixed_mode, _ in sorted(raw, key=lambda item: item[2]):
            key = (block, mixed_mode)
            if key in seen:
                continue
            seen.add(key)
            ordered.append(key)
        return ordered

    def optimize_block(
        rows: tuple[ITC2007ExamAssignment, ...],
        validation: ITC2007ExamValidation,
        block: tuple[int, ...],
        *,
        mixed_mode: bool,
        block_deadline: float,
        block_seed: int,
    ) -> tuple[tuple[ITC2007ExamAssignment, ...], ITC2007ExamValidation, str, int]:
        row_by_exam = {row.exam: row for row in rows}
        current_period = {
            unit_id: row_by_exam[members[0]].period
            for unit_id, members in enumerate(unit_members)
        }
        block_set = set(block)
        limited_room_zero_units: set[int] = set()
        limited_mixed_units: set[int] = set()
        for period_id in block:
            room_zero = [
                unit_id
                for unit_id, source in current_period.items()
                if source == period_id
                and any(
                    row_by_exam[exam_id].room == 0 for exam_id in unit_members[unit_id]
                )
            ]
            room_zero.sort(
                key=lambda unit_id: (
                    -sum(
                        problem.exams[exam_id].size for exam_id in unit_members[unit_id]
                    ),
                    unit_id,
                )
            )
            limited_room_zero_units.update(room_zero[:2])
            if not mixed_mode:
                continue
            mixed_groups: list[tuple[int, int, int, int, tuple[int, ...]]] = []
            for room_id in range(len(problem.rooms)):
                by_duration: dict[int, list[int]] = defaultdict(list)
                for row in rows:
                    if row.period == period_id and row.room == room_id:
                        by_duration[problem.exams[row.exam].duration].append(row.exam)
                if len(by_duration) <= 1:
                    continue
                duration, exam_ids = min(
                    by_duration.items(),
                    key=lambda item: (
                        sum(problem.exams[exam_id].size for exam_id in item[1]),
                        len(item[1]),
                        item[0],
                    ),
                )
                mixed_groups.append(
                    (
                        sum(problem.exams[exam_id].size for exam_id in exam_ids),
                        len(exam_ids),
                        room_id,
                        duration,
                        tuple(exam_ids),
                    )
                )
            for *_, exam_ids in sorted(mixed_groups)[:2]:
                limited_mixed_units.update(
                    unit_by_exam[exam_id] for exam_id in exam_ids
                )

        selected = tuple(
            unit_id
            for unit_id, period_id in current_period.items()
            if period_id in block_set
            and (
                unit_id in limited_room_zero_units
                or unit_id in limited_mixed_units
                or any(
                    problem.rooms[row_by_exam[exam_id].room].penalty > 0
                    for exam_id in unit_members[unit_id]
                )
            )
        )
        if not selected:
            return rows, validation, "empty", 0
        selected_set = set(selected)
        selected_exams = tuple(
            exam_id for unit_id in selected for exam_id in unit_members[unit_id]
        )
        selected_exam_set = set(selected_exams)
        fixed_by_cell: dict[tuple[int, int], list[int]] = defaultdict(list)
        for row in rows:
            if row.period in block_set and row.exam not in selected_exam_set:
                fixed_by_cell[row.period, row.room].append(row.exam)
        block_loads = {
            period_id: sum(
                problem.exams[row.exam].size for row in rows if row.period == period_id
            )
            for period_id in block
        }
        block_room_pressure = {
            period_id: sum(
                problem.rooms[row.room].penalty
                for row in rows
                if row.period == period_id
            )
            for period_id in block
        }

        domains: dict[int, tuple[int, ...]] = {}
        for unit_id in selected:
            source = current_period[unit_id]
            allowed = []
            for period_id in block:
                if any(
                    problem.exams[exam_id].duration
                    > problem.periods[period_id].duration
                    for exam_id in unit_members[unit_id]
                ):
                    continue
                if any(
                    neighbor not in selected_set
                    and current_period[neighbor] == period_id
                    for neighbor in neighbors[unit_id]
                ):
                    continue
                if any(
                    predecessor not in selected_set
                    and current_period[predecessor] >= period_id
                    for predecessor in predecessors[unit_id]
                ):
                    continue
                if any(
                    successor not in selected_set
                    and current_period[successor] <= period_id
                    for successor in successors[unit_id]
                ):
                    continue
                allowed.append(period_id)
            if source not in allowed:
                return rows, validation, "incumbent_outside_domain", len(selected)

            def boundary_cost(period_id: int) -> tuple[int, int]:
                unary = sum(
                    problem.periods[period_id].penalty
                    + int(exam_id in largest and period_id >= frontload_threshold)
                    * problem.weights.frontload_penalty
                    for exam_id in unit_members[unit_id]
                )
                external = sum(
                    common_students
                    * _temporal_pair_cost(problem, period_id, current_period[neighbor])
                    for neighbor, common_students in pair_weights[unit_id].items()
                    if neighbor not in selected_set
                )
                return unary + external, period_id

            possible_alternatives = [
                period_id for period_id in allowed if period_id != source
            ]
            alternatives = []
            if possible_alternatives:
                alternatives.append(min(possible_alternatives, key=boundary_cost))
                relief_target = min(
                    possible_alternatives,
                    key=lambda period_id: (
                        block_room_pressure[period_id] > 0,
                        block_loads[period_id],
                        boundary_cost(period_id),
                    ),
                )
                if relief_target not in alternatives:
                    alternatives.append(relief_target)
            domains[unit_id] = tuple([source, *alternatives])

        model = cp_model.CpModel()
        period_var: dict[int, cp_model.IntVar] = {}
        day_var: dict[int, cp_model.IntVar] = {}
        period_use: dict[tuple[int, int], cp_model.IntVar] = {}
        objective_terms: list[cp_model.LinearExpr] = []
        for unit_id in selected:
            source = current_period[unit_id]
            selected_period = model.new_int_var_from_domain(
                cp_model.Domain.from_values(domains[unit_id]),
                f"pressure_period_u{unit_id}",
            )
            period_var[unit_id] = selected_period
            selected_day = model.new_int_var(
                0, max(0, len(day_ids) - 1), f"pressure_day_u{unit_id}"
            )
            model.add_element(selected_period, day_by_period, selected_day)
            day_var[unit_id] = selected_day
            choices = []
            for period_id in domains[unit_id]:
                used = model.new_bool_var(f"pressure_use_u{unit_id}_p{period_id}")
                period_use[unit_id, period_id] = used
                model.add(selected_period == period_id).only_enforce_if(used)
                model.add(selected_period != period_id).only_enforce_if(used.negated())
                model.add_hint(used, int(period_id == source))
                choices.append(used)
                unary = sum(
                    problem.periods[period_id].penalty
                    + int(exam_id in largest and period_id >= frontload_threshold)
                    * problem.weights.frontload_penalty
                    for exam_id in unit_members[unit_id]
                )
                external = sum(
                    common_students
                    * _temporal_pair_cost(problem, period_id, current_period[neighbor])
                    for neighbor, common_students in pair_weights[unit_id].items()
                    if neighbor not in selected_set
                )
                if unary + external:
                    objective_terms.append((unary + external) * used)
            model.add_exactly_one(choices)
            model.add_hint(selected_period, source)

        for first_unit in selected:
            for second_unit in neighbors[first_unit]:
                if second_unit in selected_set and first_unit < second_unit:
                    model.add(period_var[first_unit] != period_var[second_unit])
            for predecessor in predecessors[first_unit]:
                if predecessor in selected_set:
                    model.add(period_var[first_unit] > period_var[predecessor])

        placement: dict[tuple[int, int, int], cp_model.IntVar] = {}
        by_cell: dict[tuple[int, int], list[tuple[int, cp_model.IntVar]]] = defaultdict(
            list
        )
        by_duration: dict[tuple[int, int, int], list[cp_model.IntVar]] = defaultdict(
            list
        )
        for exam_id in selected_exams:
            unit_id = unit_by_exam[exam_id]
            exam = problem.exams[exam_id]
            all_choices = []
            for period_id in domains[unit_id]:
                period_choices = []
                for room_id, room in enumerate(problem.rooms):
                    if exam.size > room.capacity:
                        continue
                    selected_room = model.new_bool_var(
                        f"pressure_place_e{exam_id}_p{period_id}_r{room_id}"
                    )
                    placement[exam_id, period_id, room_id] = selected_room
                    all_choices.append(selected_room)
                    period_choices.append(selected_room)
                    by_cell[period_id, room_id].append((exam_id, selected_room))
                    by_duration[period_id, room_id, exam.duration].append(selected_room)
                    model.add_hint(
                        selected_room,
                        int(
                            row_by_exam[exam_id].period == period_id
                            and row_by_exam[exam_id].room == room_id
                        ),
                    )
                    if room.penalty:
                        objective_terms.append(room.penalty * selected_room)
                model.add(sum(period_choices) == period_use[unit_id, period_id])
            model.add_exactly_one(all_choices)

        for (period_id, room_id), members in by_cell.items():
            literals = [literal for _, literal in members]
            fixed_exams = fixed_by_cell[period_id, room_id]
            fixed_load = sum(problem.exams[exam_id].size for exam_id in fixed_exams)
            model.add(
                sum(
                    problem.exams[exam_id].size * literal
                    for exam_id, literal in members
                )
                <= problem.rooms[room_id].capacity - fixed_load
            )
            if any(exam_id in exclusive for exam_id in fixed_exams):
                model.add(sum(literals) == 0)
            for exam_id, literal in members:
                if exam_id not in exclusive:
                    continue
                if fixed_exams:
                    model.add(literal == 0)
                else:
                    model.add(sum(literals) <= 1).only_enforce_if(literal)
            occupied = None
            if not fixed_exams:
                occupied = model.new_bool_var(
                    f"pressure_occupied_p{period_id}_r{room_id}"
                )
                model.add(sum(literals) >= occupied)
                model.add(sum(literals) <= len(literals) * occupied)
            fixed_durations = {
                problem.exams[exam_id].duration for exam_id in fixed_exams
            }
            for duration in sorted(
                {problem.exams[exam_id].duration for exam_id, _ in members}
            ):
                if duration in fixed_durations:
                    continue
                duration_literals = by_duration[period_id, room_id, duration]
                present = model.new_bool_var(
                    f"pressure_duration_{duration}_p{period_id}_r{room_id}"
                )
                model.add(sum(duration_literals) >= present)
                model.add(sum(duration_literals) <= len(duration_literals) * present)
                objective_terms.append(problem.weights.non_mixed_durations * present)
            if occupied is not None:
                objective_terms.append(-problem.weights.non_mixed_durations * occupied)

        for first_unit in selected:
            for second_unit, common_students in pair_weights[first_unit].items():
                if second_unit not in selected_set or first_unit >= second_unit:
                    continue
                distance = model.new_int_var(
                    1,
                    len(problem.periods) - 1,
                    f"pressure_distance_{first_unit}_{second_unit}",
                )
                model.add_abs_equality(
                    distance, period_var[first_unit] - period_var[second_unit]
                )
                same_day = model.new_bool_var(
                    f"pressure_same_day_{first_unit}_{second_unit}"
                )
                model.add(day_var[first_unit] == day_var[second_unit]).only_enforce_if(
                    same_day
                )
                model.add(day_var[first_unit] != day_var[second_unit]).only_enforce_if(
                    same_day.negated()
                )
                if problem.weights.two_in_a_day:
                    objective_terms.append(
                        common_students * problem.weights.two_in_a_day * same_day
                    )
                if problem.weights.two_in_a_row != problem.weights.two_in_a_day:
                    adjacent = model.new_bool_var(
                        f"pressure_adjacent_{first_unit}_{second_unit}"
                    )
                    model.add(adjacent <= same_day)
                    model.add(distance == 1).only_enforce_if(adjacent)
                    model.add(distance != 1).only_enforce_if(
                        [same_day, adjacent.negated()]
                    )
                    objective_terms.append(
                        common_students
                        * (problem.weights.two_in_a_row - problem.weights.two_in_a_day)
                        * adjacent
                    )
                if problem.weights.period_spread:
                    within_spread = model.new_bool_var(
                        f"pressure_spread_{first_unit}_{second_unit}"
                    )
                    model.add(
                        distance <= problem.weights.period_spread
                    ).only_enforce_if(within_spread)
                    model.add(distance > problem.weights.period_spread).only_enforce_if(
                        within_spread.negated()
                    )
                    objective_terms.append(common_students * within_spread)

        model.minimize(sum(objective_terms))
        remaining = block_deadline - time.perf_counter()
        if remaining <= 0.01:
            return rows, validation, "deadline_before_search", len(selected)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(0.001, remaining - 0.01)
        solver.parameters.num_search_workers = max(1, int(workers))
        solver.parameters.random_seed = int(block_seed)
        solver.parameters.randomize_search = True
        raw_status = solver.solve(model)
        status = solver.status_name(raw_status)
        if raw_status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            return rows, validation, status, len(selected)
        candidate = []
        for exam_id in range(exam_count):
            if exam_id not in selected_exam_set:
                candidate.append(row_by_exam[exam_id])
                continue
            unit_id = unit_by_exam[exam_id]
            period_id = int(solver.value(period_var[unit_id]))
            room_id = next(
                candidate_room
                for candidate_room in range(len(problem.rooms))
                if (exam_id, period_id, candidate_room) in placement
                and solver.value(placement[exam_id, period_id, candidate_room])
            )
            candidate.append(ITC2007ExamAssignment(exam_id, period_id, room_id))
        candidate_rows = tuple(candidate)
        candidate_validation = validate_itc2007_exam_solution(problem, candidate_rows)
        if (
            time.perf_counter() >= search_deadline
            or not candidate_validation.feasible
            or candidate_validation.objective.total >= validation.objective.total
        ):
            return rows, validation, status, len(selected)
        return candidate_rows, candidate_validation, status, len(selected)

    blocks = candidate_blocks(incumbent)
    telemetry["candidate_blocks"] = len(blocks)
    for block_index, (block, mixed_mode) in enumerate(blocks):
        now = time.perf_counter()
        remaining = search_deadline - now
        if remaining <= 0.03:
            break
        blocks_left = max(1, len(blocks) - block_index)
        fair_slice = min(0.22, max(0.045, remaining / blocks_left))
        candidate, validation, status, selected_units = optimize_block(
            incumbent,
            incumbent_validation,
            block,
            mixed_mode=mixed_mode,
            block_deadline=min(search_deadline, now + fair_slice),
            block_seed=seed + block_index,
        )
        telemetry["attempted_blocks"] = int(telemetry["attempted_blocks"]) + 1
        telemetry["selected_units"] = int(telemetry["selected_units"]) + selected_units
        if status == "OPTIMAL":
            telemetry["optimal_blocks"] = int(telemetry["optimal_blocks"]) + 1
        if validation.objective.total < incumbent_validation.objective.total:
            incumbent = candidate
            incumbent_validation = validation
            telemetry["accepted_blocks"] = int(telemetry["accepted_blocks"]) + 1

    telemetry.update(
        {
            "score_after": incumbent_validation.objective.total,
            "accepted": incumbent_validation.objective.total
            < int(telemetry["score_before"]),
            "elapsed_seconds": max(0.0, time.perf_counter() - started),
        }
    )
    return incumbent, incumbent_validation, telemetry


def _temporal_pair_cost(
    problem: ITC2007ExamProblem,
    first_period: int,
    second_period: int,
) -> int:
    low = min(first_period, second_period)
    high = max(first_period, second_period)
    distance = high - low
    same_day = problem.periods[low].date == problem.periods[high].date
    cost = 0
    if distance == 1 and same_day:
        cost += problem.weights.two_in_a_row
    elif distance > 1 and same_day:
        cost += problem.weights.two_in_a_day
    if 0 < distance <= problem.weights.period_spread:
        cost += 1
    return int(cost)


def _period_polish_temporal_unary_delta(
    problem: ITC2007ExamProblem,
    unit_members: Sequence[Sequence[int]],
    pair_weights: Sequence[dict[int, int]],
    period_by_unit: dict[int, int],
    changes: dict[int, int],
) -> int:
    """Exact non-room objective delta for an atomic period change.

    This deliberately remains a small, independently testable seam. The hot
    room-burden exchange uses an algebraically equivalent cached calculation,
    while focused randomized tests compare both against full public scoring.
    """

    largest = set(
        sorted(
            range(len(problem.exams)),
            key=lambda exam_id: (-problem.exams[exam_id].size, exam_id),
        )[: problem.weights.frontload_largest_exams]
    )
    frontload_threshold = max(
        0,
        len(problem.periods) - problem.weights.frontload_last_periods,
    )

    def unary_cost(unit_id: int, period_id: int) -> int:
        cost = 0
        for exam_id in unit_members[unit_id]:
            cost += problem.periods[period_id].penalty
            if exam_id in largest and period_id >= frontload_threshold:
                cost += problem.weights.frontload_penalty
        return cost

    delta = sum(
        unary_cost(unit_id, target) - unary_cost(unit_id, period_by_unit[unit_id])
        for unit_id, target in changes.items()
    )
    affected_edges: set[tuple[int, int]] = set()
    for unit_id in changes:
        affected_edges.update(
            (min(unit_id, neighbor), max(unit_id, neighbor))
            for neighbor in pair_weights[unit_id]
        )
    for left, right in affected_edges:
        common_students = pair_weights[left].get(right, 0)
        if common_students <= 0:
            continue
        old_cost = _temporal_pair_cost(
            problem,
            period_by_unit[left],
            period_by_unit[right],
        )
        new_cost = _temporal_pair_cost(
            problem,
            changes.get(left, period_by_unit[left]),
            changes.get(right, period_by_unit[right]),
        )
        delta += common_students * (new_cost - old_cost)
    return int(delta)


class _PeriodPolishDeltaCache:
    """Exact cached single/swap deltas for one period-coloring state."""

    def __init__(
        self,
        problem: ITC2007ExamProblem,
        unit_members: Sequence[Sequence[int]],
        pair_weights: Sequence[dict[int, int]],
    ) -> None:
        self.problem = problem
        self.unit_members = unit_members
        self.pair_weights = pair_weights
        self.largest = set(
            sorted(
                range(len(problem.exams)),
                key=lambda exam_id: (-problem.exams[exam_id].size, exam_id),
            )[: problem.weights.frontload_largest_exams]
        )
        self.frontload_threshold = max(
            0,
            len(problem.periods) - problem.weights.frontload_last_periods,
        )
        period_count = len(problem.periods)
        self.period_pair_cost_matrix = (
            tuple(
                tuple(
                    _temporal_pair_cost(problem, first_period, second_period)
                    for second_period in range(period_count)
                )
                for first_period in range(period_count)
            )
            if period_count <= 128
            else None
        )
        self.period_pair_cost_cache: dict[tuple[int, int], int] = {}
        self.period_by_unit: dict[int, int] = {}
        self.neighbor_weights_by_period: list[dict[int, int]] = []
        self.placement_delta_cache: dict[tuple[int, int], int] = {}

    @property
    def placement_cache_entries(self) -> int:
        return len(self.placement_delta_cache)

    def reset(self, period_by_unit: dict[int, int]) -> None:
        self.period_by_unit = period_by_unit
        self.neighbor_weights_by_period = []
        for unit_id in range(len(self.unit_members)):
            weights: dict[int, int] = defaultdict(int)
            for neighbor, common_students in self.pair_weights[unit_id].items():
                weights[period_by_unit[neighbor]] += common_students
            self.neighbor_weights_by_period.append(weights)
        self.placement_delta_cache = {}

    def _period_pair_cost(self, first_period: int, second_period: int) -> int:
        if self.period_pair_cost_matrix is not None:
            return self.period_pair_cost_matrix[first_period][second_period]
        key = (
            (first_period, second_period)
            if first_period <= second_period
            else (second_period, first_period)
        )
        cached = self.period_pair_cost_cache.get(key)
        if cached is None:
            cached = _temporal_pair_cost(self.problem, *key)
            self.period_pair_cost_cache[key] = cached
        return cached

    def _unary_cost(self, unit_id: int, period_id: int) -> int:
        cost = 0
        for exam_id in self.unit_members[unit_id]:
            cost += self.problem.periods[period_id].penalty
            if exam_id in self.largest and period_id >= self.frontload_threshold:
                cost += self.problem.weights.frontload_penalty
        return cost

    def placement_delta(self, unit_id: int, target: int) -> int:
        key = (unit_id, target)
        cached = self.placement_delta_cache.get(key)
        if cached is not None:
            return cached
        source = self.period_by_unit[unit_id]
        delta = self._unary_cost(unit_id, target) - self._unary_cost(unit_id, source)
        for neighbor_period, common_students in self.neighbor_weights_by_period[
            unit_id
        ].items():
            delta += common_students * (
                self._period_pair_cost(target, neighbor_period)
                - self._period_pair_cost(source, neighbor_period)
            )
        self.placement_delta_cache[key] = int(delta)
        return int(delta)

    def swap_delta(self, first: int, second: int) -> int:
        first_source = self.period_by_unit[first]
        second_source = self.period_by_unit[second]
        delta = self.placement_delta(first, second_source)
        delta += self.placement_delta(second, first_source)
        common_students = self.pair_weights[first].get(second, 0)
        if common_students > 0:
            old_edge = self._period_pair_cost(first_source, second_source)
            new_edge = self._period_pair_cost(second_source, first_source)
            independently_moved_edges = (
                self._period_pair_cost(second_source, second_source)
                - old_edge
                + self._period_pair_cost(first_source, first_source)
                - old_edge
            )
            delta += common_students * (new_edge - old_edge - independently_moved_edges)
        return int(delta)


@dataclass(frozen=True)
class _PostIncumbentExamGraph:
    """Representation-derived hard/temporal graph shared by portfolio moves."""

    unit_members: tuple[tuple[int, ...], ...]
    unit_by_exam: tuple[int, ...]
    unit_domains: tuple[frozenset[int], ...]
    neighbors: tuple[frozenset[int], ...]
    pair_weights: tuple[dict[int, int], ...]
    predecessors: tuple[frozenset[int], ...]
    successors: tuple[frozenset[int], ...]


def _build_post_incumbent_exam_graph(
    problem: ITC2007ExamProblem,
    *,
    deadline: float,
) -> _PostIncumbentExamGraph | None:
    """Build the contracted exam graph, or fail closed at the deadline."""

    exam_count = len(problem.exams)
    parent = list(range(exam_count))

    def find(exam_id: int) -> int:
        while parent[exam_id] != exam_id:
            parent[exam_id] = parent[parent[exam_id]]
            exam_id = parent[exam_id]
        return exam_id

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        if first_root > second_root:
            first_root, second_root = second_root, first_root
        parent[second_root] = first_root

    shared_counts = problem.shared_student_counts
    for constraint in problem.period_constraints:
        if constraint.kind == "EXAM_COINCIDENCE" and _coincidence_is_active(
            constraint, shared_counts
        ):
            union(constraint.first_exam, constraint.second_exam)

    grouped: dict[int, list[int]] = defaultdict(list)
    for exam_id in range(exam_count):
        if exam_id & 127 == 0 and time.perf_counter() >= deadline:
            return None
        grouped[find(exam_id)].append(exam_id)
    unit_members = tuple(
        tuple(members)
        for _, members in sorted(grouped.items(), key=lambda item: min(item[1]))
    )
    unit_by_exam_values = [0] * exam_count
    for unit_id, members in enumerate(unit_members):
        for exam_id in members:
            unit_by_exam_values[exam_id] = unit_id
    unit_by_exam = tuple(unit_by_exam_values)

    unit_domains: list[frozenset[int]] = []
    for members in unit_members:
        common = set(range(len(problem.periods)))
        for exam_id in members:
            common.intersection_update(
                period_id
                for period_id, period in enumerate(problem.periods)
                if problem.exams[exam_id].duration <= period.duration
            )
        unit_domains.append(frozenset(common))

    neighbors: list[set[int]] = [set() for _ in unit_members]
    pair_weights: list[dict[int, int]] = [defaultdict(int) for _ in unit_members]
    for pair_index, ((left, right), common_students) in enumerate(
        shared_counts.items()
    ):
        if pair_index & 255 == 0 and time.perf_counter() >= deadline:
            return None
        if common_students <= 0:
            continue
        first_unit = unit_by_exam[left]
        second_unit = unit_by_exam[right]
        if first_unit == second_unit:
            return None
        neighbors[first_unit].add(second_unit)
        neighbors[second_unit].add(first_unit)
        pair_weights[first_unit][second_unit] += common_students
        pair_weights[second_unit][first_unit] += common_students

    predecessors: list[set[int]] = [set() for _ in unit_members]
    successors: list[set[int]] = [set() for _ in unit_members]
    for constraint in problem.period_constraints:
        if not _coincidence_is_active(constraint, shared_counts):
            continue
        first_unit = unit_by_exam[constraint.first_exam]
        second_unit = unit_by_exam[constraint.second_exam]
        if constraint.kind == "EXAM_COINCIDENCE":
            continue
        if first_unit == second_unit:
            return None
        neighbors[first_unit].add(second_unit)
        neighbors[second_unit].add(first_unit)
        if constraint.kind == "AFTER":
            predecessors[first_unit].add(second_unit)
            successors[second_unit].add(first_unit)

    return _PostIncumbentExamGraph(
        unit_members=unit_members,
        unit_by_exam=unit_by_exam,
        unit_domains=tuple(unit_domains),
        neighbors=tuple(frozenset(values) for values in neighbors),
        pair_weights=tuple(dict(values) for values in pair_weights),
        predecessors=tuple(frozenset(values) for values in predecessors),
        successors=tuple(frozenset(values) for values in successors),
    )


def _polish_post_incumbent_singleton_room_exchanges(
    problem: ITC2007ExamProblem,
    assignments: Sequence[ITC2007ExamAssignment],
    *,
    deadline: float,
    graph: _PostIncumbentExamGraph | None = None,
    rank_limit: int = 64,
) -> tuple[
    tuple[ITC2007ExamAssignment, ...],
    ITC2007ExamValidation,
    dict[str, object],
]:
    """Swap singleton periods while directly repairing both room classes."""

    started = time.perf_counter()
    source = tuple(sorted(assignments, key=lambda row: row.exam))
    source_validation = validate_itc2007_exam_solution(problem, source)
    telemetry: dict[str, object] = {
        "strategy": "singleton_period_swap_with_room_exchange",
        "passes": 0,
        "generated_candidates": 0,
        "accepted_moves": 0,
        "rank_limit": max(0, int(rank_limit)),
        "score_before": source_validation.objective.total,
        "score_after": source_validation.objective.total,
        "accepted": False,
        "status": "not_run",
        "elapsed_seconds": 0.0,
    }
    if not source_validation.feasible:
        telemetry["status"] = "invalid_source"
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return source, source_validation, telemetry
    if time.perf_counter() >= deadline or rank_limit <= 0:
        telemetry["status"] = "deadline" if rank_limit > 0 else "disabled"
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return source, source_validation, telemetry

    active_graph = graph or _build_post_incumbent_exam_graph(
        problem,
        deadline=deadline,
    )
    if active_graph is None or time.perf_counter() >= deadline:
        telemetry["status"] = "deadline"
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return source, source_validation, telemetry

    unit_members = active_graph.unit_members
    unit_by_exam = active_graph.unit_by_exam
    row_by_exam = {row.exam: row for row in source}
    period_by_unit = [row_by_exam[members[0]].period for members in unit_members]
    room_by_exam = [row_by_exam[exam_id].room for exam_id in range(len(problem.exams))]

    exclusive_exams = {constraint.exam for constraint in problem.room_constraints}
    room_load: dict[tuple[int, int], int] = defaultdict(int)
    room_durations: dict[tuple[int, int], Counter[int]] = defaultdict(Counter)
    room_exam_count: dict[tuple[int, int], int] = defaultdict(int)
    room_exclusive_count: dict[tuple[int, int], int] = defaultdict(int)
    for row in source:
        key = (row.period, row.room)
        exam = problem.exams[row.exam]
        room_load[key] += exam.size
        room_durations[key][exam.duration] += 1
        room_exam_count[key] += 1
        room_exclusive_count[key] += int(row.exam in exclusive_exams)

    room_order = {
        exam_id: tuple(
            room_id
            for room_id, room in sorted(
                enumerate(problem.rooms),
                key=lambda item: (
                    item[1].penalty,
                    (
                        item[1].capacity - problem.exams[exam_id].size
                        if item[1].capacity >= problem.exams[exam_id].size
                        else 10_000
                    ),
                    item[0],
                ),
            )
            if problem.exams[exam_id].size <= room.capacity
        )
        for exam_id in range(len(problem.exams))
    }
    delta_cache = _PeriodPolishDeltaCache(
        problem,
        unit_members,
        active_graph.pair_weights,
    )

    def reset_delta_cache() -> None:
        delta_cache.reset(
            {unit_id: period for unit_id, period in enumerate(period_by_unit)}
        )

    reset_delta_cache()

    def changes_are_hard_valid(changes: dict[int, int]) -> bool:
        for unit_id, target in changes.items():
            if target == period_by_unit[unit_id]:
                return False
            if target not in active_graph.unit_domains[unit_id]:
                return False
            if any(
                changes.get(neighbor, period_by_unit[neighbor]) == target
                for neighbor in active_graph.neighbors[unit_id]
            ):
                return False
            if any(
                changes.get(predecessor, period_by_unit[predecessor]) >= target
                for predecessor in active_graph.predecessors[unit_id]
            ):
                return False
            if any(
                changes.get(successor, period_by_unit[successor]) <= target
                for successor in active_graph.successors[unit_id]
            ):
                return False
        return True

    def mixed_cost(durations: Counter[int]) -> int:
        return problem.weights.non_mixed_durations * max(0, len(durations) - 1)

    def replacement_room_cost(
        removed_exam: int,
        added_exam: int,
    ) -> tuple[int, int] | None:
        period_id = period_by_unit[unit_by_exam[removed_exam]]
        removed_room = room_by_exam[removed_exam]
        removed = problem.exams[removed_exam]
        added = problem.exams[added_exam]
        best: tuple[int, int] | None = None
        for added_room in room_order[added_exam]:
            keys = {(period_id, removed_room), (period_id, added_room)}
            loads = {key: room_load[key] for key in keys}
            counts = {key: room_exam_count[key] for key in keys}
            exclusives = {key: room_exclusive_count[key] for key in keys}
            durations = {key: room_durations[key].copy() for key in keys}
            before_mixed = sum(mixed_cost(values) for values in durations.values())
            removed_key = (period_id, removed_room)
            added_key = (period_id, added_room)
            loads[removed_key] -= removed.size
            counts[removed_key] -= 1
            exclusives[removed_key] -= int(removed_exam in exclusive_exams)
            durations[removed_key][removed.duration] -= 1
            if durations[removed_key][removed.duration] <= 0:
                del durations[removed_key][removed.duration]
            loads[added_key] += added.size
            counts[added_key] += 1
            exclusives[added_key] += int(added_exam in exclusive_exams)
            durations[added_key][added.duration] += 1
            if loads[added_key] > problem.rooms[added_room].capacity:
                continue
            if any(exclusives[key] > 0 and counts[key] > 1 for key in keys):
                continue
            candidate = (
                problem.rooms[added_room].penalty
                - problem.rooms[removed_room].penalty
                + sum(mixed_cost(values) for values in durations.values())
                - before_mixed,
                added_room,
            )
            if best is None or candidate < best:
                best = candidate
        return best

    def apply_exchange(
        placements: dict[int, tuple[int, int]],
    ) -> None:
        target_by_unit: dict[int, int] = {}
        for exam_id, (target_period, target_room) in placements.items():
            unit_id = unit_by_exam[exam_id]
            source_period = period_by_unit[unit_id]
            source_room = room_by_exam[exam_id]
            exam = problem.exams[exam_id]
            source_key = (source_period, source_room)
            target_key = (target_period, target_room)
            room_load[source_key] -= exam.size
            room_exam_count[source_key] -= 1
            room_exclusive_count[source_key] -= int(exam_id in exclusive_exams)
            room_durations[source_key][exam.duration] -= 1
            if room_durations[source_key][exam.duration] <= 0:
                del room_durations[source_key][exam.duration]
            room_load[target_key] += exam.size
            room_exam_count[target_key] += 1
            room_exclusive_count[target_key] += int(exam_id in exclusive_exams)
            room_durations[target_key][exam.duration] += 1
            room_by_exam[exam_id] = target_room
            target_by_unit[unit_id] = target_period
        for unit_id, target_period in target_by_unit.items():
            period_by_unit[unit_id] = target_period
        reset_delta_cache()

    singleton_units = tuple(
        unit_id for unit_id, members in enumerate(unit_members) if len(members) == 1
    )
    acceptance_reserve = min(
        0.065,
        max(0.01, 0.10 * max(0.0, deadline - started)),
    )
    telemetry["acceptance_reserve_seconds"] = acceptance_reserve
    scan_deadline = max(started, deadline - acceptance_reserve)
    accepted_deltas: list[int] = []
    passes = 0
    generated_candidates = 0
    while time.perf_counter() < scan_deadline:
        candidates: list[tuple[int, int, int, int, int]] = []
        penalized_units = [
            unit_id
            for unit_id in singleton_units
            if problem.rooms[room_by_exam[unit_members[unit_id][0]]].penalty > 0
        ]
        for first_unit in penalized_units:
            first_exam = unit_members[first_unit][0]
            first_period = period_by_unit[first_unit]
            rough: list[tuple[int, int]] = []
            for second_unit in singleton_units:
                if (
                    second_unit == first_unit
                    or period_by_unit[second_unit] == first_period
                ):
                    continue
                changes = {
                    first_unit: period_by_unit[second_unit],
                    second_unit: first_period,
                }
                if changes_are_hard_valid(changes):
                    rough.append(
                        (delta_cache.swap_delta(first_unit, second_unit), second_unit)
                    )
            for temporal_delta, second_unit in sorted(rough)[:rank_limit]:
                second_exam = unit_members[second_unit][0]
                first_side = replacement_room_cost(second_exam, first_exam)
                second_side = replacement_room_cost(first_exam, second_exam)
                if first_side is None or second_side is None:
                    continue
                net_delta = temporal_delta + first_side[0] + second_side[0]
                if net_delta < 0:
                    candidates.append(
                        (
                            net_delta,
                            first_unit,
                            second_unit,
                            first_side[1],
                            second_side[1],
                        )
                    )
            if time.perf_counter() >= scan_deadline:
                break
        generated_candidates += len(candidates)
        if not candidates:
            break

        accepted_this_pass = 0
        for _, first_unit, second_unit, _, _ in sorted(candidates):
            if time.perf_counter() >= deadline:
                break
            first_exam = unit_members[first_unit][0]
            second_exam = unit_members[second_unit][0]
            first_period = period_by_unit[first_unit]
            second_period = period_by_unit[second_unit]
            changes = {first_unit: second_period, second_unit: first_period}
            if not changes_are_hard_valid(changes):
                continue
            first_side = replacement_room_cost(second_exam, first_exam)
            second_side = replacement_room_cost(first_exam, second_exam)
            if first_side is None or second_side is None:
                continue
            net_delta = (
                delta_cache.swap_delta(first_unit, second_unit)
                + first_side[0]
                + second_side[0]
            )
            if net_delta >= 0:
                continue
            apply_exchange(
                {
                    first_exam: (second_period, first_side[1]),
                    second_exam: (first_period, second_side[1]),
                }
            )
            accepted_deltas.append(net_delta)
            accepted_this_pass += 1
        passes += 1
        if accepted_this_pass == 0:
            break

    candidate = tuple(
        ITC2007ExamAssignment(
            exam=exam_id,
            period=period_by_unit[unit_by_exam[exam_id]],
            room=room_by_exam[exam_id],
        )
        for exam_id in range(len(problem.exams))
    )
    candidate_validation = validate_itc2007_exam_solution(problem, candidate)
    finished = time.perf_counter()
    telemetry.update(
        {
            "passes": passes,
            "generated_candidates": generated_candidates,
            "elapsed_seconds": max(0.0, finished - started),
        }
    )
    if (
        finished > deadline
        or not candidate_validation.feasible
        or candidate_validation.objective.total >= source_validation.objective.total
    ):
        telemetry["status"] = "deadline" if finished > deadline else "no_improvement"
        return source, source_validation, telemetry
    telemetry.update(
        {
            "accepted_moves": len(accepted_deltas),
            "score_after": candidate_validation.objective.total,
            "accepted": True,
            "status": "accepted",
        }
    )
    return candidate, candidate_validation, telemetry


def _polish_post_incumbent_temporal_swaps(
    problem: ITC2007ExamProblem,
    assignments: Sequence[ITC2007ExamAssignment],
    *,
    deadline: float,
    graph: _PostIncumbentExamGraph | None = None,
) -> tuple[
    tuple[ITC2007ExamAssignment, ...],
    ITC2007ExamValidation,
    dict[str, object],
]:
    """Apply exact negative fixed-room period swaps under one deadline."""

    started = time.perf_counter()
    source = tuple(sorted(assignments, key=lambda row: row.exam))
    source_validation = validate_itc2007_exam_solution(problem, source)
    telemetry: dict[str, object] = {
        "strategy": "exact_fixed_room_temporal_swap",
        "generated_candidates": 0,
        "accepted_moves": 0,
        "score_before": source_validation.objective.total,
        "score_after": source_validation.objective.total,
        "accepted": False,
        "status": "not_run",
        "elapsed_seconds": 0.0,
    }
    if not source_validation.feasible:
        telemetry["status"] = "invalid_source"
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return source, source_validation, telemetry
    if time.perf_counter() >= deadline:
        telemetry["status"] = "deadline"
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return source, source_validation, telemetry

    active_graph = graph or _build_post_incumbent_exam_graph(
        problem,
        deadline=deadline,
    )
    if active_graph is None or time.perf_counter() >= deadline:
        telemetry["status"] = "deadline"
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return source, source_validation, telemetry

    unit_members = active_graph.unit_members
    unit_by_exam = active_graph.unit_by_exam
    row_by_exam = {row.exam: row for row in source}
    period_by_unit = [row_by_exam[members[0]].period for members in unit_members]
    room_by_exam = [row_by_exam[exam_id].room for exam_id in range(len(problem.exams))]
    exclusive_exams = {constraint.exam for constraint in problem.room_constraints}
    room_load: dict[tuple[int, int], int] = defaultdict(int)
    room_exam_count: dict[tuple[int, int], int] = defaultdict(int)
    room_exclusive_count: dict[tuple[int, int], int] = defaultdict(int)
    room_durations: dict[tuple[int, int], Counter[int]] = defaultdict(Counter)
    for row in source:
        key = (row.period, row.room)
        exam = problem.exams[row.exam]
        room_load[key] += exam.size
        room_exam_count[key] += 1
        room_exclusive_count[key] += int(row.exam in exclusive_exams)
        room_durations[key][exam.duration] += 1

    delta_cache = _PeriodPolishDeltaCache(
        problem,
        unit_members,
        active_graph.pair_weights,
    )

    def reset_delta_cache() -> None:
        delta_cache.reset(
            {unit_id: period for unit_id, period in enumerate(period_by_unit)}
        )

    reset_delta_cache()

    def swap_is_hard_valid(first_unit: int, second_unit: int) -> bool:
        first_target = period_by_unit[second_unit]
        second_target = period_by_unit[first_unit]
        changes = {first_unit: first_target, second_unit: second_target}
        for unit_id, target in changes.items():
            if target not in active_graph.unit_domains[unit_id]:
                return False
            if any(
                changes.get(neighbor, period_by_unit[neighbor]) == target
                for neighbor in active_graph.neighbors[unit_id]
            ):
                return False
            if any(
                changes.get(predecessor, period_by_unit[predecessor]) >= target
                for predecessor in active_graph.predecessors[unit_id]
            ):
                return False
            if any(
                changes.get(successor, period_by_unit[successor]) <= target
                for successor in active_graph.successors[unit_id]
            ):
                return False
        return True

    def swap_delta(first_unit: int, second_unit: int) -> int | None:
        changes = {
            first_unit: period_by_unit[second_unit],
            second_unit: period_by_unit[first_unit],
        }
        keys: set[tuple[int, int]] = set()
        for unit_id, target in changes.items():
            for exam_id in unit_members[unit_id]:
                keys.add((period_by_unit[unit_id], room_by_exam[exam_id]))
                keys.add((target, room_by_exam[exam_id]))
        loads = {key: room_load[key] for key in keys}
        counts = {key: room_exam_count[key] for key in keys}
        exclusives = {key: room_exclusive_count[key] for key in keys}
        durations = {key: room_durations[key].copy() for key in keys}
        before_mixed = (
            sum(max(0, len(values) - 1) for values in durations.values())
            * problem.weights.non_mixed_durations
        )
        for unit_id, target in changes.items():
            for exam_id in unit_members[unit_id]:
                room_id = room_by_exam[exam_id]
                exam = problem.exams[exam_id]
                source_key = (period_by_unit[unit_id], room_id)
                target_key = (target, room_id)
                loads[source_key] -= exam.size
                counts[source_key] -= 1
                exclusives[source_key] -= int(exam_id in exclusive_exams)
                durations[source_key][exam.duration] -= 1
                if durations[source_key][exam.duration] <= 0:
                    del durations[source_key][exam.duration]
                loads[target_key] += exam.size
                counts[target_key] += 1
                exclusives[target_key] += int(exam_id in exclusive_exams)
                durations[target_key][exam.duration] += 1
        if any(
            loads[(period_id, room_id)] > problem.rooms[room_id].capacity
            or (
                exclusives[(period_id, room_id)] > 0
                and counts[(period_id, room_id)] > 1
            )
            for period_id, room_id in keys
        ):
            return None
        after_mixed = (
            sum(max(0, len(values) - 1) for values in durations.values())
            * problem.weights.non_mixed_durations
        )
        return int(
            delta_cache.swap_delta(first_unit, second_unit) + after_mixed - before_mixed
        )

    def apply_swap(first_unit: int, second_unit: int) -> None:
        first_period = period_by_unit[first_unit]
        second_period = period_by_unit[second_unit]
        for unit_id, target in (
            (first_unit, second_period),
            (second_unit, first_period),
        ):
            for exam_id in unit_members[unit_id]:
                room_id = room_by_exam[exam_id]
                exam = problem.exams[exam_id]
                source_key = (period_by_unit[unit_id], room_id)
                target_key = (target, room_id)
                room_load[source_key] -= exam.size
                room_exam_count[source_key] -= 1
                room_exclusive_count[source_key] -= int(exam_id in exclusive_exams)
                room_durations[source_key][exam.duration] -= 1
                if room_durations[source_key][exam.duration] <= 0:
                    del room_durations[source_key][exam.duration]
                room_load[target_key] += exam.size
                room_exam_count[target_key] += 1
                room_exclusive_count[target_key] += int(exam_id in exclusive_exams)
                room_durations[target_key][exam.duration] += 1
        period_by_unit[first_unit], period_by_unit[second_unit] = (
            second_period,
            first_period,
        )
        reset_delta_cache()

    generated_candidates = 0
    accepted_deltas: list[int] = []
    acceptance_reserve = min(
        0.10,
        max(0.015, 0.18 * max(0.0, deadline - started)),
    )
    telemetry["acceptance_reserve_seconds"] = acceptance_reserve
    scan_deadline = max(started, deadline - acceptance_reserve)
    while time.perf_counter() < scan_deadline:
        order = sorted(
            range(len(unit_members)),
            key=lambda unit_id: (
                -sum(
                    common_students
                    * _temporal_pair_cost(
                        problem,
                        period_by_unit[unit_id],
                        period_by_unit[neighbor],
                    )
                    for neighbor, common_students in active_graph.pair_weights[
                        unit_id
                    ].items()
                ),
                unit_id,
            ),
        )
        candidates: list[tuple[int, int, int]] = []
        for first_unit in order:
            for second_unit in order:
                if (
                    second_unit <= first_unit
                    or period_by_unit[second_unit] == period_by_unit[first_unit]
                    or not swap_is_hard_valid(first_unit, second_unit)
                ):
                    continue
                delta = swap_delta(first_unit, second_unit)
                if delta is not None and delta < 0:
                    candidates.append((delta, first_unit, second_unit))
            if time.perf_counter() >= scan_deadline:
                break
        generated_candidates += len(candidates)
        if not candidates:
            break

        accepted_this_pass = 0
        for _, first_unit, second_unit in sorted(candidates):
            if time.perf_counter() >= deadline:
                break
            if period_by_unit[second_unit] == period_by_unit[
                first_unit
            ] or not swap_is_hard_valid(first_unit, second_unit):
                continue
            delta = swap_delta(first_unit, second_unit)
            if delta is None or delta >= 0:
                continue
            apply_swap(first_unit, second_unit)
            accepted_deltas.append(delta)
            accepted_this_pass += 1
        if accepted_this_pass == 0:
            break

    candidate = tuple(
        ITC2007ExamAssignment(
            exam=exam_id,
            period=period_by_unit[unit_by_exam[exam_id]],
            room=room_by_exam[exam_id],
        )
        for exam_id in range(len(problem.exams))
    )
    candidate_validation = validate_itc2007_exam_solution(problem, candidate)
    finished = time.perf_counter()
    telemetry.update(
        {
            "generated_candidates": generated_candidates,
            "elapsed_seconds": max(0.0, finished - started),
        }
    )
    if (
        finished > deadline
        or not candidate_validation.feasible
        or candidate_validation.objective.total >= source_validation.objective.total
    ):
        telemetry["status"] = "deadline" if finished > deadline else "no_improvement"
        return source, source_validation, telemetry
    telemetry.update(
        {
            "accepted_moves": len(accepted_deltas),
            "score_after": candidate_validation.objective.total,
            "accepted": True,
            "status": "accepted",
        }
    )
    return candidate, candidate_validation, telemetry


def _polish_post_incumbent_rooms_by_quota(
    problem: ITC2007ExamProblem,
    assignments: Sequence[ITC2007ExamAssignment],
    *,
    deadline: float,
    period_limit: int,
    node_limit: int = 25_000,
) -> tuple[
    tuple[ITC2007ExamAssignment, ...],
    ITC2007ExamValidation,
    dict[str, object],
]:
    """Repack a structural quota of costly period room classes."""

    started = time.perf_counter()
    source = tuple(sorted(assignments, key=lambda row: row.exam))
    source_validation = validate_itc2007_exam_solution(problem, source)
    quota = max(0, int(period_limit))
    telemetry: dict[str, object] = {
        "strategy": "cost_ranked_period_room_repack",
        "period_limit": quota,
        "node_limit": max(1, int(node_limit)),
        "attempted_periods": 0,
        "complete_periods": 0,
        "improved_periods": 0,
        "search_nodes": 0,
        "score_before": source_validation.objective.total,
        "score_after": source_validation.objective.total,
        "accepted": False,
        "status": "not_run",
        "elapsed_seconds": 0.0,
    }
    if not source_validation.feasible:
        telemetry["status"] = "invalid_source"
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return source, source_validation, telemetry
    if time.perf_counter() >= deadline or quota == 0:
        telemetry["status"] = "deadline" if quota else "disabled"
        telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
        return source, source_validation, telemetry

    acceptance_reserve = min(
        0.05,
        max(0.01, 0.18 * max(0.0, deadline - started)),
    )
    telemetry["acceptance_reserve_seconds"] = acceptance_reserve
    search_deadline = max(started, deadline - acceptance_reserve)

    period_exams: dict[int, list[int]] = defaultdict(list)
    room_by_exam = {row.exam: row.room for row in source}
    period_by_exam = {row.exam: row.period for row in source}
    for row in source:
        period_exams[row.period].append(row.exam)
    period_order = sorted(
        period_exams,
        key=lambda period_id: (
            -_room_class_soft_cost(
                problem,
                period_exams[period_id],
                room_by_exam,
            ),
            -len(period_exams[period_id]),
            period_id,
        ),
    )

    improved_periods = 0
    attempted_periods = 0
    complete_periods = 0
    search_nodes = 0
    for period_id in period_order[:quota]:
        if time.perf_counter() >= search_deadline:
            break
        exam_ids = period_exams[period_id]
        incumbent_rooms = {exam_id: room_by_exam[exam_id] for exam_id in exam_ids}
        before = _room_class_soft_cost(problem, exam_ids, incumbent_rooms)
        optimized, nodes, complete = _optimize_exam_class_rooms(
            problem,
            exam_ids,
            incumbent_rooms,
            deadline=search_deadline,
            node_limit=max(1, int(node_limit)),
        )
        attempted_periods += 1
        search_nodes += nodes
        complete_periods += int(complete)
        after = _room_class_soft_cost(problem, exam_ids, optimized)
        if after < before:
            room_by_exam.update(optimized)
            improved_periods += 1

    candidate = tuple(
        ITC2007ExamAssignment(
            exam=exam_id,
            period=period_by_exam[exam_id],
            room=room_by_exam[exam_id],
        )
        for exam_id in range(len(problem.exams))
    )
    candidate_validation = validate_itc2007_exam_solution(problem, candidate)
    finished = time.perf_counter()
    telemetry.update(
        {
            "attempted_periods": attempted_periods,
            "complete_periods": complete_periods,
            "improved_periods": improved_periods,
            "search_nodes": search_nodes,
            "elapsed_seconds": max(0.0, finished - started),
        }
    )
    if (
        finished > deadline
        or not candidate_validation.feasible
        or candidate_validation.objective.total >= source_validation.objective.total
    ):
        telemetry["status"] = "deadline" if finished > deadline else "no_improvement"
        return source, source_validation, telemetry
    telemetry.update(
        {
            "score_after": candidate_validation.objective.total,
            "accepted": True,
            "status": "accepted",
        }
    )
    return candidate, candidate_validation, telemetry


_POST_INCUMBENT_PORTFOLIO_STAGE_FRACTIONS = (
    0.15,
    0.20,
    0.38,
    0.45,
    0.57,
    0.81,
    0.89,
    0.99,
)

_POST_INCUMBENT_PORTFOLIO_STAGE_TAXONOMY = {
    "singleton_room_exchange_1": (
        "cross_period_singleton_interchange",
        "penalized_room_first_exact_delta_ranking",
        "early_room_basin_escape",
    ),
    "room_quota_1": (
        "fixed_period_room_reassignment",
        "highest_room_cost_first_fixed_quota",
        "early_room_cost_normalization",
    ),
    "negative_temporal_1": (
        "negative_delta_period_neighborhood",
        "bounded_negative_temporal_sweep",
        "early_temporal_descent",
    ),
    "temporal_swap_1": (
        "cross_period_interchange",
        "exact_fixed_room_negative_delta_ranking",
        "mid_portfolio_temporal_escape",
    ),
    "singleton_room_exchange_2": (
        "cross_period_singleton_interchange",
        "penalized_room_first_exact_delta_ranking",
        "post_descent_room_basin_escape",
    ),
    "period_room_neighborhood_2": (
        "coupled_period_room_neighborhood",
        "room_shadow_priced_bounded_search",
        "deep_coupled_descent",
    ),
    "room_quota_2": (
        "fixed_period_room_reassignment",
        "highest_room_cost_first_full_period_quota",
        "late_room_cost_normalization",
    ),
    "temporal_swap_2": (
        "cross_period_interchange",
        "exact_fixed_room_negative_delta_ranking",
        "final_temporal_closure",
    ),
}


def polish_itc2007_exam_post_incumbent(
    problem: ITC2007ExamProblem,
    assignments: Sequence[ITC2007ExamAssignment],
    *,
    deadline: float,
) -> tuple[
    tuple[ITC2007ExamAssignment, ...],
    ITC2007ExamValidation,
    dict[str, object],
]:
    """Run a bounded strict-improvement portfolio on a supplied incumbent.

    ``deadline`` is one absolute ``time.perf_counter()`` deadline shared by
    every stage. This API does not construct an incumbent and therefore must
    not be described as an end-to-end solve budget.
    """

    started = time.perf_counter()
    caller_snapshot = tuple(assignments)
    source = tuple(sorted(caller_snapshot, key=lambda row: row.exam))
    source_validation = validate_itc2007_exam_solution(problem, source)
    if not source_validation.feasible:
        raise ValueError("assignments must be complete and hard-feasible")

    available = max(0.0, float(deadline) - started)
    final_validation_reserve = min(0.05, max(0.005, 0.01 * available))
    final_stage_deadline = max(started, float(deadline) - final_validation_reserve)
    telemetry: dict[str, object] = {
        "strategy": "bounded_post_incumbent_exam_portfolio",
        "deadline_policy": "one_absolute_deadline",
        "mutation_policy": "immutable_handoffs",
        "stage_deadline_fractions": _POST_INCUMBENT_PORTFOLIO_STAGE_FRACTIONS,
        "final_validation_reserve_seconds": final_validation_reserve,
        "score_before": source_validation.objective.total,
        "score_after": source_validation.objective.total,
        "accepted_stages": 0,
        "accepted": False,
        "status": "not_run",
        "fail_closed": False,
        "graph_build_seconds": 0.0,
        "stages": [],
        "elapsed_seconds": 0.0,
        "deadline_overrun_seconds": 0.0,
    }
    if time.perf_counter() >= final_stage_deadline:
        finished = time.perf_counter()
        telemetry.update(
            {
                "status": "deadline",
                "fail_closed": True,
                "elapsed_seconds": max(0.0, finished - started),
                "deadline_overrun_seconds": max(0.0, finished - float(deadline)),
            }
        )
        return source, source_validation, telemetry

    def stage_deadline(fraction: float) -> float:
        return min(
            final_stage_deadline,
            started + available * fraction,
        )

    graph_started = time.perf_counter()
    graph = _build_post_incumbent_exam_graph(
        problem,
        deadline=stage_deadline(_POST_INCUMBENT_PORTFOLIO_STAGE_FRACTIONS[0]),
    )
    telemetry["graph_build_seconds"] = max(
        0.0,
        time.perf_counter() - graph_started,
    )
    if graph is None:
        finished = time.perf_counter()
        telemetry.update(
            {
                "status": "graph_unavailable",
                "fail_closed": True,
                "elapsed_seconds": max(0.0, finished - started),
                "deadline_overrun_seconds": max(0.0, finished - float(deadline)),
            }
        )
        return source, source_validation, telemetry

    incumbent = source
    incumbent_validation = source_validation
    stage_records: list[dict[str, object]] = []

    StageOperator = Callable[
        [tuple[ITC2007ExamAssignment, ...], float],
        tuple[
            tuple[ITC2007ExamAssignment, ...],
            ITC2007ExamValidation,
            dict[str, object],
        ],
    ]

    def handoff(
        name: str,
        fraction: float,
        operation: StageOperator,
    ) -> None:
        nonlocal incumbent, incumbent_validation
        cutoff = stage_deadline(fraction)
        stage_started = time.perf_counter()
        before_rows = incumbent
        before_validation = incumbent_validation
        operator_family, selection_policy, orchestration_role = (
            _POST_INCUMBENT_PORTFOLIO_STAGE_TAXONOMY[name]
        )
        record: dict[str, object] = {
            "stage": name,
            "deadline_fraction": fraction,
            "operator_origin": "established_exam_timetabling",
            "established_operator_family": operator_family,
            "selection_origin": "planora",
            "planora_selection_policy": selection_policy,
            "orchestration_origin": "planora",
            "planora_orchestration_role": orchestration_role,
            "score_before": before_validation.objective.total,
            "score_after": before_validation.objective.total,
            "accepted": False,
            "status": "deadline",
            "operator": {},
        }
        if stage_started >= cutoff:
            record["elapsed_seconds"] = 0.0
            record["cumulative_elapsed_seconds"] = max(0.0, stage_started - started)
            stage_records.append(record)
            return
        try:
            candidate_rows, reported_validation, operator_telemetry = operation(
                before_rows,
                cutoff,
            )
            candidate = tuple(candidate_rows)
            candidate_validation = validate_itc2007_exam_solution(problem, candidate)
            checked_at = time.perf_counter()
            record["operator"] = dict(operator_telemetry)
            if checked_at > cutoff:
                record["status"] = "late_candidate"
            elif reported_validation != candidate_validation:
                record["status"] = "inconsistent_validation"
            elif not candidate_validation.feasible:
                record["status"] = "invalid_candidate"
            elif (
                candidate_validation.objective.total
                >= before_validation.objective.total
            ):
                record["status"] = "no_improvement"
            else:
                incumbent = candidate
                incumbent_validation = candidate_validation
                record.update(
                    {
                        "score_after": candidate_validation.objective.total,
                        "accepted": True,
                        "status": "accepted",
                    }
                )
        except Exception as exc:  # Portfolio stages are optional and fail closed.
            checked_at = time.perf_counter()
            record.update(
                {
                    "status": "operator_error",
                    "error_type": type(exc).__name__,
                }
            )
        if incumbent is not before_rows and not bool(record["accepted"]):
            incumbent = before_rows
            incumbent_validation = before_validation
        record["elapsed_seconds"] = max(0.0, checked_at - stage_started)
        record["cumulative_elapsed_seconds"] = max(0.0, checked_at - started)
        stage_records.append(record)

    handoff(
        "singleton_room_exchange_1",
        _POST_INCUMBENT_PORTFOLIO_STAGE_FRACTIONS[0],
        lambda rows, cutoff: _polish_post_incumbent_singleton_room_exchanges(
            problem,
            rows,
            deadline=cutoff,
            graph=graph,
            rank_limit=64,
        ),
    )
    handoff(
        "room_quota_1",
        _POST_INCUMBENT_PORTFOLIO_STAGE_FRACTIONS[1],
        lambda rows, cutoff: _polish_post_incumbent_rooms_by_quota(
            problem,
            rows,
            deadline=cutoff,
            period_limit=4,
            node_limit=25_000,
        ),
    )
    handoff(
        "negative_temporal_1",
        _POST_INCUMBENT_PORTFOLIO_STAGE_FRACTIONS[2],
        lambda rows, cutoff: _polish_exam_periods(
            problem,
            rows,
            deadline=cutoff,
            max_rounds=5,
            max_exchange_candidates=0,
            max_exchange_evaluations=0,
        ),
    )
    handoff(
        "temporal_swap_1",
        _POST_INCUMBENT_PORTFOLIO_STAGE_FRACTIONS[3],
        lambda rows, cutoff: _polish_post_incumbent_temporal_swaps(
            problem,
            rows,
            deadline=cutoff,
            graph=graph,
        ),
    )
    handoff(
        "singleton_room_exchange_2",
        _POST_INCUMBENT_PORTFOLIO_STAGE_FRACTIONS[4],
        lambda rows, cutoff: _polish_post_incumbent_singleton_room_exchanges(
            problem,
            rows,
            deadline=cutoff,
            graph=graph,
            rank_limit=64,
        ),
    )
    handoff(
        "period_room_neighborhood_2",
        _POST_INCUMBENT_PORTFOLIO_STAGE_FRACTIONS[5],
        lambda rows, cutoff: _polish_exam_periods(
            problem,
            rows,
            deadline=cutoff,
            max_rounds=20,
            max_exchange_candidates=128,
            max_exchange_evaluations=18,
        ),
    )
    handoff(
        "room_quota_2",
        _POST_INCUMBENT_PORTFOLIO_STAGE_FRACTIONS[6],
        lambda rows, cutoff: _polish_post_incumbent_rooms_by_quota(
            problem,
            rows,
            deadline=cutoff,
            period_limit=len(problem.periods),
            node_limit=25_000,
        ),
    )
    handoff(
        "temporal_swap_2",
        _POST_INCUMBENT_PORTFOLIO_STAGE_FRACTIONS[7],
        lambda rows, cutoff: _polish_post_incumbent_temporal_swaps(
            problem,
            rows,
            deadline=cutoff,
            graph=graph,
        ),
    )

    final_validation = validate_itc2007_exam_solution(problem, incumbent)
    finished = time.perf_counter()
    within_deadline = finished <= float(deadline)
    final_is_valid = bool(
        final_validation.feasible
        and final_validation.objective.total <= source_validation.objective.total
    )
    rejected_unsafe_stage = any(
        record["status"]
        in {
            "late_candidate",
            "inconsistent_validation",
            "invalid_candidate",
            "operator_error",
        }
        for record in stage_records
    )
    if not within_deadline or not final_is_valid:
        incumbent = source
        final_validation = source_validation
        status = "deadline_rollback" if not within_deadline else "invalid_rollback"
        fail_closed = True
    else:
        accepted_stages = sum(bool(record["accepted"]) for record in stage_records)
        status = "improved" if accepted_stages else "no_improvement"
        fail_closed = rejected_unsafe_stage
    accepted_stages = sum(bool(record["accepted"]) for record in stage_records)
    telemetry.update(
        {
            "stages": stage_records,
            "score_after": final_validation.objective.total,
            "accepted_stages": accepted_stages if incumbent != source else 0,
            "accepted": incumbent != source,
            "status": status,
            "fail_closed": fail_closed,
            "elapsed_seconds": max(0.0, finished - started),
            "deadline_overrun_seconds": max(0.0, finished - float(deadline)),
        }
    )
    return incumbent, final_validation, telemetry


def _construct_itc2007_exam_incumbent(
    problem: ITC2007ExamProblem,
    *,
    eligible_periods: dict[int, tuple[int, ...]],
    deadline: float,
    seed: int,
    max_ejection_depth: int = 2,
) -> _ExamConstructiveResult | None:
    """Build a complete hard-feasible incumbent with bounded ejection repair.

    Active coincidence relations are contracted before coloring.  The
    resulting conflict/precedence graph is colored into periods while each
    accepted color class is immediately checked by the exact bounded room
    packer.  A failed insertion may eject one blocking color unit and reinsert
    it recursively, giving a deterministic short ejection chain without ever
    exposing a partially feasible solution.
    """

    started = time.perf_counter()
    exam_count = len(problem.exams)
    parent = list(range(exam_count))

    def find(exam_id: int) -> int:
        while parent[exam_id] != exam_id:
            parent[exam_id] = parent[parent[exam_id]]
            exam_id = parent[exam_id]
        return exam_id

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        if first_root > second_root:
            first_root, second_root = second_root, first_root
        parent[second_root] = first_root

    shared_counts = problem.shared_student_counts
    for constraint in problem.period_constraints:
        if constraint.kind == "EXAM_COINCIDENCE" and _coincidence_is_active(
            constraint, shared_counts
        ):
            union(constraint.first_exam, constraint.second_exam)

    grouped: dict[int, list[int]] = defaultdict(list)
    for exam_id in range(exam_count):
        grouped[find(exam_id)].append(exam_id)
    unit_members = tuple(
        tuple(members)
        for _, members in sorted(grouped.items(), key=lambda item: min(item[1]))
    )
    unit_by_exam = {
        exam_id: unit_id
        for unit_id, members in enumerate(unit_members)
        for exam_id in members
    }
    unit_count = len(unit_members)
    unit_domains: list[tuple[int, ...]] = []
    for members in unit_members:
        common = set(eligible_periods[members[0]])
        for exam_id in members[1:]:
            common.intersection_update(eligible_periods[exam_id])
        if not common:
            return None
        unit_domains.append(tuple(sorted(common)))

    neighbors: list[set[int]] = [set() for _ in range(unit_count)]
    pair_weights: list[dict[int, int]] = [defaultdict(int) for _ in range(unit_count)]
    for (left, right), common_students in shared_counts.items():
        if common_students <= 0:
            continue
        first_unit = unit_by_exam[left]
        second_unit = unit_by_exam[right]
        if first_unit == second_unit:
            return None
        neighbors[first_unit].add(second_unit)
        neighbors[second_unit].add(first_unit)
        pair_weights[first_unit][second_unit] += common_students
        pair_weights[second_unit][first_unit] += common_students

    predecessors: list[set[int]] = [set() for _ in range(unit_count)]
    successors: list[set[int]] = [set() for _ in range(unit_count)]
    for constraint in problem.period_constraints:
        if not _coincidence_is_active(constraint, shared_counts):
            continue
        first_unit = unit_by_exam[constraint.first_exam]
        second_unit = unit_by_exam[constraint.second_exam]
        if constraint.kind == "EXAM_COINCIDENCE":
            continue
        if first_unit == second_unit:
            return None
        neighbors[first_unit].add(second_unit)
        neighbors[second_unit].add(first_unit)
        if constraint.kind == "AFTER":
            predecessors[first_unit].add(second_unit)
            successors[second_unit].add(first_unit)

    indegree = [len(predecessors[unit_id]) for unit_id in range(unit_count)]
    frontier = sorted(unit_id for unit_id, degree in enumerate(indegree) if degree == 0)
    topological: list[int] = []
    while frontier:
        unit_id = frontier.pop(0)
        topological.append(unit_id)
        for successor in sorted(successors[unit_id]):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                frontier.append(successor)
        frontier.sort()
    if len(topological) != unit_count:
        return None
    earliest = [0] * unit_count
    for unit_id in topological:
        if predecessors[unit_id]:
            earliest[unit_id] = max(
                earliest[parent_unit] + 1 for parent_unit in predecessors[unit_id]
            )
    latest = [len(problem.periods) - 1] * unit_count
    for unit_id in reversed(topological):
        if successors[unit_id]:
            latest[unit_id] = min(
                latest[child_unit] - 1 for child_unit in successors[unit_id]
            )
        if earliest[unit_id] > latest[unit_id]:
            return None

    largest = set(
        sorted(
            range(exam_count),
            key=lambda exam_id: (-problem.exams[exam_id].size, exam_id),
        )[: problem.weights.frontload_largest_exams]
    )
    frontload_threshold = max(
        0, len(problem.periods) - problem.weights.frontload_last_periods
    )
    unit_load = [
        sum(problem.exams[exam_id].size for exam_id in members)
        for members in unit_members
    ]
    room_capacity = max(1, sum(room.capacity for room in problem.rooms))
    assignment: dict[int, int] = {}
    period_units: list[set[int]] = [set() for _ in problem.periods]
    period_rooms: list[dict[int, int]] = [dict() for _ in problem.periods]
    period_load = [0] * len(problem.periods)
    period_room_soft = [0] * len(problem.periods)
    telemetry: dict[str, object] = {
        "units": unit_count,
        "coincidence_contractions": exam_count - unit_count,
        "room_pack_attempts": 0,
        "room_backtrack_nodes": 0,
        "ejection_attempts": 0,
        "ejection_successes": 0,
        "max_ejection_depth": int(max_ejection_depth),
    }

    def unit_tie(unit_id: int) -> int:
        return int(
            ((unit_id + 1) * 2_654_435_761 ^ (int(seed) + 1) * 1_103_515_245)
            & 0xFFFF_FFFF
        )

    def period_tie(unit_id: int, period_id: int) -> int:
        return int(
            ((period_id + 1) * 1_103_515_245 ^ (unit_id + int(seed) + 1) * 12_345)
            & 0xFFFF
        )

    def assigned_periods_valid(unit_id: int, period_id: int) -> bool:
        if not earliest[unit_id] <= period_id <= latest[unit_id]:
            return False
        if any(
            assignment.get(neighbor) == period_id for neighbor in neighbors[unit_id]
        ):
            return False
        if any(
            predecessor in assignment and assignment[predecessor] >= period_id
            for predecessor in predecessors[unit_id]
        ):
            return False
        return not any(
            successor in assignment and assignment[successor] <= period_id
            for successor in successors[unit_id]
        )

    def quick_period_cost(unit_id: int, period_id: int) -> tuple[int, int, int]:
        temporal = sum(
            common_students
            * _temporal_pair_cost(problem, period_id, assignment[neighbor])
            for neighbor, common_students in pair_weights[unit_id].items()
            if neighbor in assignment
        )
        unary = 0
        for exam_id in unit_members[unit_id]:
            unary += problem.periods[period_id].penalty
            if exam_id in largest and period_id >= frontload_threshold:
                unary += problem.weights.frontload_penalty
        old_load = period_load[period_id]
        new_load = old_load + unit_load[unit_id]
        load_pressure = (new_load * new_load - old_load * old_load) // room_capacity
        return (
            int(temporal + unary + load_pressure),
            int(temporal + unary),
            period_tie(unit_id, period_id),
        )

    def remove_unit(unit_id: int) -> None:
        period_id = assignment.pop(unit_id)
        period_units[period_id].remove(unit_id)
        for exam_id in unit_members[unit_id]:
            period_rooms[period_id].pop(exam_id, None)
        period_load[period_id] -= unit_load[unit_id]
        exam_ids = [
            exam_id
            for resident in period_units[period_id]
            for exam_id in unit_members[resident]
        ]
        period_room_soft[period_id] = _room_class_soft_cost(
            problem, exam_ids, period_rooms[period_id]
        )

    def commit_unit(
        unit_id: int,
        period_id: int,
        packed_rooms: dict[int, int],
    ) -> None:
        assignment[unit_id] = period_id
        period_units[period_id].add(unit_id)
        period_rooms[period_id] = packed_rooms
        period_load[period_id] += unit_load[unit_id]
        exam_ids = [
            exam_id
            for resident in period_units[period_id]
            for exam_id in unit_members[resident]
        ]
        period_room_soft[period_id] = _room_class_soft_cost(
            problem, exam_ids, packed_rooms
        )

    def try_pack(unit_id: int, period_id: int) -> dict[int, int] | None:
        exam_ids = [
            exam_id
            for resident in period_units[period_id]
            for exam_id in unit_members[resident]
        ]
        exam_ids.extend(unit_members[unit_id])
        if sum(problem.exams[exam_id].size for exam_id in exam_ids) > room_capacity:
            return None
        telemetry["room_pack_attempts"] = int(telemetry["room_pack_attempts"]) + 1
        packed, nodes = _pack_exam_class_rooms(
            problem,
            exam_ids,
            deadline=deadline,
            node_limit=4_000,
        )
        telemetry["room_backtrack_nodes"] = (
            int(telemetry["room_backtrack_nodes"]) + nodes
        )
        return packed

    def restore_state(
        snapshot_assignment: dict[int, int],
        snapshot_units: list[set[int]],
        snapshot_rooms: list[dict[int, int]],
        snapshot_load: list[int],
        snapshot_soft: list[int],
    ) -> None:
        assignment.clear()
        assignment.update(snapshot_assignment)
        for period_id in range(len(problem.periods)):
            period_units[period_id] = set(snapshot_units[period_id])
            period_rooms[period_id] = dict(snapshot_rooms[period_id])
            period_load[period_id] = snapshot_load[period_id]
            period_room_soft[period_id] = snapshot_soft[period_id]

    def place_unit(
        unit_id: int,
        *,
        depth: int,
        avoid_periods: frozenset[int] = frozenset(),
        trail: frozenset[int] = frozenset(),
    ) -> bool:
        if time.perf_counter() >= deadline or unit_id in trail:
            return False
        direct_periods = [
            period_id
            for period_id in unit_domains[unit_id]
            if period_id not in avoid_periods
            and assigned_periods_valid(unit_id, period_id)
        ]
        direct_periods.sort(key=lambda period_id: quick_period_cost(unit_id, period_id))
        for period_id in direct_periods:
            packed = try_pack(unit_id, period_id)
            if packed is not None:
                commit_unit(unit_id, period_id, packed)
                return True
            if time.perf_counter() >= deadline:
                return False
        if depth <= 0:
            return False

        repair_periods = [
            period_id
            for period_id in unit_domains[unit_id]
            if period_id not in avoid_periods
            and earliest[unit_id] <= period_id <= latest[unit_id]
        ]
        repair_periods.sort(key=lambda period_id: quick_period_cost(unit_id, period_id))
        for period_id in repair_periods[:12]:
            conflict_blockers = sorted(
                neighbor
                for neighbor in neighbors[unit_id]
                if assignment.get(neighbor) == period_id
            )
            if len(conflict_blockers) > 1:
                continue
            if conflict_blockers:
                candidates = conflict_blockers
            else:
                candidates = sorted(
                    period_units[period_id],
                    key=lambda resident: (-unit_load[resident], unit_tie(resident)),
                )[:4]
            for ejected in candidates:
                if ejected in trail:
                    continue
                telemetry["ejection_attempts"] = int(telemetry["ejection_attempts"]) + 1
                snapshot = (
                    dict(assignment),
                    [set(units) for units in period_units],
                    [dict(rooms) for rooms in period_rooms],
                    list(period_load),
                    list(period_room_soft),
                )
                remove_unit(ejected)
                if not assigned_periods_valid(unit_id, period_id):
                    restore_state(*snapshot)
                    continue
                packed = try_pack(unit_id, period_id)
                if packed is None:
                    restore_state(*snapshot)
                    continue
                commit_unit(unit_id, period_id, packed)
                if place_unit(
                    ejected,
                    depth=depth - 1,
                    avoid_periods=frozenset({period_id}),
                    trail=trail | {unit_id},
                ):
                    telemetry["ejection_successes"] = (
                        int(telemetry["ejection_successes"]) + 1
                    )
                    return True
                restore_state(*snapshot)
                if time.perf_counter() >= deadline:
                    return False
        return False

    while len(assignment) < unit_count:
        if time.perf_counter() >= deadline:
            return None
        unassigned = [
            unit_id for unit_id in range(unit_count) if unit_id not in assignment
        ]
        unit_id = max(
            unassigned,
            key=lambda candidate: (
                len(
                    {
                        assignment[neighbor]
                        for neighbor in neighbors[candidate]
                        if neighbor in assignment
                    }
                ),
                -len(unit_domains[candidate]),
                len(neighbors[candidate]),
                len(predecessors[candidate]) + len(successors[candidate]),
                unit_load[candidate],
                -unit_tie(candidate),
            ),
        )
        if not place_unit(unit_id, depth=max(0, int(max_ejection_depth))):
            return None

    assignments = tuple(
        ITC2007ExamAssignment(
            exam=exam_id,
            period=assignment[unit_by_exam[exam_id]],
            room=period_rooms[assignment[unit_by_exam[exam_id]]][exam_id],
        )
        for exam_id in range(exam_count)
    )
    validation = validate_itc2007_exam_solution(problem, assignments)
    if not validation.feasible:
        return None
    # The room search owns only the remaining constructive-search slice.  Keep
    # a separate tail for its mandatory full independent validation and the
    # caller's already-reserved final acceptance work.
    polish_validation_reserve = min(
        0.05,
        max(0.005, 0.05 * max(0.0, deadline - started)),
    )
    polish_finished_by = deadline - polish_validation_reserve
    polish_started = time.perf_counter()
    polish_available = max(0.0, polish_finished_by - polish_started)
    # Give the broad room closure and the atomic period LNS explicit shares,
    # then let the deeper per-period room B&B use only the middle remainder.
    # This prevents either established neighborhood from starving behind a few
    # expensive room color classes while remaining scale-neutral.
    room_closure_reserve = min(0.08, 0.20 * polish_available)
    period_lns_reserve = min(0.28, 0.55 * polish_available)
    room_polish_budget = max(0.0, polish_available - period_lns_reserve)
    room_bnb_budget = max(0.0, room_polish_budget - room_closure_reserve)
    room_polish_deadline = min(
        polish_finished_by,
        polish_started + room_polish_budget,
    )
    assignments, validation, room_polish = _polish_fixed_period_rooms(
        problem,
        assignments,
        deadline=room_polish_deadline,
        closure_budget_seconds=room_closure_reserve,
    )
    room_polish["validation_reserve_seconds"] = polish_validation_reserve
    telemetry["room_polish"] = room_polish
    tail_available = max(0.0, polish_finished_by - time.perf_counter())
    pressure_block_reserve = min(
        1.45,
        max(0.0, tail_available - 0.65),
    )
    period_polish_deadline = max(
        time.perf_counter(),
        polish_finished_by - pressure_block_reserve,
    )
    assignments, validation, period_polish = _polish_exam_periods(
        problem,
        assignments,
        deadline=period_polish_deadline,
        # The absolute deadline and the polish acceptance reserve remain the
        # real stop conditions. Public set1 evidence showed that the former
        # six-round cap could stop after six consecutive strict gains while
        # more than a second of the allocated constructive window remained.
        max_rounds=20,
    )
    period_polish["validation_reserve_seconds"] = polish_validation_reserve
    telemetry["period_polish"] = period_polish
    assignments, validation, pressure_block_polish = _polish_exam_pressure_blocks(
        problem,
        assignments,
        deadline=polish_finished_by,
        seed=seed,
        workers=1,
    )
    pressure_block_polish["validation_reserve_seconds"] = polish_validation_reserve
    telemetry["pressure_block_polish"] = pressure_block_polish
    telemetry["polish_budget"] = {
        "available_seconds": polish_available,
        "room_closure_reserve_seconds": room_closure_reserve,
        "room_bnb_budget_seconds": room_bnb_budget,
        "room_polish_budget_seconds": room_polish_budget,
        "period_lns_reserve_seconds": period_lns_reserve,
        "pressure_block_reserve_seconds": pressure_block_reserve,
        "validation_reserve_seconds": polish_validation_reserve,
    }
    telemetry["elapsed_seconds"] = max(0.0, time.perf_counter() - started)
    telemetry["objective"] = validation.objective.total
    return _ExamConstructiveResult(
        assignments=assignments,
        validation=validation,
        telemetry=telemetry,
    )


def _projected_acceptance_is_timely(
    finished_at: float,
    *,
    deadline: float,
    final_acceptance_reserve_seconds: float,
) -> bool:
    """Keep final validation/serialization inside the caller's hard deadline."""

    return float(finished_at) < (
        float(deadline) - max(0.0, float(final_acceptance_reserve_seconds))
    )


# Deliberately optimistic relative to source-stable local build probes: the
# gate skips only when even this faster, representation-only estimate cannot
# preserve the calibrated search slice.  No corpus or instance identifier is
# part of the decision.
_PROJECTED_BUILD_ADMISSION_UNITS_PER_SECOND = 600_000.0
_PROJECTED_BUILD_FIXED_SECONDS = 0.02


def _estimate_projected_exam_build(
    problem: ITC2007ExamProblem,
    eligible_periods: dict[int, tuple[int, ...]],
) -> dict[str, int]:
    """Count representation work before allocating the projected CP model.

    The estimate counts period literals, temporal relation objects, and literal
    references copied into Hall inequalities.  It intentionally excludes CP-SAT
    search: the admission gate asks only whether the calibrated minimum search
    slice can still exist after Python model construction.
    """

    period_count = len(problem.periods)
    period_literals = sum(len(values) for values in eligible_periods.values())
    shared_pairs = sum(
        1
        for common_students in problem.shared_student_counts.values()
        if common_students > 0
    )
    needs_temporal_cost = bool(
        problem.weights.two_in_a_row
        or problem.weights.two_in_a_day
        or problem.weights.period_spread
    )
    temporal_relation_units = shared_pairs
    if needs_temporal_cost and period_count > 1:
        # Conflict plus distance/same-day encodings and their reifications.
        temporal_relation_units += 4 * shared_pairs
        if problem.weights.two_in_a_row != problem.weights.two_in_a_day:
            temporal_relation_units += 4 * shared_pairs
        if problem.weights.period_spread > 0:
            temporal_relation_units += 3 * shared_pairs

    room_capacities = sorted(room.capacity for room in problem.rooms)
    thresholds = (0, *sorted(set(room_capacities))[:-1])
    hall_capacity_term_references = 0
    for threshold in thresholds:
        hall_capacity_term_references += sum(
            len(eligible_periods[exam_id])
            for exam_id, exam in enumerate(problem.exams)
            if exam.size > threshold
        )

    hall_cardinality_term_references = 0
    seen_slot_profiles: set[tuple[int, ...]] = set()
    for minimum_size in sorted({exam.size for exam in problem.exams}):
        if minimum_size <= 0:
            continue
        slot_profile = tuple(capacity // minimum_size for capacity in room_capacities)
        if slot_profile in seen_slot_profiles:
            continue
        seen_slot_profiles.add(slot_profile)
        available_slots = sum(slot_profile)
        members = [
            exam_id
            for exam_id, exam in enumerate(problem.exams)
            if exam.size >= minimum_size
        ]
        if available_slots >= len(members):
            continue
        # The builder materializes the per-period term list before deciding
        # whether its cardinality exceeds available_slots, so every eligible
        # literal is real Python representation work even when no cut is added.
        hall_cardinality_term_references += sum(
            len(eligible_periods[exam_id]) for exam_id in members
        )

    exclusive = {constraint.exam for constraint in problem.room_constraints}
    exclusive_term_references = sum(
        len(eligible_periods[exam_id]) for exam_id in exclusive
    )
    work_units = int(
        period_literals
        + temporal_relation_units
        + hall_capacity_term_references
        + hall_cardinality_term_references
        + exclusive_term_references
    )
    return {
        "period_literals": int(period_literals),
        "shared_pairs": int(shared_pairs),
        "temporal_relation_units": int(temporal_relation_units),
        "hall_capacity_term_references": int(hall_capacity_term_references),
        "hall_cardinality_term_references": int(hall_cardinality_term_references),
        "exclusive_term_references": int(exclusive_term_references),
        "work_units": work_units,
    }


def _projected_exam_prebuild_admission(
    work_units: int,
    *,
    build_window_seconds: float,
    units_per_second: float = _PROJECTED_BUILD_ADMISSION_UNITS_PER_SECOND,
    fixed_seconds: float = _PROJECTED_BUILD_FIXED_SECONDS,
) -> dict[str, float | bool | int]:
    """Admit projected construction only when its optimistic estimate fits."""

    if units_per_second <= 0:
        raise ValueError("units_per_second must be positive")
    estimated_seconds = max(0.0, float(fixed_seconds)) + max(
        0, int(work_units)
    ) / float(units_per_second)
    available_seconds = max(0.0, float(build_window_seconds))
    return {
        "admitted": bool(estimated_seconds <= available_seconds),
        "work_units": max(0, int(work_units)),
        "build_window_seconds": available_seconds,
        "estimated_build_seconds": estimated_seconds,
        "admission_units_per_second": float(units_per_second),
        "fixed_seconds": max(0.0, float(fixed_seconds)),
    }


def _solve_projected_itc2007_exam(
    problem: ITC2007ExamProblem,
    *,
    started: float,
    deadline: float,
    eligible_periods: dict[int, tuple[int, ...]],
    scale: dict[str, object],
    seed: int,
    workers: int,
    solve_reserve_seconds: float,
) -> ITC2007ExamSolveResult:
    """Solve periods exactly, then lift independent period color classes.

    This projection removes the room Cartesian product from the expensive
    temporal search.  Nested Hall-capacity inequalities preserve the strongest
    cheap room-feasibility conditions.  The projected objective still models
    every student temporal component exactly by combining absolute period
    distance with reified same-day and adjacent-day relations.
    """

    total_budget = max(0.0, deadline - started)
    final_acceptance_reserve = max(
        max(0.0, float(solve_reserve_seconds)),
        min(0.5, max(0.05, 0.08 * total_budget)),
    )
    room_lift_reserve = min(1.0, max(0.05, 0.10 * total_budget))
    minimum_projected_search = min(1.5, max(0.25, 0.20 * total_budget))
    acceptance_deadline = deadline - final_acceptance_reserve
    constructive_budget = min(1.6, max(0.05, 0.30 * total_budget))
    build_estimate = _estimate_projected_exam_build(problem, eligible_periods)
    constructive_started_at = time.perf_counter()
    nominal_constructive_deadline = min(
        acceptance_deadline - room_lift_reserve - minimum_projected_search,
        constructive_started_at + constructive_budget,
    )
    nominal_projected_build_window = max(
        0.0,
        acceptance_deadline
        - room_lift_reserve
        - minimum_projected_search
        - nominal_constructive_deadline,
    )
    prebuild_admission = _projected_exam_prebuild_admission(
        build_estimate["work_units"],
        build_window_seconds=nominal_projected_build_window,
    )
    prebuild_skip = not bool(prebuild_admission["admitted"])
    coupled_lns_reserve = (
        min(
            max(0.0, acceptance_deadline - constructive_started_at - 5.0),
            max(20.0, 0.75 * total_budget),
        )
        if prebuild_skip and total_budget >= 30.0
        else 0.0
    )
    constructive_deadline = (
        acceptance_deadline - coupled_lns_reserve
        if prebuild_skip
        else nominal_constructive_deadline
    )
    deadline_policy: dict[str, object] = {
        "total_budget_seconds": total_budget,
        "constructive_budget_seconds": constructive_budget,
        "constructive_allocated_seconds": max(
            0.0, constructive_deadline - constructive_started_at
        ),
        "constructive_lane_extended": prebuild_skip,
        "coupled_lns_reserve_seconds": coupled_lns_reserve,
        "final_acceptance_reserve_seconds": final_acceptance_reserve,
        "room_lift_reserve_seconds": room_lift_reserve,
        "minimum_projected_search_seconds": minimum_projected_search,
        "nominal_projected_build_window_seconds": nominal_projected_build_window,
        "projected_build_estimate": build_estimate,
        "projected_prebuild_admission": prebuild_admission,
        "projected_search_seconds": 0.0,
        "projected_skipped_reason": (
            "representation_prebuild_gate" if prebuild_skip else None
        ),
    }
    incumbent = _construct_itc2007_exam_incumbent(
        problem,
        eligible_periods=eligible_periods,
        deadline=constructive_deadline,
        seed=seed,
    )
    if prebuild_skip:
        coupled_lns: dict[str, object] | None = None
        if (
            incumbent is not None
            and coupled_lns_reserve > 0
            and time.perf_counter() < acceptance_deadline
        ):
            optimized, optimized_validation, coupled_lns = (
                _optimize_exam_period_room_neighborhood(
                    problem,
                    incumbent.assignments,
                    deadline=acceptance_deadline,
                    seed=seed,
                    period_radius=3,
                    workers=workers,
                )
            )
            constructive_telemetry = dict(incumbent.telemetry)
            constructive_telemetry["coupled_lns"] = coupled_lns
            constructive_telemetry["objective"] = optimized_validation.objective.total
            incumbent = _ExamConstructiveResult(
                assignments=optimized,
                validation=optimized_validation,
                telemetry=constructive_telemetry,
            )
        build_finished = time.perf_counter()
        if incumbent is not None:
            return _constructive_incumbent_solve_result(
                problem,
                incumbent,
                started=started,
                build_finished=build_finished,
                search_finished=None,
                deadline=deadline,
                seed=seed,
                workers=workers,
                fallback_reason="projected_prebuild_representation_gate",
                telemetry={"scale": scale, "deadline_policy": deadline_policy},
            )
        return _non_solution_result(
            problem,
            status="projected_prebuild_gate_constructive_failed",
            started=started,
            build_finished=build_finished,
            deadline=deadline,
            seed=seed,
            workers=workers,
            telemetry={
                "strategy": "constructive_coloring_with_bounded_ejection",
                "scale": scale,
                "deadline_policy": deadline_policy,
                "fail_closed": True,
            },
        )
    model = cp_model.CpModel()
    period_var: dict[int, cp_model.IntVar] = {}
    period_use: dict[tuple[int, int], cp_model.IntVar] = {}
    day_var: dict[int, cp_model.IntVar] = {}
    objective_terms: list[cp_model.LinearExpr] = []
    day_ids: dict[str, int] = {}
    day_by_period: list[int] = []
    hall_cut_count = 0
    for period in problem.periods:
        day_by_period.append(day_ids.setdefault(period.date, len(day_ids)))

    try:
        for exam_id, allowed_periods in eligible_periods.items():
            if exam_id & 15 == 0:
                _deadline_check(acceptance_deadline, "projected period variables")
            selected_period = model.new_int_var_from_domain(
                cp_model.Domain.from_values(allowed_periods),
                f"projected_period_e{exam_id}",
            )
            period_var[exam_id] = selected_period
            selected_day = model.new_int_var(
                0, max(0, len(day_ids) - 1), f"projected_day_e{exam_id}"
            )
            model.add_element(selected_period, day_by_period, selected_day)
            day_var[exam_id] = selected_day
            uses: list[cp_model.IntVar] = []
            for period_id in allowed_periods:
                used = model.new_bool_var(f"projected_use_e{exam_id}_p{period_id}")
                period_use[(exam_id, period_id)] = used
                uses.append(used)
                unary = problem.periods[period_id].penalty
                if unary:
                    objective_terms.append(unary * used)
            model.add_exactly_one(uses)
            model.add(
                selected_period
                == sum(
                    period_id * period_use[(exam_id, period_id)]
                    for period_id in allowed_periods
                )
            )
            if incumbent is not None:
                model.add_hint(
                    selected_period,
                    incumbent.assignments[exam_id].period,
                )

        shared_counts = problem.shared_student_counts
        for pair_index, ((left, right), common_students) in enumerate(
            sorted(shared_counts.items())
        ):
            if pair_index & 63 == 0:
                _deadline_check(acceptance_deadline, "projected student relations")
            if common_students <= 0:
                continue
            model.add(period_var[left] != period_var[right])
            needs_temporal_cost = bool(
                problem.weights.two_in_a_row
                or problem.weights.two_in_a_day
                or problem.weights.period_spread
            )
            if not needs_temporal_cost:
                continue
            if len(problem.periods) <= 1:
                # The conflict already makes this model infeasible; avoid
                # constructing an invalid [1, 0] distance domain.
                continue
            distance = model.new_int_var(
                1, len(problem.periods) - 1, f"projected_distance_{left}_{right}"
            )
            model.add_abs_equality(distance, period_var[left] - period_var[right])
            same_day = model.new_bool_var(f"projected_same_day_{left}_{right}")
            model.add(day_var[left] == day_var[right]).only_enforce_if(same_day)
            model.add(day_var[left] != day_var[right]).only_enforce_if(
                same_day.negated()
            )
            if problem.weights.two_in_a_day:
                objective_terms.append(
                    common_students * problem.weights.two_in_a_day * same_day
                )
            if problem.weights.two_in_a_row != problem.weights.two_in_a_day:
                adjacent_same_day = model.new_bool_var(
                    f"projected_adjacent_same_day_{left}_{right}"
                )
                model.add(adjacent_same_day <= same_day)
                model.add(distance == 1).only_enforce_if(adjacent_same_day)
                model.add(distance != 1).only_enforce_if(
                    [same_day, adjacent_same_day.negated()]
                )
                objective_terms.append(
                    common_students
                    * (problem.weights.two_in_a_row - problem.weights.two_in_a_day)
                    * adjacent_same_day
                )
            if problem.weights.period_spread > 0:
                within_spread = model.new_bool_var(
                    f"projected_within_spread_{left}_{right}"
                )
                model.add(distance <= problem.weights.period_spread).only_enforce_if(
                    within_spread
                )
                model.add(distance > problem.weights.period_spread).only_enforce_if(
                    within_spread.negated()
                )
                objective_terms.append(common_students * within_spread)

        for constraint in problem.period_constraints:
            if not _coincidence_is_active(constraint, shared_counts):
                continue
            if constraint.kind == "AFTER":
                model.add(
                    period_var[constraint.first_exam]
                    > period_var[constraint.second_exam]
                )
            elif constraint.kind == "EXCLUSION":
                model.add(
                    period_var[constraint.first_exam]
                    != period_var[constraint.second_exam]
                )
            else:
                model.add(
                    period_var[constraint.first_exam]
                    == period_var[constraint.second_exam]
                )

        largest = set(
            sorted(
                range(len(problem.exams)),
                key=lambda exam_id: (-problem.exams[exam_id].size, exam_id),
            )[: problem.weights.frontload_largest_exams]
        )
        frontload_threshold = max(
            0, len(problem.periods) - problem.weights.frontload_last_periods
        )
        if problem.weights.frontload_penalty:
            for exam_id in largest:
                for period_id in eligible_periods[exam_id]:
                    if period_id >= frontload_threshold:
                        objective_terms.append(
                            problem.weights.frontload_penalty
                            * period_use[(exam_id, period_id)]
                        )

        room_capacities = sorted(room.capacity for room in problem.rooms)
        thresholds = (0, *sorted(set(room_capacities))[:-1])
        for threshold in thresholds:
            available_capacity = sum(
                capacity for capacity in room_capacities if capacity > threshold
            )
            members = [
                exam_id
                for exam_id, exam in enumerate(problem.exams)
                if exam.size > threshold
            ]
            if not members:
                continue
            for period_id in range(len(problem.periods)):
                if period_id & 15 == 0:
                    _deadline_check(acceptance_deadline, "projected Hall capacity cuts")
                terms = [
                    problem.exams[exam_id].size * period_use[(exam_id, period_id)]
                    for exam_id in members
                    if (exam_id, period_id) in period_use
                ]
                if terms:
                    model.add(sum(terms) <= available_capacity)
                    hall_cut_count += 1

        # Size-only Hall cuts can miss a class containing too many medium or
        # large exams.  These cardinality cuts are another necessary condition:
        # a room of capacity C has at most floor(C / q) slots for exams whose
        # size is at least q.  Deduplicating identical slot profiles keeps the
        # projected model compact on large public instances.
        seen_slot_profiles: set[tuple[int, ...]] = set()
        for minimum_size in sorted({exam.size for exam in problem.exams}):
            if minimum_size <= 0:
                continue
            slot_profile = tuple(
                capacity // minimum_size for capacity in room_capacities
            )
            if slot_profile in seen_slot_profiles:
                continue
            seen_slot_profiles.add(slot_profile)
            available_slots = sum(slot_profile)
            members = [
                exam_id
                for exam_id, exam in enumerate(problem.exams)
                if exam.size >= minimum_size
            ]
            if available_slots >= len(members):
                continue
            for period_id in range(len(problem.periods)):
                if period_id & 15 == 0:
                    _deadline_check(
                        acceptance_deadline, "projected Hall cardinality cuts"
                    )
                terms = [
                    period_use[(exam_id, period_id)]
                    for exam_id in members
                    if (exam_id, period_id) in period_use
                ]
                if len(terms) > available_slots:
                    model.add(sum(terms) <= available_slots)
                    hall_cut_count += 1

        exclusive = {constraint.exam for constraint in problem.room_constraints}
        if exclusive:
            for period_id in range(len(problem.periods)):
                terms = [
                    period_use[(exam_id, period_id)]
                    for exam_id in exclusive
                    if (exam_id, period_id) in period_use
                ]
                if terms:
                    model.add(sum(terms) <= len(problem.rooms))
                    hall_cut_count += 1
            for threshold in thresholds[1:]:
                fitting_rooms = sum(
                    capacity > threshold for capacity in room_capacities
                )
                members = [
                    exam_id
                    for exam_id in exclusive
                    if problem.exams[exam_id].size > threshold
                ]
                if not members:
                    continue
                for period_id in range(len(problem.periods)):
                    terms = [
                        period_use[(exam_id, period_id)]
                        for exam_id in members
                        if (exam_id, period_id) in period_use
                    ]
                    if len(terms) > fitting_rooms:
                        model.add(sum(terms) <= fitting_rooms)
                        hall_cut_count += 1

        projected_objective = sum(objective_terms)
        if incumbent is not None:
            incumbent_projected_objective = (
                incumbent.validation.objective.total
                - incumbent.validation.objective.room_penalty
                - incumbent.validation.objective.mixed_durations
            )
            model.add(projected_objective <= incumbent_projected_objective)
        model.minimize(projected_objective)
    except _DeadlineExpired:
        build_finished = time.perf_counter()
        if incumbent is not None:
            return _constructive_incumbent_solve_result(
                problem,
                incumbent,
                started=started,
                build_finished=build_finished,
                search_finished=None,
                deadline=deadline,
                seed=seed,
                workers=workers,
                fallback_reason="deadline_during_projected_build",
                telemetry={"scale": scale, "deadline_policy": deadline_policy},
            )
        return _non_solution_result(
            problem,
            status="deadline_during_projected_build",
            started=started,
            build_finished=build_finished,
            deadline=deadline,
            seed=seed,
            workers=workers,
            telemetry={
                "strategy": "projected_period_coloring_with_room_lift",
                "scale": scale,
                "fail_closed": True,
            },
        )

    build_finished = time.perf_counter()
    remaining = acceptance_deadline - build_finished - room_lift_reserve
    if remaining < minimum_projected_search:
        deadline_policy["projected_skipped_reason"] = "insufficient_calibrated_budget"
        if incumbent is not None:
            return _constructive_incumbent_solve_result(
                problem,
                incumbent,
                started=started,
                build_finished=build_finished,
                search_finished=None,
                deadline=deadline,
                seed=seed,
                workers=workers,
                fallback_reason="insufficient_budget_before_projected_search",
                telemetry={"scale": scale, "deadline_policy": deadline_policy},
            )
        return _non_solution_result(
            problem,
            status="insufficient_budget_before_projected_search",
            started=started,
            build_finished=build_finished,
            deadline=deadline,
            seed=seed,
            workers=workers,
            telemetry={
                "strategy": "projected_period_coloring_with_room_lift",
                "scale": scale,
                "deadline_policy": deadline_policy,
                "fail_closed": True,
            },
        )

    projected_search_seconds = min(
        remaining * 0.60,
        max(0.001, remaining - 0.25 * minimum_projected_search),
    )
    deadline_policy["projected_search_seconds"] = projected_search_seconds
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.001, projected_search_seconds)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.random_seed = int(seed)
    solver.parameters.randomize_search = True
    raw_status = int(solver.solve(model))
    search_finished = time.perf_counter()
    if not _projected_acceptance_is_timely(
        search_finished,
        deadline=deadline,
        final_acceptance_reserve_seconds=final_acceptance_reserve,
    ):
        deadline_policy["projected_skipped_reason"] = "late_solver_return"
        if incumbent is not None:
            return _constructive_incumbent_solve_result(
                problem,
                incumbent,
                started=started,
                build_finished=build_finished,
                search_finished=search_finished,
                deadline=deadline,
                seed=seed,
                workers=workers,
                fallback_reason="late_projected_solver_return",
                raw_status=raw_status,
                telemetry={"scale": scale, "deadline_policy": deadline_policy},
            )
        return _non_solution_result(
            problem,
            status="late_projected_solver_return",
            started=started,
            build_finished=build_finished,
            deadline=deadline,
            seed=seed,
            workers=workers,
            raw_status=raw_status,
            telemetry={
                "strategy": "projected_period_coloring_with_room_lift",
                "scale": scale,
                "deadline_policy": deadline_policy,
                "fail_closed": True,
            },
        )
    if raw_status not in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}:
        if incumbent is not None:
            return _constructive_incumbent_solve_result(
                problem,
                incumbent,
                started=started,
                build_finished=build_finished,
                search_finished=search_finished,
                deadline=deadline,
                seed=seed,
                workers=workers,
                fallback_reason=(
                    f"projected_{cp_model.CpSolverStatus(raw_status).name.lower()}"
                ),
                raw_status=raw_status,
                telemetry={
                    "scale": scale,
                    "projected_objective_terms": len(objective_terms),
                    "hall_cuts": hall_cut_count,
                    "deadline_policy": deadline_policy,
                },
            )
        return _non_solution_result(
            problem,
            status=f"projected_{cp_model.CpSolverStatus(raw_status).name.lower()}",
            started=started,
            build_finished=build_finished,
            deadline=deadline,
            seed=seed,
            workers=workers,
            raw_status=raw_status,
            telemetry={
                "strategy": "projected_period_coloring_with_room_lift",
                "scale": scale,
                "projected_objective_terms": len(objective_terms),
                "hall_cuts": hall_cut_count,
                "fail_closed": True,
            },
        )

    period_by_exam = tuple(
        int(solver.value(period_var[exam_id])) for exam_id in range(len(problem.exams))
    )
    room_deadline = acceptance_deadline
    room_started = time.perf_counter()
    room_by_exam, room_telemetry = _pack_fixed_period_rooms(
        problem,
        period_by_exam,
        deadline=room_deadline,
    )
    if room_by_exam is None:
        if incumbent is not None:
            return _constructive_incumbent_solve_result(
                problem,
                incumbent,
                started=started,
                build_finished=build_finished,
                search_finished=search_finished,
                deadline=deadline,
                seed=seed,
                workers=workers,
                fallback_reason="projected_room_lift_failed",
                raw_status=raw_status,
                telemetry={
                    "scale": scale,
                    "room_lift": room_telemetry,
                    "deadline_policy": deadline_policy,
                },
            )
        return _non_solution_result(
            problem,
            status="projected_room_lift_failed",
            started=started,
            build_finished=build_finished,
            deadline=deadline,
            seed=seed,
            workers=workers,
            raw_status=raw_status,
            telemetry={
                "strategy": "projected_period_coloring_with_room_lift",
                "scale": scale,
                "room_lift": room_telemetry,
                "fail_closed": True,
            },
        )
    assignments = tuple(
        ITC2007ExamAssignment(
            exam=exam_id,
            period=period_by_exam[exam_id],
            room=room_by_exam[exam_id],
        )
        for exam_id in range(len(problem.exams))
    )
    validation = validate_itc2007_exam_solution(problem, assignments)
    finished = time.perf_counter()
    if not _projected_acceptance_is_timely(
        finished,
        deadline=deadline,
        final_acceptance_reserve_seconds=final_acceptance_reserve,
    ):
        deadline_policy["projected_skipped_reason"] = "late_final_validation"
        if incumbent is not None:
            return _constructive_incumbent_solve_result(
                problem,
                incumbent,
                started=started,
                build_finished=build_finished,
                search_finished=search_finished,
                deadline=deadline,
                seed=seed,
                workers=workers,
                fallback_reason="late_projected_final_validation",
                raw_status=raw_status,
                telemetry={
                    "scale": scale,
                    "deadline_policy": deadline_policy,
                    "room_lift": room_telemetry,
                },
            )
        return _non_solution_result(
            problem,
            status="late_projected_final_validation",
            started=started,
            build_finished=build_finished,
            deadline=deadline,
            seed=seed,
            workers=workers,
            raw_status=raw_status,
            telemetry={
                "strategy": "projected_period_coloring_with_room_lift",
                "scale": scale,
                "deadline_policy": deadline_policy,
                "room_lift": room_telemetry,
                "fail_closed": True,
            },
        )
    if incumbent is not None and (
        not validation.feasible
        or incumbent.validation.objective.total <= validation.objective.total
    ):
        return _constructive_incumbent_solve_result(
            problem,
            incumbent,
            started=started,
            build_finished=build_finished,
            search_finished=search_finished,
            deadline=deadline,
            seed=seed,
            workers=workers,
            fallback_reason=(
                "projected_solution_invalid"
                if not validation.feasible
                else "constructive_incumbent_nonworsening"
            ),
            raw_status=raw_status,
            telemetry={
                "scale": scale,
                "projected_candidate_objective": (
                    validation.objective.total if validation.feasible else None
                ),
                "projected_objective": int(round(solver.objective_value)),
                "hall_cuts": hall_cut_count,
                "room_lift": room_telemetry,
                "deadline_policy": deadline_policy,
            },
        )
    status = (
        "feasible_projected" if validation.feasible else "invalid_projected_solution"
    )
    if not validation.feasible:
        assignments = ()
    return ITC2007ExamSolveResult(
        assignments=assignments,
        validation=validation,
        status=status,
        raw_status=raw_status,
        objective_value=validation.objective.total if validation.feasible else None,
        best_bound=None,
        build_seconds=max(0.0, build_finished - started),
        search_seconds=max(0.0, search_finished - build_finished),
        elapsed_seconds=max(0.0, finished - started),
        deadline_overrun_seconds=max(0.0, finished - deadline),
        seed=seed,
        workers=workers,
        telemetry={
            "strategy": "projected_period_coloring_with_room_lift",
            "scale": scale,
            "projected_objective": int(round(solver.objective_value)),
            "projected_best_bound": int(round(solver.best_objective_bound)),
            "projected_objective_terms": len(objective_terms),
            "hall_cuts": hall_cut_count,
            "room_lift_seconds": max(0.0, finished - room_started),
            "room_lift": room_telemetry,
            "cleanup_reserve_seconds": final_acceptance_reserve,
            "room_lift_reserve_seconds": room_lift_reserve,
            "deadline_policy": deadline_policy,
            "constructive": (
                dict(incumbent.telemetry) if incumbent is not None else None
            ),
            "fail_closed": not validation.feasible,
        },
    )


def solve_itc2007_exam(
    problem: ITC2007ExamProblem,
    *,
    time_limit_seconds: float,
    seed: int = 0,
    workers: int = 1,
    max_exams: int = 1_500,
    max_shared_student_pairs: int = 50_000,
    max_placements: int = 2_000_000,
    max_exact_exams: int = 80,
    max_exact_shared_student_pairs: int = 4_000,
    max_exact_placements: int = 20_000,
    solve_reserve_seconds: float = 0.005,
    initial_assignments: Sequence[ITC2007ExamAssignment] | None = None,
    coupled_lns_period_radius: int = 3,
    post_incumbent_portfolio: bool = False,
) -> ITC2007ExamSolveResult:
    """Solve through an exact core or a scale-safe period/room decomposition."""

    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be positive")
    if workers <= 0:
        raise ValueError("workers must be positive")
    if coupled_lns_period_radius < 0:
        raise ValueError("coupled_lns_period_radius must be non-negative")
    if post_incumbent_portfolio and initial_assignments is None:
        raise ValueError(
            "post_incumbent_portfolio requires explicit initial_assignments"
        )
    if (
        min(
            max_exams,
            max_shared_student_pairs,
            max_placements,
            max_exact_exams,
            max_exact_shared_student_pairs,
            max_exact_placements,
        )
        < 0
    ):
        raise ValueError("scale gates must be non-negative")
    started = time.perf_counter()
    deadline = started + float(time_limit_seconds)
    basic_scale: dict[str, object] = {
        "exams": len(problem.exams),
        "periods": len(problem.periods),
        "rooms": len(problem.rooms),
        "shared_student_pairs": None,
        "eligible_placements": None,
        "gates": {
            "max_exams": int(max_exams),
            "max_shared_student_pairs": int(max_shared_student_pairs),
            "max_placements": int(max_placements),
            "max_exact_exams": int(max_exact_exams),
            "max_exact_shared_student_pairs": int(max_exact_shared_student_pairs),
            "max_exact_placements": int(max_exact_placements),
        },
    }
    if len(problem.exams) > max_exams:
        now = time.perf_counter()
        return _non_solution_result(
            problem,
            status="unsupported_scale",
            started=started,
            build_finished=now,
            deadline=deadline,
            seed=seed,
            workers=workers,
            telemetry={"scale": basic_scale, "fail_closed": True},
        )
    eligible_periods: dict[int, tuple[int, ...]] = {}
    eligible_rooms: dict[int, tuple[int, ...]] = {}
    placement_count = 0
    for exam_id, exam in enumerate(problem.exams):
        if exam_id % 16 == 0 and time.perf_counter() >= deadline:
            now = time.perf_counter()
            return _non_solution_result(
                problem,
                status="deadline_during_presolve",
                started=started,
                build_finished=now,
                deadline=deadline,
                seed=seed,
                workers=workers,
                telemetry={"scale": basic_scale, "fail_closed": True},
            )
        periods = tuple(
            period_id
            for period_id, period in enumerate(problem.periods)
            if exam.duration <= period.duration
        )
        rooms = tuple(
            room_id
            for room_id, room in enumerate(problem.rooms)
            if exam.size <= room.capacity
        )
        eligible_periods[exam_id] = periods
        eligible_rooms[exam_id] = rooms
        placement_count += len(periods) * len(rooms)
    basic_scale["eligible_placements"] = placement_count
    if placement_count > max_placements:
        now = time.perf_counter()
        return _non_solution_result(
            problem,
            status="unsupported_scale",
            started=started,
            build_finished=now,
            deadline=deadline,
            seed=seed,
            workers=workers,
            telemetry={"scale": basic_scale, "fail_closed": True},
        )
    shared_counts = problem.shared_student_counts
    basic_scale["shared_student_pairs"] = len(shared_counts)

    scale = basic_scale
    if len(shared_counts) > max_shared_student_pairs:
        now = time.perf_counter()
        return _non_solution_result(
            problem,
            status="unsupported_scale",
            started=started,
            build_finished=now,
            deadline=deadline,
            seed=seed,
            workers=workers,
            telemetry={"scale": scale, "fail_closed": True},
        )
    impossible = [
        exam_id
        for exam_id in range(len(problem.exams))
        if not eligible_periods[exam_id] or not eligible_rooms[exam_id]
    ]
    if impossible:
        now = time.perf_counter()
        return _non_solution_result(
            problem,
            status="infeasible_domain",
            started=started,
            build_finished=now,
            deadline=deadline,
            seed=seed,
            workers=workers,
            telemetry={
                "scale": scale,
                "domain_empty_exams": impossible,
                "fail_closed": True,
            },
            raw_status=int(cp_model.INFEASIBLE),
        )

    if initial_assignments is not None:
        incumbent = tuple(sorted(initial_assignments, key=lambda row: row.exam))
        incumbent_validation = validate_itc2007_exam_solution(problem, incumbent)
        if not incumbent_validation.feasible:
            raise ValueError("initial_assignments must be complete and hard-feasible")
        build_finished = time.perf_counter()
        if post_incumbent_portfolio:
            optimized, validation, portfolio = polish_itc2007_exam_post_incumbent(
                problem,
                incumbent,
                deadline=deadline,
            )
            finished = time.perf_counter()
            return ITC2007ExamSolveResult(
                assignments=optimized,
                validation=validation,
                status=(
                    "feasible_post_incumbent_portfolio"
                    if bool(portfolio["accepted"])
                    else "feasible_initial_assignments"
                ),
                raw_status=int(cp_model.FEASIBLE),
                objective_value=validation.objective.total,
                best_bound=None,
                build_seconds=max(0.0, build_finished - started),
                search_seconds=max(0.0, finished - build_finished),
                elapsed_seconds=max(0.0, finished - started),
                deadline_overrun_seconds=max(0.0, finished - deadline),
                seed=seed,
                workers=workers,
                telemetry={
                    "strategy": "explicit_post_incumbent_portfolio",
                    "scale": scale,
                    "post_incumbent_portfolio": portfolio,
                    "fail_closed": bool(portfolio["fail_closed"]),
                },
            )
        optimized, validation, coupled_lns = _optimize_exam_period_room_neighborhood(
            problem,
            incumbent,
            deadline=deadline,
            seed=seed,
            period_radius=coupled_lns_period_radius,
            workers=workers,
        )
        finished = time.perf_counter()
        return ITC2007ExamSolveResult(
            assignments=optimized,
            validation=validation,
            status=(
                "feasible_coupled_lns"
                if bool(coupled_lns["accepted"])
                else "feasible_initial_assignments"
            ),
            raw_status=int(cp_model.FEASIBLE),
            objective_value=validation.objective.total,
            best_bound=None,
            build_seconds=max(0.0, build_finished - started),
            search_seconds=max(0.0, finished - build_finished),
            elapsed_seconds=max(0.0, finished - started),
            deadline_overrun_seconds=max(0.0, finished - deadline),
            seed=seed,
            workers=workers,
            telemetry={
                "strategy": "incumbent_hinted_coupled_period_room_lns",
                "scale": scale,
                "coupled_lns": coupled_lns,
                "fail_closed": False,
            },
        )

    exact_scale = bool(
        len(problem.exams) <= max_exact_exams
        and len(shared_counts) <= max_exact_shared_student_pairs
        and placement_count <= max_exact_placements
    )
    scale["solver_lane"] = "exact_cartesian" if exact_scale else "projected_period_room"
    if not exact_scale:
        try:
            return _solve_projected_itc2007_exam(
                problem,
                started=started,
                deadline=deadline,
                eligible_periods=eligible_periods,
                scale=scale,
                seed=seed,
                workers=workers,
                solve_reserve_seconds=solve_reserve_seconds,
            )
        except (MemoryError, OSError) as exc:
            now = time.perf_counter()
            return _non_solution_result(
                problem,
                status="resource_exhausted_during_projected_solve",
                started=started,
                build_finished=now,
                deadline=deadline,
                seed=seed,
                workers=workers,
                telemetry={
                    "strategy": "projected_period_coloring_with_room_lift",
                    "scale": scale,
                    "resource_error": type(exc).__name__,
                    "fail_closed": True,
                },
            )

    eligible = {
        exam_id: tuple(
            (period_id, room_id)
            for period_id in eligible_periods[exam_id]
            for room_id in eligible_rooms[exam_id]
        )
        for exam_id in range(len(problem.exams))
    }

    model = cp_model.CpModel()
    placement: dict[tuple[int, int, int], cp_model.IntVar] = {}
    period_use: dict[tuple[int, int], cp_model.IntVar] = {}
    period_var: dict[int, cp_model.IntVar] = {}
    objective_terms: list[cp_model.LinearExpr] = []
    try:
        for exam_id, placements in eligible.items():
            _deadline_check(deadline, "placement variables")
            exam_variables: list[cp_model.IntVar] = []
            by_period: dict[int, list[cp_model.IntVar]] = defaultdict(list)
            for period_id, room_id in placements:
                variable = model.new_bool_var(f"x_e{exam_id}_p{period_id}_r{room_id}")
                placement[(exam_id, period_id, room_id)] = variable
                exam_variables.append(variable)
                by_period[period_id].append(variable)
                unary = (
                    problem.periods[period_id].penalty + problem.rooms[room_id].penalty
                )
                if unary:
                    objective_terms.append(unary * variable)
            model.add_exactly_one(exam_variables)
            for period_id in range(len(problem.periods)):
                variables = by_period.get(period_id, [])
                if not variables:
                    period_use[(exam_id, period_id)] = model.new_constant(0)
                elif len(variables) == 1:
                    period_use[(exam_id, period_id)] = variables[0]
                else:
                    used = model.new_bool_var(f"y_e{exam_id}_p{period_id}")
                    model.add(used == sum(variables))
                    period_use[(exam_id, period_id)] = used
            selected_period = model.new_int_var(
                0, len(problem.periods) - 1, f"period_e{exam_id}"
            )
            model.add(
                selected_period
                == sum(
                    period_id * period_use[(exam_id, period_id)]
                    for period_id in range(len(problem.periods))
                )
            )
            period_var[exam_id] = selected_period

        by_room_period: dict[tuple[int, int], list[tuple[int, cp_model.IntVar]]] = (
            defaultdict(list)
        )
        for (exam_id, period_id, room_id), variable in placement.items():
            by_room_period[(period_id, room_id)].append((exam_id, variable))
        for (period_id, room_id), members in by_room_period.items():
            model.add(
                sum(problem.exams[exam].size * variable for exam, variable in members)
                <= problem.rooms[room_id].capacity
            )

        for (left, right), common_students in shared_counts.items():
            if common_students <= 0:
                continue
            _deadline_check(deadline, "student conflicts")
            for period_id in range(len(problem.periods)):
                model.add(
                    period_use[(left, period_id)] + period_use[(right, period_id)] <= 1
                )

        for constraint in problem.period_constraints:
            if not _coincidence_is_active(constraint, shared_counts):
                continue
            if constraint.kind == "AFTER":
                model.add(
                    period_var[constraint.first_exam]
                    > period_var[constraint.second_exam]
                )
            elif constraint.kind == "EXCLUSION":
                for period_id in range(len(problem.periods)):
                    model.add(
                        period_use[(constraint.first_exam, period_id)]
                        + period_use[(constraint.second_exam, period_id)]
                        <= 1
                    )
            else:
                model.add(
                    period_var[constraint.first_exam]
                    == period_var[constraint.second_exam]
                )

        exclusive = {constraint.exam for constraint in problem.room_constraints}
        for exam_id in exclusive:
            for period_id, room_id in eligible[exam_id]:
                selected = placement[(exam_id, period_id, room_id)]
                for other, other_variable in by_room_period[(period_id, room_id)]:
                    if other != exam_id:
                        model.add(selected + other_variable <= 1)

        largest = set(
            sorted(
                range(len(problem.exams)),
                key=lambda exam: (-problem.exams[exam].size, exam),
            )[: problem.weights.frontload_largest_exams]
        )
        threshold = max(
            0, len(problem.periods) - problem.weights.frontload_last_periods
        )
        if problem.weights.frontload_penalty:
            for exam_id in largest:
                for period_id in range(threshold, len(problem.periods)):
                    objective_terms.append(
                        problem.weights.frontload_penalty
                        * period_use[(exam_id, period_id)]
                    )

        pair_cost_variables = 0
        period_count = len(problem.periods)
        for pair_index, ((left, right), common_students) in enumerate(
            sorted(shared_counts.items())
        ):
            if pair_index % 32 == 0:
                _deadline_check(deadline, "student objective")
            costs: list[int] = []
            for first_period in range(period_count):
                for second_period in range(period_count):
                    low = min(first_period, second_period)
                    high = max(first_period, second_period)
                    distance = high - low
                    same_day = problem.periods[low].date == problem.periods[high].date
                    value = 0
                    if distance == 1 and same_day:
                        value += common_students * problem.weights.two_in_a_row
                    elif distance > 1 and same_day:
                        value += common_students * problem.weights.two_in_a_day
                    if 0 < distance <= problem.weights.period_spread:
                        value += common_students
                    costs.append(value)
            if not any(costs):
                continue
            index = model.new_int_var(
                0, period_count * period_count - 1, f"pair_index_{left}_{right}"
            )
            model.add(index == period_var[left] * period_count + period_var[right])
            cost = model.new_int_var(0, max(costs), f"pair_cost_{left}_{right}")
            model.add_element(index, costs, cost)
            objective_terms.append(cost)
            pair_cost_variables += 1

        duration_types = sorted({exam.duration for exam in problem.exams})
        mixed_room_periods = 0
        if problem.weights.non_mixed_durations:
            for (period_id, room_id), members in by_room_period.items():
                duration_members: dict[int, list[cp_model.IntVar]] = defaultdict(list)
                all_variables: list[cp_model.IntVar] = []
                for exam_id, variable in members:
                    duration_members[problem.exams[exam_id].duration].append(variable)
                    all_variables.append(variable)
                if len(duration_members) <= 1:
                    continue
                occupied = model.new_bool_var(f"occupied_p{period_id}_r{room_id}")
                model.add_max_equality(occupied, all_variables)
                duration_used: list[cp_model.IntVar] = []
                for duration in duration_types:
                    variables = duration_members.get(duration)
                    if not variables:
                        continue
                    if len(variables) == 1:
                        duration_used.append(variables[0])
                    else:
                        used = model.new_bool_var(
                            f"duration_{duration}_p{period_id}_r{room_id}"
                        )
                        model.add_max_equality(used, variables)
                        duration_used.append(used)
                weight = problem.weights.non_mixed_durations
                objective_terms.extend(weight * used for used in duration_used)
                objective_terms.append(-weight * occupied)
                mixed_room_periods += 1

        model.minimize(sum(objective_terms))
    except _DeadlineExpired:
        build_finished = time.perf_counter()
        return _non_solution_result(
            problem,
            status="deadline_during_build",
            started=started,
            build_finished=build_finished,
            deadline=deadline,
            seed=seed,
            workers=workers,
            telemetry={"scale": scale, "fail_closed": True},
        )

    build_finished = time.perf_counter()
    cleanup_reserve = max(
        max(0.0, float(solve_reserve_seconds)),
        min(3.0, max(0.05, 0.20 * float(time_limit_seconds))),
    )
    remaining = deadline - build_finished - cleanup_reserve
    if remaining <= 0:
        return _non_solution_result(
            problem,
            status="deadline_before_search",
            started=started,
            build_finished=build_finished,
            deadline=deadline,
            seed=seed,
            workers=workers,
            telemetry={"scale": scale, "fail_closed": True},
        )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.001, remaining)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.random_seed = int(seed)
    raw_status = int(solver.solve(model))
    search_finished = time.perf_counter()
    assignments: tuple[ITC2007ExamAssignment, ...] = ()
    objective_value: int | None = None
    best_bound: int | None = None
    if raw_status in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}:
        assignments = tuple(
            ITC2007ExamAssignment(
                exam=exam_id,
                period=next(
                    period_id
                    for period_id, room_id in eligible[exam_id]
                    if solver.value(placement[(exam_id, period_id, room_id)])
                ),
                room=next(
                    room_id
                    for period_id, room_id in eligible[exam_id]
                    if solver.value(placement[(exam_id, period_id, room_id)])
                ),
            )
            for exam_id in range(len(problem.exams))
        )
        objective_value = int(round(solver.objective_value))
    if raw_status != int(cp_model.MODEL_INVALID):
        try:
            best_bound = int(round(solver.best_objective_bound))
        except (AttributeError, OverflowError, ValueError):
            best_bound = None
    validation = validate_itc2007_exam_solution(problem, assignments)
    status = cp_model.CpSolverStatus(raw_status).name.lower()
    if assignments and not validation.feasible:
        status = "invalid_returned_solution"
    if assignments and objective_value != validation.objective.total:
        status = "objective_mismatch"
    finished = time.perf_counter()
    return ITC2007ExamSolveResult(
        assignments=assignments,
        validation=validation,
        status=status,
        raw_status=raw_status,
        objective_value=objective_value,
        best_bound=best_bound,
        build_seconds=max(0.0, build_finished - started),
        search_seconds=max(0.0, search_finished - build_finished),
        elapsed_seconds=max(0.0, finished - started),
        deadline_overrun_seconds=max(0.0, finished - deadline),
        seed=seed,
        workers=workers,
        telemetry={
            "scale": scale,
            "pair_cost_variables": pair_cost_variables,
            "mixed_room_periods": mixed_room_periods,
            "objective_terms": len(objective_terms),
            "cleanup_reserve_seconds": cleanup_reserve,
            "fail_closed": not bool(assignments),
        },
    )
