from __future__ import annotations

import gc
import tracemalloc

import pytest

from services.contracts import SolveOptions
from services.diagnostics_service import build_stakeholder_quality_report, compute_entity_heatmaps
from services.scenario_service import build_builtin_product_scenario, compile_scenario_instance
from services.solver_service import solve_instance


@pytest.mark.slow
def test_repeated_service_cycles_keep_python_memory_bounded():
    tracemalloc.start()
    gc.collect()
    baseline_current, _baseline_peak = tracemalloc.get_traced_memory()

    for idx in range(4):
        scenario = build_builtin_product_scenario("small_demo", name=f"Mem {idx}")
        inst = compile_scenario_instance(scenario)
        result = solve_instance(
            inst,
            SolveOptions(
                room_mode="greedy",
                use_objective=False,
                retry_without_objective=False,
                objective_profile="balanced",
                time_limit_seconds=12.0,
                workers=1,
            ),
        )
        assert result.is_feasible is True
        assert result.schedule
        compute_entity_heatmaps(inst, result.schedule)
        build_stakeholder_quality_report(inst, result.schedule)
        del inst
        del result
        gc.collect()

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Conservative regression guards: we only track Python allocations.
    assert (current - baseline_current) < 20_000_000
    assert (peak - baseline_current) < 80_000_000
