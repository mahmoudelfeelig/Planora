from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ortools.sat.python import cp_model

from utils.generator import generate_instance
from main import normalize_instance_for_spec, stamp_instance_time
from utils.specs import validate_instance_against_spec
from core.solver_cp_sat import TimetableSolver
from core.metaheuristics import LocalSearchImprover


def run_one(mode: str, seed: int, *, room_mode: str, use_objective: bool, time_limit: float, workers: int, ls_iters: int, ls_seconds: float | None):
    # Generator modes are mostly deterministic; for "random", seed affects the generator.
    os.environ["PYTHONHASHSEED"] = str(seed)
    inst = generate_instance(mode=mode)
    normalize_instance_for_spec(inst)
    stamp_instance_time(inst, "08:30", 90, 0)
    validate_instance_against_spec(inst)

    solver = TimetableSolver(inst, room_mode=room_mode, use_objective=use_objective)
    t0 = time.perf_counter()
    sat, status = solver.solve(time_limit_seconds=time_limit, workers=workers)
    t1 = time.perf_counter()

    out = {
        "mode": mode,
        "seed": seed,
        "room_mode": room_mode,
        "use_objective": use_objective,
        "time_limit": time_limit,
        "workers": workers,
        "status": int(status),
        "status_name": str(cp_model.CpSolverStatus(status)),
        "cp_seconds": t1 - t0,
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

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return out

    schedule = solver.extract_solution(sat)
    ls = LocalSearchImprover(inst)
    out["penalty_base"] = int(ls.compute_soft_penalty(schedule))

    if ls_iters > 0:
        improved = ls.improve(schedule, iterations=ls_iters, max_seconds=ls_seconds)
        out["penalty_ls"] = int(ls.compute_soft_penalty(improved))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="small_demo", help="Generator mode")
    ap.add_argument("--seeds", default="1,2,3", help="Comma-separated seeds")
    ap.add_argument("--room-mode", default="cp_rooms", choices=["cp_rooms", "greedy"])
    ap.add_argument("--use-objective", default="1")
    ap.add_argument("--time-limit", type=float, default=30.0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--ls-iters", type=int, default=0)
    ap.add_argument("--ls-seconds", type=float, default=None)
    ap.add_argument("--out", default="paper/results.jsonl")
    args = ap.parse_args()

    use_objective = str(args.use_objective).lower() not in ("0", "false", "no")
    seeds = [int(s.strip()) for s in str(args.seeds).split(",") if s.strip()]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for seed in seeds:
            row = run_one(
                args.mode,
                seed,
                room_mode=args.room_mode,
                use_objective=use_objective,
                time_limit=float(args.time_limit),
                workers=int(args.workers),
                ls_iters=int(args.ls_iters),
                ls_seconds=args.ls_seconds,
            )
            f.write(json.dumps(row) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
