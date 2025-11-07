from __future__ import annotations

import random
random.seed(12345)
from typing import Dict, List, Tuple

from domain import (
    Instance,
    Program,
    Group,
    Course,
    StaffMember,
    Room,
    Activity,
)


DAYS: List[str] = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
WEEKS: List[int] = list(range(1, 13))
SLOTS_PER_DAY: int = 5


def generate_instance(mode: str = "small_demo") -> Instance:
    """
    Entry point used by main.py and ui_desktop.py.

    Modes:
      - "small_demo"
      - "mixed_large"
      - "block_profs"
      - "labs_only"
      - "random"
      - "target_case"
    """

    if mode == "small_demo":
        return _generate_university(
            seed=1,
            num_programs=2,
            groups_per_program=(1, 2),
            courses_per_program=(4, 5),
        )

    if mode == "mixed_large":
        return _generate_university(
            seed=2,
            num_programs=25,
            groups_per_program=(1, 2),
            courses_per_program=(4, 7),
        )

    if mode == "block_profs":
        return _generate_university(
            seed=3,
            num_programs=20,
            groups_per_program=(1, 2),
            courses_per_program=(4, 7),
        )

    if mode == "labs_only":
        return _generate_university(
            seed=4,
            num_programs=10,
            groups_per_program=(1, 2),
            courses_per_program=(4, 6),
        )

    if mode == "random":
        rand_seed = random.randint(1, 10**9)
        num_programs = random.randint(10, 25)
        return _generate_university(
            seed=rand_seed,
            num_programs=num_programs,
            groups_per_program=(1, 2),
            courses_per_program=(4, 7),
        )

    if mode == "target_case":
        # main realistic target
        return _generate_university(
            seed=42,
            num_programs=20,
            groups_per_program=(1, 2),
            courses_per_program=(4, 7),
        )

    raise ValueError(f"Unknown generation mode: {mode}")


# ---------- core generator ----------


def _generate_university(
    seed: int,
    num_programs: int,
    groups_per_program: Tuple[int, int],
    courses_per_program: Tuple[int, int],
) -> Instance:
    """
    Generic builder for all modes, matching your domain model.

    Per program:
      - 1–2 groups
      - 4–7 courses
      - if #courses < max_courses: optionally ONE labs-only course
        (2-slot weekly lab, 12 weeks, no lectures/tutorials)
      - among non-lab courses, up to 3 can be block-lecture courses
        taught by special block professors.

    For each group and course:
      - non-lab, non-block course:
          * structure_type = "LEC_TUT"
          * one 1-slot lecture per week (shared by all groups in program)
          * one 1-slot tutorial per week per group
          * lecture_count = 12, tutorial_count = 12
      - block course:
          * structure_type = "LEC_TUT"
          * lectures in 4 blocks of 3 consecutive slots (weeks 1, 4, 7, 10)
            shared by all groups in program
          * tutorials weekly per group
          * lecture_count = 12 (4*3), tutorial_count = 12
      - labs-only course:
          * structure_type = "LAB_ONLY"
          * one 2-slot lab per week shared by all groups
          * lab_weeks = 12, lab_duration = 2, no lectures/tutorials

    By design and checked by _check_group_week_load, each group uses
    at most 20 slots/week (5 slots/day * 4 days), so 2 free days are
    mathematically possible.
    """

    rng = random.Random(seed)

    programs: Dict[int, Program] = {}
    groups: Dict[int, Group] = {}
    courses: Dict[int, Course] = {}
    staff: Dict[int, StaffMember] = {}
    rooms: Dict[int, Room] = {}
    activities: Dict[int, Activity] = {}

    # ----- groups and programs -----

    program_to_group_ids: Dict[int, List[int]] = {}
    next_group_id = 1

    for p in range(1, num_programs + 1):
        g_min, g_max = groups_per_program
        num_groups = rng.randint(g_min, g_max)
        g_ids: List[int] = []

        for gi in range(num_groups):
            g_id = next_group_id
            next_group_id += 1
            g_name = f"P{p}-G{gi+1}"
            size = rng.randint(40, 80)

            groups[g_id] = Group(
                id=g_id,
                name=g_name,
                program_id=p,
                size=size,
                course_ids=[],            # filled after courses created
                preferred_free_days=2,
            )
            g_ids.append(g_id)

        program_to_group_ids[p] = g_ids

    # ----- courses -----

    program_to_course_ids: Dict[int, List[int]] = {}
    next_course_id = 1
    min_c, max_c = courses_per_program

    # first create bare courses per program
    for p in range(1, num_programs + 1):
        num_courses = rng.randint(min_c, max_c)
        c_ids: List[int] = []

        for ci in range(num_courses):
            c_id = next_course_id
            next_course_id += 1
            code = f"C{c_id}"
            name = f"Course-{c_id}"

            # temporary defaults; structure_type etc. will be finalized below
            courses[c_id] = Course(
                id=c_id,
                code=code,
                name=name,
                structure_type="LEC_TUT",
                lecture_count=0,
                tutorial_count=0,
                lab_weeks=0,
                lab_duration=0,
                share_lecture_group_ids=[],
                prof_id=None,
                ta_id=None,
            )
            c_ids.append(c_id)

        program_to_course_ids[p] = c_ids

    total_courses = len(courses)

    # ----- choose labs-only and block courses per program -----

    labs_only_for_program: Dict[int, int] = {}
    block_courses: set[int] = set()
    BLOCK_WEEKS = [1, 4, 7, 10]

    for p in range(1, num_programs + 1):
        c_ids = program_to_course_ids[p]
        num_courses = len(c_ids)

        # optional labs-only if #courses < max_c
        labs_only_id: int | None = None
        if num_courses < max_c and num_courses > 0 and rng.random() < 0.5:
            labs_only_id = rng.choice(c_ids)
            labs_only_for_program[p] = labs_only_id

        # up to 3 block-lecture courses among non-lab courses
        nonlab_candidates = [c for c in c_ids if c != labs_only_id]
        if nonlab_candidates:
            n_block = rng.randint(0, min(3, len(nonlab_candidates)))
        else:
            n_block = 0

        if n_block > 0:
            chosen = rng.sample(nonlab_candidates, n_block)
            block_courses.update(chosen)

    # ----- staff (profs, block profs, TAs) -----

    prof_ids, ta_ids, block_prof_ids = _build_staff_pool(
        staff=staff,
        rng=rng,
        total_courses=total_courses,
    )

    prof_load = {sid: 0 for sid in prof_ids}
    ta_load = {sid: 0 for sid in ta_ids}
    block_prof_course_count = {sid: 0 for sid in block_prof_ids}
    max_block_courses_per_prof = 2  # keeps weekly load well under 8 slots

    # ----- rooms -----

    rooms.update(_build_target_case_rooms())

    # ----- assign courses to staff and finalise course metadata -----

    for p in range(1, num_programs + 1):
        g_ids = program_to_group_ids[p]
        c_ids = program_to_course_ids[p]
        labs_only_id = labs_only_for_program.get(p)

        for c_id in c_ids:
            # choose TA (lightest course count)
            ta_choice = min(ta_ids, key=lambda s: ta_load[s])
            ta_load[ta_choice] += 1

            # choose professor
            is_block_course = c_id in block_courses
            prof_choice: int | None = None

            if is_block_course and block_prof_ids:
                candidates = [
                    s
                    for s in block_prof_ids
                    if block_prof_course_count[s] < max_block_courses_per_prof
                ]
                if candidates:
                    prof_choice = min(candidates, key=lambda s: prof_load[s])
                    block_prof_course_count[prof_choice] += 1

            if prof_choice is None:
                prof_choice = min(prof_ids, key=lambda s: prof_load[s])

            prof_load[prof_choice] += 1

            # finalise course fields
            c = courses[c_id]
            c.share_lecture_group_ids = list(g_ids)
            c.prof_id = prof_choice
            c.ta_id = ta_choice

            # add course to staff can_teach_courses
            staff[prof_choice].can_teach_courses.add(c_id)
            staff[ta_choice].can_teach_courses.add(c_id)

            # structure and counts
            if labs_only_id is not None and c_id == labs_only_id:
                c.structure_type = "LAB_ONLY"
                c.lecture_count = 0
                c.tutorial_count = 0
                c.lab_weeks = 12
                c.lab_duration = 2
            else:
                c.structure_type = "LEC_TUT"
                c.lecture_count = 12  # total lecture slots
                c.tutorial_count = 12
                c.lab_weeks = 0
                c.lab_duration = 0

    # ----- assign course_ids to groups and build Program objects -----

    programs: Dict[int, Program] = {}
    for p in range(1, num_programs + 1):
        c_ids = program_to_course_ids[p]
        g_ids = program_to_group_ids[p]

        for g_id in g_ids:
            groups[g_id].course_ids = list(c_ids)

        programs[p] = Program(
            id=p,
            name=f"Program-{p}",
            course_ids=list(c_ids),
            group_ids=list(g_ids),
        )

    # ----- activities based on course structure -----

    activities = {}
    next_act_id = 1

    for p in range(1, num_programs + 1):
        g_ids = program_to_group_ids[p]
        c_ids = program_to_course_ids[p]
        labs_only_id = labs_only_for_program.get(p)

        for c_id in c_ids:
            c = courses[c_id]
            prof_id = c.prof_id
            ta_id = c.ta_id
            is_block_course = c_id in block_courses

            if labs_only_id is not None and c_id == labs_only_id:
                # labs-only: 2-slot lab per week, all groups
                spec_tag = random.choice(["LAB1", "LAB2", "LAB3"])
                for week in WEEKS:
                    act_id = next_act_id
                    next_act_id += 1
                    activities[act_id] = Activity(
                        id=act_id,
                        course_id=c_id,
                        week=week,
                        kind="LAB",
                        duration=2,
                        group_ids=list(g_ids),
                        prof_id=prof_id,
                        ta_id=ta_id,
                        requires_specialization=spec_tag,
                    )
                continue

            # non-lab course: lectures + tutorials
            if is_block_course:
                # 4 blocks, each 3 consecutive slots, shared by all groups
                for week in BLOCK_WEEKS:
                    act_id = next_act_id
                    next_act_id += 1
                    activities[act_id] = Activity(
                        id=act_id,
                        course_id=c_id,
                        week=week,
                        kind="LEC",
                        duration=3,
                        group_ids=list(g_ids),
                        prof_id=prof_id,
                        ta_id=ta_id,
                        requires_specialization=None,
                    )
            else:
                # standard lecture: 1 slot per week, shared by all groups
                for week in WEEKS:
                    act_id = next_act_id
                    next_act_id += 1
                    activities[act_id] = Activity(
                        id=act_id,
                        course_id=c_id,
                        week=week,
                        kind="LEC",
                        duration=1,
                        group_ids=list(g_ids),
                        prof_id=prof_id,
                        ta_id=ta_id,
                        requires_specialization=None,
                    )

            # tutorials: 1 slot per week, per group
            for week in WEEKS:
                for g_id in g_ids:
                    act_id = next_act_id
                    next_act_id += 1
                    activities[act_id] = Activity(
                        id=act_id,
                        course_id=c_id,
                        week=week,
                        kind="TUT",
                        duration=1,
                        group_ids=[g_id],
                        prof_id=prof_id,
                        ta_id=ta_id,
                        requires_specialization=None,
                    )

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

    _check_group_week_load(inst)
    return inst


# ---------- staff + rooms + sanity check ----------


def _build_staff_pool(
    staff: Dict[int, StaffMember],
    rng: random.Random,
    total_courses: int,
) -> tuple[List[int], List[int], List[int]]:
    """
    Build academics:

      - 0–3 "block professors":
          * is_prof = True
          * prefers_block = True, blocks_only = True
          * available_days = {"SAT"} or {"FRI","SAT"}
          * max_slots_per_week = 8 (hard cap)
      - remaining professors:
          * is_prof = True
          * available_days = all teaching days
          * no hard weekly cap
      - TAs:
          * is_prof = False
          * available_days = all teaching days
    """

    prof_ids: List[int] = []
    ta_ids: List[int] = []
    block_prof_ids: List[int] = []

    num_profs = max(8, total_courses // 3)
    # 0–3 block professors
    num_block = rng.randint(0, min(3, num_profs))
    num_regular = num_profs - num_block

    next_staff_id = 1

    # block professors
    for _ in range(num_block):
        s_id = next_staff_id
        next_staff_id += 1

        if rng.random() < 0.5:
            days = {"SAT"}
        else:
            days = {"FRI", "SAT"}

        staff[s_id] = StaffMember(
            id=s_id,
            name=f"Prof-{s_id}",
            is_prof=True,
            available_days=days,
            max_slots_per_day=None,
            max_slots_per_week=8,
            can_teach_courses=set(),
            prefers_block=True,
            blocks_only=True,
        )
        prof_ids.append(s_id)
        block_prof_ids.append(s_id)

    # regular professors
    for _ in range(num_regular):
        s_id = next_staff_id
        next_staff_id += 1

        staff[s_id] = StaffMember(
            id=s_id,
            name=f"Prof-{s_id}",
            is_prof=True,
            available_days=set(DAYS),
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses=set(),
            prefers_block=False,
            blocks_only=False,
        )
        prof_ids.append(s_id)

    # TAs
    num_tas = max(8, total_courses // 4)
    for _ in range(num_tas):
        s_id = next_staff_id
        next_staff_id += 1

        staff[s_id] = StaffMember(
            id=s_id,
            name=f"TA-{s_id}",
            is_prof=False,
            available_days=set(DAYS),
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses=set(),
            prefers_block=False,
            blocks_only=False,
        )
        ta_ids.append(s_id)

    return prof_ids, ta_ids, block_prof_ids


def _build_target_case_rooms() -> Dict[int, Room]:
    """
    25 total rooms:

      - 15 regular lecture rooms (capacity for any single group)
      - 5 big lecture rooms (capacity for all groups together)
      - 3 specialised labs (LAB1–LAB3)
      - 2 computer labs
    """

    rooms: Dict[int, Room] = {}
    next_room_id = 1

    # regular lecture rooms
    for i in range(15):
        r_id = next_room_id
        next_room_id += 1
        rooms[r_id] = Room(
            id=r_id,
            name=f"Lec-{i+1}",
            capacity=80,
            room_type="LECTURE",
            specialization_tags=set(),
        )

    # big lecture rooms
    for i in range(5):
        r_id = next_room_id
        next_room_id += 1
        rooms[r_id] = Room(
            id=r_id,
            name=f"BigLec-{i+1}",
            capacity=400,
            room_type="LECTURE",
            specialization_tags=set(),
        )

     # specialised labs
    spec_tags = ["LAB1", "LAB2", "LAB3"]
    for i, tag in enumerate(spec_tags):
        r_id = next_room_id
        next_room_id += 1
        rooms[r_id] = Room(
            id=r_id,
            name=f"SpecLab-{i+1}",
            capacity=160,          # was 40; now large enough for 2 groups of 80
            room_type="SPECIALIZED_LAB",
            specialization_tags={tag},
        )

    # computer labs
    for i in range(2):
        r_id = next_room_id
        next_room_id += 1
        rooms[r_id] = Room(
            id=r_id,
            name=f"CompLab-{i+1}",
            capacity=40,
            room_type="COMPUTER_LAB",
            specialization_tags=set(),
        )

    return rooms


def _check_group_week_load(inst: Instance) -> None:
    """
    Sanity check: for every group and week, ensure total used slots <= 20.

    With 5 slots/day this means each group can in principle be scheduled
    on at most 4 teaching days, leaving 2 free days.
    """

    max_days_with_teaching = 4
    max_slots_allowed = max_days_with_teaching * inst.slots_per_day  # 20

    load: Dict[Tuple[int, int], int] = {}  # (group_id, week) -> total slots

    for act in inst.activities.values():
        for g_id in act.group_ids:
            key = (g_id, act.week)
            load[key] = load.get(key, 0) + act.duration

    for (g_id, w), used in load.items():
        if used > max_slots_allowed:
            raise ValueError(
                f"Generator bug: group {g_id} in week {w} uses "
                f"{used} slots (> {max_slots_allowed})"
            )
