from __future__ import annotations

import re
from pathlib import Path

import pytest

import api.actions as api_actions
import services.engine_backend as engine_backend
from services.application_service import solve_options_from_payload
from services.contracts import SolveResult
from utils.generator import generate_instance, instance_to_json


ROOT = Path(__file__).resolve().parent.parent


def _web_number(source: str, name: str) -> int:
    match = re.search(rf"{re.escape(name)}:\s*(\d+)", source)
    assert match is not None
    return int(match.group(1))


def test_interactive_contract_is_shared_with_web_defaults():
    contract = engine_backend.engine_contract()
    source = (ROOT / "web/src/react/solver_settings.ts").read_text(encoding="utf-8")

    assert contract["backend_id"] == "planora-solver-service-v1"
    assert f'roomMode: "{contract["solve"]["room_mode"]}"' in source
    assert f'profile: "{contract["solve"]["objective_profile"]}"' in source
    assert _web_number(source, "timeLimitSeconds") == int(
        contract["solve"]["time_limit_seconds"]
    )
    assert _web_number(source, "improveIterations") == int(
        contract["improve"]["iterations"]
    )
    assert _web_number(source, "improveSeconds") == int(
        contract["improve"]["max_seconds"]
    )


def test_omitted_http_options_use_interactive_contract():
    inst = generate_instance("small_demo")
    options = solve_options_from_payload(inst, {})
    contract = engine_backend.engine_contract()["solve"]

    assert options.room_mode == contract["room_mode"]
    assert options.objective_profile == contract["objective_profile"]
    assert options.time_limit_seconds == pytest.approx(
        contract["time_limit_seconds"]
    )
    assert options.use_objective is contract["use_objective"]


def test_http_solve_routes_through_shared_engine(monkeypatch):
    inst = generate_instance("small_demo")
    captured = {}

    def fake_solve(received, options):
        captured["instance"] = received
        captured["options"] = options
        return SolveResult(
            status=-1,
            raw_status=0,
            schedule={},
            attempts=[],
            hard_conflicts=[],
            meta={
                "engine_backend": {
                    "backend_id": engine_backend.ENGINE_BACKEND_ID,
                    "operation": "solve",
                    "elapsed_seconds": 0.0,
                }
            },
        )

    monkeypatch.setattr(api_actions, "solve_with_engine", fake_solve)
    payload = api_actions.handle_solve({"instance": instance_to_json(inst)})

    assert captured["instance"].activities
    assert captured["options"].time_limit_seconds == pytest.approx(15.0)
    assert payload["meta"]["engine_backend"]["backend_id"] == (
        engine_backend.ENGINE_BACKEND_ID
    )


def test_http_improve_routes_through_shared_engine_defaults(monkeypatch):
    inst = generate_instance("small_demo")
    captured = {}

    def fake_improve(received, schedule, options, *, focus_term=""):
        captured["instance"] = received
        captured["schedule"] = schedule
        captured["options"] = options
        captured["focus_term"] = focus_term
        return {
            "schedule": {},
            "meta": {
                "engine_backend": {
                    "backend_id": engine_backend.ENGINE_BACKEND_ID,
                    "operation": "improve",
                    "elapsed_seconds": 0.0,
                }
            },
        }

    monkeypatch.setattr(api_actions, "improve_with_engine", fake_improve)
    payload = api_actions.handle_improve(
        {"instance": instance_to_json(inst), "schedule": {}}
    )

    assert captured["instance"].activities
    assert captured["options"].iterations == 500
    assert captured["options"].max_seconds == pytest.approx(2.0)
    assert payload["meta"]["engine_backend"]["backend_id"] == (
        engine_backend.ENGINE_BACKEND_ID
    )


def test_capabilities_publish_shared_engine_contract():
    source = (ROOT / "api/server.py").read_text(encoding="utf-8")
    assert '"shared_backend": engine_contract()' in source
