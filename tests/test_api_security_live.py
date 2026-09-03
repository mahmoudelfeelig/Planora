from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from api import server as api_server
from api.http import allowed_origin, request_base_url
from api.rate_limit import rate_limit_identity
from services.auth_service import (
    AUTH_COOKIE,
    CSRF_COOKIE,
    Principal,
    create_auth_token,
)
from services.password_auth_service import (
    build_password_reset_email,
    build_verification_email,
    verification_base_url,
)
from services.persistence_service import PersistenceStore


ROOT = Path(__file__).resolve().parent.parent


class _RateHandler:
    def __init__(self, path: str = "/auth/config") -> None:
        self.path = path
        self.headers: dict[str, str] = {}
        self.client_address = ("203.0.113.10", 12345)
        self.server = type("Server", (), {"server_port": 8787})()


def test_rate_limits_separate_anonymous_and_authenticated_users(monkeypatch):
    api_server._RATE_BUCKETS.clear()
    monkeypatch.setenv("PLANORA_RATE_LIMIT_ANONYMOUS_PER_MINUTE", "1")
    monkeypatch.setenv("PLANORA_RATE_LIMIT_AUTHENTICATED_PER_MINUTE", "2")
    handler = _RateHandler()

    monkeypatch.setattr(api_server, "principal_from_headers", lambda _headers: (_ for _ in ()).throw(PermissionError()))
    api_server._check_rate_limit(handler)
    with pytest.raises(api_server.RateLimitExceeded) as anonymous_error:
        api_server._check_rate_limit(handler)
    assert anonymous_error.value.retry_after > 0

    api_server._RATE_BUCKETS.clear()
    principal = Principal(user_id="email:admin@example.com", role="admin", tenant_id="default")
    monkeypatch.setattr(api_server, "principal_from_headers", lambda _headers: principal)
    api_server._check_rate_limit(handler)
    api_server._check_rate_limit(handler)
    with pytest.raises(api_server.RateLimitExceeded):
        api_server._check_rate_limit(handler)


def test_health_and_readiness_are_not_rate_limited(monkeypatch):
    monkeypatch.setenv("PLANORA_RATE_LIMIT_ANONYMOUS_PER_MINUTE", "1")
    monkeypatch.setattr(api_server, "principal_from_headers", lambda _headers: (_ for _ in ()).throw(PermissionError()))
    for path in ("/health", "/ready"):
        handler = _RateHandler(path)
        for _ in range(5):
            api_server._check_rate_limit(handler)


def test_openapi_documents_head_health_and_readiness():
    paths = api_server._openapi_schema()["paths"]
    assert "head" in paths["/health"]
    assert "get" in paths["/ready"]
    assert "head" in paths["/ready"]


def test_verify_endpoint_uses_sensitive_auth_rate_limit(monkeypatch):
    api_server._RATE_BUCKETS.clear()
    monkeypatch.setenv("PLANORA_RATE_LIMIT_AUTH_PER_MINUTE", "1")
    monkeypatch.setenv("PLANORA_RATE_LIMIT_ANONYMOUS_PER_MINUTE", "100")
    monkeypatch.setattr(api_server, "principal_from_headers", lambda _headers: (_ for _ in ()).throw(PermissionError()))
    handler = _RateHandler("/auth/verify")
    api_server._check_rate_limit(handler)
    with pytest.raises(api_server.RateLimitExceeded):
        api_server._check_rate_limit(handler)


def test_anonymous_rate_identity_ignores_forwarded_for_until_proxy_trust_is_enabled(monkeypatch):
    handler = _RateHandler()
    handler.headers = {"X-Forwarded-For": "198.51.100.20, 198.51.100.21"}
    anonymous = lambda _headers: (_ for _ in ()).throw(PermissionError())
    monkeypatch.delenv("PLANORA_TRUST_PROXY_HEADERS", raising=False)

    assert rate_limit_identity(handler, anonymous) == ("ip:203.0.113.10", False)

    monkeypatch.setenv("PLANORA_TRUST_PROXY_HEADERS", "1")
    assert rate_limit_identity(handler, anonymous) == ("ip:198.51.100.21", False)

    handler.headers = {"X-Forwarded-For": "198.51.100.20, not-an-ip"}
    assert rate_limit_identity(handler, anonymous) == ("ip:203.0.113.10", False)


def test_rate_limit_bucket_cardinality_is_strictly_bounded(monkeypatch):
    api_server._RATE_BUCKETS.clear()
    monkeypatch.setenv("PLANORA_RATE_LIMIT_MAX_BUCKETS", "8")
    monkeypatch.setenv("PLANORA_RATE_LIMIT_AUTH_PER_MINUTE", "10000")
    monkeypatch.setattr(
        api_server,
        "principal_from_headers",
        lambda _headers: (_ for _ in ()).throw(PermissionError()),
    )

    for index in range(64):
        handler = _RateHandler("/auth/login")
        handler.client_address = (f"203.0.113.{index + 1}", 12345)
        api_server._check_rate_limit(handler)

    assert len(api_server._RATE_BUCKETS) <= 8


def test_default_development_cors_allows_only_known_loopback_ui_origins(monkeypatch):
    monkeypatch.delenv("PLANORA_PRODUCTION", raising=False)
    monkeypatch.delenv("PLANORA_ALLOWED_ORIGINS", raising=False)
    handler = _RateHandler()

    handler.headers = {"Origin": "https://attacker.example"}
    assert allowed_origin(handler) == ""

    handler.headers = {"Origin": "http://localhost:5173"}
    assert allowed_origin(handler) == "http://localhost:5173"

    monkeypatch.setenv("PLANORA_ALLOWED_ORIGINS", "https://admin.example")
    handler.headers = {"Origin": "https://admin.example"}
    assert allowed_origin(handler) == "https://admin.example"


def test_request_base_url_ignores_host_and_forwarded_headers_without_proxy_trust(monkeypatch):
    monkeypatch.delenv("PLANORA_PRODUCTION", raising=False)
    monkeypatch.delenv("PLANORA_TRUST_PROXY_HEADERS", raising=False)
    monkeypatch.delenv("PLANORA_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("PLANORA_DOMAIN", raising=False)
    handler = _RateHandler()
    handler.headers = {
        "Host": "attacker.example",
        "X-Forwarded-Host": "forwarded-attacker.example",
        "X-Forwarded-Proto": "https",
    }

    base_url = verification_base_url(request_base_url(handler))
    assert base_url == "http://127.0.0.1:8787"
    reset_email = build_password_reset_email(
        base_url,
        "victim@example.edu",
        "reset_secret",
        "123456",
    )
    assert "attacker.example" not in reset_email.body

    monkeypatch.setenv("PLANORA_TRUST_PROXY_HEADERS", "1")
    handler.headers = {
        "X-Forwarded-Host": "scheduler.example.edu",
        "X-Forwarded-Proto": "https",
    }
    assert request_base_url(handler) == "https://scheduler.example.edu"

    handler.headers = {
        "X-Forwarded-Host": "scheduler.example.edu/path",
        "X-Forwarded-Proto": "javascript",
    }
    assert request_base_url(handler) == "http://127.0.0.1:8787"


def test_account_email_embeds_the_elephant_and_uses_the_planora_palette():
    message = build_verification_email(
        "https://planora.example",
        "student@example.edu",
        "verification-token",
        "123456",
    )

    assert 'src="cid:planora-elephant"' in message.html_body
    assert "#1f669b" in message.html_body
    assert "#8d3bd1" not in message.html_body
    assert len(message.inline_images) == 1
    image = message.inline_images[0]
    assert image.content_id == "planora-elephant"
    assert image.content_type == "image/png"
    assert image.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_csrf_gate_exempts_only_public_auth_posts():
    public_posts = (
        ["analytics", "event"],
        ["events", "collect"],
        ["auth", "login"],
        ["auth", "register"],
        ["auth", "verify"],
        ["auth", "forgot-password"],
        ["auth", "reset-password"],
        ["auth", "logout"],
        ["auth", "refresh"],
    )
    for parts in public_posts:
        assert not api_server._post_requires_csrf(parts)

    protected_posts = (
        ["auth", "change-password"],
        ["auth", "sessions"],
        ["auth", "resend-verification"],
        ["access", "join-invite"],
        ["sessions"],
        ["projects"],
    )
    for parts in protected_posts:
        assert api_server._post_requires_csrf(parts)


def test_optional_analytics_identity_uses_resolved_principal(monkeypatch):
    principal = Principal(user_id="email:viewer@example.edu", role="student", tenant_id="uni-a")
    monkeypatch.setattr(api_server, "_authenticated", lambda _handler: principal)
    assert api_server._optional_authenticated(_RateHandler("/analytics/event")) == principal
    monkeypatch.setattr(api_server, "_authenticated", lambda _handler: (_ for _ in ()).throw(PermissionError()))
    assert api_server._optional_authenticated(_RateHandler("/analytics/event")) is None


def test_infeasible_solve_does_not_clear_workspace_session(monkeypatch):
    original_schedule = {1: {"week": 1, "day": "MON", "slot": 1, "room_id": 1, "staff_id": 1}}
    session = api_server.SESSION_STORE.create(
        instance_json={"activities": {}},
        schedule=original_schedule,
        meta={"tenant_id": "default"},
    )
    normalized_original = dict(session.schedule)
    monkeypatch.setattr(
        api_server,
        "run_workspace_action",
        lambda **_kwargs: {"status": -1, "raw_status": 0, "schedule": {}, "hard_conflicts": []},
    )
    api_server._session_action_payload(session.session_id, "solve", {})
    assert api_server.SESSION_STORE.get(session.session_id).schedule == normalized_original


def test_session_action_preserves_tenant_and_creator_provenance(monkeypatch):
    security_meta = {
        "tenant_id": "uni-a",
        "created_by": "email:admin@example.edu",
        "created_by_role": "uni_admin",
    }
    session = api_server.SESSION_STORE.create(
        instance_json={"activities": {}},
        schedule={},
        meta={**security_meta, "workspace_label": "Spring planning"},
    )
    monkeypatch.setattr(
        api_server,
        "run_workspace_action",
        lambda **_kwargs: {
            "status": 4,
            "raw_status": 4,
            "schedule": {1: {"week": 1, "day": "MON", "slot": 1}},
            "meta": {
                "tenant_id": "attacker-tenant",
                "created_by": "email:attacker@example.edu",
                "created_by_role": "global_admin",
                "solver_backend": "planora-solver-service-v1",
            },
        },
    )

    api_server._session_action_payload(session.session_id, "solve", {})

    updated = api_server.SESSION_STORE.get(session.session_id)
    assert {key: updated.meta[key] for key in security_meta} == security_meta
    assert updated.meta["workspace_label"] == "Spring planning"
    assert updated.meta["solver_backend"] == "planora-solver-service-v1"


def _free_port() -> int:
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])
    except PermissionError:
        pytest.skip("Live socket binding is unavailable.")


def _status(url: str, *, method: str = "GET", payload: dict | None = None, headers: dict | None = None) -> int:
    status, _body = _status_and_body(url, method=method, payload=payload, headers=headers)
    return status


def _status_and_body(url: str, *, method: str = "GET", payload: dict | None = None, headers: dict | None = None) -> tuple[int, bytes]:
    status, body, _headers = _status_body_headers(url, method=method, payload=payload, headers=headers)
    return status, body


def _status_body_headers(url: str, *, method: str = "GET", payload: dict | None = None, headers: dict | None = None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310
            return int(response.status), response.read(), response.headers
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(), exc.headers
    except urllib.error.URLError:
        return 0, b"", {}


@pytest.mark.slow
def test_production_api_rejects_anonymous_forged_and_local_admin(tmp_path, monkeypatch):
    port = _free_port()
    database_path = tmp_path / "security.sqlite3"
    auth_secret = "test-secret-that-is-not-used-outside-this-process"
    token_pepper = "different-test-token-pepper-that-is-long-enough-1234"
    monkeypatch.setenv("PLANORA_PRODUCTION", "1")
    monkeypatch.setenv("PLANORA_TRUST_DEV_HEADERS", "0")
    monkeypatch.setenv("PLANORA_AUTH_SECRET", auth_secret)
    monkeypatch.setenv("PLANORA_TOKEN_PEPPER", token_pepper)
    monkeypatch.setenv("PLANORA_PUBLIC_BASE_URL", "https://scheduler.example.edu")
    monkeypatch.setenv("PLANORA_SMTP_HOST", "smtp.example.edu")

    store = PersistenceStore(database_path)
    account = Principal(
        user_id="email:session@example.edu",
        role="student",
        tenant_id="default",
        provider="email",
    )
    store.upsert_user(account)
    old_session = Principal(
        user_id=account.user_id,
        role=account.role,
        tenant_id=account.tenant_id,
        session_id="sid-before-refresh",
        provider=account.provider,
    )
    old_csrf = store.create_auth_session(old_session, old_session.session_id, ttl_seconds=300)
    old_token = create_auth_token(old_session, ttl_seconds=300)

    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "PLANORA_DB_PATH": str(database_path),
            "PLANORA_PRODUCTION": "1",
            "PLANORA_TRUST_DEV_HEADERS": "0",
            "PLANORA_AUTH_SECRET": auth_secret,
            "PLANORA_TOKEN_PEPPER": token_pepper,
            "PLANORA_PUBLIC_BASE_URL": "https://scheduler.example.edu",
            "PLANORA_SMTP_HOST": "smtp.example.edu",
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "api.server", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.time() + 10
        while time.time() < deadline and _status(f"http://127.0.0.1:{port}/health") != 200:
            time.sleep(0.1)
        for path in ("/health", "/ready"):
            status, body = _status_and_body(f"http://127.0.0.1:{port}{path}", method="HEAD")
            assert status == 200
            assert body == b""
        status, body = _status_and_body(f"http://127.0.0.1:{port}/auth/config", method="HEAD")
        assert status == 200
        assert body == b""
        assert _status(f"http://127.0.0.1:{port}/auth/config") == 200
        assert _status(f"http://127.0.0.1:{port}/auth/whoami") == 401
        assert _status(
            f"http://127.0.0.1:{port}/auth/whoami",
            headers={"X-Planora-Role": "admin", "X-Planora-Tenant": "victim"},
        ) == 401

        old_cookie = f"{AUTH_COOKIE}={old_token}; {CSRF_COOKIE}={old_csrf}"
        missing_csrf_status, missing_csrf_body = _status_and_body(
            f"http://127.0.0.1:{port}/auth/refresh",
            method="POST",
            payload={},
            headers={"Cookie": old_cookie},
        )
        assert missing_csrf_status == 403
        assert b"Invalid CSRF token" in missing_csrf_body

        refresh_status, refresh_body, _refresh_headers = _status_body_headers(
            f"http://127.0.0.1:{port}/auth/refresh",
            method="POST",
            payload={},
            headers={"Cookie": old_cookie, "X-CSRF-Token": old_csrf},
        )
        assert refresh_status == 200
        refreshed = json.loads(refresh_body.decode())
        new_token = str(refreshed["token"])
        new_csrf = str(refreshed["csrf_token"])
        assert _status(
            f"http://127.0.0.1:{port}/auth/whoami",
            headers={"Authorization": f"Bearer {old_token}"},
        ) in {401, 403}
        assert _status(
            f"http://127.0.0.1:{port}/auth/whoami",
            headers={"Authorization": f"Bearer {new_token}"},
        ) == 200

        new_cookie = f"{AUTH_COOKIE}={new_token}; {CSRF_COOKIE}={new_csrf}"
        assert _status(
            f"http://127.0.0.1:{port}/auth/logout",
            method="POST",
            payload={},
            headers={
                "Authorization": f"Bearer {new_token}",
                "Cookie": new_cookie,
                "X-CSRF-Token": new_csrf,
            },
        ) == 403
        logout_without_csrf, logout_without_csrf_body = _status_and_body(
            f"http://127.0.0.1:{port}/auth/logout",
            method="POST",
            payload={},
            headers={"Cookie": new_cookie},
        )
        assert logout_without_csrf == 403
        assert b"Invalid CSRF token" in logout_without_csrf_body
        assert _status(
            f"http://127.0.0.1:{port}/auth/logout",
            method="POST",
            payload={},
            headers={"Cookie": new_cookie, "X-CSRF-Token": new_csrf},
        ) == 200
        assert _status(
            f"http://127.0.0.1:{port}/auth/whoami",
            headers={"Authorization": f"Bearer {new_token}"},
        ) in {401, 403}

        assert _status(
            f"http://127.0.0.1:{port}/auth/login",
            method="POST",
            payload={"email": "attacker@example.edu", "password": "incorrect password"},
        ) == 403
        stale_cookie_status, stale_cookie_body = _status_and_body(
            f"http://127.0.0.1:{port}/auth/login",
            method="POST",
            payload={"email": "attacker@example.edu", "password": "incorrect password"},
            headers={"Cookie": "planora_session=stale-invalid-session"},
        )
        assert stale_cookie_status == 403
        assert b"Invalid CSRF token" not in stale_cookie_body
        assert b"Email or password is incorrect" in stale_cookie_body
        stale_refresh_status, stale_refresh_body = _status_and_body(
            f"http://127.0.0.1:{port}/auth/refresh",
            method="POST",
            payload={},
            headers={"Cookie": "planora_session=stale-invalid-session"},
        )
        assert stale_refresh_status in {401, 403}
        assert b"Invalid CSRF token" not in stale_refresh_body
        stale_logout_status, stale_logout_body, stale_logout_headers = _status_body_headers(
            f"http://127.0.0.1:{port}/auth/logout",
            method="POST",
            payload={},
            headers={"Cookie": "planora_session=stale-invalid-session"},
        )
        assert stale_logout_status == 200
        assert json.loads(stale_logout_body.decode()) == {"ok": True}
        set_cookies = stale_logout_headers.get_all("Set-Cookie", [])
        assert any(cookie.startswith("planora_session=;") and "Max-Age=0" in cookie for cookie in set_cookies)
        assert any(cookie.startswith("planora_csrf=;") and "Max-Age=0" in cookie for cookie in set_cookies)
        assert _status(
            f"http://127.0.0.1:{port}/analytics/event",
            method="POST",
            payload={
                "client_id": "security-test-client",
                "event_name": "page_view",
                "path": "/",
                "tenant_id": "public",
            },
        ) == 200
        assert _status(f"http://127.0.0.1:{port}/analytics/summary") == 401
        assert _status(f"http://127.0.0.1:{port}/sessions/unknown") == 401
        assert _status(f"http://127.0.0.1:{port}/jobs/unknown") == 401
    finally:
        process.terminate()
        process.wait(timeout=5)
