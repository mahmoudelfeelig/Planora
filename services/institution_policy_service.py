from __future__ import annotations

import copy
from typing import Any

from utils.domain import Instance


INSTITUTION_POLICY_PRESETS: dict[str, dict[str, Any]] = {
    "generic_research_university": {
        "label": "Generic research university",
        "objective_profile": "fairness_first",
        "hard_constraints": {
            "enforce_room_capacity": True,
            "enforce_room_availability": True,
            "enforce_calendar_rules": True,
            "enforce_building_closures": True,
            "enforce_travel_time_buffers": True,
            "enforce_standard_start_slots": False,
        },
        "demand_policy": {"mode": "nominal"},
        "institutional_policy": {
            "policy_id": "generic_research_university",
            "evidence_status": "portable baseline; configure locally before production use",
            "prime_time": {
                "days": ["MON", "TUE", "WED", "THU", "FRI"],
                "slots": [1, 2, 3],
                "share_cap": 0.70,
            },
            "room_target_fill": 0.80,
            "staged_solve": ["large_shared_courses", "departments", "specialized_labs"],
        },
    },
    "north_american_balanced": {
        "label": "North American balanced-grid research preset",
        "objective_profile": "fairness_first",
        "hard_constraints": {
            "enforce_room_capacity": True,
            "enforce_room_availability": True,
            "enforce_calendar_rules": True,
            "enforce_travel_time_buffers": True,
            "enforce_standard_start_slots": True,
        },
        "demand_policy": {"mode": "quantile", "service_level": 0.90},
        "institutional_policy": {
            "policy_id": "north_american_balanced",
            "evidence_status": "research abstraction from published university policies, not an official institution preset",
            "standard_start_slots": [0, 1, 2, 3, 4],
            "prime_time": {
                "days": ["MON", "TUE", "WED", "THU", "FRI"],
                "slots": [1, 2, 3],
                "share_cap": 0.70,
            },
            "room_target_fill": 0.80,
            "freeze_after_registration": True,
            "staged_solve": ["large_shared_courses", "departments", "specialized_labs"],
        },
    },
    "giu_target": {
        "label": "GIU Berlin historical research preset",
        "objective_profile": "fairness_first",
        "hard_constraints": {
            "enforce_room_capacity": True,
            "enforce_room_availability": True,
            "enforce_calendar_rules": False,
            "enforce_building_closures": False,
            "enforce_travel_time_buffers": False,
            "enforce_standard_start_slots": True,
        },
        "demand_policy": {"mode": "nominal"},
        "institutional_policy": {
            "policy_id": "giu_target",
            "evidence_status": "partially calibrated against a local GIU Berlin Spring 2023 timetable snapshot; historical, not institution-approved, and not validated as current policy",
            "standard_start_slots": [0, 1, 2, 3, 4],
            "standard_start_slots_evidence": "all extracted scheduled cells use the five displayed starts; this does not establish current-policy exclusivity",
            "historical_calendar_snapshot": {
                "label": "Berlin Campus Spring Semester 2023",
                "weeks": list(range(1, 13)),
                "days": ["MON", "TUE", "WED", "THU", "FRI", "SAT"],
                "time_labels": [
                    "08:30 - 10:00",
                    "10:30 - 12:00",
                    "12:15 - 13:45",
                    "14:15 - 15:45",
                    "16:00 - 17:30",
                ],
                "source_sha256": "217e8a08bcf525a38df6200161b361a3135b6962f0393026764780ebfb38d395",
                "authority": "historical local snapshot only",
            },
            "calibration_artifact": "paper/evidence/giu_ss23_calibration.json",
            "institutional_validation_protocol": "docs/GIU_INSTITUTIONAL_VALIDATION_PROTOCOL.md",
            "known_missing_evidence": [
                "current academic calendar and scheduling policy",
                "room capacities, types, accessibility, buildings, and travel times",
                "staff identities, availability, qualifications, and workload limits",
                "student enrollment, sectioning choices, and demand uncertainty",
                "approved prime-time, fairness, and room-utilization targets",
            ],
        },
    },
}


def list_institution_policy_presets() -> list[dict[str, str]]:
    return [
        {"id": preset_id, "label": str(payload["label"])}
        for preset_id, payload in INSTITUTION_POLICY_PRESETS.items()
    ]


def institution_policy_catalog() -> list[dict[str, Any]]:
    """Return administrator-safe policy metadata and the applied defaults."""
    return [
        {
            "id": preset_id,
            "label": str(payload["label"]),
            "objective_profile": str(payload.get("objective_profile") or "balanced"),
            "evidence_status": str(
                dict(payload.get("institutional_policy") or {}).get(
                    "evidence_status",
                    "configure locally before production use",
                )
            ),
            "demand_policy": copy.deepcopy(payload.get("demand_policy") or {}),
            "hard_constraints": copy.deepcopy(payload.get("hard_constraints") or {}),
            "institutional_policy": copy.deepcopy(
                payload.get("institutional_policy") or {}
            ),
        }
        for preset_id, payload in INSTITUTION_POLICY_PRESETS.items()
    ]


def institution_policy_preset(preset_id: str) -> dict[str, Any]:
    key = str(preset_id or "").strip().lower().replace("-", "_")
    aliases = {"generic": "generic_research_university", "giu": "giu_target"}
    key = aliases.get(key, key)
    if key not in INSTITUTION_POLICY_PRESETS:
        raise KeyError(f"Unknown institution policy preset: {preset_id}")
    return copy.deepcopy(INSTITUTION_POLICY_PRESETS[key])


def apply_institution_policy(
    inst: Instance,
    preset: str | dict[str, Any],
    *,
    in_place: bool = False,
) -> Instance:
    target = inst if in_place else copy.deepcopy(inst)
    payload = institution_policy_preset(preset) if isinstance(preset, str) else copy.deepcopy(preset)
    target.hard_constraints = {
        **dict(getattr(target, "hard_constraints", {}) or {}),
        **dict(payload.get("hard_constraints", {}) or {}),
    }
    target.soft_weights = {
        **dict(getattr(target, "soft_weights", {}) or {}),
        **dict(payload.get("soft_weights", {}) or {}),
    }
    target.demand_policy = {
        **dict(getattr(target, "demand_policy", {}) or {}),
        **dict(payload.get("demand_policy", {}) or {}),
    }
    target.institutional_policy = {
        **dict(getattr(target, "institutional_policy", {}) or {}),
        **dict(payload.get("institutional_policy", {}) or {}),
    }
    target.sla_targets = {
        **dict(getattr(target, "sla_targets", {}) or {}),
        **dict(payload.get("sla_targets", {}) or {}),
    }
    if payload.get("objective_profile"):
        target.objective_profile = str(payload["objective_profile"])
    return target
