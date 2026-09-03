from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path, PurePosixPath

import pytest


ROOT = Path(__file__).resolve().parents[1]
FINAL_MATRIX = "itc2007-room-dive-breadth-seed17-counterbalanced-final-v2"
MODERN_MATRIX = "itc2007-factorial-release-contract-fixture"
OUTPUT_FIXTURES = (
    "itc2007-ablation-comp01-adaptive-seeding-off-idle-10s",
    "itc2007-ablation-comp01-adaptive-seeding-on-idle-10s",
    "itc2007-breadth-21-candidate-vs-cpsolver-10s-seed17",
    "itc2007-breadth-21-planora-rescue-seed17-10s",
    FINAL_MATRIX,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _write_modern_matrix_fixture(repo: Path) -> None:
    matrix_root = repo / "output" / MODERN_MATRIX
    matrix_root.mkdir(parents=True)
    (matrix_root / "manifest.json").write_text("{}\n", encoding="utf-8")
    (matrix_root / "results.jsonl").write_text('{"fixture": true}\n', encoding="utf-8")
    (matrix_root / "summary.json").write_text(
        json.dumps(
            {
                "complete": True,
                "record_count": 1,
                "completed_runs": 1,
                "planned_runs": 1,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts = [
        {"path": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}
        for path in sorted(matrix_root.iterdir())
        if path.is_file()
    ]
    (matrix_root / "matrix-index.json").write_text(
        json.dumps(
            {
                "schema_version": "planora.itc2007-factorial-ablation-index.v1",
                "complete": True,
                "source_snapshot_sha256": "f" * 64,
                "record_count": 1,
                "artifact_count": len(artifacts),
                "artifacts": artifacts,
                "artifact_set_sha256": _canonical_sha256(artifacts),
                "self_exclusion": "matrix-index.json is excluded to avoid a circular digest",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _stage_release_source(destination: Path) -> Path:
    missing_output_fixtures = [
        directory
        for directory in OUTPUT_FIXTURES
        if not (ROOT / "output" / directory).is_dir()
    ]
    if missing_output_fixtures:
        pytest.skip(
            "local release-evidence fixtures are unavailable: "
            + ", ".join(missing_output_fixtures)
        )
    repo = destination / "repo"
    repo.mkdir()
    for directory in (
        "api",
        "benchmarks",
        "connectors",
        "config",
        "core",
        "cover",
        "docs",
        "paper",
        "product",
        "reports",
        "scripts",
        "services",
        "tests",
        "ui",
        "utils",
    ):
        shutil.copytree(
            ROOT / directory,
            repo / directory,
            ignore=shutil.ignore_patterns("__pycache__", ".ruff_cache", "build"),
        )
    for relative in (
        "FEATURES.MD",
        "LICENSE",
        "README.md",
        "SPECS.md",
        "main.py",
        "pyproject.toml",
        "requirements-dev.txt",
        "requirements.txt",
    ):
        _copy_file(ROOT / relative, repo / relative)
    for directory in ("web/src", "web/public"):
        shutil.copytree(ROOT / directory, repo / directory)
    for relative in (
        "web/eslint.config.js",
        "web/index.html",
        "web/package-lock.json",
        "web/package.json",
        "web/playwright.config.ts",
        "web/tsconfig.json",
        "web/vite.config.ts",
    ):
        _copy_file(ROOT / relative, repo / relative)
    for directory in OUTPUT_FIXTURES:
        shutil.copytree(ROOT / "output" / directory, repo / "output" / directory)
    _write_modern_matrix_fixture(repo)
    for relative in (
        "data/external/cbctt-ea30189c5e3a/PROVENANCE.json",
        "data/external/cbctt-ea30189c5e3a/PROVENANCE.sha256",
        "data/external/cbctt-ea30189c5e3a/OFFICIAL_VALIDATOR_COMPATIBILITY.json",
        "data/external/itc2019-mpp-c33d15797686/PROVENANCE.json",
    ):
        _copy_file(ROOT / relative, repo / relative)

    # The repository may intentionally be between paper/coverage freezes while
    # this focused contract test runs. The isolated fixture represents the
    # post-CI state without mutating or mislabeling the real checkout.
    now = time.time()
    for source in (repo / "paper").rglob("*"):
        if source.is_file() and source.suffix.lower() in {".tex", ".bib"}:
            os.utime(source, (now - 10.0, now - 10.0))
    os.utime(repo / "paper/main.pdf", (now, now))

    coverage_path = repo / "cover/critical-coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    baseline_path = repo / "config/critical_coverage_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    project = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    configured_sources = project["tool"]["coverage"]["report"]["include"]
    staged_coverage_files = {}
    staged_baseline_files = {}
    for relative in configured_sources:
        staged_coverage_files[relative] = coverage["files"].get(
            relative,
            {
                "summary": {
                    "num_statements": 1,
                    "covered_lines": 1,
                    "missing_lines": 0,
                    "excluded_lines": 0,
                    "percent_covered": 100.0,
                    "percent_covered_display": "100",
                    "num_branches": 0,
                    "num_partial_branches": 0,
                    "covered_branches": 0,
                    "missing_branches": 0,
                }
            },
        )
        staged_baseline_files[relative] = baseline["files"].get(
            relative,
            {
                "minimum_line_percent": 100.0,
                "minimum_branch_percent": 100.0,
                "fixture_note": "isolated release-contract fixture",
            },
        )
    coverage["files"] = staged_coverage_files
    baseline["files"] = staged_baseline_files
    configured_source_set = set(configured_sources)
    staged_categories = {}
    categorized_sources: set[str] = set()
    for category_name, category in baseline["categories"].items():
        staged_files = [
            relative
            for relative in category["files"]
            if relative in configured_source_set
        ]
        if not staged_files:
            continue
        staged_category = dict(category)
        staged_category["files"] = staged_files
        staged_categories[category_name] = staged_category
        categorized_sources.update(staged_files)
    missing_category_sources = sorted(configured_source_set - categorized_sources)
    if missing_category_sources:
        staged_categories["release_contract_expanded_scope"] = {
            "files": missing_category_sources,
            "minimum_line_percent": 100.0,
            "minimum_branch_percent": 100.0,
            "fixture_note": "isolated release-contract fixture",
        }
    baseline["categories"] = staged_categories
    coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    baseline_path.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")

    source_rows = []
    for relative in sorted(coverage["files"]):
        path = repo.joinpath(*PurePosixPath(relative).parts)
        source_rows.append(
            {"path": relative, "sha256": _sha256(path), "bytes": path.stat().st_size}
        )
    xml_path = repo / "cover/critical-coverage.xml"
    coverage_manifest = {
        "schema_version": "planora.critical-coverage-source-manifest.v1",
        "generated_at_utc": "2026-08-11T00:00:00+00:00",
        "coverage_json": {
            "path": "cover/critical-coverage.json",
            "sha256": _sha256(coverage_path),
            "bytes": coverage_path.stat().st_size,
        },
        "coverage_xml": {
            "path": "cover/critical-coverage.xml",
            "sha256": _sha256(xml_path),
            "bytes": xml_path.stat().st_size,
        },
        "source_files": source_rows,
        "source_file_count": len(source_rows),
        "source_set_sha256": _canonical_sha256(source_rows),
    }
    (repo / "cover/critical-coverage-source-manifest.json").write_text(
        json.dumps(coverage_manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return repo


def _run_freezer(
    repo: Path, release_root: Path, version: str
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(
        {
            "GIT_DIR": str(ROOT / ".git"),
            "GIT_WORK_TREE": str(repo),
            "PLANORA_RELEASE_ROOT": str(release_root),
            "PYTHON_BIN": sys.executable,
        }
    )
    return subprocess.run(
        ["bash", "scripts/freeze_release_artifacts.sh", version],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _rewrite_outer_checksum(artifact: Path, relative: str) -> None:
    checksum_path = artifact / "SHA256SUMS"
    suffix = f"  ./{relative}"
    target = artifact / relative
    checksum_path.write_text(
        "\n".join(
            f"{_sha256(target)}{suffix}" if row.endswith(suffix) else row
            for row in checksum_path.read_text(encoding="utf-8").splitlines()
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def frozen_release(tmp_path_factory: pytest.TempPathFactory) -> Path:
    workspace = tmp_path_factory.mktemp("release-contract")
    repo = _stage_release_source(workspace)
    release_root = workspace / "releases"
    result = _run_freezer(repo, release_root, "test-release")
    assert result.returncode == 0, result.stderr
    return release_root / "test-release"


def test_frozen_release_preserves_paper_tree_and_verifies(
    frozen_release: Path,
) -> None:
    artifact = frozen_release
    assert (artifact / "paper/main.pdf").is_file()
    assert (
        artifact / "paper/evidence/itc2007_support_proxy_comp10_2026-08-13.json"
    ).is_file()
    assert (
        artifact
        / "paper/evidence/selected_post_incumbent_quality_2026-08-13.json"
    ).is_file()
    assert (artifact / "paper/sections/01_introduction.tex").is_file()
    assert (artifact / "api/http.py").is_file()
    assert (artifact / "api/rate_limit.py").is_file()
    assert (artifact / "core/fixed_time_room_oracle.py").is_file()
    assert (artifact / "core/fixed_time_room_proof_checker.py").is_file()
    assert (artifact / "services/teaching_load_import_service.py").is_file()
    assert (artifact / "utils/io.py").is_file()
    assert (artifact / "benchmarks/cbctt_corpus.py").is_file()
    assert (artifact / "benchmarks/itc2019_corpus.py").is_file()
    assert (
        artifact / "paper/evidence/itc2019_public_mirror_validation_2026-08-11.json"
    ).is_file()
    assert (
        artifact / "reports/itc2007_breadth_21_rescue_seed17_2026-08-11.json"
    ).is_file()
    assert (
        artifact
        / "reports/itc2007_fixed_time_room_dive_breadth_final_v2_seed17_2026-08-11.json"
    ).is_file()
    assert (artifact / "output" / FINAL_MATRIX / "matrix_index.json").is_file()
    assert (artifact / "output" / FINAL_MATRIX / "comp21-on/results.jsonl").is_file()
    assert (artifact / "output" / MODERN_MATRIX / "matrix-index.json").is_file()
    assert (artifact / "cover/critical-coverage-source-manifest.json").is_file()
    assert (artifact / "cover/critical-coverage-full-local.json").is_file()
    assert (artifact / "cover/critical-coverage-ci-portable.json").is_file()

    ledger = json.loads(
        (artifact / "reports/hardening_ledger.json").read_text(encoding="utf-8")
    )
    metadata = dict(
        line.split("=", 1)
        for line in (artifact / "release-metadata.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert metadata["schema_version"] == "2"
    assert (
        metadata["research_release_gate"] == ledger["release_gate"]["status"] == "NO-GO"
    )
    assert metadata["external_readiness_claimed"] == "false"
    assert metadata["compiled_paper_status"] == "included_fresh"
    assert metadata["compiled_paper_sha256"] == _sha256(artifact / "paper/main.pdf")
    assert "./SHA256SUMS" not in (artifact / "SHA256SUMS").read_text(encoding="utf-8")

    result = subprocess.run(
        ["bash", "scripts/verify_release_artifact.sh", str(artifact)],
        cwd=artifact,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Research release gate: NO-GO" in result.stdout


def test_verifier_rejects_rehashed_nested_final_matrix_tamper(
    frozen_release: Path, tmp_path: Path
) -> None:
    artifact = tmp_path / "tampered-matrix"
    shutil.copytree(frozen_release, artifact)
    nested = artifact / "output" / FINAL_MATRIX / "comp01-on/summary.json"
    payload = json.loads(nested.read_text(encoding="utf-8"))
    payload["record_count"] = 2
    nested.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _rewrite_outer_checksum(artifact, nested.relative_to(artifact).as_posix())

    result = subprocess.run(
        ["bash", "scripts/verify_release_artifact.sh", str(artifact)],
        cwd=artifact,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "nested artifact hash mismatch" in result.stderr


def test_verifier_rejects_rehashed_content_addressed_matrix_tamper(
    frozen_release: Path, tmp_path: Path
) -> None:
    artifact = tmp_path / "tampered-content-addressed-matrix"
    shutil.copytree(frozen_release, artifact)
    manifest = artifact / "output" / MODERN_MATRIX / "manifest.json"
    manifest.write_text('{"tampered": true}\n', encoding="utf-8")
    _rewrite_outer_checksum(artifact, manifest.relative_to(artifact).as_posix())

    result = subprocess.run(
        ["bash", "scripts/verify_release_artifact.sh", str(artifact)],
        cwd=artifact,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "matrix-index artifact" in result.stderr


def test_verifier_rejects_rehashed_covered_source_tamper(
    frozen_release: Path, tmp_path: Path
) -> None:
    artifact = tmp_path / "tampered-source"
    shutil.copytree(frozen_release, artifact)
    source = artifact / "core/fixed_time_room_proof_checker.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    _rewrite_outer_checksum(artifact, source.relative_to(artifact).as_posix())

    result = subprocess.run(
        ["bash", "scripts/verify_release_artifact.sh", str(artifact)],
        cwd=artifact,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "covered source does not match coverage manifest" in result.stderr


def test_verifier_rejects_rehashed_selected_quality_claim_tamper(
    frozen_release: Path, tmp_path: Path
) -> None:
    artifact = tmp_path / "tampered-selected-quality"
    shutil.copytree(frozen_release, artifact)
    ledger_path = (
        artifact
        / "paper/evidence/selected_post_incumbent_quality_2026-08-13.json"
    )
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["results"][0]["post_incumbent"]["score"] = 999999
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    _rewrite_outer_checksum(artifact, ledger_path.relative_to(artifact).as_posix())

    result = subprocess.run(
        ["bash", "scripts/verify_release_artifact.sh", str(artifact)],
        cwd=artifact,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "selected post-incumbent result" in (result.stdout + result.stderr)


def test_verifier_rejects_rehashed_unmeasured_pyproject_coverage_scope(
    frozen_release: Path, tmp_path: Path
) -> None:
    artifact = tmp_path / "unmeasured-coverage-scope"
    shutil.copytree(frozen_release, artifact)
    pyproject_path = artifact / "pyproject.toml"
    contents = pyproject_path.read_text(encoding="utf-8")
    marker = '  "utils/specs.py",\n]'
    assert marker in contents
    pyproject_path.write_text(
        contents.replace(
            marker,
            '  "utils/specs.py",\n  "services/institution_policy_service.py",\n]',
            1,
        ),
        encoding="utf-8",
    )
    _rewrite_outer_checksum(artifact, "pyproject.toml")

    result = subprocess.run(
        ["bash", "scripts/verify_release_artifact.sh", str(artifact)],
        cwd=artifact,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "does not exactly match the pyproject.toml include scope" in result.stderr


def test_verifier_rejects_go_while_external_blockers_remain(
    frozen_release: Path, tmp_path: Path
) -> None:
    artifact = tmp_path / "forged-go"
    shutil.copytree(frozen_release, artifact)
    ledger_path = artifact / "reports/hardening_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["external_blockers"]
    ledger["release_gate"] = {"status": "GO", "open_requirements": []}
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

    metadata_path = artifact / "release-metadata.txt"
    metadata = dict(
        line.split("=", 1)
        for line in metadata_path.read_text(encoding="utf-8").splitlines()
    )
    metadata["research_release_gate"] = "GO"
    metadata["open_requirement_count"] = "0"
    metadata["hardening_ledger_sha256"] = _sha256(ledger_path)
    metadata_path.write_text(
        "".join(f"{key}={value}\n" for key, value in metadata.items()),
        encoding="utf-8",
    )
    _rewrite_outer_checksum(artifact, "reports/hardening_ledger.json")
    _rewrite_outer_checksum(artifact, "release-metadata.txt")

    result = subprocess.run(
        ["bash", "scripts/verify_release_artifact.sh", str(artifact)],
        cwd=artifact,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "GO hardening ledger cannot retain external blockers" in result.stderr


def test_verifier_rejects_go_while_required_evidence_remains_no_go(
    frozen_release: Path, tmp_path: Path
) -> None:
    artifact = tmp_path / "forged-evidence-go"
    shutil.copytree(frozen_release, artifact)
    ledger_path = artifact / "reports/hardening_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["external_blockers"] = []
    ledger["release_gate"] = {"status": "GO", "open_requirements": []}
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

    metadata_path = artifact / "release-metadata.txt"
    metadata = dict(
        line.split("=", 1)
        for line in metadata_path.read_text(encoding="utf-8").splitlines()
    )
    metadata["research_release_gate"] = "GO"
    metadata["open_requirement_count"] = "0"
    metadata["hardening_ledger_sha256"] = _sha256(ledger_path)
    metadata_path.write_text(
        "".join(f"{key}={value}\n" for key, value in metadata.items()),
        encoding="utf-8",
    )
    _rewrite_outer_checksum(artifact, "reports/hardening_ledger.json")
    _rewrite_outer_checksum(artifact, "release-metadata.txt")

    result = subprocess.run(
        ["bash", "scripts/verify_release_artifact.sh", str(artifact)],
        cwd=artifact,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "evidence still requires NO-GO" in result.stderr


def test_freeze_fails_closed_before_creating_snapshot_for_stale_paper(
    tmp_path: Path,
) -> None:
    repo = _stage_release_source(tmp_path)
    source = repo / "paper/main.tex"
    now = time.time() + 10.0
    os.utime(source, (now, now))
    release_root = tmp_path / "releases"

    result = _run_freezer(repo, release_root, "stale-paper")

    assert result.returncode == 1
    assert "canonical paper/main.pdf is older than paper/main.tex" in result.stderr
    assert not (release_root / "stale-paper").exists()


def test_freeze_refuses_to_overwrite_existing_snapshot(tmp_path: Path) -> None:
    artifact = tmp_path / "existing-release"
    artifact.mkdir()
    marker = artifact / "preserve-me.txt"
    marker.write_text("preserved", encoding="utf-8")
    env = dict(os.environ)
    env["PLANORA_RELEASE_ROOT"] = str(tmp_path)

    result = subprocess.run(
        ["bash", "scripts/freeze_release_artifacts.sh", "existing-release"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "refusing to overwrite immutable snapshot" in result.stderr
    assert marker.read_text(encoding="utf-8") == "preserved"
