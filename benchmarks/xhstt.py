from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from functools import cached_property
from pathlib import Path
import random
import time
from typing import Iterable, Mapping, Sequence

from lxml import etree
from ortools.sat.python import cp_model


_STANDARD_CONSTRAINTS = frozenset(
    {
        "AssignResourceConstraint",
        "AssignTimeConstraint",
        "SplitEventsConstraint",
        "DistributeSplitEventsConstraint",
        "PreferResourcesConstraint",
        "PreferTimesConstraint",
        "AvoidSplitAssignmentsConstraint",
        "SpreadEventsConstraint",
        "LinkEventsConstraint",
        "OrderEventsConstraint",
        "AvoidClashesConstraint",
        "AvoidUnavailableTimesConstraint",
        "LimitIdleTimesConstraint",
        "ClusterBusyTimesConstraint",
        "LimitBusyTimesConstraint",
        "LimitWorkloadConstraint",
    }
)
_COST_FUNCTIONS = frozenset(
    {
        "Linear",
        "Quadratic",
        "Step",
        # Pre-XHSTT-2014 spellings remain useful when validating old archives.
        "SumSteps",
        "StepSum",
        "Sum",
        "SumSquares",
        "SquareSum",
    }
)
_MIN_CP_SEARCH_SECONDS = 0.05


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _children(element: etree._Element, name: str) -> list[etree._Element]:
    return [child for child in element if _local_name(child.tag) == name]


def _child(element: etree._Element, name: str) -> etree._Element | None:
    matches = _children(element, name)
    if len(matches) > 1:
        raise ValueError(
            f"XHSTT <{_local_name(element.tag)}> contains duplicate <{name}>"
        )
    return matches[0] if matches else None


def _required_child(element: etree._Element, name: str) -> etree._Element:
    result = _child(element, name)
    if result is None:
        raise ValueError(
            f"XHSTT <{_local_name(element.tag)}> is missing required <{name}>"
        )
    return result


def _text(element: etree._Element, name: str, *, default: str | None = None) -> str:
    child = _child(element, name)
    if child is None:
        if default is not None:
            return default
        raise ValueError(
            f"XHSTT <{_local_name(element.tag)}> is missing required <{name}>"
        )
    value = (child.text or "").strip()
    if not value:
        raise ValueError(
            f"XHSTT <{_local_name(element.tag)}> has empty <{name}>"
        )
    return value


def _integer_text(
    element: etree._Element,
    name: str,
    *,
    minimum: int | None = None,
    default: int | None = None,
) -> int:
    child = _child(element, name)
    if child is None:
        if default is None:
            raise ValueError(
                f"XHSTT <{_local_name(element.tag)}> is missing required <{name}>"
            )
        return int(default)
    raw = (child.text or "").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"XHSTT <{name}> must be an integer, got {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ValueError(f"XHSTT <{name}> must be at least {minimum}, got {value}")
    return value


def _boolean_text(element: etree._Element, name: str) -> bool:
    value = _text(element, name).lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"XHSTT <{name}> must be true or false, got {value!r}")


def _required_attribute(element: etree._Element, name: str) -> str:
    value = element.attrib.get(name)
    if value is None or not str(value).strip():
        raise ValueError(
            f"XHSTT <{_local_name(element.tag)}> is missing required "
            f"attribute {name!r}"
        )
    return str(value).strip()


def _references(parent: etree._Element | None, child_name: str) -> tuple[str, ...]:
    if parent is None:
        return ()
    return tuple(
        _required_attribute(child, "Reference")
        for child in _children(parent, child_name)
    )


def _ensure_unique(values: Iterable[str], *, kind: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        rendered = ", ".join(sorted(duplicates))
        raise ValueError(f"XHSTT duplicate {kind} id(s): {rendered}")


def _distance_to_interval(value: int, minimum: int, maximum: int) -> int:
    if value < minimum:
        return int(minimum - value)
    if value > maximum:
        return int(value - maximum)
    return 0


@dataclass(frozen=True)
class XHSTTTimeGroup:
    id: str
    name: str
    kind: str


@dataclass(frozen=True)
class XHSTTTime:
    id: str
    name: str
    group_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class XHSTTResourceType:
    id: str
    name: str


@dataclass(frozen=True)
class XHSTTResourceGroup:
    id: str
    name: str
    resource_type_id: str


@dataclass(frozen=True)
class XHSTTResource:
    id: str
    name: str
    resource_type_id: str
    group_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class XHSTTEventGroup:
    id: str
    name: str
    kind: str


@dataclass(frozen=True)
class XHSTTEventResource:
    role: str | None
    resource_type_id: str | None
    resource_id: str | None = None
    workload: int | None = None


@dataclass(frozen=True)
class XHSTTEvent:
    id: str
    name: str
    duration: int
    course_id: str | None = None
    preassigned_time_id: str | None = None
    resources: tuple[XHSTTEventResource, ...] = ()
    resource_group_ids: tuple[str, ...] = ()
    event_group_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class XHSTTTimeGroupLimit:
    time_group_id: str
    minimum: int
    maximum: int


@dataclass(frozen=True)
class XHSTTEventPair:
    first_event_id: str
    second_event_id: str
    minimum_separation: int
    maximum_separation: int


@dataclass(frozen=True)
class XHSTTConstraint:
    type: str
    id: str
    name: str
    required: bool
    weight: int
    cost_function: str
    applies_event_ids: tuple[str, ...] = ()
    applies_event_group_ids: tuple[str, ...] = ()
    applies_resource_ids: tuple[str, ...] = ()
    applies_resource_group_ids: tuple[str, ...] = ()
    role: str | None = None
    preferred_resource_ids: tuple[str, ...] = ()
    preferred_resource_group_ids: tuple[str, ...] = ()
    preferred_time_ids: tuple[str, ...] = ()
    preferred_time_group_ids: tuple[str, ...] = ()
    time_group_ids: tuple[str, ...] = ()
    time_group_limits: tuple[XHSTTTimeGroupLimit, ...] = ()
    event_pairs: tuple[XHSTTEventPair, ...] = ()
    duration: int | None = None
    minimum: int | None = None
    maximum: int | None = None
    minimum_duration: int | None = None
    maximum_duration: int | None = None
    minimum_amount: int | None = None
    maximum_amount: int | None = None


@dataclass(frozen=True)
class XHSTTProblem:
    id: str
    name: str
    times: tuple[XHSTTTime, ...]
    time_groups: tuple[XHSTTTimeGroup, ...]
    resource_types: tuple[XHSTTResourceType, ...]
    resource_groups: tuple[XHSTTResourceGroup, ...]
    resources: tuple[XHSTTResource, ...]
    event_groups: tuple[XHSTTEventGroup, ...]
    events: tuple[XHSTTEvent, ...]
    constraints: tuple[XHSTTConstraint, ...]
    unsupported_features: tuple[str, ...] = ()

    @cached_property
    def time_by_id(self) -> dict[str, XHSTTTime]:
        return {item.id: item for item in self.times}

    @cached_property
    def time_index(self) -> dict[str, int]:
        return {item.id: index for index, item in enumerate(self.times)}

    @cached_property
    def time_group_by_id(self) -> dict[str, XHSTTTimeGroup]:
        return {item.id: item for item in self.time_groups}

    @cached_property
    def times_by_group(self) -> dict[str, frozenset[str]]:
        output: dict[str, set[str]] = {
            group.id: set() for group in self.time_groups
        }
        for item in self.times:
            for group_id in item.group_ids:
                output[group_id].add(item.id)
        return {key: frozenset(value) for key, value in output.items()}

    @cached_property
    def resource_type_by_id(self) -> dict[str, XHSTTResourceType]:
        return {item.id: item for item in self.resource_types}

    @cached_property
    def resource_group_by_id(self) -> dict[str, XHSTTResourceGroup]:
        return {item.id: item for item in self.resource_groups}

    @cached_property
    def resource_by_id(self) -> dict[str, XHSTTResource]:
        return {item.id: item for item in self.resources}

    @cached_property
    def resources_by_group(self) -> dict[str, frozenset[str]]:
        output: dict[str, set[str]] = {
            group.id: set() for group in self.resource_groups
        }
        for resource in self.resources:
            for group_id in resource.group_ids:
                output[group_id].add(resource.id)
        return {key: frozenset(value) for key, value in output.items()}

    @cached_property
    def event_group_by_id(self) -> dict[str, XHSTTEventGroup]:
        return {item.id: item for item in self.event_groups}

    @cached_property
    def event_by_id(self) -> dict[str, XHSTTEvent]:
        return {item.id: item for item in self.events}

    @cached_property
    def events_by_group(self) -> dict[str, frozenset[str]]:
        output: dict[str, set[str]] = {
            group.id: set() for group in self.event_groups
        }
        for event in self.events:
            memberships = set(event.event_group_ids)
            if event.course_id is not None:
                memberships.add(event.course_id)
            for group_id in memberships:
                output[group_id].add(event.id)
        return {key: frozenset(value) for key, value in output.items()}


@dataclass(frozen=True)
class XHSTTResourceAssignment:
    role: str
    resource_id: str


@dataclass(frozen=True)
class XHSTTMeet:
    event_id: str
    duration: int
    time_id: str | None
    resource_assignments: tuple[XHSTTResourceAssignment, ...] = ()


@dataclass(frozen=True)
class XHSTTSolution:
    instance_id: str
    meets: tuple[XHSTTMeet, ...]
    description: str | None = None
    reported_score: tuple[int, int] | None = None


@dataclass(frozen=True)
class XHSTTConstraintCost:
    constraint_id: str
    constraint_type: str
    required: bool
    deviations: tuple[int, ...]
    cost: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class XHSTTScore:
    hard_cost: int
    soft_cost: int
    constraint_costs: tuple[XHSTTConstraintCost, ...] = ()

    @property
    def lexicographic(self) -> tuple[int, int]:
        return int(self.hard_cost), int(self.soft_cost)

    def to_dict(self) -> dict[str, object]:
        return {
            "hard_cost": int(self.hard_cost),
            "soft_cost": int(self.soft_cost),
            "lexicographic": list(self.lexicographic),
            "constraint_costs": [item.to_dict() for item in self.constraint_costs],
        }


@dataclass(frozen=True)
class XHSTTValidation:
    score: XHSTTScore
    errors: tuple[str, ...] = ()
    unsupported_features: tuple[str, ...] = ()

    @property
    def structurally_valid(self) -> bool:
        return not self.errors

    @property
    def feasible(self) -> bool:
        return (
            self.structurally_valid
            and not self.unsupported_features
            and self.score.hard_cost == 0
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "feasible": self.feasible,
            "structurally_valid": self.structurally_valid,
            "errors": list(self.errors),
            "unsupported_features": list(self.unsupported_features),
            "score": self.score.to_dict(),
        }


@dataclass(frozen=True)
class XHSTTArchive:
    id: str | None
    problems: tuple[XHSTTProblem, ...]
    solutions: tuple[XHSTTSolution, ...] = ()


@dataclass(frozen=True)
class XHSTTSolveResult:
    solution: XHSTTSolution
    validation: XHSTTValidation
    status: str
    raw_status: int
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
            "build_seconds": float(self.build_seconds),
            "search_seconds": float(self.search_seconds),
            "elapsed_seconds": float(self.elapsed_seconds),
            "deadline_overrun_seconds": float(self.deadline_overrun_seconds),
            "seed": int(self.seed),
            "workers": int(self.workers),
            "validation": self.validation.to_dict(),
            "telemetry": dict(self.telemetry),
        }


def _parse_time_groups(element: etree._Element) -> tuple[XHSTTTimeGroup, ...]:
    output: list[XHSTTTimeGroup] = []
    group_root = _child(element, "TimeGroups")
    if group_root is None:
        return ()
    for group in group_root:
        kind = _local_name(group.tag)
        if kind not in {"Day", "Week", "TimeGroup"}:
            raise ValueError(f"Unsupported XHSTT time group element <{kind}>")
        output.append(
            XHSTTTimeGroup(
                id=_required_attribute(group, "Id"),
                name=_text(group, "Name"),
                kind=kind,
            )
        )
    _ensure_unique((item.id for item in output), kind="time group")
    return tuple(output)


def _parse_times(element: etree._Element) -> tuple[XHSTTTime, ...]:
    output: list[XHSTTTime] = []
    for item in _children(element, "Time"):
        group_ids: list[str] = []
        week = _child(item, "Week")
        day = _child(item, "Day")
        if week is not None:
            group_ids.append(_required_attribute(week, "Reference"))
        if day is not None:
            group_ids.append(_required_attribute(day, "Reference"))
        group_ids.extend(_references(_child(item, "TimeGroups"), "TimeGroup"))
        output.append(
            XHSTTTime(
                id=_required_attribute(item, "Id"),
                name=_text(item, "Name"),
                group_ids=tuple(group_ids),
            )
        )
    if not output:
        raise ValueError("XHSTT instance has no times")
    _ensure_unique((item.id for item in output), kind="time")
    return tuple(output)


def _parse_resources(
    element: etree._Element,
) -> tuple[
    tuple[XHSTTResourceType, ...],
    tuple[XHSTTResourceGroup, ...],
    tuple[XHSTTResource, ...],
]:
    type_root = _required_child(element, "ResourceTypes")
    resource_types = tuple(
        XHSTTResourceType(
            id=_required_attribute(item, "Id"),
            name=_text(item, "Name"),
        )
        for item in _children(type_root, "ResourceType")
    )
    _ensure_unique((item.id for item in resource_types), kind="resource type")

    group_root = _child(element, "ResourceGroups")
    resource_groups = tuple(
        XHSTTResourceGroup(
            id=_required_attribute(item, "Id"),
            name=_text(item, "Name"),
            resource_type_id=_required_attribute(
                _required_child(item, "ResourceType"), "Reference"
            ),
        )
        for item in (() if group_root is None else _children(group_root, "ResourceGroup"))
    )
    _ensure_unique((item.id for item in resource_groups), kind="resource group")

    resources = tuple(
        XHSTTResource(
            id=_required_attribute(item, "Id"),
            name=_text(item, "Name"),
            resource_type_id=_required_attribute(
                _required_child(item, "ResourceType"), "Reference"
            ),
            group_ids=_references(_child(item, "ResourceGroups"), "ResourceGroup"),
        )
        for item in _children(element, "Resource")
    )
    _ensure_unique((item.id for item in resources), kind="resource")
    return resource_types, resource_groups, resources


def _parse_events(
    element: etree._Element,
) -> tuple[tuple[XHSTTEventGroup, ...], tuple[XHSTTEvent, ...]]:
    group_root = _child(element, "EventGroups")
    event_groups: list[XHSTTEventGroup] = []
    if group_root is not None:
        for item in group_root:
            kind = _local_name(item.tag)
            if kind not in {"Course", "EventGroup"}:
                raise ValueError(f"Unsupported XHSTT event group element <{kind}>")
            event_groups.append(
                XHSTTEventGroup(
                    id=_required_attribute(item, "Id"),
                    name=_text(item, "Name"),
                    kind=kind,
                )
            )
    _ensure_unique((item.id for item in event_groups), kind="event group")

    events: list[XHSTTEvent] = []
    for item in _children(element, "Event"):
        requirements: list[XHSTTEventResource] = []
        resource_root = _child(item, "Resources")
        if resource_root is not None:
            for requirement in _children(resource_root, "Resource"):
                role_element = _child(requirement, "Role")
                type_element = _child(requirement, "ResourceType")
                role = (
                    (role_element.text or "").strip()
                    if role_element is not None
                    else None
                )
                type_id = (
                    _required_attribute(type_element, "Reference")
                    if type_element is not None
                    else None
                )
                resource_id = requirement.attrib.get("Reference")
                if resource_id is None and (not role or type_id is None):
                    raise ValueError(
                        "XHSTT unassigned event resources require Role and ResourceType"
                    )
                workload_element = _child(requirement, "Workload")
                workload = (
                    _integer_text(requirement, "Workload", minimum=0)
                    if workload_element is not None
                    else None
                )
                requirements.append(
                    XHSTTEventResource(
                        role=role,
                        resource_type_id=type_id,
                        resource_id=resource_id,
                        workload=workload,
                    )
                )
        course = _child(item, "Course")
        preassigned_time = _child(item, "Time")
        events.append(
            XHSTTEvent(
                id=_required_attribute(item, "Id"),
                name=_text(item, "Name"),
                duration=_integer_text(item, "Duration", minimum=1),
                course_id=(
                    _required_attribute(course, "Reference")
                    if course is not None
                    else None
                ),
                preassigned_time_id=(
                    _required_attribute(preassigned_time, "Reference")
                    if preassigned_time is not None
                    else None
                ),
                resources=tuple(requirements),
                resource_group_ids=_references(
                    _child(item, "ResourceGroups"), "ResourceGroup"
                ),
                event_group_ids=_references(
                    _child(item, "EventGroups"), "EventGroup"
                ),
            )
        )
    if not events:
        raise ValueError("XHSTT instance has no events")
    _ensure_unique((item.id for item in events), kind="event")
    return tuple(event_groups), tuple(events)


def _parse_applies_to(
    element: etree._Element,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    applies = _required_child(element, "AppliesTo")
    return (
        _references(_child(applies, "Events"), "Event"),
        _references(_child(applies, "EventGroups"), "EventGroup"),
        _references(_child(applies, "Resources"), "Resource"),
        _references(_child(applies, "ResourceGroups"), "ResourceGroup"),
    )


def _parse_constraint(element: etree._Element) -> XHSTTConstraint:
    constraint_type = _local_name(element.tag)
    constraint_id = _required_attribute(element, "Id")
    cost_function = _text(element, "CostFunction")
    if cost_function not in _COST_FUNCTIONS:
        raise ValueError(
            f"Unsupported XHSTT cost function {cost_function!r} in {constraint_id}"
        )
    common: dict[str, object] = {
        "type": constraint_type,
        "id": constraint_id,
        "name": _text(element, "Name"),
        "required": _boolean_text(element, "Required"),
        "weight": _integer_text(element, "Weight", minimum=0),
        "cost_function": cost_function,
    }

    event_ids: tuple[str, ...] = ()
    event_group_ids: tuple[str, ...] = ()
    resource_ids: tuple[str, ...] = ()
    resource_group_ids: tuple[str, ...] = ()
    if constraint_type != "OrderEventsConstraint":
        event_ids, event_group_ids, resource_ids, resource_group_ids = (
            _parse_applies_to(element)
        )
    common.update(
        {
            "applies_event_ids": event_ids,
            "applies_event_group_ids": event_group_ids,
            "applies_resource_ids": resource_ids,
            "applies_resource_group_ids": resource_group_ids,
        }
    )

    if constraint_type in {
        "AssignResourceConstraint",
        "PreferResourcesConstraint",
        "AvoidSplitAssignmentsConstraint",
    }:
        common["role"] = _text(element, "Role")
    if constraint_type == "SplitEventsConstraint":
        common.update(
            {
                "minimum_duration": _integer_text(
                    element, "MinimumDuration", minimum=1
                ),
                "maximum_duration": _integer_text(
                    element, "MaximumDuration", minimum=1
                ),
                "minimum_amount": _integer_text(
                    element, "MinimumAmount", minimum=0
                ),
                "maximum_amount": _integer_text(
                    element, "MaximumAmount", minimum=0
                ),
            }
        )
    elif constraint_type == "DistributeSplitEventsConstraint":
        common.update(
            {
                "duration": _integer_text(element, "Duration", minimum=1),
                "minimum": _integer_text(element, "Minimum", minimum=0),
                "maximum": _integer_text(element, "Maximum", minimum=0),
            }
        )
    elif constraint_type == "PreferResourcesConstraint":
        common.update(
            {
                "preferred_resource_ids": _references(
                    _child(element, "Resources"), "Resource"
                ),
                "preferred_resource_group_ids": _references(
                    _child(element, "ResourceGroups"), "ResourceGroup"
                ),
            }
        )
    elif constraint_type == "PreferTimesConstraint":
        duration_element = _child(element, "Duration")
        common.update(
            {
                "preferred_time_ids": _references(
                    _child(element, "Times"), "Time"
                ),
                "preferred_time_group_ids": _references(
                    _child(element, "TimeGroups"), "TimeGroup"
                ),
                "duration": (
                    _integer_text(element, "Duration", minimum=1)
                    if duration_element is not None
                    else None
                ),
            }
        )
    elif constraint_type == "SpreadEventsConstraint":
        limits: list[XHSTTTimeGroupLimit] = []
        group_root = _required_child(element, "TimeGroups")
        for item in _children(group_root, "TimeGroup"):
            limits.append(
                XHSTTTimeGroupLimit(
                    time_group_id=_required_attribute(item, "Reference"),
                    minimum=_integer_text(item, "Minimum", minimum=0),
                    maximum=_integer_text(item, "Maximum", minimum=0),
                )
            )
        common["time_group_limits"] = tuple(limits)
    elif constraint_type == "OrderEventsConstraint":
        applies = _required_child(element, "AppliesTo")
        pair_root = _required_child(applies, "EventPairs")
        pairs: list[XHSTTEventPair] = []
        for pair in _children(pair_root, "EventPair"):
            pairs.append(
                XHSTTEventPair(
                    first_event_id=_required_attribute(
                        _required_child(pair, "FirstEvent"), "Reference"
                    ),
                    second_event_id=_required_attribute(
                        _required_child(pair, "SecondEvent"), "Reference"
                    ),
                    minimum_separation=_integer_text(
                        pair, "MinSeparation", minimum=0
                    ),
                    maximum_separation=_integer_text(
                        pair, "MaxSeparation", minimum=0
                    ),
                )
            )
        common["event_pairs"] = tuple(pairs)
    elif constraint_type == "AvoidUnavailableTimesConstraint":
        common.update(
            {
                "preferred_time_ids": _references(
                    _child(element, "Times"), "Time"
                ),
                "preferred_time_group_ids": _references(
                    _child(element, "TimeGroups"), "TimeGroup"
                ),
            }
        )
    elif constraint_type in {
        "LimitIdleTimesConstraint",
        "ClusterBusyTimesConstraint",
        "LimitBusyTimesConstraint",
    }:
        common.update(
            {
                "time_group_ids": _references(
                    _required_child(element, "TimeGroups"), "TimeGroup"
                ),
                "minimum": _integer_text(element, "Minimum", minimum=0),
                "maximum": _integer_text(element, "Maximum", minimum=0),
            }
        )
    elif constraint_type == "LimitWorkloadConstraint":
        common.update(
            {
                "minimum": _integer_text(element, "Minimum", minimum=0),
                "maximum": _integer_text(element, "Maximum", minimum=0),
            }
        )
    result = XHSTTConstraint(**common)
    numeric_pairs = (
        (result.minimum, result.maximum, "minimum/maximum"),
        (
            result.minimum_duration,
            result.maximum_duration,
            "minimum/maximum duration",
        ),
        (
            result.minimum_amount,
            result.maximum_amount,
            "minimum/maximum amount",
        ),
    )
    for minimum, maximum, label in numeric_pairs:
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(
                f"XHSTT constraint {constraint_id} has inverted {label}"
            )
    for limit in result.time_group_limits:
        if limit.minimum > limit.maximum:
            raise ValueError(
                f"XHSTT constraint {constraint_id} has inverted time-group limits"
            )
    for pair in result.event_pairs:
        if pair.minimum_separation > pair.maximum_separation:
            raise ValueError(
                f"XHSTT constraint {constraint_id} has inverted separation limits"
            )
    return result


def _validate_problem_references(problem: XHSTTProblem) -> None:
    time_ids = set(problem.time_by_id)
    time_group_ids = set(problem.time_group_by_id)
    resource_type_ids = set(problem.resource_type_by_id)
    resource_group_ids = set(problem.resource_group_by_id)
    resource_ids = set(problem.resource_by_id)
    event_group_ids = set(problem.event_group_by_id)
    event_ids = set(problem.event_by_id)

    def require(values: Iterable[str], valid: set[str], kind: str) -> None:
        missing = sorted(set(values) - valid)
        if missing:
            raise ValueError(
                f"XHSTT contains unknown {kind} reference(s): {', '.join(missing)}"
            )

    for item in problem.times:
        require(item.group_ids, time_group_ids, "time group")
    for group in problem.resource_groups:
        require((group.resource_type_id,), resource_type_ids, "resource type")
    for resource in problem.resources:
        require((resource.resource_type_id,), resource_type_ids, "resource type")
        require(resource.group_ids, resource_group_ids, "resource group")
        for group_id in resource.group_ids:
            if (
                problem.resource_group_by_id[group_id].resource_type_id
                != resource.resource_type_id
            ):
                raise ValueError(
                    f"XHSTT resource {resource.id} belongs to group {group_id} "
                    "of a different resource type"
                )
    for event in problem.events:
        if event.course_id is not None:
            require((event.course_id,), event_group_ids, "event group")
        if event.preassigned_time_id is not None:
            require((event.preassigned_time_id,), time_ids, "time")
        require(event.event_group_ids, event_group_ids, "event group")
        require(event.resource_group_ids, resource_group_ids, "resource group")
        unassigned_roles: list[str] = []
        for requirement in event.resources:
            if requirement.resource_id is not None:
                require((requirement.resource_id,), resource_ids, "resource")
            if requirement.resource_type_id is not None:
                require(
                    (requirement.resource_type_id,),
                    resource_type_ids,
                    "resource type",
                )
            if requirement.resource_id is not None and requirement.resource_type_id:
                actual = problem.resource_by_id[requirement.resource_id].resource_type_id
                if actual != requirement.resource_type_id:
                    raise ValueError(
                        f"XHSTT event {event.id} assigns resource "
                        f"{requirement.resource_id} with the wrong resource type"
                    )
            if requirement.resource_id is None and requirement.role is not None:
                unassigned_roles.append(requirement.role)
        _ensure_unique(unassigned_roles, kind=f"role in event {event.id}")

    for constraint in problem.constraints:
        require(constraint.applies_event_ids, event_ids, "event")
        require(constraint.applies_event_group_ids, event_group_ids, "event group")
        require(constraint.applies_resource_ids, resource_ids, "resource")
        require(
            constraint.applies_resource_group_ids,
            resource_group_ids,
            "resource group",
        )
        require(constraint.preferred_resource_ids, resource_ids, "resource")
        require(
            constraint.preferred_resource_group_ids,
            resource_group_ids,
            "resource group",
        )
        require(constraint.preferred_time_ids, time_ids, "time")
        require(
            constraint.preferred_time_group_ids, time_group_ids, "time group"
        )
        require(constraint.time_group_ids, time_group_ids, "time group")
        require(
            (item.time_group_id for item in constraint.time_group_limits),
            time_group_ids,
            "time group",
        )
        require(
            (
                event_id
                for pair in constraint.event_pairs
                for event_id in (pair.first_event_id, pair.second_event_id)
            ),
            event_ids,
            "event",
        )


def _parse_problem(element: etree._Element) -> XHSTTProblem:
    instance_id = _required_attribute(element, "Id")
    metadata = _child(element, "MetaData")
    name = (
        _text(metadata, "Name", default=instance_id)
        if metadata is not None
        else instance_id
    )
    time_root = _required_child(element, "Times")
    resource_root = _required_child(element, "Resources")
    event_root = _required_child(element, "Events")
    constraint_root = _required_child(element, "Constraints")
    time_groups = _parse_time_groups(time_root)
    times = _parse_times(time_root)
    resource_types, resource_groups, resources = _parse_resources(resource_root)
    event_groups, events = _parse_events(event_root)

    constraints: list[XHSTTConstraint] = []
    unsupported: list[str] = []
    for item in constraint_root:
        constraint_type = _local_name(item.tag)
        if constraint_type not in _STANDARD_CONSTRAINTS:
            constraint_id = item.attrib.get("Id", "missing-id")
            unsupported.append(f"constraint {constraint_type} ({constraint_id})")
            continue
        constraints.append(_parse_constraint(item))
    _ensure_unique((item.id for item in constraints), kind="constraint")
    problem = XHSTTProblem(
        id=instance_id,
        name=name,
        times=times,
        time_groups=time_groups,
        resource_types=resource_types,
        resource_groups=resource_groups,
        resources=resources,
        event_groups=event_groups,
        events=events,
        constraints=tuple(constraints),
        unsupported_features=tuple(unsupported),
    )
    _validate_problem_references(problem)
    return problem


def _secure_xml_root(path: str | Path) -> etree._Element:
    source = Path(path)
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        huge_tree=False,
        remove_comments=True,
    )
    try:
        tree = etree.parse(str(source), parser)
    except (OSError, etree.XMLSyntaxError) as exc:
        raise ValueError(f"Could not parse XHSTT XML {source}: {exc}") from exc
    if tree.docinfo.doctype:
        raise ValueError("XHSTT parser rejects documents with a DOCTYPE declaration")
    root = tree.getroot()
    if _local_name(root.tag) != "HighSchoolTimetableArchive":
        raise ValueError(
            "XHSTT root must be <HighSchoolTimetableArchive>, got "
            f"<{_local_name(root.tag)}>"
        )
    return root


def _parse_solution_element(
    element: etree._Element,
    problem: XHSTTProblem,
) -> XHSTTSolution:
    instance_id = _required_attribute(element, "Reference")
    if instance_id != problem.id:
        raise ValueError(
            f"XHSTT solution references {instance_id!r}, expected {problem.id!r}"
        )
    event_root = _child(element, "Events")
    raw_rows: list[
        tuple[
            str,
            int | None,
            str | None,
            tuple[XHSTTResourceAssignment, ...],
        ]
    ] = []
    if event_root is not None:
        for row in _children(event_root, "Event"):
            event_id = _required_attribute(row, "Reference")
            duration_element = _child(row, "Duration")
            duration = (
                _integer_text(row, "Duration", minimum=1)
                if duration_element is not None
                else None
            )
            time_element = _child(row, "Time")
            time_id = (
                _required_attribute(time_element, "Reference")
                if time_element is not None
                else None
            )
            assignments: list[XHSTTResourceAssignment] = []
            resources_element = _child(row, "Resources")
            if resources_element is not None:
                for assignment in _children(resources_element, "Resource"):
                    assignments.append(
                        XHSTTResourceAssignment(
                            role=_text(assignment, "Role"),
                            resource_id=_required_attribute(assignment, "Reference"),
                        )
                    )
            raw_rows.append((event_id, duration, time_id, tuple(assignments)))

    row_counts: dict[str, int] = defaultdict(int)
    for event_id, _, _, _ in raw_rows:
        row_counts[event_id] += 1
    meets: list[XHSTTMeet] = []
    for event_id, duration, time_id, assignments in raw_rows:
        event = problem.event_by_id.get(event_id)
        if duration is None:
            if event is None:
                raise ValueError(
                    f"XHSTT solution references unknown event {event_id!r}"
                )
            if row_counts[event_id] != 1:
                raise ValueError(
                    f"XHSTT split event {event_id!r} must state each Duration"
                )
            duration = event.duration
        meets.append(
            XHSTTMeet(
                event_id=event_id,
                duration=duration,
                time_id=time_id,
                resource_assignments=assignments,
            )
        )
    report = _child(element, "Report")
    reported_score: tuple[int, int] | None = None
    if report is not None:
        hard = _child(report, "InfeasibilityValue")
        soft = _child(report, "ObjectiveValue")
        if hard is not None and soft is not None:
            reported_score = (
                _integer_text(report, "InfeasibilityValue", minimum=0),
                _integer_text(report, "ObjectiveValue", minimum=0),
            )
    description_element = _child(element, "Description")
    description = (
        _text(element, "Description")
        if description_element is not None
        else element.attrib.get("Description")
    )
    return XHSTTSolution(
        instance_id=instance_id,
        meets=tuple(meets),
        description=description,
        reported_score=reported_score,
    )


def parse_xhstt_archive(
    path: str | Path,
    *,
    include_solutions: bool = False,
) -> XHSTTArchive:
    """Parse a current XHSTT archive without silently projecting semantics."""

    root = _secure_xml_root(path)
    instances_root = _child(root, "Instances")
    problems = tuple(
        _parse_problem(item)
        for item in (
            () if instances_root is None else _children(instances_root, "Instance")
        )
    )
    _ensure_unique((item.id for item in problems), kind="instance")
    if not problems and not include_solutions:
        raise ValueError("XHSTT archive has no instances")
    solutions: list[XHSTTSolution] = []
    if include_solutions:
        problem_by_id = {item.id: item for item in problems}
        solution_groups = _child(root, "SolutionGroups")
        if solution_groups is not None:
            for group in _children(solution_groups, "SolutionGroup"):
                for item in _children(group, "Solution"):
                    reference = _required_attribute(item, "Reference")
                    problem = problem_by_id.get(reference)
                    if problem is None:
                        raise ValueError(
                            f"XHSTT solution references unknown instance {reference!r}"
                        )
                    solutions.append(_parse_solution_element(item, problem))
    return XHSTTArchive(
        id=root.attrib.get("Id"),
        problems=problems,
        solutions=tuple(solutions),
    )


def parse_xhstt(path: str | Path, *, instance_id: str | None = None) -> XHSTTProblem:
    archive = parse_xhstt_archive(path)
    if instance_id is not None:
        for problem in archive.problems:
            if problem.id == instance_id:
                return problem
        raise ValueError(f"XHSTT archive has no instance {instance_id!r}")
    if len(archive.problems) != 1:
        raise ValueError(
            "XHSTT archive contains multiple instances; provide instance_id explicitly"
        )
    return archive.problems[0]


def parse_xhstt_solutions(
    path: str | Path,
    problem: XHSTTProblem,
) -> tuple[XHSTTSolution, ...]:
    root = _secure_xml_root(path)
    output: list[XHSTTSolution] = []
    solution_groups = _child(root, "SolutionGroups")
    if solution_groups is None:
        return ()
    for group in _children(solution_groups, "SolutionGroup"):
        for item in _children(group, "Solution"):
            output.append(_parse_solution_element(item, problem))
    return tuple(output)


def write_xhstt_solution(
    path: str | Path,
    solution: XHSTTSolution,
    *,
    solution_group_id: str = "Planora",
) -> None:
    """Write a solution-only XHSTT archive suitable for transport or merging."""

    root = etree.Element("HighSchoolTimetableArchive")
    etree.SubElement(root, "Instances")
    groups = etree.SubElement(root, "SolutionGroups")
    group = etree.SubElement(groups, "SolutionGroup", Id=solution_group_id)
    solution_element = etree.SubElement(
        group, "Solution", Reference=solution.instance_id
    )
    if solution.description:
        etree.SubElement(solution_element, "Description").text = (
            solution.description
        )
    events_element = etree.SubElement(solution_element, "Events")
    for meet in solution.meets:
        event_element = etree.SubElement(
            events_element, "Event", Reference=meet.event_id
        )
        etree.SubElement(event_element, "Duration").text = str(meet.duration)
        if meet.time_id is not None:
            etree.SubElement(event_element, "Time", Reference=meet.time_id)
        if meet.resource_assignments:
            resources = etree.SubElement(event_element, "Resources")
            for assignment in meet.resource_assignments:
                resource = etree.SubElement(
                    resources, "Resource", Reference=assignment.resource_id
                )
                etree.SubElement(resource, "Role").text = assignment.role
    if solution.reported_score is not None:
        report = etree.SubElement(solution_element, "Report")
        etree.SubElement(report, "InfeasibilityValue").text = str(
            solution.reported_score[0]
        )
        etree.SubElement(report, "ObjectiveValue").text = str(
            solution.reported_score[1]
        )
    payload = etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )
    Path(path).write_bytes(payload)


def _applied_events(
    problem: XHSTTProblem,
    constraint: XHSTTConstraint,
) -> frozenset[str]:
    output = set(constraint.applies_event_ids)
    for group_id in constraint.applies_event_group_ids:
        output.update(problem.events_by_group[group_id])
    return frozenset(output)


def _applied_resources(
    problem: XHSTTProblem,
    constraint: XHSTTConstraint,
) -> frozenset[str]:
    output = set(constraint.applies_resource_ids)
    for group_id in constraint.applies_resource_group_ids:
        output.update(problem.resources_by_group[group_id])
    return frozenset(output)


def _selected_times(
    problem: XHSTTProblem,
    time_ids: Sequence[str],
    time_group_ids: Sequence[str],
) -> frozenset[str]:
    output = set(time_ids)
    for group_id in time_group_ids:
        output.update(problem.times_by_group[group_id])
    return frozenset(output)


def _selected_resources(
    problem: XHSTTProblem,
    resource_ids: Sequence[str],
    resource_group_ids: Sequence[str],
) -> frozenset[str]:
    output = set(resource_ids)
    for group_id in resource_group_ids:
        output.update(problem.resources_by_group[group_id])
    return frozenset(output)


@dataclass(frozen=True)
class _MeetState:
    meet: XHSTTMeet
    event: XHSTTEvent
    effective_time_id: str | None
    occupied_time_ids: tuple[str, ...]
    role_assignments: Mapping[str, str]
    attending_resources: frozenset[str]
    workload_rows: tuple[tuple[str, int], ...]


def _normalize_solution(
    problem: XHSTTProblem,
    solution: XHSTTSolution,
) -> tuple[dict[str, tuple[_MeetState, ...]], tuple[str, ...]]:
    errors: list[str] = []
    if solution.instance_id != problem.id:
        errors.append(
            f"solution references instance {solution.instance_id!r}, expected {problem.id!r}"
        )
    raw_by_event: dict[str, list[XHSTTMeet]] = defaultdict(list)
    for meet in solution.meets:
        if meet.event_id not in problem.event_by_id:
            errors.append(f"solution references unknown event {meet.event_id!r}")
            continue
        raw_by_event[meet.event_id].append(meet)

    states_by_event: dict[str, tuple[_MeetState, ...]] = {}
    for event in problem.events:
        meets = list(raw_by_event.get(event.id, []))
        # Every instance event initially owns one full-duration meet in the
        # XHSTT solution model.  An absent row therefore means an unscheduled
        # implicit meet (or the preassigned meet), not a deleted event.
        if not meets:
            meets = [XHSTTMeet(event.id, event.duration, None)]
        total_duration = sum(meet.duration for meet in meets)
        if total_duration != event.duration:
            errors.append(
                f"event {event.id} solution duration {total_duration} does not equal "
                f"instance duration {event.duration}"
            )
        states: list[_MeetState] = []
        variable_by_role = {
            item.role: item
            for item in event.resources
            if item.resource_id is None and item.role is not None
        }
        fixed_by_role = {
            item.role: item.resource_id
            for item in event.resources
            if item.resource_id is not None and item.role is not None
        }
        fixed_resources = {
            item.resource_id
            for item in event.resources
            if item.resource_id is not None
        }
        for group_id in event.resource_group_ids:
            fixed_resources.update(problem.resources_by_group[group_id])
        explicit_workload_seen: set[tuple[int, str]] = set()

        for meet_index, meet in enumerate(meets):
            if meet.duration <= 0:
                errors.append(
                    f"event {event.id} meet {meet_index} has non-positive duration"
                )
            assignment_map: dict[str, str] = {}
            for assignment in meet.resource_assignments:
                if assignment.role in assignment_map:
                    errors.append(
                        f"event {event.id} meet {meet_index} assigns role "
                        f"{assignment.role!r} more than once"
                    )
                    continue
                resource = problem.resource_by_id.get(assignment.resource_id)
                if resource is None:
                    errors.append(
                        f"event {event.id} meet {meet_index} references unknown "
                        f"resource {assignment.resource_id!r}"
                    )
                    continue
                requirement = variable_by_role.get(assignment.role)
                fixed_resource_id = fixed_by_role.get(assignment.role)
                if requirement is None and fixed_resource_id is None:
                    errors.append(
                        f"event {event.id} meet {meet_index} assigns undeclared "
                        f"role {assignment.role!r}"
                    )
                    continue
                if fixed_resource_id is not None:
                    if fixed_resource_id != assignment.resource_id:
                        errors.append(
                            f"event {event.id} meet {meet_index} overrides preassigned "
                            f"role {assignment.role!r}"
                        )
                    assignment_map[assignment.role] = fixed_resource_id
                    continue
                assert requirement is not None
                if resource.resource_type_id != requirement.resource_type_id:
                    errors.append(
                        f"event {event.id} meet {meet_index} assigns resource "
                        f"{resource.id} of the wrong type to role {assignment.role!r}"
                    )
                    continue
                assignment_map[assignment.role] = resource.id

            effective_time_id = meet.time_id
            if event.preassigned_time_id is not None:
                if meet.time_id not in {None, event.preassigned_time_id}:
                    errors.append(
                        f"event {event.id} meet {meet_index} overrides preassigned time"
                    )
                effective_time_id = event.preassigned_time_id
            occupied: tuple[str, ...] = ()
            if effective_time_id is not None:
                start = problem.time_index.get(effective_time_id)
                if start is None:
                    errors.append(
                        f"event {event.id} meet {meet_index} references unknown time "
                        f"{effective_time_id!r}"
                    )
                elif start + meet.duration > len(problem.times):
                    errors.append(
                        f"event {event.id} meet {meet_index} extends beyond the cycle"
                    )
                else:
                    occupied = tuple(
                        item.id
                        for item in problem.times[start : start + meet.duration]
                    )

            attending = set(fixed_resources)
            attending.update(assignment_map.values())
            workload_rows: list[tuple[str, int]] = []
            described_resources: set[str] = set()
            for requirement_index, requirement in enumerate(event.resources):
                resource_id = requirement.resource_id
                if resource_id is None and requirement.role is not None:
                    resource_id = assignment_map.get(requirement.role)
                if resource_id is not None:
                    described_resources.add(resource_id)
                    if requirement.workload is not None:
                        marker = (requirement_index, resource_id)
                        if marker in explicit_workload_seen:
                            continue
                        explicit_workload_seen.add(marker)
                    workload_rows.append(
                        (
                            resource_id,
                            meet.duration
                            if requirement.workload is None
                            else requirement.workload,
                        )
                    )
            for resource_id in attending - described_resources:
                workload_rows.append((resource_id, meet.duration))
            states.append(
                _MeetState(
                    meet=meet,
                    event=event,
                    effective_time_id=effective_time_id,
                    occupied_time_ids=occupied,
                    role_assignments=assignment_map,
                    attending_resources=frozenset(attending),
                    workload_rows=tuple(workload_rows),
                )
            )
        states_by_event[event.id] = tuple(states)
    return states_by_event, tuple(errors)


def _resource_views(
    problem: XHSTTProblem,
    states_by_event: Mapping[str, Sequence[_MeetState]],
) -> tuple[
    dict[str, set[str]],
    dict[tuple[str, str], int],
    dict[str, int],
]:
    busy: dict[str, set[str]] = {resource.id: set() for resource in problem.resources}
    multiplicity: dict[tuple[str, str], int] = defaultdict(int)
    workload: dict[str, int] = defaultdict(int)
    for states in states_by_event.values():
        for state in states:
            for resource_id in state.attending_resources:
                for time_id in state.occupied_time_ids:
                    busy[resource_id].add(time_id)
                    multiplicity[(resource_id, time_id)] += 1
            for resource_id, amount in state.workload_rows:
                workload[resource_id] += amount
    return busy, multiplicity, workload


def _constraint_deviation_groups(
    problem: XHSTTProblem,
    constraint: XHSTTConstraint,
    states_by_event: Mapping[str, Sequence[_MeetState]],
    busy: Mapping[str, set[str]],
    multiplicity: Mapping[tuple[str, str], int],
    workload: Mapping[str, int],
) -> tuple[tuple[int, ...], ...]:
    applied_events = _applied_events(problem, constraint)
    applied_resources = _applied_resources(problem, constraint)
    groups: list[tuple[int, ...]] = []
    if constraint.type == "AssignResourceConstraint":
        assert constraint.role is not None
        for event_id in sorted(applied_events):
            event = problem.event_by_id[event_id]
            role_requirements = [
                item for item in event.resources if item.role == constraint.role
            ]
            if not role_requirements or any(
                item.resource_id is not None for item in role_requirements
            ):
                continue
            groups.append(
                tuple(
                    state.meet.duration
                    if constraint.role not in state.role_assignments
                    else 0
                    for state in states_by_event[event_id]
                )
            )
    elif constraint.type == "AssignTimeConstraint":
        for event_id in sorted(applied_events):
            event = problem.event_by_id[event_id]
            if event.preassigned_time_id is not None:
                continue
            groups.append(
                tuple(
                    state.meet.duration if state.effective_time_id is None else 0
                    for state in states_by_event[event_id]
                )
            )
    elif constraint.type == "SplitEventsConstraint":
        assert constraint.minimum_amount is not None
        assert constraint.maximum_amount is not None
        assert constraint.minimum_duration is not None
        assert constraint.maximum_duration is not None
        for event_id in sorted(applied_events):
            states = states_by_event[event_id]
            deviations = [
                _distance_to_interval(
                    len(states),
                    constraint.minimum_amount,
                    constraint.maximum_amount,
                )
            ]
            deviations.extend(
                _distance_to_interval(
                    state.meet.duration,
                    constraint.minimum_duration,
                    constraint.maximum_duration,
                )
                for state in states
            )
            groups.append(tuple(deviations))
    elif constraint.type == "DistributeSplitEventsConstraint":
        assert constraint.duration is not None
        assert constraint.minimum is not None
        assert constraint.maximum is not None
        for event_id in sorted(applied_events):
            amount = sum(
                state.meet.duration == constraint.duration
                for state in states_by_event[event_id]
            )
            groups.append(
                (
                    _distance_to_interval(
                        amount, constraint.minimum, constraint.maximum
                    ),
                )
            )
    elif constraint.type == "PreferResourcesConstraint":
        assert constraint.role is not None
        selected = _selected_resources(
            problem,
            constraint.preferred_resource_ids,
            constraint.preferred_resource_group_ids,
        )
        for event_id in sorted(applied_events):
            event = problem.event_by_id[event_id]
            requirements = [
                item for item in event.resources if item.role == constraint.role
            ]
            if not requirements or any(item.resource_id is not None for item in requirements):
                continue
            groups.append(
                tuple(
                    state.meet.duration
                    if (
                        (assigned := state.role_assignments.get(constraint.role))
                        is not None
                        and assigned not in selected
                    )
                    else 0
                    for state in states_by_event[event_id]
                )
            )
    elif constraint.type == "PreferTimesConstraint":
        selected = _selected_times(
            problem,
            constraint.preferred_time_ids,
            constraint.preferred_time_group_ids,
        )
        for event_id in sorted(applied_events):
            event = problem.event_by_id[event_id]
            if event.preassigned_time_id is not None:
                continue
            groups.append(
                tuple(
                    state.meet.duration
                    if (
                        state.effective_time_id is not None
                        and state.effective_time_id not in selected
                        and (
                            constraint.duration is None
                            or constraint.duration == state.meet.duration
                        )
                    )
                    else 0
                    for state in states_by_event[event_id]
                )
            )
    elif constraint.type == "AvoidSplitAssignmentsConstraint":
        assert constraint.role is not None
        for event_group_id in constraint.applies_event_group_ids:
            assigned = {
                state.role_assignments[constraint.role]
                for event_id in problem.events_by_group[event_group_id]
                for state in states_by_event[event_id]
                if constraint.role in state.role_assignments
            }
            groups.append((max(0, len(assigned) - 1),))
    elif constraint.type == "SpreadEventsConstraint":
        for event_group_id in constraint.applies_event_group_ids:
            deviations: list[int] = []
            event_ids = problem.events_by_group[event_group_id]
            for limit in constraint.time_group_limits:
                selected = problem.times_by_group[limit.time_group_id]
                amount = sum(
                    state.effective_time_id in selected
                    for event_id in event_ids
                    for state in states_by_event[event_id]
                    if state.effective_time_id is not None
                )
                deviations.append(
                    _distance_to_interval(amount, limit.minimum, limit.maximum)
                )
            groups.append(tuple(deviations))
    elif constraint.type == "LinkEventsConstraint":
        for event_group_id in constraint.applies_event_group_ids:
            event_ids = problem.events_by_group[event_group_id]
            time_sets = [
                {
                    time_id
                    for state in states_by_event[event_id]
                    for time_id in state.occupied_time_ids
                }
                for event_id in event_ids
            ]
            if not time_sets:
                groups.append((0,))
                continue
            union = set().union(*time_sets)
            intersection = set(time_sets[0])
            for item in time_sets[1:]:
                intersection.intersection_update(item)
            groups.append((len(union - intersection),))
    elif constraint.type == "OrderEventsConstraint":
        for pair in constraint.event_pairs:
            first_times = [
                problem.time_index[time_id]
                for state in states_by_event[pair.first_event_id]
                for time_id in state.occupied_time_ids
            ]
            second_times = [
                problem.time_index[time_id]
                for state in states_by_event[pair.second_event_id]
                for time_id in state.occupied_time_ids
            ]
            if not first_times or not second_times:
                groups.append((0,))
                continue
            separation = min(second_times) - max(first_times) - 1
            groups.append(
                (
                    _distance_to_interval(
                        separation,
                        pair.minimum_separation,
                        pair.maximum_separation,
                    ),
                )
            )
    elif constraint.type == "AvoidClashesConstraint":
        for resource_id in sorted(applied_resources):
            groups.append(
                tuple(
                    max(0, multiplicity.get((resource_id, time.id), 0) - 1)
                    for time in problem.times
                )
            )
    elif constraint.type == "AvoidUnavailableTimesConstraint":
        selected = _selected_times(
            problem,
            constraint.preferred_time_ids,
            constraint.preferred_time_group_ids,
        )
        for resource_id in sorted(applied_resources):
            groups.append((len(busy[resource_id].intersection(selected)),))
    elif constraint.type == "LimitIdleTimesConstraint":
        assert constraint.minimum is not None
        assert constraint.maximum is not None
        for resource_id in sorted(applied_resources):
            idle_total = 0
            resource_busy = busy[resource_id]
            for group_id in constraint.time_group_ids:
                indices = sorted(
                    problem.time_index[time_id]
                    for time_id in problem.times_by_group[group_id]
                )
                occupied_positions = [
                    position
                    for position, time_index in enumerate(indices)
                    if problem.times[time_index].id in resource_busy
                ]
                if occupied_positions:
                    first = min(occupied_positions)
                    last = max(occupied_positions)
                    idle_total += sum(
                        problem.times[indices[position]].id not in resource_busy
                        for position in range(first + 1, last)
                    )
            groups.append(
                (
                    _distance_to_interval(
                        idle_total, constraint.minimum, constraint.maximum
                    ),
                )
            )
    elif constraint.type == "ClusterBusyTimesConstraint":
        assert constraint.minimum is not None
        assert constraint.maximum is not None
        for resource_id in sorted(applied_resources):
            used = sum(
                bool(busy[resource_id].intersection(problem.times_by_group[group_id]))
                for group_id in constraint.time_group_ids
            )
            groups.append(
                (
                    _distance_to_interval(
                        used, constraint.minimum, constraint.maximum
                    ),
                )
            )
    elif constraint.type == "LimitBusyTimesConstraint":
        assert constraint.minimum is not None
        assert constraint.maximum is not None
        for resource_id in sorted(applied_resources):
            deviations: list[int] = []
            for group_id in constraint.time_group_ids:
                amount = len(
                    busy[resource_id].intersection(problem.times_by_group[group_id])
                )
                deviations.append(
                    0
                    if amount == 0
                    else _distance_to_interval(
                        amount, constraint.minimum, constraint.maximum
                    )
                )
            groups.append(tuple(deviations))
    elif constraint.type == "LimitWorkloadConstraint":
        assert constraint.minimum is not None
        assert constraint.maximum is not None
        for resource_id in sorted(applied_resources):
            groups.append(
                (
                    _distance_to_interval(
                        workload.get(resource_id, 0),
                        constraint.minimum,
                        constraint.maximum,
                    ),
                )
            )
    return tuple(groups)


def _cost_from_deviation_groups(
    cost_function: str,
    weight: int,
    groups: Sequence[Sequence[int]],
) -> int:
    if cost_function in {"Linear", "Sum"}:
        raw = sum(value for group in groups for value in group)
    elif cost_function in {"Quadratic", "SumSquares"}:
        raw = sum(value * value for group in groups for value in group)
    elif cost_function in {"Step", "SumSteps"}:
        raw = sum(value > 0 for group in groups for value in group)
    elif cost_function == "StepSum":
        raw = sum(any(value > 0 for value in group) for group in groups)
    elif cost_function == "SquareSum":
        raw = sum(sum(group) ** 2 for group in groups)
    else:  # The strict parser prevents this branch.
        raise ValueError(f"Unsupported XHSTT cost function {cost_function!r}")
    return int(weight * raw)


def validate_xhstt_solution(
    problem: XHSTTProblem,
    solution: XHSTTSolution,
) -> XHSTTValidation:
    """Independently validate structure and calculate the official lexicographic cost."""

    states_by_event, errors = _normalize_solution(problem, solution)
    busy, multiplicity, workload = _resource_views(problem, states_by_event)
    costs: list[XHSTTConstraintCost] = []
    hard_cost = 0
    soft_cost = 0
    for constraint in problem.constraints:
        groups = _constraint_deviation_groups(
            problem,
            constraint,
            states_by_event,
            busy,
            multiplicity,
            workload,
        )
        cost = _cost_from_deviation_groups(
            constraint.cost_function, constraint.weight, groups
        )
        flat = tuple(value for group in groups for value in group)
        costs.append(
            XHSTTConstraintCost(
                constraint_id=constraint.id,
                constraint_type=constraint.type,
                required=constraint.required,
                deviations=flat,
                cost=cost,
            )
        )
        if constraint.required:
            hard_cost += cost
        else:
            soft_cost += cost
    return XHSTTValidation(
        score=XHSTTScore(
            hard_cost=int(hard_cost),
            soft_cost=int(soft_cost),
            constraint_costs=tuple(costs),
        ),
        errors=errors,
        unsupported_features=problem.unsupported_features,
    )


def _constraint_partition_cost(
    problem: XHSTTProblem,
    event: XHSTTEvent,
    durations: tuple[int, ...],
) -> tuple[int, int]:
    hard = 0
    soft = 0
    for constraint in problem.constraints:
        if constraint.type not in {
            "SplitEventsConstraint",
            "DistributeSplitEventsConstraint",
        } or event.id not in _applied_events(problem, constraint):
            continue
        if constraint.type == "SplitEventsConstraint":
            assert constraint.minimum_amount is not None
            assert constraint.maximum_amount is not None
            assert constraint.minimum_duration is not None
            assert constraint.maximum_duration is not None
            deviations = [
                _distance_to_interval(
                    len(durations),
                    constraint.minimum_amount,
                    constraint.maximum_amount,
                )
            ]
            deviations.extend(
                _distance_to_interval(
                    duration,
                    constraint.minimum_duration,
                    constraint.maximum_duration,
                )
                for duration in durations
            )
        else:
            assert constraint.duration is not None
            assert constraint.minimum is not None
            assert constraint.maximum is not None
            amount = sum(duration == constraint.duration for duration in durations)
            deviations = [
                _distance_to_interval(
                    amount,
                    constraint.minimum,
                    constraint.maximum,
                )
            ]
        groups = (tuple(deviations),)
        cost = _cost_from_deviation_groups(
            constraint.cost_function, constraint.weight, groups
        )
        if constraint.required:
            hard += cost
        else:
            soft += cost
    return hard, soft


def _candidate_partitions(event: XHSTTEvent) -> tuple[tuple[int, ...], ...]:
    duration = event.duration
    candidates: set[tuple[int, ...]] = {(duration,)}
    if duration <= 512:
        candidates.add(tuple(1 for _ in range(duration)))
    for amount in range(1, min(duration, 32) + 1):
        quotient, remainder = divmod(duration, amount)
        if quotient <= 0:
            continue
        candidate = tuple(
            sorted(
                (quotient + 1 for _ in range(remainder)),
                reverse=True,
            )
        ) + tuple(quotient for _ in range(amount - remainder))
        candidates.add(tuple(sorted(candidate)))
    return tuple(sorted(candidates, key=lambda item: (len(item), item)))


def _choose_partitions(
    problem: XHSTTProblem,
    deadline: float,
) -> tuple[dict[str, tuple[int, ...]], bool]:
    output: dict[str, tuple[int, ...]] = {}
    complete = True
    for index, event in enumerate(problem.events):
        if index % 16 == 0 and time.perf_counter() >= deadline:
            complete = False
            break
        candidates = _candidate_partitions(event)
        output[event.id] = min(
            candidates,
            key=lambda candidate: (
                _constraint_partition_cost(problem, event, candidate),
                len(candidate),
                candidate,
            ),
        )
    for event in problem.events:
        output.setdefault(event.id, (event.duration,))
    return output, complete


def _unassigned_solution(
    problem: XHSTTProblem,
    partitions: Mapping[str, Sequence[int]] | None = None,
    assignments_by_event: Mapping[
        str, Sequence[XHSTTResourceAssignment]
    ] | None = None,
) -> XHSTTSolution:
    rows: list[XHSTTMeet] = []
    for event in problem.events:
        durations = (
            tuple(partitions[event.id])
            if partitions is not None
            else (event.duration,)
        )
        rows.extend(
            XHSTTMeet(
                event_id=event.id,
                duration=duration,
                time_id=event.preassigned_time_id,
                resource_assignments=(
                    tuple(assignments_by_event[event.id])
                    if assignments_by_event is not None
                    else ()
                ),
            )
            for duration in durations
        )
    return XHSTTSolution(instance_id=problem.id, meets=tuple(rows))


def _default_resource_assignments(
    problem: XHSTTProblem,
    event: XHSTTEvent,
) -> tuple[XHSTTResourceAssignment, ...]:
    output: list[XHSTTResourceAssignment] = []
    for requirement in event.resources:
        if requirement.resource_id is not None or requirement.role is None:
            continue
        candidates = _eligible_resources_for_requirement(
            problem, event, requirement
        )
        if candidates:
            output.append(
                XHSTTResourceAssignment(requirement.role, min(candidates))
            )
    return tuple(output)


def _eligible_resources_for_requirement(
    problem: XHSTTProblem,
    event: XHSTTEvent,
    requirement: XHSTTEventResource,
) -> set[str]:
    candidates = {
        resource.id
        for resource in problem.resources
        if resource.resource_type_id == requirement.resource_type_id
    }
    for constraint in problem.constraints:
        if (
            constraint.type == "PreferResourcesConstraint"
            and constraint.required
            and constraint.role == requirement.role
            and event.id in _applied_events(problem, constraint)
        ):
            candidates.intersection_update(
                _selected_resources(
                    problem,
                    constraint.preferred_resource_ids,
                    constraint.preferred_resource_group_ids,
                )
            )
    return candidates


def _balanced_resource_assignments(
    problem: XHSTTProblem,
    *,
    deadline: float,
    seed: int,
) -> tuple[dict[str, tuple[XHSTTResourceAssignment, ...]], bool, dict[str, int]]:
    """Balance variable roles, preserving every required resource preference."""

    empty_fallback = {event.id: () for event in problem.events}
    resources_by_type: dict[str, set[str]] = defaultdict(set)
    for resource in problem.resources:
        resources_by_type[resource.resource_type_id].add(resource.id)
    required_preferences: list[tuple[str, frozenset[str], frozenset[str]]] = []
    for constraint_index, constraint in enumerate(problem.constraints):
        if constraint_index % 16 == 0 and time.perf_counter() >= deadline:
            return empty_fallback, False, {"assignment_unit_count": 0}
        if (
            constraint.required
            and constraint.type == "PreferResourcesConstraint"
            and constraint.role is not None
        ):
            required_preferences.append(
                (
                    constraint.role,
                    _applied_events(problem, constraint),
                    _selected_resources(
                        problem,
                        constraint.preferred_resource_ids,
                        constraint.preferred_resource_group_ids,
                    ),
                )
            )

    node_requirement: dict[tuple[str, str], XHSTTEventResource] = {}
    candidates_by_node: dict[tuple[str, str], set[str]] = {}
    for event_index, event in enumerate(problem.events):
        if event_index % 32 == 0 and time.perf_counter() >= deadline:
            return empty_fallback, False, {"assignment_unit_count": 0}
        for requirement in event.resources:
            if requirement.resource_id is not None or requirement.role is None:
                continue
            node = event.id, requirement.role
            node_requirement[node] = requirement
            candidates = set(resources_by_type[requirement.resource_type_id or ""])
            for role, applied_events, selected_resources in required_preferences:
                if role == requirement.role and event.id in applied_events:
                    candidates.intersection_update(selected_resources)
            candidates_by_node[node] = candidates
    if not node_requirement:
        return {event.id: () for event in problem.events}, True, {
            "assignment_unit_count": 0,
            "assigned_role_count": 0,
            "maximum_assigned_load": 0,
        }

    parent = {node: node for node in node_requirement}

    def find(node: tuple[str, str]) -> tuple[str, str]:
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != node:
            next_node = parent[node]
            parent[node] = root
            node = next_node
        return root

    def union(left: tuple[str, str], right: tuple[str, str]) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for constraint_index, constraint in enumerate(problem.constraints):
        if constraint_index % 16 == 0 and time.perf_counter() >= deadline:
            return empty_fallback, False, {"assignment_unit_count": 0}
        if (
            not constraint.required
            or constraint.type != "AvoidSplitAssignmentsConstraint"
            or constraint.role is None
        ):
            continue
        for event_group_id in constraint.applies_event_group_ids:
            nodes = sorted(
                (event_id, constraint.role)
                for event_id in problem.events_by_group[event_group_id]
                if (event_id, constraint.role) in node_requirement
            )
            for node in nodes[1:]:
                union(nodes[0], node)

    nodes_by_unit: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for node in node_requirement:
        nodes_by_unit[find(node)].append(node)

    hard_unavailable_count: dict[str, int] = defaultdict(int)
    workload_minimum: dict[str, int] = {}
    workload_maximum: dict[str, int] = {}
    for constraint_index, constraint in enumerate(problem.constraints):
        if constraint_index % 16 == 0 and time.perf_counter() >= deadline:
            return empty_fallback, False, {
                "assignment_unit_count": len(nodes_by_unit)
            }
        if not constraint.required:
            continue
        if constraint.type == "AvoidUnavailableTimesConstraint":
            unavailable = _selected_times(
                problem,
                constraint.preferred_time_ids,
                constraint.preferred_time_group_ids,
            )
            for resource_id in _applied_resources(problem, constraint):
                hard_unavailable_count[resource_id] += len(unavailable)
        elif constraint.type == "LimitWorkloadConstraint":
            assert constraint.minimum is not None
            assert constraint.maximum is not None
            for resource_id in _applied_resources(problem, constraint):
                workload_minimum[resource_id] = max(
                    workload_minimum.get(resource_id, constraint.minimum),
                    constraint.minimum,
                )
                workload_maximum[resource_id] = min(
                    workload_maximum.get(resource_id, constraint.maximum),
                    constraint.maximum,
                )

    assigned_load: dict[str, int] = defaultdict(int)
    assigned_workload: dict[str, int] = defaultdict(int)
    selected_by_event: dict[str, set[str]] = defaultdict(set)
    for event in problem.events:
        fixed_resources = {
            requirement.resource_id
            for requirement in event.resources
            if requirement.resource_id is not None
        }
        for resource_id in fixed_resources:
            assigned_load[resource_id] += event.duration
        for requirement in event.resources:
            if requirement.resource_id is not None:
                assigned_workload[requirement.resource_id] += (
                    event.duration
                    if requirement.workload is None
                    else requirement.workload
                )
    fixed_load = dict(assigned_load)
    fixed_workload = dict(assigned_workload)

    unit_rows: list[
        tuple[
            tuple[str, str],
            list[tuple[str, str]],
            set[str],
            int,
            int,
        ]
    ] = []
    for root, nodes in nodes_by_unit.items():
        candidates: set[str] | None = None
        load = 0
        workload = 0
        for event_id, role in nodes:
            node = event_id, role
            event = problem.event_by_id[event_id]
            requirement = node_requirement[node]
            node_candidates = candidates_by_node[node]
            candidates = (
                set(node_candidates)
                if candidates is None
                else candidates.intersection(node_candidates)
            )
            load += event.duration
            workload += (
                event.duration
                if requirement.workload is None
                else requirement.workload
            )
        unit_rows.append((root, nodes, candidates or set(), load, workload))
    unit_rows.sort(
        key=lambda item: (len(item[2]), -item[3], -len(item[1]), item[0])
    )

    rng = random.Random(int(seed) ^ 0x58485354)
    tie_breaker = {
        resource.id: rng.random()
        for resource in sorted(problem.resources, key=lambda x: x.id)
    }
    assignment_by_node: dict[tuple[str, str], str] = {}
    chosen_by_unit: list[str | None] = []
    missing_unit_count = 0
    horizon = len(problem.times)
    for unit_index, (_, nodes, candidates, load, workload) in enumerate(unit_rows):
        if unit_index % 16 == 0 and time.perf_counter() >= deadline:
            return empty_fallback, False, {
                "assignment_unit_count": len(unit_rows)
            }
        if not candidates:
            missing_unit_count += 1
            chosen_by_unit.append(None)
            continue

        event_ids = {event_id for event_id, _ in nodes}

        def rank(resource_id: str) -> tuple[int, int, int, int, int, float, str]:
            projected_load = assigned_load[resource_id] + load
            projected_workload = assigned_workload[resource_id] + workload
            maximum_workload = workload_maximum.get(resource_id)
            return (
                max(0, projected_load - horizon),
                (
                    0
                    if maximum_workload is None
                    else max(0, projected_workload - maximum_workload)
                ),
                hard_unavailable_count[resource_id],
                sum(resource_id in selected_by_event[event_id] for event_id in event_ids),
                projected_load,
                tie_breaker[resource_id],
                resource_id,
            )

        chosen = min(candidates, key=rank)
        chosen_by_unit.append(chosen)
        assigned_load[chosen] += load
        assigned_workload[chosen] += workload
        for node in nodes:
            selected_by_event[node[0]].add(chosen)

    def capacity_violation(
        resource_id: str,
        load: int,
        workload: int,
    ) -> int:
        return max(0, load - horizon) + max(
            0,
            workload - workload_maximum.get(resource_id, workload),
        )

    resource_event_count: dict[tuple[str, str], int] = defaultdict(int)
    for unit_index, (_, nodes, _, _, _) in enumerate(unit_rows):
        chosen = chosen_by_unit[unit_index]
        if chosen is None:
            continue
        for event_id in {event_id for event_id, _ in nodes}:
            resource_event_count[chosen, event_id] += 1

    repair_moves = 0
    repair_expired = False
    for _ in range(len(unit_rows)):
        if time.perf_counter() >= deadline:
            repair_expired = True
            break
        overloaded = {
            resource_id
            for resource_id in assigned_load
            if capacity_violation(
                resource_id,
                assigned_load[resource_id],
                assigned_workload[resource_id],
            )
            > 0
        }
        if not overloaded:
            break
        moves: list[
            tuple[int, int, int, float, str, int, str]
        ] = []
        for unit_index, (_, nodes, candidates, load, workload) in enumerate(
            unit_rows
        ):
            if unit_index % 32 == 0 and time.perf_counter() >= deadline:
                repair_expired = True
                break
            current = chosen_by_unit[unit_index]
            if current is None or current not in overloaded:
                continue
            event_ids = {event_id for event_id, _ in nodes}
            current_before = capacity_violation(
                current,
                assigned_load[current],
                assigned_workload[current],
            )
            current_after = capacity_violation(
                current,
                assigned_load[current] - load,
                assigned_workload[current] - workload,
            )
            for alternative in sorted(candidates.difference({current})):
                if any(
                    resource_event_count[alternative, event_id] > 0
                    for event_id in event_ids
                ):
                    continue
                alternative_before = capacity_violation(
                    alternative,
                    assigned_load[alternative],
                    assigned_workload[alternative],
                )
                alternative_after = capacity_violation(
                    alternative,
                    assigned_load[alternative] + load,
                    assigned_workload[alternative] + workload,
                )
                improvement = (
                    current_before
                    + alternative_before
                    - current_after
                    - alternative_after
                )
                if improvement <= 0:
                    continue
                moves.append(
                    (
                        -improvement,
                        alternative_after,
                        hard_unavailable_count[alternative],
                        tie_breaker[alternative],
                        alternative,
                        unit_index,
                        current,
                    )
                )
        if repair_expired:
            break
        if moves:
            _, _, _, _, alternative, unit_index, current = min(moves)
            _, _, _, load, workload = unit_rows[unit_index]
            assigned_load[current] -= load
            assigned_workload[current] -= workload
            assigned_load[alternative] += load
            assigned_workload[alternative] += workload
            event_ids = {event_id for event_id, _ in unit_rows[unit_index][1]}
            for event_id in event_ids:
                resource_event_count[current, event_id] -= 1
                resource_event_count[alternative, event_id] += 1
            chosen_by_unit[unit_index] = alternative
            repair_moves += 1
            continue

        swaps: list[tuple[int, int, float, int, int, str, str]] = []
        for left_index, (_, left_nodes, left_candidates, left_load, left_workload) in enumerate(
            unit_rows
        ):
            if left_index % 32 == 0 and time.perf_counter() >= deadline:
                repair_expired = True
                break
            left_resource = chosen_by_unit[left_index]
            if left_resource is None or left_resource not in overloaded:
                continue
            left_events = {event_id for event_id, _ in left_nodes}
            for right_index, (
                _,
                right_nodes,
                right_candidates,
                right_load,
                right_workload,
            ) in enumerate(unit_rows):
                right_resource = chosen_by_unit[right_index]
                if (
                    right_resource is None
                    or right_resource == left_resource
                    or right_resource not in left_candidates
                    or left_resource not in right_candidates
                ):
                    continue
                right_events = {event_id for event_id, _ in right_nodes}
                if any(
                    resource_event_count[right_resource, event_id]
                    - int(event_id in right_events)
                    > 0
                    for event_id in left_events
                ) or any(
                    resource_event_count[left_resource, event_id]
                    - int(event_id in left_events)
                    > 0
                    for event_id in right_events
                ):
                    continue
                before = capacity_violation(
                    left_resource,
                    assigned_load[left_resource],
                    assigned_workload[left_resource],
                ) + capacity_violation(
                    right_resource,
                    assigned_load[right_resource],
                    assigned_workload[right_resource],
                )
                after = capacity_violation(
                    left_resource,
                    assigned_load[left_resource] - left_load + right_load,
                    assigned_workload[left_resource]
                    - left_workload
                    + right_workload,
                ) + capacity_violation(
                    right_resource,
                    assigned_load[right_resource] - right_load + left_load,
                    assigned_workload[right_resource]
                    - right_workload
                    + left_workload,
                )
                if after >= before:
                    continue
                swaps.append(
                    (
                        after - before,
                        after,
                        tie_breaker[right_resource],
                        left_index,
                        right_index,
                        left_resource,
                        right_resource,
                    )
                )
        if repair_expired or not swaps:
            break
        (
            _,
            _,
            _,
            left_index,
            right_index,
            left_resource,
            right_resource,
        ) = min(swaps)
        _, left_nodes, _, left_load, left_workload = unit_rows[left_index]
        _, right_nodes, _, right_load, right_workload = unit_rows[right_index]
        assigned_load[left_resource] += right_load - left_load
        assigned_workload[left_resource] += right_workload - left_workload
        assigned_load[right_resource] += left_load - right_load
        assigned_workload[right_resource] += left_workload - right_workload
        for event_id in {event_id for event_id, _ in left_nodes}:
            resource_event_count[left_resource, event_id] -= 1
            resource_event_count[right_resource, event_id] += 1
        for event_id in {event_id for event_id, _ in right_nodes}:
            resource_event_count[right_resource, event_id] -= 1
            resource_event_count[left_resource, event_id] += 1
        chosen_by_unit[left_index] = right_resource
        chosen_by_unit[right_index] = left_resource
        repair_moves += 1

    remaining_capacity_violation = sum(
        capacity_violation(
            resource_id,
            assigned_load[resource_id],
            assigned_workload[resource_id],
        )
        for resource_id in assigned_load
    ) + sum(
        max(0, minimum - assigned_workload[resource_id])
        for resource_id, minimum in workload_minimum.items()
    )
    exact_assignment_status = "not_needed"
    exact_assignment_variables = sum(len(row[2]) for row in unit_rows)
    exact_assignment_seconds = 0.0
    if (
        remaining_capacity_violation > 0
        and missing_unit_count == 0
        and not repair_expired
        and exact_assignment_variables <= 20_000
        and time.perf_counter() + _MIN_CP_SEARCH_SECONDS < deadline
    ):
        exact_started = time.perf_counter()
        assignment_model = cp_model.CpModel()
        assignment_variables: dict[tuple[int, str], cp_model.IntVar] = {}
        clash_resources: set[str] = set()
        for constraint in problem.constraints:
            if constraint.required and constraint.type == "AvoidClashesConstraint":
                clash_resources.update(_applied_resources(problem, constraint))

        def exact_candidate_order(resource_id: str) -> tuple[int, str]:
            if resource_id in workload_maximum:
                slack = (
                    workload_maximum[resource_id]
                    - fixed_workload.get(resource_id, 0)
                )
            else:
                slack = 1_000_000_000
            return -slack, resource_id

        event_position = {
            event.id: index for index, event in enumerate(problem.events)
        }
        exact_unit_indices = sorted(
            range(len(unit_rows)),
            key=lambda unit_index: min(
                event_position[event_id]
                for event_id, _ in unit_rows[unit_index][1]
            ),
        )
        for unit_index in exact_unit_indices:
            _, _, candidates, _, _ = unit_rows[unit_index]
            ordered_candidates = sorted(candidates, key=exact_candidate_order)
            for resource_id in ordered_candidates:
                assignment_variables[unit_index, resource_id] = (
                    assignment_model.new_bool_var(
                        f"resource_assignment_{unit_index}_{resource_id}"
                    )
                )
            row = [
                assignment_variables[unit_index, resource_id]
                for resource_id in ordered_candidates
            ]
            if row:
                assignment_model.add(sum(row) == 1)

        for resource_id in sorted(clash_resources):
            terms = [
                load * assignment_variables[unit_index, resource_id]
                for unit_index, (_, _, _, load, _) in enumerate(unit_rows)
                if (unit_index, resource_id) in assignment_variables
            ]
            assignment_model.add(
                fixed_load.get(resource_id, 0) + sum(terms) <= horizon
            )
        workload_resources = set(workload_minimum).union(workload_maximum)
        for resource_id in sorted(workload_resources):
            terms = [
                workload * assignment_variables[unit_index, resource_id]
                for unit_index, (_, _, _, _, workload) in enumerate(unit_rows)
                if (unit_index, resource_id) in assignment_variables
            ]
            expression = fixed_workload.get(resource_id, 0) + sum(terms)
            if workload_minimum.get(resource_id, 0) > 0:
                assignment_model.add(
                    expression >= workload_minimum[resource_id]
                )
            if resource_id in workload_maximum:
                assignment_model.add(
                    expression <= workload_maximum[resource_id]
                )
        assignment_solver = cp_model.CpSolver()
        assignment_solver.parameters.max_time_in_seconds = min(
            1.5,
            max(0.0, deadline - exact_started),
        )
        # This is a feasibility repair rather than a diversification lane.  A
        # fixed sub-seed keeps its bounded search stable while the outer seed
        # still controls the constructive incumbent and time search.
        assignment_solver.parameters.random_seed = 0
        assignment_solver.parameters.num_search_workers = 1
        exact_raw_status = int(assignment_solver.solve(assignment_model))
        exact_completed = time.perf_counter()
        exact_assignment_seconds = exact_completed - exact_started
        if (
            exact_raw_status in {int(cp_model.OPTIMAL), int(cp_model.FEASIBLE)}
            and exact_completed <= deadline
        ):
            chosen_by_unit = [
                next(
                    resource_id
                    for resource_id in sorted(candidates)
                    if assignment_solver.value(
                        assignment_variables[unit_index, resource_id]
                    )
                )
                for unit_index, (_, _, candidates, _, _) in enumerate(unit_rows)
            ]
            assigned_load = defaultdict(int, fixed_load)
            assigned_workload = defaultdict(int, fixed_workload)
            for unit_index, (_, _, _, load, workload) in enumerate(unit_rows):
                chosen = chosen_by_unit[unit_index]
                assert chosen is not None
                assigned_load[chosen] += load
                assigned_workload[chosen] += workload
            exact_assignment_status = "validated_feasible"
        elif exact_completed > deadline:
            exact_assignment_status = "late_rejected"
            repair_expired = True
        elif exact_raw_status == int(cp_model.INFEASIBLE):
            exact_assignment_status = "infeasible"
        else:
            exact_assignment_status = "search_exhausted"

    for unit_index, (_, nodes, _, _, _) in enumerate(unit_rows):
        chosen = chosen_by_unit[unit_index]
        if chosen is None:
            continue
        for node in nodes:
            assignment_by_node[node] = chosen

    output: dict[str, tuple[XHSTTResourceAssignment, ...]] = {}
    for event in problem.events:
        output[event.id] = tuple(
            XHSTTResourceAssignment(role, assignment_by_node[event.id, role])
            for role in sorted(
                {
                    requirement.role
                    for requirement in event.resources
                    if requirement.resource_id is None
                    and requirement.role is not None
                    and (event.id, requirement.role) in assignment_by_node
                }
            )
        )
    return output, missing_unit_count == 0 and not repair_expired, {
        "assignment_unit_count": len(unit_rows),
        "assigned_role_count": len(assignment_by_node),
        "missing_assignment_unit_count": missing_unit_count,
        "capacity_repair_move_count": repair_moves,
        "capacity_repair_complete": not repair_expired,
        "remaining_capacity_violation": sum(
            capacity_violation(
                resource_id,
                assigned_load[resource_id],
                assigned_workload[resource_id],
            )
            for resource_id in assigned_load
        )
        + sum(
            max(0, minimum - assigned_workload[resource_id])
            for resource_id, minimum in workload_minimum.items()
        ),
        "exact_assignment_status": exact_assignment_status,
        "exact_assignment_variable_count": exact_assignment_variables,
        "exact_assignment_seconds": exact_assignment_seconds,
        "maximum_assigned_load": max(assigned_load.values(), default=0),
    }


def _attending_resources(
    problem: XHSTTProblem,
    event: XHSTTEvent,
    assignments: Sequence[XHSTTResourceAssignment],
) -> frozenset[str]:
    attending = {
        item.resource_id
        for item in event.resources
        if item.resource_id is not None
    }
    attending.update(item.resource_id for item in assignments)
    for group_id in event.resource_group_ids:
        attending.update(problem.resources_by_group[group_id])
    return frozenset(attending)


def _allowed_start_indices(
    problem: XHSTTProblem,
    event: XHSTTEvent,
    duration: int,
    assignments: Sequence[XHSTTResourceAssignment],
) -> frozenset[int]:
    allowed = set(range(0, len(problem.times) - duration + 1))
    if event.preassigned_time_id is not None:
        allowed.intersection_update({problem.time_index[event.preassigned_time_id]})
    for constraint in problem.constraints:
        if not constraint.required:
            continue
        if (
            constraint.type == "PreferTimesConstraint"
            and event.id in _applied_events(problem, constraint)
            and event.preassigned_time_id is None
            and (constraint.duration is None or constraint.duration == duration)
        ):
            selected = _selected_times(
                problem,
                constraint.preferred_time_ids,
                constraint.preferred_time_group_ids,
            )
            allowed.intersection_update(
                problem.time_index[time_id] for time_id in selected
            )

    attending = _attending_resources(problem, event, assignments)
    for constraint in problem.constraints:
        if (
            not constraint.required
            or constraint.type != "AvoidUnavailableTimesConstraint"
            or not attending.intersection(_applied_resources(problem, constraint))
        ):
            continue
        unavailable = _selected_times(
            problem,
            constraint.preferred_time_ids,
            constraint.preferred_time_group_ids,
        )
        allowed = {
            start
            for start in allowed
            if all(
                problem.times[index].id not in unavailable
                for index in range(start, start + duration)
            )
        }
    return frozenset(allowed)


@dataclass(frozen=True)
class _IncidenceColoringAttempt:
    solution: XHSTTSolution | None
    validation: XHSTTValidation | None
    raw_status: int
    build_finished: float
    search_finished: float
    completed: float
    reason: str
    variable_count: int
    unit_meet_count: int


@dataclass(frozen=True)
class _MatchingDecompositionAttempt:
    solution: XHSTTSolution | None
    validation: XHSTTValidation | None
    started: float
    completed: float
    reason: str
    attempt_count: int
    search_nodes: int
    unit_meet_count: int


def _add_cp_deviation_cost(
    model: cp_model.CpModel,
    constraint: XHSTTConstraint,
    groups: Sequence[Sequence[tuple[cp_model.IntVar, int]]],
    *,
    prefix: str,
) -> list[cp_model.LinearExpr]:
    """Encode one independently-scored XHSTT deviation family exactly."""

    if constraint.weight <= 0:
        return []
    terms: list[cp_model.LinearExpr] = []

    def positive_flag(
        variable: cp_model.IntVar,
        *,
        name: str,
    ) -> cp_model.IntVar:
        flag = model.new_bool_var(name)
        model.add(variable >= 1).only_enforce_if(flag)
        model.add(variable == 0).only_enforce_if(flag.Not())
        return flag

    for group_index, group in enumerate(groups):
        bounded = [item for item in group if item[1] > 0]
        if not bounded:
            continue
        if constraint.cost_function in {"Linear", "Sum"}:
            terms.extend(constraint.weight * variable for variable, _ in bounded)
        elif constraint.cost_function in {"Quadratic", "SumSquares"}:
            for deviation_index, (variable, upper_bound) in enumerate(bounded):
                square = model.new_int_var(
                    0,
                    upper_bound * upper_bound,
                    f"{prefix}_square_{group_index}_{deviation_index}",
                )
                model.add_multiplication_equality(square, [variable, variable])
                terms.append(constraint.weight * square)
        elif constraint.cost_function in {"Step", "SumSteps"}:
            for deviation_index, (variable, _) in enumerate(bounded):
                terms.append(
                    constraint.weight
                    * positive_flag(
                        variable,
                        name=f"{prefix}_step_{group_index}_{deviation_index}",
                    )
                )
        elif constraint.cost_function == "StepSum":
            total_upper_bound = sum(upper_bound for _, upper_bound in bounded)
            total = model.new_int_var(
                0,
                total_upper_bound,
                f"{prefix}_total_{group_index}",
            )
            model.add(total == sum(variable for variable, _ in bounded))
            terms.append(
                constraint.weight
                * positive_flag(total, name=f"{prefix}_step_sum_{group_index}")
            )
        elif constraint.cost_function == "SquareSum":
            total_upper_bound = sum(upper_bound for _, upper_bound in bounded)
            total = model.new_int_var(
                0,
                total_upper_bound,
                f"{prefix}_total_{group_index}",
            )
            square = model.new_int_var(
                0,
                total_upper_bound * total_upper_bound,
                f"{prefix}_square_sum_{group_index}",
            )
            model.add(total == sum(variable for variable, _ in bounded))
            model.add_multiplication_equality(square, [total, total])
            terms.append(constraint.weight * square)
        else:  # The strict parser prevents this branch.
            raise ValueError(
                f"Unsupported XHSTT cost function {constraint.cost_function!r}"
            )
    return terms


def _try_matching_decomposition(
    problem: XHSTTProblem,
    *,
    deadline: float,
    search_cap_seconds: float,
    seed: int,
    max_cp_meets: int,
    assignments_by_event: Mapping[
        str, Sequence[XHSTTResourceAssignment]
    ] | None = None,
) -> _MatchingDecompositionAttempt | None:
    """Decompose a balanced multipartite event tensor into time matchings."""

    if problem.unsupported_features or not problem.times:
        return None
    unit_meet_count = sum(event.duration for event in problem.events)
    if unit_meet_count > max_cp_meets:
        return None
    if any(
        event.preassigned_time_id is not None and event.duration != 1
        for event in problem.events
    ):
        return None
    for event in problem.events:
        unit_partition = tuple(1 for _ in range(event.duration))
        hard_partition_cost, _ = _constraint_partition_cost(
            problem, event, unit_partition
        )
        if hard_partition_cost:
            return None

    if assignments_by_event is None:
        assignments_by_event = {
            event.id: _default_resource_assignments(problem, event)
            for event in problem.events
        }
    clash_resources: set[str] = set()
    for constraint in problem.constraints:
        if constraint.required and constraint.type == "AvoidClashesConstraint":
            clash_resources.update(_applied_resources(problem, constraint))
    if not clash_resources:
        return None
    attending_by_event = {
        event.id: _attending_resources(
            problem, event, assignments_by_event[event.id]
        ).intersection(clash_resources)
        for event in problem.events
    }
    horizon = len(problem.times)
    load: dict[str, int] = defaultdict(int)
    for event in problem.events:
        for resource_id in attending_by_event[event.id]:
            load[resource_id] += event.duration
    # The decomposition is lossless and strongest when every constrained
    # resource must occur in every color/time.  Otherwise the generic incidence
    # model handles the at-most-one rows.
    if any(load[resource_id] != horizon for resource_id in clash_resources):
        return None

    resources_by_type: dict[str, set[str]] = defaultdict(set)
    for resource_id in clash_resources:
        resources_by_type[
            problem.resource_by_id[resource_id].resource_type_id
        ].add(resource_id)
    type_sizes = {len(resources) for resources in resources_by_type.values()}
    if (
        len(resources_by_type) < 2
        or len(type_sizes) != 1
        or not type_sizes
        or min(type_sizes) < 2
        or max(type_sizes) > 12
    ):
        return None
    type_ids = tuple(
        sorted(resources_by_type, key=lambda item: (len(resources_by_type[item]), item))
    )
    expected_types = set(type_ids)
    event_resources_by_type: dict[str, dict[str, str]] = {}
    for event in problem.events:
        typed: dict[str, str] = {}
        for resource_id in sorted(attending_by_event[event.id]):
            resource_type_id = problem.resource_by_id[resource_id].resource_type_id
            if resource_type_id in typed:
                return None
            typed[resource_type_id] = resource_id
        if set(typed) != expected_types:
            return None
        event_resources_by_type[event.id] = typed

    allowed_by_event = {
        event.id: _allowed_start_indices(
            problem,
            event,
            1,
            assignments_by_event[event.id],
        )
        for event in problem.events
    }
    if any(not allowed for allowed in allowed_by_event.values()):
        return None
    anchor_type = type_ids[0]
    anchor_resources = frozenset(resources_by_type[anchor_type])
    event_indices_by_anchor: dict[str, list[int]] = defaultdict(list)
    for index, event in enumerate(problem.events):
        event_indices_by_anchor[
            event_resources_by_type[event.id][anchor_type]
        ].append(index)

    started = time.perf_counter()
    local_deadline = min(
        deadline,
        started + max(0.0, float(search_cap_seconds)),
    )
    rng = random.Random(int(seed))
    base_counts = [event.duration for event in problem.events]
    event_resource_sets = [
        attending_by_event[event.id] for event in problem.events
    ]
    attempt_count = 0
    search_nodes = 0
    solved_slots: list[list[int]] | None = None
    expired = False
    while time.perf_counter() < local_deadline:
        attempt_count += 1
        counts = list(base_counts)
        slots: list[list[int]] = []
        attempt_succeeded = True
        for time_index in range(horizon):
            chosen: list[int] = []
            used: set[str] = set()

            def fill(free_anchors: frozenset[str]) -> bool:
                nonlocal expired, search_nodes
                search_nodes += 1
                if search_nodes % 256 == 0 and time.perf_counter() >= local_deadline:
                    expired = True
                    return False
                if not free_anchors:
                    return used == clash_resources
                choices: list[tuple[int, float, str, list[int]]] = []
                for anchor in sorted(free_anchors):
                    candidates = [
                        index
                        for index in event_indices_by_anchor[anchor]
                        if counts[index] > 0
                        and time_index
                        in allowed_by_event[problem.events[index].id]
                        and event_resource_sets[index].isdisjoint(used)
                    ]
                    if not candidates:
                        return False
                    choices.append((len(candidates), rng.random(), anchor, candidates))
                _, _, _, candidates = min(choices)
                rng.shuffle(candidates)
                candidates.sort(key=lambda index: -counts[index])
                for index in candidates:
                    resources = event_resource_sets[index]
                    chosen.append(index)
                    previous = set(used)
                    used.update(resources)
                    if fill(free_anchors.difference(resources)):
                        return True
                    used.clear()
                    used.update(previous)
                    chosen.pop()
                    if expired:
                        return False
                return False

            if not fill(anchor_resources):
                attempt_succeeded = False
                break
            for index in chosen:
                counts[index] -= 1
            slots.append(list(chosen))
        if attempt_succeeded and not any(counts):
            solved_slots = slots
            break
        if expired:
            break

    completed = time.perf_counter()
    if solved_slots is None:
        return _MatchingDecompositionAttempt(
            solution=None,
            validation=None,
            started=started,
            completed=completed,
            reason="search_exhausted",
            attempt_count=attempt_count,
            search_nodes=search_nodes,
            unit_meet_count=unit_meet_count,
        )

    rows: list[XHSTTMeet] = []
    for time_index, event_indices in enumerate(solved_slots):
        for event_index in event_indices:
            event = problem.events[event_index]
            rows.append(
                XHSTTMeet(
                    event_id=event.id,
                    duration=1,
                    time_id=problem.times[time_index].id,
                    resource_assignments=assignments_by_event[event.id],
                )
            )
    solution = XHSTTSolution(instance_id=problem.id, meets=tuple(rows))
    validation = validate_xhstt_solution(problem, solution)
    completed = time.perf_counter()
    return _MatchingDecompositionAttempt(
        solution=solution,
        validation=validation,
        started=started,
        completed=completed,
        reason="validated_feasible" if validation.feasible else "postcheck_failed",
        attempt_count=attempt_count,
        search_nodes=search_nodes,
        unit_meet_count=unit_meet_count,
    )


def _try_incidence_coloring(
    problem: XHSTTProblem,
    *,
    deadline: float,
    search_cap_seconds: float,
    seed: int,
    workers: int,
    max_cp_meets: int,
    assignments_by_event: Mapping[
        str, Sequence[XHSTTResourceAssignment]
    ] | None = None,
) -> _IncidenceColoringAttempt | None:
    """Color freely splittable unit meets without introducing copy symmetry.

    A duration-d event is represented by one bounded variable for each time,
    whose sum is d, instead of d interchangeable meet variables.  Resource-time
    incidence rows become capacity constraints.  This is exact for the lane's
    unit-meet projection and is especially strong on dense XHSTT graph/hypergraph
    coloring instances.
    """

    if problem.unsupported_features or not problem.times:
        return None
    unit_meet_count = sum(event.duration for event in problem.events)
    if unit_meet_count > max_cp_meets:
        return None
    if len(problem.events) * len(problem.times) > 200_000:
        return None
    # An instance-level time fixes the original meet.  Splitting a multi-period
    # preassignment into same-time unit meets is not a lossless transformation.
    if any(
        event.preassigned_time_id is not None and event.duration != 1
        for event in problem.events
    ):
        return None
    for event in problem.events:
        unit_partition = tuple(1 for _ in range(event.duration))
        hard_partition_cost, _ = _constraint_partition_cost(
            problem, event, unit_partition
        )
        if hard_partition_cost:
            return None

    started = time.perf_counter()
    if started >= deadline:
        return _IncidenceColoringAttempt(
            solution=None,
            validation=None,
            raw_status=int(cp_model.UNKNOWN),
            build_finished=started,
            search_finished=started,
            completed=started,
            reason="deadline_before_build",
            variable_count=0,
            unit_meet_count=unit_meet_count,
        )

    if assignments_by_event is None:
        assignments_by_event = {
            event.id: _default_resource_assignments(problem, event)
            for event in problem.events
        }
    attending_by_event = {
        event.id: _attending_resources(
            problem, event, assignments_by_event[event.id]
        )
        for event in problem.events
    }
    clash_resources: set[str] = set()
    for constraint in problem.constraints:
        if constraint.required and constraint.type == "AvoidClashesConstraint":
            clash_resources.update(_applied_resources(problem, constraint))

    model = cp_model.CpModel()
    variables: dict[tuple[str, int], cp_model.IntVar] = {}
    coverage: dict[tuple[str, int], list[cp_model.IntVar]] = defaultdict(list)
    resource_load: dict[str, int] = defaultdict(int)
    for event_index, event in enumerate(problem.events):
        if event_index % 32 == 0 and time.perf_counter() >= deadline:
            now = time.perf_counter()
            return _IncidenceColoringAttempt(
                solution=None,
                validation=None,
                raw_status=int(cp_model.UNKNOWN),
                build_finished=now,
                search_finished=now,
                completed=now,
                reason="deadline_during_build",
                variable_count=len(variables),
                unit_meet_count=unit_meet_count,
            )
        assignments = assignments_by_event[event.id]
        attending = attending_by_event[event.id]
        constrained_resources = attending.intersection(clash_resources)
        for resource_id in constrained_resources:
            resource_load[resource_id] += event.duration
        allowed = _allowed_start_indices(problem, event, 1, assignments)
        if not allowed:
            now = time.perf_counter()
            return _IncidenceColoringAttempt(
                solution=None,
                validation=None,
                raw_status=int(cp_model.INFEASIBLE),
                build_finished=now,
                search_finished=now,
                completed=now,
                reason="infeasible_unit_domain",
                variable_count=len(variables),
                unit_meet_count=unit_meet_count,
            )
        upper_bound = 1 if constrained_resources else event.duration
        event_variables: list[cp_model.IntVar] = []
        for time_index in sorted(allowed):
            variable = model.new_int_var(
                0,
                upper_bound,
                f"incidence_{event_index}_{time_index}",
            )
            variables[event.id, time_index] = variable
            event_variables.append(variable)
            for resource_id in constrained_resources:
                coverage[resource_id, time_index].append(variable)
        model.add(sum(event_variables) == event.duration)

    horizon = len(problem.times)
    for resource_index, resource_id in enumerate(sorted(clash_resources)):
        if resource_index % 32 == 0 and time.perf_counter() >= deadline:
            now = time.perf_counter()
            return _IncidenceColoringAttempt(
                solution=None,
                validation=None,
                raw_status=int(cp_model.UNKNOWN),
                build_finished=now,
                search_finished=now,
                completed=now,
                reason="deadline_during_build",
                variable_count=len(variables),
                unit_meet_count=unit_meet_count,
            )
        if resource_load[resource_id] > horizon:
            now = time.perf_counter()
            return _IncidenceColoringAttempt(
                solution=None,
                validation=None,
                raw_status=int(cp_model.INFEASIBLE),
                build_finished=now,
                search_finished=now,
                completed=now,
                reason="resource_load_exceeds_horizon",
                variable_count=len(variables),
                unit_meet_count=unit_meet_count,
            )
        for time_index in range(horizon):
            row = coverage.get((resource_id, time_index), [])
            if resource_load[resource_id] == horizon:
                model.add(sum(row) == 1)
            else:
                model.add(sum(row) <= 1)

    build_finished = time.perf_counter()
    remaining = min(
        max(0.0, deadline - build_finished),
        max(0.0, float(search_cap_seconds)),
    )
    if remaining < _MIN_CP_SEARCH_SECONDS:
        return _IncidenceColoringAttempt(
            solution=None,
            validation=None,
            raw_status=int(cp_model.UNKNOWN),
            build_finished=build_finished,
            search_finished=build_finished,
            completed=build_finished,
            reason="insufficient_search_budget",
            variable_count=len(variables),
            unit_meet_count=unit_meet_count,
        )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = remaining
    solver.parameters.random_seed = int(seed)
    solver.parameters.num_search_workers = workers
    raw_status = int(solver.solve(model))
    search_finished = time.perf_counter()
    if raw_status not in {int(cp_model.OPTIMAL), int(cp_model.FEASIBLE)}:
        return _IncidenceColoringAttempt(
            solution=None,
            validation=None,
            raw_status=raw_status,
            build_finished=build_finished,
            search_finished=search_finished,
            completed=search_finished,
            reason=(
                "encoded_infeasible"
                if raw_status == int(cp_model.INFEASIBLE)
                else "search_exhausted"
            ),
            variable_count=len(variables),
            unit_meet_count=unit_meet_count,
        )

    rows: list[XHSTTMeet] = []
    for event in problem.events:
        assignments = assignments_by_event[event.id]
        for time_index in range(horizon):
            variable = variables.get((event.id, time_index))
            count = 0 if variable is None else int(solver.value(variable))
            rows.extend(
                XHSTTMeet(
                    event_id=event.id,
                    duration=1,
                    time_id=problem.times[time_index].id,
                    resource_assignments=assignments,
                )
                for _ in range(count)
            )
    solution = XHSTTSolution(instance_id=problem.id, meets=tuple(rows))
    validation = validate_xhstt_solution(problem, solution)
    completed = time.perf_counter()
    return _IncidenceColoringAttempt(
        solution=solution,
        validation=validation,
        raw_status=raw_status,
        build_finished=build_finished,
        search_finished=search_finished,
        completed=completed,
        reason="validated_feasible" if validation.feasible else "postcheck_failed",
        variable_count=len(variables),
        unit_meet_count=unit_meet_count,
    )


def solve_xhstt(
    problem: XHSTTProblem,
    *,
    time_limit_seconds: float = 10.0,
    seed: int = 0,
    workers: int = 1,
    max_cp_meets: int = 2_000,
) -> XHSTTSolveResult:
    """Build a deadline-bounded native timetable, with exact post-validation.

    Balanced freely-splittable tensors first use matching decomposition, then a
    symmetry-reduced time-incidence model.  The general CP adapter encodes hard
    time assignment, time preferences, unavailable times, resource clashes,
    event spreading, linking, and ordering. Richer resource workload and
    workload-pattern constraints are still scored by the independent evaluator
    and therefore cannot be mistaken for feasibility.
    """

    started = time.perf_counter()
    budget = max(0.0, float(time_limit_seconds))
    deadline = started + budget
    # Leave bounded Python-side headroom for materializing and independently
    # validating the candidate after the native search returns.
    headroom = min(budget, min(0.25, max(0.05, budget * 0.05)))
    search_deadline = max(started, deadline - headroom)
    workers = max(1, int(workers))
    if budget <= 0.0:
        solution = _unassigned_solution(problem)
        validation = validate_xhstt_solution(problem, solution)
        elapsed = time.perf_counter() - started
        return XHSTTSolveResult(
            solution=solution,
            validation=validation,
            status="deadline_during_build",
            raw_status=int(cp_model.UNKNOWN),
            build_seconds=elapsed,
            search_seconds=0.0,
            elapsed_seconds=elapsed,
            deadline_overrun_seconds=max(0.0, time.perf_counter() - deadline),
            seed=int(seed),
            workers=workers,
            telemetry={"returned_source": "unassigned_fallback"},
        )

    partitions, partitions_complete = _choose_partitions(problem, search_deadline)
    fallback = _unassigned_solution(problem, partitions)
    if time.perf_counter() >= search_deadline or not partitions_complete:
        validation = validate_xhstt_solution(problem, fallback)
        elapsed = time.perf_counter() - started
        return XHSTTSolveResult(
            solution=fallback,
            validation=validation,
            status="deadline_during_build",
            raw_status=int(cp_model.UNKNOWN),
            build_seconds=elapsed,
            search_seconds=0.0,
            elapsed_seconds=elapsed,
            deadline_overrun_seconds=max(0.0, time.perf_counter() - deadline),
            seed=int(seed),
            workers=workers,
            telemetry={
                "returned_source": "unassigned_fallback",
                "partition_search_complete": partitions_complete,
            },
        )

    structural_solution: XHSTTSolution | None = None
    structural_validation: XHSTTValidation | None = None
    structural_source: str | None = None
    structural_raw_status = int(cp_model.UNKNOWN)
    assignments_by_event, assignments_complete, assignment_telemetry = (
        _balanced_resource_assignments(
            problem,
            deadline=search_deadline,
            seed=int(seed),
        )
    )
    fallback = _unassigned_solution(
        problem,
        partitions,
        assignments_by_event,
    )
    if time.perf_counter() >= search_deadline:
        validation = validate_xhstt_solution(problem, fallback)
        elapsed = time.perf_counter() - started
        return XHSTTSolveResult(
            solution=fallback,
            validation=validation,
            status="deadline_during_build",
            raw_status=int(cp_model.UNKNOWN),
            build_seconds=elapsed,
            search_seconds=0.0,
            elapsed_seconds=elapsed,
            deadline_overrun_seconds=max(0.0, time.perf_counter() - deadline),
            seed=int(seed),
            workers=workers,
            telemetry={
                "returned_source": "resource_assigned_fallback",
                "partition_search_complete": partitions_complete,
                "resource_assignment_complete": assignments_complete,
                "resource_assignment": assignment_telemetry,
            },
        )

    decomposition_attempt = _try_matching_decomposition(
        problem,
        deadline=search_deadline,
        search_cap_seconds=min(0.4, max(0.0, budget * 0.2)),
        seed=int(seed),
        max_cp_meets=max_cp_meets,
        assignments_by_event=assignments_by_event,
    )
    decomposition_telemetry: dict[str, object] = {}
    if decomposition_attempt is not None:
        decomposition_late = decomposition_attempt.completed > deadline
        decomposition_telemetry = {
            "matching_decomposition": {
                "reason": decomposition_attempt.reason,
                "attempt_count": decomposition_attempt.attempt_count,
                "search_nodes": decomposition_attempt.search_nodes,
                "unit_meet_count": decomposition_attempt.unit_meet_count,
                "search_seconds": max(
                    0.0,
                    decomposition_attempt.completed
                    - decomposition_attempt.started,
                ),
                "candidate_rejected_reason": (
                    "deadline" if decomposition_late else None
                ),
            }
        }
        if (
            decomposition_attempt.solution is not None
            and decomposition_attempt.validation is not None
            and decomposition_attempt.validation.feasible
            and not decomposition_late
        ):
            unencoded_hard = sorted(
                {
                    constraint.type
                    for constraint in problem.constraints
                    if constraint.required
                    and constraint.type
                    not in {
                        "AssignTimeConstraint",
                        "SplitEventsConstraint",
                        "DistributeSplitEventsConstraint",
                        "PreferTimesConstraint",
                        "AvoidClashesConstraint",
                        "AvoidUnavailableTimesConstraint",
                    }
                }
            )
            if decomposition_attempt.validation.score.soft_cost == 0:
                return XHSTTSolveResult(
                    solution=decomposition_attempt.solution,
                    validation=decomposition_attempt.validation,
                    status="feasible",
                    raw_status=int(cp_model.FEASIBLE),
                    build_seconds=max(
                        0.0, decomposition_attempt.started - started
                    ),
                    search_seconds=max(
                        0.0,
                        decomposition_attempt.completed
                        - decomposition_attempt.started,
                    ),
                    elapsed_seconds=max(
                        0.0, decomposition_attempt.completed - started
                    ),
                    deadline_overrun_seconds=max(
                        0.0, decomposition_attempt.completed - deadline
                    ),
                    seed=int(seed),
                    workers=workers,
                    telemetry={
                        "returned_source": "matching_decomposition",
                        "partition_mode": "aggregated_unit_meets",
                        "meet_count": decomposition_attempt.unit_meet_count,
                        "encoded_constraint_types": [
                            "AssignTimeConstraint",
                            "AvoidClashesConstraint",
                            "AvoidUnavailableTimesConstraint",
                            "DistributeSplitEventsConstraint",
                            "PreferTimesConstraint",
                            "SplitEventsConstraint",
                        ],
                        "unencoded_hard_constraint_types": unencoded_hard,
                        "unsupported_features": list(problem.unsupported_features),
                        "resource_assignment_complete": assignments_complete,
                        "resource_assignment": assignment_telemetry,
                        **decomposition_telemetry,
                    },
                )
            structural_solution = decomposition_attempt.solution
            structural_validation = decomposition_attempt.validation
            structural_source = "matching_decomposition"
            structural_raw_status = int(cp_model.FEASIBLE)

    incidence_attempt = _try_incidence_coloring(
        problem,
        deadline=search_deadline,
        search_cap_seconds=min(1.5, max(0.0, budget * 0.6)),
        seed=int(seed),
        workers=workers,
        max_cp_meets=max_cp_meets,
        assignments_by_event=assignments_by_event,
    )
    incidence_telemetry: dict[str, object] = {}
    if incidence_attempt is not None:
        incidence_late = incidence_attempt.completed > deadline
        incidence_telemetry = {
            "incidence_coloring": {
                "reason": incidence_attempt.reason,
                "raw_status": incidence_attempt.raw_status,
                "variable_count": incidence_attempt.variable_count,
                "unit_meet_count": incidence_attempt.unit_meet_count,
                "build_seconds": max(
                    0.0, incidence_attempt.build_finished - started
                ),
                "search_seconds": max(
                    0.0,
                    incidence_attempt.search_finished
                    - incidence_attempt.build_finished,
                ),
                "candidate_rejected_reason": (
                    "deadline" if incidence_late else None
                ),
            }
        }
        if (
            incidence_attempt.solution is not None
            and incidence_attempt.validation is not None
            and incidence_attempt.validation.feasible
            and not incidence_late
        ):
            unencoded_hard = sorted(
                {
                    constraint.type
                    for constraint in problem.constraints
                    if constraint.required
                    and constraint.type
                    not in {
                        "AssignTimeConstraint",
                        "SplitEventsConstraint",
                        "DistributeSplitEventsConstraint",
                        "PreferTimesConstraint",
                        "AvoidClashesConstraint",
                        "AvoidUnavailableTimesConstraint",
                    }
                }
            )
            if incidence_attempt.validation.score.soft_cost == 0:
                return XHSTTSolveResult(
                    solution=incidence_attempt.solution,
                    validation=incidence_attempt.validation,
                    status="feasible",
                    raw_status=incidence_attempt.raw_status,
                    build_seconds=max(
                        0.0, incidence_attempt.build_finished - started
                    ),
                    search_seconds=max(
                        0.0,
                        incidence_attempt.search_finished
                        - incidence_attempt.build_finished,
                    ),
                    elapsed_seconds=max(
                        0.0, incidence_attempt.completed - started
                    ),
                    deadline_overrun_seconds=max(
                        0.0, incidence_attempt.completed - deadline
                    ),
                    seed=int(seed),
                    workers=workers,
                    telemetry={
                        "returned_source": "incidence_coloring",
                        "partition_mode": "aggregated_unit_meets",
                        "meet_count": incidence_attempt.unit_meet_count,
                        "encoded_constraint_types": [
                            "AssignTimeConstraint",
                            "AvoidClashesConstraint",
                            "AvoidUnavailableTimesConstraint",
                            "DistributeSplitEventsConstraint",
                            "PreferTimesConstraint",
                            "SplitEventsConstraint",
                        ],
                        "unencoded_hard_constraint_types": unencoded_hard,
                        "unsupported_features": list(problem.unsupported_features),
                        "resource_assignment_complete": assignments_complete,
                        "resource_assignment": assignment_telemetry,
                        **decomposition_telemetry,
                        **incidence_telemetry,
                    },
                )
            if (
                structural_validation is None
                or incidence_attempt.validation.score.lexicographic
                < structural_validation.score.lexicographic
            ):
                structural_solution = incidence_attempt.solution
                structural_validation = incidence_attempt.validation
                structural_source = "incidence_coloring"
                structural_raw_status = incidence_attempt.raw_status

    draft: list[XHSTTMeet] = []
    for event in problem.events:
        assignments = assignments_by_event[event.id]
        draft.extend(
            XHSTTMeet(
                event_id=event.id,
                duration=duration,
                time_id=event.preassigned_time_id,
                resource_assignments=assignments,
            )
            for duration in partitions[event.id]
        )
    if len(draft) > max_cp_meets:
        validation = validate_xhstt_solution(problem, fallback)
        elapsed = time.perf_counter() - started
        return XHSTTSolveResult(
            solution=fallback,
            validation=validation,
            status="scale_gated",
            raw_status=int(cp_model.UNKNOWN),
            build_seconds=elapsed,
            search_seconds=0.0,
            elapsed_seconds=elapsed,
            deadline_overrun_seconds=max(0.0, time.perf_counter() - deadline),
            seed=int(seed),
            workers=workers,
            telemetry={
                "returned_source": "resource_assigned_fallback",
                "meet_count": len(draft),
                "max_cp_meets": int(max_cp_meets),
                "resource_assignment_complete": assignments_complete,
                "resource_assignment": assignment_telemetry,
                **decomposition_telemetry,
                **incidence_telemetry,
            },
        )

    estimated_time_model_variables = len(draft) * len(problem.times)
    if estimated_time_model_variables > 200_000:
        validation = validate_xhstt_solution(problem, fallback)
        elapsed = time.perf_counter() - started
        return XHSTTSolveResult(
            solution=fallback,
            validation=validation,
            status="scale_gated",
            raw_status=int(cp_model.UNKNOWN),
            build_seconds=elapsed,
            search_seconds=0.0,
            elapsed_seconds=elapsed,
            deadline_overrun_seconds=max(0.0, time.perf_counter() - deadline),
            seed=int(seed),
            workers=workers,
            telemetry={
                "returned_source": "resource_assigned_fallback",
                "meet_count": len(draft),
                "estimated_time_model_variables": estimated_time_model_variables,
                "max_time_model_variables": 200_000,
                "resource_assignment_complete": assignments_complete,
                "resource_assignment": assignment_telemetry,
                **decomposition_telemetry,
                **incidence_telemetry,
            },
        )

    model = cp_model.CpModel()
    start_vars: list[cp_model.IntVar] = []
    allowed_starts_by_meet: list[frozenset[int]] = []
    attending_by_meet: list[frozenset[str]] = []
    intervals_by_resource: dict[str, list[cp_model.IntervalVar]] = defaultdict(list)
    clash_resources: set[str] = set()
    for constraint in problem.constraints:
        if constraint.required and constraint.type == "AvoidClashesConstraint":
            clash_resources.update(_applied_resources(problem, constraint))

    draft_by_event: dict[str, list[int]] = defaultdict(list)
    encoded_constraint_types: set[str] = {
        "AssignTimeConstraint",
        "SplitEventsConstraint",
        "DistributeSplitEventsConstraint",
        "PreferTimesConstraint",
        "AvoidClashesConstraint",
        "AvoidUnavailableTimesConstraint",
        "SpreadEventsConstraint",
        "LinkEventsConstraint",
        "OrderEventsConstraint",
    }
    for meet_index, meet in enumerate(draft):
        if meet_index % 32 == 0 and time.perf_counter() >= search_deadline:
            validation = validate_xhstt_solution(problem, fallback)
            elapsed = time.perf_counter() - started
            return XHSTTSolveResult(
                solution=fallback,
                validation=validation,
                status="deadline_during_build",
                raw_status=int(cp_model.UNKNOWN),
                build_seconds=elapsed,
                search_seconds=0.0,
                elapsed_seconds=elapsed,
                deadline_overrun_seconds=max(0.0, time.perf_counter() - deadline),
                seed=int(seed),
                workers=workers,
                telemetry={
                    "returned_source": "resource_assigned_fallback",
                    "resource_assignment_complete": assignments_complete,
                    "resource_assignment": assignment_telemetry,
                    **decomposition_telemetry,
                    **incidence_telemetry,
                },
            )
        event = problem.event_by_id[meet.event_id]
        allowed = _allowed_start_indices(
            problem,
            event,
            meet.duration,
            meet.resource_assignments,
        )
        attending = _attending_resources(
            problem, event, meet.resource_assignments
        )
        if not allowed:
            validation = validate_xhstt_solution(problem, fallback)
            elapsed = time.perf_counter() - started
            return XHSTTSolveResult(
                solution=fallback,
                validation=validation,
                status="infeasible_encoded_domain",
                raw_status=int(cp_model.INFEASIBLE),
                build_seconds=elapsed,
                search_seconds=0.0,
                elapsed_seconds=elapsed,
                deadline_overrun_seconds=max(0.0, time.perf_counter() - deadline),
                seed=int(seed),
                workers=workers,
                telemetry={
                    "returned_source": "resource_assigned_fallback",
                    "resource_assignment_complete": assignments_complete,
                    "resource_assignment": assignment_telemetry,
                    **decomposition_telemetry,
                    **incidence_telemetry,
                },
            )
        start = model.new_int_var_from_domain(
            cp_model.Domain.from_values(sorted(allowed)), f"start_{meet_index}"
        )
        start_vars.append(start)
        allowed_starts_by_meet.append(allowed)
        attending_by_meet.append(attending)
        draft_by_event[meet.event_id].append(meet_index)
        for resource_id in attending.intersection(clash_resources):
            intervals_by_resource[resource_id].append(
                model.new_fixed_size_interval_var(
                    start, meet.duration, f"interval_{meet_index}_{resource_id}"
                )
            )
    for intervals in intervals_by_resource.values():
        if len(intervals) > 1:
            model.add_no_overlap(intervals)

    membership_flags: dict[tuple[int, tuple[int, ...]], cp_model.IntVar] = {}
    membership_counter = 0

    def membership_flag(
        meet_index: int,
        selected_indices: Iterable[int],
    ) -> cp_model.IntVar:
        nonlocal membership_counter
        selected = tuple(
            sorted(set(selected_indices).intersection(allowed_starts_by_meet[meet_index]))
        )
        key = meet_index, selected
        cached = membership_flags.get(key)
        if cached is not None:
            return cached
        allowed = allowed_starts_by_meet[meet_index]
        if not selected:
            result = model.new_constant(0)
        elif len(selected) == len(allowed):
            result = model.new_constant(1)
        else:
            result = model.new_bool_var(f"membership_{membership_counter}")
            membership_counter += 1
            selected_set = set(selected)
            model.add_allowed_assignments(
                [start_vars[meet_index], result],
                [(value, int(value in selected_set)) for value in sorted(allowed)],
            )
        membership_flags[key] = result
        return result

    meet_indices_by_resource: dict[str, list[int]] = defaultdict(list)
    for meet_index, attending in enumerate(attending_by_meet):
        for resource_id in attending:
            meet_indices_by_resource[resource_id].append(meet_index)
    busy_flags: dict[tuple[str, int], cp_model.IntVar] = {}

    def busy_flag(resource_id: str, time_index: int) -> cp_model.IntVar:
        key = resource_id, time_index
        cached = busy_flags.get(key)
        if cached is not None:
            return cached
        covering: list[cp_model.IntVar] = []
        for meet_index in meet_indices_by_resource.get(resource_id, []):
            duration = draft[meet_index].duration
            starts = {
                start
                for start in allowed_starts_by_meet[meet_index]
                if start <= time_index < start + duration
            }
            if starts:
                covering.append(membership_flag(meet_index, starts))
        if not covering:
            result = model.new_constant(0)
        elif len(covering) == 1:
            result = covering[0]
        else:
            result = model.new_bool_var(
                f"busy_{len(busy_flags)}_{time_index}"
            )
            model.add_max_equality(result, covering)
        busy_flags[key] = result
        return result

    event_busy_flags: dict[tuple[str, int], cp_model.IntVar] = {}

    def event_busy_flag(event_id: str, time_index: int) -> cp_model.IntVar:
        key = event_id, time_index
        cached = event_busy_flags.get(key)
        if cached is not None:
            return cached
        covering: list[cp_model.IntVar] = []
        for meet_index in draft_by_event[event_id]:
            duration = draft[meet_index].duration
            starts = {
                start
                for start in allowed_starts_by_meet[meet_index]
                if start <= time_index < start + duration
            }
            if starts:
                covering.append(membership_flag(meet_index, starts))
        if not covering:
            result = model.new_constant(0)
        elif len(covering) == 1:
            result = covering[0]
        else:
            result = model.new_bool_var(
                f"event_busy_{len(event_busy_flags)}_{time_index}"
            )
            model.add_max_equality(result, covering)
        event_busy_flags[key] = result
        return result

    def amount_variable(
        values: Sequence[cp_model.IntVar],
        *,
        name: str,
    ) -> cp_model.IntVar:
        amount = model.new_int_var(0, len(values), name)
        model.add(amount == sum(values))
        return amount

    def interval_deviation(
        amount: cp_model.IntVar,
        *,
        amount_upper_bound: int,
        minimum: int,
        maximum: int,
        zero_is_valid: bool,
        name: str,
    ) -> tuple[cp_model.IntVar, int]:
        deviations = [
            (
                0
                if zero_is_valid and value == 0
                else _distance_to_interval(value, minimum, maximum)
            )
            for value in range(amount_upper_bound + 1)
        ]
        upper_bound = max(deviations, default=0)
        deviation = model.new_int_var(0, upper_bound, name)
        model.add_allowed_assignments(
            [amount, deviation],
            list(enumerate(deviations)),
        )
        return deviation, upper_bound

    idle_totals: dict[tuple[str, tuple[str, ...]], tuple[cp_model.IntVar, int]] = {}

    def idle_total(
        resource_id: str,
        time_group_ids: Sequence[str],
    ) -> tuple[cp_model.IntVar, int]:
        key = resource_id, tuple(time_group_ids)
        cached = idle_totals.get(key)
        if cached is not None:
            return cached
        idle_flags: list[cp_model.IntVar] = []
        for group_id in time_group_ids:
            indices = sorted(
                problem.time_index[time_id]
                for time_id in problem.times_by_group[group_id]
            )
            row = [busy_flag(resource_id, index) for index in indices]
            if len(row) < 3:
                continue
            prefixes: list[cp_model.IntVar] = []
            for position, flag in enumerate(row):
                if position == 0:
                    prefixes.append(flag)
                else:
                    prefix = model.new_bool_var(
                        f"idle_prefix_{len(idle_flags)}_{position}"
                    )
                    model.add_max_equality(prefix, [prefixes[-1], flag])
                    prefixes.append(prefix)
            suffixes: list[cp_model.IntVar] = [row[-1]]
            for position in range(len(row) - 2, -1, -1):
                suffix = model.new_bool_var(
                    f"idle_suffix_{len(idle_flags)}_{position}"
                )
                model.add_max_equality(suffix, [row[position], suffixes[0]])
                suffixes.insert(0, suffix)
            for position in range(1, len(row) - 1):
                idle = model.new_bool_var(
                    f"idle_{len(idle_flags)}_{position}"
                )
                before = prefixes[position - 1]
                after = suffixes[position + 1]
                current = row[position]
                model.add(idle <= before)
                model.add(idle <= after)
                model.add(idle + current <= 1)
                model.add(idle >= before + after - current - 1)
                idle_flags.append(idle)
        total = amount_variable(
            idle_flags,
            name=f"idle_total_{len(idle_totals)}",
        )
        result = total, len(idle_flags)
        idle_totals[key] = result
        return result

    for constraint in problem.constraints:
        if not constraint.required:
            continue
        if constraint.type == "SpreadEventsConstraint":
            for group_id in constraint.applies_event_group_ids:
                meet_indices = [
                    index
                    for event_id in problem.events_by_group[group_id]
                    for index in draft_by_event[event_id]
                ]
                for limit in constraint.time_group_limits:
                    selected_indices = {
                        problem.time_index[time_id]
                        for time_id in problem.times_by_group[limit.time_group_id]
                    }
                    flags: list[cp_model.IntVar] = []
                    for index in meet_indices:
                        flag = model.new_bool_var(
                            f"spread_{constraint.id}_{group_id}_{limit.time_group_id}_{index}"
                        )
                        domain = list(start_vars[index].proto.domain)
                        possible: list[int] = []
                        for pos in range(0, len(domain), 2):
                            possible.extend(range(domain[pos], domain[pos + 1] + 1))
                        model.add_allowed_assignments(
                            [start_vars[index], flag],
                            [(value, int(value in selected_indices)) for value in possible],
                        )
                        flags.append(flag)
                    model.add(sum(flags) >= limit.minimum)
                    model.add(sum(flags) <= limit.maximum)
        elif constraint.type == "LimitBusyTimesConstraint":
            assert constraint.minimum is not None
            assert constraint.maximum is not None
            for resource_id in sorted(_applied_resources(problem, constraint)):
                for group_id in constraint.time_group_ids:
                    indices = sorted(
                        problem.time_index[time_id]
                        for time_id in problem.times_by_group[group_id]
                    )
                    flags = [busy_flag(resource_id, index) for index in indices]
                    amount = amount_variable(
                        flags,
                        name=f"hard_busy_{constraint.id}_{resource_id}_{group_id}",
                    )
                    used = model.new_bool_var(
                        f"hard_busy_used_{constraint.id}_{resource_id}_{group_id}"
                    )
                    model.add_max_equality(used, flags or [model.new_constant(0)])
                    model.add(amount >= constraint.minimum).only_enforce_if(used)
                    model.add(amount <= constraint.maximum).only_enforce_if(used)
            encoded_constraint_types.add("LimitBusyTimesConstraint")
        elif constraint.type == "ClusterBusyTimesConstraint":
            assert constraint.minimum is not None
            assert constraint.maximum is not None
            for resource_id in sorted(_applied_resources(problem, constraint)):
                group_flags: list[cp_model.IntVar] = []
                for group_id in constraint.time_group_ids:
                    indices = sorted(
                        problem.time_index[time_id]
                        for time_id in problem.times_by_group[group_id]
                    )
                    used = model.new_bool_var(
                        f"hard_cluster_{constraint.id}_{resource_id}_{group_id}"
                    )
                    model.add_max_equality(
                        used,
                        [busy_flag(resource_id, index) for index in indices]
                        or [model.new_constant(0)],
                    )
                    group_flags.append(used)
                amount = amount_variable(
                    group_flags,
                    name=f"hard_cluster_amount_{constraint.id}_{resource_id}",
                )
                model.add(amount >= constraint.minimum)
                model.add(amount <= constraint.maximum)
            encoded_constraint_types.add("ClusterBusyTimesConstraint")
        elif constraint.type == "LimitIdleTimesConstraint":
            assert constraint.minimum is not None
            assert constraint.maximum is not None
            for resource_id in sorted(_applied_resources(problem, constraint)):
                amount, _ = idle_total(resource_id, constraint.time_group_ids)
                model.add(amount >= constraint.minimum)
                model.add(amount <= constraint.maximum)
            encoded_constraint_types.add("LimitIdleTimesConstraint")
        elif constraint.type == "LinkEventsConstraint":
            for group_id in constraint.applies_event_group_ids:
                event_ids = sorted(problem.events_by_group[group_id])
                if not event_ids:
                    continue
                for time_index in range(len(problem.times)):
                    first = event_busy_flag(event_ids[0], time_index)
                    for event_id in event_ids[1:]:
                        model.add(event_busy_flag(event_id, time_index) == first)
        elif constraint.type == "OrderEventsConstraint":
            for pair in constraint.event_pairs:
                first = draft_by_event[pair.first_event_id]
                second = draft_by_event[pair.second_event_id]
                if len(first) == 1 and len(second) == 1:
                    first_index = first[0]
                    gap = (
                        start_vars[second[0]]
                        - start_vars[first_index]
                        - draft[first_index].duration
                    )
                    model.add(gap >= pair.minimum_separation)
                    model.add(gap <= pair.maximum_separation)
                else:
                    encoded_constraint_types.discard("OrderEventsConstraint")

    objective_terms: list[cp_model.LinearExpr] = []
    objective_constraint_types: set[str] = set()
    for constraint_index, constraint in enumerate(problem.constraints):
        if constraint.required or constraint.weight <= 0:
            continue
        groups: list[list[tuple[cp_model.IntVar, int]]] = []
        prefix = f"soft_{constraint_index}_{constraint.id}"
        if constraint.type == "PreferTimesConstraint":
            selected_indices = {
                problem.time_index[time_id]
                for time_id in _selected_times(
                    problem,
                    constraint.preferred_time_ids,
                    constraint.preferred_time_group_ids,
                )
            }
            for event_id in sorted(_applied_events(problem, constraint)):
                event = problem.event_by_id[event_id]
                if event.preassigned_time_id is not None:
                    continue
                deviations: list[tuple[cp_model.IntVar, int]] = []
                for meet_index in draft_by_event[event_id]:
                    duration = draft[meet_index].duration
                    if (
                        constraint.duration is not None
                        and constraint.duration != duration
                    ):
                        continue
                    preferred = membership_flag(meet_index, selected_indices)
                    deviation = model.new_int_var(
                        0,
                        duration,
                        f"{prefix}_deviation_{meet_index}",
                    )
                    model.add(deviation == duration * (1 - preferred))
                    deviations.append((deviation, duration))
                groups.append(deviations)
        elif constraint.type == "SpreadEventsConstraint":
            for event_group_id in constraint.applies_event_group_ids:
                deviations: list[tuple[cp_model.IntVar, int]] = []
                meet_indices = [
                    meet_index
                    for event_id in problem.events_by_group[event_group_id]
                    for meet_index in draft_by_event[event_id]
                ]
                for limit_index, limit in enumerate(constraint.time_group_limits):
                    selected_indices = {
                        problem.time_index[time_id]
                        for time_id in problem.times_by_group[limit.time_group_id]
                    }
                    flags = [
                        membership_flag(meet_index, selected_indices)
                        for meet_index in meet_indices
                    ]
                    amount = amount_variable(
                        flags,
                        name=(
                            f"{prefix}_amount_{event_group_id}_{limit_index}"
                        ),
                    )
                    deviations.append(
                        interval_deviation(
                            amount,
                            amount_upper_bound=len(flags),
                            minimum=limit.minimum,
                            maximum=limit.maximum,
                            zero_is_valid=False,
                            name=(
                                f"{prefix}_deviation_{event_group_id}_{limit_index}"
                            ),
                        )
                    )
                groups.append(deviations)
        elif constraint.type == "AvoidUnavailableTimesConstraint":
            selected_indices = {
                problem.time_index[time_id]
                for time_id in _selected_times(
                    problem,
                    constraint.preferred_time_ids,
                    constraint.preferred_time_group_ids,
                )
            }
            for resource_id in sorted(_applied_resources(problem, constraint)):
                flags = [
                    busy_flag(resource_id, time_index)
                    for time_index in sorted(selected_indices)
                ]
                amount = amount_variable(
                    flags,
                    name=f"{prefix}_amount_{resource_id}",
                )
                groups.append([(amount, len(flags))])
        elif constraint.type == "LimitBusyTimesConstraint":
            assert constraint.minimum is not None
            assert constraint.maximum is not None
            for resource_id in sorted(_applied_resources(problem, constraint)):
                deviations: list[tuple[cp_model.IntVar, int]] = []
                for group_id in constraint.time_group_ids:
                    indices = sorted(
                        problem.time_index[time_id]
                        for time_id in problem.times_by_group[group_id]
                    )
                    flags = [busy_flag(resource_id, index) for index in indices]
                    amount = amount_variable(
                        flags,
                        name=f"{prefix}_amount_{resource_id}_{group_id}",
                    )
                    deviations.append(
                        interval_deviation(
                            amount,
                            amount_upper_bound=len(flags),
                            minimum=constraint.minimum,
                            maximum=constraint.maximum,
                            zero_is_valid=True,
                            name=f"{prefix}_deviation_{resource_id}_{group_id}",
                        )
                    )
                groups.append(deviations)
        elif constraint.type == "ClusterBusyTimesConstraint":
            assert constraint.minimum is not None
            assert constraint.maximum is not None
            for resource_id in sorted(_applied_resources(problem, constraint)):
                group_flags: list[cp_model.IntVar] = []
                for group_id in constraint.time_group_ids:
                    indices = sorted(
                        problem.time_index[time_id]
                        for time_id in problem.times_by_group[group_id]
                    )
                    used = model.new_bool_var(
                        f"{prefix}_used_{resource_id}_{group_id}"
                    )
                    model.add_max_equality(
                        used,
                        [busy_flag(resource_id, index) for index in indices]
                        or [model.new_constant(0)],
                    )
                    group_flags.append(used)
                amount = amount_variable(
                    group_flags,
                    name=f"{prefix}_amount_{resource_id}",
                )
                groups.append(
                    [
                        interval_deviation(
                            amount,
                            amount_upper_bound=len(group_flags),
                            minimum=constraint.minimum,
                            maximum=constraint.maximum,
                            zero_is_valid=False,
                            name=f"{prefix}_deviation_{resource_id}",
                        )
                    ]
                )
        elif constraint.type == "LimitIdleTimesConstraint":
            assert constraint.minimum is not None
            assert constraint.maximum is not None
            for resource_id in sorted(_applied_resources(problem, constraint)):
                amount, upper_bound = idle_total(
                    resource_id, constraint.time_group_ids
                )
                groups.append(
                    [
                        interval_deviation(
                            amount,
                            amount_upper_bound=upper_bound,
                            minimum=constraint.minimum,
                            maximum=constraint.maximum,
                            zero_is_valid=False,
                            name=f"{prefix}_deviation_{resource_id}",
                        )
                    ]
                )
        elif constraint.type == "LinkEventsConstraint":
            for event_group_id in constraint.applies_event_group_ids:
                event_ids = sorted(problem.events_by_group[event_group_id])
                if not event_ids:
                    groups.append([])
                    continue
                differences: list[cp_model.IntVar] = []
                for time_index in range(len(problem.times)):
                    flags = [
                        event_busy_flag(event_id, time_index)
                        for event_id in event_ids
                    ]
                    union = model.new_bool_var(
                        f"{prefix}_union_{event_group_id}_{time_index}"
                    )
                    intersection = model.new_bool_var(
                        f"{prefix}_intersection_{event_group_id}_{time_index}"
                    )
                    difference = model.new_bool_var(
                        f"{prefix}_difference_{event_group_id}_{time_index}"
                    )
                    model.add_max_equality(union, flags)
                    model.add_min_equality(intersection, flags)
                    model.add(difference == union - intersection)
                    differences.append(difference)
                amount = amount_variable(
                    differences,
                    name=f"{prefix}_amount_{event_group_id}",
                )
                groups.append([(amount, len(differences))])
        if groups:
            constraint_terms = _add_cp_deviation_cost(
                model,
                constraint,
                groups,
                prefix=prefix,
            )
            if constraint_terms:
                objective_terms.extend(constraint_terms)
                objective_constraint_types.add(constraint.type)

    if objective_terms:
        model.minimize(sum(objective_terms))

    if structural_solution is not None:
        incumbent_by_event: dict[str, list[XHSTTMeet]] = defaultdict(list)
        for meet in structural_solution.meets:
            incumbent_by_event[meet.event_id].append(meet)
        for event_id, meet_indices in draft_by_event.items():
            incumbent_meets = incumbent_by_event[event_id]
            if sorted(meet.duration for meet in incumbent_meets) != sorted(
                draft[index].duration for index in meet_indices
            ):
                continue
            remaining_meets = list(incumbent_meets)
            for meet_index in meet_indices:
                duration = draft[meet_index].duration
                match = next(
                    (
                        meet
                        for meet in remaining_meets
                        if meet.duration == duration and meet.time_id is not None
                    ),
                    None,
                )
                if match is None:
                    break
                model.add_hint(start_vars[meet_index], problem.time_index[match.time_id])
                remaining_meets.remove(match)

    build_finished = time.perf_counter()
    remaining = max(0.0, search_deadline - build_finished)
    if remaining < _MIN_CP_SEARCH_SECONDS:
        if structural_solution is not None and structural_validation is not None:
            solution = structural_solution
            validation = structural_validation
            status = "feasible"
            raw_status = structural_raw_status
            returned_source = structural_source or "structural_incumbent"
        else:
            solution = fallback
            validation = validate_xhstt_solution(problem, fallback)
            status = "deadline_during_build"
            raw_status = int(cp_model.UNKNOWN)
            returned_source = "resource_assigned_fallback"
        elapsed = time.perf_counter() - started
        return XHSTTSolveResult(
            solution=solution,
            validation=validation,
            status=status,
            raw_status=raw_status,
            build_seconds=build_finished - started,
            search_seconds=0.0,
            elapsed_seconds=elapsed,
            deadline_overrun_seconds=max(0.0, time.perf_counter() - deadline),
            seed=int(seed),
            workers=workers,
            telemetry={
                "returned_source": returned_source,
                "objective_constraint_types": sorted(
                    objective_constraint_types
                ),
                "structural_incumbent_score": (
                    list(structural_validation.score.lexicographic)
                    if structural_validation is not None
                    else None
                ),
                "resource_assignment_complete": assignments_complete,
                "resource_assignment": assignment_telemetry,
                **decomposition_telemetry,
                **incidence_telemetry,
            },
        )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = remaining
    solver.parameters.random_seed = int(seed)
    solver.parameters.num_search_workers = workers
    raw_status = int(solver.solve(model))
    search_finished = time.perf_counter()
    candidate_rejected_reason: str | None = None
    if raw_status not in {int(cp_model.OPTIMAL), int(cp_model.FEASIBLE)}:
        if structural_solution is not None and structural_validation is not None:
            solution = structural_solution
            validation = structural_validation
            status = "feasible"
            returned_source = structural_source or "structural_incumbent"
        else:
            validation = validate_xhstt_solution(problem, fallback)
            solution = fallback
            status = (
                "encoded_infeasible"
                if raw_status == int(cp_model.INFEASIBLE)
                else "unknown"
            )
            returned_source = "resource_assigned_fallback"
    elif search_finished > deadline:
        candidate_rejected_reason = "deadline"
        if structural_solution is not None and structural_validation is not None:
            solution = structural_solution
            validation = structural_validation
            status = "feasible"
            returned_source = structural_source or "structural_incumbent"
        else:
            solution = fallback
            validation = validate_xhstt_solution(problem, fallback)
            status = "deadline_after_search"
            returned_source = "resource_assigned_fallback"
    else:
        solved_rows = tuple(
            XHSTTMeet(
                event_id=meet.event_id,
                duration=meet.duration,
                time_id=problem.times[solver.value(start_vars[index])].id,
                resource_assignments=meet.resource_assignments,
            )
            for index, meet in enumerate(draft)
        )
        candidate = XHSTTSolution(instance_id=problem.id, meets=solved_rows)
        candidate_validation = validate_xhstt_solution(problem, candidate)
        candidate_completed = time.perf_counter()
        if candidate_completed > deadline:
            candidate_rejected_reason = "deadline"
            if (
                structural_solution is not None
                and structural_validation is not None
            ):
                solution = structural_solution
                validation = structural_validation
                status = "feasible"
                returned_source = structural_source or "structural_incumbent"
            else:
                solution = fallback
                validation = validate_xhstt_solution(problem, fallback)
                status = "deadline_after_validation"
                returned_source = "resource_assigned_fallback"
        elif (
            structural_solution is not None
            and structural_validation is not None
            and structural_validation.score.lexicographic
            <= candidate_validation.score.lexicographic
        ):
            solution = structural_solution
            validation = structural_validation
            status = "feasible"
            returned_source = structural_source or "structural_incumbent"
        else:
            solution = candidate
            validation = candidate_validation
            status = "feasible" if validation.feasible else "partial_feasible"
            returned_source = "native_cp_sat"
    completed = time.perf_counter()
    elapsed = completed - started
    unencoded_hard = sorted(
        {
            constraint.type
            for constraint in problem.constraints
            if constraint.required and constraint.type not in encoded_constraint_types
        }
    )
    return XHSTTSolveResult(
        solution=solution,
        validation=validation,
        status=status,
        raw_status=raw_status,
        build_seconds=build_finished - started,
        search_seconds=search_finished - build_finished,
        elapsed_seconds=elapsed,
        deadline_overrun_seconds=max(0.0, completed - deadline),
        seed=int(seed),
        workers=workers,
        telemetry={
            "returned_source": returned_source,
            "meet_count": len(draft),
            "partition_search_complete": partitions_complete,
            "encoded_constraint_types": sorted(encoded_constraint_types),
            "objective_constraint_types": sorted(objective_constraint_types),
            "structural_incumbent_score": (
                list(structural_validation.score.lexicographic)
                if structural_validation is not None
                else None
            ),
            "candidate_rejected_reason": candidate_rejected_reason,
            "unencoded_hard_constraint_types": unencoded_hard,
            "unsupported_features": list(problem.unsupported_features),
            "resource_assignment_complete": assignments_complete,
            "resource_assignment": assignment_telemetry,
            **decomposition_telemetry,
            **incidence_telemetry,
        },
    )


__all__ = [
    "XHSTTArchive",
    "XHSTTConstraint",
    "XHSTTConstraintCost",
    "XHSTTEvent",
    "XHSTTEventGroup",
    "XHSTTEventPair",
    "XHSTTEventResource",
    "XHSTTMeet",
    "XHSTTProblem",
    "XHSTTResource",
    "XHSTTResourceAssignment",
    "XHSTTResourceGroup",
    "XHSTTResourceType",
    "XHSTTScore",
    "XHSTTSolution",
    "XHSTTSolveResult",
    "XHSTTTime",
    "XHSTTTimeGroup",
    "XHSTTTimeGroupLimit",
    "XHSTTValidation",
    "parse_xhstt",
    "parse_xhstt_archive",
    "parse_xhstt_solutions",
    "solve_xhstt",
    "validate_xhstt_solution",
    "write_xhstt_solution",
]
