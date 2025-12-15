from __future__ import annotations

import sys
import os
import pickle
import traceback
from typing import Dict, Any

from solver_cp_sat import TimetableSolver


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
        room_mode = os.getenv("TT_ROOM_MODE", "greedy")
        use_objective_env = os.getenv("TT_USE_OBJECTIVE", "1").strip()
        use_objective = use_objective_env not in ("0", "false", "False", "no")

        # CP-rooming defaults to enforcing capacity/availability; override via env for speed trade-offs.
        solver_model = TimetableSolver(inst, room_mode=room_mode, use_objective=use_objective)

        # Optional time limit via env var (seconds). Keep defaults if unset.
        tl = os.getenv("TT_TIME_LIMIT")
        time_limit = float(tl) if tl else None

        sat, status = solver_model.solve(time_limit_seconds=time_limit)
    except Exception as e:
        print(f"[error] CP build/solve failed: {e}", file=sys.stderr)
        traceback.print_exc()
        return 3

    ui_status = _map_status_to_ui(status)

    # Only write a schedule if we are FEASIBLE or OPTIMAL by the UI's convention
    if ui_status not in (0, 4):
        try:
            with open(out_path, "wb") as f:
                pickle.dump({"status": ui_status, "schedule": {}}, f)
        except Exception as e:
            print(f"[error] failed to write result pickle: {e}", file=sys.stderr)
            traceback.print_exc()
            return 5
        print(f"[warn] solver returned non-feasible status: {status} (ui_status={ui_status})")
        return 0  # UI will handle non-(0,4) as "no feasible schedule"

    try:
        schedule: Dict[int, Dict[str, Any]] = solver_model.extract_solution(sat)
    except Exception as e:
        print(f"[error] failed to extract solution: {e}", file=sys.stderr)
        traceback.print_exc()
        return 4

    # Persist exactly what the UI expects
    try:
        with open(out_path, "wb") as f:
            pickle.dump({"status": ui_status, "schedule": schedule}, f)
    except Exception as e:
        print(f"[error] failed to write result pickle: {e}", file=sys.stderr)
        traceback.print_exc()
        return 5

    # Brief log line for the merged QProcess output
    print(f"[ok] solved. activities={len(inst.activities)} status={ui_status} (raw={status})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
