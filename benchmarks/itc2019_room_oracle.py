"""Deterministic exact room oracle for prepared ITC-2019 timetables.

The oracle accepts a complete canonical time assignment and deliberately
rebuilds every room decision.  No incumbent room, published placement, or
competitor result is an input to this module.  Class assumptions make an
infeasible result useful to a time-frontier search without weakening any room,
travel, or required distribution semantics.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from itertools import combinations
import math
import time
from typing import Iterable, Mapping, Sequence

from ortools.sat.python import cp_model

from benchmarks.itc2019 import (
    ITC2019ClassPlacement,
    ITC2019TimeOption,
    _PAIR_DISTRIBUTIONS,
    _pair_distribution_satisfied,
    _special_distribution_units,
    _travel_values,
    validate_itc2019_solution,
)
from benchmarks.itc2019_preprocessing import (
    ITC2019CheckpointTime,
    ITC2019PartialCheckpoint,
    ITC2019PreparedContext,
    ITC2019PreparedTime,
    ITC2019TimeSignature,
)


@dataclass(frozen=True, slots=True)
class ITC2019RoomOracleLimits:
    """Hard model-construction limits; every limit is checked fail-closed."""

    max_room_selectors: int = 400_000
    max_occurrence_records: int = 5_000_000
    max_clique_literals: int = 20_000_000
    max_pair_room_cells: int = 10_000_000
    max_model_variables: int = 500_000
    max_model_constraints: int = 10_000_000

    def validate(self) -> None:
        if min(
            self.max_room_selectors,
            self.max_occurrence_records,
            self.max_clique_literals,
            self.max_pair_room_cells,
            self.max_model_variables,
            self.max_model_constraints,
        ) <= 0:
            raise ValueError("room-oracle limits must be positive")


@dataclass(frozen=True, slots=True)
class ITC2019RoomStructuralCore:
    """Source-derived structural explanation for an infeasible room model."""

    class_ids: tuple[str, ...]
    distribution_ordinals: tuple[int, ...] = ()
    kind: str = "assumption_core"


@dataclass(frozen=True, slots=True)
class ITC2019RoomCertificate:
    """Complete independently validated source-only room certificate."""

    canonical_times: tuple[ITC2019CheckpointTime, ...]
    rooms: tuple[tuple[str, str | None], ...]
    competitor_schedule_or_result_used: bool = False
    competitor_placement_or_hint_used: bool = False


@dataclass(frozen=True, slots=True)
class ITC2019RoomOracleResult:
    """Immutable outcome of an exact room-oracle call."""

    status: str
    placements: tuple[ITC2019ClassPlacement, ...] = ()
    certificate: ITC2019RoomCertificate | None = None
    core: ITC2019RoomStructuralCore | None = None
    failure_reason: str | None = None
    room_selectors: int = 0
    occurrence_records: int = 0
    clique_constraints: int = 0
    clique_literals: int = 0
    pair_room_cells: int = 0
    model_variables: int = 0
    model_constraints: int = 0
    solver_status: str | None = None
    wall_time_seconds: float = 0.0

    @property
    def is_feasible(self) -> bool:
        return self.status == "FEASIBLE"


@dataclass(frozen=True, slots=True)
class _RoomChoice:
    class_id: str
    room_id: str | None
    variable: cp_model.IntVar


def _deadline_expired(deadline: float) -> bool:
    return time.monotonic() >= deadline


def _prepared_option(value: ITC2019PreparedTime) -> ITC2019TimeOption:
    return ITC2019TimeOption(
        days=value.days,
        start=value.start,
        length=value.length,
        weeks=value.weeks,
        penalty=value.penalty,
        extra_attributes=value.extra_attributes,
    )


def _normalize_times(
    context: ITC2019PreparedContext,
    selected_times: ITC2019PartialCheckpoint
    | Mapping[str, ITC2019TimeSignature]
    | Sequence[ITC2019CheckpointTime],
) -> tuple[
    tuple[ITC2019CheckpointTime, ...],
    dict[str, ITC2019PreparedTime],
]:
    if isinstance(selected_times, ITC2019PartialCheckpoint):
        entries = selected_times.times
    elif isinstance(selected_times, Mapping):
        entries = tuple(
            ITC2019CheckpointTime(str(class_id), signature)
            for class_id, signature in selected_times.items()
        )
    else:
        entries = tuple(selected_times)
    if not all(isinstance(entry, ITC2019CheckpointTime) for entry in entries):
        raise TypeError("selected times must contain checkpoint-time entries")

    source_ids = tuple(value.class_id for value in context.classes)
    known = set(source_ids)
    by_id: dict[str, ITC2019CheckpointTime] = {}
    duplicate_ids: set[str] = set()
    for entry in entries:
        if entry.class_id in by_id:
            duplicate_ids.add(entry.class_id)
        else:
            by_id[entry.class_id] = entry
    if duplicate_ids:
        raise ValueError(
            "room-oracle times contain duplicate classes: "
            + ", ".join(sorted(duplicate_ids))
        )
    unknown = sorted(set(by_id) - known)
    if unknown:
        raise ValueError(
            "room-oracle times contain unknown classes: " + ", ".join(unknown)
        )
    missing = tuple(class_id for class_id in source_ids if class_id not in by_id)
    if missing:
        raise ValueError(
            "room-oracle times are incomplete; missing classes: "
            + ", ".join(missing)
        )

    resolved: dict[str, ITC2019PreparedTime] = {}
    canonical: list[ITC2019CheckpointTime] = []
    for prepared_class in context.classes:
        entry = by_id[prepared_class.class_id]
        matches = tuple(
            value
            for value in prepared_class.times
            if value.signature == entry.signature
        )
        if len(matches) != 1:
            raise ValueError(
                f"room-oracle class {prepared_class.class_id} has a stale or "
                "non-admitted time signature"
            )
        resolved[prepared_class.class_id] = matches[0]
        canonical.append(
            ITC2019CheckpointTime(prepared_class.class_id, matches[0].signature)
        )
    return tuple(canonical), resolved


def maximal_half_open_interval_cliques(
    intervals: Iterable[tuple[int, int, str]],
) -> tuple[tuple[str, ...], ...]:
    """Return deterministic maximal cliques for half-open interval records.

    Records with the same key are coalesced.  Endpoints touching at ``end ==
    start`` do not overlap.  Singleton cliques are omitted because they cannot
    create room contention.
    """

    rows = tuple(sorted(set(intervals), key=lambda row: (row[0], row[1], row[2])))
    if any(start >= end for start, end, _key in rows):
        raise ValueError("room-oracle intervals must have positive length")
    active: dict[str, int] = {}
    candidates: set[tuple[str, ...]] = set()
    cursor = 0
    while cursor < len(rows):
        start = rows[cursor][0]
        active = {key: end for key, end in active.items() if end > start}
        while cursor < len(rows) and rows[cursor][0] == start:
            _start, end, key = rows[cursor]
            active[key] = max(end, active.get(key, end))
            cursor += 1
        if len(active) >= 2:
            candidates.add(tuple(sorted(active)))
    maximal = tuple(
        sorted(
            (
                candidate
                for candidate in candidates
                if not any(
                    set(candidate) < set(other) for other in candidates
                )
            ),
            key=lambda value: (len(value), value),
        )
    )
    return maximal


def _result(
    *,
    started: float,
    status: str,
    failure_reason: str | None = None,
    core: ITC2019RoomStructuralCore | None = None,
    room_selectors: int = 0,
    occurrence_records: int = 0,
    clique_constraints: int = 0,
    clique_literals: int = 0,
    pair_room_cells: int = 0,
    model_variables: int = 0,
    model_constraints: int = 0,
    solver_status: str | None = None,
) -> ITC2019RoomOracleResult:
    return ITC2019RoomOracleResult(
        status=status,
        core=core,
        failure_reason=failure_reason,
        room_selectors=room_selectors,
        occurrence_records=occurrence_records,
        clique_constraints=clique_constraints,
        clique_literals=clique_literals,
        pair_room_cells=pair_room_cells,
        model_variables=model_variables,
        model_constraints=model_constraints,
        solver_status=solver_status,
        wall_time_seconds=time.monotonic() - started,
    )


def solve_itc2019_room_oracle(
    context: ITC2019PreparedContext,
    selected_times: ITC2019PartialCheckpoint
    | Mapping[str, ITC2019TimeSignature]
    | Sequence[ITC2019CheckpointTime],
    *,
    deadline: float,
    random_seed: int = 17,
    limits: ITC2019RoomOracleLimits | None = None,
) -> ITC2019RoomOracleResult:
    """Solve the full-instance room problem for one complete time assignment.

    The result is exact when ``FEASIBLE`` or ``INFEASIBLE``.  Deadline and
    resource-bound outcomes are explicit and never presented as infeasibility.
    """

    started = time.monotonic()
    if not math.isfinite(deadline):
        raise ValueError("room-oracle deadline must be a finite monotonic timestamp")
    if random_seed < 0:
        raise ValueError("room-oracle random seed must be non-negative")
    effective_limits = limits or ITC2019RoomOracleLimits()
    effective_limits.validate()
    if _deadline_expired(deadline):
        return _result(started=started, status="DEADLINE_EXCEEDED")
    canonical, resolved = _normalize_times(context, selected_times)

    source_order = {
        prepared_class.class_id: ordinal
        for ordinal, prepared_class in enumerate(context.classes)
    }
    options = {
        class_id: _prepared_option(value) for class_id, value in resolved.items()
    }
    room_domains = {
        prepared_class.class_id: tuple(
            room_id
            for room_id in resolved[prepared_class.class_id].legal_room_ids
        )
        for prepared_class in context.classes
    }
    for prepared_class in context.classes:
        if not room_domains[prepared_class.class_id]:
            if _deadline_expired(deadline):
                return _result(started=started, status="DEADLINE_EXCEEDED")
            return _result(
                started=started,
                status="INFEASIBLE",
                core=ITC2019RoomStructuralCore((prepared_class.class_id,)),
                failure_reason="empty_legal_room_domain",
            )

    grouped_ordinals: list[int] = []
    for distribution in context.distributions:
        if not distribution.required or distribution.base in _PAIR_DISTRIBUTIONS:
            continue
        units = _special_distribution_units(
            context.problem,
            distribution.base,
            distribution.parameters,
            distribution.class_ids,
            options,
        )
        if _deadline_expired(deadline):
            return _result(started=started, status="DEADLINE_EXCEEDED")
        if units:
            grouped_ordinals.append(distribution.source_ordinal)
            ordered_ids = tuple(
                sorted(distribution.class_ids, key=source_order.__getitem__)
            )
            if _deadline_expired(deadline):
                return _result(started=started, status="DEADLINE_EXCEEDED")
            return _result(
                started=started,
                status="INFEASIBLE",
                core=ITC2019RoomStructuralCore(
                    ordered_ids,
                    tuple(grouped_ordinals),
                    "required_group_time_violation",
                ),
                failure_reason=(
                    f"required_{distribution.constraint_type}_violation:{units}"
                ),
            )
        if _deadline_expired(deadline):
            return _result(started=started, status="DEADLINE_EXCEEDED")

    room_selectors = sum(len(values) for values in room_domains.values())
    occurrence_records = sum(
        resolved[class_id].occurrence_count * (room_id is not None)
        for class_id, values in room_domains.items()
        for room_id in values
    )
    if room_selectors > effective_limits.max_room_selectors:
        return _result(
            started=started,
            status="RESOURCE_LIMIT",
            failure_reason=(
                f"room_selector_limit:{room_selectors}>"
                f"{effective_limits.max_room_selectors}"
            ),
            room_selectors=room_selectors,
            occurrence_records=occurrence_records,
        )
    if occurrence_records > effective_limits.max_occurrence_records:
        return _result(
            started=started,
            status="RESOURCE_LIMIT",
            failure_reason=(
                f"occurrence_record_limit:{occurrence_records}>"
                f"{effective_limits.max_occurrence_records}"
            ),
            room_selectors=room_selectors,
            occurrence_records=occurrence_records,
        )

    model = cp_model.CpModel()
    assumptions: dict[int, str] = {}
    selectors_by_class: dict[str, tuple[_RoomChoice, ...]] = {}
    selector_by_key: dict[tuple[str, str | None], cp_model.IntVar] = {}
    occurrence_buckets: dict[
        tuple[str, int, int], list[tuple[int, int, str]]
    ] = defaultdict(list)

    for class_ordinal, prepared_class in enumerate(context.classes):
        class_id = prepared_class.class_id
        assumption = model.new_bool_var(f"ro_assume_c{class_ordinal}")
        model.add_assumption(assumption)
        assumptions[assumption.index] = class_id
        choices: list[_RoomChoice] = []
        for room_ordinal, room_id in enumerate(room_domains[class_id]):
            selector = model.new_bool_var(
                f"ro_room_c{class_ordinal}_r{room_ordinal}"
            )
            model.add(selector <= assumption)
            choice = _RoomChoice(class_id, room_id, selector)
            choices.append(choice)
            selector_by_key[(class_id, room_id)] = selector
            if room_id is not None:
                for occurrence in resolved[class_id].occurrences():
                    occurrence_buckets[
                        (room_id, occurrence.week, occurrence.day)
                    ].append((occurrence.start, occurrence.end, class_id))
        model.add_exactly_one(choice.variable for choice in choices).only_enforce_if(
            assumption
        )
        selectors_by_class[class_id] = tuple(choices)
        if class_ordinal % 64 == 0 and _deadline_expired(deadline):
            return _result(
                started=started,
                status="DEADLINE_EXCEEDED",
                room_selectors=room_selectors,
                occurrence_records=occurrence_records,
            )

    clique_constraints = 0
    clique_literals = 0
    for bucket_ordinal, bucket in enumerate(sorted(occurrence_buckets)):
        room_id, _week, _day = bucket
        for clique in maximal_half_open_interval_cliques(
            occurrence_buckets[bucket]
        ):
            literals = tuple(
                selector_by_key[(class_id, room_id)] for class_id in clique
            )
            model.add_at_most_one(literals)
            clique_constraints += 1
            clique_literals += len(literals)
            if clique_literals > effective_limits.max_clique_literals:
                return _result(
                    started=started,
                    status="RESOURCE_LIMIT",
                    failure_reason=(
                        f"clique_literal_limit:{clique_literals}>"
                        f"{effective_limits.max_clique_literals}"
                    ),
                    room_selectors=room_selectors,
                    occurrence_records=occurrence_records,
                    clique_constraints=clique_constraints,
                    clique_literals=clique_literals,
                )
        if bucket_ordinal % 128 == 0 and _deadline_expired(deadline):
            return _result(
                started=started,
                status="DEADLINE_EXCEEDED",
                room_selectors=room_selectors,
                occurrence_records=occurrence_records,
                clique_constraints=clique_constraints,
                clique_literals=clique_literals,
            )

    travel = _travel_values(context.problem)
    pair_room_cells = 0
    seen_pairs: set[tuple[int, str, str]] = set()
    for distribution in context.distributions:
        if not distribution.required or distribution.base not in _PAIR_DISTRIBUTIONS:
            continue
        for first_id, second_id in combinations(distribution.class_ids, 2):
            pair_key = (distribution.source_ordinal, first_id, second_id)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            for first_choice in selectors_by_class[first_id]:
                first_placement = ITC2019ClassPlacement(
                    first_id,
                    options[first_id].days,
                    options[first_id].start,
                    options[first_id].weeks,
                    first_choice.room_id,
                )
                for second_choice in selectors_by_class[second_id]:
                    pair_room_cells += 1
                    if pair_room_cells > effective_limits.max_pair_room_cells:
                        return _result(
                            started=started,
                            status="RESOURCE_LIMIT",
                            failure_reason=(
                                f"pair_room_cell_limit:{pair_room_cells}>"
                                f"{effective_limits.max_pair_room_cells}"
                            ),
                            room_selectors=room_selectors,
                            occurrence_records=occurrence_records,
                            clique_constraints=clique_constraints,
                            clique_literals=clique_literals,
                            pair_room_cells=pair_room_cells,
                        )
                    second_placement = ITC2019ClassPlacement(
                        second_id,
                        options[second_id].days,
                        options[second_id].start,
                        options[second_id].weeks,
                        second_choice.room_id,
                    )
                    if not _pair_distribution_satisfied(
                        distribution.base,
                        distribution.parameters,
                        first_placement,
                        options[first_id],
                        second_placement,
                        options[second_id],
                        travel,
                    ):
                        model.add_at_most_one(
                            (first_choice.variable, second_choice.variable)
                        )
            if pair_room_cells % 4096 == 0 and _deadline_expired(deadline):
                return _result(
                    started=started,
                    status="DEADLINE_EXCEEDED",
                    room_selectors=room_selectors,
                    occurrence_records=occurrence_records,
                    clique_constraints=clique_constraints,
                    clique_literals=clique_literals,
                    pair_room_cells=pair_room_cells,
                )

    model_variables = len(model.proto.variables)
    model_constraints = len(model.proto.constraints)
    if model_variables > effective_limits.max_model_variables:
        return _result(
            started=started,
            status="RESOURCE_LIMIT",
            failure_reason=(
                f"model_variable_limit:{model_variables}>"
                f"{effective_limits.max_model_variables}"
            ),
            room_selectors=room_selectors,
            occurrence_records=occurrence_records,
            clique_constraints=clique_constraints,
            clique_literals=clique_literals,
            pair_room_cells=pair_room_cells,
            model_variables=model_variables,
            model_constraints=model_constraints,
        )
    if model_constraints > effective_limits.max_model_constraints:
        return _result(
            started=started,
            status="RESOURCE_LIMIT",
            failure_reason=(
                f"model_constraint_limit:{model_constraints}>"
                f"{effective_limits.max_model_constraints}"
            ),
            room_selectors=room_selectors,
            occurrence_records=occurrence_records,
            clique_constraints=clique_constraints,
            clique_literals=clique_literals,
            pair_room_cells=pair_room_cells,
            model_variables=model_variables,
            model_constraints=model_constraints,
        )
    model_error = model.validate()
    if model_error:
        return _result(
            started=started,
            status="MODEL_INVALID",
            failure_reason=model_error,
            room_selectors=room_selectors,
            occurrence_records=occurrence_records,
            clique_constraints=clique_constraints,
            clique_literals=clique_literals,
            pair_room_cells=pair_room_cells,
            model_variables=model_variables,
            model_constraints=model_constraints,
        )
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return _result(
            started=started,
            status="DEADLINE_EXCEEDED",
            room_selectors=room_selectors,
            occurrence_records=occurrence_records,
            clique_constraints=clique_constraints,
            clique_literals=clique_literals,
            pair_room_cells=pair_room_cells,
            model_variables=model_variables,
            model_constraints=model_constraints,
        )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(remaining)
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = int(random_seed)
    solver.parameters.stop_after_first_solution = True
    solver.parameters.core_minimization_level = 2
    status_code = solver.solve(model)
    solver_status = solver.status_name(status_code).upper()
    common = {
        "room_selectors": room_selectors,
        "occurrence_records": occurrence_records,
        "clique_constraints": clique_constraints,
        "clique_literals": clique_literals,
        "pair_room_cells": pair_room_cells,
        "model_variables": model_variables,
        "model_constraints": model_constraints,
        "solver_status": solver_status,
    }
    if _deadline_expired(deadline):
        return _result(started=started, status="DEADLINE_EXCEEDED", **common)
    if status_code == cp_model.INFEASIBLE:
        raw_core = {
            assumptions.get(int(literal))
            for literal in solver.sufficient_assumptions_for_infeasibility()
        }
        core_ids = tuple(
            class_id
            for class_id in source_order
            if class_id in raw_core
        )
        if _deadline_expired(deadline):
            return _result(started=started, status="DEADLINE_EXCEEDED", **common)
        return _result(
            started=started,
            status="INFEASIBLE",
            core=ITC2019RoomStructuralCore(core_ids),
            **common,
        )
    if status_code not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        return _result(started=started, status=solver_status, **common)

    placements: list[ITC2019ClassPlacement] = []
    room_rows: list[tuple[str, str | None]] = []
    for prepared_class in context.classes:
        class_id = prepared_class.class_id
        chosen = tuple(
            choice
            for choice in selectors_by_class[class_id]
            if solver.boolean_value(choice.variable)
        )
        if len(chosen) != 1:
            return _result(
                started=started,
                status="INVALID_RESULT",
                failure_reason=f"class_{class_id}_room_selection_count:{len(chosen)}",
                **common,
            )
        room_id = chosen[0].room_id
        room_rows.append((class_id, room_id))
        option = options[class_id]
        placements.append(
            ITC2019ClassPlacement(
                class_id,
                option.days,
                option.start,
                option.weeks,
                room_id,
            )
        )
    immutable = tuple(placements)
    timetable_problem = replace(context.problem, students=())
    validation_errors = tuple(
        validate_itc2019_solution(timetable_problem, immutable, {})
    )
    if validation_errors:
        return _result(
            started=started,
            status="INVALID_RESULT",
            failure_reason=validation_errors[0],
            **common,
        )
    certificate = ITC2019RoomCertificate(canonical, tuple(room_rows))
    return ITC2019RoomOracleResult(
        status="FEASIBLE",
        placements=immutable,
        certificate=certificate,
        wall_time_seconds=time.monotonic() - started,
        **common,
    )


__all__ = [
    "ITC2019RoomCertificate",
    "ITC2019RoomOracleLimits",
    "ITC2019RoomOracleResult",
    "ITC2019RoomStructuralCore",
    "maximal_half_open_interval_cliques",
    "solve_itc2019_room_oracle",
]
