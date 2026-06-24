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
from services.auth_service import Principal


ROOT = Path(__file__).resolve().parent.parent


class _RateHandler:
    def __init__(self, path: str = "/auth/config") -> None:
        self.path = path
        self.headers: dict[str, str] = {}
        self.client_address = ("203.0.113.10", 12345)


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
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()
    except urllib.error.URLError:
        return 0, b""


@pytest.mark.slow
def test_production_api_rejects_anonymous_forged_and_local_admin(tmp_path):
    port = _free_port()
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "PLANORA_DB_PATH": str(tmp_path / "security.sqlite3"),
            "PLANORA_PRODUCTION": "1",
            "PLANORA_TRUST_DEV_HEADERS": "0",
            "PLANORA_AUTH_SECRET": "test-secret-that-is-not-used-outside-this-process",
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
        assert _status(
            f"http://127.0.0.1:{port}/auth/login",
            method="POST",
            payload={"email": "attacker@example.edu", "password": "incorrect password"},
        ) == 403
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
