from __future__ import annotations

from services.application_service import solve_options_from_payload
from utils.generator import generate_instance
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_web_solve_payload_moves_hard_constraints_out_of_options():
    inst = generate_instance("small_demo")
    assert not inst.hard_constraints.get("force_repeat_weekly_pattern")

    options = solve_options_from_payload(
        inst,
        {
            "options": {
                "room_mode": "greedy",
                "use_objective": False,
                "force_repeat_weekly_pattern": True,
            }
        },
    )

    assert options.room_mode == "greedy"
    assert options.use_objective is False
    assert inst.hard_constraints["force_repeat_weekly_pattern"] is True


def test_react_client_preserves_failed_solves_and_handles_complete_jobs():
    app = (ROOT / "web" / "src" / "react" / "App.tsx").read_text(encoding="utf-8")
    assert "The current timetable was preserved" in app
    assert '["complete", "done", "failed", "cancelled"]' in app
    assert '["complete", "done"].includes(String(payload.status))' in app
    assert "function jobPercent" not in app
    assert "Number(jobStatus.progress || 0)" not in app


def test_react_admin_downloads_are_authenticated_and_insights_are_implemented():
    api = (ROOT / "web" / "src" / "react" / "api.ts").read_text(encoding="utf-8")
    admin = (ROOT / "web" / "src" / "react" / "components" / "AdminPanel.tsx").read_text(encoding="utf-8")
    access = (ROOT / "web" / "src" / "react" / "components" / "AccessPanel.tsx").read_text(encoding="utf-8")
    insights = (ROOT / "web" / "src" / "react" / "components" / "InsightsPanel.tsx").read_text(encoding="utf-8")
    assert "download(path: string" in api
    assert "onDownload(`/analytics/export.csv" in admin
    assert "apiBaseUrl" not in admin
    assert "accountTenants" in access and "selectedTenant" in access
    assert "Fairness and utilization" in insights


def test_server_contract_rotates_tenant_sessions_and_uses_sqlite_project_writes():
    server = (ROOT / "api" / "server.py").read_text(encoding="utf-8")
    assert 'if parts == ["sessions"]:' in server
    assert 'principal = _authenticated(self, "schedule:read")' in server
    assert "analytics_principal.tenant_id if analytics_principal else \"public\"" in server
    assert "token, csrf, ttl, session_principal = _session_for_principal(updated)" in server
    assert 'saved = {"name": safe_project_name(name), "storage": "sqlite"}' in server
    assert "save_web_project(WEB_PROJECTS_DIR" not in server
    assert 'if raw_status not in {2, 4} or not new_schedule:' in server
    assert '"iterations": total_iterations' in server


def test_react_hardening_workflows_are_wired():
    app = (ROOT / "web" / "src" / "react" / "App.tsx").read_text(encoding="utf-8")
    operations = (ROOT / "web" / "src" / "react" / "components" / "OperationsPanel.tsx").read_text(encoding="utf-8")
    projects = (ROOT / "web" / "src" / "react" / "components" / "ProjectsPanel.tsx").read_text(encoding="utf-8")
    board = (ROOT / "web" / "src" / "react" / "components" / "ScheduleBoard.tsx").read_text(encoding="utf-8")
    assert 'await api.post<Dict>("/auth/logout", {})' in app
    assert "window.setTimeout(poll" in app and "window.setInterval" not in app[app.index("const jobId"):app.index("async function holdSelected")]
    assert "schedule={schedule}" in app
    assert "scheduleActivities" not in app
    assert "instance={instance}" in app and "scenarios={uiContract.scenarios}" in app
    assert "scheduleActivities" not in operations
    assert "Save current workspace" in projects and "Rename" in projects and "Delete" in projects
    assert "colSpan={span}" in board and 'span > 1 ? "multi-slot"' in board


def test_shared_ui_contract_maps_plain_language_choices_to_backend_owned_modes():
    app = (ROOT / "web" / "src" / "react" / "App.tsx").read_text(encoding="utf-8")
    operations = (ROOT / "web" / "src" / "react" / "components" / "OperationsPanel.tsx").read_text(encoding="utf-8")
    planner_api = (ROOT / "web" / "src" / "react" / "planner_api.ts").read_text(encoding="utf-8")
    ui_contract = (ROOT / "services" / "ui_contract.py").read_text(encoding="utf-8")

    assert "loadUiContract(client)" in app
    assert "uiContract.scenarios" in app and "uiContract.modes" in app
    assert "advancedOverridesEnabled" in app
    assert "Choose the result you want. Planora selects the underlying engine settings." in operations
    assert "modes.map" in operations
    assert '"label": "Fast"' in ui_contract and '"label": "Balanced"' in ui_contract
    assert "run_mode: mode" in planner_api
    assert "advanced_overrides" in planner_api
    assert 'UI_CONTRACT_VERSION = "planora.ui.v1"' in ui_contract
    assert '"id": "spring_2023"' in ui_contract
    assert '"id": "quality"' in ui_contract
    assert '"target_case"' not in ui_contract.split("def public_preset_ids", 1)[0]


def test_quality_and_local_backup_gates_are_configured():
    package = (ROOT / "web" / "package.json").read_text(encoding="utf-8")
    compose = (ROOT / "deploy" / "docker-compose.prod.yml").read_text(encoding="utf-8")
    retention = (ROOT / "scripts" / "retention_planora.py").read_text(encoding="utf-8")
    assert '"lint": "eslint' in package
    assert "planora-backup:" in compose
    assert "offsite-backup" not in compose
    assert "rclone" not in compose
    assert "PLANORA_MAX_ACTIVE_JOBS_PER_TENANT" in compose
    assert "'complete', 'done', 'failed', 'cancelled'" in retention
    assert '("sessions", "updated_at", "workspace sessions")' in retention
