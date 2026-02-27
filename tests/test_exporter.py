from __future__ import annotations

from datetime import date
from typing import Dict

import pytest

from utils import exporter
from utils.domain import Activity, Course, Group, Instance, Room, StaffMember


def make_instance(
    *,
    days,
    slots_per_day,
    weeks,
    groups: Dict[int, Group],
    courses: Dict[int, Course],
    staff: Dict[int, StaffMember],
    rooms: Dict[int, Room],
    activities: Dict[int, Activity],
) -> Instance:
    inst = Instance(
        days=list(days),
        slots_per_day=slots_per_day,
        weeks=list(weeks),
        programs={},
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )
    return inst


def test_slot_labels_respect_instance_time_labels():
    inst = make_instance(
        days=["MON"],
        slots_per_day=2,
        weeks=[1],
        groups={},
        courses={},
        staff={},
        rooms={},
        activities={},
    )
    inst.time_labels = ["A", "B"]

    assert exporter._slot_labels(inst) == ["A", "B"]


def test_slot_labels_compute_ranges_from_instance_settings():
    inst = make_instance(
        days=["MON"],
        slots_per_day=2,
        weeks=[1],
        groups={},
        courses={},
        staff={},
        rooms={},
        activities={},
    )
    inst.day_start_time = "09:00"
    inst.slot_minutes = 60
    inst.slot_break_minutes = 15

    labels = exporter._slot_labels(inst)
    assert labels == ["09:00 - 10:00", "10:15 - 11:15"]


def test_export_groups_ics_per_id_writes_expected_vevent(monkeypatch):
    groups = {1: Group(id=1, name="Group A", program_id=1, size=30, course_ids=[1])}
    staff = {1: StaffMember(
        id=1,
        name="Prof-1",
        is_prof=True,
        available_days={"MON"},
        max_slots_per_day=None,
        max_slots_per_week=None,
        can_teach_courses={1},
        prefers_block=False,
        blocks_only=False,
    )}
    rooms = {1: Room(id=1, name="Room 101", capacity=120, room_type="LECTURE", specialization_tags=set())}
    courses = {
        1: Course(
            id=1,
            code="C1",
            name="Course 1",
            structure_type="LEC_ONLY",
            lecture_count=12,
            tutorial_count=0,
            lab_weeks=0,
            lab_duration=0,
            share_lecture_group_ids=[],
        )
    }
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[1],
            prof_id=1,
            ta_id=1,
            requires_specialization=None,
        )
    }
    inst = make_instance(
        days=["MON"],
        slots_per_day=1,
        weeks=[1],
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )
    inst.day_start_time = "08:00"
    inst.slot_minutes = 60

    schedule = {
        1: {
            "week": 1,
            "day": "MON",
            "slot": 0,
            "duration": 1,
            "room_id": 1,
            "staff_id": 1,
            "course_id": 1,
            "group_ids": [1],
            "kind": "LEC",
        }
    }

    written = {}

    def fake_write(text: str, path):
        written[path.name] = text

    monkeypatch.setattr(exporter, "_write_ics", fake_write)

    exporter.export_groups_ics_per_id(inst, schedule, "out", week0_monday=date(2025, 1, 6))

    fname = "group_1_group-a.ics"
    assert fname in written
    ics_text = written[fname]
    assert "BEGIN:VCALENDAR" in ics_text
    assert "UID:group-1-a1-w1-dMON-s0" in ics_text
    assert "SUMMARY:C1 LEC" in ics_text
    assert "LOCATION:Room 101" in ics_text


def test_export_groups_pdf_writes_pdf_header(tmp_path):
    inst = make_instance(
        days=["MON"],
        slots_per_day=1,
        weeks=[1],
        groups={1: Group(id=1, name="Group A", program_id=1, size=30, course_ids=[1])},
        courses={
            1: Course(
                id=1,
                code="C1",
                name="Course 1",
                structure_type="LEC_ONLY",
                lecture_count=1,
                tutorial_count=0,
                lab_weeks=0,
                lab_duration=0,
                share_lecture_group_ids=[],
            )
        },
        staff={1: StaffMember(
            id=1,
            name="Prof-1",
            is_prof=True,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        )},
        rooms={1: Room(id=1, name="Room 101", capacity=120, room_type="LECTURE", specialization_tags=set())},
        activities={
            1: Activity(
                id=1,
                course_id=1,
                week=1,
                kind="LEC",
                duration=1,
                group_ids=[1],
                prof_id=1,
                ta_id=1,
                requires_specialization=None,
            )
        },
    )
    schedule = {
        1: {
            "week": 1,
            "day": "MON",
            "slot": 0,
            "duration": 1,
            "room_id": 1,
            "staff_id": 1,
            "course_id": 1,
            "group_ids": [1],
            "kind": "LEC",
        }
    }

    out_path = tmp_path / "groups.pdf"
    exporter.export_groups_pdf(inst, schedule, out_path)
    data = out_path.read_bytes()
    assert data.startswith(b"%PDF-")


def test_export_summary_reports_writes_csvs(tmp_path):
    inst = make_instance(
        days=["MON"],
        slots_per_day=1,
        weeks=[1],
        groups={1: Group(id=1, name="Group A", program_id=1, size=30, course_ids=[1])},
        courses={
            1: Course(
                id=1,
                code="C1",
                name="Course 1",
                structure_type="LEC_ONLY",
                lecture_count=1,
                tutorial_count=0,
                lab_weeks=0,
                lab_duration=0,
                share_lecture_group_ids=[],
            )
        },
        staff={1: StaffMember(
            id=1,
            name="Prof-1",
            is_prof=True,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        )},
        rooms={1: Room(id=1, name="Room 101", capacity=120, room_type="LECTURE", specialization_tags=set())},
        activities={
            1: Activity(
                id=1,
                course_id=1,
                week=1,
                kind="LEC",
                duration=1,
                group_ids=[1],
                prof_id=1,
                ta_id=1,
                requires_specialization=None,
            )
        },
    )
    schedule = {
        1: {
            "week": 1,
            "day": "MON",
            "slot": 0,
            "duration": 1,
            "room_id": 1,
            "staff_id": 1,
            "course_id": 1,
            "group_ids": [1],
            "kind": "LEC",
        }
    }

    exporter.export_summary_reports(inst, schedule, tmp_path)
    assert (tmp_path / "staff_load.csv").exists()
    assert (tmp_path / "group_load.csv").exists()
    assert (tmp_path / "room_util.csv").exists()


def test_export_calendar_feeds_writes_manifest(tmp_path):
    inst = make_instance(
        days=["MON"],
        slots_per_day=1,
        weeks=[1],
        groups={1: Group(id=1, name="Group A", program_id=1, size=30, course_ids=[1])},
        courses={
            1: Course(
                id=1,
                code="C1",
                name="Course 1",
                structure_type="LEC_ONLY",
                lecture_count=1,
                tutorial_count=0,
                lab_weeks=0,
                lab_duration=0,
                share_lecture_group_ids=[],
            )
        },
        staff={
            1: StaffMember(
                id=1,
                name="Prof-1",
                is_prof=True,
                available_days={"MON"},
                max_slots_per_day=None,
                max_slots_per_week=None,
                can_teach_courses={1},
                prefers_block=False,
                blocks_only=False,
            )
        },
        rooms={1: Room(id=1, name="Room 101", capacity=120, room_type="LECTURE", specialization_tags=set())},
        activities={
            1: Activity(
                id=1,
                course_id=1,
                week=1,
                kind="LEC",
                duration=1,
                group_ids=[1],
                prof_id=1,
                ta_id=1,
                requires_specialization=None,
            )
        },
    )
    schedule = {
        1: {
            "week": 1,
            "day": "MON",
            "slot": 0,
            "duration": 1,
            "room_id": 1,
            "staff_id": 1,
            "course_id": 1,
            "group_ids": [1],
            "kind": "LEC",
        }
    }

    out_dir = tmp_path / "feeds"
    manifest = exporter.export_calendar_feeds(inst, schedule, str(out_dir))
    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "groups").exists()
    assert (out_dir / "staff").exists()
    assert (out_dir / "rooms").exists()
    assert "feeds" in manifest
    assert isinstance(manifest["feeds"]["groups"], list)
