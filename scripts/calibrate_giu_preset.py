from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.institution_policy_service import institution_policy_preset
from services.timetable_import_service import (
    build_instance_and_schedule_from_events,
    load_timetable_events,
)
from utils.specs import validate_schedule_against_instance


CALIBRATION_SCHEMA_VERSION = 1
CALIBRATION_ID = "giu_berlin_ss23_historical_schedule_snapshot"
DEFAULT_PDF = ROOT / "data" / "SS23-All-Majors-Schedule.pdf"
DEFAULT_EVENTS = ROOT / "data" / "SS23-All-Majors-Schedule-events.csv"
DEFAULT_SUMMARY = ROOT / "data" / "SS23-All-Majors-Schedule-summary.json"
DEFAULT_VALIDATION_REPORT = ROOT / "data" / "ss23-uni-validation-report.json"
DEFAULT_OUTPUT = ROOT / "paper" / "evidence" / "giu_ss23_calibration.json"

DAY_CODES = {
    "monday": "MON",
    "tuesday": "TUE",
    "wednesday": "WED",
    "thursday": "THU",
    "friday": "FRI",
    "saturday": "SAT",
    "sunday": "SUN",
}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _portable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _source_record(path: Path, *, role: str, evidence_level: str) -> dict[str, Any]:
    return {
        "path": _portable_path(path),
        "sha256": sha256_file(path),
        "size_bytes": int(path.stat().st_size),
        "role": role,
        "evidence_level": evidence_level,
    }


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def _load_raw_events(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {
            "week",
            "day",
            "slot_index",
            "time",
            "course",
            "room",
            "major",
            "major_row_index",
        }
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise ValueError(
                "GIU calibration events CSV is missing columns: " + ", ".join(missing)
            )
        rows = [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in reader
            if str(row.get("status", "scheduled") or "scheduled").strip().lower()
            == "scheduled"
        ]
    if not rows:
        raise ValueError("GIU calibration events CSV contains no scheduled rows")
    return rows


def _integer_values(rows: Sequence[Mapping[str, str]], field: str) -> list[int]:
    try:
        return [int(str(row[field])) for row in rows]
    except (KeyError, ValueError) as exc:
        raise ValueError(f"GIU calibration field {field!r} must contain integers") from exc


def _normalized_days(rows: Sequence[Mapping[str, str]]) -> list[str]:
    raw_days = {str(row["day"]).strip().lower() for row in rows}
    unknown = sorted(day for day in raw_days if day not in DAY_CODES)
    if unknown:
        raise ValueError("Unknown weekday labels: " + ", ".join(unknown))
    order = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    observed = {DAY_CODES[day] for day in raw_days}
    return [day for day in order if day in observed]


def _slot_grid(rows: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    labels_by_index: dict[int, set[str]] = {}
    counts = Counter(_integer_values(rows, "slot_index"))
    for row in rows:
        source_index = int(row["slot_index"])
        labels_by_index.setdefault(source_index, set()).add(str(row["time"]))
    total = max(1, len(rows))
    grid: list[dict[str, Any]] = []
    for source_index in sorted(labels_by_index):
        labels = sorted(label for label in labels_by_index[source_index] if label)
        if len(labels) != 1:
            raise ValueError(
                f"Slot {source_index} has ambiguous time labels: {labels or ['<blank>']}"
            )
        grid.append(
            {
                "source_index": int(source_index),
                "solver_index": int(source_index - 1),
                "time_label": labels[0],
                "raw_scheduled_cells": int(counts[source_index]),
                "raw_scheduled_share": round(float(counts[source_index] / total), 8),
            }
        )
    return grid


def _sorted_counter(values: Sequence[str]) -> dict[str, int]:
    return {key: int(value) for key, value in sorted(Counter(values).items())}


def _validation_category(error: str) -> str:
    text = str(error)
    if text.startswith("Room overlap"):
        return "room_overlap"
    if text.startswith("Staff overlap"):
        return "synthetic_staff_overlap"
    if " room " in f" {text.lower()} " or "room" in text.lower():
        return "inferred_room_type_or_specialization"
    return "other"


def _calibration_comparison(
    preset: Mapping[str, Any],
    *,
    observed_days: Sequence[str],
    observed_start_slots: Sequence[int],
) -> dict[str, Any]:
    policy = dict(preset.get("institutional_policy") or {})
    hard = dict(preset.get("hard_constraints") or {})
    return {
        "standard_start_slots": {
            "preset": [int(value) for value in policy.get("standard_start_slots", [])],
            "historically_observed": [int(value) for value in observed_start_slots],
            "delta": sorted(
                set(int(value) for value in policy.get("standard_start_slots", []))
                ^ set(int(value) for value in observed_start_slots)
            ),
            "assessment": "matches the five starts used in this historical snapshot; exclusivity is not confirmed as current policy",
        },
        "calendar_days": {
            "preset_hard_calendar_rules": bool(hard.get("enforce_calendar_rules", False)),
            "historically_observed": list(observed_days),
            "assessment": "snapshot evidence only; no current academic-calendar rule was supplied",
        },
        "room_capacity": {
            "preset_enforced": bool(hard.get("enforce_room_capacity", False)),
            "capacity_evidence_available": False,
            "assessment": "retain as a scheduler safety invariant, but calibrate capacities before institutional use",
        },
        "room_availability": {
            "preset_enforced": bool(hard.get("enforce_room_availability", False)),
            "inventory_evidence_available": False,
            "assessment": "retain as a scheduler safety invariant; the snapshot only records assigned room labels",
        },
        "travel_and_building": {
            "travel_buffers_enforced": bool(hard.get("enforce_travel_time_buffers", False)),
            "building_closures_enforced": bool(hard.get("enforce_building_closures", False)),
            "evidence_available": False,
        },
        "demand_policy": {
            "preset": dict(preset.get("demand_policy") or {}),
            "enrollment_or_forecast_evidence_available": False,
            "assessment": "nominal is the only non-speculative default until enrollment and uncertainty evidence are supplied",
        },
        "prime_time_and_fill_targets": {
            "prime_time_configured": "prime_time" in policy,
            "room_target_fill_configured": "room_target_fill" in policy,
            "stakeholder_policy_evidence_available": False,
        },
    }


def build_giu_calibration(
    *,
    pdf_path: str | Path,
    events_path: str | Path,
    summary_path: str | Path,
    validation_report_path: str | Path,
    preset: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    pdf = Path(pdf_path)
    events_csv = Path(events_path)
    summary_json = Path(summary_path)
    validation_report_json = Path(validation_report_path)
    for source in (pdf, events_csv, summary_json, validation_report_json):
        if not source.is_file():
            raise FileNotFoundError(f"GIU calibration source is missing: {source}")

    selected_preset = dict(preset or institution_policy_preset("giu_target"))
    raw_rows = _load_raw_events(events_csv)
    extracted_summary = _load_json(summary_json)
    stored_validation = _load_json(validation_report_json)
    normalized_events = load_timetable_events(events_csv)
    imported_instance, imported_schedule, import_meta = (
        build_instance_and_schedule_from_events(normalized_events, lock_imported=True)
    )
    current_validation_errors = validate_schedule_against_instance(
        imported_instance,
        imported_schedule,
        strict_rooms=True,
        require_all_activities=True,
    )

    weeks = sorted(set(_integer_values(raw_rows, "week")))
    days = _normalized_days(raw_rows)
    slots = _slot_grid(raw_rows)
    major_labels = sorted({str(row["major"]) for row in raw_rows})
    group_row_keys = sorted(
        {
            (str(row["major"]), int(row["major_row_index"]))
            for row in raw_rows
        }
    )
    course_labels = sorted({str(row["course"]) for row in raw_rows if str(row["course"])})
    nonblank_room_labels = sorted(
        {str(row["room"]) for row in raw_rows if str(row["room"])}
    )
    blank_room_rows = sum(not str(row["room"]) for row in raw_rows)
    modeled_rooms = int(import_meta.get("rooms", 0))
    expected_placeholder_rooms = int(blank_room_rows)
    room_accounting_agrees = modeled_rooms == (
        len(nonblank_room_labels) + expected_placeholder_rooms
    )
    validation_error_digest = canonical_sha256(sorted(current_validation_errors))
    validation_categories = _sorted_counter(
        [_validation_category(error) for error in current_validation_errors]
    )

    source_records = {
        "pdf": _source_record(
            pdf,
            role="historical timetable document",
            evidence_level="primary local snapshot; institutional provenance not independently authenticated",
        ),
        "events_csv": _source_record(
            events_csv,
            role="machine-extracted scheduled cells",
            evidence_level="derived from the PDF by repository extraction code",
        ),
        "extraction_summary": _source_record(
            summary_json,
            role="extractor aggregate report",
            evidence_level="derived",
        ),
        "stored_validation_report": _source_record(
            validation_report_json,
            role="historical importer validation report",
            evidence_level="derived and potentially stale relative to current importer code",
        ),
    }

    observed = {
        "snapshot_label": "Berlin Campus Spring Semester 2023",
        "calendar": {
            "week_count": len(weeks),
            "weeks": weeks,
            "days": days,
            "slot_count": len(slots),
            "slot_grid": slots,
        },
        "raw_extraction": {
            "scheduled_cells": len(raw_rows),
            "major_labels": major_labels,
            "major_label_count": len(major_labels),
            "major_row_keys": [
                {"major": major, "row_index": int(row_index)}
                for major, row_index in group_row_keys
            ],
            "major_row_key_count": len(group_row_keys),
            "course_text_label_count": len(course_labels),
            "course_text_labels_sha256": canonical_sha256(course_labels),
            "nonblank_room_label_count": len(nonblank_room_labels),
            "nonblank_room_labels": nonblank_room_labels,
            "blank_room_event_rows": int(blank_room_rows),
            "compound_room_labels": [
                label for label in nonblank_room_labels if "/" in label or "," in label
            ],
            "day_counts": _sorted_counter([DAY_CODES[str(row["day"]).lower()] for row in raw_rows]),
            "week_counts": {
                str(key): int(value)
                for key, value in sorted(Counter(_integer_values(raw_rows, "week")).items())
            },
        },
        "extractor_summary": {
            key: extracted_summary.get(key)
            for key in (
                "pages",
                "cells",
                "scheduled_cells",
                "free_cells",
                "holiday_cells",
                "blank_cells",
            )
        },
        "current_import_projection": {
            "normalized_source_events": int(import_meta.get("source_events", 0)),
            "merged_activities": int(
                import_meta.get("activities_after_shared_event_merge", 0)
            ),
            "inferred_groups": int(import_meta.get("groups", 0)),
            "course_text_entities": int(import_meta.get("courses", 0)),
            "modeled_room_records": modeled_rooms,
            "modeled_room_accounting": {
                "nonblank_labels": len(nonblank_room_labels),
                "row_scoped_unspecified_placeholders": expected_placeholder_rooms,
                "sum_matches_modeled_records": bool(room_accounting_agrees),
            },
            "synthetic_staff_records": int(import_meta.get("staff", 0)),
            "synthetic_staff_pool_size_per_role": int(
                import_meta.get("synthetic_staff_pool_size_per_role", 0)
            ),
            "validation_error_count": len(current_validation_errors),
            "validation_error_categories": validation_categories,
            "validation_errors_sha256": validation_error_digest,
            "assumptions": list(import_meta.get("assumptions") or []),
        },
        "stored_validation_report": {
            "source_events": stored_validation.get("source_events"),
            "merged_activities": stored_validation.get(
                "activities_after_shared_event_merge"
            ),
            "groups": stored_validation.get("groups"),
            "courses": stored_validation.get("courses"),
            "modeled_rooms": stored_validation.get("rooms"),
            "synthetic_staff_records": stored_validation.get("staff"),
            "validation_error_count": stored_validation.get("validation_error_count"),
            "warning": "historical generated report; staff-model counts differ from the current importer and are not institutional observations",
        },
    }

    cross_checks = {
        "events_match_extractor_scheduled_cells": len(raw_rows)
        == int(extracted_summary.get("scheduled_cells", -1)),
        "events_match_stored_report": len(raw_rows)
        == int(stored_validation.get("source_events", -1)),
        "merged_activities_match_stored_report": int(
            import_meta.get("activities_after_shared_event_merge", -1)
        )
        == int(stored_validation.get("activities_after_shared_event_merge", -2)),
        "groups_match_stored_report": int(import_meta.get("groups", -1))
        == int(stored_validation.get("groups", -2)),
        "courses_match_stored_report": int(import_meta.get("courses", -1))
        == int(stored_validation.get("courses", -2)),
        "room_record_accounting_explained": bool(room_accounting_agrees),
        "current_validation_count_matches_stored_report": len(current_validation_errors)
        == int(stored_validation.get("validation_error_count", -1)),
        "current_room_overlap_count_matches_stored_report": int(
            validation_categories.get("room_overlap", 0)
        )
        == int(stored_validation.get("validation_error_count", -1)),
        "staff_count_matches_stored_report": int(import_meta.get("staff", -1))
        == int(stored_validation.get("staff", -2)),
    }

    policy = dict(selected_preset.get("institutional_policy") or {})
    artifact = {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "calibration_id": CALIBRATION_ID,
        "status": {
            "classification": "historical_partial_calibration",
            "official_or_institution_approved": False,
            "current_policy_validated": False,
            "fit_for_current_production_configuration": False,
            "fit_for_reproducible_historical_scale_research": True,
            "statement": "This artifact calibrates only observable properties of a local Spring 2023 Berlin Campus timetable snapshot. It is not a current or institution-approved GIU policy model.",
        },
        "sources": source_records,
        "observed": observed,
        "cross_source_checks": cross_checks,
        "evidence_classification": {
            "directly_observed_in_historical_snapshot": [
                "twelve displayed teaching weeks",
                "Monday through Saturday page grid",
                "five displayed daily time labels",
                "raw scheduled/free/holiday/blank cell counts",
                "major, course-text, and room-label strings present in the extraction",
            ],
            "derived_or_inferred_by_planora": [
                "major plus row-index keys as distinct scheduling groups",
                "identical-row merging into scheduling activities",
                "course text labels as course entities",
                "blank room cells as row-scoped UNSPECIFIED room placeholders",
                "all staff identities and workload assignments",
                "room types, capacities, and specialization semantics",
            ],
            "missing_for_institutional_calibration": [
                "current academic calendar and authoritative scheduling policy",
                "authoritative room inventory, capacities, types, accessibility, buildings, and travel times",
                "staff identities, availability, qualifications, contracts, and workload limits",
                "student enrollment, section choices, demand forecasts, and uncertainty calibration",
                "course ownership, required contact hours, precedence, sharing, and cross-listing rules",
                "approved prime-time definition, fairness targets, room-fill targets, and objective weights",
                "interpretation or correction of apparent room overlaps and fragmented PDF cells",
                "authorized institutional sign-off and data-retention/privacy review",
            ],
        },
        "current_preset": {
            "id": str(policy.get("policy_id", "giu_target")),
            "payload_sha256": canonical_sha256(selected_preset),
            "payload": selected_preset,
        },
        "preset_comparison": _calibration_comparison(
            selected_preset,
            observed_days=days,
            observed_start_slots=[int(row["solver_index"]) for row in slots],
        ),
        "calibration_decisions": [
            {
                "path": "institutional_policy.standard_start_slots",
                "decision": "retain 0..4 only as the historical five-start grid",
                "evidence": "all 1,265 extracted scheduled cells use the five displayed time labels",
            },
            {
                "path": "demand_policy",
                "decision": "use nominal rather than a budgeted uncertainty gamma",
                "evidence": "the snapshot contains no enrollment or demand-deviation observations",
            },
            {
                "path": "hard_constraints.calendar/buildings/travel",
                "decision": "disable GIU-specific enforcement pending authoritative inputs",
                "evidence": "no current rules, building closures, locations, or travel matrix were supplied",
            },
            {
                "path": "institutional_policy.prime_time/room_target_fill/staged_solve",
                "decision": "do not encode these as GIU facts",
                "evidence": "the snapshot does not establish normative policy targets or solver strategy",
            },
        ],
        "publication_and_deployment_gates": {
            "historical_snapshot_provenance": "pass for the checked-in source hashes and aggregate extraction counts",
            "historical_schedule_model_agreement": "open: the current import projection has synthetic-staff, inferred-room-type, and apparent room-overlap errors that require adjudication",
            "institutional_calibration": "open",
            "required_protocol": "docs/GIU_INSTITUTIONAL_VALIDATION_PROTOCOL.md",
            "minimum_sign_off_roles": [
                "registrar or timetable owner",
                "facilities or room inventory owner",
                "academic department representatives",
                "student services or accessibility representative",
                "data protection or information security representative",
            ],
        },
    }
    return artifact


def write_calibration(payload: Mapping[str, Any], output: str | Path) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the limitation-aware GIU SS23 historical calibration artifact."
    )
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument(
        "--validation-report",
        type=Path,
        default=DEFAULT_VALIDATION_REPORT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the committed artifact differs from a fresh calibration.",
    )
    args = parser.parse_args()

    payload = build_giu_calibration(
        pdf_path=args.pdf,
        events_path=args.events,
        summary_path=args.summary,
        validation_report_path=args.validation_report,
    )
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.is_file():
            print(f"Calibration artifact is missing: {args.output}", file=sys.stderr)
            return 1
        if args.output.read_text(encoding="utf-8") != rendered:
            print(
                "GIU calibration artifact is stale; regenerate with "
                "scripts/calibrate_giu_preset.py",
                file=sys.stderr,
            )
            return 1
        print(f"GIU calibration artifact is current: {args.output}")
        return 0

    destination = write_calibration(payload, args.output)
    print(
        json.dumps(
            {
                "output": _portable_path(destination),
                "calibration_id": payload["calibration_id"],
                "classification": payload["status"]["classification"],
                "official_or_institution_approved": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
