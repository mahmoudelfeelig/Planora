from __future__ import annotations

import json
import urllib.request
from typing import Any, Dict

from services.contracts import PortfolioCandidate, PortfolioResult, SolveOptions, SolveResult
from services.application_service import run_workspace_action
from services.engine_backend import engine_contract, solve_portfolio_with_engine
from services.ui_contract import ui_contract
from utils.generator import instance_to_json


class PlanoraBackendClient:
    def capabilities(self) -> Dict[str, Any]:
        raise NotImplementedError

    def solve(
        self, inst, *, run_mode: str = "balanced", options: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def improve(
        self,
        inst,
        schedule: Dict[Any, Dict[str, Any]],
        *,
        run_mode: str = "balanced",
        options: Dict[str, Any] | None = None,
        focus_term: str = "",
        progress_hook=None,
        stop_hook=None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def score(self, inst, schedule: Dict[Any, Dict[str, Any]]) -> Dict[str, Any]:
        raise NotImplementedError

    def solve_portfolio(self, inst, options: SolveOptions) -> PortfolioResult:
        raise NotImplementedError


class LocalBackendClient(PlanoraBackendClient):
    def capabilities(self) -> Dict[str, Any]:
        return {"shared_backend": engine_contract(), "ui_contract": ui_contract()}

    def _action(
        self,
        inst,
        schedule: Dict[Any, Dict[str, Any]] | None,
        action: str,
        payload: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return run_workspace_action(
            instance_json=instance_to_json(inst),
            schedule=schedule,
            action=action,
            payload=payload,
        )

    def solve(
        self, inst, *, run_mode: str = "balanced", options: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        return self._action(
            inst,
            None,
            "solve",
            {"run_mode": run_mode, "options": dict(options or {})},
        )

    def improve(
        self,
        inst,
        schedule: Dict[Any, Dict[str, Any]],
        *,
        run_mode: str = "balanced",
        options: Dict[str, Any] | None = None,
        focus_term: str = "",
        progress_hook=None,
        stop_hook=None,
    ) -> Dict[str, Any]:
        payload = {
            "run_mode": run_mode,
            "options": dict(options or {}),
            "focus_term": str(focus_term or ""),
        }
        return run_workspace_action(
            instance_json=instance_to_json(inst),
            schedule=schedule,
            action="improve",
            payload=payload,
            progress_hook=progress_hook,
            stop_hook=stop_hook,
        )

    def score(self, inst, schedule: Dict[Any, Dict[str, Any]]) -> Dict[str, Any]:
        return self._action(inst, schedule, "score")

    def solve_portfolio(self, inst, options: SolveOptions) -> PortfolioResult:
        return solve_portfolio_with_engine(inst, options)


class HttpBackendClient(PlanoraBackendClient):
    def __init__(self, base_url: str, *, bearer_token: str | None = None):
        self.base_url = str(base_url).rstrip("/")
        self.bearer_token = str(bearer_token or "")

    def _request(
        self, path: str, *, payload: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=(json.dumps(payload).encode("utf-8") if payload is not None else None),
            headers=headers,
            method=("POST" if payload is not None else "GET"),
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Invalid backend response for {path}.")
        return data

    def capabilities(self) -> Dict[str, Any]:
        return self._request("/capabilities")

    def solve(
        self, inst, *, run_mode: str = "balanced", options: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        return self._request(
            "/solve",
            payload={
                "instance": instance_to_json(inst),
                "run_mode": run_mode,
                "options": dict(options or {}),
            },
        )

    def improve(
        self,
        inst,
        schedule: Dict[Any, Dict[str, Any]],
        *,
        run_mode: str = "balanced",
        options: Dict[str, Any] | None = None,
        focus_term: str = "",
        progress_hook=None,
        stop_hook=None,
    ) -> Dict[str, Any]:
        return self._request(
            "/improve",
            payload={
                "instance": instance_to_json(inst),
                "schedule": schedule,
                "run_mode": run_mode,
                "options": dict(options or {}),
                "focus_term": str(focus_term or ""),
            },
        )

    def score(self, inst, schedule: Dict[Any, Dict[str, Any]]) -> Dict[str, Any]:
        return self._request(
            "/score",
            payload={"instance": instance_to_json(inst), "schedule": schedule},
        )

    def solve_portfolio(self, inst, options: SolveOptions) -> PortfolioResult:
        payload = {
            "instance": instance_to_json(inst),
            "options": dict(options.__dict__),
        }
        data = self._request("/portfolio", payload=payload)
        candidates = []
        for raw in list(data.get("candidates") or []):
            if not isinstance(raw, dict):
                continue
            result_raw = dict(raw.get("result") or {})
            candidates.append(
                PortfolioCandidate(
                    name=str(raw.get("name", "")),
                    options=SolveOptions(**dict(raw.get("options") or {})),
                    result=SolveResult(
                        status=int(result_raw.get("status", -1)),
                        raw_status=int(result_raw.get("raw_status", -1)),
                        schedule=dict(result_raw.get("schedule") or {}),
                        attempts=[],
                        hard_conflicts=list(result_raw.get("hard_conflicts") or []),
                        meta=dict(result_raw.get("meta") or {}),
                    ),
                    soft_penalty=raw.get("soft_penalty"),
                    rank_explanation=str(raw.get("rank_explanation", "")),
                )
            )
        best_index = int(data.get("best_index", -1))
        return PortfolioResult(candidates=candidates, best_index=best_index)


def create_backend_client(
    *, backend_url: str | None = None, bearer_token: str | None = None
) -> PlanoraBackendClient:
    if backend_url:
        return HttpBackendClient(str(backend_url), bearer_token=bearer_token)
    return LocalBackendClient()
