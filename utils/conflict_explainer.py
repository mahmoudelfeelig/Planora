from __future__ import annotations

from typing import Any, Dict, Iterable, List


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
    if "wrong specialized lab" in text:
        suggestions.append("Select a specialized lab with the required tag.")
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
