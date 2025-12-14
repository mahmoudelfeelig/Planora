from __future__ import annotations

from typing import Dict, Sequence

from ortools.sat.python import cp_model
import pytest

from domain import Activity, Course, Group, Instance, Room, StaffMember
from solver_cp_sat import TimetableSolver


def build_instance(
    *,
    days: Sequence[str],
    slots_per_day: int,
    weeks: Sequence[int],
    groups: Dict[int, Group],
    staff: Dict[int, StaffMember],
    rooms: Dict[int, Room],
    activities: Dict[int, Activity],
    courses: Dict[int, Course] | None = None,
) -> Instance:
    if courses is None:
        course_ids = {act.course_id for act in activities.values()}
        courses = {
            c_id: Course(
                id=c_id,
                code=f"C{c_id}",
                name=f"Course {c_id}",
                structure_type="LEC_ONLY",
                lecture_count=12,
                tutorial_count=0,
                lab_weeks=0,
                lab_duration=0,
                share_lecture_group_ids=[],
            )
            for c_id in course_ids
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


def solve_status(inst: Instance) -> int:
    solver = TimetableSolver(inst)
    _, status = solver.solve()
    return status


def extract_day(inst: Instance, solver: TimetableSolver, cp_solver: cp_model.CpSolver, act_id: int) -> str:
    start_value = cp_solver.Value(solver.start[act_id])
    day_index = start_value // inst.slots_per_day
    return inst.days[day_index]


def test_staff_availability_is_respected() -> None:
    days = ["MON", "TUE", "WED"]
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1]),
    }
    staff = {
        1: StaffMember(
            id=1,
            name="Prof-1",
            is_prof=True,
            available_days={"TUE", "WED"},
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
            available_days=set(days),
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        ),
    }
    rooms = {
        1: Room(id=1, name="L1", capacity=120, room_type="LECTURE", specialization_tags=set()),
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
            ta_id=2,
            requires_specialization=None,
        ),
    }
    inst = build_instance(
        days=days,
        slots_per_day=1,
        weeks=[1],
        groups=groups,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    solver = TimetableSolver(inst)
    cp_solver, status = solver.solve()
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert extract_day(inst, solver, cp_solver, 1) in {"TUE", "WED"}


def test_staff_daily_max_limit_enforced() -> None:
    groups = {
        i: Group(id=i, name=f"G{i}", program_id=1, size=30, course_ids=[i])
        for i in range(1, 4)
    }
    staff = {
        1: StaffMember(
            id=1,
            name="Prof-1",
            is_prof=True,
            available_days={"MON"},
            max_slots_per_day=2,
            max_slots_per_week=None,
            can_teach_courses={1, 2, 3},
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
            can_teach_courses={1, 2, 3},
            prefers_block=False,
            blocks_only=False,
        ),
    }
    rooms = {1: Room(id=1, name="L1", capacity=200, room_type="LECTURE", specialization_tags=set())}
    activities = {
        i: Activity(
            id=i,
            course_id=i,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[i],
            prof_id=1,
            ta_id=2,
            requires_specialization=None,
        )
        for i in range(1, 4)
    }
    inst = build_instance(
        days=["MON"],
        slots_per_day=3,
        weeks=[1],
        groups=groups,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    assert solve_status(inst) == cp_model.INFEASIBLE


def test_block_only_professor_needs_single_start_per_day() -> None:
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=40, course_ids=[1]),
        2: Group(id=2, name="G2", program_id=1, size=40, course_ids=[2]),
    }
    staff = {
        1: StaffMember(
            id=1,
            name="Prof-Block",
            is_prof=True,
            available_days={"SAT"},
            max_slots_per_day=None,
            max_slots_per_week=8,
            can_teach_courses={1, 2},
            prefers_block=True,
            blocks_only=True,
        ),
        2: StaffMember(
            id=2,
            name="TA-1",
            is_prof=False,
            available_days={"SAT"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1, 2},
            prefers_block=False,
            blocks_only=False,
        ),
    }
    rooms = {1: Room(id=1, name="L1", capacity=300, room_type="LECTURE", specialization_tags=set())}
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=1,
            kind="LEC",
            duration=3,
            group_ids=[1],
            prof_id=1,
            ta_id=2,
            requires_specialization=None,
        ),
        2: Activity(
            id=2,
            course_id=2,
            week=1,
            kind="LEC",
            duration=3,
            group_ids=[2],
            prof_id=1,
            ta_id=2,
            requires_specialization=None,
        ),
    }
    inst = build_instance(
        days=["SAT"],
        slots_per_day=5,
        weeks=[1],
        groups=groups,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    assert solve_status(inst) == cp_model.INFEASIBLE


def test_group_overlaps_render_instance_infeasible() -> None:
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1, 2]),
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
            name="Prof-2",
            is_prof=True,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={2},
            prefers_block=False,
            blocks_only=False,
        ),
        3: StaffMember(
            id=3,
            name="TA-1",
            is_prof=False,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1, 2},
            prefers_block=False,
            blocks_only=False,
        ),
    }
    rooms = {1: Room(id=1, name="L1", capacity=200, room_type="LECTURE", specialization_tags=set())}
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
            requires_specialization=None,
        ),
        2: Activity(
            id=2,
            course_id=2,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[1],
            prof_id=2,
            ta_id=3,
            requires_specialization=None,
        ),
    }
    inst = build_instance(
        days=["MON"],
        slots_per_day=1,
        weeks=[1],
        groups=groups,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    assert solve_status(inst) == cp_model.INFEASIBLE


def test_staff_overlaps_are_blocked() -> None:
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1]),
        2: Group(id=2, name="G2", program_id=1, size=30, course_ids=[2]),
    }
    staff = {
        1: StaffMember(
            id=1,
            name="TA-1",
            is_prof=False,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1, 2},
            prefers_block=False,
            blocks_only=False,
        ),
        2: StaffMember(
            id=2,
            name="Prof-1",
            is_prof=True,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        ),
        3: StaffMember(
            id=3,
            name="Prof-2",
            is_prof=True,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={2},
            prefers_block=False,
            blocks_only=False,
        ),
    }
    rooms = {1: Room(id=1, name="L1", capacity=150, room_type="LECTURE", specialization_tags=set())}
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=2,
            kind="TUT",
            duration=1,
            group_ids=[1],
            prof_id=2,
            ta_id=1,
            requires_specialization=None,
        ),
        2: Activity(
            id=2,
            course_id=2,
            week=2,
            kind="TUT",
            duration=1,
            group_ids=[2],
            prof_id=3,
            ta_id=1,
            requires_specialization=None,
        ),
    }
    inst = build_instance(
        days=["MON"],
        slots_per_day=1,
        weeks=[1, 2],
        groups=groups,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    assert solve_status(inst) == cp_model.INFEASIBLE


def test_staff_weekly_load_limit_enforced() -> None:
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1]),
    }
    staff = {
        1: StaffMember(
            id=1,
            name="Prof-1",
            is_prof=True,
            available_days={"MON", "TUE", "WED"},
            max_slots_per_day=None,
            max_slots_per_week=2,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        ),
        2: StaffMember(
            id=2,
            name="TA-1",
            is_prof=False,
            available_days={"MON", "TUE", "WED"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        ),
    }
    rooms = {1: Room(id=1, name="L1", capacity=120, room_type="LECTURE", specialization_tags=set())}
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
        3: Activity(
            id=3,
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
    inst = build_instance(
        days=["MON", "TUE", "WED"],
        slots_per_day=1,
        weeks=[1],
        groups=groups,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    assert solve_status(inst) == cp_model.INFEASIBLE


def test_lecture_room_capacity_limits_parallel_events() -> None:
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1]),
        2: Group(id=2, name="G2", program_id=1, size=30, course_ids=[2]),
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
            name="Prof-2",
            is_prof=True,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={2},
            prefers_block=False,
            blocks_only=False,
        ),
        3: StaffMember(
            id=3,
            name="TA-1",
            is_prof=False,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1, 2},
            prefers_block=False,
            blocks_only=False,
        ),
        4: StaffMember(
            id=4,
            name="TA-2",
            is_prof=False,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1, 2},
            prefers_block=False,
            blocks_only=False,
        ),
    }
    rooms = {1: Room(id=1, name="L1", capacity=80, room_type="LECTURE", specialization_tags=set())}
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
            requires_specialization=None,
        ),
        2: Activity(
            id=2,
            course_id=2,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[2],
            prof_id=2,
            ta_id=4,
            requires_specialization=None,
        ),
    }
    inst = build_instance(
        days=["MON"],
        slots_per_day=1,
        weeks=[1],
        groups=groups,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    assert solve_status(inst) == cp_model.INFEASIBLE


def test_big_lecture_capacity_obeys_limited_large_rooms() -> None:
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=90, course_ids=[1]),
        2: Group(id=2, name="G2", program_id=1, size=90, course_ids=[2]),
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
            name="Prof-2",
            is_prof=True,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={2},
            prefers_block=False,
            blocks_only=False,
        ),
        3: StaffMember(
            id=3,
            name="TA-1",
            is_prof=False,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1, 2},
            prefers_block=False,
            blocks_only=False,
        ),
        4: StaffMember(
            id=4,
            name="TA-2",
            is_prof=False,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1, 2},
            prefers_block=False,
            blocks_only=False,
        ),
    }
    rooms = {
        1: Room(id=1, name="BigL1", capacity=250, room_type="LECTURE", specialization_tags=set()),
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
            requires_specialization=None,
        ),
        2: Activity(
            id=2,
            course_id=2,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[2],
            prof_id=2,
            ta_id=4,
            requires_specialization=None,
        ),
    }
    inst = build_instance(
        days=["MON"],
        slots_per_day=1,
        weeks=[1],
        groups=groups,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    assert solve_status(inst) == cp_model.INFEASIBLE


def test_lab_room_capacity_limits_parallel_labs() -> None:
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=40, course_ids=[1]),
        2: Group(id=2, name="G2", program_id=1, size=40, course_ids=[2]),
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
            name="Prof-2",
            is_prof=True,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={2},
            prefers_block=False,
            blocks_only=False,
        ),
        3: StaffMember(
            id=3,
            name="TA-1",
            is_prof=False,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1, 2},
            prefers_block=False,
            blocks_only=False,
        ),
        4: StaffMember(
            id=4,
            name="TA-2",
            is_prof=False,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1, 2},
            prefers_block=False,
            blocks_only=False,
        ),
    }
    rooms = {
        1: Room(id=1, name="Lab1", capacity=40, room_type="SPECIALIZED_LAB", specialization_tags={"BIO"}),
    }
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=2,
            kind="LAB",
            duration=1,
            group_ids=[1],
            prof_id=1,
            ta_id=3,
            requires_specialization=None,
        ),
        2: Activity(
            id=2,
            course_id=2,
            week=2,
            kind="LAB",
            duration=1,
            group_ids=[2],
            prof_id=2,
            ta_id=4,
            requires_specialization=None,
        ),
    }
    inst = build_instance(
        days=["MON"],
        slots_per_day=1,
        weeks=[1, 2],
        groups=groups,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    assert solve_status(inst) == cp_model.INFEASIBLE


def test_specialized_lab_capacity_honours_per_tag_limits() -> None:
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=40, course_ids=[1]),
        2: Group(id=2, name="G2", program_id=1, size=40, course_ids=[2]),
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
            name="Prof-2",
            is_prof=True,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={2},
            prefers_block=False,
            blocks_only=False,
        ),
        3: StaffMember(
            id=3,
            name="TA-1",
            is_prof=False,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        ),
        4: StaffMember(
            id=4,
            name="TA-2",
            is_prof=False,
            available_days={"MON"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={2},
            prefers_block=False,
            blocks_only=False,
        ),
    }
    rooms = {
        1: Room(id=1, name="SpecLab", capacity=40, room_type="SPECIALIZED_LAB", specialization_tags={"BIO"}),
        2: Room(id=2, name="CompLab", capacity=40, room_type="COMPUTER_LAB", specialization_tags=set()),
    }
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=2,
            kind="LAB",
            duration=1,
            group_ids=[1],
            prof_id=1,
            ta_id=3,
            requires_specialization="BIO",
        ),
        2: Activity(
            id=2,
            course_id=2,
            week=2,
            kind="LAB",
            duration=1,
            group_ids=[2],
            prof_id=2,
            ta_id=4,
            requires_specialization="BIO",
        ),
    }
    inst = build_instance(
        days=["MON"],
        slots_per_day=1,
        weeks=[1, 2],
        groups=groups,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    assert solve_status(inst) == cp_model.INFEASIBLE


def test_shared_lecture_clusters_force_same_start_when_feasible() -> None:
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1]),
        2: Group(id=2, name="G2", program_id=1, size=30, course_ids=[1]),
    }
    staff = {
        1: StaffMember(
            id=1,
            name="Prof-A",
            is_prof=True,
            available_days={"MON", "TUE"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        ),
        2: StaffMember(
            id=2,
            name="Prof-B",
            is_prof=True,
            available_days={"MON", "TUE"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        ),
        3: StaffMember(
            id=3,
            name="TA",
            is_prof=False,
            available_days={"MON", "TUE"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        ),
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
            tutorial_count=0,
            lab_weeks=0,
            lab_duration=0,
            share_lecture_group_ids=[1, 2],
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
            ta_id=3,
            requires_specialization=None,
        ),
        2: Activity(
            id=2,
            course_id=1,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[2],
            prof_id=2,
            ta_id=3,
            requires_specialization=None,
        ),
    }
    inst = build_instance(
        days=["MON", "TUE"],
        slots_per_day=2,
        weeks=[1],
        groups=groups,
        staff=staff,
        rooms=rooms,
        activities=activities,
        courses=courses,
    )
    solver = TimetableSolver(inst)
    cp_solver, status = solver.solve()
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    day1 = extract_day(inst, solver, cp_solver, 1)
    day2 = extract_day(inst, solver, cp_solver, 2)
    slot1 = cp_solver.Value(solver.start[1]) % inst.slots_per_day
    slot2 = cp_solver.Value(solver.start[2]) % inst.slots_per_day
    assert day1 == day2
    assert slot1 == slot2


def test_disjoint_shared_lecture_availability_causes_infeasible_cluster() -> None:
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1]),
        2: Group(id=2, name="G2", program_id=1, size=30, course_ids=[1]),
    }
    staff = {
        1: StaffMember(
            id=1,
            name="Prof-A",
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
            name="Prof-B",
            is_prof=True,
            available_days={"TUE"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        ),
        3: StaffMember(
            id=3,
            name="TA",
            is_prof=False,
            available_days={"MON", "TUE"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        ),
    }
    rooms = {
        1: Room(id=1, name="L1", capacity=200, room_type="LECTURE", specialization_tags=set()),
    }
    courses = {
        1: Course(
            id=1,
            code="C1",
            name="Course 1",
            structure_type="LEC_TUT",
            lecture_count=12,
            tutorial_count=0,
            lab_weeks=0,
            lab_duration=0,
            share_lecture_group_ids=[1, 2],
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
            ta_id=3,
            requires_specialization=None,
        ),
        2: Activity(
            id=2,
            course_id=1,
            week=1,
            kind="LEC",
            duration=1,
            group_ids=[2],
            prof_id=2,
            ta_id=3,
            requires_specialization=None,
        ),
    }
    inst = build_instance(
        days=["MON", "TUE"],
        slots_per_day=2,
        weeks=[1],
        groups=groups,
        staff=staff,
        rooms=rooms,
        activities=activities,
        courses=courses,
    )

    assert solve_status(inst) == cp_model.INFEASIBLE


def test_week1_tutorials_are_rejected_early() -> None:
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1]),
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
    }
    rooms = {1: Room(id=1, name="L1", capacity=100, room_type="LECTURE", specialization_tags=set())}
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=1,
            kind="TUT",
            duration=1,
            group_ids=[1],
            prof_id=1,
            ta_id=1,
            requires_specialization=None,
        ),
    }
    inst = build_instance(
        days=["MON", "TUE"],
        slots_per_day=2,
        weeks=[1],
        groups=groups,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    with pytest.raises(ValueError, match="Week 1 must be lectures only"):
        TimetableSolver(inst)


def test_activity_longer_than_day_slots_raises() -> None:
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1]),
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
    rooms = {1: Room(id=1, name="L1", capacity=100, room_type="LECTURE", specialization_tags=set())}
    activities = {
        1: Activity(
            id=1,
            course_id=1,
            week=1,
            kind="LEC",
            duration=3,
            group_ids=[1],
            prof_id=1,
            ta_id=2,
            requires_specialization=None,
        ),
    }
    inst = build_instance(
        days=["MON"],
        slots_per_day=2,
        weeks=[1],
        groups=groups,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    with pytest.raises(ValueError, match="exceeds day slots"):
        TimetableSolver(inst)


def test_activity_with_no_allowed_start_times_raises() -> None:
    groups = {
        1: Group(id=1, name="G1", program_id=1, size=30, course_ids=[1]),
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
        ),
        2: StaffMember(
            id=2,
            name="TA-1",
            is_prof=False,
            available_days={"TUE"},
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses={1},
            prefers_block=False,
            blocks_only=False,
        ),
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
            ta_id=2,
            requires_specialization=None,
        ),
    }
    inst = build_instance(
        days=["MON"],
        slots_per_day=2,
        weeks=[1],
        groups=groups,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    with pytest.raises(ValueError, match="No allowed starts"):
        TimetableSolver(inst)
