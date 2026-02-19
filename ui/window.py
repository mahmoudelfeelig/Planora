from __future__ import annotations

import sys
import os
import uuid
import pickle
import tempfile
import traceback
from typing import Dict, Any, Tuple, List

# Allow running directly (python ui/window.py) by ensuring repo root on sys.path
ROOT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from PyQt6.QtCore import Qt, QProcess
from PyQt6.QtGui import QBrush, QColor, QIcon, QAction
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QGridLayout,
    QPushButton,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QLabel,
    QDialog,
    QMessageBox,
    QFileDialog,
    QSpinBox,
    QAbstractSpinBox,
    QCheckBox,
    QToolButton,
    QMenu,
    QSizePolicy,
    QHeaderView,
)

from ui.constants import (
    DEFAULT_DAY_START,
    DEFAULT_SLOT_MINUTES,
    DEFAULT_BREAK_MINUTES,
    DEFAULT_TIME_LIMIT,
    DEFAULT_CP_WORKERS,
)
from ui.dialogs import EditActivityDialog
from ui.styles import DARK_STYLE
from utils.generator import generate_instance
from core.metaheuristics import LocalSearchImprover
from utils.exporter import (
    export_group_schedules_to_docx,
    export_groups_pdf,
    export_summary_reports,
    export_schedule_to_csv,
    export_groups_ics_per_id,
    export_staff_ics_per_id,
    export_rooms_ics_per_id,
)
from utils.domain import Instance
from utils.io import read_scenario, write_scenario, read_instance, read_schedule_csv
from utils.compare import compare_schedules, write_comparison_report
from utils.feasibility import explain_infeasibility
from utils.specs import validate_instance_against_spec, validate_schedule_against_instance
from main import normalize_instance_for_spec, check_staff_weekly_capacity, stamp_instance_time


# ---------- Main window ----------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("University Timetabling")
        icon_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "app_icon.png"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.inst: Instance | None = None
        self.base_schedule: Dict[int, Dict[str, Any]] = {}
        self.current_schedule: Dict[int, Dict[str, Any]] = {}
        self.locked_activities: Dict[int, Dict[str, Any]] = {}

        self.proc: QProcess | None = None
        self.tmp_inst_path: str | None = None
        self.tmp_res_path: str | None = None

        self._build_ui()
        self._connect_signals()

    # ----- UI setup -----

    def _build_ui(self):
        top_widget = QWidget()
        top_layout = QGridLayout(top_widget)
        top_layout.setHorizontalSpacing(10)
        top_layout.setVerticalSpacing(6)

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
        self.resolve_button = QPushButton("Re-solve")
        self.clear_locks_button = QPushButton("Clear Locks")
        self.improve_button = QPushButton("Improve")

        self.room_mode_combo = QComboBox()
        self.room_mode_combo.addItems(["Strict (CP rooms)", "Fast (Greedy rooms)"])
        self.room_mode_combo.setCurrentIndex(0)

        self.objective_cb = QCheckBox("Use CP objective")
        self.objective_cb.setChecked(True)

        self.time_limit_spin = QSpinBox()
        self.time_limit_spin.setRange(5, 600)
        self.time_limit_spin.setValue(DEFAULT_TIME_LIMIT)
        self.time_limit_spin.setSuffix(" s")

        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 64)
        self.workers_spin.setValue(DEFAULT_CP_WORKERS)

        self.improve_runs_spin = QSpinBox()
        self.improve_runs_spin.setRange(10, 100000)
        self.improve_runs_spin.setSingleStep(10)
        self.improve_runs_spin.setValue(1000)
        self.improve_runs_spin.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.UpDownArrows
        )
        self.improve_runs_spin.setMinimumWidth(90)

        self.ls_time_spin = QSpinBox()
        self.ls_time_spin.setRange(0, 600)
        self.ls_time_spin.setValue(10)
        self.ls_time_spin.setSuffix(" s")

        self.export_menu_btn = QToolButton()
        self.export_menu_btn.setText("Export")
        self.export_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.export_menu = QMenu(self.export_menu_btn)
        self.export_menu_btn.setMenu(self.export_menu)

        self.project_menu_btn = QToolButton()
        self.project_menu_btn.setText("Project")
        self.project_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.project_menu = QMenu(self.project_menu_btn)
        self.project_menu_btn.setMenu(self.project_menu)

        self.view_type_combo = QComboBox()
        self.view_type_combo.addItems(["Group", "Staff", "Room"])
        self.entity_combo = QComboBox()
        self.week_combo = QComboBox()

        self.status_label = QLabel("Ready")
        self.quality_label = QLabel("")
        self.quality_label.setWordWrap(True)

        # Row 0: main actions
        r = 0
        c = 0
        top_layout.addWidget(QLabel("Mode:"), r, c); c += 1
        top_layout.addWidget(self.mode_combo, r, c); c += 1
        top_layout.addWidget(self.generate_button, r, c); c += 1
        top_layout.addWidget(self.solve_button, r, c); c += 1
        top_layout.addWidget(self.resolve_button, r, c); c += 1
        top_layout.addWidget(self.clear_locks_button, r, c); c += 1
        top_layout.addWidget(self.improve_button, r, c); c += 1
        top_layout.addWidget(self.export_menu_btn, r, c); c += 1
        top_layout.addWidget(self.project_menu_btn, r, c); c += 1

        # Row 1: tuning
        r = 1
        c = 0
        top_layout.addWidget(QLabel("LS iters:"), r, c); c += 1
        top_layout.addWidget(self.improve_runs_spin, r, c); c += 1
        top_layout.addWidget(QLabel("LS time:"), r, c); c += 1
        top_layout.addWidget(self.ls_time_spin, r, c); c += 1
        top_layout.addWidget(QLabel("Room mode:"), r, c); c += 1
        top_layout.addWidget(self.room_mode_combo, r, c); c += 1
        top_layout.addWidget(self.objective_cb, r, c); c += 1
        top_layout.addWidget(QLabel("Limit:"), r, c); c += 1
        top_layout.addWidget(self.time_limit_spin, r, c); c += 1
        top_layout.addWidget(QLabel("Workers:"), r, c); c += 1
        top_layout.addWidget(self.workers_spin, r, c); c += 1

        # Row 2: view controls + status
        r = 2
        c = 0
        top_layout.addWidget(QLabel("View:"), r, c); c += 1
        top_layout.addWidget(self.view_type_combo, r, c); c += 1
        top_layout.addWidget(self.entity_combo, r, c); c += 1
        top_layout.addWidget(QLabel("Week:"), r, c); c += 1
        top_layout.addWidget(self.week_combo, r, c); c += 1
        top_layout.addWidget(self.status_label, r, c); c += 1
        top_layout.setColumnStretch(c, 1)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(True)
        self.table.horizontalHeader().setVisible(True)
        self.table.setWordWrap(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.addWidget(top_widget)
        main_layout.addWidget(self.table)
        main_layout.addWidget(self.quality_label)
        self.setCentralWidget(central)

        self.setStyleSheet(DARK_STYLE)

        self._build_menus()

    def _connect_signals(self):
        self.generate_button.clicked.connect(self.on_generate)
        self.solve_button.clicked.connect(self.on_solve)
        self.resolve_button.clicked.connect(self.on_resolve)
        self.clear_locks_button.clicked.connect(self.on_clear_locks)
        self.improve_button.clicked.connect(self.on_improve)
        self.view_type_combo.currentIndexChanged.connect(self.update_entities)
        self.entity_combo.currentIndexChanged.connect(self.update_table)
        self.week_combo.currentIndexChanged.connect(self.update_table)
        self.table.cellDoubleClicked.connect(self.on_cell_double_clicked)

    def _build_menus(self):
        # Export menu
        act_docx = QAction("Export DOCX", self)
        act_docx.triggered.connect(self.on_export)
        act_pdf = QAction("Export PDF", self)
        act_pdf.triggered.connect(self.on_export_pdf)
        act_reports = QAction("Export Reports", self)
        act_reports.triggered.connect(self.on_export_reports)
        act_csv = QAction("Export CSV", self)
        act_csv.triggered.connect(self.on_export_csv)
        act_ics = QAction("Export ICS", self)
        act_ics.triggered.connect(self.on_export_ics)

        self.export_menu.addAction(act_docx)
        self.export_menu.addAction(act_pdf)
        self.export_menu.addSeparator()
        self.export_menu.addAction(act_reports)
        self.export_menu.addAction(act_csv)
        self.export_menu.addAction(act_ics)

        # Project menu
        act_save = QAction("Save Project", self)
        act_save.triggered.connect(self.on_save_project)
        act_load = QAction("Load Project", self)
        act_load.triggered.connect(self.on_load_project)
        act_compare = QAction("Compare", self)
        act_compare.triggered.connect(self.on_compare)
        act_load_inst = QAction("Load Instance", self)
        act_load_inst.triggered.connect(self.on_load_instance)
        act_load_sched = QAction("Load Schedule (CSV)", self)
        act_load_sched.triggered.connect(self.on_load_schedule)

        self.project_menu.addAction(act_save)
        self.project_menu.addAction(act_load)
        self.project_menu.addSeparator()
        self.project_menu.addAction(act_compare)
        self.project_menu.addSeparator()
        self.project_menu.addAction(act_load_inst)
        self.project_menu.addAction(act_load_sched)

    # ----- helpers -----

    def set_status(self, text: str):
        self.status_label.setText(text)
        QApplication.processEvents()

    def set_busy(self, busy: bool):
        enable = not busy
        for btn in [
            self.generate_button,
            self.solve_button,
            self.resolve_button,
            self.clear_locks_button,
            self.improve_button,
            self.export_menu_btn,
            self.project_menu_btn,
        ]:
            btn.setEnabled(enable)
        self.improve_runs_spin.setEnabled(enable)
        self.ls_time_spin.setEnabled(enable)
        self.room_mode_combo.setEnabled(enable)
        self.objective_cb.setEnabled(enable)
        self.time_limit_spin.setEnabled(enable)
        self.workers_spin.setEnabled(enable)

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
            stamp_instance_time(
                inst,
                DEFAULT_DAY_START,
                DEFAULT_SLOT_MINUTES,
                DEFAULT_BREAK_MINUTES,
            )
            check_staff_weekly_capacity(inst)  # logs warnings to stdout
            self.inst = inst
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Generate error", str(e))
            return

        self.base_schedule = {}
        self.current_schedule = {}
        self.locked_activities = {}
        self.set_status(f"Instance generated ({mode})")
        self.populate_weeks()
        self.update_entities()
        self.clear_table()

    def _start_solver_process(self, *, keep_locks: bool) -> None:
        if self.inst is None:
            self.set_status("Generate instance first")
            return
        if self.proc is not None:
            QMessageBox.warning(self, "Busy", "Solver already running.")
            return

        if not keep_locks:
            self.locked_activities = {}

        # Push locks into the instance so the worker can fix them.
        self.inst.locked_activities = dict(self.locked_activities)

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
        solver_script = os.path.normpath(os.path.join(base_dir, "..", "core", "engine_cli.py"))

        self.proc = QProcess(self)
        self.proc.setProgram(python_exe)
        self.proc.setArguments([solver_script, self.tmp_inst_path, self.tmp_res_path])
        env_map = os.environ.copy()
        env_map["TT_ROOM_MODE"] = "cp_rooms" if self.room_mode_combo.currentIndex() == 0 else "greedy"
        env_map["TT_TIME_LIMIT"] = str(self.time_limit_spin.value())
        env_map["TT_CP_WORKERS"] = str(self.workers_spin.value())
        env_map["TT_USE_OBJECTIVE"] = "1" if self.objective_cb.isChecked() else "0"
        # ensure the worker can import core/utils modules
        env_map["PYTHONPATH"] = os.pathsep.join([os.path.dirname(os.path.dirname(os.path.abspath(__file__))), env_map.get("PYTHONPATH", "")])
        try:
            from PyQt6.QtCore import QProcessEnvironment

            penv = QProcessEnvironment.systemEnvironment()
            for k, v in env_map.items():
                penv.insert(k, str(v))
            self.proc.setProcessEnvironment(penv)
        except Exception:
            # Fallback for platforms without QProcessEnvironment
            self.proc.setEnvironment([f"{k}={v}" for k, v in env_map.items()])
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.finished.connect(self.on_solver_finished)
        self.proc.errorOccurred.connect(self.on_solver_error)

        self.set_busy(True)
        lock_count = len(self.locked_activities)
        self.set_status("Solving in external process..." + (f" (locks={lock_count})" if lock_count else ""))
        self.proc.start()

    def on_solve(self):
        self._start_solver_process(keep_locks=False)

    def on_resolve(self):
        if not self.current_schedule:
            self.set_status("No schedule yet; run Solve first")
            return
        self._start_solver_process(keep_locks=True)

    def on_clear_locks(self):
        self.locked_activities = {}
        if self.inst is not None:
            self.inst.locked_activities = {}
        self.set_status("Locks cleared")

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
            if res.get("error"):
                msg = res.get("error")
                if res.get("reason"):
                    msg += f"\nReason: {res.get('reason')}"
                QMessageBox.information(self, "Solver error", msg)
            elif self.inst is not None:
                reasons = explain_infeasibility(self.inst)
                if reasons:
                    msg = "Likely causes:\n" + "\n".join(f"- {r}" for r in reasons)
                else:
                    msg = (
                        "No specific conflicts detected. "
                        "Try increasing the time limit or relaxing constraints."
                    )
                QMessageBox.information(self, "No feasible schedule", msg)
            return

        self.base_schedule = res.get("schedule", {})
        self.current_schedule = {
            a_id: info.copy() for a_id, info in self.base_schedule.items()
        }

        try:
            if self.inst is not None and self.current_schedule:
                ls = LocalSearchImprover(self.inst)
                before = ls.compute_soft_penalty(self.current_schedule)
                max_seconds = self.ls_time_spin.value() or None
                improved = ls.improve(
                    self.current_schedule,
                    iterations=int(self.improve_runs_spin.value()),
                    max_seconds=max_seconds,
                )
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

            max_seconds = self.ls_time_spin.value() or None
            improved = ls.improve(base_schedule, iterations=total_iters, max_seconds=max_seconds)
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

    def on_export_pdf(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to export")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export group schedules (PDF)",
            "timetable.pdf",
            "PDF document (*.pdf)",
        )
        if not path:
            return

        try:
            self.set_status("Exporting PDF...")
            export_groups_pdf(self.inst, self.current_schedule, path)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Export error", str(e))
            self.set_status("Export error")
            return

        self.set_status(f"Exported to {path}")

    def on_export_reports(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to export")
            return

        path = QFileDialog.getExistingDirectory(
            self,
            "Export CSV reports (choose folder)",
            "",
        )
        if not path:
            return

        try:
            self.set_status("Writing reports...")
            export_summary_reports(self.inst, self.current_schedule, path)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Export error", str(e))
            self.set_status("Export error")
            return

        self.set_status(f"Reports written to {path}")

    def on_export_csv(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to export")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export schedule (CSV)",
            "schedule.csv",
            "CSV files (*.csv)",
        )
        if not path:
            return

        try:
            self.set_status("Exporting CSV...")
            export_schedule_to_csv(self.inst, self.current_schedule, path)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Export error", str(e))
            self.set_status("Export error")
            return

        self.set_status(f"Exported to {path}")

    def on_export_ics(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to export")
            return

        path = QFileDialog.getExistingDirectory(
            self,
            "Export ICS calendars (choose folder)",
            "",
        )
        if not path:
            return

        try:
            self.set_status("Exporting ICS...")
            export_groups_ics_per_id(self.inst, self.current_schedule, path)
            export_staff_ics_per_id(self.inst, self.current_schedule, path)
            export_rooms_ics_per_id(self.inst, self.current_schedule, path)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Export error", str(e))
            self.set_status("Export error")
            return

        self.set_status(f"ICS exported to {path}")

    def on_save_project(self):
        if self.inst is None:
            self.set_status("No instance to save")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save project",
            "project.json",
            "Project (*.json *.pkl)",
        )
        if not path:
            return

        try:
            self.set_status("Saving project...")
            # Ensure locks are persisted
            self.inst.locked_activities = dict(self.locked_activities)
            schedule = self.current_schedule or {}
            write_scenario(path, self.inst, schedule, meta={"source": "ui"})
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Save error", str(e))
            self.set_status("Save error")
            return

        self.set_status(f"Saved to {path}")

    def on_load_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load project",
            "",
            "Project (*.json *.pkl)",
        )
        if not path:
            return

        try:
            self.set_status("Loading project...")
            inst, schedule, _meta = read_scenario(path)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Load error", str(e))
            self.set_status("Load error")
            return

        self.inst = inst
        self.locked_activities = dict(getattr(inst, "locked_activities", {}) or {})
        self.base_schedule = schedule
        self.current_schedule = {a_id: info.copy() for a_id, info in schedule.items()}

        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self.set_status(f"Loaded {path}")

    def on_compare(self):
        if not self.current_schedule:
            self.set_status("No schedule to compare")
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Compare with project",
            "",
            "Project (*.json *.pkl)",
        )
        if not path:
            return

        try:
            inst, schedule, _meta = read_scenario(path)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Compare error", str(e))
            self.set_status("Compare error")
            return

        summary = compare_schedules(self.current_schedule, schedule)
        lines = [
            f"Shared activities: {summary['shared']}",
            f"Missing in other: {len(summary['missing_in_other'])}",
            f"Missing in current: {len(summary['missing_in_base'])}",
            f"Changed time: {summary['changed_time']}",
            f"Changed room: {summary['changed_room']}",
            f"Changed staff: {summary['changed_staff']}",
        ]
        if summary["missing_in_other"] or summary["missing_in_base"]:
            lines.append("Note: schedules are not based on identical activity sets.")
        if inst.weeks != getattr(self.inst, "weeks", []):
            lines.append("Note: compared scenario has different week set.")
        QMessageBox.information(self, "Schedule comparison", "\n".join(lines))
        # Optional export
        try:
            save = QMessageBox.question(
                self,
                "Save comparison report?",
                "Save a comparison report (JSON/CSV)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if save == QMessageBox.StandardButton.Yes:
                out_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "Save comparison report",
                    "comparison.json",
                    "Report (*.json *.csv)",
                )
                if out_path:
                    write_comparison_report(out_path, summary)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.warning(self, "Report error", str(e))
        self.set_status("Comparison complete")

    def on_load_instance(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load instance",
            "",
            "Instance (*.json *.pkl)",
        )
        if not path:
            return

        try:
            self.set_status("Loading instance...")
            inst = read_instance(path)
            normalize_instance_for_spec(inst)
            stamp_instance_time(inst, DEFAULT_DAY_START, DEFAULT_SLOT_MINUTES, DEFAULT_BREAK_MINUTES)
            validate_instance_against_spec(inst)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Load error", str(e))
            self.set_status("Load error")
            return

        self.inst = inst
        self.locked_activities = dict(getattr(inst, "locked_activities", {}) or {})
        self.base_schedule = {}
        self.current_schedule = {}
        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self.set_status(f"Loaded instance {path}")

    def on_load_schedule(self):
        if self.inst is None:
            self.set_status("Load instance first")
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load schedule (CSV)",
            "",
            "CSV files (*.csv)",
        )
        if not path:
            return

        try:
            self.set_status("Loading schedule...")
            schedule = read_schedule_csv(path)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Load error", str(e))
            self.set_status("Load error")
            return

        # Validate and filter out activities that are not in the instance
        filtered = {}
        missing = 0
        invalid = 0
        inst = self.inst
        for a_id, info in schedule.items():
            if a_id not in inst.activities:
                missing += 1
                continue
            act = inst.activities[a_id]
            day = info.get("day")
            slot = int(info.get("slot", -1))
            dur = int(info.get("duration", act.duration))
            staff_id = info.get("staff_id")
            week = int(info.get("week", act.week))
            if day not in inst.days:
                invalid += 1
                continue
            if slot < 0 or slot + dur > inst.slots_per_day:
                invalid += 1
                continue
            if dur not in (1, 2, 3):
                invalid += 1
                continue
            if week != act.week:
                invalid += 1
                continue
            if dur != act.duration:
                invalid += 1
                continue
            if staff_id is not None and int(staff_id) not in inst.staff:
                invalid += 1
                continue
            if act.kind == "LEC" and staff_id is not None and not inst.staff.get(int(staff_id)).is_prof:
                invalid += 1
                continue
            if act.kind != "LEC" and staff_id is not None and inst.staff.get(int(staff_id)).is_prof:
                invalid += 1
                continue
            filtered[a_id] = info

        self.base_schedule = filtered
        self.current_schedule = {a_id: info.copy() for a_id, info in filtered.items()}
        errors = validate_schedule_against_instance(self.inst, self.current_schedule, strict_rooms=True)
        if errors:
            msg = "Schedule violates hard rules:\n" + "\n".join(f"- {e}" for e in errors[:20])
            if len(errors) > 20:
                msg += f"\n... and {len(errors) - 20} more"
            QMessageBox.critical(self, "Invalid schedule", msg)
            self.base_schedule = {}
            self.current_schedule = {}
            self.clear_table()
            self.set_status("Load error")
            return
        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        msg = f"Loaded schedule {path}"
        if missing:
            msg += f" ({missing} activities ignored)"
        if invalid:
            msg += f" ({invalid} invalid rows skipped)"
        self.set_status(msg)

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
            lock = self.locked_activities.get(a_id, {})
            if isinstance(lock, dict):
                lock_flags: List[str] = []
                if "day" in lock and "slot" in lock:
                    lock_flags.append("T")
                if "room_id" in lock:
                    lock_flags.append("R")
                if lock_flags:
                    parts.append(f"LOCK[{''.join(lock_flags)}]")
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
        W_ACTIVE_DAYS = 5
        W_LATE_START = 3
        W_THIN_DAY = 3
        W_STABILITY = 1
        W_SINGLE_SLOT = 6

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
                    first_slot = None
                    for idx, v in enumerate(occ):
                        if v == 1 and prev == 0:
                            blocks += 1
                        if v == 1:
                            load += 1
                            if first_slot is None:
                                first_slot = idx
                        prev = v
                    if blocks > 1:
                        pen += W_STUD_GAPS * (blocks - 1)
                    if load == 1:
                        pen += W_SINGLE_SLOT
                    if load == 2:
                        pen += W_THIN_DAY
                    if first_slot is not None and first_slot >= 2:
                        pen += W_LATE_START

                active_days = sum(day_active[g_id, w, d] for d in days)
                if active_days > 3:
                    pen += W_ACTIVE_DAYS * (active_days - 3)

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

        dlg = EditActivityDialog(self, self.inst, self.current_schedule, act_ids, week, day, slot, locked=self.locked_activities)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        a_id, new_day, new_slot, new_room, new_staff, lock_time, lock_room = dlg.get_values()
        ok, reason = self.check_move(a_id, new_day, new_slot, new_room, new_staff)
        if not ok:
            QMessageBox.warning(self, "Invalid move", reason)
            return

        info = self.current_schedule[a_id]
        info["day"] = new_day
        info["slot"] = new_slot
        info["room_id"] = new_room
        info["staff_id"] = new_staff

        # Persist staff assignment onto the instance (solver convention: prof for LEC, TA for TUT/LAB).
        act = self.inst.activities[a_id]
        if act.kind == "LEC":
            act.prof_id = int(new_staff)
        else:
            act.ta_id = int(new_staff)

        # Update locks (used by re-solve).
        fixed = dict(self.locked_activities.get(a_id, {}))
        if lock_time:
            fixed["day"] = new_day
            fixed["slot"] = int(new_slot)
        else:
            fixed.pop("day", None)
            fixed.pop("slot", None)
        if lock_room:
            fixed["room_id"] = int(new_room)
        else:
            fixed.pop("room_id", None)
        if fixed:
            self.locked_activities[a_id] = fixed
        else:
            self.locked_activities.pop(a_id, None)

        self.update_table()
        self.update_quality_summary()
        self.set_status(f"Edited A{a_id} (locks={len(self.locked_activities)})")

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
        if act.kind == "LEC":
            if not staff.is_prof:
                return False, "Lectures must be taught by a professor."
            if act.course_id not in staff.can_teach_courses:
                return False, "Professor cannot teach this course."
        else:
            if staff.is_prof:
                return False, "Tutorials/labs must be taught by a TA."
            if act.course_id not in staff.can_teach_courses:
                return False, "TA cannot teach this course."
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
        if room.availability is not None:
            for s in range(new_slot, new_slot + dur):
                if (new_day, s) not in room.availability:
                    return False, "Room unavailable at that day/slot."

        if act.kind == "LAB":
            if room.room_type not in ("COMPUTER_LAB", "SPECIALIZED_LAB"):
                return False, "Lab must be in a lab room."
            if act.requires_specialization and act.requires_specialization not in room.specialization_tags:
                return False, "Wrong specialized lab."
        elif act.kind == "LEC":
            if room.room_type != "LECTURE":
                return False, "Lecture must use a lecture room."
        else:  # TUT
            if room.room_type not in ("LECTURE", "TUTORIAL"):
                return False, "Tutorial must use a lecture/tutorial room."

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
    icon_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "app_icon.png"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    win = MainWindow()
    win.resize(1300, 720)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
