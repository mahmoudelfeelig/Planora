from __future__ import annotations

import os
from typing import Dict, Any, Iterable
from collections import Counter, defaultdict
from datetime import datetime, date, time, timedelta

from ortools.sat.python import cp_model

from utils.generator import generate_instance
from core.solver_cp_sat import TimetableSolver
from core.metaheuristics import LocalSearchImprover
from utils.domain import Instance
from utils.exporter import (
    export_group_schedules_to_docx,
    export_groups_ics_per_id,
    export_staff_ics_per_id,
    export_rooms_ics_per_id,
    export_schedule_to_csv,
    export_groups_pdf,
    export_summary_reports,
)
from utils.specs import validate_instance_against_spec

# ---------- time labels ----------

def build_time_labels(slots_per_day: int, day_start: time, slot_minutes: int, break_minutes: int = 0) -> list[str]:
    labels: list[str] = []
    cur = datetime.combine(date.today(), day_start)
    for _ in range(slots_per_day):
        start = cur
        end = start + timedelta(minutes=slot_minutes)
        labels.append(f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
        cur = end + timedelta(minutes=break_minutes)
    return labels

def stamp_instance_time(inst: Instance, day_start_str: str, slot_minutes: int, break_minutes: int = 0) -> None:
    inst.day_start_time = day_start_str
    inst.slot_minutes = int(slot_minutes)
    inst.slot_break_minutes = int(break_minutes)
    hh, mm = [int(x) for x in day_start_str.split(":")]
    inst.time_labels = build_time_labels(inst.slots_per_day, time(hh, mm), slot_minutes, break_minutes)

# ---------- feasibility helpers (new) ----------

def _has_sun(days: list[str]) -> bool:
    return any(d.upper().startswith("SUN") for d in days)

def normalize_instance_for_spec(inst: Instance) -> None:
    """
    Make the generated instance compatible with the documented hard rules:
      - Strip Sunday from the working week (teaching is not allowed on Sunday).
      - Preserve staff availability, normalized to the instance's days; fill with all
        valid days only when it would otherwise be empty.
      - Quick sanity for specialized lab tags: warn if a LAB requires a tag with no room.
    """
    original_days = list(inst.days)
    pruned_days = [d for d in original_days if not d.upper().startswith("SUN")]
    if len(pruned_days) != len(original_days):
        print("[WARN] Removed Sunday from inst.days; teaching is not allowed on Sunday.")
    inst.days = pruned_days

    valid_days = set(inst.days)
    for s in inst.staff.values():
        avail = {d for d in getattr(s, "available_days", []) or [] if d in valid_days}
        if not avail and valid_days:
            print(f"[WARN] Staff '{s.name}' has no valid availability; defaulting to all days.")
            avail = set(valid_days)
        s.available_days = avail

    # Warn if any specialized lab tag has no room (keeps your strict matching)
    tags_present = defaultdict(int)
    for r in inst.rooms.values():
        if getattr(r, "room_type", None) == "SPECIALIZED_LAB":
            for t in getattr(r, "specialization_tags", []) or []:
                tags_present[t] += 1
    missing = set()
    for a in inst.activities.values():
        if a.kind == "LAB":
            tag = getattr(a, "requires_specialization", None)
            if tag and tags_present.get(tag, 0) == 0:
                missing.add(tag)
    if missing:
        print("[WARN] No specialized lab rooms for tags:", sorted(missing))

def print_instance_stats(inst: Instance) -> None:
    profs = sum(1 for s in inst.staff.values() if s.is_prof)
    tas = sum(1 for s in inst.staff.values() if not s.is_prof)

    print("=== Instance stats ===")
    print(f"Programs       : {len(inst.programs)}")
    print(f"Groups         : {len(inst.groups)}")
    print(f"Courses        : {len(inst.courses)}")
    print(f"Staff total    : {len(inst.staff)}")
    print(f"  Professors   : {profs}")
    print(f"  TAs          : {tas}")
    print(f"Rooms          : {len(inst.rooms)}")
    print(f"Activities     : {len(inst.activities)}")

    lec = sum(1 for a in inst.activities.values() if a.kind == "LEC")
    tut = sum(1 for a in inst.activities.values() if a.kind == "TUT")
    lab = sum(1 for a in inst.activities.values() if a.kind == "LAB")
    print(f"  LEC activities: {lec}")
    print(f"  TUT activities: {tut}")
    print(f"  LAB activities: {lab}")

    c_struct = Counter(c.structure_type for c in inst.courses.values())
    print("Course structures:")
    for stype, cnt in c_struct.items():
        print(f"  {stype}: {cnt}")

    print("Groups and their course counts:")
    for g_id, g in inst.groups.items():
        print(f"  {g.name} (id {g_id}), size={g.size}, courses={len(g.course_ids)}")
    print("===")

def _is_block_prof(staff) -> bool:
    return bool(getattr(staff, "blocks_only", False) or getattr(staff, "is_block_prof", False))

def check_staff_weekly_capacity(inst: Instance) -> None:
    """
    Prints warnings when any staff's required slot load per week exceeds
    what is schedulable under availability plus daily/weekly caps.
    """
    S = inst.slots_per_day
    valid_days = [d for d in inst.days if not d.upper().startswith("SUN")]
    cap_by_staff: Dict[int, int] = {}
    for sid, s in inst.staff.items():
        avail = {d for d in getattr(s, "available_days", []) or [] if d in valid_days}
        if not avail:
            avail = set(valid_days)

        usable_days = min(len(avail), 2 if _is_block_prof(s) else len(avail))
        daily_cap = S if s.max_slots_per_day is None else min(S, int(s.max_slots_per_day))
        cap = usable_days * daily_cap
        weekly_cap = getattr(s, "max_slots_per_week", None)
        if weekly_cap is not None:
            cap = min(cap, int(weekly_cap))
        cap_by_staff[sid] = cap

    load_by_staff_week: Dict[tuple, int] = defaultdict(int)
    for a in inst.activities.values():
        sid = a.prof_id if a.kind == "LEC" else a.ta_id
        load_by_staff_week[(sid, a.week)] += int(a.duration)

    flagged = False
    for (sid, w), req in sorted(load_by_staff_week.items()):
        cap = cap_by_staff.get(sid, 0)
        if req > cap:
            flagged = True
            s = inst.staff[sid]
            kind = "BLOCK" if _is_block_prof(s) else ("PROF" if s.is_prof else "TA")
            print(f"[WARN] Staff '{s.name}' ({kind}) week {w}: need {req} slots > capacity {cap}")
    if not flagged:
        print("Staff weekly loads within theoretical capacity bounds.")

# ---------- group quality (unchanged) ----------

def compute_group_penalties(inst: Instance, schedule: Dict[int, Dict[str, Any]]) -> Dict[int, int]:
    days = inst.days
    weeks = inst.weeks
    S = inst.slots_per_day

    weights = {
        "stud_free_days": 10,
        "stud_free_mf": 5,
        "stud_gaps": 5,
        "active_days": 5,
        "late_start": 3,
        "thin_day": 3,
        "stability": 1,
        "single_slot": 6,
    }
    overrides = getattr(inst, "soft_weights", None)
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            if k in weights:
                try:
                    weights[k] = int(v)
                except Exception:
                    pass

    W_STUD_FREE_DAYS = weights["stud_free_days"]
    W_STUD_FREE_MF = weights["stud_free_mf"]
    W_STUD_GAPS = weights["stud_gaps"]
    W_ACTIVE_DAYS = weights["active_days"]
    W_LATE_START = weights["late_start"]
    W_THIN_DAY = weights["thin_day"]
    W_STABILITY = weights["stability"]
    W_SINGLE_SLOT = weights["single_slot"]

    group_occ: Dict[tuple, int] = {}
    for g_id in inst.groups.keys():
        for w in weeks:
            for d in days:
                for s in range(S):
                    group_occ[g_id, w, d, s] = 0

    for a_id, info in schedule.items():
        w = info["week"]; d = info["day"]; s0 = info["slot"]; dur = info["duration"]
        for ds in range(dur):
            s = s0 + ds
            if 0 <= s < S:
                for g_id in info["group_ids"]:
                    group_occ[g_id, w, d, s] = 1

    day_active: Dict[tuple, int] = {}
    for g_id in inst.groups.keys():
        for w in weeks:
            for d in days:
                occs = [group_occ[g_id, w, d, s] for s in range(S)]
                day_active[g_id, w, d] = 1 if any(occs) else 0

    penalties: Dict[int, int] = {g_id: 0 for g_id in inst.groups.keys()}
    workdays = [d for d in days if d in {"MON","TUE","WED","THU","FRI"}]

    for g_id, g in inst.groups.items():
        pen = 0
        for w in weeks:
            free_days = sum(1 - day_active[g_id, w, d] for d in days)
            if free_days < g.preferred_free_days:
                pen += W_STUD_FREE_DAYS * (g.preferred_free_days - free_days)
            free_mf = sum(1 - day_active[g_id, w, d] for d in workdays)
            if free_mf < g.preferred_free_days:
                pen += W_STUD_FREE_MF * (g.preferred_free_days - free_mf)
            for d in days:
                occ = [group_occ[g_id, w, d, s] for s in range(S)]
                blocks = 0; prev = 0; load = 0; first_slot = None
                for idx, v in enumerate(occ):
                    if v == 1 and prev == 0: blocks += 1
                    if v == 1:
                        load += 1
                        if first_slot is None:
                            first_slot = idx
                    prev = v
                if blocks > 1: pen += W_STUD_GAPS * (blocks - 1)
                if load == 1: pen += W_SINGLE_SLOT
                if load == 2: pen += W_THIN_DAY
                if first_slot is not None and first_slot >= 2: pen += W_LATE_START
            active_days = sum(day_active[g_id, w, d] for d in days)
            if active_days > 3: pen += W_ACTIVE_DAYS * (active_days - 3)
        for wi in range(1, len(weeks)):
            w_prev = weeks[wi-1]; w_curr = weeks[wi]
            for d in days:
                if day_active[g_id, w_prev, d] != day_active[g_id, w_curr, d]:
                    pen += W_STABILITY
        penalties[g_id] = pen
    return penalties

def classify_group_quality(pen: int) -> str:
    if pen <= 150: return "optimal"
    if pen <= 400: return "near-optimal"
    if pen <= 800: return "decent"
    return "bad"

def print_group_quality(inst: Instance, schedule: Dict[int, Dict[str, Any]]) -> None:
    group_pens = compute_group_penalties(inst, schedule)
    print("=== Per-group quality ===")
    for g_id in sorted(inst.groups.keys()):
        g = inst.groups[g_id]
        pen = group_pens.get(g_id, 0)
        label = classify_group_quality(pen)
        print(f"  {g.name} (id {g_id}): {pen} ({label})")
    print("===")

# ---------- main ----------

def main():
    MODE = "target_case"

    CP_TIME_LIMIT = float(os.getenv("TT_TIME_LIMIT", "300.0"))
    CP_WORKERS = int(os.getenv("TT_CP_WORKERS", "8"))
    LS_ITERATIONS = int(os.getenv("TT_LS_ITERATIONS", "10000"))
    LS_START_TEMP = 5.0
    LS_END_TEMP = 0.1
    LS_MAX_SECONDS_ENV = os.getenv("TT_LS_MAX_SECONDS")
    LS_MAX_SECONDS = float(LS_MAX_SECONDS_ENV) if LS_MAX_SECONDS_ENV not in (None, "") else None

    DAY_START = "08:30"
    SLOT_MINUTES = 90
    BREAK_MINUTES = 0

    EXPORT_DOCX = f"timetable_{MODE}.docx"
    EXPORT_ICS_DIR = f"ics_{MODE}"
    EXPORT_CSV = f"schedule_{MODE}.csv"
    EXPORT_PDF = f"groups_{MODE}.pdf"
    EXPORT_REPORTS_DIR = f"reports_{MODE}"

    inst = generate_instance(mode=MODE)

    # normalize to satisfy new hard rules
    normalize_instance_for_spec(inst)
    stamp_instance_time(inst, DAY_START, SLOT_MINUTES, BREAK_MINUTES)
    validate_instance_against_spec(inst)
    print_instance_stats(inst)
    check_staff_weekly_capacity(inst)  # prints warnings only

    room_mode = os.getenv("TT_ROOM_MODE", "cp_rooms")
    use_objective_env = os.getenv("TT_USE_OBJECTIVE", "1").strip()
    use_objective = use_objective_env not in ("0", "false", "False", "no")
    log_progress_env = os.getenv("TT_CP_LOG", "").strip().lower()
    log_progress = log_progress_env not in ("", "0", "false", "no")

    strict_limit_env = os.getenv("TT_STRICT_TIME_LIMIT")
    strict_limit = float(strict_limit_env) if strict_limit_env else min(CP_TIME_LIMIT, 300.0)

    solver_model = TimetableSolver(inst, room_mode=room_mode, use_objective=use_objective)
    cp_solver, status = solver_model.solve(
        time_limit_seconds=strict_limit,
        workers=CP_WORKERS,
        log_progress=log_progress,
    )

    # Fallback to faster mode if strict solve fails (unknown/infeasible)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE) and room_mode == "cp_rooms":
        print("Strict CP-rooming did not find a solution (status =", status, "); falling back to greedy rooming...")
        solver_model = TimetableSolver(inst, room_mode="greedy", use_objective=False)
        cp_solver, status = solver_model.solve(
            time_limit_seconds=CP_TIME_LIMIT,
            workers=CP_WORKERS,
            log_progress=log_progress,
        )

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("No feasible solution, status:", status)
        return

    schedule = solver_model.extract_solution(cp_solver)
    print(f"CP-SAT status: {status} (0=FEASIBLE, 4=OPTIMAL); time limit = {CP_TIME_LIMIT}s")

    # optional local search: off by default to avoid breaking hard rules
    improved = schedule
    if LS_ITERATIONS and LS_ITERATIONS > 0:
        ls = LocalSearchImprover(inst)
        base_pen = ls.compute_soft_penalty(schedule)
        print("Soft penalty before local search:", base_pen)

        ls_progress_env = os.getenv("TT_LS_PROGRESS", "1").strip().lower()
        ls_progress = ls_progress_env not in ("0", "false", "no")

        def _ls_progress_hook(iteration: int, best_pen: int, current_pen: int):
            if ls_progress:
                print(f"[ls] iter {iteration}/{LS_ITERATIONS} best={best_pen} current={current_pen}")

        improved = ls.improve(
            schedule, iterations=LS_ITERATIONS,
            start_temp=LS_START_TEMP, end_temp=LS_END_TEMP,
            max_seconds=LS_MAX_SECONDS,
            progress_every=1000,
            progress_hook=_ls_progress_hook if ls_progress else None,
        )
        print("Soft penalty after local search:", ls.compute_soft_penalty(improved))

    print_group_quality(inst, improved)

    print("=== Sample activities ===")
    for a_id, info in sorted(improved.items())[:200]:
        print(
            f"A{a_id}: week {info['week']} {info['day']} "
            f"slot {info['slot']} dur {info['duration']} "
            f"room {info['room_id']} staff {info['staff_id']} "
            f"course {info['course_id']} kind {info['kind']} "
            f"groups {info['group_ids']}"
        )

    try:
        print(f"Exporting group DOCX to {EXPORT_DOCX} ...")
        export_group_schedules_to_docx(inst, improved, EXPORT_DOCX)
        print("Export finished:", EXPORT_DOCX)
    except Exception as e:
        print("Export error:", e)

    # new: per-entity ICS files (groups, staff, rooms)
    try:
        export_groups_ics_per_id(inst, improved, EXPORT_ICS_DIR)
        export_staff_ics_per_id(inst, improved, EXPORT_ICS_DIR)
        export_rooms_ics_per_id(inst, improved, EXPORT_ICS_DIR)
        print("ICS exported to:", EXPORT_ICS_DIR)
    except Exception as e:
        print("ICS export error:", e)
        if getattr(e, "reason", None):
            print("Rooming failure reason:", getattr(e, "reason", None))

    # CSV schedule export
    try:
        export_schedule_to_csv(inst, improved, EXPORT_CSV)
        print("CSV exported to:", EXPORT_CSV)
    except Exception as e:
        print("CSV export error:", e)

    # PDF group export
    try:
        export_groups_pdf(inst, improved, EXPORT_PDF)
        print("PDF exported to:", EXPORT_PDF)
    except Exception as e:
        print("PDF export error:", e)

    # Summary reports
    try:
        export_summary_reports(inst, improved, EXPORT_REPORTS_DIR)
        print("Reports exported to:", EXPORT_REPORTS_DIR)
    except Exception as e:
        print("Report export error:", e)


if __name__ == "__main__":
    main()
