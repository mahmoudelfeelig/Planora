from __future__ import annotations

import time

import pytest

from benchmarks.corpus import BENCHMARK_CASES
from core.metaheuristics import LocalSearchImprover
from services.contracts import SolveOptions
from services.scenario_service import build_builtin_product_scenario, compile_scenario_instance
from services.solver_service import solve_instance


@pytest.mark.slow
def test_small_demo_benchmark_case_meets_guardrails():
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

    assert int(result.status) in set(int(v) for v in case.expected_statuses)
    assert float(elapsed) <= float(case.max_wall_seconds)
    if case.max_soft_penalty is not None:
        improver = LocalSearchImprover(inst)
        assert improver.compute_soft_penalty(result.schedule) <= int(case.max_soft_penalty)
