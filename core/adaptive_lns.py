from __future__ import annotations

import math
import random
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from utils.domain import Instance
from utils.schedule_rules import hard_flag

Schedule = dict[int, dict[str, Any]]


@dataclass(frozen=True)
class CertificateSignal:
    """A typed proof/search signal emitted by an exact subproblem."""

    certificate_type: str
    activity_ids: tuple[int, ...]
    weight: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    certificate_id: str | None = None
    cut_id: str | None = None
    derivation_id: str | None = None


@dataclass(frozen=True)
class NeighborhoodArm:
    family: str
    target_size: int

    @property
    def id(self) -> str:
        return f"{self.family}:{self.target_size}"


@dataclass
class RepairOutcome:
    schedule: Schedule | None
    score: int | None
    elapsed_seconds: float
    status: str
    validated: bool
    neighborhood_optimal: bool = False
    objective_value: float | None = None
    best_objective_bound: float | None = None
    relative_gap: float | None = None
    proof_status: str = "none"
    proof_scope: str = "neighborhood"
    certificates: list[CertificateSignal] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdaptiveLNSResult:
    schedule: Schedule
    initial_score: int
    final_score: int
    elapsed_seconds: float
    trace: list[dict[str, Any]]
    arm_statistics: dict[str, dict[str, float | int]]
    certificates_seen: int
    budget_seconds: float
    deadline_overrun_seconds: float
    termination_reason: str

    def to_dict(self, *, include_schedule: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "initial_score": int(self.initial_score),
            "final_score": int(self.final_score),
            "improvement": int(self.initial_score - self.final_score),
            "elapsed_seconds": float(self.elapsed_seconds),
            "trace": list(self.trace),
            "arm_statistics": dict(self.arm_statistics),
            "certificates_seen": int(self.certificates_seen),
            "budget_seconds": float(self.budget_seconds),
            "deadline_overrun_seconds": float(self.deadline_overrun_seconds),
            "termination_reason": str(self.termination_reason),
            "rounds_completed": int(len(self.trace)),
        }
        if include_schedule:
            payload["schedule"] = {
                str(activity_id): dict(info)
                for activity_id, info in sorted(self.schedule.items())
            }
        return payload


class ConstraintHypergraph:
    """Typed activity adjacency used to close semantic neighborhoods."""

    def __init__(self, inst: Instance, schedule: Schedule) -> None:
        self.inst = inst
        self.schedule = schedule
        self.neighbors: dict[int, set[int]] = {
            int(activity_id): set() for activity_id in inst.activities
        }
        self.edge_types: dict[tuple[int, int], set[str]] = defaultdict(set)
        self._build()

    def _connect(self, activity_ids: Iterable[int], edge_type: str) -> None:
        members = sorted({int(value) for value in activity_ids if int(value) in self.neighbors})
        for left_index, left in enumerate(members):
            for right in members[left_index + 1 :]:
                self.neighbors[left].add(right)
                self.neighbors[right].add(left)
                key = (min(left, right), max(left, right))
                self.edge_types[key].add(str(edge_type))

    def _build(self) -> None:
        by_staff: dict[int, list[int]] = defaultdict(list)
        by_group: dict[int, list[int]] = defaultdict(list)
        by_course: dict[int, list[int]] = defaultdict(list)
        by_room_week: dict[tuple[int, int], list[int]] = defaultdict(list)
        by_week: dict[int, list[int]] = defaultdict(list)
        by_cluster: dict[str, list[int]] = defaultdict(list)

        for activity_id, activity in self.inst.activities.items():
            activity_id = int(activity_id)
            info = self.schedule.get(activity_id, {})
            staff_id = info.get("staff_id")
            if staff_id is None:
                staff_id = activity.prof_id if activity.kind == "LEC" else activity.ta_id
            by_staff[int(staff_id)].append(activity_id)
            for group_id in activity.group_ids:
                by_group[int(group_id)].append(activity_id)
            by_course[int(activity.course_id)].append(activity_id)
            by_week[int(activity.week)].append(activity_id)
            room_id = info.get("room_id")
            if room_id is not None:
                by_room_week[(int(activity.week), int(room_id))].append(activity_id)
            cluster_key = getattr(activity, "cluster_key", None)
            if cluster_key:
                by_cluster[f"{activity.week}:{activity.kind}:{cluster_key}"].append(activity_id)

        for members in by_staff.values():
            self._connect(members, "staff")
        for members in by_group.values():
            self._connect(members, "group")
        for members in by_course.values():
            self._connect(members, "course")
        for members in by_room_week.values():
            self._connect(members, "room")
        for members in by_cluster.values():
            self._connect(members, "cluster")

        for constraint in getattr(self.inst, "distribution_constraints", []) or []:
            self._connect(getattr(constraint, "activity_ids", []) or [], "distribution")

        # Week partitions need a boundary master for course/stability terms. Link
        # the first and last occurrence in adjacent weeks so those activities are
        # preferentially released together.
        course_week: dict[tuple[int, int], list[int]] = defaultdict(list)
        for activity_id, activity in self.inst.activities.items():
            course_week[(int(activity.course_id), int(activity.week))].append(int(activity_id))
        weeks = sorted(int(value) for value in self.inst.weeks)
        for course_id in sorted(int(value) for value in self.inst.courses):
            for left_week, right_week in zip(weeks, weeks[1:]):
                left = course_week.get((course_id, left_week), [])
                right = course_week.get((course_id, right_week), [])
                if left and right:
                    self._connect([left[-1], right[0]], "partition_boundary")

    def closure(
        self,
        seeds: Sequence[int],
        target_size: int,
        *,
        preferred_edge_types: set[str] | None = None,
    ) -> list[int]:
        target = max(len(seeds), int(target_size))
        selected: list[int] = []
        seen: set[int] = set()
        queue: deque[int] = deque(int(value) for value in seeds)
        while queue and len(selected) < target:
            activity_id = int(queue.popleft())
            if activity_id in seen or activity_id not in self.neighbors:
                continue
            seen.add(activity_id)
            selected.append(activity_id)
            ranked: list[tuple[int, int]] = []
            for neighbor in self.neighbors[activity_id]:
                key = (min(activity_id, neighbor), max(activity_id, neighbor))
                types = self.edge_types.get(key, set())
                preferred = bool(preferred_edge_types and types & preferred_edge_types)
                ranked.append((0 if preferred else 1, int(neighbor)))
            for _rank, neighbor in sorted(ranked):
                if neighbor not in seen:
                    queue.append(neighbor)

        if len(selected) < target:
            for activity_id in sorted(self.neighbors):
                if activity_id not in seen:
                    selected.append(activity_id)
                    if len(selected) >= target:
                        break
        return selected


class DiscountedUCBController:
    """Low-overhead online control; policy choices never affect correctness."""

    def __init__(
        self,
        arms: Sequence[NeighborhoodArm],
        *,
        discount: float = 0.97,
        exploration: float = 0.35,
        random_seed: int = 0,
    ) -> None:
        if not arms:
            raise ValueError("At least one LNS arm is required")
        self.arms = list(arms)
        self.discount = min(1.0, max(0.5, float(discount)))
        self.exploration = max(0.0, float(exploration))
        self.rng = random.Random(int(random_seed))
        self.counts = {arm.id: 0.0 for arm in self.arms}
        self.rewards = {arm.id: 0.0 for arm in self.arms}

    def choose(
        self,
        eligible_families: set[str] | None = None,
    ) -> NeighborhoodArm:
        eligible = [
            arm
            for arm in self.arms
            if eligible_families is None or arm.family in eligible_families
        ]
        if not eligible:
            raise ValueError("At least one UCB arm family must be eligible")
        unseen = [arm for arm in eligible if self.counts[arm.id] < 0.5]
        if unseen:
            return unseen[0]
        total = max(1.0, sum(self.counts.values()))
        scored: list[tuple[float, float, NeighborhoodArm]] = []
        for arm in eligible:
            count = max(1e-9, self.counts[arm.id])
            mean = self.rewards[arm.id] / count
            bonus = self.exploration * math.sqrt(math.log1p(total) / count)
            scored.append((mean + bonus, self.rng.random(), arm))
        return max(scored, key=lambda item: (item[0], item[1]))[2]

    def update(self, arm: NeighborhoodArm, reward: float) -> None:
        for key in self.counts:
            self.counts[key] *= self.discount
            self.rewards[key] *= self.discount
        self.counts[arm.id] += 1.0
        self.rewards[arm.id] += float(reward)

    def report(self) -> dict[str, dict[str, float | int]]:
        out: dict[str, dict[str, float | int]] = {}
        for arm in self.arms:
            count = self.counts[arm.id]
            out[arm.id] = {
                "effective_pulls": float(count),
                "mean_reward": float(self.rewards[arm.id] / count) if count > 0 else 0.0,
                "target_size": int(arm.target_size),
            }
        return out


class CertificateGuidedAdaptiveLNS:
    """Anytime LNS with typed certificates, semantic closure, and UCB control."""

    FAMILIES = ("certificate", "penalty", "partition_boundary", "random")

    def __init__(
        self,
        inst: Instance,
        *,
        neighborhood_sizes: Sequence[int] = (12, 24, 48),
        random_seed: int = 0,
    ) -> None:
        sizes = sorted({max(1, int(value)) for value in neighborhood_sizes})
        arms = [NeighborhoodArm(family, size) for family in self.FAMILIES for size in sizes]
        self.inst = inst
        self.rng = random.Random(int(random_seed))
        self.controller = DiscountedUCBController(arms, random_seed=int(random_seed))
        self.context_eligible_arms = hard_flag(
            inst,
            "enable_context_eligible_adaptive_arms",
            False,
        )

    def _itc2007_metadata(self) -> dict[str, Any] | None:
        sla = getattr(self.inst, "sla_targets", {}) or {}
        metadata = sla.get("itc2007")
        if str(sla.get("benchmark_family", "")).startswith("ITC-2007") and isinstance(
            metadata,
            dict,
        ):
            return dict(metadata)
        return None

    def _itc2007_penalty_support(
        self,
        schedule: Schedule,
    ) -> dict[int, dict[str, int]]:
        """Attribute official ITC-2007 penalty components to repair seeds."""

        metadata = self._itc2007_metadata()
        if metadata is None:
            return {}
        weights = {
            str(key): int(value)
            for key, value in dict(metadata.get("objective_weights") or {}).items()
        }
        students_by_code = {
            str(key): int(value)
            for key, value in dict(metadata.get("course_students") or {}).items()
        }
        minimum_days_by_code = {
            str(key): int(value)
            for key, value in dict(metadata.get("minimum_working_days") or {}).items()
        }
        curricula = {
            str(name): tuple(str(value) for value in list(members or []))
            for name, members in dict(metadata.get("curricula") or {}).items()
        }
        code_by_course_id = {
            int(course_id): str(course.code)
            for course_id, course in self.inst.courses.items()
        }
        activities_by_code: dict[str, list[int]] = defaultdict(list)
        for activity_id, activity in self.inst.activities.items():
            code = code_by_course_id.get(int(activity.course_id))
            if code is not None and int(activity_id) in schedule:
                activities_by_code[code].append(int(activity_id))

        support: dict[int, dict[str, int]] = defaultdict(dict)

        def add(activity_id: int, component: str, amount: int) -> None:
            if int(amount) <= 0:
                return
            row = support.setdefault(int(activity_id), {})
            row[str(component)] = int(row.get(str(component), 0)) + int(amount)

        capacity_weight = int(weights.get("room_capacity", 1))
        days_weight = int(weights.get("minimum_working_days", 5))
        compactness_weight = int(weights.get("curriculum_compactness", 2))
        stability_weight = int(weights.get("room_stability", 1))

        for course_code, activity_ids in activities_by_code.items():
            students = int(students_by_code.get(course_code, 0))
            for activity_id in activity_ids:
                room_id = schedule[activity_id].get("room_id")
                room = self.inst.rooms.get(int(room_id)) if room_id is not None else None
                if room is not None:
                    add(
                        activity_id,
                        "room_capacity",
                        capacity_weight * max(0, students - int(room.capacity)),
                    )

            minimum_days = int(minimum_days_by_code.get(course_code, 0))
            day_to_activities: dict[tuple[int, str], list[int]] = defaultdict(list)
            for activity_id in activity_ids:
                info = schedule[activity_id]
                day_to_activities[(int(info["week"]), str(info["day"]))].append(
                    int(activity_id)
                )
            missing_days = max(0, minimum_days - len(day_to_activities))
            if missing_days:
                movable = sorted(
                    activity_id
                    for members in day_to_activities.values()
                    if len(members) > 1
                    for activity_id in members
                ) or sorted(activity_ids)
                for activity_id in movable:
                    add(
                        activity_id,
                        "minimum_working_days",
                        days_weight * missing_days,
                    )

            by_room: dict[int, list[int]] = defaultdict(list)
            for activity_id in activity_ids:
                room_id = schedule[activity_id].get("room_id")
                if room_id is not None:
                    by_room[int(room_id)].append(int(activity_id))
            if len(by_room) > 1:
                preferred_room = min(
                    by_room,
                    key=lambda room_id: (-len(by_room[room_id]), int(room_id)),
                )
                for room_id, members in by_room.items():
                    if int(room_id) == int(preferred_room):
                        continue
                    for activity_id in members:
                        add(activity_id, "room_stability", stability_weight)

        for members in curricula.values():
            member_set = set(members)
            by_day: dict[tuple[int, str], list[int]] = defaultdict(list)
            for course_code in member_set:
                for activity_id in activities_by_code.get(course_code, []):
                    info = schedule[activity_id]
                    by_day[(int(info["week"]), str(info["day"]))].append(
                        int(activity_id)
                    )
            for activity_ids in by_day.values():
                occupied_slots = {int(schedule[value]["slot"]) for value in activity_ids}
                for activity_id in activity_ids:
                    slot = int(schedule[activity_id]["slot"])
                    if slot - 1 not in occupied_slots and slot + 1 not in occupied_slots:
                        add(
                            activity_id,
                            "curriculum_compactness",
                            compactness_weight,
                        )
        return {
            int(activity_id): dict(components)
            for activity_id, components in support.items()
            if sum(int(value) for value in components.values()) > 0
        }

    def _penalty_seed_order(self, schedule: Schedule) -> list[int]:
        if self.context_eligible_arms and self._itc2007_metadata() is not None:
            support = self._itc2007_penalty_support(schedule)
            return sorted(
                support,
                key=lambda activity_id: (
                    -sum(int(value) for value in support[int(activity_id)].values()),
                    int(activity_id),
                ),
            )
        scores: dict[int, int] = defaultdict(int)
        group_day_slots: dict[tuple[int, int, str], set[int]] = defaultdict(set)
        staff_day_slots: dict[tuple[int, int, str], set[int]] = defaultdict(set)
        for activity_id, info in schedule.items():
            week = int(info["week"])
            day = str(info["day"])
            slot = int(info["slot"])
            duration = int(info["duration"])
            occupied = set(range(slot, slot + duration))
            for group_id in info.get("group_ids", []) or []:
                group_day_slots[(int(group_id), week, day)].update(occupied)
            staff_day_slots[(int(info["staff_id"]), week, day)].update(occupied)

        bad_group_days: set[tuple[int, int, str]] = set()
        for key, slots in group_day_slots.items():
            gaps = max(slots) - min(slots) + 1 - len(slots) if slots else 0
            if gaps > 0 or (slots and min(slots) >= 2) or len(slots) == 1:
                bad_group_days.add(key)
        bad_staff_days = {
            key
            for key, slots in staff_day_slots.items()
            if slots and (max(slots) - min(slots) + 1 - len(slots) > 0)
        }
        for activity_id, info in schedule.items():
            key_base = (int(info["week"]), str(info["day"]))
            scores[int(activity_id)] += sum(
                3
                for group_id in info.get("group_ids", []) or []
                if (int(group_id), *key_base) in bad_group_days
            )
            if (int(info["staff_id"]), *key_base) in bad_staff_days:
                scores[int(activity_id)] += 2
            scores[int(activity_id)] += max(0, int(info["slot"]) - 1)
        return sorted(schedule, key=lambda activity_id: (-scores[int(activity_id)], int(activity_id)))

    def _eligible_families(
        self,
        schedule: Schedule,
        graph: ConstraintHypergraph,
        certificates: Sequence[CertificateSignal],
    ) -> set[str]:
        if not self.context_eligible_arms:
            return set(self.FAMILIES)
        eligible = {"random"}
        if certificates:
            eligible.add("certificate")
        if any("partition_boundary" in types for types in graph.edge_types.values()):
            eligible.add("partition_boundary")
        if self._penalty_seed_order(schedule):
            eligible.add("penalty")
        return eligible

    def _seeds(
        self,
        arm: NeighborhoodArm,
        schedule: Schedule,
        graph: ConstraintHypergraph,
        certificates: Sequence[CertificateSignal],
    ) -> tuple[list[int], set[str], list[CertificateSignal], dict[int, dict[str, int]]]:
        if arm.family == "certificate" and certificates:
            ranked = sorted(
                certificates,
                key=lambda item: (
                    -float(item.weight),
                    item.certificate_type,
                    item.certificate_id or "",
                    item.activity_ids,
                ),
            )
            selected = ranked[0]
            return (
                list(selected.activity_ids),
                {"room", "distribution", "group", "staff"},
                [selected],
                {},
            )
        if arm.family == "partition_boundary":
            boundary = [
                activity_id
                for (left, right), types in graph.edge_types.items()
                if "partition_boundary" in types
                for activity_id in (left, right)
            ]
            if boundary:
                return (
                    [int(self.rng.choice(sorted(set(boundary))))],
                    {"partition_boundary", "course"},
                    [],
                    {},
                )
        if arm.family == "penalty":
            ranked = self._penalty_seed_order(schedule)
            if ranked:
                selected = ranked[: max(1, min(3, arm.target_size // 8))]
                typed_support = (
                    self._itc2007_penalty_support(schedule)
                    if self.context_eligible_arms and self._itc2007_metadata() is not None
                    else {}
                )
                return (
                    selected,
                    {"group", "staff", "course"},
                    [],
                    {
                        int(activity_id): dict(typed_support.get(int(activity_id), {}))
                        for activity_id in selected
                        if typed_support.get(int(activity_id))
                    },
                )
        return [int(self.rng.choice(sorted(schedule)))], set(), [], {}

    def run(
        self,
        initial_schedule: Schedule,
        *,
        score_fn: Callable[[Schedule], int],
        validate_fn: Callable[[Schedule], Sequence[str]],
        repair_fn: Callable[[list[int], Schedule, float, int], RepairOutcome],
        total_seconds: float,
        slice_seconds: float = 2.0,
        max_rounds: int = 24,
        initial_certificates: Sequence[CertificateSignal] = (),
    ) -> AdaptiveLNSResult:
        started = time.perf_counter()
        deadline = started + max(0.0, float(total_seconds))
        best = {int(activity_id): dict(info) for activity_id, info in initial_schedule.items()}
        validation_errors = list(validate_fn(best))
        if validation_errors:
            raise ValueError(f"Adaptive LNS requires a validated incumbent: {validation_errors[0]}")
        initial_score = int(score_fn(best))
        best_score = int(initial_score)
        graph = ConstraintHypergraph(self.inst, best)
        certificates = list(initial_certificates)
        trace: list[dict[str, Any]] = []
        termination_reason = "MAX_ROUNDS"

        for round_index in range(1, max(1, int(max_rounds)) + 1):
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                termination_reason = "TIME_LIMIT"
                break
            eligible_families = self._eligible_families(
                best,
                graph,
                certificates,
            )
            arm = self.controller.choose(eligible_families)
            seeds, preferred_types, source_certificates, seed_support = self._seeds(
                arm,
                best,
                graph,
                certificates,
            )
            neighborhood = graph.closure(
                seeds,
                min(len(best), int(arm.target_size)),
                preferred_edge_types=preferred_types,
            )
            budget = min(max(0.0, float(slice_seconds)), max(0.0, remaining))
            if budget <= 0:
                termination_reason = "TIME_LIMIT"
                break
            repair_seed = self.rng.randrange(1, 2**31 - 1)
            outcome = repair_fn(neighborhood, best, budget, repair_seed)
            certificates.extend(outcome.certificates)

            candidate_errors: list[str] = []
            if outcome.schedule is not None and outcome.validated:
                candidate_errors = list(validate_fn(outcome.schedule))
            candidate_valid = (
                outcome.schedule is not None
                and outcome.score is not None
                and outcome.validated
                and not candidate_errors
            )
            improvement = (
                max(0, best_score - int(outcome.score))
                if candidate_valid and outcome.score is not None
                else 0
            )
            accepted = bool(candidate_valid and outcome.score is not None and int(outcome.score) < best_score)
            prior_score = int(best_score)
            if accepted and outcome.schedule is not None and outcome.score is not None:
                best = {int(activity_id): dict(info) for activity_id, info in outcome.schedule.items()}
                best_score = int(outcome.score)
                graph = ConstraintHypergraph(self.inst, best)

            elapsed = max(1e-6, float(outcome.elapsed_seconds))
            reward = (float(improvement) / max(1.0, float(prior_score))) / elapsed
            if outcome.neighborhood_optimal:
                reward += 0.005 / elapsed
            if not candidate_valid:
                reward -= 0.01
            self.controller.update(arm, reward)
            trace.append(
                {
                    "round": int(round_index),
                    "arm": arm.id,
                    "family": arm.family,
                    "target_size": int(arm.target_size),
                    "actual_size": int(len(neighborhood)),
                    "seed_activity_ids": [int(value) for value in seeds],
                    "seed_support": {
                        str(activity_id): dict(components)
                        for activity_id, components in sorted(seed_support.items())
                    },
                    "eligible_families": sorted(eligible_families),
                    "source_certificate_ids": sorted(
                        {
                            str(signal.certificate_id)
                            for signal in source_certificates
                            if signal.certificate_id
                        }
                    ),
                    "source_cut_ids": sorted(
                        {
                            str(signal.cut_id)
                            for signal in source_certificates
                            if signal.cut_id
                        }
                    ),
                    "source_derivation_ids": sorted(
                        {
                            str(signal.derivation_id)
                            for signal in source_certificates
                            if signal.derivation_id
                        }
                    ),
                    "source_lineage": [
                        {
                            "certificate_type": str(signal.certificate_type),
                            "certificate_id": signal.certificate_id,
                            "cut_id": signal.cut_id,
                            "derivation_id": signal.derivation_id,
                            "activity_ids": [
                                int(value) for value in signal.activity_ids
                            ],
                        }
                        for signal in source_certificates
                    ],
                    "status": str(outcome.status),
                    "validated": bool(candidate_valid),
                    "accepted": bool(accepted),
                    "score_before": int(prior_score),
                    "candidate_score": int(outcome.score) if outcome.score is not None else None,
                    "score_after": int(best_score),
                    "reward": float(reward),
                    "elapsed_seconds": float(outcome.elapsed_seconds),
                    "remaining_at_start_seconds": float(remaining),
                    "slice_budget_seconds": float(budget),
                    "neighborhood_optimal": bool(outcome.neighborhood_optimal),
                    "objective_value": outcome.objective_value,
                    "best_objective_bound": outcome.best_objective_bound,
                    "relative_gap": outcome.relative_gap,
                    "proof_status": str(outcome.proof_status),
                    "proof_scope": str(outcome.proof_scope),
                    "certificates_emitted": len(outcome.certificates),
                    "repair_metadata": dict(outcome.metadata),
                }
            )

        elapsed_seconds = float(time.perf_counter() - started)
        if elapsed_seconds >= max(0.0, float(total_seconds)) and len(trace) < max(
            1,
            int(max_rounds),
        ):
            termination_reason = "TIME_LIMIT"
        return AdaptiveLNSResult(
            schedule=best,
            initial_score=int(initial_score),
            final_score=int(best_score),
            elapsed_seconds=elapsed_seconds,
            trace=trace,
            arm_statistics=self.controller.report(),
            certificates_seen=len(certificates),
            budget_seconds=max(0.0, float(total_seconds)),
            deadline_overrun_seconds=max(
                0.0,
                elapsed_seconds - max(0.0, float(total_seconds)),
            ),
            termination_reason=str(termination_reason),
        )


def certificate_signals_from_decomposition(report: Mapping[str, Any] | None) -> list[CertificateSignal]:
    """Extract sound certificate seeds from a solver decomposition trace."""
    signals: list[CertificateSignal] = []
    for round_row in list((report or {}).get("rounds") or []):
        cuts_by_certificate_id = {
            str(cut.get("certificate_id")): cut
            for cut in list((round_row or {}).get("room_cuts") or [])
            if isinstance(cut, Mapping) and cut.get("certificate_id")
        }
        room_result = dict((round_row or {}).get("room_subproblem") or {})
        for raw in list(room_result.get("certificates") or []):
            activity_ids = raw.get("activity_ids") or raw.get("representative_activity_ids") or []
            normalized = tuple(sorted({int(value) for value in activity_ids}))
            if not normalized:
                continue
            deficiency = max(1.0, float(raw.get("deficiency") or 1.0))
            certificate_id = (
                str(raw.get("certificate_id"))
                if raw.get("certificate_id")
                else None
            )
            cut = cuts_by_certificate_id.get(str(certificate_id), {})
            metadata: dict[str, Any] = {
                "week": raw.get("week"),
                "day": raw.get("day"),
                "slot": raw.get("slot"),
            }
            if raw.get("candidate_room_ids") is not None:
                metadata["candidate_room_ids"] = sorted(
                    int(value) for value in (raw.get("candidate_room_ids") or [])
                )
            proof = raw.get("proof")
            if isinstance(proof, Mapping):
                metadata["certificate_proof_rule"] = proof.get("proof_rule")
                metadata["certificate_proof_assumptions"] = dict(proof)
            if cut:
                metadata.update(
                    {
                        "witness_room_ids": list(
                            cut.get("witness_room_ids") or []
                        ),
                        "derived_gamma_room_ids": list(
                            cut.get("derived_gamma_room_ids") or []
                        ),
                        "cut_proof_rule": cut.get("proof_rule"),
                        "cut_proof_assumptions": {
                            "room_context_id": cut.get("room_context_id"),
                            "master_start_domains": dict(
                                cut.get("master_start_domains") or {}
                            ),
                            "counted_starts": list(
                                cut.get("counted_starts") or []
                            ),
                        },
                    }
                )
            signals.append(
                CertificateSignal(
                    certificate_type=str(raw.get("certificate_type") or "room_nogood"),
                    activity_ids=normalized,
                    weight=deficiency,
                    metadata=metadata,
                    certificate_id=certificate_id,
                    cut_id=(str(cut.get("cut_id")) if cut.get("cut_id") else None),
                    derivation_id=(
                        str(cut.get("derivation_id"))
                        if cut.get("derivation_id")
                        else None
                    ),
                )
            )
    return signals


def arm_to_dict(arm: NeighborhoodArm) -> dict[str, Any]:
    return asdict(arm)
