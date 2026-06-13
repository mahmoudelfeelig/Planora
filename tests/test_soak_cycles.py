from __future__ import annotations

import pytest

from services.contracts import ImproveOptions, SolveOptions
from services.scenario_service import build_builtin_product_scenario, compile_scenario_instance
from services.solver_service import improve_schedule, solve_instance
from utils.specs import validate_schedule_against_instance


@pytest.mark.slow
def test_repeated_solve_improve_cycles_remain_feasible():
    profiles = ["fast_feasible", "balanced", "quality_first"]

    for cycle_idx in range(4):
        scenario = build_builtin_product_scenario(
            "small_demo",
            name=f"Soak cycle {cycle_idx}",
        )
        inst = compile_scenario_instance(scenario)
        solve_result = solve_instance(
            inst,
            SolveOptions(
                room_mode="greedy",
                use_objective=(profiles[cycle_idx % len(profiles)] != "fast_feasible"),
                retry_without_objective=True,
                objective_profile=profiles[cycle_idx % len(profiles)],
                time_limit_seconds=18.0,
                workers=1,
            ),
        )
        assert solve_result.is_feasible is True
        assert solve_result.schedule
        assert validate_schedule_against_instance(inst, solve_result.schedule, strict_rooms=True) == []

        improved = improve_schedule(
            inst,
            solve_result.schedule,
            ImproveOptions(
                iterations=400,
                max_seconds=0.2,
                progress_every=200,
            ),
        )
        assert improved
        assert validate_schedule_against_instance(inst, improved, strict_rooms=True) == []
