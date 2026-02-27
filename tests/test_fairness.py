from __future__ import annotations

from utils.fairness import compute_fairness_dashboard
from utils.generator import generate_instance


def test_compute_fairness_dashboard_returns_group_and_staff_rows():
    inst = generate_instance("small_demo")
    # Build a small synthetic schedule subset to keep test deterministic and fast.
    schedule = {}
    for a_id, act in list(inst.activities.items())[:25]:
        schedule[int(a_id)] = {
            "week": int(act.week),
            "day": inst.days[0],
            "slot": 0,
            "duration": int(act.duration),
            "room_id": next(iter(inst.rooms.keys())),
            "staff_id": int(act.prof_id if act.kind == "LEC" else act.ta_id),
            "course_id": int(act.course_id),
            "group_ids": [int(g) for g in act.group_ids],
            "kind": str(act.kind),
        }

    out = compute_fairness_dashboard(inst, schedule)
    assert "groups" in out and "staff" in out and "summary" in out
    assert isinstance(out["groups"], list)
    assert isinstance(out["staff"], list)
    assert out["summary"]["groups"]["count"] == len(inst.groups)
    assert out["summary"]["staff"]["count"] == len(inst.staff)
    assert "mean_fairness_score" in out["summary"]["groups"]
    assert "mean_fairness_score" in out["summary"]["staff"]
