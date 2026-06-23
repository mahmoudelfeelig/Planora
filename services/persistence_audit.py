from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterable, List

from services.auth_service import Principal, require_permission


def audit(
    store: Any,
    principal: Principal,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    details: Dict[str, Any] | None = None,
) -> None:
    with store._connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_events(
                tenant_id, user_id, role, action, resource_type, resource_id,
                details_json, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                principal.tenant_id,
                principal.user_id,
                principal.role,
                str(action),
                str(resource_type),
                str(resource_id),
                json.dumps(dict(details or {}), ensure_ascii=False),
                time.time(),
            ),
        )


def record_analytics_event(store: Any, event: Dict[str, Any]) -> None:
    name = str(event.get("event_name") or "").strip()[:80]
    path = str(event.get("path") or "/").strip()[:500]
    client_id_hash = str(event.get("client_id_hash") or "").strip()[:128]
    if not name or not client_id_hash:
        raise ValueError("Analytics event requires event_name and client_id_hash.")
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    details_json = json.dumps(details, ensure_ascii=False)
    if len(details_json.encode("utf-8")) > 8192:
        raise ValueError("Analytics event details exceed the 8192-byte limit.")
    with store._connect() as conn:
        conn.execute(
            """
            INSERT INTO analytics_events(
                client_id_hash, tenant_id, user_role, event_name, path, view_name,
                referrer, viewport_width, viewport_height, details_json,
                user_agent, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id_hash,
                str(event.get("tenant_id") or "public")[:120],
                str(event.get("user_role") or "anonymous")[:60],
                name,
                path,
                str(event.get("view_name") or "")[:120],
                str(event.get("referrer") or "")[:500],
                int(event["viewport_width"]) if event.get("viewport_width") not in (None, "") else None,
                int(event["viewport_height"]) if event.get("viewport_height") not in (None, "") else None,
                details_json,
                str(event.get("user_agent") or "")[:500],
                time.time(),
            ),
        )


def analytics_summary(
    store: Any,
    principal: Principal,
    *,
    days: int = 30,
    tenant_id: str = "",
    event_name: str = "",
    path: str = "",
) -> Dict[str, Any]:
    require_permission(principal, "audit:read")
    cutoff = time.time() - max(1, int(days)) * 86400
    filters = ["created_at>=?"]
    args_list: list[Any] = [cutoff]
    requested_tenant = str(tenant_id or "").strip()
    if principal.is_global_admin and requested_tenant:
        filters.append("tenant_id=?")
        args_list.append(requested_tenant)
    elif not principal.is_global_admin:
        filters.append("tenant_id=?")
        args_list.append(principal.tenant_id)
    if event_name:
        filters.append("event_name=?")
        args_list.append(str(event_name))
    if path:
        filters.append("path LIKE ?")
        args_list.append(f"%{path}%")
    where = " AND ".join(filters)
    args: tuple[Any, ...] = tuple(args_list)
    with store._connect() as conn:
        totals = conn.execute(
            f"""
            SELECT COUNT(*) AS events, COUNT(DISTINCT client_id_hash) AS visitors
            FROM analytics_events
            WHERE {where}
            """,
            args,
        ).fetchone()
        top_paths = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT path, COUNT(*) AS events, COUNT(DISTINCT client_id_hash) AS visitors
                FROM analytics_events
                WHERE {where}
                GROUP BY path
                ORDER BY events DESC, path
                LIMIT 10
                """,
                args,
            ).fetchall()
        ]
        top_events = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT event_name, COUNT(*) AS events
                FROM analytics_events
                WHERE {where}
                GROUP BY event_name
                ORDER BY events DESC, event_name
                LIMIT 10
                """,
                args,
            ).fetchall()
        ]
        by_day = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT date(created_at, 'unixepoch') AS day, COUNT(*) AS events,
                    COUNT(DISTINCT client_id_hash) AS visitors
                FROM analytics_events
                WHERE {where}
                GROUP BY day
                ORDER BY day
                """,
                args,
            ).fetchall()
        ]
    return {
        "days": int(days),
        "events": int(totals["events"] or 0) if totals is not None else 0,
        "visitors": int(totals["visitors"] or 0) if totals is not None else 0,
        "top_paths": top_paths,
        "top_events": top_events,
        "by_day": by_day,
    }


def list_audit(
    store: Any,
    principal: Principal,
    *,
    limit: int = 100,
    action: str = "",
    user_id: str = "",
    tenant_id: str = "",
) -> List[Dict[str, Any]]:
    filters: list[str] = []
    args_list: list[Any] = []
    if principal.is_global_admin:
        requested_tenant = str(tenant_id or "").strip()
        if requested_tenant:
            filters.append("tenant_id=?")
            args_list.append(requested_tenant)
    else:
        filters.append("tenant_id=?")
        args_list.append(principal.tenant_id)
    if action:
        filters.append("action LIKE ?")
        args_list.append(f"%{action}%")
    if user_id:
        filters.append("user_id LIKE ?")
        args_list.append(f"%{user_id}%")
    where = f" WHERE {' AND '.join(filters)}" if filters else ""
    sql = f"SELECT * FROM audit_events{where} ORDER BY id DESC LIMIT ?"
    args: Iterable[Any] = (*args_list, int(limit))
    with store._connect() as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()
    return [
        {
            "id": int(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "user_id": str(row["user_id"]),
            "role": str(row["role"]),
            "action": str(row["action"]),
            "resource_type": str(row["resource_type"]),
            "resource_id": str(row["resource_id"]),
            "details": json.loads(str(row["details_json"])),
            "created_at": float(row["created_at"]),
        }
        for row in rows
    ]
