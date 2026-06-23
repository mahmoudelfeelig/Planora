from __future__ import annotations

from typing import Any, Dict


def openapi_schema() -> Dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Planora Local Scheduler API", "version": "1.0.0"},
        "paths": {
            "/health": {"get": {"summary": "Health check"}, "head": {"summary": "Health check headers"}},
            "/ready": {"get": {"summary": "Readiness check"}, "head": {"summary": "Readiness check headers"}},
            "/capabilities": {"get": {"summary": "List UI/API capabilities"}},
            "/auth/whoami": {"get": {"summary": "Return current principal and permissions"}},
            "/auth/config": {"get": {"summary": "Read email/password authentication configuration"}},
            "/auth/register": {"post": {"summary": "Register using email, password, and an invite code"}},
            "/auth/verify": {"get": {"summary": "Verify an email confirmation token"}, "post": {"summary": "Verify an email confirmation token"}},
            "/auth/forgot-password": {"post": {"summary": "Request a password reset email"}},
            "/auth/reset-password": {"post": {"summary": "Reset password using a link token or emailed code"}},
            "/auth/change-password": {"post": {"summary": "Change password for the current account"}},
            "/auth/sessions": {"get": {"summary": "List current account sessions"}, "post": {"summary": "Revoke other account sessions"}},
            "/auth/resend-verification": {"post": {"summary": "Resend email verification"}},
            "/auth/login": {"post": {"summary": "Sign in with email and password"}},
            "/auth/refresh": {"post": {"summary": "Rotate the authenticated session"}},
            "/auth/logout": {"post": {"summary": "Revoke and clear the authenticated session"}},
            "/access": {"get": {"summary": "Read tenant access settings"}, "post": {"summary": "Apply a tenant access change"}},
            "/access/my-organizations": {"get": {"summary": "List organizations linked to the current account"}},
            "/access/join-invite": {"post": {"summary": "Redeem an invite code after account creation"}},
            "/access/switch-organization": {"post": {"summary": "Switch the current account's active organization"}},
            "/audit": {"get": {"summary": "List tenant-scoped audit events"}},
            "/analytics/event": {"post": {"summary": "Record a consented first-party analytics event"}},
            "/events/collect": {"post": {"summary": "Record a consented first-party telemetry event"}},
            "/analytics/summary": {"get": {"summary": "Read first-party analytics summary"}},
            "/analytics/export.csv": {"get": {"summary": "Export first-party analytics summary as CSV"}},
            "/system": {"get": {"summary": "Return API and persistence health"}},
            "/system/status": {"get": {"summary": "Return admin-only runtime and resource status"}},
            "/system/email-test": {"post": {"summary": "Send a test email to validate SMTP delivery"}},
            "/parity": {"get": {"summary": "Return desktop/backend/web parity manifest"}},
            "/sessions": {"post": {"summary": "Create a backend workspace session"}},
            "/sessions/{session_id}": {"get": {"summary": "Read session workspace"}},
            "/sessions/{session_id}/{action}": {
                "post": {
                    "summary": "Run a shared scheduler action on a session",
                    "description": "Actions include solve, portfolio, score, conflicts, improve, cp-polish, move, lock, unlock, and export-csv.",
                }
            },
            "/jobs/{action}": {"post": {"summary": "Start an async shared scheduler action"}},
            "/jobs/{job_id}": {"get": {"summary": "Poll async job state"}, "post": {"summary": "Cancel async job"}},
            "/jobs/{job_id}/events": {"get": {"summary": "Read Server-Sent Events job snapshot"}},
            "/projects": {"get": {"summary": "List saved local web projects"}, "post": {"summary": "Save a local web project"}},
            "/projects/{name}": {
                "get": {"summary": "Load a tenant-scoped web project"},
                "delete": {"summary": "Delete a tenant-scoped web project"},
            },
            "/solve": {"post": {"summary": "Solve one instance without session state"}},
            "/portfolio": {"post": {"summary": "Run portfolio solve without session state"}},
            "/import/csv": {"post": {"summary": "Import timetable CSV content"}},
            "/export/csv": {"post": {"summary": "Export schedule CSV content"}},
        },
    }
