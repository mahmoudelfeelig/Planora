"""Compact joint constructor for recurring grouped ITC-2019 calendars.

The admitted representation factors each class' exact time domain into a day
pattern and a local start while retaining one class-level room variable.  Hard
grouped load constraints, attendee travel, room availability, and recurring
room occupancy remain coupled in one CP-SAT model.  The admission predicate is
semantic and fails closed whenever this factorization would lose information.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
import time

from ortools.sat.python import cp_model

from benchmarks.itc2019 import (
    ITC2019ClassPlacement,
    ITC2019Problem,
    _distribution_spec,
    _masks_overlap,
    _travel_values,
    validate_itc2019_solution,
)
from benchmarks.itc2019_factorized import _build_factorized_domains


_GROUPED_CALENDAR_REQUIRED_TYPES = frozenset(
    {
        "DifferentDays",
        "MaxDayLoad",
        "MaxDays",
        "MinGap",
        "SameAttendees",
        "SameDays",
        "SameRoom",
    }
)
_GROUPED_CALENDAR_GROUP_TYPES = frozenset({"MaxDayLoad", "MaxDays"})


def itc2019_grouped_calendar_admission_reason(
    problem: ITC2019Problem,
) -> str | None:
    """Return why the exact recurring day/start factorization is unsafe."""

    if problem.students:
        return "grouped_calendar_students_not_supported"
    if not any(
        distribution.required
        and _distribution_spec(distribution.type)[0] in _GROUPED_CALENDAR_GROUP_TYPES
        for distribution in problem.distributions
    ):
        return "grouped_calendar_no_required_grouped_constraint"

    class_by_id = {klass.id: klass for klass in problem.classes}
    for klass in problem.classes:
        if not klass.time_options:
            return f"grouped_calendar_empty_time_domain:{klass.id}"
        if klass.room_required and not klass.room_options:
            return f"grouped_calendar_empty_room_domain:{klass.id}"
        weeks = {option.weeks for option in klass.time_options}
        lengths = {option.length for option in klass.time_options}
        if len(weeks) != 1:
            return f"grouped_calendar_variable_week_mask:{klass.id}"
        if len(lengths) != 1:
            return f"grouped_calendar_variable_duration:{klass.id}"
        keys = set()
        for option in klass.time_options:
            if (
                len(option.days) != problem.nr_days
                or len(option.weeks) != problem.nr_weeks
                or "1" not in option.days
                or "1" not in option.weeks
            ):
                return f"grouped_calendar_invalid_mask:{klass.id}"
            if (
                option.length <= 0
                or option.start < 0
                or option.start + option.length > problem.slots_per_day
            ):
                return f"grouped_calendar_cross_day_time:{klass.id}"
            key = (option.days, option.start)
            if key in keys:
                return f"grouped_calendar_duplicate_day_start:{klass.id}"
            keys.add(key)

    for distribution in problem.distributions:
        if not distribution.required:
            continue
        base, parameters = _distribution_spec(distribution.type)
        if base not in _GROUPED_CALENDAR_REQUIRED_TYPES:
            return f"grouped_calendar_required_distribution_not_supported:{base}"
        if any(class_id not in class_by_id for class_id in distribution.class_ids):
            return f"grouped_calendar_unknown_distribution_class:{base}"
        if base == "SameRoom" and any(
            not class_by_id[class_id].room_required
            for class_id in distribution.class_ids
        ):
            return "grouped_calendar_roomless_same_room"
        if base in {"MaxDayLoad", "MaxDays", "MinGap"} and len(parameters) != 1:
            return f"grouped_calendar_invalid_parameters:{base}"
    return None


def should_construct_itc2019_grouped_calendar(problem: ITC2019Problem) -> bool:
    """Route only large, bounded calendars with lossless grouped semantics."""

    if itc2019_grouped_calendar_admission_reason(problem) is not None:
        return False
    if len(problem.classes) < 250:
        return False
    day_patterns = {
        option.days for klass in problem.classes for option in klass.time_options
    }
    if len(day_patterns) > 64:
        return False
    time_room_rows = sum(
        len(klass.time_options)
        * (len(klass.room_options) if klass.room_required else 1)
        for klass in problem.classes
    )
    if time_room_rows > 300_000:
        return False
    attendee_pairs = {
        tuple(sorted((first, second)))
        for distribution in problem.distributions
        if distribution.required
        and _distribution_spec(distribution.type)[0] == "SameAttendees"
        for first, second in combinations(dict.fromkeys(distribution.class_ids), 2)
    }
    return len(attendee_pairs) <= 10_000


def construct_itc2019_grouped_calendar(
    problem: ITC2019Problem,
    *,
    deadline: float,
    workers: int,
    random_seed: int,
    diagnostics: dict | None = None,
) -> tuple[ITC2019ClassPlacement, ...] | None:
    """Return a complete independently validated grouped-calendar timetable."""

    diagnostics = diagnostics if diagnostics is not None else {}
    started = time.monotonic()
    reason = itc2019_grouped_calendar_admission_reason(problem)
    if reason is not None:
        diagnostics["admission_reason"] = reason
        return None
    if workers <= 0:
        raise ValueError("workers must be positive")
    if random_seed < 0:
        raise ValueError("random_seed must be non-negative")

    total_budget = max(0.0, deadline - started)
    finalization_reserve = min(3.0, max(0.5, total_budget * 0.03))
    solve_deadline = deadline - finalization_reserve
    diagnostics["finalization_reserve_seconds"] = finalization_reserve
    if time.monotonic() >= solve_deadline:
        diagnostics["deadline_exhausted"] = True
        return None
    try:
        domains = _build_factorized_domains(problem, deadline=solve_deadline)
    except (TimeoutError, ValueError) as exc:
        diagnostics["domain_error"] = str(exc)
        diagnostics["deadline_exhausted"] = time.monotonic() >= solve_deadline
        return None

    day_patterns = tuple(
        sorted(
            {option.days for options in domains.times.values() for option in options}
        )
    )
    day_codes = {pattern: index for index, pattern in enumerate(day_patterns)}
    model = cp_model.CpModel()
    days = {}
    starts = {}
    day_present = {}
    time_intervals = {}
    gap_intervals = {}
    weeks = {}
    lengths = {}
    option_by_pair = {}

    for class_index, klass in enumerate(problem.classes):
        options = domains.times[klass.id]
        weeks[klass.id] = options[0].weeks
        lengths[klass.id] = options[0].length
        pairs = {(day_codes[option.days], option.start): option for option in options}
        option_by_pair[klass.id] = pairs
        day_values = sorted({pair[0] for pair in pairs})
        start_values = sorted({pair[1] for pair in pairs})
        days[klass.id] = model.new_int_var_from_domain(
            cp_model.Domain.from_values(day_values), f"grouped_day_{klass.id}"
        )
        starts[klass.id] = model.new_int_var_from_domain(
            cp_model.Domain.from_values(start_values), f"grouped_start_{klass.id}"
        )
        if len(pairs) != len(day_values) * len(start_values):
            model.add_allowed_assignments(
                (days[klass.id], starts[klass.id]), sorted(pairs)
            )
        for day in range(problem.nr_days):
            active_codes = [
                code for code in day_values if day_patterns[code][day] == "1"
            ]
            if not active_codes:
                presence = model.new_constant(0)
            elif len(active_codes) == len(day_values):
                presence = model.new_constant(1)
            else:
                presence = model.new_bool_var(f"grouped_present_{klass.id}_{day}")
                model.add_allowed_assignments(
                    (days[klass.id], presence),
                    [(code, int(code in active_codes)) for code in day_values],
                )
            day_present[(klass.id, day)] = presence
            time_intervals[(klass.id, day)] = (
                model.new_optional_fixed_size_interval_var(
                    starts[klass.id],
                    lengths[klass.id],
                    presence,
                    f"grouped_meeting_{klass.id}_{day}",
                )
            )
        if class_index % 32 == 0 and time.monotonic() >= solve_deadline:
            diagnostics["deadline_exhausted"] = True
            return None

    grouped_keys = set()
    same_attendee_pairs = set()
    hard_counts = defaultdict(int)
    for distribution in problem.distributions:
        if not distribution.required:
            continue
        base, parameters = _distribution_spec(distribution.type)
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        hard_counts[base] += 1
        if base == "SameAttendees":
            same_attendee_pairs.update(
                tuple(sorted((first, second)))
                for first, second in combinations(class_ids, 2)
                if _masks_overlap(weeks[first], weeks[second])
            )
        elif base == "DifferentDays":
            for day in range(problem.nr_days):
                model.add_at_most_one(
                    day_present[(class_id, day)] for class_id in class_ids
                )
        elif base == "SameDays":
            for first, second in combinations(class_ids, 2):
                first_values = sorted({pair[0] for pair in option_by_pair[first]})
                second_values = sorted({pair[0] for pair in option_by_pair[second]})
                rows = []
                for first_code in first_values:
                    first_mask = day_patterns[first_code]
                    for second_code in second_values:
                        second_mask = day_patterns[second_code]
                        first_subset = all(
                            left != "1" or right == "1"
                            for left, right in zip(first_mask, second_mask)
                        )
                        second_subset = all(
                            right != "1" or left == "1"
                            for left, right in zip(first_mask, second_mask)
                        )
                        if first_subset or second_subset:
                            rows.append((first_code, second_code))
                model.add_allowed_assignments((days[first], days[second]), rows)
        elif base == "MinGap":
            (minimum_gap,) = parameters
            for first, second in combinations(class_ids, 2):
                if not _masks_overlap(weeks[first], weeks[second]):
                    continue
                for day in range(problem.nr_days):
                    for class_id in (first, second):
                        key = (class_id, day, minimum_gap)
                        if key not in gap_intervals:
                            gap_intervals[key] = (
                                model.new_optional_fixed_size_interval_var(
                                    starts[class_id],
                                    lengths[class_id] + minimum_gap,
                                    day_present[(class_id, day)],
                                    f"grouped_gap_{minimum_gap}_{class_id}_{day}",
                                )
                            )
                    model.add_no_overlap(
                        (
                            gap_intervals[(first, day, minimum_gap)],
                            gap_intervals[(second, day, minimum_gap)],
                        )
                    )
        elif base == "MaxDayLoad":
            (maximum_load,) = parameters
            for week in range(problem.nr_weeks):
                active = tuple(
                    sorted(
                        class_id
                        for class_id in class_ids
                        if weeks[class_id][week] == "1"
                    )
                )
                for day in range(problem.nr_days):
                    key = (base, active, day, maximum_load)
                    if key in grouped_keys:
                        continue
                    grouped_keys.add(key)
                    model.add(
                        sum(
                            lengths[class_id] * day_present[(class_id, day)]
                            for class_id in active
                        )
                        <= maximum_load
                    )
        elif base == "MaxDays":
            (maximum_days,) = parameters
            used_days = []
            for day in range(problem.nr_days):
                active = [day_present[(class_id, day)] for class_id in class_ids]
                used = model.new_bool_var(f"grouped_max_days_{len(grouped_keys)}_{day}")
                model.add_max_equality(used, active)
                used_days.append(used)
            model.add(sum(used_days) <= maximum_days)
            grouped_keys.add((base, class_ids, maximum_days))
        elif base == "SameRoom":
            continue

    room_ids = tuple(room.id for room in problem.rooms)
    room_codes = {room_id: index for index, room_id in enumerate(room_ids)}
    room_by_code = dict(enumerate(room_ids))
    room_variables = {}
    room_domains = {}
    room_intervals = {}
    room_availability_rows = 0
    for class_offset, klass in enumerate(problem.classes):
        if klass.room_required:
            codes = sorted(
                {
                    room_codes[option.room_id]
                    for option in domains.rooms[klass.id]
                    if option is not None
                }
            )
        else:
            code = len(room_ids) + class_offset
            codes = [code]
            room_by_code[code] = None
        room_domains[klass.id] = tuple(codes)
        room_variables[klass.id] = (
            model.new_constant(codes[0])
            if len(codes) == 1
            else model.new_int_var_from_domain(
                cp_model.Domain.from_values(codes),
                f"grouped_room_{klass.id}",
            )
        )
        if klass.room_required:
            available_rows = []
            for (day_code, start), option in option_by_pair[klass.id].items():
                for room_code in codes:
                    room = problem.rooms[room_code]
                    blocked = any(
                        _masks_overlap(option.days, unavailable.days)
                        and _masks_overlap(option.weeks, unavailable.weeks)
                        and option.start < unavailable.start + unavailable.length
                        and unavailable.start < option.start + option.length
                        for unavailable in room.unavailable
                    )
                    if not blocked:
                        available_rows.append((day_code, start, room_code))
            if not available_rows:
                diagnostics["empty_time_room_domain"] = klass.id
                return None
            model.add_allowed_assignments(
                (
                    days[klass.id],
                    starts[klass.id],
                    room_variables[klass.id],
                ),
                available_rows,
            )
            room_availability_rows += len(available_rows)
        for day in range(problem.nr_days):
            room_intervals[(klass.id, day)] = (
                model.new_optional_fixed_size_interval_var(
                    room_variables[klass.id],
                    1,
                    day_present[(klass.id, day)],
                    f"grouped_room_interval_{klass.id}_{day}",
                )
            )

    for distribution in problem.distributions:
        if not distribution.required:
            continue
        base, _parameters = _distribution_spec(distribution.type)
        if base != "SameRoom":
            continue
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        for first, second in zip(class_ids, class_ids[1:]):
            model.add(room_variables[first] == room_variables[second])

    travel = _travel_values(problem)
    maximum_travel = max(travel.values(), default=0)
    attendee_room_rows = 0
    for first, second in sorted(same_attendee_pairs):
        first_day_values = sorted({pair[0] for pair in option_by_pair[first]})
        second_day_values = sorted({pair[0] for pair in option_by_pair[second]})
        day_overlap = model.new_bool_var(
            f"grouped_attendee_day_overlap_{first}_{second}"
        )
        model.add_allowed_assignments(
            (days[first], days[second], day_overlap),
            [
                (
                    first_code,
                    second_code,
                    int(
                        _masks_overlap(
                            day_patterns[first_code], day_patterns[second_code]
                        )
                    ),
                )
                for first_code in first_day_values
                for second_code in second_day_values
            ],
        )
        distance = model.new_int_var(
            0,
            maximum_travel,
            f"grouped_attendee_travel_{first}_{second}",
        )
        distance_rows = []
        for first_code in room_domains[first]:
            for second_code in room_domains[second]:
                first_room = room_by_code[first_code]
                second_room = room_by_code[second_code]
                value = 0
                if first_room is not None and second_room is not None:
                    value = travel.get(
                        (first_room, second_room),
                        travel.get((second_room, first_room), 0),
                    )
                distance_rows.append((first_code, second_code, value))
        model.add_allowed_assignments(
            (room_variables[first], room_variables[second], distance),
            distance_rows,
        )
        attendee_room_rows += len(distance_rows)
        first_before = model.new_bool_var(
            f"grouped_attendee_first_before_{first}_{second}"
        )
        second_before = model.new_bool_var(
            f"grouped_attendee_second_before_{first}_{second}"
        )
        model.add(
            starts[first] + lengths[first] + distance <= starts[second]
        ).only_enforce_if(first_before)
        model.add(
            starts[second] + lengths[second] + distance <= starts[first]
        ).only_enforce_if(second_before)
        model.add_bool_or((day_overlap.Not(), first_before, second_before))

    room_layers = set()
    room_rectangles = 0
    for week in range(problem.nr_weeks):
        active = tuple(
            klass.id for klass in problem.classes if weeks[klass.id][week] == "1"
        )
        for day in range(problem.nr_days):
            layer = (active, day)
            if layer in room_layers:
                continue
            room_layers.add(layer)
            model.add_no_overlap_2d(
                [time_intervals[(class_id, day)] for class_id in active],
                [room_intervals[(class_id, day)] for class_id in active],
            )
            room_rectangles += len(active)

    time_penalties = []
    for klass in problem.classes:
        pairs = option_by_pair[klass.id]
        maximum_penalty = max(option.penalty for option in pairs.values())
        if maximum_penalty == 0:
            continue
        penalty = model.new_int_var(
            0, maximum_penalty, f"grouped_time_penalty_{klass.id}"
        )
        model.add_allowed_assignments(
            (days[klass.id], starts[klass.id], penalty),
            sorted(
                (day, start, option.penalty) for (day, start), option in pairs.items()
            ),
        )
        time_penalties.append(penalty)
    if time_penalties:
        model.minimize(sum(time_penalties))

    diagnostics.update(
        {
            "build_seconds": time.monotonic() - started,
            "day_patterns": len(day_patterns),
            "hard_counts": dict(hard_counts),
            "grouped_constraints": len(grouped_keys),
            "same_attendee_pairs": len(same_attendee_pairs),
            "same_attendee_room_rows": attendee_room_rows,
            "room_availability_rows": room_availability_rows,
            "recurring_room_layers": len(room_layers),
            "room_rectangles": room_rectangles,
        }
    )
    remaining = solve_deadline - time.monotonic()
    if remaining <= 0:
        diagnostics["deadline_exhausted"] = True
        return None
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = remaining
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.random_seed = int(random_seed)
    solver.parameters.linearization_level = 0
    solver.parameters.stop_after_first_solution = True
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
        diagnostics["deadline_exhausted"] = time.monotonic() >= solve_deadline
        return None

    placements = []
    for klass in problem.classes:
        key = (
            int(solver.value(days[klass.id])),
            int(solver.value(starts[klass.id])),
        )
        option = option_by_pair[klass.id][key]
        placements.append(
            ITC2019ClassPlacement(
                class_id=klass.id,
                days=option.days,
                start=option.start,
                weeks=option.weeks,
                room_id=room_by_code[int(solver.value(room_variables[klass.id]))],
            )
        )
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
