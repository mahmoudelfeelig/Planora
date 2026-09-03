"""Checkpoint-safe recurrence quality for global ITC-2019 incumbents.

The global feasibility constructor assigns recurring meetings independently.  This
phase repairs that deliberate completion-first choice by alternating exact time and
room neighborhoods over soft recurrence groups.  Every accepted neighborhood is a
strictly better, whole-problem-valid checkpoint; an interruption therefore returns
the last valid incumbent rather than an unverified partial schedule.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
import time
from typing import Mapping, Sequence

from ortools.sat.python import cp_model

from benchmarks.itc2019 import (
    ITC2019ClassPlacement,
    ITC2019Problem,
    ITC2019TimeOption,
    _PAIR_DISTRIBUTIONS,
    _distribution_spec,
    _pair_distribution_satisfied,
    _travel_values,
    evaluate_itc2019_distributions,
    score_itc2019_solution,
    validate_itc2019_solution,
)
from benchmarks.itc2019_factorized import _build_factorized_domains


_RECURRENCE_RULES = frozenset({"SameDays", "SameTime", "SameRoom"})
_PairRule = tuple[str, str, str, tuple[int, ...], bool, int]


def _overlaps(first, first_time, second, second_time, travel) -> bool:
    return not _pair_distribution_satisfied(
        "NotOverlap",
        (),
        first,
        first_time,
        second,
        second_time,
        travel,
    )


def _rule_satisfied(
    rule: _PairRule,
    first_placement,
    first_time,
    second_placement,
    second_time,
    travel,
) -> bool:
    return _pair_distribution_satisfied(
        rule[2],
        rule[3],
        first_placement,
        first_time,
        second_placement,
        second_time,
        travel,
    )


def _candidate_against_outside(
    problem,
    class_id,
    placement,
    time_option,
    *,
    inside,
    placements,
    current_times,
    rules,
    travel,
    deadline,
):
    soft_cost = 0
    for other_id, other_placement in placements.items():
        if time.monotonic() >= deadline - 0.75:
            raise TimeoutError("deadline while filtering recurrence candidates")
        if other_id in inside:
            continue
        other_time = current_times[other_id]
        if (
            placement.room_id is not None
            and placement.room_id == other_placement.room_id
            and _overlaps(
                placement,
                time_option,
                other_placement,
                other_time,
                travel,
            )
        ):
            return None
        for rule in rules.get(tuple(sorted((class_id, other_id))), ()):
            if rule[0] == class_id:
                satisfied = _rule_satisfied(
                    rule,
                    placement,
                    time_option,
                    other_placement,
                    other_time,
                    travel,
                )
            else:
                satisfied = _rule_satisfied(
                    rule,
                    other_placement,
                    other_time,
                    placement,
                    time_option,
                    travel,
                )
            if rule[4] and not satisfied:
                return None
            if not rule[4] and not satisfied:
                soft_cost += rule[5] * problem.optimization.distribution
    return soft_cost


def _pair_rows(
    problem,
    first_id,
    second_id,
    first_candidates,
    second_candidates,
    *,
    first_time_at,
    second_time_at,
    rules,
    travel,
    deadline,
):
    rows = []
    maximum_cost = 0
    pair_rules = rules.get(tuple(sorted((first_id, second_id))), ())
    for first_index, first_placement in enumerate(first_candidates):
        if time.monotonic() >= deadline - 0.75:
            raise TimeoutError("deadline while encoding recurrence pair")
        first_time = first_time_at(first_index)
        for second_index, second_placement in enumerate(second_candidates):
            second_time = second_time_at(second_index)
            if (
                first_placement.room_id is not None
                and first_placement.room_id == second_placement.room_id
                and _overlaps(
                    first_placement,
                    first_time,
                    second_placement,
                    second_time,
                    travel,
                )
            ):
                continue
            cost = 0
            allowed = True
            for rule in pair_rules:
                if rule[0] == first_id:
                    satisfied = _rule_satisfied(
                        rule,
                        first_placement,
                        first_time,
                        second_placement,
                        second_time,
                        travel,
                    )
                else:
                    satisfied = _rule_satisfied(
                        rule,
                        second_placement,
                        second_time,
                        first_placement,
                        first_time,
                        travel,
                    )
                if rule[4] and not satisfied:
                    allowed = False
                    break
                if not rule[4] and not satisfied:
                    cost += rule[5] * problem.optimization.distribution
            if allowed:
                rows.append((first_index, second_index, cost))
                maximum_cost = max(maximum_cost, cost)
    return rows, maximum_cost


def _solve_time_group(
    problem,
    group,
    *,
    placements,
    current_times,
    current_indices,
    time_domains,
    admitted_rooms,
    rules,
    travel,
    deadline,
    workers,
    random_seed,
    maximum_pair_cells,
):
    inside = set(group)
    candidates = {}
    candidate_domain_indices = {}
    unary_costs = {}
    projected_pair_cells = 0
    for class_id in group:
        room_id = placements[class_id].room_id
        class_candidates = []
        domain_indices = []
        costs = []
        for option_index, option in enumerate(time_domains[class_id]):
            if room_id not in admitted_rooms[(class_id, option_index)]:
                continue
            placement = ITC2019ClassPlacement(
                class_id,
                option.days,
                option.start,
                option.weeks,
                room_id,
            )
            try:
                outside_cost = _candidate_against_outside(
                    problem,
                    class_id,
                    placement,
                    option,
                    inside=inside,
                    placements=placements,
                    current_times=current_times,
                    rules=rules,
                    travel=travel,
                    deadline=deadline,
                )
            except TimeoutError:
                return None, "deadline_during_domains"
            if outside_cost is None:
                continue
            class_candidates.append(placement)
            domain_indices.append(option_index)
            costs.append(problem.optimization.time * option.penalty + outside_cost)
        if not class_candidates:
            return None, "empty_candidate_domain"
        candidates[class_id] = class_candidates
        candidate_domain_indices[class_id] = domain_indices
        unary_costs[class_id] = costs
        if time.monotonic() >= deadline - 0.75:
            return None, "deadline_during_domains"
    for first_id, second_id in combinations(group, 2):
        projected_pair_cells += len(candidates[first_id]) * len(candidates[second_id])
    if projected_pair_cells > maximum_pair_cells:
        return None, "pair_cell_scale_guard"

    model = cp_model.CpModel()
    choices = {}
    objective_terms = []
    for class_id in group:
        choice = model.new_int_var(0, len(candidates[class_id]) - 1, f"time_{class_id}")
        choices[class_id] = choice
        costs = unary_costs[class_id]
        cost = model.new_int_var(min(costs), max(costs), f"time_cost_{class_id}")
        model.add_element(choice, costs, cost)
        objective_terms.append(cost)
        incumbent_index = current_indices[class_id]
        if incumbent_index in candidate_domain_indices[class_id]:
            model.add_hint(
                choice,
                candidate_domain_indices[class_id].index(incumbent_index),
            )

    for first_id, second_id in combinations(group, 2):
        first_options = [
            time_domains[first_id][index]
            for index in candidate_domain_indices[first_id]
        ]
        second_options = [
            time_domains[second_id][index]
            for index in candidate_domain_indices[second_id]
        ]
        try:
            rows, maximum_cost = _pair_rows(
                problem,
                first_id,
                second_id,
                candidates[first_id],
                candidates[second_id],
                first_time_at=lambda index, options=first_options: options[index],
                second_time_at=lambda index, options=second_options: options[index],
                rules=rules,
                travel=travel,
                deadline=deadline,
            )
        except TimeoutError:
            return None, "deadline_during_model"
        if not rows:
            return None, "empty_pair_relation"
        pair_cost = model.new_int_var(
            0, maximum_cost, f"time_pair_{first_id}_{second_id}"
        )
        model.add_allowed_assignments(
            (choices[first_id], choices[second_id], pair_cost),
            rows,
        )
        objective_terms.append(pair_cost)
        if time.monotonic() >= deadline - 0.75:
            return None, "deadline_during_model"

    model.minimize(sum(objective_terms))
    remaining = deadline - time.monotonic() - 0.5
    if remaining <= 0:
        return None, "deadline_before_search"
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = remaining
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = random_seed
    status = solver.solve(model)
    if status not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        return None, solver.status_name(status)
    candidate = dict(placements)
    selected = {}
    for class_id in group:
        selected_index = int(solver.value(choices[class_id]))
        candidate[class_id] = candidates[class_id][selected_index]
        selected[class_id] = candidate_domain_indices[class_id][selected_index]
    return (candidate, selected), solver.status_name(status)


def _solve_room_group(
    problem,
    group,
    *,
    placements,
    current_times,
    current_indices,
    admitted_rooms,
    room_penalties,
    rules,
    travel,
    deadline,
    workers,
    random_seed,
    maximum_pair_cells,
):
    inside = set(group)
    candidates = {}
    unary_costs = {}
    projected_pair_cells = 0
    for class_id in group:
        option = current_times[class_id]
        class_candidates = []
        costs = []
        for room_id in admitted_rooms[(class_id, current_indices[class_id])]:
            placement = ITC2019ClassPlacement(
                class_id,
                option.days,
                option.start,
                option.weeks,
                room_id,
            )
            try:
                outside_cost = _candidate_against_outside(
                    problem,
                    class_id,
                    placement,
                    option,
                    inside=inside,
                    placements=placements,
                    current_times=current_times,
                    rules=rules,
                    travel=travel,
                    deadline=deadline,
                )
            except TimeoutError:
                return None, "deadline_during_domains"
            if outside_cost is None:
                continue
            class_candidates.append(placement)
            costs.append(
                problem.optimization.room * room_penalties[class_id].get(room_id, 0)
                + outside_cost
            )
        if not class_candidates:
            return None, "empty_candidate_domain"
        candidates[class_id] = class_candidates
        unary_costs[class_id] = costs
    for first_id, second_id in combinations(group, 2):
        projected_pair_cells += len(candidates[first_id]) * len(candidates[second_id])
    if projected_pair_cells > maximum_pair_cells:
        return None, "pair_cell_scale_guard"

    model = cp_model.CpModel()
    choices = {}
    objective_terms = []
    for class_id in group:
        choice = model.new_int_var(0, len(candidates[class_id]) - 1, f"room_{class_id}")
        choices[class_id] = choice
        costs = unary_costs[class_id]
        cost = model.new_int_var(min(costs), max(costs), f"room_cost_{class_id}")
        model.add_element(choice, costs, cost)
        objective_terms.append(cost)
        for index, placement in enumerate(candidates[class_id]):
            if placement.room_id == placements[class_id].room_id:
                model.add_hint(choice, index)
                break

    for first_id, second_id in combinations(group, 2):
        try:
            rows, maximum_cost = _pair_rows(
                problem,
                first_id,
                second_id,
                candidates[first_id],
                candidates[second_id],
                first_time_at=lambda _index, class_id=first_id: current_times[class_id],
                second_time_at=lambda _index, class_id=second_id: current_times[
                    class_id
                ],
                rules=rules,
                travel=travel,
                deadline=deadline,
            )
        except TimeoutError:
            return None, "deadline_during_model"
        if not rows:
            return None, "empty_pair_relation"
        pair_cost = model.new_int_var(
            0, maximum_cost, f"room_pair_{first_id}_{second_id}"
        )
        model.add_allowed_assignments(
            (choices[first_id], choices[second_id], pair_cost),
            rows,
        )
        objective_terms.append(pair_cost)
        if time.monotonic() >= deadline - 0.75:
            return None, "deadline_during_model"

    model.minimize(sum(objective_terms))
    remaining = deadline - time.monotonic() - 0.5
    if remaining <= 0:
        return None, "deadline_before_search"
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = remaining
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = random_seed
    status = solver.solve(model)
    if status not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        return None, solver.status_name(status)
    candidate = dict(placements)
    for class_id in group:
        candidate[class_id] = candidates[class_id][int(solver.value(choices[class_id]))]
    return candidate, solver.status_name(status)


def improve_itc2019_global_recurrence(
    problem: ITC2019Problem,
    placements: Mapping[str, ITC2019ClassPlacement] | Sequence[ITC2019ClassPlacement],
    student_classes: Mapping[str, Sequence[str]],
    *,
    deadline: float,
    workers: int = 1,
    random_seed: int = 17,
    diagnostics: dict | None = None,
    maximum_group_size: int = 24,
    maximum_pair_cells: int = 2_000_000,
) -> tuple[ITC2019ClassPlacement, ...]:
    """Improve soft recurrence groups without risking a valid incumbent."""

    diagnostics = diagnostics if diagnostics is not None else {}
    original = {placement.class_id: placement for placement in placements}
    student_classes = {
        student_id: tuple(class_ids)
        for student_id, class_ids in student_classes.items()
    }
    errors = validate_itc2019_solution(problem, original, student_classes)
    if errors:
        raise ValueError(errors[:8])
    original_score = score_itc2019_solution(problem, original, student_classes)
    diagnostics["initial_score"] = original_score.total
    if workers <= 0 or maximum_group_size <= 0 or maximum_pair_cells <= 0:
        raise ValueError("quality limits and workers must be positive")
    completion_deadline = deadline - 3.0
    if time.monotonic() >= completion_deadline:
        diagnostics["skipped"] = "insufficient_finalization_headroom"
        diagnostics["final_score"] = original_score.total
        return tuple(original[class_id] for class_id in sorted(original))

    try:
        domains = _build_factorized_domains(problem, deadline=completion_deadline)
    except (RuntimeError, TimeoutError) as exc:
        diagnostics["skipped"] = f"domain_build:{type(exc).__name__}"
        diagnostics["final_score"] = original_score.total
        return tuple(original[class_id] for class_id in sorted(original))
    if time.monotonic() >= completion_deadline:
        diagnostics["skipped"] = "deadline_after_domain_build"
        diagnostics["final_score"] = original_score.total
        return tuple(original[class_id] for class_id in sorted(original))
    time_domains = domains.times
    current_times = {}
    current_indices = {}
    for class_id, placement in original.items():
        for option_index, option in enumerate(time_domains[class_id]):
            if (
                option.days,
                option.start,
                option.weeks,
            ) == (placement.days, placement.start, placement.weeks):
                current_times[class_id] = option
                current_indices[class_id] = option_index
                break
        else:
            raise ValueError(f"time domain mismatch {class_id}")

    travel = _travel_values(problem)
    room_penalties = {
        klass.id: {
            option.room_id: option.penalty
            for option in domains.rooms[klass.id]
            if option is not None
        }
        for klass in problem.classes
    }
    blocked_by_room = defaultdict(int)
    for room in problem.rooms:
        for unavailable in room.unavailable:
            for week, week_active in enumerate(unavailable.weeks):
                if week_active != "1":
                    continue
                for day, day_active in enumerate(unavailable.days):
                    if day_active != "1":
                        continue
                    for slot in range(
                        unavailable.start, unavailable.start + unavailable.length
                    ):
                        blocked_by_room[room.id] |= 1 << (
                            (week * problem.nr_days + day) * problem.slots_per_day
                            + slot
                        )

    admitted_rooms = {}
    for klass in problem.classes:
        room_ids = tuple(room_penalties[klass.id]) or (None,)
        for option_index, option in enumerate(time_domains[klass.id]):
            time_mask = 0
            for week, week_active in enumerate(option.weeks):
                if week_active != "1":
                    continue
                for day, day_active in enumerate(option.days):
                    if day_active != "1":
                        continue
                    for slot in range(option.start, option.start + option.length):
                        time_mask |= 1 << (
                            (week * problem.nr_days + day) * problem.slots_per_day
                            + slot
                        )
            admitted_rooms[(klass.id, option_index)] = tuple(
                room_id
                for room_id in room_ids
                if room_id is None or not blocked_by_room[room_id] & time_mask
            )
        if time.monotonic() >= completion_deadline:
            diagnostics["skipped"] = "deadline_during_room_admission"
            diagnostics["final_score"] = original_score.total
            return tuple(original[class_id] for class_id in sorted(original))

    rules = defaultdict(list)
    group_keys = set()
    for distribution in problem.distributions:
        base, parameters = _distribution_spec(distribution.type)
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        if (
            not distribution.required
            and base in _RECURRENCE_RULES
            and len(class_ids) >= 3
        ):
            group_keys.add(tuple(sorted(class_ids)))
        if base not in _PAIR_DISTRIBUTIONS:
            continue
        for first_id, second_id in combinations(class_ids, 2):
            rules[tuple(sorted((first_id, second_id)))].append(
                (
                    first_id,
                    second_id,
                    base,
                    parameters,
                    distribution.required,
                    distribution.penalty,
                )
            )
        if time.monotonic() >= completion_deadline:
            diagnostics["skipped"] = "deadline_during_recurrence_index"
            diagnostics["final_score"] = original_score.total
            return tuple(original[class_id] for class_id in sorted(original))

    distribution_scores = evaluate_itc2019_distributions(problem, original)
    recurrence_penalty = defaultdict(int)
    for distribution, score in zip(
        problem.distributions, distribution_scores, strict=True
    ):
        key = tuple(sorted(dict.fromkeys(distribution.class_ids)))
        if key in group_keys and not distribution.required:
            recurrence_penalty[key] += score.penalty
    groups = tuple(
        sorted(
            (key for key in group_keys if len(key) <= maximum_group_size),
            key=lambda key: (-recurrence_penalty[key], key),
        )
    )
    diagnostics["recurrence_groups"] = len(group_keys)
    diagnostics["admitted_groups"] = len(groups)

    incumbent = dict(original)
    incumbent_score = original_score
    accepted = 0
    attempted = 0
    cycle = 0
    while groups and time.monotonic() < completion_deadline - 1.0:
        cycle_start_score = incumbent_score.total
        for phase in ("time", "room"):
            for group_index, group in enumerate(groups):
                if time.monotonic() >= completion_deadline - 1.0:
                    break
                attempted += 1
                slice_seconds = min(
                    8.0,
                    max(0.75, completion_deadline - time.monotonic()),
                )
                group_deadline = min(
                    completion_deadline,
                    time.monotonic() + slice_seconds,
                )
                if phase == "time":
                    result, status = _solve_time_group(
                        problem,
                        group,
                        placements=incumbent,
                        current_times=current_times,
                        current_indices=current_indices,
                        time_domains=time_domains,
                        admitted_rooms=admitted_rooms,
                        rules=rules,
                        travel=travel,
                        deadline=group_deadline,
                        workers=workers,
                        random_seed=random_seed + cycle * 101 + group_index,
                        maximum_pair_cells=maximum_pair_cells,
                    )
                    if result is None:
                        diagnostics[f"{phase}_{cycle}_{group_index}"] = status
                        continue
                    candidate, selected_indices = result
                else:
                    candidate, status = _solve_room_group(
                        problem,
                        group,
                        placements=incumbent,
                        current_times=current_times,
                        current_indices=current_indices,
                        admitted_rooms=admitted_rooms,
                        room_penalties=room_penalties,
                        rules=rules,
                        travel=travel,
                        deadline=group_deadline,
                        workers=workers,
                        random_seed=random_seed + 50 + cycle * 101 + group_index,
                        maximum_pair_cells=maximum_pair_cells,
                    )
                    if candidate is None:
                        diagnostics[f"{phase}_{cycle}_{group_index}"] = status
                        continue
                if time.monotonic() >= completion_deadline:
                    break
                candidate_errors = validate_itc2019_solution(
                    problem,
                    candidate,
                    student_classes,
                )
                if candidate_errors:
                    diagnostics[f"{phase}_{cycle}_{group_index}"] = (
                        "whole_problem_invalid"
                    )
                    continue
                candidate_score = score_itc2019_solution(
                    problem,
                    candidate,
                    student_classes,
                )
                if candidate_score.total >= incumbent_score.total:
                    continue
                incumbent = candidate
                incumbent_score = candidate_score
                accepted += 1
                if phase == "time":
                    for class_id, option_index in selected_indices.items():
                        current_indices[class_id] = option_index
                        current_times[class_id] = time_domains[class_id][option_index]
        diagnostics["cycles"] = cycle + 1
        cycle += 1
        if incumbent_score.total >= cycle_start_score or cycle >= 8:
            break

    final_errors = validate_itc2019_solution(problem, incumbent, student_classes)
    if final_errors:
        diagnostics["final_validation_errors"] = len(final_errors)
        incumbent = original
        incumbent_score = original_score
    diagnostics["attempted_neighborhoods"] = attempted
    diagnostics["accepted_checkpoints"] = accepted
    diagnostics["final_score"] = incumbent_score.total
    diagnostics["improvement"] = original_score.total - incumbent_score.total
    diagnostics["finalization_headroom_seconds"] = deadline - time.monotonic()
    return tuple(incumbent[class_id] for class_id in sorted(incumbent))


__all__ = ["improve_itc2019_global_recurrence"]
