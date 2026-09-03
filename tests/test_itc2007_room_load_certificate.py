from __future__ import annotations

import copy
import time
from pathlib import Path

from benchmarks.itc2007 import convert_itc2007_to_instance, parse_itc2007_ctt
from core.itc2007_room_load_certificate import (
    certify_itc2007_room_load_lower_bound,
    verify_itc2007_room_load_certificate,
)


ROOM_LOAD_INSTANCE = """\
Name: room-load-certificate
Courses: 2
Rooms: 2
Days: 1
Periods_per_day: 3
Curricula: 0
Constraints: 0
COURSES:
A TA 3 1 31
B TB 1 1 31
ROOMS:
Large 40
Small 30
CURRICULA:
UNAVAILABILITY_CONSTRAINTS:
END.
"""


def _case(tmp_path: Path):
    source = tmp_path / "room-load.ctt"
    source.write_text(ROOM_LOAD_INSTANCE, encoding="utf-8")
    inst = convert_itc2007_to_instance(parse_itc2007_ctt(source))
    rooms = {str(room.name): int(room_id) for room_id, room in inst.rooms.items()}
    inst.rooms[rooms["Large"]].availability = {("D0", 0), ("D0", 1)}
    inst.rooms[rooms["Small"]].availability = {
        ("D0", 0),
        ("D0", 1),
        ("D0", 2),
    }
    by_course: dict[str, list[int]] = {}
    for activity_id, activity in inst.activities.items():
        code = str(inst.courses[int(activity.course_id)].code)
        by_course.setdefault(code, []).append(int(activity_id))
    placements = {
        by_course["A"][0]: (0, rooms["Large"]),
        by_course["A"][1]: (1, rooms["Large"]),
        by_course["A"][2]: (2, rooms["Small"]),
        by_course["B"][0]: (0, rooms["Small"]),
    }
    schedule: dict[int, dict[str, object]] = {}
    for activity_id, activity in inst.activities.items():
        slot, room_id = placements[int(activity_id)]
        schedule[int(activity_id)] = {
            "week": 1,
            "day": "D0",
            "slot": int(slot),
            "duration": 1,
            "room_id": int(room_id),
            "staff_id": int(activity.prof_id),
            "course_id": int(activity.course_id),
            "group_ids": list(activity.group_ids),
            "kind": str(activity.kind),
        }
    return inst, schedule


def test_exact_room_load_relaxation_certifies_attained_global_optimum(
    tmp_path: Path,
) -> None:
    inst, schedule = _case(tmp_path)

    result = certify_itc2007_room_load_lower_bound(
        inst,
        schedule,
        deadline=time.perf_counter() + 2.0,
        seed=17,
    )

    assert result.status == "global_optimum_certified"
    assert result.proven
    assert result.lower_bound == 3
    assert result.certificate_capacity_cost == 2
    assert result.certificate_stability_cost == 1
    assert result.incumbent_score is not None
    assert result.incumbent_score.total == 3
    assert result.attained_global_optimum
    assert result.telemetry.solver_status == "optimal"
    assert result.telemetry.validation_calls == 1
    assert result.telemetry.independent_rescores == 1
    assert not result.telemetry.certificate_replay_errors


def test_lower_bound_is_proved_without_overclaiming_without_an_incumbent(
    tmp_path: Path,
) -> None:
    inst, _schedule = _case(tmp_path)

    result = certify_itc2007_room_load_lower_bound(
        inst,
        deadline=time.perf_counter() + 2.0,
        seed=17,
    )

    assert result.status == "lower_bound_proved"
    assert result.proven
    assert result.lower_bound == 3
    assert result.incumbent_score is None
    assert not result.attained_global_optimum


def test_certificate_replay_detects_count_and_objective_tampering(
    tmp_path: Path,
) -> None:
    inst, schedule = _case(tmp_path)
    result = certify_itc2007_room_load_lower_bound(
        inst,
        schedule,
        deadline=time.perf_counter() + 2.0,
        seed=17,
    )
    payload = [row.to_dict() for row in result.certificates]

    count_tamper = copy.deepcopy(payload)
    count_tamper[0]["room_counts"][0][1] += 1
    count_errors = verify_itc2007_room_load_certificate(
        inst,
        count_tamper,
        claimed_lower_bound=int(result.lower_bound),
    )
    objective_errors = verify_itc2007_room_load_certificate(
        inst,
        payload,
        claimed_lower_bound=int(result.lower_bound) + 1,
    )

    assert any("room_count_total_mismatch" in value for value in count_errors)
    assert any("objective_mismatch" in value for value in objective_errors)


def test_deadline_and_nonstandard_weights_fail_closed(tmp_path: Path) -> None:
    inst, schedule = _case(tmp_path)
    expired = certify_itc2007_room_load_lower_bound(
        inst,
        schedule,
        deadline=time.perf_counter() - 1.0,
        seed=17,
    )
    inst.sla_targets["itc2007"]["objective_weights"]["room_stability"] = 2
    nonstandard = certify_itc2007_room_load_lower_bound(
        inst,
        schedule,
        deadline=time.perf_counter() + 2.0,
        seed=17,
    )

    assert expired.status == "deadline_exhausted"
    assert not expired.proven
    assert expired.lower_bound is None
    assert nonstandard.status == "ineligible"
    assert not nonstandard.proven
    assert "itc2007_objective_weights_nonstandard" in nonstandard.eligibility.reasons
