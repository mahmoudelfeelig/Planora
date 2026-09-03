from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CALIBRATION = ROOT / "paper/evidence/giu_ss23_calibration.json"
DEFAULT_OUTPUT = ROOT / "paper/evidence/giu_extrapolated_planning_scenario.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_extrapolated_scenario(calibration_path: str | Path) -> dict[str, Any]:
    source = Path(calibration_path)
    calibration = json.loads(source.read_text(encoding="utf-8"))
    observed = dict(calibration["observed"])
    raw = dict(observed["raw_extraction"])
    calendar = dict(observed["calendar"])
    projection = dict(observed["current_import_projection"])
    source_events = int(projection["normalized_source_events"])
    week_count = int(calendar["week_count"])

    demand_scenarios = []
    for scenario_id, multiplier in (
        ("historical_volume", 1.0),
        ("planning_plus_10_percent", 1.1),
        ("stress_plus_20_percent", 1.2),
    ):
        demand_scenarios.append(
            {
                "scenario_id": scenario_id,
                "volume_multiplier": multiplier,
                "projected_scheduled_event_rows": round(source_events * multiplier),
                "interpretation": (
                    "workload-volume sensitivity only; not an enrollment or policy forecast"
                ),
            }
        )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "scenario_id": "giu_berlin_repository_extrapolation_2026",
        "generated_for_date": "2026-08-13",
        "classification": "repository_derived_research_extrapolation",
        "institution_approved": False,
        "current_giu_policy_claim": False,
        "source": {
            "path": source.resolve().relative_to(ROOT.resolve()).as_posix(),
            "sha256": _sha256(source),
            "calibration_id": calibration["calibration_id"],
            "source_snapshot_label": observed["snapshot_label"],
        },
        "preserved_observations": {
            "weeks": list(calendar["weeks"]),
            "days": list(calendar["days"]),
            "slot_grid": list(calendar["slot_grid"]),
            "major_labels": list(raw["major_labels"]),
            "course_text_label_count": int(raw["course_text_label_count"]),
            "normalized_source_events": source_events,
            "merged_activities": int(projection["merged_activities"]),
            "rooms_observed_or_placeholder_records": int(
                projection["modeled_room_records"]
            ),
        },
        "derived_capacity_indicators": {
            "scheduled_rows_per_teaching_week": round(source_events / week_count, 3),
            "scheduled_rows_by_day": dict(raw["day_counts"]),
            "scheduled_rows_by_week": dict(raw["week_counts"]),
            "slot_shares": {
                str(row["solver_index"]): float(row["raw_scheduled_share"])
                for row in calendar["slot_grid"]
            },
        },
        "demand_sensitivity_scenarios": demand_scenarios,
        "safe_solver_policy": {
            "room_mode": "partitioned",
            "objective_profile": "university_fast",
            "interactive_solve_limit_seconds": 15.0,
            "interactive_improve_limit_seconds": 2.0,
            "hard_constraints_preserved": [
                "room capacity",
                "room availability",
                "standard observed start slots",
            ],
            "not_enabled_without_authoritative_data": [
                "current calendar rules",
                "building closures",
                "travel buffers",
                "staff workload policy",
                "student demand uncertainty",
            ],
        },
        "sign_off": {
            "status": "institutional_signature_required",
            "required_protocol": "docs/GIU_INSTITUTIONAL_VALIDATION_PROTOCOL.md",
            "required_roles": list(
                calibration["publication_and_deployment_gates"][
                    "minimum_sign_off_roles"
                ]
            ),
            "decision": None,
            "approvers": [],
            "effective_term": None,
            "review_or_expiry_date": None,
        },
        "limitations": [
            "The source is a Spring 2023 historical timetable snapshot, not a current GIU system export.",
            "Volume multipliers are sensitivity cases, not forecasts of enrollment or institutional demand.",
            "Room capacities, staff constraints, student requests, accessibility needs, and current policy remain unconfirmed.",
            "Only an authorized GIU institutional decision can change institution_approved to true.",
        ],
    }
    payload["canonical_payload_sha256"] = _canonical_sha(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build an honest planning extrapolation from the GIU SS23 calibration."
    )
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_extrapolated_scenario(args.calibration)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output), "sha256": _sha256(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
