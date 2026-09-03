from __future__ import annotations

import pickle
from pathlib import Path

import pytest

import core.engine_cli as engine_cli
from main import normalize_instance_for_spec, stamp_instance_time
from services.contracts import SolveAttempt, SolveResult
from services.engine_backend import ENGINE_BACKEND_ID
from utils.generator import generate_instance


def _write_instance(tmp_path: Path) -> tuple[Path, Path]:
    inst = generate_instance("small_demo")
    normalize_instance_for_spec(inst)
    stamp_instance_time(inst, "08:30", 90, 0)
    in_path = tmp_path / "inst.pkl"
    out_path = tmp_path / "res.pkl"
    in_path.write_bytes(pickle.dumps(inst))
    return in_path, out_path


def _schedule() -> dict[int, dict[str, object]]:
    return {
        1: {
            "room_id": 1,
            "staff_id": 1,
            "week": 1,
            "day": "MON",
            "slot": 0,
            "duration": 1,
            "group_ids": [],
            "course_id": 1,
            "kind": "LEC",
        }
    }


def test_read_int_env_parses_and_validates(monkeypatch):
    monkeypatch.delenv("TT_CP_WORKERS", raising=False)
    assert engine_cli._read_int_env("TT_CP_WORKERS") is None

    monkeypatch.setenv("TT_CP_WORKERS", "3")
    assert engine_cli._read_int_env("TT_CP_WORKERS") == 3

    monkeypatch.setenv("TT_CP_WORKERS", "0")
    with pytest.raises(ValueError):
        engine_cli._read_int_env("TT_CP_WORKERS")


def test_shared_options_translate_desktop_environment(monkeypatch):
    monkeypatch.setenv("TT_ROOM_MODE", "greedy")
    monkeypatch.setenv("TT_OBJECTIVE_PROFILE", "university_fast")
    monkeypatch.setenv("TT_USE_OBJECTIVE", "0")
    monkeypatch.setenv("TT_RETRY_NO_OBJECTIVE", "0")
    monkeypatch.setenv("TT_TIME_LIMIT", "7.5")
    monkeypatch.setenv("TT_STRICT_TIME_LIMIT", "4")
    monkeypatch.setenv("TT_CP_WORKERS", "3")
    monkeypatch.setenv("TT_RANDOM_SEED", "17")
    monkeypatch.setenv("TT_PHASED_SOLVE", "0")

    options = engine_cli._shared_solve_options_from_env()

    assert options.room_mode == "greedy"
    assert options.objective_profile == "university_fast"
    assert options.use_objective is False
    assert options.retry_without_objective is False
    assert options.time_limit_seconds == pytest.approx(7.5)
    assert options.strict_limit_seconds == pytest.approx(4.0)
    assert options.workers == 3
    assert options.random_seed == 17


def test_shared_options_use_interactive_defaults(monkeypatch):
    for name in (
        "TT_ROOM_MODE",
        "TT_OBJECTIVE_PROFILE",
        "TT_USE_OBJECTIVE",
        "TT_TIME_LIMIT",
        "TT_STRICT_TIME_LIMIT",
    ):
        monkeypatch.delenv(name, raising=False)

    options = engine_cli._shared_solve_options_from_env()

    assert options.room_mode == "partitioned"
    assert options.objective_profile == "university_fast"
    assert options.use_objective is False
    assert options.time_limit_seconds == pytest.approx(15.0)


def test_engine_cli_uses_shared_backend_and_serializes_contract(
    monkeypatch, tmp_path: Path
):
    in_path, out_path = _write_instance(tmp_path)
    captured = {}

    def fake_solve(inst, options, *, progress_hook=None):
        captured["activities"] = len(inst.activities)
        captured["options"] = options
        if progress_hook is not None:
            progress_hook("test_progress", {"value": 1})
        return SolveResult(
            status=0,
            raw_status=2,
            schedule=_schedule(),
            attempts=[
                SolveAttempt(
                    room_mode="greedy",
                    use_objective=False,
                    time_limit_seconds=2.0,
                    raw_status=2,
                    elapsed_seconds=0.01,
                )
            ],
            hard_conflicts=[],
            meta={"quality": {"soft_penalty": 0}},
        )

    monkeypatch.setattr(engine_cli, "solve_with_engine", fake_solve)
    monkeypatch.setenv("TT_OBJECTIVE_PROFILE", "university_fast")
    monkeypatch.setenv("TT_CP_WORKERS", "2")
    monkeypatch.setattr(
        engine_cli.sys,
        "argv",
        ["engine_cli.py", str(in_path), str(out_path)],
    )

    assert engine_cli.main() == 0
    payload = pickle.loads(out_path.read_bytes())

    assert captured["activities"] > 0
    assert captured["options"].workers == 2
    assert payload["status"] == 0
    assert payload["raw_status"] == 2
    assert payload["schedule"] == _schedule()
    assert payload["hard_conflicts"] == []
    assert payload["meta"]["engine_backend"] == {
        "backend_id": ENGINE_BACKEND_ID,
        "transport": "desktop_qprocess_pickle_v1",
    }
    assert payload["meta"]["attempts"][0]["room_mode"] == "greedy"


def test_engine_cli_preserves_no_feasible_result(monkeypatch, tmp_path: Path):
    in_path, out_path = _write_instance(tmp_path)

    monkeypatch.setattr(
        engine_cli,
        "solve_with_engine",
        lambda *_args, **_kwargs: SolveResult(
            status=-1,
            raw_status=0,
            schedule={},
            attempts=[],
            hard_conflicts=[],
            meta={},
        ),
    )
    monkeypatch.setattr(
        engine_cli.sys,
        "argv",
        ["engine_cli.py", str(in_path), str(out_path)],
    )

    assert engine_cli.main() == 0
    payload = pickle.loads(out_path.read_bytes())
    assert payload["status"] == -1
    assert payload["schedule"] == {}
    assert "No feasible schedule" in payload["error"]


def test_engine_cli_rejects_invalid_invocation(monkeypatch):
    monkeypatch.setattr(engine_cli.sys, "argv", ["engine_cli.py"])
    assert engine_cli.main() == 2


def test_profile_budget_split_remains_compatible():
    feasibility, improve = engine_cli._profile_budget_split(
        profile="quality_first",
        time_limit=8.0,
        feasibility_seconds=None,
        improve_total_seconds=0.0,
    )
    assert feasibility == pytest.approx(5.2)
    assert improve == pytest.approx(2.8)
