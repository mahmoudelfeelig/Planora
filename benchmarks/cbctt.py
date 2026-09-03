from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from benchmarks.itc2007 import ITC2007Course, ITC2007Problem, ITC2007Room


CBCTT_ARCHIVE_ORIGIN = "https://bitbucket.org/satt/public-cb-ctt"
CBCTT_ARCHIVE_REVISION = "ea30189c5e3a670bc5d27920606d1bd8f820adec"
CBCTT_ARCHIVE_REVISION_SWHID = f"swh:1:rev:{CBCTT_ARCHIVE_REVISION}"
CBCTT_ARCHIVE_DIRECTORY_SWHID = "swh:1:dir:befbaef87d7a3bb00d387075515e26be47b95ead"
CBCTT_INSTANCES_DIRECTORY_SWHID = "swh:1:dir:5df6e8cb61b9b05a3323ab75f48aa9c323178072"
CBCTT_ITC2007_PROJECTION_ID = "ectt_to_itc2007_four_term_projection_v1"

_ECTT_METADATA_FIELDS = {
    "name",
    "courses",
    "rooms",
    "days",
    "periods_per_day",
    "curricula",
    "min_max_daily_lectures",
    "unavailabilityconstraints",
    "roomconstraints",
}
_ECTT_SECTIONS = {
    "COURSES",
    "ROOMS",
    "CURRICULA",
    "UNAVAILABILITY_CONSTRAINTS",
    "ROOM_CONSTRAINTS",
}


@dataclass(frozen=True)
class CBCTTExtendedCourse:
    name: str
    teacher: str
    lectures: int
    minimum_working_days: int
    students: int
    double_lectures: bool


@dataclass(frozen=True)
class CBCTTExtendedRoom:
    name: str
    capacity: int
    location: int


@dataclass(frozen=True)
class CBCTTExtendedProblem:
    name: str
    days: int
    periods_per_day: int
    minimum_daily_lectures: int
    maximum_daily_lectures: int
    courses: tuple[CBCTTExtendedCourse, ...]
    rooms: tuple[CBCTTExtendedRoom, ...]
    curricula: dict[str, tuple[str, ...]]
    unavailability: tuple[tuple[str, int, int], ...]
    room_constraints: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class CBCTTExtensionLosses:
    """ECTT semantics deliberately excluded from the four-term projection."""

    double_lecture_course_preferences: int
    room_location_attributes: int
    nonzero_room_locations: int
    course_room_constraint_rows: int
    daily_load_bound_values: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)

    @property
    def excluded_semantic_records(self) -> int:
        return int(
            self.double_lecture_course_preferences
            + self.room_location_attributes
            + self.course_room_constraint_rows
            + self.daily_load_bound_values
        )


@dataclass(frozen=True)
class CBCTTITC2007Projection:
    """A deliberately lossy projection onto standard ITC-2007 semantics.

    The projected problem retains the official four soft terms: room capacity,
    minimum working days, curriculum compactness, and room stability. ECTT-only
    semantics are not silently treated as equivalent; every excluded category
    is recorded in ``extension_losses``.
    """

    problem: ITC2007Problem
    source_format: str
    projection_id: str
    extension_losses: CBCTTExtensionLosses

    def to_dict(self) -> dict[str, object]:
        return {
            "projection_id": self.projection_id,
            "projection_kind": "lossy_four_term_projection",
            "source_format": self.source_format,
            "retained_itc2007_soft_terms": [
                "room_capacity",
                "minimum_working_days",
                "curriculum_compactness",
                "room_stability",
            ],
            "extension_losses": self.extension_losses.to_dict(),
            "excluded_semantic_records": (
                self.extension_losses.excluded_semantic_records
            ),
        }


def _parse_int(value: str, *, context: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"ECTT {context} must be an integer: {value!r}") from exc


def _read_sections(path: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    metadata: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    current: str | None = None
    saw_end = False

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if saw_end:
            raise ValueError(
                f"Unexpected ECTT content after END at line {line_number}: {line}"
            )

        token = line.rstrip(":").upper()
        if token in _ECTT_SECTIONS:
            if token in sections:
                raise ValueError(
                    f"Duplicate ECTT section {token} at line {line_number}"
                )
            current = token
            sections[current] = []
            continue
        if token.rstrip(".") == "END":
            saw_end = True
            current = None
            continue
        if current is not None:
            sections[current].append(line)
            continue
        if ":" not in line:
            raise ValueError(
                f"Unexpected ECTT row outside a section at line {line_number}: {line}"
            )
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower()
        if normalized_key in metadata:
            raise ValueError(
                f"Duplicate ECTT metadata field {normalized_key} at line {line_number}"
            )
        if not value.strip():
            raise ValueError(
                f"ECTT metadata field {normalized_key} is empty at line {line_number}"
            )
        metadata[normalized_key] = value.strip()

    if not saw_end:
        raise ValueError("ECTT input is missing the END marker")
    unknown_metadata = sorted(set(metadata) - _ECTT_METADATA_FIELDS)
    if unknown_metadata:
        raise ValueError(f"Unsupported ECTT metadata fields: {unknown_metadata}")
    missing_sections = sorted(_ECTT_SECTIONS - set(sections))
    if missing_sections:
        raise ValueError(f"Missing ECTT sections: {missing_sections}")
    return metadata, sections


def parse_cbctt_ectt(path: str | Path) -> CBCTTExtendedProblem:
    """Parse and semantically validate a public-corpus ECTT instance."""

    source = Path(path)
    metadata, sections = _read_sections(source)

    def required_text(key: str) -> str:
        if key not in metadata:
            raise ValueError(f"Missing ECTT metadata field: {key}")
        return metadata[key]

    def required_int(key: str) -> int:
        return _parse_int(required_text(key), context=f"metadata field {key}")

    name = required_text("name")
    days = required_int("days")
    periods_per_day = required_int("periods_per_day")
    if days <= 0 or periods_per_day <= 0:
        raise ValueError("ECTT days and periods_per_day must be positive")

    daily_fields = required_text("min_max_daily_lectures").split()
    if len(daily_fields) != 2:
        raise ValueError("ECTT Min_Max_Daily_Lectures must contain two integers")
    minimum_daily, maximum_daily = (
        _parse_int(value, context="daily lecture bound") for value in daily_fields
    )
    if minimum_daily < 0 or maximum_daily < minimum_daily:
        raise ValueError("ECTT daily lecture bounds are invalid")
    if maximum_daily > periods_per_day:
        raise ValueError(
            "ECTT maximum daily lectures exceed the declared periods per day"
        )

    courses: list[CBCTTExtendedCourse] = []
    for line in sections["COURSES"]:
        fields = line.split()
        if len(fields) != 6:
            raise ValueError(f"Invalid ECTT course row: {line}")
        lectures = _parse_int(fields[2], context=f"course {fields[0]} lectures")
        minimum_working_days = _parse_int(
            fields[3], context=f"course {fields[0]} minimum working days"
        )
        students = _parse_int(fields[4], context=f"course {fields[0]} students")
        double_lectures = _parse_int(
            fields[5], context=f"course {fields[0]} double-lecture flag"
        )
        if lectures <= 0:
            raise ValueError(f"ECTT course lectures must be positive: {line}")
        # Authentic EasyAcademy rows may deliberately request more working
        # days than a course has lectures. That is a soft-cost input, not a
        # malformed hard domain, and the standard scorer must retain it.
        if minimum_working_days < 0:
            raise ValueError(f"ECTT course minimum working days are invalid: {line}")
        if students < 0:
            raise ValueError(f"ECTT course students must be non-negative: {line}")
        if double_lectures not in {0, 1}:
            raise ValueError(f"ECTT double-lecture flag must be 0 or 1: {line}")
        courses.append(
            CBCTTExtendedCourse(
                name=fields[0],
                teacher=fields[1],
                lectures=lectures,
                minimum_working_days=minimum_working_days,
                students=students,
                double_lectures=bool(double_lectures),
            )
        )

    rooms: list[CBCTTExtendedRoom] = []
    for line in sections["ROOMS"]:
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(f"Invalid ECTT room row: {line}")
        capacity = _parse_int(fields[1], context=f"room {fields[0]} capacity")
        location = _parse_int(fields[2], context=f"room {fields[0]} location")
        if capacity < 0:
            raise ValueError(f"ECTT room capacity must be non-negative: {line}")
        if location < 0:
            raise ValueError(f"ECTT room location must be non-negative: {line}")
        rooms.append(
            CBCTTExtendedRoom(
                name=fields[0],
                capacity=capacity,
                location=location,
            )
        )

    curricula: dict[str, tuple[str, ...]] = {}
    for line in sections["CURRICULA"]:
        fields = line.split()
        if len(fields) < 2:
            raise ValueError(f"Invalid ECTT curriculum row: {line}")
        declared = _parse_int(fields[1], context=f"curriculum {fields[0]} member count")
        members = tuple(fields[2:])
        if declared < 0 or len(members) != declared:
            raise ValueError(
                f"ECTT curriculum {fields[0]} declares {declared} courses "
                f"but lists {len(members)}"
            )
        if len(set(members)) != len(members):
            raise ValueError(f"ECTT curriculum {fields[0]} repeats a course")
        if fields[0] in curricula:
            raise ValueError(f"Duplicate ECTT curriculum: {fields[0]}")
        curricula[fields[0]] = members

    unavailability: list[tuple[str, int, int]] = []
    for line in sections["UNAVAILABILITY_CONSTRAINTS"]:
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(f"Invalid ECTT unavailability row: {line}")
        unavailability.append(
            (
                fields[0],
                _parse_int(fields[1], context=f"unavailability day in {line}"),
                _parse_int(fields[2], context=f"unavailability period in {line}"),
            )
        )

    room_constraints: list[tuple[str, str]] = []
    for line in sections["ROOM_CONSTRAINTS"]:
        fields = line.split()
        if len(fields) != 2:
            raise ValueError(f"Invalid ECTT room-constraint row: {line}")
        room_constraints.append((fields[0], fields[1]))

    expected_counts = {
        "courses": len(courses),
        "rooms": len(rooms),
        "curricula": len(curricula),
        "unavailabilityconstraints": len(unavailability),
        "roomconstraints": len(room_constraints),
    }
    for key, actual in expected_counts.items():
        declared = required_int(key)
        if declared < 0 or declared != actual:
            raise ValueError(
                f"ECTT {key} count mismatch: header={declared}, parsed={actual}"
            )
    if not courses:
        raise ValueError("ECTT input must contain at least one course")
    if not rooms:
        raise ValueError("ECTT input must contain at least one room")

    course_names = {course.name for course in courses}
    room_names = {room.name for room in rooms}
    if len(course_names) != len(courses):
        raise ValueError("ECTT course identifiers must be unique")
    if len(room_names) != len(rooms):
        raise ValueError("ECTT room identifiers must be unique")
    for curriculum, members in curricula.items():
        unknown = sorted(set(members) - course_names)
        if unknown:
            raise ValueError(
                f"ECTT curriculum {curriculum} references unknown courses: {unknown}"
            )
    for course_name, day, period in unavailability:
        if course_name not in course_names:
            raise ValueError(
                f"ECTT unavailability references unknown course {course_name}"
            )
        if not 0 <= day < days or not 0 <= period < periods_per_day:
            raise ValueError(
                "ECTT unavailability is outside the declared grid: "
                f"{(course_name, day, period)}"
            )
    for course_name, room_name in room_constraints:
        if course_name not in course_names or room_name not in room_names:
            raise ValueError(
                "ECTT room constraint references an unknown course or room: "
                f"{(course_name, room_name)}"
            )

    return CBCTTExtendedProblem(
        name=name,
        days=days,
        periods_per_day=periods_per_day,
        minimum_daily_lectures=minimum_daily,
        maximum_daily_lectures=maximum_daily,
        courses=tuple(courses),
        rooms=tuple(rooms),
        curricula=curricula,
        unavailability=tuple(unavailability),
        room_constraints=tuple(room_constraints),
    )


def project_cbctt_to_itc2007(
    problem: CBCTTExtendedProblem,
) -> CBCTTITC2007Projection:
    """Project ECTT onto the standard ITC-2007 four-term formulation.

    The result is intentionally scoped to ITC-2007. It must not be used as an
    ECTT score or as evidence that a schedule satisfies the excluded extension
    semantics.
    """

    projected = ITC2007Problem(
        name=problem.name,
        days=int(problem.days),
        periods_per_day=int(problem.periods_per_day),
        courses=tuple(
            ITC2007Course(
                name=course.name,
                teacher=course.teacher,
                lectures=int(course.lectures),
                minimum_working_days=int(course.minimum_working_days),
                students=int(course.students),
            )
            for course in problem.courses
        ),
        rooms=tuple(
            ITC2007Room(name=room.name, capacity=int(room.capacity))
            for room in problem.rooms
        ),
        curricula=dict(problem.curricula),
        unavailability=tuple(problem.unavailability),
    )
    return CBCTTITC2007Projection(
        problem=projected,
        source_format="CB-CTT ECTT",
        projection_id=CBCTT_ITC2007_PROJECTION_ID,
        extension_losses=CBCTTExtensionLosses(
            double_lecture_course_preferences=sum(
                int(course.double_lectures) for course in problem.courses
            ),
            room_location_attributes=len(problem.rooms),
            nonzero_room_locations=sum(
                int(room.location != 0) for room in problem.rooms
            ),
            course_room_constraint_rows=len(problem.room_constraints),
            daily_load_bound_values=2,
        ),
    )


def render_projected_itc2007_ctt(projection: CBCTTITC2007Projection) -> str:
    """Render the standard CTT input accepted by the ITC-2007 validator."""

    problem = projection.problem
    rows = [
        f"Name: {problem.name}",
        f"Courses: {len(problem.courses)}",
        f"Rooms: {len(problem.rooms)}",
        f"Days: {problem.days}",
        f"Periods_per_day: {problem.periods_per_day}",
        f"Curricula: {len(problem.curricula)}",
        f"Constraints: {len(problem.unavailability)}",
        "",
        "COURSES:",
    ]
    rows.extend(
        f"{course.name} {course.teacher} {course.lectures} "
        f"{course.minimum_working_days} {course.students}"
        for course in problem.courses
    )
    rows.extend(("", "ROOMS:"))
    rows.extend(f"{room.name} {room.capacity}" for room in problem.rooms)
    rows.extend(("", "CURRICULA:"))
    rows.extend(
        f"{name} {len(members)}{' ' if members else ''}{' '.join(members)}"
        for name, members in problem.curricula.items()
    )
    rows.extend(("", "UNAVAILABILITY_CONSTRAINTS:"))
    rows.extend(
        f"{course_name} {day} {period}"
        for course_name, day, period in problem.unavailability
    )
    rows.extend(("", "END.", ""))
    return "\n".join(rows)


def write_projected_itc2007_ctt(
    path: str | Path,
    projection: CBCTTITC2007Projection,
) -> None:
    """Write a projected standard CTT file for the official validator."""

    Path(path).write_text(
        render_projected_itc2007_ctt(projection),
        encoding="utf-8",
        newline="\n",
    )
