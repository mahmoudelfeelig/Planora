from __future__ import annotations

from services.diagnostics_service import (
    build_unsat_rule_diagnosis,
    explain_candidate_slot,
)
from services.scenario_service import build_builtin_product_scenario, compile_scenario_instance
from services.solver_service import solve_instance
from services.contracts import SolveOptions
from utils.specs import validate_schedule_against_instance


def _solve_small():
    scenario = build_builtin_product_scenario("small_demo", name="Validation Demo")
    inst = compile_scenario_instance(scenario)
    result = solve_instance(
        inst,
        SolveOptions(
            room_mode="greedy",
            use_objective=False,
            retry_without_objective=False,
            time_limit_seconds=15.0,
            workers=1,
        ),
    )
    assert result.is_feasible is True
    assert result.schedule
    return inst, result.schedule


def test_valid_current_assignment_has_no_validation_errors():
    inst, schedule = _solve_small()
    errors = validate_schedule_against_instance(inst, schedule, strict_rooms=True)
    assert errors == []


def test_candidate_slot_explainer_matches_validation_for_invalid_move():
    inst, schedule = _solve_small()
    a_id = next(iter(schedule.keys()))
    current = schedule[a_id]
    invalid_slot = int(inst.slots_per_day)

    explained = explain_candidate_slot(
        inst,
        schedule,
        activity_id=int(a_id),
        week=int(current["week"]),
        day=str(current["day"]),
        slot=int(invalid_slot),
        room_id=int(current["room_id"]),
        staff_id=int(current["staff_id"]),
    )
    assert explained["valid"] is False
    assert explained["reasons"]

    mutated = {k: dict(v) for k, v in schedule.items()}
    mutated[a_id]["slot"] = int(invalid_slot)
    validation_errors = validate_schedule_against_instance(
        inst,
        mutated,
        strict_rooms=True,
    )
    assert validation_errors
    assert any(f"A{int(a_id)}" in str(reason) for reason in explained["reasons"])


def test_unsat_rule_diagnosis_surfaces_malformed_schedule_categories():
    inst, schedule = _solve_small()
    a_id = next(iter(schedule.keys()))
    broken = {k: dict(v) for k, v in schedule.items()}
    broken[a_id]["slot"] = int(inst.slots_per_day)
    broken[a_id]["staff_id"] = -1

    diagnosis = build_unsat_rule_diagnosis(inst, broken)
    rule_ids = {row["rule_id"] for row in diagnosis}
    assert diagnosis
    assert "slot_range" in rule_ids or "general_feasibility" in rule_ids
    assert "staff_availability" in rule_ids or "general_feasibility" in rule_ids
