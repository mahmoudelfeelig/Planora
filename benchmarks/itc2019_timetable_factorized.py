from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from itertools import combinations
import math
import time
from typing import Any, Iterable, Mapping, Sequence

from ortools.sat.python import cp_model

from benchmarks.itc2019 import (
    ITC2019Class,
    ITC2019ClassPlacement,
    ITC2019Problem,
    ITC2019RoomOption,
    ITC2019TimeOption,
    _distribution_spec,
    _travel_values,
    evaluate_itc2019_distributions,
    validate_itc2019_class_placements,
)
from benchmarks.itc2019_factorized import (
    _EncodingInfeasible,
    _EncodingScaleExceeded,
    _FactorizedDomains,
    _PairEncoder,
    _SparseRoomBudget,
    _add_group_distribution,
    _add_room_resources,
    _group_distribution_estimate,
    _travel_distance,
    _travel_exception_count,
)


_TIME_PAIR_DISTRIBUTIONS = frozenset(
    {
        "SameStart",
        "SameTime",
        "DifferentTime",
        "SameDays",
        "DifferentDays",
        "SameWeeks",
        "DifferentWeeks",
        "Overlap",
        "NotOverlap",
        "Precedence",
        "WorkDay",
        "MinGap",
    }
)
_ROOM_PAIR_DISTRIBUTIONS = frozenset({"SameRoom", "DifferentRoom"})
SUPPORTED_REQUIRED_PAIR_DISTRIBUTIONS = frozenset(
    {*_TIME_PAIR_DISTRIBUTIONS, *_ROOM_PAIR_DISTRIBUTIONS, "SameAttendees"}
)
SUPPORTED_REQUIRED_GROUP_DISTRIBUTIONS = frozenset({"MaxBreaks"})
_DEADLINE_CHECK_INTERVAL = 64
_CP_SAT_INT64_MAX = (1 << 63) - 1


@dataclass
class _DeadlineGuard:
    deadline: float
    operations: int = 0

    def check(self, message: str, *, force: bool = False) -> None:
        self.operations += 1
        if (
            force or self.operations % _DEADLINE_CHECK_INTERVAL == 0
        ) and time.monotonic() >= self.deadline:
            raise TimeoutError(message)


@dataclass(frozen=True)
class ITC2019TimetableFactorizedLimits:
    """Fail-closed construction limits for the prototype."""

    max_domain_values: int = 2_500_000
    max_required_pair_relations: int = 2_000_000
    max_required_group_cells: int = 2_000_000
    max_sparse_room_constraints: int = 2_500_000
    max_room_pair_evaluations: int = 2_500_000
    max_room_pair_evaluations_per_pair: int = 250_000

    def validate(self) -> None:
        if self.max_domain_values <= 0:
            raise ValueError("max_domain_values must be positive")
        if self.max_required_pair_relations <= 0:
            raise ValueError("max_required_pair_relations must be positive")
        if self.max_required_group_cells <= 0:
            raise ValueError("max_required_group_cells must be positive")
        if self.max_sparse_room_constraints <= 0:
            raise ValueError("max_sparse_room_constraints must be positive")
        if self.max_room_pair_evaluations <= 0:
            raise ValueError("max_room_pair_evaluations must be positive")
        if self.max_room_pair_evaluations_per_pair <= 0:
            raise ValueError("max_room_pair_evaluations_per_pair must be positive")


@dataclass(frozen=True)
class _RequiredDistributionRequest:
    distribution_index: int
    base: str
    parameters: tuple[int, ...]
    class_ids: tuple[str, ...]


@dataclass(frozen=True)
class _DistributionAdmission:
    pair_requests: tuple[_RequiredDistributionRequest, ...] = ()
    group_requests: tuple[_RequiredDistributionRequest, ...] = ()
    non_same_attendees_relations: int = 0
    soft_distributions: int = 0
    unsupported: tuple[str, ...] = ()


@dataclass(frozen=True)
class _RoomPairPreflight:
    evaluations: int = 0
    sparse_constraints: int = 0
    rejection: str | None = None


@dataclass(frozen=True)
class _PreparedSameAttendeesRelations:
    relations: tuple[tuple[str, str], ...] = ()
    raw_ordered_relations: int = 0
    exact_ordered_duplicates_removed: int = 0
    reversed_equivalent_relations_removed: int = 0
    equivalence_evaluations: int = 0


@dataclass(frozen=True)
class ITC2019SameAttendeesWorkload:
    """Static prepared-relation evidence; constructing it never creates a model."""

    prepared_ordered_relations: tuple[tuple[str, str], ...]
    raw_ordered_relations: int
    exact_ordered_duplicates_removed: int
    reversed_equivalent_relations_removed: int
    equivalence_evaluations: int
    room_pair_evaluations: int
    exact_sparse_constraints: int
    rejection: str | None


@dataclass(frozen=True)
class ITC2019TimetableFactorizedTelemetry:
    """Build evidence with a stable structural signature and separate wall times."""

    schema: str
    class_count: int
    time_domain_values: int
    room_domain_values: int
    required_pair_distributions: int
    required_pair_relations: int
    required_group_distributions: int
    required_group_cells: int
    room_pair_evaluations: int
    sparse_room_constraints: int
    model_variables: int
    model_constraints: int
    model_proto_bytes: int
    model_proto_sha256: str
    model_fingerprint_mode: str
    source_student_records_excluded: int
    source_soft_distributions_excluded: int
    phase_wall_seconds: tuple[tuple[str, float], ...]

    @property
    def deterministic_signature(self) -> tuple[tuple[str, int | str], ...]:
        """Return only input-derived metrics; wall-clock observations are excluded."""

        return (
            ("schema", self.schema),
            ("class_count", self.class_count),
            ("time_domain_values", self.time_domain_values),
            ("room_domain_values", self.room_domain_values),
            ("required_pair_distributions", self.required_pair_distributions),
            ("required_pair_relations", self.required_pair_relations),
            ("required_group_distributions", self.required_group_distributions),
            ("required_group_cells", self.required_group_cells),
            ("room_pair_evaluations", self.room_pair_evaluations),
            ("sparse_room_constraints", self.sparse_room_constraints),
            ("model_variables", self.model_variables),
            ("model_constraints", self.model_constraints),
            ("model_proto_bytes", self.model_proto_bytes),
            ("model_proto_sha256", self.model_proto_sha256),
            ("model_fingerprint_mode", self.model_fingerprint_mode),
            (
                "source_soft_distributions_excluded",
                self.source_soft_distributions_excluded,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["deterministic_signature"] = dict(self.deterministic_signature)
        return payload


@dataclass(frozen=True)
class ITC2019TimetableFactorizedResult:
    """Build or solve result for the isolated timetable-only prototype.

    A ``BUILT`` result contains a model but no candidate.  A solve result contains
    placements only after the independent arithmetic validators have accepted a
    complete candidate.
    """

    status: str
    build_only: bool
    model: cp_model.CpModel | None
    time_choices: Mapping[str, cp_model.IntVar]
    room_choices: Mapping[str, cp_model.IntVar]
    time_domains: Mapping[str, tuple[ITC2019TimeOption, ...]]
    room_domains: Mapping[str, tuple[ITC2019RoomOption | None, ...]]
    placements: tuple[ITC2019ClassPlacement, ...]
    telemetry: ITC2019TimetableFactorizedTelemetry
    unsupported_reasons: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()
    solver_status: str = "NOT_RUN"
    solver_wall_time_seconds: float = 0.0
    conflicts: int = 0
    branches: int = 0

    @property
    def has_validated_candidate(self) -> bool:
        return (
            self.status in {"FEASIBLE", "OPTIMAL"}
            and bool(self.placements)
            and not self.validation_errors
            and not self.unsupported_reasons
        )


def _empty_telemetry(
    problem: ITC2019Problem,
    *,
    phases: Sequence[tuple[str, float]],
    class_count: int | None = None,
    domains: _FactorizedDomains | None = None,
    required_pair_distributions: int = 0,
    required_pair_relations: int = 0,
    required_group_distributions: int = 0,
    required_group_cells: int = 0,
    source_soft_distributions_excluded: int = 0,
    room_pair_evaluations: int = 0,
    sparse_room_constraints: int = 0,
    model: cp_model.CpModel | None = None,
    model_proto: bytes | None = None,
) -> ITC2019TimetableFactorizedTelemetry:
    proto = model_proto or b""
    return ITC2019TimetableFactorizedTelemetry(
        schema="planora.itc2019.timetable-factorized-build.v1",
        class_count=len(problem.classes) if class_count is None else class_count,
        time_domain_values=domains.time_values if domains is not None else 0,
        room_domain_values=domains.room_values if domains is not None else 0,
        required_pair_distributions=required_pair_distributions,
        required_pair_relations=required_pair_relations,
        required_group_distributions=required_group_distributions,
        required_group_cells=required_group_cells,
        room_pair_evaluations=room_pair_evaluations,
        sparse_room_constraints=sparse_room_constraints,
        model_variables=len(model.proto.variables) if model is not None else 0,
        model_constraints=len(model.proto.constraints) if model is not None else 0,
        model_proto_bytes=len(proto),
        model_proto_sha256=sha256(proto).hexdigest() if proto else "",
        model_fingerprint_mode="canonical_proto_text_v1" if proto else "not_requested",
        source_student_records_excluded=len(problem.students),
        source_soft_distributions_excluded=source_soft_distributions_excluded,
        phase_wall_seconds=tuple(phases),
    )


def _deterministic_model_bytes(model: cp_model.CpModel) -> bytes:
    # OR-Tools 9.15 exposes CpModelProto through a pybind wrapper rather than a
    # generated protobuf Message, so SerializeToString is intentionally absent.
    # Its canonical protobuf text representation is stable and preserves field
    # order, making it suitable for exact repeated-build comparison and hashing.
    return str(model.proto).encode("utf-8")


def _failure(
    problem: ITC2019Problem,
    *,
    status: str,
    phases: Sequence[tuple[str, float]],
    class_count: int | None = None,
    domains: _FactorizedDomains | None = None,
    required_pair_distributions: int = 0,
    required_pair_relations: int = 0,
    required_group_distributions: int = 0,
    required_group_cells: int = 0,
    source_soft_distributions_excluded: int = 0,
    room_pair_evaluations: int = 0,
    sparse_room_constraints: int = 0,
    unsupported_reasons: Sequence[str] = (),
    validation_errors: Sequence[str] = (),
) -> ITC2019TimetableFactorizedResult:
    return ITC2019TimetableFactorizedResult(
        status=status,
        build_only=True,
        model=None,
        time_choices={},
        room_choices={},
        time_domains={},
        room_domains={},
        placements=(),
        telemetry=_empty_telemetry(
            problem,
            phases=phases,
            class_count=class_count,
            domains=domains,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
            required_group_cells=required_group_cells,
            source_soft_distributions_excluded=source_soft_distributions_excluded,
            room_pair_evaluations=room_pair_evaluations,
            sparse_room_constraints=sparse_room_constraints,
        ),
        unsupported_reasons=tuple(unsupported_reasons),
        validation_errors=tuple(validation_errors),
    )


def _finish_phase(
    phases: list[tuple[str, float]],
    name: str,
    phase_started: float,
) -> float:
    now = time.monotonic()
    phases.append((name, max(0.0, now - phase_started)))
    return now


def _bounded_duplicates(
    values: Iterable[str],
    *,
    guard: _DeadlineGuard,
) -> list[str]:
    counts: dict[str, int] = {}
    for value in values:
        guard.check("timetable factorized reference validation timed out")
        counts[value] = counts.get(value, 0) + 1
    return sorted(value for value, count in counts.items() if count > 1)


def _has_ambiguous_values(
    values_by_key: Mapping[Any, set[int]],
    *,
    guard: _DeadlineGuard,
) -> bool:
    for values in values_by_key.values():
        guard.check("timetable factorized reference validation timed out")
        if len(values) > 1:
            return True
    return False


def _max_breaks_parameter_errors(
    distribution_type: str,
    parameters: tuple[int, ...],
) -> tuple[str, ...]:
    if len(parameters) != 2:
        return ()
    maximum_breaks, maximum_gap = parameters
    errors: list[str] = []
    if maximum_breaks > _CP_SAT_INT64_MAX - 1:
        errors.append(
            f"distribution {distribution_type} maximum breaks exceed the "
            "CP-SAT int64-safe bound"
        )
    if maximum_gap > _CP_SAT_INT64_MAX - 2:
        errors.append(
            f"distribution {distribution_type} maximum gap exceeds the "
            "CP-SAT int64-safe bound"
        )
    return tuple(errors)


def _validate_problem_references_bounded(
    problem: ITC2019Problem,
    *,
    deadline: float,
) -> tuple[list[str], tuple[ITC2019Class, ...]]:
    """Validate references while keeping admission responsive to its deadline."""

    guard = _DeadlineGuard(deadline)
    guard.check("timetable factorized reference validation timed out", force=True)
    errors: list[str] = []
    room_ids: set[str] = set()
    for room in problem.rooms:
        guard.check("timetable factorized reference validation timed out")
        room_ids.add(room.id)
    course_ids: set[str] = set()
    classes: list[ITC2019Class] = []
    class_context: dict[str, tuple[str, str, str, ITC2019Class]] = {}
    for course in problem.courses:
        guard.check("timetable factorized reference validation timed out")
        course_ids.add(course.id)
        for configuration in course.configurations:
            guard.check("timetable factorized reference validation timed out")
            for subpart in configuration.subparts:
                guard.check("timetable factorized reference validation timed out")
                for klass in subpart.classes:
                    guard.check("timetable factorized reference validation timed out")
                    classes.append(klass)
                    class_context[klass.id] = (
                        course.id,
                        configuration.id,
                        subpart.id,
                        klass,
                    )
    class_tuple = tuple(classes)
    class_ids: set[str] = set()
    for klass in class_tuple:
        guard.check("timetable factorized reference validation timed out")
        class_ids.add(klass.id)

    for name, value in (
        ("time", problem.optimization.time),
        ("room", problem.optimization.room),
        ("distribution", problem.optimization.distribution),
        ("student", problem.optimization.student),
    ):
        guard.check("timetable factorized reference validation timed out")
        if value < 0:
            errors.append(f"optimization weight {name} is negative")

    for label, values in (
        ("room", (room.id for room in problem.rooms)),
        ("course", (course.id for course in problem.courses)),
        ("class", (klass.id for klass in class_tuple)),
        ("student", (student.id for student in problem.students)),
    ):
        duplicate_ids = _bounded_duplicates(values, guard=guard)
        if duplicate_ids:
            errors.append(f"duplicate {label} ids: {', '.join(duplicate_ids)}")

    for room in problem.rooms:
        guard.check("timetable factorized reference validation timed out")
        travel_values: dict[str, set[int]] = defaultdict(set)
        for travel in room.travel:
            guard.check("timetable factorized reference validation timed out")
            travel_values[travel.room_id].add(travel.value)
            if travel.room_id not in room_ids:
                errors.append(
                    f"room {room.id} travels to unknown room {travel.room_id}"
                )
            if travel.value < 0:
                errors.append(f"room {room.id} has negative travel value")
        if _has_ambiguous_values(travel_values, guard=guard):
            errors.append(f"room {room.id} has ambiguous travel values")
        for unavailable in room.unavailable:
            guard.check("timetable factorized reference validation timed out")
            if unavailable.start < 0 or (
                unavailable.start + unavailable.length > problem.slots_per_day
            ):
                errors.append(f"room {room.id} has unavailability outside the day")

    for klass in class_tuple:
        guard.check("timetable factorized reference validation timed out")
        if not klass.time_options:
            errors.append(f"class {klass.id} has no time options")
        if klass.room_required and not klass.room_options:
            errors.append(f"class {klass.id} requires a room but has no room options")
        room_costs: dict[str, set[int]] = defaultdict(set)
        for room_option in klass.room_options:
            guard.check("timetable factorized reference validation timed out")
            if room_option.room_id not in room_ids:
                errors.append(
                    f"class {klass.id} references unknown room {room_option.room_id}"
                )
            if room_option.penalty < 0:
                errors.append(f"class {klass.id} has a negative room penalty")
            room_costs[room_option.room_id].add(room_option.penalty)
        if _has_ambiguous_values(room_costs, guard=guard):
            errors.append(f"class {klass.id} has ambiguous room penalties")
        time_lengths: dict[tuple[str, int, str], set[int]] = defaultdict(set)
        for time_option in klass.time_options:
            guard.check("timetable factorized reference validation timed out")
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
        if _has_ambiguous_values(time_lengths, guard=guard):
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
        guard.check("timetable factorized reference validation timed out")
        try:
            base, parameters = _distribution_spec(distribution.type)
        except ValueError as exc:
            errors.append(str(exc))
        else:
            if base == "MaxBreaks":
                errors.extend(
                    _max_breaks_parameter_errors(distribution.type, parameters)
                )
        if distribution.penalty < 0:
            errors.append(f"distribution {distribution.type} has a negative penalty")
        for class_id in distribution.class_ids:
            guard.check("timetable factorized reference validation timed out")
            if class_id not in class_ids:
                errors.append(
                    f"distribution {distribution.type} references unknown class {class_id}"
                )

    for student in problem.students:
        guard.check("timetable factorized reference validation timed out")
        duplicate_requests = _bounded_duplicates(student.course_ids, guard=guard)
        if duplicate_requests:
            errors.append(
                f"student {student.id} has duplicate requests: "
                + ", ".join(duplicate_requests)
            )
        for course_id in student.course_ids:
            guard.check("timetable factorized reference validation timed out")
            if course_id not in course_ids:
                errors.append(
                    f"student {student.id} requests unknown course {course_id}"
                )

    for course in problem.courses:
        guard.check("timetable factorized reference validation timed out")
        if not course.configurations:
            errors.append(f"course {course.id} has no configurations")
        duplicate_configurations = _bounded_duplicates(
            (configuration.id for configuration in course.configurations),
            guard=guard,
        )
        if duplicate_configurations:
            errors.append(
                f"course {course.id} has duplicate configuration ids: "
                + ", ".join(duplicate_configurations)
            )
        for configuration in course.configurations:
            guard.check("timetable factorized reference validation timed out")
            if not configuration.subparts:
                errors.append(
                    f"configuration {configuration.id} of course {course.id} has no subparts"
                )
            duplicate_subparts = _bounded_duplicates(
                (subpart.id for subpart in configuration.subparts),
                guard=guard,
            )
            if duplicate_subparts:
                errors.append(
                    f"configuration {configuration.id} has duplicate subpart ids: "
                    + ", ".join(duplicate_subparts)
                )
            for subpart in configuration.subparts:
                guard.check("timetable factorized reference validation timed out")
                if not subpart.classes:
                    errors.append(f"subpart {subpart.id} has no classes")
    guard.check("timetable factorized reference validation timed out", force=True)
    return errors, class_tuple


def _build_distribution_admission(
    problem: ITC2019Problem,
    *,
    deadline: float,
) -> _DistributionAdmission:
    guard = _DeadlineGuard(deadline)
    guard.check("timetable factorized distribution admission timed out", force=True)
    pair_requests: list[_RequiredDistributionRequest] = []
    group_requests: list[_RequiredDistributionRequest] = []
    relations = 0
    soft_distributions = 0
    unsupported: list[str] = []
    for index, distribution in enumerate(problem.distributions, start=1):
        guard.check("timetable factorized distribution admission timed out")
        try:
            base, _parameters = _distribution_spec(distribution.type)
        except ValueError as exc:
            unsupported.append(f"distribution {index}: {exc}")
            continue
        if not distribution.required:
            # Soft distributions affect quality, not feasibility. This isolated
            # model intentionally excludes them and reports the exclusion in
            # telemetry; final scoring remains the authority for their cost.
            if distribution.penalty > 0:
                soft_distributions += 1
            continue
        class_ids: list[str] = []
        seen: set[str] = set()
        for class_id in distribution.class_ids:
            guard.check("timetable factorized distribution admission timed out")
            if class_id not in seen:
                seen.add(class_id)
                class_ids.append(class_id)
        request = _RequiredDistributionRequest(
            distribution_index=index,
            base=base,
            parameters=_parameters,
            class_ids=tuple(class_ids),
        )
        if base in SUPPORTED_REQUIRED_GROUP_DISTRIBUTIONS:
            group_requests.append(request)
            continue
        if base not in SUPPORTED_REQUIRED_PAIR_DISTRIBUTIONS:
            unsupported.append(
                f"distribution {index} {distribution.type}: only required "
                "pairwise distributions and MaxBreaks are supported"
            )
            continue
        pair_requests.append(request)
        if base != "SameAttendees":
            relations += len(class_ids) * (len(class_ids) - 1) // 2
    guard.check("timetable factorized distribution admission timed out", force=True)
    return _DistributionAdmission(
        pair_requests=tuple(pair_requests),
        group_requests=tuple(group_requests),
        non_same_attendees_relations=relations,
        soft_distributions=soft_distributions,
        unsupported=tuple(unsupported),
    )


def _required_group_cell_count(
    problem: ITC2019Problem,
    domains: _FactorizedDomains,
    requests: Sequence[_RequiredDistributionRequest],
    *,
    maximum_cells: int,
    deadline: float,
) -> int:
    guard = _DeadlineGuard(deadline)
    guard.check("timetable factorized group admission timed out", force=True)
    total = 0
    for request in requests:
        guard.check("timetable factorized group admission timed out", force=True)
        remaining = max(0, maximum_cells - total)
        estimate = _group_distribution_estimate(
            problem,
            domains.times,
            base=request.base,
            parameters=request.parameters,
            class_ids=request.class_ids,
            required=True,
            maximum_cells=remaining,
            deadline=deadline,
        )
        total += estimate.cells
        if total > maximum_cells:
            return total
    guard.check("timetable factorized group admission timed out", force=True)
    return total


def _ordered_same_attendees_relations(
    requests: Sequence[_RequiredDistributionRequest],
    *,
    deadline: float,
) -> tuple[tuple[str, str], ...]:
    guard = _DeadlineGuard(deadline)
    guard.check("timetable factorized room-pair admission timed out", force=True)
    relations: list[tuple[str, str]] = []
    for request in requests:
        guard.check("timetable factorized room-pair admission timed out", force=True)
        if request.base != "SameAttendees":
            continue
        for first_id, second_id in combinations(request.class_ids, 2):
            guard.check("timetable factorized room-pair admission timed out")
            relations.append((first_id, second_id))
    guard.check("timetable factorized room-pair admission timed out", force=True)
    return tuple(relations)


def _travel_order_equivalent(
    first_rooms: Sequence[ITC2019RoomOption | None],
    second_rooms: Sequence[ITC2019RoomOption | None],
    travel: Mapping[tuple[str, str], int],
    *,
    max_evaluations: int,
    deadline: float,
) -> tuple[bool, int]:
    evaluations = len(first_rooms) * len(second_rooms)
    if evaluations > max_evaluations:
        return False, 0
    guard = _DeadlineGuard(deadline)
    guard.check("timetable factorized travel-equivalence proof timed out", force=True)
    scanned = 0
    for first in first_rooms:
        for second in second_rooms:
            forward = _travel_distance(first, second, travel, reverse=False)
            backward = _travel_distance(second, first, travel, reverse=False)
            scanned += 1
            if forward != backward:
                return False, scanned
            guard.check("timetable factorized travel-equivalence proof timed out")
    guard.check("timetable factorized travel-equivalence proof timed out", force=True)
    return True, scanned


def _prepare_same_attendees_relations(
    problem: ITC2019Problem,
    domains: _FactorizedDomains,
    requests: Sequence[_RequiredDistributionRequest],
    *,
    max_evaluations_per_pair: int,
    deadline: float,
) -> _PreparedSameAttendeesRelations:
    raw_relations = _ordered_same_attendees_relations(
        requests,
        deadline=deadline,
    )
    travel = _travel_values(problem)
    seen_ordered: set[tuple[str, str]] = set()
    prepared: list[tuple[str, str]] = []
    prepared_set: set[tuple[str, str]] = set()
    exact_duplicates = 0
    reversed_equivalent = 0
    equivalence_evaluations = 0
    guard = _DeadlineGuard(deadline)
    guard.check("timetable factorized relation preparation timed out", force=True)
    for relation in raw_relations:
        guard.check("timetable factorized relation preparation timed out", force=True)
        if relation in seen_ordered:
            exact_duplicates += 1
            continue
        seen_ordered.add(relation)
        first_id, second_id = relation
        reverse = (second_id, first_id)
        if reverse in prepared_set:
            equivalent, scanned = _travel_order_equivalent(
                domains.rooms[first_id],
                domains.rooms[second_id],
                travel,
                max_evaluations=max_evaluations_per_pair,
                deadline=deadline,
            )
            equivalence_evaluations += scanned
            if equivalent:
                reversed_equivalent += 1
                continue
        prepared.append(relation)
        prepared_set.add(relation)
    guard.check("timetable factorized relation preparation timed out", force=True)
    return _PreparedSameAttendeesRelations(
        relations=tuple(prepared),
        raw_ordered_relations=len(raw_relations),
        exact_ordered_duplicates_removed=exact_duplicates,
        reversed_equivalent_relations_removed=reversed_equivalent,
        equivalence_evaluations=equivalence_evaluations,
    )


def _same_attendees_room_preflight(
    problem: ITC2019Problem,
    domains: _FactorizedDomains,
    pairs: Sequence[tuple[str, str]],
    *,
    max_total_evaluations: int,
    max_evaluations_per_pair: int,
    max_sparse_constraints: int,
    deadline: float,
) -> _RoomPairPreflight:
    guard = _DeadlineGuard(deadline)
    guard.check("timetable factorized room-pair admission timed out", force=True)
    travel = _travel_values(problem)
    evaluations = 0
    per_pair_rejection: str | None = None
    for first_id, second_id in pairs:
        guard.check("timetable factorized room-pair admission timed out")
        pair_evaluations = len(domains.rooms[first_id]) * len(domains.rooms[second_id])
        evaluations += pair_evaluations
        if pair_evaluations > max_evaluations_per_pair and per_pair_rejection is None:
            per_pair_rejection = (
                f"SameAttendees room pair {first_id}/{second_id} evaluations "
                f"exceed {max_evaluations_per_pair}"
            )
    if per_pair_rejection is not None:
        return _RoomPairPreflight(
            evaluations=evaluations,
            rejection=per_pair_rejection,
        )
    if evaluations > max_total_evaluations:
        return _RoomPairPreflight(
            evaluations=evaluations,
            rejection=(
                f"SameAttendees room-pair evaluations exceed {max_total_evaluations}"
            ),
        )

    sparse_constraints = 0
    for first_id, second_id in pairs:
        guard.check("timetable factorized room-pair admission timed out", force=True)
        sparse_constraints += _travel_exception_count(
            domains.rooms[first_id],
            domains.rooms[second_id],
            travel,
            reverse=False,
            deadline=deadline,
            max_evaluations=max_evaluations_per_pair,
            label=f"SameAttendees room pair {first_id}/{second_id}",
        )
        if sparse_constraints > max_sparse_constraints:
            return _RoomPairPreflight(
                evaluations=evaluations,
                sparse_constraints=sparse_constraints,
                rejection=(
                    "SameAttendees exact sparse room constraints exceed "
                    f"{max_sparse_constraints}"
                ),
            )
    guard.check("timetable factorized room-pair admission timed out", force=True)
    return _RoomPairPreflight(
        evaluations=evaluations,
        sparse_constraints=sparse_constraints,
    )


def _build_bounded_factorized_domains(
    classes: Sequence[ITC2019Class],
    *,
    deadline: float,
    max_domain_values: int,
) -> _FactorizedDomains:
    """Canonicalize domains without retaining more than the admitted cap."""

    guard = _DeadlineGuard(deadline)
    guard.check("timetable factorized domain construction timed out", force=True)
    times: dict[str, tuple[ITC2019TimeOption, ...]] = {}
    rooms: dict[str, tuple[ITC2019RoomOption | None, ...]] = {}
    retained_values = 0

    def claim_value() -> None:
        nonlocal retained_values
        if retained_values >= max_domain_values:
            raise _EncodingScaleExceeded(
                f"factorized domain values exceed {max_domain_values}"
            )
        retained_values += 1

    for klass in classes:
        guard.check("timetable factorized domain construction timed out")
        unique_times: dict[tuple[str, int, int, str], ITC2019TimeOption] = {}
        for option in klass.time_options:
            guard.check("timetable factorized domain construction timed out")
            key = (option.days, option.start, option.length, option.weeks)
            current = unique_times.get(key)
            if current is None:
                claim_value()
                unique_times[key] = option
            elif option.penalty < current.penalty:
                unique_times[key] = option
        class_times = tuple(unique_times.values())
        if not class_times:
            raise _EncodingInfeasible(
                f"class {klass.id} has no factorized time or room domain"
            )
        times[klass.id] = class_times

        if klass.room_required:
            unique_rooms: dict[str, ITC2019RoomOption] = {}
            for option in klass.room_options:
                guard.check("timetable factorized domain construction timed out")
                current = unique_rooms.get(option.room_id)
                if current is None:
                    claim_value()
                    unique_rooms[option.room_id] = option
                elif option.penalty < current.penalty:
                    unique_rooms[option.room_id] = option
            class_rooms: tuple[ITC2019RoomOption | None, ...] = tuple(
                unique_rooms.values()
            )
        else:
            claim_value()
            class_rooms = (None,)
        if not class_rooms:
            raise _EncodingInfeasible(
                f"class {klass.id} has no factorized time or room domain"
            )
        rooms[klass.id] = class_rooms
    guard.check("timetable factorized domain construction timed out", force=True)
    return _FactorizedDomains(times=times, rooms=rooms)


def estimate_itc2019_timetable_same_attendees_workload(
    problem: ITC2019Problem,
    *,
    time_limit_seconds: float = 30.0,
    limits: ITC2019TimetableFactorizedLimits | None = None,
) -> ITC2019SameAttendeesWorkload:
    """Prepare and count SameAttendees work without constructing a CP-SAT model."""

    try:
        normalized_time_limit = float(time_limit_seconds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("time_limit_seconds must be a finite positive number") from exc
    if not math.isfinite(normalized_time_limit) or normalized_time_limit <= 0:
        raise ValueError("time_limit_seconds must be a finite positive number")
    limits = limits or ITC2019TimetableFactorizedLimits()
    limits.validate()
    deadline = time.monotonic() + normalized_time_limit
    timetable_problem = replace(problem, students=())
    problem_errors, classes = _validate_problem_references_bounded(
        timetable_problem,
        deadline=deadline,
    )
    if problem_errors:
        raise ValueError("; ".join(problem_errors))
    admission = _build_distribution_admission(
        timetable_problem,
        deadline=deadline,
    )
    if admission.unsupported:
        raise ValueError("; ".join(admission.unsupported))
    domains = _build_bounded_factorized_domains(
        classes,
        deadline=deadline,
        max_domain_values=limits.max_domain_values,
    )
    prepared = _prepare_same_attendees_relations(
        timetable_problem,
        domains,
        admission.pair_requests,
        max_evaluations_per_pair=limits.max_room_pair_evaluations_per_pair,
        deadline=deadline,
    )
    preflight = _same_attendees_room_preflight(
        timetable_problem,
        domains,
        prepared.relations,
        max_total_evaluations=limits.max_room_pair_evaluations,
        max_evaluations_per_pair=limits.max_room_pair_evaluations_per_pair,
        max_sparse_constraints=limits.max_sparse_room_constraints,
        deadline=deadline,
    )
    return ITC2019SameAttendeesWorkload(
        prepared_ordered_relations=prepared.relations,
        raw_ordered_relations=prepared.raw_ordered_relations,
        exact_ordered_duplicates_removed=(prepared.exact_ordered_duplicates_removed),
        reversed_equivalent_relations_removed=(
            prepared.reversed_equivalent_relations_removed
        ),
        equivalence_evaluations=prepared.equivalence_evaluations,
        room_pair_evaluations=preflight.evaluations,
        exact_sparse_constraints=preflight.sparse_constraints,
        rejection=preflight.rejection,
    )


def _add_choice_variables(
    *,
    problem: ITC2019Problem,
    domains: _FactorizedDomains,
    model: cp_model.CpModel,
    deadline: float,
) -> tuple[
    dict[str, cp_model.IntVar],
    dict[str, cp_model.IntVar],
    dict[str, cp_model.IntVar],
    dict[str, tuple[cp_model.IntVar, ...]],
    dict[str, tuple[cp_model.IntVar, ...]],
]:
    time_choices: dict[str, cp_model.IntVar] = {}
    room_choices: dict[str, cp_model.IntVar] = {}
    room_assignments: dict[str, cp_model.IntVar] = {}
    time_selectors: dict[str, tuple[cp_model.IntVar, ...]] = {}
    room_selectors: dict[str, tuple[cp_model.IntVar, ...]] = {}
    global_room_codes = {room.id: index for index, room in enumerate(problem.rooms)}
    no_room_code = len(global_room_codes)

    for class_index, klass in enumerate(problem.classes):
        class_times = domains.times[klass.id]
        class_rooms = domains.rooms[klass.id]
        time_literals = tuple(
            model.new_bool_var(f"class_{klass.id}_time_{index}")
            for index in range(len(class_times))
        )
        room_literals = tuple(
            model.new_bool_var(f"class_{klass.id}_room_{index}")
            for index in range(len(class_rooms))
        )
        time_selectors[klass.id] = time_literals
        room_selectors[klass.id] = room_literals
        model.add_exactly_one(time_literals)
        model.add_exactly_one(room_literals)

        time_choice = model.new_int_var(
            0,
            len(class_times) - 1,
            f"class_{klass.id}_time_choice",
        )
        room_choice = model.new_int_var(
            0,
            len(class_rooms) - 1,
            f"class_{klass.id}_room_choice",
        )
        time_choices[klass.id] = time_choice
        room_choices[klass.id] = room_choice
        for index, literal in enumerate(time_literals):
            model.add(time_choice == index).only_enforce_if(literal)
        for index, literal in enumerate(room_literals):
            model.add(room_choice == index).only_enforce_if(literal)

        room_codes = [
            global_room_codes[option.room_id] if option is not None else no_room_code
            for option in class_rooms
        ]
        room_assignment = model.new_int_var_from_domain(
            cp_model.Domain.from_values(room_codes),
            f"class_{klass.id}_global_room",
        )
        model.add_element(room_choice, room_codes, room_assignment)
        room_assignments[klass.id] = room_assignment

        if class_index % 256 == 0 and time.monotonic() >= deadline:
            raise TimeoutError("timetable factorized variable encoding timed out")

    return (
        time_choices,
        room_choices,
        room_assignments,
        time_selectors,
        room_selectors,
    )


def _add_required_pair_distributions(
    *,
    requests: Sequence[_RequiredDistributionRequest],
    same_attendees_relations: Sequence[tuple[str, str]],
    model: cp_model.CpModel,
    encoder: _PairEncoder,
    deadline: float,
) -> None:
    guard = _DeadlineGuard(deadline)
    guard.check("timetable factorized distribution encoding timed out", force=True)
    for request in requests:
        guard.check("timetable factorized distribution encoding timed out", force=True)
        if request.base == "SameAttendees":
            continue
        for first_id, second_id in combinations(request.class_ids, 2):
            guard.check("timetable factorized distribution encoding timed out")
            key = f"distribution_{request.distribution_index}_{request.base}"
            if request.base in _TIME_PAIR_DISTRIBUTIONS:
                violation = encoder.time_distribution_violation(
                    first_id,
                    second_id,
                    request.base,
                    request.parameters,
                    key,
                )
            elif request.base in _ROOM_PAIR_DISTRIBUTIONS:
                violation = encoder.room_distribution_violation(
                    first_id,
                    second_id,
                    request.base,
                    key,
                )
            else:  # pragma: no cover - admission rejects this before construction
                raise ValueError(f"unsupported required distribution {request.base!r}")
            model.add(violation.variable == 0)
    for first_id, second_id in same_attendees_relations:
        guard.check("timetable factorized distribution encoding timed out", force=True)
        violation = encoder.same_attendees_violation(first_id, second_id)
        model.add(violation.variable == 0)
    guard.check("timetable factorized distribution encoding timed out", force=True)


def _add_required_group_distributions(
    *,
    problem: ITC2019Problem,
    requests: Sequence[_RequiredDistributionRequest],
    model: cp_model.CpModel,
    domains: _FactorizedDomains,
    time_selectors: Mapping[str, tuple[cp_model.IntVar, ...]],
    encoder: _PairEncoder,
    maximum_cells: int,
    deadline: float,
) -> None:
    guard = _DeadlineGuard(deadline)
    guard.check("timetable factorized group encoding timed out", force=True)
    for request in requests:
        guard.check("timetable factorized group encoding timed out", force=True)
        _add_group_distribution(
            problem=problem,
            model=model,
            domains=domains,
            time_selectors=time_selectors,
            encoder=encoder,
            objective_terms=[],
            distribution_index=request.distribution_index,
            base=request.base,
            parameters=request.parameters,
            class_ids=request.class_ids,
            required=True,
            penalty=0,
            maximum_cells=maximum_cells,
            deadline=deadline,
        )
    guard.check("timetable factorized group encoding timed out", force=True)


def build_itc2019_timetable_factorized(
    problem: ITC2019Problem,
    *,
    time_limit_seconds: float = 30.0,
    limits: ITC2019TimetableFactorizedLimits | None = None,
    include_proto_fingerprint: bool = False,
) -> ITC2019TimetableFactorizedResult:
    """Build the PU-oriented timetable-only feasibility model without solving it.

    Student records are stripped before reference validation and never reach model
    construction.  Unsupported active semantics are rejected before any CP-SAT
    variables are created.
    """

    try:
        normalized_time_limit = float(time_limit_seconds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("time_limit_seconds must be a finite positive number") from exc
    if not math.isfinite(normalized_time_limit) or normalized_time_limit <= 0:
        raise ValueError("time_limit_seconds must be a finite positive number")
    limits = limits or ITC2019TimetableFactorizedLimits()
    limits.validate()

    deadline = time.monotonic() + normalized_time_limit
    phases: list[tuple[str, float]] = []
    phase_started = time.monotonic()
    timetable_problem = replace(problem, students=())
    required_pair_distributions = 0
    required_pair_relations = 0
    required_group_distributions = 0
    required_group_cells = 0
    source_soft_distributions_excluded = 0
    admission = _DistributionAdmission()
    classes: tuple[ITC2019Class, ...] = ()
    try:
        problem_errors, classes = _validate_problem_references_bounded(
            timetable_problem,
            deadline=deadline,
        )
        admission = _build_distribution_admission(
            timetable_problem,
            deadline=deadline,
        )
        required_pair_distributions = len(admission.pair_requests)
        required_pair_relations = admission.non_same_attendees_relations
        required_group_distributions = len(admission.group_requests)
        source_soft_distributions_excluded = admission.soft_distributions
    except TimeoutError:
        _finish_phase(phases, "admission", phase_started)
        return _failure(
            problem,
            status="DEADLINE_EXCEEDED",
            phases=phases,
            class_count=len(classes),
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
        )
    phase_started = _finish_phase(phases, "admission", phase_started)
    class_count = len(classes)

    if problem_errors:
        return _failure(
            problem,
            status="INVALID_PROBLEM",
            phases=phases,
            class_count=class_count,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
            validation_errors=problem_errors,
        )
    if admission.unsupported:
        return _failure(
            problem,
            status="UNSUPPORTED_SEMANTICS",
            phases=phases,
            class_count=class_count,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
            unsupported_reasons=admission.unsupported,
        )
    if required_pair_relations > limits.max_required_pair_relations:
        return _failure(
            problem,
            status="UNSUPPORTED_MODEL_SCALE",
            phases=phases,
            class_count=class_count,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
            unsupported_reasons=(
                f"required pair relations exceed {limits.max_required_pair_relations}",
            ),
        )
    if time.monotonic() >= deadline:
        return _failure(
            problem,
            status="DEADLINE_EXCEEDED",
            phases=phases,
            class_count=class_count,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
        )

    try:
        domains = _build_bounded_factorized_domains(
            classes,
            deadline=deadline,
            max_domain_values=limits.max_domain_values,
        )
    except _EncodingScaleExceeded as exc:
        _finish_phase(phases, "domains", phase_started)
        return _failure(
            problem,
            status="UNSUPPORTED_MODEL_SCALE",
            phases=phases,
            class_count=class_count,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
            unsupported_reasons=(str(exc),),
        )
    except _EncodingInfeasible as exc:
        _finish_phase(phases, "domains", phase_started)
        return _failure(
            problem,
            status="INFEASIBLE_DOMAIN",
            phases=phases,
            class_count=class_count,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
            validation_errors=(str(exc),),
        )
    except TimeoutError:
        _finish_phase(phases, "domains", phase_started)
        return _failure(
            problem,
            status="DEADLINE_EXCEEDED",
            phases=phases,
            class_count=class_count,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
        )
    phase_started = _finish_phase(phases, "domains", phase_started)

    try:
        prepared_same_attendees = _prepare_same_attendees_relations(
            timetable_problem,
            domains,
            admission.pair_requests,
            max_evaluations_per_pair=(limits.max_room_pair_evaluations_per_pair),
            deadline=deadline,
        )
    except TimeoutError:
        return _failure(
            problem,
            status="DEADLINE_EXCEEDED",
            phases=phases,
            class_count=class_count,
            domains=domains,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
        )
    required_pair_relations = admission.non_same_attendees_relations + len(
        prepared_same_attendees.relations
    )
    if required_pair_relations > limits.max_required_pair_relations:
        return _failure(
            problem,
            status="UNSUPPORTED_MODEL_SCALE",
            phases=phases,
            class_count=class_count,
            domains=domains,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
            unsupported_reasons=(
                f"required pair relations exceed {limits.max_required_pair_relations}",
            ),
        )

    try:
        required_group_cells = _required_group_cell_count(
            timetable_problem,
            domains,
            admission.group_requests,
            maximum_cells=limits.max_required_group_cells,
            deadline=deadline,
        )
    except TimeoutError:
        return _failure(
            problem,
            status="DEADLINE_EXCEEDED",
            phases=phases,
            class_count=class_count,
            domains=domains,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
        )
    if required_group_cells > limits.max_required_group_cells:
        return _failure(
            problem,
            status="UNSUPPORTED_MODEL_SCALE",
            phases=phases,
            class_count=class_count,
            domains=domains,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
            required_group_cells=required_group_cells,
            unsupported_reasons=(
                f"required group cells exceed {limits.max_required_group_cells}",
            ),
        )

    try:
        room_pair_preflight = _same_attendees_room_preflight(
            timetable_problem,
            domains,
            prepared_same_attendees.relations,
            max_total_evaluations=limits.max_room_pair_evaluations,
            max_evaluations_per_pair=(limits.max_room_pair_evaluations_per_pair),
            max_sparse_constraints=limits.max_sparse_room_constraints,
            deadline=deadline,
        )
    except TimeoutError:
        return _failure(
            problem,
            status="DEADLINE_EXCEEDED",
            phases=phases,
            class_count=class_count,
            domains=domains,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
            required_group_cells=required_group_cells,
        )
    room_pair_evaluations = room_pair_preflight.evaluations
    if room_pair_preflight.rejection is not None:
        return _failure(
            problem,
            status="UNSUPPORTED_MODEL_SCALE",
            phases=phases,
            class_count=class_count,
            domains=domains,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
            required_group_cells=required_group_cells,
            room_pair_evaluations=room_pair_evaluations,
            sparse_room_constraints=room_pair_preflight.sparse_constraints,
            unsupported_reasons=(room_pair_preflight.rejection,),
        )

    model = cp_model.CpModel()
    sparse_room_budget = _SparseRoomBudget(limits.max_sparse_room_constraints)
    try:
        (
            time_choices,
            room_choices,
            room_assignments,
            time_selectors,
            room_selectors,
        ) = _add_choice_variables(
            problem=timetable_problem,
            domains=domains,
            model=model,
            deadline=deadline,
        )
        phase_started = _finish_phase(phases, "choice_variables", phase_started)

        encoder = _PairEncoder(
            problem=timetable_problem,
            model=model,
            domains=domains,
            time_choices=time_choices,
            time_selectors=time_selectors,
            room_assignments=room_assignments,
            room_selectors=room_selectors,
            sparse_room_budget=sparse_room_budget,
            deadline=deadline,
            max_room_pair_evaluations_per_pair=(
                limits.max_room_pair_evaluations_per_pair
            ),
        )
        _add_required_pair_distributions(
            requests=admission.pair_requests,
            same_attendees_relations=prepared_same_attendees.relations,
            model=model,
            encoder=encoder,
            deadline=deadline,
        )
        phase_started = _finish_phase(phases, "pair_distributions", phase_started)

        _add_required_group_distributions(
            problem=timetable_problem,
            requests=admission.group_requests,
            model=model,
            domains=domains,
            time_selectors=time_selectors,
            encoder=encoder,
            maximum_cells=limits.max_required_group_cells,
            deadline=deadline,
        )
        phase_started = _finish_phase(phases, "group_distributions", phase_started)

        _add_room_resources(
            problem=timetable_problem,
            domains=domains,
            model=model,
            time_selectors=time_selectors,
            room_assignments=room_assignments,
            sparse_room_budget=sparse_room_budget,
            deadline=deadline,
        )
        phase_started = _finish_phase(phases, "room_resources", phase_started)
    except _EncodingScaleExceeded as exc:
        _finish_phase(phases, "failed_phase", phase_started)
        return _failure(
            problem,
            status="UNSUPPORTED_MODEL_SCALE",
            phases=phases,
            class_count=class_count,
            domains=domains,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
            required_group_cells=required_group_cells,
            room_pair_evaluations=room_pair_evaluations,
            sparse_room_constraints=sparse_room_budget.used,
            unsupported_reasons=(str(exc),),
        )
    except TimeoutError:
        _finish_phase(phases, "failed_phase", phase_started)
        return _failure(
            problem,
            status="DEADLINE_EXCEEDED",
            phases=phases,
            class_count=class_count,
            domains=domains,
            required_pair_distributions=required_pair_distributions,
            required_pair_relations=required_pair_relations,
            required_group_distributions=required_group_distributions,
            required_group_cells=required_group_cells,
            room_pair_evaluations=room_pair_evaluations,
            sparse_room_constraints=sparse_room_budget.used,
        )

    model_proto = (
        _deterministic_model_bytes(model) if include_proto_fingerprint else None
    )
    _finish_phase(phases, "finalize_proto", phase_started)
    telemetry = _empty_telemetry(
        problem,
        phases=phases,
        class_count=class_count,
        domains=domains,
        required_pair_distributions=required_pair_distributions,
        required_pair_relations=required_pair_relations,
        required_group_distributions=required_group_distributions,
        required_group_cells=required_group_cells,
        source_soft_distributions_excluded=source_soft_distributions_excluded,
        room_pair_evaluations=room_pair_evaluations,
        sparse_room_constraints=sparse_room_budget.used,
        model=model,
        model_proto=model_proto,
    )
    return ITC2019TimetableFactorizedResult(
        status="BUILT",
        build_only=True,
        model=model,
        time_choices=time_choices,
        room_choices=room_choices,
        time_domains=domains.times,
        room_domains=domains.rooms,
        placements=(),
        telemetry=telemetry,
    )


def _validated_timetable_candidate(
    problem: ITC2019Problem,
    placements: Sequence[ITC2019ClassPlacement],
) -> tuple[str, ...]:
    timetable_problem = replace(problem, students=())
    errors = validate_itc2019_class_placements(
        timetable_problem,
        placements,
        require_complete=True,
    )
    if errors:
        return tuple(errors)
    try:
        distribution_scores = evaluate_itc2019_distributions(
            timetable_problem,
            placements,
        )
    except ValueError as exc:
        return (str(exc),)
    return tuple(
        f"required distribution {score.constraint_type} has "
        f"{score.violation_units} violation units"
        for score in distribution_scores
        if score.is_hard_violation
    )


def solve_itc2019_timetable_factorized(
    problem: ITC2019Problem,
    *,
    build_only: bool = True,
    build_time_limit_seconds: float = 30.0,
    solve_time_limit_seconds: float = 30.0,
    workers: int = 1,
    random_seed: int = 0,
    limits: ITC2019TimetableFactorizedLimits | None = None,
    include_proto_fingerprint: bool = False,
) -> ITC2019TimetableFactorizedResult:
    """Build, and optionally solve, the timetable-only feasibility prototype."""

    if workers <= 0:
        raise ValueError("workers must be positive")
    if random_seed < 0:
        raise ValueError("random_seed must be non-negative")
    if not build_only and solve_time_limit_seconds <= 0:
        raise ValueError("solve_time_limit_seconds must be positive")

    built = build_itc2019_timetable_factorized(
        problem,
        time_limit_seconds=build_time_limit_seconds,
        limits=limits,
        include_proto_fingerprint=include_proto_fingerprint,
    )
    if build_only or built.status != "BUILT" or built.model is None:
        return built

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(solve_time_limit_seconds)
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = random_seed
    solve_started = time.monotonic()
    raw_status = solver.solve(built.model)
    solver_wall = max(0.0, time.monotonic() - solve_started)
    solver_status = solver.status_name(raw_status)
    if raw_status not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        return replace(
            built,
            status=solver_status,
            build_only=False,
            solver_status=solver_status,
            solver_wall_time_seconds=solver_wall,
            conflicts=int(solver.num_conflicts),
            branches=int(solver.num_branches),
        )

    placements: list[ITC2019ClassPlacement] = []
    for klass in replace(problem, students=()).classes:
        time_option = built.time_domains[klass.id][
            int(solver.value(built.time_choices[klass.id]))
        ]
        room_option = built.room_domains[klass.id][
            int(solver.value(built.room_choices[klass.id]))
        ]
        placements.append(
            ITC2019ClassPlacement(
                class_id=klass.id,
                days=time_option.days,
                start=time_option.start,
                weeks=time_option.weeks,
                room_id=room_option.room_id if room_option is not None else None,
            )
        )

    validation_errors = _validated_timetable_candidate(problem, placements)
    if validation_errors:
        return replace(
            built,
            status="VALIDATION_FAILED",
            build_only=False,
            placements=(),
            validation_errors=validation_errors,
            solver_status=solver_status,
            solver_wall_time_seconds=solver_wall,
            conflicts=int(solver.num_conflicts),
            branches=int(solver.num_branches),
        )
    return replace(
        built,
        # This prototype is a feasibility model.  CP-SAT's OPTIMAL status only
        # means the satisfaction search completed; it is not an objective claim.
        status="FEASIBLE",
        build_only=False,
        placements=tuple(placements),
        solver_status=solver_status,
        solver_wall_time_seconds=solver_wall,
        conflicts=int(solver.num_conflicts),
        branches=int(solver.num_branches),
    )


__all__ = [
    "ITC2019TimetableFactorizedLimits",
    "ITC2019TimetableFactorizedResult",
    "ITC2019TimetableFactorizedTelemetry",
    "SUPPORTED_REQUIRED_GROUP_DISTRIBUTIONS",
    "SUPPORTED_REQUIRED_PAIR_DISTRIBUTIONS",
    "build_itc2019_timetable_factorized",
    "solve_itc2019_timetable_factorized",
]
