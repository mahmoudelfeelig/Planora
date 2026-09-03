from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ortools.sat.python import cp_model

from core.solver_factory import build_timetable_solver
from services.research_metrics_service import evaluate_research_metrics
from services.scenario_service import build_builtin_product_scenario, compile_scenario_instance
from utils.process_memory import peak_rss_kib
from utils.specs import validate_schedule_against_instance


def _timed(call: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    value = call()
    return value, float(time.perf_counter() - started)


def run_local_app_benchmark(
    *,
    mode: str = "small_demo",
    room_mode: str = "decomposed",
    use_objective: bool = False,
    time_limit_seconds: float = 15.0,
    workers: int = 1,
    random_seed: int = 1,
    include_desktop_startup: bool = True,
) -> dict[str, Any]:
    """Exercise the local product path and return machine-readable timings."""
    scenario, scenario_seconds = _timed(
        lambda: build_builtin_product_scenario(str(mode), name="Local benchmark")
    )
    inst, compile_seconds = _timed(lambda: compile_scenario_instance(scenario))
    model, model_seconds = _timed(
        lambda: build_timetable_solver(
            inst,
            room_mode=str(room_mode),
            use_objective=bool(use_objective),
        )
    )
    solved, solve_seconds = _timed(
        lambda: model.solve(
            time_limit_seconds=float(time_limit_seconds),
            workers=int(workers),
            random_seed=int(random_seed),
        )
    )
    solver, status = solved
    feasible = int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    schedule: dict[int, dict[str, Any]] = {}
    extract_seconds = 0.0
    validation_errors: list[str] = []
    metrics: dict[str, Any] | None = None
    metrics_seconds = 0.0
    if feasible:
        schedule, extract_seconds = _timed(lambda: model.extract_solution(solver))
        validation_errors, validation_seconds = _timed(
            lambda: validate_schedule_against_instance(
                inst,
                schedule,
                strict_rooms=True,
                require_all_activities=True,
            )
        )
        metrics, metrics_seconds = _timed(
            lambda: evaluate_research_metrics(inst, schedule)
        )
    else:
        validation_seconds = 0.0

    desktop_seconds: float | None = None
    if include_desktop_startup:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication

            from ui.app import MainWindow

            app = QApplication.instance() or QApplication([])
            window, desktop_seconds = _timed(MainWindow)
            window.close()
            window.deleteLater()
            app.processEvents()
        except ImportError:
            desktop_seconds = None

    if hasattr(model, "model_stats"):
        model_stats = dict(model.model_stats())
    else:
        proto = model.m.Proto()
        model_stats = {
            "variables": len(proto.variables),
            "constraints": len(proto.constraints),
            "materialized_start_literals": len(model.x),
        }
    stage_seconds = {
        "scenario": scenario_seconds,
        "compile": compile_seconds,
        "model": model_seconds,
        "solve": solve_seconds,
        "extract": extract_seconds,
        "validate": validation_seconds,
        "metrics": metrics_seconds,
        "desktop_startup": desktop_seconds,
    }
    measured_total = sum(
        float(value) for value in stage_seconds.values() if value is not None
    )
    return {
        "schema_version": 1,
        "mode": str(mode),
        "room_mode": str(room_mode),
        "use_objective": bool(use_objective),
        "time_limit_seconds": float(time_limit_seconds),
        "workers": int(workers),
        "random_seed": int(random_seed),
        "include_desktop_startup": bool(include_desktop_startup),
        "status": int(status),
        "status_name": str(cp_model.CpSolverStatus(int(status))),
        "feasible": bool(feasible),
        "stage_seconds": stage_seconds,
        "measured_total_seconds": float(measured_total),
        "model": model_stats,
        "instance": {
            "activities": len(inst.activities),
            "rooms": len(inst.rooms),
            "groups": len(inst.groups),
            "staff": len(inst.staff),
        },
        "schedule_rows": len(schedule),
        "validation_error_count": len(validation_errors),
        "validation_errors": validation_errors[:20],
        "peak_rss_kib": peak_rss_kib(),
        "research_metrics": metrics,
        "decomposition": dict(getattr(model, "decomposition_report", {}) or {}),
    }


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * min(1.0, max(0.0, float(probability)))
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def summarize_benchmark_runs(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate repeated full-path measurements without hiding failed runs."""
    if not reports:
        raise ValueError("At least one benchmark report is required")

    def _series(stage: str | None = None) -> list[float]:
        if stage is None:
            return [float(report["measured_total_seconds"]) for report in reports]
        return [
            float(value)
            for report in reports
            if (value := (report.get("stage_seconds") or {}).get(stage)) is not None
        ]

    def _summary(values: list[float]) -> dict[str, float | None]:
        return {
            "minimum": min(values) if values else None,
            "median": statistics.median(values) if values else None,
            "p95": _percentile(values, 0.95),
            "maximum": max(values) if values else None,
        }

    valid_runs = [
        report
        for report in reports
        if bool(report.get("feasible"))
        and int(report.get("validation_error_count", -1)) == 0
    ]
    return {
        "schema_version": 2,
        "kind": "local_app_repeated_benchmark",
        "configuration": {
            key: reports[0].get(key)
            for key in (
                "mode",
                "room_mode",
                "use_objective",
                "time_limit_seconds",
                "workers",
                "random_seed",
                "include_desktop_startup",
            )
        },
        "repetitions": len(reports),
        "valid_runs": len(valid_runs),
        "all_runs_valid": len(valid_runs) == len(reports),
        "timings": {
            "measured_total_seconds": _summary(_series()),
            "model_seconds": _summary(_series("model")),
            "solve_seconds": _summary(_series("solve")),
            "validation_seconds": _summary(_series("validate")),
            "desktop_startup_seconds": _summary(_series("desktop_startup")),
        },
        "peak_rss_kib_max": max(int(report["peak_rss_kib"]) for report in reports),
        "runs": reports,
    }


def run_local_app_benchmark_series(
    *,
    repeats: int,
    warmup_runs: int = 0,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run repeated scenario-to-validated-schedule paths in one controlled process."""
    if int(repeats) <= 0:
        raise ValueError("repeats must be positive")
    if int(warmup_runs) < 0:
        raise ValueError("warmup_runs must be non-negative")
    for _ in range(int(warmup_runs)):
        run_local_app_benchmark(**kwargs)
    reports = [run_local_app_benchmark(**kwargs) for _ in range(int(repeats))]
    result = summarize_benchmark_runs(reports)
    result["warmup_runs"] = int(warmup_runs)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark the local Planora scenario-to-schedule application path."
    )
    parser.add_argument("--mode", default="small_demo")
    parser.add_argument(
        "--room-mode",
        default="decomposed",
        choices=["greedy", "cp_rooms", "decomposed", "partitioned"],
    )
    parser.add_argument("--use-objective", action="store_true")
    parser.add_argument("--time-limit", type=float, default=15.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--skip-desktop-startup", action="store_true")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--warmup-runs", type=int, default=0)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    benchmark_kwargs = {
        "mode": args.mode,
        "room_mode": args.room_mode,
        "use_objective": bool(args.use_objective),
        "time_limit_seconds": float(args.time_limit),
        "workers": int(args.workers),
        "random_seed": int(args.seed),
        "include_desktop_startup": not bool(args.skip_desktop_startup),
    }
    if int(args.repeats) == 1 and int(args.warmup_runs) == 0:
        payload = run_local_app_benchmark(**benchmark_kwargs)
        success = bool(payload["feasible"]) and payload["validation_error_count"] == 0
    else:
        payload = run_local_app_benchmark_series(
            repeats=int(args.repeats),
            warmup_runs=int(args.warmup_runs),
            **benchmark_kwargs,
        )
        success = bool(payload["all_runs_valid"])
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
