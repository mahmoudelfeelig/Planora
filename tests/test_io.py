from __future__ import annotations

from pathlib import Path

from utils.generator import generate_instance, instance_to_json
from utils.exporter import export_schedule_to_csv
from utils.io import instance_from_json, read_schedule_csv, write_scenario, read_scenario


def test_instance_json_roundtrip():
    inst = generate_instance("small_demo")
    data = instance_to_json(inst)
    restored = instance_from_json(data)

    assert restored.days == inst.days
    assert restored.slots_per_day == inst.slots_per_day
    assert restored.weeks == inst.weeks
    assert len(restored.programs) == len(inst.programs)
    assert len(restored.groups) == len(inst.groups)
    assert len(restored.courses) == len(inst.courses)
    assert len(restored.staff) == len(inst.staff)
    assert len(restored.rooms) == len(inst.rooms)
    assert len(restored.activities) == len(inst.activities)


def test_schedule_csv_roundtrip(tmp_path: Path):
    inst = generate_instance("small_demo")
    # fake schedule by placing all activities at slot 0, day MON (not necessarily feasible)
    schedule = {}
    for a_id, act in inst.activities.items():
        schedule[a_id] = {
            "week": act.week,
            "day": inst.days[0],
            "slot": 0,
            "duration": act.duration,
            "room_id": None,
            "staff_id": act.prof_id if act.kind == "LEC" else act.ta_id,
            "course_id": act.course_id,
            "group_ids": list(act.group_ids),
            "kind": act.kind,
        }
    out_path = tmp_path / "sched.csv"
    export_schedule_to_csv(inst, schedule, out_path)

    loaded = read_schedule_csv(out_path)
    assert loaded.keys() == schedule.keys()
    sample_id = next(iter(schedule.keys()))
    assert loaded[sample_id]["week"] == schedule[sample_id]["week"]
    assert loaded[sample_id]["day"] == schedule[sample_id]["day"]
    assert loaded[sample_id]["duration"] == schedule[sample_id]["duration"]
    assert loaded[sample_id]["group_ids"] == schedule[sample_id]["group_ids"]


def test_scenario_json_roundtrip(tmp_path: Path):
    inst = generate_instance("small_demo")
    schedule = {}
    for a_id, act in inst.activities.items():
        schedule[a_id] = {
            "week": act.week,
            "day": inst.days[0],
            "slot": 0,
            "duration": act.duration,
            "room_id": None,
            "staff_id": act.prof_id if act.kind == "LEC" else act.ta_id,
            "course_id": act.course_id,
            "group_ids": list(act.group_ids),
            "kind": act.kind,
        }
    path = tmp_path / "scenario.json"
    write_scenario(path, inst, schedule, meta={"name": "demo"})

    inst2, sched2, meta = read_scenario(path)
    assert meta["name"] == "demo"
    assert len(inst2.activities) == len(inst.activities)
    assert sched2.keys() == schedule.keys()


def test_scenario_pickle_roundtrip(tmp_path: Path):
    inst = generate_instance("small_demo")
    schedule = {}
    for a_id, act in inst.activities.items():
        schedule[a_id] = {
            "week": act.week,
            "day": inst.days[0],
            "slot": 0,
            "duration": act.duration,
            "room_id": None,
            "staff_id": act.prof_id if act.kind == "LEC" else act.ta_id,
            "course_id": act.course_id,
            "group_ids": list(act.group_ids),
            "kind": act.kind,
        }
    path = tmp_path / "scenario.pkl"
    write_scenario(path, inst, schedule, meta={"name": "demo"})

    inst2, sched2, meta = read_scenario(path)
    assert meta["name"] == "demo"
    assert len(inst2.activities) == len(inst.activities)
    assert sched2.keys() == schedule.keys()

