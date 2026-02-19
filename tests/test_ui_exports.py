from __future__ import annotations

from pathlib import Path
import os

import pytest

PyQt6 = pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from ui import window as ui_window  # noqa: E402
from utils.generator import generate_instance  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _fake_schedule(inst):
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
    return schedule


def test_ui_export_csv_calls_exporter(monkeypatch, qt_app, tmp_path: Path):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        win.current_schedule = _fake_schedule(inst)

        target = tmp_path / "sched.csv"
        monkeypatch.setattr(
            ui_window.QFileDialog,
            "getSaveFileName",
            lambda *args, **kwargs: (str(target), "CSV"),
        )

        called = {}

        def fake_export(inst_arg, schedule_arg, path):
            called["path"] = path

        monkeypatch.setattr(ui_window, "export_schedule_to_csv", fake_export)

        win.on_export_csv()
        assert called["path"] == str(target)
    finally:
        win.close()
        win.deleteLater()


def test_ui_export_ics_calls_exporter(monkeypatch, qt_app, tmp_path: Path):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        win.current_schedule = _fake_schedule(inst)

        monkeypatch.setattr(
            ui_window.QFileDialog,
            "getExistingDirectory",
            lambda *args, **kwargs: str(tmp_path),
        )

        called = {"groups": False, "staff": False, "rooms": False}

        def fake_groups(*args, **kwargs):
            called["groups"] = True

        def fake_staff(*args, **kwargs):
            called["staff"] = True

        def fake_rooms(*args, **kwargs):
            called["rooms"] = True

        monkeypatch.setattr(ui_window, "export_groups_ics_per_id", fake_groups)
        monkeypatch.setattr(ui_window, "export_staff_ics_per_id", fake_staff)
        monkeypatch.setattr(ui_window, "export_rooms_ics_per_id", fake_rooms)

        win.on_export_ics()
        assert called["groups"]
        assert called["staff"]
        assert called["rooms"]
    finally:
        win.close()
        win.deleteLater()
