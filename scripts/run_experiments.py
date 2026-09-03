from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ortools.sat.python import cp_model

from utils.generator import generate_instance, instance_to_json
from main import normalize_instance_for_spec, stamp_instance_time
from utils.specs import validate_instance_against_spec, validate_schedule_against_instance
from core.solver_cp_sat import TimetableSolver, GreedyRoomingError
from core.metaheuristics import LocalSearchImprover


def _status_name(code: int) -> str:
    return str(cp_model.CpSolverStatus(code))


def _is_feasible(code: int) -> bool:
    return code in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _repository_state() -> dict[str, Any]:
    def _git(*args: str) -> str | None:
        try:
            return subprocess.check_output(
                ["git", *args], cwd=ROOT_DIR, text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    status = _git("status", "--porcelain")
    return {
        "git_sha": _git("rev-parse", "HEAD"),
        "git_dirty": bool(status) if status is not None else None,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "ortools": importlib.metadata.version("ortools"),
        "pythonhashseed_at_startup": os.environ.get("PYTHONHASHSEED"),
    }


def _schedule_fingerprint(schedule: dict[int, dict[str, Any]]) -> str:
    canonical = {str(k): schedule[k] for k in sorted(schedule)}
    return _stable_hash(canonical)


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
    instance_seed = int(seed)
    solver_seed = int(seed)
    local_search_seed = int(seed)
    inst = generate_instance(mode=mode, seed=instance_seed)
    normalize_instance_for_spec(inst)
    stamp_instance_time(inst, "08:30", 90, 0)
    validate_instance_against_spec(inst)
    instance_fingerprint = _stable_hash(instance_to_json(inst))

    strict_limit = float(strict_seconds) if strict_seconds is not None else min(time_limit, 30.0)
    attempts: list[dict[str, Any]] = []

    def _attempt(role: str, mode_name: str, objective_enabled: bool, limit: float | None):
        solver = TimetableSolver(inst, room_mode=mode_name, use_objective=objective_enabled)
        t0 = time.perf_counter()
        sat_solver, sat_status = solver.solve(
            time_limit_seconds=limit,
            workers=workers,
            random_seed=solver_seed,
        )
        elapsed = time.perf_counter() - t0
        feasible = _is_feasible(int(sat_status))
        attempts.append(
            {
                "role": role,
                "room_mode": mode_name,
                "use_objective": bool(objective_enabled),
                "time_limit": limit,
                "status": int(sat_status),
                "status_name": _status_name(int(sat_status)),
                "cp_seconds": elapsed,
                "objective_value": float(sat_solver.ObjectiveValue()) if feasible and objective_enabled else None,
                "best_objective_bound": float(sat_solver.BestObjectiveBound()) if objective_enabled else None,
                "relative_gap": (
                    abs(float(sat_solver.ObjectiveValue()) - float(sat_solver.BestObjectiveBound()))
                    / max(1.0, abs(float(sat_solver.ObjectiveValue())))
                    if feasible and objective_enabled
                    else None
                ),
                "branches": int(sat_solver.NumBranches()),
                "conflicts": int(sat_solver.NumConflicts()),
                "wall_time_reported": float(sat_solver.WallTime()),
            }
        )
        return solver, sat_solver, int(sat_status), elapsed

    solver, sat, status, _ = _attempt("primary", room_mode, use_objective, strict_limit)

    if retry_without_objective and use_objective and not _is_feasible(status):
        solver, sat, status, _ = _attempt("retry_without_objective", room_mode, False, time_limit)

    if cp_rooms_fallback_to_greedy and room_mode == "cp_rooms" and not _is_feasible(status):
        solver, sat, status, _ = _attempt("fallback", "greedy", False, time_limit)

    total_cp_seconds = sum(float(a["cp_seconds"]) for a in attempts)
    final = attempts[-1]

    out: dict[str, Any] = {
        "schema_version": 2,
        "run_id": _stable_hash(
            {
                "mode": mode,
                "instance_seed": instance_seed,
                "solver_seed": solver_seed,
                "local_search_seed": local_search_seed,
                "room_mode": room_mode,
                "use_objective": use_objective,
                "strict_limit": strict_limit,
                "time_limit": time_limit,
                "workers": workers,
                "ls_iters": ls_iters,
            }
        )[:16],
        "mode": mode,
        "seed": instance_seed,
        "seeds": {
            "instance": instance_seed,
            "solver": solver_seed,
            "local_search": local_search_seed,
        },
        "deterministic_solver_configuration": workers == 1,
        "instance_sha256": instance_fingerprint,
        "environment": _repository_state(),
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
        "primary_attempt": attempts[0],
        "fallback_used": len(attempts) > 1,
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
        "schedule_sha256_base": None,
        "schedule_sha256_ls": None,
        "validation_errors_base": [],
        "validation_errors_ls": [],
        "effective_instance": False,
        "decomposition": getattr(solver, "decomposition_report", None),
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

    out["schedule_sha256_base"] = _schedule_fingerprint(schedule)
    out["validation_errors_base"] = validate_schedule_against_instance(
        inst,
        schedule,
        strict_rooms=True,
    )
    out["effective_instance"] = not out["validation_errors_base"] and not out["fallback_used"]
    ls = LocalSearchImprover(inst, random_seed=local_search_seed)
    out["penalty_base"] = int(ls.compute_soft_penalty(schedule))
    if ls_iters > 0:
        improved = ls.improve(schedule, iterations=ls_iters, max_seconds=ls_seconds)
        out["penalty_ls"] = int(ls.compute_soft_penalty(improved))
        out["schedule_sha256_ls"] = _schedule_fingerprint(improved)
        out["validation_errors_ls"] = validate_schedule_against_instance(
            inst,
            improved,
            strict_rooms=True,
        )
    return out


def _parse_csv_str(raw: str) -> list[str]:
    return [s.strip() for s in str(raw).split(",") if s.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="small_demo", help="Single generator mode")
    ap.add_argument("--modes", default="", help="Comma-separated generator modes; overrides --mode when set")
    ap.add_argument("--seeds", default="1,2,3", help="Comma-separated seeds")
    ap.add_argument("--room-mode", default="cp_rooms", choices=["cp_rooms", "greedy", "decomposed"], help="Single room mode")
    ap.add_argument("--room-modes", default="", help="Comma-separated room modes; overrides --room-mode when set")
    ap.add_argument("--use-objective", default="1")
    ap.add_argument("--retry-without-objective", default="0", help="Retry same room mode with objective off; disabled for clean comparisons")
    ap.add_argument("--cp-rooms-fallback-to-greedy", default="0", help="Fallback to greedy/no-objective; disabled for clean comparisons")
    ap.add_argument("--time-limit", type=float, default=30.0)
    ap.add_argument("--strict-seconds", type=float, default=None, help="Time budget for first strict attempt")
    ap.add_argument("--workers", type=int, default=1, help="Use one worker for reproducible research runs")
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
        if rm not in ("cp_rooms", "greedy", "decomposed"):
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
