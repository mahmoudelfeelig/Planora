from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any, Dict

from api.http import (
    common_headers as _common_headers,
    csv_response as _csv_response,
    json_response as _json_response,
    parse_json as _parse_json,
    request_base_url as _request_base_url,
    segments as _segments,
    text_response as _text_response,
)
from api.actions import (
    handle_conflicts as _handle_conflicts,
    handle_cp_polish as _handle_cp_polish,
    handle_export_csv as _handle_export_csv,
    handle_graphql as _handle_graphql,
    handle_improve as _handle_improve,
    handle_portfolio as _handle_portfolio,
    handle_score as _handle_score,
    handle_solve as _handle_solve,
)
from api.schema import openapi_schema as _openapi_schema
from api import auth_helpers
from api.rate_limit import RateLimitExceeded, check_rate_limit as _check_rate_limit_impl
from api.system_status import system_status_payload as _system_status_payload_impl
from services.application_service import (
    JobCapacityExceeded,
    JobStore,
    SessionStore,
    list_web_projects,
    load_web_project,
    run_workspace_action,
    safe_project_name,
)
from services.auth_service import (
    Principal,
    create_auth_token,
    principal_from_headers,
    principal_payload,
    production_mode,
    require_permission,
    require_tenant_access,
    stamp_meta,
    validate_csrf,
)
from services.password_auth_service import (
    build_password_reset_email,
    build_verification_email,
    email_auth_public_config,
    email_verification_required,
    registration_enabled,
    send_email,
    smtp_configured,
    verification_base_url,
)
from services.quality_service import SOFT_WEIGHT_DEFAULTS
from services.schedule_ops_service import (
    normalize_schedule,
    score_schedule,
)
from services.persistence_service import PersistenceStore, default_persistence_path
from services.parity_service import parity_manifest
from services.timetable_import_service import import_timetable_csv
from utils.generator import generate_instance, instance_to_json


ROOT_DIR = Path(__file__).resolve().parent.parent
WEB_PROJECTS_DIR = ROOT_DIR / "data" / "web_projects"
SESSION_STORE = SessionStore()
PERSISTENCE = PersistenceStore(default_persistence_path(ROOT_DIR))
JOB_STORE = JobStore(on_change=PERSISTENCE.save_job)
STARTED_AT = time.time()
_RATE_LOCK = threading.Lock()
_RATE_BUCKETS: dict[str, list[float]] = {}
_CSRF_EXEMPT_POST_PATHS = {
    ("analytics", "event"),
    ("events", "collect"),
    ("auth", "login"),
    ("auth", "register"),
    ("auth", "verify"),
    ("auth", "forgot-password"),
    ("auth", "reset-password"),
}


def _post_requires_csrf(parts: list[str]) -> bool:
    return tuple(parts) not in _CSRF_EXEMPT_POST_PATHS


def _check_rate_limit(handler: BaseHTTPRequestHandler) -> None:
    _check_rate_limit_impl(
        handler,
        buckets=_RATE_BUCKETS,
        lock=_RATE_LOCK,
        principal_from_headers=principal_from_headers,
    )


def _hash_analytics_client_id(value: str) -> str:
    raw = str(value or "").strip()
    if len(raw) < 8:
        raise ValueError("Analytics client id is missing.")
    return hashlib.sha256(f"planora-analytics:{raw}".encode("utf-8")).hexdigest()


def _system_status_payload() -> Dict[str, Any]:
    return _system_status_payload_impl(
        root_dir=ROOT_DIR,
        started_at=STARTED_AT,
        persistence=PERSISTENCE,
        job_store=JOB_STORE,
        production_mode=production_mode,
        default_persistence_path=default_persistence_path,
    )


def _authenticated(handler: BaseHTTPRequestHandler, permission: str | None = None) -> Principal:
    return auth_helpers.authenticated(handler, PERSISTENCE, permission)


def _global_admin(handler: BaseHTTPRequestHandler, permission: str | None = "audit:read") -> Principal:
    return auth_helpers.global_admin(handler, PERSISTENCE, permission)


def _optional_authenticated(handler: BaseHTTPRequestHandler) -> Principal | None:
    """Resolve a real authenticated principal without making telemetry require login."""
    try:
        return _authenticated(handler)
    except PermissionError:
        return None


def _workspace_session(session_id: str, principal: Principal):
    try:
        session = SESSION_STORE.get(session_id)
    except KeyError:
        saved = PERSISTENCE.load_session(session_id, principal)
        if saved is None:
            raise KeyError(f"Unknown session: {session_id}")
        session = SESSION_STORE.restore(**saved)
    require_tenant_access(principal, dict(session.meta or {}).get("tenant_id"))
    return session


def _job_record(job_id: str, principal: Principal):
    try:
        job = JOB_STORE.get(job_id)
    except KeyError:
        saved = PERSISTENCE.load_job(job_id, principal)
        if saved is None:
            raise KeyError(f"Unknown job: {job_id}")
        job = JOB_STORE.restore(saved)
    require_tenant_access(principal, job.tenant_id)
    if principal.role not in {"uni_admin", "admin"} and job.created_by != principal.user_id:
        raise PermissionError("This user cannot access another user's scheduler job.")
    return job


def _project_workspace_payload(principal: Principal, payload: Dict[str, Any]) -> Dict[str, Any]:
    if principal.role in {"uni_admin", "admin"}:
        return payload
    instance = dict(payload.get("instance") or {})
    schedule = normalize_schedule(payload.get("schedule") if isinstance(payload.get("schedule"), dict) else {})
    activities = dict(instance.get("activities") or {})
    visible_ids: set[int] = set()
    for raw_id, activity in activities.items():
        activity_id = int(raw_id)
        row = dict(activity or {})
        group_ids = {int(value) for value in row.get("group_ids", [])}
        assigned_staff = {int(value) for value in (row.get("prof_id"), row.get("ta_id")) if value is not None}
        scheduled_staff = schedule.get(activity_id, {}).get("staff_id")
        if scheduled_staff is not None:
            assigned_staff.add(int(scheduled_staff))
        if principal.role == "student" and principal.student_group_id in group_ids:
            visible_ids.add(activity_id)
        elif principal.role in {"professor", "ta"} and principal.staff_id in assigned_staff:
            visible_ids.add(activity_id)
        for _role, scope_type, scope_id in principal.scopes:
            if scope_type == "course" and str(row.get("course_id")) == scope_id:
                visible_ids.add(activity_id)
            elif scope_type == "group" and any(str(group_id) == scope_id for group_id in group_ids):
                visible_ids.add(activity_id)
            elif scope_type == "program" and str(row.get("program_id", "")) == scope_id:
                visible_ids.add(activity_id)
    instance["activities"] = {str(key): value for key, value in activities.items() if int(key) in visible_ids}
    instance["groups"] = {
        str(key): value
        for key, value in dict(instance.get("groups") or {}).items()
        if principal.student_group_id is not None and int(key) == principal.student_group_id
    }
    instance["staff"] = {
        str(key): value
        for key, value in dict(instance.get("staff") or {}).items()
        if principal.staff_id is not None and int(key) == principal.staff_id
    }
    projected = dict(payload)
    projected["instance"] = instance
    projected["schedule"] = {activity_id: row for activity_id, row in schedule.items() if activity_id in visible_ids}
    return projected


def _error_response(handler: BaseHTTPRequestHandler, exc: Exception) -> None:
    if isinstance(exc, RateLimitExceeded):
        _json_response(
            handler,
            429,
            {"error": str(exc), "retry_after": exc.retry_after},
            headers={"Retry-After": str(exc.retry_after)},
        )
        return
    if isinstance(exc, JobCapacityExceeded):
        _json_response(handler, 429, {"error": str(exc), "retry_after": 5}, headers={"Retry-After": "5"})
        return
    if "Rate limit exceeded" in str(exc):
        status = 429
    elif "Request body exceeds" in str(exc):
        status = 413
    elif isinstance(exc, PermissionError):
        status = 401 if "Authentication required" in str(exc) or "auth token" in str(exc).lower() else 403
    elif isinstance(exc, (ValueError, KeyError)):
        status = 400
    else:
        status = 500
    _json_response(handler, status, {"error": str(exc)})


def _redirect_with_session(
    handler: BaseHTTPRequestHandler,
    location: str,
    token: str,
    csrf_token: str,
    *,
    max_age: int,
) -> None:
    auth_helpers.redirect_with_session(
        handler,
        location,
        token,
        csrf_token,
        max_age=max_age,
        common_headers_fn=_common_headers,
    )


def _auth_json_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    payload: Dict[str, Any],
    *,
    token: str = "",
    csrf_token: str = "",
    max_age: int = 0,
    clear: bool = False,
) -> None:
    auth_helpers.auth_json_response(
        handler,
        status,
        payload,
        token=token,
        csrf_token=csrf_token,
        max_age=max_age,
        clear=clear,
        common_headers_fn=_common_headers,
    )


def _session_for_principal(principal: Principal) -> tuple[str, str, int, Principal]:
    return auth_helpers.session_for_principal(PERSISTENCE, principal)


def _session_payload_from_request(payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[int, Dict[str, Any]], Dict[str, Any]]:
    inst_raw = payload.get("instance")
    if not isinstance(inst_raw, dict):
        raise ValueError("Payload missing instance JSON.")
    schedule = normalize_schedule(payload.get("schedule") if isinstance(payload.get("schedule"), dict) else {})
    meta = dict(payload.get("meta") or {}) if isinstance(payload.get("meta"), dict) else {}
    return dict(inst_raw), schedule, meta


class PlanoraApiHandler(BaseHTTPRequestHandler):
    server_version = "PlanoraAPI/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        if not production_mode() and os.environ.get("PLANORA_STRUCTURED_LOGS", "0").lower() not in {"1", "true", "yes", "on"}:
            return
        record = {
            "timestamp": time.time(),
            "level": "info",
            "event": "http_request",
            "client": str(self.client_address[0]),
            "method": self.command,
            "path": urlparse(self.path).path,
            "request_id": str(getattr(self, "_request_id", "")),
            "message": format % args,
        }
        print(json.dumps(record, separators=(",", ":")), file=sys.stderr, flush=True)

    def do_GET(self) -> None:  # noqa: N802
        self._request_id = self.headers.get("X-Request-ID") or secrets.token_hex(8)
        try:
            _check_rate_limit(self)
            self._do_GET()
        except Exception as exc:
            _error_response(self, exc)

    def do_HEAD(self) -> None:  # noqa: N802
        self._request_id = self.headers.get("X-Request-ID") or secrets.token_hex(8)
        try:
            _check_rate_limit(self)
            parsed_path = urlparse(self.path).path
            if parsed_path == "/auth/verify":
                _json_response(self, 405, {"error": "Method not allowed"})
                return
            self._do_GET()
        except Exception as exc:
            _error_response(self, exc)

    def _do_GET(self) -> None:
        parts = _segments(self.path)
        parsed_path = urlparse(self.path).path
        if parsed_path == "/health":
            _json_response(self, 200, {"ok": True})
            return
        if parsed_path == "/ready":
            schema = PERSISTENCE.schema_info()
            _json_response(self, 200, {"ok": True, "ready": True, "database": schema})
            return
        if parsed_path == "/openapi.json":
            _json_response(self, 200, _openapi_schema())
            return
        if parsed_path == "/auth/config":
            _json_response(self, 200, email_auth_public_config())
            return
        if parsed_path == "/auth/verify":
            query = parse_qs(urlparse(self.path).query)
            token = str((query.get("token") or [""])[0])
            principal = PERSISTENCE.verify_email_token(token)
            PERSISTENCE.audit(principal, action="auth.verify_email", resource_type="user", resource_id=principal.user_id)
            auth_token, csrf, ttl, session_principal = _session_for_principal(principal)
            _redirect_with_session(
                self,
                "/login?verified=1",
                auth_token,
                csrf,
                max_age=ttl,
            )
            return
        if parsed_path == "/presets":
            _authenticated(self, "schedule:read")
            _json_response(
                self,
                200,
                {
                    "presets": [
                        "small_demo",
                        "mixed_large",
                        "block_profs",
                        "labs_only",
                        "ss23_uni_like",
                        "target_case",
                    ]
                },
            )
            return
        if parsed_path == "/capabilities":
            _authenticated(self, "schedule:read")
            _json_response(
                self,
                200,
                {
                    "actions": [
                        "load_preset",
                        "import_instance_json",
                        "import_timetable_csv",
                        "solve",
                        "portfolio",
                        "score",
                        "conflicts",
                        "improve",
                        "focused_cp_sat_polish",
                        "session_workspace",
                        "async_jobs",
                        "job_events",
                        "manual_move",
                        "move_target_deltas",
                        "activity_locks",
                        "project_save_load",
                        "export_csv",
                        "tenant_auth_headers",
                        "email_password_login",
                        "invite_code_registration",
                        "sqlite_persistence",
                        "audit_log",
                        "email_verification",
                        "invite_code_rotation",
                        "revocable_auth_sessions",
                        "tenant_group_rbac",
                        "scoped_schedule_projection",
                    ],
                    "focus_terms": list(SOFT_WEIGHT_DEFAULTS.keys()),
                    "shared_backend": "python-services",
                },
            )
            return
        if parsed_path == "/auth/whoami":
            principal = _authenticated(self)
            _json_response(self, 200, principal_payload(principal))
            return
        if parsed_path == "/system":
            principal = _global_admin(self)
            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "database": PERSISTENCE.schema_info(),
                    "auth": email_auth_public_config(),
                },
            )
            return
        if parsed_path == "/system/status":
            _global_admin(self)
            _json_response(self, 200, _system_status_payload())
            return
        if parsed_path == "/parity":
            _authenticated(self, "schedule:read")
            _json_response(self, 200, parity_manifest())
            return
        if parsed_path in {"/audit", "/audit.csv"}:
            principal = _authenticated(self, "audit:read")
            query = parse_qs(urlparse(self.path).query)
            events = PERSISTENCE.list_audit(
                principal,
                limit=int((query.get("limit") or ["100"])[0] or 100),
                action=str((query.get("action") or [""])[0]),
                user_id=str((query.get("user_id") or [""])[0]),
                tenant_id=str((query.get("tenant_id") or [""])[0]),
            )
            if parsed_path == "/audit.csv":
                _csv_response(self, "planora-audit.csv", events)
            else:
                _json_response(self, 200, {"events": events})
            return
        if parts == ["analytics", "summary"]:
            principal = _authenticated(self, "audit:read")
            query = parse_qs(urlparse(self.path).query)
            _json_response(
                self,
                200,
                PERSISTENCE.analytics_summary(
                    principal,
                    days=int((query.get("days") or ["30"])[0] or 30),
                    tenant_id=str((query.get("tenant_id") or [""])[0]),
                    event_name=str((query.get("event_name") or [""])[0]),
                    path=str((query.get("path") or [""])[0]),
                ),
            )
            return
        if parts == ["analytics", "export.csv"]:
            principal = _authenticated(self, "audit:read")
            query = parse_qs(urlparse(self.path).query)
            summary = PERSISTENCE.analytics_summary(
                principal,
                days=int((query.get("days") or ["30"])[0] or 30),
                tenant_id=str((query.get("tenant_id") or [""])[0]),
                event_name=str((query.get("event_name") or [""])[0]),
                path=str((query.get("path") or [""])[0]),
            )
            rows = [
                {"kind": "total", "name": "events", "events": summary["events"], "visitors": summary["visitors"]},
                *({"kind": "path", "name": row["path"], "events": row["events"], "visitors": row["visitors"]} for row in summary["top_paths"]),
                *({"kind": "event", "name": row["event_name"], "events": row["events"], "visitors": ""} for row in summary["top_events"]),
                *({"kind": "day", "name": row["day"], "events": row["events"], "visitors": row["visitors"]} for row in summary["by_day"]),
            ]
            _csv_response(self, "planora-analytics.csv", rows)
            return
        if parts == ["auth", "sessions"]:
            principal = _authenticated(self)
            _json_response(self, 200, PERSISTENCE.list_auth_sessions(principal))
            return
        if parts == ["access"]:
            principal = _authenticated(self, "access:manage")
            _json_response(self, 200, PERSISTENCE.access_snapshot(principal))
            return
        if parts == ["access", "my-organizations"]:
            principal = _authenticated(self)
            _json_response(self, 200, PERSISTENCE.user_organizations(principal))
            return
        if parts and parts[0] == "sessions" and len(parts) == 2:
            principal = _authenticated(self, "schedule:read")
            try:
                session = _workspace_session(parts[1], principal)
            except KeyError as exc:
                _json_response(self, 404, {"error": str(exc)})
                return
            except Exception as exc:
                _error_response(self, exc)
                return
            _json_response(self, 200, _project_workspace_payload(principal, session.to_dict(include_workspace=True)))
            return
        if parts and parts[0] == "jobs" and len(parts) == 2:
            principal = _authenticated(self, "schedule:read")
            try:
                job = _job_record(parts[1], principal)
                _json_response(self, 200, job.to_dict())
            except KeyError as exc:
                _json_response(self, 404, {"error": str(exc)})
            except Exception as exc:
                _error_response(self, exc)
            return
        if parts and parts[0] == "jobs" and len(parts) == 3 and parts[2] == "events":
            principal = _authenticated(self, "schedule:read")
            try:
                job_record = _job_record(parts[1], principal)
                job = job_record.to_dict()
            except KeyError as exc:
                _text_response(self, 404, f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n", content_type="text/event-stream")
                return
            except PermissionError as exc:
                _text_response(self, 403, f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n", content_type="text/event-stream")
                return
            except Exception as exc:
                _text_response(self, 500, f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n", content_type="text/event-stream")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            _common_headers(self)
            self.end_headers()
            if self.command == "HEAD":
                self.close_connection = True
                return
            terminal = {"complete", "failed", "cancelled"}
            try:
                while True:
                    job = _job_record(parts[1], principal).to_dict()
                    self.wfile.write(f"event: job\ndata: {json.dumps(job)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    if str(job.get("status")) in terminal:
                        break
                    time.sleep(0.5)
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True
            return
        if parts and parts[0] == "projects":
            principal = _authenticated(self, "schedule:read")
            try:
                if len(parts) == 1:
                    persisted = PERSISTENCE.list_projects(principal)
                    projects_payload = list_web_projects(WEB_PROJECTS_DIR)
                    visible_legacy = []
                    persisted_names = {str(row.get("name", "")) for row in persisted}
                    for row in projects_payload.get("projects", []):
                        if str(row.get("name", "")) in persisted_names:
                            continue
                        try:
                            project_payload = load_web_project(WEB_PROJECTS_DIR, str(row.get("name", "")))
                            tenant_id = dict(project_payload.get("meta") or {}).get("tenant_id")
                        except Exception:
                            tenant_id = "default"
                        if principal.is_global_admin or str(tenant_id or "default") == principal.tenant_id:
                            visible_legacy.append({**row, "tenant_id": str(tenant_id or "default"), "storage": "legacy"})
                    _json_response(self, 200, {"projects": [*persisted, *visible_legacy]})
                    return
                if len(parts) == 2:
                    query = parse_qs(urlparse(self.path).query)
                    tenant_id = str((query.get("tenant_id") or [""])[0])
                    project_payload = PERSISTENCE.load_project(parts[1], principal, tenant_id=tenant_id)
                    if project_payload is None:
                        project_payload = load_web_project(WEB_PROJECTS_DIR, parts[1])
                    require_tenant_access(principal, dict(project_payload.get("meta") or {}).get("tenant_id"))
                    _json_response(self, 200, _project_workspace_payload(principal, project_payload))
                    return
            except (FileNotFoundError, KeyError) as exc:
                _json_response(self, 404, {"error": str(exc)})
                return
            except PermissionError as exc:
                _error_response(self, exc)
                return
            except Exception as exc:
                _error_response(self, exc)
                return
        if self.path.startswith("/preset/"):
            _authenticated(self, "schedule:read")
            mode = self.path.split("/preset/", 1)[1].strip()
            try:
                instance = generate_instance(mode)
            except Exception as exc:
                _json_response(self, 400, {"error": str(exc)})
                return
            _json_response(self, 200, {"mode": mode, "instance": instance_to_json(instance)})
            return
        _json_response(self, 404, {"error": "Not found"})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        _common_headers(self)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        self._request_id = self.headers.get("X-Request-ID") or secrets.token_hex(8)
        try:
            _check_rate_limit(self)
            if _post_requires_csrf(_segments(self.path)):
                validate_csrf(self.headers)
            self._do_POST()
        except Exception as exc:
            _error_response(self, exc)

    def do_DELETE(self) -> None:  # noqa: N802
        self._request_id = self.headers.get("X-Request-ID") or secrets.token_hex(8)
        try:
            _check_rate_limit(self)
            validate_csrf(self.headers)
            parts = _segments(self.path)
            if len(parts) != 2 or parts[0] != "projects":
                _json_response(self, 404, {"error": "Not found"})
                return
            principal = _authenticated(self, "projects:write")
            query = parse_qs(urlparse(self.path).query)
            tenant_id = str((query.get("tenant_id") or [""])[0])
            deleted = PERSISTENCE.delete_project(parts[1], principal, tenant_id=tenant_id)
            if not deleted:
                _json_response(self, 404, {"error": "Project not found."})
                return
            PERSISTENCE.audit(
                principal,
                action="project.delete",
                resource_type="project",
                resource_id=parts[1],
                details={"tenant_id": tenant_id or principal.tenant_id},
            )
            _json_response(self, 200, {"ok": True})
        except Exception as exc:
            _error_response(self, exc)

    def _do_POST(self) -> None:
        parts = _segments(self.path)
        try:
            payload = _parse_json(self)
        except Exception as exc:
            _json_response(self, 400, {"error": str(exc)})
            return

        try:
            if parts in (["analytics", "event"], ["events", "collect"]):
                client_id = str(payload.get("client_id") or "")
                analytics_principal = _optional_authenticated(self)
                PERSISTENCE.record_analytics_event(
                    {
                        "client_id_hash": _hash_analytics_client_id(client_id),
                        "tenant_id": analytics_principal.tenant_id if analytics_principal else "public",
                        "user_role": analytics_principal.role if analytics_principal else "anonymous",
                        "event_name": str(payload.get("event_name") or ""),
                        "path": str(payload.get("path") or "/"),
                        "view_name": str(payload.get("view_name") or ""),
                        "referrer": str(payload.get("referrer") or ""),
                        "viewport_width": payload.get("viewport_width"),
                        "viewport_height": payload.get("viewport_height"),
                        "details": payload.get("details") if isinstance(payload.get("details"), dict) else {},
                        "user_agent": str(self.headers.get("User-Agent", "") or ""),
                    }
                )
                _json_response(self, 200, {"ok": True})
                return
            if parts == ["auth", "register"]:
                if not registration_enabled():
                    raise PermissionError("Registration is disabled.")
                if email_verification_required() and production_mode() and not smtp_configured():
                    raise RuntimeError("SMTP is required in production when email verification is enabled.")
                result = PERSISTENCE.register_email_user(
                    email=str(payload.get("email", "")),
                    password=str(payload.get("password", "")),
                    display_name=str(payload.get("display_name", "")),
                    invite_code=str(payload.get("invite_code", "")),
                )
                principal = result["principal"]
                verification_token = str(result["verification_token"])
                verification_code = str(result["verification_code"])
                response: Dict[str, Any] = {
                    "ok": True,
                    "principal": principal_payload(principal),
                    "email_verification_required": email_verification_required(),
                    "smtp_configured": smtp_configured(),
                }
                if email_verification_required():
                    message = build_verification_email(
                        verification_base_url(_request_base_url(self)),
                        str(payload.get("email", "")),
                        verification_token,
                        verification_code,
                    )
                    if smtp_configured():
                        send_email(message)
                    else:
                        response["verification_token"] = verification_token
                        response["verification_code"] = verification_code
                        response["verification_url"] = f"/auth/verify?token={verification_token}"
                else:
                    principal = PERSISTENCE.verify_email_token(verification_token)
                    auth_token, csrf, ttl, session_principal = _session_for_principal(principal)
                    PERSISTENCE.audit(principal, action="auth.register", resource_type="user", resource_id=principal.user_id)
                    _auth_json_response(
                        self,
                        200,
                        {
                            **response,
                            "token": auth_token,
                            "csrf_token": csrf,
                            "principal": principal_payload(session_principal),
                        },
                        token=auth_token,
                        csrf_token=csrf,
                        max_age=ttl,
                    )
                    return
                PERSISTENCE.audit(principal, action="auth.register", resource_type="user", resource_id=principal.user_id)
                _json_response(self, 200, response)
                return
            if parts == ["auth", "verify"]:
                principal = PERSISTENCE.verify_email_token(
                    str(payload.get("token") or payload.get("code") or ""),
                    email=str(payload.get("email") or ""),
                )
                PERSISTENCE.audit(principal, action="auth.verify_email", resource_type="user", resource_id=principal.user_id)
                auth_token, csrf, ttl, session_principal = _session_for_principal(principal)
                _auth_json_response(
                    self,
                    200,
                    {"ok": True, "token": auth_token, "csrf_token": csrf, "principal": principal_payload(session_principal)},
                    token=auth_token,
                    csrf_token=csrf,
                    max_age=ttl,
                )
                return
            if parts == ["auth", "forgot-password"]:
                reset = PERSISTENCE.create_password_reset(str(payload.get("email", "")))
                response: Dict[str, Any] = {"ok": True}
                if reset is not None:
                    message = build_password_reset_email(
                        verification_base_url(_request_base_url(self)),
                        str(payload.get("email", "")),
                        str(reset["reset_token"]),
                        str(reset["reset_code"]),
                    )
                    if smtp_configured():
                        send_email(message)
                    else:
                        response["reset_token"] = reset["reset_token"]
                        response["reset_code"] = reset["reset_code"]
                _json_response(self, 200, response)
                return
            if parts == ["auth", "reset-password"]:
                principal = PERSISTENCE.reset_password(
                    token=str(payload.get("token") or payload.get("code") or ""),
                    email=str(payload.get("email") or ""),
                    new_password=str(payload.get("new_password") or payload.get("password") or ""),
                )
                PERSISTENCE.audit(principal, action="auth.reset_password", resource_type="user", resource_id=principal.user_id)
                auth_token, csrf, ttl, session_principal = _session_for_principal(principal)
                _auth_json_response(
                    self,
                    200,
                    {"ok": True, "token": auth_token, "csrf_token": csrf, "principal": principal_payload(session_principal)},
                    token=auth_token,
                    csrf_token=csrf,
                    max_age=ttl,
                )
                return
            if parts == ["auth", "change-password"]:
                principal = _authenticated(self)
                PERSISTENCE.change_password(
                    principal,
                    current_password=str(payload.get("current_password") or ""),
                    new_password=str(payload.get("new_password") or ""),
                )
                PERSISTENCE.revoke_other_auth_sessions(principal)
                PERSISTENCE.audit(principal, action="auth.change_password", resource_type="user", resource_id=principal.user_id)
                _json_response(self, 200, {"ok": True})
                return
            if parts == ["auth", "sessions"]:
                principal = _authenticated(self)
                PERSISTENCE.revoke_other_auth_sessions(principal)
                PERSISTENCE.audit(principal, action="auth.revoke_other_sessions", resource_type="user", resource_id=principal.user_id)
                _json_response(self, 200, PERSISTENCE.list_auth_sessions(principal))
                return
            if parts == ["auth", "resend-verification"]:
                principal = _authenticated(self)
                verification = PERSISTENCE.create_email_verification_for_user(principal)
                message = build_verification_email(
                    verification_base_url(_request_base_url(self)),
                    verification["email"],
                    verification["verification_token"],
                    verification["verification_code"],
                )
                response: Dict[str, Any] = {"ok": True}
                if smtp_configured():
                    send_email(message)
                else:
                    response.update(verification)
                PERSISTENCE.audit(principal, action="auth.resend_verification", resource_type="user", resource_id=principal.user_id)
                _json_response(self, 200, response)
                return
            if parts == ["auth", "login"]:
                principal = PERSISTENCE.authenticate_email_user(
                    email=str(payload.get("email", "")),
                    password=str(payload.get("password", "")),
                    require_verified=email_verification_required(),
                )
                token, csrf, ttl, session_principal = _session_for_principal(principal)
                PERSISTENCE.audit(
                    principal,
                    action="auth.login",
                    resource_type="user",
                    resource_id=principal.user_id,
                    details={"role": principal.role, "provider": "email"},
                )
                _auth_json_response(
                    self, 200, {"token": token, "csrf_token": csrf, "principal": principal_payload(session_principal)},
                    token=token, csrf_token=csrf, max_age=ttl,
                )
                return
            if parts == ["auth", "logout"]:
                principal = _authenticated(self)
                PERSISTENCE.revoke_auth_session(principal)
                PERSISTENCE.audit(principal, action="auth.logout", resource_type="user", resource_id=principal.user_id)
                _auth_json_response(self, 200, {"ok": True}, clear=True)
                return
            if parts == ["auth", "refresh"]:
                principal = _authenticated(self)
                session_id = secrets.token_urlsafe(24)
                ttl = int(os.environ.get("PLANORA_SESSION_TTL_SECONDS", "28800"))
                csrf = PERSISTENCE.create_auth_session(principal, session_id, ttl_seconds=ttl)
                refreshed = Principal(
                    user_id=principal.user_id, role=principal.role, tenant_id=principal.tenant_id,
                    groups=principal.groups, session_id=session_id, provider=principal.provider,
                    staff_id=principal.staff_id, student_group_id=principal.student_group_id,
                    scopes=principal.scopes,
                )
                token = create_auth_token(refreshed, ttl_seconds=ttl, session_id=session_id)
                PERSISTENCE.audit(principal, action="auth.refresh", resource_type="user", resource_id=principal.user_id)
                _auth_json_response(
                    self, 200, {"token": token, "csrf_token": csrf, "principal": principal_payload(refreshed)},
                    token=token, csrf_token=csrf, max_age=ttl,
                )
                return
            if parts == ["access", "join-invite"]:
                principal = _authenticated(self)
                updated = PERSISTENCE.redeem_invite_for_user(principal, str(payload.get("invite_code", "")))
                PERSISTENCE.audit(updated, action="access.join_invite", resource_type="user", resource_id=updated.user_id)
                PERSISTENCE.revoke_auth_session(principal)
                token, csrf, ttl, session_principal = _session_for_principal(updated)
                _auth_json_response(
                    self, 200, {
                        "ok": True,
                        "token": token,
                        "csrf_token": csrf,
                        "principal": principal_payload(session_principal),
                        "organizations": PERSISTENCE.user_organizations(session_principal)["organizations"],
                    },
                    token=token, csrf_token=csrf, max_age=ttl,
                )
                return
            if parts == ["access", "switch-organization"]:
                principal = _authenticated(self)
                updated = PERSISTENCE.switch_user_tenant(principal, str(payload.get("tenant_id", "")))
                PERSISTENCE.audit(updated, action="access.switch_organization", resource_type="tenant", resource_id=updated.tenant_id)
                PERSISTENCE.revoke_auth_session(principal)
                token, csrf, ttl, session_principal = _session_for_principal(updated)
                _auth_json_response(
                    self, 200, {
                        "ok": True,
                        "token": token,
                        "csrf_token": csrf,
                        "principal": principal_payload(session_principal),
                        "organizations": PERSISTENCE.user_organizations(session_principal)["organizations"],
                    },
                    token=token, csrf_token=csrf, max_age=ttl,
                )
                return
            if parts == ["sessions"]:
                principal = _authenticated(self, "schedule:read")
                inst_json, schedule, meta = _session_payload_from_request(payload)
                session = SESSION_STORE.create(
                    instance_json=inst_json,
                    schedule=schedule,
                    meta=stamp_meta(meta, principal),
                )
                PERSISTENCE.save_session(session)
                PERSISTENCE.audit(
                    principal,
                    action="session.create",
                    resource_type="session",
                    resource_id=session.session_id,
                    details={"activities": len(inst_json.get("activities") or {})},
                )
                _json_response(self, 200, session.to_dict(include_workspace=True))
                return
            if parts and parts[0] == "sessions" and len(parts) == 3:
                principal = _authenticated(self)
                session = _workspace_session(parts[1], principal)
                action_name = _canonical_action(parts[2])
                _require_action_permission(principal, action_name)
                result = _handle_session_action(parts[1], parts[2], payload)
                PERSISTENCE.save_session(SESSION_STORE.get(parts[1]))
                PERSISTENCE.audit(
                    principal,
                    action=f"session.{_canonical_action(parts[2])}",
                    resource_type="session",
                    resource_id=parts[1],
                    details={"payload_keys": sorted(payload.keys())},
                )
                _json_response(self, 200, result)
                return
            if parts and parts[0] == "jobs" and len(parts) == 2:
                if parts[1] == "cancel":
                    raise ValueError("Use /jobs/{job_id}/cancel.")
                principal = _authenticated(self)
                _require_action_permission(principal, _canonical_action(parts[1]))
                if payload.get("session_id"):
                    _workspace_session(str(payload["session_id"]), principal)
                result = _handle_job_submit(parts[1], payload, principal)
                _json_response(self, 200, result)
                return
            if parts and parts[0] == "jobs" and len(parts) == 3 and parts[2] == "cancel":
                principal = _authenticated(self, "solver:run")
                job = _job_record(parts[1], principal)
                _json_response(self, 200, JOB_STORE.cancel(parts[1]).to_dict())
                return
            if parts == ["access"]:
                principal = _authenticated(self, "access:manage")
                result = PERSISTENCE.apply_access_change(principal, payload)
                PERSISTENCE.audit(principal, action="access.change", resource_type="tenant", resource_id=str(payload.get("tenant_id") or principal.tenant_id), details={"action": payload.get("action")})
                _json_response(self, 200, result)
                return
            if parts == ["system", "email-test"]:
                principal = _global_admin(self)
                to_email = str(payload.get("email") or "").strip()
                if not to_email:
                    raise ValueError("Email is required.")
                message = build_verification_email(
                    verification_base_url(_request_base_url(self)),
                    to_email,
                    "verify_test_link_token",
                    "000000",
                )
                if smtp_configured():
                    send_email(message)
                else:
                    raise RuntimeError("SMTP is not configured.")
                PERSISTENCE.audit(principal, action="system.email_test", resource_type="email", resource_id=to_email)
                _json_response(self, 200, {"ok": True})
                return
            if parts == ["projects"]:
                principal = _authenticated(self, "projects:write")
                if payload.get("session_id"):
                    _workspace_session(str(payload["session_id"]), principal)
                payload["meta"] = stamp_meta(payload.get("meta") if isinstance(payload.get("meta"), dict) else {}, principal)
                if principal.is_global_admin and payload.get("tenant_id"):
                    payload["meta"]["tenant_id"] = str(payload["tenant_id"])
                result = _handle_project_save(payload)
                project_payload = dict(result.get("project") or {})
                PERSISTENCE.save_project(str(project_payload.get("name") or payload.get("name") or "project"), project_payload, principal)
                PERSISTENCE.audit(
                    principal,
                    action="project.save",
                    resource_type="project",
                    resource_id=str(project_payload.get("name") or payload.get("name") or "project"),
                    details={"has_schedule": bool(project_payload.get("schedule"))},
                )
                _json_response(self, 200, result)
                return
            if self.path == "/solve":
                _authenticated(self, "solver:run")
                result = _handle_solve(payload)
                _json_response(self, 200, result)
                return
            if self.path == "/portfolio":
                _authenticated(self, "solver:run")
                result = _handle_portfolio(payload)
                _json_response(self, 200, result)
                return
            if self.path == "/score":
                _authenticated(self, "schedule:read")
                result = _handle_score(payload)
                _json_response(self, 200, result)
                return
            if self.path == "/conflicts":
                _authenticated(self, "conflicts:read")
                result = _handle_conflicts(payload)
                _json_response(self, 200, result)
                return
            if self.path == "/improve":
                _authenticated(self, "solver:run")
                result = _handle_improve(payload)
                _json_response(self, 200, result)
                return
            if self.path == "/cp-polish":
                _authenticated(self, "solver:run")
                result = _handle_cp_polish(payload)
                _json_response(self, 200, result)
                return
            if self.path == "/import/csv":
                _authenticated(self, "schedule:write")
                result = _handle_import_csv(payload)
                _json_response(self, 200, result)
                return
            if self.path == "/export/csv":
                _authenticated(self, "schedule:read")
                result = _handle_export_csv(payload)
                _json_response(self, 200, result)
                return
            if self.path == "/graphql":
                principal = _authenticated(self, "schedule:read")
                result = _handle_graphql(payload, principal)
                _json_response(self, 200, result)
                return
        except Exception:
            raise

        _json_response(self, 404, {"error": "Not found"})


def _canonical_action(action: str) -> str:
    aliases = {
        "cp-polish": "cp_polish",
        "focused_cp_sat_polish": "cp_polish",
        "export-csv": "export_csv",
        "move": "move_activity",
        "move_deltas": "move_deltas",
        "lock": "lock_activity",
        "unlock": "unlock_activity",
    }
    raw = str(action or "").strip().replace("-", "_")
    return aliases.get(raw, raw)


def _require_action_permission(principal, action_name: str) -> None:
    action = _canonical_action(action_name)
    if action in {"score", "conflicts", "move_deltas", "export_csv"}:
        require_permission(principal, "schedule:read")
    elif action in {"solve", "portfolio", "improve", "cp_polish"}:
        require_permission(principal, "solver:run")
    elif action in {"move_activity", "lock_activity", "unlock_activity"}:
        require_permission(principal, "repair:write")


def _session_action_payload(
    session_id: str,
    action: str,
    payload: Dict[str, Any],
    *,
    progress_hook=None,
    stop_hook=None,
) -> Dict[str, Any]:
    session = SESSION_STORE.get(session_id)
    if isinstance(payload.get("hard_constraints"), dict):
        inst_json = dict(session.instance_json)
        hard = dict(inst_json.get("hard_constraints") or {})
        hard.update({str(k): v for k, v in dict(payload.get("hard_constraints") or {}).items()})
        inst_json["hard_constraints"] = hard
        SESSION_STORE.update(session_id, instance_json=inst_json)
        session = SESSION_STORE.get(session_id)
    result = run_workspace_action(
        instance_json=session.instance_json,
        schedule=session.schedule,
        action=_canonical_action(action),
        payload=payload,
        progress_hook=progress_hook,
        stop_hook=stop_hook,
    )
    new_instance = result.get("instance") if isinstance(result.get("instance"), dict) else None
    new_schedule = result.get("schedule") if isinstance(result.get("schedule"), dict) else None
    canonical_action = _canonical_action(action)
    if canonical_action in {"solve", "cp_polish"} and new_schedule is not None:
        raw_status = int(result.get("raw_status", result.get("status", 0)) or 0)
        if raw_status not in {2, 4} or not new_schedule:
            new_schedule = None
    if new_schedule is None and canonical_action == "portfolio":
        candidates = result.get("candidates") or []
        best_idx = int(result.get("best_index", -1))
        if 0 <= best_idx < len(candidates):
            best_result = dict(candidates[best_idx].get("result") or {})
            new_schedule = best_result.get("schedule") if isinstance(best_result.get("schedule"), dict) else None
            if best_result.get("meta"):
                session.meta = dict(best_result.get("meta") or {})
    if new_schedule is not None or new_instance is not None:
        SESSION_STORE.update(
            session_id,
            instance_json=new_instance,
            schedule=new_schedule,
            meta=(result.get("meta") if isinstance(result.get("meta"), dict) else session.meta),
        )
    return {"session": SESSION_STORE.get(session_id).to_dict(include_workspace=False), "result": result}


def _handle_session_action(session_id: str, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return _session_action_payload(session_id, action, payload)


def _handle_job_submit(action: str, payload: Dict[str, Any], principal: Principal) -> Dict[str, Any]:
    action_name = _canonical_action(action)
    supported = {"improve", "score", "conflicts", "export_csv", "move_deltas"}
    if action_name not in supported:
        raise ValueError(
            f"Background action {action_name!r} is not cancellable. Use the synchronous endpoint for that action."
        )
    session_id = str(payload.get("session_id", "") or "")

    def _run(job) -> Dict[str, Any]:
        def _progress(iteration: int, best_penalty: int, current_penalty: int) -> None:
            total_iterations = int(dict(payload.get("options") or {}).get("iterations", 0) or 0)
            JOB_STORE.update(
                job.job_id,
                progress={
                    "event": "local_search",
                    "iteration": int(iteration),
                    "iterations": total_iterations,
                    "best_penalty": int(best_penalty),
                    "current_penalty": int(current_penalty),
                },
            )

        if session_id:
            _workspace_session(session_id, principal)
            return _session_action_payload(
                session_id,
                action_name,
                payload,
                progress_hook=(_progress if action_name == "improve" else None),
                stop_hook=(lambda: bool(job.cancel_requested)),
            ).get("result", {})
        inst_json, schedule, _meta = _session_payload_from_request(payload)
        return run_workspace_action(
            instance_json=inst_json,
            schedule=schedule,
            action=action_name,
            payload=payload,
            progress_hook=(_progress if action_name == "improve" else None),
            stop_hook=(lambda: bool(job.cancel_requested)),
        )

    job = JOB_STORE.submit(
        action_name,
        _run,
        tenant_id=principal.tenant_id,
        created_by=principal.user_id,
    )
    return job.to_dict()


def _handle_project_save(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = safe_project_name(str(payload.get("name", "") or "project"))
    if payload.get("session_id"):
        session = SESSION_STORE.get(str(payload["session_id"]))
        project_payload = {
            "name": name,
            "instance": session.instance_json,
            "schedule": normalize_schedule(session.schedule),
            "meta": dict(session.meta or {}),
        }
    else:
        inst_json, schedule, meta = _session_payload_from_request(payload)
        project_payload = {
            "name": name,
            "instance": inst_json,
            "schedule": normalize_schedule(schedule),
            "meta": dict(meta or {}),
        }
    saved = {"name": safe_project_name(name), "storage": "sqlite"}
    return {"saved": saved, "project": project_payload}


def _safe_optional_local_path(raw: Any) -> str | None:
    if raw in (None, ""):
        return None
    candidate = Path(str(raw)).expanduser()
    if not candidate.is_absolute():
        candidate = (ROOT_DIR / candidate).resolve()
    else:
        candidate = candidate.resolve()
    allowed_roots = [(ROOT_DIR / "data").resolve(), Path(tempfile.gettempdir()).resolve()]
    if not any(root == candidate or root in candidate.parents for root in allowed_roots):
        raise ValueError("Local file path is outside the scheduler workspace.")
    if not candidate.exists():
        raise FileNotFoundError(str(candidate))
    return str(candidate)


def _handle_import_csv(payload: Dict[str, Any]) -> Dict[str, Any]:
    content = str(payload.get("content", "") or "")
    if not content.strip():
        raise ValueError("Payload missing CSV content.")
    filename = str(payload.get("filename", "uploaded.csv") or "uploaded.csv")
    suffix = Path(filename).suffix or ".csv"
    with tempfile.NamedTemporaryFile("w", suffix=suffix, encoding="utf-8", newline="", delete=False) as fh:
        fh.write(content)
        tmp_path = Path(fh.name)
    try:
        inst, schedule, meta = import_timetable_csv(
            tmp_path,
            lock_imported=bool(payload.get("lock_imported", False)),
            field_map=payload.get("field_map") if isinstance(payload.get("field_map"), dict) else None,
            transform_config=(
                payload.get("transform_config")
                if isinstance(payload.get("transform_config"), dict)
                else None
            ),
            teaching_load_path=_safe_optional_local_path(payload.get("teaching_load_path")),
        )
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass
    return {
        "instance": instance_to_json(inst),
        "schedule": schedule,
        "meta": dict(meta or {}),
        "score": score_schedule(inst, schedule),
    }


def serve(*, host: str = "127.0.0.1", port: int = 8787) -> None:
    ThreadingHTTPServer((host, int(port)), PlanoraApiHandler).serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Planora integration API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)
    serve(host=str(args.host), port=int(args.port))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
