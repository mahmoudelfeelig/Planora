from __future__ import annotations

import time

from ortools.sat.python import cp_model

from utils.generator import generate_instance
from core.solver_cp_sat import TimetableSolver
from core.metaheuristics import LocalSearchImprover


def _solve_small_instance():
    inst = generate_instance("small_demo")
    solver = TimetableSolver(inst, room_mode="greedy", use_objective=False)
    cp, status = solver.solve(time_limit_seconds=10, workers=4)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    schedule = solver.extract_solution(cp)
    return inst, schedule


def test_local_search_respects_time_budget():
    inst, schedule = _solve_small_instance()
    improver = LocalSearchImprover(inst)

    start = time.perf_counter()
    improver.improve(schedule, iterations=200_000, max_seconds=0.05)
    elapsed = time.perf_counter() - start

    # Should stop quickly even when given a huge iteration budget.
    assert elapsed < 0.3


def test_greedy_rooming_is_fast():
    inst, schedule = _solve_small_instance()
    # Clear rooms to force greedy assignment again
    for info in schedule.values():
        info["room_id"] = None

    start = time.perf_counter()
    from core.solver_cp_sat import assign_rooms_greedily
    assign_rooms_greedily(inst, schedule)
    elapsed = time.perf_counter() - start

    # Should be fast for a small instance.
    assert elapsed < 1.0


def test_local_search_does_not_move_locked_activity():
    inst, schedule = _solve_small_instance()
    # Lock the first activity
    first_id = next(iter(schedule.keys()))
    locked = schedule[first_id]
    inst.locked_activities = {
        first_id: {"day": locked["day"], "slot": locked["slot"], "room_id": locked["room_id"]},
    }

    improver = LocalSearchImprover(inst)
    before = schedule[first_id].copy()
    out = improver.improve(schedule, iterations=1_000, max_seconds=0.05)

    assert out[first_id]["day"] == before["day"]
    assert out[first_id]["slot"] == before["slot"]
    assert out[first_id]["room_id"] == before["room_id"]


def test_time_move_respects_room_availability():
    inst, schedule = _solve_small_instance()
    a_id = next(iter(schedule.keys()))
    info = schedule[a_id]
    room_id = info["room_id"]
    assert room_id is not None

    # Restrict the assigned room to the activity's current occupied slots only.
    allowed_pairs = {
        (str(info["day"]), int(info["slot"]) + int(off))
        for off in range(int(info["duration"]))
    }
    inst.rooms[int(room_id)].availability = set(allowed_pairs)

    # Pick a different candidate slot/day.
    new_day = next((d for d in inst.days if str(d) != str(info["day"])), str(info["day"]))
    if str(new_day) == str(info["day"]):
        max_start = int(inst.slots_per_day) - int(info["duration"])
        new_slot = 0 if int(info["slot"]) != 0 else max(0, max_start)
    else:
        new_slot = int(info["slot"])
    if str(new_day) == str(info["day"]) and int(new_slot) == int(info["slot"]):
        new_slot = max(0, min(int(inst.slots_per_day) - int(info["duration"]), int(info["slot"]) + 1))

    improver = LocalSearchImprover(inst)
    improver._build_state(schedule)
    assert (
        improver._can_place_time(schedule, int(a_id), str(new_day), int(new_slot))
        is False
    )
