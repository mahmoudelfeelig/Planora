from __future__ import annotations

from collections import defaultdict

import pytest

from generator import generate_instance


@pytest.fixture(scope="module")
def demo_instance():
    # small_demo is deterministic and fast, making it ideal for spec checks
    return generate_instance("small_demo")


def test_time_grid_matches_schedule_spec(demo_instance):
    assert demo_instance.days == ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
    assert demo_instance.slots_per_day == 5
    assert demo_instance.weeks == list(range(1, 13))


def test_program_groups_share_course_catalog(demo_instance):
    for program in demo_instance.programs.values():
        for group_id in program.group_ids:
            group = demo_instance.groups[group_id]
            assert group.program_id == program.id
            assert set(group.course_ids) == set(program.course_ids)


def test_block_professors_follow_documented_limits(demo_instance):
    for staff in demo_instance.staff.values():
        if not staff.blocks_only:
            continue
        assert staff.is_prof
        assert staff.prefers_block
        assert staff.max_slots_per_week == 8
        # allowed days per specification: either {"SAT"} or {"FRI","SAT"}
        assert staff.available_days.issubset({"FRI", "SAT"})
        assert staff.available_days


def test_group_weekly_load_stays_within_four_days(demo_instance):
    max_slots = 4 * demo_instance.slots_per_day
    usage = defaultdict(int)

    for act in demo_instance.activities.values():
        for g_id in act.group_ids:
            usage[(g_id, act.week)] += act.duration

    for total in usage.values():
        assert total <= max_slots


def test_labs_only_courses_have_weekly_specialized_labs(demo_instance):
    labs_only_courses = [c for c in demo_instance.courses.values() if c.structure_type == "LAB_ONLY"]
    if not labs_only_courses:
        pytest.skip("No labs-only courses in small_demo instance")

    for course in labs_only_courses:
        acts = [a for a in demo_instance.activities.values() if a.course_id == course.id]
        assert acts
        assert all(act.kind == "LAB" for act in acts)
        assert all(act.requires_specialization for act in acts)
        assert all(act.duration == course.lab_duration for act in acts)
        assert len(acts) == len(demo_instance.weeks)


def test_block_courses_have_expected_block_weeks(demo_instance):
    block_weeks = {1, 4, 7, 10}
    block_courses = []

    for course in demo_instance.courses.values():
        lectures = [
            act for act in demo_instance.activities.values()
            if act.course_id == course.id and act.kind == "LEC"
        ]
        block_lectures = [act for act in lectures if act.duration == 3]
        if block_lectures:
            block_courses.append(course.id)
            assert {act.week for act in block_lectures} == block_weeks

    if not block_courses:
        pytest.skip("No block courses generated for this scenario")


def test_each_group_has_weekly_tutorials_per_course(demo_instance):
    week_count = len(demo_instance.weeks)
    for course in demo_instance.courses.values():
        if course.structure_type == "LAB_ONLY":
            continue
        enrolled_groups = [
            g.id for g in demo_instance.groups.values()
            if course.id in g.course_ids
        ]
        if not enrolled_groups:
            continue
        tutorials = [
            act for act in demo_instance.activities.values()
            if act.course_id == course.id and act.kind == "TUT"
        ]
        for g_id in enrolled_groups:
            acts_for_group = [act for act in tutorials if g_id in act.group_ids]
            assert len(acts_for_group) == week_count


def test_staff_can_teach_sets_include_assigned_courses(demo_instance):
    courses_by_staff = defaultdict(set)
    for course in demo_instance.courses.values():
        if course.prof_id is not None:
            courses_by_staff[course.prof_id].add(course.id)
        if course.ta_id is not None:
            courses_by_staff[course.ta_id].add(course.id)

    for staff_id, course_ids in courses_by_staff.items():
        staff = demo_instance.staff[staff_id]
        assert course_ids.issubset(staff.can_teach_courses)
