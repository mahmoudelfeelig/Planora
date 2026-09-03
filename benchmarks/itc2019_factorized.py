from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
import time
from typing import Any, Mapping, Sequence

from ortools.sat.python import cp_model

from benchmarks.itc2019 import (
    ITC2019ClassPlacement,
    ITC2019FactorizedScaleEstimate,
    ITC2019NativeSolveResult,
    ITC2019Problem,
    ITC2019RoomOption,
    ITC2019TimeOption,
    _class_context,
    _itc2019_native_failure,
    _travel_values,
    _validate_problem_references,
    _distribution_spec,
    score_itc2019_solution,
    solve_itc2019_student_sectioning,
    validate_itc2019_solution,
)


_TIME_ONLY_PAIR_DISTRIBUTIONS = frozenset(
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
_ROOM_ONLY_PAIR_DISTRIBUTIONS = frozenset({"SameRoom", "DifferentRoom"})


class _EncodingScaleExceeded(RuntimeError):
    pass


class _EncodingInfeasible(RuntimeError):
    pass


@dataclass
class _CellBudget:
    limit: int
    used: int = 0

    def claim(self, cells: int, label: str) -> None:
        if cells < 0 or self.used + cells > self.limit:
            raise _EncodingScaleExceeded(
                f"factorized {label} needs more than {self.limit} predicate cells"
            )
        self.used += cells


@dataclass
class _SparseRoomBudget:
    limit: int
    used: int = 0

    def claim(self, constraints: int, label: str) -> None:
        if constraints < 0 or self.used + constraints > self.limit:
            raise _EncodingScaleExceeded(
                f"factorized {label} needs more than {self.limit} sparse room constraints"
            )
        self.used += constraints


@dataclass(frozen=True)
class _FactorizedDomains:
    times: Mapping[str, tuple[ITC2019TimeOption, ...]]
    rooms: Mapping[str, tuple[ITC2019RoomOption | None, ...]]

    @property
    def time_values(self) -> int:
        return sum(len(values) for values in self.times.values())

    @property
    def room_values(self) -> int:
        return sum(len(values) for values in self.rooms.values())


@dataclass(frozen=True)
class _Indicator:
    variable: Any
    constant: int | None = None


@dataclass(frozen=True)
class _ScalarFeature:
    value: Any
    minimum: int
    maximum: int


@dataclass(frozen=True)
class _GroupEncodingEstimate:
    cells: int


def _factorized_failure(
    *,
    status: str,
    started: float,
    build_started: float,
    random_seed: int,
    workers: int,
    domains: _FactorizedDomains | None = None,
    budget: _CellBudget | None = None,
    sparse_room_budget: _SparseRoomBudget | None = None,
    validation_errors: Sequence[str] = (),
    unsupported_reasons: Sequence[str] = (),
    sectioning_mode: str = "not_started",
) -> ITC2019NativeSolveResult:
    result = _itc2019_native_failure(
        status=status,
        started=started,
        build_started=build_started,
        random_seed=random_seed,
        workers=workers,
        validation_errors=validation_errors,
        unsupported_reasons=unsupported_reasons,
    )
    return ITC2019NativeSolveResult(
        **{
            **result.to_dict(),
            "formulation": "factorized_domains_v2",
            "sectioning_mode": sectioning_mode,
            "time_domain_values": domains.time_values if domains is not None else 0,
            "room_domain_values": domains.room_values if domains is not None else 0,
            "predicate_table_cells": budget.used if budget is not None else 0,
            "sparse_room_constraints": (
                sparse_room_budget.used if sparse_room_budget is not None else 0
            ),
        }
    )


def _build_factorized_domains(
    problem: ITC2019Problem,
    *,
    deadline: float,
) -> _FactorizedDomains:
    times, rooms = _unique_factorized_domains(problem, deadline=deadline)
    for klass in problem.classes:
        if not times[klass.id] or not rooms[klass.id]:
            raise _EncodingInfeasible(
                f"class {klass.id} has no factorized time or room domain"
            )
        if time.monotonic() >= deadline:
            raise TimeoutError("ITC-2019 factorized domain construction timed out")

    return _FactorizedDomains(times=times, rooms=rooms)


class _PairEncoder:
    def __init__(
        self,
        *,
        problem: ITC2019Problem,
        model: cp_model.CpModel,
        domains: _FactorizedDomains,
        time_choices: Mapping[str, cp_model.IntVar],
        time_selectors: Mapping[str, tuple[cp_model.IntVar, ...]],
        room_assignments: Mapping[str, cp_model.IntVar],
        room_selectors: Mapping[str, tuple[cp_model.IntVar, ...]],
        sparse_room_budget: _SparseRoomBudget,
        deadline: float,
        max_room_pair_evaluations_per_pair: int | None = None,
    ) -> None:
        self.problem = problem
        self.model = model
        self.domains = domains
        self.time_choices = time_choices
        self.time_selectors = time_selectors
        self.room_assignments = room_assignments
        self.room_selectors = room_selectors
        self.sparse_room_budget = sparse_room_budget
        self.deadline = deadline
        self.max_room_pair_evaluations_per_pair = max_room_pair_evaluations_per_pair
        self._indicators: dict[tuple[str, str, str, str], _Indicator] = {}
        self._same_attendees: dict[tuple[str, str, str], _Indicator] = {}
        self._scalar_features: dict[tuple[str, str], _ScalarFeature] = {}
        self._mask_bits: dict[tuple[str, str, int], _Indicator] = {}
        self._mask_overlaps: dict[tuple[str, str, str], _Indicator] = {}
        self._room_pair_indicators: dict[
            tuple[str, int, str, int], cp_model.IntVar
        ] = {}
        self._travel = _travel_values(problem)

    def fixed(self, value: int, name: str) -> _Indicator:
        del name
        return _Indicator(variable=int(value), constant=int(value))

    def check_deadline(self) -> None:
        if time.monotonic() >= self.deadline:
            raise TimeoutError("ITC-2019 factorized predicate encoding timed out")

    def _scalar_feature(
        self,
        class_id: str,
        key: str,
        values: Sequence[int],
    ) -> _ScalarFeature:
        cache_key = (class_id, key)
        cached = self._scalar_features.get(cache_key)
        if cached is not None:
            return cached
        minimum = min(values)
        maximum = max(values)
        if minimum == maximum:
            result = _ScalarFeature(minimum, minimum, maximum)
        else:
            variable = self.model.new_int_var(
                minimum,
                maximum,
                f"time_feature_{key}_{class_id}",
            )
            self.model.add_element(self.time_choices[class_id], values, variable)
            result = _ScalarFeature(variable, minimum, maximum)
        self._scalar_features[cache_key] = result
        return result

    def _start(self, class_id: str) -> _ScalarFeature:
        return self._scalar_feature(
            class_id,
            "start",
            [option.start for option in self.domains.times[class_id]],
        )

    def _end(self, class_id: str) -> _ScalarFeature:
        return self._scalar_feature(
            class_id,
            "end",
            [option.start + option.length for option in self.domains.times[class_id]],
        )

    def _first_active(self, class_id: str, dimension: str) -> _ScalarFeature:
        return self._scalar_feature(
            class_id,
            f"first_{dimension}",
            [
                (option.days if dimension == "day" else option.weeks).index("1")
                for option in self.domains.times[class_id]
            ],
        )

    def _mask_bit(self, class_id: str, dimension: str, index: int) -> _Indicator:
        cache_key = (class_id, dimension, index)
        cached = self._mask_bits.get(cache_key)
        if cached is not None:
            return cached
        masks = [
            option.days if dimension == "day" else option.weeks
            for option in self.domains.times[class_id]
        ]
        active = [
            selector
            for selector, mask in zip(self.time_selectors[class_id], masks, strict=True)
            if mask[index] == "1"
        ]
        inactive = [
            selector
            for selector, mask in zip(self.time_selectors[class_id], masks, strict=True)
            if mask[index] == "0"
        ]
        if not active:
            result = self.fixed(0, f"{dimension}_{class_id}_{index}_inactive")
        elif not inactive:
            result = self.fixed(1, f"{dimension}_{class_id}_{index}_active")
        else:
            selected = active if len(active) <= len(inactive) else inactive
            if len(selected) == 1:
                literal = selected[0]
            else:
                literal = self.model.new_bool_var(
                    f"{dimension}_{class_id}_{index}_{'on' if selected is active else 'off'}"
                )
                self.model.add_max_equality(literal, selected)
            result = _Indicator(
                variable=(literal if selected is active else literal.negated())
            )
        self._mask_bits[cache_key] = result
        return result

    @staticmethod
    def _negated(indicator: _Indicator) -> _Indicator:
        if indicator.constant is not None:
            value = 1 - indicator.constant
            return _Indicator(variable=value, constant=value)
        return _Indicator(
            variable=indicator.variable.negated(),
        )

    def _and(self, indicators: Sequence[_Indicator], name: str) -> _Indicator:
        if any(indicator.constant == 0 for indicator in indicators):
            return self.fixed(0, f"{name}_false")
        variables = [
            indicator.variable for indicator in indicators if indicator.constant is None
        ]
        if not variables:
            return self.fixed(1, f"{name}_true")
        if len(variables) == 1:
            return _Indicator(variable=variables[0])
        result = self.model.new_bool_var(name)
        self.model.add_min_equality(result, variables)
        return _Indicator(variable=result)

    def _or(self, indicators: Sequence[_Indicator], name: str) -> _Indicator:
        if any(indicator.constant == 1 for indicator in indicators):
            return self.fixed(1, f"{name}_true")
        variables = [
            indicator.variable for indicator in indicators if indicator.constant is None
        ]
        if not variables:
            return self.fixed(0, f"{name}_false")
        if len(variables) == 1:
            return _Indicator(variable=variables[0])
        result = self.model.new_bool_var(name)
        self.model.add_max_equality(result, variables)
        return _Indicator(variable=result)

    def _comparison(
        self,
        left: Any,
        operator: str,
        right: Any,
        name: str,
    ) -> _Indicator:
        if isinstance(left, int) and isinstance(right, int):
            comparisons = {
                "eq": left == right,
                "lt": left < right,
                "le": left <= right,
                "gt": left > right,
            }
            return self.fixed(int(comparisons[operator]), f"{name}_constant")
        result = self.model.new_bool_var(name)
        if operator == "eq":
            self.model.add(left == right).only_enforce_if(result)
            self.model.add(left != right).only_enforce_if(result.negated())
        elif operator == "lt":
            self.model.add(left < right).only_enforce_if(result)
            self.model.add(left >= right).only_enforce_if(result.negated())
        elif operator == "le":
            self.model.add(left <= right).only_enforce_if(result)
            self.model.add(left > right).only_enforce_if(result.negated())
        elif operator == "gt":
            self.model.add(left > right).only_enforce_if(result)
            self.model.add(left <= right).only_enforce_if(result.negated())
        else:  # pragma: no cover - internal callers are exhaustive
            raise ValueError(f"unsupported comparison operator {operator!r}")
        return _Indicator(variable=result)

    def _mask_overlap(
        self,
        first_id: str,
        second_id: str,
        dimension: str,
    ) -> _Indicator:
        first_id, second_id = sorted((first_id, second_id))
        cache_key = (dimension, first_id, second_id)
        cached = self._mask_overlaps.get(cache_key)
        if cached is not None:
            return cached
        width = self.problem.nr_days if dimension == "day" else self.problem.nr_weeks
        overlaps = [
            self._and(
                (
                    self._mask_bit(first_id, dimension, index),
                    self._mask_bit(second_id, dimension, index),
                ),
                f"{dimension}_overlap_{first_id}_{second_id}_{index}",
            )
            for index in range(width)
        ]
        result = self._or(
            overlaps,
            f"{dimension}_overlap_{first_id}_{second_id}",
        )
        self._mask_overlaps[cache_key] = result
        return result

    def _mask_subset(
        self,
        first_id: str,
        second_id: str,
        dimension: str,
        name: str,
    ) -> _Indicator:
        width = self.problem.nr_days if dimension == "day" else self.problem.nr_weeks
        implications = [
            self._or(
                (
                    self._negated(self._mask_bit(first_id, dimension, index)),
                    self._mask_bit(second_id, dimension, index),
                ),
                f"{name}_{index}",
            )
            for index in range(width)
        ]
        return self._and(implications, name)

    def time_distribution_violation(
        self,
        first_id: str,
        second_id: str,
        base: str,
        parameters: tuple[int, ...],
        predicate_key: str,
    ) -> _Indicator:
        cache_key = ("time", first_id, second_id, f"{base}{parameters}")
        cached = self._indicators.get(cache_key)
        if cached is not None:
            return cached

        prefix = f"time_{predicate_key}_{first_id}_{second_id}"

        if base == "SameStart":
            satisfied = self._comparison(
                self._start(first_id).value,
                "eq",
                self._start(second_id).value,
                f"{prefix}_satisfied",
            )
        elif base == "SameTime":
            first_start = self._start(first_id).value
            second_start = self._start(second_id).value
            first_end = self._end(first_id).value
            second_end = self._end(second_id).value
            first_contains = self._and(
                (
                    self._comparison(
                        first_start, "le", second_start, f"{prefix}_first_starts"
                    ),
                    self._comparison(
                        second_end, "le", first_end, f"{prefix}_first_ends"
                    ),
                ),
                f"{prefix}_first_contains",
            )
            second_contains = self._and(
                (
                    self._comparison(
                        second_start, "le", first_start, f"{prefix}_second_starts"
                    ),
                    self._comparison(
                        first_end, "le", second_end, f"{prefix}_second_ends"
                    ),
                ),
                f"{prefix}_second_contains",
            )
            satisfied = self._or(
                (first_contains, second_contains), f"{prefix}_satisfied"
            )
        elif base == "DifferentTime":
            first_start = self._start(first_id).value
            second_start = self._start(second_id).value
            first_end = self._end(first_id).value
            second_end = self._end(second_id).value
            satisfied = self._or(
                (
                    self._comparison(
                        first_end, "le", second_start, f"{prefix}_first_before"
                    ),
                    self._comparison(
                        second_end, "le", first_start, f"{prefix}_second_before"
                    ),
                ),
                f"{prefix}_satisfied",
            )
        elif base in {"SameDays", "SameWeeks"}:
            dimension = "day" if base == "SameDays" else "week"
            satisfied = self._or(
                (
                    self._mask_subset(
                        first_id,
                        second_id,
                        dimension,
                        f"{prefix}_first_subset",
                    ),
                    self._mask_subset(
                        second_id,
                        first_id,
                        dimension,
                        f"{prefix}_second_subset",
                    ),
                ),
                f"{prefix}_satisfied",
            )
        elif base in {"DifferentDays", "DifferentWeeks"}:
            dimension = "day" if base == "DifferentDays" else "week"
            satisfied = self._negated(
                self._mask_overlap(first_id, second_id, dimension)
            )
        elif base in {"Overlap", "NotOverlap"}:
            first_start = self._start(first_id).value
            second_start = self._start(second_id).value
            first_end = self._end(first_id).value
            second_end = self._end(second_id).value
            interval_overlap = self._and(
                (
                    self._comparison(
                        first_start, "lt", second_end, f"{prefix}_first_starts"
                    ),
                    self._comparison(
                        second_start, "lt", first_end, f"{prefix}_second_starts"
                    ),
                ),
                f"{prefix}_interval_overlap",
            )
            overlap = self._and(
                (
                    self._mask_overlap(first_id, second_id, "day"),
                    self._mask_overlap(first_id, second_id, "week"),
                    interval_overlap,
                ),
                f"{prefix}_overlap",
            )
            satisfied = overlap if base == "Overlap" else self._negated(overlap)
        elif base == "Precedence":
            first_end = self._end(first_id).value
            second_start = self._start(second_id).value
            first_week = self._first_active(first_id, "week").value
            second_week = self._first_active(second_id, "week").value
            first_day = self._first_active(first_id, "day").value
            second_day = self._first_active(second_id, "day").value
            week_equal = self._comparison(
                first_week, "eq", second_week, f"{prefix}_week_equal"
            )
            day_equal = self._comparison(
                first_day, "eq", second_day, f"{prefix}_day_equal"
            )
            satisfied = self._or(
                (
                    self._comparison(
                        first_week, "lt", second_week, f"{prefix}_earlier_week"
                    ),
                    self._and(
                        (
                            week_equal,
                            self._comparison(
                                first_day,
                                "lt",
                                second_day,
                                f"{prefix}_earlier_day",
                            ),
                        ),
                        f"{prefix}_same_week_earlier_day",
                    ),
                    self._and(
                        (
                            week_equal,
                            day_equal,
                            self._comparison(
                                first_end,
                                "le",
                                second_start,
                                f"{prefix}_earlier_time",
                            ),
                        ),
                        f"{prefix}_same_day_earlier_time",
                    ),
                ),
                f"{prefix}_satisfied",
            )
        elif base == "WorkDay":
            (maximum_span,) = parameters
            first_start = self._start(first_id).value
            second_start = self._start(second_id).value
            first_end = self._end(first_id).value
            second_end = self._end(second_id).value
            span_bad = self._or(
                tuple(
                    self._comparison(
                        end,
                        "gt",
                        start + maximum_span,
                        f"{prefix}_span_{index}",
                    )
                    for index, (end, start) in enumerate(
                        (
                            (first_end, first_start),
                            (first_end, second_start),
                            (second_end, first_start),
                            (second_end, second_start),
                        )
                    )
                ),
                f"{prefix}_span_bad",
            )
            violation = self._and(
                (
                    self._mask_overlap(first_id, second_id, "day"),
                    self._mask_overlap(first_id, second_id, "week"),
                    span_bad,
                ),
                f"{prefix}_violation",
            )
            self._indicators[cache_key] = violation
            return violation
        elif base == "MinGap":
            (minimum_gap,) = parameters
            first_start = self._start(first_id).value
            second_start = self._start(second_id).value
            first_end = self._end(first_id).value
            second_end = self._end(second_id).value
            separated = self._or(
                (
                    self._comparison(
                        first_end + minimum_gap,
                        "le",
                        second_start,
                        f"{prefix}_first_before",
                    ),
                    self._comparison(
                        second_end + minimum_gap,
                        "le",
                        first_start,
                        f"{prefix}_second_before",
                    ),
                ),
                f"{prefix}_separated",
            )
            violation = self._and(
                (
                    self._mask_overlap(first_id, second_id, "day"),
                    self._mask_overlap(first_id, second_id, "week"),
                    self._negated(separated),
                ),
                f"{prefix}_violation",
            )
            self._indicators[cache_key] = violation
            return violation
        else:  # pragma: no cover - caller restricts to the exhaustive set
            raise ValueError(f"unsupported factorized time distribution {base!r}")

        violation = self._negated(satisfied)
        self._indicators[cache_key] = violation
        return violation

    def room_distribution_violation(
        self,
        first_id: str,
        second_id: str,
        base: str,
        predicate_key: str,
    ) -> _Indicator:
        del predicate_key
        first_rooms = {
            option.room_id if option is not None else None
            for option in self.domains.rooms[first_id]
        }
        second_rooms = {
            option.room_id if option is not None else None
            for option in self.domains.rooms[second_id]
        }
        shared = first_rooms & second_rooms
        if base == "SameRoom" and not shared:
            return self.fixed(1, f"same_room_{first_id}_{second_id}_impossible")
        if base == "DifferentRoom" and not shared:
            return self.fixed(0, f"different_room_{first_id}_{second_id}_guaranteed")
        if len(first_rooms) == len(second_rooms) == len(shared) == 1:
            return self.fixed(
                int(base == "DifferentRoom"),
                f"room_relation_{base}_{first_id}_{second_id}_constant",
            )
        self.sparse_room_budget.claim(1, f"{base} relation {first_id}/{second_id}")
        violation = self.model.new_bool_var(
            f"room_relation_{base}_{first_id}_{second_id}_violation"
        )
        if base == "SameRoom":
            self.model.add(
                self.room_assignments[first_id] != self.room_assignments[second_id]
            ).only_enforce_if(violation)
            self.model.add(
                self.room_assignments[first_id] == self.room_assignments[second_id]
            ).only_enforce_if(violation.negated())
        else:
            self.model.add(
                self.room_assignments[first_id] == self.room_assignments[second_id]
            ).only_enforce_if(violation)
            self.model.add(
                self.room_assignments[first_id] != self.room_assignments[second_id]
            ).only_enforce_if(violation.negated())
        return _Indicator(variable=violation)

    def _room_pair_indicator(
        self,
        first_id: str,
        first_index: int,
        second_id: str,
        second_index: int,
    ) -> cp_model.IntVar:
        key = (first_id, first_index, second_id, second_index)
        cached = self._room_pair_indicators.get(key)
        if cached is not None:
            return cached
        first = self.room_selectors[first_id][first_index]
        second = self.room_selectors[second_id][second_index]
        conjunction = self.model.new_bool_var(
            f"room_pair_{first_id}_{first_index}_{second_id}_{second_index}"
        )
        self.model.add(conjunction <= first)
        self.model.add(conjunction <= second)
        self.model.add(conjunction >= first + second - 1)
        self._room_pair_indicators[key] = conjunction
        return conjunction

    def _compressed_travel_value(
        self,
        first_id: str,
        second_id: str,
        *,
        reverse: bool,
        label: str,
    ) -> int | cp_model.IntVar:
        first_rooms = self.domains.rooms[first_id]
        second_rooms = self.domains.rooms[second_id]
        counts, evaluations = _travel_value_counts(
            first_rooms,
            second_rooms,
            self._travel,
            reverse=reverse,
            deadline=self.deadline,
            max_evaluations=self.max_room_pair_evaluations_per_pair,
            label=f"{label} {first_id}/{second_id}",
        )
        default = min(counts, key=lambda value: (-counts[value], value))
        exception_count = evaluations - counts[default]
        minimum = min(counts)
        maximum = max(counts)
        if not exception_count:
            return default
        self.sparse_room_budget.claim(
            exception_count + 1,
            f"compressed travel relation {label} {first_id}/{second_id}",
        )
        terms = []
        scanned = 0
        for first_index, first in enumerate(first_rooms):
            for second_index, second in enumerate(second_rooms):
                distance = _travel_distance(
                    first,
                    second,
                    self._travel,
                    reverse=reverse,
                )
                if distance != default:
                    terms.append(
                        (distance - default)
                        * self._room_pair_indicator(
                            first_id,
                            first_index,
                            second_id,
                            second_index,
                        )
                    )
                scanned += 1
                if scanned % 256 == 0:
                    self.check_deadline()
        self.check_deadline()
        travel_value = self.model.new_int_var(
            minimum,
            maximum,
            f"travel_{label}_{first_id}_{second_id}",
        )
        self.model.add(travel_value == default + sum(terms))
        return travel_value

    def same_attendees_violation(
        self,
        first_id: str,
        second_id: str,
        *,
        student_travel: bool = False,
    ) -> _Indicator:
        semantics = "student" if student_travel else "distribution"
        cache_key = (first_id, second_id, semantics)
        cached = self._same_attendees.get(cache_key)
        if cached is not None:
            return cached

        forward_value = self._compressed_travel_value(
            first_id,
            second_id,
            reverse=False,
            label=f"{semantics}_forward",
        )
        if student_travel:
            backward_value = self._compressed_travel_value(
                first_id,
                second_id,
                reverse=True,
                label=f"{semantics}_backward",
            )
        else:
            backward_value = forward_value
        prefix = f"same_attendees_{semantics}_{first_id}_{second_id}"
        first_start = self._start(first_id).value
        second_start = self._start(second_id).value
        first_end = self._end(first_id).value
        second_end = self._end(second_id).value
        forward_safe = self._comparison(
            first_end + forward_value,
            "le",
            second_start,
            f"{prefix}_forward_safe",
        )
        backward_safe = self._comparison(
            second_end + backward_value,
            "le",
            first_start,
            f"{prefix}_backward_safe",
        )
        result = self._and(
            (
                self._mask_overlap(first_id, second_id, "day"),
                self._mask_overlap(first_id, second_id, "week"),
                self._negated(forward_safe),
                self._negated(backward_safe),
            ),
            f"{prefix}_violation",
        )
        self._same_attendees[cache_key] = result
        return result


def _joint_sectioning_term_upper_bound(problem: ITC2019Problem, limit: int) -> int:
    course_classes = {
        course.id: {
            klass.id
            for configuration in course.configurations
            for subpart in configuration.subparts
            for klass in subpart.classes
        }
        for course in problem.courses
    }
    total = 0
    for student in problem.students:
        possible = set().union(
            *(course_classes[course_id] for course_id in student.course_ids)
        )
        total += len(possible) * (len(possible) - 1) // 2
        if total > limit:
            return total
    return total


def _unique_factorized_domains(
    problem: ITC2019Problem,
    *,
    deadline: float | None = None,
) -> tuple[
    dict[str, tuple[ITC2019TimeOption, ...]],
    dict[str, tuple[ITC2019RoomOption | None, ...]],
]:
    times: dict[str, tuple[ITC2019TimeOption, ...]] = {}
    rooms: dict[str, tuple[ITC2019RoomOption | None, ...]] = {}
    options_seen = 0
    for klass in problem.classes:
        unique_times: dict[tuple[str, int, int, str], ITC2019TimeOption] = {}
        for option in klass.time_options:
            key = (option.days, option.start, option.length, option.weeks)
            current = unique_times.get(key)
            if current is None or option.penalty < current.penalty:
                unique_times[key] = option
            options_seen += 1
            if (
                deadline is not None
                and options_seen % 1024 == 0
                and time.monotonic() >= deadline
            ):
                raise TimeoutError("ITC-2019 factorized domain construction timed out")
        times[klass.id] = tuple(unique_times.values())
        if klass.room_required:
            unique_rooms: dict[str, ITC2019RoomOption] = {}
            for option in klass.room_options:
                current = unique_rooms.get(option.room_id)
                if current is None or option.penalty < current.penalty:
                    unique_rooms[option.room_id] = option
                options_seen += 1
                if (
                    deadline is not None
                    and options_seen % 1024 == 0
                    and time.monotonic() >= deadline
                ):
                    raise TimeoutError(
                        "ITC-2019 factorized domain construction timed out"
                    )
            rooms[klass.id] = tuple(unique_rooms.values())
        else:
            rooms[klass.id] = (None,)
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("ITC-2019 factorized domain construction timed out")
    return times, rooms


def _travel_exception_count(
    first_rooms: Sequence[ITC2019RoomOption | None],
    second_rooms: Sequence[ITC2019RoomOption | None],
    travel: Mapping[tuple[str, str], int],
    *,
    reverse: bool,
    deadline: float | None = None,
    max_evaluations: int | None = None,
    label: str = "room pair",
) -> int:
    counts, evaluations = _travel_value_counts(
        first_rooms,
        second_rooms,
        travel,
        reverse=reverse,
        deadline=deadline,
        max_evaluations=max_evaluations,
        label=label,
    )
    default_count = max(counts.values())
    exceptions = evaluations - default_count
    return exceptions + int(exceptions > 0)


def _travel_distance(
    first: ITC2019RoomOption | None,
    second: ITC2019RoomOption | None,
    travel: Mapping[tuple[str, str], int],
    *,
    reverse: bool,
) -> int:
    first_id = first.room_id if first is not None else None
    second_id = second.room_id if second is not None else None
    if first_id is None or second_id is None:
        return 0
    origin, destination = (second_id, first_id) if reverse else (first_id, second_id)
    return travel.get(
        (origin, destination),
        travel.get((destination, origin), 0),
    )


def _travel_value_counts(
    first_rooms: Sequence[ITC2019RoomOption | None],
    second_rooms: Sequence[ITC2019RoomOption | None],
    travel: Mapping[tuple[str, str], int],
    *,
    reverse: bool,
    deadline: float | None,
    max_evaluations: int | None,
    label: str,
) -> tuple[Counter[int], int]:
    evaluations = len(first_rooms) * len(second_rooms)
    if max_evaluations is not None and evaluations > max_evaluations:
        raise _EncodingScaleExceeded(f"{label} evaluations exceed {max_evaluations}")
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("ITC-2019 factorized room-pair preprocessing timed out")

    counts: Counter[int] = Counter()
    scanned = 0
    for first in first_rooms:
        for second in second_rooms:
            counts[
                _travel_distance(
                    first,
                    second,
                    travel,
                    reverse=reverse,
                )
            ] += 1
            scanned += 1
            if (
                deadline is not None
                and scanned % 256 == 0
                and time.monotonic() >= deadline
            ):
                raise TimeoutError(
                    "ITC-2019 factorized room-pair preprocessing timed out"
                )
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("ITC-2019 factorized room-pair preprocessing timed out")
    if not counts:
        raise _EncodingInfeasible(f"{label} has an empty room domain")
    return counts, evaluations


def _joint_sectioning_pairs(
    problem: ITC2019Problem,
    *,
    deadline: float | None = None,
) -> set[tuple[str, str]]:
    course_classes = {
        course.id: {
            klass.id
            for configuration in course.configurations
            for subpart in configuration.subparts
            for klass in subpart.classes
        }
        for course in problem.courses
    }
    pairs: set[tuple[str, str]] = set()
    for student_index, student in enumerate(problem.students):
        possible = sorted(
            set().union(
                *(course_classes[course_id] for course_id in student.course_ids)
            )
        )
        pairs.update(combinations(possible, 2))
        if (
            deadline is not None
            and student_index % 128 == 0
            and time.monotonic() >= deadline
        ):
            raise TimeoutError("ITC-2019 factorized student-pair estimate timed out")
    return pairs


def _time_predicate_requests(
    problem: ITC2019Problem,
    *,
    joint_sectioning: bool,
    deadline: float | None = None,
) -> set[tuple[str, tuple[int, ...], str, str, str]]:
    requests: set[tuple[str, tuple[int, ...], str, str, str]] = set()
    for distribution_index, distribution in enumerate(problem.distributions):
        if not distribution.required and not distribution.penalty:
            continue
        base, parameters = _distribution_spec(distribution.type)
        if base not in _TIME_ONLY_PAIR_DISTRIBUTIONS and base != "SameAttendees":
            continue
        semantics = "distribution" if base == "SameAttendees" else "time"
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        requests.update(
            (base, parameters, first_id, second_id, semantics)
            for first_id, second_id in combinations(class_ids, 2)
        )
        if (
            deadline is not None
            and distribution_index % 128 == 0
            and time.monotonic() >= deadline
        ):
            raise TimeoutError("ITC-2019 factorized predicate estimate timed out")
    if joint_sectioning:
        requests.update(
            ("SameAttendees", (), first_id, second_id, "student")
            for first_id, second_id in _joint_sectioning_pairs(
                problem,
                deadline=deadline,
            )
        )
    return requests


def _mask_bit_state(
    domains: Mapping[str, tuple[ITC2019TimeOption, ...]],
    class_id: str,
    dimension: str,
    index: int,
) -> int | None:
    values = {
        (option.days if dimension == "day" else option.weeks)[index]
        for option in domains[class_id]
    }
    if len(values) == 1:
        return int(next(iter(values)))
    return None


def _mask_overlap_cells(
    problem: ITC2019Problem,
    domains: Mapping[str, tuple[ITC2019TimeOption, ...]],
    first_id: str,
    second_id: str,
    dimension: str,
) -> int:
    width = problem.nr_days if dimension == "day" else problem.nr_weeks
    conjunctions = 0
    variable_terms = 0
    guaranteed = False
    for index in range(width):
        first = _mask_bit_state(domains, first_id, dimension, index)
        second = _mask_bit_state(domains, second_id, dimension, index)
        if first == 0 or second == 0:
            continue
        if first == second == 1:
            guaranteed = True
            continue
        variable_terms += 1
        if first is None and second is None:
            conjunctions += 1
    return conjunctions + int(not guaranteed and variable_terms > 1)


def _mask_subset_cells(
    problem: ITC2019Problem,
    domains: Mapping[str, tuple[ITC2019TimeOption, ...]],
    first_id: str,
    second_id: str,
    dimension: str,
) -> tuple[int, int | None]:
    width = problem.nr_days if dimension == "day" else problem.nr_weeks
    disjunctions = 0
    variable_terms = 0
    impossible = False
    for index in range(width):
        first = _mask_bit_state(domains, first_id, dimension, index)
        second = _mask_bit_state(domains, second_id, dimension, index)
        if first == 0 or second == 1:
            continue
        if first == 1 and second == 0:
            impossible = True
            continue
        variable_terms += 1
        if first is None and second is None:
            disjunctions += 1
    if impossible:
        return disjunctions, 0
    if not variable_terms:
        return disjunctions, 1
    return disjunctions + int(variable_terms > 1), None


def _time_relation_cells(
    base: str,
    problem: ITC2019Problem,
    domains: Mapping[str, tuple[ITC2019TimeOption, ...]],
    first_id: str,
    second_id: str,
) -> int:
    """Return a conservative linear-size guard for one direct relation.

    The units count reified comparisons and literal supports.  Unlike the former
    pair table, the count is independent of the Cartesian product of two time
    domains and therefore mirrors the direct interval/mask formulation's growth.
    """

    def day_overlap() -> int:
        return _mask_overlap_cells(problem, domains, first_id, second_id, "day")

    def week_overlap() -> int:
        return _mask_overlap_cells(problem, domains, first_id, second_id, "week")

    if base == "SameStart":
        return 0
    if base == "SameTime":
        return 7
    if base == "DifferentTime":
        return 3
    if base in {"SameDays", "SameWeeks"}:
        dimension = "day" if base == "SameDays" else "week"
        first_cells, first_state = _mask_subset_cells(
            problem, domains, first_id, second_id, dimension
        )
        second_cells, second_state = _mask_subset_cells(
            problem, domains, second_id, first_id, dimension
        )
        final_or = int(first_state is None and second_state is None)
        return first_cells + second_cells + final_or
    if base == "DifferentDays":
        return day_overlap()
    if base == "DifferentWeeks":
        return week_overlap()
    if base in {"Overlap", "NotOverlap"}:
        return day_overlap() + week_overlap() + 4
    if base == "Precedence":
        return 8
    if base == "WorkDay":
        return day_overlap() + week_overlap() + 6
    if base == "MinGap":
        return day_overlap() + week_overlap() + 4
    if base == "SameAttendees":
        return day_overlap() + week_overlap() + 3
    raise ValueError(f"unsupported sparse time relation {base!r}")


def _sparse_time_predicate_cells(
    problem: ITC2019Problem,
    times: Mapping[str, tuple[ITC2019TimeOption, ...]],
    *,
    joint_sectioning: bool,
    deadline: float | None = None,
) -> int:
    scalar_features: set[tuple[str, str]] = set()
    mask_features: set[tuple[str, str]] = set()
    requests = _time_predicate_requests(
        problem,
        joint_sectioning=joint_sectioning,
        deadline=deadline,
    )

    def scalars(class_ids: Sequence[str], *keys: str) -> None:
        scalar_features.update(
            (class_id, key) for class_id in class_ids for key in keys
        )

    def masks(class_ids: Sequence[str], *dimensions: str) -> None:
        mask_features.update(
            (class_id, dimension) for class_id in class_ids for dimension in dimensions
        )

    for base, _parameters, first_id, second_id, _semantics in requests:
        pair = (first_id, second_id)
        if base == "SameStart":
            scalars(pair, "start")
        elif base in {"SameTime", "DifferentTime"}:
            scalars(pair, "start", "end")
        elif base in {"SameDays", "DifferentDays"}:
            masks(pair, "day")
        elif base in {"SameWeeks", "DifferentWeeks"}:
            masks(pair, "week")
        elif base in {"Overlap", "NotOverlap", "WorkDay", "MinGap"}:
            scalars(pair, "start", "end")
            masks(pair, "day", "week")
        elif base == "Precedence":
            scalar_features.update(
                {
                    (first_id, "end"),
                    (second_id, "start"),
                    (first_id, "first_day"),
                    (second_id, "first_day"),
                    (first_id, "first_week"),
                    (second_id, "first_week"),
                }
            )
        elif base == "SameAttendees":
            scalars(pair, "start", "end")
            masks(pair, "day", "week")

    cells = 0
    for request_index, (
        base,
        _parameters,
        first_id,
        second_id,
        _semantics,
    ) in enumerate(requests):
        cells += _time_relation_cells(
            base,
            problem,
            times,
            first_id,
            second_id,
        )
        if (
            deadline is not None
            and request_index % 1024 == 0
            and time.monotonic() >= deadline
        ):
            raise TimeoutError("ITC-2019 factorized predicate estimate timed out")
    for class_id, key in scalar_features:
        if key == "start":
            values = [option.start for option in times[class_id]]
        elif key == "end":
            values = [option.start + option.length for option in times[class_id]]
        elif key == "first_day":
            values = [option.days.index("1") for option in times[class_id]]
        else:
            values = [option.weeks.index("1") for option in times[class_id]]
        if min(values) != max(values):
            cells += len(values)
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("ITC-2019 factorized predicate estimate timed out")

    for class_id, dimension in mask_features:
        masks_for_class = [
            option.days if dimension == "day" else option.weeks
            for option in times[class_id]
        ]
        for bit in range(len(masks_for_class[0])):
            active = sum(mask[bit] == "1" for mask in masks_for_class)
            if 0 < active < len(masks_for_class):
                cells += min(active, len(masks_for_class) - active)
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("ITC-2019 factorized predicate estimate timed out")
    return cells


def _occurrence_interval_groups(
    problem: ITC2019Problem,
    domains: Mapping[str, tuple[ITC2019TimeOption, ...]],
    class_ids: Sequence[str],
    *,
    day: int,
    week: int,
    deadline: float | None = None,
) -> tuple[tuple[int, int, tuple[tuple[str, int], ...]], ...]:
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("ITC-2019 factorized group scan timed out")
    selectors: dict[tuple[int, int], list[tuple[str, int]]] = defaultdict(list)
    options_seen = 0
    for class_id in class_ids:
        for option_index, option in enumerate(domains[class_id]):
            if option.days[day] == "1" and option.weeks[week] == "1":
                selectors[(option.start, option.start + option.length)].append(
                    (class_id, option_index)
                )
            options_seen += 1
            if (
                deadline is not None
                and options_seen % 1024 == 0
                and time.monotonic() >= deadline
            ):
                raise TimeoutError("ITC-2019 factorized group scan timed out")
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("ITC-2019 factorized group scan timed out")
    return tuple(
        (start, end, tuple(selector_keys))
        for (start, end), selector_keys in sorted(selectors.items())
    )


def _group_distribution_estimate(
    problem: ITC2019Problem,
    domains: Mapping[str, tuple[ITC2019TimeOption, ...]],
    *,
    base: str,
    parameters: tuple[int, ...],
    class_ids: Sequence[str],
    required: bool,
    maximum_cells: int,
    deadline: float | None = None,
) -> _GroupEncodingEstimate:
    del required
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("ITC-2019 factorized group estimate timed out")
    _first_parameter, _maximum_gap = parameters
    total = 0
    occurrences = 0
    for day in range(problem.nr_days):
        for week in range(problem.nr_weeks):
            groups = _occurrence_interval_groups(
                problem,
                domains,
                class_ids,
                day=day,
                week=week,
                deadline=deadline,
            )
            active = len(groups)
            if active:
                # A scan uses a bounded number of state, reification, and
                # recurrence cells per unique interval.  MaxBlock carries two
                # extra state values and emits at most one violation event.
                selector_support = sum(
                    len(selector_keys) for _start, _end, selector_keys in groups
                )
                total += (
                    (32 if base == "MaxBlock" else 14) * active + selector_support + 3
                )
            if total > maximum_cells:
                return _GroupEncodingEstimate(total)
            occurrences += 1
            if (
                deadline is not None
                and occurrences % 64 == 0
                and time.monotonic() >= deadline
            ):
                raise TimeoutError("ITC-2019 factorized group estimate timed out")
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("ITC-2019 factorized group estimate timed out")
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("ITC-2019 factorized group estimate timed out")
    return _GroupEncodingEstimate(total)


def estimate_itc2019_factorized_scale(
    problem: ITC2019Problem,
    *,
    max_pair_matrix_cells: int,
    max_group_table_rows: int,
    max_joint_student_conjunctions: int,
    max_sparse_room_constraints: int,
) -> ITC2019FactorizedScaleEstimate:
    """Mirror every formulation guard using counts only; never build CP-SAT."""

    for value in (
        max_pair_matrix_cells,
        max_group_table_rows,
        max_joint_student_conjunctions,
        max_sparse_room_constraints,
    ):
        if value <= 0:
            raise ValueError("factorized ITC-2019 encoding budgets must be positive")
    problem_errors = _validate_problem_references(problem)
    if problem_errors:
        return ITC2019FactorizedScaleEstimate(
            False, "not_started", 0, 0, 0, 0, 0, 0, 0, tuple(problem_errors)
        )

    times, rooms = _unique_factorized_domains(problem)
    if any(not times[klass.id] or not rooms[klass.id] for klass in problem.classes):
        return ITC2019FactorizedScaleEstimate(
            False,
            "not_started",
            sum(map(len, times.values())),
            sum(map(len, rooms.values())),
            sum(
                len(times[klass.id]) * len(rooms[klass.id]) for klass in problem.classes
            ),
            0,
            0,
            0,
            0,
            ("class has no factorized time or room domain",),
        )

    joint_terms = _joint_sectioning_term_upper_bound(
        problem, max_joint_student_conjunctions
    )
    joint = bool(problem.students) and joint_terms <= max_joint_student_conjunctions
    sectioning_mode = (
        "none"
        if not problem.students
        else "joint"
        if joint
        else "staged_exact_fixed_timetable"
    )
    predicate_cells = _sparse_time_predicate_cells(
        problem,
        times,
        joint_sectioning=joint,
    )
    sparse_constraints = 0
    maximum_group_rows = 0
    reasons: list[str] = []
    seen_same_attendees: set[tuple[str, str, str]] = set()
    seen_travel: set[tuple[str, str, bool, str]] = set()
    travel = _travel_values(problem)

    def claim_same_attendees(first_id: str, second_id: str, semantics: str) -> None:
        nonlocal sparse_constraints
        key = (first_id, second_id, semantics)
        if key in seen_same_attendees:
            return
        seen_same_attendees.add(key)
        for reverse in (False, True) if semantics == "student" else (False,):
            travel_key = (first_id, second_id, reverse, semantics)
            if travel_key not in seen_travel:
                seen_travel.add(travel_key)
                sparse_constraints += _travel_exception_count(
                    rooms[first_id], rooms[second_id], travel, reverse=reverse
                )

    for distribution_index, distribution in enumerate(problem.distributions, start=1):
        base, parameters = _distribution_spec(distribution.type)
        if not distribution.required and not distribution.penalty:
            continue
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        if base in _TIME_ONLY_PAIR_DISTRIBUTIONS:
            pass
        elif base in _ROOM_ONLY_PAIR_DISTRIBUTIONS:
            for first_id, second_id in combinations(class_ids, 2):
                first_set = {
                    option.room_id if option is not None else None
                    for option in rooms[first_id]
                }
                second_set = {
                    option.room_id if option is not None else None
                    for option in rooms[second_id]
                }
                shared = first_set & second_set
                if shared and not (
                    len(first_set) == len(second_set) == len(shared) == 1
                ):
                    sparse_constraints += 1
        elif base == "SameAttendees":
            for first_id, second_id in combinations(class_ids, 2):
                claim_same_attendees(first_id, second_id, "distribution")
        elif base in {"MaxBreaks", "MaxBlock"}:
            group = _group_distribution_estimate(
                problem,
                times,
                base=base,
                parameters=parameters,
                class_ids=class_ids,
                required=distribution.required,
                maximum_cells=max_group_table_rows,
            )
            maximum_group_rows = max(maximum_group_rows, group.cells)
            if group.cells > max_group_table_rows:
                reasons.append(
                    f"distribution {distribution_index} needs {group.cells} sparse "
                    f"group cells; limit is {max_group_table_rows}"
                )

    if joint:
        for first_id, second_id in sorted(_joint_sectioning_pairs(problem)):
            claim_same_attendees(first_id, second_id, "student")

    classes_by_room: dict[str, set[str]] = defaultdict(set)
    for klass in problem.classes:
        for option in rooms[klass.id]:
            if option is not None:
                classes_by_room[option.room_id].add(klass.id)
    rooms_by_id = {room.id: room for room in problem.rooms}
    resource_classes = {
        class_id
        for room_id, class_ids in classes_by_room.items()
        if len(class_ids) > 1 or rooms_by_id[room_id].unavailable
        for class_id in class_ids
    }
    for class_id in resource_classes:
        sparse_constraints += sum(
            option.days.count("1") * option.weeks.count("1")
            for option in times[class_id]
        )
    used_rooms = {
        option.room_id
        for class_id in resource_classes
        for option in rooms[class_id]
        if option is not None
    }
    for room_id in used_rooms:
        by_occurrence: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        for unavailable in rooms_by_id[room_id].unavailable:
            for week, active_week in enumerate(unavailable.weeks):
                if active_week != "1":
                    continue
                for day, active_day in enumerate(unavailable.days):
                    if active_day == "1":
                        by_occurrence[(week, day)].append(
                            (unavailable.start, unavailable.start + unavailable.length)
                        )
        for intervals in by_occurrence.values():
            end = -1
            for start, stop in sorted(intervals):
                if start > end:
                    sparse_constraints += 1
                end = max(end, stop)
    if resource_classes:
        sparse_constraints += 1

    if predicate_cells > max_pair_matrix_cells:
        reasons.append(
            f"factorized predicates need {predicate_cells} cells; limit is "
            f"{max_pair_matrix_cells}"
        )
    if sparse_constraints > max_sparse_room_constraints:
        reasons.append(
            f"factorized sparse room encoding needs {sparse_constraints} constraints; "
            f"limit is {max_sparse_room_constraints}"
        )
    return ITC2019FactorizedScaleEstimate(
        admitted=not reasons,
        sectioning_mode=sectioning_mode,
        time_domain_values=sum(map(len, times.values())),
        room_domain_values=sum(map(len, rooms.values())),
        cartesian_domain_values=sum(
            len(times[klass.id]) * len(rooms[klass.id]) for klass in problem.classes
        ),
        predicate_table_cells=predicate_cells,
        sparse_room_constraints=sparse_constraints,
        joint_student_conjunctions=joint_terms,
        maximum_group_table_rows=maximum_group_rows,
        unsupported_reasons=tuple(reasons),
    )


def _add_group_distribution(
    *,
    problem: ITC2019Problem,
    model: cp_model.CpModel,
    domains: _FactorizedDomains,
    time_selectors: Mapping[str, tuple[cp_model.IntVar, ...]],
    encoder: _PairEncoder,
    objective_terms: list[Any],
    distribution_index: int,
    base: str,
    parameters: tuple[int, ...],
    class_ids: tuple[str, ...],
    required: bool,
    penalty: int,
    maximum_cells: int,
    deadline: float,
) -> None:
    """Encode MaxBreaks/MaxBlock by scanning sparse active intervals.

    Each (day, week) scan follows the official MergeBlocks recurrence.  Presence
    literals are shared by all coincident class intervals, preserving the
    mathematical-set rule and MaxBlock's single-interval exemption without ever
    enumerating the Cartesian product of class time domains.
    """

    estimate = _group_distribution_estimate(
        problem,
        domains.times,
        base=base,
        parameters=parameters,
        class_ids=class_ids,
        required=required,
        maximum_cells=maximum_cells,
        deadline=deadline,
    )
    if estimate.cells > maximum_cells:
        raise _EncodingScaleExceeded(
            f"distribution {distribution_index} needs {estimate.cells} sparse "
            f"group cells; limit is {maximum_cells}"
        )

    first_parameter, maximum_gap = parameters
    violation_units: list[Any] = []
    maximum_units = 0
    for day in range(problem.nr_days):
        for week in range(problem.nr_weeks):
            groups = _occurrence_interval_groups(
                problem,
                domains.times,
                class_ids,
                day=day,
                week=week,
                deadline=deadline,
            )
            if not groups:
                continue
            occurrence = f"distribution_{distribution_index}_{day}_{week}"
            sentinel = (
                min(start for start, _end, _selectors in groups) - maximum_gap - 2
            )
            prefix_end: Any = sentinel
            block_start: Any = sentinel
            block_bad = encoder.fixed(0, f"{occurrence}_initial_block_bad")
            new_blocks: list[Any] = []
            bad_events: list[Any] = []
            maximum_end = max(end for _start, end, _selectors in groups)

            for interval_index, (start, end, selector_keys) in enumerate(groups):
                presence = encoder._or(
                    tuple(
                        _Indicator(time_selectors[class_id][option_index])
                        for class_id, option_index in selector_keys
                    ),
                    f"{occurrence}_{interval_index}_present",
                )
                selected_end = model.new_int_var(
                    sentinel,
                    end,
                    f"{occurrence}_{interval_index}_selected_end",
                )
                model.add(selected_end == end).only_enforce_if(presence.variable)
                model.add(selected_end == sentinel).only_enforce_if(
                    presence.variable.negated()
                )
                next_prefix_end = model.new_int_var(
                    sentinel,
                    maximum_end,
                    f"{occurrence}_{interval_index}_prefix_end",
                )
                model.add_max_equality(
                    next_prefix_end,
                    (prefix_end, selected_end),
                )
                separated = encoder._comparison(
                    start,
                    "gt",
                    prefix_end + maximum_gap,
                    f"{occurrence}_{interval_index}_separated",
                )
                new_block = encoder._and(
                    (presence, separated),
                    f"{occurrence}_{interval_index}_new_block",
                )
                connected = encoder._and(
                    (presence, encoder._negated(separated)),
                    f"{occurrence}_{interval_index}_connected",
                )
                new_blocks.append(new_block.variable)

                if base == "MaxBlock":
                    span_bad = encoder._comparison(
                        next_prefix_end,
                        "gt",
                        block_start + first_parameter,
                        f"{occurrence}_{interval_index}_span_bad",
                    )
                    bad_event = encoder._and(
                        (
                            connected,
                            encoder._negated(block_bad),
                            span_bad,
                        ),
                        f"{occurrence}_{interval_index}_bad_event",
                    )
                    bad_events.append(bad_event.variable)
                    carried_bad = encoder._and(
                        (encoder._negated(presence), block_bad),
                        f"{occurrence}_{interval_index}_carried_bad",
                    )
                    connected_bad = encoder._and(
                        (
                            connected,
                            encoder._or(
                                (block_bad, span_bad),
                                f"{occurrence}_{interval_index}_connected_bad_state",
                            ),
                        ),
                        f"{occurrence}_{interval_index}_connected_bad",
                    )
                    block_bad = encoder._or(
                        (carried_bad, connected_bad),
                        f"{occurrence}_{interval_index}_block_bad",
                    )
                    next_block_start = model.new_int_var(
                        sentinel,
                        start,
                        f"{occurrence}_{interval_index}_block_start",
                    )
                    model.add(next_block_start == start).only_enforce_if(
                        new_block.variable
                    )
                    model.add(next_block_start == block_start).only_enforce_if(
                        new_block.variable.negated()
                    )
                    block_start = next_block_start

                prefix_end = next_prefix_end
                if interval_index % 128 == 0 and time.monotonic() >= deadline:
                    raise TimeoutError(
                        "ITC-2019 factorized sparse group construction timed out"
                    )

            if base == "MaxBreaks":
                block_count = sum(new_blocks)
                if required:
                    model.add(block_count <= first_parameter + 1)
                else:
                    excess = model.new_int_var(
                        0,
                        len(groups),
                        f"{occurrence}_break_excess",
                    )
                    model.add_max_equality(
                        excess,
                        (block_count - (first_parameter + 1), 0),
                    )
                    violation_units.append(excess)
                    maximum_units += len(groups)
            elif required:
                model.add(sum(bad_events) == 0)
            else:
                violation_units.extend(bad_events)
                maximum_units += len(groups)

    if not required and penalty and violation_units:
        total_units = model.new_int_var(
            0,
            maximum_units,
            f"distribution_{distribution_index}_factorized_total_excess",
        )
        model.add(total_units == sum(violation_units))
        numerator = model.new_int_var(
            0,
            penalty * maximum_units,
            f"distribution_{distribution_index}_factorized_numerator",
        )
        model.add(numerator == penalty * total_units)
        cost = model.new_int_var(
            0,
            penalty * maximum_units,
            f"distribution_{distribution_index}_factorized_cost",
        )
        model.add_division_equality(cost, numerator, problem.nr_weeks)
        objective_terms.append(problem.optimization.distribution * cost)


def _add_distributions(
    *,
    problem: ITC2019Problem,
    model: cp_model.CpModel,
    domains: _FactorizedDomains,
    time_choices: Mapping[str, cp_model.IntVar],
    time_selectors: Mapping[str, tuple[cp_model.IntVar, ...]],
    encoder: _PairEncoder,
    objective_terms: list[Any],
    max_group_table_rows: int,
    deadline: float,
) -> None:
    for distribution_index, distribution in enumerate(problem.distributions, start=1):
        base, parameters = _distribution_spec(distribution.type)
        if not distribution.required and not distribution.penalty:
            continue
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        if base in _TIME_ONLY_PAIR_DISTRIBUTIONS:
            for first_index, second_index in combinations(range(len(class_ids)), 2):
                first_id = class_ids[first_index]
                second_id = class_ids[second_index]
                violation = encoder.time_distribution_violation(
                    first_id,
                    second_id,
                    base,
                    parameters,
                    f"distribution_{distribution_index}_{base}",
                )
                if distribution.required:
                    model.add(violation.variable == 0)
                elif distribution.penalty:
                    objective_terms.append(
                        distribution.penalty
                        * problem.optimization.distribution
                        * violation.variable
                    )
        elif base in _ROOM_ONLY_PAIR_DISTRIBUTIONS:
            for first_index, second_index in combinations(range(len(class_ids)), 2):
                first_id = class_ids[first_index]
                second_id = class_ids[second_index]
                violation = encoder.room_distribution_violation(
                    first_id,
                    second_id,
                    base,
                    f"distribution_{distribution_index}_{base}",
                )
                if distribution.required:
                    model.add(violation.variable == 0)
                elif distribution.penalty:
                    objective_terms.append(
                        distribution.penalty
                        * problem.optimization.distribution
                        * violation.variable
                    )
        elif base == "SameAttendees":
            for first_index, second_index in combinations(range(len(class_ids)), 2):
                violation = encoder.same_attendees_violation(
                    class_ids[first_index],
                    class_ids[second_index],
                )
                if distribution.required:
                    model.add(violation.variable == 0)
                elif distribution.penalty:
                    objective_terms.append(
                        distribution.penalty
                        * problem.optimization.distribution
                        * violation.variable
                    )
        elif base == "MaxDays":
            (maximum_days,) = parameters
            used_days: list[cp_model.IntVar] = []
            for day in range(problem.nr_days):
                active = [
                    time_selectors[class_id][time_index]
                    for class_id in class_ids
                    for time_index, option in enumerate(domains.times[class_id])
                    if option.days[day] == "1"
                ]
                used = model.new_bool_var(
                    f"distribution_{distribution_index}_factorized_day_{day}"
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
                    f"distribution_{distribution_index}_factorized_day_excess",
                )
                model.add(excess >= sum(used_days) - maximum_days)
                objective_terms.append(
                    distribution.penalty * problem.optimization.distribution * excess
                )
        elif base == "MaxDayLoad":
            (maximum_load,) = parameters
            maximum_possible = sum(
                max(option.length for option in domains.times[class_id])
                for class_id in class_ids
            )
            excesses: list[cp_model.IntVar] = []
            for day in range(problem.nr_days):
                for week in range(problem.nr_weeks):
                    load_terms = [
                        option.length * time_selectors[class_id][time_index]
                        for class_id in class_ids
                        for time_index, option in enumerate(domains.times[class_id])
                        if option.days[day] == "1" and option.weeks[week] == "1"
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
                    f"distribution_{distribution_index}_factorized_total_excess",
                )
                model.add(total_excess == sum(excesses))
                numerator = model.new_int_var(
                    0,
                    distribution.penalty
                    * maximum_possible
                    * problem.nr_days
                    * problem.nr_weeks,
                    f"distribution_{distribution_index}_factorized_numerator",
                )
                model.add(numerator == distribution.penalty * total_excess)
                cost = model.new_int_var(
                    0,
                    distribution.penalty * maximum_possible * problem.nr_days,
                    f"distribution_{distribution_index}_factorized_cost",
                )
                model.add_division_equality(cost, numerator, problem.nr_weeks)
                objective_terms.append(problem.optimization.distribution * cost)
        elif base in {"MaxBreaks", "MaxBlock"}:
            _add_group_distribution(
                problem=problem,
                model=model,
                domains=domains,
                time_selectors=time_selectors,
                encoder=encoder,
                objective_terms=objective_terms,
                distribution_index=distribution_index,
                base=base,
                parameters=parameters,
                class_ids=class_ids,
                required=distribution.required,
                penalty=distribution.penalty,
                maximum_cells=max_group_table_rows,
                deadline=deadline,
            )
        else:  # pragma: no cover - _distribution_spec is exhaustive
            raise ValueError(f"unsupported factorized distribution {base!r}")
        if time.monotonic() >= deadline:
            raise TimeoutError("ITC-2019 factorized distribution encoding timed out")


def _add_room_resources(
    *,
    problem: ITC2019Problem,
    domains: _FactorizedDomains,
    model: cp_model.CpModel,
    time_selectors: Mapping[str, tuple[cp_model.IntVar, ...]],
    room_assignments: Mapping[str, cp_model.IntVar],
    sparse_room_budget: _SparseRoomBudget,
    deadline: float,
) -> None:
    """Encode recurring room occupancy as exact optional 2-D rectangles.

    X is a flattened (week, day, slot) coordinate and Y is the globally coded
    room assignment.  A selected time option contributes one optional rectangle
    per active day/week occurrence.  Merged fixed rectangles represent room
    unavailability.  NoOverlap2D therefore rejects exactly the same-time,
    same-room combinations without materializing class-pair x time-pair tables.
    """

    classes_by_room: dict[str, set[str]] = defaultdict(set)
    for klass in problem.classes:
        for room_option in domains.rooms[klass.id]:
            if room_option is not None:
                classes_by_room[room_option.room_id].add(klass.id)

    rooms_by_id = {room.id: room for room in problem.rooms}
    resource_class_ids = {
        class_id
        for room_id, class_ids in classes_by_room.items()
        if len(class_ids) > 1 or rooms_by_id[room_id].unavailable
        for class_id in class_ids
    }
    if not resource_class_ids:
        return

    global_room_codes = {room.id: index for index, room in enumerate(problem.rooms)}
    x_intervals: list[cp_model.IntervalVar] = []
    y_intervals: list[cp_model.IntervalVar] = []
    rectangles = 0

    for klass in problem.classes:
        if klass.id not in resource_class_ids:
            continue
        for time_index, option in enumerate(domains.times[klass.id]):
            presence = time_selectors[klass.id][time_index]
            for week, week_active in enumerate(option.weeks):
                if week_active != "1":
                    continue
                for day, day_active in enumerate(option.days):
                    if day_active != "1":
                        continue
                    sparse_room_budget.claim(
                        1,
                        f"room-resource rectangles for class {klass.id}",
                    )
                    flattened_start = (
                        week * problem.nr_days + day
                    ) * problem.slots_per_day + option.start
                    suffix = f"{klass.id}_{time_index}_{week}_{day}"
                    x_intervals.append(
                        model.new_optional_fixed_size_interval_var(
                            flattened_start,
                            option.length,
                            presence,
                            f"room_resource_x_{suffix}",
                        )
                    )
                    y_intervals.append(
                        model.new_optional_fixed_size_interval_var(
                            room_assignments[klass.id],
                            1,
                            presence,
                            f"room_resource_y_{suffix}",
                        )
                    )
                    rectangles += 1
                    if rectangles % 512 == 0 and time.monotonic() >= deadline:
                        raise TimeoutError("ITC-2019 room-resource encoding timed out")

    used_room_ids = {
        option.room_id
        for class_id in resource_class_ids
        for option in domains.rooms[class_id]
        if option is not None
    }
    blocked: dict[tuple[str, int, int], list[tuple[int, int]]] = defaultdict(list)
    for room_id in sorted(used_room_ids):
        for unavailable in rooms_by_id[room_id].unavailable:
            for week, week_active in enumerate(unavailable.weeks):
                if week_active != "1":
                    continue
                for day, day_active in enumerate(unavailable.days):
                    if day_active == "1":
                        blocked[(room_id, week, day)].append(
                            (
                                unavailable.start,
                                unavailable.start + unavailable.length,
                            )
                        )
            if time.monotonic() >= deadline:
                raise TimeoutError("ITC-2019 room-resource encoding timed out")

    for (room_id, week, day), intervals in sorted(blocked.items()):
        merged: list[list[int]] = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        for blocked_index, (start, end) in enumerate(merged):
            sparse_room_budget.claim(
                1,
                f"room-unavailability rectangles for room {room_id}",
            )
            flattened_start = (
                week * problem.nr_days + day
            ) * problem.slots_per_day + start
            suffix = f"{room_id}_{week}_{day}_{blocked_index}"
            x_intervals.append(
                model.new_fixed_size_interval_var(
                    flattened_start,
                    end - start,
                    f"room_unavailable_x_{suffix}",
                )
            )
            y_intervals.append(
                model.new_fixed_size_interval_var(
                    global_room_codes[room_id],
                    1,
                    f"room_unavailable_y_{suffix}",
                )
            )
            rectangles += 1
            if rectangles % 512 == 0 and time.monotonic() >= deadline:
                raise TimeoutError("ITC-2019 room-resource encoding timed out")

    sparse_room_budget.claim(1, "global room-resource NoOverlap2D")
    model.add_no_overlap_2d(x_intervals, y_intervals)


def _add_joint_sectioning(
    *,
    problem: ITC2019Problem,
    model: cp_model.CpModel,
    encoder: _PairEncoder,
    objective_terms: list[Any],
    maximum_terms: int,
    deadline: float,
) -> tuple[dict[tuple[str, str], cp_model.IntVar], int]:
    class_context = _class_context(problem)
    courses = {course.id: course for course in problem.courses}
    enrollment: dict[tuple[str, str], cp_model.IntVar] = {}
    for student in problem.students:
        for course_id in student.course_ids:
            course = courses[course_id]
            configuration_choices: list[cp_model.IntVar] = []
            for configuration in course.configurations:
                configuration_choice = model.new_bool_var(
                    f"student_{student.id}_course_{course_id}_config_{configuration.id}"
                )
                configuration_choices.append(configuration_choice)
                for subpart in configuration.subparts:
                    subpart_variables: list[cp_model.IntVar] = []
                    for klass in subpart.classes:
                        variable = enrollment.setdefault(
                            (student.id, klass.id),
                            model.new_bool_var(
                                f"student_{student.id}_class_{klass.id}"
                            ),
                        )
                        subpart_variables.append(variable)
                    model.add(sum(subpart_variables) == configuration_choice)
                    for klass in subpart.classes:
                        if klass.parent_id is not None:
                            model.add(
                                enrollment[(student.id, klass.id)]
                                <= enrollment[(student.id, klass.parent_id)]
                            )
            model.add_exactly_one(configuration_choices)
        if time.monotonic() >= deadline:
            raise TimeoutError("ITC-2019 factorized sectioning encoding timed out")

    enrollment_by_class: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    enrollment_by_student: dict[str, list[str]] = defaultdict(list)
    for (student_id, class_id), variable in enrollment.items():
        enrollment_by_class[class_id].append(variable)
        enrollment_by_student[student_id].append(class_id)
    for class_id, (_, _, _, klass) in class_context.items():
        variables = enrollment_by_class.get(class_id, [])
        if variables:
            model.add(sum(variables) <= klass.limit)

    terms = 0
    for student in problem.students:
        possible = sorted(enrollment_by_student[student.id])
        for first_id, second_id in combinations(possible, 2):
            terms += 1
            if terms > maximum_terms:
                raise _EncodingScaleExceeded(
                    "factorized joint sectioning needs more than "
                    f"{maximum_terms} student conjunctions"
                )
            time_conflict = encoder.same_attendees_violation(
                first_id,
                second_id,
                student_travel=True,
            )
            if time_conflict.constant == 0:
                continue
            first = enrollment[(student.id, first_id)]
            second = enrollment[(student.id, second_id)]
            conflict = model.new_bool_var(
                f"student_{student.id}_conflict_{first_id}_{second_id}"
            )
            model.add(conflict <= first)
            model.add(conflict <= second)
            if time_conflict.constant is None:
                model.add(conflict <= time_conflict.variable)
                model.add(conflict >= first + second + time_conflict.variable - 2)
            else:
                model.add(conflict >= first + second - 1)
            if problem.optimization.student:
                objective_terms.append(problem.optimization.student * conflict)
            if terms % 256 == 0 and time.monotonic() >= deadline:
                raise TimeoutError("ITC-2019 factorized sectioning encoding timed out")
    return enrollment, terms


def solve_itc2019_factorized(
    problem: ITC2019Problem,
    *,
    time_limit_seconds: float,
    workers: int,
    random_seed: int,
    max_pair_matrix_cells: int,
    max_group_table_rows: int,
    max_joint_student_conjunctions: int,
    max_sparse_room_constraints: int,
) -> ITC2019NativeSolveResult:
    """Solve with separate exact time and room domains.

    Timetabling predicates are encoded only over the dimensions they consume.
    ``max_group_table_rows`` is retained as a compatibility parameter but guards
    the exact sparse scan cells used by grouped distributions.
    Small sectioning models remain joint and exact.  Larger sectioning models use
    an exact fixed-timetable sectioning stage; those candidates are reported as
    feasible, never optimal, and are accepted only after independent validation and
    scoring.  Every table and both stages share one absolute wall-clock deadline.
    """

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
        raise ValueError("factorized ITC-2019 encoding budgets must be positive")

    started = time.monotonic()
    build_started = started
    deadline = started + float(time_limit_seconds)
    budget = _CellBudget(max_pair_matrix_cells)
    sparse_room_budget = _SparseRoomBudget(max_sparse_room_constraints)

    problem_errors = _validate_problem_references(problem)
    if problem_errors:
        return _factorized_failure(
            status="INVALID_PROBLEM",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
            budget=budget,
            sparse_room_budget=sparse_room_budget,
            validation_errors=problem_errors,
        )

    try:
        domains = _build_factorized_domains(problem, deadline=deadline)
    except TimeoutError:
        return _factorized_failure(
            status="DEADLINE_EXCEEDED",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
            budget=budget,
            sparse_room_budget=sparse_room_budget,
        )
    except _EncodingInfeasible as exc:
        return _factorized_failure(
            status="INFEASIBLE_DOMAIN",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
            budget=budget,
            sparse_room_budget=sparse_room_budget,
            validation_errors=(str(exc),),
        )

    model = cp_model.CpModel()
    time_choices: dict[str, cp_model.IntVar] = {}
    room_choices: dict[str, cp_model.IntVar] = {}
    room_assignments: dict[str, cp_model.IntVar] = {}
    time_selectors: dict[str, tuple[cp_model.IntVar, ...]] = {}
    room_selectors: dict[str, tuple[cp_model.IntVar, ...]] = {}
    objective_terms: list[Any] = []
    global_room_codes = {room.id: index for index, room in enumerate(problem.rooms)}
    no_room_code = len(global_room_codes)
    joint_upper_bound = _joint_sectioning_term_upper_bound(
        problem,
        max_joint_student_conjunctions,
    )
    joint_sectioning = bool(problem.students) and (
        joint_upper_bound <= max_joint_student_conjunctions
    )
    sectioning_mode = (
        "none"
        if not problem.students
        else "joint"
        if joint_sectioning
        else "staged_exact_fixed_timetable"
    )
    try:
        estimated_predicate_cells = _sparse_time_predicate_cells(
            problem,
            domains.times,
            joint_sectioning=joint_sectioning,
            deadline=deadline,
        )
        budget.claim(
            estimated_predicate_cells,
            "sparse time predicate encoding",
        )
        if time.monotonic() >= deadline:
            raise TimeoutError("ITC-2019 factorized predicate estimate timed out")
        for klass in problem.classes:
            class_times = domains.times[klass.id]
            class_rooms = domains.rooms[klass.id]
            time_variables = tuple(
                model.new_bool_var(f"class_{klass.id}_time_{index}")
                for index in range(len(class_times))
            )
            room_variables = tuple(
                model.new_bool_var(f"class_{klass.id}_room_{index}")
                for index in range(len(class_rooms))
            )
            time_selectors[klass.id] = time_variables
            room_selectors[klass.id] = room_variables
            model.add_exactly_one(time_variables)
            model.add_exactly_one(room_variables)

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
            room_codes = [
                global_room_codes[option.room_id]
                if option is not None
                else no_room_code
                for option in class_rooms
            ]
            room_assignment = model.new_int_var_from_domain(
                cp_model.Domain.from_values(room_codes),
                f"class_{klass.id}_global_room",
            )
            room_assignments[klass.id] = room_assignment
            model.add_element(room_choice, room_codes, room_assignment)
            for index, variable in enumerate(time_variables):
                model.add(time_choice == index).only_enforce_if(variable)
                coefficient = class_times[index].penalty * problem.optimization.time
                if coefficient:
                    objective_terms.append(coefficient * variable)
            for index, variable in enumerate(room_variables):
                model.add(room_choice == index).only_enforce_if(variable)
                room_option = class_rooms[index]
                coefficient = (
                    room_option.penalty * problem.optimization.room
                    if room_option is not None
                    else 0
                )
                if coefficient:
                    objective_terms.append(coefficient * variable)

            if time.monotonic() >= deadline:
                raise TimeoutError("ITC-2019 factorized variable encoding timed out")

        encoder = _PairEncoder(
            problem=problem,
            model=model,
            domains=domains,
            time_choices=time_choices,
            time_selectors=time_selectors,
            room_assignments=room_assignments,
            room_selectors=room_selectors,
            sparse_room_budget=sparse_room_budget,
            deadline=deadline,
        )
        _add_room_resources(
            problem=problem,
            domains=domains,
            model=model,
            time_selectors=time_selectors,
            room_assignments=room_assignments,
            sparse_room_budget=sparse_room_budget,
            deadline=deadline,
        )
        _add_distributions(
            problem=problem,
            model=model,
            domains=domains,
            time_choices=time_choices,
            time_selectors=time_selectors,
            encoder=encoder,
            objective_terms=objective_terms,
            max_group_table_rows=max_group_table_rows,
            deadline=deadline,
        )

        enrollment: dict[tuple[str, str], cp_model.IntVar] = {}
        if joint_sectioning:
            enrollment, _terms = _add_joint_sectioning(
                problem=problem,
                model=model,
                encoder=encoder,
                objective_terms=objective_terms,
                maximum_terms=max_joint_student_conjunctions,
                deadline=deadline,
            )
    except _EncodingScaleExceeded as exc:
        return _factorized_failure(
            status="UNSUPPORTED_MODEL_SCALE",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
            domains=domains,
            budget=budget,
            sparse_room_budget=sparse_room_budget,
            unsupported_reasons=(str(exc),),
            sectioning_mode=locals().get("sectioning_mode", "not_started"),
        )
    except _EncodingInfeasible as exc:
        return _factorized_failure(
            status="INFEASIBLE",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
            domains=domains,
            budget=budget,
            sparse_room_budget=sparse_room_budget,
            validation_errors=(str(exc),),
            sectioning_mode=locals().get("sectioning_mode", "not_started"),
        )
    except TimeoutError:
        return _factorized_failure(
            status="DEADLINE_EXCEEDED",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
            domains=domains,
            budget=budget,
            sparse_room_budget=sparse_room_budget,
            sectioning_mode=locals().get("sectioning_mode", "not_started"),
        )

    model.minimize(sum(objective_terms) if objective_terms else 0)
    build_finished = time.monotonic()
    remaining = deadline - build_finished
    if remaining <= 0:
        return _factorized_failure(
            status="DEADLINE_EXCEEDED",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
            domains=domains,
            budget=budget,
            sparse_room_budget=sparse_room_budget,
            sectioning_mode=sectioning_mode,
        )

    validation_reserve = min(0.1, max(0.005, time_limit_seconds * 0.02))
    if sectioning_mode == "staged_exact_fixed_timetable":
        sectioning_reserve = max(0.05, remaining * 0.35)
    else:
        sectioning_reserve = 0.0
    search_seconds = remaining - sectioning_reserve - validation_reserve
    if search_seconds <= 0:
        return _factorized_failure(
            status="DEADLINE_EXCEEDED",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
            domains=domains,
            budget=budget,
            sparse_room_budget=sparse_room_budget,
            sectioning_mode=sectioning_mode,
        )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(search_seconds)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.random_seed = int(random_seed)
    status_code = solver.solve(model)
    status = solver.status_name(status_code).upper()
    if status_code not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        finished = time.monotonic()
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
            formulation="factorized_domains_v2",
            sectioning_mode=sectioning_mode,
            time_domain_values=domains.time_values,
            room_domain_values=domains.room_values,
            predicate_table_cells=budget.used,
            sparse_room_constraints=sparse_room_budget.used,
        )

    placements: tuple[ITC2019ClassPlacement, ...] = tuple(
        ITC2019ClassPlacement(
            class_id=klass.id,
            days=domains.times[klass.id][
                int(solver.value(time_choices[klass.id]))
            ].days,
            start=domains.times[klass.id][
                int(solver.value(time_choices[klass.id]))
            ].start,
            weeks=domains.times[klass.id][
                int(solver.value(time_choices[klass.id]))
            ].weeks,
            room_id=(
                room_option.room_id
                if (
                    room_option := domains.rooms[klass.id][
                        int(solver.value(room_choices[klass.id]))
                    ]
                )
                is not None
                else None
            ),
        )
        for klass in problem.classes
    )

    sectioning_solver_wall = 0.0
    if sectioning_mode == "joint":
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
    elif sectioning_mode == "staged_exact_fixed_timetable":
        sectioning_remaining = deadline - time.monotonic() - validation_reserve
        if sectioning_remaining <= 0:
            return _factorized_failure(
                status="DEADLINE_EXCEEDED",
                started=started,
                build_started=build_started,
                random_seed=random_seed,
                workers=workers,
                domains=domains,
                budget=budget,
                sparse_room_budget=sparse_room_budget,
                sectioning_mode=sectioning_mode,
            )
        sectioning = solve_itc2019_student_sectioning(
            problem,
            placements,
            time_limit_seconds=sectioning_remaining,
            workers=workers,
            random_seed=random_seed,
            max_conflict_pairs=max_pair_matrix_cells,
            max_conflict_terms=max_pair_matrix_cells,
        )
        sectioning_solver_wall = sectioning.solver_wall_time_seconds
        if sectioning.status != "OPTIMAL" or not sectioning.is_feasible:
            return _factorized_failure(
                status=f"SECTIONING_{sectioning.status}",
                started=started,
                build_started=build_started,
                random_seed=random_seed,
                workers=workers,
                domains=domains,
                budget=budget,
                sparse_room_budget=sparse_room_budget,
                validation_errors=sectioning.validation_errors,
                sectioning_mode=sectioning_mode,
            )
        student_classes = sectioning.student_classes
        status = "FEASIBLE"
    else:
        student_classes = {}

    validation_errors = validate_itc2019_solution(
        problem,
        placements,
        student_classes,
    )
    objective = None
    if not validation_errors:
        try:
            objective = score_itc2019_solution(problem, placements, student_classes)
        except ValueError as exc:  # independent scorer remains the acceptance gate
            validation_errors = [str(exc)]
    finished = time.monotonic()
    if finished > deadline:
        return _factorized_failure(
            status="DEADLINE_EXCEEDED",
            started=started,
            build_started=build_started,
            random_seed=random_seed,
            workers=workers,
            domains=domains,
            budget=budget,
            sparse_room_budget=sparse_room_budget,
            sectioning_mode=sectioning_mode,
        )
    return ITC2019NativeSolveResult(
        status="INVALID_RESULT" if validation_errors else status,
        placements=placements,
        student_classes=student_classes,
        objective=objective,
        best_bound=(
            None
            if sectioning_mode == "staged_exact_fixed_timetable"
            else float(solver.best_objective_bound)
        ),
        wall_time_seconds=finished - started,
        model_build_seconds=build_finished - build_started,
        solver_wall_time_seconds=float(solver.wall_time) + sectioning_solver_wall,
        conflicts=int(solver.num_conflicts),
        branches=int(solver.num_branches),
        deterministic_seed=random_seed,
        workers=workers,
        validation_errors=tuple(validation_errors),
        formulation="factorized_domains_v2",
        sectioning_mode=sectioning_mode,
        time_domain_values=domains.time_values,
        room_domain_values=domains.room_values,
        predicate_table_cells=budget.used,
        sparse_room_constraints=sparse_room_budget.used,
    )


__all__ = ["solve_itc2019_factorized"]
