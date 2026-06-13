from __future__ import annotations

from pathlib import Path

import pytest

from services.timetable_import_service import import_timetable_csv


ROOT = Path(__file__).resolve().parent.parent


def test_import_timetable_csv_builds_instance_and_schedule(tmp_path):
    path = tmp_path / "timetable.csv"
    path.write_text(
        "\n".join(
            [
                "week,day,slot,course,major,room",
                "1,Monday,1,CS101 Intro,G1,R1",
                "1,Monday,1,CS101 Intro,G2,R1",
                "1,Tuesday,2,MATH201,G1,R2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    inst, schedule, meta = import_timetable_csv(path)

    assert len(inst.groups) == 2
    assert len(inst.courses) == 2
    assert len(schedule) == 2
    assert inst.locked_activities == {}
    assert all(not course.share_lecture_group_ids for course in inst.courses.values())
    assert meta["source_events"] == 3
    assert meta["activities_after_shared_event_merge"] == 2
    assert meta["soft_penalty"] >= 0


def test_import_ss23_csv_scores_original_if_fixture_exists():
    path = ROOT / "data" / "SS23-All-Majors-Schedule-events.csv"
    if not path.exists():
        pytest.skip("local SS23 events CSV is not present")

    inst, schedule, meta = import_timetable_csv(path)

    assert len(inst.groups) == 17
    assert len(inst.courses) == 88
    assert len(inst.rooms) == 161
    assert len(schedule) == 1044
    assert all(not course.share_lecture_group_ids for course in inst.courses.values())
    assert meta["validation_error_count"] == 16
    assert meta["soft_penalty"] == 2378
