"""Exact sparse joint-placement constructor for ITC-2019 timetables.

The formulation creates one Boolean for every legal raw time-room placement,
selects exactly one placement per class, packs concrete room occurrences with
interval cliques, and encodes every admitted required pair or group predicate
exactly.
Admission is semantic and scale-based; it never depends on instance identity,
known solutions, scores, or retained assignments.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations, product
import math
import time
from typing import Mapping, Sequence

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


DEFAULT_MAX_PLACEMENT_LITERALS = 250_000
DEFAULT_MAX_ROOM_OCCURRENCE_RECORDS = 5_000_000
DEFAULT_MAX_PAIR_SEMANTIC_CELLS = 120_000_000
DEFAULT_MAX_PAIR_ROWS = 500_000
DEFAULT_MAX_GROUP_SEMANTIC_CELLS = 500_000
_SUPPORTED_GROUP_DISTRIBUTIONS = frozenset({"MaxBreaks"})


@dataclass(frozen=True, slots=True)
class ITC2019SparseJointScaleEstimate:
    """Model-free size and semantic admission result."""

    admitted: bool
    placement_literals: int
    semantic_placement_values: int
    room_occurrence_records: int
    required_pair_relations: int
    pair_semantic_cells: int
    pair_rows: int
    required_group_relations: int
    group_semantic_cells: int
    unsupported_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _LegalPlacement:
    time_index: int
    room_index: int | None
    time: ITC2019TimeOption
    room_id: str | None

    @property
    def semantic_key(self) -> tuple[str, int, int, str, str | None]:
        return (
            self.time.days,
            self.time.start,
            self.time.length,
            self.time.weeks,
            self.room_id,
        )


@dataclass(frozen=True, slots=True)
class _DomainAnalysis:
    estimate: ITC2019SparseJointScaleEstimate
    domains: Mapping[str, tuple[_LegalPlacement, ...]]
    time_domains: Mapping[str, tuple[ITC2019TimeOption, ...]]
    required_pairs: tuple[tuple[str, str, str, tuple[int, ...]], ...]
    required_groups: tuple[tuple[str, tuple[int, ...], tuple[str, ...]], ...]
    illegal_room_time_pairs: int


@dataclass(frozen=True, slots=True)
class _PlacementValue:
    class_id: str
    time: ITC2019TimeOption
    room_id: str | None
    variable_index: int


@dataclass(frozen=True, slots=True)
class _SemanticPlacement:
    time: ITC2019TimeOption
    room_id: str | None
    day_mask: int
    week_mask: int
    first_day: int
    first_week: int
    variable_indices: tuple[int, ...]

    @property
    def start(self) -> int:
        return self.time.start

    @property
    def end(self) -> int:
        return self.time.start + self.time.length


def _deadline_expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _semantic_reason(problem: ITC2019Problem) -> str | None:
    reference_errors = _validate_problem_references(problem)
    if reference_errors:
        return f"sparse_joint_invalid_problem:{reference_errors[0]}"
    if problem.students:
        return "sparse_joint_requires_timetable_only_problem"
    for distribution in problem.distributions:
        if not distribution.required:
            continue
        base, _parameters = _distribution_spec(distribution.type)
        if (
            base not in _PAIR_DISTRIBUTIONS
            and base not in _SUPPORTED_GROUP_DISTRIBUTIONS
        ):
            return f"sparse_joint_required_distribution_not_supported:{base}"
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
        if base not in _PAIR_DISTRIBUTIONS:
            continue
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        for first_id, second_id in combinations(class_ids, 2):
            key = (first_id, second_id, base, parameters)
            if key not in seen:
                seen.add(key)
                result.append(key)
    return tuple(result)


def _required_groups(
    problem: ITC2019Problem,
) -> tuple[tuple[str, tuple[int, ...], tuple[str, ...]], ...]:
    result: list[tuple[str, tuple[int, ...], tuple[str, ...]]] = []
    seen: set[tuple[str, tuple[int, ...], tuple[str, ...]]] = set()
    for distribution in problem.distributions:
        if not distribution.required:
            continue
        base, parameters = _distribution_spec(distribution.type)
        if base not in _SUPPORTED_GROUP_DISTRIBUTIONS:
            continue
        key = (base, parameters, tuple(dict.fromkeys(distribution.class_ids)))
        if key not in seen:
            seen.add(key)
            result.append(key)
    return tuple(result)


def _analyze_domains(
    problem: ITC2019Problem,
    *,
    max_placement_literals: int,
    max_room_occurrence_records: int,
    max_pair_semantic_cells: int,
    max_pair_rows: int,
    max_group_semantic_cells: int,
    materialize_domains: bool,
    deadline: float | None = None,
) -> _DomainAnalysis:
    reason = _semantic_reason(problem)
    if reason is not None:
        return _DomainAnalysis(
            estimate=ITC2019SparseJointScaleEstimate(
                admitted=False,
                placement_literals=0,
                semantic_placement_values=0,
                room_occurrence_records=0,
                required_pair_relations=0,
                pair_semantic_cells=0,
                pair_rows=0,
                required_group_relations=0,
                group_semantic_cells=0,
                unsupported_reasons=(reason,),
            ),
            domains={},
            time_domains={},
            required_pairs=(),
            required_groups=(),
            illegal_room_time_pairs=0,
        )

    rooms = {room.id: room for room in problem.rooms}
    domains: dict[str, tuple[_LegalPlacement, ...]] = {}
    time_domains: dict[str, tuple[ITC2019TimeOption, ...]] = {}
    semantic_counts: dict[str, int] = {}
    time_counts: dict[str, int] = {}
    placement_literals = 0
    semantic_placement_values = 0
    room_occurrence_records = 0
    illegal_room_time_pairs = 0
    scanned_values = 0
    domain_reason: str | None = None

    for klass in problem.classes:
        room_values: tuple[tuple[int | None, str | None], ...]
        if klass.room_required:
            room_values = tuple(
                (index, option.room_id)
                for index, option in enumerate(klass.room_options)
            )
        else:
            room_values = ((None, None),)
        class_domain: list[_LegalPlacement] = []
        legal_values = 0
        unique_times: dict[tuple[str, int, int, str], ITC2019TimeOption] = {}
        semantic_keys: set[tuple[str, int, int, str, str | None]] = set()
        for time_index, option in enumerate(klass.time_options):
            for room_index, room_id in room_values:
                scanned_values += 1
                if room_id is not None and not _room_accepts_time(
                    rooms[room_id], option
                ):
                    illegal_room_time_pairs += 1
                    continue
                if materialize_domains:
                    class_domain.append(
                        _LegalPlacement(
                            time_index=time_index,
                            room_index=room_index,
                            time=option,
                            room_id=room_id,
                        )
                    )
                unique_times.setdefault(
                    (option.days, option.start, option.length, option.weeks), option
                )
                semantic_keys.add(
                    (
                        option.days,
                        option.start,
                        option.length,
                        option.weeks,
                        room_id,
                    )
                )
                legal_values += 1
                placement_literals += 1
                if room_id is not None:
                    room_occurrence_records += option.days.count(
                        "1"
                    ) * option.weeks.count("1")
                if scanned_values % 256 == 0 and _deadline_expired(deadline):
                    raise TimeoutError("sparse-joint domain analysis exceeded deadline")
        if not legal_values:
            domain_reason = f"sparse_joint_empty_legal_domain:{klass.id}"
            break
        if materialize_domains:
            domains[klass.id] = tuple(class_domain)
            time_domains[klass.id] = tuple(unique_times.values())
        time_counts[klass.id] = len(unique_times)
        semantic_counts[klass.id] = len(semantic_keys)
        semantic_placement_values += len(semantic_keys)
        if _deadline_expired(deadline):
            raise TimeoutError("sparse-joint domain analysis exceeded deadline")

    pairs = _required_pairs(problem) if domain_reason is None else ()
    groups = _required_groups(problem) if domain_reason is None else ()
    pair_semantic_cells = 0
    pair_rows = 0
    if domain_reason is None:
        for index, (first_id, second_id, _base, _parameters) in enumerate(pairs):
            first_count = semantic_counts[first_id]
            second_count = semantic_counts[second_id]
            pair_semantic_cells += first_count * second_count
            pair_rows += min(first_count, second_count)
            if index % 256 == 0 and _deadline_expired(deadline):
                raise TimeoutError("sparse-joint pair analysis exceeded deadline")

    group_semantic_cells = 0
    if domain_reason is None:
        for index, (_base, _parameters, class_ids) in enumerate(groups):
            cells = 1
            for class_id in class_ids:
                cells *= time_counts[class_id]
            group_semantic_cells += cells
            if index % 64 == 0 and _deadline_expired(deadline):
                raise TimeoutError("sparse-joint group analysis exceeded deadline")

    reasons: list[str] = []
    if domain_reason is not None:
        reasons.append(domain_reason)
    if placement_literals > max_placement_literals:
        reasons.append(
            "sparse_joint_placement_literal_limit:"
            f"{placement_literals}>{max_placement_literals}"
        )
    if room_occurrence_records > max_room_occurrence_records:
        reasons.append(
            "sparse_joint_room_occurrence_limit:"
            f"{room_occurrence_records}>{max_room_occurrence_records}"
        )
    if pair_semantic_cells > max_pair_semantic_cells:
        reasons.append(
            "sparse_joint_pair_semantic_cell_limit:"
            f"{pair_semantic_cells}>{max_pair_semantic_cells}"
        )
    if pair_rows > max_pair_rows:
        reasons.append(f"sparse_joint_pair_row_limit:{pair_rows}>{max_pair_rows}")
    if group_semantic_cells > max_group_semantic_cells:
        reasons.append(
            "sparse_joint_group_semantic_cell_limit:"
            f"{group_semantic_cells}>{max_group_semantic_cells}"
        )

    estimate = ITC2019SparseJointScaleEstimate(
        admitted=not reasons,
        placement_literals=placement_literals,
        semantic_placement_values=semantic_placement_values,
        room_occurrence_records=room_occurrence_records,
        required_pair_relations=len(pairs),
        pair_semantic_cells=pair_semantic_cells,
        pair_rows=pair_rows,
        required_group_relations=len(groups),
        group_semantic_cells=group_semantic_cells,
        unsupported_reasons=tuple(reasons),
    )
    return _DomainAnalysis(
        estimate=estimate,
        domains=domains,
        time_domains=time_domains,
        required_pairs=pairs,
        required_groups=groups,
        illegal_room_time_pairs=illegal_room_time_pairs,
    )


def _validate_limits(
    *,
    max_placement_literals: int,
    max_room_occurrence_records: int,
    max_pair_semantic_cells: int,
    max_pair_rows: int,
    max_group_semantic_cells: int,
) -> None:
    if (
        min(
            max_placement_literals,
            max_room_occurrence_records,
            max_pair_semantic_cells,
            max_pair_rows,
            max_group_semantic_cells,
        )
        <= 0
    ):
        raise ValueError("sparse-joint scale limits must be positive")


def estimate_itc2019_sparse_joint_scale(
    problem: ITC2019Problem,
    *,
    max_placement_literals: int = DEFAULT_MAX_PLACEMENT_LITERALS,
    max_room_occurrence_records: int = DEFAULT_MAX_ROOM_OCCURRENCE_RECORDS,
    max_pair_semantic_cells: int = DEFAULT_MAX_PAIR_SEMANTIC_CELLS,
    max_pair_rows: int = DEFAULT_MAX_PAIR_ROWS,
    max_group_semantic_cells: int = DEFAULT_MAX_GROUP_SEMANTIC_CELLS,
) -> ITC2019SparseJointScaleEstimate:
    """Return exact pre-build scale counts and semantic admission reasons."""

    _validate_limits(
        max_placement_literals=max_placement_literals,
        max_room_occurrence_records=max_room_occurrence_records,
        max_pair_semantic_cells=max_pair_semantic_cells,
        max_pair_rows=max_pair_rows,
        max_group_semantic_cells=max_group_semantic_cells,
    )
    return _analyze_domains(
        problem,
        max_placement_literals=max_placement_literals,
        max_room_occurrence_records=max_room_occurrence_records,
        max_pair_semantic_cells=max_pair_semantic_cells,
        max_pair_rows=max_pair_rows,
        max_group_semantic_cells=max_group_semantic_cells,
        materialize_domains=False,
    ).estimate


def itc2019_sparse_joint_admission_reason(
    problem: ITC2019Problem,
    **scale_limits: int,
) -> str | None:
    """Return the first semantic or scale reason that prevents exact encoding."""

    estimate = estimate_itc2019_sparse_joint_scale(problem, **scale_limits)
    return estimate.unsupported_reasons[0] if estimate.unsupported_reasons else None


def should_construct_itc2019_sparse_joint(
    problem: ITC2019Problem,
    **scale_limits: int,
) -> bool:
    """Admit any timetable-only problem represented exactly within scale limits."""

    return itc2019_sparse_joint_admission_reason(problem, **scale_limits) is None


def _mask_indices(mask: str) -> tuple[int, ...]:
    return tuple(index for index, active in enumerate(mask) if active == "1")


def _semantic_placement(
    time_option: ITC2019TimeOption,
    room_id: str | None,
    variable_indices: tuple[int, ...],
) -> _SemanticPlacement:
    return _SemanticPlacement(
        time=time_option,
        room_id=room_id,
        day_mask=int(time_option.days, 2),
        week_mask=int(time_option.weeks, 2),
        first_day=time_option.days.index("1"),
        first_week=time_option.weeks.index("1"),
        variable_indices=variable_indices,
    )


def _pair_satisfied(
    base: str,
    parameters: tuple[int, ...],
    first: _SemanticPlacement,
    second: _SemanticPlacement,
    travel: Mapping[tuple[str, str], int],
) -> bool:
    """Mirror the official pair arithmetic over compact semantic placements."""

    first_end = first.end
    second_end = second.end
    if base == "SameStart":
        return first.start == second.start
    if base == "SameTime":
        return (first.start <= second.start and second_end <= first_end) or (
            second.start <= first.start and first_end <= second_end
        )
    if base == "DifferentTime":
        return first_end <= second.start or second_end <= first.start
    if base == "SameDays":
        return (first.day_mask & ~second.day_mask) == 0 or (
            second.day_mask & ~first.day_mask
        ) == 0
    if base == "DifferentDays":
        return (first.day_mask & second.day_mask) == 0
    if base == "SameWeeks":
        return (first.week_mask & ~second.week_mask) == 0 or (
            second.week_mask & ~first.week_mask
        ) == 0
    if base == "DifferentWeeks":
        return (first.week_mask & second.week_mask) == 0
    if base == "SameRoom":
        return first.room_id == second.room_id
    if base == "DifferentRoom":
        return first.room_id != second.room_id
    if base == "Overlap":
        return (
            bool(first.day_mask & second.day_mask)
            and bool(first.week_mask & second.week_mask)
            and first.start < second_end
            and second.start < first_end
        )
    if base == "NotOverlap":
        return not (
            bool(first.day_mask & second.day_mask)
            and bool(first.week_mask & second.week_mask)
            and first.start < second_end
            and second.start < first_end
        )
    if base == "SameAttendees":
        if not (first.day_mask & second.day_mask) or not (
            first.week_mask & second.week_mask
        ):
            return True
        distance = 0
        if first.room_id is not None and second.room_id is not None:
            distance = travel.get(
                (first.room_id, second.room_id),
                travel.get((second.room_id, first.room_id), 0),
            )
        return first_end + distance <= second.start or (
            second_end + distance <= first.start
        )
    if base == "Precedence":
        if first.first_week != second.first_week:
            return first.first_week < second.first_week
        if first.first_day != second.first_day:
            return first.first_day < second.first_day
        return first_end <= second.start
    if base == "WorkDay":
        (maximum_span,) = parameters
        return (
            not (first.day_mask & second.day_mask)
            or not (first.week_mask & second.week_mask)
            or max(first_end, second_end) - min(first.start, second.start)
            <= maximum_span
        )
    if base == "MinGap":
        (minimum_gap,) = parameters
        return (
            not (first.day_mask & second.day_mask)
            or not (first.week_mask & second.week_mask)
            or first_end + minimum_gap <= second.start
            or second_end + minimum_gap <= first.start
        )
    raise ValueError(f"unsupported sparse-joint pair distribution {base!r}")


def _max_breaks_violation_units(
    problem: ITC2019Problem,
    parameters: tuple[int, ...],
    class_ids: Sequence[str],
    resolved: Mapping[str, ITC2019TimeOption],
    *,
    deadline: float | None = None,
) -> int:
    """Return official MaxBreaks excess for a complete group time tuple."""

    maximum_breaks, maximum_gap = parameters
    total_excess = 0
    for day in range(problem.nr_days):
        for week in range(problem.nr_weeks):
            if _deadline_expired(deadline):
                raise TimeoutError("sparse-joint group encoding exceeded deadline")
            intervals = sorted(
                {
                    (option.start, option.start + option.length)
                    for class_id in class_ids
                    for option in (resolved[class_id],)
                    if option.days[day] == "1" and option.weeks[week] == "1"
                }
            )
            blocks: list[tuple[int, int]] = []
            for start, end in intervals:
                if blocks and start <= blocks[-1][1] + maximum_gap:
                    previous_start, previous_end = blocks[-1]
                    blocks[-1] = (previous_start, max(previous_end, end))
                else:
                    blocks.append((start, end))
            total_excess += max(len(blocks) - (maximum_breaks + 1), 0)
    return total_excess


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


def construct_itc2019_sparse_joint(
    problem: ITC2019Problem,
    *,
    deadline: float,
    workers: int = 1,
    random_seed: int = 17,
    diagnostics: dict[str, object] | None = None,
    max_placement_literals: int = DEFAULT_MAX_PLACEMENT_LITERALS,
    max_room_occurrence_records: int = DEFAULT_MAX_ROOM_OCCURRENCE_RECORDS,
    max_pair_semantic_cells: int = DEFAULT_MAX_PAIR_SEMANTIC_CELLS,
    max_pair_rows: int = DEFAULT_MAX_PAIR_ROWS,
    max_group_semantic_cells: int = DEFAULT_MAX_GROUP_SEMANTIC_CELLS,
) -> tuple[ITC2019ClassPlacement, ...] | None:
    """Return a complete immutable timetable or fail closed before ``deadline``.

    The caller owns the one absolute monotonic deadline.  ``workers`` is accepted
    for routing compatibility, but this deterministic feasibility constructor
    always runs CP-SAT with exactly one worker.
    """

    if workers <= 0:
        raise ValueError("workers must be positive")
    if random_seed < 0:
        raise ValueError("random_seed must be non-negative")
    if not math.isfinite(deadline):
        raise ValueError("deadline must be a finite monotonic timestamp")
    _validate_limits(
        max_placement_literals=max_placement_literals,
        max_room_occurrence_records=max_room_occurrence_records,
        max_pair_semantic_cells=max_pair_semantic_cells,
        max_pair_rows=max_pair_rows,
        max_group_semantic_cells=max_group_semantic_cells,
    )

    diagnostics = diagnostics if diagnostics is not None else {}
    started = time.monotonic()
    diagnostics.update(
        {
            "formulation": "sparse_joint_placement_sat_v1",
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
        admission = _analyze_domains(
            problem,
            max_placement_literals=max_placement_literals,
            max_room_occurrence_records=max_room_occurrence_records,
            max_pair_semantic_cells=max_pair_semantic_cells,
            max_pair_rows=max_pair_rows,
            max_group_semantic_cells=max_group_semantic_cells,
            materialize_domains=False,
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
    diagnostics.update(admission.estimate.to_dict())
    diagnostics["illegal_room_time_pairs_filtered"] = admission.illegal_room_time_pairs
    if not admission.estimate.admitted:
        _fail(
            diagnostics,
            status="UNSUPPORTED",
            stage="admission",
            started=started,
            reason=admission.estimate.unsupported_reasons[0],
        )
        return None

    diagnostics["stage"] = "domain_materialization"
    try:
        analysis = _analyze_domains(
            problem,
            max_placement_literals=max_placement_literals,
            max_room_occurrence_records=max_room_occurrence_records,
            max_pair_semantic_cells=max_pair_semantic_cells,
            max_pair_rows=max_pair_rows,
            max_group_semantic_cells=max_group_semantic_cells,
            materialize_domains=True,
            deadline=build_deadline,
        )
    except TimeoutError as exc:
        _fail(
            diagnostics,
            status="DEADLINE_EXCEEDED",
            stage="domain_materialization",
            started=started,
            reason=str(exc),
        )
        return None
    if analysis.estimate != admission.estimate:
        _fail(
            diagnostics,
            status="FAILED",
            stage="domain_materialization",
            started=started,
            reason="sparse_joint_admission_materialization_mismatch",
        )
        return None

    model = cp_model.CpModel()
    all_variables: list[cp_model.IntVar] = []
    values_by_class: dict[str, tuple[_PlacementValue, ...]] = {}
    semantics_by_class: dict[str, tuple[_SemanticPlacement, ...]] = {}
    values_by_room: dict[str, list[_PlacementValue]] = defaultdict(list)
    grouped_class_ids = {
        class_id
        for _base, _parameters, class_ids in analysis.required_groups
        for class_id in class_ids
    }
    time_choices: dict[str, cp_model.IntVar] = {}
    diagnostics["stage"] = "placement_variables"

    for class_index, klass in enumerate(problem.classes):
        class_values: list[_PlacementValue] = []
        semantic_indices: dict[tuple[str, int, int, str, str | None], list[int]] = (
            defaultdict(list)
        )
        semantic_times: dict[
            tuple[str, int, int, str, str | None], ITC2019TimeOption
        ] = {}
        for placement in analysis.domains[klass.id]:
            room_label = (
                f"r{placement.room_index}"
                if placement.room_index is not None
                else "roomless"
            )
            variable = model.new_bool_var(
                f"sj_c{class_index}_t{placement.time_index}_{room_label}"
            )
            variable_index = int(variable.index)
            if variable_index != len(all_variables):
                raise RuntimeError("sparse-joint variable indices are not contiguous")
            all_variables.append(variable)
            value = _PlacementValue(
                class_id=klass.id,
                time=placement.time,
                room_id=placement.room_id,
                variable_index=variable_index,
            )
            class_values.append(value)
            if placement.room_id is not None:
                values_by_room[placement.room_id].append(value)
            semantic_indices[placement.semantic_key].append(variable_index)
            semantic_times.setdefault(placement.semantic_key, placement.time)
        model.add_exactly_one(
            all_variables[value.variable_index] for value in class_values
        )
        values_by_class[klass.id] = tuple(class_values)
        semantics_by_class[klass.id] = tuple(
            _semantic_placement(
                semantic_times[key],
                key[-1],
                tuple(variable_indices),
            )
            for key, variable_indices in semantic_indices.items()
        )
        if class_index % 32 == 0 and _deadline_expired(build_deadline):
            _fail(
                diagnostics,
                status="DEADLINE_EXCEEDED",
                stage="placement_variables",
                started=started,
            )
            return None

    for class_index, klass in enumerate(problem.classes):
        if klass.id not in grouped_class_ids:
            continue
        time_domain = analysis.time_domains[klass.id]
        time_indices = {
            (option.days, option.start, option.length, option.weeks): index
            for index, option in enumerate(time_domain)
        }
        choice = model.new_int_var(
            0,
            len(time_domain) - 1,
            f"sj_group_time_c{class_index}",
        )
        model.add(
            choice
            == sum(
                time_indices[
                    (
                        value.time.days,
                        value.time.start,
                        value.time.length,
                        value.time.weeks,
                    )
                ]
                * all_variables[value.variable_index]
                for value in values_by_class[klass.id]
            )
        )
        time_choices[klass.id] = choice
        if class_index % 32 == 0 and _deadline_expired(build_deadline):
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
    for room_index, room_id in enumerate(sorted(values_by_room)):
        occurrence_intervals: dict[tuple[int, int], list[tuple[int, int, int, str]]] = (
            defaultdict(list)
        )
        for value in values_by_room[room_id]:
            for day in _mask_indices(value.time.days):
                for week in _mask_indices(value.time.weeks):
                    occurrence_intervals[(day, week)].append(
                        (
                            value.time.start,
                            value.time.start + value.time.length,
                            value.variable_index,
                            value.class_id,
                        )
                    )
        seen_cliques: set[tuple[int, ...]] = set()
        for bucket_index, intervals in enumerate(occurrence_intervals.values()):
            ordered = sorted(intervals)
            active: dict[int, tuple[int, str]] = {}
            cursor = 0
            while cursor < len(ordered):
                start = ordered[cursor][0]
                active = {
                    index: (end, class_id)
                    for index, (end, class_id) in active.items()
                    if end > start
                }
                while cursor < len(ordered) and ordered[cursor][0] == start:
                    _start, end, variable_index, class_id = ordered[cursor]
                    active[variable_index] = (end, class_id)
                    cursor += 1
                if len({class_id for _end, class_id in active.values()}) < 2:
                    continue
                clique = tuple(sorted(active))
                if clique in seen_cliques:
                    continue
                seen_cliques.add(clique)
                model.add_at_most_one(all_variables[index] for index in clique)
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
    pair_semantic_evaluations = 0
    pair_row_constraints = 0
    pair_row_literals = 0
    pair_rows_compatibility_encoded = 0
    pair_rows_conflict_encoded = 0
    pair_rows_unconstrained = 0
    pair_rows_disabled = 0
    for pair_index, (first_id, second_id, base, parameters) in enumerate(
        analysis.required_pairs
    ):
        first_values = semantics_by_class[first_id]
        second_values = semantics_by_class[second_id]
        lhs_is_first = len(first_values) <= len(second_values)
        lhs_values = first_values if lhs_is_first else second_values
        rhs_values = second_values if lhs_is_first else first_values
        for lhs in lhs_values:
            compatible_indices: list[int] = []
            incompatible_indices: list[int] = []
            for rhs in rhs_values:
                first = lhs if lhs_is_first else rhs
                second = rhs if lhs_is_first else lhs
                pair_semantic_evaluations += 1
                target = (
                    compatible_indices
                    if _pair_satisfied(base, parameters, first, second, travel)
                    else incompatible_indices
                )
                target.extend(rhs.variable_indices)
                if pair_semantic_evaluations % 4096 == 0 and _deadline_expired(
                    build_deadline
                ):
                    _fail(
                        diagnostics,
                        status="DEADLINE_EXCEEDED",
                        stage="required_pair_rows",
                        started=started,
                    )
                    return None
            lhs_variables = [all_variables[index] for index in lhs.variable_indices]
            if not incompatible_indices:
                pair_rows_unconstrained += 1
                continue
            if not compatible_indices:
                model.add(sum(lhs_variables) == 0)
                pair_row_constraints += 1
                pair_row_literals += len(lhs_variables)
                pair_rows_disabled += 1
                continue
            if len(compatible_indices) <= len(incompatible_indices):
                model.add(
                    sum(lhs_variables)
                    <= sum(all_variables[index] for index in compatible_indices)
                )
                pair_row_literals += len(lhs_variables) + len(compatible_indices)
                pair_rows_compatibility_encoded += 1
            else:
                variables = lhs_variables + [
                    all_variables[index] for index in incompatible_indices
                ]
                model.add_at_most_one(variables)
                pair_row_literals += len(variables)
                pair_rows_conflict_encoded += 1
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
            "pair_semantic_evaluations": pair_semantic_evaluations,
            "pair_row_constraints": pair_row_constraints,
            "pair_row_literals": pair_row_literals,
            "pair_rows_compatibility_encoded": pair_rows_compatibility_encoded,
            "pair_rows_conflict_encoded": pair_rows_conflict_encoded,
            "pair_rows_unconstrained": pair_rows_unconstrained,
            "pair_rows_disabled": pair_rows_disabled,
        }
    )
    if _deadline_expired(build_deadline):
        _fail(
            diagnostics,
            status="DEADLINE_EXCEEDED",
            stage="required_pair_rows",
            started=started,
        )
        return None

    diagnostics["stage"] = "required_group_tables"
    group_semantic_evaluations = 0
    group_forbidden_rows = 0
    group_unconstrained = 0
    for group_index, (base, parameters, class_ids) in enumerate(
        analysis.required_groups
    ):
        forbidden_rows: list[tuple[int, ...]] = []
        domains = tuple(
            range(len(analysis.time_domains[class_id])) for class_id in class_ids
        )
        for time_indices in product(*domains):
            if _deadline_expired(build_deadline):
                _fail(
                    diagnostics,
                    status="DEADLINE_EXCEEDED",
                    stage="required_group_tables",
                    started=started,
                )
                return None
            resolved = {
                class_id: analysis.time_domains[class_id][time_index]
                for class_id, time_index in zip(class_ids, time_indices, strict=True)
            }
            if base == "MaxBreaks":
                try:
                    violation_units = _max_breaks_violation_units(
                        problem,
                        parameters,
                        class_ids,
                        resolved,
                        deadline=build_deadline,
                    )
                except TimeoutError as exc:
                    _fail(
                        diagnostics,
                        status="DEADLINE_EXCEEDED",
                        stage="required_group_tables",
                        started=started,
                        reason=str(exc),
                    )
                    return None
            else:
                _fail(
                    diagnostics,
                    status="UNSUPPORTED",
                    stage="required_group_tables",
                    started=started,
                    reason=f"unsupported sparse-joint group distribution {base!r}",
                )
                return None
            if violation_units:
                forbidden_rows.append(time_indices)
            group_semantic_evaluations += 1
            if group_semantic_evaluations % 256 == 0 and _deadline_expired(
                build_deadline
            ):
                _fail(
                    diagnostics,
                    status="DEADLINE_EXCEEDED",
                    stage="required_group_tables",
                    started=started,
                )
                return None
        if forbidden_rows:
            model.add_forbidden_assignments(
                tuple(time_choices[class_id] for class_id in class_ids),
                forbidden_rows,
            )
            group_forbidden_rows += len(forbidden_rows)
        else:
            group_unconstrained += 1
        if group_index % 16 == 0 and _deadline_expired(build_deadline):
            _fail(
                diagnostics,
                status="DEADLINE_EXCEEDED",
                stage="required_group_tables",
                started=started,
            )
            return None
    diagnostics.update(
        {
            "group_semantic_evaluations": group_semantic_evaluations,
            "group_forbidden_rows": group_forbidden_rows,
            "group_unconstrained": group_unconstrained,
        }
    )
    if _deadline_expired(build_deadline):
        _fail(
            diagnostics,
            status="DEADLINE_EXCEEDED",
            stage="required_group_tables",
            started=started,
        )
        return None

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

    placements: list[ITC2019ClassPlacement] = []
    diagnostics["stage"] = "decode"
    for klass in problem.classes:
        selected = [
            value
            for value in values_by_class[klass.id]
            if solver.boolean_value(all_variables[value.variable_index])
        ]
        if len(selected) != 1:
            _fail(
                diagnostics,
                status="INVALID_RESULT",
                stage="decode",
                started=started,
                reason=(f"class {klass.id} selected {len(selected)} sparse placements"),
            )
            return None
        value = selected[0]
        placements.append(
            ITC2019ClassPlacement(
                class_id=klass.id,
                days=value.time.days,
                start=value.time.start,
                weeks=value.time.weeks,
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
    "ITC2019SparseJointScaleEstimate",
    "construct_itc2019_sparse_joint",
    "estimate_itc2019_sparse_joint_scale",
    "itc2019_sparse_joint_admission_reason",
    "should_construct_itc2019_sparse_joint",
]
