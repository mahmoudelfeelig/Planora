"""Immutable, lossless preprocessing for hybrid ITC-2019 search phases.

This module deliberately stops before model construction.  It canonicalizes
indistinguishable time and room choices, expands no slot-level calendars, and
retains every distribution so exact downstream phases can choose their own
encoding.  A partial checkpoint freezes time signatures only; incumbent rooms
are never promoted to fixed decisions because global room repair must remain
free to move them.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Iterable, Iterator, Literal, Mapping, Sequence, TypeAlias

from benchmarks.itc2019 import (
    AttributePairs,
    ITC2019Class,
    ITC2019ClassPlacement,
    ITC2019Distribution,
    ITC2019Problem,
    ITC2019Room,
    ITC2019RoomOption,
    ITC2019TimeOption,
    _PAIR_DISTRIBUTIONS,
    _distribution_spec,
    _merge_blocks,
    _pair_distribution_satisfied,
    _room_accepts_time,
    _travel_values,
    _validate_problem_references,
)


ITC2019TimeSignature: TypeAlias = tuple[str, int, int, str]
ITC2019IncumbentValue: TypeAlias = (
    ITC2019ClassPlacement | ITC2019TimeOption | ITC2019TimeSignature
)
ITC2019Incumbent: TypeAlias = (
    "ITC2019PartialCheckpoint"
    | Mapping[str, ITC2019IncumbentValue]
    | Sequence[ITC2019ClassPlacement]
    | None
)

_ROOM_ONLY_DISTRIBUTIONS = frozenset({"SameRoom", "DifferentRoom"})
_GROUP_DISTRIBUTIONS = frozenset(
    {"MaxDays", "MaxDayLoad", "MaxBreaks", "MaxBlock"}
)


@dataclass(frozen=True, slots=True)
class ITC2019CheckpointTime:
    """One immutable time decision in a partial checkpoint."""

    class_id: str
    signature: ITC2019TimeSignature


@dataclass(frozen=True, slots=True)
class ITC2019PartialCheckpoint:
    """Time-only incumbent state safe to freeze outside a repair frontier.

    Entries are tuples rather than a dictionary so the checkpoint is deeply
    immutable and duplicate class entries remain detectable instead of being
    silently overwritten.
    """

    times: tuple[ITC2019CheckpointTime, ...] = ()

    @classmethod
    def from_placements(
        cls,
        problem: ITC2019Problem,
        placements: Mapping[str, ITC2019ClassPlacement]
        | Sequence[ITC2019ClassPlacement],
    ) -> ITC2019PartialCheckpoint:
        """Resolve solution-format placements to canonical length-bearing times."""

        checkpoint, _room_hints = _checkpoint_from_placements(problem, placements)
        return checkpoint

    def only(self, class_ids: Iterable[str]) -> ITC2019PartialCheckpoint:
        """Return an immutable source-order-independent subset."""

        admitted = frozenset(class_ids)
        return ITC2019PartialCheckpoint(
            tuple(entry for entry in self.times if entry.class_id in admitted)
        )


@dataclass(frozen=True, slots=True)
class ITC2019Occurrence:
    """One exact recurring meeting interval."""

    week: int
    day: int
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ITC2019PreparedRoom:
    """One canonical room choice; ``None`` is the roomless sentinel."""

    room_id: str | None
    penalty: int
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True, slots=True)
class ITC2019PreparedTime:
    """One canonical time choice with compact, exact recurrence metadata."""

    signature: ITC2019TimeSignature
    penalty: int
    active_days: tuple[int, ...]
    active_weeks: tuple[int, ...]
    legal_room_ids: tuple[str | None, ...]
    source_ordinal: int
    extra_attributes: AttributePairs = ()

    @property
    def days(self) -> str:
        return self.signature[0]

    @property
    def start(self) -> int:
        return self.signature[1]

    @property
    def length(self) -> int:
        return self.signature[2]

    @property
    def weeks(self) -> str:
        return self.signature[3]

    @property
    def occurrence_count(self) -> int:
        return len(self.active_days) * len(self.active_weeks)

    def occurrences(self) -> Iterator[ITC2019Occurrence]:
        """Yield every recurring interval without storing slot-expanded sets."""

        for week in self.active_weeks:
            for day in self.active_days:
                yield ITC2019Occurrence(
                    week=week,
                    day=day,
                    start=self.start,
                    end=self.start + self.length,
                )


@dataclass(frozen=True, slots=True)
class ITC2019PreparedClass:
    """Canonical domain and hierarchy metadata for one class."""

    class_id: str
    course_id: str
    configuration_id: str
    subpart_id: str
    limit: int
    parent_id: str | None
    room_required: bool
    is_open: bool
    times: tuple[ITC2019PreparedTime, ...]
    rooms: tuple[ITC2019PreparedRoom, ...]
    incumbent_signature: ITC2019TimeSignature | None
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True, slots=True)
class ITC2019PreparedDistribution:
    """Parsed distribution metadata without dropping raw source membership."""

    source_ordinal: int
    constraint_type: str
    base: str
    parameters: tuple[int, ...]
    required: bool
    penalty: int
    raw_class_ids: tuple[str, ...]
    class_ids: tuple[str, ...]
    extra_attributes: AttributePairs = ()


@dataclass(frozen=True, slots=True)
class ITC2019PreparedContext:
    """Lossless immutable boundary shared by hybrid ITC-2019 phases."""

    problem: ITC2019Problem
    classes: tuple[ITC2019PreparedClass, ...]
    distributions: tuple[ITC2019PreparedDistribution, ...]
    open_class_ids: tuple[str, ...]
    fixed_class_ids: tuple[str, ...]
    fixed_checkpoint: ITC2019PartialCheckpoint

    def class_for(self, class_id: str) -> ITC2019PreparedClass:
        for prepared in self.classes:
            if prepared.class_id == class_id:
                return prepared
        raise KeyError(class_id)

    def checkpoint_signature(
        self, class_id: str
    ) -> ITC2019TimeSignature | None:
        for entry in self.fixed_checkpoint.times:
            if entry.class_id == class_id:
                return entry.signature
        return None


def _time_signature(option: ITC2019TimeOption) -> ITC2019TimeSignature:
    return (option.days, option.start, option.length, option.weeks)


def _check_deadline(deadline: float | None, operation: str) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError(f"ITC-2019 preprocessing timed out during {operation}")


def _iter_class_context(
    problem: ITC2019Problem,
) -> Iterator[tuple[str, str, str, ITC2019Class]]:
    for course in problem.courses:
        for configuration in course.configurations:
            for subpart in configuration.subparts:
                for klass in subpart.classes:
                    yield course.id, configuration.id, subpart.id, klass


def _canonical_times(
    klass: ITC2019Class,
    *,
    deadline: float | None,
) -> tuple[tuple[int, ITC2019TimeOption], ...]:
    chosen: dict[ITC2019TimeSignature, tuple[int, ITC2019TimeOption]] = {}
    for ordinal, option in enumerate(klass.time_options):
        signature = _time_signature(option)
        incumbent = chosen.get(signature)
        if incumbent is None or option.penalty < incumbent[1].penalty:
            chosen[signature] = (ordinal, option)
        if ordinal % 1024 == 0:
            _check_deadline(deadline, "time canonicalization")
    return tuple(chosen.values())


def _canonical_rooms(klass: ITC2019Class) -> tuple[ITC2019PreparedRoom, ...]:
    if not klass.room_required:
        return (ITC2019PreparedRoom(room_id=None, penalty=0),)
    chosen: dict[str, ITC2019RoomOption] = {}
    for option in klass.room_options:
        incumbent = chosen.get(option.room_id)
        if incumbent is None or option.penalty < incumbent.penalty:
            chosen[option.room_id] = option
    return tuple(
        ITC2019PreparedRoom(
            room_id=option.room_id,
            penalty=option.penalty,
            extra_attributes=option.extra_attributes,
        )
        for option in chosen.values()
    )


def _legal_room_ids(
    klass: ITC2019Class,
    option: ITC2019TimeOption,
    rooms_by_id: Mapping[str, ITC2019Room],
) -> tuple[str | None, ...]:
    """Return every locally legal room without fixing a room decision."""

    if not klass.room_required:
        return (None,)
    room_ids = tuple(dict.fromkeys(value.room_id for value in klass.room_options))
    return tuple(
        room_id
        for room_id in room_ids
        if _room_accepts_time(rooms_by_id[room_id], option)
    )


def _prepared_time(
    source_ordinal: int,
    option: ITC2019TimeOption,
    rooms: tuple[ITC2019PreparedRoom, ...],
    rooms_by_id: Mapping[str, ITC2019Room],
) -> ITC2019PreparedTime:
    legal_rooms = tuple(
        room.room_id
        for room in rooms
        if room.room_id is None
        or _room_accepts_time(rooms_by_id[room.room_id], option)
    )
    return ITC2019PreparedTime(
        signature=_time_signature(option),
        penalty=option.penalty,
        active_days=tuple(
            day for day, active in enumerate(option.days) if active == "1"
        ),
        active_weeks=tuple(
            week for week, active in enumerate(option.weeks) if active == "1"
        ),
        legal_room_ids=legal_rooms,
        source_ordinal=source_ordinal,
        extra_attributes=option.extra_attributes,
    )


def _group_violation_units_with_deadline(
    problem: ITC2019Problem,
    base: str,
    parameters: tuple[int, ...],
    class_ids: Sequence[str],
    resolved: Mapping[str, ITC2019TimeOption],
    *,
    deadline: float | None,
) -> int:
    """Mirror the official grouped evaluator with interruptible inner loops."""

    work = 0

    def tick() -> None:
        nonlocal work
        work += 1
        if work % 128 == 0:
            _check_deadline(deadline, "checkpoint grouped distribution validation")

    if base == "MaxDays":
        (maximum_days,) = parameters
        used_days: set[int] = set()
        for class_id in class_ids:
            for day, active in enumerate(resolved[class_id].days):
                if active == "1":
                    used_days.add(day)
                tick()
        _check_deadline(deadline, "checkpoint grouped distribution validation")
        return max(len(used_days) - maximum_days, 0)

    if base == "MaxDayLoad":
        (maximum_load,) = parameters
        total_excess = 0
        for day in range(problem.nr_days):
            for week in range(problem.nr_weeks):
                load = 0
                for class_id in class_ids:
                    option = resolved[class_id]
                    if option.days[day] == "1" and option.weeks[week] == "1":
                        load += option.length
                    tick()
                total_excess += max(load - maximum_load, 0)
        _check_deadline(deadline, "checkpoint grouped distribution validation")
        return total_excess

    if base in {"MaxBreaks", "MaxBlock"}:
        first_parameter, maximum_gap = parameters
        total_excess = 0
        for day in range(problem.nr_days):
            for week in range(problem.nr_weeks):
                intervals: list[tuple[int, int]] = []
                for class_id in class_ids:
                    option = resolved[class_id]
                    if option.days[day] == "1" and option.weeks[week] == "1":
                        intervals.append(
                            (option.start, option.start + option.length)
                        )
                    tick()
                blocks = _merge_blocks(intervals, maximum_gap)
                if base == "MaxBreaks":
                    total_excess += max(len(blocks) - (first_parameter + 1), 0)
                else:
                    total_excess += sum(
                        members >= 2 and end - start > first_parameter
                        for start, end, members in blocks
                    )
                tick()
        _check_deadline(deadline, "checkpoint grouped distribution validation")
        return total_excess

    raise ValueError(f"Unsupported grouped ITC-2019 distribution {base!r}")


def _checkpoint_from_placements(
    problem: ITC2019Problem,
    placements: Mapping[str, ITC2019ClassPlacement]
    | Sequence[ITC2019ClassPlacement],
) -> tuple[ITC2019PartialCheckpoint, tuple[tuple[str, str | None], ...]]:
    if isinstance(placements, Mapping):
        source = []
        for class_id, placement in placements.items():
            if str(class_id) != placement.class_id:
                raise ValueError(
                    f"incumbent key {class_id!r} does not match class id "
                    f"{placement.class_id!r}"
                )
            source.append(placement)
    else:
        source = list(placements)

    classes = {klass.id: klass for klass in problem.classes}
    times: list[ITC2019CheckpointTime] = []
    room_hints: list[tuple[str, str | None]] = []
    for placement in source:
        klass = classes.get(placement.class_id)
        if klass is None:
            # Preserve the unknown id so the public validator returns one
            # deterministic diagnostic instead of failing during conversion.
            signature = (placement.days, placement.start, -1, placement.weeks)
        else:
            candidates = tuple(
                option
                for option in klass.time_options
                if option.days == placement.days
                and option.start == placement.start
                and option.weeks == placement.weeks
            )
            if not candidates:
                signature = (placement.days, placement.start, -1, placement.weeks)
            else:
                option = min(candidates, key=lambda value: value.penalty)
                signature = _time_signature(option)
        times.append(ITC2019CheckpointTime(placement.class_id, signature))
        room_hints.append((placement.class_id, placement.room_id))
    return ITC2019PartialCheckpoint(tuple(times)), tuple(room_hints)


def _coerce_incumbent(
    problem: ITC2019Problem,
    incumbent: ITC2019Incumbent,
) -> tuple[ITC2019PartialCheckpoint, tuple[tuple[str, str | None], ...]]:
    if incumbent is None:
        return ITC2019PartialCheckpoint(), ()
    if isinstance(incumbent, ITC2019PartialCheckpoint):
        return incumbent, ()
    if isinstance(incumbent, Mapping):
        if all(isinstance(value, ITC2019ClassPlacement) for value in incumbent.values()):
            return _checkpoint_from_placements(problem, incumbent)  # type: ignore[arg-type]
        entries: list[ITC2019CheckpointTime] = []
        for class_id, value in incumbent.items():
            if isinstance(value, ITC2019TimeOption):
                signature = _time_signature(value)
            elif (
                isinstance(value, tuple)
                and len(value) == 4
                and isinstance(value[0], str)
                and isinstance(value[1], int)
                and isinstance(value[2], int)
                and isinstance(value[3], str)
            ):
                signature = value
            else:
                raise TypeError(
                    "incumbent mappings must contain only placements, time "
                    "options, or canonical time signatures"
                )
            entries.append(ITC2019CheckpointTime(str(class_id), signature))
        return ITC2019PartialCheckpoint(tuple(entries)), ()
    if isinstance(incumbent, Sequence) and all(
        isinstance(value, ITC2019ClassPlacement) for value in incumbent
    ):
        return _checkpoint_from_placements(problem, incumbent)  # type: ignore[arg-type]
    raise TypeError(
        "incumbent must be an ITC2019PartialCheckpoint, placement collection, "
        "time mapping, or None"
    )


def _validate_open_ids(
    problem: ITC2019Problem,
    open_class_ids: Iterable[str] | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if open_class_ids is None:
        return (), ()
    raw = tuple(str(class_id) for class_id in open_class_ids)
    errors: list[str] = []
    seen: set[str] = set()
    duplicates: set[str] = set()
    for class_id in raw:
        if class_id in seen:
            duplicates.add(class_id)
        seen.add(class_id)
    if duplicates:
        errors.append(
            "open class ids contain duplicates: " + ", ".join(sorted(duplicates))
        )
    known = {klass.id for klass in problem.classes}
    unknown = sorted(set(raw) - known)
    if unknown:
        errors.append("open class ids contain unknown classes: " + ", ".join(unknown))
    return raw, tuple(errors)


def validate_itc2019_partial_checkpoint(
    problem: ITC2019Problem,
    checkpoint: ITC2019PartialCheckpoint,
    *,
    open_class_ids: Iterable[str] | None = None,
    room_hints: Mapping[str, str | None] | None = None,
    deadline: float | None = None,
) -> tuple[str, ...]:
    """Validate immutable fixed-time state without turning rooms into decisions.

    When ``open_class_ids`` is provided, every class outside that frontier must
    have a checkpoint time.  Required pair constraints are checked whenever
    both endpoints are fixed.  Required grouped constraints are checked once
    all their members are fixed.  Supplied entries for open classes are checked
    against their time domains but remain hints and never enter fixed room or
    distribution validation.  Room-only constraints and global room occupancy
    intentionally remain for the downstream room phase.

    Optional ``room_hints`` for fixed entries are checked only for per-class
    domain and unavailability legality.  They are never used for occupancy,
    SameRoom, DifferentRoom, or SameAttendees decisions.
    """

    _check_deadline(deadline, "checkpoint validation")
    errors = list(_validate_problem_references(problem))
    _check_deadline(deadline, "problem validation")
    raw_open_ids, open_errors = _validate_open_ids(problem, open_class_ids)
    errors.extend(open_errors)

    class_rows = tuple(_iter_class_context(problem))
    classes = {klass.id: klass for _course, _config, _subpart, klass in class_rows}
    checkpoint_by_id: dict[str, ITC2019CheckpointTime] = {}
    duplicate_ids: set[str] = set()
    for ordinal, entry in enumerate(checkpoint.times):
        if entry.class_id in checkpoint_by_id:
            duplicate_ids.add(entry.class_id)
        else:
            checkpoint_by_id[entry.class_id] = entry
        if ordinal % 1024 == 0:
            _check_deadline(deadline, "checkpoint indexing")
    if duplicate_ids:
        errors.append(
            "checkpoint contains duplicate classes: " + ", ".join(sorted(duplicate_ids))
        )
    unknown = sorted(set(checkpoint_by_id) - set(classes))
    if unknown:
        errors.append("checkpoint contains unknown classes: " + ", ".join(unknown))

    if open_class_ids is not None and not open_errors:
        fixed_ids = set(classes) - set(raw_open_ids)
        missing = sorted(fixed_ids - set(checkpoint_by_id))
        if missing:
            errors.append("checkpoint is missing fixed classes: " + ", ".join(missing))

    domain_resolved: dict[str, ITC2019TimeOption] = {}
    for ordinal, (class_id, entry) in enumerate(checkpoint_by_id.items()):
        klass = classes.get(class_id)
        if klass is None:
            continue
        candidates = tuple(
            option
            for option in klass.time_options
            if _time_signature(option) == entry.signature
        )
        if not candidates:
            errors.append(
                f"checkpoint class {class_id} time signature is outside its domain"
            )
            continue
        domain_resolved[class_id] = min(
            candidates, key=lambda option: option.penalty
        )
        if ordinal % 1024 == 0:
            _check_deadline(deadline, "checkpoint time resolution")

    fixed_entry_ids = set(checkpoint_by_id)
    if open_class_ids is not None:
        fixed_entry_ids.difference_update(raw_open_ids)
    resolved = {
        class_id: option
        for class_id, option in domain_resolved.items()
        if class_id in fixed_entry_ids
    }

    rooms = {room.id: room for room in problem.rooms}
    legal_rooms_by_class: dict[str, tuple[str | None, ...]] = {}
    for ordinal, (class_id, option) in enumerate(resolved.items()):
        klass = classes[class_id]
        legal_rooms = _legal_room_ids(klass, option, rooms)
        legal_rooms_by_class[class_id] = legal_rooms
        if klass.room_required and not legal_rooms:
            errors.append(
                f"checkpoint class {class_id} required-room time has no legal rooms"
            )
        if ordinal % 256 == 0:
            _check_deadline(deadline, "checkpoint legal-room resolution")

    if room_hints is not None:
        unknown_hints = sorted(set(room_hints) - set(classes))
        if unknown_hints:
            errors.append(
                "room hints contain unknown classes: " + ", ".join(unknown_hints)
            )
        for class_id, room_id in room_hints.items():
            klass = classes.get(class_id)
            if klass is None or room_id is None:
                continue
            if class_id not in resolved:
                if class_id not in domain_resolved:
                    errors.append(
                        f"room hint for class {class_id} has no valid checkpoint time"
                    )
                continue
            if not klass.room_required:
                errors.append(f"roomless class {class_id} must not have a room hint")
                continue
            allowed = {option.room_id for option in klass.room_options}
            if room_id not in allowed:
                errors.append(
                    f"room hint {room_id} for class {class_id} is outside its room domain"
                )
                continue
            if not _room_accepts_time(rooms[room_id], resolved[class_id]):
                errors.append(
                    f"room hint {room_id} for class {class_id} is unavailable at its time"
                )

    synthetic_placements = {
        class_id: ITC2019ClassPlacement(
            class_id=class_id,
            days=option.days,
            start=option.start,
            weeks=option.weeks,
            room_id=None,
        )
        for class_id, option in resolved.items()
    }
    travel = _travel_values(problem)
    pair_work = 0
    for distribution in problem.distributions:
        if distribution.required:
            base, parameters = _distribution_spec(distribution.type)
            class_ids = tuple(dict.fromkeys(distribution.class_ids))
            if base in _PAIR_DISTRIBUTIONS and base not in _ROOM_ONLY_DISTRIBUTIONS:
                for first_index, first_id in enumerate(class_ids):
                    if first_id not in resolved:
                        continue
                    for second_id in class_ids[first_index + 1 :]:
                        if second_id not in resolved:
                            continue
                        if base == "SameAttendees":
                            satisfied = False
                            for first_room in legal_rooms_by_class[first_id]:
                                first_placement = ITC2019ClassPlacement(
                                    class_id=first_id,
                                    days=resolved[first_id].days,
                                    start=resolved[first_id].start,
                                    weeks=resolved[first_id].weeks,
                                    room_id=first_room,
                                )
                                for second_room in legal_rooms_by_class[second_id]:
                                    second_placement = ITC2019ClassPlacement(
                                        class_id=second_id,
                                        days=resolved[second_id].days,
                                        start=resolved[second_id].start,
                                        weeks=resolved[second_id].weeks,
                                        room_id=second_room,
                                    )
                                    pair_work += 1
                                    if pair_work % 128 == 0:
                                        _check_deadline(
                                            deadline,
                                            "checkpoint pair distribution validation",
                                        )
                                    if _pair_distribution_satisfied(
                                        base,
                                        parameters,
                                        first_placement,
                                        resolved[first_id],
                                        second_placement,
                                        resolved[second_id],
                                        travel,
                                    ):
                                        satisfied = True
                                        break
                                if satisfied:
                                    break
                        else:
                            pair_work += 1
                            satisfied = _pair_distribution_satisfied(
                                base,
                                parameters,
                                synthetic_placements[first_id],
                                resolved[first_id],
                                synthetic_placements[second_id],
                                resolved[second_id],
                                travel,
                            )
                        if pair_work % 128 == 0:
                            _check_deadline(
                                deadline,
                                "checkpoint pair distribution validation",
                            )
                        if not satisfied:
                            errors.append(
                                f"checkpoint violates required {distribution.type}: "
                                f"{first_id}, {second_id}"
                            )
            elif base in _GROUP_DISTRIBUTIONS and all(
                class_id in resolved for class_id in class_ids
            ):
                units = _group_violation_units_with_deadline(
                    problem,
                    base,
                    parameters,
                    class_ids,
                    resolved,
                    deadline=deadline,
                )
                if units:
                    errors.append(
                        f"checkpoint violates required {distribution.type}: "
                        f"{units} unit(s)"
                    )
        _check_deadline(deadline, "checkpoint distribution validation")
    _check_deadline(deadline, "checkpoint validation completion")
    return tuple(errors)


def _prepare_distribution(
    source_ordinal: int,
    distribution: ITC2019Distribution,
) -> ITC2019PreparedDistribution:
    base, parameters = _distribution_spec(distribution.type)
    return ITC2019PreparedDistribution(
        source_ordinal=source_ordinal,
        constraint_type=distribution.type,
        base=base,
        parameters=parameters,
        required=distribution.required,
        penalty=distribution.penalty,
        raw_class_ids=distribution.class_ids,
        class_ids=tuple(dict.fromkeys(distribution.class_ids)),
        extra_attributes=distribution.extra_attributes,
    )


def prepare_itc2019_context(
    problem: ITC2019Problem,
    *,
    incumbent: ITC2019Incumbent,
    open_class_ids: Iterable[str],
    deadline: float,
    materialization: Literal["streamed", "full"] = "streamed",
) -> ITC2019PreparedContext:
    """Build one deterministic immutable context before ``deadline``.

    ``streamed`` and ``full`` are semantically identical.  The streamed path
    consumes hierarchy rows one at a time so large instances do not require an
    additional full class-context tuple during preprocessing.
    """

    if materialization not in {"streamed", "full"}:
        raise ValueError("materialization must be 'streamed' or 'full'")
    _check_deadline(deadline, "context admission")
    problem_errors = _validate_problem_references(problem)
    if problem_errors:
        raise ValueError("Invalid ITC-2019 problem: " + "; ".join(problem_errors))
    _check_deadline(deadline, "problem validation")

    class_ids = tuple(klass.id for klass in problem.classes)
    raw_open_ids, open_errors = _validate_open_ids(problem, open_class_ids)
    if open_errors:
        raise ValueError("; ".join(open_errors))
    open_set = frozenset(raw_open_ids)
    ordered_open_ids = tuple(class_id for class_id in class_ids if class_id in open_set)
    fixed_ids = tuple(class_id for class_id in class_ids if class_id not in open_set)

    normalized, _room_hints = _coerce_incumbent(problem, incumbent)
    incumbent_ids = tuple(entry.class_id for entry in normalized.times)
    seen_incumbent_ids: set[str] = set()
    duplicate_incumbent_ids: set[str] = set()
    for class_id in incumbent_ids:
        if class_id in seen_incumbent_ids:
            duplicate_incumbent_ids.add(class_id)
        seen_incumbent_ids.add(class_id)
    if duplicate_incumbent_ids:
        raise ValueError(
            "Invalid ITC-2019 partial checkpoint: checkpoint contains duplicate "
            "classes: " + ", ".join(sorted(duplicate_incumbent_ids))
        )
    unknown_incumbent_ids = sorted(set(incumbent_ids) - set(class_ids))
    if unknown_incumbent_ids:
        raise ValueError(
            "Invalid ITC-2019 partial checkpoint: checkpoint contains unknown "
            "classes: " + ", ".join(unknown_incumbent_ids)
        )
    class_by_id = {klass.id: klass for klass in problem.classes}
    stale_incumbent_ids: list[str] = []
    for ordinal, entry in enumerate(normalized.times):
        if not any(
            _time_signature(option) == entry.signature
            for option in class_by_id[entry.class_id].time_options
        ):
            stale_incumbent_ids.append(entry.class_id)
        if ordinal % 256 == 0:
            _check_deadline(deadline, "incumbent time validation")
    if stale_incumbent_ids:
        raise ValueError(
            "Invalid ITC-2019 partial checkpoint: time signature is outside the "
            "class domain for: " + ", ".join(stale_incumbent_ids)
        )
    normalized_by_id = {entry.class_id: entry for entry in normalized.times}
    fixed_checkpoint = ITC2019PartialCheckpoint(
        tuple(
            normalized_by_id[class_id]
            for class_id in fixed_ids
            if class_id in normalized_by_id
        )
    )
    checkpoint_errors = validate_itc2019_partial_checkpoint(
        problem,
        fixed_checkpoint,
        open_class_ids=ordered_open_ids,
        deadline=deadline,
    )
    if checkpoint_errors:
        raise ValueError(
            "Invalid ITC-2019 partial checkpoint: "
            + "; ".join(checkpoint_errors)
        )

    rooms_by_id = {room.id: room for room in problem.rooms}
    source_rows: Iterable[tuple[str, str, str, ITC2019Class]]
    if materialization == "full":
        source_rows = tuple(_iter_class_context(problem))
    else:
        source_rows = _iter_class_context(problem)
    prepared_classes: list[ITC2019PreparedClass] = []
    for class_ordinal, (course_id, configuration_id, subpart_id, klass) in enumerate(
        source_rows
    ):
        room_values = _canonical_rooms(klass)
        canonical_times = _canonical_times(klass, deadline=deadline)
        incumbent_entry = normalized_by_id.get(klass.id)
        if klass.id in open_set:
            selected_times = canonical_times
        else:
            assert incumbent_entry is not None  # validated above
            selected_times = tuple(
                row
                for row in canonical_times
                if _time_signature(row[1]) == incumbent_entry.signature
            )
        all_prepared_times = tuple(
            _prepared_time(
                source_ordinal,
                option,
                room_values,
                rooms_by_id,
            )
            for source_ordinal, option in selected_times
        )
        prepared_times = tuple(
            value for value in all_prepared_times if value.legal_room_ids
        )
        if not prepared_times:
            if klass.id in open_set:
                raise ValueError(
                    f"open class {klass.id} has no legal time-room alternatives"
                )
            raise ValueError(
                f"fixed class {klass.id} has no legal time-room alternatives"
            )
        incumbent_signature = (
            incumbent_entry.signature if incumbent_entry is not None else None
        )
        if incumbent_signature not in {
            value.signature for value in prepared_times
        }:
            incumbent_signature = None
        prepared_classes.append(
            ITC2019PreparedClass(
                class_id=klass.id,
                course_id=course_id,
                configuration_id=configuration_id,
                subpart_id=subpart_id,
                limit=klass.limit,
                parent_id=klass.parent_id,
                room_required=klass.room_required,
                is_open=klass.id in open_set,
                times=prepared_times,
                rooms=room_values,
                incumbent_signature=incumbent_signature,
                extra_attributes=klass.extra_attributes,
            )
        )
        if class_ordinal % 64 == 0:
            _check_deadline(deadline, "class preparation")

    prepared_distributions: list[ITC2019PreparedDistribution] = []
    for ordinal, distribution in enumerate(problem.distributions):
        prepared_distributions.append(_prepare_distribution(ordinal, distribution))
        if ordinal % 256 == 0:
            _check_deadline(deadline, "distribution preparation")
    _check_deadline(deadline, "distribution preparation")
    context = ITC2019PreparedContext(
        problem=problem,
        classes=tuple(prepared_classes),
        distributions=tuple(prepared_distributions),
        open_class_ids=ordered_open_ids,
        fixed_class_ids=fixed_ids,
        fixed_checkpoint=fixed_checkpoint,
    )
    _check_deadline(deadline, "context finalization")
    return context


__all__ = [
    "ITC2019CheckpointTime",
    "ITC2019Occurrence",
    "ITC2019PartialCheckpoint",
    "ITC2019PreparedClass",
    "ITC2019PreparedContext",
    "ITC2019PreparedDistribution",
    "ITC2019PreparedRoom",
    "ITC2019PreparedTime",
    "ITC2019TimeSignature",
    "prepare_itc2019_context",
    "validate_itc2019_partial_checkpoint",
]
