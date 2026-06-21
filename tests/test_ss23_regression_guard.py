from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_ss23_regression_guard_script_runs_or_skips_cleanly(tmp_path):
    missing = tmp_path / "missing.csv"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/ss23_regression_guard.py",
            "--csv",
            str(missing),
            "--iterations",
            "1",
            "--max-seconds",
            "0",
        ],
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["skipped"] is True


def test_ss23_regression_guard_real_data_if_present():
    path = Path("data/SS23-All-Majors-Schedule-events.csv")
    if not path.exists():
        return
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/ss23_regression_guard.py",
            "--csv",
            str(path),
            "--iterations",
            "5",
            "--max-seconds",
            "0.2",
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["activities"] >= 1000
    assert payload["after_soft_penalty"] <= payload["before_soft_penalty"]
