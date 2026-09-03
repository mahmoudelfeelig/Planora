from __future__ import annotations

import time
from typing import Any, Callable, Dict

from services.contracts import ImproveOptions, PortfolioResult, SolveOptions, SolveResult
from services.schedule_ops_service import improve_schedule_shared
from services.solver_service import solve_instance, solve_portfolio
from services.ui_contract import UI_CONTRACT_VERSION


ENGINE_BACKEND_ID = "planora-solver-service-v1"
INTERACTIVE_ROOM_MODE = "partitioned"
INTERACTIVE_OBJECTIVE_PROFILE = "university_fast"
INTERACTIVE_SOLVE_SECONDS = 15.0
INTERACTIVE_IMPROVE_ITERATIONS = 500
INTERACTIVE_IMPROVE_SECONDS = 2.0


def engine_contract() -> Dict[str, Any]:
    """Return the cross-client engine identity and bounded interactive defaults."""
    return {
        "backend_id": ENGINE_BACKEND_ID,
        "contract_version": UI_CONTRACT_VERSION,
        "solve": {
            "room_mode": INTERACTIVE_ROOM_MODE,
            "objective_profile": INTERACTIVE_OBJECTIVE_PROFILE,
            "time_limit_seconds": INTERACTIVE_SOLVE_SECONDS,
            "use_objective": False,
        },
        "improve": {
            "iterations": INTERACTIVE_IMPROVE_ITERATIONS,
            "max_seconds": INTERACTIVE_IMPROVE_SECONDS,
        },
    }


def interactive_solve_options(**overrides: Any) -> SolveOptions:
    values: Dict[str, Any] = {
        "room_mode": INTERACTIVE_ROOM_MODE,
        "objective_profile": INTERACTIVE_OBJECTIVE_PROFILE,
        "time_limit_seconds": INTERACTIVE_SOLVE_SECONDS,
        "use_objective": False,
        "retry_without_objective": True,
    }
    values.update(overrides)
    return SolveOptions(**values)


def interactive_improve_options(**overrides: Any) -> ImproveOptions:
    values: Dict[str, Any] = {
        "iterations": INTERACTIVE_IMPROVE_ITERATIONS,
        "max_seconds": INTERACTIVE_IMPROVE_SECONDS,
    }
    values.update(overrides)
    return ImproveOptions(**values)


def _engine_meta(*, operation: str, elapsed_seconds: float) -> Dict[str, Any]:
    return {
        "backend_id": ENGINE_BACKEND_ID,
        "contract_version": UI_CONTRACT_VERSION,
        "operation": str(operation),
        "elapsed_seconds": float(elapsed_seconds),
    }


def solve_with_engine(
    inst: Any,
    options: SolveOptions,
    *,
    progress_hook: Callable[[str, Dict[str, Any]], None] | None = None,
) -> SolveResult:
    started = time.perf_counter()
    result = solve_instance(inst, options, progress_hook=progress_hook)
    result.meta = dict(result.meta or {})
    result.meta["engine_backend"] = _engine_meta(
        operation="solve",
        elapsed_seconds=time.perf_counter() - started,
    )
    return result


def solve_portfolio_with_engine(
    inst: Any,
    options: SolveOptions,
    *,
    progress_hook: Callable[[str, Dict[str, Any]], None] | None = None,
) -> PortfolioResult:
    started = time.perf_counter()
    result = solve_portfolio(inst, options, progress_hook=progress_hook)
    elapsed = time.perf_counter() - started
    for candidate in result.candidates:
        candidate.result.meta = dict(candidate.result.meta or {})
        candidate.result.meta["engine_backend"] = _engine_meta(
            operation="portfolio_solve",
            elapsed_seconds=elapsed,
        )
    return result


def improve_with_engine(
    inst: Any,
    schedule: Dict[Any, Dict[str, Any]],
    options: ImproveOptions,
    *,
    focus_term: str = "",
    progress_hook=None,
    stop_hook=None,
) -> Dict[str, Any]:
    started = time.perf_counter()
    result = improve_schedule_shared(
        inst,
        schedule,
        options,
        focus_term=focus_term,
        progress_hook=progress_hook,
        stop_hook=stop_hook,
    )
    result = dict(result)
    meta = dict(result.get("meta") or {})
    meta["engine_backend"] = _engine_meta(
        operation="improve",
        elapsed_seconds=time.perf_counter() - started,
    )
    result["meta"] = meta
    return result
