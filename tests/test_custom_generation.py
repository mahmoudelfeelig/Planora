from __future__ import annotations

from utils.generator import ROOM_CATEGORY_CAPACITY, generate_custom_instance, generate_instance


def test_generate_custom_instance_applies_counts_staff_mapping_and_rooms():
    inst = generate_custom_instance(
        num_programs=3,
        groups_per_program=2,
        courses_per_program=4,
        num_professors=3,
        num_tas=2,
        professor_course_map={1: [1, 2, 3], 2: [4, 5]},
        ta_course_map={1: [1, 2], 2: [3, 4, 5]},
        professor_days={1: ["MON", "TUE"], 2: ["WED"], 3: ["THU", "FRI"]},
        ta_days={1: ["MON", "WED"], 2: ["TUE", "THU", "SAT"]},
        room_specs=[
            {"name": "L-Big", "room_type": "LECTURE", "category": "BIG"},
            {"name": "T-Mid", "room_type": "TUTORIAL", "capacity": 110},
            {"name": "Lab-Spec", "room_type": "SPECIALIZED_LAB", "category": "SMALL", "tags": ["lab1"]},
            {"name": "Lab-PC", "room_type": "COMPUTER_LAB", "category": "MEDIUM"},
        ],
        seed=7,
    )

    assert len(inst.programs) == 3
    assert len(inst.groups) == 6
    assert len(inst.courses) == 12

    profs = [s for s in inst.staff.values() if s.is_prof]
    tas = [s for s in inst.staff.values() if not s.is_prof]
    assert len(profs) == 3
    assert len(tas) == 2

    # Professors are ids 1..num_professors; TAs follow after that.
    assert inst.staff[1].available_days == {"MON", "TUE"}
    assert inst.staff[2].available_days == {"WED"}
    assert inst.staff[4].available_days == {"MON", "WED"}
    assert inst.staff[5].available_days == {"TUE", "THU", "SAT"}

    # Explicit mapping is respected where provided.
    assert inst.courses[1].prof_id == 1
    assert inst.courses[2].prof_id == 1
    assert inst.courses[4].prof_id == 2
    assert inst.courses[1].ta_id == 4
    assert inst.courses[3].ta_id == 5

    for act in inst.activities.values():
        course = inst.courses[act.course_id]
        assert act.prof_id == course.prof_id
        assert act.ta_id == course.ta_id

    # Custom generation may inject fallback rooms to preserve solvability when
    # user-provided room definitions leave an activity without any eligible room.
    assert len(inst.rooms) >= 4
    assert inst.rooms[1].capacity == ROOM_CATEGORY_CAPACITY["BIG"]
    assert inst.rooms[2].capacity == 110
    assert inst.rooms[3].specialization_tags == {"LAB1"}
    assert inst.rooms[4].room_type == "COMPUTER_LAB"


def test_generate_custom_instance_supports_program_and_course_overrides():
    inst = generate_custom_instance(
        num_programs=2,
        groups_per_program=2,
        courses_per_program=4,
        program_overrides=[
            {"program_id": 1, "groups": 1, "courses": 3, "courses_per_group": 2},
            {"program_id": 2, "groups": 3, "courses": 5, "courses_per_group": 3},
        ],
        course_patterns=[
            {
                "course_id": 1,
                "lecture_count": 24,
                "tutorial_count": 18,
                "lab_type": "NONE",
                "lab_duration": 2,
                "lab_tag": "",
            },
            {
                "course_id": 2,
                "lecture_count": 12,
                "tutorial_count": 12,
                "lab_type": "SPECIAL",
                "lab_duration": 2,
                "lab_tag": "LAB2",
            },
            {
                "course_id": 4,
                "lecture_count": 18,
                "tutorial_count": 12,
                "lab_type": "NORMAL",
                "lab_duration": 2,
                "lab_tag": "",
            },
        ],
        num_professors=4,
        num_tas=4,
        seed=11,
    )

    assert len(inst.programs) == 2
    assert len(inst.groups) == 4  # 1 + 3
    assert len(inst.courses) == 8  # 3 + 5

    p1 = inst.programs[1]
    p2 = inst.programs[2]
    assert len(p1.group_ids) == 1
    assert len(p2.group_ids) == 3
    assert len(p1.course_ids) == 3
    assert len(p2.course_ids) == 5

    # Program 1 was configured for two courses per group.
    g1 = inst.groups[p1.group_ids[0]]
    assert len(g1.course_ids) == 2

    # Program 2 was configured for three courses per group.
    for g_id in p2.group_ids:
        assert len(inst.groups[g_id].course_ids) == 3

    c1 = inst.courses[1]
    c2 = inst.courses[2]
    c4 = inst.courses[4]
    assert c1.lecture_count == 24
    assert c1.tutorial_count == 18
    assert c1.lab_weeks == 0
    assert c2.structure_type == "LEC_TUT_LAB"
    assert c2.lab_weeks == 12
    assert c2.lab_duration == 2
    assert c4.structure_type == "LEC_TUT_LAB"
    assert c4.lab_weeks == 12

    c2_labs = [a for a in inst.activities.values() if a.course_id == 2 and a.kind == "LAB"]
    assert c2_labs
    assert all(a.requires_specialization == "LAB2" for a in c2_labs)

    c4_labs = [a for a in inst.activities.values() if a.course_id == 4 and a.kind == "LAB"]
    assert c4_labs
    assert all(a.requires_specialization is None for a in c4_labs)


def test_generate_custom_instance_infers_structure_from_counts():
    inst = generate_custom_instance(
        num_programs=1,
        groups_per_program=1,
        courses_per_program=4,
        course_patterns=[
            {
                "course_id": 1,
                "lecture_count": 0,
                "tutorial_count": 0,
                "lab_count": 18,
                "lab_type": "SPECIAL",
                "lab_duration": 2,
                "lab_tag": "LAB3",
            },
            {
                "course_id": 2,
                "lecture_count": 0,
                "tutorial_count": 24,
                "lab_count": 0,
                "lab_type": "NONE",
                "lab_duration": 2,
                "lab_tag": "",
            },
            {
                "course_id": 3,
                "lecture_count": 18,
                "tutorial_count": 0,
                "lab_count": 0,
                "lab_type": "NONE",
                "lab_duration": 2,
                "lab_tag": "",
            },
            {
                "course_id": 4,
                "lecture_count": 12,
                "tutorial_count": 0,
                "lab_count": 12,
                "lab_type": "NORMAL",
                "lab_duration": 1,
                "lab_tag": "",
            },
        ],
        num_professors=2,
        num_tas=2,
        seed=31,
    )

    c1 = inst.courses[1]
    c2 = inst.courses[2]
    c3 = inst.courses[3]
    c4 = inst.courses[4]

    assert c1.structure_type == "LAB_ONLY"
    assert c1.lecture_count == 0
    assert c1.tutorial_count == 0
    assert c1.lab_weeks == 18

    assert c2.structure_type == "LEC_TUT"
    assert c2.lecture_count == 0
    assert c2.tutorial_count == 24
    assert c2.lab_weeks == 0

    assert c3.structure_type == "LEC_ONLY"
    assert c3.lecture_count == 18
    assert c3.tutorial_count == 0
    assert c3.lab_weeks == 0

    assert c4.structure_type == "LEC_TUT_LAB"
    assert c4.lecture_count == 12
    assert c4.tutorial_count == 0
    assert c4.lab_weeks == 12

    c1_labs = [a for a in inst.activities.values() if a.course_id == 1 and a.kind == "LAB"]
    assert len(c1_labs) == 18
    assert all(a.requires_specialization == "LAB3" for a in c1_labs)

    c2_lecs = [a for a in inst.activities.values() if a.course_id == 2 and a.kind == "LEC"]
    c2_tuts = [a for a in inst.activities.values() if a.course_id == 2 and a.kind == "TUT"]
    assert len(c2_lecs) == 0
    assert len(c2_tuts) == 24

    c3_lecs = [a for a in inst.activities.values() if a.course_id == 3 and a.kind == "LEC"]
    c3_tuts = [a for a in inst.activities.values() if a.course_id == 3 and a.kind == "TUT"]
    assert len(c3_lecs) == 18
    assert len(c3_tuts) == 0

    c4_tuts = [a for a in inst.activities.values() if a.course_id == 4 and a.kind == "TUT"]
    c4_labs = [a for a in inst.activities.values() if a.course_id == 4 and a.kind == "LAB"]
    assert len(c4_tuts) == 0
    assert len(c4_labs) == 12
    assert all(a.requires_specialization is None for a in c4_labs)


def test_generate_custom_instance_supports_calendar_and_room_metadata():
    inst = generate_custom_instance(
        num_programs=1,
        groups_per_program=1,
        courses_per_program=3,
        num_professors=2,
        num_tas=2,
        calendar_days=["MON", "TUE", "WED", "THU", "FRI"],
        calendar_weeks=[1, 2, 3, 4, 5, 6, 7, 8],
        slots_per_day=6,
        room_specs=[
            {
                "name": "North Hall A",
                "room_type": "LECTURE",
                "category": "MEDIUM",
                "campus": "NORTH",
                "building": "HALL-A",
                "features": ["PROJECTOR", "ACCESSIBLE"],
            },
            {
                "name": "North Lab",
                "room_type": "SPECIALIZED_LAB",
                "category": "SMALL",
                "campus": "NORTH",
                "building": "LAB-1",
                "features": ["WET_LAB"],
                "tags": ["LAB1"],
            },
        ],
        seed=19,
    )

    assert inst.days == ["MON", "TUE", "WED", "THU", "FRI"]
    assert inst.weeks == [1, 2, 3, 4, 5, 6, 7, 8]
    assert int(inst.slots_per_day) == 6
    assert inst.rooms[1].campus == "NORTH"
    assert inst.rooms[1].building == "HALL-A"
    assert inst.rooms[1].features == {"PROJECTOR", "ACCESSIBLE"}
    assert inst.rooms[2].campus == "NORTH"
    assert inst.rooms[2].building == "LAB-1"
    assert inst.rooms[2].features == {"WET_LAB"}
    for room in inst.rooms.values():
        assert room.availability is not None
        assert all(day in {"MON", "TUE", "WED", "THU", "FRI"} for day, _slot in room.availability)


def test_ss23_uni_like_preset_matches_extracted_scale():
    inst = generate_instance("ss23_uni_like")

    assert inst.days == ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
    assert inst.weeks == list(range(1, 13))
    assert int(inst.slots_per_day) == 5
    assert len(inst.programs) == 9
    assert len(inst.groups) == 17
    assert len(inst.courses) == 88
    assert len(inst.rooms) == 161
    assert len([s for s in inst.staff.values() if s.is_prof]) == 88
    assert len([s for s in inst.staff.values() if not s.is_prof]) == 44
    assert 1000 <= len(inst.activities) <= 2200

    room_types = {room.room_type for room in inst.rooms.values()}
    assert room_types == {"LECTURE", "TUTORIAL", "COMPUTER_LAB", "SPECIALIZED_LAB"}
    assert getattr(inst, "objective_profile", "") == "fast_feasible"
    assert inst.sla_targets["source_events"] == 1265
    assert inst.sla_targets["observed_merged_activities"] == 1044

    for act in inst.activities.values():
        needed_capacity = sum(inst.groups[g_id].size for g_id in act.group_ids)
        eligible = []
        for room in inst.rooms.values():
            if room.capacity < needed_capacity:
                continue
            if act.kind == "LEC" and room.room_type == "LECTURE":
                eligible.append(room.id)
            elif act.kind == "TUT" and room.room_type in {"TUTORIAL", "LECTURE"}:
                eligible.append(room.id)
            elif act.kind == "LAB" and act.requires_specialization:
                if (
                    room.room_type == "SPECIALIZED_LAB"
                    and act.requires_specialization in room.specialization_tags
                ):
                    eligible.append(room.id)
            elif act.kind == "LAB" and room.room_type in {"COMPUTER_LAB", "SPECIALIZED_LAB"}:
                eligible.append(room.id)
        assert eligible, f"activity {act.id} has no eligible room"
