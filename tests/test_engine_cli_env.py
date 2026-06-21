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


def test_engine_cli_phased_solve_runs_feasibility_then_improves(monkeypatch, tmp_path: Path):
    in_path, out_path = _write_instance(tmp_path)
    calls: list[tuple[str, bool, int | None, float | None]] = []
    improve_calls: list[tuple[int, float | None]] = []

    class FakeSolver:
        def __init__(self, inst, room_mode="cp_rooms", *, use_objective=True):
            self.room_mode = room_mode
            self.use_objective = use_objective

        def solve(self, *, time_limit_seconds=None, workers=None, random_seed=None, log_progress=False):
            calls.append((self.room_mode, self.use_objective, workers, time_limit_seconds))
            return object(), cp_model.FEASIBLE

        def extract_solution(self, sat):
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

    class FakeImprover:
        def __init__(self, inst):
            pass

        def compute_soft_penalty(self, schedule):
            info = schedule[1]
            return 5 if info["slot"] == 1 else 10

        def improve(self, schedule, *, iterations=0, max_seconds=None, **kwargs):
            improve_calls.append((int(iterations), max_seconds))
            out = {a_id: info.copy() for a_id, info in schedule.items()}
            out[1]["slot"] = 1
            return out

    monkeypatch.setattr(engine_cli, "TimetableSolver", FakeSolver)
    monkeypatch.setattr(engine_cli, "LocalSearchImprover", FakeImprover)
    monkeypatch.setattr(engine_cli, "validate_schedule_against_instance", lambda *args, **kwargs: [])
    monkeypatch.setenv("TT_ROOM_MODE", "cp_rooms")
    monkeypatch.setenv("TT_CP_WORKERS", "2")
    monkeypatch.setenv("TT_PHASED_SOLVE", "1")
    monkeypatch.setenv("TT_FEASIBILITY_SECONDS", "7")
    monkeypatch.setenv("TT_IMPROVE_TOTAL_SECONDS", "2")
    monkeypatch.setenv("TT_IMPROVE_SLICE_SECONDS", "1")
    monkeypatch.setenv("TT_IMPROVE_ITERS_PER_SLICE", "123")
    monkeypatch.setenv("TT_IMPROVE_MAX_ROUNDS", "2")
    monkeypatch.setattr(engine_cli.sys, "argv", ["engine_cli.py", str(in_path), str(out_path)])

    rc = engine_cli.main()
    assert rc == 0
    assert out_path.exists()
    assert len(calls) == 1
    assert calls[0][:3] == ("cp_rooms", False, 2)
    assert calls[0][3] == pytest.approx(7.0)
    assert improve_calls == [(123, 1.0), (123, 1.0)]

    payload = pickle.loads(out_path.read_bytes())
    meta = payload.get("meta", {})
    phased = meta.get("phased", {})
    improvement = meta.get("improvement", {})
    assert phased.get("enabled") is True
    assert improvement.get("enabled") is True
    assert improvement.get("start_penalty") == 10
    assert improvement.get("final_penalty") == 5
    assert payload["schedule"][1]["slot"] == 1


def test_engine_cli_quality_first_respects_explicit_total_time_limit():
    feasibility, improve = engine_cli._profile_budget_split(
        profile="quality_first",
        time_limit=8.0,
        feasibility_seconds=None,
        improve_total_seconds=0.0,
    )

    assert feasibility == pytest.approx(5.2)
    assert improve == pytest.approx(2.8)
    assert feasibility + improve == pytest.approx(8.0)


def test_engine_cli_fast_feasible_uses_full_time_limit_without_objective(monkeypatch, tmp_path: Path):
    in_path, out_path = _write_instance(tmp_path)
    calls: list[float | None] = []

    class FakeSolver:
        def __init__(self, inst, room_mode="cp_rooms", *, use_objective=True):
            self.room_mode = room_mode
            self.use_objective = use_objective

        def solve(self, *, time_limit_seconds=None, workers=None, random_seed=None, log_progress=False):
            calls.append(time_limit_seconds)
            return object(), cp_model.FEASIBLE

        def extract_solution(self, sat):
            return {}

    monkeypatch.setattr(engine_cli, "TimetableSolver", FakeSolver)
    monkeypatch.setenv("TT_OBJECTIVE_PROFILE", "fast_feasible")
    monkeypatch.setenv("TT_USE_OBJECTIVE", "0")
    monkeypatch.setenv("TT_TIME_LIMIT", "60")
    monkeypatch.setattr(engine_cli.sys, "argv", ["engine_cli.py", str(in_path), str(out_path)])

    rc = engine_cli.main()

    assert rc == 0
    assert calls == [pytest.approx(60.0)]


def test_engine_cli_rejects_post_extract_hard_conflicts(monkeypatch, tmp_path: Path):
    in_path, out_path = _write_instance(tmp_path)

    class FakeSolver:
        def __init__(self, inst, room_mode="cp_rooms", *, use_objective=True):
            self.room_mode = room_mode
            self.use_objective = use_objective

        def solve(self, *, time_limit_seconds=None, workers=None, random_seed=None, log_progress=False):
            return object(), cp_model.FEASIBLE

        def extract_solution(self, sat):
            return {1: {"week": 1, "day": "MON", "slot": 0, "duration": 1, "room_id": 1, "staff_id": 1, "course_id": 1, "group_ids": [], "kind": "LEC"}}

    monkeypatch.setattr(engine_cli, "TimetableSolver", FakeSolver)
    monkeypatch.setattr(engine_cli, "validate_schedule_against_instance", lambda *args, **kwargs: ["group overlap"])
    monkeypatch.setattr(engine_cli.sys, "argv", ["engine_cli.py", str(in_path), str(out_path)])

    rc = engine_cli.main()
    assert rc == 0
    payload = pickle.loads(out_path.read_bytes())
    assert payload["status"] == -3
    assert payload["schedule"] == {}
    assert "hard conflicts" in str(payload.get("error", "")).lower()


def test_engine_cli_phased_improvement_rejects_hard_conflict_candidates(monkeypatch, tmp_path: Path):
    in_path, out_path = _write_instance(tmp_path)

    class FakeSolver:
        def __init__(self, inst, room_mode="cp_rooms", *, use_objective=True):
            self.room_mode = room_mode
            self.use_objective = use_objective

        def solve(self, *, time_limit_seconds=None, workers=None, random_seed=None, log_progress=False):
            return object(), cp_model.FEASIBLE

        def extract_solution(self, sat):
            return {
                1: {
                    "week": 1,
                    "day": "MON",
                    "slot": 0,
                    "duration": 1,
                    "room_id": 1,
                    "staff_id": 1,
                    "course_id": 1,
                    "group_ids": [],
                    "kind": "LEC",
                }
            }

    class FakeImprover:
        def __init__(self, inst):
            pass

        def compute_soft_penalty(self, schedule):
            return int(schedule[1]["slot"])

        def improve(self, schedule, *, iterations=0, max_seconds=None, **kwargs):
            out = {a_id: info.copy() for a_id, info in schedule.items()}
            out[1]["slot"] = 1
            return out

    def _fake_validate(_inst, schedule, **kwargs):
        # Slot 1 is considered hard-conflicting for this test.
        return ["hard conflict"] if int(schedule[1]["slot"]) == 1 else []

    monkeypatch.setattr(engine_cli, "TimetableSolver", FakeSolver)
    monkeypatch.setattr(engine_cli, "LocalSearchImprover", FakeImprover)
    monkeypatch.setattr(engine_cli, "validate_schedule_against_instance", _fake_validate)
    monkeypatch.setenv("TT_PHASED_SOLVE", "1")
    monkeypatch.setenv("TT_IMPROVE_TOTAL_SECONDS", "1")
    monkeypatch.setenv("TT_IMPROVE_SLICE_SECONDS", "1")
    monkeypatch.setenv("TT_IMPROVE_ITERS_PER_SLICE", "50")
    monkeypatch.setenv("TT_IMPROVE_MAX_ROUNDS", "1")
    monkeypatch.setattr(engine_cli.sys, "argv", ["engine_cli.py", str(in_path), str(out_path)])

    rc = engine_cli.main()
    assert rc == 0
    payload = pickle.loads(out_path.read_bytes())
    assert payload["status"] in (0, 4)
    assert payload["schedule"][1]["slot"] == 0
    rounds = payload.get("meta", {}).get("improvement", {}).get("rounds", [])
    assert rounds
    assert rounds[0].get("hard_conflicts") == 1
    assert rounds[0].get("accepted") is False
