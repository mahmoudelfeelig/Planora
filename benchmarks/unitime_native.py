"""Native, fail-closed adapters for public UniTime XML benchmark formats.

This module deliberately keeps its objective separate from UniTime/CPSolver's
version- and configuration-dependent objective.  It parses the stable research
formats documented by UniTime (course timetabling 2.1--2.4, examination
timetabling 1.0, and student sectioning 1.0), validates a useful exact subset,
and exposes a bounded CP-SAT reference solver for small instances.

Unsupported semantics are retained as named capabilities and make validation
fail closed.  A locally computed ``planora-unitime-native-v1`` score must never
be presented as an official UniTime score.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from itertools import combinations, product
from pathlib import Path
import math
import re
import time
from typing import Iterable, Literal, Mapping, Sequence, TypeAlias

from lxml import etree
from ortools.sat.python import cp_model


UniTimeKind = Literal["course", "exam", "sectioning"]
AttributePairs: TypeAlias = tuple[tuple[str, str], ...]

_COURSE_VERSIONS = frozenset({"2.1", "2.2", "2.3", "2.4"})
_EXAM_VERSIONS = frozenset({"1.0"})
_SECTIONING_VERSIONS = frozenset({"1.0"})
_COURSE_SUPPORTED_CONSTRAINTS = frozenset(
    {
        "DIFF_TIME",
        "SAME_DAYS",
        "SAME_ROOM",
        "SAME_START",
        "SAME_TIME",
    }
)
_EXAM_SUPPORTED_CONSTRAINTS = frozenset(
    {"same-room", "different-room", "same-period", "different-period", "precedence"}
)
_BINARY_MASK = re.compile(r"^[01]+$")


def _local_name(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _children(element: etree._Element, name: str) -> list[etree._Element]:
    return [child for child in element if _local_name(child.tag) == name]


def _child(element: etree._Element, name: str) -> etree._Element | None:
    matches = _children(element, name)
    if len(matches) > 1:
        raise ValueError(f"UniTime <{_local_name(element.tag)}> has duplicate <{name}> blocks")
    return matches[0] if matches else None


def _required(element: etree._Element, name: str) -> str:
    value = element.get(name)
    if value is None or not value.strip():
        raise ValueError(
            f"UniTime <{_local_name(element.tag)}> is missing required attribute {name!r}"
        )
    return value.strip()


def _integer(
    element: etree._Element,
    name: str,
    *,
    default: int | None = None,
    minimum: int | None = None,
) -> int:
    raw = element.get(name)
    if raw is None:
        if default is None:
            _required(element, name)
        value = int(default)
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(
                f"UniTime <{_local_name(element.tag)}> attribute {name!r} must be an integer"
            ) from exc
    if minimum is not None and value < minimum:
        raise ValueError(
            f"UniTime <{_local_name(element.tag)}> attribute {name!r} must be >= {minimum}"
        )
    return value


def _number(
    element: etree._Element,
    name: str,
    *,
    default: float | None = None,
) -> float:
    raw = element.get(name)
    if raw is None:
        if default is None:
            _required(element, name)
        return float(default)
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(
            f"UniTime <{_local_name(element.tag)}> attribute {name!r} must be numeric"
        ) from exc
    if not math.isfinite(value):
        raise ValueError(
            f"UniTime <{_local_name(element.tag)}> attribute {name!r} must be finite"
        )
    return value


def _boolean(element: etree._Element, name: str, *, default: bool = False) -> bool:
    raw = element.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ValueError(
        f"UniTime <{_local_name(element.tag)}> attribute {name!r} must be true or false"
    )


def _extra_attributes(element: etree._Element, known: Iterable[str]) -> AttributePairs:
    accepted = set(known)
    return tuple(sorted((str(k), str(v)) for k, v in element.attrib.items() if k not in accepted))


def _unique_ids(items: Sequence[object], *, label: str) -> None:
    ids = [str(getattr(item, "id")) for item in items]
    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"UniTime {label} contain duplicate ids: {', '.join(duplicates)}")


def _validate_mask(value: str, *, field_name: str, length: int | None = None) -> str:
    if not value or _BINARY_MASK.fullmatch(value) is None:
        raise ValueError(f"UniTime {field_name} must be a non-empty binary mask")
    if length is not None and len(value) != length:
        raise ValueError(f"UniTime {field_name} must contain exactly {length} bits")
    return value


def _secure_xml_root(path: str | Path) -> tuple[Path, etree._Element]:
    source = Path(path)
    tail = b""
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            combined = tail + chunk
            if b"<!ENTITY" in combined.upper():
                raise ValueError("UniTime XML entity declarations are not accepted")
            tail = combined[-16:]
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        recover=False,
        huge_tree=False,
        remove_comments=False,
    )
    try:
        root = etree.parse(str(source), parser=parser).getroot()
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"Invalid UniTime XML: {exc}") from exc
    return source, root


@dataclass(frozen=True)
class UniTimeRoom:
    id: str
    capacity: int
    alternate_capacity: int | None = None
    constrained: bool = True
    location: tuple[float, float] | None = None
    period_penalties: tuple[tuple[str, float], ...] = ()
    unavailable_periods: tuple[str, ...] = ()
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class UniTimeTime:
    id: str
    days: str
    start: int
    length: int
    dates: str = "1"
    break_time: int = 0
    penalty: float = 0.0


@dataclass(frozen=True)
class UniTimeRoomOption:
    room_id: str
    penalty: float = 0.0
    max_penalty: float | None = None


@dataclass(frozen=True)
class UniTimeCourseClass:
    id: str
    offering_id: str
    config_id: str
    subpart_id: str
    committed: bool
    class_limit: int
    minimum_limit: int
    maximum_limit: int
    room_to_limit_ratio: float
    rooms_required: int
    instructor_ids: tuple[str, ...]
    time_options: tuple[UniTimeTime, ...]
    room_options: tuple[UniTimeRoomOption, ...]
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class UniTimeCourseConstraint:
    id: str
    type: str
    preference: str
    class_ids: tuple[str, ...]
    required: bool
    prohibited: bool
    weight: float
    supported: bool


@dataclass(frozen=True)
class UniTimeCourseStudent:
    id: str
    offering_weights: tuple[tuple[str, float], ...]
    class_ids: tuple[str, ...]
    prohibited_class_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class UniTimeCourseProblem:
    kind: Literal["course"]
    name: str
    version: str
    nr_days: int
    slots_per_day: int
    rooms: tuple[UniTimeRoom, ...]
    classes: tuple[UniTimeCourseClass, ...]
    constraints: tuple[UniTimeCourseConstraint, ...]
    students: tuple[UniTimeCourseStudent, ...]
    unsupported_features: tuple[str, ...]
    embedded_solution: UniTimeSolution | None
    source_path: str
    metadata: AttributePairs = ()


@dataclass(frozen=True)
class UniTimeExamPeriod:
    id: str
    length: int
    day: str
    time_label: str
    penalty: float
    index: int


@dataclass(frozen=True)
class UniTimeExam:
    id: str
    length: int
    alternate_seating: bool
    minimum_size: int
    maximum_rooms: int
    declared_size: int | None
    average_period: float | None
    period_options: tuple[tuple[str, float | None], ...]
    room_options: tuple[UniTimeRoomOption, ...]
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class UniTimeExamPerson:
    id: str
    exam_ids: tuple[str, ...]
    unavailable_period_ids: tuple[str, ...]


@dataclass(frozen=True)
class UniTimeExamConstraint:
    id: str
    type: str
    exam_ids: tuple[str, ...]
    required: bool
    weight: float
    supported: bool


@dataclass(frozen=True)
class UniTimeExamProblem:
    kind: Literal["exam"]
    name: str
    version: str
    periods: tuple[UniTimeExamPeriod, ...]
    rooms: tuple[UniTimeRoom, ...]
    exams: tuple[UniTimeExam, ...]
    students: tuple[UniTimeExamPerson, ...]
    instructors: tuple[UniTimeExamPerson, ...]
    constraints: tuple[UniTimeExamConstraint, ...]
    parameters: tuple[tuple[str, str], ...]
    unsupported_features: tuple[str, ...]
    embedded_solution: UniTimeSolution | None
    source_path: str
    metadata: AttributePairs = ()


@dataclass(frozen=True)
class UniTimeSection:
    id: str
    subpart_id: str
    config_id: str
    offering_id: str
    limit: float
    parent_id: str | None
    time: UniTimeTime | None
    room_ids: tuple[str, ...]
    instructor_ids: tuple[str, ...] = ()
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class UniTimeSubpart:
    id: str
    parent_id: str | None
    sections: tuple[UniTimeSection, ...]


@dataclass(frozen=True)
class UniTimeConfiguration:
    id: str
    limit: float
    subparts: tuple[UniTimeSubpart, ...]


@dataclass(frozen=True)
class UniTimeOffering:
    id: str
    course_ids: tuple[str, ...]
    configurations: tuple[UniTimeConfiguration, ...]


@dataclass(frozen=True)
class UniTimeSectioningRequest:
    id: str
    kind: Literal["course", "free_time"]
    priority: int
    weight: float
    course_id: str | None = None
    alternative_course_ids: tuple[str, ...] = ()
    alternative_request: bool = False
    waitlist: bool = False
    free_time: UniTimeTime | None = None


@dataclass(frozen=True)
class UniTimeSectioningStudent:
    id: str
    dummy: bool
    requests: tuple[UniTimeSectioningRequest, ...]


@dataclass(frozen=True)
class UniTimeSectioningProblem:
    kind: Literal["sectioning"]
    name: str
    version: str
    nr_days: int
    slots_per_day: int
    offerings: tuple[UniTimeOffering, ...]
    students: tuple[UniTimeSectioningStudent, ...]
    unsupported_features: tuple[str, ...]
    embedded_solution: UniTimeSolution | None
    source_path: str
    metadata: AttributePairs = ()

    @property
    def sections(self) -> tuple[UniTimeSection, ...]:
        return tuple(
            section
            for offering in self.offerings
            for config in offering.configurations
            for subpart in config.subparts
            for section in subpart.sections
        )


UniTimeProblem: TypeAlias = UniTimeCourseProblem | UniTimeExamProblem | UniTimeSectioningProblem


@dataclass(frozen=True)
class UniTimeAssignment:
    item_id: str
    assigned: bool = True
    time_id: str | None = None
    room_ids: tuple[str, ...] = ()
    section_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class UniTimeSolution:
    kind: UniTimeKind
    assignments: tuple[UniTimeAssignment, ...]
    metadata: AttributePairs = ()

    def by_item(self) -> dict[str, UniTimeAssignment]:
        return {assignment.item_id: assignment for assignment in self.assignments}


@dataclass(frozen=True)
class UniTimeNativeScore:
    hard_violations: int
    components: tuple[tuple[str, float], ...]
    native_total: float
    scheme: str = "planora-unitime-native-v1"
    official_total: None = None
    officially_comparable: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "hard_violations": self.hard_violations,
            "components": dict(self.components),
            "native_total": self.native_total,
            "scheme": self.scheme,
            "official_total": None,
            "officially_comparable": False,
        }


@dataclass(frozen=True)
class UniTimeValidation:
    score: UniTimeNativeScore
    errors: tuple[str, ...] = ()
    unsupported_features: tuple[str, ...] = ()

    @property
    def native_feasible(self) -> bool:
        return not self.errors

    @property
    def supported(self) -> bool:
        return not self.unsupported_features

    @property
    def feasible(self) -> bool:
        return self.native_feasible and self.supported

    def to_dict(self) -> dict[str, object]:
        return {
            "feasible": self.feasible,
            "native_feasible": self.native_feasible,
            "supported": self.supported,
            "errors": list(self.errors),
            "unsupported_features": list(self.unsupported_features),
            "score": self.score.to_dict(),
        }


@dataclass(frozen=True)
class UniTimeNativeSolveResult:
    status: str
    solution: UniTimeSolution
    validation: UniTimeValidation
    objective_value: float | None
    best_bound: float | None
    elapsed_seconds: float
    model_build_seconds: float
    solver_wall_time_seconds: float
    deadline_overrun_seconds: float
    seed: int
    workers: int
    telemetry: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["validation"] = self.validation.to_dict()
        return payload


def _parse_location(raw: str | None, *, owner: str) -> tuple[float, float] | None:
    if raw is None:
        return None
    parts = raw.split(",")
    if len(parts) != 2:
        raise ValueError(f"UniTime {owner} location must contain two comma-separated numbers")
    try:
        location = (float(parts[0]), float(parts[1]))
    except ValueError as exc:
        raise ValueError(f"UniTime {owner} location is not numeric") from exc
    if not all(math.isfinite(value) for value in location):
        raise ValueError(f"UniTime {owner} location must be finite")
    return location


def _parse_common_room(element: etree._Element, *, exam: bool) -> UniTimeRoom:
    identifier = _required(element, "id")
    capacity_name = "size" if exam else "capacity"
    capacity = _integer(element, capacity_name, minimum=0)
    penalties: list[tuple[str, float]] = []
    unavailable: list[str] = []
    for child in element:
        tag = _local_name(child.tag)
        if tag == "period" and exam:
            period_id = _required(child, "id")
            if not _boolean(child, "available", default=True):
                unavailable.append(period_id)
            if child.get("penalty") is not None:
                penalties.append((period_id, _number(child, "penalty")))
    return UniTimeRoom(
        id=identifier,
        capacity=capacity,
        alternate_capacity=_integer(element, "alt", minimum=0) if exam and element.get("alt") else None,
        constrained=_boolean(element, "constraint", default=True) if not exam else True,
        location=_parse_location(
            element.get("coordinates") if exam else element.get("location"),
            owner=f"room {identifier}",
        ),
        period_penalties=tuple(penalties),
        unavailable_periods=tuple(unavailable),
        extra_attributes=_extra_attributes(
            element,
            {"id", capacity_name, "alt", "constraint", "location", "coordinates", "discouraged", "ignoreTooFar", "name", "building"},
        ),
    )


def _preference(raw: str) -> tuple[bool, bool, float]:
    normalized = raw.strip().upper()
    if normalized == "R":
        return True, False, 0.0
    if normalized == "P":
        return True, True, 0.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"Unknown UniTime preference code {raw!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"UniTime preference {raw!r} must be finite")
    return False, False, abs(value)


def parse_unitime_course_xml(path: str | Path) -> UniTimeCourseProblem:
    source, root = _secure_xml_root(path)
    if _local_name(root.tag) != "timetable":
        raise ValueError("UniTime course XML root must be <timetable>")
    version = _required(root, "version")
    if version not in _COURSE_VERSIONS:
        raise ValueError(f"Unsupported UniTime course format version {version!r}")
    nr_days = _integer(root, "nrDays", default=7, minimum=1)
    slots_per_day = _integer(root, "slotsPerDay", default=288, minimum=1)
    unsupported: set[str] = set()
    allowed_root = {"rooms", "instructors", "classes", "groupConstraints", "students", "progress", "info"}
    for element in root:
        tag = _local_name(element.tag)
        if tag not in allowed_root:
            unsupported.add(f"course top-level element <{tag}>")

    rooms_block = _child(root, "rooms")
    classes_block = _child(root, "classes")
    constraints_block = _child(root, "groupConstraints")
    students_block = _child(root, "students")
    if rooms_block is None or classes_block is None:
        raise ValueError("UniTime course XML requires <rooms> and <classes>")
    rooms: list[UniTimeRoom] = []
    for element in rooms_block:
        if _local_name(element.tag) != "room":
            unsupported.add(f"course rooms element <{_local_name(element.tag)}>")
            continue
        room = _parse_common_room(element, exam=False)
        if _child(element, "sharing") is not None:
            unsupported.add(f"course room-sharing matrix ({room.id})")
        rooms.append(room)
    _unique_ids(rooms, label="rooms")
    room_ids = {room.id for room in rooms}

    classes: list[UniTimeCourseClass] = []
    embedded: list[UniTimeAssignment] = []
    for element in classes_block:
        if _local_name(element.tag) != "class":
            unsupported.add(f"course classes element <{_local_name(element.tag)}>")
            continue
        identifier = _required(element, "id")
        offering = element.get("offering") or element.get("course")
        config = element.get("config") or offering
        subpart = element.get("subpart") or element.get("course")
        if not offering or not config or not subpart:
            raise ValueError(f"UniTime course class {identifier} is missing offering/config/subpart identity")
        committed = _boolean(element, "committed", default=False)
        if element.get("expectedCapacity") is not None:
            minimum_limit = maximum_limit = _integer(element, "expectedCapacity", minimum=0)
        elif element.get("classLimit") is not None:
            minimum_limit = maximum_limit = _integer(element, "classLimit", minimum=0)
        elif element.get("minClassLimit") is not None or element.get("maxClassLimit") is not None:
            minimum_limit = _integer(element, "minClassLimit", minimum=0)
            maximum_limit = _integer(element, "maxClassLimit", minimum=0)
            unsupported.add(f"course variable class-limit semantics ({identifier})")
        else:
            minimum_limit = maximum_limit = 0
        if minimum_limit > maximum_limit:
            raise ValueError(f"UniTime course class {identifier} has an inverted class-limit range")
        ratio = _number(element, "roomToLimitRatio", default=1.0)
        if ratio <= 0:
            raise ValueError(f"UniTime course class {identifier} roomToLimitRatio must be positive")
        class_dates = _validate_mask(
            element.get("dates", "1"), field_name=f"class {identifier} dates"
        )
        instructor_ids: list[str] = []
        room_options: list[UniTimeRoomOption] = []
        time_options: list[UniTimeTime] = []
        selected_rooms: list[str] = []
        selected_time: str | None = None
        for child_element in element:
            tag = _local_name(child_element.tag)
            if tag == "instructor":
                instructor_ids.append(_required(child_element, "id"))
            elif tag == "room":
                room_id = _required(child_element, "id")
                if room_id not in room_ids:
                    raise ValueError(f"UniTime course class {identifier} references unknown room {room_id}")
                room_options.append(
                    UniTimeRoomOption(room_id=room_id, penalty=_number(child_element, "pref", default=0.0))
                )
                if _boolean(child_element, "solution", default=False):
                    selected_rooms.append(room_id)
                for grandchild in child_element:
                    if _local_name(grandchild.tag) == "preference":
                        unsupported.add(f"course indexed room preference ({identifier}, {room_id})")
                    else:
                        unsupported.add(
                            f"course room-option element <{_local_name(grandchild.tag)}> ({identifier})"
                        )
            elif tag == "time":
                option_id = f"{identifier}:t{len(time_options)}"
                days = _validate_mask(
                    _required(child_element, "days"),
                    field_name=f"class {identifier} time days",
                    length=nr_days,
                )
                start = _integer(child_element, "start", minimum=0)
                length = _integer(child_element, "length", minimum=0)
                if length == 0:
                    unsupported.add(f"course zero-length time option ({identifier})")
                if start + length > slots_per_day:
                    raise ValueError(f"UniTime course class {identifier} time exceeds slotsPerDay")
                option = UniTimeTime(
                    id=option_id,
                    days=days,
                    start=start,
                    length=length,
                    dates=class_dates,
                    break_time=_integer(child_element, "breakTime", default=0, minimum=0),
                    penalty=_number(child_element, "pref", default=0.0),
                )
                time_options.append(option)
                if _boolean(child_element, "solution", default=False):
                    if selected_time is not None:
                        prior = next(item for item in time_options if item.id == selected_time)
                        if (
                            prior.days,
                            prior.start,
                            prior.length,
                            prior.dates,
                            prior.break_time,
                        ) != (
                            option.days,
                            option.start,
                            option.length,
                            option.dates,
                            option.break_time,
                        ):
                            raise ValueError(
                                f"UniTime course class {identifier} selects multiple distinct solution times"
                            )
                        unsupported.add(
                            f"course duplicate selected time marker ({identifier})"
                        )
                    else:
                        selected_time = option_id
            elif tag not in {"date"}:
                unsupported.add(f"course class element <{tag}> ({identifier})")
        if not time_options:
            raise ValueError(f"UniTime course class {identifier} has no time option")
        rooms_required = _integer(
            element,
            "nrRooms",
            default=0 if not room_options else 1,
            minimum=0,
        )
        if rooms_required > len(room_options):
            raise ValueError(f"UniTime course class {identifier} requires more rooms than it permits")
        if element.get("parent") is not None:
            unsupported.add(f"course parent-class sectioning ({identifier})")
        if _boolean(element, "splitAttandance", default=False):
            unsupported.add(f"course split-attendance room semantics ({identifier})")
        klass = UniTimeCourseClass(
            id=identifier,
            offering_id=offering,
            config_id=config,
            subpart_id=subpart,
            committed=committed,
            class_limit=maximum_limit,
            minimum_limit=minimum_limit,
            maximum_limit=maximum_limit,
            room_to_limit_ratio=ratio,
            rooms_required=rooms_required,
            instructor_ids=tuple(instructor_ids),
            time_options=tuple(time_options),
            room_options=tuple(room_options),
            extra_attributes=_extra_attributes(
                element,
                {
                    "id", "offering", "course", "config", "subpart", "committed", "classLimit",
                    "minClassLimit", "maxClassLimit", "expectedCapacity", "roomCapacity",
                    "roomToLimitRatio", "nrRooms", "dates", "parent", "splitAttandance",
                    "scheduler", "department", "solverGroup", "name", "note", "ord", "weight",
                    "maxRoomCombinations", "assignment",
                },
            ),
        )
        classes.append(klass)
        if selected_time is not None or selected_rooms:
            embedded.append(
                UniTimeAssignment(
                    item_id=identifier,
                    assigned=selected_time is not None,
                    time_id=selected_time,
                    room_ids=tuple(selected_rooms),
                )
            )
    _unique_ids(classes, label="classes")
    class_ids = {klass.id for klass in classes}

    constraints: list[UniTimeCourseConstraint] = []
    if constraints_block is not None:
        for element in constraints_block:
            if _local_name(element.tag) != "constraint":
                unsupported.add(f"course group-constraints element <{_local_name(element.tag)}>")
                continue
            identifier = _required(element, "id")
            constraint_type = _required(element, "type").upper()
            preference = element.get("pref", "R")
            required, prohibited, weight = _preference(preference)
            references = tuple(
                _required(child_element, "id")
                for child_element in element
                if _local_name(child_element.tag) == "class"
            )
            unknown = sorted(set(references) - class_ids)
            if unknown:
                raise ValueError(
                    f"UniTime course constraint {identifier} references unknown classes: {', '.join(unknown)}"
                )
            supported = constraint_type in _COURSE_SUPPORTED_CONSTRAINTS
            if constraint_type == "SAME_STUDENTS":
                supported = False
                unsupported.add(
                    f"course constraint SAME_STUDENTS travel semantics ({identifier})"
                )
            elif not supported:
                unsupported.add(f"course constraint {constraint_type} ({identifier})")
            constraints.append(
                UniTimeCourseConstraint(
                    id=identifier,
                    type=constraint_type,
                    preference=preference,
                    class_ids=references,
                    required=required,
                    prohibited=prohibited,
                    weight=weight,
                    supported=supported,
                )
            )
    duplicate_constraint_ids = sorted(
        item for item, count in Counter(c.id for c in constraints).items() if count > 1
    )
    for identifier in duplicate_constraint_ids:
        unsupported.add(f"course duplicate constraint id ({identifier})")

    students: list[UniTimeCourseStudent] = []
    if students_block is not None:
        for element in students_block:
            if _local_name(element.tag) != "student":
                unsupported.add(f"course students element <{_local_name(element.tag)}>")
                continue
            identifier = _required(element, "id")
            offering_weights: list[tuple[str, float]] = []
            enrollments: list[str] = []
            prohibited_classes: list[str] = []
            for child_element in element:
                tag = _local_name(child_element.tag)
                if tag == "offering":
                    offering_weights.append(
                        (_required(child_element, "id"), _number(child_element, "weight", default=1.0))
                    )
                elif tag == "class":
                    enrollments.append(_required(child_element, "id"))
                elif tag == "prohibited-class":
                    prohibited_classes.append(_required(child_element, "id"))
                else:
                    unsupported.add(f"course student element <{tag}> ({identifier})")
            bad = sorted((set(enrollments) | set(prohibited_classes)) - class_ids)
            if bad:
                raise ValueError(
                    f"UniTime course student {identifier} references unknown classes: {', '.join(bad)}"
                )
            students.append(
                UniTimeCourseStudent(
                    id=identifier,
                    offering_weights=tuple(offering_weights),
                    class_ids=tuple(enrollments),
                    prohibited_class_ids=tuple(prohibited_classes),
                )
            )
    _unique_ids(students, label="course students")
    solution = (
        UniTimeSolution(kind="course", assignments=tuple(embedded)) if embedded else None
    )
    return UniTimeCourseProblem(
        kind="course",
        name=root.get("term") or source.stem,
        version=version,
        nr_days=nr_days,
        slots_per_day=slots_per_day,
        rooms=tuple(rooms),
        classes=tuple(classes),
        constraints=tuple(constraints),
        students=tuple(students),
        unsupported_features=tuple(sorted(unsupported)),
        embedded_solution=solution,
        source_path=str(source.resolve()),
        metadata=_extra_attributes(root, {"version", "initiative", "term", "year", "created", "nrDays", "slotsPerDay"}),
    )


def parse_unitime_exam_xml(path: str | Path) -> UniTimeExamProblem:
    source, root = _secure_xml_root(path)
    if _local_name(root.tag) != "examtt":
        raise ValueError("UniTime examination XML root must be <examtt>")
    version = _required(root, "version")
    if version not in _EXAM_VERSIONS:
        raise ValueError(f"Unsupported UniTime examination format version {version!r}")
    unsupported: set[str] = set()
    allowed_root = {"parameters", "periods", "rooms", "exams", "students", "instructors", "constraints", "progress"}
    for element in root:
        tag = _local_name(element.tag)
        if tag not in allowed_root:
            unsupported.add(f"exam top-level element <{tag}>")
    periods_block = _child(root, "periods")
    rooms_block = _child(root, "rooms")
    exams_block = _child(root, "exams")
    if periods_block is None or rooms_block is None or exams_block is None:
        raise ValueError("UniTime examination XML requires periods, rooms, and exams")
    periods: list[UniTimeExamPeriod] = []
    for index, element in enumerate(periods_block):
        if _local_name(element.tag) != "period":
            unsupported.add(f"exam periods element <{_local_name(element.tag)}>")
            continue
        periods.append(
            UniTimeExamPeriod(
                id=_required(element, "id"),
                length=_integer(element, "length", minimum=1),
                day=_required(element, "day"),
                time_label=element.get("time", ""),
                penalty=_number(element, "penalty", default=0.0),
                index=index,
            )
        )
    _unique_ids(periods, label="exam periods")
    period_ids = {period.id for period in periods}
    rooms = [
        _parse_common_room(element, exam=True)
        for element in rooms_block
        if _local_name(element.tag) == "room"
    ]
    for element in rooms_block:
        if _local_name(element.tag) != "room":
            unsupported.add(f"exam rooms element <{_local_name(element.tag)}>")
    _unique_ids(rooms, label="exam rooms")
    room_ids = {room.id for room in rooms}
    for room in rooms:
        bad = (set(room.unavailable_periods) | {item[0] for item in room.period_penalties}) - period_ids
        if bad:
            raise ValueError(f"UniTime exam room {room.id} references unknown periods: {', '.join(sorted(bad))}")

    exams: list[UniTimeExam] = []
    embedded: list[UniTimeAssignment] = []
    for element in exams_block:
        if _local_name(element.tag) != "exam":
            unsupported.add(f"exam exams element <{_local_name(element.tag)}>")
            continue
        identifier = _required(element, "id")
        period_options: list[tuple[str, float | None]] = []
        room_options: list[UniTimeRoomOption] = []
        assignment_element: etree._Element | None = None
        for child_element in element:
            tag = _local_name(child_element.tag)
            if tag == "period":
                period_id = _required(child_element, "id")
                if period_id not in period_ids:
                    raise ValueError(f"UniTime exam {identifier} references unknown period {period_id}")
                period_options.append(
                    (period_id, _number(child_element, "penalty") if child_element.get("penalty") is not None else None)
                )
            elif tag == "room":
                room_id = _required(child_element, "id")
                if room_id not in room_ids:
                    raise ValueError(f"UniTime exam {identifier} references unknown room {room_id}")
                room_options.append(
                    UniTimeRoomOption(
                        room_id=room_id,
                        penalty=_number(child_element, "penalty", default=0.0),
                        max_penalty=_number(child_element, "maxPenalty") if child_element.get("maxPenalty") is not None else None,
                    )
                )
            elif tag == "assignment":
                if assignment_element is not None:
                    raise ValueError(f"UniTime exam {identifier} has duplicate assignments")
                assignment_element = child_element
            else:
                unsupported.add(f"exam element <{tag}> ({identifier})")
        if not period_options:
            raise ValueError(f"UniTime exam {identifier} has no available period")
        maximum_rooms = _integer(element, "maxRooms", default=4, minimum=0)
        exam = UniTimeExam(
            id=identifier,
            length=_integer(element, "length", minimum=1),
            alternate_seating=_boolean(element, "alt", default=False),
            minimum_size=_integer(element, "minSize", default=0, minimum=0),
            maximum_rooms=maximum_rooms,
            declared_size=_integer(element, "size", minimum=0) if element.get("size") is not None else None,
            average_period=_number(element, "average") if element.get("average") is not None else None,
            period_options=tuple(period_options),
            room_options=tuple(room_options),
            extra_attributes=_extra_attributes(
                element,
                {"id", "length", "alt", "minSize", "maxRooms", "average", "size", "printOffset", "name"},
            ),
        )
        exams.append(exam)
        if assignment_element is not None:
            selected_periods = [
                _required(item, "id")
                for item in assignment_element
                if _local_name(item.tag) == "period"
            ]
            selected_rooms = tuple(
                _required(item, "id")
                for item in assignment_element
                if _local_name(item.tag) == "room"
            )
            for item in assignment_element:
                if _local_name(item.tag) not in {"period", "room"}:
                    unsupported.add(f"exam assignment element <{_local_name(item.tag)}> ({identifier})")
            if len(selected_periods) != 1:
                raise ValueError(f"UniTime exam {identifier} assignment must select exactly one period")
            embedded.append(
                UniTimeAssignment(
                    item_id=identifier,
                    time_id=selected_periods[0],
                    room_ids=selected_rooms,
                )
            )
    _unique_ids(exams, label="exams")
    exam_ids = {exam.id for exam in exams}

    def parse_people(block_name: str) -> tuple[UniTimeExamPerson, ...]:
        block = _child(root, block_name)
        people: list[UniTimeExamPerson] = []
        if block is None:
            return ()
        singular = "student" if block_name == "students" else "instructor"
        for element in block:
            if _local_name(element.tag) != singular:
                unsupported.add(f"exam {block_name} element <{_local_name(element.tag)}>")
                continue
            identifier = _required(element, "id")
            enrolled: list[str] = []
            unavailable: list[str] = []
            for child_element in element:
                tag = _local_name(child_element.tag)
                if tag == "exam":
                    enrolled.append(_required(child_element, "id"))
                elif tag == "period" and not _boolean(child_element, "available", default=True):
                    unavailable.append(_required(child_element, "id"))
                elif tag != "period":
                    unsupported.add(f"exam {singular} element <{tag}> ({identifier})")
            bad_exams = sorted(set(enrolled) - exam_ids)
            bad_periods = sorted(set(unavailable) - period_ids)
            if bad_exams or bad_periods:
                raise ValueError(
                    f"UniTime exam {singular} {identifier} contains unknown references: "
                    + ", ".join(bad_exams + bad_periods)
                )
            people.append(UniTimeExamPerson(identifier, tuple(enrolled), tuple(unavailable)))
        _unique_ids(people, label=f"exam {block_name}")
        return tuple(people)

    students = parse_people("students")
    instructors = parse_people("instructors")
    constraints: list[UniTimeExamConstraint] = []
    constraints_block = _child(root, "constraints")
    if constraints_block is not None:
        for element in constraints_block:
            constraint_type = _local_name(element.tag)
            identifier = _required(element, "id")
            references = tuple(
                _required(item, "id") for item in element if _local_name(item.tag) == "exam"
            )
            unknown = sorted(set(references) - exam_ids)
            if unknown:
                raise ValueError(
                    f"UniTime exam constraint {identifier} references unknown exams: {', '.join(unknown)}"
                )
            supported = constraint_type in _EXAM_SUPPORTED_CONSTRAINTS
            if not supported:
                unsupported.add(f"exam constraint {constraint_type} ({identifier})")
            constraints.append(
                UniTimeExamConstraint(
                    id=identifier,
                    type=constraint_type,
                    exam_ids=references,
                    required=_boolean(element, "hard", default=True),
                    weight=_number(element, "weight", default=1.0),
                    supported=supported,
                )
            )
    _unique_ids(constraints, label="exam constraints")
    parameters_block = _child(root, "parameters")
    parameters: list[tuple[str, str]] = []
    if parameters_block is not None:
        for element in parameters_block:
            if _local_name(element.tag) != "property":
                unsupported.add(f"exam parameters element <{_local_name(element.tag)}>")
                continue
            parameters.append((_required(element, "name"), _required(element, "value")))
    solution = UniTimeSolution("exam", tuple(embedded)) if embedded else None
    return UniTimeExamProblem(
        kind="exam",
        name=root.get("term") or source.stem,
        version=version,
        periods=tuple(periods),
        rooms=tuple(rooms),
        exams=tuple(exams),
        students=students,
        instructors=instructors,
        constraints=tuple(constraints),
        parameters=tuple(parameters),
        unsupported_features=tuple(sorted(unsupported)),
        embedded_solution=solution,
        source_path=str(source.resolve()),
        metadata=_extra_attributes(root, {"version", "campus", "term", "year", "created"}),
    )


def parse_unitime_sectioning_xml(
    path: str | Path,
    *,
    solution_mode: Literal["best", "current", "initial"] = "best",
) -> UniTimeSectioningProblem:
    source, root = _secure_xml_root(path)
    if _local_name(root.tag) != "sectioning":
        raise ValueError("UniTime student-sectioning XML root must be <sectioning>")
    version = _required(root, "version")
    if version not in _SECTIONING_VERSIONS:
        raise ValueError(f"Unsupported UniTime student-sectioning format version {version!r}")
    nr_days = _integer(root, "nrDays", default=7, minimum=1)
    slots_per_day = _integer(root, "slotsPerDay", default=288, minimum=1)
    unsupported: set[str] = set()
    allowed_root = {"offerings", "students", "travel-times", "constraints", "progress"}
    for element in root:
        tag = _local_name(element.tag)
        if tag not in allowed_root:
            unsupported.add(f"sectioning top-level element <{tag}>")
        elif tag in {"travel-times", "constraints"}:
            unsupported.add(f"sectioning {tag} semantics")
    offerings_block = _child(root, "offerings")
    students_block = _child(root, "students")
    if offerings_block is None or students_block is None:
        raise ValueError("UniTime student-sectioning XML requires offerings and students")
    offerings: list[UniTimeOffering] = []
    all_course_ids: set[str] = set()
    all_config_ids: list[str] = []
    all_subpart_ids: list[str] = []
    all_section_ids: list[str] = []
    for offering_element in offerings_block:
        if _local_name(offering_element.tag) != "offering":
            unsupported.add(f"sectioning offerings element <{_local_name(offering_element.tag)}>")
            continue
        offering_id = _required(offering_element, "id")
        course_ids: list[str] = []
        configurations: list[UniTimeConfiguration] = []
        for child_element in offering_element:
            tag = _local_name(child_element.tag)
            if tag == "course":
                course_id = _required(child_element, "id")
                if course_id in all_course_ids:
                    raise ValueError(f"UniTime sectioning course id {course_id} is duplicated")
                all_course_ids.add(course_id)
                course_ids.append(course_id)
            elif tag == "config":
                config_id = _required(child_element, "id")
                all_config_ids.append(config_id)
                config_limit = _number(child_element, "limit", default=-1.0)
                subparts: list[UniTimeSubpart] = []
                if _child(child_element, "instructional-method") is not None:
                    unsupported.add(f"sectioning instructional-method choice ({config_id})")
                for subpart_element in child_element:
                    subpart_tag = _local_name(subpart_element.tag)
                    if subpart_tag == "instructional-method":
                        continue
                    if subpart_tag != "subpart":
                        unsupported.add(f"sectioning config element <{subpart_tag}> ({config_id})")
                        continue
                    subpart_id = _required(subpart_element, "id")
                    all_subpart_ids.append(subpart_id)
                    if _boolean(subpart_element, "allowOverlap", default=False):
                        unsupported.add(f"sectioning allow-overlap subpart ({subpart_id})")
                    sections: list[UniTimeSection] = []
                    for section_element in subpart_element:
                        if _local_name(section_element.tag) != "section":
                            unsupported.add(
                                f"sectioning subpart element <{_local_name(section_element.tag)}> ({subpart_id})"
                            )
                            continue
                        section_id = _required(section_element, "id")
                        all_section_ids.append(section_id)
                        time_elements = _children(section_element, "time")
                        if len(time_elements) > 1:
                            raise ValueError(f"UniTime section {section_id} has multiple fixed times")
                        section_time: UniTimeTime | None = None
                        if time_elements:
                            time_element = time_elements[0]
                            days = _validate_mask(
                                _required(time_element, "days"),
                                field_name=f"section {section_id} days",
                                length=nr_days,
                            )
                            start = _integer(time_element, "start", minimum=0)
                            length = _integer(time_element, "length", minimum=1)
                            if start + length > slots_per_day:
                                raise ValueError(f"UniTime section {section_id} time exceeds slotsPerDay")
                            section_time = UniTimeTime(
                                id=f"{section_id}:fixed",
                                days=days,
                                start=start,
                                length=length,
                                dates=_validate_mask(
                                    time_element.get("dates", "1"),
                                    field_name=f"section {section_id} dates",
                                ),
                                break_time=_integer(time_element, "breakTime", default=0, minimum=0),
                            )
                        room_ids = tuple(
                            _required(item, "id") for item in _children(section_element, "room")
                        )
                        instructor_ids = tuple(
                            _required(item, "id") for item in _children(section_element, "instructor")
                        )
                        allowed_section_children = {"time", "room", "instructor", "cname"}
                        for item in section_element:
                            item_tag = _local_name(item.tag)
                            if item_tag == "no-conflicts":
                                unsupported.add(f"sectioning no-conflicts relation ({section_id})")
                            elif item_tag not in allowed_section_children:
                                unsupported.add(f"sectioning section element <{item_tag}> ({section_id})")
                        if _boolean(section_element, "cancelled", default=False) or not _boolean(
                            section_element, "enabled", default=True
                        ):
                            unsupported.add(f"sectioning disabled or cancelled section ({section_id})")
                        sections.append(
                            UniTimeSection(
                                id=section_id,
                                subpart_id=subpart_id,
                                config_id=config_id,
                                offering_id=offering_id,
                                limit=_number(section_element, "limit"),
                                parent_id=section_element.get("parent"),
                                time=section_time,
                                room_ids=room_ids,
                                instructor_ids=instructor_ids,
                                extra_attributes=_extra_attributes(
                                    section_element,
                                    {
                                        "id", "limit", "parent", "hold", "expect", "expected", "name",
                                        "cancelled", "enabled", "online", "past", "instructorIds",
                                        "instructorNames",
                                    },
                                ),
                            )
                        )
                    if not sections:
                        raise ValueError(f"UniTime sectioning subpart {subpart_id} contains no sections")
                    subparts.append(
                        UniTimeSubpart(
                            id=subpart_id,
                            parent_id=subpart_element.get("parent"),
                            sections=tuple(sections),
                        )
                    )
                if not subparts:
                    raise ValueError(f"UniTime sectioning configuration {config_id} contains no subparts")
                configurations.append(
                    UniTimeConfiguration(id=config_id, limit=config_limit, subparts=tuple(subparts))
                )
            elif tag in {"reservation", "restriction"}:
                unsupported.add(f"sectioning {tag} ({offering_id})")
            else:
                unsupported.add(f"sectioning offering element <{tag}> ({offering_id})")
        if not course_ids or not configurations:
            raise ValueError(f"UniTime sectioning offering {offering_id} is incomplete")
        offerings.append(
            UniTimeOffering(
                id=offering_id,
                course_ids=tuple(course_ids),
                configurations=tuple(configurations),
            )
        )
    _unique_ids(offerings, label="sectioning offerings")
    if len(all_config_ids) != len(set(all_config_ids)):
        raise ValueError("UniTime sectioning configuration ids must be globally unique")
    if len(all_subpart_ids) != len(set(all_subpart_ids)):
        raise ValueError("UniTime sectioning subpart ids must be globally unique")
    if len(all_section_ids) != len(set(all_section_ids)):
        raise ValueError("UniTime sectioning section ids must be globally unique")
    section_ids = set(all_section_ids)
    sections_by_id = {
        section.id: section
        for offering in offerings
        for config in offering.configurations
        for subpart in config.subparts
        for section in subpart.sections
    }
    subpart_ids = set(all_subpart_ids)
    for offering in offerings:
        for config in offering.configurations:
            for subpart in config.subparts:
                if subpart.parent_id is not None and subpart.parent_id not in subpart_ids:
                    raise ValueError(
                        f"UniTime sectioning subpart {subpart.id} references unknown parent {subpart.parent_id}"
                    )
                for section in subpart.sections:
                    if section.parent_id is None:
                        continue
                    parent = sections_by_id.get(section.parent_id)
                    if parent is None:
                        raise ValueError(
                            f"UniTime section {section.id} references unknown parent {section.parent_id}"
                        )
                    if subpart.parent_id is not None and parent.subpart_id != subpart.parent_id:
                        raise ValueError(
                            f"UniTime section {section.id} parent is outside parent subpart"
                        )

    students: list[UniTimeSectioningStudent] = []
    embedded: list[UniTimeAssignment] = []
    request_ids: list[str] = []
    saw_embedded = False
    solution_preference = (solution_mode,) + tuple(
        item for item in ("best", "current", "initial") if item != solution_mode
    )
    for student_element in students_block:
        if _local_name(student_element.tag) != "student":
            unsupported.add(f"sectioning students element <{_local_name(student_element.tag)}>")
            continue
        student_id = _required(student_element, "id")
        requests: list[UniTimeSectioningRequest] = []
        for request_element in student_element:
            tag = _local_name(request_element.tag)
            if tag in {"classification", "major", "minor", "group", "accommodation"}:
                continue
            if tag not in {"course", "freeTime"}:
                unsupported.add(f"sectioning student element <{tag}> ({student_id})")
                continue
            request_id = _required(request_element, "id")
            request_ids.append(request_id)
            priority = _integer(request_element, "priority", default=0, minimum=0)
            weight = _number(request_element, "weight", default=1.0)
            if weight < 0:
                raise ValueError(f"UniTime sectioning request {request_id} weight must be non-negative")
            selected: etree._Element | None = None
            for mode in solution_preference:
                candidates = _children(request_element, mode)
                if len(candidates) > 1:
                    raise ValueError(f"UniTime sectioning request {request_id} has duplicate {mode} solutions")
                if candidates:
                    selected = candidates[0]
                    break
            if tag == "course":
                course_id = _required(request_element, "course")
                if course_id not in all_course_ids:
                    raise ValueError(
                        f"UniTime sectioning request {request_id} references unknown course {course_id}"
                    )
                alternatives = tuple(
                    _required(item, "course") for item in _children(request_element, "alternative")
                )
                unknown_alternatives = sorted(set(alternatives) - all_course_ids)
                if unknown_alternatives:
                    raise ValueError(
                        f"UniTime sectioning request {request_id} has unknown alternatives: "
                        + ", ".join(unknown_alternatives)
                    )
                alternative_request = _boolean(request_element, "alternative", default=False)
                if alternative_request:
                    unsupported.add(f"sectioning alternative-request substitution ({request_id})")
                requests.append(
                    UniTimeSectioningRequest(
                        id=request_id,
                        kind="course",
                        priority=priority,
                        weight=weight,
                        course_id=course_id,
                        alternative_course_ids=alternatives,
                        alternative_request=alternative_request,
                        waitlist=_boolean(request_element, "waitlist", default=False),
                    )
                )
                if selected is not None:
                    selected_sections = tuple(
                        _required(item, "id") for item in _children(selected, "section")
                    )
                    unknown = sorted(set(selected_sections) - section_ids)
                    if unknown:
                        raise ValueError(
                            f"UniTime sectioning solution {request_id} references unknown sections: "
                            + ", ".join(unknown)
                        )
                    embedded.append(
                        UniTimeAssignment(
                            item_id=request_id,
                            assigned=bool(selected_sections),
                            section_ids=selected_sections,
                        )
                    )
                    saw_embedded = True
            else:
                days = _validate_mask(
                    _required(request_element, "days"),
                    field_name=f"free-time request {request_id} days",
                    length=nr_days,
                )
                start = _integer(request_element, "start", minimum=0)
                length = _integer(request_element, "length", minimum=1)
                if start + length > slots_per_day:
                    raise ValueError(f"UniTime free-time request {request_id} exceeds slotsPerDay")
                free_time = UniTimeTime(
                    id=f"{request_id}:free",
                    days=days,
                    start=start,
                    length=length,
                    dates=_validate_mask(
                        request_element.get("dates", "1"),
                        field_name=f"free-time request {request_id} dates",
                    ),
                )
                requests.append(
                    UniTimeSectioningRequest(
                        id=request_id,
                        kind="free_time",
                        priority=priority,
                        weight=weight,
                        waitlist=_boolean(request_element, "waitlist", default=False),
                        free_time=free_time,
                    )
                )
                if selected is not None:
                    embedded.append(UniTimeAssignment(item_id=request_id, assigned=True))
                    saw_embedded = True
        students.append(
            UniTimeSectioningStudent(
                id=student_id,
                dummy=_boolean(student_element, "dummy", default=False),
                requests=tuple(requests),
            )
        )
    _unique_ids(students, label="sectioning students")
    if len(request_ids) != len(set(request_ids)):
        raise ValueError("UniTime student-sectioning request ids must be globally unique")
    solution = (
        UniTimeSolution("sectioning", tuple(embedded), (("mode", solution_mode),))
        if saw_embedded
        else None
    )
    return UniTimeSectioningProblem(
        kind="sectioning",
        name=f"{root.get('initiative', '')}-{root.get('year', '')}-{root.get('term', '')}".strip("-")
        or source.stem,
        version=version,
        nr_days=nr_days,
        slots_per_day=slots_per_day,
        offerings=tuple(offerings),
        students=tuple(students),
        unsupported_features=tuple(sorted(unsupported)),
        embedded_solution=solution,
        source_path=str(source.resolve()),
        metadata=_extra_attributes(root, {"version", "initiative", "term", "year", "created", "nrDays", "slotsPerDay"}),
    )


def parse_unitime_xml(
    path: str | Path,
    *,
    sectioning_solution_mode: Literal["best", "current", "initial"] = "best",
) -> UniTimeProblem:
    """Dispatch a public UniTime solver XML by its root element."""

    source = Path(path)
    try:
        context = etree.iterparse(
            str(source),
            events=("start",),
            resolve_entities=False,
            no_network=True,
            load_dtd=False,
            huge_tree=False,
        )
        _, first = next(context)
        root_name = _local_name(first.tag)
        del context
    except (etree.XMLSyntaxError, StopIteration) as exc:
        raise ValueError(f"Invalid UniTime XML: {exc}") from exc
    if root_name == "timetable":
        return parse_unitime_course_xml(source)
    if root_name == "examtt":
        return parse_unitime_exam_xml(source)
    if root_name == "sectioning":
        return parse_unitime_sectioning_xml(source, solution_mode=sectioning_solution_mode)
    raise ValueError(
        "Unsupported UniTime XML root; expected timetable, examtt, or sectioning, "
        f"got {root_name!r}"
    )


def _masks_overlap(first: str, second: str) -> bool:
    if first == "1" or second == "1":
        return True
    if len(first) != len(second):
        return False
    return any(left == right == "1" for left, right in zip(first, second, strict=True))


def _times_overlap(first: UniTimeTime, second: UniTimeTime) -> bool:
    return (
        _masks_overlap(first.days, second.days)
        and _masks_overlap(first.dates, second.dates)
        and first.start < second.start + second.length
        and second.start < first.start + first.length
    )


def _same_days(first: str, second: str) -> bool:
    first_set = {index for index, bit in enumerate(first) if bit == "1"}
    second_set = {index for index, bit in enumerate(second) if bit == "1"}
    return first_set <= second_set or second_set <= first_set


def _same_time(first: UniTimeTime, second: UniTimeTime) -> bool:
    first_end = first.start + first.length
    second_end = second.start + second.length
    return (first.start <= second.start and first_end >= second_end) or (
        second.start <= first.start and second_end >= first_end
    )


class _ErrorCollector:
    def __init__(self, limit: int = 250) -> None:
        self.count = 0
        self.messages: list[str] = []
        self.limit = limit

    def add(self, message: str) -> None:
        self.count += 1
        if len(self.messages) < self.limit:
            self.messages.append(message)

    def finish(self) -> tuple[str, ...]:
        if self.count > len(self.messages):
            self.messages.append(
                f"{self.count - len(self.messages)} additional hard violations omitted"
            )
        return tuple(self.messages)


def _assignment_map(
    solution: UniTimeSolution,
    *,
    expected_kind: UniTimeKind,
    errors: _ErrorCollector,
) -> dict[str, UniTimeAssignment]:
    if solution.kind != expected_kind:
        errors.add(
            f"solution kind {solution.kind!r} does not match problem kind {expected_kind!r}"
        )
    result: dict[str, UniTimeAssignment] = {}
    for assignment in solution.assignments:
        if assignment.item_id in result:
            errors.add(f"duplicate solution assignment for {assignment.item_id}")
        else:
            result[assignment.item_id] = assignment
    return result


@dataclass(frozen=True)
class _CoursePlaced:
    klass: UniTimeCourseClass
    assignment: UniTimeAssignment
    time: UniTimeTime


def _course_constraint_satisfied(
    constraint: UniTimeCourseConstraint,
    first: _CoursePlaced,
    second: _CoursePlaced,
) -> bool:
    if constraint.type == "SAME_ROOM":
        return set(first.assignment.room_ids) == set(second.assignment.room_ids)
    if constraint.type == "SAME_START":
        return first.time.start == second.time.start
    if constraint.type == "SAME_DAYS":
        return _same_days(first.time.days, second.time.days)
    if constraint.type == "SAME_TIME":
        return _same_time(first.time, second.time)
    if constraint.type == "DIFF_TIME":
        return not _times_overlap(first.time, second.time)
    return False


def _score_course(
    problem: UniTimeCourseProblem,
    solution: UniTimeSolution,
) -> tuple[UniTimeNativeScore, tuple[str, ...]]:
    errors = _ErrorCollector()
    assignment_by_id = _assignment_map(solution, expected_kind="course", errors=errors)
    classes_by_id = {klass.id: klass for klass in problem.classes}
    unknown = sorted(set(assignment_by_id) - set(classes_by_id))
    for item in unknown:
        errors.add(f"solution references unknown course class {item}")
    placed: dict[str, _CoursePlaced] = {}
    time_penalty = 0.0
    room_penalty = 0.0
    rooms_by_id = {room.id: room for room in problem.rooms}
    room_option_penalties = {
        klass.id: {option.room_id: option.penalty for option in klass.room_options}
        for klass in problem.classes
    }
    for klass in problem.classes:
        assignment = assignment_by_id.get(klass.id)
        if assignment is None or not assignment.assigned:
            errors.add(f"course class {klass.id} is unassigned")
            continue
        times = {option.id: option for option in klass.time_options}
        selected_time = times.get(assignment.time_id or "")
        if selected_time is None:
            errors.add(f"course class {klass.id} selects an unavailable time")
            continue
        if len(assignment.room_ids) != klass.rooms_required:
            errors.add(
                f"course class {klass.id} selects {len(assignment.room_ids)} rooms; "
                f"expected {klass.rooms_required}"
            )
        if len(set(assignment.room_ids)) != len(assignment.room_ids):
            errors.add(f"course class {klass.id} selects a room more than once")
        allowed_rooms = room_option_penalties[klass.id]
        for room_id in assignment.room_ids:
            if room_id not in allowed_rooms:
                errors.add(f"course class {klass.id} selects unavailable room {room_id}")
                continue
            room_penalty += allowed_rooms[room_id]
        time_penalty += selected_time.penalty
        placed[klass.id] = _CoursePlaced(klass, assignment, selected_time)

    placed_values = list(placed.values())
    for first, second in combinations(placed_values, 2):
        if not _times_overlap(first.time, second.time):
            continue
        shared_rooms = set(first.assignment.room_ids) & set(second.assignment.room_ids)
        for room_id in sorted(shared_rooms):
            if rooms_by_id[room_id].constrained:
                errors.add(
                    f"course classes {first.klass.id} and {second.klass.id} clash in room {room_id}"
                )
        shared_instructors = set(first.klass.instructor_ids) & set(second.klass.instructor_ids)
        for instructor_id in sorted(shared_instructors):
            errors.add(
                f"course classes {first.klass.id} and {second.klass.id} clash for instructor {instructor_id}"
            )

    student_conflicts = 0.0
    for student in problem.students:
        student_classes = [placed[item] for item in student.class_ids if item in placed]
        for first, second in combinations(student_classes, 2):
            if _times_overlap(first.time, second.time):
                student_conflicts += 1.0

    soft_distribution = 0.0
    for constraint in problem.constraints:
        if not constraint.supported:
            continue
        members = [placed[item] for item in constraint.class_ids if item in placed]
        for first, second in combinations(members, 2):
            satisfied = _course_constraint_satisfied(constraint, first, second)
            violated = satisfied if constraint.prohibited else not satisfied
            if not violated:
                continue
            if constraint.required:
                errors.add(
                    f"course constraint {constraint.id} ({constraint.type}) is violated by "
                    f"{first.klass.id}/{second.klass.id}"
                )
            else:
                soft_distribution += constraint.weight
    components = (
        ("time_preference", time_penalty),
        ("room_preference", room_penalty),
        ("soft_distribution", soft_distribution),
        ("student_conflicts", student_conflicts),
    )
    return (
        UniTimeNativeScore(
            hard_violations=errors.count,
            components=components,
            native_total=sum(value for _, value in components),
        ),
        errors.finish(),
    )


def _exam_constraint_satisfied(
    constraint: UniTimeExamConstraint,
    assignments: Mapping[str, UniTimeAssignment],
    period_indexes: Mapping[str, int],
) -> bool:
    selected = [assignments.get(item) for item in constraint.exam_ids]
    if any(item is None or not item.assigned or item.time_id is None for item in selected):
        return False
    concrete = [item for item in selected if item is not None]
    if constraint.type == "same-period":
        return len({item.time_id for item in concrete}) <= 1
    if constraint.type == "different-period":
        return len({item.time_id for item in concrete}) == len(concrete)
    if constraint.type == "same-room":
        return all(set(item.room_ids) == set(concrete[0].room_ids) for item in concrete[1:])
    if constraint.type == "different-room":
        return all(
            not (set(first.room_ids) & set(second.room_ids))
            for first, second in combinations(concrete, 2)
        )
    if constraint.type == "precedence":
        return all(
            period_indexes[first.time_id or ""] < period_indexes[second.time_id or ""]
            for first, second in zip(concrete, concrete[1:])
        )
    return False


def _parameter(problem: UniTimeExamProblem, name: str, default: float) -> float:
    values = dict(problem.parameters)
    raw = values.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if math.isfinite(value) else default


def _score_exam(
    problem: UniTimeExamProblem,
    solution: UniTimeSolution,
) -> tuple[UniTimeNativeScore, tuple[str, ...]]:
    errors = _ErrorCollector()
    assignment_by_id = _assignment_map(solution, expected_kind="exam", errors=errors)
    exams_by_id = {exam.id: exam for exam in problem.exams}
    periods_by_id = {period.id: period for period in problem.periods}
    rooms_by_id = {room.id: room for room in problem.rooms}
    period_indexes = {period.id: period.index for period in problem.periods}
    exam_students: dict[str, int] = Counter(
        exam_id for student in problem.students for exam_id in student.exam_ids
    )
    period_penalty = 0.0
    room_penalty = 0.0
    room_size_excess = 0.0
    room_splits = 0.0
    concrete: dict[str, UniTimeAssignment] = {}
    for unknown in sorted(set(assignment_by_id) - set(exams_by_id)):
        errors.add(f"solution references unknown exam {unknown}")
    for exam in problem.exams:
        assignment = assignment_by_id.get(exam.id)
        if assignment is None or not assignment.assigned:
            errors.add(f"exam {exam.id} is unassigned")
            continue
        period = periods_by_id.get(assignment.time_id or "")
        option_penalties = dict(exam.period_options)
        if period is None or period.id not in option_penalties:
            errors.add(f"exam {exam.id} selects an unavailable period")
            continue
        if period.length < exam.length:
            errors.add(f"exam {exam.id} is longer than period {period.id}")
        selected_period_penalty = option_penalties[period.id]
        period_penalty += period.penalty if selected_period_penalty is None else selected_period_penalty
        if len(set(assignment.room_ids)) != len(assignment.room_ids):
            errors.add(f"exam {exam.id} selects a room more than once")
        if len(assignment.room_ids) > exam.maximum_rooms:
            errors.add(f"exam {exam.id} exceeds its maximum room count")
        if exam.maximum_rooms == 0 and assignment.room_ids:
            errors.add(f"exam {exam.id} must not select a room")
        if exam.maximum_rooms > 0 and not assignment.room_ids:
            errors.add(f"exam {exam.id} has no room assignment")
        room_options = {option.room_id: option for option in exam.room_options}
        total_capacity = 0
        for room_id in assignment.room_ids:
            option = room_options.get(room_id)
            room = rooms_by_id.get(room_id)
            if option is None or room is None:
                errors.add(f"exam {exam.id} selects unavailable room {room_id}")
                continue
            if period.id in room.unavailable_periods:
                errors.add(f"exam {exam.id} uses room {room_id} while it is unavailable")
            room_period_penalty = dict(room.period_penalties).get(period.id, 0.0)
            room_penalty += option.penalty + room_period_penalty
            capacity = (
                room.alternate_capacity
                if exam.alternate_seating and room.alternate_capacity is not None
                else room.capacity
            )
            total_capacity += capacity
            if capacity < exam.minimum_size:
                errors.add(f"exam {exam.id} uses room {room_id} below its minimum size")
        needed = exam.declared_size if exam.declared_size is not None else exam_students.get(exam.id, 0)
        if exam.maximum_rooms > 0 and total_capacity < needed:
            errors.add(f"exam {exam.id} has insufficient total room capacity")
        room_size_excess += max(0, total_capacity - needed)
        room_splits += max(0, len(assignment.room_ids) - 1)
        concrete[exam.id] = assignment

    for first, second in combinations(concrete.values(), 2):
        if first.time_id != second.time_id:
            continue
        for room_id in sorted(set(first.room_ids) & set(second.room_ids)):
            errors.add(f"exams {first.item_id} and {second.item_id} clash in room {room_id}")

    student_direct = 0.0
    student_back_to_back = 0.0
    student_more_than_two = 0.0
    instructor_direct = 0.0
    for people, instructor in ((problem.students, False), (problem.instructors, True)):
        for person in people:
            assigned = [concrete[item] for item in person.exam_ids if item in concrete]
            for assignment in assigned:
                if assignment.time_id in person.unavailable_period_ids:
                    if instructor:
                        instructor_direct += 1.0
                    else:
                        student_direct += 1.0
            for first, second in combinations(assigned, 2):
                if first.time_id == second.time_id:
                    if instructor:
                        instructor_direct += 1.0
                    else:
                        student_direct += 1.0
                elif not instructor:
                    first_period = periods_by_id[first.time_id or ""]
                    second_period = periods_by_id[second.time_id or ""]
                    if (
                        first_period.day == second_period.day
                        and abs(first_period.index - second_period.index) == 1
                    ):
                        student_back_to_back += 1.0
            if not instructor:
                by_day = Counter(periods_by_id[item.time_id or ""].day for item in assigned)
                student_more_than_two += sum(max(0, count - 2) for count in by_day.values())

    soft_distribution = 0.0
    for constraint in problem.constraints:
        if not constraint.supported:
            continue
        satisfied = _exam_constraint_satisfied(constraint, concrete, period_indexes)
        if satisfied:
            continue
        if constraint.required:
            errors.add(f"exam constraint {constraint.id} ({constraint.type}) is violated")
        else:
            soft_distribution += constraint.weight
    components = (
        ("period_penalty", period_penalty * _parameter(problem, "periodWeight", 1.0)),
        ("room_penalty", room_penalty * _parameter(problem, "roomWeight", 1.0)),
        ("room_size_excess", room_size_excess * _parameter(problem, "roomSizeWeight", 0.001)),
        ("room_splits", room_splits * _parameter(problem, "roomSplitWeight", 10.0)),
        ("student_direct_conflicts", student_direct * _parameter(problem, "directConflictWeight", 1000.0)),
        ("student_back_to_back", student_back_to_back * _parameter(problem, "backToBackConflictWeight", 10.0)),
        ("student_more_than_two", student_more_than_two * _parameter(problem, "moreThanTwoADayWeight", 100.0)),
        ("instructor_direct_conflicts", instructor_direct * _parameter(problem, "instructorDirectConflictWeight", 10.0)),
        ("soft_distribution", soft_distribution * _parameter(problem, "distributionWeight", 1.0)),
    )
    return (
        UniTimeNativeScore(
            hard_violations=errors.count,
            components=components,
            native_total=sum(value for _, value in components),
        ),
        errors.finish(),
    )


def _score_sectioning(
    problem: UniTimeSectioningProblem,
    solution: UniTimeSolution,
) -> tuple[UniTimeNativeScore, tuple[str, ...]]:
    errors = _ErrorCollector()
    assignment_by_id = _assignment_map(solution, expected_kind="sectioning", errors=errors)
    request_owner: dict[str, UniTimeSectioningStudent] = {}
    requests: dict[str, UniTimeSectioningRequest] = {}
    for student in problem.students:
        for request in student.requests:
            request_owner[request.id] = student
            requests[request.id] = request
    for unknown in sorted(set(assignment_by_id) - set(requests)):
        errors.add(f"solution references unknown sectioning request {unknown}")
    offerings_by_course = {
        course_id: offering
        for offering in problem.offerings
        for course_id in offering.course_ids
    }
    offerings_by_id = {offering.id: offering for offering in problem.offerings}
    configurations = {
        config.id: config
        for offering in problem.offerings
        for config in offering.configurations
    }
    sections = {section.id: section for section in problem.sections}
    section_load: defaultdict[str, float] = defaultdict(float)
    section_max_weight: defaultdict[str, float] = defaultdict(float)
    config_load: defaultdict[str, float] = defaultdict(float)
    config_max_weight: defaultdict[str, float] = defaultdict(float)
    selected_by_student: defaultdict[str, list[tuple[str, UniTimeTime]]] = defaultdict(list)
    unassigned_weight = 0.0
    alternative_weight = 0.0
    assigned_weight = 0.0
    for request_id, request in requests.items():
        assignment = assignment_by_id.get(request_id)
        if request.kind == "free_time":
            if assignment is not None and assignment.section_ids:
                errors.add(f"free-time request {request_id} contains section ids")
            if assignment is not None and assignment.assigned and request.free_time is not None:
                selected_by_student[request_owner[request_id].id].append(
                    (request_id, request.free_time)
                )
            continue
        if assignment is None or not assignment.assigned:
            if not request.alternative_request:
                unassigned_weight += request.weight * (1000.0 + request.priority)
            continue
        if not assignment.section_ids:
            errors.add(f"course request {request_id} is assigned without sections")
            continue
        if len(set(assignment.section_ids)) != len(assignment.section_ids):
            errors.add(f"course request {request_id} selects a section more than once")
        chosen: list[UniTimeSection] = []
        for section_id in assignment.section_ids:
            section = sections.get(section_id)
            if section is None:
                errors.add(f"course request {request_id} selects unknown section {section_id}")
            else:
                chosen.append(section)
        if not chosen:
            continue
        offering_ids = {section.offering_id for section in chosen}
        config_ids = {section.config_id for section in chosen}
        allowed_courses = (request.course_id,) + request.alternative_course_ids
        allowed_offerings = {
            offerings_by_course[course_id].id
            for course_id in allowed_courses
            if course_id in offerings_by_course
        }
        if len(offering_ids) != 1 or not offering_ids <= allowed_offerings:
            errors.add(f"course request {request_id} selects sections outside one requested offering")
            continue
        if len(config_ids) != 1:
            errors.add(f"course request {request_id} mixes configurations")
            continue
        offering = offerings_by_id[next(iter(offering_ids))]
        config = configurations[next(iter(config_ids))]
        selected_by_subpart = Counter(section.subpart_id for section in chosen)
        expected_subparts = {subpart.id for subpart in config.subparts}
        if set(selected_by_subpart) != expected_subparts or any(
            count != 1 for count in selected_by_subpart.values()
        ):
            errors.add(f"course request {request_id} must select one section from every subpart")
        selected_ids = {section.id for section in chosen}
        for section in chosen:
            if section.parent_id is not None and section.parent_id not in selected_ids:
                errors.add(
                    f"course request {request_id} selects child {section.id} without parent {section.parent_id}"
                )
            section_load[section.id] += request.weight
            section_max_weight[section.id] = max(
                section_max_weight[section.id], request.weight
            )
            if section.time is not None:
                selected_by_student[request_owner[request_id].id].append(
                    (f"{request_id}:{section.id}", section.time)
                )
        config_load[config.id] += request.weight
        config_max_weight[config.id] = max(config_max_weight[config.id], request.weight)
        assigned_weight += request.weight
        selected_offering = offering_ids.pop()
        primary_offering = offerings_by_course[request.course_id or ""].id
        if selected_offering != primary_offering:
            alternative_weight += request.weight

    for section_id, load in section_load.items():
        limit = sections[section_id].limit
        effective = load - section_max_weight[section_id]
        if limit >= 0 and effective > limit + 1e-8:
            errors.add(f"section {section_id} capacity exceeded ({load:.4f}>{limit:.4f})")
    for config_id, load in config_load.items():
        limit = configurations[config_id].limit
        effective = load - config_max_weight[config_id]
        if limit >= 0 and effective > limit + 1e-8:
            errors.add(f"configuration {config_id} capacity exceeded ({load:.4f}>{limit:.4f})")
    student_conflicts = 0.0
    for student_id, selections in selected_by_student.items():
        for first, second in combinations(selections, 2):
            if _times_overlap(first[1], second[1]):
                student_conflicts += 1.0
                errors.add(
                    f"student {student_id} has overlapping assignments {first[0]} and {second[0]}"
                )
    components = (
        ("unassigned_request_weight", unassigned_weight),
        ("alternative_course_weight", alternative_weight),
        ("student_conflicts", student_conflicts),
        ("assigned_request_weight", -assigned_weight),
    )
    return (
        UniTimeNativeScore(
            hard_violations=errors.count,
            components=components,
            native_total=sum(value for _, value in components),
        ),
        errors.finish(),
    )


def validate_unitime_solution(
    problem: UniTimeProblem,
    solution: UniTimeSolution,
) -> UniTimeValidation:
    """Validate exact supported semantics and fail closed on unsupported ones."""

    if isinstance(problem, UniTimeCourseProblem):
        score, errors = _score_course(problem, solution)
    elif isinstance(problem, UniTimeExamProblem):
        score, errors = _score_exam(problem, solution)
    else:
        score, errors = _score_sectioning(problem, solution)
    return UniTimeValidation(
        score=score,
        errors=errors,
        unsupported_features=problem.unsupported_features,
    )


def score_unitime_solution(
    problem: UniTimeProblem,
    solution: UniTimeSolution,
) -> UniTimeNativeScore:
    """Return the local native-subset score, never an official CPSolver score."""

    return validate_unitime_solution(problem, solution).score


def summarize_unitime_problem(problem: UniTimeProblem) -> dict[str, object]:
    if isinstance(problem, UniTimeCourseProblem):
        counts = {
            "rooms": len(problem.rooms),
            "classes": len(problem.classes),
            "time_options": sum(len(item.time_options) for item in problem.classes),
            "room_options": sum(len(item.room_options) for item in problem.classes),
            "constraints": len(problem.constraints),
            "students": len(problem.students),
        }
    elif isinstance(problem, UniTimeExamProblem):
        counts = {
            "periods": len(problem.periods),
            "rooms": len(problem.rooms),
            "exams": len(problem.exams),
            "students": len(problem.students),
            "instructors": len(problem.instructors),
            "constraints": len(problem.constraints),
        }
    else:
        counts = {
            "offerings": len(problem.offerings),
            "configurations": sum(len(item.configurations) for item in problem.offerings),
            "sections": len(problem.sections),
            "students": len(problem.students),
            "requests": sum(len(item.requests) for item in problem.students),
        }
    return {
        "kind": problem.kind,
        "name": problem.name,
        "version": problem.version,
        **counts,
        "fully_supported": not problem.unsupported_features,
        "unsupported_features": list(problem.unsupported_features),
        "score_scheme": "planora-unitime-native-v1",
        "officially_comparable": False,
    }


@dataclass(frozen=True)
class _NativeAlternative:
    assignment: UniTimeAssignment
    time: UniTimeTime | None
    penalty: int


class _BuildDeadline(RuntimeError):
    pass


class _ScaleGuard(RuntimeError):
    pass


def _check_build_deadline(deadline: float, phase: str) -> None:
    if time.perf_counter() >= deadline:
        raise _BuildDeadline(phase)


def _empty_solution(problem: UniTimeProblem) -> UniTimeSolution:
    # Absence is the canonical compact representation of an unassigned item.
    # Keeping this O(1) matters when a deadline or scale guard is hit on a
    # hundred-thousand-request public sectioning instance.
    return UniTimeSolution(kind=problem.kind, assignments=())


def _course_alternatives(
    problem: UniTimeCourseProblem,
    deadline: float,
    *,
    maximum_alternatives: int,
) -> dict[str, tuple[_NativeAlternative, ...]]:
    fixed = (
        problem.embedded_solution.by_item() if problem.embedded_solution is not None else {}
    )
    total = 0
    output: dict[str, tuple[_NativeAlternative, ...]] = {}
    for klass in problem.classes:
        _check_build_deadline(deadline, "course alternative construction")
        room_count = klass.rooms_required
        room_combinations: Iterable[tuple[UniTimeRoomOption, ...]]
        if room_count == 0:
            room_combinations = [()]
        else:
            room_combinations = combinations(klass.room_options, room_count)
        materialized_rooms: list[tuple[UniTimeRoomOption, ...]] = []
        for room_items in room_combinations:
            materialized_rooms.append(room_items)
            if len(materialized_rooms) > maximum_alternatives:
                raise _ScaleGuard("course room-combination domain is too large")
        alternatives: list[_NativeAlternative] = []
        fixed_assignment = fixed.get(klass.id) if klass.committed else None
        for time_option in klass.time_options:
            for room_items in materialized_rooms:
                assignment = UniTimeAssignment(
                    item_id=klass.id,
                    time_id=time_option.id,
                    room_ids=tuple(item.room_id for item in room_items),
                )
                if fixed_assignment is not None and assignment != fixed_assignment:
                    continue
                alternatives.append(
                    _NativeAlternative(
                        assignment=assignment,
                        time=time_option,
                        penalty=round(
                            100
                            * (
                                time_option.penalty
                                + sum(item.penalty for item in room_items)
                            )
                        ),
                    )
                )
        if not alternatives:
            raise _ScaleGuard(f"course class {klass.id} has no capacity-feasible alternative")
        total += len(alternatives)
        if total > maximum_alternatives:
            raise _ScaleGuard("course alternative domain exceeds the configured scale guard")
        output[klass.id] = tuple(alternatives)
    return output


def _course_pair_is_hard_conflict(
    first: _NativeAlternative,
    second: _NativeAlternative,
    first_class: UniTimeCourseClass,
    second_class: UniTimeCourseClass,
    constrained_rooms: set[str],
) -> bool:
    if first.time is None or second.time is None or not _times_overlap(first.time, second.time):
        return False
    if set(first_class.instructor_ids) & set(second_class.instructor_ids):
        return True
    return bool(
        set(first.assignment.room_ids)
        & set(second.assignment.room_ids)
        & constrained_rooms
    )


def _build_course_model(
    problem: UniTimeCourseProblem,
    alternatives: Mapping[str, tuple[_NativeAlternative, ...]],
    deadline: float,
) -> tuple[cp_model.CpModel, dict[tuple[str, int], cp_model.IntVar], list[cp_model.LinearExpr]]:
    model = cp_model.CpModel()
    variables: dict[tuple[str, int], cp_model.IntVar] = {}
    objective: list[cp_model.LinearExpr] = []
    classes = {klass.id: klass for klass in problem.classes}
    for class_id, choices in alternatives.items():
        choice_variables = []
        for index, choice in enumerate(choices):
            variable = model.new_bool_var(f"c_{class_id}_{index}")
            variables[(class_id, index)] = variable
            choice_variables.append(variable)
            if choice.penalty:
                objective.append(choice.penalty * variable)
        model.add_exactly_one(choice_variables)
    constrained_rooms = {room.id for room in problem.rooms if room.constrained}
    for first_class, second_class in combinations(problem.classes, 2):
        _check_build_deadline(deadline, "course conflicts")
        first_choices = alternatives[first_class.id]
        second_choices = alternatives[second_class.id]
        for first_index, first in enumerate(first_choices):
            for second_index, second in enumerate(second_choices):
                if _course_pair_is_hard_conflict(
                    first,
                    second,
                    first_class,
                    second_class,
                    constrained_rooms,
                ):
                    model.add(
                        variables[(first_class.id, first_index)]
                        + variables[(second_class.id, second_index)]
                        <= 1
                    )
    for constraint in problem.constraints:
        if not constraint.supported:
            continue
        for first_id, second_id in combinations(constraint.class_ids, 2):
            if first_id not in alternatives or second_id not in alternatives:
                continue
            first_class = classes[first_id]
            second_class = classes[second_id]
            for first_index, first in enumerate(alternatives[first_id]):
                for second_index, second in enumerate(alternatives[second_id]):
                    first_placed = _CoursePlaced(first_class, first.assignment, first.time)  # type: ignore[arg-type]
                    second_placed = _CoursePlaced(second_class, second.assignment, second.time)  # type: ignore[arg-type]
                    satisfied = _course_constraint_satisfied(
                        constraint, first_placed, second_placed
                    )
                    violated = satisfied if constraint.prohibited else not satisfied
                    if not violated:
                        continue
                    left = variables[(first_id, first_index)]
                    right = variables[(second_id, second_index)]
                    if constraint.required:
                        model.add(left + right <= 1)
                    else:
                        violation = model.new_bool_var(
                            f"course_soft_{constraint.id}_{first_id}_{first_index}_{second_id}_{second_index}"
                        )
                        model.add(violation >= left + right - 1)
                        objective.append(round(100 * constraint.weight) * violation)
    student_pair_weights: Counter[tuple[str, str]] = Counter()
    for student in problem.students:
        for first, second in combinations(sorted(set(student.class_ids)), 2):
            if first in alternatives and second in alternatives:
                student_pair_weights[(first, second)] += 1
    for (first_id, second_id), weight in student_pair_weights.items():
        _check_build_deadline(deadline, "course student-conflict objective")
        for first_index, first in enumerate(alternatives[first_id]):
            for second_index, second in enumerate(alternatives[second_id]):
                if first.time is None or second.time is None or not _times_overlap(first.time, second.time):
                    continue
                violation = model.new_bool_var(
                    f"student_{first_id}_{first_index}_{second_id}_{second_index}"
                )
                model.add(
                    violation
                    >= variables[(first_id, first_index)]
                    + variables[(second_id, second_index)]
                    - 1
                )
                objective.append(100 * weight * violation)
    model.minimize(sum(objective) if objective else 0)
    return model, variables, objective


def _exam_room_combinations(
    exam: UniTimeExam,
    rooms: Mapping[str, UniTimeRoom],
    size: int,
    *,
    maximum_combinations: int,
) -> tuple[tuple[UniTimeRoomOption, ...], ...]:
    if exam.maximum_rooms == 0:
        return ((),)
    if len(exam.room_options) > 24 or exam.maximum_rooms > 4:
        raise _ScaleGuard(f"exam {exam.id} room domain is too large for exact enumeration")
    result: list[tuple[UniTimeRoomOption, ...]] = []
    for count in range(1, min(exam.maximum_rooms, len(exam.room_options)) + 1):
        for items in combinations(exam.room_options, count):
            capacities = [
                (
                    rooms[item.room_id].alternate_capacity
                    if exam.alternate_seating and rooms[item.room_id].alternate_capacity is not None
                    else rooms[item.room_id].capacity
                )
                for item in items
            ]
            if sum(capacities) < size or any(value < exam.minimum_size for value in capacities):
                continue
            result.append(items)
            if len(result) > maximum_combinations:
                raise _ScaleGuard(f"exam {exam.id} room combinations exceed the scale guard")
    return tuple(result)


def _exam_alternatives(
    problem: UniTimeExamProblem,
    deadline: float,
    *,
    maximum_alternatives: int,
) -> dict[str, tuple[_NativeAlternative, ...]]:
    rooms = {room.id: room for room in problem.rooms}
    periods = {period.id: period for period in problem.periods}
    sizes: Counter[str] = Counter(
        exam_id for student in problem.students for exam_id in student.exam_ids
    )
    fixed = problem.embedded_solution.by_item() if problem.embedded_solution else {}
    total = 0
    output: dict[str, tuple[_NativeAlternative, ...]] = {}
    for exam in problem.exams:
        _check_build_deadline(deadline, "exam alternative construction")
        size = exam.declared_size if exam.declared_size is not None else sizes.get(exam.id, 0)
        room_combinations = _exam_room_combinations(
            exam, rooms, size, maximum_combinations=128
        )
        if not room_combinations:
            raise _ScaleGuard(f"exam {exam.id} has no capacity-feasible room combination")
        choices: list[_NativeAlternative] = []
        fixed_assignment = fixed.get(exam.id)
        for period_id, explicit_period_penalty in exam.period_options:
            period = periods[period_id]
            if period.length < exam.length:
                continue
            for room_items in room_combinations:
                if any(period_id in rooms[item.room_id].unavailable_periods for item in room_items):
                    continue
                assignment = UniTimeAssignment(
                    item_id=exam.id,
                    time_id=period_id,
                    room_ids=tuple(item.room_id for item in room_items),
                )
                if fixed_assignment is not None and assignment != fixed_assignment:
                    continue
                period_value = (
                    period.penalty
                    if explicit_period_penalty is None
                    else explicit_period_penalty
                )
                room_value = sum(
                    item.penalty + dict(rooms[item.room_id].period_penalties).get(period_id, 0.0)
                    for item in room_items
                )
                choices.append(
                    _NativeAlternative(
                        assignment=assignment,
                        time=None,
                        penalty=round(100 * (period_value + room_value)),
                    )
                )
        if not choices:
            raise _ScaleGuard(f"exam {exam.id} has no feasible alternative")
        total += len(choices)
        if total > maximum_alternatives:
            raise _ScaleGuard("exam alternative domain exceeds the configured scale guard")
        output[exam.id] = tuple(choices)
    return output


def _build_exam_model(
    problem: UniTimeExamProblem,
    alternatives: Mapping[str, tuple[_NativeAlternative, ...]],
    deadline: float,
) -> tuple[cp_model.CpModel, dict[tuple[str, int], cp_model.IntVar]]:
    model = cp_model.CpModel()
    variables: dict[tuple[str, int], cp_model.IntVar] = {}
    objective: list[cp_model.LinearExpr] = []
    for exam_id, choices in alternatives.items():
        selected = []
        for index, choice in enumerate(choices):
            variable = model.new_bool_var(f"e_{exam_id}_{index}")
            variables[(exam_id, index)] = variable
            selected.append(variable)
            if choice.penalty:
                objective.append(choice.penalty * variable)
        model.add_exactly_one(selected)
    exams = list(problem.exams)
    for first_exam, second_exam in combinations(exams, 2):
        _check_build_deadline(deadline, "exam room conflicts")
        for first_index, first in enumerate(alternatives[first_exam.id]):
            for second_index, second in enumerate(alternatives[second_exam.id]):
                if (
                    first.assignment.time_id == second.assignment.time_id
                    and set(first.assignment.room_ids) & set(second.assignment.room_ids)
                ):
                    model.add(
                        variables[(first_exam.id, first_index)]
                        + variables[(second_exam.id, second_index)]
                        <= 1
                    )
    period_indexes = {period.id: period.index for period in problem.periods}
    for constraint in problem.constraints:
        if not constraint.supported:
            continue
        member_ids = [item for item in constraint.exam_ids if item in alternatives]
        for first_id, second_id in combinations(member_ids, 2):
            pair_constraint = UniTimeExamConstraint(
                constraint.id,
                constraint.type,
                (first_id, second_id),
                constraint.required,
                constraint.weight,
                constraint.supported,
            )
            for first_index, first in enumerate(alternatives[first_id]):
                for second_index, second in enumerate(alternatives[second_id]):
                    pair = {
                        first_id: first.assignment,
                        second_id: second.assignment,
                    }
                    if _exam_constraint_satisfied(pair_constraint, pair, period_indexes):
                        continue
                    left = variables[(first_id, first_index)]
                    right = variables[(second_id, second_index)]
                    if constraint.required:
                        model.add(left + right <= 1)
                    else:
                        violation = model.new_bool_var(
                            f"exam_soft_{constraint.id}_{first_id}_{first_index}_{second_id}_{second_index}"
                        )
                        model.add(violation >= left + right - 1)
                        objective.append(round(100 * constraint.weight) * violation)
        if constraint.type == "precedence" and constraint.required:
            for first_id, second_id in zip(member_ids, member_ids[1:]):
                for first_index, first in enumerate(alternatives[first_id]):
                    for second_index, second in enumerate(alternatives[second_id]):
                        if period_indexes[first.assignment.time_id or ""] >= period_indexes[
                            second.assignment.time_id or ""
                        ]:
                            model.add(
                                variables[(first_id, first_index)]
                                + variables[(second_id, second_index)]
                                <= 1
                            )
    pair_weights: Counter[tuple[str, str]] = Counter()
    unavailable_weights: Counter[tuple[str, str]] = Counter()
    for person in problem.students:
        for first, second in combinations(sorted(set(person.exam_ids)), 2):
            pair_weights[(first, second)] += round(
                _parameter(problem, "directConflictWeight", 1000.0)
            )
        for exam_id in person.exam_ids:
            for period_id in person.unavailable_period_ids:
                unavailable_weights[(exam_id, period_id)] += round(
                    _parameter(problem, "directConflictWeight", 1000.0)
                )
    for person in problem.instructors:
        for first, second in combinations(sorted(set(person.exam_ids)), 2):
            pair_weights[(first, second)] += round(
                _parameter(problem, "instructorDirectConflictWeight", 10.0)
            )
        for exam_id in person.exam_ids:
            for period_id in person.unavailable_period_ids:
                unavailable_weights[(exam_id, period_id)] += round(
                    _parameter(problem, "instructorDirectConflictWeight", 10.0)
                )
    for (exam_id, period_id), weight in unavailable_weights.items():
        if exam_id not in alternatives or not weight:
            continue
        for index, choice in enumerate(alternatives[exam_id]):
            if choice.assignment.time_id == period_id:
                objective.append(100 * weight * variables[(exam_id, index)])
    for (first_id, second_id), weight in pair_weights.items():
        if first_id not in alternatives or second_id not in alternatives or not weight:
            continue
        _check_build_deadline(deadline, "exam person-conflict objective")
        for first_index, first in enumerate(alternatives[first_id]):
            for second_index, second in enumerate(alternatives[second_id]):
                if first.assignment.time_id != second.assignment.time_id:
                    continue
                violation = model.new_bool_var(
                    f"exam_person_{first_id}_{first_index}_{second_id}_{second_index}"
                )
                model.add(
                    violation
                    >= variables[(first_id, first_index)]
                    + variables[(second_id, second_index)]
                    - 1
                )
                objective.append(100 * weight * violation)
    model.minimize(sum(objective) if objective else 0)
    return model, variables


def _section_enrollment_options(
    problem: UniTimeSectioningProblem,
    request: UniTimeSectioningRequest,
    *,
    maximum_per_request: int,
) -> tuple[_NativeAlternative, ...]:
    offerings = {
        course_id: offering
        for offering in problem.offerings
        for course_id in offering.course_ids
    }
    choices: list[_NativeAlternative] = []
    course_ids = (request.course_id,) + request.alternative_course_ids
    for course_index, course_id in enumerate(course_ids):
        if course_id is None:
            continue
        offering = offerings[course_id]
        for config in offering.configurations:
            section_domains = [subpart.sections for subpart in config.subparts]
            for selected in product(*section_domains):
                selected_ids = {section.id for section in selected}
                if any(
                    section.parent_id is not None and section.parent_id not in selected_ids
                    for section in selected
                ):
                    continue
                choices.append(
                    _NativeAlternative(
                        assignment=UniTimeAssignment(
                            item_id=request.id,
                            section_ids=tuple(section.id for section in selected),
                        ),
                        time=None,
                        penalty=round(10000 * request.weight * course_index),
                    )
                )
                if len(choices) > maximum_per_request:
                    raise _ScaleGuard(
                        f"sectioning request {request.id} enrollment domain exceeds the scale guard"
                    )
    choices.append(
        _NativeAlternative(
            assignment=UniTimeAssignment(item_id=request.id, assigned=False),
            time=None,
            penalty=round(10000 * request.weight * (1000 + request.priority)),
        )
    )
    return tuple(choices)


def _sectioning_alternatives(
    problem: UniTimeSectioningProblem,
    deadline: float,
    *,
    maximum_alternatives: int,
) -> dict[str, tuple[_NativeAlternative, ...]]:
    result: dict[str, tuple[_NativeAlternative, ...]] = {}
    total = 0
    for student in problem.students:
        for request in student.requests:
            _check_build_deadline(deadline, "sectioning enrollment construction")
            if request.kind != "course":
                continue
            choices = _section_enrollment_options(
                problem, request, maximum_per_request=256
            )
            total += len(choices)
            if total > maximum_alternatives:
                raise _ScaleGuard(
                    "sectioning enrollment domain exceeds the configured scale guard"
                )
            result[request.id] = choices
    return result


def _build_sectioning_model(
    problem: UniTimeSectioningProblem,
    alternatives: Mapping[str, tuple[_NativeAlternative, ...]],
    deadline: float,
) -> tuple[cp_model.CpModel, dict[tuple[str, int], cp_model.IntVar]]:
    model = cp_model.CpModel()
    variables: dict[tuple[str, int], cp_model.IntVar] = {}
    objective: list[cp_model.LinearExpr] = []
    sections = {section.id: section for section in problem.sections}
    requests = {
        request.id: request for student in problem.students for request in student.requests
    }
    for request_id, choices in alternatives.items():
        selected = []
        for index, choice in enumerate(choices):
            variable = model.new_bool_var(f"s_{request_id}_{index}")
            variables[(request_id, index)] = variable
            selected.append(variable)
            if choice.penalty:
                objective.append(choice.penalty * variable)
        model.add_exactly_one(selected)
    weight_scale = 10000
    for section in problem.sections:
        if section.limit < 0:
            continue
        terms: list[cp_model.LinearExpr] = []
        maximum_weight = 0
        for request_id, choices in alternatives.items():
            coefficient = round(weight_scale * requests[request_id].weight)
            for index, choice in enumerate(choices):
                if section.id in choice.assignment.section_ids:
                    terms.append(coefficient * variables[(request_id, index)])
                    maximum_weight = max(maximum_weight, coefficient)
        if terms:
            model.add(
                sum(terms)
                <= math.floor(weight_scale * section.limit + maximum_weight)
            )
    for offering in problem.offerings:
        for config in offering.configurations:
            if config.limit < 0:
                continue
            config_sections = {
                section.id for subpart in config.subparts for section in subpart.sections
            }
            terms = []
            maximum_weight = 0
            for request_id, choices in alternatives.items():
                coefficient = round(weight_scale * requests[request_id].weight)
                for index, choice in enumerate(choices):
                    if set(choice.assignment.section_ids) & config_sections:
                        terms.append(coefficient * variables[(request_id, index)])
                        maximum_weight = max(maximum_weight, coefficient)
            if terms:
                model.add(
                    sum(terms)
                    <= math.floor(weight_scale * config.limit + maximum_weight)
                )
    for student in problem.students:
        fixed_free_times = [
            request.free_time
            for request in student.requests
            if request.kind == "free_time" and request.free_time is not None
        ]
        course_requests = [
            request for request in student.requests if request.kind == "course"
        ]
        for request in course_requests:
            for index, choice in enumerate(alternatives[request.id]):
                choice_times = [
                    sections[item].time
                    for item in choice.assignment.section_ids
                    if sections[item].time is not None
                ]
                if any(
                    _times_overlap(choice_time, free_time)
                    for choice_time in choice_times
                    for free_time in fixed_free_times
                ):
                    model.add(variables[(request.id, index)] == 0)
        for first_request, second_request in combinations(course_requests, 2):
            _check_build_deadline(deadline, "sectioning student conflicts")
            for first_index, first in enumerate(alternatives[first_request.id]):
                first_times = [
                    sections[item].time
                    for item in first.assignment.section_ids
                    if sections[item].time is not None
                ]
                for second_index, second in enumerate(alternatives[second_request.id]):
                    second_times = [
                        sections[item].time
                        for item in second.assignment.section_ids
                        if sections[item].time is not None
                    ]
                    if any(
                        _times_overlap(first_time, second_time)
                        for first_time in first_times
                        for second_time in second_times
                    ):
                        model.add(
                            variables[(first_request.id, first_index)]
                            + variables[(second_request.id, second_index)]
                            <= 1
                        )
    model.minimize(sum(objective) if objective else 0)
    return model, variables


def _non_solve_result(
    problem: UniTimeProblem,
    *,
    status: str,
    started: float,
    deadline: float,
    seed: int,
    workers: int,
    model_build_seconds: float = 0.0,
    reason: str,
) -> UniTimeNativeSolveResult:
    solution = problem.embedded_solution or _empty_solution(problem)
    if isinstance(problem, UniTimeCourseProblem):
        validation_size = len(problem.classes)
    elif isinstance(problem, UniTimeExamProblem):
        validation_size = len(problem.exams)
    elif len(problem.students) > 500:
        validation_size = 501
    else:
        validation_size = sum(len(student.requests) for student in problem.students)
    if validation_size <= 500 and time.perf_counter() < deadline:
        validation = validate_unitime_solution(problem, solution)
    else:
        validation = UniTimeValidation(
            score=UniTimeNativeScore(
                hard_violations=1,
                components=(("validation_skipped", 0.0),),
                native_total=0.0,
            ),
            errors=(f"solution validation skipped: {reason}",),
            unsupported_features=problem.unsupported_features,
        )
    elapsed = time.perf_counter() - started
    return UniTimeNativeSolveResult(
        status=status,
        solution=solution,
        validation=validation,
        objective_value=(validation.score.native_total if validation.native_feasible else None),
        best_bound=None,
        elapsed_seconds=elapsed,
        model_build_seconds=model_build_seconds,
        solver_wall_time_seconds=0.0,
        deadline_overrun_seconds=max(0.0, time.perf_counter() - deadline),
        seed=seed,
        workers=workers,
        telemetry={
            "reason": reason,
            "used_embedded_solution": problem.embedded_solution is not None,
            "officially_comparable": False,
            "score_scheme": "planora-unitime-native-v1",
        },
    )


def solve_unitime_native(
    problem: UniTimeProblem,
    *,
    time_limit_seconds: float = 5.0,
    deadline: float | None = None,
    seed: int = 17,
    workers: int = 1,
    maximum_items: int = 180,
    maximum_alternatives: int = 12000,
) -> UniTimeNativeSolveResult:
    """Solve the supported subset with a strict wall-clock budget and scale guard.

    The method is a small-instance reference implementation and an adapter for
    embedded UniTime solutions.  Large official instances return ``SCALE_GUARD``
    instead of silently truncating their domains.
    """

    started = time.perf_counter()
    if not math.isfinite(time_limit_seconds) or time_limit_seconds < 0:
        raise ValueError("time_limit_seconds must be finite and non-negative")
    if workers < 1:
        raise ValueError("workers must be at least one")
    if maximum_items < 1 or maximum_alternatives < 1:
        raise ValueError("scale guards must be positive")
    local_deadline = started + time_limit_seconds
    if deadline is not None:
        if not math.isfinite(deadline):
            raise ValueError("deadline must be finite")
        local_deadline = min(local_deadline, deadline)
    if time.perf_counter() >= local_deadline:
        return _non_solve_result(
            problem,
            status="DEADLINE_DURING_BUILD",
            started=started,
            deadline=local_deadline,
            seed=seed,
            workers=workers,
            reason="deadline exhausted before model construction",
        )
    if problem.unsupported_features:
        return _non_solve_result(
            problem,
            status="UNSUPPORTED",
            started=started,
            deadline=local_deadline,
            seed=seed,
            workers=workers,
            reason="problem contains unsupported semantics",
        )
    if isinstance(problem, UniTimeCourseProblem):
        item_count = len(problem.classes)
    elif isinstance(problem, UniTimeExamProblem):
        item_count = len(problem.exams)
    else:
        item_count = 0
        for student in problem.students:
            item_count += sum(request.kind == "course" for request in student.requests)
            if item_count > maximum_items:
                break
    if item_count > maximum_items:
        return _non_solve_result(
            problem,
            status="SCALE_GUARD",
            started=started,
            deadline=local_deadline,
            seed=seed,
            workers=workers,
            reason=f"{item_count} decision items exceed maximum_items={maximum_items}",
        )
    build_started = time.perf_counter()
    try:
        if isinstance(problem, UniTimeCourseProblem):
            alternatives = _course_alternatives(
                problem,
                local_deadline,
                maximum_alternatives=maximum_alternatives,
            )
            model, variables, _ = _build_course_model(
                problem, alternatives, local_deadline
            )
        elif isinstance(problem, UniTimeExamProblem):
            alternatives = _exam_alternatives(
                problem,
                local_deadline,
                maximum_alternatives=maximum_alternatives,
            )
            model, variables = _build_exam_model(problem, alternatives, local_deadline)
        else:
            alternatives = _sectioning_alternatives(
                problem,
                local_deadline,
                maximum_alternatives=maximum_alternatives,
            )
            model, variables = _build_sectioning_model(
                problem, alternatives, local_deadline
            )
    except _BuildDeadline as exc:
        return _non_solve_result(
            problem,
            status="DEADLINE_DURING_BUILD",
            started=started,
            deadline=local_deadline,
            seed=seed,
            workers=workers,
            model_build_seconds=time.perf_counter() - build_started,
            reason=f"deadline exhausted during {exc}",
        )
    except _ScaleGuard as exc:
        return _non_solve_result(
            problem,
            status="SCALE_GUARD",
            started=started,
            deadline=local_deadline,
            seed=seed,
            workers=workers,
            model_build_seconds=time.perf_counter() - build_started,
            reason=str(exc),
        )
    build_seconds = time.perf_counter() - build_started
    remaining = local_deadline - time.perf_counter()
    if remaining <= 0.002:
        return _non_solve_result(
            problem,
            status="DEADLINE_DURING_BUILD",
            started=started,
            deadline=local_deadline,
            seed=seed,
            workers=workers,
            model_build_seconds=build_seconds,
            reason="no search budget remains after model construction",
        )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.001, remaining - 0.001)
    solver.parameters.random_seed = int(seed)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.log_search_progress = False
    search_started = time.perf_counter()
    raw_status = solver.solve(model)
    solver_seconds = time.perf_counter() - search_started
    status = solver.status_name(raw_status)
    if raw_status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        return _non_solve_result(
            problem,
            status=status,
            started=started,
            deadline=local_deadline,
            seed=seed,
            workers=workers,
            model_build_seconds=build_seconds,
            reason="CP-SAT did not return a feasible assignment",
        )
    assignments: list[UniTimeAssignment] = []
    for item_id, choices in alternatives.items():
        selected = [
            choice.assignment
            for index, choice in enumerate(choices)
            if solver.boolean_value(variables[(item_id, index)])
        ]
        if len(selected) != 1:
            return _non_solve_result(
                problem,
                status="INVALID_SOLVER_OUTPUT",
                started=started,
                deadline=local_deadline,
                seed=seed,
                workers=workers,
                model_build_seconds=build_seconds,
                reason=f"CP-SAT selected {len(selected)} alternatives for {item_id}",
            )
        assignments.append(selected[0])
    if isinstance(problem, UniTimeSectioningProblem):
        assignments.extend(
            UniTimeAssignment(item_id=request.id, assigned=True)
            for student in problem.students
            for request in student.requests
            if request.kind == "free_time"
        )
    solution = UniTimeSolution(kind=problem.kind, assignments=tuple(assignments))
    validation = validate_unitime_solution(problem, solution)
    elapsed = time.perf_counter() - started
    if validation.errors:
        status = "INVALID_SOLVER_OUTPUT"
    return UniTimeNativeSolveResult(
        status=status,
        solution=solution,
        validation=validation,
        objective_value=validation.score.native_total,
        best_bound=float(solver.best_objective_bound),
        elapsed_seconds=elapsed,
        model_build_seconds=build_seconds,
        solver_wall_time_seconds=solver_seconds,
        deadline_overrun_seconds=max(0.0, time.perf_counter() - local_deadline),
        seed=seed,
        workers=workers,
        telemetry={
            "items": item_count,
            "alternatives": sum(len(items) for items in alternatives.values()),
            "branches": int(solver.num_branches),
            "conflicts": int(solver.num_conflicts),
            "officially_comparable": False,
            "score_scheme": "planora-unitime-native-v1",
        },
    )


def write_unitime_solution_xml(
    path: str | Path,
    problem: UniTimeProblem,
    solution: UniTimeSolution,
    *,
    sectioning_solution_mode: Literal["best", "current", "initial"] = "best",
    allow_unsupported: bool = False,
) -> None:
    """Write assignments back into the corresponding UniTime XML dialect.

    The original instance is used as the lossless carrier, mirroring CPSolver's
    own solution files.  Unsupported semantics require an explicit opt-in.
    """

    validation = validate_unitime_solution(problem, solution)
    if validation.errors:
        raise ValueError(
            "Cannot write an invalid UniTime native solution: " + validation.errors[0]
        )
    if problem.unsupported_features and not allow_unsupported:
        raise ValueError(
            "Cannot claim a complete UniTime solution while unsupported semantics remain"
        )
    _, root = _secure_xml_root(problem.source_path)
    assignments = solution.by_item()
    if isinstance(problem, UniTimeCourseProblem):
        classes_block = _child(root, "classes")
        if classes_block is None:
            raise ValueError("Source course XML no longer contains classes")
        for class_element in _children(classes_block, "class"):
            class_id = _required(class_element, "id")
            assignment = assignments[class_id]
            for item in class_element:
                if _local_name(item.tag) in {"time", "room", "instructor"}:
                    item.attrib.pop("solution", None)
            if not assignment.assigned:
                continue
            time_index = int((assignment.time_id or "").rsplit(":t", 1)[-1])
            time_elements = _children(class_element, "time")
            if not 0 <= time_index < len(time_elements):
                raise ValueError(f"Course assignment {class_id} has an invalid time id")
            time_elements[time_index].set("solution", "true")
            selected_rooms = set(assignment.room_ids)
            for room_element in _children(class_element, "room"):
                if room_element.get("id") in selected_rooms:
                    room_element.set("solution", "true")
            for instructor_element in _children(class_element, "instructor"):
                instructor_element.set("solution", "true")
    elif isinstance(problem, UniTimeExamProblem):
        exams_block = _child(root, "exams")
        if exams_block is None:
            raise ValueError("Source examination XML no longer contains exams")
        for exam_element in _children(exams_block, "exam"):
            exam_id = _required(exam_element, "id")
            for old in _children(exam_element, "assignment"):
                exam_element.remove(old)
            assignment = assignments[exam_id]
            if not assignment.assigned:
                continue
            assignment_element = etree.SubElement(exam_element, "assignment")
            etree.SubElement(
                assignment_element, "period", id=str(assignment.time_id)
            )
            for room_id in assignment.room_ids:
                etree.SubElement(assignment_element, "room", id=room_id)
    else:
        students_block = _child(root, "students")
        if students_block is None:
            raise ValueError("Source student-sectioning XML no longer contains students")
        for student_element in _children(students_block, "student"):
            for request_element in student_element:
                if _local_name(request_element.tag) not in {"course", "freeTime"}:
                    continue
                request_id = _required(request_element, "id")
                for old in _children(request_element, sectioning_solution_mode):
                    request_element.remove(old)
                assignment = assignments.get(request_id)
                if assignment is None or not assignment.assigned:
                    continue
                solution_element = etree.SubElement(
                    request_element, sectioning_solution_mode
                )
                for section_id in assignment.section_ids:
                    etree.SubElement(solution_element, "section", id=section_id)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    etree.ElementTree(root).write(
        str(destination),
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )


# Backwards-friendly benchmark entry names.
parse_unitime_native = parse_unitime_xml
validate_unitime_native = validate_unitime_solution
score_unitime_native = score_unitime_solution


__all__ = [
    "UniTimeAssignment",
    "UniTimeConfiguration",
    "UniTimeCourseClass",
    "UniTimeCourseConstraint",
    "UniTimeCourseProblem",
    "UniTimeCourseStudent",
    "UniTimeExam",
    "UniTimeExamConstraint",
    "UniTimeExamPeriod",
    "UniTimeExamPerson",
    "UniTimeExamProblem",
    "UniTimeNativeScore",
    "UniTimeNativeSolveResult",
    "UniTimeOffering",
    "UniTimeProblem",
    "UniTimeRoom",
    "UniTimeRoomOption",
    "UniTimeSection",
    "UniTimeSectioningProblem",
    "UniTimeSectioningRequest",
    "UniTimeSectioningStudent",
    "UniTimeSolution",
    "UniTimeSubpart",
    "UniTimeTime",
    "UniTimeValidation",
    "parse_unitime_course_xml",
    "parse_unitime_exam_xml",
    "parse_unitime_native",
    "parse_unitime_sectioning_xml",
    "parse_unitime_xml",
    "score_unitime_native",
    "score_unitime_solution",
    "solve_unitime_native",
    "summarize_unitime_problem",
    "validate_unitime_native",
    "validate_unitime_solution",
    "write_unitime_solution_xml",
]
