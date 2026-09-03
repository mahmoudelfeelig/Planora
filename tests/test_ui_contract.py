from __future__ import annotations

import pytest

from api.schema import openapi_schema
from services.application_service import (
    improve_options_from_payload,
    solve_options_from_payload,
)
from services.engine_backend import engine_contract
from services.ui_contract import (
    generator_mode_for_scenario,
    public_preset_ids,
    ui_contract,
)
from ui.backend_client import HttpBackendClient, LocalBackendClient
from utils.generator import generate_instance


def test_public_ui_contract_is_small_versioned_and_engine_neutral():
    contract = ui_contract()

    assert contract["contract_version"] == "planora.ui.v1"
    assert [scenario["id"] for scenario in contract["scenarios"]] == [
        "demo",
        "spring_2023",
        "import",
    ]
    assert [mode["id"] for mode in contract["run_modes"]] == [
        "fast",
        "balanced",
        "quality",
    ]
    assert all("solve" not in mode and "improve" not in mode for mode in contract["run_modes"])
    assert len(contract["tutorial"]) == 5
    assert public_preset_ids() == ["demo", "spring_2023"]
    assert generator_mode_for_scenario("spring_2023") == "ss23_uni_like"
    assert generator_mode_for_scenario("target_case") == "target_case"


def test_run_modes_map_server_side_with_bounded_advanced_overrides():
    inst = generate_instance("small_demo")

    fast = solve_options_from_payload(inst, {"run_mode": "fast"})
    balanced = solve_options_from_payload(inst, {"run_mode": "balanced"})
    quality = solve_options_from_payload(inst, {"run_mode": "quality"})
    override = solve_options_from_payload(
        inst,
        {
            "run_mode": "fast",
            "advanced_overrides": {"solve": {"time_limit_seconds": 9.0}},
        },
    )

    assert fast.time_limit_seconds < balanced.time_limit_seconds < quality.time_limit_seconds
    assert override.time_limit_seconds == pytest.approx(9.0)
    assert improve_options_from_payload({"run_mode": "quality"}).max_seconds == pytest.approx(8.0)
    with pytest.raises(ValueError, match="Unknown run mode"):
        solve_options_from_payload(inst, {"run_mode": "invented"})


def test_local_client_and_openapi_publish_the_same_contract():
    local = LocalBackendClient().capabilities()
    schema = openapi_schema()

    assert local["ui_contract"] == ui_contract()
    assert local["shared_backend"] == engine_contract()
    assert schema["components"]["schemas"]["RunMode"]["enum"] == [
        "fast",
        "balanced",
        "quality",
    ]


def test_remote_client_sends_the_configured_bearer_token(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ui_contract": {"contract_version": "planora.ui.v1"}}'

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("ui.backend_client.urllib.request.urlopen", fake_urlopen)

    client = HttpBackendClient("https://planora.example/api", bearer_token="secret-token")
    client.capabilities()

    assert captured == {"authorization": "Bearer secret-token", "timeout": 180}


def test_remote_improve_keeps_runtime_hooks_out_of_the_json_payload(monkeypatch):
    inst = generate_instance("small_demo")
    captured = {}
    client = HttpBackendClient("https://planora.example/api", bearer_token="token")

    def fake_request(path, *, payload=None):
        captured["path"] = path
        captured["payload"] = payload
        return {"schedule": {}, "after": {}, "global_after": {}, "meta": {}}

    monkeypatch.setattr(client, "_request", fake_request)
    client.improve(
        inst,
        {},
        run_mode="balanced",
        options={"iterations": 20, "max_seconds": 0.1},
        focus_term="room_changes",
        progress_hook=lambda *_args, **_kwargs: None,
        stop_hook=lambda: False,
    )

    assert captured["path"] == "/improve"
    assert captured["payload"]["focus_term"] == "room_changes"
    assert "progress_hook" not in captured["payload"]
    assert "stop_hook" not in captured["payload"]
