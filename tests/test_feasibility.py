from __future__ import annotations

from utils.domain import Activity, Course, Group, Instance, Room, StaffMember
from utils.feasibility import explain_infeasibility


def make_instance(
    *,
    days,
    slots_per_day,
    weeks,
    groups,
    courses,
    staff,
    rooms,
    activities,
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


def test_explain_week1_non_lecture():
    groups = {1: Group(id=1, name="G1", program_id=1, size=20, course_ids=[1])}
    courses = {
        1: Course(
            id=1,
            code="C1",
            name="Course 1",
            structure_type="LEC_TUT",
            lecture_count=1,
            tutorial_count=1,
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
        ),
        2: StaffMember(
            id=2,
            name="TA-1",
            is_prof=False,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        ),
    }
    rooms = {1: Room(id=1, name="L1", capacity=40, room_type="LECTURE", specialization_tags=set())}
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=1,
            kind="TUT",
            duration=1,
            group_ids=[1],
            prof_id=1,
            ta_id=2,
            requires_specialization=None,
        ),
    }
    inst = make_instance(
        days=["MON"],
        slots_per_day=2,
        weeks=[1],
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )
    reasons = explain_infeasibility(inst)
    assert any("Week 1" in r for r in reasons)


def test_explain_staff_availability_no_days():
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
            available_days={"TUE"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        )
    }
    rooms = {1: Room(id=1, name="L1", capacity=40, room_type="LECTURE", specialization_tags=set())}
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
    }
    inst = make_instance(
        days=["MON"],
        slots_per_day=2,
        weeks=[1],
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )
    reasons = explain_infeasibility(inst)
    assert any("no available days" in r for r in reasons)


def test_explain_missing_special_lab_tag():
    groups = {1: Group(id=1, name="G1", program_id=1, size=20, course_ids=[1])}
    courses = {
        1: Course(
            id=1,
            code="C1",
            name="Course 1",
            structure_type="LAB_ONLY",
            lecture_count=0,
            tutorial_count=0,
            lab_weeks=1,
            lab_duration=1,
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
        ),
        2: StaffMember(
            id=2,
            name="TA-1",
            is_prof=False,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        ),
    }
    rooms = {1: Room(id=1, name="Lab1", capacity=40, room_type="COMPUTER_LAB", specialization_tags=set())}
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=2,
            kind="LAB",
            duration=1,
            group_ids=[1],
            prof_id=1,
            ta_id=2,
            requires_specialization="BIO",
        ),
    }
    inst = make_instance(
        days=["MON"],
        slots_per_day=2,
        weeks=[1, 2],
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )
    reasons = explain_infeasibility(inst)
    assert any("requires lab tag" in r for r in reasons)


def test_explain_staff_weekly_capacity():
    groups = {1: Group(id=1, name="G1", program_id=1, size=20, course_ids=[1])}
    courses = {
        1: Course(
            id=1,
            code="C1",
            name="Course 1",
            structure_type="LEC_ONLY",
            lecture_count=2,
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
            max_slots_per_day=1,
            max_slots_per_week=1,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        ),
        2: StaffMember(
            id=2,
            name="TA-1",
            is_prof=False,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        ),
    }
    rooms = {1: Room(id=1, name="L1", capacity=40, room_type="LECTURE", specialization_tags=set())}
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[1],
            prof_id=1,
            ta_id=2,
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
            ta_id=2,
            requires_specialization=None,
        ),
    }
    inst = make_instance(
        days=["MON"],
        slots_per_day=2,
        weeks=[1],
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )
    reasons = explain_infeasibility(inst)
    assert any("exceeds cap" in r for r in reasons)

