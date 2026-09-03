from __future__ import annotations

import json

from scripts.extrapolate_giu_profile import (
    DEFAULT_CALIBRATION,
    DEFAULT_OUTPUT,
    build_extrapolated_scenario,
)


def test_giu_extrapolation_is_deterministic_and_not_mislabeled():
    first = build_extrapolated_scenario(DEFAULT_CALIBRATION)
    second = build_extrapolated_scenario(DEFAULT_CALIBRATION)

    assert first == second
    assert first["institution_approved"] is False
    assert first["current_giu_policy_claim"] is False
    assert first["sign_off"]["status"] == "institutional_signature_required"
    assert first["preserved_observations"]["normalized_source_events"] == 1265
    assert [row["volume_multiplier"] for row in first["demand_sensitivity_scenarios"]] == [
        1.0,
        1.1,
        1.2,
    ]


def test_checked_in_giu_extrapolation_matches_generator():
    assert json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8")) == (
        build_extrapolated_scenario(DEFAULT_CALIBRATION)
    )
