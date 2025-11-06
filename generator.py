import random
from typing import Dict, List
from domain import (
    Instance, Program, Group, Course, Staff, Room, Activity,
    Day, WeekIndex,
)


def _base_calendar():
    days: List[Day] = ["SAT", "MON", "TUE", "WED", "THU", "FRI"]
    slots_per_day = 5
    weeks: List[WeekIndex] = list(range(1, 13))
    return days, slots_per_day, weeks


def _make_basic_rooms() -> Dict[int, Room]:
    rooms: Dict[int, Room] = {}
    rid = 1

    # A few lecture/tutorial rooms with different capacities
    for cap in [40, 60, 80, 120]:
        rooms[rid] = Room(
            id=rid,
            name=f"Room-{rid}-LecTut-{cap}",
            room_type="LECTURE",
            capacity=cap,
        )
        rid += 1

    # Computer labs
    for _ in range(3):
        rooms[rid] = Room(
            id=rid,
            name=f"CompLab-{rid}",
            room_type="COMPUTER_LAB",
            capacity=30,
        )
        rid += 1

    # Specialized labs
    for tag in ["PHYSICS_LAB", "CHEM_LAB"]:
        rooms[rid] = Room(
            id=rid,
            name=f"{tag}-1",
            room_type="SPECIALIZED_LAB",
            capacity=24,
            specialization_tags={tag},
        )
        rid += 1

    return rooms


def _make_staff(num_profs: int, num_tas: int, courses: Dict[int, Course]) -> Dict[int, Staff]:
    staff: Dict[int, Staff] = {}
    sid = 1
    course_ids = list(courses.keys())

    def random_course_subset(k: int):
        return set(random.sample(course_ids, min(k, len(course_ids)))) if course_ids else set()

    # Professors
    for _ in range(num_profs):
        is_block = random.random() < 0.3
        available_days = {"SAT", "MON", "TUE", "WED", "THU", "FRI"}
        block_days = set()
        if is_block:
            # Many block profs teach only Fri/Sat or SAT alone
            options = [
                {"SAT"},
                {"FRI"},
                {"SAT", "FRI"},
            ]
            block_days = random.choice(options)
            available_days = block_days.copy()

        staff[sid] = Staff(
            id=sid,
            name=f"Prof-{sid}",
            is_professor=True,
            is_block_professor=is_block,
            available_days=available_days,
            max_slots_per_day=3,
            max_slots_per_week=8,
            skilled_course_ids=random_course_subset(4),
            block_allowed_days=block_days,
        )
        sid += 1

    # TAs – usually available all days except Sunday + one free day
    for _ in range(num_tas):
        all_days = {"SAT", "MON", "TUE", "WED", "THU", "FRI"}
        free_extra = random.choice(list(all_days))
        available_days = all_days - {free_extra}
        staff[sid] = Staff(
            id=sid,
            name=f"TA-{sid}",
            is_professor=False,
            is_block_professor=False,
            available_days=available_days,
            max_slots_per_day=4,
            max_slots_per_week=12,
            skilled_course_ids=random_course_subset(3),
        )
        sid += 1

    return staff


def _make_activities(
    groups: Dict[int, Group],
    courses: Dict[int, Course],
    staff: Dict[int, Staff],
    weeks,
    block_heavy: bool = False,
    labs_heavy: bool = False,
) -> Dict[int, Activity]:
    """
    Builds activities per course/group/week with:
      - lectures only in week 1
      - tutorials and labs in weeks 2–12
      - lab duration stored in course.lab_duration
    Block-only profs will get longer lecture activities (2–3 slots) in a single day.
    """
    activities: Dict[int, Activity] = {}
    aid = 1

    # Precompute staff candidates per course
    staff_candidates_for_course: Dict[int, List[int]] = {c_id: [] for c_id in courses}
    for s_id, s in staff.items():
        for c_id in s.skilled_course_ids:
            if c_id in courses:
                staff_candidates_for_course[c_id].append(s_id)

    # pattern_id groups replications of the same weekly event across weeks
    next_pattern_id = 1

    for c_id, course in courses.items():
        # For simplicity, assume 1 lecture per week, 1 tutorial per week, 1 lab per week when present.
        # That gives 12 each, matching the 12 variant.
        # You can extend to 18/24 by adding extra weekly lecture activities.
        lecture_weeks = weeks
        tutorial_weeks = weeks[1:] if course.tutorial_count > 0 else []
        lab_weeks = weeks[1:] if course.lab_weeks > 0 else []

        # Staff candidates
        lec_staff = staff_candidates_for_course.get(c_id, [])
        tut_staff = lec_staff  # many places share pool; customize if you want
        lab_staff = lec_staff  # or TAs only, etc.

        # If there are no staff candidates for a course, you will get infeasibility,
        # which is useful for testing error reporting.
        if not lec_staff:
            # assign all professors as fallbacks
            lec_staff = [s.id for s in staff.values() if s.is_professor]
        if not tut_staff:
            tut_staff = [s.id for s in staff.values() if not s.is_professor] or lec_staff
        if not lab_staff:
            lab_staff = [s.id for s in staff.values() if not s.is_professor] or lec_staff

        # Each group in the course gets its own tutorials and labs
        groups_in_course = [g for g in groups.values() if c_id in g.course_ids]

        # Shared lectures across those groups
        shared_group_ids = [g.id for g in groups_in_course] if course.share_lecture_group_ids else [g.id for g in groups_in_course]

        # Lectures
        if lecture_weeks:
            lec_pattern_id = next_pattern_id
            next_pattern_id += 1
            for w in lecture_weeks:
                # If block-heavy, some lectures will be 2-slot activities by construction
                dur = 2 if block_heavy else 1
                activities[aid] = Activity(
                    id=aid,
                    course_id=c_id,
                    group_ids=shared_group_ids,
                    kind="LEC",
                    duration_slots=dur,
                    week=w,
                    staff_candidates=lec_staff,
                    requires_specialization=None,
                    pattern_id=lec_pattern_id,
                )
                aid += 1

        # Tutorials
        if tutorial_weeks and course.structure_type in ("LEC_TUT", "LEC_TUT_LAB"):
            for g in groups_in_course:
                tut_pattern_id = next_pattern_id
                next_pattern_id += 1
                for w in tutorial_weeks:
                    activities[aid] = Activity(
                        id=aid,
                        course_id=c_id,
                        group_ids=[g.id],
                        kind="TUT",
                        duration_slots=1,
                        week=w,
                        staff_candidates=tut_staff,
                        requires_specialization=None,
                        pattern_id=tut_pattern_id,
                    )
                    aid += 1

        # Labs
        if lab_weeks and course.structure_type in ("LEC_TUT_LAB", "LAB_ONLY"):
            for g in groups_in_course:
                lab_pattern_id = next_pattern_id
                next_pattern_id += 1
                for w in lab_weeks:
                    dur = course.lab_duration
                    spec = None
                    if labs_heavy:
                        # use specialization labels to force specific labs
                        spec = random.choice(["PHYSICS_LAB", "CHEM_LAB"])
                    activities[aid] = Activity(
                        id=aid,
                        course_id=c_id,
                        group_ids=[g.id],
                        kind="LAB",
                        duration_slots=dur,
                        week=w,
                        staff_candidates=lab_staff,
                        requires_specialization=spec,
                        pattern_id=lab_pattern_id,
                    )
                    aid += 1

    return activities


def generate_instance(mode: str = "small_demo") -> Instance:
    days, slots_per_day, weeks = _base_calendar()

    programs: Dict[int, Program] = {}
    groups: Dict[int, Group] = {}
    courses: Dict[int, Course] = {}

    # Build programs, groups, courses according to the mode
    pid = 1
    gid = 1
    cid = 1

    if mode == "small_demo":
        # Two programs, one group each, three courses total
        for p in range(2):
            prog_course_ids = []
            prog_group_ids = []
            for _ in range(2):  # 2 courses per program, share some
                course = Course(
                    id=cid,
                    code=f"C{cid}",
                    name=f"Course-{cid}",
                    structure_type=random.choice(["LEC_ONLY", "LEC_TUT", "LEC_TUT_LAB"]),
                    lecture_count=12,
                    tutorial_count=12,
                    lab_weeks=12 if random.random() < 0.5 else 0,
                    lab_duration=random.choice([1, 2]),
                    share_lecture_group_ids=[],
                )
                courses[cid] = course
                prog_course_ids.append(cid)
                cid += 1
            group = Group(
                id=gid,
                name=f"G{gid}",
                program_id=pid,
                size=random.randint(20, 80),
                course_ids=prog_course_ids,
                preferred_free_days=2,
            )
            groups[gid] = group
            prog_group_ids.append(gid)
            programs[pid] = Program(
                id=pid,
                name=f"Program-{pid}",
                course_ids=prog_course_ids,
                group_ids=prog_group_ids,
            )
            gid += 1
            pid += 1

    elif mode == "block_profs":
        # One program, 2 groups, 4 courses, set up for block-only professors
        prog_course_ids = []
        prog_group_ids = []
        for _ in range(4):
            course = Course(
                id=cid,
                code=f"B{cid}",
                name=f"BlockCourse-{cid}",
                structure_type="LEC_TUT",
                lecture_count=12,
                tutorial_count=12,
                lab_weeks=0,
                lab_duration=1,
                share_lecture_group_ids=[gid, gid + 1],
            )
            courses[cid] = course
            prog_course_ids.append(cid)
            cid += 1

        for i in range(2):
            group = Group(
                id=gid,
                name=f"BlockGroup-{gid}",
                program_id=pid,
                size=50,
                course_ids=prog_course_ids,
                preferred_free_days=2,
            )
            groups[gid] = group
            prog_group_ids.append(gid)
            gid += 1

        programs[pid] = Program(
            id=pid,
            name="BlockProgram",
            course_ids=prog_course_ids,
            group_ids=prog_group_ids,
        )

    elif mode == "labs_only":
        # Focus on lab-only and lab-heavy courses
        prog_course_ids = []
        prog_group_ids = []
        for _ in range(3):
            course = Course(
                id=cid,
                code=f"L{cid}",
                name=f"LabCourse-{cid}",
                structure_type=random.choice(["LAB_ONLY", "LEC_TUT_LAB"]),
                lecture_count=12,
                tutorial_count=12,
                lab_weeks=12,
                lab_duration=random.choice([1, 2]),
                share_lecture_group_ids=[],
            )
            courses[cid] = course
            prog_course_ids.append(cid)
            cid += 1

        for i in range(3):
            group = Group(
                id=gid,
                name=f"LabGroup-{gid}",
                program_id=pid,
                size=random.randint(20, 35),
                course_ids=prog_course_ids,
                preferred_free_days=2,
            )
            groups[gid] = group
            prog_group_ids.append(gid)
            gid += 1

        programs[pid] = Program(
            id=pid,
            name="LabProgram",
            course_ids=prog_course_ids,
            group_ids=prog_group_ids,
        )

    elif mode in ("mixed_large", "random"):
        # Something closer to your scale: ~20 programs, 1–2 groups each, 5–6 courses each
        num_programs = 20 if mode == "mixed_large" else random.randint(10, 25)
        for _ in range(num_programs):
            prog_course_ids = []
            prog_group_ids = []

            num_courses = random.randint(5, 6)
            for _ in range(num_courses):
                stype = random.choice(["LEC_ONLY", "LEC_TUT", "LEC_TUT_LAB", "LAB_ONLY"])
                course = Course(
                    id=cid,
                    code=f"R{cid}",
                    name=f"RandCourse-{cid}",
                    structure_type=stype,
                    lecture_count=12,
                    tutorial_count=12 if stype in ("LEC_TUT", "LEC_TUT_LAB") else 0,
                    lab_weeks=12 if stype in ("LEC_TUT_LAB", "LAB_ONLY") else 0,
                    lab_duration=random.choice([1, 2]),
                    share_lecture_group_ids=[],
                )
                courses[cid] = course
                prog_course_ids.append(cid)
                cid += 1

            num_groups = random.randint(1, 2)
            for _ in range(num_groups):
                group = Group(
                    id=gid,
                    name=f"RGroup-{gid}",
                    program_id=pid,
                    size=random.randint(25, 90),
                    course_ids=prog_course_ids.copy(),
                    preferred_free_days=2,
                )
                groups[gid] = group
                prog_group_ids.append(gid)
                gid += 1

            programs[pid] = Program(
                id=pid,
                name=f"RandProgram-{pid}",
                course_ids=prog_course_ids,
                group_ids=prog_group_ids,
            )
            pid += 1

    # Rooms and staff shared across programs
    rooms = _make_basic_rooms()
    staff = _make_staff(
        num_profs=max(3, len(courses) // 4),
        num_tas=max(4, len(courses) // 3),
        courses=courses,
    )

    block_heavy = mode == "block_profs"
    labs_heavy = mode in ("labs_only", "mixed_large", "random")

    activities = _make_activities(
        groups=groups,
        courses=courses,
        staff=staff,
        weeks=weeks,
        block_heavy=block_heavy,
        labs_heavy=labs_heavy,
    )

    inst = Instance(
        days=days,
        slots_per_day=slots_per_day,
        weeks=weeks,
        programs=programs,
        groups=groups,
        courses=courses,
        staff=staff,
        rooms=rooms,
        activities=activities,
    )
    return inst
