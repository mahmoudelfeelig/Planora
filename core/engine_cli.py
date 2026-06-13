from __future__ import annotations

import sys
import os
import pickle
import time
import json
import traceback
from typing import Dict, Any

from core.solver_cp_sat import TimetableSolver, GreedyRoomingError
from core.metaheuristics import LocalSearchImprover
from services.quality_service import compute_penalty_breakdown, evaluate_schedule_sla
from utils.specs import validate_schedule_against_instance


def _map_status_to_ui(status: int) -> int:
    """
    The UI expects 0 for FEASIBLE and 4 for OPTIMAL.
    OR-Tools uses enum ints; we translate to the UI's convention.
    Unknown/other statuses are passed through unchanged so failures surface clearly,
    but UNKNOWN (0) is remapped to a non-feasible sentinel to avoid looking like FEASIBLE.
    """
    try:
        # Lazy import to avoid hard dependency here
        from ortools.sat.python import cp_model
        if status == cp_model.UNKNOWN:
            return -1  # prevent UNKNOWN from being mistaken for FEASIBLE (0)
        if status == cp_model.OPTIMAL:
            return 4
        if status == cp_model.FEASIBLE:
            return 0
    except Exception:
        # If OR-Tools constants aren't available for some reason,
        # keep the raw status so the UI will reject non-(0,4).
        pass
    if status == 0:
        return -1  # keep UNKNOWN distinct from UI's FEASIBLE code
    return status


def _read_int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    value = int(raw)
    if value < 1:
        raise ValueError(f"{name} must be >= 1, got {value}")
    return value


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("", "0", "false", "no")


def _read_float_env(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    value = float(raw)
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")
    return value


def _hard_conflict_errors(inst, schedule: Dict[int, Dict[str, Any]]) -> list[str]:
    return validate_schedule_against_instance(
        inst,
        schedule,
        strict_rooms=True,
        require_all_activities=False,
    )


def _normalize_objective_profile(raw: str | None) -> str:
    text = str(raw or "balanced").strip().lower().replace("-", "_").replace(" ", "_")
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
    return aliases.get(text, "balanced")


def _profile_budget_split(
    *,
    profile: str,
    time_limit: float | None,
    feasibility_seconds: float | None,
    improve_total_seconds: float,
) -> tuple[float | None, float]:
    if time_limit is None or float(time_limit) <= 0:
        return feasibility_seconds, float(improve_total_seconds)

    total_limit = max(0.0, float(time_limit))
    if str(profile) == "quality_first":
        feasibility = (
            float(feasibility_seconds)
            if feasibility_seconds is not None
            else min(total_limit, max(1.0, total_limit * 0.65))
        )
    else:
        feasibility = (
            float(feasibility_seconds)
            if feasibility_seconds is not None
            else min(total_limit, max(1.0, total_limit * 0.75))
        )
    feasibility = min(float(feasibility), total_limit)
    improve = (
        float(improve_total_seconds)
        if float(improve_total_seconds) > 0
        else max(0.0, total_limit - float(feasibility))
    )
    improve = min(float(improve), max(0.0, total_limit - float(feasibility)))
    return float(feasibility), float(improve)


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "Usage: engine_cli.py <instance_pickle_path> <result_pickle_path>",
            file=sys.stderr,
        )
        return 2

    in_path = sys.argv[1]
    out_path = sys.argv[2]

    # Read the pickled Instance produced by the UI
    try:
        with open(in_path, "rb") as f:
            inst = pickle.load(f)
    except Exception as e:
        print(f"[error] failed to read instance pickle: {e}", file=sys.stderr)
        traceback.print_exc()
        return 2

    # Build and solve the CP model
    try:
        def _emit_progress(event: str, **payload: object) -> None:
            msg = {"event": str(event)}
            msg.update(payload)
            print(f"[progress] {json.dumps(msg, separators=(',', ':'))}", flush=True)

        room_mode = os.getenv("TT_ROOM_MODE", "cp_rooms")
        objective_profile = _normalize_objective_profile(
            os.getenv("TT_OBJECTIVE_PROFILE", "balanced")
        )
        use_objective_env = os.getenv("TT_USE_OBJECTIVE", "1").strip()
        use_objective = use_objective_env not in ("0", "false", "False", "no")
        retry_without_objective = _read_bool_env("TT_RETRY_NO_OBJECTIVE", True)
        phased_solve = _read_bool_env("TT_PHASED_SOLVE", False)
        enforce_hard_conflict_free = _read_bool_env("TT_ENFORCE_HARD_CONFLICT_FREE", True)
        log_progress_env = os.getenv("TT_CP_LOG", "").strip().lower()
        log_progress = log_progress_env not in ("", "0", "false", "no")
        workers = _read_int_env("TT_CP_WORKERS")
        attempts: list[dict[str, object]] = []
        meta: dict[str, object] = {
            "attempts": attempts,
            "enforce_hard_conflict_free": bool(enforce_hard_conflict_free),
            "objective_profile": str(objective_profile),
        }

        from ortools.sat.python import cp_model

        def _is_feasible(raw_status: int) -> bool:
            return raw_status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

        def _objective_bound_info(solver: cp_model.CpSolver, raw_status: int, *, objective: bool) -> dict[str, float | None]:
            if not bool(objective):
                return {
                    "objective_value": None,
                    "best_objective_bound": None,
                    "relative_gap": None,
                }
            objective_value = None
            best_bound = None
            if _is_feasible(int(raw_status)):
                try:
                    objective_value = float(solver.ObjectiveValue())
                except Exception:
                    objective_value = None
            try:
                best_bound = float(solver.BestObjectiveBound())
            except Exception:
                best_bound = None
            relative_gap = None
            if objective_value is not None and best_bound is not None:
                denom = max(1.0, abs(float(objective_value)))
                relative_gap = max(0.0, float(objective_value) - float(best_bound)) / denom
            return {
                "objective_value": objective_value,
                "best_objective_bound": best_bound,
                "relative_gap": relative_gap,
            }

        def _solve_attempt(mode: str, objective: bool, limit: float | None):
            nonlocal attempts
            attempt_idx = len(attempts) + 1
            _emit_progress(
                "solve_attempt_start",
                attempt=attempt_idx,
                mode=str(mode),
                objective=bool(objective),
                limit_seconds=(float(limit) if limit is not None else None),
            )
            model = TimetableSolver(inst, room_mode=mode, use_objective=objective)
            t0 = time.perf_counter()
            sat_solver, sat_status = model.solve(
                time_limit_seconds=limit,
                workers=workers,
                log_progress=log_progress,
            )
            elapsed = time.perf_counter() - t0
            objective_info = _objective_bound_info(
                sat_solver,
                int(sat_status),
                objective=bool(objective),
            )
            attempts.append(
                {
                    "room_mode": mode,
                    "use_objective": objective,
                    "time_limit_seconds": limit,
                    "status": int(sat_status),
                    "raw_status": int(sat_status),
                    "elapsed_seconds": float(elapsed),
                    "workers": int(workers) if workers is not None else None,
                    "objective_value": objective_info["objective_value"],
                    "best_objective_bound": objective_info["best_objective_bound"],
                    "relative_gap": objective_info["relative_gap"],
                }
            )
            _emit_progress(
                "solve_attempt_done",
                attempt=attempt_idx,
                mode=str(mode),
                objective=bool(objective),
                status=int(sat_status),
                elapsed_seconds=float(elapsed),
            )
            return model, sat_solver, sat_status

        def _remaining(deadline: float | None) -> float | None:
            if deadline is None:
                return None
            return max(0.0, float(deadline) - time.perf_counter())

        # Optional time limit via env var (seconds). Keep defaults if unset.
        tl = os.getenv("TT_TIME_LIMIT")
        strict_tl = os.getenv("TT_STRICT_TIME_LIMIT")
        time_limit = float(tl) if tl else None
        strict_limit = float(strict_tl) if strict_tl else (min(time_limit, 30.0) if time_limit else 30.0)
        feasibility_seconds = _read_float_env("TT_FEASIBILITY_SECONDS")

        improve_total_seconds = _read_float_env("TT_IMPROVE_TOTAL_SECONDS") or 0.0
        improve_slice_seconds = _read_float_env("TT_IMPROVE_SLICE_SECONDS")
        if improve_slice_seconds is None or improve_slice_seconds <= 0:
            improve_slice_seconds = 5.0
        improve_iters_per_slice = _read_int_env("TT_IMPROVE_ITERS_PER_SLICE")
        if improve_iters_per_slice is None:
            improve_iters_per_slice = 1200
        improve_max_rounds = _read_int_env("TT_IMPROVE_MAX_ROUNDS")
        if improve_max_rounds is None:
            improve_max_rounds = 12
        if objective_profile == "university_fast":
            room_mode = "greedy"
            use_objective = False
            retry_without_objective = False
            phased_solve = False
            improve_total_seconds = 0.0
        elif objective_profile == "university_quality":
            room_mode = "greedy"
            use_objective = True
            retry_without_objective = True
            phased_solve = True
            feasibility_seconds, improve_total_seconds = _profile_budget_split(
                profile="balanced",
                time_limit=time_limit,
                feasibility_seconds=feasibility_seconds,
                improve_total_seconds=improve_total_seconds,
            )
        elif objective_profile == "verification":
            room_mode = "cp_rooms"
            use_objective = True
            retry_without_objective = True
            phased_solve = False
            improve_total_seconds = 0.0
        elif objective_profile == "fast_feasible":
            use_objective = False
            retry_without_objective = False
            phased_solve = False
            improve_total_seconds = 0.0
        elif objective_profile == "quality_first":
            use_objective = True
            retry_without_objective = True
            phased_solve = True
            feasibility_seconds, improve_total_seconds = _profile_budget_split(
                profile=objective_profile,
                time_limit=time_limit,
                feasibility_seconds=feasibility_seconds,
                improve_total_seconds=improve_total_seconds,
            )
            improve_slice_seconds = max(float(improve_slice_seconds), 6.0)
            improve_iters_per_slice = max(int(improve_iters_per_slice), 1500)
            improve_max_rounds = max(int(improve_max_rounds), 16)
        elif objective_profile == "balanced" and phased_solve:
            feasibility_seconds, improve_total_seconds = _profile_budget_split(
                profile=objective_profile,
                time_limit=time_limit,
                feasibility_seconds=feasibility_seconds,
                improve_total_seconds=improve_total_seconds,
            )
        _emit_progress(
            "run_start",
            phased=bool(phased_solve),
            room_mode=str(room_mode),
            use_objective=bool(use_objective),
            objective_profile=str(objective_profile),
            retry_without_objective=bool(retry_without_objective),
            strict_limit_seconds=(float(strict_limit) if strict_limit is not None else None),
            time_limit_seconds=(float(time_limit) if time_limit is not None else None),
            improve_total_seconds=float(improve_total_seconds),
            improve_max_rounds=int(improve_max_rounds),
        )

        if phased_solve:
            feasibility_limit = feasibility_seconds if feasibility_seconds is not None else strict_limit
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
            feasibility_deadline = (
                time.perf_counter() + float(feasibility_limit)
                if feasibility_limit is not None
                else None
            )
            strict_deadline = (
                time.perf_counter() + float(strict_limit_phase)
                if strict_limit_phase is not None
                else feasibility_deadline
            )
            solver_model, sat, status = _solve_attempt(
                room_mode,
                False,
                _remaining(strict_deadline) if strict_deadline is not None else strict_limit_phase,
            )
            fallback_limit = _remaining(feasibility_deadline)
            if room_mode == "cp_rooms" and not _is_feasible(status) and (fallback_limit is None or fallback_limit > 0):
                _emit_progress("solve_fallback", from_mode="cp_rooms", to_mode="greedy")
                solver_model, sat, status = _solve_attempt("greedy", False, fallback_limit)
            meta["phased"] = {
                "enabled": True,
                "feasibility_seconds": feasibility_limit,
                "improve_total_seconds": improve_total_seconds,
                "improve_slice_seconds": improve_slice_seconds,
                "improve_iters_per_slice": improve_iters_per_slice,
                "improve_max_rounds": improve_max_rounds,
                "cp_rooms_fallback_reserve_seconds": fallback_reserve,
            }
        else:
            solve_deadline = (
                time.perf_counter() + float(time_limit)
                if time_limit is not None
                else None
            )
            base_limit = strict_limit if use_objective else time_limit
            first_limit = (
                min(float(base_limit), float(_remaining(solve_deadline)))
                if solve_deadline is not None and base_limit is not None
                else base_limit
            )
            solver_model, sat, status = _solve_attempt(room_mode, use_objective, first_limit)

            # Retry in the same room mode without objective when objective search times out/returns unknown.
            retry_limit = _remaining(solve_deadline)
            if (
                retry_without_objective
                and use_objective
                and not _is_feasible(status)
                and (retry_limit is None or retry_limit > 0)
            ):
                solver_model, sat, status = _solve_attempt(room_mode, False, retry_limit)

            # Fallback: if strict mode still fails, retry with greedy rooming and no objective for feasibility.
            fallback_limit = _remaining(solve_deadline)
            if room_mode == "cp_rooms" and not _is_feasible(status) and (fallback_limit is None or fallback_limit > 0):
                _emit_progress("solve_fallback", from_mode="cp_rooms", to_mode="greedy")
                solver_model, sat, status = _solve_attempt("greedy", False, fallback_limit)
            meta["phased"] = {"enabled": False}
    except Exception as e:
        print(f"[error] CP build/solve failed: {e}", file=sys.stderr)
        traceback.print_exc()
        return 3

    ui_status = _map_status_to_ui(status)
    meta["final_raw_status"] = int(status)
    meta["final_ui_status"] = int(ui_status)

    # Only write a schedule if we are FEASIBLE or OPTIMAL by the UI's convention
    if ui_status not in (0, 4):
        try:
            with open(out_path, "wb") as f:
                pickle.dump({"status": ui_status, "schedule": {}, "meta": meta}, f)
        except Exception as e:
            print(f"[error] failed to write result pickle: {e}", file=sys.stderr)
            traceback.print_exc()
            return 5
        print(f"[warn] solver returned non-feasible status: {status} (ui_status={ui_status})")
        return 0  # UI will handle non-(0,4) as "no feasible schedule"

    try:
        schedule: Dict[int, Dict[str, Any]] = solver_model.extract_solution(sat)
    except GreedyRoomingError as e:
        print(f"[error] greedy rooming failed: {e}", file=sys.stderr)
        traceback.print_exc()
        try:
            with open(out_path, "wb") as f:
                pickle.dump({"status": -2, "schedule": {}, "error": str(e), "reason": e.reason, "meta": meta}, f)
        except Exception as write_err:
            print(f"[error] failed to write result pickle: {write_err}", file=sys.stderr)
        return 0
    except Exception as e:
        print(f"[error] failed to extract solution: {e}", file=sys.stderr)
        traceback.print_exc()
        return 4

    if enforce_hard_conflict_free:
        try:
            post_extract_errors = _hard_conflict_errors(inst, schedule)
        except Exception as e:
            post_extract_errors = [f"Hard-conflict validation failed: {e}"]
        if post_extract_errors:
            meta["hard_conflicts"] = {
                "count": len(post_extract_errors),
                "sample": post_extract_errors[:25],
                "stage": "post_extract",
            }
            try:
                with open(out_path, "wb") as f:
                    pickle.dump(
                        {
                            "status": -3,
                            "schedule": {},
                            "error": (
                                "Solver returned a schedule with hard conflicts; "
                                "strict conflict gate rejected it."
                            ),
                            "meta": meta,
                        },
                        f,
                    )
            except Exception as write_err:
                print(f"[error] failed to write result pickle: {write_err}", file=sys.stderr)
                traceback.print_exc()
                return 5
            print(f"[warn] strict hard-conflict gate rejected solution ({len(post_extract_errors)} errors)")
            return 0

    if phased_solve and improve_total_seconds > 0:
        try:
            _emit_progress(
                "improve_start",
                total_seconds=float(improve_total_seconds),
                max_rounds=int(improve_max_rounds),
                iters_per_slice=int(improve_iters_per_slice),
            )
            improver = LocalSearchImprover(inst)
            best_schedule = {a_id: info.copy() for a_id, info in schedule.items()}
            best_penalty = int(improver.compute_soft_penalty(best_schedule))
            base_penalty = best_penalty
            start_ts = time.perf_counter()
            deadline = start_ts + improve_total_seconds
            rounds: list[dict[str, object]] = []

            for round_idx in range(1, improve_max_rounds + 1):
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                slice_budget = min(improve_slice_seconds, remaining)
                candidate = improver.improve(
                    best_schedule,
                    iterations=improve_iters_per_slice,
                    max_seconds=slice_budget,
                )
                candidate_penalty = int(improver.compute_soft_penalty(candidate))
                candidate_hard_errors: list[str] = []
                if enforce_hard_conflict_free:
                    try:
                        candidate_hard_errors = _hard_conflict_errors(inst, candidate)
                    except Exception as e:
                        candidate_hard_errors = [f"Hard-conflict validation failed: {e}"]
                accepted = (not candidate_hard_errors) and (candidate_penalty <= best_penalty)
                if accepted:
                    best_schedule = {a_id: info.copy() for a_id, info in candidate.items()}
                    best_penalty = candidate_penalty
                rounds.append(
                    {
                        "round": round_idx,
                        "slice_seconds": slice_budget,
                        "candidate_penalty": candidate_penalty,
                        "hard_conflicts": len(candidate_hard_errors),
                        "accepted": accepted,
                        "best_penalty": best_penalty,
                    }
                )
                _emit_progress(
                    "improve_round",
                    round=int(round_idx),
                    max_rounds=int(improve_max_rounds),
                    candidate_penalty=int(candidate_penalty),
                    best_penalty=int(best_penalty),
                    accepted=bool(accepted),
                    elapsed_seconds=float(time.perf_counter() - start_ts),
                    total_seconds=float(improve_total_seconds),
                )

            schedule = best_schedule
            meta["improvement"] = {
                "enabled": True,
                "start_penalty": base_penalty,
                "final_penalty": best_penalty,
                "rounds": rounds,
                "elapsed_seconds": time.perf_counter() - start_ts,
            }
            _emit_progress(
                "improve_done",
                rounds_completed=int(len(rounds)),
                final_penalty=int(best_penalty),
                elapsed_seconds=float(time.perf_counter() - start_ts),
            )
        except Exception as e:
            meta["improvement"] = {"enabled": True, "error": str(e)}

    if enforce_hard_conflict_free:
        try:
            final_hard_errors = _hard_conflict_errors(inst, schedule)
        except Exception as e:
            final_hard_errors = [f"Hard-conflict validation failed: {e}"]
        if final_hard_errors:
            meta["hard_conflicts"] = {
                "count": len(final_hard_errors),
                "sample": final_hard_errors[:25],
                "stage": "final",
            }
            try:
                with open(out_path, "wb") as f:
                    pickle.dump(
                        {
                            "status": -3,
                            "schedule": {},
                            "error": (
                                "Final schedule contains hard conflicts after improvement; "
                                "strict conflict gate rejected it."
                            ),
                            "meta": meta,
                        },
                        f,
                    )
            except Exception as write_err:
                print(f"[error] failed to write result pickle: {write_err}", file=sys.stderr)
                traceback.print_exc()
                return 5
            print(f"[warn] strict hard-conflict gate rejected final schedule ({len(final_hard_errors)} errors)")
            return 0

    try:
        breakdown = compute_penalty_breakdown(inst, schedule)
        meta["quality"] = {
            "soft_penalty": int(breakdown.get("total", 0)),
            "breakdown": dict(breakdown),
            "sla": evaluate_schedule_sla(inst, schedule, hard_conflicts=0),
        }
    except Exception as e:
        meta["quality"] = {"error": str(e)}

    # Persist exactly what the UI expects
    try:
        with open(out_path, "wb") as f:
            pickle.dump({"status": ui_status, "schedule": schedule, "meta": meta}, f)
    except Exception as e:
        print(f"[error] failed to write result pickle: {e}", file=sys.stderr)
        traceback.print_exc()
        return 5

    # Brief log line for the merged QProcess output
    try:
        _emit_progress("run_done", status=int(ui_status), attempts=int(len(attempts)))
    except Exception:
        pass
    print(f"[ok] solved. activities={len(inst.activities)} status={ui_status} (raw={status}) attempts={len(attempts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
