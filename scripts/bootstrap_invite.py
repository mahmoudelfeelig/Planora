from __future__ import annotations

import argparse
import secrets
import sqlite3
import time
from pathlib import Path

from services.password_auth_service import hash_token


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an initial Planora group and invite code.")
    parser.add_argument("--database", required=True, help="SQLite database path.")
    parser.add_argument("--tenant", default="default", help="Tenant/university id.")
    parser.add_argument("--group", default="Initial admins", help="Planora group name.")
    parser.add_argument("--role", default="uni_admin", choices=["student", "ta", "professor", "uni_admin"])
    parser.add_argument("--code", default="", help="Optional manual invite code. Random if omitted.")
    parser.add_argument("--max-uses", type=int, default=1)
    args = parser.parse_args()

    code = args.code.strip() or f"invite_{secrets.token_urlsafe(24)}"
    now = time.time()
    group_id = secrets.token_urlsafe(12)
    invite_id = secrets.token_urlsafe(12)
    db_path = Path(args.database)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO tenants(tenant_id, display_name, enabled, created_at, updated_at) VALUES(?, ?, 1, ?, ?)",
            (args.tenant, args.tenant, now, now),
        )
        conn.execute(
            "INSERT INTO auth_groups(group_id, tenant_id, name, description, created_at) VALUES(?, ?, ?, ?, ?)",
            (group_id, args.tenant, args.group, "Bootstrap group", now),
        )
        conn.execute(
            """
            INSERT INTO invite_codes(
                invite_id, tenant_id, group_id, role, code_hash, label,
                max_uses, used_count, expires_at, disabled, created_by, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, 0, NULL, 0, 'bootstrap', ?, ?)
            """,
            (invite_id, args.tenant, group_id, args.role, hash_token(code), "Bootstrap invite", args.max_uses, now, now),
        )
    print(code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
