from __future__ import annotations

import argparse
import sqlite3
import time
from contextlib import closing
from pathlib import Path


def backup_database(source: Path, destination_dir: Path, *, keep: int = 28, keep_days: int = 0) -> Path:
    if not source.exists():
        raise FileNotFoundError(source)
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    destination = destination_dir / f"planora-{timestamp}.sqlite3"
    source_uri = f"file:{source.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as source_db, closing(sqlite3.connect(str(destination))) as backup_db:
        source_db.backup(backup_db)
        backup_db.commit()
    verify_database(destination)
    backups = sorted(destination_dir.glob("planora-*.sqlite3"), key=lambda path: path.stat().st_mtime, reverse=True)
    if keep_days > 0:
        cutoff = time.time() - (int(keep_days) * 86400)
        for old in backups:
            if old == destination:
                continue
            if old.stat().st_mtime < cutoff:
                old.unlink()
        backups = sorted(destination_dir.glob("planora-*.sqlite3"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in backups[max(1, int(keep)):]:
        old.unlink()
    return destination


def verify_database(path: Path) -> None:
    with closing(sqlite3.connect(str(path))) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()
    if result is None or str(result[0]).lower() != "ok":
        raise RuntimeError(f"Database integrity check failed for {path}: {result}")


def restore_database(backup: Path, destination: Path) -> None:
    verify_database(backup)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".restore")
    with closing(sqlite3.connect(str(backup))) as source_db, closing(sqlite3.connect(str(temporary))) as destination_db:
        source_db.backup(destination_db)
        destination_db.commit()
    verify_database(temporary)
    temporary.replace(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up or restore the Planora SQLite database safely.")
    parser.add_argument("--source", type=Path, default=Path("/app/data/planora.sqlite3"))
    parser.add_argument("--destination-dir", type=Path, default=Path("/backups"))
    parser.add_argument("--keep", type=int, default=28)
    parser.add_argument("--keep-days", type=int, default=0)
    parser.add_argument("--restore", type=Path)
    parser.add_argument("--watch-seconds", type=int, default=0)
    args = parser.parse_args()
    if args.restore:
        restore_database(args.restore, args.source)
        return 0
    while True:
        print(backup_database(args.source, args.destination_dir, keep=args.keep, keep_days=args.keep_days), flush=True)
        if args.watch_seconds <= 0:
            return 0
        time.sleep(args.watch_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
