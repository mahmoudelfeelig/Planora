from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ortools.sat.python import cp_model

from utils.generator import generate_instance
from main import normalize_instance_for_spec, stamp_instance_time
from utils.specs import validate_instance_against_spec
from core.solver_cp_sat import TimetableSolver, GreedyRoomingError
from core.metaheuristics import LocalSearchImprover


def _status_name(code: int) -> str:
    return str(cp_model.CpSolverStatus(code))


def _is_feasible(code: int) -> bool:
    return code in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def run_one(
    mode: str,
    seed: int,
    *,
    room_mode: str,
    use_objective: bool,
    retry_without_objective: bool,
    cp_rooms_fallback_to_greedy: bool,
    time_limit: float,
    strict_seconds: float | None,
    workers: int,
    ls_iters: int,
    ls_seconds: float | None,
) -> dict[str, Any]:
    # Generator modes are mostly deterministic; for "random", seed affects the generator.
    os.environ["PYTHONHASHSEED"] = str(seed)
    inst = generate_instance(mode=mode)
    normalize_instance_for_spec(inst)
    stamp_instance_time(inst, "08:30", 90, 0)
    validate_instance_against_spec(inst)

    strict_limit = float(strict_seconds) if strict_seconds is not None else min(time_limit, 30.0)
    attempts: list[dict[str, Any]] = []

    def _attempt(mode_name: str, objective_enabled: bool, limit: float | None):
        solver = TimetableSolver(inst, room_mode=mode_name, use_objective=objective_enabled)
        t0 = time.perf_counter()
        sat_solver, sat_status = solver.solve(time_limit_seconds=limit, workers=workers)
        elapsed = time.perf_counter() - t0
        attempts.append(
            {
                "room_mode": mode_name,
                "use_objective": bool(objective_enabled),
                "time_limit": limit,
                "status": int(sat_status),
                "status_name": _status_name(int(sat_status)),
                "cp_seconds": elapsed,
            }
        )
        return solver, sat_solver, int(sat_status), elapsed

    solver, sat, status, _ = _attempt(room_mode, use_objective, strict_limit)

    if retry_without_objective and use_objective and not _is_feasible(status):
        solver, sat, status, _ = _attempt(room_mode, False, time_limit)

    if cp_rooms_fallback_to_greedy and room_mode == "cp_rooms" and not _is_feasible(status):
        solver, sat, status, _ = _attempt("greedy", False, time_limit)

    total_cp_seconds = sum(float(a["cp_seconds"]) for a in attempts)
    final = attempts[-1]

    out: dict[str, Any] = {
        "mode": mode,
        "seed": seed,
        "requested_room_mode": room_mode,
        "requested_use_objective": use_objective,
        "retry_without_objective": retry_without_objective,
        "cp_rooms_fallback_to_greedy": cp_rooms_fallback_to_greedy,
        "time_limit": time_limit,
        "strict_seconds": strict_limit,
        "workers": workers,
        "status": int(status),
        "status_name": _status_name(int(status)),
        "feasible": _is_feasible(status),
        "final_room_mode": str(final["room_mode"]),
        "final_use_objective": bool(final["use_objective"]),
        "cp_seconds_total": total_cp_seconds,
        "attempts": attempts,
        "instance": {
            "programs": len(inst.programs),
            "groups": len(inst.groups),
            "courses": len(inst.courses),
            "staff": len(inst.staff),
            "rooms": len(inst.rooms),
            "activities": len(inst.activities),
        },
        "penalty_base": None,
        "penalty_ls": None,
    }

    if not _is_feasible(status):
        return out

    try:
        schedule = solver.extract_solution(sat)
    except GreedyRoomingError as e:
        out["feasible"] = False
        out["status_name"] = f"ROOMING_FAILED:{e.reason}"
        out["rooming_error"] = {"reason": e.reason, "message": str(e), "activity_id": e.activity_id}
        return out

    ls = LocalSearchImprover(inst)
    out["penalty_base"] = int(ls.compute_soft_penalty(schedule))
    if ls_iters > 0:
        improved = ls.improve(schedule, iterations=ls_iters, max_seconds=ls_seconds)
        out["penalty_ls"] = int(ls.compute_soft_penalty(improved))
    return out


def _parse_csv_str(raw: str) -> list[str]:
    return [s.strip() for s in str(raw).split(",") if s.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="small_demo", help="Single generator mode")
    ap.add_argument("--modes", default="", help="Comma-separated generator modes; overrides --mode when set")
    ap.add_argument("--seeds", default="1,2,3", help="Comma-separated seeds")
    ap.add_argument("--room-mode", default="cp_rooms", choices=["cp_rooms", "greedy"], help="Single room mode")
    ap.add_argument("--room-modes", default="", help="Comma-separated room modes; overrides --room-mode when set")
    ap.add_argument("--use-objective", default="1")
    ap.add_argument("--retry-without-objective", default="1", help="Retry same room mode with objective off when first solve is not feasible")
    ap.add_argument("--cp-rooms-fallback-to-greedy", default="1", help="Fallback to greedy/no-objective when cp_rooms remains non-feasible")
    ap.add_argument("--time-limit", type=float, default=30.0)
    ap.add_argument("--strict-seconds", type=float, default=None, help="Time budget for first strict attempt")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--ls-iters", type=int, default=0)
    ap.add_argument("--ls-seconds", type=float, default=None)
    ap.add_argument("--out", default="paper/results.jsonl")
    args = ap.parse_args()

    use_objective = str(args.use_objective).lower() not in ("0", "false", "no")
    retry_without_objective = str(args.retry_without_objective).lower() not in ("0", "false", "no")
    cp_rooms_fallback = str(args.cp_rooms_fallback_to_greedy).lower() not in ("0", "false", "no")
    seeds = [int(s.strip()) for s in str(args.seeds).split(",") if s.strip()]
    modes = _parse_csv_str(args.modes) or [str(args.mode)]
    room_modes = _parse_csv_str(args.room_modes) or [str(args.room_mode)]
    for rm in room_modes:
        if rm not in ("cp_rooms", "greedy"):
            raise ValueError(f"Unsupported room mode: {rm}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for mode in modes:
            for room_mode in room_modes:
                for seed in seeds:
                    row = run_one(
                        mode,
                        seed,
                        room_mode=room_mode,
                        use_objective=use_objective,
                        retry_without_objective=retry_without_objective,
                        cp_rooms_fallback_to_greedy=cp_rooms_fallback,
                        time_limit=float(args.time_limit),
                        strict_seconds=args.strict_seconds,
                        workers=int(args.workers),
                        ls_iters=int(args.ls_iters),
                        ls_seconds=args.ls_seconds,
                    )
                    print(
                        f"[exp] mode={mode} room={room_mode} seed={seed} "
                        f"status={row['status_name']} feasible={row['feasible']} "
                        f"cp_total={row['cp_seconds_total']:.2f}s final={row['final_room_mode']}/"
                        f"{'obj' if row['final_use_objective'] else 'noobj'}"
                    )
                    f.write(json.dumps(row) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
