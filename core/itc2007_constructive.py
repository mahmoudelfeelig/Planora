from __future__ import annotations

import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]

_STRATEGIES = ("scarcity", "balanced", "compact")


@dataclass
class ITC2007ConstructiveResult:
    """Fail-closed result for the ITC-2007 constructive timetable builder."""

    schedule: Schedule | None
    status: str
    elapsed_seconds: float
    attempts: int
    assigned_activities: int
    nodes: int
    backtracks: int
    conflicts_evaluated: int
    deadline_exhausted: bool
    attempt_telemetry: list[dict[str, Any]] = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return self.schedule is not None and self.status == "feasible"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "feasible": bool(self.feasible),
            "elapsed_seconds": float(self.elapsed_seconds),
            "attempts": int(self.attempts),
            "assigned_activities": int(self.assigned_activities),
            "nodes": int(self.nodes),
            "backtracks": int(self.backtracks),
            "conflicts_evaluated": int(self.conflicts_evaluated),
            "deadline_exhausted": bool(self.deadline_exhausted),
            "attempt_telemetry": list(self.attempt_telemetry),
        }


def _eligibility(inst: Instance) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    sla = getattr(inst, "sla_targets", {}) or {}
    if not str(sla.get("benchmark_family", "")).startswith("ITC-2007"):
        reasons.append("not_imported_itc2007")
    if not isinstance(sla.get("itc2007"), dict):
        reasons.append("missing_itc2007_metadata")
    if len(inst.weeks) != 1:
        reasons.append("requires_single_week")
    if any(int(activity.duration) != 1 for activity in inst.activities.values()):
        reasons.append("requires_unit_duration")
    if not inst.activities:
        reasons.append("requires_activities")
    if not inst.rooms:
        reasons.append("requires_rooms")
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
    return not reasons, tuple(reasons)


class _DeadlineReached(RuntimeError):
    pass


class _ConstructiveAttempt:
    def __init__(
        self,
        inst: Instance,
        *,
        deadline: float,
        seed: int,
        strategy: str,
        beam_width: int,
        bundle_limit: int,
        node_limit: int,
    ) -> None:
        self.inst = inst
        self.deadline = float(deadline)
        self.rng = random.Random(int(seed))
        self.strategy = str(strategy)
        self.beam_width = max(4, int(beam_width))
        self.bundle_limit = max(2, int(bundle_limit))
        self.node_limit = max(1, int(node_limit))
        self.conflicts_evaluated = 0
        self.slots_per_day = int(inst.slots_per_day)
        self.period_count = len(inst.days) * self.slots_per_day
        self.day_index = {str(day): index for index, day in enumerate(inst.days)}
        self.course_code = {
            int(course_id): str(course.code)
            for course_id, course in inst.courses.items()
        }
        self.course_id = {
            str(course.code): int(course_id)
            for course_id, course in inst.courses.items()
        }
        self.activities_by_course: dict[str, tuple[int, ...]] = {}
        grouped: dict[str, list[int]] = defaultdict(list)
        for activity_id, activity in inst.activities.items():
            grouped[self.course_code[int(activity.course_id)]].append(int(activity_id))
        self.activities_by_course = {
            code: tuple(sorted(activity_ids))
            for code, activity_ids in grouped.items()
        }
        self.codes = tuple(sorted(self.activities_by_course))

        metadata = dict(inst.sla_targets["itc2007"])
        self.students = {
            str(key): int(value)
            for key, value in dict(metadata["course_students"]).items()
        }
        self.minimum_days = {
            str(key): int(value)
            for key, value in dict(metadata["minimum_working_days"]).items()
        }
        self.domains: dict[int, tuple[int, ...]] = {}
        for activity_id in sorted(inst.activities):
            forbidden = {
                self.day_index[str(day)] * self.slots_per_day + int(slot)
                for day, slot in (inst.activity_unavailability or {}).get(
                    int(activity_id), set()
                )
            }
            self.domains[int(activity_id)] = tuple(
                period
                for period in range(self.period_count)
                if period not in forbidden
            )
        self.course_period_union = {
            code: frozenset(
                period
                for activity_id in activity_ids
                for period in self.domains[activity_id]
            )
            for code, activity_ids in self.activities_by_course.items()
        }

        self.conflicts: dict[str, set[str]] = {code: {code} for code in self.codes}
        groups = {
            code: set(
                int(group_id)
                for activity_id in self.activities_by_course[code]
                for group_id in inst.activities[activity_id].group_ids
            )
            for code in self.codes
        }
        teacher = {
            code: int(
                inst.courses[self.course_id[code]].prof_id  # type: ignore[arg-type]
            )
            for code in self.codes
        }
        for index, left in enumerate(self.codes):
            for right in self.codes[index + 1 :]:
                self._check_deadline()
                self.conflicts_evaluated += 1
                if teacher[left] == teacher[right] or groups[left] & groups[right]:
                    self.conflicts[left].add(right)
                    self.conflicts[right].add(left)

        self.available_rooms: dict[int, tuple[int, ...]] = {}
        for period in range(self.period_count):
            day = str(inst.days[period // self.slots_per_day])
            slot = int(period % self.slots_per_day)
            self.available_rooms[period] = tuple(
                sorted(
                    int(room_id)
                    for room_id, room in inst.rooms.items()
                    if str(room.room_type) == "LECTURE"
                    and (
                        room.availability is None
                        or (day, slot) in room.availability
                    )
                )
            )

        self.assigned: dict[str, tuple[tuple[int, int], ...]] = {}
        self.period_courses = {
            period: set() for period in range(self.period_count)
        }
        self.period_load = [0] * self.period_count
        self.nodes = 0
        self.backtracks = 0
        self.best_assigned_activities = 0
        self.max_depth = 0
        self.dead_ends = 0

    def _check_deadline(self) -> None:
        if time.perf_counter() >= self.deadline:
            raise _DeadlineReached

    def _period_is_open(self, code: str, period: int) -> bool:
        if self.period_load[int(period)] >= len(self.available_rooms[int(period)]):
            return False
        occupants = self.period_courses[int(period)]
        return not any(other in self.conflicts[code] for other in occupants)

    def _match_course(
        self,
        code: str,
        periods: Sequence[int],
    ) -> tuple[tuple[int, int], ...] | None:
        selected = frozenset(int(period) for period in periods)
        if len(selected) != len(self.activities_by_course[code]):
            return None
        match_by_period: dict[int, int] = {}

        def augment(activity_id: int, seen: set[int]) -> bool:
            for period in self.domains[int(activity_id)]:
                if period not in selected or period in seen:
                    continue
                seen.add(int(period))
                previous = match_by_period.get(int(period))
                if previous is None or augment(int(previous), seen):
                    match_by_period[int(period)] = int(activity_id)
                    return True
            return False

        ordered = sorted(
            self.activities_by_course[code],
            key=lambda activity_id: (len(self.domains[activity_id]), activity_id),
        )
        for activity_id in ordered:
            if not augment(int(activity_id), set()):
                return None
        return tuple(
            sorted(
                (int(activity_id), int(period))
                for period, activity_id in match_by_period.items()
            )
        )

    def _legal_periods(self, code: str) -> tuple[int, ...]:
        return tuple(
            period
            for period in sorted(self.course_period_union[code])
            if self._period_is_open(code, int(period))
        )

    def _course_key(self, code: str) -> tuple[float, ...]:
        legal = self._legal_periods(code)
        lecture_count = len(self.activities_by_course[code])
        slack = len(legal) - lecture_count
        assigned_neighbors = sum(
            int(neighbor in self.assigned) for neighbor in self.conflicts[code]
        )
        degree_pressure = sum(
            len(self.activities_by_course[neighbor])
            for neighbor in self.conflicts[code]
            if neighbor != code
        )
        jitter = self.rng.random()
        if self.strategy == "scarcity":
            return (
                float(slack),
                float(-assigned_neighbors),
                float(-degree_pressure),
                float(-lecture_count),
                jitter,
            )
        if self.strategy == "compact":
            return (
                float(slack),
                float(-lecture_count),
                float(-assigned_neighbors),
                float(-degree_pressure),
                jitter,
            )
        return (
            float(slack),
            float(-degree_pressure),
            float(-assigned_neighbors),
            float(-lecture_count),
            jitter,
        )

    def _placement_cost(
        self,
        code: str,
        period: int,
        selected: tuple[int, ...],
        unassigned: set[str],
    ) -> tuple[float, int]:
        day = int(period // self.slots_per_day)
        slot = int(period % self.slots_per_day)
        selected_days = {value // self.slots_per_day for value in selected}
        day_repeat = int(day in selected_days)
        load_ratio = self.period_load[period] / max(
            1, len(self.available_rooms[period])
        )
        future_pressure = 0.0
        adjacency = 0
        for neighbor in sorted(self.conflicts[code]):
            if neighbor in unassigned:
                if period in self.course_period_union[neighbor]:
                    future_pressure += 1.0 / max(
                        1, len(self.course_period_union[neighbor])
                    )
            elif neighbor in self.assigned:
                neighbor_periods = {
                    value for _activity_id, value in self.assigned[neighbor]
                }
                adjacency += int(period - 1 in neighbor_periods and slot > 0)
                adjacency += int(
                    period + 1 in neighbor_periods
                    and slot + 1 < self.slots_per_day
                )
        minimum_days = min(
            len(self.activities_by_course[code]),
            int(self.minimum_days.get(code, 1)),
        )
        spread_need = int(len(selected_days) < minimum_days)
        capacity_tie = sum(
            max(
                0,
                self.students[code] - int(self.inst.rooms[room_id].capacity),
            )
            for room_id in self.available_rooms[period]
        )
        if self.strategy == "scarcity":
            value = (
                12.0 * future_pressure
                + 7.0 * load_ratio
                + 5.0 * day_repeat * spread_need
                - 0.8 * adjacency
            )
        elif self.strategy == "compact":
            value = (
                5.0 * future_pressure
                + 5.0 * load_ratio
                + 8.0 * day_repeat * spread_need
                - 3.0 * adjacency
            )
        else:
            value = (
                8.0 * future_pressure
                + 10.0 * load_ratio
                + 7.0 * day_repeat * spread_need
                - 1.5 * adjacency
            )
        # Capacity is soft in ITC-2007, so it only breaks otherwise similar
        # placements and can never block a feasible construction.
        value += 0.0001 * float(capacity_tie)
        return float(value), int(period)

    def _bundles(self, code: str, unassigned: set[str]) -> list[tuple[tuple[int, int], ...]]:
        lecture_count = len(self.activities_by_course[code])
        legal = self._legal_periods(code)
        if len(legal) < lecture_count:
            return []
        beam: list[tuple[float, tuple[int, ...]]] = [(0.0, ())]
        for _index in range(lecture_count):
            self._check_deadline()
            expanded: list[tuple[float, tuple[int, ...]]] = []
            for current_cost, selected in beam:
                for period in legal:
                    if period in selected:
                        continue
                    marginal, period_tie = self._placement_cost(
                        code,
                        int(period),
                        selected,
                        unassigned,
                    )
                    diversified = self.rng.random() * 0.005
                    expanded.append(
                        (
                            float(current_cost + marginal + diversified),
                            tuple(sorted((*selected, int(period_tie)))),
                        )
                    )
            best_by_bundle: dict[tuple[int, ...], float] = {}
            for cost, selected in expanded:
                prior = best_by_bundle.get(selected)
                if prior is None or cost < prior:
                    best_by_bundle[selected] = float(cost)
            beam = sorted(
                (cost, selected) for selected, cost in best_by_bundle.items()
            )[: self.beam_width]
            if not beam:
                return []
        output: list[tuple[tuple[int, int], ...]] = []
        for _cost, periods in beam:
            matched = self._match_course(code, periods)
            if matched is not None:
                output.append(matched)
                if len(output) >= self.bundle_limit:
                    break
        return output

    def _apply(self, code: str, bundle: tuple[tuple[int, int], ...]) -> None:
        self.assigned[code] = bundle
        for _activity_id, period in bundle:
            self.period_courses[int(period)].add(code)
            self.period_load[int(period)] += 1

    def _undo(self, code: str) -> None:
        bundle = self.assigned.pop(code)
        for _activity_id, period in bundle:
            self.period_courses[int(period)].remove(code)
            self.period_load[int(period)] -= 1

    def _search(self, unassigned: set[str], depth: int) -> bool:
        self._check_deadline()
        if not unassigned:
            return True
        if self.nodes >= self.node_limit:
            return False
        self.nodes += 1
        self.max_depth = max(self.max_depth, int(depth))
        assigned_count = sum(
            len(self.activities_by_course[code]) for code in self.assigned
        )
        self.best_assigned_activities = max(
            self.best_assigned_activities, int(assigned_count)
        )
        code = min(sorted(unassigned), key=self._course_key)
        bundles = self._bundles(code, unassigned)
        if not bundles:
            self.dead_ends += 1
            return False
        unassigned.remove(code)
        for bundle in bundles:
            self._check_deadline()
            self._apply(code, bundle)
            if self._search(unassigned, depth + 1):
                return True
            self._undo(code)
            self.backtracks += 1
            if self.nodes >= self.node_limit:
                break
        unassigned.add(code)
        return False

    def solve(self) -> tuple[dict[int, int] | None, bool]:
        try:
            feasible = self._search(set(self.codes), 0)
        except _DeadlineReached:
            return None, True
        if not feasible:
            return None, time.perf_counter() >= self.deadline
        assignment = {
            int(activity_id): int(period)
            for bundle in self.assigned.values()
            for activity_id, period in bundle
        }
        return assignment, False

    def materialize(self, assignment: Mapping[int, int]) -> Schedule | None:
        by_period: dict[int, list[int]] = defaultdict(list)
        for activity_id, period in assignment.items():
            by_period[int(period)].append(int(activity_id))
        output: Schedule = {}
        enforce_capacity = bool(
            (getattr(self.inst, "hard_constraints", {}) or {}).get(
                "enforce_room_capacity", False
            )
        )
        for period, activity_ids in sorted(by_period.items()):
            self._check_deadline()
            room_ids = list(self.available_rooms[int(period)])
            ordered_activities = sorted(
                activity_ids,
                key=lambda activity_id: (
                    -self.students[
                        self.course_code[
                            int(self.inst.activities[activity_id].course_id)
                        ]
                    ],
                    int(activity_id),
                ),
            )
            room_ids.sort(
                key=lambda room_id: (
                    -int(self.inst.rooms[int(room_id)].capacity),
                    int(room_id),
                )
            )
            if len(room_ids) < len(ordered_activities):
                return None
            for activity_id, room_id in zip(ordered_activities, room_ids):
                activity = self.inst.activities[int(activity_id)]
                code = self.course_code[int(activity.course_id)]
                if enforce_capacity and int(self.inst.rooms[room_id].capacity) < int(
                    self.students[code]
                ):
                    return None
                output[int(activity_id)] = {
                    "week": int(activity.week),
                    "day": str(
                        self.inst.days[int(period) // self.slots_per_day]
                    ),
                    "slot": int(period) % self.slots_per_day,
                    "duration": int(activity.duration),
                    "room_id": int(room_id),
                    "staff_id": int(activity.prof_id),
                    "course_id": int(activity.course_id),
                    "group_ids": [int(value) for value in activity.group_ids],
                    "kind": str(activity.kind),
                }
        return output


def construct_itc2007_schedule(
    inst: Instance,
    *,
    deadline: float,
    seed: int = 0,
    max_starts: int = 1,
    strategies: Sequence[str] | None = None,
    beam_width: int = 8,
    bundle_limit: int = 4,
    node_limit: int = 20_000,
    validator: Validator | None = None,
) -> ITC2007ConstructiveResult:
    """Build a first feasible ITC-2007 schedule under one shared deadline.

    The constructor works on course multi-coloring rather than the full
    activity-room CP model. Dynamic scarcity ordering, conflict-aware period
    bundles, bounded backtracking, and a final resource matching step keep the
    hot path small. Nothing partial is returned: validation failure, an
    unsupported instance, or deadline exhaustion all fail closed.
    """

    started = time.perf_counter()
    eligible, reasons = _eligibility(inst)
    if not eligible:
        return ITC2007ConstructiveResult(
            schedule=None,
            status="ineligible:" + ",".join(reasons),
            elapsed_seconds=float(time.perf_counter() - started),
            attempts=0,
            assigned_activities=0,
            nodes=0,
            backtracks=0,
            conflicts_evaluated=0,
            deadline_exhausted=False,
        )
    if time.perf_counter() >= float(deadline):
        return ITC2007ConstructiveResult(
            schedule=None,
            status="deadline_exhausted",
            elapsed_seconds=float(time.perf_counter() - started),
            attempts=0,
            assigned_activities=0,
            nodes=0,
            backtracks=0,
            conflicts_evaluated=0,
            deadline_exhausted=True,
        )

    requested = tuple(str(value) for value in (strategies or _STRATEGIES))
    unknown = sorted(set(requested) - set(_STRATEGIES))
    if unknown:
        return ITC2007ConstructiveResult(
            schedule=None,
            status="invalid_strategy:" + ",".join(unknown),
            elapsed_seconds=float(time.perf_counter() - started),
            attempts=0,
            assigned_activities=0,
            nodes=0,
            backtracks=0,
            conflicts_evaluated=0,
            deadline_exhausted=False,
        )
    strategy_order = requested[: max(1, int(max_starts))]
    telemetry: list[dict[str, Any]] = []
    total_nodes = 0
    total_backtracks = 0
    total_conflicts = 0
    best_partial = 0
    exhausted = False
    validation_fn = validator or (
        lambda candidate_inst, candidate: validate_schedule_against_instance(
            candidate_inst,
            dict(candidate),
            strict_rooms=True,
            require_all_activities=True,
        )
    )

    for attempt_index, strategy in enumerate(strategy_order):
        now = time.perf_counter()
        if now >= float(deadline):
            exhausted = True
            break
        attempts_left = len(strategy_order) - attempt_index
        attempt_deadline = (
            float(deadline)
            if attempts_left == 1
            else min(
                float(deadline),
                now + max(0.002, (float(deadline) - now) / attempts_left),
            )
        )
        attempt_started = time.perf_counter()
        attempt: _ConstructiveAttempt | None = None
        try:
            attempt = _ConstructiveAttempt(
                inst,
                deadline=float(attempt_deadline),
                seed=int(seed) + attempt_index * 104_729,
                strategy=str(strategy),
                beam_width=int(beam_width),
                bundle_limit=int(bundle_limit),
                node_limit=int(node_limit),
            )
            assignment, attempt_exhausted = attempt.solve()
            schedule = (
                None if assignment is None else attempt.materialize(assignment)
            )
        except _DeadlineReached:
            attempt_exhausted = True
            schedule = None
        nodes = int(getattr(attempt, "nodes", 0))
        backtracks = int(getattr(attempt, "backtracks", 0))
        conflicts = int(getattr(attempt, "conflicts_evaluated", 0))
        partial = int(getattr(attempt, "best_assigned_activities", 0))
        total_nodes += nodes
        total_backtracks += backtracks
        total_conflicts += conflicts
        best_partial = max(best_partial, partial)
        exhausted = bool(exhausted or attempt_exhausted)
        row = {
            "attempt_index": int(attempt_index),
            "strategy": str(strategy),
            "seed": int(seed) + attempt_index * 104_729,
            "status": "deadline_exhausted" if attempt_exhausted else "infeasible",
            "elapsed_seconds": float(time.perf_counter() - attempt_started),
            "nodes": nodes,
            "backtracks": backtracks,
            "conflicts_evaluated": conflicts,
            "assigned_activities": partial,
            "max_depth": int(getattr(attempt, "max_depth", 0)),
            "dead_ends": int(getattr(attempt, "dead_ends", 0)),
        }
        if schedule is not None and time.perf_counter() < float(deadline):
            errors = list(validation_fn(inst, schedule))
            if not errors and time.perf_counter() <= float(deadline):
                row["status"] = "feasible"
                row["assigned_activities"] = len(schedule)
                row["elapsed_seconds"] = float(
                    time.perf_counter() - attempt_started
                )
                telemetry.append(row)
                return ITC2007ConstructiveResult(
                    schedule=schedule,
                    status="feasible",
                    elapsed_seconds=float(time.perf_counter() - started),
                    attempts=len(telemetry),
                    assigned_activities=len(schedule),
                    nodes=int(total_nodes),
                    backtracks=int(total_backtracks),
                    conflicts_evaluated=int(total_conflicts),
                    deadline_exhausted=False,
                    attempt_telemetry=telemetry,
                )
            row["status"] = (
                "deadline_exhausted"
                if time.perf_counter() > float(deadline)
                else "invalid_candidate"
            )
            row["validation_errors"] = [str(error) for error in errors[:8]]
            exhausted = bool(exhausted or time.perf_counter() > float(deadline))
        elif time.perf_counter() >= float(deadline):
            row["status"] = "deadline_exhausted"
            exhausted = True
        row["elapsed_seconds"] = float(time.perf_counter() - attempt_started)
        telemetry.append(row)

    return ITC2007ConstructiveResult(
        schedule=None,
        status="deadline_exhausted" if exhausted else "infeasible",
        elapsed_seconds=float(time.perf_counter() - started),
        attempts=len(telemetry),
        assigned_activities=int(best_partial),
        nodes=int(total_nodes),
        backtracks=int(total_backtracks),
        conflicts_evaluated=int(total_conflicts),
        deadline_exhausted=bool(exhausted),
        attempt_telemetry=telemetry,
    )


__all__ = [
    "ITC2007ConstructiveResult",
    "construct_itc2007_schedule",
]
