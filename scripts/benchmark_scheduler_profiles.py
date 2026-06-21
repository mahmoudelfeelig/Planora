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
from benchmarks.corpus import BENCHMARK_CASES
from utils.generator import generate_instance
from utils.specs import validate_schedule_against_instance


def run_case(
    mode: str,
    *,
    time_limit: float,
    profile: str | None = None,
    room_mode: str | None = None,
    use_objective: bool | None = None,
    case_id: str | None = None,
) -> Dict[str, Any]:
    inst = generate_instance(str(mode))
    recommendation = recommend_solver_profile(inst)
    objective_profile = str(profile or recommendation["objective_profile"])
    selected_room_mode = str(room_mode or recommendation["room_mode"])
    selected_use_objective = (
        bool(use_objective)
        if use_objective is not None
        else objective_profile not in {"fast_feasible", "university_fast"}
    )
    started = time.perf_counter()
    result = solve_instance(
        inst,
        SolveOptions(
            room_mode=selected_room_mode,
            objective_profile=objective_profile,
            use_objective=bool(selected_use_objective),
            time_limit_seconds=float(time_limit),
            strict_limit_seconds=min(float(time_limit), 300.0),
            workers=1,
            phased_solve=bool(selected_use_objective),
            enforce_hard_conflict_free=True,
        ),
    )
    elapsed = time.perf_counter() - started
    hard = validate_schedule_against_instance(inst, result.schedule, strict_rooms=True) if result.schedule else []
    breakdown = compute_penalty_breakdown(inst, result.schedule) if result.schedule else {"total": None}
    final_attempt = result.attempts[-1] if result.attempts else None
    return {
        "mode": str(mode),
        "case_id": str(case_id or mode),
        "status": int(result.status),
        "raw_status": int(result.raw_status),
        "wall_seconds": round(float(elapsed), 3),
        "activities": int(len(inst.activities)),
        "rooms": int(len(inst.rooms)),
        "profile": str(objective_profile),
        "room_mode": str(final_attempt.room_mode if final_attempt is not None else selected_room_mode),
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
    parser.add_argument("--corpus", action="store_true", help="Run the curated benchmark corpus.")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    if args.corpus:
        rows = [
            run_case(
                str(case.mode),
                time_limit=float(case.time_limit_seconds),
                profile=args.profile,
                room_mode=str(case.room_mode),
                use_objective=bool(case.use_objective),
                case_id=str(case.case_id),
            )
            for case in BENCHMARK_CASES
        ]
    else:
        rows = [
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
