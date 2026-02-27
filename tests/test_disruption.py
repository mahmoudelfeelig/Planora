from __future__ import annotations

from utils.disruption import (
    apply_staff_outage_week,
    apply_room_outage_week,
    build_freeze_locks,
)
from utils.domain import Activity, Course, Group, Instance, Program, Room, StaffMember


def _mini_instance() -> Instance:
    programs = {1: Program(id=1, name="P1", course_ids=[1], group_ids=[1])}
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1]),
    }
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
            prof_id=1,
            ta_id=3,
        )
    }
    staff = {
        1: StaffMember(
            id=1,
            name="Prof-1",
            is_prof=True,
            available_days={"MON", "TUE"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            available_weeks={1, 2},
        ),
        2: StaffMember(
            id=2,
            name="Prof-2",
            is_prof=True,
            available_days={"MON", "TUE"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            available_weeks={1, 2},
        ),
        3: StaffMember(
            id=3,
            name="TA-1",
            is_prof=False,
            available_days={"MON", "TUE"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            available_weeks={1, 2},
        ),
    }
    rooms = {
        1: Room(id=1, name="R1", capacity=120, room_type="LECTURE"),
        2: Room(id=2, name="R2", capacity=120, room_type="LECTURE"),
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
            ta_id=3,
        ),
        2: Activity(
            id=2,
            course_id=1,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[1],
            prof_id=2,
            ta_id=3,
        ),
    }
    return Instance(
        days=["MON", "TUE"],
        slots_per_day=4,
        weeks=[1, 2],
        programs=programs,
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )


def test_apply_staff_outage_week_reassigns_when_candidate_exists():
    inst = _mini_instance()
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
    out, affected, unresolved = apply_staff_outage_week(
        inst, schedule, staff_id=1, week=1
    )
    assert affected == {1}
    assert unresolved == set()
    assert int(out[1]["staff_id"]) == 2


def test_apply_room_outage_week_marks_unresolved_when_no_spare_room():
    inst = _mini_instance()
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
        },
        2: {
            "week": 1,
            "day": "MON",
            "slot": 0,
            "duration": 1,
            "room_id": 2,
            "staff_id": 2,
            "course_id": 1,
            "group_ids": [1],
            "kind": "LEC",
        },
    }
    out, affected, unresolved = apply_room_outage_week(inst, schedule, room_id=1, week=1)
    assert affected == {1}
    assert unresolved == {1}
    assert int(out[1]["room_id"]) == 1


def test_build_freeze_locks_excludes_unlocked_ids():
    schedule = {
        1: {"day": "MON", "slot": 0, "room_id": 10},
        2: {"day": "TUE", "slot": 1, "room_id": 20},
    }
    locks = build_freeze_locks(schedule, unlocked_activity_ids={2})
    assert set(locks.keys()) == {1}
    assert locks[1]["day"] == "MON"
    assert int(locks[1]["slot"]) == 0
    assert int(locks[1]["room_id"]) == 10
