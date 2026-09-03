"""Staged exact-time and joint room repair for sparse ITC-2019 instances."""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import replace
from heapq import heapify, heappop, heappush
from itertools import combinations
import random
import time

from ortools.sat.python import cp_model

from benchmarks.itc2019 import (
    ITC2019ClassPlacement,
    ITC2019NativeSolveResult,
    ITC2019Problem,
    _PAIR_DISTRIBUTIONS,
    _distribution_spec,
    _intervals_overlap,
    _itc2019_native_failure,
    _masks_overlap,
    _pair_distribution_satisfied,
    _special_distribution_units,
    _travel_values,
    score_itc2019_solution,
    solve_itc2019_student_sectioning,
    validate_itc2019_solution,
)
from benchmarks.itc2019_factorized import _build_factorized_domains
from benchmarks.itc2019_compact_joint import (
    construct_itc2019_compact_joint,
    estimate_itc2019_compact_joint_scale,
)
from benchmarks.itc2019_global_components import (
    construct_itc2019_global_components,
    should_construct_itc2019_globally,
)
from benchmarks.itc2019_global_quality import improve_itc2019_global_recurrence
from benchmarks.itc2019_generalized_occurrences import (
    construct_itc2019_generalized_occurrences,
    should_construct_itc2019_generalized_occurrences,
)
from benchmarks.itc2019_grouped_calendar import (
    construct_itc2019_grouped_calendar,
    should_construct_itc2019_grouped_calendar,
)
from benchmarks.itc2019_resource_seed import (
    construct_itc2019_resource_seed,
    should_construct_itc2019_resource_seed,
)
from benchmarks.itc2019_sparse_joint import (
    construct_itc2019_sparse_joint,
    estimate_itc2019_sparse_joint_scale,
)
from benchmarks.itc2019_violation_lns import (
    DEFAULT_MAX_STUDENT_PAIR_VISITS,
    count_itc2019_student_pair_visits,
    improve_itc2019_violation_rooted,
)


DEFAULT_MAX_TIME_PAIR_CACHE_ENTRIES = 65_536
_PREDICATE_DEADLINE_CHECK_INTERVAL = 4_096


class _BoundedPredicateCache:
    """Small exact LRU for scalar predicate results.

    Compatibility matrices retain their own compact integer rows.  Keeping every
    individual Cartesian predicate cell in a second dictionary duplicates that
    matrix with high-overhead Python keys and values, so this cache deliberately
    bounds only the repeated scalar lookups used by the repair heuristics.
    """

    __slots__ = ("_max_entries", "_values")

    def __init__(self, *, max_entries: int) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max_entries = int(max_entries)
        self._values = OrderedDict()

    def __contains__(self, key) -> bool:
        return key in self._values

    def __len__(self) -> int:
        return len(self._values)

    def resolve(self, key, build):
        try:
            value = self._values.pop(key)
        except KeyError:
            value = build()
            if len(self._values) >= self._max_entries:
                self._values.popitem(last=False)
        self._values[key] = value
        return value


def _build_compact_allowed_option_masks(
    first_domain_size: int,
    second_domain_size: int,
    predicate,
    *,
    deadline: float,
    clock=time.monotonic,
) -> tuple[int, ...]:
    """Evaluate one Cartesian predicate without retaining its individual cells."""

    rows = []
    visits = 0
    for first_index in range(first_domain_size):
        allowed = 0
        for second_index in range(second_domain_size):
            if visits % _PREDICATE_DEADLINE_CHECK_INTERVAL == 0:
                if clock() >= deadline:
                    raise TimeoutError("decomposed option-mask build exceeded deadline")
            visits += 1
            if predicate(first_index, second_index):
                allowed |= 1 << second_index
        rows.append(allowed)
    return tuple(rows)


def _iter_forbidden_option_pairs(
    allowed_rows,
    second_domain_size: int,
    *,
    deadline: float,
    clock=time.monotonic,
):
    """Yield the legacy forbidden-table order without a duplicate tuple list."""

    visits = 0
    for first_index, allowed in enumerate(allowed_rows):
        for second_index in range(second_domain_size):
            if visits % _PREDICATE_DEADLINE_CHECK_INTERVAL == 0:
                if clock() >= deadline:
                    raise TimeoutError(
                        "decomposed time-predicate build exceeded deadline"
                    )
            visits += 1
            if not allowed & (1 << second_index):
                yield first_index, second_index


def _add_streamed_forbidden_assignments(model, expressions, forbidden_pairs) -> bool:
    """Append a table directly to its protobuf, avoiding a duplicate Python list.

    The frozen OR-Tools binding annotates ``tuples_list`` as an iterable but its
    native boundary accepts only ``list[list[int]]``.  Creating the empty table
    through the public API preserves expression encoding and validation; appending
    each already-validated integer pair to the repeated scalar field then produces
    the same final model protobuf without retaining a second Cartesian copy.
    """

    arity = len(expressions)
    constraint = model.add_forbidden_assignments(expressions, [])
    values = constraint.proto.table.values
    forbidden_iterator = iter(forbidden_pairs)
    first_pair = next(forbidden_iterator, None)
    if first_pair is None:
        return True
    if len(first_pair) != arity:
        raise TypeError("forbidden tuple has the wrong arity")
    values.extend(first_pair)
    for pair in forbidden_iterator:
        if len(pair) != arity:
            raise TypeError("forbidden tuple has the wrong arity")
        values.extend(pair)
    return True


def overlap(first, second):
    return (
        _masks_overlap(first.days, second.days)
        and _masks_overlap(first.weeks, second.weeks)
        and _intervals_overlap(first.start, first.length, second.start, second.length)
    )


def _set_bit_indices(mask: int):
    while mask:
        least_bit = mask & -mask
        yield least_bit.bit_length() - 1
        mask ^= least_bit


def occurrences(option):
    for week, week_active in enumerate(option.weeks):
        if week_active != "1":
            continue
        for day, day_active in enumerate(option.days):
            if day_active != "1":
                continue
            for slot in range(option.start, option.start + option.length):
                yield week, day, slot


def _add_room_assignment_hint(model, variable, best_code, room_codes):
    """Hint only genuine room choices, not CP-SAT's deduplicated constants."""

    if len(room_codes) > 1:
        model.add_hint(variable, best_code)


def _adaptive_construction_stage_cap(
    total_budget_seconds: float,
    *,
    base_cap_seconds: float,
    extended_budget_share: float,
    hard_cap_seconds: float = 300.0,
) -> float:
    """Let explicitly longer research runs spend their extra time constructing.

    The published 120-second condition retains its proven caps exactly.  Longer
    caller budgets previously had no effect because every constructive phase
    remained fixed at 15/45 seconds; the solver therefore repeated the same
    incomplete search and returned early.  Allocate only a bounded share of the
    budget above 120 seconds so room assignment, sectioning, and serialization
    still retain the remainder.
    """

    if total_budget_seconds <= 0:
        return 0.0
    extra = max(0.0, float(total_budget_seconds) - 120.0)
    return min(
        float(hard_cap_seconds),
        float(base_cap_seconds) + extra * float(extended_budget_share),
    )


def _construction_stage_window(
    *,
    total_budget_seconds: float,
    stage_started: float,
    absolute_deadline: float,
    base_cap_seconds: float,
    extended_budget_share: float,
    minimum_stage_seconds: float,
) -> tuple[float, float]:
    """Return the bounded stage budget and its reserve-safe deadline."""

    remaining = max(0.0, absolute_deadline - stage_started)
    stage_budget = min(
        _adaptive_construction_stage_cap(
            total_budget_seconds,
            base_cap_seconds=base_cap_seconds,
            extended_budget_share=extended_budget_share,
        ),
        max(float(minimum_stage_seconds), remaining * 0.5),
    )
    repair_deadline = min(
        absolute_deadline - min(3.0, max(0.05, remaining * 0.1)),
        stage_started + stage_budget,
    )
    return stage_budget, repair_deadline


def construct_itc2019_decomposed(
    problem: ITC2019Problem,
    *,
    deadline: float,
    workers: int = 4,
    random_seed: int = 17,
    joint_construction: bool = False,
    objective_problem: ITC2019Problem | None = None,
    diagnostics: dict | None = None,
):
    construction_started = time.monotonic()
    total_construction_budget = max(0.0, deadline - construction_started)
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics["requested_construction_budget_seconds"] = total_construction_budget
    domains = _build_factorized_domains(problem, deadline=deadline)
    blocked_by_room = {}
    for room in problem.rooms:
        blocked = 0
        for unavailable in room.unavailable:
            for week, day, slot in occurrences(unavailable):
                bit = (week * problem.nr_days + day) * problem.slots_per_day + slot
                blocked |= 1 << bit
        blocked_by_room[room.id] = blocked
    time_mask_cache = {}
    time_domains = {}
    supported_rooms = {}
    pressure_masks = {}
    supported_room_pool = {}
    full_time_masks = {}
    for klass in problem.classes:
        admitted_times = []
        allowed_rooms = {
            option.room_id for option in domains.rooms[klass.id] if option is not None
        }
        roomless = all(option is None for option in domains.rooms[klass.id])
        for time_option in domains.times[klass.id]:
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
            rooms = tuple(
                room_id
                for room_id in sorted(allowed_rooms)
                if not blocked_by_room[room_id] & time_mask
            )
            rooms = supported_room_pool.setdefault(rooms, rooms)
            if not rooms and not roomless:
                continue
            option_index = len(admitted_times)
            admitted_times.append(time_option)
            pressure_mask = sum(
                1 << (day * problem.slots_per_day + slot)
                for day, active in enumerate(time_option.days)
                if active == "1"
                for slot in range(
                    time_option.start, time_option.start + time_option.length
                )
            )
            supported_rooms[(klass.id, option_index)] = rooms
            pressure_masks[(klass.id, option_index)] = pressure_mask
            full_time_masks[(klass.id, option_index)] = time_mask
        if not admitted_times:
            return None
        time_domains[klass.id] = tuple(admitted_times)

    neighbors = {klass.id: set() for klass in problem.classes}
    hard_pair_rules = defaultdict(list)
    hard_group_rules = []
    groups_by_class = defaultdict(list)
    for distribution in problem.distributions:
        base, parameters = _distribution_spec(distribution.type)
        if not distribution.required:
            continue
        if base in {"MaxDays", "MaxDayLoad", "MaxBreaks", "MaxBlock"}:
            class_ids = tuple(dict.fromkeys(distribution.class_ids))
            group = (base, parameters, class_ids)
            hard_group_rules.append(group)
            for class_id in class_ids:
                groups_by_class[class_id].append(group)
            continue
        if base not in _PAIR_DISTRIBUTIONS:
            continue
        for first_id, second_id in combinations(
            dict.fromkeys(distribution.class_ids), 2
        ):
            neighbors[first_id].add(second_id)
            neighbors[second_id].add(first_id)
            canonical = tuple(sorted((first_id, second_id)))
            hard_pair_rules[canonical].append(
                (base, parameters, first_id != canonical[0])
            )

    travel = _travel_values(problem)
    room_sensitive_bases = {"SameRoom", "DifferentRoom", "SameAttendees"}
    time_pair_cache = _BoundedPredicateCache(
        max_entries=DEFAULT_MAX_TIME_PAIR_CACHE_ENTRIES
    )

    def time_signature(option):
        return option.days, option.start, option.length, option.weeks

    time_domain_signatures = {
        class_id: tuple(time_signature(option) for option in options)
        for class_id, options in time_domains.items()
    }

    def pair_rules(first_id, second_id):
        canonical = tuple(sorted((first_id, second_id)))
        return hard_pair_rules.get(canonical, ()), first_id != canonical[0]

    def hard_pair_valid(
        first_id,
        first_option,
        first_room,
        second_id,
        second_option,
        second_room,
    ):
        rules, reversed_order = pair_rules(first_id, second_id)
        first_placement = ITC2019ClassPlacement(
            class_id=first_id,
            days=first_option.days,
            start=first_option.start,
            weeks=first_option.weeks,
            room_id=first_room,
        )
        second_placement = ITC2019ClassPlacement(
            class_id=second_id,
            days=second_option.days,
            start=second_option.start,
            weeks=second_option.weeks,
            room_id=second_room,
        )
        for base, parameters, defined_reversed in rules:
            if defined_reversed != reversed_order:
                valid = _pair_distribution_satisfied(
                    base,
                    parameters,
                    second_placement,
                    second_option,
                    first_placement,
                    first_option,
                    travel,
                )
            else:
                valid = _pair_distribution_satisfied(
                    base,
                    parameters,
                    first_placement,
                    first_option,
                    second_placement,
                    second_option,
                    travel,
                )
            if not valid:
                return False
        return True

    def evaluate_time_pair_valid(first_id, first_option, second_id, second_option):
        rules, reversed_order = pair_rules(first_id, second_id)
        first_placement = ITC2019ClassPlacement(
            class_id=first_id,
            days=first_option.days,
            start=first_option.start,
            weeks=first_option.weeks,
            room_id=None,
        )
        second_placement = ITC2019ClassPlacement(
            class_id=second_id,
            days=second_option.days,
            start=second_option.start,
            weeks=second_option.weeks,
            room_id=None,
        )
        for base, parameters, defined_reversed in rules:
            if base in {"SameRoom", "DifferentRoom"}:
                continue
            if defined_reversed != reversed_order:
                valid = _pair_distribution_satisfied(
                    base,
                    parameters,
                    second_placement,
                    second_option,
                    first_placement,
                    first_option,
                    {},
                )
            else:
                valid = _pair_distribution_satisfied(
                    base,
                    parameters,
                    first_placement,
                    first_option,
                    second_placement,
                    second_option,
                    {},
                )
            if not valid:
                return False
        return True

    def time_pair_valid(first_id, first_option, second_id, second_option):
        rules, reversed_order = pair_rules(first_id, second_id)
        cache_key = (
            tuple(rules),
            reversed_order,
            time_signature(first_option),
            time_signature(second_option),
        )
        return time_pair_cache.resolve(
            cache_key,
            lambda: evaluate_time_pair_valid(
                first_id,
                first_option,
                second_id,
                second_option,
            ),
        )

    option_matrix_cache = {}
    edge_option_masks = {}

    def allowed_option_masks(first_id, second_id):
        edge_key = (first_id, second_id)
        cached_edge = edge_option_masks.get(edge_key)
        if cached_edge is not None:
            return cached_edge
        rules, reversed_order = pair_rules(first_id, second_id)
        matrix_key = (
            tuple(rules),
            reversed_order,
            time_domain_signatures[first_id],
            time_domain_signatures[second_id],
        )
        rows = option_matrix_cache.get(matrix_key)
        if rows is None:
            rows = _build_compact_allowed_option_masks(
                len(time_domains[first_id]),
                len(time_domains[second_id]),
                lambda first_index, second_index: evaluate_time_pair_valid(
                        first_id,
                        time_domains[first_id][first_index],
                        second_id,
                        time_domains[second_id][second_index],
                    ),
                deadline=deadline - 1.0,
            )
            option_matrix_cache[matrix_key] = rows
        edge_option_masks[edge_key] = rows
        return rows

    room_penalties_by_class = {
        klass.id: {
            room_option.room_id: room_option.penalty
            for room_option in domains.rooms[klass.id]
            if room_option is not None
        }
        for klass in problem.classes
    }
    course_by_class = {
        klass.id: course.id
        for course in problem.courses
        for configuration in course.configurations
        for subpart in configuration.subparts
        for klass in subpart.classes
    }
    classes_by_course = defaultdict(list)
    for class_id, course_id in course_by_class.items():
        classes_by_course[course_id].append(class_id)
    student_course_weights = defaultdict(lambda: defaultdict(int))
    if objective_problem is not None:
        for student in objective_problem.students:
            course_ids = tuple(dict.fromkeys(student.course_ids))
            for first_course, second_course in combinations(course_ids, 2):
                student_course_weights[first_course][second_course] += 1
                student_course_weights[second_course][first_course] += 1
    strongest_student_partners = {
        course_id: tuple(
            sorted(partners.items(), key=lambda item: (-item[1], item[0]))[:32]
        )
        for course_id, partners in student_course_weights.items()
    }

    def student_overlap_pressure(class_id, option, assigned):
        course_id = course_by_class[class_id]
        partners = strongest_student_partners.get(course_id, ())
        if not partners:
            return 0
        return sum(
            weight
            for partner_course, weight in partners
            for other_id in classes_by_course[partner_course]
            if other_id in assigned
            and other_id != class_id
            and overlap(option, assigned[other_id][1])
        )

    def solve_fixed_time_rooms_for(
        selected_mapping,
        *,
        max_seconds,
        diagnostic_key=None,
    ):
        """Complete one exact time seed with rooms without changing its times."""

        if max_seconds <= 0.0:
            return None
        selected_times = {
            class_id: pair[1] for class_id, pair in selected_mapping.items()
        }
        room_model = cp_model.CpModel()
        global_room_codes = {room.id: index for index, room in enumerate(problem.rooms)}
        room_variables = {}
        room_by_code = {}
        room_code_domains = {}
        room_costs = []
        occupancy_variables = defaultdict(list)
        for class_offset, class_id in enumerate(sorted(selected_mapping)):
            option_index, option = selected_mapping[class_id]
            room_ids = supported_rooms[(class_id, option_index)] or (None,)
            codes = []
            penalties = room_penalties_by_class[class_id]
            for room_id in room_ids:
                code = (
                    global_room_codes[room_id]
                    if room_id is not None
                    else len(global_room_codes) + class_offset
                )
                codes.append(code)
                room_by_code[(class_id, code)] = room_id
            room_code_domains[class_id] = tuple(codes)
            if len(codes) == 1:
                variable = room_model.new_constant(codes[0])
            else:
                variable = room_model.new_int_var_from_domain(
                    cp_model.Domain.from_values(codes), f"room_{class_id}"
                )
            room_variables[class_id] = variable
            maximum_penalty = max(penalties.values(), default=0)
            cost = room_model.new_int_var(0, maximum_penalty, f"room_cost_{class_id}")
            room_model.add_allowed_assignments(
                (variable, cost),
                (
                    (code, penalties.get(room_by_code[(class_id, code)], 0))
                    for code in codes
                ),
            )
            room_costs.append(cost)
            best_code = min(
                codes,
                key=lambda code: (
                    penalties.get(room_by_code[(class_id, code)], 0),
                    code,
                ),
            )
            _add_room_assignment_hint(room_model, variable, best_code, codes)
            for occurrence in occurrences(option):
                occupancy_variables[occurrence].append(variable)

        for variables in occupancy_variables.values():
            if len(variables) > 1:
                room_model.add_all_different(variables)

        for first_id, second_id in hard_pair_rules:
            rules, _reversed_order = pair_rules(first_id, second_id)
            if not any(
                base in room_sensitive_bases
                for base, _parameters, _defined_reversed in rules
            ):
                continue
            forbidden = []
            for first_code in room_code_domains[first_id]:
                for second_code in room_code_domains[second_id]:
                    if not hard_pair_valid(
                        first_id,
                        selected_times[first_id],
                        room_by_code[(first_id, first_code)],
                        second_id,
                        selected_times[second_id],
                        room_by_code[(second_id, second_code)],
                    ):
                        forbidden.append((first_code, second_code))
            if forbidden:
                room_model.add_forbidden_assignments(
                    (room_variables[first_id], room_variables[second_id]), forbidden
                )
        room_model.minimize(sum(room_costs))
        room_solver = cp_model.CpSolver()
        room_solver.parameters.max_time_in_seconds = max(0.01, max_seconds)
        room_solver.parameters.num_search_workers = workers
        room_solver.parameters.random_seed = random_seed
        room_status = room_solver.solve(room_model)
        if diagnostic_key is not None:
            diagnostics[diagnostic_key] = room_solver.status_name(room_status)
        if room_status not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
            return None
        assigned = {
            class_id: room_by_code[
                (class_id, int(room_solver.value(room_variables[class_id])))
            ]
            for class_id in room_variables
        }
        candidate = tuple(
            ITC2019ClassPlacement(
                class_id=klass.id,
                days=selected_times[klass.id].days,
                start=selected_times[klass.id].start,
                weeks=selected_times[klass.id].weeks,
                room_id=assigned[klass.id],
            )
            for klass in problem.classes
        )
        return (
            candidate if not validate_itc2019_solution(problem, candidate, {}) else None
        )

    def construct_time_min_conflicts():
        repair_started = time.monotonic()
        # Time-only repair is a seed for the joint time/room constructor, not the
        # terminal search.  On very large sparse instances it can keep reducing
        # pair residuals without reaching zero and previously consumed the whole
        # condition, leaving no opportunity for the stronger joint repair.
        _stage_budget, repair_deadline = _construction_stage_window(
            total_budget_seconds=total_construction_budget,
            stage_started=repair_started,
            absolute_deadline=deadline,
            base_cap_seconds=(
                15.0
                if (objective_problem is not None and objective_problem.students)
                else 45.0
            ),
            extended_budget_share=0.20,
            minimum_stage_seconds=2.0,
        )
        best_conflicts = 10**9
        best_assignment = None
        total_iterations = 0

        def group_conflicts_for(class_id, option, assigned):
            total = 0
            for base, parameters, class_ids in groups_by_class[class_id]:
                if any(
                    other_id != class_id and other_id not in assigned
                    for other_id in class_ids
                ):
                    continue
                resolved = {
                    other_id: option if other_id == class_id else assigned[other_id][1]
                    for other_id in class_ids
                }
                total += _special_distribution_units(
                    problem, base, parameters, class_ids, resolved
                )
            return total

        def sampled_indices(class_id, rng, *, current_index=None, limit=64):
            options = time_domains[class_id]
            if len(options) <= limit:
                return tuple(range(len(options)))
            selected = {
                index
                for index, _option in sorted(
                    enumerate(options),
                    key=lambda item: (item[1].penalty, item[0]),
                )[:16]
            }
            if current_index is not None:
                selected.add(current_index)
            spread_count = 16
            selected.update(
                round(offset * (len(options) - 1) / (spread_count - 1))
                for offset in range(spread_count)
            )
            remaining = [
                index for index in range(len(options)) if index not in selected
            ]
            rng.shuffle(remaining)
            selected.update(remaining[: max(0, limit - len(selected))])
            return tuple(sorted(selected))

        def build_conflict_state(assigned):
            degrees = defaultdict(int)
            pair_state = {}
            group_state = {}
            pair_total = 0
            group_total = 0
            for first_id, second_id in hard_pair_rules:
                violated = not time_pair_valid(
                    first_id,
                    assigned[first_id][1],
                    second_id,
                    assigned[second_id][1],
                )
                pair_state[tuple(sorted((first_id, second_id)))] = violated
                if violated:
                    degrees[first_id] += 1
                    degrees[second_id] += 1
                    pair_total += 1
            resolved = {class_id: values[1] for class_id, values in assigned.items()}
            for group in hard_group_rules:
                base, parameters, class_ids = group
                units = _special_distribution_units(
                    problem, base, parameters, class_ids, resolved
                )
                group_state[group] = units
                if units:
                    group_total += units
                    for class_id in class_ids:
                        degrees[class_id] += units
            return (
                pair_total + group_total,
                degrees,
                pair_state,
                group_state,
                pair_total,
                group_total,
            )

        for restart in range(10):
            if time.monotonic() >= repair_deadline:
                break
            rng = random.Random(random_seed + 110503 + restart * 65537)
            assigned = {}
            for class_id in sorted(
                time_domains,
                key=lambda item: (-len(neighbors[item]), len(time_domains[item]), item),
            ):
                choices = []
                for option_index in sampled_indices(class_id, rng):
                    option = time_domains[class_id][option_index]
                    pair_conflicts = sum(
                        not time_pair_valid(
                            class_id,
                            option,
                            neighbor,
                            assigned[neighbor][1],
                        )
                        for neighbor in neighbors[class_id]
                        if neighbor in assigned
                    )
                    choices.append(
                        (
                            pair_conflicts
                            + group_conflicts_for(class_id, option, assigned),
                            student_overlap_pressure(class_id, option, assigned),
                            option.penalty,
                            rng.random(),
                            option_index,
                            option,
                        )
                    )
                chosen = min(choices)
                assigned[class_id] = (chosen[-2], chosen[-1])

            tabu = {}
            stagnant = 0
            (
                conflict_total,
                degrees,
                pair_state,
                group_state,
                pair_total,
                group_total,
            ) = build_conflict_state(assigned)
            for iteration in range(50000):
                total_iterations += 1
                if iteration % 8 == 0 and time.monotonic() >= repair_deadline:
                    break
                if conflict_total < best_conflicts:
                    best_conflicts = conflict_total
                    best_assignment = dict(assigned)
                    diagnostics["time_min_conflicts_breakdown"] = {
                        "pair_time": pair_total,
                        "group": group_total,
                    }
                    stagnant = 0
                else:
                    stagnant += 1
                if conflict_total == 0:
                    diagnostics["time_min_conflicts_restarts"] = restart + 1
                    diagnostics["time_min_conflicts_iterations"] = total_iterations
                    diagnostics["time_min_conflicts_best"] = 0
                    return dict(assigned)
                worst = max(degrees.values())
                roots = [
                    class_id for class_id, value in degrees.items() if value == worst
                ]
                class_id = roots[rng.randrange(len(roots))]
                old_index, _old_option = assigned[class_id]
                search_limit = 192 if stagnant > 80 and iteration % 48 == 0 else 72
                choices = []
                for option_index in sampled_indices(
                    class_id,
                    rng,
                    current_index=old_index,
                    limit=search_limit,
                ):
                    option = time_domains[class_id][option_index]
                    local_conflicts = sum(
                        not time_pair_valid(
                            class_id,
                            option,
                            neighbor,
                            assigned[neighbor][1],
                        )
                        for neighbor in neighbors[class_id]
                    ) + group_conflicts_for(class_id, option, assigned)
                    choices.append(
                        (
                            int(
                                tabu.get((class_id, option_index), -1)
                                > total_iterations
                                and local_conflicts >= worst
                            ),
                            local_conflicts,
                            student_overlap_pressure(class_id, option, assigned),
                            option.penalty,
                            rng.random(),
                            option_index,
                            option,
                        )
                    )
                choices.sort()
                feasibility_key = choices[0][:2]
                choice_pool = [
                    choice for choice in choices if choice[:2] == feasibility_key
                ]
                chosen = choice_pool[rng.randrange(len(choice_pool))]
                new_index, new_option = chosen[-2], chosen[-1]
                for neighbor in neighbors[class_id]:
                    edge_key = tuple(sorted((class_id, neighbor)))
                    old_violated = pair_state[edge_key]
                    new_violated = not time_pair_valid(
                        class_id,
                        new_option,
                        neighbor,
                        assigned[neighbor][1],
                    )
                    if old_violated == new_violated:
                        continue
                    delta = 1 if new_violated else -1
                    pair_state[edge_key] = new_violated
                    pair_total += delta
                    conflict_total += delta
                    degrees[class_id] += delta
                    degrees[neighbor] += delta
                for group in groups_by_class[class_id]:
                    base, parameters, class_ids = group
                    old_units = group_state[group]
                    resolved = {
                        other_id: (
                            new_option
                            if other_id == class_id
                            else assigned[other_id][1]
                        )
                        for other_id in class_ids
                    }
                    new_units = _special_distribution_units(
                        problem, base, parameters, class_ids, resolved
                    )
                    delta = new_units - old_units
                    if not delta:
                        continue
                    group_state[group] = new_units
                    group_total += delta
                    conflict_total += delta
                    for other_id in class_ids:
                        degrees[other_id] += delta
                assigned[class_id] = (new_index, new_option)
                tabu[(class_id, old_index)] = total_iterations + 7 + rng.randrange(11)
                if stagnant > 120:
                    kick_roots = sorted(
                        degrees, key=lambda item: (-degrees[item], item)
                    )[: min(16, len(degrees))]
                    for kick_id in kick_roots:
                        current_index = assigned[kick_id][0]
                        indices = sampled_indices(
                            kick_id,
                            rng,
                            current_index=current_index,
                            limit=96,
                        )
                        replacement_index = indices[rng.randrange(len(indices))]
                        assigned[kick_id] = (
                            replacement_index,
                            time_domains[kick_id][replacement_index],
                        )
                    (
                        conflict_total,
                        degrees,
                        pair_state,
                        group_state,
                        pair_total,
                        group_total,
                    ) = build_conflict_state(assigned)
                    stagnant = 0
                    tabu.clear()
        diagnostics["time_min_conflicts_restarts"] = restart + 1
        diagnostics["time_min_conflicts_iterations"] = total_iterations
        diagnostics["time_min_conflicts_best"] = best_conflicts
        if best_assignment is not None:
            diagnostics["time_min_conflicts_seed_residual"] = best_conflicts
        if best_assignment is not None and best_conflicts > 0:
            closure_deadline = min(deadline - 3.0, time.monotonic() + 5.0)
            (
                _total,
                _degrees,
                pair_state,
                group_state,
                _pair_total,
                _group_total,
            ) = build_conflict_state(best_assignment)
            violated_edges = [edge for edge, violated in pair_state.items() if violated]
            for first_id, second_id in violated_edges:
                moved_ids = {first_id, second_id}
                affected_edges = {
                    tuple(sorted((class_id, neighbor)))
                    for class_id in moved_ids
                    for neighbor in neighbors[class_id]
                }
                affected_groups = {
                    group
                    for class_id in moved_ids
                    for group in groups_by_class[class_id]
                }
                before_local = sum(pair_state[edge] for edge in affected_edges) + sum(
                    group_state[group] for group in affected_groups
                )
                first_indices = sorted(
                    range(len(time_domains[first_id])),
                    key=lambda index: (time_domains[first_id][index].penalty, index),
                )
                second_indices = sorted(
                    range(len(time_domains[second_id])),
                    key=lambda index: (time_domains[second_id][index].penalty, index),
                )
                checked = 0
                for first_index in first_indices:
                    first_option = time_domains[first_id][first_index]
                    for second_index in second_indices:
                        checked += 1
                        if checked % 256 == 0 and time.monotonic() >= closure_deadline:
                            break
                        second_option = time_domains[second_id][second_index]
                        overrides = {
                            first_id: first_option,
                            second_id: second_option,
                        }
                        after_local = 0
                        for edge_first, edge_second in affected_edges:
                            if not time_pair_valid(
                                edge_first,
                                overrides.get(
                                    edge_first, best_assignment[edge_first][1]
                                ),
                                edge_second,
                                overrides.get(
                                    edge_second, best_assignment[edge_second][1]
                                ),
                            ):
                                after_local += 1
                        for base, parameters, class_ids in affected_groups:
                            resolved = {
                                class_id: overrides.get(
                                    class_id, best_assignment[class_id][1]
                                )
                                for class_id in class_ids
                            }
                            after_local += _special_distribution_units(
                                problem,
                                base,
                                parameters,
                                class_ids,
                                resolved,
                            )
                        if best_conflicts - before_local + after_local == 0:
                            closed = dict(best_assignment)
                            closed[first_id] = (first_index, first_option)
                            closed[second_id] = (second_index, second_option)
                            diagnostics["time_pair_closure_candidates"] = checked
                            diagnostics["time_min_conflicts_best"] = 0
                            return closed
                    if time.monotonic() >= closure_deadline:
                        break
                if time.monotonic() >= closure_deadline:
                    break
        return best_assignment

    def construct_joint_min_conflicts(initial_times=None):
        repair_started = time.monotonic()
        _stage_budget, repair_deadline = _construction_stage_window(
            total_budget_seconds=total_construction_budget,
            stage_started=repair_started,
            absolute_deadline=deadline,
            base_cap_seconds=45.0,
            extended_budget_share=0.25,
            minimum_stage_seconds=5.0,
        )
        best_conflicts = 10**9
        best_assignment = None
        total_iterations = 0

        def sampled_time_indices(class_id, rng, *, current_index=None, limit=36):
            """Return a small, deterministic cross-section of a large time domain.

            Several competition instances expose hundreds or thousands of legal
            time choices per class.  Evaluating every time-room combination in a
            min-conflicts step makes the constructor quadratic before it has a
            first incumbent.  Keep the best static choices, an even structural
            spread, the incumbent choice, and a seeded random sample instead.
            """

            options = time_domains[class_id]
            if len(options) <= limit:
                return tuple(range(len(options)))
            selected = {
                index
                for index, _option in sorted(
                    enumerate(options),
                    key=lambda item: (item[1].penalty, item[0]),
                )[:10]
            }
            if current_index is not None:
                selected.add(current_index)
            spread_count = 10
            denominator = max(1, spread_count - 1)
            selected.update(
                round(offset * (len(options) - 1) / denominator)
                for offset in range(spread_count)
            )
            remaining = [
                index for index in range(len(options)) if index not in selected
            ]
            rng.shuffle(remaining)
            selected.update(remaining[: max(0, limit - len(selected))])
            return tuple(sorted(selected))

        def sampled_rooms(class_id, option_index, rng, *, current_room=None):
            rooms = supported_rooms[(class_id, option_index)] or (None,)
            limit = 10
            if len(rooms) <= limit:
                return rooms
            penalties = room_penalties_by_class[class_id]
            selected = set(
                sorted(rooms, key=lambda room_id: (penalties.get(room_id, 0), room_id))[
                    :5
                ]
            )
            if current_room in rooms:
                selected.add(current_room)
            remaining = [room_id for room_id in rooms if room_id not in selected]
            rng.shuffle(remaining)
            selected.update(remaining[: max(0, limit - len(selected))])
            return tuple(
                sorted(selected, key=lambda room_id: (room_id is None, room_id))
            )

        def group_conflicts_for(class_id, option, assigned):
            total = 0
            for base, parameters, class_ids in groups_by_class[class_id]:
                if any(
                    other_id != class_id and other_id not in assigned
                    for other_id in class_ids
                ):
                    continue
                resolved = {
                    other_id: (
                        option if other_id == class_id else assigned[other_id][1]
                    )
                    for other_id in class_ids
                }
                total += _special_distribution_units(
                    problem, base, parameters, class_ids, resolved
                )
            return total

        def build_joint_conflict_state(assigned, room_members):
            degrees = defaultdict(int)
            pair_state = {}
            group_state = {}
            room_total = 0
            pair_total = 0
            pair_time_total = 0
            pair_room_total = 0
            group_total = 0
            for room_id, class_ids in room_members.items():
                if room_id is None:
                    continue
                ordered = sorted(class_ids)
                for offset, first_id in enumerate(ordered):
                    first_mask = full_time_masks[(first_id, assigned[first_id][0])]
                    for second_id in ordered[offset + 1 :]:
                        if (
                            first_mask
                            & full_time_masks[(second_id, assigned[second_id][0])]
                        ):
                            degrees[first_id] += 1
                            degrees[second_id] += 1
                            room_total += 1
            for first_id, second_id in hard_pair_rules:
                violated = not hard_pair_valid(
                    first_id,
                    assigned[first_id][1],
                    assigned[first_id][2],
                    second_id,
                    assigned[second_id][1],
                    assigned[second_id][2],
                )
                kind = None
                if violated:
                    kind = (
                        "room"
                        if time_pair_valid(
                            first_id,
                            assigned[first_id][1],
                            second_id,
                            assigned[second_id][1],
                        )
                        else "time"
                    )
                    degrees[first_id] += 1
                    degrees[second_id] += 1
                    pair_total += 1
                    if kind == "room":
                        pair_room_total += 1
                    else:
                        pair_time_total += 1
                pair_state[tuple(sorted((first_id, second_id)))] = kind
            resolved = {class_id: values[1] for class_id, values in assigned.items()}
            for group in hard_group_rules:
                base, parameters, class_ids = group
                units = _special_distribution_units(
                    problem, base, parameters, class_ids, resolved
                )
                group_state[group] = units
                if units:
                    group_total += units
                    for class_id in class_ids:
                        degrees[class_id] += units
            return (
                room_total + pair_total + group_total,
                degrees,
                pair_state,
                group_state,
                room_total,
                pair_total,
                pair_time_total,
                pair_room_total,
                group_total,
            )

        def polish_student_pressure(assigned, room_members, rng):
            if not strongest_student_partners:
                return assigned
            weights = (objective_problem or problem).optimization
            accepted = 0
            passes = 0
            # This course-level proxy is useful for selecting a better first
            # feasible basin, but it is intentionally coarse.  Do not let it
            # consume the sectioning and concrete-conflict quality budget after
            # hard feasibility has already been established.
            polish_deadline = min(repair_deadline, time.monotonic() + 10.0)
            while time.monotonic() < polish_deadline:
                passes += 1
                improved = False
                roots = sorted(
                    assigned,
                    key=lambda class_id: (
                        -student_overlap_pressure(
                            class_id, assigned[class_id][1], assigned
                        ),
                        class_id,
                    ),
                )
                for class_id in roots:
                    if time.monotonic() >= polish_deadline:
                        break
                    old_index, old_option, old_room = assigned[class_id]
                    current_score = (
                        student_overlap_pressure(class_id, old_option, assigned)
                        * weights.student
                        + old_option.penalty * weights.time
                        + room_penalties_by_class[class_id].get(old_room, 0)
                        * weights.room
                    )
                    room_members[old_room].remove(class_id)
                    choices = []
                    for option_index in sampled_time_indices(
                        class_id,
                        rng,
                        current_index=old_index,
                        limit=96,
                    ):
                        option = time_domains[class_id][option_index]
                        time_mask = full_time_masks[(class_id, option_index)]
                        for room_id in sampled_rooms(
                            class_id,
                            option_index,
                            rng,
                            current_room=(
                                old_room if option_index == old_index else None
                            ),
                        ):
                            if room_id is not None and any(
                                time_mask
                                & full_time_masks[(other_id, assigned[other_id][0])]
                                for other_id in room_members[room_id]
                            ):
                                continue
                            if any(
                                not hard_pair_valid(
                                    class_id,
                                    option,
                                    room_id,
                                    neighbor,
                                    assigned[neighbor][1],
                                    assigned[neighbor][2],
                                )
                                for neighbor in neighbors[class_id]
                            ):
                                continue
                            if group_conflicts_for(class_id, option, assigned):
                                continue
                            score = (
                                student_overlap_pressure(class_id, option, assigned)
                                * weights.student
                                + option.penalty * weights.time
                                + room_penalties_by_class[class_id].get(room_id, 0)
                                * weights.room
                            )
                            if score < current_score:
                                choices.append(
                                    (
                                        score,
                                        option.penalty,
                                        room_penalties_by_class[class_id].get(
                                            room_id, 0
                                        ),
                                        option_index,
                                        option,
                                        room_id,
                                    )
                                )
                    if choices:
                        chosen = min(choices)
                        assigned[class_id] = (chosen[-3], chosen[-2], chosen[-1])
                        room_members[chosen[-1]].add(class_id)
                        accepted += 1
                        improved = True
                        break
                    room_members[old_room].add(class_id)
                if not improved:
                    break
            diagnostics["joint_student_pressure_passes"] = passes
            diagnostics["joint_student_pressure_moves"] = accepted
            return assigned

        for restart in range(8):
            if time.monotonic() >= repair_deadline:
                break
            rng = random.Random(random_seed + 170003 + restart * 65537)
            assigned = {}
            room_members = defaultdict(set)
            occupancy_pressure = defaultdict(int)
            for class_id in sorted(
                time_domains,
                key=lambda item: (
                    -len(neighbors[item]),
                    len(time_domains[item]),
                    item,
                ),
            ):
                candidates = []
                initial_index = (
                    initial_times[class_id][0]
                    if restart == 0 and initial_times is not None
                    else None
                )
                time_indices = (
                    (initial_index,)
                    if initial_index is not None
                    else sampled_time_indices(class_id, rng)
                )
                for option_offset, option_index in enumerate(time_indices):
                    if option_offset % 8 == 0 and time.monotonic() >= repair_deadline:
                        diagnostics["joint_deadline_exhausted"] = True
                        return None
                    option = time_domains[class_id][option_index]
                    time_mask = full_time_masks[(class_id, option_index)]
                    pressure_mask = pressure_masks[(class_id, option_index)]
                    student_pressure = student_overlap_pressure(
                        class_id, option, assigned
                    )
                    group_conflicts = group_conflicts_for(class_id, option, assigned)
                    time_pair_conflicts = 0
                    room_sensitive_neighbors = []
                    for neighbor in neighbors[class_id]:
                        if neighbor not in assigned:
                            continue
                        if not time_pair_valid(
                            class_id,
                            option,
                            neighbor,
                            assigned[neighbor][1],
                        ):
                            time_pair_conflicts += 1
                        elif any(
                            base in room_sensitive_bases
                            for base, _parameters, _defined_reversed in pair_rules(
                                class_id, neighbor
                            )[0]
                        ):
                            room_sensitive_neighbors.append(neighbor)
                    for room_id in sampled_rooms(class_id, option_index, rng):
                        collisions = (
                            sum(
                                bool(
                                    time_mask
                                    & full_time_masks[(other_id, assigned[other_id][0])]
                                )
                                for other_id in room_members[room_id]
                            )
                            if room_id is not None
                            else 0
                        )
                        pair_conflicts = time_pair_conflicts
                        for neighbor_offset, neighbor in enumerate(
                            room_sensitive_neighbors
                        ):
                            if (
                                neighbor_offset % 16 == 0
                                and time.monotonic() >= repair_deadline
                            ):
                                diagnostics["joint_deadline_exhausted"] = True
                                return None
                            pair_conflicts += not hard_pair_valid(
                                class_id,
                                option,
                                room_id,
                                neighbor,
                                assigned[neighbor][1],
                                assigned[neighbor][2],
                            )
                        candidates.append(
                            (
                                collisions + pair_conflicts + group_conflicts,
                                student_pressure,
                                sum(
                                    (occupancy_pressure[slot] + 1) ** 2
                                    for slot in _set_bit_indices(pressure_mask)
                                ),
                                option.penalty,
                                room_penalties_by_class[class_id].get(room_id, 0),
                                rng.random(),
                                option_index,
                                option,
                                room_id,
                                pressure_mask,
                            )
                        )
                candidates.sort()
                chosen = candidates[rng.randrange(min(3, len(candidates)))]
                option_index, option, room_id, pressure_mask = chosen[-4:]
                assigned[class_id] = (option_index, option, room_id)
                room_members[room_id].add(class_id)
                for slot in _set_bit_indices(pressure_mask):
                    occupancy_pressure[slot] += 1

            tabu = {}
            stagnant = 0
            (
                conflict_total,
                degrees,
                pair_state,
                group_state,
                room_total,
                pair_total,
                pair_time_total,
                pair_room_total,
                group_total,
            ) = build_joint_conflict_state(assigned, room_members)
            for iteration in range(50000):
                total_iterations += 1
                if iteration % 8 == 0 and time.monotonic() >= repair_deadline:
                    break
                if conflict_total < best_conflicts:
                    best_conflicts = conflict_total
                    best_assignment = dict(assigned)
                    diagnostics["joint_min_conflicts_breakdown"] = {
                        "room": room_total,
                        "pair": pair_total,
                        "pair_time": pair_time_total,
                        "pair_room": pair_room_total,
                        "group": group_total,
                    }
                    stagnant = 0
                else:
                    stagnant += 1
                if conflict_total == 0:
                    assigned = polish_student_pressure(assigned, room_members, rng)
                    candidate = tuple(
                        ITC2019ClassPlacement(
                            class_id=klass.id,
                            days=assigned[klass.id][1].days,
                            start=assigned[klass.id][1].start,
                            weeks=assigned[klass.id][1].weeks,
                            room_id=assigned[klass.id][2],
                        )
                        for klass in problem.classes
                    )
                    if not validate_itc2019_solution(problem, candidate, {}):
                        diagnostics["joint_min_conflicts_restarts"] = restart + 1
                        diagnostics["joint_min_conflicts_iterations"] = total_iterations
                        diagnostics["joint_min_conflicts_best"] = 0
                        return candidate
                worst = max(degrees.values())
                roots = [
                    class_id for class_id, value in degrees.items() if value == worst
                ]
                class_id = roots[rng.randrange(len(roots))]
                old_index, old_option, old_room = assigned[class_id]
                room_members[old_room].remove(class_id)
                choices = []
                search_limit = 216 if stagnant > 80 and iteration % 48 == 0 else 72
                for option_offset, option_index in enumerate(
                    sampled_time_indices(
                        class_id,
                        rng,
                        current_index=old_index,
                        limit=search_limit,
                    )
                ):
                    if option_offset % 8 == 0 and time.monotonic() >= repair_deadline:
                        diagnostics["joint_deadline_exhausted"] = True
                        return None
                    option = time_domains[class_id][option_index]
                    time_mask = full_time_masks[(class_id, option_index)]
                    student_pressure = student_overlap_pressure(
                        class_id, option, assigned
                    )
                    group_conflicts = group_conflicts_for(class_id, option, assigned)
                    time_pair_conflicts = 0
                    room_sensitive_neighbors = []
                    for neighbor in neighbors[class_id]:
                        if not time_pair_valid(
                            class_id,
                            option,
                            neighbor,
                            assigned[neighbor][1],
                        ):
                            time_pair_conflicts += 1
                        elif any(
                            base in room_sensitive_bases
                            for base, _parameters, _defined_reversed in pair_rules(
                                class_id, neighbor
                            )[0]
                        ):
                            room_sensitive_neighbors.append(neighbor)
                    for room_id in sampled_rooms(
                        class_id,
                        option_index,
                        rng,
                        current_room=old_room if option_index == old_index else None,
                    ):
                        collisions = (
                            sum(
                                bool(
                                    time_mask
                                    & full_time_masks[(other_id, assigned[other_id][0])]
                                )
                                for other_id in room_members[room_id]
                            )
                            if room_id is not None
                            else 0
                        )
                        pair_conflicts = time_pair_conflicts
                        for neighbor_offset, neighbor in enumerate(
                            room_sensitive_neighbors
                        ):
                            if (
                                neighbor_offset % 16 == 0
                                and time.monotonic() >= repair_deadline
                            ):
                                diagnostics["joint_deadline_exhausted"] = True
                                return None
                            pair_conflicts += not hard_pair_valid(
                                class_id,
                                option,
                                room_id,
                                neighbor,
                                assigned[neighbor][1],
                                assigned[neighbor][2],
                            )
                        tabu_penalty = (
                            tabu.get((class_id, option_index, room_id), -1)
                            > total_iterations
                            and collisions + pair_conflicts + group_conflicts >= worst
                        )
                        choices.append(
                            (
                                int(tabu_penalty),
                                collisions + pair_conflicts + group_conflicts,
                                student_pressure,
                                option.penalty,
                                room_penalties_by_class[class_id].get(room_id, 0),
                                rng.random(),
                                option_index,
                                option,
                                room_id,
                            )
                        )
                choices.sort()
                feasibility_key = choices[0][:2]
                choice_pool = [
                    choice for choice in choices if choice[:2] == feasibility_key
                ]
                chosen = choice_pool[rng.randrange(len(choice_pool))]
                option_index, option, room_id = chosen[-3:]
                old_mask = full_time_masks[(class_id, old_index)]
                if old_room is not None:
                    for other_id in room_members[old_room]:
                        if (
                            old_mask
                            & full_time_masks[(other_id, assigned[other_id][0])]
                        ):
                            room_total -= 1
                            conflict_total -= 1
                            degrees[class_id] -= 1
                            degrees[other_id] -= 1
                for neighbor in neighbors[class_id]:
                    edge_key = tuple(sorted((class_id, neighbor)))
                    old_kind = pair_state[edge_key]
                    violated = not hard_pair_valid(
                        class_id,
                        option,
                        room_id,
                        neighbor,
                        assigned[neighbor][1],
                        assigned[neighbor][2],
                    )
                    new_kind = None
                    if violated:
                        new_kind = (
                            "room"
                            if time_pair_valid(
                                class_id,
                                option,
                                neighbor,
                                assigned[neighbor][1],
                            )
                            else "time"
                        )
                    if old_kind == new_kind:
                        continue
                    if old_kind is not None:
                        pair_total -= 1
                        conflict_total -= 1
                        degrees[class_id] -= 1
                        degrees[neighbor] -= 1
                        if old_kind == "room":
                            pair_room_total -= 1
                        else:
                            pair_time_total -= 1
                    if new_kind is not None:
                        pair_total += 1
                        conflict_total += 1
                        degrees[class_id] += 1
                        degrees[neighbor] += 1
                        if new_kind == "room":
                            pair_room_total += 1
                        else:
                            pair_time_total += 1
                    pair_state[edge_key] = new_kind
                for group in groups_by_class[class_id]:
                    base, parameters, class_ids = group
                    old_units = group_state[group]
                    resolved = {
                        other_id: (
                            option if other_id == class_id else assigned[other_id][1]
                        )
                        for other_id in class_ids
                    }
                    new_units = _special_distribution_units(
                        problem, base, parameters, class_ids, resolved
                    )
                    delta = new_units - old_units
                    if not delta:
                        continue
                    group_state[group] = new_units
                    group_total += delta
                    conflict_total += delta
                    for other_id in class_ids:
                        degrees[other_id] += delta
                assigned[class_id] = (option_index, option, room_id)
                room_members[room_id].add(class_id)
                new_mask = full_time_masks[(class_id, option_index)]
                if room_id is not None:
                    for other_id in room_members[room_id]:
                        if other_id == class_id:
                            continue
                        if (
                            new_mask
                            & full_time_masks[(other_id, assigned[other_id][0])]
                        ):
                            room_total += 1
                            conflict_total += 1
                            degrees[class_id] += 1
                            degrees[other_id] += 1
                tabu[(class_id, old_index, old_room)] = (
                    total_iterations + 7 + rng.randrange(11)
                )
                if stagnant > 120:
                    # A coordinated deterministic kick crosses plateaus where
                    # every single-class move merely transfers a room and
                    # SameAttendees collision to another class.  The following
                    # iterations still evaluate and repair the exact hard model.
                    kick_roots = sorted(
                        degrees,
                        key=lambda item: (-degrees[item], item),
                    )[: min(16, len(degrees))]
                    for kick_id in kick_roots:
                        kick_index, _kick_option, kick_room = assigned[kick_id]
                        room_members[kick_room].remove(kick_id)
                        indices = sampled_time_indices(
                            kick_id,
                            rng,
                            current_index=kick_index,
                            limit=72,
                        )
                        replacement_index = indices[rng.randrange(len(indices))]
                        replacement_option = time_domains[kick_id][replacement_index]
                        replacement_rooms = sampled_rooms(
                            kick_id,
                            replacement_index,
                            rng,
                        )
                        replacement_room = replacement_rooms[
                            rng.randrange(len(replacement_rooms))
                        ]
                        assigned[kick_id] = (
                            replacement_index,
                            replacement_option,
                            replacement_room,
                        )
                        room_members[replacement_room].add(kick_id)
                    (
                        conflict_total,
                        degrees,
                        pair_state,
                        group_state,
                        room_total,
                        pair_total,
                        pair_time_total,
                        pair_room_total,
                        group_total,
                    ) = build_joint_conflict_state(assigned, room_members)
                    stagnant = 0
                    tabu.clear()
                if stagnant > 600:
                    break
        diagnostics["joint_min_conflicts_restarts"] = restart + 1
        diagnostics["joint_min_conflicts_iterations"] = total_iterations
        diagnostics["joint_min_conflicts_best"] = best_conflicts
        diagnostics["joint_min_conflicts_complete_assignment"] = (
            best_assignment is not None
        )
        return None

    def construct_joint_greedy():
        joint_started = time.monotonic()
        joint_remaining = max(0.0, deadline - joint_started)
        joint_budget = min(20.0, max(0.25, joint_remaining * 0.25))
        joint_deadline = min(deadline - 0.5, joint_started + joint_budget)
        best_assigned = 0
        for restart in range(12):
            if time.monotonic() >= joint_deadline:
                diagnostics["joint_deadline_exhausted"] = True
                diagnostics["joint_assigned"] = best_assigned
                return None
            rng = random.Random(random_seed + 9001 + restart * 65537)
            assigned = {}
            occupied_by_room = defaultdict(int)
            room_members = defaultdict(set)
            occupancy_pressure = defaultdict(int)
            unassigned = set(time_domains)
            tabu_until = {}
            move_counts = defaultdict(int)
            construction_step = 0
            assigned_neighbor_counts = defaultdict(int)
            queue = [
                (
                    0,
                    len(supported_rooms[(class_id, 0)]) or 10**9,
                    -len(neighbors[class_id]),
                    len(time_domains[class_id]),
                    class_id,
                )
                for class_id in unassigned
            ]
            heapify(queue)

            def push_class(class_id):
                heappush(
                    queue,
                    (
                        -assigned_neighbor_counts[class_id],
                        len(supported_rooms[(class_id, 0)]) or 10**9,
                        -len(neighbors[class_id]),
                        len(time_domains[class_id]),
                        class_id,
                    ),
                )

            def next_class():
                while queue:
                    item = heappop(queue)
                    class_id = item[-1]
                    if (
                        class_id in unassigned
                        and item[0] == -assigned_neighbor_counts[class_id]
                    ):
                        return class_id
                return None

            def mark_assigned(class_id):
                unassigned.remove(class_id)
                for neighbor in neighbors[class_id]:
                    if neighbor in unassigned:
                        assigned_neighbor_counts[neighbor] += 1
                        push_class(neighbor)

            def mark_unassigned(class_id):
                for neighbor in neighbors[class_id]:
                    if neighbor in unassigned:
                        assigned_neighbor_counts[neighbor] -= 1
                        push_class(neighbor)
                unassigned.add(class_id)
                assigned_neighbor_counts[class_id] = sum(
                    neighbor in assigned for neighbor in neighbors[class_id]
                )
                push_class(class_id)

            def construction_rooms(class_id, option_index):
                rooms = supported_rooms[(class_id, option_index)] or (None,)
                if len(rooms) <= 12:
                    return rooms
                penalties = room_penalties_by_class[class_id]
                selected = set(
                    sorted(
                        rooms,
                        key=lambda room_id: (
                            penalties.get(room_id, 0),
                            str(room_id),
                        ),
                    )[:6]
                )
                selected.update(
                    assigned[neighbor][2]
                    for neighbor in neighbors[class_id]
                    if neighbor in assigned and assigned[neighbor][2] in rooms
                )
                remaining_rooms = [
                    room_id for room_id in rooms if room_id not in selected
                ]
                rng.shuffle(remaining_rooms)
                selected.update(remaining_rooms[: max(0, 12 - len(selected))])
                return tuple(sorted(selected, key=lambda value: str(value)))

            while unassigned:
                if time.monotonic() >= joint_deadline:
                    diagnostics["joint_deadline_exhausted"] = True
                    diagnostics["joint_assigned"] = max(best_assigned, len(assigned))
                    return None
                class_id = next_class()
                if class_id is None:
                    break
                candidates = []
                compatible_times = 0
                open_room_choices = 0
                hard_compatible_choices = 0
                future_supports = [
                    len(time_domains[neighbor])
                    for neighbor in neighbors[class_id]
                    if neighbor in unassigned and neighbor != class_id
                ]
                for option_index, option in enumerate(time_domains[class_id]):
                    if option_index % 8 == 0 and time.monotonic() >= joint_deadline:
                        diagnostics["joint_deadline_exhausted"] = True
                        diagnostics["joint_assigned"] = max(
                            best_assigned, len(assigned)
                        )
                        return None
                    compatible_times += 1
                    # Keep the constructive path genuinely lazy.  Exact
                    # assigned-neighbor semantics are checked with the chosen
                    # room below; precomputing every neighbor option matrix here
                    # dominated the budget on large student-heavy instances.
                    time_mask = full_time_masks[(class_id, option_index)]
                    pressure_mask = pressure_masks[(class_id, option_index)]
                    rooms = construction_rooms(class_id, option_index)
                    feasible_rooms = []
                    for room_id in rooms:
                        if (
                            room_id is not None
                            and occupied_by_room[room_id] & time_mask
                        ):
                            continue
                        open_room_choices += 1
                        if any(
                            neighbor in assigned
                            and not hard_pair_valid(
                                class_id,
                                option,
                                room_id,
                                neighbor,
                                assigned[neighbor][1],
                                assigned[neighbor][2],
                            )
                            for neighbor in neighbors[class_id]
                        ):
                            continue
                        hard_compatible_choices += 1
                        feasible_rooms.append(
                            (
                                occupied_by_room[room_id].bit_count()
                                if room_id is not None
                                else 0,
                                room_penalties_by_class[class_id].get(room_id, 0),
                                str(room_id),
                                room_id,
                            )
                        )
                    if not feasible_rooms:
                        continue
                    feasible_rooms.sort()
                    peak = max(
                        (
                            occupancy_pressure[slot] + 1
                            for slot in _set_bit_indices(pressure_mask)
                        ),
                        default=0,
                    )
                    pressure = sum(
                        (occupancy_pressure[slot] + 1) ** 2
                        for slot in _set_bit_indices(pressure_mask)
                    )
                    for room_choice in feasible_rooms[:8]:
                        candidates.append(
                            (
                                -min(future_supports, default=10**9),
                                -sum(future_supports),
                                peak,
                                pressure,
                                option.penalty,
                                room_choice[0],
                                room_choice[1],
                                -len(rooms),
                                rng.random(),
                                option_index,
                                option,
                                room_choice[-1],
                                time_mask,
                                pressure_mask,
                            )
                        )
                if not candidates:
                    repaired = None
                    for option_index, option in enumerate(time_domains[class_id]):
                        time_mask = full_time_masks[(class_id, option_index)]
                        for room_id in construction_rooms(class_id, option_index):
                            blockers = [
                                blocker_id
                                for blocker_id in room_members[room_id]
                                if full_time_masks[
                                    (blocker_id, assigned[blocker_id][0])
                                ]
                                & time_mask
                            ]
                            if len(blockers) != 1:
                                continue
                            blocker_id = blockers[0]
                            blocker_index, blocker_option, blocker_room = assigned[
                                blocker_id
                            ]
                            blocker_mask = full_time_masks[(blocker_id, blocker_index)]
                            for alternate_room in construction_rooms(
                                blocker_id, blocker_index
                            ):
                                if alternate_room == blocker_room or (
                                    alternate_room is not None
                                    and occupied_by_room[alternate_room] & blocker_mask
                                ):
                                    continue
                                assigned[blocker_id] = (
                                    blocker_index,
                                    blocker_option,
                                    alternate_room,
                                )
                                blocker_valid = all(
                                    neighbor not in assigned
                                    or neighbor == blocker_id
                                    or hard_pair_valid(
                                        blocker_id,
                                        blocker_option,
                                        alternate_room,
                                        neighbor,
                                        assigned[neighbor][1],
                                        assigned[neighbor][2],
                                    )
                                    for neighbor in neighbors[blocker_id]
                                )
                                root_valid = blocker_valid and all(
                                    neighbor not in assigned
                                    or hard_pair_valid(
                                        class_id,
                                        option,
                                        room_id,
                                        neighbor,
                                        assigned[neighbor][1],
                                        assigned[neighbor][2],
                                    )
                                    for neighbor in neighbors[class_id]
                                )
                                if root_valid:
                                    room_members[blocker_room].remove(blocker_id)
                                    occupied_by_room[blocker_room] = 0
                                    for other_id in room_members[blocker_room]:
                                        occupied_by_room[blocker_room] |= (
                                            full_time_masks[
                                                (other_id, assigned[other_id][0])
                                            ]
                                        )
                                    room_members[alternate_room].add(blocker_id)
                                    if alternate_room is not None:
                                        occupied_by_room[alternate_room] |= blocker_mask
                                    repaired = (
                                        option_index,
                                        option,
                                        room_id,
                                        time_mask,
                                        pressure_masks[(class_id, option_index)],
                                    )
                                    break
                                assigned[blocker_id] = (
                                    blocker_index,
                                    blocker_option,
                                    blocker_room,
                                )
                            if repaired is not None:
                                break
                        if repaired is not None:
                            break
                    if repaired is not None:
                        option_index, option, room_id, time_mask, pressure_mask = repaired
                        assigned[class_id] = (option_index, option, room_id)
                        room_members[room_id].add(class_id)
                        if room_id is not None:
                            occupied_by_room[room_id] |= time_mask
                        for slot in _set_bit_indices(pressure_mask):
                            occupancy_pressure[slot] += 1
                        mark_assigned(class_id)
                        diagnostics["joint_ejections"] = (
                            diagnostics.get("joint_ejections", 0) + 1
                        )
                        continue
                    # Conflict-directed construction: choose a legal value with
                    # the smallest assigned conflict set, evict that set, and
                    # requeue it.  This is deliberately sparse and incremental;
                    # it avoids materializing the full time-room Cartesian model
                    # while escaping the first blocked greedy prefix.
                    ejection_candidates = []
                    maximum_ejections = min(
                        32,
                        max(8, len(assigned) // 50 + 6),
                    )
                    for option_index, option in enumerate(time_domains[class_id]):
                        if option_index % 8 == 0 and time.monotonic() >= joint_deadline:
                            diagnostics["joint_deadline_exhausted"] = True
                            diagnostics["joint_assigned"] = max(
                                best_assigned, len(assigned)
                            )
                            return None
                        time_mask = full_time_masks[(class_id, option_index)]
                        pressure_mask = pressure_masks[(class_id, option_index)]
                        for room_id in construction_rooms(class_id, option_index):
                            blockers = {
                                neighbor
                                for neighbor in neighbors[class_id]
                                if neighbor in assigned
                                and not hard_pair_valid(
                                    class_id,
                                    option,
                                    room_id,
                                    neighbor,
                                    assigned[neighbor][1],
                                    assigned[neighbor][2],
                                )
                            }
                            if room_id is not None:
                                blockers.update(
                                    blocker_id
                                    for blocker_id in room_members[room_id]
                                    if full_time_masks[
                                        (blocker_id, assigned[blocker_id][0])
                                    ]
                                    & time_mask
                                )
                            if not blockers or len(blockers) > maximum_ejections:
                                continue
                            protected = sum(
                                tabu_until.get(blocker_id, -1) > construction_step
                                for blocker_id in blockers
                            )
                            future_supports = [
                                len(time_domains[neighbor])
                                for neighbor in neighbors[class_id]
                                if neighbor in unassigned and neighbor != class_id
                            ]
                            ejection_candidates.append(
                                (
                                    protected,
                                    len(blockers),
                                    sum(
                                        move_counts[blocker_id]
                                        for blocker_id in blockers
                                    ),
                                    -min(future_supports, default=10**9),
                                    sum(
                                        (occupancy_pressure[slot] + 1) ** 2
                                        for slot in _set_bit_indices(pressure_mask)
                                    ),
                                    option.penalty,
                                    room_penalties_by_class[class_id].get(room_id, 0),
                                    rng.random(),
                                    option_index,
                                    option,
                                    room_id,
                                    time_mask,
                                    pressure_mask,
                                    tuple(sorted(blockers)),
                                )
                            )
                    if ejection_candidates:
                        ejection_candidates.sort()
                        chosen_ejection = ejection_candidates[0]
                        option_index = chosen_ejection[-6]
                        option = chosen_ejection[-5]
                        room_id = chosen_ejection[-4]
                        time_mask = chosen_ejection[-3]
                        pressure_mask = chosen_ejection[-2]
                        blockers = chosen_ejection[-1]
                        for blocker_id in blockers:
                            blocker_index, _, blocker_room = assigned.pop(blocker_id)
                            room_members[blocker_room].remove(blocker_id)
                            if blocker_room is not None:
                                occupied_by_room[blocker_room] = 0
                                for other_id in room_members[blocker_room]:
                                    occupied_by_room[blocker_room] |= full_time_masks[
                                        (other_id, assigned[other_id][0])
                                    ]
                            for slot in _set_bit_indices(
                                pressure_masks[(blocker_id, blocker_index)]
                            ):
                                occupancy_pressure[slot] -= 1
                            mark_unassigned(blocker_id)
                            move_counts[blocker_id] += 1
                        assigned[class_id] = (option_index, option, room_id)
                        room_members[room_id].add(class_id)
                        if room_id is not None:
                            occupied_by_room[room_id] |= time_mask
                        for slot in _set_bit_indices(pressure_mask):
                            occupancy_pressure[slot] += 1
                        mark_assigned(class_id)
                        construction_step += 1
                        tabu_until[class_id] = construction_step + 7 + len(blockers)
                        diagnostics["joint_conflict_ejections"] = diagnostics.get(
                            "joint_conflict_ejections", 0
                        ) + len(blockers)
                        diagnostics["joint_ejection_steps"] = (
                            diagnostics.get("joint_ejection_steps", 0) + 1
                        )
                        best_assigned = max(best_assigned, len(assigned))
                        continue
                    best_assigned = max(best_assigned, len(assigned))
                    diagnostics["joint_failed_class_id"] = class_id
                    diagnostics["joint_compatible_times"] = compatible_times
                    diagnostics["joint_open_room_choices"] = open_room_choices
                    diagnostics["joint_hard_compatible_choices"] = (
                        hard_compatible_choices
                    )
                    break
                candidates.sort()
                chosen = candidates[rng.randrange(min(3, len(candidates)))]
                option_index = chosen[-5]
                option = chosen[-4]
                room_id = chosen[-3]
                time_mask = chosen[-2]
                pressure_mask = chosen[-1]
                assigned[class_id] = (option_index, option, room_id)
                room_members[room_id].add(class_id)
                if room_id is not None:
                    occupied_by_room[room_id] |= time_mask
                for slot in _set_bit_indices(pressure_mask):
                    occupancy_pressure[slot] += 1
                mark_assigned(class_id)
            if not unassigned:
                candidate = tuple(
                    ITC2019ClassPlacement(
                        class_id=klass.id,
                        days=assigned[klass.id][1].days,
                        start=assigned[klass.id][1].start,
                        weeks=assigned[klass.id][1].weeks,
                        room_id=assigned[klass.id][2],
                    )
                    for klass in problem.classes
                )
                if not validate_itc2019_solution(problem, candidate, {}):
                    diagnostics["joint_restarts"] = restart + 1
                    diagnostics["joint_assigned"] = len(assigned)
                    return candidate
            if time.monotonic() >= joint_deadline:
                break
        diagnostics["joint_restarts"] = restart + 1
        diagnostics["joint_assigned"] = best_assigned
        diagnostics["joint_unassigned"] = len(problem.classes) - best_assigned
        return None

    selected = None
    occupancy = None
    pair_matrix_cells = sum(
        len(time_domains[first_id]) * len(time_domains[second_id])
        for first_id, second_id in hard_pair_rules
    )
    diagnostics["pair_matrix_cells"] = pair_matrix_cells
    use_joint_construction = joint_construction
    if use_joint_construction:
        from benchmarks.itc2019_structural import (
            construct_itc2019_structural,
            should_construct_itc2019_structurally,
        )

        if should_construct_itc2019_structurally(problem):
            structural_diagnostics = {}
            structural_candidate = construct_itc2019_structural(
                problem,
                deadline=deadline,
                workers=workers,
                random_seed=random_seed,
                diagnostics=structural_diagnostics,
            )
            diagnostics["structural_constructor"] = structural_diagnostics
            if structural_candidate is not None:
                return structural_candidate
            diagnostics["structural_failed_closed"] = True
            return None
        selected = (
            construct_time_min_conflicts()
            if deadline - time.monotonic() > 8.0
            and (pair_matrix_cells > 100_000 or len(problem.classes) > 200)
            else None
        )
        if selected is not None:
            occupancy = defaultdict(int)
            for class_id, (option_index, _option) in selected.items():
                for item in _set_bit_indices(pressure_masks[(class_id, option_index)]):
                    occupancy[item] += 1
        time_seed_is_feasible = (
            selected is not None and diagnostics.get("time_min_conflicts_best") == 0
        )
        hard_time_component_coupling = any(
            base in {"SameDays", "SameStart", "SameTime", "SameWeeks"}
            for rules in hard_pair_rules.values()
            for base, _parameters, _defined_reversed in rules
        )
        joint_handoff_required = bool(
            not time_seed_is_feasible
            or (objective_problem is not None and objective_problem.students)
            or hard_time_component_coupling
        )
        # A hard-time-feasible seed is not necessarily room-feasible.  Always
        # offer a constructed seed to the joint repair so room conflicts can
        # move both the room and its selected time instead of freezing a time
        # pattern that the fixed-time room model may be unable to complete.
        if selected is not None:
            if time_seed_is_feasible:
                precheck_seconds = min(
                    5.0,
                    max(0.0, deadline - time.monotonic() - 3.0),
                )
                fixed_time_candidate = solve_fixed_time_rooms_for(
                    selected,
                    max_seconds=precheck_seconds,
                    diagnostic_key="fixed_time_room_precheck_status",
                )
                if fixed_time_candidate is not None:
                    return fixed_time_candidate
            if joint_handoff_required:
                joint_candidate = construct_joint_min_conflicts(selected)
                if joint_candidate is not None:
                    return joint_candidate
        elif selected is None:
            joint_candidate = construct_joint_min_conflicts()
            if joint_candidate is not None:
                return joint_candidate
        if not time_seed_is_feasible and time.monotonic() < deadline - 3.0:
            joint_candidate = construct_joint_greedy()
            if joint_candidate is not None:
                return joint_candidate
        if not time_seed_is_feasible and time.monotonic() >= deadline - 3.0:
            diagnostics["joint_deadline_exhausted"] = True
            return None
    # One deterministic pass deliberately feeds the exact time repair when the
    # greedy ordering stalls.  Repeated greedy restarts can find a feasible but
    # substantially worse basin and consume the time needed by that repair.
    greedy_restarts = 0 if selected is not None else 1
    for restart in range(greedy_restarts):
        rng = random.Random(random_seed + restart * 65537)
        attempt_selected = {}
        attempt_occupancy = defaultdict(int)
        unassigned = set(time_domains)
        while unassigned:
            class_id = min(
                unassigned,
                key=lambda item: (
                    -sum(neighbor in attempt_selected for neighbor in neighbors[item]),
                    -len(neighbors[item]),
                    len(time_domains[item]),
                    rng.random(),
                ),
            )
            candidates = []
            for option_index, option in enumerate(time_domains[class_id]):
                if any(
                    neighbor in attempt_selected
                    and not (
                        (
                            allowed_option_masks(class_id, neighbor)[option_index]
                            & (1 << attempt_selected[neighbor][0])
                        )
                        if use_joint_construction
                        else time_pair_valid(
                            class_id,
                            option,
                            neighbor,
                            attempt_selected[neighbor][1],
                        )
                    )
                    for neighbor in neighbors[class_id]
                ):
                    continue
                pressure_mask = pressure_masks[(class_id, option_index)]
                room_support = len(supported_rooms[(class_id, option_index)])
                peak = max(
                    (
                        attempt_occupancy[item] + 1
                        for item in _set_bit_indices(pressure_mask)
                    ),
                    default=0,
                )
                pressure = sum(
                    (attempt_occupancy[item] + 1) ** 2
                    for item in _set_bit_indices(pressure_mask)
                )
                candidates.append(
                    (
                        pressure,
                        peak,
                        -room_support,
                        option.penalty,
                        rng.random(),
                        option_index,
                        option,
                        pressure_mask,
                    )
                )
            if not candidates:
                break
            candidates.sort()
            chosen = candidates[rng.randrange(min(3, len(candidates)))]
            option_index = chosen[-3]
            attempt_selected[class_id] = (option_index, chosen[-2])
            for item in _set_bit_indices(chosen[-1]):
                attempt_occupancy[item] += 1
            unassigned.remove(class_id)
        if not unassigned:
            selected = attempt_selected
            occupancy = attempt_occupancy
            break
        if time.monotonic() >= deadline - 5.0:
            break
    if selected is None or occupancy is None:
        rng = random.Random(random_seed + 1701)
        occupancy = defaultdict(int)
        selected = {}
        for class_id in sorted(
            time_domains, key=lambda item: (-len(neighbors[item]), item)
        ):
            candidates = []
            for option_index, option in enumerate(time_domains[class_id]):
                pressure_mask = pressure_masks[(class_id, option_index)]
                pressure = sum(
                    (occupancy[item] + 1) ** 2
                    for item in _set_bit_indices(pressure_mask)
                )
                candidates.append(
                    (pressure, option.penalty, rng.random(), option_index, option)
                )
            chosen = min(candidates)
            selected[class_id] = (chosen[-2], chosen[-1])
            for item in _set_bit_indices(pressure_masks[(class_id, chosen[-2])]):
                occupancy[item] += 1

        edge_list = list(hard_pair_rules)
        exact_model = cp_model.CpModel()
        exact_choices = {
            class_id: exact_model.new_int_var(
                0, len(time_domains[class_id]) - 1, f"t_{class_id}"
            )
            for class_id in sorted(time_domains)
        }
        for first_id, second_id in edge_list:
            if time.monotonic() >= deadline - 3.0:
                raise TimeoutError("decomposed time-predicate build exceeded deadline")
            rows = allowed_option_masks(first_id, second_id)
            forbidden = _iter_forbidden_option_pairs(
                rows,
                len(time_domains[second_id]),
                deadline=deadline - 3.0,
            )
            _add_streamed_forbidden_assignments(
                exact_model,
                (exact_choices[first_id], exact_choices[second_id]),
                forbidden,
            )
        ordered_choices = sorted(
            exact_choices,
            key=lambda class_id: (
                -len(neighbors[class_id]),
                len(time_domains[class_id]),
                class_id,
            ),
        )
        exact_model.add_decision_strategy(
            [exact_choices[class_id] for class_id in ordered_choices],
            cp_model.CHOOSE_FIRST,
            cp_model.SELECT_RANDOM_HALF,
        )
        for class_id, (option_index, _option) in selected.items():
            exact_model.add_hint(exact_choices[class_id], option_index)
        exact_solver = cp_model.CpSolver()
        exact_solver.parameters.max_time_in_seconds = max(
            0.01, min(60.0, deadline - time.monotonic() - 3.0)
        )
        exact_solver.parameters.num_search_workers = workers
        exact_solver.parameters.random_seed = random_seed
        exact_solver.parameters.randomize_search = True
        exact_solver.parameters.search_branching = cp_model.RANDOMIZED_SEARCH
        exact_status = exact_solver.solve(exact_model)
        if exact_status not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
            return None
        selected = {
            class_id: (
                int(exact_solver.value(exact_choices[class_id])),
                time_domains[class_id][
                    int(exact_solver.value(exact_choices[class_id]))
                ],
            )
            for class_id in exact_choices
        }
        occupancy = defaultdict(int)
        for class_id, (option_index, _option) in selected.items():
            for item in _set_bit_indices(pressure_masks[(class_id, option_index)]):
                occupancy[item] += 1

    selected_times = {class_id: pair[1] for class_id, pair in selected.items()}

    rng = random.Random(random_seed + 1717)
    selected_rooms = {}
    room_members = defaultdict(set)
    overlap_pressure = defaultdict(int)
    classes_by_occurrence = defaultdict(list)
    for class_id, option in selected_times.items():
        for occurrence in occurrences(option):
            classes_by_occurrence[occurrence].append(class_id)
    for class_ids in classes_by_occurrence.values():
        pressure = len(class_ids) - 1
        if pressure > 0:
            for class_id in class_ids:
                overlap_pressure[class_id] += pressure
    for class_id in sorted(
        selected,
        key=lambda item: (
            len(supported_rooms[(item, selected[item][0])]) or 10**9,
            -overlap_pressure[item] if use_joint_construction else 0,
            -len(neighbors[item]),
            item,
        ),
    ):
        option_index, option = selected[class_id]
        rooms = supported_rooms[(class_id, option_index)] or (None,)
        room_id = min(
            rooms,
            key=lambda candidate: (
                sum(
                    overlap(option, selected[other_id][1])
                    for other_id in room_members[candidate]
                )
                if candidate is not None
                else 0,
                sum(
                    not hard_pair_valid(
                        class_id,
                        option,
                        candidate,
                        neighbor,
                        selected[neighbor][1],
                        selected_rooms[neighbor],
                    )
                    for neighbor in neighbors[class_id]
                    if neighbor in selected_rooms
                ),
                str(candidate),
            ),
        )
        selected_rooms[class_id] = room_id
        room_members[room_id].add(class_id)

    def room_conflicts(class_id, room_id):
        option = selected_times[class_id]
        collisions = sum(
            other_id != class_id
            and bool(
                full_time_masks[(class_id, selected[class_id][0])]
                & full_time_masks[(other_id, selected[other_id][0])]
            )
            for other_id in room_members[room_id]
        )
        pair_violations = sum(
            other_id in selected_rooms
            and not hard_pair_valid(
                class_id,
                option,
                room_id,
                other_id,
                selected_times[other_id],
                selected_rooms[other_id],
            )
            for other_id in neighbors[class_id]
        )
        return collisions + pair_violations

    room_penalties = room_penalties_by_class
    stagnant_room_moves = 0
    room_repair_started = time.monotonic()
    room_repair_deadline = min(
        deadline - 2.0,
        room_repair_started
        + min(8.0, max(0.25, (deadline - room_repair_started) * 0.15)),
    )
    for _repair_iteration in range(5000 if use_joint_construction else 0):
        if time.monotonic() >= room_repair_deadline:
            break
        conflicted = []
        scan_expired = False
        for class_offset, class_id in enumerate(selected):
            if class_offset % 64 == 0 and time.monotonic() >= room_repair_deadline:
                scan_expired = True
                break
            conflict_count = room_conflicts(class_id, selected_rooms[class_id])
            if conflict_count > 0:
                conflicted.append((conflict_count, class_id))
        if scan_expired:
            break
        if not conflicted:
            candidate = tuple(
                ITC2019ClassPlacement(
                    class_id=klass.id,
                    days=selected_times[klass.id].days,
                    start=selected_times[klass.id].start,
                    weeks=selected_times[klass.id].weeks,
                    room_id=selected_rooms[klass.id],
                )
                for klass in problem.classes
            )
            if not validate_itc2019_solution(problem, candidate, {}):
                return candidate
            break
        worst = max(count for count, _class_id in conflicted)
        roots = [class_id for count, class_id in conflicted if count == worst]
        class_id = roots[rng.randrange(len(roots))]
        old_room = selected_rooms[class_id]
        candidates = []
        for room_id in supported_rooms[(class_id, selected[class_id][0])] or (None,):
            selected_rooms[class_id] = room_id
            candidates.append(
                (
                    room_conflicts(class_id, room_id),
                    room_penalties[class_id].get(room_id, 0),
                    rng.random(),
                    room_id,
                )
            )
        selected_rooms[class_id] = old_room
        if not candidates:
            break
        candidates.sort()
        chosen = candidates[0]
        selected_rooms[class_id] = chosen[-1]
        if chosen[0] < worst:
            stagnant_room_moves = 0
        else:
            stagnant_room_moves += 1
        if stagnant_room_moves > 400 or time.monotonic() >= room_repair_deadline:
            break

    if (
        use_joint_construction
        and diagnostics.get("fixed_time_room_precheck_status") != "INFEASIBLE"
    ):
        exact_room_candidate = solve_fixed_time_rooms_for(
            selected,
            max_seconds=max(0.0, min(45.0, deadline - time.monotonic() - 1.0)),
        )
        if exact_room_candidate is not None:
            return exact_room_candidate

    room_members = defaultdict(set)
    for class_id, room_id in selected_rooms.items():
        room_members[room_id].add(class_id)

    best_room_conflicts = 10**9
    stagnant = 0
    for iteration in range(50000):
        conflicted = defaultdict(int)
        for room_id, class_ids in room_members.items():
            if room_id is None:
                continue
            ordered_ids = sorted(class_ids)
            for first_index, first_id in enumerate(ordered_ids):
                for second_id in ordered_ids[first_index + 1 :]:
                    if overlap(selected[first_id][1], selected[second_id][1]):
                        conflicted[first_id] += 1
                        conflicted[second_id] += 1
        for first_id, second_id in hard_pair_rules:
            if not hard_pair_valid(
                first_id,
                selected[first_id][1],
                selected_rooms[first_id],
                second_id,
                selected[second_id][1],
                selected_rooms[second_id],
            ):
                conflicted[first_id] += 1
                conflicted[second_id] += 1
        conflict_count = sum(conflicted.values()) // 2
        if conflict_count == 0:
            break
        if conflict_count < best_room_conflicts:
            best_room_conflicts = conflict_count
            stagnant = 0
        else:
            stagnant += 1
        worst = max(conflicted.values())
        roots = [class_id for class_id, count in conflicted.items() if count == worst]
        class_id = roots[rng.randrange(len(roots))]
        old_room = selected_rooms[class_id]
        room_members[old_room].remove(class_id)
        candidates = []
        for option_index, option in enumerate(time_domains[class_id]):
            if any(
                not time_pair_valid(
                    class_id,
                    option,
                    neighbor,
                    selected[neighbor][1],
                )
                for neighbor in neighbors[class_id]
            ):
                continue
            for room_id in supported_rooms[(class_id, option_index)] or (None,):
                room_conflicts = (
                    sum(
                        overlap(option, selected[other_id][1])
                        for other_id in room_members[room_id]
                    )
                    if room_id is not None
                    else 0
                )
                attendee_conflicts = sum(
                    not hard_pair_valid(
                        class_id,
                        option,
                        room_id,
                        neighbor,
                        selected[neighbor][1],
                        selected_rooms[neighbor],
                    )
                    for neighbor in neighbors[class_id]
                )
                candidates.append(
                    (
                        room_conflicts + attendee_conflicts,
                        option.penalty,
                        len(room_members[room_id]),
                        rng.random(),
                        option_index,
                        option,
                        room_id,
                    )
                )
        if not candidates:
            room_members[old_room].add(class_id)
            return None
        candidates.sort()
        best_value = candidates[0][0]
        best_penalty = candidates[0][1]
        tied = [
            candidate
            for candidate in candidates
            if candidate[0] == best_value and candidate[1] == best_penalty
        ]
        chosen = tied[rng.randrange(len(tied))]
        selected[class_id] = (chosen[-3], chosen[-2])
        selected_times[class_id] = chosen[-2]
        selected_rooms[class_id] = chosen[-1]
        room_members[chosen[-1]].add(class_id)
        if stagnant > 800:
            stagnant = 0
        if time.monotonic() >= deadline - 2.0:
            return None
    else:
        return None

    placements = [
        ITC2019ClassPlacement(
            class_id=klass.id,
            days=selected_times[klass.id].days,
            start=selected_times[klass.id].start,
            weeks=selected_times[klass.id].weeks,
            room_id=selected_rooms[klass.id],
        )
        for klass in problem.classes
    ]
    errors = validate_itc2019_solution(problem, placements, {})
    return tuple(placements) if not errors else None


def decomposed_admission_reason(problem: ITC2019Problem) -> str | None:
    """Return why the staged representation is not lossless for this problem."""

    for distribution in problem.distributions:
        base, _parameters = _distribution_spec(distribution.type)
        if distribution.required and base not in _PAIR_DISTRIBUTIONS | {
            "MaxDays",
            "MaxDayLoad",
            "MaxBreaks",
            "MaxBlock",
        }:
            return f"decomposed_required_distribution_not_supported:{base}"
    return None


def solve_itc2019_decomposed(
    problem: ITC2019Problem,
    *,
    time_limit_seconds: float,
    workers: int,
    random_seed: int,
) -> ITC2019NativeSolveResult:
    """Construct and improve a losslessly admitted sparse ITC-2019 timetable."""

    started = time.monotonic()
    deadline = started + float(time_limit_seconds)
    effective_formulation = "decomposed_time_room_repair_v1"

    def failure(**kwargs):
        return replace(
            _itc2019_native_failure(**kwargs),
            formulation=effective_formulation,
            sectioning_mode=("post_timetable_exact" if problem.students else "none"),
        )

    reason = decomposed_admission_reason(problem)
    if reason is not None:
        result = failure(
            status="UNSUPPORTED_MODEL_SCALE",
            started=started,
            build_started=started,
            random_seed=random_seed,
            workers=workers,
            unsupported_reasons=(reason,),
        )
        return result
    # The decomposed route establishes a complete, independently validated
    # capacity-flow sectioning before attempting any soft conflict work.  That
    # path is deliberately much smaller than the generic enrollment CP model,
    # so reserving a quarter of the whole condition needlessly starves the
    # harder timetable constructor on large official instances.
    sectioning_reserve = (
        min(12.0, max(1.0, time_limit_seconds * 0.10)) if problem.students else 0.0
    )
    timetable_deadline = deadline - sectioning_reserve
    timetable_problem = replace(problem, students=()) if problem.students else problem
    if timetable_deadline <= started:
        return failure(
            status="DEADLINE_EXCEEDED",
            started=started,
            build_started=started,
            random_seed=random_seed,
            workers=workers,
        )
    grouped_calendar_route = should_construct_itc2019_grouped_calendar(
        timetable_problem
    )
    generalized_occurrence_route = (
        not grouped_calendar_route
        and should_construct_itc2019_generalized_occurrences(timetable_problem)
    )
    global_route = (
        not grouped_calendar_route
        and not generalized_occurrence_route
        and should_construct_itc2019_globally(timetable_problem)
    )
    resource_seed_route = (
        not grouped_calendar_route
        and not generalized_occurrence_route
        and not global_route
        and should_construct_itc2019_resource_seed(timetable_problem)
    )
    sparse_joint_estimate = (
        estimate_itc2019_sparse_joint_scale(timetable_problem)
        if not grouped_calendar_route
        and not generalized_occurrence_route
        and not global_route
        and not resource_seed_route
        else None
    )
    # Sparse joint placement is the dense pair-coupling constructor.  Keep
    # semantically encodable but smaller/easier cases on their established
    # decomposed route so a new exact formulation cannot regress proven
    # completion or checkpointed quality behavior.
    sparse_joint_route = bool(
        sparse_joint_estimate is not None
        and sparse_joint_estimate.admitted
        and sparse_joint_estimate.required_pair_relations >= 1_000
    )
    compact_joint_estimate = (
        estimate_itc2019_compact_joint_scale(timetable_problem)
        if not grouped_calendar_route
        and not generalized_occurrence_route
        and not global_route
        and not resource_seed_route
        and not sparse_joint_route
        else None
    )
    # The compact factorization pays off only once the direct placement layer
    # is large and pair coupling is dense.  This preserves the established
    # legacy route for smaller semantically encodable instances.
    compact_joint_route = bool(
        compact_joint_estimate is not None
        and compact_joint_estimate.admitted
        and compact_joint_estimate.placement_literals >= 250_000
        and compact_joint_estimate.required_pair_relations >= 1_000
    )
    try:
        if grouped_calendar_route:
            effective_formulation = "grouped_calendar_joint_v1"
            placements = construct_itc2019_grouped_calendar(
                timetable_problem,
                deadline=timetable_deadline,
                workers=workers,
                random_seed=random_seed,
            )
        elif generalized_occurrence_route:
            effective_formulation = "generalized_occurrence_global_v1"
            placements = construct_itc2019_generalized_occurrences(
                timetable_problem,
                deadline=timetable_deadline,
                workers=workers,
                random_seed=random_seed,
            )
        elif global_route:
            effective_formulation = "global_recurring_component_v1"
            placements = construct_itc2019_global_components(
                timetable_problem,
                deadline=timetable_deadline,
                workers=workers,
                random_seed=random_seed,
            )
        elif resource_seed_route:
            effective_formulation = "resource_conflict_seed_v1"
            placements = construct_itc2019_resource_seed(
                timetable_problem,
                deadline=timetable_deadline,
                workers=workers,
                random_seed=random_seed,
            )
        elif sparse_joint_route:
            effective_formulation = "sparse_joint_placement_sat_v1"
            placements = construct_itc2019_sparse_joint(
                timetable_problem,
                deadline=timetable_deadline,
                workers=workers,
                random_seed=random_seed,
            )
        elif compact_joint_route:
            effective_formulation = "compact_joint_placement_sat_v1"
            placements = construct_itc2019_compact_joint(
                timetable_problem,
                deadline=timetable_deadline,
                workers=workers,
                random_seed=random_seed,
            )
        else:
            placements = construct_itc2019_decomposed(
                timetable_problem,
                deadline=timetable_deadline,
                workers=workers,
                random_seed=random_seed,
                objective_problem=problem,
                joint_construction=bool(
                    problem.students
                    or len(problem.classes) > 200
                    or any(
                        distribution.required
                        and _distribution_spec(distribution.type)[0]
                        in {"MaxDays", "MaxDayLoad", "MaxBreaks", "MaxBlock"}
                        for distribution in problem.distributions
                    )
                ),
            )
    except TimeoutError:
        placements = None
    if placements is None:
        return failure(
            status=(
                "DEADLINE_EXCEEDED"
                if time.monotonic() >= timetable_deadline
                else "UNKNOWN"
            ),
            started=started,
            build_started=started,
            random_seed=random_seed,
            workers=workers,
        )

    from benchmarks.itc2019_decomposed_quality import improve_itc2019_decomposed

    incumbent = tuple(placements)
    incumbent_objective = score_itc2019_solution(timetable_problem, incumbent, {})
    quality_round = 0
    if (
        global_route
        and not problem.students
        and timetable_deadline - time.monotonic() > 6.0
    ):
        # The recurrence-aware phase owns only the actual remainder of the same
        # absolute condition deadline.  Its output is advisory: an exception,
        # late return, invalid candidate, or non-improvement preserves the
        # already validated global incumbent.
        try:
            quality_deadline = timetable_deadline - 2.0
            candidate = improve_itc2019_global_recurrence(
                timetable_problem,
                incumbent,
                {},
                deadline=quality_deadline,
                workers=workers,
                random_seed=random_seed,
            )
        except Exception:  # noqa: BLE001 - checkpoint rollback is intentional.
            candidate = None
        if candidate is not None and time.monotonic() < timetable_deadline - 1.0:
            candidate_errors = validate_itc2019_solution(
                timetable_problem, candidate, {}
            )
            if not candidate_errors:
                candidate_objective = score_itc2019_solution(
                    timetable_problem, candidate, {}
                )
                if candidate_objective.total < incumbent_objective.total:
                    incumbent = tuple(candidate)
                    incumbent_objective = candidate_objective
    # Student-heavy instances must establish sectioning before spending the
    # reserved window on timetable quality.  A later timetable change would
    # invalidate that sectioning anyway, so completion takes precedence here.
    # The global route is a completion constructor.  Its first independently
    # validated incumbent must not be lost to a decomposed quality phase whose
    # fixed-time neighborhoods were designed for the older constructor and can
    # consume the entire outer deadline.  Global quality requires its own
    # recurrence-aware neighborhood and is deliberately separate.
    while (
        not problem.students
        and not grouped_calendar_route
        and not global_route
        and not generalized_occurrence_route
        and not resource_seed_route
        and not sparse_joint_route
        and not compact_joint_route
        and timetable_deadline - time.monotonic() > 6.0
    ):
        # Keep each quality phase checkpointable.  A single long phase can
        # consume the condition deadline before the already validated
        # incumbent is returned to the worker for serialization.
        quality_slice_seconds = 45.0
        quality_deadline = min(
            timetable_deadline - 1.0, time.monotonic() + quality_slice_seconds
        )
        candidate = improve_itc2019_decomposed(
            timetable_problem,
            incumbent,
            {},
            deadline=quality_deadline,
            workers=workers,
            random_seed=random_seed + quality_round,
        )
        quality_round += 1
        if candidate is None:
            break
        candidate_errors = validate_itc2019_solution(timetable_problem, candidate, {})
        if candidate_errors:
            break
        candidate_objective = score_itc2019_solution(timetable_problem, candidate, {})
        if candidate_objective.total >= incumbent_objective.total:
            break
        incumbent = tuple(candidate)
        incumbent_objective = candidate_objective

    student_classes = {}
    if problem.students:
        # A complete sectioning incumbent is normally established within a few
        # seconds by the feasibility-first model.  Bound conflict optimization
        # so final validation/scoring cannot be starved by the soft objective.
        finalization_reserve = min(4.0, max(0.25, float(time_limit_seconds) * 0.1))
        remaining = min(16.0, deadline - time.monotonic() - finalization_reserve)
        if remaining <= 0:
            return failure(
                status="DEADLINE_EXCEEDED",
                started=started,
                build_started=started,
                random_seed=random_seed,
                workers=workers,
            )
        sectioning = solve_itc2019_student_sectioning(
            problem,
            incumbent,
            time_limit_seconds=remaining,
            workers=workers,
            random_seed=random_seed,
            feasibility_first_only=True,
        )
        if not sectioning.is_feasible:
            return failure(
                status=sectioning.status,
                started=started,
                build_started=started,
                random_seed=random_seed,
                workers=workers,
                validation_errors=sectioning.validation_errors,
            )
        student_classes = sectioning.student_classes
        # The timetable constructor is deliberately scored without students.
        # Once sectioning is concrete, every downstream quality comparison must
        # use that same full objective.  Otherwise a rooted improvement can be
        # rejected against the stale student-free (often zero) baseline when the
        # broader quality phase is skipped by its larger headroom requirement.
        incumbent_objective = score_itc2019_solution(
            problem,
            incumbent,
            student_classes,
        )

        # The feasibility-first sectioner deliberately establishes a complete
        # enrollment before optimizing conflicts.  Use the remaining shared
        # budget to improve the timetable against that concrete enrollment;
        # this captures real student conflicts instead of the constructor's
        # coarse course-overlap pressure.  Keep a generous outer reserve because
        # the independent validator and scorer are part of the acceptance gate.
        quality_tail_deadline = deadline - finalization_reserve
        quality_deadline = min(
            quality_tail_deadline,
            time.monotonic() + 45.0,
        )
        if quality_deadline - time.monotonic() > 8.0:
            candidate = improve_itc2019_decomposed(
                problem,
                incumbent,
                student_classes,
                deadline=quality_deadline,
                workers=workers,
                random_seed=random_seed,
            )
            if time.monotonic() < deadline - 4.0:
                candidate_errors = validate_itc2019_solution(
                    problem, candidate, student_classes
                )
                if not candidate_errors:
                    candidate_objective = score_itc2019_solution(
                        problem, candidate, student_classes
                    )
                    incumbent_objective = score_itc2019_solution(
                        problem, incumbent, student_classes
                    )
                    if candidate_objective.total < incumbent_objective.total:
                        incumbent = tuple(candidate)
                        incumbent_objective = candidate_objective

        # The broad neighborhood has deliberately bounded reach.  On the
        # resource-seed route, spend the remaining quality window on compact
        # neighborhoods rooted only in realized student/soft violations.  The
        # operator consumes only an independently validated complete incumbent,
        # so the same bounded tail is safe for every student-bearing constructor,
        # including grouped MaxDays/MaxLoad/MaxBreaks/MaxBlock routes.  It owns
        # the same absolute quality deadline and any failure preserves the
        # current incumbent for final validation and serialization.
        student_pair_visits = count_itc2019_student_pair_visits(
            student_classes,
            stop_after=DEFAULT_MAX_STUDENT_PAIR_VISITS,
        )
        if (
            student_pair_visits <= DEFAULT_MAX_STUDENT_PAIR_VISITS
            and quality_tail_deadline - time.monotonic() >= 3.0
        ):
            try:
                rooted = improve_itc2019_violation_rooted(
                    problem,
                    incumbent,
                    student_classes,
                    deadline=quality_tail_deadline,
                    workers=workers,
                    random_seed=random_seed,
                    max_attempts=24,
                    max_accepted_passes=6,
                )
            except Exception:  # noqa: BLE001 - optional-tail rollback is intentional.
                rooted = None
            rooted_placements = None
            rooted_objective = None
            if rooted is not None and time.monotonic() < quality_tail_deadline - 1.0:
                # Treat the rooted result as an untrusted checkpoint boundary.
                # Its embedded errors and score are useful telemetry, but may
                # be stale or malformed after an implementation/ABI change.
                # Independently validate and rescore before replacing the last
                # known-good incumbent, exactly as the broad quality phase does.
                try:
                    candidate_placements = tuple(rooted.placements)
                    candidate_errors = tuple(
                        validate_itc2019_solution(
                            problem,
                            candidate_placements,
                            student_classes,
                        )
                    )
                    if (
                        not candidate_errors
                        and time.monotonic() < quality_tail_deadline
                    ):
                        candidate_objective = score_itc2019_solution(
                            problem,
                            candidate_placements,
                            student_classes,
                        )
                        if time.monotonic() < quality_tail_deadline:
                            rooted_placements = candidate_placements
                            rooted_objective = candidate_objective
                except Exception:  # noqa: BLE001 - checkpoint rollback is intentional.
                    rooted_placements = None
                    rooted_objective = None
            if (
                rooted_placements is not None
                and rooted_objective is not None
                and rooted_objective.total < incumbent_objective.total
            ):
                incumbent = rooted_placements
                incumbent_objective = rooted_objective

    validation_errors = tuple(
        validate_itc2019_solution(problem, incumbent, student_classes)
    )
    finished = time.monotonic()
    if validation_errors or finished > deadline:
        return failure(
            status="DEADLINE_EXCEEDED" if finished > deadline else "UNKNOWN",
            started=started,
            build_started=started,
            random_seed=random_seed,
            workers=workers,
            validation_errors=validation_errors,
        )
    time_values = sum(len(klass.time_options) for klass in problem.classes)
    room_values = sum(len(klass.room_options) for klass in problem.classes)
    return ITC2019NativeSolveResult(
        status="FEASIBLE",
        placements=incumbent,
        student_classes=student_classes,
        objective=score_itc2019_solution(problem, incumbent, student_classes),
        best_bound=None,
        wall_time_seconds=finished - started,
        model_build_seconds=0.0,
        solver_wall_time_seconds=finished - started,
        conflicts=0,
        branches=0,
        deterministic_seed=random_seed,
        workers=workers,
        validation_errors=(),
        unsupported_reasons=(),
        formulation=effective_formulation,
        sectioning_mode="post_timetable_exact" if problem.students else "none",
        time_domain_values=time_values,
        room_domain_values=room_values,
    )
