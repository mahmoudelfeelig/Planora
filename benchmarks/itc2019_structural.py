"""Compact structural constructor for singleton-day ITC-2019 timetables.

The constructor is admitted only when the source representation makes the
calendar constraints lossless in day/start space: every meeting uses one full
week mask, one active day, and a fixed duration per class.  Rooms are assigned
after hard time feasibility with one variable per SameRoom component.
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
    ITC2019TimeOption,
    _distribution_spec,
    _masks_overlap,
    _travel_values,
    score_itc2019_solution,
    validate_itc2019_solution,
)
from benchmarks.itc2019_factorized import _build_factorized_domains


_STRUCTURAL_REQUIRED_TYPES = {
    "DifferentDays",
    "NotOverlap",
    "Precedence",
    "SameAttendees",
    "SameDays",
    "SameRoom",
    "SameStart",
    "SameTime",
    "WorkDay",
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


def _singleton_day(mask: str) -> int:
    if mask.count("1") != 1:
        raise ValueError(f"expected one active day, got {mask!r}")
    return mask.index("1")


def _occurrences(problem: ITC2019Problem, option: ITC2019TimeOption):
    for week, week_active in enumerate(option.weeks):
        if week_active != "1":
            continue
        for day, day_active in enumerate(option.days):
            if day_active != "1":
                continue
            for slot in range(option.start, option.start + option.length):
                yield week, day, slot


def itc2019_structural_admission_reason(problem: ITC2019Problem) -> str | None:
    """Return why the compact day/start representation is not lossless."""

    full_weeks = "1" * problem.nr_weeks
    by_id = {klass.id: klass for klass in problem.classes}
    same_room = _UnionFind(by_id)
    same_room_members: set[str] = set()
    for klass in problem.classes:
        if not klass.time_options:
            return f"structural_empty_time_domain:{klass.id}"
        if len({option.length for option in klass.time_options}) != 1:
            return f"structural_variable_duration:{klass.id}"
        for option in klass.time_options:
            if option.days.count("1") != 1:
                return f"structural_non_singleton_day:{klass.id}"
            if option.weeks != full_weeks:
                return f"structural_non_full_week_mask:{klass.id}"
    for distribution in problem.distributions:
        base, _parameters = _distribution_spec(distribution.type)
        if not distribution.required:
            continue
        if base not in _STRUCTURAL_REQUIRED_TYPES:
            return f"structural_required_distribution_not_supported:{base}"
        if base == "SameRoom":
            class_ids = tuple(dict.fromkeys(distribution.class_ids))
            same_room_members.update(class_ids)
            for first_id, second_id in combinations(class_ids, 2):
                same_room.union(first_id, second_id)
    for class_id in same_room_members:
        klass = by_id[class_id]
        if not klass.room_required or not klass.room_options:
            return f"structural_roomless_same_room_component:{class_id}"
    return None


def should_construct_itc2019_structurally(problem: ITC2019Problem) -> bool:
    """Admit large pair products without depending on a benchmark identifier."""

    if itc2019_structural_admission_reason(problem) is not None:
        return False
    domain_sizes = {klass.id: len(klass.time_options) for klass in problem.classes}
    edges = set()
    for distribution in problem.distributions:
        if not distribution.required:
            continue
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        edges.update(tuple(sorted(edge)) for edge in combinations(class_ids, 2))
    pair_product = sum(
        domain_sizes[first_id] * domain_sizes[second_id]
        for first_id, second_id in edges
    )
    return len(problem.classes) >= 1_000 or pair_product >= 2_000_000


def construct_itc2019_structural(
    problem: ITC2019Problem,
    *,
    deadline: float,
    workers: int,
    random_seed: int,
    time_hints: Mapping[str, ITC2019TimeOption] | None = None,
    diagnostics: dict | None = None,
):
    """Return an independently validated hard-feasible timetable or ``None``.

    ``deadline`` is the sole wall-clock boundary.  The immutable input problem
    and caller-owned hints are never changed when construction fails.
    """

    diagnostics = diagnostics if diagnostics is not None else {}
    started = time.monotonic()
    total_budget = max(0.0, deadline - started)
    finalization_headroom = min(10.0, max(1.0, total_budget * 0.05))
    structural_deadline = deadline - finalization_headroom
    diagnostics["finalization_headroom_seconds"] = finalization_headroom
    reason = itc2019_structural_admission_reason(problem)
    if reason is not None:
        diagnostics["admission_reason"] = reason
        return None
    if time.monotonic() >= structural_deadline:
        diagnostics["deadline_exhausted"] = True
        return None

    build_started = time.monotonic()
    try:
        domains = _build_factorized_domains(problem, deadline=structural_deadline)
    except TimeoutError:
        diagnostics["deadline_exhausted"] = True
        return None
    class_by_id = {klass.id: klass for klass in problem.classes}
    lengths = {
        class_id: next(iter({option.length for option in domains.times[class_id]}))
        for class_id in class_by_id
    }

    blocked_by_room = {}
    for room in problem.rooms:
        blocked = 0
        for unavailable in room.unavailable:
            for week, day, slot in _occurrences(problem, unavailable):
                bit = (week * problem.nr_days + day) * problem.slots_per_day + slot
                blocked |= 1 << bit
        blocked_by_room[room.id] = blocked

    admitted_times = {}
    supported_rooms = {}
    for klass in problem.classes:
        allowed_rooms = {
            option.room_id for option in domains.rooms[klass.id] if option is not None
        }
        roomless = all(option is None for option in domains.rooms[klass.id])
        admitted = []
        for option in domains.times[klass.id]:
            mask = 0
            for week, day, slot in _occurrences(problem, option):
                bit = (week * problem.nr_days + day) * problem.slots_per_day + slot
                mask |= 1 << bit
            rooms = tuple(
                room_id
                for room_id in sorted(allowed_rooms)
                if not blocked_by_room[room_id] & mask
            )
            if not rooms and not roomless:
                continue
            option_index = len(admitted)
            admitted.append(option)
            supported_rooms[(klass.id, option_index)] = rooms or (None,)
        if not admitted:
            diagnostics["empty_admitted_domain"] = klass.id
            return None
        admitted_times[klass.id] = tuple(admitted)

    same_room = _UnionFind(class_by_id)
    pair_rules = defaultdict(list)
    for distribution in problem.distributions:
        if not distribution.required:
            continue
        base, parameters = _distribution_spec(distribution.type)
        class_ids = tuple(dict.fromkeys(distribution.class_ids))
        for first_id, second_id in combinations(class_ids, 2):
            pair_rules[(first_id, second_id)].append((base, parameters))
            if base == "SameRoom":
                same_room.union(first_id, second_id)

    model = cp_model.CpModel()
    day_variables = {}
    start_variables = {}
    choice_variables = {}
    for klass in problem.classes:
        class_id = klass.id
        tuples = tuple(
            (
                _singleton_day(option.days),
                option.start,
                option_index,
            )
            for option_index, option in enumerate(admitted_times[class_id])
        )
        day_variables[class_id] = model.new_int_var_from_domain(
            cp_model.Domain.from_values(sorted({item[0] for item in tuples})),
            f"structural_day_{class_id}",
        )
        start_variables[class_id] = model.new_int_var_from_domain(
            cp_model.Domain.from_values(sorted({item[1] for item in tuples})),
            f"structural_start_{class_id}",
        )
        choice_variables[class_id] = model.new_int_var(
            0,
            len(admitted_times[class_id]) - 1,
            f"structural_choice_{class_id}",
        )
        model.add_allowed_assignments(
            (
                day_variables[class_id],
                start_variables[class_id],
                choice_variables[class_id],
            ),
            tuples,
        )
        hint = None if time_hints is None else time_hints.get(class_id)
        if hint is not None:
            hint_signature = (hint.days, hint.start, hint.length, hint.weeks)
            hint_index = next(
                (
                    index
                    for index, option in enumerate(admitted_times[class_id])
                    if (option.days, option.start, option.length, option.weeks)
                    == hint_signature
                ),
                None,
            )
            if hint_index is not None:
                model.add_hint(choice_variables[class_id], hint_index)
        else:
            best_index = min(
                range(len(admitted_times[class_id])),
                key=lambda index: (admitted_times[class_id][index].penalty, index),
            )
            model.add_hint(choice_variables[class_id], best_index)

    day_equal_literals = {}
    nonoverlap_pairs = set()

    def same_day(first_id, second_id):
        key = tuple(sorted((first_id, second_id)))
        literal = day_equal_literals.get(key)
        if literal is None:
            literal = model.new_bool_var(f"structural_same_day_{key[0]}_{key[1]}")
            model.add(
                day_variables[first_id] == day_variables[second_id]
            ).only_enforce_if(literal)
            model.add(
                day_variables[first_id] != day_variables[second_id]
            ).only_enforce_if(literal.Not())
            day_equal_literals[key] = literal
        return literal

    def add_nonoverlap(first_id, second_id):
        key = tuple(sorted((first_id, second_id)))
        if key in nonoverlap_pairs:
            return
        nonoverlap_pairs.add(key)
        first_before = model.new_bool_var(f"structural_before_{first_id}_{second_id}")
        second_before = model.new_bool_var(f"structural_before_{second_id}_{first_id}")
        model.add(
            start_variables[first_id] + lengths[first_id] <= start_variables[second_id]
        ).only_enforce_if(first_before)
        model.add(
            start_variables[second_id] + lengths[second_id] <= start_variables[first_id]
        ).only_enforce_if(second_before)
        model.add_bool_or(
            (same_day(first_id, second_id).Not(), first_before, second_before)
        )

    for (first_id, second_id), rules in pair_rules.items():
        first_start = start_variables[first_id]
        second_start = start_variables[second_id]
        for base, parameters in rules:
            if base == "SameRoom":
                continue
            if base == "SameDays":
                model.add(day_variables[first_id] == day_variables[second_id])
            elif base == "DifferentDays":
                model.add(day_variables[first_id] != day_variables[second_id])
            elif base == "SameStart":
                model.add(first_start == second_start)
            elif base == "SameTime":
                first_length = lengths[first_id]
                second_length = lengths[second_id]
                if first_length == second_length:
                    model.add(first_start == second_start)
                elif first_length > second_length:
                    model.add(first_start <= second_start)
                    model.add(
                        second_start + second_length <= first_start + first_length
                    )
                else:
                    model.add(second_start <= first_start)
                    model.add(
                        first_start + first_length <= second_start + second_length
                    )
            elif base in {"NotOverlap", "SameAttendees"}:
                add_nonoverlap(first_id, second_id)
            elif base == "WorkDay":
                (maximum_span,) = parameters
                equal = same_day(first_id, second_id)
                model.add(
                    first_start + lengths[first_id] - second_start <= maximum_span
                ).only_enforce_if(equal)
                model.add(
                    second_start + lengths[second_id] - first_start <= maximum_span
                ).only_enforce_if(equal)
            elif base == "Precedence":
                model.add(
                    day_variables[first_id] * problem.slots_per_day
                    + first_start
                    + lengths[first_id]
                    <= day_variables[second_id] * problem.slots_per_day + second_start
                )

    component_members = defaultdict(list)
    for class_id in class_by_id:
        component_members[same_room.find(class_id)].append(class_id)
    implied_nonoverlap = 0
    for members in component_members.values():
        if len(members) < 2:
            continue
        for first_id, second_id in combinations(sorted(members), 2):
            before = len(nonoverlap_pairs)
            add_nonoverlap(first_id, second_id)
            implied_nonoverlap += len(nonoverlap_pairs) - before
    diagnostics["implied_same_room_nonoverlap"] = implied_nonoverlap
    fixed_components_by_room = defaultdict(list)
    for root, members in component_members.items():
        common_rooms = set.intersection(
            *[
                {option.room_id for option in class_by_id[class_id].room_options}
                for class_id in members
            ]
        )
        if len(common_rooms) == 1:
            fixed_components_by_room[next(iter(common_rooms))].append(root)
    implied_fixed_room_nonoverlap = 0
    for roots in fixed_components_by_room.values():
        for first_root, second_root in combinations(sorted(roots), 2):
            for first_id in component_members[first_root]:
                for second_id in component_members[second_root]:
                    before = len(nonoverlap_pairs)
                    add_nonoverlap(first_id, second_id)
                    implied_fixed_room_nonoverlap += len(nonoverlap_pairs) - before
    diagnostics["implied_fixed_room_nonoverlap"] = implied_fixed_room_nonoverlap

    # Hall-style room-pool capacity closure.  For every small room-domain set S,
    # all classes whose complete room domain is a subset of S consume one unit of
    # the |S| resources.  Optional day intervals make the condition exact in the
    # compact singleton-day calendar without introducing room-choice booleans.
    component_room_domains = {}
    for root, members in component_members.items():
        room_sets = [
            {option.room_id for option in class_by_id[class_id].room_options}
            for class_id in members
        ]
        common_rooms = set.intersection(*room_sets)
        if common_rooms:
            component_room_domains[root] = frozenset(common_rooms)
    room_pools = sorted(
        {
            room_domain
            for room_domain in component_room_domains.values()
            if 1 <= len(room_domain) <= 16
        },
        key=lambda item: (len(item), tuple(sorted(item))),
    )
    optional_intervals = {}

    def interval_for(class_id, day):
        key = (class_id, day)
        interval = optional_intervals.get(key)
        if interval is not None:
            return interval
        active = model.new_bool_var(f"structural_day_active_{class_id}_{day}")
        model.add(day_variables[class_id] == day).only_enforce_if(active)
        model.add(day_variables[class_id] != day).only_enforce_if(active.Not())
        interval = model.new_optional_fixed_size_interval_var(
            start_variables[class_id],
            lengths[class_id],
            active,
            f"structural_interval_{class_id}_{day}",
        )
        optional_intervals[key] = interval
        return interval

    capacity_constraints = 0
    for pool in room_pools:
        members = [
            class_id
            for root, room_domain in component_room_domains.items()
            if room_domain.issubset(pool)
            for class_id in component_members[root]
        ]
        if len(members) <= len(pool):
            continue
        possible_days = sorted(
            {
                _singleton_day(option.days)
                for class_id in members
                for option in admitted_times[class_id]
            }
        )
        for day in possible_days:
            intervals = [
                interval_for(class_id, day)
                for class_id in members
                if any(
                    _singleton_day(option.days) == day
                    for option in admitted_times[class_id]
                )
            ]
            if len(intervals) > len(pool):
                model.add_cumulative(intervals, [1] * len(intervals), len(pool))
                capacity_constraints += 1
    diagnostics["structural_room_pools"] = len(room_pools)
    diagnostics["structural_capacity_constraints"] = capacity_constraints
    diagnostics["time_model_build_seconds"] = time.monotonic() - build_started

    remaining = structural_deadline - time.monotonic()
    if remaining <= 1.0:
        diagnostics["deadline_exhausted"] = True
        return None
    room_reserve = min(20.0, max(2.0, remaining * 0.2))
    time_solver = cp_model.CpSolver()
    time_solver.parameters.max_time_in_seconds = max(0.01, remaining - room_reserve)
    time_solver.parameters.num_search_workers = max(1, int(workers))
    time_solver.parameters.random_seed = int(random_seed)
    time_solver.parameters.randomize_search = True
    time_solver.parameters.search_branching = cp_model.HINT_SEARCH
    solve_started = time.monotonic()
    time_status = time_solver.solve(model)
    diagnostics["time_solve_seconds"] = time.monotonic() - solve_started
    diagnostics["time_status"] = time_solver.status_name(time_status)
    if time_status not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        return None

    selected_indices = {
        class_id: int(time_solver.value(choice_variables[class_id]))
        for class_id in class_by_id
    }
    selected_times = {
        class_id: admitted_times[class_id][selected_indices[class_id]]
        for class_id in class_by_id
    }

    room_ids = tuple(sorted(room.id for room in problem.rooms))
    room_codes = {room_id: index for index, room_id in enumerate(room_ids)}
    room_model = cp_model.CpModel()
    component_variables = {}
    component_room_ids = {}
    roomless_components = set()
    for root, members in component_members.items():
        room_sets = [
            set(supported_rooms[(class_id, selected_indices[class_id])])
            for class_id in members
        ]
        common_rooms = set.intersection(*room_sets)
        if common_rooms == {None}:
            roomless_components.add(root)
            component_room_ids[root] = (None,)
            continue
        common_rooms.discard(None)
        if not common_rooms:
            diagnostics["empty_same_room_intersection"] = tuple(sorted(members))
            return None
        ordered_rooms = tuple(sorted(common_rooms))
        component_room_ids[root] = ordered_rooms
        component_variables[root] = room_model.new_int_var_from_domain(
            cp_model.Domain.from_values([room_codes[item] for item in ordered_rooms]),
            f"structural_room_{root}",
        )

    active_by_occurrence = defaultdict(list)
    for class_id, option in selected_times.items():
        root = same_room.find(class_id)
        if root in roomless_components:
            continue
        for occurrence in _occurrences(problem, option):
            active_by_occurrence[occurrence].append(root)
    occupancy_cliques = set()
    for roots in active_by_occurrence.values():
        if len(roots) != len(set(roots)):
            diagnostics["same_room_component_overlap"] = True
            return None
        clique = tuple(sorted(roots))
        if len(clique) > 1:
            occupancy_cliques.add(clique)
    for clique in occupancy_cliques:
        room_model.add_all_different([component_variables[root] for root in clique])
    diagnostics["room_components"] = len(component_members)
    diagnostics["occupancy_cliques"] = len(occupancy_cliques)

    travel = _travel_values(problem)
    travel_constraints = 0
    forbidden_travel_pairs = 0
    for (first_id, second_id), rules in pair_rules.items():
        if not any(base == "SameAttendees" for base, _ in rules):
            continue
        first_time = selected_times[first_id]
        second_time = selected_times[second_id]
        if not _masks_overlap(first_time.days, second_time.days):
            continue
        first_root = same_room.find(first_id)
        second_root = same_room.find(second_id)
        if first_root in roomless_components or second_root in roomless_components:
            continue
        first_end = first_time.start + first_time.length
        second_end = second_time.start + second_time.length
        gap = (
            second_time.start - first_end
            if first_end <= second_time.start
            else first_time.start - second_end
        )
        if gap < 0:
            diagnostics["same_attendees_time_overlap"] = (first_id, second_id)
            return None
        forbidden = []
        for first_room in component_room_ids[first_root]:
            for second_room in component_room_ids[second_root]:
                distance = travel.get(
                    (first_room, second_room),
                    travel.get((second_room, first_room), 0),
                )
                if distance > gap:
                    forbidden.append((room_codes[first_room], room_codes[second_room]))
        if not forbidden:
            continue
        forbidden_travel_pairs += len(forbidden)
        if first_root == second_root:
            for code in {first for first, second in forbidden if first == second}:
                room_model.add(component_variables[first_root] != code)
        else:
            room_model.add_forbidden_assignments(
                (component_variables[first_root], component_variables[second_root]),
                forbidden,
            )
        travel_constraints += 1
    diagnostics["travel_constraints"] = travel_constraints
    diagnostics["forbidden_travel_pairs"] = forbidden_travel_pairs

    remaining = structural_deadline - time.monotonic()
    if remaining <= 0.25:
        diagnostics["deadline_exhausted"] = True
        return None
    room_solver = cp_model.CpSolver()
    room_solver.parameters.max_time_in_seconds = max(0.01, remaining - 0.1)
    room_solver.parameters.num_search_workers = max(1, int(workers))
    room_solver.parameters.random_seed = int(random_seed)
    room_started = time.monotonic()
    room_status = room_solver.solve(room_model)
    diagnostics["room_solve_seconds"] = time.monotonic() - room_started
    diagnostics["room_status"] = room_solver.status_name(room_status)
    if room_status not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        return None

    assigned_rooms = {}
    for class_id in class_by_id:
        root = same_room.find(class_id)
        if root in roomless_components:
            assigned_rooms[class_id] = None
        else:
            assigned_rooms[class_id] = room_ids[
                int(room_solver.value(component_variables[root]))
            ]
    candidate = tuple(
        ITC2019ClassPlacement(
            class_id=klass.id,
            days=selected_times[klass.id].days,
            start=selected_times[klass.id].start,
            weeks=selected_times[klass.id].weeks,
            room_id=assigned_rooms[klass.id],
        )
        for klass in problem.classes
    )
    errors = validate_itc2019_solution(problem, candidate, {})
    diagnostics["validation_error_count"] = len(errors)
    if errors:
        diagnostics["validation_first"] = tuple(errors[:5])
        return None
    score = score_itc2019_solution(problem, candidate, {})
    diagnostics["independent_score"] = score.total
    diagnostics["complete"] = True
    return candidate
