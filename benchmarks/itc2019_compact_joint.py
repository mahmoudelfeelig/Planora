"""Compact exact joint time-room constructor for large ITC-2019 timetables.

The formulation keeps one Boolean for every legal joint time-room placement,
but evaluates room-independent required pair predicates over aggregated time
choices. Room occurrence packing and room-sensitive predicates remain attached
to the joint placements, so the compression does not relax the timetable.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations
import math
import time
from typing import Mapping

from ortools.sat.python import cp_model

from benchmarks.itc2019 import (
    ITC2019ClassPlacement,
    ITC2019Problem,
    ITC2019TimeOption,
    _PAIR_DISTRIBUTIONS,
    _distribution_spec,
    _room_accepts_time,
    _travel_values,
    _validate_problem_references,
    validate_itc2019_solution,
)


DEFAULT_MAX_PLACEMENT_LITERALS = 400_000
DEFAULT_MAX_ROOM_OCCURRENCE_RECORDS = 5_000_000
DEFAULT_MAX_PAIR_TIME_CELLS = 30_000_000
DEFAULT_MAX_PAIR_ROWS = 1_000_000
DEFAULT_MAX_TRAVEL_JOINT_CELLS = 5_000_000
_ROOM_PAIR_DISTRIBUTIONS = frozenset({"SameRoom", "DifferentRoom"})


@dataclass(frozen=True, slots=True)
class ITC2019CompactJointScaleEstimate:
    """Model-free semantic and scale admission result."""

    admitted: bool
    placement_literals: int
    admitted_time_values: int
    room_choice_values: int
    room_occurrence_records: int
    required_pair_relations: int
    pair_time_cells: int
    pair_rows: int
    room_pair_cells: int
    illegal_room_time_pairs: int
    room_unsupported_time_options: int
    unsupported_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _CompactTime:
    original_index: int
    option: ITC2019TimeOption
    legal_rooms: tuple[str | None, ...]
    day_mask: int
    week_mask: int
    first_day: int
    first_week: int

    @property
    def start(self) -> int:
        return self.option.start

    @property
    def end(self) -> int:
        return self.option.start + self.option.length


@dataclass(frozen=True, slots=True)
class _DomainAnalysis:
    estimate: ITC2019CompactJointScaleEstimate
    times_by_class: Mapping[str, tuple[_CompactTime, ...]]
    room_domain_by_class: Mapping[str, tuple[str | None, ...]]
    required_pairs: tuple[tuple[str, str, str, tuple[int, ...]], ...]


@dataclass(frozen=True, slots=True)
class _PlacementChoice:
    class_id: str
    time_index: int
    time: _CompactTime
    room_id: str | None
    variable: cp_model.IntVar


def _deadline_expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _semantic_reason(problem: ITC2019Problem) -> str | None:
    reference_errors = _validate_problem_references(problem)
    if reference_errors:
        return f"compact_joint_invalid_problem:{reference_errors[0]}"
    if problem.students:
        return "compact_joint_requires_timetable_only_problem"
    for distribution in problem.distributions:
        if not distribution.required:
            continue
        base, _parameters = _distribution_spec(distribution.type)
        if base not in _PAIR_DISTRIBUTIONS:
            return f"compact_joint_required_distribution_not_supported:{base}"
    return None


def _required_pairs(
    problem: ITC2019Problem,
) -> tuple[tuple[str, str, str, tuple[int, ...]], ...]:
    result: list[tuple[str, str, str, tuple[int, ...]]] = []
    seen: set[tuple[str, str, str, tuple[int, ...]]] = set()
    for distribution in problem.distributions:
        if not distribution.required:
            continue
        base, parameters = _distribution_spec(distribution.type)
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        for first_id, second_id in combinations(class_ids, 2):
            key = (first_id, second_id, base, parameters)
            if key not in seen:
                seen.add(key)
                result.append(key)
    return tuple(result)


def _empty_analysis(reason: str) -> _DomainAnalysis:
    return _DomainAnalysis(
        estimate=ITC2019CompactJointScaleEstimate(
            admitted=False,
            placement_literals=0,
            admitted_time_values=0,
            room_choice_values=0,
            room_occurrence_records=0,
            required_pair_relations=0,
            pair_time_cells=0,
            pair_rows=0,
            room_pair_cells=0,
            illegal_room_time_pairs=0,
            room_unsupported_time_options=0,
            unsupported_reasons=(reason,),
        ),
        times_by_class={},
        room_domain_by_class={},
        required_pairs=(),
    )


def _analyze_domains(
    problem: ITC2019Problem,
    *,
    max_placement_literals: int,
    max_room_occurrence_records: int,
    max_pair_time_cells: int,
    max_pair_rows: int,
    deadline: float | None = None,
) -> _DomainAnalysis:
    semantic_reason = _semantic_reason(problem)
    if semantic_reason is not None:
        return _empty_analysis(semantic_reason)

    rooms = {room.id: room for room in problem.rooms}
    times_by_class: dict[str, tuple[_CompactTime, ...]] = {}
    room_domain_by_class: dict[str, tuple[str | None, ...]] = {}
    placement_literals = 0
    admitted_time_values = 0
    room_occurrence_records = 0
    illegal_room_time_pairs = 0
    room_unsupported_time_options = 0

    for class_index, klass in enumerate(problem.classes):
        raw_rooms: tuple[str | None, ...] = (
            tuple(option.room_id for option in klass.room_options)
            if klass.room_required
            else (None,)
        )
        admitted: list[_CompactTime] = []
        admitted_rooms: set[str | None] = set()
        for time_index, option in enumerate(klass.time_options):
            legal_rooms = tuple(
                room_id
                for room_id in raw_rooms
                if room_id is None or _room_accepts_time(rooms[room_id], option)
            )
            illegal_room_time_pairs += len(raw_rooms) - len(legal_rooms)
            if not legal_rooms:
                room_unsupported_time_options += 1
                continue
            admitted.append(
                _CompactTime(
                    original_index=time_index,
                    option=option,
                    legal_rooms=legal_rooms,
                    day_mask=int(option.days, 2),
                    week_mask=int(option.weeks, 2),
                    first_day=option.days.index("1"),
                    first_week=option.weeks.index("1"),
                )
            )
            admitted_rooms.update(legal_rooms)
            placement_literals += len(legal_rooms)
            if legal_rooms != (None,):
                room_occurrence_records += len(legal_rooms) * (
                    option.days.count("1") * option.weeks.count("1")
                )
            if _deadline_expired(deadline):
                raise TimeoutError("compact-joint domain analysis exceeded deadline")
        if not admitted:
            return _empty_analysis(f"compact_joint_empty_legal_domain:{klass.id}")
        times_by_class[klass.id] = tuple(admitted)
        room_domain_by_class[klass.id] = tuple(
            sorted(admitted_rooms, key=lambda value: "" if value is None else value)
        )
        admitted_time_values += len(admitted)
        if class_index % 16 == 0 and _deadline_expired(deadline):
            raise TimeoutError("compact-joint domain analysis exceeded deadline")

    pairs = _required_pairs(problem)
    pair_time_cells = 0
    pair_rows = 0
    room_pair_cells = 0
    for pair_index, (first_id, second_id, base, _parameters) in enumerate(pairs):
        if base in _ROOM_PAIR_DISTRIBUTIONS:
            first_count = len(room_domain_by_class[first_id])
            second_count = len(room_domain_by_class[second_id])
            room_pair_cells += first_count * second_count
            pair_rows += min(first_count, second_count)
        else:
            first_count = len(times_by_class[first_id])
            second_count = len(times_by_class[second_id])
            pair_time_cells += first_count * second_count
            pair_rows += min(first_count, second_count)
        if pair_index % 256 == 0 and _deadline_expired(deadline):
            raise TimeoutError("compact-joint pair analysis exceeded deadline")

    reasons: list[str] = []
    if placement_literals > max_placement_literals:
        reasons.append(
            "compact_joint_placement_literal_limit:"
            f"{placement_literals}>{max_placement_literals}"
        )
    if room_occurrence_records > max_room_occurrence_records:
        reasons.append(
            "compact_joint_room_occurrence_limit:"
            f"{room_occurrence_records}>{max_room_occurrence_records}"
        )
    if pair_time_cells > max_pair_time_cells:
        reasons.append(
            f"compact_joint_pair_time_cell_limit:{pair_time_cells}>{max_pair_time_cells}"
        )
    if pair_rows > max_pair_rows:
        reasons.append(f"compact_joint_pair_row_limit:{pair_rows}>{max_pair_rows}")

    estimate = ITC2019CompactJointScaleEstimate(
        admitted=not reasons,
        placement_literals=placement_literals,
        admitted_time_values=admitted_time_values,
        room_choice_values=sum(len(values) for values in room_domain_by_class.values()),
        room_occurrence_records=room_occurrence_records,
        required_pair_relations=len(pairs),
        pair_time_cells=pair_time_cells,
        pair_rows=pair_rows,
        room_pair_cells=room_pair_cells,
        illegal_room_time_pairs=illegal_room_time_pairs,
        room_unsupported_time_options=room_unsupported_time_options,
        unsupported_reasons=tuple(reasons),
    )
    return _DomainAnalysis(
        estimate=estimate,
        times_by_class=times_by_class,
        room_domain_by_class=room_domain_by_class,
        required_pairs=pairs,
    )


def _validate_limits(
    *,
    max_placement_literals: int,
    max_room_occurrence_records: int,
    max_pair_time_cells: int,
    max_pair_rows: int,
    max_travel_joint_cells: int,
) -> None:
    if (
        min(
            max_placement_literals,
            max_room_occurrence_records,
            max_pair_time_cells,
            max_pair_rows,
            max_travel_joint_cells,
        )
        <= 0
    ):
        raise ValueError("compact-joint scale limits must be positive")


def estimate_itc2019_compact_joint_scale(
    problem: ITC2019Problem,
    *,
    max_placement_literals: int = DEFAULT_MAX_PLACEMENT_LITERALS,
    max_room_occurrence_records: int = DEFAULT_MAX_ROOM_OCCURRENCE_RECORDS,
    max_pair_time_cells: int = DEFAULT_MAX_PAIR_TIME_CELLS,
    max_pair_rows: int = DEFAULT_MAX_PAIR_ROWS,
) -> ITC2019CompactJointScaleEstimate:
    """Return exact pre-build semantic and core scale counts."""

    _validate_limits(
        max_placement_literals=max_placement_literals,
        max_room_occurrence_records=max_room_occurrence_records,
        max_pair_time_cells=max_pair_time_cells,
        max_pair_rows=max_pair_rows,
        max_travel_joint_cells=DEFAULT_MAX_TRAVEL_JOINT_CELLS,
    )
    return _analyze_domains(
        problem,
        max_placement_literals=max_placement_literals,
        max_room_occurrence_records=max_room_occurrence_records,
        max_pair_time_cells=max_pair_time_cells,
        max_pair_rows=max_pair_rows,
    ).estimate


def itc2019_compact_joint_admission_reason(
    problem: ITC2019Problem,
    **scale_limits: int,
) -> str | None:
    """Return the first semantic or core-scale admission failure."""

    estimate = estimate_itc2019_compact_joint_scale(problem, **scale_limits)
    return estimate.unsupported_reasons[0] if estimate.unsupported_reasons else None


def should_construct_itc2019_compact_joint(
    problem: ITC2019Problem,
    **scale_limits: int,
) -> bool:
    """Admit exact pair-only timetable models within explicit scale limits."""

    return itc2019_compact_joint_admission_reason(problem, **scale_limits) is None


def _time_pair_satisfied_without_room(
    base: str,
    parameters: tuple[int, ...],
    first: _CompactTime,
    second: _CompactTime,
) -> bool:
    """Evaluate every room-independent part of the official pair arithmetic."""

    if base == "SameStart":
        return first.start == second.start
    if base == "SameTime":
        return (first.start <= second.start and second.end <= first.end) or (
            second.start <= first.start and first.end <= second.end
        )
    if base == "DifferentTime":
        return first.end <= second.start or second.end <= first.start
    if base == "SameDays":
        return (first.day_mask & ~second.day_mask) == 0 or (
            second.day_mask & ~first.day_mask
        ) == 0
    if base == "DifferentDays":
        return not (first.day_mask & second.day_mask)
    if base == "SameWeeks":
        return (first.week_mask & ~second.week_mask) == 0 or (
            second.week_mask & ~first.week_mask
        ) == 0
    if base == "DifferentWeeks":
        return not (first.week_mask & second.week_mask)
    if base == "Overlap":
        return (
            bool(first.day_mask & second.day_mask)
            and bool(first.week_mask & second.week_mask)
            and first.start < second.end
            and second.start < first.end
        )
    if base in {"NotOverlap", "SameAttendees"}:
        return not (
            bool(first.day_mask & second.day_mask)
            and bool(first.week_mask & second.week_mask)
            and first.start < second.end
            and second.start < first.end
        )
    if base == "Precedence":
        if first.first_week != second.first_week:
            return first.first_week < second.first_week
        if first.first_day != second.first_day:
            return first.first_day < second.first_day
        return first.end <= second.start
    if base == "WorkDay":
        return (
            not (first.day_mask & second.day_mask)
            or not (first.week_mask & second.week_mask)
            or max(first.end, second.end) - min(first.start, second.start)
            <= parameters[0]
        )
    if base == "MinGap":
        return (
            not (first.day_mask & second.day_mask)
            or not (first.week_mask & second.week_mask)
            or first.end + parameters[0] <= second.start
            or second.end + parameters[0] <= first.start
        )
    raise ValueError(f"unsupported compact-joint time distribution {base!r}")


def _fail(
    diagnostics: dict[str, object],
    *,
    status: str,
    stage: str,
    started: float,
    reason: str | None = None,
) -> None:
    diagnostics["status"] = status
    diagnostics["stage"] = stage
    diagnostics["wall_time_seconds"] = time.monotonic() - started
    if reason is not None:
        diagnostics["failure_reason"] = reason


def construct_itc2019_compact_joint(
    problem: ITC2019Problem,
    *,
    deadline: float,
    workers: int = 1,
    random_seed: int = 17,
    diagnostics: dict[str, object] | None = None,
    max_placement_literals: int = DEFAULT_MAX_PLACEMENT_LITERALS,
    max_room_occurrence_records: int = DEFAULT_MAX_ROOM_OCCURRENCE_RECORDS,
    max_pair_time_cells: int = DEFAULT_MAX_PAIR_TIME_CELLS,
    max_pair_rows: int = DEFAULT_MAX_PAIR_ROWS,
    max_travel_joint_cells: int = DEFAULT_MAX_TRAVEL_JOINT_CELLS,
) -> tuple[ITC2019ClassPlacement, ...] | None:
    """Return a complete exact timetable or fail closed before ``deadline``."""

    if workers <= 0:
        raise ValueError("workers must be positive")
    if random_seed < 0:
        raise ValueError("random_seed must be non-negative")
    if not math.isfinite(deadline):
        raise ValueError("deadline must be a finite monotonic timestamp")
    _validate_limits(
        max_placement_literals=max_placement_literals,
        max_room_occurrence_records=max_room_occurrence_records,
        max_pair_time_cells=max_pair_time_cells,
        max_pair_rows=max_pair_rows,
        max_travel_joint_cells=max_travel_joint_cells,
    )

    diagnostics = diagnostics if diagnostics is not None else {}
    started = time.monotonic()
    diagnostics.update(
        {
            "formulation": "compact_joint_time_aggregation_sat_v1",
            "requested_workers": workers,
            "effective_workers": 1,
            "random_seed": random_seed,
            "absolute_deadline": deadline,
            "status": "BUILDING",
            "stage": "admission",
        }
    )
    if started >= deadline:
        _fail(
            diagnostics,
            status="DEADLINE_EXCEEDED",
            stage="admission",
            started=started,
        )
        return None

    total_budget = deadline - started
    finalization_reserve = min(5.0, max(0.1, total_budget * 0.05))
    build_deadline = deadline - finalization_reserve
    diagnostics["finalization_reserve_seconds"] = finalization_reserve
    if started >= build_deadline:
        _fail(
            diagnostics,
            status="DEADLINE_EXCEEDED",
            stage="admission",
            started=started,
        )
        return None

    try:
        analysis = _analyze_domains(
            problem,
            max_placement_literals=max_placement_literals,
            max_room_occurrence_records=max_room_occurrence_records,
            max_pair_time_cells=max_pair_time_cells,
            max_pair_rows=max_pair_rows,
            deadline=build_deadline,
        )
    except TimeoutError as exc:
        _fail(
            diagnostics,
            status="DEADLINE_EXCEEDED",
            stage="admission",
            started=started,
            reason=str(exc),
        )
        return None
    diagnostics.update(analysis.estimate.to_dict())
    if not analysis.estimate.admitted:
        _fail(
            diagnostics,
            status="UNSUPPORTED",
            stage="admission",
            started=started,
            reason=analysis.estimate.unsupported_reasons[0],
        )
        return None

    model = cp_model.CpModel()
    time_variables: dict[str, tuple[cp_model.IntVar, ...]] = {}
    room_variables: dict[str, dict[str | None, cp_model.IntVar]] = {}
    placements_by_class: dict[str, tuple[_PlacementChoice, ...]] = {}
    placements_by_class_time: dict[str, tuple[tuple[_PlacementChoice, ...], ...]] = {}
    placements_by_room: dict[str, list[_PlacementChoice]] = defaultdict(list)
    diagnostics["stage"] = "placement_variables"

    for class_index, klass in enumerate(problem.classes):
        compact_times = analysis.times_by_class[klass.id]
        class_time_variables = tuple(
            model.new_bool_var(f"cj_t_c{class_index}_{time_index}")
            for time_index in range(len(compact_times))
        )
        time_variables[klass.id] = class_time_variables
        class_placements: list[_PlacementChoice] = []
        by_time: list[list[_PlacementChoice]] = [[] for _ in compact_times]
        by_room: dict[str | None, list[_PlacementChoice]] = defaultdict(list)
        for time_index, compact_time in enumerate(compact_times):
            for room_index, room_id in enumerate(compact_time.legal_rooms):
                variable = model.new_bool_var(
                    f"cj_p_c{class_index}_t{time_index}_r{room_index}"
                )
                value = _PlacementChoice(
                    class_id=klass.id,
                    time_index=time_index,
                    time=compact_time,
                    room_id=room_id,
                    variable=variable,
                )
                class_placements.append(value)
                by_time[time_index].append(value)
                by_room[room_id].append(value)
                if room_id is not None:
                    placements_by_room[room_id].append(value)
        model.add_exactly_one(value.variable for value in class_placements)
        for time_index, values in enumerate(by_time):
            model.add(
                sum(value.variable for value in values)
                == class_time_variables[time_index]
            )
        class_room_variables: dict[str | None, cp_model.IntVar] = {}
        for room_index, (room_id, values) in enumerate(by_room.items()):
            room_variable = model.new_bool_var(f"cj_r_c{class_index}_{room_index}")
            model.add(sum(value.variable for value in values) == room_variable)
            class_room_variables[room_id] = room_variable
        room_variables[klass.id] = class_room_variables
        placements_by_class[klass.id] = tuple(class_placements)
        placements_by_class_time[klass.id] = tuple(tuple(values) for values in by_time)
        if class_index % 16 == 0 and _deadline_expired(build_deadline):
            _fail(
                diagnostics,
                status="DEADLINE_EXCEEDED",
                stage="placement_variables",
                started=started,
            )
            return None
    diagnostics["placement_variable_seconds"] = time.monotonic() - started

    diagnostics["stage"] = "room_occurrence_cliques"
    room_clique_constraints = 0
    room_clique_literals = 0
    for room_index, room_id in enumerate(sorted(placements_by_room)):
        buckets: dict[tuple[int, int], list[tuple[int, int, int, _PlacementChoice]]] = (
            defaultdict(list)
        )
        for serial, value in enumerate(placements_by_room[room_id]):
            for day, active_day in enumerate(value.time.option.days):
                if active_day != "1":
                    continue
                for week, active_week in enumerate(value.time.option.weeks):
                    if active_week == "1":
                        buckets[(day, week)].append(
                            (value.time.start, value.time.end, serial, value)
                        )
        seen_cliques: set[tuple[int, ...]] = set()
        for bucket_index, intervals in enumerate(buckets.values()):
            ordered = sorted(intervals, key=lambda row: (row[0], row[1], row[2]))
            active: dict[int, tuple[int, str, _PlacementChoice]] = {}
            cursor = 0
            while cursor < len(ordered):
                current_start = ordered[cursor][0]
                active = {
                    serial: item
                    for serial, item in active.items()
                    if item[0] > current_start
                }
                while cursor < len(ordered) and ordered[cursor][0] == current_start:
                    _start, end, serial, value = ordered[cursor]
                    active[serial] = (end, value.class_id, value)
                    cursor += 1
                if len({class_id for _end, class_id, _value in active.values()}) < 2:
                    continue
                clique = tuple(sorted(active))
                if clique in seen_cliques:
                    continue
                seen_cliques.add(clique)
                model.add_at_most_one(active[serial][2].variable for serial in clique)
                room_clique_constraints += 1
                room_clique_literals += len(clique)
            if bucket_index % 32 == 0 and _deadline_expired(build_deadline):
                _fail(
                    diagnostics,
                    status="DEADLINE_EXCEEDED",
                    stage="room_occurrence_cliques",
                    started=started,
                )
                return None
        if room_index % 8 == 0 and _deadline_expired(build_deadline):
            _fail(
                diagnostics,
                status="DEADLINE_EXCEEDED",
                stage="room_occurrence_cliques",
                started=started,
            )
            return None
    diagnostics["room_clique_constraints"] = room_clique_constraints
    diagnostics["room_clique_literals"] = room_clique_literals

    diagnostics["stage"] = "required_pair_rows"
    travel = _travel_values(problem)
    maximum_travel = max(travel.values(), default=0)
    pair_time_evaluations = 0
    pair_row_constraints = 0
    pair_row_literals = 0
    room_pair_constraints = 0
    travel_joint_cells = 0
    travel_joint_conflicts = 0
    for pair_index, (first_id, second_id, base, parameters) in enumerate(
        analysis.required_pairs
    ):
        if base in _ROOM_PAIR_DISTRIBUTIONS:
            first_rooms = room_variables[first_id]
            second_rooms = room_variables[second_id]
            if base == "SameRoom":
                for room_id in set(first_rooms) | set(second_rooms):
                    first_variable = first_rooms.get(room_id)
                    second_variable = second_rooms.get(room_id)
                    if first_variable is None:
                        assert second_variable is not None
                        model.add(second_variable == 0)
                    elif second_variable is None:
                        model.add(first_variable == 0)
                    else:
                        model.add(first_variable == second_variable)
                    room_pair_constraints += 1
            else:
                for room_id in set(first_rooms) & set(second_rooms):
                    model.add_at_most_one([first_rooms[room_id], second_rooms[room_id]])
                    room_pair_constraints += 1
            continue

        first_times = analysis.times_by_class[first_id]
        second_times = analysis.times_by_class[second_id]
        lhs_is_first = len(first_times) <= len(second_times)
        lhs_id, rhs_id = (
            (first_id, second_id) if lhs_is_first else (second_id, first_id)
        )
        lhs_times, rhs_times = (
            (first_times, second_times) if lhs_is_first else (second_times, first_times)
        )
        lhs_variables = time_variables[lhs_id]
        rhs_variables = time_variables[rhs_id]
        for lhs_time_index, lhs_time in enumerate(lhs_times):
            compatible: list[int] = []
            incompatible: list[int] = []
            for rhs_time_index, rhs_time in enumerate(rhs_times):
                if lhs_is_first:
                    first_time = lhs_time
                    second_time = rhs_time
                    first_time_index = lhs_time_index
                    second_time_index = rhs_time_index
                else:
                    first_time = rhs_time
                    second_time = lhs_time
                    first_time_index = rhs_time_index
                    second_time_index = lhs_time_index
                satisfied_without_room = _time_pair_satisfied_without_room(
                    base, parameters, first_time, second_time
                )
                pair_time_evaluations += 1
                target = compatible if satisfied_without_room else incompatible
                target.append(rhs_time_index)

                overlap_masks = bool(
                    first_time.day_mask & second_time.day_mask
                ) and bool(first_time.week_mask & second_time.week_mask)
                gap = (
                    second_time.start - first_time.end
                    if first_time.end <= second_time.start
                    else first_time.start - second_time.end
                )
                if (
                    base == "SameAttendees"
                    and satisfied_without_room
                    and overlap_masks
                    and gap < maximum_travel
                ):
                    first_values = placements_by_class_time[first_id][first_time_index]
                    second_values = placements_by_class_time[second_id][
                        second_time_index
                    ]
                    for first_value in first_values:
                        for second_value in second_values:
                            travel_joint_cells += 1
                            if travel_joint_cells > max_travel_joint_cells:
                                _fail(
                                    diagnostics,
                                    status="UNSUPPORTED_MODEL_SCALE",
                                    stage="required_pair_rows",
                                    started=started,
                                    reason=(
                                        "compact_joint_travel_cell_limit:"
                                        f"{travel_joint_cells}>{max_travel_joint_cells}"
                                    ),
                                )
                                return None
                            distance = 0
                            if (
                                first_value.room_id is not None
                                and second_value.room_id is not None
                            ):
                                distance = travel.get(
                                    (first_value.room_id, second_value.room_id),
                                    travel.get(
                                        (
                                            second_value.room_id,
                                            first_value.room_id,
                                        ),
                                        0,
                                    ),
                                )
                            if distance > gap:
                                model.add_at_most_one(
                                    [first_value.variable, second_value.variable]
                                )
                                travel_joint_conflicts += 1
                if pair_time_evaluations % 4096 == 0 and _deadline_expired(
                    build_deadline
                ):
                    _fail(
                        diagnostics,
                        status="DEADLINE_EXCEEDED",
                        stage="required_pair_rows",
                        started=started,
                    )
                    return None

            lhs_variable = lhs_variables[lhs_time_index]
            if not incompatible:
                continue
            if not compatible:
                model.add(lhs_variable == 0)
                pair_row_literals += 1
            elif len(compatible) <= len(incompatible):
                model.add(
                    lhs_variable <= sum(rhs_variables[index] for index in compatible)
                )
                pair_row_literals += 1 + len(compatible)
            else:
                model.add_at_most_one(
                    [lhs_variable] + [rhs_variables[index] for index in incompatible]
                )
                pair_row_literals += 1 + len(incompatible)
            pair_row_constraints += 1
        if pair_index % 32 == 0 and _deadline_expired(build_deadline):
            _fail(
                diagnostics,
                status="DEADLINE_EXCEEDED",
                stage="required_pair_rows",
                started=started,
            )
            return None

    diagnostics.update(
        {
            "pair_time_evaluations": pair_time_evaluations,
            "pair_row_constraints": pair_row_constraints,
            "pair_row_literals": pair_row_literals,
            "room_pair_constraints": room_pair_constraints,
            "travel_joint_cells": travel_joint_cells,
            "travel_joint_conflicts": travel_joint_conflicts,
        }
    )
    diagnostics["stage"] = "model_validation"
    model_error = model.validate()
    diagnostics["model_variables"] = len(model.proto.variables)
    diagnostics["model_constraints"] = len(model.proto.constraints)
    diagnostics["model_build_seconds"] = time.monotonic() - started
    if model_error:
        diagnostics["model_validation_error"] = model_error
        _fail(
            diagnostics,
            status="MODEL_INVALID",
            stage="model_validation",
            started=started,
            reason=model_error,
        )
        return None
    if _deadline_expired(build_deadline):
        _fail(
            diagnostics,
            status="DEADLINE_EXCEEDED",
            stage="model_validation",
            started=started,
        )
        return None

    search_seconds = deadline - time.monotonic() - finalization_reserve
    if search_seconds <= 0:
        _fail(
            diagnostics,
            status="DEADLINE_EXCEEDED",
            stage="search",
            started=started,
        )
        return None
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(search_seconds)
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = int(random_seed)
    diagnostics["stage"] = "search"
    status_code = solver.solve(model)
    diagnostics.update(
        {
            "solver_status": solver.status_name(status_code).upper(),
            "solver_wall_time_seconds": float(solver.wall_time),
            "solver_conflicts": int(solver.num_conflicts),
            "solver_branches": int(solver.num_branches),
        }
    )
    if _deadline_expired(deadline):
        _fail(
            diagnostics,
            status="DEADLINE_EXCEEDED",
            stage="search",
            started=started,
        )
        return None
    if status_code not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        _fail(
            diagnostics,
            status=solver.status_name(status_code).upper(),
            stage="search",
            started=started,
        )
        return None

    diagnostics["stage"] = "decode"
    placements: list[ITC2019ClassPlacement] = []
    for klass in problem.classes:
        selected = [
            value
            for value in placements_by_class[klass.id]
            if solver.boolean_value(value.variable)
        ]
        if len(selected) != 1:
            _fail(
                diagnostics,
                status="INVALID_RESULT",
                stage="decode",
                started=started,
                reason=f"class {klass.id} selected {len(selected)} placements",
            )
            return None
        value = selected[0]
        placements.append(
            ITC2019ClassPlacement(
                class_id=klass.id,
                days=value.time.option.days,
                start=value.time.option.start,
                weeks=value.time.option.weeks,
                room_id=value.room_id,
            )
        )

    diagnostics["stage"] = "independent_validation"
    immutable = tuple(placements)
    validation_errors = tuple(validate_itc2019_solution(problem, immutable, {}))
    diagnostics["validation_errors"] = validation_errors
    if validation_errors:
        _fail(
            diagnostics,
            status="INVALID_RESULT",
            stage="independent_validation",
            started=started,
            reason=validation_errors[0],
        )
        return None
    if _deadline_expired(deadline):
        _fail(
            diagnostics,
            status="DEADLINE_EXCEEDED",
            stage="independent_validation",
            started=started,
        )
        return None

    diagnostics["status"] = "FEASIBLE"
    diagnostics["stage"] = "complete"
    diagnostics["wall_time_seconds"] = time.monotonic() - started
    return immutable


__all__ = [
    "ITC2019CompactJointScaleEstimate",
    "construct_itc2019_compact_joint",
    "estimate_itc2019_compact_joint_scale",
    "itc2019_compact_joint_admission_reason",
    "should_construct_itc2019_compact_joint",
]
