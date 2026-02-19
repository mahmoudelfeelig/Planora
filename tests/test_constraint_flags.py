from __future__ import annotations

from utils.domain import Activity, Course, Group, Instance, Program, Room, StaffMember
from utils.specs import validate_schedule_against_instance


def _build_min_instance(*, hard_constraints: dict[str, bool]) -> Instance:
    programs = {1: Program(id=1, name="P1", course_ids=[1], group_ids=[1])}
    groups = {1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1])}
    courses = {
        1: Course(
            id=1,
            code="C1",
            name="Course-1",
            structure_type="LEC_TUT",
            lecture_count=12,
            tutorial_count=12,
            lab_weeks=0,
            lab_duration=0,
            share_lecture_group_ids=[1],
            prof_id=1,
            ta_id=2,
        )
    }
    staff = {
        1: StaffMember(
            id=1,
            name="Prof-1",
            is_prof=True,
            available_days={"MON", "TUE", "WED", "THU", "FRI", "SAT"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
        ),
        2: StaffMember(
            id=2,
            name="TA-1",
            is_prof=False,
            available_days={"MON", "TUE", "WED", "THU", "FRI", "SAT"},
            max_slots_per_day=0,
            max_slots_per_week=None,
            can_teach_courses={1},
        ),
    }
    rooms = {
        1: Room(
            id=1,
            name="Tut-1",
            capacity=60,
            room_type="TUTORIAL",
            specialization_tags=set(),
        )
    }
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
        )
    }
    return Instance(
        days=["MON", "TUE", "WED", "THU", "FRI", "SAT"],
        slots_per_day=5,
        weeks=[1],
        programs=programs,
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
        hard_constraints=hard_constraints,
    )


def test_week1_rule_respects_hard_constraint_toggle():
    schedule = {
        1: {
            "week": 1,
            "day": "MON",
            "slot": 0,
            "duration": 1,
            "room_id": 1,
            "staff_id": 2,
            "course_id": 1,
            "group_ids": [1],
            "kind": "TUT",
        }
    }
    strict_inst = _build_min_instance(hard_constraints={"week1_lectures_only": True})
    relaxed_inst = _build_min_instance(hard_constraints={"week1_lectures_only": False})

    strict_errors = validate_schedule_against_instance(strict_inst, schedule, strict_rooms=False)
    relaxed_errors = validate_schedule_against_instance(relaxed_inst, schedule, strict_rooms=False)

    assert any("week-1 lectures-only" in e for e in strict_errors)
    assert not any("week-1 lectures-only" in e for e in relaxed_errors)


def test_staff_daily_cap_toggle_respects_hard_constraint():
    schedule = {
        1: {
            "week": 1,
            "day": "MON",
            "slot": 0,
            "duration": 1,
            "room_id": 1,
            "staff_id": 2,
            "course_id": 1,
            "group_ids": [1],
            "kind": "TUT",
        }
    }
    strict_inst = _build_min_instance(hard_constraints={"week1_lectures_only": False, "enforce_staff_daily_caps": True})
    relaxed_inst = _build_min_instance(hard_constraints={"week1_lectures_only": False, "enforce_staff_daily_caps": False})

    strict_errors = validate_schedule_against_instance(strict_inst, schedule, strict_rooms=False)
    relaxed_errors = validate_schedule_against_instance(relaxed_inst, schedule, strict_rooms=False)

    assert any("daily cap" in e for e in strict_errors)
    assert not any("daily cap" in e for e in relaxed_errors)
