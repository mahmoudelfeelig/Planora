from __future__ import annotations

import secrets
import time
from typing import Any, Dict

from services.auth_service import Principal, ROLES, require_permission, require_tenant_access
from services.password_auth_service import hash_token, new_plain_token


def access_snapshot(store: Any, principal: Principal) -> Dict[str, Any]:
    require_permission(principal, "access:manage")
    tenant_filter = "" if principal.is_global_admin else " WHERE tenant_id=?"
    args: tuple[Any, ...] = () if principal.is_global_admin else (principal.tenant_id,)
    with store._connect() as conn:
        users = [dict(row) for row in conn.execute(f"SELECT * FROM users{tenant_filter} ORDER BY tenant_id, display_name", args).fetchall()]
        groups = [dict(row) for row in conn.execute(f"SELECT * FROM auth_groups{tenant_filter} ORDER BY tenant_id, name", args).fetchall()]
        memberships = [dict(row) for row in conn.execute(f"SELECT * FROM group_memberships{tenant_filter} ORDER BY tenant_id, group_id, user_id", args).fetchall()]
        account_tenants = [dict(row) for row in conn.execute(f"SELECT * FROM account_tenants{tenant_filter} ORDER BY tenant_id, user_id", args).fetchall()]
        bindings = [dict(row) for row in conn.execute(f"SELECT * FROM role_bindings{tenant_filter} ORDER BY tenant_id, principal_type, principal_id", args).fetchall()]
        invites = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT invite_id, tenant_id, group_id, role, label, max_uses, used_count,
                    expires_at, disabled, created_by, created_at, updated_at
                FROM invite_codes{tenant_filter}
                ORDER BY tenant_id, group_id, label
                """,
                args,
            ).fetchall()
        ]
    return {
        "users": users,
        "groups": groups,
        "memberships": memberships,
        "account_tenants": account_tenants,
        "role_bindings": bindings,
        "invite_codes": invites,
    }


def apply_access_change(store: Any, principal: Principal, change: Dict[str, Any]) -> Dict[str, Any]:
    require_permission(principal, "access:manage")
    tenant_id = str(change.get("tenant_id") or principal.tenant_id)
    require_tenant_access(principal, tenant_id)
    action = str(change.get("action", ""))
    now = time.time()
    with store._connect() as conn:
        def require_group(group_id: str) -> None:
            row = conn.execute(
                "SELECT 1 FROM auth_groups WHERE tenant_id=? AND group_id=?",
                (tenant_id, group_id),
            ).fetchone()
            if row is None:
                raise ValueError("The selected group does not belong to this organization.")

        def require_account(user_id: str) -> None:
            row = conn.execute(
                "SELECT 1 FROM account_tenants WHERE tenant_id=? AND user_id=?",
                (tenant_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError("The selected user does not belong to this organization.")

        if action == "create_group":
            group_id = str(change.get("group_id") or secrets.token_urlsafe(12))
            conn.execute(
                "INSERT INTO auth_groups(group_id, tenant_id, name, description, created_at) VALUES(?, ?, ?, ?, ?)",
                (group_id, tenant_id, str(change["name"]), str(change.get("description", "")), now),
            )
        elif action == "set_membership":
            group_id = str(change["group_id"])
            user_id = str(change["user_id"])
            require_group(group_id)
            require_account(user_id)
            values = (tenant_id, group_id, user_id, now)
            if bool(change.get("enabled", True)):
                conn.execute("INSERT OR IGNORE INTO group_memberships(tenant_id, group_id, user_id, created_at) VALUES(?, ?, ?, ?)", values)
            else:
                conn.execute("DELETE FROM group_memberships WHERE tenant_id=? AND group_id=? AND user_id=?", values[:3])
        elif action == "set_role":
            role = str(change["role"])
            if role not in ROLES or (role == "admin" and not principal.is_global_admin):
                raise PermissionError("That role cannot be assigned.")
            require_account(str(change["user_id"]))
            conn.execute(
                "UPDATE users SET role=?, updated_at=? WHERE tenant_id=? AND user_id=?",
                (role, now, tenant_id, str(change["user_id"])),
            )
            conn.execute(
                """
                INSERT INTO account_tenants(user_id, tenant_id, role, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(user_id, tenant_id) DO UPDATE SET role=excluded.role, updated_at=excluded.updated_at
                """,
                (str(change["user_id"]), tenant_id, role, now, now),
            )
        elif action == "set_disabled":
            require_account(str(change["user_id"]))
            conn.execute(
                "UPDATE account_tenants SET disabled=?, updated_at=? WHERE tenant_id=? AND user_id=?",
                (int(bool(change.get("disabled", True))), now, tenant_id, str(change["user_id"])),
            )
        elif action == "delete_user":
            if not principal.is_global_admin:
                raise PermissionError("Only global administrators can delete user accounts.")
            user_id = str(change["user_id"])
            if user_id == principal.user_id:
                raise PermissionError("You cannot delete your own signed-in account.")
            row = conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone()
            if row is None:
                raise ValueError("The selected user does not exist.")
            conn.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM email_verification_tokens WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM password_reset_tokens WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM group_memberships WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM role_bindings WHERE principal_type='user' AND principal_id=?", (user_id,))
            conn.execute("DELETE FROM account_tenants WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        elif action == "link_schedule_identity":
            require_account(str(change["user_id"]))
            staff_id = change.get("staff_id")
            student_group_id = change.get("student_group_id")
            conn.execute(
                """
                UPDATE account_tenants SET staff_id=?, student_group_id=?, updated_at=?
                WHERE tenant_id=? AND user_id=?
                """,
                (
                    int(staff_id) if staff_id not in (None, "") else None,
                    int(student_group_id) if student_group_id not in (None, "") else None,
                    now,
                    tenant_id,
                    str(change["user_id"]),
                ),
            )
        elif action == "bind_role":
            role = str(change["role"])
            if role not in ROLES or (role == "admin" and not principal.is_global_admin):
                raise PermissionError("That role cannot be assigned.")
            if str(change["principal_type"]) == "group":
                require_group(str(change["principal_id"]))
            else:
                require_account(str(change["principal_id"]))
            conn.execute(
                """
                INSERT OR IGNORE INTO role_bindings(
                    binding_id, tenant_id, principal_type, principal_id, role,
                    scope_type, scope_id, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    secrets.token_urlsafe(12), tenant_id, str(change["principal_type"]),
                    str(change["principal_id"]), role, str(change.get("scope_type", "tenant")),
                    str(change.get("scope_id", "*")), now,
                ),
            )
        elif action == "create_invite":
            role = str(change.get("role", "student"))
            if role not in ROLES or role == "admin" or (role == "uni_admin" and not principal.is_global_admin and principal.role != "uni_admin"):
                raise PermissionError("That invite role cannot be assigned.")
            require_group(str(change["group_id"]))
            code = str(change.get("code") or new_plain_token("invite_")).strip()
            if len(code) < 8:
                raise ValueError("Invite code must be at least 8 characters.")
            conn.execute(
                """
                INSERT INTO invite_codes(
                    invite_id, tenant_id, group_id, role, code_hash, label,
                    max_uses, used_count, expires_at, disabled, created_by, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 0, ?, 0, ?, ?, ?)
                """,
                (
                    str(change.get("invite_id") or secrets.token_urlsafe(12)),
                    tenant_id,
                    str(change["group_id"]),
                    role,
                    hash_token(code),
                    str(change.get("label") or ""),
                    int(change["max_uses"]) if change.get("max_uses") not in (None, "") else None,
                    float(change["expires_at"]) if change.get("expires_at") not in (None, "") else None,
                    principal.user_id,
                    now,
                    now,
                ),
            )
            conn.commit()
            snapshot = access_snapshot(store, principal)
            snapshot["new_invite_code"] = code
            return snapshot
        elif action == "rotate_invite":
            code = str(change.get("code") or new_plain_token("invite_")).strip()
            if len(code) < 8:
                raise ValueError("Invite code must be at least 8 characters.")
            cursor = conn.execute(
                """
                UPDATE invite_codes SET code_hash=?, label=COALESCE(?, label),
                    used_count=0, disabled=0, updated_at=?
                WHERE tenant_id=? AND invite_id=?
                """,
                (hash_token(code), change.get("label"), now, tenant_id, str(change["invite_id"])),
            )
            if not cursor.rowcount:
                raise ValueError("Invite code was not found.")
            conn.commit()
            snapshot = access_snapshot(store, principal)
            snapshot["new_invite_code"] = code
            return snapshot
        elif action == "set_invite_disabled":
            cursor = conn.execute(
                "UPDATE invite_codes SET disabled=?, updated_at=? WHERE tenant_id=? AND invite_id=?",
                (int(bool(change.get("disabled", True))), now, tenant_id, str(change["invite_id"])),
            )
            if not cursor.rowcount:
                raise ValueError("Invite code was not found.")
        else:
            raise ValueError(f"Unknown access change action: {action}")
    return access_snapshot(store, principal)
