from __future__ import annotations

from pathlib import Path

from ortools.sat.python import cp_model

from utils.generator import generate_instance
from core.solver_cp_sat import TimetableSolver
from utils.io import write_scenario, read_scenario
from utils.compare import compare_schedules


def test_scenario_roundtrip_and_compare(tmp_path: Path):
    inst = generate_instance("small_demo")
    solver = TimetableSolver(inst, room_mode="greedy", use_objective=False)
    cp, status = solver.solve(time_limit_seconds=10, workers=4)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    schedule = solver.extract_solution(cp)
    assert schedule

    path = tmp_path / "scenario.json"
    write_scenario(path, inst, schedule, meta={"name": "roundtrip"})

    inst2, schedule2, meta = read_scenario(path)
    assert meta["name"] == "roundtrip"
    assert len(inst2.activities) == len(inst.activities)
    assert schedule2

    summary = compare_schedules(schedule, schedule2)
    assert summary["changed_time"] == 0
    assert summary["changed_room"] == 0
    assert summary["missing_in_other"] == []
