from __future__ import annotations

from pathlib import Path

from ortools.sat.python import cp_model

from benchmarks.itc2007 import (
    convert_itc2007_to_instance,
    parse_itc2007_ctt,
    score_itc2007_schedule,
)
from core.solver_cp_sat import TimetableSolver
from services.institution_policy_service import apply_institution_policy
from services.research_metrics_service import evaluate_research_metrics
from services.scenario_service import (
    build_product_scenario_from_instance,
    compile_scenario_instance,
)
from utils.distribution_constraints import (
    distribution_penalty,
    evaluate_distribution_constraints,
)
from utils.domain import DistributionConstraint
from utils.generator import generate_instance
from utils.specs import validate_schedule_against_instance


ITC_SAMPLE = """\
Name: score-toy
Courses: 2
Rooms: 2
Days: 2
Periods_per_day: 2
Curricula: 1
Constraints: 0
COURSES:
C1 T1 2 2 25
C2 T2 1 1 20
ROOMS:
R1 10
R2 30
CURRICULA:
CUR1 2 C1 C2
UNAVAILABILITY_CONSTRAINTS:
END.
"""


def test_distribution_evaluator_handles_pair_aggregate_and_soft_penalty() -> None:
    inst = generate_instance("small_demo", seed=7)
    activity_ids = sorted(inst.activities)[:3]
    schedule = {
        activity_ids[0]: {"week": 1, "day": "MON", "slot": 0, "duration": 1, "room_id": 1},
        activity_ids[1]: {"week": 1, "day": "MON", "slot": 2, "duration": 1, "room_id": 1},
        activity_ids[2]: {"week": 1, "day": "TUE", "slot": 0, "duration": 1, "room_id": 2},
    }
    inst.distribution_constraints = [
        DistributionConstraint("gap", "MinGap(3)", activity_ids[:2], required=True),
        DistributionConstraint(
            "days",
            "MaxDays(1)",
            activity_ids,
            required=False,
            penalty=11,
        ),
    ]
    violations = evaluate_distribution_constraints(inst, schedule)
    assert {(row.constraint_id, row.units) for row in violations} == {("gap", 1), ("days", 1)}
    assert distribution_penalty(inst, schedule) == 11


def test_required_time_and_room_distribution_constraints_are_solved_exactly() -> None:
    inst = generate_instance("small_demo", seed=1)
    by_course: dict[int, list[int]] = {}
    for activity_id, activity in inst.activities.items():
        if activity.kind == "LEC":
            by_course.setdefault(int(activity.course_id), []).append(int(activity_id))
    candidates = [
        values
        for values in by_course.values()
        if len({inst.activities[value].week for value in values}) >= 2
    ]
    left, right = sorted(candidates[0], key=lambda value: inst.activities[value].week)[:2]
    inst.distribution_constraints = [
        DistributionConstraint("start", "SameStart", [left, right], required=True),
        DistributionConstraint("room", "SameRoom", [left, right], required=True),
    ]
    model = TimetableSolver(inst, room_mode="decomposed", use_objective=False)
    solver, status = model.solve(time_limit_seconds=10, workers=1, random_seed=9)
    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    schedule = model.extract_solution(solver)
    assert schedule[left]["slot"] == schedule[right]["slot"]
    assert schedule[left]["room_id"] == schedule[right]["room_id"]
    assert evaluate_distribution_constraints(inst, schedule, required_only=True) == []


def test_giu_policy_is_explicitly_research_status_and_roundtrip_safe() -> None:
    inst = apply_institution_policy(generate_instance("small_demo", seed=2), "giu_target")
    assert inst.institutional_policy["policy_id"] == "giu_target"
    assert "validate" in inst.institutional_policy["evidence_status"].lower()
    assert inst.demand_policy == {"mode": "nominal"}
    assert inst.hard_constraints["enforce_standard_start_slots"] is True
    assert inst.hard_constraints["enforce_travel_time_buffers"] is False
    assert "historical" in inst.institutional_policy["evidence_status"].lower()
    assert "prime_time" not in inst.institutional_policy

    inst.distribution_constraints = [
        DistributionConstraint("portable", "DifferentDays", [1, 2], required=False, penalty=3)
    ]
    restored = compile_scenario_instance(build_product_scenario_from_instance(inst))
    assert restored.demand_policy == inst.demand_policy
    assert restored.institutional_policy == inst.institutional_policy
    assert restored.distribution_constraints == inst.distribution_constraints


def test_itc2007_official_soft_score_components(tmp_path: Path) -> None:
    source = tmp_path / "score.ctt"
    source.write_text(ITC_SAMPLE, encoding="utf-8")
    problem = parse_itc2007_ctt(source)
    inst = convert_itc2007_to_instance(problem)
    c1 = [activity_id for activity_id, activity in inst.activities.items() if activity.course_id == 1]
    c2 = [activity_id for activity_id, activity in inst.activities.items() if activity.course_id == 2]
    schedule = {
        c1[0]: {"week": 1, "day": "D0", "slot": 1, "duration": 1, "room_id": 1},
        c1[1]: {"week": 1, "day": "D1", "slot": 0, "duration": 1, "room_id": 2},
        c2[0]: {"week": 1, "day": "D0", "slot": 0, "duration": 1, "room_id": 2},
    }
    score = score_itc2007_schedule(problem, inst, schedule)
    assert score.to_dict() == {
        "room_capacity": 15,
        "minimum_working_days": 0,
        "curriculum_compactness": 2,
        "room_stability": 1,
        "total": 18,
    }


def test_research_metrics_are_portable_and_self_identifying() -> None:
    inst = apply_institution_policy(generate_instance("small_demo", seed=8), "generic")
    model = TimetableSolver(inst, room_mode="decomposed", use_objective=False)
    solver, status = model.solve(time_limit_seconds=10, workers=1, random_seed=3)
    assert int(status) in {int(cp_model.FEASIBLE), int(cp_model.OPTIMAL)}
    schedule = model.extract_solution(solver)
    assert validate_schedule_against_instance(inst, schedule, require_all_activities=True) == []
    metrics = evaluate_research_metrics(inst, schedule)
    assert len(metrics["instance_fingerprint"]) == 64
    assert metrics["completeness"] == 1.0
    assert metrics["hard_conflict_count"] == 0
    assert metrics["scale"]["activities"] == len(inst.activities)
