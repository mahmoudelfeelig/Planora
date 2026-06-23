from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, Tuple

from services.application_service import solve_options_from_payload
from services.auth_service import Principal, require_permission
from services.contracts import ImproveOptions, SolveOptions
from services.schedule_ops_service import (
    cp_sat_polish_shared,
    export_schedule_csv_text,
    improve_schedule_shared,
    normalize_schedule,
    score_schedule,
)
from services.solver_service import solve_instance, solve_portfolio
from utils.io import instance_from_json


def load_instance_and_options(payload: Dict[str, Any]) -> Tuple[Any, SolveOptions]:
    inst_raw = payload.get("instance")
    options_raw = payload.get("options") or {}
    if not isinstance(inst_raw, dict):
        raise ValueError("Payload missing instance JSON.")
    if not isinstance(options_raw, dict):
        raise ValueError("Payload options must be an object.")
    inst = instance_from_json(inst_raw)
    options = solve_options_from_payload(inst, payload)
    return inst, options


def load_instance_and_schedule(payload: Dict[str, Any]) -> Tuple[Any, Dict[int, Dict[str, Any]]]:
    inst_raw = payload.get("instance")
    schedule_raw = payload.get("schedule")
    if not isinstance(inst_raw, dict):
        raise ValueError("Payload missing instance JSON.")
    if not isinstance(schedule_raw, dict):
        raise ValueError("Payload missing schedule JSON.")
    return instance_from_json(inst_raw), normalize_schedule(schedule_raw)


def result_payload(result) -> Dict[str, Any]:
    return {
        "status": int(result.status),
        "raw_status": int(result.raw_status),
        "schedule": result.schedule,
        "hard_conflicts": list(result.hard_conflicts),
        "meta": dict(result.meta or {}),
        "attempts": [
            {
                "room_mode": str(attempt.room_mode),
                "use_objective": bool(attempt.use_objective),
                "time_limit_seconds": attempt.time_limit_seconds,
                "raw_status": int(attempt.raw_status),
                "objective_value": attempt.objective_value,
                "best_objective_bound": attempt.best_objective_bound,
                "relative_gap": attempt.relative_gap,
            }
            for attempt in (result.attempts or [])
        ],
    }


def handle_solve(payload: Dict[str, Any]) -> Dict[str, Any]:
    inst, options = load_instance_and_options(payload)
    result = solve_instance(inst, options)
    return result_payload(result)


def handle_portfolio(payload: Dict[str, Any]) -> Dict[str, Any]:
    inst, options = load_instance_and_options(payload)
    result = solve_portfolio(inst, options)
    return {
        "best_index": int(result.best_index),
        "candidates": [
            {
                "name": str(candidate.name),
                "options": dict(candidate.options.__dict__),
                "result": {
                    **result_payload(candidate.result),
                },
                "soft_penalty": candidate.soft_penalty,
                "rank_explanation": str(candidate.rank_explanation),
            }
            for candidate in result.candidates
        ],
    }


def handle_score(payload: Dict[str, Any]) -> Dict[str, Any]:
    inst, schedule = load_instance_and_schedule(payload)
    return score_schedule(inst, schedule)


def handle_conflicts(payload: Dict[str, Any]) -> Dict[str, Any]:
    return handle_score(payload)


def handle_improve(payload: Dict[str, Any]) -> Dict[str, Any]:
    inst, schedule = load_instance_and_schedule(payload)
    options_raw = payload.get("options") or {}
    if not isinstance(options_raw, dict):
        raise ValueError("Payload options must be an object.")
    focus_term = str(payload.get("focus_term", "") or "")
    return improve_schedule_shared(
        inst,
        schedule,
        ImproveOptions(**options_raw),
        focus_term=focus_term,
    )


def handle_cp_polish(payload: Dict[str, Any]) -> Dict[str, Any]:
    inst, schedule = load_instance_and_schedule(payload)
    options_raw = payload.get("options") or {}
    if not isinstance(options_raw, dict):
        raise ValueError("Payload options must be an object.")
    focus_term = str(payload.get("focus_term", "") or "")
    if not focus_term:
        raise ValueError("focus_term is required for focused CP-SAT polish.")
    return cp_sat_polish_shared(
        inst,
        schedule,
        solve_options_from_payload(inst, payload),
        focus_term=focus_term,
        affected_limit=int(payload.get("affected_limit", 100) or 100),
    )


def handle_export_csv(payload: Dict[str, Any]) -> Dict[str, Any]:
    inst, schedule = load_instance_and_schedule(payload)
    with tempfile.NamedTemporaryFile("w", suffix=".csv", encoding="utf-8", newline="", delete=False) as fh:
        tmp_path = Path(fh.name)
    try:
        content = export_schedule_csv_text(inst, schedule, tmp_path)
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass
    return {
        "filename": str(payload.get("filename", "planora-schedule.csv") or "planora-schedule.csv"),
        "content_type": "text/csv",
        "content": content,
    }


def handle_graphql(payload: Dict[str, Any], principal: Principal | None = None) -> Dict[str, Any]:
    query = str(payload.get("query", "") or "")
    if "health" in query.lower():
        return {"data": {"health": {"ok": True}}}
    if "solveportfolio" in query.lower():
        if principal is None:
            raise PermissionError("Authentication required for portfolio solving.")
        require_permission(principal, "solver:run")
        return {"data": {"portfolio": handle_portfolio(payload)}}
    if "solve" in query.lower():
        if principal is None:
            raise PermissionError("Authentication required for solving.")
        require_permission(principal, "solver:run")
        return {"data": {"solve": handle_solve(payload)}}
    return {"errors": [{"message": "Unsupported GraphQL query."}]}
