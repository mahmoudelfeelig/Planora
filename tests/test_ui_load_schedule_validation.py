from __future__ import annotations

import os
from pathlib import Path

import pytest

PyQt6 = pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from ui import window as ui_window  # noqa: E402
from utils.generator import generate_instance  # noqa: E402
from utils.exporter import export_schedule_to_csv  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_load_schedule_skips_invalid_rows(monkeypatch, qt_app, tmp_path: Path):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        win.populate_weeks()
        win.update_entities()

        a_id, act = next(iter(inst.activities.items()))
        schedule = {
            a_id: {
                "week": act.week,
                "day": inst.days[0],
                "slot": 0,
                "duration": act.duration,
                "room_id": None,
                "staff_id": act.prof_id if act.kind == "LEC" else act.ta_id,
                "course_id": act.course_id,
                "group_ids": list(act.group_ids),
                "kind": act.kind,
            },
        }
        # Add an invalid row (bad day)
        bad_id = a_id + 9999
        schedule[bad_id] = {
            "week": act.week,
            "day": "BAD",
            "slot": 0,
            "duration": 1,
            "room_id": None,
            "staff_id": act.prof_id if act.kind == "LEC" else act.ta_id,
            "course_id": act.course_id,
            "group_ids": list(act.group_ids),
            "kind": act.kind,
        }

        csv_path = tmp_path / "schedule.csv"
        export_schedule_to_csv(inst, schedule, csv_path)

        monkeypatch.setattr(
            ui_window.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(csv_path), "CSV"),
        )

        win.on_load_schedule()
        assert a_id in win.current_schedule
        assert bad_id not in win.current_schedule
    finally:
        win.close()
        win.deleteLater()
