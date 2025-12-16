from __future__ import annotations

from typing import Dict

from utils.domain import Activity, Course, Group, Instance, Room, StaffMember
from core.solver_cp_sat import assign_rooms_greedily


def make_instance(
    *,
    groups: Dict[int, Group],
    rooms: Dict[int, Room],
    activities: Dict[int, Activity],
    courses: Dict[int, Course],
) -> Instance:
    return Instance(
        days=["MON"],
        slots_per_day=3,
        weeks=[1],
        programs={},
        groups=groups,
        courses=courses,
        staff={},  # staff not needed for room assignment
        rooms=rooms,
        activities=activities,
    )


def base_schedule_entry(activity: Activity):
    return {
        "room_id": None,
        "staff_id": activity.prof_id or activity.ta_id or 0,
        "week": activity.week,
        "day": "MON",
        "slot": 0,
        "duration": activity.duration,
        "group_ids": list(activity.group_ids),
        "course_id": activity.course_id,
        "kind": activity.kind,
    }


def test_specialized_labs_use_tagged_rooms_before_falling_back():
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1]),
        2: Group(id=2, name="G2", program_id=1, size=30, course_ids=[2]),
    }
    rooms = {
        1: Room(id=1, name="SpecBio", capacity=40, room_type="SPECIALIZED_LAB", specialization_tags={"BIO"}),
        2: Room(id=2, name="CompLab", capacity=40, room_type="COMPUTER_LAB", specialization_tags=set()),
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
        ),
        2: Course(
            id=2,
            code="C2",
            name="Course 2",
            structure_type="LAB_ONLY",
            lecture_count=0,
            tutorial_count=0,
            lab_weeks=12,
            lab_duration=2,
            share_lecture_group_ids=[],
        ),
    }
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=1,
            kind="LAB",
            duration=1,
            group_ids=[1],
            prof_id=0,
            ta_id=0,
            requires_specialization="BIO",
        ),
        2: Activity(
            id=2,
            course_id=2,
            week=1,
            kind="LAB",
            duration=1,
            group_ids=[2],
            prof_id=0,
            ta_id=0,
            requires_specialization="BIO",
        ),
    }
    inst = make_instance(groups=groups, rooms=rooms, activities=activities, courses=courses)
    schedule = {a_id: base_schedule_entry(act) for a_id, act in activities.items()}

    assign_rooms_greedily(inst, schedule)

    assigned = {schedule[1]["room_id"], schedule[2]["room_id"]}
    assert assigned == {1, 2}


def test_big_lecture_prefers_large_room():
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=120, course_ids=[1]),
    }
    rooms = {
        1: Room(id=1, name="BigLec", capacity=400, room_type="LECTURE", specialization_tags=set()),
        2: Room(id=2, name="SmallLec", capacity=100, room_type="LECTURE", specialization_tags=set()),
    }
    courses = {
        1: Course(
            id=1,
            code="C1",
            name="Course 1",
            structure_type="LEC_TUT",
            lecture_count=12,
            tutorial_count=12,
            lab_weeks=0,
            lab_duration=0,
            share_lecture_group_ids=[],
        ),
    }
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[1],
            prof_id=0,
            ta_id=0,
            requires_specialization=None,
        ),
    }
    inst = make_instance(groups=groups, rooms=rooms, activities=activities, courses=courses)
    schedule = {1: base_schedule_entry(activities[1])}

    assign_rooms_greedily(inst, schedule)

    assert schedule[1]["room_id"] == 1


def test_shared_lecture_clusters_share_room():
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=40, course_ids=[1]),
        2: Group(id=2, name="G2", program_id=1, size=50, course_ids=[1]),
    }
    rooms = {
        1: Room(id=1, name="L1", capacity=200, room_type="LECTURE", specialization_tags=set()),
        2: Room(id=2, name="L2", capacity=200, room_type="LECTURE", specialization_tags=set()),
    }
    courses = {
        1: Course(
            id=1,
            code="C1",
            name="Course 1",
            structure_type="LEC_TUT",
            lecture_count=12,
            tutorial_count=12,
            lab_weeks=0,
            lab_duration=0,
            share_lecture_group_ids=[1, 2],
        ),
    }
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[1],
            prof_id=0,
            ta_id=0,
            requires_specialization=None,
        ),
        2: Activity(
            id=2,
            course_id=1,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[2],
            prof_id=0,
            ta_id=0,
            requires_specialization=None,
        ),
    }
    inst = make_instance(groups=groups, rooms=rooms, activities=activities, courses=courses)
    schedule = {a_id: base_schedule_entry(act) for a_id, act in activities.items()}

    assign_rooms_greedily(inst, schedule)

    assert schedule[1]["room_id"] == schedule[2]["room_id"]
