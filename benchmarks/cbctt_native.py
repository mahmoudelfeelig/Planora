from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
import time

from ortools.sat.python import cp_model

from benchmarks.cbctt import CBCTTExtendedProblem, CBCTTExtendedRoom


CBCTT_NATIVE_SEMANTICS_ID = "bonutti-ud1-ud5-native-v1"
CBCTT_NATIVE_REFERENCE_DOI = "10.1007/s10479-010-0707-0"


@dataclass(frozen=True)
class CBCTTFormulation:
    """One of the five weighted ECTT formulations from Bonutti et al.

    ``None`` means that a soft component is absent. Room suitability is the
    sole optional component that becomes hard (in UD4), so that distinction is
    represented explicitly instead of assigning it an arbitrary large weight.
    """

    name: str
    room_capacity: int | None
    minimum_working_days: int | None
    isolated_lectures: int | None
    windows: int | None
    room_stability: int | None
    student_min_max_load: int | None
    travel_distance: int | None
    room_suitability: int | None
    double_lectures: int | None
    room_suitability_hard: bool = False

    def weights(self) -> dict[str, int | None]:
        return {
            "room_capacity": self.room_capacity,
            "minimum_working_days": self.minimum_working_days,
            "isolated_lectures": self.isolated_lectures,
            "windows": self.windows,
            "room_stability": self.room_stability,
            "student_min_max_load": self.student_min_max_load,
            "travel_distance": self.travel_distance,
            "room_suitability": self.room_suitability,
            "double_lectures": self.double_lectures,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "weights": self.weights(),
            "room_suitability_hard": self.room_suitability_hard,
            "semantics_id": CBCTT_NATIVE_SEMANTICS_ID,
            "reference_doi": CBCTT_NATIVE_REFERENCE_DOI,
        }


CBCTT_FORMULATIONS: dict[str, CBCTTFormulation] = {
    "UD1": CBCTTFormulation(
        name="UD1",
        room_capacity=1,
        minimum_working_days=5,
        isolated_lectures=1,
        windows=None,
        room_stability=None,
        student_min_max_load=None,
        travel_distance=None,
        room_suitability=None,
        double_lectures=None,
    ),
    "UD2": CBCTTFormulation(
        name="UD2",
        room_capacity=1,
        minimum_working_days=5,
        isolated_lectures=2,
        windows=None,
        room_stability=1,
        student_min_max_load=None,
        travel_distance=None,
        room_suitability=None,
        double_lectures=None,
    ),
    "UD3": CBCTTFormulation(
        name="UD3",
        room_capacity=1,
        minimum_working_days=None,
        isolated_lectures=None,
        windows=4,
        room_stability=None,
        student_min_max_load=2,
        travel_distance=None,
        room_suitability=3,
        double_lectures=None,
    ),
    "UD4": CBCTTFormulation(
        name="UD4",
        room_capacity=1,
        minimum_working_days=1,
        isolated_lectures=None,
        windows=1,
        room_stability=None,
        student_min_max_load=1,
        travel_distance=None,
        room_suitability=None,
        double_lectures=1,
        room_suitability_hard=True,
    ),
    "UD5": CBCTTFormulation(
        name="UD5",
        room_capacity=1,
        minimum_working_days=5,
        isolated_lectures=1,
        windows=2,
        room_stability=None,
        student_min_max_load=2,
        travel_distance=2,
        room_suitability=None,
        double_lectures=None,
    ),
}


@dataclass(frozen=True)
class CBCTTAssignment:
    course_id: str
    room_id: str
    day: int
    period: int


@dataclass(frozen=True)
class CBCTTScore:
    formulation: str
    room_capacity: int
    minimum_working_days: int
    isolated_lectures: int
    windows: int
    room_stability: int
    student_min_max_load: int
    travel_distance: int
    room_suitability: int
    double_lectures: int
    total: int

    def raw_components(self) -> dict[str, int]:
        return {
            key: int(value)
            for key, value in asdict(self).items()
            if key not in {"formulation", "total"}
        }

    def weighted_components(self) -> dict[str, int]:
        formulation = get_cbctt_formulation(self.formulation)
        raw = self.raw_components()
        return {
            name: int(raw[name] * weight)
            for name, weight in formulation.weights().items()
            if weight is not None
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "formulation": self.formulation,
            "semantics_id": CBCTT_NATIVE_SEMANTICS_ID,
            "raw_components": self.raw_components(),
            "weighted_components": self.weighted_components(),
            "total": int(self.total),
        }


@dataclass(frozen=True)
class CBCTTValidation:
    formulation: str
    lecture_count_violations: int
    duplicate_course_period_violations: int
    conflict_violations: int
    room_occupancy_violations: int
    availability_violations: int
    hard_room_suitability_violations: int
    score: CBCTTScore

    @property
    def lecture_violations(self) -> int:
        return int(
            self.lecture_count_violations
            + self.duplicate_course_period_violations
        )

    @property
    def hard_violations(self) -> int:
        return int(
            self.lecture_violations
            + self.conflict_violations
            + self.room_occupancy_violations
            + self.availability_violations
            + self.hard_room_suitability_violations
        )

    @property
    def feasible(self) -> bool:
        return self.hard_violations == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "formulation": self.formulation,
            "semantics_id": CBCTT_NATIVE_SEMANTICS_ID,
            "lecture_count_violations": int(self.lecture_count_violations),
            "duplicate_course_period_violations": int(
                self.duplicate_course_period_violations
            ),
            "lecture_violations": self.lecture_violations,
            "conflict_violations": int(self.conflict_violations),
            "room_occupancy_violations": int(
                self.room_occupancy_violations
            ),
            "availability_violations": int(self.availability_violations),
            "hard_room_suitability_violations": int(
                self.hard_room_suitability_violations
            ),
            "hard_violations": self.hard_violations,
            "feasible": self.feasible,
            "score": self.score.to_dict(),
        }


@dataclass(frozen=True)
class CBCTTSolverEligibility:
    eligible: bool
    formulation: str
    reasons: tuple[str, ...]
    course_count: int
    lecture_count: int
    room_count: int
    period_count: int
    curriculum_count: int
    estimated_assignment_variables: int
    estimated_auxiliary_variables: int
    max_assignment_variables: int
    max_auxiliary_variables: int
    supported_semantics: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        payload["supported_semantics"] = list(self.supported_semantics)
        payload["semantics_id"] = CBCTT_NATIVE_SEMANTICS_ID
        payload["reference_doi"] = CBCTT_NATIVE_REFERENCE_DOI
        return payload


@dataclass(frozen=True)
class _EquivalentRoomGroup:
    """Physical rooms that are interchangeable in one formulation.

    The quotient is deliberately limited to formulations whose objective and
    hard constraints cannot observe physical room identity.  A selected group
    literal is lifted back to a distinct physical member after CP-SAT returns.
    """

    rooms: tuple[str, ...]
    capacity: int
    location: int
    unsuitable_courses: frozenset[str]


_FACTORIZABLE_FORMULATIONS = frozenset({"UD1", "UD3", "UD5"})


def _equivalent_room_groups(
    problem: CBCTTExtendedProblem,
    spec: CBCTTFormulation,
    *,
    factorize: bool,
) -> tuple[_EquivalentRoomGroup, ...]:
    constrained_courses: dict[str, set[str]] = defaultdict(set)
    for course_id, room_id in problem.room_constraints:
        constrained_courses[room_id].add(course_id)

    groups: dict[tuple[object, ...], list[CBCTTExtendedRoom]] = {}
    use_quotient = factorize and spec.name in _FACTORIZABLE_FORMULATIONS
    for room in problem.rooms:
        if not use_quotient:
            signature: tuple[object, ...] = ("physical", room.name)
        elif spec.name == "UD1":
            signature = ("capacity", int(room.capacity))
        elif spec.name == "UD3":
            signature = (
                "capacity_suitability",
                int(room.capacity),
                tuple(sorted(constrained_courses[room.name])),
            )
        else:
            # UD5 can observe capacity and location, but not room identity.
            signature = ("capacity_location", int(room.capacity), int(room.location))
        groups.setdefault(signature, []).append(room)

    return tuple(
        _EquivalentRoomGroup(
            rooms=tuple(sorted(room.name for room in members)),
            capacity=int(members[0].capacity),
            location=int(members[0].location),
            unsuitable_courses=frozenset(constrained_courses[members[0].name]),
        )
        for members in groups.values()
    )


@dataclass(frozen=True)
class CBCTTSolveResult:
    assignments: tuple[CBCTTAssignment, ...]
    validation: CBCTTValidation | None
    eligibility: CBCTTSolverEligibility
    status: str
    raw_status: int
    objective_value: int | None
    best_bound: float | None
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
            "eligibility": self.eligibility.to_dict(),
            "validation": (
                None if self.validation is None else self.validation.to_dict()
            ),
            "telemetry": dict(self.telemetry),
        }


def get_cbctt_formulation(name: str) -> CBCTTFormulation:
    normalized = str(name).strip().upper()
    try:
        return CBCTT_FORMULATIONS[normalized]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported CB-CTT formulation {name!r}; expected one of "
            f"{sorted(CBCTT_FORMULATIONS)}"
        ) from exc


def _check_assignment_structure(
    assignments: Sequence[CBCTTAssignment],
    problem: CBCTTExtendedProblem,
) -> tuple[CBCTTAssignment, ...]:
    courses = {course.name for course in problem.courses}
    rooms = {room.name for room in problem.rooms}
    checked: list[CBCTTAssignment] = []
    for row_number, row in enumerate(assignments, start=1):
        if not isinstance(row, CBCTTAssignment):
            raise TypeError(
                f"CB-CTT solution row {row_number} is not a CBCTTAssignment"
            )
        if row.course_id not in courses:
            raise ValueError(
                f"CB-CTT solution row {row_number} references unknown course "
                f"{row.course_id!r}"
            )
        if row.room_id not in rooms:
            raise ValueError(
                f"CB-CTT solution row {row_number} references unknown room "
                f"{row.room_id!r}"
            )
        if not 0 <= int(row.day) < int(problem.days):
            raise ValueError(
                f"CB-CTT solution row {row_number} day is outside the grid: "
                f"{row.day}"
            )
        if not 0 <= int(row.period) < int(problem.periods_per_day):
            raise ValueError(
                f"CB-CTT solution row {row_number} period is outside the grid: "
                f"{row.period}"
            )
        checked.append(
            CBCTTAssignment(
                course_id=str(row.course_id),
                room_id=str(row.room_id),
                day=int(row.day),
                period=int(row.period),
            )
        )
    return tuple(checked)


def parse_cbctt_solution(
    path: str | Path,
    *,
    problem: CBCTTExtendedProblem | None = None,
    require_complete: bool = False,
) -> tuple[CBCTTAssignment, ...]:
    """Parse the native ``Course Room Day Period`` ECTT solution format."""

    rows: list[CBCTTAssignment] = []
    for line_number, raw_line in enumerate(
        Path(path).read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 4:
            raise ValueError(
                f"Invalid CB-CTT solution row {line_number}: expected 4 fields, "
                f"got {len(fields)}"
            )
        try:
            day = int(fields[2])
            period = int(fields[3])
        except ValueError as exc:
            raise ValueError(
                f"Invalid CB-CTT solution row {line_number}: day and period "
                "must be integers"
            ) from exc
        rows.append(CBCTTAssignment(fields[0], fields[1], day, period))

    if require_complete and problem is None:
        raise ValueError("require_complete=True requires a CB-CTT problem")
    assignments = tuple(rows)
    if problem is not None:
        assignments = _check_assignment_structure(assignments, problem)
        if require_complete:
            expected = Counter(
                {course.name: int(course.lectures) for course in problem.courses}
            )
            actual = Counter(row.course_id for row in assignments)
            if actual != expected:
                details = [
                    f"{course.name}: expected {course.lectures}, "
                    f"got {actual[course.name]}"
                    for course in problem.courses
                    if actual[course.name] != int(course.lectures)
                ]
                raise ValueError(
                    "CB-CTT solution lecture count mismatch: " + "; ".join(details)
                )
    return assignments


def render_cbctt_solution(assignments: Sequence[CBCTTAssignment]) -> str:
    return "".join(
        f"{row.course_id} {row.room_id} {int(row.day)} {int(row.period)}\n"
        for row in assignments
    )


def write_cbctt_solution(
    path: str | Path, assignments: Sequence[CBCTTAssignment]
) -> None:
    Path(path).write_text(
        render_cbctt_solution(assignments),
        encoding="utf-8",
        newline="\n",
    )


def _raw_score_components(
    problem: CBCTTExtendedProblem,
    assignments: Sequence[CBCTTAssignment],
) -> dict[str, int]:
    course_by_name = {course.name: course for course in problem.courses}
    room_by_name = {room.name: room for room in problem.rooms}
    constrained_rooms = set(problem.room_constraints)

    by_course: dict[str, list[CBCTTAssignment]] = defaultdict(list)
    mutable_curricula_by_course: dict[str, list[str]] = defaultdict(list)
    for curriculum, members in problem.curricula.items():
        for course_id in members:
            mutable_curricula_by_course[course_id].append(curriculum)
    curricula_by_course: dict[str, tuple[str, ...]] = {
        course_id: tuple(curricula)
        for course_id, curricula in mutable_curricula_by_course.items()
    }
    curriculum_slots: dict[tuple[str, int, int], CBCTTAssignment] = {}
    for row in assignments:
        by_course[row.course_id].append(row)
        for curriculum in curricula_by_course.get(row.course_id, ()):
            # Hard-feasible schedules contain at most one member per slot.
            # Keeping the last row makes soft scoring total and deterministic
            # even when the caller separately inspects hard violations.
            curriculum_slots[(curriculum, row.day, row.period)] = row

    room_capacity = sum(
        max(
            0,
            int(course_by_name[row.course_id].students)
            - int(room_by_name[row.room_id].capacity),
        )
        for row in assignments
    )
    minimum_working_days = sum(
        max(
            0,
            int(course.minimum_working_days)
            - len({row.day for row in by_course.get(course.name, ())}),
        )
        for course in problem.courses
    )

    isolated_lectures = 0
    windows = 0
    student_min_max_load = 0
    travel_distance = 0
    for curriculum in problem.curricula:
        for day in range(problem.days):
            periods = sorted(
                period
                for current_curriculum, current_day, period in curriculum_slots
                if current_curriculum == curriculum and current_day == day
            )
            occupied = set(periods)
            isolated_lectures += sum(
                1
                for period in periods
                if period - 1 not in occupied and period + 1 not in occupied
            )
            if periods:
                windows += periods[-1] - periods[0] + 1 - len(periods)
                load = len(periods)
                if load < problem.minimum_daily_lectures:
                    student_min_max_load += problem.minimum_daily_lectures - load
                elif load > problem.maximum_daily_lectures:
                    student_min_max_load += load - problem.maximum_daily_lectures
            for period in range(problem.periods_per_day - 1):
                left = curriculum_slots.get((curriculum, day, period))
                right = curriculum_slots.get((curriculum, day, period + 1))
                if left is None or right is None:
                    continue
                if (
                    room_by_name[left.room_id].location
                    != room_by_name[right.room_id].location
                ):
                    travel_distance += 1

    room_stability = sum(
        max(0, len({row.room_id for row in by_course.get(course.name, ())}) - 1)
        for course in problem.courses
    )
    room_suitability = sum(
        int((row.course_id, row.room_id) in constrained_rooms)
        for row in assignments
    )

    double_lectures = 0
    for course in problem.courses:
        if not course.double_lectures:
            continue
        for day in range(problem.days):
            rows = [row for row in by_course.get(course.name, ()) if row.day == day]
            if len(rows) < 2:
                continue
            occupied_same_room = {(row.room_id, row.period) for row in rows}
            double_lectures += sum(
                1
                for row in rows
                if (row.room_id, row.period - 1) not in occupied_same_room
                and (row.room_id, row.period + 1) not in occupied_same_room
            )

    return {
        "room_capacity": int(room_capacity),
        "minimum_working_days": int(minimum_working_days),
        "isolated_lectures": int(isolated_lectures),
        "windows": int(windows),
        "room_stability": int(room_stability),
        "student_min_max_load": int(student_min_max_load),
        "travel_distance": int(travel_distance),
        "room_suitability": int(room_suitability),
        "double_lectures": int(double_lectures),
    }


def score_cbctt_assignments(
    problem: CBCTTExtendedProblem,
    assignments: Sequence[CBCTTAssignment],
    *,
    formulation: str = "UD2",
) -> CBCTTScore:
    """Compute all nine ECTT components and the selected weighted objective."""

    checked = _check_assignment_structure(assignments, problem)
    spec = get_cbctt_formulation(formulation)
    raw = _raw_score_components(problem, checked)
    total = sum(
        raw[name] * weight
        for name, weight in spec.weights().items()
        if weight is not None
    )
    return CBCTTScore(
        formulation=spec.name,
        total=int(total),
        **raw,
    )


def validate_cbctt_assignments(
    problem: CBCTTExtendedProblem,
    assignments: Sequence[CBCTTAssignment],
    *,
    formulation: str = "UD2",
) -> CBCTTValidation:
    """Independently validate hard ECTT semantics and score a solution.

    Unknown identifiers and out-of-grid rows are rejected instead of being
    dropped. Hard violations within the valid output vocabulary are reported as
    counts, matching the ECTT distinction between feasibility and weighted cost.
    """

    checked = _check_assignment_structure(assignments, problem)
    spec = get_cbctt_formulation(formulation)
    expected_counts = {
        course.name: int(course.lectures) for course in problem.courses
    }
    actual_counts = Counter(row.course_id for row in checked)
    lecture_count_violations = sum(
        abs(actual_counts[name] - expected)
        for name, expected in expected_counts.items()
    )
    duplicate_course_period_violations = sum(
        max(0, count - 1)
        for count in Counter(
            (row.course_id, row.day, row.period) for row in checked
        ).values()
    )

    course_by_name = {course.name: course for course in problem.courses}
    curricula_by_course: dict[str, set[str]] = defaultdict(set)
    for curriculum, members in problem.curricula.items():
        for course in members:
            curricula_by_course[course].add(curriculum)

    courses_by_slot: dict[tuple[int, int], set[str]] = defaultdict(set)
    rows_by_room_slot: Counter[tuple[str, int, int]] = Counter()
    for row in checked:
        courses_by_slot[(row.day, row.period)].add(row.course_id)
        rows_by_room_slot[(row.room_id, row.day, row.period)] += 1

    conflict_violations = 0
    for course_names in courses_by_slot.values():
        ordered = sorted(course_names)
        for index, left_name in enumerate(ordered):
            left = course_by_name[left_name]
            for right_name in ordered[index + 1 :]:
                right = course_by_name[right_name]
                if left.teacher == right.teacher or (
                    curricula_by_course[left_name]
                    & curricula_by_course[right_name]
                ):
                    conflict_violations += 1

    room_occupancy_violations = sum(
        max(0, count - 1) for count in rows_by_room_slot.values()
    )
    unavailable = set(problem.unavailability)
    availability_violations = sum(
        int((row.course_id, row.day, row.period) in unavailable)
        for row in checked
    )
    constrained_rooms = set(problem.room_constraints)
    hard_room_suitability_violations = (
        sum(
            int((row.course_id, row.room_id) in constrained_rooms)
            for row in checked
        )
        if spec.room_suitability_hard
        else 0
    )
    return CBCTTValidation(
        formulation=spec.name,
        lecture_count_violations=int(lecture_count_violations),
        duplicate_course_period_violations=int(
            duplicate_course_period_violations
        ),
        conflict_violations=int(conflict_violations),
        room_occupancy_violations=int(room_occupancy_violations),
        availability_violations=int(availability_violations),
        hard_room_suitability_violations=int(
            hard_room_suitability_violations
        ),
        score=score_cbctt_assignments(
            problem, checked, formulation=spec.name
        ),
    )


_SUPPORTED_SEMANTICS = (
    "hard:lectures",
    "hard:teacher_and_curriculum_conflicts",
    "hard:room_occupancy",
    "hard:availability",
    "hard:room_suitability_in_ud4",
    "soft:room_capacity",
    "soft:minimum_working_days",
    "soft:isolated_lectures",
    "soft:windows",
    "soft:room_stability",
    "soft:student_min_max_load",
    "soft:travel_distance",
    "soft:room_suitability_in_ud3",
    "soft:double_lectures",
)


def assess_cbctt_native_eligibility(
    problem: CBCTTExtendedProblem,
    *,
    formulation: str = "UD2",
    max_assignment_variables: int = 250_000,
    max_auxiliary_variables: int = 250_000,
    factorize_equivalent_rooms: bool = True,
) -> CBCTTSolverEligibility:
    """Fail-closed admission check for the exact CP-SAT formulation.

    All UD1--UD5 semantics represented by ``CBCTTExtendedProblem`` are
    supported. Admission is intentionally bounded by model scale and by cheap
    necessary feasibility checks; no claim of feasibility is made when those
    checks pass.
    """

    normalized = str(formulation).strip().upper()
    reasons: list[str] = []
    try:
        spec = get_cbctt_formulation(normalized)
    except ValueError:
        spec = None
        reasons.append(f"unsupported_formulation:{normalized}")

    if max_assignment_variables <= 0:
        reasons.append("invalid_assignment_variable_limit")
    if max_auxiliary_variables <= 0:
        reasons.append("invalid_auxiliary_variable_limit")

    unavailable: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for course, day, period in problem.unavailability:
        unavailable[course].add((day, period))

    formulation_spec = spec or CBCTT_FORMULATIONS["UD2"]
    room_groups = _equivalent_room_groups(
        problem,
        formulation_spec,
        factorize=bool(factorize_equivalent_rooms and spec is not None),
    )
    assignment_variables = 0
    for course in problem.courses:
        available_periods = (
            problem.days * problem.periods_per_day
            - len(unavailable[course])
        )
        if spec is not None and spec.room_suitability_hard:
            eligible_rooms = sum(
                int(course.name not in group.unsuitable_courses)
                for group in room_groups
            )
        else:
            eligible_rooms = len(room_groups)
        if available_periods < course.lectures:
            reasons.append(f"course_period_domain_too_small:{course.name}")
        if eligible_rooms <= 0:
            reasons.append(f"course_room_domain_empty:{course.name}")
        assignment_variables += max(0, available_periods) * max(0, eligible_rooms)

    total_periods = int(problem.days * problem.periods_per_day)
    total_lectures = sum(int(course.lectures) for course in problem.courses)
    if total_lectures > total_periods * len(problem.rooms):
        reasons.append("aggregate_room_period_capacity_insufficient")

    lectures_by_teacher: Counter[str] = Counter()
    for course in problem.courses:
        lectures_by_teacher[course.teacher] += int(course.lectures)
    for teacher, lecture_count in lectures_by_teacher.items():
        if lecture_count > total_periods:
            reasons.append(f"teacher_period_capacity_insufficient:{teacher}")
    course_by_name = {course.name: course for course in problem.courses}
    for curriculum, members in problem.curricula.items():
        lecture_count = sum(course_by_name[name].lectures for name in members)
        if lecture_count > total_periods:
            reasons.append(f"curriculum_period_capacity_insufficient:{curriculum}")

    course_time_variables = len(problem.courses) * total_periods
    auxiliary_variables = course_time_variables
    if formulation_spec.minimum_working_days is not None:
        auxiliary_variables += len(problem.courses) * (problem.days + 1)
    if formulation_spec.room_stability is not None:
        auxiliary_variables += len(problem.courses) * (len(problem.rooms) + 1)
    curriculum_slots = len(problem.curricula) * total_periods
    if any(
        value is not None
        for value in (
            formulation_spec.isolated_lectures,
            formulation_spec.windows,
            formulation_spec.student_min_max_load,
            formulation_spec.travel_distance,
        )
    ):
        auxiliary_variables += curriculum_slots
    if formulation_spec.isolated_lectures is not None:
        auxiliary_variables += curriculum_slots
    if formulation_spec.windows is not None:
        auxiliary_variables += len(problem.curricula) * problem.days * 4
    if formulation_spec.student_min_max_load is not None:
        auxiliary_variables += len(problem.curricula) * problem.days * 3
    if formulation_spec.travel_distance is not None:
        locations = len({room.location for room in problem.rooms})
        auxiliary_variables += curriculum_slots * max(1, locations)
        auxiliary_variables += (
            len(problem.curricula)
            * problem.days
            * max(0, problem.periods_per_day - 1)
            * (locations + 1)
        )
    if formulation_spec.double_lectures is not None:
        double_courses = sum(course.double_lectures for course in problem.courses)
        auxiliary_variables += double_courses * problem.days
        auxiliary_variables += (
            double_courses
            * problem.days
            * problem.periods_per_day
            * len(problem.rooms)
        )

    if assignment_variables > max_assignment_variables:
        reasons.append(
            "assignment_variable_limit_exceeded:"
            f"{assignment_variables}>{max_assignment_variables}"
        )
    if auxiliary_variables > max_auxiliary_variables:
        reasons.append(
            "auxiliary_variable_limit_exceeded:"
            f"{auxiliary_variables}>{max_auxiliary_variables}"
        )

    return CBCTTSolverEligibility(
        eligible=not reasons,
        formulation=normalized,
        reasons=tuple(dict.fromkeys(reasons)),
        course_count=len(problem.courses),
        lecture_count=total_lectures,
        room_count=len(problem.rooms),
        period_count=total_periods,
        curriculum_count=len(problem.curricula),
        estimated_assignment_variables=int(assignment_variables),
        estimated_auxiliary_variables=int(auxiliary_variables),
        max_assignment_variables=int(max_assignment_variables),
        max_auxiliary_variables=int(max_auxiliary_variables),
        supported_semantics=_SUPPORTED_SEMANTICS,
    )


class _DeadlineExpired(RuntimeError):
    pass


def _deadline_check(deadline: float, phase: str) -> None:
    if time.perf_counter() >= deadline:
        raise _DeadlineExpired(phase)


def _empty_solve_result(
    *,
    eligibility: CBCTTSolverEligibility,
    status: str,
    started: float,
    build_finished: float,
    deadline: float,
    seed: int,
    workers: int,
    telemetry: dict[str, object] | None = None,
) -> CBCTTSolveResult:
    finished = time.perf_counter()
    return CBCTTSolveResult(
        assignments=(),
        validation=None,
        eligibility=eligibility,
        status=status,
        raw_status=-1,
        objective_value=None,
        best_bound=None,
        build_seconds=max(0.0, build_finished - started),
        search_seconds=0.0,
        elapsed_seconds=max(0.0, finished - started),
        deadline_overrun_seconds=max(0.0, finished - deadline),
        seed=int(seed),
        workers=int(workers),
        telemetry={"fail_closed": True, **(telemetry or {})},
    )


def solve_cbctt_native(
    problem: CBCTTExtendedProblem,
    *,
    formulation: str = "UD2",
    time_limit_seconds: float = 10.0,
    seed: int = 0,
    workers: int = 1,
    max_assignment_variables: int = 250_000,
    max_auxiliary_variables: int = 250_000,
    cleanup_reserve_seconds: float = 0.05,
    factorize_equivalent_rooms: bool = True,
) -> CBCTTSolveResult:
    """Solve an admitted ECTT instance with an exact UD1--UD5 CP-SAT model.

    The method is intentionally bounded. Ineligible or deadline-exhausted calls
    return no assignment, never a projected or partially interpreted schedule.
    """

    if time_limit_seconds < 0:
        raise ValueError("time_limit_seconds must be non-negative")
    if workers <= 0:
        raise ValueError("workers must be positive")
    if cleanup_reserve_seconds < 0:
        raise ValueError("cleanup_reserve_seconds must be non-negative")

    started = time.perf_counter()
    deadline = started + float(time_limit_seconds)
    eligibility = assess_cbctt_native_eligibility(
        problem,
        formulation=formulation,
        max_assignment_variables=max_assignment_variables,
        max_auxiliary_variables=max_auxiliary_variables,
        factorize_equivalent_rooms=factorize_equivalent_rooms,
    )
    if not eligibility.eligible:
        now = time.perf_counter()
        return _empty_solve_result(
            eligibility=eligibility,
            status="ineligible",
            started=started,
            build_finished=now,
            deadline=deadline,
            seed=seed,
            workers=workers,
            telemetry={"phase": "admission"},
        )
    if time.perf_counter() >= deadline:
        now = time.perf_counter()
        return _empty_solve_result(
            eligibility=eligibility,
            status="deadline_before_build",
            started=started,
            build_finished=now,
            deadline=deadline,
            seed=seed,
            workers=workers,
        )

    spec = get_cbctt_formulation(formulation)
    model = cp_model.CpModel()
    room_groups = _equivalent_room_groups(
        problem,
        spec,
        factorize=bool(factorize_equivalent_rooms),
    )
    unavailable = set(problem.unavailability)
    objective_terms: list[cp_model.LinearExpr | int] = []
    placement: dict[tuple[str, int, int, int], cp_model.IntVar] = {}
    course_time: dict[tuple[str, int, int], cp_model.IntVar] = {}
    by_room_time: dict[tuple[int, int, int], list[cp_model.IntVar]] = defaultdict(list)
    by_course_room: dict[tuple[str, int], list[cp_model.IntVar]] = defaultdict(list)

    try:
        for course_index, course in enumerate(problem.courses):
            if course_index % 16 == 0:
                _deadline_check(deadline, "assignment variables")
            course_variables: list[cp_model.IntVar] = []
            for day in range(problem.days):
                for period in range(problem.periods_per_day):
                    if (course.name, day, period) in unavailable:
                        continue
                    at_time: list[cp_model.IntVar] = []
                    for group_index, room_group in enumerate(room_groups):
                        if (
                            spec.room_suitability_hard
                            and course.name in room_group.unsuitable_courses
                        ):
                            continue
                        variable = model.new_bool_var(
                            f"x_{course.name}_{day}_{period}_g{group_index}"
                        )
                        placement[(course.name, day, period, group_index)] = variable
                        course_variables.append(variable)
                        at_time.append(variable)
                        by_room_time[(group_index, day, period)].append(variable)
                        by_course_room[(course.name, group_index)].append(variable)
                        if spec.room_capacity is not None:
                            shortage = max(
                                0, course.students - room_group.capacity
                            )
                            if shortage:
                                objective_terms.append(
                                    spec.room_capacity * shortage * variable
                                )
                        if (
                            spec.room_suitability is not None
                            and course.name in room_group.unsuitable_courses
                        ):
                            objective_terms.append(
                                spec.room_suitability * variable
                            )
                    used = model.new_bool_var(
                        f"y_{course.name}_{day}_{period}"
                    )
                    model.add(used == sum(at_time))
                    course_time[(course.name, day, period)] = used
            model.add(sum(course_variables) == course.lectures)

        _deadline_check(deadline, "room occupancy constraints")
        for (group_index, _day, _period), variables in by_room_time.items():
            model.add(sum(variables) <= len(room_groups[group_index].rooms))

        courses_by_teacher: dict[str, list[str]] = defaultdict(list)
        for course in problem.courses:
            courses_by_teacher[course.teacher].append(course.name)
        for teacher_index, members in enumerate(courses_by_teacher.values()):
            if teacher_index % 16 == 0:
                _deadline_check(deadline, "teacher conflicts")
            for day in range(problem.days):
                for period in range(problem.periods_per_day):
                    variables = [
                        course_time[(course, day, period)]
                        for course in members
                        if (course, day, period) in course_time
                    ]
                    if len(variables) > 1:
                        model.add(sum(variables) <= 1)
        for curriculum_index, members in enumerate(problem.curricula.values()):
            if curriculum_index % 16 == 0:
                _deadline_check(deadline, "curriculum conflicts")
            for day in range(problem.days):
                for period in range(problem.periods_per_day):
                    variables = [
                        course_time[(course, day, period)]
                        for course in members
                        if (course, day, period) in course_time
                    ]
                    if len(variables) > 1:
                        model.add(sum(variables) <= 1)

        if spec.minimum_working_days is not None:
            for course_index, course in enumerate(problem.courses):
                if course_index % 16 == 0:
                    _deadline_check(deadline, "minimum working days")
                day_used: list[cp_model.IntVar] = []
                for day in range(problem.days):
                    variables = [
                        course_time[(course.name, day, period)]
                        for period in range(problem.periods_per_day)
                        if (course.name, day, period) in course_time
                    ]
                    if not variables:
                        continue
                    used = model.new_bool_var(f"course_day_{course.name}_{day}")
                    model.add_max_equality(used, variables)
                    day_used.append(used)
                missing = model.new_int_var(
                    0,
                    course.minimum_working_days,
                    f"missing_days_{course.name}",
                )
                model.add(
                    missing >= course.minimum_working_days - sum(day_used)
                )
                objective_terms.append(spec.minimum_working_days * missing)

        if spec.room_stability is not None:
            for course_index, course in enumerate(problem.courses):
                if course_index % 16 == 0:
                    _deadline_check(deadline, "room stability")
                room_used: list[cp_model.IntVar] = []
                for group_index, room_group in enumerate(room_groups):
                    variables = by_course_room.get((course.name, group_index), ())
                    if not variables:
                        continue
                    used = model.new_bool_var(
                        f"course_room_{course.name}_{room_group.rooms[0]}"
                    )
                    model.add_max_equality(used, variables)
                    room_used.append(used)
                extra = model.new_int_var(
                    0, max(0, len(problem.rooms) - 1), f"extra_rooms_{course.name}"
                )
                model.add(extra == sum(room_used) - 1)
                objective_terms.append(spec.room_stability * extra)

        needs_curriculum_occupancy = any(
            value is not None
            for value in (
                spec.isolated_lectures,
                spec.windows,
                spec.student_min_max_load,
                spec.travel_distance,
            )
        )
        curriculum_occupancy: dict[
            tuple[str, int, int], cp_model.IntVar | int
        ] = {}
        if needs_curriculum_occupancy:
            for curriculum_index, (curriculum, members) in enumerate(
                problem.curricula.items()
            ):
                if curriculum_index % 8 == 0:
                    _deadline_check(deadline, "curriculum occupancy")
                for day in range(problem.days):
                    for period in range(problem.periods_per_day):
                        variables = [
                            course_time[(course, day, period)]
                            for course in members
                            if (course, day, period) in course_time
                        ]
                        if not variables:
                            curriculum_occupancy[(curriculum, day, period)] = 0
                            continue
                        occupied = model.new_bool_var(
                            f"curr_{curriculum}_{day}_{period}"
                        )
                        model.add(occupied == sum(variables))
                        curriculum_occupancy[(curriculum, day, period)] = occupied

        if spec.isolated_lectures is not None:
            for curriculum_index, curriculum in enumerate(problem.curricula):
                if curriculum_index % 16 == 0:
                    _deadline_check(deadline, "isolated lectures")
                for day in range(problem.days):
                    for period in range(problem.periods_per_day):
                        occupied = curriculum_occupancy[
                            (curriculum, day, period)
                        ]
                        if isinstance(occupied, int):
                            continue
                        previous = (
                            curriculum_occupancy[(curriculum, day, period - 1)]
                            if period > 0
                            else 0
                        )
                        following = (
                            curriculum_occupancy[(curriculum, day, period + 1)]
                            if period + 1 < problem.periods_per_day
                            else 0
                        )
                        isolated = model.new_bool_var(
                            f"isolated_{curriculum}_{day}_{period}"
                        )
                        model.add(isolated <= occupied)
                        model.add(isolated <= 1 - previous)
                        model.add(isolated <= 1 - following)
                        model.add(
                            isolated >= occupied - previous - following
                        )
                        objective_terms.append(
                            spec.isolated_lectures * isolated
                        )

        if spec.windows is not None:
            for curriculum_index, curriculum in enumerate(problem.curricula):
                if curriculum_index % 16 == 0:
                    _deadline_check(deadline, "curriculum windows")
                for day in range(problem.days):
                    occupied = [
                        curriculum_occupancy[(curriculum, day, period)]
                        for period in range(problem.periods_per_day)
                    ]
                    variables = [
                        variable
                        for variable in occupied
                        if not isinstance(variable, int)
                    ]
                    if not variables:
                        continue
                    day_used = model.new_bool_var(
                        f"curr_day_{curriculum}_{day}"
                    )
                    model.add_max_equality(day_used, variables)
                    first = model.new_int_var(
                        0,
                        problem.periods_per_day - 1,
                        f"first_{curriculum}_{day}",
                    )
                    last = model.new_int_var(
                        0,
                        problem.periods_per_day - 1,
                        f"last_{curriculum}_{day}",
                    )
                    model.add(first <= (problem.periods_per_day - 1) * day_used)
                    model.add(last <= (problem.periods_per_day - 1) * day_used)
                    for period, variable in enumerate(occupied):
                        if isinstance(variable, int):
                            continue
                        model.add(
                            first
                            <= period
                            + problem.periods_per_day * (1 - variable)
                        )
                        model.add(
                            last
                            >= period
                            - problem.periods_per_day * (1 - variable)
                        )
                    window_count = model.new_int_var(
                        0,
                        problem.periods_per_day,
                        f"windows_{curriculum}_{day}",
                    )
                    model.add(
                        window_count
                        == last - first + day_used - sum(occupied)
                    )
                    objective_terms.append(spec.windows * window_count)

        if spec.student_min_max_load is not None:
            for curriculum_index, curriculum in enumerate(problem.curricula):
                if curriculum_index % 16 == 0:
                    _deadline_check(deadline, "student daily load")
                for day in range(problem.days):
                    occupied = [
                        curriculum_occupancy[(curriculum, day, period)]
                        for period in range(problem.periods_per_day)
                    ]
                    variables = [
                        variable
                        for variable in occupied
                        if not isinstance(variable, int)
                    ]
                    if not variables:
                        continue
                    day_used = model.new_bool_var(
                        f"load_day_{curriculum}_{day}"
                    )
                    model.add_max_equality(day_used, variables)
                    load = sum(occupied)
                    under = model.new_int_var(
                        0,
                        problem.minimum_daily_lectures,
                        f"under_load_{curriculum}_{day}",
                    )
                    over = model.new_int_var(
                        0,
                        problem.periods_per_day,
                        f"over_load_{curriculum}_{day}",
                    )
                    model.add(
                        under
                        >= problem.minimum_daily_lectures * day_used - load
                    )
                    model.add(over >= load - problem.maximum_daily_lectures)
                    objective_terms.append(
                        spec.student_min_max_load * under
                    )
                    objective_terms.append(
                        spec.student_min_max_load * over
                    )

        if spec.travel_distance is not None:
            groups_by_location: dict[int, tuple[int, ...]] = {}
            for location in sorted({room.location for room in room_groups}):
                groups_by_location[location] = tuple(
                    group_index
                    for group_index, room_group in enumerate(room_groups)
                    if room_group.location == location
                )
            building_occupancy: dict[
                tuple[str, int, int, int], cp_model.IntVar | int
            ] = {}
            for curriculum_index, (curriculum, members) in enumerate(
                problem.curricula.items()
            ):
                if curriculum_index % 4 == 0:
                    _deadline_check(deadline, "travel building occupancy")
                for day in range(problem.days):
                    for period in range(problem.periods_per_day):
                        for location, group_indices in groups_by_location.items():
                            variables = [
                                placement[(course, day, period, group_index)]
                                for course in members
                                for group_index in group_indices
                                if (course, day, period, group_index) in placement
                            ]
                            if not variables:
                                building_occupancy[
                                    (curriculum, day, period, location)
                                ] = 0
                                continue
                            occupied = model.new_bool_var(
                                f"building_{curriculum}_{day}_{period}_{location}"
                            )
                            model.add(occupied == sum(variables))
                            building_occupancy[
                                (curriculum, day, period, location)
                            ] = occupied
            for curriculum_index, curriculum in enumerate(problem.curricula):
                if curriculum_index % 8 == 0:
                    _deadline_check(deadline, "travel transitions")
                for day in range(problem.days):
                    for period in range(problem.periods_per_day - 1):
                        left = curriculum_occupancy[(curriculum, day, period)]
                        right = curriculum_occupancy[
                            (curriculum, day, period + 1)
                        ]
                        if isinstance(left, int) or isinstance(right, int):
                            continue
                        adjacent = model.new_bool_var(
                            f"adjacent_{curriculum}_{day}_{period}"
                        )
                        model.add(adjacent <= left)
                        model.add(adjacent <= right)
                        model.add(adjacent >= left + right - 1)
                        objective_terms.append(
                            spec.travel_distance * adjacent
                        )
                        for location in groups_by_location:
                            left_building = building_occupancy[
                                (curriculum, day, period, location)
                            ]
                            right_building = building_occupancy[
                                (curriculum, day, period + 1, location)
                            ]
                            if isinstance(left_building, int) or isinstance(
                                right_building, int
                            ):
                                continue
                            same = model.new_bool_var(
                                f"same_building_{curriculum}_{day}_{period}_{location}"
                            )
                            model.add(same <= left_building)
                            model.add(same <= right_building)
                            model.add(
                                same >= left_building + right_building - 1
                            )
                            objective_terms.append(
                                -spec.travel_distance * same
                            )

        if spec.double_lectures is not None:
            for course_index, course in enumerate(problem.courses):
                if course_index % 16 == 0:
                    _deadline_check(deadline, "double lectures")
                if not course.double_lectures:
                    continue
                for day in range(problem.days):
                    times = [
                        course_time[(course.name, day, period)]
                        for period in range(problem.periods_per_day)
                        if (course.name, day, period) in course_time
                    ]
                    if not times:
                        continue
                    multiple = model.new_bool_var(
                        f"multiple_{course.name}_{day}"
                    )
                    model.add(sum(times) >= 2).only_enforce_if(multiple)
                    model.add(sum(times) <= 1).only_enforce_if(multiple.Not())
                    for period in range(problem.periods_per_day):
                        for group_index, room_group in enumerate(room_groups):
                            variable = placement.get(
                                (course.name, day, period, group_index)
                            )
                            if variable is None:
                                continue
                            previous = placement.get(
                                (course.name, day, period - 1, group_index), 0
                            )
                            following = placement.get(
                                (course.name, day, period + 1, group_index), 0
                            )
                            ungrouped = model.new_bool_var(
                                "ungrouped_"
                                f"{course.name}_{day}_{period}_{room_group.rooms[0]}"
                            )
                            model.add(ungrouped <= variable)
                            model.add(ungrouped <= multiple)
                            model.add(ungrouped <= 1 - previous)
                            model.add(ungrouped <= 1 - following)
                            model.add(
                                ungrouped
                                >= variable
                                + multiple
                                - previous
                                - following
                                - 1
                            )
                            objective_terms.append(
                                spec.double_lectures * ungrouped
                            )

        model.minimize(sum(objective_terms))
    except _DeadlineExpired as exc:
        now = time.perf_counter()
        return _empty_solve_result(
            eligibility=eligibility,
            status="deadline_during_build",
            started=started,
            build_finished=now,
            deadline=deadline,
            seed=seed,
            workers=workers,
            telemetry={"phase": str(exc)},
        )

    build_finished = time.perf_counter()
    reserve = max(
        float(cleanup_reserve_seconds),
        min(0.5, max(0.01, 0.05 * float(time_limit_seconds))),
    )
    remaining = deadline - build_finished - reserve
    if remaining <= 0:
        return _empty_solve_result(
            eligibility=eligibility,
            status="deadline_before_search",
            started=started,
            build_finished=build_finished,
            deadline=deadline,
            seed=seed,
            workers=workers,
            telemetry={"cleanup_reserve_seconds": reserve},
        )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.001, remaining)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.random_seed = int(seed)
    raw_status = int(solver.solve(model))
    search_finished = time.perf_counter()

    assignments: tuple[CBCTTAssignment, ...] = ()
    validation: CBCTTValidation | None = None
    objective_value: int | None = None
    if raw_status in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}:
        selected_by_group_slot: dict[
            tuple[int, int, int], list[str]
        ] = defaultdict(list)
        for (course, day, period, group_index), variable in placement.items():
            if solver.value(variable):
                selected_by_group_slot[(day, period, group_index)].append(course)
        lifted: list[CBCTTAssignment] = []
        for (day, period, group_index), courses in sorted(
            selected_by_group_slot.items()
        ):
            physical_rooms = room_groups[group_index].rooms
            if len(courses) > len(physical_rooms):
                # The corresponding group-capacity constraint makes this
                # unreachable; refusing the candidate keeps extraction closed
                # if the solver/model API ever violates that invariant.
                courses = []
                lifted = []
                break
            lifted.extend(
                CBCTTAssignment(course, room, day, period)
                for course, room in zip(sorted(courses), physical_rooms, strict=False)
            )
        assignments = tuple(lifted)
        validation = validate_cbctt_assignments(
            problem, assignments, formulation=spec.name
        )
        objective_value = int(round(solver.objective_value))

    best_bound: float | None = None
    if raw_status != int(cp_model.MODEL_INVALID):
        try:
            best_bound = float(solver.best_objective_bound)
        except (AttributeError, OverflowError, ValueError):
            best_bound = None

    status = cp_model.CpSolverStatus(raw_status).name.lower()
    if validation is not None and not validation.feasible:
        status = "invalid_returned_solution"
    if (
        validation is not None
        and objective_value is not None
        and objective_value != validation.score.total
    ):
        status = "objective_mismatch"
    finished = time.perf_counter()
    return CBCTTSolveResult(
        assignments=assignments,
        validation=validation,
        eligibility=eligibility,
        status=status,
        raw_status=raw_status,
        objective_value=objective_value,
        best_bound=best_bound,
        build_seconds=max(0.0, build_finished - started),
        search_seconds=max(0.0, search_finished - build_finished),
        elapsed_seconds=max(0.0, finished - started),
        deadline_overrun_seconds=max(0.0, finished - deadline),
        seed=int(seed),
        workers=int(workers),
        telemetry={
            "assignment_variables": len(placement),
            "physical_rooms": len(problem.rooms),
            "room_groups": len(room_groups),
            "room_factorization": bool(
                factorize_equivalent_rooms
                and spec.name in _FACTORIZABLE_FORMULATIONS
            ),
            "objective_terms": len(objective_terms),
            "cleanup_reserve_seconds": reserve,
            "conflicts": int(solver.num_conflicts),
            "branches": int(solver.num_branches),
            "fail_closed": not bool(assignments),
            "objective_parity": (
                None
                if validation is None or objective_value is None
                else objective_value == validation.score.total
            ),
        },
    )


__all__ = [
    "CBCTTAssignment",
    "CBCTTFormulation",
    "CBCTTScore",
    "CBCTTSolveResult",
    "CBCTTSolverEligibility",
    "CBCTTValidation",
    "CBCTT_FORMULATIONS",
    "CBCTT_NATIVE_REFERENCE_DOI",
    "CBCTT_NATIVE_SEMANTICS_ID",
    "assess_cbctt_native_eligibility",
    "get_cbctt_formulation",
    "parse_cbctt_solution",
    "render_cbctt_solution",
    "score_cbctt_assignments",
    "solve_cbctt_native",
    "validate_cbctt_assignments",
    "write_cbctt_solution",
]
