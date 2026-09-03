from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from services.application_service import (
    improve_options_from_payload,
    solve_options_from_payload,
)
from utils.exporter import _ics_event, _ics_header
from utils.generator import generate_instance


ROOT = Path(__file__).resolve().parent.parent


def test_remote_solver_options_are_server_bounded():
    inst = generate_instance("small_demo")
    with pytest.raises(ValueError, match="time_limit_seconds"):
        solve_options_from_payload(inst, {"options": {"time_limit_seconds": 121}})
    with pytest.raises(ValueError, match="workers"):
        solve_options_from_payload(inst, {"options": {"workers": 17}})
    with pytest.raises(ValueError, match="iterations"):
        improve_options_from_payload({"options": {"iterations": 10_001}})
    with pytest.raises(ValueError, match="max_seconds"):
        improve_options_from_payload({"options": {"max_seconds": 31}})

    assert solve_options_from_payload(
        inst, {"options": {"time_limit_seconds": 120, "workers": 16}}
    ).workers == 16
    assert improve_options_from_payload(
        {"options": {"iterations": 10_000, "max_seconds": 30}}
    ).iterations == 10_000


def test_ics_text_is_escaped_and_folded_without_property_injection():
    value = "Course, One; Room\\A\r\nBEGIN:VEVENT\r\nSUMMARY:Injected"
    text = _ics_header(value) + "\n" + _ics_event(
        "uid\nX-ALT:bad",
        value,
        datetime(2026, 1, 1, 8, 30),
        datetime(2026, 1, 1, 10, 0),
        location=value,
        description=value * 4,
    )

    assert "\nBEGIN:VEVENT\nSUMMARY:Injected" not in text
    unfolded = text.replace("\r\n ", "")
    assert "Course\\, One\\; Room\\\\A\\nBEGIN:VEVENT\\nSUMMARY:Injected" in unfolded
    for line in text.splitlines():
        assert len(line.encode("utf-8")) <= 75


def test_project_import_does_not_restore_trusted_runtime_paths():
    source = (ROOT / "ui/window_io.py").read_text(encoding="utf-8")
    load_start = source.index("def on_load_project")
    load_body = source[load_start:]
    assert "import_export_template_store_path" not in load_body
    assert "save_runtime_settings" not in load_body


def test_http_server_has_bounded_io_streaming_and_solver_admission():
    source = (ROOT / "api/server.py").read_text(encoding="utf-8")
    assert "PLANORA_HTTP_IO_TIMEOUT_SECONDS" in source
    assert "PLANORA_MAX_SSE_DURATION_SECONDS" in source
    assert "PLANORA_MAX_SSE_STREAMS_PER_USER" in source
    assert "PLANORA_MAX_SYNC_SOLVER_REQUESTS_PER_TENANT" in source
    assert "with _solver_admission(principal):" in source
