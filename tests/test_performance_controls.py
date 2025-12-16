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
