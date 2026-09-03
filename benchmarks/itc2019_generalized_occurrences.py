"""Exact generalized-occurrence constructor for sparse ITC-2019 calendars.

Every selected time option contributes one optional interval per real
``(week, day)`` occurrence.  There are no padded or synthetic meetings.
Recurring room occupancy is coupled globally with ``NoOverlap2D`` while large
NotOverlap and SameAttendees groups reuse the occurrence intervals directly.

The admission predicate is semantic and deliberately narrow.  Unsupported
hard distributions and student sectioning fail closed to another formulation.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
import time

from ortools.sat.python import cp_model

from benchmarks.itc2019 import (
    ITC2019ClassPlacement,
    ITC2019Problem,
    ITC2019TimeOption,
    _distribution_spec,
    _pair_distribution_satisfied,
    _travel_values,
    validate_itc2019_solution,
)
from benchmarks.itc2019_factorized import _build_factorized_domains


_GENERALIZED_OCCURRENCE_REQUIRED_TYPES = frozenset(
    {"NotOverlap", "SameAttendees", "SameDays", "SameTime"}
)


def _occurrences(problem: ITC2019Problem, option: ITC2019TimeOption):
    for week, week_active in enumerate(option.weeks):
        if week_active != "1":
            continue
        for day, day_active in enumerate(option.days):
            if day_active == "1":
                yield week, day, option.start, option.length


def _placement(
    class_id: str,
    option: ITC2019TimeOption,
    room_id: str | None = None,
) -> ITC2019ClassPlacement:
    return ITC2019ClassPlacement(
        class_id=class_id,
        days=option.days,
        start=option.start,
        weeks=option.weeks,
        room_id=room_id,
    )


def itc2019_generalized_occurrence_admission_reason(
    problem: ITC2019Problem,
) -> str | None:
    """Return why the exact occurrence representation cannot handle ``problem``."""

    if problem.students:
        return "generalized_occurrence_students_not_supported"
    for klass in problem.classes:
        if not klass.time_options:
            return f"generalized_occurrence_empty_time_domain:{klass.id}"
        if klass.room_required and not klass.room_options:
            return f"generalized_occurrence_empty_room_domain:{klass.id}"
        for option in klass.time_options:
            if len(option.days) != problem.nr_days or "1" not in option.days:
                return f"generalized_occurrence_invalid_day_mask:{klass.id}"
            if len(option.weeks) != problem.nr_weeks or "1" not in option.weeks:
                return f"generalized_occurrence_invalid_week_mask:{klass.id}"
            if (
                option.start < 0
                or option.length <= 0
                or option.start + option.length > problem.slots_per_day
            ):
                return f"generalized_occurrence_cross_day_time:{klass.id}"
    for distribution in problem.distributions:
        if not distribution.required:
            continue
        base, _parameters = _distribution_spec(distribution.type)
        if base not in _GENERALIZED_OCCURRENCE_REQUIRED_TYPES:
            return f"generalized_occurrence_required_distribution_not_supported:{base}"
    return None


def should_construct_itc2019_generalized_occurrences(
    problem: ITC2019Problem,
) -> bool:
    """Admit only sparse generalized calendars suited to this formulation."""

    if itc2019_generalized_occurrence_admission_reason(problem) is not None:
        return False
    time_choices = sum(len(klass.time_options) for klass in problem.classes)
    option_occurrences = sum(
        option.days.count("1") * option.weeks.count("1")
        for klass in problem.classes
        for option in klass.time_options
    )
    has_generalized_calendar = any(
        option.days.count("1") > 1
        for klass in problem.classes
        for option in klass.time_options
    ) or any(
        len({option.length for option in klass.time_options}) > 1
        for klass in problem.classes
    )
    return (
        has_generalized_calendar
        and len(problem.classes) >= 250
        and time_choices <= 50_000
        and option_occurrences <= 100_000
    )


def construct_itc2019_generalized_occurrences(
    problem: ITC2019Problem,
    *,
    deadline: float,
    workers: int,
    random_seed: int,
    diagnostics: dict | None = None,
) -> tuple[ITC2019ClassPlacement, ...] | None:
    """Return a complete independently validated timetable or ``None``."""

    diagnostics = diagnostics if diagnostics is not None else {}
    started = time.monotonic()
    reason = itc2019_generalized_occurrence_admission_reason(problem)
    if reason is not None:
        diagnostics["admission_reason"] = reason
        return None
    if workers <= 0:
        raise ValueError("workers must be positive")
    if random_seed < 0:
        raise ValueError("random_seed must be non-negative")
    total_budget = max(0.0, deadline - started)
    finalization_reserve = min(5.0, max(0.5, total_budget * 0.05))
    build_deadline = deadline - finalization_reserve
    diagnostics["finalization_reserve_seconds"] = finalization_reserve
    if time.monotonic() >= build_deadline:
        diagnostics["deadline_exhausted"] = True
        return None

    try:
        domains = _build_factorized_domains(problem, deadline=build_deadline)
    except (TimeoutError, ValueError) as exc:
        diagnostics["domain_error"] = str(exc)
        diagnostics["deadline_exhausted"] = time.monotonic() >= build_deadline
        return None

    room_ids = tuple(room.id for room in problem.rooms)
    room_codes = {room_id: index for index, room_id in enumerate(room_ids)}
    rooms_by_code = dict(enumerate(room_ids))
    travel = _travel_values(problem)
    maximum_travel = max(travel.values(), default=0)
    model = cp_model.CpModel()
    choices = {}
    selectors = {}
    room_variables = {}
    intervals_by_class = defaultdict(list)
    x_rectangles = []
    y_rectangles = []
    option_occurrences = 0

    for class_index, klass in enumerate(problem.classes):
        options = domains.times[klass.id]
        choice = model.new_int_var(0, len(options) - 1, f"choice_{klass.id}")
        choices[klass.id] = choice
        class_selectors = tuple(
            model.new_bool_var(f"select_{klass.id}_{index}")
            for index in range(len(options))
        )
        selectors[klass.id] = class_selectors
        model.add_exactly_one(class_selectors)
        for index, selector in enumerate(class_selectors):
            model.add(choice == index).only_enforce_if(selector)

        if klass.room_required:
            codes = sorted(
                {
                    room_codes[room.room_id]
                    for room in domains.rooms[klass.id]
                    if room is not None
                }
            )
            if not codes:
                diagnostics["empty_room_domain"] = klass.id
                return None
            room_variables[klass.id] = model.new_int_var_from_domain(
                cp_model.Domain.from_values(codes), f"room_{klass.id}"
            )

        for option_index, (option, selector) in enumerate(
            zip(options, class_selectors, strict=True)
        ):
            for occurrence_index, (week, day, start, length) in enumerate(
                _occurrences(problem, option)
            ):
                absolute_start = (
                    week * problem.nr_days + day
                ) * problem.slots_per_day + start
                suffix = f"{klass.id}_{option_index}_{occurrence_index}"
                interval = model.new_optional_fixed_size_interval_var(
                    absolute_start,
                    length,
                    selector,
                    f"occurrence_{suffix}",
                )
                intervals_by_class[klass.id].append(interval)
                if klass.room_required:
                    x_rectangles.append(interval)
                    y_rectangles.append(
                        model.new_optional_fixed_size_interval_var(
                            room_variables[klass.id],
                            1,
                            selector,
                            f"occurrence_room_{suffix}",
                        )
                    )
                option_occurrences += 1
        if class_index % 32 == 0 and time.monotonic() >= build_deadline:
            diagnostics["deadline_exhausted"] = True
            return None

    unavailable_rectangles = 0
    for room in problem.rooms:
        for unavailable_index, unavailable in enumerate(room.unavailable):
            for week, day, start, length in _occurrences(problem, unavailable):
                absolute_start = (
                    week * problem.nr_days + day
                ) * problem.slots_per_day + start
                suffix = f"{room.id}_{unavailable_index}_{week}_{day}"
                x_rectangles.append(
                    model.new_fixed_size_interval_var(
                        absolute_start, length, f"unavailable_{suffix}"
                    )
                )
                y_rectangles.append(
                    model.new_fixed_size_interval_var(
                        room_codes[room.id], 1, f"unavailable_room_{suffix}"
                    )
                )
                unavailable_rectangles += 1
    if x_rectangles:
        model.add_no_overlap_2d(x_rectangles, y_rectangles)

    grouped_no_overlap = 0
    pair_table_rows = 0
    same_attendee_groups = []
    for distribution in problem.distributions:
        if not distribution.required:
            continue
        base, parameters = _distribution_spec(distribution.type)
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        if base in {"NotOverlap", "SameAttendees"}:
            intervals = [
                interval
                for class_id in class_ids
                for interval in intervals_by_class[class_id]
            ]
            if len(intervals) > 1:
                model.add_no_overlap(intervals)
                grouped_no_overlap += 1
            if base == "SameAttendees" and len(class_ids) > 1:
                same_attendee_groups.append(class_ids)
            continue
        for first_id, second_id in combinations(class_ids, 2):
            rows = []
            for first_index, first in enumerate(domains.times[first_id]):
                for second_index, second in enumerate(domains.times[second_id]):
                    if _pair_distribution_satisfied(
                        base,
                        parameters,
                        _placement(first_id, first),
                        first,
                        _placement(second_id, second),
                        second,
                        travel,
                    ):
                        rows.append((first_index, second_index))
            if not rows:
                diagnostics["empty_pair_relation"] = (
                    base,
                    first_id,
                    second_id,
                )
                return None
            model.add_allowed_assignments((choices[first_id], choices[second_id]), rows)
            pair_table_rows += len(rows)
        if time.monotonic() >= build_deadline:
            diagnostics["deadline_exhausted"] = True
            return None

    travel_support_keys = set()
    travel_forbidden_rows = 0
    for group_index, class_ids in enumerate(same_attendee_groups):
        starts = defaultdict(list)
        ends = defaultdict(list)
        for class_id in class_ids:
            for option_index, option in enumerate(domains.times[class_id]):
                for week, day, start, length in _occurrences(problem, option):
                    starts[(week, day, start)].append((class_id, option_index))
                    ends[(week, day, start + length)].append((class_id, option_index))
        for (week, day, end), ending_options in ends.items():
            for gap in range(maximum_travel):
                starting_options = starts.get((week, day, end + gap), ())
                for first_id, first_index in ending_options:
                    for second_id, second_index in starting_options:
                        if first_id == second_id:
                            continue
                        support_key = (
                            first_id,
                            first_index,
                            second_id,
                            second_index,
                        )
                        if support_key in travel_support_keys:
                            continue
                        travel_support_keys.add(support_key)
                        if (
                            first_id not in room_variables
                            or second_id not in room_variables
                        ):
                            continue
                        bad = {
                            (
                                room_codes[first_room.room_id],
                                room_codes[second_room.room_id],
                            )
                            for first_room in domains.rooms[first_id]
                            if first_room is not None
                            for second_room in domains.rooms[second_id]
                            if second_room is not None
                            and travel.get(
                                (first_room.room_id, second_room.room_id),
                                travel.get(
                                    (second_room.room_id, first_room.room_id), 0
                                ),
                            )
                            > gap
                        }
                        if bad:
                            model.add_forbidden_assignments(
                                (
                                    room_variables[first_id],
                                    room_variables[second_id],
                                ),
                                sorted(bad),
                            ).only_enforce_if(
                                (
                                    selectors[first_id][first_index],
                                    selectors[second_id][second_index],
                                )
                            )
                            travel_forbidden_rows += len(bad)
        if group_index % 4 == 0 and time.monotonic() >= build_deadline:
            diagnostics["deadline_exhausted"] = True
            return None

    diagnostics.update(
        {
            "build_seconds": time.monotonic() - started,
            "time_choices": sum(len(values) for values in domains.times.values()),
            "option_occurrences": option_occurrences,
            "room_rectangles": len(x_rectangles) - unavailable_rectangles,
            "unavailable_rectangles": unavailable_rectangles,
            "grouped_no_overlap": grouped_no_overlap,
            "pair_table_rows": pair_table_rows,
            "travel_supports": len(travel_support_keys),
            "travel_forbidden_rows": travel_forbidden_rows,
        }
    )
    remaining = build_deadline - time.monotonic()
    if remaining <= 0:
        diagnostics["deadline_exhausted"] = True
        return None
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = remaining
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.random_seed = int(random_seed)
    solve_started = time.monotonic()
    status = solver.solve(model)
    diagnostics.update(
        {
            "solve_seconds": time.monotonic() - solve_started,
            "solver_wall_time_seconds": solver.wall_time,
            "solver_status": solver.status_name(status),
            "branches": solver.num_branches,
            "conflicts": solver.num_conflicts,
        }
    )
    if status not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        diagnostics["deadline_exhausted"] = time.monotonic() >= build_deadline
        return None

    placements = []
    for klass in problem.classes:
        option = domains.times[klass.id][int(solver.value(choices[klass.id]))]
        room_id = None
        if klass.room_required:
            room_id = rooms_by_code[int(solver.value(room_variables[klass.id]))]
        placements.append(_placement(klass.id, option, room_id))
    if time.monotonic() >= deadline:
        diagnostics["deadline_exhausted"] = True
        return None
    errors = validate_itc2019_solution(problem, placements, {})
    diagnostics["validation_errors"] = tuple(errors)
    diagnostics["wall_time_seconds"] = time.monotonic() - started
    if errors or time.monotonic() >= deadline:
        diagnostics["deadline_exhausted"] = time.monotonic() >= deadline
        return None
    return tuple(placements)
