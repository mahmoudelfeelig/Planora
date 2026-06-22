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


ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])
    except PermissionError:
        pytest.skip("Live socket binding is unavailable.")


def _status(url: str, *, method: str = "GET", payload: dict | None = None, headers: dict | None = None) -> int:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except urllib.error.URLError:
        return 0


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
