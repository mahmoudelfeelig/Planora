from __future__ import annotations

import pickle
from pathlib import Path

import pytest
from ortools.sat.python import cp_model

import core.engine_cli as engine_cli
from main import normalize_instance_for_spec, stamp_instance_time
from utils.generator import generate_instance


def _write_instance(tmp_path: Path) -> tuple[Path, Path]:
    inst = generate_instance("small_demo")
    normalize_instance_for_spec(inst)
    stamp_instance_time(inst, "08:30", 90, 0)
    in_path = tmp_path / "inst.pkl"
    out_path = tmp_path / "res.pkl"
    in_path.write_bytes(pickle.dumps(inst))
    return in_path, out_path


def test_read_int_env_parses_and_validates(monkeypatch):
    monkeypatch.delenv("TT_CP_WORKERS", raising=False)
    assert engine_cli._read_int_env("TT_CP_WORKERS") is None

    monkeypatch.setenv("TT_CP_WORKERS", "3")
    assert engine_cli._read_int_env("TT_CP_WORKERS") == 3

    monkeypatch.setenv("TT_CP_WORKERS", "0")
    with pytest.raises(ValueError):
        engine_cli._read_int_env("TT_CP_WORKERS")


def test_engine_cli_passes_workers_to_solver(monkeypatch, tmp_path: Path):
    in_path, out_path = _write_instance(tmp_path)
    calls: list[tuple[str, bool, int | None]] = []

    class FakeSolver:
        def __init__(self, inst, room_mode="cp_rooms", *, use_objective=True):
            self.room_mode = room_mode
            self.use_objective = use_objective

        def solve(self, *, time_limit_seconds=None, workers=None, random_seed=None, log_progress=False):
            calls.append((self.room_mode, self.use_objective, workers))
            return object(), cp_model.FEASIBLE

        def extract_solution(self, sat):
            return {}

    monkeypatch.setattr(engine_cli, "TimetableSolver", FakeSolver)
    monkeypatch.setenv("TT_ROOM_MODE", "cp_rooms")
    monkeypatch.setenv("TT_CP_WORKERS", "3")
    monkeypatch.setattr(engine_cli.sys, "argv", ["engine_cli.py", str(in_path), str(out_path)])

    rc = engine_cli.main()
    assert rc == 0
    assert out_path.exists()
    assert calls == [("cp_rooms", True, 3)]
    payload = pickle.loads(out_path.read_bytes())
    assert "meta" in payload and "attempts" in payload["meta"]


def test_engine_cli_retry_without_objective_keeps_workers(monkeypatch, tmp_path: Path):
    in_path, out_path = _write_instance(tmp_path)
    calls: list[tuple[str, bool, int | None]] = []
    statuses = [cp_model.UNKNOWN, cp_model.FEASIBLE]

    class FakeSolver:
        def __init__(self, inst, room_mode="cp_rooms", *, use_objective=True):
            self.room_mode = room_mode
            self.use_objective = use_objective

        def solve(self, *, time_limit_seconds=None, workers=None, random_seed=None, log_progress=False):
            calls.append((self.room_mode, self.use_objective, workers))
            return object(), statuses.pop(0)

        def extract_solution(self, sat):
            return {}

    monkeypatch.setattr(engine_cli, "TimetableSolver", FakeSolver)
    monkeypatch.setenv("TT_ROOM_MODE", "cp_rooms")
    monkeypatch.setenv("TT_CP_WORKERS", "5")
    monkeypatch.setattr(engine_cli.sys, "argv", ["engine_cli.py", str(in_path), str(out_path)])

    rc = engine_cli.main()
    assert rc == 0
    assert out_path.exists()
    assert calls == [("cp_rooms", True, 5), ("cp_rooms", False, 5)]


def test_engine_cli_greedy_fallback_after_retry(monkeypatch, tmp_path: Path):
    in_path, out_path = _write_instance(tmp_path)
    calls: list[tuple[str, bool, int | None]] = []
    statuses = [cp_model.UNKNOWN, cp_model.UNKNOWN, cp_model.FEASIBLE]

    class FakeSolver:
        def __init__(self, inst, room_mode="cp_rooms", *, use_objective=True):
            self.room_mode = room_mode
            self.use_objective = use_objective

        def solve(self, *, time_limit_seconds=None, workers=None, random_seed=None, log_progress=False):
            calls.append((self.room_mode, self.use_objective, workers))
            return object(), statuses.pop(0)

        def extract_solution(self, sat):
            return {}

    monkeypatch.setattr(engine_cli, "TimetableSolver", FakeSolver)
    monkeypatch.setenv("TT_ROOM_MODE", "cp_rooms")
    monkeypatch.setenv("TT_CP_WORKERS", "6")
    monkeypatch.setenv("TT_RETRY_NO_OBJECTIVE", "1")
    monkeypatch.setattr(engine_cli.sys, "argv", ["engine_cli.py", str(in_path), str(out_path)])

    rc = engine_cli.main()
    assert rc == 0
    assert out_path.exists()
    assert calls == [
        ("cp_rooms", True, 6),
        ("cp_rooms", False, 6),
        ("greedy", False, 6),
    ]
