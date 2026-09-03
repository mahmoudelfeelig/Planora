"""Feasibility-first construction for large single-day ITC-2019 domains.

The constructor keeps time choice search sparse, learns exact room-resource
cuts from Hall deficiencies and room-assignment unsatisfiable cores, and only
returns an independently validated complete timetable.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from itertools import combinations
import random
import time

from ortools.sat.python import cp_model

from benchmarks.itc2019 import (
    ITC2019ClassPlacement,
    ITC2019Problem,
    _distribution_spec,
    _pair_distribution_satisfied,
    _travel_values,
    validate_itc2019_solution,
)


_TIME_BASES = {
    "DifferentDays",
    "DifferentWeeks",
    "MinGap",
    "NotOverlap",
    "Precedence",
    "SameAttendees",
    "SameDays",
    "SameStart",
    "SameTime",
    "SameWeeks",
    "WorkDay",
}
_ROOM_BASES = {"DifferentRoom", "SameAttendees", "SameRoom"}


@dataclass(frozen=True, slots=True)
class _TimeValue:
    original_index: int
    day: int
    start: int
    end: int
    weeks: int
    first_week: int
    penalty: int


@dataclass(frozen=True, slots=True)
class _Edge:
    left: int
    right: int
    base: str
    parameters: tuple[int, ...]


def itc2019_resource_seed_admission_reason(problem: ITC2019Problem) -> str | None:
    """Return why this sparse representation would not be lossless."""

    if not problem.rooms:
        return "resource_seed_requires_rooms"
    for klass in problem.classes:
        if not klass.time_options:
            return f"resource_seed_empty_time_domain:{klass.id}"
        if any(option.days.count("1") != 1 for option in klass.time_options):
            return f"resource_seed_requires_single_day_options:{klass.id}"
        if any("1" not in option.weeks for option in klass.time_options):
            return f"resource_seed_empty_week_mask:{klass.id}"
        if klass.room_required and not klass.room_options:
            return f"resource_seed_empty_room_domain:{klass.id}"
    supported = _TIME_BASES | _ROOM_BASES
    for distribution in problem.distributions:
        if not distribution.required:
            continue
        base, _parameters = _distribution_spec(distribution.type)
        if base not in supported:
            return f"resource_seed_required_distribution_not_supported:{base}"
    return None


def should_construct_itc2019_resource_seed(problem: ITC2019Problem) -> bool:
    """Admit only large option-rich instances that benefit from this lane."""

    classes = problem.classes
    return (
        len(classes) >= 500
        and len(classes) <= 1_000
        and len(problem.rooms) <= 64
        and sum(len(klass.time_options) for klass in classes) >= 10_000
        and itc2019_resource_seed_admission_reason(problem) is None
    )


def _occurrence_slots(problem: ITC2019Problem, option):
    for week, week_active in enumerate(option.weeks):
        if week_active != "1":
            continue
        for day, day_active in enumerate(option.days):
            if day_active != "1":
                continue
            base = (week * problem.nr_days + day) * problem.slots_per_day
            for slot in range(option.start, option.start + option.length):
                yield base + slot


def _compatible(edge: _Edge, left: _TimeValue, right: _TimeValue) -> bool:
    day_overlap = left.day == right.day
    week_overlap = bool(left.weeks & right.weeks)
    if edge.base == "DifferentWeeks":
        return not week_overlap
    if edge.base == "DifferentDays":
        return not day_overlap
    if edge.base == "SameStart":
        return left.start == right.start
    if edge.base == "SameWeeks":
        intersection = left.weeks & right.weeks
        return intersection == left.weeks or intersection == right.weeks
    if edge.base == "SameDays":
        return day_overlap
    if edge.base == "SameTime":
        return (left.start <= right.start and right.end <= left.end) or (
            right.start <= left.start and left.end <= right.end
        )
    if edge.base in {"SameAttendees", "NotOverlap"}:
        return (
            not day_overlap
            or not week_overlap
            or left.end <= right.start
            or right.end <= left.start
        )
    if edge.base == "Precedence":
        if left.first_week != right.first_week:
            return left.first_week < right.first_week
        if left.day != right.day:
            return left.day < right.day
        return left.end <= right.start
    if edge.base == "WorkDay":
        return (
            not day_overlap
            or not week_overlap
            or max(left.end, right.end) - min(left.start, right.start)
            <= edge.parameters[0]
        )
    if edge.base == "MinGap":
        return (
            not day_overlap
            or not week_overlap
            or left.end + edge.parameters[0] <= right.start
            or right.end + edge.parameters[0] <= left.start
        )
    raise ValueError(f"unsupported resource-seed edge {edge.base}")


class _SearchState:
    def __init__(self, problem: ITC2019Problem, deadline: float, seed: int):
        self.problem = problem
        self.rng = random.Random(seed)
        self.class_ids = tuple(klass.id for klass in problem.classes)
        self.ordinal = {
            class_id: index for index, class_id in enumerate(self.class_ids)
        }
        rooms = {room.id: room for room in problem.rooms}
        blocked = {}
        for room_id, room in rooms.items():
            slots = set()
            for unavailable in room.unavailable:
                slots.update(_occurrence_slots(problem, unavailable))
            blocked[room_id] = frozenset(slots)

        self.values: list[list[_TimeValue]] = []
        self.slots: list[list[frozenset[int]]] = []
        self.room_domains: list[list[tuple[str, ...]]] = []
        for variable, klass in enumerate(problem.classes):
            admitted = []
            value_slots = []
            value_rooms = []
            for original_index, option in enumerate(klass.time_options):
                occupied = frozenset(_occurrence_slots(problem, option))
                available = tuple(
                    sorted(
                        room_option.room_id
                        for room_option in klass.room_options
                        if not occupied.intersection(blocked[room_option.room_id])
                    )
                )
                if klass.room_required and not available:
                    continue
                admitted.append(
                    _TimeValue(
                        original_index=original_index,
                        day=option.days.index("1"),
                        start=option.start,
                        end=option.start + option.length,
                        weeks=int(option.weeks, 2),
                        first_week=option.weeks.index("1"),
                        penalty=option.penalty,
                    )
                )
                value_slots.append(occupied)
                value_rooms.append(available)
                if original_index % 256 == 0 and time.monotonic() >= deadline:
                    raise TimeoutError("resource-seed domain build exceeded deadline")
            if not admitted:
                raise ValueError(f"class {klass.id} has no room-supported time option")
            self.values.append(admitted)
            self.slots.append(value_slots)
            self.room_domains.append(value_rooms)
            if variable % 16 == 0 and time.monotonic() >= deadline:
                raise TimeoutError("resource-seed domain build exceeded deadline")

        self.edges: list[_Edge] = []
        seen = set()
        for distribution in problem.distributions:
            if not distribution.required:
                continue
            base, parameters = _distribution_spec(distribution.type)
            if base not in _TIME_BASES:
                continue
            ids = tuple(dict.fromkeys(distribution.class_ids))
            for first_id, second_id in combinations(ids, 2):
                left = self.ordinal[first_id]
                right = self.ordinal[second_id]
                if base != "Precedence" and left > right:
                    left, right = right, left
                key = left, right, base, parameters
                if key not in seen:
                    seen.add(key)
                    self.edges.append(_Edge(left, right, base, parameters))
        self.original_edge_count = len(self.edges)
        self.incident: list[list[int]] = [[] for _ in self.class_ids]
        for edge_index, edge in enumerate(self.edges):
            self.incident[edge.left].append(edge_index)
            self.incident[edge.right].append(edge_index)
        self._add_room_implications()

    def _add_edge(self, edge: _Edge) -> None:
        edge_index = len(self.edges)
        self.edges.append(edge)
        self.incident[edge.left].append(edge_index)
        self.incident[edge.right].append(edge_index)

    def _add_room_implications(self) -> None:
        singleton_groups = defaultdict(list)
        for variable, domains in enumerate(self.room_domains):
            union = set().union(*domains)
            if len(union) == 1:
                singleton_groups[next(iter(union))].append(variable)
        singleton_pairs = {
            pair
            for variables in singleton_groups.values()
            for pair in combinations(sorted(variables), 2)
        }
        for left, right in sorted(singleton_pairs):
            self._add_edge(_Edge(left, right, "NotOverlap", ()))
        self.singleton_pair_cuts = len(singleton_pairs)

        travel = _travel_values(self.problem)
        min_travel = set()
        for edge in self.edges[: self.original_edge_count]:
            if edge.base != "SameAttendees":
                continue
            left_rooms = set().union(*self.room_domains[edge.left])
            right_rooms = set().union(*self.room_domains[edge.right])
            if not left_rooms or not right_rooms:
                continue
            distance = min(
                travel.get(
                    (left_room, right_room), travel.get((right_room, left_room), 0)
                )
                for left_room in left_rooms
                for right_room in right_rooms
            )
            if distance:
                min_travel.add((edge.left, edge.right, int(distance)))
        for left, right, distance in sorted(min_travel):
            self._add_edge(_Edge(left, right, "MinGap", (distance,)))
        self.minimum_travel_cuts = len(min_travel)

    def edge_ok(self, edge_index: int, assignment: list[int]) -> bool:
        edge = self.edges[edge_index]
        return _compatible(
            edge,
            self.values[edge.left][assignment[edge.left]],
            self.values[edge.right][assignment[edge.right]],
        )

    def candidate_conflicts(
        self, variable: int, candidate: int, assignment: list[int]
    ) -> int:
        value = self.values[variable][candidate]
        conflicts = 0
        for edge_index in self.incident[variable]:
            edge = self.edges[edge_index]
            other = edge.right if edge.left == variable else edge.left
            if assignment[other] < 0:
                continue
            other_value = self.values[other][assignment[other]]
            if edge.left == variable:
                valid = _compatible(edge, value, other_value)
            else:
                valid = _compatible(edge, other_value, value)
            conflicts += not valid
        return int(conflicts)

    def conflicts(self, assignment: list[int]) -> list[int]:
        return [
            index
            for index in range(len(self.edges))
            if not self.edge_ok(index, assignment)
        ]

    def domains(self) -> list[list[int]]:
        domains = [list(range(len(values))) for values in self.values]
        queue = deque(index for index, domain in enumerate(domains) if len(domain) == 1)
        while queue:
            fixed = queue.popleft()
            fixed_value = self.values[fixed][domains[fixed][0]]
            for edge_index in self.incident[fixed]:
                edge = self.edges[edge_index]
                other = edge.right if edge.left == fixed else edge.left
                if len(domains[other]) == 1:
                    continue
                kept = []
                for candidate in domains[other]:
                    candidate_value = self.values[other][candidate]
                    valid = (
                        _compatible(edge, fixed_value, candidate_value)
                        if edge.left == fixed
                        else _compatible(edge, candidate_value, fixed_value)
                    )
                    if valid:
                        kept.append(candidate)
                if not kept:
                    raise ValueError(
                        f"fixed propagation emptied class {self.class_ids[other]}"
                    )
                if len(kept) != len(domains[other]):
                    domains[other] = kept
                    if len(kept) == 1:
                        queue.append(other)
        return domains

    def solve_pairwise(self, deadline: float) -> list[int] | None:
        domains = self.domains()
        assignment = [-1] * len(domains)
        order = list(range(len(domains)))
        noise = {variable: self.rng.random() for variable in order}
        order.sort(
            key=lambda variable: (
                len(domains[variable]) != 1,
                -len(self.incident[variable]),
                noise[variable],
            )
        )
        for variable in order:
            best = 10**9
            choices = []
            for candidate in domains[variable]:
                score = self.candidate_conflicts(variable, candidate, assignment)
                if score < best:
                    best, choices = score, [candidate]
                elif score == best:
                    choices.append(candidate)
            assignment[variable] = self.rng.choice(choices)
        bad = self.conflicts(assignment)
        best_assignment = assignment[:]
        best_count = len(bad)
        iteration = 0
        tabu = {}
        while bad and time.monotonic() < deadline:
            iteration += 1
            edge = self.edges[self.rng.choice(bad)]
            endpoints = [edge.left, edge.right]
            self.rng.shuffle(endpoints)
            endpoints.sort(key=lambda variable: len(domains[variable]) == 1)
            variable = endpoints[0]
            if len(domains[variable]) == 1:
                variable = endpoints[1]
            old = assignment[variable]
            old_score = self.candidate_conflicts(variable, old, assignment)
            scored = []
            minimum = 10**9
            for candidate in domains[variable]:
                score = self.candidate_conflicts(variable, candidate, assignment)
                if score < minimum:
                    minimum, scored = score, [candidate]
                elif score == minimum:
                    scored.append(candidate)
            admissible = [
                candidate
                for candidate in scored
                if tabu.get((variable, candidate), 0) <= iteration
                or len(bad) - old_score + minimum < best_count
            ] or scored
            if minimum < old_score or self.rng.random() < 0.08:
                penalty = min(
                    self.values[variable][candidate].penalty for candidate in admissible
                )
                assignment[variable] = self.rng.choice(
                    [
                        candidate
                        for candidate in admissible
                        if self.values[variable][candidate].penalty == penalty
                    ]
                )
                tabu[(variable, old)] = iteration + 5 + self.rng.randrange(11)
            else:
                # Preserve bounded movement across local plateaus.  This is
                # the same one-edge ejection used by the proven prototype:
                # every accepted value remains scored against all incident
                # exact predicates, and the independent validator remains the
                # final admission gate.
                pool = [
                    candidate
                    for candidate in domains[variable]
                    if self.candidate_conflicts(variable, candidate, assignment)
                    <= old_score + 1
                ]
                if pool:
                    assignment[variable] = self.rng.choice(pool)
            bad = self.conflicts(assignment)
            if len(bad) < best_count:
                best_count = len(bad)
                best_assignment = assignment[:]
            if iteration % 2000 == 0 and len(bad) > best_count:
                assignment = best_assignment[:]
                bad = self.conflicts(assignment)
                tabu.clear()
        return best_assignment if best_count == 0 else None


def _hall_deficiency(variables, domains):
    match_room = {}

    def augment(variable, seen):
        for room_id in domains[variable]:
            if room_id in seen:
                continue
            seen.add(room_id)
            owner = match_room.get(room_id)
            if owner is None or augment(owner, seen):
                match_room[room_id] = variable
                return True
        return False

    unmatched = []
    for variable in sorted(variables, key=lambda item: (len(domains[item]), item)):
        if not augment(variable, set()):
            unmatched.append(variable)
    if not unmatched:
        return None
    matched_by_variable = {variable: room for room, variable in match_room.items()}
    classes = set(unmatched)
    rooms = set()
    pending = list(unmatched)
    while pending:
        variable = pending.pop()
        matched_room = matched_by_variable.get(variable)
        for room_id in domains[variable]:
            if room_id == matched_room or room_id in rooms:
                continue
            rooms.add(room_id)
            owner = match_room.get(room_id)
            if owner is not None and owner not in classes:
                classes.add(owner)
                pending.append(owner)
    return frozenset(classes), frozenset(rooms)


def _hall_deficiencies(state: _SearchState, assignment: list[int]):
    occupancy = defaultdict(list)
    for variable, choice in enumerate(assignment):
        if not state.room_domains[variable][choice]:
            continue
        for slot in state.slots[variable][choice]:
            occupancy[slot].append(variable)
    result = []
    seen = set()
    for slot, variables in occupancy.items():
        key = tuple(sorted(variables))
        if key in seen or len(key) < 2:
            continue
        seen.add(key)
        domains = {
            variable: state.room_domains[variable][assignment[variable]]
            for variable in key
        }
        deficient = _hall_deficiency(key, domains)
        if deficient is not None:
            result.append((slot, *deficient))
    return result


def _repair_hall(
    state: _SearchState, assignment: list[int], deadline: float
) -> list[int] | None:
    deficiencies = _hall_deficiencies(state, assignment)
    best_assignment = assignment[:]
    best_metric = (
        sum(max(1, len(core) - len(rooms)) for _, core, rooms in deficiencies),
        len(deficiencies),
    )
    learned = {}
    iteration = 0
    while deficiencies and time.monotonic() < deadline:
        iteration += 1
        for slot, core, rooms in deficiencies:
            learned[(slot, core, rooms)] = len(rooms)
        slot, core, rooms = max(
            deficiencies,
            key=lambda row: (len(row[1]) - len(row[2]), -len(row[1]), -row[0]),
        )
        candidates = []
        for variable in core:
            old = assignment[variable]
            for choice in range(len(state.values[variable])):
                if choice == old or state.candidate_conflicts(
                    variable, choice, assignment
                ):
                    continue
                if slot in state.slots[variable][choice] and set(
                    state.room_domains[variable][choice]
                ).issubset(rooms):
                    continue
                pressure = 0
                for (cut_slot, cut_core, cut_rooms), capacity in learned.items():
                    if variable not in cut_core:
                        continue
                    active = sum(
                        cut_slot
                        in state.slots[member][
                            choice if member == variable else assignment[member]
                        ]
                        and set(
                            state.room_domains[member][
                                choice if member == variable else assignment[member]
                            ]
                        ).issubset(cut_rooms)
                        for member in cut_core
                    )
                    pressure += max(0, active - capacity)
                candidates.append(
                    (
                        pressure,
                        state.values[variable][choice].penalty,
                        state.rng.random(),
                        variable,
                        choice,
                    )
                )
        if not candidates:
            return None
        exact = []
        for cheap in sorted(candidates)[:32]:
            variable, choice = cheap[-2:]
            old = assignment[variable]
            assignment[variable] = choice
            rows = _hall_deficiencies(state, assignment)
            metric = (
                sum(max(1, len(core) - len(rooms)) for _, core, rooms in rows),
                len(rows),
            )
            exact.append((metric, cheap, rows))
            assignment[variable] = old
            if time.monotonic() >= deadline:
                break
        if not exact:
            return None
        metric, cheap, deficiencies = min(exact, key=lambda row: (row[0], row[1]))
        variable, choice = cheap[-2:]
        assignment[variable] = choice
        if metric < best_metric:
            best_metric = metric
            best_assignment = assignment[:]
    return best_assignment if best_metric == (0, 0) else None


def _room_assignment_or_core(
    state: _SearchState,
    assignment: list[int],
    deadline: float,
    seed: int,
):
    if time.monotonic() >= deadline:
        return None, None
    problem = state.problem
    selected = {
        klass.id: klass.time_options[
            state.values[variable][assignment[variable]].original_index
        ]
        for variable, klass in enumerate(problem.classes)
    }
    room_ids = tuple(sorted(room.id for room in problem.rooms))
    code = {room_id: index for index, room_id in enumerate(room_ids)}
    model = cp_model.CpModel()
    variables = {}
    domains = {}
    room_by_code = {}
    occupancy = defaultdict(list)
    for variable, klass in enumerate(problem.classes):
        allowed = state.room_domains[variable][assignment[variable]]
        if not klass.room_required:
            pseudo = len(code) + variable
            domains[klass.id] = (pseudo,)
            room_by_code[(klass.id, pseudo)] = None
            variables[klass.id] = model.new_constant(pseudo)
        else:
            codes = tuple(code[room_id] for room_id in allowed)
            domains[klass.id] = codes
            for room_id in allowed:
                room_by_code[(klass.id, code[room_id])] = room_id
            variables[klass.id] = (
                model.new_constant(codes[0])
                if len(codes) == 1
                else model.new_int_var_from_domain(
                    cp_model.Domain.from_values(codes), f"room_{klass.id}"
                )
            )
        for slot in state.slots[variable][assignment[variable]]:
            occupancy[slot].append(klass.id)

    labels = {}

    def assumption(label):
        literal = model.new_bool_var(f"assume_{len(labels)}")
        labels[literal.Index()] = label
        model.add_assumption(literal)
        return literal

    collision_pairs = {
        tuple(sorted(pair))
        for class_ids in occupancy.values()
        for pair in combinations(class_ids, 2)
    }
    for offset, (left, right) in enumerate(sorted(collision_pairs)):
        model.add(variables[left] != variables[right]).only_enforce_if(
            assumption((state.ordinal[left], state.ordinal[right]))
        )
        if offset % 256 == 0 and time.monotonic() >= deadline:
            return None, None

    travel = _travel_values(problem)
    for distribution in problem.distributions:
        if not distribution.required:
            continue
        base, parameters = _distribution_spec(distribution.type)
        if base not in _ROOM_BASES:
            continue
        for left, right in combinations(dict.fromkeys(distribution.class_ids), 2):
            forbidden = []
            left_time = selected[left]
            right_time = selected[right]
            for left_code in domains[left]:
                left_placement = ITC2019ClassPlacement(
                    left,
                    left_time.days,
                    left_time.start,
                    left_time.weeks,
                    room_by_code[(left, left_code)],
                )
                for right_code in domains[right]:
                    right_placement = ITC2019ClassPlacement(
                        right,
                        right_time.days,
                        right_time.start,
                        right_time.weeks,
                        room_by_code[(right, right_code)],
                    )
                    if not _pair_distribution_satisfied(
                        base,
                        parameters,
                        left_placement,
                        left_time,
                        right_placement,
                        right_time,
                        travel,
                    ):
                        forbidden.append((left_code, right_code))
            if forbidden:
                model.add_forbidden_assignments(
                    (variables[left], variables[right]), forbidden
                ).only_enforce_if(
                    assumption((state.ordinal[left], state.ordinal[right]))
                )
            if time.monotonic() >= deadline:
                return None, None

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.01, deadline - time.monotonic())
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = seed
    solver.parameters.stop_after_first_solution = True
    solver.parameters.core_minimization_level = 2
    status = solver.solve(model)
    if status in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        placements = tuple(
            ITC2019ClassPlacement(
                klass.id,
                selected[klass.id].days,
                selected[klass.id].start,
                selected[klass.id].weeks,
                room_by_code[(klass.id, int(solver.value(variables[klass.id])))],
            )
            for klass in problem.classes
        )
        return placements, ()
    if status != cp_model.INFEASIBLE:
        return None, None
    core = set()
    for literal in solver.sufficient_assumptions_for_infeasibility():
        core.update(labels.get(literal, ()))
    return None, frozenset(core)


def construct_itc2019_resource_seed(
    problem: ITC2019Problem,
    *,
    deadline: float,
    workers: int = 1,
    random_seed: int = 17,
    diagnostics: dict | None = None,
):
    """Return a complete validator-clean timetable or fail closed."""

    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics["workers_requested"] = workers
    reason = itc2019_resource_seed_admission_reason(problem)
    if reason is not None:
        diagnostics["admission_reason"] = reason
        return None
    if time.monotonic() >= deadline:
        diagnostics["deadline_exhausted"] = True
        return None
    try:
        state = _SearchState(problem, deadline, random_seed)
    except (TimeoutError, ValueError) as exc:
        diagnostics["build_error"] = str(exc)
        diagnostics["deadline_exhausted"] = time.monotonic() >= deadline
        return None
    diagnostics.update(
        {
            "original_pair_edges": state.original_edge_count,
            "singleton_pair_cuts": state.singleton_pair_cuts,
            "minimum_travel_cuts": state.minimum_travel_cuts,
        }
    )
    assignment = state.solve_pairwise(min(deadline, time.monotonic() + 30.0))
    if assignment is None:
        diagnostics["stage"] = "pairwise_seed"
        diagnostics["deadline_exhausted"] = time.monotonic() >= deadline
        return None
    assignment = _repair_hall(state, assignment, deadline)
    if assignment is None:
        diagnostics["stage"] = "hall_repair"
        diagnostics["deadline_exhausted"] = time.monotonic() >= deadline
        return None
    diagnostics["hall_deficiencies"] = 0

    learned = []
    room_iterations = 0
    while time.monotonic() < deadline:
        placements, core = _room_assignment_or_core(
            state, assignment, deadline, random_seed + room_iterations
        )
        if placements is not None:
            errors = validate_itc2019_solution(problem, placements, {})
            diagnostics["room_repair_iterations"] = room_iterations
            diagnostics["validation_errors"] = tuple(errors)
            diagnostics["deadline_exhausted"] = time.monotonic() > deadline
            if not errors and time.monotonic() <= deadline:
                return placements
            return None
        if not core:
            diagnostics["stage"] = "room_assignment"
            diagnostics["deadline_exhausted"] = time.monotonic() >= deadline
            return None
        signature = tuple(sorted((variable, assignment[variable]) for variable in core))
        if signature not in learned:
            learned.append(signature)
        candidates = []
        for variable in core:
            old = assignment[variable]
            for choice in range(len(state.values[variable])):
                if choice == old or state.candidate_conflicts(
                    variable, choice, assignment
                ):
                    continue
                assignment[variable] = choice
                if _hall_deficiencies(state, assignment):
                    assignment[variable] = old
                    continue
                violated = sum(
                    all(
                        assignment[member] == learned_choice
                        for member, learned_choice in nogood
                    )
                    for nogood in learned
                )
                candidates.append(
                    (
                        violated,
                        state.values[variable][choice].penalty,
                        -len(state.room_domains[variable][choice]),
                        state.rng.random(),
                        variable,
                        choice,
                    )
                )
                assignment[variable] = old
                if time.monotonic() >= deadline:
                    break
            if time.monotonic() >= deadline:
                break
        if not candidates:
            diagnostics["stage"] = "room_core_repair"
            diagnostics["learned_room_nogoods"] = len(learned)
            diagnostics["deadline_exhausted"] = time.monotonic() >= deadline
            return None
        _violated, _penalty, _flexibility, _noise, variable, choice = min(candidates)
        assignment[variable] = choice
        room_iterations += 1
    diagnostics["stage"] = "room_core_repair"
    diagnostics["learned_room_nogoods"] = len(learned)
    diagnostics["deadline_exhausted"] = True
    return None


__all__ = [
    "construct_itc2019_resource_seed",
    "itc2019_resource_seed_admission_reason",
    "should_construct_itc2019_resource_seed",
]
