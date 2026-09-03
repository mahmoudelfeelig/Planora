from __future__ import annotations

import random
import time
import math
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from benchmarks.itc2007 import ITC2007Score, score_itc2007_instance_schedule
from ortools.sat.python import cp_model
from core.fixed_time_room_oracle import (
    RoomOracleDeadline,
    solve_period_additive_projection,
)
from core.itc2007_constructive_v2 import construct_itc2007_schedule
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]


@dataclass
class ProjectedTimeSearchResult:
    schedule: Schedule
    status: str
    initial_score: int
    final_score: int
    initial_projected_score: int
    final_projected_score: int
    projected_lower_bound: int
    elapsed_seconds: float
    iterations: int
    candidates_evaluated: int
    accepted_moves: int
    accepted_by_family: dict[str, int] = field(default_factory=dict)
    lift_status: str = "not_started"
    oracle_status: str = "not_started"
    room_cp_status: str = "not_started"
    trace: list[dict[str, Any]] = field(default_factory=list)
    starts_requested: int = 1
    starts_generated: int = 1
    starts_completed: int = 0
    selected_start_index: int = 0
    start_telemetry: list[dict[str, Any]] = field(default_factory=list)
    room_screening: dict[str, Any] = field(default_factory=dict)
    deadline_exhausted: bool = False
    deadline_overrun_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "initial_score": int(self.initial_score),
            "final_score": int(self.final_score),
            "improvement": int(self.initial_score - self.final_score),
            "initial_projected_score": int(self.initial_projected_score),
            "final_projected_score": int(self.final_projected_score),
            "projected_lower_bound": int(self.projected_lower_bound),
            "projected_gap": int(
                self.final_projected_score - self.projected_lower_bound
            ),
            "projected_improvement": int(
                self.initial_projected_score - self.final_projected_score
            ),
            "elapsed_seconds": float(self.elapsed_seconds),
            "iterations": int(self.iterations),
            "candidates_evaluated": int(self.candidates_evaluated),
            "accepted_moves": int(self.accepted_moves),
            "accepted_by_family": dict(self.accepted_by_family),
            "lift_status": str(self.lift_status),
            "oracle_status": str(self.oracle_status),
            "room_cp_status": str(self.room_cp_status),
            "trace": list(self.trace),
            "starts_requested": int(self.starts_requested),
            "starts_generated": int(self.starts_generated),
            "starts_completed": int(self.starts_completed),
            "selected_start_index": int(self.selected_start_index),
            "start_telemetry": list(self.start_telemetry),
            "room_screening": dict(self.room_screening),
            "deadline_exhausted": bool(self.deadline_exhausted),
            "deadline_overrun_seconds": float(self.deadline_overrun_seconds),
        }


@dataclass
class ITC2007FixedTimeRoomCPResult:
    """Fail-closed result for the exact fixed-time ITC-2007 room tail."""

    schedule: Schedule
    status: str
    improved: bool
    initial_score: ITC2007Score | None
    final_score: ITC2007Score | None
    candidate_score: ITC2007Score | None
    solver_status: str = "not_started"
    eligibility_reasons: tuple[str, ...] = ()
    validation_attempted: bool = False
    validation_errors: tuple[str, ...] = ()
    fixed_starts_preserved: bool | None = None
    elapsed_seconds: float = 0.0
    deadline_exhausted: bool = False
    deadline_overrun_seconds: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "improved": bool(self.improved),
            "initial_score": (
                None if self.initial_score is None else self.initial_score.to_dict()
            ),
            "final_score": (
                None if self.final_score is None else self.final_score.to_dict()
            ),
            "candidate_score": (
                None
                if self.candidate_score is None
                else self.candidate_score.to_dict()
            ),
            "improvement": (
                0
                if self.initial_score is None or self.final_score is None
                else max(0, int(self.initial_score.total - self.final_score.total))
            ),
            "solver_status": str(self.solver_status),
            "eligibility_reasons": list(self.eligibility_reasons),
            "validation_attempted": bool(self.validation_attempted),
            "validation_errors": list(self.validation_errors),
            "fixed_starts_preserved": self.fixed_starts_preserved,
            "elapsed_seconds": float(self.elapsed_seconds),
            "deadline_exhausted": bool(self.deadline_exhausted),
            "deadline_overrun_seconds": float(self.deadline_overrun_seconds),
            "error": self.error,
        }


def _copy_schedule(schedule: Mapping[int, Mapping[str, Any]]) -> Schedule:
    return {int(activity_id): dict(row) for activity_id, row in schedule.items()}


def _default_validator(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
) -> Sequence[str]:
    return validate_schedule_against_instance(
        inst,
        dict(schedule),
        strict_rooms=True,
        require_all_activities=True,
    )


def projected_time_search_eligibility(inst: Instance, schedule: Mapping[int, Mapping[str, Any]]) -> tuple[bool, tuple[str, ...]]:
    """Return the deliberately narrow, fail-closed v1 eligibility predicate."""

    reasons: list[str] = []
    sla = getattr(inst, "sla_targets", {}) or {}
    metadata = sla.get("itc2007")
    if not str(sla.get("benchmark_family", "")).startswith("ITC-2007"):
        reasons.append("not_imported_itc2007")
    if not isinstance(metadata, dict):
        reasons.append("missing_itc2007_metadata")
    if set(int(value) for value in schedule) != set(int(value) for value in inst.activities):
        reasons.append("incomplete_schedule")
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
    if getattr(inst, "locked_activities", None) or getattr(inst, "locks", None):
        reasons.append("locks_not_supported")
    return not reasons, tuple(reasons)


class _ITCProjectedState:
    def __init__(self, inst: Instance, schedule: Schedule, *, seed: int) -> None:
        self.inst = inst
        self.schedule = _copy_schedule(schedule)
        self.rng = random.Random(int(seed))
        self.slots_per_day = int(inst.slots_per_day)
        self.day_count = len(inst.days)
        self.period_count = self.day_count * self.slots_per_day
        self.room_count = len(inst.rooms)
        # The course-coloring proxy is a useful tie breaker on the small
        # instances where there is time to exploit equal-score plateaus.  On
        # larger instances it can displace genuine compactness/minimum-day
        # improvements inside a short ten-second budget, so those retain the
        # exact additive projection only.
        self.use_stability_proxy = len(inst.activities) <= 200
        self.day_index = {str(day): index for index, day in enumerate(inst.days)}

        metadata = dict(inst.sla_targets["itc2007"])
        weights = {
            str(key): int(value)
            for key, value in dict(metadata.get("objective_weights") or {}).items()
        }
        self.days_weight = int(weights.get("minimum_working_days", 5))
        self.compactness_weight = int(weights.get("curriculum_compactness", 2))
        self.minimum_days = {
            str(key): int(value)
            for key, value in dict(metadata["minimum_working_days"]).items()
        }
        self.students = {
            str(key): int(value)
            for key, value in dict(metadata["course_students"]).items()
        }
        self.room_capacities = sorted(
            (int(room.capacity) for room in inst.rooms.values()), reverse=True
        )
        self.room_capacity_by_id = {
            int(room_id): int(room.capacity)
            for room_id, room in inst.rooms.items()
        }
        largest_room_capacity = max(self.room_capacities)

        self.course_code = {
            int(activity_id): str(inst.courses[int(activity.course_id)].code)
            for activity_id, activity in inst.activities.items()
        }
        self.events_by_course: dict[str, list[int]] = defaultdict(list)
        for activity_id, code in self.course_code.items():
            self.events_by_course[str(code)].append(int(activity_id))
        self.projected_lower_bound = int(
            sum(
                max(0, int(self.students[code]) - int(largest_room_capacity))
                for code in self.course_code.values()
            )
        )

        self.curricula = {
            str(name): tuple(str(code) for code in members)
            for name, members in dict(metadata["curricula"]).items()
        }
        self.curricula_by_course: dict[str, set[str]] = defaultdict(set)
        self.events_by_curriculum: dict[str, tuple[int, ...]] = {}
        for name, codes in self.curricula.items():
            ids: list[int] = []
            for code in codes:
                self.curricula_by_course[str(code)].add(str(name))
                ids.extend(self.events_by_course[str(code)])
            self.events_by_curriculum[str(name)] = tuple(ids)

        teacher_by_course = {
            str(course.code): int(course.prof_id) for course in inst.courses.values()
        }
        self.conflicts: dict[str, set[str]] = {
            code: {code} for code in self.events_by_course
        }
        codes = sorted(self.events_by_course)
        for index, left in enumerate(codes):
            for right in codes[index + 1 :]:
                if (
                    teacher_by_course[left] == teacher_by_course[right]
                    or self.curricula_by_course[left] & self.curricula_by_course[right]
                ):
                    self.conflicts[left].add(right)
                    self.conflicts[right].add(left)

        self.forbidden: dict[int, set[int]] = defaultdict(set)
        for raw_activity_id, pairs in (inst.activity_unavailability or {}).items():
            for day, slot in pairs:
                self.forbidden[int(raw_activity_id)].add(
                    self.day_index[str(day)] * self.slots_per_day + int(slot)
                )

        self.assignment = {
            int(activity_id): self._period(row)
            for activity_id, row in self.schedule.items()
        }
        self.period_events: dict[int, set[int]] = {
            period: set() for period in range(self.period_count)
        }
        for activity_id, period in self.assignment.items():
            self.period_events[int(period)].add(int(activity_id))
        # A static course-room coloring supplies a cheap cross-period tie
        # breaker that the additive capacity projection cannot see.  The
        # resulting collision count is not presented as an official bound; it
        # only directs equal-official-score moves toward time layouts in which
        # more courses can retain one room throughout the week.
        self.primary_room = (
            self._derive_primary_rooms() if self.use_stability_proxy else {}
        )
        self.stability_proxy_by_period = (
            {
                period: self._stability_proxy_for(period, None)
                for period in range(self.period_count)
            }
            if self.use_stability_proxy
            else {period: 0 for period in range(self.period_count)}
        )
        self.stability_proxy = int(sum(self.stability_proxy_by_period.values()))

        self.course_penalty = {
            code: self._course_penalty_for(code, None)
            for code in self.events_by_course
        }
        self.curriculum_day_penalty = {
            (name, day): self._curriculum_day_penalty_for(name, day, None)
            for name in self.curricula
            for day in range(self.day_count)
        }
        self.capacity_penalty = {
            period: self._capacity_penalty_for(period, None)
            for period in range(self.period_count)
        }
        self.score = int(
            sum(self.course_penalty.values())
            + sum(self.curriculum_day_penalty.values())
            + sum(self.capacity_penalty.values())
        )

    @property
    def time_penalty(self) -> int:
        return int(
            sum(self.course_penalty.values())
            + sum(self.curriculum_day_penalty.values())
        )

    def _period(self, row: Mapping[str, Any]) -> int:
        return self.day_index[str(row["day"])] * self.slots_per_day + int(row["slot"])

    def _period_after(self, activity_id: int, move: Mapping[int, int] | None) -> int:
        if move is not None and int(activity_id) in move:
            return int(move[int(activity_id)])
        return int(self.assignment[int(activity_id)])

    def _course_penalty_for(self, code: str, move: Mapping[int, int] | None) -> int:
        days = {
            self._period_after(activity_id, move) // self.slots_per_day
            for activity_id in self.events_by_course[str(code)]
        }
        return self.days_weight * max(0, int(self.minimum_days[str(code)]) - len(days))

    def _curriculum_day_penalty_for(
        self,
        name: str,
        day: int,
        move: Mapping[int, int] | None,
    ) -> int:
        periods: list[int] = []
        for activity_id in self.events_by_curriculum[str(name)]:
            period = self._period_after(activity_id, move)
            if period // self.slots_per_day == int(day):
                periods.append(int(period))
        occupied = set(periods)
        isolated = 0
        for period in periods:
            slot = int(period) % self.slots_per_day
            if (slot == 0 or period - 1 not in occupied) and (
                slot + 1 == self.slots_per_day or period + 1 not in occupied
            ):
                isolated += 1
        return int(self.compactness_weight * isolated)

    def _capacity_penalty_for(
        self,
        period: int,
        move: Mapping[int, int] | None,
    ) -> int:
        ids = set(self.period_events[int(period)])
        if move:
            for activity_id, target in move.items():
                ids.discard(int(activity_id))
                if int(target) == int(period):
                    ids.add(int(activity_id))
        demands = sorted(
            (self.students[self.course_code[activity_id]] for activity_id in ids),
            reverse=True,
        )
        return int(
            sum(
                max(0, int(demand) - int(capacity))
                for demand, capacity in zip(demands, self.room_capacities)
            )
        )

    def _derive_primary_rooms(self) -> dict[str, int]:
        room_ids = tuple(sorted(self.room_capacity_by_id))
        course_neighbors: dict[str, set[str]] = {
            str(code): set() for code in self.events_by_course
        }
        for activity_ids in self.period_events.values():
            period_codes = sorted(
                {self.course_code[int(activity_id)] for activity_id in activity_ids}
            )
            for index, left in enumerate(period_codes):
                for right in period_codes[index + 1 :]:
                    course_neighbors[left].add(right)
                    course_neighbors[right].add(left)

        selected: dict[str, int] = {}
        uncolored = set(course_neighbors)
        while uncolored:
            code = min(
                uncolored,
                key=lambda value: (
                    -len(
                        {
                            selected[neighbor]
                            for neighbor in course_neighbors[value]
                            if neighbor in selected
                        }
                    ),
                    -len(course_neighbors[value]),
                    -int(self.students[value]),
                    str(value),
                ),
            )
            selected[code] = min(
                room_ids,
                key=lambda room_id: (
                    sum(
                        int(selected.get(neighbor) == int(room_id))
                        for neighbor in course_neighbors[code]
                    ),
                    max(
                        0,
                        int(self.students[code])
                        - int(self.room_capacity_by_id[int(room_id)]),
                    )
                    * len(self.events_by_course[code]),
                    int(room_id),
                ),
            )
            uncolored.remove(code)
        return selected

    def _stability_proxy_for(
        self,
        period: int,
        move: Mapping[int, int] | None,
    ) -> int:
        ids = set(self.period_events[int(period)])
        if move:
            for activity_id, target in move.items():
                ids.discard(int(activity_id))
                if int(target) == int(period):
                    ids.add(int(activity_id))
        counts = Counter(
            int(self.primary_room[self.course_code[int(activity_id)]])
            for activity_id in ids
        )
        return int(sum(max(0, int(count) - 1) for count in counts.values()))

    def stability_proxy_delta(self, move: Mapping[int, int]) -> int:
        if not self.use_stability_proxy:
            return 0
        _courses, _curriculum_days, periods = self._affected(move)
        before = sum(self.stability_proxy_by_period[period] for period in periods)
        after = sum(self._stability_proxy_for(period, move) for period in periods)
        return int(after - before)

    def _affected(
        self, move: Mapping[int, int]
    ) -> tuple[set[str], set[tuple[str, int]], set[int]]:
        changed = [
            int(activity_id)
            for activity_id, target in move.items()
            if int(self.assignment[int(activity_id)]) != int(target)
        ]
        courses = {self.course_code[activity_id] for activity_id in changed}
        curriculum_days: set[tuple[str, int]] = set()
        periods: set[int] = set()
        for activity_id in changed:
            old_period = int(self.assignment[activity_id])
            new_period = int(move[activity_id])
            periods.update((old_period, new_period))
            for name in self.curricula_by_course[self.course_code[activity_id]]:
                curriculum_days.add((str(name), old_period // self.slots_per_day))
                curriculum_days.add((str(name), new_period // self.slots_per_day))
        return courses, curriculum_days, periods

    def delta(self, move: Mapping[int, int]) -> int:
        courses, curriculum_days, periods = self._affected(move)
        before = sum(self.course_penalty[code] for code in courses)
        before += sum(self.curriculum_day_penalty[key] for key in curriculum_days)
        before += sum(self.capacity_penalty[period] for period in periods)
        after = sum(self._course_penalty_for(code, move) for code in courses)
        after += sum(
            self._curriculum_day_penalty_for(name, day, move)
            for name, day in curriculum_days
        )
        after += sum(self._capacity_penalty_for(period, move) for period in periods)
        return int(after - before)

    def feasible(self, move: Mapping[int, int]) -> bool:
        changed = {
            int(activity_id): int(period)
            for activity_id, period in move.items()
            if int(self.assignment[int(activity_id)]) != int(period)
        }
        if not changed:
            return False
        for activity_id, period in changed.items():
            if not 0 <= int(period) < self.period_count:
                return False
            if int(period) in self.forbidden.get(int(activity_id), set()):
                return False

        affected_periods = {
            int(self.assignment[activity_id]) for activity_id in changed
        } | set(changed.values())
        for period in affected_periods:
            occupants = {
                activity_id
                for activity_id in self.period_events[int(period)]
                if activity_id not in changed
            }
            occupants.update(
                activity_id
                for activity_id, target in changed.items()
                if int(target) == int(period)
            )
            if len(occupants) > self.room_count:
                return False
            ids = sorted(occupants)
            for index, left_id in enumerate(ids):
                left_code = self.course_code[left_id]
                for right_id in ids[index + 1 :]:
                    if self.course_code[right_id] in self.conflicts[left_code]:
                        return False
        return True

    def _kempe_component(
        self, seed_activity_id: int, source: int, target: int
    ) -> set[int]:
        selected = {int(seed_activity_id)}
        queue: deque[int] = deque([int(seed_activity_id)])
        while queue:
            activity_id = queue.popleft()
            period = int(self.assignment[activity_id])
            opposite = int(target) if period == int(source) else int(source)
            code = self.course_code[activity_id]
            # ``period_events`` is a set because incremental moves need cheap
            # membership updates.  Canonicalize only at the decision boundary:
            # queue order changes which otherwise-equivalent component move is
            # generated first and used to depend on the ambient hash seed.
            for other in sorted(self.period_events[opposite]):
                if other in selected:
                    continue
                if self.course_code[other] in self.conflicts[code]:
                    selected.add(int(other))
                    queue.append(int(other))
        return selected

    def kempe_move(self, activity_id: int, target: int) -> dict[int, int] | None:
        source = int(self.assignment[int(activity_id)])
        target = int(target)
        if source == target:
            return None
        component = self._kempe_component(int(activity_id), source, target)
        move = {
            member: (
                target if int(self.assignment[member]) == source else source
            )
            for member in component
        }
        return move if self.feasible(move) else None

    def double_kempe_moves(
        self,
        activity_id: int,
        target: int,
        *,
        limit: int = 2,
    ) -> list[dict[int, int]]:
        source = int(self.assignment[int(activity_id)])
        target = int(target)
        if source == target:
            return []
        first = self._kempe_component(int(activity_id), source, target)
        remaining = sorted(
            (self.period_events[source] | self.period_events[target]) - first
        )
        self.rng.shuffle(remaining)
        output: list[dict[int, int]] = []
        covered = set(first)
        for seed in remaining:
            if seed in covered:
                continue
            second = self._kempe_component(int(seed), source, target)
            covered.update(second)
            members = first | second
            move = {
                member: (
                    target if int(self.assignment[member]) == source else source
                )
                for member in sorted(members)
            }
            if self.feasible(move):
                output.append(move)
                if len(output) >= int(limit):
                    break
        return output

    def _minimum_days_specs(self) -> list[tuple[int, int, str]]:
        specs: list[tuple[int, int, str]] = []
        for code in sorted(self.events_by_course):
            ids = self.events_by_course[code]
            if int(self.course_penalty[code]) <= 0:
                continue
            by_day: dict[int, list[int]] = defaultdict(list)
            for activity_id in ids:
                by_day[self.assignment[activity_id] // self.slots_per_day].append(
                    int(activity_id)
                )
            if len(by_day) >= int(self.minimum_days[code]):
                continue
            missing = list(sorted(set(range(self.day_count)) - set(by_day)))
            duplicate = sorted(
                activity_id
                for day in sorted(by_day)
                for members in (by_day[day],)
                if len(members) > 1
                for activity_id in members
            )
            self.rng.shuffle(missing)
            self.rng.shuffle(duplicate)
            for activity_id in duplicate[:4]:
                for day in missing[:2]:
                    slots = list(range(self.slots_per_day))
                    self.rng.shuffle(slots)
                    for slot in slots[:3]:
                        specs.append(
                            (
                                int(activity_id),
                                int(day * self.slots_per_day + slot),
                                "minimum_days",
                            )
                        )
        return specs

    def _compactness_specs(self) -> list[tuple[int, int, str]]:
        specs: list[tuple[int, int, str]] = []
        seen: set[tuple[int, int]] = set()
        names = sorted(
            {
                str(name)
                for (name, _day), penalty in self.curriculum_day_penalty.items()
                if int(penalty) > 0
            }
        )
        self.rng.shuffle(names)
        for name in names:
            ids = tuple(sorted(self.events_by_curriculum[name]))
            occupied = {self.assignment[activity_id] for activity_id in ids}
            isolated: list[int] = []
            for activity_id in ids:
                period = int(self.assignment[activity_id])
                slot = period % self.slots_per_day
                if (slot == 0 or period - 1 not in occupied) and (
                    slot + 1 == self.slots_per_day or period + 1 not in occupied
                ):
                    isolated.append(int(activity_id))
            self.rng.shuffle(isolated)
            anchors = sorted(occupied)
            self.rng.shuffle(anchors)
            for activity_id in isolated[:3]:
                for anchor in anchors[:6]:
                    for target in (anchor - 1, anchor + 1):
                        if not 0 <= target < self.period_count:
                            continue
                        if target // self.slots_per_day != anchor // self.slots_per_day:
                            continue
                        key = (int(activity_id), int(target))
                        if key in seen:
                            continue
                        seen.add(key)
                        specs.append((int(activity_id), int(target), "compactness"))
        return specs

    def _stability_proxy_specs(self) -> list[tuple[int, int, str]]:
        if not self.use_stability_proxy:
            return []
        specs: list[tuple[int, int, str]] = []
        preferred_occupancy: dict[tuple[int, int], list[int]] = defaultdict(list)
        for period in sorted(self.period_events):
            for activity_id in sorted(self.period_events[period]):
                preferred_occupancy[
                    (
                        int(period),
                        int(self.primary_room[self.course_code[int(activity_id)]]),
                    )
                ].append(int(activity_id))
        colliding: list[int] = []
        for key in sorted(preferred_occupancy):
            members = preferred_occupancy[key]
            if len(members) > 1:
                colliding.extend(sorted(members)[1:])
        self.rng.shuffle(colliding)
        periods = list(range(self.period_count))
        for activity_id in colliding[:12]:
            preferred = int(self.primary_room[self.course_code[int(activity_id)]])
            source = int(self.assignment[int(activity_id)])
            targets = [
                period
                for period in periods
                if period != source
                and not preferred_occupancy.get((int(period), preferred))
            ]
            self.rng.shuffle(targets)
            for target in targets[:8]:
                specs.append((int(activity_id), int(target), "stability_proxy"))
        return specs

    def candidate_moves(self, *, limit: int) -> list[tuple[dict[int, int], str]]:
        specs = (
            self._minimum_days_specs()
            + self._compactness_specs()
            + self._stability_proxy_specs()
        )
        activities = sorted(self.assignment)
        for _index in range(max(16, int(limit // 2))):
            specs.append(
                (
                    int(self.rng.choice(activities)),
                    int(self.rng.randrange(self.period_count)),
                    "random",
                )
            )
        self.rng.shuffle(specs)

        moves: list[tuple[dict[int, int], str]] = []
        seen: set[tuple[tuple[int, int], ...]] = set()
        for activity_id, target, family in specs:
            source = int(self.assignment[activity_id])
            if source == int(target):
                continue
            candidates: list[tuple[dict[int, int] | None, str]] = [
                ({int(activity_id): int(target)}, f"{family}:relocate"),
                (self.kempe_move(int(activity_id), int(target)), f"{family}:kempe"),
            ]
            if family != "random" or self.rng.random() < 0.15:
                candidates.extend(
                    (move, f"{family}:double_kempe")
                    for move in self.double_kempe_moves(
                        int(activity_id), int(target), limit=2
                    )
                )
            occupants = sorted(self.period_events[int(target)])
            self.rng.shuffle(occupants)
            for other in occupants[:2]:
                candidates.append(
                    (
                        {int(activity_id): int(target), int(other): int(source)},
                        f"{family}:swap",
                    )
                )
            for move, label in candidates:
                if move is None or not self.feasible(move):
                    continue
                key = tuple(sorted((int(k), int(v)) for k, v in move.items()))
                if key in seen:
                    continue
                seen.add(key)
                moves.append((move, label))
                if len(moves) >= int(limit):
                    return moves
        return moves

    def apply(self, move: Mapping[int, int]) -> None:
        courses, curriculum_days, periods = self._affected(move)
        for activity_id, target in move.items():
            source = int(self.assignment[int(activity_id)])
            if source != int(target):
                self.period_events[source].remove(int(activity_id))
        for activity_id, target in move.items():
            source = int(self.assignment[int(activity_id)])
            if source != int(target):
                self.assignment[int(activity_id)] = int(target)
                self.period_events[int(target)].add(int(activity_id))
        for code in courses:
            self.course_penalty[code] = self._course_penalty_for(code, None)
        for name, day in curriculum_days:
            self.curriculum_day_penalty[(name, day)] = (
                self._curriculum_day_penalty_for(name, day, None)
            )
        for period in periods:
            self.capacity_penalty[int(period)] = self._capacity_penalty_for(
                int(period), None
            )
            self.stability_proxy_by_period[int(period)] = (
                self._stability_proxy_for(int(period), None)
                if self.use_stability_proxy
                else 0
            )
        self.stability_proxy = int(sum(self.stability_proxy_by_period.values()))
        self.score = int(
            sum(self.course_penalty.values())
            + sum(self.curriculum_day_penalty.values())
            + sum(self.capacity_penalty.values())
        )

    def restore(self, assignment: Mapping[int, int]) -> None:
        self.assignment = {int(key): int(value) for key, value in assignment.items()}
        self.period_events = {
            period: set() for period in range(self.period_count)
        }
        for activity_id, period in self.assignment.items():
            self.period_events[int(period)].add(int(activity_id))
        self.course_penalty = {
            code: self._course_penalty_for(code, None)
            for code in self.events_by_course
        }
        self.curriculum_day_penalty = {
            (name, day): self._curriculum_day_penalty_for(name, day, None)
            for name in self.curricula
            for day in range(self.day_count)
        }
        self.capacity_penalty = {
            period: self._capacity_penalty_for(period, None)
            for period in range(self.period_count)
        }
        self.stability_proxy_by_period = (
            {
                period: self._stability_proxy_for(period, None)
                for period in range(self.period_count)
            }
            if self.use_stability_proxy
            else {period: 0 for period in range(self.period_count)}
        )
        self.stability_proxy = int(sum(self.stability_proxy_by_period.values()))
        self.score = int(
            sum(self.course_penalty.values())
            + sum(self.curriculum_day_penalty.values())
            + sum(self.capacity_penalty.values())
        )

    def materialize(self, assignment: Mapping[int, int] | None = None) -> Schedule:
        selected = self.assignment if assignment is None else assignment
        output = _copy_schedule(self.schedule)
        for activity_id, period in selected.items():
            output[int(activity_id)]["day"] = str(
                self.inst.days[int(period) // self.slots_per_day]
            )
            output[int(activity_id)]["slot"] = int(period) % self.slots_per_day
        return output


def _capacity_lift(
    inst: Instance,
    schedule: Schedule,
    *,
    deadline: float,
) -> tuple[Schedule | None, str]:
    lifted = _copy_schedule(schedule)
    metadata = dict(inst.sla_targets["itc2007"])
    students = {
        str(key): int(value)
        for key, value in dict(metadata["course_students"]).items()
    }
    rooms = tuple(sorted(int(value) for value in inst.rooms))
    by_period: dict[tuple[int, str, int], list[int]] = defaultdict(list)
    for activity_id, row in lifted.items():
        by_period[(int(row["week"]), str(row["day"]), int(row["slot"]))].append(
            int(activity_id)
        )
    try:
        for period, activity_ids in sorted(by_period.items()):
            if time.perf_counter() >= float(deadline):
                return None, "deadline_exhausted"
            edges: dict[int, list[tuple[int, int]]] = {}
            for activity_id in activity_ids:
                course = inst.courses[int(inst.activities[activity_id].course_id)]
                demand = int(students[str(course.code)])
                edges[int(activity_id)] = [
                    (
                        int(room_id),
                        max(0, demand - int(inst.rooms[int(room_id)].capacity)),
                    )
                    for room_id in rooms
                ]
            projection = solve_period_additive_projection(
                period,
                activity_ids,
                edges,
                deadline=deadline,
            )
            if not projection.feasible or projection.certificate is None:
                return None, "room_projection_infeasible"
            for activity_id, room_id in projection.certificate.assignments:
                lifted[int(activity_id)]["room_id"] = int(room_id)
    except RoomOracleDeadline:
        return None, "deadline_exhausted"
    return lifted, "capacity_optimal_lift"


def _dense_assignment(
    activity_ids: Sequence[int],
    room_ids: Sequence[int],
    costs: Mapping[tuple[int, int], int],
) -> dict[int, int]:
    """Return a deterministic rectangular Hungarian assignment."""

    activities = tuple(int(value) for value in activity_ids)
    rooms = tuple(int(value) for value in room_ids)
    rows = len(activities)
    columns = len(rooms)
    if rows > columns:
        raise ValueError("Room assignment has more activities than rooms")
    matrix = [
        [int(costs[(activity_id, room_id)]) for room_id in rooms]
        for activity_id in activities
    ]
    u = [0] * (rows + 1)
    v = [0] * (columns + 1)
    matching = [0] * (columns + 1)
    way = [0] * (columns + 1)
    infinity = 10**15
    for row in range(1, rows + 1):
        matching[0] = row
        column0 = 0
        minimum = [infinity] * (columns + 1)
        used = [False] * (columns + 1)
        while True:
            used[column0] = True
            row0 = matching[column0]
            delta = infinity
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
            for column in range(columns + 1):
                if used[column]:
                    u[matching[column]] += int(delta)
                    v[column] -= int(delta)
                else:
                    minimum[column] -= int(delta)
            column0 = int(column1)
            if matching[column0] == 0:
                break
        while True:
            column1 = int(way[column0])
            matching[column0] = matching[column1]
            column0 = int(column1)
            if column0 == 0:
                break
    return {
        int(activities[matching[column] - 1]): int(rooms[column - 1])
        for column in range(1, columns + 1)
        if matching[column]
    }


def _fast_capacity_lift(
    inst: Instance,
    schedule: Schedule,
    *,
    deadline: float,
) -> tuple[Schedule | None, str]:
    """Exact ITC per-period capacity lift with no certificate serialization."""

    output = _copy_schedule(schedule)
    metadata = dict(inst.sla_targets["itc2007"])
    students_by_code = {
        str(key): int(value)
        for key, value in dict(metadata["course_students"]).items()
    }
    room_ids = tuple(sorted(int(room_id) for room_id in inst.rooms))
    by_period: dict[tuple[int, str, int], list[int]] = defaultdict(list)
    for activity_id, row in output.items():
        by_period[(int(row["week"]), str(row["day"]), int(row["slot"]))].append(
            int(activity_id)
        )
    for activity_ids in by_period.values():
        if time.perf_counter() >= float(deadline):
            return None, "deadline_exhausted"
        selected = tuple(sorted(activity_ids))
        if len(selected) > len(room_ids):
            return None, "room_projection_infeasible"
        costs: dict[tuple[int, int], int] = {}
        for activity_id in selected:
            code = str(
                inst.courses[
                    int(inst.activities[int(activity_id)].course_id)
                ].code
            )
            demand = int(students_by_code[code])
            for room_id in room_ids:
                costs[(int(activity_id), int(room_id))] = max(
                    0, demand - int(inst.rooms[int(room_id)].capacity)
                )
        assignment = _dense_assignment(selected, room_ids, costs)
        if len(assignment) != len(selected):
            return None, "room_projection_infeasible"
        for activity_id, room_id in assignment.items():
            output[int(activity_id)]["room_id"] = int(room_id)
    return output, "capacity_optimal_dense_lift"


def _fast_coordinate_room_lift(
    inst: Instance,
    schedule: Schedule,
    *,
    deadline: float,
    max_sweeps: int = 24,
) -> tuple[Schedule, str]:
    """Exact one-period room descent without certificate serialization overhead."""

    output = _copy_schedule(schedule)
    metadata = dict(inst.sla_targets["itc2007"])
    students = {
        str(key): int(value)
        for key, value in dict(metadata["course_students"]).items()
    }
    room_ids = tuple(sorted(int(value) for value in inst.rooms))
    course_code = {
        int(activity_id): str(
            inst.courses[int(inst.activities[int(activity_id)].course_id)].code
        )
        for activity_id in output
    }
    by_period: dict[tuple[int, str, int], list[int]] = defaultdict(list)
    for activity_id, row in output.items():
        by_period[(int(row["week"]), str(row["day"]), int(row["slot"]))].append(
            int(activity_id)
        )
    periods = sorted(by_period)
    events_by_course: dict[str, list[int]] = defaultdict(list)
    period_by_activity: dict[int, tuple[int, str, int]] = {}
    for period, activity_ids in by_period.items():
        for activity_id in activity_ids:
            events_by_course[course_code[int(activity_id)]].append(int(activity_id))
            period_by_activity[int(activity_id)] = period

    def room_objective() -> int:
        capacity = sum(
            max(
                0,
                int(students[course_code[int(activity_id)]])
                - int(inst.rooms[int(row["room_id"])].capacity),
            )
            for activity_id, row in output.items()
        )
        supports: dict[str, set[int]] = defaultdict(set)
        for activity_id, row in output.items():
            supports[course_code[int(activity_id)]].add(int(row["room_id"]))
        stability = sum(max(0, len(rooms) - 1) for rooms in supports.values())
        return int(capacity + stability)

    support_counts: dict[str, Counter[int]] = defaultdict(Counter)
    for activity_id, row in output.items():
        support_counts[course_code[int(activity_id)]][int(row["room_id"])] += 1
    current = int(room_objective())
    completed_no_change = False
    for sweep in range(max(1, int(max_sweeps))):
        if time.perf_counter() >= float(deadline):
            return output, "deadline_exhausted"
        changed = False
        order = periods if sweep % 2 == 0 else list(reversed(periods))
        for period in order:
            if time.perf_counter() >= float(deadline):
                return output, "deadline_exhausted"
            activity_ids = tuple(sorted(by_period[period]))
            old_rooms = {
                activity_id: int(output[activity_id]["room_id"])
                for activity_id in activity_ids
            }
            for activity_id, room_id in old_rooms.items():
                code = course_code[activity_id]
                support_counts[code][room_id] -= 1
                if support_counts[code][room_id] <= 0:
                    support_counts[code].pop(room_id, None)
            costs: dict[tuple[int, int], int] = {}
            old_conditional = 0
            for activity_id in activity_ids:
                code = course_code[activity_id]
                demand = int(students[code])
                outside_rooms = support_counts[code]
                old_room = int(old_rooms[activity_id])
                old_conditional += max(
                    0, demand - int(inst.rooms[old_room].capacity)
                ) + int(bool(outside_rooms) and old_room not in outside_rooms)
                for room_id in room_ids:
                    costs[(activity_id, room_id)] = max(
                        0, demand - int(inst.rooms[room_id].capacity)
                    ) + int(bool(outside_rooms) and room_id not in outside_rooms)
            assignment = _dense_assignment(activity_ids, room_ids, costs)
            new_conditional = sum(
                int(costs[(activity_id, room_id)])
                for activity_id, room_id in assignment.items()
            )
            for activity_id, room_id in assignment.items():
                output[activity_id]["room_id"] = int(room_id)
                support_counts[course_code[activity_id]][int(room_id)] += 1
            if new_conditional < old_conditional:
                current += int(new_conditional - old_conditional)
                changed = True
            else:
                for activity_id, room_id in assignment.items():
                    code = course_code[activity_id]
                    support_counts[code][room_id] -= 1
                    if support_counts[code][room_id] <= 0:
                        support_counts[code].pop(room_id, None)
                for activity_id, room_id in old_rooms.items():
                    output[activity_id]["room_id"] = int(room_id)
                    support_counts[course_code[activity_id]][int(room_id)] += 1
        # A complementary course block can remove stability penalties that
        # period-wise descent cannot cross. It is exact for the selected
        # course under the one-room restriction and accepts only strict global
        # room-objective descent.
        occupancy = {
            (period_by_activity[int(activity_id)], int(row["room_id"])): int(
                activity_id
            )
            for activity_id, row in output.items()
        }
        course_order = sorted(
            events_by_course,
            key=lambda code: (
                -len(support_counts[code]),
                str(code),
            ),
        )
        for code in course_order:
            if time.perf_counter() >= float(deadline):
                return output, "deadline_exhausted"
            activity_ids = events_by_course[code]
            if len(support_counts[code]) <= 1:
                continue
            current_course_cost = sum(
                max(
                    0,
                    int(students[code])
                    - int(inst.rooms[int(output[activity_id]["room_id"])].capacity),
                )
                for activity_id in activity_ids
            ) + len(support_counts[code]) - 1
            best_room: int | None = None
            best_cost = int(current_course_cost)
            for room_id in room_ids:
                if any(
                    (period_by_activity[activity_id], int(room_id)) in occupancy
                    and occupancy[(period_by_activity[activity_id], int(room_id))]
                    not in activity_ids
                    for activity_id in activity_ids
                ):
                    continue
                cost = sum(
                    max(
                        0,
                        int(students[code])
                        - int(inst.rooms[int(room_id)].capacity),
                    )
                    for _activity_id in activity_ids
                )
                if int(cost) < int(best_cost):
                    best_cost = int(cost)
                    best_room = int(room_id)
            if best_room is None:
                continue
            for activity_id in activity_ids:
                old_room = int(output[activity_id]["room_id"])
                occupancy.pop((period_by_activity[activity_id], old_room), None)
                support_counts[code][old_room] -= 1
                if support_counts[code][old_room] <= 0:
                    support_counts[code].pop(old_room, None)
            for activity_id in activity_ids:
                output[activity_id]["room_id"] = int(best_room)
                occupancy[(period_by_activity[activity_id], best_room)] = int(
                    activity_id
                )
                support_counts[code][best_room] += 1
            current = int(room_objective())
            changed = True
        if not changed:
            completed_no_change = True
            break
    return output, (
        "one_period_local_optimum" if completed_no_change else "sweep_limit"
    )


def _anneal_fixed_time_rooms(
    inst: Instance,
    schedule: Schedule,
    *,
    deadline: float,
    seed: int,
    max_iterations: int = 80_000,
) -> tuple[Schedule, str, dict[str, Any]]:
    """Escape one-period room minima with incremental swaps and relocations.

    Fixed times make room feasibility local to a period.  Moving a lecture to
    an empty room, or swapping it with that room's occupant, therefore
    preserves every hard ITC-2007 constraint.  Capacity and support-cardinality
    deltas are exact and O(1), which permits tens of thousands of stability
    ejection moves in the fraction of a second left by the time search.
    """

    started = time.perf_counter()
    output = _copy_schedule(schedule)
    if time.perf_counter() >= float(deadline):
        return output, "deadline_exhausted", {
            "iterations": 0,
            "accepted_moves": 0,
            "best_room_objective": None,
            "elapsed_seconds": float(time.perf_counter() - started),
        }

    metadata = dict(inst.sla_targets["itc2007"])
    students_by_code = {
        str(key): int(value)
        for key, value in dict(metadata["course_students"]).items()
    }
    course_id = {
        int(activity_id): int(inst.activities[int(activity_id)].course_id)
        for activity_id in output
    }
    students = {
        int(course.id): int(students_by_code[str(course.code)])
        for course in inst.courses.values()
    }
    rooms = tuple(sorted(int(room_id) for room_id in inst.rooms))
    activities = tuple(sorted(int(activity_id) for activity_id in output))
    activities_by_course: dict[int, tuple[int, ...]] = defaultdict(tuple)
    mutable_by_course: dict[int, list[int]] = defaultdict(list)
    period_by_activity: dict[int, tuple[int, str, int]] = {}
    occupancy: dict[tuple[tuple[int, str, int], int], int] = {}
    current_room: dict[int, int] = {}
    support_counts: dict[int, Counter[int]] = defaultdict(Counter)
    for activity_id in activities:
        row = output[activity_id]
        period = (int(row["week"]), str(row["day"]), int(row["slot"]))
        room_id = int(row["room_id"])
        period_by_activity[activity_id] = period
        occupancy[(period, room_id)] = int(activity_id)
        current_room[activity_id] = int(room_id)
        mutable_by_course[course_id[activity_id]].append(int(activity_id))
        support_counts[course_id[activity_id]][room_id] += 1
    activities_by_course = {
        int(value): tuple(sorted(members))
        for value, members in mutable_by_course.items()
    }
    capacity_cost = {
        (int(activity_id), int(room_id)): max(
            0,
            int(students[course_id[int(activity_id)]])
            - int(inst.rooms[int(room_id)].capacity),
        )
        for activity_id in activities
        for room_id in rooms
    }

    def stability(course: int) -> int:
        return max(0, len(support_counts[int(course)]) - 1)

    current_objective = int(
        sum(
            capacity_cost[(activity_id, room_id)]
            for activity_id, room_id in current_room.items()
        )
        + sum(stability(value) for value in activities_by_course)
    )
    initial_objective = int(current_objective)
    best_objective = int(current_objective)
    best_room = dict(current_room)
    rng = random.Random(int(seed))
    budget_seconds = max(1e-6, float(deadline) - float(started))
    iterations = 0
    accepted_moves = 0
    improving_moves = 0
    fragmented = sorted(
        int(value)
        for value in activities_by_course
        if len(support_counts[int(value)]) > 1
    )

    while (
        iterations < max(1, int(max_iterations))
        and time.perf_counter() < float(deadline)
    ):
        iterations += 1
        if iterations % 64 == 1:
            fragmented = sorted(
                int(value)
                for value in activities_by_course
                if len(support_counts[int(value)]) > 1
            )
        targeted = bool(fragmented) and rng.random() < 0.70
        if targeted:
            selected_course = int(rng.choice(fragmented))
            dominant_room = min(
                sorted(support_counts[selected_course]),
                key=lambda room_id: (
                    -support_counts[selected_course][room_id],
                    sum(
                        capacity_cost[(activity_id, int(room_id))]
                        for activity_id in activities_by_course[selected_course]
                    ),
                    int(room_id),
                ),
            )
            course_members = activities_by_course[selected_course]
            use_course_ejection = rng.random() < 0.18
            activity_id = int(rng.choice(course_members))
            target_room = int(dominant_room)
        else:
            activity_id = int(rng.choice(activities))
            target_room = int(rng.choice(rooms))
        source_room = int(current_room[activity_id])
        if source_room == target_room:
            continue

        period = period_by_activity[activity_id]
        moves: dict[int, int] = {}
        if targeted and use_course_ejection:
            for member in course_members:
                member_source = int(current_room[int(member)])
                if member_source == target_room:
                    continue
                member_period = period_by_activity[int(member)]
                occupant = occupancy.get((member_period, target_room))
                moves[int(member)] = int(target_room)
                if occupant is not None:
                    moves[int(occupant)] = int(member_source)
            if not moves:
                continue
        else:
            occupant = occupancy.get((period, target_room))
            moves = {int(activity_id): int(target_room)}
            if occupant is not None:
                moves[int(occupant)] = int(source_room)
        old_rooms = {
            int(member): int(current_room[int(member)]) for member in moves
        }
        affected_courses = {course_id[int(member)] for member in moves}
        before = sum(
            capacity_cost[(int(member), int(old_rooms[int(member)]))]
            for member in moves
        ) + sum(stability(value) for value in affected_courses)

        for member, old_room in old_rooms.items():
            member_course = course_id[int(member)]
            support_counts[member_course][int(old_room)] -= 1
            if support_counts[member_course][int(old_room)] <= 0:
                support_counts[member_course].pop(int(old_room), None)
        for member, new_room in moves.items():
            support_counts[course_id[int(member)]][int(new_room)] += 1
        after = sum(
            capacity_cost[(int(member), int(new_room))]
            for member, new_room in moves.items()
        ) + sum(stability(value) for value in affected_courses)
        delta = int(after - before)
        progress = min(
            1.0,
            max(
                0.0,
                (time.perf_counter() - started) / budget_seconds,
                iterations / max(1, int(max_iterations)),
            ),
        )
        temperature = max(0.05, 3.0 * (1.0 - progress))
        accept = delta <= 0 or rng.random() < math.exp(-float(delta) / temperature)
        if accept:
            accepted_moves += 1
            improving_moves += int(delta < 0)
            # Remove the whole alternating edge before inserting its new
            # endpoint rooms. Interleaving the two operations would erase the
            # first activity when a two-cycle swap processes its occupant.
            for member, old_room in old_rooms.items():
                occupancy.pop((period_by_activity[int(member)], old_room), None)
            for member, new_room in moves.items():
                occupancy[(period_by_activity[int(member)], int(new_room))] = int(
                    member
                )
                current_room[int(member)] = int(new_room)
            current_objective += int(delta)
            if current_objective < best_objective:
                best_objective = int(current_objective)
                best_room = dict(current_room)
        else:
            for member, new_room in moves.items():
                member_course = course_id[int(member)]
                support_counts[member_course][int(new_room)] -= 1
                if support_counts[member_course][int(new_room)] <= 0:
                    support_counts[member_course].pop(int(new_room), None)
            for member, old_room in old_rooms.items():
                support_counts[course_id[int(member)]][int(old_room)] += 1

    for activity_id, room_id in best_room.items():
        output[int(activity_id)]["room_id"] = int(room_id)
    finished = time.perf_counter()
    return output, (
        "improved" if best_objective < initial_objective else "completed"
    ), {
        "iterations": int(iterations),
        "accepted_moves": int(accepted_moves),
        "improving_moves": int(improving_moves),
        "initial_room_objective": int(initial_objective),
        "best_room_objective": int(best_objective),
        "elapsed_seconds": float(finished - started),
        "deadline_exhausted": bool(finished >= float(deadline)),
    }


def _course_room_ejection_descent(
    inst: Instance,
    schedule: Schedule,
    *,
    deadline: float,
    max_sweeps: int = 4,
) -> tuple[Schedule, str, dict[str, Any]]:
    """Deterministically consolidate a course through whole-week ejection chains.

    Fixed lecture times make a target-room conflict local to one period.  For a
    selected course, every lecture moves to the same target room and displaces
    that room's occupant into the lecture's vacated room.  The alternating
    chains therefore preserve room feasibility.  Capacity plus official course
    support cardinality is evaluated exactly, and only strict descent is
    accepted, so the complete incumbent remains safe at every checkpoint.
    """

    started = time.perf_counter()
    output = _copy_schedule(schedule)
    if time.perf_counter() >= float(deadline):
        return output, "deadline_exhausted", {
            "sweeps": 0,
            "candidates_evaluated": 0,
            "accepted_chains": 0,
            "initial_room_objective": None,
            "final_room_objective": None,
            "elapsed_seconds": float(time.perf_counter() - started),
            "deadline_exhausted": True,
        }
    if any(room.availability is not None for room in inst.rooms.values()):
        return output, "requires_universal_room_domains", {
            "sweeps": 0,
            "candidates_evaluated": 0,
            "accepted_chains": 0,
            "initial_room_objective": None,
            "final_room_objective": None,
            "elapsed_seconds": float(time.perf_counter() - started),
            "deadline_exhausted": False,
        }

    metadata = dict(inst.sla_targets["itc2007"])
    students = {
        str(key): int(value)
        for key, value in dict(metadata["course_students"]).items()
    }
    room_ids = tuple(sorted(int(room_id) for room_id in inst.rooms))
    course_code = {
        int(activity_id): str(
            inst.courses[int(inst.activities[int(activity_id)].course_id)].code
        )
        for activity_id in output
    }
    events_by_course: dict[str, list[int]] = defaultdict(list)
    period_by_activity: dict[int, tuple[int, str, int]] = {}
    occupancy: dict[tuple[tuple[int, str, int], int], int] = {}
    current_room: dict[int, int] = {}
    support_counts: dict[str, Counter[int]] = defaultdict(Counter)
    for activity_id in sorted(output):
        row = output[int(activity_id)]
        period = (int(row["week"]), str(row["day"]), int(row["slot"]))
        room_id = int(row["room_id"])
        code = course_code[int(activity_id)]
        events_by_course[code].append(int(activity_id))
        period_by_activity[int(activity_id)] = period
        occupancy[(period, room_id)] = int(activity_id)
        current_room[int(activity_id)] = int(room_id)
        support_counts[code][room_id] += 1
    events_by_course = {
        str(code): sorted(members)
        for code, members in sorted(events_by_course.items())
    }
    capacity_cost = {
        (int(activity_id), int(room_id)): max(
            0,
            int(students[course_code[int(activity_id)]])
            - int(inst.rooms[int(room_id)].capacity),
        )
        for activity_id in sorted(output)
        for room_id in room_ids
    }

    def stability(code: str) -> int:
        return max(0, len(support_counts[str(code)]) - 1)

    current_objective = int(
        sum(
            capacity_cost[(activity_id, room_id)]
            for activity_id, room_id in current_room.items()
        )
        + sum(stability(code) for code in events_by_course)
    )
    initial_objective = int(current_objective)
    candidates_evaluated = 0
    accepted_chains = 0
    completed_sweeps = 0
    termination_reason = "sweep_limit"

    for _sweep in range(max(1, int(max_sweeps))):
        if time.perf_counter() >= float(deadline):
            termination_reason = "deadline_exhausted"
            break
        course_order = sorted(
            (
                code
                for code in events_by_course
                if len(support_counts[code]) > 1
            ),
            key=lambda code: (
                -len(support_counts[code]),
                -len(events_by_course[code]),
                str(code),
            ),
        )
        best: tuple[
            tuple[int, int, tuple[tuple[int, int], ...]],
            dict[int, int],
            tuple[str, ...],
        ] | None = None
        for code in course_order:
            if time.perf_counter() >= float(deadline):
                termination_reason = "deadline_exhausted"
                break
            course_best: tuple[
                tuple[int, int, tuple[tuple[int, int], ...]],
                dict[int, int],
                tuple[str, ...],
            ] | None = None
            for target_room in room_ids:
                moves: dict[int, int] = {}
                collision = False
                for activity_id in events_by_course[code]:
                    source_room = int(current_room[int(activity_id)])
                    if source_room == int(target_room):
                        continue
                    period = period_by_activity[int(activity_id)]
                    occupant = occupancy.get((period, int(target_room)))
                    moves[int(activity_id)] = int(target_room)
                    if occupant is not None:
                        displaced = int(source_room)
                        previous = moves.get(int(occupant))
                        if previous is not None and previous != displaced:
                            collision = True
                            break
                        moves[int(occupant)] = displaced
                if collision or not moves:
                    continue
                destinations = {
                    (period_by_activity[int(activity_id)], int(room_id))
                    for activity_id, room_id in moves.items()
                }
                if len(destinations) != len(moves):
                    continue
                if any(
                    (occupant := occupancy.get(destination)) is not None
                    and int(occupant) not in moves
                    for destination in destinations
                ):
                    continue
                candidates_evaluated += 1
                affected = tuple(
                    sorted(
                        {
                            course_code[int(activity_id)]
                            for activity_id in moves
                        }
                    )
                )
                before = sum(
                    capacity_cost[
                        (int(activity_id), int(current_room[int(activity_id)]))
                    ]
                    for activity_id in moves
                ) + sum(stability(value) for value in affected)
                simulated = {
                    value: Counter(support_counts[value]) for value in affected
                }
                for activity_id, new_room in sorted(moves.items()):
                    moved_code = course_code[int(activity_id)]
                    old_room = int(current_room[int(activity_id)])
                    simulated[moved_code][old_room] -= 1
                    if simulated[moved_code][old_room] <= 0:
                        simulated[moved_code].pop(old_room, None)
                    simulated[moved_code][int(new_room)] += 1
                after = sum(
                    capacity_cost[(int(activity_id), int(new_room))]
                    for activity_id, new_room in moves.items()
                ) + sum(
                    max(0, len(simulated[value]) - 1) for value in affected
                )
                delta = int(after - before)
                fingerprint = tuple(sorted(moves.items()))
                key = (int(delta), int(target_room), fingerprint)
                if int(delta) < 0 and (
                    course_best is None or key < course_best[0]
                ):
                    course_best = (key, moves, affected)
            if course_best is not None:
                best = course_best
                break
        if termination_reason == "deadline_exhausted":
            break
        if best is None:
            completed_sweeps += 1
            termination_reason = "local_optimum"
            break

        (best_key, moves, _affected) = best
        old_rooms = {
            int(activity_id): int(current_room[int(activity_id)])
            for activity_id in moves
        }
        for activity_id, old_room in sorted(old_rooms.items()):
            moved_code = course_code[int(activity_id)]
            support_counts[moved_code][int(old_room)] -= 1
            if support_counts[moved_code][int(old_room)] <= 0:
                support_counts[moved_code].pop(int(old_room), None)
            occupancy.pop(
                (period_by_activity[int(activity_id)], int(old_room)),
                None,
            )
        for activity_id, new_room in sorted(moves.items()):
            moved_code = course_code[int(activity_id)]
            support_counts[moved_code][int(new_room)] += 1
            occupancy[
                (period_by_activity[int(activity_id)], int(new_room))
            ] = int(activity_id)
            current_room[int(activity_id)] = int(new_room)
        current_objective += int(best_key[0])
        accepted_chains += 1
        completed_sweeps += 1

    for activity_id, room_id in sorted(current_room.items()):
        output[int(activity_id)]["room_id"] = int(room_id)
    finished = time.perf_counter()
    return output, (
        "improved" if current_objective < initial_objective else termination_reason
    ), {
        "sweeps": int(completed_sweeps),
        "candidates_evaluated": int(candidates_evaluated),
        "accepted_chains": int(accepted_chains),
        "initial_room_objective": int(initial_objective),
        "final_room_objective": int(current_objective),
        "improvement": int(initial_objective - current_objective),
        "elapsed_seconds": float(finished - started),
        "termination_reason": str(termination_reason),
        "deadline_exhausted": bool(finished >= float(deadline)),
    }


def _polish_large_fixed_time_rooms(
    inst: Instance,
    schedule: Schedule,
    *,
    deadline: float,
    seed: int,
    validator: Validator,
    max_cycles: int = 3,
) -> tuple[Schedule, dict[str, Any]]:
    """Retain the best complete room incumbent across bounded polish cycles."""

    started = time.perf_counter()
    selected = _copy_schedule(schedule)
    selected_score = int(score_itc2007_instance_schedule(inst, selected).total)
    trace: list[dict[str, Any]] = []
    cycles_completed = 0
    for cycle in range(max(1, int(max_cycles))):
        now = time.perf_counter()
        remaining = max(0.0, float(deadline) - now)
        if remaining <= 0.04:
            break
        ejection_deadline = min(
            float(deadline) - 0.02,
            now + min(0.20, max(0.02, remaining * 0.22)),
        )
        ejected, ejection_status, ejection_meta = _course_room_ejection_descent(
            inst,
            selected,
            deadline=float(ejection_deadline),
            max_sweeps=16,
        )
        ejection_score = int(score_itc2007_instance_schedule(inst, ejected).total)
        ejection_errors = list(validator(inst, ejected))
        ejection_accepted = bool(
            time.perf_counter() < float(deadline)
            and not ejection_errors
            and ejection_score < selected_score
        )
        if ejection_accepted:
            selected = ejected
            selected_score = int(ejection_score)
        trace.append(
            {
                "cycle": int(cycle),
                "phase": "course_room_ejection",
                "status": str(ejection_status),
                "official_score": int(ejection_score),
                "accepted": bool(ejection_accepted),
                "valid": not ejection_errors,
                "telemetry": dict(ejection_meta),
            }
        )

        now = time.perf_counter()
        remaining = max(0.0, float(deadline) - now)
        if remaining <= 0.04:
            break
        cycles_left = max(1, int(max_cycles) - cycle)
        anneal_deadline = min(
            float(deadline),
            now + max(0.04, remaining / cycles_left),
        )
        annealed, annealing_status, annealing_meta = _anneal_fixed_time_rooms(
            inst,
            selected,
            deadline=float(anneal_deadline),
            seed=int(seed) + 104_729 * (cycle + 1),
            max_iterations=35_000,
        )
        annealed_score = int(
            score_itc2007_instance_schedule(inst, annealed).total
        )
        annealed_errors = list(validator(inst, annealed))
        annealed_accepted = bool(
            time.perf_counter() < float(deadline)
            and not annealed_errors
            and annealed_score < selected_score
        )
        if annealed_accepted:
            selected = annealed
            selected_score = int(annealed_score)
        trace.append(
            {
                "cycle": int(cycle),
                "phase": "room_annealing",
                "status": str(annealing_status),
                "official_score": int(annealed_score),
                "accepted": bool(annealed_accepted),
                "valid": not annealed_errors,
                "telemetry": dict(annealing_meta),
            }
        )
        cycles_completed += 1

    finished = time.perf_counter()
    return selected, {
        "cycles_requested": int(max_cycles),
        "cycles_completed": int(cycles_completed),
        "final_score": int(selected_score),
        "trace": trace,
        "elapsed_seconds": float(finished - started),
        "deadline_exhausted": bool(finished >= float(deadline)),
    }


def _exact_fixed_time_room_lift(
    inst: Instance,
    schedule: Schedule,
    *,
    deadline: float,
    seed: int,
) -> tuple[Schedule | None, str]:
    """Jointly minimize official ITC room capacity and stability at fixed times.

    This is intentionally a compact benchmark adapter rather than another full
    timetable model: only activity-room literals and course-room support
    literals are constructed. All period decisions are constants.
    """

    started = time.perf_counter()
    remaining = max(0.0, float(deadline) - float(started))
    if remaining <= 0.015:
        return None, "deadline_exhausted"

    metadata = dict(inst.sla_targets["itc2007"])
    students = {
        str(key): int(value)
        for key, value in dict(metadata["course_students"]).items()
    }
    room_ids = tuple(sorted(int(value) for value in inst.rooms))
    model = cp_model.CpModel()
    activity_room: dict[tuple[int, int], cp_model.IntVar] = {}
    by_period_room: dict[tuple[int, str, int, int], list[cp_model.IntVar]] = (
        defaultdict(list)
    )
    by_course_room: dict[tuple[str, int], list[cp_model.IntVar]] = defaultdict(list)
    capacity_terms: list[cp_model.LinearExpr] = []

    for activity_id in sorted(schedule):
        if time.perf_counter() >= float(deadline):
            return None, "deadline_exhausted"
        row = schedule[int(activity_id)]
        activity = inst.activities[int(activity_id)]
        course = inst.courses[int(activity.course_id)]
        code = str(course.code)
        demand = int(students[code])
        literals: list[cp_model.IntVar] = []
        for room_id in room_ids:
            literal = model.new_bool_var(f"room_a{activity_id}_r{room_id}")
            activity_room[(int(activity_id), int(room_id))] = literal
            literals.append(literal)
            by_period_room[
                (
                    int(row["week"]),
                    str(row["day"]),
                    int(row["slot"]),
                    int(room_id),
                )
            ].append(literal)
            by_course_room[(code, int(room_id))].append(literal)
            overflow = max(0, demand - int(inst.rooms[int(room_id)].capacity))
            if overflow:
                capacity_terms.append(int(overflow) * literal)
        model.add_exactly_one(literals)

    for literals in by_period_room.values():
        if len(literals) > 1:
            model.add_at_most_one(literals)

    stability_terms: list[cp_model.IntVar] = []
    for (code, room_id), literals in sorted(by_course_room.items()):
        used = model.new_bool_var(f"course_{code}_uses_r{room_id}")
        for literal in literals:
            model.add(literal <= used)
        # Equality prevents unconstrained support variables in hints/bounds.
        model.add(used <= sum(literals))
        stability_terms.append(used)

    room_objective = sum(capacity_terms) + sum(stability_terms)
    incumbent_support = {
        (
            str(inst.courses[int(inst.activities[activity_id].course_id)].code),
            int(row["room_id"]),
        )
        for activity_id, row in schedule.items()
    }
    incumbent_capacity = sum(
        max(
            0,
            int(
                students[
                    str(
                        inst.courses[
                            int(inst.activities[int(activity_id)].course_id)
                        ].code
                    )
                ]
            )
            - int(inst.rooms[int(row["room_id"])].capacity),
        )
        for activity_id, row in schedule.items()
    )
    incumbent_room_objective = int(incumbent_capacity + len(incumbent_support))
    model.add(room_objective <= int(incumbent_room_objective))
    model.minimize(room_objective)
    for (activity_id, room_id), literal in activity_room.items():
        model.add_hint(
            literal,
            int(schedule[int(activity_id)].get("room_id") == int(room_id)),
        )

    build_finished = time.perf_counter()
    search_budget = max(0.0, float(deadline) - float(build_finished) - 0.08)
    if search_budget <= 0:
        return None, "deadline_exhausted"
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(search_budget)
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = int(seed)
    solver.parameters.log_search_progress = False
    raw_status = int(solver.solve(model))
    if raw_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, str(cp_model.CpSolverStatus(raw_status)).lower()
    if time.perf_counter() >= float(deadline):
        return None, "deadline_exhausted"

    lifted = _copy_schedule(schedule)
    for activity_id in sorted(lifted):
        selected = [
            room_id
            for room_id in room_ids
            if solver.boolean_value(activity_room[(int(activity_id), int(room_id))])
        ]
        if len(selected) != 1:
            return None, "invalid_cp_assignment"
        lifted[int(activity_id)]["room_id"] = int(selected[0])
    return lifted, str(cp_model.CpSolverStatus(raw_status)).lower()


def itc2007_fixed_time_room_cp_eligibility(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
) -> tuple[bool, tuple[str, ...]]:
    """Recognize the lossless official ITC-2007 model used by the room CP."""

    eligible, raw_reasons = projected_time_search_eligibility(inst, schedule)
    reasons = list(raw_reasons)
    sla = getattr(inst, "sla_targets", {}) or {}
    metadata = sla.get("itc2007")
    if not isinstance(metadata, Mapping):
        metadata = {}
    expected_weights = {
        "room_capacity": 1,
        "minimum_working_days": 5,
        "curriculum_compactness": 2,
        "room_stability": 1,
    }
    try:
        weights = {
            str(key): int(value)
            for key, value in dict(metadata.get("objective_weights") or {}).items()
        }
    except (TypeError, ValueError):
        weights = {}
    if weights != expected_weights:
        reasons.append("requires_standard_itc2007_objective")
    if not str(sla.get("translation", "")).startswith("Lossless ITC-2007"):
        reasons.append("requires_lossless_itc2007_import")
    unmapped = sla.get("unmapped_soft_constraints")
    if not isinstance(unmapped, (list, tuple)) or list(unmapped):
        reasons.append("requires_lossless_itc2007_import")
    hard_constraints = getattr(inst, "hard_constraints", {}) or {}
    if hard_constraints.get("enforce_room_capacity") is not False:
        reasons.append("requires_soft_itc2007_room_capacity")
    if any(str(activity.kind) != "LEC" for activity in inst.activities.values()):
        reasons.append("requires_itc2007_lecture_activities")
    if any(str(room.room_type) != "LECTURE" for room in inst.rooms.values()):
        reasons.append("requires_itc2007_lecture_rooms")
    if any(room.availability is not None for room in inst.rooms.values()):
        # The compact CP intentionally uses the universal room domains of the
        # official CTT format. Canonical validation remains a second boundary.
        reasons.append("requires_universal_room_domains")
    unique_reasons = tuple(dict.fromkeys(reasons))
    return bool(eligible) and not unique_reasons, unique_reasons


def _fixed_starts_equal(
    left: Mapping[int, Mapping[str, Any]],
    right: Mapping[int, Mapping[str, Any]],
) -> bool:
    if {int(value) for value in left} != {int(value) for value in right}:
        return False
    fields = ("week", "day", "slot", "duration")
    for raw_activity_id in left:
        activity_id = int(raw_activity_id)
        if tuple(left[activity_id].get(field) for field in fields) != tuple(
            right[activity_id].get(field) for field in fields
        ):
            return False
    return True


def optimize_itc2007_fixed_time_rooms_cp(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float,
    seed: int = 0,
    validator: Validator | None = None,
) -> ITC2007FixedTimeRoomCPResult:
    """Optimize only ITC-2007 rooms and return an incumbent-safe result.

    The CP objective is exactly the sum of the two official terms affected by
    a fixed-time room reassignment: capacity overflow and course room
    stability. The public boundary independently validates the incumbent and
    candidate, verifies that every lecture start is unchanged, canonically
    rescores the full four-term objective, and exposes a candidate only when it
    is strictly better and completed before ``deadline``.
    """

    started = time.perf_counter()
    validation_fn = validator or _default_validator
    incumbent: Schedule = {}
    initial_score: ITC2007Score | None = None
    candidate_score: ITC2007Score | None = None
    solver_status = "not_started"
    validation_attempted = False
    validation_errors: tuple[str, ...] = ()
    fixed_starts_preserved: bool | None = None

    def finish(
        status: str,
        *,
        returned: Schedule | None = None,
        improved: bool = False,
        final_score: ITC2007Score | None = None,
        eligibility_reasons: tuple[str, ...] = (),
        error: str | None = None,
    ) -> ITC2007FixedTimeRoomCPResult:
        returned_schedule = _copy_schedule(
            incumbent if returned is None else returned
        )
        finished = time.perf_counter()
        return ITC2007FixedTimeRoomCPResult(
            schedule=returned_schedule,
            status=str(status),
            improved=bool(improved),
            initial_score=initial_score,
            final_score=(initial_score if final_score is None else final_score),
            candidate_score=candidate_score,
            solver_status=str(solver_status),
            eligibility_reasons=tuple(eligibility_reasons),
            validation_attempted=bool(validation_attempted),
            validation_errors=tuple(validation_errors),
            fixed_starts_preserved=fixed_starts_preserved,
            elapsed_seconds=float(finished - started),
            deadline_exhausted=bool(
                status == "deadline_exhausted" or finished >= float(deadline)
            ),
            deadline_overrun_seconds=max(0.0, finished - float(deadline)),
            error=error,
        )

    try:
        if not isinstance(schedule, Mapping):
            return finish(
                "ineligible",
                eligibility_reasons=("schedule_not_mapping",),
            )
        incumbent = _copy_schedule(schedule)
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")

        eligible, reasons = itc2007_fixed_time_room_cp_eligibility(
            inst,
            incumbent,
        )
        if not eligible:
            return finish("ineligible", eligibility_reasons=reasons)

        validation_attempted = True
        validation_errors = tuple(
            str(error) for error in validation_fn(inst, incumbent)
        )
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        if validation_errors:
            return finish("invalid_incumbent")

        initial_score = score_itc2007_instance_schedule(inst, incumbent)
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")

        candidate, solver_status = _exact_fixed_time_room_lift(
            inst,
            incumbent,
            deadline=float(deadline),
            seed=int(seed),
        )
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        if candidate is None:
            return finish(
                "deadline_exhausted"
                if solver_status == "deadline_exhausted"
                else "no_candidate"
            )

        fixed_starts_preserved = _fixed_starts_equal(incumbent, candidate)
        if not fixed_starts_preserved:
            return finish("fixed_starts_changed")

        validation_attempted = True
        validation_errors = tuple(
            str(error) for error in validation_fn(inst, candidate)
        )
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        if validation_errors:
            return finish("invalid_candidate")

        candidate_score = score_itc2007_instance_schedule(inst, candidate)
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        if int(candidate_score.total) >= int(initial_score.total):
            return finish("no_improvement")
        return finish(
            "improved",
            returned=candidate,
            improved=True,
            final_score=candidate_score,
        )
    except Exception as exc:
        return finish("error", error=f"{type(exc).__name__}: {exc}")


def _single_room_course_lift(
    inst: Instance,
    schedule: Schedule,
    *,
    deadline: float,
    seed: int,
) -> tuple[Schedule | None, str]:
    """Try the zero-stability course-coloring subproblem at fixed times."""

    metadata = dict(inst.sla_targets["itc2007"])
    students = {
        str(key): int(value)
        for key, value in dict(metadata["course_students"]).items()
    }
    room_ids = tuple(sorted(int(value) for value in inst.rooms))
    course_code = {
        int(activity_id): str(
            inst.courses[int(inst.activities[int(activity_id)].course_id)].code
        )
        for activity_id in schedule
    }
    events_by_course: dict[str, list[int]] = defaultdict(list)
    courses_by_period: dict[tuple[int, str, int], set[str]] = defaultdict(set)
    for activity_id, row in schedule.items():
        code = course_code[int(activity_id)]
        events_by_course[code].append(int(activity_id))
        courses_by_period[
            (int(row["week"]), str(row["day"]), int(row["slot"]))
        ].add(code)

    model = cp_model.CpModel()
    selected = {
        (code, room_id): model.new_bool_var(f"single_{code}_r{room_id}")
        for code in sorted(events_by_course)
        for room_id in room_ids
    }
    for code in sorted(events_by_course):
        model.add_exactly_one(selected[(code, room_id)] for room_id in room_ids)
    for codes in courses_by_period.values():
        if len(codes) < 2:
            continue
        for room_id in room_ids:
            model.add_at_most_one(selected[(code, room_id)] for code in sorted(codes))

    capacity_terms: list[cp_model.LinearExpr] = []
    for code, activity_ids in events_by_course.items():
        for room_id in room_ids:
            overflow = max(
                0,
                int(students[code]) - int(inst.rooms[room_id].capacity),
            )
            if overflow:
                capacity_terms.append(
                    int(len(activity_ids) * overflow) * selected[(code, room_id)]
                )
    model.minimize(sum(capacity_terms))
    for code, activity_ids in events_by_course.items():
        incumbent_rooms = Counter(
            int(schedule[activity_id]["room_id"]) for activity_id in activity_ids
        )
        preferred = min(
            room_ids,
            key=lambda room_id: (-incumbent_rooms[room_id], int(room_id)),
        )
        for room_id in room_ids:
            model.add_hint(selected[(code, room_id)], int(room_id == preferred))

    remaining = max(0.0, float(deadline) - time.perf_counter() - 0.02)
    if remaining <= 0:
        return None, "deadline_exhausted"
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(remaining)
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = int(seed)
    raw_status = int(solver.solve(model))
    if raw_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, str(cp_model.CpSolverStatus(raw_status)).lower()
    if time.perf_counter() >= float(deadline):
        return None, "deadline_exhausted"
    output = _copy_schedule(schedule)
    for code, activity_ids in events_by_course.items():
        rooms = [
            room_id
            for room_id in room_ids
            if solver.boolean_value(selected[(code, room_id)])
        ]
        if len(rooms) != 1:
            return None, "invalid_course_assignment"
        for activity_id in activity_ids:
            output[activity_id]["room_id"] = int(rooms[0])
    return output, str(cp_model.CpSolverStatus(raw_status)).lower()


@dataclass
class _ProjectedTrajectoryResult:
    start_index: int
    start_kind: str
    trajectory_mode: str
    seed: int
    start_score: int
    start_stability_proxy: int
    best_score: int
    best_stability_proxy: int
    best_assignment: dict[int, int]
    elite_assignments: dict[
        tuple[tuple[int, int], ...], tuple[int, dict[int, int]]
    ]
    iterations: int
    candidates_evaluated: int
    accepted_moves: int
    accepted_by_family: Counter[str]
    trace: list[dict[str, Any]]
    elapsed_seconds: float
    termination_reason: str
    completed: bool
    iteration_limit: int | None


def _assignment_distance(
    left: Mapping[int, int],
    right: Mapping[int, int],
) -> int:
    return sum(
        int(int(left[activity_id]) != int(right[activity_id]))
        for activity_id in left
    )


def _projected_trajectory_iteration_checkpoint(
    *,
    activity_count: int,
    trajectory_mode: str,
    lossless_itc2007: bool = True,
) -> int | None:
    """Return a conservative deterministic checkpoint for dense instances.

    The dense imported-CTT path used to stop at whichever iteration happened
    to straddle a wall-clock check.  Its 32-candidate batches have stable work
    per iteration, so bounded structural checkpoints make the normal path
    reproducible while the deadline remains an independent fail-safe.  Smaller
    instances retain completion/stagnation search because they normally finish
    well inside their slice and benefit from doing so.
    """

    if not bool(lossless_itc2007) or int(activity_count) <= 256:
        return None
    return {
        "steepest_descent": 96,
        "late_acceptance": 64,
        # The dense long-horizon basin consistently matures after roughly
        # 350 iterations and continued improving through the measured
        # 500-560 range after the smaller batch reduced iteration cost.  The
        # 600 checkpoint retains that basin while the wall deadline remains
        # the hard stop and preserves downstream room/feedback reserves.
        "long_horizon": 600,
    }.get(str(trajectory_mode), 128)


def _diversify_projected_start(
    inst: Instance,
    schedule: Schedule,
    *,
    deadline: float,
    seed: int,
    mode: str,
    target_moves: int,
) -> tuple[Schedule, dict[str, Any]]:
    """Create a feasible time-only start through deliberate large perturbations."""

    started = time.perf_counter()
    state = _ITCProjectedState(inst, schedule, seed=int(seed))
    original = dict(state.assignment)
    activity_ids = list(sorted(state.assignment))
    state.rng.shuffle(activity_ids)
    changed_moves = 0
    attempts = 0
    target = max(1, min(int(target_moves), len(activity_ids)))
    while (
        changed_moves < target
        and attempts < max(24, target * 18)
        and time.perf_counter() < float(deadline)
    ):
        activity_id = int(activity_ids[attempts % len(activity_ids)])
        source = int(state.assignment[activity_id])
        code = state.course_code[activity_id]
        if mode == "day_scatter":
            used_days = {
                state.assignment[member] // state.slots_per_day
                for member in state.events_by_course[code]
            }
            targets = [
                period
                for period in range(state.period_count)
                if period // state.slots_per_day not in used_days
            ]
            if not targets:
                targets = list(range(state.period_count))
        else:
            targets = sorted(
                range(state.period_count),
                key=lambda period: (
                    len(state.period_events[period]),
                    -abs(period - source),
                    period,
                ),
            )
            rotate = attempts % max(1, len(targets))
            targets = targets[rotate:] + targets[:rotate]
        state.rng.shuffle(targets)
        applied = False
        for target_period in targets[: max(6, state.slots_per_day * 2)]:
            if time.perf_counter() >= float(deadline):
                break
            if int(target_period) == source:
                continue
            direct = {int(activity_id): int(target_period)}
            candidate = direct if state.feasible(direct) else state.kempe_move(
                int(activity_id), int(target_period)
            )
            if candidate is None:
                continue
            state.apply(candidate)
            changed_moves += 1
            applied = True
            break
        attempts += 1
        if not applied and attempts % len(activity_ids) == 0:
            state.rng.shuffle(activity_ids)
    distance = _assignment_distance(original, state.assignment)
    return state.materialize(), {
        "status": "generated" if distance else "duplicate",
        "mode": str(mode),
        "target_moves": int(target),
        "accepted_perturbations": int(changed_moves),
        "activity_distance": int(distance),
        "attempts": int(attempts),
        "elapsed_seconds": float(time.perf_counter() - started),
        "deadline_exhausted": bool(time.perf_counter() >= float(deadline)),
    }


def _run_projected_trajectory(
    inst: Instance,
    schedule: Schedule,
    *,
    deadline: float,
    seed: int,
    candidate_batch_size: int,
    start_index: int,
    start_kind: str,
    trajectory_mode: str,
    global_started: float,
    iteration_limit: int | None = None,
) -> _ProjectedTrajectoryResult:
    started = time.perf_counter()
    state = _ITCProjectedState(inst, schedule, seed=int(seed))
    start_score = int(state.score)
    start_stability_proxy = int(state.stability_proxy)
    best_score = int(state.score)
    best_stability_proxy = int(state.stability_proxy)
    best_assignment = dict(state.assignment)
    elite_assignments: dict[
        tuple[tuple[int, int], ...], tuple[int, dict[int, int]]
    ] = {
        tuple(sorted(best_assignment.items())): (
            int(best_score),
            dict(best_assignment),
        )
    }
    current_score = int(state.score)
    current_stability_proxy = int(state.stability_proxy)
    history_length = {
        "steepest_descent": 1,
        "late_acceptance": 64,
        "long_horizon": 128,
    }.get(str(trajectory_mode), 64)
    late_history = [int(current_score)] * int(history_length)
    stagnation_limit = {
        "steepest_descent": 120,
        "late_acceptance": 180,
        "long_horizon": 240,
    }.get(str(trajectory_mode), 180)
    tabu_until: dict[int, int] = {}
    accepted_by_family: Counter[str] = Counter()
    trace: list[dict[str, Any]] = []
    iterations = 0
    last_best_iteration = 0
    candidates_evaluated = 0
    accepted_moves = 0
    termination_reason = "deadline"

    while (
        (iteration_limit is None or iterations < int(iteration_limit))
        and time.perf_counter() < float(deadline)
    ):
        if (
            int(best_score) <= int(state.projected_lower_bound)
            and int(best_stability_proxy) <= 0
        ):
            termination_reason = "projected_lower_bound"
            break
        if iterations - last_best_iteration >= int(stagnation_limit):
            termination_reason = "stagnation"
            break
        iterations += 1
        candidates = state.candidate_moves(limit=max(8, int(candidate_batch_size)))
        if not candidates:
            termination_reason = "no_candidates"
            break
        history_bound = int(late_history[iterations % len(late_history)])
        if trajectory_mode == "steepest_descent":
            history_bound = int(current_score)
        chosen: tuple[dict[int, int], str, int, int, int] | None = None
        chosen_key: tuple[
            int,
            int,
            int,
            int,
            str,
            tuple[tuple[int, int], ...],
        ] | None = None
        for move, family in candidates:
            if time.perf_counter() >= float(deadline):
                break
            delta = int(state.delta(move))
            proxy_delta = int(state.stability_proxy_delta(move))
            candidates_evaluated += 1
            next_score = int(current_score + delta)
            next_proxy = int(current_stability_proxy + proxy_delta)
            tabu = any(
                tabu_until.get(int(activity_id), 0) > iterations
                for activity_id in move
            )
            aspiration = (next_score, next_proxy) < (
                best_score,
                best_stability_proxy,
            )
            admissible = aspiration or (
                not tabu
                and (
                    next_score < history_bound
                    or (
                        next_score == history_bound
                        and next_proxy <= current_stability_proxy
                    )
                )
            )
            if not admissible:
                continue
            family_priority = (
                0 if family.startswith("minimum_days") else 1
            )
            if trajectory_mode == "long_horizon":
                family_priority = 0 if family.startswith("compactness") else 1
            key = (
                int(next_score),
                int(next_proxy),
                len(move),
                int(family_priority),
                str(family),
                tuple(
                    sorted(
                        (int(activity_id), int(period))
                        for activity_id, period in move.items()
                    )
                ),
            )
            if chosen is None or key < chosen_key:
                chosen = (move, family, delta, next_score, next_proxy)
                chosen_key = key
        late_history[iterations % len(late_history)] = int(current_score)
        if chosen is None:
            if current_score != best_score:
                state.restore(best_assignment)
                current_score = int(state.score)
                current_stability_proxy = int(state.stability_proxy)
                tabu_until.clear()
                continue
            termination_reason = "local_optimum"
            break

        move, family, delta, next_score, next_proxy = chosen
        state.apply(move)
        if int(state.score) != int(next_score):
            raise AssertionError(
                f"Projected delta drift: expected {next_score}, got {state.score}"
            )
        current_score = int(next_score)
        current_stability_proxy = int(next_proxy)
        if int(state.stability_proxy) != int(next_proxy):
            raise AssertionError(
                "Projected stability proxy drift: "
                f"expected {next_proxy}, got {state.stability_proxy}"
            )
        accepted_moves += 1
        accepted_by_family[str(family)] += 1
        tenure_base = 3 if trajectory_mode == "steepest_descent" else 5
        tenure_range = 6 if trajectory_mode == "steepest_descent" else 8
        if trajectory_mode == "long_horizon":
            tenure_base, tenure_range = 7, 12
        tenure = int(tenure_base + state.rng.randrange(tenure_range))
        for activity_id in move:
            tabu_until[int(activity_id)] = int(iterations + tenure)
        if (current_score, current_stability_proxy) < (
            best_score,
            best_stability_proxy,
        ):
            best_score = int(current_score)
            best_stability_proxy = int(current_stability_proxy)
            best_assignment = dict(state.assignment)
            last_best_iteration = int(iterations)
            elite_assignments[tuple(sorted(best_assignment.items()))] = (
                int(best_score),
                dict(best_assignment),
            )
            trace.append(
                {
                    "start_index": int(start_index),
                    "start_kind": str(start_kind),
                    "trajectory_mode": str(trajectory_mode),
                    "iteration": int(iterations),
                    "projected_score": int(best_score),
                    "stability_proxy": int(best_stability_proxy),
                    "delta": int(delta),
                    "family": str(family),
                    "moved": int(len(move)),
                    "elapsed_seconds": float(
                        time.perf_counter() - global_started
                    ),
                }
            )
            if len(trace) > 96:
                trace = trace[-96:]
        if iterations % 8 == 0 and current_score <= best_score + 8:
            fingerprint = tuple(sorted(state.assignment.items()))
            elite_assignments[fingerprint] = (
                int(current_score),
                dict(state.assignment),
            )
            if len(elite_assignments) > 24:
                worst = max(
                    elite_assignments,
                    key=lambda key: (elite_assignments[key][0], key),
                )
                elite_assignments.pop(worst, None)
        restore_interval = 48 if trajectory_mode == "steepest_descent" else 80
        if iterations % restore_interval == 0 and current_score > best_score:
            state.restore(best_assignment)
            current_score = int(state.score)
            current_stability_proxy = int(state.stability_proxy)
            tabu_until.clear()
    else:
        termination_reason = (
            "iteration_checkpoint"
            if iteration_limit is not None
            and iterations >= int(iteration_limit)
            else "deadline"
        )

    return _ProjectedTrajectoryResult(
        start_index=int(start_index),
        start_kind=str(start_kind),
        trajectory_mode=str(trajectory_mode),
        seed=int(seed),
        start_score=int(start_score),
        start_stability_proxy=int(start_stability_proxy),
        best_score=int(best_score),
        best_stability_proxy=int(best_stability_proxy),
        best_assignment=dict(best_assignment),
        elite_assignments=elite_assignments,
        iterations=int(iterations),
        candidates_evaluated=int(candidates_evaluated),
        accepted_moves=int(accepted_moves),
        accepted_by_family=accepted_by_family,
        trace=trace,
        elapsed_seconds=float(time.perf_counter() - started),
        termination_reason=str(termination_reason),
        completed=bool(time.perf_counter() < float(deadline)),
        iteration_limit=(
            None if iteration_limit is None else int(iteration_limit)
        ),
    )


def optimize_projected_times(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float,
    seed: int = 0,
    candidate_batch_size: int = 96,
    adapt_dense_default_batch: bool = False,
    room_reserve_seconds: float = 0.75,
    validator: Validator | None = None,
    multi_start_count: int = 3,
    enable_constructive_start: bool = True,
    constructive_start_min_seconds: float = 3.0,
    small_room_cp_budget_seconds: float | None = None,
) -> ProjectedTimeSearchResult:
    """Run bounded projected multi-start search, then lift the global elites.

    Search acceptance uses an exact projected objective: official minimum-working
    days and compactness plus the per-period minimum room-capacity penalty. The
    projection deliberately excludes room stability. Returned schedules are
    accepted only after a complete room lift, canonical score comparison, and
    strict full validation. The incumbent, deterministic structural
    perturbations, and (when the budget is large enough) a fresh course-coloring
    construction use independent search trajectories under one shared deadline.
    """

    started = time.perf_counter()
    incumbent = _copy_schedule(schedule)
    validation_fn = validator or _default_validator
    effective_candidate_batch_size = max(8, int(candidate_batch_size))
    starts_requested = max(1, min(8, int(multi_start_count)))
    initial_score = int(score_itc2007_instance_schedule(inst, incumbent).total)
    eligible, reasons = projected_time_search_eligibility(inst, incumbent)
    try:
        lossless_itc2007, _lossless_reasons = (
            itc2007_fixed_time_room_cp_eligibility(inst, incumbent)
        )
    except Exception:
        lossless_itc2007 = False
    dense_lossless_policy = bool(
        eligible and lossless_itc2007 and len(inst.activities) > 256
    )
    if dense_lossless_policy and bool(adapt_dense_default_batch):
        # Only the service-owned large-instance default is adapted.  Direct
        # callers keep their explicit batch, including an explicit value 32.
        effective_candidate_batch_size = 24
    if not eligible:
        return ProjectedTimeSearchResult(
            schedule=incumbent,
            status="ineligible:" + ",".join(reasons),
            initial_score=initial_score,
            final_score=initial_score,
            initial_projected_score=initial_score,
            final_projected_score=initial_score,
            projected_lower_bound=0,
            elapsed_seconds=float(time.perf_counter() - started),
            iterations=0,
            candidates_evaluated=0,
            accepted_moves=0,
            starts_requested=int(starts_requested),
            starts_generated=1,
        )
    incumbent_errors = list(validation_fn(inst, incumbent))
    if incumbent_errors:
        return ProjectedTimeSearchResult(
            schedule=incumbent,
            status="invalid_incumbent",
            initial_score=initial_score,
            final_score=initial_score,
            initial_projected_score=initial_score,
            final_projected_score=initial_score,
            projected_lower_bound=0,
            elapsed_seconds=float(time.perf_counter() - started),
            iterations=0,
            candidates_evaluated=0,
            accepted_moves=0,
            starts_requested=int(starts_requested),
            starts_generated=1,
        )
    if time.perf_counter() >= float(deadline):
        return ProjectedTimeSearchResult(
            schedule=incumbent,
            status="deadline_exhausted",
            initial_score=int(initial_score),
            final_score=int(initial_score),
            initial_projected_score=int(initial_score),
            final_projected_score=int(initial_score),
            projected_lower_bound=0,
            elapsed_seconds=float(time.perf_counter() - started),
            iterations=0,
            candidates_evaluated=0,
            accepted_moves=0,
            starts_requested=int(starts_requested),
            starts_generated=1,
            deadline_exhausted=True,
            deadline_overrun_seconds=max(
                0.0, time.perf_counter() - float(deadline)
            ),
        )

    base_state = _ITCProjectedState(inst, incumbent, seed=int(seed))
    initial_projected = int(base_state.score)
    base_assignment = dict(base_state.assignment)
    completion_reserve = min(
        0.25,
        max(0.02, (float(deadline) - float(started)) * 0.10),
    )
    work_deadline = max(float(started), float(deadline) - completion_reserve)
    search_deadline = max(
        float(started),
        min(
            float(work_deadline),
            float(deadline) - max(0.05, float(room_reserve_seconds)),
        ),
    )

    starts: list[dict[str, Any]] = [
        {
            "index": 0,
            "kind": "incumbent",
            "trajectory_mode": "late_acceptance",
            "schedule": incumbent,
            "start_score": int(initial_projected),
            "generation": {
                "status": "provided_incumbent",
                "activity_distance": 0,
                "elapsed_seconds": 0.0,
            },
        }
    ]
    fingerprints = {tuple(sorted(base_assignment.items()))}
    search_window = max(0.0, float(search_deadline) - float(started))
    admitted_start_target = int(starts_requested)
    if len(inst.activities) > 256:
        # On the dense comp07-style regime, a third shallow trajectory loses
        # to giving the deliberately distant day-scatter basin enough time to
        # mature. Improvement velocity, rather than its poor pilot score, is
        # the useful signal here; retain the incumbent plus one long-horizon
        # structural start.
        admitted_start_target = min(admitted_start_target, 2)
    if (
        len(inst.activities) > 256
        and search_window / max(1, starts_requested) < 0.75
    ):
        admitted_start_target = 1
        starts[0]["generation"]["admission_policy"] = (
            "single_survivor_for_short_large_instance"
        )

    if (
        admitted_start_target > 1
        and bool(enable_constructive_start)
        and search_window >= max(0.1, float(constructive_start_min_seconds))
        and time.perf_counter() < float(search_deadline)
    ):
        construction_started = time.perf_counter()
        construction_budget = min(
            0.75,
            max(0.10, search_window * 0.18),
        )
        construction_deadline = min(
            float(search_deadline),
            construction_started + float(construction_budget),
        )
        # When the service already supplies a complete constructive incumbent,
        # another constructor mostly reproduces the same basin while consuming
        # roughly 0.6s on comp07. A structural perturbation gives the racing
        # controller a genuinely different start at a fraction of that cost.
        strategy = ("balanced", "compact", "spread", "room")[
            abs(int(seed)) % 4
        ]
        incumbent_is_constructive = bool(
            schedule
            and all(
                str(row.get("source", "")) == "itc2007_course_constructive"
                for row in schedule.values()
            )
        )
        if incumbent_is_constructive:
            constructed = None
        else:
            constructed = construct_itc2007_schedule(
                inst,
                deadline=float(construction_deadline),
                seed=int(seed) + 400_009,
                max_starts=1,
                strategies=(strategy,),
                beam_width=4,
                bundle_limit=2,
                validator=validation_fn,
            )
        if constructed is not None and constructed.schedule is not None:
            constructed_state = _ITCProjectedState(
                inst,
                constructed.schedule,
                seed=int(seed) + 400_009,
            )
            fingerprint = tuple(sorted(constructed_state.assignment.items()))
            if fingerprint not in fingerprints:
                fingerprints.add(fingerprint)
                starts.append(
                    {
                        "index": len(starts),
                        "kind": f"constructive_{strategy}",
                        "trajectory_mode": "steepest_descent",
                        "schedule": constructed.schedule,
                        "start_score": int(constructed_state.score),
                        "generation": constructed.to_dict(),
                    }
                )

    diversification_modes = ("day_scatter", "load_rotate")
    generation_index = 0
    while (
        len(starts) < admitted_start_target
        and time.perf_counter() < float(search_deadline)
    ):
        remaining_slots = admitted_start_target - len(starts)
        remaining = max(0.0, float(search_deadline) - time.perf_counter())
        if remaining <= 0.01:
            break
        generation_deadline = min(
            float(search_deadline),
            time.perf_counter()
            + min(0.08, max(0.01, remaining * 0.08 / remaining_slots)),
        )
        mode = diversification_modes[generation_index % len(diversification_modes)]
        source = starts[generation_index % len(starts)]["schedule"]
        diversified, generation = _diversify_projected_start(
            inst,
            source,
            deadline=float(generation_deadline),
            seed=int(seed) + 1_000_003 * (generation_index + 1),
            mode=str(mode),
            target_moves=max(4, min(24, len(inst.activities) // 16)),
        )
        diversified_state = _ITCProjectedState(
            inst,
            diversified,
            seed=int(seed) + 1_000_003 * (generation_index + 1),
        )
        fingerprint = tuple(sorted(diversified_state.assignment.items()))
        generation_index += 1
        if fingerprint in fingerprints:
            if generation_index >= admitted_start_target * 3:
                break
            continue
        fingerprints.add(fingerprint)
        starts.append(
            {
                "index": len(starts),
                "kind": f"structural_{mode}",
                "trajectory_mode": (
                    "long_horizon" if mode == "day_scatter" else "steepest_descent"
                ),
                "schedule": diversified,
                "start_score": int(diversified_state.score),
                "generation": generation,
            }
        )

    ranked_starts = sorted(
        starts,
        key=lambda row: (
            int(row["start_score"]),
            int(row["index"] != 0),
            int(row["index"]),
        ),
    )
    global_elites: dict[
        tuple[tuple[int, int], ...], tuple[int, dict[int, int], int]
    ] = {
        tuple(sorted(base_assignment.items())): (
            int(initial_projected),
            dict(base_assignment),
            0,
        )
    }
    accepted_by_family: Counter[str] = Counter()
    trace: list[dict[str, Any]] = []
    start_telemetry: list[dict[str, Any]] = []
    iterations = 0
    candidates_evaluated = 0
    accepted_moves = 0
    starts_completed = 0
    best_start_score = min(int(row["start_score"]) for row in ranked_starts)
    score_scale = max(8.0, abs(float(best_start_score)) * 0.15)
    # Deterministic quality racing: structurally promising starts receive most
    # of the budget, while every admitted start retains a small probe. This
    # avoids paying an equal third of a short comp07 budget to a deliberately
    # distant construction whose projected score is already much worse.
    if len(inst.activities) > 256:
        remaining_weights = [
            3.0 if str(row["trajectory_mode"]) == "long_horizon" else 1.0
            for row in ranked_starts
        ]
    else:
        remaining_weights = [
            max(
                0.03,
                (
                    1.0
                    + max(0.0, int(row["start_score"]) - best_start_score)
                    / score_scale
                )
                ** -3,
            )
            for row in ranked_starts
        ]
    for rank, start_row in enumerate(ranked_starts):
        now = time.perf_counter()
        if now >= float(search_deadline):
            break
        remaining = max(0.0, float(search_deadline) - now)
        weight_left = sum(remaining_weights[rank:])
        share = (
            remaining
            if rank + 1 == len(ranked_starts)
            else remaining * remaining_weights[rank] / max(1e-9, weight_left)
        )
        trajectory_deadline = min(float(search_deadline), now + max(0.002, share))
        iteration_limit = _projected_trajectory_iteration_checkpoint(
            activity_count=len(inst.activities),
            trajectory_mode=str(start_row["trajectory_mode"]),
            lossless_itc2007=bool(dense_lossless_policy),
        )
        trajectory = _run_projected_trajectory(
            inst,
            start_row["schedule"],
            deadline=float(trajectory_deadline),
            seed=int(seed) + 65_537 * int(start_row["index"]),
            candidate_batch_size=int(effective_candidate_batch_size),
            start_index=int(start_row["index"]),
            start_kind=str(start_row["kind"]),
            trajectory_mode=str(start_row["trajectory_mode"]),
            global_started=float(started),
            iteration_limit=iteration_limit,
        )
        starts_completed += 1
        iterations += int(trajectory.iterations)
        candidates_evaluated += int(trajectory.candidates_evaluated)
        accepted_moves += int(trajectory.accepted_moves)
        accepted_by_family.update(trajectory.accepted_by_family)
        trace.extend(trajectory.trace)
        for fingerprint, (elite_score, assignment) in trajectory.elite_assignments.items():
            previous = global_elites.get(fingerprint)
            candidate = (
                int(elite_score),
                dict(assignment),
                int(trajectory.start_index),
            )
            if previous is None or (candidate[0], candidate[2]) < (
                previous[0],
                previous[2],
            ):
                global_elites[fingerprint] = candidate
        start_telemetry.append(
            {
                "start_index": int(trajectory.start_index),
                "start_kind": str(trajectory.start_kind),
                "trajectory_mode": str(trajectory.trajectory_mode),
                "seed": int(trajectory.seed),
                "rank": int(rank),
                "generation": dict(start_row["generation"]),
                "start_projected_score": int(trajectory.start_score),
                "start_stability_proxy": int(
                    trajectory.start_stability_proxy
                ),
                "final_projected_score": int(trajectory.best_score),
                "final_stability_proxy": int(
                    trajectory.best_stability_proxy
                ),
                "projected_improvement": int(
                    trajectory.start_score - trajectory.best_score
                ),
                "iterations": int(trajectory.iterations),
                "candidates_evaluated": int(trajectory.candidates_evaluated),
                "accepted_moves": int(trajectory.accepted_moves),
                "accepted_by_family": {
                    str(key): int(value)
                    for key, value in sorted(
                        trajectory.accepted_by_family.items()
                    )
                },
                "elite_count": int(len(trajectory.elite_assignments)),
                "elapsed_seconds": float(trajectory.elapsed_seconds),
                "termination_reason": str(trajectory.termination_reason),
                "iteration_limit": trajectory.iteration_limit,
                "iteration_checkpoint_reached": bool(
                    trajectory.iteration_limit is not None
                    and trajectory.iterations >= trajectory.iteration_limit
                ),
                "candidate_batch_size": int(effective_candidate_batch_size),
                "dense_lossless_policy": bool(dense_lossless_policy),
                "completed_before_slice_deadline": bool(trajectory.completed),
                "activity_distance_from_incumbent": int(
                    _assignment_distance(base_assignment, trajectory.best_assignment)
                ),
            }
        )

    trace = sorted(
        trace,
        key=lambda row: (
            float(row["elapsed_seconds"]),
            int(row["start_index"]),
            int(row["iteration"]),
        ),
    )[-192:]
    best_projected, _best_assignment, _best_start_index = min(
        global_elites.values(),
        key=lambda item: (
            int(item[0]),
            int(item[2]),
            tuple(sorted(item[1].items())),
        ),
    )

    best_schedule = incumbent
    final_score = int(initial_score)
    selected_start_index = 0
    oracle_status = "not_started"
    room_cp_status = "not_started"
    lift_status = "not_started"
    ordered_elites = sorted(
        global_elites.values(),
        key=lambda item: (
            int(item[0]),
            int(item[2]),
            tuple(sorted(item[1].items())),
        ),
    )
    remaining_for_rooms = max(0.0, work_deadline - time.perf_counter())
    # Lifting only the lexicographically first projected optimum is a poor
    # anytime policy: many time layouts have the same additive projection but
    # radically different cross-period room-stability cost.  First screen a
    # diverse set of elites with exact per-period capacity matching and cheap
    # stability-aware coordinate descent.  Then spend the remaining room
    # budget once, polishing the best *complete official-score* candidate with
    # the joint fixed-time CP model.  This turns room work into a funnel instead
    # of rebuilding an expensive CP model for every projected tie.
    small_screening_instance = len(inst.activities) <= 200
    screen_budget = (
        0.0
        if remaining_for_rooms <= 0.03
        # Screening is deliberately capped: the joint room CP benefits much
        # more from a contiguous search slice than a long tail of equivalent
        # time layouts does from additional cheap probes. Large instances get
        # one complete lift instead of paying validation/matching setup for a
        # shallow set of ties.
        else (
            min(0.25, max(0.04, remaining_for_rooms * 0.20))
            if small_screening_instance
            else min(0.30, max(0.12, remaining_for_rooms * 0.55))
        )
    )
    screen_deadline = min(
        float(work_deadline), time.perf_counter() + float(screen_budget)
    )
    estimated_screen_seconds = max(0.025, len(inst.activities) / 7_000.0)
    screen_limit = (
        0
        if screen_budget <= 0.0
        else min(3, len(ordered_elites))
        if not small_screening_instance
        else min(
            len(ordered_elites),
            8,
            max(1, int(screen_budget / estimated_screen_seconds)),
        )
    )
    # Guarantee representation from each generated start before filling the
    # remainder by projected score.  This is important when dozens of equal
    # optima were inserted by the first trajectory before later starts ran.
    first_by_start: dict[int, tuple[int, dict[int, int], int]] = {}
    for elite in ordered_elites:
        first_by_start.setdefault(int(elite[2]), elite)
    prioritized_elites = sorted(
        first_by_start.values(),
        key=lambda item: (
            int(item[0]),
            int(item[2]),
            tuple(sorted(item[1].items())),
        ),
    )
    represented = {
        tuple(sorted(item[1].items())) for item in prioritized_elites
    }
    prioritized_elites.extend(
        item
        for item in ordered_elites
        if tuple(sorted(item[1].items())) not in represented
    )

    screen_trace: list[dict[str, Any]] = []
    screened_candidates: list[
        tuple[int, int, int, Schedule]
    ] = []
    for elite_index, (
        projected_score,
        elite_assignment,
        elite_start_index,
    ) in enumerate(prioritized_elites[:screen_limit]):
        now = time.perf_counter()
        if now >= float(screen_deadline) - 0.005:
            break
        candidates_left = max(1, screen_limit - elite_index)
        slice_deadline = min(
            float(screen_deadline),
            now
            + max(
                0.025,
                (float(screen_deadline) - now) / candidates_left,
            ),
        )
        timed = base_state.materialize(elite_assignment)
        lifted, candidate_lift_status = _fast_capacity_lift(
            inst,
            timed,
            deadline=float(slice_deadline),
        )
        lift_status = str(candidate_lift_status)
        if lifted is None:
            screen_trace.append(
                {
                    "elite_index": int(elite_index),
                    "start_index": int(elite_start_index),
                    "projected_score": int(projected_score),
                    "status": str(candidate_lift_status),
                }
            )
            continue

        room_candidate = lifted
        coordinate_status = "not_started"
        annealing_status = "not_started"
        annealing_telemetry: dict[str, Any] = {}
        coordinate_remaining = max(
            0.0, float(slice_deadline) - time.perf_counter()
        )
        if coordinate_remaining > 0.008:
            coordinate_candidate, coordinate_status = _fast_coordinate_room_lift(
                inst,
                lifted,
                deadline=float(slice_deadline),
                max_sweeps=24,
            )
            if coordinate_candidate is not None:
                room_candidate = coordinate_candidate
        oracle_status = f"fast_coordinate_screen:{coordinate_status}"

        annealing_remaining = max(
            0.0, float(slice_deadline) - time.perf_counter()
        )
        if annealing_remaining > 0.05 and small_screening_instance:
            annealing_deadline = min(
                float(slice_deadline),
                time.perf_counter()
                + (
                    annealing_remaining
                    if len(inst.activities) > 200
                    else min(0.12, annealing_remaining * 0.70)
                ),
            )
            annealed, annealing_status, annealing_telemetry = (
                _anneal_fixed_time_rooms(
                    inst,
                    room_candidate,
                    deadline=float(annealing_deadline),
                    seed=int(seed) + 104_729 * (int(elite_index) + 1),
                )
            )
            annealed_score = int(
                score_itc2007_instance_schedule(inst, annealed).total
            )
            incumbent_room_score = int(
                score_itc2007_instance_schedule(inst, room_candidate).total
            )
            if annealed_score < incumbent_room_score:
                room_candidate = annealed
            oracle_status = f"room_annealing:{annealing_status}"

        candidate_score = int(
            score_itc2007_instance_schedule(inst, room_candidate).total
        )
        candidate_errors = list(validation_fn(inst, room_candidate))
        valid = not candidate_errors
        screen_trace.append(
            {
                "elite_index": int(elite_index),
                "start_index": int(elite_start_index),
                "projected_score": int(projected_score),
                "official_score": int(candidate_score),
                "valid": bool(valid),
                "status": str(coordinate_status),
                "annealing_status": str(annealing_status),
                "annealing": dict(annealing_telemetry),
            }
        )
        if not valid:
            lift_status = "invalid_lift"
            continue
        screened_candidates.append(
            (
                int(candidate_score),
                int(projected_score),
                int(elite_start_index),
                room_candidate,
            )
        )
        if candidate_score < final_score:
            best_schedule = room_candidate
            final_score = int(candidate_score)
            selected_start_index = int(elite_start_index)

    if screened_candidates:
        (
            screened_best_score,
            _screened_projected_score,
            screened_best_start_index,
            screened_best_schedule,
        ) = min(
            screened_candidates,
            key=lambda item: (int(item[0]), int(item[1]), int(item[2])),
        )
        remaining = max(0.0, float(work_deadline) - time.perf_counter())
        if not small_screening_instance and remaining > 0.05:
            polished, polishing_telemetry = _polish_large_fixed_time_rooms(
                inst,
                screened_best_schedule,
                deadline=float(work_deadline),
                seed=int(seed),
                validator=validation_fn,
                max_cycles=3,
            )
            polished_errors = list(validation_fn(inst, polished))
            polished_score = int(
                score_itc2007_instance_schedule(inst, polished).total
            )
            if not polished_errors and polished_score < final_score:
                best_schedule = polished
                final_score = int(polished_score)
                selected_start_index = int(screened_best_start_index)
            screen_trace.append(
                {
                    "phase": "selected_elite_room_polish",
                    "start_index": int(screened_best_start_index),
                    "official_score": int(polished_score),
                    "valid": not polished_errors,
                    "polishing": dict(polishing_telemetry),
                }
            )
            oracle_status = "selected_room_polish"
        elif remaining > 0.10 and (
            small_room_cp_budget_seconds is None
            or float(small_room_cp_budget_seconds) > 0.0
        ):
            room_cp_deadline = float(work_deadline)
            if small_room_cp_budget_seconds is not None:
                room_cp_deadline = min(
                    room_cp_deadline,
                    time.perf_counter()
                    + max(0.0, float(small_room_cp_budget_seconds)),
                )
            candidate, room_cp_status = _exact_fixed_time_room_lift(
                inst,
                screened_best_schedule,
                deadline=float(room_cp_deadline),
                seed=int(seed) + int(screened_best_start_index),
            )
            if candidate is not None and time.perf_counter() < float(deadline):
                candidate_errors = list(validation_fn(inst, candidate))
                candidate_score = int(
                    score_itc2007_instance_schedule(inst, candidate).total
                )
                if not candidate_errors and candidate_score < final_score:
                    best_schedule = candidate
                    final_score = int(candidate_score)
                    selected_start_index = int(screened_best_start_index)

    room_screening = {
        "elites_available": int(len(ordered_elites)),
        "elites_admitted": int(screen_limit),
        "elites_screened": int(len(screen_trace)),
        "valid_candidates": int(len(screened_candidates)),
        "screen_budget_seconds": float(screen_budget),
        "best_screened_score": (
            None
            if not screened_candidates
            else int(min(item[0] for item in screened_candidates))
        ),
        "trace": screen_trace,
        "search_policy": {
            "requested_candidate_batch_size": int(candidate_batch_size),
            "effective_candidate_batch_size": int(
                effective_candidate_batch_size
            ),
            "dense_lossless_policy": bool(dense_lossless_policy),
            "adapt_dense_default_batch": bool(adapt_dense_default_batch),
            "trajectory_iteration_checkpoints": {
                str(row["trajectory_mode"]): row["iteration_limit"]
                for row in start_telemetry
            },
        },
    }

    finished = time.perf_counter()
    status = "improved" if final_score < initial_score else "no_improvement"
    return ProjectedTimeSearchResult(
        schedule=best_schedule,
        status=status,
        initial_score=int(initial_score),
        final_score=int(final_score),
        initial_projected_score=int(initial_projected),
        final_projected_score=int(best_projected),
        projected_lower_bound=int(base_state.projected_lower_bound),
        elapsed_seconds=float(finished - started),
        iterations=int(iterations),
        candidates_evaluated=int(candidates_evaluated),
        accepted_moves=int(accepted_moves),
        accepted_by_family={
            str(key): int(value) for key, value in sorted(accepted_by_family.items())
        },
        lift_status=str(lift_status),
        oracle_status=str(oracle_status),
        room_cp_status=str(room_cp_status),
        trace=trace,
        starts_requested=int(starts_requested),
        starts_generated=int(len(starts)),
        starts_completed=int(starts_completed),
        selected_start_index=int(selected_start_index),
        start_telemetry=sorted(
            start_telemetry, key=lambda row: int(row["start_index"])
        ),
        room_screening=room_screening,
        deadline_exhausted=bool(finished >= float(deadline)),
        deadline_overrun_seconds=max(0.0, float(finished) - float(deadline)),
    )


__all__ = [
    "ITC2007FixedTimeRoomCPResult",
    "ProjectedTimeSearchResult",
    "itc2007_fixed_time_room_cp_eligibility",
    "optimize_itc2007_fixed_time_rooms_cp",
    "optimize_projected_times",
    "projected_time_search_eligibility",
]
