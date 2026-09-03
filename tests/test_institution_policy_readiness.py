from __future__ import annotations

from services.institution_policy_readiness_service import (
    evaluate_institution_policy_readiness,
)
from services.institution_policy_service import apply_institution_policy
from utils.domain import DistributionConstraint
from utils.generator import generate_instance


def _check(report: dict, check_id: str) -> dict:
    return next(row for row in report["checks"] if row["id"] == check_id)


def test_generic_policy_reports_missing_semantics_instead_of_false_readiness() -> None:
    inst = apply_institution_policy(generate_instance("small_demo", seed=3), "generic")
    inst.calendar_rules = {}
    inst.room_closures = []
    inst.travel_time_rules = {}

    report = evaluate_institution_policy_readiness(inst)

    assert report["research_semantics_ready"] is False
    assert report["institutional_use_ready"] is False
    assert _check(report, "calendar_rules")["status"] == "missing"
    assert _check(report, "building_closures")["status"] == "missing"
    assert _check(report, "travel_time_buffers")["status"] == "missing"
    assert _check(report, "prime_time")["enforcement"] == "diagnostic_only"


def test_giu_historical_policy_separates_solver_semantics_from_signoff() -> None:
    inst = apply_institution_policy(generate_instance("small_demo", seed=5), "giu_target")

    report = evaluate_institution_policy_readiness(inst)

    assert _check(report, "standard_start_slots")["status"] == "pass"
    assert _check(report, "calendar_rules")["status"] == "not_enabled"
    assert _check(report, "institution_evidence")["status"] == "missing"
    assert report["institutional_use_ready"] is False


def test_forecast_policy_requires_scenario_coverage_for_active_groups() -> None:
    inst = generate_instance("small_demo", seed=7)
    inst.demand_policy = {"mode": "quantile", "service_level": 0.9}
    for group in inst.groups.values():
        group.demand_scenarios = {}

    report = evaluate_institution_policy_readiness(inst)

    check = _check(report, "demand_scenarios")
    assert check["status"] == "missing"
    assert check["details"]["coverage"] == 0.0


def test_unsupported_hard_distribution_rule_is_an_explicit_blocker() -> None:
    inst = generate_instance("small_demo", seed=9)
    activity_ids = sorted(inst.activities)[:2]
    inst.distribution_constraints = [
        DistributionConstraint(
            id="hard-breaks",
            constraint_type="MaxBreaks(1)",
            activity_ids=activity_ids,
            required=True,
        )
    ]

    report = evaluate_institution_policy_readiness(inst)

    check = _check(report, "distribution_constraints")
    assert check["status"] == "unsupported"
    assert check["details"]["hard_cp_unsupported_ids"] == ["hard-breaks"]
    assert report["research_semantics_ready"] is False
