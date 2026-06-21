from __future__ import annotations

import argparse
from pathlib import Path

from services.persistence_service import PersistenceStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap a registered Planora user into an administrator role.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--user", required=True, help="Planora user ID, for example email:admin@example.edu")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--role", choices=["uni_admin", "admin"], default="uni_admin")
    args = parser.parse_args()
    PersistenceStore(args.database).bootstrap_user_role(user_id=args.user, tenant_id=args.tenant, role=args.role)
    print(f"Assigned {args.role} to {args.user} in {args.tenant}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
