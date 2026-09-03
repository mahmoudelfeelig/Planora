from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.calibrate_giu_preset import (
    CALIBRATION_ID,
    DEFAULT_EVENTS,
    DEFAULT_OUTPUT,
    DEFAULT_PDF,
    DEFAULT_SUMMARY,
    DEFAULT_VALIDATION_REPORT,
    build_giu_calibration,
    canonical_sha256,
)
from services.institution_policy_service import institution_policy_preset


def _write_synthetic_sources(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    pdf = tmp_path / "schedule.pdf"
    pdf.write_bytes(b"synthetic calibration fixture\n")
    events = tmp_path / "events.csv"
    events.write_text(
        "source_page,week,date_range,day,major,major_row_index,slot_index,time,course,room,status\n"
        "1,1,01.01.-06.01.,Monday,Major A,1,1,08:30 - 10:00,C1 - Course,R1,scheduled\n"
        "2,1,01.01.-06.01.,Monday,Major B,2,1,08:30 - 10:00,C1 - Course,R1,scheduled\n"
        "3,2,08.01.-13.01.,Tuesday,Major A,1,2,10:30 - 12:00,C1 - Course,,scheduled\n",
        encoding="utf-8",
    )
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "pages": 3,
                "cells": 10,
                "scheduled_cells": 3,
                "free_cells": 5,
                "holiday_cells": 1,
                "blank_cells": 1,
            }
        ),
        encoding="utf-8",
    )
    report = tmp_path / "validation.json"
    report.write_text(
        json.dumps(
            {
                "source_events": 3,
                "activities_after_shared_event_merge": 2,
                "groups": 2,
                "courses": 1,
                "rooms": 2,
                "staff": 2,
                "validation_error_count": 0,
            }
        ),
        encoding="utf-8",
    )
    return pdf, events, summary, report


def test_giu_calibration_is_deterministic_and_distinguishes_room_placeholders(
    tmp_path: Path,
) -> None:
    pdf, events, summary, report = _write_synthetic_sources(tmp_path)
    arguments = {
        "pdf_path": pdf,
        "events_path": events,
        "summary_path": summary,
        "validation_report_path": report,
    }

    first = build_giu_calibration(**arguments)
    second = build_giu_calibration(**arguments)

    assert first == second
    assert first["calibration_id"] == CALIBRATION_ID
    assert first["status"]["official_or_institution_approved"] is False
    assert first["status"]["current_policy_validated"] is False
    raw = first["observed"]["raw_extraction"]
    assert raw["scheduled_cells"] == 3
    assert raw["major_label_count"] == 2
    assert raw["major_row_key_count"] == 2
    assert raw["nonblank_room_label_count"] == 1
    assert raw["blank_room_event_rows"] == 1
    modeled = first["observed"]["current_import_projection"]
    assert modeled["merged_activities"] == 2
    assert modeled["modeled_room_records"] == 2
    assert modeled["modeled_room_accounting"] == {
        "nonblank_labels": 1,
        "row_scoped_unspecified_placeholders": 1,
        "sum_matches_modeled_records": True,
    }
    assert first["preset_comparison"]["standard_start_slots"]["delta"] == [2, 3, 4]


def test_checked_in_giu_preset_is_limitation_aware_and_matches_artifact() -> None:
    artifact = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    preset = institution_policy_preset("giu_target")

    assert artifact["calibration_id"] == CALIBRATION_ID
    assert artifact["status"]["classification"] == "historical_partial_calibration"
    assert artifact["status"]["official_or_institution_approved"] is False
    assert artifact["current_preset"]["payload"] == preset
    assert artifact["current_preset"]["payload_sha256"] == canonical_sha256(preset)
    assert preset["demand_policy"] == {"mode": "nominal"}
    assert preset["hard_constraints"]["enforce_calendar_rules"] is False
    assert preset["hard_constraints"]["enforce_building_closures"] is False
    assert preset["hard_constraints"]["enforce_travel_time_buffers"] is False
    policy = preset["institutional_policy"]
    assert policy["standard_start_slots"] == [0, 1, 2, 3, 4]
    assert "prime_time" not in policy
    assert "room_target_fill" not in policy
    assert len(policy["known_missing_evidence"]) >= 5


def test_local_giu_calibration_sources_reproduce_committed_artifact() -> None:
    sources = (DEFAULT_PDF, DEFAULT_EVENTS, DEFAULT_SUMMARY, DEFAULT_VALIDATION_REPORT)
    if not all(path.is_file() for path in sources):
        pytest.skip("private/local GIU SS23 calibration sources are not available")
    regenerated = build_giu_calibration(
        pdf_path=DEFAULT_PDF,
        events_path=DEFAULT_EVENTS,
        summary_path=DEFAULT_SUMMARY,
        validation_report_path=DEFAULT_VALIDATION_REPORT,
    )
    committed = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    assert regenerated == committed
