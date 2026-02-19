from __future__ import annotations

import pytest

from utils.domain import Activity, Course, Group, Instance, Room
from core.solver_cp_sat import assign_rooms_greedily, GreedyRoomingError


def make_instance(
    *,
    rooms,
    activities,
    courses,
    groups,
) -> Instance:
    return Instance(
        days=["MON"],
        slots_per_day=2,
        weeks=[1],
        programs={},
        groups=groups,
        courses=courses,
        staff={},
        rooms=rooms,
        activities=activities,
    )


def base_schedule(activity: Activity):
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


def test_greedy_rooming_missing_lab_rooms():
    groups = {1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1])}
    rooms = {}
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
        )
    }
    inst = make_instance(groups=groups, rooms=rooms, activities=activities, courses=courses)
    schedule = {1: base_schedule(activities[1])}

    with pytest.raises(GreedyRoomingError) as exc:
        assign_rooms_greedily(inst, schedule)
    assert exc.value.reason in {"room_type_missing", "tag_mismatch"}


def test_greedy_rooming_capacity():
    groups = {1: Group(id=1, name="G1", program_id=1, size=200, course_ids=[1])}
    rooms = {1: Room(id=1, name="SmallLec", capacity=50, room_type="LECTURE", specialization_tags=set())}
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
        )
    }
    inst = make_instance(groups=groups, rooms=rooms, activities=activities, courses=courses)
    schedule = {1: base_schedule(activities[1])}

    with pytest.raises(GreedyRoomingError) as exc:
        assign_rooms_greedily(inst, schedule)
    assert exc.value.reason == "capacity"


def test_greedy_rooming_availability():
    groups = {1: Group(id=1, name="G1", program_id=1, size=20, course_ids=[1])}
    rooms = {
        1: Room(
            id=1,
            name="L1",
            capacity=40,
            room_type="LECTURE",
            specialization_tags=set(),
            availability={("MON", 1)},  # slot 0 unavailable
        )
    }
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
        )
    }
    inst = make_instance(groups=groups, rooms=rooms, activities=activities, courses=courses)
    schedule = {1: base_schedule(activities[1])}

    with pytest.raises(GreedyRoomingError) as exc:
        assign_rooms_greedily(inst, schedule)
    assert exc.value.reason == "availability"
