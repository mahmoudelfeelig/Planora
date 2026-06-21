from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from services.branding_service import (  # noqa: E402
    default_branding_profile,
    white_label_profile_for_institution,
)
from services.diagnostics_service import (  # noqa: E402
    build_stakeholder_quality_report,
    build_unsat_rule_diagnosis,
    compute_entity_heatmaps,
    explain_candidate_slot,
    write_stakeholder_quality_report,
)
from services.export_service import export_reports  # noqa: E402
from services.institution_template_service import apply_institution_template  # noqa: E402
from services.runtime_ops_service import (  # noqa: E402
    append_runtime_log,
    check_for_updates,
    collect_support_bundle,
    load_runtime_settings,
    record_telemetry_event,
    save_runtime_settings,
    save_update_manifest,
    write_crash_report,
)
from ui import window as ui_window  # noqa: E402
from utils.generator import generate_instance  # noqa: E402


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


def test_diagnostics_services_generate_rule_diagnosis_and_reports(tmp_path: Path):
    inst = generate_instance("small_demo")
    a_id, schedule = _single_activity_schedule(inst)
    invalid = {k: dict(v) for k, v in schedule.items()}
    invalid[a_id]["slot"] = int(inst.slots_per_day)

    diagnosis = build_unsat_rule_diagnosis(inst, invalid)
    assert diagnosis
    assert diagnosis[0]["rule_id"] in {"slot_range", "general_feasibility"}

    explanation = explain_candidate_slot(
        inst,
        schedule,
        activity_id=a_id,
        week=int(schedule[a_id]["week"]),
        day=str(schedule[a_id]["day"]),
        slot=int(inst.slots_per_day),
        room_id=int(schedule[a_id]["room_id"]),
        staff_id=int(schedule[a_id]["staff_id"]),
    )
    assert explanation["valid"] is False
    assert explanation["reasons"]

    heatmaps = compute_entity_heatmaps(inst, schedule)
    assert heatmaps["groups"]
    assert heatmaps["staff"]

    branding = default_branding_profile()
    report = build_stakeholder_quality_report(inst, schedule, branding=branding)
    outputs = write_stakeholder_quality_report(tmp_path, report)
    assert Path(outputs["json"]).exists()
    assert "Planora" in Path(outputs["markdown"]).read_text(encoding="utf-8")


def test_runtime_ops_services_roundtrip(tmp_path: Path):
    settings_path = tmp_path / "runtime_settings.json"
    log_path = tmp_path / "runtime.jsonl"
    telemetry_path = tmp_path / "telemetry.jsonl"
    crash_dir = tmp_path / "crash"
    manifest_path = tmp_path / "update_manifest.json"
    bundle_path = tmp_path / "support.zip"

    settings = save_runtime_settings(
        settings_path,
        {"crash_reports_opt_in": True, "telemetry_opt_in": True, "update_channel": "preview"},
    )
    assert load_runtime_settings(settings_path)["update_channel"] == "preview"

    append_runtime_log(log_path, event="solve_started", details={"mode": "greedy"})
    record_telemetry_event(telemetry_path, event="ui_opened", details={"source": "test"}, opt_in=True)
    crash_path = write_crash_report(
        crash_dir,
        error_type="RuntimeError",
        message="boom",
        traceback_text="trace",
        opt_in=True,
    )
    assert crash_path is not None

    save_update_manifest(
        manifest_path,
        {
            "channels": {
                "stable": {"version": "1.0.0", "download_url": "https://example/stable", "notes": "stable"},
                "preview": {"version": "1.1.0", "download_url": "https://example/preview", "notes": "preview"},
            }
        },
    )
    update = check_for_updates(current_version="1.0.0", manifest_source=manifest_path, channel="preview")
    assert update["available"] is True
    assert update["latest_version"] == "1.1.0"

    bundle = collect_support_bundle(
        bundle_path,
        runtime_paths={
            "settings": str(settings_path),
            "runtime_log": str(log_path),
            "crash_dir": str(crash_dir),
            "telemetry_log": str(telemetry_path),
        },
        settings=settings,
        metadata={"test": True},
        extra_files={"workspace/state.json": json.dumps({"ok": True})},
    )
    assert Path(bundle).exists()
    with zipfile.ZipFile(bundle, "r") as archive:
        names = set(archive.namelist())
    assert "manifest.json" in names
    assert "workspace/state.json" in names


def test_branded_export_reports_and_white_label_support(tmp_path: Path):
    inst = generate_instance("small_demo")
    _, schedule = _single_activity_schedule(inst)
    white_label = white_label_profile_for_institution(
        institution_name="North Campus",
        owner_name="feel",
        accent="#0055AA",
    )
    merged = apply_institution_template(
        {"branding": white_label},
        current_config={"branding": default_branding_profile()},
    )
    export_reports(
        inst,
        schedule,
        tmp_path,
        branding=merged["branding"],
        baseline_schedule=schedule,
    )
    staff_load = (tmp_path / "staff_load.csv").read_text(encoding="utf-8").splitlines()
    quality_md = (tmp_path / "quality_report.md").read_text(encoding="utf-8")
    assert "North Campus Scheduler" in staff_load[0]
    assert "North Campus Scheduler" in quality_md
    assert (tmp_path / "group_heatmaps.csv").exists()
    assert (tmp_path / "staff_heatmaps.csv").exists()


def test_ui_diagnostics_tab_and_white_label_profile(monkeypatch, qt_app):
    win = ui_window.MainWindow()
    try:
        inst = generate_instance("small_demo")
        _, schedule = _single_activity_schedule(inst)
        win.inst = inst
        win.base_schedule = {k: dict(v) for k, v in schedule.items()}
        win.current_schedule = {k: dict(v) for k, v in schedule.items()}
        win.populate_weeks()
        win.update_entities()
        win.update_table()
        win.update_quality_summary()
        win._refresh_diagnostics_controls()
        win.on_explain_candidate_slot()
        assert "Valid:" in win.why_not_output_text.toPlainText()
        assert win.heatmap_table.rowCount() == len(inst.days)
        assert win.diagnostics_summary_text.toPlainText().strip()

        monkeypatch.setattr(
            ui_window.QInputDialog,
            "getText",
            lambda *args, **kwargs: ("North Campus", True)
            if "Institution" in str(args[2])
            else ("feel", True),
        )
        win.on_apply_white_label_profile()
        assert "North Campus Scheduler" in win.windowTitle()
    finally:
        win.close()
        win.deleteLater()


def test_ui_update_check_and_support_bundle(monkeypatch, qt_app, tmp_path: Path):
    win = ui_window.MainWindow()
    try:
        manifest_path = tmp_path / "manifest.json"
        save_update_manifest(
            manifest_path,
            {"channels": {"stable": {"version": "1.0.0", "download_url": "https://example", "notes": "ok"}}},
        )
        win._runtime_settings["update_manifest_path"] = str(manifest_path)
        info_calls: list[str] = []
        monkeypatch.setattr(QMessageBox, "information", lambda *args: info_calls.append(str(args[2])) or QMessageBox.StandardButton.Ok)
        win.on_check_updates()
        assert info_calls
    finally:
        win.close()
        win.deleteLater()
