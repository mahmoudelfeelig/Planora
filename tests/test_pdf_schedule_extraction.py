from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts.extract_pdf_schedule import extract, validate
from scripts.build_uni_schedule_scenario import _load_events, build_instance_and_schedule
from utils.specs import validate_schedule_against_instance


ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.slow
def test_ss23_all_majors_schedule_pdf_extracts_to_valid_cells():
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext is required for PDF schedule extraction")

    pdf_path = ROOT / "data" / "SS23-All-Majors-Schedule.pdf"
    if not pdf_path.exists():
        pytest.skip("local SS23 university schedule PDF is not present")

    cells, summary = extract(pdf_path)
    errors = validate(cells, summary)

    assert errors == []
    assert summary["pages"] == 72
    assert summary["weeks"] == list(range(1, 13))
    assert summary["days"] == ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    assert summary["cells"] == 3360
    assert summary["scheduled_cells"] > 1000
    assert summary["free_cells"] > 1000

    scheduled = {
        (
            cell["week"],
            cell["day"],
            cell["major"],
            cell["slot_index"],
            cell["course"],
            cell["room"],
        )
        for cell in cells
        if cell["status"] == "scheduled"
    }
    assert (
        1,
        "Tuesday",
        "CSEN 6th",
        2,
        "MNGT601 - Introduction to Management",
        "2.07",
    ) in scheduled
    assert not any(str(cell["course"]).endswith(" Free") for cell in cells)


@pytest.mark.slow
def test_ss23_all_majors_events_build_scheduler_scenario():
    events_path = ROOT / "data" / "SS23-All-Majors-Schedule-events.csv"
    if not events_path.exists():
        pytest.skip("local SS23 university schedule events CSV is not present")

    events = _load_events(events_path)
    inst, schedule, meta = build_instance_and_schedule(events)
    errors = validate_schedule_against_instance(
        inst,
        schedule,
        strict_rooms=True,
        require_all_activities=True,
    )

    assert meta["source_events"] == 1265
    assert meta["activities_after_shared_event_merge"] == 1044
    assert len(inst.groups) == 17
    assert len(inst.courses) == 88
    assert len(schedule) == 1044
    assert not any(str(error).startswith("Group overlap") for error in errors)
    assert any(str(error).startswith("Room overlap") for error in errors)
