from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.auth_service import (
    Principal,
    auth_secret,
    create_auth_token,
    permissions_for_role,
    principal_payload,
    principal_from_token,
    require_permission,
    require_tenant_access,
    stamp_meta,
)
from services.parity_service import parity_manifest
from services.persistence_service import PersistenceStore


def test_role_permissions_and_tenant_access():
    student = Principal(user_id="s1", role="student", tenant_id="uni-a")
    admin = Principal(user_id="root", role="admin", tenant_id="global")
    assert "schedule:read" in permissions_for_role("student")
    assert "tenants:read_all" in permissions_for_role("admin")
    assert principal_payload(student)["tenant_id"] == "uni-a"
    require_tenant_access(student, "uni-a")
    require_tenant_access(admin, "uni-b")
    require_permission(admin, "solver:run")


def test_signed_auth_token_roundtrip():
    principal = Principal(user_id="prof-a", role="professor", tenant_id="uni-a")
    token = create_auth_token(principal, ttl_seconds=60)
    restored = principal_from_token(token)
    assert restored == principal


def test_auth_secret_can_be_loaded_from_secret_file(monkeypatch, tmp_path):
    secret_file = tmp_path / "auth-secret.txt"
    secret_file.write_text("file-backed-secret\n", encoding="utf-8")
    monkeypatch.delenv("PLANORA_AUTH_SECRET", raising=False)
    monkeypatch.setenv("PLANORA_AUTH_SECRET_FILE", str(secret_file))
    assert auth_secret() == "file-backed-secret"


def test_stamp_meta_records_principal_identity():
    principal = Principal(user_id="u1", role="uni_admin", tenant_id="uni-a")
    meta = stamp_meta({"source": "test"}, principal)
    assert meta["tenant_id"] == "uni-a"
    assert meta["created_by"] == "u1"
    assert meta["created_by_role"] == "uni_admin"
    assert meta["source"] == "test"


def test_stamp_meta_cannot_be_used_to_spoof_tenant_or_creator():
    principal = Principal(user_id="u1", role="uni_admin", tenant_id="uni-a")
    meta = stamp_meta({"tenant_id": "uni-b", "created_by": "attacker"}, principal)
    assert meta["tenant_id"] == "uni-a"
    assert meta["created_by"] == "u1"


def test_persistence_projects_are_tenant_scoped(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    assert store.schema_info()["schema_version"] >= 2
    admin = Principal(user_id="root", role="admin", tenant_id="global")
    uni_a = Principal(user_id="a-admin", role="uni_admin", tenant_id="uni-a")
    uni_b = Principal(user_id="b-admin", role="uni_admin", tenant_id="uni-b")
    project_a = {"name": "schedule", "instance": {}, "schedule": {}, "meta": {"tenant_id": "uni-a"}}
    project_b = {"name": "schedule", "instance": {}, "schedule": {}, "meta": {"tenant_id": "uni-b"}}
    store.save_project("schedule", project_a, uni_a)
    store.save_project("schedule", project_b, uni_b)
    assert [row["tenant_id"] for row in store.list_projects(uni_a)] == ["uni-a"]
    assert [row["tenant_id"] for row in store.list_projects(uni_b)] == ["uni-b"]
    assert {row["tenant_id"] for row in store.list_projects(admin)} == {"uni-a", "uni-b"}
    assert store.load_project("schedule", uni_a)["meta"]["tenant_id"] == "uni-a"


def test_persistence_sessions_and_audit_events(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    principal = Principal(user_id="admin-a", role="uni_admin", tenant_id="uni-a")
    session = SimpleNamespace(
        session_id="s1",
        instance_json={"activities": {"1": {}}},
        schedule={1: {"week": 1}},
        meta={"tenant_id": "uni-a", "created_by": "admin-a", "created_by_role": "uni_admin"},
        created_at=1.0,
        updated_at=2.0,
    )
    store.upsert_user(principal)
    store.save_session(session)
    store.audit(principal, action="session.solve", resource_type="session", resource_id="s1")
    events = store.list_audit(principal)
    assert events[0]["action"] == "session.solve"
    assert events[0]["tenant_id"] == "uni-a"


def test_auth_sessions_are_revocable(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    principal = Principal(user_id="admin-a", role="uni_admin", tenant_id="uni-a", session_id="sid-1")
    store.upsert_user(principal)
    csrf = store.create_auth_session(principal, "sid-1", ttl_seconds=60)
    assert csrf
    store.require_active_session(principal)
    store.revoke_auth_session(principal)
    with pytest.raises(PermissionError, match="expired or revoked"):
        store.require_active_session(principal)


def test_group_roles_are_tenant_scoped_and_database_owned(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    admin = Principal(user_id="admin-a", role="uni_admin", tenant_id="uni-a")
    user = Principal(user_id="student-a", role="student", tenant_id="uni-a")
    store.upsert_user(admin)
    store.upsert_user(user)
    snapshot = store.apply_access_change(admin, {"action": "create_group", "name": "Schedulers"})
    group_id = snapshot["groups"][0]["group_id"]
    store.apply_access_change(admin, {"action": "set_membership", "group_id": group_id, "user_id": user.user_id})
    store.apply_access_change(admin, {"action": "bind_role", "principal_type": "group", "principal_id": group_id, "role": "uni_admin"})
    resolved = store.resolve_principal(user)
    assert resolved.role == "uni_admin"
    other_admin = Principal(user_id="admin-b", role="uni_admin", tenant_id="uni-b")
    store.upsert_user(other_admin)
    with pytest.raises(PermissionError):
        store.apply_access_change(other_admin, {"action": "set_membership", "tenant_id": "uni-a", "group_id": group_id, "user_id": user.user_id})


def test_invite_registration_verification_and_password_login(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    admin = Principal(user_id="admin-a", role="uni_admin", tenant_id="uni-a")
    store.upsert_user(admin)
    snapshot = store.apply_access_change(admin, {"action": "create_group", "name": "Students"})
    group_id = snapshot["groups"][0]["group_id"]
    snapshot = store.apply_access_change(
        admin,
        {"action": "create_invite", "group_id": group_id, "role": "student", "code": "manual-student-code"},
    )
    assert snapshot["new_invite_code"] == "manual-student-code"
    registered = store.register_email_user(
        email="Student@Example.edu",
        password="correct horse battery",
        display_name="Student One",
        invite_code="manual-student-code",
    )
    principal = registered["principal"]
    assert principal.user_id == "email:student@example.edu"
    assert principal.role == "student"
    with pytest.raises(PermissionError, match="not verified"):
        store.authenticate_email_user(email="student@example.edu", password="correct horse battery", require_verified=True)
    verified = store.verify_email_token(registered["verification_token"])
    assert verified.user_id == principal.user_id
    logged_in = store.authenticate_email_user(email="student@example.edu", password="correct horse battery", require_verified=True)
    assert logged_in.user_id == principal.user_id
    assert group_id in logged_in.groups


def test_invite_rotation_keeps_existing_members(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    admin = Principal(user_id="admin-a", role="uni_admin", tenant_id="uni-a")
    store.upsert_user(admin)
    snapshot = store.apply_access_change(admin, {"action": "create_group", "name": "TAs"})
    group_id = snapshot["groups"][0]["group_id"]
    snapshot = store.apply_access_change(
        admin,
        {"action": "create_invite", "group_id": group_id, "role": "ta", "code": "old-ta-code"},
    )
    invite_id = snapshot["invite_codes"][0]["invite_id"]
    first = store.register_email_user(
        email="ta1@example.edu",
        password="correct horse battery",
        display_name="TA One",
        invite_code="old-ta-code",
    )["principal"]
    rotated = store.apply_access_change(admin, {"action": "rotate_invite", "invite_id": invite_id, "code": "new-ta-code"})
    assert rotated["new_invite_code"] == "new-ta-code"
    with pytest.raises(PermissionError, match="invalid"):
        store.register_email_user(
            email="ta2@example.edu",
            password="correct horse battery",
            display_name="TA Two",
            invite_code="old-ta-code",
        )
    second = store.register_email_user(
        email="ta2@example.edu",
        password="correct horse battery",
        display_name="TA Two",
        invite_code="new-ta-code",
    )["principal"]
    assert group_id in store.resolve_principal(first).groups
    assert group_id in store.resolve_principal(second).groups


def test_parity_manifest_reports_coverage():
    manifest = parity_manifest()
    assert manifest["covered"] > 0
    assert manifest["total"] >= manifest["covered"]
    assert any(row["capability"] == "solve" for row in manifest["items"])

