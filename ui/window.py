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
    QCheckBox,
    QToolButton,
    QMenu,
    QSizePolicy,
    QHeaderView,
    QTabWidget,
    QSplitter,
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
from services.engine_backend import (
    INTERACTIVE_IMPROVE_ITERATIONS,
    INTERACTIVE_IMPROVE_SECONDS,
    INTERACTIVE_OBJECTIVE_PROFILE,
    INTERACTIVE_SOLVE_SECONDS,
)
from services.ui_contract import (
    generator_mode_for_scenario,
    run_mode_options,
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
from ui.styles import DARK_STYLE, LIGHT_STYLE
from ui.tutorial import TutorialDialog
from ui.table_items import NaturalSortTableItem, NumericTableItem, StepSpinBox
from ui.widgets import ScheduleItemDelegate, ScheduleTableWidget, StatusToast
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


from ui.window_helpers import WindowHelpersMixin
from ui.window_generation import WindowGenerationMixin
from ui.window_history import WindowHistoryMixin
from ui.window_repair import WindowRepairMixin
from ui.window_solver import WindowSolverMixin
from ui.window_io import WindowIOMixin

class MainWindow(
    WindowHelpersMixin,
    WindowGenerationMixin,
    WindowHistoryMixin,
    WindowRepairMixin,
    WindowSolverMixin,
    WindowIOMixin,
    QMainWindow,
):
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
        self._last_toast_text: str = self._status_full_text
        self._live_improve_mode: bool = False
        self._improve_running: bool = False
        self._improve_stop_requested: bool = False
        self._solver_safe_retry_used: bool = False
        self._last_solver_keep_locks: bool = False
        self._maximize_on_first_show: bool = True
        self.tmp_inst_path: str | None = None
        self.tmp_res_path: str | None = None
        self.tmp_solver_dir: str | None = None
        self._room_table_internal_change = False
        self._custom_program_table_internal_change = False
        self._custom_course_pattern_table_internal_change = False
        self.backend_client = create_backend_client(
            backend_url=os.getenv("PLANORA_BACKEND_URL", "").strip() or None,
            bearer_token=os.getenv("PLANORA_BACKEND_TOKEN", "").strip() or None,
        )
        self._ui_contract: Dict[str, Any] = self._load_backend_ui_contract()
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
        self._theme_mode = str(
            dict(self._runtime_settings.get("ui_preferences", {}) or {}).get(
                "theme", "light"
            )
        )
        if self._theme_mode not in {"light", "dark"}:
            self._theme_mode = "light"
        self._thread_pool = QThreadPool.globalInstance()
        self._held_analysis_async_key: Tuple[Any, ...] | None = None
        self._improve_thread: QThread | None = None
        self._improve_worker: ImproveWorker | None = None
        self._improve_original_schedule: Dict[int, Dict[str, Any]] | None = None
        self._improve_total_iters: int = 0
        self._improve_base_penalty: int | None = None
        self._improve_focus_term: str = ""
        self._active_solve_worker: FunctionWorker | None = None
        self._tutorial_checked = False

        self._build_ui()
        self._connect_signals()
        self._load_templates()
        self._load_persistent_history()
        self._load_ui_control_preferences()
        self._apply_branding_profile()
        self._append_audit_log("app_started", {"window": self.windowTitle()})

    # ----- UI setup -----

    def _load_backend_ui_contract(self) -> Dict[str, Any]:
        try:
            capabilities = self.backend_client.capabilities()
        except Exception as exc:
            if os.getenv("PLANORA_BACKEND_URL", "").strip():
                raise RuntimeError(
                    "The configured Planora backend could not be reached or authenticated. "
                    "Set PLANORA_BACKEND_TOKEN to a valid bearer token and try again."
                ) from exc
            raise
        contract = capabilities.get("ui_contract")
        if not isinstance(contract, dict):
            raise RuntimeError("The Planora backend did not provide a UI contract.")
        if str(contract.get("contract_version") or "") != "planora.ui.v1":
            raise RuntimeError(
                "This Planora desktop requires backend UI contract planora.ui.v1."
            )
        if not contract.get("scenarios") or not contract.get("run_modes"):
            raise RuntimeError("The Planora backend UI contract is incomplete.")
        return dict(contract)

    def _build_ui(self):
        self.top_widget = QWidget()
        top_layout = QVBoxLayout(self.top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)

        self.mode_combo = QComboBox()
        for mode in (
            "small_demo",
            "giu_target",
            "ss23_uni_like",
            "custom",
            "block_profs",
            "labs_only",
            "mixed_large",
            "random",
            "target_case",
        ):
            self.mode_combo.addItem(mode, mode)
        self.mode_combo.setVisible(False)

        self.scenario_combo = QComboBox()
        shared_ui_contract = self._ui_contract
        for scenario in shared_ui_contract["scenarios"]:
            self.scenario_combo.addItem(str(scenario["label"]), str(scenario["id"]))

        self.run_mode_combo = QComboBox()
        recommended_mode = "balanced"
        for run_mode in shared_ui_contract["run_modes"]:
            self.run_mode_combo.addItem(str(run_mode["label"]), str(run_mode["id"]))
            if bool(run_mode.get("recommended")):
                recommended_mode = str(run_mode["id"])
        recommended_index = self.run_mode_combo.findData(recommended_mode)
        self.run_mode_combo.setCurrentIndex(max(0, recommended_index))

        self.generate_button = QPushButton("Open data")
        self.solve_button = QPushButton("Build schedule")
        self.clear_locks_button = QPushButton("Clear Locks")
        self.improve_button = QPushButton("Improve")
        self.stop_improve_button = QPushButton("Stop improvement")
        self.stop_improve_button.setEnabled(False)
        self.stop_improve_button.setVisible(False)
        self.undo_button = QPushButton("Undo")
        self.redo_button = QPushButton("Redo")
        self.revert_button = QPushButton("Revert Base")
        self.conflicts_button = QPushButton("Validate")
        self.publish_button = QPushButton("Publish")
        self.publish_button.setObjectName("publishButton")
        self.tutorial_button = QPushButton("How it works")
        self.tutorial_button.setObjectName("quietButton")

        self.room_mode_combo = QComboBox()
        self.room_mode_combo.addItem("Auto", "auto")
        self.room_mode_combo.addItem("Scale (Adaptive week partitions)", "partitioned")
        self.room_mode_combo.addItem("Research (Certificate decomposition)", "decomposed")
        self.room_mode_combo.addItem("Strict (CP rooms)", "cp_rooms")
        self.room_mode_combo.addItem("Fast (Greedy rooms)", "greedy")
        interactive_room_idx = self.room_mode_combo.findData("partitioned")
        self.room_mode_combo.setCurrentIndex(
            interactive_room_idx if interactive_room_idx >= 0 else 0
        )

        self.objective_cb = QCheckBox("Use CP objective")
        self.objective_cb.setChecked(False)
        self.debug_diagnostics_cb = QCheckBox("Debug diagnostics")
        self.debug_diagnostics_cb.setChecked(
            str(os.getenv("PLANORA_SOLVER_DEBUG", "")).strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self.objective_profile_combo = QComboBox()
        for profile_id, label in available_objective_profiles():
            self.objective_profile_combo.addItem(str(label), str(profile_id))
        interactive_idx = self.objective_profile_combo.findData(
            INTERACTIVE_OBJECTIVE_PROFILE
        )
        if interactive_idx >= 0:
            self.objective_profile_combo.setCurrentIndex(interactive_idx)

        self.time_limit_spin = StepSpinBox()
        self.time_limit_spin.setRange(5, 3600)
        self.time_limit_spin.setValue(int(INTERACTIVE_SOLVE_SECONDS))
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
        self.improve_runs_spin.setValue(INTERACTIVE_IMPROVE_ITERATIONS)
        self.improve_runs_spin.setMinimumWidth(90)
        self.improve_runs_spin.setMaximumWidth(130)

        self.ls_time_spin = StepSpinBox()
        self.ls_time_spin.setRange(0, 600)
        self.ls_time_spin.setValue(int(INTERACTIVE_IMPROVE_SECONDS))
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

        self.theme_button = QToolButton()
        self.theme_button.setObjectName("secondaryButton")
        self.theme_button.setMinimumWidth(82)
        self.theme_button.clicked.connect(self._toggle_theme)

        self.view_type_combo = QComboBox()
        self.view_type_combo.addItems(["Group", "Staff", "Room", "All"])
        self.entity_combo = QComboBox()
        self.week_combo = QComboBox()
        self.search_scope_combo = QComboBox()
        self.search_scope_combo.addItems(["Activities", "Staff", "Rooms", "Conflicts", "All"])
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search activities, staff, rooms, conflicts...")
        self.search_button = QPushButton("Search")

        self.status_toast = StatusToast()
        self.status_label = self.status_toast.message_label
        self.run_status_label = QLabel("Ready")
        self.run_status_label.setObjectName("runStatusLabel")
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

        self.app_header = QFrame()
        self.app_header.setObjectName("appHeader")
        brand_row = QHBoxLayout(self.app_header)
        brand_row.setContentsMargins(14, 9, 12, 9)
        brand_row.setSpacing(10)
        icon_path = _app_icon_path()
        if icon_path:
            brand_icon = QLabel()
            brand_icon.setObjectName("brandIcon")
            brand_icon.setPixmap(QIcon(icon_path).pixmap(40, 40))
            brand_icon.setFixedSize(44, 44)
            brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            brand_row.addWidget(brand_icon)
        brand_copy = QVBoxLayout()
        brand_copy.setSpacing(0)
        brand_title = QLabel("Planora")
        brand_title.setObjectName("brandTitle")
        brand_context = QLabel("ACADEMIC PLANNING / DRAFT TIMETABLE")
        brand_context.setObjectName("eyebrowLabel")
        brand_copy.addWidget(brand_title)
        brand_copy.addWidget(brand_context)
        brand_row.addLayout(brand_copy)
        brand_row.addStretch(1)
        brand_row.addWidget(self.tutorial_button)
        brand_row.addWidget(self.theme_button)
        brand_row.addWidget(self.project_menu_btn)
        brand_row.addWidget(self.export_menu_btn)
        top_layout.addWidget(self.app_header)

        # The normal workflow exposes only the meaningful scenario, run mode, and actions.
        self.command_bar = QFrame()
        self.command_bar.setObjectName("commandBar")
        row_actions = QHBoxLayout(self.command_bar)
        row_actions.setContentsMargins(10, 7, 10, 7)
        row_actions.setSpacing(7)
        action_widgets: List[QWidget] = [
            _pair_widget("Data:", self.scenario_combo),
            self.generate_button,
            _pair_widget("Run mode:", self.run_mode_combo),
            self.solve_button,
            self.improve_button,
            self.stop_improve_button,
            self.conflicts_button,
            self.publish_button,
        ]
        for widget in action_widgets:
            row_actions.addWidget(widget)
        row_actions.addStretch(1)
        top_layout.addWidget(self.command_bar)

        # Timetable view controls stay adjacent to the canvas.
        self.filter_bar = QFrame()
        self.filter_bar.setObjectName("filterBar")
        row_view = QHBoxLayout(self.filter_bar)
        row_view.setContentsMargins(10, 7, 10, 7)
        row_view.setSpacing(7)
        row_view.addWidget(_pair_widget("View:", self.view_type_combo))
        row_view.addWidget(self.entity_combo)
        row_view.addWidget(_pair_widget("Week:", self.week_combo))
        row_view.addWidget(_pair_widget("Search:", self.search_scope_combo))
        row_view.addWidget(self.search_edit)
        row_view.addWidget(self.search_button)
        top_layout.addWidget(self.filter_bar)

        # Emphasize primary admin controls and improve discoverability.
        self.improve_button.setMinimumWidth(92)
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
        self.run_status_label.setWordWrap(False)
        self.run_status_label.setMinimumWidth(240)
        self.run_status_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.run_status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
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
        self.table.setItemDelegate(ScheduleItemDelegate(self.table))
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
        # Keep headers fixed and use the table's native scrollbars. This avoids
        # competing nested scroll regions and lets wheel events bubble at bounds.
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.setObjectName("workspaceTabs")
        schedule_tab = QWidget()
        schedule_tab_layout = QVBoxLayout(schedule_tab)
        schedule_tab_layout.setContentsMargins(0, 0, 0, 0)
        schedule_tab_layout.setSpacing(0)

        self.blueprint_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.blueprint_splitter.setObjectName("blueprintSplitter")
        self.resource_panel = QFrame()
        self.resource_panel.setObjectName("resourcePanel")
        self.resource_panel.setMinimumWidth(0)
        resource_layout = QVBoxLayout(self.resource_panel)
        resource_layout.setContentsMargins(12, 14, 12, 14)
        resource_title = QLabel("RESOURCES")
        resource_title.setObjectName("eyebrowLabel")
        self.blueprint_resource_search = QLineEdit()
        self.blueprint_resource_search.setPlaceholderText("Find course, group, staff, room")
        self.blueprint_resource_list = QListWidget()
        self.blueprint_resource_list.setObjectName("resourceList")
        resource_layout.addWidget(resource_title)
        resource_layout.addWidget(self.blueprint_resource_search)
        resource_layout.addWidget(self.blueprint_resource_list, 1)
        self.blueprint_splitter.addWidget(self.resource_panel)

        schedule_center = QWidget()
        schedule_center.setObjectName("scheduleCanvas")
        schedule_layout = QVBoxLayout(schedule_center)
        schedule_layout.setContentsMargins(8, 8, 8, 8)
        schedule_layout.setSpacing(6)
        self.schedule_view_scroll = QScrollArea()
        self.schedule_view_scroll.setWidgetResizable(True)
        self.schedule_view_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.schedule_view_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.schedule_view_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.table.setExternalScrollArea(None)
        self.schedule_view_scroll.setWidget(self.table)
        schedule_layout.addWidget(self.status_toast, 0)
        schedule_layout.addWidget(self.schedule_view_scroll, 1)

        run_strip = QFrame()
        run_strip.setObjectName("runStrip")
        run_strip_layout = QHBoxLayout(run_strip)
        run_strip_layout.setContentsMargins(12, 7, 12, 7)
        run_strip_layout.setSpacing(10)
        run_strip_layout.addWidget(QLabel("CURRENT DRAFT"))
        run_strip_layout.addWidget(self.quality_label, 1)
        run_strip_layout.addWidget(self.run_status_label)
        schedule_layout.addWidget(run_strip)
        self.blueprint_splitter.addWidget(schedule_center)

        self.inspector_panel = QFrame()
        self.inspector_panel.setObjectName("inspectorPanel")
        self.inspector_panel.setMinimumWidth(0)
        inspector_layout = QVBoxLayout(self.inspector_panel)
        inspector_layout.setContentsMargins(12, 14, 12, 14)
        inspector_label = QLabel("SELECTED CLASS")
        inspector_label.setObjectName("eyebrowLabel")
        self.blueprint_inspector_title = QLabel("Select a class")
        self.blueprint_inspector_title.setObjectName("inspectorTitle")
        self.blueprint_inspector_title.setWordWrap(True)
        self.blueprint_inspector_copy = QLabel(
            "Its room, teacher, conflicts, and explained suggestions will appear here."
        )
        self.blueprint_inspector_copy.setObjectName("inspectorMeta")
        self.blueprint_inspector_copy.setWordWrap(True)
        inspector_meta_card = QFrame()
        inspector_meta_card.setObjectName("inspectorMetaCard")
        inspector_meta_layout = QVBoxLayout(inspector_meta_card)
        inspector_meta_layout.setContentsMargins(11, 10, 11, 10)
        inspector_meta_layout.setSpacing(5)
        inspector_meta_layout.addWidget(self.blueprint_inspector_title)
        inspector_meta_layout.addWidget(self.blueprint_inspector_copy)
        inspector_layout.addWidget(inspector_label)
        inspector_layout.addWidget(inspector_meta_card)
        constraint_box = QGroupBox("Constraints")
        constraint_layout = QVBoxLayout(constraint_box)
        self.blueprint_constraints_copy = QLabel(
            "Room capacity, staff availability, group overlap, and institutional rules are checked for the selected class."
        )
        self.blueprint_constraints_copy.setObjectName("inspectorMeta")
        self.blueprint_constraints_copy.setWordWrap(True)
        constraint_layout.addWidget(self.blueprint_constraints_copy)
        inspector_layout.addWidget(constraint_box)
        self.schedule_actions_scroll = QScrollArea()
        self.schedule_actions_scroll.setWidget(self._build_schedule_actions_panel())
        self.schedule_actions_scroll.setWidgetResizable(True)
        self.schedule_actions_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.schedule_actions_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.schedule_actions_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.schedule_actions_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        suggestion_box = QGroupBox("Suggestions")
        suggestion_layout = QVBoxLayout(suggestion_box)
        suggestion_copy = QLabel(
            "Preview safe alternatives for the selected class before applying a change."
        )
        suggestion_copy.setObjectName("inspectorMeta")
        suggestion_copy.setWordWrap(True)
        suggestion_layout.addWidget(suggestion_copy)
        suggestion_layout.addWidget(self.quick_edit_btn)
        suggestion_layout.addWidget(self.quick_hold_btn)
        suggestion_layout.addWidget(self.quick_targets_btn)
        suggestion_layout.addWidget(self.quick_release_btn)
        suggestion_layout.addStretch(1)
        inspector_layout.addWidget(suggestion_box, 1)
        self.quality_scroll = QScrollArea()
        self.quality_scroll.setObjectName("validationCard")
        self.blueprint_validation_label = QLabel("Validation and score details appear after a run.")
        self.blueprint_validation_label.setWordWrap(True)
        self.quality_scroll.setWidget(self.blueprint_validation_label)
        self.quality_scroll.setWidgetResizable(True)
        self.quality_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.quality_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.quality_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.quality_scroll.setMaximumHeight(106)
        self.quality_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        inspector_layout.addWidget(self.quality_scroll, 0)
        self.blueprint_splitter.addWidget(self.inspector_panel)
        self.blueprint_splitter.setSizes([220, 950, 290])
        self.blueprint_splitter.setStretchFactor(1, 1)
        schedule_tab_layout.addWidget(self.blueprint_splitter)

        data_tab = QWidget()
        data_layout = QVBoxLayout(data_tab)
        data_layout.setContentsMargins(24, 22, 24, 22)
        data_layout.setSpacing(14)
        data_eyebrow = QLabel("TIMETABLE DATA")
        data_eyebrow.setObjectName("eyebrowLabel")
        data_heading = QLabel("Start from a clear, relevant scenario")
        data_heading.setObjectName("pageHeading")
        data_intro = QLabel(
            "Use the small demo to learn the workflow, the Spring 2023 university data for a full-scale plan, or import your institution's data."
        )
        data_intro.setWordWrap(True)
        data_layout.addWidget(data_eyebrow)
        data_layout.addWidget(data_heading)
        data_layout.addWidget(data_intro)
        data_cards = QHBoxLayout()
        self.demo_data_button = QPushButton("Open demo timetable")
        self.spring_data_button = QPushButton("Open Spring 2023 university")
        self.import_data_button = QPushButton("Import institutional data")
        for button in (self.demo_data_button, self.spring_data_button, self.import_data_button):
            button.setMinimumHeight(72)
            data_cards.addWidget(button)
        data_layout.addLayout(data_cards)
        data_layout.addStretch(1)

        review_tabs = QTabWidget()
        review_tabs.addTab(self._build_fairness_tab(), "Quality")
        review_tabs.addTab(self._build_diagnostics_tab(), "Diagnostics")

        advanced_tab = QScrollArea()
        advanced_tab.setWidgetResizable(True)
        advanced_tab.setFrameShape(QFrame.Shape.NoFrame)
        advanced_content = QWidget()
        advanced_tab.setWidget(advanced_content)
        advanced_layout = QVBoxLayout(advanced_content)
        advanced_layout.setContentsMargins(8, 8, 8, 8)
        advanced_notice = QLabel(
            "Specialist and research controls. Normal planning uses the shared Fast, Balanced, and Maximum quality modes."
        )
        advanced_notice.setObjectName("advancedNotice")
        advanced_notice.setWordWrap(True)
        advanced_layout.addWidget(advanced_notice)
        tuning_box = QGroupBox("Engine overrides")
        tuning_form = QFormLayout(tuning_box)
        tuning_form.addRow("Room strategy", self.room_mode_combo)
        tuning_form.addRow("Objective profile", self.objective_profile_combo)
        tuning_form.addRow("Solve limit", self.time_limit_spin)
        tuning_form.addRow("Workers", self.workers_preset_combo)
        tuning_form.addRow("Random seed", self.random_seed_spin)
        tuning_form.addRow("Improve iterations", self.improve_runs_spin)
        tuning_form.addRow("Improve time", self.ls_time_spin)
        tuning_form.addRow("Improve focus", self.improve_focus_combo)
        tuning_form.addRow(self.objective_cb)
        tuning_form.addRow(self.debug_diagnostics_cb)
        advanced_actions = QHBoxLayout()
        for button in (self.clear_locks_button, self.undo_button, self.redo_button, self.revert_button):
            advanced_actions.addWidget(button)
        advanced_actions.addStretch(1)
        tuning_form.addRow(advanced_actions)
        advanced_layout.addWidget(tuning_box)
        advanced_sections = QTabWidget()
        generator_tab = QWidget()
        generator_layout = QVBoxLayout(generator_tab)
        generator_layout.setContentsMargins(0, 0, 0, 0)
        self.custom_generate_button = QPushButton("Build custom scenario")
        self.custom_generate_button.setMinimumHeight(42)
        generator_layout.addWidget(self.custom_generate_button)
        generator_layout.addWidget(self._build_generator_tab(), 1)
        advanced_sections.addTab(generator_tab, "Custom builder")
        advanced_sections.addTab(self._build_constraints_tab(), "Rules and weights")
        advanced_sections.addTab(self.schedule_actions_scroll, "Manual repair")
        advanced_layout.addWidget(advanced_sections, 1)

        self.workspace_tabs.addTab(schedule_tab, "Schedule")
        self.workspace_tabs.addTab(data_tab, "Data")
        self.workspace_tabs.addTab(review_tabs, "Review")
        self.workspace_tabs.addTab(self._build_history_tab(), "Projects")
        self.workspace_tabs.addTab(advanced_tab, "Advanced")

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

        self._apply_theme()

        self._build_menus()
        self._ensure_custom_generator_seeded()
        self._load_custom_config_local(silent=True)
        self._apply_room_capacity_mode()
        self._load_constraint_controls_from_instance(None)
        self._apply_run_mode()
        self._refresh_blueprint_resources()
        self._refresh_blueprint_inspector()
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
        if not self._tutorial_checked:
            self._tutorial_checked = True
            if not TutorialDialog.was_seen() and not os.getenv("PLANORA_SKIP_TUTORIAL"):
                QTimer.singleShot(250, self.on_show_tutorial)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            self._shutdown_solver_process()
        except Exception:
            self.proc = None
            self._cleanup_solver_temp_files()
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

        self.improve_button.setMinimumWidth(improve_max)
        self.improve_button.setMaximumWidth(16777215)
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
        if hasattr(self, "resource_panel"):
            self.resource_panel.setVisible(w >= 1180)
        if hasattr(self, "inspector_panel"):
            self.inspector_panel.setVisible(True)
            self.inspector_panel.setMinimumWidth(220 if w < 1180 else 250)
        if hasattr(self, "blueprint_splitter"):
            self.blueprint_splitter.setSizes(
                [0, max(420, w - 330), 270]
                if w < 1180
                else [210, max(520, w - 560), 280]
            )
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

        theme = str(prefs.get("theme", self._theme_mode))
        if theme in {"light", "dark"} and theme != self._theme_mode:
            self._theme_mode = theme
            self._apply_theme()

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
            "theme": self._theme_mode,
        }
        self._runtime_settings["ui_preferences"] = prefs
        self._runtime_settings = save_runtime_settings(
            self._runtime_paths["settings"],
            self._runtime_settings,
        )

    def _apply_theme(self) -> None:
        self.setStyleSheet(DARK_STYLE if self._theme_mode == "dark" else LIGHT_STYLE)
        if hasattr(self, "theme_button"):
            self.theme_button.setText("Light" if self._theme_mode == "dark" else "Dark")
            self.theme_button.setToolTip(
                f"Switch to {'light' if self._theme_mode == 'dark' else 'dark'} theme"
            )
        if hasattr(self, "table") and self.inst is not None:
            self.update_table()
            self.table.viewport().update()

    def _toggle_theme(self) -> None:
        self._theme_mode = "light" if self._theme_mode == "dark" else "dark"
        self._apply_theme()
        self._save_ui_control_preferences()

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
        # Keep the timetable dense and readable while leaving scrolling to the
        # table itself. Fixed headers remain visible as users move through a
        # large university week.
        base_col_w = 152
        min_col_w = 124
        row_h = 66
        min_row_h = 48
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

        self.table.setMinimumSize(0, 0)
        self.table.setMaximumSize(16777215, 16777215)
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
        self.publish_button.setToolTip("Publish the current validated release candidate.")
        self.export_menu_btn.setToolTip("Export schedules/reports.")
        self.project_menu_btn.setToolTip(
            "Save/load/compare plus admin tooling: disruption auto-repair, sandbox branches, and history snapshots."
            "\nAuto-repair: Project > Auto-Repair Disruption... then pick outage type and week to re-solve with unaffected activities frozen."
            "\nSandbox flow: start a branch, try edits, compare, then apply or discard."
        )
        self.mode_combo.setToolTip("Instance template used when generating data.")
        self.room_mode_combo.setToolTip(
            "Room assignment strategy:\n"
            "- Auto: strict room variables on small instances, parallel exact week partitions on large instances.\n"
            "- Scale: independent weeks run in parallel; exact room certificates activate on demand.\n"
            "- Strict: CP-SAT chooses rooms with room no-overlap constraints.\n"
            "- Fast: CP-SAT chooses times, then a greedy pass assigns rooms.\n"
            "Cross-week hard decision constraints require a monolithic mode."
        )
        self.objective_profile_combo.setToolTip(
            "Solve profile:\n"
            "- Fast feasible: prioritize a valid timetable quickly.\n"
            "- University fast: parallel week solves with adaptive exact room fallback.\n"
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
        self.generate_button.clicked.connect(self._on_public_generate)
        self.solve_button.clicked.connect(self.on_solve)
        self.clear_locks_button.clicked.connect(self.on_clear_locks)
        self.improve_button.clicked.connect(self.on_improve)
        self.stop_improve_button.clicked.connect(self.on_stop_improve)
        self.undo_button.clicked.connect(self.on_undo)
        self.redo_button.clicked.connect(self.on_redo)
        self.revert_button.clicked.connect(self.on_revert_to_base)
        self.conflicts_button.clicked.connect(self.on_show_conflicts)
        self.publish_button.clicked.connect(self.on_publish_release_candidate)
        self.tutorial_button.clicked.connect(self.on_show_tutorial)
        self.run_mode_combo.currentIndexChanged.connect(self._apply_run_mode)
        self.demo_data_button.clicked.connect(lambda: self._select_public_scenario("demo"))
        self.spring_data_button.clicked.connect(
            lambda: self._select_public_scenario("spring_2023")
        )
        self.import_data_button.clicked.connect(self.on_import_timetable_csv)
        self.custom_generate_button.clicked.connect(self._generate_custom_scenario)
        self.blueprint_resource_search.textChanged.connect(self._refresh_blueprint_resources)
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
        self.selected_activity_combo.currentIndexChanged.connect(
            self._refresh_blueprint_inspector
        )
        self.table.itemSelectionChanged.connect(self._refresh_quick_actions)
        self.table.itemSelectionChanged.connect(self._refresh_blueprint_inspector)
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

    def on_show_tutorial(self) -> None:
        tutorial_steps = [
            {
                "title": str(step.get("title") or ""),
                "description": str(step.get("body") or step.get("description") or ""),
            }
            for step in self._ui_contract.get("tutorial", [])
            if isinstance(step, dict)
        ]
        dialog = TutorialDialog(self, icon_path=_app_icon_path(), steps=tutorial_steps)
        if dialog.exec() == 2:
            self.workspace_tabs.setCurrentIndex(1)

    def _select_public_scenario(self, mode: str) -> None:
        scenario_index = self.scenario_combo.findData(str(mode))
        if scenario_index >= 0:
            self.scenario_combo.setCurrentIndex(scenario_index)
        self.workspace_tabs.setCurrentIndex(0)
        self._on_public_generate()

    def _on_public_generate(self) -> None:
        scenario_id = str(self.scenario_combo.currentData() or "demo")
        if scenario_id == "import":
            self.on_import_timetable_csv()
            return
        mode = generator_mode_for_scenario(scenario_id)
        mode_index = self.mode_combo.findData(mode)
        if mode_index >= 0:
            self.mode_combo.setCurrentIndex(mode_index)
        self.on_generate()
        self.workspace_tabs.setCurrentIndex(0)

    def _generate_custom_scenario(self) -> None:
        mode_index = self.mode_combo.findData("custom")
        if mode_index >= 0:
            self.mode_combo.setCurrentIndex(mode_index)
        self.on_generate()
        self.workspace_tabs.setCurrentIndex(0)

    def _apply_run_mode(self, *_args: Any) -> None:
        mode = str(self.run_mode_combo.currentData() or "balanced")
        solve_defaults = run_mode_options(mode, action="solve")
        improve_defaults = run_mode_options(mode, action="improve")
        room_mode = str(solve_defaults["room_mode"])
        profile = str(solve_defaults["objective_profile"])
        seconds = float(solve_defaults["time_limit_seconds"])
        objective = bool(solve_defaults["use_objective"])
        iterations = int(improve_defaults["iterations"])
        improve_seconds = float(improve_defaults["max_seconds"])
        room_index = self.room_mode_combo.findData(room_mode)
        if room_index >= 0:
            self.room_mode_combo.setCurrentIndex(room_index)
        profile_index = self.objective_profile_combo.findData(profile)
        if profile_index >= 0:
            self.objective_profile_combo.setCurrentIndex(profile_index)
        self.time_limit_spin.setValue(max(self.time_limit_spin.minimum(), int(round(seconds))))
        self.objective_cb.setChecked(bool(objective))
        self.improve_runs_spin.setValue(int(iterations))
        self.ls_time_spin.setValue(int(round(improve_seconds)))

    def _active_advanced_solve_options(self) -> Dict[str, Any]:
        return {
            "room_mode": str(self.room_mode_combo.currentData()),
            "objective_profile": str(self.objective_profile_combo.currentData()),
            "time_limit_seconds": float(self.time_limit_spin.value()),
            "workers": int(self.workers_preset_combo.currentData()),
            "use_objective": bool(self.objective_cb.isChecked()),
        }

    def _refresh_blueprint_resources(self, *_args: Any) -> None:
        if not hasattr(self, "blueprint_resource_list"):
            return
        query = str(self.blueprint_resource_search.text()).strip().lower()
        self.blueprint_resource_list.clear()
        if self.inst is None:
            self.blueprint_resource_list.addItem("Choose timetable data to see resources")
            return
        collections = (
            ("GROUPS", getattr(self.inst, "groups", {})),
            ("COURSES", getattr(self.inst, "courses", {})),
            ("STAFF", getattr(self.inst, "staff", {})),
            ("ROOMS", getattr(self.inst, "rooms", {})),
        )
        for heading, collection in collections:
            labels = []
            for entity_id, entity in collection.items():
                name = str(getattr(entity, "name", "") or getattr(entity, "code", "") or entity_id)
                if query and query not in name.lower():
                    continue
                labels.append(name)
            if not labels:
                continue
            heading_item = QListWidgetItem(f"{heading}  {len(labels)}")
            heading_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.blueprint_resource_list.addItem(heading_item)
            for label in labels[:18]:
                self.blueprint_resource_list.addItem(f"  {label}")

    def _refresh_blueprint_inspector(self, *_args: Any) -> None:
        if not hasattr(self, "blueprint_inspector_title"):
            return
        activity_id = self.selected_activity_id
        if activity_id is None or self.inst is None:
            self.blueprint_inspector_title.setText("Select a class")
            self.blueprint_inspector_copy.setText(
                "Its room, teacher, conflicts, and explained suggestions will appear here."
            )
            self.blueprint_constraints_copy.setText(
                "Room capacity, staff availability, group overlap, and institutional rules are checked for the selected class."
            )
            self.blueprint_validation_label.setText(
                "Validation and score details appear after a run."
            )
            return
        activity = self.inst.activities.get(int(activity_id))
        placement = self.current_schedule.get(int(activity_id), {})
        if activity is None:
            return
        course = self.inst.courses.get(int(activity.course_id))
        default_staff_id = (
            int(activity.prof_id)
            if str(activity.kind).upper() == "LEC"
            else int(activity.ta_id)
        )
        staff_id = placement.get("staff_id", default_staff_id)
        staff = self.inst.staff.get(int(staff_id)) if staff_id is not None else None
        room_id = placement.get("room_id")
        room = self.inst.rooms.get(int(room_id)) if room_id is not None else None
        title = str(getattr(course, "name", "") or f"Activity {activity_id}")
        self.blueprint_inspector_title.setText(title)
        self.blueprint_inspector_copy.setText(
            "\n".join(
                (
                    f"{str(activity.kind)} · Activity {int(activity_id)}",
                    f"Staff: {getattr(staff, 'name', 'Unassigned')}",
                    f"Room: {getattr(room, 'name', 'Unassigned')}",
                    f"Time: {placement.get('day', 'Not placed')} · Slot {int(placement.get('slot', -1)) + 1}",
                )
            )
        )
        if self.current_schedule and self._conflict_ids_cache_revision != int(self._schedule_revision):
            self._conflict_ids_cache = self._compute_conflicting_activity_ids(self.current_schedule)
            self._conflict_ids_cache_revision = int(self._schedule_revision)
        conflict_count = len(self._conflict_ids_cache) if self.current_schedule else 0
        selected_has_conflict = int(activity_id) in self._conflict_ids_cache
        lock = self.locked_activities.get(int(activity_id), {})
        lock_labels: List[str] = []
        if "day" in lock and "slot" in lock:
            lock_labels.append("time locked")
        if "room_id" in lock:
            lock_labels.append("room locked")
        lock_summary = ", ".join(lock_labels) if lock_labels else "editable"
        self.blueprint_constraints_copy.setText(
            " · ".join(
                (
                    "Room capacity checked",
                    "Staff availability checked",
                    "No overlap checked",
                    "Conflict detected" if selected_has_conflict else "No hard conflict",
                    lock_summary.capitalize(),
                )
            )
        )
        self.blueprint_validation_label.setText(
            "No hard conflict is currently reported for this draft."
            if conflict_count == 0
            else f"The current draft contains {conflict_count} activities in hard conflict. Open Validate for details."
        )

    def _on_mode_changed(self) -> None:
        mode = str(self.mode_combo.currentData() or self.mode_combo.currentText())
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
            self.workspace_tabs.setCurrentIndex(4)

    # ----- helpers -----

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
            self._refresh_blueprint_resources()
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
        self._refresh_blueprint_resources()
        self._refresh_blueprint_inspector()
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

            self.table.setRowCount(S)
            self.table.setColumnCount(len(days))
            self.table.setVerticalHeaderLabels(
                [self._slot_display_label(idx) for idx in range(S)]
            )
            self.table.setHorizontalHeaderLabels(days)
            self.table.clearSpans()
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
                    title = f"{course_code} · {course_name}" if course_name else course_code
                    if lock_text:
                        title = f"{lock_text.strip()} {title}"
                    label = "\n".join(
                        (
                            title,
                            f"{str(info['kind'])} · {room_name}",
                            staff_name,
                        )
                    )

                detail = (
                    f"A{a_id} {course_code} {course_name} {info['kind']} | "
                    f"Groups={len(info['group_ids'])} | Room={room_name} | Staff={staff_name}"
                ).strip()

                for ds in range(dur):
                    s = s0 + ds
                    if 0 <= s < S:
                        cell_entries[(day, s)].append(
                            (int(a_id), label if ds == 0 else "", detail)
                        )

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
            course_card_colors = (
                QColor("#dbeafe"),
                QColor("#d9f3e8"),
                QColor("#fff0cf"),
                QColor("#e8ddfa"),
                QColor("#f9d9cc"),
            )

            span_requests: List[Tuple[int, int, int]] = []
            for row in range(S):
                for col, day in enumerate(days):
                    slot = int(row)
                    entries = sorted(cell_entries[(day, slot)], key=lambda t: int(t[0]))
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
                        analysis = self._held_move_analysis_map.get((str(day), int(slot)))
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
                    item.setForeground(QBrush(QColor("#20344f")))
                    if ids:
                        item.setData(Qt.ItemDataRole.UserRole, ids)
                        first_info = self.current_schedule.get(int(ids[0]), {})
                        course_key = int(first_info.get("course_id", ids[0]))
                        item.setBackground(
                            QBrush(course_card_colors[course_key % len(course_card_colors)])
                        )
                        card_font = item.font()
                        card_font.setBold(True)
                        item.setFont(card_font)

                    if held_week_ok and held_id is not None and held_id in ids:
                        item.setForeground(QBrush(QColor("#ffffff")))
                        item.setBackground(QBrush(color_held))
                    elif ids and any(int(a_id) in conflict_ids for a_id in ids):
                        item.setForeground(QBrush(QColor("#ffffff")))
                        item.setBackground(QBrush(color_current_conflict))
                    elif held_week_ok and held_id is not None:
                        analysis = self._held_move_analysis_map.get((str(day), int(slot)))
                        if analysis is not None and held_target_map.get((str(day), int(slot)), False):
                            delta_here = held_delta_map.get((str(day), int(slot)))
                            if not text:
                                text = "VALID TARGET"
                            elif "VALID TARGET" not in text and "BETTER" not in text and "WORSE" not in text:
                                text = f"VALID TARGET\n{text}"
                            item.setText(text)
                            item.setForeground(QBrush(QColor("#ffffff")))
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
                        item.setForeground(QBrush(QColor("#ffffff")))
                        item.setBackground(QBrush(color_changed))

                    tooltip = self._build_cell_tooltip(
                        row=int(row),
                        col=int(slot),
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

                    if view_type != "All" and len(entries) == 1 and entries[0][1]:
                        placement = self.current_schedule.get(int(entries[0][0]), {})
                        duration = max(1, int(placement.get("duration", 1) or 1))
                        span = min(duration, S - row)
                        if span > 1 and all(
                            [int(entry[0]) for entry in cell_entries.get((day, row + offset), [])]
                            == [int(entries[0][0])]
                            for offset in range(span)
                        ):
                            span_requests.append((int(row), int(col), int(span)))

            for row, col, span in span_requests:
                self.table.setSpan(int(row), int(col), int(span), 1)

            if self.selected_activity_id is None:
                for (row, col), activity_ids in self._cell_activity_map.items():
                    if not activity_ids:
                        continue
                    self.selected_cell_row = int(row)
                    self.selected_cell_col = int(col)
                    self.selected_activity_id = int(activity_ids[0])
                    self.table.setCurrentCell(int(row), int(col))
                    break

            self._schedule_table_relayout()
            self._refresh_quick_actions()
            self._refresh_blueprint_inspector()
        except Exception:
            traceback.print_exc()
            self.clear_table()
            self.set_status("Failed to render schedule table")

    # ----- per-group quality -----


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
