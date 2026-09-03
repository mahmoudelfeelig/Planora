from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from itertools import combinations, product
from pathlib import Path
import re
import time
from typing import Any, Iterable, Mapping, Sequence
from xml.etree import ElementTree

from ortools.sat.python import cp_model


AttributePairs = tuple[tuple[str, str], ...]


_DISTRIBUTION_PARAMETER_COUNTS = {
    "SameStart": 0,
    "SameTime": 0,
    "DifferentTime": 0,
    "SameDays": 0,
    "DifferentDays": 0,
    "SameWeeks": 0,
    "DifferentWeeks": 0,
    "SameRoom": 0,
    "DifferentRoom": 0,
    "Overlap": 0,
    "NotOverlap": 0,
    "SameAttendees": 0,
    "Precedence": 0,
    "WorkDay": 1,
    "MinGap": 1,
    "MaxDays": 1,
    "MaxDayLoad": 1,
    "MaxBreaks": 2,
    "MaxBlock": 2,
}
_PAIR_DISTRIBUTIONS = frozenset(
    {
        "SameStart",
        "SameTime",
        "DifferentTime",
        "SameDays",
        "DifferentDays",
        "SameWeeks",
        "DifferentWeeks",
        "SameRoom",
        "DifferentRoom",
        "Overlap",
        "NotOverlap",
        "SameAttendees",
        "Precedence",
        "WorkDay",
        "MinGap",
    }
)
_DISTRIBUTION_PATTERN = re.compile(r"^([A-Za-z]+)(?:\(([0-9]+(?:,[0-9]+)*)\))?$")
ITC2019_AUTO_CARTESIAN_DOMAIN_THRESHOLD = 50_000
ITC2019_SECTIONING_CP_ENROLLMENT_THRESHOLD = 250_000


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].lower()


def _children(element: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    expected = name.lower()
    return [child for child in element if _local_name(child.tag) == expected]


def _child(
    element: ElementTree.Element,
    name: str,
) -> ElementTree.Element | None:
    children = _children(element, name)
    return children[0] if children else None


def _required_attribute(element: ElementTree.Element, name: str) -> str:
    value = element.attrib.get(name)
    if value is None or not str(value).strip():
        raise ValueError(
            f"ITC-2019 <{_local_name(element.tag)}> is missing required "
            f"attribute {name!r}"
        )
    return str(value)


def _integer_attribute(
    element: ElementTree.Element,
    name: str,
    *,
    default: int | None = None,
) -> int:
    raw = element.attrib.get(name)
    if raw is None:
        if default is None:
            _required_attribute(element, name)
        return int(default)
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"ITC-2019 <{_local_name(element.tag)}> attribute {name!r} "
            f"must be an integer, got {raw!r}"
        ) from exc


def _boolean_attribute(
    element: ElementTree.Element,
    name: str,
    *,
    default: bool,
) -> bool:
    raw = element.attrib.get(name)
    if raw is None:
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ValueError(
        f"ITC-2019 <{_local_name(element.tag)}> attribute {name!r} "
        f"must be true or false, got {raw!r}"
    )


def _extra_attributes(
    element: ElementTree.Element,
    known: Iterable[str],
) -> AttributePairs:
    known_set = set(known)
    return tuple(
        sorted(
            (str(key), str(value))
            for key, value in element.attrib.items()
            if key not in known_set
        )
    )


def _validate_binary_mask(value: str, *, field: str, expected_length: int) -> None:
    if len(value) != expected_length or any(
        character not in {"0", "1"} for character in value
    ):
        raise ValueError(
            f"ITC-2019 {field} must be a {expected_length}-character binary mask, "
            f"got {value!r}"
        )


def _distribution_spec(value: str) -> tuple[str, tuple[int, ...]]:
    """Parse one official distribution spelling and reject unknown semantics.

    ITC-2019 deliberately embeds integer parameters in the type attribute.  Keeping
    this parser strict prevents a misspelled or future constraint from being silently
    treated as satisfied by either the scorer or the native solver.
    """

    match = _DISTRIBUTION_PATTERN.fullmatch(str(value).strip())
    if match is None:
        raise ValueError(f"Unsupported ITC-2019 distribution type {value!r}")
    base = match.group(1)
    expected = _DISTRIBUTION_PARAMETER_COUNTS.get(base)
    if expected is None:
        raise ValueError(f"Unsupported ITC-2019 distribution type {value!r}")
    raw_parameters = match.group(2)
    parameters = (
        tuple(int(item) for item in raw_parameters.split(","))
        if raw_parameters is not None
        else ()
    )
    if len(parameters) != expected:
        raise ValueError(
            f"ITC-2019 distribution {base} expects {expected} parameter(s), "
            f"got {value!r}"
        )
    return base, parameters


@dataclass(frozen=True)
class ITC2019OptimizationWeights:
    time: int = 2
    room: int = 1
    distribution: int = 10
    student: int = 5
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class ITC2019Travel:
    room_id: str
    value: int
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class ITC2019Unavailable:
    days: str
    start: int
    length: int
    weeks: str
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class ITC2019Room:
    id: str
    capacity: int
    travel: tuple[ITC2019Travel, ...]
    unavailable: tuple[ITC2019Unavailable, ...]
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class ITC2019TimeOption:
    days: str
    start: int
    length: int
    weeks: str
    penalty: int = 0
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class ITC2019RoomOption:
    room_id: str
    penalty: int = 0
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class ITC2019Class:
    id: str
    limit: int
    parent_id: str | None
    room_required: bool
    time_options: tuple[ITC2019TimeOption, ...]
    room_options: tuple[ITC2019RoomOption, ...]
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class ITC2019Subpart:
    id: str
    classes: tuple[ITC2019Class, ...]
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class ITC2019Configuration:
    id: str
    subparts: tuple[ITC2019Subpart, ...]
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class ITC2019Course:
    id: str
    configurations: tuple[ITC2019Configuration, ...]
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class ITC2019Distribution:
    type: str
    required: bool
    penalty: int
    class_ids: tuple[str, ...]
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class ITC2019Student:
    id: str
    course_ids: tuple[str, ...]
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True)
class ITC2019Problem:
    name: str
    nr_days: int
    slots_per_day: int
    nr_weeks: int
    optimization: ITC2019OptimizationWeights
    rooms: tuple[ITC2019Room, ...]
    courses: tuple[ITC2019Course, ...]
    distributions: tuple[ITC2019Distribution, ...]
    students: tuple[ITC2019Student, ...]
    source_path: str
    extra_attributes: AttributePairs = ()

    @property
    def classes(self) -> tuple[ITC2019Class, ...]:
        return tuple(
            klass
            for course in self.courses
            for configuration in course.configurations
            for subpart in configuration.subparts
            for klass in subpart.classes
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ITC2019ConversionSummary:
    instance_name: str
    rooms: int
    travel_entries: int
    unavailable_periods: int
    courses: int
    configurations: int
    subparts: int
    classes: int
    parent_relations: int
    time_options: int
    room_options: int
    distributions: int
    required_distributions: int
    soft_distributions: int
    students: int
    course_requests: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ITC2019ClassPlacement:
    class_id: str
    days: str
    start: int
    weeks: str
    room_id: str | None = None


@dataclass(frozen=True)
class ITC2019Solution:
    placements: tuple[ITC2019ClassPlacement, ...]
    student_classes: dict[str, tuple[str, ...]]
    metadata: AttributePairs = ()


@dataclass(frozen=True)
class ITC2019DistributionScore:
    constraint_type: str
    required: bool
    violation_units: int
    penalty: int

    @property
    def is_hard_violation(self) -> bool:
        return self.required and self.violation_units > 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ITC2019Objective:
    time: int
    room: int
    distribution: int
    student: int
    weighted_time: int
    weighted_room: int
    weighted_distribution: int
    weighted_student: int
    total: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ITC2019NativeSolveResult:
    status: str
    placements: tuple[ITC2019ClassPlacement, ...]
    student_classes: dict[str, tuple[str, ...]]
    objective: ITC2019Objective | None
    best_bound: float | None
    wall_time_seconds: float
    model_build_seconds: float
    solver_wall_time_seconds: float
    conflicts: int
    branches: int
    deterministic_seed: int
    workers: int
    validation_errors: tuple[str, ...] = ()
    unsupported_reasons: tuple[str, ...] = ()
    formulation: str = "cartesian_joint_v1"
    sectioning_mode: str = "joint"
    time_domain_values: int = 0
    room_domain_values: int = 0
    predicate_table_cells: int = 0
    sparse_room_constraints: int = 0
    requested_formulation: str = ""
    effective_formulation: str = ""
    formulation_selection_reason: str = ""
    raw_cartesian_domain_values: int | None = None
    auto_cartesian_domain_threshold: int | None = None

    @property
    def is_feasible(self) -> bool:
        return (
            self.status in {"FEASIBLE", "OPTIMAL"}
            and self.objective is not None
            and not self.validation_errors
            and not self.unsupported_reasons
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ITC2019FactorizedScaleEstimate:
    """Model-free admission estimate for the exact factorized formulation."""

    admitted: bool
    sectioning_mode: str
    time_domain_values: int
    room_domain_values: int
    cartesian_domain_values: int
    predicate_table_cells: int
    sparse_room_constraints: int
    joint_student_conjunctions: int
    maximum_group_table_rows: int
    unsupported_reasons: tuple[str, ...] = ()

    @property
    def factorized_domain_values(self) -> int:
        return self.time_domain_values + self.room_domain_values

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _ITC2019Alternative:
    placement: ITC2019ClassPlacement
    time: ITC2019TimeOption
    time_penalty: int
    room_penalty: int


@dataclass(frozen=True)
class ITC2019SectioningResult:
    status: str
    student_classes: dict[str, tuple[str, ...]]
    student_conflicts: int | None
    weighted_objective: int | None
    best_bound: float | None
    wall_time_seconds: float
    validation_errors: tuple[str, ...] = ()
    model_build_seconds: float = 0.0
    solver_wall_time_seconds: float = 0.0

    @property
    def is_feasible(self) -> bool:
        return self.status in {"FEASIBLE", "OPTIMAL"} and not self.validation_errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ITC2019Inspection:
    path: str
    root_tag: str
    instance_name: str
    element_counts: dict[str, int]
    distribution_types: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_itc2019_xml(path: str | Path) -> ITC2019Inspection:
    source = Path(path)
    root = ElementTree.parse(source).getroot()
    counts = Counter(_local_name(element.tag) for element in root.iter())
    distribution_types = Counter()
    for element in root.iter():
        if _local_name(element.tag) in {"distribution", "constraint"}:
            distribution_type = element.attrib.get("type") or element.attrib.get("name")
            if distribution_type:
                distribution_types[str(distribution_type)] += 1
    instance_name = (
        root.attrib.get("name")
        or root.attrib.get("instance")
        or root.attrib.get("id")
        or source.stem
    )
    return ITC2019Inspection(
        path=str(source.resolve()),
        root_tag=_local_name(root.tag),
        instance_name=str(instance_name),
        element_counts=dict(sorted(counts.items())),
        distribution_types=dict(sorted(distribution_types.items())),
    )


def _parse_time_option(
    element: ElementTree.Element,
    *,
    nr_days: int,
    nr_weeks: int,
) -> ITC2019TimeOption:
    days = _required_attribute(element, "days")
    weeks = element.attrib.get("weeks", "1" * nr_weeks)
    _validate_binary_mask(days, field="time days", expected_length=nr_days)
    _validate_binary_mask(weeks, field="time weeks", expected_length=nr_weeks)
    length = _integer_attribute(element, "length")
    if length <= 0:
        raise ValueError("ITC-2019 class time length must be positive")
    return ITC2019TimeOption(
        days=days,
        start=_integer_attribute(element, "start"),
        length=length,
        weeks=weeks,
        penalty=_integer_attribute(element, "penalty", default=0),
        extra_attributes=_extra_attributes(
            element,
            {"days", "start", "length", "weeks", "penalty"},
        ),
    )


def _parse_class(
    element: ElementTree.Element,
    *,
    nr_days: int,
    nr_weeks: int,
) -> ITC2019Class:
    limit = _integer_attribute(element, "limit")
    if limit < 0:
        raise ValueError("ITC-2019 class limit must be non-negative")
    room_required = _boolean_attribute(
        element,
        "room" if "room" in element.attrib else "rooms",
        default=True,
    )
    return ITC2019Class(
        id=_required_attribute(element, "id"),
        limit=limit,
        parent_id=element.attrib.get("parent"),
        room_required=room_required,
        time_options=tuple(
            _parse_time_option(time_element, nr_days=nr_days, nr_weeks=nr_weeks)
            for time_element in _children(element, "time")
        ),
        room_options=tuple(
            ITC2019RoomOption(
                room_id=_required_attribute(room_element, "id"),
                penalty=_integer_attribute(room_element, "penalty", default=0),
                extra_attributes=_extra_attributes(room_element, {"id", "penalty"}),
            )
            for room_element in _children(element, "room")
        ),
        extra_attributes=_extra_attributes(
            element,
            {"id", "limit", "parent", "room", "rooms"},
        ),
    )


def parse_itc2019_xml(path: str | Path) -> ITC2019Problem:
    """Parse an official ITC-2019 problem without flattening its sectioning model.

    IDs remain strings and every schema-level choice is retained: alternative course
    configurations, hierarchical subparts/classes, time and room domains, room travel
    and unavailability, distribution constraints, and individual course requests.
    """

    source = Path(path)
    root = ElementTree.parse(source).getroot()
    if _local_name(root.tag) != "problem":
        raise ValueError(
            f"Expected ITC-2019 <problem> root, got <{_local_name(root.tag)}>"
        )

    nr_days = _integer_attribute(root, "nrDays", default=7)
    slots_per_day = _integer_attribute(root, "slotsPerDay", default=288)
    nr_weeks = _integer_attribute(root, "nrWeeks", default=13)
    if nr_days <= 0 or slots_per_day <= 0 or nr_weeks <= 0:
        raise ValueError("ITC-2019 calendar dimensions must all be positive")
    all_weeks = "1" * nr_weeks

    optimization_element = _child(root, "optimization")
    if optimization_element is None:
        optimization = ITC2019OptimizationWeights()
    else:
        optimization = ITC2019OptimizationWeights(
            time=_integer_attribute(optimization_element, "time", default=2),
            room=_integer_attribute(optimization_element, "room", default=1),
            distribution=_integer_attribute(
                optimization_element, "distribution", default=10
            ),
            student=_integer_attribute(optimization_element, "student", default=5),
            extra_attributes=_extra_attributes(
                optimization_element,
                {"time", "room", "distribution", "student"},
            ),
        )

    rooms_element = _child(root, "rooms")
    rooms: list[ITC2019Room] = []
    for room_element in (
        _children(rooms_element, "room") if rooms_element is not None else []
    ):
        capacity = _integer_attribute(room_element, "capacity")
        if capacity < 0:
            raise ValueError("ITC-2019 room capacity must be non-negative")
        unavailable: list[ITC2019Unavailable] = []
        for unavailable_element in _children(room_element, "unavailable"):
            days = _required_attribute(unavailable_element, "days")
            weeks = unavailable_element.attrib.get("weeks", all_weeks)
            _validate_binary_mask(
                days, field="room-unavailable days", expected_length=nr_days
            )
            _validate_binary_mask(
                weeks, field="room-unavailable weeks", expected_length=nr_weeks
            )
            length = _integer_attribute(unavailable_element, "length")
            if length <= 0:
                raise ValueError("ITC-2019 room-unavailable length must be positive")
            unavailable.append(
                ITC2019Unavailable(
                    days=days,
                    start=_integer_attribute(unavailable_element, "start"),
                    length=length,
                    weeks=weeks,
                    extra_attributes=_extra_attributes(
                        unavailable_element,
                        {"days", "start", "length", "weeks"},
                    ),
                )
            )
        rooms.append(
            ITC2019Room(
                id=_required_attribute(room_element, "id"),
                capacity=capacity,
                travel=tuple(
                    ITC2019Travel(
                        room_id=_required_attribute(travel_element, "room"),
                        value=_integer_attribute(travel_element, "value"),
                        extra_attributes=_extra_attributes(
                            travel_element, {"room", "value"}
                        ),
                    )
                    for travel_element in _children(room_element, "travel")
                ),
                unavailable=tuple(unavailable),
                extra_attributes=_extra_attributes(room_element, {"id", "capacity"}),
            )
        )

    courses_element = _child(root, "courses")
    courses: list[ITC2019Course] = []
    for course_element in (
        _children(courses_element, "course") if courses_element is not None else []
    ):
        configurations: list[ITC2019Configuration] = []
        for configuration_element in _children(course_element, "config"):
            subparts: list[ITC2019Subpart] = []
            for subpart_element in _children(configuration_element, "subpart"):
                subparts.append(
                    ITC2019Subpart(
                        id=_required_attribute(subpart_element, "id"),
                        classes=tuple(
                            _parse_class(
                                class_element,
                                nr_days=nr_days,
                                nr_weeks=nr_weeks,
                            )
                            for class_element in _children(subpart_element, "class")
                        ),
                        extra_attributes=_extra_attributes(subpart_element, {"id"}),
                    )
                )
            configurations.append(
                ITC2019Configuration(
                    id=_required_attribute(configuration_element, "id"),
                    subparts=tuple(subparts),
                    extra_attributes=_extra_attributes(configuration_element, {"id"}),
                )
            )
        courses.append(
            ITC2019Course(
                id=_required_attribute(course_element, "id"),
                configurations=tuple(configurations),
                extra_attributes=_extra_attributes(course_element, {"id"}),
            )
        )

    distributions_element = _child(root, "distributions")
    distributions: list[ITC2019Distribution] = []
    for distribution_element in (
        _children(distributions_element, "distribution")
        if distributions_element is not None
        else []
    ):
        distribution_type = _required_attribute(distribution_element, "type")
        _distribution_spec(distribution_type)
        penalty = _integer_attribute(distribution_element, "penalty", default=0)
        if penalty < 0:
            raise ValueError("ITC-2019 distribution penalty must be non-negative")
        distributions.append(
            ITC2019Distribution(
                type=distribution_type,
                required=_boolean_attribute(
                    distribution_element,
                    "required",
                    default=False,
                ),
                penalty=penalty,
                class_ids=tuple(
                    _required_attribute(class_element, "id")
                    for class_element in _children(distribution_element, "class")
                ),
                extra_attributes=_extra_attributes(
                    distribution_element,
                    {"type", "required", "penalty"},
                ),
            )
        )

    students_element = _child(root, "students")
    students = tuple(
        ITC2019Student(
            id=_required_attribute(student_element, "id"),
            course_ids=tuple(
                _required_attribute(course_element, "id")
                for course_element in _children(student_element, "course")
            ),
            extra_attributes=_extra_attributes(student_element, {"id"}),
        )
        for student_element in (
            _children(students_element, "student")
            if students_element is not None
            else []
        )
    )

    problem = ITC2019Problem(
        name=str(root.attrib.get("name") or source.stem),
        nr_days=nr_days,
        slots_per_day=slots_per_day,
        nr_weeks=nr_weeks,
        optimization=optimization,
        rooms=tuple(rooms),
        courses=tuple(courses),
        distributions=tuple(distributions),
        students=students,
        source_path=str(source.resolve()),
        extra_attributes=_extra_attributes(
            root,
            {"name", "nrDays", "slotsPerDay", "nrWeeks"},
        ),
    )
    reference_errors = _validate_problem_references(problem)
    if reference_errors:
        raise ValueError("Invalid ITC-2019 problem: " + "; ".join(reference_errors))
    return problem


def _duplicates(values: Iterable[str]) -> list[str]:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)


def _validate_problem_references(problem: ITC2019Problem) -> list[str]:
    errors: list[str] = []
    room_ids = {room.id for room in problem.rooms}
    course_ids = {course.id for course in problem.courses}
    classes = problem.classes
    class_ids = {klass.id for klass in classes}

    for name, value in (
        ("time", problem.optimization.time),
        ("room", problem.optimization.room),
        ("distribution", problem.optimization.distribution),
        ("student", problem.optimization.student),
    ):
        if value < 0:
            errors.append(f"optimization weight {name} is negative")

    for label, values in (
        ("room", (room.id for room in problem.rooms)),
        ("course", (course.id for course in problem.courses)),
        ("class", (klass.id for klass in classes)),
        ("student", (student.id for student in problem.students)),
    ):
        duplicate_ids = _duplicates(values)
        if duplicate_ids:
            errors.append(f"duplicate {label} ids: {', '.join(duplicate_ids)}")

    class_context = _class_context(problem)
    for room in problem.rooms:
        travel_values: dict[str, set[int]] = defaultdict(set)
        for travel in room.travel:
            travel_values[travel.room_id].add(travel.value)
            if travel.room_id not in room_ids:
                errors.append(
                    f"room {room.id} travels to unknown room {travel.room_id}"
                )
            if travel.value < 0:
                errors.append(f"room {room.id} has negative travel value")
        if any(len(values) > 1 for values in travel_values.values()):
            errors.append(f"room {room.id} has ambiguous travel values")
        for unavailable in room.unavailable:
            if unavailable.start < 0 or (
                unavailable.start + unavailable.length > problem.slots_per_day
            ):
                errors.append(f"room {room.id} has unavailability outside the day")
    for klass in classes:
        if not klass.time_options:
            errors.append(f"class {klass.id} has no time options")
        if klass.room_required and not klass.room_options:
            errors.append(f"class {klass.id} requires a room but has no room options")
        for room_option in klass.room_options:
            if room_option.room_id not in room_ids:
                errors.append(
                    f"class {klass.id} references unknown room {room_option.room_id}"
                )
            if room_option.penalty < 0:
                errors.append(f"class {klass.id} has a negative room penalty")
        room_costs: dict[str, set[int]] = defaultdict(set)
        for room_option in klass.room_options:
            room_costs[room_option.room_id].add(room_option.penalty)
        if any(len(costs) > 1 for costs in room_costs.values()):
            errors.append(f"class {klass.id} has ambiguous room penalties")
        time_lengths: dict[tuple[str, int, str], set[int]] = defaultdict(set)
        for time_option in klass.time_options:
            time_lengths[(time_option.days, time_option.start, time_option.weeks)].add(
                time_option.length
            )
            if time_option.penalty < 0:
                errors.append(f"class {klass.id} has a negative time penalty")
            if time_option.start < 0 or (
                time_option.start + time_option.length > problem.slots_per_day
            ):
                errors.append(f"class {klass.id} has a time outside the teaching day")
            if "1" not in time_option.days or "1" not in time_option.weeks:
                errors.append(f"class {klass.id} has an empty meeting pattern")
        if any(len(values) > 1 for values in time_lengths.values()):
            errors.append(f"class {klass.id} has ambiguous time lengths")
        if klass.parent_id is not None:
            if klass.parent_id not in class_ids:
                errors.append(f"class {klass.id} has unknown parent {klass.parent_id}")
            elif (
                class_context.get(klass.parent_id, ())[:2]
                != class_context.get(klass.id, ())[:2]
            ):
                errors.append(
                    f"class {klass.id} parent {klass.parent_id} is outside its configuration"
                )
    for distribution in problem.distributions:
        try:
            _distribution_spec(distribution.type)
        except ValueError as exc:
            errors.append(str(exc))
        if distribution.penalty < 0:
            errors.append(f"distribution {distribution.type} has a negative penalty")
        for class_id in distribution.class_ids:
            if class_id not in class_ids:
                errors.append(
                    f"distribution {distribution.type} references unknown class {class_id}"
                )
    for student in problem.students:
        duplicate_requests = _duplicates(student.course_ids)
        if duplicate_requests:
            errors.append(
                f"student {student.id} has duplicate requests: {', '.join(duplicate_requests)}"
            )
        for course_id in student.course_ids:
            if course_id not in course_ids:
                errors.append(
                    f"student {student.id} requests unknown course {course_id}"
                )
    for course in problem.courses:
        if not course.configurations:
            errors.append(f"course {course.id} has no configurations")
        duplicate_configurations = _duplicates(
            configuration.id for configuration in course.configurations
        )
        if duplicate_configurations:
            errors.append(
                f"course {course.id} has duplicate configuration ids: "
                + ", ".join(duplicate_configurations)
            )
        for configuration in course.configurations:
            if not configuration.subparts:
                errors.append(
                    f"configuration {configuration.id} of course {course.id} has no subparts"
                )
            duplicate_subparts = _duplicates(
                subpart.id for subpart in configuration.subparts
            )
            if duplicate_subparts:
                errors.append(
                    f"configuration {configuration.id} has duplicate subpart ids: "
                    + ", ".join(duplicate_subparts)
                )
            for subpart in configuration.subparts:
                if not subpart.classes:
                    errors.append(f"subpart {subpart.id} has no classes")
    return errors


def summarize_itc2019_problem(problem: ITC2019Problem) -> ITC2019ConversionSummary:
    configurations = [
        configuration
        for course in problem.courses
        for configuration in course.configurations
    ]
    subparts = [
        subpart
        for configuration in configurations
        for subpart in configuration.subparts
    ]
    classes = [klass for subpart in subparts for klass in subpart.classes]
    return ITC2019ConversionSummary(
        instance_name=problem.name,
        rooms=len(problem.rooms),
        travel_entries=sum(len(room.travel) for room in problem.rooms),
        unavailable_periods=sum(len(room.unavailable) for room in problem.rooms),
        courses=len(problem.courses),
        configurations=len(configurations),
        subparts=len(subparts),
        classes=len(classes),
        parent_relations=sum(klass.parent_id is not None for klass in classes),
        time_options=sum(len(klass.time_options) for klass in classes),
        room_options=sum(len(klass.room_options) for klass in classes),
        distributions=len(problem.distributions),
        required_distributions=sum(
            distribution.required for distribution in problem.distributions
        ),
        soft_distributions=sum(
            not distribution.required for distribution in problem.distributions
        ),
        students=len(problem.students),
        course_requests=sum(len(student.course_ids) for student in problem.students),
    )


def _class_context(
    problem: ITC2019Problem,
) -> dict[str, tuple[str, str, str, ITC2019Class]]:
    return {
        klass.id: (course.id, configuration.id, subpart.id, klass)
        for course in problem.courses
        for configuration in course.configurations
        for subpart in configuration.subparts
        for klass in subpart.classes
    }


def _placement_map(
    placements: Mapping[str, ITC2019ClassPlacement] | Sequence[ITC2019ClassPlacement],
) -> dict[str, ITC2019ClassPlacement]:
    if isinstance(placements, Mapping):
        result = dict(placements)
        for key, placement in result.items():
            if str(key) != placement.class_id:
                raise ValueError(
                    f"Placement key {key!r} does not match class id {placement.class_id!r}"
                )
        return result
    result: dict[str, ITC2019ClassPlacement] = {}
    for placement in placements:
        if placement.class_id in result:
            raise ValueError(f"Duplicate placement for class {placement.class_id}")
        result[placement.class_id] = placement
    return result


def _matching_time_option(
    klass: ITC2019Class,
    placement: ITC2019ClassPlacement,
) -> ITC2019TimeOption | None:
    candidates = [
        option
        for option in klass.time_options
        if option.days == placement.days
        and option.start == placement.start
        and option.weeks == placement.weeks
    ]
    # A handful of public instances repeat an indistinguishable time assignment
    # with different penalties.  The solution format cannot name the duplicate;
    # canonicalize it to the least-penalized equivalent assignment.
    return min(candidates, key=lambda option: option.penalty) if candidates else None


def _masks_overlap(first: str, second: str) -> bool:
    return any(left == right == "1" for left, right in zip(first, second, strict=True))


def _intervals_overlap(
    first_start: int, first_length: int, second_start: int, second_length: int
) -> bool:
    return (
        first_start < second_start + second_length
        and second_start < first_start + first_length
    )


def _mask_subset(first: str, second: str) -> bool:
    return all(
        left != "1" or right == "1" for left, right in zip(first, second, strict=True)
    )


def _first_set(mask: str) -> int:
    try:
        return mask.index("1")
    except ValueError as exc:
        raise ValueError("ITC-2019 meeting masks must contain an active bit") from exc


def _pair_distribution_satisfied(
    base: str,
    parameters: tuple[int, ...],
    first_placement: ITC2019ClassPlacement,
    first_time: ITC2019TimeOption,
    second_placement: ITC2019ClassPlacement,
    second_time: ITC2019TimeOption,
    travel: Mapping[tuple[str, str], int],
) -> bool:
    first_end = first_time.start + first_time.length
    second_end = second_time.start + second_time.length
    if base == "SameStart":
        return first_time.start == second_time.start
    if base == "SameTime":
        return (first_time.start <= second_time.start and second_end <= first_end) or (
            second_time.start <= first_time.start and first_end <= second_end
        )
    if base == "DifferentTime":
        return first_end <= second_time.start or second_end <= first_time.start
    if base == "SameDays":
        return _mask_subset(first_time.days, second_time.days) or _mask_subset(
            second_time.days,
            first_time.days,
        )
    if base == "DifferentDays":
        return not _masks_overlap(first_time.days, second_time.days)
    if base == "SameWeeks":
        return _mask_subset(first_time.weeks, second_time.weeks) or _mask_subset(
            second_time.weeks,
            first_time.weeks,
        )
    if base == "DifferentWeeks":
        return not _masks_overlap(first_time.weeks, second_time.weeks)
    if base == "SameRoom":
        return first_placement.room_id == second_placement.room_id
    if base == "DifferentRoom":
        return first_placement.room_id != second_placement.room_id
    if base == "Overlap":
        return (
            _masks_overlap(first_time.days, second_time.days)
            and _masks_overlap(first_time.weeks, second_time.weeks)
            and _intervals_overlap(
                first_time.start,
                first_time.length,
                second_time.start,
                second_time.length,
            )
        )
    if base == "NotOverlap":
        return not (
            _masks_overlap(first_time.days, second_time.days)
            and _masks_overlap(first_time.weeks, second_time.weeks)
            and _intervals_overlap(
                first_time.start,
                first_time.length,
                second_time.start,
                second_time.length,
            )
        )
    if base == "SameAttendees":
        if not _masks_overlap(first_time.days, second_time.days) or not _masks_overlap(
            first_time.weeks,
            second_time.weeks,
        ):
            return True
        first_room = first_placement.room_id
        second_room = second_placement.room_id
        distance = 0
        if first_room is not None and second_room is not None:
            distance = travel.get(
                (first_room, second_room),
                travel.get((second_room, first_room), 0),
            )
        return (
            first_end + distance <= second_time.start
            or second_end + distance <= first_time.start
        )
    if base == "Precedence":
        first_week = _first_set(first_time.weeks)
        second_week = _first_set(second_time.weeks)
        if first_week != second_week:
            return first_week < second_week
        first_day = _first_set(first_time.days)
        second_day = _first_set(second_time.days)
        if first_day != second_day:
            return first_day < second_day
        return first_end <= second_time.start
    if base == "WorkDay":
        (maximum_span,) = parameters
        return (
            not _masks_overlap(first_time.days, second_time.days)
            or not _masks_overlap(first_time.weeks, second_time.weeks)
            or max(first_end, second_end) - min(first_time.start, second_time.start)
            <= maximum_span
        )
    if base == "MinGap":
        (minimum_gap,) = parameters
        return (
            not _masks_overlap(first_time.days, second_time.days)
            or not _masks_overlap(first_time.weeks, second_time.weeks)
            or first_end + minimum_gap <= second_time.start
            or second_end + minimum_gap <= first_time.start
        )
    raise ValueError(f"Unsupported pairwise ITC-2019 distribution {base!r}")


def _merge_blocks(
    intervals: Sequence[tuple[int, int]],
    maximum_gap: int,
) -> list[tuple[int, int, int]]:
    """Merge intervals using the official inclusive end-plus-gap relation.

    The third tuple member retains the number of original classes, which is needed
    for MaxBlock's explicit exemption for a single class longer than the limit.
    """

    blocks: list[tuple[int, int, int]] = []
    # The published formula passes a mathematical set of (start, end) pairs to
    # MergeBlocks.  Coincident classes therefore form one interval, an important
    # detail for MaxBlock's single-block exemption.
    for start, end in sorted(set(intervals)):
        if blocks and start <= blocks[-1][1] + maximum_gap:
            previous_start, previous_end, members = blocks[-1]
            blocks[-1] = (previous_start, max(previous_end, end), members + 1)
        else:
            blocks.append((start, end, 1))
    return blocks


def _special_distribution_units(
    problem: ITC2019Problem,
    base: str,
    parameters: tuple[int, ...],
    class_ids: Sequence[str],
    resolved: Mapping[str, ITC2019TimeOption],
) -> int:
    if base == "MaxDays":
        (maximum_days,) = parameters
        used_days = {
            day
            for class_id in class_ids
            for day, active in enumerate(resolved[class_id].days)
            if active == "1"
        }
        return max(len(used_days) - maximum_days, 0)
    if base == "MaxDayLoad":
        (maximum_load,) = parameters
        return sum(
            max(
                sum(
                    resolved[class_id].length
                    for class_id in class_ids
                    if resolved[class_id].days[day] == "1"
                    and resolved[class_id].weeks[week] == "1"
                )
                - maximum_load,
                0,
            )
            for day in range(problem.nr_days)
            for week in range(problem.nr_weeks)
        )
    if base in {"MaxBreaks", "MaxBlock"}:
        first_parameter, maximum_gap = parameters
        total_excess = 0
        for day in range(problem.nr_days):
            for week in range(problem.nr_weeks):
                intervals = [
                    (
                        resolved[class_id].start,
                        resolved[class_id].start + resolved[class_id].length,
                    )
                    for class_id in class_ids
                    if resolved[class_id].days[day] == "1"
                    and resolved[class_id].weeks[week] == "1"
                ]
                blocks = _merge_blocks(intervals, maximum_gap)
                if base == "MaxBreaks":
                    total_excess += max(len(blocks) - (first_parameter + 1), 0)
                else:
                    total_excess += sum(
                        members >= 2 and end - start > first_parameter
                        for start, end, members in blocks
                    )
        return total_excess
    raise ValueError(f"Unsupported grouped ITC-2019 distribution {base!r}")


def evaluate_itc2019_distributions(
    problem: ITC2019Problem,
    placements: Mapping[str, ITC2019ClassPlacement] | Sequence[ITC2019ClassPlacement],
) -> tuple[ITC2019DistributionScore, ...]:
    """Evaluate every official distribution type used by the 36-instance corpus.

    This is an independent arithmetic evaluator: it consumes only resolved solution
    placements and does not reuse any CP-SAT objective variables.
    """

    by_class = _placement_map(placements)
    context = _class_context(problem)
    missing = sorted(set(context) - set(by_class))
    if missing:
        raise ValueError("placements are missing classes: " + ", ".join(missing))
    resolved: dict[str, ITC2019TimeOption] = {}
    for class_id, (_, _, _, klass) in context.items():
        option = _matching_time_option(klass, by_class[class_id])
        if option is None:
            raise ValueError(f"class {class_id} placement is outside its time domain")
        resolved[class_id] = option

    travel = _travel_values(problem)
    scores: list[ITC2019DistributionScore] = []
    for distribution in problem.distributions:
        base, parameters = _distribution_spec(distribution.type)
        # The public pu-proj-fal19 file repeats a few class references.  A
        # distribution is defined over a set of classes, so preserve the raw XML in
        # the parsed model while evaluating each referenced class once.
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        violation_units = 0
        penalty = 0
        if base in _PAIR_DISTRIBUTIONS:
            for first_index, second_index in combinations(range(len(class_ids)), 2):
                first_id = class_ids[first_index]
                second_id = class_ids[second_index]
                if not _pair_distribution_satisfied(
                    base,
                    parameters,
                    by_class[first_id],
                    resolved[first_id],
                    by_class[second_id],
                    resolved[second_id],
                    travel,
                ):
                    violation_units += 1
            if not distribution.required:
                penalty = distribution.penalty * violation_units
        elif base in {"MaxDays", "MaxDayLoad", "MaxBreaks", "MaxBlock"}:
            violation_units = _special_distribution_units(
                problem,
                base,
                parameters,
                class_ids,
                resolved,
            )
            if not distribution.required:
                if base in {"MaxDayLoad", "MaxBreaks", "MaxBlock"}:
                    penalty = distribution.penalty * violation_units // problem.nr_weeks
                else:
                    penalty = distribution.penalty * violation_units
        else:  # pragma: no cover - guarded by _distribution_spec
            raise ValueError(
                f"Unsupported ITC-2019 distribution type {distribution.type!r}"
            )
        scores.append(
            ITC2019DistributionScore(
                constraint_type=distribution.type,
                required=distribution.required,
                violation_units=violation_units,
                penalty=penalty,
            )
        )
    return tuple(scores)


def validate_itc2019_class_placements(
    problem: ITC2019Problem,
    placements: Mapping[str, ITC2019ClassPlacement] | Sequence[ITC2019ClassPlacement],
    *,
    require_complete: bool = True,
) -> list[str]:
    """Validate fixed class placements against domains and room hard constraints.

    This narrow validator is the resource/domain layer.  Use
    :func:`validate_itc2019_solution` for required distributions and sectioning too.
    """

    try:
        by_class = _placement_map(placements)
    except ValueError as exc:
        return [str(exc)]
    context = _class_context(problem)
    rooms = {room.id: room for room in problem.rooms}
    errors: list[str] = []
    unknown = sorted(set(by_class) - set(context))
    if unknown:
        errors.append("placements contain unknown classes: " + ", ".join(unknown))
    if require_complete:
        missing = sorted(set(context) - set(by_class))
        if missing:
            errors.append("placements are missing classes: " + ", ".join(missing))

    resolved: dict[str, ITC2019TimeOption] = {}
    for class_id, placement in by_class.items():
        if class_id not in context:
            continue
        klass = context[class_id][3]
        option = _matching_time_option(klass, placement)
        if option is None:
            errors.append(f"class {class_id} placement is outside its time domain")
            continue
        resolved[class_id] = option
        if klass.room_required and placement.room_id is None:
            errors.append(f"class {class_id} requires a room")
            continue
        if not klass.room_required and placement.room_id is not None:
            errors.append(f"class {class_id} must not have a room")
            continue
        if placement.room_id is None:
            continue
        allowed_rooms = {room_option.room_id for room_option in klass.room_options}
        if placement.room_id not in allowed_rooms:
            errors.append(
                f"class {class_id} room {placement.room_id} is outside its room domain"
            )
            continue
        room = rooms[placement.room_id]
        # ITC-2019 room domains are prefiltered for suitability.  The official
        # FAQ explicitly says validators must not compare either class limits
        # or assigned-student counts with the informational room capacity:
        # https://www.itc2019.org/faq
        for unavailable in room.unavailable:
            if (
                _masks_overlap(option.days, unavailable.days)
                and _masks_overlap(option.weeks, unavailable.weeks)
                and _intervals_overlap(
                    option.start,
                    option.length,
                    unavailable.start,
                    unavailable.length,
                )
            ):
                errors.append(f"class {class_id} uses unavailable room {room.id}")
                break

    room_meetings: dict[
        tuple[str, int, int],
        list[tuple[int, int, str]],
    ] = defaultdict(list)
    for class_id, placement in by_class.items():
        if placement.room_id is None or class_id not in resolved:
            continue
        option = resolved[class_id]
        for day, active_day in enumerate(option.days):
            if active_day != "1":
                continue
            for week, active_week in enumerate(option.weeks):
                if active_week == "1":
                    room_meetings[(placement.room_id, day, week)].append(
                        (option.start, option.start + option.length, class_id)
                    )
    overlapping_pairs: set[tuple[str, str, str]] = set()
    for (room_id, _day, _week), meetings in room_meetings.items():
        active: list[tuple[int, str]] = []
        for start, end, class_id in sorted(meetings):
            active = [entry for entry in active if entry[0] > start]
            for _active_end, other_id in active:
                first_id, second_id = sorted((class_id, other_id))
                overlapping_pairs.add((room_id, first_id, second_id))
            active.append((end, class_id))
    errors.extend(
        f"classes {first_id} and {second_id} overlap in room {room_id}"
        for room_id, first_id, second_id in sorted(overlapping_pairs)
    )
    return errors


def _travel_values(problem: ITC2019Problem) -> dict[tuple[str, str], int]:
    return {
        (room.id, travel.room_id): travel.value
        for room in problem.rooms
        for travel in room.travel
    }


def _student_pair_conflicts(
    problem: ITC2019Problem,
    first_placement: ITC2019ClassPlacement,
    first_time: ITC2019TimeOption,
    second_placement: ITC2019ClassPlacement,
    second_time: ITC2019TimeOption,
    travel: Mapping[tuple[str, str], int],
) -> bool:
    del problem
    if not _masks_overlap(first_time.days, second_time.days) or not _masks_overlap(
        first_time.weeks,
        second_time.weeks,
    ):
        return False
    if _intervals_overlap(
        first_time.start,
        first_time.length,
        second_time.start,
        second_time.length,
    ):
        return True
    if first_placement.room_id is None or second_placement.room_id is None:
        return False
    if first_time.start + first_time.length <= second_time.start:
        gap = second_time.start - (first_time.start + first_time.length)
        required = travel.get(
            (first_placement.room_id, second_placement.room_id),
            travel.get((second_placement.room_id, first_placement.room_id), 0),
        )
    else:
        gap = first_time.start - (second_time.start + second_time.length)
        required = travel.get(
            (second_placement.room_id, first_placement.room_id),
            travel.get((first_placement.room_id, second_placement.room_id), 0),
        )
    return gap < required


def _conflicting_class_pairs(
    problem: ITC2019Problem,
    by_class: Mapping[str, ITC2019ClassPlacement],
    *,
    eligible_pairs: set[tuple[str, str]] | None = None,
    deadline: float | None = None,
) -> set[tuple[str, str]]:
    context = _class_context(problem)
    resolved = {
        class_id: _matching_time_option(context[class_id][3], placement)
        for class_id, placement in by_class.items()
        if class_id in context
    }
    travel = _travel_values(problem)
    conflicts: set[tuple[str, str]] = set()
    if eligible_pairs is not None:
        candidate_pairs = {
            (first_id, second_id)
            for first_id, second_id in eligible_pairs
            if resolved.get(first_id) is not None
            and resolved.get(second_id) is not None
            and _masks_overlap(resolved[first_id].days, resolved[second_id].days)
            and _masks_overlap(resolved[first_id].weeks, resolved[second_id].weeks)
        }
    else:
        meeting_buckets: dict[tuple[int, int], list[str]] = defaultdict(list)
        for class_id, option in resolved.items():
            if option is None:
                continue
            for day_index, active_day in enumerate(option.days):
                if active_day != "1":
                    continue
                for week_index, active_week in enumerate(option.weeks):
                    if active_week == "1":
                        meeting_buckets[(day_index, week_index)].append(class_id)

        candidate_pairs = set()
        for class_ids in meeting_buckets.values():
            ordered = sorted(class_ids)
            candidate_pairs.update(
                (first_id, second_id)
                for index, first_id in enumerate(ordered)
                for second_id in ordered[index + 1 :]
            )
    for pair_index, (first_id, second_id) in enumerate(sorted(candidate_pairs)):
        first_time = resolved[first_id]
        second_time = resolved[second_id]
        assert first_time is not None and second_time is not None
        if _student_pair_conflicts(
            problem,
            by_class[first_id],
            first_time,
            by_class[second_id],
            second_time,
            travel,
        ):
            conflicts.add((first_id, second_id))
        if (
            pair_index % 256 == 0
            and deadline is not None
            and time.monotonic() >= deadline
        ):
            raise TimeoutError("ITC-2019 conflict-pair construction timed out")
    return conflicts


def _eligible_student_class_pairs(
    problem: ITC2019Problem,
    *,
    deadline: float | None = None,
    maximum_pairs: int | None = None,
) -> set[tuple[str, str]]:
    course_classes = {
        course.id: sorted(
            klass.id
            for configuration in course.configurations
            for subpart in configuration.subparts
            for klass in subpart.classes
        )
        for course in problem.courses
    }
    pairs: set[tuple[str, str]] = set()
    seen_request_sets: set[tuple[str, ...]] = set()
    for student in problem.students:
        request_set = tuple(sorted(set(student.course_ids)))
        if request_set in seen_request_sets:
            continue
        seen_request_sets.add(request_set)
        class_ids = sorted(
            {
                class_id
                for course_id in request_set
                for class_id in course_classes[course_id]
            }
        )
        for index, first_id in enumerate(class_ids):
            for second_id in class_ids[index + 1 :]:
                pairs.add((first_id, second_id))
                if maximum_pairs is not None and len(pairs) > maximum_pairs:
                    raise OverflowError(
                        "exact sectioning conflict graph requires more than "
                        f"{maximum_pairs} class pairs"
                    )
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("ITC-2019 eligible-pair construction timed out")
    return pairs


def validate_itc2019_student_sectioning(
    problem: ITC2019Problem,
    student_classes: Mapping[str, Sequence[str]],
) -> list[str]:
    context = _class_context(problem)
    configuration_subparts = {
        (course.id, configuration.id): tuple(
            (subpart.id, frozenset(klass.id for klass in subpart.classes))
            for subpart in configuration.subparts
        )
        for course in problem.courses
        for configuration in course.configurations
    }
    students = {student.id: student for student in problem.students}
    errors: list[str] = []

    unknown_students = sorted(set(student_classes) - set(students))
    if unknown_students:
        errors.append(
            "sectioning contains unknown students: " + ", ".join(unknown_students)
        )
    missing_students = sorted(set(students) - set(student_classes))
    if missing_students:
        errors.append("sectioning is missing students: " + ", ".join(missing_students))

    class_loads: Counter[str] = Counter()
    for student_id, raw_class_ids in student_classes.items():
        if student_id not in students:
            continue
        class_ids = tuple(str(class_id) for class_id in raw_class_ids)
        duplicate_classes = _duplicates(class_ids)
        if duplicate_classes:
            errors.append(
                f"student {student_id} has duplicate classes: {', '.join(duplicate_classes)}"
            )
        selected = set(class_ids)
        unknown_classes = sorted(
            class_id for class_id in selected if class_id not in context
        )
        if unknown_classes:
            errors.append(
                f"student {student_id} has unknown classes: {', '.join(unknown_classes)}"
            )
            selected.difference_update(unknown_classes)
        requested = set(students[student_id].course_ids)
        selected_by_course: dict[str, list[str]] = defaultdict(list)
        selected_configurations: dict[str, set[str]] = defaultdict(set)
        for class_id in selected:
            course_id, configuration_id, _subpart_id, _klass = context[class_id]
            selected_by_course[course_id].append(class_id)
            selected_configurations[course_id].add(configuration_id)
        selected_courses = set(selected_by_course)
        unexpected_courses = sorted(selected_courses - requested)
        if unexpected_courses:
            errors.append(
                f"student {student_id} is sectioned into unrequested courses: "
                + ", ".join(unexpected_courses)
            )
        for course_id in sorted(requested):
            course_classes = selected_by_course.get(course_id, ())
            course_configurations = selected_configurations.get(course_id, set())
            if len(course_configurations) != 1:
                errors.append(
                    f"student {student_id} must select exactly one configuration for "
                    f"course {course_id}"
                )
                continue
            configuration_id = next(iter(course_configurations))
            course_class_set = set(course_classes)
            for subpart_id, subpart_class_ids in configuration_subparts[
                (course_id, configuration_id)
            ]:
                if len(course_class_set & subpart_class_ids) != 1:
                    errors.append(
                        f"student {student_id} must select exactly one class from "
                        f"subpart {subpart_id}"
                    )
            for class_id in course_classes:
                klass = context[class_id][3]
                if (
                    klass.parent_id is not None
                    and klass.parent_id not in course_class_set
                ):
                    errors.append(
                        f"student {student_id} class {class_id} requires parent "
                        f"{klass.parent_id}"
                    )
        class_loads.update(selected)

    for class_id, load in sorted(class_loads.items()):
        limit = context[class_id][3].limit
        if load > limit:
            errors.append(f"class {class_id} load {load} exceeds limit {limit}")
    return errors


def _capacity_first_student_sectioning(
    problem: ITC2019Problem,
    *,
    deadline: float,
) -> dict[str, tuple[str, ...]] | None:
    """Construct exact hard-feasible sectioning without per-student Booleans.

    Class capacities and parent links are local to a course.  Official course
    configurations form forests of subparts: every non-root subpart contains
    classes whose parents all belong to one earlier subpart.  A bottom-up capacity
    pass computes the exact number of students each class/configuration can carry;
    a top-down flow pass then expands those aggregate counts to individual students.

    ``None`` means either that the structure is more general than this exact forest
    formulation or that its aggregate capacities cannot serve every request.  The
    caller retains the generic CP-SAT model as a fail-closed fallback in both cases.
    """

    courses = {course.id: course for course in problem.courses}
    selected: dict[str, list[str]] = {student.id: [] for student in problem.students}
    requesters: dict[str, list[str]] = defaultdict(list)
    for student in problem.students:
        for course_id in dict.fromkeys(student.course_ids):
            if course_id not in courses:
                return None
            requesters[course_id].append(student.id)

    for course_id in sorted(
        requesters, key=lambda item: (-len(requesters[item]), item)
    ):
        if time.monotonic() >= deadline:
            return None
        student_ids = requesters[course_id]
        course = courses[course_id]
        configuration_plans: list[
            tuple[
                ITC2019Configuration,
                tuple[ITC2019Subpart, ...],
                dict[str, str | None],
                dict[str, int],
                int,
            ]
        ] = []

        for configuration in course.configurations:
            subpart_by_class = {
                klass.id: subpart.id
                for subpart in configuration.subparts
                for klass in subpart.classes
            }
            subparts = {subpart.id: subpart for subpart in configuration.subparts}
            parent_subpart: dict[str, str | None] = {}
            children: dict[str, list[str]] = defaultdict(list)
            indegree = {subpart.id: 0 for subpart in configuration.subparts}
            supported = True
            for subpart in configuration.subparts:
                raw_parents = [klass.parent_id for klass in subpart.classes]
                if not raw_parents or all(parent is None for parent in raw_parents):
                    parent_subpart[subpart.id] = None
                    continue
                if any(parent is None for parent in raw_parents):
                    supported = False
                    break
                parent_ids = {
                    subpart_by_class.get(str(parent)) for parent in raw_parents
                }
                if None in parent_ids or len(parent_ids) != 1:
                    supported = False
                    break
                parent_id = next(iter(parent_ids))
                assert parent_id is not None
                if parent_id == subpart.id:
                    supported = False
                    break
                parent_subpart[subpart.id] = parent_id
                children[parent_id].append(subpart.id)
                indegree[subpart.id] += 1
            if not supported:
                return None

            ready = sorted(
                subpart_id for subpart_id, degree in indegree.items() if degree == 0
            )
            topological_ids: list[str] = []
            while ready:
                subpart_id = ready.pop(0)
                topological_ids.append(subpart_id)
                for child_id in sorted(children.get(subpart_id, ())):
                    indegree[child_id] -= 1
                    if indegree[child_id] == 0:
                        ready.append(child_id)
                        ready.sort()
            if len(topological_ids) != len(configuration.subparts):
                return None

            effective_capacity = {
                klass.id: max(0, int(klass.limit))
                for subpart in configuration.subparts
                for klass in subpart.classes
            }
            for subpart_id in reversed(topological_ids):
                subpart = subparts[subpart_id]
                parent_id = parent_subpart[subpart_id]
                if parent_id is None:
                    continue
                child_capacity: Counter[str] = Counter()
                for klass in subpart.classes:
                    assert klass.parent_id is not None
                    child_capacity[klass.parent_id] += effective_capacity[klass.id]
                for parent in subparts[parent_id].classes:
                    effective_capacity[parent.id] = min(
                        effective_capacity[parent.id], child_capacity[parent.id]
                    )

            root_capacities = [
                sum(
                    effective_capacity[klass.id]
                    for klass in subparts[subpart_id].classes
                )
                for subpart_id in topological_ids
                if parent_subpart[subpart_id] is None
            ]
            if not root_capacities:
                return None
            configuration_plans.append(
                (
                    configuration,
                    tuple(subparts[item] for item in topological_ids),
                    parent_subpart,
                    effective_capacity,
                    min(root_capacities),
                )
            )

        remaining = len(student_ids)
        offset = 0
        for (
            _configuration,
            ordered_subparts,
            parent_subpart,
            effective_capacity,
            configuration_capacity,
        ) in sorted(configuration_plans, key=lambda item: (-item[4], item[0].id)):
            assigned_count = min(remaining, configuration_capacity)
            if assigned_count <= 0:
                continue
            assigned_students = student_ids[offset : offset + assigned_count]
            chosen_by_subpart: dict[tuple[str, str], str] = {}

            for subpart in ordered_subparts:
                parent_id = parent_subpart[subpart.id]
                if parent_id is None:
                    groups: list[tuple[str | None, list[str]]] = [
                        (None, assigned_students)
                    ]
                else:
                    grouped_students: dict[str, list[str]] = defaultdict(list)
                    for student_id in assigned_students:
                        parent_class = chosen_by_subpart.get((student_id, parent_id))
                        if parent_class is None:
                            return None
                        grouped_students[parent_class].append(student_id)
                    groups = sorted(grouped_students.items())

                for parent_class, group in groups:
                    candidates = [
                        klass
                        for klass in subpart.classes
                        if klass.parent_id == parent_class
                    ]
                    group_offset = 0
                    for klass in sorted(
                        candidates,
                        key=lambda item: (-effective_capacity[item.id], item.id),
                    ):
                        take = min(
                            len(group) - group_offset, effective_capacity[klass.id]
                        )
                        for student_id in group[group_offset : group_offset + take]:
                            selected[student_id].append(klass.id)
                            chosen_by_subpart[(student_id, subpart.id)] = klass.id
                        group_offset += take
                        if group_offset == len(group):
                            break
                    if group_offset != len(group):
                        return None

            offset += assigned_count
            remaining -= assigned_count
            if remaining == 0:
                break
        if remaining:
            return None

    return {
        student.id: tuple(sorted(selected[student.id])) for student in problem.students
    }


def count_itc2019_student_conflicts(
    problem: ITC2019Problem,
    placements: Mapping[str, ITC2019ClassPlacement] | Sequence[ITC2019ClassPlacement],
    student_classes: Mapping[str, Sequence[str]],
) -> int:
    by_class = _placement_map(placements)
    eligible_pairs: set[tuple[str, str]] = set()
    for class_ids in student_classes.values():
        ordered = sorted(set(class_ids))
        eligible_pairs.update(
            (first_id, second_id)
            for index, first_id in enumerate(ordered)
            for second_id in ordered[index + 1 :]
        )
    conflicting_pairs = _conflicting_class_pairs(
        problem,
        by_class,
        eligible_pairs=eligible_pairs,
    )
    total = 0
    for class_ids in student_classes.values():
        selected = set(class_ids)
        total += sum(
            first in selected and second in selected
            for first, second in conflicting_pairs
        )
    return total


def validate_itc2019_solution(
    problem: ITC2019Problem,
    placements: Mapping[str, ITC2019ClassPlacement] | Sequence[ITC2019ClassPlacement],
    student_classes: Mapping[str, Sequence[str]],
) -> list[str]:
    """Independently validate every hard semantic condition of a solution.

    Soft distribution penalties and student conflicts are objective components, not
    validation failures.  This validator is complete for the published format and the
    constraint vocabulary present in the pinned 36-problem corpus; it is intentionally
    not described as agreement with the unavailable competition website validator.
    """

    errors = validate_itc2019_class_placements(
        problem,
        placements,
        require_complete=True,
    ) + validate_itc2019_student_sectioning(problem, student_classes)
    if errors:
        return errors
    for index, score in enumerate(
        evaluate_itc2019_distributions(problem, placements),
        start=1,
    ):
        if score.is_hard_violation:
            errors.append(
                f"required distribution {index} ({score.constraint_type}) has "
                f"{score.violation_units} violation unit(s)"
            )
    return errors


def score_itc2019_solution(
    problem: ITC2019Problem,
    placements: Mapping[str, ITC2019ClassPlacement] | Sequence[ITC2019ClassPlacement],
    student_classes: Mapping[str, Sequence[str]],
) -> ITC2019Objective:
    """Compute the published four-component weighted ITC-2019 objective."""

    errors = validate_itc2019_class_placements(
        problem,
        placements,
        require_complete=True,
    ) + validate_itc2019_student_sectioning(problem, student_classes)
    if errors:
        raise ValueError("Invalid ITC-2019 solution: " + "; ".join(errors))
    distribution_scores = evaluate_itc2019_distributions(problem, placements)
    hard_errors = [
        f"required distribution {index} ({score.constraint_type}) has "
        f"{score.violation_units} violation unit(s)"
        for index, score in enumerate(distribution_scores, start=1)
        if score.is_hard_violation
    ]
    if hard_errors:
        raise ValueError("Invalid ITC-2019 solution: " + "; ".join(hard_errors))
    by_class = _placement_map(placements)
    context = _class_context(problem)
    room_penalties = {
        class_id: {room.room_id: room.penalty for room in klass.room_options}
        for class_id, (_, _, _, klass) in context.items()
    }
    time_penalty = 0
    room_penalty = 0
    for class_id, placement in by_class.items():
        option = _matching_time_option(context[class_id][3], placement)
        assert option is not None
        time_penalty += option.penalty
        if placement.room_id is not None:
            room_penalty += room_penalties[class_id][placement.room_id]
    distribution_penalty = sum(score.penalty for score in distribution_scores)
    student_conflicts = count_itc2019_student_conflicts(
        problem,
        by_class,
        student_classes,
    )
    weighted_time = time_penalty * problem.optimization.time
    weighted_room = room_penalty * problem.optimization.room
    weighted_distribution = distribution_penalty * problem.optimization.distribution
    weighted_student = student_conflicts * problem.optimization.student
    return ITC2019Objective(
        time=time_penalty,
        room=room_penalty,
        distribution=distribution_penalty,
        student=student_conflicts,
        weighted_time=weighted_time,
        weighted_room=weighted_room,
        weighted_distribution=weighted_distribution,
        weighted_student=weighted_student,
        total=weighted_time + weighted_room + weighted_distribution + weighted_student,
    )


def solve_itc2019_student_sectioning(
    problem: ITC2019Problem,
    placements: Mapping[str, ITC2019ClassPlacement] | Sequence[ITC2019ClassPlacement],
    *,
    time_limit_seconds: float = 30.0,
    workers: int = 1,
    random_seed: int = 0,
    max_conflict_pairs: int = 2_000_000,
    max_conflict_terms: int = 2_000_000,
    feasibility_first_only: bool = False,
) -> ITC2019SectioningResult:
    """Optimally section students after all class placements have been fixed.

    The CP-SAT model selects exactly one configuration per requested course and one
    class from every subpart, enforces parent/child compatibility and class limits,
    and minimizes direct plus room-travel student conflicts induced by the fixed
    timetable.  ``feasibility_first_only`` returns the independently validated
    capacity-flow incumbent immediately; unsupported or infeasible forest structures
    still fail closed through the generic CP-SAT feasibility model.
    """

    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be positive")
    if workers <= 0:
        raise ValueError("workers must be positive")
    if random_seed < 0:
        raise ValueError("random_seed must be non-negative")
    if max_conflict_pairs <= 0 or max_conflict_terms <= 0:
        raise ValueError("sectioning scale budgets must be positive")
    started = time.monotonic()
    deadline = started + float(time_limit_seconds)
    placement_errors = validate_itc2019_class_placements(
        problem,
        placements,
        require_complete=True,
    )
    if placement_errors:
        return ITC2019SectioningResult(
            status="INVALID_PLACEMENT",
            student_classes={},
            student_conflicts=None,
            weighted_objective=None,
            best_bound=None,
            wall_time_seconds=time.monotonic() - started,
            validation_errors=tuple(placement_errors),
        )
    if time.monotonic() >= deadline:
        return ITC2019SectioningResult(
            status="DEADLINE_EXCEEDED",
            student_classes={},
            student_conflicts=None,
            weighted_objective=None,
            best_bound=None,
            wall_time_seconds=time.monotonic() - started,
        )
    by_class = _placement_map(placements)
    class_context = _class_context(problem)
    courses = {course.id: course for course in problem.courses}

    capacity_first = _capacity_first_student_sectioning(
        problem,
        deadline=deadline,
    )
    if capacity_first is not None:
        capacity_errors = validate_itc2019_student_sectioning(problem, capacity_first)
        if capacity_errors:
            capacity_first = None
    course_variable_counts = {
        course_id: sum(
            len(subpart.classes)
            for configuration in courses[course_id].configurations
            for subpart in configuration.subparts
        )
        for course_id in courses
    }
    enrollment_variable_estimate = sum(
        course_variable_counts[course_id]
        for student in problem.students
        for course_id in dict.fromkeys(student.course_ids)
    )
    if capacity_first is not None and (
        feasibility_first_only
        or enrollment_variable_estimate > ITC2019_SECTIONING_CP_ENROLLMENT_THRESHOLD
    ):
        return ITC2019SectioningResult(
            status="FEASIBLE",
            student_classes=capacity_first,
            student_conflicts=None,
            weighted_objective=None,
            best_bound=None,
            wall_time_seconds=time.monotonic() - started,
            model_build_seconds=time.monotonic() - started,
        )

    model = cp_model.CpModel()
    enrollment: dict[tuple[str, str], cp_model.IntVar] = {}

    for student in problem.students:
        for course_id in student.course_ids:
            course = courses[course_id]
            choice_variables: list[cp_model.IntVar] = []
            for configuration in course.configurations:
                choice = model.new_bool_var(
                    f"student_{student.id}_course_{course_id}_config_{configuration.id}"
                )
                choice_variables.append(choice)
                for subpart in configuration.subparts:
                    subpart_enrollments: list[cp_model.IntVar] = []
                    for klass in subpart.classes:
                        variable = enrollment.setdefault(
                            (student.id, klass.id),
                            model.new_bool_var(
                                f"student_{student.id}_class_{klass.id}"
                            ),
                        )
                        subpart_enrollments.append(variable)
                    model.add(sum(subpart_enrollments) == choice)
                for subpart in configuration.subparts:
                    for klass in subpart.classes:
                        if klass.parent_id is not None:
                            model.add(
                                enrollment[(student.id, klass.id)]
                                <= enrollment[(student.id, klass.parent_id)]
                            )
            model.add_exactly_one(choice_variables)
        if time.monotonic() >= deadline:
            return ITC2019SectioningResult(
                status="DEADLINE_EXCEEDED",
                student_classes={},
                student_conflicts=None,
                weighted_objective=None,
                best_bound=None,
                wall_time_seconds=time.monotonic() - started,
            )

    enrollment_by_class: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    enrollment_by_student: dict[str, list[tuple[str, cp_model.IntVar]]] = defaultdict(
        list
    )
    for (student_id, class_id), variable in enrollment.items():
        enrollment_by_class[class_id].append(variable)
        enrollment_by_student[student_id].append((class_id, variable))
    for class_id, (_, _, _, klass) in class_context.items():
        variables = enrollment_by_class.get(class_id, [])
        if variables:
            model.add(sum(variables) <= klass.limit)

    # Establish a complete hard-feasible sectioning before materializing the
    # potentially much larger student-conflict objective.  This preserves a
    # publishable solution when objective preprocessing or improvement consumes
    # the remaining budget on large student-heavy instances.
    hard_model_finished = time.monotonic()
    feasibility_solver_wall = 0.0
    if capacity_first is None:
        hard_remaining = deadline - hard_model_finished
        if hard_remaining <= 0:
            return ITC2019SectioningResult(
                status="DEADLINE_EXCEEDED",
                student_classes={},
                student_conflicts=None,
                weighted_objective=None,
                best_bound=None,
                wall_time_seconds=time.monotonic() - started,
            )
        feasibility_solver = cp_model.CpSolver()
        feasibility_solver.parameters.max_time_in_seconds = min(
            10.0, max(0.1, hard_remaining * 0.5)
        )
        feasibility_solver.parameters.num_search_workers = int(workers)
        feasibility_solver.parameters.random_seed = int(random_seed)
        feasibility_status_code = feasibility_solver.solve(model)
        feasibility_solver_wall = float(feasibility_solver.wall_time)
        if feasibility_status_code not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
            return ITC2019SectioningResult(
                status=feasibility_solver.status_name(feasibility_status_code).upper(),
                student_classes={},
                student_conflicts=None,
                weighted_objective=None,
                best_bound=None,
                wall_time_seconds=time.monotonic() - started,
                model_build_seconds=hard_model_finished - started,
                solver_wall_time_seconds=feasibility_solver_wall,
            )
        feasible_student_classes = {
            student.id: tuple(
                sorted(
                    class_id
                    for class_id, variable in enrollment_by_student[student.id]
                    if feasibility_solver.boolean_value(variable)
                )
            )
            for student in problem.students
        }
    else:
        feasible_student_classes = capacity_first
    feasibility_errors = validate_itc2019_student_sectioning(
        problem, feasible_student_classes
    )
    if feasibility_errors:
        return ITC2019SectioningResult(
            status="UNKNOWN",
            student_classes={},
            student_conflicts=None,
            weighted_objective=None,
            best_bound=None,
            wall_time_seconds=time.monotonic() - started,
            validation_errors=tuple(feasibility_errors),
            model_build_seconds=hard_model_finished - started,
            solver_wall_time_seconds=feasibility_solver_wall,
        )

    try:
        eligible_pairs = _eligible_student_class_pairs(
            problem,
            deadline=deadline,
            maximum_pairs=max_conflict_pairs,
        )
        conflicting_pairs = _conflicting_class_pairs(
            problem,
            by_class,
            eligible_pairs=eligible_pairs,
            deadline=deadline,
        )
    except (TimeoutError, OverflowError):
        return ITC2019SectioningResult(
            status="FEASIBLE",
            student_classes=feasible_student_classes,
            student_conflicts=None,
            weighted_objective=None,
            best_bound=None,
            wall_time_seconds=time.monotonic() - started,
            model_build_seconds=hard_model_finished - started,
            solver_wall_time_seconds=feasibility_solver_wall,
        )

    def conflicts_for(
        assignment: Mapping[str, Sequence[str]],
    ) -> int:
        conflicting_pair_set = {
            tuple(sorted((first_id, second_id)))
            for first_id, second_id in conflicting_pairs
        }
        return sum(
            tuple(sorted((first_id, second_id))) in conflicting_pair_set
            for class_ids in assignment.values()
            for first_id, second_id in combinations(class_ids, 2)
        )

    conflict_variables: list[cp_model.IntVar] = []
    course_class_ids = {
        course.id: {
            klass.id
            for configuration in course.configurations
            for subpart in configuration.subparts
            for klass in subpart.classes
        }
        for course in problem.courses
    }
    conflicts_by_request_set: dict[tuple[str, ...], tuple[tuple[str, str], ...]] = {}
    conflict_term_count = 0
    for student in problem.students:
        request_set = tuple(sorted(set(student.course_ids)))
        request_conflicts = conflicts_by_request_set.get(request_set)
        if request_conflicts is None:
            possible_classes = {
                class_id
                for course_id in request_set
                for class_id in course_class_ids[course_id]
            }
            request_conflicts = tuple(
                (first_id, second_id)
                for first_id, second_id in sorted(conflicting_pairs)
                if first_id in possible_classes and second_id in possible_classes
            )
            conflicts_by_request_set[request_set] = request_conflicts
        for first_id, second_id in request_conflicts:
            first = enrollment.get((student.id, first_id))
            second = enrollment.get((student.id, second_id))
            if first is None or second is None:
                continue
            conflict_term_count += 1
            if conflict_term_count > max_conflict_terms:
                return ITC2019SectioningResult(
                    status="UNSUPPORTED_MODEL_SCALE",
                    student_classes={},
                    student_conflicts=None,
                    weighted_objective=None,
                    best_bound=None,
                    wall_time_seconds=time.monotonic() - started,
                )
            conflict = model.new_bool_var(
                f"student_{student.id}_conflict_{first_id}_{second_id}"
            )
            model.add(conflict <= first)
            model.add(conflict <= second)
            model.add(conflict >= first + second - 1)
            conflict_variables.append(conflict)
        if time.monotonic() >= deadline:
            feasible_conflicts = conflicts_for(feasible_student_classes)
            return ITC2019SectioningResult(
                status="FEASIBLE",
                student_classes=feasible_student_classes,
                student_conflicts=feasible_conflicts,
                weighted_objective=feasible_conflicts * problem.optimization.student,
                best_bound=None,
                wall_time_seconds=time.monotonic() - started,
                model_build_seconds=hard_model_finished - started,
                solver_wall_time_seconds=feasibility_solver_wall,
            )
    feasible_class_sets = {
        student_id: set(class_ids)
        for student_id, class_ids in feasible_student_classes.items()
    }
    for (student_id, class_id), variable in enrollment.items():
        model.add_hint(variable, int(class_id in feasible_class_sets[student_id]))
    model.minimize(sum(conflict_variables))

    model_build_finished = time.monotonic()
    remaining = deadline - model_build_finished - 0.25
    if remaining <= 0:
        feasible_conflicts = conflicts_for(feasible_student_classes)
        return ITC2019SectioningResult(
            status="FEASIBLE",
            student_classes=feasible_student_classes,
            student_conflicts=feasible_conflicts,
            weighted_objective=feasible_conflicts * problem.optimization.student,
            best_bound=None,
            wall_time_seconds=time.monotonic() - started,
            model_build_seconds=hard_model_finished - started,
            solver_wall_time_seconds=feasibility_solver_wall,
        )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(remaining)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.random_seed = int(random_seed)
    status_code = solver.solve(model)
    status = solver.status_name(status_code).upper()
    if status_code not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        feasible_conflicts = conflicts_for(feasible_student_classes)
        return ITC2019SectioningResult(
            status="FEASIBLE",
            student_classes=feasible_student_classes,
            student_conflicts=feasible_conflicts,
            weighted_objective=feasible_conflicts * problem.optimization.student,
            best_bound=(
                float(solver.best_objective_bound)
                if status_code != cp_model.MODEL_INVALID
                else None
            ),
            wall_time_seconds=time.monotonic() - started,
            model_build_seconds=model_build_finished - started,
            solver_wall_time_seconds=float(solver.wall_time),
        )

    student_classes = {
        student.id: tuple(
            sorted(
                class_id
                for class_id, variable in enrollment_by_student[student.id]
                if solver.boolean_value(variable)
            )
        )
        for student in problem.students
    }
    validation_errors = validate_itc2019_student_sectioning(problem, student_classes)
    conflicts = count_itc2019_student_conflicts(problem, by_class, student_classes)
    finished = time.monotonic()
    if finished > deadline:
        feasible_conflicts = conflicts_for(feasible_student_classes)
        return ITC2019SectioningResult(
            status="FEASIBLE",
            student_classes=feasible_student_classes,
            student_conflicts=feasible_conflicts,
            weighted_objective=feasible_conflicts * problem.optimization.student,
            best_bound=None,
            wall_time_seconds=finished - started,
            model_build_seconds=model_build_finished - started,
            solver_wall_time_seconds=float(solver.wall_time),
        )
    return ITC2019SectioningResult(
        status=status,
        student_classes=student_classes,
        student_conflicts=conflicts,
        weighted_objective=conflicts * problem.optimization.student,
        best_bound=float(solver.best_objective_bound),
        wall_time_seconds=finished - started,
        validation_errors=tuple(validation_errors),
        model_build_seconds=model_build_finished - started,
        solver_wall_time_seconds=float(solver.wall_time),
    )


def _room_accepts_time(room: ITC2019Room, option: ITC2019TimeOption) -> bool:
    return not any(
        _masks_overlap(option.days, unavailable.days)
        and _masks_overlap(option.weeks, unavailable.weeks)
        and _intervals_overlap(
            option.start,
            option.length,
            unavailable.start,
            unavailable.length,
        )
        for unavailable in room.unavailable
    )


def _native_class_alternatives(
    problem: ITC2019Problem,
    *,
    deadline: float | None = None,
) -> dict[str, tuple[_ITC2019Alternative, ...]]:
    rooms = {room.id: room for room in problem.rooms}
    alternatives: dict[str, tuple[_ITC2019Alternative, ...]] = {}
    for klass in problem.classes:
        times_by_assignment: dict[
            tuple[str, int, int, str],
            ITC2019TimeOption,
        ] = {}
        for option in klass.time_options:
            key = (option.days, option.start, option.length, option.weeks)
            current = times_by_assignment.get(key)
            if current is None or option.penalty < current.penalty:
                times_by_assignment[key] = option
        unique_times = tuple(times_by_assignment.values())
        unique_rooms = tuple(
            {
                (option.room_id, option.penalty): option
                for option in klass.room_options
            }.values()
        )
        rows: list[_ITC2019Alternative] = []
        for time_option in unique_times:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("ITC-2019 native alternative construction timed out")
            if not klass.room_required:
                rows.append(
                    _ITC2019Alternative(
                        placement=ITC2019ClassPlacement(
                            class_id=klass.id,
                            days=time_option.days,
                            start=time_option.start,
                            weeks=time_option.weeks,
                            room_id=None,
                        ),
                        time=time_option,
                        time_penalty=time_option.penalty,
                        room_penalty=0,
                    )
                )
                continue
            for room_option in unique_rooms:
                if not _room_accepts_time(rooms[room_option.room_id], time_option):
                    continue
                rows.append(
                    _ITC2019Alternative(
                        placement=ITC2019ClassPlacement(
                            class_id=klass.id,
                            days=time_option.days,
                            start=time_option.start,
                            weeks=time_option.weeks,
                            room_id=room_option.room_id,
                        ),
                        time=time_option,
                        time_penalty=time_option.penalty,
                        room_penalty=room_option.penalty,
                    )
                )
        alternatives[klass.id] = tuple(rows)
    return alternatives


@dataclass(frozen=True)
class _ITC2019PairMatrix:
    values: tuple[int, ...]
    constant: int | None

    @property
    def charged_cells(self) -> int:
        return 0 if self.constant is not None else len(self.values)


def _classify_itc2019_pair_matrix(
    values: Iterable[int],
    *,
    deadline: float | None = None,
) -> _ITC2019PairMatrix:
    """Materialize and classify one exact Boolean pair matrix.

    Cartesian admission and construction share this helper so constant matrices
    remain free in both paths and nonconstant matrices consume exactly their
    materialized cell count.
    """

    materialized: list[int] = []
    for index, value in enumerate(values):
        materialized.append(int(value))
        if deadline is not None and index % 1024 == 0 and time.monotonic() >= deadline:
            raise TimeoutError("ITC-2019 pair matrix classification timed out")
    if not materialized:
        raise ValueError("ITC-2019 pair matrix must not be empty")
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("ITC-2019 pair matrix classification timed out")
    constant = (
        materialized[0]
        if all(value == materialized[0] for value in materialized)
        else None
    )
    return _ITC2019PairMatrix(tuple(materialized), constant)


def _distribution_pair_matrix(
    *,
    base: str,
    parameters: tuple[int, ...],
    first: Sequence[_ITC2019Alternative],
    second: Sequence[_ITC2019Alternative],
    travel: Mapping[tuple[str, str], int],
    deadline: float | None = None,
) -> _ITC2019PairMatrix:
    return _classify_itc2019_pair_matrix(
        (
            int(
                not _pair_distribution_satisfied(
                    base,
                    parameters,
                    first_alternative.placement,
                    first_alternative.time,
                    second_alternative.placement,
                    second_alternative.time,
                    travel,
                )
            )
            for first_alternative in first
            for second_alternative in second
        ),
        deadline=deadline,
    )


def _student_pair_matrix(
    problem: ITC2019Problem,
    *,
    first: Sequence[_ITC2019Alternative],
    second: Sequence[_ITC2019Alternative],
    travel: Mapping[tuple[str, str], int],
    deadline: float | None = None,
) -> _ITC2019PairMatrix:
    return _classify_itc2019_pair_matrix(
        (
            int(
                _student_pair_conflicts(
                    problem,
                    first_alternative.placement,
                    first_alternative.time,
                    second_alternative.placement,
                    second_alternative.time,
                    travel,
                )
            )
            for first_alternative in first
            for second_alternative in second
        ),
        deadline=deadline,
    )


def _itc2019_native_failure(
    *,
    status: str,
    started: float,
    build_started: float,
    random_seed: int,
    workers: int,
    validation_errors: Sequence[str] = (),
    unsupported_reasons: Sequence[str] = (),
) -> ITC2019NativeSolveResult:
    now = time.monotonic()
    return ITC2019NativeSolveResult(
        status=status,
        placements=(),
        student_classes={},
        objective=None,
        best_bound=None,
        wall_time_seconds=now - started,
        model_build_seconds=now - build_started,
        solver_wall_time_seconds=0.0,
        conflicts=0,
        branches=0,
        deterministic_seed=random_seed,
        workers=workers,
        validation_errors=tuple(validation_errors),
        unsupported_reasons=tuple(unsupported_reasons),
    )


def _solve_itc2019_native_cartesian(
    problem: ITC2019Problem,
    *,
    time_limit_seconds: float = 30.0,
    workers: int = 1,
    random_seed: int = 0,
    max_pair_matrix_cells: int = 2_000_000,
    max_group_table_rows: int = 200_000,
) -> ITC2019NativeSolveResult:
    """Jointly place classes and section students in the native ITC-2019 model.

    All official objective components are modeled.  Pairwise constraints use exact
    option-index tables, MaxDays and MaxDayLoad use direct formulations, and the two
    block constraints use exact group tables.  The table and pair budgets are explicit
    fail-closed guards: callers receive ``UNSUPPORTED_MODEL_SCALE`` instead of a
    silently relaxed model when an exact encoding would exceed the configured budget.
    The wall-clock limit includes model construction as well as CP-SAT search.
    """

    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be positive")
    if workers <= 0:
        raise ValueError("workers must be positive")
    if random_seed < 0:
        raise ValueError("random_seed must be non-negative")
    if max_pair_matrix_cells <= 0 or max_group_table_rows <= 0:
        raise ValueError("native ITC-2019 encoding budgets must be positive")

    started = time.monotonic()
    build_started = started
    deadline = started + float(time_limit_seconds)

    def deadline_exceeded() -> bool:
        return time.monotonic() >= deadline

    problem_errors = _validate_problem_references(problem)
    if problem_errors:
        return _itc2019_native_failure(
            status="INVALID_PROBLEM",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
            validation_errors=problem_errors,
        )

    try:
        alternatives = _native_class_alternatives(problem, deadline=deadline)
    except TimeoutError:
        return _itc2019_native_failure(
            status="DEADLINE_EXCEEDED",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
        )
    empty_domains = sorted(
        class_id for class_id, rows in alternatives.items() if not rows
    )
    if empty_domains:
        return _itc2019_native_failure(
            status="INFEASIBLE_DOMAIN",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
            validation_errors=(
                "classes have no room-available placement: " + ", ".join(empty_domains),
            ),
        )
    if deadline_exceeded():
        return _itc2019_native_failure(
            status="DEADLINE_EXCEEDED",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
        )

    model = cp_model.CpModel()
    selectors: dict[str, tuple[cp_model.IntVar, ...]] = {}
    choices: dict[str, cp_model.IntVar] = {}
    objective_terms: list[Any] = []
    for klass in problem.classes:
        rows = alternatives[klass.id]
        class_selectors = tuple(
            model.new_bool_var(f"class_{klass.id}_alternative_{index}")
            for index in range(len(rows))
        )
        selectors[klass.id] = class_selectors
        model.add_exactly_one(class_selectors)
        choice = model.new_int_var(0, len(rows) - 1, f"class_{klass.id}_choice")
        choices[klass.id] = choice
        for index, variable in enumerate(class_selectors):
            model.add(choice == index).only_enforce_if(variable)
            coefficient = (
                rows[index].time_penalty * problem.optimization.time
                + rows[index].room_penalty * problem.optimization.room
            )
            if coefficient:
                objective_terms.append(coefficient * variable)

    room_cells: dict[tuple[str, int, int, int], list[cp_model.IntVar]] = defaultdict(
        list
    )
    for class_id, rows in alternatives.items():
        for index, alternative in enumerate(rows):
            room_id = alternative.placement.room_id
            if room_id is None:
                continue
            for day, active_day in enumerate(alternative.time.days):
                if active_day != "1":
                    continue
                for week, active_week in enumerate(alternative.time.weeks):
                    if active_week != "1":
                        continue
                    for slot in range(
                        alternative.time.start,
                        alternative.time.start + alternative.time.length,
                    ):
                        room_cells[(room_id, day, week, slot)].append(
                            selectors[class_id][index]
                        )
            if deadline_exceeded():
                return _itc2019_native_failure(
                    status="DEADLINE_EXCEEDED",
                    started=started,
                    build_started=build_started,
                    random_seed=random_seed,
                    workers=workers,
                )
    for variables in room_cells.values():
        if len(variables) > 1:
            model.add_at_most_one(variables)

    pair_cells_used = 0
    pair_indicator_cache: dict[tuple[str, str, str], cp_model.IntVar] = {}

    def guard_pair_matrix_allocation(first_id: str, second_id: str) -> None:
        matrix_cells = len(alternatives[first_id]) * len(alternatives[second_id])
        if pair_cells_used + matrix_cells > max_pair_matrix_cells:
            raise OverflowError(
                f"exact pair matrices require more than {max_pair_matrix_cells} cells"
            )

    def element_indicator(
        first_id: str,
        second_id: str,
        key: str,
        matrix: _ITC2019PairMatrix,
    ) -> cp_model.IntVar:
        nonlocal pair_cells_used
        cache_key = (first_id, second_id, key)
        cached = pair_indicator_cache.get(cache_key)
        if cached is not None:
            return cached
        if matrix.constant is not None:
            indicator = model.new_bool_var(
                f"pair_{first_id}_{second_id}_{len(pair_indicator_cache)}_constant"
            )
            model.add(indicator == matrix.constant)
            pair_indicator_cache[cache_key] = indicator
            return indicator
        pair_cells_used += matrix.charged_cells
        if pair_cells_used > max_pair_matrix_cells:
            raise OverflowError(
                f"exact pair matrices require more than {max_pair_matrix_cells} cells"
            )
        second_size = len(alternatives[second_id])
        pair_index = model.new_int_var(
            0,
            len(matrix.values) - 1,
            f"pair_{first_id}_{second_id}_{len(pair_indicator_cache)}_index",
        )
        model.add(pair_index == choices[first_id] * second_size + choices[second_id])
        indicator = model.new_bool_var(
            f"pair_{first_id}_{second_id}_{len(pair_indicator_cache)}_violation"
        )
        model.add_element(pair_index, list(matrix.values), indicator)
        pair_indicator_cache[cache_key] = indicator
        return indicator

    travel = _travel_values(problem)
    unsupported: list[str] = []
    try:
        for distribution_index, distribution in enumerate(
            problem.distributions, start=1
        ):
            base, parameters = _distribution_spec(distribution.type)
            class_ids = tuple(dict.fromkeys(distribution.class_ids))
            if base in _PAIR_DISTRIBUTIONS:
                for first_index, second_index in combinations(range(len(class_ids)), 2):
                    first_id = class_ids[first_index]
                    second_id = class_ids[second_index]
                    guard_pair_matrix_allocation(first_id, second_id)
                    matrix = _distribution_pair_matrix(
                        base=base,
                        parameters=parameters,
                        first=alternatives[first_id],
                        second=alternatives[second_id],
                        travel=travel,
                        deadline=deadline,
                    )
                    violation = element_indicator(
                        first_id,
                        second_id,
                        f"distribution_{distribution_index}_{base}",
                        matrix,
                    )
                    if distribution.required:
                        model.add(violation == 0)
                    elif distribution.penalty:
                        objective_terms.append(
                            distribution.penalty
                            * problem.optimization.distribution
                            * violation
                        )
            elif base == "MaxDays":
                (maximum_days,) = parameters
                used_days: list[cp_model.IntVar] = []
                for day in range(problem.nr_days):
                    active = [
                        selectors[class_id][alternative_index]
                        for class_id in class_ids
                        for alternative_index, alternative in enumerate(
                            alternatives[class_id]
                        )
                        if alternative.time.days[day] == "1"
                    ]
                    used = model.new_bool_var(
                        f"distribution_{distribution_index}_day_{day}"
                    )
                    if active:
                        model.add_max_equality(used, active)
                    else:
                        model.add(used == 0)
                    used_days.append(used)
                if distribution.required:
                    model.add(sum(used_days) <= maximum_days)
                elif distribution.penalty:
                    excess = model.new_int_var(
                        0,
                        problem.nr_days,
                        f"distribution_{distribution_index}_day_excess",
                    )
                    model.add(excess >= sum(used_days) - maximum_days)
                    objective_terms.append(
                        distribution.penalty
                        * problem.optimization.distribution
                        * excess
                    )
            elif base == "MaxDayLoad":
                (maximum_load,) = parameters
                excesses: list[cp_model.IntVar] = []
                maximum_possible = sum(
                    max(
                        alternative.time.length
                        for alternative in alternatives[class_id]
                    )
                    for class_id in class_ids
                )
                for day in range(problem.nr_days):
                    for week in range(problem.nr_weeks):
                        load_terms = [
                            alternative.time.length
                            * selectors[class_id][alternative_index]
                            for class_id in class_ids
                            for alternative_index, alternative in enumerate(
                                alternatives[class_id]
                            )
                            if alternative.time.days[day] == "1"
                            and alternative.time.weeks[week] == "1"
                        ]
                        load = sum(load_terms) if load_terms else 0
                        if distribution.required:
                            model.add(load <= maximum_load)
                        elif distribution.penalty:
                            excess = model.new_int_var(
                                0,
                                maximum_possible,
                                f"distribution_{distribution_index}_{day}_{week}_excess",
                            )
                            model.add(excess >= load - maximum_load)
                            excesses.append(excess)
                if not distribution.required and distribution.penalty and excesses:
                    total_excess = model.new_int_var(
                        0,
                        maximum_possible * problem.nr_days * problem.nr_weeks,
                        f"distribution_{distribution_index}_total_excess",
                    )
                    model.add(total_excess == sum(excesses))
                    numerator = model.new_int_var(
                        0,
                        distribution.penalty
                        * maximum_possible
                        * problem.nr_days
                        * problem.nr_weeks,
                        f"distribution_{distribution_index}_numerator",
                    )
                    model.add(numerator == distribution.penalty * total_excess)
                    cost = model.new_int_var(
                        0,
                        distribution.penalty * maximum_possible * problem.nr_days,
                        f"distribution_{distribution_index}_cost",
                    )
                    model.add_division_equality(cost, numerator, problem.nr_weeks)
                    objective_terms.append(problem.optimization.distribution * cost)
            elif base in {"MaxBreaks", "MaxBlock"}:
                row_count = 1
                for class_id in class_ids:
                    row_count *= len(alternatives[class_id])
                    if row_count > max_group_table_rows:
                        break
                if row_count > max_group_table_rows:
                    unsupported.append(
                        f"distribution {distribution_index} ({distribution.type}) "
                        f"needs {row_count}+ exact group rows; limit is "
                        f"{max_group_table_rows}"
                    )
                    continue
                table_rows: list[tuple[int, ...]] = []
                maximum_cost = 0
                for row_number, assignment in enumerate(
                    product(
                        *(range(len(alternatives[class_id])) for class_id in class_ids)
                    )
                ):
                    resolved = {
                        class_id: alternatives[class_id][selected].time
                        for class_id, selected in zip(
                            class_ids, assignment, strict=True
                        )
                    }
                    units = _special_distribution_units(
                        problem,
                        base,
                        parameters,
                        class_ids,
                        resolved,
                    )
                    if distribution.required:
                        if units == 0:
                            table_rows.append(tuple(assignment))
                    else:
                        cost = distribution.penalty * units // problem.nr_weeks
                        maximum_cost = max(maximum_cost, cost)
                        table_rows.append((*assignment, cost))
                    if row_number % 1024 == 0 and deadline_exceeded():
                        return _itc2019_native_failure(
                            status="DEADLINE_EXCEEDED",
                            started=started,
                            build_started=build_started,
                            random_seed=random_seed,
                            workers=workers,
                        )
                if distribution.required:
                    if not table_rows:
                        return _itc2019_native_failure(
                            status="INFEASIBLE",
                            started=started,
                            build_started=build_started,
                            random_seed=random_seed,
                            workers=workers,
                        )
                    model.add_allowed_assignments(
                        [choices[class_id] for class_id in class_ids],
                        table_rows,
                    )
                elif distribution.penalty:
                    cost = model.new_int_var(
                        0,
                        maximum_cost,
                        f"distribution_{distribution_index}_cost",
                    )
                    model.add_allowed_assignments(
                        [*(choices[class_id] for class_id in class_ids), cost],
                        table_rows,
                    )
                    objective_terms.append(problem.optimization.distribution * cost)
            if deadline_exceeded():
                return _itc2019_native_failure(
                    status="DEADLINE_EXCEEDED",
                    started=started,
                    build_started=build_started,
                    random_seed=random_seed,
                    workers=workers,
                )
    except TimeoutError:
        return _itc2019_native_failure(
            status="DEADLINE_EXCEEDED",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
        )
    except OverflowError as exc:
        unsupported.append(str(exc))

    if unsupported:
        return _itc2019_native_failure(
            status="UNSUPPORTED_MODEL_SCALE",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
            unsupported_reasons=unsupported,
        )

    class_context = _class_context(problem)
    courses = {course.id: course for course in problem.courses}
    enrollment: dict[tuple[str, str], cp_model.IntVar] = {}
    for student in problem.students:
        for course_id in student.course_ids:
            course = courses[course_id]
            for configuration in course.configurations:
                for subpart in configuration.subparts:
                    for klass in subpart.classes:
                        enrollment[(student.id, klass.id)] = model.new_bool_var(
                            f"student_{student.id}_class_{klass.id}"
                        )
            configuration_choices: list[cp_model.IntVar] = []
            for configuration in course.configurations:
                configuration_choice = model.new_bool_var(
                    f"student_{student.id}_course_{course_id}_config_{configuration.id}"
                )
                configuration_choices.append(configuration_choice)
                for subpart in configuration.subparts:
                    model.add(
                        sum(
                            enrollment[(student.id, klass.id)]
                            for klass in subpart.classes
                        )
                        == configuration_choice
                    )
                    for klass in subpart.classes:
                        if klass.parent_id is not None:
                            model.add(
                                enrollment[(student.id, klass.id)]
                                <= enrollment[(student.id, klass.parent_id)]
                            )
            model.add_exactly_one(configuration_choices)

    enrollment_by_class: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    enrollment_by_student: dict[str, list[str]] = defaultdict(list)
    for (student_id, class_id), variable in enrollment.items():
        enrollment_by_class[class_id].append(variable)
        enrollment_by_student[student_id].append(class_id)
    for class_id, (_, _, _, klass) in class_context.items():
        if enrollment_by_class[class_id]:
            model.add(sum(enrollment_by_class[class_id]) <= klass.limit)

    student_pair_cache: dict[tuple[str, str], cp_model.IntVar] = {}
    student_conflict_terms = 0
    try:
        for student in problem.students:
            possible = sorted(enrollment_by_student[student.id])
            for first_id, second_id in combinations(possible, 2):
                student_conflict_terms += 1
                if student_conflict_terms > max_pair_matrix_cells:
                    raise OverflowError(
                        "exact student-conflict model requires more than "
                        f"{max_pair_matrix_cells} conjunctions"
                    )
                pair_key = (first_id, second_id)
                time_conflict = student_pair_cache.get(pair_key)
                if time_conflict is None:
                    guard_pair_matrix_allocation(first_id, second_id)
                    matrix = _student_pair_matrix(
                        problem,
                        first=alternatives[first_id],
                        second=alternatives[second_id],
                        travel=travel,
                        deadline=deadline,
                    )
                    time_conflict = element_indicator(
                        first_id,
                        second_id,
                        "student_conflict",
                        matrix,
                    )
                    student_pair_cache[pair_key] = time_conflict
                first_enrollment = enrollment[(student.id, first_id)]
                second_enrollment = enrollment[(student.id, second_id)]
                conflict = model.new_bool_var(
                    f"student_{student.id}_conflict_{first_id}_{second_id}"
                )
                model.add(conflict <= first_enrollment)
                model.add(conflict <= second_enrollment)
                model.add(conflict <= time_conflict)
                model.add(
                    conflict >= first_enrollment + second_enrollment + time_conflict - 2
                )
                if problem.optimization.student:
                    objective_terms.append(problem.optimization.student * conflict)
                if student_conflict_terms % 256 == 0 and deadline_exceeded():
                    return _itc2019_native_failure(
                        status="DEADLINE_EXCEEDED",
                        started=started,
                        build_started=build_started,
                        random_seed=random_seed,
                        workers=workers,
                    )
            if deadline_exceeded():
                return _itc2019_native_failure(
                    status="DEADLINE_EXCEEDED",
                    started=started,
                    build_started=build_started,
                    random_seed=random_seed,
                    workers=workers,
                )
    except TimeoutError:
        return _itc2019_native_failure(
            status="DEADLINE_EXCEEDED",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
        )
    except OverflowError as exc:
        return _itc2019_native_failure(
            status="UNSUPPORTED_MODEL_SCALE",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
            unsupported_reasons=(str(exc),),
        )

    model.minimize(sum(objective_terms) if objective_terms else 0)
    build_finished = time.monotonic()
    remaining = deadline - build_finished
    if remaining <= 0:
        return _itc2019_native_failure(
            status="DEADLINE_EXCEEDED",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
        )

    solver = cp_model.CpSolver()
    # Do not round a sub-millisecond remainder up: the public API's budget covers
    # model construction and search, so CP-SAT must receive only the time left.
    solver.parameters.max_time_in_seconds = float(remaining)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.random_seed = int(random_seed)
    status_code = solver.solve(model)
    status = solver.status_name(status_code).upper()
    finished = time.monotonic()
    if status_code not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        return ITC2019NativeSolveResult(
            status=status,
            placements=(),
            student_classes={},
            objective=None,
            best_bound=(
                float(solver.best_objective_bound)
                if status_code != cp_model.MODEL_INVALID
                else None
            ),
            wall_time_seconds=finished - started,
            model_build_seconds=build_finished - build_started,
            solver_wall_time_seconds=float(solver.wall_time),
            conflicts=int(solver.num_conflicts),
            branches=int(solver.num_branches),
            deterministic_seed=random_seed,
            workers=workers,
        )

    placements = tuple(
        alternatives[klass.id][int(solver.value(choices[klass.id]))].placement
        for klass in problem.classes
    )
    student_classes = {
        student.id: tuple(
            sorted(
                class_id
                for (student_id, class_id), variable in enrollment.items()
                if student_id == student.id and solver.boolean_value(variable)
            )
        )
        for student in problem.students
    }
    try:
        objective = score_itc2019_solution(problem, placements, student_classes)
        validation_errors: list[str] = []
    except ValueError:
        objective = None
        validation_errors = validate_itc2019_solution(
            problem,
            placements,
            student_classes,
        )
    return ITC2019NativeSolveResult(
        status="INVALID_RESULT" if validation_errors else status,
        placements=placements,
        student_classes=student_classes,
        objective=objective,
        best_bound=float(solver.best_objective_bound),
        wall_time_seconds=finished - started,
        model_build_seconds=build_finished - build_started,
        solver_wall_time_seconds=float(solver.wall_time),
        conflicts=int(solver.num_conflicts),
        branches=int(solver.num_branches),
        deterministic_seed=random_seed,
        workers=workers,
        validation_errors=tuple(validation_errors),
    )


@dataclass(frozen=True)
class _ITC2019AutoDispatchEstimate:
    raw_cartesian_domain_values: int
    cartesian_admitted: bool
    selection_reason: str


def _raw_cartesian_domain_values(
    problem: ITC2019Problem,
    *,
    deadline: float,
) -> int:
    """Count canonical time x room values without constructing alternatives."""

    total = 0
    values_seen = 0
    for klass in problem.classes:
        unique_times = {
            (option.days, option.start, option.length, option.weeks)
            for option in klass.time_options
        }
        unique_rooms = (
            {option.room_id for option in klass.room_options}
            if klass.room_required
            else {None}
        )
        total += len(unique_times) * len(unique_rooms)
        values_seen += len(klass.time_options) + len(klass.room_options)
        if values_seen % 1024 == 0 and time.monotonic() >= deadline:
            raise TimeoutError("ITC-2019 auto formulation estimate timed out")
    if time.monotonic() >= deadline:
        raise TimeoutError("ITC-2019 auto formulation estimate timed out")
    return total


def _estimate_cartesian_scale_guards(
    problem: ITC2019Problem,
    alternatives: Mapping[str, tuple[_ITC2019Alternative, ...]],
    *,
    max_pair_matrix_cells: int,
    max_group_table_rows: int,
    deadline: float,
) -> str | None:
    """Mirror every Cartesian pair, conjunction, and group scale guard exactly."""

    if any(not rows for rows in alternatives.values()):
        # Empty placement domains are a semantic result, not a scale rejection.
        # Admit Cartesian so its existing INFEASIBLE_DOMAIN path remains authoritative.
        return None

    pair_cells = 0
    travel = _travel_values(problem)
    for distribution_index, distribution in enumerate(problem.distributions, start=1):
        base, parameters = _distribution_spec(distribution.type)
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        if base in _PAIR_DISTRIBUTIONS:
            for first_id, second_id in combinations(class_ids, 2):
                matrix_cells = len(alternatives[first_id]) * len(
                    alternatives[second_id]
                )
                if pair_cells + matrix_cells > max_pair_matrix_cells:
                    return "cartesian_pair_matrix_guard_exceeded"
                matrix = _distribution_pair_matrix(
                    base=base,
                    parameters=parameters,
                    first=alternatives[first_id],
                    second=alternatives[second_id],
                    travel=travel,
                    deadline=deadline,
                )
                pair_cells += matrix.charged_cells
                if pair_cells > max_pair_matrix_cells:
                    return "cartesian_pair_matrix_guard_exceeded"
        elif base in {"MaxBreaks", "MaxBlock"}:
            rows = 1
            for class_id in class_ids:
                rows *= len(alternatives[class_id])
                if rows > max_group_table_rows:
                    return "cartesian_group_table_guard_exceeded"
        if distribution_index % 64 == 0 and time.monotonic() >= deadline:
            raise TimeoutError("ITC-2019 auto formulation estimate timed out")

    course_classes = {
        course.id: {
            klass.id
            for configuration in course.configurations
            for subpart in configuration.subparts
            for klass in subpart.classes
        }
        for course in problem.courses
    }
    student_terms = 0
    student_pairs: set[tuple[str, str]] = set()
    for student_index, student in enumerate(problem.students):
        possible = sorted(
            set().union(
                *(course_classes[course_id] for course_id in student.course_ids)
            )
        )
        for first_id, second_id in combinations(possible, 2):
            student_terms += 1
            if student_terms > max_pair_matrix_cells:
                return "cartesian_student_conjunction_guard_exceeded"
            pair_key = (first_id, second_id)
            if pair_key not in student_pairs:
                matrix_cells = len(alternatives[first_id]) * len(
                    alternatives[second_id]
                )
                if pair_cells + matrix_cells > max_pair_matrix_cells:
                    return "cartesian_pair_matrix_guard_exceeded"
                student_pairs.add(pair_key)
                matrix = _student_pair_matrix(
                    problem,
                    first=alternatives[first_id],
                    second=alternatives[second_id],
                    travel=travel,
                    deadline=deadline,
                )
                pair_cells += matrix.charged_cells
                if pair_cells > max_pair_matrix_cells:
                    return "cartesian_pair_matrix_guard_exceeded"
        if student_index % 128 == 0 and time.monotonic() >= deadline:
            raise TimeoutError("ITC-2019 auto formulation estimate timed out")
    if time.monotonic() >= deadline:
        raise TimeoutError("ITC-2019 auto formulation estimate timed out")
    return None


def _estimate_itc2019_auto_dispatch(
    problem: ITC2019Problem,
    *,
    max_pair_matrix_cells: int,
    max_group_table_rows: int,
    deadline: float,
) -> _ITC2019AutoDispatchEstimate:
    raw_values = _raw_cartesian_domain_values(problem, deadline=deadline)
    if raw_values > ITC2019_AUTO_CARTESIAN_DOMAIN_THRESHOLD:
        return _ITC2019AutoDispatchEstimate(
            raw_cartesian_domain_values=raw_values,
            cartesian_admitted=False,
            selection_reason="raw_cartesian_domain_exceeds_auto_threshold",
        )
    alternatives = _native_class_alternatives(problem, deadline=deadline)
    guard_reason = _estimate_cartesian_scale_guards(
        problem,
        alternatives,
        max_pair_matrix_cells=max_pair_matrix_cells,
        max_group_table_rows=max_group_table_rows,
        deadline=deadline,
    )
    if guard_reason is not None:
        return _ITC2019AutoDispatchEstimate(
            raw_cartesian_domain_values=raw_values,
            cartesian_admitted=False,
            selection_reason=guard_reason,
        )
    return _ITC2019AutoDispatchEstimate(
        raw_cartesian_domain_values=raw_values,
        cartesian_admitted=True,
        selection_reason="cartesian_domain_and_scale_guards_admitted",
    )


def _with_formulation_telemetry(
    result: ITC2019NativeSolveResult,
    *,
    requested: str,
    effective: str,
    reason: str,
    raw_cartesian_domain_values: int | None,
    auto_threshold: int | None,
    wall_time_seconds: float | None = None,
    dispatch_seconds: float = 0.0,
) -> ITC2019NativeSolveResult:
    not_started = effective == "not_started"
    return replace(
        result,
        wall_time_seconds=(
            result.wall_time_seconds
            if wall_time_seconds is None
            else float(wall_time_seconds)
        ),
        model_build_seconds=result.model_build_seconds + float(dispatch_seconds),
        requested_formulation=requested,
        effective_formulation=effective,
        formulation="not_started" if not_started else result.formulation,
        sectioning_mode="not_started" if not_started else result.sectioning_mode,
        formulation_selection_reason=reason,
        raw_cartesian_domain_values=raw_cartesian_domain_values,
        auto_cartesian_domain_threshold=auto_threshold,
    )


def solve_itc2019_native(
    problem: ITC2019Problem,
    *,
    time_limit_seconds: float = 30.0,
    workers: int = 1,
    random_seed: int = 0,
    max_pair_matrix_cells: int = 2_000_000,
    max_group_table_rows: int = 200_000,
    max_joint_student_conjunctions: int = 200_000,
    max_sparse_room_constraints: int = 2_000_000,
    formulation: str = "auto",
) -> ITC2019NativeSolveResult:
    """Solve ITC-2019 with an exact, scale-guarded native formulation.

    The default chooses the Cartesian formulation only when its canonical raw
    time-room domain has at most 50,000 values and a model-free preflight admits
    its existing pair and group guards. Larger or guard-rejected instances use
    the sparse decomposed constructor whenever every required distribution has
    a lossless decomposed implementation; otherwise they fall back to the
    factorized model. Selection and solving share one absolute deadline. Every
    formulation remains directly selectable for reproducibility.
    """

    if formulation == "cartesian":
        result = _solve_itc2019_native_cartesian(
            problem,
            time_limit_seconds=time_limit_seconds,
            workers=workers,
            random_seed=random_seed,
            max_pair_matrix_cells=max_pair_matrix_cells,
            max_group_table_rows=max_group_table_rows,
        )
        return _with_formulation_telemetry(
            result,
            requested="cartesian",
            effective="cartesian",
            reason="explicit_cartesian",
            raw_cartesian_domain_values=None,
            auto_threshold=None,
        )
    if formulation == "decomposed":
        from benchmarks.itc2019_decomposed import solve_itc2019_decomposed

        result = solve_itc2019_decomposed(
            problem,
            time_limit_seconds=time_limit_seconds,
            workers=workers,
            random_seed=random_seed,
        )
        return _with_formulation_telemetry(
            result,
            requested="decomposed",
            effective="decomposed",
            reason="explicit_decomposed",
            raw_cartesian_domain_values=None,
            auto_threshold=None,
        )
    if formulation == "factorized":
        from benchmarks.itc2019_factorized import solve_itc2019_factorized

        result = solve_itc2019_factorized(
            problem,
            time_limit_seconds=time_limit_seconds,
            workers=workers,
            random_seed=random_seed,
            max_pair_matrix_cells=max_pair_matrix_cells,
            max_group_table_rows=max_group_table_rows,
            max_joint_student_conjunctions=max_joint_student_conjunctions,
            max_sparse_room_constraints=max_sparse_room_constraints,
        )
        return _with_formulation_telemetry(
            result,
            requested="factorized",
            effective="factorized",
            reason="explicit_factorized",
            raw_cartesian_domain_values=None,
            auto_threshold=None,
        )
    if formulation != "auto":
        raise ValueError(
            "formulation must be 'auto', 'decomposed', 'factorized', or 'cartesian'"
        )
    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be positive")
    if workers <= 0:
        raise ValueError("workers must be positive")
    if random_seed < 0:
        raise ValueError("random_seed must be non-negative")
    if (
        max_pair_matrix_cells <= 0
        or max_group_table_rows <= 0
        or max_joint_student_conjunctions <= 0
        or max_sparse_room_constraints <= 0
    ):
        raise ValueError("ITC-2019 encoding budgets must be positive")

    started = time.monotonic()
    deadline = started + float(time_limit_seconds)
    problem_errors = _validate_problem_references(problem)
    if problem_errors:
        result = _itc2019_native_failure(
            status="INVALID_PROBLEM",
            started=started,
            build_started=started,
            random_seed=random_seed,
            workers=workers,
            validation_errors=problem_errors,
        )
        return _with_formulation_telemetry(
            result,
            requested="auto",
            effective="not_started",
            reason="invalid_problem",
            raw_cartesian_domain_values=None,
            auto_threshold=ITC2019_AUTO_CARTESIAN_DOMAIN_THRESHOLD,
        )
    try:
        estimate = _estimate_itc2019_auto_dispatch(
            problem,
            max_pair_matrix_cells=max_pair_matrix_cells,
            max_group_table_rows=max_group_table_rows,
            deadline=deadline,
        )
    except TimeoutError:
        result = _itc2019_native_failure(
            status="DEADLINE_EXCEEDED",
            started=started,
            build_started=started,
            random_seed=random_seed,
            workers=workers,
        )
        return _with_formulation_telemetry(
            result,
            requested="auto",
            effective="not_started",
            reason="auto_dispatch_estimate_deadline_exceeded",
            raw_cartesian_domain_values=None,
            auto_threshold=ITC2019_AUTO_CARTESIAN_DOMAIN_THRESHOLD,
        )

    dispatch_finished = time.monotonic()
    remaining = deadline - dispatch_finished
    if remaining <= 0:
        result = _itc2019_native_failure(
            status="DEADLINE_EXCEEDED",
            started=started,
            build_started=started,
            random_seed=random_seed,
            workers=workers,
        )
        return _with_formulation_telemetry(
            result,
            requested="auto",
            effective="not_started",
            reason="auto_dispatch_budget_exhausted_after_estimate",
            raw_cartesian_domain_values=estimate.raw_cartesian_domain_values,
            auto_threshold=ITC2019_AUTO_CARTESIAN_DOMAIN_THRESHOLD,
        )

    if estimate.cartesian_admitted:
        effective = "cartesian"
        result = _solve_itc2019_native_cartesian(
            problem,
            time_limit_seconds=remaining,
            workers=workers,
            random_seed=random_seed,
            max_pair_matrix_cells=max_pair_matrix_cells,
            max_group_table_rows=max_group_table_rows,
        )
    else:
        from benchmarks.itc2019_decomposed import (
            decomposed_admission_reason,
            solve_itc2019_decomposed,
        )

        decomposed_reason = decomposed_admission_reason(problem)
        if decomposed_reason is None:
            effective = "decomposed"
            result = solve_itc2019_decomposed(
                problem,
                time_limit_seconds=remaining,
                workers=workers,
                random_seed=random_seed,
            )
            estimate = replace(
                estimate,
                selection_reason="decomposed_sparse_semantics_admitted",
            )
        else:
            effective = "factorized"
            from benchmarks.itc2019_factorized import solve_itc2019_factorized

            result = solve_itc2019_factorized(
                problem,
                time_limit_seconds=remaining,
                workers=workers,
                random_seed=random_seed,
                max_pair_matrix_cells=max_pair_matrix_cells,
                max_group_table_rows=max_group_table_rows,
                max_joint_student_conjunctions=max_joint_student_conjunctions,
                max_sparse_room_constraints=max_sparse_room_constraints,
            )
    finished = time.monotonic()
    return _with_formulation_telemetry(
        result,
        requested="auto",
        effective=effective,
        reason=estimate.selection_reason,
        raw_cartesian_domain_values=estimate.raw_cartesian_domain_values,
        auto_threshold=ITC2019_AUTO_CARTESIAN_DOMAIN_THRESHOLD,
        wall_time_seconds=finished - started,
        dispatch_seconds=dispatch_finished - started,
    )


def estimate_itc2019_factorized_scale(
    problem: ITC2019Problem,
    *,
    max_pair_matrix_cells: int = 2_000_000,
    max_group_table_rows: int = 200_000,
    max_joint_student_conjunctions: int = 200_000,
    max_sparse_room_constraints: int = 2_000_000,
) -> ITC2019FactorizedScaleEstimate:
    """Classify exact factorized admission without constructing or solving CP-SAT.

    ``max_group_table_rows`` remains the compatibility spelling for the exact
    sparse grouped-distribution cell budget used by the factorized formulation.
    """

    from benchmarks.itc2019_factorized import (
        estimate_itc2019_factorized_scale as estimate,
    )

    return estimate(
        problem,
        max_pair_matrix_cells=max_pair_matrix_cells,
        max_group_table_rows=max_group_table_rows,
        max_joint_student_conjunctions=max_joint_student_conjunctions,
        max_sparse_room_constraints=max_sparse_room_constraints,
    )


def parse_itc2019_solution(path: str | Path) -> ITC2019Solution:
    source = Path(path)
    root = ElementTree.parse(source).getroot()
    if _local_name(root.tag) != "solution":
        nested = _child(root, "solution")
        if nested is None:
            raise ValueError(
                f"Expected ITC-2019 <solution> root, got <{_local_name(root.tag)}>"
            )
        root = nested
    placements: list[ITC2019ClassPlacement] = []
    student_classes: dict[str, list[str]] = defaultdict(list)
    for class_element in _children(root, "class"):
        class_id = _required_attribute(class_element, "id")
        missing = [
            attribute
            for attribute in ("days", "start", "weeks")
            if attribute not in class_element.attrib
        ]
        if missing:
            raise ValueError(
                f"ITC-2019 solution class {class_id} is missing " + ", ".join(missing)
            )
        placements.append(
            ITC2019ClassPlacement(
                class_id=class_id,
                days=_required_attribute(class_element, "days"),
                start=_integer_attribute(class_element, "start"),
                weeks=_required_attribute(class_element, "weeks"),
                room_id=class_element.attrib.get("room"),
            )
        )
        for student_element in _children(class_element, "student"):
            student_classes[_required_attribute(student_element, "id")].append(class_id)
    return ITC2019Solution(
        placements=tuple(placements),
        student_classes={
            student_id: tuple(sorted(class_ids))
            for student_id, class_ids in sorted(student_classes.items())
        },
        metadata=tuple(
            sorted((str(key), str(value)) for key, value in root.attrib.items())
        ),
    )


def validate_itc2019_solution_document(
    problem: ITC2019Problem,
    solution: ITC2019Solution,
) -> list[str]:
    """Validate root identity together with all timetable and sectioning semantics."""

    metadata = dict(solution.metadata)
    errors: list[str] = []
    if metadata.get("name") != problem.name:
        errors.append(
            f"solution name {metadata.get('name')!r} does not match problem "
            f"{problem.name!r}"
        )
    errors.extend(
        validate_itc2019_solution(
            problem,
            solution.placements,
            solution.student_classes,
        )
    )
    return errors


def write_itc2019_solution(
    problem: ITC2019Problem,
    placements: Mapping[str, ITC2019ClassPlacement] | Sequence[ITC2019ClassPlacement],
    student_classes: Mapping[str, Sequence[str]],
    path: str | Path,
    *,
    metadata: Mapping[str, str | int | float] | None = None,
) -> Path:
    errors = validate_itc2019_solution(problem, placements, student_classes)
    if errors:
        raise ValueError("Invalid ITC-2019 solution: " + "; ".join(errors))

    by_class = _placement_map(placements)
    students_by_class: dict[str, list[str]] = defaultdict(list)
    for student_id, class_ids in student_classes.items():
        for class_id in class_ids:
            students_by_class[class_id].append(student_id)

    root = ElementTree.Element("solution")
    root.set("name", problem.name)
    for key, value in sorted((metadata or {}).items()):
        if key == "name":
            continue
        root.set(str(key), str(value))
    for class_id in sorted(by_class):
        placement = by_class[class_id]
        class_element = ElementTree.SubElement(root, "class")
        class_element.set("id", class_id)
        class_element.set("days", placement.days)
        class_element.set("start", str(placement.start))
        class_element.set("weeks", placement.weeks)
        if placement.room_id is not None:
            class_element.set("room", placement.room_id)
        for student_id in sorted(students_by_class.get(class_id, [])):
            student_element = ElementTree.SubElement(class_element, "student")
            student_element.set("id", student_id)

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tree = ElementTree.ElementTree(root)
    ElementTree.indent(tree, space="  ")
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return destination
