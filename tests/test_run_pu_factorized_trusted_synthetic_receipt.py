from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "run_pu_factorized_trusted_synthetic_receipt.py"


def _load_runner():
    module_name = "planora_pu_factorized_trusted_synthetic_runner_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_import_does_not_import_project_modules() -> None:
    before = {name for name in sys.modules if name.startswith("benchmarks")}
    _load_runner()
    after = {name for name in sys.modules if name.startswith("benchmarks")}
    assert after == before


def test_create_only_publication_never_replaces_destination(tmp_path: Path) -> None:
    runner = _load_runner()
    destination = tmp_path / "receipt.json"
    runner._publish_bytes_create_only(destination, b"first")

    with pytest.raises(FileExistsError):
        runner._publish_bytes_create_only(destination, b"second")

    assert destination.read_bytes() == b"first"


def test_claim_read_failure_is_caught_after_claim_and_receipted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    claim_path = tmp_path / "claim.json"
    receipt_path = tmp_path / "receipt.json"
    monkeypatch.setattr(runner, "CLAIM_PATH", claim_path)
    monkeypatch.setattr(runner, "RECEIPT_PATH", receipt_path)
    monkeypatch.setattr(runner, "EXPECTED_SOURCE_SHA256", {})

    original_sha256 = runner._sha256

    def fail_claim_read(path: Path) -> str:
        if path == claim_path:
            raise OSError("injected claim read failure")
        return original_sha256(path)

    monkeypatch.setattr(runner, "_sha256", fail_claim_read)

    with pytest.raises(OSError, match="injected claim read failure"):
        runner.main()

    assert claim_path.is_file()
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["outcome"] == "ERROR"
    assert receipt["error"]["type"] == "builtins.OSError"
    assert (
        receipt["claim_sha256"] == hashlib.sha256(claim_path.read_bytes()).hexdigest()
    )


def test_error_receipt_replays_and_records_runner_hash(tmp_path: Path) -> None:
    runner = _load_runner()
    script_path = tmp_path / "reviewed-runner.py"
    script_path.write_bytes(b"observed runner bytes")
    receipt_path = tmp_path / "receipt.json"
    monkeypatch_values = {
        "SCRIPT_PATH": script_path,
        "RECEIPT_PATH": receipt_path,
        "CLAIM_PATH": tmp_path / "claim.json",
        "EXPECTED_SOURCE_SHA256": {},
    }
    for name, value in monkeypatch_values.items():
        setattr(runner, name, value)

    expected_before = hashlib.sha256(b"different reviewed bytes").hexdigest()
    runner._publish_post_claim_error(
        claim_sha256="0" * 64,
        script_sha256=expected_before,
        started_at=datetime.now(timezone.utc),
        error=RuntimeError("injected"),
    )

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert (
        receipt["postflight_script_sha256"]
        == hashlib.sha256(script_path.read_bytes()).hexdigest()
    )
    assert receipt["postflight_script_match"] is False


def test_receipt_metadata_does_not_claim_unbound_probe_count() -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert '"independent_adversarial_probes_passed"' not in source
    assert "NOT_BOUND_TO_A_WORKSPACE_ARTIFACT_NOT_USED_FOR_AUTHORIZATION" in source
