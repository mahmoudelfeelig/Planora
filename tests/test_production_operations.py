from __future__ import annotations

import sqlite3

from scripts.backup_planora import backup_database, restore_database, verify_database


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
