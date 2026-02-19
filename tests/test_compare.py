from __future__ import annotations

from utils.compare import compare_schedules


def test_compare_schedules_counts_changes():
    base = {
        1: {
            "week": 1,
            "day": "MON",
            "slot": 0,
            "duration": 1,
            "room_id": 10,
            "staff_id": 100,
            "course_id": 1,
            "group_ids": [1],
            "kind": "LEC",
        },
        2: {
            "week": 1,
            "day": "MON",
            "slot": 1,
            "duration": 1,
            "room_id": 11,
            "staff_id": 101,
            "course_id": 2,
            "group_ids": [2],
            "kind": "TUT",
        },
    }
    other = {
        1: {
            "week": 1,
            "day": "TUE",
            "slot": 0,
            "duration": 1,
            "room_id": 10,
            "staff_id": 100,
            "course_id": 1,
            "group_ids": [1],
            "kind": "LEC",
        },
        2: {
            "week": 1,
            "day": "MON",
            "slot": 1,
            "duration": 1,
            "room_id": 12,
            "staff_id": 102,
            "course_id": 2,
            "group_ids": [2],
            "kind": "TUT",
        },
    }

    out = compare_schedules(base, other)
    assert out["shared"] == 2
    assert out["changed_time"] == 1
    assert out["changed_day"] == 1
    assert out["changed_slot"] == 0
    assert out["changed_room"] == 1
    assert out["changed_staff"] == 1
    assert out["group_move_counts"].get(1) == 1
    assert out["group_move_counts"].get(2, 0) == 0

