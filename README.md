# University Timetabling Scheduler (Python)

Generates and edits 12-week university timetables (lectures, tutorials, and labs) on a fixed weekly grid, using an OR-Tools CP-SAT feasibility model plus an optional local-search improver. Includes a PyQt6 desktop UI and exporters for DOCX/CSV/ICS/PDF plus CSV summary reports.

## What’s in this repo

- `utils/`: dataclasses (`domain.py`), generator (`generator.py`), exporter (`exporter.py`).
- `core/`: CP-SAT solver (`solver_cp_sat.py`), local search (`metaheuristics.py`), solver worker (`engine_cli.py`).
- `ui/`: PyQt6 desktop UI (`app.py`, `window.py`, `dialogs.py`, `styles.py`).
- `main.py`: CLI entry point (generate → solve → optional local search → export).
- `tests/`: pytest suite that checks key behaviors and constraints.
- `SPECS.md`: unified program + schedule spec checklist (replaces PROGRAM/SCHEDULE_SPECS).
 - Projects: save/load JSON/PKL snapshots (instance + schedule + locks) via the UI.
 - Imports: load raw instances (JSON/PKL) and schedules (CSV) from the UI.

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
   - `room_mode="cp_rooms"` (default): CP also chooses rooms with per-room no-overlap (slower).
   - `room_mode="greedy"` (fast mode): assign rooms after CP timing with `assign_rooms_greedily`.
3. **Optional improvement** (`metaheuristics.py`):
   - Local search attempts to reduce soft penalties (free days, gaps, early starts, stability, room consistency) while keeping schedules feasible for the constraints it checks.

## Running

### Prerequisites

- Python 3.12+

Recommended setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Optional editable install (exposes `scheduler-cli` and `scheduler-ui` entrypoints):

```bash
python -m pip install -e .[dev]
```

### CLI run (generate + solve + export)

`python main.py`

Exports include DOCX, ICS, CSV schedule, PDF group listings, and CSV summary reports.

`main.py` generates an instance (default `MODE="target_case"`), runs the CP-SAT solver, optionally runs local search, and exports:

- Group schedules to `timetable_<mode>.docx` (requires `python-docx`)
- ICS calendars to `ics_<mode>/` (groups, staff, rooms)

### Desktop UI

`python ui/app.py`

Workflow:

- Pick a generation mode → **Generate**
- For `custom` mode, use the **Generator** tab to set:
  - programs / groups-per-program / courses-per-program
  - professor/TA counts, per-staff course responsibilities, and available teaching days
  - per-room type/category/capacity/tags
- **Solve** (runs `engine_cli.py` via `QProcess`)
- **Improve** (runs local search)
- Use the **Constraints** tab to tune hard-constraint toggles and soft weights before solving.
- **Export DOCX** (group schedules; requires `python-docx`)
 - **Export CSV/ICS** (schedule CSV; per-entity ICS)
 - **Save/Load Project** (JSON/PKL snapshots)
 - **Compare** (diff current schedule vs a saved project; optional report export)
 - **Load Instance / Load Schedule** (bring in external data)

Optional solver time limit (seconds) for the UI worker:

- `TT_TIME_LIMIT=300`
- `TT_PHASED_SOLVE=1` enables a feasibility-first pipeline:
  - solve without objective up to `TT_FEASIBILITY_SECONDS`
  - then run iterative local-search improvement slices for up to `TT_IMPROVE_TOTAL_SECONDS`
  - tune rounds via `TT_IMPROVE_SLICE_SECONDS`, `TT_IMPROVE_ITERS_PER_SLICE`, and `TT_IMPROVE_MAX_ROUNDS`
- Optional hard toggles carried inside the instance (`inst.hard_constraints`):
  - `week1_lectures_only`
  - `enforce_block_professor_rules`
  - `enforce_staff_daily_caps`
  - `enforce_staff_weekly_caps`
  - `enforce_room_availability`

### Windows Installer (`.exe`)

Build a distributable Windows installer for the desktop app:

1. Install:
   - Python 3.12+
   - Inno Setup 6
2. From a PowerShell terminal at repo root, run:

```powershell
.\scripts\windows\build_installer.ps1
```

Outputs:
- Portable app folder: `dist/Scheduler/`
- Installer executable: `dist/installer/Scheduler-Setup-v1.0.exe`

Useful flags:
- `-SkipTests`: skip pytest before packaging
- `-SkipInstaller`: build only `dist/Scheduler` (no setup `.exe`)

### macOS/Linux Packaging

Build a distributable desktop package on Unix-like systems:

```bash
chmod +x ./scripts/unix/build_installer.sh
./scripts/unix/build_installer.sh
```

Outputs:
- macOS: `dist/Scheduler-macos-v1.0.zip` (or `dist/Scheduler.app` portable bundle)
- Linux: `dist/Scheduler-linux-v1.0.tar.gz` (plus `dist/Scheduler/`)

Useful flags:
- `--skip-tests`: skip pytest before packaging
- `--skip-package`: build only portable app folder (`dist/Scheduler`)
- `--python /path/to/python`: use a specific Python interpreter

### Test and CI commands

Run the same checks used in CI:

```bash
./scripts/run_ci_checks.sh
```

This executes:
- syntax compile checks (`python -m compileall -q core ui utils tests main.py scripts`)
- non-slow tests (`pytest -m "not slow"`)
- slow/integration/UI tests (`pytest -m "slow"`)

### Publication experiment pipeline

Reproduce the expanded experiment batches and regenerate paper tables:

```bash
PYTHON_BIN=.venv/bin/python ./scripts/run_experiment_batches.sh
```

Freeze a release artifact bundle (commit + environment + checksums + paper inputs):

```bash
PYTHON_BIN=.venv/bin/python ./scripts/freeze_release_artifacts.sh v1.0
```

## Notes / current limitations

- The built-in generator focuses on `LEC_TUT` and `LAB_ONLY` course patterns; other structure types can be added by extending `generator.py`.
- Data import is file-based (JSON/PKL/CSV); schedules are validated against hard rules on load.
- Comparison reporting is summary-only (no side-by-side visualization).
