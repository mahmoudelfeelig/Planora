from __future__ import annotations

from services.performance_service import (
    build_decomposition_plan,
    build_feasibility_certificate,
    estimate_cp_model_scale,
    recommend_solver_profile,
)
from utils.generator import generate_instance


def test_performance_service_recommends_university_fast_for_ss23_scale():
    inst = generate_instance("ss23_uni_like")

    scale = estimate_cp_model_scale(inst)
    recommendation = recommend_solver_profile(inst)
    certificate = build_feasibility_certificate(inst)

    assert scale["activities"] == 1621
    assert scale["estimated_cp_room_candidates"] >= 50000
    assert recommendation["profile"] == "university_fast"
    assert recommendation["room_mode"] == "greedy"
    assert certificate["room_missing"] == []
    assert certificate["decomposition"]["week_blocks"]


def test_decomposition_plan_reports_week_and_program_blocks():
    inst = generate_instance("small_demo")

    plan = build_decomposition_plan(inst)

    assert plan["recommended_order"] == [
        "solve_or_relax_by_week",
        "room_assignment_by_slot",
        "repair_cross_program_staff_conflicts",
        "local_search_quality_pass",
    ]
    assert len(plan["week_blocks"]) == len(inst.weeks)
    assert plan["program_blocks"]
