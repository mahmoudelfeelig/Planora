from __future__ import annotations

import copy
import hashlib
import json
import os
import random
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import replace
from threading import Lock
from typing import Any, Callable, Dict, Iterable, List, Tuple

from ortools.sat.python import cp_model

from core.adaptive_lns import (
    CertificateGuidedAdaptiveLNS,
    CertificateSignal,
    RepairOutcome,
    certificate_signals_from_decomposition,
)
from core.fixed_time_room_oracle import optimize_fixed_time_rooms
from core.itc2007_compound_search import optimize_itc2007_compound
from core.itc2007_constructive_v2 import construct_itc2007_schedule
from core.itc2007_feedback_search import optimize_itc2007_feedback
from core.itc2007_rooted_adjacency import (
    DEFAULT_COMPLETION_RESERVE_SECONDS,
    itc2007_rooted_adjacency_eligibility,
    optimize_itc2007_rooted_adjacency,
)
from core.itc2007_quality_tail import (
    itc2007_quality_tail_eligibility,
    optimize_itc2007_quality_tail,
)
from core.metaheuristics import LocalSearchImprover
from core.partitioned_solver import week_partitioning_blockers
from core.projected_time_search import (
    itc2007_fixed_time_room_cp_eligibility,
    optimize_itc2007_fixed_time_rooms_cp,
    optimize_projected_times,
    projected_time_search_eligibility,
)
from core.solver_factory import build_timetable_solver
from core.solver_cp_sat import GreedyRoomingError, TimetableSolver
from services.contracts import (
    ImproveOptions,
    PortfolioCandidate,
    PortfolioResult,
    SolveAttempt,
    SolveOptions,
    SolveResult,
)
from services.quality_service import (
    compute_penalty_breakdown,
    evaluate_schedule_sla,
    explain_solution_ranking,
)
from services.solver_profiles import OBJECTIVE_PROFILE_PRESETS
from utils.disruption import build_freeze_locks
from utils.generator import instance_to_json
from utils.schedule_rules import hard_flag
from utils.specs import validate_schedule_against_instance

_SOLVE_RESULT_CACHE: Dict[str, SolveResult] = {}
_DEFAULT_ADAPTIVE_LNS_NEIGHBORHOOD_SIZES = (12, 24, 48)
_ITC2007_COMPACT_ADAPTIVE_LNS_NEIGHBORHOOD_SIZES = (12, 24)
_FIXED_TIME_ROOM_STRATEGIES = {
    "control",
    "oracle_only",
    "cp_only",
    "oracle_then_cp",
}


def _normalize_fixed_time_room_strategy(value: object) -> str:
    strategy = str(value or "oracle_then_cp").strip().lower()
    if strategy not in _FIXED_TIME_ROOM_STRATEGIES:
        raise ValueError(
            "fixed_time_room_strategy must be one of "
            + ", ".join(sorted(_FIXED_TIME_ROOM_STRATEGIES))
        )
    return strategy


def _solve_portfolio_candidate_process(
    idx: int,
    profile_id: str,
    inst: Any,
    candidate_options: SolveOptions,
) -> tuple[int, str, SolveOptions, SolveResult, int | None]:
    candidate_inst = copy.deepcopy(inst)
    result = solve_instance(candidate_inst, candidate_options, progress_hook=None)
    soft_penalty = None
    if result.is_feasible and result.schedule:
        quality = dict((result.meta or {}).get("quality") or {})
        soft_penalty = int(
            quality.get(
                "soft_penalty",
                compute_penalty_breakdown(candidate_inst, result.schedule).get(
                    "total", 0
                ),
            )
        )
    return int(idx - 1), str(profile_id), candidate_options, result, soft_penalty


def _map_status_to_ui(status: int) -> int:
    if status == cp_model.UNKNOWN:
        return -1
    if status == cp_model.OPTIMAL:
        return 4
    if status == cp_model.FEASIBLE:
        return 0
    if status == 0:
        return -1
    return int(status)


def _is_feasible(raw_status: int) -> bool:
    return int(raw_status) in (int(cp_model.OPTIMAL), int(cp_model.FEASIBLE))


def _proof_status(raw_status: int) -> str:
    if int(raw_status) == int(cp_model.OPTIMAL):
        return "optimal"
    if int(raw_status) == int(cp_model.FEASIBLE):
        return "feasible_incumbent"
    if int(raw_status) == int(cp_model.INFEASIBLE):
        return "infeasible"
    if int(raw_status) == int(cp_model.MODEL_INVALID):
        return "model_invalid"
    return "no_solution"


def _fairness_feasibility_budget(
    total_budget_seconds: float | None,
    requested_seconds: float | None,
) -> float:
    """Reserve a bounded first-stage budget for a validated incumbent.

    Fairness-first uses an exact time/room decomposition.  A time-master
    incumbent can still be impossible to room, so spending the entire budget
    on the fairness objective can otherwise finish without any usable
    timetable.  The first stage is intentionally feasibility-only; unused
    time is immediately available to the fairness stage.
    """

    if requested_seconds is not None:
        requested = max(0.0, float(requested_seconds))
        if total_budget_seconds is None:
            return requested
        return min(requested, max(0.0, float(total_budget_seconds)))
    if total_budget_seconds is None:
        return 10.0
    total = max(0.0, float(total_budget_seconds))
    return min(
        total,
        10.0,
        max(min(2.0, total), total * 0.40),
    )


def _budget_after_reserves(
    requested_seconds: float,
    remaining_seconds: float | None,
    *reserve_seconds: float,
) -> float:
    """Bound a stage by the shared remainder after all later-phase reserves."""
    requested = max(0.0, float(requested_seconds))
    if remaining_seconds is None:
        return requested
    reserved = sum(max(0.0, float(value)) for value in reserve_seconds)
    return min(
        requested,
        max(0.0, float(remaining_seconds) - float(reserved)),
    )


def _research_rescue_seed(base_seed: int | None) -> int:
    """Derive a deterministic, non-repeating CP-SAT seed for feasibility rescue."""

    seed = 0 if base_seed is None else int(base_seed)
    return int(seed % 2_147_483_646) + 1


def _attempt_timing_meta(
    attempt: SolveAttempt, *, attempt_index: int
) -> Dict[str, Any]:
    return {
        "attempt_index": int(attempt_index),
        "room_mode": str(attempt.room_mode),
        "use_objective": bool(attempt.use_objective),
        "status_name": str(attempt.status_name),
        "proof_status": str(attempt.proof_status),
        "budget_seconds": attempt.budget_seconds,
        "elapsed_seconds": float(attempt.elapsed_seconds),
        "model_build_seconds": float(attempt.model_build_seconds),
        "setup_seconds": float(attempt.setup_seconds),
        "deadline_safety_margin_seconds": float(attempt.deadline_safety_margin_seconds),
        "search_budget_seconds": attempt.search_budget_seconds,
        "search_seconds": float(attempt.search_seconds),
        "deadline_overrun_seconds": float(attempt.deadline_overrun_seconds),
        "budget_exhausted": bool(attempt.budget_exhausted),
    }


def _extract_complete_validated_schedule(
    inst: Any,
    model: Any,
    solver: Any,
) -> tuple[Dict[int, Dict[str, Any]], List[str], float]:
    """Extract a complete strict-room incumbent and validate it independently."""

    validation_started = time.perf_counter()
    try:
        schedule = model.extract_solution(solver)
        errors = validate_schedule_against_instance(
            inst,
            schedule,
            strict_rooms=True,
            require_all_activities=True,
        )
    except Exception as exc:  # Defensive release boundary.
        schedule = {}
        errors = [f"incumbent extraction failed: {type(exc).__name__}: {exc}"]
    elapsed_seconds = float(time.perf_counter() - validation_started)
    if errors:
        return {}, list(errors), elapsed_seconds
    return (
        {int(activity_id): dict(info) for activity_id, info in schedule.items()},
        [],
        elapsed_seconds,
    )


def _objective_bound_info(
    solver: Any, raw_status: int, *, use_objective: bool
) -> Dict[str, float | None]:
    if not bool(use_objective):
        return {
            "objective_value": None,
            "best_objective_bound": None,
            "relative_gap": None,
        }
    objective_value: float | None = None
    best_bound: float | None = None
    if _is_feasible(int(raw_status)):
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
        denom = max(1.0, abs(float(objective_value)))
        relative_gap = max(0.0, float(objective_value) - float(best_bound)) / denom
    return {
        "objective_value": objective_value,
        "best_objective_bound": best_bound,
        "relative_gap": relative_gap,
    }


def _hard_conflict_errors(inst, schedule: Dict[int, Dict[str, Any]]) -> List[str]:
    return validate_schedule_against_instance(
        inst,
        schedule,
        strict_rooms=True,
        require_all_activities=False,
    )


def _canonical_profile_name(profile: str | None) -> str:
    raw = str(profile or "balanced").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "fast": "fast_feasible",
        "fast_feasible": "fast_feasible",
        "university_fast": "university_fast",
        "uni_fast": "university_fast",
        "university_quality": "university_quality",
        "uni_quality": "university_quality",
        "verify": "verification",
        "verification": "verification",
        "balanced": "balanced",
        "quality": "quality_first",
        "quality_first": "quality_first",
        "fair": "fairness_first",
        "fairness": "fairness_first",
        "fairness_first": "fairness_first",
        "research": "research_adaptive",
        "research_adaptive": "research_adaptive",
        "adaptive_lns": "research_adaptive",
    }
    return aliases.get(raw, "balanced")


def available_objective_profiles() -> List[Tuple[str, str]]:
    return [
        (profile_id, str(meta.get("label", profile_id)))
        for profile_id, meta in OBJECTIVE_PROFILE_PRESETS.items()
    ]


def _expanded_incremental_scope(
    inst,
    base_schedule: Dict[int, Dict[str, Any]],
    affected_activity_ids: Iterable[int],
) -> List[int]:
    affected = {
        int(a_id) for a_id in affected_activity_ids if int(a_id) in base_schedule
    }
    if not affected:
        return []
    impacted_weeks: set[int] = set()
    impacted_staff: set[int] = set()
    impacted_groups: set[int] = set()
    impacted_rooms: set[int] = set()
    for a_id in sorted(affected):
        info = base_schedule[int(a_id)]
        impacted_weeks.add(int(info.get("week", -1)))
        impacted_staff.add(int(info.get("staff_id", -1)))
        impacted_groups.update(int(g) for g in (info.get("group_ids", []) or []))
        room_id = info.get("room_id")
        if room_id is not None:
            impacted_rooms.add(int(room_id))

    expanded = set(affected)
    changed = True
    while changed:
        changed = False
        for a_id, info in base_schedule.items():
            a_int = int(a_id)
            if a_int in expanded:
                continue
            if int(info.get("week", -1)) not in impacted_weeks:
                continue
            shares_staff = int(info.get("staff_id", -1)) in impacted_staff
            shares_group = bool(
                {int(g) for g in (info.get("group_ids", []) or [])} & impacted_groups
            )
            room_id = info.get("room_id")
            shares_room = room_id is not None and int(room_id) in impacted_rooms
            if shares_staff or shares_group or shares_room:
                expanded.add(a_int)
                impacted_staff.add(int(info.get("staff_id", -1)))
                impacted_groups.update(
                    int(g) for g in (info.get("group_ids", []) or [])
                )
                if room_id is not None:
                    impacted_rooms.add(int(room_id))
                changed = True
    return sorted(expanded)


def _apply_incremental_scope(
    inst, options: SolveOptions
) -> tuple[Any, SolveOptions, Dict[str, Any]]:
    inst_work = copy.deepcopy(inst)
    meta: Dict[str, Any] = {"enabled": False}
    if not (
        options.freeze_unaffected
        and isinstance(options.base_schedule, dict)
        and options.affected_activity_ids
    ):
        return inst_work, options, meta

    expanded_scope = _expanded_incremental_scope(
        inst_work,
        options.base_schedule,
        options.affected_activity_ids,
    )
    if not expanded_scope:
        return inst_work, options, meta

    freeze_locks = build_freeze_locks(
        options.base_schedule,
        unlocked_activity_ids=expanded_scope,
    )
    explicit_locks = getattr(inst_work, "locked_activities", {}) or {}
    merged_locks = {
        int(a_id): dict(lock)
        for a_id, lock in freeze_locks.items()
        if isinstance(lock, dict)
    }
    for a_id, lock in explicit_locks.items():
        if not isinstance(lock, dict):
            continue
        merged = dict(merged_locks.get(int(a_id), {}))
        merged.update({str(k): v for k, v in lock.items()})
        merged_locks[int(a_id)] = merged
    inst_work.locked_activities = merged_locks
    meta = {
        "enabled": True,
        "requested_activities": sorted(
            int(a) for a in (options.affected_activity_ids or [])
        ),
        "expanded_activities": list(expanded_scope),
        "frozen_activities": int(len(merged_locks)),
    }
    return inst_work, options, meta


def _apply_objective_profile(
    inst, options: SolveOptions
) -> tuple[Any, SolveOptions, Dict[str, Any]]:
    inst_work = copy.deepcopy(inst)
    profile = _canonical_profile_name(
        options.objective_profile or getattr(inst_work, "objective_profile", "balanced")
    )
    inst_work.objective_profile = str(profile)
    preset = dict(
        OBJECTIVE_PROFILE_PRESETS.get(profile, OBJECTIVE_PROFILE_PRESETS["balanced"])
    )

    resolved = options
    if profile == "university_fast":
        resolved = replace(
            resolved,
            room_mode=(
                "decomposed" if week_partitioning_blockers(inst_work) else "partitioned"
            ),
            use_objective=False,
            retry_without_objective=False,
            phased_solve=False,
            improve_total_seconds=0.0,
        )
    elif profile == "university_quality":
        total_limit = max(0.0, float(resolved.time_limit_seconds or 180.0))
        feasibility_seconds = (
            resolved.feasibility_seconds
            if resolved.feasibility_seconds is not None
            else min(total_limit, max(1.0, total_limit * 0.75))
        )
        improve_total_seconds = (
            float(resolved.improve_total_seconds)
            if float(resolved.improve_total_seconds) > 0
            else max(0.0, total_limit - float(feasibility_seconds))
        )
        resolved = replace(
            resolved,
            room_mode="greedy",
            use_objective=True,
            retry_without_objective=True,
            phased_solve=True,
            feasibility_seconds=float(feasibility_seconds),
            improve_total_seconds=float(improve_total_seconds),
        )
    elif profile == "verification":
        resolved = replace(
            resolved,
            room_mode="cp_rooms",
            use_objective=True,
            retry_without_objective=True,
            phased_solve=False,
        )
    elif profile == "fast_feasible":
        resolved = replace(
            resolved,
            use_objective=False,
            retry_without_objective=False,
            phased_solve=False,
            improve_total_seconds=0.0,
        )
    elif profile == "balanced":
        if resolved.time_limit_seconds is not None:
            total_limit = max(0.0, float(resolved.time_limit_seconds))
            feasibility_seconds = (
                resolved.feasibility_seconds
                if resolved.feasibility_seconds is not None
                else min(total_limit, max(1.0, total_limit * 0.75))
            )
            feasibility_seconds = min(float(feasibility_seconds), total_limit)
            improve_total_seconds = (
                float(resolved.improve_total_seconds)
                if float(resolved.improve_total_seconds) > 0
                else max(0.0, total_limit - float(feasibility_seconds))
            )
            improve_total_seconds = min(
                float(improve_total_seconds),
                max(0.0, total_limit - float(feasibility_seconds)),
            )
        else:
            feasibility_seconds = resolved.feasibility_seconds
            improve_total_seconds = resolved.improve_total_seconds
        resolved = replace(
            resolved,
            use_objective=bool(resolved.use_objective),
            retry_without_objective=bool(resolved.retry_without_objective),
            phased_solve=bool(resolved.phased_solve),
            feasibility_seconds=feasibility_seconds,
            improve_total_seconds=float(improve_total_seconds),
        )
    elif profile == "quality_first":
        explicit_limit = resolved.time_limit_seconds is not None
        total_limit = max(0.0, float(resolved.time_limit_seconds or 180.0))
        if explicit_limit:
            feasibility_seconds = (
                resolved.feasibility_seconds
                if resolved.feasibility_seconds is not None
                else min(total_limit, max(1.0, total_limit * 0.65))
            )
            feasibility_seconds = min(float(feasibility_seconds), total_limit)
            improve_total_seconds = (
                float(resolved.improve_total_seconds)
                if float(resolved.improve_total_seconds) > 0
                else max(0.0, total_limit - float(feasibility_seconds))
            )
            improve_total_seconds = min(
                float(improve_total_seconds),
                max(0.0, total_limit - float(feasibility_seconds)),
            )
        else:
            feasibility_seconds = (
                resolved.feasibility_seconds
                if resolved.feasibility_seconds is not None
                else max(30.0, total_limit * 0.65)
            )
            improve_total_seconds = (
                float(resolved.improve_total_seconds)
                if float(resolved.improve_total_seconds) > 0
                else max(30.0, total_limit - float(feasibility_seconds))
            )
        resolved = replace(
            resolved,
            use_objective=True,
            retry_without_objective=True,
            phased_solve=True,
            feasibility_seconds=float(feasibility_seconds),
            improve_total_seconds=float(improve_total_seconds),
            improve_slice_seconds=max(float(resolved.improve_slice_seconds), 6.0),
            improve_iters_per_slice=max(int(resolved.improve_iters_per_slice), 1500),
            improve_max_rounds=max(int(resolved.improve_max_rounds), 16),
        )
    elif profile == "fairness_first":
        resolved = replace(
            resolved,
            room_mode="decomposed",
            use_objective=True,
            retry_without_objective=False,
            phased_solve=False,
            improve_total_seconds=0.0,
        )
    elif profile == "research_adaptive":
        total_limit = max(
            0.0,
            float(
                resolved.time_limit_seconds
                if resolved.time_limit_seconds is not None
                else 60.0
            ),
        )
        incumbent_seconds = min(30.0, max(0.0, total_limit * 0.30))
        adaptive_seconds = min(
            max(0.0, total_limit - incumbent_seconds),
            max(
                0.0,
                float(resolved.adaptive_lns_seconds)
                if float(resolved.adaptive_lns_seconds) > 0
                else total_limit - incumbent_seconds,
            ),
        )
        resolved = replace(
            resolved,
            room_mode=(
                "decomposed" if week_partitioning_blockers(inst_work) else "partitioned"
            ),
            use_objective=False,
            retry_without_objective=False,
            phased_solve=False,
            time_limit_seconds=float(incumbent_seconds),
            improve_total_seconds=0.0,
            adaptive_lns_seconds=float(adaptive_seconds),
            adaptive_lns_slice_seconds=max(
                0.25, float(resolved.adaptive_lns_slice_seconds)
            ),
            adaptive_lns_max_rounds=max(1, int(resolved.adaptive_lns_max_rounds)),
        )

    return (
        inst_work,
        resolved,
        {
            "id": str(profile),
            "label": str(preset.get("label", profile)),
        },
    )


def _solve_cache_key(inst, options: SolveOptions) -> str:
    payload = {
        "instance": instance_to_json(inst),
        "hard_constraints": dict(getattr(inst, "hard_constraints", {}) or {}),
        "soft_weights": dict(getattr(inst, "soft_weights", {}) or {}),
        "objective_profile": str(
            getattr(inst, "objective_profile", "balanced") or "balanced"
        ),
        "options": dict(options.__dict__),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _fixed_time_schedule_fingerprint(schedule: Dict[int, Dict[str, Any]]) -> str:
    """Identify the exact pre-finalization lecture-time incumbent, excluding rooms."""

    payload = [
        [
            int(activity_id),
            int(row["week"]),
            str(row["day"]),
            int(row["slot"]),
            int(row["duration"]),
        ]
        for activity_id, row in sorted(schedule.items())
    ]
    encoded = json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_solve_attempt(
    inst,
    *,
    room_mode: str,
    use_objective: bool,
    options: SolveOptions,
) -> tuple[Any, Any, int, SolveAttempt]:
    attempt_started = time.perf_counter()
    budget_seconds = (
        None
        if options.time_limit_seconds is None
        else max(0.0, float(options.time_limit_seconds))
    )
    deadline = (
        None
        if budget_seconds is None
        else float(attempt_started) + float(budget_seconds)
    )
    build_started = time.perf_counter()
    model = build_timetable_solver(
        inst,
        room_mode=str(room_mode),
        use_objective=bool(use_objective),
    )
    model_build_seconds = float(time.perf_counter() - build_started)
    setup_started = time.perf_counter()
    if isinstance(options.base_schedule, dict) and hasattr(model, "add_solution_hint"):
        model.add_solution_hint(options.base_schedule, include_rooms=True)
    setup_seconds = float(time.perf_counter() - setup_started)
    deadline_safety_margin_seconds = (
        0.0
        if budget_seconds is None
        else min(0.25, max(0.002, float(budget_seconds) * 0.03))
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
    search_started = time.perf_counter()
    if search_budget_seconds is not None and search_budget_seconds <= 0:
        solver = cp_model.CpSolver()
        raw_status = int(cp_model.UNKNOWN)
        search_seconds = 0.0
    else:
        solver, raw_status = model.solve(
            time_limit_seconds=search_budget_seconds,
            workers=options.workers,
            random_seed=options.random_seed,
            log_progress=options.log_progress,
        )
        search_seconds = float(time.perf_counter() - search_started)
    elapsed_seconds = float(time.perf_counter() - attempt_started)
    deadline_overrun_seconds = (
        0.0 if deadline is None else max(0.0, time.perf_counter() - float(deadline))
    )
    objective_info = _objective_bound_info(
        solver,
        int(raw_status),
        use_objective=bool(use_objective),
    )
    attempt = SolveAttempt(
        room_mode=str(getattr(model, "room_mode", room_mode)),
        use_objective=bool(use_objective),
        time_limit_seconds=options.time_limit_seconds,
        raw_status=int(raw_status),
        objective_value=objective_info["objective_value"],
        best_objective_bound=objective_info["best_objective_bound"],
        relative_gap=objective_info["relative_gap"],
        status_name=str(cp_model.CpSolverStatus(int(raw_status))),
        proof_status=_proof_status(int(raw_status)),
        budget_seconds=budget_seconds,
        elapsed_seconds=elapsed_seconds,
        model_build_seconds=model_build_seconds,
        setup_seconds=setup_seconds,
        deadline_safety_margin_seconds=float(deadline_safety_margin_seconds),
        search_budget_seconds=search_budget_seconds,
        search_seconds=search_seconds,
        deadline_overrun_seconds=float(deadline_overrun_seconds),
        budget_exhausted=bool(
            deadline is not None
            and time.perf_counter() >= float(deadline)
            and not _is_feasible(int(raw_status))
        ),
    )
    return model, solver, int(raw_status), attempt


def _build_quality_meta(
    inst,
    schedule: Dict[int, Dict[str, Any]],
    *,
    hard_conflicts: int = 0,
    base_schedule: Dict[int, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    breakdown = compute_penalty_breakdown(inst, schedule)
    sla = evaluate_schedule_sla(inst, schedule, hard_conflicts=int(hard_conflicts))
    quality: Dict[str, Any] = {
        "soft_penalty": int(breakdown.get("total", 0)),
        "breakdown": dict(breakdown),
        "sla": dict(sla),
    }
    benchmark_family = str(
        (getattr(inst, "sla_targets", {}) or {}).get("benchmark_family", "")
    )
    if benchmark_family.startswith("ITC-2007"):
        from benchmarks.itc2007 import score_itc2007_instance_schedule

        official = score_itc2007_instance_schedule(inst, schedule)
        quality["benchmark_objective"] = {
            "id": "itc2007_official",
            "components": official.to_dict(),
        }
    if isinstance(base_schedule, dict) and base_schedule:
        quality["comparison_to_base"] = explain_solution_ranking(
            inst,
            base_schedule,
            schedule,
            base_label="base",
            candidate_label="current",
        )
    return quality


def _adaptive_acceptance_score(
    inst,
    schedule: Dict[int, Dict[str, Any]],
) -> tuple[int, str]:
    """Return the objective that the active exact model is intended to improve."""

    benchmark_family = str(
        (getattr(inst, "sla_targets", {}) or {}).get("benchmark_family", "")
    )
    if benchmark_family.startswith("ITC-2007"):
        from benchmarks.itc2007 import score_itc2007_instance_schedule

        return int(
            score_itc2007_instance_schedule(inst, schedule).total
        ), "itc2007_official"
    return int(
        compute_penalty_breakdown(inst, schedule).get("total", 0)
    ), "planora_generic"


def _room_component_snapshot(
    inst,
    schedule: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    """Return exact active-objective room terms for room-dive telemetry."""
    score, objective_id = _adaptive_acceptance_score(inst, schedule)
    if objective_id == "itc2007_official":
        from benchmarks.itc2007 import score_itc2007_instance_schedule

        components = score_itc2007_instance_schedule(inst, schedule).to_dict()
        return {
            "objective_id": str(objective_id),
            "objective_total": int(score),
            "room_capacity": int(components.get("room_capacity", 0)),
            "room_stability": int(components.get("room_stability", 0)),
            "room_total": int(components.get("room_capacity", 0))
            + int(components.get("room_stability", 0)),
        }
    breakdown = compute_penalty_breakdown(inst, schedule)
    return {
        "objective_id": str(objective_id),
        "objective_total": int(score),
        "room_consistency": int(breakdown.get("room_consistency", 0)),
        "room_total": int(breakdown.get("room_consistency", 0)),
    }


def _run_fixed_time_room_dive(
    inst,
    schedule: Dict[int, Dict[str, Any]],
    reusable_model: TimetableSolver | None,
    *,
    budget_seconds: float,
    final_deadline: float | None,
    workers: int,
    seed: int,
    completion_reserve_seconds: float = 0.0,
    strategy: str = "oracle_then_cp",
) -> tuple[Dict[int, Dict[str, Any]], Dict[str, Any]]:
    """Optimize rooms only and retain the incumbent unless quality improves."""
    started = time.perf_counter()
    resolved_strategy = _normalize_fixed_time_room_strategy(strategy)
    requested_budget = max(0.0, float(budget_seconds))
    completion_reserve = max(0.0, float(completion_reserve_seconds))
    shared_deadline_remaining_at_start = (
        None
        if final_deadline is None
        else max(0.0, float(final_deadline) - float(started))
    )
    room_dive_outer_deadline = (
        None
        if final_deadline is None
        else float(final_deadline) - float(completion_reserve)
    )
    effective_deadline = (
        float(started) + float(requested_budget)
        if room_dive_outer_deadline is None
        else min(
            float(room_dive_outer_deadline),
            float(started) + float(requested_budget),
        )
    )
    admission_required_seconds = float(requested_budget) + (
        0.0 if final_deadline is None else float(completion_reserve)
    )
    admission_shortfall_seconds = (
        None
        if shared_deadline_remaining_at_start is None
        else max(
            0.0,
            float(admission_required_seconds)
            - float(shared_deadline_remaining_at_start),
        )
    )
    admission_passed = bool(
        requested_budget > 0
        and (
            shared_deadline_remaining_at_start is None
            or float(shared_deadline_remaining_at_start)
            >= float(admission_required_seconds)
        )
    )
    base_meta: Dict[str, Any] = {
        "enabled": True,
        "strategy": str(resolved_strategy),
        "attempted": False,
        "status": "NOT_STARTED",
        "budget_seconds": float(requested_budget),
        "shared_deadline_remaining_at_start_seconds": (
            None
            if shared_deadline_remaining_at_start is None
            else float(shared_deadline_remaining_at_start)
        ),
        "completion_reserve_seconds": float(completion_reserve),
        "admission_required_seconds": float(admission_required_seconds),
        "admission_shortfall_seconds": admission_shortfall_seconds,
        "admission_scope": "setup_search_validation_and_outer_completion",
        "admission_policy": "full_requested_reserve_required",
        "admission_passed": bool(admission_passed),
        "effective_room_dive_deadline_seconds": float(effective_deadline),
        "effective_room_dive_window_seconds": max(
            0.0, float(effective_deadline) - float(started)
        ),
        "acceptance_objective": None,
        "pre_score": None,
        "post_score": None,
        "returned_score": None,
        "candidate_score": None,
        "improvement": 0,
        "candidate_improvement": None,
        "pre_room_components": None,
        "post_room_components": None,
        "returned_room_components": None,
        "candidate_room_components": None,
        "validation": {
            "attempted": False,
            "valid": None,
            "error_count": 0,
            "errors": [],
        },
        "fixed_starts_preserved": None,
        "returned_source": "incumbent",
        "incumbent_fixed_time_fingerprint": _fixed_time_schedule_fingerprint(schedule),
        "incumbent_room_assignment": [
            [int(activity_id), int(schedule[int(activity_id)]["room_id"])]
            for activity_id in sorted(schedule)
            if schedule[int(activity_id)].get("room_id") is not None
        ],
        "oracle": None,
    }

    def finish(status: str, **updates: Any):
        elapsed = float(time.perf_counter() - started)
        base_meta.update(updates)
        base_meta.update(
            {
                "status": str(status),
                "elapsed_seconds": float(elapsed),
                "deadline_remaining_seconds": max(
                    0.0, float(effective_deadline) - time.perf_counter()
                ),
                "deadline_overrun_seconds": max(
                    0.0, time.perf_counter() - float(effective_deadline)
                ),
                "shared_deadline_remaining_seconds": (
                    None
                    if final_deadline is None
                    else max(0.0, float(final_deadline) - time.perf_counter())
                ),
            }
        )
        return dict(base_meta)

    # Preserve the legacy unsupported-model result when there is not even an
    # admitted window in which the model-independent oracle could run.
    if reusable_model is None and not admission_passed:
        return schedule, finish(
            "SKIPPED_UNSUPPORTED",
            skip_reason="reusable_full_objective_model_unavailable",
        )
    if requested_budget <= 0:
        return schedule, finish(
            "SKIPPED_INSUFFICIENT_BUDGET",
            skip_reason="no_finalization_reserve_remaining",
        )
    if not admission_passed:
        return schedule, finish(
            "SKIPPED_INSUFFICIENT_BUDGET",
            skip_reason="full_finalization_and_completion_reserve_unavailable",
        )
    if time.perf_counter() >= float(effective_deadline):
        return schedule, finish(
            "SKIPPED_INSUFFICIENT_BUDGET",
            skip_reason="no_finalization_reserve_remaining",
        )

    pre_score, objective_id = _adaptive_acceptance_score(inst, schedule)
    pre_room_components = _room_component_snapshot(inst, schedule)
    base_meta.update(
        {
            "acceptance_objective": str(objective_id),
            "pre_score": int(pre_score),
            "post_score": int(pre_score),
            "returned_score": int(pre_score),
            "pre_room_components": dict(pre_room_components),
            "post_room_components": dict(pre_room_components),
            "returned_room_components": dict(pre_room_components),
        }
    )

    if resolved_strategy == "control":
        return schedule, finish(
            "CONTROL_RESERVE_ONLY",
            skip_reason="matched_finalization_reserve_without_room_optimization",
        )

    # Eligible fixed-time unit-duration schedules admit exact polynomial
    # assignment blocks. Try that smaller certificate-carrying oracle unless
    # the caller explicitly selected the CP-only ablation. Unsupported cases
    # fall through only for the oracle-then-CP production dispatcher.
    effective_window = max(0.0, float(effective_deadline) - float(started))
    safety_margin = min(0.10, max(0.002, effective_window * 0.20))
    oracle_deadline = max(
        float(started), float(effective_deadline) - float(safety_margin)
    )
    oracle_returned_after_deadline = False
    oracle_result = None
    oracle_meta: Dict[str, Any] = {
        "status": "not_requested",
        "error": None,
        "improved": False,
    }
    if resolved_strategy != "cp_only":
        try:
            oracle_result = optimize_fixed_time_rooms(
                inst,
                schedule,
                deadline=float(oracle_deadline),
                max_sweeps=32,
                run_reverse_start=True,
                run_capacity_start=False,
            )
            oracle_returned_after_deadline = bool(
                time.perf_counter() >= float(effective_deadline)
            )
            if oracle_returned_after_deadline:
                oracle_meta = {
                    "status": "deadline_exhausted",
                    "error": "oracle_returned_after_effective_deadline",
                    "improved": False,
                    "service_acceptance_rejected_deadline": True,
                }
            else:
                oracle_meta = oracle_result.to_dict(deadline=float(effective_deadline))
        except Exception as exc:  # fail closed; fallback is strategy-controlled
            oracle_result = None
            oracle_meta = {
                "status": "internal_error",
                "error": f"{type(exc).__name__}: {exc}",
                "improved": False,
            }
    base_meta["oracle"] = dict(oracle_meta)
    base_meta["attempted"] = bool(
        oracle_result is not None and oracle_result.eligibility.eligible
    )

    if oracle_returned_after_deadline:
        return schedule, finish(
            "REJECTED_DEADLINE_OVERRUN",
            returned_source="incumbent",
            skip_reason="oracle_candidate_completed_after_effective_deadline",
        )

    if (
        oracle_result is not None
        and oracle_result.improved
        and oracle_result.best_schedule is not None
    ):
        candidate = oracle_result.best_schedule
        validation_started = time.perf_counter()
        errors = validate_schedule_against_instance(
            inst,
            candidate,
            strict_rooms=True,
            require_all_activities=True,
        )
        validation_seconds = float(time.perf_counter() - validation_started)
        fixed_starts_preserved = all(
            tuple(
                candidate.get(activity_id, {}).get(field)
                for field in ("week", "day", "slot", "duration")
            )
            == tuple(
                schedule.get(activity_id, {}).get(field)
                for field in ("week", "day", "slot", "duration")
            )
            for activity_id in inst.activities
        )
        candidate_score, candidate_objective = _adaptive_acceptance_score(
            inst, candidate
        )
        candidate_components = _room_component_snapshot(inst, candidate)
        comparison_meta = {
            "solver_status": "STRUCTURAL_ORACLE",
            "search_seconds": float(
                (oracle_result.timing or {}).get("elapsed_seconds", 0.0) or 0.0
            ),
            "proof_status": str(oracle_result.proof_status),
            "proof_scope": str(oracle_result.proof_scope),
            "best_objective_bound": (
                None
                if oracle_result.room_lower_bound is None
                else int(pre_score)
                - int(pre_room_components.get("room_total", 0))
                + int(oracle_result.room_lower_bound)
            ),
            "candidate_score": int(candidate_score),
            "candidate_room_components": dict(candidate_components),
            "candidate_improvement": int(pre_score) - int(candidate_score),
            "fixed_starts_preserved": bool(fixed_starts_preserved),
            "validation_seconds": float(validation_seconds),
            "validation": {
                "attempted": True,
                "valid": bool(
                    not errors
                    and fixed_starts_preserved
                    and oracle_result.objective_parity is True
                ),
                "error_count": int(len(errors)),
                "errors": [str(value) for value in errors[:20]],
            },
        }
        if time.perf_counter() >= float(effective_deadline):
            oracle_meta["service_acceptance_rejected_deadline"] = True
            base_meta["oracle"] = dict(oracle_meta)
            return schedule, finish(
                "REJECTED_DEADLINE_OVERRUN",
                returned_source="incumbent",
                skip_reason="oracle_candidate_completed_after_effective_deadline",
                **comparison_meta,
            )
        if (
            str(candidate_objective) == str(objective_id)
            and not errors
            and fixed_starts_preserved
            and oracle_result.objective_parity is True
            and int(candidate_score) < int(pre_score)
        ):
            return candidate, finish(
                "ACCEPTED_IMPROVEMENT",
                returned_source="fixed_time_room_oracle",
                post_score=int(candidate_score),
                returned_score=int(candidate_score),
                improvement=int(pre_score) - int(candidate_score),
                post_room_components=dict(candidate_components),
                returned_room_components=dict(candidate_components),
                **comparison_meta,
            )
        oracle_meta["service_acceptance_rejected"] = True
        oracle_meta["service_candidate_objective"] = str(candidate_objective)
        oracle_meta["service_validation_errors"] = [str(value) for value in errors[:20]]
        base_meta["oracle"] = dict(oracle_meta)

    if resolved_strategy == "oracle_only":
        if oracle_result is not None and oracle_result.status == "no_improvement":
            return schedule, finish(
                "REJECTED_NO_IMPROVEMENT",
                skip_reason="structural_oracle_proved_no_strict_improvement",
                proof_status=str(oracle_result.proof_status),
                proof_scope=str(oracle_result.proof_scope),
                fixed_starts_preserved=oracle_result.fixed_starts_preserved,
                validation={
                    "attempted": bool(oracle_result.validation_attempted),
                    "valid": bool(not oracle_result.validation_errors),
                    "error_count": len(oracle_result.validation_errors),
                    "errors": list(oracle_result.validation_errors),
                },
            )
        if oracle_result is not None and not oracle_result.eligibility.eligible:
            return schedule, finish(
                "SKIPPED_UNSUPPORTED",
                skip_reason="structural_oracle_ineligible",
            )
        if oracle_result is None:
            return schedule, finish(
                "ERROR",
                skip_reason="structural_oracle_failed_without_cp_fallback",
            )
        return schedule, finish(
            "REJECTED_ORACLE_CANDIDATE",
            skip_reason="structural_oracle_candidate_failed_acceptance",
        )

    if reusable_model is None:
        if oracle_result is not None and oracle_result.status == "no_improvement":
            return schedule, finish(
                "REJECTED_NO_IMPROVEMENT",
                skip_reason="structural_oracle_proved_no_strict_improvement",
                proof_status=str(oracle_result.proof_status),
                proof_scope=str(oracle_result.proof_scope),
                fixed_starts_preserved=oracle_result.fixed_starts_preserved,
                validation={
                    "attempted": bool(oracle_result.validation_attempted),
                    "valid": bool(not oracle_result.validation_errors),
                    "error_count": len(oracle_result.validation_errors),
                    "errors": list(oracle_result.validation_errors),
                },
            )
        return schedule, finish(
            "SKIPPED_UNSUPPORTED",
            skip_reason="reusable_full_objective_model_unavailable",
        )
    if reusable_model.room_mode != "cp_rooms" or not reusable_model.use_objective:
        return schedule, finish(
            "SKIPPED_UNSUPPORTED",
            skip_reason="room_dive_requires_cp_rooms_and_active_objective",
        )

    try:
        setup_started = time.perf_counter()
        assumption_meta = reusable_model.set_fixed_time_room_assumptions(schedule)
        setup_seconds = float(time.perf_counter() - setup_started)
        search_budget = max(
            0.0,
            float(effective_deadline) - time.perf_counter() - float(safety_margin),
        )
        base_meta.update(
            {
                "assumptions": dict(assumption_meta),
                "setup_seconds": float(setup_seconds),
                "deadline_safety_margin_seconds": float(safety_margin),
                "search_budget_seconds": float(search_budget),
            }
        )
        if search_budget <= 0:
            return schedule, finish(
                "SKIPPED_INSUFFICIENT_BUDGET",
                skip_reason="assumption_setup_consumed_finalization_reserve",
                search_seconds=0.0,
            )

        base_meta["attempted"] = True
        search_started = time.perf_counter()
        solver, raw_status = reusable_model.solve(
            time_limit_seconds=float(search_budget),
            workers=max(1, min(4, int(workers or 1))),
            random_seed=int(seed),
            log_progress=False,
        )
        search_seconds = float(time.perf_counter() - search_started)
        status_name = str(cp_model.CpSolverStatus(int(raw_status)))
        objective_info = _objective_bound_info(
            solver,
            int(raw_status),
            use_objective=True,
        )
        solve_meta = {
            "raw_status": int(raw_status),
            "solver_status": str(status_name),
            "search_seconds": float(search_seconds),
            "proof_status": _proof_status(int(raw_status)),
            "proof_scope": "fixed_time_room_subproblem",
            **objective_info,
        }
        if not _is_feasible(int(raw_status)):
            return schedule, finish("NO_FEASIBLE_CANDIDATE", **solve_meta)

        candidate = reusable_model.extract_solution(solver)
        validation_started = time.perf_counter()
        errors = validate_schedule_against_instance(
            inst,
            candidate,
            strict_rooms=True,
            require_all_activities=True,
        )
        validation_seconds = float(time.perf_counter() - validation_started)
        fixed_starts_preserved = all(
            str(candidate.get(activity_id, {}).get("day"))
            == str(schedule.get(activity_id, {}).get("day"))
            and int(candidate.get(activity_id, {}).get("slot", -1))
            == int(schedule.get(activity_id, {}).get("slot", -2))
            for activity_id in inst.activities
        )
        candidate_score, candidate_objective = _adaptive_acceptance_score(
            inst,
            candidate,
        )
        candidate_components = _room_component_snapshot(inst, candidate)
        comparison_meta = {
            **solve_meta,
            "candidate_score": int(candidate_score),
            "candidate_room_components": dict(candidate_components),
            "candidate_improvement": int(pre_score) - int(candidate_score),
            "fixed_starts_preserved": bool(fixed_starts_preserved),
            "validation_seconds": float(validation_seconds),
            "validation": {
                "attempted": True,
                "valid": bool(not errors and fixed_starts_preserved),
                "error_count": int(len(errors)),
                "errors": [str(value) for value in errors[:20]],
            },
        }
        if time.perf_counter() >= float(effective_deadline):
            return schedule, finish(
                "REJECTED_DEADLINE_OVERRUN",
                returned_source="incumbent",
                skip_reason="cp_candidate_completed_after_effective_deadline",
                **comparison_meta,
            )
        if str(candidate_objective) != str(objective_id):
            return schedule, finish(
                "REJECTED_OBJECTIVE_MISMATCH",
                returned_source="incumbent",
                **comparison_meta,
            )
        if errors or not fixed_starts_preserved:
            return schedule, finish(
                "REJECTED_VALIDATION",
                returned_source="incumbent",
                **comparison_meta,
            )
        if int(candidate_score) >= int(pre_score):
            return schedule, finish(
                "REJECTED_NO_IMPROVEMENT",
                returned_source="incumbent",
                **comparison_meta,
            )
        return candidate, finish(
            "ACCEPTED_IMPROVEMENT",
            returned_source="fixed_time_room_dive",
            post_score=int(candidate_score),
            returned_score=int(candidate_score),
            improvement=int(pre_score) - int(candidate_score),
            post_room_components=dict(candidate_components),
            returned_room_components=dict(candidate_components),
            **comparison_meta,
        )
    except Exception as exc:
        return schedule, finish(
            "ERROR",
            error=f"{type(exc).__name__}: {exc}",
            returned_source="incumbent",
        )


def _adaptive_lns_neighborhood_policy(
    inst,
    options: SolveOptions,
    *,
    activity_count: int,
) -> tuple[tuple[int, ...], Dict[str, Any]]:
    """Resolve an explicit, fail-closed adaptive-arm policy with telemetry."""

    requested_sizes = tuple(
        int(value) for value in options.adaptive_lns_neighborhood_sizes
    )
    configured_sizes = tuple(sorted({max(1, int(value)) for value in requested_sizes}))
    sla = getattr(inst, "sla_targets", {}) or {}
    imported_itc2007 = bool(
        str(sla.get("benchmark_family", "")).startswith("ITC-2007")
        and isinstance(sla.get("itc2007"), dict)
    )
    compact_switch_enabled = hard_flag(
        inst,
        "enable_itc2007_compact_adaptive_arms",
        False,
    )
    uses_default_configuration = (
        configured_sizes == _DEFAULT_ADAPTIVE_LNS_NEIGHBORHOOD_SIZES
    )

    if not uses_default_configuration:
        selected_sizes = configured_sizes
        applied = False
        reason = "explicit_neighborhood_sizes_preserved"
    elif not imported_itc2007:
        selected_sizes = configured_sizes
        applied = False
        reason = "not_imported_itc2007"
    elif not compact_switch_enabled:
        selected_sizes = configured_sizes
        applied = False
        reason = "itc2007_compact_candidate_disabled"
    else:
        selected_sizes = _ITC2007_COMPACT_ADAPTIVE_LNS_NEIGHBORHOOD_SIZES
        applied = True
        reason = "itc2007_compact_candidate_explicitly_enabled"

    effective_sizes = tuple(
        sorted(
            {
                min(max(1, int(activity_count)), max(1, int(value)))
                for value in selected_sizes
            }
        )
    )
    telemetry = {
        "requested_sizes": [int(value) for value in requested_sizes],
        "configured_sizes": [int(value) for value in configured_sizes],
        "effective_sizes": [int(value) for value in effective_sizes],
        "activity_count": int(activity_count),
        "imported_itc2007_eligible": bool(imported_itc2007),
        "compact_switch_enabled": bool(compact_switch_enabled),
        "applied": bool(applied),
        "reason": str(reason),
    }
    return effective_sizes, telemetry


def _itc2007_constructive_initializer_strategy_policy(
    inst,
    *,
    activity_count: int,
    requested_strategy: str = "balanced",
) -> Dict[str, Any]:
    """Select the initial coloring heuristic from lossless model structure.

    Large imported CTT instances benefit from establishing minimum working
    days before projected search.  Keep the established balanced constructor
    everywhere else, including enriched or otherwise non-lossless models.
    """

    requested = str(requested_strategy or "balanced")
    placeholder_schedule = {
        int(activity_id): {} for activity_id in getattr(inst, "activities", {})
    }
    try:
        lossless_eligible, raw_reasons = itc2007_fixed_time_room_cp_eligibility(
            inst,
            placeholder_schedule,
        )
        eligibility_reasons = tuple(str(value) for value in raw_reasons)
    except Exception as exc:
        lossless_eligible = False
        eligibility_reasons = (f"eligibility_error:{type(exc).__name__}:{exc}",)

    large_activity_threshold = 256
    is_large = int(activity_count) > int(large_activity_threshold)
    effective = requested
    applied = False
    if requested != "balanced":
        reason = "explicit_strategy_preserved"
    elif not lossless_eligible:
        reason = "requires_lossless_itc2007_import"
    elif not is_large:
        reason = "small_lossless_itc2007_balanced_default"
    else:
        effective = "spread"
        applied = True
        reason = "large_lossless_itc2007_day_spread"

    return {
        "requested_strategy": str(requested),
        "effective_strategy": str(effective),
        "reason": str(reason),
        "applied": bool(applied),
        "activity_count": int(activity_count),
        "large_activity_threshold": int(large_activity_threshold),
        "lossless_import_eligible": bool(lossless_eligible),
        "eligibility_reasons": list(eligibility_reasons),
    }


def _projected_feedback_phase_policy(
    *,
    activity_count: int,
    available_seconds: float,
    feedback_enabled: bool,
    requested_feedback_seconds: float,
    requested_feedback_rounds: int,
) -> Dict[str, Any]:
    """Reserve a deterministic tail window for room-aware feedback.

    The projected optimizer and the feedback search share one adaptive deadline.
    Reserving the feedback tail before projected search starts prevents the first
    phase from consuming the second phase's entire budget.  Small instances can
    profit from several feedback rounds; larger instances get one bounded round
    followed by consolidation so their projected search still owns most of the
    deadline.
    """

    available = max(0.0, float(available_seconds))
    requested_seconds = max(0.0, float(requested_feedback_seconds))
    configured_rounds = max(0, int(requested_feedback_rounds))
    is_small = int(activity_count) <= 200
    reserve_fraction = 0.40 if is_small else 0.18
    reserve_cap_seconds = 3.50 if is_small else 1.60
    effective_rounds = configured_rounds if is_small else min(1, configured_rounds)
    enabled = bool(feedback_enabled) and requested_seconds > 0.0 and available > 0.0
    reserved_seconds = (
        min(
            requested_seconds,
            reserve_cap_seconds,
            available * reserve_fraction,
        )
        if enabled
        else 0.0
    )
    return {
        "enabled": bool(enabled),
        "size_class": "small" if is_small else "large",
        "requested_seconds": float(requested_seconds),
        "configured_rounds": int(configured_rounds),
        "effective_rounds": int(effective_rounds),
        "reserve_fraction": float(reserve_fraction),
        "reserve_cap_seconds": float(reserve_cap_seconds),
        "reserved_seconds": float(reserved_seconds),
        "projected_reserved_seconds": max(0.0, available - reserved_seconds),
        "run_consolidation": bool(enabled),
    }


def _projected_compound_phase_policy(
    *,
    activity_count: int,
    available_seconds: float,
    eligible: bool,
) -> Dict[str, Any]:
    """Reserve a fixed safe tail for atomic ITC-2007 barrier escapes."""

    available = max(0.0, float(available_seconds))
    is_small = int(activity_count) <= 200
    target_seconds = 0.65 if is_small else 0.35
    minimum_window_seconds = 1.00 if is_small else 2.00
    enabled = bool(eligible) and available >= minimum_window_seconds
    reserved_seconds = float(target_seconds if enabled else 0.0)
    return {
        "enabled": bool(enabled),
        "eligible": bool(eligible),
        "reason": (
            "eligible_safe_tail_reserved"
            if enabled
            else (
                "ineligible" if not bool(eligible) else "insufficient_shared_deadline"
            )
        ),
        "size_class": "small" if is_small else "large",
        "available_seconds": float(available),
        "target_seconds": float(target_seconds),
        "minimum_window_seconds": float(minimum_window_seconds),
        "reserved_seconds": float(reserved_seconds),
        "upstream_reserved_seconds": max(
            0.0,
            float(available) - float(reserved_seconds),
        ),
    }


def _projected_rooted_adjacency_tail_policy(
    *,
    activity_count: int,
    available_seconds: float,
    exchangeable_eligible: bool,
    eligibility_reasons: Iterable[str] = (),
    feedback_enabled: bool,
    requested_feedback_seconds: float,
    requested_feedback_rounds: int,
) -> Dict[str, Any]:
    """Reserve a bounded dense-CTT adjacency/feedback continuation tail.

    The tail consumes up to two additional caller-requested feedback rounds
    around deterministic representation-rooted adjacency descents.  It is kept
    off small and enriched instances so their established compound, exact-room,
    and coordinated quality-tail policies remain unchanged.
    """

    available = max(0.0, float(available_seconds))
    configured_rounds = max(0, int(requested_feedback_rounds))
    normalized_reasons = tuple(str(value) for value in eligibility_reasons)
    dense_exchangeable = bool(exchangeable_eligible) and int(activity_count) > 256
    feedback_requested = (
        bool(feedback_enabled) and float(requested_feedback_seconds) > 0.0
    )
    continuation_rounds = min(2, max(0, configured_rounds - 1))
    target_seconds = 1.45 if continuation_rounds >= 2 else 1.10
    minimum_window_seconds = 3.35 if continuation_rounds >= 2 else 3.0
    enabled = bool(
        dense_exchangeable
        and feedback_requested
        and configured_rounds >= 2
        and available >= float(minimum_window_seconds)
    )
    if enabled:
        reason = "dense_exchangeable_rooted_feedback_tail_reserved"
    elif not bool(exchangeable_eligible):
        reason = (
            "itc2007_lectures_not_exchangeable"
            if "itc2007_lectures_not_exchangeable" in normalized_reasons
            else "requires_exchangeable_lossless_itc2007_import"
        )
    elif int(activity_count) <= 256:
        reason = "requires_more_than_256_activities"
    elif not feedback_requested:
        reason = "feedback_disabled_or_zero_budget"
    elif configured_rounds < 2:
        reason = "additional_feedback_round_not_requested"
    else:
        reason = "insufficient_shared_deadline"
    reserved_seconds = float(target_seconds if enabled else 0.0)
    return {
        "enabled": bool(enabled),
        "eligible": bool(dense_exchangeable),
        "reason": str(reason),
        "size_class": "dense_large" if int(activity_count) > 256 else "other",
        "activity_count": int(activity_count),
        "activity_threshold": 256,
        "lecture_exchange_eligible": bool(exchangeable_eligible),
        "eligibility_reasons": list(normalized_reasons),
        "feedback_enabled": bool(feedback_enabled),
        "requested_feedback_seconds": max(0.0, float(requested_feedback_seconds)),
        "configured_feedback_rounds": int(configured_rounds),
        "continuation_feedback_rounds": int(continuation_rounds if enabled else 0),
        "available_seconds": float(available),
        "target_seconds": float(target_seconds),
        "minimum_window_seconds": float(minimum_window_seconds),
        "reserved_seconds": float(reserved_seconds),
        "upstream_reserved_seconds": max(
            0.0, float(available) - float(reserved_seconds)
        ),
    }


def _projected_room_cp_tail_policy(
    *,
    activity_count: int,
    available_seconds: float,
    eligible: bool,
    feedback_enabled: bool,
    requested_feedback_seconds: float,
) -> Dict[str, Any]:
    """Reserve the final exact-room slice without starving upstream search."""

    available = max(0.0, float(available_seconds))
    is_small = int(activity_count) <= 200
    target_seconds = 1.0
    compound_minimum_seconds = 0.65
    projected_minimum_seconds = 0.50
    feedback_requested = (
        bool(feedback_enabled) and float(requested_feedback_seconds) > 0.0
    )
    feedback_minimum_seconds = (
        min(0.25, max(0.0, float(requested_feedback_seconds)))
        if feedback_requested
        else 0.0
    )
    feedback_reserve_fraction = 0.40
    shared_search_minimum_seconds = (
        max(
            float(projected_minimum_seconds) / (1.0 - float(feedback_reserve_fraction)),
            float(feedback_minimum_seconds) / float(feedback_reserve_fraction),
        )
        if feedback_requested
        else float(projected_minimum_seconds)
    )
    upstream_minimum_seconds = float(compound_minimum_seconds) + float(
        shared_search_minimum_seconds
    )
    admission_required_seconds = float(target_seconds) + float(upstream_minimum_seconds)
    enabled = bool(
        eligible and is_small and available >= float(admission_required_seconds)
    )
    reserved_seconds = float(target_seconds if enabled else 0.0)
    return {
        "enabled": bool(enabled),
        "eligible": bool(eligible),
        "reason": (
            "eligible_exact_room_tail_reserved"
            if enabled
            else (
                "ineligible"
                if not bool(eligible)
                else (
                    "activity_limit_exceeded"
                    if not is_small
                    else "insufficient_shared_deadline"
                )
            )
        ),
        "size_class": "small" if is_small else "large",
        "available_seconds": float(available),
        "target_seconds": float(target_seconds),
        "reserved_seconds": float(reserved_seconds),
        "compound_minimum_seconds": float(compound_minimum_seconds),
        "projected_minimum_seconds": float(projected_minimum_seconds),
        "feedback_minimum_seconds": float(feedback_minimum_seconds),
        "feedback_reserve_fraction": float(feedback_reserve_fraction),
        "shared_search_minimum_seconds": float(shared_search_minimum_seconds),
        "upstream_minimum_seconds": float(upstream_minimum_seconds),
        "admission_required_seconds": float(admission_required_seconds),
        "upstream_reserved_seconds": max(
            0.0,
            float(available) - float(reserved_seconds),
        ),
    }


def _projected_quality_tail_policy(
    *,
    activity_count: int,
    available_seconds: float,
    eligible: bool,
    feedback_enabled: bool,
    requested_feedback_seconds: float,
) -> Dict[str, Any]:
    """Reserve the coordinated small-ITC quality tail when upstream survives."""

    available = max(0.0, float(available_seconds))
    is_small = int(activity_count) <= 200
    target_seconds = 2.30
    projected_minimum_seconds = 0.50
    feedback_requested = (
        bool(feedback_enabled) and float(requested_feedback_seconds) > 0.0
    )
    feedback_minimum_seconds = (
        min(0.25, max(0.0, float(requested_feedback_seconds)))
        if feedback_requested
        else 0.0
    )
    feedback_reserve_fraction = 0.40
    shared_search_minimum_seconds = (
        max(
            float(projected_minimum_seconds) / (1.0 - float(feedback_reserve_fraction)),
            float(feedback_minimum_seconds) / float(feedback_reserve_fraction),
        )
        if feedback_requested
        else float(projected_minimum_seconds)
    )
    admission_required_seconds = float(target_seconds) + float(
        shared_search_minimum_seconds
    )
    enabled = bool(
        eligible and is_small and available >= float(admission_required_seconds)
    )
    reserved_seconds = float(target_seconds if enabled else 0.0)
    return {
        "enabled": bool(enabled),
        "eligible": bool(eligible),
        "reason": (
            "eligible_coordinated_quality_tail_reserved"
            if enabled
            else (
                "ineligible"
                if not bool(eligible)
                else (
                    "activity_limit_exceeded"
                    if not is_small
                    else "insufficient_shared_deadline"
                )
            )
        ),
        "size_class": "small" if is_small else "large",
        "available_seconds": float(available),
        "target_seconds": float(target_seconds),
        "reserved_seconds": float(reserved_seconds),
        "projected_minimum_seconds": float(projected_minimum_seconds),
        "feedback_minimum_seconds": float(feedback_minimum_seconds),
        "feedback_reserve_fraction": float(feedback_reserve_fraction),
        "shared_search_minimum_seconds": float(shared_search_minimum_seconds),
        "admission_required_seconds": float(admission_required_seconds),
        "upstream_reserved_seconds": max(
            0.0,
            float(available) - float(reserved_seconds),
        ),
    }


def _admit_nonworsening_adaptive_candidate(
    inst: Any,
    incumbent: Dict[int, Dict[str, Any]],
    candidate: Dict[int, Dict[str, Any]] | None,
    *,
    require_strict_improvement: bool = False,
) -> tuple[Dict[int, Dict[str, Any]], Dict[str, Any]]:
    """Validate and independently score a phase hand-off, failing closed."""

    incumbent_copy = {
        int(activity_id): dict(row) for activity_id, row in incumbent.items()
    }
    if not isinstance(candidate, dict):
        return incumbent_copy, {
            "accepted": False,
            "reason": "missing_candidate",
        }
    candidate_copy = {
        int(activity_id): dict(row) for activity_id, row in candidate.items()
    }
    try:
        errors = validate_schedule_against_instance(
            inst,
            candidate_copy,
            strict_rooms=True,
            require_all_activities=True,
        )
        if errors:
            return incumbent_copy, {
                "accepted": False,
                "reason": "candidate_validation_failed",
                "validation_errors": [str(error) for error in errors[:20]],
            }
        incumbent_score, incumbent_objective = _adaptive_acceptance_score(
            inst,
            incumbent_copy,
        )
        candidate_score, candidate_objective = _adaptive_acceptance_score(
            inst,
            candidate_copy,
        )
    except Exception as exc:
        return incumbent_copy, {
            "accepted": False,
            "reason": "candidate_evaluation_error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    same_objective = str(candidate_objective) == str(incumbent_objective)
    accepted = bool(
        same_objective
        and (
            int(candidate_score) < int(incumbent_score)
            if bool(require_strict_improvement)
            else int(candidate_score) <= int(incumbent_score)
        )
    )
    return (
        candidate_copy if accepted else incumbent_copy,
        {
            "accepted": bool(accepted),
            "reason": (
                (
                    "strictly_improving_candidate"
                    if bool(require_strict_improvement)
                    else "nonworsening_candidate"
                )
                if accepted
                else (
                    "objective_mismatch"
                    if not same_objective
                    else (
                        "candidate_not_strictly_better"
                        if bool(require_strict_improvement)
                        else "candidate_worsened_objective"
                    )
                )
            ),
            "objective_id": str(incumbent_objective),
            "incumbent_score": int(incumbent_score),
            "candidate_score": int(candidate_score),
            "improvement": max(0, int(incumbent_score) - int(candidate_score)),
        },
    )


def _admit_strict_itc2007_fixed_time_candidate(
    inst: Any,
    incumbent: Dict[int, Dict[str, Any]],
    candidate: Dict[int, Dict[str, Any]] | None,
) -> tuple[Dict[int, Dict[str, Any]], Dict[str, Any]]:
    """Independently validate, fixed-start check, and officially rescore."""

    incumbent_copy = {
        int(activity_id): dict(row) for activity_id, row in incumbent.items()
    }
    base: Dict[str, Any] = {
        "accepted": False,
        "reason": "missing_candidate",
        "objective_id": "itc2007_official",
        "fixed_starts_preserved": None,
        "validation": {
            "attempted": False,
            "valid": None,
            "error_count": 0,
            "errors": [],
        },
        "incumbent_score": None,
        "candidate_score": None,
        "returned_score": None,
        "improvement": 0,
        "incumbent_components": None,
        "candidate_components": None,
        "returned_components": None,
    }
    if not isinstance(candidate, dict):
        return incumbent_copy, base
    candidate_copy = {
        int(activity_id): dict(row) for activity_id, row in candidate.items()
    }
    try:
        incumbent_fingerprint = _fixed_time_schedule_fingerprint(incumbent_copy)
        candidate_fingerprint = _fixed_time_schedule_fingerprint(candidate_copy)
    except Exception as exc:
        base.update(
            {
                "reason": "fixed_start_evaluation_error",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return incumbent_copy, base
    fixed_starts_preserved = bool(incumbent_fingerprint == candidate_fingerprint)
    base.update(
        {
            "fixed_starts_preserved": bool(fixed_starts_preserved),
            "incumbent_fixed_time_fingerprint": str(incumbent_fingerprint),
            "candidate_fixed_time_fingerprint": str(candidate_fingerprint),
        }
    )
    if not fixed_starts_preserved:
        base["reason"] = "fixed_starts_changed"
        return incumbent_copy, base

    try:
        errors = validate_schedule_against_instance(
            inst,
            candidate_copy,
            strict_rooms=True,
            require_all_activities=True,
        )
    except Exception as exc:
        base.update(
            {
                "reason": "candidate_validation_error",
                "validation": {
                    "attempted": True,
                    "valid": False,
                    "error_count": 1,
                    "errors": [f"{type(exc).__name__}: {exc}"],
                },
            }
        )
        return incumbent_copy, base
    validation_errors = [str(error) for error in errors[:20]]
    base["validation"] = {
        "attempted": True,
        "valid": not errors,
        "error_count": len(errors),
        "errors": validation_errors,
    }
    if errors:
        base["reason"] = "candidate_validation_failed"
        return incumbent_copy, base

    try:
        from benchmarks.itc2007 import score_itc2007_instance_schedule

        incumbent_official = score_itc2007_instance_schedule(
            inst,
            incumbent_copy,
        )
        candidate_official = score_itc2007_instance_schedule(
            inst,
            candidate_copy,
        )
    except Exception as exc:
        base.update(
            {
                "reason": "official_rescore_error",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return incumbent_copy, base

    incumbent_components = incumbent_official.to_dict()
    candidate_components = candidate_official.to_dict()
    improvement = int(incumbent_official.total - candidate_official.total)
    accepted = bool(improvement > 0)
    base.update(
        {
            "accepted": bool(accepted),
            "reason": (
                "strictly_improving_candidate"
                if accepted
                else "candidate_not_strictly_better"
            ),
            "incumbent_score": int(incumbent_official.total),
            "candidate_score": int(candidate_official.total),
            "returned_score": int(
                candidate_official.total if accepted else incumbent_official.total
            ),
            "improvement": max(0, int(improvement)),
            "incumbent_components": dict(incumbent_components),
            "candidate_components": dict(candidate_components),
            "returned_components": dict(
                candidate_components if accepted else incumbent_components
            ),
        }
    )
    return (candidate_copy if accepted else incumbent_copy), base


def _run_itc2007_rooted_adjacency_tail(
    inst: Any,
    incumbent: Dict[int, Dict[str, Any]],
    *,
    deadline: float,
    seed: int,
    continuation_feedback_rounds: int,
    stability_collision_weight: int = 1,
    stability_proxy_mode: str = "collision_events",
) -> tuple[Dict[int, Dict[str, Any]], Dict[str, Any], str | None]:
    """Run rooted descents with caller-authorized feedback continuations.

    Every stage recomputes its own incumbent room majorities.  Each complete
    candidate is independently strict-validated and rescored before hand-off;
    helper or whole-phase deadline exhaustion fails closed to the phase input.
    """

    phase_started = time.perf_counter()
    phase_incumbent = {
        int(activity_id): copy.deepcopy(dict(row))
        for activity_id, row in incumbent.items()
    }
    working = {
        int(activity_id): copy.deepcopy(dict(row))
        for activity_id, row in phase_incumbent.items()
    }
    returned_stage: str | None = None
    stages: list[Dict[str, Any]] = []
    phase_deadline_exhausted = False
    continuation_rounds = min(
        2,
        max(1, int(continuation_feedback_rounds)),
    )

    def run_stage(
        *,
        stage_name: str,
        stage_source: str,
        stage_deadline: float,
        search: Callable[[], Any],
    ) -> None:
        nonlocal working, returned_stage, phase_deadline_exhausted
        stage_started = time.perf_counter()
        stage_incumbent = {
            int(activity_id): copy.deepcopy(dict(row))
            for activity_id, row in working.items()
        }
        row: Dict[str, Any] = {
            "stage": str(stage_name),
            "input_source": str(returned_stage or "phase_incumbent"),
            "candidate_source": str(stage_source),
            "started_at_seconds": float(stage_started),
            "deadline_seconds": float(stage_deadline),
            "service_acceptance": {
                "accepted": False,
                "reason": "not_attempted",
            },
        }
        stages.append(row)
        if stage_started >= float(stage_deadline):
            row.update(
                {
                    "status": "skipped_deadline_exhausted",
                    "finished_at_seconds": float(stage_started),
                    "elapsed_seconds": 0.0,
                    "deadline_overrun_seconds": max(
                        0.0, float(stage_started) - float(stage_deadline)
                    ),
                    "service_acceptance": {
                        "accepted": False,
                        "reason": "stage_window_unavailable",
                    },
                }
            )
            phase_deadline_exhausted = True
            return
        try:
            result = search()
            search_finished = time.perf_counter()
            result_meta = (
                dict(result.to_dict())
                if hasattr(result, "to_dict")
                else {"status": "invalid_result"}
            )
            row.update(result_meta)
            observed_overrun = max(0.0, float(search_finished) - float(stage_deadline))
            helper_overrun = max(
                0.0,
                float(getattr(result, "deadline_overrun_seconds", 0.0)),
            )
            helper_exhausted = (
                bool(getattr(result, "deadline_exhausted", False))
                or str(result_meta.get("status", "")) == "deadline_exhausted"
            )
            if observed_overrun > 0.0 or helper_overrun > 0.0:
                acceptance = {
                    "accepted": False,
                    "reason": "stage_search_deadline_overrun",
                    "deadline_overrun_seconds": max(
                        float(observed_overrun), float(helper_overrun)
                    ),
                }
                phase_deadline_exhausted = True
            elif helper_exhausted:
                acceptance = {
                    "accepted": False,
                    "reason": "stage_helper_deadline_exhausted",
                }
                phase_deadline_exhausted = True
            else:
                candidate = getattr(result, "schedule", None)
                candidate_schedule, acceptance = _admit_nonworsening_adaptive_candidate(
                    inst,
                    stage_incumbent,
                    candidate,
                    require_strict_improvement=True,
                )
                validation_finished = time.perf_counter()
                validation_overrun = max(
                    0.0,
                    float(validation_finished) - float(stage_deadline),
                )
                if validation_overrun > 0.0:
                    acceptance = {
                        **dict(acceptance),
                        "accepted": False,
                        "reason": "stage_service_validation_overrun",
                        "deadline_overrun_seconds": float(validation_overrun),
                    }
                    phase_deadline_exhausted = True
                elif bool(acceptance.get("accepted")):
                    working = {
                        int(activity_id): copy.deepcopy(dict(value))
                        for activity_id, value in candidate_schedule.items()
                    }
                    returned_stage = str(stage_source)
            row["service_acceptance"] = dict(acceptance)
            row["status"] = (
                "improved"
                if bool(acceptance.get("accepted"))
                else (
                    "deadline_rejected"
                    if phase_deadline_exhausted
                    else "no_improvement"
                )
            )
        except Exception as exc:
            search_finished = time.perf_counter()
            row.update(
                {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "service_acceptance": {
                        "accepted": False,
                        "reason": "stage_search_error",
                    },
                }
            )
        stage_finished = time.perf_counter()
        row.update(
            {
                "finished_at_seconds": float(stage_finished),
                "elapsed_seconds": float(stage_finished - stage_started),
                "deadline_overrun_seconds": max(
                    0.0, float(stage_finished) - float(stage_deadline)
                ),
                "returned_source": str(returned_stage or row["input_source"]),
            }
        )

    available = max(0.0, float(deadline) - float(phase_started))
    if available <= 0.0:
        phase_deadline_exhausted = True
    else:
        downstream_minimum = 0.90 if continuation_rounds >= 2 else 0.60
        first_window = min(
            0.50,
            max(0.0, float(available) - float(downstream_minimum)),
        )
        first_deadline = min(
            float(deadline) - float(downstream_minimum),
            float(phase_started) + float(first_window),
        )
        run_stage(
            stage_name="rooted_before_feedback",
            stage_source="itc2007_rooted_adjacency",
            stage_deadline=float(first_deadline),
            search=lambda: optimize_itc2007_rooted_adjacency(
                inst,
                working,
                deadline=float(first_deadline),
                seed=int(seed) + 1_850_001,
                completion_reserve_seconds=(DEFAULT_COMPLETION_RESERVE_SECONDS),
            ),
        )

    if not phase_deadline_exhausted:
        continuation_started = time.perf_counter()
        continuation_stage_deadline = min(
            float(deadline) - (0.42 if continuation_rounds >= 2 else 0.20),
            float(continuation_started) + 0.65,
        )
        continuation_helper_deadline = float(continuation_stage_deadline) - 0.03
        continuation_seconds = max(
            0.05,
            float(continuation_helper_deadline) - float(continuation_started) - 0.02,
        )
        run_stage(
            stage_name="feedback_continuation_round_2",
            stage_source="itc2007_rooted_feedback_continuation_round_2",
            stage_deadline=float(continuation_stage_deadline),
            search=lambda: optimize_itc2007_feedback(
                inst,
                working,
                deadline=float(continuation_helper_deadline),
                # The first large feedback call uses base seed +900001 and
                # derives its round seed by +65537.  Reuse that derived seed
                # as the continuation base so this consumes deterministic
                # requested round two rather than replaying round one.
                seed=int(seed) + 900_001 + 65_537,
                max_feedback_rounds=1,
                feedback_round_seconds=float(continuation_seconds),
                candidate_batch_size=32,
                history_length=128,
                stagnation_limit=180,
                room_lift_reserve_seconds=0.08,
                coordinate_room_sweeps=8,
                stability_collision_weight=int(stability_collision_weight),
                stability_proxy_mode=str(stability_proxy_mode),
                run_consolidation=True,
            ),
        )

    if not phase_deadline_exhausted:
        final_started = time.perf_counter()
        final_stage_deadline = float(deadline) - (
            0.23 if continuation_rounds >= 2 else 0.03
        )
        final_helper_deadline = float(final_stage_deadline) - 0.02
        run_stage(
            stage_name="rooted_after_feedback",
            stage_source="itc2007_rooted_adjacency",
            stage_deadline=float(final_stage_deadline),
            search=lambda: optimize_itc2007_rooted_adjacency(
                inst,
                working,
                deadline=float(final_helper_deadline),
                seed=int(seed) + 1_850_002,
                completion_reserve_seconds=min(
                    DEFAULT_COMPLETION_RESERVE_SECONDS,
                    max(
                        0.0,
                        (float(final_helper_deadline) - float(final_started)) * 0.40,
                    ),
                ),
            ),
        )

    if not phase_deadline_exhausted and continuation_rounds >= 2:
        final_feedback_started = time.perf_counter()
        # Leave an explicit service-level completion slice after the helper;
        # the helper also preserves its own room-lift/copying reserve.
        final_feedback_stage_deadline = float(deadline) - 0.03
        final_feedback_helper_deadline = float(final_feedback_stage_deadline) - 0.03
        final_feedback_seconds = max(
            0.05,
            min(
                0.32,
                float(final_feedback_helper_deadline)
                - float(final_feedback_started)
                - 0.03,
            ),
        )
        run_stage(
            stage_name="feedback_continuation_round_3",
            stage_source="itc2007_rooted_feedback_continuation_round_3",
            stage_deadline=float(final_feedback_stage_deadline),
            search=lambda: optimize_itc2007_feedback(
                inst,
                working,
                deadline=float(final_feedback_helper_deadline),
                # Advance the continuation base by one round stride.  The
                # optimizer derives the requested third round by adding its
                # own deterministic stride once more.
                seed=int(seed) + 900_001 + (2 * 65_537),
                max_feedback_rounds=1,
                feedback_round_seconds=float(final_feedback_seconds),
                candidate_batch_size=32,
                history_length=128,
                stagnation_limit=180,
                room_lift_reserve_seconds=0.12,
                coordinate_room_sweeps=8,
                stability_collision_weight=int(stability_collision_weight),
                stability_proxy_mode=str(stability_proxy_mode),
                run_consolidation=True,
            ),
        )

    phase_finished = time.perf_counter()
    phase_overrun = max(0.0, float(phase_finished) - float(deadline))
    if phase_deadline_exhausted or phase_overrun > 0.0:
        returned = {
            int(activity_id): copy.deepcopy(dict(row))
            for activity_id, row in phase_incumbent.items()
        }
        phase_acceptance = {
            "accepted": False,
            "reason": (
                "phase_deadline_overrun"
                if phase_overrun > 0.0
                else "phase_helper_deadline_exhausted"
            ),
            "deadline_overrun_seconds": float(phase_overrun),
        }
        returned_stage = None
    else:
        returned, phase_acceptance = _admit_nonworsening_adaptive_candidate(
            inst,
            phase_incumbent,
            working,
            require_strict_improvement=True,
        )
        acceptance_finished = time.perf_counter()
        completion_overrun = max(0.0, float(acceptance_finished) - float(deadline))
        if completion_overrun > 0.0:
            returned = phase_incumbent
            returned_stage = None
            phase_acceptance = {
                **dict(phase_acceptance),
                "accepted": False,
                "reason": "phase_service_validation_overrun",
                "deadline_overrun_seconds": float(completion_overrun),
            }
            phase_finished = acceptance_finished
            phase_overrun = completion_overrun
        elif not bool(phase_acceptance.get("accepted")):
            returned_stage = None
        returned = {
            int(activity_id): copy.deepcopy(dict(row))
            for activity_id, row in returned.items()
        }

    meta = {
        "enabled": True,
        "status": (
            "improved"
            if bool(phase_acceptance.get("accepted"))
            else (
                "deadline_rejected"
                if phase_deadline_exhausted or phase_overrun > 0.0
                else "no_improvement"
            )
        ),
        "stages": stages,
        "service_acceptance": dict(phase_acceptance),
        "returned_source": str(returned_stage or "phase_incumbent"),
        "deadline_exhausted": bool(
            phase_deadline_exhausted or phase_finished >= float(deadline)
        ),
        "deadline_overrun_seconds": float(phase_overrun),
        "timing": {
            "started_at_seconds": float(phase_started),
            "deadline_seconds": float(deadline),
            "finished_at_seconds": float(phase_finished),
            "elapsed_seconds": float(phase_finished - phase_started),
            "deadline_remaining_seconds": max(
                0.0, float(deadline) - float(phase_finished)
            ),
            "deadline_overrun_seconds": float(phase_overrun),
        },
    }
    return returned, meta, returned_stage


def _run_adaptive_lns(
    inst,
    schedule: Dict[int, Dict[str, Any]],
    options: SolveOptions,
    *,
    decomposition_report: Dict[str, Any] | None = None,
    progress_hook: Callable[[str, Dict[str, Any]], None] | None = None,
    fixed_time_room_dive_enabled: bool = False,
    fixed_time_room_dive_budget_seconds: float = 0.0,
    fixed_time_room_dive_completion_reserve_seconds: float = 0.0,
    fixed_time_room_strategy: str = "oracle_then_cp",
    final_deadline: float | None = None,
    initial_source: str | None = None,
) -> tuple[Dict[int, Dict[str, Any]], Dict[str, Any]]:
    """Run exact, warm-started semantic neighborhoods around an incumbent."""
    adaptive_started = time.perf_counter()
    budget_seconds = max(0.0, float(options.adaptive_lns_seconds))
    deadline = float(adaptive_started) + float(budget_seconds)
    activity_count = len(inst.activities)
    sizes, neighborhood_size_policy = _adaptive_lns_neighborhood_policy(
        inst,
        options,
        activity_count=activity_count,
    )
    projected_eligible, _projected_reasons = projected_time_search_eligibility(
        inst, schedule
    )
    if (
        bool(options.projected_time_search)
        and bool(projected_eligible)
        and budget_seconds > 0
    ):
        requested_adaptive_deadline = float(deadline)
        effective_deadline = max(
            float(adaptive_started),
            min(
                float(requested_adaptive_deadline),
                float(final_deadline) - 0.05
                if final_deadline is not None
                else float(requested_adaptive_deadline),
            ),
        )
        available_window_seconds = max(
            0.0,
            float(effective_deadline) - float(adaptive_started),
        )
        # Keep the final independent validation/rescore and telemetry assembly
        # inside the adaptive budget even when a cooperative optimizer returns
        # exactly at its assigned deadline.
        service_completion_reserve_seconds = min(
            0.05,
            float(available_window_seconds) * 0.05,
        )
        phase_execution_deadline = max(
            float(adaptive_started),
            float(effective_deadline) - float(service_completion_reserve_seconds),
        )
        phase_execution_window_seconds = max(
            0.0,
            float(phase_execution_deadline) - float(adaptive_started),
        )
        try:
            room_cp_structurally_eligible, room_cp_eligibility_reasons = (
                itc2007_fixed_time_room_cp_eligibility(
                    inst,
                    schedule,
                )
            )
        except Exception as exc:
            room_cp_structurally_eligible = False
            room_cp_eligibility_reasons = (
                f"eligibility_error:{type(exc).__name__}:{exc}",
            )
        try:
            rooted_eligibility = itc2007_rooted_adjacency_eligibility(
                inst,
                schedule,
            )
            rooted_structurally_eligible = bool(rooted_eligibility.eligible)
            rooted_eligibility_reasons = tuple(rooted_eligibility.reasons)
        except Exception as exc:
            rooted_structurally_eligible = False
            rooted_eligibility_reasons = (
                f"eligibility_error:{type(exc).__name__}:{exc}",
            )
        try:
            quality_tail_eligibility = itc2007_quality_tail_eligibility(
                inst,
                schedule,
            )
            quality_tail_structurally_eligible = bool(quality_tail_eligibility.eligible)
            quality_tail_eligibility_reasons = tuple(
                str(value) for value in quality_tail_eligibility.reasons
            )
        except Exception as exc:
            quality_tail_structurally_eligible = False
            quality_tail_eligibility_reasons = (
                f"eligibility_error:{type(exc).__name__}:{exc}",
            )
        quality_tail_policy = _projected_quality_tail_policy(
            activity_count=int(activity_count),
            available_seconds=float(phase_execution_window_seconds),
            eligible=bool(projected_eligible and quality_tail_structurally_eligible),
            feedback_enabled=bool(options.projected_time_feedback),
            requested_feedback_seconds=float(options.projected_time_feedback_seconds),
        )
        quality_tail_reserve_seconds = float(quality_tail_policy["reserved_seconds"])
        quality_tail_reservation_start_deadline = max(
            float(adaptive_started),
            float(phase_execution_deadline) - float(quality_tail_reserve_seconds),
        )
        room_cp_tail_policy = _projected_room_cp_tail_policy(
            activity_count=int(activity_count),
            available_seconds=float(phase_execution_window_seconds),
            eligible=bool(projected_eligible and room_cp_structurally_eligible),
            feedback_enabled=bool(options.projected_time_feedback),
            requested_feedback_seconds=float(options.projected_time_feedback_seconds),
        )
        if bool(quality_tail_policy["enabled"]):
            room_cp_tail_policy = {
                **dict(room_cp_tail_policy),
                "enabled": False,
                "reason": "superseded_by_coordinated_quality_tail",
                "reserved_seconds": 0.0,
                "superseded_by": "itc2007_quality_tail",
            }
            room_cp_reserve_seconds = 0.0
            room_cp_reservation_start_deadline = float(phase_execution_deadline)
            rooted_adjacency_policy = _projected_rooted_adjacency_tail_policy(
                activity_count=int(activity_count),
                available_seconds=float(phase_execution_window_seconds),
                exchangeable_eligible=bool(
                    projected_eligible and rooted_structurally_eligible
                ),
                eligibility_reasons=rooted_eligibility_reasons,
                feedback_enabled=bool(options.projected_time_feedback),
                requested_feedback_seconds=float(
                    options.projected_time_feedback_seconds
                ),
                requested_feedback_rounds=int(options.projected_time_feedback_rounds),
            )
            rooted_adjacency_policy = {
                **dict(rooted_adjacency_policy),
                "enabled": False,
                "reason": "superseded_by_coordinated_quality_tail",
                "reserved_seconds": 0.0,
                "superseded_by": "itc2007_quality_tail",
            }
            rooted_adjacency_reserve_seconds = 0.0
            rooted_adjacency_reservation_start_deadline = float(
                quality_tail_reservation_start_deadline
            )
            compound_policy = _projected_compound_phase_policy(
                activity_count=int(activity_count),
                available_seconds=float(phase_execution_window_seconds),
                eligible=False,
            )
            compound_policy = {
                **dict(compound_policy),
                "reason": "superseded_by_coordinated_quality_tail",
                "superseded_by": "itc2007_quality_tail",
            }
            compound_reserve_seconds = 0.0
            upstream_execution_deadline = float(quality_tail_reservation_start_deadline)
        else:
            room_cp_reserve_seconds = float(room_cp_tail_policy["reserved_seconds"])
            room_cp_reservation_start_deadline = max(
                float(adaptive_started),
                float(phase_execution_deadline) - float(room_cp_reserve_seconds),
            )
            pre_room_cp_window_seconds = max(
                0.0,
                float(room_cp_reservation_start_deadline) - float(adaptive_started),
            )
            rooted_adjacency_policy = _projected_rooted_adjacency_tail_policy(
                activity_count=int(activity_count),
                available_seconds=float(pre_room_cp_window_seconds),
                exchangeable_eligible=bool(
                    projected_eligible and rooted_structurally_eligible
                ),
                eligibility_reasons=rooted_eligibility_reasons,
                feedback_enabled=bool(options.projected_time_feedback),
                requested_feedback_seconds=float(
                    options.projected_time_feedback_seconds
                ),
                requested_feedback_rounds=int(options.projected_time_feedback_rounds),
            )
            rooted_adjacency_reserve_seconds = float(
                rooted_adjacency_policy["reserved_seconds"]
            )
            rooted_adjacency_reservation_start_deadline = float(
                room_cp_reservation_start_deadline
            )
            if bool(rooted_adjacency_policy["enabled"]):
                compound_policy = _projected_compound_phase_policy(
                    activity_count=int(activity_count),
                    available_seconds=float(pre_room_cp_window_seconds),
                    eligible=False,
                )
                compound_policy = {
                    **dict(compound_policy),
                    "reason": "superseded_by_rooted_adjacency_tail",
                    "superseded_by": "itc2007_rooted_adjacency",
                }
                compound_reserve_seconds = 0.0
            else:
                compound_policy = _projected_compound_phase_policy(
                    activity_count=int(activity_count),
                    available_seconds=float(pre_room_cp_window_seconds),
                    eligible=bool(projected_eligible),
                )
                compound_reserve_seconds = float(compound_policy["reserved_seconds"])
            upstream_execution_deadline = max(
                float(adaptive_started),
                float(room_cp_reservation_start_deadline)
                - float(rooted_adjacency_reserve_seconds)
                - float(compound_reserve_seconds),
            )
        upstream_execution_window_seconds = max(
            0.0,
            float(upstream_execution_deadline) - float(adaptive_started),
        )
        feedback_policy = _projected_feedback_phase_policy(
            activity_count=int(activity_count),
            available_seconds=float(upstream_execution_window_seconds),
            feedback_enabled=bool(options.projected_time_feedback),
            requested_feedback_seconds=float(options.projected_time_feedback_seconds),
            requested_feedback_rounds=int(options.projected_time_feedback_rounds),
        )
        feedback_reserve_seconds = float(feedback_policy["reserved_seconds"])
        projected_deadline = max(
            float(adaptive_started),
            float(upstream_execution_deadline) - float(feedback_reserve_seconds),
        )
        projected_started = time.perf_counter()
        projected_result: Any | None = None
        projected_error: str | None = None
        try:
            projected_result = optimize_projected_times(
                inst,
                schedule,
                deadline=float(projected_deadline),
                seed=int(options.random_seed or 0),
                # Smaller batches let dense projected search update its state more
                # frequently under short benchmark deadlines instead of evaluating
                # many dominated variants of the same move family before acceptance.
                candidate_batch_size=(48 if activity_count <= 200 else 32),
                adapt_dense_default_batch=True,
                room_reserve_seconds=max(
                    0.10,
                    float(options.projected_time_room_reserve_seconds),
                ),
                enable_constructive_start=(
                    str(initial_source) != "constructive_initializer"
                ),
                small_room_cp_budget_seconds=(
                    max(0.0, float(options.projected_time_small_room_cp_seconds))
                    if bool(options.projected_time_feedback) and activity_count <= 200
                    else None
                ),
            )
        except Exception as exc:
            projected_error = f"{type(exc).__name__}: {exc}"
        projected_finished = time.perf_counter()
        projected_overrun_seconds = max(
            0.0,
            float(projected_finished) - float(projected_deadline),
        )
        selected_schedule = {
            int(activity_id): dict(row) for activity_id, row in schedule.items()
        }
        returned_source = str(initial_source or "incumbent")
        if projected_result is None:
            projected_result_meta: Dict[str, Any] = {
                "status": "error",
                "error": projected_error,
            }
            projected_acceptance = {
                "accepted": False,
                "reason": "projected_search_error",
                "error": projected_error,
            }
        else:
            projected_result_meta = dict(projected_result.to_dict())
            if projected_overrun_seconds > 0.0:
                projected_acceptance = {
                    "accepted": False,
                    "reason": "projected_phase_deadline_overrun",
                    "deadline_overrun_seconds": float(projected_overrun_seconds),
                }
            else:
                selected_schedule, projected_acceptance = (
                    _admit_nonworsening_adaptive_candidate(
                        inst,
                        selected_schedule,
                        projected_result.schedule,
                    )
                )
        projected_result_meta["service_acceptance"] = dict(projected_acceptance)
        if bool(projected_acceptance.get("accepted")):
            returned_source = "projected_time_search"

        feedback_phase_started = time.perf_counter()
        configured_window = float(feedback_policy["requested_seconds"])
        feedback_meta: Dict[str, Any] = {
            "enabled": bool(options.projected_time_feedback),
            "status": (
                "not_started"
                if bool(feedback_policy["enabled"])
                else (
                    "disabled"
                    if not bool(options.projected_time_feedback)
                    else "skipped_zero_budget"
                )
            ),
            "configured_window_seconds": float(configured_window),
            "reserved_window_seconds": float(feedback_reserve_seconds),
            "configured_rounds": int(feedback_policy["configured_rounds"]),
            "effective_rounds": int(feedback_policy["effective_rounds"]),
            "size_class": str(feedback_policy["size_class"]),
            "stability_collision_weight": int(
                options.projected_time_stability_collision_weight
            ),
            "stability_proxy_mode": str(options.projected_time_stability_proxy_mode),
        }
        feedback_requested_deadline: float | None = None
        feedback_deadline: float | None = None
        feedback_search_started: float | None = None
        feedback_search_finished: float | None = None
        if bool(feedback_policy["enabled"]):
            feedback_requested_deadline = float(feedback_phase_started) + float(
                configured_window
            )
            feedback_deadline = min(
                float(upstream_execution_deadline),
                float(feedback_requested_deadline),
            )
            feedback_rounds = int(feedback_policy["effective_rounds"])
            remaining_feedback = max(
                0.0,
                float(feedback_deadline) - time.perf_counter(),
            )
            per_round_seconds = (
                min(
                    2.0,
                    max(
                        0.05,
                        (remaining_feedback - 0.03) / max(1, feedback_rounds),
                    ),
                )
                if feedback_rounds > 0
                else 0.0
            )
            if remaining_feedback <= 0.0:
                feedback_meta["status"] = "skipped_deadline_exhausted"
                feedback_meta["feedback_round_seconds"] = 0.0
            else:
                feedback_search_started = time.perf_counter()
                try:
                    feedback = optimize_itc2007_feedback(
                        inst,
                        selected_schedule,
                        deadline=float(feedback_deadline),
                        seed=int(options.random_seed or 0) + 900_001,
                        max_feedback_rounds=int(feedback_rounds),
                        feedback_round_seconds=float(per_round_seconds),
                        candidate_batch_size=(
                            # Feedback prices realized room collisions and
                            # keeps its independently validated 32-candidate
                            # dense policy; the 24-candidate adaptation above
                            # applies only to projected time search.
                            48 if activity_count <= 200 else 32
                        ),
                        room_lift_reserve_seconds=min(
                            0.15,
                            max(0.02, remaining_feedback * 0.08),
                        ),
                        stability_collision_weight=int(
                            options.projected_time_stability_collision_weight
                        ),
                        stability_proxy_mode=str(
                            options.projected_time_stability_proxy_mode
                        ),
                        run_consolidation=True,
                    )
                    feedback_search_finished = time.perf_counter()
                    feedback_meta = feedback.to_dict()
                    feedback_meta["enabled"] = True
                    feedback_overrun_seconds = max(
                        0.0,
                        float(feedback_search_finished) - float(feedback_deadline),
                    )
                    if feedback_overrun_seconds > 0.0:
                        feedback_acceptance = {
                            "accepted": False,
                            "reason": "feedback_phase_deadline_overrun",
                            "deadline_overrun_seconds": float(feedback_overrun_seconds),
                        }
                    else:
                        selected_schedule, feedback_acceptance = (
                            _admit_nonworsening_adaptive_candidate(
                                inst,
                                selected_schedule,
                                feedback.schedule,
                            )
                        )
                    feedback_meta["service_acceptance"] = dict(feedback_acceptance)
                    if bool(feedback_acceptance.get("accepted")):
                        returned_source = "itc2007_room_feedback"
                except Exception as exc:
                    feedback_search_finished = time.perf_counter()
                    feedback_meta = {
                        "enabled": True,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                        "service_acceptance": {
                            "accepted": False,
                            "reason": "feedback_search_error",
                        },
                    }
                feedback_meta["configured_window_seconds"] = float(configured_window)
                feedback_meta["reserved_window_seconds"] = float(
                    feedback_reserve_seconds
                )
                feedback_meta["effective_window_seconds"] = float(
                    max(
                        0.0,
                        float(feedback_deadline) - float(feedback_phase_started),
                    )
                )
                feedback_meta["feedback_round_seconds"] = float(per_round_seconds)
                feedback_meta["configured_rounds"] = int(
                    feedback_policy["configured_rounds"]
                )
                feedback_meta["effective_rounds"] = int(feedback_rounds)
                feedback_meta["size_class"] = str(feedback_policy["size_class"])
                feedback_meta["stability_collision_weight"] = int(
                    options.projected_time_stability_collision_weight
                )
                feedback_meta["stability_proxy_mode"] = str(
                    options.projected_time_stability_proxy_mode
                )
        feedback_phase_finished = time.perf_counter()

        rooted_adjacency_phase_started = time.perf_counter()
        rooted_adjacency_search_started: float | None = None
        rooted_adjacency_search_finished: float | None = None
        rooted_adjacency_deadline: float | None = None
        rooted_adjacency_meta: Dict[str, Any] = {
            "enabled": bool(rooted_adjacency_policy["enabled"]),
            "eligible": bool(rooted_adjacency_policy["eligible"]),
            "status": (
                "not_started" if bool(rooted_adjacency_policy["enabled"]) else "skipped"
            ),
            "reason": str(rooted_adjacency_policy["reason"]),
            "activity_count": int(activity_count),
            "activity_threshold": int(rooted_adjacency_policy["activity_threshold"]),
            "reservation_policy": dict(rooted_adjacency_policy),
            "reserved_window_seconds": float(rooted_adjacency_reserve_seconds),
            "reservation_start_deadline_seconds": float(
                rooted_adjacency_reservation_start_deadline
            ),
            "input_source": str(returned_source),
            "returned_source": str(returned_source),
            "service_acceptance": {
                "accepted": False,
                "reason": "not_attempted",
            },
        }
        if bool(rooted_adjacency_policy["enabled"]):
            rooted_adjacency_deadline = min(
                float(room_cp_reservation_start_deadline),
                float(rooted_adjacency_phase_started)
                + float(rooted_adjacency_reserve_seconds),
            )
            if time.perf_counter() >= float(rooted_adjacency_deadline):
                rooted_adjacency_meta.update(
                    {
                        "status": "skipped_deadline_exhausted",
                        "reason": "rooted_adjacency_window_unavailable",
                        "service_acceptance": {
                            "accepted": False,
                            "reason": "rooted_adjacency_not_attempted",
                        },
                    }
                )
            else:
                rooted_adjacency_search_started = time.perf_counter()
                rooted_adjacency_incumbent = {
                    int(activity_id): copy.deepcopy(dict(row))
                    for activity_id, row in selected_schedule.items()
                }
                try:
                    (
                        rooted_candidate,
                        rooted_result_meta,
                        rooted_returned_stage,
                    ) = _run_itc2007_rooted_adjacency_tail(
                        inst,
                        rooted_adjacency_incumbent,
                        deadline=float(rooted_adjacency_deadline),
                        seed=int(options.random_seed or 0),
                        continuation_feedback_rounds=int(
                            rooted_adjacency_policy["continuation_feedback_rounds"]
                        ),
                        stability_collision_weight=int(
                            options.projected_time_stability_collision_weight
                        ),
                        stability_proxy_mode=str(
                            options.projected_time_stability_proxy_mode
                        ),
                    )
                    rooted_adjacency_search_finished = time.perf_counter()
                    rooted_adjacency_meta.update(rooted_result_meta)
                    rooted_adjacency_meta.update(
                        {
                            "enabled": True,
                            "eligible": True,
                            "reason": "optimizer_completed",
                            "activity_count": int(activity_count),
                            "activity_threshold": int(
                                rooted_adjacency_policy["activity_threshold"]
                            ),
                            "reservation_policy": dict(rooted_adjacency_policy),
                            "reserved_window_seconds": float(
                                rooted_adjacency_reserve_seconds
                            ),
                            "reservation_start_deadline_seconds": float(
                                rooted_adjacency_reservation_start_deadline
                            ),
                            "input_source": str(returned_source),
                        }
                    )
                    observed_overrun = max(
                        0.0,
                        float(rooted_adjacency_search_finished)
                        - float(rooted_adjacency_deadline),
                    )
                    helper_overrun = max(
                        0.0,
                        float(rooted_result_meta.get("deadline_overrun_seconds", 0.0)),
                    )
                    helper_exhausted = bool(
                        rooted_result_meta.get("deadline_exhausted", False)
                    )
                    helper_acceptance = dict(
                        rooted_result_meta.get("service_acceptance") or {}
                    )
                    completion_overrun = 0.0
                    if observed_overrun > 0.0 or helper_overrun > 0.0:
                        rooted_acceptance = {
                            "accepted": False,
                            "reason": "rooted_adjacency_phase_deadline_overrun",
                            "deadline_overrun_seconds": max(
                                float(observed_overrun),
                                float(helper_overrun),
                            ),
                        }
                    elif helper_exhausted:
                        rooted_acceptance = {
                            "accepted": False,
                            "reason": "rooted_adjacency_helper_deadline_exhausted",
                        }
                    elif not bool(helper_acceptance.get("accepted")):
                        rooted_acceptance = {
                            "accepted": False,
                            "reason": "rooted_adjacency_no_strict_improvement",
                        }
                    else:
                        (
                            rooted_candidate,
                            rooted_acceptance,
                        ) = _admit_nonworsening_adaptive_candidate(
                            inst,
                            rooted_adjacency_incumbent,
                            rooted_candidate,
                            require_strict_improvement=True,
                        )
                        validation_finished = time.perf_counter()
                        completion_overrun = max(
                            0.0,
                            float(validation_finished)
                            - float(rooted_adjacency_deadline),
                        )
                        if completion_overrun > 0.0:
                            rooted_acceptance = {
                                **dict(rooted_acceptance),
                                "accepted": False,
                                "reason": "rooted_adjacency_service_validation_overrun",
                                "deadline_overrun_seconds": float(completion_overrun),
                            }
                        elif bool(rooted_acceptance.get("accepted")):
                            selected_schedule = {
                                int(activity_id): copy.deepcopy(dict(row))
                                for activity_id, row in rooted_candidate.items()
                            }
                            returned_source = str(
                                rooted_returned_stage or "itc2007_rooted_adjacency"
                            )
                    reported_overrun = max(
                        float(observed_overrun),
                        float(helper_overrun),
                        float(completion_overrun),
                    )
                    rooted_adjacency_meta["deadline_exhausted"] = bool(
                        helper_exhausted or reported_overrun > 0.0
                    )
                    rooted_adjacency_meta["deadline_overrun_seconds"] = float(
                        reported_overrun
                    )
                    rooted_adjacency_meta["service_acceptance"] = dict(
                        rooted_acceptance
                    )
                    rooted_adjacency_meta["status"] = (
                        "improved"
                        if bool(rooted_acceptance.get("accepted"))
                        else "rejected"
                    )
                    rooted_adjacency_meta["returned_source"] = str(returned_source)
                except Exception as exc:
                    rooted_adjacency_search_finished = time.perf_counter()
                    rooted_adjacency_meta.update(
                        {
                            "status": "error",
                            "reason": "rooted_adjacency_search_error",
                            "error": f"{type(exc).__name__}: {exc}",
                            "service_acceptance": {
                                "accepted": False,
                                "reason": "rooted_adjacency_search_error",
                            },
                        }
                    )
        rooted_adjacency_phase_finished = time.perf_counter()

        compound_phase_started = time.perf_counter()
        compound_search_started: float | None = None
        compound_search_finished: float | None = None
        compound_deadline: float | None = None
        compound_meta: Dict[str, Any] = {
            "enabled": bool(compound_policy["enabled"]),
            "status": (
                "not_started" if bool(compound_policy["enabled"]) else "skipped"
            ),
            "reason": str(compound_policy["reason"]),
            "reserved_window_seconds": float(compound_reserve_seconds),
            "size_class": str(compound_policy["size_class"]),
        }
        if bool(compound_policy["enabled"]):
            compound_deadline = min(
                float(room_cp_reservation_start_deadline),
                float(compound_phase_started) + float(compound_reserve_seconds),
            )
            remaining_compound = max(
                0.0,
                float(compound_deadline) - time.perf_counter(),
            )
            if remaining_compound <= 0.0:
                compound_meta["status"] = "skipped_deadline_exhausted"
            else:
                compound_search_started = time.perf_counter()
                try:
                    compound = optimize_itc2007_compound(
                        inst,
                        selected_schedule,
                        deadline=float(compound_deadline),
                        seed=int(options.random_seed or 0) + 1_800_001,
                    )
                    compound_search_finished = time.perf_counter()
                    compound_meta = compound.to_dict()
                    compound_meta["enabled"] = True
                    compound_overrun_seconds = max(
                        0.0,
                        float(compound_search_finished) - float(compound_deadline),
                    )
                    if compound_overrun_seconds > 0.0:
                        compound_acceptance = {
                            "accepted": False,
                            "reason": "compound_phase_deadline_overrun",
                            "deadline_overrun_seconds": float(compound_overrun_seconds),
                        }
                    else:
                        selected_schedule, compound_acceptance = (
                            _admit_nonworsening_adaptive_candidate(
                                inst,
                                selected_schedule,
                                compound.schedule,
                                require_strict_improvement=True,
                            )
                        )
                    compound_meta["service_acceptance"] = dict(compound_acceptance)
                    if bool(compound_acceptance.get("accepted")):
                        returned_source = "itc2007_compound_search"
                except Exception as exc:
                    compound_search_finished = time.perf_counter()
                    compound_meta = {
                        "enabled": True,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                        "service_acceptance": {
                            "accepted": False,
                            "reason": "compound_search_error",
                        },
                    }
                compound_meta["reserved_window_seconds"] = float(
                    compound_reserve_seconds
                )
                compound_meta["effective_window_seconds"] = float(
                    max(
                        0.0,
                        float(compound_deadline) - float(compound_phase_started),
                    )
                )
                compound_meta["size_class"] = str(compound_policy["size_class"])
        compound_phase_finished = time.perf_counter()

        quality_tail_phase_started = time.perf_counter()
        quality_tail_search_started: float | None = None
        quality_tail_search_finished: float | None = None
        quality_tail_phase_finished = float(quality_tail_phase_started)
        quality_tail_service_validation_reserve_seconds = 0.05
        quality_tail_deadline: float | None = None
        quality_tail_supported = bool(
            projected_eligible
            and quality_tail_structurally_eligible
            and int(activity_count) <= 200
        )
        quality_tail_eligible = bool(
            quality_tail_supported and quality_tail_policy["enabled"]
        )
        quality_tail_remaining_at_start = max(
            0.0,
            float(phase_execution_deadline) - float(quality_tail_phase_started),
        )
        quality_tail_input_source = str(returned_source)
        quality_tail_meta: Dict[str, Any] = {
            "enabled": bool(quality_tail_eligible),
            "eligible": bool(quality_tail_supported),
            "status": (
                "not_started"
                if quality_tail_eligible
                else (
                    "skipped_unreserved"
                    if quality_tail_supported
                    else "skipped_ineligible"
                )
            ),
            "reason": (
                "eligible_lossless_itc2007_small_instance"
                if quality_tail_eligible
                else str(quality_tail_policy["reason"])
            ),
            "activity_count": int(activity_count),
            "activity_limit": 200,
            "eligibility_reasons": list(quality_tail_eligibility_reasons),
            "reservation_policy": dict(quality_tail_policy),
            "reserved_window_seconds": float(quality_tail_reserve_seconds),
            "reservation_start_deadline_seconds": float(
                quality_tail_reservation_start_deadline
            ),
            "remaining_at_start_seconds": float(quality_tail_remaining_at_start),
            "service_validation_reserve_seconds": float(
                quality_tail_service_validation_reserve_seconds
            ),
            "input_source": str(quality_tail_input_source),
            "returned_source": str(quality_tail_input_source),
            "service_acceptance": {
                "accepted": False,
                "reason": "not_attempted",
            },
        }
        if quality_tail_eligible:
            quality_tail_deadline = max(
                float(quality_tail_phase_started),
                float(phase_execution_deadline)
                - float(quality_tail_service_validation_reserve_seconds),
            )
            if time.perf_counter() >= float(quality_tail_deadline):
                quality_tail_meta.update(
                    {
                        "status": "skipped_deadline_exhausted",
                        "reason": "quality_tail_search_window_unavailable",
                        "service_acceptance": {
                            "accepted": False,
                            "reason": "quality_tail_not_attempted",
                        },
                    }
                )
            else:
                quality_tail_search_started = time.perf_counter()
                quality_tail_incumbent = {
                    int(activity_id): dict(row)
                    for activity_id, row in selected_schedule.items()
                }
                try:
                    quality_tail_result = optimize_itc2007_quality_tail(
                        inst,
                        quality_tail_incumbent,
                        deadline=float(quality_tail_deadline),
                        seed=int(options.random_seed or 0),
                    )
                    quality_tail_search_finished = time.perf_counter()
                    quality_tail_meta.update(quality_tail_result.to_dict())
                    quality_tail_meta.update(
                        {
                            "enabled": True,
                            "eligible": True,
                            "optimizer_status": str(quality_tail_result.status),
                            "reason": "optimizer_completed",
                            "input_source": str(quality_tail_input_source),
                            "returned_source": str(quality_tail_input_source),
                            "activity_count": int(activity_count),
                            "activity_limit": 200,
                            "eligibility_reasons": list(
                                quality_tail_eligibility_reasons
                            ),
                            "reservation_policy": dict(quality_tail_policy),
                            "reserved_window_seconds": float(
                                quality_tail_reserve_seconds
                            ),
                            "reservation_start_deadline_seconds": float(
                                quality_tail_reservation_start_deadline
                            ),
                            "remaining_at_start_seconds": float(
                                quality_tail_remaining_at_start
                            ),
                            "service_validation_reserve_seconds": float(
                                quality_tail_service_validation_reserve_seconds
                            ),
                        }
                    )
                    observed_overrun = max(
                        0.0,
                        float(quality_tail_search_finished)
                        - float(quality_tail_deadline),
                    )
                    helper_overrun = max(
                        0.0,
                        float(
                            getattr(
                                quality_tail_result,
                                "deadline_overrun_seconds",
                                0.0,
                            )
                        ),
                    )
                    helper_improved = (
                        bool(getattr(quality_tail_result, "improved", False))
                        and str(getattr(quality_tail_result, "status", "unknown"))
                        == "improved"
                    )
                    helper_deadline_exhausted = bool(
                        getattr(
                            quality_tail_result,
                            "deadline_exhausted",
                            False,
                        )
                    )
                    if observed_overrun > 0.0 or helper_overrun > 0.0:
                        quality_tail_acceptance = {
                            "accepted": False,
                            "reason": "quality_tail_search_deadline_overrun",
                            "deadline_overrun_seconds": max(
                                float(observed_overrun),
                                float(helper_overrun),
                            ),
                        }
                    elif helper_deadline_exhausted:
                        quality_tail_acceptance = {
                            "accepted": False,
                            "reason": "quality_tail_helper_deadline_exhausted",
                        }
                    elif not helper_improved:
                        quality_tail_acceptance = {
                            "accepted": False,
                            "reason": "quality_tail_no_strict_improvement",
                            "optimizer_status": str(
                                getattr(
                                    quality_tail_result,
                                    "status",
                                    "unknown",
                                )
                            ),
                        }
                    else:
                        quality_tail_candidate, quality_tail_acceptance = (
                            _admit_nonworsening_adaptive_candidate(
                                inst,
                                quality_tail_incumbent,
                                quality_tail_result.schedule,
                                require_strict_improvement=True,
                            )
                        )
                        validation_finished = time.perf_counter()
                        completion_overrun = max(
                            0.0,
                            float(validation_finished)
                            - float(phase_execution_deadline),
                        )
                        if completion_overrun > 0.0:
                            quality_tail_acceptance = {
                                **dict(quality_tail_acceptance),
                                "accepted": False,
                                "reason": "quality_tail_service_validation_overrun",
                                "deadline_overrun_seconds": float(completion_overrun),
                            }
                        elif bool(quality_tail_acceptance.get("accepted")):
                            selected_schedule = quality_tail_candidate
                            returned_source = "itc2007_quality_tail"
                            quality_tail_meta["returned_source"] = str(returned_source)
                    quality_tail_meta["service_acceptance"] = dict(
                        quality_tail_acceptance
                    )
                    quality_tail_meta["status"] = (
                        "improved"
                        if bool(quality_tail_acceptance.get("accepted"))
                        else "rejected"
                    )
                except Exception as exc:
                    quality_tail_search_finished = time.perf_counter()
                    quality_tail_meta.update(
                        {
                            "status": "error",
                            "reason": "quality_tail_search_error",
                            "error": f"{type(exc).__name__}: {exc}",
                            "service_acceptance": {
                                "accepted": False,
                                "reason": "quality_tail_search_error",
                            },
                        }
                    )
        quality_tail_phase_finished = time.perf_counter()

        room_cp_phase_started = time.perf_counter()
        room_cp_search_started: float | None = None
        room_cp_search_finished: float | None = None
        room_cp_phase_finished: float = float(room_cp_phase_started)
        room_cp_deadline: float | None = None
        room_cp_service_validation_reserve_seconds = 0.05
        room_cp_minimum_remaining_seconds = 1.0
        room_cp_remaining_at_start = max(
            0.0,
            float(phase_execution_deadline) - float(room_cp_phase_started),
        )
        room_cp_input_source = str(returned_source)
        room_cp_supported = (
            bool(projected_eligible)
            and bool(room_cp_structurally_eligible)
            and int(activity_count) <= 200
        )
        room_cp_eligible = bool(room_cp_supported and room_cp_tail_policy["enabled"])
        room_cp_meta: Dict[str, Any] = {
            "enabled": bool(room_cp_eligible),
            "eligible": bool(room_cp_supported),
            "status": (
                "not_started"
                if room_cp_eligible
                else (
                    "skipped_unreserved" if room_cp_supported else "skipped_ineligible"
                )
            ),
            "reason": (
                "eligible_lossless_itc2007_small_instance"
                if room_cp_eligible
                else (
                    str(room_cp_tail_policy["reason"])
                    if room_cp_supported
                    else (
                        "activity_limit_exceeded"
                        if int(activity_count) > 200
                        else "requires_lossless_itc2007_import"
                    )
                )
            ),
            "activity_count": int(activity_count),
            "activity_limit": 200,
            "eligibility_reasons": list(room_cp_eligibility_reasons),
            "reservation_policy": dict(room_cp_tail_policy),
            "reserved_window_seconds": float(room_cp_reserve_seconds),
            "reservation_start_deadline_seconds": float(
                room_cp_reservation_start_deadline
            ),
            "minimum_remaining_seconds": float(room_cp_minimum_remaining_seconds),
            "remaining_at_start_seconds": float(room_cp_remaining_at_start),
            "service_validation_reserve_seconds": float(
                room_cp_service_validation_reserve_seconds
            ),
            "input_source": str(room_cp_input_source),
            "returned_source": str(room_cp_input_source),
            "service_acceptance": {
                "accepted": False,
                "reason": "not_attempted",
            },
        }
        if room_cp_eligible:
            if room_cp_remaining_at_start < room_cp_minimum_remaining_seconds:
                room_cp_meta.update(
                    {
                        "status": "skipped_insufficient_remaining_time",
                        "reason": "minimum_remaining_window_unavailable",
                        "service_acceptance": {
                            "accepted": False,
                            "reason": "room_cp_not_attempted",
                        },
                    }
                )
            else:
                room_cp_deadline = max(
                    float(room_cp_phase_started),
                    float(phase_execution_deadline)
                    - float(room_cp_service_validation_reserve_seconds),
                )
                room_cp_search_started = time.perf_counter()
                room_cp_incumbent = {
                    int(activity_id): dict(row)
                    for activity_id, row in selected_schedule.items()
                }
                try:
                    room_cp_result = optimize_itc2007_fixed_time_rooms_cp(
                        inst,
                        room_cp_incumbent,
                        deadline=float(room_cp_deadline),
                        seed=int(options.random_seed or 0) + 2_700_001,
                    )
                    room_cp_search_finished = time.perf_counter()
                    room_cp_meta.update(room_cp_result.to_dict())
                    room_cp_meta.update(
                        {
                            "enabled": True,
                            "eligible": True,
                            "optimizer_status": str(room_cp_result.status),
                            "reason": "optimizer_completed",
                            "input_source": str(room_cp_input_source),
                            "returned_source": str(room_cp_input_source),
                            "activity_count": int(activity_count),
                            "activity_limit": 200,
                            "eligibility_reasons": list(room_cp_eligibility_reasons),
                            "reservation_policy": dict(room_cp_tail_policy),
                            "reserved_window_seconds": float(room_cp_reserve_seconds),
                            "reservation_start_deadline_seconds": float(
                                room_cp_reservation_start_deadline
                            ),
                            "minimum_remaining_seconds": float(
                                room_cp_minimum_remaining_seconds
                            ),
                            "remaining_at_start_seconds": float(
                                room_cp_remaining_at_start
                            ),
                            "service_validation_reserve_seconds": float(
                                room_cp_service_validation_reserve_seconds
                            ),
                        }
                    )
                    room_cp_search_overrun = max(
                        0.0,
                        float(room_cp_search_finished) - float(room_cp_deadline),
                    )
                    helper_overrun = max(
                        0.0,
                        float(
                            getattr(
                                room_cp_result,
                                "deadline_overrun_seconds",
                                0.0,
                            )
                        ),
                    )
                    helper_deadline_exhausted = bool(
                        getattr(room_cp_result, "deadline_exhausted", False)
                    )
                    helper_status = str(getattr(room_cp_result, "status", "unknown"))
                    helper_improved = (
                        bool(getattr(room_cp_result, "improved", False))
                        and helper_status == "improved"
                    )
                    if room_cp_search_overrun > 0.0 or helper_overrun > 0.0:
                        room_cp_acceptance = {
                            "accepted": False,
                            "reason": "room_cp_search_deadline_overrun",
                            "deadline_overrun_seconds": max(
                                float(room_cp_search_overrun),
                                float(helper_overrun),
                            ),
                        }
                    elif helper_deadline_exhausted:
                        room_cp_acceptance = {
                            "accepted": False,
                            "reason": "room_cp_helper_deadline_exhausted",
                        }
                    elif helper_status == "error":
                        room_cp_acceptance = {
                            "accepted": False,
                            "reason": "room_cp_helper_error",
                            "error": getattr(room_cp_result, "error", None),
                        }
                    elif not helper_improved:
                        room_cp_acceptance = {
                            "accepted": False,
                            "reason": "room_cp_no_strict_improvement",
                            "optimizer_status": str(helper_status),
                        }
                    else:
                        room_cp_candidate, room_cp_acceptance = (
                            _admit_strict_itc2007_fixed_time_candidate(
                                inst,
                                room_cp_incumbent,
                                room_cp_result.schedule,
                            )
                        )
                        validation_finished = time.perf_counter()
                        completion_overrun = max(
                            0.0,
                            float(validation_finished)
                            - float(phase_execution_deadline),
                        )
                        if completion_overrun > 0.0:
                            room_cp_acceptance = {
                                **dict(room_cp_acceptance),
                                "accepted": False,
                                "reason": "room_cp_service_validation_overrun",
                                "deadline_overrun_seconds": float(completion_overrun),
                            }
                        elif bool(room_cp_acceptance.get("accepted")):
                            selected_schedule = room_cp_candidate
                            returned_source = "itc2007_fixed_time_room_cp"
                            room_cp_meta["returned_source"] = str(returned_source)
                    room_cp_meta["service_acceptance"] = dict(room_cp_acceptance)
                    room_cp_meta["status"] = (
                        "improved"
                        if bool(room_cp_acceptance.get("accepted"))
                        else "rejected"
                    )
                except Exception as exc:
                    room_cp_search_finished = time.perf_counter()
                    room_cp_meta.update(
                        {
                            "status": "error",
                            "reason": "room_cp_search_error",
                            "error": f"{type(exc).__name__}: {exc}",
                            "service_acceptance": {
                                "accepted": False,
                                "reason": "room_cp_search_error",
                            },
                        }
                    )
        room_cp_phase_finished = time.perf_counter()
        try:
            initial_score, initial_objective = _adaptive_acceptance_score(
                inst,
                schedule,
            )
            selected_score, selected_objective = _adaptive_acceptance_score(
                inst,
                selected_schedule,
            )
            overall_improved = bool(
                str(initial_objective) == str(selected_objective)
                and int(selected_score) < int(initial_score)
            )
        except Exception:
            overall_improved = False
        finished = time.perf_counter()
        projected_status = str(projected_result_meta.get("status", "error"))
        meta = {
            "enabled": True,
            "status": ("improved" if overall_improved else projected_status),
            "returned_source": str(returned_source),
            "strategy": "projected_time_space_with_room_feedback",
            "budget_seconds": float(budget_seconds),
            "elapsed_seconds": float(finished - adaptive_started),
            "deadline_overrun_seconds": max(
                0.0,
                float(finished) - float(effective_deadline),
            ),
            "termination_reason": (
                "TIME_LIMIT"
                if float(finished) >= float(effective_deadline)
                else "SEARCH_COMPLETE"
            ),
            "projected_time_search": projected_result_meta,
            "itc2007_room_feedback": feedback_meta,
            "itc2007_rooted_adjacency": rooted_adjacency_meta,
            "itc2007_compound_search": compound_meta,
            "itc2007_quality_tail": quality_tail_meta,
            "itc2007_fixed_time_room_cp": room_cp_meta,
            "phase_timing": {
                "adaptive": {
                    "requested_budget_seconds": float(budget_seconds),
                    "requested_deadline_seconds": float(requested_adaptive_deadline),
                    "reserved_deadline_seconds": float(effective_deadline),
                    "actual_deadline_seconds": float(effective_deadline),
                    "started_at_seconds": float(adaptive_started),
                    "finished_at_seconds": float(finished),
                    "elapsed_seconds": float(finished - adaptive_started),
                    "service_completion_reserve_seconds": float(
                        service_completion_reserve_seconds
                    ),
                    "phase_execution_deadline_seconds": float(phase_execution_deadline),
                },
                "projected_time_search": {
                    "requested_budget_seconds": float(available_window_seconds),
                    "reserved_for_feedback_seconds": float(feedback_reserve_seconds),
                    "reserved_for_compound_seconds": float(compound_reserve_seconds),
                    "reserved_for_rooted_adjacency_seconds": float(
                        rooted_adjacency_reserve_seconds
                    ),
                    "reserved_for_room_cp_seconds": float(room_cp_reserve_seconds),
                    "reserved_for_quality_tail_seconds": float(
                        quality_tail_reserve_seconds
                    ),
                    "reserved_budget_seconds": float(
                        feedback_policy["projected_reserved_seconds"]
                    ),
                    "requested_deadline_seconds": float(
                        room_cp_reservation_start_deadline
                    ),
                    "reserved_deadline_seconds": float(projected_deadline),
                    "actual_deadline_seconds": float(projected_deadline),
                    "started_at_seconds": float(projected_started),
                    "finished_at_seconds": float(projected_finished),
                    "elapsed_seconds": float(projected_finished - projected_started),
                    "deadline_overrun_seconds": float(projected_overrun_seconds),
                },
                "itc2007_room_feedback": {
                    "requested_budget_seconds": float(configured_window),
                    "reserved_budget_seconds": float(feedback_reserve_seconds),
                    "requested_deadline_seconds": (
                        None
                        if feedback_requested_deadline is None
                        else float(feedback_requested_deadline)
                    ),
                    "reserved_deadline_seconds": (
                        float(upstream_execution_deadline)
                        if bool(feedback_policy["enabled"])
                        else None
                    ),
                    "actual_deadline_seconds": (
                        None if feedback_deadline is None else float(feedback_deadline)
                    ),
                    "started_at_seconds": float(feedback_phase_started),
                    "search_started_at_seconds": (
                        None
                        if feedback_search_started is None
                        else float(feedback_search_started)
                    ),
                    "search_finished_at_seconds": (
                        None
                        if feedback_search_finished is None
                        else float(feedback_search_finished)
                    ),
                    "finished_at_seconds": float(feedback_phase_finished),
                    "elapsed_seconds": float(
                        feedback_phase_finished - feedback_phase_started
                    ),
                    "deadline_overrun_seconds": (
                        0.0
                        if feedback_deadline is None
                        else max(
                            0.0,
                            float(feedback_phase_finished) - float(feedback_deadline),
                        )
                    ),
                },
                "itc2007_rooted_adjacency": {
                    "requested_budget_seconds": float(
                        rooted_adjacency_policy["target_seconds"]
                    ),
                    "reserved_budget_seconds": float(rooted_adjacency_reserve_seconds),
                    "reservation_start_deadline_seconds": float(
                        rooted_adjacency_reservation_start_deadline
                    ),
                    "requested_deadline_seconds": (
                        float(room_cp_reservation_start_deadline)
                        if bool(rooted_adjacency_policy["enabled"])
                        else None
                    ),
                    "reserved_deadline_seconds": (
                        None
                        if rooted_adjacency_deadline is None
                        else float(rooted_adjacency_deadline)
                    ),
                    "actual_deadline_seconds": (
                        None
                        if rooted_adjacency_deadline is None
                        else float(rooted_adjacency_deadline)
                    ),
                    "started_at_seconds": float(rooted_adjacency_phase_started),
                    "search_started_at_seconds": (
                        None
                        if rooted_adjacency_search_started is None
                        else float(rooted_adjacency_search_started)
                    ),
                    "search_finished_at_seconds": (
                        None
                        if rooted_adjacency_search_finished is None
                        else float(rooted_adjacency_search_finished)
                    ),
                    "finished_at_seconds": float(rooted_adjacency_phase_finished),
                    "elapsed_seconds": float(
                        rooted_adjacency_phase_finished - rooted_adjacency_phase_started
                    ),
                    "deadline_overrun_seconds": (
                        0.0
                        if rooted_adjacency_deadline is None
                        else max(
                            0.0,
                            float(rooted_adjacency_phase_finished)
                            - float(rooted_adjacency_deadline),
                        )
                    ),
                },
                "itc2007_compound_search": {
                    "requested_budget_seconds": float(
                        compound_policy["target_seconds"]
                    ),
                    "reserved_budget_seconds": float(compound_reserve_seconds),
                    "requested_deadline_seconds": (
                        float(room_cp_reservation_start_deadline)
                        if bool(compound_policy["enabled"])
                        else None
                    ),
                    "reserved_deadline_seconds": (
                        float(room_cp_reservation_start_deadline)
                        if bool(compound_policy["enabled"])
                        else None
                    ),
                    "actual_deadline_seconds": (
                        None if compound_deadline is None else float(compound_deadline)
                    ),
                    "started_at_seconds": float(compound_phase_started),
                    "search_started_at_seconds": (
                        None
                        if compound_search_started is None
                        else float(compound_search_started)
                    ),
                    "search_finished_at_seconds": (
                        None
                        if compound_search_finished is None
                        else float(compound_search_finished)
                    ),
                    "finished_at_seconds": float(compound_phase_finished),
                    "elapsed_seconds": float(
                        compound_phase_finished - compound_phase_started
                    ),
                    "deadline_overrun_seconds": (
                        0.0
                        if compound_deadline is None
                        else max(
                            0.0,
                            float(compound_phase_finished) - float(compound_deadline),
                        )
                    ),
                },
                "itc2007_quality_tail": {
                    "requested_budget_seconds": float(
                        quality_tail_policy["target_seconds"]
                    ),
                    "reserved_budget_seconds": float(quality_tail_reserve_seconds),
                    "reservation_start_deadline_seconds": float(
                        quality_tail_reservation_start_deadline
                    ),
                    "requested_deadline_seconds": (
                        float(phase_execution_deadline)
                        if bool(quality_tail_eligible)
                        else None
                    ),
                    "reserved_deadline_seconds": (
                        None
                        if quality_tail_deadline is None
                        else float(quality_tail_deadline)
                    ),
                    "actual_deadline_seconds": (
                        None
                        if quality_tail_deadline is None
                        else float(quality_tail_deadline)
                    ),
                    "phase_completion_deadline_seconds": float(
                        phase_execution_deadline
                    ),
                    "service_validation_reserve_seconds": float(
                        quality_tail_service_validation_reserve_seconds
                    ),
                    "remaining_at_start_seconds": float(
                        quality_tail_remaining_at_start
                    ),
                    "started_at_seconds": float(quality_tail_phase_started),
                    "search_started_at_seconds": (
                        None
                        if quality_tail_search_started is None
                        else float(quality_tail_search_started)
                    ),
                    "search_finished_at_seconds": (
                        None
                        if quality_tail_search_finished is None
                        else float(quality_tail_search_finished)
                    ),
                    "finished_at_seconds": float(quality_tail_phase_finished),
                    "elapsed_seconds": float(
                        quality_tail_phase_finished - quality_tail_phase_started
                    ),
                    "search_deadline_overrun_seconds": (
                        0.0
                        if quality_tail_deadline is None
                        or quality_tail_search_finished is None
                        else max(
                            0.0,
                            float(quality_tail_search_finished)
                            - float(quality_tail_deadline),
                        )
                    ),
                    "phase_completion_overrun_seconds": max(
                        0.0,
                        float(quality_tail_phase_finished)
                        - float(phase_execution_deadline),
                    ),
                },
                "itc2007_fixed_time_room_cp": {
                    "reserved_budget_seconds": float(room_cp_reserve_seconds),
                    "reservation_start_deadline_seconds": float(
                        room_cp_reservation_start_deadline
                    ),
                    "minimum_admission_window_seconds": float(
                        room_cp_minimum_remaining_seconds
                    ),
                    "remaining_at_start_seconds": float(room_cp_remaining_at_start),
                    "requested_deadline_seconds": (
                        float(phase_execution_deadline)
                        if bool(room_cp_eligible)
                        else None
                    ),
                    "reserved_deadline_seconds": (
                        None if room_cp_deadline is None else float(room_cp_deadline)
                    ),
                    "actual_deadline_seconds": (
                        None if room_cp_deadline is None else float(room_cp_deadline)
                    ),
                    "phase_completion_deadline_seconds": float(
                        phase_execution_deadline
                    ),
                    "service_validation_reserve_seconds": float(
                        room_cp_service_validation_reserve_seconds
                    ),
                    "started_at_seconds": float(room_cp_phase_started),
                    "search_started_at_seconds": (
                        None
                        if room_cp_search_started is None
                        else float(room_cp_search_started)
                    ),
                    "search_finished_at_seconds": (
                        None
                        if room_cp_search_finished is None
                        else float(room_cp_search_finished)
                    ),
                    "finished_at_seconds": float(room_cp_phase_finished),
                    "elapsed_seconds": float(
                        room_cp_phase_finished - room_cp_phase_started
                    ),
                    "search_deadline_overrun_seconds": (
                        0.0
                        if room_cp_deadline is None or room_cp_search_finished is None
                        else max(
                            0.0,
                            float(room_cp_search_finished) - float(room_cp_deadline),
                        )
                    ),
                    "phase_completion_overrun_seconds": max(
                        0.0,
                        float(room_cp_phase_finished) - float(phase_execution_deadline),
                    ),
                },
                "policy": {
                    **dict(feedback_policy),
                    "rooted_adjacency": dict(rooted_adjacency_policy),
                    "compound": dict(compound_policy),
                    "room_cp": dict(room_cp_tail_policy),
                    "quality_tail": dict(quality_tail_policy),
                },
            },
            "projected_time_search_policy": {
                "requested": True,
                "eligible": True,
                "reasons": [],
                "fallback": None,
            },
            "neighborhood_size_policy": dict(neighborhood_size_policy),
        }
        return selected_schedule, meta
    exact_limit = max(1, int(options.adaptive_lns_exact_activity_limit))
    if activity_count > exact_limit:
        meta = {
            "enabled": False,
            "status": "SKIPPED_MODEL_SIZE",
            "activity_count": int(activity_count),
            "exact_activity_limit": int(exact_limit),
            "reason": (
                "Exact full-model neighborhoods are disabled above the configured limit; "
                "use the partitioned incumbent/local improvement path or raise the limit "
                "after measuring memory."
            ),
            "budget_seconds": float(budget_seconds),
            "elapsed_seconds": float(time.perf_counter() - adaptive_started),
            "deadline_overrun_seconds": 0.0,
            "neighborhood_size_policy": dict(neighborhood_size_policy),
        }
        if fixed_time_room_dive_enabled:
            _, room_dive_meta = _run_fixed_time_room_dive(
                inst,
                schedule,
                None,
                budget_seconds=float(fixed_time_room_dive_budget_seconds),
                final_deadline=final_deadline,
                workers=int(options.workers or 1),
                seed=int(options.random_seed or 0),
                completion_reserve_seconds=float(
                    fixed_time_room_dive_completion_reserve_seconds
                ),
                strategy=str(fixed_time_room_strategy),
            )
            meta["fixed_time_room_dive"] = dict(room_dive_meta)
        return schedule, meta
    if budget_seconds <= 0:
        meta = {
            "enabled": True,
            "status": "BUDGET_EXHAUSTED_BEFORE_BUILD",
            "budget_seconds": 0.0,
            "elapsed_seconds": float(time.perf_counter() - adaptive_started),
            "deadline_overrun_seconds": 0.0,
            "termination_reason": "TIME_LIMIT",
            "trace": [],
            "rounds_completed": 0,
            "neighborhood_size_policy": dict(neighborhood_size_policy),
        }
        if fixed_time_room_dive_enabled:
            _, room_dive_meta = _run_fixed_time_room_dive(
                inst,
                schedule,
                None,
                budget_seconds=float(fixed_time_room_dive_budget_seconds),
                final_deadline=final_deadline,
                workers=int(options.workers or 1),
                seed=int(options.random_seed or 0),
                completion_reserve_seconds=float(
                    fixed_time_room_dive_completion_reserve_seconds
                ),
                strategy=str(fixed_time_room_strategy),
            )
            meta["fixed_time_room_dive"] = dict(room_dive_meta)
        return schedule, meta

    engine = CertificateGuidedAdaptiveLNS(
        inst,
        neighborhood_sizes=sizes,
        random_seed=int(options.random_seed or 0),
    )
    model_started = time.perf_counter()
    reusable_model = TimetableSolver(
        copy.deepcopy(inst),
        room_mode="cp_rooms",
        use_objective=True,
    )
    model_build_seconds = float(time.perf_counter() - model_started)
    hint_started = time.perf_counter()
    reusable_model.add_solution_hint(schedule, include_rooms=True)
    hint_setup_seconds = float(time.perf_counter() - hint_started)
    shared_proto = reusable_model.m.Proto()
    objective_fingerprint = hashlib.sha256(
        str(shared_proto.objective).encode("utf-8")
    ).hexdigest()
    shared_model_meta = {
        "variables": len(shared_proto.variables),
        "constraints": len(shared_proto.constraints),
        "start_literals": len(reusable_model.x),
        "room_literals": len(reusable_model.room_sel),
        "one_time_build_seconds": float(model_build_seconds),
        "initial_hint_setup_seconds": float(hint_setup_seconds),
        "objective_fingerprint": str(objective_fingerprint),
        "objective_reused_across_rounds": True,
        "reused_across_rounds": True,
    }

    _, acceptance_objective = _adaptive_acceptance_score(
        inst,
        schedule,
    )

    def score_fn(candidate: Dict[int, Dict[str, Any]]) -> int:
        score, _objective = _adaptive_acceptance_score(inst, candidate)
        return int(score)

    def validate_fn(candidate: Dict[int, Dict[str, Any]]) -> List[str]:
        return validate_schedule_against_instance(
            inst,
            candidate,
            strict_rooms=True,
            require_all_activities=True,
        )

    def repair_fn(
        neighborhood: List[int],
        incumbent: Dict[int, Dict[str, Any]],
        seconds: float,
        seed: int,
    ) -> RepairOutcome:
        started = time.perf_counter()
        round_deadline = float(started) + max(0.0, float(seconds))
        try:
            assumption_meta = reusable_model.set_neighborhood_assumptions(
                incumbent,
                unlocked_activity_ids=set(neighborhood),
            )
            setup_seconds = float(time.perf_counter() - started)
            deadline_safety_margin_seconds = min(
                0.01,
                max(0.0005, max(0.0, float(seconds)) * 0.02),
            )
            search_budget_seconds = max(
                0.0,
                float(round_deadline)
                - time.perf_counter()
                - float(deadline_safety_margin_seconds),
            )
            current_proto = reusable_model.m.Proto()
            current_objective_fingerprint = hashlib.sha256(
                str(current_proto.objective).encode("utf-8")
            ).hexdigest()
            model_stats = {
                **shared_model_meta,
                **assumption_meta,
                "round_setup_seconds": float(setup_seconds),
                "slice_budget_seconds": max(0.0, float(seconds)),
                "deadline_safety_margin_seconds": float(deadline_safety_margin_seconds),
                "search_budget_seconds": float(search_budget_seconds),
                "model_structure_unchanged": bool(
                    len(current_proto.variables) == int(shared_model_meta["variables"])
                    and len(current_proto.constraints)
                    == int(shared_model_meta["constraints"])
                ),
                "objective_unchanged": bool(
                    current_objective_fingerprint
                    == str(shared_model_meta["objective_fingerprint"])
                ),
            }
            if search_budget_seconds <= 0:
                model_stats.update(
                    {
                        "search_seconds": 0.0,
                        "deadline_overrun_seconds": max(
                            0.0,
                            time.perf_counter() - float(round_deadline),
                        ),
                        "proof_status": "none",
                        "proof_scope": "neighborhood",
                    }
                )
                return RepairOutcome(
                    schedule=None,
                    score=None,
                    elapsed_seconds=float(time.perf_counter() - started),
                    status="BUDGET_EXHAUSTED",
                    validated=False,
                    proof_status="none",
                    proof_scope="neighborhood",
                    metadata=model_stats,
                )
            search_started = time.perf_counter()
            solver, raw_status = reusable_model.solve(
                time_limit_seconds=float(search_budget_seconds),
                workers=max(1, min(4, int(options.workers or 1))),
                random_seed=int(seed),
                log_progress=False,
            )
            model_stats["search_seconds"] = float(time.perf_counter() - search_started)
            model_stats["deadline_overrun_seconds"] = max(
                0.0,
                time.perf_counter() - float(round_deadline),
            )
            model_stats["proof_status"] = _proof_status(int(raw_status))
            model_stats["proof_scope"] = "neighborhood"
            status_name = str(cp_model.CpSolverStatus(int(raw_status)))
            if not _is_feasible(int(raw_status)):
                core_ids = reusable_model.assumption_core_activity_ids(
                    solver,
                    raw_status=int(raw_status),
                )
                return RepairOutcome(
                    schedule=None,
                    score=None,
                    elapsed_seconds=float(time.perf_counter() - started),
                    status=status_name,
                    validated=False,
                    proof_status=_proof_status(int(raw_status)),
                    proof_scope="neighborhood",
                    certificates=(
                        [
                            CertificateSignal(
                                certificate_type="assumption_core",
                                activity_ids=tuple(core_ids),
                                weight=float(max(1, len(core_ids))),
                                metadata={"source": "cp_sat_assumption_core"},
                            )
                        ]
                        if core_ids
                        else []
                    ),
                    metadata=model_stats,
                )
            candidate = reusable_model.extract_solution(solver)
            errors = validate_fn(candidate)
            objective_info = _objective_bound_info(
                solver,
                int(raw_status),
                use_objective=True,
            )
            return RepairOutcome(
                schedule=candidate,
                score=score_fn(candidate),
                elapsed_seconds=float(time.perf_counter() - started),
                status=status_name,
                validated=not errors,
                neighborhood_optimal=int(raw_status) == int(cp_model.OPTIMAL),
                objective_value=objective_info["objective_value"],
                best_objective_bound=objective_info["best_objective_bound"],
                relative_gap=objective_info["relative_gap"],
                proof_status=_proof_status(int(raw_status)),
                proof_scope="neighborhood",
                metadata=model_stats,
            )
        except Exception as exc:
            return RepairOutcome(
                schedule=None,
                score=None,
                elapsed_seconds=float(time.perf_counter() - started),
                status=f"ERROR:{type(exc).__name__}:{exc}",
                validated=False,
                proof_status="error",
                proof_scope="neighborhood",
            )

    if progress_hook is not None:
        progress_hook(
            "adaptive_lns_start",
            {
                "total_seconds": float(options.adaptive_lns_seconds),
                "slice_seconds": float(options.adaptive_lns_slice_seconds),
                "neighborhood_sizes": list(sizes),
                "neighborhood_size_policy": dict(neighborhood_size_policy),
            },
        )
    remaining_after_build = max(0.0, float(deadline) - time.perf_counter())
    if remaining_after_build <= 0:
        elapsed_seconds = float(time.perf_counter() - adaptive_started)
        meta = {
            "enabled": True,
            "status": "BUDGET_EXHAUSTED_AFTER_BUILD",
            "initial_score": int(score_fn(schedule)),
            "final_score": int(score_fn(schedule)),
            "improvement": 0,
            "trace": [],
            "rounds_completed": 0,
            "budget_seconds": float(budget_seconds),
            "elapsed_seconds": float(elapsed_seconds),
            "deadline_overrun_seconds": max(
                0.0,
                elapsed_seconds - float(budget_seconds),
            ),
            "termination_reason": "TIME_LIMIT",
            "reusable_model": dict(shared_model_meta),
            "acceptance_objective": str(acceptance_objective),
            "neighborhood_size_policy": dict(neighborhood_size_policy),
        }
        if fixed_time_room_dive_enabled:
            schedule, room_dive_meta = _run_fixed_time_room_dive(
                inst,
                schedule,
                reusable_model,
                budget_seconds=float(fixed_time_room_dive_budget_seconds),
                final_deadline=final_deadline,
                workers=int(options.workers or 1),
                seed=int(options.random_seed or 0),
                completion_reserve_seconds=float(
                    fixed_time_room_dive_completion_reserve_seconds
                ),
                strategy=str(fixed_time_room_strategy),
            )
            meta["fixed_time_room_dive"] = dict(room_dive_meta)
            returned_score = room_dive_meta.get("returned_score")
            meta["final_score"] = (
                int(returned_score)
                if returned_score is not None
                else int(score_fn(schedule))
            )
            meta["improvement"] = int(meta["initial_score"]) - int(meta["final_score"])
        if progress_hook is not None:
            progress_hook("adaptive_lns_done", dict(meta))
        return schedule, meta

    result = engine.run(
        schedule,
        score_fn=score_fn,
        validate_fn=validate_fn,
        repair_fn=repair_fn,
        total_seconds=float(remaining_after_build),
        slice_seconds=float(options.adaptive_lns_slice_seconds),
        max_rounds=int(options.adaptive_lns_max_rounds),
        initial_certificates=certificate_signals_from_decomposition(
            decomposition_report
        ),
    )
    meta = result.to_dict(include_schedule=False)
    elapsed_seconds = float(time.perf_counter() - adaptive_started)
    meta.update(
        {
            "enabled": True,
            "status": (
                "TIME_LIMIT"
                if str(result.termination_reason) == "TIME_LIMIT"
                else "COMPLETE"
            ),
            "engine_budget_seconds": float(result.budget_seconds),
            "budget_seconds": float(budget_seconds),
            "elapsed_seconds": float(elapsed_seconds),
            "deadline_overrun_seconds": max(
                0.0,
                elapsed_seconds - float(budget_seconds),
            ),
            "guarantee": (
                "Every accepted incumbent passed the independent hard validator. "
                "OPTIMAL trace rows certify only their frozen neighborhood, not global optimality."
            ),
            "reusable_model": dict(shared_model_meta),
            "acceptance_objective": str(acceptance_objective),
            "neighborhood_size_policy": dict(neighborhood_size_policy),
        }
    )
    if fixed_time_room_dive_enabled:
        room_dive_incumbent = result.schedule
        room_dive_schedule, room_dive_meta = _run_fixed_time_room_dive(
            inst,
            room_dive_incumbent,
            reusable_model,
            budget_seconds=float(fixed_time_room_dive_budget_seconds),
            final_deadline=final_deadline,
            workers=int(options.workers or 1),
            seed=int(options.random_seed or 0),
            completion_reserve_seconds=float(
                fixed_time_room_dive_completion_reserve_seconds
            ),
            strategy=str(fixed_time_room_strategy),
        )
        meta["fixed_time_room_dive"] = dict(room_dive_meta)
        returned_score = room_dive_meta.get("returned_score")
        meta["final_score"] = (
            int(returned_score)
            if returned_score is not None
            else int(score_fn(room_dive_schedule))
        )
        meta["improvement"] = int(meta["initial_score"]) - int(meta["final_score"])
        result.schedule = room_dive_schedule
    if progress_hook is not None:
        progress_hook("adaptive_lns_done", dict(meta))
    return result.schedule, meta


def solve_instance(
    inst,
    options: SolveOptions,
    *,
    progress_hook: Callable[[str, Dict[str, Any]], None] | None = None,
) -> SolveResult:
    solve_instance_started = time.perf_counter()
    total_budget_seconds = (
        None
        if options.time_limit_seconds is None
        else max(0.0, float(options.time_limit_seconds))
    )
    total_deadline = (
        None
        if total_budget_seconds is None
        else float(solve_instance_started) + float(total_budget_seconds)
    )

    def total_remaining_seconds() -> float | None:
        if total_deadline is None:
            return None
        return max(0.0, float(total_deadline) - time.perf_counter())

    def total_timing_meta() -> Dict[str, Any]:
        elapsed_seconds = float(time.perf_counter() - solve_instance_started)
        return {
            "budget_seconds": total_budget_seconds,
            "elapsed_seconds": elapsed_seconds,
            "deadline_overrun_seconds": (
                0.0
                if total_budget_seconds is None
                else max(0.0, elapsed_seconds - float(total_budget_seconds))
            ),
            "budget_exhausted": bool(
                total_deadline is not None
                and time.perf_counter() >= float(total_deadline)
            ),
        }

    def finalization_reserve_seconds() -> float:
        if total_budget_seconds is None:
            return 0.0
        remaining = total_remaining_seconds()
        if remaining is None:
            return 0.0
        configured = min(
            0.50,
            max(0.05, float(total_budget_seconds) * 0.05),
        )
        return min(max(0.0, float(remaining)), float(configured))

    def completion_reserve_seconds() -> float:
        """Keep result scoring/construction outside the optional room-dive budget."""
        if total_budget_seconds is None:
            return 0.0
        remaining = total_remaining_seconds()
        if remaining is None:
            return 0.0
        configured = min(
            0.25,
            max(0.05, float(total_budget_seconds) * 0.025),
        )
        return min(max(0.0, float(remaining)), float(configured))

    inst_profiled, resolved_options, profile_meta = _apply_objective_profile(
        inst, options
    )
    inst_work, resolved_options, incremental_meta = _apply_incremental_scope(
        inst_profiled,
        resolved_options,
    )

    cache_key = None
    if progress_hook is None:
        try:
            cache_key = _solve_cache_key(inst_work, resolved_options)
        except Exception:
            cache_key = None
        if cache_key and cache_key in _SOLVE_RESULT_CACHE:
            cached = copy.deepcopy(_SOLVE_RESULT_CACHE[cache_key])
            cached.meta = dict(cached.meta or {})
            cached.meta["cached"] = True
            cached.meta["timing"] = {
                **total_timing_meta(),
                "source": "cache",
            }
            return cached

    attempts: List[SolveAttempt] = []
    fairness_first_meta: Dict[str, Any] | None = None
    research_adaptive_meta: Dict[str, Any] | None = None
    validated_profile_schedule: Dict[int, Dict[str, Any]] | None = None

    def profile_execution_meta() -> Dict[str, Any]:
        execution: Dict[str, Any] = {}
        if fairness_first_meta is not None:
            execution["fairness_first"] = dict(fairness_first_meta)
        if research_adaptive_meta is not None:
            research_snapshot = dict(research_adaptive_meta)
            research_snapshot["remaining_at_snapshot_seconds"] = (
                total_remaining_seconds()
            )
            research_snapshot["total_timing"] = total_timing_meta()
            execution["research_adaptive"] = research_snapshot
        return execution

    def emit(event: str, **payload: Any) -> None:
        if progress_hook is not None:
            progress_hook(str(event), dict(payload))

    room_mode = str(resolved_options.room_mode)
    use_objective = bool(resolved_options.use_objective)
    strict_limit = resolved_options.strict_limit_seconds
    if strict_limit is None and resolved_options.time_limit_seconds is not None:
        strict_limit = min(float(resolved_options.time_limit_seconds), 300.0)

    strict_options = replace(resolved_options, time_limit_seconds=strict_limit)
    full_options = replace(resolved_options)

    if str(profile_meta.get("id")) == "research_adaptive":
        research_adaptive_meta = {
            "status": "INITIAL_FEASIBILITY_PENDING",
            "total_budget_seconds": total_budget_seconds,
            "initial_feasibility_allocation_seconds": (
                None
                if resolved_options.time_limit_seconds is None
                else float(resolved_options.time_limit_seconds)
            ),
            "adaptive_allocation_seconds": float(resolved_options.adaptive_lns_seconds),
            "initial_valid": False,
            "rescue_attempted": False,
            "rescue_valid": False,
            "returned_source": "none",
        }

    emit(
        "run_start",
        room_mode=room_mode,
        use_objective=use_objective,
        phased=bool(resolved_options.phased_solve),
        objective_profile=dict(profile_meta),
        incremental=dict(incremental_meta),
    )

    def solve_attempt(mode: str, objective: bool, run_options: SolveOptions):
        overall_remaining = total_remaining_seconds()
        if overall_remaining is not None:
            effective_limit = (
                float(overall_remaining)
                if run_options.time_limit_seconds is None
                else min(
                    max(0.0, float(run_options.time_limit_seconds)),
                    float(overall_remaining),
                )
            )
            run_options = replace(
                run_options,
                time_limit_seconds=max(0.0, float(effective_limit)),
            )
        emit(
            "solve_attempt_start",
            attempt=len(attempts) + 1,
            mode=str(mode),
            objective=bool(objective),
            limit_seconds=(
                float(run_options.time_limit_seconds)
                if run_options.time_limit_seconds is not None
                else None
            ),
        )
        started = time.perf_counter()
        model, solver, raw_status, attempt = _run_solve_attempt(
            inst_work,
            room_mode=mode,
            use_objective=objective,
            options=run_options,
        )
        attempts.append(attempt)
        emit(
            "solve_attempt_done",
            attempt=len(attempts),
            mode=str(mode),
            objective=bool(objective),
            status=int(raw_status),
            elapsed_seconds=float(time.perf_counter() - started),
        )
        return model, solver, raw_status, attempt

    def remaining_seconds(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return max(0.0, float(deadline) - time.perf_counter())

    def enough_time_for_another_attempt(target_mode: str) -> bool:
        remaining = total_remaining_seconds()
        if remaining is None:
            return True
        same_mode_builds = [
            float(attempt.model_build_seconds)
            for attempt in attempts
            if str(attempt.room_mode) == str(target_mode)
            and float(attempt.model_build_seconds) > 0
        ]
        if same_mode_builds:
            estimated_build = max(same_mode_builds)
        elif attempts:
            # Greedy fallback models are materially smaller than CP-room models,
            # but still need a nonzero construction/search window.
            estimated_build = max(
                0.02,
                min(float(attempt.model_build_seconds) for attempt in attempts)
                * (0.20 if str(target_mode) == "greedy" else 0.75),
            )
        else:
            estimated_build = 0.02
        return float(remaining) > max(0.025, float(estimated_build) * 1.10)

    if str(profile_meta.get("id")) == "fairness_first":
        bootstrap_budget_seconds = _fairness_feasibility_budget(
            total_budget_seconds,
            resolved_options.feasibility_seconds,
        )
        fairness_first_meta = {
            "status": "BOOTSTRAP_PENDING",
            "bootstrap_budget_seconds": float(bootstrap_budget_seconds),
            "bootstrap_attempted": False,
            "bootstrap_valid": False,
            "fairness_attempted": False,
            "fairness_solution_available": False,
            "fairness_optimization_complete": False,
            "returned_source": "none",
        }
        retained_incumbent: tuple[Any, Any, int, Dict[int, Dict[str, Any]]] | None = (
            None
        )

        if bootstrap_budget_seconds > 0:
            fairness_first_meta["bootstrap_attempted"] = True
            emit(
                "fairness_bootstrap_start",
                limit_seconds=float(bootstrap_budget_seconds),
            )
            model, solver, raw_status, bootstrap_attempt = solve_attempt(
                room_mode,
                False,
                replace(
                    full_options,
                    time_limit_seconds=float(bootstrap_budget_seconds),
                ),
            )
            fairness_first_meta.update(
                {
                    "bootstrap_attempt_index": int(len(attempts)),
                    "bootstrap_status_name": str(bootstrap_attempt.status_name),
                    "bootstrap_proof_status": str(bootstrap_attempt.proof_status),
                    "bootstrap_decomposition": dict(
                        getattr(model, "decomposition_report", {}) or {}
                    ),
                }
            )
            bootstrap_errors: List[str] = []
            if _is_feasible(raw_status):
                try:
                    bootstrap_schedule = model.extract_solution(solver)
                    bootstrap_errors = validate_schedule_against_instance(
                        inst_work,
                        bootstrap_schedule,
                        strict_rooms=True,
                        require_all_activities=True,
                    )
                except Exception as exc:  # Defensive release boundary.
                    bootstrap_schedule = {}
                    bootstrap_errors = [
                        f"bootstrap extraction failed: {type(exc).__name__}: {exc}"
                    ]
                if not bootstrap_errors:
                    retained_incumbent = (
                        model,
                        solver,
                        int(raw_status),
                        {
                            int(activity_id): dict(info)
                            for activity_id, info in bootstrap_schedule.items()
                        },
                    )
            fairness_first_meta["bootstrap_valid"] = retained_incumbent is not None
            fairness_first_meta["bootstrap_validation_error_count"] = int(
                len(bootstrap_errors)
            )
            if bootstrap_errors:
                fairness_first_meta["bootstrap_validation_errors"] = list(
                    bootstrap_errors[:10]
                )
            emit(
                "fairness_bootstrap_done",
                status=int(raw_status),
                valid=bool(retained_incumbent is not None),
            )
        else:
            model = None
            solver = cp_model.CpSolver()
            raw_status = int(cp_model.UNKNOWN)

        fairness_remaining = total_remaining_seconds()
        fairness_limit = (
            None if fairness_remaining is None else max(0.0, float(fairness_remaining))
        )
        if strict_limit is not None:
            fairness_limit = (
                max(0.0, float(strict_limit))
                if fairness_limit is None
                else min(float(fairness_limit), max(0.0, float(strict_limit)))
            )
        if (
            fairness_limit is None or fairness_limit > 0
        ) and enough_time_for_another_attempt(room_mode):
            fairness_first_meta["fairness_attempted"] = True
            hinted_schedule = (
                retained_incumbent[3]
                if retained_incumbent is not None
                else resolved_options.base_schedule
            )
            fairness_model, fairness_solver, fairness_status, fairness_attempt = (
                solve_attempt(
                    room_mode,
                    True,
                    replace(
                        full_options,
                        time_limit_seconds=fairness_limit,
                        base_schedule=hinted_schedule,
                    ),
                )
            )
            fairness_report = dict(
                getattr(fairness_model, "decomposition_report", {}) or {}
            )
            fairness_first_meta.update(
                {
                    "fairness_attempt_index": int(len(attempts)),
                    "fairness_status_name": str(fairness_attempt.status_name),
                    "fairness_proof_status": str(fairness_attempt.proof_status),
                    "fairness_decomposition": fairness_report,
                    "fairness_solution_available": bool(_is_feasible(fairness_status)),
                    "fairness_optimization_complete": bool(
                        int(fairness_status) == int(cp_model.OPTIMAL)
                    ),
                }
            )
            if _is_feasible(fairness_status):
                model, solver, raw_status = (
                    fairness_model,
                    fairness_solver,
                    int(fairness_status),
                )
                fairness_first_meta["returned_source"] = "fairness_solution"
                fairness_first_meta["status"] = (
                    "FAIRNESS_OPTIMAL"
                    if int(fairness_status) == int(cp_model.OPTIMAL)
                    else "FAIRNESS_INCUMBENT"
                )
            elif retained_incumbent is not None:
                model, solver, _, _ = retained_incumbent
                # The feasibility solve may be optimal for its empty objective,
                # but it is only an incumbent for the requested fairness model.
                raw_status = int(cp_model.FEASIBLE)
                fairness_first_meta["returned_source"] = "feasibility_incumbent"
                fairness_first_meta["status"] = (
                    "FEASIBILITY_INCUMBENT_FAIRNESS_INCOMPLETE"
                )
            else:
                model, solver, raw_status = (
                    fairness_model,
                    fairness_solver,
                    int(fairness_status),
                )
                fairness_first_meta["status"] = "NO_FEASIBLE_INCUMBENT"
        elif retained_incumbent is not None:
            model, solver, _, _ = retained_incumbent
            raw_status = int(cp_model.FEASIBLE)
            fairness_first_meta["returned_source"] = "feasibility_incumbent"
            fairness_first_meta["status"] = "FEASIBILITY_INCUMBENT_FAIRNESS_NOT_STARTED"
            fairness_first_meta["fairness_proof_status"] = "not_started"
        else:
            fairness_first_meta["status"] = "NO_FEASIBLE_INCUMBENT"
            fairness_first_meta["fairness_proof_status"] = "not_started"
    elif resolved_options.phased_solve:
        feasibility_limit = (
            resolved_options.feasibility_seconds
            if resolved_options.feasibility_seconds is not None
            else strict_limit
        )
        feasibility_deadline = (
            time.perf_counter() + float(feasibility_limit)
            if feasibility_limit is not None
            else None
        )
        fallback_reserve = 0.0
        if (
            room_mode == "cp_rooms"
            and feasibility_limit is not None
            and float(feasibility_limit) >= 60.0
        ):
            fallback_reserve = min(
                90.0,
                max(15.0, float(feasibility_limit) * 0.20),
                max(0.0, float(feasibility_limit) - 1.0),
            )
        strict_limit_phase = (
            max(1.0, float(feasibility_limit) - float(fallback_reserve))
            if feasibility_limit is not None
            else None
        )
        strict_deadline = (
            time.perf_counter() + float(strict_limit_phase)
            if strict_limit_phase is not None
            else feasibility_deadline
        )
        phased_options = replace(
            resolved_options,
            time_limit_seconds=(
                remaining_seconds(strict_deadline)
                if strict_deadline is not None
                else strict_limit_phase
            ),
        )
        model, solver, raw_status, attempt = solve_attempt(
            room_mode, False, phased_options
        )
        fallback_limit = remaining_seconds(feasibility_deadline)
        if (
            room_mode == "cp_rooms"
            and not _is_feasible(raw_status)
            and (fallback_limit is None or fallback_limit > 0)
            and enough_time_for_another_attempt("greedy")
        ):
            emit("solve_fallback", from_mode="cp_rooms", to_mode="greedy")
            model, solver, raw_status, attempt = solve_attempt(
                "greedy",
                False,
                replace(resolved_options, time_limit_seconds=fallback_limit),
            )
    else:
        solve_deadline = (
            time.perf_counter() + float(resolved_options.time_limit_seconds)
            if resolved_options.time_limit_seconds is not None
            else None
        )
        first_options = strict_options if use_objective else full_options
        if solve_deadline is not None and first_options.time_limit_seconds is not None:
            first_options = replace(
                first_options,
                time_limit_seconds=min(
                    float(first_options.time_limit_seconds),
                    float(remaining_seconds(solve_deadline) or 0.0),
                ),
            )
        model = None
        solver = None
        raw_status = int(cp_model.UNKNOWN)
        constructive_result = None
        use_constructive_initializer = bool(
            research_adaptive_meta is not None
            and resolved_options.projected_time_search
            and solve_deadline is not None
        )
        if use_constructive_initializer:
            constructive_strategy_policy = (
                _itc2007_constructive_initializer_strategy_policy(
                    inst_work,
                    activity_count=len(inst_work.activities),
                    requested_strategy="balanced",
                )
            )
            constructive_strategy = str(
                constructive_strategy_policy["effective_strategy"]
            )
            research_adaptive_meta["constructive_initializer_policy"] = dict(
                constructive_strategy_policy
            )
            remaining_initial = max(
                0.0,
                float(remaining_seconds(solve_deadline) or 0.0),
            )
            constructive_reserve = min(0.05, remaining_initial * 0.05)
            constructive_budget = min(
                1.25,
                max(0.0, remaining_initial - constructive_reserve),
            )
            constructive_deadline = min(
                float(solve_deadline) - float(constructive_reserve),
                time.perf_counter() + float(constructive_budget),
            )
            emit(
                "research_constructive_initializer_start",
                budget_seconds=float(constructive_budget),
                random_seed=int(resolved_options.random_seed or 0),
                requested_strategy=str(
                    constructive_strategy_policy["requested_strategy"]
                ),
                effective_strategy=str(constructive_strategy),
                strategy_reason=str(constructive_strategy_policy["reason"]),
            )
            constructive_result = construct_itc2007_schedule(
                inst_work,
                deadline=float(constructive_deadline),
                seed=int(resolved_options.random_seed or 0),
                max_starts=1,
                strategies=(constructive_strategy,),
                beam_width=8,
                bundle_limit=4,
            )
            research_adaptive_meta["constructive_initializer"] = (
                constructive_result.to_dict()
            )
            if constructive_result.schedule is not None:
                validated_profile_schedule = {
                    int(activity_id): dict(row)
                    for activity_id, row in constructive_result.schedule.items()
                }
                raw_status = int(cp_model.FEASIBLE)
                attempt = SolveAttempt(
                    room_mode="itc2007_course_constructive",
                    use_objective=False,
                    time_limit_seconds=float(constructive_budget),
                    raw_status=int(cp_model.FEASIBLE),
                    status_name="CONSTRUCTIVE_FEASIBLE",
                    proof_status="validated_constructive_incumbent",
                    budget_seconds=float(constructive_budget),
                    elapsed_seconds=float(constructive_result.elapsed_seconds),
                    model_build_seconds=0.0,
                    setup_seconds=float(constructive_result.elapsed_seconds),
                    deadline_safety_margin_seconds=float(constructive_reserve),
                    search_budget_seconds=float(constructive_budget),
                    search_seconds=0.0,
                    deadline_overrun_seconds=max(
                        0.0,
                        time.perf_counter() - float(constructive_deadline),
                    ),
                    budget_exhausted=bool(constructive_result.deadline_exhausted),
                )
                attempts.append(attempt)
                emit(
                    "research_constructive_initializer_done",
                    valid=True,
                    elapsed_seconds=float(constructive_result.elapsed_seconds),
                )
        if validated_profile_schedule is None:
            model, solver, raw_status, attempt = solve_attempt(
                room_mode,
                use_objective,
                first_options,
            )
        if research_adaptive_meta is not None:
            research_adaptive_meta["initial"] = _attempt_timing_meta(
                attempt,
                attempt_index=len(attempts),
            )
            initial_validation_errors: List[str] = []
            initial_validation_seconds = 0.0
            if _is_feasible(raw_status) and validated_profile_schedule is None:
                (
                    validated_profile_schedule,
                    initial_validation_errors,
                    initial_validation_seconds,
                ) = _extract_complete_validated_schedule(
                    inst_work,
                    model,
                    solver,
                )
            research_adaptive_meta.update(
                {
                    "initial_validation_attempted": bool(_is_feasible(raw_status)),
                    "initial_validation_seconds": float(initial_validation_seconds),
                    "initial_validation_error_count": int(
                        len(initial_validation_errors)
                    ),
                    "initial_valid": bool(validated_profile_schedule is not None),
                    "remaining_after_initial_seconds": total_remaining_seconds(),
                }
            )
            if initial_validation_errors:
                research_adaptive_meta["initial_validation_errors"] = list(
                    initial_validation_errors[:10]
                )

            if validated_profile_schedule is not None:
                research_adaptive_meta["status"] = "INITIAL_INCUMBENT_VALIDATED"
                research_adaptive_meta["returned_source"] = (
                    "constructive_initializer"
                    if constructive_result is not None
                    and constructive_result.schedule is not None
                    else "initial_incumbent"
                )
            else:
                # A nominally feasible but invalid extraction is not an incumbent.
                if _is_feasible(raw_status):
                    raw_status = int(cp_model.UNKNOWN)
                remaining_before_rescue = total_remaining_seconds()
                rescue_allocation = max(
                    0.0,
                    float(resolved_options.adaptive_lns_seconds),
                )
                rescue_finalization_reserve = finalization_reserve_seconds()
                rescue_budget_seconds = (
                    rescue_allocation
                    if remaining_before_rescue is None
                    else min(
                        rescue_allocation,
                        max(
                            0.0,
                            float(remaining_before_rescue)
                            - float(rescue_finalization_reserve),
                        ),
                    )
                )
                research_adaptive_meta.update(
                    {
                        "status": "RESCUE_PENDING",
                        "rescue_reason": "no_validated_initial_incumbent",
                        "rescue_objective": "none",
                        "rescue_room_mode": str(room_mode),
                        "rescue_remaining_at_start_seconds": remaining_before_rescue,
                        "finalization_reserve_seconds": float(
                            rescue_finalization_reserve
                        ),
                        "rescue_budget_seconds": float(rescue_budget_seconds),
                    }
                )
                if rescue_budget_seconds > 0 and enough_time_for_another_attempt(
                    room_mode
                ):
                    rescue_seed = _research_rescue_seed(resolved_options.random_seed)
                    research_adaptive_meta.update(
                        {
                            "rescue_attempted": True,
                            "rescue_seed": int(rescue_seed),
                            "rescue_seed_derivation": "base_seed_plus_one_mod_2147483646",
                        }
                    )
                    emit(
                        "research_feasibility_rescue_start",
                        limit_seconds=float(rescue_budget_seconds),
                        room_mode=str(room_mode),
                        random_seed=int(rescue_seed),
                    )
                    (
                        rescue_model,
                        rescue_solver,
                        rescue_status,
                        rescue_attempt,
                    ) = solve_attempt(
                        room_mode,
                        False,
                        replace(
                            full_options,
                            time_limit_seconds=float(rescue_budget_seconds),
                            random_seed=int(rescue_seed),
                            adaptive_lns_seconds=0.0,
                        ),
                    )
                    research_adaptive_meta["rescue"] = _attempt_timing_meta(
                        rescue_attempt,
                        attempt_index=len(attempts),
                    )
                    rescue_validation_errors: List[str] = []
                    rescue_validation_seconds = 0.0
                    rescue_schedule: Dict[int, Dict[str, Any]] = {}
                    if _is_feasible(rescue_status):
                        (
                            rescue_schedule,
                            rescue_validation_errors,
                            rescue_validation_seconds,
                        ) = _extract_complete_validated_schedule(
                            inst_work,
                            rescue_model,
                            rescue_solver,
                        )
                    research_adaptive_meta.update(
                        {
                            "rescue_validation_attempted": bool(
                                _is_feasible(rescue_status)
                            ),
                            "rescue_validation_seconds": float(
                                rescue_validation_seconds
                            ),
                            "rescue_validation_error_count": int(
                                len(rescue_validation_errors)
                            ),
                            "rescue_valid": bool(rescue_schedule),
                            "remaining_after_rescue_seconds": (
                                total_remaining_seconds()
                            ),
                        }
                    )
                    if rescue_validation_errors:
                        research_adaptive_meta["rescue_validation_errors"] = list(
                            rescue_validation_errors[:10]
                        )
                    model, solver = rescue_model, rescue_solver
                    if rescue_schedule:
                        validated_profile_schedule = rescue_schedule
                        raw_status = int(rescue_status)
                        research_adaptive_meta.update(
                            {
                                "status": "RESCUE_INCUMBENT_VALIDATED",
                                "returned_source": "rescue_incumbent",
                            }
                        )
                    else:
                        raw_status = (
                            int(rescue_status)
                            if not _is_feasible(rescue_status)
                            else int(cp_model.UNKNOWN)
                        )
                        research_adaptive_meta["status"] = (
                            "RESCUE_NO_VALIDATED_INCUMBENT"
                        )
                    emit(
                        "research_feasibility_rescue_done",
                        status=int(raw_status),
                        valid=bool(rescue_schedule),
                        elapsed_seconds=float(rescue_attempt.elapsed_seconds),
                    )
                else:
                    research_adaptive_meta["status"] = "RESCUE_NOT_STARTED"
                    research_adaptive_meta["rescue_skip_reason"] = (
                        "insufficient_remaining_budget"
                    )
        retry_limit = remaining_seconds(solve_deadline)
        if (
            resolved_options.retry_without_objective
            and use_objective
            and not _is_feasible(raw_status)
            and (retry_limit is None or retry_limit > 0)
            and enough_time_for_another_attempt(room_mode)
        ):
            model, solver, raw_status, attempt = solve_attempt(
                room_mode,
                False,
                replace(full_options, time_limit_seconds=retry_limit),
            )
        fallback_limit = remaining_seconds(solve_deadline)
        if (
            room_mode == "cp_rooms"
            and not _is_feasible(raw_status)
            and (fallback_limit is None or fallback_limit > 0)
            and enough_time_for_another_attempt("greedy")
        ):
            emit("solve_fallback", from_mode="cp_rooms", to_mode="greedy")
            model, solver, raw_status, attempt = solve_attempt(
                "greedy",
                False,
                replace(full_options, time_limit_seconds=fallback_limit),
            )

    ui_status = _map_status_to_ui(raw_status)
    if ui_status not in (0, 4):
        result = SolveResult(
            status=int(ui_status),
            raw_status=int(raw_status),
            schedule={},
            attempts=attempts,
            meta={
                "phased": bool(resolved_options.phased_solve),
                "objective_profile": dict(profile_meta),
                "incremental": dict(incremental_meta),
                "decomposition": dict(getattr(model, "decomposition_report", {}) or {}),
                "timing": total_timing_meta(),
                **profile_execution_meta(),
            },
        )
        if cache_key:
            _SOLVE_RESULT_CACHE[cache_key] = copy.deepcopy(result)
        return result

    try:
        schedule = (
            {
                int(activity_id): dict(info)
                for activity_id, info in validated_profile_schedule.items()
            }
            if validated_profile_schedule is not None
            else model.extract_solution(solver)
        )
    except GreedyRoomingError as exc:
        result = SolveResult(
            status=-2,
            raw_status=int(raw_status),
            schedule={},
            attempts=attempts,
            meta={
                "error": str(exc),
                "reason": getattr(exc, "reason", ""),
                "objective_profile": dict(profile_meta),
                "incremental": dict(incremental_meta),
                "decomposition": dict(getattr(model, "decomposition_report", {}) or {}),
                "timing": total_timing_meta(),
                **profile_execution_meta(),
            },
        )
        if cache_key:
            _SOLVE_RESULT_CACHE[cache_key] = copy.deepcopy(result)
        return result

    hard_conflicts: List[str] = []
    if resolved_options.enforce_hard_conflict_free:
        hard_conflicts = _hard_conflict_errors(inst_work, schedule)
        if hard_conflicts:
            result = SolveResult(
                status=-3,
                raw_status=int(raw_status),
                schedule={},
                attempts=attempts,
                hard_conflicts=hard_conflicts,
                meta={
                    "stage": "post_extract",
                    "objective_profile": dict(profile_meta),
                    "incremental": dict(incremental_meta),
                    "decomposition": dict(
                        getattr(model, "decomposition_report", {}) or {}
                    ),
                    "timing": total_timing_meta(),
                    **profile_execution_meta(),
                },
            )
            if cache_key:
                _SOLVE_RESULT_CACHE[cache_key] = copy.deepcopy(result)
            return result

    configured_improvement_seconds = max(
        0.0,
        float(resolved_options.improve_total_seconds),
    )
    remaining_for_improvement = total_remaining_seconds()
    improvement_stage_budget = (
        configured_improvement_seconds
        if remaining_for_improvement is None
        else min(configured_improvement_seconds, float(remaining_for_improvement))
    )
    improvement_meta: Dict[str, Any] | None = None
    if resolved_options.phased_solve and float(improvement_stage_budget) > 0:
        improvement_started = time.perf_counter()
        improvement_budget_seconds = max(0.0, float(improvement_stage_budget))
        deadline = float(improvement_started) + float(improvement_budget_seconds)
        emit(
            "improve_start",
            total_seconds=float(resolved_options.improve_total_seconds),
            max_rounds=int(resolved_options.improve_max_rounds),
            iters_per_slice=int(resolved_options.improve_iters_per_slice),
        )
        improver_setup_started = time.perf_counter()
        try:
            improver = LocalSearchImprover(
                inst_work,
                random_seed=resolved_options.random_seed,
            )
        except TypeError:
            # Compatibility for injected/test improvers that implement the
            # historical one-argument constructor.
            if resolved_options.random_seed is not None:
                random.seed(int(resolved_options.random_seed))
            improver = LocalSearchImprover(inst_work)
        best_schedule = {int(a_id): dict(info) for a_id, info in schedule.items()}
        start_penalty = int(improver.compute_soft_penalty(best_schedule))
        best_penalty = int(start_penalty)
        improver_setup_seconds = float(time.perf_counter() - improver_setup_started)
        rounds: List[Dict[str, Any]] = []

        for round_idx in range(1, int(resolved_options.improve_max_rounds) + 1):
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            deadline_safety_margin_seconds = min(
                0.10,
                max(0.005, float(remaining) * 0.05),
            )
            slice_budget = min(
                float(resolved_options.improve_slice_seconds),
                max(0.0, float(remaining) - deadline_safety_margin_seconds),
            )
            if slice_budget <= 0:
                break
            candidate = improver.improve(
                best_schedule,
                iterations=int(resolved_options.improve_iters_per_slice),
                max_seconds=float(slice_budget),
            )
            candidate_penalty = int(improver.compute_soft_penalty(candidate))
            candidate_hard_errors: List[str] = []
            if resolved_options.enforce_hard_conflict_free:
                candidate_hard_errors = _hard_conflict_errors(inst_work, candidate)
            accepted = (not candidate_hard_errors) and int(candidate_penalty) <= int(
                best_penalty
            )
            if accepted:
                best_schedule = {
                    int(a_id): dict(info) for a_id, info in candidate.items()
                }
                best_penalty = int(candidate_penalty)
            rounds.append(
                {
                    "round": int(round_idx),
                    "slice_seconds": float(slice_budget),
                    "deadline_safety_margin_seconds": float(
                        deadline_safety_margin_seconds
                    ),
                    "candidate_penalty": int(candidate_penalty),
                    "hard_conflicts": int(len(candidate_hard_errors)),
                    "accepted": bool(accepted),
                    "best_penalty": int(best_penalty),
                }
            )
            emit(
                "improve_round",
                round=int(round_idx),
                max_rounds=int(resolved_options.improve_max_rounds),
                candidate_penalty=int(candidate_penalty),
                best_penalty=int(best_penalty),
                accepted=bool(accepted),
                elapsed_seconds=float(time.perf_counter() - improvement_started),
                total_seconds=float(resolved_options.improve_total_seconds),
            )

        schedule = best_schedule
        improvement_elapsed_seconds = float(time.perf_counter() - improvement_started)
        improvement_meta = {
            "enabled": True,
            "start_penalty": int(start_penalty),
            "final_penalty": int(best_penalty),
            "rounds": rounds,
            "budget_seconds": float(improvement_budget_seconds),
            "setup_seconds": float(improver_setup_seconds),
            "elapsed_seconds": float(improvement_elapsed_seconds),
            "deadline_overrun_seconds": max(
                0.0,
                improvement_elapsed_seconds - float(improvement_budget_seconds),
            ),
            "termination_reason": (
                "TIME_LIMIT"
                if time.perf_counter() >= float(deadline)
                and len(rounds) < int(resolved_options.improve_max_rounds)
                else "MAX_ROUNDS"
            ),
        }
        emit(
            "improve_done",
            rounds_completed=int(len(rounds)),
            final_penalty=int(best_penalty),
            elapsed_seconds=float(improvement_elapsed_seconds),
        )

    adaptive_lns_meta: Dict[str, Any] | None = None
    if float(resolved_options.adaptive_lns_seconds) > 0 or bool(
        resolved_options.fixed_time_room_dive
    ):
        remaining_for_adaptive = total_remaining_seconds()
        adaptive_finalization_reserve = finalization_reserve_seconds()
        adaptive_completion_reserve = (
            completion_reserve_seconds()
            if bool(resolved_options.fixed_time_room_dive)
            else 0.0
        )
        adaptive_request_seconds = float(resolved_options.adaptive_lns_seconds)
        if (
            bool(resolved_options.projected_time_search)
            and remaining_for_adaptive is not None
        ):
            adaptive_request_seconds = max(
                float(adaptive_request_seconds),
                max(
                    0.0,
                    float(remaining_for_adaptive)
                    - float(adaptive_finalization_reserve)
                    - float(adaptive_completion_reserve),
                ),
            )
        adaptive_budget_seconds = _budget_after_reserves(
            float(adaptive_request_seconds),
            remaining_for_adaptive,
            adaptive_finalization_reserve,
            adaptive_completion_reserve,
        )
        if research_adaptive_meta is not None:
            research_adaptive_meta.update(
                {
                    "adaptive_remaining_at_start_seconds": remaining_for_adaptive,
                    "finalization_reserve_seconds": float(
                        adaptive_finalization_reserve
                    ),
                    "completion_reserve_seconds": float(adaptive_completion_reserve),
                    "total_reserved_after_adaptive_seconds": float(
                        adaptive_finalization_reserve + adaptive_completion_reserve
                    ),
                    "adaptive_budget_seconds_granted": float(adaptive_budget_seconds),
                    "adaptive_started": bool(adaptive_budget_seconds > 0),
                }
            )
        schedule, adaptive_lns_meta = _run_adaptive_lns(
            inst_work,
            schedule,
            replace(
                resolved_options,
                adaptive_lns_seconds=float(adaptive_budget_seconds),
            ),
            decomposition_report=dict(getattr(model, "decomposition_report", {}) or {}),
            progress_hook=(
                (lambda event, payload: emit(event, **payload))
                if progress_hook is not None
                else None
            ),
            fixed_time_room_dive_enabled=bool(resolved_options.fixed_time_room_dive),
            fixed_time_room_dive_budget_seconds=(
                float(adaptive_finalization_reserve)
                if bool(resolved_options.fixed_time_room_dive)
                else 0.0
            ),
            fixed_time_room_dive_completion_reserve_seconds=float(
                adaptive_completion_reserve
            ),
            fixed_time_room_strategy=str(resolved_options.fixed_time_room_strategy),
            initial_source=(
                None
                if research_adaptive_meta is None
                else str(research_adaptive_meta.get("returned_source") or "")
            ),
            final_deadline=total_deadline,
        )
        if research_adaptive_meta is not None:
            room_dive_meta = dict(
                (adaptive_lns_meta or {}).get("fixed_time_room_dive") or {}
            )
            adaptive_source = str(
                (adaptive_lns_meta or {}).get("returned_source") or ""
            )
            research_adaptive_meta.update(
                {
                    "adaptive_remaining_after_seconds": total_remaining_seconds(),
                    "adaptive_status": str(
                        (adaptive_lns_meta or {}).get("status", "NOT_STARTED")
                    ),
                    "fixed_time_room_dive_status": str(
                        room_dive_meta.get("status", "DISABLED")
                    ),
                }
            )
            if adaptive_source:
                research_adaptive_meta["returned_source"] = adaptive_source
            room_dive_source = str(room_dive_meta.get("returned_source", ""))
            if room_dive_source in {
                "fixed_time_room_dive",
                "fixed_time_room_oracle",
            }:
                research_adaptive_meta["returned_source"] = room_dive_source

    quality_meta = _build_quality_meta(
        inst_work,
        schedule,
        hard_conflicts=len(hard_conflicts),
        base_schedule=resolved_options.base_schedule,
    )
    meta: Dict[str, Any] = {
        "phased": bool(resolved_options.phased_solve),
        "objective_profile": dict(profile_meta),
        "incremental": dict(incremental_meta),
        "quality": quality_meta,
        "decomposition": dict(getattr(model, "decomposition_report", {}) or {}),
        "timing": total_timing_meta(),
        **profile_execution_meta(),
    }
    if improvement_meta is not None:
        meta["improvement"] = dict(improvement_meta)
    if adaptive_lns_meta is not None:
        meta["adaptive_lns"] = dict(adaptive_lns_meta)

    result = SolveResult(
        status=int(ui_status),
        raw_status=int(raw_status),
        schedule=schedule,
        attempts=attempts,
        hard_conflicts=hard_conflicts,
        meta=meta,
    )
    if cache_key:
        _SOLVE_RESULT_CACHE[cache_key] = copy.deepcopy(result)
    return result


def build_portfolio_solve_options(
    base_options: SolveOptions,
) -> List[Tuple[str, SolveOptions]]:
    profiles = ["fast_feasible", "balanced", "quality_first"]
    out: List[Tuple[str, SolveOptions]] = []
    for profile in profiles:
        out.append(
            (
                profile,
                replace(
                    base_options,
                    objective_profile=str(profile),
                ),
            )
        )
    return out


def solve_portfolio(
    inst,
    options: SolveOptions,
    *,
    progress_hook: Callable[[str, Dict[str, Any]], None] | None = None,
) -> PortfolioResult:
    base_options = replace(options)
    profile_options = list(build_portfolio_solve_options(base_options))
    total = len(profile_options)
    progress_lock = Lock()

    def _emit(event: str, payload: Dict[str, Any]) -> None:
        if progress_hook is not None:
            with progress_lock:
                progress_hook(str(event), dict(payload))

    def _run_candidate(
        idx: int, profile_id: str, candidate_options: SolveOptions
    ) -> tuple[int, PortfolioCandidate]:
        _emit(
            "portfolio_candidate_start",
            {"index": int(idx), "total": int(total), "profile": str(profile_id)},
        )
        candidate_inst = copy.deepcopy(inst)
        result = solve_instance(
            candidate_inst,
            candidate_options,
            progress_hook=lambda event, payload: _emit(
                event,
                {
                    **dict(payload or {}),
                    "portfolio_index": int(idx),
                    "portfolio_profile": str(profile_id),
                },
            ),
        )
        soft_penalty = None
        if result.is_feasible and result.schedule:
            quality = dict((result.meta or {}).get("quality") or {})
            soft_penalty = int(
                quality.get(
                    "soft_penalty",
                    compute_penalty_breakdown(candidate_inst, result.schedule).get(
                        "total", 0
                    ),
                )
            )
        candidate = PortfolioCandidate(
            name=str(profile_id),
            options=candidate_options,
            result=result,
            soft_penalty=soft_penalty,
        )
        _emit(
            "portfolio_candidate_done",
            {
                "index": int(idx),
                "total": int(total),
                "profile": str(profile_id),
                "status": int(result.status),
                "soft_penalty": soft_penalty,
            },
        )
        return int(idx - 1), candidate

    candidates: List[PortfolioCandidate | None] = [None] * total
    parallel_enabled = str(
        os.getenv("PLANORA_PORTFOLIO_PARALLEL", "1")
    ).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    if parallel_enabled and total > 1:
        max_workers = min(
            total, max(1, int(getattr(options, "portfolio_workers", 0) or 3))
        )
        portfolio_backend = (
            str(os.getenv("PLANORA_PORTFOLIO_BACKEND", "process")).strip().lower()
        )
        process_safe = getattr(solve_instance, "__module__", __name__) == __name__
        if portfolio_backend in {"process", "processes", "subprocess"} and process_safe:
            try:
                with ProcessPoolExecutor(max_workers=max_workers) as executor:
                    futures = []
                    for idx, (profile_id, candidate_options) in enumerate(
                        profile_options, start=1
                    ):
                        adjusted_options = replace(
                            candidate_options,
                            workers=max(
                                1,
                                int(candidate_options.workers or max_workers)
                                // int(max_workers),
                            ),
                        )
                        _emit(
                            "portfolio_candidate_start",
                            {
                                "index": int(idx),
                                "total": int(total),
                                "profile": str(profile_id),
                            },
                        )
                        futures.append(
                            executor.submit(
                                _solve_portfolio_candidate_process,
                                idx,
                                str(profile_id),
                                inst,
                                adjusted_options,
                            )
                        )
                    for future in as_completed(futures):
                        slot, profile_id, candidate_options, result, soft_penalty = (
                            future.result()
                        )
                        candidate = PortfolioCandidate(
                            name=str(profile_id),
                            options=candidate_options,
                            result=result,
                            soft_penalty=soft_penalty,
                        )
                        candidates[int(slot)] = candidate
                        _emit(
                            "portfolio_candidate_done",
                            {
                                "index": int(slot) + 1,
                                "total": int(total),
                                "profile": str(profile_id),
                                "status": int(result.status),
                                "soft_penalty": soft_penalty,
                                "backend": "process",
                            },
                        )
            except Exception as exc:
                _emit(
                    "portfolio_backend_fallback",
                    {"backend": "thread", "reason": str(exc)},
                )
                candidates = [None] * total
        if any(candidate is None for candidate in candidates):
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(
                        _run_candidate,
                        idx,
                        str(profile_id),
                        replace(
                            candidate_options,
                            workers=max(
                                1,
                                int(candidate_options.workers or max_workers)
                                // int(max_workers),
                            ),
                        ),
                    )
                    for idx, (profile_id, candidate_options) in enumerate(
                        profile_options, start=1
                    )
                ]
                for future in as_completed(futures):
                    slot, candidate = future.result()
                    candidates[int(slot)] = candidate
    else:
        for idx, (profile_id, candidate_options) in enumerate(profile_options, start=1):
            slot, candidate = _run_candidate(idx, str(profile_id), candidate_options)
            candidates[int(slot)] = candidate

    ordered_candidates: List[PortfolioCandidate] = [
        candidate for candidate in candidates if candidate is not None
    ]
    if len(ordered_candidates) != total:
        raise RuntimeError("Portfolio solve finished with missing candidate results.")

    feasible = [
        (idx, candidate)
        for idx, candidate in enumerate(ordered_candidates)
        if candidate.result.is_feasible and candidate.result.schedule
    ]
    if feasible:
        feasible.sort(
            key=lambda pair: (
                int(
                    pair[1].soft_penalty if pair[1].soft_penalty is not None else 10**9
                ),
                len(pair[1].result.hard_conflicts or []),
                len(pair[1].result.attempts or []),
            )
        )
        best_index = int(feasible[0][0])
        best_candidate = ordered_candidates[best_index]
        for idx, candidate in enumerate(ordered_candidates):
            if (
                idx == best_index
                or not candidate.result.is_feasible
                or not candidate.result.schedule
            ):
                continue
            candidate.rank_explanation = explain_solution_ranking(
                inst,
                best_candidate.result.schedule,
                candidate.result.schedule,
                base_label=str(best_candidate.name),
                candidate_label=str(candidate.name),
            )
        if best_candidate.result.schedule:
            best_candidate.rank_explanation = (
                f"{best_candidate.name} ranked first with soft penalty "
                f"{int(best_candidate.soft_penalty or 0)}."
            )
    else:
        best_index = -1

    return PortfolioResult(candidates=ordered_candidates, best_index=int(best_index))


def improve_schedule(
    inst,
    schedule: Dict[int, Dict[str, Any]],
    options: ImproveOptions,
    *,
    progress_hook: Callable[..., None] | None = None,
    stop_hook: Callable[[], bool] | None = None,
) -> Dict[int, Dict[str, Any]]:
    improver = LocalSearchImprover(inst)
    improved = improver.improve(
        schedule,
        iterations=int(options.iterations),
        start_temp=float(options.start_temp),
        end_temp=float(options.end_temp),
        max_seconds=options.max_seconds,
        progress_every=int(options.progress_every),
        progress_hook=progress_hook,
        stop_hook=stop_hook,
        restart_after=options.restart_after,
        max_restarts=options.max_restarts,
        kick_steps=options.kick_steps,
        probe_activities=options.probe_activities,
    )
    conflicts = _hard_conflict_errors(inst, improved)
    if conflicts:
        return {int(a_id): dict(info) for a_id, info in schedule.items()}
    return improved
