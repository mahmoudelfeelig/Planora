from __future__ import annotations

import pickle
import subprocess
import sys
import os
from pathlib import Path

from utils.generator import generate_instance
from main import normalize_instance_for_spec, stamp_instance_time


def test_engine_cli_solves_and_respects_locks(tmp_path: Path) -> None:
    inst = generate_instance("small_demo")
    normalize_instance_for_spec(inst)
    stamp_instance_time(inst, "08:30", 90, 0)

    in_path = tmp_path / "inst.pkl"
    out_path = tmp_path / "res.pkl"

    in_path.write_bytes(pickle.dumps(inst))

    solver_path = Path(__file__).resolve().parent.parent / "core" / "engine_cli.py"
    env = {**os.environ, "TT_TIME_LIMIT": "20", "PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
    proc = subprocess.run(
        [sys.executable, str(solver_path), str(in_path), str(out_path)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0
    assert out_path.exists()

    res = pickle.loads(out_path.read_bytes())
    assert res["status"] in (0, 4)
    schedule = res["schedule"]
    assert schedule
    # CP-rooming should produce real room ids.
    assert all(v.get("room_id") is not None for v in schedule.values())

    # Lock one activity (time and room) and re-run.
    lock_a = next(iter(schedule.keys()))
    inst.locked_activities = {
        lock_a: {"day": schedule[lock_a]["day"], "slot": schedule[lock_a]["slot"], "room_id": schedule[lock_a]["room_id"]}
    }
    in_path.write_bytes(pickle.dumps(inst))
    out_path.unlink()

    proc2 = subprocess.run(
        [sys.executable, str(solver_path), str(in_path), str(out_path)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc2.returncode == 0
    res2 = pickle.loads(out_path.read_bytes())
    assert res2["status"] in (0, 4)
    sched2 = res2["schedule"]
    assert sched2[lock_a]["day"] == inst.locked_activities[lock_a]["day"]
    assert sched2[lock_a]["slot"] == inst.locked_activities[lock_a]["slot"]
    assert sched2[lock_a]["room_id"] == inst.locked_activities[lock_a]["room_id"]
