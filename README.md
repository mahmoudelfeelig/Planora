# Planora

Planora generates and edits academic timetables (lectures, tutorials, and labs) on configurable term and daily grids, using an OR-Tools CP-SAT master, exact or integrated room assignment, and an optional local-search improver. It includes a PyQt6 desktop UI and exporters for DOCX/CSV/ICS/PDF plus CSV summary reports.

The normal desktop, web, and Android workflow is deliberately small: Demo,
Spring 2023 university, or Import your data; then Fast, Balanced, or Maximum
quality. All clients consume the versioned `planora.ui.v1` catalog and route
solve/improve through `planora-solver-service-v1`. Research generators and raw
engine controls remain available under Advanced without becoming public
presets.

## What’s in this repo

- `utils/`: dataclasses (`domain.py`), generator (`generator.py`), exporter (`exporter.py`).
- `core/`: CP-SAT solver (`solver_cp_sat.py`), local search (`metaheuristics.py`), solver worker (`engine_cli.py`).
- `ui/`: PyQt6 desktop UI (`app.py`, `window.py`, `dialogs.py`, `styles.py`).
- `main.py`: CLI entry point (generate → solve → optional local search → export).
- `tests/`: pytest suite that checks key behaviors and constraints.
- `SPECS.md`: unified program + schedule spec checklist (replaces PROGRAM/SCHEDULE_SPECS).
 - Projects: save/load JSON or SQLite snapshots (instance + schedule + locks) via the UI.
 - Imports: load raw instances (JSON) and schedules (CSV) from the UI.

## Performance / Quality knobs

- Hard constraints (including room conflicts) are enforced by default (`TT_ROOM_MODE=cp_rooms`, objective on). Strict CP rooming uses the full eligible-room domain unless `TT_CP_ROOM_CANDIDATE_LIMIT` is explicitly set.
- Research decomposition: set `TT_ROOM_MODE=decomposed` to solve times in a CP-SAT master and rooms in an exact subproblem. A Hall witness is lifted only across alternative starts whose exact start-dependent room domain is proven to be contained in the witnessed room set; uncertain cases receive an exact incumbent nogood.
- Large-institution mode: set `TT_ROOM_MODE=partitioned` to preflight global invariants, solve independent teaching weeks in parallel, validate room assignments, and activate exact certificate decomposition only for a week whose fast room assignment fails. Required cross-week decision constraints fail before solving and must use a monolithic mode.
- Faster but looser room handling: set `TT_ROOM_MODE=greedy` (room overlaps checked after CP, faster).
- Skip CP soft objective to speed up: `TT_USE_OBJECTIVE=0` (local search still improves quality).
- Time/worker limits: `TT_TIME_LIMIT` (seconds), `TT_CP_WORKERS` (threads).
- Local search: `TT_LS_ITERATIONS`, `TT_LS_MAX_SECONDS` (0/blank = no cap).

The desktop UI exposes these toggles: room mode (Auto/Scale/Research/Strict/Fast), objective profile including fairness-first, CP time limit, worker count, and local-search budget.

## Key concepts

- **Time grid**: the built-in `target_case`/historical GIU research preset uses 12 teaching weeks, `MON..SAT`, and five daily slots. Imported instances and custom institutional presets can define different week/day/slot calendars.
- **Activities**: each `Activity` is a single event in a specific week (LEC/TUT/LAB) with a duration in slots.
- **Schedule format**: a dict keyed by activity id, with values like:
  - `week`, `day`, `slot`, `duration`
  - `room_id`, `staff_id`, `course_id`, `group_ids`, `kind`

## Solver approach (high level)

- **CP-SAT time model** (`solver_cp_sat.py`): picks one start per activity under resource, availability, calendar, travel, precedence, load, cluster, and lock constraints.
- **Room assignment**:
  - `room_mode="cp_rooms"`: integrated full-domain CP rooming.
  - `room_mode="decomposed"`: exact fixed-time room subproblem with iterative Hall/nogood cuts, explanation metadata, and repair scope support.
  - `room_mode="partitioned"`: parallel week-local compact masters with validated greedy rooming and automatic exact certificate fallback. This objective-free scale mode refuses hard cross-week decision coupling rather than dropping it.
  - `room_mode="greedy"`: fast post-processing baseline that can fail after a time-feasible master schedule.
- **Optional improvement** (`metaheuristics.py`): seeded local search reduces free-day, gap, late-start, stability, and room-consistency penalties while preserving checked hard constraints.
- **Fairness-first objective**: exact lexicographic minimization of worst group burden before total penalty, with tail, Gini, and Jain diagnostics.
- **Proof-guided adaptive improvement**: one reusable integrated CP-room model accepts incumbent hints and neighborhood assumptions, while typed room certificates, solver cores, penalty hotspots, and partition boundaries seed candidate neighborhoods. This avoids rebuilding the full model each round, but it does not reduce the model's variable or constraint count.

## Institution and benchmark portability

- `services/institution_policy_service.py` supplies executable policy presets. `generic_research_university` is the portable baseline, `north_american_balanced` is an explicitly non-official research abstraction, and `giu_target` is partially calibrated to the local historical GIU Berlin Spring 2023 schedule snapshot. The reproducible evidence and limitations are in `paper/evidence/giu_ss23_calibration.json`; it is not an official or current institution-approved preset. The source has 15 distinct nonblank room labels and 146 missing-room rows preserved as scoped placeholders, not 161 confirmed physical rooms. Its current replay has 148 unresolved validation errors: 93 synthetic-staff overlaps, 39 inferred room-type or specialization mismatches, and 16 apparent room overlaps.
- `services/institution_policy_readiness_service.py` distinguishes enabled flags from the calendar, capacity, availability, travel, demand, and stakeholder evidence needed to support them. `docs/INSTITUTION_POLICY_PORTABILITY.md` maps the portable representation to documented UC Davis, UC Berkeley, Michigan, and UniTime policy patterns without treating those examples as universal defaults.
- `Instance.distribution_constraints` represents ITC/UniTime-style relations. Common time, day, week, room, attendance, precedence, maximum-day, and maximum-day-load rules are enforced by CP; all supported relations share an exact post-solve evaluator and soft score. A required rule without an exact compiler fails before solving instead of being weakened silently.
- Room sizing can use nominal enrollment, named-scenario worst case, empirical quantiles, or a budgeted uncertainty set. The active policy and binding scenario are included in room certificates and experiment metrics.
- `benchmarks/itc2007.py` imports curriculum-course-timetabling instances, compiles all four official weighted objective components for integrated CP-room optimization, reads and writes official `.out` files, and cross-checks scores with the official C++ validator. The immutable breadth matrix remains official-valid on 21/21 instances and loses all 21 comparisons. Newer bounded post-incumbent operators have official-valid wins on selected instances, but they are not an end-to-end equal-budget replacement for that matrix and are reported separately.
- `benchmarks/itc2019.py` preserves alternate configurations, class hierarchies, admissible time/room domains, travel, distributions, and student requests in a local inspection representation and supports official-format solution XML interchange. Its CP-SAT student-sectioning path is conditional on already-fixed class placements; it does not compile a full joint placement-and-sectioning problem, and distribution constraints are not part of that sectioning conversion. Separate repository-local validators and representative synthetic XML tests do not establish official-corpus or official distribution/objective-validator agreement.
- `services/research_metrics_service.py` reports stable instance fingerprints, model scale, completion and hard-conflict counts, room fill/utilization, nominal/robust/scenario service, prime-time allocation equity, and distribution-rule performance across datasets.

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
 - **Save/Load Project** (JSON or SQLite snapshots)
 - **Compare** (diff current schedule vs a saved project; optional report export)
- **Load Instance / Load Schedule** (bring in external data)

The React administration workspace also includes a five-step setup wizard that asks for the scenario, institution policy, scheduling priorities, uncertainty posture, and final review in administrator language. It exposes the exact enabled hard checks and unresolved institutional evidence before applying a configuration.

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

### Research experiment pipeline

Generate clean primary-attempt rows and paired statistics:

```bash
.venv/bin/python scripts/run_experiments.py \
  --mode small_demo \
  --room-modes cp_rooms,decomposed,greedy \
  --seeds 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30 \
  --workers 1 --use-objective 0 --time-limit 10 \
  --retry-without-objective 0 \
  --cp-rooms-fallback-to-greedy 0 \
  --ls-iters 0 \
  --out paper/evidence/generated_feasibility_30x3_2026-08-11.jsonl
.venv/bin/python scripts/run_experiments.py \
  --mode small_demo \
  --room-modes cp_rooms,decomposed,greedy \
  --seeds 31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50 \
  --workers 1 --use-objective 0 --time-limit 10 \
  --retry-without-objective 0 \
  --cp-rooms-fallback-to-greedy 0 \
  --ls-iters 0 \
  --out paper/evidence/generated_feasibility_supplement_31_50_2026-08-11.jsonl
.venv/bin/python scripts/analyze_experiments.py \
  paper/evidence/generated_feasibility_30x3_2026-08-11.jsonl \
  paper/evidence/generated_feasibility_supplement_31_50_2026-08-11.jsonl \
  --out paper/evidence/generated_feasibility_50x3_2026-08-11_analysis.json \
  --minimum-effective-instances 30 --require-publication-ready
```

The historical paper result files are explicitly quarantined in `paper/results_status.json`; their seed labels did not identify distinct instances and their strict-room timings mixed retries/fallbacks. The current checked-in study preserves two content-hashed shards and passes the generated-feasibility gate with 37--38 effective instances per condition under a separate repository-local post-solve validator; it supports a generated feasibility-latency comparison only, not a quality or external superiority claim. The raw rows record a base Git revision and `git_dirty=true`, but no file-by-file manifest of that dirty tree, so their checksums protect the result artifacts without fully reconstructing the executed source snapshot.

External benchmark and disruption entry points are `scripts/import_external_benchmark.py`, `scripts/benchmark_itc2007.py`, and `scripts/run_disruption_experiments.py`. Every comparative ITC-2007 result must retain the official validator output; an internally scored schedule alone is not benchmark evidence.

The official ITC-2007 rescue breadth report is `reports/itc2007_breadth_21_rescue_seed17_2026-08-11.json` (SHA-256 `50adfe6ccc8add2e7e9225f8268c430331153bdb8244826eec125ad5716ea385`): Planora is officially feasible with internal/official component parity on 21/21 instances, but CPSolver wins 21/21 and the aggregate objective is 20,170 versus 3,586. The corrected room-dive evidence is summarized in `reports/itc2007_fixed_time_room_dive_breadth_final_v2_seed17_2026-08-11.json` (SHA-256 `24fccbf81d78a1371d625f42c94e1ff1b7d8e841633874ddb788a552d7146be6`) and backed by `output/itc2007-room-dive-breadth-seed17-counterbalanced-final-v2/matrix_index.json` (SHA-256 `aba9413209699d2eff0db431f90e971dea3dada0e675420f3d9cefeb6bc8f2f4`, source SHA-256 `a63732de42d9e0053ea196f46a410024b85c006e4cc6d7f91e5529f3bd1294cb`). All 42 OFF/ON runs are official-valid, component-matched, source-stable, and within the strict total deadline. ON is better on three pairs, tied on 18, worse on none, and totals 19,870 versus 20,457 OFF (-2.869%); only `comp01` contains an accepted direct dive gain (-246). Of 21 ON runs, 13 attempted the dive, one accepted, 12 returned no accepted improvement, and eight skipped it. CPSolver still wins all 21, and the ON total is 5.541 times CPSolver's 3,586 total. The feature remains disabled by default because this is single-seed evidence with no competitor superiority. Source stability is internal to that frozen report and matrix: `a63732de…` predates the later repeat-week greedy-to-decomposed correctness-only change, so they are immutable historical evidence rather than evidence for the exact current checkout.

The preceding breadth run is retained as a negative gate in `reports/itc2007_fixed_time_room_dive_breadth_seed17_2026-08-11.json` (SHA-256 `43560980d667a5495dda0b597ae4942f4e355ed94ec041dbdb0fcd3cd2d912d7`): although its reported ON/OFF sums were 19,711/20,360, seven ON runs exceeded the strict total deadline and two pairs worsened. It is provenance, not pooled evidence for the corrected result.

For a full local product-path benchmark, including strict validation and portable metrics:

```bash
.venv/bin/python scripts/benchmark_local_app.py \
  --mode giu_target --room-mode partitioned \
  --time-limit 30 --workers 4 --seed 1 \
  --out data/giu-partitioned-benchmark.json
```

For the current controlled 3,888-activity distribution, use `scripts/benchmark_end_to_end_performance.py`. The checked-in five-run evidence covers embedded Python, fresh-process HTTP, and a persistent HTTP service through the same application backend; medians are 17.668 s, 28.080 s, and 6.234 s respectively. The persistent result benefits from the exact shared solve cache. Full methods, stage timings, and limitations are in `docs/PERFORMANCE_3888_2026-08-14.md`; `paper/engineering_smoke_2026-08-11.json` remains older regression provenance.

Freeze a release artifact bundle (commit + environment + checksums + paper inputs):

```bash
PYTHON_BIN=.venv/bin/python ./scripts/freeze_release_artifacts.sh v1.0-rc-20260811-a
./scripts/verify_release_artifact.sh release/v1.0-rc-20260811-a
```

Use a new identifier for every freeze: the workflow is immutable and refuses to overwrite an existing release directory. The checked-in `release/v1.0` predates the current solver, wizard, calibration, security, and research changes and is not the current release candidate.

The freezer fails before creating the snapshot unless `paper/main.pdf` is a valid canonical PDF newer than every bundled TeX/Bib source and the full CI run has emitted `cover/critical-coverage-source-manifest.json`. Verification requires the coverage report, source manifest, per-file ratchets, and category ratchets to match the exact protected-file scope declared in `pyproject.toml`; it then replays that source binding, the latest 21-instance rescue evidence, and every nested record/hash in the corrected final-v2 room matrix. It also packages the CB-CTT and ITC-2019 provenance metadata without vendoring their source corpora. A verified bundle retains the hardening ledger's `NO-GO` while any current evidence still records an open requirement, external blocker, or failed external-quality boundary.

## Notes / current limitations

- The built-in generator focuses on `LEC_TUT` and `LAB_ONLY` course patterns; other structure types can be added by extending `generator.py`.
- Data import is file-based (JSON/SQLite/CSV); schedules are validated against hard rules on load. Legacy pickle files are intentionally rejected because deserializing them can execute arbitrary code; migrate them only in an isolated, trusted offline environment.
- Comparison reporting is summary-only (no side-by-side visualization).
- Official ITC-2007 validation now covers two fresh complete 42-row paired passes. Planora has the lower mean objective in both, while seven changing instance winners prohibit a deterministic or general superiority claim; the next research gate is a prespecified multi-seed design. Authenticated ITC-2019 validation is operational: the four-way `lums-sum17` smoke agreed 4/4, and the three complete valid outputs from the 120-run competition matrix agreed 3/3. Effective 30-instance coverage remains open because 117 nominal-budget conditions emitted no complete valid output. Current GIU institutional sign-off also remains external; local validation or extrapolation cannot close it.
- The selected post-incumbent evidence ledger is `paper/evidence/selected_post_incumbent_quality_2026-08-13.json`. It binds four CTT and one Exam result to incumbent/output/comparator/source hashes, while explicitly excluding incumbent construction, equal-runtime comparison, and any corpus-wide superiority claim.
- The narrowed mathematical construction and proof-reuse pipeline are research hypotheses. The checked-in systematic review explicitly records prior work that subsumes broad decomposition, Hall-cut, explanation-guided LNS, and bandit-selection claims.
- A repository-local formal security equivalent and an authorized desktop/mobile Edge accessibility pass are complete. Deployment-layer security and the two external authority gates above remain outside this checkout, so local engineering is ready for handoff but the institutional/official release decision remains fail-closed.

## License

This project is licensed under the GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later). See `LICENSE`.
