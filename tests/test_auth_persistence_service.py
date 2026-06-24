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


def test_bootstrap_role_activates_requested_tenant(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    registered = store.register_email_user(
        email="server-admin@example.edu",
        password="correct horse battery",
        display_name="Server Admin",
    )["principal"]
    store.bootstrap_user_role(user_id=registered.user_id, tenant_id="operations", role="admin")
    resolved = store.resolve_principal(registered)
    assert resolved.tenant_id == "operations"
    assert resolved.role == "admin"
    assert resolved.is_global_admin


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
    store.audit(principal, action="auth.login", resource_type="user", resource_id=principal.user_id)
    events = store.list_audit(principal)
    assert events[0]["action"] == "auth.login"
    assert events[0]["tenant_id"] == "uni-a"
    filtered = store.list_audit(principal, action="session", user_id="admin")
    assert len(filtered) == 1
    assert filtered[0]["action"] == "session.solve"


def test_persistence_records_and_summarizes_first_party_analytics(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    admin = Principal(user_id="root", role="admin", tenant_id="global")
    uni_admin = Principal(user_id="admin-a", role="uni_admin", tenant_id="uni-a")
    student = Principal(user_id="student-a", role="student", tenant_id="uni-a")
    store.upsert_user(admin)
    store.upsert_user(uni_admin)
    store.record_analytics_event(
        {
            "client_id_hash": "client-a",
            "tenant_id": "uni-a",
            "user_role": "student",
            "event_name": "page_view",
            "path": "/workspace",
            "view_name": "workspace",
            "viewport_width": 1280,
            "viewport_height": 720,
            "details": {"source": "test"},
        }
    )
    store.record_analytics_event(
        {
            "client_id_hash": "client-a",
            "tenant_id": "uni-a",
            "user_role": "student",
            "event_name": "solve_complete",
            "path": "/workspace",
        }
    )
    store.record_analytics_event(
        {
            "client_id_hash": "client-b",
            "tenant_id": "uni-b",
            "user_role": "uni_admin",
            "event_name": "page_view",
            "path": "/admin",
        }
    )

    tenant_summary = store.analytics_summary(uni_admin)
    assert tenant_summary["events"] == 2
    assert tenant_summary["visitors"] == 1
    assert tenant_summary["top_paths"][0]["path"] == "/workspace"
    assert {row["event_name"] for row in tenant_summary["top_events"]} == {"page_view", "solve_complete"}

    global_summary = store.analytics_summary(admin)
    assert global_summary["events"] == 3
    assert global_summary["visitors"] == 2
    filtered = store.analytics_summary(admin, tenant_id="uni-a", event_name="page_view", path="/workspace")
    assert filtered["events"] == 1
    assert filtered["visitors"] == 1
    with pytest.raises(PermissionError):
        store.analytics_summary(student)


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


def test_auth_session_replacement_revokes_old_after_creating_new(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    old = Principal(user_id="admin-a", role="uni_admin", tenant_id="uni-a", session_id="sid-old")
    new = Principal(user_id="admin-a", role="uni_admin", tenant_id="uni-a", session_id="sid-new")
    store.upsert_user(old)
    store.create_auth_session(old, "sid-old", ttl_seconds=60)
    csrf = store.replace_auth_session(old, "sid-new", ttl_seconds=60)

    assert csrf
    with pytest.raises(PermissionError, match="expired or revoked"):
        store.require_active_session(old)
    store.require_active_session(new)


def test_auth_session_listing_password_change_and_revoke_others(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    registered = store.register_email_user(
        email="secure@example.edu",
        password="correct horse battery",
        display_name="Secure User",
    )
    store.verify_email_token(registered["verification_token"])
    principal = store.authenticate_email_user(email="secure@example.edu", password="correct horse battery")
    first = Principal(user_id=principal.user_id, role=principal.role, tenant_id=principal.tenant_id, session_id="sid-1")
    second = Principal(user_id=principal.user_id, role=principal.role, tenant_id=principal.tenant_id, session_id="sid-2")
    store.create_auth_session(first, "sid-1", ttl_seconds=60)
    store.create_auth_session(second, "sid-2", ttl_seconds=60)
    listed = store.list_auth_sessions(first)["sessions"]
    assert {row["session_id"] for row in listed} == {"sid-1", "sid-2"}
    assert any(row["current"] for row in listed)

    store.change_password(first, current_password="correct horse battery", new_password="new correct horse battery")
    with pytest.raises(PermissionError):
        store.authenticate_email_user(email="secure@example.edu", password="correct horse battery")
    assert store.authenticate_email_user(email="secure@example.edu", password="new correct horse battery").user_id == first.user_id

    store.revoke_other_auth_sessions(first)
    store.require_active_session(first)
    with pytest.raises(PermissionError):
        store.require_active_session(second)


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


def test_admin_can_disable_and_reenable_account(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    admin = Principal(user_id="admin-a", role="uni_admin", tenant_id="default")
    user = store.register_email_user(
        email="delete-me@example.edu",
        password="correct horse battery",
        display_name="Delete Me",
    )["principal"]
    store.upsert_user(admin)
    store.apply_access_change(admin, {"action": "set_disabled", "user_id": user.user_id, "disabled": True, "tenant_id": "default"})
    with pytest.raises(PermissionError, match="disabled"):
        store.resolve_principal(user)
    store.apply_access_change(admin, {"action": "set_disabled", "user_id": user.user_id, "disabled": False, "tenant_id": "default"})
    assert store.resolve_principal(user).user_id == user.user_id


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
    assert registered["verification_code"].isdigit()
    assert len(registered["verification_code"]) == 6
    principal = registered["principal"]
    assert principal.user_id == "email:student@example.edu"
    assert principal.role == "student"
    with pytest.raises(PermissionError, match="not verified"):
        store.authenticate_email_user(email="student@example.edu", password="correct horse battery", require_verified=True)
    verified = store.verify_email_token(registered["verification_code"], email="student@example.edu")
    assert verified.user_id == principal.user_id
    logged_in = store.authenticate_email_user(email="student@example.edu", password="correct horse battery", require_verified=True)
    assert logged_in.user_id == principal.user_id
    assert group_id in logged_in.groups


def test_password_reset_code_changes_password(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    registered = store.register_email_user(
        email="reset-user@example.edu",
        password="correct horse battery",
        display_name="Reset User",
    )
    store.verify_email_token(registered["verification_token"])
    reset = store.create_password_reset("reset-user@example.edu")
    assert reset is not None
    assert reset["reset_code"].isdigit()
    principal = store.reset_password(
        email="reset-user@example.edu",
        token=reset["reset_code"],
        new_password="new correct horse battery",
    )
    assert principal.user_id == "email:reset-user@example.edu"
    with pytest.raises(PermissionError):
        store.authenticate_email_user(email="reset-user@example.edu", password="correct horse battery")
    logged_in = store.authenticate_email_user(email="reset-user@example.edu", password="new correct horse battery")
    assert logged_in.user_id == principal.user_id


def test_email_account_can_join_group_after_registration(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    admin = Principal(user_id="admin-a", role="uni_admin", tenant_id="default")
    store.upsert_user(admin)
    snapshot = store.apply_access_change(admin, {"action": "create_group", "name": "Reviewers"})
    group_id = snapshot["groups"][0]["group_id"]
    store.apply_access_change(
        admin,
        {"action": "create_invite", "group_id": group_id, "role": "professor", "code": "reviewers-code"},
    )
    registered = store.register_email_user(
        email="new-user@example.edu",
        password="correct horse battery",
        display_name="New User",
    )
    principal = registered["principal"]
    assert principal.role == "student"
    assert principal.groups == ()
    store.verify_email_token(registered["verification_token"])
    logged_in = store.authenticate_email_user(email="new-user@example.edu", password="correct horse battery")
    joined = store.redeem_invite_for_user(logged_in, "reviewers-code")
    assert group_id in joined.groups
    assert joined.role == "professor"


def test_email_account_can_join_and_switch_between_organizations(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    global_admin = Principal(user_id="root", role="admin", tenant_id="global")
    store.upsert_user(global_admin)
    uni_a_snapshot = store.apply_access_change(global_admin, {"action": "create_group", "tenant_id": "uni-a", "name": "Students"})
    uni_b_snapshot = store.apply_access_change(global_admin, {"action": "create_group", "tenant_id": "uni-b", "name": "Reviewers"})
    uni_a_group = [row["group_id"] for row in uni_a_snapshot["groups"] if row["tenant_id"] == "uni-a"][0]
    uni_b_group = [row["group_id"] for row in uni_b_snapshot["groups"] if row["tenant_id"] == "uni-b"][0]
    store.apply_access_change(
        global_admin,
        {"action": "create_invite", "tenant_id": "uni-a", "group_id": uni_a_group, "role": "student", "code": "uni-a-student-code"},
    )
    store.apply_access_change(
        global_admin,
        {"action": "create_invite", "tenant_id": "uni-b", "group_id": uni_b_group, "role": "professor", "code": "uni-b-reviewer-code"},
    )
    registered = store.register_email_user(
        email="multi@example.edu",
        password="correct horse battery",
        display_name="Multi Org",
        invite_code="uni-a-student-code",
    )
    store.verify_email_token(registered["verification_token"])
    logged_in = store.authenticate_email_user(email="multi@example.edu", password="correct horse battery")
    assert logged_in.tenant_id == "uni-a"
    assert uni_a_group in logged_in.groups
    joined = store.redeem_invite_for_user(logged_in, "uni-b-reviewer-code")
    assert joined.tenant_id == "uni-b"
    assert joined.role == "professor"
    assert uni_b_group in joined.groups
    orgs = store.user_organizations(joined)["organizations"]
    assert {row["tenant_id"] for row in orgs} == {"uni-a", "uni-b"}
    switched = store.switch_user_tenant(joined, "uni-a")
    assert switched.tenant_id == "uni-a"
    assert switched.role == "student"
    assert uni_a_group in switched.groups


def test_global_admin_cannot_switch_to_missing_organization(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    global_admin = Principal(user_id="root", role="admin", tenant_id="global")
    store.upsert_user(global_admin)

    with pytest.raises(ValueError, match="Organization was not found"):
        store.switch_user_tenant(global_admin, "missing-org")


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


def test_invite_mutations_require_existing_invite(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    admin = Principal(user_id="admin-a", role="uni_admin", tenant_id="uni-a")
    store.upsert_user(admin)

    with pytest.raises(ValueError, match="Invite code was not found"):
        store.apply_access_change(admin, {"action": "rotate_invite", "invite_id": "missing", "code": "new-code-123"})
    with pytest.raises(ValueError, match="Invite code was not found"):
        store.apply_access_change(admin, {"action": "set_invite_disabled", "invite_id": "missing", "disabled": True})


def test_parity_manifest_reports_coverage():
    manifest = parity_manifest()
    assert manifest["covered"] > 0
    assert manifest["total"] >= manifest["covered"]
    assert any(row["capability"] == "solve" for row in manifest["items"])
