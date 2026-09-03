"""Source-only checkpoint admission and bounded exact ITC-2019 frontier search.

Outside-frontier class times are fixed by frozen preprocessing.  Their rooms
are not fixed: the joint model assigns rooms for every class, so a local time
repair can still perform a global room repair.  Required pair and grouped
distributions are encoded over their full source membership, including every
frontier boundary crossing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from itertools import combinations, product
import math
import re
import time
from typing import Any, Iterable, Mapping, Sequence

from ortools.sat.python import cp_model

from benchmarks.itc2019 import (
    ITC2019ClassPlacement,
    ITC2019Problem,
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
    prepare_itc2019_context,
    validate_itc2019_partial_checkpoint,
)
from benchmarks.itc2019_room_oracle import maximal_half_open_interval_cliques


CHECKPOINT_SCHEMA = "planora.itc2019.frontier-checkpoint.v1"
CHECKPOINT_STATUS = "PARTIAL_FRONTIER"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CHECKPOINT_KEYS = frozenset(
    {
        "schema",
        "status",
        "assigned_class_ids",
        "open_class_ids",
        "canonical_times",
        "provenance_hashes",
        "competitor_schedule_or_result_used",
        "competitor_placement_or_hint_used",
        "admissible_as_solution",
    }
)


@dataclass(frozen=True, slots=True)
class ITC2019ProvenanceHash:
    name: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ITC2019FrontierCheckpoint:
    """Strict resumable time state; explicitly not a solution artifact."""

    assigned_class_ids: tuple[str, ...]
    open_class_ids: tuple[str, ...]
    canonical_times: ITC2019PartialCheckpoint
    provenance_hashes: tuple[ITC2019ProvenanceHash, ...]
    schema: str = CHECKPOINT_SCHEMA
    status: str = CHECKPOINT_STATUS
    competitor_schedule_or_result_used: bool = False
    competitor_placement_or_hint_used: bool = False
    admissible_as_solution: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "status": self.status,
            "assigned_class_ids": list(self.assigned_class_ids),
            "open_class_ids": list(self.open_class_ids),
            "canonical_times": [
                {
                    "class_id": entry.class_id,
                    "signature": list(entry.signature),
                }
                for entry in self.canonical_times.times
            ],
            "provenance_hashes": [
                {"name": entry.name, "sha256": entry.sha256}
                for entry in self.provenance_hashes
            ],
            "competitor_schedule_or_result_used": (
                self.competitor_schedule_or_result_used
            ),
            "competitor_placement_or_hint_used": (
                self.competitor_placement_or_hint_used
            ),
            "admissible_as_solution": self.admissible_as_solution,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ITC2019FrontierCheckpoint:
        if not isinstance(payload, Mapping):
            raise TypeError("frontier checkpoint must be a mapping")
        keys = frozenset(payload)
        missing = sorted(_CHECKPOINT_KEYS - keys)
        extra = sorted(keys - _CHECKPOINT_KEYS)
        if missing or extra:
            details = []
            if missing:
                details.append("missing keys: " + ", ".join(missing))
            if extra:
                details.append("unexpected keys: " + ", ".join(extra))
            raise ValueError("invalid frontier checkpoint shape; " + "; ".join(details))

        def string_tuple(key: str) -> tuple[str, ...]:
            raw = payload[key]
            if not isinstance(raw, list) or not all(
                isinstance(value, str) for value in raw
            ):
                raise TypeError(f"frontier checkpoint {key} must be a string list")
            return tuple(raw)

        raw_times = payload["canonical_times"]
        if not isinstance(raw_times, list):
            raise TypeError("frontier checkpoint canonical_times must be a list")
        time_entries: list[ITC2019CheckpointTime] = []
        for raw in raw_times:
            if not isinstance(raw, Mapping) or frozenset(raw) != {
                "class_id",
                "signature",
            }:
                raise ValueError("invalid canonical time entry shape")
            class_id = raw["class_id"]
            signature = raw["signature"]
            if not isinstance(class_id, str):
                raise TypeError("canonical time class_id must be a string")
            if (
                not isinstance(signature, list)
                or len(signature) != 4
                or not isinstance(signature[0], str)
                or type(signature[1]) is not int
                or type(signature[2]) is not int
                or not isinstance(signature[3], str)
            ):
                raise TypeError("canonical time signature has invalid types")
            time_entries.append(
                ITC2019CheckpointTime(
                    class_id,
                    (signature[0], signature[1], signature[2], signature[3]),
                )
            )

        raw_hashes = payload["provenance_hashes"]
        if not isinstance(raw_hashes, list):
            raise TypeError("frontier checkpoint provenance_hashes must be a list")
        hashes: list[ITC2019ProvenanceHash] = []
        for raw in raw_hashes:
            if not isinstance(raw, Mapping) or frozenset(raw) != {"name", "sha256"}:
                raise ValueError("invalid provenance hash entry shape")
            name = raw["name"]
            sha256 = raw["sha256"]
            if not isinstance(name, str) or not isinstance(sha256, str):
                raise TypeError("provenance name and sha256 must be strings")
            hashes.append(ITC2019ProvenanceHash(name, sha256))

        for key in (
            "competitor_schedule_or_result_used",
            "competitor_placement_or_hint_used",
            "admissible_as_solution",
        ):
            if type(payload[key]) is not bool:
                raise TypeError(f"frontier checkpoint {key} must be boolean")
        schema = payload["schema"]
        status = payload["status"]
        if not isinstance(schema, str) or not isinstance(status, str):
            raise TypeError("frontier checkpoint schema and status must be strings")
        return cls(
            assigned_class_ids=string_tuple("assigned_class_ids"),
            open_class_ids=string_tuple("open_class_ids"),
            canonical_times=ITC2019PartialCheckpoint(tuple(time_entries)),
            provenance_hashes=tuple(hashes),
            schema=schema,
            status=status,
            competitor_schedule_or_result_used=payload[
                "competitor_schedule_or_result_used"
            ],
            competitor_placement_or_hint_used=payload[
                "competitor_placement_or_hint_used"
            ],
            admissible_as_solution=payload["admissible_as_solution"],
        )


@dataclass(frozen=True, slots=True)
class ITC2019FrontierJointLimits:
    max_placement_literals: int = 500_000
    max_occurrence_records: int = 5_000_000
    max_clique_literals: int = 20_000_000
    max_pair_placement_cells: int = 30_000_000
    max_group_time_rows: int = 2_000_000
    max_model_variables: int = 750_000
    max_model_constraints: int = 30_000_000

    def validate(self) -> None:
        if min(
            self.max_placement_literals,
            self.max_occurrence_records,
            self.max_clique_literals,
            self.max_pair_placement_cells,
            self.max_group_time_rows,
            self.max_model_variables,
            self.max_model_constraints,
        ) <= 0:
            raise ValueError("frontier-joint limits must be positive")


@dataclass(frozen=True, slots=True)
class ITC2019FrontierJointResult:
    status: str
    placements: tuple[ITC2019ClassPlacement, ...] = ()
    canonical_times: ITC2019PartialCheckpoint | None = None
    failure_reason: str | None = None
    placement_literals: int = 0
    occurrence_records: int = 0
    clique_literals: int = 0
    pair_placement_cells: int = 0
    group_time_rows: int = 0
    model_variables: int = 0
    model_constraints: int = 0
    solver_status: str | None = None
    wall_time_seconds: float = 0.0

    @property
    def is_feasible(self) -> bool:
        return self.status == "FEASIBLE"


@dataclass(frozen=True, slots=True)
class _JointChoice:
    class_id: str
    time_index: int
    time: ITC2019PreparedTime
    room_id: str | None
    variable: cp_model.IntVar
    serial: int


def _require_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"frontier progress {field} must be a non-negative integer")
    return value


def select_final_round_frontier(
    progress: Mapping[str, object],
    known_class_ids: Iterable[str],
) -> tuple[str, ...]:
    """Select the source-order union of newly added final-round structural cuts."""

    ordered = tuple(known_class_ids)
    if len(set(ordered)) != len(ordered):
        raise ValueError("known class ids contain duplicates")
    known = set(ordered)
    if not isinstance(progress, Mapping):
        raise TypeError("frontier progress must be a mapping")
    round_value = _require_int(progress.get("round"), "round")
    last_round = progress.get("last_round")
    hall_cuts = progress.get("hall_cuts")
    property_cuts = progress.get("hall_property_cuts")
    if not isinstance(last_round, Mapping):
        raise ValueError("frontier progress is missing last_round")
    if not isinstance(hall_cuts, list) or not isinstance(property_cuts, list):
        raise ValueError("frontier progress cut collections must be lists")
    if _require_int(last_round.get("round"), "last_round.round") != round_value:
        raise ValueError("frontier progress last round does not match round")
    new_hall = _require_int(
        last_round.get("new_hall_cuts"), "last_round.new_hall_cuts"
    )
    new_property = _require_int(
        last_round.get("new_hall_property_cuts"),
        "last_round.new_hall_property_cuts",
    )
    if new_hall > len(hall_cuts) or new_property > len(property_cuts):
        raise ValueError("frontier progress final-round cut count exceeds history")
    if "total_hall_cuts" in last_round and _require_int(
        last_round["total_hall_cuts"], "last_round.total_hall_cuts"
    ) != len(hall_cuts):
        raise ValueError("frontier progress hall cut total is stale")
    if "total_hall_property_cuts" in last_round and _require_int(
        last_round["total_hall_property_cuts"],
        "last_round.total_hall_property_cuts",
    ) != len(property_cuts):
        raise ValueError("frontier progress hall-property cut total is stale")

    selected: set[str] = set()
    for raw_cut in hall_cuts[len(hall_cuts) - new_hall :]:
        if not isinstance(raw_cut, list):
            raise ValueError("frontier hall cut must be a list")
        for component in raw_cut:
            if (
                not isinstance(component, list)
                or len(component) != 2
                or not isinstance(component[0], str)
                or type(component[1]) is not int
                or component[1] < 0
            ):
                raise ValueError("frontier hall cut component is malformed")
            selected.add(component[0])
    for raw_cut in property_cuts[len(property_cuts) - new_property :]:
        if not isinstance(raw_cut, Mapping):
            raise ValueError("frontier hall-property cut must be a mapping")
        components = raw_cut.get("components")
        if not isinstance(components, list) or not all(
            isinstance(class_id, str) for class_id in components
        ):
            raise ValueError("frontier hall-property components are malformed")
        selected.update(components)
    unknown = sorted(selected - known)
    if unknown:
        raise ValueError(
            "frontier structural cuts contain unknown classes: "
            + ", ".join(unknown)
        )
    return tuple(class_id for class_id in ordered if class_id in selected)


def _normalize_hashes(
    values: Mapping[str, str] | Sequence[ITC2019ProvenanceHash],
) -> tuple[ITC2019ProvenanceHash, ...]:
    if isinstance(values, Mapping):
        rows = tuple(
            ITC2019ProvenanceHash(str(name), value)
            for name, value in values.items()
        )
    else:
        rows = tuple(values)
    if not rows:
        raise ValueError("frontier checkpoint requires provenance hashes")
    if not all(isinstance(row, ITC2019ProvenanceHash) for row in rows):
        raise TypeError("provenance must contain provenance-hash entries")
    names = tuple(row.name for row in rows)
    if any(not name for name in names):
        raise ValueError("provenance hash names must be non-empty")
    duplicates = sorted(name for name in set(names) if names.count(name) > 1)
    if duplicates:
        raise ValueError(
            "provenance contains duplicate names: " + ", ".join(duplicates)
        )
    for row in rows:
        if _SHA256_PATTERN.fullmatch(row.sha256) is None:
            raise ValueError(f"provenance hash {row.name!r} is not canonical sha256")
    return tuple(sorted(rows, key=lambda row: row.name))


def _normalize_complete_times(
    problem: ITC2019Problem,
    checkpoint: ITC2019PartialCheckpoint,
) -> ITC2019PartialCheckpoint:
    class_ids = tuple(klass.id for klass in problem.classes)
    by_id: dict[str, ITC2019CheckpointTime] = {}
    duplicates: set[str] = set()
    for entry in checkpoint.times:
        if entry.class_id in by_id:
            duplicates.add(entry.class_id)
        else:
            by_id[entry.class_id] = entry
    if duplicates:
        raise ValueError(
            "canonical times contain duplicate classes: "
            + ", ".join(sorted(duplicates))
        )
    unknown = sorted(set(by_id) - set(class_ids))
    if unknown:
        raise ValueError(
            "canonical times contain unknown classes: " + ", ".join(unknown)
        )
    missing = tuple(class_id for class_id in class_ids if class_id not in by_id)
    if missing:
        raise ValueError(
            "canonical times are missing classes: " + ", ".join(missing)
        )
    return ITC2019PartialCheckpoint(tuple(by_id[class_id] for class_id in class_ids))


def create_frontier_checkpoint(
    problem: ITC2019Problem,
    incumbent: ITC2019PartialCheckpoint,
    *,
    open_class_ids: Iterable[str],
    provenance_hashes: Mapping[str, str] | Sequence[ITC2019ProvenanceHash],
    deadline: float,
) -> ITC2019FrontierCheckpoint:
    """Create a canonical resumable frontier artifact from source-only times."""

    if not math.isfinite(deadline) or time.monotonic() >= deadline:
        raise TimeoutError("frontier checkpoint creation exceeded deadline")
    class_ids = tuple(klass.id for klass in problem.classes)
    raw_open = tuple(open_class_ids)
    if len(set(raw_open)) != len(raw_open):
        raise ValueError("open class ids contain duplicates")
    unknown = sorted(set(raw_open) - set(class_ids))
    if unknown:
        raise ValueError("open class ids contain unknown classes: " + ", ".join(unknown))
    open_set = set(raw_open)
    ordered_open = tuple(class_id for class_id in class_ids if class_id in open_set)
    assigned = tuple(class_id for class_id in class_ids if class_id not in open_set)
    normalized = _normalize_complete_times(problem, incumbent)
    errors = validate_itc2019_partial_checkpoint(
        problem,
        normalized,
        open_class_ids=ordered_open,
        deadline=deadline,
    )
    if errors:
        raise ValueError("invalid canonical frontier times: " + "; ".join(errors))
    hashes = _normalize_hashes(provenance_hashes)
    if time.monotonic() >= deadline:
        raise TimeoutError("frontier checkpoint creation exceeded deadline")
    return ITC2019FrontierCheckpoint(
        assigned_class_ids=assigned,
        open_class_ids=ordered_open,
        canonical_times=normalized,
        provenance_hashes=hashes,
    )


def admit_frontier_checkpoint(
    problem: ITC2019Problem,
    checkpoint: ITC2019FrontierCheckpoint | Mapping[str, object],
    *,
    expected_provenance_hashes: Mapping[str, str]
    | Sequence[ITC2019ProvenanceHash],
    deadline: float,
) -> ITC2019PreparedContext:
    """Fail closed on schema, partition, provenance, or canonical-time drift."""

    if not math.isfinite(deadline) or time.monotonic() >= deadline:
        raise TimeoutError("frontier checkpoint admission exceeded deadline")
    value = (
        ITC2019FrontierCheckpoint.from_dict(checkpoint)
        if isinstance(checkpoint, Mapping)
        else checkpoint
    )
    if not isinstance(value, ITC2019FrontierCheckpoint):
        raise TypeError("checkpoint must be a frontier checkpoint or mapping")
    if value.schema != CHECKPOINT_SCHEMA or value.status != CHECKPOINT_STATUS:
        raise ValueError("frontier checkpoint schema or status is stale")
    if (
        value.competitor_schedule_or_result_used
        or value.competitor_placement_or_hint_used
        or value.admissible_as_solution
    ):
        raise ValueError("frontier checkpoint provenance or admissibility flags reject it")

    class_ids = tuple(klass.id for klass in problem.classes)
    assigned = value.assigned_class_ids
    opened = value.open_class_ids
    if len(set(assigned)) != len(assigned) or len(set(opened)) != len(opened):
        raise ValueError("frontier checkpoint partition contains duplicates")
    if set(assigned) & set(opened):
        raise ValueError("frontier checkpoint assigned/open partitions overlap")
    if set(assigned) | set(opened) != set(class_ids):
        raise ValueError("frontier checkpoint assigned/open partition is incomplete")
    open_set = set(opened)
    if assigned != tuple(class_id for class_id in class_ids if class_id not in open_set):
        raise ValueError("frontier checkpoint assigned partition is not source ordered")
    if opened != tuple(class_id for class_id in class_ids if class_id in open_set):
        raise ValueError("frontier checkpoint open partition is not source ordered")
    normalized = _normalize_complete_times(problem, value.canonical_times)
    actual_hashes = _normalize_hashes(value.provenance_hashes)
    expected_hashes = _normalize_hashes(expected_provenance_hashes)
    if actual_hashes != expected_hashes:
        raise ValueError("frontier checkpoint provenance hashes are stale")
    errors = validate_itc2019_partial_checkpoint(
        problem,
        normalized,
        open_class_ids=opened,
        deadline=deadline,
    )
    if errors:
        raise ValueError("frontier checkpoint canonical times are invalid: " + "; ".join(errors))
    return prepare_itc2019_context(
        problem,
        incumbent=normalized,
        open_class_ids=opened,
        deadline=deadline,
    )


def _option(value: ITC2019PreparedTime) -> ITC2019TimeOption:
    return ITC2019TimeOption(
        value.days,
        value.start,
        value.length,
        value.weeks,
        value.penalty,
        value.extra_attributes,
    )


def _failure(
    started: float,
    status: str,
    *,
    reason: str | None = None,
    counts: Mapping[str, int] | None = None,
    solver_status: str | None = None,
) -> ITC2019FrontierJointResult:
    values = dict(counts or {})
    return ITC2019FrontierJointResult(
        status=status,
        failure_reason=reason,
        solver_status=solver_status,
        wall_time_seconds=time.monotonic() - started,
        **values,
    )


def solve_itc2019_frontier_joint(
    context: ITC2019PreparedContext,
    *,
    deadline: float,
    random_seed: int = 17,
    limits: ITC2019FrontierJointLimits | None = None,
) -> ITC2019FrontierJointResult:
    """Build and solve one bounded exact joint time-room frontier candidate."""

    started = time.monotonic()
    if not math.isfinite(deadline):
        raise ValueError("frontier-joint deadline must be finite")
    if random_seed < 0:
        raise ValueError("frontier-joint random seed must be non-negative")
    effective_limits = limits or ITC2019FrontierJointLimits()
    effective_limits.validate()
    if time.monotonic() >= deadline:
        return _failure(started, "DEADLINE_EXCEEDED")

    placement_count = sum(
        len(time_value.legal_room_ids)
        for prepared_class in context.classes
        for time_value in prepared_class.times
    )
    occurrence_count = sum(
        time_value.occurrence_count * (room_id is not None)
        for prepared_class in context.classes
        for time_value in prepared_class.times
        for room_id in time_value.legal_room_ids
    )
    counts = {
        "placement_literals": placement_count,
        "occurrence_records": occurrence_count,
    }
    if placement_count > effective_limits.max_placement_literals:
        return _failure(
            started,
            "RESOURCE_LIMIT",
            reason=(
                f"placement_literal_limit:{placement_count}>"
                f"{effective_limits.max_placement_literals}"
            ),
            counts=counts,
        )
    if occurrence_count > effective_limits.max_occurrence_records:
        return _failure(
            started,
            "RESOURCE_LIMIT",
            reason=(
                f"occurrence_record_limit:{occurrence_count}>"
                f"{effective_limits.max_occurrence_records}"
            ),
            counts=counts,
        )

    model = cp_model.CpModel()
    choices_by_class: dict[str, tuple[_JointChoice, ...]] = {}
    choices_by_time: dict[str, tuple[tuple[_JointChoice, ...], ...]] = {}
    time_selectors: dict[str, tuple[cp_model.IntVar, ...]] = {}
    time_choices: dict[str, cp_model.IntVar] = {}
    occurrence_buckets: dict[
        tuple[str, int, int], list[tuple[int, int, str]]
    ] = defaultdict(list)
    choice_by_key: dict[str, _JointChoice] = {}
    objective_terms: list[Any] = []
    serial = 0
    for class_ordinal, prepared_class in enumerate(context.classes):
        selectors = tuple(
            model.new_bool_var(f"fj_t_c{class_ordinal}_{time_index}")
            for time_index in range(len(prepared_class.times))
        )
        time_selectors[prepared_class.class_id] = selectors
        if len(selectors) == 1:
            choice_var = model.new_constant(0)
        else:
            choice_var = model.new_int_var(
                0, len(selectors) - 1, f"fj_time_c{class_ordinal}"
            )
            model.add(choice_var == sum(i * value for i, value in enumerate(selectors)))
        time_choices[prepared_class.class_id] = choice_var
        class_choices: list[_JointChoice] = []
        by_time: list[list[_JointChoice]] = [[] for _ in selectors]
        for time_index, time_value in enumerate(prepared_class.times):
            for room_ordinal, room_id in enumerate(time_value.legal_room_ids):
                variable = model.new_bool_var(
                    f"fj_p_c{class_ordinal}_t{time_index}_r{room_ordinal}"
                )
                key = f"p{serial}"
                choice = _JointChoice(
                    prepared_class.class_id,
                    time_index,
                    time_value,
                    room_id,
                    variable,
                    serial,
                )
                serial += 1
                class_choices.append(choice)
                by_time[time_index].append(choice)
                choice_by_key[key] = choice
                if room_id is not None:
                    for occurrence in time_value.occurrences():
                        occurrence_buckets[
                            (room_id, occurrence.week, occurrence.day)
                        ].append((occurrence.start, occurrence.end, key))
                room_penalty = next(
                    (
                        room.penalty
                        for room in prepared_class.rooms
                        if room.room_id == room_id
                    ),
                    0,
                )
                if time_value.penalty or room_penalty:
                    objective_terms.append(
                        (time_value.penalty + room_penalty) * variable
                    )
        model.add_exactly_one(choice.variable for choice in class_choices)
        for time_index, values in enumerate(by_time):
            model.add(sum(choice.variable for choice in values) == selectors[time_index])
        choices_by_class[prepared_class.class_id] = tuple(class_choices)
        choices_by_time[prepared_class.class_id] = tuple(tuple(row) for row in by_time)
        incumbent = prepared_class.incumbent_signature
        if prepared_class.is_open and incumbent is not None:
            for index, time_value in enumerate(prepared_class.times):
                if time_value.signature != incumbent:
                    objective_terms.append(1_000_000 * selectors[index])
        if class_ordinal % 32 == 0 and time.monotonic() >= deadline:
            return _failure(started, "DEADLINE_EXCEEDED", counts=counts)

    clique_literals = 0
    clique_constraints = 0
    for bucket_ordinal, bucket in enumerate(sorted(occurrence_buckets)):
        for clique in maximal_half_open_interval_cliques(occurrence_buckets[bucket]):
            model.add_at_most_one(choice_by_key[key].variable for key in clique)
            clique_constraints += 1
            clique_literals += len(clique)
            if clique_literals > effective_limits.max_clique_literals:
                counts.update(
                    clique_literals=clique_literals,
                )
                return _failure(
                    started,
                    "RESOURCE_LIMIT",
                    reason=(
                        f"clique_literal_limit:{clique_literals}>"
                        f"{effective_limits.max_clique_literals}"
                    ),
                    counts=counts,
                )
        if bucket_ordinal % 64 == 0 and time.monotonic() >= deadline:
            counts.update(clique_literals=clique_literals)
            return _failure(started, "DEADLINE_EXCEEDED", counts=counts)

    travel = _travel_values(context.problem)
    pair_cells = 0
    group_rows = 0
    for distribution in context.distributions:
        if not distribution.required:
            continue
        if distribution.base in _PAIR_DISTRIBUTIONS:
            for first_id, second_id in combinations(distribution.class_ids, 2):
                for first_choice in choices_by_class[first_id]:
                    first_time = _option(first_choice.time)
                    first_placement = ITC2019ClassPlacement(
                        first_id,
                        first_time.days,
                        first_time.start,
                        first_time.weeks,
                        first_choice.room_id,
                    )
                    for second_choice in choices_by_class[second_id]:
                        pair_cells += 1
                        if pair_cells > effective_limits.max_pair_placement_cells:
                            counts.update(
                                clique_literals=clique_literals,
                                pair_placement_cells=pair_cells,
                                group_time_rows=group_rows,
                            )
                            return _failure(
                                started,
                                "RESOURCE_LIMIT",
                                reason=(
                                    f"pair_placement_cell_limit:{pair_cells}>"
                                    f"{effective_limits.max_pair_placement_cells}"
                                ),
                                counts=counts,
                            )
                        second_time = _option(second_choice.time)
                        second_placement = ITC2019ClassPlacement(
                            second_id,
                            second_time.days,
                            second_time.start,
                            second_time.weeks,
                            second_choice.room_id,
                        )
                        if not _pair_distribution_satisfied(
                            distribution.base,
                            distribution.parameters,
                            first_placement,
                            first_time,
                            second_placement,
                            second_time,
                            travel,
                        ):
                            model.add_at_most_one(
                                (first_choice.variable, second_choice.variable)
                            )
                        if (
                            pair_cells % 4096 == 0
                            and time.monotonic() >= deadline
                        ):
                            counts.update(
                                clique_literals=clique_literals,
                                pair_placement_cells=pair_cells,
                                group_time_rows=group_rows,
                            )
                            return _failure(
                                started, "DEADLINE_EXCEEDED", counts=counts
                            )
        else:
            domain_sizes = tuple(
                len(context.class_for(class_id).times)
                for class_id in distribution.class_ids
            )
            row_count = math.prod(domain_sizes)
            group_rows += row_count
            if group_rows > effective_limits.max_group_time_rows:
                counts.update(
                    clique_literals=clique_literals,
                    pair_placement_cells=pair_cells,
                    group_time_rows=group_rows,
                )
                return _failure(
                    started,
                    "RESOURCE_LIMIT",
                    reason=(
                        f"group_time_row_limit:{group_rows}>"
                        f"{effective_limits.max_group_time_rows}"
                    ),
                    counts=counts,
                )
            allowed: list[tuple[int, ...]] = []
            class_times = tuple(
                context.class_for(class_id).times
                for class_id in distribution.class_ids
            )
            for row in product(*(range(size) for size in domain_sizes)):
                resolved = {
                    class_id: _option(class_times[index][time_index])
                    for index, (class_id, time_index) in enumerate(
                        zip(distribution.class_ids, row, strict=True)
                    )
                }
                if not _special_distribution_units(
                    context.problem,
                    distribution.base,
                    distribution.parameters,
                    distribution.class_ids,
                    resolved,
                ):
                    allowed.append(row)
                if time.monotonic() >= deadline:
                    counts.update(
                        clique_literals=clique_literals,
                        pair_placement_cells=pair_cells,
                        group_time_rows=group_rows,
                    )
                    return _failure(started, "DEADLINE_EXCEEDED", counts=counts)
            if time.monotonic() >= deadline:
                counts.update(
                    clique_literals=clique_literals,
                    pair_placement_cells=pair_cells,
                    group_time_rows=group_rows,
                )
                return _failure(started, "DEADLINE_EXCEEDED", counts=counts)
            if not allowed:
                counts.update(
                    clique_literals=clique_literals,
                    pair_placement_cells=pair_cells,
                    group_time_rows=group_rows,
                )
                return _failure(
                    started,
                    "INFEASIBLE",
                    reason=f"required_group_has_no_allowed_rows:{distribution.source_ordinal}",
                    counts=counts,
                )
            model.add_allowed_assignments(
                tuple(time_choices[class_id] for class_id in distribution.class_ids),
                allowed,
            )

    if objective_terms:
        model.minimize(sum(objective_terms))
    model_variables = len(model.proto.variables)
    model_constraints = len(model.proto.constraints)
    counts.update(
        clique_literals=clique_literals,
        pair_placement_cells=pair_cells,
        group_time_rows=group_rows,
        model_variables=model_variables,
        model_constraints=model_constraints,
    )
    if model_variables > effective_limits.max_model_variables:
        return _failure(
            started,
            "RESOURCE_LIMIT",
            reason=(
                f"model_variable_limit:{model_variables}>"
                f"{effective_limits.max_model_variables}"
            ),
            counts=counts,
        )
    if model_constraints > effective_limits.max_model_constraints:
        return _failure(
            started,
            "RESOURCE_LIMIT",
            reason=(
                f"model_constraint_limit:{model_constraints}>"
                f"{effective_limits.max_model_constraints}"
            ),
            counts=counts,
        )
    model_error = model.validate()
    if model_error:
        return _failure(
            started, "MODEL_INVALID", reason=model_error, counts=counts
        )
    if time.monotonic() >= deadline:
        return _failure(started, "DEADLINE_EXCEEDED", counts=counts)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return _failure(started, "DEADLINE_EXCEEDED", counts=counts)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(remaining)
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = int(random_seed)
    status_code = solver.solve(model)
    solver_status = solver.status_name(status_code).upper()
    if time.monotonic() >= deadline:
        return _failure(
            started,
            "DEADLINE_EXCEEDED",
            counts=counts,
            solver_status=solver_status,
        )
    if status_code not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        return _failure(
            started, solver_status, counts=counts, solver_status=solver_status
        )

    placements: list[ITC2019ClassPlacement] = []
    checkpoint_entries: list[ITC2019CheckpointTime] = []
    for class_ordinal, prepared_class in enumerate(context.classes):
        selected = tuple(
            choice
            for choice in choices_by_class[prepared_class.class_id]
            if solver.boolean_value(choice.variable)
        )
        if len(selected) != 1:
            return _failure(
                started,
                "INVALID_RESULT",
                reason=(
                    f"class_{prepared_class.class_id}_placement_count:{len(selected)}"
                ),
                counts=counts,
                solver_status=solver_status,
            )
        choice = selected[0]
        placements.append(
            ITC2019ClassPlacement(
                prepared_class.class_id,
                choice.time.days,
                choice.time.start,
                choice.time.weeks,
                choice.room_id,
            )
        )
        checkpoint_entries.append(
            ITC2019CheckpointTime(prepared_class.class_id, choice.time.signature)
        )
        if class_ordinal % 128 == 0 and time.monotonic() >= deadline:
            return _failure(
                started,
                "DEADLINE_EXCEEDED",
                counts=counts,
                solver_status=solver_status,
            )
    if time.monotonic() >= deadline:
        return _failure(
            started,
            "DEADLINE_EXCEEDED",
            counts=counts,
            solver_status=solver_status,
        )
    immutable = tuple(placements)
    validation_errors = tuple(
        validate_itc2019_solution(replace(context.problem, students=()), immutable, {})
    )
    if time.monotonic() >= deadline:
        return _failure(
            started,
            "DEADLINE_EXCEEDED",
            counts=counts,
            solver_status=solver_status,
        )
    if validation_errors:
        return _failure(
            started,
            "INVALID_RESULT",
            reason=validation_errors[0],
            counts=counts,
            solver_status=solver_status,
        )
    return ITC2019FrontierJointResult(
        status="FEASIBLE",
        placements=immutable,
        canonical_times=ITC2019PartialCheckpoint(tuple(checkpoint_entries)),
        solver_status=solver_status,
        wall_time_seconds=time.monotonic() - started,
        **counts,
    )


# Explicit aliases keep call sites readable while retaining compact public names.
admit_itc2019_frontier_checkpoint = admit_frontier_checkpoint
create_itc2019_frontier_checkpoint = create_frontier_checkpoint
select_itc2019_final_round_frontier = select_final_round_frontier


__all__ = [
    "CHECKPOINT_SCHEMA",
    "CHECKPOINT_STATUS",
    "ITC2019FrontierCheckpoint",
    "ITC2019FrontierJointLimits",
    "ITC2019FrontierJointResult",
    "ITC2019ProvenanceHash",
    "admit_frontier_checkpoint",
    "admit_itc2019_frontier_checkpoint",
    "create_frontier_checkpoint",
    "create_itc2019_frontier_checkpoint",
    "select_final_round_frontier",
    "select_itc2019_final_round_frontier",
    "solve_itc2019_frontier_joint",
]
