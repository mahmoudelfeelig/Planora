from __future__ import annotations

import sys
import os
import uuid
import pickle
import tempfile
import traceback
from typing import Dict, Any, Tuple, List, Set

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
    QHBoxLayout,
    QGridLayout,
    QFormLayout,
    QGroupBox,
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
    QTabWidget,
    QInputDialog,
)

from ui.constants import (
    DEFAULT_DAY_START,
    DEFAULT_SLOT_MINUTES,
    DEFAULT_BREAK_MINUTES,
    DEFAULT_TIME_LIMIT,
    DEFAULT_CP_WORKERS,
)
from ui.dialogs import EditActivityDialog, MoveConflictDialog, ConflictInspectorDialog
from ui.styles import DARK_STYLE
from utils.generator import generate_instance, generate_custom_instance, ROOM_CATEGORY_CAPACITY
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
        self.held_activity_id: int | None = None
        self._cell_activity_map: Dict[Tuple[int, int], List[int]] = {}
        self._undo_stack: List[Dict[str, Any]] = []
        self._redo_stack: List[Dict[str, Any]] = []

        self.proc: QProcess | None = None
        self.tmp_inst_path: str | None = None
        self.tmp_res_path: str | None = None
        self._room_table_internal_change = False

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
                "custom",
            ]
        )

        self.generate_button = QPushButton("Generate")
        self.solve_button = QPushButton("Solve")
        self.resolve_button = QPushButton("Re-solve")
        self.clear_locks_button = QPushButton("Clear Locks")
        self.improve_button = QPushButton("Improve")
        self.undo_button = QPushButton("Undo")
        self.redo_button = QPushButton("Redo")
        self.revert_button = QPushButton("Revert Base")
        self.conflicts_button = QPushButton("Conflicts")

        self.room_mode_combo = QComboBox()
        self.room_mode_combo.addItems(["Strict (CP rooms)", "Fast (Greedy rooms)"])
        self.room_mode_combo.setCurrentIndex(0)

        self.objective_cb = QCheckBox("Use CP objective")
        self.objective_cb.setChecked(True)

        self.time_limit_spin = QSpinBox()
        self.time_limit_spin.setRange(5, 3600)
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
        top_layout.addWidget(self.undo_button, r, c); c += 1
        top_layout.addWidget(self.redo_button, r, c); c += 1
        top_layout.addWidget(self.revert_button, r, c); c += 1
        top_layout.addWidget(self.conflicts_button, r, c); c += 1

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
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(True)
        self.table.horizontalHeader().setVisible(True)
        self.table.setWordWrap(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.workspace_tabs = QTabWidget()
        schedule_tab = QWidget()
        schedule_layout = QVBoxLayout(schedule_tab)
        schedule_layout.addWidget(self.table)
        schedule_layout.addWidget(self.quality_label)
        self.workspace_tabs.addTab(schedule_tab, "Schedule")
        self.workspace_tabs.addTab(self._build_generator_tab(), "Generator")
        self.workspace_tabs.addTab(self._build_constraints_tab(), "Constraints")

        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.addWidget(top_widget)
        main_layout.addWidget(self.workspace_tabs)
        self.setCentralWidget(central)

        self.setStyleSheet(DARK_STYLE)

        self._build_menus()
        self._reset_custom_staff_table()
        self._reset_custom_room_table()
        self._load_constraint_controls_from_instance(None)
        self._refresh_history_buttons()

    def _connect_signals(self):
        self.generate_button.clicked.connect(self.on_generate)
        self.solve_button.clicked.connect(self.on_solve)
        self.resolve_button.clicked.connect(self.on_resolve)
        self.clear_locks_button.clicked.connect(self.on_clear_locks)
        self.improve_button.clicked.connect(self.on_improve)
        self.undo_button.clicked.connect(self.on_undo)
        self.redo_button.clicked.connect(self.on_redo)
        self.revert_button.clicked.connect(self.on_revert_to_base)
        self.conflicts_button.clicked.connect(self.on_show_conflicts)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.custom_reset_staff_btn.clicked.connect(self._reset_custom_staff_table)
        self.custom_reset_rooms_btn.clicked.connect(self._reset_custom_room_table)
        self.custom_room_table.itemChanged.connect(self._on_room_table_item_changed)
        self.apply_constraints_btn.clicked.connect(self.on_apply_constraints_to_instance)
        self.view_type_combo.currentIndexChanged.connect(self.update_entities)
        self.entity_combo.currentIndexChanged.connect(self.update_table)
        self.week_combo.currentIndexChanged.connect(self.update_table)
        self.table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        self.table.customContextMenuRequested.connect(self.on_table_context_menu)

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
        act_undo = QAction("Undo Edit", self)
        act_undo.triggered.connect(self.on_undo)
        act_redo = QAction("Redo Edit", self)
        act_redo.triggered.connect(self.on_redo)
        act_revert = QAction("Revert To Base", self)
        act_revert.triggered.connect(self.on_revert_to_base)
        act_conflicts = QAction("Show Conflicts", self)
        act_conflicts.triggered.connect(self.on_show_conflicts)
        act_load_inst = QAction("Load Instance", self)
        act_load_inst.triggered.connect(self.on_load_instance)
        act_load_sched = QAction("Load Schedule (CSV)", self)
        act_load_sched.triggered.connect(self.on_load_schedule)

        self.project_menu.addAction(act_save)
        self.project_menu.addAction(act_load)
        self.project_menu.addSeparator()
        self.project_menu.addAction(act_compare)
        self.project_menu.addAction(act_undo)
        self.project_menu.addAction(act_redo)
        self.project_menu.addAction(act_revert)
        self.project_menu.addAction(act_conflicts)
        self.project_menu.addSeparator()
        self.project_menu.addAction(act_load_inst)
        self.project_menu.addAction(act_load_sched)

    def _build_generator_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        counts_box = QGroupBox("Scenario Size")
        counts_form = QFormLayout(counts_box)
        self.custom_programs_spin = QSpinBox()
        self.custom_programs_spin.setRange(1, 200)
        self.custom_programs_spin.setValue(20)
        self.custom_groups_per_program_spin = QSpinBox()
        self.custom_groups_per_program_spin.setRange(1, 20)
        self.custom_groups_per_program_spin.setValue(2)
        self.custom_courses_per_program_spin = QSpinBox()
        self.custom_courses_per_program_spin.setRange(1, 20)
        self.custom_courses_per_program_spin.setValue(6)
        counts_form.addRow("Programs", self.custom_programs_spin)
        counts_form.addRow("Groups per program", self.custom_groups_per_program_spin)
        counts_form.addRow("Courses per program", self.custom_courses_per_program_spin)
        layout.addWidget(counts_box)

        staff_box = QGroupBox("Staff Mapping")
        staff_layout = QVBoxLayout(staff_box)
        staff_controls = QHBoxLayout()
        self.custom_num_profs_spin = QSpinBox()
        self.custom_num_profs_spin.setRange(1, 500)
        self.custom_num_profs_spin.setValue(40)
        self.custom_num_tas_spin = QSpinBox()
        self.custom_num_tas_spin.setRange(1, 500)
        self.custom_num_tas_spin.setValue(30)
        self.custom_reset_staff_btn = QPushButton("Reset Staff Rows")
        staff_controls.addWidget(QLabel("Professors"))
        staff_controls.addWidget(self.custom_num_profs_spin)
        staff_controls.addWidget(QLabel("TAs"))
        staff_controls.addWidget(self.custom_num_tas_spin)
        staff_controls.addWidget(self.custom_reset_staff_btn)
        staff_controls.addStretch(1)
        staff_layout.addLayout(staff_controls)
        self.custom_staff_table = QTableWidget(0, 4)
        self.custom_staff_table.setHorizontalHeaderLabels(
            ["Staff", "Role", "Course IDs (csv)", "Available Days (csv)"]
        )
        self.custom_staff_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.custom_staff_table.verticalHeader().setVisible(False)
        staff_layout.addWidget(self.custom_staff_table)
        layout.addWidget(staff_box)

        room_box = QGroupBox("Room Definitions")
        room_layout = QVBoxLayout(room_box)
        room_controls = QHBoxLayout()
        self.custom_room_count_spin = QSpinBox()
        self.custom_room_count_spin.setRange(1, 500)
        self.custom_room_count_spin.setValue(30)
        self.custom_reset_rooms_btn = QPushButton("Reset Room Rows")
        room_controls.addWidget(QLabel("Total rooms"))
        room_controls.addWidget(self.custom_room_count_spin)
        room_controls.addWidget(self.custom_reset_rooms_btn)
        room_controls.addWidget(QLabel("Category defaults: SMALL/MEDIUM/BIG"))
        room_controls.addStretch(1)
        room_layout.addLayout(room_controls)
        self.custom_room_table = QTableWidget(0, 5)
        self.custom_room_table.setHorizontalHeaderLabels(
            ["Name", "Type", "Category", "Capacity", "Tags (csv for specialized labs)"]
        )
        self.custom_room_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.custom_room_table.verticalHeader().setVisible(False)
        room_layout.addWidget(self.custom_room_table)
        layout.addWidget(room_box)

        hint = QLabel(
            "Use mode 'custom' to generate from these tables.\n"
            "Room category and capacity are interchangeable: either can drive the other."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return tab

    def _build_constraints_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        hard_box = QGroupBox("Hard Constraints")
        hard_layout = QVBoxLayout(hard_box)
        self.hard_week1_cb = QCheckBox("Week 1 is lectures-only")
        self.hard_block_prof_cb = QCheckBox("Enforce block professor rules")
        self.hard_staff_daily_cb = QCheckBox("Enforce staff daily caps")
        self.hard_staff_weekly_cb = QCheckBox("Enforce staff weekly caps")
        self.hard_room_availability_cb = QCheckBox("Enforce room availability")
        hard_layout.addWidget(self.hard_week1_cb)
        hard_layout.addWidget(self.hard_block_prof_cb)
        hard_layout.addWidget(self.hard_staff_daily_cb)
        hard_layout.addWidget(self.hard_staff_weekly_cb)
        hard_layout.addWidget(self.hard_room_availability_cb)
        layout.addWidget(hard_box)

        soft_box = QGroupBox("Soft Constraint Weights")
        soft_form = QFormLayout(soft_box)
        self.soft_weight_spins: Dict[str, QSpinBox] = {}
        soft_defs = [
            ("stud_free_days", "Student free days", 10),
            ("stud_free_mf", "Student Mon-Fri free days", 5),
            ("stud_gaps", "Student gaps", 5),
            ("staff_free_day", "Staff free day", 6),
            ("active_days", "Active-day minimization", 5),
            ("late_start", "Late start", 3),
            ("thin_day", "Thin day", 3),
            ("single_slot", "Single-slot day", 6),
            ("stability", "Week-to-week stability", 1),
            ("room_consistency", "Room consistency", 1),
        ]
        for key, label, default in soft_defs:
            spin = QSpinBox()
            spin.setRange(0, 200)
            spin.setValue(default)
            self.soft_weight_spins[key] = spin
            soft_form.addRow(label, spin)
        layout.addWidget(soft_box)

        self.apply_constraints_btn = QPushButton("Apply Constraints To Current Instance")
        layout.addWidget(self.apply_constraints_btn)
        layout.addStretch(1)
        return tab

    @staticmethod
    def _infer_room_category(capacity: int) -> str:
        if capacity <= 80:
            return "SMALL"
        if capacity <= 180:
            return "MEDIUM"
        return "BIG"

    def _reset_custom_staff_table(self) -> None:
        rows = int(self.custom_num_profs_spin.value()) + int(self.custom_num_tas_spin.value())
        self.custom_staff_table.blockSignals(True)
        self.custom_staff_table.setRowCount(rows)
        row = 0
        for idx in range(1, int(self.custom_num_profs_spin.value()) + 1):
            name_item = QTableWidgetItem(f"Prof-{idx}")
            role_item = QTableWidgetItem("PROF")
            role_item.setFlags(role_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.custom_staff_table.setItem(row, 0, name_item)
            self.custom_staff_table.setItem(row, 1, role_item)
            self.custom_staff_table.setItem(row, 2, QTableWidgetItem(""))
            self.custom_staff_table.setItem(row, 3, QTableWidgetItem(",".join(self.inst.days if self.inst else ["MON", "TUE", "WED", "THU", "FRI", "SAT"])))
            row += 1
        for idx in range(1, int(self.custom_num_tas_spin.value()) + 1):
            name_item = QTableWidgetItem(f"TA-{idx}")
            role_item = QTableWidgetItem("TA")
            role_item.setFlags(role_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.custom_staff_table.setItem(row, 0, name_item)
            self.custom_staff_table.setItem(row, 1, role_item)
            self.custom_staff_table.setItem(row, 2, QTableWidgetItem(""))
            self.custom_staff_table.setItem(row, 3, QTableWidgetItem(",".join(self.inst.days if self.inst else ["MON", "TUE", "WED", "THU", "FRI", "SAT"])))
            row += 1
        self.custom_staff_table.blockSignals(False)

    def _reset_custom_room_table(self) -> None:
        self.custom_room_table.blockSignals(True)
        self.custom_room_table.setRowCount(int(self.custom_room_count_spin.value()))
        defaults = ["LECTURE", "LECTURE", "TUTORIAL", "COMPUTER_LAB", "SPECIALIZED_LAB"]
        for row in range(self.custom_room_table.rowCount()):
            rtype = defaults[row % len(defaults)]
            cat = "MEDIUM"
            cap = ROOM_CATEGORY_CAPACITY[cat]
            self.custom_room_table.setItem(row, 0, QTableWidgetItem(f"{rtype.title()}-{row + 1}"))
            self.custom_room_table.setItem(row, 1, QTableWidgetItem(rtype))
            self.custom_room_table.setItem(row, 2, QTableWidgetItem(cat))
            self.custom_room_table.setItem(row, 3, QTableWidgetItem(str(cap)))
            self.custom_room_table.setItem(row, 4, QTableWidgetItem("" if rtype != "SPECIALIZED_LAB" else "LAB1"))
        self.custom_room_table.blockSignals(False)

    def _on_room_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._room_table_internal_change:
            return
        if item is None:
            return
        row = item.row()
        col = item.column()
        cat_item = self.custom_room_table.item(row, 2)
        cap_item = self.custom_room_table.item(row, 3)
        if cat_item is None or cap_item is None:
            return
        self._room_table_internal_change = True
        try:
            if col == 2:
                cat = str(cat_item.text()).strip().upper()
                if cat in ROOM_CATEGORY_CAPACITY:
                    cap_item.setText(str(ROOM_CATEGORY_CAPACITY[cat]))
            elif col == 3:
                try:
                    cap = max(1, int(str(cap_item.text()).strip()))
                except Exception:
                    cap = ROOM_CATEGORY_CAPACITY["MEDIUM"]
                    cap_item.setText(str(cap))
                cat_item.setText(self._infer_room_category(cap))
        finally:
            self._room_table_internal_change = False

    @staticmethod
    def _parse_csv_ints(raw: str) -> List[int]:
        out: List[int] = []
        for token in str(raw).split(","):
            token = token.strip()
            if not token:
                continue
            try:
                out.append(int(token))
            except Exception:
                continue
        return out

    @staticmethod
    def _parse_csv_days(raw: str) -> List[str]:
        valid = {"MON", "TUE", "WED", "THU", "FRI", "SAT"}
        out: List[str] = []
        for token in str(raw).split(","):
            day = token.strip().upper()
            if day in valid:
                out.append(day)
        return out

    def _collect_custom_generation_config(self) -> Dict[str, Any]:
        prof_course_map: Dict[int, List[int]] = {}
        ta_course_map: Dict[int, List[int]] = {}
        prof_days: Dict[int, List[str]] = {}
        ta_days: Dict[int, List[str]] = {}
        prof_idx = 0
        ta_idx = 0
        for row in range(self.custom_staff_table.rowCount()):
            role_item = self.custom_staff_table.item(row, 1)
            courses_item = self.custom_staff_table.item(row, 2)
            days_item = self.custom_staff_table.item(row, 3)
            role = str(role_item.text()).strip().upper() if role_item else ""
            courses = self._parse_csv_ints(courses_item.text() if courses_item else "")
            days = self._parse_csv_days(days_item.text() if days_item else "")
            if role == "PROF":
                prof_idx += 1
                if courses:
                    prof_course_map[prof_idx] = courses
                prof_days[prof_idx] = days
            elif role == "TA":
                ta_idx += 1
                if courses:
                    ta_course_map[ta_idx] = courses
                ta_days[ta_idx] = days

        room_specs: List[Dict[str, Any]] = []
        for row in range(self.custom_room_table.rowCount()):
            name_item = self.custom_room_table.item(row, 0)
            type_item = self.custom_room_table.item(row, 1)
            cat_item = self.custom_room_table.item(row, 2)
            cap_item = self.custom_room_table.item(row, 3)
            tags_item = self.custom_room_table.item(row, 4)
            name = str(name_item.text()).strip() if name_item else f"Room-{row + 1}"
            room_type = str(type_item.text()).strip().upper() if type_item else "LECTURE"
            category = str(cat_item.text()).strip().upper() if cat_item else "MEDIUM"
            try:
                capacity = max(1, int(str(cap_item.text()).strip())) if cap_item else ROOM_CATEGORY_CAPACITY.get(category, 150)
            except Exception:
                capacity = ROOM_CATEGORY_CAPACITY.get(category, 150)
            tags = [t.strip().upper() for t in str(tags_item.text()).split(",") if t.strip()] if tags_item else []
            room_specs.append(
                {
                    "name": name,
                    "room_type": room_type,
                    "category": category,
                    "capacity": capacity,
                    "tags": tags,
                }
            )

        return {
            "num_programs": int(self.custom_programs_spin.value()),
            "groups_per_program": int(self.custom_groups_per_program_spin.value()),
            "courses_per_program": int(self.custom_courses_per_program_spin.value()),
            "num_professors": int(self.custom_num_profs_spin.value()),
            "num_tas": int(self.custom_num_tas_spin.value()),
            "professor_course_map": prof_course_map,
            "ta_course_map": ta_course_map,
            "professor_days": prof_days,
            "ta_days": ta_days,
            "room_specs": room_specs,
            "seed": 42,
        }

    def _collect_constraint_settings(self) -> tuple[Dict[str, bool], Dict[str, int]]:
        hard = {
            "week1_lectures_only": self.hard_week1_cb.isChecked(),
            "enforce_block_professor_rules": self.hard_block_prof_cb.isChecked(),
            "enforce_staff_daily_caps": self.hard_staff_daily_cb.isChecked(),
            "enforce_staff_weekly_caps": self.hard_staff_weekly_cb.isChecked(),
            "enforce_room_availability": self.hard_room_availability_cb.isChecked(),
        }
        soft = {k: int(spin.value()) for k, spin in self.soft_weight_spins.items()}
        return hard, soft

    def _apply_constraint_settings(self, inst: Instance | None) -> None:
        if inst is None:
            return
        hard, soft = self._collect_constraint_settings()
        inst.hard_constraints = hard
        inst.soft_weights = soft

    def _load_constraint_controls_from_instance(self, inst: Instance | None) -> None:
        hard_defaults = {
            "week1_lectures_only": True,
            "enforce_block_professor_rules": True,
            "enforce_staff_daily_caps": True,
            "enforce_staff_weekly_caps": True,
            "enforce_room_availability": True,
        }
        soft_defaults = {
            "stud_free_days": 10,
            "stud_free_mf": 5,
            "stud_gaps": 5,
            "staff_free_day": 6,
            "active_days": 5,
            "late_start": 3,
            "thin_day": 3,
            "single_slot": 6,
            "stability": 1,
            "room_consistency": 1,
        }
        hard = hard_defaults
        soft = soft_defaults
        if inst is not None:
            raw_hard = getattr(inst, "hard_constraints", {}) or {}
            if isinstance(raw_hard, dict):
                hard = {k: bool(raw_hard.get(k, v)) for k, v in hard_defaults.items()}
            raw_soft = getattr(inst, "soft_weights", {}) or {}
            if isinstance(raw_soft, dict):
                soft = dict(soft_defaults)
                for k in soft.keys():
                    if k in raw_soft:
                        try:
                            soft[k] = int(raw_soft[k])
                        except Exception:
                            pass
        self.hard_week1_cb.setChecked(hard["week1_lectures_only"])
        self.hard_block_prof_cb.setChecked(hard["enforce_block_professor_rules"])
        self.hard_staff_daily_cb.setChecked(hard["enforce_staff_daily_caps"])
        self.hard_staff_weekly_cb.setChecked(hard["enforce_staff_weekly_caps"])
        self.hard_room_availability_cb.setChecked(hard["enforce_room_availability"])
        for key, spin in self.soft_weight_spins.items():
            spin.setValue(int(soft.get(key, spin.value())))

    def on_apply_constraints_to_instance(self) -> None:
        if self.inst is None:
            self.set_status("Generate or load an instance first")
            return
        self._apply_constraint_settings(self.inst)
        self.update_quality_summary()
        self.set_status("Constraint settings applied to current instance")

    def _on_mode_changed(self) -> None:
        if self.mode_combo.currentText() == "custom":
            self.workspace_tabs.setCurrentIndex(1)

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
            self.undo_button,
            self.redo_button,
            self.revert_button,
            self.conflicts_button,
        ]:
            btn.setEnabled(enable)
        self.improve_runs_spin.setEnabled(enable)
        self.ls_time_spin.setEnabled(enable)
        self.room_mode_combo.setEnabled(enable)
        self.objective_cb.setEnabled(enable)
        self.time_limit_spin.setEnabled(enable)
        self.workers_spin.setEnabled(enable)
        self.workspace_tabs.setEnabled(enable)
        self.custom_reset_staff_btn.setEnabled(enable)
        self.custom_reset_rooms_btn.setEnabled(enable)
        self.apply_constraints_btn.setEnabled(enable)
        if enable:
            self._refresh_history_buttons()

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
        self._cell_activity_map = {}
        self.quality_label.setText("")

    def _snapshot_state(self) -> Dict[str, Any]:
        return {
            "current_schedule": self._clone_schedule(),
            "locked_activities": {
                int(a_id): dict(lock) for a_id, lock in self.locked_activities.items()
            },
            "held_activity_id": self.held_activity_id,
        }

    def _restore_state(self, state: Dict[str, Any], status: str) -> None:
        self.current_schedule = {
            int(a_id): info.copy()
            for a_id, info in (state.get("current_schedule") or {}).items()
        }
        self.locked_activities = {
            int(a_id): dict(lock)
            for a_id, lock in (state.get("locked_activities") or {}).items()
        }
        held = state.get("held_activity_id")
        self.held_activity_id = int(held) if held is not None else None
        self._sync_instance_staff_from_schedule(self.current_schedule)
        self._sync_locks_to_instance()
        self.update_table()
        self.update_quality_summary()
        self.set_status(status)

    def _reset_history(self) -> None:
        self._undo_stack = []
        self._redo_stack = []
        self._refresh_history_buttons()

    def _push_undo_state(self) -> None:
        if self.inst is None:
            return
        self._undo_stack.append(self._snapshot_state())
        if len(self._undo_stack) > 120:
            self._undo_stack.pop(0)
        self._redo_stack = []
        self._refresh_history_buttons()

    def _refresh_history_buttons(self) -> None:
        self.undo_button.setEnabled(bool(self._undo_stack))
        self.redo_button.setEnabled(bool(self._redo_stack))
        self.revert_button.setEnabled(bool(self.base_schedule))
        self.conflicts_button.setEnabled(bool(self.current_schedule))

    def _sync_locks_to_instance(self) -> None:
        if self.inst is None:
            return
        self.inst.locked_activities = {
            int(a_id): dict(lock) for a_id, lock in self.locked_activities.items()
        }

    def _collect_conflict_errors(self) -> List[str]:
        if self.inst is None or not self.current_schedule:
            return []
        try:
            return validate_schedule_against_instance(
                self.inst, self.current_schedule, strict_rooms=False
            )
        except Exception:
            return []

    def _toggle_activity_lock(self, a_id: int, *, time_lock: bool) -> None:
        if a_id not in self.current_schedule:
            return
        self._push_undo_state()
        info = self.current_schedule[a_id]
        fixed = dict(self.locked_activities.get(a_id, {}))
        if time_lock:
            if "day" in fixed and "slot" in fixed:
                fixed.pop("day", None)
                fixed.pop("slot", None)
            else:
                fixed["day"] = str(info["day"])
                fixed["slot"] = int(info["slot"])
        else:
            if "room_id" in fixed:
                fixed.pop("room_id", None)
            else:
                fixed["room_id"] = int(info["room_id"])
        if fixed:
            self.locked_activities[a_id] = fixed
        else:
            self.locked_activities.pop(a_id, None)
        self._sync_locks_to_instance()
        self.update_table()
        self.update_quality_summary()
        lock_name = "time" if time_lock else "room"
        self.set_status(f"Toggled {lock_name} lock for A{a_id}")
        self._refresh_history_buttons()

    def _focus_activity(self, a_id: int, *, hold: bool = False) -> None:
        if self.inst is None or a_id not in self.current_schedule:
            return
        info = self.current_schedule[a_id]
        week = int(info["week"])
        week_idx = self.week_combo.findData(week)
        if week_idx >= 0:
            self.week_combo.setCurrentIndex(week_idx)

        # Prefer group view because it is usually the most interpretable.
        self.view_type_combo.setCurrentText("Group")
        group_ids = info.get("group_ids") or []
        if group_ids:
            ent_idx = self.entity_combo.findData(int(group_ids[0]))
            if ent_idx >= 0:
                self.entity_combo.setCurrentIndex(ent_idx)
        self.update_table()

        day = str(info["day"])
        if day in self.inst.days:
            row = self.inst.days.index(day)
            col = int(info["slot"])
            if 0 <= row < self.table.rowCount() and 0 <= col < self.table.columnCount():
                self.table.setCurrentCell(row, col)
        if hold:
            self._set_held_activity(a_id)
        else:
            self.set_status(f"Focused {self._activity_title(a_id)}")

    def _activity_title(
        self,
        a_id: int,
        schedule: Dict[int, Dict[str, Any]] | None = None,
    ) -> str:
        inst = self.inst
        if inst is None:
            return f"A{a_id}"
        info = None
        if schedule is not None:
            info = schedule.get(a_id)
        elif self.current_schedule:
            info = self.current_schedule.get(a_id)
        course_code = ""
        if info is not None:
            course = inst.courses.get(int(info["course_id"]))
            if course is not None:
                course_code = f" {course.code}"
            return f"A{a_id}{course_code} ({info['day']} S{int(info['slot']) + 1})"
        return f"A{a_id}"

    def _clone_schedule(
        self, schedule: Dict[int, Dict[str, Any]] | None = None
    ) -> Dict[int, Dict[str, Any]]:
        source = self.current_schedule if schedule is None else schedule
        return {a_id: info.copy() for a_id, info in source.items()}

    def _sync_instance_staff_from_schedule(
        self, schedule: Dict[int, Dict[str, Any]]
    ) -> None:
        if self.inst is None:
            return
        for a_id, info in schedule.items():
            act = self.inst.activities.get(a_id)
            if act is None:
                continue
            try:
                sid = int(info["staff_id"])
            except Exception:
                continue
            if act.kind == "LEC":
                act.prof_id = sid
            else:
                act.ta_id = sid

    def _touch_time_lock_if_present(self, a_id: int, day: str, slot: int) -> None:
        fixed = self.locked_activities.get(int(a_id))
        if not isinstance(fixed, dict):
            return
        if "day" in fixed and "slot" in fixed:
            fixed["day"] = str(day)
            fixed["slot"] = int(slot)
            self.locked_activities[int(a_id)] = fixed

    def _current_week(self) -> int | None:
        week_data = self.week_combo.currentData()
        if week_data is None:
            return None
        return int(week_data)

    def _cell_activity_ids_for_view(self, day: str, slot: int, week: int) -> List[int]:
        if self.inst is None or not self.current_schedule:
            return []
        data = self.entity_combo.currentData()
        if data is None:
            return []
        entity_id = int(data)
        view_type = self.view_type_combo.currentText()
        act_ids: List[int] = []
        for a_id, info in self.current_schedule.items():
            if int(info["week"]) != int(week):
                continue
            if str(info["day"]) != str(day):
                continue
            s0 = int(info["slot"])
            dur = int(info["duration"])
            if slot < s0 or slot >= s0 + dur:
                continue
            if view_type == "Group" and entity_id not in info["group_ids"]:
                continue
            if view_type == "Staff" and entity_id != int(info["staff_id"]):
                continue
            if view_type == "Room" and entity_id != int(info["room_id"]):
                continue
            act_ids.append(int(a_id))
        return act_ids

    def _choose_activity_from_ids(self, act_ids: List[int], title: str) -> int | None:
        if not act_ids:
            return None
        if len(act_ids) == 1:
            return int(act_ids[0])
        labels = [self._activity_title(a_id) for a_id in act_ids]
        choice, ok = QInputDialog.getItem(
            self,
            title,
            "Activity:",
            labels,
            0,
            False,
        )
        if not ok:
            return None
        idx = labels.index(choice)
        return int(act_ids[idx])

    def _set_held_activity(self, a_id: int) -> None:
        if a_id not in self.current_schedule:
            return
        self.held_activity_id = int(a_id)
        held_week = int(self.current_schedule[a_id]["week"])
        idx = self.week_combo.findData(held_week)
        if idx >= 0:
            self.week_combo.setCurrentIndex(idx)
        self.update_table()
        self.set_status(
            f"Holding {self._activity_title(a_id)}. Right-click a target cell to move/swap."
        )

    def _clear_held_activity(self) -> None:
        if self.held_activity_id is None:
            return
        held = self.held_activity_id
        self.held_activity_id = None
        self.update_table()
        self.set_status(f"Released held activity A{held}")

    def _collect_held_target_map(
        self,
        week: int,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
    ) -> Dict[Tuple[str, int], bool]:
        inst = self.inst
        if inst is None or self.held_activity_id is None:
            return {}
        schedule = self.current_schedule if schedule_override is None else schedule_override
        a_id = int(self.held_activity_id)
        info = schedule.get(a_id)
        if info is None or int(info["week"]) != int(week):
            return {}
        room_id = int(info["room_id"])
        staff_id = int(info["staff_id"])
        target_map: Dict[Tuple[str, int], bool] = {}
        for day in inst.days:
            for slot in range(inst.slots_per_day):
                ok, _ = self.check_move(
                    a_id,
                    str(day),
                    int(slot),
                    room_id,
                    staff_id,
                    schedule_override=schedule,
                )
                target_map[(str(day), int(slot))] = bool(ok)
        return target_map

    def _find_move_conflicts(
        self,
        a_id: int,
        new_day: str,
        new_slot: int,
        new_room_id: int,
        new_staff_id: int,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
    ) -> List[Dict[str, Any]]:
        schedule = self.current_schedule if schedule_override is None else schedule_override
        info = schedule.get(a_id)
        if info is None:
            return []
        week = int(info["week"])
        dur = int(info["duration"])
        groups = set(int(g) for g in info["group_ids"])
        target_slots = set(range(int(new_slot), int(new_slot) + dur))
        conflicts: List[Dict[str, Any]] = []
        for b_id, other in schedule.items():
            if int(b_id) == int(a_id):
                continue
            if int(other["week"]) != week or str(other["day"]) != str(new_day):
                continue
            other_slots = set(
                range(int(other["slot"]), int(other["slot"]) + int(other["duration"]))
            )
            if not (target_slots & other_slots):
                continue
            reasons: List[str] = []
            if int(other["staff_id"]) == int(new_staff_id):
                reasons.append("staff")
            if int(other["room_id"]) == int(new_room_id):
                reasons.append("room")
            if groups & set(int(g) for g in other["group_ids"]):
                reasons.append("group")
            if reasons:
                conflicts.append(
                    {
                        "activity_id": int(b_id),
                        "reasons": reasons,
                    }
                )
        conflicts.sort(key=lambda item: int(item["activity_id"]))
        return conflicts

    def _find_relocation_slots(
        self,
        a_id: int,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
        *,
        limit: int = 20,
        exclude_starts: Set[Tuple[str, int]] | None = None,
    ) -> List[Tuple[str, int]]:
        inst = self.inst
        if inst is None:
            return []
        schedule = self.current_schedule if schedule_override is None else schedule_override
        info = schedule.get(int(a_id))
        if info is None:
            return []
        room_id = int(info["room_id"])
        staff_id = int(info["staff_id"])
        options: List[Tuple[str, int]] = []
        excluded = set(exclude_starts or set())
        for day in inst.days:
            for slot in range(inst.slots_per_day):
                key = (str(day), int(slot))
                if key in excluded:
                    continue
                ok, _ = self.check_move(
                    int(a_id),
                    str(day),
                    int(slot),
                    room_id,
                    staff_id,
                    schedule_override=schedule,
                )
                if ok:
                    options.append(key)
                    if len(options) >= int(limit):
                        return options
        return options

    def _commit_schedule(self, schedule: Dict[int, Dict[str, Any]], status: str) -> None:
        self.current_schedule = {a_id: info.copy() for a_id, info in schedule.items()}
        self._sync_instance_staff_from_schedule(self.current_schedule)
        self._sync_locks_to_instance()
        self.update_table()
        self.update_quality_summary()
        self.set_status(status)
        self._refresh_history_buttons()

    def _attempt_swap_timeslots(self, a_id: int, b_id: int) -> Tuple[bool, str]:
        if a_id not in self.current_schedule or b_id not in self.current_schedule:
            return False, "Activity not found in schedule."
        schedule = self._clone_schedule()
        a = schedule[a_id]
        b = schedule[b_id]
        if int(a["week"]) != int(b["week"]):
            return False, "Cross-week swap is not supported."
        a_day, a_slot = str(a["day"]), int(a["slot"])
        b_day, b_slot = str(b["day"]), int(b["slot"])
        a["day"], a["slot"] = b_day, b_slot
        b["day"], b["slot"] = a_day, a_slot

        ok_a, reason_a = self.check_move(
            int(a_id),
            str(a["day"]),
            int(a["slot"]),
            int(a["room_id"]),
            int(a["staff_id"]),
            schedule_override=schedule,
        )
        if not ok_a:
            return False, f"Swap invalid for A{a_id}: {reason_a}"
        ok_b, reason_b = self.check_move(
            int(b_id),
            str(b["day"]),
            int(b["slot"]),
            int(b["room_id"]),
            int(b["staff_id"]),
            schedule_override=schedule,
        )
        if not ok_b:
            return False, f"Swap invalid for A{b_id}: {reason_b}"
        errors = validate_schedule_against_instance(self.inst, schedule, strict_rooms=False)
        if errors:
            return False, f"Swap leaves {len(errors)} hard conflicts."

        self._push_undo_state()
        self._touch_time_lock_if_present(a_id, str(a["day"]), int(a["slot"]))
        self._touch_time_lock_if_present(b_id, str(b["day"]), int(b["slot"]))
        self._commit_schedule(
            schedule,
            f"Swapped {self._activity_title(a_id, schedule)} and {self._activity_title(b_id, schedule)}",
        )
        return True, ""

    def _attempt_relocate_conflict(
        self,
        held_id: int,
        conflict_id: int,
        held_day: str,
        held_slot: int,
        conflict_day: str,
        conflict_slot: int,
    ) -> Tuple[bool, str]:
        if held_id not in self.current_schedule or conflict_id not in self.current_schedule:
            return False, "Activity not found in schedule."
        schedule = self._clone_schedule()
        schedule[held_id]["day"] = str(held_day)
        schedule[held_id]["slot"] = int(held_slot)
        schedule[conflict_id]["day"] = str(conflict_day)
        schedule[conflict_id]["slot"] = int(conflict_slot)

        ok_held, reason_held = self.check_move(
            held_id,
            str(schedule[held_id]["day"]),
            int(schedule[held_id]["slot"]),
            int(schedule[held_id]["room_id"]),
            int(schedule[held_id]["staff_id"]),
            schedule_override=schedule,
        )
        if not ok_held:
            return False, f"Held move still invalid: {reason_held}"
        ok_conflict, reason_conflict = self.check_move(
            conflict_id,
            str(schedule[conflict_id]["day"]),
            int(schedule[conflict_id]["slot"]),
            int(schedule[conflict_id]["room_id"]),
            int(schedule[conflict_id]["staff_id"]),
            schedule_override=schedule,
        )
        if not ok_conflict:
            return False, f"Conflict relocation invalid: {reason_conflict}"
        errors = validate_schedule_against_instance(self.inst, schedule, strict_rooms=False)
        if errors:
            return False, f"Plan leaves {len(errors)} hard conflicts."

        self._push_undo_state()
        self._touch_time_lock_if_present(held_id, str(held_day), int(held_slot))
        self._touch_time_lock_if_present(
            conflict_id, str(conflict_day), int(conflict_slot)
        )
        self._commit_schedule(
            schedule,
            f"Moved {self._activity_title(held_id, schedule)} and relocated {self._activity_title(conflict_id, schedule)}",
        )
        return True, ""

    def _attempt_move_held_to(self, target_day: str, target_slot: int) -> None:
        if self.inst is None or self.held_activity_id is None:
            return
        held_id = int(self.held_activity_id)
        if held_id not in self.current_schedule:
            self._clear_held_activity()
            return
        info = self.current_schedule[held_id]
        room_id = int(info["room_id"])
        staff_id = int(info["staff_id"])
        ok, reason = self.check_move(
            held_id,
            str(target_day),
            int(target_slot),
            room_id,
            staff_id,
        )
        if ok:
            schedule = self._clone_schedule()
            schedule[held_id]["day"] = str(target_day)
            schedule[held_id]["slot"] = int(target_slot)
            self._push_undo_state()
            self._touch_time_lock_if_present(held_id, str(target_day), int(target_slot))
            self._commit_schedule(
                schedule,
                f"Moved {self._activity_title(held_id, schedule)}",
            )
            return

        conflicts = self._find_move_conflicts(
            held_id, str(target_day), int(target_slot), room_id, staff_id
        )
        if not conflicts:
            QMessageBox.warning(self, "Move blocked", reason)
            return

        schedule_with_held = self._clone_schedule()
        schedule_with_held[held_id]["day"] = str(target_day)
        schedule_with_held[held_id]["slot"] = int(target_slot)
        relocation_options: Dict[int, List[Tuple[str, int]]] = {}
        for conflict in conflicts:
            b_id = int(conflict["activity_id"])
            current_b = self.current_schedule[b_id]
            relocation_options[b_id] = self._find_relocation_slots(
                b_id,
                schedule_override=schedule_with_held,
                exclude_starts={
                    (str(current_b["day"]), int(current_b["slot"])),
                    (str(target_day), int(target_slot)),
                },
            )

        dlg = MoveConflictDialog(
            self,
            self.inst,
            self.current_schedule,
            held_id,
            str(target_day),
            int(target_slot),
            conflicts,
            relocation_options,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        decision = dlg.get_decision()
        if not decision:
            return
        kind = str(decision[0])
        if kind == "swap":
            b_id = int(decision[1])
            ok_swap, reason_swap = self._attempt_swap_timeslots(held_id, b_id)
            if not ok_swap:
                QMessageBox.warning(self, "Swap blocked", reason_swap)
        elif kind == "relocate":
            b_id = int(decision[1])
            b_day = str(decision[2])
            b_slot = int(decision[3])
            ok_move, reason_move = self._attempt_relocate_conflict(
                held_id,
                b_id,
                str(target_day),
                int(target_slot),
                b_day,
                b_slot,
            )
            if not ok_move:
                QMessageBox.warning(self, "Plan blocked", reason_move)

    def on_table_context_menu(self, pos) -> None:
        if self.inst is None or not self.current_schedule:
            return
        item = self.table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        col = item.column()
        if row < 0 or col < 0:
            return
        week = self._current_week()
        if week is None:
            return
        day = self.inst.days[row]
        act_ids = list(self._cell_activity_map.get((row, col), []))

        menu = QMenu(self.table)
        act_hold = None
        act_edit = None
        act_focus = None
        act_toggle_time_lock = None
        act_toggle_room_lock = None
        act_swap_here = None
        if act_ids:
            act_hold = menu.addAction("Hold activity...")
            act_focus = menu.addAction("Focus activity...")
            act_edit = menu.addAction("Edit activity...")
            act_toggle_time_lock = menu.addAction("Toggle time lock...")
            act_toggle_room_lock = menu.addAction("Toggle room lock...")
        act_move_held = None
        act_show_targets = None
        act_clear_held = None
        if self.held_activity_id is not None:
            menu.addSeparator()
            act_move_held = menu.addAction("Move held activity here")
            act_show_targets = menu.addAction("Show held move targets")
            if act_ids and int(self.held_activity_id) not in act_ids:
                act_swap_here = menu.addAction("Swap held with activity here...")
            act_clear_held = menu.addAction("Release held activity")
        menu.addSeparator()
        act_show_conflicts = menu.addAction("Open conflict inspector")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_hold:
            a_id = self._choose_activity_from_ids(act_ids, "Hold activity")
            if a_id is not None:
                self._set_held_activity(a_id)
            return
        if chosen == act_focus:
            a_id = self._choose_activity_from_ids(act_ids, "Focus activity")
            if a_id is not None:
                self._focus_activity(a_id, hold=False)
            return
        if chosen == act_edit:
            self.on_cell_double_clicked(row, col)
            return
        if chosen == act_toggle_time_lock:
            a_id = self._choose_activity_from_ids(act_ids, "Toggle time lock")
            if a_id is not None:
                self._toggle_activity_lock(a_id, time_lock=True)
            return
        if chosen == act_toggle_room_lock:
            a_id = self._choose_activity_from_ids(act_ids, "Toggle room lock")
            if a_id is not None:
                self._toggle_activity_lock(a_id, time_lock=False)
            return
        if chosen == act_move_held:
            self._attempt_move_held_to(str(day), int(col))
            return
        if chosen == act_swap_here:
            other_ids = [a for a in act_ids if a != int(self.held_activity_id)]
            b_id = self._choose_activity_from_ids(other_ids, "Swap with held activity")
            if b_id is not None and self.held_activity_id is not None:
                ok_swap, reason_swap = self._attempt_swap_timeslots(
                    int(self.held_activity_id), int(b_id)
                )
                if not ok_swap:
                    QMessageBox.warning(self, "Swap blocked", reason_swap)
            return
        if chosen == act_show_targets:
            if self.held_activity_id is None:
                return
            target_map = self._collect_held_target_map(week)
            valid_targets = [
                f"{d} S{s + 1}"
                for d in self.inst.days
                for s in range(self.inst.slots_per_day)
                if target_map.get((d, s), False)
            ]
            if not valid_targets:
                QMessageBox.information(
                    self,
                    "Held activity targets",
                    "No valid target slots for the held activity under current hard constraints.",
                )
            else:
                QMessageBox.information(
                    self,
                    "Held activity targets",
                    "Valid slots:\n" + "\n".join(valid_targets),
                )
            return
        if chosen == act_clear_held:
            self._clear_held_activity()
            return
        if chosen == act_show_conflicts:
            self.on_show_conflicts()
            return

    def _format_solver_attempts(self, res: Dict[str, Any]) -> list[str]:
        meta = res.get("meta")
        if not isinstance(meta, dict):
            return []
        attempts = meta.get("attempts")
        if not isinstance(attempts, list):
            return []
        lines: list[str] = []
        for i, attempt in enumerate(attempts, start=1):
            if not isinstance(attempt, dict):
                continue
            mode = attempt.get("room_mode", "?")
            objective = "on" if attempt.get("use_objective", False) else "off"
            limit = attempt.get("time_limit_seconds")
            limit_txt = "none" if limit in (None, "") else str(limit)
            raw_status = attempt.get("status", "?")
            lines.append(
                f"Attempt {i}: mode={mode}, objective={objective}, "
                f"limit={limit_txt}s, raw_status={raw_status}"
            )
        return lines

    def _build_no_feasible_message(self, res: Dict[str, Any], status: int) -> str:
        if res.get("error"):
            msg = str(res.get("error"))
            if res.get("reason"):
                msg += f"\nReason: {res.get('reason')}"
            return msg

        lines: list[str] = [
            f"No feasible schedule found (status {status}).",
            "",
            "Solver settings:",
            f"- Room mode: {'cp_rooms' if self.room_mode_combo.currentIndex() == 0 else 'greedy'}",
            f"- Objective: {'on' if self.objective_cb.isChecked() else 'off'}",
            f"- Time limit: {self.time_limit_spin.value()}s",
            f"- Workers: {self.workers_spin.value()}",
        ]
        attempts = self._format_solver_attempts(res)
        if attempts:
            lines.extend(["", "Attempt details:"])
            lines.extend(f"- {line}" for line in attempts[:6])

        if self.inst is not None:
            reasons = explain_infeasibility(self.inst)
            if reasons:
                lines.extend(["", "Likely causes:"])
                lines.extend(f"- {r}" for r in reasons[:8])
            else:
                lines.extend(
                    [
                        "",
                        "No specific structural conflict was detected.",
                        "Try increasing Limit, switching Room mode to Fast (Greedy), or disabling Use CP objective.",
                    ]
                )
        return "\n".join(lines)

    @staticmethod
    def _top_counts(values: Dict[int, int], limit: int = 3) -> list[tuple[int, int]]:
        items = [(int(k), int(v)) for k, v in values.items()]
        items.sort(key=lambda kv: (-kv[1], kv[0]))
        return items[:limit]

    @staticmethod
    def _split_phased_budget(total_seconds: float) -> tuple[float, float]:
        """
        Split solve budget for phased mode.
        Prioritize feasibility first, then reserve a smaller tail for iterative improvement.
        """
        if total_seconds <= 0:
            return 30.0, 0.0
        if total_seconds <= 60:
            return float(total_seconds), 0.0
        improve = min(90.0, float(total_seconds) * 0.20)
        feasibility = max(30.0, float(total_seconds) - improve)
        return feasibility, max(0.0, float(total_seconds) - feasibility)

    # ----- actions -----

    def on_generate(self):
        if self.proc is not None:
            QMessageBox.warning(self, "Busy", "Wait for solving to finish first.")
            return

        mode = self.mode_combo.currentText()
        try:
            if mode == "custom":
                inst = generate_custom_instance(**self._collect_custom_generation_config())
            else:
                inst = generate_instance(mode=mode)
            normalize_instance_for_spec(inst)
            stamp_instance_time(
                inst,
                DEFAULT_DAY_START,
                DEFAULT_SLOT_MINUTES,
                DEFAULT_BREAK_MINUTES,
            )
            self._apply_constraint_settings(inst)
            check_staff_weekly_capacity(inst)  # logs warnings to stdout
            self.inst = inst
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Generate error", str(e))
            return

        self.base_schedule = {}
        self.current_schedule = {}
        self.locked_activities = {}
        self.held_activity_id = None
        self._reset_history()
        self.set_status(f"Instance generated ({mode})")
        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self._load_constraint_controls_from_instance(self.inst)

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
        self._apply_constraint_settings(self.inst)

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
        time_limit_seconds = float(self.time_limit_spin.value())
        objective_on = self.objective_cb.isChecked()
        env_map["TT_ROOM_MODE"] = "cp_rooms" if self.room_mode_combo.currentIndex() == 0 else "greedy"
        env_map["TT_TIME_LIMIT"] = str(self.time_limit_spin.value())
        env_map["TT_CP_WORKERS"] = str(self.workers_spin.value())
        env_map["TT_USE_OBJECTIVE"] = "1" if objective_on else "0"
        if objective_on:
            # Feasibility-first then iterative improvement within the total solve budget.
            feasibility_seconds, improve_budget_seconds = self._split_phased_budget(time_limit_seconds)
            env_map["TT_PHASED_SOLVE"] = "1"
            env_map["TT_FEASIBILITY_SECONDS"] = f"{feasibility_seconds:g}"
            env_map["TT_IMPROVE_TOTAL_SECONDS"] = f"{improve_budget_seconds:g}"
            env_map["TT_IMPROVE_SLICE_SECONDS"] = "5"
            env_map["TT_IMPROVE_ITERS_PER_SLICE"] = "1200"
            env_map["TT_IMPROVE_MAX_ROUNDS"] = "12"
        else:
            env_map["TT_PHASED_SOLVE"] = "0"
            env_map["TT_IMPROVE_TOTAL_SECONDS"] = "0"
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

    def on_undo(self) -> None:
        if not self._undo_stack:
            self.set_status("Nothing to undo")
            return
        current = self._snapshot_state()
        prev = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._restore_state(prev, "Undo applied")
        self._refresh_history_buttons()

    def on_redo(self) -> None:
        if not self._redo_stack:
            self.set_status("Nothing to redo")
            return
        current = self._snapshot_state()
        nxt = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._restore_state(nxt, "Redo applied")
        self._refresh_history_buttons()

    def on_revert_to_base(self) -> None:
        if not self.base_schedule:
            self.set_status("No base solution to revert to")
            return
        self._push_undo_state()
        self.current_schedule = {a_id: info.copy() for a_id, info in self.base_schedule.items()}
        self.locked_activities = {}
        self.held_activity_id = None
        self._sync_instance_staff_from_schedule(self.current_schedule)
        self._sync_locks_to_instance()
        self.update_table()
        self.update_quality_summary()
        self.set_status("Reverted to base schedule")
        self._refresh_history_buttons()

    def on_show_conflicts(self) -> None:
        errors = self._collect_conflict_errors()
        if not errors:
            QMessageBox.information(
                self,
                "Conflict Inspector",
                "No hard conflicts detected in the current schedule.",
            )
            self.set_status("No hard conflicts")
            return
        dlg = ConflictInspectorDialog(self, errors)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            activity_id = dlg.selected_activity_id()
            if activity_id is not None:
                self._focus_activity(int(activity_id), hold=False)
                return
        self.set_status(f"Conflicts found: {len(errors)}")

    def on_clear_locks(self):
        if self.locked_activities:
            self._push_undo_state()
        self.locked_activities = {}
        self._sync_locks_to_instance()
        self.update_table()
        self.update_quality_summary()
        self.set_status("Locks cleared")
        self._refresh_history_buttons()

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
            self.held_activity_id = None
            self._reset_history()
            self.clear_table()
            self.set_status(f"No feasible schedule (status {status})")
            msg = self._build_no_feasible_message(res, int(status))
            QMessageBox.information(self, "No feasible schedule", msg)
            return

        self.base_schedule = res.get("schedule", {})
        self.current_schedule = {
            a_id: info.copy() for a_id, info in self.base_schedule.items()
        }
        self.held_activity_id = None
        self._reset_history()

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

            if improved != self.current_schedule:
                self._push_undo_state()
            self._commit_schedule(
                improved,
                f"Improved global penalty {base_pen} -> {best_pen} "
                f"in {total_iters} iterations",
            )

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
        self.held_activity_id = None
        self._reset_history()
        self._load_constraint_controls_from_instance(self.inst)

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
            f"  - Changed day: {summary['changed_day']}",
            f"  - Changed slot: {summary['changed_slot']}",
            f"Changed room: {summary['changed_room']}",
            f"Changed staff: {summary['changed_staff']}",
        ]
        top_groups = self._top_counts(summary.get("group_move_counts", {}))
        if top_groups:
            labels: list[str] = []
            for g_id, count in top_groups:
                g = self.inst.groups.get(g_id) if self.inst else None
                labels.append(f"{g.name if g else g_id} ({count})")
            lines.append("Top moved groups: " + ", ".join(labels))
        top_staff = self._top_counts(summary.get("staff_move_counts", {}))
        if top_staff:
            labels = []
            for s_id, count in top_staff:
                s = self.inst.staff.get(s_id) if self.inst else None
                labels.append(f"{s.name if s else s_id} ({count})")
            lines.append("Top moved staff: " + ", ".join(labels))
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
        self.held_activity_id = None
        self._reset_history()
        self._load_constraint_controls_from_instance(self.inst)
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
        self.held_activity_id = None
        self._reset_history()
        # Allow importing partially specified schedules (room_id may be blank).
        # Room consistency can still be repaired/validated after solving/exporting.
        errors = validate_schedule_against_instance(self.inst, self.current_schedule, strict_rooms=False)
        if errors:
            msg = "Schedule violates hard rules:\n" + "\n".join(f"- {e}" for e in errors[:20])
            if len(errors) > 20:
                msg += f"\n... and {len(errors) - 20} more"
            QMessageBox.critical(self, "Invalid schedule", msg)
            self.base_schedule = {}
            self.current_schedule = {}
            self.held_activity_id = None
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
        if self.inst is None:
            self.clear_table()
            return
        if self.week_combo.count() == 0:
            self.clear_table()
            return

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

        # Render an empty calendar right after generation/loading even before solving.
        if not self.current_schedule:
            self._cell_activity_map = {}
            for row in range(len(days)):
                for col in range(S):
                    item = QTableWidgetItem("")
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                    )
                    item.setForeground(QBrush(QColor("#f5f5f5")))
                    self.table.setItem(row, col, item)
                    self._cell_activity_map[(row, col)] = []
            self.table.resizeColumnsToContents()
            self.table.resizeRowsToContents()
            for c in range(self.table.columnCount()):
                if self.table.columnWidth(c) < 120:
                    self.table.setColumnWidth(c, 120)
            for r in range(self.table.rowCount()):
                if self.table.rowHeight(r) < 34:
                    self.table.setRowHeight(r, 34)
            return

        if self.entity_combo.count() == 0:
            self.clear_table()
            return
        data = self.entity_combo.currentData()
        if data is None:
            self.clear_table()
            return
        entity_id = int(data)
        view_type = self.view_type_combo.currentText()

        cell_entries: Dict[Tuple[str, int], List[Tuple[int, str]]] = {
            (d, s): [] for d in days for s in range(S)
        }
        self._cell_activity_map = {}

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
                    cell_entries[(day, s)].append((int(a_id), label))

        held_target_map = self._collect_held_target_map(week)
        held_id = (
            int(self.held_activity_id)
            if self.held_activity_id is not None and self.held_activity_id in self.current_schedule
            else None
        )
        held_week_ok = (
            held_id is not None
            and int(self.current_schedule[held_id]["week"]) == int(week)
        )

        for row, day in enumerate(days):
            for col in range(S):
                entries = cell_entries[(day, col)]
                ids = [a_id for a_id, _ in entries]
                text = "\n\n".join(label for _, label in entries)
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                )
                item.setForeground(QBrush(QColor("#f5f5f5")))
                if ids:
                    item.setData(Qt.ItemDataRole.UserRole, ids)
                    item.setToolTip(" / ".join(f"A{a_id}" for a_id in ids))
                if held_week_ok and held_id is not None:
                    if held_id in ids:
                        item.setBackground(QBrush(QColor("#234f7a")))
                    elif held_target_map.get((day, col), False):
                        item.setBackground(QBrush(QColor("#2c5f3c")))
                self.table.setItem(row, col, item)
                self._cell_activity_map[(row, col)] = ids

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

        weights = {
            "stud_free_days": 10,
            "stud_free_mf": 5,
            "stud_gaps": 5,
            "active_days": 5,
            "late_start": 3,
            "thin_day": 3,
            "stability": 1,
            "single_slot": 6,
        }
        overrides = getattr(inst, "soft_weights", None)
        if isinstance(overrides, dict):
            for k, v in overrides.items():
                if k in weights:
                    try:
                        weights[k] = int(v)
                    except Exception:
                        pass

        W_STUD_FREE_DAYS = weights["stud_free_days"]
        W_STUD_FREE_MF = weights["stud_free_mf"]
        W_STUD_GAPS = weights["stud_gaps"]
        W_ACTIVE_DAYS = weights["active_days"]
        W_LATE_START = weights["late_start"]
        W_THIN_DAY = weights["thin_day"]
        W_STABILITY = weights["stability"]
        W_SINGLE_SLOT = weights["single_slot"]

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

        global_penalty = None
        hard_conflicts = 0
        try:
            global_penalty = LocalSearchImprover(self.inst).compute_soft_penalty(
                self.current_schedule
            )
        except Exception:
            global_penalty = None
        try:
            hard_conflicts = len(
                validate_schedule_against_instance(
                    self.inst, self.current_schedule, strict_rooms=False
                )
            )
        except Exception:
            hard_conflicts = 0

        penalties = self.compute_group_penalties(self.current_schedule)
        if not penalties:
            self.quality_label.setText("")
            return

        header_parts: List[str] = []
        if global_penalty is not None:
            header_parts.append(f"Global soft penalty: {global_penalty}")
        header_parts.append(f"Hard conflicts: {hard_conflicts}")
        if self.held_activity_id is not None:
            header_parts.append(f"Held: A{self.held_activity_id}")

        parts: List[str] = []
        for g_id in sorted(self.inst.groups.keys()):
            pen = penalties.get(g_id, 0)
            g = self.inst.groups[g_id]
            status = self.classify_group_quality(pen)
            parts.append(f"{g.name}: {pen} ({status})")

        text = " | ".join(header_parts) + "\nGroup quality:\n" + " | ".join(parts)
        self.quality_label.setText(text)

    # ----- manual edit -----

    def on_cell_double_clicked(self, row: int, col: int):
        if self.inst is None or not self.current_schedule:
            return
        if self.entity_combo.count() == 0 or self.week_combo.count() == 0:
            return

        if self.entity_combo.currentData() is None:
            return

        week_data = self.week_combo.currentData()
        if week_data is None:
            return
        week = int(week_data)

        day = self.inst.days[row]
        slot = col

        act_ids = self._cell_activity_ids_for_view(day, slot, week)

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

        self._push_undo_state()
        updated_schedule = self._clone_schedule()
        info = updated_schedule[a_id]
        info["day"] = new_day
        info["slot"] = new_slot
        info["room_id"] = new_room
        info["staff_id"] = new_staff

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

        self._commit_schedule(
            updated_schedule, f"Edited A{a_id} (locks={len(self.locked_activities)})"
        )

    def check_move(
        self,
        a_id: int,
        new_day: str,
        new_slot: int,
        new_room_id: int,
        new_staff_id: int,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
    ) -> Tuple[bool, str]:
        inst = self.inst
        if inst is None:
            return False, "No instance loaded."
        schedule = self.current_schedule if schedule_override is None else schedule_override
        if a_id not in schedule:
            return False, f"Activity A{a_id} not found in schedule."
        if a_id not in inst.activities:
            return False, f"Activity A{a_id} not found in instance."
        if new_staff_id not in inst.staff:
            return False, "Unknown staff member."
        if new_room_id not in inst.rooms:
            return False, "Unknown room."
        act = inst.activities[a_id]
        info = schedule[a_id]
        w = info["week"]
        dur = info["duration"]
        groups = info["group_ids"]
        hard_flags = getattr(inst, "hard_constraints", {}) or {}

        def _flag(name: str, default: bool = True) -> bool:
            raw = hard_flags.get(name, default) if isinstance(hard_flags, dict) else default
            if isinstance(raw, bool):
                return raw
            if raw is None:
                return default
            return str(raw).strip().lower() not in ("0", "false", "no")

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

        if _flag("enforce_staff_daily_caps", True) and staff.max_slots_per_day is not None and day_load > staff.max_slots_per_day:
            return False, "Staff daily load limit exceeded."
        if _flag("enforce_staff_weekly_caps", True) and staff.max_slots_per_week is not None and week_load > staff.max_slots_per_week:
            return False, "Staff weekly load limit exceeded."

        room = inst.rooms[new_room_id]
        total_students = sum(inst.groups[g].size for g in groups)
        if room.capacity < total_students:
            return False, "Room capacity too small."
        if _flag("enforce_room_availability", True) and room.availability is not None:
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
