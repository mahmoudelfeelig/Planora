from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from benchmarks import itc2019_competitor_build_admission as admission
from benchmarks.itc2019_competitor_build_admission import (
    BuildAdmissionError,
    build_build_admission_manifest,
    verify_build_admission_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "benchmarks" / "competitor_packages"
POLICY = PACKAGE_ROOT / "build-admission-policy.json"
MANIFEST = PACKAGE_ROOT / "build-admission-manifest.json"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _mutated_policy(tmp_path: Path, mutate) -> Path:
    payload = copy.deepcopy(_load(POLICY))
    mutate(payload)
    return _write_json(tmp_path / "policy.json", payload)


def test_live_manifest_verifies_and_is_fail_closed() -> None:
    result = verify_build_admission_manifest(
        MANIFEST,
        policy_path=POLICY,
        repo_root=ROOT,
    )

    assert result["schema"] == admission.MANIFEST_SCHEMA
    assert result["status"] == admission.STATUS
    assert result["custody_binding_sha256"] == admission.CUSTODY_BINDING_SHA256
    assert result["claim_boundary"] == {
        "scope": admission.CLAIM_SCOPE,
        "build_ready": False,
        "claim_grade_ready": False,
        "performance_claims_authorized": False,
        "statement": (
            "This admission policy specifies evidence required for later "
            "deterministic offline builds. It does not attest that any dependency "
            "closure, toolchain, recipe, adapter, build receipt, binary, image, "
            "license review, or matched-resource control exists or has passed review."
        ),
    }
    assert result["global_gates"] == {
        "license_review_ready": False,
        "matched_resources_ready": False,
    }
    for solver in result["solvers"]:
        assert solver["admission"] and not any(solver["admission"].values())


def test_live_manifest_exactly_matches_a_fresh_build() -> None:
    assert _load(MANIFEST) == build_build_admission_manifest(POLICY, repo_root=ROOT)


def test_two_fresh_builds_have_identical_canonical_bytes() -> None:
    first = build_build_admission_manifest(POLICY, repo_root=ROOT)
    second = build_build_admission_manifest(POLICY, repo_root=ROOT)

    assert first == second
    assert admission._manifest_bytes(first) == admission._manifest_bytes(second)
    canonical = {key: value for key, value in first.items() if key != "binding_sha256"}
    assert first["binding_sha256"] == admission._json_sha256(canonical)


def test_all_reviewed_contracts_are_exactly_bound() -> None:
    manifest = build_build_admission_manifest(POLICY, repo_root=ROOT)
    expected = [
        {"role": role, "path": path, "size_bytes": size, "sha256": digest}
        for role, path, size, digest in admission.REVIEWED_CONTRACTS
    ]

    assert manifest["reviewed_contracts"] == expected
    for record in expected:
        path = ROOT / record["path"]
        assert path.stat().st_size == record["size_bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_all_immutable_source_archives_are_exactly_bound() -> None:
    manifest = build_build_admission_manifest(POLICY, repo_root=ROOT)
    observed = {
        entry["solver"]: entry["source_archives"] for entry in manifest["solvers"]
    }

    assert list(observed) == ["gashi-sa", "unitime-cpsolver", "lemos-maxsat"]
    assert [item["role"] for item in observed["unitime-cpsolver"]] == [
        "primary",
        "required-source-dependency",
    ]
    for sources in observed.values():
        for source in sources:
            path = ROOT / source["path"]
            assert path.stat().st_size == source["size_bytes"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]


def test_policy_pins_harness_adapter_interfaces() -> None:
    policy = _load(POLICY)
    for solver in policy["solvers"]:
        assert solver["adapter_output_contract"]["argv_template"] == list(
            admission.ARGV_CONTRACTS[solver["solver"]]
        )
    assert "{seed}" not in admission.ARGV_CONTRACTS["lemos-maxsat"]


def test_policy_records_every_required_build_gate() -> None:
    policy = _load(POLICY)
    for solver in policy["solvers"]:
        assert solver["toolchain_dependency_closure"]["status"] == admission.NOT_READY
        assert solver["deterministic_recipe_contract"]["status"] == admission.NOT_READY
        assert solver["adapter_output_contract"]["status"] == admission.NOT_READY
        assert solver["build_receipt_contract"]["status"] == admission.NOT_READY
        assert solver["artifact_digest_replay"]["status"] == admission.NOT_READY
        assert solver["build_receipt_contract"]["schema"].endswith("build-receipt.v2")
    assert policy["global_gates"]["license_review"]["status"] == admission.NOT_READY
    assert policy["global_gates"]["matched_resources"]["status"] == admission.NOT_READY


def test_cli_verify_output_is_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    assert admission._main([]) == 0
    first = capsys.readouterr()
    assert admission._main([]) == 0
    second = capsys.readouterr()

    assert first == second
    payload = json.loads(first.out)
    assert payload["build_ready"] is False
    assert payload["claim_grade_ready"] is False
    assert payload["performance_claims_authorized"] is False


def test_strict_json_rejects_duplicate_members() -> None:
    with pytest.raises(BuildAdmissionError, match="duplicate member"):
        admission._strict_json_bytes(b'{"schema":"one","schema":"two"}', "hostile")


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_strict_json_rejects_nonstandard_constants(constant: str) -> None:
    with pytest.raises(BuildAdmissionError, match="non-standard constant"):
        admission._strict_json_bytes(
            f'{{"value":{constant}}}'.encode(),
            "hostile",
        )


def test_strict_json_rejects_invalid_utf8() -> None:
    with pytest.raises(BuildAdmissionError, match="strict UTF-8 JSON"):
        admission._strict_json_bytes(b'{"value":"\xff"}', "hostile")


@pytest.mark.parametrize(
    "value",
    [
        "../outside",
        "inside/../outside",
        "./inside",
        "/absolute",
        "C:/absolute",
        "inside\\windows",
        "inside//duplicate",
        "inside/./dot",
        "inside\x00suffix",
        "",
    ],
)
def test_hostile_paths_are_rejected(value: str) -> None:
    with pytest.raises(BuildAdmissionError):
        admission._normalized_relative_path(value, "hostile path")


def test_policy_rejects_custody_binding_tamper(tmp_path: Path) -> None:
    policy = _mutated_policy(
        tmp_path,
        lambda payload: payload.update({"custody_binding_sha256": "0" * 64}),
    )
    with pytest.raises(BuildAdmissionError, match="custody binding"):
        build_build_admission_manifest(policy, repo_root=ROOT)


def test_policy_rejects_reviewed_contract_hash_tamper(tmp_path: Path) -> None:
    policy = _mutated_policy(
        tmp_path,
        lambda payload: payload["reviewed_contracts"][0].update({"sha256": "0" * 64}),
    )
    with pytest.raises(BuildAdmissionError, match="contract set or identity"):
        build_build_admission_manifest(policy, repo_root=ROOT)


def test_policy_rejects_source_archive_tamper(tmp_path: Path) -> None:
    policy = _mutated_policy(
        tmp_path,
        lambda payload: payload["solvers"][0]["source_archives"][0].update(
            {"size_bytes": 1}
        ),
    )
    with pytest.raises(BuildAdmissionError, match="immutable source inputs"):
        build_build_admission_manifest(policy, repo_root=ROOT)


def test_policy_rejects_any_ready_claim(tmp_path: Path) -> None:
    policy = _mutated_policy(
        tmp_path,
        lambda payload: payload["claim_boundary"].update({"build_ready": True}),
    )
    with pytest.raises(BuildAdmissionError, match="explicitly false"):
        build_build_admission_manifest(policy, repo_root=ROOT)


def test_policy_rejects_gate_status_upgrade(tmp_path: Path) -> None:
    policy = _mutated_policy(
        tmp_path,
        lambda payload: payload["solvers"][0]["toolchain_dependency_closure"].update(
            {"status": "READY"}
        ),
    )
    with pytest.raises(BuildAdmissionError, match="fail-closed"):
        build_build_admission_manifest(policy, repo_root=ROOT)


def test_policy_rejects_solver_reordering(tmp_path: Path) -> None:
    def reverse(payload: dict[str, object]) -> None:
        payload["solvers"].reverse()

    policy = _mutated_policy(tmp_path, reverse)
    with pytest.raises(BuildAdmissionError, match="solver order"):
        build_build_admission_manifest(policy, repo_root=ROOT)


def test_policy_rejects_adapter_argv_drift(tmp_path: Path) -> None:
    policy = _mutated_policy(
        tmp_path,
        lambda payload: payload["solvers"][0]["adapter_output_contract"][
            "argv_template"
        ].append("--extra"),
    )
    with pytest.raises(BuildAdmissionError, match="argv contract"):
        build_build_admission_manifest(policy, repo_root=ROOT)


def test_policy_rejects_future_evidence_path_traversal(tmp_path: Path) -> None:
    policy = _mutated_policy(
        tmp_path,
        lambda payload: payload["solvers"][0]["build_receipt_contract"].update(
            {"receipt_path": "../receipt.json"}
        ),
    )
    with pytest.raises(BuildAdmissionError, match="inside the repository"):
        build_build_admission_manifest(policy, repo_root=ROOT)


def test_manifest_tamper_is_rejected(tmp_path: Path) -> None:
    payload = _load(MANIFEST)
    payload["status"] = "READY"
    candidate = _write_json(tmp_path / "manifest.json", payload)

    with pytest.raises(BuildAdmissionError, match="manifest drifted"):
        verify_build_admission_manifest(
            candidate,
            policy_path=POLICY,
            repo_root=ROOT,
        )


def test_manifest_bool_integer_type_confusion_is_rejected(tmp_path: Path) -> None:
    payload = _load(MANIFEST)
    payload["claim_boundary"]["build_ready"] = 0
    candidate = _write_json(tmp_path / "manifest.json", payload)

    with pytest.raises(BuildAdmissionError, match="manifest drifted"):
        verify_build_admission_manifest(
            candidate,
            policy_path=POLICY,
            repo_root=ROOT,
        )


def test_manifest_duplicate_member_is_rejected(tmp_path: Path) -> None:
    candidate = tmp_path / "manifest.json"
    candidate.write_text('{"schema":"one","schema":"two"}', encoding="utf-8")

    with pytest.raises(BuildAdmissionError, match="duplicate member"):
        verify_build_admission_manifest(
            candidate,
            policy_path=POLICY,
            repo_root=ROOT,
        )


def test_attestation_rejects_content_tamper(tmp_path: Path) -> None:
    path = tmp_path / "artifact"
    path.write_bytes(b"trusted")
    record = {
        "path": "artifact",
        "size_bytes": len(b"trusted"),
        "sha256": hashlib.sha256(b"trusted").hexdigest(),
    }
    path.write_bytes(b"changed")

    with pytest.raises(BuildAdmissionError, match="does not match"):
        admission._attest_bound_file(tmp_path, record, "artifact")


def test_attestation_rejects_hard_links(tmp_path: Path) -> None:
    target = tmp_path / "target"
    alias = tmp_path / "alias"
    target.write_bytes(b"content")
    try:
        os.link(target, alias)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")

    with pytest.raises(BuildAdmissionError, match="single-name"):
        admission._attest_regular(target, "hard-linked artifact")


def test_attestation_rejects_symbolic_links(tmp_path: Path) -> None:
    target = tmp_path / "target"
    link = tmp_path / "link"
    target.write_bytes(b"content")
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symbolic links unavailable: {exc}")

    with pytest.raises(BuildAdmissionError, match="single-name"):
        admission._attest_regular(link, "symbolic-linked artifact")


def test_replay_rejects_byte_identical_replacement(tmp_path: Path) -> None:
    path = tmp_path / "artifact"
    path.write_bytes(b"content")
    tracked = admission._attest_regular(path, "artifact")
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"content")
    os.replace(replacement, path)

    with pytest.raises(BuildAdmissionError, match="changed during replay"):
        admission._replay([tracked])


def test_exact_json_comparison_distinguishes_bool_and_integer() -> None:
    assert admission._json_values_match_exactly(False, False)
    assert not admission._json_values_match_exactly(False, 0)
    assert not admission._json_values_match_exactly({"ready": False}, {"ready": 0})


def test_policy_and_manifest_are_single_name_regular_files() -> None:
    for path in (POLICY, MANIFEST):
        assert path.is_file()
        assert not path.is_symlink()
        assert path.stat().st_nlink == 1


def test_module_has_no_build_or_execution_facility() -> None:
    source = Path(admission.__file__).read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "import tarfile" not in source
    assert "import docker" not in source
    assert "os.system" not in source
