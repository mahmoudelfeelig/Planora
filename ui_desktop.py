# ui_desktop.py

import sys
from typing import Dict, Any, Tuple, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem, QLabel,
    QMessageBox, QFileDialog, QDialog, QFormLayout
)

from generator import generate_instance
from solver_cp_sat import TimetableSolver
from metaheuristics import LocalSearchImprover
from exporter import export_group_schedules_to_docx
from ortools.sat.python import cp_model


class EditActivityDialog(QDialog):
    """
    Dialog to edit a single activity's day/slot/room/staff.
    """
    def __init__(self, parent, inst, schedule, act_ids: List[int], week: int, day: str, slot: int):
        super().__init__(parent)
        self.inst = inst
        self.schedule = schedule
        self.act_ids = act_ids
        self.week = week

        self.setWindowTitle("Edit activity")
        layout = QFormLayout()
        self.setLayout(layout)

        # activity selector
        self.activity_combo = QComboBox()
        for a_id in act_ids:
            info = schedule[a_id]
            course = inst.courses.get(info["course_id"])
            text = f"A{a_id} {course.code if course else ''} {info['kind']}"
            self.activity_combo.addItem(text, a_id)
        layout.addRow("Activity:", self.activity_combo)

        # day
        self.day_combo = QComboBox()
        for d in inst.days:
            self.day_combo.addItem(d, d)
        idx = self.day_combo.findData(day)
        if idx >= 0:
            self.day_combo.setCurrentIndex(idx)
        layout.addRow("Day:", self.day_combo)

        # slot
        self.slot_combo = QComboBox()
        for s in range(inst.slots_per_day):
            self.slot_combo.addItem(str(s + 1), s)
        idx = self.slot_combo.findData(slot)
        if idx >= 0:
            self.slot_combo.setCurrentIndex(idx)
        layout.addRow("Start slot:", self.slot_combo)

        # room
        self.room_combo = QComboBox()
        for r_id, r in inst.rooms.items():
            self.room_combo.addItem(f"{r.name} (id {r_id})", r_id)
        # preselect current room
        cur_a_id = self.activity_combo.currentData()
        cur_info = schedule[cur_a_id]
        cur_room = cur_info["room_id"]
        idx = self.room_combo.findData(cur_room)
        if idx >= 0:
            self.room_combo.setCurrentIndex(idx)
        layout.addRow("Room:", self.room_combo)

        # staff
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("University Timetabling")

        self.inst = None
        self.base_schedule: Dict[int, Dict[str, Any]] = {}
        self.current_schedule: Dict[int, Dict[str, Any]] = {}

        self._build_ui()
        self._connect_signals()

    # ---------- UI setup ----------

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

        # basic modern-ish style
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

    # ---------- helpers ----------

    def set_status(self, text: str):
        self.status_label.setText(text)
        QApplication.processEvents()

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

    # ---------- actions ----------

    def on_generate(self):
        mode = self.mode_combo.currentText()
        self.inst = generate_instance(mode=mode)
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

        self.set_status("Solving...")
        solver_model = TimetableSolver(self.inst)
        cp_solver, status = solver_model.solve(time_limit_seconds=60)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            self.set_status(f"No feasible schedule (status {status})")
            self.base_schedule = {}
            self.current_schedule = {}
            self.clear_table()
            return

        self.base_schedule = solver_model.extract_solution(cp_solver)
        self.current_schedule = {a_id: info.copy() for a_id, info in self.base_schedule.items()}
        self.set_status(f"Solved, objective={cp_solver.ObjectiveValue():.0f}")
        self.update_entities()
        self.update_table()

    def on_improve(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to improve")
            return
        self.set_status("Improving...")
        ls = LocalSearchImprover(self.inst)
        before = ls.compute_soft_penalty(self.current_schedule)
        improved = ls.improve(self.current_schedule, iterations=300)
        after = ls.compute_soft_penalty(improved)
        self.current_schedule = improved
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
        self.set_status("Exporting...")
        export_group_schedules_to_docx(self.inst, self.current_schedule, path)
        self.set_status(f"Exported to {path}")

    # ---------- table rendering ----------

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

    # ---------- manual edit ----------

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
        slots_per_day = self.inst.slots_per_day

        # find activities in this cell under current view
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

        # apply move
        info = self.current_schedule[a_id]
        info["day"] = new_day
        info["slot"] = new_slot
        info["room_id"] = new_room
        info["staff_id"] = new_staff
        self.update_table()
        self.set_status(f"Edited A{a_id}")

    def check_move(self, a_id: int, new_day: str, new_slot: int,
                   new_room_id: int, new_staff_id: int) -> Tuple[bool, str]:
        """
        Hard constraint check for a single edited activity.
        """
        inst = self.inst
        schedule = self.current_schedule
        act = inst.activities[a_id]
        info = schedule[a_id]
        w = info["week"]
        dur = info["duration"]
        groups = info["group_ids"]

        # slot range
        if new_slot < 0 or new_slot + dur > inst.slots_per_day:
            return False, "Activity would overflow the day."

        # staff availability and load
        staff = inst.staff[new_staff_id]
        if new_day not in staff.available_days:
            return False, "Staff is not available on that day."

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

        # room type/capacity
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
                return False, "Lecture/Tutorial must use a lecture/tutorial room."

        # conflicts with other activities at same time
        new_slots = set(range(new_slot, new_slot + dur))
        for b_id, b in schedule.items():
            if b_id == a_id:
                continue
            if b["week"] != w or b["day"] != new_day:
                continue
            other_slots = set(range(b["slot"], b["slot"] + b["duration"]))
            if not (new_slots & other_slots):
                continue

            # staff conflict
            if b["staff_id"] == new_staff_id:
                return False, f"Staff conflict with activity A{b_id}."

            # room conflict
            if b["room_id"] == new_room_id:
                return False, f"Room conflict with activity A{b_id}."

            # group conflict
            if set(groups) & set(b["group_ids"]):
                return False, f"Group conflict with activity A{b_id}."

        return True, ""


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1200, 650)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
