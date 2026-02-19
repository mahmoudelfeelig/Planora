from __future__ import annotations

import random
from typing import Dict, List, Tuple

from utils.domain import Activity, Course, Group, Instance, Program, Room, StaffMember
from utils.generator import DAYS, WEEKS, SLOTS_PER_DAY, _distribute_sessions, _check_group_week_load
from utils.generator import _inject_cross_major_clusters


def generate_target_profile(seed: int = 42) -> Instance:
    rng = random.Random(seed)

    num_programs = rng.randint(15, 20)
    groups_per_program: Tuple[int, int] = (1, 2)
    courses_per_program: Tuple[int, int] = (5, 7)

    programs: Dict[int, Program] = {}
    groups: Dict[int, Group] = {}
    courses: Dict[int, Course] = {}
    staff: Dict[int, StaffMember] = {}
    rooms: Dict[int, Room] = {}
    activities: Dict[int, Activity] = {}

    # Groups/programs
    program_to_group_ids: Dict[int, List[int]] = {}
    next_group_id = 1
    for p in range(1, num_programs + 1):
        num_groups = rng.randint(*groups_per_program)
        g_ids: List[int] = []
        for gi in range(num_groups):
            g_id = next_group_id; next_group_id += 1
            groups[g_id] = Group(
                id=g_id,
                name=f"P{p}-G{gi+1}",
                program_id=p,
                size=rng.randint(40, 80),
                course_ids=[],
                preferred_free_days=2,
            )
            g_ids.append(g_id)
        program_to_group_ids[p] = g_ids

    # Courses
    program_to_course_ids: Dict[int, List[int]] = {}
    next_course_id = 1
    for p in range(1, num_programs + 1):
        num_courses = rng.randint(*courses_per_program)
        c_ids: List[int] = []
        for _ in range(num_courses):
            c_id = next_course_id; next_course_id += 1
            courses[c_id] = Course(
                id=c_id,
                code=f"C{c_id}",
                name=f"Course-{c_id}",
                structure_type="LEC_TUT",
                lecture_count=12,
                tutorial_count=12,
                lab_weeks=0,
                lab_duration=0,
                share_lecture_group_ids=[],
                prof_id=None,
                ta_id=None,
            )
            c_ids.append(c_id)
        program_to_course_ids[p] = c_ids

    # Four specific lab courses
    specific_lab_tags = ["LABA", "LABB", "LABC", "LABD"]
    specific_lab_courses: Dict[int, str] = {}
    pick = rng.sample(list(courses.keys()), k=min(len(specific_lab_tags), len(courses)))
    for cid, tag in zip(pick, specific_lab_tags):
        specific_lab_courses[cid] = tag

    # Block courses (optional). For solvability, keep none by default.
    block_courses: set[int] = set()

    # Share lectures for clustered groups
    for p, c_ids in program_to_course_ids.items():
        g_ids = program_to_group_ids[p]
        for cid in c_ids:
            if len(g_ids) >= 2:
                courses[cid].share_lecture_group_ids = list(g_ids)

    # Staff pool
    total_courses = len(courses)
    prof_ids: List[int] = []
    block_prof_ids: List[int] = []  # disabled for solvability
    ta_ids: List[int] = []
    next_staff_id = 1

    # Regular professors: 1–4 courses each target
    num_profs = max(25, total_courses // 3)
    for _ in range(num_profs):
        s_id = next_staff_id; next_staff_id += 1
        staff[s_id] = StaffMember(
            id=s_id, name=f"Prof-{s_id}", is_prof=True,
            available_days=set(DAYS),
            max_slots_per_day=None, max_slots_per_week=None,
            can_teach_courses=set(),
            prefers_block=False, blocks_only=False,
        )
        prof_ids.append(s_id)

    # TAs: each off one day; 3–4 courses each
    num_tas = max(10, (total_courses + 3) // 4)
    for _ in range(num_tas):
        s_id = next_staff_id; next_staff_id += 1
        off_day = rng.choice(DAYS)
        avail = set(DAYS) - {off_day}
        staff[s_id] = StaffMember(
            id=s_id, name=f"TA-{s_id}", is_prof=False,
            available_days=avail,
            max_slots_per_day=None, max_slots_per_week=None,
            can_teach_courses=set(),
            prefers_block=False, blocks_only=False,
        )
        ta_ids.append(s_id)

    # Rooms (big/small lecture, tutorial, specific labs, PC labs)
    rooms.update(_build_target_profile_rooms(rng))
    for r in rooms.values():
        r.availability = {(d, s) for d in DAYS for s in range(SLOTS_PER_DAY)}

    # Assign staff to courses respecting loads
    prof_load = {sid: 0 for sid in prof_ids}
    ta_load = {sid: 0 for sid in ta_ids}
    block_prof_course_count = {}
    prof_course_cap = 4

    regular_prof_ids = [p for p in prof_ids if p not in block_prof_ids]

    for c_id, c in courses.items():
        is_specific_lab = c_id in specific_lab_courses
        is_block = c_id in block_courses

        # professor
        prof_choice = None
        candidates = [s for s in regular_prof_ids if prof_load[s] < prof_course_cap] or regular_prof_ids
        prof_choice = min(candidates, key=lambda s: prof_load[s])
        prof_load[prof_choice] += 1
        c.prof_id = prof_choice
        staff[prof_choice].can_teach_courses.add(c_id)

        # TA
        ta_candidates = [s for s in ta_ids if ta_load[s] < 4] or ta_ids
        ta_choice = min(ta_candidates, key=lambda s: ta_load[s])
        ta_load[ta_choice] += 1
        c.ta_id = ta_choice
        staff[ta_choice].can_teach_courses.add(c_id)

        # Structure
        if is_specific_lab:
            c.structure_type = "LEC_TUT_LAB"
            c.lecture_count = rng.choices([12, 18, 24], weights=[0.7, 0.2, 0.1])[0]
            c.tutorial_count = rng.choices([12, 18, 24], weights=[0.7, 0.2, 0.1])[0]
            c.lab_weeks = 12
            c.lab_duration = 2
        elif is_block:
            c.structure_type = "LEC_TUT"
            c.lecture_count = 12
            c.tutorial_count = rng.choices([12, 18, 24], weights=[0.7, 0.2, 0.1])[0]
            c.lab_weeks = 0
            c.lab_duration = 0
        else:
            c.structure_type = rng.choices(["LEC_ONLY", "LEC_TUT"], weights=[0.1, 0.9])[0]
            c.lecture_count = rng.choices([12, 18, 24], weights=[0.7, 0.2, 0.1])[0]
            if c.structure_type == "LEC_ONLY":
                c.tutorial_count = 0
                c.lab_weeks = 0
                c.lab_duration = 0
            else:
                c.tutorial_count = rng.choices([12, 18, 24], weights=[0.7, 0.2, 0.1])[0]
                c.lab_weeks = 0
                c.lab_duration = 0

    # Assign course ids to groups and build Program objects
    for p in range(1, num_programs + 1):
        c_ids = program_to_course_ids[p]
        g_ids = program_to_group_ids[p]
        for g_id in g_ids:
            groups[g_id].course_ids = list(c_ids)
        programs[p] = Program(id=p, name=f"Program-{p}", course_ids=list(c_ids), group_ids=list(g_ids))

    # Activities
    activities = {}
    next_act_id = 1
    tut_weeks = list(range(2, 13))

    for p in range(1, num_programs + 1):
        g_ids = program_to_group_ids[p]
        c_ids = program_to_course_ids[p]

        for c_id in c_ids:
            c = courses[c_id]
            prof_id = c.prof_id
            ta_id = c.ta_id
            # lectures
            if c_id in block_courses:
                for week in [1, 5, 9]:
                    act_id = next_act_id; next_act_id += 1
                    activities[act_id] = Activity(
                        id=act_id, course_id=c_id, week=week,
                        kind="LEC", duration=3, group_ids=list(g_ids),
                        prof_id=prof_id, ta_id=ta_id, requires_specialization=None,
                    )
            else:
                lec_counts = _distribute_sessions(int(c.lecture_count), WEEKS, rng=rng)
                for week in WEEKS:
                    for _ in range(lec_counts.get(week, 0)):
                        act_id = next_act_id; next_act_id += 1
                        activities[act_id] = Activity(
                            id=act_id, course_id=c_id, week=week,
                            kind="LEC", duration=1, group_ids=list(g_ids),
                            prof_id=prof_id, ta_id=ta_id, requires_specialization=None,
                        )
            # tutorials
            if c.tutorial_count > 0:
                tut_counts = _distribute_sessions(int(c.tutorial_count), tut_weeks, rng=rng)
                for week in tut_weeks:
                    for g in g_ids:
                        for _ in range(tut_counts.get(week, 0)):
                            act_id = next_act_id; next_act_id += 1
                            activities[act_id] = Activity(
                                id=act_id, course_id=c_id, week=week,
                                kind="TUT", duration=1, group_ids=[g],
                                prof_id=prof_id, ta_id=ta_id, requires_specialization=None,
                            )
            # labs
            if c.lab_weeks > 0 and c.lab_duration > 0:
                lab_counts = _distribute_sessions(int(c.lab_weeks), tut_weeks, rng=rng)
                req_tag = specific_lab_courses.get(c_id)
                for week in tut_weeks:
                    for _ in range(lab_counts.get(week, 0)):
                        act_id = next_act_id; next_act_id += 1
                        activities[act_id] = Activity(
                            id=act_id, course_id=c_id, week=week,
                            kind="LAB", duration=int(c.lab_duration), group_ids=list(g_ids),
                            prof_id=prof_id, ta_id=ta_id, requires_specialization=req_tag,
                        )

    _inject_cross_major_clusters(activities, groups, courses, rng, target_profile=True)

    inst = Instance(
        days=list(DAYS),
        slots_per_day=SLOTS_PER_DAY,
        weeks=list(WEEKS),
        programs=programs,
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )

    # Soft warnings only
    _check_group_week_load(inst, hard_cap=None)
    return inst


def _build_target_profile_rooms(rng: random.Random) -> Dict[int, Room]:
    rooms: Dict[int, Room] = {}
    next_room_id = 1

    # big lecture
    for i in range(10):
        r_id = next_room_id; next_room_id += 1
        rooms[r_id] = Room(
            id=r_id, name=f"BigLec-{i+1}",
            capacity=500, room_type="LECTURE", specialization_tags=set(),
        )
    # small lecture (can host tutorials)
    for i in range(5):
        r_id = next_room_id; next_room_id += 1
        rooms[r_id] = Room(
            id=r_id, name=f"SmallLec-{i+1}",
            capacity=150, room_type="LECTURE", specialization_tags=set(),
        )
    # tutorial rooms
    for i in range(10):
        r_id = next_room_id; next_room_id += 1
        rooms[r_id] = Room(
            id=r_id, name=f"Tut-{i+1}",
            capacity=100, room_type="TUTORIAL", specialization_tags=set(),
        )
    # specific labs
    for tag in ["LABA", "LABB", "LABC", "LABD"]:
        r_id = next_room_id; next_room_id += 1
        rooms[r_id] = Room(
            id=r_id, name=f"Spec-{tag}",
            capacity=500, room_type="SPECIALIZED_LAB", specialization_tags={tag},
        )
    # PC labs
    num_pc = rng.randint(5, 7)
    for i in range(num_pc):
        r_id = next_room_id; next_room_id += 1
        rooms[r_id] = Room(
            id=r_id, name=f"PC-Lab-{i+1}",
            capacity=200, room_type="COMPUTER_LAB", specialization_tags=set(),
        )
    return rooms
