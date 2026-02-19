from __future__ import annotations

from pathlib import Path
import json

from utils.compare import write_comparison_report


def test_write_comparison_report_json(tmp_path: Path):
    summary = {
        "shared": 1,
        "missing_in_other": [],
        "missing_in_base": [],
        "changed_time": 0,
        "changed_day": 0,
        "changed_slot": 0,
        "changed_room": 0,
        "changed_staff": 0,
    }
    out = tmp_path / "report.json"
    write_comparison_report(out, summary)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["shared"] == 1


def test_write_comparison_report_csv(tmp_path: Path):
    summary = {
        "shared": 2,
        "missing_in_other": [1],
        "missing_in_base": [],
        "changed_time": 1,
        "changed_day": 1,
        "changed_slot": 0,
        "changed_room": 0,
        "changed_staff": 0,
    }
    out = tmp_path / "report.csv"
    write_comparison_report(out, summary)
    text = out.read_text(encoding="utf-8")
    assert "metric,value" in text
    assert "shared,2" in text
