from __future__ import annotations

from utils.constraint_templates import (
    DEFAULT_TEMPLATES,
    apply_template_to_instance,
    load_templates,
    save_templates,
)
from utils.generator import generate_instance


EXPECTED_HARD_FLAGS = {
    "week1_lectures_only",
    "force_repeat_weekly_pattern",
    "enforce_course_totals",
    "enforce_block_professor_rules",
    "enforce_staff_daily_caps",
    "enforce_staff_weekly_caps",
    "enforce_room_availability",
    "enforce_travel_time_buffers",
    "enforce_building_closures",
    "enforce_calendar_rules",
    "enforce_precedence_rules",
}


def test_default_templates_cover_all_hard_constraint_flags():
    assert DEFAULT_TEMPLATES
    for name, template in DEFAULT_TEMPLATES.items():
        hard = template.get("hard", {})
        assert EXPECTED_HARD_FLAGS.issubset(set(hard.keys())), name
        assert all(isinstance(hard[key], bool) for key in EXPECTED_HARD_FLAGS)


def test_template_store_roundtrip(tmp_path):
    p = tmp_path / "templates.json"
    templates = dict(DEFAULT_TEMPLATES)
    templates["MyTemplate"] = {
        "hard": {"week1_lectures_only": False},
        "soft": {"stud_gaps": 99},
    }
    save_templates(p, templates)
    loaded = load_templates(p)
    assert "Balanced" in loaded
    assert "MyTemplate" in loaded
    assert loaded["MyTemplate"]["hard"]["week1_lectures_only"] is False
    assert int(loaded["MyTemplate"]["soft"]["stud_gaps"]) == 99


def test_apply_template_to_instance_sets_hard_and_soft():
    inst = generate_instance("small_demo")
    tpl = {
        "hard": {
            "week1_lectures_only": True,
            "enforce_room_availability": False,
        },
        "soft": {"stud_gaps": 42, "staff_free_day": 9},
    }
    apply_template_to_instance(inst, tpl)
    assert bool(inst.hard_constraints["week1_lectures_only"]) is True
    assert bool(inst.hard_constraints["enforce_room_availability"]) is False
    assert int(inst.soft_weights["stud_gaps"]) == 42
    assert int(inst.soft_weights["staff_free_day"]) == 9
