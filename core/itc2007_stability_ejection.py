from __future__ import annotations

import copy
import time
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from ortools.sat.python import cp_model

from benchmarks.itc2007 import (
    ITC2007Score,
    canonicalize_itc2007_schedule,
    score_itc2007_instance_schedule,
)
from core.projected_time_search import itc2007_fixed_time_room_cp_eligibility
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]


@dataclass(frozen=True)
class StabilityEjectionChange:
    activity_id: int
    course_code: str
    from_period: int
    to_period: int
    from_room: int
    to_room: int

    @property
    def time_changed(self) -> bool:
        return int(self.from_period) != int(self.to_period)

    @property
    def room_changed(self) -> bool:
        return int(self.from_room) != int(self.to_room)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "time_changed": self.time_changed,
            "room_changed": self.room_changed,
        }


@dataclass
class StabilityEjectionTelemetry:
    seed: int
    fragmented_courses: list[dict[str, Any]] = field(default_factory=list)
    targets_considered: int = 0
    targets_attempted: int = 0
    frontiers_built: int = 0
    models_solved: int = 0
    validation_calls: int = 0
    independent_rescores: int = 0
    accepted_candidates: int = 0
    attempts: list[dict[str, Any]] = field(default_factory=list)
    best_trajectory: list[dict[str, Any]] = field(default_factory=list)
    timing: dict[str, float | int | bool | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StabilityEjectionResult:
    status: str
    schedule: Schedule
    improved: bool
    initial_score: ITC2007Score | None
    final_score: ITC2007Score | None
    telemetry: StabilityEjectionTelemetry
    validation_errors: tuple[str, ...] = ()
    eligibility_reasons: tuple[str, ...] = ()
    deadline_exhausted: bool = False
    deadline_overrun_seconds: float = 0.0
    error: str | None = None

    @property
    def best_schedule(self) -> Schedule:
        return self.schedule

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
            "improvement": (
                0
                if self.initial_score is None or self.final_score is None
                else int(self.initial_score.total - self.final_score.total)
            ),
            "telemetry": self.telemetry.to_dict(),
            "validation_errors": list(self.validation_errors),
            "eligibility_reasons": list(self.eligibility_reasons),
            "deadline_exhausted": bool(self.deadline_exhausted),
            "deadline_overrun_seconds": float(self.deadline_overrun_seconds),
            "error": self.error,
        }


@dataclass(frozen=True)
class _Target:
    course_code: str
    primary_room: int
    support: tuple[int, ...]
    minority_activities: tuple[int, ...]


@dataclass(frozen=True)
class _Frontier:
    target: _Target
    courses: tuple[str, ...]
    activities: tuple[int, ...]
    direct_room_blockers: tuple[str, ...]
    conflict_courses: tuple[str, ...]
    room_displacement_courses: tuple[str, ...]


@dataclass
class _ModelResult:
    status: str
    schedule: Schedule | None
    model_score: int | None
    solve_elapsed_seconds: float
    solve_deadline: float
    changes: tuple[StabilityEjectionChange, ...] = ()


class _AttemptDeadline(RuntimeError):
    pass


def _copy_schedule(schedule: Mapping[int, Mapping[str, Any]]) -> Schedule:
    return {
        int(activity_id): copy.deepcopy(dict(row))
        for activity_id, row in schedule.items()
    }


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


class _State:
    def __init__(self, inst: Instance, schedule: Schedule) -> None:
        self.inst = inst
        self.schedule = schedule
        self.activity_ids = tuple(sorted(int(value) for value in inst.activities))
        self.days = tuple(str(value) for value in inst.days)
        self.day_index = {day: index for index, day in enumerate(self.days)}
        self.slots_per_day = int(inst.slots_per_day)
        self.period_count = len(self.days) * self.slots_per_day
        self.room_ids = tuple(sorted(int(value) for value in inst.rooms))
        self.room_rank = {
            int(room_id): index for index, room_id in enumerate(self.room_ids)
        }
        self.course_code = {
            activity_id: str(
                inst.courses[int(inst.activities[activity_id].course_id)].code
            )
            for activity_id in self.activity_ids
        }
        self.activities_by_course: dict[str, tuple[int, ...]] = {}
        grouped: dict[str, list[int]] = defaultdict(list)
        for activity_id, code in self.course_code.items():
            grouped[code].append(int(activity_id))
        self.activities_by_course = {
            code: tuple(sorted(values)) for code, values in sorted(grouped.items())
        }
        self.base_period = {
            activity_id: self.day_index[str(schedule[activity_id]["day"])]
            * self.slots_per_day
            + int(schedule[activity_id]["slot"])
            for activity_id in self.activity_ids
        }
        self.base_room = {
            activity_id: int(schedule[activity_id]["room_id"])
            for activity_id in self.activity_ids
        }
        self.teacher_by_course = {
            code: int(inst.activities[activity_ids[0]].prof_id)
            for code, activity_ids in self.activities_by_course.items()
        }

        metadata = dict(inst.sla_targets["itc2007"])
        self.students = {
            str(key): int(value)
            for key, value in dict(metadata["course_students"]).items()
        }
        self.minimum_days = {
            str(key): int(value)
            for key, value in dict(metadata["minimum_working_days"]).items()
        }
        self.curricula = {
            str(key): tuple(str(code) for code in values)
            for key, values in dict(metadata["curricula"]).items()
        }
        self.curricula_by_course: dict[str, set[str]] = defaultdict(set)
        for curriculum, members in self.curricula.items():
            for code in members:
                self.curricula_by_course[code].add(curriculum)
        self.conflict_neighbors = self._build_conflict_neighbors()
        self.support_by_course = {
            code: tuple(
                sorted({self.base_room[activity_id] for activity_id in activity_ids})
            )
            for code, activity_ids in self.activities_by_course.items()
        }
        self.occupant_by_period_room = {
            (self.base_period[activity_id], self.base_room[activity_id]): activity_id
            for activity_id in self.activity_ids
        }
        self.room_load = Counter(self.base_room.values())
        self.forbidden = {
            activity_id: {
                self.day_index[str(day)] * self.slots_per_day + int(slot)
                for day, slot in (
                    getattr(inst, "activity_unavailability", {}) or {}
                ).get(activity_id, set())
            }
            for activity_id in self.activity_ids
        }

    def _build_conflict_neighbors(self) -> dict[str, tuple[str, ...]]:
        output: dict[str, set[str]] = {
            code: set() for code in self.activities_by_course
        }
        codes = tuple(sorted(self.activities_by_course))
        for left_index, left in enumerate(codes):
            for right in codes[left_index + 1 :]:
                if (
                    self.teacher_by_course[left] == self.teacher_by_course[right]
                    or self.curricula_by_course[left]
                    & self.curricula_by_course[right]
                ):
                    output[left].add(right)
                    output[right].add(left)
        return {code: tuple(sorted(values)) for code, values in output.items()}

    def _target_local_gain(self, target: _Target) -> int:
        """Exact target-course gain before any blocker displacement.

        A room-stability consolidation can silently worsen capacity when the
        majority room is too small.  Keeping that exact local delta next to
        the structural ranking prevents cheap but objective-incompatible
        orientations from consuming the first bounded attempt.
        """

        activity_ids = self.activities_by_course[target.course_code]
        current_capacity = sum(
            max(
                0,
                int(self.students[target.course_code])
                - int(self.inst.rooms[self.base_room[activity_id]].capacity),
            )
            for activity_id in activity_ids
        )
        target_capacity = len(activity_ids) * max(
            0,
            int(self.students[target.course_code])
            - int(self.inst.rooms[target.primary_room].capacity),
        )
        stability_gain = max(0, len(target.support) - 1)
        return int(stability_gain + current_capacity - target_capacity)

    def _target_room_pressure(self, target: _Target) -> int:
        """Return the unavoidable number of target-room displacements."""

        return max(
            0,
            int(self.room_load[target.primary_room])
            + len(target.minority_activities)
            - int(self.period_count),
        )

    def _target_conflict_room_affinity(self, target: _Target) -> int:
        """Measure period-exchange support already colored into the room.

        Conflicting courses using the target room form useful alternating
        period chains: they cannot coincide with the target course, but can
        exchange periods while retaining their incumbent room colors.
        """

        return sum(
            len(self.activities_by_course[code])
            for code in self.conflict_neighbors[target.course_code]
            if target.primary_room in self.support_by_course[code]
        )

    def _target_orientation_priority(self, target: _Target) -> tuple[Any, ...]:
        """Choose the cheapest safe incumbent-room orientation per course."""

        local_gain = self._target_local_gain(target)
        return (
            int(local_gain <= 0),
            self._target_room_pressure(target),
            len(target.minority_activities),
            -self._target_conflict_room_affinity(target),
            -int(local_gain),
            len(target.support),
            target.course_code,
            int(target.primary_room),
        )

    def _target_priority(self, target: _Target) -> tuple[Any, ...]:
        """Rank oriented courses by safe fragmentation-reduction leverage.

        Orientation selection and cross-course selection need opposite views
        of the off-primary lecture count.  Within one course, fewer moved
        lectures is the cheaper consolidation orientation.  Across already
        oriented courses, a larger fragmented minority exposes more of the
        incumbent room coloring to the atomic frontier and is preferred when
        local gain and unavoidable room pressure are otherwise equivalent.
        Keeping those decisions separate avoids repeatedly spending the first
        bounded attempt on an almost-consolidated course that can block a more
        connected course-color exchange.
        """

        local_gain = self._target_local_gain(target)
        return (
            int(local_gain <= 0),
            self._target_room_pressure(target),
            -len(target.minority_activities),
            -self._target_conflict_room_affinity(target),
            -int(local_gain),
            len(target.support),
            target.course_code,
            int(target.primary_room),
        )

    def fragmented_targets(self) -> tuple[_Target, ...]:
        targets: list[_Target] = []
        for code, activity_ids in self.activities_by_course.items():
            counts = Counter(self.base_room[activity_id] for activity_id in activity_ids)
            if len(counts) <= 1:
                continue
            support = tuple(sorted(int(value) for value in counts))
            # Every incumbent room color is a lossless consolidation
            # orientation.  Majority-only selection misses tie and
            # alternating-chain cases whose feasible target is the other
            # supported room.  Keep the best representation-derived
            # orientation per course so ``max_target_courses`` retains its
            # documented course-count meaning.
            orientations: list[_Target] = []
            for primary in support:
                minority = tuple(
                    activity_id
                    for activity_id in activity_ids
                    if self.base_room[activity_id] != int(primary)
                )
                orientations.append(
                    _Target(
                        course_code=code,
                        primary_room=int(primary),
                        support=support,
                        minority_activities=minority,
                    )
                )
            targets.append(
                min(orientations, key=self._target_orientation_priority)
            )
        targets.sort(key=self._target_priority)
        return tuple(targets)

    def _can_add_course(
        self,
        selected: set[str],
        code: str,
        *,
        max_courses: int,
        max_activities: int,
    ) -> bool:
        if code in selected:
            return False
        if len(selected) >= int(max_courses):
            return False
        activity_count = sum(
            len(self.activities_by_course[value]) for value in selected
        )
        return (
            activity_count + len(self.activities_by_course[code])
            <= int(max_activities)
        )

    def _room_displacement_candidates(self, code: str) -> tuple[str, ...]:
        candidates: Counter[str] = Counter()
        supports = self.support_by_course[code]
        for activity_id in self.activities_by_course[code]:
            for period in range(self.period_count):
                if period in self.forbidden[activity_id]:
                    continue
                for room_id in supports:
                    occupant = self.occupant_by_period_room.get((period, room_id))
                    if occupant is None:
                        continue
                    other = self.course_code[occupant]
                    if other != code:
                        candidates[other] += 1
        return tuple(
            sorted(candidates, key=lambda value: (-candidates[value], value))
        )

    def build_frontier(
        self,
        target: _Target,
        *,
        max_courses: int,
        max_activities: int,
        max_depth: int,
        deadline: float,
    ) -> _Frontier | None:
        if time.perf_counter() >= float(deadline):
            raise _AttemptDeadline
        selected = {target.course_code}
        direct_blockers: list[str] = []
        conflict_courses: list[str] = []
        displacement_courses: list[str] = []

        for activity_id in target.minority_activities:
            occupant = self.occupant_by_period_room.get(
                (self.base_period[activity_id], target.primary_room)
            )
            if occupant is None:
                continue
            code = self.course_code[occupant]
            if self._can_add_course(
                selected,
                code,
                max_courses=max_courses,
                max_activities=max_activities,
            ):
                selected.add(code)
                direct_blockers.append(code)

        # Direct room blockers are hard dependencies of this orientation.
        # Expand their conflict neighborhoods before the target's broader
        # curriculum/teacher neighborhood so a tight course/activity cap does
        # not evict the transitive alternating-chain blockers.
        queue: deque[tuple[str, int]] = deque(
            (code, 0)
            for code in (*tuple(sorted(direct_blockers)), target.course_code)
        )
        expanded: set[tuple[str, int]] = set()
        while queue:
            if time.perf_counter() >= float(deadline):
                raise _AttemptDeadline
            source, depth = queue.popleft()
            if (source, depth) in expanded or depth >= int(max_depth):
                continue
            expanded.add((source, depth))
            for code in self.conflict_neighbors[source]:
                if self._can_add_course(
                    selected,
                    code,
                    max_courses=max_courses,
                    max_activities=max_activities,
                ):
                    selected.add(code)
                    conflict_courses.append(code)
                    queue.append((code, depth + 1))

        # Room-displacement edges are intentionally considered after exact
        # conflict edges.  This keeps the bounded frontier focused while still
        # admitting occupants that an ejection chain may need to displace.
        room_sources = tuple(sorted(selected))
        for source in room_sources:
            if time.perf_counter() >= float(deadline):
                raise _AttemptDeadline
            for code in self._room_displacement_candidates(source):
                if self._can_add_course(
                    selected,
                    code,
                    max_courses=max_courses,
                    max_activities=max_activities,
                ):
                    selected.add(code)
                    displacement_courses.append(code)

        activities = tuple(
            sorted(
                activity_id
                for code in selected
                for activity_id in self.activities_by_course[code]
            )
        )
        if (
            target.course_code not in selected
            or not activities
            or len(selected) > int(max_courses)
            or len(activities) > int(max_activities)
        ):
            return None
        return _Frontier(
            target=target,
            courses=tuple(sorted(selected)),
            activities=activities,
            direct_room_blockers=tuple(sorted(set(direct_blockers))),
            conflict_courses=tuple(sorted(set(conflict_courses))),
            room_displacement_courses=tuple(
                sorted(set(displacement_courses))
            ),
        )

    def _course_mwd_term(self, code: str) -> int:
        days = {
            self.base_period[activity_id] // self.slots_per_day
            for activity_id in self.activities_by_course[code]
        }
        return 5 * max(0, int(self.minimum_days[code]) - len(days))

    def _course_stability_term(self, code: str) -> int:
        return max(0, len(self.support_by_course[code]) - 1)

    def _curriculum_compactness_term(self, curriculum: str) -> int:
        periods = [
            self.base_period[activity_id]
            for code in self.curricula[curriculum]
            for activity_id in self.activities_by_course[code]
        ]
        occupied = set(periods)
        isolated = 0
        for period in periods:
            slot = period % self.slots_per_day
            adjacent = (
                slot > 0 and period - 1 in occupied
            ) or (
                slot + 1 < self.slots_per_day and period + 1 in occupied
            )
            isolated += int(not adjacent)
        return 2 * isolated

    def solve_frontier(
        self,
        frontier: _Frontier,
        *,
        incumbent_score: ITC2007Score,
        deadline: float,
        seed: int,
        max_moved_activities: int,
    ) -> _ModelResult:
        build_started = time.perf_counter()

        def check() -> None:
            if time.perf_counter() >= float(deadline):
                raise _AttemptDeadline

        model = cp_model.CpModel()
        frontier_ids = set(frontier.activities)
        frontier_courses = set(frontier.courses)

        time_vars: dict[tuple[int, int], cp_model.IntVar] = {}
        period_vars: dict[int, cp_model.IntVar] = {}
        room_vars: dict[tuple[int, int], cp_model.IntVar] = {}
        room_value_vars: dict[int, cp_model.IntVar] = {}
        room_domains: dict[int, tuple[int, ...]] = {}
        time_changed: dict[int, cp_model.IntVar] = {}
        room_changed: dict[int, cp_model.IntVar] = {}
        changed: dict[int, cp_model.IntVar] = {}

        for activity_id in frontier.activities:
            check()
            allowed_periods = tuple(
                period
                for period in range(self.period_count)
                if period not in self.forbidden[activity_id]
            )
            if not allowed_periods:
                return _ModelResult(
                    status="empty_time_domain",
                    schedule=None,
                    model_score=None,
                    solve_elapsed_seconds=0.0,
                    solve_deadline=float(deadline),
                )
            literals = []
            for period in allowed_periods:
                literal = model.new_bool_var(f"t_a{activity_id}_p{period}")
                time_vars[(activity_id, period)] = literal
                literals.append(literal)
                model.add_hint(
                    literal,
                    int(period == self.base_period[activity_id]),
                )
            model.add_exactly_one(literals)
            period_value = model.new_int_var(
                0,
                self.period_count - 1,
                f"period_a{activity_id}",
            )
            model.add(
                period_value
                == sum(
                    period * time_vars[(activity_id, period)]
                    for period in allowed_periods
                )
            )
            period_vars[activity_id] = period_value

            code = self.course_code[activity_id]
            if code == frontier.target.course_code:
                rooms = (frontier.target.primary_room,)
            else:
                rooms = self.support_by_course[code]
            room_domains[activity_id] = rooms
            room_literals = []
            for room_id in rooms:
                literal = model.new_bool_var(f"r_a{activity_id}_r{room_id}")
                room_vars[(activity_id, room_id)] = literal
                room_literals.append(literal)
                model.add_hint(
                    literal,
                    int(room_id == self.base_room[activity_id]),
                )
            model.add_exactly_one(room_literals)
            room_value = model.new_int_var(
                0,
                len(self.room_ids) - 1,
                f"room_rank_a{activity_id}",
            )
            model.add(
                room_value
                == sum(
                    self.room_rank[room_id]
                    * room_vars[(activity_id, room_id)]
                    for room_id in rooms
                )
            )
            room_value_vars[activity_id] = room_value

            t_changed = model.new_bool_var(f"time_changed_a{activity_id}")
            model.add(
                t_changed
                + time_vars[(activity_id, self.base_period[activity_id])]
                == 1
            )
            time_changed[activity_id] = t_changed
            r_changed = model.new_bool_var(f"room_changed_a{activity_id}")
            if self.base_room[activity_id] in rooms:
                model.add(
                    r_changed
                    + room_vars[(activity_id, self.base_room[activity_id])]
                    == 1
                )
            else:
                model.add(r_changed == 1)
            room_changed[activity_id] = r_changed
            any_changed = model.new_bool_var(f"changed_a{activity_id}")
            model.add_max_equality(any_changed, [t_changed, r_changed])
            changed[activity_id] = any_changed

        model.add(sum(changed.values()) <= int(max_moved_activities))

        # Strict start-order symmetry is safe for untouched ITC-2007 imports:
        # lecture identifiers within a course are artificial and exchangeable.
        placement_scale = len(self.room_ids)
        for code in frontier.courses:
            activity_ids = self.activities_by_course[code]
            for left, right in zip(activity_ids, activity_ids[1:]):
                model.add(
                    period_vars[left] * placement_scale + room_value_vars[left]
                    <= period_vars[right] * placement_scale + room_value_vars[right]
                )

        # Teacher, curriculum, and same-course time conflicts.  Outside
        # placements are constants; a nonzero outside occupancy closes the
        # corresponding frontier period exactly.
        resource_members: dict[tuple[str, str], set[int]] = defaultdict(set)
        for activity_id in self.activity_ids:
            code = self.course_code[activity_id]
            resource_members[("course", code)].add(activity_id)
            resource_members[("teacher", str(self.teacher_by_course[code]))].add(
                activity_id
            )
            for curriculum in self.curricula_by_course[code]:
                resource_members[("curriculum", curriculum)].add(activity_id)
        for members in resource_members.values():
            movable = sorted(frontier_ids & members)
            if not movable:
                continue
            fixed = members - frontier_ids
            fixed_periods = Counter(self.base_period[value] for value in fixed)
            for period in range(self.period_count):
                literals = [
                    time_vars[(activity_id, period)]
                    for activity_id in movable
                    if (activity_id, period) in time_vars
                ]
                if literals:
                    model.add(
                        int(fixed_periods[period]) + sum(literals) <= 1
                    )

        # Couple room and time assignments, then enforce exact occupancy with
        # the outside frontier held fixed.
        joint_vars: dict[tuple[int, int, int], cp_model.IntVar] = {}
        fixed_room_period = Counter(
            (self.base_period[activity_id], self.base_room[activity_id])
            for activity_id in self.activity_ids
            if activity_id not in frontier_ids
        )
        by_period_room: dict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)
        for activity_id in frontier.activities:
            check()
            for room_id in room_domains[activity_id]:
                for period in range(self.period_count):
                    time_literal = time_vars.get((activity_id, period))
                    if time_literal is None:
                        continue
                    joint = model.new_bool_var(
                        f"joint_a{activity_id}_p{period}_r{room_id}"
                    )
                    model.add(joint <= time_literal)
                    model.add(joint <= room_vars[(activity_id, room_id)])
                    model.add(
                        joint
                        >= time_literal + room_vars[(activity_id, room_id)] - 1
                    )
                    joint_vars[(activity_id, period, room_id)] = joint
                    by_period_room[(period, room_id)].append(joint)
        for key, literals in by_period_room.items():
            model.add(int(fixed_room_period[key]) + sum(literals) <= 1)

        capacity_terms: list[Any] = []
        for activity_id in self.activity_ids:
            code = self.course_code[activity_id]
            if activity_id not in frontier_ids:
                capacity_terms.append(
                    max(
                        0,
                        int(self.students[code])
                        - int(
                            self.inst.rooms[self.base_room[activity_id]].capacity
                        ),
                    )
                )
                continue
            for room_id in room_domains[activity_id]:
                overflow = max(
                    0,
                    int(self.students[code])
                    - int(self.inst.rooms[room_id].capacity),
                )
                if not overflow:
                    continue
                capacity_terms.extend(
                    overflow
                    * joint_vars[(activity_id, period, room_id)]
                    for period in range(self.period_count)
                    if (activity_id, period, room_id) in joint_vars
                )

        mwd_terms: list[Any] = []
        stability_terms: list[Any] = []
        for code, activity_ids in self.activities_by_course.items():
            if code not in frontier_courses:
                mwd_terms.append(self._course_mwd_term(code))
                stability_terms.append(self._course_stability_term(code))
                continue
            day_used = []
            for day_index in range(len(self.days)):
                literal = model.new_bool_var(f"day_used_{code}_{day_index}")
                day_literals = [
                    time_vars[(activity_id, period)]
                    for activity_id in activity_ids
                    for period in range(
                        day_index * self.slots_per_day,
                        (day_index + 1) * self.slots_per_day,
                    )
                    if (activity_id, period) in time_vars
                ]
                if day_literals:
                    model.add_max_equality(literal, day_literals)
                else:
                    model.add(literal == 0)
                day_used.append(literal)
            deficit = model.new_int_var(
                0,
                int(self.minimum_days[code]),
                f"mwd_deficit_{code}",
            )
            model.add_max_equality(
                deficit,
                [0, int(self.minimum_days[code]) - sum(day_used)],
            )
            mwd_terms.append(5 * deficit)

            used_rooms = []
            support = (
                (frontier.target.primary_room,)
                if code == frontier.target.course_code
                else self.support_by_course[code]
            )
            for room_id in support:
                used = model.new_bool_var(f"room_used_{code}_{room_id}")
                model.add_max_equality(
                    used,
                    [room_vars[(activity_id, room_id)] for activity_id in activity_ids],
                )
                used_rooms.append(used)
            stability_terms.append(sum(used_rooms) - 1)

        compactness_terms: list[Any] = []
        for curriculum, member_codes in self.curricula.items():
            if not frontier_courses.intersection(member_codes):
                compactness_terms.append(
                    self._curriculum_compactness_term(curriculum)
                )
                continue
            member_activities = {
                activity_id
                for code in member_codes
                for activity_id in self.activities_by_course[code]
            }
            fixed_periods = Counter(
                self.base_period[activity_id]
                for activity_id in member_activities - frontier_ids
            )
            movable = sorted(member_activities & frontier_ids)
            occupied: list[cp_model.IntVar] = []
            for period in range(self.period_count):
                literal = model.new_bool_var(f"occupied_{curriculum}_{period}")
                period_literals = [
                    time_vars[(activity_id, period)]
                    for activity_id in movable
                    if (activity_id, period) in time_vars
                ]
                model.add(
                    literal == int(fixed_periods[period]) + sum(period_literals)
                )
                occupied.append(literal)
            for period in range(self.period_count):
                slot = period % self.slots_per_day
                neighbors = []
                if slot > 0:
                    neighbors.append(occupied[period - 1])
                if slot + 1 < self.slots_per_day:
                    neighbors.append(occupied[period + 1])
                isolated = model.new_bool_var(
                    f"isolated_{curriculum}_{period}"
                )
                model.add(isolated <= occupied[period])
                for neighbor in neighbors:
                    model.add(isolated + neighbor <= 1)
                model.add(isolated >= occupied[period] - sum(neighbors))
                compactness_terms.append(2 * isolated)

        total_score = model.new_int_var(0, 1_000_000_000, "official_total")
        model.add(
            total_score
            == sum(capacity_terms)
            + sum(mwd_terms)
            + sum(compactness_terms)
            + sum(stability_terms)
        )
        model.add(total_score <= int(incumbent_score.total) - 1)

        move_scale = (len(frontier.activities) + 1) ** 2
        model.minimize(
            total_score * move_scale
            + sum(time_changed.values()) * (len(frontier.activities) + 1)
            + sum(room_changed.values())
        )

        build_finished = time.perf_counter()
        if build_finished >= float(deadline):
            raise _AttemptDeadline
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(
            0.0, float(deadline) - build_finished
        )
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = int(seed)
        solver.parameters.log_search_progress = False
        solve_started = time.perf_counter()
        raw_status = int(solver.solve(model))
        solve_finished = time.perf_counter()
        status = {
            int(cp_model.OPTIMAL): "optimal",
            int(cp_model.FEASIBLE): "feasible",
            int(cp_model.INFEASIBLE): "infeasible",
            int(cp_model.MODEL_INVALID): "model_invalid",
            int(cp_model.UNKNOWN): "unknown",
        }.get(raw_status, f"status_{raw_status}")
        if solve_finished >= float(deadline):
            return _ModelResult(
                status="deadline_exhausted",
                schedule=None,
                model_score=None,
                solve_elapsed_seconds=float(solve_finished - solve_started),
                solve_deadline=float(deadline),
            )
        if raw_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return _ModelResult(
                status=status,
                schedule=None,
                model_score=None,
                solve_elapsed_seconds=float(solve_finished - solve_started),
                solve_deadline=float(deadline),
            )

        candidate = _copy_schedule(self.schedule)
        changes: list[StabilityEjectionChange] = []
        for activity_id in frontier.activities:
            periods = [
                period
                for period in range(self.period_count)
                if (activity_id, period) in time_vars
                and solver.boolean_value(time_vars[(activity_id, period)])
            ]
            rooms = [
                room_id
                for room_id in room_domains[activity_id]
                if solver.boolean_value(room_vars[(activity_id, room_id)])
            ]
            if len(periods) != 1 or len(rooms) != 1:
                return _ModelResult(
                    status="invalid_cp_assignment",
                    schedule=None,
                    model_score=None,
                    solve_elapsed_seconds=float(solve_finished - solve_started),
                    solve_deadline=float(deadline),
                )
            period = int(periods[0])
            room_id = int(rooms[0])
            candidate[activity_id]["day"] = self.days[
                period // self.slots_per_day
            ]
            candidate[activity_id]["slot"] = period % self.slots_per_day
            candidate[activity_id]["room_id"] = room_id
            if (
                period != self.base_period[activity_id]
                or room_id != self.base_room[activity_id]
            ):
                changes.append(
                    StabilityEjectionChange(
                        activity_id=activity_id,
                        course_code=self.course_code[activity_id],
                        from_period=self.base_period[activity_id],
                        to_period=period,
                        from_room=self.base_room[activity_id],
                        to_room=room_id,
                    )
                )
        candidate = canonicalize_itc2007_schedule(self.inst, candidate)
        return _ModelResult(
            status=status,
            schedule=candidate,
            model_score=int(solver.value(total_score)),
            solve_elapsed_seconds=float(solve_finished - solve_started),
            solve_deadline=float(deadline),
            changes=tuple(changes),
        )


def optimize_itc2007_stability_ejection(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float,
    seed: int = 0,
    max_target_courses: int = 4,
    max_frontier_courses: int = 12,
    max_frontier_activities: int = 72,
    max_frontier_depth: int = 1,
    max_moved_activities: int = 12,
    max_solve_seconds: float = 0.65,
    max_seconds_per_target: float = 0.30,
    completion_reserve_seconds: float = 0.03,
    validator: Validator | None = None,
) -> StabilityEjectionResult:
    """Try a bounded, support-preserving ITC-2007 stability ejection.

    Ejection chains, lecture exchanges, room-stability moves, and minimum-day
    repair are established timetabling neighborhoods.  This implementation
    therefore makes no claim to a new neighborhood family.  Its deliberately
    narrow engineering contribution is the deterministic blocker frontier,
    incumbent-support preservation, exact official-score bound, and atomic
    validate-and-rescore acceptance boundary under one absolute deadline.
    """

    started = time.perf_counter()
    original = _copy_schedule(schedule) if isinstance(schedule, Mapping) else {}
    telemetry = StabilityEjectionTelemetry(seed=int(seed))
    validation_fn = validator or _default_validator
    initial_score: ITC2007Score | None = None
    final_score: ITC2007Score | None = None
    selected: Schedule | None = None
    validation_errors: tuple[str, ...] = ()
    search_deadline = float(deadline)

    def finish(
        status: str,
        *,
        eligibility_reasons: Sequence[str] = (),
        errors: Sequence[str] = (),
        error: str | None = None,
    ) -> StabilityEjectionResult:
        improvement_ready = bool(
            selected is not None
            and initial_score is not None
            and final_score is not None
            and int(final_score.total) < int(initial_score.total)
        )
        returned_schedule = _copy_schedule(
            selected if improvement_ready and selected is not None else original
        )
        finished = time.perf_counter()
        overrun = max(0.0, finished - float(deadline))
        improved = bool(improvement_ready and overrun == 0.0)
        if improvement_ready and not improved:
            # Copying a large accepted candidate is part of the public phase.
            # If that crosses the deadline, discard it and measure again after
            # the incumbent-safe copy has completed.
            returned_schedule = _copy_schedule(original)
            finished = time.perf_counter()
            overrun = max(0.0, finished - float(deadline))
        telemetry.timing = {
            "started_at": float(started),
            "absolute_deadline": float(deadline),
            "search_deadline": float(search_deadline),
            "requested_budget_seconds": max(0.0, float(deadline) - started),
            "completion_reserve_seconds": max(
                0.0, float(deadline) - float(search_deadline)
            ),
            "elapsed_seconds": float(finished - started),
            "deadline_remaining_seconds": max(0.0, float(deadline) - finished),
            "deadline_overrun_seconds": float(overrun),
        }
        return StabilityEjectionResult(
            status=str(
                status
                if improved or status != "improved"
                else "deadline_exhausted"
            ),
            schedule=returned_schedule,
            improved=improved,
            initial_score=initial_score,
            final_score=final_score if improved else initial_score,
            telemetry=telemetry,
            validation_errors=tuple(str(value) for value in errors)[:20],
            eligibility_reasons=tuple(str(value) for value in eligibility_reasons),
            deadline_exhausted=bool(finished >= float(deadline)),
            deadline_overrun_seconds=float(overrun),
            error=error,
        )

    try:
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        bounds = {
            "max_target_courses": int(max_target_courses),
            "max_frontier_courses": int(max_frontier_courses),
            "max_frontier_activities": int(max_frontier_activities),
            "max_frontier_depth": int(max_frontier_depth),
            "max_moved_activities": int(max_moved_activities),
        }
        if (
            any(value < 1 for key, value in bounds.items() if key != "max_frontier_depth")
            or bounds["max_frontier_depth"] < 0
            or float(max_solve_seconds) <= 0.0
            or float(max_seconds_per_target) <= 0.0
            or float(completion_reserve_seconds) < 0.0
        ):
            return finish(
                "ineligible",
                eligibility_reasons=("search_bounds_must_be_positive",),
            )
        eligible, reasons = itc2007_fixed_time_room_cp_eligibility(inst, original)
        if not eligible:
            return finish("ineligible", eligibility_reasons=reasons)

        telemetry.validation_calls += 1
        validation_errors = tuple(
            str(value) for value in validation_fn(inst, original)
        )
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        if validation_errors:
            return finish("invalid_incumbent", errors=validation_errors)

        initial_score = score_itc2007_instance_schedule(inst, original)
        if int(initial_score.total) <= 0:
            return finish("no_improvement")

        working = canonicalize_itc2007_schedule(inst, original)
        state = _State(inst, working)
        targets = state.fragmented_targets()
        telemetry.fragmented_courses = [
            {
                "course_code": target.course_code,
                "primary_room": target.primary_room,
                "room_support": list(target.support),
                "minority_activities": list(target.minority_activities),
            }
            for target in targets
        ]
        if not targets:
            return finish("no_fragmented_courses")

        now = time.perf_counter()
        available = max(0.0, float(deadline) - now)
        reserve = min(
            max(0.0, float(completion_reserve_seconds)),
            max(0.0, available * 0.25),
        )
        search_deadline = min(
            float(deadline) - reserve,
            now + max(0.0, float(max_solve_seconds)),
        )
        if time.perf_counter() >= search_deadline:
            return finish("deadline_exhausted")

        for target_index, target in enumerate(targets[: int(max_target_courses)]):
            telemetry.targets_considered += 1
            target_started = time.perf_counter()
            if target_started >= search_deadline:
                break
            target_deadline = min(
                search_deadline,
                target_started + float(max_seconds_per_target),
            )
            attempt: dict[str, Any] = {
                "target_index": int(target_index),
                "target_course": target.course_code,
                "primary_room": int(target.primary_room),
                "requested_deadline": float(target_deadline),
                "started_at": float(target_started),
                "accepted": False,
            }
            telemetry.attempts.append(attempt)
            telemetry.targets_attempted += 1
            try:
                frontier = state.build_frontier(
                    target,
                    max_courses=int(max_frontier_courses),
                    max_activities=int(max_frontier_activities),
                    max_depth=int(max_frontier_depth),
                    deadline=target_deadline,
                )
                if frontier is None:
                    attempt["status"] = "frontier_ineligible"
                    continue
                telemetry.frontiers_built += 1
                attempt.update(
                    {
                        "frontier_courses": list(frontier.courses),
                        "frontier_activity_count": len(frontier.activities),
                        "direct_room_blockers": list(
                            frontier.direct_room_blockers
                        ),
                        "conflict_courses": list(frontier.conflict_courses),
                        "room_displacement_courses": list(
                            frontier.room_displacement_courses
                        ),
                    }
                )
                model_result = state.solve_frontier(
                    frontier,
                    incumbent_score=initial_score,
                    deadline=target_deadline,
                    seed=int(seed) + target_index * 104_729,
                    max_moved_activities=int(max_moved_activities),
                )
                telemetry.models_solved += 1
                attempt.update(
                    {
                        "status": model_result.status,
                        "solve_deadline": float(model_result.solve_deadline),
                        "solve_elapsed_seconds": float(
                            model_result.solve_elapsed_seconds
                        ),
                        "model_score": model_result.model_score,
                    }
                )
                if model_result.schedule is None:
                    continue
                if time.perf_counter() >= float(target_deadline):
                    attempt["status"] = "deadline_exhausted"
                    continue

                # Canonical modeling is a symmetry reduction only.  Courses
                # outside the selected frontier are restored byte-for-byte to
                # the caller's incumbent before the independent boundary.
                frontier_ids = set(frontier.activities)
                for activity_id in state.activity_ids:
                    if activity_id not in frontier_ids:
                        model_result.schedule[activity_id] = copy.deepcopy(
                            original[activity_id]
                        )

                telemetry.validation_calls += 1
                candidate_errors = tuple(
                    str(value)
                    for value in validation_fn(inst, model_result.schedule)
                )
                if time.perf_counter() >= float(deadline):
                    return finish("deadline_exhausted")
                if candidate_errors:
                    attempt["status"] = "invalid_candidate"
                    attempt["validation_errors"] = list(candidate_errors[:10])
                    continue

                telemetry.independent_rescores += 1
                official = score_itc2007_instance_schedule(
                    inst, model_result.schedule
                )
                attempt["official_score"] = official.to_dict()
                attempt["score_parity"] = (
                    model_result.model_score == int(official.total)
                )
                if time.perf_counter() >= float(deadline):
                    return finish("deadline_exhausted")
                if not attempt["score_parity"]:
                    return finish(
                        "error",
                        error="model_official_score_disagreement",
                    )
                if int(official.total) >= int(initial_score.total):
                    attempt["status"] = "no_strict_improvement"
                    continue

                selected = model_result.schedule
                final_score = official
                telemetry.accepted_candidates = 1
                attempt["accepted"] = True
                attempt["status"] = "improved"
                attempt["finished_at"] = time.perf_counter()
                telemetry.best_trajectory = [
                    {
                        "atomic": True,
                        "target_course": target.course_code,
                        "primary_room": target.primary_room,
                        "frontier_courses": list(frontier.courses),
                        "changes": [
                            change.to_dict() for change in model_result.changes
                        ],
                        "initial_score": initial_score.to_dict(),
                        "final_score": final_score.to_dict(),
                        "independently_validated": True,
                        "independently_rescored": True,
                    }
                ]
                return finish("improved")
            except _AttemptDeadline:
                attempt["status"] = "deadline_exhausted"
            finally:
                attempt["finished_at"] = time.perf_counter()
                attempt["elapsed_seconds"] = float(
                    attempt["finished_at"] - target_started
                )
                attempt["deadline_overrun_seconds"] = max(
                    0.0, attempt["finished_at"] - float(target_deadline)
                )

        return finish(
            "deadline_exhausted"
            if time.perf_counter() >= search_deadline
            else "no_improvement"
        )
    except Exception as exc:
        return finish("error", error=f"{type(exc).__name__}:{exc}")


__all__ = [
    "StabilityEjectionChange",
    "StabilityEjectionResult",
    "StabilityEjectionTelemetry",
    "optimize_itc2007_stability_ejection",
]
