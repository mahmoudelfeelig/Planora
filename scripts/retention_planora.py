from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path


RETENTION_TABLES: tuple[tuple[str, str, str], ...] = (
    ("audit_events", "created_at", "audit events"),
    ("analytics_events", "created_at", "analytics events"),
    ("projects", "updated_at", "old projects"),
)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _count_where(conn: sqlite3.Connection, table: str, predicate: str, args: tuple[object, ...]) -> int:
    row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {predicate}", args).fetchone()
    return int(row[0] if row is not None else 0)


def cleanup_database(database: Path, *, keep_days: int = 183, dry_run: bool = False) -> dict[str, int]:
    if keep_days < 1:
        raise ValueError("keep_days must be positive.")
    cutoff = time.time() - (int(keep_days) * 86400)
    deleted: dict[str, int] = {}
    with sqlite3.connect(database) as conn:
        for table, column, label in RETENTION_TABLES:
            if not _table_exists(conn, table):
                deleted[label] = 0
                continue
            count = _count_where(conn, table, f"{column} < ?", (cutoff,))
            deleted[label] = count
            if count and not dry_run:
                conn.execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))

        if _table_exists(conn, "jobs"):
            predicate = "updated_at < ? AND status IN ('done', 'failed', 'cancelled')"
            count = _count_where(conn, "jobs", predicate, (cutoff,))
            deleted["finished jobs"] = count
            if count and not dry_run:
                conn.execute(f"DELETE FROM jobs WHERE {predicate}", (cutoff,))

        for table in ("email_verification_tokens", "password_reset_tokens"):
            if not _table_exists(conn, table):
                deleted[table.replace("_", " ")] = 0
                continue
            count = _count_where(conn, table, "expires_at < ?", (time.time(),))
            deleted[table.replace("_", " ")] = count
            if count and not dry_run:
                conn.execute(f"DELETE FROM {table} WHERE expires_at < ?", (time.time(),))

        if _table_exists(conn, "auth_sessions"):
            predicate = "expires_at < ? OR revoked_at IS NOT NULL"
            count = _count_where(conn, "auth_sessions", predicate, (time.time(),))
            deleted["expired auth sessions"] = count
            if count and not dry_run:
                conn.execute(f"DELETE FROM auth_sessions WHERE {predicate}", (time.time(),))

        if not dry_run:
            conn.commit()
            conn.execute("PRAGMA optimize")
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply Planora database retention cleanup.")
    parser.add_argument("--database", type=Path, default=Path("/app/data/planora.sqlite3"))
    parser.add_argument("--keep-days", type=int, default=183)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--watch-seconds", type=int, default=0)
    args = parser.parse_args()

    while True:
        result = cleanup_database(args.database, keep_days=args.keep_days, dry_run=args.dry_run)
        print(result, flush=True)
        if args.watch_seconds <= 0:
            return 0
        time.sleep(args.watch_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
