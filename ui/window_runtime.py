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


def _window_global(name: str, fallback: Any) -> Any:
    """Resolve patchable window globals after mixin extraction."""
    module = sys.modules.get("ui.window")
    if module is None:
        return fallback
    return getattr(module, name, fallback)

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
from ui.table_items import NaturalSortTableItem, NumericTableItem, StepSpinBox
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
