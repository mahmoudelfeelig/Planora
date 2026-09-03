from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ortools.sat.python import cp_model

from core.solver_cp_sat import TimetableSolver
from main import normalize_instance_for_spec, stamp_instance_time
from utils.disruption import apply_room_outage_week, apply_staff_outage_week
from utils.generator import generate_instance
from utils.specs import validate_instance_against_spec, validate_schedule_against_instance


def _schedule_hash(schedule: dict[int, dict[str, Any]]) -> str:
    payload = json.dumps(
        {str(key): schedule[key] for key in sorted(schedule)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _changed_activities(
    baseline: dict[int, dict[str, Any]], candidate: dict[int, dict[str, Any]]
) -> int:
    fields = ("week", "day", "slot", "room_id", "staff_id")
    return sum(
        any(baseline[activity_id].get(field) != candidate[activity_id].get(field) for field in fields)
        for activity_id in baseline.keys() & candidate.keys()
    )


def run_disruption_trials(
    mode: str,
    seed: int,
    *,
    room_mode: str,
    time_limit_seconds: float,
    trials_per_type: int,
) -> dict[str, Any]:
    instance = generate_instance(mode, seed=int(seed))
    normalize_instance_for_spec(instance)
    stamp_instance_time(instance, "08:30", 90, 0)
    validate_instance_against_spec(instance)
    model = TimetableSolver(instance, room_mode=room_mode, use_objective=False)
    started = time.perf_counter()
    solver, status = model.solve(
        time_limit_seconds=float(time_limit_seconds),
        workers=1,
        random_seed=int(seed),
    )
    elapsed = time.perf_counter() - started
    feasible = int(status) in (int(cp_model.OPTIMAL), int(cp_model.FEASIBLE))
    output: dict[str, Any] = {
        "schema_version": 1,
        "mode": mode,
        "seed": int(seed),
        "room_mode": room_mode,
        "baseline_status": str(cp_model.CpSolverStatus(int(status))),
        "baseline_seconds": float(elapsed),
        "baseline_feasible": feasible,
        "baseline_schedule_sha256": None,
        "decomposition": dict(getattr(model, "decomposition_report", {}) or {}),
        "trials": [],
    }
    if not feasible:
        return output
    baseline = model.extract_solution(solver)
    output["baseline_schedule_sha256"] = _schedule_hash(baseline)
    rng = random.Random(int(seed))

    staff_events = sorted(
        {
            (int(info["staff_id"]), int(info["week"]))
            for info in baseline.values()
        }
    )
    room_events = sorted(
        {
            (int(info["room_id"]), int(info["week"]))
            for info in baseline.values()
            if info.get("room_id") is not None
        }
    )
    rng.shuffle(staff_events)
    rng.shuffle(room_events)
    for disruption_type, events in (("staff_outage", staff_events), ("room_outage", room_events)):
        for resource_id, week in events[: max(0, int(trials_per_type))]:
            trial_started = time.perf_counter()
            if disruption_type == "staff_outage":
                candidate, affected, unresolved = apply_staff_outage_week(
                    instance,
                    baseline,
                    staff_id=int(resource_id),
                    week=int(week),
                )
            else:
                candidate, affected, unresolved = apply_room_outage_week(
                    instance,
                    baseline,
                    room_id=int(resource_id),
                    week=int(week),
                )
            errors = validate_schedule_against_instance(
                instance,
                candidate,
                strict_rooms=True,
                require_all_activities=True,
            )
            output["trials"].append(
                {
                    "type": disruption_type,
                    "resource_id": int(resource_id),
                    "week": int(week),
                    "affected_activities": len(affected),
                    "unresolved_activities": len(unresolved),
                    "recovery_rate": (
                        (len(affected) - len(unresolved)) / len(affected) if affected else 1.0
                    ),
                    "changed_activities": _changed_activities(baseline, candidate),
                    "hard_conflicts": len(errors),
                    "hard_conflict_sample": errors[:10],
                    "repair_seconds": time.perf_counter() - trial_started,
                    "schedule_sha256": _schedule_hash(candidate),
                }
            )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic room/staff outage experiments.")
    parser.add_argument("--mode", default="small_demo")
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--room-mode", choices=["greedy", "cp_rooms", "decomposed"], default="decomposed")
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--trials-per-type", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("paper/disruption_results.jsonl"))
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for seed in [int(value.strip()) for value in args.seeds.split(",") if value.strip()]:
            result = run_disruption_trials(
                args.mode,
                seed,
                room_mode=args.room_mode,
                time_limit_seconds=args.time_limit,
                trials_per_type=args.trials_per_type,
            )
            handle.write(json.dumps(result, sort_keys=True) + "\n")
            print(
                f"[disruption] mode={args.mode} seed={seed} "
                f"baseline={result['baseline_status']} trials={len(result['trials'])}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
