from __future__ import annotations

import io
import os
import sqlite3
import time

from api.server import _auth_json_response
from scripts.backup_planora import backup_database, restore_database, verify_database
from scripts.retention_planora import cleanup_database


def test_database_backup_retention_and_restore(tmp_path):
    source = tmp_path / "planora.sqlite3"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE marker(value TEXT NOT NULL)")
        conn.execute("INSERT INTO marker(value) VALUES('ready')")
    backup = backup_database(source, tmp_path / "backups", keep=2)
    verify_database(backup)
    restored = tmp_path / "restored.sqlite3"
    restore_database(backup, restored)
    with sqlite3.connect(restored) as conn:
        assert conn.execute("SELECT value FROM marker").fetchone()[0] == "ready"


def test_backup_retention_can_prune_by_age(tmp_path):
    source = tmp_path / "planora.sqlite3"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE marker(value TEXT NOT NULL)")
        conn.execute("INSERT INTO marker(value) VALUES('ready')")
    backup_dir = tmp_path / "backups"
    old_backup = backup_dir / "planora-20000101T000000Z.sqlite3"
    backup_dir.mkdir()
    old_backup.write_bytes(source.read_bytes())
    old_time = time.time() - 10 * 86400
    os.utime(old_backup, (old_time, old_time))

    backup_database(source, backup_dir, keep=10, keep_days=1)

    assert not old_backup.exists()
    assert len(list(backup_dir.glob("planora-*.sqlite3"))) == 1


def test_database_retention_cleanup_prunes_policy_tables(tmp_path):
    database = tmp_path / "planora.sqlite3"
    old = time.time() - 200 * 86400
    recent = time.time()
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE audit_events(id INTEGER PRIMARY KEY, created_at REAL NOT NULL)")
        conn.execute("CREATE TABLE analytics_events(id INTEGER PRIMARY KEY, created_at REAL NOT NULL)")
        conn.execute("CREATE TABLE projects(name TEXT PRIMARY KEY, updated_at REAL NOT NULL)")
        conn.execute("CREATE TABLE jobs(job_id TEXT PRIMARY KEY, status TEXT NOT NULL, updated_at REAL NOT NULL)")
        conn.execute("CREATE TABLE auth_sessions(session_id TEXT PRIMARY KEY, expires_at REAL NOT NULL, revoked_at REAL)")
        conn.execute("INSERT INTO audit_events(created_at) VALUES(?), (?)", (old, recent))
        conn.execute("INSERT INTO analytics_events(created_at) VALUES(?), (?)", (old, recent))
        conn.execute("INSERT INTO projects(name, updated_at) VALUES('old', ?), ('new', ?)", (old, recent))
        conn.execute("INSERT INTO jobs(job_id, status, updated_at) VALUES('old-done', 'done', ?), ('old-running', 'running', ?)", (old, old))
        conn.execute("INSERT INTO auth_sessions(session_id, expires_at, revoked_at) VALUES('expired', ?, NULL), ('active', ?, NULL)", (old, recent + 3600))

    dry_run = cleanup_database(database, keep_days=183, dry_run=True)
    assert dry_run["audit events"] == 1

    deleted = cleanup_database(database, keep_days=183)
    assert deleted["old projects"] == 1
    assert deleted["finished jobs"] == 1
    assert deleted["expired auth sessions"] == 1
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM analytics_events").fetchone()[0] == 1
        assert conn.execute("SELECT name FROM projects").fetchone()[0] == "new"
        assert conn.execute("SELECT job_id FROM jobs").fetchone()[0] == "old-running"
        assert conn.execute("SELECT session_id FROM auth_sessions").fetchone()[0] == "active"


class _FakeHandler:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.sent_headers: list[tuple[str, str]] = []
        self.wfile = io.BytesIO()

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, name: str, value: str) -> None:
        self.sent_headers.append((name, value))

    def end_headers(self) -> None:
        pass


def test_production_auth_cookies_are_secure(monkeypatch):
    monkeypatch.setenv("PLANORA_PRODUCTION", "1")
    handler = _FakeHandler()

    _auth_json_response(handler, 200, {"ok": True}, token="session-token", csrf_token="csrf-token", max_age=60)

    cookies = [value for name, value in handler.sent_headers if name.lower() == "set-cookie"]
    assert len(cookies) == 2
    assert all("Secure" in cookie for cookie in cookies)
    assert all("SameSite=Lax" in cookie for cookie in cookies)
    assert any("HttpOnly" in cookie and cookie.startswith("planora_session=") for cookie in cookies)
