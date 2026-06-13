from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from services.quality_service import compute_penalty_breakdown, evaluate_schedule_sla, rank_penalty_drivers
from utils.compare import compare_schedules
from utils.domain import Instance
from utils.fairness import compute_fairness_dashboard
from utils.feasibility import explain_infeasibility
from utils.specs import validate_schedule_against_instance


def _reason_rule(reason: str) -> str:
    text = str(reason or "").lower()
    if "week 1" in text and "lecture" in text:
        return "week1_lectures_only"
    if "duration exceeds day" in text or "invalid slot range" in text:
        return "slot_range"
    if "non-prof" in text or "professor" in text:
        return "staff_role_match"
    if "cannot teach course" in text:
        return "staff_course_eligibility"
    if "unavailable" in text and "staff" in text:
        return "staff_availability"
    if "capacity" in text:
        return "room_capacity"
    if "lab tag" in text or "specialized" in text:
        return "room_specialization"
    if "blocked calendar" in text or "holiday" in text or "blackout" in text:
        return "calendar_blackout"
    if "travel buffer" in text:
        return "travel_buffer"
    if "precedence" in text:
        return "precedence"
    if "overlap" in text:
        return "resource_overlap"
    return "general_feasibility"


def build_unsat_rule_diagnosis(
    inst: Instance,
    schedule: Dict[int, Dict[str, Any]] | None = None,
    *,
    strict_rooms: bool = True,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    reasons = (
        validate_schedule_against_instance(inst, schedule, strict_rooms=strict_rooms)
        if isinstance(schedule, dict) and schedule
        else explain_infeasibility(inst)
    )
    grouped: Dict[str, List[str]] = {}
    for reason in reasons:
        rule_id = _reason_rule(str(reason))
        grouped.setdefault(rule_id, []).append(str(reason))
    rows: List[Dict[str, Any]] = []
    for rule_id, evidence in grouped.items():
        rows.append(
            {
                "rule_id": str(rule_id),
                "severity": int(len(evidence)),
                "summary": str(evidence[0]),
                "evidence": list(evidence[:4]),
            }
        )
    rows.sort(key=lambda row: (-int(row["severity"]), str(row["rule_id"])))
    return rows[: max(1, int(limit))]


def explain_candidate_slot(
    inst: Instance,
    schedule: Dict[int, Dict[str, Any]],
    *,
    activity_id: int,
    week: int,
    day: str,
    slot: int,
    room_id: int | None = None,
    staff_id: int | None = None,
    strict_rooms: bool = True,
) -> Dict[str, Any]:
    a_id = int(activity_id)
    if a_id not in schedule:
        raise KeyError(f"Activity A{a_id} not present in schedule.")
    candidate = {int(k): dict(v) for k, v in schedule.items()}
    info = dict(candidate[a_id])
    info["week"] = int(week)
    info["day"] = str(day)
    info["slot"] = int(slot)
    if room_id is not None:
        info["room_id"] = int(room_id)
    if staff_id is not None:
        info["staff_id"] = int(staff_id)
    candidate[a_id] = info

    errors = validate_schedule_against_instance(
        inst,
        candidate,
        strict_rooms=bool(strict_rooms),
    )
    relevant = [
        str(err)
        for err in errors
        if f"A{a_id}" in str(err)
        or "overlap" in str(err).lower()
        or "travel buffer" in str(err).lower()
        or "precedence" in str(err).lower()
    ]
    base_penalty = int(compute_penalty_breakdown(inst, schedule).get("total", 0))
    candidate_penalty = int(compute_penalty_breakdown(inst, candidate).get("total", 0))
    return {
        "activity_id": int(a_id),
        "candidate": dict(info),
        "valid": not bool(errors),
        "reasons": relevant or [str(err) for err in errors[:8]],
        "soft_penalty_delta": int(candidate_penalty - base_penalty),
    }


def compute_entity_heatmaps(inst: Instance, schedule: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    days = [str(d) for d in inst.days]
    day_index = {str(day): idx for idx, day in enumerate(days)}
    slots = int(inst.slots_per_day)
    weeks = [int(w) for w in inst.weeks]

    def _blank() -> List[List[int]]:
        return [[0 for _ in range(slots)] for _ in days]

    group_heatmaps: Dict[int, Dict[str, Any]] = {}
    for g_id, group in inst.groups.items():
        load = _blank()
        gaps = _blank()
        instability = _blank()
        week_presence: Dict[tuple[int, str, int], int] = {}
        for w in weeks:
            for day in days:
                occupied_slots: List[int] = []
                for info in schedule.values():
                    if int(info.get("week", -1)) != int(w) or str(info.get("day", "")) != str(day):
                        continue
                    if int(g_id) not in {int(x) for x in info.get("group_ids", [])}:
                        continue
                    start = int(info.get("slot", 0))
                    dur = int(info.get("duration", 1))
                    for off in range(max(1, dur)):
                        current_slot = start + off
                        if 0 <= current_slot < slots:
                            load[day_index[day]][current_slot] += 1
                            occupied_slots.append(current_slot)
                            week_presence[(w, day, current_slot)] = 1
                if occupied_slots:
                    lo = min(occupied_slots)
                    hi = max(occupied_slots)
                    for candidate_slot in range(lo, hi + 1):
                        if candidate_slot not in occupied_slots:
                            gaps[day_index[day]][candidate_slot] += 1
        for day in days:
            for slot_id in range(slots):
                flips = 0
                prev = 0
                for w in weeks:
                    cur = int(week_presence.get((w, day, slot_id), 0))
                    if w != weeks[0] and cur != prev:
                        flips += 1
                    prev = cur
                instability[day_index[day]][slot_id] = flips
        group_heatmaps[int(g_id)] = {
            "entity_label": str(group.name),
            "load": load,
            "gaps": gaps,
            "instability": instability,
        }

    staff_heatmaps: Dict[int, Dict[str, Any]] = {}
    for s_id, staff in inst.staff.items():
        load = _blank()
        gaps = _blank()
        instability = _blank()
        week_presence: Dict[tuple[int, str, int], int] = {}
        for w in weeks:
            for day in days:
                occupied_slots: List[int] = []
                for info in schedule.values():
                    if int(info.get("week", -1)) != int(w) or str(info.get("day", "")) != str(day):
                        continue
                    if int(info.get("staff_id", -1)) != int(s_id):
                        continue
                    start = int(info.get("slot", 0))
                    dur = int(info.get("duration", 1))
                    for off in range(max(1, dur)):
                        current_slot = start + off
                        if 0 <= current_slot < slots:
                            load[day_index[day]][current_slot] += 1
                            occupied_slots.append(current_slot)
                            week_presence[(w, day, current_slot)] = 1
                if occupied_slots:
                    lo = min(occupied_slots)
                    hi = max(occupied_slots)
                    for candidate_slot in range(lo, hi + 1):
                        if candidate_slot not in occupied_slots:
                            gaps[day_index[day]][candidate_slot] += 1
        for day in days:
            for slot_id in range(slots):
                flips = 0
                prev = 0
                for w in weeks:
                    cur = int(week_presence.get((w, day, slot_id), 0))
                    if w != weeks[0] and cur != prev:
                        flips += 1
                    prev = cur
                instability[day_index[day]][slot_id] = flips
        staff_heatmaps[int(s_id)] = {
            "entity_label": str(staff.name),
            "load": load,
            "gaps": gaps,
            "instability": instability,
        }

    return {
        "days": days,
        "slots_per_day": slots,
        "groups": group_heatmaps,
        "staff": staff_heatmaps,
    }


def build_stakeholder_quality_report(
    inst: Instance,
    schedule: Dict[int, Dict[str, Any]],
    *,
    branding: Dict[str, Any] | None = None,
    baseline_schedule: Dict[int, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    hard_conflicts = validate_schedule_against_instance(inst, schedule, strict_rooms=True)
    breakdown = compute_penalty_breakdown(inst, schedule)
    fairness = compute_fairness_dashboard(inst, schedule)
    sla = evaluate_schedule_sla(inst, schedule, hard_conflicts=len(hard_conflicts))
    report: Dict[str, Any] = {
        "branding": dict(branding or {}),
        "summary": {
            "activities": int(len(schedule)),
            "groups": int(len(inst.groups)),
            "staff": int(len(inst.staff)),
            "rooms": int(len(inst.rooms)),
            "hard_conflicts": int(len(hard_conflicts)),
            "soft_penalty": int(breakdown.get("total", 0)),
        },
        "soft_penalty_breakdown": dict(breakdown),
        "top_penalty_drivers": rank_penalty_drivers(inst, schedule),
        "sla": dict(sla),
        "fairness": dict(fairness.get("summary", {})),
        "top_group_risks": list(fairness.get("groups", [])[:5]),
        "top_staff_risks": list(fairness.get("staff", [])[:5]),
        "unsat_diagnosis": build_unsat_rule_diagnosis(inst, schedule if hard_conflicts else None),
        "hard_conflict_samples": list(hard_conflicts[:10]),
    }
    if baseline_schedule:
        report["comparison_to_baseline"] = compare_schedules(baseline_schedule, schedule)
    return report


def write_stakeholder_quality_report(
    out_dir: str | Path,
    report: Dict[str, Any],
) -> Dict[str, str]:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "quality_report.json"
    md_path = target / "quality_report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    summary = dict(report.get("summary", {}) or {})
    breakdown = dict(report.get("soft_penalty_breakdown", {}) or {})
    sla = dict(report.get("sla", {}) or {})
    lines = [
        f"# {report.get('branding', {}).get('display_name', 'Schedule Quality Report')}",
        "",
        "## Summary",
        f"- Activities: {summary.get('activities', 0)}",
        f"- Groups: {summary.get('groups', 0)}",
        f"- Staff: {summary.get('staff', 0)}",
        f"- Rooms: {summary.get('rooms', 0)}",
        f"- Hard conflicts: {summary.get('hard_conflicts', 0)}",
        f"- Soft penalty: {summary.get('soft_penalty', 0)}",
        "",
        "## SLA",
        f"- Passed: {bool(sla.get('passed', True))}",
        f"- Violations: {', '.join(str(v) for v in (sla.get('violations') or [])) or 'none'}",
        "",
        "## Top soft-penalty terms",
    ]
    top_terms = [
        (key, int(value))
        for key, value in breakdown.items()
        if str(key) != "total" and int(value) > 0
    ]
    top_terms.sort(key=lambda item: item[1], reverse=True)
    if top_terms:
        lines.extend(f"- {key}: {value}" for key, value in top_terms[:8])
    else:
        lines.append("- No soft-penalty drivers recorded.")
    lines.extend(["", "## Hard-conflict samples"])
    samples = list(report.get("hard_conflict_samples", []) or [])
    if samples:
        lines.extend(f"- {line}" for line in samples)
    else:
        lines.append("- None.")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}
