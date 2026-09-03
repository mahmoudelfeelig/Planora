from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from api import server as api_server
from api.server import _global_admin, _handle_graphql, _system_status_payload
from services.application_service import JobCapacityExceeded, JobStore
from services.auth_service import (
    Principal,
    auth_secret,
    create_auth_token,
    production_mode,
    trusted_dev_headers_enabled,
    validate_auth_configuration,
)
from services.password_auth_service import secret_pepper, verification_base_url
from services.persistence_service import PersistenceStore


ROOT = Path(__file__).resolve().parents[1]


def test_graphql_solver_requires_solver_permission():
    student = Principal(user_id="student", role="student", tenant_id="uni-a")
    with pytest.raises(PermissionError, match="solver:run"):
        _handle_graphql({"query": "mutation { solve }"}, student)


def test_production_rejects_short_hmac_auth_secret(monkeypatch):
    monkeypatch.setenv("PLANORA_PRODUCTION", "1")
    monkeypatch.setenv("PLANORA_AUTH_SECRET", "short-secret")
    with pytest.raises(RuntimeError, match="at least 32 UTF-8 bytes"):
        auth_secret()


def test_docker_context_policy_excludes_secret_material() -> None:
    patterns = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert {
        ".env",
        ".env.*",
        "**/.env",
        "**/.env.*",
        "**/*.env",
        "**/secrets/**",
        "**/*.pem",
        "**/*.key",
        "**/*.p12",
        "**/*.pfx",
        "**/.ssh/**",
        "**/id_rsa",
        "output",
        "reports",
        "cover",
    } <= patterns
    verification = (ROOT / "scripts" / "verify_docker_build_context.sh").read_text(
        encoding="utf-8"
    )
    assert "docker buildx build" in verification
    assert "deploy/.env" in verification
    assert "nested/prod.env" in verification
    assert "output/local-result.json" in verification
    assert "Sensitive file entered the Docker build context" in verification


def test_desktop_solver_ipc_uses_private_exclusive_temp_files() -> None:
    source = (ROOT / "ui" / "window_solver.py").read_text(encoding="utf-8")
    assert 'tempfile.mkdtemp(prefix="planora_solver_")' in source
    assert "os.O_EXCL" in source
    assert "0o600" in source
    assert "shutil.rmtree(private_dir)" in source


def test_private_solver_payload_closes_descriptor_when_wrapping_fails(monkeypatch):
    from ui import window_solver

    closed: list[int] = []
    monkeypatch.setattr(window_solver.os, "open", lambda *_args, **_kwargs: 123)
    monkeypatch.setattr(
        window_solver.os,
        "fdopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("wrap failed")),
    )
    monkeypatch.setattr(window_solver.os, "close", closed.append)

    with pytest.raises(OSError, match="wrap failed"):
        window_solver._write_private_solver_payload("ignored", object())

    assert closed == [123]


def test_production_mode_rejects_ambiguous_values(monkeypatch):
    monkeypatch.setenv("PLANORA_PRODUCTION", "prod")
    with pytest.raises(RuntimeError, match="explicit boolean"):
        production_mode()


def test_production_cannot_enable_trusted_development_headers(monkeypatch):
    monkeypatch.setenv("PLANORA_PRODUCTION", "1")
    monkeypatch.setenv("PLANORA_TRUST_DEV_HEADERS", "1")
    with pytest.raises(RuntimeError, match="must be disabled"):
        trusted_dev_headers_enabled()


def test_production_auth_configuration_validates_before_serving(monkeypatch):
    monkeypatch.setenv("PLANORA_PRODUCTION", "1")
    monkeypatch.setenv("PLANORA_TRUST_DEV_HEADERS", "0")
    monkeypatch.setenv("PLANORA_AUTH_SECRET", "a" * 48)
    monkeypatch.delenv("PLANORA_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("PLANORA_DOMAIN", raising=False)
    monkeypatch.delenv("PLANORA_TOKEN_PEPPER", raising=False)
    monkeypatch.delenv("PLANORA_TOKEN_PEPPER_FILE", raising=False)
    with pytest.raises(RuntimeError, match="TOKEN_PEPPER.*required"):
        validate_auth_configuration()

    monkeypatch.setenv("PLANORA_TOKEN_PEPPER", "b" * 48)
    with pytest.raises(RuntimeError, match="PUBLIC_BASE_URL.*DOMAIN"):
        validate_auth_configuration()

    monkeypatch.setenv("PLANORA_PUBLIC_BASE_URL", "https://scheduler.example.edu")
    with pytest.raises(RuntimeError, match="SMTP_HOST is required"):
        validate_auth_configuration()

    monkeypatch.setenv("PLANORA_SMTP_HOST", "smtp.example.edu")
    validate_auth_configuration()


def test_production_verification_links_require_an_explicit_https_base_url(monkeypatch):
    monkeypatch.setenv("PLANORA_PRODUCTION", "1")
    monkeypatch.delenv("PLANORA_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("PLANORA_DOMAIN", raising=False)
    with pytest.raises(RuntimeError, match="PUBLIC_BASE_URL.*DOMAIN"):
        verification_base_url("https://attacker.example")

    monkeypatch.setenv("PLANORA_DOMAIN", "scheduler.example.edu")
    assert verification_base_url("https://attacker.example") == "https://scheduler.example.edu"

    monkeypatch.setenv("PLANORA_PUBLIC_BASE_URL", "http://scheduler.example.edu")
    with pytest.raises(RuntimeError, match="must use https"):
        verification_base_url("https://attacker.example")


def test_password_reset_smtp_failure_does_not_disclose_account_or_token(monkeypatch):
    responses: list[tuple[int, dict[str, object]]] = []

    class Store:
        def create_password_reset(self, email: str):
            if email == "known@example.edu":
                return {"reset_token": "secret-token", "reset_code": "123456"}
            return None

    class Handler:
        path = "/auth/forgot-password"

    monkeypatch.setattr(api_server, "PERSISTENCE", Store())
    monkeypatch.setattr(
        api_server,
        "build_password_reset_email",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(api_server, "_request_base_url", lambda _handler: "http://local")
    monkeypatch.setattr(api_server, "smtp_configured", lambda: True)
    monkeypatch.setattr(
        api_server,
        "send_email",
        lambda _message: (_ for _ in ()).throw(RuntimeError("SMTP unavailable")),
    )
    monkeypatch.setattr(
        api_server,
        "_json_response",
        lambda _handler, status, payload: responses.append((status, dict(payload))),
    )

    for email in ("known@example.edu", "unknown@example.edu"):
        monkeypatch.setattr(api_server, "_parse_json", lambda _handler, value=email: {"email": value})
        api_server.PlanoraApiHandler._do_POST(Handler())

    assert responses == [(200, {"ok": True}), (200, {"ok": True})]


def test_production_requires_a_long_independent_token_pepper(monkeypatch):
    auth_value = "a" * 48
    monkeypatch.setenv("PLANORA_PRODUCTION", "1")
    monkeypatch.setenv("PLANORA_AUTH_SECRET", auth_value)
    monkeypatch.delenv("PLANORA_TOKEN_PEPPER", raising=False)
    monkeypatch.delenv("PLANORA_TOKEN_PEPPER_FILE", raising=False)
    with pytest.raises(RuntimeError, match="required in production"):
        secret_pepper()

    monkeypatch.setenv("PLANORA_TOKEN_PEPPER", "too-short")
    with pytest.raises(RuntimeError, match="at least 32 UTF-8 bytes"):
        secret_pepper()

    monkeypatch.setenv("PLANORA_TOKEN_PEPPER", auth_value)
    with pytest.raises(RuntimeError, match="must be independent"):
        secret_pepper()

    unicode_value = "ä" * 32
    monkeypatch.setenv("PLANORA_AUTH_SECRET", unicode_value)
    monkeypatch.setenv("PLANORA_TOKEN_PEPPER", unicode_value)
    with pytest.raises(RuntimeError, match="must be independent"):
        secret_pepper()

    independent = "b" * 48
    monkeypatch.setenv("PLANORA_AUTH_SECRET", auth_value)
    monkeypatch.setenv("PLANORA_TOKEN_PEPPER", independent)
    assert secret_pepper() == independent


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


def test_access_snapshot_never_serializes_password_hashes(tmp_path):
    store = PersistenceStore(tmp_path / "planora.sqlite3")
    admin = Principal(user_id="admin", role="uni_admin", tenant_id="default")
    store.upsert_user(admin)
    registered = store.register_email_user(
        email="snapshot-user@example.edu",
        password="correct horse battery",
        display_name="Snapshot User",
    )

    snapshot = store.access_snapshot(admin)
    user = next(
        row
        for row in snapshot["users"]
        if row["user_id"] == registered["principal"].user_id
    )
    assert "password_hash" not in user


def test_development_compose_binds_api_to_loopback():
    root = Path(api_server.__file__).resolve().parents[1]
    compose = (root / "deploy" / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert '"127.0.0.1:8787:8787"' in compose


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


def test_background_session_mutation_is_persisted_before_terminal_job(monkeypatch):
    events: list[tuple[str, str]] = []

    class SessionStore:
        def get(self, session_id: str):
            assert session_id == "session-1"
            return {"session_id": session_id, "schedule": {"1": {"slot": 2}}}

    class Persistence:
        def save_session(self, session) -> None:
            events.append(("session", str(session["session_id"])))

    store = JobStore(on_change=lambda job: events.append(("job", str(job.status))))
    monkeypatch.setattr(api_server, "SESSION_STORE", SessionStore())
    monkeypatch.setattr(api_server, "PERSISTENCE", Persistence())
    monkeypatch.setattr(api_server, "JOB_STORE", store)
    monkeypatch.setattr(api_server, "_workspace_session", lambda *_args: object())
    monkeypatch.setattr(
        api_server,
        "_session_action_payload",
        lambda *_args, **_kwargs: {"result": {"schedule": {"1": {"slot": 2}}}},
    )

    principal = Principal(user_id="admin", role="uni_admin", tenant_id="uni-a")
    submitted = api_server._handle_job_submit(
        "improve",
        {"session_id": "session-1", "options": {"iterations": 1}},
        principal,
    )
    deadline = time.time() + 1
    while time.time() < deadline and store.get(submitted["job_id"]).status not in {"complete", "failed"}:
        time.sleep(0.01)

    assert store.get(submitted["job_id"]).status == "complete"
    assert events.index(("session", "session-1")) < events.index(("job", "complete"))


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
