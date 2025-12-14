from __future__ import annotations

import random
random.seed(12345)
from typing import Dict, List, Tuple, DefaultDict
from collections import defaultdict

from domain import (
    Instance,
    Program,
    Group,
    Course,
    StaffMember,
    Room,
    Activity,
)
import json
import pickle
from dataclasses import is_dataclass
from pathlib import Path
from typing import Dict, Any, List


DAYS: List[str] = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
WEEKS: List[int] = list(range(1, 12 + 1))  # 12-week semester
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

    # ----- staff (profs, block profs, TAs) -----

    prof_ids, ta_ids, block_prof_ids = _build_staff_pool(
        staff=staff,
        rng=rng,
        total_courses=total_courses,
    )

    prof_load = {sid: 0 for sid in prof_ids}
    ta_load = {sid: 0 for sid in ta_ids}
    block_prof_course_count = {sid: 0 for sid in block_prof_ids}
    max_block_courses_per_prof = 2

    # ----- rooms -----

    rooms.update(_build_target_case_rooms())  # includes LECTURE + TUTORIAL + LAB rooms

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
                candidates = [s for s in block_prof_ids if block_prof_course_count[s] < max_block_courses_per_prof]
                if candidates:
                    prof_choice = min(candidates, key=lambda s: prof_load[s])
                    block_prof_course_count[prof_choice] += 1
            if prof_choice is None:
                prof_choice = min(prof_ids, key=lambda s: prof_load[s])
            prof_load[prof_choice] += 1

            c = courses[c_id]
            c.share_lecture_group_ids = list(g_ids)
            c.prof_id = prof_choice
            c.ta_id = ta_choice
            staff[prof_choice].can_teach_courses.add(c_id)
            staff[ta_choice].can_teach_courses.add(c_id)

            if labs_only_id is not None and c_id == labs_only_id:
                c.structure_type = "LAB_ONLY"
                c.lecture_count = 0
                c.tutorial_count = 0
                c.lab_weeks = 12
                c.lab_duration = 2
            else:
                c.structure_type = "LEC_TUT"
                c.lecture_count = 12
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

            # LECTURES
            if is_block_course:
                # 4 blocks of 3 slots (weeks 1,4,7,10), shared by all groups
                for week in [1, 4, 7, 10]:
                    act_id = next_act_id; next_act_id += 1
                    activities[act_id] = Activity(
                        id=act_id, course_id=c_id, week=week,
                        kind="LEC", duration=3, group_ids=list(g_ids),
                        prof_id=prof_id, ta_id=ta_id, requires_specialization=None,
                    )
            else:
                # 1-slot lecture each week 1..12, shared by all groups
                for week in WEEKS:
                    act_id = next_act_id; next_act_id += 1
                    activities[act_id] = Activity(
                        id=act_id, course_id=c_id, week=week,
                        kind="LEC", duration=1, group_ids=list(g_ids),
                        prof_id=prof_id, ta_id=ta_id, requires_specialization=None,
                    )

            # TUTORIALS: no week 1; add one extra tutorial in a later week to reach 12 total
            makeup_week = 2 + (c_id % 11)  # spreads extras across weeks 2..12
            for week in range(2, 13):  # weeks 2..12
                for g_id in g_ids:
                    act_id = next_act_id; next_act_id += 1
                    activities[act_id] = Activity(
                        id=act_id, course_id=c_id, week=week,
                        kind="TUT", duration=1, group_ids=[g_id],
                        prof_id=prof_id, ta_id=ta_id, requires_specialization=None,
                    )
                    # add the extra tutorial when we hit makeup_week
                    if week == makeup_week:
                        act_id2 = next_act_id; next_act_id += 1
                        activities[act_id2] = Activity(
                            id=act_id2, course_id=c_id, week=week,
                            kind="TUT", duration=1, group_ids=[g_id],
                            prof_id=prof_id, ta_id=ta_id, requires_specialization=None,
                        )

            # LABS-ONLY courses: skip week 1; double one week to keep 12 labs
            if labs_only_id is not None and c_id == labs_only_id:
                spec_tag = rng.choice(["LAB1", "LAB2", "LAB3"])
                lab_makeup_week = 2 + (c_id % 11)
                for week in range(2, 13):
                    act_id = next_act_id; next_act_id += 1
                    activities[act_id] = Activity(
                        id=act_id, course_id=c_id, week=week,
                        kind="LAB", duration=2, group_ids=list(g_ids),
                        prof_id=prof_id, ta_id=ta_id, requires_specialization=spec_tag,
                    )
                    if week == lab_makeup_week:
                        act_id2 = next_act_id; next_act_id += 1
                        activities[act_id2] = Activity(
                            id=act_id2, course_id=c_id, week=week,
                            kind="LAB", duration=2, group_ids=list(g_ids),
                            prof_id=prof_id, ta_id=ta_id, requires_specialization=spec_tag,
                        )

    # rare cross-major clusters for TUT and LAB
    _inject_cross_major_clusters(activities, groups, courses, rng)

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
    Professors and TAs. No daily caps; optional weekly cap for block professors.
    """

    prof_ids: List[int] = []
    ta_ids: List[int] = []
    block_prof_ids: List[int] = []

    num_profs = max(8, total_courses // 3)
    num_block = rng.randint(0, min(3, num_profs))
    num_regular = num_profs - num_block

    next_staff_id = 1

    # block professors
    for _ in range(num_block):
        s_id = next_staff_id; next_staff_id += 1
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


def _build_target_case_rooms() -> Dict[int, Room]:
    """
    25 rooms total, uniform capacity assumption for LEC/TUT:

      - 15 LECTURE rooms
      - 5 TUTORIAL rooms
      - 3 SPECIALIZED_LAB rooms (LAB1–LAB3)
      - 2 COMPUTER_LAB rooms
    """

    rooms: Dict[int, Room] = {}
    next_room_id = 1

    # uniform capacity for simplicity; solver ignores capacity anyway
    CAP = 200

    # lecture rooms
    for i in range(15):
        r_id = next_room_id; next_room_id += 1
        rooms[r_id] = Room(
            id=r_id, name=f"Lec-{i+1}",
            capacity=CAP, room_type="LECTURE", specialization_tags=set(),
        )

    # tutorial rooms
    for i in range(5):
        r_id = next_room_id; next_room_id += 1
        rooms[r_id] = Room(
            id=r_id, name=f"Tut-{i+1}",
            capacity=CAP, room_type="TUTORIAL", specialization_tags=set(),
        )

    # specialised labs
    for tag in ["LAB1", "LAB2", "LAB3"]:
        r_id = next_room_id; next_room_id += 1
        rooms[r_id] = Room(
            id=r_id, name=f"SpecLab-{tag[-1]}",
            capacity=CAP, room_type="SPECIALIZED_LAB", specialization_tags={tag},
        )

    # computer labs
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

    # candidates by week and kind
    by_week_kind: DefaultDict[Tuple[int, str], List[int]] = defaultdict(list)
    for a_id, a in activities.items():
        if a.kind in ("TUT", "LAB") and a.week != 1:
            by_week_kind[(a.week, a.kind)].append(a_id)

    # choose a few clusters with low probability
    cluster_budget = 0
    for (week, kind), ids in by_week_kind.items():
        if cluster_budget >= 3:
            break
        if rng.random() > 0.08:  # ~8% of weeks
            continue

        # pick up to 3 activities from distinct programs
        rng.shuffle(ids)
        picked: List[int] = []
        seen_prog: set[int] = set()
        for a_id in ids:
            p = act_prog.get(a_id)
            if p is None or p in seen_prog:
                continue
            picked.append(a_id)
            seen_prog.add(p)
            if len(picked) == 3:
                break

        if len(picked) >= 2:
            key = f"XCLUST-{kind}-W{week}"
            for a_id in picked:
                setattr(activities[a_id], "cluster_key", key)
            cluster_budget += 1


def _check_group_week_load(inst: Instance) -> None:
    """
    Sanity check: ensure we don't exceed the *physical* weekly capacity.
    Free days are handled as soft constraints by the improver.
    """
    max_slots_allowed = inst.slots_per_day * len(inst.days)  # e.g., 5 * 6 = 30

    load: Dict[tuple[int, int], int] = {}  # (group_id, week) -> total slots
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
