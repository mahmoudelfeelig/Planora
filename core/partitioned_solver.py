from __future__ import annotations

import copy
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from ortools.sat.python import cp_model

from core.solver_cp_sat import GreedyRoomingError, TimetableSolver
from utils.distribution_constraints import AGGREGATE_TYPES, normalize_distribution_type
from utils.domain import Instance


_FEASIBLE_STATUSES = {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}


def _hard_flag(inst: Instance, name: str, default: bool) -> bool:
    raw = (getattr(inst, "hard_constraints", {}) or {}).get(name, default)
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def week_partitioning_blockers(inst: Instance) -> list[str]:
    """Return hard reasons why week decisions cannot be solved independently."""
    blockers: list[str] = []
    if _hard_flag(inst, "force_repeat_weekly_pattern", False) and len(inst.weeks) > 1:
        blockers.append(
            "Week partitioning cannot enforce force_repeat_weekly_pattern across "
            "weeks. Use room_mode='decomposed' or disable that hard rule."
        )

    activity_week = {
        int(activity_id): int(activity.week)
        for activity_id, activity in inst.activities.items()
    }
    for constraint in getattr(inst, "distribution_constraints", []) or []:
        activity_ids = [int(value) for value in constraint.activity_ids]
        missing = [value for value in activity_ids if value not in activity_week]
        if missing:
            blockers.append(
                f"Distribution constraint {constraint.id} references unknown "
                f"activities {missing}"
            )
            continue
        weeks = {activity_week[value] for value in activity_ids}
        if len(weeks) <= 1 or not bool(constraint.required):
            continue
        try:
            kind = normalize_distribution_type(constraint.constraint_type)
        except ValueError as exc:
            blockers.append(str(exc))
            continue
        if kind in AGGREGATE_TYPES or kind in {"not_overlap", "same_attendees"}:
            continue
        if kind == "different_weeks":
            if len(set(activity_week[value] for value in activity_ids)) != len(
                activity_ids
            ):
                blockers.append(
                    f"Required distribution constraint {constraint.id} "
                    "(different_weeks) is statically infeasible"
                )
            continue
        if kind in {"same_weeks", "overlap"}:
            blockers.append(
                f"Required distribution constraint {constraint.id} ({kind}) "
                f"is statically infeasible across weeks {sorted(weeks)}"
            )
            continue
        if kind == "precedence":
            ordered_weeks = [activity_week[value] for value in activity_ids]
            if any(
                left > right for left, right in zip(ordered_weeks, ordered_weeks[1:])
            ):
                blockers.append(
                    f"Required distribution constraint {constraint.id} "
                    "(precedence) reverses fixed week order"
                )
            continue
        blockers.append(
            f"Week partitioning cannot separate required cross-week distribution "
            f"constraint {constraint.id} ({kind}) over weeks {sorted(weeks)}. "
            "Use room_mode='decomposed'."
        )

    if _hard_flag(inst, "enforce_precedence_rules", True):
        for raw_rule in getattr(inst, "precedence_rules", []) or []:
            if not isinstance(raw_rule, dict):
                continue
            try:
                before_id = int(raw_rule.get("before_activity_id"))
                after_id = int(raw_rule.get("after_activity_id"))
            except (TypeError, ValueError):
                continue
            if before_id not in activity_week or after_id not in activity_week:
                continue
            if activity_week[before_id] > activity_week[after_id]:
                blockers.append(
                    f"Precedence impossible: A{before_id} is in a later week "
                    f"than A{after_id}"
                )
    return blockers


@dataclass
class _PartitionResult:
    index: int
    week: int
    solver: cp_model.CpSolver
    status: int
    schedule: dict[int, dict[str, Any]]
    elapsed_seconds: float
    remaining_at_start_seconds: float | None
    model: TimetableSolver
    exact_room_fallback_used: bool
    queue_rank: int
    estimated_hardness: dict[str, int]


class PartitionedTimetableSolver:
    """Parallel exact-feasibility decomposition over independent teaching weeks.

    Every week gets a compact CP time master. Valid greedy rooming is accepted;
    if it fails, that partition is retried through the certificate-guided exact
    room subproblem. The decomposition is complete for feasibility without a
    time limit whenever hard constraints do not couple decisions across weeks.
    Unsupported cross-week hard coupling fails before any solve starts; it is
    never dropped silently.

    The mode intentionally excludes the global soft objective.  Cross-week
    fairness, stability, and consistency remain available through the
    monolithic research modes or a post-feasibility improvement experiment.
    """

    room_mode = "partitioned"

    def __init__(self, inst: Instance, *, use_objective: bool = False):
        if bool(use_objective):
            raise ValueError(
                "room_mode='partitioned' is an exact feasibility mode and does not "
                "claim a globally valid objective bound; set use_objective=False"
            )
        self.inst = inst
        self.use_objective = False
        self._solution: dict[int, dict[str, Any]] = {}
        self._last_solver = cp_model.CpSolver()
        self.decomposition_report: dict[str, Any] = {}
        self._soft_cross_week_constraints: list[str] = []
        self._resolved_cross_week_constraints: list[str] = []

        TimetableSolver.validate_instance(inst)
        self._validate_partitionability()
        self._partitions = self._build_partitions()

        # Compatibility with diagnostics that inspect a normal TimetableSolver.
        self.m = self._partitions[0][2].m if self._partitions else cp_model.CpModel()
        self.x: dict[tuple[int, int], Any] = {}

    def _validate_partitionability(self) -> None:
        blockers = week_partitioning_blockers(self.inst)
        if blockers:
            raise ValueError(blockers[0])

        activity_week = {
            int(activity_id): int(activity.week)
            for activity_id, activity in self.inst.activities.items()
        }
        for constraint in getattr(self.inst, "distribution_constraints", []) or []:
            activity_ids = [int(value) for value in constraint.activity_ids]
            missing = [value for value in activity_ids if value not in activity_week]
            if missing:
                raise ValueError(
                    f"Distribution constraint {constraint.id} references unknown "
                    f"activities {missing}"
                )
            weeks = {activity_week[value] for value in activity_ids}
            if len(weeks) <= 1:
                continue
            kind = normalize_distribution_type(constraint.constraint_type)
            if bool(constraint.required):
                if kind in AGGREGATE_TYPES or kind in {"not_overlap", "same_attendees"}:
                    self._resolved_cross_week_constraints.append(str(constraint.id))
                    continue
                if kind == "different_weeks":
                    self._resolved_cross_week_constraints.append(str(constraint.id))
                    continue
                if kind == "precedence":
                    self._resolved_cross_week_constraints.append(str(constraint.id))
                    continue
            self._soft_cross_week_constraints.append(str(constraint.id))

    def _build_partitions(self) -> list[tuple[int, int, TimetableSolver]]:
        partitions: list[tuple[int, int, TimetableSolver]] = []
        activities_by_week: dict[int, dict[int, Any]] = {}
        for activity_id, activity in self.inst.activities.items():
            activities_by_week.setdefault(int(activity.week), {})[int(activity_id)] = activity

        for index, week in enumerate(sorted(int(value) for value in self.inst.weeks)):
            week_activities = activities_by_week.get(int(week), {})
            activity_ids = set(week_activities)
            if not activity_ids:
                continue

            # Entity records are read-only during model construction and search. A
            # shallow instance view therefore safely shares programs, groups,
            # courses, staff, rooms, and activities while giving every partition
            # independent copies of the collections that this adapter rewrites.
            # This avoids copying the full semester once for every teaching week.
            sub = copy.copy(self.inst)
            sub.weeks = [int(week)]
            sub.activities = dict(week_activities)
            sub.locked_activities = {
                int(activity_id): dict(lock)
                for activity_id, lock in (self.inst.locked_activities or {}).items()
                if int(activity_id) in activity_ids
            }
            sub.activity_unavailability = {
                int(activity_id): set(values)
                for activity_id, values in (self.inst.activity_unavailability or {}).items()
                if int(activity_id) in activity_ids
            }
            sub.precedence_rules = [
                dict(rule)
                for rule in (self.inst.precedence_rules or [])
                if isinstance(rule, dict)
                and int(rule.get("before_activity_id", -1)) in activity_ids
                and int(rule.get("after_activity_id", -1)) in activity_ids
            ]
            partition_constraints = []
            for constraint in self.inst.distribution_constraints or []:
                all_ids = [int(value) for value in constraint.activity_ids]
                local_ids = [value for value in all_ids if value in activity_ids]
                if len(local_ids) == len(all_ids):
                    local = copy.copy(constraint)
                    local.activity_ids = list(all_ids)
                    local.parameters = dict(constraint.parameters or {})
                    partition_constraints.append(local)
                    continue
                if not bool(constraint.required):
                    continue
                kind = normalize_distribution_type(constraint.constraint_type)
                if kind == "different_weeks":
                    continue
                if kind == "precedence":
                    # Fixed week order already validates cross-week edges. Keep
                    # only the consecutive same-week segment in this partition.
                    if len(local_ids) >= 2:
                        derived = copy.copy(constraint)
                        derived.id = f"{constraint.id}::week-{week}"
                        derived.activity_ids = list(local_ids)
                        derived.parameters = dict(constraint.parameters or {})
                        partition_constraints.append(derived)
                    continue
                if kind in AGGREGATE_TYPES:
                    if local_ids:
                        derived = copy.copy(constraint)
                        derived.id = f"{constraint.id}::week-{week}"
                        derived.activity_ids = list(local_ids)
                        derived.parameters = dict(constraint.parameters or {})
                        partition_constraints.append(derived)
                    continue
                if kind in {"not_overlap", "same_attendees"} and len(local_ids) >= 2:
                    derived = copy.copy(constraint)
                    derived.id = f"{constraint.id}::week-{week}"
                    derived.activity_ids = list(local_ids)
                    derived.parameters = dict(constraint.parameters or {})
                    partition_constraints.append(derived)
            sub.distribution_constraints = partition_constraints
            sub.hard_constraints = dict(self.inst.hard_constraints or {})
            # These invariants were checked once against the complete instance.
            sub.hard_constraints["enforce_course_totals"] = False
            sub.hard_constraints["week1_lectures_only"] = False
            sub.hard_constraints["force_repeat_weekly_pattern"] = False
            required_room_relation = any(
                bool(constraint.required)
                and normalize_distribution_type(constraint.constraint_type)
                in {"same_room", "different_room"}
                for constraint in sub.distribution_constraints
            )
            inner_mode = "decomposed" if required_room_relation else "greedy"
            partitions.append(
                (
                    int(index),
                    int(week),
                    TimetableSolver(sub, room_mode=inner_mode, use_objective=False),
                )
            )
        return partitions

    @staticmethod
    def _partition_hardness(model: TimetableSolver) -> dict[str, int]:
        proto = model.m.Proto()
        return {
            "constraints": int(len(proto.constraints)),
            "variables": int(len(proto.variables)),
            "activities": int(len(model.inst.activities)),
        }

    def _execution_partitions(
        self,
    ) -> list[tuple[int, int, TimetableSolver, dict[str, int]]]:
        candidates = [
            (index, week, model, self._partition_hardness(model))
            for index, week, model in self._partitions
        ]
        return sorted(
            candidates,
            key=lambda row: (
                -int(row[3]["constraints"]),
                -int(row[3]["variables"]),
                -int(row[3]["activities"]),
                int(row[1]),
            ),
        )

    @staticmethod
    def _worker_cap(requested: int | None, partition_count: int) -> int:
        raw_cap = os.getenv("TT_PARTITION_WORKERS_CAP", "4").strip()
        try:
            configured_cap = max(1, int(raw_cap))
        except ValueError:
            configured_cap = 4
        wanted = configured_cap if requested is None else max(1, int(requested))
        return max(1, min(int(partition_count), int(wanted), int(configured_cap)))

    def model_stats(self) -> dict[str, int]:
        variables = 0
        constraints = 0
        materialized_literals = 0
        for _, _, model in self._partitions:
            proto = model.m.Proto()
            variables += len(proto.variables)
            constraints += len(proto.constraints)
            materialized_literals += len(model.x)
        return {
            "variables": int(variables),
            "constraints": int(constraints),
            "materialized_start_literals": int(materialized_literals),
            "partition_count": int(len(self._partitions)),
        }

    def solve(
        self,
        time_limit_seconds: float | None = None,
        workers: int | None = 8,
        random_seed: int | None = None,
        log_progress: bool = False,
    ) -> tuple[cp_model.CpSolver, int]:
        started = time.perf_counter()
        deadline = (
            None
            if time_limit_seconds is None
            else started + max(0.0, float(time_limit_seconds))
        )
        partition_workers = self._worker_cap(workers, len(self._partitions))

        def run_partition(
            index: int,
            week: int,
            model: TimetableSolver,
            queue_rank: int,
            estimated_hardness: dict[str, int],
        ) -> _PartitionResult:
            partition_started = time.perf_counter()
            remaining = (
                None
                if deadline is None
                else max(0.0, float(deadline) - partition_started)
            )
            if remaining is not None and remaining <= 0:
                return _PartitionResult(
                    index=index,
                    week=week,
                    solver=cp_model.CpSolver(),
                    status=int(cp_model.UNKNOWN),
                    schedule={},
                    elapsed_seconds=0.0,
                    remaining_at_start_seconds=0.0,
                    model=model,
                    exact_room_fallback_used=False,
                    queue_rank=int(queue_rank),
                    estimated_hardness=dict(estimated_hardness),
                )
            solver, status = model.solve(
                time_limit_seconds=remaining,
                workers=1,
                random_seed=(
                    None
                    if random_seed is None
                    else int(random_seed) + int(index) * 104729
                ),
                log_progress=bool(log_progress),
            )
            schedule: dict[int, dict[str, Any]] = {}
            exact_room_fallback_used = False
            if int(status) in _FEASIBLE_STATUSES:
                try:
                    schedule = model.extract_solution(solver)
                except GreedyRoomingError:
                    exact_room_fallback_used = True
                    fallback_started = time.perf_counter()
                    fallback_remaining = (
                        None
                        if deadline is None
                        else max(0.0, float(deadline) - fallback_started)
                    )
                    if fallback_remaining is None or fallback_remaining > 0:
                        model = TimetableSolver(
                            model.inst,
                            room_mode="decomposed",
                            use_objective=False,
                        )
                        fallback_remaining = (
                            None
                            if deadline is None
                            else max(0.0, float(deadline) - time.perf_counter())
                        )
                        if fallback_remaining is None or fallback_remaining > 0:
                            solver, status = model.solve(
                                time_limit_seconds=fallback_remaining,
                                workers=1,
                                random_seed=(
                                    None
                                    if random_seed is None
                                    else int(random_seed) + int(index) * 104729
                                ),
                                log_progress=bool(log_progress),
                            )
                            if int(status) in _FEASIBLE_STATUSES:
                                schedule = model.extract_solution(solver)
                        else:
                            status = int(cp_model.UNKNOWN)
                    else:
                        status = int(cp_model.UNKNOWN)
            return _PartitionResult(
                index=index,
                week=week,
                solver=solver,
                status=int(status),
                schedule=schedule,
                elapsed_seconds=float(time.perf_counter() - partition_started),
                remaining_at_start_seconds=remaining,
                model=model,
                exact_room_fallback_used=bool(exact_room_fallback_used),
                queue_rank=int(queue_rank),
                estimated_hardness=dict(estimated_hardness),
            )

        results: list[_PartitionResult] = []
        execution_partitions = self._execution_partitions()
        with ThreadPoolExecutor(
            max_workers=partition_workers,
            thread_name_prefix="planora-week",
        ) as executor:
            futures = {
                executor.submit(
                    run_partition,
                    index,
                    week,
                    model,
                    queue_rank,
                    hardness,
                ): (index, week)
                for queue_rank, (index, week, model, hardness) in enumerate(
                    execution_partitions,
                    start=1,
                )
            }
            for future in as_completed(futures):
                results.append(future.result())

        results.sort(key=lambda row: row.index)
        self._partitions = [
            (int(row.index), int(row.week), row.model)
            for row in results
        ]
        self._solution = {}
        self.m = self._partitions[0][2].m if self._partitions else cp_model.CpModel()
        for row in results:
            if int(row.status) in _FEASIBLE_STATUSES:
                self._solution.update(row.schedule)
                self._last_solver = row.solver

        statuses = [int(row.status) for row in results]
        if not results:
            overall_status = int(cp_model.MODEL_INVALID)
        elif all(status == int(cp_model.OPTIMAL) for status in statuses):
            overall_status = int(cp_model.OPTIMAL)
        elif all(status in _FEASIBLE_STATUSES for status in statuses):
            overall_status = int(cp_model.FEASIBLE)
        elif int(cp_model.INFEASIBLE) in statuses:
            overall_status = int(cp_model.INFEASIBLE)
        elif int(cp_model.MODEL_INVALID) in statuses:
            overall_status = int(cp_model.MODEL_INVALID)
        else:
            overall_status = int(cp_model.UNKNOWN)

        partition_rows = []
        for row in results:
            partition_rows.append(
                {
                    "week": int(row.week),
                    "activities": int(len(row.model.inst.activities)),
                    "status": str(cp_model.CpSolverStatus(int(row.status))),
                    "elapsed_seconds": float(row.elapsed_seconds),
                    "remaining_at_start_seconds": row.remaining_at_start_seconds,
                    "inner_room_mode": str(row.model.room_mode),
                    "exact_room_fallback_used": bool(row.exact_room_fallback_used),
                    "queue_rank": int(row.queue_rank),
                    "estimated_hardness": dict(row.estimated_hardness),
                    "room_decomposition": dict(row.model.decomposition_report or {}),
                }
            )
        self.decomposition_report = {
            "status": str(cp_model.CpSolverStatus(int(overall_status))),
            "strategy": "parallel_week_partition_with_exact_room_fallback",
            "partition_dimension": "week",
            "partition_workers": int(partition_workers),
            "inner_search_workers": 1,
            "wall_seconds": float(time.perf_counter() - started),
            "soft_cross_week_constraints_scored_post_solve": list(
                self._soft_cross_week_constraints
            ),
            "required_cross_week_constraints_resolved_without_coupling": list(
                self._resolved_cross_week_constraints
            ),
            "model": self.model_stats(),
            "partitions": partition_rows,
        }
        return self._last_solver, int(overall_status)

    def extract_solution(self, solver: cp_model.CpSolver) -> dict[int, dict[str, Any]]:
        del solver
        if len(self._solution) != len(self.inst.activities):
            raise ValueError("No complete partitioned schedule is available")
        return copy.deepcopy(self._solution)
