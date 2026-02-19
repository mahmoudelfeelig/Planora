# Scheduler Specifications (Unified)

This document merges the program- and schedule-level specs. All modes must respect these hard rules; performance knobs only affect solve speed/quality, not feasibility.

## Time Grid & Activity Structure
- 12 teaching weeks (1–12); teaching days Mon–Sat; 5 slots/day; Sunday unsupported/stripped.
- Activities: LEC/TUT/LAB durations 1–3 slots; week 1 is LEC-only (TUT/LAB rejected).
- Course patterns: `LEC_ONLY`, `LEC_TUT`, `LEC_TUT_LAB`, `LAB_ONLY`; lecture/tutorial slot totals support 12/18/24; labs run 0/12 weeks with 1- or 2-slot duration.
- Clustering: shared lectures by course/group and optional cross-major clusters with tag-safe LAB clustering.

## Hard Constraints (CP)
- No overlap per group and per staff (interval NoOverlap).
- Staff availability enforced; activities without allowed starts fail early; Sunday excluded.
- Staff assignment: professors teach LEC for courses in `can_teach_courses`; TAs teach TUT/LAB likewise.
- Block-only professors: single contiguous 2–3-slot lecture block per course/week on one day.
- Optional staff daily/weekly load caps enforced.
- Course totals validated (lecture/tutorial slots, lab sessions/durations).
- Week-1 LEC-only rule.
- Rooms: in strict mode (`room_mode=cp_rooms`), per-room NoOverlap with eligibility (type/tag/capacity) and optional availability; specialized labs require matching tags or fail generation/solve.
- Locking: activities may be fixed (day/slot/room) via `Instance.locked_activities`.

## Room Assignment
- Strict (default): CP picks rooms with NoOverlap, eligibility, availability, and cluster co-location.
- Fast: greedy assignment after CP timing; still respects eligibility/capacity/availability, but conflicts are not part of CP timing.

## Soft Constraints
- Free days (overall and Mon–Fri), gaps, thin/single days, late starts, active-day minimization, week-to-week stability, staff free day, room consistency. Modeled in CP objective (optional) and in local search.

## Solve/Improve Flow
- CLI/UI use CP-SAT; UNKNOWN maps to non-feasible. Local search optional with iteration/time cap.
- Optional phased solve (anytime):
  - Phase 1: feasibility-first CP run (objective off) bounded by `TT_FEASIBILITY_SECONDS`.
  - Phase 2: iterative local-search improvement slices bounded by `TT_IMPROVE_TOTAL_SECONDS`.
  - Worker always returns the best schedule found so far under the configured budgets.
- Exports: DOCX, CSV, ICS (per group/staff/room) with stamped time grid; PDF (text-only) and CSV summary reports.

## Performance / Quality Knobs
- `TT_ROOM_MODE`: `cp_rooms` (strict, default) vs `greedy` (faster).
- `TT_USE_OBJECTIVE`: `1`/`0` to toggle CP soft objective.
- `TT_TIME_LIMIT`: CP time limit (seconds); `TT_CP_WORKERS`: solver threads.
- `TT_PHASED_SOLVE`: `1` enables feasibility-first + iterative improvement.
- `TT_FEASIBILITY_SECONDS`: phase-1 budget (seconds).
- `TT_IMPROVE_TOTAL_SECONDS`: total phase-2 budget (seconds).
- `TT_IMPROVE_SLICE_SECONDS`, `TT_IMPROVE_ITERS_PER_SLICE`, `TT_IMPROVE_MAX_ROUNDS`: per-round local-search controls.
- `TT_LS_ITERATIONS`, `TT_LS_MAX_SECONDS`: local-search effort.
- Desktop UI exposes these toggles (room mode, objective, time limit, workers, LS iters/time).

## Known Limitations
- No Sunday scheduling without code changes.
- In greedy room mode, room constraints don’t influence CP timing (validated afterward).
- UI manual edits remain basic; conflict explanations are heuristic only.
