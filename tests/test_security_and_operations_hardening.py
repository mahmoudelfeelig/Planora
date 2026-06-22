from __future__ import annotations

import threading
import time

import pytest

from api import server as api_server
from api.server import _global_admin, _handle_graphql, _system_status_payload
from services.application_service import JobCapacityExceeded, JobStore
from services.auth_service import Principal, create_auth_token
from services.persistence_service import PersistenceStore


def test_graphql_solver_requires_solver_permission():
    student = Principal(user_id="student", role="student", tenant_id="uni-a")
    with pytest.raises(PermissionError, match="solver:run"):
        _handle_graphql({"query": "mutation { solve }"}, student)


def test_global_admin_helper_rejects_tenant_admin(monkeypatch, tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    root = Principal(user_id="root", role="admin", tenant_id="global")
    tenant_admin = Principal(user_id="uni-admin", role="uni_admin", tenant_id="uni-a")
    store.upsert_user(root)
    store.upsert_user(tenant_admin)
    monkeypatch.setattr(api_server, "PERSISTENCE", store)

    class Handler:
        def __init__(self, principal: Principal) -> None:
            self.headers = {"Authorization": f"Bearer {create_auth_token(principal)}"}

    assert _global_admin(Handler(root)).is_global_admin
    with pytest.raises(PermissionError, match="Global administrator"):
        _global_admin(Handler(tenant_admin))


def test_system_status_payload_has_safe_runtime_metrics(monkeypatch, tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    monkeypatch.setattr(api_server, "PERSISTENCE", store)
    payload = _system_status_payload()
    assert payload["ok"] is True
    assert payload["database"]["path"].endswith("planora.sqlite3")
    assert payload["disk"]["total_bytes"] > 0
    assert "container" in payload["memory"]
    assert "host" in payload["memory"]
    assert "active" in payload["jobs"]
    assert "authenticated_rate_per_minute" in payload["limits"]


def test_job_store_enforces_tenant_capacity_and_cooperative_cancel(monkeypatch):
    monkeypatch.setenv("PLANORA_JOB_WORKERS", "1")
    monkeypatch.setenv("PLANORA_MAX_ACTIVE_JOBS_PER_TENANT", "1")
    store = JobStore()
    started = threading.Event()

    def work(job):
        started.set()
        while not job.cancel_requested:
            time.sleep(0.005)
        raise RuntimeError("cancelled")

    first = store.submit("improve", work, tenant_id="uni-a", created_by="admin")
    assert started.wait(1)
    with pytest.raises(JobCapacityExceeded, match="active scheduler jobs"):
        store.submit("improve", work, tenant_id="uni-a", created_by="admin")
    store.cancel(first.job_id)
    deadline = time.time() + 1
    while time.time() < deadline and store.get(first.job_id).status != "cancelled":
        time.sleep(0.01)
    assert store.get(first.job_id).status == "cancelled"


def test_invite_reuse_does_not_consume_another_use(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    admin = Principal(user_id="admin", role="uni_admin", tenant_id="uni-a")
    user = Principal(user_id="student", role="student", tenant_id="uni-a")
    store.upsert_user(admin)
    store.upsert_user(user)
    snapshot = store.apply_access_change(admin, {"action": "create_group", "name": "Students"})
    group_id = snapshot["groups"][0]["group_id"]
    store.apply_access_change(admin, {
        "action": "create_invite", "group_id": group_id, "role": "student",
        "code": "repeat-safe-code", "max_uses": 2,
    })
    store.redeem_invite_for_user(user, "repeat-safe-code")
    store.redeem_invite_for_user(user, "repeat-safe-code")
    invite = store.access_snapshot(admin)["invite_codes"][0]
    assert invite["used_count"] == 1


def test_access_changes_are_scoped_to_membership_tenant(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    admin_a = Principal(user_id="admin-a", role="uni_admin", tenant_id="uni-a")
    user_a = Principal(user_id="shared", role="student", tenant_id="uni-a")
    user_b = Principal(user_id="shared", role="student", tenant_id="uni-b")
    store.upsert_user(admin_a)
    store.upsert_user(user_a)
    store.upsert_user(user_b)
    store.apply_access_change(admin_a, {
        "action": "link_schedule_identity", "user_id": "shared", "staff_id": 41,
        "student_group_id": 12, "tenant_id": "uni-a",
    })
    active_a = store.switch_user_tenant(user_b, "uni-a")
    assert active_a.staff_id == 41
    assert active_a.student_group_id == 12
    store.apply_access_change(admin_a, {
        "action": "set_disabled", "user_id": "shared", "disabled": True, "tenant_id": "uni-a",
    })
    active_b = store.switch_user_tenant(active_a, "uni-b")
    assert store.resolve_principal(active_b).tenant_id == "uni-b"
    with pytest.raises(PermissionError, match="disabled for that organization"):
        store.switch_user_tenant(active_b, "uni-a")
    assert store.resolve_principal(active_b).tenant_id == "uni-b"


def test_access_change_rejects_foreign_user_or_group(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    admin = Principal(user_id="admin-a", role="uni_admin", tenant_id="uni-a")
    outsider = Principal(user_id="outsider", role="student", tenant_id="uni-b")
    store.upsert_user(admin)
    store.upsert_user(outsider)
    group_id = store.apply_access_change(admin, {"action": "create_group", "name": "Local"})["groups"][0]["group_id"]
    with pytest.raises(ValueError, match="does not belong"):
        store.apply_access_change(admin, {"action": "set_membership", "group_id": group_id, "user_id": outsider.user_id})
    with pytest.raises(ValueError, match="selected group"):
        store.apply_access_change(admin, {"action": "create_invite", "group_id": "foreign", "role": "student"})


def test_global_project_load_requires_tenant_when_names_collide(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    root = Principal(user_id="root", role="admin", tenant_id="global")
    a = Principal(user_id="a", role="uni_admin", tenant_id="uni-a")
    b = Principal(user_id="b", role="uni_admin", tenant_id="uni-b")
    store.save_project("fall", {"meta": {"tenant_id": "uni-a"}}, a)
    store.save_project("fall", {"meta": {"tenant_id": "uni-b"}}, b)
    with pytest.raises(ValueError, match="ambiguous"):
        store.load_project("fall", root)
    assert store.load_project("fall", root, tenant_id="uni-a")["meta"]["tenant_id"] == "uni-a"
    assert store.delete_project("fall", root, tenant_id="uni-b")


def test_analytics_details_have_storage_limit(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    with pytest.raises(ValueError, match="8192-byte"):
        store.record_analytics_event({
            "client_id_hash": "client", "event_name": "page_view", "path": "/",
            "details": {"payload": "x" * 9000},
        })


def test_password_reset_revokes_existing_sessions(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    registration = store.register_email_user(
        email="reset@example.edu", password="correct horse battery", display_name="Reset User",
    )
    store.verify_email_token(registration["verification_token"])
    principal = store.authenticate_email_user(email="reset@example.edu", password="correct horse battery")
    active = Principal(
        user_id=principal.user_id, role=principal.role, tenant_id=principal.tenant_id, session_id="old-session",
    )
    store.create_auth_session(active, "old-session", ttl_seconds=3600)
    reset = store.create_password_reset("reset@example.edu")
    assert reset is not None
    store.reset_password(token=reset["reset_token"], new_password="new correct horse battery")
    with pytest.raises(PermissionError, match="revoked"):
        store.require_active_session(active)
