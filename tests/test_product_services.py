from __future__ import annotations

from pathlib import Path

from product.model import ProductScenario
from product.rules import HARD_RULES, RULE_REGISTRY, SOFT_RULES
from services.compare_service import compare_schedule_sets
from services.contracts import SolveOptions
from services.scenario_service import (
    build_builtin_product_scenario,
    build_product_scenario_from_instance,
    compile_scenario_instance,
    load_product_scenario,
    save_product_scenario,
)
from services.solver_service import solve_instance
from utils.generator import generate_instance


EXPECTED_HARD_RULE_IDS = {
    "week1_lectures_only",
    "force_repeat_weekly_pattern",
    "enforce_course_totals",
    "enforce_block_professor_rules",
    "enforce_staff_daily_caps",
    "enforce_staff_weekly_caps",
    "enforce_room_availability",
    "enforce_travel_time_buffers",
    "enforce_building_closures",
    "enforce_calendar_rules",
    "enforce_precedence_rules",
}


def test_builtin_product_scenario_compiles_to_instance():
    scenario = build_builtin_product_scenario("small_demo", name="Planora demo")
    inst = compile_scenario_instance(scenario)

    assert getattr(inst, "product_metadata", {})["name"] == "Planora demo"
    assert len(inst.activities) > 0
    assert getattr(inst, "day_start_time", "") == scenario.calendar.day_start_time


def test_product_scenario_json_roundtrip(tmp_path: Path):
    scenario = build_builtin_product_scenario("small_demo", name="Roundtrip")
    scenario.constraints.objective_profile = "quality_first"
    scenario.constraints.precedence_rules = [
        {"before_activity_id": 1, "after_activity_id": 2, "min_gap_slots": 1}
    ]
    scenario.constraints.sla_targets = {"max_soft_penalty": 50}
    scenario.calendar.blackout_weeks = [11]
    scenario.calendar.holiday_dates = ["W2-MON"]
    scenario.resources.travel_buffers = {"cross_campus": 2}
    scenario.resources.closures = [{"campus": "MAIN", "building": "A", "week": 1}]
    path = tmp_path / "product_scenario.json"

    save_product_scenario(path, scenario)
    restored = load_product_scenario(path)

    assert isinstance(restored, ProductScenario)
    assert restored.metadata.name == "Roundtrip"
    assert restored.generation.mode == "small_demo"
    assert restored.constraints.objective_profile == "quality_first"
    assert restored.constraints.precedence_rules
    assert restored.constraints.sla_targets["max_soft_penalty"] == 50
    assert restored.calendar.blackout_weeks == [11]
    assert restored.calendar.holiday_dates == ["W2-MON"]
    assert restored.resources.travel_buffers["cross_campus"] == 2
    assert restored.resources.closures
    assert restored.feature_flags.get("versioned_projects") is True


def test_product_scenario_from_legacy_instance_compiles():
    inst = generate_instance("small_demo")
    scenario = build_product_scenario_from_instance(inst, name="Imported")
    compiled = compile_scenario_instance(scenario)

    assert len(compiled.activities) == len(inst.activities)
    assert getattr(compiled, "product_metadata", {})["name"] == "Imported"


def test_rule_registry_covers_hard_and_soft_rules():
    assert set(HARD_RULES.keys()).issubset(set(RULE_REGISTRY.keys()))
    assert set(SOFT_RULES.keys()).issubset(set(RULE_REGISTRY.keys()))
    assert EXPECTED_HARD_RULE_IDS.issubset(set(HARD_RULES.keys()))
    assert "stud_free_days" in SOFT_RULES


def test_solver_service_returns_feasible_schedule_for_small_demo():
    scenario = build_builtin_product_scenario("small_demo")
    inst = compile_scenario_instance(scenario)
    result = solve_instance(
        inst,
        SolveOptions(
            room_mode="greedy",
            use_objective=False,
            time_limit_seconds=20.0,
            workers=1,
            retry_without_objective=False,
        ),
    )

    assert result.is_feasible is True
    assert result.schedule
    assert result.hard_conflicts == []


def test_solver_service_uses_cache_for_identical_requests():
    scenario = build_builtin_product_scenario("small_demo")
    inst = compile_scenario_instance(scenario)
    options = SolveOptions(
        room_mode="greedy",
        use_objective=False,
        time_limit_seconds=20.0,
        workers=1,
        retry_without_objective=False,
    )
    first = solve_instance(inst, options)
    second = solve_instance(inst, options)

    assert first.is_feasible is True
    assert second.is_feasible is True
    assert second.meta.get("cached") is True


def test_compare_service_wraps_compare_logic():
    base = {
        1: {
            "week": 1,
            "day": "MON",
            "slot": 0,
            "duration": 1,
            "room_id": 1,
            "staff_id": 1,
            "course_id": 1,
            "group_ids": [1],
            "kind": "LEC",
        }
    }
    other = {
        1: {
            "week": 1,
            "day": "TUE",
            "slot": 0,
            "duration": 1,
            "room_id": 1,
            "staff_id": 1,
            "course_id": 1,
            "group_ids": [1],
            "kind": "LEC",
        }
    }
    summary = compare_schedule_sets(base, other)
    assert int(summary["changed_time"]) == 1
