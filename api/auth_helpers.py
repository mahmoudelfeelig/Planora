from __future__ import annotations

import json
import os
import secrets
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable, Dict

from api.http import common_headers
from services.auth_service import (
    AUTH_COOKIE,
    CSRF_COOKIE,
    Principal,
    create_auth_token,
    principal_from_headers,
    principal_payload,
    production_mode,
    require_permission,
)


def authenticated(handler: BaseHTTPRequestHandler, persistence: Any, permission: str | None = None) -> Principal:
    principal = principal_from_headers(handler.headers)
    persistence.require_active_session(principal)
    principal = persistence.resolve_principal(principal)
    if permission:
        require_permission(principal, permission)
    return principal


def global_admin(handler: BaseHTTPRequestHandler, persistence: Any, permission: str | None = "audit:read") -> Principal:
    principal = authenticated(handler, persistence, permission)
    if not principal.is_global_admin:
        raise PermissionError("Global administrator access is required.")
    return principal


def optional_authenticated(handler: BaseHTTPRequestHandler, persistence: Any) -> Principal | None:
    try:
        return authenticated(handler, persistence)
    except PermissionError:
        return None


def redirect_with_session(
    handler: BaseHTTPRequestHandler,
    location: str,
    token: str,
    csrf_token: str,
    *,
    max_age: int,
    common_headers_fn: Callable[[BaseHTTPRequestHandler], None] = common_headers,
) -> None:
    secure = "; Secure" if production_mode() else ""
    handler.send_response(303)
    handler.send_header("Location", location)
    handler.send_header("Set-Cookie", f"{AUTH_COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}")
    handler.send_header("Set-Cookie", f"{CSRF_COOKIE}={csrf_token}; Path=/; Max-Age={max_age}; SameSite=Lax{secure}")
    common_headers_fn(handler)
    handler.end_headers()


def auth_json_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    payload: Dict[str, Any],
    *,
    token: str = "",
    csrf_token: str = "",
    max_age: int = 0,
    clear: bool = False,
    common_headers_fn: Callable[[BaseHTTPRequestHandler], None] = common_headers,
) -> None:
    body = json.dumps(payload).encode("utf-8")
    secure = "; Secure" if production_mode() else ""
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    if clear:
        handler.send_header("Set-Cookie", f"{AUTH_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax{secure}")
        handler.send_header("Set-Cookie", f"{CSRF_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax{secure}")
    elif token and csrf_token:
        handler.send_header("Set-Cookie", f"{AUTH_COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}")
        handler.send_header("Set-Cookie", f"{CSRF_COOKIE}={csrf_token}; Path=/; Max-Age={max_age}; SameSite=Lax{secure}")
    common_headers_fn(handler)
    handler.end_headers()
    handler.wfile.write(body)


def session_for_principal(persistence: Any, principal: Principal) -> tuple[str, str, int, Principal]:
    session_id = secrets.token_urlsafe(24)
    ttl = int(os.environ.get("PLANORA_SESSION_TTL_SECONDS", "28800"))
    csrf = persistence.create_auth_session(principal, session_id, ttl_seconds=ttl)
    session_principal = Principal(
        user_id=principal.user_id,
        role=principal.role,
        tenant_id=principal.tenant_id,
        groups=principal.groups,
        session_id=session_id,
        provider=principal.provider,
        staff_id=principal.staff_id,
        student_group_id=principal.student_group_id,
        scopes=principal.scopes,
    )
    token = create_auth_token(session_principal, ttl_seconds=ttl, session_id=session_id)
    return token, csrf, ttl, session_principal


def auth_payload(principal: Principal) -> Dict[str, Any]:
    return principal_payload(principal)
