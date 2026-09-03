# Testing Guide

## Fast Checks

Run focused UI/import checks:

```powershell
.venv\Scripts\python.exe -m pytest -q tests\test_ui_diagnostics.py tests\test_ui_import_wizard.py
```

Run import/scoring checks:

```powershell
.venv\Scripts\python.exe -m pytest -q tests\test_timetable_import_service.py
```

Run syntax checks:

```powershell
.venv\Scripts\python.exe -m py_compile ui\window.py services\timetable_import_service.py
```

## Full CI and critical-path coverage

Install the pinned development environment, then run the same entry point used by GitHub Actions from WSL or Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
PYTHON_BIN=.venv/bin/python ./scripts/run_ci_checks.sh
```

The script keeps the existing two test phases: fast feedback with `pytest -m "not slow"`, followed by tests marked `slow`. Coverage wraps those two executions and appends the second phase to the first; it does not run the entire test suite again just to obtain a percentage. Both statement and branch coverage are collected. The terminal report shows missing lines and branches for the explicitly scoped solver, authentication, persistence/tenant, and schedule-validation modules. Machine-readable JSON and Cobertura XML reports are written under `cover/`.

The same run writes `cover/critical-coverage-source-manifest.json` after the JSON and XML reports. It first requires the report to match the exact protected-file scope in `pyproject.toml`, then hashes every covered source and binds those hashes to both report files. Release verification also requires the source manifest plus the baseline's per-file and category ratchets to name that exact scope before replaying the manifest against the frozen source tree. Adding a protected boundary without fresh coverage evidence, or editing a covered file after CI, invalidates the release even if the outer bundle checksums are regenerated.

`config/critical_coverage_baseline.json` is the enforced ratchet. It records both category-level and per-file floors, the exact tool versions used to establish them, and the measurement evidence. Floors are derived by flooring a fresh observed percentage to two decimal places, never by choosing an aspirational target. A floor may be raised after deterministic tests add meaningful critical-path coverage. Lowering one requires a documented reason and fresh before/after evidence; moving code or adding untested branches is not a reason to lower it.

The normal CI phases do not deselect or suppress environment-dependent tests. Pytest's `-ra` summary keeps every skip visible. Expected environmental cases include unavailable live socket binding, missing optional Qt runtime libraries, missing `pdftotext`, and private/local GIU, SS23, workbook, or quiz fixtures. The checked-in baseline separately records the exact optional-data node IDs omitted from its CI-portable calibration measurement so local private data cannot inflate the enforced floor. Those tests still execute normally whenever their inputs exist.

Coverage is a regression signal, not a correctness claim. Solver feasibility, official-validator agreement, tenant isolation, security invariants, and real UI behavior retain their dedicated tests and release gates.

## Benchmark Report

Run a single preset:

```powershell
.venv\Scripts\python.exe scripts\benchmark_scheduler_profiles.py --mode small_demo --time-limit 20 --out data\benchmark-small.json
```

Run the curated corpus:

```powershell
.venv\Scripts\python.exe scripts\benchmark_scheduler_profiles.py --corpus --out data\benchmark-corpus.json
```

The corpus is defined in `benchmarks/corpus.py`.

## Local application performance and E2E path

Run scenario creation, product compilation, CP model construction, solve, exact rooming, extraction, strict validation, research metrics, and off-screen desktop startup in one measured path:

```powershell
.venv\Scripts\python.exe scripts\benchmark_local_app.py --mode small_demo --room-mode decomposed --time-limit 15 --out data\local-app-benchmark.json
```

The report separates stage timings, CP variables/constraints, materialized start literals, peak resident memory, validation results, and portable research metrics. Use one worker and fixed seeds for comparable research runs. Repeat seeds and report distributions rather than treating a single timing as a general performance claim.

Exercise the large-institution scale path with four independent week workers:

```powershell
.venv\Scripts\python.exe scripts\benchmark_local_app.py --mode giu_target --room-mode partitioned --time-limit 30 --workers 4 --seed 1 --out data\giu-partitioned-benchmark.json
```

The partitioned mode is feasibility-only. It checks semester totals and competencies globally, solves week-local hard constraints in parallel, validates the merged schedule, and refuses required cross-week decision constraints. Fast room assignment is accepted only after validation; a failed week is retried with exact certificate-guided room decomposition.

The matching integration guard is:

```powershell
.venv\Scripts\python.exe -m pytest -q tests\test_local_app_performance_e2e.py tests\test_general_purpose_research.py tests\test_partitioned_solver.py
```

## SS23 Import Test

Use:

```powershell
.venv\Scripts\python.exe -m pytest -q tests\test_timetable_import_service.py
```

If `data/SS23-All-Majors-Schedule-events.csv` exists, the test verifies the original imported score and hard-conflict count.

## Known Test Risk

Some OR-Tools CP-SAT tests can trigger native access violations on specific Windows/Python/OR-Tools combinations. If a process exits with a Windows access violation inside `ortools.sat.python.cp_model`, rerun the narrower test suite around the changed files and record the crash separately from Python assertion failures.
