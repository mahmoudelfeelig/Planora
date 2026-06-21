from __future__ import annotations

from pathlib import Path

import pytest

from services.timetable_import_service import import_timetable_csv
from services.timetable_import_service import load_timetable_events


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


def test_import_timetable_csv_accepts_explicit_column_mapping(tmp_path):
    path = tmp_path / "mapped_timetable.csv"
    path.write_text(
        "\n".join(
            [
                "wk,weekday,period,module,cohort,venue,slots,activity_type",
                "2,Thu,3,Algorithms,A,R12,2,tutorial",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    field_map = {
        "week": "wk",
        "day": "weekday",
        "slot": "period",
        "course": "module",
        "group": "cohort",
        "room": "venue",
        "duration": "slots",
        "kind": "activity_type",
    }
    events = load_timetable_events(path, field_map=field_map)
    inst, schedule, meta = import_timetable_csv(path, field_map=field_map)

    assert events[0]["week"] == 2
    assert events[0]["day"] == "THU"
    assert events[0]["slot"] == 2
    assert events[0]["duration"] == 2
    assert events[0]["kind"] == "TUT"
    assert len(inst.groups) == 1
    assert len(schedule) == 1
    assert meta["source_events"] == 1


def test_import_timetable_csv_transform_config_splits_groups_and_infers_room_type(tmp_path):
    path = tmp_path / "transformed.csv"
    path.write_text(
        "\n".join(
            [
                "wk,weekday,period,module,cohort,venue,activity_type",
                "3,R,PM2,Networks,G1/G2,Lab-7,practice",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    field_map = {
        "week": "wk",
        "day": "weekday",
        "slot": "period",
        "course": "module",
        "group": "cohort",
        "room": "venue",
        "kind": "activity_type",
    }
    transform_config = {
        "day_aliases": {"R": "THU"},
        "slot_aliases": {"PM2": 3},
        "kind_aliases": {"practice": "LAB"},
        "group_separator": "/",
        "room_type_rules": [{"pattern": "Lab", "room_type": "COMPUTER_LAB"}],
    }
    inst, schedule, meta = import_timetable_csv(
        path,
        field_map=field_map,
        transform_config=transform_config,
    )

    assert len(inst.groups) == 2
    assert len(schedule) == 1
    only = next(iter(schedule.values()))
    assert only["day"] == "THU"
    assert only["slot"] == 3
    assert only["kind"] == "LAB"
    assert len(only["group_ids"]) == 2
    assert next(iter(inst.rooms.values())).room_type == "COMPUTER_LAB"
    assert meta["source_events"] == 2


def test_import_timetable_csv_skips_exact_duplicates_and_reuses_synthetic_lecturer(tmp_path):
    path = tmp_path / "duplicates.csv"
    path.write_text(
        "\n".join(
            [
                "week,day,slot,course,major,room",
                "1,Monday,1,CS101 Intro,G1,R1",
                "1,Monday,1,CS101 Intro,G1,R1",
                "2,Tuesday,2,CS101 Intro,G1,R1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    inst, schedule, meta = import_timetable_csv(path)

    assert meta["source_events"] == 3
    assert meta["duplicate_event_rows_skipped"] == 1
    assert len(schedule) == 2
    assert len({act.prof_id for act in inst.activities.values()}) == 1


def test_import_timetable_csv_reuses_ta_for_tutorial_and_lab_course_variants(tmp_path):
    path = tmp_path / "ta_variants.csv"
    path.write_text(
        "\n".join(
            [
                "week,day,slot,course,major,room",
                "2,Monday,1,CS101 T1,G1,Tutorial Room",
                "3,Tuesday,2,CS101 LAB,G1,Lab Room",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    inst, schedule, meta = import_timetable_csv(path)

    assert len(schedule) == 2
    assert meta["duplicate_event_rows_skipped"] == 0
    assert {row["kind"] for row in schedule.values()} == {"TUT", "LAB"}
    ta_ids = {act.ta_id for act in inst.activities.values()}
    assert len(ta_ids) == 1
    ta_id = next(iter(ta_ids))
    assert not inst.staff[int(ta_id)].is_prof
    assert all(row["staff_id"] == ta_id for row in schedule.values())


def test_import_ss23_csv_scores_original_if_fixture_exists():
    path = ROOT / "data" / "SS23-All-Majors-Schedule-events.csv"
    if not path.exists():
        pytest.skip("local SS23 events CSV is not present")

    inst, schedule, meta = import_timetable_csv(path)

    assert len(inst.groups) == 17
    assert len(inst.courses) == 88
    assert len(inst.rooms) == 161
    assert len(inst.staff) == 44
    assert len(schedule) == 1044
    assert all(not course.share_lecture_group_ids for course in inst.courses.values())
    assert meta["duplicate_event_rows_skipped"] == 0
    assert {k: sum(1 for a in inst.activities.values() if a.kind == k) for k in ["LEC", "TUT", "LAB"]} == {
        "LEC": 895,
        "TUT": 108,
        "LAB": 41,
    }
    assert sum(1 for staff in inst.staff.values() if staff.is_prof) == 22
    assert sum(1 for staff in inst.staff.values() if not staff.is_prof) == 22
    assert all(len(staff.can_teach_courses) == 4 for staff in inst.staff.values())
    assert meta["validation_error_count"] == 148
    assert meta["soft_penalty"] == 2375
