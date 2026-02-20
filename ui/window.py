from __future__ import annotations

import sys
import os
import uuid
import pickle
import tempfile
import traceback
import time
import re
import json
from typing import Dict, Any, Tuple, List, Set

# Allow running directly (python ui/window.py) by ensuring repo root on sys.path
ROOT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def _resource_path(*parts: str) -> str:
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = ROOT_DIR
    return os.path.normpath(os.path.join(base, *parts))

from PyQt6.QtCore import Qt, QProcess, QTimer, QEvent
from PyQt6.QtGui import QBrush, QColor, QIcon, QAction, QGuiApplication
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
    QLineEdit,
    QScrollArea,
    QFrame,
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
ROOM_TYPE_CHOICES: Tuple[str, ...] = (
    "LECTURE",
    "TUTORIAL",
    "COMPUTER_LAB",
    "SPECIALIZED_LAB",
)
ROOM_CATEGORY_CHOICES: Tuple[str, ...] = ("SMALL", "MEDIUM", "BIG")
COURSE_LAB_TYPE_CHOICES: Tuple[str, ...] = ("NONE", "NORMAL", "SPECIAL")


class StepSpinBox(QSpinBox):
    """Spinbox with explicit +/- buttons so controls are visible across styles/themes."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setProperty("stepBox", True)
        self._btn_plus = QToolButton(self)
        self._btn_minus = QToolButton(self)
        self._configure_button(self._btn_minus, "-", "left", self.stepDown)
        self._configure_button(self._btn_plus, "+", "right", self.stepUp)

    def _configure_button(
        self,
        button: QToolButton,
        text: str,
        direction: str,
        callback,
    ) -> None:
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setAutoRaise(False)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAutoRepeat(True)
        button.setProperty("spinStep", True)
        button.setProperty("spinDir", direction)
        button.clicked.connect(callback)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        # Keep inner step buttons away from the outer frame so the global outline stays visible.
        inset = 3
        hinted_w = max(
            int(self._btn_plus.minimumSizeHint().width()),
            int(self._btn_minus.minimumSizeHint().width()),
            14,
        )
        w = min(hinted_w, max(14, self.width() - (2 * inset) - 2))
        h = max(14, self.height() - (2 * inset))
        right_x = max(inset, self.width() - w - inset)
        self._btn_minus.setGeometry(inset, inset, w, h)
        self._btn_plus.setGeometry(right_x, inset, w, h)
        self._btn_plus.raise_()
        self._btn_minus.raise_()


class MainWindow(QMainWindow):
    DEFAULT_PREVIEW_DAYS: Tuple[str, ...] = ("MON", "TUE", "WED", "THU", "FRI", "SAT")
    DEFAULT_PREVIEW_SLOTS: int = 5

    def __init__(self):
        super().__init__()
        self.setWindowTitle("University Timetabling")
        icon_path = _resource_path("app_icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.inst: Instance | None = None
        self.base_schedule: Dict[int, Dict[str, Any]] = {}
        self._manual_highlight_base_schedule: Dict[int, Dict[str, Any]] = {}
        self.current_schedule: Dict[int, Dict[str, Any]] = {}
        self.locked_activities: Dict[int, Dict[str, Any]] = {}
        self.held_activity_id: int | None = None
        self._cell_activity_map: Dict[Tuple[int, int], List[int]] = {}
        self.selected_cell_row: int | None = None
        self.selected_cell_col: int | None = None
        self.selected_activity_id: int | None = None
        self._held_move_analysis_map: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self._undo_stack: List[Dict[str, Any]] = []
        self._redo_stack: List[Dict[str, Any]] = []

        self.proc: QProcess | None = None
        self._solve_progress_timer: QTimer | None = None
        self._solve_started_at: float | None = None
        self._solve_expected_seconds: float = 0.0
        self._solve_progress_percent: int = 0
        self._solve_progress_context: Dict[str, Any] = {}
        self._solve_attempt_started_at: float | None = None
        self._solver_output_log: str = ""
        self._solver_output_partial: str = ""
        self._table_relayout_pending = False
        self._layout_stabilize_pending: bool = False
        self.top_widget: QWidget | None = None
        self._top_controls_height_cache: int | None = None
        self._status_full_text: str = "Ready"
        self._live_improve_mode: bool = False
        self._improve_running: bool = False
        self._improve_stop_requested: bool = False
        self._maximize_on_first_show: bool = True
        self.tmp_inst_path: str | None = None
        self.tmp_res_path: str | None = None
        self._room_table_internal_change = False
        self._custom_program_table_internal_change = False
        self._custom_course_pattern_table_internal_change = False

        self._build_ui()
        self._connect_signals()

    # ----- UI setup -----

    def _build_ui(self):
        self.top_widget = QWidget()
        top_layout = QVBoxLayout(self.top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)

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
        self.clear_locks_button = QPushButton("Clear Locks")
        self.improve_button = QPushButton("Improve")
        self.stop_improve_button = QPushButton("Stop Improving")
        self.stop_improve_button.setEnabled(False)
        self.undo_button = QPushButton("Undo")
        self.redo_button = QPushButton("Redo")
        self.revert_button = QPushButton("Revert Base")
        self.conflicts_button = QPushButton("Conflicts")

        self.room_mode_combo = QComboBox()
        self.room_mode_combo.addItems(["Strict (CP rooms)", "Fast (Greedy rooms)"])
        self.room_mode_combo.setCurrentIndex(0)

        self.objective_cb = QCheckBox("Use CP objective")
        self.objective_cb.setChecked(True)

        self.time_limit_spin = StepSpinBox()
        self.time_limit_spin.setRange(5, 3600)
        self.time_limit_spin.setValue(DEFAULT_TIME_LIMIT)
        self.time_limit_spin.setSuffix(" s")

        self.workers_preset_combo = QComboBox()
        self._worker_preset_counts: Dict[str, int] = {}
        cpu_count = max(1, min(64, int(os.cpu_count() or DEFAULT_CP_WORKERS)))
        workers_min = 1
        workers_med = max(1, min(cpu_count, max(2, cpu_count // 2)))
        workers_max = cpu_count
        for label, value in [
            ("Min", workers_min),
            ("Medium", workers_med),
            ("Max", workers_max),
        ]:
            self.workers_preset_combo.addItem(f"{label} ({int(value)})", int(value))
            self._worker_preset_counts[str(label).lower()] = int(value)
        # Default to medium unless DEFAULT_CP_WORKERS clearly matches another preset.
        default_idx = 1
        for idx in range(self.workers_preset_combo.count()):
            data = self.workers_preset_combo.itemData(idx)
            if int(data) == int(DEFAULT_CP_WORKERS):
                default_idx = idx
                break
        self.workers_preset_combo.setCurrentIndex(default_idx)

        self.improve_runs_spin = StepSpinBox()
        self.improve_runs_spin.setRange(10, 100000)
        self.improve_runs_spin.setSingleStep(10)
        self.improve_runs_spin.setValue(1000)
        self.improve_runs_spin.setMinimumWidth(90)
        self.improve_runs_spin.setMaximumWidth(130)

        self.ls_time_spin = StepSpinBox()
        self.ls_time_spin.setRange(0, 600)
        self.ls_time_spin.setValue(10)
        self.ls_time_spin.setSuffix(" s")
        self.ls_time_spin.setMaximumWidth(120)

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
        self.view_type_combo.addItems(["Group", "Staff", "Room", "All"])
        self.entity_combo = QComboBox()
        self.week_combo = QComboBox()

        self.status_label = QLabel("Ready")
        self.quality_label = QLabel("")
        self.quality_label.setWordWrap(True)

        def _pair_widget(label: str, widget: QWidget) -> QWidget:
            box = QWidget()
            lay = QHBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(4)
            lay.addWidget(QLabel(label))
            lay.addWidget(widget)
            return box

        # Row 0: main actions
        row_actions = QHBoxLayout()
        row_actions.setContentsMargins(8, 1, 8, 1)
        row_actions.setSpacing(8)
        action_widgets: List[QWidget] = [
            _pair_widget("Mode:", self.mode_combo),
            self.generate_button,
            self.solve_button,
            self.clear_locks_button,
            self.improve_button,
            self.stop_improve_button,
            self.export_menu_btn,
            self.project_menu_btn,
            self.undo_button,
            self.redo_button,
            self.revert_button,
            self.conflicts_button,
        ]
        for idx, widget in enumerate(action_widgets):
            row_actions.addWidget(widget)
            if idx < len(action_widgets) - 1:
                row_actions.addStretch(1)
        top_layout.addLayout(row_actions)

        # Row 1: tuning
        row_tuning = QHBoxLayout()
        row_tuning.setContentsMargins(8, 1, 8, 1)
        row_tuning.setSpacing(10)
        tuning_widgets: List[QWidget] = [
            _pair_widget("LS iters:", self.improve_runs_spin),
            _pair_widget("LS time:", self.ls_time_spin),
            _pair_widget("Room mode:", self.room_mode_combo),
            self.objective_cb,
            _pair_widget("Limit:", self.time_limit_spin),
            _pair_widget("Workers:", self.workers_preset_combo),
        ]
        for idx, widget in enumerate(tuning_widgets):
            row_tuning.addWidget(widget)
            if idx < len(tuning_widgets) - 1:
                row_tuning.addStretch(1)
        top_layout.addLayout(row_tuning)

        # Row 2: view controls + status
        row_view = QHBoxLayout()
        row_view.setContentsMargins(8, 1, 8, 1)
        row_view.setSpacing(10)
        row_view.addWidget(_pair_widget("View:", self.view_type_combo))
        row_view.addWidget(self.entity_combo)
        row_view.addWidget(_pair_widget("Week:", self.week_combo))
        row_view.addWidget(self.status_label, 1)
        top_layout.addLayout(row_view)

        # Emphasize primary admin controls and improve discoverability.
        self.improve_button.setMaximumWidth(96)
        self.stop_improve_button.setMinimumWidth(126)
        self.export_menu_btn.setMinimumWidth(92)
        self.project_menu_btn.setMinimumWidth(92)
        self.view_type_combo.setMinimumWidth(120)
        self.entity_combo.setMinimumWidth(220)
        self.week_combo.setMinimumWidth(96)
        self.workers_preset_combo.setMinimumWidth(120)
        self.status_label.setWordWrap(False)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.entity_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.entity_combo.setMinimumContentsLength(18)
        self.view_type_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.week_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(True)
        self.table.horizontalHeader().setVisible(True)
        self.table.setWordWrap(True)
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.workspace_tabs = QTabWidget()
        schedule_tab = QWidget()
        schedule_layout = QVBoxLayout(schedule_tab)
        schedule_layout.setContentsMargins(0, 0, 0, 0)
        schedule_layout.setSpacing(6)
        schedule_layout.addWidget(self.table, 1)
        self.schedule_actions_scroll = QScrollArea()
        self.schedule_actions_scroll.setWidget(self._build_schedule_actions_panel())
        self.schedule_actions_scroll.setWidgetResizable(True)
        self.schedule_actions_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.schedule_actions_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.schedule_actions_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        schedule_layout.addWidget(self.schedule_actions_scroll, 0)
        schedule_layout.addWidget(self.quality_label)
        self.workspace_tabs.addTab(schedule_tab, "Schedule")
        self.workspace_tabs.addTab(self._build_generator_tab(), "Generator")
        self.workspace_tabs.addTab(self._build_constraints_tab(), "Constraints")

        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)
        self.top_controls_scroll = QScrollArea()
        self.top_controls_scroll.setWidget(self.top_widget)
        self.top_controls_scroll.setWidgetResizable(True)
        self.top_controls_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.top_controls_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.top_controls_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.top_controls_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        main_layout.addWidget(self.top_controls_scroll, 0)
        main_layout.addWidget(self.workspace_tabs)
        self.setCentralWidget(central)

        self.setStyleSheet(DARK_STYLE)

        self._build_menus()
        self._reset_custom_program_table()
        self._reset_custom_course_pattern_table()
        self._reset_custom_staff_table()
        self._reset_custom_room_table()
        self._refresh_staff_course_picker()
        self._load_constraint_controls_from_instance(None)
        self._apply_control_tooltips()
        self._refresh_history_buttons()
        self._refresh_quick_actions()
        self.clear_table()
        self._schedule_table_relayout()
        self._apply_responsive_ui()
        self._sync_top_controls_height()
        self._defer_layout_stabilization()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._schedule_table_relayout()
        self._apply_responsive_ui()
        self._defer_layout_stabilization()

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._schedule_table_relayout()
            self._apply_responsive_ui()
            self._defer_layout_stabilization()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if self._maximize_on_first_show:
            self._maximize_on_first_show = False
            self._enforce_true_maximized()
            QTimer.singleShot(60, self._enforce_true_maximized)
            QTimer.singleShot(180, self._enforce_true_maximized)
        self._sync_top_controls_height()
        self._defer_layout_stabilization()

    def _apply_responsive_ui(self) -> None:
        w = int(self.width())
        if w >= 1700:
            improve_max = 96
            stop_min = 132
            menu_min = 96
            view_min = 130
            entity_min = 260
            week_min = 110
            workers_min = 130
        elif w >= 1450:
            improve_max = 90
            stop_min = 126
            menu_min = 90
            view_min = 116
            entity_min = 220
            week_min = 100
            workers_min = 124
        elif w >= 1250:
            improve_max = 84
            stop_min = 120
            menu_min = 84
            view_min = 102
            entity_min = 180
            week_min = 92
            workers_min = 116
        else:
            improve_max = 76
            stop_min = 112
            menu_min = 78
            view_min = 88
            entity_min = 140
            week_min = 84
            workers_min = 108

        self.improve_button.setMaximumWidth(improve_max)
        self.stop_improve_button.setMinimumWidth(stop_min)
        self.export_menu_btn.setMinimumWidth(menu_min)
        self.project_menu_btn.setMinimumWidth(menu_min)
        self.view_type_combo.setMinimumWidth(view_min)
        self.entity_combo.setMinimumWidth(entity_min)
        self.week_combo.setMinimumWidth(week_min)
        if hasattr(self, "workers_preset_combo"):
            self.workers_preset_combo.setMinimumWidth(workers_min)
        self.top_widget.setMinimumWidth(0)
        if hasattr(self, "top_controls_scroll"):
            self.top_controls_scroll.setMinimumWidth(0)
            self.top_controls_scroll.updateGeometry()
        if hasattr(self, "schedule_actions_scroll"):
            self.schedule_actions_scroll.setMinimumWidth(0)
            self.schedule_actions_scroll.updateGeometry()
        if self.top_widget is not None:
            top_layout = self.top_widget.layout()
            if top_layout is not None:
                top_layout.activate()
            self.top_widget.updateGeometry()
        self._sync_top_controls_height()
        central = self.centralWidget()
        if central is not None:
            layout = central.layout()
            if layout is not None:
                layout.activate()
            central.updateGeometry()
        self._refresh_status_label()
        self.table.updateGeometry()

    def _defer_layout_stabilization(self) -> None:
        if self._layout_stabilize_pending:
            return
        self._layout_stabilize_pending = True
        QTimer.singleShot(0, self._force_layout_refresh)
        QTimer.singleShot(120, self._force_layout_refresh)

    def _force_layout_refresh(self) -> None:
        if not self._layout_stabilize_pending:
            return
        self._apply_responsive_ui()
        self._schedule_table_relayout()
        self.updateGeometry()
        self.update()
        self._layout_stabilize_pending = False

    def _sync_top_controls_height(self) -> None:
        if not hasattr(self, "top_controls_scroll") or self.top_widget is None:
            return
        try:
            base = max(72, int(self.top_widget.sizeHint().height()) + 6)
            hbar = self.top_controls_scroll.horizontalScrollBar()
            extra = int(hbar.sizeHint().height()) + 2 if hbar.isVisible() else 0
            target = int(base + extra)
            if self._top_controls_height_cache == target:
                return
            self.top_controls_scroll.setMinimumHeight(target)
            self.top_controls_scroll.setMaximumHeight(target)
            self.top_controls_scroll.updateGeometry()
            self._top_controls_height_cache = target
        except Exception:
            pass

    def _enforce_true_maximized(self) -> None:
        try:
            screen = self.screen() or QGuiApplication.primaryScreen()
            if screen is None:
                self.showMaximized()
                return
            available = screen.availableGeometry()
            width_ok = int(self.width()) >= int(available.width() * 0.9)
            height_ok = int(self.height()) >= int(available.height() * 0.9)
            if not self.isMaximized() or not (width_ok and height_ok):
                self.showNormal()
                self.setGeometry(available)
                self.showMaximized()
        except Exception:
            self.showMaximized()

    def _schedule_table_relayout(self) -> None:
        if self._table_relayout_pending:
            return
        self._table_relayout_pending = True
        QTimer.singleShot(0, self._apply_table_relayout)

    def _apply_table_relayout(self) -> None:
        self._table_relayout_pending = False
        if not hasattr(self, "table"):
            return
        if self.table.columnCount() <= 0 or self.table.rowCount() <= 0:
            return

        h = self.table.horizontalHeader()
        v = self.table.verticalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        h.setMinimumSectionSize(110)
        v.setMinimumSectionSize(34)
        self.table.updateGeometry()
        self.table.viewport().update()

    def _apply_control_tooltips(self) -> None:
        self.generate_button.setToolTip("Create a new scheduling instance from the selected mode.")
        self.solve_button.setToolTip("Run the solver from scratch.")
        self.clear_locks_button.setToolTip("Remove all time/room locks from activities.")
        self.improve_button.setToolTip("Run local-search improvement on the current schedule.")
        self.stop_improve_button.setToolTip("Request a graceful stop for the active improvement run.")
        self.undo_button.setToolTip("Undo the last manual/admin schedule change.")
        self.redo_button.setToolTip("Redo the last undone schedule change.")
        self.revert_button.setToolTip("Restore the current schedule to the base solved schedule.")
        self.conflicts_button.setToolTip("Open a list of current hard-constraint conflicts.")
        self.export_menu_btn.setToolTip("Export schedules/reports.")
        self.project_menu_btn.setToolTip("Save/load/compare project data.")
        self.mode_combo.setToolTip("Instance template used when generating data.")
        self.room_mode_combo.setToolTip(
            "Room assignment strategy: Strict uses CP room variables; Fast uses greedy room assignment."
        )
        self.objective_cb.setToolTip(
            "Solver modes:\n"
            "- CP: Strict room mode + objective OFF (feasible solution focus)\n"
            "- CP objective: Strict room mode + objective ON (optimize soft constraints)\n"
            "- Greedy: Fast room mode (rooms assigned greedily; fastest but less rigorous)"
        )
        self.view_type_combo.setToolTip("Choose whether the timetable is filtered by Group, Staff, Room, or All.")
        self.entity_combo.setToolTip("Select which entity to view in the timetable.")
        self.week_combo.setToolTip("Select academic week.")
        self.time_limit_spin.setToolTip("Maximum solver runtime (seconds).")
        self.workers_preset_combo.setToolTip(
            "CP-SAT worker preset: Min=1 thread, Medium=about half cores, Max=all available cores."
        )
        self.improve_runs_spin.setToolTip("Maximum local-search iterations.")
        self.ls_time_spin.setToolTip("Maximum local-search runtime (seconds).")
        self.selected_activity_combo.setToolTip(
            "Activities in the currently selected cell."
        )
        self.quick_edit_btn.setToolTip("Edit selected activity time/room/staff and locks.")
        self.quick_hold_btn.setToolTip("Mark selected activity as held for drag-like moves.")
        self.quick_move_btn.setToolTip("Move held activity to the selected day/slot.")
        self.quick_swap_btn.setToolTip("Swap timeslots between held and selected activity.")
        self.quick_time_lock_btn.setToolTip("Toggle time lock for selected activity.")
        self.quick_room_lock_btn.setToolTip("Toggle room lock for selected activity.")
        self.quick_targets_btn.setToolTip("Show all valid target slots for the held activity.")
        self.quick_release_btn.setToolTip("Clear held activity selection.")
        self.show_score_deltas_cb.setToolTip(
            "Show/hide in-grid global soft-score deltas for held-move target slots."
        )

    def _build_schedule_actions_panel(self) -> QWidget:
        box = QGroupBox("Quick Admin Actions")
        layout = QVBoxLayout(box)

        self.quick_help_label = QLabel(
            "Click a timetable cell, choose an activity, then use actions below."
            " Hold mode supports hover diagnostics for target-slot conflicts."
        )
        self.quick_help_label.setWordWrap(True)
        layout.addWidget(self.quick_help_label)
        self.quick_legend_label = QLabel(
            "Colors: "
            "<span style='color:#6fe38a'>green</span>=better held target (lower global score), "
            "<span style='color:#d8a958'>amber</span>=worse held target (higher global score), "
            "<span style='color:#ffd84d'>yellow</span>=held target conflicts, "
            "<span style='color:#ff86dd'>pink</span>=manual admin edits, "
            "<span style='color:#ff6b6b'>red</span>=current hard conflict, "
            "<span style='color:#7ab7ff'>blue</span>=held activity."
        )
        self.quick_legend_label.setWordWrap(True)
        layout.addWidget(self.quick_legend_label)
        self.show_score_deltas_cb = QCheckBox("Show score deltas in grid")
        self.show_score_deltas_cb.setChecked(True)
        layout.addWidget(self.show_score_deltas_cb)

        row1 = QHBoxLayout()
        self.selected_slot_label = QLabel("Selected: none")
        self.selected_slot_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.selected_activity_combo = QComboBox()
        self.selected_activity_combo.setMinimumWidth(280)
        self.selected_activity_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.quick_edit_btn = QPushButton("Edit")
        self.quick_hold_btn = QPushButton("Hold")
        row1.addWidget(self.selected_slot_label)
        row1.addWidget(QLabel("Activity:"))
        row1.addWidget(self.selected_activity_combo)
        row1.addWidget(self.quick_edit_btn)
        row1.addWidget(self.quick_hold_btn)
        row1.addStretch(1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.held_slot_label = QLabel("Held: none")
        self.held_slot_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.quick_move_btn = QPushButton("Move Held Here")
        self.quick_swap_btn = QPushButton("Swap Held/Selected")
        self.quick_time_lock_btn = QPushButton("Toggle Time Lock")
        self.quick_room_lock_btn = QPushButton("Toggle Room Lock")
        self.quick_targets_btn = QPushButton("Show Held Targets")
        self.quick_release_btn = QPushButton("Release Held")
        row2.addWidget(self.held_slot_label)
        row2.addWidget(self.quick_move_btn)
        row2.addWidget(self.quick_swap_btn)
        row2.addWidget(self.quick_time_lock_btn)
        row2.addWidget(self.quick_room_lock_btn)
        row2.addWidget(self.quick_targets_btn)
        row2.addWidget(self.quick_release_btn)
        row2.addStretch(1)
        layout.addLayout(row2)

        return box

    def _connect_signals(self):
        self.generate_button.clicked.connect(self.on_generate)
        self.solve_button.clicked.connect(self.on_solve)
        self.clear_locks_button.clicked.connect(self.on_clear_locks)
        self.improve_button.clicked.connect(self.on_improve)
        self.stop_improve_button.clicked.connect(self.on_stop_improve)
        self.undo_button.clicked.connect(self.on_undo)
        self.redo_button.clicked.connect(self.on_redo)
        self.revert_button.clicked.connect(self.on_revert_to_base)
        self.conflicts_button.clicked.connect(self.on_show_conflicts)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.custom_reset_staff_btn.clicked.connect(self._reset_custom_staff_table)
        self.custom_reset_rooms_btn.clicked.connect(self._reset_custom_room_table)
        self.custom_reset_programs_btn.clicked.connect(self._reset_custom_program_table)
        self.custom_reset_course_patterns_btn.clicked.connect(
            self._reset_custom_course_pattern_table
        )
        self.staff_add_course_btn.clicked.connect(self._on_add_course_to_selected_staff)
        self.custom_programs_spin.valueChanged.connect(self._on_custom_size_changed)
        self.custom_groups_per_program_spin.valueChanged.connect(self._on_custom_size_changed)
        self.custom_courses_per_program_spin.valueChanged.connect(self._on_custom_size_changed)
        self.custom_course_names_edit.textChanged.connect(self._refresh_staff_course_picker)
        self.custom_course_names_edit.textChanged.connect(
            self._reset_custom_course_pattern_table
        )
        self.custom_program_table.itemChanged.connect(self._on_custom_program_table_item_changed)
        self.custom_room_table.itemChanged.connect(self._on_room_table_item_changed)
        self.apply_constraints_btn.clicked.connect(self.on_apply_constraints_to_instance)
        self.view_type_combo.currentIndexChanged.connect(self.update_entities)
        self.entity_combo.currentIndexChanged.connect(self.update_table)
        self.week_combo.currentIndexChanged.connect(self.update_table)
        self.selected_activity_combo.currentIndexChanged.connect(
            self.on_selected_activity_changed
        )
        self.quick_edit_btn.clicked.connect(self.on_quick_edit_selected)
        self.quick_hold_btn.clicked.connect(self.on_quick_hold_selected)
        self.quick_move_btn.clicked.connect(self.on_quick_move_held_here)
        self.quick_swap_btn.clicked.connect(self.on_quick_swap_held_with_selected)
        self.quick_time_lock_btn.clicked.connect(self.on_quick_toggle_time_lock)
        self.quick_room_lock_btn.clicked.connect(self.on_quick_toggle_room_lock)
        self.quick_targets_btn.clicked.connect(self.on_quick_show_held_targets)
        self.quick_release_btn.clicked.connect(self.on_quick_release_held)
        self.show_score_deltas_cb.toggled.connect(lambda _v: self.update_table())
        self.table.cellClicked.connect(self.on_table_cell_clicked)
        self.table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        self.table.customContextMenuRequested.connect(self.on_table_context_menu)
        self.hard_week1_cb.toggled.connect(self.on_constraint_controls_changed)
        self.hard_block_prof_cb.toggled.connect(self.on_constraint_controls_changed)
        self.hard_staff_daily_cb.toggled.connect(self.on_constraint_controls_changed)
        self.hard_staff_weekly_cb.toggled.connect(self.on_constraint_controls_changed)
        self.hard_room_availability_cb.toggled.connect(self.on_constraint_controls_changed)
        for spin in self.soft_weight_spins.values():
            spin.valueChanged.connect(self.on_constraint_controls_changed)

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
        self.custom_programs_spin = StepSpinBox()
        self.custom_programs_spin.setRange(1, 200)
        self.custom_programs_spin.setValue(20)
        self.custom_groups_per_program_spin = StepSpinBox()
        self.custom_groups_per_program_spin.setRange(1, 20)
        self.custom_groups_per_program_spin.setValue(2)
        self.custom_courses_per_program_spin = StepSpinBox()
        self.custom_courses_per_program_spin.setRange(1, 20)
        self.custom_courses_per_program_spin.setValue(6)
        self.custom_course_names_edit = QLineEdit()
        self.custom_course_names_edit.setPlaceholderText(
            "Optional CSV names: Algorithms,Databases,Networks,..."
        )
        counts_form.addRow("Programs", self.custom_programs_spin)
        counts_form.addRow("Groups per program", self.custom_groups_per_program_spin)
        counts_form.addRow("Courses per program", self.custom_courses_per_program_spin)
        counts_form.addRow("Course names (CSV)", self.custom_course_names_edit)
        layout.addWidget(counts_box)

        plan_box = QGroupBox("Program/Course Overrides")
        plan_layout = QVBoxLayout(plan_box)
        plan_controls = QHBoxLayout()
        self.custom_reset_programs_btn = QPushButton("Reset Program Rows")
        self.custom_reset_course_patterns_btn = QPushButton("Reset Course Patterns")
        plan_controls.addWidget(self.custom_reset_programs_btn)
        plan_controls.addWidget(self.custom_reset_course_patterns_btn)
        plan_controls.addStretch(1)
        plan_layout.addLayout(plan_controls)

        self.custom_program_table = QTableWidget(0, 4)
        self.custom_program_table.setHorizontalHeaderLabels(
            ["Program", "Groups", "Courses", "Courses/Group"]
        )
        self.custom_program_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.custom_program_table.verticalHeader().setVisible(False)
        self.custom_program_table.setSortingEnabled(True)
        plan_layout.addWidget(self.custom_program_table)

        self.custom_course_pattern_table = QTableWidget(0, 7)
        self.custom_course_pattern_table.setHorizontalHeaderLabels(
            [
                "Course ID",
                "Course Name",
                "LEC Count",
                "TUT Count",
                "Lab Type",
                "Lab Dur",
                "Lab Tag",
            ]
        )
        self.custom_course_pattern_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.custom_course_pattern_table.verticalHeader().setVisible(False)
        self.custom_course_pattern_table.setSortingEnabled(True)
        plan_layout.addWidget(self.custom_course_pattern_table)

        plan_hint = QLabel(
            "Program rows allow different groups/courses per program and courses per group.\n"
            "Course pattern rows allow per-course LEC/TUT totals and lab type (NONE/NORMAL/SPECIAL)."
        )
        plan_hint.setWordWrap(True)
        plan_layout.addWidget(plan_hint)
        layout.addWidget(plan_box)

        staff_box = QGroupBox("Staff Mapping")
        staff_layout = QVBoxLayout(staff_box)
        staff_controls = QHBoxLayout()
        self.custom_num_profs_spin = StepSpinBox()
        self.custom_num_profs_spin.setRange(1, 500)
        self.custom_num_profs_spin.setValue(40)
        self.custom_num_tas_spin = StepSpinBox()
        self.custom_num_tas_spin.setRange(1, 500)
        self.custom_num_tas_spin.setValue(30)
        self.custom_reset_staff_btn = QPushButton("Reset Staff Rows")
        staff_controls.addWidget(QLabel("Professors"))
        staff_controls.addWidget(self.custom_num_profs_spin)
        staff_controls.addWidget(QLabel("TAs"))
        staff_controls.addWidget(self.custom_num_tas_spin)
        staff_controls.addWidget(self.custom_reset_staff_btn)
        self.staff_course_picker_combo = QComboBox()
        self.staff_course_picker_combo.setMinimumWidth(200)
        self.staff_add_course_btn = QPushButton("Add Course To Selected Staff")
        self.staff_add_course_btn.setMinimumWidth(180)
        staff_controls.addWidget(QLabel("Course ID picker"))
        staff_controls.addWidget(self.staff_course_picker_combo)
        staff_controls.addWidget(self.staff_add_course_btn)
        staff_controls.addStretch(1)
        staff_layout.addLayout(staff_controls)
        self.custom_staff_table = QTableWidget(0, 4)
        self.custom_staff_table.setHorizontalHeaderLabels(
            ["Staff", "Role", "Course IDs (csv)", "Available Days (csv)"]
        )
        self.custom_staff_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.custom_staff_table.horizontalHeader().setSectionsClickable(True)
        self.custom_staff_table.horizontalHeader().setSortIndicatorShown(True)
        self.custom_staff_table.verticalHeader().setVisible(False)
        self.custom_staff_table.setSortingEnabled(True)
        staff_layout.addWidget(self.custom_staff_table)
        layout.addWidget(staff_box)

        room_box = QGroupBox("Room Definitions")
        room_layout = QVBoxLayout(room_box)
        room_controls = QHBoxLayout()
        self.custom_room_count_spin = StepSpinBox()
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
        self.custom_room_table.horizontalHeader().setSectionsClickable(True)
        self.custom_room_table.horizontalHeader().setSortIndicatorShown(True)
        self.custom_room_table.verticalHeader().setVisible(False)
        self.custom_room_table.setSortingEnabled(True)
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
        soft_box.setToolTip(
            "Hover each soft-constraint label or value to see what it optimizes."
        )
        soft_form = QFormLayout(soft_box)
        self.soft_weight_spins: Dict[str, QSpinBox] = {}
        self.soft_weight_help: Dict[str, str] = {}
        soft_defs = [
            (
                "stud_free_days",
                "Student free days",
                10,
                "Penalizes schedules that give each group fewer free days than its preference.",
            ),
            (
                "stud_free_mf",
                "Student Mon-Fri free days",
                5,
                "Extra pressure to keep free days on weekdays, not only Saturday.",
            ),
            (
                "stud_gaps",
                "Student gaps",
                5,
                "Penalizes multiple separated teaching blocks in one day for a group.",
            ),
            (
                "staff_free_day",
                "Staff free day",
                6,
                "Rewards giving each staff member at least one lighter/free day per week.",
            ),
            (
                "active_days",
                "Active-day minimization",
                5,
                "Penalizes spreading a group's classes across too many different days.",
            ),
            (
                "late_start",
                "Late start",
                3,
                "Penalizes days whose first class starts late in the timetable.",
            ),
            (
                "thin_day",
                "Thin day",
                3,
                "Penalizes days with very light attendance (e.g., only 2 slots).",
            ),
            (
                "single_slot",
                "Single-slot day",
                6,
                "Penalizes days where a group comes in for only one slot.",
            ),
            (
                "stability",
                "Week-to-week stability",
                1,
                "Penalizes changing which days are active for a group between weeks.",
            ),
            (
                "room_consistency",
                "Room consistency",
                1,
                "Penalizes moving a course between many different rooms over time.",
            ),
        ]
        for key, label, default, help_text in soft_defs:
            spin = StepSpinBox()
            spin.setRange(0, 200)
            spin.setValue(default)
            spin.setToolTip(help_text)
            spin.setStatusTip(help_text)
            spin.setWhatsThis(help_text)
            self.soft_weight_spins[key] = spin
            self.soft_weight_help[key] = help_text
            label_widget = QLabel(label)
            label_widget.setToolTip(help_text)
            label_widget.setStatusTip(help_text)
            label_widget.setWhatsThis(help_text)
            soft_form.addRow(label_widget, spin)
        layout.addWidget(soft_box)

        soft_help = QLabel(
            "Soft-constraint weights are trade-offs (not hard requirements): higher value means the solver"
            " prioritizes that preference more strongly."
        )
        soft_help.setWordWrap(True)
        layout.addWidget(soft_help)

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

    @staticmethod
    def _make_locked_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _find_room_combo_position(self, combo: QComboBox) -> Tuple[int, int]:
        for row in range(self.custom_room_table.rowCount()):
            for col in (1, 2):
                if self.custom_room_table.cellWidget(row, col) is combo:
                    return row, col
        return -1, -1

    def _on_room_combo_changed(self, _text: str) -> None:
        if self._room_table_internal_change:
            return
        sender = self.sender()
        if not isinstance(sender, QComboBox):
            return
        row, col = self._find_room_combo_position(sender)
        if row < 0 or col < 0:
            return
        item = self.custom_room_table.item(row, col)
        if item is None:
            item = self._make_locked_item(sender.currentText())
            self.custom_room_table.setItem(row, col, item)
        else:
            item.setText(sender.currentText())
        self._on_room_table_item_changed(item)

    def _set_room_enum_cell(
        self,
        row: int,
        col: int,
        *,
        options: Tuple[str, ...],
        value: str,
    ) -> None:
        value_norm = str(value).strip().upper()
        if value_norm not in options:
            value_norm = options[0]
        self.custom_room_table.setItem(row, col, self._make_locked_item(value_norm))
        combo = QComboBox(self.custom_room_table)
        combo.addItems(list(options))
        combo.blockSignals(True)
        idx = combo.findText(value_norm)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        combo.currentTextChanged.connect(self._on_room_combo_changed)
        self.custom_room_table.setCellWidget(row, col, combo)

    def _room_table_text(self, row: int, col: int) -> str:
        widget = self.custom_room_table.cellWidget(row, col)
        if isinstance(widget, QComboBox):
            return str(widget.currentText()).strip()
        item = self.custom_room_table.item(row, col)
        return str(item.text()).strip() if item is not None else ""

    def _reset_custom_staff_table(self) -> None:
        rows = int(self.custom_num_profs_spin.value()) + int(self.custom_num_tas_spin.value())
        was_sorting = self.custom_staff_table.isSortingEnabled()
        self.custom_staff_table.setSortingEnabled(False)
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
        self.custom_staff_table.setSortingEnabled(was_sorting)

    def _reset_custom_room_table(self) -> None:
        was_sorting = self.custom_room_table.isSortingEnabled()
        self.custom_room_table.setSortingEnabled(False)
        self.custom_room_table.blockSignals(True)
        self.custom_room_table.setRowCount(int(self.custom_room_count_spin.value()))
        defaults = ["LECTURE", "LECTURE", "TUTORIAL", "COMPUTER_LAB", "SPECIALIZED_LAB"]
        for row in range(self.custom_room_table.rowCount()):
            rtype = defaults[row % len(defaults)]
            cat = "MEDIUM"
            cap = ROOM_CATEGORY_CAPACITY[cat]
            self.custom_room_table.setItem(row, 0, QTableWidgetItem(f"{rtype.title()}-{row + 1}"))
            self._set_room_enum_cell(row, 1, options=ROOM_TYPE_CHOICES, value=rtype)
            self._set_room_enum_cell(row, 2, options=ROOM_CATEGORY_CHOICES, value=cat)
            self.custom_room_table.setItem(row, 3, QTableWidgetItem(str(cap)))
            self.custom_room_table.setItem(row, 4, QTableWidgetItem("" if rtype != "SPECIALIZED_LAB" else "LAB1"))
        self.custom_room_table.blockSignals(False)
        self.custom_room_table.setSortingEnabled(was_sorting)

    def _on_custom_size_changed(self, *_args: Any) -> None:
        self._reset_custom_program_table()
        self._reset_custom_course_pattern_table()
        self._refresh_staff_course_picker()

    def _reset_custom_program_table(self) -> None:
        rows = int(self.custom_programs_spin.value())
        default_groups = int(self.custom_groups_per_program_spin.value())
        default_courses = int(self.custom_courses_per_program_spin.value())
        was_sorting = self.custom_program_table.isSortingEnabled()
        self.custom_program_table.setSortingEnabled(False)
        self.custom_program_table.blockSignals(True)
        self._custom_program_table_internal_change = True
        self.custom_program_table.setRowCount(rows)
        for row in range(rows):
            self.custom_program_table.setItem(row, 0, self._make_locked_item(str(row + 1)))
            self.custom_program_table.setItem(row, 1, QTableWidgetItem(str(default_groups)))
            self.custom_program_table.setItem(row, 2, QTableWidgetItem(str(default_courses)))
            self.custom_program_table.setItem(row, 3, QTableWidgetItem(str(default_courses)))
        self._custom_program_table_internal_change = False
        self.custom_program_table.blockSignals(False)
        self.custom_program_table.setSortingEnabled(was_sorting)

    def _effective_custom_total_courses(self) -> int:
        if not hasattr(self, "custom_program_table"):
            return int(self.custom_programs_spin.value()) * int(
                self.custom_courses_per_program_spin.value()
            )
        total = 0
        for row in range(self.custom_program_table.rowCount()):
            item = self.custom_program_table.item(row, 2)
            try:
                courses = max(1, int(str(item.text()).strip())) if item is not None else int(
                    self.custom_courses_per_program_spin.value()
                )
            except Exception:
                courses = int(self.custom_courses_per_program_spin.value())
            total += int(courses)
        return max(1, int(total))

    def _find_course_lab_combo_row(self, combo: QComboBox) -> int:
        for row in range(self.custom_course_pattern_table.rowCount()):
            if self.custom_course_pattern_table.cellWidget(row, 4) is combo:
                return row
        return -1

    def _set_course_lab_type_cell(self, row: int, value: str) -> None:
        value_norm = str(value).strip().upper()
        if value_norm not in COURSE_LAB_TYPE_CHOICES:
            value_norm = "NONE"
        self.custom_course_pattern_table.setItem(row, 4, self._make_locked_item(value_norm))
        combo = QComboBox(self.custom_course_pattern_table)
        combo.addItems(list(COURSE_LAB_TYPE_CHOICES))
        combo.blockSignals(True)
        idx = combo.findText(value_norm)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        combo.currentTextChanged.connect(self._on_course_lab_type_changed)
        self.custom_course_pattern_table.setCellWidget(row, 4, combo)

    def _course_pattern_table_text(self, row: int, col: int) -> str:
        widget = self.custom_course_pattern_table.cellWidget(row, col)
        if isinstance(widget, QComboBox):
            return str(widget.currentText()).strip()
        item = self.custom_course_pattern_table.item(row, col)
        return str(item.text()).strip() if item is not None else ""

    def _on_course_lab_type_changed(self, _text: str) -> None:
        if self._custom_course_pattern_table_internal_change:
            return
        sender = self.sender()
        if not isinstance(sender, QComboBox):
            return
        row = self._find_course_lab_combo_row(sender)
        if row < 0:
            return
        self._custom_course_pattern_table_internal_change = True
        try:
            lab_type = self._course_pattern_table_text(row, 4).upper()
            tag_item = self.custom_course_pattern_table.item(row, 6)
            if tag_item is None:
                tag_item = QTableWidgetItem("")
                self.custom_course_pattern_table.setItem(row, 6, tag_item)
            if lab_type == "SPECIAL":
                if not str(tag_item.text()).strip():
                    tag_item.setText("LAB1")
            else:
                tag_item.setText("")
        finally:
            self._custom_course_pattern_table_internal_change = False

    def _reset_custom_course_pattern_table(self) -> None:
        existing: Dict[int, Dict[str, Any]] = {}
        if not hasattr(self, "custom_course_pattern_table"):
            return
        for row in range(self.custom_course_pattern_table.rowCount()):
            cid_item = self.custom_course_pattern_table.item(row, 0)
            if cid_item is None:
                continue
            try:
                c_id = int(str(cid_item.text()).strip())
            except Exception:
                continue
            existing[c_id] = {
                "lecture_count": self.custom_course_pattern_table.item(row, 2).text()
                if self.custom_course_pattern_table.item(row, 2) is not None
                else "12",
                "tutorial_count": self.custom_course_pattern_table.item(row, 3).text()
                if self.custom_course_pattern_table.item(row, 3) is not None
                else "12",
                "lab_type": self._course_pattern_table_text(row, 4).upper() or "NONE",
                "lab_duration": self.custom_course_pattern_table.item(row, 5).text()
                if self.custom_course_pattern_table.item(row, 5) is not None
                else "2",
                "lab_tag": self.custom_course_pattern_table.item(row, 6).text()
                if self.custom_course_pattern_table.item(row, 6) is not None
                else "",
            }

        total = self._effective_custom_total_courses()
        names = self._parse_csv_names(self.custom_course_names_edit.text())
        was_sorting = self.custom_course_pattern_table.isSortingEnabled()
        self.custom_course_pattern_table.setSortingEnabled(False)
        self.custom_course_pattern_table.blockSignals(True)
        self._custom_course_pattern_table_internal_change = True
        self.custom_course_pattern_table.setRowCount(total)
        for row in range(total):
            c_id = row + 1
            name = names[row % len(names)] if names else f"Course-{c_id}"
            prev = existing.get(c_id, {})
            lec = str(prev.get("lecture_count", "12"))
            tut = str(prev.get("tutorial_count", "12"))
            lab_type = str(prev.get("lab_type", "NONE")).upper()
            lab_dur = str(prev.get("lab_duration", "2"))
            lab_tag = str(prev.get("lab_tag", ""))
            if lab_type not in COURSE_LAB_TYPE_CHOICES:
                lab_type = "NONE"
            self.custom_course_pattern_table.setItem(row, 0, self._make_locked_item(str(c_id)))
            self.custom_course_pattern_table.setItem(row, 1, self._make_locked_item(name))
            self.custom_course_pattern_table.setItem(row, 2, QTableWidgetItem(lec))
            self.custom_course_pattern_table.setItem(row, 3, QTableWidgetItem(tut))
            self._set_course_lab_type_cell(row, lab_type)
            self.custom_course_pattern_table.setItem(row, 5, QTableWidgetItem(lab_dur))
            self.custom_course_pattern_table.setItem(
                row,
                6,
                QTableWidgetItem(lab_tag if lab_type == "SPECIAL" else ""),
            )
        self._custom_course_pattern_table_internal_change = False
        self.custom_course_pattern_table.blockSignals(False)
        self.custom_course_pattern_table.setSortingEnabled(was_sorting)

    def _on_custom_program_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._custom_program_table_internal_change:
            return
        if item is None:
            return
        if item.column() not in (1, 2, 3):
            return
        self._custom_program_table_internal_change = True
        try:
            try:
                val = max(1, int(str(item.text()).strip()))
            except Exception:
                if item.column() == 1:
                    val = int(self.custom_groups_per_program_spin.value())
                else:
                    val = int(self.custom_courses_per_program_spin.value())
            item.setText(str(val))
            if item.column() == 2:
                cpg_item = self.custom_program_table.item(item.row(), 3)
                if cpg_item is not None:
                    try:
                        cpg = max(1, int(str(cpg_item.text()).strip()))
                    except Exception:
                        cpg = int(val)
                    cpg_item.setText(str(min(int(val), int(cpg))))
            elif item.column() == 3:
                courses_item = self.custom_program_table.item(item.row(), 2)
                if courses_item is not None:
                    try:
                        courses = max(1, int(str(courses_item.text()).strip()))
                    except Exception:
                        courses = int(self.custom_courses_per_program_spin.value())
                    item.setText(str(min(int(courses), int(val))))
        finally:
            self._custom_program_table_internal_change = False
        self._reset_custom_course_pattern_table()
        self._refresh_staff_course_picker()

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
            if col == 1:
                room_type = self._room_table_text(row, 1).upper()
                tags_item = self.custom_room_table.item(row, 4)
                if tags_item is not None:
                    if room_type != "SPECIALIZED_LAB":
                        tags_item.setText("")
                    elif not str(tags_item.text()).strip():
                        tags_item.setText("LAB1")
            if col == 2:
                cat = self._room_table_text(row, 2).upper()
                if cat in ROOM_CATEGORY_CAPACITY:
                    cap_item.setText(str(ROOM_CATEGORY_CAPACITY[cat]))
            elif col == 3:
                try:
                    cap = max(1, int(str(cap_item.text()).strip()))
                except Exception:
                    cap = ROOM_CATEGORY_CAPACITY["MEDIUM"]
                    cap_item.setText(str(cap))
                inferred_cat = self._infer_room_category(cap)
                cat_item.setText(inferred_cat)
                cat_combo = self.custom_room_table.cellWidget(row, 2)
                if isinstance(cat_combo, QComboBox):
                    idx = cat_combo.findText(inferred_cat)
                    if idx >= 0:
                        cat_combo.setCurrentIndex(idx)
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

    @staticmethod
    def _parse_csv_names(raw: str) -> List[str]:
        out: List[str] = []
        for token in str(raw).split(","):
            name = token.strip()
            if name:
                out.append(name)
        return out

    def _refresh_staff_course_picker(self, *_args: Any) -> None:
        self.staff_course_picker_combo.clear()
        total = self._effective_custom_total_courses()
        names = self._parse_csv_names(self.custom_course_names_edit.text())
        for c_id in range(1, max(1, total) + 1):
            if names:
                course_name = names[(c_id - 1) % len(names)]
                label = f"{c_id}: {course_name}"
            else:
                label = f"{c_id}: C{c_id:03d}"
            self.staff_course_picker_combo.addItem(label, int(c_id))

    def _on_add_course_to_selected_staff(self) -> None:
        row = self.custom_staff_table.currentRow()
        if row < 0:
            self.set_status("Select a staff row first")
            return
        course_id = self.staff_course_picker_combo.currentData()
        if course_id is None:
            return
        item = self.custom_staff_table.item(int(row), 2)
        if item is None:
            item = QTableWidgetItem("")
            self.custom_staff_table.setItem(int(row), 2, item)
        existing = self._parse_csv_ints(item.text())
        if int(course_id) not in existing:
            existing.append(int(course_id))
            existing = sorted(set(existing))
            item.setText(",".join(str(v) for v in existing))

    def _collect_custom_generation_config(self) -> Dict[str, Any]:
        prof_course_map: Dict[int, List[int]] = {}
        ta_course_map: Dict[int, List[int]] = {}
        prof_days: Dict[int, List[str]] = {}
        ta_days: Dict[int, List[str]] = {}
        program_overrides: List[Dict[str, Any]] = []
        course_patterns: List[Dict[str, Any]] = []
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
            cap_item = self.custom_room_table.item(row, 3)
            tags_item = self.custom_room_table.item(row, 4)
            name = str(name_item.text()).strip() if name_item else f"Room-{row + 1}"
            room_type = self._room_table_text(row, 1).upper() or "LECTURE"
            category = self._room_table_text(row, 2).upper() or "MEDIUM"
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

        for row in range(self.custom_program_table.rowCount()):
            pid_item = self.custom_program_table.item(row, 0)
            groups_item = self.custom_program_table.item(row, 1)
            courses_item = self.custom_program_table.item(row, 2)
            cpg_item = self.custom_program_table.item(row, 3)
            try:
                pid = int(str(pid_item.text()).strip()) if pid_item is not None else row + 1
                groups = max(1, int(str(groups_item.text()).strip())) if groups_item is not None else int(self.custom_groups_per_program_spin.value())
                courses = max(1, int(str(courses_item.text()).strip())) if courses_item is not None else int(self.custom_courses_per_program_spin.value())
                courses_per_group = max(1, int(str(cpg_item.text()).strip())) if cpg_item is not None else courses
            except Exception:
                continue
            program_overrides.append(
                {
                    "program_id": int(pid),
                    "groups": int(groups),
                    "courses": int(courses),
                    "courses_per_group": min(int(courses), int(courses_per_group)),
                }
            )

        for row in range(self.custom_course_pattern_table.rowCount()):
            cid_item = self.custom_course_pattern_table.item(row, 0)
            lec_item = self.custom_course_pattern_table.item(row, 2)
            tut_item = self.custom_course_pattern_table.item(row, 3)
            dur_item = self.custom_course_pattern_table.item(row, 5)
            tag_item = self.custom_course_pattern_table.item(row, 6)
            try:
                c_id = int(str(cid_item.text()).strip()) if cid_item is not None else row + 1
                lecture_count = int(str(lec_item.text()).strip()) if lec_item is not None else 12
                tutorial_count = int(str(tut_item.text()).strip()) if tut_item is not None else 12
                lab_duration = int(str(dur_item.text()).strip()) if dur_item is not None else 2
            except Exception:
                continue
            lab_type = self._course_pattern_table_text(row, 4).upper() or "NONE"
            lab_tag = str(tag_item.text()).strip().upper() if tag_item is not None else ""
            course_patterns.append(
                {
                    "course_id": int(c_id),
                    "lecture_count": int(lecture_count),
                    "tutorial_count": int(tutorial_count),
                    "lab_type": str(lab_type),
                    "lab_duration": int(lab_duration),
                    "lab_tag": str(lab_tag),
                }
            )

        return {
            "num_programs": int(self.custom_programs_spin.value()),
            "groups_per_program": int(self.custom_groups_per_program_spin.value()),
            "courses_per_program": int(self.custom_courses_per_program_spin.value()),
            "program_overrides": program_overrides,
            "course_patterns": course_patterns,
            "course_names": self._parse_csv_names(self.custom_course_names_edit.text()),
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
        controls: List[Any] = [
            self.hard_week1_cb,
            self.hard_block_prof_cb,
            self.hard_staff_daily_cb,
            self.hard_staff_weekly_cb,
            self.hard_room_availability_cb,
            *self.soft_weight_spins.values(),
        ]
        for control in controls:
            control.blockSignals(True)
        self.hard_week1_cb.setChecked(hard["week1_lectures_only"])
        self.hard_block_prof_cb.setChecked(hard["enforce_block_professor_rules"])
        self.hard_staff_daily_cb.setChecked(hard["enforce_staff_daily_caps"])
        self.hard_staff_weekly_cb.setChecked(hard["enforce_staff_weekly_caps"])
        self.hard_room_availability_cb.setChecked(hard["enforce_room_availability"])
        for key, spin in self.soft_weight_spins.items():
            spin.setValue(int(soft.get(key, spin.value())))
        for control in controls:
            control.blockSignals(False)

    def on_apply_constraints_to_instance(self) -> None:
        if self.inst is None:
            self.set_status("Generate or load an instance first")
            return
        self._apply_constraint_settings(self.inst)
        self.update_quality_summary()
        self.set_status("Constraint settings applied to current instance")

    def on_constraint_controls_changed(self, *_args: Any) -> None:
        if self.inst is None:
            return
        try:
            self._apply_constraint_settings(self.inst)
            if self.current_schedule:
                self.update_quality_summary()
                self.update_table()
        except Exception:
            traceback.print_exc()
            self.set_status("Failed to apply constraints from controls")

    def _on_mode_changed(self) -> None:
        if self.mode_combo.currentText() == "custom":
            self.workspace_tabs.setCurrentIndex(1)

    # ----- helpers -----

    def set_status(self, text: str):
        self._status_full_text = str(text)
        self._refresh_status_label()
        QApplication.processEvents()

    def _refresh_status_label(self) -> None:
        full = str(getattr(self, "_status_full_text", "") or "")
        if not hasattr(self, "status_label"):
            return
        self.status_label.setToolTip(full)
        try:
            width = max(120, int(self.status_label.width()) - 10)
            shown = self.status_label.fontMetrics().elidedText(
                full, Qt.TextElideMode.ElideRight, width
            )
            self.status_label.setText(shown)
        except Exception:
            self.status_label.setText(full)

    def set_busy(self, busy: bool):
        enable = not busy
        for btn in [
            self.generate_button,
            self.solve_button,
            self.clear_locks_button,
            self.improve_button,
            self.stop_improve_button,
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
        self.workers_preset_combo.setEnabled(enable)
        self.workspace_tabs.setEnabled(enable)
        self.custom_reset_staff_btn.setEnabled(enable)
        self.custom_reset_rooms_btn.setEnabled(enable)
        self.custom_reset_programs_btn.setEnabled(enable)
        self.custom_reset_course_patterns_btn.setEnabled(enable)
        self.apply_constraints_btn.setEnabled(enable)
        # Keep stop available while a local improvement pass is running.
        if hasattr(self, "stop_improve_button"):
            self.stop_improve_button.setEnabled(bool(busy and self._improve_running))
        if enable:
            self._refresh_history_buttons()
            self._refresh_quick_actions()

    def _start_solve_progress(self) -> None:
        self._stop_solve_progress()
        self._solve_started_at = time.perf_counter()
        ctx = dict(self._solve_progress_context or {})
        phased = bool(ctx.get("phased", False))
        feasibility_seconds = float(ctx.get("feasibility_seconds", 0.0) or 0.0)
        improve_total_seconds = float(ctx.get("improve_total_seconds", 0.0) or 0.0)
        if phased:
            self._solve_expected_seconds = max(1.0, feasibility_seconds + improve_total_seconds)
        else:
            self._solve_expected_seconds = max(1.0, float(self.time_limit_spin.value()))
        self._solve_progress_percent = 0
        self._solve_attempt_started_at = None
        self._solve_progress_timer = QTimer(self)
        self._solve_progress_timer.setInterval(400)
        self._solve_progress_timer.timeout.connect(self._on_solve_progress_tick)
        self._solve_progress_timer.start()

    def _on_solve_progress_tick(self) -> None:
        if self.proc is None or self._solve_started_at is None:
            self._stop_solve_progress()
            return
        ctx = self._solve_progress_context or {}
        phased = bool(ctx.get("phased", False))
        attempt_idx = int(ctx.get("attempt", 1) or 1)
        expected_attempts = max(1, int(ctx.get("expected_attempts", 1) or 1))
        solve_share = 0.5 if phased else 1.0
        base_pct = int((max(0, attempt_idx - 1) / float(expected_attempts)) * (solve_share * 100.0))
        limit = float(ctx.get("attempt_limit_seconds", 0.0) or 0.0)
        if self._solve_attempt_started_at is not None and limit > 0:
            elapsed_attempt = max(0.0, time.perf_counter() - self._solve_attempt_started_at)
            frac_attempt = min(1.0, elapsed_attempt / max(1.0, limit))
            pct = int(base_pct + frac_attempt * ((solve_share * 100.0) / float(expected_attempts)))
        else:
            completed = max(0, int(ctx.get("completed_attempts", 0) or 0))
            pct = int((min(completed, expected_attempts) / float(expected_attempts)) * (solve_share * 100.0))
        phase_label = str(ctx.get("phase_label", "running"))
        self._update_solve_progress_status(pct, phase_label)

    def _update_solve_progress_status(self, pct: int, phase_label: str = "") -> None:
        pct_clamped = max(0, min(99, int(pct)))
        if pct_clamped < int(self._solve_progress_percent):
            pct_clamped = int(self._solve_progress_percent)
        self._solve_progress_percent = int(pct_clamped)
        detail = f" ({phase_label})" if str(phase_label).strip() else ""
        self._status_full_text = f"Solving... {int(self._solve_progress_percent)}%{detail}"
        self._refresh_status_label()

    def _stop_solve_progress(self) -> None:
        if self._solve_progress_timer is not None:
            self._solve_progress_timer.stop()
            self._solve_progress_timer.deleteLater()
        self._solve_progress_timer = None
        self._solve_started_at = None
        self._solve_expected_seconds = 0.0
        self._solve_progress_percent = 0
        self._solve_attempt_started_at = None
        self._solve_progress_context = {}
        self._solver_output_partial = ""

    def _expected_solver_attempts(self, *, phased: bool, room_mode: str, objective_on: bool) -> int:
        mode = str(room_mode)
        if phased:
            # Feasibility-first: room-mode attempt, then optional strict->greedy fallback.
            return 2 if mode == "cp_rooms" else 1
        attempts = 1
        if bool(objective_on):
            attempts += 1  # objective-off retry
        if mode == "cp_rooms":
            attempts += 1  # strict->greedy fallback
        return max(1, int(attempts))

    def _selected_worker_count(self) -> int:
        if hasattr(self, "workers_preset_combo") and self.workers_preset_combo is not None:
            data = self.workers_preset_combo.currentData()
            try:
                return max(1, min(64, int(data)))
            except Exception:
                pass
        return max(1, min(64, int(DEFAULT_CP_WORKERS)))

    def on_solver_output_ready(self) -> None:
        if self.proc is None:
            return
        try:
            chunk = bytes(self.proc.readAll()).decode("utf-8", errors="ignore")
        except Exception:
            return
        if not chunk:
            return
        self._solver_output_log += str(chunk)
        blob = self._solver_output_partial + str(chunk)
        lines = blob.splitlines()
        if blob and not blob.endswith("\n"):
            self._solver_output_partial = lines[-1] if lines else blob
            lines = lines[:-1]
        else:
            self._solver_output_partial = ""
        for raw in lines:
            line = str(raw).strip()
            if not line:
                continue
            if not line.startswith("[progress] "):
                continue
            payload = line[len("[progress] "):].strip()
            try:
                event = json.loads(payload)
            except Exception:
                continue
            if isinstance(event, dict):
                self._handle_solver_progress_event(event)

    def _handle_solver_progress_event(self, event: Dict[str, Any]) -> None:
        kind = str(event.get("event", "")).strip().lower()
        ctx = dict(self._solve_progress_context or {})
        phased = bool(ctx.get("phased", event.get("phased", False)))
        expected_attempts = max(1, int(ctx.get("expected_attempts", 1) or 1))
        if kind == "run_start":
            mode = str(event.get("room_mode", ctx.get("room_mode", "")))
            objective = bool(event.get("use_objective", ctx.get("objective_on", False)))
            phased = bool(event.get("phased", phased))
            expected_attempts = self._expected_solver_attempts(
                phased=bool(phased),
                room_mode=str(mode),
                objective_on=bool(objective),
            )
            ctx["phased"] = bool(phased)
            ctx["room_mode"] = str(mode)
            ctx["objective_on"] = bool(objective)
            ctx["expected_attempts"] = int(expected_attempts)
            ctx["completed_attempts"] = 0
            self._solve_progress_context = ctx
            return
        solve_share = 0.5 if phased else 1.0
        improve_share = 1.0 - solve_share

        if kind == "solve_attempt_start":
            attempt = max(1, int(event.get("attempt", 1) or 1))
            expected_attempts = max(expected_attempts, int(attempt))
            limit = event.get("limit_seconds")
            try:
                attempt_limit = float(limit) if limit is not None else float(self.time_limit_spin.value())
            except Exception:
                attempt_limit = float(self.time_limit_spin.value())
            ctx["attempt"] = int(attempt)
            ctx["expected_attempts"] = int(expected_attempts)
            ctx["completed_attempts"] = max(int(ctx.get("completed_attempts", 0) or 0), int(attempt - 1))
            ctx["attempt_limit_seconds"] = float(max(1.0, attempt_limit))
            mode = str(event.get("mode", ctx.get("room_mode", "")))
            objective = bool(event.get("objective", False))
            phase = "objective" if objective else "feasibility"
            mode_label = "strict cp_rooms" if mode == "cp_rooms" else "greedy"
            if mode == "greedy" and str(ctx.get("room_mode", "")) == "cp_rooms" and int(attempt) > 1:
                mode_label = "greedy fallback"
            ctx["phase_label"] = f"attempt {attempt}/{expected_attempts}: {mode_label} ({phase})"
            self._solve_progress_context = ctx
            self._solve_attempt_started_at = time.perf_counter()
            base_pct = int((max(0, attempt - 1) / float(expected_attempts)) * (solve_share * 100.0))
            self._update_solve_progress_status(base_pct, str(ctx.get("phase_label", "")))
            return

        if kind == "solve_attempt_done":
            attempt = max(1, int(event.get("attempt", ctx.get("attempt", 1)) or 1))
            expected_attempts = max(expected_attempts, int(attempt))
            ctx["attempt"] = int(attempt)
            ctx["expected_attempts"] = int(expected_attempts)
            ctx["completed_attempts"] = int(attempt)
            status = event.get("status")
            ctx["phase_label"] = f"attempt {attempt}/{expected_attempts} done (status {status})"
            self._solve_progress_context = ctx
            self._solve_attempt_started_at = None
            pct = int((min(attempt, expected_attempts) / float(expected_attempts)) * (solve_share * 100.0))
            self._update_solve_progress_status(pct, str(ctx.get("phase_label", "")))
            return

        if kind == "solve_fallback":
            from_mode = str(event.get("from_mode", "cp_rooms"))
            to_mode = str(event.get("to_mode", "greedy"))
            label = f"fallback: {from_mode} -> {to_mode}"
            ctx["phase_label"] = label
            self._solve_progress_context = ctx
            self._update_solve_progress_status(int(self._solve_progress_percent), label)
            return

        if kind == "improve_start":
            max_rounds = max(1, int(ctx.get("improve_max_rounds", event.get("max_rounds", 1)) or 1))
            ctx["phase_label"] = f"improve round 0/{max_rounds}"
            self._solve_progress_context = ctx
            self._update_solve_progress_status(
                int(solve_share * 100.0),
                str(ctx.get("phase_label", "improve round 0/1")),
            )
            return

        if kind == "improve_round":
            round_idx = max(0, int(event.get("round", 0) or 0))
            max_rounds = max(1, int(event.get("max_rounds", 1) or 1))
            elapsed = float(event.get("elapsed_seconds", 0.0) or 0.0)
            total = float(event.get("total_seconds", 0.0) or 0.0)
            frac_rounds = min(1.0, float(round_idx) / float(max_rounds))
            frac_time = min(1.0, elapsed / total) if total > 0 else 0.0
            frac = max(frac_rounds, frac_time)
            pct = int((solve_share + improve_share * frac) * 100.0)
            label = f"improve round {round_idx}/{max_rounds}"
            ctx["phase_label"] = label
            self._solve_progress_context = ctx
            self._update_solve_progress_status(pct, label)
            return

        if kind in {"improve_done", "run_done"}:
            self._update_solve_progress_status(99, "finalizing")

    def populate_weeks(self):
        self.week_combo.blockSignals(True)
        self.week_combo.clear()
        if self.inst is not None:
            for w in self.inst.weeks:
                self.week_combo.addItem(f"Week {w}", w)
        self.week_combo.blockSignals(False)

    def update_entities(self):
        try:
            if self.inst is None:
                self.entity_combo.clear()
                self.entity_combo.setEnabled(False)
                return

            view_type = self.view_type_combo.currentText()
            self.entity_combo.blockSignals(True)
            self.entity_combo.clear()

            if view_type == "Group":
                self.entity_combo.setEnabled(True)
                for g_id, g in self.inst.groups.items():
                    self.entity_combo.addItem(f"{g.name} (id {g_id})", g_id)
            elif view_type == "Staff":
                self.entity_combo.setEnabled(True)
                for s_id, s in self.inst.staff.items():
                    self.entity_combo.addItem(f"{s.name} (id {s_id})", s_id)
            elif view_type == "Room":
                self.entity_combo.setEnabled(True)
                for r_id, r in self.inst.rooms.items():
                    self.entity_combo.addItem(f"{r.name} (id {r_id})", r_id)
            else:
                self.entity_combo.setEnabled(False)
                self.entity_combo.addItem("All entities", "__ALL__")

            self.entity_combo.blockSignals(False)
            self.update_table()
        except Exception:
            traceback.print_exc()
            self.entity_combo.blockSignals(False)
            self.set_status("Failed to update view entities")

    def clear_table(self):
        self._render_empty_calendar(None, None)
        self._cell_activity_map = {}
        self._held_move_analysis_map = {}
        self.selected_cell_row = None
        self.selected_cell_col = None
        self.selected_activity_id = None
        self._refresh_quick_actions()
        self.quality_label.setText("")

    def _render_empty_calendar(
        self,
        days: List[str] | Tuple[str, ...] | None,
        slots_per_day: int | None,
        *,
        week_label: str = "Week -",
    ) -> None:
        render_days = list(days) if days else list(self.DEFAULT_PREVIEW_DAYS)
        render_slots = int(slots_per_day) if slots_per_day and int(slots_per_day) > 0 else int(self.DEFAULT_PREVIEW_SLOTS)
        self.table.clear()
        self.table.setRowCount(len(render_days))
        self.table.setColumnCount(render_slots)
        self.table.setVerticalHeaderLabels(render_days)
        self.table.setHorizontalHeaderLabels([f"S{idx + 1}" for idx in range(render_slots)])
        self._cell_activity_map = {}
        for row, day in enumerate(render_days):
            for col in range(render_slots):
                item = QTableWidgetItem("")
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                )
                item.setForeground(QBrush(QColor("#f5f5f5")))
                item.setToolTip(f"{week_label} | {day} S{col + 1}\nActivities: none")
                self.table.setItem(row, col, item)
                self._cell_activity_map[(row, col)] = []
        self._schedule_table_relayout()

    def _selected_cell_day_slot(self) -> Tuple[str, int] | None:
        if self.inst is None:
            return None
        if self.selected_cell_row is None or self.selected_cell_col is None:
            return None
        if not (0 <= int(self.selected_cell_row) < len(self.inst.days)):
            return None
        if not (0 <= int(self.selected_cell_col) < int(self.inst.slots_per_day)):
            return None
        return (self.inst.days[int(self.selected_cell_row)], int(self.selected_cell_col))

    def _show_held_targets_dialog(self) -> None:
        if self.inst is None or self.held_activity_id is None:
            self.set_status("No held activity")
            return
        week = self._current_week()
        if week is None:
            self.set_status("Select a week first")
            return
        analysis_map = self._build_held_move_analysis(week)
        valid_targets: List[str] = []
        for d in self.inst.days:
            for s in range(self.inst.slots_per_day):
                info = analysis_map.get((str(d), int(s)))
                if not info or not bool(info.get("ok", False)):
                    continue
                score_after = info.get("score_after")
                score_delta = info.get("score_delta")
                if isinstance(score_after, int) and isinstance(score_delta, int):
                    valid_targets.append(
                        f"{d} S{s + 1} | soft penalty {int(score_after)} "
                        f"(Δ {int(score_delta):+d}, {self._describe_penalty_delta(int(score_delta))})"
                    )
                else:
                    valid_targets.append(f"{d} S{s + 1}")
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

    def _refresh_quick_actions(self) -> None:
        has_inst = self.inst is not None
        week = self._current_week()
        selected_cell = self._selected_cell_day_slot()
        if has_inst and selected_cell and week is not None:
            day, slot = selected_cell
            selected_text = f"Selected: {day} S{int(slot) + 1} (Week {week})"
            self.selected_slot_label.setText(selected_text)
            self.selected_slot_label.setToolTip(selected_text)
        else:
            self.selected_slot_label.setText("Selected: none")
            self.selected_slot_label.setToolTip("Selected: none")

        selected_ids: List[int] = []
        if selected_cell and has_inst and week is not None:
            row = int(self.selected_cell_row) if self.selected_cell_row is not None else -1
            col = int(self.selected_cell_col) if self.selected_cell_col is not None else -1
            selected_ids = list(self._cell_activity_map.get((row, col), []))

        self.selected_activity_combo.blockSignals(True)
        self.selected_activity_combo.clear()
        for a_id in selected_ids:
            self.selected_activity_combo.addItem(self._activity_title(int(a_id)), int(a_id))
        if selected_ids:
            target_id = (
                int(self.selected_activity_id)
                if self.selected_activity_id is not None and int(self.selected_activity_id) in selected_ids
                else int(selected_ids[0])
            )
            idx = self.selected_activity_combo.findData(target_id)
            if idx >= 0:
                self.selected_activity_combo.setCurrentIndex(idx)
            self.selected_activity_id = target_id
        else:
            self.selected_activity_id = None
        self.selected_activity_combo.blockSignals(False)

        if self.held_activity_id is not None and self.held_activity_id in self.current_schedule:
            held_id = int(self.held_activity_id)
            held_info = self.current_schedule.get(held_id, {})
            held_day = str(held_info.get("day", "?"))
            held_slot = int(held_info.get("slot", 0)) + 1
            compact = f"Held: A{held_id} ({held_day} S{held_slot})"
            self.held_slot_label.setText(compact)
            self.held_slot_label.setToolTip(self._activity_title(held_id))
        else:
            self.held_slot_label.setText("Held: none")
            self.held_slot_label.setToolTip("Held: none")

        has_selected_activity = self.selected_activity_id is not None
        has_held = (
            self.held_activity_id is not None
            and self.held_activity_id in self.current_schedule
        )
        has_selected_slot = selected_cell is not None

        self.selected_activity_combo.setEnabled(bool(selected_ids))
        self.quick_edit_btn.setEnabled(has_selected_activity)
        self.quick_hold_btn.setEnabled(has_selected_activity)
        self.quick_time_lock_btn.setEnabled(has_selected_activity)
        self.quick_room_lock_btn.setEnabled(has_selected_activity)
        self.quick_move_btn.setEnabled(has_held and has_selected_slot)
        self.quick_swap_btn.setEnabled(
            has_held and has_selected_activity and int(self.held_activity_id) != int(self.selected_activity_id)
        )
        self.quick_targets_btn.setEnabled(has_held)
        self.quick_release_btn.setEnabled(has_held)
        if not self._live_improve_mode:
            self._defer_layout_stabilization()

    def on_table_cell_clicked(self, row: int, col: int) -> None:
        try:
            self.selected_cell_row = int(row)
            self.selected_cell_col = int(col)
            self._refresh_quick_actions()
        except Exception:
            traceback.print_exc()
            self.set_status("Failed to select cell")

    def on_selected_activity_changed(self, _idx: int = -1) -> None:
        data = self.selected_activity_combo.currentData()
        self.selected_activity_id = int(data) if data is not None else None
        self._refresh_quick_actions()

    def on_quick_edit_selected(self) -> None:
        if self.selected_activity_id is None:
            return
        if self.selected_cell_row is None or self.selected_cell_col is None:
            return
        self.on_cell_double_clicked(int(self.selected_cell_row), int(self.selected_cell_col))
        self._refresh_quick_actions()

    def on_quick_hold_selected(self) -> None:
        if self.selected_activity_id is None:
            return
        self._set_held_activity(int(self.selected_activity_id))
        self._refresh_quick_actions()

    def on_quick_move_held_here(self) -> None:
        cell = self._selected_cell_day_slot()
        if cell is None:
            return
        day, slot = cell
        self._attempt_move_held_to(str(day), int(slot))
        self._refresh_quick_actions()

    def on_quick_swap_held_with_selected(self) -> None:
        if self.held_activity_id is None or self.selected_activity_id is None:
            return
        if int(self.held_activity_id) == int(self.selected_activity_id):
            self.set_status("Held and selected activity are the same")
            return
        ok, reason = self._attempt_swap_timeslots(
            int(self.held_activity_id), int(self.selected_activity_id)
        )
        if not ok:
            QMessageBox.warning(self, "Swap blocked", reason)
        self._refresh_quick_actions()

    def on_quick_toggle_time_lock(self) -> None:
        if self.selected_activity_id is None:
            return
        self._toggle_activity_lock(int(self.selected_activity_id), time_lock=True)
        self._refresh_quick_actions()

    def on_quick_toggle_room_lock(self) -> None:
        if self.selected_activity_id is None:
            return
        self._toggle_activity_lock(int(self.selected_activity_id), time_lock=False)
        self._refresh_quick_actions()

    def on_quick_show_held_targets(self) -> None:
        self._show_held_targets_dialog()
        self._refresh_quick_actions()

    def on_quick_release_held(self) -> None:
        self._clear_held_activity()
        self._refresh_quick_actions()

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

    def _validate_schedule_hard_errors(
        self,
        schedule: Dict[int, Dict[str, Any]],
        *,
        require_all: bool = True,
    ) -> List[str]:
        if self.inst is None or not schedule:
            return []
        try:
            return validate_schedule_against_instance(
                self.inst,
                schedule,
                strict_rooms=True,
                require_all_activities=bool(require_all),
            )
        except Exception:
            return []

    def _collect_conflict_errors(self) -> List[str]:
        return self._validate_schedule_hard_errors(
            self.current_schedule, require_all=True
        )

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

    def _set_manual_highlight_base(
        self, schedule: Dict[int, Dict[str, Any]] | None = None
    ) -> None:
        if schedule is None:
            self._manual_highlight_base_schedule = {}
            return
        self._manual_highlight_base_schedule = {
            int(a_id): dict(info)
            for a_id, info in schedule.items()
            if isinstance(info, dict)
        }

    def _compute_soft_penalty(self, schedule: Dict[int, Dict[str, Any]]) -> int | None:
        if self.inst is None:
            return None
        try:
            return int(LocalSearchImprover(self.inst).compute_soft_penalty(schedule))
        except Exception:
            return None

    @staticmethod
    def _describe_penalty_delta(delta: int) -> str:
        if int(delta) < 0:
            return f"gain {abs(int(delta))}"
        if int(delta) > 0:
            return f"loss {int(delta)}"
        return "no change"

    def _format_score_status_suffix(self, before: int | None, after: int | None) -> str:
        if before is None or after is None:
            return ""
        delta = int(after) - int(before)
        return (
            f" | soft penalty {int(before)} -> {int(after)} "
            f"(Δ {delta:+d}, {self._describe_penalty_delta(delta)})"
        )

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
        view_type = self.view_type_combo.currentText()
        data = self.entity_combo.currentData()
        if data is None and view_type != "All":
            return []
        entity_id = int(data) if data is not None and view_type != "All" else None
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
            if view_type == "Group" and entity_id is not None and entity_id not in info["group_ids"]:
                continue
            if view_type == "Staff" and entity_id is not None and entity_id != int(info["staff_id"]):
                continue
            if view_type == "Room" and entity_id is not None and entity_id != int(info["room_id"]):
                continue
            act_ids.append(int(a_id))
        return act_ids

    def _is_activity_changed_from_base(self, a_id: int) -> bool:
        current = self.current_schedule.get(int(a_id))
        base = self._manual_highlight_base_schedule.get(int(a_id))
        if current is None:
            return False
        if base is None:
            return True
        for key in ("week", "day", "slot", "room_id", "staff_id"):
            if current.get(key) != base.get(key):
                return True
        return False

    def _compute_conflicting_activity_ids(
        self, schedule: Dict[int, Dict[str, Any]]
    ) -> Set[int]:
        out: Set[int] = set()
        if self.inst is None:
            return out
        try:
            if schedule is self.current_schedule:
                errors = self._collect_conflict_errors()
            else:
                errors = validate_schedule_against_instance(
                    self.inst, schedule, strict_rooms=True, require_all_activities=True
                )
        except Exception:
            errors = []
        for err in errors:
            for match in re.findall(r"\bA(\d+)\b", str(err)):
                try:
                    out.add(int(match))
                except Exception:
                    continue
        return out

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
        info = self.current_schedule[a_id]
        if self.inst is not None and str(info["day"]) in self.inst.days:
            self.selected_cell_row = self.inst.days.index(str(info["day"]))
            self.selected_cell_col = int(info["slot"])
            self.selected_activity_id = int(a_id)
        self.update_table()
        self._refresh_quick_actions()
        self.set_status(
            f"Holding {self._activity_title(a_id)}. Hover slots to inspect conflicts, then use 'Move Held Here'."
        )

    def _clear_held_activity(self) -> None:
        if self.held_activity_id is None:
            return
        held = self.held_activity_id
        self.held_activity_id = None
        self.update_table()
        self._refresh_quick_actions()
        self.set_status(f"Released held activity A{held}")

    def _collect_held_target_map(
        self,
        week: int,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
    ) -> Dict[Tuple[str, int], bool]:
        analysis_map = self._build_held_move_analysis(
            week, schedule_override=schedule_override
        )
        return {
            key: bool(info.get("ok", False)) for key, info in analysis_map.items()
        }

    def _build_held_move_analysis(
        self,
        week: int,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
    ) -> Dict[Tuple[str, int], Dict[str, Any]]:
        inst = self.inst
        if inst is None or self.held_activity_id is None:
            return {}
        schedule = self.current_schedule if schedule_override is None else schedule_override
        a_id = int(self.held_activity_id)
        info = schedule.get(a_id)
        if info is None or int(info["week"]) != int(week):
            return {}
        current_day = str(info["day"])
        current_slot = int(info["slot"])
        room_id = int(info["room_id"])
        staff_id = int(info["staff_id"])
        base_penalty = self._compute_soft_penalty(schedule)
        analysis: Dict[Tuple[str, int], Dict[str, Any]] = {}
        for day in inst.days:
            for slot in range(inst.slots_per_day):
                ok, reason = self.check_move(
                    a_id,
                    str(day),
                    int(slot),
                    room_id,
                    staff_id,
                    schedule_override=schedule,
                )
                day_slot = (str(day), int(slot))
                details: Dict[str, Any] = {
                    "ok": bool(ok),
                    "reason": "",
                    "conflicts": [],
                    "score_current": base_penalty,
                    "score_after": None,
                    "score_delta": None,
                }
                if ok:
                    if base_penalty is not None:
                        if str(day) == current_day and int(slot) == current_slot:
                            target_penalty = int(base_penalty)
                        else:
                            moved = self._clone_schedule(schedule)
                            moved[a_id]["day"] = str(day)
                            moved[a_id]["slot"] = int(slot)
                            target_penalty = self._compute_soft_penalty(moved)
                        if target_penalty is not None:
                            details["score_after"] = int(target_penalty)
                            details["score_delta"] = int(target_penalty) - int(base_penalty)
                    analysis[day_slot] = details
                    continue
                details["reason"] = str(reason or "")
                details["conflicts"] = self._find_move_conflicts(
                    a_id,
                    str(day),
                    int(slot),
                    room_id,
                    staff_id,
                    schedule_override=schedule,
                )
                analysis[day_slot] = details
        return analysis

    def _build_cell_tooltip(
        self,
        *,
        row: int,
        col: int,
        ids: List[int],
        week: int,
        day: str,
        held_id: int | None,
        held_week_ok: bool,
    ) -> str:
        lines: List[str] = [f"Week {week} | {day} S{int(col) + 1}"]
        if ids:
            lines.append("Activities:")
            for a_id in ids[:12]:
                lines.append(f"  - {self._activity_title(int(a_id))}")
            extra = len(ids) - 12
            if extra > 0:
                lines.append(f"  - ... +{extra} more")
        else:
            lines.append("Activities: none")

        if held_week_ok and held_id is not None:
            if held_id in ids:
                lines.append("")
                lines.append("Held activity origin slot.")
            else:
                analysis = self._held_move_analysis_map.get((str(day), int(col)))
                if analysis is not None:
                    lines.append("")
                    if bool(analysis.get("ok", False)):
                        lines.append("Hold move: valid target")
                        current_score = analysis.get("score_current")
                        target_score = analysis.get("score_after")
                        score_delta = analysis.get("score_delta")
                        if isinstance(current_score, int):
                            lines.append(f"Current soft penalty: {int(current_score)}")
                        if isinstance(target_score, int) and isinstance(score_delta, int):
                            lines.append(
                                f"If moved here: {int(target_score)} "
                                f"(Δ {int(score_delta):+d}, {self._describe_penalty_delta(int(score_delta))})"
                            )
                    else:
                        lines.append(
                            f"Hold move: blocked ({str(analysis.get('reason') or 'constraint violation')})"
                        )
                        current_score = analysis.get("score_current")
                        if isinstance(current_score, int):
                            lines.append(f"Current soft penalty: {int(current_score)}")
                        conflicts = analysis.get("conflicts") or []
                        if conflicts:
                            lines.append("Conflicts if moved here:")
                            for conflict in conflicts[:8]:
                                b_id = int(conflict.get("activity_id", -1))
                                reasons = ",".join(conflict.get("reasons", []))
                                lines.append(f"  - A{b_id} [{reasons}]")
                            extra = len(conflicts) - 8
                            if extra > 0:
                                lines.append(f"  - ... +{extra} more")

        return "\n".join(lines)

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
        before_penalty = self._compute_soft_penalty(self.current_schedule)
        after_penalty = self._compute_soft_penalty(schedule)
        self.current_schedule = {a_id: info.copy() for a_id, info in schedule.items()}
        self._sync_instance_staff_from_schedule(self.current_schedule)
        self._sync_locks_to_instance()
        self.update_table()
        self.update_quality_summary()
        self.set_status(status + self._format_score_status_suffix(before_penalty, after_penalty))
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
        errors = validate_schedule_against_instance(
            self.inst, schedule, strict_rooms=True, require_all_activities=True
        )
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
        errors = validate_schedule_against_instance(
            self.inst, schedule, strict_rooms=True, require_all_activities=True
        )
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

    def _commit_held_plan_move(
        self,
        held_id: int,
        target_day: str,
        target_slot: int,
        schedule: Dict[int, Dict[str, Any]],
        *,
        forced: bool = False,
    ) -> None:
        errors: List[str] = []
        try:
            errors = validate_schedule_against_instance(
                self.inst, schedule, strict_rooms=True, require_all_activities=True
            )
        except Exception:
            errors = []

        self._push_undo_state()
        self._touch_time_lock_if_present(held_id, str(target_day), int(target_slot))
        title = self._activity_title(held_id, schedule)
        status = f"Moved {title}"
        if forced:
            status += " (forced)"
        if errors:
            status += f" with {len(errors)} hard conflict(s)"
        self._commit_schedule(schedule, status)
        if forced and errors:
            QMessageBox.warning(
                self,
                "Forced move applied",
                "Move committed with unresolved hard conflicts.\n"
                "Use Conflicts to inspect and resolve remaining overlaps.",
            )

    def _resolve_held_move_conflicts(
        self,
        held_id: int,
        target_day: str,
        target_slot: int,
    ) -> None:
        info = self.current_schedule.get(int(held_id))
        if info is None or self.inst is None:
            return

        origin_day = str(info["day"])
        origin_slot = int(info["slot"])
        room_id = int(info["room_id"])
        staff_id = int(info["staff_id"])

        planned = self._clone_schedule()
        planned[held_id]["day"] = str(target_day)
        planned[held_id]["slot"] = int(target_slot)
        step_note = ""
        dlg: MoveConflictDialog | None = None

        while True:
            conflicts = self._find_move_conflicts(
                held_id,
                str(target_day),
                int(target_slot),
                room_id,
                staff_id,
                schedule_override=planned,
            )
            if not conflicts:
                self._commit_held_plan_move(
                    held_id, str(target_day), int(target_slot), planned, forced=False
                )
                return

            relocation_options: Dict[int, List[Tuple[str, int]]] = {}
            for conflict in conflicts:
                b_id = int(conflict["activity_id"])
                b_info = planned.get(b_id)
                if b_info is None:
                    relocation_options[b_id] = []
                    continue
                relocation_options[b_id] = self._find_relocation_slots(
                    b_id,
                    schedule_override=planned,
                    exclude_starts={
                        (str(b_info["day"]), int(b_info["slot"])),
                        (str(target_day), int(target_slot)),
                    },
                )

            if dlg is None:
                dlg = MoveConflictDialog(
                    self,
                    self.inst,
                    planned,
                    held_id,
                    str(target_day),
                    int(target_slot),
                    conflicts,
                    relocation_options,
                )
            else:
                dlg.update_state(
                    conflicts,
                    relocation_options,
                    message=step_note
                    or f"{len(conflicts)} conflict(s) remain for held move.",
                )

            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            decision = dlg.get_decision()
            if not decision:
                return

            kind = str(decision[0])
            if kind == "force":
                self._commit_held_plan_move(
                    held_id, str(target_day), int(target_slot), planned, forced=True
                )
                return

            if kind == "swap":
                b_id = int(decision[1])
                b_info = planned.get(b_id)
                if b_info is None:
                    step_note = f"Selected conflict A{b_id} no longer exists."
                    continue
                prev_day = str(b_info["day"])
                prev_slot = int(b_info["slot"])
                b_info["day"] = str(origin_day)
                b_info["slot"] = int(origin_slot)
                ok_b, reason_b = self.check_move(
                    int(b_id),
                    str(b_info["day"]),
                    int(b_info["slot"]),
                    int(b_info["room_id"]),
                    int(b_info["staff_id"]),
                    schedule_override=planned,
                )
                if not ok_b:
                    b_info["day"] = prev_day
                    b_info["slot"] = prev_slot
                    step_note = f"Swap blocked for A{b_id}: {reason_b}"
                else:
                    step_note = (
                        f"Swapped conflict A{b_id} to held activity origin "
                        f"({origin_day} S{origin_slot + 1})."
                    )
                continue

            if kind == "relocate":
                b_id = int(decision[1])
                b_day = str(decision[2])
                b_slot = int(decision[3])
                b_info = planned.get(b_id)
                if b_info is None:
                    step_note = f"Selected conflict A{b_id} no longer exists."
                    continue
                prev_day = str(b_info["day"])
                prev_slot = int(b_info["slot"])
                b_info["day"] = str(b_day)
                b_info["slot"] = int(b_slot)
                ok_b, reason_b = self.check_move(
                    int(b_id),
                    str(b_day),
                    int(b_slot),
                    int(b_info["room_id"]),
                    int(b_info["staff_id"]),
                    schedule_override=planned,
                )
                if not ok_b:
                    b_info["day"] = prev_day
                    b_info["slot"] = prev_slot
                    step_note = f"Relocation blocked for A{b_id}: {reason_b}"
                else:
                    step_note = f"Relocated conflict A{b_id} to {b_day} S{b_slot + 1}."
                continue

            step_note = f"Unknown action: {kind}"

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

        self._resolve_held_move_conflicts(held_id, str(target_day), int(target_slot))

    def on_table_context_menu(self, pos) -> None:
        try:
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
            act_toggle_time_lock = None
            act_toggle_room_lock = None
            act_swap_here = None
            if act_ids:
                act_hold = menu.addAction("Hold activity...")
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
                self._show_held_targets_dialog()
                return
            if chosen == act_clear_held:
                self._clear_held_activity()
                return
            if chosen == act_show_conflicts:
                self.on_show_conflicts()
                return
        except Exception:
            traceback.print_exc()
            self.set_status("Failed to open context actions")

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
            f"- Workers: {self.workers_preset_combo.currentText()}",
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
        self._set_manual_highlight_base({})
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

        self.proc = QProcess(self)
        if getattr(sys, "frozen", False):
            # In packaged mode, reuse the same executable in CLI-worker mode.
            self.proc.setProgram(sys.executable)
            self.proc.setArguments(
                ["--engine-cli", self.tmp_inst_path, self.tmp_res_path]
            )
        else:
            python_exe = sys.executable
            base_dir = os.path.dirname(os.path.abspath(__file__))
            solver_script = os.path.normpath(
                os.path.join(base_dir, "..", "core", "engine_cli.py")
            )
            self.proc.setProgram(python_exe)
            self.proc.setArguments(
                [solver_script, self.tmp_inst_path, self.tmp_res_path]
            )
        env_map = os.environ.copy()
        time_limit_seconds = float(self.time_limit_spin.value())
        objective_on = self.objective_cb.isChecked()
        room_mode = "cp_rooms" if self.room_mode_combo.currentIndex() == 0 else "greedy"
        env_map["TT_ROOM_MODE"] = room_mode
        env_map["TT_TIME_LIMIT"] = str(self.time_limit_spin.value())
        env_map["TT_CP_WORKERS"] = str(self._selected_worker_count())
        env_map["TT_USE_OBJECTIVE"] = "1" if objective_on else "0"
        phased_enabled = bool(objective_on)
        feasibility_seconds = float(time_limit_seconds)
        improve_budget_seconds = 0.0
        improve_max_rounds = 0
        if objective_on:
            # Feasibility-first then iterative improvement within the total solve budget.
            feasibility_seconds, improve_budget_seconds = self._split_phased_budget(time_limit_seconds)
            env_map["TT_PHASED_SOLVE"] = "1"
            env_map["TT_FEASIBILITY_SECONDS"] = f"{feasibility_seconds:g}"
            env_map["TT_IMPROVE_TOTAL_SECONDS"] = f"{improve_budget_seconds:g}"
            env_map["TT_IMPROVE_SLICE_SECONDS"] = "5"
            env_map["TT_IMPROVE_ITERS_PER_SLICE"] = "1200"
            env_map["TT_IMPROVE_MAX_ROUNDS"] = "12"
            improve_max_rounds = 12
        else:
            env_map["TT_PHASED_SOLVE"] = "0"
            env_map["TT_IMPROVE_TOTAL_SECONDS"] = "0"
            phased_enabled = False
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
        self.proc.readyRead.connect(self.on_solver_output_ready)

        expected_attempts = self._expected_solver_attempts(
            phased=bool(phased_enabled),
            room_mode=room_mode,
            objective_on=bool(objective_on),
        )
        self._solve_progress_context = {
            "phased": bool(phased_enabled),
            "room_mode": str(room_mode),
            "objective_on": bool(objective_on),
            "expected_attempts": int(expected_attempts),
            "attempt": 1,
            "completed_attempts": 0,
            "attempt_limit_seconds": float(max(1.0, feasibility_seconds if phased_enabled else time_limit_seconds)),
            "feasibility_seconds": float(max(0.0, feasibility_seconds)),
            "improve_total_seconds": float(max(0.0, improve_budget_seconds)),
            "improve_max_rounds": int(max(0, improve_max_rounds)),
            "phase_label": "starting",
        }
        self._solver_output_log = ""
        self._solver_output_partial = ""

        self.set_busy(True)
        lock_count = len(self.locked_activities)
        self.set_status(
            "Solving in external process..."
            + (f" (locks={lock_count})" if lock_count else "")
        )
        self._start_solve_progress()
        self.proc.start()

    def on_solve(self):
        self._start_solver_process(keep_locks=False)

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
        self._set_manual_highlight_base(self.current_schedule)
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
                self.set_status(f"Conflict selected: A{int(activity_id)}")
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
        self._stop_solve_progress()
        output = str(self._solver_output_log or "")
        if self.proc is not None:
            try:
                output += self.proc.readAll().data().decode("utf-8", errors="ignore")
            except Exception:
                pass
        QMessageBox.critical(
            self, "Solver error", output or f"QProcess error: {error}"
        )
        self.proc = None
        self._solver_output_log = ""
        self.set_status("Solve error")

    def on_solver_finished(self, exit_code: int, exit_status):
        if self.proc is not None:
            try:
                self.on_solver_output_ready()
            except Exception:
                pass
        self._update_solve_progress_status(99, "finalizing")
        self.set_busy(False)
        self._stop_solve_progress()

        output = str(self._solver_output_log or "")
        if self.proc is not None:
            try:
                output += self.proc.readAll().data().decode("utf-8", errors="ignore")
            except Exception:
                pass
        self.proc = None
        self._solver_output_log = ""

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
            self._set_manual_highlight_base({})
            self.current_schedule = {}
            self.held_activity_id = None
            self._reset_history()
            self.clear_table()
            self.set_status(f"No feasible schedule (status {status})")
            msg = self._build_no_feasible_message(res, int(status))
            QMessageBox.information(self, "No feasible schedule", msg)
            return

        self.base_schedule = res.get("schedule", {})
        if not isinstance(self.base_schedule, dict):
            self.base_schedule = {}
        self.base_schedule = {
            int(a_id): dict(info)
            for a_id, info in self.base_schedule.items()
            if isinstance(info, dict)
        }
        base_hard_errors = self._validate_schedule_hard_errors(
            self.base_schedule, require_all=True
        )
        if base_hard_errors:
            self.base_schedule = {}
            self._set_manual_highlight_base({})
            self.current_schedule = {}
            self.held_activity_id = None
            self._reset_history()
            self.clear_table()
            self.set_status(
                f"Solve rejected: hard conflicts detected ({len(base_hard_errors)})"
            )
            sample = "\n".join(f"- {line}" for line in base_hard_errors[:12])
            QMessageBox.critical(
                self,
                "Invalid solve result",
                "The solver returned a schedule with hard conflicts and it was rejected.\n\n"
                f"Conflicts: {len(base_hard_errors)}\n\n"
                f"{sample}",
            )
            return

        self.current_schedule = {
            a_id: info.copy() for a_id, info in self.base_schedule.items()
        }
        self._set_manual_highlight_base(self.current_schedule)
        self.held_activity_id = None
        self._reset_history()
        attempts = self._format_solver_attempts(res)
        final_attempt = attempts[-1] if attempts else ""

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
                improved_hard_errors = self._validate_schedule_hard_errors(
                    improved, require_all=True
                )
                if improved_hard_errors:
                    self.set_status(
                        f"Solved (status {status}); post-solve improvement rejected "
                        f"({len(improved_hard_errors)} hard conflicts)."
                    )
                else:
                    after = ls.compute_soft_penalty(improved)
                    self.current_schedule = {
                        a_id: info.copy() for a_id, info in improved.items()
                    }
                    self._set_manual_highlight_base(self.current_schedule)
                    status_msg = (
                        f"Solved (status {status}), soft penalty {before} -> {after}"
                    )
                    if final_attempt:
                        status_msg += f" | {final_attempt}"
                    self.set_status(status_msg)
        except Exception:
            traceback.print_exc()
            status_msg = f"Solved (status {status}), local search skipped"
            if final_attempt:
                status_msg += f" | {final_attempt}"
            self.set_status(status_msg)

        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()

    def on_improve(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to improve")
            return

        total_iters = int(self.improve_runs_spin.value())
        original_schedule = {
            a_id: info.copy() for a_id, info in self.current_schedule.items()
        }

        try:
            self.set_busy(True)
            self._live_improve_mode = True
            self._improve_running = True
            self._improve_stop_requested = False
            self.stop_improve_button.setEnabled(True)
            ls = LocalSearchImprover(self.inst)
            best_schedule = {
                a_id: info.copy() for a_id, info in self.current_schedule.items()
            }
            base_pen = ls.compute_soft_penalty(best_schedule)
            best_pen = int(base_pen)

            # Dynamic best-as-base: each round starts from the latest accepted best schedule.
            round_iters = max(25, min(250, max(1, total_iters // 10)))
            max_seconds = self.ls_time_spin.value() or None
            round_seconds = None
            if max_seconds:
                round_seconds = min(2.0, max(0.25, float(max_seconds) / 8.0))

            self.set_status(f"Improving... 0% (target {total_iters} iters)")

            progress_every = 1
            render_interval_s = 0.45
            quality_interval_s = 0.35
            pump_interval = 20
            last_render_ts = 0.0
            last_quality_ts = 0.0
            total_done = 0
            round_idx = 0
            started_at = time.perf_counter()

            while total_done < total_iters:
                if self._improve_stop_requested:
                    break
                iter_budget = min(round_iters, total_iters - total_done)

                slice_budget = None
                if max_seconds:
                    elapsed = time.perf_counter() - started_at
                    remaining = float(max_seconds) - elapsed
                    if remaining <= 0:
                        break
                    slice_budget = min(float(round_seconds), remaining)
                round_idx += 1

                round_offset = total_done
                round_progress_done = 0

                def _progress_hook(
                    it_done: int,
                    round_best_pen: int,
                    cur_pen: int,
                    **kwargs: Any,
                ) -> None:
                    nonlocal last_render_ts, last_quality_ts, round_progress_done
                    if self._improve_stop_requested:
                        return
                    round_progress_done = max(round_progress_done, int(it_done))
                    global_iter = min(total_iters, round_offset + int(it_done))
                    pct_iter = float(global_iter) / max(1.0, float(total_iters))
                    pct_time = 0.0
                    if max_seconds:
                        elapsed_total = max(0.0, time.perf_counter() - started_at)
                        pct_time = min(1.0, float(elapsed_total) / max(1e-6, float(max_seconds)))
                    pct = int(min(99.0, max(float(pct_iter), float(pct_time)) * 100.0))
                    msg = (
                        f"Improving... {pct}% "
                        f"(iter {global_iter}/{total_iters}, best={round_best_pen}, current={cur_pen})"
                    )
                    self._status_full_text = msg
                    self._refresh_status_label()

                    now = time.perf_counter()
                    preview_snapshot = kwargs.get("best_schedule") or kwargs.get(
                        "current_schedule"
                    )
                    should_render = (
                        isinstance(preview_snapshot, dict)
                        and (
                            (now - last_render_ts) >= render_interval_s
                            or global_iter >= int(total_iters)
                        )
                    )
                    if should_render:
                        self.current_schedule = {
                            int(a_id): info.copy()
                            for a_id, info in preview_snapshot.items()
                        }
                        self.update_table()
                        last_render_ts = now
                        if (now - last_quality_ts) >= quality_interval_s or global_iter >= int(
                            total_iters
                        ):
                            self.update_quality_summary()
                            last_quality_ts = now
                        QApplication.processEvents()
                    elif global_iter % int(pump_interval) == 0:
                        QApplication.processEvents()

                candidate = ls.improve(
                    best_schedule,
                    iterations=iter_budget,
                    max_seconds=slice_budget,
                    progress_every=progress_every,
                    progress_hook=_progress_hook,
                    stop_hook=lambda: bool(self._improve_stop_requested),
                    probe_activities=7,
                )

                total_done += int(max(0, min(iter_budget, round_progress_done)))
                if self._improve_stop_requested:
                    break
                candidate_pen = int(ls.compute_soft_penalty(candidate))
                candidate_hard_errors = self._validate_schedule_hard_errors(
                    candidate, require_all=True
                )

                if (not candidate_hard_errors) and candidate_pen <= int(best_pen):
                    best_schedule = {
                        a_id: info.copy() for a_id, info in candidate.items()
                    }
                    best_pen = int(candidate_pen)

                # Keep live view synced with the best accepted state between rounds.
                self.current_schedule = {
                    a_id: info.copy() for a_id, info in best_schedule.items()
                }
                self.update_table()
                self.update_quality_summary()
                QApplication.processEvents()

            self._status_full_text = (
                "Improving... stopped (finalizing)"
                if self._improve_stop_requested
                else "Improving... 100% (finalizing)"
            )
            self._refresh_status_label()
            improved = {
                a_id: info.copy() for a_id, info in best_schedule.items()
            }
            improved_hard_errors = self._validate_schedule_hard_errors(
                improved, require_all=True
            )

            # Restore pre-improve state so commit status shows true delta against baseline.
            self.current_schedule = {
                a_id: info.copy() for a_id, info in original_schedule.items()
            }
            self._live_improve_mode = False
            if improved_hard_errors:
                self.update_table()
                self.update_quality_summary()
                self.set_status(
                    f"Improvement rejected: {len(improved_hard_errors)} hard conflicts detected"
                )
            else:
                if improved != original_schedule:
                    self._push_undo_state()
                self._commit_schedule(
                    improved,
                    f"Improved global penalty {base_pen} -> {best_pen} "
                    f"in {total_done} iterations ({round_idx} rounds)"
                    + (" [stopped]" if self._improve_stop_requested else ""),
                )
                # Improvement changes are optimizer-generated; don't mark them as manual edits.
                self._set_manual_highlight_base(self.current_schedule)

        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Improve error", str(e))
            self.set_status("Improve error")
            self.current_schedule = {
                a_id: info.copy() for a_id, info in original_schedule.items()
            }
            self.update_table()
            self.update_quality_summary()
        finally:
            self._live_improve_mode = False
            self._improve_running = False
            self._improve_stop_requested = False
            self.stop_improve_button.setEnabled(False)
            self.set_busy(False)

    def on_stop_improve(self) -> None:
        if not self._improve_running:
            self.set_status("No active improve run")
            return
        self._improve_stop_requested = True
        self.set_status("Stopping improvement at next safe checkpoint...")

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
        self._set_manual_highlight_base(self.current_schedule)
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
        self._set_manual_highlight_base({})
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
        self._set_manual_highlight_base(self.current_schedule)
        self.held_activity_id = None
        self._reset_history()
        # Allow importing partially specified schedules (room_id may be blank).
        # Room consistency can still be repaired/validated after solving/exporting.
        errors = validate_schedule_against_instance(
            self.inst, self.current_schedule, strict_rooms=False, require_all_activities=False
        )
        if errors:
            msg = "Schedule violates hard rules:\n" + "\n".join(f"- {e}" for e in errors[:20])
            if len(errors) > 20:
                msg += f"\n... and {len(errors) - 20} more"
            QMessageBox.critical(self, "Invalid schedule", msg)
            self.base_schedule = {}
            self._set_manual_highlight_base({})
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
        try:
            if self.inst is None:
                self._render_empty_calendar(None, None)
                self._refresh_quick_actions()
                return
            if self.week_combo.count() == 0:
                self._render_empty_calendar(self.inst.days, int(self.inst.slots_per_day))
                self._refresh_quick_actions()
                return

            week_data = self.week_combo.currentData()
            if week_data is None:
                self._render_empty_calendar(self.inst.days, int(self.inst.slots_per_day))
                self._refresh_quick_actions()
                return
            week = int(week_data)

            days = self.inst.days
            S = self.inst.slots_per_day

            self.table.setRowCount(len(days))
            self.table.setColumnCount(S)
            self.table.setVerticalHeaderLabels(days)
            self.table.setHorizontalHeaderLabels([f"S{idx + 1}" for idx in range(S)])
            self._held_move_analysis_map = {}

            # Render an empty calendar right after generation/loading even before solving.
            if not self.current_schedule:
                self._render_empty_calendar(days, S, week_label=f"Week {week}")
                self._refresh_quick_actions()
                return

            view_type = self.view_type_combo.currentText()
            if self.entity_combo.count() == 0:
                self.clear_table()
                return
            data = self.entity_combo.currentData()
            if data is None and view_type != "All":
                self.clear_table()
                return
            entity_id = int(data) if data is not None and view_type != "All" else None

            cell_entries: Dict[Tuple[str, int], List[Tuple[int, str, str]]] = {
                (d, s): [] for d in days for s in range(S)
            }
            self._cell_activity_map = {}

            for a_id, info in self.current_schedule.items():
                if int(info["week"]) != int(week):
                    continue
                day = str(info["day"])
                s0 = int(info["slot"])
                dur = int(info["duration"])

                if view_type == "Group" and entity_id is not None and entity_id not in info["group_ids"]:
                    continue
                if view_type == "Staff" and entity_id is not None and entity_id != int(info["staff_id"]):
                    continue
                room_id_raw = info.get("room_id")
                if (
                    view_type == "Room"
                    and entity_id is not None
                    and (room_id_raw is None or entity_id != int(room_id_raw))
                ):
                    continue

                course_id_raw = info.get("course_id")
                staff_id_raw = info.get("staff_id")
                course = (
                    self.inst.courses.get(int(course_id_raw))
                    if course_id_raw is not None
                    else None
                )
                room = (
                    self.inst.rooms.get(int(room_id_raw))
                    if room_id_raw is not None
                    else None
                )
                staff = (
                    self.inst.staff.get(int(staff_id_raw))
                    if staff_id_raw is not None
                    else None
                )

                lock = self.locked_activities.get(int(a_id), {})
                lock_text = ""
                if isinstance(lock, dict):
                    lock_flags: List[str] = []
                    if "day" in lock and "slot" in lock:
                        lock_flags.append("T")
                    if "room_id" in lock:
                        lock_flags.append("R")
                    if lock_flags:
                        lock_text = f"LOCK[{''.join(lock_flags)}] "

                course_code = course.code if course is not None else f"C{course_id_raw}"
                course_name = course.name if course is not None else ""
                room_name = room.name if room is not None else (
                    f"R{room_id_raw}" if room_id_raw is not None else "(unassigned)"
                )
                staff_name = staff.name if staff is not None else f"S{staff_id_raw}"

                if view_type == "All":
                    label = (
                        f"{lock_text}A{a_id} {course_code} {info['kind']} "
                        f"| G{len(info['group_ids'])} | {room_name} | {staff_name}"
                    )
                else:
                    parts: List[str] = []
                    if lock_text:
                        parts.append(lock_text.strip())
                    parts.append(course_code)
                    if course_name:
                        parts.append(course_name)
                    parts.append(str(info["kind"]))
                    parts.append(f"Room: {room_name}")
                    parts.append(f"Staff: {staff_name}")
                    label = "\n".join(parts)

                detail = (
                    f"A{a_id} {course_code} {course_name} {info['kind']} | "
                    f"Groups={len(info['group_ids'])} | Room={room_name} | Staff={staff_name}"
                ).strip()

                for ds in range(dur):
                    s = s0 + ds
                    if 0 <= s < S:
                        cell_entries[(day, s)].append((int(a_id), label, detail))

            conflict_ids = self._compute_conflicting_activity_ids(self.current_schedule)
            changed_ids = {
                int(a_id)
                for a_id in self.current_schedule.keys()
                if self._is_activity_changed_from_base(int(a_id))
            }

            held_id = (
                int(self.held_activity_id)
                if self.held_activity_id is not None and self.held_activity_id in self.current_schedule
                else None
            )
            held_week_ok = (
                held_id is not None
                and int(self.current_schedule[held_id]["week"]) == int(week)
            )
            held_target_map: Dict[Tuple[str, int], bool] = {}
            held_base_score: int | None = None
            held_delta_map: Dict[Tuple[str, int], int] = {}
            show_score_deltas = bool(
                hasattr(self, "show_score_deltas_cb") and self.show_score_deltas_cb.isChecked()
            )
            if held_week_ok:
                self._held_move_analysis_map = self._build_held_move_analysis(week)
                held_target_map = {
                    key: bool(v.get("ok", False))
                    for key, v in self._held_move_analysis_map.items()
                }
                for details in self._held_move_analysis_map.values():
                    score_current = details.get("score_current")
                    if isinstance(score_current, int):
                        held_base_score = int(score_current)
                        break
                for key, details in self._held_move_analysis_map.items():
                    score_delta = details.get("score_delta")
                    if bool(details.get("ok", False)) and isinstance(score_delta, int):
                        held_delta_map[key] = int(score_delta)

            color_held = QColor("#234f7a")
            color_valid_target = QColor("#2c5f3c")
            color_valid_target_better = QColor("#1f6d44")
            color_valid_target_worse = QColor("#6f5324")
            color_conflict_target = QColor("#d3a300")
            color_changed = QColor("#8a3f7a")
            color_current_conflict = QColor("#8a1f1f")

            for row, day in enumerate(days):
                for col in range(S):
                    entries = sorted(cell_entries[(day, col)], key=lambda t: int(t[0]))
                    ids = [int(a_id) for a_id, _, _ in entries]
                    if view_type == "All":
                        max_lines = 7
                        lines = [label for _, label, _ in entries[:max_lines]]
                        extra = len(entries) - max_lines
                        if extra > 0:
                            lines.append(f"... +{extra} more (hover)")
                        text = "\n".join(lines)
                    else:
                        text = "\n\n".join(label for _, label, _ in entries)
                    if held_week_ok and held_id is not None and show_score_deltas:
                        analysis = self._held_move_analysis_map.get((str(day), int(col)))
                        if analysis is not None and bool(analysis.get("ok", False)):
                            score_after = analysis.get("score_after")
                            score_delta = analysis.get("score_delta")
                            if isinstance(score_after, int) and isinstance(score_delta, int):
                                if held_id in ids:
                                    score_badge = f"[CURRENT P {int(score_after)}]"
                                else:
                                    if int(score_delta) < 0:
                                        trend = "BETTER"
                                    elif int(score_delta) > 0:
                                        trend = "WORSE"
                                    else:
                                        trend = "SAME"
                                    score_badge = (
                                        f"[{trend} {int(score_delta):+d} | P {int(score_after)}]"
                                    )
                                text = f"{score_badge}\n{text}" if text else score_badge
                        elif held_id in ids and held_base_score is not None:
                            score_badge = f"[CURRENT P {int(held_base_score)}]"
                            text = f"{score_badge}\n{text}" if text else score_badge
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                    )
                    item.setForeground(QBrush(QColor("#f5f5f5")))
                    if ids:
                        item.setData(Qt.ItemDataRole.UserRole, ids)

                    if held_week_ok and held_id is not None and held_id in ids:
                        item.setBackground(QBrush(color_held))
                    elif ids and any(int(a_id) in conflict_ids for a_id in ids):
                        item.setBackground(QBrush(color_current_conflict))
                    elif held_week_ok and held_id is not None:
                        analysis = self._held_move_analysis_map.get((str(day), int(col)))
                        if analysis is not None and held_target_map.get((str(day), int(col)), False):
                            delta_here = held_delta_map.get((str(day), int(col)))
                            if isinstance(delta_here, int) and delta_here < 0:
                                item.setBackground(QBrush(color_valid_target_better))
                            elif isinstance(delta_here, int) and delta_here > 0:
                                item.setBackground(QBrush(color_valid_target_worse))
                            else:
                                item.setBackground(QBrush(color_valid_target))
                        elif analysis is not None and (analysis.get("conflicts") or []):
                            item.setBackground(QBrush(color_conflict_target))
                    elif ids and any(int(a_id) in changed_ids for a_id in ids):
                        item.setBackground(QBrush(color_changed))

                    tooltip = self._build_cell_tooltip(
                        row=int(row),
                        col=int(col),
                        ids=ids,
                        week=int(week),
                        day=str(day),
                        held_id=held_id,
                        held_week_ok=bool(held_week_ok),
                    )
                    if view_type == "All" and entries:
                        details = [detail for _, _, detail in entries]
                        tooltip += "\n\nDetailed entries:\n" + "\n".join(
                            f"  - {line}" for line in details[:24]
                        )
                        extra = len(details) - 24
                        if extra > 0:
                            tooltip += f"\n  - ... +{extra} more"
                    item.setToolTip(tooltip)

                    self.table.setItem(row, col, item)
                    self._cell_activity_map[(row, col)] = ids

            self._schedule_table_relayout()
            self._refresh_quick_actions()
        except Exception:
            traceback.print_exc()
            self.clear_table()
            self.set_status("Failed to render schedule table")

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
        if pen <= 10:
            return "optimal"
        if pen <= 80:
            return "near-optimal"
        if pen <= 220:
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
            hard_conflicts = len(self._collect_conflict_errors())
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
        try:
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

            dlg = EditActivityDialog(
                self,
                self.inst,
                self.current_schedule,
                act_ids,
                week,
                day,
                slot,
                locked=self.locked_activities,
            )
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
        except Exception:
            traceback.print_exc()
            self.set_status("Edit failed")

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

        def _is_block_staff(member: Any) -> bool:
            return bool(
                getattr(member, "blocks_only", False)
                or getattr(member, "prefers_block", False)
                or getattr(member, "is_block_prof", False)
            )

        if new_slot < 0 or new_slot + dur > inst.slots_per_day:
            return False, "Activity would overflow the day."

        if _flag("week1_lectures_only", True) and inst.weeks:
            first_week = min(int(wk) for wk in inst.weeks)
            if int(w) == int(first_week) and act.kind in ("TUT", "LAB"):
                return False, "Week 1 allows lectures only."

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

        if _flag("enforce_block_professor_rules", True) and _is_block_staff(staff):
            teaching_days = {str(new_day)}
            for b_id, b in schedule.items():
                if int(b_id) == int(a_id):
                    continue
                if int(b["week"]) != int(w) or int(b["staff_id"]) != int(new_staff_id):
                    continue
                teaching_days.add(str(b["day"]))
            if len(teaching_days) > 2:
                return False, "Block-staff can teach on at most two days per week."

            if act.kind == "LEC" and bool(getattr(staff, "blocks_only", False)):
                slots_by_day: Dict[str, Set[int]] = {}
                total = 0
                for b_id, b in schedule.items():
                    if int(b_id) == int(a_id):
                        continue
                    if int(b["week"]) != int(w):
                        continue
                    if int(b["staff_id"]) != int(new_staff_id):
                        continue
                    other_act = inst.activities.get(int(b_id))
                    if other_act is None:
                        continue
                    if other_act.kind != "LEC" or int(other_act.course_id) != int(act.course_id):
                        continue
                    day_cur = str(b["day"])
                    slot_cur = int(b["slot"])
                    dur_cur = int(b["duration"])
                    total += dur_cur
                    day_slots = slots_by_day.setdefault(day_cur, set())
                    for off in range(dur_cur):
                        day_slots.add(slot_cur + off)
                total += int(dur)
                own_slots = slots_by_day.setdefault(str(new_day), set())
                for off in range(int(dur)):
                    own_slots.add(int(new_slot) + off)

                if total and not (2 <= total <= 3):
                    return False, "Block-only professor lectures must be 2-3 contiguous slots per course/week."
                if len(slots_by_day) > 1:
                    return False, "Block-only professor lectures for a course must stay on one day."
                for slots_for_day in slots_by_day.values():
                    sorted_slots = sorted(slots_for_day)
                    for idx in range(1, len(sorted_slots)):
                        if sorted_slots[idx] != sorted_slots[idx - 1] + 1:
                            return False, "Block-only professor lecture slots must be contiguous."

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
    icon_path = _resource_path("app_icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
