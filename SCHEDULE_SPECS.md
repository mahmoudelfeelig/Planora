# Schedule Specification (Checklist)

## Time Grid & Activity Structure
- [x] 12 teaching weeks (1–12); teaching days Mon–Sat only (Sunday stripped/unsupported); 5 slots per day.
- [x] Activities: lectures (LEC), tutorials (TUT), labs (LAB) with durations 1–3 slots; week 1 is LEC-only (TUT/LAB in week 1 are rejected).
- [x] Course patterns from generator: LEC_TUT with parity between total LEC slots and per-group TUT slots; optional LAB_ONLY courses with specialized lab tags; optional block-lecture courses.
- [x] Clustering: shared lectures by course/group and optional cross-major clusters co-locate starts (and rooms where applicable).

## Hard Constraints Enforced in CP
- [x] No overlap per group and per staff member (interval NoOverlap).
- [x] Staff availability respected; activities without any allowed start raise immediately.
- [x] Block professors: at most two distinct teaching days per week.
- [x] Optional staff daily/weekly load caps honored.
- [x] Lecture/Tutorial parity per course+group validated before solve; mismatches fail fast.
- [x] Week-1 LEC-only rule enforced (tutorials/labs cause an error).
- [x] Allowed starts exclude Sunday completely.
- [x] Room guards: per-slot counts for lecture rooms, tutorial+lecture pool, lab rooms, and per-tag lab counts; CP-rooming mode adds per-room NoOverlap.
- [x] Specialized labs require matching tags when specified; missing tagged rooms raise errors.

## Room Assignment
- [x] Greedy assignment (default) co-locates clusters, prefers specialized labs, applies capacity-aware picks, and prefers tutorial rooms for TUT before lecture overflow.
- [x] CP-rooming mode (optional) enforces room NoOverlap and co-locates clustered activities into a shared room choice set.
- [ ] Room capacity is approximated (not a hard CP constraint in greedy mode; CP-rooming ignores capacity numbers).

## Soft Constraints (Local Search Improver)
- [x] Student free days (overall and Mon–Fri preference).
- [x] Student gaps within a day; heavy-day penalty; early-start discourager.
- [x] Staff free day (≥1 per week).
- [x] Active-day minimization for groups.
- [x] Week-to-week stability of day patterns.
- [x] Room consistency per (course, group, kind) across weeks.

## Solve/Export Flow
- [x] Solve via `engine_cli.py` (CP-SAT; optional time limit via `TT_TIME_LIMIT` env var); UNKNOWN solver status mapped to non-feasible to avoid bogus schedules.
- [x] Optional local search improvement in UI and CLI.
- [x] Exports: DOCX, CSV, ICS (per group/staff/room) with timezone-safe DTSTAMP; DOCX uses time labels derived from stamped or default slot settings.

## Known Limitations
- [ ] No Sunday scheduling; extending the grid requires code changes.
- [ ] Capacity is not enforced inside CP unless using CP-rooming; greedy assignment may still fail if no room fits.
- [ ] Manual edits in the UI do not perform live conflict detection beyond the displayed grid; feasibility is preserved only when re-solving.
