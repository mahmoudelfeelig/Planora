"""Bounded quality improvement for decomposed ITC-2019 incumbents."""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
import time

from ortools.sat.python import cp_model

from benchmarks.itc2019 import (
    ITC2019ClassPlacement,
    ITC2019Problem,
    _PAIR_DISTRIBUTIONS,
    _distribution_spec,
    _pair_distribution_satisfied,
    _special_distribution_units,
    _student_pair_conflicts,
    _travel_values,
    score_itc2019_solution,
    validate_itc2019_solution,
)
from benchmarks.itc2019_factorized import _build_factorized_domains


def occurrences(option):
    for week, week_active in enumerate(option.weeks):
        if week_active != "1":
            continue
        for day, day_active in enumerate(option.days):
            if day_active != "1":
                continue
            for slot in range(option.start, option.start + option.length):
                yield week, day, slot


def _improve_fixed_time_rooms(
    problem: ITC2019Problem,
    placements,
    student_classes,
    *,
    current_times,
    current_indices,
    admitted_rooms_by_time,
    room_penalties,
    travel,
    hard_rule_edges,
    deadline: float,
    workers: int,
    random_seed: int,
):
    """Optimize rooms exactly for fixed times, including room-sensitive soft rules."""

    if student_classes or deadline - time.monotonic() <= 1.0:
        return None, None
    model = cp_model.CpModel()
    room_codes = {room.id: index for index, room in enumerate(problem.rooms)}
    room_variables = {}
    room_code_domains = {}
    room_by_code = {}
    room_cost_variables = []
    for class_index, klass in enumerate(problem.classes):
        class_id = klass.id
        room_ids = admitted_rooms_by_time[(class_id, current_indices[class_id])]
        if room_ids == (None,):
            code = len(room_codes) + class_index
            room_variables[class_id] = model.new_constant(code)
            room_code_domains[class_id] = (code,)
            room_by_code[(class_id, code)] = None
            continue
        codes = tuple(room_codes[room_id] for room_id in room_ids)
        room_code_domains[class_id] = codes
        room_by_code.update(
            ((class_id, room_codes[room_id]), room_id) for room_id in room_ids
        )
        variable = model.new_int_var_from_domain(
            cp_model.Domain.from_values(codes), f"fixed_time_room_{class_id}"
        )
        room_variables[class_id] = variable
        cost = model.new_int_var(
            0,
            max(room_penalties[class_id].values(), default=0),
            f"fixed_time_room_cost_{class_id}",
        )
        model.add_allowed_assignments(
            (variable, cost),
            [
                (code, room_penalties[class_id][room_by_code[(class_id, code)]])
                for code in codes
            ],
        )
        room_cost_variables.append(cost)
        incumbent_room = placements[class_id].room_id
        if incumbent_room is not None and room_codes[incumbent_room] in codes:
            model.add_hint(variable, room_codes[incumbent_room])

    occurrence_classes = defaultdict(list)
    for class_id, option in current_times.items():
        for occurrence in occurrences(option):
            occurrence_classes[occurrence].append(class_id)
    for class_ids in {
        tuple(sorted(class_ids))
        for class_ids in occurrence_classes.values()
        if len(class_ids) > 1
    }:
        model.add_all_different([room_variables[class_id] for class_id in class_ids])

    for first_id, second_id, base, parameters in hard_rule_edges:
        first_time = current_times[first_id]
        second_time = current_times[second_id]
        forbidden = []
        for first_code in room_code_domains[first_id]:
            first_room = room_by_code[(first_id, first_code)]
            first_candidate = ITC2019ClassPlacement(
                class_id=first_id,
                days=first_time.days,
                start=first_time.start,
                weeks=first_time.weeks,
                room_id=first_room,
            )
            for second_code in room_code_domains[second_id]:
                second_room = room_by_code[(second_id, second_code)]
                second_candidate = ITC2019ClassPlacement(
                    class_id=second_id,
                    days=second_time.days,
                    start=second_time.start,
                    weeks=second_time.weeks,
                    room_id=second_room,
                )
                if not _pair_distribution_satisfied(
                    base,
                    parameters,
                    first_candidate,
                    first_time,
                    second_candidate,
                    second_time,
                    travel,
                ):
                    forbidden.append((first_code, second_code))
        if forbidden:
            model.add_forbidden_assignments(
                (room_variables[first_id], room_variables[second_id]), forbidden
            )
        if time.monotonic() >= deadline - 0.5:
            return None, None

    soft_room_cost_variables = []
    for distribution_index, distribution in enumerate(problem.distributions):
        if distribution.required:
            continue
        base, parameters = _distribution_spec(distribution.type)
        if base not in {"SameRoom", "DifferentRoom", "SameAttendees"}:
            continue
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        for pair_index, (first_id, second_id) in enumerate(combinations(class_ids, 2)):
            first_time = current_times[first_id]
            second_time = current_times[second_id]
            rows = []
            for first_code in room_code_domains[first_id]:
                first_room = room_by_code[(first_id, first_code)]
                first_candidate = ITC2019ClassPlacement(
                    first_id,
                    first_time.days,
                    first_time.start,
                    first_time.weeks,
                    first_room,
                )
                for second_code in room_code_domains[second_id]:
                    second_room = room_by_code[(second_id, second_code)]
                    second_candidate = ITC2019ClassPlacement(
                        second_id,
                        second_time.days,
                        second_time.start,
                        second_time.weeks,
                        second_room,
                    )
                    satisfied = _pair_distribution_satisfied(
                        base,
                        parameters,
                        first_candidate,
                        first_time,
                        second_candidate,
                        second_time,
                        travel,
                    )
                    rows.append(
                        (
                            first_code,
                            second_code,
                            0 if satisfied else distribution.penalty,
                        )
                    )
            cost = model.new_int_var(
                0,
                distribution.penalty,
                f"fixed_time_soft_room_{distribution_index}_{pair_index}",
            )
            model.add_allowed_assignments(
                (room_variables[first_id], room_variables[second_id], cost), rows
            )
            soft_room_cost_variables.append(cost)
            if time.monotonic() >= deadline - 0.5:
                return None, None

    model.minimize(
        problem.optimization.room * sum(room_cost_variables)
        + problem.optimization.distribution * sum(soft_room_cost_variables)
    )
    remaining = deadline - time.monotonic() - 0.25
    if remaining <= 0:
        return None, None
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = remaining
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = random_seed
    status = solver.solve(model)
    telemetry = {
        "status": solver.status_name(status),
        "wall_time_seconds": solver.wall_time,
        "branches": solver.num_branches,
        "conflicts": solver.num_conflicts,
    }
    if status not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        return None, telemetry
    candidate = {}
    for klass in problem.classes:
        class_id = klass.id
        old = placements[class_id]
        code = int(solver.value(room_variables[class_id]))
        candidate[class_id] = ITC2019ClassPlacement(
            class_id=class_id,
            days=old.days,
            start=old.start,
            weeks=old.weeks,
            room_id=room_by_code[(class_id, code)],
        )
    if validate_itc2019_solution(problem, candidate, student_classes):
        return None, telemetry
    before = score_itc2019_solution(problem, placements, student_classes)
    after = score_itc2019_solution(problem, candidate, student_classes)
    telemetry["before_score"] = before.total
    telemetry["after_score"] = after.total
    return (candidate if after.total < before.total else None), telemetry


def _improve_fixed_room_times(
    problem: ITC2019Problem,
    placements,
    student_classes,
    *,
    time_domains,
    admitted_rooms_by_time,
    travel,
    deadline: float,
    workers: int,
    random_seed: int,
):
    """Optimize time and pair-distribution cost with incumbent rooms fixed."""

    if deadline - time.monotonic() <= 1.0:
        return None
    model = cp_model.CpModel()
    choice_variables = {}
    selectors_by_class = {}
    time_costs = []
    room_intervals = defaultdict(list)
    valid_indices = {}
    current_indices = {}
    for klass in problem.classes:
        class_id = klass.id
        placement = placements[class_id]
        indices = tuple(
            option_index
            for option_index, _option in enumerate(time_domains[class_id])
            if placement.room_id in admitted_rooms_by_time[(class_id, option_index)]
        )
        if not indices:
            return None
        valid_indices[class_id] = indices
        choice = model.new_int_var_from_domain(
            cp_model.Domain.from_values(indices), f"fixed_room_time_{class_id}"
        )
        choice_variables[class_id] = choice
        selectors = {}
        for option_index in indices:
            selector = model.new_bool_var(
                f"fixed_room_select_{class_id}_{option_index}"
            )
            selectors[option_index] = selector
            model.add(choice == option_index).only_enforce_if(selector)
            option = time_domains[class_id][option_index]
            if placement.room_id is not None:
                for week, week_active in enumerate(option.weeks):
                    if week_active != "1":
                        continue
                    for day, day_active in enumerate(option.days):
                        if day_active != "1":
                            continue
                        room_intervals[(placement.room_id, day, week)].append(
                            model.new_optional_fixed_size_interval_var(
                                option.start,
                                option.length,
                                selector,
                                f"fixed_room_interval_{class_id}_{option_index}_{day}_{week}",
                            )
                        )
            if (
                option.days == placement.days
                and option.start == placement.start
                and option.weeks == placement.weeks
            ):
                current_indices[class_id] = option_index
        model.add_exactly_one(selectors.values())
        selectors_by_class[class_id] = selectors
        cost = model.new_int_var(
            0,
            max(option.penalty for option in time_domains[class_id]),
            f"fixed_room_time_cost_{class_id}",
        )
        model.add_element(
            choice,
            [option.penalty for option in time_domains[class_id]],
            cost,
        )
        time_costs.append(cost)
        if class_id not in current_indices:
            return None
        model.add_hint(choice, current_indices[class_id])
        if time.monotonic() >= deadline - 0.5:
            return None

    for intervals in room_intervals.values():
        if len(intervals) > 1:
            model.add_no_overlap(intervals)

    distribution_costs = []
    for distribution in problem.distributions:
        base, parameters = _distribution_spec(distribution.type)
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        if base not in {
            "SameStart",
            "SameTime",
            "DifferentTime",
            "SameDays",
            "DifferentDays",
            "SameWeeks",
            "DifferentWeeks",
            "SameRoom",
            "DifferentRoom",
            "Overlap",
            "NotOverlap",
            "SameAttendees",
            "Precedence",
            "WorkDay",
            "MinGap",
        }:
            continue
        for first_id, second_id in combinations(class_ids, 2):
            rows = []
            for first_index in valid_indices[first_id]:
                first_time = time_domains[first_id][first_index]
                first_placement = ITC2019ClassPlacement(
                    class_id=first_id,
                    days=first_time.days,
                    start=first_time.start,
                    weeks=first_time.weeks,
                    room_id=placements[first_id].room_id,
                )
                for second_index in valid_indices[second_id]:
                    second_time = time_domains[second_id][second_index]
                    second_placement = ITC2019ClassPlacement(
                        class_id=second_id,
                        days=second_time.days,
                        start=second_time.start,
                        weeks=second_time.weeks,
                        room_id=placements[second_id].room_id,
                    )
                    satisfied = _pair_distribution_satisfied(
                        base,
                        parameters,
                        first_placement,
                        first_time,
                        second_placement,
                        second_time,
                        travel,
                    )
                    if distribution.required:
                        if satisfied:
                            rows.append((first_index, second_index))
                    else:
                        rows.append(
                            (
                                first_index,
                                second_index,
                                0 if satisfied else distribution.penalty,
                            )
                        )
                if time.monotonic() >= deadline - 0.5:
                    return None
            if distribution.required:
                if not rows:
                    return None
                model.add_allowed_assignments(
                    (choice_variables[first_id], choice_variables[second_id]), rows
                )
            else:
                cost = model.new_int_var(
                    0,
                    distribution.penalty,
                    f"fixed_room_distribution_cost_{len(distribution_costs)}",
                )
                model.add_allowed_assignments(
                    (choice_variables[first_id], choice_variables[second_id], cost),
                    rows,
                )
                distribution_costs.append(cost)

    model.minimize(
        problem.optimization.time * sum(time_costs)
        + problem.optimization.distribution * sum(distribution_costs)
    )
    remaining = deadline - time.monotonic() - 0.25
    if remaining <= 0:
        return None
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = remaining
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = random_seed
    status = solver.solve(model)
    if status not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        return None
    candidate = {}
    for klass in problem.classes:
        class_id = klass.id
        option = time_domains[class_id][int(solver.value(choice_variables[class_id]))]
        candidate[class_id] = ITC2019ClassPlacement(
            class_id=class_id,
            days=option.days,
            start=option.start,
            weeks=option.weeks,
            room_id=placements[class_id].room_id,
        )
    if time.monotonic() >= deadline:
        return None
    errors = validate_itc2019_solution(problem, candidate, student_classes)
    if errors:
        return None
    before = score_itc2019_solution(problem, placements, student_classes)
    after = score_itc2019_solution(problem, candidate, student_classes)
    return candidate if after.total < before.total else None


def _improve_relaxed_times_and_rooms(
    problem: ITC2019Problem,
    placements,
    student_classes,
    *,
    time_domains,
    admitted_rooms_by_time,
    room_penalties,
    travel,
    deadline: float,
    workers: int,
    random_seed: int,
):
    """Solve a room-relaxed time master followed by an exact fixed-time room model."""

    started = time.monotonic()
    if deadline - started <= 4.0:
        return None
    time_deadline = started + (deadline - started) * 0.35
    time_model = cp_model.CpModel()
    time_choices = {}
    valid_indices = {}
    time_costs = []
    current_indices = {}
    for klass in problem.classes:
        class_id = klass.id
        indices = tuple(
            option_index
            for option_index in range(len(time_domains[class_id]))
            if admitted_rooms_by_time[(class_id, option_index)]
        )
        if not indices:
            return None
        valid_indices[class_id] = indices
        choice = time_model.new_int_var_from_domain(
            cp_model.Domain.from_values(indices), f"relaxed_time_{class_id}"
        )
        time_choices[class_id] = choice
        cost = time_model.new_int_var(
            0,
            max(option.penalty for option in time_domains[class_id]),
            f"relaxed_time_cost_{class_id}",
        )
        time_model.add_element(
            choice,
            [option.penalty for option in time_domains[class_id]],
            cost,
        )
        time_costs.append(cost)
        incumbent = placements[class_id]
        for option_index in indices:
            option = time_domains[class_id][option_index]
            if (
                option.days == incumbent.days
                and option.start == incumbent.start
                and option.weeks == incumbent.weeks
            ):
                current_indices[class_id] = option_index
                time_model.add_hint(choice, option_index)
                break
        if time.monotonic() >= time_deadline - 0.5:
            return None

    distribution_costs = []
    pair_bases = {
        "SameStart",
        "SameTime",
        "DifferentTime",
        "SameDays",
        "DifferentDays",
        "SameWeeks",
        "DifferentWeeks",
        "SameRoom",
        "DifferentRoom",
        "Overlap",
        "NotOverlap",
        "SameAttendees",
        "Precedence",
        "WorkDay",
        "MinGap",
    }
    hard_room_rules = []
    for distribution in problem.distributions:
        base, parameters = _distribution_spec(distribution.type)
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        if base not in pair_bases:
            continue
        for first_id, second_id in combinations(class_ids, 2):
            if distribution.required:
                hard_room_rules.append((first_id, second_id, base, parameters))
            if base in {"SameRoom", "DifferentRoom"}:
                continue
            rows = []
            for first_index in valid_indices[first_id]:
                first_time = time_domains[first_id][first_index]
                first_placement = ITC2019ClassPlacement(
                    class_id=first_id,
                    days=first_time.days,
                    start=first_time.start,
                    weeks=first_time.weeks,
                    room_id=None,
                )
                for second_index in valid_indices[second_id]:
                    second_time = time_domains[second_id][second_index]
                    second_placement = ITC2019ClassPlacement(
                        class_id=second_id,
                        days=second_time.days,
                        start=second_time.start,
                        weeks=second_time.weeks,
                        room_id=None,
                    )
                    satisfied = _pair_distribution_satisfied(
                        base,
                        parameters,
                        first_placement,
                        first_time,
                        second_placement,
                        second_time,
                        {},
                    )
                    if distribution.required:
                        if satisfied:
                            rows.append((first_index, second_index))
                    else:
                        rows.append(
                            (
                                first_index,
                                second_index,
                                0 if satisfied else distribution.penalty,
                            )
                        )
                if time.monotonic() >= time_deadline - 0.5:
                    return None
            if distribution.required:
                if not rows:
                    return None
                time_model.add_allowed_assignments(
                    (time_choices[first_id], time_choices[second_id]), rows
                )
            else:
                cost = time_model.new_int_var(
                    0,
                    distribution.penalty,
                    f"relaxed_distribution_cost_{len(distribution_costs)}",
                )
                time_model.add_allowed_assignments(
                    (time_choices[first_id], time_choices[second_id], cost), rows
                )
                distribution_costs.append(cost)

    time_model.minimize(
        problem.optimization.time * sum(time_costs)
        + problem.optimization.distribution * sum(distribution_costs)
    )
    incumbent_time_penalty = sum(
        time_domains[class_id][option_index].penalty
        for class_id, option_index in current_indices.items()
    )
    if incumbent_time_penalty <= 0:
        return None
    time_model.add(sum(time_costs) <= incumbent_time_penalty - 1)
    remaining = time_deadline - time.monotonic() - 0.25
    if remaining <= 0:
        return None
    time_solver = cp_model.CpSolver()
    time_solver.parameters.max_time_in_seconds = remaining
    time_solver.parameters.num_search_workers = workers
    time_solver.parameters.random_seed = random_seed
    time_status = time_solver.solve(time_model)
    if time_status not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        return None
    selected_indices = {
        class_id: int(time_solver.value(choice))
        for class_id, choice in time_choices.items()
    }
    selected_times = {
        class_id: time_domains[class_id][option_index]
        for class_id, option_index in selected_indices.items()
    }

    room_model = cp_model.CpModel()
    global_room_codes = {room.id: index for index, room in enumerate(problem.rooms)}
    room_variables = {}
    room_code_domains = {}
    room_by_code = {}
    room_costs = []
    for class_index, klass in enumerate(problem.classes):
        class_id = klass.id
        room_ids = admitted_rooms_by_time[(class_id, selected_indices[class_id])]
        codes = []
        for room_id in room_ids:
            if room_id is None:
                code = len(global_room_codes) + class_index
            else:
                code = global_room_codes[room_id]
            codes.append(code)
            room_by_code[(class_id, code)] = room_id
        if not codes:
            return None
        room_code_domains[class_id] = tuple(codes)
        if len(codes) == 1:
            variable = room_model.new_constant(codes[0])
        else:
            variable = room_model.new_int_var_from_domain(
                cp_model.Domain.from_values(codes), f"relaxed_room_{class_id}"
            )
        room_variables[class_id] = variable
        maximum_penalty = max(room_penalties[class_id].values(), default=0)
        cost = room_model.new_int_var(
            0, maximum_penalty, f"relaxed_room_cost_{class_id}"
        )
        room_model.add_allowed_assignments(
            (variable, cost),
            [
                (code, room_penalties[class_id].get(room_by_code[(class_id, code)], 0))
                for code in codes
            ],
        )
        room_costs.append(cost)
        incumbent_room = placements[class_id].room_id
        incumbent_code = (
            global_room_codes.get(incumbent_room)
            if incumbent_room is not None
            else len(global_room_codes) + class_index
        )
        if incumbent_code in codes:
            room_model.add_hint(variable, incumbent_code)
        if time.monotonic() >= deadline - 0.5:
            return None

    occurrence_classes = defaultdict(list)
    for class_id, option in selected_times.items():
        for occurrence in occurrences(option):
            occurrence_classes[occurrence].append(class_id)
    for class_ids in {
        tuple(sorted(class_ids))
        for class_ids in occurrence_classes.values()
        if len(class_ids) > 1
    }:
        room_model.add_all_different(
            [room_variables[class_id] for class_id in class_ids]
        )

    for first_id, second_id, base, parameters in hard_room_rules:
        first_time = selected_times[first_id]
        second_time = selected_times[second_id]
        forbidden = []
        for first_code in room_code_domains[first_id]:
            first_room = room_by_code[(first_id, first_code)]
            first_placement = ITC2019ClassPlacement(
                class_id=first_id,
                days=first_time.days,
                start=first_time.start,
                weeks=first_time.weeks,
                room_id=first_room,
            )
            for second_code in room_code_domains[second_id]:
                second_room = room_by_code[(second_id, second_code)]
                second_placement = ITC2019ClassPlacement(
                    class_id=second_id,
                    days=second_time.days,
                    start=second_time.start,
                    weeks=second_time.weeks,
                    room_id=second_room,
                )
                if not _pair_distribution_satisfied(
                    base,
                    parameters,
                    first_placement,
                    first_time,
                    second_placement,
                    second_time,
                    travel,
                ):
                    forbidden.append((first_code, second_code))
        if forbidden:
            room_model.add_forbidden_assignments(
                (room_variables[first_id], room_variables[second_id]), forbidden
            )
        if time.monotonic() >= deadline - 0.5:
            return None

    room_model.minimize(sum(room_costs))
    remaining = deadline - time.monotonic() - 0.25
    if remaining <= 0:
        return None
    room_solver = cp_model.CpSolver()
    room_solver.parameters.max_time_in_seconds = remaining
    room_solver.parameters.num_search_workers = workers
    room_solver.parameters.random_seed = random_seed
    room_status = room_solver.solve(room_model)
    if room_status not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        return None
    candidate = {}
    for klass in problem.classes:
        class_id = klass.id
        option = selected_times[class_id]
        code = int(room_solver.value(room_variables[class_id]))
        candidate[class_id] = ITC2019ClassPlacement(
            class_id=class_id,
            days=option.days,
            start=option.start,
            weeks=option.weeks,
            room_id=room_by_code[(class_id, code)],
        )
    if time.monotonic() >= deadline:
        return None
    if validate_itc2019_solution(problem, candidate, student_classes):
        return None
    before = score_itc2019_solution(problem, placements, student_classes)
    after = score_itc2019_solution(problem, candidate, student_classes)
    return candidate if after.total < before.total else None


def improve_itc2019_decomposed(
    problem: ITC2019Problem,
    placements,
    student_classes,
    *,
    deadline: float,
    workers: int = 4,
    random_seed: int = 17,
    diagnostics: dict | None = None,
):
    started = time.monotonic()
    completion_deadline = deadline - 3.0
    diagnostics = diagnostics if diagnostics is not None else {}
    placements = {placement.class_id: placement for placement in placements}
    student_classes = {
        student_id: tuple(class_ids)
        for student_id, class_ids in student_classes.items()
    }
    errors = validate_itc2019_solution(problem, placements, student_classes)
    if errors:
        raise ValueError(errors[:8])
    domains = _build_factorized_domains(problem, deadline=deadline)
    travel = _travel_values(problem)
    time_domains = domains.times
    room_domains = {}
    room_penalties = {}
    blocked_by_room = {}
    for room in problem.rooms:
        blocked = 0
        for unavailable in room.unavailable:
            for week, day, slot in occurrences(unavailable):
                bit = (week * problem.nr_days + day) * problem.slots_per_day + slot
                blocked |= 1 << bit
        blocked_by_room[room.id] = blocked
    time_mask_cache = {}
    admitted_rooms_by_time = {}
    roomless_classes = set()
    for klass in problem.classes:
        room_domains[klass.id] = tuple(
            option for option in domains.rooms[klass.id] if option is not None
        )
        room_penalties[klass.id] = {
            option.room_id: option.penalty for option in room_domains[klass.id]
        }
        if not room_domains[klass.id]:
            roomless_classes.add(klass.id)
        allowed_rooms = tuple(sorted(room_penalties[klass.id]))
        for option_index, time_option in enumerate(time_domains[klass.id]):
            signature = (
                time_option.days,
                time_option.start,
                time_option.length,
                time_option.weeks,
            )
            time_mask = time_mask_cache.get(signature)
            if time_mask is None:
                time_mask = 0
                for week, day, slot in occurrences(time_option):
                    bit = (week * problem.nr_days + day) * problem.slots_per_day + slot
                    time_mask |= 1 << bit
                time_mask_cache[signature] = time_mask
            admitted_rooms_by_time[(klass.id, option_index)] = tuple(
                room_id
                for room_id in allowed_rooms
                if not blocked_by_room[room_id] & time_mask
            ) or ((None,) if klass.id in roomless_classes else ())

    current_times = {}
    current_indices = {}
    for klass in problem.classes:
        placement = placements[klass.id]
        for option_index, option in enumerate(time_domains[klass.id]):
            if (
                option.days == placement.days
                and option.start == placement.start
                and option.weeks == placement.weeks
            ):
                current_times[klass.id] = option
                current_indices[klass.id] = option_index
                break
        else:
            raise ValueError(f"time domain mismatch {klass.id}")

    hard_pairs = defaultdict(list)
    soft_pairs = defaultdict(list)
    hard_groups = defaultdict(list)
    soft_groups = defaultdict(list)
    hard_rule_edges = []
    for distribution in problem.distributions:
        base, parameters = _distribution_spec(distribution.type)
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        if base not in _PAIR_DISTRIBUTIONS:
            entry = (base, parameters, class_ids, distribution.penalty)
            destination = hard_groups if distribution.required else soft_groups
            for class_id in class_ids:
                destination[class_id].append(entry)
            continue
        for first_id, second_id in combinations(class_ids, 2):
            if distribution.required:
                hard_pairs[first_id].append(
                    (second_id, base, parameters, distribution.penalty, True)
                )
                hard_pairs[second_id].append(
                    (first_id, base, parameters, distribution.penalty, False)
                )
                hard_rule_edges.append((first_id, second_id, base, parameters))
            else:
                soft_pairs[first_id].append(
                    (second_id, base, parameters, distribution.penalty, True)
                )
                soft_pairs[second_id].append(
                    (first_id, base, parameters, distribution.penalty, False)
                )

    student_pair_weights = defaultdict(int)
    student_neighbors = defaultdict(list)
    for class_ids in student_classes.values():
        for first_id, second_id in combinations(sorted(set(class_ids)), 2):
            student_pair_weights[(first_id, second_id)] += 1
    for (first_id, second_id), weight in student_pair_weights.items():
        student_neighbors[first_id].append((second_id, weight))
        student_neighbors[second_id].append((first_id, weight))

    room_members = defaultdict(set)
    for class_id, placement in placements.items():
        room_members[placement.room_id].add(class_id)

    def pair_ok(class_id, placement, time_option, entry):
        other_id, base, parameters, _penalty, current_is_first = entry
        if current_is_first:
            return _pair_distribution_satisfied(
                base,
                parameters,
                placement,
                time_option,
                placements[other_id],
                current_times[other_id],
                travel,
            )
        return _pair_distribution_satisfied(
            base,
            parameters,
            placements[other_id],
            current_times[other_id],
            placement,
            time_option,
            travel,
        )

    def group_units(class_id, time_option, entry):
        base, parameters, class_ids, _penalty = entry
        resolved = {
            member_id: time_option
            if member_id == class_id
            else current_times[member_id]
            for member_id in class_ids
        }
        return _special_distribution_units(
            problem,
            base,
            parameters,
            class_ids,
            resolved,
        )

    def group_penalty(class_id, time_option, entry):
        base, _parameters, _class_ids, penalty = entry
        units = group_units(class_id, time_option, entry)
        if base in {"MaxDayLoad", "MaxBreaks", "MaxBlock"}:
            return penalty * units // problem.nr_weeks
        return penalty * units

    def hard_groups_ok(*class_ids):
        entries = {entry for class_id in class_ids for entry in hard_groups[class_id]}
        return all(
            _special_distribution_units(
                problem,
                entry[0],
                entry[1],
                entry[2],
                current_times,
            )
            == 0
            for entry in entries
        )

    def local_cost(class_id, placement, time_option):
        room_cost = (
            room_penalties[class_id].get(placement.room_id, 0)
            if placement.room_id is not None
            else 0
        )
        distribution_cost = sum(
            entry[3]
            for entry in soft_pairs[class_id]
            if not pair_ok(class_id, placement, time_option, entry)
        )
        distribution_cost += sum(
            group_penalty(class_id, time_option, entry)
            for entry in soft_groups[class_id]
        )
        student_cost = sum(
            weight
            for other_id, weight in student_neighbors[class_id]
            if _student_pair_conflicts(
                problem,
                placement,
                time_option,
                placements[other_id],
                current_times[other_id],
                travel,
            )
        )
        return (
            problem.optimization.time * time_option.penalty
            + problem.optimization.room * room_cost
            + problem.optimization.distribution * distribution_cost
            + problem.optimization.student * student_cost
        )

    current_score = score_itc2019_solution(problem, placements, student_classes)
    diagnostics["initial_score"] = current_score.total
    remaining = completion_deadline - time.monotonic()
    if not student_classes and remaining > 8.0:
        room_slice = min(30.0, remaining * 0.55, remaining - 6.0)
        room_deadline = time.monotonic() + room_slice
        room_candidate, room_telemetry = _improve_fixed_time_rooms(
            problem,
            placements,
            student_classes,
            current_times=current_times,
            current_indices=current_indices,
            admitted_rooms_by_time=admitted_rooms_by_time,
            room_penalties=room_penalties,
            travel=travel,
            hard_rule_edges=hard_rule_edges,
            deadline=room_deadline,
            workers=workers,
            random_seed=random_seed,
        )
        if room_telemetry is not None:
            diagnostics["early_room_optimization"] = room_telemetry
        if room_candidate is not None:
            placements = room_candidate
            room_members = defaultdict(set)
            for class_id, placement in placements.items():
                room_members[placement.room_id].add(class_id)
            current_score = score_itc2019_solution(problem, placements, student_classes)
            diagnostics["post_early_room_score"] = current_score.total
    best_score = current_score
    best_placements = tuple(placements[class_id] for class_id in sorted(placements))
    move_count = 0
    for sweep in range(20):
        accepted = 0
        ordered_classes = sorted(
            problem.classes,
            key=lambda klass: (
                -local_cost(klass.id, placements[klass.id], current_times[klass.id]),
                klass.id,
            ),
        )
        for klass in ordered_classes:
            class_id = klass.id
            current_placement = placements[class_id]
            current_time = current_times[class_id]
            before = local_cost(class_id, current_placement, current_time)
            best = None
            for option_index, option in enumerate(time_domains[class_id]):
                admitted_rooms = admitted_rooms_by_time[(class_id, option_index)]
                for room_id in admitted_rooms:
                    diagnostics["single_candidates"] = (
                        diagnostics.get("single_candidates", 0) + 1
                    )
                    if (
                        option_index == current_indices[class_id]
                        and room_id == current_placement.room_id
                    ):
                        continue
                    candidate = ITC2019ClassPlacement(
                        class_id=class_id,
                        days=option.days,
                        start=option.start,
                        weeks=option.weeks,
                        room_id=room_id,
                    )
                    if any(
                        not pair_ok(class_id, candidate, option, entry)
                        for entry in hard_pairs[class_id]
                    ):
                        diagnostics["single_hard_rejections"] = (
                            diagnostics.get("single_hard_rejections", 0) + 1
                        )
                        continue
                    if any(
                        group_units(class_id, option, entry) > 0
                        for entry in hard_groups[class_id]
                    ):
                        diagnostics["single_group_rejections"] = (
                            diagnostics.get("single_group_rejections", 0) + 1
                        )
                        continue
                    if room_id is not None and any(
                        _pair_distribution_satisfied(
                            "NotOverlap",
                            (),
                            candidate,
                            option,
                            placements[other_id],
                            current_times[other_id],
                            travel,
                        )
                        is False
                        for other_id in room_members[room_id]
                        if other_id != class_id
                    ):
                        diagnostics["single_room_rejections"] = (
                            diagnostics.get("single_room_rejections", 0) + 1
                        )
                        continue
                    delta = local_cost(class_id, candidate, option) - before
                    if delta >= 0:
                        continue
                    diagnostics["single_improving_candidates"] = (
                        diagnostics.get("single_improving_candidates", 0) + 1
                    )
                    key = (delta, option_index, str(room_id))
                    if best is None or key < best[0]:
                        best = (key, option_index, option, room_id, candidate)
            if time.monotonic() >= completion_deadline:
                break
            if best is None:
                continue
            _key, option_index, option, room_id, candidate = best
            old_room = placements[class_id].room_id
            room_members[old_room].remove(class_id)
            placements[class_id] = candidate
            current_times[class_id] = option
            current_indices[class_id] = option_index
            room_members[room_id].add(class_id)
            accepted += 1
            move_count += 1
        diagnostics["single_sweeps"] = sweep + 1
        diagnostics["single_moves"] = move_count
        current_score = score_itc2019_solution(problem, placements, student_classes)
        diagnostics["post_single_score"] = current_score.total
        if current_score.total < best_score.total:
            checkpoint = tuple(placements[class_id] for class_id in sorted(placements))
            if not validate_itc2019_solution(problem, checkpoint, student_classes):
                best_score = current_score
                best_placements = checkpoint
        if accepted == 0:
            break
        if time.monotonic() >= completion_deadline:
            break

    for _ejection_pass in range(8):
        if time.monotonic() >= completion_deadline:
            break
        best_ejection = None
        roots = sorted(
            placements,
            key=lambda class_id: (
                -current_times[class_id].penalty,
                class_id,
            ),
        )
        for root_id in roots:
            root = placements[root_id]
            root_time = current_times[root_id]
            root_options = sorted(
                (
                    (option.penalty, option_index, option)
                    for option_index, option in enumerate(time_domains[root_id])
                    if option.penalty < root_time.penalty
                ),
                key=lambda item: (item[0], item[1]),
            )[:16]
            for _penalty, root_index, root_option in root_options:
                root_rooms = sorted(
                    admitted_rooms_by_time[(root_id, root_index)],
                    key=lambda room_id: (
                        room_penalties[root_id].get(room_id, 0),
                        str(room_id),
                    ),
                )[:6]
                for root_room in root_rooms:
                    root_candidate = ITC2019ClassPlacement(
                        class_id=root_id,
                        days=root_option.days,
                        start=root_option.start,
                        weeks=root_option.weeks,
                        room_id=root_room,
                    )
                    conflicts = {
                        other_id
                        for other_id in room_members[root_room]
                        if other_id != root_id
                        and not _pair_distribution_satisfied(
                            "NotOverlap",
                            (),
                            root_candidate,
                            root_option,
                            placements[other_id],
                            current_times[other_id],
                            travel,
                        )
                    }
                    conflicts.update(
                        entry[0]
                        for entry in hard_pairs[root_id]
                        if not pair_ok(root_id, root_candidate, root_option, entry)
                    )
                    if len(conflicts) != 1:
                        continue
                    blocker_id = next(iter(conflicts))
                    blocker = placements[blocker_id]
                    blocker_time = current_times[blocker_id]
                    blocker_options = sorted(
                        enumerate(time_domains[blocker_id]),
                        key=lambda item: (item[1].penalty, item[0]),
                    )[:16]
                    for blocker_index, blocker_option in blocker_options:
                        blocker_rooms = sorted(
                            admitted_rooms_by_time[(blocker_id, blocker_index)],
                            key=lambda room_id: (
                                room_penalties[blocker_id].get(room_id, 0),
                                str(room_id),
                            ),
                        )[:6]
                        for blocker_room in blocker_rooms:
                            direct_before = problem.optimization.time * (
                                root_time.penalty + blocker_time.penalty
                            ) + problem.optimization.room * (
                                room_penalties[root_id].get(root.room_id, 0)
                                + room_penalties[blocker_id].get(blocker.room_id, 0)
                            )
                            direct_after = problem.optimization.time * (
                                root_option.penalty + blocker_option.penalty
                            ) + problem.optimization.room * (
                                room_penalties[root_id].get(root_room, 0)
                                + room_penalties[blocker_id].get(blocker_room, 0)
                            )
                            if direct_after >= direct_before:
                                continue
                            blocker_candidate = ITC2019ClassPlacement(
                                class_id=blocker_id,
                                days=blocker_option.days,
                                start=blocker_option.start,
                                weeks=blocker_option.weeks,
                                room_id=blocker_room,
                            )
                            if blocker_room is not None and any(
                                not _pair_distribution_satisfied(
                                    "NotOverlap",
                                    (),
                                    blocker_candidate,
                                    blocker_option,
                                    placements[other_id],
                                    current_times[other_id],
                                    travel,
                                )
                                for other_id in room_members[blocker_room]
                                if other_id not in {root_id, blocker_id}
                            ):
                                continue
                            if (
                                root_room == blocker_room
                                and not _pair_distribution_satisfied(
                                    "NotOverlap",
                                    (),
                                    root_candidate,
                                    root_option,
                                    blocker_candidate,
                                    blocker_option,
                                    travel,
                                )
                            ):
                                continue
                            placements[root_id] = root_candidate
                            placements[blocker_id] = blocker_candidate
                            current_times[root_id] = root_option
                            current_times[blocker_id] = blocker_option
                            hard_valid = (
                                not any(
                                    not pair_ok(
                                        root_id, root_candidate, root_option, entry
                                    )
                                    for entry in hard_pairs[root_id]
                                )
                                and not any(
                                    not pair_ok(
                                        blocker_id,
                                        blocker_candidate,
                                        blocker_option,
                                        entry,
                                    )
                                    for entry in hard_pairs[blocker_id]
                                )
                                and hard_groups_ok(root_id, blocker_id)
                            )
                            if hard_valid:
                                candidate_score = score_itc2019_solution(
                                    problem, placements, student_classes
                                )
                                key = (
                                    candidate_score.total,
                                    root_id,
                                    blocker_id,
                                    root_index,
                                    blocker_index,
                                    str(root_room),
                                    str(blocker_room),
                                )
                                if candidate_score.total < current_score.total and (
                                    best_ejection is None or key < best_ejection[0]
                                ):
                                    best_ejection = (
                                        key,
                                        root_id,
                                        blocker_id,
                                        root,
                                        blocker,
                                        root_candidate,
                                        blocker_candidate,
                                        root_option,
                                        blocker_option,
                                        root_index,
                                        blocker_index,
                                        candidate_score,
                                    )
                            placements[root_id] = root
                            placements[blocker_id] = blocker
                            current_times[root_id] = root_time
                            current_times[blocker_id] = blocker_time
                        if time.monotonic() >= completion_deadline:
                            break
                    if time.monotonic() >= completion_deadline:
                        break
                if time.monotonic() >= completion_deadline:
                    break
            if time.monotonic() >= completion_deadline:
                break
        if best_ejection is None or time.monotonic() >= completion_deadline:
            break
        (
            _key,
            root_id,
            blocker_id,
            root,
            blocker,
            root_candidate,
            blocker_candidate,
            root_option,
            blocker_option,
            root_index,
            blocker_index,
            current_score,
        ) = best_ejection
        room_members[root.room_id].remove(root_id)
        room_members[blocker.room_id].remove(blocker_id)
        placements[root_id] = root_candidate
        placements[blocker_id] = blocker_candidate
        current_times[root_id] = root_option
        current_times[blocker_id] = blocker_option
        current_indices[root_id] = root_index
        current_indices[blocker_id] = blocker_index
        room_members[root_candidate.room_id].add(root_id)
        room_members[blocker_candidate.room_id].add(blocker_id)

    class_ids = tuple(sorted(placements))
    for _swap_pass in range(8):
        if time.monotonic() >= completion_deadline:
            break
        best_swap = None
        for first_offset, first_id in enumerate(class_ids):
            first = placements[first_id]
            first_room = first.room_id
            if first_room is None:
                continue
            first_time = current_times[first_id]
            for second_id in class_ids[first_offset + 1 :]:
                second = placements[second_id]
                second_room = second.room_id
                if second_room is None or second_room == first_room:
                    continue
                second_time = current_times[second_id]
                if (
                    second_room
                    not in admitted_rooms_by_time[(first_id, current_indices[first_id])]
                    or first_room
                    not in admitted_rooms_by_time[
                        (second_id, current_indices[second_id])
                    ]
                ):
                    continue
                room_delta = problem.optimization.room * (
                    room_penalties[first_id][second_room]
                    + room_penalties[second_id][first_room]
                    - room_penalties[first_id][first_room]
                    - room_penalties[second_id][second_room]
                )
                if room_delta >= 0:
                    continue
                first_candidate = ITC2019ClassPlacement(
                    class_id=first_id,
                    days=first.days,
                    start=first.start,
                    weeks=first.weeks,
                    room_id=second_room,
                )
                second_candidate = ITC2019ClassPlacement(
                    class_id=second_id,
                    days=second.days,
                    start=second.start,
                    weeks=second.weeks,
                    room_id=first_room,
                )
                if any(
                    not _pair_distribution_satisfied(
                        "NotOverlap",
                        (),
                        first_candidate,
                        first_time,
                        placements[other_id],
                        current_times[other_id],
                        travel,
                    )
                    for other_id in room_members[second_room]
                    if other_id != second_id
                ) or any(
                    not _pair_distribution_satisfied(
                        "NotOverlap",
                        (),
                        second_candidate,
                        second_time,
                        placements[other_id],
                        current_times[other_id],
                        travel,
                    )
                    for other_id in room_members[first_room]
                    if other_id != first_id
                ):
                    continue
                placements[first_id] = first_candidate
                placements[second_id] = second_candidate
                hard_valid = (
                    not any(
                        not pair_ok(first_id, first_candidate, first_time, entry)
                        for entry in hard_pairs[first_id]
                    )
                    and not any(
                        not pair_ok(second_id, second_candidate, second_time, entry)
                        for entry in hard_pairs[second_id]
                    )
                    and hard_groups_ok(first_id, second_id)
                )
                if hard_valid:
                    candidate_score = score_itc2019_solution(
                        problem, placements, student_classes
                    )
                    key = (candidate_score.total, first_id, second_id)
                    if candidate_score.total < current_score.total and (
                        best_swap is None or key < best_swap[0]
                    ):
                        best_swap = (
                            key,
                            first_id,
                            second_id,
                            first,
                            second,
                            first_candidate,
                            second_candidate,
                            candidate_score,
                        )
                placements[first_id] = first
                placements[second_id] = second
            if time.monotonic() >= completion_deadline:
                break
        if best_swap is None or time.monotonic() >= completion_deadline:
            break
        (
            _key,
            first_id,
            second_id,
            first,
            second,
            first_candidate,
            second_candidate,
            current_score,
        ) = best_swap
        room_members[first.room_id].remove(first_id)
        room_members[second.room_id].remove(second_id)
        placements[first_id] = first_candidate
        placements[second_id] = second_candidate
        room_members[first_candidate.room_id].add(first_id)
        room_members[second_candidate.room_id].add(second_id)

    time_index_by_signature = {
        klass.id: {
            (option.days, option.start, option.weeks): option_index
            for option_index, option in enumerate(time_domains[klass.id])
        }
        for klass in problem.classes
    }
    for _exchange_pass in range(8):
        if time.monotonic() >= completion_deadline:
            break
        best_exchange = None
        ordered_ids = tuple(
            sorted(
                class_ids,
                key=lambda class_id: (
                    -time_domains[class_id][current_indices[class_id]].penalty,
                    class_id,
                ),
            )
        )
        for first_offset, first_id in enumerate(ordered_ids):
            first = placements[first_id]
            for second_id in ordered_ids[first_offset + 1 :]:
                second = placements[second_id]
                first_index = time_index_by_signature[first_id].get(
                    (second.days, second.start, second.weeks)
                )
                second_index = time_index_by_signature[second_id].get(
                    (first.days, first.start, first.weeks)
                )
                if first_index is None or second_index is None:
                    continue
                first_time = time_domains[first_id][first_index]
                second_time = time_domains[second_id][second_index]
                first_rooms = tuple(
                    room_id
                    for room_id in (first.room_id, second.room_id)
                    if room_id in admitted_rooms_by_time[(first_id, first_index)]
                )
                second_rooms = tuple(
                    room_id
                    for room_id in (second.room_id, first.room_id)
                    if room_id in admitted_rooms_by_time[(second_id, second_index)]
                )
                for first_room in dict.fromkeys(first_rooms):
                    for second_room in dict.fromkeys(second_rooms):
                        direct_delta = problem.optimization.time * (
                            first_time.penalty
                            + second_time.penalty
                            - current_times[first_id].penalty
                            - current_times[second_id].penalty
                        ) + problem.optimization.room * (
                            room_penalties[first_id].get(first_room, 0)
                            + room_penalties[second_id].get(second_room, 0)
                            - room_penalties[first_id].get(first.room_id, 0)
                            - room_penalties[second_id].get(second.room_id, 0)
                        )
                        if direct_delta >= 0:
                            continue
                        first_candidate = ITC2019ClassPlacement(
                            class_id=first_id,
                            days=first_time.days,
                            start=first_time.start,
                            weeks=first_time.weeks,
                            room_id=first_room,
                        )
                        second_candidate = ITC2019ClassPlacement(
                            class_id=second_id,
                            days=second_time.days,
                            start=second_time.start,
                            weeks=second_time.weeks,
                            room_id=second_room,
                        )
                        if first_room is not None and any(
                            not _pair_distribution_satisfied(
                                "NotOverlap",
                                (),
                                first_candidate,
                                first_time,
                                placements[other_id],
                                current_times[other_id],
                                travel,
                            )
                            for other_id in room_members[first_room]
                            if other_id not in {first_id, second_id}
                        ):
                            continue
                        if second_room is not None and any(
                            not _pair_distribution_satisfied(
                                "NotOverlap",
                                (),
                                second_candidate,
                                second_time,
                                placements[other_id],
                                current_times[other_id],
                                travel,
                            )
                            for other_id in room_members[second_room]
                            if other_id not in {first_id, second_id}
                        ):
                            continue
                        if (
                            first_room == second_room
                            and not _pair_distribution_satisfied(
                                "NotOverlap",
                                (),
                                first_candidate,
                                first_time,
                                second_candidate,
                                second_time,
                                travel,
                            )
                        ):
                            continue
                        placements[first_id] = first_candidate
                        placements[second_id] = second_candidate
                        old_first_time = current_times[first_id]
                        old_second_time = current_times[second_id]
                        current_times[first_id] = first_time
                        current_times[second_id] = second_time
                        hard_valid = (
                            not any(
                                not pair_ok(
                                    first_id, first_candidate, first_time, entry
                                )
                                for entry in hard_pairs[first_id]
                            )
                            and not any(
                                not pair_ok(
                                    second_id, second_candidate, second_time, entry
                                )
                                for entry in hard_pairs[second_id]
                            )
                            and hard_groups_ok(first_id, second_id)
                        )
                        if hard_valid:
                            candidate_score = score_itc2019_solution(
                                problem, placements, student_classes
                            )
                            key = (candidate_score.total, first_id, second_id)
                            if candidate_score.total < current_score.total and (
                                best_exchange is None or key < best_exchange[0]
                            ):
                                best_exchange = (
                                    key,
                                    first_id,
                                    second_id,
                                    first,
                                    second,
                                    first_candidate,
                                    second_candidate,
                                    first_time,
                                    second_time,
                                    first_index,
                                    second_index,
                                    candidate_score,
                                )
                        placements[first_id] = first
                        placements[second_id] = second
                        current_times[first_id] = old_first_time
                        current_times[second_id] = old_second_time
                if time.monotonic() >= completion_deadline:
                    break
            if time.monotonic() >= completion_deadline:
                break
        if best_exchange is None or time.monotonic() >= completion_deadline:
            break
        (
            _key,
            first_id,
            second_id,
            first,
            second,
            first_candidate,
            second_candidate,
            first_time,
            second_time,
            first_index,
            second_index,
            current_score,
        ) = best_exchange
        room_members[first.room_id].remove(first_id)
        room_members[second.room_id].remove(second_id)
        placements[first_id] = first_candidate
        placements[second_id] = second_candidate
        current_times[first_id] = first_time
        current_times[second_id] = second_time
        current_indices[first_id] = first_index
        current_indices[second_id] = second_index
        room_members[first_candidate.room_id].add(first_id)
        room_members[second_candidate.room_id].add(second_id)

    remaining = deadline - time.monotonic()
    relaxed_pair_cells = sum(
        len(time_domains[first_id]) * len(time_domains[second_id])
        for distribution in problem.distributions
        for first_id, second_id in combinations(
            tuple(dict.fromkeys(distribution.class_ids)), 2
        )
    )
    diagnostics["relaxed_pair_cells"] = relaxed_pair_cells
    if remaining > 12.0 and relaxed_pair_cells <= 1_000_000:
        time_candidate = _improve_relaxed_times_and_rooms(
            problem,
            placements,
            student_classes,
            time_domains=time_domains,
            admitted_rooms_by_time=admitted_rooms_by_time,
            room_penalties=room_penalties,
            travel=travel,
            deadline=completion_deadline,
            workers=workers,
            random_seed=random_seed,
        )
        if time_candidate is not None:
            placements = time_candidate
            for klass in problem.classes:
                class_id = klass.id
                placement = placements[class_id]
                for option_index, option in enumerate(time_domains[class_id]):
                    if (
                        option.days == placement.days
                        and option.start == placement.start
                        and option.weeks == placement.weeks
                    ):
                        current_times[class_id] = option
                        current_indices[class_id] = option_index
                        break
            room_members = defaultdict(set)
            for class_id, placement in placements.items():
                room_members[placement.room_id].add(class_id)
            current_score = score_itc2019_solution(problem, placements, student_classes)
    elif relaxed_pair_cells > 1_000_000:
        diagnostics["relaxed_stage_skipped"] = "pair_matrix_scale_guard"

    remaining = completion_deadline - time.monotonic()
    if remaining > 1.0:
        room_model = cp_model.CpModel()
        room_codes = {room.id: index for index, room in enumerate(problem.rooms)}
        room_variables = {}
        room_code_domains = {}
        room_by_code = {}
        room_cost_variables = []
        for class_index, klass in enumerate(problem.classes):
            if class_index % 16 == 0 and time.monotonic() >= completion_deadline:
                diagnostics["final_room_stage_expired"] = "class_model_build"
                return best_placements
            class_id = klass.id
            room_ids = admitted_rooms_by_time[(class_id, current_indices[class_id])]
            if room_ids == (None,):
                code = len(room_codes) + class_index
                room_variables[class_id] = room_model.new_constant(code)
                room_code_domains[class_id] = (code,)
                room_by_code[(class_id, code)] = None
                continue
            codes = [room_codes[room_id] for room_id in room_ids]
            room_code_domains[class_id] = tuple(codes)
            room_by_code.update(
                ((class_id, room_codes[room_id]), room_id) for room_id in room_ids
            )
            variable = room_model.new_int_var_from_domain(
                cp_model.Domain.from_values(codes), f"room_{class_id}"
            )
            room_variables[class_id] = variable
            cost = room_model.new_int_var(
                0,
                max(room_penalties[class_id].values(), default=0),
                f"room_cost_{class_id}",
            )
            penalty_vector = [
                room_penalties[class_id].get(room.id, 0) for room in problem.rooms
            ]
            room_model.add_element(variable, penalty_vector, cost)
            room_cost_variables.append(cost)
            current_room = placements[class_id].room_id
            if current_room is not None:
                room_model.add_hint(variable, room_codes[current_room])

        occurrence_classes = defaultdict(list)
        for class_id, option in current_times.items():
            for occurrence in occurrences(option):
                occurrence_classes[occurrence].append(class_id)
        unique_cliques = {
            tuple(sorted(class_ids))
            for class_ids in occurrence_classes.values()
            if len(class_ids) > 1
        }
        for clique_index, class_ids in enumerate(unique_cliques):
            if clique_index % 64 == 0 and time.monotonic() >= completion_deadline:
                diagnostics["final_room_stage_expired"] = "occupancy_model_build"
                return best_placements
            room_model.add_all_different(
                [room_variables[class_id] for class_id in class_ids]
            )

        for edge_index, (first_id, second_id, base, parameters) in enumerate(
            hard_rule_edges
        ):
            if edge_index % 16 == 0 and time.monotonic() >= completion_deadline:
                diagnostics["final_room_stage_expired"] = "rule_model_build"
                return best_placements
            first_time = current_times[first_id]
            second_time = current_times[second_id]
            forbidden = []
            for first_code in room_code_domains[first_id]:
                first_room = room_by_code[(first_id, first_code)]
                first_candidate = ITC2019ClassPlacement(
                    class_id=first_id,
                    days=first_time.days,
                    start=first_time.start,
                    weeks=first_time.weeks,
                    room_id=first_room,
                )
                for second_code in room_code_domains[second_id]:
                    second_room = room_by_code[(second_id, second_code)]
                    second_candidate = ITC2019ClassPlacement(
                        class_id=second_id,
                        days=second_time.days,
                        start=second_time.start,
                        weeks=second_time.weeks,
                        room_id=second_room,
                    )
                    if not _pair_distribution_satisfied(
                        base,
                        parameters,
                        first_candidate,
                        first_time,
                        second_candidate,
                        second_time,
                        travel,
                    ):
                        forbidden.append((first_code, second_code))
            if forbidden:
                room_model.add_forbidden_assignments(
                    (room_variables[first_id], room_variables[second_id]), forbidden
                )
        room_model.minimize(sum(room_cost_variables))
        solver_budget = completion_deadline - time.monotonic()
        if solver_budget <= 0:
            diagnostics["final_room_stage_expired"] = "before_solve"
            return best_placements
        room_solver = cp_model.CpSolver()
        room_solver.parameters.max_time_in_seconds = max(0.01, solver_budget)
        room_solver.parameters.num_search_workers = workers
        room_solver.parameters.random_seed = random_seed
        room_status = room_solver.solve(room_model)
        if time.monotonic() >= completion_deadline:
            diagnostics["final_room_stage_expired"] = "after_solve"
            return best_placements
        if room_status in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
            for klass in problem.classes:
                class_id = klass.id
                code = int(room_solver.value(room_variables[class_id]))
                room_id = room_by_code[(class_id, code)]
                old = placements[class_id]
                placements[class_id] = ITC2019ClassPlacement(
                    class_id=class_id,
                    days=old.days,
                    start=old.start,
                    weeks=old.weeks,
                    room_id=room_id,
                )

    errors = validate_itc2019_solution(problem, placements, student_classes)
    if errors:
        diagnostics["final_validation_errors"] = len(errors)
        return best_placements
    candidate = tuple(placements[class_id] for class_id in sorted(placements))
    candidate_score = score_itc2019_solution(problem, candidate, student_classes)
    if candidate_score.total < best_score.total:
        best_score = candidate_score
        best_placements = candidate
    if time.monotonic() > deadline:
        diagnostics["deadline_exhausted"] = True
    diagnostics["final_score"] = best_score.total
    return best_placements
