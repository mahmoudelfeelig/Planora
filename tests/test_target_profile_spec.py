from __future__ import annotations

from utils.target_profile import generate_target_profile


def test_target_profile_matches_spec_counts():
    inst = generate_target_profile(seed=42)
    for c in inst.courses.values():
        assert c.lecture_count in {12, 18, 24}
        assert c.tutorial_count in {0, 12, 18, 24}
        assert c.lab_weeks in {0, 12}
        assert c.lab_duration in {0, 1, 2}
