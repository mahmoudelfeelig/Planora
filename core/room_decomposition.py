from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from ortools.sat.python import cp_model

from core.room_proof_checker import (
    EFFECTIVE_DOMAIN_RULE,
    HALL_CERTIFICATE_RULE,
    ROOM_CERTIFICATE_SCHEMA,
    certificate_id_for_payload,
    room_context_id,
)
from utils.domain import Instance
from utils.demand import demand_requirement, required_capacity as capacity_required
from utils.distribution_constraints import normalize_distribution_type
from utils.schedule_rules import hard_flag, room_is_available, room_transition_buffer


@dataclass(frozen=True)
class RoomConflictCertificate:
    certificate_type: str
    activity_ids: tuple[int, ...]
    representative_activity_ids: tuple[int, ...]
    candidate_room_ids: tuple[int, ...]
    week: int | None
    day: str | None
    slot: int | None
    deficiency: int
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)
    proof: dict[str, Any] = field(default_factory=dict)
    schema_version: str = ROOM_CERTIFICATE_SCHEMA
    certificate_id: str = ""

    def __post_init__(self) -> None:
        payload = self._identity_payload()
        expected_id = certificate_id_for_payload(payload)
        if self.certificate_id and self.certificate_id != expected_id:
            raise ValueError("Room certificate ID does not match its content")
        object.__setattr__(self, "certificate_id", expected_id)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "certificate_type": str(self.certificate_type),
            "activity_ids": list(self.activity_ids),
            "representative_activity_ids": list(
                self.representative_activity_ids
            ),
            "candidate_room_ids": list(self.candidate_room_ids),
            "week": self.week,
            "day": self.day,
            "slot": self.slot,
            "deficiency": int(self.deficiency),
            "message": str(self.message),
            "metadata": dict(self.metadata),
            "proof": dict(self.proof),
            "schema_version": str(self.schema_version),
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RoomSubproblemResult:
    status: int
    status_name: str
    feasible: bool
    assignments: dict[int, int] = field(default_factory=dict)
    certificates: list[RoomConflictCertificate] = field(default_factory=list)
    objective_value: float | None = None
    best_objective_bound: float | None = None
    relative_gap: float | None = None
    timing: dict[str, Any] = field(default_factory=dict)
    proof: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": int(self.status),
            "status_name": self.status_name,
            "feasible": bool(self.feasible),
            "assignments": {str(k): int(v) for k, v in sorted(self.assignments.items())},
            "certificates": [certificate.to_dict() for certificate in self.certificates],
            "objective_value": self.objective_value,
            "best_objective_bound": self.best_objective_bound,
            "relative_gap": self.relative_gap,
            "timing": dict(self.timing),
            "proof": dict(self.proof),
        }


@dataclass(frozen=True)
class _RoomJob:
    id: int
    members: tuple[int, ...]
    representative: int
    week: int
    day: str
    slot: int
    duration: int
    staff_ids: frozenset[int]
    group_ids: frozenset[int]
    candidate_rooms: tuple[int, ...]
    required_capacity: int
    demand_requirement: dict[str, Any]


def eligible_rooms_for_activity(inst: Instance, activity_id: int) -> list[int]:
    activity = inst.activities[int(activity_id)]
    required_capacity = capacity_required(inst, activity.group_ids)
    enforce_capacity = hard_flag(inst, "enforce_room_capacity", True)
    if activity.kind == "LAB":
        specialization = getattr(activity, "requires_specialization", None)
        rooms = [
            int(room_id)
            for room_id, room in inst.rooms.items()
            if room.room_type in ("SPECIALIZED_LAB", "COMPUTER_LAB")
            and (not enforce_capacity or int(room.capacity) >= required_capacity)
        ]
        if specialization:
            rooms = [
                room_id
                for room_id in rooms
                if inst.rooms[room_id].room_type == "SPECIALIZED_LAB"
                and specialization in (getattr(inst.rooms[room_id], "specialization_tags", set()) or set())
            ]
        return sorted(rooms)
    if activity.kind == "TUT":
        return sorted(
            int(room_id)
            for room_id, room in inst.rooms.items()
            if room.room_type in ("TUTORIAL", "LECTURE")
            and (not enforce_capacity or int(room.capacity) >= required_capacity)
        )
    return sorted(
        int(room_id)
        for room_id, room in inst.rooms.items()
        if room.room_type == "LECTURE"
        and (not enforce_capacity or int(room.capacity) >= required_capacity)
    )


def candidate_rooms_for_members(
    inst: Instance,
    activity_ids: Iterable[int],
    *,
    week: int,
    day: str,
    start_slot: int,
    duration: int | None = None,
) -> tuple[int, ...]:
    """Return the exact fixed-time room domain for one activity or cluster job."""
    members = tuple(sorted({int(value) for value in activity_ids}))
    if not members:
        return ()

    group_ids = {
        int(group_id)
        for activity_id in members
        for group_id in inst.activities[activity_id].group_ids
    }
    required_capacity = capacity_required(inst, group_ids)
    job_duration = (
        max(int(inst.activities[activity_id].duration) for activity_id in members)
        if duration is None
        else int(duration)
    )

    candidates = set(eligible_rooms_for_activity(inst, members[0]))
    for activity_id in members[1:]:
        candidates &= set(eligible_rooms_for_activity(inst, activity_id))
    candidates = {
        int(room_id)
        for room_id in candidates
        if (
            not hard_flag(inst, "enforce_room_capacity", True)
            or int(inst.rooms[room_id].capacity) >= int(required_capacity)
        )
        and room_is_available(
            inst,
            int(room_id),
            week=int(week),
            day=str(day),
            start_slot=int(start_slot),
            dur=int(job_duration),
        )
    }

    locks = getattr(inst, "locked_activities", {}) or {}
    locked_rooms = {
        int(locks[activity_id]["room_id"])
        for activity_id in members
        if isinstance(locks, dict)
        and isinstance(locks.get(activity_id), dict)
        and locks[activity_id].get("room_id") is not None
    }
    if len(locked_rooms) > 1:
        return ()
    if locked_rooms:
        candidates &= locked_rooms
    return tuple(sorted(candidates))


def _maximum_matching(
    left_ids: Iterable[int], edges: dict[int, tuple[int, ...]]
) -> tuple[dict[int, int], dict[int, int]]:
    right_to_left: dict[int, int] = {}

    def augment(left_id: int, seen_rooms: set[int]) -> bool:
        for room_id in edges.get(int(left_id), ()):
            if int(room_id) in seen_rooms:
                continue
            seen_rooms.add(int(room_id))
            prior = right_to_left.get(int(room_id))
            if prior is None or augment(int(prior), seen_rooms):
                right_to_left[int(room_id)] = int(left_id)
                return True
        return False

    for left_id in sorted(int(value) for value in left_ids):
        augment(int(left_id), set())
    return {left_id: room_id for room_id, left_id in right_to_left.items()}, right_to_left


def hall_deficiency_certificate(
    jobs: Iterable[_RoomJob],
    *,
    inst: Instance,
    week: int,
    day: str,
    slot: int,
) -> RoomConflictCertificate | None:
    active_jobs = [job for job in jobs if job.slot <= int(slot) < job.slot + job.duration]
    if not active_jobs:
        return None
    edges = {job.id: tuple(job.candidate_rooms) for job in active_jobs}
    left_to_right, right_to_left = _maximum_matching(edges, edges)
    unmatched = [job.id for job in active_jobs if job.id not in left_to_right]
    if not unmatched:
        return None

    reachable_left = set(int(job_id) for job_id in unmatched)
    reachable_right: set[int] = set()
    queue = list(reachable_left)
    while queue:
        left_id = queue.pop()
        matched_room = left_to_right.get(int(left_id))
        for room_id in edges.get(int(left_id), ()):
            if matched_room == int(room_id):
                continue
            if int(room_id) in reachable_right:
                continue
            reachable_right.add(int(room_id))
            matched_left = right_to_left.get(int(room_id))
            if matched_left is not None and int(matched_left) not in reachable_left:
                reachable_left.add(int(matched_left))
                queue.append(int(matched_left))

    by_id = {job.id: job for job in active_jobs}
    witness_jobs = [by_id[job_id] for job_id in sorted(reachable_left)]
    candidate_rooms = sorted(
        {room_id for job in witness_jobs for room_id in job.candidate_rooms}
    )
    deficiency = len(witness_jobs) - len(candidate_rooms)
    if deficiency <= 0:
        # Defensive fallback: the entire active set is always a valid Hall witness
        # when maximum matching could not cover all jobs.
        witness_jobs = active_jobs
        candidate_rooms = sorted({room_id for job in active_jobs for room_id in job.candidate_rooms})
        deficiency = len(witness_jobs) - len(candidate_rooms)

    activities = sorted({activity_id for job in witness_jobs for activity_id in job.members})
    representatives = sorted(job.representative for job in witness_jobs)
    representative_jobs = [
        {
            "representative_activity_id": int(job.representative),
            "member_activity_ids": [int(value) for value in job.members],
            "start_slot": int(job.slot),
            "duration": int(job.duration),
            "effective_room_ids": [int(value) for value in job.candidate_rooms],
            "domain_assumptions": {
                "domain_rule": EFFECTIVE_DOMAIN_RULE,
                "member_activity_ids": [int(value) for value in job.members],
                "week": int(week),
                "day": str(day),
                "start_slot": int(job.slot),
                "duration": int(job.duration),
            },
        }
        for job in sorted(witness_jobs, key=lambda item: int(item.representative))
    ]
    return RoomConflictCertificate(
        certificate_type="hall_deficiency",
        activity_ids=tuple(activities),
        representative_activity_ids=tuple(representatives),
        candidate_room_ids=tuple(candidate_rooms),
        week=int(week),
        day=str(day),
        slot=int(slot),
        deficiency=max(1, int(deficiency)),
        message=(
            f"{len(witness_jobs)} simultaneous room jobs can use only "
            f"{len(candidate_rooms)} eligible rooms at W{week} {day} slot {slot}."
        ),
        metadata={
            "required_capacities": sorted(
                int(job.required_capacity) for job in witness_jobs
            ),
            "demand_modes": sorted(
                {
                    str(job.demand_requirement.get("mode", "nominal"))
                    for job in witness_jobs
                }
            ),
        },
        proof={
            "proof_rule": HALL_CERTIFICATE_RULE,
            "room_context_id": room_context_id(inst),
            "witness_slot": {
                "week": int(week),
                "day": str(day),
                "slot": int(slot),
            },
            "representative_jobs": representative_jobs,
            "witness_room_ids": [int(value) for value in candidate_rooms],
            "job_count": int(len(witness_jobs)),
            "witness_room_count": int(len(candidate_rooms)),
            "deficiency": int(deficiency),
        },
    )


class ExactRoomSubproblem:
    """Assign rooms exactly for a fixed time schedule and emit cut-ready certificates."""

    def __init__(
        self,
        inst: Instance,
        schedule: dict[int, dict[str, Any]],
        *,
        clusters_by_week_kind: dict[int, dict[str, list[list[int]]]] | None = None,
        repeat_pattern_pairs: Iterable[tuple[int, int]] = (),
        optimize: bool = True,
    ) -> None:
        setup_started = time.perf_counter()
        self.inst = inst
        self.schedule = schedule
        self.clusters_by_week_kind = clusters_by_week_kind or {}
        self.repeat_pattern_pairs = [(int(a), int(b)) for a, b in repeat_pattern_pairs]
        self.optimize = bool(optimize)
        self.jobs = self._build_jobs()
        self.job_by_activity = {
            int(activity_id): job for job in self.jobs for activity_id in job.members
        }
        self.job_build_seconds = float(time.perf_counter() - setup_started)

    def _build_jobs(self) -> list[_RoomJob]:
        cluster_by_activity: dict[int, tuple[int, ...]] = {}
        for by_kind in self.clusters_by_week_kind.values():
            for clusters in by_kind.values():
                for cluster in clusters:
                    members = tuple(sorted(int(value) for value in cluster))
                    for activity_id in members:
                        prior = cluster_by_activity.get(int(activity_id))
                        if prior is not None and prior != members:
                            raise ValueError(f"Activity {activity_id} belongs to overlapping room clusters")
                        cluster_by_activity[int(activity_id)] = members

        grouped: list[tuple[int, ...]] = []
        seen: set[int] = set()
        for activity_id in sorted(int(value) for value in self.schedule):
            if activity_id in seen:
                continue
            members = cluster_by_activity.get(activity_id, (activity_id,))
            grouped.append(members)
            seen.update(members)

        jobs: list[_RoomJob] = []
        for job_id, members in enumerate(grouped):
            infos = [self.schedule[activity_id] for activity_id in members]
            time_keys = {
                (int(info["week"]), str(info["day"]), int(info["slot"]))
                for info in infos
            }
            if len(time_keys) != 1:
                raise ValueError(f"Cluster {members} does not share one fixed start")
            week, day, slot = next(iter(time_keys))
            duration = max(int(info["duration"]) for info in infos)
            group_ids = {
                int(group_id)
                for activity_id in members
                for group_id in self.inst.activities[activity_id].group_ids
            }
            capacity_requirement = demand_requirement(self.inst, group_ids)
            required_capacity = int(capacity_requirement.required)
            candidates = candidate_rooms_for_members(
                self.inst,
                members,
                week=int(week),
                day=str(day),
                start_slot=int(slot),
                duration=int(duration),
            )
            jobs.append(
                _RoomJob(
                    id=int(job_id),
                    members=members,
                    representative=int(members[0]),
                    week=week,
                    day=day,
                    slot=slot,
                    duration=duration,
                    staff_ids=frozenset(int(info["staff_id"]) for info in infos),
                    group_ids=frozenset(group_ids),
                    candidate_rooms=tuple(candidates),
                    required_capacity=int(required_capacity),
                    demand_requirement=capacity_requirement.to_dict(),
                )
            )
        return jobs

    def _hall_certificates(self) -> list[RoomConflictCertificate]:
        certificates: list[RoomConflictCertificate] = []
        seen: set[tuple[int, str, int, tuple[int, ...]]] = set()
        slots = sorted(
            {
                (job.week, job.day, slot)
                for job in self.jobs
                for slot in range(job.slot, job.slot + job.duration)
            }
        )
        for week, day, slot in slots:
            jobs = [job for job in self.jobs if job.week == week and job.day == day]
            certificate = hall_deficiency_certificate(
                jobs,
                inst=self.inst,
                week=week,
                day=day,
                slot=slot,
            )
            if certificate is None:
                continue
            key = (week, day, slot, certificate.representative_activity_ids)
            if key not in seen:
                seen.add(key)
                certificates.append(certificate)
        return certificates

    def solve(
        self,
        *,
        time_limit_seconds: float | None = None,
        workers: int = 1,
        random_seed: int | None = None,
    ) -> RoomSubproblemResult:
        solve_started = time.perf_counter()
        budget_seconds = (
            None
            if time_limit_seconds is None
            else max(0.0, float(time_limit_seconds))
        )
        deadline = (
            None
            if budget_seconds is None
            else float(solve_started) + float(budget_seconds)
        )

        def timing_payload(
            *,
            model_setup_seconds: float,
            search_budget_seconds: float | None,
            search_seconds: float,
            deadline_safety_margin_seconds: float = 0.0,
        ) -> dict[str, Any]:
            elapsed = float(time.perf_counter() - solve_started)
            return {
                "budget_seconds": budget_seconds,
                "pre_solve_job_build_seconds": float(self.job_build_seconds),
                "model_setup_seconds": float(model_setup_seconds),
                "search_budget_seconds": search_budget_seconds,
                "deadline_safety_margin_seconds": float(
                    deadline_safety_margin_seconds
                ),
                "search_seconds": float(search_seconds),
                "elapsed_seconds": float(elapsed),
                "deadline_overrun_seconds": (
                    0.0
                    if deadline is None
                    else max(0.0, time.perf_counter() - float(deadline))
                ),
            }

        static_certificates = self._hall_certificates()
        if static_certificates:
            return RoomSubproblemResult(
                status=int(cp_model.INFEASIBLE),
                status_name="INFEASIBLE",
                feasible=False,
                certificates=static_certificates,
                timing=timing_payload(
                    model_setup_seconds=float(time.perf_counter() - solve_started),
                    search_budget_seconds=0.0,
                    search_seconds=0.0,
                ),
                proof={
                    "status": "infeasible",
                    "scope": "fixed_time_room_assignment",
                    "source": "hall_certificate",
                },
            )

        model = cp_model.CpModel()
        selected: dict[tuple[int, int], cp_model.IntVar] = {}
        for job in self.jobs:
            if not job.candidate_rooms:
                certificate = RoomConflictCertificate(
                    certificate_type="empty_domain",
                    activity_ids=job.members,
                    representative_activity_ids=(job.representative,),
                    candidate_room_ids=(),
                    week=job.week,
                    day=job.day,
                    slot=job.slot,
                    deficiency=1,
                    message=f"Room job {job.members} has no eligible room at its fixed time.",
                    metadata={
                        "demand_requirement": dict(job.demand_requirement),
                        "candidate_count": 0,
                    },
                )
                return RoomSubproblemResult(
                    status=int(cp_model.INFEASIBLE),
                    status_name="INFEASIBLE",
                    feasible=False,
                    certificates=[certificate],
                    timing=timing_payload(
                        model_setup_seconds=float(time.perf_counter() - solve_started),
                        search_budget_seconds=0.0,
                        search_seconds=0.0,
                    ),
                    proof={
                        "status": "infeasible",
                        "scope": "fixed_time_room_assignment",
                        "source": "empty_domain_certificate",
                    },
                )
            variables = []
            for room_id in job.candidate_rooms:
                variable = model.NewBoolVar(f"room[{job.id},{room_id}]")
                selected[(job.id, int(room_id))] = variable
                variables.append(variable)
            model.AddExactlyOne(variables)

        for room_id in sorted(int(value) for value in self.inst.rooms):
            for week, day, slot in sorted(
                {
                    (job.week, job.day, occupied_slot)
                    for job in self.jobs
                    for occupied_slot in range(job.slot, job.slot + job.duration)
                }
            ):
                variables = [
                    selected[(job.id, room_id)]
                    for job in self.jobs
                    if room_id in job.candidate_rooms
                    and job.week == week
                    and job.day == day
                    and job.slot <= slot < job.slot + job.duration
                ]
                if len(variables) > 1:
                    model.AddAtMostOne(variables)

        same_attendee_pairs: set[frozenset[int]] = set()
        for constraint in getattr(self.inst, "distribution_constraints", []) or []:
            if not constraint.required:
                continue
            if normalize_distribution_type(constraint.constraint_type) != "same_attendees":
                continue
            members = [int(value) for value in constraint.activity_ids]
            for index, left_activity in enumerate(members):
                for right_activity in members[index + 1 :]:
                    same_attendee_pairs.add(frozenset((left_activity, right_activity)))

        if hard_flag(self.inst, "enforce_travel_time_buffers", True):
            for index, left in enumerate(self.jobs):
                for right in self.jobs[index + 1 :]:
                    if left.week != right.week or left.day != right.day:
                        continue
                    explicit_same_attendees = any(
                        frozenset((left_activity, right_activity)) in same_attendee_pairs
                        for left_activity in left.members
                        for right_activity in right.members
                    )
                    if not (
                        left.staff_ids & right.staff_ids
                        or left.group_ids & right.group_ids
                        or explicit_same_attendees
                    ):
                        continue
                    if left.slot <= right.slot:
                        gap = right.slot - (left.slot + left.duration)
                    else:
                        gap = left.slot - (right.slot + right.duration)
                    for left_room in left.candidate_rooms:
                        for right_room in right.candidate_rooms:
                            buffer_slots = room_transition_buffer(
                                self.inst,
                                self.inst.rooms[left_room],
                                self.inst.rooms[right_room],
                            )
                            if gap < int(buffer_slots):
                                model.Add(
                                    selected[(left.id, left_room)]
                                    + selected[(right.id, right_room)]
                                    <= 1
                                )

        if hard_flag(self.inst, "force_repeat_weekly_pattern", False):
            for left_activity, right_activity in self.repeat_pattern_pairs:
                left = self.job_by_activity.get(left_activity)
                right = self.job_by_activity.get(right_activity)
                if left is None or right is None or left.id == right.id:
                    continue
                common = set(left.candidate_rooms) & set(right.candidate_rooms)
                for room_id in set(left.candidate_rooms) | set(right.candidate_rooms):
                    left_var = selected.get((left.id, room_id))
                    right_var = selected.get((right.id, room_id))
                    if room_id not in common:
                        if left_var is not None:
                            model.Add(left_var == 0)
                        if right_var is not None:
                            model.Add(right_var == 0)
                    elif left_var is not None and right_var is not None:
                        model.Add(left_var == right_var)

        for constraint in getattr(self.inst, "distribution_constraints", []) or []:
            if not constraint.required:
                continue
            kind = normalize_distribution_type(constraint.constraint_type)
            if kind not in {"same_room", "different_room"}:
                continue
            members = [int(value) for value in constraint.activity_ids]
            for index, left_activity in enumerate(members):
                for right_activity in members[index + 1 :]:
                    left = self.job_by_activity.get(left_activity)
                    right = self.job_by_activity.get(right_activity)
                    if left is None or right is None:
                        raise ValueError(
                            f"Distribution constraint {constraint.id} references an unscheduled activity"
                        )
                    if left.id == right.id:
                        if kind == "different_room":
                            model.Add(0 == 1)
                        continue
                    common = set(left.candidate_rooms) & set(right.candidate_rooms)
                    if kind == "same_room":
                        if not common:
                            model.Add(0 == 1)
                            continue
                        for room_id in set(left.candidate_rooms) | set(right.candidate_rooms):
                            left_var = selected.get((left.id, room_id))
                            right_var = selected.get((right.id, room_id))
                            if room_id not in common:
                                if left_var is not None:
                                    model.Add(left_var == 0)
                                if right_var is not None:
                                    model.Add(right_var == 0)
                            elif left_var is not None and right_var is not None:
                                model.Add(left_var == right_var)
                    else:
                        for room_id in common:
                            model.Add(
                                selected[(left.id, room_id)]
                                + selected[(right.id, room_id)]
                                <= 1
                            )

        costs = []
        for job in self.jobs:
            for room_id in job.candidate_rooms:
                room = self.inst.rooms[room_id]
                type_cost = 1 if job.members and self.inst.activities[job.representative].kind == "TUT" and room.room_type == "LECTURE" else 0
                capacity_overflow = max(0, job.required_capacity - int(room.capacity))
                capacity_waste = max(0, int(room.capacity) - job.required_capacity)
                scalar = (
                    type_cost * 1_000_000
                    + capacity_overflow * 100_000
                    + capacity_waste * 10
                    + int(room_id)
                )
                costs.append(int(scalar) * selected[(job.id, room_id)])
        if costs and self.optimize:
            model.Minimize(sum(costs))

        model_setup_seconds = float(time.perf_counter() - solve_started)
        deadline_safety_margin_seconds = (
            0.0
            if budget_seconds is None
            else min(0.02, max(0.001, float(budget_seconds) * 0.02))
        )
        search_budget_seconds = (
            None
            if deadline is None
            else max(
                0.0,
                float(deadline)
                - time.perf_counter()
                - float(deadline_safety_margin_seconds),
            )
        )
        if search_budget_seconds is not None and search_budget_seconds <= 0:
            return RoomSubproblemResult(
                status=int(cp_model.UNKNOWN),
                status_name=str(cp_model.CpSolverStatus(int(cp_model.UNKNOWN))),
                feasible=False,
                timing=timing_payload(
                    model_setup_seconds=model_setup_seconds,
                    search_budget_seconds=0.0,
                    search_seconds=0.0,
                    deadline_safety_margin_seconds=(
                        deadline_safety_margin_seconds
                    ),
                ),
                proof={
                    "status": "none",
                    "scope": "fixed_time_room_assignment",
                    "source": "budget_exhausted_during_model_setup",
                },
            )

        solver = cp_model.CpSolver()
        if search_budget_seconds is not None:
            solver.parameters.max_time_in_seconds = float(search_budget_seconds)
        solver.parameters.num_search_workers = int(workers)
        if random_seed is not None:
            solver.parameters.random_seed = int(random_seed)
        search_started = time.perf_counter()
        status = int(solver.Solve(model))
        search_seconds = float(time.perf_counter() - search_started)
        feasible = status in (int(cp_model.OPTIMAL), int(cp_model.FEASIBLE))
        assignments: dict[int, int] = {}
        if feasible:
            for job in self.jobs:
                room_id = next(
                    room_id
                    for room_id in job.candidate_rooms
                    if solver.BooleanValue(selected[(job.id, room_id)])
                )
                for activity_id in job.members:
                    assignments[int(activity_id)] = int(room_id)
        certificates: list[RoomConflictCertificate] = []
        if status == int(cp_model.INFEASIBLE):
            representatives = tuple(sorted(job.representative for job in self.jobs))
            certificates.append(
                RoomConflictCertificate(
                    certificate_type="room_model_nogood",
                    activity_ids=tuple(sorted(self.schedule)),
                    representative_activity_ids=representatives,
                    candidate_room_ids=tuple(sorted(self.inst.rooms)),
                    week=None,
                    day=None,
                    slot=None,
                    deficiency=1,
                    message="The exact room model is infeasible under travel, repeat, or lock constraints.",
                    metadata={
                        "demand_policy": dict(
                            getattr(self.inst, "demand_policy", {}) or {}
                        ),
                        "distribution_constraint_ids": [
                            str(constraint.id)
                            for constraint in getattr(
                                self.inst,
                                "distribution_constraints",
                                [],
                            )
                            or []
                            if constraint.required
                        ],
                    },
                )
            )
        objective_value = float(solver.ObjectiveValue()) if feasible else None
        best_objective_bound = (
            float(solver.BestObjectiveBound())
            if status != int(cp_model.UNKNOWN)
            else None
        )
        relative_gap = None
        if objective_value is not None and best_objective_bound is not None:
            relative_gap = max(
                0.0,
                float(objective_value) - float(best_objective_bound),
            ) / max(1.0, abs(float(objective_value)))
        proof_status = (
            "optimal"
            if status == int(cp_model.OPTIMAL)
            else "feasible_incumbent"
            if status == int(cp_model.FEASIBLE)
            else "infeasible"
            if status == int(cp_model.INFEASIBLE)
            else "model_invalid"
            if status == int(cp_model.MODEL_INVALID)
            else "none"
        )
        return RoomSubproblemResult(
            status=status,
            status_name=str(cp_model.CpSolverStatus(status)),
            feasible=feasible,
            assignments=assignments,
            certificates=certificates,
            objective_value=objective_value,
            best_objective_bound=best_objective_bound,
            relative_gap=relative_gap,
            timing=timing_payload(
                model_setup_seconds=model_setup_seconds,
                search_budget_seconds=search_budget_seconds,
                search_seconds=search_seconds,
                deadline_safety_margin_seconds=deadline_safety_margin_seconds,
            ),
            proof={
                "status": proof_status,
                "scope": "fixed_time_room_assignment",
                "source": "cp_sat",
            },
        )
