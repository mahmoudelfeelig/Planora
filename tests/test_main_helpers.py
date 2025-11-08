from __future__ import annotations

from typing import Dict, List

import pytest

from domain import Activity, Course, Group, Instance, Room, StaffMember
from main import normalize_instance_for_spec, check_staff_weekly_capacity


def make_instance(
    *,
    days: List[str],
    slots_per_day: int,
    weeks: List[int],
    groups: Dict[int, Group],
    courses: Dict[int, Course],
    staff: Dict[int, StaffMember],
    rooms: Dict[int, Room],
    activities: Dict[int, Activity],
) -> Instance:
    return Instance(
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


def test_normalize_instance_adds_sunday_and_sets_staff_availability(capsys):
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=20, course_ids=[1]),
    }
    courses = {
        1: Course(
            id=1,
            code="C1",
            name="Course 1",
            structure_type="LAB_ONLY",
            lecture_count=0,
            tutorial_count=0,
            lab_weeks=12,
            lab_duration=2,
            share_lecture_group_ids=[],
        )
    }
    staff = {
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
    }
    rooms = {
        1: Room(
            id=1,
            name="SpecLab",
            capacity=40,
            room_type="SPECIALIZED_LAB",
            specialization_tags={"BIO"},
        )
    }
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=1,
            kind="LAB",
            duration=2,
            group_ids=[1],
            prof_id=1,
            ta_id=1,
            requires_specialization="BIO",
        )
    }
    inst = make_instance(
        days=["MON", "TUE"],
        slots_per_day=5,
        weeks=[1],
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    normalize_instance_for_spec(inst)

    assert inst.days[-1] == "SUN"
    assert inst.days[:2] == ["MON", "TUE"]
    assert staff[1].available_days == inst.days

    out = capsys.readouterr().out
    assert "[WARN]" not in out


def test_normalize_instance_warns_when_missing_special_lab_tag(capsys):
    groups = {1: Group(id=1, name="G1", program_id=1, size=20, course_ids=[1])}
    courses = {
        1: Course(
            id=1,
            code="C1",
            name="Course 1",
            structure_type="LAB_ONLY",
            lecture_count=0,
            tutorial_count=0,
            lab_weeks=12,
            lab_duration=2,
            share_lecture_group_ids=[],
        )
    }
    staff = {
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
    }
    rooms: Dict[int, Room] = {}
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=1,
            kind="LAB",
            duration=2,
            group_ids=[1],
            prof_id=1,
            ta_id=1,
            requires_specialization="BIO",
        )
    }
    inst = make_instance(
        days=["MON"],
        slots_per_day=5,
        weeks=[1],
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    normalize_instance_for_spec(inst)

    out = capsys.readouterr().out
    assert "[WARN] No specialized lab rooms for tags: ['BIO']" in out


def test_check_staff_weekly_capacity_warns_when_load_exceeds_cap(capsys):
    groups = {1: Group(id=1, name="G1", program_id=1, size=20, course_ids=[1])}
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
    staff = {
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
    }
    rooms = {1: Room(id=1, name="L1", capacity=100, room_type="LECTURE", specialization_tags=set())}
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
        ),
        2: Activity(
            id=2,
            course_id=1,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[1],
            prof_id=1,
            ta_id=1,
            requires_specialization=None,
        ),
        3: Activity(
            id=3,
            course_id=1,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[1],
            prof_id=1,
            ta_id=1,
            requires_specialization=None,
        ),
    }
    inst = make_instance(
        days=["MON", "TUE", "SUN"],
        slots_per_day=1,
        weeks=[1],
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    check_staff_weekly_capacity(inst)

    out = capsys.readouterr().out
    assert "[WARN] Staff 'Prof-1' (PROF) week 1: need 3 slots > capacity 1" in out
