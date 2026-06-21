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
import copy
from datetime import datetime, timezone
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


def _app_icon_path() -> str:
    for filename in ("Logo.ico", "app_icon.png"):
        path = _resource_path(filename)
        if os.path.exists(path):
            return path
    return ""

from PyQt6.QtCore import Qt, QProcess, QTimer, QEvent, QThread, QThreadPool
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
    QPlainTextEdit,
    QScrollArea,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QTableView,
)

from product.model import ProductScenario
from services.approval_service import approval_to_dict, build_approval_record
from services.branch_service import (
    branch_merge_assistance,
    create_branch,
    list_branch_rows,
    update_branch,
)
from services.branding_service import (
    about_lines,
    branding_from_institution_template,
    default_branding_profile,
    ensure_branding_profile,
    white_label_profile_for_institution,
)
from services.calendar_sync_service import (
    build_calendar_sync_bundle,
    write_calendar_sync_bundle,
)
from services.diagnostics_service import (
    build_stakeholder_quality_report,
    build_unsat_rule_diagnosis,
    compute_entity_heatmaps,
    explain_candidate_slot,
    write_stakeholder_quality_report,
)
from services.institution_template_service import (
    apply_institution_template,
    load_institution_template,
    save_institution_template,
)
from services.performance_service import build_feasibility_certificate
from services.release_service import (
    create_release_candidate,
    protect_baseline_state,
    publish_release_candidate,
)
from services.template_profile_service import (
    list_import_export_template_profiles,
    load_import_export_template_profile,
    save_import_export_template_profile,
)
from services.timetable_import_service import import_timetable_csv
from services.timetable_import_service import suggest_timetable_mapping
from ui.constants import (
    APP_COPYRIGHT_LINE,
    APP_DISPLAY_NAME,
    APP_OWNER_NAME,
    APP_SHORT_NAME,
    APP_SUBTITLE,
    APP_VERSION,
    DEFAULT_DAY_START,
    DEFAULT_SLOT_MINUTES,
    DEFAULT_BREAK_MINUTES,
    DEFAULT_TIME_LIMIT,
    DEFAULT_CP_WORKERS,
)
from services.compare_service import compare_schedule_sets
from services.contracts import SolveOptions
from services.export_service import (
    export_csv as export_csv_service,
    export_docx as export_docx_service,
    export_ics as export_ics_service,
    export_pdf as export_pdf_service,
    export_reports as export_reports_service,
)
from services.project_service import load_legacy_project, save_legacy_project
from services.quality_service import (
    SOFT_WEIGHT_DEFAULTS,
    compute_penalty_breakdown,
    evaluate_schedule_sla,
    explain_solution_ranking,
    rank_penalty_drivers,
)
from services.runtime_ops_service import (
    append_runtime_log,
    check_for_updates,
    collect_support_bundle,
    default_runtime_paths,
    load_runtime_settings,
    record_telemetry_event,
    save_runtime_settings,
    write_crash_report,
)
from services.schedule_ops_service import (
    build_focused_improve_instance,
    focus_penalty_activity_ids,
)
from services.scenario_service import (
    build_builtin_product_scenario,
    build_product_scenario_from_instance,
    compile_scenario_instance,
    load_product_scenario,
    save_product_scenario,
)
from services.solver_service import available_objective_profiles, solve_portfolio
from ui.dialogs import (
    ApprovalDialog,
    BranchMetadataDialog,
    BulkEditDialog,
    ChangeHistoryDialog,
    CommandPaletteDialog,
    EditActivityDialog,
    MoveConflictDialog,
    ConflictInspectorDialog,
    ImportScheduleWizardDialog,
    TimetableCsvImportWizardDialog,
    SearchResultsDialog,
)
from ui.backend_client import create_backend_client
from ui.models import SimpleTableModel
from ui.styles import DARK_STYLE
from ui.widgets import ScheduleTableWidget
from ui.workers import FunctionWorker, ImproveWorker
from connectors.csv_connectors import ERPCsvConnector, LMSCsvConnector, SISCsvConnector
from utils.generator import (
    generate_instance,
    generate_custom_instance,
    ROOM_CATEGORY_CAPACITY,
    instance_to_json,
)
from core.metaheuristics import LocalSearchImprover
from utils.exporter import (
    export_group_schedules_to_docx,
    export_groups_pdf,
    export_summary_reports,
    export_schedule_to_csv,
    export_groups_ics_per_id,
    export_staff_ics_per_id,
    export_rooms_ics_per_id,
    export_calendar_feeds,
)
from utils.domain import Instance
from utils.io import (
    read_scenario,
    write_scenario,
    read_instance,
    read_schedule_csv,
    read_schedule_csv_mapped,
    instance_from_json,
)
from utils.compare import compare_schedules, write_comparison_report
from utils.feasibility import explain_infeasibility
from utils.specs import validate_instance_against_spec, validate_schedule_against_instance
from utils.disruption import (
    apply_staff_outage_week,
    apply_room_outage_week,
    build_freeze_locks,
)
from utils.conflict_explainer import build_move_explanation_text
from utils.fairness import compute_fairness_dashboard
from utils.schedule_rules import (
    calendar_slot_blocked,
    generic_resource_violations,
    generic_resources_available,
    precedence_violations,
    room_is_available,
    travel_buffer_violations,
)
from utils.constraint_templates import (
    DEFAULT_TEMPLATES,
    load_templates,
    save_templates,
    apply_template_to_instance,
)
from main import normalize_instance_for_spec, check_staff_weekly_capacity, stamp_instance_time


# ---------- Main window ----------
ROOM_TYPE_CHOICES: Tuple[str, ...] = (
    "LECTURE",
    "TUTORIAL",
    "COMPUTER_LAB",
    "SPECIALIZED_LAB",
)
ROOM_CATEGORY_CHOICES: Tuple[str, ...] = ("SMALL", "MEDIUM", "BIG")
ROOM_CAPACITY_MODE_CHOICES: Tuple[Tuple[str, str], ...] = (
    ("Categorical (SMALL/MEDIUM/BIG)", "categorical"),
    ("Numeric (exact capacity)", "numeric"),
)
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


class NumericTableItem(QTableWidgetItem):
    """Table item that sorts numeric text by numeric value."""

    @staticmethod
    def _to_number(value: str) -> float | int | None:
        text = str(value).strip()
        if not text:
            return None
        try:
            if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
                return int(text)
            return float(text)
        except Exception:
            return None

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, QTableWidgetItem):
            a_num = self._to_number(self.text())
            b_num = self._to_number(other.text())
            if a_num is not None and b_num is not None:
                return a_num < b_num
            if a_num is not None and b_num is None:
                return True
            if a_num is None and b_num is not None:
                return False
            return self.text().lower() < other.text().lower()
        return super().__lt__(other)


class NaturalSortTableItem(QTableWidgetItem):
    """Table item that sorts mixed text/number tokens naturally."""

    @staticmethod
    def _key(value: str) -> tuple:
        parts = re.split(r"(\d+)", str(value).strip().lower())
        key: List[Any] = []
        for part in parts:
            if not part:
                continue
            if part.isdigit():
                key.append(int(part))
            else:
                key.append(part)
        return tuple(key)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, QTableWidgetItem):
            return self._key(self.text()) < self._key(other.text())
        return super().__lt__(other)


class MainWindow(QMainWindow):
    DEFAULT_PREVIEW_DAYS: Tuple[str, ...] = ("MON", "TUE", "WED", "THU", "FRI", "SAT")
    DEFAULT_PREVIEW_SLOTS: int = 5

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_DISPLAY_NAME)
        icon_path = _app_icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

        self.inst: Instance | None = None
        self.product_scenario: ProductScenario | None = None
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
        self._held_analysis_cache_key: Tuple[Any, ...] | None = None
        self._held_analysis_cache_value: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self._schedule_revision: int = 0
        self._conflict_ids_cache_revision: int = -1
        self._conflict_ids_cache: Set[int] = set()
        self._undo_stack: List[Dict[str, Any]] = []
        self._redo_stack: List[Dict[str, Any]] = []
        self._sandbox_base_schedule: Dict[int, Dict[str, Any]] | None = None
        self._restore_locks_after_solve: Dict[int, Dict[str, Any]] | None = None
        self._history_store_path = os.path.join(
            os.path.expanduser("~"), ".planora_ui_history.json"
        )
        self._audit_log_path = os.path.join(
            os.path.expanduser("~"), ".planora_audit_log.jsonl"
        )
        self._template_store_path = os.path.join(
            os.path.expanduser("~"), ".planora_constraint_templates.json"
        )
        self.constraint_templates: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._snapshot_store_dir = os.path.join(
            os.path.expanduser("~"), ".planora_history_snapshots"
        )
        self._soft_penalty_improver: LocalSearchImprover | None = None
        self._soft_penalty_improver_inst_ref: Instance | None = None

        self.proc: QProcess | None = None
        self._solve_progress_timer: QTimer | None = None
        self._solve_started_at: float | None = None
        self._solve_expected_seconds: float = 0.0
        self._solve_progress_percent: int = 0
        self._solve_progress_context: Dict[str, Any] = {}
        self._solve_attempt_started_at: float | None = None
        self._solver_output_log: str = ""
        self._solver_output_partial: str = ""
        self._last_solver_output_log: str = ""
        self._last_solver_result_meta: Dict[str, Any] = {}
        self._table_relayout_pending = False
        self._layout_stabilize_pending: bool = False
        self.top_widget: QWidget | None = None
        self._top_controls_height_cache: int | None = None
        self._status_full_text: str = f"{APP_SHORT_NAME} ready"
        self._live_improve_mode: bool = False
        self._improve_running: bool = False
        self._improve_stop_requested: bool = False
        self._solver_safe_retry_used: bool = False
        self._last_solver_keep_locks: bool = False
        self._maximize_on_first_show: bool = True
        self.tmp_inst_path: str | None = None
        self.tmp_res_path: str | None = None
        self._room_table_internal_change = False
        self._custom_program_table_internal_change = False
        self._custom_course_pattern_table_internal_change = False
        self.backend_client = create_backend_client(
            backend_url=os.getenv("PLANORA_BACKEND_URL", "").strip() or None
        )
        self._institution_template: Dict[str, Any] | None = None
        self._last_import_mapping: Dict[str, str] = {}
        self._last_group_separator: str = ";"
        self._operator_name: str = str(
            os.getenv("PLANORA_OPERATOR")
            or os.getenv("USERNAME")
            or os.getenv("USER")
            or os.getenv("LOGNAME")
            or "unknown"
        ).strip() or "unknown"
        self._branches: Dict[str, Dict[str, Any]] = {}
        self._active_branch_name: str | None = None
        self._release_candidates: Dict[str, Dict[str, Any]] = {}
        self._published_release_id: str | None = None
        self._protected_baseline: Dict[str, Any] = {"protected": False}
        self._workspace_change_log: List[Dict[str, Any]] = []
        self._import_export_template_path = os.path.join(
            os.path.expanduser("~"), ".planora_import_export_templates.json"
        )
        self._branding_profile: Dict[str, Any] = default_branding_profile()
        self._runtime_paths: Dict[str, str] = default_runtime_paths(APP_SHORT_NAME)
        self._runtime_settings: Dict[str, Any] = load_runtime_settings(
            self._runtime_paths["settings"]
        )
        self._thread_pool = QThreadPool.globalInstance()
        self._held_analysis_async_key: Tuple[Any, ...] | None = None
        self._improve_thread: QThread | None = None
        self._improve_worker: ImproveWorker | None = None
        self._improve_original_schedule: Dict[int, Dict[str, Any]] | None = None
        self._improve_total_iters: int = 0
        self._improve_base_penalty: int | None = None
        self._improve_focus_term: str = ""

        self._build_ui()
        self._connect_signals()
        self._load_templates()
        self._load_persistent_history()
        self._load_ui_control_preferences()
        self._apply_branding_profile()
        self._append_audit_log("app_started", {"window": self.windowTitle()})

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
                "ss23_uni_like",
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
        self.room_mode_combo.addItem("Auto", "auto")
        self.room_mode_combo.addItem("Strict (CP rooms)", "cp_rooms")
        self.room_mode_combo.addItem("Fast (Greedy rooms)", "greedy")
        self.room_mode_combo.setCurrentIndex(0)

        self.objective_cb = QCheckBox("Use CP objective")
        self.objective_cb.setChecked(True)
        self.debug_diagnostics_cb = QCheckBox("Debug diagnostics")
        self.debug_diagnostics_cb.setChecked(
            str(os.getenv("PLANORA_SOLVER_DEBUG", "")).strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self.objective_profile_combo = QComboBox()
        for profile_id, label in available_objective_profiles():
            self.objective_profile_combo.addItem(str(label), str(profile_id))
        balanced_idx = self.objective_profile_combo.findData("balanced")
        if balanced_idx >= 0:
            self.objective_profile_combo.setCurrentIndex(balanced_idx)

        self.time_limit_spin = StepSpinBox()
        self.time_limit_spin.setRange(5, 3600)
        self.time_limit_spin.setValue(DEFAULT_TIME_LIMIT)
        self.time_limit_spin.setSuffix(" s")

        self.random_seed_spin = StepSpinBox()
        self.random_seed_spin.setRange(1, 2_147_483_647)
        self.random_seed_spin.setValue(2023)
        self.random_seed_spin.setMaximumWidth(120)

        self.workers_preset_combo = QComboBox()
        self._worker_preset_counts: Dict[str, int] = {}
        cpu_count = max(1, min(64, int(os.cpu_count() or DEFAULT_CP_WORKERS)))
        workers_min = 1
        workers_med = max(1, min(cpu_count, int(DEFAULT_CP_WORKERS)))
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
        self.ls_time_spin.setValue(0)
        self.ls_time_spin.setSuffix(" s")
        self.ls_time_spin.setMaximumWidth(120)

        self.improve_focus_combo = QComboBox()
        self.improve_focus_combo.addItem("Overall", "")
        for key in SOFT_WEIGHT_DEFAULTS:
            self.improve_focus_combo.addItem(str(key), str(key))
        self.improve_focus_combo.setMinimumWidth(140)

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
        self.search_scope_combo = QComboBox()
        self.search_scope_combo.addItems(["Activities", "Staff", "Rooms", "Conflicts", "All"])
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search activities, staff, rooms, conflicts...")
        self.search_button = QPushButton("Search")

        self.status_label = QLabel("Ready")
        self.quality_label = QLabel("")
        self.quality_label.setWordWrap(True)
        self.quality_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

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
        row_actions.setContentsMargins(6, 0, 6, 0)
        row_actions.setSpacing(6)
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
        for widget in action_widgets:
            row_actions.addWidget(widget)
        row_actions.addStretch(1)
        top_layout.addLayout(row_actions)

        # Row 1: tuning
        row_tuning = QHBoxLayout()
        row_tuning.setContentsMargins(6, 0, 6, 0)
        row_tuning.setSpacing(6)
        tuning_widgets: List[QWidget] = [
            _pair_widget("LS iters:", self.improve_runs_spin),
            _pair_widget("LS time:", self.ls_time_spin),
            _pair_widget("Focus:", self.improve_focus_combo),
            _pair_widget("Room mode:", self.room_mode_combo),
            _pair_widget("Profile:", self.objective_profile_combo),
            self.objective_cb,
        ]
        for widget in tuning_widgets:
            row_tuning.addWidget(widget)
        row_tuning.addStretch(1)
        top_layout.addLayout(row_tuning)

        # Row 2: solver runtime/debug controls
        row_solver = QHBoxLayout()
        row_solver.setContentsMargins(6, 0, 6, 0)
        row_solver.setSpacing(6)
        solver_widgets: List[QWidget] = [
            _pair_widget("Limit:", self.time_limit_spin),
            _pair_widget("Workers:", self.workers_preset_combo),
            _pair_widget("Seed:", self.random_seed_spin),
            self.debug_diagnostics_cb,
        ]
        for widget in solver_widgets:
            row_solver.addWidget(widget)
        row_solver.addStretch(1)
        top_layout.addLayout(row_solver)

        # Row 3: view controls + status
        row_view = QHBoxLayout()
        row_view.setContentsMargins(6, 0, 6, 0)
        row_view.setSpacing(6)
        row_view.addWidget(_pair_widget("View:", self.view_type_combo))
        row_view.addWidget(self.entity_combo)
        row_view.addWidget(_pair_widget("Week:", self.week_combo))
        row_view.addWidget(_pair_widget("Search:", self.search_scope_combo))
        row_view.addWidget(self.search_edit)
        row_view.addWidget(self.search_button)
        row_view.addWidget(self.status_label, 2)
        top_layout.addLayout(row_view)

        # Emphasize primary admin controls and improve discoverability.
        self.improve_button.setMaximumWidth(96)
        self.stop_improve_button.setMinimumWidth(126)
        self.export_menu_btn.setMinimumWidth(92)
        self.project_menu_btn.setMinimumWidth(92)
        self.view_type_combo.setMinimumWidth(120)
        self.entity_combo.setMinimumWidth(220)
        self.week_combo.setMinimumWidth(96)
        self.search_scope_combo.setMinimumWidth(110)
        self.search_edit.setMinimumWidth(200)
        self.workers_preset_combo.setMinimumWidth(120)
        self.objective_profile_combo.setMinimumWidth(150)
        self.status_label.setWordWrap(False)
        self.status_label.setMinimumWidth(300)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
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

        self.table = ScheduleTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(True)
        self.table.horizontalHeader().setVisible(True)
        self.table.setWordWrap(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        # Keep scrolling on the outer Schedule view, not inside the table widget.
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)

        self.workspace_tabs = QTabWidget()
        schedule_tab = QWidget()
        schedule_tab_layout = QVBoxLayout(schedule_tab)
        schedule_tab_layout.setContentsMargins(0, 0, 0, 0)
        schedule_tab_layout.setSpacing(0)
        self.schedule_view_scroll = QScrollArea()
        self.schedule_view_scroll.setWidgetResizable(True)
        self.schedule_view_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.schedule_view_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.schedule_view_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.table.setExternalScrollArea(self.schedule_view_scroll)
        schedule_tab_layout.addWidget(self.schedule_view_scroll)
        schedule_content = QWidget()
        self.schedule_view_scroll.setWidget(schedule_content)
        schedule_layout = QVBoxLayout(schedule_content)
        schedule_layout.setContentsMargins(0, 0, 0, 0)
        schedule_layout.setSpacing(6)
        schedule_layout.addWidget(self.table, 0)
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
        self.schedule_actions_scroll.setMaximumHeight(210)
        schedule_layout.addWidget(self.schedule_actions_scroll, 0)
        self.quality_scroll = QScrollArea()
        self.quality_scroll.setWidget(self.quality_label)
        self.quality_scroll.setWidgetResizable(True)
        self.quality_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.quality_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.quality_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.quality_scroll.setMaximumHeight(120)
        self.quality_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        schedule_layout.addWidget(self.quality_scroll, 0)
        self.workspace_tabs.addTab(schedule_tab, "Schedule")
        self.workspace_tabs.addTab(self._build_generator_tab(), "Generator")
        self.workspace_tabs.addTab(self._build_constraints_tab(), "Constraints")
        self.workspace_tabs.addTab(self._build_fairness_tab(), "Fairness")
        self.workspace_tabs.addTab(self._build_diagnostics_tab(), "Diagnostics")
        self.workspace_tabs.addTab(self._build_history_tab(), "History")

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
        self._ensure_custom_generator_seeded()
        self._load_custom_config_local(silent=True)
        self._apply_room_capacity_mode()
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

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            self._save_ui_control_preferences()
        except Exception:
            pass
        try:
            self._save_persistent_history()
        except Exception:
            pass
        super().closeEvent(event)

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
        if hasattr(self, "schedule_view_scroll"):
            self.schedule_view_scroll.setMinimumWidth(0)
            self.schedule_view_scroll.updateGeometry()
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

    def _load_ui_control_preferences(self) -> None:
        prefs = dict(self._runtime_settings.get("ui_preferences", {}) or {})

        def _set_combo_data(combo: QComboBox, value: Any) -> None:
            idx = combo.findData(value)
            if idx >= 0:
                combo.setCurrentIndex(idx)

        if "room_mode" in prefs:
            _set_combo_data(self.room_mode_combo, str(prefs.get("room_mode")))
        if "objective_profile" in prefs:
            _set_combo_data(self.objective_profile_combo, str(prefs.get("objective_profile")))
        if "improve_focus" in prefs:
            _set_combo_data(self.improve_focus_combo, str(prefs.get("improve_focus")))
        if "workers" in prefs:
            try:
                _set_combo_data(self.workers_preset_combo, int(prefs.get("workers")))
            except Exception:
                pass
        if "time_limit_seconds" in prefs:
            try:
                self.time_limit_spin.setValue(int(prefs.get("time_limit_seconds")))
            except Exception:
                pass
        if "random_seed" in prefs:
            try:
                self.random_seed_spin.setValue(int(prefs.get("random_seed")))
            except Exception:
                pass
        if "improve_iterations" in prefs:
            try:
                self.improve_runs_spin.setValue(int(prefs.get("improve_iterations")))
            except Exception:
                pass
        if "improve_seconds" in prefs:
            try:
                self.ls_time_spin.setValue(int(prefs.get("improve_seconds")))
            except Exception:
                pass
        if "use_cp_objective" in prefs:
            self.objective_cb.setChecked(bool(prefs.get("use_cp_objective")))
        if "debug_diagnostics" in prefs:
            self.debug_diagnostics_cb.setChecked(bool(prefs.get("debug_diagnostics")))

    def _save_ui_control_preferences(self) -> None:
        prefs = {
            "room_mode": str(self.room_mode_combo.currentData() or "auto"),
            "objective_profile": str(self.objective_profile_combo.currentData() or "balanced"),
            "improve_focus": str(self.improve_focus_combo.currentData() or ""),
            "workers": int(self._selected_worker_count()),
            "time_limit_seconds": int(self.time_limit_spin.value()),
            "random_seed": int(self.random_seed_spin.value()),
            "improve_iterations": int(self.improve_runs_spin.value()),
            "improve_seconds": int(self.ls_time_spin.value()),
            "use_cp_objective": bool(self.objective_cb.isChecked()),
            "debug_diagnostics": bool(self.debug_diagnostics_cb.isChecked()),
        }
        self._runtime_settings["ui_preferences"] = prefs
        self._runtime_settings = save_runtime_settings(
            self._runtime_paths["settings"],
            self._runtime_settings,
        )

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
        h.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        v.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        # Keep schedule cells readable, but expand to fill horizontal space when available.
        base_col_w = 170
        min_col_w = 130
        row_h = 78
        min_row_h = 42
        h.setDefaultSectionSize(base_col_w)
        v.setDefaultSectionSize(row_h)
        h.setMinimumSectionSize(min_col_w)
        v.setMinimumSectionSize(min_row_h)

        col_count = int(self.table.columnCount())
        available_w = 0
        if hasattr(self, "schedule_view_scroll"):
            try:
                available_w = int(self.schedule_view_scroll.viewport().width())
            except Exception:
                available_w = 0
        if available_w <= 0:
            parent = self.table.parentWidget()
            if parent is not None:
                try:
                    available_w = int(parent.width())
                except Exception:
                    available_w = 0

        non_col_w = int(v.width()) + (self.table.frameWidth() * 2) + 4
        target_col_w = int(base_col_w)
        if available_w > non_col_w and col_count > 0:
            fill_col_w = int((available_w - non_col_w) // col_count)
            target_col_w = int(max(min_col_w, max(base_col_w, fill_col_w)))

        for col in range(col_count):
            self.table.setColumnWidth(col, int(target_col_w))

        # Consume remainder on the last column so the table reaches the right edge.
        if available_w > 0 and col_count > 0:
            used_cols = int(target_col_w) * int(col_count)
            remainder = int(max(0, available_w - non_col_w - used_cols))
            if remainder > 0:
                last = int(col_count - 1)
                self.table.setColumnWidth(last, int(target_col_w + remainder))

        total_w = int(v.width()) + (self.table.frameWidth() * 2) + 4
        for col in range(col_count):
            total_w += int(self.table.columnWidth(col))
        total_h = int(h.height()) + (self.table.frameWidth() * 2) + 4
        for row in range(self.table.rowCount()):
            total_h += int(self.table.rowHeight(row))
        self.table.setMinimumSize(int(total_w), int(total_h))
        self.table.setMaximumSize(int(total_w), int(total_h))
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
        self.project_menu_btn.setToolTip(
            "Save/load/compare plus admin tooling: disruption auto-repair, sandbox branches, and history snapshots."
            "\nAuto-repair: Project > Auto-Repair Disruption... then pick outage type and week to re-solve with unaffected activities frozen."
            "\nSandbox flow: start a branch, try edits, compare, then apply or discard."
        )
        self.mode_combo.setToolTip("Instance template used when generating data.")
        self.room_mode_combo.setToolTip(
            "Room assignment strategy:\n"
            "- Auto: strict room variables on small instances, greedy room assignment on large instances.\n"
            "- Strict: CP-SAT chooses rooms with room no-overlap constraints.\n"
            "- Fast: CP-SAT chooses times, then a greedy pass assigns rooms."
        )
        self.objective_profile_combo.setToolTip(
            "Solve profile:\n"
            "- Fast feasible: prioritize a valid timetable quickly.\n"
            "- University fast: large-instance time solve with separate greedy rooming.\n"
            "- University quality: university-fast feasibility plus bounded quality improvement.\n"
            "- Verification: strict CP room assignment for smaller or audit cases.\n"
            "- Balanced: feasibility first, then bounded quality improvement.\n"
            "- Quality-first: spend more of the budget on soft-penalty reduction."
        )
        self.objective_cb.setToolTip(
            "Solver modes:\n"
            "- CP: Strict room mode + objective OFF (feasible solution focus)\n"
            "- CP objective: Strict room mode + objective ON (optimize soft constraints)\n"
            "- Greedy: Fast room mode (rooms assigned greedily; fastest but less rigorous)"
        )
        self.debug_diagnostics_cb.setToolTip(
            "Show expanded solver diagnostics when a solve fails or is rejected: "
            "instance scale, room/staff/group pressure, raw metadata, and solver log tail."
        )
        self.view_type_combo.setToolTip("Choose whether the timetable is filtered by Group, Staff, Room, or All.")
        self.entity_combo.setToolTip("Select which entity to view in the timetable.")
        self.week_combo.setToolTip("Select academic week.")
        self.search_scope_combo.setToolTip(
            "Choose what the workspace search should scan."
        )
        self.search_edit.setToolTip(
            "Search activities, staff, rooms, or current conflicts."
        )
        self.search_button.setToolTip("Open searchable results and jump directly to matches.")
        self.time_limit_spin.setToolTip("Maximum solver runtime (seconds).")
        self.random_seed_spin.setToolTip(
            "Deterministic seed for CP-SAT and local improvement random choices."
        )
        self.hard_repeat_week_cb.setToolTip(
            "After the first/lecture-only week, recurring activities with the same "
            "course, kind, staff member, group set, and duration must use the same "
            "day, slot, and room."
        )
        self.hard_course_totals_cb.setToolTip(
            "Validate generated course metadata against the activity totals. "
            "Turn this off for raw imported timetables with incomplete course metadata."
        )
        self.hard_travel_buffers_cb.setToolTip(
            "Require configured transition buffers when shared staff/groups move between rooms."
        )
        self.hard_building_closures_cb.setToolTip(
            "Respect declared building or campus closure rules."
        )
        self.hard_calendar_rules_cb.setToolTip(
            "Respect calendar blackout, holiday, and special-week closure rules."
        )
        self.hard_precedence_rules_cb.setToolTip(
            "Enforce configured before/after activity precedence rules."
        )
        self.workers_preset_combo.setToolTip(
            "CP-SAT worker preset: Min=1 thread, Medium=about half cores, Max=all available cores."
        )
        self.custom_save_local_btn.setToolTip(
            "Save the current custom-generator table state to a local auto-reload file."
        )
        self.custom_save_cfg_btn.setToolTip(
            "Export current custom-generator settings to a JSON file."
        )
        self.custom_load_cfg_btn.setToolTip(
            "Import custom-generator settings from a JSON file."
        )
        self.custom_room_capacity_mode_combo.setToolTip(
            "Categorical mode locks capacities to SMALL/MEDIUM/BIG defaults; numeric mode uses exact room capacities."
        )
        self.constraint_template_combo.setToolTip(
            "Reusable hard/soft constraint profile."
        )
        self.constraint_template_apply_btn.setToolTip(
            "Apply selected template to controls and current instance."
        )
        self.constraint_template_save_btn.setToolTip(
            "Save current hard/soft settings as a reusable template."
        )
        self.apply_constraints_btn.setToolTip(
            "Apply the currently shown hard/soft controls into the active instance."
        )
        self.improve_runs_spin.setToolTip("Maximum local-search iterations.")
        self.ls_time_spin.setToolTip("Maximum local-search runtime (seconds).")
        self.improve_focus_combo.setToolTip(
            "Local-search improvement focus. Overall uses the normal soft-penalty weights. "
            "Choosing a term temporarily boosts that term during Improve, so the search spends "
            "more effort reducing that specific issue."
        )
        self.selected_activity_combo.setToolTip(
            "Activities in the currently selected cell.\n"
            "Click a timetable cell first, then choose an activity and use the quick actions."
        )
        self.quick_edit_btn.setToolTip(
            "Click a timetable cell, choose an activity, then edit its time/room/staff/locks."
        )
        self.quick_hold_btn.setToolTip(
            "Click a timetable cell, choose an activity, then hold it for drag-like moves.\n"
            "Hold mode: hover target slots to preview conflicts and score deltas before moving."
        )
        self.quick_bulk_btn.setToolTip(
            "Apply note/week/lock changes to all activities in the currently selected timetable cells."
        )
        self.quick_move_btn.setToolTip(
            "Move held activity to the selected day/slot.\n"
            "Use with hold mode hover previews to choose safer/better targets."
        )
        self.quick_swap_btn.setToolTip("Swap timeslots between held and selected activity.")
        self.quick_time_lock_btn.setToolTip("Toggle time lock for selected activity.")
        self.quick_room_lock_btn.setToolTip("Toggle room lock for selected activity.")
        self.quick_explain_btn.setToolTip(
            "Explain why the held move is valid/blocked and show actionable fixes."
        )
        self.quick_targets_btn.setToolTip("Show all valid target slots for the held activity.")
        self.quick_release_btn.setToolTip("Clear held activity selection.")
        self.show_score_deltas_cb.setToolTip(
            "Show/hide in-grid global soft-score deltas for held-move target slots."
        )
        self.history_undo5_btn.setToolTip("Undo the last 5 checkpoints at once.")
        self.history_redo5_btn.setToolTip("Redo the next 5 checkpoints at once.")
        self.history_save_snapshot_btn.setToolTip(
            "Save the current schedule/locks/held state to a dedicated JSON snapshot file."
        )
        self.history_load_snapshot_btn.setToolTip(
            "Load a previously saved snapshot as the current HEAD state."
        )
        self.history_open_snapshot_dir_btn.setToolTip(
            "Show where per-snapshot history files are stored."
        )
        self.custom_programs_spin.setToolTip("Number of programs to synthesize.")
        self.custom_groups_per_program_spin.setToolTip(
            "Default groups per program; can be overridden per-row below."
        )
        self.custom_group_size_spin.setToolTip(
            "Default students per group; can be overridden per program below."
        )
        self.custom_courses_per_program_spin.setToolTip(
            "Default courses per program; per-program/course-pattern overrides apply."
        )
        self.custom_course_names_edit.setToolTip(
            "Optional CSV. Example: Algorithms,Databases,Networks.\n"
            "If fewer names than required, generator auto-fills remaining courses."
        )
        self.custom_program_table.setToolTip(
            "Per-program overrides. Courses/Group accepts CSV of course IDs (e.g., 1,2,5)."
        )
        self.custom_course_pattern_table.setToolTip(
            "Per-course pattern: LEC/TUT/LAB counts by week. Zero counts are allowed."
        )
        self.custom_staff_table.setToolTip(
            "Staff mapping. Course IDs and day/week lists are CSV; week supports ALL."
        )
        self.custom_room_table.setToolTip(
            "Room mapping. In categorical mode, capacity follows SMALL/MEDIUM/BIG. "
            "In numeric mode, Capacity is authoritative."
        )

    def _build_schedule_actions_panel(self) -> QWidget:
        box = QGroupBox("Quick Admin Actions")
        layout = QVBoxLayout(box)

        self.quick_help_label = QLabel("Hover controls for usage tips.")
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
        self.quick_bulk_btn = QPushButton("Bulk Edit Selected")
        row1.addWidget(self.selected_slot_label)
        row1.addWidget(QLabel("Activity:"))
        row1.addWidget(self.selected_activity_combo)
        row1.addWidget(self.quick_edit_btn)
        row1.addWidget(self.quick_hold_btn)
        row1.addWidget(self.quick_bulk_btn)
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
        self.quick_explain_btn = QPushButton("Explain Move")
        self.quick_targets_btn = QPushButton("Show Held Targets")
        self.quick_release_btn = QPushButton("Release Held")
        row2.addWidget(self.held_slot_label)
        row2.addWidget(self.quick_move_btn)
        row2.addWidget(self.quick_swap_btn)
        row2.addWidget(self.quick_time_lock_btn)
        row2.addWidget(self.quick_room_lock_btn)
        row2.addWidget(self.quick_explain_btn)
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
        self.custom_save_local_btn.clicked.connect(self.on_save_custom_config_local)
        self.custom_save_cfg_btn.clicked.connect(self.on_save_custom_config_file)
        self.custom_load_cfg_btn.clicked.connect(self.on_load_custom_config_file)
        self.custom_room_capacity_mode_combo.currentIndexChanged.connect(
            self._on_room_capacity_mode_changed
        )
        self.staff_add_course_btn.clicked.connect(self._on_add_course_to_selected_staff)
        self.custom_programs_spin.valueChanged.connect(self._on_custom_size_changed)
        self.custom_groups_per_program_spin.valueChanged.connect(self._on_custom_size_changed)
        self.custom_group_size_spin.valueChanged.connect(self._on_custom_size_changed)
        self.custom_courses_per_program_spin.valueChanged.connect(self._on_custom_size_changed)
        self.custom_course_names_edit.textChanged.connect(self._refresh_staff_course_picker)
        self.custom_course_names_edit.textChanged.connect(
            self._reset_custom_course_pattern_table
        )
        self.custom_program_table.itemChanged.connect(self._on_custom_program_table_item_changed)
        self.custom_room_table.itemChanged.connect(self._on_room_table_item_changed)
        self.apply_constraints_btn.clicked.connect(self.on_apply_constraints_to_instance)
        self.constraint_template_apply_btn.clicked.connect(self.on_apply_constraint_template)
        self.constraint_template_save_btn.clicked.connect(self.on_save_constraint_template)
        self.view_type_combo.currentIndexChanged.connect(self.update_entities)
        self.entity_combo.currentIndexChanged.connect(self.update_table)
        self.week_combo.currentIndexChanged.connect(self.update_table)
        self.search_button.clicked.connect(self.on_run_search)
        self.search_edit.returnPressed.connect(self.on_run_search)
        self.selected_activity_combo.currentIndexChanged.connect(
            self.on_selected_activity_changed
        )
        self.table.itemSelectionChanged.connect(self._refresh_quick_actions)
        self.table.dragRequested.connect(self._on_schedule_drag_requested)
        self.table.dropRequested.connect(self._on_schedule_drop_requested)
        self.quick_edit_btn.clicked.connect(self.on_quick_edit_selected)
        self.quick_hold_btn.clicked.connect(self.on_quick_hold_selected)
        self.quick_bulk_btn.clicked.connect(self.on_quick_bulk_edit_selected)
        self.quick_move_btn.clicked.connect(self.on_quick_move_held_here)
        self.quick_swap_btn.clicked.connect(self.on_quick_swap_held_with_selected)
        self.quick_time_lock_btn.clicked.connect(self.on_quick_toggle_time_lock)
        self.quick_room_lock_btn.clicked.connect(self.on_quick_toggle_room_lock)
        self.quick_explain_btn.clicked.connect(self.on_quick_explain_move)
        self.quick_targets_btn.clicked.connect(self.on_quick_show_held_targets)
        self.quick_release_btn.clicked.connect(self.on_quick_release_held)
        self.show_score_deltas_cb.toggled.connect(lambda _v: self.update_table())
        self.history_undo5_btn.clicked.connect(lambda: self._undo_many(5))
        self.history_redo5_btn.clicked.connect(lambda: self._redo_many(5))
        self.history_save_snapshot_btn.clicked.connect(self.on_save_history_snapshot)
        self.history_load_snapshot_btn.clicked.connect(self.on_load_history_snapshot)
        self.history_open_snapshot_dir_btn.clicked.connect(self.on_show_snapshot_dir)
        self.history_list.itemDoubleClicked.connect(self.on_history_item_activated)
        self.why_not_run_btn.clicked.connect(self.on_explain_candidate_slot)
        self.heatmap_entity_kind_combo.currentIndexChanged.connect(
            self._refresh_heatmap_entities
        )
        self.heatmap_entity_combo.currentIndexChanged.connect(self._update_heatmap_table)
        self.heatmap_metric_combo.currentIndexChanged.connect(self._update_heatmap_table)
        self.export_quality_report_btn.clicked.connect(self.on_export_quality_report)
        self.table.cellClicked.connect(self.on_table_cell_clicked)
        self.table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        self.table.customContextMenuRequested.connect(self.on_table_context_menu)
        self.hard_week1_cb.toggled.connect(self.on_constraint_controls_changed)
        self.hard_repeat_week_cb.toggled.connect(self.on_constraint_controls_changed)
        self.hard_course_totals_cb.toggled.connect(self.on_constraint_controls_changed)
        self.hard_block_prof_cb.toggled.connect(self.on_constraint_controls_changed)
        self.hard_staff_daily_cb.toggled.connect(self.on_constraint_controls_changed)
        self.hard_staff_weekly_cb.toggled.connect(self.on_constraint_controls_changed)
        self.hard_room_availability_cb.toggled.connect(self.on_constraint_controls_changed)
        self.hard_travel_buffers_cb.toggled.connect(self.on_constraint_controls_changed)
        self.hard_building_closures_cb.toggled.connect(self.on_constraint_controls_changed)
        self.hard_calendar_rules_cb.toggled.connect(self.on_constraint_controls_changed)
        self.hard_precedence_rules_cb.toggled.connect(self.on_constraint_controls_changed)
        self.objective_profile_combo.currentIndexChanged.connect(
            self.on_constraint_controls_changed
        )
        for spin in self.soft_weight_spins.values():
            spin.valueChanged.connect(self.on_constraint_controls_changed)
        self._setup_shortcuts()

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
        act_feed = QAction("Export Calendar Feeds", self)
        act_feed.triggered.connect(self.on_export_calendar_feeds)
        act_sis = QAction("Export SIS CSV", self)
        act_sis.triggered.connect(self.on_export_sis_csv)
        act_erp = QAction("Export ERP CSV", self)
        act_erp.triggered.connect(self.on_export_erp_csv)
        act_lms = QAction("Export LMS CSV", self)
        act_lms.triggered.connect(self.on_export_lms_csv)

        self.export_menu.addAction(act_docx)
        self.export_menu.addAction(act_pdf)
        self.export_menu.addSeparator()
        self.export_menu.addAction(act_reports)
        self.export_menu.addAction(act_csv)
        self.export_menu.addAction(act_ics)
        self.export_menu.addAction(act_feed)
        self.export_menu.addSeparator()
        self.export_menu.addAction(act_sis)
        self.export_menu.addAction(act_erp)
        self.export_menu.addAction(act_lms)

        # Project menu
        act_save = QAction("Save Project", self)
        act_save.triggered.connect(self.on_save_project)
        act_load = QAction("Load Project", self)
        act_load.triggered.connect(self.on_load_project)
        act_compare = QAction("Compare", self)
        act_compare.triggered.connect(self.on_compare)
        act_portfolio = QAction("Portfolio Solve Report", self)
        act_portfolio.triggered.connect(self.on_portfolio_solve_report)
        act_score_breakdown = QAction("Score Breakdown", self)
        act_score_breakdown.triggered.connect(self.on_show_score_breakdown)
        act_set_operator = QAction("Set Operator Name", self)
        act_set_operator.triggered.connect(self.on_set_operator_name)
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
        act_save_product = QAction("Save Product Scenario", self)
        act_save_product.triggered.connect(self.on_save_product_scenario)
        act_load_product = QAction("Load Product Scenario", self)
        act_load_product.triggered.connect(self.on_load_product_scenario)
        act_save_institution = QAction("Save Institution Template", self)
        act_save_institution.triggered.connect(self.on_save_institution_template)
        act_load_institution = QAction("Load Institution Template", self)
        act_load_institution.triggered.connect(self.on_load_institution_template)
        act_white_label = QAction("Apply White-Label Institution Profile", self)
        act_white_label.triggered.connect(self.on_apply_white_label_profile)
        act_load_sched = QAction("Load Schedule (CSV)", self)
        act_load_sched.triggered.connect(self.on_load_schedule)
        act_import_timetable = QAction("Import Timetable CSV (create scenario)", self)
        act_import_timetable.triggered.connect(self.on_import_timetable_csv)
        act_import_wizard = QAction("Import Schedule Wizard (CSV)", self)
        act_import_wizard.triggered.connect(self.on_import_schedule_wizard)
        act_save_ie_template = QAction("Save Import/Export Template", self)
        act_save_ie_template.triggered.connect(self.on_save_import_export_template)
        act_load_ie_template = QAction("Load Import/Export Template", self)
        act_load_ie_template.triggered.connect(self.on_load_import_export_template)
        act_disruption = QAction("Auto-Repair Disruption...", self)
        act_disruption.triggered.connect(self.on_auto_repair_disruption)
        act_fix_conflicts = QAction("Fix Current Conflicts", self)
        act_fix_conflicts.triggered.connect(self.on_fix_current_conflicts)
        act_cp_polish = QAction("Focused CP-SAT Polish", self)
        act_cp_polish.triggered.connect(self.on_focused_cp_sat_polish)
        act_sandbox_start = QAction("Sandbox: Start Branch", self)
        act_sandbox_start.triggered.connect(self.on_sandbox_start)
        act_branch_save = QAction("Branch: Save Named Branch", self)
        act_branch_save.triggered.connect(self.on_save_named_branch)
        act_branch_load = QAction("Branch: Load Named Branch", self)
        act_branch_load.triggered.connect(self.on_load_named_branch)
        act_branch_merge = QAction("Branch: Merge Assistance", self)
        act_branch_merge.triggered.connect(self.on_branch_merge_assistance)
        act_sandbox_compare = QAction("Sandbox: Compare", self)
        act_sandbox_compare.triggered.connect(self.on_sandbox_compare)
        act_sandbox_apply = QAction("Sandbox: Apply Branch", self)
        act_sandbox_apply.triggered.connect(self.on_sandbox_apply)
        act_sandbox_discard = QAction("Sandbox: Discard Branch", self)
        act_sandbox_discard.triggered.connect(self.on_sandbox_discard)
        act_release_create = QAction("Release: Create Candidate", self)
        act_release_create.triggered.connect(self.on_create_release_candidate)
        act_release_publish = QAction("Release: Publish Candidate", self)
        act_release_publish.triggered.connect(self.on_publish_release_candidate)
        act_protect_base = QAction("Release: Toggle Protected Baseline", self)
        act_protect_base.triggered.connect(self.on_toggle_protected_baseline)
        act_sync_bundle = QAction("Export Calendar Sync Bundle", self)
        act_sync_bundle.triggered.connect(self.on_export_calendar_sync_bundle)
        act_quality_report = QAction("Export Quality Report", self)
        act_quality_report.triggered.connect(self.on_export_quality_report)
        act_updates = QAction("Check Update Channel", self)
        act_updates.triggered.connect(self.on_check_updates)
        act_set_update_channel = QAction("Set Update Channel", self)
        act_set_update_channel.triggered.connect(self.on_set_update_channel)
        act_support_bundle = QAction("Export Support Bundle", self)
        act_support_bundle.triggered.connect(self.on_export_support_bundle)
        act_toggle_crash = QAction("Toggle Crash Reports", self)
        act_toggle_crash.triggered.connect(self.on_toggle_crash_reports_opt_in)
        act_toggle_telemetry = QAction("Toggle Telemetry", self)
        act_toggle_telemetry.triggered.connect(self.on_toggle_telemetry_opt_in)
        act_runtime_logs = QAction("Show Runtime Log Folder", self)
        act_runtime_logs.triggered.connect(self.on_show_runtime_log_folder)
        act_show_history = QAction("Show Workspace Change History", self)
        act_show_history.triggered.connect(self.on_show_change_history)
        act_audit_log = QAction("Show Audit Log Path", self)
        act_audit_log.triggered.connect(self.on_show_audit_log_path)
        act_about = QAction(f"About {APP_SHORT_NAME}", self)
        act_about.triggered.connect(self.on_show_about)

        file_menu = self.project_menu.addMenu("File")
        file_menu.addAction(act_save)
        file_menu.addAction(act_load)
        file_menu.addAction(act_load_inst)
        product_menu = file_menu.addMenu("Product Scenario")
        product_menu.addAction(act_save_product)
        product_menu.addAction(act_load_product)

        import_menu = self.project_menu.addMenu("Import")
        import_menu.addAction(act_import_timetable)
        import_menu.addAction(act_import_wizard)
        import_menu.addAction(act_load_sched)
        template_menu = import_menu.addMenu("Import/Export Templates")
        template_menu.addAction(act_save_ie_template)
        template_menu.addAction(act_load_ie_template)

        reports_menu = self.project_menu.addMenu("Reports")
        reports_menu.addAction(act_quality_report)
        reports_menu.addAction(act_sync_bundle)

        analyze_menu = self.project_menu.addMenu("Analyze")
        analyze_menu.addAction(act_conflicts)
        analyze_menu.addAction(act_score_breakdown)
        analyze_menu.addAction(act_compare)
        analyze_menu.addAction(act_portfolio)
        analyze_menu.addAction(act_show_history)

        edit_menu = self.project_menu.addMenu("Edit")
        edit_menu.addAction(act_undo)
        edit_menu.addAction(act_redo)
        edit_menu.addAction(act_revert)

        repair_menu = self.project_menu.addMenu("Repair")
        repair_menu.addAction(act_fix_conflicts)
        repair_menu.addAction(act_cp_polish)
        repair_menu.addSeparator()
        repair_menu.addAction(act_disruption)

        branch_menu = self.project_menu.addMenu("Branches")
        branch_menu.addAction(act_sandbox_start)
        branch_menu.addAction(act_branch_save)
        branch_menu.addAction(act_branch_load)
        branch_menu.addAction(act_branch_merge)
        branch_menu.addSeparator()
        branch_menu.addAction(act_sandbox_compare)
        branch_menu.addAction(act_sandbox_apply)
        branch_menu.addAction(act_sandbox_discard)

        release_menu = self.project_menu.addMenu("Release")
        release_menu.addAction(act_release_create)
        release_menu.addAction(act_release_publish)
        release_menu.addAction(act_protect_base)

        institution_menu = self.project_menu.addMenu("Institution")
        institution_menu.addAction(act_set_operator)
        institution_menu.addAction(act_save_institution)
        institution_menu.addAction(act_load_institution)
        institution_menu.addAction(act_white_label)

        settings_menu = self.project_menu.addMenu("Settings & Diagnostics")
        settings_menu.addAction(act_updates)
        settings_menu.addAction(act_set_update_channel)
        settings_menu.addSeparator()
        settings_menu.addAction(act_support_bundle)
        settings_menu.addAction(act_runtime_logs)
        settings_menu.addAction(act_audit_log)
        settings_menu.addSeparator()
        settings_menu.addAction(act_toggle_crash)
        settings_menu.addAction(act_toggle_telemetry)

        self.project_menu.addSeparator()
        self.project_menu.addAction(act_about)

    def _setup_shortcuts(self) -> None:
        shortcuts: List[Tuple[str, str, Any, str]] = [
            ("Ctrl+G", "Generate instance", self.on_generate, "generate new instance"),
            ("Ctrl+R", "Solve schedule", self.on_solve, "solve schedule"),
            ("Ctrl+I", "Improve schedule", self.on_improve, "improve current schedule"),
            ("Ctrl+F", "Search workspace", self.on_run_search, "search schedule workspace"),
            ("Ctrl+Shift+P", "Open command palette", self.on_open_command_palette, "command palette"),
            ("Ctrl+Shift+C", "Show conflicts", self.on_show_conflicts, "show hard conflicts"),
            ("Ctrl+Shift+S", "Portfolio solve report", self.on_portfolio_solve_report, "portfolio solve report"),
            ("", "Import timetable CSV", self.on_import_timetable_csv, "import csv timetable create scenario"),
            ("", "Fix current conflicts", self.on_fix_current_conflicts, "repair solve conflicts current hard"),
            ("", "Focused CP-SAT polish", self.on_focused_cp_sat_polish, "cp sat polish neighborhood focus"),
            ("", "Show score breakdown", self.on_show_score_breakdown, "quality penalty score drivers"),
            ("", "Export quality report", self.on_export_quality_report, "quality report export"),
        ]
        self._command_actions: List[QAction] = []
        for shortcut, text, callback, keywords in shortcuts:
            action = QAction(str(text), self)
            if str(shortcut):
                action.setShortcut(str(shortcut))
            action.triggered.connect(callback)
            action.setData({"label": str(text), "keywords": str(keywords), "callback": callback})
            self.addAction(action)
            self._command_actions.append(action)

    def on_open_command_palette(self) -> None:
        entries: List[Dict[str, Any]] = []
        for action in getattr(self, "_command_actions", []):
            payload = action.data()
            if isinstance(payload, dict):
                entries.append(dict(payload))
        dlg = CommandPaletteDialog(self, entries)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        payload = dlg.selected_command()
        callback = payload.get("callback") if isinstance(payload, dict) else None
        if callable(callback):
            callback()

    def _build_collapsible_section(
        self,
        title: str,
        content: QWidget,
        *,
        collapsed: bool = True,
    ) -> QWidget:
        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(4)

        toggle = QToolButton(wrapper)
        toggle.setText(str(title))
        toggle.setCheckable(True)
        toggle.setChecked(not collapsed)
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setArrowType(
            Qt.ArrowType.DownArrow if not collapsed else Qt.ArrowType.RightArrow
        )
        toggle.setProperty("sectionToggle", True)
        toggle.setStyleSheet("QToolButton { font-weight: 600; text-align: left; }")

        content.setVisible(not collapsed)

        def _on_toggle(opened: bool) -> None:
            content.setVisible(bool(opened))
            toggle.setArrowType(
                Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow
            )

        toggle.toggled.connect(_on_toggle)
        wrapper_layout.addWidget(toggle)
        wrapper_layout.addWidget(content)
        return wrapper

    def _ensure_custom_generator_seeded(self) -> None:
        # Keep custom tables populated even after resize/layout edge-cases.
        try:
            if hasattr(self, "custom_program_table") and self.custom_program_table.rowCount() <= 0:
                self._reset_custom_program_table()
            if hasattr(self, "custom_course_pattern_table") and self.custom_course_pattern_table.rowCount() <= 0:
                self._reset_custom_course_pattern_table()
            if hasattr(self, "custom_staff_table") and self.custom_staff_table.rowCount() <= 0:
                self._reset_custom_staff_table()
            if hasattr(self, "custom_room_table") and self.custom_room_table.rowCount() <= 0:
                self._reset_custom_room_table()
            if hasattr(self, "staff_course_picker_combo"):
                self._refresh_staff_course_picker()
            if hasattr(self, "custom_room_capacity_mode_combo"):
                self._apply_room_capacity_mode()
            self._normalize_custom_table_item_types()
        except Exception:
            traceback.print_exc()

    def _normalize_custom_table_item_types(self) -> None:
        """Ensure key sortable columns use numeric-aware item classes."""
        if hasattr(self, "custom_program_table"):
            was_sorting = self.custom_program_table.isSortingEnabled()
            self.custom_program_table.setSortingEnabled(False)
            for row in range(self.custom_program_table.rowCount()):
                item = self.custom_program_table.item(row, 0)
                txt = str(item.text()).strip() if item is not None else str(row + 1)
                self.custom_program_table.setItem(
                    row, 0, self._make_locked_item(txt, numeric=True)
                )
                name_item = self.custom_program_table.item(row, 1)
                if name_item is not None:
                    self.custom_program_table.setItem(
                        row, 1, NaturalSortTableItem(str(name_item.text()))
                    )
            self.custom_program_table.setSortingEnabled(was_sorting)
        if hasattr(self, "custom_course_pattern_table"):
            was_sorting = self.custom_course_pattern_table.isSortingEnabled()
            self.custom_course_pattern_table.setSortingEnabled(False)
            for row in range(self.custom_course_pattern_table.rowCount()):
                id_item = self.custom_course_pattern_table.item(row, 0)
                id_txt = str(id_item.text()).strip() if id_item is not None else str(row + 1)
                self.custom_course_pattern_table.setItem(
                    row, 0, self._make_locked_item(id_txt, numeric=True)
                )
                name_item = self.custom_course_pattern_table.item(row, 1)
                if name_item is not None:
                    name_txt = str(name_item.text())
                    self.custom_course_pattern_table.setItem(
                        row, 1, self._make_locked_item(name_txt, natural=True)
                    )
            self.custom_course_pattern_table.setSortingEnabled(was_sorting)
        if hasattr(self, "custom_staff_table"):
            was_sorting = self.custom_staff_table.isSortingEnabled()
            self.custom_staff_table.setSortingEnabled(False)
            for row in range(self.custom_staff_table.rowCount()):
                name_item = self.custom_staff_table.item(row, 0)
                if name_item is not None:
                    self.custom_staff_table.setItem(
                        row, 0, NaturalSortTableItem(str(name_item.text()))
                    )
            self.custom_staff_table.setSortingEnabled(was_sorting)
        if hasattr(self, "custom_room_table"):
            was_sorting = self.custom_room_table.isSortingEnabled()
            self.custom_room_table.setSortingEnabled(False)
            for row in range(self.custom_room_table.rowCount()):
                name_item = self.custom_room_table.item(row, 0)
                if name_item is not None:
                    self.custom_room_table.setItem(
                        row, 0, NaturalSortTableItem(str(name_item.text()))
                    )
            self.custom_room_table.setSortingEnabled(was_sorting)

    def _build_generator_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        counts_box = QGroupBox("Scenario Size")
        counts_form = QFormLayout(counts_box)
        self.custom_programs_spin = StepSpinBox()
        self.custom_programs_spin.setRange(1, 200)
        self.custom_programs_spin.setValue(20)
        self.custom_groups_per_program_spin = StepSpinBox()
        self.custom_groups_per_program_spin.setRange(1, 20)
        self.custom_groups_per_program_spin.setValue(2)
        self.custom_group_size_spin = StepSpinBox()
        self.custom_group_size_spin.setRange(1, 2000)
        self.custom_group_size_spin.setValue(60)
        self.custom_courses_per_program_spin = StepSpinBox()
        self.custom_courses_per_program_spin.setRange(1, 20)
        self.custom_courses_per_program_spin.setValue(6)
        self.custom_slots_per_day_spin = StepSpinBox()
        self.custom_slots_per_day_spin.setRange(3, 16)
        self.custom_slots_per_day_spin.setValue(5)
        self.custom_days_edit = QLineEdit()
        self.custom_days_edit.setText("MON,TUE,WED,THU,FRI,SAT")
        self.custom_weeks_edit = QLineEdit()
        self.custom_weeks_edit.setText("1-12")
        self.custom_term_blocks_edit = QLineEdit()
        self.custom_term_blocks_edit.setPlaceholderText(
            "Optional named blocks: Teaching A:8, Exams:2, Teaching B:6"
        )
        self.custom_term_blocks_edit.setToolTip(
            "Optional arbitrary term layout. Format: Label:length_weeks, !NonTeaching:length_weeks.\n"
            "When present, this overrides the plain Teaching weeks field."
        )
        self.custom_course_names_edit = QLineEdit()
        self.custom_course_names_edit.setPlaceholderText(
            "Optional CSV names: Algorithms,Databases,Networks,..."
        )
        counts_form.addRow("Programs", self.custom_programs_spin)
        counts_form.addRow("Groups per program", self.custom_groups_per_program_spin)
        counts_form.addRow("Students per group", self.custom_group_size_spin)
        counts_form.addRow("Courses per program", self.custom_courses_per_program_spin)
        counts_form.addRow("Slots per day", self.custom_slots_per_day_spin)
        counts_form.addRow("Teaching days (CSV)", self.custom_days_edit)
        counts_form.addRow("Teaching weeks", self.custom_weeks_edit)
        counts_form.addRow("Term blocks", self.custom_term_blocks_edit)
        counts_form.addRow("Course names (CSV)", self.custom_course_names_edit)
        cfg_row = QWidget()
        cfg_row_layout = QHBoxLayout(cfg_row)
        cfg_row_layout.setContentsMargins(0, 0, 0, 0)
        cfg_row_layout.setSpacing(6)
        self.custom_save_local_btn = QPushButton("Save Local")
        self.custom_save_cfg_btn = QPushButton("Save Config...")
        self.custom_load_cfg_btn = QPushButton("Load Config...")
        cfg_row_layout.addWidget(self.custom_save_local_btn)
        cfg_row_layout.addWidget(self.custom_save_cfg_btn)
        cfg_row_layout.addWidget(self.custom_load_cfg_btn)
        cfg_row_layout.addStretch(1)
        counts_form.addRow("Custom config", cfg_row)
        layout.addWidget(
            self._build_collapsible_section("Scenario Size", counts_box, collapsed=True)
        )

        plan_box = QGroupBox("Program/Course Overrides")
        plan_layout = QVBoxLayout(plan_box)
        plan_controls = QHBoxLayout()
        self.custom_reset_programs_btn = QPushButton("Reset Program Rows")
        self.custom_reset_course_patterns_btn = QPushButton("Reset Course Patterns")
        plan_controls.addWidget(self.custom_reset_programs_btn)
        plan_controls.addWidget(self.custom_reset_course_patterns_btn)
        plan_controls.addStretch(1)
        plan_layout.addLayout(plan_controls)

        self.custom_program_table = QTableWidget(0, 6)
        self.custom_program_table.setHorizontalHeaderLabels(
            ["Program ID", "Program Name", "Groups", "Group Size", "Courses", "Courses/Group"]
        )
        self.custom_program_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.custom_program_table.verticalHeader().setVisible(False)
        self.custom_program_table.setSortingEnabled(True)
        self.custom_program_table.setMinimumHeight(220)
        self.custom_program_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        plan_layout.addWidget(self.custom_program_table)

        self.custom_course_pattern_table = QTableWidget(0, 8)
        self.custom_course_pattern_table.setHorizontalHeaderLabels(
            [
                "Course ID",
                "Course Name",
                "LEC Count",
                "TUT Count",
                "Lab Count",
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
        self.custom_course_pattern_table.setMinimumHeight(300)
        self.custom_course_pattern_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        plan_layout.addWidget(self.custom_course_pattern_table)

        plan_hint = QLabel(
            "Program rows allow different groups/courses per program and courses per group.\n"
            "Course pattern rows allow per-course LEC/TUT/LAB totals and lab type (NONE/NORMAL/SPECIAL).\n"
            "Course structure is inferred from counts (e.g., lab-only, lec-only, tut-only)."
        )
        plan_hint.setWordWrap(True)
        plan_layout.addWidget(plan_hint)
        layout.addWidget(
            self._build_collapsible_section(
                "Program/Course Overrides", plan_box, collapsed=True
            )
        )

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
        self.custom_staff_table = QTableWidget(0, 5)
        self.custom_staff_table.setHorizontalHeaderLabels(
            [
                "Staff",
                "Role",
                "Course IDs (csv)",
                "Available Days (csv)",
                "Available Weeks (csv or ALL)",
            ]
        )
        self.custom_staff_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.custom_staff_table.horizontalHeader().setSectionsClickable(True)
        self.custom_staff_table.horizontalHeader().setSortIndicatorShown(True)
        self.custom_staff_table.verticalHeader().setVisible(False)
        self.custom_staff_table.setSortingEnabled(True)
        self.custom_staff_table.setMinimumHeight(360)
        self.custom_staff_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        staff_layout.addWidget(self.custom_staff_table)
        layout.addWidget(
            self._build_collapsible_section("Staff Mapping", staff_box, collapsed=True)
        )

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
        room_controls.addWidget(QLabel("Capacity mode"))
        self.custom_room_capacity_mode_combo = QComboBox()
        for label, mode in ROOM_CAPACITY_MODE_CHOICES:
            self.custom_room_capacity_mode_combo.addItem(str(label), str(mode))
        numeric_idx = self.custom_room_capacity_mode_combo.findData("numeric")
        if numeric_idx >= 0:
            self.custom_room_capacity_mode_combo.setCurrentIndex(numeric_idx)
        room_controls.addWidget(self.custom_room_capacity_mode_combo)
        room_controls.addStretch(1)
        room_layout.addLayout(room_controls)
        self.custom_room_table = QTableWidget(0, 9)
        self.custom_room_table.setHorizontalHeaderLabels(
            [
                "Name",
                "Type",
                "Category",
                "Capacity",
                "Campus",
                "Building",
                "Floor",
                "Features (csv)",
                "Tags (csv for specialized labs)",
            ]
        )
        self.custom_room_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.custom_room_table.horizontalHeader().setSectionsClickable(True)
        self.custom_room_table.horizontalHeader().setSortIndicatorShown(True)
        self.custom_room_table.verticalHeader().setVisible(False)
        self.custom_room_table.setSortingEnabled(True)
        self.custom_room_table.setMinimumHeight(280)
        self.custom_room_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        room_layout.addWidget(self.custom_room_table)
        layout.addWidget(
            self._build_collapsible_section("Room Definitions", room_box, collapsed=True)
        )

        hint = QLabel(
            "Use mode 'custom' to generate from these tables.\n"
            "Room capacity mode controls whether category labels or exact capacities are authoritative."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        return scroll

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
        self.hard_repeat_week_cb = QCheckBox("Force same weekly pattern after week 1")
        self.hard_course_totals_cb = QCheckBox("Enforce course total metadata")
        self.hard_travel_buffers_cb = QCheckBox("Enforce travel-time buffers")
        self.hard_building_closures_cb = QCheckBox("Enforce building closures")
        self.hard_calendar_rules_cb = QCheckBox("Enforce calendar blackout rules")
        self.hard_precedence_rules_cb = QCheckBox("Enforce activity precedence rules")
        hard_layout.addWidget(self.hard_week1_cb)
        hard_layout.addWidget(self.hard_repeat_week_cb)
        hard_layout.addWidget(self.hard_course_totals_cb)
        hard_layout.addWidget(self.hard_block_prof_cb)
        hard_layout.addWidget(self.hard_staff_daily_cb)
        hard_layout.addWidget(self.hard_staff_weekly_cb)
        hard_layout.addWidget(self.hard_room_availability_cb)
        hard_layout.addWidget(self.hard_travel_buffers_cb)
        hard_layout.addWidget(self.hard_building_closures_cb)
        hard_layout.addWidget(self.hard_calendar_rules_cb)
        hard_layout.addWidget(self.hard_precedence_rules_cb)
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
            (
                "same_kind_week",
                "Same-course weekly bunching",
                3,
                "Penalizes placing multiple lecture/tutorial sessions of the same course into one week for a group.",
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

        template_row = QHBoxLayout()
        template_row.addWidget(QLabel("Template"))
        self.constraint_template_combo = QComboBox()
        template_row.addWidget(self.constraint_template_combo)
        self.constraint_template_apply_btn = QPushButton("Apply Template")
        self.constraint_template_save_btn = QPushButton("Save As Template")
        template_row.addWidget(self.constraint_template_apply_btn)
        template_row.addWidget(self.constraint_template_save_btn)
        template_row.addStretch(1)
        layout.addLayout(template_row)

        self.apply_constraints_btn = QPushButton("Apply Constraints To Current Instance")
        layout.addWidget(self.apply_constraints_btn)
        layout.addStretch(1)
        return tab

    def _build_fairness_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.fairness_summary_label = QLabel("Generate/solve to view fairness dashboard.")
        self.fairness_summary_label.setWordWrap(True)
        self.fairness_summary_label.setToolTip(
            "Lower fairness score is better. Scores aggregate total load, active days, gaps, and late events."
        )
        layout.addWidget(self.fairness_summary_label)

        group_headers = [
            "Group",
            "Total Slots",
            "Active Days",
            "Single Days",
            "Gap Slots",
            "Late Events",
            "Avg Weekly Load",
            "Fairness Score",
        ]
        self.fairness_group_model = SimpleTableModel(group_headers, [])
        self.fairness_group_table = QTableView()
        self.fairness_group_table.setModel(self.fairness_group_model)
        self.fairness_group_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.fairness_group_table.setSortingEnabled(True)
        layout.addWidget(QLabel("Group Fairness"))
        layout.addWidget(self.fairness_group_table)

        staff_headers = [
            "Staff",
            "Role",
            "Total Slots",
            "Active Days",
            "Single Days",
            "Gap Slots",
            "Late Events",
            "Avg Weekly Load",
            "Fairness Score",
        ]
        self.fairness_staff_model = SimpleTableModel(staff_headers, [])
        self.fairness_staff_table = QTableView()
        self.fairness_staff_table.setModel(self.fairness_staff_model)
        self.fairness_staff_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.fairness_staff_table.setSortingEnabled(True)
        layout.addWidget(QLabel("Staff Fairness"))
        layout.addWidget(self.fairness_staff_table)
        return tab

    def _build_diagnostics_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.diagnostics_summary_text = QPlainTextEdit()
        self.diagnostics_summary_text.setReadOnly(True)
        self.diagnostics_summary_text.setPlaceholderText(
            "Generate, solve, or load a schedule to inspect infeasibility diagnoses and quality risks."
        )
        layout.addWidget(QLabel("Unsat-style Rule Diagnosis"))
        layout.addWidget(self.diagnostics_summary_text)

        why_not_box = QGroupBox("Why Not This Slot?")
        why_not_layout = QGridLayout(why_not_box)
        self.why_not_activity_combo = QComboBox()
        self.why_not_week_combo = QComboBox()
        self.why_not_day_combo = QComboBox()
        self.why_not_slot_combo = QComboBox()
        self.why_not_run_btn = QPushButton("Explain Candidate Slot")
        self.why_not_output_text = QPlainTextEdit()
        self.why_not_output_text.setReadOnly(True)
        why_not_layout.addWidget(QLabel("Activity"), 0, 0)
        why_not_layout.addWidget(self.why_not_activity_combo, 0, 1)
        why_not_layout.addWidget(QLabel("Week"), 0, 2)
        why_not_layout.addWidget(self.why_not_week_combo, 0, 3)
        why_not_layout.addWidget(QLabel("Day"), 1, 0)
        why_not_layout.addWidget(self.why_not_day_combo, 1, 1)
        why_not_layout.addWidget(QLabel("Slot"), 1, 2)
        why_not_layout.addWidget(self.why_not_slot_combo, 1, 3)
        why_not_layout.addWidget(self.why_not_run_btn, 2, 0, 1, 4)
        why_not_layout.addWidget(self.why_not_output_text, 3, 0, 1, 4)
        layout.addWidget(why_not_box)

        heatmap_box = QGroupBox("Heatmaps")
        heatmap_layout = QGridLayout(heatmap_box)
        self.heatmap_entity_kind_combo = QComboBox()
        self.heatmap_entity_kind_combo.addItem("Group", "groups")
        self.heatmap_entity_kind_combo.addItem("Staff", "staff")
        self.heatmap_entity_combo = QComboBox()
        self.heatmap_metric_combo = QComboBox()
        self.heatmap_metric_combo.addItem("Load", "load")
        self.heatmap_metric_combo.addItem("Gaps", "gaps")
        self.heatmap_metric_combo.addItem("Instability", "instability")
        self.heatmap_summary_label = QLabel("Heatmaps unavailable until a schedule is loaded.")
        self.heatmap_summary_label.setWordWrap(True)
        self.heatmap_table = QTableWidget(0, 0)
        self.heatmap_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        heatmap_layout.addWidget(QLabel("Entity type"), 0, 0)
        heatmap_layout.addWidget(self.heatmap_entity_kind_combo, 0, 1)
        heatmap_layout.addWidget(QLabel("Entity"), 0, 2)
        heatmap_layout.addWidget(self.heatmap_entity_combo, 0, 3)
        heatmap_layout.addWidget(QLabel("Metric"), 1, 0)
        heatmap_layout.addWidget(self.heatmap_metric_combo, 1, 1)
        heatmap_layout.addWidget(self.heatmap_summary_label, 1, 2, 1, 2)
        heatmap_layout.addWidget(self.heatmap_table, 2, 0, 1, 4)
        layout.addWidget(heatmap_box)

        quality_row = QHBoxLayout()
        self.export_quality_report_btn = QPushButton("Export Quality Report")
        quality_row.addWidget(self.export_quality_report_btn)
        quality_row.addStretch(1)
        layout.addLayout(quality_row)
        layout.addStretch(1)
        return tab

    def _build_history_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.history_help_label = QLabel(
            "Git-like timeline: older checkpoints on top, current HEAD in the middle, redo states below.\n"
            "Double-click an entry to jump directly (multi-step undo/redo)."
        )
        self.history_help_label.setWordWrap(True)
        layout.addWidget(self.history_help_label)

        self.history_list = QListWidget()
        self.history_list.setAlternatingRowColors(True)
        self.history_list.setToolTip(
            "Timeline entries; each can include a saved snapshot path for external backups."
        )
        layout.addWidget(self.history_list, 1)

        row = QHBoxLayout()
        self.history_undo5_btn = QPushButton("Undo 5")
        self.history_redo5_btn = QPushButton("Redo 5")
        self.history_save_snapshot_btn = QPushButton("Save Snapshot...")
        self.history_load_snapshot_btn = QPushButton("Load Snapshot...")
        self.history_open_snapshot_dir_btn = QPushButton("Show Snapshot Folder")
        row.addWidget(self.history_undo5_btn)
        row.addWidget(self.history_redo5_btn)
        row.addWidget(self.history_save_snapshot_btn)
        row.addWidget(self.history_load_snapshot_btn)
        row.addWidget(self.history_open_snapshot_dir_btn)
        row.addStretch(1)
        layout.addLayout(row)
        return tab

    @staticmethod
    def _infer_room_category(capacity: int) -> str:
        if capacity <= 80:
            return "SMALL"
        if capacity <= 180:
            return "MEDIUM"
        return "BIG"

    @staticmethod
    def _make_locked_item(
        text: str, *, numeric: bool = False, natural: bool = False
    ) -> QTableWidgetItem:
        if numeric:
            item: QTableWidgetItem = NumericTableItem(text)
        elif natural:
            item = NaturalSortTableItem(text)
        else:
            item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    @staticmethod
    def _make_numeric_item(value: Any) -> QTableWidgetItem:
        return NumericTableItem(str(value))

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

    def _room_capacity_mode(self) -> str:
        if not hasattr(self, "custom_room_capacity_mode_combo"):
            return "numeric"
        data = self.custom_room_capacity_mode_combo.currentData()
        mode = str(data if data is not None else self.custom_room_capacity_mode_combo.currentText()).strip().lower()
        return "categorical" if mode.startswith("cat") else "numeric"

    def _on_room_capacity_mode_changed(self, _index: int) -> None:
        self._apply_room_capacity_mode()
        # Re-normalize room rows to the active authority (category or numeric).
        for row in range(self.custom_room_table.rowCount()):
            cap_item = self.custom_room_table.item(row, 3)
            if cap_item is not None:
                self._on_room_table_item_changed(cap_item)

    def _apply_room_capacity_mode(self) -> None:
        mode = self._room_capacity_mode()
        for row in range(self.custom_room_table.rowCount()):
            cap_item = self.custom_room_table.item(row, 3)
            if cap_item is not None:
                if mode == "categorical":
                    cap_item.setFlags(cap_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                else:
                    cap_item.setFlags(cap_item.flags() | Qt.ItemFlag.ItemIsEditable)
            cat_combo = self.custom_room_table.cellWidget(row, 2)
            if isinstance(cat_combo, QComboBox):
                cat_combo.setEnabled(mode == "categorical")

    def _reset_custom_staff_table(self) -> None:
        rows = int(self.custom_num_profs_spin.value()) + int(self.custom_num_tas_spin.value())
        default_days = self._parse_csv_days(
            self.custom_days_edit.text() if hasattr(self, "custom_days_edit") else ""
        ) or (self.inst.days if self.inst else ["MON", "TUE", "WED", "THU", "FRI", "SAT"])
        default_days_text = ",".join(default_days)
        was_sorting = self.custom_staff_table.isSortingEnabled()
        self.custom_staff_table.setSortingEnabled(False)
        self.custom_staff_table.blockSignals(True)
        self.custom_staff_table.setRowCount(rows)
        row = 0
        for idx in range(1, int(self.custom_num_profs_spin.value()) + 1):
            name_item = NaturalSortTableItem(f"Prof-{idx}")
            role_item = QTableWidgetItem("PROF")
            role_item.setFlags(role_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.custom_staff_table.setItem(row, 0, name_item)
            self.custom_staff_table.setItem(row, 1, role_item)
            self.custom_staff_table.setItem(row, 2, QTableWidgetItem(""))
            self.custom_staff_table.setItem(row, 3, QTableWidgetItem(default_days_text))
            self.custom_staff_table.setItem(row, 4, QTableWidgetItem("ALL"))
            row += 1
        for idx in range(1, int(self.custom_num_tas_spin.value()) + 1):
            name_item = NaturalSortTableItem(f"TA-{idx}")
            role_item = QTableWidgetItem("TA")
            role_item.setFlags(role_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.custom_staff_table.setItem(row, 0, name_item)
            self.custom_staff_table.setItem(row, 1, role_item)
            self.custom_staff_table.setItem(row, 2, QTableWidgetItem(""))
            self.custom_staff_table.setItem(row, 3, QTableWidgetItem(default_days_text))
            self.custom_staff_table.setItem(row, 4, QTableWidgetItem("ALL"))
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
            self.custom_room_table.setItem(
                row, 0, NaturalSortTableItem(f"{rtype.title()}-{row + 1}")
            )
            self._set_room_enum_cell(row, 1, options=ROOM_TYPE_CHOICES, value=rtype)
            self._set_room_enum_cell(row, 2, options=ROOM_CATEGORY_CHOICES, value=cat)
            self.custom_room_table.setItem(row, 3, self._make_numeric_item(cap))
            self.custom_room_table.setItem(row, 4, QTableWidgetItem("MAIN"))
            self.custom_room_table.setItem(row, 5, QTableWidgetItem(f"BLD-{1 + (row // 6)}"))
            self.custom_room_table.setItem(row, 6, QTableWidgetItem("1"))
            self.custom_room_table.setItem(
                row, 7, QTableWidgetItem("")
            )
            self.custom_room_table.setItem(
                row, 8, QTableWidgetItem("" if rtype != "SPECIALIZED_LAB" else "LAB1")
            )
        self.custom_room_table.blockSignals(False)
        self._apply_room_capacity_mode()
        self.custom_room_table.setSortingEnabled(was_sorting)

    def _on_custom_size_changed(self, *_args: Any) -> None:
        self._reset_custom_program_table()
        self._reset_custom_course_pattern_table()
        self._refresh_staff_course_picker()

    def _reset_custom_program_table(self) -> None:
        rows = int(self.custom_programs_spin.value())
        default_groups = int(self.custom_groups_per_program_spin.value())
        default_group_size = int(self.custom_group_size_spin.value())
        default_courses = int(self.custom_courses_per_program_spin.value())
        was_sorting = self.custom_program_table.isSortingEnabled()
        self.custom_program_table.setSortingEnabled(False)
        self.custom_program_table.blockSignals(True)
        self._custom_program_table_internal_change = True
        self.custom_program_table.setRowCount(rows)
        for row in range(rows):
            self.custom_program_table.setItem(
                row, 0, self._make_locked_item(str(row + 1), numeric=True)
            )
            self.custom_program_table.setItem(
                row, 1, NaturalSortTableItem(f"Program-{row + 1}")
            )
            self.custom_program_table.setItem(
                row, 2, self._make_numeric_item(default_groups)
            )
            self.custom_program_table.setItem(
                row, 3, self._make_numeric_item(default_group_size)
            )
            self.custom_program_table.setItem(
                row, 4, self._make_numeric_item(default_courses)
            )
            self.custom_program_table.setItem(
                row, 5, self._make_numeric_item(default_courses)
            )
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
            item = self.custom_program_table.item(row, 4)
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
            if self.custom_course_pattern_table.cellWidget(row, 5) is combo:
                return row
        return -1

    def _set_course_lab_type_cell(self, row: int, value: str) -> None:
        value_norm = str(value).strip().upper()
        if value_norm not in COURSE_LAB_TYPE_CHOICES:
            value_norm = "NONE"
        self.custom_course_pattern_table.setItem(row, 5, self._make_locked_item(value_norm))
        combo = QComboBox(self.custom_course_pattern_table)
        combo.addItems(list(COURSE_LAB_TYPE_CHOICES))
        combo.blockSignals(True)
        idx = combo.findText(value_norm)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        combo.currentTextChanged.connect(self._on_course_lab_type_changed)
        self.custom_course_pattern_table.setCellWidget(row, 5, combo)

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
            lab_type = self._course_pattern_table_text(row, 5).upper()
            lab_count_item = self.custom_course_pattern_table.item(row, 4)
            try:
                lab_count = max(0, int(str(lab_count_item.text()).strip())) if lab_count_item else 0
            except Exception:
                lab_count = 0
            tag_item = self.custom_course_pattern_table.item(row, 7)
            if tag_item is None:
                tag_item = QTableWidgetItem("")
                self.custom_course_pattern_table.setItem(row, 7, tag_item)
            if lab_count <= 0:
                if lab_type != "NONE":
                    idx = sender.findText("NONE")
                    if idx >= 0:
                        sender.setCurrentIndex(idx)
                tag_item.setText("")
            elif lab_type == "SPECIAL":
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
                "lab_count": self.custom_course_pattern_table.item(row, 4).text()
                if self.custom_course_pattern_table.item(row, 4) is not None
                else "0",
                "lab_type": self._course_pattern_table_text(row, 5).upper() or "NONE",
                "lab_duration": self.custom_course_pattern_table.item(row, 6).text()
                if self.custom_course_pattern_table.item(row, 6) is not None
                else "2",
                "lab_tag": self.custom_course_pattern_table.item(row, 7).text()
                if self.custom_course_pattern_table.item(row, 7) is not None
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
            default_lab_count = "12" if str(prev.get("lab_type", "NONE")).upper() in {"NORMAL", "SPECIAL"} else "0"
            lab_count = str(prev.get("lab_count", default_lab_count))
            lab_type = str(prev.get("lab_type", "NONE")).upper()
            lab_dur = str(prev.get("lab_duration", "2"))
            lab_tag = str(prev.get("lab_tag", ""))
            if lab_type not in COURSE_LAB_TYPE_CHOICES:
                lab_type = "NONE"
            try:
                lab_count_int = max(0, int(str(lab_count).strip()))
            except Exception:
                lab_count_int = 0
            if lab_count_int <= 0:
                lab_type = "NONE"
            self.custom_course_pattern_table.setItem(
                row, 0, self._make_locked_item(str(c_id), numeric=True)
            )
            self.custom_course_pattern_table.setItem(
                row, 1, self._make_locked_item(name, natural=True)
            )
            self.custom_course_pattern_table.setItem(
                row, 2, self._make_numeric_item(lec)
            )
            self.custom_course_pattern_table.setItem(
                row, 3, self._make_numeric_item(tut)
            )
            self.custom_course_pattern_table.setItem(
                row, 4, self._make_numeric_item(lab_count_int)
            )
            self._set_course_lab_type_cell(row, lab_type)
            self.custom_course_pattern_table.setItem(
                row, 6, self._make_numeric_item(lab_dur)
            )
            self.custom_course_pattern_table.setItem(
                row,
                7,
                QTableWidgetItem(lab_tag if lab_type == "SPECIAL" and lab_count_int > 0 else ""),
            )
        self._custom_course_pattern_table_internal_change = False
        self.custom_course_pattern_table.blockSignals(False)
        self.custom_course_pattern_table.setSortingEnabled(was_sorting)

    def _on_custom_program_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._custom_program_table_internal_change:
            return
        if item is None:
            return
        if item.column() not in (2, 3, 4, 5):
            return
        self._custom_program_table_internal_change = True
        try:
            try:
                val = max(1, int(str(item.text()).strip()))
            except Exception:
                if item.column() == 2:
                    val = int(self.custom_groups_per_program_spin.value())
                elif item.column() == 3:
                    val = int(self.custom_group_size_spin.value())
                else:
                    val = int(self.custom_courses_per_program_spin.value())
            item.setText(str(val))
            if item.column() == 4:
                cpg_item = self.custom_program_table.item(item.row(), 5)
                if cpg_item is not None:
                    try:
                        cpg = max(1, int(str(cpg_item.text()).strip()))
                    except Exception:
                        cpg = int(val)
                    cpg_item.setText(str(min(int(val), int(cpg))))
            elif item.column() == 5:
                courses_item = self.custom_program_table.item(item.row(), 4)
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
            mode = self._room_capacity_mode()
            if col == 1:
                room_type = self._room_table_text(row, 1).upper()
                tags_item = self.custom_room_table.item(row, 8)
                if tags_item is not None:
                    if room_type != "SPECIALIZED_LAB":
                        tags_item.setText("")
                    elif not str(tags_item.text()).strip():
                        tags_item.setText("LAB1")
            if mode == "categorical":
                cat = self._room_table_text(row, 2).upper()
                if cat not in ROOM_CATEGORY_CAPACITY:
                    cat = "MEDIUM"
                    cat_item.setText(cat)
                cap_item.setText(str(ROOM_CATEGORY_CAPACITY[cat]))
            else:
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
    def _parse_csv_weeks(raw: str) -> List[int]:
        text = str(raw).strip()
        if not text or text.upper() == "ALL":
            return []
        out: List[int] = []
        for token in text.split(","):
            token = token.strip()
            if not token:
                continue
            if "-" in token:
                parts = token.split("-", 1)
                try:
                    start = int(parts[0].strip())
                    end = int(parts[1].strip())
                except Exception:
                    continue
                lo = min(start, end)
                hi = max(start, end)
                out.extend(range(int(lo), int(hi) + 1))
                continue
            try:
                out.append(int(token))
            except Exception:
                continue
        return sorted(set(out))

    @staticmethod
    def _parse_csv_names(raw: str) -> List[str]:
        out: List[str] = []
        for token in str(raw).split(","):
            name = token.strip()
            if name:
                out.append(name)
        return out

    @staticmethod
    def _parse_term_blocks(raw: str) -> List[Dict[str, Any]]:
        blocks: List[Dict[str, Any]] = []
        for idx, token in enumerate(str(raw).split(","), start=1):
            part = token.strip()
            if not part:
                continue
            if ":" in part:
                label, length_text = part.split(":", 1)
            else:
                label, length_text = f"Term {idx}", part
            label = str(label).strip() or f"Term {idx}"
            teaching = True
            if label.startswith("!"):
                label = label[1:].strip() or f"Term {idx}"
                teaching = False
            try:
                length = max(1, int(str(length_text).strip()))
            except Exception:
                continue
            blocks.append(
                {
                    "label": str(label),
                    "length_weeks": int(length),
                    "teaching": bool(teaching),
                }
            )
        return blocks

    @staticmethod
    def _format_term_blocks(blocks: List[Dict[str, Any]] | None) -> str:
        parts: List[str] = []
        for idx, block in enumerate(blocks or [], start=1):
            if not isinstance(block, dict):
                continue
            try:
                length = max(1, int(block.get("length_weeks", 0)))
            except Exception:
                continue
            label = str(block.get("label", f"Term {idx}") or f"Term {idx}").strip()
            teaching = bool(block.get("teaching", True))
            if not teaching:
                label = "!" + label
            parts.append(f"{label}:{length}")
        return ", ".join(parts)

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
        prof_weeks: Dict[int, List[int]] = {}
        ta_weeks: Dict[int, List[int]] = {}
        program_overrides: List[Dict[str, Any]] = []
        course_patterns: List[Dict[str, Any]] = []
        prof_idx = 0
        ta_idx = 0
        for row in range(self.custom_staff_table.rowCount()):
            role_item = self.custom_staff_table.item(row, 1)
            courses_item = self.custom_staff_table.item(row, 2)
            days_item = self.custom_staff_table.item(row, 3)
            weeks_item = self.custom_staff_table.item(row, 4)
            role = str(role_item.text()).strip().upper() if role_item else ""
            courses = self._parse_csv_ints(courses_item.text() if courses_item else "")
            days = self._parse_csv_days(days_item.text() if days_item else "")
            weeks = self._parse_csv_weeks(weeks_item.text() if weeks_item else "")
            if role == "PROF":
                prof_idx += 1
                if courses:
                    prof_course_map[prof_idx] = courses
                prof_days[prof_idx] = days
                prof_weeks[prof_idx] = weeks
            elif role == "TA":
                ta_idx += 1
                if courses:
                    ta_course_map[ta_idx] = courses
                ta_days[ta_idx] = days
                ta_weeks[ta_idx] = weeks

        room_specs: List[Dict[str, Any]] = []
        room_capacity_mode = self._room_capacity_mode()
        for row in range(self.custom_room_table.rowCount()):
            name_item = self.custom_room_table.item(row, 0)
            cap_item = self.custom_room_table.item(row, 3)
            campus_item = self.custom_room_table.item(row, 4)
            building_item = self.custom_room_table.item(row, 5)
            floor_item = self.custom_room_table.item(row, 6)
            features_item = self.custom_room_table.item(row, 7)
            tags_item = self.custom_room_table.item(row, 8)
            name = str(name_item.text()).strip() if name_item else f"Room-{row + 1}"
            room_type = self._room_table_text(row, 1).upper() or "LECTURE"
            category = self._room_table_text(row, 2).upper() or "MEDIUM"
            try:
                capacity = max(1, int(str(cap_item.text()).strip())) if cap_item else ROOM_CATEGORY_CAPACITY.get(category, 150)
            except Exception:
                capacity = ROOM_CATEGORY_CAPACITY.get(category, 150)
            campus = str(campus_item.text()).strip().upper() if campus_item else "MAIN"
            building = str(building_item.text()).strip() if building_item else ""
            floor = str(floor_item.text()).strip() if floor_item else ""
            features = [t.strip().upper() for t in str(features_item.text()).split(",") if t.strip()] if features_item else []
            tags = [t.strip().upper() for t in str(tags_item.text()).split(",") if t.strip()] if tags_item else []
            cap_field: int | None = int(capacity)
            if room_capacity_mode == "categorical":
                cap_field = None
            room_specs.append(
                {
                    "name": name,
                    "room_type": room_type,
                    "category": category,
                    "capacity": cap_field,
                    "capacity_mode": room_capacity_mode,
                    "campus": campus or "MAIN",
                    "building": building,
                    "floor": floor,
                    "features": features,
                    "tags": tags,
                }
            )

        for row in range(self.custom_program_table.rowCount()):
            pid_item = self.custom_program_table.item(row, 0)
            name_item = self.custom_program_table.item(row, 1)
            groups_item = self.custom_program_table.item(row, 2)
            group_size_item = self.custom_program_table.item(row, 3)
            courses_item = self.custom_program_table.item(row, 4)
            cpg_item = self.custom_program_table.item(row, 5)
            try:
                pid = int(str(pid_item.text()).strip()) if pid_item is not None else row + 1
                pname = (
                    str(name_item.text()).strip()
                    if name_item is not None and str(name_item.text()).strip()
                    else f"Program-{int(pid)}"
                )
                groups = max(1, int(str(groups_item.text()).strip())) if groups_item is not None else int(self.custom_groups_per_program_spin.value())
                group_size = max(1, int(str(group_size_item.text()).strip())) if group_size_item is not None else int(self.custom_group_size_spin.value())
                courses = max(1, int(str(courses_item.text()).strip())) if courses_item is not None else int(self.custom_courses_per_program_spin.value())
                courses_per_group = max(1, int(str(cpg_item.text()).strip())) if cpg_item is not None else courses
            except Exception:
                continue
            program_overrides.append(
                {
                    "program_id": int(pid),
                    "program_name": str(pname),
                    "groups": int(groups),
                    "group_size": int(group_size),
                    "courses": int(courses),
                    "courses_per_group": min(int(courses), int(courses_per_group)),
                }
            )

        for row in range(self.custom_course_pattern_table.rowCount()):
            cid_item = self.custom_course_pattern_table.item(row, 0)
            lec_item = self.custom_course_pattern_table.item(row, 2)
            tut_item = self.custom_course_pattern_table.item(row, 3)
            lab_count_item = self.custom_course_pattern_table.item(row, 4)
            dur_item = self.custom_course_pattern_table.item(row, 6)
            tag_item = self.custom_course_pattern_table.item(row, 7)
            try:
                c_id = int(str(cid_item.text()).strip()) if cid_item is not None else row + 1
                lecture_count = int(str(lec_item.text()).strip()) if lec_item is not None else 12
                tutorial_count = int(str(tut_item.text()).strip()) if tut_item is not None else 12
                lab_count = int(str(lab_count_item.text()).strip()) if lab_count_item is not None else 0
                lab_duration = int(str(dur_item.text()).strip()) if dur_item is not None else 2
            except Exception:
                continue
            lab_type = self._course_pattern_table_text(row, 5).upper() or "NONE"
            lab_tag = str(tag_item.text()).strip().upper() if tag_item is not None else ""
            if int(lab_count) <= 0:
                lab_type = "NONE"
                lab_tag = ""
            course_patterns.append(
                {
                    "course_id": int(c_id),
                    "lecture_count": int(lecture_count),
                    "tutorial_count": int(tutorial_count),
                    "lab_count": int(max(0, lab_count)),
                    "lab_type": str(lab_type),
                    "lab_duration": int(lab_duration),
                    "lab_tag": str(lab_tag),
                }
            )

        term_blocks = self._parse_term_blocks(self.custom_term_blocks_edit.text())
        calendar_weeks = self._parse_csv_weeks(self.custom_weeks_edit.text())
        if term_blocks:
            calendar_weeks = []
        return {
            "num_programs": int(self.custom_programs_spin.value()),
            "groups_per_program": int(self.custom_groups_per_program_spin.value()),
            "group_size": int(self.custom_group_size_spin.value()),
            "courses_per_program": int(self.custom_courses_per_program_spin.value()),
            "program_overrides": program_overrides,
            "course_patterns": course_patterns,
            "course_names": self._parse_csv_names(self.custom_course_names_edit.text()),
            "num_professors": int(self.custom_num_profs_spin.value()),
            "num_tas": int(self.custom_num_tas_spin.value()),
            "calendar_days": self._parse_csv_days(self.custom_days_edit.text()),
            "calendar_weeks": calendar_weeks,
            "term_blocks": term_blocks,
            "slots_per_day": int(self.custom_slots_per_day_spin.value()),
            "professor_course_map": prof_course_map,
            "ta_course_map": ta_course_map,
            "professor_days": prof_days,
            "ta_days": ta_days,
            "professor_weeks": prof_weeks,
            "ta_weeks": ta_weeks,
            "room_specs": room_specs,
            "room_capacity_mode": room_capacity_mode,
            "seed": 42,
        }

    @staticmethod
    def _local_custom_config_path() -> str:
        return os.path.join(os.path.expanduser("~"), ".planora_custom_config.json")

    @staticmethod
    def _write_custom_config(path: str, config: Dict[str, Any]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, sort_keys=True)

    @staticmethod
    def _read_custom_config(path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Custom config must be a JSON object.")
        return data

    def _apply_custom_generation_config(self, config: Dict[str, Any]) -> None:
        if not isinstance(config, dict):
            raise ValueError("Invalid custom configuration payload.")

        def _ival(key: str, default: int) -> int:
            try:
                return int(config.get(key, default))
            except Exception:
                return int(default)

        num_programs = max(1, _ival("num_programs", int(self.custom_programs_spin.value())))
        groups_per_program = max(
            1, _ival("groups_per_program", int(self.custom_groups_per_program_spin.value()))
        )
        group_size = max(1, _ival("group_size", int(self.custom_group_size_spin.value())))
        courses_per_program = max(
            1, _ival("courses_per_program", int(self.custom_courses_per_program_spin.value()))
        )
        slots_per_day = max(3, _ival("slots_per_day", int(self.custom_slots_per_day_spin.value())))
        num_professors = max(1, _ival("num_professors", int(self.custom_num_profs_spin.value())))
        num_tas = max(1, _ival("num_tas", int(self.custom_num_tas_spin.value())))
        course_names = config.get("course_names", [])
        if not isinstance(course_names, list):
            course_names = []
        course_names_text = ",".join(str(v).strip() for v in course_names if str(v).strip())
        calendar_days = config.get("calendar_days", [])
        if not isinstance(calendar_days, list):
            calendar_days = []
        calendar_days_text = ",".join(
            str(v).strip().upper() for v in calendar_days if str(v).strip()
        )
        calendar_weeks = config.get("calendar_weeks", [])
        if not isinstance(calendar_weeks, list):
            calendar_weeks = []
        term_blocks = config.get("term_blocks", [])
        if not isinstance(term_blocks, list):
            term_blocks = []
        calendar_weeks_text = (
            ",".join(str(int(v)) for v in calendar_weeks) if calendar_weeks else "1-12"
        )
        term_blocks_text = self._format_term_blocks(term_blocks)

        for spin, value in (
            (self.custom_programs_spin, num_programs),
            (self.custom_groups_per_program_spin, groups_per_program),
            (self.custom_group_size_spin, group_size),
            (self.custom_courses_per_program_spin, courses_per_program),
            (self.custom_slots_per_day_spin, slots_per_day),
            (self.custom_num_profs_spin, num_professors),
            (self.custom_num_tas_spin, num_tas),
        ):
            spin.blockSignals(True)
            spin.setValue(int(value))
            spin.blockSignals(False)
        self.custom_days_edit.blockSignals(True)
        self.custom_days_edit.setText(calendar_days_text or "MON,TUE,WED,THU,FRI,SAT")
        self.custom_days_edit.blockSignals(False)
        self.custom_weeks_edit.blockSignals(True)
        self.custom_weeks_edit.setText(calendar_weeks_text)
        self.custom_weeks_edit.blockSignals(False)
        self.custom_term_blocks_edit.blockSignals(True)
        self.custom_term_blocks_edit.setText(term_blocks_text)
        self.custom_term_blocks_edit.blockSignals(False)
        self.custom_course_names_edit.blockSignals(True)
        self.custom_course_names_edit.setText(course_names_text)
        self.custom_course_names_edit.blockSignals(False)

        self._reset_custom_program_table()
        self._reset_custom_course_pattern_table()
        self._reset_custom_staff_table()

        program_overrides = config.get("program_overrides", [])
        if isinstance(program_overrides, list):
            for row_cfg in program_overrides:
                if not isinstance(row_cfg, dict):
                    continue
                try:
                    pid = int(row_cfg.get("program_id"))
                    pname = str(row_cfg.get("program_name", "")).strip() or f"Program-{pid}"
                    groups = max(1, int(row_cfg.get("groups", groups_per_program)))
                    row_group_size = max(1, int(row_cfg.get("group_size", group_size)))
                    courses = max(1, int(row_cfg.get("courses", courses_per_program)))
                    cpg = max(1, int(row_cfg.get("courses_per_group", courses)))
                except Exception:
                    continue
                row = int(pid) - 1
                if not (0 <= row < self.custom_program_table.rowCount()):
                    continue
                self.custom_program_table.setItem(row, 1, NaturalSortTableItem(pname))
                self.custom_program_table.setItem(row, 2, self._make_numeric_item(groups))
                self.custom_program_table.setItem(row, 3, self._make_numeric_item(row_group_size))
                self.custom_program_table.setItem(row, 4, self._make_numeric_item(courses))
                self.custom_program_table.setItem(
                    row, 5, self._make_numeric_item(min(courses, cpg))
                )

        self._reset_custom_course_pattern_table()
        course_patterns = config.get("course_patterns", [])
        if isinstance(course_patterns, list):
            by_course: Dict[int, Dict[str, Any]] = {}
            for row_cfg in course_patterns:
                if not isinstance(row_cfg, dict):
                    continue
                try:
                    c_id = int(row_cfg.get("course_id"))
                except Exception:
                    continue
                by_course[int(c_id)] = row_cfg
            for row in range(self.custom_course_pattern_table.rowCount()):
                cid_item = self.custom_course_pattern_table.item(row, 0)
                if cid_item is None:
                    continue
                try:
                    c_id = int(str(cid_item.text()).strip())
                except Exception:
                    continue
                row_cfg = by_course.get(int(c_id))
                if not row_cfg:
                    continue
                try:
                    lec = max(0, int(row_cfg.get("lecture_count", 12)))
                    tut = max(0, int(row_cfg.get("tutorial_count", 12)))
                    lab_count = max(
                        0,
                        int(
                            row_cfg.get(
                                "lab_count",
                                12 if str(row_cfg.get("lab_type", "NONE")).strip().upper() in {"NORMAL", "SPECIAL"} else 0,
                            )
                        ),
                    )
                    lab_type = str(row_cfg.get("lab_type", "NONE")).strip().upper()
                    lab_dur = max(1, int(row_cfg.get("lab_duration", 2)))
                    lab_tag = str(row_cfg.get("lab_tag", "")).strip().upper()
                except Exception:
                    continue
                self.custom_course_pattern_table.setItem(row, 2, self._make_numeric_item(lec))
                self.custom_course_pattern_table.setItem(row, 3, self._make_numeric_item(tut))
                self.custom_course_pattern_table.setItem(
                    row, 4, self._make_numeric_item(lab_count)
                )
                if lab_count <= 0:
                    lab_type = "NONE"
                lab_combo = self.custom_course_pattern_table.cellWidget(row, 5)
                if isinstance(lab_combo, QComboBox):
                    idx = lab_combo.findText(lab_type)
                    if idx >= 0:
                        lab_combo.setCurrentIndex(idx)
                self.custom_course_pattern_table.setItem(
                    row, 6, self._make_numeric_item(lab_dur)
                )
                self.custom_course_pattern_table.setItem(
                    row, 7, QTableWidgetItem(lab_tag if lab_type == "SPECIAL" and lab_count > 0 else "")
                )

        professor_course_map = config.get("professor_course_map", {}) or {}
        ta_course_map = config.get("ta_course_map", {}) or {}
        professor_days = config.get("professor_days", {}) or {}
        ta_days = config.get("ta_days", {}) or {}
        professor_weeks = config.get("professor_weeks", {}) or {}
        ta_weeks = config.get("ta_weeks", {}) or {}
        for idx in range(1, int(num_professors) + 1):
            row = idx - 1
            if row >= self.custom_staff_table.rowCount():
                break
            courses = professor_course_map.get(idx, professor_course_map.get(str(idx), [])) or []
            days = professor_days.get(idx, professor_days.get(str(idx), [])) or []
            weeks = professor_weeks.get(idx, professor_weeks.get(str(idx), [])) or []
            self.custom_staff_table.setItem(
                row, 2, QTableWidgetItem(",".join(str(int(c)) for c in courses if str(c).strip()))
            )
            day_text = ",".join(str(d).strip().upper() for d in days if str(d).strip())
            self.custom_staff_table.setItem(row, 3, QTableWidgetItem(day_text))
            if weeks:
                week_text = ",".join(str(int(w)) for w in weeks if str(w).strip())
            else:
                week_text = "ALL"
            self.custom_staff_table.setItem(row, 4, QTableWidgetItem(week_text))
        for idx in range(1, int(num_tas) + 1):
            row = int(num_professors) + idx - 1
            if row >= self.custom_staff_table.rowCount():
                break
            courses = ta_course_map.get(idx, ta_course_map.get(str(idx), [])) or []
            days = ta_days.get(idx, ta_days.get(str(idx), [])) or []
            weeks = ta_weeks.get(idx, ta_weeks.get(str(idx), [])) or []
            self.custom_staff_table.setItem(
                row, 2, QTableWidgetItem(",".join(str(int(c)) for c in courses if str(c).strip()))
            )
            day_text = ",".join(str(d).strip().upper() for d in days if str(d).strip())
            self.custom_staff_table.setItem(row, 3, QTableWidgetItem(day_text))
            if weeks:
                week_text = ",".join(str(int(w)) for w in weeks if str(w).strip())
            else:
                week_text = "ALL"
            self.custom_staff_table.setItem(row, 4, QTableWidgetItem(week_text))

        room_specs = config.get("room_specs", [])
        if isinstance(room_specs, list) and room_specs:
            self.custom_room_count_spin.blockSignals(True)
            self.custom_room_count_spin.setValue(max(1, len(room_specs)))
            self.custom_room_count_spin.blockSignals(False)
            mode_raw = config.get("room_capacity_mode")
            if mode_raw is None and room_specs:
                mode_raw = room_specs[0].get("capacity_mode")
            mode = str(mode_raw or "numeric").strip().lower()
            mode = "categorical" if mode.startswith("cat") else "numeric"
            mode_idx = self.custom_room_capacity_mode_combo.findData(mode)
            if mode_idx >= 0:
                self.custom_room_capacity_mode_combo.setCurrentIndex(mode_idx)
            self._reset_custom_room_table()
            for row, room_cfg in enumerate(room_specs):
                if row >= self.custom_room_table.rowCount() or not isinstance(room_cfg, dict):
                    break
                name = str(room_cfg.get("name", "")).strip() or f"Room-{row + 1}"
                rtype = str(room_cfg.get("room_type", "LECTURE")).strip().upper()
                cat = str(room_cfg.get("category", "MEDIUM")).strip().upper()
                cap = room_cfg.get("capacity", ROOM_CATEGORY_CAPACITY.get(cat, 150))
                try:
                    cap_int = max(1, int(cap))
                except Exception:
                    cap_int = int(ROOM_CATEGORY_CAPACITY.get(cat, 150))
                campus = str(room_cfg.get("campus", "MAIN")).strip().upper() or "MAIN"
                building = str(room_cfg.get("building", "")).strip()
                floor = str(room_cfg.get("floor", "")).strip()
                features_raw = room_cfg.get("features", []) or []
                features = ",".join(
                    str(t).strip().upper() for t in features_raw if str(t).strip()
                )
                tags_raw = room_cfg.get("tags", []) or []
                tags = ",".join(str(t).strip().upper() for t in tags_raw if str(t).strip())

                self.custom_room_table.setItem(row, 0, NaturalSortTableItem(name))
                type_combo = self.custom_room_table.cellWidget(row, 1)
                if isinstance(type_combo, QComboBox):
                    idx = type_combo.findText(rtype)
                    if idx >= 0:
                        type_combo.setCurrentIndex(idx)
                cat_combo = self.custom_room_table.cellWidget(row, 2)
                if isinstance(cat_combo, QComboBox):
                    idx = cat_combo.findText(cat)
                    if idx >= 0:
                        cat_combo.setCurrentIndex(idx)
                self.custom_room_table.setItem(row, 3, self._make_numeric_item(cap_int))
                self.custom_room_table.setItem(row, 4, QTableWidgetItem(campus))
                self.custom_room_table.setItem(row, 5, QTableWidgetItem(building))
                self.custom_room_table.setItem(row, 6, QTableWidgetItem(floor))
                self.custom_room_table.setItem(row, 7, QTableWidgetItem(features))
                self.custom_room_table.setItem(row, 8, QTableWidgetItem(tags))

        self._apply_room_capacity_mode()
        self._refresh_staff_course_picker()
        self._normalize_custom_table_item_types()

    def on_save_custom_config_local(self) -> None:
        try:
            config = self._collect_custom_generation_config()
            path = self._local_custom_config_path()
            self._write_custom_config(path, config)
            self.set_status(f"Saved local custom config to {path}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Custom config error", str(exc))

    def on_save_custom_config_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save custom generation config",
            "custom_generator_config.json",
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            config = self._collect_custom_generation_config()
            self._write_custom_config(path, config)
            self.set_status(f"Saved custom config to {path}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Custom config error", str(exc))

    def on_load_custom_config_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load custom generation config",
            "",
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            config = self._read_custom_config(path)
            self._apply_custom_generation_config(config)
            self.set_status(f"Loaded custom config from {path}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Custom config error", str(exc))

    def _load_custom_config_local(self, *, silent: bool = False) -> None:
        path = self._local_custom_config_path()
        if not os.path.exists(path):
            return
        try:
            config = self._read_custom_config(path)
            self._apply_custom_generation_config(config)
            if not silent:
                self.set_status(f"Loaded local custom config from {path}")
        except Exception:
            if not silent:
                traceback.print_exc()
            if not silent:
                QMessageBox.warning(
                    self,
                    "Custom config warning",
                    f"Failed to load local custom configuration from {path}.",
                )

    def _append_audit_log(self, event: str, details: Dict[str, Any] | None = None) -> None:
        row = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "user": str(self._operator_name or "unknown"),
            "event": str(event),
            "details": details or {},
        }
        details_summary_parts: List[str] = []
        for key, value in sorted((details or {}).items()):
            if isinstance(value, (dict, list, tuple)):
                details_summary_parts.append(f"{key}=...")
            else:
                details_summary_parts.append(f"{key}={value}")
        row["details_summary"] = ", ".join(details_summary_parts[:4])
        self._workspace_change_log.append(dict(row))
        if len(self._workspace_change_log) > 200:
            self._workspace_change_log = self._workspace_change_log[-200:]
        try:
            append_runtime_log(
                self._runtime_paths["runtime_log"],
                event=str(event),
                level="info",
                details=dict(details or {}),
            )
            record_telemetry_event(
                self._runtime_paths["telemetry_log"],
                event=str(event),
                details=dict(details or {}),
                opt_in=bool(self._runtime_settings.get("telemetry_opt_in", False)),
            )
        except Exception:
            pass
        if os.getenv("PYTEST_CURRENT_TEST"):
            return
        try:
            with open(self._audit_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, sort_keys=True) + "\n")
        except Exception:
            pass

    def _state_to_json_ready(self, state: Dict[str, Any]) -> Dict[str, Any]:
        out = {
            "current_schedule": {},
            "locked_activities": {},
            "held_activity_id": state.get("held_activity_id"),
        }
        cur = state.get("current_schedule") or {}
        if isinstance(cur, dict):
            out["current_schedule"] = {
                str(int(a_id)): dict(info)
                for a_id, info in cur.items()
                if isinstance(info, dict)
            }
        locks = state.get("locked_activities") or {}
        if isinstance(locks, dict):
            out["locked_activities"] = {
                str(int(a_id)): dict(lock)
                for a_id, lock in locks.items()
                if isinstance(lock, dict)
        }
        return out

    def _workspace_meta(self) -> Dict[str, Any]:
        return {
            "operator_name": str(self._operator_name or "unknown"),
            "branches": {
                str(name): dict(branch)
                for name, branch in self._branches.items()
                if isinstance(branch, dict)
            },
            "active_branch_name": self._active_branch_name,
            "release_candidates": {
                str(name): dict(candidate)
                for name, candidate in self._release_candidates.items()
                if isinstance(candidate, dict)
            },
            "published_release_id": self._published_release_id,
            "protected_baseline": dict(self._protected_baseline or {}),
            "change_history": [dict(row) for row in self._workspace_change_log[-200:]],
            "import_export_template_store_path": str(self._import_export_template_path),
            "branding_profile": dict(self._branding_profile or {}),
            "runtime_settings": dict(self._runtime_settings or {}),
            "last_import_mapping": dict(self._last_import_mapping or {}),
            "last_group_separator": str(self._last_group_separator or ";"),
        }

    def _effective_branding(self) -> Dict[str, Any]:
        return ensure_branding_profile(self._branding_profile)

    def _apply_branding_profile(self) -> None:
        branding = self._effective_branding()
        self.setWindowTitle(str(branding.get("display_name", APP_DISPLAY_NAME)))
        if hasattr(self, "status_label"):
            self._refresh_status_label()
        if hasattr(self, "quality_label") and not self.quality_label.text().strip():
            self.quality_label.setText(
                f"{branding.get('display_name', APP_DISPLAY_NAME)} ready."
            )

    @staticmethod
    def _state_from_json_ready(state: Dict[str, Any]) -> Dict[str, Any]:
        cur = state.get("current_schedule") or {}
        locks = state.get("locked_activities") or {}
        return {
            "current_schedule": {
                int(a_id): dict(info)
                for a_id, info in cur.items()
                if isinstance(info, dict)
            },
            "locked_activities": {
                int(a_id): dict(lock)
                for a_id, lock in locks.items()
                if isinstance(lock, dict)
            },
            "held_activity_id": state.get("held_activity_id"),
        }

    def _save_persistent_history(self) -> None:
        if os.getenv("PYTEST_CURRENT_TEST"):
            return
        if self.inst is None:
            return
        try:
            payload = {
                "saved_at_utc": datetime.now(timezone.utc).isoformat(),
                "instance": instance_to_json(self.inst),
                "base_schedule": {
                    str(int(a_id)): dict(info)
                    for a_id, info in self.base_schedule.items()
                    if isinstance(info, dict)
                },
                "state": self._state_to_json_ready(self._snapshot_state()),
                "undo": [
                    self._state_to_json_ready(s)
                    for s in self._undo_stack[-60:]
                    if isinstance(s, dict)
                ],
                "redo": [
                    self._state_to_json_ready(s)
                    for s in self._redo_stack[-60:]
                    if isinstance(s, dict)
                ],
                "workspace_meta": self._workspace_meta(),
            }
            with open(self._history_store_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
        except Exception:
            pass

    def _load_persistent_history(self) -> None:
        if os.getenv("PYTEST_CURRENT_TEST"):
            return
        if not os.path.exists(self._history_store_path):
            return
        try:
            with open(self._history_store_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                return
            inst_raw = payload.get("instance")
            if not isinstance(inst_raw, dict):
                return
            inst = instance_from_json(inst_raw)
            self.inst = inst
            base_raw = payload.get("base_schedule", {})
            if isinstance(base_raw, dict):
                self.base_schedule = {
                    int(a_id): dict(info)
                    for a_id, info in base_raw.items()
                    if isinstance(info, dict)
                }
            state_raw = payload.get("state", {})
            state = self._state_from_json_ready(state_raw if isinstance(state_raw, dict) else {})
            self.current_schedule = {
                int(a_id): dict(info)
                for a_id, info in (state.get("current_schedule") or {}).items()
            }
            self.locked_activities = {
                int(a_id): dict(lock)
                for a_id, lock in (state.get("locked_activities") or {}).items()
            }
            held = state.get("held_activity_id")
            self.held_activity_id = int(held) if held is not None else None
            self._bump_schedule_revision()
            self._undo_stack = [
                self._state_from_json_ready(s)
                for s in (payload.get("undo") or [])
                if isinstance(s, dict)
            ]
            self._redo_stack = [
                self._state_from_json_ready(s)
                for s in (payload.get("redo") or [])
                if isinstance(s, dict)
            ]
            workspace_meta = payload.get("workspace_meta", {})
            if isinstance(workspace_meta, dict):
                self._operator_name = str(
                    workspace_meta.get("operator_name", self._operator_name) or self._operator_name
                )
                self._branches = {
                    str(name): dict(branch)
                    for name, branch in dict(workspace_meta.get("branches", {}) or {}).items()
                    if isinstance(branch, dict)
                }
                active_branch = workspace_meta.get("active_branch_name")
                self._active_branch_name = str(active_branch) if active_branch else None
                self._release_candidates = {
                    str(name): dict(candidate)
                    for name, candidate in dict(workspace_meta.get("release_candidates", {}) or {}).items()
                    if isinstance(candidate, dict)
                }
                published = workspace_meta.get("published_release_id")
                self._published_release_id = str(published) if published else None
                self._protected_baseline = dict(
                    workspace_meta.get("protected_baseline", self._protected_baseline) or {}
                )
                self._workspace_change_log = [
                    dict(row)
                    for row in list(workspace_meta.get("change_history", []) or [])
                    if isinstance(row, dict)
                ][-200:]
                self._import_export_template_path = str(
                    workspace_meta.get(
                        "import_export_template_store_path",
                        self._import_export_template_path,
                    )
                    or self._import_export_template_path
                )
                self._branding_profile = ensure_branding_profile(
                    dict(workspace_meta.get("branding_profile", self._branding_profile) or {})
                )
                self._runtime_settings = save_runtime_settings(
                    self._runtime_paths["settings"],
                    dict(workspace_meta.get("runtime_settings", self._runtime_settings) or {}),
                )
                self._last_import_mapping = {
                    str(k): str(v)
                    for k, v in dict(workspace_meta.get("last_import_mapping", {}) or {}).items()
                }
                self._last_group_separator = str(
                    workspace_meta.get("last_group_separator", self._last_group_separator) or self._last_group_separator
                )
            self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
            self._sync_instance_staff_from_schedule(self.current_schedule)
            self._sync_locks_to_instance()
            self._load_constraint_controls_from_instance(self.inst)
            self.populate_weeks()
            self.update_entities()
            self.update_table()
            self.update_quality_summary()
            self._refresh_history_buttons()
            self._apply_branding_profile()
            self.set_status("Restored previous workspace history.")
        except Exception:
            # Corrupted history should never break app startup.
            pass

    def _history_state_brief(self, state: Dict[str, Any]) -> str:
        cur = state.get("current_schedule") or {}
        locks = state.get("locked_activities") or {}
        held = state.get("held_activity_id")
        held_txt = f"A{int(held)}" if held is not None else "none"
        return (
            f"activities={len(cur) if isinstance(cur, dict) else 0}, "
            f"locks={len(locks) if isinstance(locks, dict) else 0}, held={held_txt}"
        )

    def _ensure_snapshot_store_dir(self) -> str:
        path = str(self._snapshot_store_dir)
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except Exception:
            fallback = os.path.join(
                tempfile.gettempdir(), "scheduler_history_snapshots"
            )
            os.makedirs(fallback, exist_ok=True)
            self._snapshot_store_dir = str(fallback)
            return str(fallback)

    def _refresh_history_view(self) -> None:
        if not hasattr(self, "history_list"):
            return
        self.history_list.clear()
        if self.inst is None:
            self.history_list.addItem("No active instance.")
            return

        undo_count = len(self._undo_stack)
        for idx, state in enumerate(self._undo_stack):
            steps = max(1, int(undo_count - idx))
            line = f"o  undo {steps:02d}  {self._history_state_brief(state)}"
            item = QListWidgetItem(line)
            item.setData(Qt.ItemDataRole.UserRole, ("undo", int(steps)))
            self.history_list.addItem(item)

        head_item = QListWidgetItem(f"*  HEAD      {self._history_state_brief(self._snapshot_state())}")
        head_item.setData(Qt.ItemDataRole.UserRole, ("head", 0))
        self.history_list.addItem(head_item)

        for idx, state in enumerate(reversed(self._redo_stack), start=1):
            line = f"o  redo {idx:02d}  {self._history_state_brief(state)}"
            item = QListWidgetItem(line)
            item.setData(Qt.ItemDataRole.UserRole, ("redo", int(idx)))
            self.history_list.addItem(item)

        branch_rows = list_branch_rows(self._branches)
        if branch_rows:
            self.history_list.addItem(QListWidgetItem("---- named branches ----"))
            for row in branch_rows:
                item = QListWidgetItem(
                    f"  {row['name']} | {row['author']} | {row['description']}"
                )
                item.setData(Qt.ItemDataRole.UserRole, ("branch", str(row["name"])))
                self.history_list.addItem(item)

        if self._release_candidates:
            self.history_list.addItem(QListWidgetItem("---- release candidates ----"))
            for name, candidate in sorted(self._release_candidates.items()):
                status = str(candidate.get("status", "candidate"))
                author = str(candidate.get("author", ""))
                item = QListWidgetItem(f"  {name} | {status} | {author}")
                item.setData(Qt.ItemDataRole.UserRole, ("release", str(name)))
                self.history_list.addItem(item)

        if self._workspace_change_log:
            self.history_list.addItem(QListWidgetItem("---- recent changes ----"))
            for idx, row in enumerate(reversed(self._workspace_change_log[-12:]), start=1):
                actor = str(row.get("user", "unknown"))
                event = str(row.get("event", "event"))
                summary = str(row.get("details_summary", ""))
                item = QListWidgetItem(f"  {actor} | {event} | {summary}")
                item.setData(
                    Qt.ItemDataRole.UserRole,
                    ("change_event", int(len(self._workspace_change_log) - idx)),
                )
                self.history_list.addItem(item)

        if os.path.isdir(self._snapshot_store_dir):
            try:
                files = [
                    os.path.join(self._snapshot_store_dir, f)
                    for f in os.listdir(self._snapshot_store_dir)
                    if str(f).lower().endswith(".json")
                ]
                files.sort(key=lambda p: os.path.getmtime(p))
            except Exception:
                files = []
            if files:
                self.history_list.addItem(QListWidgetItem("---- saved snapshot paths ----"))
                for snap_path in reversed(files[-8:]):
                    item = QListWidgetItem(f"  {snap_path}")
                    item.setData(Qt.ItemDataRole.UserRole, ("snapshot_path", str(snap_path)))
                    self.history_list.addItem(item)

        self.history_undo5_btn.setEnabled(bool(self._undo_stack))
        self.history_redo5_btn.setEnabled(bool(self._redo_stack))
        self.history_save_snapshot_btn.setEnabled(bool(self.current_schedule))
        self.history_load_snapshot_btn.setEnabled(self.inst is not None)

    def _undo_many(self, steps: int) -> None:
        count = max(0, min(int(steps), len(self._undo_stack)))
        for _ in range(count):
            self.on_undo()
        if count > 1:
            self.set_status(f"Undo applied x{count}")

    def _redo_many(self, steps: int) -> None:
        count = max(0, min(int(steps), len(self._redo_stack)))
        for _ in range(count):
            self.on_redo()
        if count > 1:
            self.set_status(f"Redo applied x{count}")

    def on_history_item_activated(self, item: QListWidgetItem) -> None:
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        kind, steps = payload
        if str(kind) == "snapshot_path":
            self._load_history_snapshot_path(str(steps))
            return
        if str(kind) == "branch":
            branch = self._branches.get(str(steps))
            if not isinstance(branch, dict):
                return
            self._push_undo_state()
            schedule = {
                int(a_id): dict(info)
                for a_id, info in dict(branch.get("current_schedule", {}) or {}).items()
                if isinstance(info, dict)
            }
            self.current_schedule = schedule
            self._active_branch_name = str(steps)
            self._bump_schedule_revision()
            self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
            self._sync_instance_staff_from_schedule(self.current_schedule)
            self._sync_locks_to_instance()
            self.update_table()
            self.update_quality_summary()
            self._refresh_history_buttons()
            self._append_audit_log("named_branch_loaded", {"name": str(steps), "source": "history"})
            self.set_status(f"Loaded branch {steps} from history.")
            return
        if str(kind) == "release":
            candidate = self._release_candidates.get(str(steps))
            if not isinstance(candidate, dict):
                return
            self._push_undo_state()
            schedule = {
                int(a_id): dict(info)
                for a_id, info in dict(candidate.get("schedule", {}) or {}).items()
                if isinstance(info, dict)
            }
            self.current_schedule = schedule
            self._bump_schedule_revision()
            self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
            self._sync_instance_staff_from_schedule(self.current_schedule)
            self._sync_locks_to_instance()
            self.update_table()
            self.update_quality_summary()
            self._refresh_history_buttons()
            self._append_audit_log(
                "release_candidate_loaded",
                {"name": str(steps), "source": "history"},
            )
            self.set_status(f"Loaded release candidate {steps} from history.")
            return
        if str(kind) == "change_event":
            try:
                idx = int(steps)
            except Exception:
                return
            if idx < 0 or idx >= len(self._workspace_change_log):
                return
            row = self._workspace_change_log[idx]
            QMessageBox.information(
                self,
                "Change Event",
                "\n".join(
                    [
                        f"Time: {row.get('timestamp_utc', '')}",
                        f"Actor: {row.get('user', '')}",
                        f"Event: {row.get('event', '')}",
                        f"Details: {json.dumps(row.get('details', {}), ensure_ascii=False)}",
                    ]
                ),
            )
            return
        try:
            steps_i = int(steps)
        except Exception:
            steps_i = 0
        if str(kind) == "undo" and steps_i > 0:
            self._undo_many(steps_i)
            return
        if str(kind) == "redo" and steps_i > 0:
            self._redo_many(steps_i)
            return

    def on_save_history_snapshot(self) -> None:
        if self.inst is None or not self.current_schedule:
            return
        snapshot_dir = self._ensure_snapshot_store_dir()
        default_name = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "_snapshot.json"
        )
        default_path = os.path.join(snapshot_dir, default_name)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save history snapshot",
            default_path,
            "JSON files (*.json)",
        )
        if not path:
            return
        payload = {
            "saved_at_utc": datetime.now(timezone.utc).isoformat(),
            "instance": instance_to_json(self.inst),
            "base_schedule": {
                str(int(a_id)): dict(info)
                for a_id, info in self.base_schedule.items()
                if isinstance(info, dict)
            },
            "state": self._state_to_json_ready(self._snapshot_state()),
            "undo": [
                self._state_to_json_ready(s)
                for s in self._undo_stack[-60:]
                if isinstance(s, dict)
            ],
            "redo": [
                self._state_to_json_ready(s)
                for s in self._redo_stack[-60:]
                if isinstance(s, dict)
            ],
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
            self.set_status(f"History snapshot saved: {path}")
            self._append_audit_log("history_snapshot_saved", {"path": str(path)})
            self._refresh_history_view()
        except Exception as exc:
            QMessageBox.critical(self, "Snapshot error", str(exc))

    def on_load_history_snapshot(self) -> None:
        snapshot_dir = self._ensure_snapshot_store_dir()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load history snapshot",
            snapshot_dir,
            "JSON files (*.json)",
        )
        if not path:
            return
        self._load_history_snapshot_path(str(path))

    def _load_history_snapshot_path(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("Snapshot must be a JSON object.")
            inst_raw = payload.get("instance")
            if not isinstance(inst_raw, dict):
                raise ValueError("Snapshot is missing instance data.")
            self.inst = instance_from_json(inst_raw)
            base_raw = payload.get("base_schedule", {})
            self.base_schedule = {
                int(a_id): dict(info)
                for a_id, info in (base_raw.items() if isinstance(base_raw, dict) else [])
                if isinstance(info, dict)
            }
            state_raw = payload.get("state", {})
            state = self._state_from_json_ready(
                state_raw if isinstance(state_raw, dict) else {}
            )
            self.current_schedule = {
                int(a_id): dict(info)
                for a_id, info in (state.get("current_schedule") or {}).items()
            }
            self.locked_activities = {
                int(a_id): dict(lock)
                for a_id, lock in (state.get("locked_activities") or {}).items()
            }
            held = state.get("held_activity_id")
            self.held_activity_id = int(held) if held is not None else None
            self._undo_stack = [
                self._state_from_json_ready(s)
                for s in (payload.get("undo") or [])
                if isinstance(s, dict)
            ]
            self._redo_stack = [
                self._state_from_json_ready(s)
                for s in (payload.get("redo") or [])
                if isinstance(s, dict)
            ]
            self._bump_schedule_revision()
            self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
            self._sync_instance_staff_from_schedule(self.current_schedule)
            self._sync_locks_to_instance()
            self._load_constraint_controls_from_instance(self.inst)
            self.populate_weeks()
            self.update_entities()
            self.update_table()
            self.update_quality_summary()
            self._refresh_history_buttons()
            self.set_status(f"History snapshot loaded: {path}")
            self._append_audit_log("history_snapshot_loaded", {"path": str(path)})
        except Exception as exc:
            QMessageBox.critical(self, "Snapshot error", str(exc))

    def on_show_snapshot_dir(self) -> None:
        path = self._ensure_snapshot_store_dir()
        QMessageBox.information(
            self,
            "Snapshot folder",
            f"History snapshot folder:\n{path}",
        )

    def _load_templates(self) -> None:
        self.constraint_templates = load_templates(self._template_store_path)
        if not self.constraint_templates:
            self.constraint_templates = dict(DEFAULT_TEMPLATES)
        self.constraint_template_combo.blockSignals(True)
        self.constraint_template_combo.clear()
        for name in sorted(self.constraint_templates.keys(), key=lambda x: str(x).lower()):
            self.constraint_template_combo.addItem(str(name), str(name))
        self.constraint_template_combo.blockSignals(False)

    def on_apply_constraint_template(self) -> None:
        name = self.constraint_template_combo.currentData()
        if not name:
            return
        self._invalidate_held_analysis_cache()
        template = self.constraint_templates.get(str(name))
        if not isinstance(template, dict):
            return
        hard = template.get("hard", {})
        soft = template.get("soft", {})
        controls: List[Any] = [
            self.hard_week1_cb,
            self.hard_repeat_week_cb,
            self.hard_course_totals_cb,
            self.hard_block_prof_cb,
            self.hard_staff_daily_cb,
            self.hard_staff_weekly_cb,
            self.hard_room_availability_cb,
            self.hard_travel_buffers_cb,
            self.hard_building_closures_cb,
            self.hard_calendar_rules_cb,
            self.hard_precedence_rules_cb,
            *self.soft_weight_spins.values(),
        ]
        for control in controls:
            control.blockSignals(True)
        if isinstance(hard, dict):
            self.hard_week1_cb.setChecked(bool(hard.get("week1_lectures_only", True)))
            self.hard_repeat_week_cb.setChecked(
                bool(hard.get("force_repeat_weekly_pattern", False))
            )
            self.hard_course_totals_cb.setChecked(
                bool(hard.get("enforce_course_totals", True))
            )
            self.hard_block_prof_cb.setChecked(
                bool(hard.get("enforce_block_professor_rules", True))
            )
            self.hard_staff_daily_cb.setChecked(
                bool(hard.get("enforce_staff_daily_caps", True))
            )
            self.hard_staff_weekly_cb.setChecked(
                bool(hard.get("enforce_staff_weekly_caps", True))
            )
            self.hard_room_availability_cb.setChecked(
                bool(hard.get("enforce_room_availability", True))
            )
            self.hard_travel_buffers_cb.setChecked(
                bool(hard.get("enforce_travel_time_buffers", True))
            )
            self.hard_building_closures_cb.setChecked(
                bool(hard.get("enforce_building_closures", True))
            )
            self.hard_calendar_rules_cb.setChecked(
                bool(hard.get("enforce_calendar_rules", True))
            )
            self.hard_precedence_rules_cb.setChecked(
                bool(hard.get("enforce_precedence_rules", True))
            )
        if isinstance(soft, dict):
            for key, spin in self.soft_weight_spins.items():
                if key in soft:
                    try:
                        spin.setValue(int(soft[key]))
                    except Exception:
                        pass
        for control in controls:
            control.blockSignals(False)
        if self.inst is not None:
            apply_template_to_instance(self.inst, template)
            if self.current_schedule:
                self.update_quality_summary()
                self.update_table()
        self._append_audit_log("constraint_template_applied", {"name": str(name)})
        self.set_status(f"Applied constraint template: {name}")

    def on_save_constraint_template(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "Save constraint template",
            "Template name:",
            text="Custom Template",
        )
        if not ok:
            return
        clean_name = str(name).strip()
        if not clean_name:
            return
        hard, soft = self._collect_constraint_settings()
        self.constraint_templates[clean_name] = {
            "hard": {str(k): bool(v) for k, v in hard.items()},
            "soft": {str(k): int(v) for k, v in soft.items()},
        }
        save_templates(self._template_store_path, self.constraint_templates)
        self._load_templates()
        idx = self.constraint_template_combo.findData(clean_name)
        if idx >= 0:
            self.constraint_template_combo.setCurrentIndex(idx)
        self._append_audit_log("constraint_template_saved", {"name": clean_name})
        self.set_status(f"Saved constraint template: {clean_name}")

    def _collect_constraint_settings(self) -> tuple[Dict[str, bool], Dict[str, int]]:
        hard = {
            "week1_lectures_only": self.hard_week1_cb.isChecked(),
            "force_repeat_weekly_pattern": self.hard_repeat_week_cb.isChecked(),
            "enforce_course_totals": self.hard_course_totals_cb.isChecked(),
            "enforce_block_professor_rules": self.hard_block_prof_cb.isChecked(),
            "enforce_staff_daily_caps": self.hard_staff_daily_cb.isChecked(),
            "enforce_staff_weekly_caps": self.hard_staff_weekly_cb.isChecked(),
            "enforce_room_availability": self.hard_room_availability_cb.isChecked(),
            "enforce_travel_time_buffers": self.hard_travel_buffers_cb.isChecked(),
            "enforce_building_closures": self.hard_building_closures_cb.isChecked(),
            "enforce_calendar_rules": self.hard_calendar_rules_cb.isChecked(),
            "enforce_precedence_rules": self.hard_precedence_rules_cb.isChecked(),
        }
        soft = {k: int(spin.value()) for k, spin in self.soft_weight_spins.items()}
        return hard, soft

    def _build_product_scenario_from_controls(self, mode: str) -> ProductScenario:
        scenario = build_builtin_product_scenario(
            str(mode),
            name=f"{APP_SHORT_NAME} {str(mode).replace('_', ' ').title()}",
        )
        scenario.calendar.day_start_time = str(DEFAULT_DAY_START)
        scenario.calendar.slot_minutes = int(DEFAULT_SLOT_MINUTES)
        scenario.calendar.break_minutes = int(DEFAULT_BREAK_MINUTES)
        if str(mode) == "custom":
            self._ensure_custom_generator_seeded()
            scenario.generation.mode = "custom"
            custom_config = dict(self._collect_custom_generation_config())
            scenario.generation.custom_config = dict(custom_config)
            scenario.calendar.days = list(custom_config.get("calendar_days") or scenario.calendar.days)
            scenario.calendar.term_blocks = list(custom_config.get("term_blocks") or [])
            weeks = list(custom_config.get("calendar_weeks") or [])
            if weeks:
                scenario.calendar.weeks = [int(w) for w in weeks]
            elif scenario.calendar.term_blocks:
                derived_weeks: List[int] = []
                next_week = 1
                for block in scenario.calendar.term_blocks:
                    if not isinstance(block, dict):
                        continue
                    length = max(1, int(block.get("length_weeks", 1) or 1))
                    block_weeks = list(range(int(next_week), int(next_week + length)))
                    block["weeks"] = list(block_weeks)
                    derived_weeks.extend(block_weeks)
                    next_week += length
                if derived_weeks:
                    scenario.calendar.weeks = derived_weeks
        hard, soft = self._collect_constraint_settings()
        scenario.constraints.hard_constraints = dict(hard)
        scenario.constraints.soft_weights = dict(soft)
        scenario.constraints.objective_profile = str(
            self.objective_profile_combo.currentData() or "balanced"
        )
        return scenario

    def _refresh_product_scenario_from_instance(self) -> None:
        if self.inst is None:
            self.product_scenario = None
            return
        name = getattr(self.inst, "product_metadata", {}).get(
            "name", "Imported scenario"
        )
        scenario = build_product_scenario_from_instance(
            self.inst,
            name=str(name),
            owner=APP_OWNER_NAME,
        )
        hard, soft = self._collect_constraint_settings()
        scenario.constraints.hard_constraints = dict(hard)
        scenario.constraints.soft_weights = dict(soft)
        self.product_scenario = scenario

    def _apply_constraint_settings(self, inst: Instance | None) -> None:
        if inst is None:
            return
        hard, soft = self._collect_constraint_settings()
        inst.hard_constraints = hard
        inst.soft_weights = soft
        inst.objective_profile = str(
            self.objective_profile_combo.currentData() or "balanced"
        )

    def _load_constraint_controls_from_instance(self, inst: Instance | None) -> None:
        hard_defaults = {
            "week1_lectures_only": True,
            "force_repeat_weekly_pattern": False,
            "enforce_course_totals": True,
            "enforce_block_professor_rules": True,
            "enforce_staff_daily_caps": True,
            "enforce_staff_weekly_caps": True,
            "enforce_room_availability": True,
            "enforce_travel_time_buffers": True,
            "enforce_building_closures": True,
            "enforce_calendar_rules": True,
            "enforce_precedence_rules": True,
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
            "same_kind_week": 3,
        }
        hard = hard_defaults
        soft = soft_defaults
        objective_profile = "balanced"
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
            objective_profile = str(
                getattr(inst, "objective_profile", "balanced") or "balanced"
            )
        controls: List[Any] = [
            self.hard_week1_cb,
            self.hard_repeat_week_cb,
            self.hard_course_totals_cb,
            self.hard_block_prof_cb,
            self.hard_staff_daily_cb,
            self.hard_staff_weekly_cb,
            self.hard_room_availability_cb,
            self.hard_travel_buffers_cb,
            self.hard_building_closures_cb,
            self.hard_calendar_rules_cb,
            self.hard_precedence_rules_cb,
            self.objective_profile_combo,
            *self.soft_weight_spins.values(),
        ]
        for control in controls:
            control.blockSignals(True)
        self.hard_week1_cb.setChecked(hard["week1_lectures_only"])
        self.hard_repeat_week_cb.setChecked(hard["force_repeat_weekly_pattern"])
        self.hard_course_totals_cb.setChecked(hard["enforce_course_totals"])
        self.hard_block_prof_cb.setChecked(hard["enforce_block_professor_rules"])
        self.hard_staff_daily_cb.setChecked(hard["enforce_staff_daily_caps"])
        self.hard_staff_weekly_cb.setChecked(hard["enforce_staff_weekly_caps"])
        self.hard_room_availability_cb.setChecked(hard["enforce_room_availability"])
        self.hard_travel_buffers_cb.setChecked(hard["enforce_travel_time_buffers"])
        self.hard_building_closures_cb.setChecked(hard["enforce_building_closures"])
        self.hard_calendar_rules_cb.setChecked(hard["enforce_calendar_rules"])
        self.hard_precedence_rules_cb.setChecked(hard["enforce_precedence_rules"])
        profile_idx = self.objective_profile_combo.findData(str(objective_profile))
        if profile_idx < 0:
            profile_idx = self.objective_profile_combo.findData("balanced")
        if profile_idx >= 0:
            self.objective_profile_combo.setCurrentIndex(profile_idx)
        for key, spin in self.soft_weight_spins.items():
            spin.setValue(int(soft.get(key, spin.value())))
        for control in controls:
            control.blockSignals(False)

    def on_apply_constraints_to_instance(self) -> None:
        if self.inst is None:
            self.set_status("Generate or load an instance first")
            return
        self._apply_constraint_settings(self.inst)
        self._refresh_product_scenario_from_instance()
        self.update_quality_summary()
        self.set_status("Constraint settings applied to current instance")

    def on_constraint_controls_changed(self, *_args: Any) -> None:
        if self.inst is None:
            return
        try:
            self._invalidate_held_analysis_cache()
            self._apply_constraint_settings(self.inst)
            self._refresh_product_scenario_from_instance()
            if self.current_schedule:
                self.update_quality_summary()
                self.update_table()
        except Exception:
            traceback.print_exc()
            self.set_status("Failed to apply constraints from controls")

    def _on_mode_changed(self) -> None:
        mode = self.mode_combo.currentText()
        if mode in {"ss23_uni_like", "uni_like"}:
            if hasattr(self, "room_mode_combo"):
                idx = self.room_mode_combo.findData("auto")
                self.room_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
            if hasattr(self, "objective_profile_combo"):
                idx = self.objective_profile_combo.findData("university_fast")
                if idx < 0:
                    idx = self.objective_profile_combo.findData("fast_feasible")
                if idx >= 0:
                    self.objective_profile_combo.setCurrentIndex(idx)
            if hasattr(self, "objective_cb"):
                self.objective_cb.setChecked(False)
        if mode == "custom":
            self._ensure_custom_generator_seeded()
            self.workspace_tabs.setCurrentIndex(1)

    # ----- helpers -----

    def set_status(self, text: str):
        self._status_full_text = str(text)
        self._refresh_status_label()
        QApplication.processEvents()

    @staticmethod
    def _compact_status_text(text: str) -> str:
        full = str(text or "")
        match = re.match(
            r"^Improving\.\.\. (\d+)% \(iter (\d+)/(\d+), "
            r"(?:original=(\d+), )?current=(\d+), best=(\d+)\)$",
            full,
        )
        if not match:
            return full
        pct, done, total, original, current, best = match.groups()
        if original is None:
            return f"Improving {pct}% | {done}/{total} | current {current} | best {best}"
        return f"Improving {pct}% | {done}/{total} | {original}->{current} | best {best}"

    def _selected_improve_focus_term(self) -> str:
        if not hasattr(self, "improve_focus_combo"):
            return ""
        data = self.improve_focus_combo.currentData()
        term = str(data or "").strip()
        return term if term in SOFT_WEIGHT_DEFAULTS else ""

    @staticmethod
    def _focus_label(term: str) -> str:
        return str(term or "overall").replace("_", " ")

    def _build_focused_improve_instance(self, term: str) -> Instance:
        if self.inst is None:
            raise ValueError("No instance loaded")
        return build_focused_improve_instance(self.inst, term)

    def _refresh_status_label(self) -> None:
        full = str(getattr(self, "_status_full_text", "") or "")
        if not hasattr(self, "status_label"):
            return
        self.status_label.setToolTip(full)
        try:
            self.status_label.setText(self._compact_status_text(full))
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
        self.objective_profile_combo.setEnabled(enable)
        self.objective_cb.setEnabled(enable)
        self.debug_diagnostics_cb.setEnabled(enable)
        self.time_limit_spin.setEnabled(enable)
        self.random_seed_spin.setEnabled(enable)
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

    def _room_mode_selection(self) -> str:
        if not hasattr(self, "room_mode_combo") or self.room_mode_combo is None:
            return "cp_rooms"
        data = self.room_mode_combo.currentData()
        if str(data) in {"auto", "cp_rooms", "greedy"}:
            return str(data)
        text = str(self.room_mode_combo.currentText()).strip().lower()
        if "fast" in text or "greedy" in text:
            return "greedy"
        if "auto" in text:
            return "auto"
        return "cp_rooms"

    def _estimate_cp_room_candidate_count(self, inst: Any | None = None) -> int:
        inst = inst or self.inst
        if inst is None:
            return 0
        total = 0
        for act in inst.activities.values():
            kind = str(act.kind)
            need = sum(
                int(inst.groups[g_id].size)
                for g_id in act.group_ids
                if g_id in inst.groups
            )
            count = 0
            for room in inst.rooms.values():
                if int(room.capacity) < int(need):
                    continue
                room_type = str(room.room_type)
                if kind == "LEC":
                    if room_type == "LECTURE":
                        count += 1
                elif kind == "TUT":
                    if room_type in {"TUTORIAL", "LECTURE"}:
                        count += 1
                elif kind == "LAB":
                    tag = str(getattr(act, "requires_specialization", "") or "").strip()
                    if tag:
                        tags = set(getattr(room, "specialization_tags", []) or [])
                        if room_type == "SPECIALIZED_LAB" and tag in tags:
                            count += 1
                    elif room_type in {"COMPUTER_LAB", "SPECIALIZED_LAB"}:
                        count += 1
            total += int(count)
        return int(total)

    def _auto_room_mode_uses_greedy(self, inst: Any | None = None) -> bool:
        inst = inst or self.inst
        if inst is None:
            return False
        activity_count = len(getattr(inst, "activities", {}) or {})
        room_count = len(getattr(inst, "rooms", {}) or {})
        candidate_count = self._estimate_cp_room_candidate_count(inst)
        return (
            int(activity_count) >= 1000
            or int(room_count) >= 100
            or int(candidate_count) >= 50000
        )

    def _selected_room_mode(self) -> str:
        selection = self._room_mode_selection()
        if selection == "auto":
            return "greedy" if self._auto_room_mode_uses_greedy() else "cp_rooms"
        return selection

    def _selected_room_mode_label(self) -> str:
        selection = self._room_mode_selection()
        resolved = self._selected_room_mode()
        if selection == "auto":
            candidate_count = self._estimate_cp_room_candidate_count()
            return f"auto -> {resolved} (estimated CP room candidates={candidate_count})"
        return str(resolved)

    def _selected_worker_count(self) -> int:
        if hasattr(self, "workers_preset_combo") and self.workers_preset_combo is not None:
            data = self.workers_preset_combo.currentData()
            try:
                return max(1, min(64, int(data)))
            except Exception:
                pass
        return max(1, min(64, int(DEFAULT_CP_WORKERS)))

    def on_solver_output_ready(self) -> None:
        sender_proc = self.sender()
        if (
            sender_proc is not None
            and self.proc is not None
            and sender_proc is not self.proc
        ):
            return
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
                self.week_combo.addItem(self._week_display_label(int(w)), w)
        self.week_combo.blockSignals(False)
        self._refresh_diagnostics_controls()

    def _week_display_label(self, week: int) -> str:
        if self.inst is None:
            return f"Week {int(week)}"
        for block in getattr(self.inst, "term_blocks", []) or []:
            if not isinstance(block, dict):
                continue
            weeks = {int(v) for v in (block.get("weeks") or [])}
            if int(week) in weeks:
                label = str(block.get("label", "Term") or "Term").strip()
                return f"{label} · W{int(week)}"
        return f"Week {int(week)}"

    def update_entities(self):
        try:
            if self.inst is None:
                self.entity_combo.clear()
                self.entity_combo.setEnabled(False)
                self._refresh_diagnostics_controls()
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
            self._refresh_diagnostics_controls()
            self.update_table()
        except Exception:
            traceback.print_exc()
            self.entity_combo.blockSignals(False)
            self.set_status("Failed to update view entities")

    def clear_table(self):
        self._render_empty_calendar(None, None)
        self._cell_activity_map = {}
        self._held_move_analysis_map = {}
        self._invalidate_held_analysis_cache()
        self.selected_cell_row = None
        self.selected_cell_col = None
        self.selected_activity_id = None
        self._refresh_quick_actions()
        self.quality_label.setText("")
        self._last_solver_result_meta = {}
        self._update_diagnostics_dashboard()

    def _refresh_diagnostics_controls(self) -> None:
        if not hasattr(self, "why_not_activity_combo"):
            return
        self.why_not_activity_combo.blockSignals(True)
        self.why_not_activity_combo.clear()
        self.why_not_week_combo.blockSignals(True)
        self.why_not_week_combo.clear()
        self.why_not_day_combo.blockSignals(True)
        self.why_not_day_combo.clear()
        self.why_not_slot_combo.blockSignals(True)
        self.why_not_slot_combo.clear()
        self.heatmap_entity_combo.blockSignals(True)
        self.heatmap_entity_combo.clear()
        if self.inst is not None:
            for a_id, act in self.inst.activities.items():
                course = self.inst.courses.get(int(act.course_id))
                label = f"A{int(a_id)}"
                if course is not None:
                    label += f" {course.code}"
                label += f" {str(act.kind)}"
                self.why_not_activity_combo.addItem(label, int(a_id))
            for w in self.inst.weeks:
                self.why_not_week_combo.addItem(self._week_display_label(int(w)), int(w))
            for day in self.inst.days:
                self.why_not_day_combo.addItem(str(day), str(day))
            for slot in range(self.inst.slots_per_day):
                self.why_not_slot_combo.addItem(f"S{int(slot) + 1}", int(slot))
        self.why_not_activity_combo.blockSignals(False)
        self.why_not_week_combo.blockSignals(False)
        self.why_not_day_combo.blockSignals(False)
        self.why_not_slot_combo.blockSignals(False)
        self.heatmap_entity_combo.blockSignals(False)
        self._refresh_heatmap_entities()

    def _refresh_heatmap_entities(self) -> None:
        if not hasattr(self, "heatmap_entity_combo"):
            return
        self.heatmap_entity_combo.blockSignals(True)
        self.heatmap_entity_combo.clear()
        if self.inst is not None:
            kind = str(self.heatmap_entity_kind_combo.currentData() or "groups")
            if kind == "groups":
                for g_id, group in self.inst.groups.items():
                    self.heatmap_entity_combo.addItem(str(group.name), int(g_id))
            else:
                for s_id, staff in self.inst.staff.items():
                    self.heatmap_entity_combo.addItem(str(staff.name), int(s_id))
        self.heatmap_entity_combo.blockSignals(False)
        self._update_heatmap_table()

    def _update_diagnostics_dashboard(self) -> None:
        if not hasattr(self, "diagnostics_summary_text"):
            return
        if self.inst is None:
            self.diagnostics_summary_text.setPlainText(
                "Generate, solve, or load a scenario to inspect diagnostic output."
            )
            self.why_not_output_text.setPlainText("")
            self._update_heatmap_table()
            return
        hard_errors = (
            self._collect_conflict_errors()
            if self.current_schedule
            else []
        )
        diagnosis = build_unsat_rule_diagnosis(
            self.inst,
            self.current_schedule if hard_errors else None,
        )
        if not diagnosis:
            self.diagnostics_summary_text.setPlainText(
                "No structural infeasibility signals detected in the current workspace."
            )
        else:
            lines = ["Rule diagnosis:"]
            for row in diagnosis:
                lines.append(
                    f"- {row['rule_id']} (severity {row['severity']}): {row['summary']}"
                )
            self.diagnostics_summary_text.setPlainText("\n".join(lines))
        self._update_heatmap_table()

    def _update_heatmap_table(self) -> None:
        if not hasattr(self, "heatmap_table"):
            return
        if self.inst is None or not self.current_schedule:
            self.heatmap_table.clear()
            self.heatmap_table.setRowCount(0)
            self.heatmap_table.setColumnCount(0)
            self.heatmap_summary_label.setText(
                "Heatmaps unavailable until a schedule is loaded."
            )
            return
        payload = compute_entity_heatmaps(self.inst, self.current_schedule)
        entity_kind = str(self.heatmap_entity_kind_combo.currentData() or "groups")
        entity_id = self.heatmap_entity_combo.currentData()
        metric = str(self.heatmap_metric_combo.currentData() or "load")
        entity_rows = dict(payload.get(entity_kind, {}) or {})
        if entity_id is None or int(entity_id) not in entity_rows:
            self.heatmap_table.clear()
            self.heatmap_table.setRowCount(0)
            self.heatmap_table.setColumnCount(0)
            self.heatmap_summary_label.setText("Select an entity to inspect heatmaps.")
            return
        entry = dict(entity_rows[int(entity_id)])
        matrix = entry.get(metric, []) or []
        days = list(payload.get("days", []) or [])
        slots = int(payload.get("slots_per_day", 0))
        self.heatmap_table.clear()
        self.heatmap_table.setRowCount(len(days))
        self.heatmap_table.setColumnCount(slots)
        self.heatmap_table.setVerticalHeaderLabels(days)
        self.heatmap_table.setHorizontalHeaderLabels([f"S{idx + 1}" for idx in range(slots)])
        max_value = max((int(value) for row in matrix for value in row), default=0)
        for row_idx, row in enumerate(matrix):
            for col_idx, value in enumerate(row):
                item = QTableWidgetItem(str(int(value)))
                ratio = 0.0 if max_value <= 0 else float(value) / float(max_value)
                red = min(255, int(40 + (180 * ratio)))
                green = min(255, int(80 + (110 * (1.0 - ratio))))
                item.setBackground(QBrush(QColor(red, green, 90)))
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                )
                self.heatmap_table.setItem(row_idx, col_idx, item)
        self.heatmap_summary_label.setText(
            f"{entry.get('entity_label', entity_id)} | Metric: {metric} | Peak intensity: {max_value}"
        )

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
        analysis_map = self._held_move_analysis_from_cache(
            int(week), compute_scores=True, include_conflicts=False
        )
        if not analysis_map:
            self._request_held_move_analysis_async(
                int(week), compute_scores=True, include_conflicts=False
            )
            self.set_status("Computing held target analysis in background...")
            return
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
                f"No valid target slots in week {int(week)} for the held activity under current hard constraints.",
            )
        else:
            QMessageBox.information(
                self,
                "Held activity targets",
                f"Valid slots in week {int(week)}:\n" + "\n".join(valid_targets),
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
        bulk_selected_ids = self._selected_activity_ids_from_table_selection()
        has_bulk_selection = bool(bulk_selected_ids)
        has_held = (
            self.held_activity_id is not None
            and self.held_activity_id in self.current_schedule
        )
        has_selected_slot = selected_cell is not None

        self.selected_activity_combo.setEnabled(bool(selected_ids))
        self.quick_edit_btn.setEnabled(has_selected_activity)
        self.quick_hold_btn.setEnabled(has_selected_activity)
        self.quick_bulk_btn.setEnabled(has_bulk_selection)
        self.quick_time_lock_btn.setEnabled(has_selected_activity)
        self.quick_room_lock_btn.setEnabled(has_selected_activity)
        self.quick_move_btn.setEnabled(has_held and has_selected_slot)
        self.quick_explain_btn.setEnabled(has_held and has_selected_slot)
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

    def _on_schedule_drag_requested(self, row: int, col: int) -> None:
        if self.inst is None or not self.current_schedule:
            return
        week = self._current_week()
        if week is None or not (0 <= int(row) < len(self.inst.days)):
            return
        day = str(self.inst.days[int(row)])
        act_ids = list(self._cell_activity_ids_for_view(day, int(col), int(week)))
        if not act_ids:
            return
        a_id = None
        if self.selected_activity_id is not None and int(self.selected_activity_id) in act_ids:
            a_id = int(self.selected_activity_id)
        elif len(act_ids) == 1:
            a_id = int(act_ids[0])
        else:
            a_id = self._choose_activity_from_ids(act_ids, "Drag activity")
        if a_id is not None:
            self._set_held_activity(int(a_id))
            self.set_status(
                f"Dragging {self._activity_title(int(a_id))}. Drop it on a target slot to move safely."
            )

    def _on_schedule_drop_requested(self, row: int, col: int) -> None:
        if self.inst is None or self.held_activity_id is None:
            return
        week = self._current_week()
        if week is None or not (0 <= int(row) < len(self.inst.days)):
            return
        day = str(self.inst.days[int(row)])
        self._attempt_move_held_to(str(day), int(col), int(week))

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

    def on_quick_bulk_edit_selected(self) -> None:
        if self.inst is None or not self.current_schedule:
            return
        selected_ids = self._selected_activity_ids_from_table_selection()
        if not selected_ids:
            self.set_status("Select timetable cells first")
            return
        dlg = BulkEditDialog(self, weeks=list(self.inst.weeks), count=len(selected_ids))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        changes = dlg.get_values()
        updated = self._clone_schedule()
        updated_locks = {
            int(a_id): dict(lock)
            for a_id, lock in self.locked_activities.items()
            if isinstance(lock, dict)
        }
        skipped: List[int] = []
        changed_count = 0
        for a_id in selected_ids:
            info = updated.get(int(a_id))
            if info is None:
                continue
            new_week = int(info["week"])
            week_mode = str(changes.get("week_mode", "keep"))
            if week_mode == "set":
                new_week = int(changes.get("target_week"))
            elif week_mode == "shift":
                new_week = int(info["week"]) + int(changes.get("week_delta", 0))
            if new_week not in set(int(w) for w in self.inst.weeks):
                skipped.append(int(a_id))
                continue
            ok, _reason = self.check_move(
                int(a_id),
                str(info["day"]),
                int(info["slot"]),
                int(info["room_id"]),
                int(info["staff_id"]),
                int(new_week),
                schedule_override=updated,
            )
            if week_mode != "keep" and not ok:
                skipped.append(int(a_id))
                continue
            if week_mode != "keep":
                info["week"] = int(new_week)
                changed_count += 1

            note_mode = str(changes.get("note_mode", "keep"))
            if note_mode == "set":
                info["admin_note"] = str(changes.get("note_text", "")).strip()
                changed_count += 1
            elif note_mode == "clear":
                if "admin_note" in info:
                    info.pop("admin_note", None)
                    changed_count += 1

            fixed = dict(updated_locks.get(int(a_id), {}))
            time_mode = str(changes.get("time_lock_mode", "keep"))
            if time_mode == "enable":
                fixed["day"] = str(info["day"])
                fixed["slot"] = int(info["slot"])
                changed_count += 1
            elif time_mode == "disable":
                if "day" in fixed or "slot" in fixed:
                    fixed.pop("day", None)
                    fixed.pop("slot", None)
                    changed_count += 1

            room_mode = str(changes.get("room_lock_mode", "keep"))
            if room_mode == "enable":
                fixed["room_id"] = int(info["room_id"])
                changed_count += 1
            elif room_mode == "disable":
                if "room_id" in fixed:
                    fixed.pop("room_id", None)
                    changed_count += 1

            if fixed:
                updated_locks[int(a_id)] = fixed
            else:
                updated_locks.pop(int(a_id), None)

        if changed_count <= 0:
            self.set_status("Bulk edit made no changes")
            return
        self._push_undo_state()
        self.locked_activities = updated_locks
        self._commit_schedule(
            updated,
            f"Bulk edit applied to {int(len(selected_ids) - len(skipped))} activities"
            + (f"; skipped {len(skipped)}" if skipped else ""),
        )
        self._refresh_quick_actions()

    def on_quick_move_held_here(self) -> None:
        cell = self._selected_cell_day_slot()
        if cell is None:
            return
        week = self._current_week()
        if week is None:
            return
        day, slot = cell
        self._attempt_move_held_to(str(day), int(slot), int(week))
        self._refresh_quick_actions()

    def on_quick_explain_move(self) -> None:
        if self.inst is None or self.held_activity_id is None:
            return
        cell = self._selected_cell_day_slot()
        week = self._current_week()
        if cell is None or week is None:
            return
        held_id = int(self.held_activity_id)
        info = self.current_schedule.get(held_id)
        if info is None:
            return
        target_day, target_slot = cell
        result = explain_candidate_slot(
            self.inst,
            self.current_schedule,
            activity_id=int(held_id),
            week=int(week),
            day=str(target_day),
            slot=int(target_slot),
            room_id=int(info["room_id"]),
            staff_id=int(info["staff_id"]),
        )
        ok = bool(result.get("valid", False))
        reason = (
            "Candidate placement is valid."
            if ok
            else "; ".join(str(line) for line in (result.get("reasons") or [])[:3])
        )
        conflicts = []
        if not ok:
            conflicts = self._find_move_conflicts(
                held_id,
                str(target_day),
                int(target_slot),
                int(info["room_id"]),
                int(info["staff_id"]),
                int(week),
            )
        text = build_move_explanation_text(
            activity_id=int(held_id),
            target_week=int(week),
            target_day=str(target_day),
            target_slot=int(target_slot),
            valid=bool(ok),
            reason=str(reason),
            conflicts=conflicts,
        )
        delta = int(result.get("soft_penalty_delta", 0))
        text += f"\n\nSoft penalty delta: {delta:+d}"
        QMessageBox.information(self, "Move Explanation", text)

    def on_explain_candidate_slot(self) -> None:
        if self.inst is None or not self.current_schedule:
            self.set_status("No schedule loaded")
            return
        activity_id = self.why_not_activity_combo.currentData()
        week = self.why_not_week_combo.currentData()
        day = self.why_not_day_combo.currentData()
        slot = self.why_not_slot_combo.currentData()
        if activity_id is None or week is None or day is None or slot is None:
            self.why_not_output_text.setPlainText("Select an activity, week, day, and slot.")
            return
        info = self.current_schedule.get(int(activity_id))
        room_id = int(info["room_id"]) if info and info.get("room_id") is not None else None
        staff_id = int(info["staff_id"]) if info and info.get("staff_id") is not None else None
        try:
            result = explain_candidate_slot(
                self.inst,
                self.current_schedule,
                activity_id=int(activity_id),
                week=int(week),
                day=str(day),
                slot=int(slot),
                room_id=room_id,
                staff_id=staff_id,
            )
        except Exception as exc:
            traceback.print_exc()
            self.why_not_output_text.setPlainText(str(exc))
            return
        lines = [
            f"Activity A{int(activity_id)} -> W{int(week)} {str(day)} S{int(slot) + 1}",
            f"Valid: {bool(result.get('valid', False))}",
            f"Soft penalty delta: {int(result.get('soft_penalty_delta', 0)):+d}",
        ]
        reasons = list(result.get("reasons", []) or [])
        if reasons:
            lines.append("Reasons:")
            lines.extend(f"- {line}" for line in reasons[:8])
        self.why_not_output_text.setPlainText("\n".join(lines))
        self.set_status("Candidate slot explanation updated")

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
        self._bump_schedule_revision()
        self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
        self._sync_instance_staff_from_schedule(self.current_schedule)
        self._sync_locks_to_instance()
        self.update_table()
        self.update_quality_summary()
        self.set_status(status)
        self._save_persistent_history()

    def _reset_history(self) -> None:
        self._undo_stack = []
        self._redo_stack = []
        self._refresh_history_buttons()
        self._save_persistent_history()

    def _push_undo_state(self) -> None:
        if self.inst is None:
            return
        self._undo_stack.append(self._snapshot_state())
        if len(self._undo_stack) > 120:
            self._undo_stack.pop(0)
        self._redo_stack = []
        self._refresh_history_buttons()
        self._save_persistent_history()

    def _refresh_history_buttons(self) -> None:
        self.undo_button.setEnabled(bool(self._undo_stack))
        self.redo_button.setEnabled(bool(self._redo_stack))
        self.revert_button.setEnabled(bool(self.base_schedule))
        self.conflicts_button.setEnabled(bool(self.current_schedule))
        self._refresh_history_view()

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
        original_weeks: Dict[int, int] = {}
        for a_id, act in self.inst.activities.items():
            original_weeks[int(a_id)] = int(act.week)
        try:
            self._sync_instance_activity_weeks_from_schedule(schedule)
            return validate_schedule_against_instance(
                self.inst,
                schedule,
                strict_rooms=True,
                require_all_activities=bool(require_all),
            )
        except Exception:
            return []
        finally:
            for a_id, week in original_weeks.items():
                act = self.inst.activities.get(int(a_id))
                if act is not None:
                    act.week = int(week)

    def _collect_conflict_errors(self) -> List[str]:
        return self._validate_schedule_hard_errors(
            self.current_schedule, require_all=True
        )

    def _activity_conflict_context(self, a_id: int) -> str:
        inst = self.inst
        info = self.current_schedule.get(int(a_id))
        if inst is None or info is None:
            return f"A{int(a_id)}"

        room_id = info.get("room_id")
        room_name = "Unassigned"
        if room_id is not None:
            room = inst.rooms.get(int(room_id))
            if room is not None:
                room_name = f"{room.name} [id {int(room_id)}]"
            else:
                room_name = f"R{int(room_id)}"

        staff_id = info.get("staff_id")
        staff_name = "Unknown"
        if staff_id is not None:
            staff = inst.staff.get(int(staff_id))
            if staff is not None:
                staff_name = f"{staff.name} [id {int(staff_id)}]"
            else:
                staff_name = f"S{int(staff_id)}"

        group_parts: List[str] = []
        for g_id in info.get("group_ids", []) or []:
            try:
                gid = int(g_id)
            except Exception:
                continue
            grp = inst.groups.get(gid)
            if grp is not None:
                group_parts.append(f"{grp.name} [id {gid}]")
            else:
                group_parts.append(f"G{gid}")
        group_text = ", ".join(group_parts) if group_parts else "-"

        day = str(info.get("day", "?"))
        slot = int(info.get("slot", 0)) + 1
        week = int(info.get("week", 0))
        return (
            f"A{int(a_id)} @ W{week} {day} S{slot} | "
            f"room={room_name} | staff={staff_name} | groups={group_text}"
        )

    def _humanize_conflict_error(self, message: str) -> str:
        msg = str(message or "")

        def _slot_repl(match: re.Match[str]) -> str:
            try:
                raw_slot = int(match.group(1))
            except Exception:
                return match.group(0)
            return f"slot S{raw_slot + 1}"

        text = re.sub(r"\bslot\s+(-?\d+)\b", _slot_repl, msg)
        activity_ids: List[int] = []
        for token in re.findall(r"\bA(\d+)\b", text):
            try:
                a_id = int(token)
            except Exception:
                continue
            if a_id not in activity_ids:
                activity_ids.append(a_id)

        if not activity_ids:
            return text

        details: List[str] = []
        for a_id in activity_ids[:2]:
            details.append(self._activity_conflict_context(a_id))

        if len(activity_ids) >= 2:
            a0 = self.current_schedule.get(int(activity_ids[0]), {})
            a1 = self.current_schedule.get(int(activity_ids[1]), {})
            lower = text.lower()
            if "group overlap" in lower:
                shared = sorted(
                    set(int(g) for g in (a0.get("group_ids") or []))
                    & set(int(g) for g in (a1.get("group_ids") or []))
                )
                if shared:
                    grp_labels: List[str] = []
                    if self.inst is not None:
                        for gid in shared:
                            grp = self.inst.groups.get(int(gid))
                            grp_labels.append(
                                f"{grp.name} [id {int(gid)}]"
                                if grp is not None
                                else f"G{int(gid)}"
                            )
                    else:
                        grp_labels = [f"G{int(gid)}" for gid in shared]
                    details.append("shared groups=" + ", ".join(grp_labels))
            if "room overlap" in lower:
                rid0 = a0.get("room_id")
                rid1 = a1.get("room_id")
                if rid0 is not None and rid1 is not None and int(rid0) == int(rid1):
                    room_desc = f"R{int(rid0)}"
                    if self.inst is not None:
                        room = self.inst.rooms.get(int(rid0))
                        if room is not None:
                            room_desc = f"{room.name} [id {int(rid0)}]"
                    details.append(f"same room={room_desc}")
            if "staff overlap" in lower:
                sid0 = a0.get("staff_id")
                sid1 = a1.get("staff_id")
                if sid0 is not None and sid1 is not None and int(sid0) == int(sid1):
                    staff_desc = f"S{int(sid0)}"
                    if self.inst is not None:
                        staff = self.inst.staff.get(int(sid0))
                        if staff is not None:
                            staff_desc = f"{staff.name} [id {int(sid0)}]"
                    details.append(f"same staff={staff_desc}")

        return f"{text} | " + " | ".join(details)

    def _jump_to_activity(self, a_id: int) -> bool:
        if self.inst is None:
            return False
        info = self.current_schedule.get(int(a_id))
        if info is None:
            return False

        week = int(info.get("week", 0))
        day = str(info.get("day", ""))
        slot = int(info.get("slot", 0))

        week_idx = self.week_combo.findData(int(week))
        if week_idx >= 0 and week_idx != self.week_combo.currentIndex():
            self.week_combo.setCurrentIndex(week_idx)

        all_idx = self.view_type_combo.findText("All")
        if all_idx >= 0 and all_idx != self.view_type_combo.currentIndex():
            self.view_type_combo.setCurrentIndex(all_idx)
        else:
            self.update_table()

        if day not in self.inst.days:
            return False
        row = int(self.inst.days.index(day))
        col = int(max(0, min(slot, int(self.inst.slots_per_day) - 1)))
        self.selected_cell_row = row
        self.selected_cell_col = col
        self.selected_activity_id = int(a_id)
        self._refresh_quick_actions()

        try:
            self.table.setCurrentCell(row, col)
            item = self.table.item(row, col)
            if item is not None:
                self.table.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
        except Exception:
            pass
        return True

    def _solve_current_conflicts(self, errors: List[str] | None = None) -> None:
        if self.inst is None or not self.current_schedule:
            self.set_status("No schedule to repair")
            return
        if self.proc is not None:
            QMessageBox.warning(self, "Busy", "Solver already running.")
            return

        raw_errors = list(errors or self._collect_conflict_errors())
        if not raw_errors:
            self.set_status("No hard conflicts to solve")
            return

        conflict_ids: Set[int] = set()
        for err in raw_errors:
            for token in re.findall(r"\bA(\d+)\b", str(err)):
                try:
                    conflict_ids.add(int(token))
                except Exception:
                    continue

        if not conflict_ids:
            self.set_status("Could not map conflicts to activities; running full solve")
            self.on_solve()
            return

        prior_locks = {
            int(a_id): dict(lock)
            for a_id, lock in self.locked_activities.items()
            if isinstance(lock, dict)
        }
        freeze_locks = build_freeze_locks(
            self.current_schedule,
            unlocked_activity_ids=set(int(a_id) for a_id in conflict_ids),
        )
        self.locked_activities = freeze_locks
        self._sync_locks_to_instance()
        self._restore_locks_after_solve = prior_locks
        self._append_audit_log(
            "conflict_repair_started",
            {
                "conflicts": int(len(raw_errors)),
                "conflict_activities": int(len(conflict_ids)),
                "frozen_activities": int(len(freeze_locks)),
            },
        )
        self.set_status(
            f"Repairing conflicts: {len(raw_errors)} issue(s), "
            f"{len(conflict_ids)} conflicting activity(ies)"
        )
        self._start_solver_process(keep_locks=True)

    def on_fix_current_conflicts(self) -> None:
        self._solve_current_conflicts()

    def _focus_penalty_activity_ids(self, term: str, *, limit: int = 80) -> List[int]:
        if self.inst is None or not self.current_schedule:
            return []
        return focus_penalty_activity_ids(
            self.inst,
            self.current_schedule,
            term,
            limit=int(limit),
        )

    def on_focused_cp_sat_polish(self) -> None:
        if self.inst is None or not self.current_schedule:
            self.set_status("No schedule to polish")
            return
        if self.proc is not None:
            QMessageBox.warning(self, "Busy", "Solver already running.")
            return
        term = self._selected_improve_focus_term()
        if not term:
            QMessageBox.information(
                self,
                "Focused CP-SAT polish",
                "Choose a Focus term first, then run focused CP-SAT polish.",
            )
            self.set_status("Focused CP-SAT polish needs a focus term")
            return
        affected = self._focus_penalty_activity_ids(term, limit=100)
        if not affected:
            self.set_status(f"No activities found for {self._focus_label(term)}")
            return
        prior_locks = {
            int(a_id): dict(lock)
            for a_id, lock in self.locked_activities.items()
            if isinstance(lock, dict)
        }
        self.locked_activities = build_freeze_locks(
            self.current_schedule,
            unlocked_activity_ids=set(int(a_id) for a_id in affected),
        )
        self._sync_locks_to_instance()
        self._restore_locks_after_solve = prior_locks
        profile_before = self.objective_profile_combo.currentData()
        objective_before = self.objective_cb.isChecked()
        room_before = self.room_mode_combo.currentData()
        try:
            profile_idx = self.objective_profile_combo.findData("balanced")
            if profile_idx >= 0:
                self.objective_profile_combo.setCurrentIndex(profile_idx)
            room_idx = self.room_mode_combo.findData("greedy")
            if room_idx >= 0:
                self.room_mode_combo.setCurrentIndex(room_idx)
            self.objective_cb.setChecked(True)
            self.set_status(
                f"Focused CP-SAT polish: {self._focus_label(term)} "
                f"({len(affected)} activities, locks={len(self.locked_activities)})"
            )
            self._append_audit_log(
                "focused_cp_sat_polish_started",
                {
                    "term": str(term),
                    "affected_activities": int(len(affected)),
                    "frozen_activities": int(len(self.locked_activities)),
                },
            )
            self._start_solver_process(keep_locks=True)
        finally:
            profile_restore = self.objective_profile_combo.findData(profile_before)
            if profile_restore >= 0:
                self.objective_profile_combo.setCurrentIndex(profile_restore)
            room_restore = self.room_mode_combo.findData(room_before)
            if room_restore >= 0:
                self.room_mode_combo.setCurrentIndex(room_restore)
            self.objective_cb.setChecked(bool(objective_before))

    def on_show_score_breakdown(self) -> None:
        if self.inst is None or not self.current_schedule:
            self.set_status("No schedule to score")
            return
        try:
            breakdown = compute_penalty_breakdown(self.inst, self.current_schedule)
            drivers = rank_penalty_drivers(self.inst, self.current_schedule, limit=12)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, "Score breakdown", str(exc))
            return
        total = int(breakdown.get("total", 0))
        lines = [f"Global soft penalty: {total}", "", "Top penalty drivers:"]
        for row in drivers:
            lines.append(
                f"- {row['term']}: {int(row['penalty'])} "
                f"({float(row['share']) * 100:.1f}%)"
            )
        lines.append("")
        lines.append("All terms:")
        for key, value in sorted(breakdown.items()):
            if key != "total":
                lines.append(f"- {key}: {int(value)}")
        QMessageBox.information(self, "Score breakdown", "\n".join(lines))
        self.set_status(f"Score breakdown shown: soft penalty {total}")

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
            return (
                f"A{a_id}{course_code} "
                f"(W{int(info['week'])} {info['day']} S{int(info['slot']) + 1})"
            )
        return f"A{a_id}"

    def _clone_schedule(
        self, schedule: Dict[int, Dict[str, Any]] | None = None
    ) -> Dict[int, Dict[str, Any]]:
        source = self.current_schedule if schedule is None else schedule
        return {a_id: info.copy() for a_id, info in source.items()}

    def _invalidate_held_analysis_cache(self) -> None:
        self._held_analysis_cache_key = None
        self._held_analysis_cache_value = {}

    def _bump_schedule_revision(self) -> None:
        self._schedule_revision = int(self._schedule_revision) + 1
        self._invalidate_held_analysis_cache()
        self._conflict_ids_cache_revision = -1
        self._conflict_ids_cache = set()

    def _schedule_cache_token(
        self, schedule: Dict[int, Dict[str, Any]]
    ) -> Tuple[str, Any]:
        if schedule is self.current_schedule:
            return ("current", int(self._schedule_revision))
        return ("override", id(schedule))

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
            if (
                self._soft_penalty_improver is None
                or self._soft_penalty_improver_inst_ref is not self.inst
            ):
                self._soft_penalty_improver = LocalSearchImprover(self.inst)
                self._soft_penalty_improver_inst_ref = self.inst
            return int(self._soft_penalty_improver.compute_soft_penalty(schedule))
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

    def _show_improvement_delta_report(
        self,
        before_schedule: Dict[int, Dict[str, Any]],
        after_schedule: Dict[int, Dict[str, Any]],
        *,
        title: str = "Improvement report",
    ) -> None:
        if self.inst is None:
            return
        try:
            before = compute_penalty_breakdown(self.inst, before_schedule)
            after = compute_penalty_breakdown(self.inst, after_schedule)
        except Exception:
            return
        rows: List[Tuple[str, int, int, int]] = []
        for term in sorted(set(before.keys()) | set(after.keys())):
            if term == "total":
                continue
            b = int(before.get(term, 0))
            a = int(after.get(term, 0))
            if b != a:
                rows.append((str(term), b, a, int(a - b)))
        rows.sort(key=lambda row: (row[3], row[0]))
        moved = sum(
            1
            for a_id, info in after_schedule.items()
            if dict(before_schedule.get(int(a_id), {})) != dict(info)
        )
        lines = [
            f"Global soft penalty: {int(before.get('total', 0))} -> {int(after.get('total', 0))}",
            f"Delta: {int(after.get('total', 0)) - int(before.get('total', 0)):+d}",
            f"Moved activities: {int(moved)}",
            "",
            "Changed penalty terms:",
        ]
        if rows:
            for term, b, a, delta in rows[:12]:
                lines.append(f"- {term}: {b} -> {a} ({delta:+d})")
        else:
            lines.append("- No modeled soft-penalty terms changed.")
        QMessageBox.information(self, str(title), "\n".join(lines))

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

    def _sync_instance_activity_weeks_from_schedule(
        self, schedule: Dict[int, Dict[str, Any]]
    ) -> None:
        if self.inst is None:
            return
        for a_id, info in schedule.items():
            act = self.inst.activities.get(int(a_id))
            if act is None:
                continue
            try:
                act.week = int(info.get("week", act.week))
            except Exception:
                continue

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

    def _selected_activity_ids_from_table_selection(self) -> List[int]:
        if self.inst is None:
            return []
        out: List[int] = []
        seen: Set[int] = set()
        for item in self.table.selectedItems():
            row = int(item.row())
            col = int(item.column())
            for a_id in self._cell_activity_map.get((row, col), []):
                if int(a_id) in seen:
                    continue
                seen.add(int(a_id))
                out.append(int(a_id))
        return out

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
        self._invalidate_held_analysis_cache()
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
        self._invalidate_held_analysis_cache()
        self.update_table()
        self._refresh_quick_actions()
        self.set_status(f"Released held activity A{held}")

    def _collect_held_target_map(
        self,
        week: int,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
    ) -> Dict[Tuple[str, int], bool]:
        analysis_map = self._build_held_move_analysis(
            week,
            schedule_override=schedule_override,
            compute_scores=False,
            include_conflicts=False,
        )
        return {
            key: bool(info.get("ok", False)) for key, info in analysis_map.items()
        }

    def _build_held_move_analysis(
        self,
        week: int,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
        *,
        compute_scores: bool = True,
        include_conflicts: bool = True,
    ) -> Dict[Tuple[str, int], Dict[str, Any]]:
        inst = self.inst
        if inst is None or self.held_activity_id is None:
            return {}
        schedule = self.current_schedule if schedule_override is None else schedule_override
        a_id = int(self.held_activity_id)
        info = schedule.get(a_id)
        if info is None:
            return {}
        origin_week = int(info["week"])
        current_day = str(info["day"])
        current_slot = int(info["slot"])
        room_id = int(info["room_id"])
        staff_id = int(info["staff_id"])
        cache_key = (
            self._schedule_cache_token(schedule),
            int(a_id),
            int(week),
            int(origin_week),
            str(current_day),
            int(current_slot),
            int(room_id),
            int(staff_id),
            int(bool(compute_scores)),
            int(bool(include_conflicts)),
        )
        if self._held_analysis_cache_key == cache_key:
            return self._held_analysis_cache_value
        analysis = self._compute_held_move_analysis_snapshot(
            week,
            schedule_override=schedule,
            compute_scores=compute_scores,
            include_conflicts=include_conflicts,
        )
        self._held_analysis_cache_key = cache_key
        self._held_analysis_cache_value = analysis
        return analysis

    def _compute_held_move_analysis_snapshot(
        self,
        week: int,
        *,
        schedule_override: Dict[int, Dict[str, Any]],
        compute_scores: bool,
        include_conflicts: bool,
    ) -> Dict[Tuple[str, int], Dict[str, Any]]:
        inst = self.inst
        if inst is None or self.held_activity_id is None:
            return {}
        schedule = schedule_override
        a_id = int(self.held_activity_id)
        info = schedule.get(a_id)
        if info is None:
            return {}
        origin_week = int(info["week"])
        current_day = str(info["day"])
        current_slot = int(info["slot"])
        room_id = int(info["room_id"])
        staff_id = int(info["staff_id"])
        base_penalty = self._compute_soft_penalty(schedule) if compute_scores else None
        analysis: Dict[Tuple[str, int], Dict[str, Any]] = {}
        for day in inst.days:
            for slot in range(inst.slots_per_day):
                ok, reason = self.check_move(
                    a_id,
                    str(day),
                    int(slot),
                    room_id,
                    staff_id,
                    int(week),
                    schedule_override=schedule,
                )
                day_slot = (str(day), int(slot))
                details: Dict[str, Any] = {
                    "ok": bool(ok),
                    "reason": "",
                    "conflicts": [] if include_conflicts else None,
                    "score_current": base_penalty,
                    "score_after": None,
                    "score_delta": None,
                }
                if ok:
                    if compute_scores and base_penalty is not None:
                        if (
                            int(week) == int(origin_week)
                            and str(day) == current_day
                            and int(slot) == current_slot
                        ):
                            target_penalty = int(base_penalty)
                        else:
                            moved = self._clone_schedule(schedule)
                            moved[a_id]["week"] = int(week)
                            moved[a_id]["day"] = str(day)
                            moved[a_id]["slot"] = int(slot)
                            target_penalty = self._compute_soft_penalty(moved)
                        if target_penalty is not None:
                            details["score_after"] = int(target_penalty)
                            details["score_delta"] = int(target_penalty) - int(base_penalty)
                    analysis[day_slot] = details
                    continue
                details["reason"] = str(reason or "")
                if include_conflicts:
                    details["conflicts"] = self._find_move_conflicts(
                        a_id,
                        str(day),
                        int(slot),
                        room_id,
                        staff_id,
                        int(week),
                        schedule_override=schedule,
                    )
                analysis[day_slot] = details
        return analysis

    def _request_held_move_analysis_async(
        self,
        week: int,
        *,
        compute_scores: bool,
        include_conflicts: bool,
    ) -> None:
        if self.inst is None or self.held_activity_id is None:
            return
        schedule_snapshot = self._clone_schedule()
        a_id = int(self.held_activity_id)
        info = schedule_snapshot.get(a_id)
        if info is None:
            return
        key = (
            self._schedule_cache_token(schedule_snapshot),
            int(a_id),
            int(week),
            int(info["week"]),
            str(info["day"]),
            int(info["slot"]),
            int(info["room_id"]),
            int(info["staff_id"]),
            int(bool(compute_scores)),
            int(bool(include_conflicts)),
        )
        if self._held_analysis_async_key == key or self._held_analysis_cache_key == key:
            return
        self._held_analysis_async_key = key
        worker = FunctionWorker(
            self._compute_held_move_analysis_snapshot,
            int(week),
            schedule_override=schedule_snapshot,
            compute_scores=bool(compute_scores),
            include_conflicts=bool(include_conflicts),
        )

        def _on_done(result: object) -> None:
            if self._held_analysis_async_key != key:
                return
            if isinstance(result, dict):
                self._held_analysis_cache_key = key
                self._held_analysis_cache_value = {
                    (str(day), int(slot)): dict(details)
                    for (day, slot), details in result.items()
                }
                self._held_move_analysis_map = self._held_analysis_cache_value
                self._held_analysis_async_key = None
                self.update_table()

        def _on_error(_message: str) -> None:
            if self._held_analysis_async_key == key:
                self._held_analysis_async_key = None

        worker.signals.finished.connect(_on_done)
        worker.signals.error.connect(_on_error)
        self._thread_pool.start(worker)

    def _held_move_analysis_from_cache(
        self,
        week: int,
        *,
        compute_scores: bool,
        include_conflicts: bool,
    ) -> Dict[Tuple[str, int], Dict[str, Any]]:
        if self.inst is None or self.held_activity_id is None:
            return {}
        schedule = self.current_schedule
        a_id = int(self.held_activity_id)
        info = schedule.get(a_id)
        if info is None:
            return {}
        key = (
            self._schedule_cache_token(schedule),
            int(a_id),
            int(week),
            int(info["week"]),
            str(info["day"]),
            int(info["slot"]),
            int(info["room_id"]),
            int(info["staff_id"]),
            int(bool(compute_scores)),
            int(bool(include_conflicts)),
        )
        if self._held_analysis_cache_key == key:
            return dict(self._held_analysis_cache_value or {})
        return {}

    def _ensure_held_analysis_conflicts(
        self,
        *,
        day: str,
        slot: int,
        week: int,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
    ) -> List[Dict[str, Any]]:
        analysis = self._held_move_analysis_map.get((str(day), int(slot)))
        if analysis is None or bool(analysis.get("ok", False)):
            return []
        existing = analysis.get("conflicts")
        if isinstance(existing, list):
            return existing
        if self.held_activity_id is None:
            return []
        schedule = self.current_schedule if schedule_override is None else schedule_override
        info = schedule.get(int(self.held_activity_id))
        if info is None:
            return []
        conflicts = self._find_move_conflicts(
            int(self.held_activity_id),
            str(day),
            int(slot),
            int(info["room_id"]),
            int(info["staff_id"]),
            int(week),
            schedule_override=schedule,
        )
        analysis["conflicts"] = list(conflicts)
        return conflicts

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
                note = ""
                info = self.current_schedule.get(int(a_id), {})
                raw_note = str(info.get("admin_note", "") or "").strip()
                if raw_note:
                    note = f" | note: {raw_note}"
                lines.append(f"  - {self._activity_title(int(a_id))}{note}")
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
                        conflicts = analysis.get("conflicts")
                        if not isinstance(conflicts, list):
                            conflicts = self._ensure_held_analysis_conflicts(
                                day=str(day),
                                slot=int(col),
                                week=int(week),
                            )
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
        target_week: int | None = None,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
    ) -> List[Dict[str, Any]]:
        schedule = self.current_schedule if schedule_override is None else schedule_override
        info = schedule.get(a_id)
        if info is None:
            return []
        week = int(info["week"]) if target_week is None else int(target_week)
        dur = int(info["duration"])
        groups = set(int(g) for g in info["group_ids"])
        target_slots = set(range(int(new_slot), int(new_slot) + dur))
        conflicts: List[Dict[str, Any]] = []
        for b_id, other in schedule.items():
            if int(b_id) == int(a_id):
                continue
            if int(other["week"]) != int(week) or str(other["day"]) != str(new_day):
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
        week: int | None = None,
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
        target_week = int(info["week"]) if week is None else int(week)
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
                    target_week,
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
        if self._active_branch_name and self._active_branch_name in self._branches:
            self._branches[self._active_branch_name] = update_branch(
                self._branches[self._active_branch_name], self.current_schedule
            )
        self._bump_schedule_revision()
        self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
        self._sync_instance_staff_from_schedule(self.current_schedule)
        self._sync_locks_to_instance()
        self.update_table()
        self.update_quality_summary()
        self.set_status(status + self._format_score_status_suffix(before_penalty, after_penalty))
        self._refresh_history_buttons()
        self._append_audit_log(
            "schedule_commit",
            {
                "status": str(status),
                "before_soft_penalty": before_penalty,
                "after_soft_penalty": after_penalty,
                "activities": int(len(self.current_schedule)),
            },
        )
        self._save_persistent_history()

    def _attempt_swap_timeslots(self, a_id: int, b_id: int) -> Tuple[bool, str]:
        if a_id not in self.current_schedule or b_id not in self.current_schedule:
            return False, "Activity not found in schedule."
        schedule = self._clone_schedule()
        a = schedule[a_id]
        b = schedule[b_id]
        a_week, a_day, a_slot = int(a["week"]), str(a["day"]), int(a["slot"])
        b_week, b_day, b_slot = int(b["week"]), str(b["day"]), int(b["slot"])
        a["week"], a["day"], a["slot"] = b_week, b_day, b_slot
        b["week"], b["day"], b["slot"] = a_week, a_day, a_slot

        ok_a, reason_a = self.check_move(
            int(a_id),
            str(a["day"]),
            int(a["slot"]),
            int(a["room_id"]),
            int(a["staff_id"]),
            int(a["week"]),
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
            int(b["week"]),
            schedule_override=schedule,
        )
        if not ok_b:
            return False, f"Swap invalid for A{b_id}: {reason_b}"
        errors = self._validate_schedule_hard_errors(schedule, require_all=True)
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
        errors = self._validate_schedule_hard_errors(schedule, require_all=True)
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
        target_week: int,
        target_day: str,
        target_slot: int,
        schedule: Dict[int, Dict[str, Any]],
        *,
        forced: bool = False,
    ) -> None:
        errors = self._validate_schedule_hard_errors(schedule, require_all=True)

        self._push_undo_state()
        self._touch_time_lock_if_present(held_id, str(target_day), int(target_slot))
        title = self._activity_title(held_id, schedule)
        status = f"Moved {title} to week {int(target_week)}"
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
        target_week: int,
    ) -> None:
        info = self.current_schedule.get(int(held_id))
        if info is None or self.inst is None:
            return

        origin_week = int(info["week"])
        origin_day = str(info["day"])
        origin_slot = int(info["slot"])
        room_id = int(info["room_id"])
        staff_id = int(info["staff_id"])

        planned = self._clone_schedule()
        planned[held_id]["week"] = int(target_week)
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
                int(target_week),
                schedule_override=planned,
            )
            if not conflicts:
                self._commit_held_plan_move(
                    held_id,
                    int(target_week),
                    str(target_day),
                    int(target_slot),
                    planned,
                    forced=False,
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
                approval = self._require_approval(
                    action="force_move_with_conflicts",
                    details={
                        "held_activity_id": int(held_id),
                        "target_week": int(target_week),
                        "target_day": str(target_day),
                        "target_slot": int(target_slot),
                        "conflict_count": int(len(conflicts)),
                    },
                )
                if approval is None:
                    step_note = "Force move canceled: approval not granted."
                    continue
                planned[held_id]["override_approval"] = dict(approval)
                self._commit_held_plan_move(
                    held_id,
                    int(target_week),
                    str(target_day),
                    int(target_slot),
                    planned,
                    forced=True,
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
                prev_week = int(b_info["week"])
                b_info["week"] = int(origin_week)
                b_info["day"] = str(origin_day)
                b_info["slot"] = int(origin_slot)
                ok_b, reason_b = self.check_move(
                    int(b_id),
                    str(b_info["day"]),
                    int(b_info["slot"]),
                    int(b_info["room_id"]),
                    int(b_info["staff_id"]),
                    int(origin_week),
                    schedule_override=planned,
                )
                if not ok_b:
                    b_info["week"] = prev_week
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
                prev_week = int(b_info["week"])
                b_info["day"] = str(b_day)
                b_info["slot"] = int(b_slot)
                ok_b, reason_b = self.check_move(
                    int(b_id),
                    str(b_day),
                    int(b_slot),
                    int(b_info["room_id"]),
                    int(b_info["staff_id"]),
                    int(prev_week),
                    schedule_override=planned,
                )
                if not ok_b:
                    b_info["week"] = prev_week
                    b_info["day"] = prev_day
                    b_info["slot"] = prev_slot
                    step_note = f"Relocation blocked for A{b_id}: {reason_b}"
                else:
                    step_note = f"Relocated conflict A{b_id} to {b_day} S{b_slot + 1}."
                continue

            step_note = f"Unknown action: {kind}"

    def _attempt_move_held_to(
        self, target_day: str, target_slot: int, target_week: int | None = None
    ) -> None:
        if self.inst is None or self.held_activity_id is None:
            return
        held_id = int(self.held_activity_id)
        if held_id not in self.current_schedule:
            self._clear_held_activity()
            return
        info = self.current_schedule[held_id]
        move_week = int(info["week"]) if target_week is None else int(target_week)
        room_id = int(info["room_id"])
        staff_id = int(info["staff_id"])
        cached_analysis = None
        current_week = self._current_week()
        if current_week is not None and int(current_week) == int(move_week):
            cached_analysis = self._held_move_analysis_map.get(
                (str(target_day), int(target_slot))
            )
        if isinstance(cached_analysis, dict):
            ok = bool(cached_analysis.get("ok", False))
            reason = str(cached_analysis.get("reason") or "")
        else:
            ok, reason = self.check_move(
                held_id,
                str(target_day),
                int(target_slot),
                room_id,
                staff_id,
                move_week,
            )
        if ok:
            schedule = self._clone_schedule()
            schedule[held_id]["week"] = int(move_week)
            schedule[held_id]["day"] = str(target_day)
            schedule[held_id]["slot"] = int(target_slot)
            self._push_undo_state()
            self._touch_time_lock_if_present(held_id, str(target_day), int(target_slot))
            self._commit_schedule(
                schedule,
                f"Moved {self._activity_title(held_id, schedule)}",
            )
            return

        conflicts = []
        if isinstance(cached_analysis, dict):
            conflicts = cached_analysis.get("conflicts")
            if not isinstance(conflicts, list):
                conflicts = self._ensure_held_analysis_conflicts(
                    day=str(target_day),
                    slot=int(target_slot),
                    week=int(move_week),
                )
        else:
            conflicts = self._find_move_conflicts(
                held_id,
                str(target_day),
                int(target_slot),
                room_id,
                staff_id,
                int(move_week),
            )
        if not conflicts:
            explanation = build_move_explanation_text(
                activity_id=int(held_id),
                target_week=int(move_week),
                target_day=str(target_day),
                target_slot=int(target_slot),
                valid=False,
                reason=str(reason),
                conflicts=[],
            )
            QMessageBox.warning(self, "Move blocked", explanation)
            return

        self._resolve_held_move_conflicts(
            held_id, str(target_day), int(target_slot), int(move_week)
        )

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
                self._attempt_move_held_to(str(day), int(col), int(week))
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
            raw_status = attempt.get("raw_status", attempt.get("status", "?"))
            elapsed = attempt.get("elapsed_seconds")
            elapsed_txt = ""
            if elapsed not in (None, ""):
                try:
                    elapsed_txt = f", elapsed={float(elapsed):.2f}s"
                except Exception:
                    elapsed_txt = f", elapsed={elapsed}s"
            workers = attempt.get("workers")
            workers_txt = "" if workers in (None, "") else f", workers={workers}"
            objective_txt = ""
            if attempt.get("objective_value") not in (None, ""):
                try:
                    objective_txt += f", obj={float(attempt.get('objective_value')):.2f}"
                except Exception:
                    objective_txt += f", obj={attempt.get('objective_value')}"
            if attempt.get("best_objective_bound") not in (None, ""):
                try:
                    objective_txt += f", bound={float(attempt.get('best_objective_bound')):.2f}"
                except Exception:
                    objective_txt += f", bound={attempt.get('best_objective_bound')}"
            if attempt.get("relative_gap") not in (None, ""):
                try:
                    objective_txt += f", gap={float(attempt.get('relative_gap')) * 100.0:.2f}%"
                except Exception:
                    objective_txt += f", gap={attempt.get('relative_gap')}"
            lines.append(
                f"Attempt {i}: mode={mode}, objective={objective}, "
                f"limit={limit_txt}s, raw_status={raw_status}{elapsed_txt}{workers_txt}{objective_txt}"
            )
        return lines

    def _cp_bound_summary_from_meta(self, meta: Dict[str, Any] | None = None) -> str:
        meta = self._last_solver_result_meta if meta is None else meta
        if not isinstance(meta, dict):
            return "CP bound: unavailable"
        attempts = meta.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            return "CP bound: unavailable"
        objective_attempts = [
            attempt
            for attempt in attempts
            if isinstance(attempt, dict) and bool(attempt.get("use_objective", False))
        ]
        if not objective_attempts:
            profile = meta.get("objective_profile")
            if isinstance(profile, dict):
                profile = profile.get("id") or profile.get("label")
            profile_txt = f" ({profile})" if profile else ""
            return (
                f"CP gap: unavailable{profile_txt}; ran without CP objective, "
                "so no lower bound was computed"
            )
        attempt = objective_attempts[-1]
        obj = attempt.get("objective_value")
        bound = attempt.get("best_objective_bound")
        gap = attempt.get("relative_gap")
        if obj in (None, "") and bound in (None, ""):
            return "CP bound: unavailable; objective attempt found no bounded solution"
        parts = ["CP bound/gap"]
        if obj not in (None, ""):
            try:
                parts.append(f"obj={float(obj):.2f}")
            except Exception:
                parts.append(f"obj={obj}")
        if bound not in (None, ""):
            try:
                parts.append(f"best>={float(bound):.2f}")
            except Exception:
                parts.append(f"best>={bound}")
        if gap not in (None, ""):
            try:
                parts.append(f"gap={float(gap) * 100.0:.2f}%")
            except Exception:
                parts.append(f"gap={gap}")
        return " ".join(parts)

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
            f"- Room mode: {self._selected_room_mode_label()}",
            f"- Profile: {self.objective_profile_combo.currentText()}",
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
            diagnosis = build_unsat_rule_diagnosis(self.inst)
            if diagnosis:
                lines.extend(["", "Rule diagnosis:"])
                lines.extend(
                    f"- {row['rule_id']}: {row['summary']}"
                    for row in diagnosis[:5]
                )
            else:
                lines.extend(
                    [
                        "",
                        "No specific structural conflict was detected.",
                        "Try increasing Limit, switching Room mode to Fast (Greedy), or disabling Use CP objective.",
                    ]
                )
        return "\n".join(lines)

    def _solver_debug_enabled(self) -> bool:
        if hasattr(self, "debug_diagnostics_cb"):
            try:
                return bool(self.debug_diagnostics_cb.isChecked())
            except Exception:
                pass
        return str(os.getenv("PLANORA_SOLVER_DEBUG", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _format_json_debug(value: Any, *, max_chars: int = 12000) -> str:
        try:
            text = json.dumps(value, indent=2, sort_keys=True, default=str)
        except Exception:
            text = str(value)
        if len(text) > int(max_chars):
            return text[: int(max_chars)] + "\n... truncated ..."
        return text

    def _activity_room_coverage_debug(self, limit: int = 12) -> list[str]:
        if self.inst is None:
            return ["No instance loaded."]
        inst = self.inst
        missing: list[str] = []
        by_kind: Dict[str, int] = {}
        by_kind_missing: Dict[str, int] = {}
        for act in inst.activities.values():
            kind = str(act.kind)
            by_kind[kind] = int(by_kind.get(kind, 0)) + 1
            need = sum(int(inst.groups[g_id].size) for g_id in act.group_ids if g_id in inst.groups)
            eligible = []
            for room in inst.rooms.values():
                if int(room.capacity) < int(need):
                    continue
                if kind == "LEC" and room.room_type == "LECTURE":
                    eligible.append(room.id)
                elif kind == "TUT" and room.room_type in {"TUTORIAL", "LECTURE"}:
                    eligible.append(room.id)
                elif kind == "LAB":
                    tag = str(getattr(act, "requires_specialization", "") or "").strip()
                    if tag:
                        if room.room_type == "SPECIALIZED_LAB" and tag in set(room.specialization_tags or []):
                            eligible.append(room.id)
                    elif room.room_type in {"COMPUTER_LAB", "SPECIALIZED_LAB"}:
                        eligible.append(room.id)
            if not eligible:
                by_kind_missing[kind] = int(by_kind_missing.get(kind, 0)) + 1
                if len(missing) < int(limit):
                    missing.append(
                        f"A{act.id} {kind} C{act.course_id} W{act.week} "
                        f"groups={act.group_ids} need_cap={need} tag={getattr(act, 'requires_specialization', None) or '-'}"
                    )
        lines = [
            "Room eligibility coverage:",
            f"- Activities by kind: {by_kind}",
            f"- Missing eligible rooms by kind: {by_kind_missing or {}}",
        ]
        if missing:
            lines.append("- Missing samples:")
            lines.extend(f"  {row}" for row in missing)
        return lines

    def _instance_pressure_debug(self, limit: int = 8) -> list[str]:
        if self.inst is None:
            return ["No instance loaded."]
        inst = self.inst
        lines: list[str] = [
            "Instance scale:",
            f"- Programs: {len(inst.programs)}",
            f"- Groups: {len(inst.groups)}",
            f"- Courses: {len(inst.courses)}",
            f"- Staff: {len(inst.staff)} "
            f"(profs={sum(1 for s in inst.staff.values() if s.is_prof)}, "
            f"TAs={sum(1 for s in inst.staff.values() if not s.is_prof)})",
            f"- Rooms: {len(inst.rooms)}",
            f"- Activities: {len(inst.activities)}",
            f"- Calendar: {len(inst.weeks)} weeks x {len(inst.days)} days x {inst.slots_per_day} slots/day",
            f"- Locks: {len(getattr(inst, 'locked_activities', {}) or {})}",
        ]

        room_types: Dict[str, int] = {}
        room_max_caps: Dict[str, int] = {}
        for room in inst.rooms.values():
            r_type = str(room.room_type)
            room_types[r_type] = int(room_types.get(r_type, 0)) + 1
            room_max_caps[r_type] = max(int(room_max_caps.get(r_type, 0)), int(room.capacity))
        lines.extend(
            [
                "Room pool:",
                f"- Counts by type: {room_types}",
                f"- Max capacity by type: {room_max_caps}",
            ]
        )

        group_week_loads: list[tuple[int, int, int, str]] = []
        capacity = len(inst.days) * int(inst.slots_per_day)
        for g_id, group in inst.groups.items():
            for week in inst.weeks:
                load = sum(
                    int(act.duration)
                    for act in inst.activities.values()
                    if int(act.week) == int(week) and int(g_id) in {int(x) for x in act.group_ids}
                )
                group_week_loads.append((int(load), int(g_id), int(week), str(group.name)))
        group_week_loads.sort(reverse=True)
        lines.append("Highest group-week loads:")
        for load, g_id, week, name in group_week_loads[: int(limit)]:
            lines.append(f"- G{g_id} {name} week {week}: {load}/{capacity} slots")

        staff_week_loads: Dict[tuple[int, int], int] = {}
        for act in inst.activities.values():
            staff_id = int(act.prof_id if act.kind == "LEC" else act.ta_id)
            key = (staff_id, int(act.week))
            staff_week_loads[key] = int(staff_week_loads.get(key, 0)) + int(act.duration)
        staff_rows = [
            (load, staff_id, week, str(inst.staff.get(staff_id).name if staff_id in inst.staff else staff_id))
            for (staff_id, week), load in staff_week_loads.items()
        ]
        staff_rows.sort(reverse=True)
        lines.append("Highest staff-week loads:")
        for load, staff_id, week, name in staff_rows[: int(limit)]:
            staff = inst.staff.get(staff_id)
            cap = getattr(staff, "max_slots_per_week", None) if staff is not None else None
            cap_txt = "uncapped" if cap is None else str(cap)
            lines.append(f"- S{staff_id} {name} week {week}: {load} slots, cap={cap_txt}")

        return lines

    def _build_solver_debug_report(self, res: Dict[str, Any], status: int) -> str:
        lines: list[str] = [
            self._build_no_feasible_message(res, int(status)),
            "",
            "===== DEBUG DIAGNOSTICS =====",
            "Status legend:",
            "- UI status -1 = no feasible schedule / CP-SAT UNKNOWN",
            "- UI status -2 = greedy rooming/extraction failed",
            "- UI status -3 = strict hard-conflict gate rejected the returned schedule",
            "- CP-SAT raw status: 0 UNKNOWN, 1 MODEL_INVALID, 2 FEASIBLE, 3 INFEASIBLE, 4 OPTIMAL",
            "",
        ]
        lines.extend(self._instance_pressure_debug())
        lines.append("")
        lines.extend(self._activity_room_coverage_debug())

        if self.inst is not None:
            try:
                certificate = build_feasibility_certificate(self.inst)
                scale = dict(certificate.get("scale", {}) or {})
                recommendation = dict(certificate.get("recommendation", {}) or {})
                decomposition = dict(certificate.get("decomposition", {}) or {})
                lines.extend(
                    [
                        "",
                        "Performance certificate:",
                        f"- Estimated start literals: {scale.get('estimated_start_literals', 0)}",
                        f"- Estimated CP room candidates: {scale.get('estimated_cp_room_candidates', 0)}",
                        f"- Estimated conflict edges: {scale.get('estimated_conflict_edges', 0)}",
                        f"- Recommended profile: {recommendation.get('profile', '?')} "
                        f"(room_mode={recommendation.get('room_mode', '?')}, "
                        f"objective_profile={recommendation.get('objective_profile', '?')})",
                        f"- Reason: {recommendation.get('reason', '')}",
                    ]
                )
                smallest = list(scale.get("smallest_domains", []) or [])[:6]
                if smallest:
                    lines.append("- Smallest activity domains:")
                    lines.extend(
                        f"  A{row.get('activity_id')} {row.get('kind')} W{row.get('week')}: "
                        f"starts={row.get('start_domain')}, rooms={row.get('room_domain')}"
                        for row in smallest
                    )
                week_blocks = list(decomposition.get("week_blocks", []) or [])[:6]
                if week_blocks:
                    lines.append("- Week decomposition samples:")
                    lines.extend(
                        f"  W{row.get('week')}: activities={row.get('activities')}, "
                        f"staff={row.get('staff')}, groups={row.get('groups')}"
                        for row in week_blocks
                    )
            except Exception as exc:
                lines.extend(["", f"Performance certificate unavailable: {exc}"])

            reasons = explain_infeasibility(self.inst, max_per_category=20)
            lines.extend(["", "Expanded structural checks:"])
            if reasons:
                lines.extend(f"- {row}" for row in reasons[:40])
            else:
                lines.append("- No structural issue found by heuristic checks.")

            diagnosis = build_unsat_rule_diagnosis(self.inst)
            lines.extend(["", "Expanded rule diagnosis:"])
            if diagnosis:
                for row in diagnosis[:20]:
                    lines.append(
                        f"- {row.get('rule_id', '?')}: {row.get('summary', '')}"
                    )
            else:
                lines.append("- No rule-level diagnosis rows returned.")

        meta = res.get("meta") if isinstance(res, dict) else {}
        lines.extend(["", "Raw result metadata:", self._format_json_debug(meta)])

        output = str(getattr(self, "_last_solver_output_log", "") or "")
        if output:
            tail = output[-16000:]
            lines.extend(["", "Solver output tail:", tail])
        else:
            lines.extend(["", "Solver output tail:", "(empty)"])

        return "\n".join(lines)

    def _show_solver_report_dialog(self, title: str, text: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(str(title))
        dlg.resize(980, 720)
        layout = QVBoxLayout(dlg)
        editor = QPlainTextEdit(dlg)
        editor.setReadOnly(True)
        editor.setPlainText(str(text))
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(editor)
        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = QPushButton("Close", dlg)
        close_btn.clicked.connect(dlg.accept)
        row.addWidget(close_btn)
        layout.addLayout(row)
        dlg.exec()

    @staticmethod
    def _top_counts(values: Dict[int, int], limit: int = 3) -> list[tuple[int, int]]:
        items = [(int(k), int(v)) for k, v in values.items()]
        items.sort(key=lambda kv: (-kv[1], kv[0]))
        return items[:limit]

    def _require_approval(
        self,
        *,
        action: str,
        details: Dict[str, Any] | None = None,
    ) -> Dict[str, Any] | None:
        dlg = ApprovalDialog(self, action=str(action), actor=str(self._operator_name))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        actor, reason = dlg.values()
        record = build_approval_record(
            action=str(action),
            actor=str(actor or self._operator_name),
            reason=str(reason),
            details=dict(details or {}),
        )
        self._operator_name = str(record.actor)
        self._append_audit_log("override_approved", approval_to_dict(record))
        self._save_persistent_history()
        return approval_to_dict(record)

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

    def _current_solve_options(self) -> SolveOptions:
        time_limit_seconds = float(self.time_limit_spin.value())
        objective_on = bool(self.objective_cb.isChecked())
        return SolveOptions(
            room_mode=self._selected_room_mode(),
            use_objective=bool(objective_on),
            retry_without_objective=True,
            objective_profile=str(self.objective_profile_combo.currentData() or "balanced"),
            time_limit_seconds=float(time_limit_seconds),
            strict_limit_seconds=min(float(time_limit_seconds), 300.0),
            workers=int(self._selected_worker_count()),
            random_seed=int(self.random_seed_spin.value()),
            phased_solve=bool(objective_on),
            feasibility_seconds=None,
            improve_total_seconds=0.0,
            enforce_hard_conflict_free=True,
        )

    # ----- actions -----

    def on_generate(self):
        if self.proc is not None:
            QMessageBox.warning(self, "Busy", "Wait for solving to finish first.")
            return

        mode = self.mode_combo.currentText()
        try:
            self.product_scenario = self._build_product_scenario_from_controls(str(mode))
            inst = compile_scenario_instance(self.product_scenario)
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
        self._last_solver_result_meta = {}
        self.locked_activities = {}
        self.held_activity_id = None
        self._bump_schedule_revision()
        self._reset_history()
        self.set_status(f"Instance generated ({mode})")
        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self._load_constraint_controls_from_instance(self.inst)
        self._append_audit_log(
            "generate_instance",
            {"mode": str(mode), "activities": int(len(self.inst.activities))},
        )
        self._save_persistent_history()

    def on_portfolio_solve_report(self) -> None:
        if self.inst is None:
            self.set_status("Generate or load an instance first")
            return
        if self.proc is not None:
            QMessageBox.warning(self, "Busy", "Wait for solving to finish first.")
            return
        try:
            self._apply_constraint_settings(self.inst)
            self.set_busy(True)
            self.set_status("Running portfolio solve comparison...")
            QApplication.processEvents()
            portfolio = self.backend_client.solve_portfolio(
                self.inst, self._current_solve_options()
            )
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Portfolio error", str(exc))
            self.set_status("Portfolio solve error")
            return
        finally:
            self.set_busy(False)

        lines: List[str] = ["Portfolio candidates:"]
        for idx, candidate in enumerate(portfolio.candidates, start=1):
            result = candidate.result
            feasibility = "feasible" if result.is_feasible else f"status {result.status}"
            penalty = (
                str(int(candidate.soft_penalty))
                if candidate.soft_penalty is not None
                else "n/a"
            )
            lines.append(
                f"{idx}. {candidate.name}: {feasibility}, penalty={penalty}, attempts={len(result.attempts)}"
            )
            if candidate.rank_explanation:
                lines.append(f"   {candidate.rank_explanation}")

        best = portfolio.best
        if best is None or not best.result.schedule:
            QMessageBox.information(
                self,
                "Portfolio solve report",
                "\n".join(lines),
            )
            self.set_status("Portfolio solve completed with no feasible candidate")
            return

        choice = QMessageBox.question(
            self,
            "Portfolio solve report",
            "\n".join(lines)
            + "\n\nApply the best candidate to the workspace?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        self.set_status(
            f"Portfolio best: {best.name} "
            f"(penalty {int(best.soft_penalty or 0)})"
        )
        if choice != QMessageBox.StandardButton.Yes:
            return

        self.base_schedule = {
            int(a_id): dict(info) for a_id, info in best.result.schedule.items()
        }
        self.current_schedule = {
            int(a_id): dict(info) for a_id, info in best.result.schedule.items()
        }
        self._set_manual_highlight_base(self.current_schedule)
        self.held_activity_id = None
        self._bump_schedule_revision()
        self._reset_history()
        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self._append_audit_log(
            "portfolio_solve_applied",
            {
                "profile": str(best.name),
                "penalty": int(best.soft_penalty or 0),
            },
        )

    def _cleanup_solver_temp_files(self) -> None:
        for path in (self.tmp_inst_path, self.tmp_res_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        self.tmp_inst_path = None
        self.tmp_res_path = None

    @staticmethod
    def _is_access_violation_exit_code(exit_code: int) -> bool:
        return int(exit_code) in {-1073741819, 3221225477}

    @staticmethod
    def _is_solver_process_crash_error(error: Any) -> bool:
        try:
            if int(error) == int(QProcess.ProcessError.Crashed):
                return True
        except Exception:
            pass
        name = str(getattr(error, "name", "") or "").lower()
        return "crash" in name

    def _retry_solver_once_in_safe_mode(self, *, reason: str, detail: Dict[str, Any]) -> bool:
        if not getattr(sys, "frozen", False):
            return False
        if self._solver_safe_retry_used:
            return False
        self._solver_safe_retry_used = True
        payload: Dict[str, Any] = {"reason": str(reason)}
        payload.update({str(k): v for k, v in detail.items()})
        self._append_audit_log("solve_crash_safe_retry", payload)
        self._cleanup_solver_temp_files()
        self.set_status(
            "Solver worker crashed (native dependency). Retrying once in safe mode..."
        )
        self._start_solver_process(
            keep_locks=bool(self._last_solver_keep_locks),
            retry_safe=True,
        )
        return True

    def _start_solver_process(self, *, keep_locks: bool, retry_safe: bool = False) -> None:
        if self.inst is None:
            self.set_status("Generate instance first")
            return
        if self.proc is not None:
            QMessageBox.warning(self, "Busy", "Solver already running.")
            return
        if not retry_safe:
            self._solver_safe_retry_used = False
        self._last_solver_keep_locks = bool(keep_locks)

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
            # In packaged mode, prefer a dedicated worker executable to avoid
            # self-spawn edge-cases with native solver dependencies.
            exe_dir = os.path.dirname(sys.executable)
            worker_exe = os.path.join(exe_dir, "SchedulerEngine.exe")
            if os.path.exists(worker_exe):
                self.proc.setProgram(worker_exe)
                self.proc.setArguments([self.tmp_inst_path, self.tmp_res_path])
            else:
                self.proc.setProgram(sys.executable)
                self.proc.setArguments(
                    ["--engine-cli", self.tmp_inst_path, self.tmp_res_path]
                )
            try:
                self.proc.setWorkingDirectory(exe_dir)
            except Exception:
                pass
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
        objective_profile = str(
            self.objective_profile_combo.currentData() or "balanced"
        )
        objective_on = self.objective_cb.isChecked()
        room_mode = self._selected_room_mode()
        if objective_profile in {"fast_feasible", "university_fast"}:
            objective_on = False
            if objective_profile == "university_fast":
                room_mode = "greedy"
        elif objective_profile == "university_quality":
            objective_on = True
            room_mode = "greedy"
        elif objective_profile == "verification":
            objective_on = True
            room_mode = "cp_rooms"
        elif objective_profile == "quality_first":
            objective_on = True
        worker_count = int(self._selected_worker_count())
        if retry_safe:
            objective_on = False
            room_mode = "greedy"
            worker_count = 1
            objective_profile = "fast_feasible"
        env_map["TT_ROOM_MODE"] = room_mode
        env_map["TT_TIME_LIMIT"] = str(self.time_limit_spin.value())
        env_map["TT_CP_WORKERS"] = str(int(worker_count))
        env_map["TT_RANDOM_SEED"] = str(int(self.random_seed_spin.value()))
        env_map["TT_USE_OBJECTIVE"] = "1" if objective_on else "0"
        env_map["TT_OBJECTIVE_PROFILE"] = str(objective_profile)
        if self._solver_debug_enabled():
            env_map["TT_CP_LOG"] = "1"
            env_map["PLANORA_SOLVER_DEBUG"] = "1"
        phased_enabled = bool(objective_on)
        feasibility_seconds = float(time_limit_seconds)
        improve_budget_seconds = 0.0
        improve_max_rounds = 0
        if objective_profile == "quality_first":
            feasibility_seconds = min(
                float(time_limit_seconds),
                max(1.0, float(time_limit_seconds) * 0.65),
            )
            improve_budget_seconds = max(
                0.0,
                float(time_limit_seconds) - float(feasibility_seconds),
            )
            env_map["TT_PHASED_SOLVE"] = "1"
            env_map["TT_FEASIBILITY_SECONDS"] = f"{feasibility_seconds:g}"
            env_map["TT_IMPROVE_TOTAL_SECONDS"] = f"{improve_budget_seconds:g}"
            env_map["TT_IMPROVE_SLICE_SECONDS"] = "6"
            env_map["TT_IMPROVE_ITERS_PER_SLICE"] = "1500"
            env_map["TT_IMPROVE_MAX_ROUNDS"] = "16"
            improve_max_rounds = 16
            phased_enabled = True
        elif objective_on:
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
        if getattr(sys, "frozen", False):
            bundle_dir = str(getattr(sys, "_MEIPASS", "") or "")
            exe_dir = os.path.dirname(sys.executable)
            path_parts = [p for p in [bundle_dir, exe_dir, env_map.get("PATH", "")] if p]
            env_map["PATH"] = os.pathsep.join(path_parts)
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
            "objective_profile": str(objective_profile),
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
        self._last_solver_output_log = ""

        self.set_busy(True)
        lock_count = len(self.locked_activities)
        mode_hint = " [safe retry]" if retry_safe else ""
        self.set_status(
            "Solving in external process..."
            + mode_hint
            + (f" (locks={lock_count})" if lock_count else "")
        )
        self._start_solve_progress()
        self.proc.start()

    def on_solve(self):
        self._restore_locks_after_solve = None
        self._append_audit_log("solve_started", {"keep_locks": False})
        self._start_solver_process(keep_locks=False)

    def on_show_audit_log_path(self) -> None:
        QMessageBox.information(
            self,
            "Audit log",
            f"Audit log file:\n{self._audit_log_path}",
        )
        self.set_status(f"Audit log: {self._audit_log_path}")

    def on_show_change_history(self) -> None:
        rows = list(reversed(self._workspace_change_log))
        if not rows:
            QMessageBox.information(
                self,
                "Workspace Change History",
                "No workspace change history has been recorded yet.",
            )
            return
        dlg = ChangeHistoryDialog(self, rows)
        dlg.exec()
        self.set_status("Viewed workspace change history")

    def on_show_about(self) -> None:
        QMessageBox.information(
            self,
            f"About {self._effective_branding().get('short_name', APP_SHORT_NAME)}",
            "\n".join(about_lines(self._effective_branding())),
        )
        self.set_status(f"About {self._effective_branding().get('short_name', APP_SHORT_NAME)}")

    def on_check_updates(self) -> None:
        manifest_source = str(
            self._runtime_settings.get("update_manifest_path")
            or _resource_path("docs", "portal", "update_manifest.json")
        )
        if not os.path.isabs(manifest_source) and not manifest_source.startswith(("http://", "https://")):
            manifest_source = _resource_path(manifest_source)
        try:
            result = check_for_updates(
                current_version=str(APP_VERSION),
                manifest_source=manifest_source,
                channel=str(self._runtime_settings.get("update_channel", "stable") or "stable"),
            )
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Update check error", str(exc))
            return
        status = (
            f"Update available: {result['latest_version']}"
            if bool(result.get("available", False))
            else f"Up to date ({result['current_version']})"
        )
        msg = [
            f"Channel: {result.get('channel', 'stable')}",
            f"Current: {result.get('current_version', APP_VERSION)}",
            f"Latest: {result.get('latest_version', APP_VERSION)}",
            f"Download: {result.get('download_url', '') or 'n/a'}",
            f"Notes: {result.get('notes', '') or 'No release notes provided.'}",
        ]
        QMessageBox.information(self, "Update Channel", "\n".join(msg))
        self._append_audit_log("update_channel_checked", dict(result))
        self.set_status(status)

    def on_set_update_channel(self) -> None:
        choice, ok = QInputDialog.getItem(
            self,
            "Update Channel",
            "Channel:",
            ["stable", "preview"],
            0 if str(self._runtime_settings.get("update_channel", "stable")) == "stable" else 1,
            False,
        )
        if not ok:
            return
        self._runtime_settings["update_channel"] = str(choice)
        save_runtime_settings(self._runtime_paths["settings"], self._runtime_settings)
        self._append_audit_log("update_channel_set", {"channel": str(choice)})
        self.set_status(f"Update channel set to {choice}")

    def on_toggle_crash_reports_opt_in(self) -> None:
        current = bool(self._runtime_settings.get("crash_reports_opt_in", False))
        self._runtime_settings["crash_reports_opt_in"] = not current
        save_runtime_settings(self._runtime_paths["settings"], self._runtime_settings)
        state = "enabled" if self._runtime_settings["crash_reports_opt_in"] else "disabled"
        self._append_audit_log("crash_reporting_toggled", {"state": state})
        self.set_status(f"Crash reports {state}")

    def on_toggle_telemetry_opt_in(self) -> None:
        current = bool(self._runtime_settings.get("telemetry_opt_in", False))
        self._runtime_settings["telemetry_opt_in"] = not current
        save_runtime_settings(self._runtime_paths["settings"], self._runtime_settings)
        state = "enabled" if self._runtime_settings["telemetry_opt_in"] else "disabled"
        self._append_audit_log("telemetry_toggled", {"state": state})
        self.set_status(f"Telemetry {state}")

    def on_show_runtime_log_folder(self) -> None:
        folder = str(self._runtime_paths.get("root", os.path.expanduser("~")))
        QMessageBox.information(
            self,
            "Runtime Logs",
            f"Runtime state folder:\n{folder}",
        )
        self.set_status(f"Runtime folder: {folder}")

    def on_export_support_bundle(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export support bundle",
            "planora_support_bundle.zip",
            "ZIP (*.zip)",
        )
        if not path:
            return
        extra_files: Dict[str, str] = {}
        if self.inst is not None:
            extra_files["workspace/current_schedule.json"] = json.dumps(
                self.current_schedule,
                indent=2,
                sort_keys=True,
            )
            extra_files["workspace/meta.json"] = json.dumps(
                self._workspace_meta(),
                indent=2,
                sort_keys=True,
            )
        try:
            bundle = collect_support_bundle(
                path,
                runtime_paths=self._runtime_paths,
                settings=self._runtime_settings,
                metadata={"window_title": self.windowTitle()},
                extra_files=extra_files,
            )
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Support bundle error", str(exc))
            return
        self._append_audit_log("support_bundle_exported", {"path": str(bundle)})
        self.set_status(f"Support bundle exported to {bundle}")

    def on_export_quality_report(self) -> None:
        if self.inst is None or not self.current_schedule:
            self.set_status("No schedule to report")
            return
        folder = QFileDialog.getExistingDirectory(
            self,
            "Export quality report",
            "",
        )
        if not folder:
            return
        try:
            report = build_stakeholder_quality_report(
                self.inst,
                self.current_schedule,
                branding=self._effective_branding(),
                baseline_schedule=self.base_schedule or None,
            )
            outputs = write_stakeholder_quality_report(folder, report)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Quality report error", str(exc))
            return
        self._append_audit_log("quality_report_exported", dict(outputs))
        self.set_status(f"Quality report exported to {outputs.get('markdown', folder)}")

    def on_export_calendar_feeds(self) -> None:
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to export")
            return
        path = QFileDialog.getExistingDirectory(
            self,
            "Export calendar feeds (choose folder)",
            "",
        )
        if not path:
            return
        try:
            manifest = export_calendar_feeds(self.inst, self.current_schedule, path)
            feed_count = sum(
                len(v) for v in (manifest.get("feeds", {}) or {}).values() if isinstance(v, list)
            )
            self.set_status(f"Calendar feeds exported ({feed_count} files)")
            self._append_audit_log(
                "calendar_feeds_exported",
                {"path": str(path), "feed_files": int(feed_count)},
            )
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Export error", str(exc))

    def _export_connector_csv(
        self,
        *,
        title: str,
        default_name: str,
        writer: Any,
        audit_event: str,
    ) -> None:
        if self.inst is None:
            self.set_status("No instance to export")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            title,
            default_name,
            "CSV files (*.csv)",
        )
        if not path:
            return
        try:
            writer(self.inst, path)
            self._append_audit_log(audit_event, {"path": str(path)})
            self.set_status(f"Connector export written to {path}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Connector export error", str(exc))
            self.set_status("Connector export error")

    def on_export_sis_csv(self) -> None:
        connector = SISCsvConnector()
        self._export_connector_csv(
            title="Export SIS CSV",
            default_name="sis_courses.csv",
            writer=connector.export_courses,
            audit_event="connector_export_sis_csv",
        )

    def on_export_erp_csv(self) -> None:
        connector = ERPCsvConnector()
        self._export_connector_csv(
            title="Export ERP CSV",
            default_name="erp_staff_ownership.csv",
            writer=connector.export_staff_ownership,
            audit_event="connector_export_erp_csv",
        )

    def on_export_lms_csv(self) -> None:
        connector = LMSCsvConnector()
        self._export_connector_csv(
            title="Export LMS CSV",
            default_name="lms_group_enrollments.csv",
            writer=connector.export_group_enrollments,
            audit_event="connector_export_lms_csv",
        )

    def _read_csv_preview_rows(
        self, path: str, *, max_rows: int = 20
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        import csv

        headers: List[str] = []
        rows: List[Dict[str, Any]] = []
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = [str(h) for h in (reader.fieldnames or [])]
            for idx, row in enumerate(reader):
                if idx >= int(max_rows):
                    break
                rows.append({str(k): row.get(k) for k in headers})
        return headers, rows

    def _load_validated_schedule(self, schedule: Dict[int, Dict[str, Any]], *, source: str) -> None:
        if self.inst is None:
            return
        filtered = {}
        missing = 0
        invalid = 0
        inst = self.inst
        for a_id, info in schedule.items():
            if int(a_id) not in inst.activities:
                missing += 1
                continue
            act = inst.activities[int(a_id)]
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
            if staff_id is not None and int(staff_id) not in inst.staff:
                invalid += 1
                continue
            if act.kind == "LEC" and staff_id is not None and not inst.staff.get(int(staff_id)).is_prof:
                invalid += 1
                continue
            if act.kind != "LEC" and staff_id is not None and inst.staff.get(int(staff_id)).is_prof:
                invalid += 1
                continue
            filtered[int(a_id)] = dict(info)

        self.base_schedule = filtered
        self.current_schedule = {a_id: info.copy() for a_id, info in filtered.items()}
        self._set_manual_highlight_base(self.current_schedule)
        self.held_activity_id = None
        self._bump_schedule_revision()
        self._reset_history()
        errors = validate_schedule_against_instance(
            self.inst,
            self.current_schedule,
            strict_rooms=False,
            require_all_activities=False,
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
            self._bump_schedule_revision()
            self.clear_table()
            self.set_status("Load error")
            return
        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        msg = f"Loaded schedule {source}"
        if missing:
            msg += f" ({missing} activities ignored)"
        if invalid:
            msg += f" ({invalid} invalid rows skipped)"
        self.set_status(msg)
        self._append_audit_log(
            "schedule_imported",
            {
                "source": str(source),
                "loaded_rows": int(len(self.current_schedule)),
                "missing_rows": int(missing),
                "invalid_rows": int(invalid),
            },
        )
        self._save_persistent_history()

    def on_import_schedule_wizard(self) -> None:
        if self.inst is None:
            self.set_status("Load instance first")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import schedule (wizard)",
            "",
            "CSV files (*.csv)",
        )
        if not path:
            return
        try:
            headers, preview_rows = self._read_csv_preview_rows(path)
        except Exception as exc:
            QMessageBox.critical(self, "Import error", str(exc))
            return
        if not headers:
            QMessageBox.warning(self, "Import error", "No CSV headers found.")
            return
        dlg = ImportScheduleWizardDialog(
            self,
            headers,
            preview_rows,
            default_mapping=self._last_import_mapping,
            default_group_separator=self._last_group_separator,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._last_import_mapping = dict(dlg.selected_mapping())
            self._last_group_separator = str(dlg.group_separator())
            schedule = read_schedule_csv_mapped(
                path,
                field_map=self._last_import_mapping,
                group_separator=self._last_group_separator,
            )
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Import error", str(exc))
            return
        self._load_validated_schedule(schedule, source=path)

    def on_import_timetable_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import timetable CSV",
            "",
            "CSV files (*.csv)",
        )
        if not path:
            return
        try:
            headers, preview_rows = self._read_csv_preview_rows(path)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Import error", str(exc))
            self.set_status("Import error")
            return
        if not headers:
            QMessageBox.warning(self, "Import error", "No CSV headers found.")
            self.set_status("Import error")
            return

        default_mapping = suggest_timetable_mapping(headers)
        dlg = TimetableCsvImportWizardDialog(
            self,
            headers,
            preview_rows,
            default_mapping=default_mapping,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.set_status("Import canceled")
            return
        field_map = dict(dlg.selected_mapping())
        transform_config = {}
        try:
            transform_config = dict(dlg.transform_config())
        except Exception:
            transform_config = {}

        teaching_load_path: str | None = None
        load_staff = QMessageBox.question(
            self,
            "Use teaching-load assignments?",
            "Optionally select an XLSX teaching-load workbook to map real lecturers and TAs.\n"
            "Choose No to use balanced synthetic staff pools.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if load_staff == QMessageBox.StandardButton.Yes:
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Select teaching-load workbook",
                "",
                "Excel workbook (*.xlsx)",
            )
            if str(selected).lower().endswith(".xlsx"):
                teaching_load_path = str(selected)

        try:
            self.set_status("Importing timetable CSV...")
            inst, schedule, meta = import_timetable_csv(
                path,
                lock_imported=False,
                field_map=field_map,
                transform_config=transform_config,
                teaching_load_path=teaching_load_path,
            )
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Import error", str(exc))
            self.set_status("Import error")
            return

        preview_lines = [
            f"Source rows: {int(meta.get('source_events', 0))}",
            f"Activities after merge: {int(meta.get('activities_after_shared_event_merge', len(schedule)))}",
            f"Groups: {int(meta.get('groups', len(inst.groups)))}",
            f"Courses: {int(meta.get('courses', len(inst.courses)))}",
            f"Rooms: {int(meta.get('rooms', len(inst.rooms)))}",
            f"Teaching-load course matches: {int(meta.get('teaching_load_matches', 0))}",
            f"Soft penalty: {int(meta.get('soft_penalty', 0))}",
            f"Hard conflicts: {int(meta.get('validation_error_count', 0))}",
        ]
        decision = QMessageBox.question(
            self,
            "Import timetable CSV?",
            "Import preview:\n\n"
            + "\n".join(preview_lines)
            + "\n\nThe imported placements will remain unlocked so Solve/Repair can move them.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if decision != QMessageBox.StandardButton.Yes:
            self.set_status("Import canceled")
            return

        self.inst = inst
        self.locked_activities = dict(getattr(inst, "locked_activities", {}) or {})
        self.base_schedule = {int(a_id): dict(info) for a_id, info in schedule.items()}
        self.current_schedule = {int(a_id): dict(info) for a_id, info in schedule.items()}
        self.held_activity_id = None
        self._set_manual_highlight_base(self.current_schedule)
        self._bump_schedule_revision()
        self._reset_history()
        self._load_constraint_controls_from_instance(self.inst)
        self._refresh_product_scenario_from_instance()
        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self._refresh_history_view()
        self._refresh_history_buttons()
        self._append_audit_log(
            "timetable_csv_imported",
            {
                "path": str(path),
                "teaching_load_path": str(teaching_load_path or ""),
                "activities": int(meta.get("activities_after_shared_event_merge", 0)),
                "soft_penalty": int(meta.get("soft_penalty", 0)),
                "hard_conflicts": int(meta.get("validation_error_count", 0)),
            },
        )
        self._save_persistent_history()
        conflicts = int(meta.get("validation_error_count", 0))
        penalty = int(meta.get("soft_penalty", 0))
        self.set_status(
            f"Imported timetable CSV: {len(schedule)} activities, soft penalty {penalty}, hard conflicts {conflicts}"
        )
        if conflicts:
            preview = "\n".join(str(err) for err in list(meta.get("validation_errors", []) or [])[:8])
            QMessageBox.warning(
                self,
                "Imported with conflicts",
                "The timetable was imported and left unlocked so Solve/Improve can repair it.\n\n"
                f"Hard conflicts: {conflicts}\n"
                f"Soft penalty: {penalty}\n\n"
                + (preview if preview else "Open Conflicts for details."),
            )
        save_decision = QMessageBox.question(
            self,
            "Save imported scenario?",
            "Save this imported CSV as a reusable scheduler scenario now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if save_decision == QMessageBox.StandardButton.Yes:
            out_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save imported scenario",
                "imported_timetable_scenario.json",
                "Scenario (*.json *.pkl)",
            )
            if out_path:
                try:
                    write_scenario(
                        out_path,
                        self.inst,
                        self.current_schedule,
                        meta={
                            "source_import": dict(meta),
                            "operator_name": str(self._operator_name),
                        },
                    )
                    self.set_status(f"Imported timetable saved to {out_path}")
                except Exception as exc:
                    traceback.print_exc()
                    QMessageBox.warning(self, "Save scenario error", str(exc))

    def on_sandbox_start(self) -> None:
        if not self.current_schedule:
            self.set_status("No schedule to branch")
            return
        self._sandbox_base_schedule = self._clone_schedule()
        self.set_status(
            "Sandbox branch started. Make edits, then use Sandbox Compare/Apply/Discard."
        )
        self._append_audit_log(
            "sandbox_started", {"activities": int(len(self._sandbox_base_schedule))}
        )

    def on_sandbox_compare(self) -> None:
        if self._sandbox_base_schedule is None:
            self.set_status("Start sandbox first")
            return
        summary = compare_schedules(self._sandbox_base_schedule, self.current_schedule)
        base_soft = self._compute_soft_penalty(self._sandbox_base_schedule)
        cur_soft = self._compute_soft_penalty(self.current_schedule)
        cur_hard = len(self._collect_conflict_errors()) if self.current_schedule else 0
        msg = [
            "Sandbox Comparison",
            f"Soft penalty: {base_soft} -> {cur_soft} (Δ {int((cur_soft or 0) - (base_soft or 0)):+d})",
            f"Hard conflicts now: {cur_hard}",
            f"Changed time: {summary.get('changed_time', 0)}",
            f"Changed room: {summary.get('changed_room', 0)}",
            f"Changed staff: {summary.get('changed_staff', 0)}",
        ]
        QMessageBox.information(self, "Sandbox Compare", "\n".join(msg))

    def on_sandbox_apply(self) -> None:
        if self._sandbox_base_schedule is None:
            self.set_status("No sandbox branch active")
            return
        if bool(self._protected_baseline.get("protected", False)):
            approval = self._require_approval(
                action="apply_branch_to_protected_baseline",
                details={"active_branch": self._active_branch_name},
            )
            if approval is None:
                self.set_status("Sandbox apply canceled: approval not granted")
                return
        sandbox_errors = self._validate_schedule_hard_errors(
            self.current_schedule, require_all=True
        )
        if sandbox_errors:
            sample = "\n".join(f"- {line}" for line in sandbox_errors[:10])
            QMessageBox.warning(
                self,
                "Sandbox apply blocked",
                "Current sandbox state has hard conflicts and cannot become base.\n\n"
                f"Conflicts: {len(sandbox_errors)}\n{sample}",
            )
            self.set_status(
                f"Sandbox apply blocked: {len(sandbox_errors)} hard conflicts"
            )
            return
        self.base_schedule = self._clone_schedule()
        self._set_manual_highlight_base(self.current_schedule)
        self._sandbox_base_schedule = None
        if self._active_branch_name and self._active_branch_name in self._branches:
            self._branches[self._active_branch_name] = update_branch(
                self._branches[self._active_branch_name], self.current_schedule
            )
        self.set_status("Sandbox branch applied as new base schedule.")
        self._append_audit_log("sandbox_applied", {"activities": int(len(self.base_schedule))})
        self._save_persistent_history()

    def on_sandbox_discard(self) -> None:
        if self._sandbox_base_schedule is None:
            self.set_status("No sandbox branch active")
            return
        self._push_undo_state()
        self.current_schedule = {
            int(a_id): info.copy()
            for a_id, info in self._sandbox_base_schedule.items()
        }
        self._sandbox_base_schedule = None
        self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
        self._sync_instance_staff_from_schedule(self.current_schedule)
        self.update_table()
        self.update_quality_summary()
        self.set_status("Sandbox changes discarded; branch baseline restored.")
        self._append_audit_log("sandbox_discarded", {})

    def on_auto_repair_disruption(self) -> None:
        if self.inst is None or not self.current_schedule:
            self.set_status("No schedule to repair")
            return
        disruption_type, ok = QInputDialog.getItem(
            self,
            "Auto-Repair Disruption",
            "Disruption type:",
            ["Staff outage (week)", "Room outage (week)"],
            0,
            False,
        )
        if not ok:
            return
        if not self.inst.weeks:
            self.set_status("Instance has no weeks configured")
            return
        week_labels = [f"W{int(w)}" for w in self.inst.weeks]
        week_choice, ok = QInputDialog.getItem(
            self,
            "Auto-Repair Disruption",
            "Affected week:",
            week_labels,
            0,
            False,
        )
        if not ok:
            return
        week = int(str(week_choice).lstrip("Ww").strip())
        prior_locks = {
            int(a_id): dict(lock)
            for a_id, lock in self.locked_activities.items()
            if isinstance(lock, dict)
        }
        updated = self._clone_schedule()
        affected: Set[int] = set()
        unresolved: Set[int] = set()

        if str(disruption_type).startswith("Staff"):
            options = []
            for sid, s in sorted(self.inst.staff.items()):
                options.append(f"{int(sid)}: {s.name}")
            choice, ok = QInputDialog.getItem(
                self,
                "Staff outage",
                "Unavailable staff:",
                options,
                0,
                False,
            )
            if not ok:
                return
            staff_id = int(str(choice).split(":", 1)[0].strip())
            staff = self.inst.staff.get(int(staff_id))
            if staff is not None:
                weeks = getattr(staff, "available_weeks", None)
                if weeks is None:
                    weeks = set(int(w) for w in self.inst.weeks)
                weeks = {int(w) for w in weeks if int(w) != int(week)}
                staff.available_weeks = weeks
            updated, affected, unresolved = apply_staff_outage_week(
                self.inst,
                updated,
                staff_id=int(staff_id),
                week=int(week),
            )
        else:
            options = []
            for rid, r in sorted(self.inst.rooms.items()):
                options.append(f"{int(rid)}: {r.name}")
            choice, ok = QInputDialog.getItem(
                self,
                "Room outage",
                "Unavailable room:",
                options,
                0,
                False,
            )
            if not ok:
                return
            room_id = int(str(choice).split(":", 1)[0].strip())
            updated, affected, unresolved = apply_room_outage_week(
                self.inst,
                updated,
                room_id=int(room_id),
                week=int(week),
            )

        if not affected:
            self.set_status("No activities affected by selected disruption.")
            return
        self._push_undo_state()
        self._commit_schedule(
            updated,
            f"Applied disruption pre-repair for week {week} "
            f"(affected={len(affected)}, unresolved={len(unresolved)})",
        )
        freeze_locks = build_freeze_locks(
            self.current_schedule,
            unlocked_activity_ids=affected,
        )
        self.locked_activities = freeze_locks
        self._sync_locks_to_instance()
        self._restore_locks_after_solve = prior_locks
        self._append_audit_log(
            "auto_repair_started",
            {
                "type": str(disruption_type),
                "week": int(week),
                "affected": int(len(affected)),
                "unresolved": int(len(unresolved)),
            },
        )
        if unresolved:
            QMessageBox.warning(
                self,
                "Auto-repair warning",
                f"{len(unresolved)} activity(ies) had no direct replacement; solver will try to recover.",
            )
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
        self._append_audit_log("undo_applied", {"undo_depth": len(self._undo_stack)})

    def on_redo(self) -> None:
        if not self._redo_stack:
            self.set_status("Nothing to redo")
            return
        current = self._snapshot_state()
        nxt = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._restore_state(nxt, "Redo applied")
        self._refresh_history_buttons()
        self._append_audit_log("redo_applied", {"redo_depth": len(self._redo_stack)})

    def on_revert_to_base(self) -> None:
        if not self.base_schedule:
            self.set_status("No base solution to revert to")
            return
        base_errors = self._validate_schedule_hard_errors(
            self.base_schedule, require_all=False
        )
        if base_errors:
            sample = "\n".join(f"- {line}" for line in base_errors[:10])
            QMessageBox.warning(
                self,
                "Revert blocked",
                "Base schedule currently has hard conflicts and was not applied.\n\n"
                f"Conflicts: {len(base_errors)}\n{sample}",
            )
            self.set_status(
                f"Revert blocked: base has {len(base_errors)} hard conflicts"
            )
            return
        self._push_undo_state()
        self.current_schedule = {a_id: info.copy() for a_id, info in self.base_schedule.items()}
        self._set_manual_highlight_base(self.current_schedule)
        self.locked_activities = {}
        self.held_activity_id = None
        self._bump_schedule_revision()
        self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
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
        friendly_errors = [self._humanize_conflict_error(err) for err in errors]
        dlg = ConflictInspectorDialog(self, friendly_errors)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if dlg.solve_conflicts_requested():
                self._solve_current_conflicts(errors)
                return
            activity_id = dlg.selected_activity_id()
            if activity_id is not None:
                if self._jump_to_activity(int(activity_id)):
                    self.set_status(f"Jumped to conflict activity A{int(activity_id)}")
                else:
                    self.set_status(
                        f"Conflict selected: A{int(activity_id)} (unable to jump)"
                    )
                return
        self.set_status(f"Conflicts found: {len(errors)}")

    def _restore_locks_if_needed(self) -> None:
        if self._restore_locks_after_solve is None:
            return
        self.locked_activities = {
            int(a_id): dict(lock)
            for a_id, lock in self._restore_locks_after_solve.items()
            if isinstance(lock, dict)
        }
        self._restore_locks_after_solve = None
        self._sync_locks_to_instance()
        self._refresh_history_buttons()

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
        sender_proc = self.sender()
        if (
            sender_proc is not None
            and self.proc is not None
            and sender_proc is not self.proc
        ):
            return
        proc = self.proc
        self.set_busy(False)
        self._stop_solve_progress()
        output = str(self._solver_output_log or "")
        if proc is not None:
            try:
                output += proc.readAll().data().decode("utf-8", errors="ignore")
            except Exception:
                pass
        self.proc = None
        self._last_solver_output_log = str(output)
        self._solver_output_log = ""
        if (
            self._is_solver_process_crash_error(error)
            and self._retry_solver_once_in_safe_mode(
                reason="qprocess_error",
                detail={
                    "error": str(error),
                    "keep_locks": bool(self._last_solver_keep_locks),
                },
            )
        ):
            if proc is not None:
                try:
                    proc.deleteLater()
                except Exception:
                    pass
            return

        msg = output or f"QProcess error: {error}"
        if self._is_solver_process_crash_error(error):
            msg += (
                "\n\nNative worker crash detected.\n"
                "Try: workers=Min, objective off, or reinstall the packaged app."
            )
            try:
                write_crash_report(
                    self._runtime_paths["crash_dir"],
                    error_type="SolverWorkerCrash",
                    message=str(error),
                    traceback_text=output,
                    context={"phase": "qprocess_error"},
                    opt_in=bool(self._runtime_settings.get("crash_reports_opt_in", False)),
                )
            except Exception:
                pass
        QMessageBox.critical(self, "Solver error", msg)
        self._append_audit_log("solve_error", {"error": str(error)})
        self._restore_locks_if_needed()
        if proc is not None:
            try:
                proc.deleteLater()
            except Exception:
                pass
        self._cleanup_solver_temp_files()
        self.set_status("Solve error")

    def on_solver_finished(self, exit_code: int, exit_status):
        sender_proc = self.sender()
        if (
            sender_proc is not None
            and self.proc is not None
            and sender_proc is not self.proc
        ):
            return
        proc = self.proc
        if proc is not None:
            try:
                self.on_solver_output_ready()
            except Exception:
                pass
        self._update_solve_progress_status(99, "finalizing")
        self.set_busy(False)
        self._stop_solve_progress()

        output = str(self._solver_output_log or "")
        if proc is not None:
            try:
                output += proc.readAll().data().decode("utf-8", errors="ignore")
            except Exception:
                pass
        self.proc = None
        self._last_solver_output_log = str(output)
        self._solver_output_log = ""
        if proc is not None:
            try:
                proc.deleteLater()
            except Exception:
                pass

        if exit_code != 0:
            if (
                self._is_access_violation_exit_code(int(exit_code))
                and self._retry_solver_once_in_safe_mode(
                    reason="exit_code",
                    detail={
                        "exit_code": int(exit_code),
                        "keep_locks": bool(self._last_solver_keep_locks),
                    },
                )
            ):
                return
            msg = output or f"Solver exited with code {exit_code}"
            if self._is_access_violation_exit_code(int(exit_code)):
                msg += (
                    "\n\nWindows code 0xC0000005 (access violation): "
                    "a native dependency crashed.\n"
                    "Try: workers=Min, objective off, or reinstall the packaged app."
                )
                try:
                    write_crash_report(
                        self._runtime_paths["crash_dir"],
                        error_type="SolverWorkerExitCode",
                        message=f"Exit code {int(exit_code)}",
                        traceback_text=output,
                        context={"phase": "finished"},
                        opt_in=bool(self._runtime_settings.get("crash_reports_opt_in", False)),
                    )
                except Exception:
                    pass
            QMessageBox.critical(
                self,
                "Solver crashed",
                msg,
            )
            self._append_audit_log("solve_crash", {"exit_code": int(exit_code)})
            self._restore_locks_if_needed()
            self._cleanup_solver_temp_files()
            self.set_status(f"Solver failed (code {exit_code})")
            return

        if not self.tmp_res_path or not os.path.exists(self.tmp_res_path):
            QMessageBox.critical(self, "Result error", "Result file not found.")
            self._append_audit_log("solve_result_missing", {})
            self._restore_locks_if_needed()
            self._cleanup_solver_temp_files()
            self.set_status("Solve error")
            return

        try:
            with open(self.tmp_res_path, "rb") as f:
                res = pickle.load(f)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Result error", f"Cannot read result: {e}")
            self._append_audit_log("solve_result_read_error", {"error": str(e)})
            self._restore_locks_if_needed()
            self._cleanup_solver_temp_files()
            self.set_status("Solve error")
            return
        finally:
            self._cleanup_solver_temp_files()

        meta = res.get("meta")
        self._last_solver_result_meta = dict(meta) if isinstance(meta, dict) else {}
        status = res.get("status", -1)
        if status not in (0, 4):  # 0=FEASIBLE, 4=OPTIMAL
            self.base_schedule = {}
            self._set_manual_highlight_base({})
            self.current_schedule = {}
            self.held_activity_id = None
            self._bump_schedule_revision()
            self._reset_history()
            self.clear_table()
            self.set_status(f"No feasible schedule (status {status})")
            if self._solver_debug_enabled():
                msg = self._build_solver_debug_report(res, int(status))
                self._show_solver_report_dialog(
                    "No feasible schedule - Debug diagnostics",
                    msg,
                )
            else:
                msg = self._build_no_feasible_message(res, int(status))
                QMessageBox.information(self, "No feasible schedule", msg)
            self._append_audit_log(
                "solve_no_feasible",
                {"status": int(status), "attempts": self._format_solver_attempts(res)},
            )
            self._restore_locks_if_needed()
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
            self._bump_schedule_revision()
            self._reset_history()
            self.clear_table()
            self.set_status(
                f"Solve rejected: hard conflicts detected ({len(base_hard_errors)})"
            )
            sample = "\n".join(f"- {line}" for line in base_hard_errors[:12])
            message = (
                "The solver returned a schedule with hard conflicts and it was rejected.\n\n"
                f"Conflicts: {len(base_hard_errors)}\n\n"
                f"{sample}"
            )
            if self._solver_debug_enabled():
                debug_payload = {
                    "status": -3,
                    "schedule": {},
                    "error": "The solver returned a schedule with hard conflicts and it was rejected.",
                    "meta": {
                        "hard_conflicts": {
                            "count": len(base_hard_errors),
                            "sample": base_hard_errors[:25],
                            "stage": "ui_post_extract",
                        }
                    },
                }
                self._show_solver_report_dialog(
                    "Invalid solve result - Debug diagnostics",
                    message + "\n\n" + self._build_solver_debug_report(debug_payload, -3),
                )
            else:
                QMessageBox.critical(
                    self,
                    "Invalid solve result",
                    message,
                )
            self._append_audit_log(
                "solve_rejected_hard_conflicts", {"count": len(base_hard_errors)}
            )
            self._restore_locks_if_needed()
            return

        self.current_schedule = {
            a_id: info.copy() for a_id, info in self.base_schedule.items()
        }
        self._set_manual_highlight_base(self.current_schedule)
        self.held_activity_id = None
        self._bump_schedule_revision()
        self._reset_history()
        attempts = self._format_solver_attempts(res)
        final_attempt = attempts[-1] if attempts else ""

        try:
            if self.inst is not None and self.current_schedule:
                ls_seconds = float(self.ls_time_spin.value() or 0)
                if ls_seconds <= 0:
                    status_msg = f"Solved (status {status})"
                    if final_attempt:
                        status_msg += f" | {final_attempt}"
                    self.set_status(status_msg)
                    self.populate_weeks()
                    self.update_entities()
                    self.update_table()
                    self.update_quality_summary()
                    self._append_audit_log(
                        "solve_finished",
                        {"status": int(status), "activities": int(len(self.current_schedule))},
                    )
                    self._restore_locks_if_needed()
                    self._save_persistent_history()
                    return
                focus_term = self._selected_improve_focus_term()
                improve_inst = self._build_focused_improve_instance(focus_term)
                ls = LocalSearchImprover(improve_inst)
                before = ls.compute_soft_penalty(self.current_schedule)
                improved = ls.improve(
                    self.current_schedule,
                    iterations=int(self.improve_runs_spin.value()),
                    max_seconds=ls_seconds,
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
                    self._bump_schedule_revision()
                    metric = (
                        f"{self._focus_label(focus_term)} focus penalty"
                        if focus_term
                        else "soft penalty"
                    )
                    status_msg = (
                        f"Solved (status {status}), {metric} {before} -> {after}"
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
        self._append_audit_log(
            "solve_finished",
            {"status": int(status), "activities": int(len(self.current_schedule))},
        )
        self._restore_locks_if_needed()
        self._save_persistent_history()

    def on_improve(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to improve")
            return

        start_hard_errors = self._collect_conflict_errors()
        if start_hard_errors:
            sample = "\n".join(f"- {line}" for line in start_hard_errors[:8])
            QMessageBox.warning(
                self,
                "Improve blocked",
                "Cannot run improvement while hard constraints are violated.\n\n"
                f"Conflicts: {len(start_hard_errors)}\n{sample}\n\n"
                "Use Conflicts -> Solve Conflicts first.",
            )
            self.set_status(
                f"Improve blocked: {len(start_hard_errors)} hard conflicts present"
            )
            return

        self._improve_total_iters = int(self.improve_runs_spin.value())
        self._improve_original_schedule = {
            a_id: info.copy() for a_id, info in self.current_schedule.items()
        }
        self._improve_focus_term = self._selected_improve_focus_term()
        improve_inst = self._build_focused_improve_instance(self._improve_focus_term)
        try:
            self._improve_base_penalty = LocalSearchImprover(improve_inst).compute_soft_penalty(
                self._improve_original_schedule
            )
        except Exception:
            self._improve_base_penalty = None
        self._live_improve_mode = True
        self._improve_running = True
        self._improve_stop_requested = False
        self.stop_improve_button.setEnabled(True)
        self.set_busy(True)
        focus_note = (
            f" focused on {self._focus_label(self._improve_focus_term)}"
            if self._improve_focus_term
            else ""
        )
        self.set_status(f"Improving{focus_note}... 0% (iter 0/{self._improve_total_iters})")

        self._improve_thread = QThread(self)
        self._improve_worker = ImproveWorker(
            improve_inst,
            self._improve_original_schedule,
            iterations=int(self._improve_total_iters),
            max_seconds=(float(self.ls_time_spin.value()) or None),
        )
        self._improve_worker.moveToThread(self._improve_thread)
        self._improve_thread.started.connect(self._improve_worker.run)
        self._improve_worker.progress.connect(self._on_improve_worker_progress)
        self._improve_worker.finished.connect(self._on_improve_worker_finished)
        self._improve_worker.error.connect(self._on_improve_worker_error)
        self._improve_worker.finished.connect(self._cleanup_improve_worker)
        self._improve_worker.error.connect(self._cleanup_improve_worker)
        self._improve_thread.start()

    def _on_improve_worker_progress(
        self,
        it_done: int,
        best_pen: int,
        cur_pen: int,
        snapshot: object,
    ) -> None:
        if isinstance(snapshot, dict):
            self.current_schedule = {
                int(a_id): dict(info) for a_id, info in snapshot.items()
            }
            self.update_table()
            self.update_quality_summary()
        pct = int(
            min(
                99,
                max(0.0, float(it_done) / max(1.0, float(self._improve_total_iters))) * 100.0,
            )
        )
        base_pen = self._improve_base_penalty
        if base_pen is None:
            self.set_status(
                f"Improving... {pct}% (iter {int(it_done)}/{self._improve_total_iters}, current={int(cur_pen)}, best={int(best_pen)})"
            )
        else:
            self.set_status(
                f"Improving... {pct}% (iter {int(it_done)}/{self._improve_total_iters}, original={int(base_pen)}, current={int(cur_pen)}, best={int(best_pen)})"
            )

    def _on_improve_worker_finished(
        self,
        improved: object,
        start_pen: int,
        final_pen: int,
    ) -> None:
        original_schedule = self._improve_original_schedule or {}
        improved_schedule = (
            {int(a_id): dict(info) for a_id, info in improved.items()}
            if isinstance(improved, dict)
            else {}
        )
        improved_hard_errors = self._validate_schedule_hard_errors(
            improved_schedule, require_all=True
        )
        self.current_schedule = {
            int(a_id): dict(info) for a_id, info in original_schedule.items()
        }
        self._live_improve_mode = False
        if improved_hard_errors:
            self.update_table()
            self.update_quality_summary()
            self.set_status(
                f"Improvement rejected: {len(improved_hard_errors)} hard conflicts detected"
            )
            return
        if improved_schedule != original_schedule:
            self._push_undo_state()
        metric_label = (
            f"{self._focus_label(self._improve_focus_term)} focus penalty"
            if self._improve_focus_term
            else "global penalty"
        )
        self._commit_schedule(
            improved_schedule,
            f"Improved {metric_label} {int(start_pen)} -> {int(final_pen)}"
            + (" [stopped]" if self._improve_stop_requested else ""),
        )
        self._set_manual_highlight_base(self.current_schedule)
        if improved_schedule != original_schedule:
            self._show_improvement_delta_report(
                original_schedule,
                improved_schedule,
                title="Improve before/after report",
            )

    def _on_improve_worker_error(self, message: str) -> None:
        traceback.print_exc()
        QMessageBox.critical(self, "Improve error", str(message))
        if self._improve_original_schedule is not None:
            self.current_schedule = {
                int(a_id): dict(info)
                for a_id, info in self._improve_original_schedule.items()
            }
            self.update_table()
            self.update_quality_summary()
        self.set_status("Improve error")

    def _cleanup_improve_worker(self, *_args: Any) -> None:
        self._live_improve_mode = False
        self._improve_running = False
        self._improve_stop_requested = False
        self._improve_base_penalty = None
        self._improve_focus_term = ""
        self.stop_improve_button.setEnabled(False)
        self.set_busy(False)
        if self._improve_thread is not None:
            self._improve_thread.quit()
            self._improve_thread.wait(1000)
            self._improve_thread.deleteLater()
            self._improve_thread = None
        if self._improve_worker is not None:
            self._improve_worker.deleteLater()
            self._improve_worker = None

    def on_stop_improve(self) -> None:
        if not self._improve_running:
            self.set_status("No active improve run")
            return
        self._improve_stop_requested = True
        if self._improve_worker is not None:
            self._improve_worker.request_stop()
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
            export_docx_service(
                self.inst,
                self.current_schedule,
                path,
                branding=self._effective_branding(),
            )
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
            export_pdf_service(
                self.inst,
                self.current_schedule,
                path,
                branding=self._effective_branding(),
            )
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
            export_reports_service(
                self.inst,
                self.current_schedule,
                path,
                branding=self._effective_branding(),
                baseline_schedule=self.base_schedule or None,
            )
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
            "Project (*.json *.pkl *.db *.sqlite)",
        )
        if not path:
            return

        try:
            self.set_status("Saving project...")
            # Ensure locks are persisted
            self.inst.locked_activities = dict(self.locked_activities)
            schedule = self.current_schedule or {}
            meta = {"source": "ui", **self._workspace_meta()}
            save_legacy_project(path, self.inst, schedule, meta=meta)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Save error", str(e))
            self.set_status("Save error")
            return

        self.set_status(f"Saved to {path}")

    def on_save_product_scenario(self) -> None:
        if self.inst is None and self.product_scenario is None:
            self.set_status("No scenario to save")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Save {APP_SHORT_NAME} product scenario",
            "planora_scenario.json",
            "Product Scenario (*.json)",
        )
        if not path:
            return
        try:
            self.set_status("Saving product scenario...")
            if self.inst is not None:
                self._refresh_product_scenario_from_instance()
            scenario = self.product_scenario
            if scenario is None:
                raise ValueError("No product scenario available")
            save_product_scenario(path, scenario)
            self._append_audit_log("product_scenario_saved", {"path": str(path)})
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Save error", str(exc))
            self.set_status("Save error")
            return
        self.set_status(f"Product scenario saved to {path}")

    def _collect_institution_template_payload(self) -> Dict[str, Any]:
        custom_config = self._collect_custom_generation_config()
        hard, soft = self._collect_constraint_settings()
        return {
            "name": getattr(self.product_scenario, "metadata", None).name
            if self.product_scenario is not None
            else "Institution Template",
            "branding": {
                **self._effective_branding(),
            },
            "objective_profile": str(
                self.objective_profile_combo.currentData() or "balanced"
            ),
            "constraints": {
                "hard": dict(hard),
                "soft": dict(soft),
            },
            "generator_defaults": dict(custom_config),
            "import_defaults": {
                "mapping": dict(self._last_import_mapping or {}),
                "group_separator": str(self._last_group_separator or ";"),
            },
        }

    def _apply_institution_template_payload(self, payload: Dict[str, Any]) -> None:
        merged = apply_institution_template(
            payload,
            current_config=self._collect_institution_template_payload(),
        )
        self._institution_template = dict(merged)
        self._branding_profile = branding_from_institution_template(merged)
        self._apply_branding_profile()
        objective_profile = str(merged.get("objective_profile", "balanced") or "balanced")
        idx = self.objective_profile_combo.findData(objective_profile)
        if idx >= 0:
            self.objective_profile_combo.setCurrentIndex(idx)
        constraints = dict(merged.get("constraints", {}) or {})
        hard = dict(constraints.get("hard", {}) or {})
        soft = dict(constraints.get("soft", {}) or {})
        if hard:
            self.hard_week1_cb.setChecked(bool(hard.get("week1_lectures_only", True)))
            self.hard_block_prof_cb.setChecked(
                bool(hard.get("enforce_block_professor_rules", True))
            )
            self.hard_staff_daily_cb.setChecked(
                bool(hard.get("enforce_staff_daily_caps", True))
            )
            self.hard_staff_weekly_cb.setChecked(
                bool(hard.get("enforce_staff_weekly_caps", True))
            )
            self.hard_room_availability_cb.setChecked(
                bool(hard.get("enforce_room_availability", True))
            )
        for key, spin in self.soft_weight_spins.items():
            if key in soft:
                try:
                    spin.setValue(int(soft[key]))
                except Exception:
                    continue
        generator_defaults = merged.get("generator_defaults")
        if isinstance(generator_defaults, dict):
            self._apply_custom_generation_config(generator_defaults)
        import_defaults = dict(merged.get("import_defaults", {}) or {})
        self._last_import_mapping = {
            str(k): str(v)
            for k, v in dict(import_defaults.get("mapping", {}) or {}).items()
        }
        self._last_group_separator = str(
            import_defaults.get("group_separator", ";") or ";"
        )

    def on_save_institution_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save institution template",
            "institution_template.json",
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            save_institution_template(path, self._collect_institution_template_payload())
            self.set_status(f"Institution template saved to {path}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Template error", str(exc))
            self.set_status("Template save error")

    def on_load_institution_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load institution template",
            "",
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            payload = load_institution_template(path)
            self._apply_institution_template_payload(payload)
            self._save_persistent_history()
            self.set_status(f"Institution template loaded from {path}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Template error", str(exc))
            self.set_status("Template load error")

    def on_apply_white_label_profile(self) -> None:
        institution_name, ok = QInputDialog.getText(
            self,
            "White-Label Profile",
            "Institution name:",
            text=str(self._institution_template.get("name", "") if isinstance(self._institution_template, dict) else ""),
        )
        if not ok or not str(institution_name).strip():
            return
        owner_name, ok_owner = QInputDialog.getText(
            self,
            "White-Label Profile",
            "Owner / publisher:",
            text=str(self._operator_name or APP_OWNER_NAME),
        )
        if not ok_owner:
            return
        self._branding_profile = white_label_profile_for_institution(
            institution_name=str(institution_name).strip(),
            owner_name=str(owner_name).strip() or APP_OWNER_NAME,
        )
        if self._institution_template is None:
            self._institution_template = {}
        self._institution_template["name"] = str(institution_name).strip()
        self._institution_template["branding"] = dict(self._branding_profile)
        self._apply_branding_profile()
        self._append_audit_log(
            "white_label_profile_applied",
            {"institution": str(institution_name).strip()},
        )
        self._save_persistent_history()
        self.set_status(f"White-label profile applied for {str(institution_name).strip()}")

    def on_set_operator_name(self) -> None:
        value, ok = QInputDialog.getText(
            self,
            "Operator Name",
            "Current operator:",
            text=str(self._operator_name or ""),
        )
        if not ok:
            return
        previous = str(self._operator_name or "unknown")
        self._operator_name = str(value or "").strip() or "unknown"
        self._append_audit_log(
            "operator_changed",
            {"previous": previous, "current": self._operator_name},
        )
        self._save_persistent_history()
        self.set_status(f"Operator set to {self._operator_name}")

    def on_save_import_export_template(self) -> None:
        default_name = "Default"
        if isinstance(self._institution_template, dict):
            default_name = str(self._institution_template.get("name", default_name) or default_name)
        elif self.product_scenario is not None:
            default_name = str(self.product_scenario.metadata.name or default_name)
        institution, ok = QInputDialog.getText(
            self,
            "Save Import/Export Template",
            "Institution/profile name:",
            text=default_name,
        )
        if not ok:
            return
        payload = {
            "institution_name": str(institution or "").strip() or default_name,
            "operator_name": str(self._operator_name),
            "import_mapping": dict(self._last_import_mapping or {}),
            "group_separator": str(self._last_group_separator or ";"),
        }
        try:
            save_import_export_template_profile(
                self._import_export_template_path,
                institution_name=str(payload["institution_name"]),
                template=payload,
            )
            self._append_audit_log(
                "import_export_template_saved",
                {
                    "institution_name": str(payload["institution_name"]),
                    "path": str(self._import_export_template_path),
                },
            )
            self._save_persistent_history()
            self.set_status(
                "Import/export template saved to "
                f"{self._import_export_template_path} for {payload['institution_name']}"
            )
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Template error", str(exc))

    def on_load_import_export_template(self) -> None:
        try:
            profiles = list_import_export_template_profiles(self._import_export_template_path)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Template error", str(exc))
            return
        if not profiles:
            QMessageBox.information(
                self,
                "Import/Export Templates",
                "No saved import/export template profiles were found yet.",
            )
            return
        choice, ok = QInputDialog.getItem(
            self,
            "Load Import/Export Template",
            "Institution/profile:",
            profiles,
            0,
            False,
        )
        if not ok:
            return
        try:
            payload = load_import_export_template_profile(
                self._import_export_template_path,
                institution_name=str(choice),
            )
            self._last_import_mapping = {
                str(k): str(v)
                for k, v in dict(payload.get("import_mapping", {}) or {}).items()
            }
            self._last_group_separator = str(
                payload.get("group_separator", self._last_group_separator) or self._last_group_separator
            )
            self._append_audit_log(
                "import_export_template_loaded",
                {
                    "institution_name": str(choice),
                    "path": str(self._import_export_template_path),
                },
            )
            self._save_persistent_history()
            self.set_status(f"Import/export template loaded for {choice}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Template error", str(exc))

    def on_save_named_branch(self) -> None:
        if not self.current_schedule:
            self.set_status("No schedule to branch")
            return
        dlg = BranchMetadataDialog(
            self,
            title="Save Named Branch",
            default_name=self._active_branch_name or "",
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, description = dlg.values()
        branch = create_branch(
            name=str(name),
            author=str(self._operator_name),
            description=str(description),
            base_schedule=self.base_schedule or self.current_schedule,
            current_schedule=self.current_schedule,
        )
        self._branches[str(name)] = dict(branch)
        self._active_branch_name = str(name)
        self._refresh_history_view()
        self._append_audit_log("named_branch_saved", {"name": str(name)})
        self._save_persistent_history()
        self.set_status(f"Saved named branch {name}")

    def on_load_named_branch(self) -> None:
        if not self._branches:
            self.set_status("No named branches available")
            return
        names = sorted(self._branches.keys())
        choice, ok = QInputDialog.getItem(
            self,
            "Load Named Branch",
            "Branch:",
            names,
            0,
            False,
        )
        if not ok:
            return
        branch = self._branches.get(str(choice))
        if not isinstance(branch, dict):
            return
        self._push_undo_state()
        self.current_schedule = {
            int(a_id): dict(info)
            for a_id, info in dict(branch.get("current_schedule", {}) or {}).items()
            if isinstance(info, dict)
        }
        self._active_branch_name = str(choice)
        self._bump_schedule_revision()
        self.update_table()
        self.update_quality_summary()
        self._refresh_history_view()
        self._refresh_history_buttons()
        self._append_audit_log("named_branch_loaded", {"name": str(choice)})
        self.set_status(f"Loaded branch {choice}")

    def on_branch_merge_assistance(self) -> None:
        if not self._branches:
            self.set_status("No named branches available")
            return
        names = sorted(self._branches.keys())
        choice, ok = QInputDialog.getItem(
            self,
            "Branch Merge Assistance",
            "Branch:",
            names,
            0,
            False,
        )
        if not ok:
            return
        branch = self._branches.get(str(choice))
        if not isinstance(branch, dict):
            return
        summary = branch_merge_assistance(branch, self.current_schedule or {})
        branch.setdefault("merge_notes", []).append(
            {
                "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
                "target_branch": str(choice),
                "summary": dict(summary),
            }
        )
        self._branches[str(choice)] = dict(branch)
        self._append_audit_log(
            "branch_merge_assistance_prepared",
            {
                "branch": str(choice),
                "changed_time": int(summary.get("changed_time", 0)),
                "changed_room": int(summary.get("changed_room", 0)),
                "changed_staff": int(summary.get("changed_staff", 0)),
            },
        )
        self._save_persistent_history()
        QMessageBox.information(
            self,
            "Branch Merge Assistance",
            "\n".join(
                [
                    str(summary.get("merge_message", "")),
                    f"Missing in target: {len(summary.get('missing_in_other', []))}",
                    f"Missing in branch: {len(summary.get('missing_in_base', []))}",
                ]
            ),
        )
        self.set_status(f"Merge assistance prepared for branch {choice}")

    def on_create_release_candidate(self) -> None:
        if not self.current_schedule:
            self.set_status("No schedule to release")
            return
        dlg = BranchMetadataDialog(self, title="Create Release Candidate", default_name="rc-1")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, notes = dlg.values()
        candidate = create_release_candidate(
            name=str(name),
            author=str(self._operator_name),
            schedule=self.current_schedule,
            notes=str(notes),
        )
        self._release_candidates[str(name)] = dict(candidate)
        self._refresh_history_view()
        self._append_audit_log("release_candidate_created", {"name": str(name)})
        self._save_persistent_history()
        self.set_status(f"Release candidate {name} created")

    def on_publish_release_candidate(self) -> None:
        if not self._release_candidates:
            self.set_status("No release candidates available")
            return
        names = sorted(self._release_candidates.keys())
        choice, ok = QInputDialog.getItem(
            self,
            "Publish Release Candidate",
            "Candidate:",
            names,
            0,
            False,
        )
        if not ok:
            return
        if bool(self._protected_baseline.get("protected", False)):
            approval = self._require_approval(
                action="publish_protected_baseline",
                details={"candidate": str(choice)},
            )
            if approval is None:
                self.set_status("Publish canceled: approval not granted")
                return
        candidate = publish_release_candidate(self._release_candidates[str(choice)])
        self._release_candidates[str(choice)] = dict(candidate)
        self._published_release_id = str(choice)
        self.base_schedule = {
            int(a_id): dict(info)
            for a_id, info in dict(candidate.get("schedule", {}) or {}).items()
            if isinstance(info, dict)
        }
        self._protected_baseline = protect_baseline_state(
            protected=True,
            actor=str(self._operator_name),
            reason=f"Published release candidate {choice}",
        )
        self._set_manual_highlight_base(self.base_schedule)
        self._append_audit_log("release_candidate_published", {"name": str(choice)})
        self._refresh_history_view()
        self._save_persistent_history()
        self.set_status(f"Published release candidate {choice}")

    def on_toggle_protected_baseline(self) -> None:
        target = not bool(self._protected_baseline.get("protected", False))
        approval = self._require_approval(
            action="toggle_protected_baseline",
            details={"target": bool(target)},
        )
        if approval is None:
            self.set_status("Protected baseline change canceled")
            return
        self._protected_baseline = protect_baseline_state(
            protected=bool(target),
            actor=str(self._operator_name),
            reason=str(approval.get("reason", "")),
        )
        state = "enabled" if bool(target) else "disabled"
        self._append_audit_log("protected_baseline_toggled", {"state": str(state)})
        self._save_persistent_history()
        self.set_status(f"Protected baseline {state}")

    def on_export_calendar_sync_bundle(self) -> None:
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to export")
            return
        folder = QFileDialog.getExistingDirectory(
            self,
            "Export calendar sync bundle",
            "",
        )
        if not folder:
            return
        try:
            manifest = export_calendar_feeds(self.inst, self.current_schedule, folder)
            bundle = build_calendar_sync_bundle(
                manifest,
                base_url=str(self._effective_branding().get("website_url", "")),
            )
            out_path = os.path.join(folder, "calendar_sync_bundle.json")
            write_calendar_sync_bundle(out_path, bundle)
            self._append_audit_log(
                "calendar_sync_bundle_exported",
                {"path": str(out_path), "feeds": int(sum(len(v) for v in dict(manifest.get("feeds", {}) or {}).values()))},
            )
            self.set_status(f"Calendar sync bundle exported to {out_path}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Sync export error", str(exc))

    def on_load_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load project",
            "",
            "Project (*.json *.pkl *.db *.sqlite)",
        )
        if not path:
            return

        try:
            self.set_status("Loading project...")
            inst, schedule, _meta = load_legacy_project(path)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Load error", str(e))
            self.set_status("Load error")
            return

        self.inst = inst
        self.locked_activities = dict(getattr(inst, "locked_activities", {}) or {})
        self.base_schedule = schedule
        self.current_schedule = {a_id: info.copy() for a_id, info in schedule.items()}
        if isinstance(_meta, dict):
            self._operator_name = str(_meta.get("operator_name", self._operator_name) or self._operator_name)
            self._branches = {
                str(name): dict(branch)
                for name, branch in dict(_meta.get("branches", {}) or {}).items()
                if isinstance(branch, dict)
            }
            active_branch = _meta.get("active_branch_name")
            self._active_branch_name = str(active_branch) if active_branch else None
            self._release_candidates = {
                str(name): dict(candidate)
                for name, candidate in dict(_meta.get("release_candidates", {}) or {}).items()
                if isinstance(candidate, dict)
            }
            published = _meta.get("published_release_id")
            self._published_release_id = str(published) if published else None
            self._protected_baseline = dict(_meta.get("protected_baseline", self._protected_baseline) or {})
            self._workspace_change_log = [
                dict(row)
                for row in list(_meta.get("change_history", []) or [])
                if isinstance(row, dict)
            ][-200:]
            self._import_export_template_path = str(
                _meta.get(
                    "import_export_template_store_path",
                    self._import_export_template_path,
                )
                or self._import_export_template_path
            )
            self._branding_profile = ensure_branding_profile(
                dict(_meta.get("branding_profile", self._branding_profile) or {})
            )
            self._runtime_settings = save_runtime_settings(
                self._runtime_paths["settings"],
                dict(_meta.get("runtime_settings", self._runtime_settings) or {}),
            )
            self._last_import_mapping = {
                str(k): str(v)
                for k, v in dict(_meta.get("last_import_mapping", {}) or {}).items()
            }
            self._last_group_separator = str(_meta.get("last_group_separator", self._last_group_separator) or self._last_group_separator)
        self._set_manual_highlight_base(self.current_schedule)
        self.held_activity_id = None
        self._bump_schedule_revision()
        self._reset_history()
        self._load_constraint_controls_from_instance(self.inst)
        self._refresh_product_scenario_from_instance()

        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self._apply_branding_profile()
        self._refresh_history_view()
        self._refresh_history_buttons()
        self.set_status(f"Loaded {path}")
        self._append_audit_log("project_loaded", {"path": str(path)})
        self._save_persistent_history()

    def on_load_product_scenario(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Load {APP_SHORT_NAME} product scenario",
            "",
            "Product Scenario (*.json)",
        )
        if not path:
            return
        try:
            self.set_status("Loading product scenario...")
            scenario = load_product_scenario(path)
            inst = compile_scenario_instance(scenario)
            self.product_scenario = scenario
            self.inst = inst
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Load error", str(exc))
            self.set_status("Load error")
            return

        self.locked_activities = dict(getattr(inst, "locked_activities", {}) or {})
        self.base_schedule = {}
        self._set_manual_highlight_base({})
        self.current_schedule = {}
        self.held_activity_id = None
        self._bump_schedule_revision()
        self._reset_history()
        self._load_constraint_controls_from_instance(self.inst)
        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self.set_status(f"Loaded product scenario {path}")
        self._append_audit_log("product_scenario_loaded", {"path": str(path)})
        self._save_persistent_history()

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
            inst, schedule, _meta = load_legacy_project(path)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Compare error", str(e))
            self.set_status("Compare error")
            return

        summary = compare_schedule_sets(self.current_schedule, schedule)
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

    def _search_result_rows(self, scope: str, query: str) -> List[List[Any]]:
        rows: List[List[Any]] = []
        needle = str(query or "").strip().lower()
        if self.inst is None:
            return rows

        def _match(*parts: Any) -> bool:
            haystack = " ".join(str(part) for part in parts if part is not None).lower()
            return (not needle) or (needle in haystack)

        include_all = str(scope).lower() == "all"
        if include_all or str(scope).lower() == "activities":
            if self.current_schedule:
                source = self.current_schedule
            else:
                source = {
                    int(a_id): {
                        "week": int(act.week),
                        "day": "-",
                        "slot": 0,
                        "duration": int(act.duration),
                        "room_id": None,
                        "staff_id": int(act.prof_id if act.kind == "LEC" else act.ta_id),
                        "course_id": int(act.course_id),
                        "group_ids": list(act.group_ids),
                        "kind": str(act.kind),
                    }
                    for a_id, act in self.inst.activities.items()
                }
            for a_id, info in source.items():
                title = self._activity_title(int(a_id), source)
                if str(info.get("day")) == "-":
                    detail = f"W{int(info['week'])} unscheduled"
                else:
                    detail = f"W{int(info['week'])} {info['day']} S{int(info['slot']) + 1}"
                if _match(title, detail, info.get("kind"), info.get("course_id")):
                    rows.append(
                        [
                            "Activity",
                            title,
                            detail,
                            {"kind": "activity", "activity_id": int(a_id)},
                        ]
                    )
        if include_all or str(scope).lower() == "staff":
            for s_id, staff in self.inst.staff.items():
                if _match(staff.name, "Professor" if staff.is_prof else "TA", s_id):
                    rows.append(
                        [
                            "Staff",
                            str(staff.name),
                            f"{'Professor' if staff.is_prof else 'TA'} | id {int(s_id)}",
                            {"kind": "staff", "staff_id": int(s_id)},
                        ]
                    )
        if include_all or str(scope).lower() == "rooms":
            for room_id, room in self.inst.rooms.items():
                if _match(room.name, room.campus, room.building, room.floor, room.room_type):
                    detail = f"{room.room_type} | {room.campus}/{room.building}/{room.floor or '-'}"
                    rows.append(
                        [
                            "Room",
                            str(room.name),
                            detail,
                            {"kind": "room", "room_id": int(room_id)},
                        ]
                    )
        if include_all or str(scope).lower() == "conflicts":
            for error in self._collect_conflict_errors():
                if not _match(error):
                    continue
                activity_id = None
                matches = re.findall(r"\bA(\d+)\b", str(error))
                if matches:
                    activity_id = int(matches[0])
                rows.append(
                    [
                        "Conflict",
                        f"A{activity_id}" if activity_id is not None else "-",
                        str(error),
                        {"kind": "conflict", "activity_id": activity_id},
                    ]
                )
        return rows

    def _apply_search_result(self, payload: Dict[str, Any]) -> None:
        kind = str(payload.get("kind", ""))
        if kind in {"activity", "conflict"}:
            activity_id = payload.get("activity_id")
            if activity_id is not None and self._jump_to_activity(int(activity_id)):
                self.set_status(f"Jumped to A{int(activity_id)}")
                return
        if kind == "staff":
            self.view_type_combo.setCurrentText("Staff")
            idx = self.entity_combo.findData(int(payload.get("staff_id", -1)))
            if idx >= 0:
                self.entity_combo.setCurrentIndex(idx)
            self.set_status("Filtered to selected staff member")
            return
        if kind == "room":
            self.view_type_combo.setCurrentText("Room")
            idx = self.entity_combo.findData(int(payload.get("room_id", -1)))
            if idx >= 0:
                self.entity_combo.setCurrentIndex(idx)
            self.set_status("Filtered to selected room")
            return
        self.set_status("No matching jump target")

    def on_run_search(self) -> None:
        if self.inst is None:
            self.set_status("Generate or load an instance first")
            return
        query = str(self.search_edit.text() or "").strip()
        scope = str(self.search_scope_combo.currentText() or "All")
        rows = self._search_result_rows(scope, query)
        dlg = SearchResultsDialog(
            self,
            ["Scope", "Label", "Detail", "__payload__"],
            rows,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        payload = dlg.selected_payload()
        if payload:
            self._apply_search_result(payload)

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
        self._bump_schedule_revision()
        self._reset_history()
        self._load_constraint_controls_from_instance(self.inst)
        self._refresh_product_scenario_from_instance()
        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self.set_status(f"Loaded instance {path}")
        self._append_audit_log("instance_loaded", {"path": str(path)})
        self._save_persistent_history()

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
        self._load_validated_schedule(schedule, source=str(path))

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

            if self._conflict_ids_cache_revision != int(self._schedule_revision):
                self._conflict_ids_cache = self._compute_conflicting_activity_ids(
                    self.current_schedule
                )
                self._conflict_ids_cache_revision = int(self._schedule_revision)
            conflict_ids = set(self._conflict_ids_cache)
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
            held_week_ok = held_id is not None
            held_target_map: Dict[Tuple[str, int], bool] = {}
            held_base_score: int | None = None
            held_delta_map: Dict[Tuple[str, int], int] = {}
            show_score_deltas = bool(
                hasattr(self, "show_score_deltas_cb") and self.show_score_deltas_cb.isChecked()
            )
            if held_week_ok:
                self._held_move_analysis_map = self._held_move_analysis_from_cache(
                    int(week),
                    compute_scores=bool(show_score_deltas),
                    include_conflicts=False,
                )
                if not self._held_move_analysis_map:
                    self._held_move_analysis_map = self._held_move_analysis_from_cache(
                        int(week),
                        compute_scores=False,
                        include_conflicts=False,
                    )
                    if not self._held_move_analysis_map:
                        # Paint valid/blocked targets immediately. Global score
                        # deltas are computed asynchronously because they are
                        # expensive on large schedules.
                        self._held_move_analysis_map = self._build_held_move_analysis(
                            int(week),
                            compute_scores=False,
                            include_conflicts=False,
                        )
                    if show_score_deltas:
                        self._request_held_move_analysis_async(
                            int(week),
                            compute_scores=True,
                            include_conflicts=False,
                        )
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

            color_held = QColor("#1565c0")
            color_valid_target = QColor("#087f5b")
            color_valid_target_better = QColor("#0ca678")
            color_valid_target_worse = QColor("#f08c00")
            color_conflict_target = QColor("#ffd43b")
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
                            if not text:
                                text = "VALID TARGET"
                            elif "VALID TARGET" not in text and "BETTER" not in text and "WORSE" not in text:
                                text = f"VALID TARGET\n{text}"
                            item.setText(text)
                            if isinstance(delta_here, int) and delta_here < 0:
                                item.setBackground(QBrush(color_valid_target_better))
                            elif isinstance(delta_here, int) and delta_here > 0:
                                item.setBackground(QBrush(color_valid_target_worse))
                            else:
                                item.setBackground(QBrush(color_valid_target))
                        elif analysis is not None and not bool(analysis.get("ok", False)):
                            if not text:
                                text = "BLOCKED"
                            elif "BLOCKED" not in text:
                                text = f"BLOCKED\n{text}"
                            item.setText(text)
                            item.setForeground(QBrush(QColor("#111111")))
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
            "same_kind_week": 3,
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
        W_SAME_KIND_WEEK = weights["same_kind_week"]

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

                same_kind_counts: Dict[Tuple[int, str], int] = {}
                for info in schedule.values():
                    if int(info.get("week")) != int(w):
                        continue
                    if int(g_id) not in set(int(x) for x in info.get("group_ids", [])):
                        continue
                    kind = str(info.get("kind", ""))
                    if kind not in ("LEC", "TUT"):
                        continue
                    key = (int(info.get("course_id", -1)), kind)
                    same_kind_counts[key] = int(same_kind_counts.get(key, 0)) + 1
                for cnt in same_kind_counts.values():
                    if int(cnt) > 1:
                        pen += int(W_SAME_KIND_WEEK) * int(cnt - 1)

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
            self._update_fairness_dashboard()
            self._update_diagnostics_dashboard()
            return

        hard_conflicts = 0
        global_penalty = None
        breakdown: Dict[str, int] = {}
        sla_summary: Dict[str, Any] = {}
        try:
            breakdown = compute_penalty_breakdown(self.inst, self.current_schedule)
            global_penalty = int(breakdown.get("total", 0))
        except Exception:
            global_penalty = None
            breakdown = {}
        try:
            hard_conflicts = len(self._collect_conflict_errors())
        except Exception:
            hard_conflicts = 0
        try:
            sla_summary = evaluate_schedule_sla(
                self.inst,
                self.current_schedule,
                hard_conflicts=int(hard_conflicts),
            )
        except Exception:
            sla_summary = {}

        penalties = self.compute_group_penalties(self.current_schedule)
        if not penalties:
            self.quality_label.setText("")
            self._update_diagnostics_dashboard()
            return

        header_parts: List[str] = []
        if global_penalty is not None:
            header_parts.append(f"Global soft penalty: {global_penalty}")
        header_parts.append(f"Hard conflicts: {hard_conflicts}")
        header_parts.append(
            f"Profile: {self.objective_profile_combo.currentText()}"
        )
        cp_bound_summary = self._cp_bound_summary_from_meta()
        if cp_bound_summary:
            header_parts.append(cp_bound_summary)
        if isinstance(sla_summary, dict) and sla_summary:
            if bool(sla_summary.get("passed", True)):
                header_parts.append("SLA: pass")
            else:
                violations = ", ".join(str(v) for v in (sla_summary.get("violations") or []))
                header_parts.append(f"SLA: fail ({violations or 'thresholds'})")
        if self.held_activity_id is not None:
            header_parts.append(f"Held: A{self.held_activity_id}")

        detail_parts: List[str] = []
        if breakdown:
            top_terms = [
                (key, int(value))
                for key, value in breakdown.items()
                if key != "total" and int(value) > 0
            ]
            top_terms.sort(key=lambda item: item[1], reverse=True)
            if top_terms:
                detail_parts.append(
                    "Top penalty drivers: "
                    + " | ".join(f"{key}={value}" for key, value in top_terms[:4])
                )
        if self.base_schedule and self.current_schedule != self.base_schedule:
            try:
                detail_parts.append(
                    explain_solution_ranking(
                        self.inst,
                        self.base_schedule,
                        self.current_schedule,
                        base_label="base",
                        candidate_label="current",
                    )
                )
            except Exception:
                pass

        parts: List[str] = []
        for g_id in sorted(self.inst.groups.keys()):
            pen = penalties.get(g_id, 0)
            g = self.inst.groups[g_id]
            status = self.classify_group_quality(pen)
            parts.append(f"{g.name}: {pen} ({status})")

        lines = [" | ".join(header_parts)]
        lines.extend(detail_parts)
        lines.append("Group quality:")
        lines.append(" | ".join(parts))
        text = "\n".join(line for line in lines if line)
        self.quality_label.setText(text)
        self._update_fairness_dashboard()
        self._update_diagnostics_dashboard()

    def _update_fairness_dashboard(self) -> None:
        if not hasattr(self, "fairness_group_table") or not hasattr(
            self, "fairness_staff_table"
        ):
            return
        if self.inst is None or not self.current_schedule:
            self.fairness_group_model.set_table(self.fairness_group_model._headers, [])
            self.fairness_staff_model.set_table(self.fairness_staff_model._headers, [])
            self.fairness_summary_label.setText(
                "Generate/solve to view fairness dashboard."
            )
            return
        try:
            dashboard = compute_fairness_dashboard(self.inst, self.current_schedule)
        except Exception as exc:
            self.fairness_summary_label.setText(
                f"Fairness dashboard unavailable: {exc}"
            )
            return

        group_rows = list(dashboard.get("groups", []))
        staff_rows = list(dashboard.get("staff", []))
        self.fairness_group_model.set_table(
            self.fairness_group_model._headers,
            [
                [
                    str(row.get("name", "")),
                    int(row.get("total_slots", 0)),
                    int(row.get("active_days", 0)),
                    int(row.get("single_days", 0)),
                    int(row.get("gap_slots", 0)),
                    int(row.get("late_events", 0)),
                    float(row.get("avg_weekly_load", 0.0)),
                    float(row.get("fairness_score", 0.0)),
                ]
                for row in group_rows
            ],
        )
        self.fairness_staff_model.set_table(
            self.fairness_staff_model._headers,
            [
                [
                    str(row.get("name", "")),
                    str(row.get("role", "")),
                    int(row.get("total_slots", 0)),
                    int(row.get("active_days", 0)),
                    int(row.get("single_days", 0)),
                    int(row.get("gap_slots", 0)),
                    int(row.get("late_events", 0)),
                    float(row.get("avg_weekly_load", 0.0)),
                    float(row.get("fairness_score", 0.0)),
                ]
                for row in staff_rows
            ],
        )

        summary = dashboard.get("summary", {})
        g_sum = summary.get("groups", {}) if isinstance(summary, dict) else {}
        s_sum = summary.get("staff", {}) if isinstance(summary, dict) else {}
        self.fairness_summary_label.setText(
            "Fairness summary | "
            f"Groups mean score: {float(g_sum.get('mean_fairness_score', 0.0)):.2f} | "
            f"Staff mean score: {float(s_sum.get('mean_fairness_score', 0.0)):.2f}"
        )

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

            (
                a_id,
                new_week,
                new_day,
                new_slot,
                new_room,
                new_staff,
                lock_time,
                lock_room,
                admin_note,
            ) = dlg.get_values()
            ok, reason = self.check_move(
                a_id, new_day, new_slot, new_room, new_staff, int(new_week)
            )
            if not ok:
                QMessageBox.warning(self, "Invalid move", reason)
                return

            self._push_undo_state()
            updated_schedule = self._clone_schedule()
            info = updated_schedule[a_id]
            info["week"] = int(new_week)
            info["day"] = new_day
            info["slot"] = new_slot
            info["room_id"] = new_room
            info["staff_id"] = new_staff
            if str(admin_note).strip():
                info["admin_note"] = str(admin_note).strip()
            else:
                info.pop("admin_note", None)

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
        new_week: int | None = None,
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
        try:
            w = int(info["week"]) if new_week is None else int(new_week)
        except Exception:
            return False, "Invalid week."
        week_set = {int(x) for x in inst.weeks}
        if int(w) not in week_set:
            return False, "Unknown week."
        dur = int(info["duration"])
        groups = info["group_ids"]
        group_set = {int(g) for g in groups}
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

        if calendar_slot_blocked(inst, week=int(w), day=str(new_day)):
            return False, "Target day is blocked by calendar blackout/holiday rules."

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
        allowed_weeks = getattr(staff, "available_weeks", None)
        if allowed_weeks is not None:
            allowed_week_set = {int(v) for v in allowed_weeks}
            if allowed_week_set and int(w) not in allowed_week_set:
                return False, "Staff unavailable in that week."

        day_load = 0
        week_load = 0
        for b_id, b in schedule.items():
            if b_id == a_id:
                continue
            if b["staff_id"] != new_staff_id:
                continue
            if int(b["week"]) == int(w):
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
        total_students = sum(inst.groups[int(g)].size for g in groups)
        if room.capacity < total_students:
            return False, "Room capacity too small."
        if not room_is_available(
            inst,
            int(new_room_id),
            week=int(w),
            day=str(new_day),
            start_slot=int(new_slot),
            dur=int(dur),
        ):
            return False, "Room unavailable at that day/slot."
        if not generic_resources_available(
            inst,
            getattr(act, "resource_ids", []) or [],
            day=str(new_day),
            start_slot=int(new_slot),
            dur=int(dur),
        ):
            return False, "Generic resource unavailable at that day/slot."

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

        if _flag("force_repeat_weekly_pattern", False) and inst.weeks:
            first_week = min(int(wk) for wk in inst.weeks)
            if int(w) != int(first_week):
                repeat_key = (
                    int(act.course_id),
                    str(act.kind),
                    int(new_staff_id),
                    tuple(sorted(int(g) for g in groups)),
                    int(dur),
                )
                for b_id, b in schedule.items():
                    if int(b_id) == int(a_id):
                        continue
                    other_act = inst.activities.get(int(b_id))
                    if other_act is None:
                        continue
                    if int(b.get("week", 0)) == int(first_week):
                        continue
                    other_key = (
                        int(other_act.course_id),
                        str(other_act.kind),
                        int(b.get("staff_id", -1)),
                        tuple(sorted(int(g) for g in (b.get("group_ids", []) or []))),
                        int(b.get("duration", 1)),
                    )
                    if other_key != repeat_key:
                        continue
                    if (
                        str(b.get("day")) != str(new_day)
                        or int(b.get("slot", -1)) != int(new_slot)
                        or int(b.get("room_id", -1)) != int(new_room_id)
                    ):
                        return (
                            False,
                            f"Repeat weekly pattern requires matching A{b_id} "
                            "to use the same day, slot, and room.",
                        )

        new_slots = set(range(int(new_slot), int(new_slot) + int(dur)))
        for b_id, b in schedule.items():
            if b_id == a_id:
                continue
            if int(b["week"]) != int(w) or b["day"] != new_day:
                continue
            other_slots = set(range(b["slot"], b["slot"] + b["duration"]))
            if not (new_slots & other_slots):
                continue
            if b["staff_id"] == new_staff_id:
                return False, f"Staff conflict with A{b_id}."
            if b["room_id"] == new_room_id:
                return False, f"Room conflict with A{b_id}."
            if any(int(g) in group_set for g in b["group_ids"]):
                return False, f"Group conflict with A{b_id}."

        trial = {int(k): dict(v) for k, v in schedule.items()}
        trial[int(a_id)] = {
            **trial[int(a_id)],
            "week": int(w),
            "day": str(new_day),
            "slot": int(new_slot),
            "room_id": int(new_room_id),
            "staff_id": int(new_staff_id),
        }
        precedence_errors = precedence_violations(inst, trial)
        if precedence_errors:
            return False, str(precedence_errors[0])
        travel_errors = travel_buffer_violations(inst, trial)
        if travel_errors:
            return False, str(travel_errors[0])
        resource_errors = generic_resource_violations(inst, trial)
        if resource_errors:
            return False, str(resource_errors[0])

        return True, ""


def main():
    app = QApplication(sys.argv)
    icon_path = _app_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
