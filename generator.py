import random
from typing import Dict, List, Tuple
from domain import (
    Instance, Program, Group, Course, Staff, Room, Activity,
    Day, WeekIndex,
)


def _base_calendar() -> Tuple[List[Day], int, List[WeekIndex]]:
    days: List[Day] = ["SAT", "MON", "TUE", "WED", "THU", "FRI"]
    slots_per_day = 5
    weeks: List[WeekIndex] = list(range(1, 13))
    return days, slots_per_day, weeks


def _make_basic_rooms() -> Dict[int, Room]:
    rooms: Dict[int, Room] = {}
    rid = 1

    # lecture/tutorial rooms of varying sizes
    for cap in [40, 60, 80, 120]:
        rooms[rid] = Room(
            id=rid,
            name=f"Room-{rid}-LecTut-{cap}",
            room_type="LECTURE",
            capacity=cap,
        )
        rid += 1

    # computer labs
    for _ in range(3):
        rooms[rid] = Room(
            id=rid,
            name=f"CompLab-{rid}",
            room_type="COMPUTER_LAB",
            capacity=30,
        )
        rid += 1

    # specialized labs
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
        if not course_ids:
            return set()
        return set(random.sample(course_ids, min(k, len(course_ids))))

    # professors
    for _ in range(num_profs):
        is_block = random.random() < 0.3
        all_days = {"SAT", "MON", "TUE", "WED", "THU", "FRI"}
        block_days = set()
        available_days = all_days.copy()
        if is_block:
            # for now assume block profs only come on SAT (could extend to FRI/SAT)
            block_days = {"SAT"}
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

    # TAs
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
    weeks: List[int],
    block_heavy: bool,
    labs_heavy: bool,
) -> Dict[int, Activity]:
    """
    Builds activities per course/group/week.

    Lecture patterns:
      - 12 lectures: 1 per week
      - 18 lectures: 1 per week + second lecture in 6 weeks
      - 24 lectures: 2 per week

    For some courses and block professors:
      - if lecture_count is 12 or 18 and a block professor is skilled,
        then lectures are 3-slot blocks on SAT on a subset of weeks:
          * 12 lectures: 4 visits (every 3 weeks)
          * 18 lectures: 6 visits (every 2 weeks)

    Week 1 is lectures only; tutorials/labs start from week 2.
    """
    activities: Dict[int, Activity] = {}
    aid = 1

    # precompute staff candidates per course
    staff_candidates_for_course: Dict[int, List[int]] = {c_id: [] for c_id in courses}
    for s_id, s in staff.items():
        for c_id in s.skilled_course_ids:
            if c_id in courses:
                staff_candidates_for_course[c_id].append(s_id)

    # we also separate block professors
    block_profs = {s_id for s_id, s in staff.items() if s.is_block_professor}

    for c_id, course in courses.items():
        # groups taking this course
        groups_in_course = [g for g in groups.values() if c_id in g.course_ids]
        if not groups_in_course:
            continue

        # base staff candidates
        lec_staff = staff_candidates_for_course.get(c_id, [])
        tut_staff = lec_staff.copy()
        lab_staff = lec_staff.copy()

        # fallbacks to keep instance solvable
        if not lec_staff:
            lec_staff = [s.id for s in staff.values() if s.is_professor]
        if not tut_staff:
            tut_staff = [s.id for s in staff.values() if not s.is_professor] or lec_staff
        if not lab_staff:
            lab_staff = [s.id for s in staff.values() if not s.is_professor] or lec_staff

        # find block profs skilled for this course
        block_staff_for_course = [s for s in lec_staff if s in block_profs]

        # shared lecture groups
        shared_group_ids = [g.id for g in groups_in_course]

        # ----- lectures -----
        total_lectures = course.lecture_count
        lecture_weeks = weeks

        # decide if this is a block-pattern course for a block professor
        is_block_course = (
            block_heavy
            and block_staff_for_course
            and total_lectures in (12, 18)
        )

        if is_block_course:
            # choose a specific block professor for this course
            block_prof = random.choice(block_staff_for_course)
            lec_staff = [block_prof]

            num_blocks = total_lectures // 3
            total_weeks = len(weeks)
            step = total_weeks // num_blocks  # 12/4=3, 12/6=2

            block_weeks = weeks[0::step][:num_blocks]
            for w in block_weeks:
                activities[aid] = Activity(
                    id=aid,
                    course_id=c_id,
                    group_ids=shared_group_ids,
                    kind="LEC",
                    duration_slots=3,  # 3-slot block on that day
                    week=w,
                    staff_candidates=lec_staff,
                    requires_specialization=None,
                    pattern_id=None,
                )
                aid += 1
        else:
            # regular lecture patterns
            if total_lectures == 12:
                # one lecture per week
                for w in lecture_weeks:
                    activities[aid] = Activity(
                        id=aid,
                        course_id=c_id,
                        group_ids=shared_group_ids,
                        kind="LEC",
                        duration_slots=1,
                        week=w,
                        staff_candidates=lec_staff,
                        requires_specialization=None,
                        pattern_id=None,
                    )
                    aid += 1
            elif total_lectures == 18:
                # one per week + second lecture in 6 selected weeks
                extra_needed = 6
                # choose every second week starting from week 2
                extra_weeks = [w for w in lecture_weeks[1::2]][:extra_needed]

                for w in lecture_weeks:
                    # base lecture
                    activities[aid] = Activity(
                        id=aid,
                        course_id=c_id,
                        group_ids=shared_group_ids,
                        kind="LEC",
                        duration_slots=1,
                        week=w,
                        staff_candidates=lec_staff,
                        requires_specialization=None,
                        pattern_id=None,
                    )
                    aid += 1
                    # possibly second lecture
                    if w in extra_weeks:
                        activities[aid] = Activity(
                            id=aid,
                            course_id=c_id,
                            group_ids=shared_group_ids,
                            kind="LEC",
                            duration_slots=1,
                            week=w,
                            staff_candidates=lec_staff,
                            requires_specialization=None,
                            pattern_id=None,
                        )
                        aid += 1
            elif total_lectures == 24:
                # two lectures per week
                for w in lecture_weeks:
                    for _ in range(2):
                        activities[aid] = Activity(
                            id=aid,
                            course_id=c_id,
                            group_ids=shared_group_ids,
                            kind="LEC",
                            duration_slots=1,
                            week=w,
                            staff_candidates=lec_staff,
                            requires_specialization=None,
                            pattern_id=None,
                        )
                        aid += 1
            else:
                # fallback: treat as 1 per week
                for w in lecture_weeks:
                    activities[aid] = Activity(
                        id=aid,
                        course_id=c_id,
                        group_ids=shared_group_ids,
                        kind="LEC",
                        duration_slots=1,
                        week=w,
                        staff_candidates=lec_staff,
                        requires_specialization=None,
                        pattern_id=None,
                    )
                    aid += 1

        # ----- tutorials -----
        if course.structure_type in ("LEC_TUT", "LEC_TUT_LAB") and course.tutorial_count > 0:
            tutorial_weeks = weeks[1:]  # from week 2
            for g in groups_in_course:
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
                        pattern_id=None,
                    )
                    aid += 1

        # ----- labs -----
        if course.lab_weeks > 0 and course.structure_type in ("LEC_TUT_LAB", "LAB_ONLY"):
            lab_weeks = weeks[1:]  # from week 2
            for g in groups_in_course:
                for w in lab_weeks:
                    spec = None
                    if labs_heavy:
                        spec = random.choice(["PHYSICS_LAB", "CHEM_LAB"])
                    activities[aid] = Activity(
                        id=aid,
                        course_id=c_id,
                        group_ids=[g.id],
                        kind="LAB",
                        duration_slots=course.lab_duration,
                        week=w,
                        staff_candidates=lab_staff,
                        requires_specialization=spec,
                        pattern_id=None,
                    )
                    aid += 1

    return activities


def generate_instance(mode: str = "small_demo") -> Instance:
    """
    Modes:
      - small_demo: tiny instance
      - block_profs: tests block-only professor patterns
      - labs_only: stresses labs
      - mixed_large: closer to target scale
      - random: fully random within similar size range
    """
    days, slots_per_day, weeks = _base_calendar()

    programs: Dict[int, Program] = {}
    groups: Dict[int, Group] = {}
    courses: Dict[int, Course] = {}

    pid = 1
    gid = 1
    cid = 1

    if mode == "small_demo":
        # two programs, one group each, 2 courses per program
        for _ in range(2):
            prog_course_ids = []
            prog_group_ids = []
            used_long = False
            for _ in range(2):
                if not used_long and random.random() < 0.5:
                    lecture_count = random.choice([18, 24])
                    used_long = True
                else:
                    lecture_count = 12
                stype = random.choice(["LEC_ONLY", "LEC_TUT", "LEC_TUT_LAB"])
                tutorial_count = 12 if stype in ("LEC_TUT", "LEC_TUT_LAB") else 0
                lab_weeks = 12 if stype in ("LEC_TUT_LAB", "LAB_ONLY") else 0

                course = Course(
                    id=cid,
                    code=f"C{cid}",
                    name=f"Course-{cid}",
                    structure_type=stype,
                    lecture_count=lecture_count,
                    tutorial_count=tutorial_count,
                    lab_weeks=lab_weeks,
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
        # one program, 2 groups, 4 courses; block-heavy
        prog_course_ids = []
        prog_group_ids = []
        used_long = False
        for _ in range(4):
            # ensure at most one 18/24 per program
            if not used_long and random.random() < 0.75:
                lecture_count = random.choice([18, 12])
                used_long = lecture_count > 12
            else:
                lecture_count = 12
            course = Course(
                id=cid,
                code=f"B{cid}",
                name=f"BlockCourse-{cid}",
                structure_type="LEC_TUT",
                lecture_count=lecture_count,
                tutorial_count=12,
                lab_weeks=0,
                lab_duration=1,
                share_lecture_group_ids=[gid, gid + 1],
            )
            courses[cid] = course
            prog_course_ids.append(cid)
            cid += 1

        for _ in range(2):
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
        prog_course_ids = []
        prog_group_ids = []
        used_long = False
        for _ in range(3):
            if not used_long and random.random() < 0.5:
                lecture_count = random.choice([18, 24])
                used_long = True
            else:
                lecture_count = 12
            stype = random.choice(["LAB_ONLY", "LEC_TUT_LAB"])
            course = Course(
                id=cid,
                code=f"L{cid}",
                name=f"LabCourse-{cid}",
                structure_type=stype,
                lecture_count=lecture_count,
                tutorial_count=12 if stype == "LEC_TUT_LAB" else 0,
                lab_weeks=12,
                lab_duration=random.choice([1, 2]),
                share_lecture_group_ids=[],
            )
            courses[cid] = course
            prog_course_ids.append(cid)
            cid += 1

        for _ in range(3):
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
        num_programs = 20 if mode == "mixed_large" else random.randint(10, 25)
        for _ in range(num_programs):
            prog_course_ids = []
            prog_group_ids = []
            used_long = False

            num_courses = random.randint(5, 6)
            for _ in range(num_courses):
                if not used_long and random.random() < 0.6:
                    lecture_count = random.choice([18, 24])
                    used_long = True
                else:
                    lecture_count = 12

                stype = random.choice(["LEC_ONLY", "LEC_TUT", "LEC_TUT_LAB", "LAB_ONLY"])
                tutorial_count = 12 if stype in ("LEC_TUT", "LEC_TUT_LAB") else 0
                lab_weeks = 12 if stype in ("LEC_TUT_LAB", "LAB_ONLY") else 0

                course = Course(
                    id=cid,
                    code=f"R{cid}",
                    name=f"RandCourse-{cid}",
                    structure_type=stype,
                    lecture_count=lecture_count,
                    tutorial_count=tutorial_count,
                    lab_weeks=lab_weeks,
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

    rooms = _make_basic_rooms()
    staff = _make_staff(
        num_profs=max(3, len(courses) // 4),
        num_tas=max(4, len(courses) // 3),
        courses=courses,
    )

    block_heavy = (mode == "block_profs")
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
    