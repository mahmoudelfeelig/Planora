from __future__ import annotations

import json
import urllib.request
from typing import Any

from services.contracts import PortfolioCandidate, PortfolioResult, SolveOptions, SolveResult
from services.solver_service import solve_portfolio


class PlanoraBackendClient:
    def solve_portfolio(self, inst, options: SolveOptions) -> PortfolioResult:
        raise NotImplementedError


class LocalBackendClient(PlanoraBackendClient):
    def solve_portfolio(self, inst, options: SolveOptions) -> PortfolioResult:
        return solve_portfolio(inst, options)


class HttpBackendClient(PlanoraBackendClient):
    def __init__(self, base_url: str):
        self.base_url = str(base_url).rstrip("/")

    def solve_portfolio(self, inst, options: SolveOptions) -> PortfolioResult:
        payload = {
            "instance": getattr(inst, "__dict__", {}),
            "options": dict(options.__dict__),
        }
        req = urllib.request.Request(
            f"{self.base_url}/portfolio",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Invalid backend portfolio response.")
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


def create_backend_client(*, backend_url: str | None = None) -> PlanoraBackendClient:
    if backend_url:
        return HttpBackendClient(str(backend_url))
    return LocalBackendClient()
