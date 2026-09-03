from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Any, Mapping

import jwt

from services.env_service import env_bool, env_bool_strict, env_value


ROLES = {"student", "professor", "ta", "uni_admin", "admin"}
ROLE_ORDER = {"student": 0, "ta": 1, "professor": 2, "uni_admin": 3, "admin": 4}

ROLE_PERMISSIONS = {
    "student": {"schedule:read", "conflicts:read"},
    "ta": {"schedule:read", "conflicts:read", "own_assignments:read"},
    "professor": {
        "schedule:read",
        "conflicts:read",
        "own_assignments:read",
        "repair:suggest",
    },
    "uni_admin": {
        "schedule:read",
        "schedule:write",
        "solver:run",
        "repair:write",
        "projects:write",
        "audit:read",
        "access:manage",
    },
    "admin": {
        "schedule:read",
        "schedule:write",
        "solver:run",
        "repair:write",
        "projects:write",
        "audit:read",
        "access:manage",
        "tenants:read_all",
        "tenants:write_all",
    },
}

AUTH_COOKIE = "planora_session"
CSRF_COOKIE = "planora_csrf"


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str
    tenant_id: str
    groups: tuple[str, ...] = field(default_factory=tuple)
    session_id: str = ""
    provider: str = "local"
    staff_id: int | None = None
    student_group_id: int | None = None
    scopes: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)

    @property
    def is_global_admin(self) -> bool:
        return self.role == "admin"


def _env_bool(name: str, default: bool = False) -> bool:
    return env_bool(name, default)


def production_mode() -> bool:
    return env_bool_strict("PLANORA_PRODUCTION", False)


def trusted_dev_headers_enabled() -> bool:
    if production_mode():
        if env_bool_strict("PLANORA_TRUST_DEV_HEADERS", False):
            raise RuntimeError("PLANORA_TRUST_DEV_HEADERS must be disabled in production.")
        return False
    return _env_bool("PLANORA_TRUST_DEV_HEADERS", False)


def auth_secret() -> str:
    secret = env_value("PLANORA_AUTH_SECRET", "")
    if secret:
        if production_mode() and len(secret.encode("utf-8")) < 32:
            raise RuntimeError(
                "PLANORA_AUTH_SECRET must contain at least 32 UTF-8 bytes in production."
            )
        return secret
    if production_mode():
        raise RuntimeError("PLANORA_AUTH_SECRET or PLANORA_AUTH_SECRET_FILE is required in production.")
    return "planora-local-development-secret-not-for-production"


def validate_auth_configuration() -> None:
    """Fail before serving when production authentication is misconfigured."""
    if not production_mode():
        return
    trusted_dev_headers_enabled()
    env_bool_strict("PLANORA_TRUST_PROXY_HEADERS", False)
    auth_secret()
    from services.password_auth_service import (
        secret_pepper,
        smtp_configured,
        verification_base_url,
    )

    secret_pepper()
    verification_base_url("")
    if not smtp_configured():
        raise RuntimeError(
            "PLANORA_SMTP_HOST is required in production so verification and "
            "password-reset secrets are never returned to API callers."
        )


def auth_issuer() -> str:
    return env_value("PLANORA_AUTH_ISSUER", "planora")


def auth_audience() -> str:
    return env_value("PLANORA_AUTH_AUDIENCE", "planora-web")


def create_auth_token(
    principal: Principal,
    *,
    ttl_seconds: int = 8 * 60 * 60,
    session_id: str | None = None,
) -> str:
    now = int(time.time())
    sid = session_id if session_id is not None else principal.session_id
    payload = {
        "iss": auth_issuer(),
        "aud": auth_audience(),
        "sub": principal.user_id,
        "role": principal.role,
        "tenant_id": principal.tenant_id,
        "groups": list(principal.groups),
        "provider": principal.provider,
        "scopes": [list(item) for item in principal.scopes],
        "sid": sid,
        "jti": secrets.token_urlsafe(18),
        "iat": now,
        "nbf": now - 5,
        "exp": now + int(ttl_seconds),
    }
    if principal.staff_id is not None:
        payload["staff_id"] = int(principal.staff_id)
    if principal.student_group_id is not None:
        payload["student_group_id"] = int(principal.student_group_id)
    return jwt.encode(payload, auth_secret(), algorithm="HS256")


def token_payload(token: str) -> dict[str, Any]:
    try:
        return dict(
            jwt.decode(
                str(token),
                auth_secret(),
                algorithms=["HS256"],
                issuer=auth_issuer(),
                audience=auth_audience(),
                options={"require": ["exp", "iat", "sub", "iss", "aud", "jti", "sid"]},
            )
        )
    except Exception as exc:
        raise PermissionError(f"Invalid auth token: {exc}") from exc


def principal_from_token(token: str) -> Principal:
    payload = token_payload(token)
    role = str(payload.get("role", "student"))
    if role not in ROLES:
        role = "student"
    return Principal(
        user_id=str(payload["sub"]),
        role=role,
        tenant_id=str(payload.get("tenant_id", "default") or "default"),
        groups=tuple(str(item) for item in payload.get("groups", []) if str(item)),
        session_id=str(payload.get("sid", "")),
        provider=str(payload.get("provider", "local") or "local"),
        staff_id=(int(payload["staff_id"]) if payload.get("staff_id") is not None else None),
        student_group_id=(
            int(payload["student_group_id"])
            if payload.get("student_group_id") is not None
            else None
        ),
        scopes=tuple(
            (str(item[0]), str(item[1]), str(item[2]))
            for item in payload.get("scopes", [])
            if isinstance(item, (list, tuple)) and len(item) == 3
        ),
    )


def _cookie_token(headers: Mapping[str, Any]) -> str:
    cookie = SimpleCookie()
    cookie.load(str(headers.get("Cookie", "") or ""))
    morsel = cookie.get(AUTH_COOKIE)
    return morsel.value if morsel is not None else ""


def has_multiple_auth_credentials(headers: Mapping[str, Any]) -> bool:
    authorization = str(headers.get("Authorization", "") or "")
    return authorization.lower().startswith("bearer ") and bool(_cookie_token(headers))


def principal_from_headers(headers: Mapping[str, Any]) -> Principal:
    authorization = str(headers.get("Authorization", "") or "")
    cookie_token = _cookie_token(headers)
    if has_multiple_auth_credentials(headers):
        raise PermissionError("Multiple authentication credentials are not allowed.")
    if authorization.lower().startswith("bearer "):
        return principal_from_token(authorization.split(" ", 1)[1].strip())
    if cookie_token:
        return principal_from_token(cookie_token)
    if not trusted_dev_headers_enabled():
        raise PermissionError("Authentication required.")
    role = str(headers.get("X-Planora-Role", "admin") or "admin").strip().lower()
    if role not in ROLES:
        role = "student"
    tenant_id = str(headers.get("X-Planora-Tenant", "default") or "default").strip() or "default"
    user_id = str(headers.get("X-Planora-User", "local-admin") or "local-admin").strip() or "local-admin"
    return Principal(user_id=user_id, role=role, tenant_id=tenant_id, provider="dev-header")


def is_cookie_authenticated(headers: Mapping[str, Any]) -> bool:
    return bool(_cookie_token(headers)) and not str(headers.get("Authorization", "") or "").lower().startswith("bearer ")


def validate_csrf(headers: Mapping[str, Any]) -> None:
    if not is_cookie_authenticated(headers):
        return
    cookie = SimpleCookie()
    cookie.load(str(headers.get("Cookie", "") or ""))
    expected = cookie.get(CSRF_COOKIE)
    supplied = str(headers.get("X-CSRF-Token", "") or "")
    if expected is None or not supplied or not secrets.compare_digest(expected.value, supplied):
        raise PermissionError("Invalid CSRF token.")


def can_access_tenant(principal: Principal, tenant_id: str | None) -> bool:
    return principal.is_global_admin or str(tenant_id or "default") == principal.tenant_id


def require_tenant_access(principal: Principal, tenant_id: str | None) -> None:
    if not can_access_tenant(principal, tenant_id):
        raise PermissionError("This user cannot access that tenant workspace.")


def stamp_meta(meta: Mapping[str, Any] | None, principal: Principal) -> dict[str, Any]:
    stamped = dict(meta or {})
    stamped["tenant_id"] = principal.tenant_id
    stamped["created_by"] = principal.user_id
    stamped["created_by_role"] = principal.role
    return stamped


def permissions_for_role(role: str) -> set[str]:
    return set(ROLE_PERMISSIONS.get(str(role), set()))


def require_permission(principal: Principal, permission: str) -> None:
    if permission not in permissions_for_role(principal.role):
        raise PermissionError(f"Missing permission: {permission}")


def principal_payload(principal: Principal) -> dict[str, Any]:
    return {
        "user_id": principal.user_id,
        "role": principal.role,
        "tenant_id": principal.tenant_id,
        "groups": list(principal.groups),
        "permissions": sorted(permissions_for_role(principal.role)),
        "is_global_admin": principal.is_global_admin,
        "provider": principal.provider,
        "staff_id": principal.staff_id,
        "student_group_id": principal.student_group_id,
        "scopes": [list(item) for item in principal.scopes],
    }
