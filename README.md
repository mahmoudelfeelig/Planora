# University Timetabling Scheduler (Python)

Generates and edits 12-week university timetables (lectures, tutorials, and labs) on a fixed weekly grid, using an OR-Tools CP-SAT feasibility model plus an optional local-search improver. Includes a PyQt6 desktop UI and exporters for DOCX/CSV/ICS/PDF plus CSV summary reports.

## What’s in this repo

- `utils/`: dataclasses (`domain.py`), generator (`generator.py`), exporter (`exporter.py`).
- `core/`: CP-SAT solver (`solver_cp_sat.py`), local search (`metaheuristics.py`), solver worker (`engine_cli.py`).
- `ui/`: PyQt6 desktop UI (`app.py`, `dialogs.py`, `styles.py`) with a thin `ui_desktop.py` launcher.
- `main.py`: CLI entry point (generate → solve → optional local search → export).
- `tests/`: pytest suite that checks key behaviors and constraints.
- `SPECS.md`: unified program + schedule spec checklist (replaces PROGRAM/SCHEDULE_SPECS).

## Performance / Quality knobs

- Hard constraints (including room conflicts) are enforced by default (`TT_ROOM_MODE=cp_rooms`, objective on).
- Faster but looser room handling: set `TT_ROOM_MODE=greedy` (room overlaps checked after CP, faster).
- Skip CP soft objective to speed up: `TT_USE_OBJECTIVE=0` (local search still improves quality).
- Time/worker limits: `TT_TIME_LIMIT` (seconds), `TT_CP_WORKERS` (threads).
- Local search: `TT_LS_ITERATIONS`, `TT_LS_MAX_SECONDS` (0/blank = no cap).

The desktop UI exposes these toggles: room mode (Strict/Fast), objective on/off, CP time limit, worker count, and local-search iterations/time budget.

## Key concepts

- **Time grid**: 12 teaching weeks (`1..12`), 6 teaching days (`MON..SAT`), 5 slots/day.
- **Activities**: each `Activity` is a single event in a specific week (LEC/TUT/LAB) with a duration in slots.
- **Schedule format**: a dict keyed by activity id, with values like:
  - `week`, `day`, `slot`, `duration`
  - `room_id`, `staff_id`, `course_id`, `group_ids`, `kind`

## Solver approach (high level)

1. **CP-SAT feasibility** (`solver_cp_sat.py`):
   - Picks a start time (day/slot) for each activity subject to hard constraints (no overlaps for staff/groups; staff availability; week-1 “lectures only”; and several modeled rules used by the project).
2. **Room assignment**:
   - `room_mode="greedy"` (default): assign rooms after CP timing with `assign_rooms_greedily`.
   - `room_mode="cp_rooms"`: CP also chooses rooms with per-room no-overlap (slower).
3. **Optional improvement** (`metaheuristics.py`):
   - Local search attempts to reduce soft penalties (free days, gaps, early starts, stability, room consistency) while keeping schedules feasible for the constraints it checks.

## Running

### Prerequisites

- Python 3.12+ (the repo is Windows-friendly; examples use the `py` launcher).
- Required:
  - `ortools`
- For the desktop UI:
  - `PyQt6`
- For DOCX export:
  - `python-docx`
- For tests:
  - `pytest`

Install dependencies (example):

`py -m pip install ortools PyQt6 python-docx pytest`

### CLI run (generate + solve + export)

`py main.py`

`main.py` generates an instance (default `MODE="target_case"`), runs the CP-SAT solver, optionally runs local search, and exports:

- Group schedules to `timetable_<mode>.docx` (requires `python-docx`)
- ICS calendars to `ics_<mode>/` (groups, staff, rooms)

### Desktop UI

`py ui_desktop.py`

Workflow:

- Pick a generation mode → **Generate**
- **Solve** (runs `engine_cli.py` via `QProcess`)
- **Improve** (runs local search)
- **Export DOCX** (group schedules; requires `python-docx`)

Optional solver time limit (seconds) for the UI worker:

- `TT_TIME_LIMIT=60`

## Notes / current limitations

- The built-in generator focuses on `LEC_TUT` and `LAB_ONLY` course patterns; other structure types can be added by extending `generator.py`.
- Some features commonly found in full timetabling products (data import/edit screens, scenario persistence, multi-scenario comparison, detailed constraint explanation) are not implemented here.
