from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import random
import time
from typing import Any, Callable, Mapping, Sequence

from benchmarks.itc2007 import score_itc2007_instance_schedule
from core.itc2007_constructive import ITC2007ConstructiveResult
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]

_STRATEGIES = ("balanced", "compact", "spread", "room")
_FORBIDDEN_COST = 10**12


class _DeadlineReached(RuntimeError):
    pass


def _check_deadline(deadline: float) -> None:
    if time.perf_counter() >= float(deadline):
        raise _DeadlineReached


def _eligibility(
    inst: Instance,
    *,
    deadline: float,
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    sla = getattr(inst, "sla_targets", {}) or {}
    metadata = sla.get("itc2007")
    if not str(sla.get("benchmark_family", "")).startswith("ITC-2007"):
        reasons.append("not_imported_itc2007")
    if not isinstance(metadata, dict):
        reasons.append("missing_itc2007_metadata")
    if len(inst.weeks) != 1:
        reasons.append("requires_single_week")
    if not inst.days or int(inst.slots_per_day) <= 0:
        reasons.append("requires_time_grid")
    if not inst.activities:
        reasons.append("requires_activities")
    if not inst.rooms:
        reasons.append("requires_rooms")
    for index, activity in enumerate(inst.activities.values()):
        if index % 64 == 0:
            _check_deadline(deadline)
        if int(activity.duration) != 1 or str(activity.kind) != "LEC":
            reasons.append("requires_unit_lectures")
            break
    if getattr(inst, "distribution_constraints", None):
        reasons.append("distribution_constraints_not_supported")
    if getattr(inst, "locked_activities", None):
        reasons.append("locks_not_supported")
    if getattr(inst, "generic_resources", None):
        reasons.append("generic_resources_not_supported")
    if getattr(inst, "precedence_rules", None):
        reasons.append("precedence_not_supported")
    if getattr(inst, "travel_time_rules", None):
        reasons.append("travel_not_supported")
    if getattr(inst, "room_closures", None):
        reasons.append("room_closures_not_supported")
    if getattr(inst, "calendar_rules", None):
        reasons.append("calendar_rules_not_supported")
    for index, staff in enumerate(inst.staff.values()):
        if index % 64 == 0:
            _check_deadline(deadline)
        if (
            staff.max_slots_per_day is not None
            or staff.max_slots_per_week is not None
            or bool(staff.prefers_block)
            or bool(staff.blocks_only)
        ):
            reasons.append("staff_load_rules_not_supported")
            break
    return not reasons, tuple(dict.fromkeys(reasons))


def _flag(inst: Instance, name: str, default: bool) -> bool:
    value = (getattr(inst, "hard_constraints", {}) or {}).get(name, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no"}


@dataclass(frozen=True)
class _Prepared:
    inst: Instance
    activities: tuple[int, ...]
    period_count: int
    slots_per_day: int
    course_code: tuple[str, ...]
    course_id: tuple[int, ...]
    course_activities: dict[str, tuple[int, ...]]
    course_students: dict[str, int]
    minimum_days: dict[str, int]
    weights: dict[str, int]
    curricula: tuple[str, ...]
    activity_curricula: tuple[tuple[int, ...], ...]
    resource_masks: tuple[int, ...]
    resource_degree: tuple[int, ...]
    domains: tuple[tuple[int, ...], ...]
    period_rooms: tuple[tuple[int, ...], ...]
    room_domains: tuple[dict[int, tuple[int, ...]], ...]
    universal_rooms: tuple[bool, ...]


def _prepare(inst: Instance, *, deadline: float) -> _Prepared:
    _check_deadline(deadline)
    metadata = dict(inst.sla_targets["itc2007"])
    course_students = {
        str(key): int(value)
        for key, value in dict(metadata.get("course_students") or {}).items()
    }
    minimum_days = {
        str(key): int(value)
        for key, value in dict(metadata.get("minimum_working_days") or {}).items()
    }
    raw_weights = dict(metadata.get("objective_weights") or {})
    weights = {
        name: int(raw_weights[name])
        for name in (
            "room_capacity",
            "minimum_working_days",
            "curriculum_compactness",
            "room_stability",
        )
        if name in raw_weights
    }
    if len(weights) != 4:
        raise ValueError("incomplete_itc2007_objective_weights")

    activities = tuple(sorted(int(value) for value in inst.activities))
    course_code_by_id = {
        int(course_id): str(course.code) for course_id, course in inst.courses.items()
    }
    course_code = tuple(
        course_code_by_id[int(inst.activities[activity_id].course_id)]
        for activity_id in activities
    )
    course_id = tuple(
        int(inst.activities[activity_id].course_id) for activity_id in activities
    )
    known_codes = set(course_code)
    if known_codes - set(course_students) or known_codes - set(minimum_days):
        raise ValueError("incomplete_itc2007_course_metadata")
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, code in enumerate(course_code):
        grouped[code].append(index)
    course_activities = {
        code: tuple(indices) for code, indices in sorted(grouped.items())
    }

    raw_curricula = {
        str(name): tuple(str(value) for value in list(members or ()))
        for name, members in dict(metadata.get("curricula") or {}).items()
    }
    unknown_curriculum_courses = {
        code for members in raw_curricula.values() for code in members
    } - known_codes
    if unknown_curriculum_courses:
        raise ValueError("unknown_curriculum_course")
    curricula = tuple(sorted(raw_curricula))
    curriculum_index = {name: index for index, name in enumerate(curricula)}
    curricula_by_code: dict[str, list[int]] = defaultdict(list)
    for name, members in raw_curricula.items():
        for code in members:
            curricula_by_code[code].append(curriculum_index[name])
    activity_curricula = tuple(
        tuple(sorted(curricula_by_code.get(code, ()))) for code in course_code
    )

    resource_keys: list[tuple[str, int]] = []
    activity_resource_keys: list[tuple[tuple[str, int], ...]] = []
    for index, activity_id in enumerate(activities):
        activity = inst.activities[activity_id]
        keys = {
            ("course", int(activity.course_id)),
            ("staff", int(activity.prof_id)),
            *(("group", int(group_id)) for group_id in activity.group_ids),
            *(
                ("curriculum", int(curriculum))
                for curriculum in activity_curricula[index]
            ),
        }
        ordered = tuple(sorted(keys))
        activity_resource_keys.append(ordered)
        resource_keys.extend(ordered)
        if index % 64 == 0:
            _check_deadline(deadline)
    resource_index = {
        key: index for index, key in enumerate(sorted(set(resource_keys)))
    }
    resource_frequency = Counter(key for keys in activity_resource_keys for key in keys)
    resource_masks = tuple(
        sum(1 << resource_index[key] for key in keys) for keys in activity_resource_keys
    )
    resource_degree = tuple(
        sum(resource_frequency[key] - 1 for key in keys)
        for keys in activity_resource_keys
    )

    slots_per_day = int(inst.slots_per_day)
    period_count = len(inst.days) * slots_per_day
    policy = getattr(inst, "institutional_policy", {}) or {}
    configured_starts = policy.get("standard_start_slots", ())
    if isinstance(configured_starts, dict):
        configured_starts = configured_starts.get(
            "LEC", configured_starts.get("default", ())
        )
    standard_starts = {int(value) for value in (configured_starts or ())}
    enforce_starts = _flag(inst, "enforce_standard_start_slots", False)
    allowed_day_slots = policy.get("allowed_day_slots", {}) or {}

    period_rooms: list[tuple[int, ...]] = []
    for period in range(period_count):
        day = str(inst.days[period // slots_per_day])
        slot = int(period % slots_per_day)
        period_rooms.append(
            tuple(
                sorted(
                    int(room_id)
                    for room_id, room in inst.rooms.items()
                    if str(room.room_type) == "LECTURE"
                    and (room.availability is None or (day, slot) in room.availability)
                )
            )
        )
    hard_capacity = _flag(inst, "enforce_room_capacity", False)
    domains: list[tuple[int, ...]] = []
    room_domains: list[dict[int, tuple[int, ...]]] = []
    for index, activity_id in enumerate(activities):
        _check_deadline(deadline)
        activity = inst.activities[activity_id]
        staff = inst.staff.get(int(activity.prof_id))
        forbidden = {
            (str(day), int(slot))
            for day, slot in (inst.activity_unavailability or {}).get(
                activity_id, set()
            )
        }
        per_period: dict[int, tuple[int, ...]] = {}
        for period in range(period_count):
            day = str(inst.days[period // slots_per_day])
            slot = int(period % slots_per_day)
            configured_day = allowed_day_slots.get(
                day, allowed_day_slots.get("default")
            )
            if (day, slot) in forbidden:
                continue
            if enforce_starts and standard_starts and slot not in standard_starts:
                continue
            if configured_day is not None and slot not in {
                int(value) for value in configured_day
            }:
                continue
            if staff is None or day not in staff.available_days:
                continue
            if staff.available_weeks is not None and int(activity.week) not in {
                int(value) for value in staff.available_weeks
            }:
                continue
            rooms = period_rooms[period]
            if hard_capacity:
                rooms = tuple(
                    room_id
                    for room_id in rooms
                    if int(inst.rooms[room_id].capacity)
                    >= int(course_students[course_code[index]])
                )
            if rooms:
                per_period[period] = tuple(rooms)
        domains.append(tuple(sorted(per_period)))
        room_domains.append(per_period)

    universal_rooms = tuple(
        all(
            period not in room_domains[index]
            or room_domains[index][period] == period_rooms[period]
            for index in range(len(activities))
        )
        for period in range(period_count)
    )
    return _Prepared(
        inst=inst,
        activities=activities,
        period_count=period_count,
        slots_per_day=slots_per_day,
        course_code=course_code,
        course_id=course_id,
        course_activities=course_activities,
        course_students=course_students,
        minimum_days=minimum_days,
        weights=weights,
        curricula=curricula,
        activity_curricula=activity_curricula,
        resource_masks=resource_masks,
        resource_degree=resource_degree,
        domains=tuple(domains),
        period_rooms=tuple(period_rooms),
        room_domains=tuple(room_domains),
        universal_rooms=universal_rooms,
    )


def _room_matching(
    prepared: _Prepared,
    event_indices: Sequence[int],
    period: int,
) -> dict[int, int] | None:
    room_event: dict[int, int] = {}
    ordered = sorted(
        (int(value) for value in event_indices),
        key=lambda event: (
            len(prepared.room_domains[event].get(period, ())),
            -prepared.course_students[prepared.course_code[event]],
            prepared.activities[event],
        ),
    )

    def augment(event: int, seen: set[int]) -> bool:
        for room in prepared.room_domains[event].get(period, ()):
            if room in seen:
                continue
            seen.add(room)
            occupant = room_event.get(room)
            if occupant is None or augment(occupant, seen):
                room_event[room] = event
                return True
        return False

    for event in ordered:
        if not augment(event, set()):
            return None
    return {event: room for room, event in room_event.items()}


class _Attempt:
    def __init__(
        self,
        prepared: _Prepared,
        *,
        deadline: float,
        seed: int,
        strategy: str,
        branch_width: int,
        node_limit: int,
    ) -> None:
        self.prepared = prepared
        self.deadline = float(deadline)
        self.strategy = str(strategy)
        self.branch_width = max(2, int(branch_width))
        self.node_limit = max(1, int(node_limit))
        rng = random.Random(int(seed))
        self.jitter = tuple(
            tuple(rng.random() for _ in range(prepared.period_count))
            for _ in prepared.activities
        )
        self.event_jitter = tuple(rng.random() for _ in prepared.activities)
        self.assignment = [-1] * len(prepared.activities)
        self.period_resources = [0] * prepared.period_count
        self.period_events: list[list[int]] = [[] for _ in range(prepared.period_count)]
        self.course_day_counts: dict[str, list[int]] = {
            code: [0] * len(prepared.inst.days) for code in prepared.course_activities
        }
        self.curriculum_occupancy = [0] * len(prepared.curricula)
        self.unassigned = set(range(len(prepared.activities)))
        self.course_remaining = {
            code: len(events) for code, events in prepared.course_activities.items()
        }
        self.nodes = 0
        self.backtracks = 0
        self.max_depth = 0
        self.best_assigned = 0
        self.conflict_checks = 0
        self.hall_checks = 0
        self.matching_calls = 0
        self.dead_ends = 0

    def _basic_candidates(self, event: int) -> list[int]:
        mask = self.prepared.resource_masks[event]
        candidates: list[int] = []
        for period in self.prepared.domains[event]:
            self.conflict_checks += 1
            if self.period_resources[period] & mask:
                continue
            if len(self.period_events[period]) >= len(
                self.prepared.period_rooms[period]
            ):
                continue
            candidates.append(period)
        return candidates

    def _select_event(self) -> tuple[int, list[int]]:
        selected = -1
        selected_candidates: list[int] = []
        selected_key: tuple[int, int, int, int, float, int] | None = None
        for event in sorted(self.unassigned):
            candidates = self._basic_candidates(event)
            blocked = len(self.prepared.domains[event]) - len(candidates)
            code = self.prepared.course_code[event]
            key = (
                len(candidates),
                -blocked,
                -self.prepared.resource_degree[event],
                -self.course_remaining[code],
                self.event_jitter[event],
                self.prepared.activities[event],
            )
            if selected_key is None or key < selected_key:
                selected = event
                selected_candidates = candidates
                selected_key = key
                if not candidates:
                    break
        return selected, selected_candidates

    def _compactness_delta(self, event: int, period: int) -> int:
        day_start = period - period % self.prepared.slots_per_day
        within = period % self.prepared.slots_per_day
        delta = 0
        for curriculum in self.prepared.activity_curricula[event]:
            occupied = self.curriculum_occupancy[curriculum]
            left = within > 0 and bool(occupied & (1 << (period - 1)))
            right = within + 1 < self.prepared.slots_per_day and bool(
                occupied & (1 << (period + 1))
            )
            if not left and not right:
                delta += 1
            if left:
                left_left = within > 1 and bool(occupied & (1 << (period - 2)))
                if not left_left:
                    delta -= 1
            if right:
                right_right = within + 2 < self.prepared.slots_per_day and bool(
                    occupied & (1 << (period + 2))
                )
                if not right_right:
                    delta -= 1
            # The explicit boundary variable makes cross-day adjacency impossible.
            assert day_start <= period < day_start + self.prepared.slots_per_day
        return int(delta * self.prepared.weights["curriculum_compactness"])

    def _minimum_days_delta(self, event: int, period: int) -> int:
        code = self.prepared.course_code[event]
        counts = self.course_day_counts[code]
        before_days = sum(value > 0 for value in counts)
        day = period // self.prepared.slots_per_day
        after_days = before_days + int(counts[day] == 0)
        target = min(
            len(self.prepared.course_activities[code]),
            int(self.prepared.minimum_days[code]),
        )
        before = max(0, target - before_days)
        after = max(0, target - after_days)
        return int((after - before) * self.prepared.weights["minimum_working_days"])

    def _capacity_hint(self, event: int, period: int) -> int:
        code = self.prepared.course_code[event]
        demand = self.prepared.course_students[code]
        rooms = self.prepared.room_domains[event].get(period, ())
        return (
            min(
                (
                    max(0, demand - int(self.prepared.inst.rooms[room].capacity))
                    for room in rooms
                ),
                default=_FORBIDDEN_COST,
            )
            * self.prepared.weights["room_capacity"]
        )

    def _candidate_key(self, event: int, period: int) -> tuple[float, ...]:
        minimum_days = self._minimum_days_delta(event, period)
        compactness = self._compactness_delta(event, period)
        capacity = self._capacity_hint(event, period)
        load = len(self.period_events[period]) / max(
            1, len(self.prepared.period_rooms[period])
        )
        code = self.prepared.course_code[event]
        day = period // self.prepared.slots_per_day
        repeat = int(self.course_day_counts[code][day] > 0)
        jitter = self.jitter[event][period]
        if self.strategy == "compact":
            return (
                float(compactness),
                float(minimum_days),
                float(capacity),
                float(load),
                jitter,
                float(period),
            )
        if self.strategy == "spread":
            return (
                float(minimum_days),
                float(compactness),
                float(capacity),
                float(repeat),
                float(load),
                jitter,
                float(period),
            )
        if self.strategy == "room":
            return (
                float(capacity),
                float(load),
                float(minimum_days + compactness),
                jitter,
                float(period),
            )
        return (
            float(minimum_days + compactness + capacity),
            float(load),
            float(repeat),
            jitter,
            float(period),
        )

    def _room_feasible(self, event: int, period: int) -> bool:
        self.hall_checks += 1
        events = (*self.period_events[period], event)
        if len(events) > len(self.prepared.period_rooms[period]):
            return False
        if self.prepared.universal_rooms[period]:
            return True
        self.matching_calls += 1
        return _room_matching(self.prepared, events, period) is not None

    def _apply(self, event: int, period: int) -> None:
        self.assignment[event] = int(period)
        self.unassigned.remove(event)
        self.period_resources[period] |= self.prepared.resource_masks[event]
        self.period_events[period].append(event)
        code = self.prepared.course_code[event]
        self.course_remaining[code] -= 1
        day = period // self.prepared.slots_per_day
        self.course_day_counts[code][day] += 1
        for curriculum in self.prepared.activity_curricula[event]:
            self.curriculum_occupancy[curriculum] |= 1 << period

    def _undo(self, event: int, period: int) -> None:
        for curriculum in self.prepared.activity_curricula[event]:
            self.curriculum_occupancy[curriculum] &= ~(1 << period)
        code = self.prepared.course_code[event]
        day = period // self.prepared.slots_per_day
        self.course_day_counts[code][day] -= 1
        self.course_remaining[code] += 1
        self.period_events[period].remove(event)
        self.period_resources[period] &= ~self.prepared.resource_masks[event]
        self.unassigned.add(event)
        self.assignment[event] = -1

    def _search(self, depth: int) -> bool:
        _check_deadline(self.deadline)
        if not self.unassigned:
            return True
        if self.nodes >= self.node_limit:
            return False
        self.nodes += 1
        self.max_depth = max(self.max_depth, depth)
        self.best_assigned = max(
            self.best_assigned,
            len(self.prepared.activities) - len(self.unassigned),
        )
        event, candidates = self._select_event()
        if event < 0 or not candidates:
            self.dead_ends += 1
            return False
        ranked = sorted(
            candidates, key=lambda period: self._candidate_key(event, period)
        )
        for period in ranked[: self.branch_width]:
            _check_deadline(self.deadline)
            if not self._room_feasible(event, period):
                continue
            self._apply(event, period)
            if self._search(depth + 1):
                return True
            self._undo(event, period)
            self.backtracks += 1
            if self.nodes >= self.node_limit:
                break
        return False

    def solve(self) -> tuple[tuple[int, ...] | None, bool]:
        try:
            feasible = self._search(0)
        except _DeadlineReached:
            return None, True
        if not feasible:
            return None, time.perf_counter() >= self.deadline
        return tuple(self.assignment), False


def _dense_assignment(
    events: Sequence[int],
    rooms: Sequence[int],
    costs: Mapping[tuple[int, int], int],
    *,
    deadline: float | None = None,
) -> dict[int, int] | None:
    event_ids = tuple(int(value) for value in events)
    room_ids = tuple(int(value) for value in rooms)
    if len(event_ids) > len(room_ids):
        return None
    if not event_ids:
        return {}
    matrix = [
        [int(costs.get((event, room), _FORBIDDEN_COST)) for room in room_ids]
        for event in event_ids
    ]
    rows = len(event_ids)
    columns = len(room_ids)
    u = [0] * (rows + 1)
    v = [0] * (columns + 1)
    matching = [0] * (columns + 1)
    way = [0] * (columns + 1)
    for row in range(1, rows + 1):
        if deadline is not None:
            _check_deadline(deadline)
        matching[0] = row
        column0 = 0
        minimum = [_FORBIDDEN_COST] * (columns + 1)
        used = [False] * (columns + 1)
        while True:
            used[column0] = True
            row0 = matching[column0]
            delta = _FORBIDDEN_COST
            column1 = 0
            for column in range(1, columns + 1):
                if used[column]:
                    continue
                reduced = matrix[row0 - 1][column - 1] - u[row0] - v[column]
                if reduced < minimum[column]:
                    minimum[column] = int(reduced)
                    way[column] = int(column0)
                if minimum[column] < delta:
                    delta = int(minimum[column])
                    column1 = int(column)
            if column1 == 0 or delta >= _FORBIDDEN_COST:
                return None
            for column in range(columns + 1):
                if used[column]:
                    u[matching[column]] += delta
                    v[column] -= delta
                else:
                    minimum[column] -= delta
            column0 = column1
            if matching[column0] == 0:
                break
        while True:
            column1 = way[column0]
            matching[column0] = matching[column1]
            column0 = column1
            if column0 == 0:
                break
    result = {
        event_ids[matching[column] - 1]: room_ids[column - 1]
        for column in range(1, columns + 1)
        if matching[column]
    }
    if len(result) != len(event_ids) or any(
        costs.get((event, room), _FORBIDDEN_COST) >= _FORBIDDEN_COST
        for event, room in result.items()
    ):
        return None
    return result


def _room_objective(prepared: _Prepared, assignment: Mapping[int, int]) -> int:
    capacity = 0
    supports: dict[str, set[int]] = defaultdict(set)
    for event, room in assignment.items():
        code = prepared.course_code[event]
        capacity += (
            max(
                0,
                prepared.course_students[code]
                - int(prepared.inst.rooms[int(room)].capacity),
            )
            * prepared.weights["room_capacity"]
        )
        supports[code].add(int(room))
    stability = sum(
        max(0, len(rooms) - 1) * prepared.weights["room_stability"]
        for rooms in supports.values()
    )
    return int(capacity + stability)


def _lift_rooms(
    prepared: _Prepared,
    periods: Sequence[int],
    *,
    deadline: float,
    max_sweeps: int = 4,
) -> tuple[Schedule | None, dict[str, Any]]:
    by_period: dict[int, list[int]] = defaultdict(list)
    for event, period in enumerate(periods):
        by_period[int(period)].append(event)
    room_assignment: dict[int, int] = {}
    matching_calls = 0
    for period, events in sorted(by_period.items()):
        _check_deadline(deadline)
        rooms = prepared.period_rooms[period]
        costs: dict[tuple[int, int], int] = {}
        for event in events:
            code = prepared.course_code[event]
            for room in prepared.room_domains[event].get(period, ()):
                costs[(event, room)] = (
                    max(
                        0,
                        prepared.course_students[code]
                        - int(prepared.inst.rooms[room].capacity),
                    )
                    * prepared.weights["room_capacity"]
                )
        selected = _dense_assignment(sorted(events), rooms, costs, deadline=deadline)
        matching_calls += 1
        if selected is None:
            return None, {
                "status": "room_lift_infeasible",
                "matching_calls": matching_calls,
                "sweeps": 0,
            }
        room_assignment.update(selected)

    current = _room_objective(prepared, room_assignment)
    best = dict(room_assignment)
    best_objective = int(current)
    support: dict[str, Counter[int]] = defaultdict(Counter)
    for event, room in room_assignment.items():
        support[prepared.course_code[event]][room] += 1
    sweeps = 0
    for sweep in range(max(0, int(max_sweeps))):
        _check_deadline(deadline)
        changed = False
        order = sorted(by_period)
        if sweep % 2:
            order.reverse()
        for period in order:
            _check_deadline(deadline)
            events = tuple(sorted(by_period[period]))
            old = {event: room_assignment[event] for event in events}
            for event, room in old.items():
                code = prepared.course_code[event]
                support[code][room] -= 1
                if support[code][room] <= 0:
                    support[code].pop(room, None)
            costs: dict[tuple[int, int], int] = {}
            for event in events:
                code = prepared.course_code[event]
                demand = prepared.course_students[code]
                outside = support[code]
                for room in prepared.room_domains[event].get(period, ()):
                    costs[(event, room)] = (
                        max(0, demand - int(prepared.inst.rooms[room].capacity))
                        * prepared.weights["room_capacity"]
                        + int(bool(outside) and room not in outside)
                        * prepared.weights["room_stability"]
                    )
            selected = _dense_assignment(
                events,
                prepared.period_rooms[period],
                costs,
                deadline=deadline,
            )
            matching_calls += 1
            if selected is None:
                selected = old
            room_assignment.update(selected)
            for event, room in selected.items():
                support[prepared.course_code[event]][room] += 1
            candidate_objective = _room_objective(prepared, room_assignment)
            if candidate_objective <= current:
                changed = changed or candidate_objective < current or selected != old
                current = int(candidate_objective)
                if current < best_objective:
                    best_objective = current
                    best = dict(room_assignment)
            else:
                for event, room in selected.items():
                    code = prepared.course_code[event]
                    support[code][room] -= 1
                    if support[code][room] <= 0:
                        support[code].pop(room, None)
                room_assignment.update(old)
                for event, room in old.items():
                    support[prepared.course_code[event]][room] += 1
        sweeps += 1
        if not changed:
            break

    output: Schedule = {}
    for event, period in enumerate(periods):
        activity_id = prepared.activities[event]
        activity = prepared.inst.activities[activity_id]
        output[activity_id] = {
            "week": int(activity.week),
            "day": str(prepared.inst.days[int(period) // prepared.slots_per_day]),
            "slot": int(period) % prepared.slots_per_day,
            "duration": int(activity.duration),
            "room_id": int(best[event]),
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": [int(value) for value in activity.group_ids],
            "kind": str(activity.kind),
        }
    return output, {
        "status": "room_lifted",
        "matching_calls": matching_calls,
        "sweeps": sweeps,
        "room_objective": best_objective,
    }


def _empty_result(
    *,
    started: float,
    status: str,
    deadline_exhausted: bool,
    telemetry: list[dict[str, Any]] | None = None,
    assigned_activities: int = 0,
    nodes: int = 0,
    backtracks: int = 0,
    conflicts: int = 0,
) -> ITC2007ConstructiveResult:
    rows = telemetry or []
    return ITC2007ConstructiveResult(
        schedule=None,
        status=str(status),
        elapsed_seconds=float(time.perf_counter() - started),
        attempts=len(rows),
        assigned_activities=int(assigned_activities),
        nodes=int(nodes),
        backtracks=int(backtracks),
        conflicts_evaluated=int(conflicts),
        deadline_exhausted=bool(deadline_exhausted),
        attempt_telemetry=rows,
    )


def construct_itc2007_schedule_v2(
    inst: Instance,
    *,
    deadline: float,
    seed: int = 0,
    max_starts: int = 4,
    strategies: Sequence[str] | None = None,
    beam_width: int = 8,
    bundle_limit: int = 4,
    node_limit: int = 20_000,
    validator: Validator | None = None,
) -> ITC2007ConstructiveResult:
    """Build a validated CB-CTT incumbent by bounded multi-start coloring.

    The time phase uses dense activity indices, conflict-resource bitsets, and
    dynamic saturation/scarcity ordering. Room cardinality is the common fast
    path; heterogeneous availability or hard capacity activates exact Hall
    matching. Every complete coloring is lifted by exact per-period assignment,
    independently validated, and rescored with the persisted official objective.
    No partial or unvalidated schedule can escape the function.
    """

    started = time.perf_counter()
    absolute_deadline = float(deadline)
    if time.perf_counter() >= absolute_deadline:
        return _empty_result(
            started=started,
            status="deadline_exhausted",
            deadline_exhausted=True,
        )
    try:
        eligible, reasons = _eligibility(inst, deadline=absolute_deadline)
    except _DeadlineReached:
        return _empty_result(
            started=started,
            status="deadline_exhausted",
            deadline_exhausted=True,
        )
    if not eligible:
        return _empty_result(
            started=started,
            status="ineligible:" + ",".join(reasons),
            deadline_exhausted=False,
        )

    requested = tuple(str(value) for value in (strategies or _STRATEGIES))
    unknown = sorted(set(requested) - set(_STRATEGIES))
    if not requested or unknown:
        detail = "empty" if not requested else ",".join(unknown)
        return _empty_result(
            started=started,
            status="invalid_strategy:" + detail,
            deadline_exhausted=False,
        )
    requested_starts = max(1, int(max_starts))
    strategy_order = tuple(
        requested[index % len(requested)] for index in range(requested_starts)
    )
    initial_budget = max(0.0, absolute_deadline - started)
    completion_reserve = min(0.02, max(0.002, initial_budget * 0.02))
    work_deadline = max(started, absolute_deadline - completion_reserve)
    try:
        prepared = _prepare(inst, deadline=work_deadline)
    except _DeadlineReached:
        return _empty_result(
            started=started,
            status="deadline_exhausted",
            deadline_exhausted=True,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _empty_result(
            started=started,
            status=f"ineligible:{type(exc).__name__}:{exc}",
            deadline_exhausted=False,
        )

    telemetry: list[dict[str, Any]] = []
    total_nodes = 0
    total_backtracks = 0
    total_conflicts = 0
    best_partial = 0
    selected_schedule: Schedule | None = None
    selected_score: int | None = None
    selected_index: int | None = None
    deadline_hit = False
    saw_invalid = False
    completed_candidate_times: list[float] = []
    skipped_starts = 0

    for attempt_index, strategy in enumerate(strategy_order):
        now = time.perf_counter()
        if now >= work_deadline:
            deadline_hit = True
            break
        if selected_schedule is not None and completed_candidate_times:
            # A complete coloring is substantially more useful than several
            # truncated starts. Admit another trajectory only when measured
            # construction velocity says it has a realistic completion window.
            minimum_next_window = max(
                0.005,
                min(completed_candidate_times) * 0.65,
            )
            if work_deadline - now < minimum_next_window:
                skipped_starts = len(strategy_order) - attempt_index
                break
        attempt_deadline = work_deadline
        slice_seconds = max(0.0, attempt_deadline - now)
        lift_reserve = min(0.025, max(0.002, slice_seconds * 0.12))
        search_deadline = max(now, attempt_deadline - lift_reserve)
        attempt_seed = int(seed) + 104_729 * attempt_index
        attempt_started = time.perf_counter()
        attempt = _Attempt(
            prepared,
            deadline=search_deadline,
            seed=attempt_seed,
            strategy=strategy,
            branch_width=max(int(beam_width), int(bundle_limit)),
            node_limit=int(node_limit),
        )
        periods, attempt_exhausted = attempt.solve()
        search_finished = time.perf_counter()
        total_nodes += attempt.nodes
        total_backtracks += attempt.backtracks
        total_conflicts += attempt.conflict_checks
        best_partial = max(best_partial, attempt.best_assigned)
        row: dict[str, Any] = {
            "attempt_index": attempt_index,
            "strategy": strategy,
            "seed": attempt_seed,
            "selected": False,
            "status": "deadline_exhausted" if attempt_exhausted else "infeasible",
            "elapsed_seconds": float(search_finished - attempt_started),
            "search_seconds": float(search_finished - attempt_started),
            "nodes": attempt.nodes,
            "backtracks": attempt.backtracks,
            "max_depth": attempt.max_depth,
            "dead_ends": attempt.dead_ends,
            "assigned_activities": attempt.best_assigned,
            "conflict_checks": attempt.conflict_checks,
            "hall_checks": attempt.hall_checks,
            "matching_calls": attempt.matching_calls,
            "room_mode": (
                "cardinality_fast_path"
                if all(prepared.universal_rooms)
                else "hall_matching"
            ),
        }
        schedule: Schedule | None = None
        lift_meta: dict[str, Any] = {"status": "not_started"}
        if periods is not None and time.perf_counter() < attempt_deadline:
            try:
                schedule, lift_meta = _lift_rooms(
                    prepared,
                    periods,
                    deadline=attempt_deadline,
                )
            except _DeadlineReached:
                schedule = None
                lift_meta = {"status": "deadline_exhausted"}
                attempt_exhausted = True
        row["lift"] = lift_meta
        if schedule is not None and time.perf_counter() < absolute_deadline:
            errors = validate_schedule_against_instance(
                inst,
                schedule,
                strict_rooms=True,
                require_all_activities=True,
            )
            if not errors and validator is not None:
                try:
                    errors = [str(value) for value in validator(inst, schedule)]
                except Exception as exc:  # validator is an external fail-closed seam
                    errors = [f"validator_error:{type(exc).__name__}:{exc}"]
            if errors:
                saw_invalid = True
                row["status"] = "invalid_candidate"
                row["validation_errors"] = [str(value) for value in errors[:8]]
            elif time.perf_counter() < absolute_deadline:
                try:
                    official = score_itc2007_instance_schedule(inst, schedule)
                except (KeyError, TypeError, ValueError) as exc:
                    saw_invalid = True
                    row["status"] = "invalid_candidate"
                    row["validation_errors"] = [
                        f"official_rescore_error:{type(exc).__name__}:{exc}"
                    ]
                else:
                    if time.perf_counter() <= absolute_deadline:
                        row["status"] = "feasible"
                        row["assigned_activities"] = len(schedule)
                        row["official_score"] = official.to_dict()
                        completed_candidate_times.append(
                            float(time.perf_counter() - attempt_started)
                        )
                        if (
                            selected_score is None
                            or int(official.total) < selected_score
                        ):
                            selected_schedule = schedule
                            selected_score = int(official.total)
                            selected_index = attempt_index
                    else:
                        row["status"] = "deadline_exhausted"
                        attempt_exhausted = True
        elif periods is not None:
            row["status"] = "deadline_exhausted"
            attempt_exhausted = True
        row["elapsed_seconds"] = float(time.perf_counter() - attempt_started)
        telemetry.append(row)
        deadline_hit = deadline_hit or attempt_exhausted

    if selected_schedule is None:
        status = (
            "invalid_candidate"
            if saw_invalid and not deadline_hit
            else ("deadline_exhausted" if deadline_hit else "infeasible")
        )
        return _empty_result(
            started=started,
            status=status,
            deadline_exhausted=deadline_hit,
            telemetry=telemetry,
            assigned_activities=best_partial,
            nodes=total_nodes,
            backtracks=total_backtracks,
            conflicts=total_conflicts,
        )

    assert selected_index is not None and selected_score is not None
    for row in telemetry:
        row["selected"] = int(row["attempt_index"]) == selected_index
    telemetry[selected_index]["starts_requested"] = requested_starts
    telemetry[selected_index]["starts_completed"] = len(telemetry)
    telemetry[selected_index]["starts_skipped_for_budget"] = skipped_starts
    # The selected schedule was already validated and officially rescored in its
    # attempt. Recheck structure once at the return seam while the reserve holds.
    if time.perf_counter() >= absolute_deadline:
        telemetry[selected_index]["selected"] = False
        return _empty_result(
            started=started,
            status="deadline_exhausted",
            deadline_exhausted=True,
            telemetry=telemetry,
            assigned_activities=best_partial,
            nodes=total_nodes,
            backtracks=total_backtracks,
            conflicts=total_conflicts,
        )
    final_errors = validate_schedule_against_instance(
        inst,
        selected_schedule,
        strict_rooms=True,
        require_all_activities=True,
    )
    if final_errors:
        telemetry[selected_index]["selected"] = False
        telemetry[selected_index]["return_validation_errors"] = [
            str(value) for value in final_errors[:8]
        ]
        return _empty_result(
            started=started,
            status="invalid_candidate",
            deadline_exhausted=False,
            telemetry=telemetry,
            assigned_activities=best_partial,
            nodes=total_nodes,
            backtracks=total_backtracks,
            conflicts=total_conflicts,
        )
    if time.perf_counter() >= absolute_deadline:
        telemetry[selected_index]["selected"] = False
        return _empty_result(
            started=started,
            status="deadline_exhausted",
            deadline_exhausted=True,
            telemetry=telemetry,
            assigned_activities=best_partial,
            nodes=total_nodes,
            backtracks=total_backtracks,
            conflicts=total_conflicts,
        )
    try:
        returned_score = score_itc2007_instance_schedule(inst, selected_schedule)
    except (KeyError, TypeError, ValueError) as exc:
        telemetry[selected_index]["selected"] = False
        telemetry[selected_index]["return_validation_errors"] = [
            f"official_rescore_error:{type(exc).__name__}:{exc}"
        ]
        return _empty_result(
            started=started,
            status="invalid_candidate",
            deadline_exhausted=False,
            telemetry=telemetry,
            assigned_activities=best_partial,
            nodes=total_nodes,
            backtracks=total_backtracks,
            conflicts=total_conflicts,
        )
    if time.perf_counter() > absolute_deadline:
        telemetry[selected_index]["selected"] = False
        return _empty_result(
            started=started,
            status="deadline_exhausted",
            deadline_exhausted=True,
            telemetry=telemetry,
            assigned_activities=best_partial,
            nodes=total_nodes,
            backtracks=total_backtracks,
            conflicts=total_conflicts,
        )
    if int(returned_score.total) != selected_score:
        telemetry[selected_index]["selected"] = False
        telemetry[selected_index]["return_validation_errors"] = [
            "official_rescore_changed_selected_score"
        ]
        return _empty_result(
            started=started,
            status="invalid_candidate",
            deadline_exhausted=False,
            telemetry=telemetry,
            assigned_activities=best_partial,
            nodes=total_nodes,
            backtracks=total_backtracks,
            conflicts=total_conflicts,
        )
    telemetry[selected_index]["return_score_verified"] = True
    return ITC2007ConstructiveResult(
        schedule=selected_schedule,
        status="feasible",
        elapsed_seconds=float(time.perf_counter() - started),
        attempts=len(telemetry),
        assigned_activities=len(selected_schedule),
        nodes=total_nodes,
        backtracks=total_backtracks,
        conflicts_evaluated=total_conflicts,
        deadline_exhausted=False,
        attempt_telemetry=telemetry,
    )


# Module-local drop-in seam. Importing this module does not replace the current
# constructor used by services or projected search.
construct_itc2007_schedule = construct_itc2007_schedule_v2


__all__ = [
    "construct_itc2007_schedule",
    "construct_itc2007_schedule_v2",
]
