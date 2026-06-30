from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List

from services.auth_service import Principal, ROLE_ORDER, can_access_tenant
from services.password_auth_service import (
    expires_at,
    hash_password,
    hash_token,
    new_plain_token,
    new_verification_code,
    normalize_email,
    should_rehash_password,
    verify_password,
)
from services import persistence_access, persistence_audit, persistence_schema
from services.persistence_config import default_persistence_path


class PersistenceStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            persistence_schema.init_schema(conn)

    def _schema_version(self, conn: sqlite3.Connection) -> int:
        return persistence_schema.schema_version(conn)

    def _has_column(self, conn: sqlite3.Connection, table: str, column: str) -> bool:
        return persistence_schema.has_column(conn, table, column)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        persistence_schema.migrate(conn)

    def schema_info(self) -> Dict[str, Any]:
        with self._connect() as conn:
            return persistence_schema.schema_info(conn, self.path)

    def upsert_user(self, principal: Principal) -> None:
        with self._connect() as conn:
            now = time.time()
            conn.execute(
                """
                INSERT INTO tenants(tenant_id, display_name, enabled, created_at, updated_at)
                VALUES(?, ?, 1, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (principal.tenant_id, principal.tenant_id, now, now),
            )
            conn.execute(
                """
                INSERT INTO users(
                    user_id, tenant_id, role, display_name, provider, disabled,
                    staff_id, student_group_id, updated_at
                )
                VALUES(?, ?, ?, ?, ?, 0, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    display_name=excluded.display_name,
                    provider=excluded.provider,
                    staff_id=COALESCE(excluded.staff_id, users.staff_id),
                    student_group_id=COALESCE(excluded.student_group_id, users.student_group_id),
                    updated_at=excluded.updated_at
                """,
                (
                    principal.user_id,
                    principal.tenant_id,
                    principal.role,
                    principal.user_id,
                    principal.provider,
                    principal.staff_id,
                    principal.student_group_id,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO account_tenants(user_id, tenant_id, role, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(user_id, tenant_id) DO UPDATE SET
                    role=excluded.role,
                    updated_at=excluded.updated_at
                """,
                (principal.user_id, principal.tenant_id, principal.role, now, now),
            )

    def resolve_principal(self, principal: Principal) -> Principal:
        with self._connect() as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE user_id=?",
                (principal.user_id,),
            ).fetchone()
            if user is None:
                if (
                    os.environ.get("PLANORA_PRODUCTION", "0").lower() in {"1", "true", "yes", "on"}
                    and principal.provider != "dev-header"
                ):
                    raise PermissionError("This account is no longer active.")
                return principal
            if bool(user["disabled"]):
                raise PermissionError("This account is disabled.")
            active_tenant_id = str(user["tenant_id"] or principal.tenant_id)
            tenant = conn.execute(
                "SELECT enabled FROM tenants WHERE tenant_id=?",
                (active_tenant_id,),
            ).fetchone()
            if tenant is not None and not bool(tenant["enabled"]):
                raise PermissionError("This tenant is disabled.")
            account_row = conn.execute(
                "SELECT role, disabled, staff_id, student_group_id FROM account_tenants WHERE user_id=? AND tenant_id=?",
                (principal.user_id, active_tenant_id),
            ).fetchone()
            if account_row is not None and bool(account_row["disabled"]):
                raise PermissionError("This account is disabled for the active organization.")
            groups = [
                str(row["group_id"])
                for row in conn.execute(
                    "SELECT group_id FROM group_memberships WHERE tenant_id=? AND user_id=? ORDER BY group_id",
                    (active_tenant_id, principal.user_id),
                ).fetchall()
            ]
            roles = [str(account_row["role"] if account_row is not None else user["role"])]
            bindings = conn.execute(
                """
                SELECT role, scope_type, scope_id FROM role_bindings
                WHERE tenant_id=? AND (
                    (principal_type='user' AND principal_id=?) OR
                    (principal_type='group' AND principal_id IN (
                        SELECT group_id FROM group_memberships WHERE tenant_id=? AND user_id=?
                    ))
                )
                """,
                (active_tenant_id, principal.user_id, active_tenant_id, principal.user_id),
            ).fetchall()
            roles.extend(
                str(row["role"])
                for row in bindings
                if str(row["scope_type"]) == "tenant" and str(row["scope_id"]) == "*"
            )
            role = max(roles, key=lambda value: ROLE_ORDER.get(value, -1))
            return Principal(
                user_id=principal.user_id,
                role=role,
                tenant_id=active_tenant_id,
                groups=tuple(groups),
                session_id=principal.session_id,
                provider=str(user["provider"] or principal.provider),
                staff_id=(
                    int(account_row["staff_id"])
                    if account_row is not None and account_row["staff_id"] is not None
                    else (int(user["staff_id"]) if user["staff_id"] is not None else None)
                ),
                student_group_id=(
                    int(account_row["student_group_id"])
                    if account_row is not None and account_row["student_group_id"] is not None
                    else (int(user["student_group_id"]) if user["student_group_id"] is not None else None)
                ),
                scopes=tuple(
                    (str(row["role"]), str(row["scope_type"]), str(row["scope_id"]))
                    for row in bindings
                ),
            )

    def create_auth_session(self, principal: Principal, session_id: str, *, ttl_seconds: int) -> str:
        csrf = secrets.token_urlsafe(32)
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_sessions(
                    session_id, tenant_id, user_id, csrf_token, expires_at,
                    revoked_at, created_at, last_seen_at
                ) VALUES(?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (session_id, principal.tenant_id, principal.user_id, csrf, now + ttl_seconds, now, now),
            )
        return csrf

    def require_active_session(self, principal: Principal) -> None:
        if not principal.session_id:
            return
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT expires_at, revoked_at FROM auth_sessions WHERE session_id=? AND tenant_id=? AND user_id=?",
                (principal.session_id, principal.tenant_id, principal.user_id),
            ).fetchone()
            if row is None:
                require_record = os.environ.get(
                    "PLANORA_REQUIRE_AUTH_SESSION_RECORD",
                    "0",
                ).lower() in {"1", "true", "yes", "on"}
                if require_record:
                    raise PermissionError("Authentication session is not active.")
                return
            if row["revoked_at"] is not None or float(row["expires_at"]) <= now:
                raise PermissionError("Authentication session expired or revoked.")
            conn.execute(
                "UPDATE auth_sessions SET last_seen_at=? WHERE session_id=?",
                (now, principal.session_id),
            )

    def revoke_auth_session(self, principal: Principal) -> None:
        if not principal.session_id:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE session_id=? AND user_id=?",
                (time.time(), principal.session_id, principal.user_id),
            )

    def replace_auth_session(
        self,
        principal: Principal,
        next_session_id: str,
        *,
        ttl_seconds: int,
    ) -> str:
        csrf = secrets.token_urlsafe(32)
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO auth_sessions(
                    session_id, tenant_id, user_id, csrf_token, expires_at,
                    revoked_at, created_at, last_seen_at
                ) VALUES(?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (next_session_id, principal.tenant_id, principal.user_id, csrf, now + ttl_seconds, now, now),
            )
            if principal.session_id:
                conn.execute(
                    "UPDATE auth_sessions SET revoked_at=? WHERE session_id=? AND user_id=?",
                    (now, principal.session_id, principal.user_id),
                )
        return csrf

    def list_auth_sessions(self, principal: Principal) -> Dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, tenant_id, expires_at, revoked_at, created_at, last_seen_at
                FROM auth_sessions
                WHERE user_id=?
                ORDER BY last_seen_at DESC
                LIMIT 50
                """,
                (principal.user_id,),
            ).fetchall()
        return {
            "sessions": [
                {
                    "session_id": str(row["session_id"]),
                    "tenant_id": str(row["tenant_id"]),
                    "current": str(row["session_id"]) == str(principal.session_id or ""),
                    "active": row["revoked_at"] is None and float(row["expires_at"]) > now,
                    "expires_at": float(row["expires_at"]),
                    "revoked_at": float(row["revoked_at"]) if row["revoked_at"] is not None else None,
                    "created_at": float(row["created_at"]),
                    "last_seen_at": float(row["last_seen_at"]),
                }
                for row in rows
            ]
        }

    def revoke_other_auth_sessions(self, principal: Principal) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE auth_sessions SET revoked_at=?
                WHERE user_id=? AND session_id<>? AND revoked_at IS NULL
                """,
                (time.time(), principal.user_id, principal.session_id or ""),
            )

    def change_password(self, principal: Principal, *, current_password: str, new_password: str) -> None:
        if not principal.user_id.startswith("email:"):
            raise PermissionError("Only email/password accounts can change password.")
        with self._connect() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE user_id=? AND provider='email'", (principal.user_id,)).fetchone()
            if row is None or not row["password_hash"] or not verify_password(str(row["password_hash"]), current_password):
                raise PermissionError("Current password is incorrect.")
            conn.execute(
                "UPDATE users SET password_hash=?, updated_at=? WHERE user_id=?",
                (hash_password(new_password), time.time(), principal.user_id),
            )

    def create_email_verification_for_user(self, principal: Principal, *, verification_ttl_seconds: int = 86400) -> Dict[str, str]:
        if not principal.user_id.startswith("email:"):
            raise PermissionError("Only email accounts can request verification.")
        token = new_plain_token("verify_")
        code = new_verification_code()
        now = time.time()
        with self._connect() as conn:
            user = conn.execute(
                "SELECT tenant_id, email, email_verified_at FROM users WHERE user_id=? AND provider='email'",
                (principal.user_id,),
            ).fetchone()
            if user is None:
                raise PermissionError("Email account was not found.")
            if user["email_verified_at"] is not None:
                raise ValueError("Email is already verified.")
            conn.execute(
                "UPDATE email_verification_tokens SET consumed_at=? WHERE user_id=? AND consumed_at IS NULL",
                (now, principal.user_id),
            )
            for plain in (token, code):
                conn.execute(
                    """
                    INSERT INTO email_verification_tokens(token_hash, user_id, tenant_id, expires_at, consumed_at, created_at)
                    VALUES(?, ?, ?, ?, NULL, ?)
                    """,
                    (hash_token(plain), principal.user_id, str(user["tenant_id"]), expires_at(verification_ttl_seconds), now),
                )
        return {"email": str(user["email"] or principal.user_id.removeprefix("email:")), "verification_token": token, "verification_code": code}

    def _invite_by_code_hash(self, conn: sqlite3.Connection, code_hash: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM invite_codes WHERE code_hash=?", (code_hash,)).fetchone()
        now = time.time()
        if row is None or bool(row["disabled"]):
            raise PermissionError("Invite code is invalid.")
        if row["expires_at"] is not None and float(row["expires_at"]) <= now:
            raise PermissionError("Invite code has expired.")
        if row["max_uses"] is not None and int(row["used_count"]) >= int(row["max_uses"]):
            raise PermissionError("Invite code has already been used.")
        return row

    def register_email_user(
        self,
        *,
        email: str,
        password: str,
        display_name: str = "",
        invite_code: str = "",
        verification_ttl_seconds: int = 86400,
    ) -> Dict[str, Any]:
        normalized_email = normalize_email(email)
        user_id = f"email:{normalized_email}"
        verification_token = new_plain_token("verify_")
        verification_code = new_verification_code()
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            invite = self._invite_by_code_hash(conn, hash_token(invite_code)) if invite_code else None
            if conn.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone() is not None:
                raise ValueError("An account with this email already exists.")
            tenant_id = str(invite["tenant_id"]) if invite is not None else "default"
            role = str(invite["role"]) if invite is not None else "student"
            conn.execute(
                """
                INSERT INTO tenants(tenant_id, display_name, enabled, created_at, updated_at)
                VALUES(?, ?, 1, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (tenant_id, tenant_id, now, now),
            )
            conn.execute(
                """
                INSERT INTO users(
                    user_id, tenant_id, role, display_name, provider, email,
                    password_hash, disabled, updated_at
                ) VALUES(?, ?, ?, ?, 'email', ?, ?, 0, ?)
                """,
                (user_id, tenant_id, role, display_name or normalized_email, normalized_email, hash_password(password), now),
            )
            conn.execute(
                """
                INSERT INTO account_tenants(user_id, tenant_id, role, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(user_id, tenant_id) DO UPDATE SET role=excluded.role, updated_at=excluded.updated_at
                """,
                (user_id, tenant_id, role, now, now),
            )
            if invite is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO group_memberships(tenant_id, group_id, user_id, created_at) VALUES(?, ?, ?, ?)",
                    (tenant_id, str(invite["group_id"]), user_id, now),
                )
                conn.execute(
                    "UPDATE invite_codes SET used_count=used_count + 1, updated_at=? WHERE invite_id=?",
                    (now, str(invite["invite_id"])),
                )
            conn.execute(
                """
                INSERT INTO email_verification_tokens(token_hash, user_id, tenant_id, expires_at, consumed_at, created_at)
                VALUES(?, ?, ?, ?, NULL, ?)
                """,
                (hash_token(verification_token), user_id, tenant_id, expires_at(verification_ttl_seconds), now),
            )
            conn.execute(
                """
                INSERT INTO email_verification_tokens(token_hash, user_id, tenant_id, expires_at, consumed_at, created_at)
                VALUES(?, ?, ?, ?, NULL, ?)
                """,
                (hash_token(verification_code), user_id, tenant_id, expires_at(verification_ttl_seconds), now),
            )
        principal = self.resolve_principal(Principal(user_id=user_id, role=role, tenant_id=tenant_id, provider="email"))
        return {"principal": principal, "verification_token": verification_token, "verification_code": verification_code}

    def redeem_invite_for_user(self, principal: Principal, invite_code: str) -> Principal:
        invite_hash = hash_token(invite_code)
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            invite = self._invite_by_code_hash(conn, invite_hash)
            tenant_id = str(invite["tenant_id"])
            membership = conn.execute(
                "INSERT OR IGNORE INTO group_memberships(tenant_id, group_id, user_id, created_at) VALUES(?, ?, ?, ?)",
                (tenant_id, str(invite["group_id"]), principal.user_id, now),
            )
            invite_role = str(invite["role"])
            existing_role = conn.execute(
                "SELECT role FROM account_tenants WHERE user_id=? AND tenant_id=?",
                (principal.user_id, tenant_id),
            ).fetchone()
            next_role = invite_role
            if existing_role is not None and ROLE_ORDER.get(str(existing_role["role"]), 0) > ROLE_ORDER.get(invite_role, 0):
                next_role = str(existing_role["role"])
            conn.execute(
                """
                INSERT INTO account_tenants(user_id, tenant_id, role, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(user_id, tenant_id) DO UPDATE SET
                    role=excluded.role,
                    updated_at=excluded.updated_at
                """,
                (principal.user_id, tenant_id, next_role, now, now),
            )
            conn.execute(
                "UPDATE users SET tenant_id=?, role=?, updated_at=? WHERE user_id=?",
                (tenant_id, next_role, now, principal.user_id),
            )
            if membership.rowcount:
                conn.execute(
                    "UPDATE invite_codes SET used_count=used_count + 1, updated_at=? WHERE invite_id=?",
                    (now, str(invite["invite_id"])),
                )
        return self.resolve_principal(
            Principal(
                user_id=principal.user_id,
                role=principal.role,
                tenant_id=tenant_id,
                session_id=principal.session_id,
                provider=principal.provider,
                staff_id=principal.staff_id,
                student_group_id=principal.student_group_id,
                scopes=principal.scopes,
            )
        )

    def user_organizations(self, principal: Principal) -> Dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT at.tenant_id, at.role, t.display_name, t.enabled,
                    CASE WHEN at.tenant_id=? THEN 1 ELSE 0 END AS active,
                    COUNT(gm.group_id) AS group_count
                FROM account_tenants at
                LEFT JOIN tenants t ON t.tenant_id=at.tenant_id
                LEFT JOIN group_memberships gm ON gm.tenant_id=at.tenant_id AND gm.user_id=at.user_id
                WHERE at.user_id=?
                GROUP BY at.tenant_id, at.role, t.display_name, t.enabled
                ORDER BY active DESC, COALESCE(t.display_name, at.tenant_id)
                """,
                (principal.tenant_id, principal.user_id),
            ).fetchall()
        return {
            "organizations": [
                {
                    "tenant_id": str(row["tenant_id"]),
                    "display_name": str(row["display_name"] or row["tenant_id"]),
                    "role": str(row["role"]),
                    "enabled": bool(row["enabled"]) if row["enabled"] is not None else True,
                    "active": bool(row["active"]),
                    "group_count": int(row["group_count"] or 0),
                }
                for row in rows
            ]
        }

    def switch_user_tenant(self, principal: Principal, tenant_id: str) -> Principal:
        target_tenant = str(tenant_id or "").strip()
        if not target_tenant:
            raise ValueError("Organization is required.")
        now = time.time()
        with self._connect() as conn:
            account = conn.execute(
                "SELECT role, disabled FROM account_tenants WHERE user_id=? AND tenant_id=?",
                (principal.user_id, target_tenant),
            ).fetchone()
            if account is None and not principal.is_global_admin:
                raise PermissionError("You do not belong to that organization.")
            if account is not None and bool(account["disabled"]):
                raise PermissionError("Your account is disabled for that organization.")
            tenant = conn.execute("SELECT enabled FROM tenants WHERE tenant_id=?", (target_tenant,)).fetchone()
            if tenant is None:
                raise ValueError("Organization was not found.")
            if tenant is not None and not bool(tenant["enabled"]):
                raise PermissionError("That organization is disabled.")
            role = str(account["role"] if account is not None else principal.role)
            conn.execute(
                "UPDATE users SET tenant_id=?, role=?, updated_at=? WHERE user_id=?",
                (target_tenant, role, now, principal.user_id),
            )
        return self.resolve_principal(
            Principal(
                user_id=principal.user_id,
                role=principal.role,
                tenant_id=target_tenant,
                session_id=principal.session_id,
                provider=principal.provider,
                staff_id=principal.staff_id,
                student_group_id=principal.student_group_id,
                scopes=principal.scopes,
            )
        )

    def verify_email_token(self, token: str, *, email: str = "") -> Principal:
        raw_token = str(token or "").strip()
        token_hash = hash_token(raw_token)
        user_id = f"email:{normalize_email(email)}" if email and not raw_token.startswith("verify_") else ""
        now = time.time()
        with self._connect() as conn:
            if user_id:
                row = conn.execute(
                    "SELECT * FROM email_verification_tokens WHERE token_hash=? AND user_id=?",
                    (token_hash, user_id),
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM email_verification_tokens WHERE token_hash=?", (token_hash,)).fetchone()
            if row is None or row["consumed_at"] is not None or float(row["expires_at"]) <= now:
                raise PermissionError("Verification token is invalid, expired, or already used.")
            conn.execute(
                "UPDATE email_verification_tokens SET consumed_at=? WHERE user_id=? AND tenant_id=? AND consumed_at IS NULL",
                (now, str(row["user_id"]), str(row["tenant_id"])),
            )
            conn.execute(
                "UPDATE users SET email_verified_at=?, updated_at=? WHERE user_id=? AND tenant_id=?",
                (now, now, str(row["user_id"]), str(row["tenant_id"])),
            )
            user = conn.execute(
                "SELECT * FROM users WHERE user_id=? AND tenant_id=?",
                (str(row["user_id"]), str(row["tenant_id"])),
            ).fetchone()
        if user is None:
            raise PermissionError("Verification account no longer exists.")
        return self.resolve_principal(Principal(user_id=str(user["user_id"]), role=str(user["role"]), tenant_id=str(user["tenant_id"]), provider="email"))

    def create_password_reset(self, email: str, *, reset_ttl_seconds: int = 3600) -> Dict[str, Any] | None:
        normalized_email = normalize_email(email)
        user_id = f"email:{normalized_email}"
        reset_token = new_plain_token("reset_")
        reset_code = new_verification_code()
        now = time.time()
        with self._connect() as conn:
            user = conn.execute(
                "SELECT user_id, tenant_id FROM users WHERE user_id=? AND provider='email' AND disabled=0",
                (user_id,),
            ).fetchone()
            if user is None:
                return None
            conn.execute(
                "UPDATE password_reset_tokens SET consumed_at=? WHERE user_id=? AND consumed_at IS NULL",
                (now, user_id),
            )
            for plain in (reset_token, reset_code):
                conn.execute(
                    """
                    INSERT INTO password_reset_tokens(token_hash, user_id, tenant_id, expires_at, consumed_at, created_at)
                    VALUES(?, ?, ?, ?, NULL, ?)
                    """,
                    (hash_token(plain), user_id, str(user["tenant_id"]), expires_at(reset_ttl_seconds), now),
                )
        return {"reset_token": reset_token, "reset_code": reset_code}

    def reset_password(self, *, token: str, email: str = "", new_password: str) -> Principal:
        raw_token = str(token or "").strip()
        token_hash = hash_token(raw_token)
        user_id = f"email:{normalize_email(email)}" if email and not raw_token.startswith("reset_") else ""
        now = time.time()
        with self._connect() as conn:
            if user_id:
                row = conn.execute(
                    "SELECT * FROM password_reset_tokens WHERE token_hash=? AND user_id=?",
                    (token_hash, user_id),
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM password_reset_tokens WHERE token_hash=?", (token_hash,)).fetchone()
            if row is None or row["consumed_at"] is not None or float(row["expires_at"]) <= now:
                raise PermissionError("Password reset token is invalid, expired, or already used.")
            password_hash = hash_password(new_password)
            conn.execute(
                "UPDATE users SET password_hash=?, updated_at=? WHERE user_id=? AND tenant_id=?",
                (password_hash, now, str(row["user_id"]), str(row["tenant_id"])),
            )
            conn.execute(
                "UPDATE password_reset_tokens SET consumed_at=? WHERE user_id=? AND tenant_id=? AND consumed_at IS NULL",
                (now, str(row["user_id"]), str(row["tenant_id"])),
            )
            conn.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (now, str(row["user_id"])),
            )
            user = conn.execute(
                "SELECT * FROM users WHERE user_id=? AND tenant_id=?",
                (str(row["user_id"]), str(row["tenant_id"])),
            ).fetchone()
        if user is None:
            raise PermissionError("Password reset account no longer exists.")
        return self.resolve_principal(Principal(user_id=str(user["user_id"]), role=str(user["role"]), tenant_id=str(user["tenant_id"]), provider="email"))

    def authenticate_email_user(self, *, email: str, password: str, require_verified: bool = True) -> Principal:
        normalized_email = normalize_email(email)
        user_id = f"email:{normalized_email}"
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id=? AND provider='email'", (user_id,)).fetchone()
            if row is None or bool(row["disabled"]) or not row["password_hash"]:
                raise PermissionError("Email or password is incorrect.")
            if require_verified and row["email_verified_at"] is None:
                raise PermissionError("Email address is not verified.")
            password_hash = str(row["password_hash"])
            if not verify_password(password_hash, password):
                raise PermissionError("Email or password is incorrect.")
            if should_rehash_password(password_hash):
                conn.execute(
                    "UPDATE users SET password_hash=?, updated_at=? WHERE user_id=?",
                    (hash_password(password), time.time(), user_id),
                )
        return self.resolve_principal(Principal(user_id=user_id, role=str(row["role"]), tenant_id=str(row["tenant_id"]), provider="email"))

    def access_snapshot(self, principal: Principal) -> Dict[str, Any]:
        return persistence_access.access_snapshot(self, principal)

    def apply_access_change(self, principal: Principal, change: Dict[str, Any]) -> Dict[str, Any]:
        return persistence_access.apply_access_change(self, principal, change)

    def bootstrap_user_role(self, *, user_id: str, tenant_id: str, role: str) -> None:
        from services.auth_service import ROLES

        if role not in ROLES:
            raise ValueError(f"Unknown role: {role}")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM users WHERE user_id=?",
                (user_id,),
            ).fetchone()
            if row is None:
                raise ValueError("The user must register once before bootstrapping.")
            conn.execute(
                """
                INSERT INTO tenants(tenant_id, display_name, enabled, created_at, updated_at)
                VALUES(?, ?, 1, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (tenant_id, tenant_id, time.time(), time.time()),
            )
            conn.execute(
                "UPDATE users SET tenant_id=?, role=?, updated_at=? WHERE user_id=?",
                (tenant_id, role, time.time(), user_id),
            )
            conn.execute(
                """
                INSERT INTO account_tenants(user_id, tenant_id, role, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(user_id, tenant_id) DO UPDATE SET role=excluded.role, updated_at=excluded.updated_at
                """,
                (user_id, tenant_id, role, time.time(), time.time()),
            )

    def save_session(self, session: Any) -> None:
        meta = dict(session.meta or {})
        tenant_id = str(meta.get("tenant_id", "default") or "default")
        created_by = str(meta.get("created_by", "unknown") or "unknown")
        role = str(meta.get("created_by_role", "student") or "student")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(
                    session_id, tenant_id, created_by, role,
                    instance_json, schedule_json, meta_json, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    created_by=excluded.created_by,
                    role=excluded.role,
                    instance_json=excluded.instance_json,
                    schedule_json=excluded.schedule_json,
                    meta_json=excluded.meta_json,
                    updated_at=excluded.updated_at
                """,
                (
                    str(session.session_id),
                    tenant_id,
                    created_by,
                    role,
                    json.dumps(session.instance_json, ensure_ascii=False),
                    json.dumps(session.schedule, ensure_ascii=False),
                    json.dumps(meta, ensure_ascii=False),
                    float(session.created_at),
                    float(session.updated_at),
                ),
            )
            maximum = max(10, int(os.environ.get("PLANORA_MAX_PERSISTED_SESSIONS_PER_TENANT", "100")))
            conn.execute(
                """
                DELETE FROM sessions
                WHERE tenant_id=? AND session_id NOT IN (
                    SELECT session_id FROM sessions WHERE tenant_id=? ORDER BY updated_at DESC LIMIT ?
                )
                """,
                (tenant_id, tenant_id, maximum),
            )

    def load_session(self, session_id: str, principal: Principal) -> Dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (str(session_id),)).fetchone()
        if row is None:
            return None
        if not can_access_tenant(principal, str(row["tenant_id"])):
            raise PermissionError("This user cannot access that tenant workspace.")
        return {
            "session_id": str(row["session_id"]),
            "instance_json": json.loads(str(row["instance_json"])),
            "schedule": json.loads(str(row["schedule_json"])),
            "meta": json.loads(str(row["meta_json"])),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def save_job(self, job: Any) -> None:
        payload = job.to_dict()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs(
                    job_id, tenant_id, created_by, action, status, progress_json,
                    result_json, error, cancel_requested, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    status=excluded.status, progress_json=excluded.progress_json,
                    result_json=excluded.result_json, error=excluded.error,
                    cancel_requested=excluded.cancel_requested, updated_at=excluded.updated_at
                """,
                (
                    payload["job_id"], payload["tenant_id"], payload["created_by"], payload["action"],
                    payload["status"], json.dumps(payload.get("progress") or {}),
                    json.dumps(payload["result"]) if payload.get("result") is not None else None,
                    payload.get("error"), int(bool(payload.get("cancel_requested"))),
                    payload["created_at"], payload["updated_at"],
                ),
            )
            maximum = max(20, int(os.environ.get("PLANORA_MAX_PERSISTED_JOBS_PER_TENANT", "500")))
            conn.execute(
                """
                DELETE FROM jobs
                WHERE tenant_id=? AND status IN ('complete', 'done', 'failed', 'cancelled')
                    AND job_id NOT IN (
                        SELECT job_id FROM jobs
                        WHERE tenant_id=? AND status IN ('complete', 'done', 'failed', 'cancelled')
                        ORDER BY updated_at DESC LIMIT ?
                    )
                """,
                (str(payload["tenant_id"]), str(payload["tenant_id"]), maximum),
            )

    def load_job(self, job_id: str, principal: Principal) -> Dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (str(job_id),)).fetchone()
        if row is None:
            return None
        if not can_access_tenant(principal, str(row["tenant_id"])):
            raise PermissionError("This user cannot access that tenant job.")
        return {
            "job_id": str(row["job_id"]), "tenant_id": str(row["tenant_id"]),
            "created_by": str(row["created_by"]), "action": str(row["action"]),
            "status": str(row["status"]), "progress": json.loads(str(row["progress_json"])),
            "result": json.loads(str(row["result_json"])) if row["result_json"] else None,
            "error": str(row["error"]) if row["error"] else None,
            "cancel_requested": bool(row["cancel_requested"]),
            "created_at": float(row["created_at"]), "updated_at": float(row["updated_at"]),
        }

    def save_project(self, name: str, payload: Dict[str, Any], principal: Principal) -> None:
        tenant_id = str(dict(payload.get("meta") or {}).get("tenant_id") or principal.tenant_id)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM projects WHERE tenant_id=? AND name=?",
                (tenant_id, str(name)),
            ).fetchone()
            maximum = max(10, int(os.environ.get("PLANORA_MAX_PROJECTS_PER_TENANT", "200")))
            count = conn.execute("SELECT COUNT(*) FROM projects WHERE tenant_id=?", (tenant_id,)).fetchone()
            if existing is None and int(count[0] if count else 0) >= maximum:
                raise ValueError(f"This organization has reached its {maximum}-project limit.")
            conn.execute(
                """
                INSERT INTO projects(name, tenant_id, payload_json, created_by, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, name) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    created_by=excluded.created_by,
                    updated_at=excluded.updated_at
                """,
                (
                    str(name),
                    tenant_id,
                    json.dumps(payload, ensure_ascii=False),
                    principal.user_id,
                    time.time(),
                ),
            )

    def list_projects(self, principal: Principal) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name, tenant_id, updated_at, created_by FROM projects ORDER BY updated_at DESC"
            ).fetchall()
        return [
            {
                "name": str(row["name"]),
                "tenant_id": str(row["tenant_id"]),
                "updated_at": float(row["updated_at"]),
                "created_by": str(row["created_by"]),
            }
            for row in rows
            if can_access_tenant(principal, str(row["tenant_id"]))
        ]

    def load_project(self, name: str, principal: Principal, *, tenant_id: str = "") -> Dict[str, Any] | None:
        with self._connect() as conn:
            if principal.is_global_admin:
                if tenant_id:
                    row = conn.execute(
                        "SELECT payload_json FROM projects WHERE tenant_id=? AND name=?",
                        (str(tenant_id), str(name)),
                    ).fetchone()
                else:
                    rows = conn.execute(
                        "SELECT payload_json FROM projects WHERE name=? ORDER BY updated_at DESC LIMIT 2",
                        (str(name),),
                    ).fetchall()
                    if len(rows) > 1:
                        raise ValueError("Project name is ambiguous; specify tenant_id.")
                    row = rows[0] if rows else None
            else:
                row = conn.execute(
                    "SELECT payload_json FROM projects WHERE tenant_id=? AND name=?",
                    (principal.tenant_id, str(name)),
                ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, dict):
            raise ValueError("Persisted project payload must be an object.")
        return payload

    def delete_project(self, name: str, principal: Principal, *, tenant_id: str = "") -> bool:
        target_tenant = str(tenant_id or principal.tenant_id)
        if not principal.is_global_admin and target_tenant != principal.tenant_id:
            raise PermissionError("This user cannot delete another tenant's project.")
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM projects WHERE tenant_id=? AND name=?",
                (target_tenant, str(name)),
            )
        return bool(cursor.rowcount)

    def audit(
        self,
        principal: Principal,
        *,
        action: str,
        resource_type: str,
        resource_id: str,
        details: Dict[str, Any] | None = None,
    ) -> None:
        persistence_audit.audit(
            self,
            principal,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )

    def record_analytics_event(self, event: Dict[str, Any]) -> None:
        persistence_audit.record_analytics_event(self, event)

    def analytics_summary(
        self,
        principal: Principal,
        *,
        days: int = 30,
        tenant_id: str = "",
        event_name: str = "",
        path: str = "",
    ) -> Dict[str, Any]:
        return persistence_audit.analytics_summary(
            self,
            principal,
            days=days,
            tenant_id=tenant_id,
            event_name=event_name,
            path=path,
        )

    def list_audit(
        self,
        principal: Principal,
        *,
        limit: int = 100,
        action: str = "",
        user_id: str = "",
        tenant_id: str = "",
    ) -> List[Dict[str, Any]]:
        return persistence_audit.list_audit(
            self,
            principal,
            limit=limit,
            action=action,
            user_id=user_id,
            tenant_id=tenant_id,
        )
