from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Dict

from services.persistence_config import SCHEMA_VERSION


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row is None:
        return 0
    return int(row["value"])


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(str(row["name"]) == column for row in conn.execute(f"PRAGMA table_info({table})").fetchall())


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            created_by TEXT NOT NULL,
            role TEXT NOT NULL,
            instance_json TEXT NOT NULL,
            schedule_json TEXT NOT NULL,
            meta_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            name TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_by TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (tenant_id, name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            role TEXT NOT NULL,
            display_name TEXT,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS migrations (
            version INTEGER PRIMARY KEY,
            applied_at REAL NOT NULL
        )
        """
    )
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_groups (
            group_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            UNIQUE (tenant_id, name)
        );
        CREATE TABLE IF NOT EXISTS group_memberships (
            tenant_id TEXT NOT NULL,
            group_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (group_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS account_tenants (
            user_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            role TEXT NOT NULL,
            disabled INTEGER NOT NULL DEFAULT 0,
            staff_id INTEGER,
            student_group_id INTEGER,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (user_id, tenant_id)
        );
        CREATE TABLE IF NOT EXISTS role_bindings (
            binding_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            principal_type TEXT NOT NULL CHECK(principal_type IN ('user', 'group')),
            principal_id TEXT NOT NULL,
            role TEXT NOT NULL,
            scope_type TEXT NOT NULL DEFAULT 'tenant',
            scope_id TEXT NOT NULL DEFAULT '*',
            created_at REAL NOT NULL,
            UNIQUE (tenant_id, principal_type, principal_id, role, scope_type, scope_id)
        );
        CREATE TABLE IF NOT EXISTS auth_sessions (
            session_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            csrf_token TEXT NOT NULL,
            expires_at REAL NOT NULL,
            revoked_at REAL,
            created_at REAL NOT NULL,
            last_seen_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS invite_codes (
            invite_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            group_id TEXT NOT NULL,
            role TEXT NOT NULL,
            code_hash TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL DEFAULT '',
            max_uses INTEGER,
            used_count INTEGER NOT NULL DEFAULT 0,
            expires_at REAL,
            disabled INTEGER NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            expires_at REAL NOT NULL,
            consumed_at REAL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            expires_at REAL NOT NULL,
            consumed_at REAL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            created_by TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            progress_json TEXT NOT NULL,
            result_json TEXT,
            error TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analytics_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id_hash TEXT NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'public',
            user_role TEXT NOT NULL DEFAULT 'anonymous',
            event_name TEXT NOT NULL,
            path TEXT NOT NULL,
            view_name TEXT NOT NULL DEFAULT '',
            referrer TEXT NOT NULL DEFAULT '',
            viewport_width INTEGER,
            viewport_height INTEGER,
            details_json TEXT NOT NULL DEFAULT '{}',
            user_agent TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_groups_tenant ON auth_groups(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_memberships_user ON group_memberships(tenant_id, user_id);
        CREATE INDEX IF NOT EXISTS idx_account_tenants_user ON account_tenants(user_id, tenant_id);
        CREATE INDEX IF NOT EXISTS idx_bindings_principal ON role_bindings(tenant_id, principal_type, principal_id);
        CREATE INDEX IF NOT EXISTS idx_audit_tenant_created ON audit_events(tenant_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_jobs_tenant_updated ON jobs(tenant_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_analytics_created ON analytics_events(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_analytics_tenant_created ON analytics_events(tenant_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_invites_tenant ON invite_codes(tenant_id, group_id);
        CREATE INDEX IF NOT EXISTS idx_verification_user ON email_verification_tokens(user_id, tenant_id);
        CREATE INDEX IF NOT EXISTS idx_password_reset_user ON password_reset_tokens(user_id, tenant_id);
        """
    )
    conn.execute(
        "UPDATE jobs SET status='failed', error='API restarted while job was active', updated_at=? WHERE status IN ('queued', 'running')",
        (time.time(),),
    )
    migrate(conn)


def migrate(conn: sqlite3.Connection) -> None:
    current = schema_version(conn)
    if current < 2 and not has_column(conn, "users", "display_name"):
        conn.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
    user_columns = {
        "provider": "TEXT NOT NULL DEFAULT 'local'",
        "email": "TEXT",
        "disabled": "INTEGER NOT NULL DEFAULT 0",
        "staff_id": "INTEGER",
        "student_group_id": "INTEGER",
        "password_hash": "TEXT",
        "email_verified_at": "REAL",
    }
    for column, definition in user_columns.items():
        if not has_column(conn, "users", column):
            conn.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_tenants (
            user_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            role TEXT NOT NULL,
            disabled INTEGER NOT NULL DEFAULT 0,
            staff_id INTEGER,
            student_group_id INTEGER,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (user_id, tenant_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_account_tenants_user ON account_tenants(user_id, tenant_id)")
    account_columns = {
        "disabled": "INTEGER NOT NULL DEFAULT 0",
        "staff_id": "INTEGER",
        "student_group_id": "INTEGER",
    }
    for column, definition in account_columns.items():
        if not has_column(conn, "account_tenants", column):
            conn.execute(f"ALTER TABLE account_tenants ADD COLUMN {column} {definition}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id_hash TEXT NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'public',
            user_role TEXT NOT NULL DEFAULT 'anonymous',
            event_name TEXT NOT NULL,
            path TEXT NOT NULL,
            view_name TEXT NOT NULL DEFAULT '',
            referrer TEXT NOT NULL DEFAULT '',
            viewport_width INTEGER,
            viewport_height INTEGER,
            details_json TEXT NOT NULL DEFAULT '{}',
            user_agent TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_created ON analytics_events(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_tenant_created ON analytics_events(tenant_id, created_at DESC)")
    now = time.time()
    conn.execute(
        """
        INSERT OR IGNORE INTO account_tenants(user_id, tenant_id, role, created_at, updated_at)
        SELECT user_id, tenant_id, role, ?, ? FROM users
        """,
        (now, now),
    )
    for version in range(current + 1, SCHEMA_VERSION + 1):
        conn.execute(
            "INSERT OR IGNORE INTO migrations(version, applied_at) VALUES(?, ?)",
            (int(version), time.time()),
        )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )


def schema_info(conn: sqlite3.Connection, path: Path) -> Dict[str, Any]:
    version = schema_version(conn)
    migrations = [
        {"version": int(row["version"]), "applied_at": float(row["applied_at"])}
        for row in conn.execute("SELECT version, applied_at FROM migrations ORDER BY version").fetchall()
    ]
    return {
        "path": str(path),
        "schema_version": int(version),
        "latest_version": SCHEMA_VERSION,
        "migrations": migrations,
    }
