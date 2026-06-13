from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.contracts import SolveOptions
from services.performance_service import estimate_cp_model_scale, recommend_solver_profile
from services.quality_service import compute_penalty_breakdown, rank_penalty_drivers
from services.solver_service import solve_instance
from utils.generator import generate_instance
from utils.specs import validate_schedule_against_instance


def run_case(mode: str, *, time_limit: float, profile: str | None = None) -> Dict[str, Any]:
    inst = generate_instance(str(mode))
    recommendation = recommend_solver_profile(inst)
    objective_profile = str(profile or recommendation["objective_profile"])
    room_mode = str(recommendation["room_mode"])
    started = time.perf_counter()
    result = solve_instance(
        inst,
        SolveOptions(
            room_mode=room_mode,
            objective_profile=objective_profile,
            use_objective=objective_profile not in {"fast_feasible", "university_fast"},
            time_limit_seconds=float(time_limit),
            strict_limit_seconds=min(float(time_limit), 300.0),
            workers=1,
            phased_solve=objective_profile not in {"fast_feasible", "university_fast"},
            enforce_hard_conflict_free=True,
        ),
    )
    elapsed = time.perf_counter() - started
    hard = validate_schedule_against_instance(inst, result.schedule, strict_rooms=True) if result.schedule else []
    breakdown = compute_penalty_breakdown(inst, result.schedule) if result.schedule else {"total": None}
    final_attempt = result.attempts[-1] if result.attempts else None
    return {
        "mode": str(mode),
        "status": int(result.status),
        "raw_status": int(result.raw_status),
        "wall_seconds": round(float(elapsed), 3),
        "activities": int(len(inst.activities)),
        "rooms": int(len(inst.rooms)),
        "profile": str(objective_profile),
        "room_mode": str(final_attempt.room_mode if final_attempt is not None else room_mode),
        "scale": estimate_cp_model_scale(inst),
        "hard_conflicts": int(len(hard)),
        "soft_penalty": breakdown.get("total"),
        "cp_objective_value": (
            None if final_attempt is None else final_attempt.objective_value
        ),
        "cp_best_objective_bound": (
            None if final_attempt is None else final_attempt.best_objective_bound
        ),
        "cp_relative_gap": (
            None if final_attempt is None else final_attempt.relative_gap
        ),
        "top_penalty_drivers": rank_penalty_drivers(inst, result.schedule) if result.schedule else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run scheduler benchmark profiles and emit JSON.")
    parser.add_argument("--mode", action="append", default=None, help="Generator mode; repeatable.")
    parser.add_argument("--time-limit", type=float, default=20.0)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    rows: List[Dict[str, Any]] = [
        run_case(str(mode), time_limit=float(args.time_limit), profile=args.profile)
        for mode in (args.mode or ["small_demo"])
    ]
    payload = {"cases": rows}
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
