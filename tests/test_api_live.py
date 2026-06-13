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

from utils.generator import generate_instance, instance_to_json


ROOT = Path(__file__).resolve().parent.parent


def _find_free_port() -> int:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])
    except PermissionError:
        pytest.skip("Live socket binding is not permitted in this environment.")


def _http_json(method: str, url: str, payload: dict | None = None) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


@pytest.mark.slow
def test_live_api_server_health_solve_and_portfolio_contract():
    port = _find_free_port()
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(ROOT))
    proc = subprocess.Popen(
        [sys.executable, "-m", "api.server", "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=str(ROOT),
    )

    try:
        deadline = time.time() + 15.0
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                health = _http_json("GET", f"http://127.0.0.1:{port}/health")
                if health == {"ok": True}:
                    break
            except Exception as exc:  # pragma: no cover - timing dependent
                last_error = exc
                time.sleep(0.2)
        else:
            raise AssertionError(f"API server did not become ready: {last_error}")

        inst = generate_instance("small_demo")
        solve_payload = {
            "instance": instance_to_json(inst),
            "options": {
                "room_mode": "greedy",
                "use_objective": False,
                "retry_without_objective": False,
                "objective_profile": "balanced",
                "time_limit_seconds": 8.0,
                "workers": 1,
            },
        }
        solve_result = _http_json("POST", f"http://127.0.0.1:{port}/solve", solve_payload)
        assert int(solve_result["status"]) in (0, 4)
        assert solve_result["schedule"]
        assert solve_result["hard_conflicts"] == []

        portfolio_result = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/portfolio",
            solve_payload,
        )
        assert int(portfolio_result["best_index"]) >= 0
        assert len(portfolio_result["candidates"]) == 3

        graphql_result = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/graphql",
            {"query": "query { solve }", **solve_payload},
        )
        assert "data" in graphql_result
        assert graphql_result["data"]["solve"]["schedule"]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            proc.kill()
            proc.wait(timeout=10)
