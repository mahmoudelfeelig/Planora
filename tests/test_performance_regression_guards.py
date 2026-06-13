from __future__ import annotations

import time
from pathlib import Path

from services.contracts import SolveOptions
from services.diagnostics_service import (
    build_stakeholder_quality_report,
    compute_entity_heatmaps,
)
from services.export_service import export_bundle
from services.scenario_service import build_builtin_product_scenario, compile_scenario_instance
from services.solver_service import solve_instance


def _solve_balanced_small():
    scenario = build_builtin_product_scenario("small_demo", name="Perf Demo")
    inst = compile_scenario_instance(scenario)
    options = SolveOptions(
        room_mode="greedy",
        use_objective=False,
        retry_without_objective=False,
        objective_profile="balanced",
        time_limit_seconds=15.0,
        workers=1,
    )
    result = solve_instance(inst, options)
    assert result.is_feasible is True
    assert result.schedule
    return inst, result.schedule, options


def test_solver_cache_second_call_is_not_slower():
    scenario = build_builtin_product_scenario("small_demo", name="Cache Demo")
    inst = compile_scenario_instance(scenario)
    options = SolveOptions(
        room_mode="greedy",
        use_objective=False,
        retry_without_objective=False,
        objective_profile="balanced",
        time_limit_seconds=15.0,
        workers=1,
    )

    start_first = time.perf_counter()
    first = solve_instance(inst, options)
    first_elapsed = time.perf_counter() - start_first

    start_second = time.perf_counter()
    second = solve_instance(inst, options)
    second_elapsed = time.perf_counter() - start_second

    assert first.is_feasible is True
    assert second.is_feasible is True
    assert second.meta.get("cached") is True
    assert second_elapsed <= max(0.25, first_elapsed * 0.75)


def test_diagnostics_services_complete_within_reasonable_budget():
    inst, schedule, _options = _solve_balanced_small()

    start = time.perf_counter()
    heatmaps = compute_entity_heatmaps(inst, schedule)
    report = build_stakeholder_quality_report(inst, schedule)
    elapsed = time.perf_counter() - start

    assert heatmaps["groups"]
    assert report["summary"]["hard_conflicts"] == 0
    assert elapsed < 2.0


def test_export_bundle_completes_within_reasonable_budget(tmp_path: Path):
    inst, schedule, _options = _solve_balanced_small()

    start = time.perf_counter()
    bundle = export_bundle(
        inst,
        schedule,
        tmp_path / "bundle",
        branding={"display_name": "Planora Perf"},
        baseline_schedule=schedule,
    )
    elapsed = time.perf_counter() - start

    assert Path(bundle["docx"]).exists()
    assert Path(bundle["reports_dir"], "quality_report.json").exists()
    assert elapsed < 3.0
