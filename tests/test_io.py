from __future__ import annotations

import builtins
import pickle
from pathlib import Path

import pytest

from services.project_service import load_legacy_project
from utils.generator import generate_instance, instance_to_json
from utils.exporter import export_schedule_to_csv
from utils.io import (
    instance_from_json,
    read_instance,
    read_schedule_csv,
    read_schedule_csv_mapped,
    write_scenario,
    read_scenario,
)


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


class _MaliciousPickle:
    def __init__(self, marker: Path):
        self.marker = marker

    def __reduce__(self):
        source = f"open({str(self.marker)!r}, 'w', encoding='utf-8').write('executed')"
        return builtins.exec, (source,)


@pytest.mark.parametrize("reader", [read_instance, read_scenario, load_legacy_project])
def test_public_pickle_import_is_rejected_without_execution(tmp_path: Path, reader):
    marker = tmp_path / "pickle-executed"
    path = tmp_path / "untrusted.pkl"
    path.write_bytes(pickle.dumps(_MaliciousPickle(marker)))

    with pytest.raises(ValueError, match="can execute arbitrary code"):
        reader(path)

    assert not marker.exists()


def test_public_pickle_export_is_rejected(tmp_path: Path):
    inst = generate_instance("small_demo")
    with pytest.raises(ValueError, match="can execute arbitrary code"):
        write_scenario(tmp_path / "scenario.pkl", inst, {}, meta={"name": "demo"})


def test_desktop_file_selectors_do_not_advertise_pickle() -> None:
    source = (Path(__file__).parents[1] / "ui" / "window_io.py").read_text(
        encoding="utf-8"
    )
    assert ".pkl" not in source


def test_schedule_csv_mapped_reads_custom_headers(tmp_path: Path):
    path = tmp_path / "mapped.csv"
    path.write_text(
        "aid,wk,weekday,start,dur,cid,atype,sid,rid,groups\n"
        "1,2,MON,3,2,10,LEC,7,4,11|12\n",
        encoding="utf-8",
    )
    loaded = read_schedule_csv_mapped(
        path,
        field_map={
            "activity_id": "aid",
            "week": "wk",
            "day": "weekday",
            "slot": "start",
            "duration": "dur",
            "course_id": "cid",
            "kind": "atype",
            "staff_id": "sid",
            "room_id": "rid",
            "group_ids": "groups",
        },
        group_separator="|",
    )
    assert 1 in loaded
    assert int(loaded[1]["week"]) == 2
    assert str(loaded[1]["day"]) == "MON"
    assert int(loaded[1]["slot"]) == 3
    assert int(loaded[1]["duration"]) == 2
    assert int(loaded[1]["staff_id"]) == 7
    assert int(loaded[1]["room_id"]) == 4
    assert loaded[1]["group_ids"] == [11, 12]
