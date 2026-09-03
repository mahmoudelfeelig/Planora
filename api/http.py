from __future__ import annotations

import csv
import io
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import unquote, urlparse
from typing import Any, Dict

from services.auth_service import production_mode
from services.env_service import env_bool_strict, env_value
from utils.csv_security import spreadsheet_safe_mapping


_DEFAULT_DEVELOPMENT_ORIGINS = {
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://[::1]:5173",
}


def allowed_origin(handler: BaseHTTPRequestHandler) -> str:
    origin = str(handler.headers.get("Origin", "") or "")
    configured = [item.strip().rstrip("/") for item in os.environ.get("PLANORA_ALLOWED_ORIGINS", "").split(",") if item.strip()]
    allowed = set(configured)
    if not allowed and not production_mode():
        allowed = _DEFAULT_DEVELOPMENT_ORIGINS
    return origin if origin.rstrip("/") in allowed else ""


def common_headers(handler: BaseHTTPRequestHandler) -> None:
    origin = allowed_origin(handler)
    if origin:
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")
        if origin != "*":
            handler.send_header("Access-Control-Allow-Credentials", "true")
    handler.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-CSRF-Token, X-Planora-User, X-Planora-Role, X-Planora-Tenant")
    handler.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, DELETE, OPTIONS")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Referrer-Policy", "same-origin")
    handler.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    handler.send_header("Cache-Control", "no-store")
    request_id = str(getattr(handler, "_request_id", "") or "")
    if request_id:
        handler.send_header("X-Request-ID", request_id)


def json_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    payload: Dict[str, Any],
    *,
    headers: Dict[str, str] | None = None,
) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(int(status))
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    for name, value in dict(headers or {}).items():
        handler.send_header(str(name), str(value))
    common_headers(handler)
    handler.end_headers()
    if str(getattr(handler, "command", "")).upper() != "HEAD":
        handler.wfile.write(body)


def text_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: str,
    *,
    content_type: str = "text/plain; charset=utf-8",
) -> None:
    encoded = str(body).encode("utf-8")
    handler.send_response(int(status))
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(encoded)))
    common_headers(handler)
    handler.end_headers()
    if str(getattr(handler, "command", "")).upper() != "HEAD":
        handler.wfile.write(encoded)


def csv_response(handler: BaseHTTPRequestHandler, filename: str, rows: list[Dict[str, Any]]) -> None:
    output = io.StringIO()
    fieldnames = sorted({key for row in rows for key in row.keys()}) if rows else ["empty"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            spreadsheet_safe_mapping({key: row.get(key, "") for key in fieldnames})
        )
    body = output.getvalue().encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/csv; charset=utf-8")
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Content-Length", str(len(body)))
    common_headers(handler)
    handler.end_headers()
    if str(getattr(handler, "command", "")).upper() != "HEAD":
        handler.wfile.write(body)


def parse_json(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    path = urlparse(handler.path).path
    if path in {"/analytics/event", "/events/collect"}:
        maximum = int(os.environ.get("PLANORA_MAX_ANALYTICS_REQUEST_BYTES", "32768"))
    elif path in {"/import/csv", "/sessions"}:
        maximum = int(
            os.environ.get("PLANORA_MAX_IMPORT_REQUEST_BYTES", str(20 * 1024 * 1024))
        )
    else:
        maximum = int(os.environ.get("PLANORA_MAX_REQUEST_BYTES", str(2 * 1024 * 1024)))
    if length > maximum:
        raise ValueError(f"Request body exceeds the {maximum}-byte limit.")
    body = handler.rfile.read(length) if length > 0 else b"{}"
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object.")
    return payload


def request_base_url(handler: BaseHTTPRequestHandler) -> str:
    configured_public_url = env_value("PLANORA_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured_public_url:
        return configured_public_url
    configured_domain = env_value("PLANORA_DOMAIN", "").strip()
    if production_mode() and configured_domain:
        return f"https://{configured_domain}"
    if production_mode():
        raise RuntimeError(
            "PLANORA_PUBLIC_BASE_URL or PLANORA_DOMAIN is required in production."
        )

    port = int(handler.server.server_port)
    local_scheme = "https" if port == 443 else "http"
    local_host = "127.0.0.1" if port in {80, 443} else f"127.0.0.1:{port}"
    local_base_url = f"{local_scheme}://{local_host}"
    if not env_bool_strict("PLANORA_TRUST_PROXY_HEADERS", False):
        return local_base_url

    forwarded_proto = str(handler.headers.get("X-Forwarded-Proto", "") or "").split(",")[-1].strip().lower()
    forwarded_host = str(handler.headers.get("X-Forwarded-Host", "") or "").split(",")[-1].strip()
    parsed_host = urlparse(f"//{forwarded_host}")
    try:
        forwarded_port = parsed_host.port
    except ValueError:
        return local_base_url
    if (
        forwarded_proto not in {"http", "https"}
        or not parsed_host.hostname
        or parsed_host.username is not None
        or parsed_host.password is not None
        or parsed_host.path
        or parsed_host.query
        or parsed_host.fragment
        or forwarded_port is not None and not 1 <= forwarded_port <= 65535
    ):
        return local_base_url
    return f"{forwarded_proto}://{forwarded_host}"


def segments(path: str) -> list[str]:
    parsed = urlparse(path)
    return [unquote(part) for part in parsed.path.split("/") if part]
