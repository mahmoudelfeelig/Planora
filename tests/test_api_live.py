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


def _http_json_headers(method: str, url: str, headers: dict, payload: dict | None = None) -> dict:
    data = None
    request_headers = dict(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


@pytest.mark.slow
def test_live_api_server_health_solve_and_portfolio_contract(tmp_path):
    port = _find_free_port()
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(ROOT))
    env["PLANORA_DB_PATH"] = str(tmp_path / "planora-api.sqlite3")
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

        presets = _http_json("GET", f"http://127.0.0.1:{port}/presets")
        assert "small_demo" in presets["presets"]
        capabilities = _http_json("GET", f"http://127.0.0.1:{port}/capabilities")
        assert "import_timetable_csv" in capabilities["actions"]
        assert "focused_cp_sat_polish" in capabilities["actions"]
        assert "session_workspace" in capabilities["actions"]
        assert "async_jobs" in capabilities["actions"]
        assert "move_target_deltas" in capabilities["actions"]
        assert "tenant_auth_headers" in capabilities["actions"]
        assert "sqlite_persistence" in capabilities["actions"]
        assert "audit_log" in capabilities["actions"]
        assert "thin_day" in capabilities["focus_terms"]
        whoami = _http_json("GET", f"http://127.0.0.1:{port}/auth/whoami")
        assert whoami["role"] == "admin"
        assert "tenants:read_all" in whoami["permissions"]
        auth_config = _http_json("GET", f"http://127.0.0.1:{port}/auth/config")
        assert auth_config["mode"] == "email_password"
        analytics_event = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/analytics/event",
            {
                "client_id": "pytest-client-123456",
                "event_name": "page_view",
                "path": "/workspace",
                "view_name": "workspace",
                "viewport_width": 1200,
                "viewport_height": 800,
                "tenant_id": "default",
                "user_role": "anonymous",
                "details": {"source": "live-test"},
            },
        )
        assert analytics_event == {"ok": True}
        access = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/access",
            {"action": "create_group", "name": "Uni A admins", "tenant_id": "uni-a"},
        )
        group_id = access["groups"][0]["group_id"]
        invite = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/access",
            {"action": "create_invite", "group_id": group_id, "role": "uni_admin", "code": "uni-admin-invite", "tenant_id": "uni-a"},
        )
        assert invite["new_invite_code"] == "uni-admin-invite"
        registered = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/auth/register",
            {
                "email": "uni-admin@example.edu",
                "password": "correct horse battery",
                "display_name": "Uni Admin",
                "invite_code": "uni-admin-invite",
            },
        )
        assert registered["verification_token"]
        _http_json("POST", f"http://127.0.0.1:{port}/auth/verify", {"token": registered["verification_token"]})
        login = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/auth/login",
            {"email": "uni-admin@example.edu", "password": "correct horse battery"},
        )
        assert login["token"]
        token_whoami = _http_json_headers(
            "GET",
            f"http://127.0.0.1:{port}/auth/whoami",
            {"Authorization": f"Bearer {login['token']}"},
        )
        assert token_whoami["tenant_id"] == "uni-a"
        access_after_login = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/access",
            {"action": "create_group", "name": "Uni A review board", "tenant_id": "uni-a"},
        )
        review_group_id = [row["group_id"] for row in access_after_login["groups"] if row["name"] == "Uni A review board"][0]
        second_invite = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/access",
            {"action": "create_invite", "group_id": review_group_id, "role": "professor", "code": "review-board-invite", "tenant_id": "uni-a"},
        )
        assert second_invite["new_invite_code"] == "review-board-invite"
        joined = _http_json_headers(
            "POST",
            f"http://127.0.0.1:{port}/access/join-invite",
            {"Authorization": f"Bearer {login['token']}"},
            {"invite_code": "review-board-invite"},
        )
        assert review_group_id in joined["principal"]["groups"]
        parity = _http_json("GET", f"http://127.0.0.1:{port}/parity")
        assert parity["coverage_percent"] > 0
        system = _http_json("GET", f"http://127.0.0.1:{port}/system")
        assert system["database"]["schema_version"] >= 2
        assert "auth" in system
        analytics = _http_json("GET", f"http://127.0.0.1:{port}/analytics/summary")
        assert analytics["events"] >= 1
        assert analytics["visitors"] >= 1
        assert any(row["path"] == "/workspace" for row in analytics["top_paths"])
        openapi = _http_json("GET", f"http://127.0.0.1:{port}/openapi.json")
        assert openapi["openapi"].startswith("3.")
        assert "/sessions" in openapi["paths"]
        assert "/auth/config" in openapi["paths"]
        assert "/analytics/event" in openapi["paths"]
        assert "/analytics/summary" in openapi["paths"]
        preset_payload = _http_json("GET", f"http://127.0.0.1:{port}/preset/small_demo")
        assert preset_payload["mode"] == "small_demo"
        assert preset_payload["instance"]["activities"]

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
        assert "quality" in solve_result["meta"]

        score_payload = {
            "instance": solve_payload["instance"],
            "schedule": solve_result["schedule"],
        }
        score_result = _http_json("POST", f"http://127.0.0.1:{port}/score", score_payload)
        assert "soft_penalty" in score_result
        assert "drivers" in score_result

        improve_result = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/improve",
            {
                **score_payload,
                "focus_term": "thin_day",
                "options": {"iterations": 2, "max_seconds": 0.01},
            },
        )
        assert improve_result["schedule"]
        assert "global_after" in improve_result

        export_result = _http_json("POST", f"http://127.0.0.1:{port}/export/csv", score_payload)
        assert export_result["content_type"] == "text/csv"
        assert "activity_id" in export_result["content"].splitlines()[0]

        imported = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/import/csv",
            {
                "filename": "tiny.csv",
                "content": (
                    "week,day,slot,course,group,room,kind,lecturer,ta\n"
                    "1,MON,1,CS101 Intro,G1,R1,LEC,Prof A,TA A\n"
                    "1,TUE,1,CS101 Intro,G1,R2,TUT,Prof A,TA A\n"
                ),
            },
        )
        assert imported["instance"]["activities"]
        assert imported["schedule"]
        assert imported["score"]["soft_penalty"] >= 0

        session = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/sessions",
            {"instance": solve_payload["instance"], "schedule": solve_result["schedule"]},
        )
        session_id = session["session_id"]
        assert session_id
        session_score = _http_json("POST", f"http://127.0.0.1:{port}/sessions/{session_id}/score", {})
        assert "soft_penalty" in session_score["result"]
        first_activity = int(next(iter(solve_result["schedule"].keys())))
        move_deltas = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/sessions/{session_id}/move-deltas",
            {
                "activity_id": first_activity,
                "week": solve_result["schedule"][str(first_activity)]["week"],
                "limit": 8,
            },
        )
        assert move_deltas["result"]["targets"]
        assert {"ok", "delta", "hard_conflict_count"}.issubset(move_deltas["result"]["targets"][0])
        lock_result = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/sessions/{session_id}/lock",
            {"activity_id": first_activity},
        )
        assert str(first_activity) in {
            str(key) for key in lock_result["result"]["locked_activities"].keys()
        }
        move_result = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/sessions/{session_id}/move",
            {
                "activity_id": first_activity,
                "day": solve_result["schedule"][str(first_activity)]["day"],
                "slot": solve_result["schedule"][str(first_activity)]["slot"],
                "room_id": solve_result["schedule"][str(first_activity)]["room_id"],
                "staff_id": solve_result["schedule"][str(first_activity)]["staff_id"],
            },
        )
        assert move_result["result"]["ok"] is True

        job = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/jobs/score",
            {"session_id": session_id},
        )
        assert job["job_id"]
        deadline = time.time() + 5.0
        job_result = job
        while time.time() < deadline:
            job_result = _http_json("GET", f"http://127.0.0.1:{port}/jobs/{job['job_id']}")
            if job_result["status"] in {"complete", "failed"}:
                break
            time.sleep(0.1)
        assert job_result["status"] == "complete"
        event_request = urllib.request.Request(f"http://127.0.0.1:{port}/jobs/{job['job_id']}/events")
        with urllib.request.urlopen(event_request, timeout=10) as response:  # nosec B310
            assert "event: job" in response.read().decode("utf-8")

        saved = _http_json(
            "POST",
            f"http://127.0.0.1:{port}/projects",
            {"name": f"pytest_{port}", "session_id": session_id},
        )
        assert saved["saved"]["name"].startswith("pytest_")
        projects = _http_json("GET", f"http://127.0.0.1:{port}/projects")
        assert any(row["name"] == saved["saved"]["name"] for row in projects["projects"])
        loaded = _http_json("GET", f"http://127.0.0.1:{port}/projects/{saved['saved']['name']}")
        assert loaded["instance"]["activities"]
        audit = _http_json("GET", f"http://127.0.0.1:{port}/audit")
        assert any(row["action"] == "project.save" for row in audit["events"])

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
