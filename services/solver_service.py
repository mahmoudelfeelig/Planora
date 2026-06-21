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

from core.metaheuristics import LocalSearchImprover
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
from utils.disruption import build_freeze_locks
from utils.generator import instance_to_json
from utils.specs import validate_schedule_against_instance

_SOLVE_RESULT_CACHE: Dict[str, SolveResult] = {}


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
                compute_penalty_breakdown(candidate_inst, result.schedule).get("total", 0),
            )
        )
    return int(idx - 1), str(profile_id), candidate_options, result, soft_penalty

OBJECTIVE_PROFILE_PRESETS: Dict[str, Dict[str, Any]] = {
    "university_fast": {
        "label": "University fast",
        "use_objective": False,
        "retry_without_objective": False,
        "phased_solve": False,
        "room_mode": "greedy",
        "improve_total_seconds": 0.0,
    },
    "university_quality": {
        "label": "University quality",
        "use_objective": True,
        "retry_without_objective": True,
        "phased_solve": True,
        "room_mode": "greedy",
    },
    "verification": {
        "label": "Verification",
        "use_objective": True,
        "retry_without_objective": True,
        "phased_solve": False,
        "room_mode": "cp_rooms",
    },
    "fast_feasible": {
        "label": "Fast feasible",
        "use_objective": False,
        "retry_without_objective": False,
        "phased_solve": False,
        "improve_total_seconds": 0.0,
    },
    "balanced": {
        "label": "Balanced",
        "use_objective": True,
        "retry_without_objective": True,
        "phased_solve": True,
    },
    "quality_first": {
        "label": "Quality-first",
        "use_objective": True,
        "retry_without_objective": True,
        "phased_solve": True,
        "improve_slice_seconds": 6.0,
        "improve_iters_per_slice": 1500,
        "improve_max_rounds": 16,
    },
}


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


def _objective_bound_info(solver: Any, raw_status: int, *, use_objective: bool) -> Dict[str, float | None]:
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
    affected = {int(a_id) for a_id in affected_activity_ids if int(a_id) in base_schedule}
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
                impacted_groups.update(int(g) for g in (info.get("group_ids", []) or []))
                if room_id is not None:
                    impacted_rooms.add(int(room_id))
                changed = True
    return sorted(expanded)


def _apply_incremental_scope(inst, options: SolveOptions) -> tuple[Any, SolveOptions, Dict[str, Any]]:
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
        "requested_activities": sorted(int(a) for a in (options.affected_activity_ids or [])),
        "expanded_activities": list(expanded_scope),
        "frozen_activities": int(len(merged_locks)),
    }
    return inst_work, options, meta


def _apply_objective_profile(inst, options: SolveOptions) -> tuple[Any, SolveOptions, Dict[str, Any]]:
    inst_work = copy.deepcopy(inst)
    profile = _canonical_profile_name(
        options.objective_profile or getattr(inst_work, "objective_profile", "balanced")
    )
    inst_work.objective_profile = str(profile)
    preset = dict(OBJECTIVE_PROFILE_PRESETS.get(profile, OBJECTIVE_PROFILE_PRESETS["balanced"]))

    resolved = options
    if profile == "university_fast":
        resolved = replace(
            resolved,
            room_mode="greedy",
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
            improve_total_seconds = min(float(improve_total_seconds), max(0.0, total_limit - float(feasibility_seconds)))
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

    return inst_work, resolved, {
        "id": str(profile),
        "label": str(preset.get("label", profile)),
    }


def _solve_cache_key(inst, options: SolveOptions) -> str:
    payload = {
        "instance": instance_to_json(inst),
        "hard_constraints": dict(getattr(inst, "hard_constraints", {}) or {}),
        "soft_weights": dict(getattr(inst, "soft_weights", {}) or {}),
        "objective_profile": str(getattr(inst, "objective_profile", "balanced") or "balanced"),
        "options": dict(options.__dict__),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _run_solve_attempt(
    inst,
    *,
    room_mode: str,
    use_objective: bool,
    options: SolveOptions,
) -> tuple[TimetableSolver, Any, int, SolveAttempt]:
    model = TimetableSolver(inst, room_mode=str(room_mode), use_objective=bool(use_objective))
    solver, raw_status = model.solve(
        time_limit_seconds=options.time_limit_seconds,
        workers=options.workers,
        random_seed=options.random_seed,
        log_progress=options.log_progress,
    )
    objective_info = _objective_bound_info(
        solver,
        int(raw_status),
        use_objective=bool(use_objective),
    )
    attempt = SolveAttempt(
        room_mode=str(room_mode),
        use_objective=bool(use_objective),
        time_limit_seconds=options.time_limit_seconds,
        raw_status=int(raw_status),
        objective_value=objective_info["objective_value"],
        best_objective_bound=objective_info["best_objective_bound"],
        relative_gap=objective_info["relative_gap"],
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
    if isinstance(base_schedule, dict) and base_schedule:
        quality["comparison_to_base"] = explain_solution_ranking(
            inst,
            base_schedule,
            schedule,
            base_label="base",
            candidate_label="current",
        )
    return quality


def solve_instance(
    inst,
    options: SolveOptions,
    *,
    progress_hook: Callable[[str, Dict[str, Any]], None] | None = None,
) -> SolveResult:
    inst_profiled, resolved_options, profile_meta = _apply_objective_profile(inst, options)
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
            return cached

    attempts: List[SolveAttempt] = []

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

    emit(
        "run_start",
        room_mode=room_mode,
        use_objective=use_objective,
        phased=bool(resolved_options.phased_solve),
        objective_profile=dict(profile_meta),
        incremental=dict(incremental_meta),
    )

    def solve_attempt(mode: str, objective: bool, run_options: SolveOptions):
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

    if resolved_options.phased_solve:
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
        model, solver, raw_status, attempt = solve_attempt(room_mode, False, phased_options)
        fallback_limit = remaining_seconds(feasibility_deadline)
        if room_mode == "cp_rooms" and not _is_feasible(raw_status) and (fallback_limit is None or fallback_limit > 0):
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
        model, solver, raw_status, attempt = solve_attempt(
            room_mode,
            use_objective,
            first_options,
        )
        retry_limit = remaining_seconds(solve_deadline)
        if (
            resolved_options.retry_without_objective
            and use_objective
            and not _is_feasible(raw_status)
            and (retry_limit is None or retry_limit > 0)
        ):
            model, solver, raw_status, attempt = solve_attempt(
                room_mode,
                False,
                replace(full_options, time_limit_seconds=retry_limit),
            )
        fallback_limit = remaining_seconds(solve_deadline)
        if room_mode == "cp_rooms" and not _is_feasible(raw_status) and (fallback_limit is None or fallback_limit > 0):
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
            },
        )
        if cache_key:
            _SOLVE_RESULT_CACHE[cache_key] = copy.deepcopy(result)
        return result

    try:
        schedule = model.extract_solution(solver)
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
                },
            )
            if cache_key:
                _SOLVE_RESULT_CACHE[cache_key] = copy.deepcopy(result)
            return result

    improvement_meta: Dict[str, Any] | None = None
    if resolved_options.phased_solve and float(resolved_options.improve_total_seconds) > 0:
        emit(
            "improve_start",
            total_seconds=float(resolved_options.improve_total_seconds),
            max_rounds=int(resolved_options.improve_max_rounds),
            iters_per_slice=int(resolved_options.improve_iters_per_slice),
        )
        improver = LocalSearchImprover(inst_work)
        if resolved_options.random_seed is not None:
            random.seed(int(resolved_options.random_seed))
        best_schedule = {int(a_id): dict(info) for a_id, info in schedule.items()}
        start_penalty = int(improver.compute_soft_penalty(best_schedule))
        best_penalty = int(start_penalty)
        start_ts = time.perf_counter()
        deadline = start_ts + float(resolved_options.improve_total_seconds)
        rounds: List[Dict[str, Any]] = []

        for round_idx in range(1, int(resolved_options.improve_max_rounds) + 1):
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            slice_budget = min(float(resolved_options.improve_slice_seconds), float(remaining))
            candidate = improver.improve(
                best_schedule,
                iterations=int(resolved_options.improve_iters_per_slice),
                max_seconds=float(slice_budget),
            )
            candidate_penalty = int(improver.compute_soft_penalty(candidate))
            candidate_hard_errors: List[str] = []
            if resolved_options.enforce_hard_conflict_free:
                candidate_hard_errors = _hard_conflict_errors(inst_work, candidate)
            accepted = (not candidate_hard_errors) and int(candidate_penalty) <= int(best_penalty)
            if accepted:
                best_schedule = {int(a_id): dict(info) for a_id, info in candidate.items()}
                best_penalty = int(candidate_penalty)
            rounds.append(
                {
                    "round": int(round_idx),
                    "slice_seconds": float(slice_budget),
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
                elapsed_seconds=float(time.perf_counter() - start_ts),
                total_seconds=float(resolved_options.improve_total_seconds),
            )

        schedule = best_schedule
        improvement_meta = {
            "enabled": True,
            "start_penalty": int(start_penalty),
            "final_penalty": int(best_penalty),
            "rounds": rounds,
            "elapsed_seconds": float(time.perf_counter() - start_ts),
        }
        emit(
            "improve_done",
            rounds_completed=int(len(rounds)),
            final_penalty=int(best_penalty),
            elapsed_seconds=float(time.perf_counter() - start_ts),
        )

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
    }
    if improvement_meta is not None:
        meta["improvement"] = dict(improvement_meta)

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


def build_portfolio_solve_options(base_options: SolveOptions) -> List[Tuple[str, SolveOptions]]:
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

    def _run_candidate(idx: int, profile_id: str, candidate_options: SolveOptions) -> tuple[int, PortfolioCandidate]:
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
                    compute_penalty_breakdown(candidate_inst, result.schedule).get("total", 0),
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
    parallel_enabled = str(os.getenv("PLANORA_PORTFOLIO_PARALLEL", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    if parallel_enabled and total > 1:
        max_workers = min(total, max(1, int(getattr(options, "portfolio_workers", 0) or 3)))
        portfolio_backend = str(os.getenv("PLANORA_PORTFOLIO_BACKEND", "process")).strip().lower()
        process_safe = getattr(solve_instance, "__module__", __name__) == __name__
        if portfolio_backend in {"process", "processes", "subprocess"} and process_safe:
            try:
                with ProcessPoolExecutor(max_workers=max_workers) as executor:
                    futures = []
                    for idx, (profile_id, candidate_options) in enumerate(profile_options, start=1):
                        adjusted_options = replace(
                            candidate_options,
                            workers=max(
                                1,
                                int(candidate_options.workers or max_workers) // int(max_workers),
                            ),
                        )
                        _emit(
                            "portfolio_candidate_start",
                            {"index": int(idx), "total": int(total), "profile": str(profile_id)},
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
                        slot, profile_id, candidate_options, result, soft_penalty = future.result()
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
                _emit("portfolio_backend_fallback", {"backend": "thread", "reason": str(exc)})
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
                                int(candidate_options.workers or max_workers) // int(max_workers),
                            ),
                        ),
                    )
                    for idx, (profile_id, candidate_options) in enumerate(profile_options, start=1)
                ]
                for future in as_completed(futures):
                    slot, candidate = future.result()
                    candidates[int(slot)] = candidate
    else:
        for idx, (profile_id, candidate_options) in enumerate(profile_options, start=1):
            slot, candidate = _run_candidate(idx, str(profile_id), candidate_options)
            candidates[int(slot)] = candidate

    ordered_candidates: List[PortfolioCandidate] = [
        candidate
        for candidate in candidates
        if candidate is not None
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
                int(pair[1].soft_penalty if pair[1].soft_penalty is not None else 10**9),
                len(pair[1].result.hard_conflicts or []),
                len(pair[1].result.attempts or []),
            )
        )
        best_index = int(feasible[0][0])
        best_candidate = ordered_candidates[best_index]
        for idx, candidate in enumerate(ordered_candidates):
            if idx == best_index or not candidate.result.is_feasible or not candidate.result.schedule:
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
    progress_hook: Callable[[int, int, int], None] | None = None,
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
