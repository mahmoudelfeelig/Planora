from __future__ import annotations

import sys
import os
import pickle
import traceback
from typing import Dict, Any

from core.solver_cp_sat import TimetableSolver, GreedyRoomingError


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
        room_mode = os.getenv("TT_ROOM_MODE", "cp_rooms")
        use_objective_env = os.getenv("TT_USE_OBJECTIVE", "1").strip()
        use_objective = use_objective_env not in ("0", "false", "False", "no")
        retry_without_objective = _read_bool_env("TT_RETRY_NO_OBJECTIVE", True)
        log_progress_env = os.getenv("TT_CP_LOG", "").strip().lower()
        log_progress = log_progress_env not in ("", "0", "false", "no")
        workers = _read_int_env("TT_CP_WORKERS")
        attempts: list[dict[str, object]] = []

        from ortools.sat.python import cp_model

        def _solve_attempt(mode: str, objective: bool, limit: float | None):
            nonlocal attempts
            model = TimetableSolver(inst, room_mode=mode, use_objective=objective)
            sat_solver, sat_status = model.solve(
                time_limit_seconds=limit,
                workers=workers,
                log_progress=log_progress,
            )
            attempts.append(
                {
                    "room_mode": mode,
                    "use_objective": objective,
                    "time_limit_seconds": limit,
                    "status": int(sat_status),
                }
            )
            return model, sat_solver, sat_status

        # Optional time limit via env var (seconds). Keep defaults if unset.
        tl = os.getenv("TT_TIME_LIMIT")
        strict_tl = os.getenv("TT_STRICT_TIME_LIMIT")
        time_limit = float(tl) if tl else None
        strict_limit = float(strict_tl) if strict_tl else (min(time_limit, 30.0) if time_limit else 30.0)

        solver_model, sat, status = _solve_attempt(room_mode, use_objective, strict_limit)

        # Retry in the same room mode without objective when objective search times out/returns unknown.
        if (
            retry_without_objective
            and use_objective
            and status not in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        ):
            solver_model, sat, status = _solve_attempt(room_mode, False, time_limit)

        # Fallback: if strict mode still fails, retry with greedy rooming and no objective for feasibility.
        if room_mode == "cp_rooms" and status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            solver_model, sat, status = _solve_attempt("greedy", False, time_limit)
    except Exception as e:
        print(f"[error] CP build/solve failed: {e}", file=sys.stderr)
        traceback.print_exc()
        return 3

    ui_status = _map_status_to_ui(status)

    # Only write a schedule if we are FEASIBLE or OPTIMAL by the UI's convention
    if ui_status not in (0, 4):
        try:
            with open(out_path, "wb") as f:
                pickle.dump({"status": ui_status, "schedule": {}, "meta": {"attempts": attempts}}, f)
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
                pickle.dump({"status": -2, "schedule": {}, "error": str(e), "reason": e.reason}, f)
        except Exception as write_err:
            print(f"[error] failed to write result pickle: {write_err}", file=sys.stderr)
        return 0
    except Exception as e:
        print(f"[error] failed to extract solution: {e}", file=sys.stderr)
        traceback.print_exc()
        return 4

    # Persist exactly what the UI expects
    try:
        with open(out_path, "wb") as f:
            pickle.dump({"status": ui_status, "schedule": schedule, "meta": {"attempts": attempts}}, f)
    except Exception as e:
        print(f"[error] failed to write result pickle: {e}", file=sys.stderr)
        traceback.print_exc()
        return 5

    # Brief log line for the merged QProcess output
    print(f"[ok] solved. activities={len(inst.activities)} status={ui_status} (raw={status})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
