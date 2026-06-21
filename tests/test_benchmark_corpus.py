from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest


@pytest.mark.slow
def test_small_demo_benchmark_case_meets_guardrails():
    code = r'''
import json
import time
from benchmarks.corpus import BENCHMARK_CASES
from core.metaheuristics import LocalSearchImprover
from services.contracts import SolveOptions
from services.scenario_service import build_builtin_product_scenario, compile_scenario_instance
from services.solver_service import solve_instance

case = next(c for c in BENCHMARK_CASES if c.case_id == "small_demo_fast_feasible")
scenario = build_builtin_product_scenario(case.mode)
inst = compile_scenario_instance(scenario)
start = time.perf_counter()
result = solve_instance(
    inst,
    SolveOptions(
        room_mode=case.room_mode,
        use_objective=case.use_objective,
        time_limit_seconds=case.time_limit_seconds,
        workers=1,
        retry_without_objective=False,
    ),
)
elapsed = time.perf_counter() - start
penalty = None
improved_penalty = None
if result.schedule:
    penalty = LocalSearchImprover(inst).compute_soft_penalty(result.schedule)
    improved = LocalSearchImprover(inst).improve(result.schedule, iterations=120, max_seconds=1.0)
    improved_penalty = LocalSearchImprover(inst).compute_soft_penalty(improved)
print(json.dumps({
    "status": int(result.status),
    "expected_statuses": [int(v) for v in case.expected_statuses],
    "elapsed": float(elapsed),
    "max_wall_seconds": float(case.max_wall_seconds),
    "penalty": penalty,
    "improved_penalty": improved_penalty,
    "max_soft_penalty": case.max_soft_penalty,
}), flush=True)
'''
    env = {
        **os.environ,
        "PYTHONPATH": os.getcwd() + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    proc = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
        timeout=60,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    row = json.loads(proc.stdout.strip().splitlines()[-1])
    assert int(row["status"]) in set(int(v) for v in row["expected_statuses"])
    assert float(row["elapsed"]) <= float(row["max_wall_seconds"])
    if row["max_soft_penalty"] is not None:
        assert int(row["improved_penalty"]) <= int(row["max_soft_penalty"])
