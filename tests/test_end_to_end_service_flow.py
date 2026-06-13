from __future__ import annotations

import json
from pathlib import Path

from services.compare_service import compare_schedule_sets
from services.contracts import SolveOptions
from services.export_service import export_bundle
from services.project_service import load_legacy_project, save_legacy_project
from services.runtime_ops_service import collect_support_bundle, default_runtime_paths
from services.scenario_service import (
    build_builtin_product_scenario,
    compile_scenario_instance,
    save_product_scenario,
    load_product_scenario,
)
from services.solver_service import solve_instance, solve_portfolio


def test_end_to_end_product_solve_export_and_project_roundtrip(tmp_path: Path):
    scenario = build_builtin_product_scenario("small_demo", name="E2E Demo", owner="feel")
    scenario.constraints.objective_profile = "balanced"
    scenario.constraints.sla_targets = {"max_soft_penalty": 250}

    scenario_path = tmp_path / "scenario.json"
    save_product_scenario(scenario_path, scenario)
    restored = load_product_scenario(scenario_path)
    inst = compile_scenario_instance(restored)

    result = solve_instance(
        inst,
        SolveOptions(
            room_mode="greedy",
            use_objective=False,
            retry_without_objective=False,
            objective_profile="balanced",
            time_limit_seconds=15.0,
            workers=1,
        ),
    )
    assert result.is_feasible is True
    assert result.schedule
    assert result.hard_conflicts == []

    bundle_dir = tmp_path / "bundle"
    bundle = export_bundle(
        inst,
        result.schedule,
        bundle_dir,
        branding={"display_name": "Planora E2E"},
        baseline_schedule=result.schedule,
    )
    assert Path(bundle["docx"]).exists()
    assert Path(bundle["csv"]).exists()
    assert Path(bundle["pdf"]).exists()
    assert Path(bundle["reports_dir"]).exists()
    assert Path(bundle["ics_dir"]).exists()
    assert Path(bundle["reports_dir"], "quality_report.json").exists()
    assert Path(bundle["reports_dir"], "group_heatmaps.csv").exists()

    db_path = tmp_path / "workspace.sqlite"
    meta = {
        "operator_name": "feel",
        "active_branch_name": "main",
        "branding_profile": {"display_name": "Planora E2E"},
    }
    save_legacy_project(db_path, inst, result.schedule, meta=meta)
    inst2, schedule2, meta2 = load_legacy_project(db_path)
    summary = compare_schedule_sets(result.schedule, schedule2)
    assert summary["changed_time"] == 0
    assert summary["changed_room"] == 0
    assert meta2["operator_name"] == "feel"
    assert meta2["branding_profile"]["display_name"] == "Planora E2E"
    assert len(inst2.activities) == len(inst.activities)


def test_end_to_end_portfolio_and_support_bundle(tmp_path: Path):
    scenario = build_builtin_product_scenario("small_demo", name="Portfolio Demo")
    inst = compile_scenario_instance(scenario)

    portfolio = solve_portfolio(
        inst,
        SolveOptions(
            room_mode="greedy",
            use_objective=False,
            retry_without_objective=False,
            time_limit_seconds=10.0,
            workers=1,
        ),
    )
    assert portfolio.candidates
    assert portfolio.best_index >= 0
    assert portfolio.best is not None
    assert portfolio.best.result.schedule

    runtime_paths = default_runtime_paths("planora-e2e-tests")
    support_zip = tmp_path / "support_bundle.zip"
    bundle_path = collect_support_bundle(
        support_zip,
        runtime_paths=runtime_paths,
        settings={"telemetry_opt_in": False, "crash_reports_opt_in": False},
        metadata={"suite": "end_to_end"},
        extra_files={
            "workspace/portfolio.json": json.dumps(
                {
                    "best_index": portfolio.best_index,
                    "candidates": [candidate.name for candidate in portfolio.candidates],
                },
                indent=2,
            )
        },
    )
    assert Path(bundle_path).exists()
