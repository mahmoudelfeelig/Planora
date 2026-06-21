from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ApprovalRecord:
    action: str
    actor: str
    reason: str
    approved_at_utc: str
    details: Dict[str, Any]


def build_approval_record(
    *,
    action: str,
    actor: str,
    reason: str,
    details: Dict[str, Any] | None = None,
) -> ApprovalRecord:
    clean_actor = str(actor or "").strip()
    clean_reason = str(reason or "").strip()
    if not clean_actor:
        raise ValueError("Approval actor is required.")
    if not clean_reason:
        raise ValueError("Approval reason is required.")
    return ApprovalRecord(
        action=str(action),
        actor=clean_actor,
        reason=clean_reason,
        approved_at_utc=_utc_now(),
        details=dict(details or {}),
    )


def approval_to_dict(record: ApprovalRecord) -> Dict[str, Any]:
    return asdict(record)
