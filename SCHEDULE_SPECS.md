# Schedule Specification (Checklist)

## Time Grid & Activity Structure
- [x] 12 teaching weeks (1–12); teaching days Mon–Sat only (Sunday stripped/unsupported); 5 slots per day.
- [x] Activities: lectures (LEC), tutorials (TUT), labs (LAB) with durations 1–3 slots; week 1 is LEC-only (TUT/LAB in week 1 are rejected).
- [x] Course patterns from generator: `LEC_ONLY`, `LEC_TUT`, `LEC_TUT_LAB`, `LAB_ONLY`; lecture/tutorial slot totals support 12/18/24; labs can run for 0/12 weeks with 1- or 2-slot duration.
- [x] Clustering: shared lectures by course/group and optional cross-major clusters co-locate starts (and rooms where applicable).

## Hard Constraints Enforced in CP
- [x] No overlap per group and per staff member (interval NoOverlap).
- [x] Staff availability respected; activities without any allowed start raise immediately.
- [x] Staff assignment rules: professors teach `LEC` for courses in their `can_teach_courses`; TAs teach `TUT/LAB` for courses in their `can_teach_courses`.
- [x] Block-only professors: for each (course, week) they teach, lectures form a single contiguous 2-3 slot block on one day.
- [x] Optional staff daily/weekly load caps honored.
- [x] Course totals validated against metadata (lecture/tutorial slot totals, lab session counts, lab durations).
- [x] Week-1 LEC-only rule enforced (tutorials/labs cause an error).
- [x] Allowed starts exclude Sunday completely.
- [x] Room assignment in CP-rooming mode: per-room NoOverlap with eligible room filtering (type, specialization, capacity) and optional per-(day,slot) room availability.
- [x] Specialized labs require matching tags when specified; missing tagged rooms raise errors.

## Room Assignment
- [x] Greedy assignment (default) co-locates clusters, prefers specialized labs, applies capacity-aware picks, and prefers tutorial rooms for TUT before lecture overflow.
- [x] CP-rooming mode (optional) enforces room NoOverlap and co-locates clustered activities into a shared room choice set.
- [x] CP-rooming mode enforces room capacity by filtering eligible rooms; greedy mode is capacity-aware but does not influence CP timing decisions.

## Soft Constraints (Local Search Improver)
- [x] Student free days (overall and Mon–Fri preference).
- [x] Student gaps within a day; heavy-day penalty; early-start discourager.
- [x] Staff free day (≥1 per week).
- [x] Active-day minimization for groups.
- [x] Week-to-week stability of day patterns.
- [x] Room consistency per (course, group, kind) across weeks.

## Soft Constraints (CP Objective)
- [x] CP objective minimizes a weighted sum of free-day shortfalls, gaps, early starts, heavy days, staff no-free-day, active days, stability, and room consistency (weights overrideable via `Instance.soft_weights`).

## Solve/Export Flow
- [x] Solve via `engine_cli.py` (CP-SAT; optional time limit via `TT_TIME_LIMIT` env var); UNKNOWN solver status mapped to non-feasible to avoid bogus schedules.
- [x] Optional local search improvement in UI and CLI.
- [x] Exports: DOCX, CSV, ICS (per group/staff/room) with timezone-safe DTSTAMP; DOCX uses time labels derived from stamped or default slot settings.
- [x] Export: PDF (text-only) and CSV summary reports (staff/group/room load).
- [x] Locking: activities can be fixed (day/slot and/or room) for partial re-solving via `Instance.locked_activities` (used by the desktop UI).

## Known Limitations
- [ ] No Sunday scheduling; extending the grid requires code changes.
- [ ] In greedy room mode, capacity/room constraints are not part of CP timing decisions.
- [ ] UI manual edits validate basic constraints but do not show a full conflict list or constraint explanations.
