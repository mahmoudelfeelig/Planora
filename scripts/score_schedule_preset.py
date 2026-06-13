from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.metaheuristics import LocalSearchImprover
from services.contracts import SolveOptions
from services.quality_service import compute_penalty_breakdown
from services.solver_service import solve_instance
from utils.generator import generate_instance
from utils.specs import validate_schedule_against_instance


def _top_terms(breakdown: dict[str, int], limit: int = 6) -> list[dict[str, int | str]]:
    rows = [
        {"term": str(key), "penalty": int(value)}
        for key, value in breakdown.items()
        if key != "total" and int(value) != 0
    ]
    rows.sort(key=lambda row: int(row["penalty"]), reverse=True)
    return rows[: int(limit)]


def _print_breakdown(label: str, breakdown: dict[str, int]) -> None:
    print(f"{label} soft penalty: {int(breakdown.get('total', 0))}")
    for row in _top_terms(breakdown):
        print(f"  {row['term']}: {row['penalty']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Solve and score a built-in scheduler preset.")
    parser.add_argument("--mode", default="ss23_uni_like")
    parser.add_argument("--room-mode", default="greedy", choices=["cp_rooms", "greedy"])
    parser.add_argument("--profile", default="fast_feasible")
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=2023)
    parser.add_argument("--improve-seconds", type=float, default=20.0)
    parser.add_argument("--improve-iterations", type=int, default=5000)
    parser.add_argument("--out", default="data/ss23-uni-like-score.json")
    args = parser.parse_args(argv)

    inst = generate_instance(str(args.mode))
    print(
        "instance:",
        f"programs={len(inst.programs)}",
        f"groups={len(inst.groups)}",
        f"courses={len(inst.courses)}",
        f"rooms={len(inst.rooms)}",
        f"activities={len(inst.activities)}",
    )

    solve_started = time.perf_counter()
    result = solve_instance(
        inst,
        SolveOptions(
            room_mode=str(args.room_mode),
            objective_profile=str(args.profile),
            time_limit_seconds=float(args.time_limit),
            strict_limit_seconds=float(args.time_limit),
            workers=int(args.workers),
            random_seed=int(args.seed),
            enforce_hard_conflict_free=True,
        ),
    )
    solve_elapsed = time.perf_counter() - solve_started
    print(
        "solve:",
        f"status={result.status}",
        f"raw_status={result.raw_status}",
        f"activities={len(result.schedule or {})}",
        f"elapsed={solve_elapsed:.2f}s",
    )
    for idx, attempt in enumerate(result.attempts or [], start=1):
        print(
            f"  attempt {idx}:",
            f"room_mode={attempt.room_mode}",
            f"objective={attempt.use_objective}",
            f"limit={attempt.time_limit_seconds}",
            f"raw_status={attempt.raw_status}",
        )
    if not result.is_feasible or not result.schedule:
        print("No feasible schedule was produced; score cannot be computed.")
        if result.hard_conflicts:
            print(f"hard conflicts: {len(result.hard_conflicts)}")
            for err in result.hard_conflicts[:10]:
                print(f"  {err}")
        return 2

    hard_errors = validate_schedule_against_instance(
        inst,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    )
    before = compute_penalty_breakdown(inst, result.schedule)
    _print_breakdown("before", before)
    print(f"hard validation errors before: {len(hard_errors)}")

    improved_schedule = {int(a_id): dict(info) for a_id, info in result.schedule.items()}
    improvement_elapsed = 0.0
    if float(args.improve_seconds) > 0.0 and int(args.improve_iterations) > 0:
        improver = LocalSearchImprover(inst)
        improve_started = time.perf_counter()
        improved_schedule = improver.improve(
            improved_schedule,
            iterations=int(args.improve_iterations),
            max_seconds=float(args.improve_seconds),
        )
        improvement_elapsed = time.perf_counter() - improve_started

    improved_errors = validate_schedule_against_instance(
        inst,
        improved_schedule,
        strict_rooms=True,
        require_all_activities=True,
    )
    after = compute_penalty_breakdown(inst, improved_schedule)
    _print_breakdown("after", after)
    print(f"hard validation errors after: {len(improved_errors)}")
    print(f"improvement elapsed: {improvement_elapsed:.2f}s")
    print(f"delta: {int(after.get('total', 0)) - int(before.get('total', 0)):+d}")

    report: dict[str, Any] = {
        "mode": str(args.mode),
        "room_mode": str(args.room_mode),
        "profile": str(args.profile),
        "time_limit_seconds": float(args.time_limit),
        "workers": int(args.workers),
        "seed": int(args.seed),
        "improve_seconds": float(args.improve_seconds),
        "improve_iterations": int(args.improve_iterations),
        "instance": {
            "programs": len(inst.programs),
            "groups": len(inst.groups),
            "courses": len(inst.courses),
            "rooms": len(inst.rooms),
            "staff": len(inst.staff),
            "activities": len(inst.activities),
        },
        "solve": {
            "status": int(result.status),
            "raw_status": int(result.raw_status),
            "elapsed_seconds": float(solve_elapsed),
            "attempts": [dict(attempt.__dict__) for attempt in result.attempts],
            "hard_errors_before": list(hard_errors),
        },
        "before": {
            "breakdown": dict(before),
            "top_terms": _top_terms(before),
        },
        "after": {
            "breakdown": dict(after),
            "top_terms": _top_terms(after),
            "hard_errors": list(improved_errors),
            "elapsed_seconds": float(improvement_elapsed),
        },
        "delta": int(after.get("total", 0)) - int(before.get("total", 0)),
    }
    out_path = Path(str(args.out))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
