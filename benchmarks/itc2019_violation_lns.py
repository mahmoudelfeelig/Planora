"""Bounded violation-rooted quality search for complete ITC-2019 solutions.

Neighborhoods price realized student, pair-distribution, and grouped-distribution
violations.  MaxDays, MaxDayLoad, MaxBreaks, and MaxBlock are represented by
exact, cell-capped time tables, so required groups remain hard while soft group
costs use the same cross-week normalization as the independent official scorer.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations, product
import time
from typing import Mapping, Sequence

from ortools.sat.python import cp_model

from benchmarks.itc2019 import (
    ITC2019ClassPlacement,
    ITC2019Objective,
    ITC2019Problem,
    _distribution_spec,
    _pair_distribution_satisfied,
    _special_distribution_units,
    _student_pair_conflicts,
    _travel_values,
    score_itc2019_solution,
    validate_itc2019_solution,
)
from benchmarks.itc2019_factorized import _build_factorized_domains


_PAIR_BASES = frozenset(
    {
        "DifferentDays",
        "DifferentRoom",
        "DifferentTime",
        "DifferentWeeks",
        "MinGap",
        "NotOverlap",
        "Overlap",
        "Precedence",
        "SameAttendees",
        "SameDays",
        "SameRoom",
        "SameStart",
        "SameTime",
        "SameWeeks",
        "WorkDay",
    }
)
_SUPPORTED_GROUPS = frozenset({"MaxDays", "MaxDayLoad", "MaxBreaks", "MaxBlock"})
DEFAULT_MAX_STUDENT_PAIR_VISITS = 200_000


@dataclass(frozen=True, slots=True)
class ITC2019ViolationLNSPass:
    """Immutable evidence for one attempted root neighborhood."""

    root: str
    closure_size: int
    candidate_values: int
    pair_tables: int
    group_tables: int
    solver_status: str
    branches: int
    conflicts: int
    before_total: int
    candidate_total: int | None
    accepted: bool


@dataclass(frozen=True, slots=True)
class ITC2019ViolationLNSResult:
    """Immutable incumbent handoff and independently checked pass evidence."""

    placements: tuple[ITC2019ClassPlacement, ...]
    initial_objective: ITC2019Objective
    objective: ITC2019Objective
    attempted_passes: int
    accepted_passes: int
    passes: tuple[ITC2019ViolationLNSPass, ...]
    validation_errors: tuple[str, ...]
    stop_reason: str


def count_itc2019_student_pair_visits(
    student_classes: Mapping[str, Sequence[str]],
    *,
    stop_after: int | None = None,
) -> int:
    """Count concrete student-pair visits without retaining a global pair index."""

    if stop_after is not None and stop_after < 0:
        raise ValueError("stop_after must be non-negative")
    visits = 0
    for class_ids in student_classes.values():
        distinct_classes = len(set(class_ids))
        visits += distinct_classes * (distinct_classes - 1) // 2
        if stop_after is not None and visits > stop_after:
            break
    return visits


def _occurrences(option):
    for week, week_active in enumerate(option.weeks):
        if week_active != "1":
            continue
        for day, day_active in enumerate(option.days):
            if day_active != "1":
                continue
            for slot in range(option.start, option.start + option.length):
                yield week, day, slot


def _overlap(first, first_time, second, second_time, travel):
    return not _pair_distribution_satisfied(
        "NotOverlap", (), first, first_time, second, second_time, travel
    )


def improve_itc2019_violation_rooted(
    problem: ITC2019Problem,
    placements: Sequence[ITC2019ClassPlacement],
    student_classes: Mapping[str, Sequence[str]],
    *,
    deadline: float,
    workers: int,
    random_seed: int,
    max_attempts: int = 8,
    max_accepted_passes: int = 3,
    max_group_table_cells: int = 150_000,
    minimum_headroom_seconds: float = 3.0,
) -> ITC2019ViolationLNSResult:
    """Improve a complete incumbent through bounded recomputed violation roots.

    The caller owns the absolute deadline.  Every accepted handoff is validated
    and fully rescored independently; invalid, late, equal, or worse candidates
    are rolled back without mutating the supplied incumbent.  Exact grouped
    tables share ``max_group_table_cells`` across a neighborhood and fail closed
    when that cap or the deadline would be exceeded.
    """

    if workers <= 0:
        raise ValueError("workers must be positive")
    if random_seed < 0:
        raise ValueError("random_seed must be non-negative")
    if max_attempts <= 0 or max_accepted_passes <= 0:
        raise ValueError("pass limits must be positive")
    if max_group_table_cells <= 0:
        raise ValueError("max_group_table_cells must be positive")

    frozen_students = {
        student_id: tuple(class_ids)
        for student_id, class_ids in student_classes.items()
    }
    incumbent = tuple(placements)
    initial_errors = tuple(
        validate_itc2019_solution(problem, incumbent, frozen_students)
    )
    if initial_errors:
        raise ValueError(
            "invalid violation-rooted incumbent: " + "; ".join(initial_errors)
        )
    initial_objective = score_itc2019_solution(problem, incumbent, frozen_students)
    if deadline - time.monotonic() < minimum_headroom_seconds:
        return ITC2019ViolationLNSResult(
            incumbent,
            initial_objective,
            initial_objective,
            0,
            0,
            (),
            (),
            "insufficient_headroom",
        )

    try:
        domains = _build_factorized_domains(problem, deadline=deadline)
    except (TimeoutError, ValueError):
        return ITC2019ViolationLNSResult(
            incumbent,
            initial_objective,
            initial_objective,
            0,
            0,
            (),
            (),
            "domain_build_failed",
        )
    time_domains = domains.times
    travel = _travel_values(problem)

    room_penalties = {}
    room_options = {}
    for klass in problem.classes:
        penalties = {}
        for option in domains.rooms[klass.id]:
            if option is not None:
                penalties[option.room_id] = min(
                    penalties.get(option.room_id, 10**9), option.penalty
                )
        room_penalties[klass.id] = penalties
        room_options[klass.id] = tuple(sorted(penalties)) or (None,)
    blocked = {
        room.id: frozenset(
            occurrence
            for unavailable in room.unavailable
            for occurrence in _occurrences(unavailable)
        )
        for room in problem.rooms
    }

    hard_pairs = defaultdict(list)
    soft_pairs = defaultdict(list)
    hard_groups = []
    soft_groups = []
    for distribution_index, distribution in enumerate(problem.distributions):
        base, parameters = _distribution_spec(distribution.type)
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        if base not in _PAIR_BASES:
            if distribution.required:
                hard_groups.append((base, parameters, class_ids))
            else:
                soft_groups.append((base, parameters, class_ids, distribution.penalty))
            continue
        for left, right in combinations(class_ids, 2):
            entry = (
                left,
                right,
                base,
                parameters,
                distribution.penalty,
                distribution_index,
            )
            destination = hard_pairs if distribution.required else soft_pairs
            destination[left].append(entry)
            destination[right].append(entry)
    unsupported_hard = {
        base
        for base, _parameters, _class_ids in hard_groups
        if base not in _SUPPORTED_GROUPS
    }
    unsupported_soft = {
        base
        for base, _parameters, _class_ids, _penalty in soft_groups
        if base not in _SUPPORTED_GROUPS
    }
    if unsupported_soft or unsupported_hard:
        return ITC2019ViolationLNSResult(
            incumbent,
            initial_objective,
            initial_objective,
            0,
            0,
            (),
            (),
            "unsupported_objective_or_hard_group",
        )
    soft_groups_by_class = defaultdict(list)
    for entry in soft_groups:
        for class_id in entry[2]:
            soft_groups_by_class[class_id].append(entry)

    student_weights = defaultdict(int)
    for assigned in frozen_students.values():
        for left, right in combinations(sorted(set(assigned)), 2):
            student_weights[(left, right)] += 1
    student_partners = defaultdict(list)
    for (left, right), weight in student_weights.items():
        student_partners[left].append((right, weight))
        student_partners[right].append((left, weight))

    def current_times(placement_map):
        selected = {}
        indices = {}
        for klass in problem.classes:
            placement = placement_map[klass.id]
            for index, option in enumerate(time_domains[klass.id]):
                if (
                    option.days == placement.days
                    and option.start == placement.start
                    and option.weeks == placement.weeks
                ):
                    selected[klass.id] = option
                    indices[klass.id] = index
                    break
            else:
                raise ValueError(f"time domain mismatch {klass.id}")
        return selected, indices

    def oriented_satisfied(
        entry,
        left_id,
        left_placement,
        left_time,
        right_id,
        right_placement,
        right_time,
    ):
        first, second, base, parameters, _penalty, _distribution_index = entry
        first_placement = left_placement if first == left_id else right_placement
        first_time = left_time if first == left_id else right_time
        second_placement = left_placement if second == left_id else right_placement
        second_time = left_time if second == left_id else right_time
        return _pair_distribution_satisfied(
            base,
            parameters,
            first_placement,
            first_time,
            second_placement,
            second_time,
            travel,
        )

    incumbent_objective = initial_objective
    attempted = 0
    accepted = 0
    pass_evidence = []
    tried_roots = set()
    stop_reason = "attempt_limit"

    while attempted < max_attempts and accepted < max_accepted_passes:
        if deadline - time.monotonic() < minimum_headroom_seconds:
            stop_reason = "insufficient_headroom"
            break
        placement_map = {placement.class_id: placement for placement in incumbent}
        selected_times, current_indices = current_times(placement_map)

        violation_edges = defaultdict(int)
        for (left, right), weight in student_weights.items():
            if _student_pair_conflicts(
                problem,
                placement_map[left],
                selected_times[left],
                placement_map[right],
                selected_times[right],
                travel,
            ):
                violation_edges[(left, right)] += problem.optimization.student * weight
        seen_soft = set()
        for entries in soft_pairs.values():
            for entry in entries:
                if entry in seen_soft:
                    continue
                seen_soft.add(entry)
                left, right, _base, _parameters, penalty, _distribution_index = entry
                if not oriented_satisfied(
                    entry,
                    left,
                    placement_map[left],
                    selected_times[left],
                    right,
                    placement_map[right],
                    selected_times[right],
                ):
                    violation_edges[tuple(sorted((left, right)))] += (
                        problem.optimization.distribution * penalty
                    )
        group_pressure = defaultdict(int)
        group_scan_late = False
        for base, parameters, class_ids, penalty in soft_groups:
            if deadline - time.monotonic() < 0.75:
                group_scan_late = True
                break
            units = _special_distribution_units(
                problem,
                base,
                parameters,
                class_ids,
                selected_times,
            )
            if not units:
                continue
            if base in {"MaxDayLoad", "MaxBreaks", "MaxBlock"}:
                raw_penalty = penalty * units // problem.nr_weeks
            else:
                raw_penalty = penalty * units
            weighted_penalty = problem.optimization.distribution * raw_penalty
            for class_id in class_ids:
                group_pressure[class_id] += weighted_penalty
        if group_scan_late:
            stop_reason = "deadline_during_group_pressure"
            break
        if not violation_edges and not group_pressure:
            stop_reason = "no_realized_violation"
            break

        pressure = defaultdict(int)
        adjacency = defaultdict(list)
        for (left, right), weight in violation_edges.items():
            pressure[left] += weight
            pressure[right] += weight
            adjacency[left].append((weight, right))
            adjacency[right].append((weight, left))
        for class_id, weight in group_pressure.items():
            pressure[class_id] += weight
        ranked_roots = sorted(
            pressure,
            key=lambda class_id: (pressure[class_id], class_id),
            reverse=True,
        )
        root = next(
            (class_id for class_id in ranked_roots if class_id not in tried_roots),
            None,
        )
        if root is None:
            stop_reason = "all_realized_roots_tried"
            break

        closure = {root}
        while len(closure) < 14:
            frontier = [
                (weight, source, target)
                for source in closure
                for weight, target in adjacency[source]
                if target not in closure
            ]
            if not frontier:
                break
            _weight, _source, target = max(frontier)
            closure.add(target)

        room_members = defaultdict(list)
        for class_id, placement in placement_map.items():
            room_members[placement.room_id].append(class_id)
        blocker_rows = []
        for class_id in tuple(closure):
            option = selected_times[class_id]
            for other_id in room_members[placement_map[class_id].room_id]:
                if other_id in closure or other_id == class_id:
                    continue
                other = selected_times[other_id]
                if not any(
                    left == right == "1"
                    for left, right in zip(option.days, other.days, strict=True)
                ):
                    continue
                if not any(
                    left == right == "1"
                    for left, right in zip(option.weeks, other.weeks, strict=True)
                ):
                    continue
                gap = min(
                    abs(option.start + option.length - other.start),
                    abs(other.start + other.length - option.start),
                )
                blocker_rows.append((gap, other_id))
        for _gap, other_id in sorted(set(blocker_rows)):
            if len(closure) >= 16:
                break
            closure.add(other_id)

        outside = set(placement_map) - closure
        outside_by_room = defaultdict(list)
        for other_id in outside:
            room_id = placement_map[other_id].room_id
            if room_id is not None:
                outside_by_room[room_id].append(other_id)
        hard_outside = {}
        for class_id in closure:
            hard_outside[class_id] = tuple(
                sorted(
                    {
                        right if left == class_id else left
                        for left, right, *_rest in hard_pairs[class_id]
                        if (right if left == class_id else left) in outside
                    }
                )
            )

        def room_available(room_id, option):
            return room_id is None or not blocked[room_id].intersection(
                _occurrences(option)
            )

        def pair_valid(
            left_id,
            left_placement,
            left_time,
            right_id,
            right_placement,
            right_time,
        ):
            entries = {entry for entry in hard_pairs[left_id] if right_id in entry[:2]}
            return all(
                oriented_satisfied(
                    entry,
                    left_id,
                    left_placement,
                    left_time,
                    right_id,
                    right_placement,
                    right_time,
                )
                for entry in entries
            )

        def interaction_costs(class_id, candidate, option):
            """Price a candidate against every partner in the current solution.

            This is a pruning heuristic only. Interactions inside the closure remain
            exact pair-table terms in the model, while interactions outside remain
            exact unary terms. Including both here prevents a low unary-cost prefix
            from filling the bounded candidate domain with values that preserve the
            very student or distribution conflict that rooted this neighborhood.
            Returning both totals from one traversal avoids repricing every outside
            partner when constructing the exact unary objective.
            """
            if deadline - time.monotonic() < 0.75:
                raise TimeoutError("deadline during interaction candidate ranking")
            ranking_cost = 0
            outside_cost = 0
            for partner_index, (other_id, weight) in enumerate(
                student_partners[class_id]
            ):
                if partner_index % 32 == 0 and deadline - time.monotonic() < 0.75:
                    raise TimeoutError(
                        "deadline during student interaction candidate ranking"
                    )
                if _student_pair_conflicts(
                    problem,
                    candidate,
                    option,
                    placement_map[other_id],
                    selected_times[other_id],
                    travel,
                ):
                    weighted_cost = problem.optimization.student * weight
                    ranking_cost += weighted_cost
                    if other_id in outside:
                        outside_cost += weighted_cost
            for pair_index, entry in enumerate(soft_pairs[class_id]):
                if pair_index % 32 == 0 and deadline - time.monotonic() < 0.75:
                    raise TimeoutError(
                        "deadline during distribution interaction candidate ranking"
                    )
                left, right, _base, _parameters, penalty, _distribution_index = entry
                other_id = right if left == class_id else left
                if not oriented_satisfied(
                    entry,
                    class_id,
                    candidate,
                    option,
                    other_id,
                    placement_map[other_id],
                    selected_times[other_id],
                ):
                    weighted_cost = problem.optimization.distribution * penalty
                    ranking_cost += weighted_cost
                    if other_id in outside:
                        outside_cost += weighted_cost
            return ranking_cost, outside_cost

        group_sort_cache = {}

        def group_sort_cost(class_id, time_index, option):
            cache_key = class_id, time_index
            cached = group_sort_cache.get(cache_key)
            if cached is not None:
                return cached
            cost = 0
            for base, parameters, class_ids, penalty in soft_groups_by_class[class_id]:
                if deadline - time.monotonic() < 0.75:
                    raise TimeoutError("deadline during group candidate ranking")
                resolved = {
                    member_id: option
                    if member_id == class_id
                    else selected_times[member_id]
                    for member_id in class_ids
                }
                units = _special_distribution_units(
                    problem,
                    base,
                    parameters,
                    class_ids,
                    resolved,
                )
                if base in {"MaxDayLoad", "MaxBreaks", "MaxBlock"}:
                    raw_cost = penalty * units // problem.nr_weeks
                else:
                    raw_cost = penalty * units
                cost += problem.optimization.distribution * raw_cost
            group_sort_cache[cache_key] = cost
            return cost

        candidates = {}
        candidate_times = {}
        candidate_outside_costs = {}
        build_failed = False
        for class_id in sorted(closure):
            rows = []
            for time_index, option in enumerate(time_domains[class_id]):
                for room_id in room_options[class_id]:
                    if not room_available(room_id, option):
                        continue
                    candidate = ITC2019ClassPlacement(
                        class_id, option.days, option.start, option.weeks, room_id
                    )
                    if any(
                        _overlap(
                            candidate,
                            option,
                            placement_map[other_id],
                            selected_times[other_id],
                            travel,
                        )
                        for other_id in outside_by_room[room_id]
                    ):
                        continue
                    if any(
                        not pair_valid(
                            class_id,
                            candidate,
                            option,
                            other_id,
                            placement_map[other_id],
                            selected_times[other_id],
                        )
                        for other_id in hard_outside[class_id]
                    ):
                        continue
                    try:
                        ranking_group_cost = group_sort_cost(
                            class_id,
                            time_index,
                            option,
                        )
                        (
                            ranking_interaction_cost,
                            exact_outside_cost,
                        ) = interaction_costs(
                            class_id,
                            candidate,
                            option,
                        )
                    except TimeoutError:
                        build_failed = True
                        break
                    fixed_cost = (
                        problem.optimization.time * option.penalty
                        + problem.optimization.room
                        * room_penalties[class_id].get(room_id, 0)
                        + ranking_interaction_cost
                        + ranking_group_cost
                    )
                    is_incumbent = (
                        time_index == current_indices[class_id]
                        and room_id == placement_map[class_id].room_id
                    )
                    rows.append(
                        (
                            fixed_cost,
                            not is_incumbent,
                            time_index,
                            str(room_id),
                            candidate,
                            option,
                            exact_outside_cost,
                        )
                    )
                if build_failed:
                    break
                if deadline - time.monotonic() < 0.75:
                    build_failed = True
                    break
            if build_failed:
                break
            rows.sort(key=lambda row: row[:4])
            selected_rows = rows[:47]
            incumbent_rows = [row for row in rows if not row[1]]
            if incumbent_rows and incumbent_rows[0] not in selected_rows:
                selected_rows.append(incumbent_rows[0])
            if not selected_rows:
                build_failed = True
                break
            candidates[class_id] = tuple(row[4] for row in selected_rows)
            candidate_times[class_id] = tuple(row[5] for row in selected_rows)
            candidate_outside_costs[class_id] = tuple(row[6] for row in selected_rows)
        if build_failed:
            stop_reason = "neighborhood_build_failed_or_late"
            break

        model = cp_model.CpModel()
        choice = {}
        active = {}
        unary_costs = {}
        closure_ids = sorted(closure)
        for class_id in closure_ids:
            count = len(candidates[class_id])
            choice[class_id] = model.new_int_var(0, count - 1, f"choice_{class_id}")
            active[class_id] = tuple(
                model.new_bool_var(f"active_{class_id}_{index}")
                for index in range(count)
            )
            model.add_exactly_one(active[class_id])
            model.add(
                choice[class_id]
                == sum(
                    index * literal for index, literal in enumerate(active[class_id])
                )
            )
            unary_costs[class_id] = tuple(
                problem.optimization.time * option.penalty
                + problem.optimization.room
                * room_penalties[class_id].get(candidate.room_id, 0)
                + exact_outside_cost
                for candidate, option, exact_outside_cost in zip(
                    candidates[class_id],
                    candidate_times[class_id],
                    candidate_outside_costs[class_id],
                    strict=True,
                )
            )

        pair_cost_variables = []
        for left_id, right_id in combinations(closure_ids, 2):
            table_rows = []
            pair_weight = student_weights.get((left_id, right_id), 0)
            soft_entries = {
                entry for entry in soft_pairs[left_id] if right_id in entry[:2]
            }
            for left_index, (left_candidate, left_time) in enumerate(
                zip(
                    candidates[left_id],
                    candidate_times[left_id],
                    strict=True,
                )
            ):
                for right_index, (right_candidate, right_time) in enumerate(
                    zip(
                        candidates[right_id],
                        candidate_times[right_id],
                        strict=True,
                    )
                ):
                    if (
                        left_candidate.room_id is not None
                        and left_candidate.room_id == right_candidate.room_id
                        and _overlap(
                            left_candidate,
                            left_time,
                            right_candidate,
                            right_time,
                            travel,
                        )
                    ):
                        continue
                    if not pair_valid(
                        left_id,
                        left_candidate,
                        left_time,
                        right_id,
                        right_candidate,
                        right_time,
                    ):
                        continue
                    cost = 0
                    if pair_weight and _student_pair_conflicts(
                        problem,
                        left_candidate,
                        left_time,
                        right_candidate,
                        right_time,
                        travel,
                    ):
                        cost += problem.optimization.student * pair_weight
                    for entry in soft_entries:
                        if not oriented_satisfied(
                            entry,
                            left_id,
                            left_candidate,
                            left_time,
                            right_id,
                            right_candidate,
                            right_time,
                        ):
                            cost += problem.optimization.distribution * entry[4]
                    table_rows.append((left_index, right_index, cost))
            if not table_rows:
                build_failed = True
                break
            maximum = max(row[2] for row in table_rows)
            pair_cost = model.new_int_var(0, maximum, f"pair_cost_{left_id}_{right_id}")
            model.add_allowed_assignments(
                (choice[left_id], choice[right_id], pair_cost), table_rows
            )
            pair_cost_variables.append(pair_cost)
            if deadline - time.monotonic() < 0.75:
                build_failed = True
                break
        if build_failed:
            stop_reason = "pair_table_build_failed_or_late"
            break

        unique_times = {}
        time_choice = {}
        for class_id in closure_ids:
            signatures = {}
            values = []
            candidate_codes = []
            for option in candidate_times[class_id]:
                signature = (
                    option.days,
                    option.start,
                    option.length,
                    option.weeks,
                )
                code = signatures.get(signature)
                if code is None:
                    code = len(values)
                    signatures[signature] = code
                    values.append(option)
                candidate_codes.append(code)
            unique_times[class_id] = tuple(values)
            time_choice[class_id] = model.new_int_var(
                0,
                len(values) - 1,
                f"time_choice_{class_id}",
            )
            model.add_allowed_assignments(
                (choice[class_id], time_choice[class_id]),
                tuple(enumerate(candidate_codes)),
            )

        group_cost_variables = []
        group_table_count = 0
        group_cells = 0
        group_build_failed = False
        group_specs = tuple(
            (True, base, parameters, class_ids, 0)
            for base, parameters, class_ids in hard_groups
        ) + tuple(
            (False, base, parameters, class_ids, penalty)
            for base, parameters, class_ids, penalty in soft_groups
        )
        for (
            group_index,
            (required, base, parameters, class_ids, penalty),
        ) in enumerate(group_specs):
            inside_ids = tuple(
                class_id for class_id in class_ids if class_id in closure
            )
            if not inside_ids:
                continue
            projected_rows = 1
            for class_id in inside_ids:
                projected_rows *= len(unique_times[class_id])
                if projected_rows > max_group_table_cells:
                    break
            row_width = len(inside_ids) + (0 if required else 1)
            projected_cells = projected_rows * row_width
            if (
                projected_cells > max_group_table_cells
                or group_cells + projected_cells > max_group_table_cells
            ):
                group_build_failed = True
                break
            group_cells += projected_cells
            fixed_times = {
                class_id: selected_times[class_id]
                for class_id in class_ids
                if class_id not in closure
            }
            rows = []
            maximum_cost = 0
            for row_index, codes in enumerate(
                product(
                    *(range(len(unique_times[class_id])) for class_id in inside_ids)
                )
            ):
                if row_index % 128 == 0 and deadline - time.monotonic() < 0.75:
                    group_build_failed = True
                    break
                resolved = dict(fixed_times)
                resolved.update(
                    (
                        class_id,
                        unique_times[class_id][code],
                    )
                    for class_id, code in zip(inside_ids, codes, strict=True)
                )
                units = _special_distribution_units(
                    problem,
                    base,
                    parameters,
                    class_ids,
                    resolved,
                )
                if required:
                    if units == 0:
                        rows.append(codes)
                    continue
                if base in {"MaxDayLoad", "MaxBreaks", "MaxBlock"}:
                    raw_cost = penalty * units // problem.nr_weeks
                else:
                    raw_cost = penalty * units
                cost = problem.optimization.distribution * raw_cost
                maximum_cost = max(maximum_cost, cost)
                rows.append((*codes, cost))
            if group_build_failed or not rows:
                group_build_failed = True
                break
            variables = tuple(time_choice[class_id] for class_id in inside_ids)
            if required:
                model.add_allowed_assignments(variables, rows)
            else:
                cost_variable = model.new_int_var(
                    0,
                    maximum_cost,
                    f"group_cost_{group_index}",
                )
                model.add_allowed_assignments((*variables, cost_variable), rows)
                group_cost_variables.append(cost_variable)
            group_table_count += 1
        if group_build_failed:
            tried_roots.add(root)
            attempted += 1
            stop_reason = "group_table_build_failed_or_late"
            continue

        objective_terms = [*pair_cost_variables, *group_cost_variables]
        objective_terms.extend(
            cost * active[class_id][index]
            for class_id in closure_ids
            for index, cost in enumerate(unary_costs[class_id])
        )
        model.minimize(sum(objective_terms))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(
            0.01, min(3.5, deadline - time.monotonic() - 0.5)
        )
        solver.parameters.num_search_workers = workers
        solver.parameters.random_seed = random_seed + attempted
        before_total = incumbent_objective.total
        status = solver.solve(model)
        attempted += 1
        candidate_total = None
        accepted_move = False

        if status in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
            candidate_map = dict(placement_map)
            for class_id in closure_ids:
                candidate_map[class_id] = candidates[class_id][
                    int(solver.value(choice[class_id]))
                ]
            candidate_tuple = tuple(
                candidate_map[klass.id] for klass in problem.classes
            )
            candidate_errors = tuple(
                validate_itc2019_solution(problem, candidate_tuple, frozen_students)
            )
            if not candidate_errors and time.monotonic() < deadline:
                candidate_objective = score_itc2019_solution(
                    problem, candidate_tuple, frozen_students
                )
                candidate_total = candidate_objective.total
                if (
                    time.monotonic() < deadline
                    and candidate_total < incumbent_objective.total
                ):
                    incumbent = candidate_tuple
                    incumbent_objective = candidate_objective
                    accepted += 1
                    accepted_move = True
                    tried_roots.clear()

        pass_evidence.append(
            ITC2019ViolationLNSPass(
                root=root,
                closure_size=len(closure),
                candidate_values=sum(map(len, candidates.values())),
                pair_tables=len(pair_cost_variables),
                group_tables=group_table_count,
                solver_status=solver.status_name(status),
                branches=solver.num_branches,
                conflicts=solver.num_conflicts,
                before_total=before_total,
                candidate_total=candidate_total,
                accepted=accepted_move,
            )
        )
        if not accepted_move:
            tried_roots.add(root)

    final_errors = tuple(validate_itc2019_solution(problem, incumbent, frozen_students))
    final_objective = score_itc2019_solution(problem, incumbent, frozen_students)
    if accepted >= max_accepted_passes:
        stop_reason = "accepted_pass_limit"
    return ITC2019ViolationLNSResult(
        placements=incumbent,
        initial_objective=initial_objective,
        objective=final_objective,
        attempted_passes=attempted,
        accepted_passes=accepted,
        passes=tuple(pass_evidence),
        validation_errors=final_errors,
        stop_reason=stop_reason,
    )
