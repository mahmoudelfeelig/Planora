# ui_desktop.py

import sys
import os
import uuid
import pickle
import tempfile
import traceback
from typing import Dict, Any, Tuple, List

from PyQt6.QtCore import Qt, QProcess
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem, QLabel,
    QMessageBox, QFileDialog, QDialog, QFormLayout
)

from generator import generate_instance
from metaheuristics import LocalSearchImprover
from exporter import export_group_schedules_to_docx


# ---------- edit dialog ----------

class EditActivityDialog(QDialog):
    def __init__(self, parent, inst, schedule, act_ids: List[int], week: int, day: str, slot: int):
        super().__init__(parent)
        self.inst = inst
        self.schedule = schedule
        self.act_ids = act_ids
        self.week = week

        self.setWindowTitle("Edit activity")
        layout = QFormLayout()
        self.setLayout(layout)

        self.activity_combo = QComboBox()
        for a_id in act_ids:
            info = schedule[a_id]
            course = inst.courses.get(info["course_id"])
            text = f"A{a_id} {course.code if course else ''} {info['kind']}"
            self.activity_combo.addItem(text, a_id)
        layout.addRow("Activity:", self.activity_combo)

        self.day_combo = QComboBox()
        for d in inst.days:
            self.day_combo.addItem(d, d)
        idx = self.day_combo.findData(day)
        if idx >= 0:
            self.day_combo.setCurrentIndex(idx)
        layout.addRow("Day:", self.day_combo)

        self.slot_combo = QComboBox()
        for s in range(inst.slots_per_day):
            self.slot_combo.addItem(str(s + 1), s)
        idx = self.slot_combo.findData(slot)
        if idx >= 0:
            self.slot_combo.setCurrentIndex(idx)
        layout.addRow("Start slot:", self.slot_combo)

        self.room_combo = QComboBox()
        for r_id, r in inst.rooms.items():
            self.room_combo.addItem(f"{r.name} (id {r_id})", r_id)
        cur_a_id = self.activity_combo.currentData()
        cur_info = schedule[cur_a_id]
        cur_room = cur_info["room_id"]
        idx = self.room_combo.findData(cur_room)
        if idx >= 0:
            self.room_combo.setCurrentIndex(idx)
        layout.addRow("Room:", self.room_combo)

        self.staff_combo = QComboBox()
        cur_staff = cur_info["staff_id"]
        for s_id, s in inst.staff.items():
            self.staff_combo.addItem(f"{s.name} (id {s_id})", s_id)
        idx = self.staff_combo.findData(cur_staff)
        if idx >= 0:
            self.staff_combo.setCurrentIndex(idx)
        layout.addRow("Staff:", self.staff_combo)

    def get_values(self) -> Tuple[int, str, int, int, int]:
        a_id = self.activity_combo.currentData()
        day = self.day_combo.currentData()
        slot = self.slot_combo.currentData()
        room_id = self.room_combo.currentData()
        staff_id = self.staff_combo.currentData()
        return a_id, day, slot, room_id, staff_id


# ---------- main window ----------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("University Timetabling")

        self.inst = None
        self.base_schedule: Dict[int, Dict[str, Any]] = {}
        self.current_schedule: Dict[int, Dict[str, Any]] = {}

        # external solver process
        self.proc: QProcess | None = None
        self.tmp_inst_path: str | None = None
        self.tmp_res_path: str | None = None

        self._build_ui()
        self._connect_signals()

    # ----- UI setup -----

    def _build_ui(self):
        top_widget = QWidget()
        top_layout = QHBoxLayout()
        top_widget.setLayout(top_layout)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["small_demo", "block_profs", "labs_only", "mixed_large", "random"])

        self.generate_button = QPushButton("Generate")
        self.solve_button = QPushButton("Solve")
        self.improve_button = QPushButton("Improve")
        self.export_button = QPushButton("Export DOCX")

        self.view_type_combo = QComboBox()
        self.view_type_combo.addItems(["Group", "Staff", "Room"])
        self.entity_combo = QComboBox()
        self.week_combo = QComboBox()

        self.status_label = QLabel("Ready")

        top_layout.addWidget(QLabel("Mode:"))
        top_layout.addWidget(self.mode_combo)
        top_layout.addWidget(self.generate_button)
        top_layout.addWidget(self.solve_button)
        top_layout.addWidget(self.improve_button)
        top_layout.addWidget(self.export_button)
        top_layout.addWidget(QLabel("View:"))
        top_layout.addWidget(self.view_type_combo)
        top_layout.addWidget(self.entity_combo)
        top_layout.addWidget(QLabel("Week:"))
        top_layout.addWidget(self.week_combo)
        top_layout.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(True)
        self.table.horizontalHeader().setVisible(True)

        central = QWidget()
        main_layout = QVBoxLayout()
        central.setLayout(main_layout)
        main_layout.addWidget(top_widget)
        main_layout.addWidget(self.table)
        self.setCentralWidget(central)

        self.setStyleSheet("""
            QMainWindow {
                background-color: #22252b;
            }
            QLabel {
                color: #f0f0f0;
                font-size: 10pt;
            }
            QComboBox, QPushButton {
                font-size: 10pt;
            }
            QPushButton {
                color: #ffffff;
                background-color: #4b2e83;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:disabled {
                background-color: #555555;
            }
            QTableWidget {
                background-color: #ffffff;
                gridline-color: #c0c0c0;
                font-size: 9pt;
            }
            QHeaderView::section {
                background-color: #4b2e83;
                color: white;
                font-weight: bold;
            }
        """)

    def _connect_signals(self):
        self.generate_button.clicked.connect(self.on_generate)
        self.solve_button.clicked.connect(self.on_solve)
        self.improve_button.clicked.connect(self.on_improve)
        self.export_button.clicked.connect(self.on_export)
        self.view_type_combo.currentIndexChanged.connect(self.update_entities)
        self.entity_combo.currentIndexChanged.connect(self.update_table)
        self.week_combo.currentIndexChanged.connect(self.update_table)
        self.table.cellDoubleClicked.connect(self.on_cell_double_clicked)

    # ----- helpers -----

    def set_status(self, text: str):
        self.status_label.setText(text)
        QApplication.processEvents()

    def set_busy(self, busy: bool):
        for b in [self.generate_button, self.solve_button, self.improve_button, self.export_button]:
            b.setEnabled(not busy)

    def populate_weeks(self):
        self.week_combo.blockSignals(True)
        self.week_combo.clear()
        if self.inst is not None:
            for w in self.inst.weeks:
                self.week_combo.addItem(f"Week {w}", w)
        self.week_combo.blockSignals(False)

    def update_entities(self):
        if self.inst is None:
            self.entity_combo.clear()
            return
        view_type = self.view_type_combo.currentText()
        self.entity_combo.blockSignals(True)
        self.entity_combo.clear()
        if view_type == "Group":
            for g_id, g in self.inst.groups.items():
                self.entity_combo.addItem(f"{g.name} (id {g_id})", ("group", g_id))
        elif view_type == "Staff":
            for s_id, s in self.inst.staff.items():
                self.entity_combo.addItem(f"{s.name} (id {s_id})", ("staff", s_id))
        else:
            for r_id, r in self.inst.rooms.items():
                self.entity_combo.addItem(f"{r.name} (id {r_id})", ("room", r_id))
        self.entity_combo.blockSignals(False)

    def clear_table(self):
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)

    # ----- actions -----

    def on_generate(self):
        if self.proc is not None:
            QMessageBox.warning(self, "Busy", "Wait for solving to finish first.")
            return
        mode = self.mode_combo.currentText()
        try:
            self.inst = generate_instance(mode=mode)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Generate error", str(e))
            return

        self.base_schedule = {}
        self.current_schedule = {}
        self.set_status(f"Instance generated ({mode})")
        self.populate_weeks()
        self.update_entities()
        self.clear_table()

    def on_solve(self):
        if self.inst is None:
            self.set_status("Generate instance first")
            return
        if self.proc is not None:
            QMessageBox.warning(self, "Busy", "Solver already running.")
            return

        # write instance to temp file
        tmp_dir = tempfile.gettempdir()
        inst_name = f"tt_inst_{uuid.uuid4().hex}.pkl"
        res_name = f"tt_res_{uuid.uuid4().hex}.pkl"
        self.tmp_inst_path = os.path.join(tmp_dir, inst_name)
        self.tmp_res_path = os.path.join(tmp_dir, res_name)

        try:
            with open(self.tmp_inst_path, "wb") as f:
                pickle.dump(self.inst, f)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "File error", f"Cannot write instance: {e}")
            self.tmp_inst_path = None
            self.tmp_res_path = None
            return

        python_exe = sys.executable
        base_dir = os.path.dirname(os.path.abspath(__file__))
        solver_script = os.path.join(base_dir, "engine_cli.py")

        self.proc = QProcess(self)
        self.proc.setProgram(python_exe)
        self.proc.setArguments([solver_script, self.tmp_inst_path, self.tmp_res_path])
        self.proc.finished.connect(self.on_solver_finished)
        self.proc.errorOccurred.connect(self.on_solver_error)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)

        self.set_busy(True)
        self.set_status("Solving in external process...")
        self.proc.start()

    def on_solver_error(self, error):
        self.set_busy(False)
        msg = self.proc.readAll().data().decode("utf-8", errors="ignore") if self.proc else ""
        QMessageBox.critical(self, "Solver error", msg or f"QProcess error: {error}")
        self.proc = None
        self.set_status("Solve error")

    def on_solver_finished(self, exit_code: int, exit_status):
        self.set_busy(False)

        output = ""
        if self.proc is not None:
            output = self.proc.readAll().data().decode("utf-8", errors="ignore")
        if exit_code != 0:
            QMessageBox.critical(
                self,
                "Solver crashed",
                output or f"Solver exited with code {exit_code}",
            )
            self.proc = None
            self.set_status(f"Solver failed (code {exit_code})")
            return

        self.proc = None

        if not self.tmp_res_path or not os.path.exists(self.tmp_res_path):
            QMessageBox.critical(self, "Result error", "Result file not found.")
            self.set_status("Solve error")
            return

        try:
            with open(self.tmp_res_path, "rb") as f:
                res = pickle.load(f)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Result error", f"Cannot read result: {e}")
            self.set_status("Solve error")
            return
        finally:
            # clean up temp files
            if self.tmp_inst_path and os.path.exists(self.tmp_inst_path):
                try:
                    os.remove(self.tmp_inst_path)
                except OSError:
                    pass
            if self.tmp_res_path and os.path.exists(self.tmp_res_path):
                try:
                    os.remove(self.tmp_res_path)
                except OSError:
                    pass
            self.tmp_inst_path = None
            self.tmp_res_path = None

        status = res.get("status", -1)
        if status not in (0, 4):  # FEASIBLE=0, OPTIMAL=4
            self.base_schedule = {}
            self.current_schedule = {}
            self.clear_table()
            self.set_status(f"No feasible schedule (status {status})")
            return

        self.base_schedule = res.get("schedule", {})
        self.current_schedule = {a_id: info.copy() for a_id, info in self.base_schedule.items()}
        obj = res.get("objective", 0.0)
        self.set_status(f"Solved, objective={obj:.0f}")
        self.update_entities()
        self.update_table()

    def on_improve(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to improve")
            return

        self.set_status("Improving...")
        QApplication.processEvents()
        try:
            ls = LocalSearchImprover(self.inst)
            before = ls.compute_soft_penalty(self.current_schedule)
            improved = ls.improve(self.current_schedule, iterations=300)
            after = ls.compute_soft_penalty(improved)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Improve error", str(e))
            self.set_status("Improve error")
            return

        self.current_schedule = {a_id: info.copy() for a_id, info in improved.items()}
        self.set_status(f"Improved penalty {before} -> {after}")
        self.update_table()

    def on_export(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to export")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export group schedules",
            "timetable.docx",
            "Word document (*.docx)",
        )
        if not path:
            return

        try:
            self.set_status("Exporting...")
            export_group_schedules_to_docx(self.inst, self.current_schedule, path)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Export error", str(e))
            self.set_status("Export error")
            return

        self.set_status(f"Exported to {path}")

    # ----- table rendering -----

    def update_table(self):
        if self.inst is None or not self.current_schedule:
            self.clear_table()
            return
        if self.entity_combo.count() == 0 or self.week_combo.count() == 0:
            self.clear_table()
            return

        data = self.entity_combo.currentData()
        if data is None:
            self.clear_table()
            return
        view_type, entity_id = data

        week_data = self.week_combo.currentData()
        if week_data is None:
            self.clear_table()
            return
        week = int(week_data)

        days = self.inst.days
        slots = self.inst.slots_per_day

        self.table.setRowCount(len(days))
        self.table.setColumnCount(slots)
        self.table.setVerticalHeaderLabels(days)
        self.table.setHorizontalHeaderLabels([f"S{idx+1}" for idx in range(slots)])

        cell_content = {(d, s): [] for d in days for s in range(slots)}

        for a_id, info in self.current_schedule.items():
            if info["week"] != week:
                continue
            day = info["day"]
            start = info["slot"]
            dur = info["duration"]

            if view_type == "Group":
                if entity_id not in info["group_ids"]:
                    continue
            elif view_type == "Staff":
                if entity_id != info["staff_id"]:
                    continue
            else:
                if entity_id != info["room_id"]:
                    continue

            course = self.inst.courses.get(info["course_id"])
            label = f"A{a_id} {course.code if course else ''} {info['kind']}"
            for ds in range(dur):
                s = start + ds
                if 0 <= s < slots:
                    cell_content[day, s].append(label)

        for row, day in enumerate(days):
            for col in range(slots):
                items = cell_content[day, col]
                text = "\n".join(items)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, col, item)

    # ----- manual edit -----

    def on_cell_double_clicked(self, row: int, col: int):
        if self.inst is None or not self.current_schedule:
            return
        if self.entity_combo.count() == 0 or self.week_combo.count() == 0:
            return

        data = self.entity_combo.currentData()
        if data is None:
            return
        view_type, entity_id = data

        week_data = self.week_combo.currentData()
        if week_data is None:
            return
        week = int(week_data)

        day = self.inst.days[row]
        slot = col

        act_ids = []
        for a_id, info in self.current_schedule.items():
            if info["week"] != week:
                continue
            if info["day"] != day:
                continue
            start = info["slot"]
            dur = info["duration"]
            if slot < start or slot >= start + dur:
                continue
            if view_type == "Group":
                if entity_id not in info["group_ids"]:
                    continue
            elif view_type == "Staff":
                if entity_id != info["staff_id"]:
                    continue
            else:
                if entity_id != info["room_id"]:
                    continue
            act_ids.append(a_id)

        if not act_ids:
            return

        dlg = EditActivityDialog(self, self.inst, self.current_schedule, act_ids, week, day, slot)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        a_id, new_day, new_slot, new_room, new_staff = dlg.get_values()
        ok, reason = self.check_move(a_id, new_day, new_slot, new_room, new_staff)
        if not ok:
            QMessageBox.warning(self, "Invalid move", reason)
            return

        info = self.current_schedule[a_id]
        info["day"] = new_day
        info["slot"] = new_slot
        info["room_id"] = new_room
        info["staff_id"] = new_staff
        self.update_table()
        self.set_status(f"Edited A{a_id}")

    def check_move(self, a_id: int, new_day: str, new_slot: int,
                   new_room_id: int, new_staff_id: int) -> Tuple[bool, str]:
        inst = self.inst
        schedule = self.current_schedule
        act = inst.activities[a_id]
        info = schedule[a_id]
        w = info["week"]
        dur = info["duration"]
        groups = info["group_ids"]

        if new_slot < 0 or new_slot + dur > inst.slots_per_day:
            return False, "Activity would overflow the day."

        staff = inst.staff[new_staff_id]
        if new_day not in staff.available_days:
            return False, "Staff unavailable on that day."

        day_load = 0
        week_load = 0
        for b_id, b in schedule.items():
            if b_id == a_id:
                continue
            if b["staff_id"] != new_staff_id:
                continue
            if b["week"] == w:
                week_load += b["duration"]
                if b["day"] == new_day:
                    day_load += b["duration"]
        day_load += dur
        week_load += dur
        if staff.max_slots_per_day is not None and day_load > staff.max_slots_per_day:
            return False, "Staff daily load limit exceeded."
        if staff.max_slots_per_week is not None and week_load > staff.max_slots_per_week:
            return False, "Staff weekly load limit exceeded."

        room = inst.rooms[new_room_id]
        total_students = sum(inst.groups[g].size for g in groups)
        if room.capacity < total_students:
            return False, "Room capacity too small."

        if act.kind == "LAB":
            if room.room_type not in ("COMPUTER_LAB", "SPECIALIZED_LAB"):
                return False, "Lab must be in a lab room."
            if act.requires_specialization and act.requires_specialization not in room.specialization_tags:
                return False, "Wrong specialized lab."
        else:
            if room.room_type not in ("LECTURE", "TUTORIAL"):
                return False, "Lecture/Tutorial must use lecture/tutorial room."

        new_slots = set(range(new_slot, new_slot + dur))
        for b_id, b in schedule.items():
            if b_id == a_id:
                continue
            if b["week"] != w or b["day"] != new_day:
                continue
            other_slots = set(range(b["slot"], b["slot"] + b["duration"]))
            if not (new_slots & other_slots):
                continue
            if b["staff_id"] == new_staff_id:
                return False, f"Staff conflict with A{b_id}."
            if b["room_id"] == new_room_id:
                return False, f"Room conflict with A{b_id}."
            if set(groups) & set(b["group_ids"]):
                return False, f"Group conflict with A{b_id}."

        return True, ""


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1200, 650)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
