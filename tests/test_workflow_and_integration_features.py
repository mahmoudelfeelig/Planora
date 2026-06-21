from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PyQt6 = pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QListWidgetItem, QMessageBox  # noqa: E402

from api.server import _handle_graphql, _handle_solve  # noqa: E402
from connectors.csv_connectors import (  # noqa: E402
    ERPCsvConnector,
    LMSCsvConnector,
    SISCsvConnector,
    available_connectors,
)
from services.approval_service import build_approval_record  # noqa: E402
from services.branch_service import branch_merge_assistance, create_branch  # noqa: E402
from services.calendar_sync_service import (  # noqa: E402
    build_calendar_sync_bundle,
    write_calendar_sync_bundle,
)
from services.project_service import load_legacy_project, save_legacy_project  # noqa: E402
from services.release_service import (  # noqa: E402
    create_release_candidate,
    protect_baseline_state,
    publish_release_candidate,
)
from services.template_profile_service import (  # noqa: E402
    list_import_export_template_profiles,
    load_import_export_template_profile,
    save_import_export_template_profile,
)
from ui import window as ui_window  # noqa: E402
from utils.generator import generate_instance, instance_to_json  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _single_activity_schedule(inst):
    a_id, act = next(iter(inst.activities.items()))
    room_id = next(iter(inst.rooms.keys()))
    return int(a_id), {
        int(a_id): {
            "week": int(act.week),
            "day": inst.days[0],
            "slot": 0,
            "duration": int(act.duration),
            "room_id": int(room_id),
            "staff_id": int(act.prof_id if act.kind == "LEC" else act.ta_id),
            "course_id": int(act.course_id),
            "group_ids": list(act.group_ids),
            "kind": str(act.kind),
        }
    }


def test_approval_branch_and_release_services():
    approval = build_approval_record(
        action="force_move",
        actor="feel",
        reason="Emergency override",
        details={"activity_id": 1},
    )
    assert approval.actor == "feel"
    assert approval.reason == "Emergency override"

    base = {
        1: {"week": 1, "day": "MON", "slot": 0, "duration": 1, "room_id": 1, "staff_id": 1, "course_id": 1, "group_ids": [1], "kind": "LEC"}
    }
    current = {
        1: {"week": 1, "day": "TUE", "slot": 1, "duration": 1, "room_id": 2, "staff_id": 1, "course_id": 1, "group_ids": [1], "kind": "LEC"}
    }
    branch = create_branch(name="ops/fix", author="feel", description="repair", base_schedule=base, current_schedule=current)
    summary = branch_merge_assistance(branch, base)
    assert summary["branch_name"] == "ops/fix"
    assert int(summary["changed_time"]) == 1

    candidate = create_release_candidate(name="rc-1", author="feel", schedule=current, notes="candidate")
    published = publish_release_candidate(candidate)
    baseline = protect_baseline_state(protected=True, actor="feel", reason="published")
    assert published["status"] == "published"
    assert baseline["protected"] is True


def test_import_export_template_registry_roundtrip(tmp_path: Path):
    path = tmp_path / "templates.json"
    save_import_export_template_profile(
        path,
        institution_name="Engineering",
        template={"import_mapping": {"activity_id": "Activity ID"}, "group_separator": "|"},
    )
    save_import_export_template_profile(
        path,
        institution_name="Medicine",
        template={"import_mapping": {"activity_id": "AID"}, "group_separator": ";"},
    )

    assert list_import_export_template_profiles(path) == ["Engineering", "Medicine"]
    restored = load_import_export_template_profile(path, institution_name="Engineering")
    assert restored["import_mapping"]["activity_id"] == "Activity ID"
    assert restored["group_separator"] == "|"


def test_database_backed_project_roundtrip(tmp_path: Path):
    inst = generate_instance("small_demo")
    _, schedule = _single_activity_schedule(inst)
    path = tmp_path / "project.sqlite"

    save_legacy_project(
        path,
        inst,
        schedule,
        meta={"operator_name": "feel", "active_branch_name": "main"},
    )
    loaded_inst, loaded_schedule, meta = load_legacy_project(path)

    assert len(loaded_inst.activities) == len(inst.activities)
    assert loaded_schedule == schedule
    assert meta["operator_name"] == "feel"
    assert meta["active_branch_name"] == "main"


def test_connectors_export_csv(tmp_path: Path):
    inst = generate_instance("small_demo")
    sis_path = tmp_path / "sis.csv"
    erp_path = tmp_path / "erp.csv"
    lms_path = tmp_path / "lms.csv"

    SISCsvConnector().export_courses(inst, sis_path)
    ERPCsvConnector().export_staff_ownership(inst, erp_path)
    LMSCsvConnector().export_group_enrollments(inst, lms_path)

    assert "course_id" in sis_path.read_text(encoding="utf-8").splitlines()[0]
    assert "staff_id" in erp_path.read_text(encoding="utf-8").splitlines()[0]
    assert "group_id" in lms_path.read_text(encoding="utf-8").splitlines()[0]
    assert {row["id"] for row in available_connectors()} == {"sis_csv", "erp_csv", "lms_csv"}


def test_calendar_sync_bundle_roundtrip(tmp_path: Path):
    manifest = {
        "feeds": {
            "groups": ["groups/g1.ics"],
            "staff": ["staff/s1.ics"],
        }
    }
    bundle = build_calendar_sync_bundle(manifest, base_url="https://planora.example/cal")
    path = tmp_path / "bundle.json"
    write_calendar_sync_bundle(path, bundle)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert len(payload["providers"]["google"]) == 2
    assert payload["providers"]["outlook"][0]["url"].startswith("https://planora.example/cal/")


def test_api_handlers_expose_health_and_solve():
    health = _handle_graphql({"query": "{ health { ok } }"})
    assert health == {"data": {"health": {"ok": True}}}

    inst = generate_instance("small_demo")
    result = _handle_solve(
        {
            "instance": instance_to_json(inst),
            "options": {
                "room_mode": "greedy",
                "use_objective": False,
                "retry_without_objective": False,
                "time_limit_seconds": 5.0,
                "workers": 1,
            },
        }
    )
    assert result["schedule"]
    assert result["hard_conflicts"] == []


def test_ui_history_activation_and_change_history(monkeypatch, qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        a_id, schedule = _single_activity_schedule(inst)
        branch_schedule = {k: dict(v) for k, v in schedule.items()}
        branch_schedule[a_id]["slot"] = 1
        release_schedule = {k: dict(v) for k, v in schedule.items()}
        release_schedule[a_id]["slot"] = 2
        win.base_schedule = {k: dict(v) for k, v in schedule.items()}
        win.current_schedule = {k: dict(v) for k, v in schedule.items()}
        win.populate_weeks()
        win.update_entities()
        win.update_table()
        win._branches = {
            "ops/fix": create_branch(
                name="ops/fix",
                author="feel",
                description="repair",
                base_schedule=win.base_schedule,
                current_schedule=branch_schedule,
            )
        }
        win._release_candidates = {
            "rc-1": create_release_candidate(
                name="rc-1",
                author="feel",
                schedule=release_schedule,
                notes="candidate",
            )
        }
        win._append_audit_log("manual_override", {"activity_id": int(a_id)})
        win._refresh_history_view()

        info_calls: list[str] = []
        monkeypatch.setattr(QMessageBox, "information", lambda *args: info_calls.append(str(args[2])) or QMessageBox.StandardButton.Ok)

        branch_item = QListWidgetItem("branch")
        branch_item.setData(Qt.ItemDataRole.UserRole, ("branch", "ops/fix"))
        win.on_history_item_activated(branch_item)
        assert int(win.current_schedule[a_id]["slot"]) == 1

        release_item = QListWidgetItem("release")
        release_item.setData(Qt.ItemDataRole.UserRole, ("release", "rc-1"))
        win.on_history_item_activated(release_item)
        assert int(win.current_schedule[a_id]["slot"]) == 2

        event_item = QListWidgetItem("event")
        event_item.setData(Qt.ItemDataRole.UserRole, ("change_event", len(win._workspace_change_log) - 1))
        win.on_history_item_activated(event_item)
        assert info_calls
    finally:
        win.close()
        win.deleteLater()


def test_ui_template_registry_actions(monkeypatch, qt_app, tmp_path: Path):
    win = ui_window.MainWindow()
    try:
        win._import_export_template_path = str(tmp_path / "templates.json")
        win._institution_template = {"name": "Engineering"}
        win._last_import_mapping = {"activity_id": "Activity ID", "week": "Week"}
        win._last_group_separator = "|"

        monkeypatch.setattr(
            ui_window.QInputDialog,
            "getText",
            staticmethod(lambda *args, **kwargs: ("Engineering", True)),
        )
        win.on_save_import_export_template()

        win._last_import_mapping = {}
        win._last_group_separator = ";"
        monkeypatch.setattr(
            ui_window.QInputDialog,
            "getItem",
            staticmethod(lambda *args, **kwargs: ("Engineering", True)),
        )
        win.on_load_import_export_template()

        assert win._last_import_mapping["activity_id"] == "Activity ID"
        assert win._last_group_separator == "|"
        assert Path(win._import_export_template_path).exists()
    finally:
        win.close()
        win.deleteLater()


def test_protected_baseline_apply_requires_approval(monkeypatch, qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        win.inst = inst
        _, schedule = _single_activity_schedule(inst)
        win.base_schedule = {k: dict(v) for k, v in schedule.items()}
        win.current_schedule = {k: dict(v) for k, v in schedule.items()}
        win._sandbox_base_schedule = {k: dict(v) for k, v in schedule.items()}
        win._protected_baseline = {"protected": True}

        called = {}

        def fake_require_approval(*, action, details=None):
            called["action"] = action
            return {"reason": "approved"}

        monkeypatch.setattr(win, "_require_approval", fake_require_approval)
        monkeypatch.setattr(win, "_validate_schedule_hard_errors", lambda *args, **kwargs: [])
        win.on_sandbox_apply()
        assert called["action"] == "apply_branch_to_protected_baseline"
        assert win._sandbox_base_schedule is None
    finally:
        win.close()
        win.deleteLater()
