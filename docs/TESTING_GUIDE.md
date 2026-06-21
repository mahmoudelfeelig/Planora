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

## SS23 Import Test

Use:

```powershell
.venv\Scripts\python.exe -m pytest -q tests\test_timetable_import_service.py
```

If `data/SS23-All-Majors-Schedule-events.csv` exists, the test verifies the original imported score and hard-conflict count.

## Known Test Risk

Some OR-Tools CP-SAT tests can trigger native access violations on specific Windows/Python/OR-Tools combinations. If a process exits with a Windows access violation inside `ortools.sat.python.cp_model`, rerun the narrower test suite around the changed files and record the crash separately from Python assertion failures.
