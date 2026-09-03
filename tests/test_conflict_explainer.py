from __future__ import annotations

from utils.conflict_explainer import (
    build_move_explanation_text,
    build_room_certificate_explanation,
)


def test_conflict_explainer_includes_suggestions_for_common_blockers():
    text = build_move_explanation_text(
        activity_id=12,
        target_week=3,
        target_day="MON",
        target_slot=1,
        valid=False,
        reason="Room capacity too small.",
        conflicts=[{"activity_id": 41, "reasons": ["room", "group"]}],
    )
    assert "A12" in text
    assert "blocked" in text.lower()
    assert "A41" in text
    assert "Suggested fixes" in text
    assert "larger room" in text.lower()


def test_conflict_explainer_valid_message_is_short():
    text = build_move_explanation_text(
        activity_id=1,
        target_week=1,
        target_day="TUE",
        target_slot=2,
        valid=True,
        reason="",
        conflicts=[],
    )
    assert "valid" in text.lower()


def test_room_certificate_explains_the_counting_proof_and_repair() -> None:
    text = build_room_certificate_explanation(
        {
            "certificate_type": "hall_deficiency",
            "activity_ids": [1, 2, 3],
            "candidate_room_ids": [7, 8],
            "message": "Three room jobs can use only two rooms.",
        }
    )
    assert "A1" in text and "R7" in text
    assert "more simultaneous room jobs" in text
    assert "move at least one" in text.lower()
