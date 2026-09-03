from __future__ import annotations

import copy
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from benchmarks.itc2007 import ITC2007Score, score_itc2007_instance_schedule
from core.projected_time_search import projected_time_search_eligibility
from utils.domain import Instance
from utils.specs import validate_schedule_against_instance


Schedule = dict[int, dict[str, Any]]
Validator = Callable[[Instance, Mapping[int, Mapping[str, Any]]], Sequence[str]]
_STANDARD_WEIGHTS = {
    "room_capacity": 1,
    "minimum_working_days": 5,
    "curriculum_compactness": 2,
    "room_stability": 1,
}


@dataclass(frozen=True)
class CompoundMove:
    left_activity_id: int
    right_activity_id: int
    left_from_period: int
    right_from_period: int
    left_from_room: int
    right_from_room: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class CompoundSearchTelemetry:
    seed: int
    first_moves_checked: int = 0
    first_moves_generated: int = 0
    second_moves_checked: int = 0
    compounds_shortlisted: int = 0
    compounds_validated: int = 0
    independent_rescores: int = 0
    validation_calls: int = 0
    accepted_compounds: int = 0
    barrier_crossings: int = 0
    best_trajectory: list[dict[str, Any]] = field(default_factory=list)
    timing: dict[str, float | int | bool | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompoundSearchResult:
    status: str
    schedule: Schedule
    improved: bool
    initial_score: ITC2007Score | None
    final_score: ITC2007Score | None
    telemetry: CompoundSearchTelemetry
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


class _CompoundState:
    def __init__(self, inst: Instance, schedule: Schedule) -> None:
        self.inst = inst
        self.schedule = schedule
        self.activity_ids = tuple(sorted(int(value) for value in inst.activities))
        self.day_index = {str(day): index for index, day in enumerate(inst.days)}
        self.slots_per_day = int(inst.slots_per_day)
        self.period_count = len(inst.days) * self.slots_per_day
        self.base_period = tuple(
            self.day_index[str(schedule[activity_id]["day"])]
            * self.slots_per_day
            + int(schedule[activity_id]["slot"])
            for activity_id in self.activity_ids
        )
        self.base_room = tuple(
            int(schedule[activity_id]["room_id"])
            for activity_id in self.activity_ids
        )
        self.course_code = tuple(
            str(inst.courses[inst.activities[activity_id].course_id].code)
            for activity_id in self.activity_ids
        )
        self.teacher = tuple(
            int(inst.activities[activity_id].prof_id)
            for activity_id in self.activity_ids
        )

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
        for curriculum, codes in self.curricula.items():
            for code in codes:
                self.curricula_by_course[code].add(curriculum)
        self.indexes_by_course = {
            code: tuple(
                index
                for index, other_code in enumerate(self.course_code)
                if other_code == code
            )
            for code in sorted(set(self.course_code))
        }
        self.indexes_by_curriculum = {
            curriculum: tuple(
                index
                for index, code in enumerate(self.course_code)
                if code in set(codes)
            )
            for curriculum, codes in self.curricula.items()
        }
        self.room_capacity = {
            int(room_id): int(room.capacity)
            for room_id, room in inst.rooms.items()
        }
        self.conflicts: tuple[frozenset[int], ...] = self._build_conflicts()
        self.forbidden = tuple(
            frozenset(
                self.day_index[str(day)] * self.slots_per_day + int(slot)
                for day, slot in inst.activity_unavailability.get(activity_id, set())
            )
            for activity_id in self.activity_ids
        )
        self.base_capacity_by_index = tuple(
            self.capacity_contribution(index, self.base_room[index])
            for index in range(len(self.activity_ids))
        )
        self.base_course_terms = {
            code: self.course_terms(code, {}, {})
            for code in self.indexes_by_course
        }
        self.base_curriculum_terms = {
            curriculum: self.curriculum_term(curriculum, {})
            for curriculum in self.curricula
        }
        self.initial_score = score_itc2007_instance_schedule(inst, schedule)

    def _build_conflicts(self) -> tuple[frozenset[int], ...]:
        result: list[set[int]] = [set() for _ in self.activity_ids]
        for left in range(len(self.activity_ids)):
            for right in range(left + 1, len(self.activity_ids)):
                if (
                    self.teacher[left] == self.teacher[right]
                    or self.curricula_by_course[self.course_code[left]]
                    & self.curricula_by_course[self.course_code[right]]
                ):
                    result[left].add(right)
                    result[right].add(left)
        return tuple(frozenset(values) for values in result)

    def capacity_contribution(self, index: int, room_id: int) -> int:
        return max(
            0,
            int(self.students[self.course_code[index]])
            - int(self.room_capacity[int(room_id)]),
        )

    def course_terms(
        self,
        code: str,
        period_override: Mapping[int, int],
        room_override: Mapping[int, int],
    ) -> tuple[int, int]:
        indexes = self.indexes_by_course[code]
        days = {
            int(period_override.get(index, self.base_period[index]))
            // self.slots_per_day
            for index in indexes
        }
        rooms = {
            int(room_override.get(index, self.base_room[index]))
            for index in indexes
        }
        return (
            5 * max(0, int(self.minimum_days[code]) - len(days)),
            max(0, len(rooms) - 1),
        )

    def curriculum_term(
        self,
        curriculum: str,
        period_override: Mapping[int, int],
    ) -> int:
        periods = tuple(
            int(period_override.get(index, self.base_period[index]))
            for index in self.indexes_by_curriculum[curriculum]
        )
        occupied = set(periods)
        isolated = 0
        for period in periods:
            slot = int(period) % self.slots_per_day
            adjacent = bool(
                (slot > 0 and period - 1 in occupied)
                or (
                    slot + 1 < self.slots_per_day
                    and period + 1 in occupied
                )
            )
            isolated += int(not adjacent)
        return 2 * isolated

    def score_overrides(
        self,
        period_override: Mapping[int, int],
        room_override: Mapping[int, int],
    ) -> ITC2007Score:
        moved = set(period_override) | set(room_override)
        affected_courses = {self.course_code[index] for index in moved}
        affected_curricula: set[str] = set()
        for code in affected_courses:
            affected_curricula.update(self.curricula_by_course[code])

        capacity = int(self.initial_score.room_capacity)
        for index, room_id in room_override.items():
            capacity += self.capacity_contribution(index, int(room_id))
            capacity -= int(self.base_capacity_by_index[index])

        minimum_working_days = int(self.initial_score.minimum_working_days)
        stability = int(self.initial_score.room_stability)
        for code in affected_courses:
            old_days, old_stability = self.base_course_terms[code]
            new_days, new_stability = self.course_terms(
                code,
                period_override,
                room_override,
            )
            minimum_working_days += int(new_days) - int(old_days)
            stability += int(new_stability) - int(old_stability)

        compactness = int(self.initial_score.curriculum_compactness)
        for curriculum in affected_curricula:
            compactness += self.curriculum_term(curriculum, period_override)
            compactness -= int(self.base_curriculum_terms[curriculum])
        return ITC2007Score(
            room_capacity=int(capacity),
            minimum_working_days=int(minimum_working_days),
            curriculum_compactness=int(compactness),
            room_stability=int(stability),
            total=int(capacity + minimum_working_days + compactness + stability),
        )

    def arrays(
        self,
        period_override: Mapping[int, int],
        room_override: Mapping[int, int],
    ) -> tuple[list[int], list[int], list[set[int]]]:
        periods = list(self.base_period)
        rooms = list(self.base_room)
        for index, period in period_override.items():
            periods[index] = int(period)
        for index, room_id in room_override.items():
            rooms[index] = int(room_id)
        by_period = [set() for _ in range(self.period_count)]
        for index, period in enumerate(periods):
            by_period[int(period)].add(index)
        return periods, rooms, by_period

    def swap_feasible(
        self,
        left: int,
        right: int,
        periods: Sequence[int],
        by_period: Sequence[set[int]],
    ) -> bool:
        left_period = int(periods[left])
        right_period = int(periods[right])
        if left_period == right_period:
            return False
        if (
            right_period in self.forbidden[left]
            or left_period in self.forbidden[right]
        ):
            return False
        if any(
            other != right and other in self.conflicts[left]
            for other in by_period[right_period]
        ):
            return False
        return not any(
            other != left and other in self.conflicts[right]
            for other in by_period[left_period]
        )

    def compose_swap(
        self,
        left: int,
        right: int,
        periods: Sequence[int],
        rooms: Sequence[int],
        period_override: Mapping[int, int],
        room_override: Mapping[int, int],
    ) -> tuple[dict[int, int], dict[int, int]]:
        next_period = dict(period_override)
        next_room = dict(room_override)
        next_period[left], next_period[right] = (
            int(periods[right]),
            int(periods[left]),
        )
        next_room[left], next_room[right] = (
            int(rooms[right]),
            int(rooms[left]),
        )
        for index in (left, right):
            if next_period[index] == self.base_period[index]:
                next_period.pop(index, None)
            if next_room[index] == self.base_room[index]:
                next_room.pop(index, None)
        return next_period, next_room

    def move(
        self,
        left: int,
        right: int,
        periods: Sequence[int],
        rooms: Sequence[int],
    ) -> CompoundMove:
        return CompoundMove(
            left_activity_id=int(self.activity_ids[left]),
            right_activity_id=int(self.activity_ids[right]),
            left_from_period=int(periods[left]),
            right_from_period=int(periods[right]),
            left_from_room=int(rooms[left]),
            right_from_room=int(rooms[right]),
        )

    def materialize(
        self,
        period_override: Mapping[int, int],
        room_override: Mapping[int, int],
    ) -> Schedule:
        candidate = _copy_schedule(self.schedule)
        for index, period in period_override.items():
            activity_id = self.activity_ids[index]
            candidate[activity_id]["day"] = str(
                self.inst.days[int(period) // self.slots_per_day]
            )
            candidate[activity_id]["slot"] = int(period) % self.slots_per_day
        for index, room_id in room_override.items():
            candidate[self.activity_ids[index]]["room_id"] = int(room_id)
        return candidate


def optimize_itc2007_compound(
    inst: Instance,
    schedule: Mapping[int, Mapping[str, Any]],
    *,
    deadline: float,
    seed: int = 0,
    max_first_moves: int = 32,
    max_second_checks: int = 50_000,
    validator: Validator | None = None,
) -> CompoundSearchResult:
    """Accept a strict two-move improvement while keeping the barrier atomic.

    The first full-position exchange is generated only when it improves the
    exact capacity-plus-room-stability support signal. It may worsen the
    official objective temporarily. A second exchange must repair the complete
    official objective; only the compound's final complete schedule is exposed,
    validated, independently rescored, and eligible for strict acceptance.
    """

    started = time.perf_counter()
    original = _copy_schedule(schedule) if isinstance(schedule, Mapping) else {}
    telemetry = CompoundSearchTelemetry(seed=int(seed))
    initial_score: ITC2007Score | None = None
    final_score: ITC2007Score | None = None
    selected = original
    validation_fn = validator or _default_validator

    def finish(
        status: str,
        *,
        validation_errors: Sequence[str] = (),
        eligibility_reasons: Sequence[str] = (),
        error: str | None = None,
    ) -> CompoundSearchResult:
        finished = time.perf_counter()
        overrun = max(0.0, float(finished) - float(deadline))
        telemetry.timing = {
            "elapsed_seconds": float(finished - started),
            "budget_seconds": max(0.0, float(deadline) - float(started)),
            "deadline_remaining_seconds": max(0.0, float(deadline) - finished),
            "deadline_overrun_seconds": float(overrun),
        }
        improved = bool(
            initial_score is not None
            and final_score is not None
            and final_score.total < initial_score.total
            and selected is not original
            and overrun == 0.0
        )
        return CompoundSearchResult(
            status=str(status if improved or status != "improved" else "deadline_exhausted"),
            schedule=_copy_schedule(selected if improved else original),
            improved=improved,
            initial_score=initial_score,
            final_score=final_score if improved else initial_score,
            telemetry=telemetry,
            validation_errors=tuple(str(value) for value in validation_errors)[:20],
            eligibility_reasons=tuple(str(value) for value in eligibility_reasons),
            deadline_exhausted=bool(finished >= float(deadline)),
            deadline_overrun_seconds=float(overrun),
            error=error,
        )

    try:
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        if int(max_first_moves) < 1 or int(max_second_checks) < 1:
            return finish(
                "ineligible",
                eligibility_reasons=("search_bounds_must_be_positive",),
            )
        eligible, reasons = projected_time_search_eligibility(inst, original)
        if not eligible:
            return finish("ineligible", eligibility_reasons=reasons)
        weights = {
            str(key): int(value)
            for key, value in dict(
                inst.sla_targets["itc2007"].get("objective_weights") or {}
            ).items()
        }
        if weights != _STANDARD_WEIGHTS:
            return finish(
                "ineligible",
                eligibility_reasons=("requires_standard_itc2007_objective",),
            )
        telemetry.validation_calls += 1
        incumbent_errors = tuple(
            str(error) for error in validation_fn(inst, original)
        )
        if time.perf_counter() >= float(deadline):
            return finish("deadline_exhausted")
        if incumbent_errors:
            return finish("invalid_incumbent", validation_errors=incumbent_errors)

        state = _CompoundState(inst, original)
        initial_score = state.initial_score
        base_room_signal = int(
            initial_score.room_capacity + initial_score.room_stability
        )
        base_periods, base_rooms, base_by_period = state.arrays({}, {})
        first_moves: list[
            tuple[
                int,
                int,
                dict[int, int],
                dict[int, int],
                ITC2007Score,
                CompoundMove,
            ]
        ] = []

        for left in range(len(state.activity_ids)):
            for right in range(left + 1, len(state.activity_ids)):
                if time.perf_counter() >= float(deadline):
                    return finish("deadline_exhausted")
                if not state.swap_feasible(
                    left,
                    right,
                    base_periods,
                    base_by_period,
                ):
                    continue
                telemetry.first_moves_checked += 1
                period_override, room_override = state.compose_swap(
                    left,
                    right,
                    base_periods,
                    base_rooms,
                    {},
                    {},
                )
                intermediate = state.score_overrides(
                    period_override,
                    room_override,
                )
                if (
                    intermediate.room_capacity + intermediate.room_stability
                    >= base_room_signal
                ):
                    continue
                first_moves.append(
                    (
                        left,
                        right,
                        period_override,
                        room_override,
                        intermediate,
                        state.move(left, right, base_periods, base_rooms),
                    )
                )
        first_moves.sort(
            key=lambda row: (
                int(row[4].room_capacity + row[4].room_stability),
                int(row[4].total),
                int(row[0]),
                int(row[1]),
            )
        )
        first_moves = first_moves[: int(max_first_moves)]
        telemetry.first_moves_generated = len(first_moves)

        checks_remaining = int(max_second_checks)
        for (
            _first_left,
            _first_right,
            first_period,
            first_room,
            intermediate,
            first_move,
        ) in first_moves:
            periods, rooms, by_period = state.arrays(first_period, first_room)
            for left in range(len(state.activity_ids)):
                for right in range(left + 1, len(state.activity_ids)):
                    if time.perf_counter() >= float(deadline):
                        return finish("deadline_exhausted")
                    if checks_remaining <= 0:
                        break
                    if not state.swap_feasible(left, right, periods, by_period):
                        continue
                    checks_remaining -= 1
                    telemetry.second_moves_checked += 1
                    period_override, room_override = state.compose_swap(
                        left,
                        right,
                        periods,
                        rooms,
                        first_period,
                        first_room,
                    )
                    predicted = state.score_overrides(
                        period_override,
                        room_override,
                    )
                    if predicted.total >= initial_score.total:
                        continue
                    telemetry.compounds_shortlisted += 1
                    candidate = state.materialize(period_override, room_override)
                    telemetry.validation_calls += 1
                    errors = tuple(
                        str(error) for error in validation_fn(inst, candidate)
                    )
                    if time.perf_counter() >= float(deadline):
                        return finish("deadline_exhausted")
                    if errors:
                        continue
                    telemetry.compounds_validated += 1
                    telemetry.independent_rescores += 1
                    official = score_itc2007_instance_schedule(inst, candidate)
                    if time.perf_counter() >= float(deadline):
                        return finish("deadline_exhausted")
                    if official != predicted:
                        return finish(
                            "error",
                            error="incremental_official_score_disagreement",
                        )
                    second_move = state.move(left, right, periods, rooms)
                    selected = candidate
                    final_score = official
                    telemetry.accepted_compounds = 1
                    telemetry.barrier_crossings = int(
                        intermediate.total > initial_score.total
                    )
                    telemetry.best_trajectory = [
                        {
                            "atomic_step": 1,
                            "move": first_move.to_dict(),
                            "intermediate_score": intermediate.to_dict(),
                            "accepted_independently": False,
                        },
                        {
                            "atomic_step": 2,
                            "move": second_move.to_dict(),
                            "final_score": final_score.to_dict(),
                            "compound_accepted": True,
                        },
                    ]
                    return finish("improved")
                if checks_remaining <= 0:
                    break
            if checks_remaining <= 0:
                break

        return finish(
            "deadline_exhausted"
            if time.perf_counter() >= float(deadline)
            else "no_improvement"
        )
    except Exception as exc:
        return finish("error", error=f"{type(exc).__name__}:{exc}")


__all__ = [
    "CompoundMove",
    "CompoundSearchResult",
    "CompoundSearchTelemetry",
    "optimize_itc2007_compound",
]
