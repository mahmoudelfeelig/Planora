from __future__ import annotations

import sys
import os
import uuid
import pickle
import tempfile
import traceback
from typing import Dict, Any, Tuple, List

from PyQt6.QtCore import Qt, QProcess
from PyQt6.QtGui import QBrush, QColor, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QLabel,
    QMessageBox,
    QFileDialog,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QSpinBox,
    QAbstractSpinBox,
)

from generator import generate_instance
from metaheuristics import LocalSearchImprover
from exporter import export_group_schedules_to_docx
from domain import Instance
from main import normalize_instance_for_spec, check_staff_weekly_capacity, stamp_instance_time

# Default time grid for exports/labels (matches main.py)
DAY_START = "08:30"
SLOT_MINUTES = 90
BREAK_MINUTES = 0


# ---------- Edit dialog ----------

class EditActivityDialog(QDialog):
    def __init__(
        self,
        parent,
        inst: Instance,
        schedule: Dict[int, Dict[str, Any]],
        act_ids: List[int],
        week: int,
        day: str,
        slot: int,
    ):
        super().__init__(parent)
        self.inst = inst
        self.schedule = schedule
        self.act_ids = act_ids
        self.week = week

        self.setWindowTitle("Edit activity")
        layout = QFormLayout(self)

        self.activity_combo = QComboBox()
        for a_id in act_ids:
            info = schedule[a_id]
            course = inst.courses.get(info["course_id"])
            label = f"A{a_id}"
            if course:
                label += f" {course.code} {course.name}"
            label += f" ({info['kind']})"
            self.activity_combo.addItem(label, a_id)
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

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_values(self) -> Tuple[int, str, int, int, int]:
        a_id = self.activity_combo.currentData()
        day = self.day_combo.currentData()
        slot = self.slot_combo.currentData()
        room_id = self.room_combo.currentData()
        staff_id = self.staff_combo.currentData()
        return a_id, day, slot, room_id, staff_id


# ---------- Main window ----------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("University Timetabling")
        icon_path = os.path.join(os.path.dirname(__file__), "app_icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.inst: Instance | None = None
        self.base_schedule: Dict[int, Dict[str, Any]] = {}
        self.current_schedule: Dict[int, Dict[str, Any]] = {}

        self.proc: QProcess | None = None
        self.tmp_inst_path: str | None = None
        self.tmp_res_path: str | None = None

        self._build_ui()
        self._connect_signals()

    # ----- UI setup -----

    def _build_ui(self):
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(
            [
                "small_demo",
                "block_profs",
                "labs_only",
                "mixed_large",
                "random",
                "target_case",
            ]
        )

        self.generate_button = QPushButton("Generate")
        self.solve_button = QPushButton("Solve")
        self.improve_button = QPushButton("Improve")

        self.improve_runs_spin = QSpinBox()
        self.improve_runs_spin.setRange(10, 100000)
        self.improve_runs_spin.setSingleStep(10)
        self.improve_runs_spin.setValue(1000)
        self.improve_runs_spin.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.UpDownArrows
        )
        self.improve_runs_spin.setMinimumWidth(90)

        self.export_button = QPushButton("Export DOCX")

        self.view_type_combo = QComboBox()
        self.view_type_combo.addItems(["Group", "Staff", "Room"])
        self.entity_combo = QComboBox()
        self.week_combo = QComboBox()

        self.status_label = QLabel("Ready")
        self.quality_label = QLabel("")
        self.quality_label.setWordWrap(True)

        top_layout.addWidget(QLabel("Mode:"))
        top_layout.addWidget(self.mode_combo)
        top_layout.addWidget(self.generate_button)
        top_layout.addWidget(self.solve_button)
        top_layout.addWidget(self.improve_button)
        top_layout.addWidget(QLabel("Iterations:"))
        top_layout.addWidget(self.improve_runs_spin)
        top_layout.addWidget(self.export_button)
        top_layout.addWidget(QLabel("View:"))
        top_layout.addWidget(self.view_type_combo)
        top_layout.addWidget(self.entity_combo)
        top_layout.addWidget(QLabel("Week:"))
        top_layout.addWidget(self.week_combo)
        top_layout.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(True)
        self.table.horizontalHeader().setVisible(True)
        self.table.setWordWrap(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultSectionSize(160)
        self.table.verticalHeader().setDefaultSectionSize(34)

        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.addWidget(top_widget)
        main_layout.addWidget(self.table)
        main_layout.addWidget(self.quality_label)
        self.setCentralWidget(central)

        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #121212;
            }
            QLabel {
                color: #f5f5f5;
                font-size: 10pt;
            }
            QComboBox, QPushButton, QSpinBox {
                font-size: 10pt;
            }
            QComboBox, QSpinBox {
                background-color: #1f1f23;
                color: #f5f5f5;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 2px 6px;
            }
            QComboBox:hover, QSpinBox:hover {
                background-color: #26262b;
            }

            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #4b2e83;
                border: none;
                width: 18px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #6a44c2;
            }
            QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {
                background-color: #38215c;
            }

            QPushButton {
                color: #ffffff;
                background-color: #4b2e83;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #6a44c2;
            }
            QPushButton:pressed {
                background-color: #38215c;
            }
            QPushButton:disabled {
                background-color: #555555;
            }
            QTableWidget {
                background-color: #18181c;
                color: #f5f5f5;
                gridline-color: #3c3f41;
                font-size: 9pt;
            }
            QTableWidget::item:selected {
                background-color: #3c78d8;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #26262b;
                color: #f5f5f5;
                font-weight: bold;
            }
            """
        )

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
        enable = not busy
        for btn in [
            self.generate_button,
            self.solve_button,
            self.improve_button,
            self.export_button,
        ]:
            btn.setEnabled(enable)
        self.improve_runs_spin.setEnabled(enable)

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
                self.entity_combo.addItem(f"{g.name} (id {g_id})", g_id)
        elif view_type == "Staff":
            for s_id, s in self.inst.staff.items():
                self.entity_combo.addItem(f"{s.name} (id {s_id})", s_id)
        else:  # Room
            for r_id, r in self.inst.rooms.items():
                self.entity_combo.addItem(f"{r.name} (id {r_id})", r_id)

        self.entity_combo.blockSignals(False)
        self.update_table()

    def clear_table(self):
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.quality_label.setText("")

    # ----- actions -----

    def on_generate(self):
        if self.proc is not None:
            QMessageBox.warning(self, "Busy", "Wait for solving to finish first.")
            return

        mode = self.mode_combo.currentText()
        try:
            inst = generate_instance(mode=mode)
            normalize_instance_for_spec(inst)
            stamp_instance_time(inst, DAY_START, SLOT_MINUTES, BREAK_MINUTES)
            check_staff_weekly_capacity(inst)  # logs warnings to stdout
            self.inst = inst
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
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.finished.connect(self.on_solver_finished)
        self.proc.errorOccurred.connect(self.on_solver_error)

        self.set_busy(True)
        self.set_status("Solving in external process...")
        self.proc.start()

    def on_solver_error(self, error):
        self.set_busy(False)
        output = ""
        if self.proc is not None:
            try:
                output = (
                    self.proc.readAll().data().decode("utf-8", errors="ignore")
                )
            except Exception:
                output = ""
        QMessageBox.critical(
            self, "Solver error", output or f"QProcess error: {error}"
        )
        self.proc = None
        self.set_status("Solve error")

    def on_solver_finished(self, exit_code: int, exit_status):
        self.set_busy(False)

        output = ""
        if self.proc is not None:
            try:
                output = (
                    self.proc.readAll().data().decode("utf-8", errors="ignore")
                )
            except Exception:
                output = ""
        self.proc = None

        if exit_code != 0:
            QMessageBox.critical(
                self,
                "Solver crashed",
                output or f"Solver exited with code {exit_code}",
            )
            self.set_status(f"Solver failed (code {exit_code})")
            return

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
        if status not in (0, 4):  # 0=FEASIBLE, 4=OPTIMAL
            self.base_schedule = {}
            self.current_schedule = {}
            self.clear_table()
            self.set_status(f"No feasible schedule (status {status})")
            return

        self.base_schedule = res.get("schedule", {})
        self.current_schedule = {
            a_id: info.copy() for a_id, info in self.base_schedule.items()
        }

        try:
            if self.inst is not None and self.current_schedule:
                ls = LocalSearchImprover(self.inst)
                before = ls.compute_soft_penalty(self.current_schedule)
                improved = ls.improve(self.current_schedule, iterations=1000)
                after = ls.compute_soft_penalty(improved)
                self.current_schedule = {
                    a_id: info.copy() for a_id, info in improved.items()
                }
                self.set_status(
                    f"Solved (status {status}), soft penalty {before} -> {after}"
                )
        except Exception:
            traceback.print_exc()
            self.set_status(f"Solved (status {status}), local search skipped")

        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()

    def on_improve(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to improve")
            return

        total_iters = self.improve_runs_spin.value()

        try:
            ls = LocalSearchImprover(self.inst)
            base_schedule = {
                a_id: info.copy() for a_id, info in self.current_schedule.items()
            }
            base_pen = ls.compute_soft_penalty(base_schedule)

            self.set_status(f"Improving ({total_iters} iterations)...")
            QApplication.processEvents()

            improved = ls.improve(base_schedule, iterations=total_iters)
            best_pen = ls.compute_soft_penalty(improved)

            self.current_schedule = {
                a_id: info.copy() for a_id, info in improved.items()
            }
            self.set_status(
                f"Improved global penalty {base_pen} -> {best_pen} "
                f"in {total_iters} iterations"
            )
            self.update_table()
            self.update_quality_summary()

        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Improve error", str(e))
            self.set_status("Improve error")

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
        entity_id = int(data)
        view_type = self.view_type_combo.currentText()

        week_data = self.week_combo.currentData()
        if week_data is None:
            self.clear_table()
            return
        week = int(week_data)

        days = self.inst.days
        S = self.inst.slots_per_day

        self.table.setRowCount(len(days))
        self.table.setColumnCount(S)
        self.table.setVerticalHeaderLabels(days)
        self.table.setHorizontalHeaderLabels([f"S{idx + 1}" for idx in range(S)])

        cell_content: Dict[Tuple[str, int], List[str]] = {
            (d, s): [] for d in days for s in range(S)
        }

        for a_id, info in self.current_schedule.items():
            if info["week"] != week:
                continue
            day = info["day"]
            s0 = info["slot"]
            dur = info["duration"]

            if view_type == "Group":
                if entity_id not in info["group_ids"]:
                    continue
            elif view_type == "Staff":
                if entity_id != info["staff_id"]:
                    continue
            else:  # Room
                if entity_id != info["room_id"]:
                    continue

            course = self.inst.courses.get(info["course_id"])
            room = self.inst.rooms.get(info["room_id"])
            staff = self.inst.staff.get(info["staff_id"])

            parts: List[str] = []
            if course:
                parts.append(course.code)
                parts.append(course.name)
            parts.append(info["kind"])
            if room:
                parts.append(f"Room: {room.name}")
            if staff:
                parts.append(f"Staff: {staff.name}")

            label = "\n".join(parts)

            for ds in range(dur):
                s = s0 + ds
                if 0 <= s < S:
                    cell_content[(day, s)].append(label)

        for row, day in enumerate(days):
            for col in range(S):
                items = cell_content[(day, col)]
                text = "\n\n".join(items)
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                )
                item.setForeground(QBrush(QColor("#f5f5f5")))
                self.table.setItem(row, col, item)

        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()

        for c in range(self.table.columnCount()):
            if self.table.columnWidth(c) < 120:
                self.table.setColumnWidth(c, 120)
        for r in range(self.table.rowCount()):
            if self.table.rowHeight(r) < 34:
                self.table.setRowHeight(r, 34)

    # ----- per-group quality -----

    def compute_group_penalties(self, schedule: Dict[int, Dict[str, Any]]) -> Dict[int, int]:
        inst = self.inst
        if inst is None:
            return {}

        days = inst.days
        weeks = inst.weeks
        S = inst.slots_per_day

        W_STUD_FREE_DAYS = 10
        W_STUD_FREE_MF = 5
        W_STUD_GAPS = 5
        W_ACTIVE_DAYS = 3
        W_EARLY_START = 2
        W_BALANCE = 2
        W_STABILITY = 1

        group_occ: Dict[Tuple[int, int, str, int], int] = {}
        for g_id in inst.groups.keys():
            for w in weeks:
                for d in days:
                    for s in range(S):
                        group_occ[g_id, w, d, s] = 0

        for a_id, info in schedule.items():
            w = info["week"]
            d = info["day"]
            s0 = info["slot"]
            dur = info["duration"]
            for ds in range(dur):
                s = s0 + ds
                if s < 0 or s >= S:
                    continue
                for g_id in info["group_ids"]:
                    group_occ[g_id, w, d, s] = 1

        day_active: Dict[Tuple[int, int, str], int] = {}
        for g_id in inst.groups.keys():
            for w in weeks:
                for d in days:
                    occs = [group_occ[g_id, w, d, s] for s in range(S)]
                    day_active[g_id, w, d] = 1 if any(occs) else 0

        penalties: Dict[int, int] = {g_id: 0 for g_id in inst.groups.keys()}

        workdays = [d for d in days if d in {"MON", "TUE", "WED", "THU", "FRI"}]

        for g_id, g in inst.groups.items():
            pen = 0

            for w in weeks:
                free_days = sum(1 - day_active[g_id, w, d] for d in days)
                if free_days < g.preferred_free_days:
                    pen += W_STUD_FREE_DAYS * (g.preferred_free_days - free_days)

                free_mf = sum(1 - day_active[g_id, w, d] for d in workdays)
                if free_mf < g.preferred_free_days:
                    pen += W_STUD_FREE_MF * (g.preferred_free_days - free_mf)

                for d in days:
                    occ = [group_occ[g_id, w, d, s] for s in range(S)]
                    blocks = 0
                    prev = 0
                    load = 0
                    for v in occ:
                        if v == 1 and prev == 0:
                            blocks += 1
                        if v == 1:
                            load += 1
                        prev = v
                    if blocks > 1:
                        pen += W_STUD_GAPS * (blocks - 1)
                    if load > 3:
                        pen += W_BALANCE * (load - 3)

                active_days = sum(day_active[g_id, w, d] for d in days)
                if active_days > 3:
                    pen += W_ACTIVE_DAYS * (active_days - 3)

                for d in days:
                    occ = [group_occ[g_id, w, d, s] for s in range(S)]
                    if occ[0] == 1 and any(occ[s] == 1 for s in range(1, S)):
                        pen += W_EARLY_START

            for wi in range(1, len(weeks)):
                w_prev = weeks[wi - 1]
                w_curr = weeks[wi]
                for d in days:
                    if day_active[g_id, w_prev, d] != day_active[g_id, w_curr, d]:
                        pen += W_STABILITY

            penalties[g_id] = pen

        return penalties

    def classify_group_quality(self, pen: int) -> str:
        if pen <= 150:
            return "optimal"
        if pen <= 400:
            return "near-optimal"
        if pen <= 800:
            return "decent"
        return "bad"

    def update_quality_summary(self):
        if self.inst is None or not self.current_schedule:
            self.quality_label.setText("")
            return

        penalties = self.compute_group_penalties(self.current_schedule)
        if not penalties:
            self.quality_label.setText("")
            return

        parts: List[str] = []
        for g_id in sorted(self.inst.groups.keys()):
            pen = penalties.get(g_id, 0)
            g = self.inst.groups[g_id]
            status = self.classify_group_quality(pen)
            parts.append(f"{g.name}: {pen} ({status})")

        text = "Group quality:\n" + " | ".join(parts)
        self.quality_label.setText(text)

    # ----- manual edit -----

    def on_cell_double_clicked(self, row: int, col: int):
        if self.inst is None or not self.current_schedule:
            return
        if self.entity_combo.count() == 0 or self.week_combo.count() == 0:
            return

        data = self.entity_combo.currentData()
        if data is None:
            return
        entity_id = int(data)
        view_type = self.view_type_combo.currentText()

        week_data = self.week_combo.currentData()
        if week_data is None:
            return
        week = int(week_data)

        day = self.inst.days[row]
        slot = col

        act_ids: List[int] = []
        for a_id, info in self.current_schedule.items():
            if info["week"] != week:
                continue
            if info["day"] != day:
                continue
            s0 = info["slot"]
            dur = info["duration"]
            if slot < s0 or slot >= s0 + dur:
                continue

            if view_type == "Group":
                if entity_id not in info["group_ids"]:
                    continue
            elif view_type == "Staff":
                if entity_id != info["staff_id"]:
                    continue
            else:  # Room
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
        self.update_quality_summary()
        self.set_status(f"Edited A{a_id}")

    def check_move(
        self,
        a_id: int,
        new_day: str,
        new_slot: int,
        new_room_id: int,
        new_staff_id: int,
    ) -> Tuple[bool, str]:
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
    icon_path = os.path.join(os.path.dirname(__file__), "app_icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    win = MainWindow()
    win.resize(1300, 720)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
