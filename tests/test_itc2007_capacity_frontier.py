from __future__ import annotations

import copy
import time
from pathlib import Path

from benchmarks.itc2007 import (
    convert_itc2007_to_instance,
    parse_itc2007_ctt,
    score_itc2007_instance_schedule,
)
from core.itc2007_capacity_frontier import optimize_itc2007_capacity_frontier
from utils.specs import validate_schedule_against_instance


CAPACITY_BARRIER_INSTANCE = """\
Name: capacity-frontier-barrier
Courses: 3
Rooms: 2
Days: 1
Periods_per_day: 4
Curricula: 0
Constraints: 0
COURSES:
T TT 1 1 31
D TD 2 1 20
R TR 1 1 20
ROOMS:
Large 40
Small 30
CURRICULA:
UNAVAILABILITY_CONSTRAINTS:
END.
"""


def _instance(tmp_path: Path):
    source = tmp_path / "capacity-frontier.ctt"
    source.write_text(CAPACITY_BARRIER_INSTANCE, encoding="utf-8")
    return convert_itc2007_to_instance(parse_itc2007_ctt(source))


def _activities_by_code(inst) -> dict[str, tuple[int, ...]]:
    result: dict[str, list[int]] = {}
    for activity_id, activity in inst.activities.items():
        code = str(inst.courses[int(activity.course_id)].code)
        result.setdefault(code, []).append(int(activity_id))
    return {code: tuple(sorted(values)) for code, values in result.items()}


def _schedule(inst) -> dict[int, dict]:
    by_code = _activities_by_code(inst)
    room_by_name = {str(room.name): int(room_id) for room_id, room in inst.rooms.items()}
    placements = {
        by_code["T"][0]: (0, room_by_name["Small"]),
        by_code["D"][0]: (0, room_by_name["Large"]),
        by_code["D"][1]: (1, room_by_name["Large"]),
        by_code["R"][0]: (2, room_by_name["Small"]),
    }
    result: dict[int, dict] = {}
    for activity_id, activity in inst.activities.items():
        slot, room_id = placements[int(activity_id)]
        result[int(activity_id)] = {
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
    return result


def test_capacity_color_exchange_crosses_direct_move_barrier(tmp_path: Path) -> None:
    inst = _instance(tmp_path)
    incumbent = _schedule(inst)
    by_code = _activities_by_code(inst)
    room_by_name = {str(room.name): int(room_id) for room_id, room in inst.rooms.items()}
    direct = copy.deepcopy(incumbent)
    direct[by_code["T"][0]]["room_id"] = room_by_name["Large"]

    assert any(
        "Room overlap" in error
        for error in validate_schedule_against_instance(
            inst,
            direct,
            strict_rooms=True,
            require_all_activities=True,
        )
    )
    before = score_itc2007_instance_schedule(inst, incumbent)
    assert before.room_capacity == 1

    result = optimize_itc2007_capacity_frontier(
        inst,
        incumbent,
        deadline=time.perf_counter() + 2.0,
        seed=17,
        max_frontier_depth=0,
        max_exchange_solve_seconds=1.0,
    )

    assert result.status == "improved"
    assert result.improved
    assert result.initial_score == before
    assert result.final_score is not None
    assert result.final_score.total == 0
    assert result.final_score.room_capacity == 0
    assert result.telemetry.exchanges_enumerated >= 1
    assert result.telemetry.exchanges_attempted >= 1
    assert result.telemetry.models_feasible >= 1
    assert result.telemetry.validation_calls == 2
    assert result.telemetry.independent_rescores == 2
    assert result.telemetry.accepted_exchange is not None
    assert not validate_schedule_against_instance(
        inst,
        result.schedule,
        strict_rooms=True,
        require_all_activities=True,
    )
    assert result.schedule[by_code["T"][0]]["room_id"] == room_by_name["Large"]
    assert {
        int(result.schedule[activity_id]["room_id"])
        for activity_id in by_code["D"]
    } == {room_by_name["Small"]}


def test_expired_deadline_returns_exact_incumbent(tmp_path: Path) -> None:
    inst = _instance(tmp_path)
    incumbent = _schedule(inst)

    result = optimize_itc2007_capacity_frontier(
        inst,
        incumbent,
        deadline=time.perf_counter() - 1.0,
        seed=17,
    )

    assert result.status == "deadline_exhausted"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.telemetry.timing["deadline_exhausted"] is True


def test_model_cap_fails_closed_without_mutating_incumbent(tmp_path: Path) -> None:
    inst = _instance(tmp_path)
    incumbent = _schedule(inst)
    snapshot = copy.deepcopy(incumbent)

    result = optimize_itc2007_capacity_frontier(
        inst,
        incumbent,
        deadline=time.perf_counter() + 2.0,
        seed=17,
        max_model_variables=1,
    )

    assert result.status == "no_improvement"
    assert result.schedule == snapshot
    assert incumbent == snapshot
    assert result.telemetry.exchanges_skipped_model_cap >= 1


def test_same_seed_replays_identical_exchange_and_schedule(tmp_path: Path) -> None:
    inst = _instance(tmp_path)
    incumbent = _schedule(inst)

    left = optimize_itc2007_capacity_frontier(
        inst,
        incumbent,
        deadline=time.perf_counter() + 2.0,
        seed=991,
        max_frontier_depth=0,
    )
    right = optimize_itc2007_capacity_frontier(
        inst,
        incumbent,
        deadline=time.perf_counter() + 2.0,
        seed=991,
        max_frontier_depth=0,
    )

    assert left.status == right.status == "improved"
    assert left.schedule == right.schedule
    assert left.final_score == right.final_score
    assert left.telemetry.accepted_exchange == right.telemetry.accepted_exchange


def test_candidate_validator_rejection_returns_exact_incumbent(tmp_path: Path) -> None:
    inst = _instance(tmp_path)
    incumbent = _schedule(inst)
    calls = 0

    def reject_candidate(_inst, _schedule):
        nonlocal calls
        calls += 1
        return [] if calls == 1 else ["independent candidate rejection"]

    result = optimize_itc2007_capacity_frontier(
        inst,
        incumbent,
        deadline=time.perf_counter() + 2.0,
        seed=17,
        max_frontier_depth=0,
        validator=reject_candidate,
    )

    assert result.status == "no_improvement"
    assert result.schedule == incumbent
    assert result.telemetry.models_feasible >= 1
    assert result.telemetry.validation_calls >= 2
    assert result.telemetry.independent_rescores == 1
    assert any(
        row["status"] == "candidate_invalid" for row in result.telemetry.trace
    )


def test_candidate_crossing_deadline_during_final_copy_is_discarded(
    tmp_path: Path,
) -> None:
    inst = _instance(tmp_path)
    incumbent = _schedule(inst)
    calls = 0

    def cross_deadline_on_candidate(_inst, _schedule):
        nonlocal calls
        calls += 1
        if calls == 2:
            time.sleep(0.55)
        return []

    result = optimize_itc2007_capacity_frontier(
        inst,
        incumbent,
        deadline=time.perf_counter() + 0.5,
        seed=17,
        max_frontier_depth=0,
        max_exchange_solve_seconds=0.1,
        validator=cross_deadline_on_candidate,
    )

    assert result.status == "deadline_exhausted"
    assert not result.improved
    assert result.schedule == incumbent
    assert result.telemetry.timing["deadline_exhausted"] is True
    assert result.telemetry.timing["deadline_overrun_seconds"] > 0.0
