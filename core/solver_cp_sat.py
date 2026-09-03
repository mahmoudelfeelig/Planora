from __future__ import annotations
import os
import time
from itertools import combinations
from typing import Dict, List, Tuple, Optional, Set, DefaultDict
from collections import defaultdict, deque

from ortools.sat.python import cp_model
from utils.domain import Instance
from utils.demand import required_capacity as capacity_required
from utils.distribution_constraints import (
    AGGREGATE_TYPES,
    ORDERED_TYPES,
    PAIRWISE_TYPES,
    distribution_parameter,
    normalize_distribution_type,
    pair_satisfies_distribution,
)
from utils.schedule_rules import (
    calendar_slot_blocked,
    generic_resources_available,
    hard_flag,
    room_is_available,
    room_transition_buffer,
)
from core.room_decomposition import (
    ExactRoomSubproblem,
    RoomConflictCertificate,
    candidate_rooms_for_members,
)
from core.room_proof_checker import (
    CONTEXTUAL_CUT_RULE,
    CONTEXTUAL_CUT_SCHEMA,
    EFFECTIVE_DOMAIN_RULE,
    check_contextual_hall_derivation,
    check_hall_certificate,
    cut_id_for_inequality,
    derivation_id_for_payload,
    room_context_id,
)


class GreedyRoomingError(ValueError):
    def __init__(self, message: str, *, reason: str, activity_id: int | None = None):
        super().__init__(message)
        self.reason = reason
        self.activity_id = activity_id


def resolve_room_mode_for_hard_constraints(
    inst: Instance,
    requested_room_mode: str,
) -> tuple[str, str | None]:
    """Promote incomplete rooming modes when a hard rule couples time and rooms.

    Greedy rooming runs after the time master has finished.  A repeated weekly
    room pattern can therefore make an otherwise feasible fixed-time incumbent
    impossible to room.  The certificate-guided decomposition must participate
    in the time search for that combination; a room-only retry cannot repair it.
    """

    mode = str(requested_room_mode)
    if (
        mode == "greedy"
        and len(getattr(inst, "weeks", []) or []) > 1
        and hard_flag(inst, "force_repeat_weekly_pattern", False)
    ):
        return (
            "decomposed",
            "force_repeat_weekly_pattern_requires_joint_time_room_search",
        )
    return mode, None


def _min_cost_room_matching(
    activity_ids: List[int],
    candidate_edges: Dict[int, List[Tuple[int, int]]],
) -> Dict[int, int]:
    """
    Maximum-cardinality min-cost bipartite matching for a single timeslot.

    Edges are activity_id -> [(room_id, cost)]. Unit capacities are enough here:
    each non-clustered activity gets one room and each room is used once in
    that slot. The problem sizes per slot are small, so SPFA min-cost flow is
    simpler and deterministic enough for this post-processing phase.
    """
    left = [int(a_id) for a_id in activity_ids]
    if not left:
        return {}
    rooms = sorted({int(r_id) for edges in candidate_edges.values() for r_id, _ in edges})
    if not rooms:
        return {}
    n_left = len(left)
    n_rooms = len(rooms)
    source = 0
    left_offset = 1
    room_offset = left_offset + n_left
    sink = room_offset + n_rooms
    graph: List[List[List[int]]] = [[] for _ in range(sink + 1)]

    def add_edge(src: int, dst: int, cap: int, cost: int) -> None:
        graph[src].append([dst, int(cap), int(cost), len(graph[dst])])
        graph[dst].append([src, 0, -int(cost), len(graph[src]) - 1])

    left_index = {a_id: idx for idx, a_id in enumerate(left)}
    room_index = {r_id: idx for idx, r_id in enumerate(rooms)}
    for idx, a_id in enumerate(left):
        add_edge(source, left_offset + idx, 1, 0)
        for room_id, cost in sorted(
            candidate_edges.get(int(a_id), []),
            key=lambda item: (int(item[1]), int(item[0])),
        ):
            if int(room_id) in room_index:
                add_edge(left_offset + idx, room_offset + room_index[int(room_id)], 1, int(cost))
    for idx, _room_id in enumerate(rooms):
        add_edge(room_offset + idx, sink, 1, 0)

    flow = 0
    while flow < min(n_left, n_rooms):
        dist = [10**18] * (sink + 1)
        in_q = [False] * (sink + 1)
        prev_node = [-1] * (sink + 1)
        prev_edge = [-1] * (sink + 1)
        dist[source] = 0
        q: deque[int] = deque([source])
        in_q[source] = True
        while q:
            node = q.popleft()
            in_q[node] = False
            for edge_idx, edge in enumerate(graph[node]):
                dst, cap, cost, _rev = edge
                if cap <= 0:
                    continue
                nd = dist[node] + int(cost)
                if nd < dist[dst]:
                    dist[dst] = nd
                    prev_node[dst] = node
                    prev_edge[dst] = edge_idx
                    if not in_q[dst]:
                        q.append(dst)
                        in_q[dst] = True
        if prev_node[sink] < 0:
            break
        node = sink
        while node != source:
            p = prev_node[node]
            edge_idx = prev_edge[node]
            edge = graph[p][edge_idx]
            edge[1] -= 1
            graph[node][edge[3]][1] += 1
            node = p
        flow += 1

    assignment: Dict[int, int] = {}
    for a_id, idx in left_index.items():
        node = left_offset + idx
        for edge in graph[node]:
            dst, cap, _cost, _rev = edge
            if room_offset <= dst < room_offset + n_rooms and cap == 0:
                assignment[int(a_id)] = int(rooms[dst - room_offset])
                break
    return assignment


class TimetableSolver:
    """
    CP-SAT feasibility model with generalized co-location clusters and room-count guards.

    Time model
      - Weekly grid of D*S slots. Each activity picks one start in staff-available days.
      - Interval variables for groups and staff with NoOverlap to prevent conflicts.
      - Sunday, if present, is never scheduled.
      - Block staff: at most two distinct teaching days per week.
      - Optional weekly/daily load caps via staff settings.
      - Optional weekly load caps via staff.max_slots_per_week.
      - Clusters: LEC, TUT, LAB can be clustered; members share the same start in that week.

    Room model
      - Count guards only:
          * LEC uses LECTURE rooms.
          * TUT can use TUTORIAL or LECTURE rooms.
          * LAB uses COMPUTER_LAB or SPECIALIZED_LAB; specialization tags further restrict some LABs.
        Followers of a cluster do not count twice.
      - Modes:
          * "greedy" (fast): CP does not choose rooms. A greedy pass assigns rooms and co-locates clusters.
          * "cp_rooms" (slower): CP also chooses rooms with NoOverlap per real room and co-location inside clusters.
          * "decomposed" (research): CP chooses times; an exact room subproblem either assigns rooms or
            returns a Hall-deficiency/nogood certificate that is cut from the time master.

    Semester rules
      - First week must contain lectures only.
      - For each course: total LEC count equals total TUT count across the semester.

    Notes
      - Model targets fast feasibility on large instances. Put preferences into metaheuristics.
    """

    def __init__(self, inst: Instance, room_mode: str = "cp_rooms", *, use_objective: bool = True):
        assert room_mode in ("greedy", "cp_rooms", "decomposed")
        requested_room_mode = str(room_mode)
        room_mode, resolution_reason = resolve_room_mode_for_hard_constraints(
            inst,
            requested_room_mode,
        )
        self.inst = inst
        self.room_mode = room_mode
        self.requested_room_mode = requested_room_mode
        self.room_mode_resolution: Dict[str, object] = {
            "requested": requested_room_mode,
            "effective": str(room_mode),
            "promoted": bool(str(room_mode) != requested_room_mode),
            "reason": resolution_reason,
        }
        self.use_objective = bool(use_objective)

        self.m = cp_model.CpModel()

        # calendar geometry
        self.days: List[str] = inst.days
        self.weeks: List[int] = sorted(inst.weeks)
        self.S: int = inst.slots_per_day
        self.D: int = len(self.days)
        self.T_week: int = self.D * self.S

        # per-activity
        self.activity_staff: Dict[int, int] = {}
        self.allowed_starts: Dict[int, List[int]] = {}
        self.start: Dict[int, cp_model.IntVar] = {}
        self.x: Dict[Tuple[int, int], cp_model.BoolVar] = {}
        self.interval: Dict[int, cp_model.IntervalVar] = {}

        # resources
        self.group_intervals_by_week: Dict[Tuple[int, int], List[cp_model.IntervalVar]] = {}
        self.staff_intervals_by_week: Dict[Tuple[int, int], List[cp_model.IntervalVar]] = {}

        # clusters: week -> kind -> list of clusters (each cluster is list[int] of activity ids)
        self.clusters_by_week_kind: Dict[int, Dict[str, List[List[int]]]] = {}

        # free days support
        self.sunday_idx: Optional[int] = self._find_day_index("SUN")
        self.free_day_bool: Dict[Tuple[int, int, int], cp_model.BoolVar] = {}

        # decision var collections for strategy
        self._dec_free_bools: List[cp_model.BoolVar] = []
        self._dec_start_ints: List[cp_model.IntVar] = []
        self._dec_room_bools: List[cp_model.BoolVar] = []

        # room pools and CP-rooming vars
        self.lecture_room_ids: List[int] = []
        self.tutorial_room_ids: List[int] = []
        self.lab_room_ids: List[int] = []
        self.spec_rooms_by_tag: Dict[str, List[int]] = {}
        self.allowed_rooms: Dict[int, List[int]] = {}
        self.room_sel: Dict[Tuple[int, int], cp_model.BoolVar] = {}
        self.room_iv: Dict[Tuple[int, int], cp_model.IntervalVar] = {}
        self.room_candidate_limit: int = self._read_room_candidate_limit()
        self.decomposition_report: Dict[str, object] = {}
        self._last_room_cut_metadata: Dict[str, object] = {}
        self.hint_report: Dict[str, object] = {}
        self.assumption_report: Dict[str, object] = {}
        self.symmetry_report: Dict[str, object] = {}
        self._assumption_activity_by_literal: Dict[int, int] = {}
        self._decomposed_room_assignment: Dict[int, int] = {}

        # build model
        self._precompute()
        self._build_variables()
        self._add_constraints()
        if self.use_objective:
            self._add_objective()
        self._add_decision_strategy()

    @classmethod
    def validate_instance(cls, inst: Instance) -> None:
        """Run the solver's global structural preflight without building CP variables.

        Decomposed frontends use this hook before slicing an instance.  It keeps
        semester totals and staff competency checks global while avoiding a
        throwaway monolithic CP model.
        """
        checker = cls.__new__(cls)
        checker.inst = inst
        checker._validate_semester_rules()
        checker._validate_staff_assignments()
        checker._validate_block_professor_rules()

    # ---------- public API ----------

    def add_solution_hint(
        self,
        schedule: Dict[int, Dict[str, object]],
        *,
        include_rooms: bool = True,
    ) -> Dict[str, object]:
        """Warm-start CP-SAT from a full or partial incumbent.

        Hints do not constrain the model and may be ignored by CP-SAT. Values
        outside the current start/room domains are skipped so repair calls stay
        safe after an institutional policy change.
        """
        start_hints = 0
        room_hints = 0
        skipped: List[int] = []
        for raw_activity_id, info in (schedule or {}).items():
            try:
                activity_id = int(raw_activity_id)
            except (TypeError, ValueError):
                continue
            if activity_id not in self.start or not isinstance(info, dict):
                skipped.append(activity_id)
                continue
            day = str(info.get("day", ""))
            try:
                slot = int(info.get("slot"))
            except (TypeError, ValueError):
                skipped.append(activity_id)
                continue
            if day not in self.days:
                skipped.append(activity_id)
                continue
            start = self.days.index(day) * self.S + slot
            if int(start) not in self.allowed_starts.get(activity_id, []):
                skipped.append(activity_id)
                continue
            self.m.AddHint(self.start[activity_id], int(start))
            start_hints += 1

            if include_rooms and self.room_mode == "cp_rooms":
                raw_room = info.get("room_id")
                try:
                    room_id = int(raw_room) if raw_room is not None else None
                except (TypeError, ValueError):
                    room_id = None
                if room_id is not None and (activity_id, room_id) in self.room_sel:
                    for candidate_room in self.allowed_rooms.get(activity_id, []):
                        var = self.room_sel.get((activity_id, int(candidate_room)))
                        if var is not None:
                            self.m.AddHint(var, int(int(candidate_room) == room_id))
                            room_hints += 1

        self.hint_report = {
            "start_hints": int(start_hints),
            "room_literal_hints": int(room_hints),
            "skipped_activity_ids": sorted(set(int(value) for value in skipped)),
        }
        return dict(self.hint_report)

    def set_neighborhood_assumptions(
        self,
        schedule: Dict[int, Dict[str, object]],
        *,
        unlocked_activity_ids: Set[int] | List[int] | Tuple[int, ...],
    ) -> Dict[str, object]:
        """Fix the complement of an LNS neighborhood with reusable assumptions.

        The underlying global model and objective are built once. Each repair
        round changes only the assumption list and incumbent hint, avoiding a
        full Python/model reconstruction while preserving exact hard semantics.
        """
        if self.room_mode != "cp_rooms" or not self.use_objective:
            raise ValueError(
                "Reusable neighborhood assumptions require CP rooms and an objective"
            )
        incumbent_ids = {
            int(activity_id)
            for activity_id in (schedule or {})
            if int(activity_id) in self.inst.activities
        }
        missing_ids = sorted(set(int(value) for value in self.inst.activities) - incumbent_ids)
        if missing_ids:
            raise ValueError(
                "Reusable neighborhood assumptions require a complete incumbent; "
                f"missing activity ids {missing_ids[:10]}"
            )
        unlocked = {int(value) for value in unlocked_activity_ids}
        assumptions: List[cp_model.BoolVar] = []
        mapping: Dict[int, int] = {}
        fixed_activities = 0
        for raw_activity_id, info in (schedule or {}).items():
            activity_id = int(raw_activity_id)
            if activity_id in unlocked or activity_id not in self.inst.activities:
                continue
            if not isinstance(info, dict):
                continue
            day = str(info.get("day", ""))
            if day not in self.days:
                raise ValueError(f"Incumbent activity {activity_id} has invalid day {day!r}")
            start = self.days.index(day) * self.S + int(info.get("slot", 0))
            start_literal = self._start_literal(activity_id, int(start))
            assumptions.append(start_literal)
            mapping[int(start_literal.Index())] = int(activity_id)
            room_id = info.get("room_id")
            if room_id is not None:
                room_literal = self.room_sel.get((activity_id, int(room_id)))
                if room_literal is None:
                    raise ValueError(
                        f"Incumbent room {room_id} is outside activity {activity_id}'s domain"
                    )
                assumptions.append(room_literal)
                mapping[int(room_literal.Index())] = int(activity_id)
            fixed_activities += 1

        self.m.ClearAssumptions()
        self.m.AddAssumptions(assumptions)
        self.m.ClearHints()
        self.add_solution_hint(schedule, include_rooms=True)
        self._assumption_activity_by_literal = mapping
        self.assumption_report = {
            "unlocked_activities": int(len(unlocked)),
            "fixed_activities": int(fixed_activities),
            "assumption_literals": int(len(assumptions)),
        }
        return dict(self.assumption_report)

    def set_fixed_time_room_assumptions(
        self,
        schedule: Dict[int, Dict[str, object]],
    ) -> Dict[str, object]:
        """Fix every incumbent start while leaving all room choices free.

        The assumptions expose the exact room subproblem of the already-built
        global model.  Room locks, availability, capacity, co-location,
        travel, resources, and institution-specific relations therefore keep
        their normal CP semantics; only day/slot decisions are frozen.
        """
        if self.room_mode != "cp_rooms" or not self.use_objective:
            raise ValueError(
                "Fixed-time room assumptions require CP rooms and an objective"
            )
        incumbent_ids = {
            int(activity_id)
            for activity_id in (schedule or {})
            if int(activity_id) in self.inst.activities
        }
        missing_ids = sorted(set(int(value) for value in self.inst.activities) - incumbent_ids)
        if missing_ids:
            raise ValueError(
                "Fixed-time room assumptions require a complete incumbent; "
                f"missing activity ids {missing_ids[:10]}"
            )

        assumptions: List[cp_model.BoolVar] = []
        mapping: Dict[int, int] = {}
        for activity_id in sorted(int(value) for value in self.inst.activities):
            info = schedule.get(activity_id)
            if not isinstance(info, dict):
                raise ValueError(f"Incumbent activity {activity_id} has no schedule row")
            day = str(info.get("day", ""))
            if day not in self.days:
                raise ValueError(f"Incumbent activity {activity_id} has invalid day {day!r}")
            try:
                slot = int(info.get("slot"))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Incumbent activity {activity_id} has an invalid slot"
                ) from exc
            start = self.days.index(day) * self.S + slot
            start_literal = self._start_literal(activity_id, int(start))
            assumptions.append(start_literal)
            mapping[int(start_literal.Index())] = int(activity_id)

        self.m.ClearAssumptions()
        self.m.AddAssumptions(assumptions)
        self.m.ClearHints()
        self.add_solution_hint(schedule, include_rooms=True)
        self._assumption_activity_by_literal = mapping
        self.assumption_report = {
            "mode": "fixed_time_room_dive",
            "fixed_start_activities": int(len(assumptions)),
            "free_room_activities": int(len(self.inst.activities)),
            "assumption_literals": int(len(assumptions)),
        }
        return dict(self.assumption_report)

    def assumption_core_activity_ids(
        self,
        solver: cp_model.CpSolver,
        *,
        raw_status: int | None = None,
    ) -> List[int]:
        """Map an infeasible CP-SAT assumption core back to activity ids."""
        if raw_status is None or int(raw_status) != int(cp_model.INFEASIBLE):
            return []
        activity_ids: Set[int] = set()
        for raw_literal in solver.SufficientAssumptionsForInfeasibility():
            literal_index = int(raw_literal)
            # OR-Tools encodes a negated literal as -index-1. We currently add
            # positive assumptions, but normalize defensively for future arms.
            if literal_index < 0:
                literal_index = -literal_index - 1
            activity_id = self._assumption_activity_by_literal.get(literal_index)
            if activity_id is not None:
                activity_ids.add(int(activity_id))
        return sorted(activity_ids)

    @staticmethod
    def _read_room_candidate_limit() -> int:
        raw = os.getenv("TT_CP_ROOM_CANDIDATE_LIMIT", "").strip()
        if raw:
            try:
                return max(0, int(raw))
            except Exception:
                return 0
        return 0

    def _start_literal(self, activity_id: int, start: int) -> cp_model.BoolVar:
        """Return a lazily-created literal equivalent to ``start[a] == value``."""
        key = (int(activity_id), int(start))
        literal = self.x.get(key)
        if literal is not None:
            return literal
        if int(start) not in self.allowed_starts[int(activity_id)]:
            raise ValueError(f"Start {start} is outside activity {activity_id}'s domain")
        literal = self.m.NewBoolVar(f"x[{int(activity_id)},{int(start)}]")
        self.m.Add(self.start[int(activity_id)] == int(start)).OnlyEnforceIf(literal)
        self.m.Add(self.start[int(activity_id)] != int(start)).OnlyEnforceIf(literal.Not())
        self.x[key] = literal
        return literal

    def solve(
        self,
        time_limit_seconds: Optional[float] = None,
        workers: Optional[int] = 8,
        random_seed: Optional[int] = None,
        log_progress: bool = False,
    ):
        if self.room_mode == "decomposed":
            return self._solve_decomposed(
                time_limit_seconds=time_limit_seconds,
                workers=workers,
                random_seed=random_seed,
                log_progress=log_progress,
            )
        solver = cp_model.CpSolver()
        if time_limit_seconds is not None:
            solver.parameters.max_time_in_seconds = float(time_limit_seconds)
        if workers is not None:
            solver.parameters.num_search_workers = int(workers)
        if random_seed is not None:
            solver.parameters.random_seed = int(random_seed)
        solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH
        if log_progress:
            solver.parameters.log_search_progress = True
            solver.parameters.log_to_stdout = True
        status = solver.Solve(self.m)
        return solver, status

    def _extract_time_solution(self, solver: cp_model.CpSolver) -> Dict[int, Dict[str, object]]:
        out: Dict[int, Dict[str, object]] = {}
        for a_id, act in self.inst.activities.items():
            t = int(solver.Value(self.start[a_id]))
            day_index = t // self.S
            out[int(a_id)] = {
                "room_id": None,
                "staff_id": int(self.activity_staff[a_id]),
                "week": int(act.week),
                "day": str(self.days[day_index]),
                "slot": int(t % self.S),
                "duration": int(act.duration),
                "group_ids": [int(value) for value in act.group_ids],
                "course_id": int(act.course_id),
                "kind": str(act.kind),
            }
        return out

    def _room_job_members(self, representative: int) -> Tuple[int, ...]:
        activity = self.inst.activities[int(representative)]
        for cluster in self.clusters_by_week_kind.get(int(activity.week), {}).get(
            str(activity.kind),
            [],
        ):
            if int(representative) in {int(value) for value in cluster}:
                return tuple(sorted(int(value) for value in cluster))
        return (int(representative),)

    def _contextual_hall_cut_spec(
        self,
        certificate: RoomConflictCertificate,
        schedule: Dict[int, Dict[str, object]],
        representatives: List[int],
    ) -> Tuple[List[cp_model.IntVar], Dict[str, object]] | Tuple[None, str]:
        if certificate.certificate_type != "hall_deficiency":
            return None, "certificate_is_not_hall_deficiency"
        if certificate.week is None or certificate.day is None or certificate.slot is None:
            return None, "hall_witness_has_no_fixed_slot"
        if str(certificate.day) not in self.days:
            return None, "hall_witness_day_is_outside_master_calendar"

        certificate_payload = certificate.to_dict()
        certificate_check = check_hall_certificate(self.inst, certificate_payload)
        if not certificate_check.valid:
            return None, f"hall_certificate_check_failed:{certificate_check.errors[0]}"

        witness_rooms = {int(value) for value in certificate.candidate_room_ids}
        if any(room_id not in self.inst.rooms for room_id in witness_rooms):
            return None, "hall_witness_references_unknown_room"
        if len(representatives) <= len(witness_rooms):
            return None, "hall_witness_is_not_deficient"

        witness_week = int(certificate.week)
        witness_day = str(certificate.day)
        witness_slot = int(certificate.slot)
        term_keys: List[Tuple[int, int]] = []
        counted_starts: List[Dict[str, object]] = []
        derived_gamma_rooms: Set[int] = set()
        incumbent_starts: Dict[int, int] = {}
        covering_counts: Dict[str, int] = {}
        proven_counts: Dict[str, int] = {}
        expanded_counts: Dict[str, int] = {}
        infeasible_cluster_counts: Dict[str, int] = {}
        proof_jobs = {
            int(job["representative_activity_id"]): job
            for job in certificate.proof.get("representative_jobs", [])
            if isinstance(job, dict)
            and job.get("representative_activity_id") is not None
        }
        proof_members: Set[int] = set()

        for representative in representatives:
            activity = self.inst.activities[int(representative)]
            if int(activity.week) != witness_week:
                return None, "hall_representative_week_differs_from_witness"
            members = self._room_job_members(int(representative))
            proof_job = proof_jobs.get(int(representative))
            if proof_job is None or tuple(
                int(value) for value in proof_job.get("member_activity_ids", [])
            ) != members:
                return None, "hall_job_members_differ_from_master_cluster"
            proof_members.update(members)
            duration = max(
                int(self.inst.activities[activity_id].duration)
                for activity_id in members
            )
            proven_starts: set[int] = set()
            covering = 0
            expanded = 0
            infeasible_cluster = 0
            for start in self.allowed_starts[int(representative)]:
                day_index = int(start) // self.S
                start_slot = int(start) % self.S
                if (
                    self.days[day_index] != witness_day
                    or not start_slot <= witness_slot < start_slot + duration
                ):
                    continue
                covering += 1
                if any(
                    int(start) not in self.allowed_starts[int(member)]
                    for member in members
                ):
                    infeasible_cluster += 1
                    continue
                try:
                    candidate_domain = set(
                        candidate_rooms_for_members(
                            self.inst,
                            members,
                            week=witness_week,
                            day=witness_day,
                            start_slot=start_slot,
                            duration=duration,
                        )
                    )
                except Exception as exc:
                    return None, f"candidate_domain_error:{type(exc).__name__}"
                if candidate_domain.issubset(witness_rooms):
                    term_keys.append((int(representative), int(start)))
                    proven_starts.add(int(start))
                    derived_gamma_rooms.update(candidate_domain)
                    counted_starts.append(
                        {
                            "representative_activity_id": int(representative),
                            "member_activity_ids": [
                                int(value) for value in members
                            ],
                            "start": int(start),
                            "effective_room_ids": sorted(
                                int(value) for value in candidate_domain
                            ),
                            "domain_assumptions": {
                                "domain_rule": EFFECTIVE_DOMAIN_RULE,
                                "member_activity_ids": [
                                    int(value) for value in members
                                ],
                                "week": int(witness_week),
                                "day": str(witness_day),
                                "start_slot": int(start_slot),
                                "duration": int(duration),
                            },
                        }
                    )
                else:
                    expanded += 1

            info = schedule.get(int(representative))
            if info is None or str(info.get("day")) not in self.days:
                return None, "incumbent_representative_start_is_missing"
            incumbent_start = (
                self.days.index(str(info["day"])) * self.S + int(info["slot"])
            )
            if incumbent_start not in proven_starts:
                return None, "incumbent_domain_is_not_contained_in_hall_witness"
            incumbent_starts[int(representative)] = int(incumbent_start)
            key = str(int(representative))
            covering_counts[key] = int(covering)
            proven_counts[key] = int(len(proven_starts))
            expanded_counts[key] = int(expanded)
            infeasible_cluster_counts[key] = int(infeasible_cluster)

        rhs = len(derived_gamma_rooms)
        if len(representatives) <= rhs:
            return None, "contextual_hall_cut_does_not_exclude_incumbent"
        if len(term_keys) <= rhs:
            return None, "contextual_hall_cut_has_insufficient_terms"
        strengthened = bool(
            len(term_keys) > len(representatives)
            or rhs < max(0, len(representatives) - 1)
        )
        if not strengthened:
            return None, "no_additional_domain_monotone_start"

        counted_starts.sort(
            key=lambda item: (
                int(item["representative_activity_id"]),
                int(item["start"]),
            )
        )
        metadata: Dict[str, object] = {
            "schema_version": CONTEXTUAL_CUT_SCHEMA,
            "cut_kind": "contextual_hall",
            "certificate_id": str(certificate.certificate_id),
            "certificate_type": str(certificate.certificate_type),
            "representative_activity_ids": list(representatives),
            "witness_room_ids": sorted(witness_rooms),
            "derived_gamma_room_ids": sorted(derived_gamma_rooms),
            "room_context_id": room_context_id(self.inst),
            "week": witness_week,
            "day": witness_day,
            "slot": witness_slot,
            "rhs": int(rhs),
            "term_count": int(len(term_keys)),
            "incumbent_term_count": int(len(representatives)),
            "strengthened": bool(strengthened),
            "incumbent_starts": {
                str(activity_id): int(start)
                for activity_id, start in sorted(incumbent_starts.items())
            },
            "covering_start_counts": covering_counts,
            "proven_subset_start_counts": proven_counts,
            "excluded_expanded_domain_start_counts": expanded_counts,
            "excluded_infeasible_cluster_start_counts": infeasible_cluster_counts,
            "master_start_domains": {
                str(activity_id): sorted(
                    int(value) for value in self.allowed_starts[activity_id]
                )
                for activity_id in sorted(proof_members)
            },
            "counted_starts": counted_starts,
            "proof_rule": CONTEXTUAL_CUT_RULE,
        }
        metadata["cut_id"] = cut_id_for_inequality(counted_starts, int(rhs))
        metadata["derivation_id"] = derivation_id_for_payload(metadata)
        derivation_check = check_contextual_hall_derivation(
            self.inst,
            certificate_payload,
            metadata,
        )
        if not derivation_check.valid:
            return None, f"contextual_cut_check_failed:{derivation_check.errors[0]}"
        terms = [
            self._start_literal(int(representative), int(start))
            for representative, start in term_keys
        ]
        return terms, metadata

    def _add_room_certificate_cut(
        self,
        certificate: RoomConflictCertificate,
        schedule: Dict[int, Dict[str, object]],
    ) -> bool:
        self._last_room_cut_metadata = {}
        representatives = sorted({
            int(activity_id)
            for activity_id in certificate.representative_activity_ids
            if int(activity_id) in self.inst.activities
        })
        if not representatives:
            return False

        contextual, fallback_reason = self._contextual_hall_cut_spec(
            certificate,
            schedule,
            representatives,
        )
        if contextual is not None:
            terms, metadata = contextual, fallback_reason
            self.m.Add(sum(terms) <= int(metadata["rhs"]))
            self._last_room_cut_metadata = dict(metadata)
            return True

        # Generic room-model certificates, malformed Hall witnesses, and any
        # candidate-domain proof uncertainty retain the universally sound exact
        # incumbent nogood.
        exact_terms = []
        exact_term_specs: List[Dict[str, int]] = []
        for activity_id in representatives:
            info = schedule.get(activity_id)
            if info is None or str(info["day"]) not in self.days:
                self._last_room_cut_metadata = {
                    "cut_kind": "uncuttable",
                    "certificate_type": str(certificate.certificate_type),
                    "reason": "incumbent_representative_start_is_missing",
                }
                return False
            start = self.days.index(str(info["day"])) * self.S + int(info["slot"])
            exact_terms.append(self._start_literal(activity_id, int(start)))
            exact_term_specs.append(
                {
                    "representative_activity_id": int(activity_id),
                    "start": int(start),
                }
            )
        self.m.Add(sum(exact_terms) <= len(exact_terms) - 1)
        fallback_metadata: Dict[str, object] = {
            "schema_version": "planora.exact-room-nogood.v1",
            "cut_kind": "exact_incumbent_nogood",
            "certificate_id": str(certificate.certificate_id),
            "certificate_type": str(certificate.certificate_type),
            "representative_activity_ids": list(representatives),
            "witness_room_ids": [
                int(room_id) for room_id in certificate.candidate_room_ids
            ],
            "week": certificate.week,
            "day": certificate.day,
            "slot": certificate.slot,
            "term_count": int(len(exact_terms)),
            "rhs": int(len(exact_terms) - 1),
            "strengthened": False,
            "fallback_reason": str(fallback_reason),
            "proof_rule": "exclude-exact-incumbent-representative-starts.v1",
        }
        fallback_metadata["cut_id"] = cut_id_for_inequality(
            exact_term_specs,
            len(exact_terms) - 1,
        )
        fallback_metadata["derivation_id"] = derivation_id_for_payload(
            fallback_metadata
        )
        self._last_room_cut_metadata = fallback_metadata
        return True

    def _solve_decomposed(
        self,
        *,
        time_limit_seconds: Optional[float],
        workers: Optional[int],
        random_seed: Optional[int],
        log_progress: bool,
    ):
        started = time.perf_counter()
        budget_seconds = (
            None
            if time_limit_seconds is None
            else max(0.0, float(time_limit_seconds))
        )
        deadline = (
            None
            if budget_seconds is None
            else float(started) + float(budget_seconds)
        )
        max_rounds_raw = os.getenv("TT_DECOMPOSITION_MAX_ROUNDS", "100")
        try:
            max_rounds = max(1, int(max_rounds_raw))
        except Exception:
            max_rounds = 100
        report_rounds: List[Dict[str, object]] = []
        cuts_added = 0
        cut_kind_counts: DefaultDict[str, int] = defaultdict(int)
        last_solver = cp_model.CpSolver()

        def remaining_seconds() -> float | None:
            if deadline is None:
                return None
            return max(0.0, float(deadline) - time.perf_counter())

        def proof_status(raw_status: int, *, solution_available: bool) -> str:
            if solution_available:
                if self.use_objective and int(raw_status) == int(cp_model.OPTIMAL):
                    return "optimal"
                return "feasible_incumbent"
            if int(raw_status) == int(cp_model.INFEASIBLE):
                return "infeasible"
            if int(raw_status) == int(cp_model.MODEL_INVALID):
                return "model_invalid"
            return "no_solution"

        def objective_metrics(
            solver: cp_model.CpSolver | None,
            raw_status: int,
        ) -> Dict[str, float | None]:
            objective_value: float | None = None
            best_bound: float | None = None
            if self.use_objective and solver is not None:
                if int(raw_status) in (int(cp_model.OPTIMAL), int(cp_model.FEASIBLE)):
                    try:
                        objective_value = float(solver.ObjectiveValue())
                    except Exception:
                        objective_value = None
                try:
                    best_bound = float(solver.BestObjectiveBound())
                except Exception:
                    best_bound = None
            relative_gap: float | None = None
            if objective_value is not None and best_bound is not None:
                relative_gap = max(
                    0.0,
                    float(objective_value) - float(best_bound),
                ) / max(1.0, abs(float(objective_value)))
            return {
                "objective_value": objective_value,
                "best_objective_bound": best_bound,
                "relative_gap": relative_gap,
            }

        def store_report(
            status_name: str,
            *,
            raw_status: int = int(cp_model.UNKNOWN),
            solver_for_bounds: cp_model.CpSolver | None = None,
            solution_available: bool = False,
            extra: Dict[str, object] | None = None,
        ) -> None:
            elapsed_seconds = float(time.perf_counter() - started)
            report: Dict[str, object] = {
                "status": str(status_name),
                "room_mode_resolution": dict(self.room_mode_resolution),
                "rounds": report_rounds,
                "cuts_added": int(cuts_added),
                "cut_kind_counts": dict(sorted(cut_kind_counts.items())),
                "budget_seconds": budget_seconds,
                "elapsed_seconds": elapsed_seconds,
                "wall_seconds": elapsed_seconds,
                "deadline_overrun_seconds": (
                    0.0
                    if budget_seconds is None
                    else max(0.0, elapsed_seconds - float(budget_seconds))
                ),
                "budget_exhausted": bool(
                    deadline is not None and time.perf_counter() >= float(deadline)
                ),
                "proof_status": proof_status(
                    int(raw_status),
                    solution_available=bool(solution_available),
                ),
                "proof_scope": (
                    "decomposed_time_objective_with_exact_room_feasibility"
                    if self.use_objective
                    else "decomposed_feasibility"
                ),
                "objective_scope": (
                    "time_master" if self.use_objective else None
                ),
                **objective_metrics(solver_for_bounds, int(raw_status)),
            }
            if extra:
                report.update(extra)
            self.decomposition_report = report

        for round_index in range(max_rounds):
            remaining = remaining_seconds()
            if remaining is not None and remaining <= 0:
                store_report("TIME_LIMIT")
                return last_solver, cp_model.UNKNOWN

            room_reserve_seconds = 0.0
            master_budget_seconds = remaining
            if remaining is not None:
                room_reserve_seconds = min(
                    1.5,
                    max(0.05, float(remaining) * 0.12),
                    float(remaining) * 0.40,
                )
                master_budget_seconds = max(
                    0.0,
                    float(remaining) - float(room_reserve_seconds),
                )
            if master_budget_seconds is not None and master_budget_seconds <= 0:
                store_report("TIME_LIMIT")
                return last_solver, cp_model.UNKNOWN

            solver = cp_model.CpSolver()
            if master_budget_seconds is not None:
                solver.parameters.max_time_in_seconds = float(master_budget_seconds)
            if workers is not None:
                solver.parameters.num_search_workers = int(workers)
            if random_seed is not None:
                solver.parameters.random_seed = int(random_seed)
            solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH
            if log_progress:
                solver.parameters.log_search_progress = True
                solver.parameters.log_to_stdout = True
            master_started = time.perf_counter()
            master_status = int(solver.Solve(self.m))
            master_elapsed_seconds = float(time.perf_counter() - master_started)
            last_solver = solver
            master_metrics = objective_metrics(solver, int(master_status))
            round_row: Dict[str, object] = {
                "round": int(round_index + 1),
                "remaining_at_start_seconds": remaining,
                "master_budget_seconds": master_budget_seconds,
                "room_reserve_seconds": float(room_reserve_seconds),
                "master_status": str(cp_model.CpSolverStatus(master_status)),
                "master_seconds": float(solver.WallTime()),
                "master_elapsed_seconds": master_elapsed_seconds,
                "master_proof_status": proof_status(
                    int(master_status),
                    solution_available=master_status
                    in (int(cp_model.OPTIMAL), int(cp_model.FEASIBLE)),
                ),
                **master_metrics,
            }
            report_rounds.append(round_row)
            if master_status not in (int(cp_model.OPTIMAL), int(cp_model.FEASIBLE)):
                store_report(
                    str(cp_model.CpSolverStatus(master_status)),
                    raw_status=int(master_status),
                    solver_for_bounds=solver,
                )
                return solver, master_status

            schedule = self._extract_time_solution(solver)
            room_setup_started = time.perf_counter()
            room_subproblem = ExactRoomSubproblem(
                self.inst,
                schedule,
                clusters_by_week_kind=self.clusters_by_week_kind,
                repeat_pattern_pairs=self._repeat_week_pattern_pairs(),
                optimize=self.use_objective,
            )
            round_row["room_setup_seconds"] = float(
                time.perf_counter() - room_setup_started
            )
            remaining = remaining_seconds()
            if remaining is not None and remaining <= 0:
                store_report(
                    "TIME_LIMIT",
                    raw_status=int(master_status),
                    solver_for_bounds=solver,
                )
                return solver, cp_model.UNKNOWN
            room_result = room_subproblem.solve(
                time_limit_seconds=remaining,
                workers=1,
                random_seed=random_seed,
            )
            round_row["room_subproblem"] = room_result.to_dict()
            if room_result.feasible:
                self._decomposed_room_assignment = dict(room_result.assignments)
                store_report(
                    "FEASIBLE",
                    raw_status=int(master_status),
                    solver_for_bounds=solver,
                    solution_available=True,
                    extra={
                        "room_objective_value": room_result.objective_value,
                        "room_best_objective_bound": room_result.best_objective_bound,
                        "room_relative_gap": room_result.relative_gap,
                        "room_proof": dict(room_result.proof),
                    },
                )
                return solver, master_status
            if int(room_result.status) == int(cp_model.UNKNOWN):
                store_report(
                    "ROOM_SUBPROBLEM_TIME_LIMIT",
                    raw_status=int(master_status),
                    solver_for_bounds=solver,
                )
                return solver, cp_model.UNKNOWN

            added_this_round = 0
            room_cuts: List[Dict[str, object]] = []
            for certificate in room_result.certificates:
                if self._add_room_certificate_cut(certificate, schedule):
                    added_this_round += 1
                    cut_metadata = dict(self._last_room_cut_metadata)
                    room_cuts.append(cut_metadata)
                    cut_kind = str(cut_metadata.get("cut_kind", "unknown"))
                    cut_kind_counts[cut_kind] += 1
            cuts_added += added_this_round
            round_row["cuts_added"] = int(added_this_round)
            round_row["room_cuts"] = room_cuts
            if added_this_round == 0:
                store_report(
                    "UNCUTTABLE_CERTIFICATE",
                    raw_status=int(master_status),
                    solver_for_bounds=solver,
                )
                return solver, cp_model.UNKNOWN

        store_report("ROUND_LIMIT")
        return last_solver, cp_model.UNKNOWN

    def extract_solution(self, solver: cp_model.CpSolver):
        inst = self.inst
        out: Dict[int, Dict[str, object]] = {}

        chosen_room: Dict[int, Optional[int]] = {}
        if self.room_mode == "cp_rooms":
            for a_id in inst.activities.keys():
                rid = None
                for r in self.allowed_rooms.get(a_id, []):
                    b = self.room_sel.get((a_id, r))
                    if b is not None and solver.BooleanValue(b):
                        rid = r
                        break
                chosen_room[a_id] = rid
        elif self.room_mode == "decomposed":
            if len(self._decomposed_room_assignment) != len(inst.activities):
                raise ValueError("No complete exact room assignment is available")
            chosen_room = {
                int(a_id): int(self._decomposed_room_assignment[int(a_id)])
                for a_id in inst.activities
            }
        else:
            for a_id in inst.activities.keys():
                chosen_room[a_id] = None

        for a_id, act in inst.activities.items():
            t = solver.Value(self.start[a_id])
            day_index = t // self.S
            slot = t % self.S
            out[a_id] = {
                "room_id": chosen_room[a_id],
                "staff_id": self.activity_staff[a_id],
                "week": act.week,
                "day": self.days[day_index],
                "slot": slot,
                "duration": act.duration,
                "group_ids": list(act.group_ids),
                "course_id": act.course_id,
                "kind": act.kind,
            }

        if self.room_mode == "greedy":
            assign_rooms_greedily(inst, out)

        return out

    # ---------- internals ----------

    def _find_day_index(self, prefix: str) -> Optional[int]:
        p = prefix.upper()
        for i, d in enumerate(self.inst.days):
            if d.upper().startswith(p):
                return i
        return None

    def _is_block_prof(self, staff) -> bool:
        return bool(getattr(staff, "blocks_only", False) or getattr(staff, "prefers_block", False) or getattr(staff, "is_block_prof", False))

    def _hard_flag(self, name: str, default: bool = True) -> bool:
        flags = getattr(self.inst, "hard_constraints", {}) or {}
        if not isinstance(flags, dict):
            return default
        raw = flags.get(name, default)
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return default
        return str(raw).strip().lower() not in ("0", "false", "no")

    def _validate_staff_assignments(self) -> None:
        inst = self.inst
        errs: list[str] = []
        for a in inst.activities.values():
            if a.kind == "LEC":
                sid = a.prof_id
                s = inst.staff.get(sid)
                if s is None:
                    errs.append(f"activity {a.id}: missing professor staff id {sid}")
                    continue
                if not s.is_prof:
                    errs.append(f"activity {a.id}: LEC must be taught by a professor (staff {sid})")
                if a.course_id not in getattr(s, "can_teach_courses", set()):
                    errs.append(f"activity {a.id}: professor {sid} cannot teach course {a.course_id}")
            else:
                sid = a.ta_id
                s = inst.staff.get(sid)
                if s is None:
                    errs.append(f"activity {a.id}: missing TA staff id {sid}")
                    continue
                if s.is_prof:
                    errs.append(f"activity {a.id}: {a.kind} must be taught by a TA (staff {sid})")
                if a.course_id not in getattr(s, "can_teach_courses", set()):
                    errs.append(f"activity {a.id}: TA {sid} cannot teach course {a.course_id}")
        if errs:
            raise ValueError("Invalid staff assignment/competency: " + "; ".join(errs))

    def _validate_block_professor_rules(self) -> None:
        if not self._hard_flag("enforce_block_professor_rules", True):
            return
        inst = self.inst
        errs: list[str] = []

        # Group LEC activities by (prof, course, week)
        by_scw: DefaultDict[Tuple[int, int, int], List[int]] = defaultdict(list)
        for a_id, a in inst.activities.items():
            if a.kind == "LEC":
                by_scw[(a.prof_id, a.course_id, a.week)].append(a_id)

        for (sid, c_id, w), act_ids in by_scw.items():
            s = inst.staff.get(sid)
            if s is None or not self._is_block_prof(s):
                continue
            total = sum(inst.activities[a].duration for a in act_ids)
            if not (2 <= total <= 3):
                errs.append(f"block-prof {sid} course {c_id} week {w}: total lecture slots {total} not in [2,3]")
        if errs:
            raise ValueError("Block-professor rule violation: " + "; ".join(errs))

    def _validate_semester_rules(self) -> None:
        """
        Generator/semester invariants used by the solver:
        - Activity totals must match the course metadata (lecture/tutorial slot totals,
          lab session counts and lab durations).
        - Week-1 must be lectures-only; tutorials/labs in the first week are rejected.
        """
        inst = self.inst
        first_week = inst.weeks[0] if inst.weeks else None

        # Work out which groups belong to each course (prefer the explicit share list)
        course_groups: dict[int, list[int]] = {}
        for c_id, c in inst.courses.items():
            gids = list(c.share_lecture_group_ids) if c.share_lecture_group_ids else [
                g_id for g_id, g in inst.groups.items() if c_id in g.course_ids
            ]
            course_groups[c_id] = gids

        # Validate per-course totals against metadata (treat lecture/tutorial counts as slot totals).
        errs: list[str] = []
        by_course_kind: dict[tuple[int, str], list] = {}
        for a in inst.activities.values():
            by_course_kind.setdefault((a.course_id, a.kind), []).append(a)

        if self._hard_flag("enforce_course_totals", True):
            for c_id, c in inst.courses.items():
                lecs = by_course_kind.get((c_id, "LEC"), [])
                tuts = by_course_kind.get((c_id, "TUT"), [])
                labs = by_course_kind.get((c_id, "LAB"), [])

                lec_slots = sum(a.duration for a in lecs)
                tut_slots_by_group: dict[int, int] = {}
                for a in tuts:
                    for g in a.group_ids:
                        tut_slots_by_group[g] = tut_slots_by_group.get(g, 0) + a.duration
                lab_sessions = len(labs)

                if c.structure_type == "LAB_ONLY":
                    if lecs or tuts:
                        errs.append(f"course {c_id}: LAB_ONLY must not include LEC/TUT activities")

                if int(getattr(c, "lecture_count", 0) or 0) != lec_slots:
                    errs.append(f"course {c_id}: lecture slots {lec_slots} != lecture_count {c.lecture_count}")

                expected_tut = int(getattr(c, "tutorial_count", 0) or 0)
                for g_id in course_groups.get(c_id, []):
                    got = tut_slots_by_group.get(g_id, 0)
                    if expected_tut != got:
                        errs.append(f"course {c_id} group {g_id}: tutorial slots {got} != tutorial_count {expected_tut}")

                expected_lab_weeks = int(getattr(c, "lab_weeks", 0) or 0)
                if expected_lab_weeks != lab_sessions:
                    errs.append(f"course {c_id}: lab sessions {lab_sessions} != lab_weeks {expected_lab_weeks}")
                if labs:
                    expected_dur = int(getattr(c, "lab_duration", 0) or 0)
                    for a in labs:
                        if a.duration != expected_dur:
                            errs.append(f"course {c_id}: LAB a{a.id} duration {a.duration} != lab_duration {expected_dur}")

        if errs:
            raise ValueError("Instance violates course totals: " + "; ".join(errs))

        # Enforce: week-1 contains lectures only (configurable).
        if self._hard_flag("week1_lectures_only", True) and first_week is not None:
            bad_first = [
                (a.id, a.course_id, a.kind) for a in inst.activities.values()
                if a.week == first_week and a.kind in ("TUT", "LAB")
            ]
            if bad_first:
                kinds = sorted({k for _, _, k in bad_first})
                raise ValueError(
                    f"Week {first_week} must be lectures only; "
                    f"found {len(bad_first)} tutorial/lab activities (kinds={kinds})."
                )


    def _precompute(self) -> None:
        inst = self.inst

        self._validate_semester_rules()
        self._validate_staff_assignments()
        self._validate_block_professor_rules()

        # staff per activity: professors teach LEC, TAs teach TUT/LAB by convention
        for a_id, act in inst.activities.items():
            self.activity_staff[a_id] = act.prof_id if act.kind == "LEC" else act.ta_id
            for resource_id in getattr(act, "resource_ids", []) or []:
                if int(resource_id) not in getattr(inst, "generic_resources", {}) and getattr(inst, "generic_resources", {}):
                    raise ValueError(f"Activity {a_id} references unknown generic resource {int(resource_id)}")

        # room pools
        for r_id, r in inst.rooms.items():
            if r.room_type == "LECTURE":
                self.lecture_room_ids.append(r_id)
            elif r.room_type == "TUTORIAL":
                self.tutorial_room_ids.append(r_id)
            elif r.room_type in ("SPECIALIZED_LAB", "COMPUTER_LAB"):
                self.lab_room_ids.append(r_id)
                if r.room_type == "SPECIALIZED_LAB":
                    for tag in getattr(r, "specialization_tags", []) or []:
                        self.spec_rooms_by_tag.setdefault(tag, []).append(r_id)

        # allowed starts: respect staff available days and remove Sundays entirely
        sunday_range = None
        if self.sunday_idx is not None:
            lo = self.sunday_idx * self.S
            hi = lo + self.S - 1
            sunday_range = (lo, hi)

        week_set = set(int(w) for w in self.weeks)
        for a_id, act in inst.activities.items():
            sid = self.activity_staff[a_id]
            staff = inst.staff[sid]
            available_days = set(getattr(staff, "available_days", self.days))
            available_weeks = getattr(staff, "available_weeks", None)
            if available_weeks is None:
                allowed_weeks = set(week_set)
            else:
                allowed_weeks = {int(w) for w in available_weeks if int(w) in week_set}
                if not allowed_weeks:
                    allowed_weeks = set(week_set)
            allowed_day_idx: Set[int] = {i for i, d in enumerate(self.days) if d in available_days}

            if int(act.week) not in allowed_weeks:
                raise ValueError(
                    f"Activity {a_id} week {int(act.week)} is outside staff "
                    f"{sid} available weeks {sorted(allowed_weeks)}"
                )

            max_start_slot = self.S - act.duration
            if max_start_slot < 0:
                raise ValueError(f"Activity {a_id} duration {act.duration} exceeds day slots {self.S}")

            forbidden_starts = {
                (str(pair[0]), int(pair[1]))
                for pair in (getattr(inst, "activity_unavailability", {}) or {}).get(
                    int(a_id), set()
                )
                if isinstance(pair, (list, tuple)) and len(pair) == 2
            }
            policy = getattr(inst, "institutional_policy", {}) or {}
            configured_starts = policy.get("standard_start_slots", [])
            if isinstance(configured_starts, dict):
                configured_starts = configured_starts.get(
                    str(act.kind),
                    configured_starts.get("default", []),
                )
            standard_starts = {
                int(value) for value in (configured_starts or [])
            }
            allowed_day_slots = policy.get("allowed_day_slots", {}) or {}
            times: List[int] = []
            for d_idx in range(self.D):
                if d_idx not in allowed_day_idx:
                    continue
                if calendar_slot_blocked(inst, week=int(act.week), day=str(self.days[d_idx])):
                    continue
                for s in range(max_start_slot + 1):
                    if (
                        self._hard_flag("enforce_standard_start_slots", False)
                        and standard_starts
                        and int(s) not in standard_starts
                    ):
                        continue
                    configured_day_slots = allowed_day_slots.get(
                        str(self.days[d_idx]),
                        allowed_day_slots.get("default"),
                    )
                    if configured_day_slots is not None and int(s) not in {
                        int(value) for value in configured_day_slots
                    }:
                        continue
                    if (str(self.days[d_idx]), int(s)) in forbidden_starts:
                        continue
                    if not generic_resources_available(
                        inst,
                        getattr(act, "resource_ids", []) or [],
                        day=str(self.days[d_idx]),
                        start_slot=int(s),
                        dur=int(act.duration),
                    ):
                        continue
                    t = d_idx * self.S + s
                    if sunday_range and sunday_range[0] <= t <= sunday_range[1]:
                        continue
                    times.append(t)

            lock = getattr(inst, "locked_activities", {}) or {}
            fixed = lock.get(a_id) if isinstance(lock, dict) else None
            if fixed and isinstance(fixed, dict) and "day" in fixed and "slot" in fixed:
                fixed_day = str(fixed["day"])
                fixed_slot = int(fixed["slot"])
                if fixed_day not in self.days:
                    raise ValueError(f"Locked activity {a_id}: day '{fixed_day}' is not in inst.days")
                if not (0 <= fixed_slot <= max_start_slot):
                    raise ValueError(f"Locked activity {a_id}: slot {fixed_slot} invalid for duration {act.duration}")
                fixed_t = self.days.index(fixed_day) * self.S + fixed_slot
                if fixed_t not in times:
                    raise ValueError(f"Locked activity {a_id}: fixed time {fixed_day}@{fixed_slot} is not allowed")
                times = [fixed_t]
            if not times:
                raise ValueError(f"No allowed starts for activity {a_id}")
            self.allowed_starts[a_id] = times

        # clusters for LEC, TUT, LAB
        self.clusters_by_week_kind = self._compute_clusters()

        # optional CP-room list
        if self.room_mode == "cp_rooms":
            self._compute_allowed_rooms()

    def _compute_clusters(self) -> Dict[int, Dict[str, List[List[int]]]]:
        """
        Build clusters by week and kind.

        Sources:
          1) course.share_lecture_group_ids for LEC across single-group activities
          2) activity.cluster_key (optional, attach at generation time) for cross-course, cross-major grouping
             Works for LEC/TUT/LAB. If absent, nothing to cluster from this source.
        """
        inst = self.inst
        out: Dict[int, Dict[str, List[List[int]]]] = {w: {"LEC": [], "TUT": [], "LAB": []} for w in self.weeks}

        # single-group activities bucketed by (course, kind, week, group_id)
        by_ckwg: DefaultDict[Tuple[int, str, int, int], List[int]] = defaultdict(list)
        for a_id, a in inst.activities.items():
            if len(a.group_ids) == 1:
                by_ckwg[(a.course_id, a.kind, a.week, a.group_ids[0])].append(a_id)

        # course-level lecture sharing
        for c_id, course in inst.courses.items():
            shared = getattr(course, "share_lecture_group_ids", None)
            if shared:
                shared_set = set(shared)
                by_week: DefaultDict[int, List[int]] = defaultdict(list)
                for (cc, k, w, g), bucket in by_ckwg.items():
                    if cc != c_id or k != "LEC":
                        continue
                    if g in shared_set:
                        by_week[w].extend(bucket)
                for w, members in by_week.items():
                    if len(members) >= 2:
                        out[w]["LEC"].append(sorted(members))

        # activity-level cluster keys for any kind
        by_key_week_kind: DefaultDict[Tuple[str, int, str], List[int]] = defaultdict(list)
        for a_id, a in inst.activities.items():
            key = getattr(a, "cluster_key", None)
            if key:
                by_key_week_kind[(str(key), a.week, a.kind)].append(a_id)
        for (key, w, kind), members in by_key_week_kind.items():
            if len(members) >= 2:
                out[w][kind].append(sorted(members))

        # dedup per (w, kind)
        for w in out:
            for kind in ("LEC", "TUT", "LAB"):
                seen: Set[Tuple[int, ...]] = set()
                uniq: List[List[int]] = []
                for cluster in out[w][kind]:
                    t = tuple(cluster)
                    if t not in seen:
                        seen.add(t)
                        uniq.append(cluster)
                out[w][kind] = uniq

        return out

    def _compute_allowed_rooms(self) -> None:
        inst = self.inst

        def required_capacity(act_id: int) -> int:
            gids = inst.activities[act_id].group_ids
            return capacity_required(inst, gids)

        def trim_room_candidates(a_id: int, rooms: List[int], need: int, kind: str) -> List[int]:
            locks = getattr(inst, "locked_activities", {}) or {}
            locked_room = None
            fixed = locks.get(a_id) if isinstance(locks, dict) else None
            if isinstance(fixed, dict) and fixed.get("room_id") is not None:
                try:
                    locked_room = int(fixed["room_id"])
                except Exception:
                    locked_room = None
            if locked_room is not None:
                if int(locked_room) not in {int(room_id) for room_id in rooms}:
                    raise ValueError(
                        f"Locked activity {a_id}: room_id {locked_room} is not eligible"
                    )
                # A singleton room domain removes all redundant room literals
                # from exact LNS/incremental models instead of creating and then
                # constraining one literal for every institutional room.
                return [int(locked_room)]

            limit = int(getattr(self, "room_candidate_limit", 0) or 0)
            if limit <= 0 or len(rooms) <= limit:
                return list(rooms)

            def rank(room_id: int) -> tuple[int, int, int]:
                room = inst.rooms[int(room_id)]
                if kind == "TUT":
                    type_rank = 0 if room.room_type == "TUTORIAL" else 1
                elif kind == "LAB":
                    type_rank = 0 if room.room_type == "COMPUTER_LAB" else 1
                else:
                    type_rank = 0
                return (int(type_rank), max(0, int(room.capacity) - int(need)), int(room_id))

            ranked = sorted((int(r_id) for r_id in rooms), key=rank)
            if len(ranked) <= limit:
                return ranked

            # Keep a few best-fit rooms, then rotate through the rest so large
            # batches of similar activities do not all fight for the same rooms.
            fixed_prefix = max(2, min(6, int(limit) // 4))
            selected: List[int] = list(ranked[:fixed_prefix])
            pool = [r_id for r_id in ranked if r_id not in set(selected)]
            remaining = max(0, int(limit) - len(selected))
            if pool and remaining > 0:
                start = (int(a_id) * 7) % len(pool)
                for offset in range(min(remaining, len(pool))):
                    selected.append(pool[(start + offset) % len(pool)])
            return list(dict.fromkeys(selected))

        for a_id, act in inst.activities.items():
            rooms: List[int] = []
            need = required_capacity(a_id)
            enforce_capacity = self._hard_flag("enforce_room_capacity", True)
            if act.kind == "LAB":
                req = getattr(act, "requires_specialization", None)
                lab_candidates = [r_id for r_id, r in inst.rooms.items() if r.room_type in ("SPECIALIZED_LAB", "COMPUTER_LAB")]
                if req:
                    for r_id in lab_candidates:
                        tags = getattr(inst.rooms[r_id], "specialization_tags", []) or []
                        if req in tags and (
                            not enforce_capacity or inst.rooms[r_id].capacity >= need
                        ):
                            rooms.append(r_id)
                    if not rooms:
                        raise ValueError(f"Activity {a_id} requires specialized lab '{req}' but no matching room exists")
                else:
                    rooms = [
                        r_id
                        for r_id in lab_candidates
                        if not enforce_capacity or inst.rooms[r_id].capacity >= need
                    ]
            elif act.kind == "TUT":
                rooms = [
                    r_id
                    for r_id, r in inst.rooms.items()
                    if r.room_type in ("TUTORIAL", "LECTURE")
                    and (not enforce_capacity or r.capacity >= need)
                ]
            else:  # LEC
                rooms = [
                    r_id
                    for r_id, r in inst.rooms.items()
                    if r.room_type == "LECTURE"
                    and (not enforce_capacity or r.capacity >= need)
                ]

            if not rooms:
                raise ValueError(f"No eligible rooms for activity {a_id} ({act.kind})")
            self.allowed_rooms[a_id] = trim_room_candidates(
                int(a_id),
                rooms,
                int(need),
                str(act.kind),
            )

    def _repeat_week_pattern_key(self, a_id: int) -> Tuple[int, str, int, Tuple[int, ...], int]:
        act = self.inst.activities[int(a_id)]
        return (
            int(act.course_id),
            str(act.kind),
            int(self.activity_staff[int(a_id)]),
            tuple(sorted(int(g) for g in act.group_ids)),
            int(act.duration),
        )

    def _repeat_week_pattern_pairs(self) -> List[Tuple[int, int]]:
        """
        Pair recurring non-first-week activities by course/kind/staff/groups.

        The first week is intentionally excluded because this scheduler commonly
        models it as a lecture-only introduction week. If a recurring key has
        multiple sessions in a week, the sorted nth session is paired with the
        sorted nth session in later weeks.
        """
        if not self.weeks:
            return []
        first_week = min(int(w) for w in self.weeks)
        by_key_week: DefaultDict[
            Tuple[int, str, int, Tuple[int, ...], int],
            DefaultDict[int, List[int]],
        ] = defaultdict(lambda: defaultdict(list))
        for a_id, act in self.inst.activities.items():
            if int(act.week) == int(first_week):
                continue
            if getattr(act, "cluster_key", None):
                continue
            key = self._repeat_week_pattern_key(int(a_id))
            by_key_week[key][int(act.week)].append(int(a_id))

        pairs: List[Tuple[int, int]] = []
        repeat_weeks = [int(w) for w in self.weeks if int(w) != int(first_week)]
        for by_week in by_key_week.values():
            weeks = sorted(int(w) for w, ids in by_week.items() if ids)
            if len(weeks) < 2:
                continue
            ordered = {int(w): sorted(int(a_id) for a_id in by_week[int(w)]) for w in weeks}
            max_occurrences = max(len(ids) for ids in ordered.values())
            for occ_idx in range(max_occurrences):
                if any(occ_idx >= len(ordered.get(int(week), [])) for week in repeat_weeks):
                    continue
                leader: int | None = None
                for week in repeat_weeks:
                    ids = ordered[week]
                    current = int(ids[occ_idx])
                    if leader is None:
                        leader = current
                    else:
                        pairs.append((int(leader), int(current)))
        return pairs

    def _build_variables(self) -> None:
        m = self.m
        inst = self.inst

        for a_id, act in inst.activities.items():
            allowed = self.allowed_starts[a_id]

            s_var = m.NewIntVarFromDomain(
                cp_model.Domain.FromValues([int(value) for value in allowed]),
                f"start[{a_id}]",
            )
            self.start[a_id] = s_var
            self._dec_start_ints.append(s_var)
            if self.use_objective:
                picks: List[cp_model.BoolVar] = []
                for t in allowed:
                    literal = m.NewBoolVar(f"x[{a_id},{t}]")
                    self.x[(int(a_id), int(t))] = literal
                    picks.append(literal)
                m.AddExactlyOne(picks)
                m.Add(s_var == sum(int(t) * self.x[(int(a_id), int(t))] for t in allowed))

            e_var = m.NewIntVar(0, self.T_week, f"end[{a_id}]")
            m.Add(e_var == s_var + act.duration)
            iv = m.NewIntervalVar(s_var, act.duration, e_var, f"iv[{a_id}]")
            self.interval[a_id] = iv

            for g_id in act.group_ids:
                self.group_intervals_by_week.setdefault((g_id, act.week), []).append(iv)
            sid = self.activity_staff[a_id]
            self.staff_intervals_by_week.setdefault((sid, act.week), []).append(iv)

        if self.room_mode == "cp_rooms":
            for a_id in inst.activities.keys():
                for r in self.allowed_rooms[a_id]:
                    b = m.NewBoolVar(f"room[{a_id}]={r}")
                    self.room_sel[(a_id, r)] = b
                    self._dec_room_bools.append(b)

    def _add_constraints(self) -> None:
        m = self.m
        inst = self.inst

        # resource NoOverlap
        for (g_id, w), ivs in self.group_intervals_by_week.items():
            if len(ivs) > 1:
                m.AddNoOverlap(ivs)
        for (s_id, w), ivs in self.staff_intervals_by_week.items():
            if len(ivs) > 1:
                m.AddNoOverlap(ivs)
        if getattr(inst, "generic_resources", None):
            for res_id, resource in inst.generic_resources.items():
                cap = max(1, int(getattr(resource, "capacity", 1) or 1))
                for w in self.weeks:
                    intervals = [
                        self.interval[int(a_id)]
                        for a_id, act in inst.activities.items()
                        if int(act.week) == int(w)
                        and int(res_id)
                        in {int(value) for value in (getattr(act, "resource_ids", []) or [])}
                    ]
                    if intervals:
                        m.AddCumulative(intervals, [1] * len(intervals), int(cap))

        if self._hard_flag("enforce_block_professor_rules", True):
            # Block staff: at most two distinct days per week
            for s_id, staff in inst.staff.items():
                if not self._is_block_prof(staff):
                    continue
                for w in self.weeks:
                    y_day: Dict[int, cp_model.BoolVar] = {d: m.NewBoolVar(f"workday[{s_id},{w},{d}]")
                                                          for d in range(self.D)}
                    for a_id, act in inst.activities.items():
                        if act.week != w or self.activity_staff[a_id] != s_id:
                            continue
                        for t in self.allowed_starts[a_id]:
                            d_idx = t // self.S
                            m.Add(y_day[d_idx] >= self._start_literal(a_id, t))
                    m.Add(sum(y_day.values()) <= 2)

            # Block-only professor lecture blocks (per course/week): single 2–3-slot contiguous block on one day.
            for s_id, staff in inst.staff.items():
                if not getattr(staff, "blocks_only", False):
                    continue
                for w in self.weeks:
                    # courses with lectures taught by this professor in this week
                    courses_here = {
                        act.course_id
                        for act in inst.activities.values()
                        if act.week == w and act.kind == "LEC" and act.prof_id == s_id
                    }
                    for c_id in courses_here:
                        lec_ids = [
                            a_id for a_id, act in inst.activities.items()
                            if act.week == w and act.kind == "LEC" and act.prof_id == s_id and act.course_id == c_id
                        ]
                        if not lec_ids:
                            continue

                        occ: Dict[Tuple[int, int], cp_model.BoolVar] = {
                            (d, s): m.NewBoolVar(f"blk_occ[{s_id},{c_id},{w},{d},{s}]")
                            for d in range(self.D) for s in range(self.S)
                        }
                        for (d, s), b in occ.items():
                            terms: List[cp_model.BoolVar] = []
                            for a_id in lec_ids:
                                act = inst.activities[a_id]
                                for t in self.allowed_starts[a_id]:
                                    d_idx = t // self.S
                                    s0 = t % self.S
                                    if d_idx != d:
                                        continue
                                    if s0 <= s < s0 + act.duration:
                                        literal = self._start_literal(a_id, t)
                                        terms.append(literal)
                                        m.Add(b >= literal)
                            if terms:
                                m.Add(sum(terms) >= b)
                            else:
                                m.Add(b == 0)

                        day_used = {d: m.NewBoolVar(f"blk_day[{s_id},{c_id},{w},{d}]") for d in range(self.D)}
                        for d in range(self.D):
                            day_terms = [occ[(d, s)] for s in range(self.S)]
                            for s in range(self.S):
                                m.Add(day_used[d] >= occ[(d, s)])
                            m.Add(sum(day_terms) >= day_used[d])
                        m.Add(sum(day_used.values()) == 1)

                        total_slots_terms: List[cp_model.LinearExpr] = []
                        for a_id in lec_ids:
                            act = inst.activities[a_id]
                            for t in self.allowed_starts[a_id]:
                                total_slots_terms.append(act.duration * self._start_literal(a_id, t))
                        total_slots = sum(total_slots_terms)
                        m.Add(total_slots >= 2)
                        m.Add(total_slots <= 3)
                        m.Add(sum(occ.values()) == total_slots)

                        start_block: Dict[Tuple[int, int], cp_model.BoolVar] = {
                            (d, s): m.NewBoolVar(f"blk_start[{s_id},{c_id},{w},{d},{s}]")
                            for d in range(self.D) for s in range(self.S)
                        }
                        for d in range(self.D):
                            # slot 0
                            m.Add(start_block[(d, 0)] <= occ[(d, 0)])
                            m.Add(start_block[(d, 0)] >= occ[(d, 0)])
                            for s in range(1, self.S):
                                cur = occ[(d, s)]
                                prev = occ[(d, s - 1)]
                                sb = start_block[(d, s)]
                                m.Add(sb <= cur)
                                m.Add(sb + prev <= 1)
                                m.Add(sb + prev >= cur)
                        m.Add(sum(start_block.values()) == 1)

        # Optional weekly load cap
        if self._hard_flag("enforce_staff_weekly_caps", True):
            for s_id, staff in inst.staff.items():
                cap = getattr(staff, "max_slots_per_week", None)
                if cap is None:
                    continue
                for w in self.weeks:
                    terms: List[cp_model.LinearExpr] = []
                    for a_id, act in inst.activities.items():
                        if act.week != w or self.activity_staff[a_id] != s_id:
                            continue
                        for t in self.allowed_starts[a_id]:
                            terms.append(act.duration * self._start_literal(a_id, t))
                    if terms:
                        m.Add(sum(terms) <= int(cap))

        # Optional daily load cap
        if self._hard_flag("enforce_staff_daily_caps", True):
            for s_id, staff in inst.staff.items():
                cap = getattr(staff, "max_slots_per_day", None)
                if cap is None:
                    continue
                for w in self.weeks:
                    for d_idx in range(self.D):
                        terms: List[cp_model.LinearExpr] = []
                        for a_id, act in inst.activities.items():
                            if act.week != w or self.activity_staff[a_id] != s_id:
                                continue
                            for t in self.allowed_starts[a_id]:
                                if (t // self.S) == d_idx:
                                    terms.append(act.duration * self._start_literal(a_id, t))
                        if terms:
                            m.Add(sum(terms) <= int(cap))

        # Precedence rules across activities.
        if self._hard_flag("enforce_precedence_rules", True):
            for raw_rule in getattr(inst, "precedence_rules", []) or []:
                if not isinstance(raw_rule, dict):
                    continue
                try:
                    before_id = int(raw_rule.get("before_activity_id"))
                    after_id = int(raw_rule.get("after_activity_id"))
                except Exception:
                    continue
                if before_id not in self.start or after_id not in self.start:
                    continue
                before_act = inst.activities[before_id]
                after_act = inst.activities[after_id]
                min_gap = int(raw_rule.get("min_gap_slots", 0) or 0)
                if int(before_act.week) > int(after_act.week):
                    raise ValueError(
                        f"Precedence impossible: A{before_id} is in a later week than A{after_id}"
                    )
                if int(before_act.week) == int(after_act.week):
                    m.Add(
                        self.start[after_id]
                        >= self.start[before_id] + int(before_act.duration) + int(min_gap)
                    )

        # Cluster equal-start constraints
        for w in self.weeks:
            for kind in ("LEC", "TUT", "LAB"):
                for cluster in self.clusters_by_week_kind[w][kind]:
                    leader = cluster[0]
                    for a in cluster[1:]:
                        m.Add(self.start[a] == self.start[leader])

        repeat_pattern_pairs = self._repeat_week_pattern_pairs()
        if self._hard_flag("force_repeat_weekly_pattern", False):
            for leader, follower in repeat_pattern_pairs:
                m.Add(self.start[int(follower)] == self.start[int(leader)])

        clustered_ids = {
            int(a_id)
            for week_clusters in self.clusters_by_week_kind.values()
            for kind_clusters in week_clusters.values()
            for cluster in kind_clusters
            for a_id in cluster
        }
        itc2007 = self._itc2007_metadata()
        if itc2007 is not None:
            self._add_itc2007_course_symmetry(itc2007, clustered_ids=clustered_ids)
        else:
            # For general-purpose instances, activity labels are exchangeable
            # only when their complete modeled domains match and no explicit
            # relation gives an activity a distinct role. This avoids cutting
            # valid schedules when two otherwise-similar sessions have different
            # availability, locks, room eligibility, or cross-activity rules.
            identity_sensitive_ids: Set[int] = set()
            for raw_rule in getattr(inst, "precedence_rules", []) or []:
                if not isinstance(raw_rule, dict):
                    continue
                for field in ("before_activity_id", "after_activity_id"):
                    try:
                        identity_sensitive_ids.add(int(raw_rule[field]))
                    except (KeyError, TypeError, ValueError):
                        continue
            for constraint in getattr(inst, "distribution_constraints", []) or []:
                identity_sensitive_ids.update(
                    int(value) for value in constraint.activity_ids
                )
            if self._hard_flag("force_repeat_weekly_pattern", False):
                for leader, follower in repeat_pattern_pairs:
                    identity_sensitive_ids.update((int(leader), int(follower)))

            locks = getattr(inst, "locked_activities", {}) or {}
            by_symmetry_key: DefaultDict[Tuple[object, ...], List[int]] = defaultdict(list)
            for a_id, act in inst.activities.items():
                if int(a_id) in clustered_ids or int(a_id) in identity_sensitive_ids:
                    continue
                fixed = locks.get(int(a_id)) if isinstance(locks, dict) else None
                key = (
                    int(act.course_id),
                    str(act.kind),
                    int(act.week),
                    int(self.activity_staff[a_id]),
                    tuple(sorted(int(g) for g in act.group_ids)),
                    int(act.duration),
                    str(act.requires_specialization or ""),
                    tuple(sorted(int(value) for value in (act.resource_ids or []))),
                    str(act.cluster_key or ""),
                    tuple(int(value) for value in self.allowed_starts[int(a_id)]),
                    tuple(int(value) for value in self.allowed_rooms.get(int(a_id), [])),
                    tuple(
                        sorted(
                            (str(field), repr(value))
                            for field, value in dict(fixed or {}).items()
                        )
                    ),
                )
                by_symmetry_key[key].append(int(a_id))
            for act_ids in by_symmetry_key.values():
                ordered = sorted(act_ids)
                for prev_id, next_id in zip(ordered, ordered[1:]):
                    m.Add(self.start[prev_id] <= self.start[next_id])

        # Room-count guards per slot with tutorial support
        num_lec = len(self.lecture_room_ids)
        num_tut = len(self.tutorial_room_ids)
        num_lab = len(self.lab_room_ids)

        # followers of clusters should not count twice
        follower_ids_by_week_kind: Dict[int, Dict[str, Set[int]]] = {w: {"LEC": set(), "TUT": set(), "LAB": set()}
                                                                     for w in self.weeks}
        for w in self.weeks:
            for kind in ("LEC", "TUT", "LAB"):
                for cluster in self.clusters_by_week_kind[w][kind]:
                    follower_ids_by_week_kind[w][kind].update(cluster[1:])

        for w in self.weeks:
            lecture_intervals: List[cp_model.IntervalVar] = []
            tutorial_intervals: List[cp_model.IntervalVar] = []
            lab_intervals: List[cp_model.IntervalVar] = []
            tagged_lab_intervals: DefaultDict[str, List[cp_model.IntervalVar]] = defaultdict(list)
            for a_id, act in inst.activities.items():
                if int(act.week) != int(w):
                    continue
                if int(a_id) in follower_ids_by_week_kind[w][str(act.kind)]:
                    continue
                if str(act.kind) == "LEC":
                    lecture_intervals.append(self.interval[int(a_id)])
                elif str(act.kind) == "TUT":
                    tutorial_intervals.append(self.interval[int(a_id)])
                else:
                    lab_intervals.append(self.interval[int(a_id)])
                    tag = str(getattr(act, "requires_specialization", "") or "").strip()
                    if tag:
                        tagged_lab_intervals[tag].append(self.interval[int(a_id)])

            if num_lec > 0 and lecture_intervals:
                m.AddCumulative(lecture_intervals, [1] * len(lecture_intervals), num_lec)
            shared_teaching = [*lecture_intervals, *tutorial_intervals]
            if num_lec + num_tut > 0 and shared_teaching:
                m.AddCumulative(shared_teaching, [1] * len(shared_teaching), num_lec + num_tut)
            if num_lab > 0 and lab_intervals:
                m.AddCumulative(lab_intervals, [1] * len(lab_intervals), num_lab)
            for tag, intervals in tagged_lab_intervals.items():
                cap = len(self.spec_rooms_by_tag.get(tag, []))
                if cap > 0 and intervals:
                    m.AddCumulative(intervals, [1] * len(intervals), cap)

        # Optional CP rooming with cluster co-location
        if self.room_mode == "cp_rooms":
            room_intervals_by_week: Dict[Tuple[int, int], List[cp_model.IntervalVar]] = {}
            enforce_room_availability = self._hard_flag("enforce_room_availability", True)

            # Locked rooms (partial re-solve support)
            locks = getattr(inst, "locked_activities", {}) or {}
            if isinstance(locks, dict):
                for a_id, fixed in locks.items():
                    if not isinstance(fixed, dict) or "room_id" not in fixed:
                        continue
                    if a_id not in self.allowed_rooms:
                        continue
                    fixed_room = int(fixed["room_id"])
                    if fixed_room not in self.allowed_rooms[a_id]:
                        raise ValueError(f"Locked activity {a_id}: room_id {fixed_room} is not eligible")
                    for r in self.allowed_rooms[a_id]:
                        self.m.Add(self.room_sel[(a_id, r)] == (1 if r == fixed_room else 0))

            # Room availability (if provided): forbid (activity start, room) combinations that
            # use any unavailable (day, slot) pair.
            full_pairs = {(d, s) for d in self.days for s in range(self.S)}

            def _room_allows(room_id: int, week: int, day: str, start_slot: int, dur: int) -> bool:
                return room_is_available(
                    inst,
                    int(room_id),
                    week=int(week),
                    day=str(day),
                    start_slot=int(start_slot),
                    dur=int(dur),
                )

            for w in self.weeks:
                clustered: Set[int] = set()

                for kind in ("LEC", "TUT", "LAB"):
                    for cluster in self.clusters_by_week_kind[w][kind]:
                        leader = cluster[0]
                        common = set(self.allowed_rooms[leader])
                        for a in cluster[1:]:
                            common &= set(self.allowed_rooms[a])
                        cluster_groups = {
                            int(group_id)
                            for activity_id in cluster
                            for group_id in self.inst.activities[activity_id].group_ids
                        }
                        cluster_capacity = capacity_required(self.inst, cluster_groups)
                        if self._hard_flag("enforce_room_capacity", True):
                            common = {
                                int(room_id)
                                for room_id in common
                                if int(self.inst.rooms[room_id].capacity) >= int(cluster_capacity)
                            }
                        cluster_duration = max(
                            int(self.inst.activities[activity_id].duration)
                            for activity_id in cluster
                        )

                        self.m.Add(sum(self.room_sel[(leader, r)] for r in self.allowed_rooms[leader]) == 1)
                        for r in self.allowed_rooms[leader]:
                            if r in common:
                                iv = self.m.NewOptionalIntervalVar(
                                    self.start[leader],
                                    cluster_duration,
                                    self.start[leader] + cluster_duration,
                                    self.room_sel[(leader, r)],
                                    f"Riv[{leader},{r}]"
                                )
                                room_intervals_by_week.setdefault((r, w), []).append(iv)
                                self.room_iv[(leader, r)] = iv
                            else:
                                self.m.Add(self.room_sel[(leader, r)] == 0)

                        for a in cluster[1:]:
                            self.m.Add(sum(self.room_sel[(a, r)] for r in self.allowed_rooms[a]) == 1)
                            for r in self.allowed_rooms[a]:
                                if r in common:
                                    self.m.Add(self.room_sel[(a, r)] == self.room_sel[(leader, r)])
                                else:
                                    self.m.Add(self.room_sel[(a, r)] == 0)
                        clustered.update(cluster)

                for a_id, act in self.inst.activities.items():
                    if act.week != w or a_id in clustered:
                        continue
                    self.m.Add(sum(self.room_sel[(a_id, r)] for r in self.allowed_rooms[a_id]) == 1)
                    for r in self.allowed_rooms[a_id]:
                        iv = self.m.NewOptionalIntervalVar(
                            self.start[a_id], act.duration, self.start[a_id] + act.duration,
                            self.room_sel[(a_id, r)], f"Riv[{a_id},{r}]"
                        )
                        room_intervals_by_week.setdefault((r, w), []).append(iv)
                        self.room_iv[(a_id, r)] = iv

                # Availability constraints for all activities in the week (clustered or not)
                for a_id, act in self.inst.activities.items():
                    if act.week != w:
                        continue
                    dur = act.duration
                    allowed_starts = self.allowed_starts[a_id]
                    for r in self.allowed_rooms.get(a_id, []):
                        room = inst.rooms[r]
                        avail = getattr(room, "availability", None)
                        if (not enforce_room_availability) or avail is None:
                            continue
                        if isinstance(avail, set) and avail.issuperset(full_pairs):
                            continue
                        for t in allowed_starts:
                            d_idx = t // self.S
                            s0 = t % self.S
                            if not _room_allows(r, int(w), self.days[d_idx], s0, dur):
                                self.m.Add(
                                    self.room_sel[(a_id, r)]
                                    + self._start_literal(a_id, t)
                                    <= 1
                                )
                # Travel buffers between rooms for shared group/staff resources.
                if self._hard_flag("enforce_travel_time_buffers", True) and any(
                    int(v) > 0 for v in (getattr(inst, "travel_time_rules", {}) or {}).values()
                ):
                    shared_pairs: Set[Tuple[int, int]] = set()
                    week_activity_ids = [
                        int(a_id)
                        for a_id, act in self.inst.activities.items()
                        if int(act.week) == int(w)
                    ]
                    for idx, a_id in enumerate(week_activity_ids):
                        act_a = self.inst.activities[a_id]
                        staff_a = int(self.activity_staff[a_id])
                        groups_a = set(int(g) for g in act_a.group_ids)
                        for b_id in week_activity_ids[idx + 1 :]:
                            act_b = self.inst.activities[b_id]
                            if staff_a == int(self.activity_staff[b_id]) or groups_a & set(
                                int(g) for g in act_b.group_ids
                            ):
                                shared_pairs.add((int(a_id), int(b_id)))
                    for constraint in getattr(inst, "distribution_constraints", []) or []:
                        if not constraint.required:
                            continue
                        if normalize_distribution_type(constraint.constraint_type) != "same_attendees":
                            continue
                        ids = [
                            int(value)
                            for value in constraint.activity_ids
                            if int(value) in week_activity_ids
                        ]
                        for left_id, right_id in combinations(ids, 2):
                            shared_pairs.add(
                                (min(left_id, right_id), max(left_id, right_id))
                            )

                    for a_id, b_id in sorted(shared_pairs):
                        act_a = self.inst.activities[a_id]
                        act_b = self.inst.activities[b_id]
                        for ra in self.allowed_rooms.get(a_id, []):
                            for rb in self.allowed_rooms.get(b_id, []):
                                buffer_slots = room_transition_buffer(
                                    inst,
                                    inst.rooms.get(int(ra)),
                                    inst.rooms.get(int(rb)),
                                )
                                if int(buffer_slots) <= 0:
                                    continue
                                for ta in self.allowed_starts[a_id]:
                                    day_a = int(ta // self.S)
                                    end_a = int(ta) + int(act_a.duration)
                                    for tb in self.allowed_starts[b_id]:
                                        if int(tb // self.S) != int(day_a):
                                            continue
                                        end_b = int(tb) + int(act_b.duration)
                                        violated = False
                                        if int(ta) <= int(tb):
                                            violated = int(end_a) + int(buffer_slots) > int(tb)
                                        else:
                                            violated = int(end_b) + int(buffer_slots) > int(ta)
                                        if violated:
                                            self.m.Add(
                                                self._start_literal(a_id, ta)
                                                + self._start_literal(b_id, tb)
                                                + self.room_sel[(a_id, ra)]
                                                + self.room_sel[(b_id, rb)]
                                                <= 3
                                            )

            for (r, w), ivs in room_intervals_by_week.items():
                if len(ivs) > 1:
                    self.m.AddNoOverlap(ivs)

            if self._hard_flag("force_repeat_weekly_pattern", False):
                for leader, follower in repeat_pattern_pairs:
                    leader_rooms = set(self.allowed_rooms.get(int(leader), []))
                    follower_rooms = set(self.allowed_rooms.get(int(follower), []))
                    common = leader_rooms & follower_rooms
                    if not common:
                        raise ValueError(
                            f"Repeat weekly pattern impossible: A{leader} and A{follower} "
                            "have no common eligible room"
                        )
                    for r in leader_rooms:
                        if int(r) not in common:
                            self.m.Add(self.room_sel[(int(leader), int(r))] == 0)
                    for r in follower_rooms:
                        if int(r) not in common:
                            self.m.Add(self.room_sel[(int(follower), int(r))] == 0)
                    for r in common:
                        self.m.Add(
                            self.room_sel[(int(leader), int(r))]
                            == self.room_sel[(int(follower), int(r))]
                        )

        self._add_distribution_constraints()

    def _distribution_info(self, activity_id: int, start: int) -> Dict[str, object]:
        activity = self.inst.activities[int(activity_id)]
        return {
            "week": int(activity.week),
            "day": str(self.days[int(start) // self.S]),
            "slot": int(start) % self.S,
            "duration": int(activity.duration),
            "room_id": None,
        }

    def _add_distribution_constraints(self) -> None:
        """Compile required portable distribution rules into the CP master.

        Soft relations remain measurable by the shared evaluator and local
        improvement layer. MaxBreaks and MaxBlock have exact evaluators but are
        deliberately rejected as hard CP rules until an automaton formulation is
        selected; silently weakening an imported institution rule is unsafe.
        """
        constraints = getattr(self.inst, "distribution_constraints", []) or []
        for constraint in constraints:
            kind = normalize_distribution_type(constraint.constraint_type)
            activity_ids = [int(value) for value in constraint.activity_ids]
            missing = [value for value in activity_ids if value not in self.inst.activities]
            if missing:
                raise ValueError(
                    f"Distribution constraint {constraint.id} references unknown activities {missing}"
                )
            if not constraint.required:
                continue
            if len(activity_ids) < 2 and kind not in AGGREGATE_TYPES:
                raise ValueError(
                    f"Distribution constraint {constraint.id} requires at least two activities"
                )

            if kind in {"same_room", "different_room"}:
                if self.room_mode == "greedy":
                    raise ValueError(
                        f"Required {kind} needs room_mode='cp_rooms' or 'decomposed'"
                    )
                if self.room_mode == "decomposed":
                    continue
                for left_id, right_id in combinations(activity_ids, 2):
                    left_rooms = set(self.allowed_rooms.get(left_id, []))
                    right_rooms = set(self.allowed_rooms.get(right_id, []))
                    if kind == "same_room":
                        common = left_rooms & right_rooms
                        if not common:
                            self.m.Add(0 == 1)
                            continue
                        for room_id in left_rooms - common:
                            self.m.Add(self.room_sel[(left_id, room_id)] == 0)
                        for room_id in right_rooms - common:
                            self.m.Add(self.room_sel[(right_id, room_id)] == 0)
                        for room_id in common:
                            self.m.Add(
                                self.room_sel[(left_id, room_id)]
                                == self.room_sel[(right_id, room_id)]
                            )
                    else:
                        for room_id in left_rooms & right_rooms:
                            self.m.Add(
                                self.room_sel[(left_id, room_id)]
                                + self.room_sel[(right_id, room_id)]
                                <= 1
                            )
                continue

            if kind in PAIRWISE_TYPES:
                for left_id, right_id in combinations(activity_ids, 2):
                    allowed_pairs = [
                        (int(left_start), int(right_start))
                        for left_start in self.allowed_starts[left_id]
                        for right_start in self.allowed_starts[right_id]
                        if pair_satisfies_distribution(
                            self.inst,
                            constraint,
                            self._distribution_info(left_id, left_start),
                            self._distribution_info(right_id, right_start),
                        )
                    ]
                    if allowed_pairs:
                        self.m.AddAllowedAssignments(
                            [self.start[left_id], self.start[right_id]],
                            allowed_pairs,
                        )
                    else:
                        self.m.Add(0 == 1)
                continue

            if kind in ORDERED_TYPES:
                minimum_gap = distribution_parameter(
                    constraint,
                    "minimum_gap",
                    "G",
                    default=0,
                )
                week_index = {
                    int(week): index for index, week in enumerate(self.weeks)
                }
                for left_id, right_id in zip(activity_ids, activity_ids[1:]):
                    left_activity = self.inst.activities[left_id]
                    right_activity = self.inst.activities[right_id]
                    allowed_pairs: List[Tuple[int, int]] = []
                    for left_start in self.allowed_starts[left_id]:
                        for right_start in self.allowed_starts[right_id]:
                            left_key = (
                                week_index[int(left_activity.week)],
                                int(left_start) // self.S,
                            )
                            right_key = (
                                week_index[int(right_activity.week)],
                                int(right_start) // self.S,
                            )
                            valid = left_key < right_key or (
                                left_key == right_key
                                and int(left_start) + int(left_activity.duration) + int(minimum_gap)
                                <= int(right_start)
                            )
                            if valid:
                                allowed_pairs.append((int(left_start), int(right_start)))
                    if allowed_pairs:
                        self.m.AddAllowedAssignments(
                            [self.start[left_id], self.start[right_id]],
                            allowed_pairs,
                        )
                    else:
                        self.m.Add(0 == 1)
                continue

            if kind in {"max_breaks", "max_block"}:
                raise ValueError(
                    f"Required {kind} is evaluable but not yet CP-compilable; "
                    "use it as a soft rule or provide an institution-specific compiler"
                )

            if kind in {"max_days", "max_day_load"}:
                maximum = distribution_parameter(
                    constraint,
                    "days" if kind == "max_days" else "slots",
                    "maximum",
                    "D" if kind == "max_days" else "S",
                    default=0,
                )
                by_week: DefaultDict[int, List[int]] = defaultdict(list)
                for activity_id in activity_ids:
                    by_week[int(self.inst.activities[activity_id].week)].append(activity_id)
                for week, week_ids in by_week.items():
                    used_days: List[cp_model.BoolVar] = []
                    for day_index in range(self.D):
                        day_terms: List[cp_model.BoolVar] = []
                        load_terms: List[cp_model.LinearExpr] = []
                        for activity_id in week_ids:
                            starts = [
                                self._start_literal(activity_id, start)
                                for start in self.allowed_starts[activity_id]
                                if int(start) // self.S == int(day_index)
                            ]
                            if not starts:
                                continue
                            activity_on_day = self.m.NewBoolVar(
                                f"distribution_day[{constraint.id},{activity_id},{day_index}]"
                            )
                            self.m.Add(activity_on_day == sum(starts))
                            day_terms.append(activity_on_day)
                            load_terms.append(
                                int(self.inst.activities[activity_id].duration) * activity_on_day
                            )
                        if not day_terms:
                            continue
                        if kind == "max_day_load":
                            self.m.Add(sum(load_terms) <= int(maximum))
                        day_used = self.m.NewBoolVar(
                            f"distribution_used_day[{constraint.id},{week},{day_index}]"
                        )
                        self.m.AddMaxEquality(day_used, day_terms)
                        used_days.append(day_used)
                    if kind == "max_days" and used_days:
                        self.m.Add(sum(used_days) <= int(maximum))
                continue

            raise ValueError(f"No CP compiler for distribution type {kind}")

    def _itc2007_metadata(self) -> Dict[str, object] | None:
        sla = getattr(self.inst, "sla_targets", {}) or {}
        family = str(sla.get("benchmark_family", ""))
        metadata = sla.get("itc2007")
        if family.startswith("ITC-2007") and isinstance(metadata, dict):
            return dict(metadata)
        return None

    def _add_itc2007_course_symmetry(
        self,
        metadata: Dict[str, object],
        *,
        clustered_ids: Set[int],
    ) -> None:
        """Order provably interchangeable synthetic lectures of each ITC course.

        Official ITC-2007 solutions contain no lecture identifier.  For a
        course with ``k`` lectures, all ``k!`` label permutations therefore
        represent the same official schedule. Imported lectures also share a
        unary resource, so their starts are distinct; strict ordering keeps one
        representative and removes the other permutations.

        The cut is metadata-gated and applied only when every activity-specific
        domain and relation relevant to the CP model is identical. If an
        imported instance is later enriched with a lock or relation, that
        course orbit is skipped rather than relying on the original import
        claim.
        """

        mode = str(metadata.get("course_lecture_symmetry", "")).strip()
        enabled = self._hard_flag("enable_itc2007_course_symmetry", False)
        report: Dict[str, object] = {
            "family": "ITC-2007",
            "mode": mode or "undeclared",
            "enabled": bool(enabled and mode == "strict_start_order"),
            "eligible_course_orbits": 0,
            "ordered_activity_pairs": 0,
            "skipped_course_ids": [],
        }
        if not enabled or mode != "strict_start_order":
            self.symmetry_report = report
            return

        related_ids: Set[int] = set()
        for raw_rule in getattr(self.inst, "precedence_rules", []) or []:
            if not isinstance(raw_rule, dict):
                continue
            for key in ("before_activity_id", "after_activity_id"):
                try:
                    related_ids.add(int(raw_rule[key]))
                except (KeyError, TypeError, ValueError):
                    continue
        for constraint in getattr(self.inst, "distribution_constraints", []) or []:
            related_ids.update(int(value) for value in constraint.activity_ids)

        locks = getattr(self.inst, "locked_activities", {}) or {}
        activities_by_course: DefaultDict[int, List[int]] = defaultdict(list)
        for activity_id, activity in self.inst.activities.items():
            activities_by_course[int(activity.course_id)].append(int(activity_id))

        declared_courses = {
            str(value)
            for value in dict(metadata.get("course_students") or {})
        }
        skipped: List[int] = []
        ordered_pairs = 0
        eligible_orbits = 0
        for course_id, raw_activity_ids in sorted(activities_by_course.items()):
            activity_ids = sorted(raw_activity_ids)
            if len(activity_ids) <= 1:
                continue
            course = self.inst.courses[int(course_id)]
            if str(course.code) not in declared_courses:
                skipped.append(int(course_id))
                continue
            if any(
                activity_id in clustered_ids or activity_id in related_ids
                for activity_id in activity_ids
            ):
                skipped.append(int(course_id))
                continue

            signatures = set()
            for activity_id in activity_ids:
                activity = self.inst.activities[int(activity_id)]
                fixed = locks.get(int(activity_id)) if isinstance(locks, dict) else None
                lock_signature = tuple(
                    sorted((str(key), repr(value)) for key, value in dict(fixed or {}).items())
                )
                signatures.add(
                    (
                        int(activity.week),
                        str(activity.kind),
                        int(activity.duration),
                        int(self.activity_staff[int(activity_id)]),
                        tuple(sorted(int(value) for value in activity.group_ids)),
                        str(activity.requires_specialization or ""),
                        tuple(sorted(int(value) for value in (activity.resource_ids or []))),
                        str(activity.cluster_key or ""),
                        tuple(int(value) for value in self.allowed_starts[int(activity_id)]),
                        tuple(
                            int(value)
                            for value in self.allowed_rooms.get(int(activity_id), [])
                        ),
                        lock_signature,
                    )
                )
            if len(signatures) != 1:
                skipped.append(int(course_id))
                continue

            eligible_orbits += 1
            for previous_id, next_id in zip(activity_ids, activity_ids[1:]):
                self.m.Add(self.start[int(previous_id)] < self.start[int(next_id)])
                ordered_pairs += 1

        report.update(
            {
                "eligible_course_orbits": int(eligible_orbits),
                "ordered_activity_pairs": int(ordered_pairs),
                "skipped_course_ids": skipped,
            }
        )
        self.symmetry_report = report

    def _add_itc2007_objective(self, metadata: Dict[str, object]) -> None:
        """Compile the official ITC-2007 curriculum objective exactly."""
        if self.room_mode != "cp_rooms":
            raise ValueError(
                "The joint official ITC-2007 objective requires room_mode='cp_rooms'; "
                "time-only, greedy, and decomposed runs may be scored post-hoc only."
            )
        m = self.m
        code_to_course_id = {
            str(course.code): int(course_id)
            for course_id, course in self.inst.courses.items()
        }
        activities_by_course: DefaultDict[int, List[int]] = defaultdict(list)
        for activity_id, activity in self.inst.activities.items():
            activities_by_course[int(activity.course_id)].append(int(activity_id))

        weights = dict(metadata.get("objective_weights") or {})
        capacity_weight = int(weights.get("room_capacity", 1))
        days_weight = int(weights.get("minimum_working_days", 5))
        compactness_weight = int(weights.get("curriculum_compactness", 2))
        stability_weight = int(weights.get("room_stability", 1))
        students_by_code = {
            str(key): int(value)
            for key, value in dict(metadata.get("course_students") or {}).items()
        }
        minimum_days_by_code = {
            str(key): int(value)
            for key, value in dict(metadata.get("minimum_working_days") or {}).items()
        }
        penalties: List[cp_model.LinearExpr] = []

        # Room overflow: every missing seat is one penalty point.
        for activity_id, activity in self.inst.activities.items():
            course_code = str(self.inst.courses[int(activity.course_id)].code)
            students = int(students_by_code.get(course_code, 0))
            for room_id in self.allowed_rooms.get(int(activity_id), []):
                overflow = max(0, students - int(self.inst.rooms[int(room_id)].capacity))
                if overflow:
                    penalties.append(
                        capacity_weight
                        * int(overflow)
                        * self.room_sel[(int(activity_id), int(room_id))]
                    )

        # Five points for every missing working day below each course minimum.
        for course_code, minimum_days in minimum_days_by_code.items():
            course_id = code_to_course_id.get(str(course_code))
            if course_id is None:
                raise ValueError(f"ITC-2007 objective references unknown course {course_code}")
            day_used: List[cp_model.BoolVar] = []
            for day_index in range(self.D):
                activity_days: List[cp_model.BoolVar] = []
                for activity_id in activities_by_course[int(course_id)]:
                    starts = [
                        self._start_literal(activity_id, start)
                        for start in self.allowed_starts[activity_id]
                        if int(start) // self.S == int(day_index)
                    ]
                    if not starts:
                        continue
                    on_day = m.NewBoolVar(
                        f"itc2007_course_day_activity[{course_id},{activity_id},{day_index}]"
                    )
                    m.Add(on_day == sum(starts))
                    activity_days.append(on_day)
                used = m.NewBoolVar(f"itc2007_course_day[{course_id},{day_index}]")
                if activity_days:
                    m.AddMaxEquality(used, activity_days)
                else:
                    m.Add(used == 0)
                day_used.append(used)
            missing = m.NewIntVar(
                0,
                max(0, int(minimum_days)),
                f"itc2007_missing_days[{course_id}]",
            )
            m.AddMaxEquality(
                missing,
                [0, int(minimum_days) - sum(day_used)],
            )
            penalties.append(days_weight * missing)

        # Two points per isolated curriculum lecture.
        for curriculum_name, raw_members in dict(metadata.get("curricula") or {}).items():
            member_ids = {
                code_to_course_id[str(code)]
                for code in list(raw_members or [])
                if str(code) in code_to_course_id
            }
            for day_index in range(self.D):
                occupied: List[cp_model.BoolVar] = []
                for slot in range(self.S):
                    terms: List[cp_model.BoolVar] = []
                    for course_id in member_ids:
                        for activity_id in activities_by_course[int(course_id)]:
                            start = day_index * self.S + slot
                            if start in self.allowed_starts[activity_id]:
                                terms.append(self._start_literal(activity_id, start))
                    occ = m.NewBoolVar(
                        f"itc2007_curr_occ[{curriculum_name},{day_index},{slot}]"
                    )
                    if terms:
                        m.Add(occ == sum(terms))
                    else:
                        m.Add(occ == 0)
                    occupied.append(occ)
                for slot, occ in enumerate(occupied):
                    previous = occupied[slot - 1] if slot > 0 else None
                    following = occupied[slot + 1] if slot + 1 < self.S else None
                    isolated = m.NewBoolVar(
                        f"itc2007_isolated[{curriculum_name},{day_index},{slot}]"
                    )
                    m.Add(isolated <= occ)
                    neighbors: List[cp_model.BoolVar] = []
                    if previous is not None:
                        m.Add(isolated + previous <= 1)
                        neighbors.append(previous)
                    if following is not None:
                        m.Add(isolated + following <= 1)
                        neighbors.append(following)
                    m.Add(isolated >= occ - sum(neighbors))
                    penalties.append(compactness_weight * isolated)

        # One point for every additional room used by a course.
        for course_id, activity_ids in activities_by_course.items():
            room_ids = sorted(
                {
                    int(room_id)
                    for activity_id in activity_ids
                    for room_id in self.allowed_rooms.get(int(activity_id), [])
                }
            )
            used_rooms: List[cp_model.BoolVar] = []
            for room_id in room_ids:
                terms = [
                    self.room_sel[(activity_id, room_id)]
                    for activity_id in activity_ids
                    if (activity_id, room_id) in self.room_sel
                ]
                used = m.NewBoolVar(f"itc2007_room_used[{course_id},{room_id}]")
                if terms:
                    m.AddMaxEquality(used, terms)
                else:
                    m.Add(used == 0)
                used_rooms.append(used)
            if used_rooms:
                additional = m.NewIntVar(
                    0,
                    max(0, len(used_rooms) - 1),
                    f"itc2007_additional_rooms[{course_id}]",
                )
                # Every ITC course has at least one lecture and every lecture
                # selects exactly one room, so at least one used-room literal
                # is true. Keep the auxiliary variable functionally equal to
                # the exported schedule's score even for a merely FEASIBLE
                # incumbent whose objective has not been fully minimized.
                m.Add(additional == sum(used_rooms) - 1)
                penalties.append(stability_weight * additional)

        m.Minimize(sum(penalties) if penalties else 0)

    def _add_objective(self) -> None:
        """
        Add a linear soft-constraint objective similar to the local-search scorer.

        Notes:
          - This is a weighted penalty model; it does not change feasibility.
          - Room-consistency penalties are included only in CP-rooming mode.
        """
        m = self.m
        inst = self.inst

        itc2007 = self._itc2007_metadata()
        if itc2007 is not None:
            self._add_itc2007_objective(itc2007)
            return

        weights = {
            "stud_free_days": 10,
            "stud_free_mf": 5,
            "stud_gaps": 5,
            "staff_free_day": 6,
            "active_days": 5,
            "late_start": 3,
            "thin_day": 3,
            "stability": 1,
            "room_consistency": 1,
            "single_slot": 6,
            "same_kind_week": 3,
        }
        overrides = getattr(inst, "soft_weights", None)
        if isinstance(overrides, dict):
            for k, v in overrides.items():
                try:
                    weights[str(k)] = int(v)
                except Exception:
                    continue

        days = list(self.days)
        weeks = list(self.weeks)
        S = int(self.S)
        D = int(self.D)

        group_ids = list(inst.groups.keys())
        staff_ids = list(inst.staff.keys())

        mf_days = {d for d in days if d in {"MON", "TUE", "WED", "THU", "FRI"}}
        mf_day_idx = [i for i, d in enumerate(days) if d in mf_days]

        # Precompute occupancy terms by (entity, week, day_idx, slot).
        g_terms: DefaultDict[Tuple[int, int, int, int], List[cp_model.BoolVar]] = defaultdict(list)
        s_terms: DefaultDict[Tuple[int, int, int, int], List[cp_model.BoolVar]] = defaultdict(list)

        for a_id, act in inst.activities.items():
            w = act.week
            if w not in set(weeks):
                continue
            dur = int(act.duration)
            sid = self.activity_staff[a_id]
            for t in self.allowed_starts[a_id]:
                d_idx = t // S
                s0 = t % S
                xvar = self._start_literal(a_id, t)
                for off in range(dur):
                    slot = s0 + off
                    if 0 <= slot < S:
                        s_terms[(sid, w, d_idx, slot)].append(xvar)
                        for g in act.group_ids:
                            g_terms[(int(g), w, d_idx, slot)].append(xvar)

        # Build group occupancy and day-active booleans.
        g_occ: Dict[Tuple[int, int, int, int], cp_model.BoolVar] = {}
        g_day: Dict[Tuple[int, int, int], cp_model.BoolVar] = {}
        g_active_days: Dict[Tuple[int, int], cp_model.LinearExpr] = {}

        for g in group_ids:
            for w in weeks:
                for d_idx in range(D):
                    for s in range(S):
                        key = (g, w, d_idx, s)
                        b = m.NewBoolVar(f"g_occ[{g},{w},{d_idx},{s}]")
                        terms = g_terms.get(key, [])
                        if terms:
                            for xvar in terms:
                                m.Add(b >= xvar)
                            m.Add(sum(terms) >= b)
                        else:
                            m.Add(b == 0)
                        g_occ[key] = b

        for g in group_ids:
            for w in weeks:
                day_bools: List[cp_model.BoolVar] = []
                for d_idx in range(D):
                    b = m.NewBoolVar(f"g_day[{g},{w},{d_idx}]")
                    occs = [g_occ[(g, w, d_idx, s)] for s in range(S)]
                    for o in occs:
                        m.Add(b >= o)
                    m.Add(sum(occs) >= b)
                    g_day[(g, w, d_idx)] = b
                    day_bools.append(b)
                g_active_days[(g, w)] = sum(day_bools)

        # Staff day activity for staff-free-day penalty.
        s_occ: Dict[Tuple[int, int, int, int], cp_model.BoolVar] = {}
        s_day: Dict[Tuple[int, int, int], cp_model.BoolVar] = {}
        s_active_days: Dict[Tuple[int, int], cp_model.LinearExpr] = {}

        for sid in staff_ids:
            for w in weeks:
                for d_idx in range(D):
                    for s in range(S):
                        key = (sid, w, d_idx, s)
                        b = m.NewBoolVar(f"s_occ[{sid},{w},{d_idx},{s}]")
                        terms = s_terms.get(key, [])
                        if terms:
                            for xvar in terms:
                                m.Add(b >= xvar)
                            m.Add(sum(terms) >= b)
                        else:
                            m.Add(b == 0)
                        s_occ[key] = b

        for sid in staff_ids:
            for w in weeks:
                day_bools: List[cp_model.BoolVar] = []
                for d_idx in range(D):
                    b = m.NewBoolVar(f"s_day[{sid},{w},{d_idx}]")
                    occs = [s_occ[(sid, w, d_idx, s)] for s in range(S)]
                    for o in occs:
                        m.Add(b >= o)
                    m.Add(sum(occs) >= b)
                    s_day[(sid, w, d_idx)] = b
                    day_bools.append(b)
                s_active_days[(sid, w)] = sum(day_bools)

        penalties: List[cp_model.LinearExpr] = []
        group_penalties: DefaultDict[int, List[cp_model.LinearExpr]] = defaultdict(list)
        group_penalty_bounds: DefaultDict[int, int] = defaultdict(int)
        penalty_upper_bound = 0

        def record_penalty(
            expression: cp_model.LinearExpr | int,
            upper_bound: int,
            *,
            group_id: int | None = None,
        ) -> None:
            nonlocal penalty_upper_bound
            penalties.append(expression)
            penalty_upper_bound += max(0, int(upper_bound))
            if group_id is not None:
                group_penalties[int(group_id)].append(expression)
                group_penalty_bounds[int(group_id)] += max(0, int(upper_bound))

        # Student free days + Mon–Fri free days + active days.
        for g, group in inst.groups.items():
            want = int(getattr(group, "preferred_free_days", 0) or 0)
            for w in weeks:
                active = g_active_days[(g, w)]

                slack_free = m.NewIntVar(0, D, f"slack_free[{g},{w}]")
                m.Add(slack_free >= want - D + active)
                record_penalty(
                    weights["stud_free_days"] * slack_free,
                    abs(weights["stud_free_days"]) * D,
                    group_id=int(g),
                )

                if mf_day_idx:
                    active_mf = sum(g_day[(g, w, d)] for d in mf_day_idx)
                    slack_mf = m.NewIntVar(0, len(mf_day_idx), f"slack_mf[{g},{w}]")
                    m.Add(slack_mf >= want - len(mf_day_idx) + active_mf)
                    record_penalty(
                        weights["stud_free_mf"] * slack_mf,
                        abs(weights["stud_free_mf"]) * len(mf_day_idx),
                        group_id=int(g),
                    )

                slack_active = m.NewIntVar(0, D, f"slack_active[{g},{w}]")
                m.Add(slack_active >= active - 3)
                record_penalty(
                    weights["active_days"] * slack_active,
                    abs(weights["active_days"]) * D,
                    group_id=int(g),
                )

        # Student gaps, day shape (per day).
        for g in group_ids:
            for w in weeks:
                for d_idx in range(D):
                    occs = [g_occ[(g, w, d_idx, s)] for s in range(S)]
                    load_var = m.NewIntVar(0, S, f"g_load[{g},{w},{d_idx}]")
                    m.Add(load_var == sum(occs))

                    # thin day (exactly two slots)
                    thin = m.NewBoolVar(f"thin_day[{g},{w},{d_idx}]")
                    m.Add(load_var == 2).OnlyEnforceIf(thin)
                    m.Add(load_var != 2).OnlyEnforceIf(thin.Not())
                    record_penalty(
                        weights["thin_day"] * thin,
                        abs(weights["thin_day"]),
                        group_id=int(g),
                    )

                    # penalize single-slot presence days to avoid lonely days on campus
                    diff = m.NewIntVar(-S, S, f"single_diff[{g},{w},{d_idx}]")
                    abs_diff = m.NewIntVar(0, S, f"single_abs[{g},{w},{d_idx}]")
                    m.Add(diff == load_var - 1)
                    m.AddAbsEquality(abs_diff, diff)
                    is_single = m.NewBoolVar(f"single_day[{g},{w},{d_idx}]")
                    m.Add(abs_diff == 0).OnlyEnforceIf(is_single)
                    m.Add(abs_diff >= 1).OnlyEnforceIf(is_single.Not())
                    record_penalty(
                        weights["single_slot"] * is_single,
                        abs(weights["single_slot"]),
                        group_id=int(g),
                    )

                    # blocks: count starts of occupied segments
                    starts = [m.NewBoolVar(f"g_block[{g},{w},{d_idx},0]")]
                    m.Add(starts[0] == occs[0])
                    for s in range(1, S):
                        sb = m.NewBoolVar(f"g_block[{g},{w},{d_idx},{s}]")
                        cur = occs[s]
                        prev = occs[s - 1]
                        m.Add(sb <= cur)
                        m.Add(sb + prev <= 1)
                        m.Add(sb + prev >= cur)
                        starts.append(sb)
                    blocks = sum(starts)
                    slack_gaps = m.NewIntVar(0, S, f"slack_gaps[{g},{w},{d_idx}]")
                    m.Add(slack_gaps >= blocks - 1)
                    record_penalty(
                        weights["stud_gaps"] * slack_gaps,
                        abs(weights["stud_gaps"]) * S,
                        group_id=int(g),
                    )

                    # late start: day active but nothing in the first two slots
                    if S >= 2:
                        early_first2 = m.NewBoolVar(f"early_first2[{g},{w},{d_idx}]")
                        m.Add(early_first2 >= occs[0])
                        m.Add(early_first2 >= occs[1])
                        m.Add(early_first2 <= occs[0] + occs[1])

                        late = m.NewBoolVar(f"late_start[{g},{w},{d_idx}]")
                        day_active = g_day[(g, w, d_idx)]
                        m.Add(late >= day_active - early_first2)
                        m.Add(late <= day_active)
                        m.Add(late <= 1 - early_first2)
                        record_penalty(
                            weights["late_start"] * late,
                            abs(weights["late_start"]),
                            group_id=int(g),
                        )

        # Staff: require at least one free day per week (soft penalty).
        for sid in staff_ids:
            for w in weeks:
                active = s_active_days[(sid, w)]
                slack = m.NewIntVar(0, D, f"slack_staff_free[{sid},{w}]")
                m.Add(slack >= 1 - D + active)
                record_penalty(
                    weights["staff_free_day"] * slack,
                    abs(weights["staff_free_day"]) * D,
                )

        # Stability: day-active pattern changes between consecutive weeks.
        for g in group_ids:
            for wi in range(1, len(weeks)):
                w_prev = weeks[wi - 1]
                w_curr = weeks[wi]
                for d_idx in range(D):
                    a = g_day[(g, w_prev, d_idx)]
                    b = g_day[(g, w_curr, d_idx)]
                    diff = m.NewBoolVar(f"g_stab[{g},{w_curr},{d_idx}]")
                    m.Add(diff >= a - b)
                    m.Add(diff >= b - a)
                    m.Add(diff <= a + b)
                    m.Add(diff <= 2 - a - b)
                    record_penalty(
                        weights["stability"] * diff,
                        abs(weights["stability"]),
                        group_id=int(g),
                    )

        # This term is constant in the current model because activity weeks are
        # input data rather than decision variables. Recording it keeps CP and
        # local-search objective values on the same documented scale.
        for g in group_ids:
            for w in weeks:
                counts: DefaultDict[Tuple[int, str], int] = defaultdict(int)
                for activity in inst.activities.values():
                    if int(activity.week) != int(w) or str(activity.kind) not in ("LEC", "TUT"):
                        continue
                    if int(g) not in {int(value) for value in activity.group_ids}:
                        continue
                    counts[(int(activity.course_id), str(activity.kind))] += 1
                same_kind_penalty = sum(
                    max(0, int(count) - 1) * int(weights["same_kind_week"])
                    for count in counts.values()
                )
                if same_kind_penalty:
                    record_penalty(
                        int(same_kind_penalty),
                        int(same_kind_penalty),
                        group_id=int(g),
                    )

        # Room consistency per (course, group, kind) across weeks (CP-rooming only).
        if self.room_mode == "cp_rooms":
            key_to_activities: DefaultDict[Tuple[int, int, str], List[int]] = defaultdict(list)
            for a_id, act in inst.activities.items():
                for g in act.group_ids:
                    key_to_activities[(act.course_id, int(g), act.kind)].append(a_id)

            for (c_id, g_id, kind), act_ids in key_to_activities.items():
                if len(act_ids) <= 1:
                    continue
                room_ids: Set[int] = set()
                for a_id in act_ids:
                    room_ids.update(self.allowed_rooms.get(a_id, []))
                if not room_ids:
                    continue

                used: Dict[int, cp_model.BoolVar] = {r: m.NewBoolVar(f"room_used[{c_id},{g_id},{kind},{r}]") for r in room_ids}
                for r in room_ids:
                    terms: List[cp_model.BoolVar] = []
                    for a_id in act_ids:
                        if r in self.allowed_rooms.get(a_id, []):
                            sel = self.room_sel[(a_id, r)]
                            terms.append(sel)
                            m.Add(used[r] >= sel)
                    if terms:
                        m.Add(sum(terms) >= used[r])
                    else:
                        m.Add(used[r] == 0)

                slack = m.NewIntVar(0, len(room_ids), f"slack_room_cons[{c_id},{g_id},{kind}]")
                m.Add(slack >= sum(used.values()) - 1)
                record_penalty(
                    weights["room_consistency"] * slack,
                    abs(weights["room_consistency"]) * len(room_ids),
                    group_id=int(g_id),
                )

        if penalties:
            if str(getattr(inst, "objective_profile", "")).strip().lower() == "fairness_first":
                burden_vars: List[cp_model.IntVar] = []
                for group_id in group_ids:
                    upper = max(0, int(group_penalty_bounds.get(int(group_id), 0)))
                    burden = m.NewIntVar(0, upper, f"group_burden[{group_id}]")
                    terms = group_penalties.get(int(group_id), [])
                    m.Add(burden == (sum(terms) if terms else 0))
                    burden_vars.append(burden)
                if burden_vars:
                    max_burden_bound = max(group_penalty_bounds.values(), default=0)
                    max_burden = m.NewIntVar(0, int(max_burden_bound), "max_group_burden")
                    m.AddMaxEquality(max_burden, burden_vars)
                    # The multiplier is one greater than a proven upper bound on
                    # every secondary penalty, yielding an exact lexicographic order.
                    lexicographic_scale = int(penalty_upper_bound) + 1
                    m.Minimize(max_burden * lexicographic_scale + sum(penalties))
                else:
                    m.Minimize(sum(penalties))
            else:
                m.Minimize(sum(penalties))

    def _add_decision_strategy(self) -> None:
        if self._dec_free_bools:
            self.m.AddDecisionStrategy(self._dec_free_bools,
                                       cp_model.CHOOSE_FIRST,
                                       cp_model.SELECT_MAX_VALUE)
        if self._dec_start_ints:
            self.m.AddDecisionStrategy(self._dec_start_ints,
                                       cp_model.CHOOSE_LOWEST_MIN,
                                       cp_model.SELECT_MIN_VALUE)
        if self._dec_room_bools:
            self.m.AddDecisionStrategy(self._dec_room_bools,
                                       cp_model.CHOOSE_FIRST,
                                       cp_model.SELECT_MAX_VALUE)


# ---------- Greedy room assignment with co-location and tutorial support ----------

def _clusters_for_assignment(inst: Instance) -> Dict[int, Dict[str, List[List[int]]]]:
    # build the same cluster view the solver uses, but only membership is needed here
    by_week_kind: Dict[int, Dict[str, List[List[int]]]] = {w: {"LEC": [], "TUT": [], "LAB": []} for w in inst.weeks}

    by_ckwg: DefaultDict[Tuple[int, str, int, int], List[int]] = defaultdict(list)
    for a_id, a in inst.activities.items():
        if len(a.group_ids) == 1:
            by_ckwg[(a.course_id, a.kind, a.week, a.group_ids[0])].append(a_id)

    for c_id, course in inst.courses.items():
        shared = getattr(course, "share_lecture_group_ids", None)
        if shared:
            shared_set = set(shared)
            by_week: DefaultDict[int, List[int]] = defaultdict(list)
            for (cc, k, w, g), bucket in by_ckwg.items():
                if cc != c_id or k != "LEC":
                    continue
                if g in shared_set:
                    by_week[w].extend(bucket)
            for w, members in by_week.items():
                if len(members) >= 2:
                    by_week_kind[w]["LEC"].append(sorted(members))

    key_map: DefaultDict[Tuple[str, int, str], List[int]] = defaultdict(list)
    for a_id, a in inst.activities.items():
        key = getattr(a, "cluster_key", None)
        if key:
            key_map[(str(key), a.week, a.kind)].append(a_id)
    for (key, w, kind), members in key_map.items():
        if len(members) >= 2:
            by_week_kind[w][kind].append(sorted(members))

    for w in by_week_kind:
        for kind in ("LEC", "TUT", "LAB"):
            seen: Set[Tuple[int, ...]] = set()
            uniq: List[List[int]] = []
            for c in by_week_kind[w][kind]:
                t = tuple(c)
                if t not in seen:
                    seen.add(t)
                    uniq.append(c)
            by_week_kind[w][kind] = uniq

    return by_week_kind


def assign_rooms_greedily(inst: Instance, schedule: Dict[int, Dict[str, object]]) -> None:
    """
    After CP assigns times, pick rooms per slot.

    Policy:
      - Co-locate clustered activities onto one room for that kind.
      - Specialized labs require matching SPECIALIZED_LAB rooms with the right tag.
      - LEC use LECTURE rooms only.
      - TUT use TUTORIAL rooms first, then LECTURE overflow.
      - Room selection is capacity-aware (based on sum of involved group sizes).
    """
    days = inst.days
    weeks = sorted(inst.weeks)
    S = inst.slots_per_day
    hard_flags = getattr(inst, "hard_constraints", {}) or {}
    enforce_room_availability = bool(hard_flags.get("enforce_room_availability", True))
    enforce_room_capacity = hard_flag(inst, "enforce_room_capacity", True)
    force_repeat_weekly_pattern = bool(hard_flags.get("force_repeat_weekly_pattern", False))
    enforce_travel_time_buffers = bool(
        hard_flags.get("enforce_travel_time_buffers", True)
    )
    first_week_for_repeat = min(int(w) for w in weeks) if weeks else None

    lecture_rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "LECTURE"]
    tutorial_rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "TUTORIAL"]
    specialized_lab_rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "SPECIALIZED_LAB"]
    computer_lab_rooms = [r_id for r_id, r in inst.rooms.items() if r.room_type == "COMPUTER_LAB"]
    lab_rooms = specialized_lab_rooms + computer_lab_rooms
    spec_rooms_by_tag: Dict[str, List[int]] = {}
    for r_id, room in inst.rooms.items():
        if room.room_type == "SPECIALIZED_LAB":
            for tag in getattr(room, "specialization_tags", []) or []:
                spec_rooms_by_tag.setdefault(tag, []).append(r_id)

    def _room_available(room_id: int, week: int, day: str, start_slot: int, dur: int) -> bool:
        if not enforce_room_availability and not getattr(inst, "room_closures", None):
            return True
        return room_is_available(
            inst,
            int(room_id),
            week=int(week),
            day=str(day),
            start_slot=int(start_slot),
            dur=int(dur),
        )

    # time occupancy
    slot_acts: Dict[Tuple[int, str, int], List[int]] = {}
    for a_id, info in schedule.items():
        w = info["week"]; d = info["day"]
        s0 = info["slot"]; dur = info["duration"]
        for off in range(dur):
            s = s0 + off
            slot_acts.setdefault((w, d, s), []).append(a_id)

    # honor locked rooms before assigning anything else
    locks = getattr(inst, "locked_activities", {}) or {}
    for a_id, fixed in locks.items():
        if not isinstance(fixed, dict) or "room_id" not in fixed or a_id not in schedule:
            continue
        room_id = int(fixed["room_id"])
        info = schedule[a_id]
        if info.get("room_id") not in (None, room_id):
            raise ValueError(f"Locked room for activity {a_id} conflicts with pre-assigned room")
        if not _room_available(room_id, int(info["week"]), info["day"], info["slot"], info["duration"]):
            raise ValueError(f"Locked room for activity {a_id} is unavailable at the scheduled time")
        schedule[a_id]["room_id"] = room_id

    clusters = _clusters_for_assignment(inst)
    room_key_usage: DefaultDict[Tuple[int, int, str], Dict[int, int]] = defaultdict(dict)
    repeat_room_usage: Dict[Tuple[int, str, int, Tuple[int, ...], int], int] = {}

    def _required_capacity_for_activity(a_id: int) -> int:
        gids = schedule[a_id].get("group_ids", []) or []
        gids_int = [int(g) for g in gids]
        return capacity_required(inst, gids_int)

    def _required_capacity_for_members(members: List[int]) -> int:
        gids: set[int] = set()
        for a_id in members:
            for g in schedule[a_id].get("group_ids", []) or []:
                gids.add(int(g))
        return capacity_required(inst, gids)

    def _travel_buffer_ok(member_ids: List[int], candidate_room_id: int) -> bool:
        if (not enforce_travel_time_buffers) or not getattr(inst, "travel_time_rules", None):
            return True
        member_set = {int(a_id) for a_id in member_ids}
        for a_id in member_set:
            info = schedule[int(a_id)]
            week = int(info["week"])
            day = str(info["day"])
            slot = int(info["slot"])
            dur = int(info["duration"])
            staff_id = int(info["staff_id"])
            groups = {int(g) for g in (info.get("group_ids", []) or [])}
            for other_id, other_info in schedule.items():
                if int(other_id) in member_set:
                    continue
                if other_info.get("room_id") is None:
                    continue
                if int(other_info.get("week", -1)) != int(week):
                    continue
                if str(other_info.get("day", "")) != str(day):
                    continue
                other_staff = int(other_info.get("staff_id", -1))
                other_groups = {int(g) for g in (other_info.get("group_ids", []) or [])}
                if other_staff != int(staff_id) and not (groups & other_groups):
                    continue
                buffer_slots = room_transition_buffer(
                    inst,
                    inst.rooms.get(int(candidate_room_id)),
                    inst.rooms.get(int(other_info["room_id"])),
                )
                if int(buffer_slots) <= 0:
                    continue
                other_slot = int(other_info["slot"])
                other_dur = int(other_info["duration"])
                if int(slot) <= int(other_slot):
                    gap = int(other_slot) - (int(slot) + int(dur))
                else:
                    gap = int(slot) - (int(other_slot) + int(other_dur))
                if int(gap) < int(buffer_slots):
                    return False
        return True

    def _room_consistency_keys(member_ids: List[int]) -> List[Tuple[int, int, str]]:
        keys: List[Tuple[int, int, str]] = []
        seen: Set[Tuple[int, int, str]] = set()
        for a_id in member_ids:
            info = schedule[int(a_id)]
            c_id = int(info["course_id"])
            kind = str(info["kind"])
            for g_id in info.get("group_ids", []) or []:
                key = (c_id, int(g_id), kind)
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
        return keys

    def _base_repeat_room_key(a_id: int) -> Tuple[int, str, int, Tuple[int, ...], int] | None:
        if not force_repeat_weekly_pattern:
            return None
        info = schedule[int(a_id)]
        if first_week_for_repeat is not None and int(info["week"]) == int(first_week_for_repeat):
            return None
        act = inst.activities.get(int(a_id))
        if act is not None and getattr(act, "cluster_key", None):
            return None
        return (
            int(info["course_id"]),
            str(info["kind"]),
            int(info["staff_id"]),
            tuple(sorted(int(g) for g in (info.get("group_ids", []) or []))),
            int(info["duration"]),
        )

    repeat_room_keys_by_activity: Dict[int, Tuple[int, str, int, Tuple[int, ...], int, int]] = {}
    if force_repeat_weekly_pattern and first_week_for_repeat is not None:
        repeat_weeks = [int(w) for w in weeks if int(w) != int(first_week_for_repeat)]
        by_key_week: DefaultDict[
            Tuple[int, str, int, Tuple[int, ...], int],
            DefaultDict[int, List[int]],
        ] = defaultdict(lambda: defaultdict(list))
        for a_id in sorted(int(a_id) for a_id in schedule.keys()):
            key = _base_repeat_room_key(int(a_id))
            if key is None:
                continue
            by_key_week[key][int(schedule[int(a_id)]["week"])].append(int(a_id))
        for key, by_week in by_key_week.items():
            ordered = {
                int(w): sorted(int(a_id) for a_id in by_week.get(int(w), []))
                for w in repeat_weeks
            }
            max_occurrences = max((len(ids) for ids in ordered.values()), default=0)
            for occ_idx in range(max_occurrences):
                if any(occ_idx >= len(ordered.get(int(week), [])) for week in repeat_weeks):
                    continue
                for week in repeat_weeks:
                    repeat_room_keys_by_activity[int(ordered[int(week)][occ_idx])] = (
                        *key,
                        int(occ_idx),
                    )

    def _repeat_room_key(a_id: int) -> Tuple[int, str, int, Tuple[int, ...], int, int] | None:
        return repeat_room_keys_by_activity.get(int(a_id))

    def _repeat_room_ok(member_ids: List[int], room_id: int) -> bool:
        for a_id in member_ids:
            key = _repeat_room_key(int(a_id))
            if key is None:
                continue
            expected = repeat_room_usage.get(key)
            if expected is not None and int(expected) != int(room_id):
                return False
        return True

    def _register_room_assignment(member_ids: List[int], room_id: int) -> None:
        if not _repeat_room_ok(member_ids, int(room_id)):
            raise GreedyRoomingError(
                f"Repeat weekly room pattern would be violated by room {room_id}",
                reason="repeat_week_room",
                activity_id=int(member_ids[0]) if member_ids else None,
            )
        for a_id in member_ids:
            schedule[int(a_id)]["room_id"] = int(room_id)
        for key in _room_consistency_keys(member_ids):
            bucket = room_key_usage.setdefault(key, {})
            bucket[int(room_id)] = int(bucket.get(int(room_id), 0)) + 1
        for a_id in member_ids:
            repeat_key = _repeat_room_key(int(a_id))
            if repeat_key is not None:
                repeat_room_usage.setdefault(repeat_key, int(room_id))

    for existing_id, existing_info in schedule.items():
        existing_room = existing_info.get("room_id")
        if existing_room is not None:
            for key in _room_consistency_keys([int(existing_id)]):
                bucket = room_key_usage.setdefault(key, {})
                bucket[int(existing_room)] = int(bucket.get(int(existing_room), 0)) + 1
            repeat_key = _repeat_room_key(int(existing_id))
            if repeat_key is not None:
                expected = repeat_room_usage.get(repeat_key)
                if expected is not None and int(expected) != int(existing_room):
                    raise GreedyRoomingError(
                        f"Pre-assigned room for A{existing_id} violates repeat weekly room pattern",
                        reason="repeat_week_room",
                        activity_id=int(existing_id),
                    )
                repeat_room_usage[repeat_key] = int(existing_room)

    def _room_cost(
        room_id: int,
        required_capacity: int,
        member_ids: List[int],
    ) -> Tuple[int, int, int, int]:
        stability_penalty = 0
        stability_bonus = 0
        for key in _room_consistency_keys(member_ids):
            prior = room_key_usage.get(key, {})
            if not prior:
                continue
            hits = int(prior.get(int(room_id), 0))
            if hits:
                stability_bonus += hits
            else:
                stability_penalty += sum(int(v) for v in prior.values())
        room = inst.rooms[int(room_id)]
        capacity_overflow = max(0, int(required_capacity) - int(room.capacity))
        capacity_waste = max(0, int(room.capacity) - int(required_capacity))
        return (
            int(capacity_overflow),
            int(stability_penalty) * 1000 - int(stability_bonus) * 100,
            int(capacity_waste),
            int(room_id),
        )

    def _pick_room(
        room_ids: List[int],
        occupied: set[int],
        required_capacity: int,
        week: int,
        day: str,
        slot: int,
        dur: int,
        *,
        member_ids: List[int] | None = None,
    ) -> int | None:
        candidates = [
            r_id for r_id in room_ids
            if r_id not in occupied
            and (
                not enforce_room_capacity
                or inst.rooms[r_id].capacity >= required_capacity
            )
            and _room_available(r_id, week, day, slot, dur)
            and _travel_buffer_ok(member_ids or [], int(r_id))
            and _repeat_room_ok(member_ids or [], int(r_id))
        ]
        candidates.sort(
            key=lambda r_id: _room_cost(
                int(r_id),
                int(required_capacity),
                [int(a) for a in (member_ids or [])],
            )
        )
        return candidates[0] if candidates else None

    def _diagnose_room_failure(
        room_ids: List[int],
        occupied: set[int],
        required_capacity: int,
        week: int,
        day: str,
        slot: int,
        dur: int,
        *,
        member_ids: List[int] | None = None,
    ) -> str:
        if not room_ids:
            return "room_type_missing"
        cap_ok = [
            r_id
            for r_id in room_ids
            if (
                not enforce_room_capacity
                or inst.rooms[r_id].capacity >= required_capacity
            )
        ]
        if not cap_ok:
            return "capacity"
        avail_ok = [r_id for r_id in cap_ok if _room_available(r_id, week, day, slot, dur)]
        if not avail_ok:
            return "availability"
        free_ok = [r_id for r_id in avail_ok if r_id not in occupied]
        if not free_ok:
            return "occupied"
        travel_ok = [r_id for r_id in free_ok if _travel_buffer_ok(member_ids or [], int(r_id))]
        if not travel_ok:
            return "travel_buffer"
        repeat_ok = [r_id for r_id in travel_ok if _repeat_room_ok(member_ids or [], int(r_id))]
        if not repeat_ok:
            return "repeat_week_room"
        return "unknown"

    def _reserved_specialized_rooms(
        *,
        week: int,
        day: str,
        start_slot: int,
        dur: int,
    ) -> set[int]:
        """Rooms that should be reserved for tagged labs overlapping this time span."""
        reserved: set[int] = set()
        for off in range(dur):
            slot = start_slot + off
            for a_id in slot_acts.get((week, day, slot), []):
                if schedule[a_id].get("room_id") is not None:
                    continue
                act = inst.activities[a_id]
                if act.kind != "LAB":
                    continue
                tag = getattr(act, "requires_specialization", None)
                if tag:
                    reserved.update(spec_rooms_by_tag.get(tag, []))
        return reserved

    def _pick_generic_lab_room(
        *,
        week: int,
        day: str,
        start_slot: int,
        dur: int,
        occupied: set[int],
        required_capacity: int,
        member_ids: List[int] | None = None,
    ) -> int | None:
        # Prefer computer labs, then specialized labs not needed by overlapping tagged labs.
        room_id = _pick_room(
            computer_lab_rooms,
            occupied,
            required_capacity,
            week,
            day,
            start_slot,
            dur,
            member_ids=member_ids,
        )
        if room_id is not None:
            return room_id
        reserved = _reserved_specialized_rooms(week=week, day=day, start_slot=start_slot, dur=dur)
        non_reserved_spec = [r for r in specialized_lab_rooms if r not in reserved]
        room_id = _pick_room(
            non_reserved_spec,
            occupied,
            required_capacity,
            week,
            day,
            start_slot,
            dur,
            member_ids=member_ids,
        )
        if room_id is not None:
            return room_id
        return _pick_room(
            specialized_lab_rooms,
            occupied,
            required_capacity,
            week,
            day,
            start_slot,
            dur,
            member_ids=member_ids,
        )

    def _matching_cost_scalar(
        room_id: int,
        required_capacity: int,
        member_ids: List[int],
        *,
        type_rank: int = 0,
    ) -> int:
        overflow, stability, waste, rid = _room_cost(
            int(room_id),
            int(required_capacity),
            member_ids,
        )
        return (
            int(type_rank) * 1_000_000
            + int(overflow) * 100_000
            + int(stability) * 1_000
            + int(waste) * 10
            + int(rid)
        )

    def _candidate_edges_for_activity(
        a_id: int,
        room_ids_with_rank: List[Tuple[int, int]],
        occupied: set[int],
        week: int,
        day: str,
        slot: int,
    ) -> List[Tuple[int, int]]:
        req = _required_capacity_for_activity(int(a_id))
        dur = int(schedule[int(a_id)]["duration"])
        edges: List[Tuple[int, int]] = []
        seen_rooms: Set[int] = set()
        for room_id, type_rank in room_ids_with_rank:
            room_id = int(room_id)
            if room_id in seen_rooms:
                continue
            seen_rooms.add(room_id)
            if room_id in occupied:
                continue
            if enforce_room_capacity and inst.rooms[room_id].capacity < req:
                continue
            if not _room_available(room_id, week, day, slot, dur):
                continue
            if not _travel_buffer_ok([int(a_id)], room_id):
                continue
            if not _repeat_room_ok([int(a_id)], room_id):
                continue
            edges.append(
                (
                    room_id,
                    _matching_cost_scalar(
                        room_id,
                        req,
                        [int(a_id)],
                        type_rank=int(type_rank),
                    ),
                )
            )
        return edges

    def _assign_singles_by_matching(
        activity_ids: List[int],
        room_ids_with_rank: List[Tuple[int, int]],
        occupied: set[int],
        week: int,
        day: str,
        slot: int,
        *,
        label: str,
        failure_rooms: List[int],
    ) -> None:
        if not activity_ids:
            return
        edges = {
            int(a_id): _candidate_edges_for_activity(
                int(a_id),
                room_ids_with_rank,
                occupied,
                week,
                day,
                slot,
            )
            for a_id in activity_ids
        }
        assignment = _min_cost_room_matching([int(a) for a in activity_ids], edges)
        missing = [int(a_id) for a_id in activity_ids if int(a_id) not in assignment]
        if missing:
            sample = int(missing[0])
            reason = _diagnose_room_failure(
                failure_rooms,
                occupied,
                _required_capacity_for_activity(sample),
                week,
                day,
                slot,
                int(schedule[sample]["duration"]),
                member_ids=[sample],
            )
            raise GreedyRoomingError(
                f"No {label} room matching covers all activities at {week}-{day}-{slot} "
                f"(unmatched a{sample}, reason={reason})",
                reason=reason,
                activity_id=sample,
            )
        for a_id in sorted(assignment):
            room_id = int(assignment[int(a_id)])
            _register_room_assignment([int(a_id)], room_id)
            occupied.add(room_id)

    for w in weeks:
        for d in days:
            for s in range(S):
                key = (w, d, s)
                acts = slot_acts.get(key)
                if not acts:
                    continue

                occupied = {
                    schedule[a_id]["room_id"]
                    for a_id in acts
                    if schedule[a_id]["room_id"] is not None
                }
                occupied.discard(None)

                unassigned = [a_id for a_id in acts if schedule[a_id]["room_id"] is None]
                if not unassigned:
                    continue

                # co-locate clusters per kind
                # LEC clusters → LECTURE room
                clusters_here_lec: List[List[int]] = []
                for cl in clusters[w]["LEC"]:
                    members = [a for a in cl if a in unassigned]
                    if len(members) >= 2:
                        clusters_here_lec.append(members)
                for members in clusters_here_lec:
                    req = _required_capacity_for_members(members)
                    room_id = _pick_room(
                        lecture_rooms,
                        occupied,
                        req,
                        w,
                        d,
                        s,
                        schedule[members[0]]["duration"],
                        member_ids=members,
                    )
                    if room_id is None:
                        reason = _diagnose_room_failure(
                            lecture_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[members[0]]["duration"],
                            member_ids=members,
                        )
                        raise GreedyRoomingError(
                            f"No lecture room fits LEC cluster at {w}-{d}-{s} (need cap {req}, reason={reason})",
                            reason=reason,
                            activity_id=members[0],
                        )
                    _register_room_assignment(members, int(room_id))
                    occupied.add(room_id)
                    unassigned = [a for a in unassigned if schedule[a]["room_id"] is None]

                # TUT clusters → TUTORIAL first, else LECTURE
                clusters_here_tut: List[List[int]] = []
                for cl in clusters[w]["TUT"]:
                    members = [a for a in cl if a in unassigned]
                    if len(members) >= 2:
                        clusters_here_tut.append(members)
                for members in clusters_here_tut:
                    req = _required_capacity_for_members(members)
                    room_id = _pick_room(
                        tutorial_rooms,
                        occupied,
                        req,
                        w,
                        d,
                        s,
                        schedule[members[0]]["duration"],
                        member_ids=members,
                    )
                    if room_id is None:
                        room_id = _pick_room(
                            lecture_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[members[0]]["duration"],
                            member_ids=members,
                        )
                    if room_id is None:
                        reason = _diagnose_room_failure(
                            tutorial_rooms + lecture_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[members[0]]["duration"],
                            member_ids=members,
                        )
                        raise GreedyRoomingError(
                            f"No room fits TUT cluster at {w}-{d}-{s} (need cap {req}, reason={reason})",
                            reason=reason,
                            activity_id=members[0],
                        )
                    _register_room_assignment(members, int(room_id))
                    occupied.add(room_id)
                    unassigned = [a for a in unassigned if schedule[a]["room_id"] is None]

                # LAB clusters → lab room
                clusters_here_lab: List[List[int]] = []
                for cl in clusters[w]["LAB"]:
                    members = [a for a in cl if a in unassigned]
                    if len(members) >= 2:
                        clusters_here_lab.append(members)
                for members in clusters_here_lab:
                    req = _required_capacity_for_members(members)
                    dur = schedule[members[0]]["duration"]
                    req_tags = {
                        getattr(inst.activities[a_id], "requires_specialization", None)
                        for a_id in members
                        if getattr(inst.activities[a_id], "requires_specialization", None)
                    }
                    if len(req_tags) > 1:
                        raise GreedyRoomingError(
                            f"Conflicting specialisation tags in LAB cluster at {w}-{d}-{s}: {sorted(req_tags)}",
                            reason="tag_mismatch",
                            activity_id=members[0],
                        )
                    if req_tags:
                        tag = next(iter(req_tags))
                        candidates = spec_rooms_by_tag.get(str(tag), [])
                        room_id = _pick_room(
                            candidates,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            dur,
                            member_ids=members,
                        )
                    else:
                        room_id = _pick_generic_lab_room(
                            week=w,
                            day=d,
                            start_slot=s,
                            dur=dur,
                            occupied=occupied,
                            required_capacity=req,
                            member_ids=members,
                        )
                    if room_id is None:
                        if req_tags:
                            tag = next(iter(req_tags))
                            candidates = spec_rooms_by_tag.get(str(tag), [])
                            reason = (
                                "tag_mismatch"
                                if not candidates
                                else _diagnose_room_failure(
                                    candidates,
                                    occupied,
                                    req,
                                    w,
                                    d,
                                    s,
                                    dur,
                                    member_ids=members,
                                )
                            )
                        else:
                            reason = _diagnose_room_failure(
                                lab_rooms,
                                occupied,
                                req,
                                w,
                                d,
                                s,
                                dur,
                                member_ids=members,
                            )
                        raise GreedyRoomingError(
                            f"No lab room fits LAB cluster at {w}-{d}-{s} (need cap {req}, reason={reason})",
                            reason=reason,
                            activity_id=members[0],
                        )
                    _register_room_assignment(members, int(room_id))
                    occupied.add(room_id)
                    unassigned = [a for a in unassigned if schedule[a]["room_id"] is None]

                # specialized labs first
                labs_spec_by_tag: Dict[str, List[int]] = {}
                labs_generic: List[int] = []
                lecs: List[int] = []
                tuts: List[int] = []

                for a_id in unassigned:
                    act = inst.activities[a_id]
                    if act.kind == "LAB":
                        tag = getattr(act, "requires_specialization", None)
                        if tag:
                            labs_spec_by_tag.setdefault(tag, []).append(a_id)
                        else:
                            labs_generic.append(a_id)
                    elif act.kind == "LEC":
                        lecs.append(a_id)
                    else:
                        tuts.append(a_id)

                for tag, acts_tag in sorted(labs_spec_by_tag.items(), key=lambda item: str(item[0])):
                    tag_rooms = spec_rooms_by_tag.get(tag, [])
                    if not tag_rooms and acts_tag:
                        raise GreedyRoomingError(
                            f"No specialised lab rooms exist for tag {tag} at {w}-{d}-{s}",
                            reason="tag_mismatch",
                            activity_id=int(acts_tag[0]),
                        )
                    _assign_singles_by_matching(
                        [int(a) for a in acts_tag],
                        [(int(r), 0) for r in tag_rooms],
                        occupied,
                        w,
                        d,
                        s,
                        label=f"specialised lab tag {tag}",
                        failure_rooms=tag_rooms,
                    )

                reserved = _reserved_specialized_rooms(week=w, day=d, start_slot=s, dur=1)
                generic_lab_ranked = (
                    [(int(r), 0) for r in computer_lab_rooms]
                    + [(int(r), 1) for r in specialized_lab_rooms if int(r) not in reserved]
                    + [(int(r), 2) for r in specialized_lab_rooms]
                )
                _assign_singles_by_matching(
                    [int(a) for a in labs_generic],
                    generic_lab_ranked,
                    occupied,
                    w,
                    d,
                    s,
                    label="generic lab",
                    failure_rooms=lab_rooms,
                )

                _assign_singles_by_matching(
                    [int(a) for a in lecs],
                    [(int(r), 0) for r in lecture_rooms],
                    occupied,
                    w,
                    d,
                    s,
                    label="lecture",
                    failure_rooms=lecture_rooms,
                )

                _assign_singles_by_matching(
                    [int(a) for a in tuts],
                    [(int(r), 0) for r in tutorial_rooms]
                    + [(int(r), 1) for r in lecture_rooms],
                    occupied,
                    w,
                    d,
                    s,
                    label="tutorial/lecture",
                    failure_rooms=tutorial_rooms + lecture_rooms,
                )
                continue

                for tag, acts_tag in labs_spec_by_tag.items():
                    for a_id in acts_tag:
                        req = _required_capacity_for_activity(a_id)
                        tag_rooms = spec_rooms_by_tag.get(tag, [])
                        room_id = _pick_room(
                            tag_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[a_id]["duration"],
                            member_ids=[a_id],
                        )
                        if room_id is None:
                            if not tag_rooms:
                                reason = "tag_mismatch"
                            else:
                                reason = _diagnose_room_failure(
                                    tag_rooms,
                                    occupied,
                                    req,
                                    w,
                                    d,
                                    s,
                                    schedule[a_id]["duration"],
                                    member_ids=[a_id],
                                )
                            raise GreedyRoomingError(
                                f"No lab room fits specialised lab a{a_id} (need cap {req}, tag={tag}, reason={reason})",
                                reason=reason,
                                activity_id=a_id,
                            )
                        _register_room_assignment([int(a_id)], int(room_id))
                        occupied.add(room_id)

                for a_id in labs_generic:
                    req = _required_capacity_for_activity(a_id)
                    room_id = _pick_generic_lab_room(
                        week=w,
                        day=d,
                        start_slot=s,
                        dur=schedule[a_id]["duration"],
                        occupied=occupied,
                        required_capacity=req,
                        member_ids=[a_id],
                    )
                    if room_id is None:
                        reason = _diagnose_room_failure(
                            lab_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[a_id]["duration"],
                            member_ids=[a_id],
                        )
                        raise GreedyRoomingError(
                            f"No lab room fits lab a{a_id} (need cap {req}, reason={reason})",
                            reason=reason,
                            activity_id=a_id,
                        )
                    _register_room_assignment([int(a_id)], int(room_id))
                    occupied.add(room_id)

                # lectures
                for a_id in lecs:
                    req = _required_capacity_for_activity(a_id)
                    room_id = _pick_room(
                        lecture_rooms,
                        occupied,
                        req,
                        w,
                        d,
                        s,
                        schedule[a_id]["duration"],
                        member_ids=[a_id],
                    )
                    if room_id is None:
                        reason = _diagnose_room_failure(
                            lecture_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[a_id]["duration"],
                            member_ids=[a_id],
                        )
                        raise GreedyRoomingError(
                            f"No lecture room fits a{a_id} (need cap {req}, reason={reason})",
                            reason=reason,
                            activity_id=a_id,
                        )
                    _register_room_assignment([int(a_id)], int(room_id))
                    occupied.add(room_id)

                # tutorials (prefer TUTORIAL then LECTURE)
                for a_id in tuts:
                    req = _required_capacity_for_activity(a_id)
                    room_id = _pick_room(
                        tutorial_rooms,
                        occupied,
                        req,
                        w,
                        d,
                        s,
                        schedule[a_id]["duration"],
                        member_ids=[a_id],
                    )
                    if room_id is None:
                        room_id = _pick_room(
                            lecture_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[a_id]["duration"],
                            member_ids=[a_id],
                        )
                    if room_id is None:
                        reason = _diagnose_room_failure(
                            tutorial_rooms + lecture_rooms,
                            occupied,
                            req,
                            w,
                            d,
                            s,
                            schedule[a_id]["duration"],
                            member_ids=[a_id],
                        )
                        raise GreedyRoomingError(
                            f"No tutorial/lecture room fits a{a_id} (need cap {req}, reason={reason})",
                            reason=reason,
                            activity_id=a_id,
                        )
                    _register_room_assignment([int(a_id)], int(room_id))
                    occupied.add(room_id)
