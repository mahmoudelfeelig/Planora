from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Tuple

from services.contracts import SolveOptions
from services.solver_service import solve_instance, solve_portfolio
from utils.io import instance_from_json


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(int(status))
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _parse_json(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    body = handler.rfile.read(length) if length > 0 else b"{}"
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object.")
    return payload


class PlanoraApiHandler(BaseHTTPRequestHandler):
    server_version = "PlanoraAPI/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            _json_response(self, 200, {"ok": True})
            return
        _json_response(self, 404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            payload = _parse_json(self)
        except Exception as exc:
            _json_response(self, 400, {"error": str(exc)})
            return

        try:
            if self.path == "/solve":
                result = _handle_solve(payload)
                _json_response(self, 200, result)
                return
            if self.path == "/portfolio":
                result = _handle_portfolio(payload)
                _json_response(self, 200, result)
                return
            if self.path == "/graphql":
                result = _handle_graphql(payload)
                _json_response(self, 200, result)
                return
        except Exception as exc:
            _json_response(self, 500, {"error": str(exc)})
            return

        _json_response(self, 404, {"error": "Not found"})


def _load_instance_and_options(payload: Dict[str, Any]) -> Tuple[Any, SolveOptions]:
    inst_raw = payload.get("instance")
    options_raw = payload.get("options") or {}
    if not isinstance(inst_raw, dict):
        raise ValueError("Payload missing instance JSON.")
    if not isinstance(options_raw, dict):
        raise ValueError("Payload options must be an object.")
    inst = instance_from_json(inst_raw)
    options = SolveOptions(**options_raw)
    return inst, options


def _handle_solve(payload: Dict[str, Any]) -> Dict[str, Any]:
    inst, options = _load_instance_and_options(payload)
    result = solve_instance(inst, options)
    return {
        "status": int(result.status),
        "raw_status": int(result.raw_status),
        "schedule": result.schedule,
        "hard_conflicts": list(result.hard_conflicts),
        "meta": dict(result.meta or {}),
    }


def _handle_portfolio(payload: Dict[str, Any]) -> Dict[str, Any]:
    inst, options = _load_instance_and_options(payload)
    result = solve_portfolio(inst, options)
    return {
        "best_index": int(result.best_index),
        "candidates": [
            {
                "name": str(candidate.name),
                "options": dict(candidate.options.__dict__),
                "result": {
                    "status": int(candidate.result.status),
                    "raw_status": int(candidate.result.raw_status),
                    "schedule": candidate.result.schedule,
                    "hard_conflicts": list(candidate.result.hard_conflicts),
                    "meta": dict(candidate.result.meta or {}),
                },
                "soft_penalty": candidate.soft_penalty,
                "rank_explanation": str(candidate.rank_explanation),
            }
            for candidate in result.candidates
        ],
    }


def _handle_graphql(payload: Dict[str, Any]) -> Dict[str, Any]:
    query = str(payload.get("query", "") or "")
    if "health" in query.lower():
        return {"data": {"health": {"ok": True}}}
    if "solveportfolio" in query.lower():
        return {"data": {"portfolio": _handle_portfolio(payload)}}
    if "solve" in query.lower():
        return {"data": {"solve": _handle_solve(payload)}}
    return {"errors": [{"message": "Unsupported GraphQL query."}]}


def serve(*, host: str = "127.0.0.1", port: int = 8787) -> None:
    HTTPServer((host, int(port)), PlanoraApiHandler).serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Planora integration API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)
    serve(host=str(args.host), port=int(args.port))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
