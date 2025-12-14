# University Timetabling Scheduler (Python)

Generates and edits 12-week university timetables (lectures, tutorials, and labs) on a fixed weekly grid, using an OR-Tools CP-SAT feasibility model plus an optional local-search improver. Includes a PyQt6 desktop UI and exporters for DOCX/CSV/ICS.

## What’s in this repo

- `domain.py`: dataclasses for `Program`, `Group`, `Course`, `StaffMember`, `Room`, `Activity`, and `Instance`.
- `generator.py`: creates a synthetic university instance (multiple “modes” like `small_demo`, `target_case`).
- `solver_cp_sat.py`: CP-SAT feasibility solver (`TimetableSolver`) and a greedy room assigner.
- `metaheuristics.py`: local-search improver (`LocalSearchImprover`) for schedule quality.
- `ui_desktop.py`: PyQt6 desktop UI (generate → solve → improve → export).
- `engine_cli.py`: small worker process used by the UI to run the solver out-of-process.
- `exporter.py`: exports schedules to DOCX (optional dependency), CSV, and per-entity ICS files.
- `tests/`: pytest suite that checks key behaviors and constraints.

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
- Some features commonly found in full timetabling products (data import/edit screens, scenario persistence, PDF export, REST API) are not implemented here.

