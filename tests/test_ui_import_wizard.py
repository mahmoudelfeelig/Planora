from __future__ import annotations

import os

import pytest

PyQt6 = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

from ui import window as ui_window  # noqa: E402
from utils.generator import generate_instance  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_import_schedule_wizard_uses_mapped_reader(monkeypatch, qt_app, tmp_path):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        a_id, act = next(iter(inst.activities.items()))
        csv_path = tmp_path / "mapped.csv"
        csv_path.write_text("x\n", encoding="utf-8")

        monkeypatch.setattr(
            ui_window.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(csv_path), "CSV"),
        )
        monkeypatch.setattr(
            win,
            "_read_csv_preview_rows",
            lambda *args, **kwargs: (["x"], [{"x": "1"}]),
        )

        class FakeWizard:
            def __init__(self, *_args, **_kwargs):
                pass

            def exec(self):
                return QDialog.DialogCode.Accepted

            def selected_mapping(self):
                return {
                    "activity_id": "aid",
                    "week": "wk",
                    "day": "day",
                    "slot": "slot",
                    "duration": "dur",
                    "course_id": "cid",
                    "kind": "kind",
                    "staff_id": "sid",
                    "room_id": "rid",
                    "group_ids": "gids",
                }

            def group_separator(self):
                return ";"

        monkeypatch.setattr(ui_window, "ImportScheduleWizardDialog", FakeWizard)
        schedule = {
            int(a_id): {
                "week": int(act.week),
                "day": inst.days[0],
                "slot": 0,
                "duration": int(act.duration),
                "room_id": next(iter(inst.rooms.keys())),
                "staff_id": int(act.prof_id if act.kind == "LEC" else act.ta_id),
                "course_id": int(act.course_id),
                "group_ids": list(act.group_ids),
                "kind": str(act.kind),
            }
        }
        monkeypatch.setattr(
            ui_window,
            "read_schedule_csv_mapped",
            lambda *args, **kwargs: schedule,
        )

        win.on_import_schedule_wizard()
        assert int(a_id) in win.current_schedule
    finally:
        win.close()
        win.deleteLater()
