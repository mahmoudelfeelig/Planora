from __future__ import annotations

from typing import Any, Dict, Iterable, List


def build_room_certificate_explanation(certificate: Any) -> str:
    data = certificate.to_dict() if hasattr(certificate, "to_dict") else dict(certificate or {})
    activity_ids = [int(value) for value in data.get("activity_ids", [])]
    room_ids = [int(value) for value in data.get("candidate_room_ids", [])]
    certificate_type = str(data.get("certificate_type", "room_model_nogood"))
    message = str(data.get("message", "The fixed-time room assignment is infeasible."))
    lines = ["Exact room-assignment certificate", message]
    if activity_ids:
        lines.append("Affected activities: " + ", ".join(f"A{value}" for value in activity_ids))
    if room_ids:
        lines.append("Eligible room neighborhood: " + ", ".join(f"R{value}" for value in room_ids))
    if certificate_type == "hall_deficiency":
        lines.append(
            "Why it is impossible: more simultaneous room jobs require this room neighborhood "
            "than the neighborhood can hold."
        )
        lines.append("Repair: move at least one affected activity outside the certified slot.")
    elif certificate_type == "empty_domain":
        lines.append("Repair: change the time, capacity requirement, room availability, or room lock.")
    else:
        lines.append("Repair: reopen the affected time assignments and any linked travel, repeat, or room locks.")
    return "\n".join(lines)


def _base_suggestions_for_reason(reason: str) -> List[str]:
    text = str(reason or "").lower()
    suggestions: List[str] = []
    if "week 1 allows lectures only" in text:
        suggestions.append("Move this activity to week >= 2 or change it to a lecture.")
    if "staff unavailable on that day" in text:
        suggestions.append("Try a different day or assign another qualified staff member.")
    if "staff unavailable in that week" in text:
        suggestions.append("Try another week or replace staff for this activity.")
    if "daily load limit" in text or "weekly load limit" in text:
        suggestions.append("Move this activity to a lighter day/week for the selected staff.")
    if "room capacity too small" in text:
        suggestions.append("Select a larger room category/capacity.")
    if "room unavailable" in text:
        suggestions.append("Try another slot or another room with matching availability.")
    if "wrong specialized lab" in text or "requires lab tag" in text:
        suggestions.append("Select a specialized lab with the required tag.")
    if "invalid room" in text or "lab in invalid room" in text:
        suggestions.append("Choose a room that satisfies the activity type, capacity, and specialization requirements.")
    if "lecture must use a lecture room" in text:
        suggestions.append("Choose a room of type LECTURE.")
    if "tutorial must use a lecture/tutorial room" in text:
        suggestions.append("Choose a room of type TUTORIAL or LECTURE.")
    if "lab must be in a lab room" in text:
        suggestions.append("Choose COMPUTER_LAB or SPECIALIZED_LAB.")
    if "staff conflict" in text or "group conflict" in text or "room conflict" in text:
        suggestions.append("Use Swap/Relocate in the conflict resolver, or choose another free slot.")
    return suggestions


def build_move_explanation_text(
    *,
    activity_id: int,
    target_week: int,
    target_day: str,
    target_slot: int,
    valid: bool,
    reason: str,
    conflicts: Iterable[Dict[str, Any]] | None = None,
) -> str:
    lines: List[str] = [
        f"Move target: A{int(activity_id)} -> W{int(target_week)} {str(target_day)} S{int(target_slot) + 1}"
    ]
    if bool(valid):
        lines.append("Result: valid (no hard-constraint blockers).")
        return "\n".join(lines)

    reason_text = str(reason or "Constraint violation")
    lines.append(f"Result: blocked ({reason_text})")
    suggestions = _base_suggestions_for_reason(reason_text)

    conflict_rows = list(conflicts or [])
    if conflict_rows:
        lines.append("")
        lines.append("Direct slot conflicts:")
        for row in conflict_rows[:10]:
            b_id = int(row.get("activity_id", -1))
            reason_list = [str(r) for r in (row.get("reasons") or []) if str(r).strip()]
            if reason_list:
                lines.append(f"- A{b_id}: {', '.join(reason_list)}")
            else:
                lines.append(f"- A{b_id}")
        if len(conflict_rows) > 10:
            lines.append(f"- ... +{len(conflict_rows) - 10} more")
        if any("group" in str(r).lower() for row in conflict_rows for r in (row.get("reasons") or [])):
            suggestions.append("Try a slot where the affected group has no overlapping activity.")
        if any("staff" in str(r).lower() for row in conflict_rows for r in (row.get("reasons") or [])):
            suggestions.append("Try another slot for this staff member or reassign staff.")
        if any("room" in str(r).lower() for row in conflict_rows for r in (row.get("reasons") or [])):
            suggestions.append("Try another room at this slot or move to a room-free slot.")

    deduped: List[str] = []
    seen = set()
    for s in suggestions:
        key = str(s).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(str(s))

    if deduped:
        lines.append("")
        lines.append("Suggested fixes:")
        for s in deduped[:8]:
            lines.append(f"- {s}")

    return "\n".join(lines)
