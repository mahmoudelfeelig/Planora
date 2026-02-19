from __future__ import annotations

from utils.generator import ROOM_CATEGORY_CAPACITY, generate_custom_instance


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

    assert len(inst.rooms) == 4
    assert inst.rooms[1].capacity == ROOM_CATEGORY_CAPACITY["BIG"]
    assert inst.rooms[2].capacity == 110
    assert inst.rooms[3].specialization_tags == {"LAB1"}
    assert inst.rooms[4].room_type == "COMPUTER_LAB"
