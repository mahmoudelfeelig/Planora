"""Global recurring-occurrence constructor for sparse ITC-2019 timetables.

This formulation keeps time and room decisions in one CP-SAT model.  Every
class uses one exact recurring time-choice table, every SameRoom component uses
one room variable, and one global two-dimensional non-overlap constraint packs
all meeting occurrences against concrete room resources and unavailability.

The admission predicate is intentionally semantic rather than instance-name
based.  Unsupported calendar or hard-distribution semantics fail closed and
fall back to another formulation.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
import time
from typing import Mapping

from ortools.sat.python import cp_model

from benchmarks.itc2019 import (
    ITC2019ClassPlacement,
    ITC2019Problem,
    _distribution_spec,
    _travel_values,
    validate_itc2019_solution,
)


_GLOBAL_COMPONENT_REQUIRED_TYPES = {
    "DifferentDays",
    "DifferentRoom",
    "DifferentTime",
    "NotOverlap",
    "Precedence",
    "SameAttendees",
    "SameDays",
    "SameRoom",
    "SameStart",
    "SameTime",
}


class _UnionFind:
    def __init__(self, values):
        self.parent = {value: value for value in values}

    def find(self, value):
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, first, second):
        first_root = self.find(first)
        second_root = self.find(second)
        if first_root != second_root:
            self.parent[second_root] = first_root


def itc2019_global_component_admission_reason(
    problem: ITC2019Problem,
) -> str | None:
    """Return why the exact recurring singleton-day representation is unsafe."""

    class_by_id = {klass.id: klass for klass in problem.classes}
    same_room = _UnionFind(class_by_id)
    same_room_members: set[str] = set()
    for klass in problem.classes:
        if not klass.time_options:
            return f"global_component_empty_time_domain:{klass.id}"
        lengths = {option.length for option in klass.time_options}
        if len(lengths) != 1:
            return f"global_component_variable_duration:{klass.id}"
        recurrence_counts = {option.weeks.count("1") for option in klass.time_options}
        if len(recurrence_counts) != 1 or 0 in recurrence_counts:
            return f"global_component_variable_or_empty_recurrence:{klass.id}"
        for option in klass.time_options:
            if option.days.count("1") != 1:
                return f"global_component_non_singleton_day:{klass.id}"
            if option.start < 0 or option.start + option.length > problem.slots_per_day:
                return f"global_component_cross_day_time:{klass.id}"
        if klass.room_required and not klass.room_options:
            return f"global_component_empty_room_domain:{klass.id}"

    for distribution in problem.distributions:
        if not distribution.required:
            continue
        base, _parameters = _distribution_spec(distribution.type)
        if base not in _GLOBAL_COMPONENT_REQUIRED_TYPES:
            return f"global_component_required_distribution_not_supported:{base}"
        if base == "SameRoom":
            class_ids = tuple(dict.fromkeys(distribution.class_ids))
            same_room_members.update(class_ids)
            for first_id, second_id in combinations(class_ids, 2):
                same_room.union(first_id, second_id)
        elif base == "DifferentRoom":
            for first_id, second_id in combinations(
                dict.fromkeys(distribution.class_ids), 2
            ):
                if (
                    not class_by_id[first_id].room_required
                    and not class_by_id[second_id].room_required
                ):
                    return (
                        "global_component_roomless_different_room_pair:"
                        f"{first_id}:{second_id}"
                    )

    component_members = defaultdict(list)
    for class_id in class_by_id:
        component_members[same_room.find(class_id)].append(class_id)
    for root, members in component_members.items():
        room_sets = [
            {option.room_id for option in class_by_id[class_id].room_options}
            for class_id in members
            if class_by_id[class_id].room_required
        ]
        if any(class_id in same_room_members for class_id in members) and len(
            room_sets
        ) != len(members):
            return f"global_component_roomless_same_room_component:{root}"
        if room_sets and not set.intersection(*room_sets):
            return f"global_component_empty_room_intersection:{root}"
    return None


def should_construct_itc2019_globally(problem: ITC2019Problem) -> bool:
    """Route only large, losslessly represented joint time-room instances."""

    if itc2019_global_component_admission_reason(problem) is not None:
        return False
    occurrence_rectangles = sum(
        next(iter({option.weeks.count("1") for option in klass.time_options}))
        for klass in problem.classes
        if klass.room_required
    )
    # The exact joint model is proven within the publication condition only
    # below this recurring-rectangle envelope.  Larger admitted instances need
    # a decomposed room-capacity representation; routing them here can spend the
    # whole condition without producing a first incumbent.
    return len(problem.classes) >= 500 and occurrence_rectangles <= 10_000


def construct_itc2019_global_components(
    problem: ITC2019Problem,
    *,
    deadline: float,
    workers: int,
    random_seed: int,
    diagnostics: dict | None = None,
) -> tuple[ITC2019ClassPlacement, ...] | None:
    """Construct a complete validator-clean timetable before ``deadline``.

    The input problem is immutable.  A partial CP assignment is never exposed;
    failure, timeout, unsupported semantics, and post-solve validation all
    return ``None``.
    """

    diagnostics = diagnostics if diagnostics is not None else {}
    started = time.monotonic()
    reason = itc2019_global_component_admission_reason(problem)
    if reason is not None:
        diagnostics["admission_reason"] = reason
        return None
    if time.monotonic() >= deadline:
        diagnostics["deadline_exhausted"] = True
        return None

    class_by_id = {klass.id: klass for klass in problem.classes}
    class_ids = tuple(class_by_id)
    same_room = _UnionFind(class_ids)
    for distribution in problem.distributions:
        if not distribution.required:
            continue
        base, _parameters = _distribution_spec(distribution.type)
        if base != "SameRoom":
            continue
        for first_id, second_id in combinations(
            dict.fromkeys(distribution.class_ids), 2
        ):
            same_room.union(first_id, second_id)

    component_members = defaultdict(list)
    for class_id in class_ids:
        component_members[same_room.find(class_id)].append(class_id)

    room_ids = tuple(sorted(room.id for room in problem.rooms))
    room_codes = {room_id: index for index, room_id in enumerate(room_ids)}
    rooms_by_code = dict(enumerate(room_ids))
    model = cp_model.CpModel()
    component_room_variables = {}
    for root, members in component_members.items():
        room_domains = [
            {
                room_codes[option.room_id]
                for option in class_by_id[class_id].room_options
            }
            for class_id in members
            if class_by_id[class_id].room_required
        ]
        if not room_domains:
            continue
        common_rooms = sorted(set.intersection(*room_domains))
        component_room_variables[root] = model.new_int_var_from_domain(
            cp_model.Domain.from_values(common_rooms), f"global_room_{root}"
        )

    travel = _travel_values(problem)
    maximum_travel = max(travel.values(), default=0)
    maximum_duration = max(
        option.length for klass in problem.classes for option in klass.time_options
    )
    # Padding is used only by SameAttendees.  It makes occurrences on distinct
    # calendar days automatically satisfy the rule, while preserving exact
    # within-day start and travel distances.
    attendee_stride = problem.slots_per_day + maximum_travel + maximum_duration

    choice_variables = {}
    day_variables = {}
    start_variables = {}
    regular_starts = {}
    attendee_starts = {}
    durations = {}
    time_intervals = {}
    room_intervals = {}
    for ordinal, klass in enumerate(problem.classes):
        if ordinal % 32 == 0 and time.monotonic() >= deadline:
            diagnostics["deadline_exhausted"] = True
            diagnostics["build_seconds"] = time.monotonic() - started
            return None
        lengths = {option.length for option in klass.time_options}
        duration = next(iter(lengths))
        durations[klass.id] = duration
        occurrence_count = next(
            iter({option.weeks.count("1") for option in klass.time_options})
        )
        rows = []
        for option_index, option in enumerate(klass.time_options):
            day_index = option.days.index("1")
            weeks = tuple(
                week_index
                for week_index, active in enumerate(option.weeks)
                if active == "1"
            )
            regular = tuple(
                (week_index * problem.nr_days + day_index) * problem.slots_per_day
                + option.start
                for week_index in weeks
            )
            padded = tuple(
                (week_index * problem.nr_days + day_index) * attendee_stride
                + option.start
                for week_index in weeks
            )
            rows.append((option_index, day_index, option.start, *regular, *padded))

        choice_variables[klass.id] = model.new_int_var(
            0, len(rows) - 1, f"global_choice_{klass.id}"
        )
        day_variables[klass.id] = model.new_int_var_from_domain(
            cp_model.Domain.from_values(sorted({row[1] for row in rows})),
            f"global_day_{klass.id}",
        )
        start_variables[klass.id] = model.new_int_var_from_domain(
            cp_model.Domain.from_values(sorted({row[2] for row in rows})),
            f"global_start_{klass.id}",
        )
        regular_starts[klass.id] = tuple(
            model.new_int_var_from_domain(
                cp_model.Domain.from_values(sorted({row[3 + index] for row in rows})),
                f"global_absolute_{klass.id}_{index}",
            )
            for index in range(occurrence_count)
        )
        attendee_starts[klass.id] = tuple(
            model.new_int_var_from_domain(
                cp_model.Domain.from_values(
                    sorted({row[3 + occurrence_count + index] for row in rows})
                ),
                f"global_attendee_absolute_{klass.id}_{index}",
            )
            for index in range(occurrence_count)
        )
        model.add_allowed_assignments(
            (
                choice_variables[klass.id],
                day_variables[klass.id],
                start_variables[klass.id],
                *regular_starts[klass.id],
                *attendee_starts[klass.id],
            ),
            rows,
        )
        time_intervals[klass.id] = tuple(
            model.new_fixed_size_interval_var(
                occurrence_start,
                duration,
                f"global_time_interval_{klass.id}_{index}",
            )
            for index, occurrence_start in enumerate(regular_starts[klass.id])
        )
        root = same_room.find(klass.id)
        if klass.room_required:
            room_intervals[klass.id] = tuple(
                model.new_fixed_size_interval_var(
                    component_room_variables[root],
                    1,
                    f"global_room_interval_{klass.id}_{index}",
                )
                for index in range(occurrence_count)
            )

    x_rectangles = [
        interval for class_id in room_intervals for interval in time_intervals[class_id]
    ]
    y_rectangles = [
        interval for class_id in room_intervals for interval in room_intervals[class_id]
    ]
    # Source files may describe overlapping unavailable windows for one room.
    # Feeding those fixed rectangles independently to NoOverlap2D makes the
    # blockers collide with each other and incorrectly proves the model
    # infeasible.  Union each room/week/day interval first; adjacency can be
    # merged as well because the represented unavailable slot set is unchanged.
    unavailable_by_resource = defaultdict(list)
    for room in problem.rooms:
        for unavailable in room.unavailable:
            for week_index, week_active in enumerate(unavailable.weeks):
                if week_active != "1":
                    continue
                for day_index, day_active in enumerate(unavailable.days):
                    if day_active == "1":
                        unavailable_by_resource[
                            (room.id, week_index, day_index)
                        ].append(
                            (unavailable.start, unavailable.start + unavailable.length)
                        )

    unavailable_rectangles = 0
    for (room_id, week_index, day_index), intervals in sorted(
        unavailable_by_resource.items()
    ):
        merged = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        for interval_index, (start, end) in enumerate(merged):
            unavailable_rectangles += 1
            absolute_start = (
                week_index * problem.nr_days + day_index
            ) * problem.slots_per_day + start
            suffix = f"{room_id}_{week_index}_{day_index}_{interval_index}"
            x_rectangles.append(
                model.new_fixed_size_interval_var(
                    absolute_start,
                    end - start,
                    f"global_unavailable_time_{suffix}",
                )
            )
            y_rectangles.append(
                model.new_fixed_size_interval_var(
                    room_codes[room_id],
                    1,
                    f"global_unavailable_room_{suffix}",
                )
            )
    model.add_no_overlap_2d(x_rectangles, y_rectangles)

    rule_pairs = 0
    for distribution in problem.distributions:
        if not distribution.required:
            continue
        base, _parameters = _distribution_spec(distribution.type)
        for first_id, second_id in combinations(
            dict.fromkeys(distribution.class_ids), 2
        ):
            rule_pairs += 1
            first_start = start_variables[first_id]
            second_start = start_variables[second_id]
            first_end = first_start + durations[first_id]
            second_end = second_start + durations[second_id]
            if base == "SameRoom":
                continue
            if base == "DifferentRoom":
                first_room = component_room_variables.get(same_room.find(first_id))
                second_room = component_room_variables.get(same_room.find(second_id))
                if first_room is not None and second_room is not None:
                    model.add(first_room != second_room)
            elif base == "SameDays":
                model.add(day_variables[first_id] == day_variables[second_id])
            elif base == "DifferentDays":
                model.add(day_variables[first_id] != day_variables[second_id])
            elif base == "SameStart":
                model.add(first_start == second_start)
            elif base == "SameTime":
                if durations[first_id] == durations[second_id]:
                    model.add(first_start == second_start)
                elif durations[first_id] > durations[second_id]:
                    model.add(first_start <= second_start)
                    model.add(second_end <= first_end)
                else:
                    model.add(second_start <= first_start)
                    model.add(first_end <= second_end)
            elif base == "DifferentTime":
                first_before = model.new_bool_var(
                    f"global_different_time_{first_id}_{second_id}"
                )
                model.add(first_end <= second_start).only_enforce_if(first_before)
                model.add(second_end <= first_start).only_enforce_if(first_before.Not())
            elif base == "NotOverlap":
                model.add_no_overlap(
                    (*time_intervals[first_id], *time_intervals[second_id])
                )
            elif base == "Precedence":
                model.add(
                    regular_starts[first_id][0] + durations[first_id]
                    <= regular_starts[second_id][0]
                )
            elif base == "SameAttendees":
                first_room = component_room_variables.get(same_room.find(first_id))
                second_room = component_room_variables.get(same_room.find(second_id))
                distance: int | cp_model.IntVar = 0
                if first_room is not None and second_room is not None:
                    distance = model.new_int_var(
                        0,
                        maximum_travel,
                        f"global_travel_{first_id}_{second_id}",
                    )
                    allowed_travel = []
                    first_domain = {
                        room_codes[option.room_id]
                        for option in class_by_id[first_id].room_options
                    }
                    second_domain = {
                        room_codes[option.room_id]
                        for option in class_by_id[second_id].room_options
                    }
                    for first_code in sorted(first_domain):
                        for second_code in sorted(second_domain):
                            first_room_id = rooms_by_code[first_code]
                            second_room_id = rooms_by_code[second_code]
                            travel_value = travel.get(
                                (first_room_id, second_room_id),
                                travel.get((second_room_id, first_room_id), 0),
                            )
                            allowed_travel.append(
                                (first_code, second_code, travel_value)
                            )
                    model.add_allowed_assignments(
                        (first_room, second_room, distance), allowed_travel
                    )
                for first_index, first_absolute in enumerate(attendee_starts[first_id]):
                    for second_index, second_absolute in enumerate(
                        attendee_starts[second_id]
                    ):
                        first_before = model.new_bool_var(
                            "global_attendee_order_"
                            f"{first_id}_{first_index}_{second_id}_{second_index}"
                        )
                        model.add(
                            first_absolute + durations[first_id] + distance
                            <= second_absolute
                        ).only_enforce_if(first_before)
                        model.add(
                            second_absolute + durations[second_id] + distance
                            <= first_absolute
                        ).only_enforce_if(first_before.Not())

    diagnostics["build_seconds"] = time.monotonic() - started
    diagnostics["meeting_rectangles"] = len(x_rectangles) - unavailable_rectangles
    diagnostics["unavailable_rectangles"] = unavailable_rectangles
    diagnostics["hard_rule_pairs"] = rule_pairs
    remaining = deadline - time.monotonic()
    finalization_reserve = min(2.0, max(0.2, remaining * 0.03))
    diagnostics["finalization_reserve_seconds"] = finalization_reserve
    if remaining <= finalization_reserve:
        diagnostics["deadline_exhausted"] = True
        return None
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.01, remaining - finalization_reserve)
    solver.parameters.num_search_workers = max(1, int(workers))
    solver.parameters.random_seed = int(random_seed)
    solve_started = time.monotonic()
    status = solver.solve(model)
    diagnostics["solve_seconds"] = time.monotonic() - solve_started
    diagnostics["solver_wall_time_seconds"] = solver.wall_time
    diagnostics["solver_status"] = solver.status_name(status)
    diagnostics["branches"] = solver.num_branches
    diagnostics["conflicts"] = solver.num_conflicts
    if status not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        if time.monotonic() >= deadline - finalization_reserve:
            diagnostics["deadline_exhausted"] = True
        return None

    placements = []
    for klass in problem.classes:
        option = klass.time_options[int(solver.value(choice_variables[klass.id]))]
        room_id = None
        if klass.room_required:
            room_id = rooms_by_code[
                int(solver.value(component_room_variables[same_room.find(klass.id)]))
            ]
        placements.append(
            ITC2019ClassPlacement(
                class_id=klass.id,
                days=option.days,
                start=option.start,
                weeks=option.weeks,
                room_id=room_id,
            )
        )
    if time.monotonic() > deadline:
        diagnostics["deadline_exhausted"] = True
        return None
    validation_errors = validate_itc2019_solution(problem, placements, {})
    diagnostics["validation_errors"] = tuple(validation_errors)
    diagnostics["wall_time_seconds"] = time.monotonic() - started
    if validation_errors or time.monotonic() > deadline:
        if time.monotonic() > deadline:
            diagnostics["deadline_exhausted"] = True
        return None
    return tuple(placements)
