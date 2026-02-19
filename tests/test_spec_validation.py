from __future__ import annotations

import pytest

from utils.domain import Activity, Course, Group, Instance, Room, StaffMember
from utils.specs import validate_instance_against_spec


def make_instance(
    *,
    days,
    slots_per_day,
    weeks,
) -> Instance:
    groups = {1: Group(id=1, name="G1", program_id=1, size=20, course_ids=[1])}
    courses = {
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
    }
    staff = {
        1: StaffMember(
            id=1,
            name="Prof-1",
            is_prof=True,
            available_days=set(days),
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
            week=weeks[0],
            kind="LEC",
            duration=1,
            group_ids=[1],
            prof_id=1,
            ta_id=1,
            requires_specialization=None,
        )
    }
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


def test_validate_instance_rejects_wrong_days():
    inst = make_instance(days=["MON", "TUE"], slots_per_day=5, weeks=list(range(1, 13)))
    with pytest.raises(ValueError, match="days must be"):
        validate_instance_against_spec(inst)


def test_validate_instance_rejects_wrong_weeks():
    inst = make_instance(days=["MON", "TUE", "WED", "THU", "FRI", "SAT"], slots_per_day=5, weeks=[1, 2])
    with pytest.raises(ValueError, match="weeks must be"):
        validate_instance_against_spec(inst)


def test_validate_instance_rejects_wrong_slots_per_day():
    inst = make_instance(days=["MON", "TUE", "WED", "THU", "FRI", "SAT"], slots_per_day=4, weeks=list(range(1, 13)))
    with pytest.raises(ValueError, match="slots_per_day must be"):
        validate_instance_against_spec(inst)


def test_validate_instance_rejects_bad_duration():
    inst = make_instance(days=["MON", "TUE", "WED", "THU", "FRI", "SAT"], slots_per_day=5, weeks=list(range(1, 13)))
    inst.activities[1].duration = 4
    with pytest.raises(ValueError, match="duration"):
        validate_instance_against_spec(inst)


def test_validate_instance_rejects_bad_course_counts():
    inst = make_instance(days=["MON", "TUE", "WED", "THU", "FRI", "SAT"], slots_per_day=5, weeks=list(range(1, 13)))
    inst.courses[1].lecture_count = 10
    with pytest.raises(ValueError, match="lecture_count"):
        validate_instance_against_spec(inst)

    inst = make_instance(days=["MON", "TUE", "WED", "THU", "FRI", "SAT"], slots_per_day=5, weeks=list(range(1, 13)))
    inst.courses[1].lecture_count = 12
    inst.courses[1].tutorial_count = 8
    with pytest.raises(ValueError, match="tutorial_count"):
        validate_instance_against_spec(inst)

    inst = make_instance(days=["MON", "TUE", "WED", "THU", "FRI", "SAT"], slots_per_day=5, weeks=list(range(1, 13)))
    inst.courses[1].lecture_count = 12
    inst.courses[1].lab_weeks = 6
    with pytest.raises(ValueError, match="lab_weeks"):
        validate_instance_against_spec(inst)

    inst = make_instance(days=["MON", "TUE", "WED", "THU", "FRI", "SAT"], slots_per_day=5, weeks=list(range(1, 13)))
    inst.courses[1].lecture_count = 12
    inst.courses[1].lab_weeks = 12
    inst.courses[1].lab_duration = 3
    with pytest.raises(ValueError, match="lab_duration"):
        validate_instance_against_spec(inst)
