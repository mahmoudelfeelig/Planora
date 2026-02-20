from __future__ import annotations

import json
import pickle
import random
from collections import defaultdict
from dataclasses import is_dataclass
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Tuple, Set

from utils.domain import Activity, Course, Group, Instance, Program, Room, StaffMember


DAYS: List[str] = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
WEEKS: List[int] = list(range(1, 12 + 1))  # 12-week semester
SLOTS_PER_DAY: int = 5
ROOM_CATEGORY_CAPACITY: Dict[str, int] = {"SMALL": 80, "MEDIUM": 150, "BIG": 300}


def _distribute_sessions(total_sessions: int, weeks: List[int], rng: random.Random | None = None) -> Dict[int, int]:
    """
    Return a mapping week->count that places total_sessions across the given weeks
    as evenly as possible (deterministic).
    """
    if total_sessions < 0:
        raise ValueError("total_sessions must be non-negative")
    if not weeks:
        return {}

    base = total_sessions // len(weeks)
    rem = total_sessions % len(weeks)
    out = {w: base for w in weeks}
    if rem:
        picks = list(weeks)
        if rng is not None:
            rng.shuffle(picks)
        for w in picks[:rem]:
            out[w] += 1
    return out


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
            ensure_labs_only=True,
            ensure_block_course=True,
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
            block_prof_extra_days=("THU",),
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
        from utils.target_profile import generate_target_profile
        return generate_target_profile(seed=42)

    raise ValueError(f"Unknown generation mode: {mode}")


def _normalize_days(raw_days: List[str] | Set[str] | None) -> Set[str]:
    if not raw_days:
        return set(DAYS)
    out = {str(d).strip().upper() for d in raw_days}
    valid = {d for d in out if d in set(DAYS)}
    return valid or set(DAYS)


def _build_course_owner_map(
    *,
    course_ids: List[int],
    staff_count: int,
    staff_course_map: Dict[int, List[int]] | None,
) -> Dict[int, int]:
    if staff_count <= 0:
        raise ValueError("staff_count must be >= 1")
    owners: Dict[int, int] = {}
    valid_courses = set(course_ids)
    if isinstance(staff_course_map, dict):
        for raw_idx, raw_courses in sorted(staff_course_map.items()):
            idx = int(raw_idx)
            if idx < 1 or idx > staff_count:
                continue
            for raw_c in raw_courses or []:
                c_id = int(raw_c)
                if c_id in valid_courses and c_id not in owners:
                    owners[c_id] = idx
    rr = 1
    for c_id in course_ids:
        if c_id not in owners:
            owners[c_id] = rr
            rr += 1
            if rr > staff_count:
                rr = 1
    return owners


def _room_capacity_from_spec(spec: Dict[str, Any]) -> int:
    if spec.get("capacity") is not None:
        return max(1, int(spec["capacity"]))
    category = str(spec.get("category", "MEDIUM")).strip().upper()
    return ROOM_CATEGORY_CAPACITY.get(category, ROOM_CATEGORY_CAPACITY["MEDIUM"])


def _build_custom_rooms(room_specs: List[Dict[str, Any]]) -> Dict[int, Room]:
    if not room_specs:
        raise ValueError("room_specs must contain at least one room")
    rooms: Dict[int, Room] = {}
    full_availability = {(d, s) for d in DAYS for s in range(SLOTS_PER_DAY)}
    valid_types = {"LECTURE", "TUTORIAL", "COMPUTER_LAB", "SPECIALIZED_LAB"}
    for idx, raw in enumerate(room_specs, start=1):
        room_type = str(raw.get("room_type", "LECTURE")).strip().upper()
        if room_type not in valid_types:
            raise ValueError(f"Unsupported room type '{room_type}' in room_specs row {idx}")
        tags_raw = raw.get("tags", []) or []
        tags = {str(t).strip().upper() for t in tags_raw if str(t).strip()}
        name = str(raw.get("name") or f"Room-{idx}")
        rooms[idx] = Room(
            id=idx,
            name=name,
            capacity=_room_capacity_from_spec(raw),
            room_type=room_type,
            specialization_tags=tags,
            availability=set(full_availability),
        )
    return rooms


def generate_custom_instance(
    *,
    num_programs: int,
    groups_per_program: int,
    courses_per_program: int,
    course_names: List[str] | None = None,
    num_professors: int,
    num_tas: int,
    professor_course_map: Dict[int, List[int]] | None = None,
    ta_course_map: Dict[int, List[int]] | None = None,
    professor_days: Dict[int, List[str]] | None = None,
    ta_days: Dict[int, List[str]] | None = None,
    room_specs: List[Dict[str, Any]] | None = None,
    seed: int = 42,
) -> Instance:
    """
    Build an instance from explicit UI-provided counts/mappings.

    Notes:
      - course maps use 1-based local staff indexes (1..num_professors / 1..num_tas)
      - all courses are assigned exactly one professor and one TA
      - when maps are partial/empty, remaining courses are assigned round-robin
    """
    if num_programs < 1:
        raise ValueError("num_programs must be >= 1")
    if groups_per_program < 1:
        raise ValueError("groups_per_program must be >= 1")
    if courses_per_program < 1:
        raise ValueError("courses_per_program must be >= 1")
    if num_professors < 1:
        raise ValueError("num_professors must be >= 1")
    if num_tas < 1:
        raise ValueError("num_tas must be >= 1")

    inst = _generate_university(
        seed=seed,
        num_programs=int(num_programs),
        groups_per_program=(int(groups_per_program), int(groups_per_program)),
        courses_per_program=(int(courses_per_program), int(courses_per_program)),
    )

    # Optional custom room set.
    if room_specs is not None:
        inst.rooms = _build_custom_rooms(room_specs)

    # Optional course naming override (cycled if fewer names than courses).
    if course_names:
        clean_names = [str(name).strip() for name in course_names if str(name).strip()]
        if clean_names:
            for idx, c_id in enumerate(sorted(inst.courses.keys()), start=1):
                name = clean_names[(idx - 1) % len(clean_names)]
                code_base = "".join(ch for ch in name.upper() if ch.isalnum())[:8] or "CRS"
                inst.courses[c_id].name = name
                inst.courses[c_id].code = f"{code_base}-{int(c_id):03d}"

    # Build custom staff set.
    staff: Dict[int, StaffMember] = {}
    prof_staff_ids: List[int] = []
    ta_staff_ids: List[int] = []
    next_staff_id = 1
    for idx in range(1, int(num_professors) + 1):
        sid = next_staff_id
        next_staff_id += 1
        prof_staff_ids.append(sid)
        staff[sid] = StaffMember(
            id=sid,
            name=f"Prof-{idx}",
            is_prof=True,
            available_days=_normalize_days((professor_days or {}).get(idx)),
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses=set(),
            prefers_block=False,
            blocks_only=False,
        )
    for idx in range(1, int(num_tas) + 1):
        sid = next_staff_id
        next_staff_id += 1
        ta_staff_ids.append(sid)
        staff[sid] = StaffMember(
            id=sid,
            name=f"TA-{idx}",
            is_prof=False,
            available_days=_normalize_days((ta_days or {}).get(idx)),
            max_slots_per_day=None,
            max_slots_per_week=None,
            can_teach_courses=set(),
            prefers_block=False,
            blocks_only=False,
        )

    # Assign each course to one professor and one TA.
    course_ids = sorted(inst.courses.keys())
    prof_owner_idx = _build_course_owner_map(
        course_ids=course_ids,
        staff_count=len(prof_staff_ids),
        staff_course_map=professor_course_map,
    )
    ta_owner_idx = _build_course_owner_map(
        course_ids=course_ids,
        staff_count=len(ta_staff_ids),
        staff_course_map=ta_course_map,
    )

    for c_id in course_ids:
        prof_sid = prof_staff_ids[prof_owner_idx[c_id] - 1]
        ta_sid = ta_staff_ids[ta_owner_idx[c_id] - 1]
        inst.courses[c_id].prof_id = prof_sid
        inst.courses[c_id].ta_id = ta_sid
        staff[prof_sid].can_teach_courses.add(c_id)
        staff[ta_sid].can_teach_courses.add(c_id)

    # Activity-level assignment mirrors course-level assignment.
    for act in inst.activities.values():
        course = inst.courses[act.course_id]
        act.prof_id = int(course.prof_id)
        act.ta_id = int(course.ta_id)

    inst.staff = staff
    return inst


# ---------- core generator ----------


def _generate_university(
    seed: int,
    num_programs: int,
    groups_per_program: Tuple[int, int],
    courses_per_program: Tuple[int, int],
    *,
    ensure_labs_only: bool = False,
    ensure_block_course: bool = False,
    target_profile: bool = False,
    max_group_load_slots: int | None = None,
    block_prof_extra_days: tuple[str, ...] = (),
) -> Instance:
    """
    Generic builder for all modes.

    Enforced in data:
      - Week 1 contains only LEC activities.
      - Per-course totals: LEC = 12 and TUT = 12, achieved by adding one extra tutorial in a later week.
      - Labs-only courses skip week 1 and compensate with one extra 2-slot lab later to keep 12 labs.

    Model support:
      - Tutorials can use dedicated TUTORIAL rooms or overflow into LECTURE rooms.
      - Optional rare cross-major clustering for TUT/LAB via an ad-hoc activity.cluster_key.
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

    for p in range(1, num_programs + 1):
        num_courses = rng.randint(min_c, max_c)
        c_ids: List[int] = []

        for ci in range(num_courses):
            c_id = next_course_id
            next_course_id += 1
            code = f"C{c_id}"
            name = f"Course-{c_id}"

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
    BLOCK_WEEKS = [1, 4, 7, 10]  # includes week 1, which is allowed for LEC

    for p in range(1, num_programs + 1):
        c_ids = program_to_course_ids[p]
        num_courses = len(c_ids)

        labs_only_id: int | None = None
        if num_courses < max_c and num_courses > 0 and rng.random() < 0.5:
            labs_only_id = rng.choice(c_ids)
            labs_only_for_program[p] = labs_only_id

        nonlab_candidates = [c for c in c_ids if c != labs_only_id]
        n_block = rng.randint(0, min(3, len(nonlab_candidates))) if nonlab_candidates else 0
        if n_block > 0:
            chosen = rng.sample(nonlab_candidates, n_block)
            block_courses.update(chosen)

    # Guarantee coverage for spec tests if requested
    if ensure_labs_only and not labs_only_for_program:
        for p, c_ids in program_to_course_ids.items():
            if c_ids:
                labs_only_for_program[p] = c_ids[0]
                break

    if ensure_block_course and not block_courses:
        for c_ids in program_to_course_ids.values():
            for cid in c_ids:
                if cid not in labs_only_for_program.values():
                    block_courses.add(cid)
                    break
            if block_courses:
                break

    # ----- staff (profs, block profs, TAs) -----

    prof_ids, ta_ids, block_prof_ids = _build_staff_pool(
        staff=staff,
        rng=rng,
        total_courses=total_courses,
        target_profile=target_profile,
        programs=num_programs,
        block_prof_extra_days=block_prof_extra_days,
    )

    prof_load = {sid: 0 for sid in prof_ids}
    ta_load = {sid: 0 for sid in ta_ids}
    block_prof_course_count = {sid: 0 for sid in block_prof_ids}
    max_block_courses_per_prof = 2
    regular_prof_ids = [sid for sid in prof_ids if sid not in block_prof_ids]

    # ----- rooms -----

    rooms.update(_build_target_case_rooms(rng, target_profile=target_profile))  # includes LECTURE + TUTORIAL + LAB rooms

    # Default: all rooms available for all (day,slot) pairs (used by the solver if provided)
    for r in rooms.values():
        if getattr(r, "availability", None) is None:
            r.availability = {(d, s) for d in DAYS for s in range(SLOTS_PER_DAY)}

    # ----- assign courses to staff and finalise course metadata -----

    for p in range(1, num_programs + 1):
        g_ids = program_to_group_ids[p]
        c_ids = program_to_course_ids[p]
        labs_only_id = labs_only_for_program.get(p)

        for c_id in c_ids:
            # TA choice
            ta_choice = min(ta_ids, key=lambda s: ta_load[s])
            ta_load[ta_choice] += 1

            # Professor choice
            is_block_course = c_id in block_courses
            prof_choice: int | None = None
            if is_block_course and block_prof_ids:
                candidates = []
                for s in block_prof_ids:
                    days = getattr(staff[s], "available_days", set()) or set()
                    limit = 1 if len(days) <= 1 else max_block_courses_per_prof
                    if block_prof_course_count[s] < limit:
                        candidates.append(s)
                if candidates:
                    prof_choice = min(candidates, key=lambda s: prof_load[s])
                    block_prof_course_count[prof_choice] += 1
            if prof_choice is None:
                pool = regular_prof_ids if regular_prof_ids else prof_ids
                prof_choice = min(pool, key=lambda s: prof_load[s])
            prof_load[prof_choice] += 1

            c = courses[c_id]
            c.share_lecture_group_ids = list(g_ids) if len(g_ids) >= 2 else []
            c.prof_id = prof_choice
            c.ta_id = ta_choice
            staff[prof_choice].can_teach_courses.add(c_id)
            staff[ta_choice].can_teach_courses.add(c_id)

            # Structure selection
            if labs_only_id is not None and c_id == labs_only_id:
                c.structure_type = "LAB_ONLY"
                c.lecture_count = 0
                c.tutorial_count = 0
                c.lab_weeks = 12
                c.lab_duration = 2
            else:
                if target_profile:
                    lecture_total = 12
                    tutorial_total = rng.choices([0, 12], weights=[0.15, 0.85])[0]
                else:
                    # Keep patterns feasible at the repo's target scale: prefer 12/18, keep 24 rare.
                    lecture_total = rng.choices([12, 18, 24], weights=[0.75, 0.20, 0.05])[0]
                    tutorial_total = rng.choices([0, 12, 18, 24], weights=[0.10, 0.75, 0.12, 0.03])[0]

                if is_block_course:
                    # Block lecture courses: 4×3-slot blocks (slot-total 12) in fixed weeks.
                    lecture_total = 12

                # Decide which structure to use (some courses have labs)
                structure = rng.choices(
                    ["LEC_ONLY", "LEC_TUT", "LEC_TUT_LAB"],
                    weights=[0.15, 0.70, 0.15],
                )[0]

                if target_profile:
                    # favor clustered lectures; ensure share_lecture_group_ids already set
                    structure_weights = [0.05, 0.75, 0.20]
                    structure = rng.choices(["LEC_ONLY", "LEC_TUT", "LEC_TUT_LAB"], weights=structure_weights)[0]
                    if structure == "LEC_ONLY":
                        tutorial_total = 0
                        lab_weeks = 0
                        lab_duration = 0
                    elif structure == "LEC_TUT":
                        lab_weeks = 0
                        lab_duration = 0
                        if tutorial_total == 0:
                            tutorial_total = 12
                    else:
                        if tutorial_total == 0:
                            tutorial_total = 12
                        lab_weeks = 12
                        lab_duration = 2
                elif structure == "LEC_ONLY":
                    tutorial_total = 0
                    lab_weeks = 0
                    lab_duration = 0
                elif structure == "LEC_TUT":
                    lab_weeks = 0
                    lab_duration = 0
                    if tutorial_total == 0:
                        # keep "LEC_TUT" meaningful
                        tutorial_total = 12
                else:  # LEC_TUT_LAB
                    if tutorial_total == 0:
                        tutorial_total = 12
                    lab_weeks = 12
                    lab_duration = rng.choice([1, 2])

                c.structure_type = structure
                c.lecture_count = int(lecture_total)
                c.tutorial_count = int(tutorial_total)
                c.lab_weeks = int(lab_weeks)
                c.lab_duration = int(lab_duration)

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

    tut_weeks = list(range(2, 13))  # week-1 rule: tutorials/labs start week 2

    for p in range(1, num_programs + 1):
        g_ids = program_to_group_ids[p]
        c_ids = program_to_course_ids[p]

        for c_id in c_ids:
            c = courses[c_id]
            prof_id = c.prof_id
            ta_id = c.ta_id
            is_block_course = c_id in block_courses

            # ----- LECTURES (shared by all groups in the program) -----
            if c.lecture_count > 0:
                if is_block_course:
                    # 4 blocks of 3 slots (weeks 1,4,7,10), slot-total 12
                    for week in [1, 4, 7, 10]:
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

            # ----- TUTORIALS (per group; no week 1) -----
            if c.tutorial_count and c.tutorial_count > 0 and c.structure_type in ("LEC_TUT", "LEC_TUT_LAB"):
                tut_counts = _distribute_sessions(int(c.tutorial_count), tut_weeks, rng=rng)
                for week in tut_weeks:
                    for g_id in g_ids:
                        for _ in range(tut_counts.get(week, 0)):
                            act_id = next_act_id; next_act_id += 1
                            activities[act_id] = Activity(
                                id=act_id, course_id=c_id, week=week,
                                kind="TUT", duration=1, group_ids=[g_id],
                                prof_id=prof_id, ta_id=ta_id, requires_specialization=None,
                            )

            # ----- LABS (shared by all groups; no week 1) -----
            if c.lab_weeks and c.lab_weeks > 0 and c.lab_duration and c.lab_duration > 0:
                lab_counts = _distribute_sessions(int(c.lab_weeks), tut_weeks, rng=rng)
                if c.structure_type == "LAB_ONLY":
                    requires_tag: str | None = rng.choice(["LAB1", "LAB2", "LAB3"])
                else:
                    requires_tag = rng.choice([None, "LAB1", "LAB2", "LAB3"])
                for week in tut_weeks:
                    for _ in range(lab_counts.get(week, 0)):
                        act_id = next_act_id; next_act_id += 1
                        activities[act_id] = Activity(
                            id=act_id, course_id=c_id, week=week,
                            kind="LAB", duration=int(c.lab_duration), group_ids=list(g_ids),
                            prof_id=prof_id, ta_id=ta_id, requires_specialization=requires_tag,
                        )

    # rare cross-major clusters for TUT and LAB
    _inject_cross_major_clusters(activities, groups, courses, rng, target_profile=target_profile)

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

    _check_group_week_load(inst, hard_cap=max_group_load_slots)
    return inst


# ---------- staff + rooms + sanity check ----------


def _build_staff_pool(
    staff: Dict[int, StaffMember],
    rng: random.Random,
    total_courses: int,
    *,
    target_profile: bool = False,
    programs: int = 0,
    block_prof_extra_days: tuple[str, ...] = (),
) -> tuple[List[int], List[int], List[int]]:
    """
    Professors and TAs. No daily caps; optional weekly cap for block professors.
    """

    prof_ids: List[int] = []
    ta_ids: List[int] = []
    block_prof_ids: List[int] = []

    if target_profile:
        num_profs = max(30, total_courses // 4)
        # aim for 0–2 block profs per program (capped by total profs)
        num_block = min(num_profs, rng.randint(0, 2 * max(1, programs)))
    else:
        num_profs = max(8, total_courses // 3)
        num_block = rng.randint(0, min(3, num_profs))
    num_regular = num_profs - num_block

    next_staff_id = 1

    # block professors
    for _ in range(num_block):
        s_id = next_staff_id; next_staff_id += 1
        if block_prof_extra_days:
            # Keep the block-prof pattern constrained but avoid systematic infeasibility
            # in larger block-heavy modes by adding one extra teaching day.
            days = {"FRI", "SAT"} | set(block_prof_extra_days)
        else:
            days = {"SAT"} if rng.random() < 0.5 else {"FRI", "SAT"}
        staff[s_id] = StaffMember(
            id=s_id, name=f"Prof-{s_id}", is_prof=True,
            available_days=days,
            max_slots_per_day=None, max_slots_per_week=8,
            can_teach_courses=set(),
            prefers_block=True, blocks_only=True,
        )
        prof_ids.append(s_id); block_prof_ids.append(s_id)

    # regular professors
    for _ in range(num_regular):
        s_id = next_staff_id; next_staff_id += 1
        staff[s_id] = StaffMember(
            id=s_id, name=f"Prof-{s_id}", is_prof=True,
            available_days=set(DAYS),
            max_slots_per_day=None, max_slots_per_week=None,
            can_teach_courses=set(),
            prefers_block=False, blocks_only=False,
        )
        prof_ids.append(s_id)

    # TAs
    if target_profile:
        # Enough TAs to keep ~3–4 courses per TA; each TA has one fixed off-day
        num_tas = max(10, (total_courses + 3) // 4)
        days_list = list(DAYS)
        for _ in range(num_tas):
            s_id = next_staff_id; next_staff_id += 1
            off_day = rng.choice(days_list)
            avail = set(DAYS) - {off_day}
            staff[s_id] = StaffMember(
                id=s_id,
                name=f"TA-{s_id}",
                is_prof=False,
                available_days=avail,
                max_slots_per_day=None,
                max_slots_per_week=None,
                can_teach_courses=set(),
                prefers_block=False,
                blocks_only=False,
            )
            ta_ids.append(s_id)
    else:
        num_tas = max(8, total_courses // 4)
        for _ in range(num_tas):
            s_id = next_staff_id; next_staff_id += 1
            staff[s_id] = StaffMember(
                id=s_id, name=f"TA-{s_id}", is_prof=False,
                available_days=set(DAYS),
                max_slots_per_day=None, max_slots_per_week=None,
                can_teach_courses=set(),
                prefers_block=False, blocks_only=False,
            )
            ta_ids.append(s_id)

    return prof_ids, ta_ids, block_prof_ids


def _build_target_case_rooms(rng: random.Random, target_profile: bool = False) -> Dict[int, Room]:
    """
    Target profile: mixed big/small rooms and dedicated/specific labs.

      - Lecture rooms: 10 big (cap=500) + 5 small (cap=150) usable for LEC/TUT.
      - Tutorial rooms: 10 small (cap=100).
      - Specialized labs: 4 specific (LABA–LABD) tied to specific courses.
      - PC labs: 5–7 general labs usable for labs/tutorials.
    """

    rooms: Dict[int, Room] = {}
    next_room_id = 1

    if target_profile:
        # Big lecture rooms
        for i in range(10):
            r_id = next_room_id; next_room_id += 1
            rooms[r_id] = Room(
                id=r_id, name=f"BigLec-{i+1}",
                capacity=500, room_type="LECTURE", specialization_tags=set(),
            )
        # Small lecture rooms (can host tutorials as overflow)
        for i in range(5):
            r_id = next_room_id; next_room_id += 1
            rooms[r_id] = Room(
                id=r_id, name=f"SmallLec-{i+1}",
                capacity=150, room_type="LECTURE", specialization_tags=set(),
            )
        # Tutorial rooms
        for i in range(10):
            r_id = next_room_id; next_room_id += 1
            rooms[r_id] = Room(
                id=r_id, name=f"Tut-{i+1}",
                capacity=100, room_type="TUTORIAL", specialization_tags=set(),
            )
        # Specialized labs for specific courses
        for tag in ["LABA", "LABB", "LABC", "LABD"]:
            r_id = next_room_id; next_room_id += 1
            rooms[r_id] = Room(
                id=r_id, name=f"Spec-{tag}",
                capacity=60, room_type="SPECIALIZED_LAB", specialization_tags={tag},
            )
        # General computer labs
        num_pc = rng.randint(5, 7)
        for i in range(num_pc):
            r_id = next_room_id; next_room_id += 1
            rooms[r_id] = Room(
                id=r_id, name=f"PC-Lab-{i+1}",
                capacity=120, room_type="COMPUTER_LAB", specialization_tags=set(),
            )
    else:
        # legacy/default setup
        CAP = 400
        for i in range(15):
            r_id = next_room_id; next_room_id += 1
            rooms[r_id] = Room(
                id=r_id, name=f"Lec-{i+1}",
                capacity=CAP, room_type="LECTURE", specialization_tags=set(),
            )
        for i in range(5):
            r_id = next_room_id; next_room_id += 1
            rooms[r_id] = Room(
                id=r_id, name=f"Tut-{i+1}",
                capacity=CAP, room_type="TUTORIAL", specialization_tags=set(),
            )
        for tag in ["LAB1", "LAB2", "LAB3"]:
            r_id = next_room_id; next_room_id += 1
            rooms[r_id] = Room(
                id=r_id, name=f"SpecLab-{tag[-1]}",
                capacity=CAP, room_type="SPECIALIZED_LAB", specialization_tags={tag},
            )
        for i in range(2):
            r_id = next_room_id; next_room_id += 1
            rooms[r_id] = Room(
                id=r_id, name=f"CompLab-{i+1}",
                capacity=CAP, room_type="COMPUTER_LAB", specialization_tags=set(),
            )

    return rooms


def _inject_cross_major_clusters(
    activities: Dict[int, Activity],
    groups: Dict[int, Group],
    courses: Dict[int, Course],
    rng: random.Random,
    *,
    target_profile: bool = False,
) -> None:
    """
    Occasionally co-locate tutorials or labs across different programs in the same week.
    This sets a runtime attribute 'cluster_key' on Activity. JSON export will drop it
    unless the Activity dataclass is extended to include cluster_key.
    """

    # build program id per activity
    act_prog: Dict[int, int] = {}
    for a_id, a in activities.items():
        # pick program via first group in the list
        if a.group_ids:
            g0 = a.group_ids[0]
            act_prog[a_id] = groups[g0].program_id

    # candidates by (week, kind, tag) to keep LAB specializations compatible
    by_bucket: DefaultDict[Tuple[int, str, str], List[int]] = defaultdict(list)
    for a_id, a in activities.items():
        if a.kind in ("TUT", "LAB") and a.week != 1:
            tag = getattr(a, "requires_specialization", None) if a.kind == "LAB" else "ANY"
            if target_profile and a.kind == "LAB" and tag and tag.startswith("LAB"):
                continue  # keep specific labs unclustered across programs
            by_bucket[(a.week, a.kind, str(tag))].append(a_id)

    # choose a few clusters with low probability
    cluster_budget = 0
    for (week, kind, tag), ids in by_bucket.items():
        if cluster_budget >= 3:
            break
        if rng.random() > 0.08:  # ~8% of weeks
            continue

        # pick up to 3 activities from distinct programs and distinct staff to avoid
        # forcing impossible same-start overlaps.
        rng.shuffle(ids)
        picked: List[int] = []
        seen_prog: set[int] = set()
        seen_staff: set[int] = set()
        for a_id in ids:
            p = act_prog.get(a_id)
            if p is None or p in seen_prog:
                continue
            a = activities[a_id]
            staff_id = a.ta_id if a.kind in ("TUT", "LAB") else a.prof_id
            if staff_id in seen_staff:
                continue
            picked.append(a_id)
            seen_prog.add(p)
            seen_staff.add(staff_id)
            if len(picked) == 3:
                break

        if len(picked) >= 2:
            key = f"XCLUST-{kind}-W{week}"
            for a_id in picked:
                setattr(activities[a_id], "cluster_key", key)
            cluster_budget += 1


def _check_group_week_load(inst: Instance, hard_cap: int | None = None) -> None:
    """
    Sanity check: ensure we don't exceed the *physical* weekly capacity.
    Free days are handled as soft constraints by the improver.
    """
    max_slots_allowed = inst.slots_per_day * len(inst.days)  # e.g., 5 * 6 = 30
    soft_target = inst.slots_per_day * 4  # e.g., 5 * 4 = 20

    load: Dict[tuple[int, int], int] = {}  # (group_id, week) -> total slots
    for act in inst.activities.values():
        for g_id in act.group_ids:
            key = (g_id, act.week)
            load[key] = load.get(key, 0) + act.duration

    for (g_id, w), used in load.items():
        if used > soft_target:
            # soft warning only (kept as a log line, not an error)
            print(f"[WARN] Group {g_id} week {w}: load {used} slots > soft target {soft_target}")
        cap = hard_cap if hard_cap is not None else max_slots_allowed
        if used > cap:
            raise ValueError(
                f"Generator bug: group {g_id} in week {w} uses "
                f"{used} slots (> {cap})"
            )



# ===== JSON I/O + CLI additions =====

def _conv(obj):
    # dataclasses.asdict-like but convert sets to sorted lists and keep dict keys as strings
    if is_dataclass(obj):
        return { k: _conv(getattr(obj, k)) for k in obj.__annotations__.keys() }  # type: ignore
    if isinstance(obj, dict):
        return { str(k): _conv(v) for k, v in obj.items() }
    if isinstance(obj, (list, tuple)):
        return [ _conv(x) for x in obj ]
    if isinstance(obj, set):
        return sorted(_conv(x) for x in obj)
    return obj

def instance_to_json(inst: Instance) -> Dict[str, Any]:
    return {
        "days": inst.days,
        "slots_per_day": inst.slots_per_day,
        "weeks": inst.weeks,
        "programs": _conv(inst.programs),
        "groups": _conv(inst.groups),
        "courses": _conv(inst.courses),
        "staff": _conv(inst.staff),
        "rooms": _conv(inst.rooms),
        "activities": _conv(inst.activities),
        "locked_activities": _conv(getattr(inst, "locked_activities", {}) or {}),
        "soft_weights": _conv(getattr(inst, "soft_weights", {}) or {}),
        "hard_constraints": _conv(getattr(inst, "hard_constraints", {}) or {}),
    }

def write_instance(inst: Instance, out_path: str | Path) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        with path.open("w", encoding="utf-8") as f:
            json.dump(instance_to_json(inst), f, ensure_ascii=False, indent=2)
    elif path.suffix.lower() == ".pkl":
        with path.open("wb") as f:
            pickle.dump(inst, f)
    else:
        raise SystemExit(f"Unsupported output format: {path.suffix}")

def _cli_main(argv: List[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Generate a timetable instance.")
    parser.add_argument("--mode", default="target_case",
                        choices=["small_demo","mixed_large","block_profs","labs_only","random","target_case"],
                        help="Scenario to generate")
    parser.add_argument("--seed", type=int, default=None, help="Random seed override for 'random' mode")
    parser.add_argument("--out", required=True, help="Output path (.json or .pkl)")
    args = parser.parse_args(argv)

    inst = generate_instance(args.mode)

    if args.mode == "random" and args.seed is not None:
        import random as _random
        _random.seed(args.seed)
        inst = generate_instance(args.mode)

    write_instance(inst, args.out)
    return 0

if __name__ == "__main__":
    raise SystemExit(_cli_main())
