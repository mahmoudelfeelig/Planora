# Program Specification (Checklist)

## Delivered
- [x] Data model includes programs, groups, courses, staff (professors/TAs), rooms (lecture/tutorial/computer/specialized lab), activities, and a 12-week time grid (Mon–Sat, 5 slots/day).
- [x] Automatic instance generation (`generator.py`) for multiple scenarios (small_demo, block_profs, labs_only, mixed_large, random, target_case).
- [x] Solver pipeline: CP-SAT feasibility (`solver_cp_sat.py`) + greedy rooming (or CP-rooming) + optional local search improver.
- [x] Desktop UI (`ui_desktop.py`) to generate, solve (via `engine_cli.py` worker), run local search, export DOCX, and manually edit placed activities (day/slot/room/staff) per cell.
- [x] Exporters for DOCX timetables, CSV, and ICS (per group/staff/room) with timezone-safe timestamps.
- [x] Status mapping safeguards: UNKNOWN solver status is treated as non-feasible; week-1 lecture-only rule enforced; specialized labs require matching tagged rooms or fail fast.

## Partially Delivered / Simplified
- [ ] Capacity and room-choice constraints are approximated by room counts in CP and capacity-aware greedy/CP assignment; no per-slot real-room overlap checks when using greedy mode.
- [ ] Staff availability editing and hard overrides are not exposed in the UI; the UI trusts generated data and normalization.
- [ ] Manual conflict checking is limited to solver/local-search feasibility; the UI does not surface a conflict list during edits.
- [ ] Scenario persistence/cloning/versioning is not implemented beyond ad-hoc pickle/DOCX/ICS exports.

## Not Delivered (reference items from the original spec)
- [ ] Full CRUD admin screens for programs/groups/courses/staff/rooms with validation.
- [ ] REST API for remote clients or web UI.
- [ ] PDF export; rich reporting beyond DOCX/CSV/ICS.
- [ ] Transaction/logging layer for auditability of edits and solver runs.
