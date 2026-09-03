#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 RELEASE_DIRECTORY" >&2
  exit 2
fi

ARTIFACT_DIR="$(cd "$1" && pwd)"
VERIFY_PYTHON="${PYTHON_BIN:-}"
if [[ -n "${VERIFY_PYTHON}" ]]; then
  if [[ "${VERIFY_PYTHON}" == */* ]]; then
    if [[ ! -x "${VERIFY_PYTHON}" ]]; then
      VERIFY_PYTHON=""
    fi
  elif command -v "${VERIFY_PYTHON}" >/dev/null 2>&1; then
    VERIFY_PYTHON="$(command -v "${VERIFY_PYTHON}")"
  else
    VERIFY_PYTHON=""
  fi
fi
if [[ -z "${VERIFY_PYTHON}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    VERIFY_PYTHON="$(command -v python3)"
  else
    VERIFY_PYTHON="$(command -v python)"
  fi
fi

for required in \
  "SHA256SUMS" \
  "environment.txt" \
  "release-metadata.txt" \
  "ARTIFACT_README.md" \
  "README.md" \
  "FEATURES.MD" \
  "LICENSE" \
  "main.py" \
  "pyproject.toml" \
  "requirements.txt" \
  "requirements-dev.txt" \
  "paper/main.pdf" \
  "paper/main.tex" \
  "paper/metadata.tex" \
  "paper/refs.bib" \
  "paper/engineering_smoke_2026-08-11.json" \
  "paper/results_status.json" \
  "paper/evidence/generated_feasibility_30x3_2026-08-11.jsonl" \
  "paper/evidence/generated_feasibility_30x3_2026-08-11_analysis.json" \
  "paper/evidence/generated_feasibility_supplement_31_50_2026-08-11.jsonl" \
  "paper/evidence/generated_feasibility_50x3_2026-08-11_analysis.json" \
  "paper/evidence/giu_ss23_calibration.json" \
  "paper/evidence/itc2007_support_proxy_comp10_2026-08-13.json" \
  "paper/evidence/selected_post_incumbent_quality_2026-08-13.json" \
  "paper/evidence/itc2019_public_mirror_validation_2026-08-11.json" \
  "paper/sections/01_introduction.tex" \
  "paper/sections/04_rooms.tex" \
  "paper/sections/07_experiments.tex" \
  "paper/sections/08_limitations.tex" \
  "paper/sections/09_conclusion.tex" \
  "paper/sections/99_reproducibility.tex" \
  "api/http.py" \
  "api/rate_limit.py" \
  "core/solver_cp_sat.py" \
  "core/partitioned_solver.py" \
  "core/solver_factory.py" \
  "core/room_decomposition.py" \
  "core/room_proof_checker.py" \
  "core/fixed_time_room_oracle.py" \
  "core/fixed_time_room_proof_checker.py" \
  "core/adaptive_lns.py" \
  "benchmarks/cbctt.py" \
  "benchmarks/cbctt_corpus.py" \
  "benchmarks/itc2007.py" \
  "benchmarks/itc2007_ablation.py" \
  "benchmarks/itc2007_harness.py" \
  "benchmarks/itc2019.py" \
  "benchmarks/itc2019_corpus.py" \
  "product/compiler.py" \
  "services/institution_policy_service.py" \
  "services/institution_policy_readiness_service.py" \
  "services/research_metrics_service.py" \
  "services/teaching_load_import_service.py" \
  "utils/demand.py" \
  "utils/distribution_constraints.py" \
  "utils/io.py" \
  "scripts/benchmark_local_app.py" \
  "scripts/calibrate_giu_preset.py" \
  "scripts/fetch_cbctt_corpus.py" \
  "scripts/fetch_itc2019_public_corpus.py" \
  "scripts/validate_cbctt_projection_compatibility.py" \
  "docs/CBCTT_EXTERNAL_CORPUS.md" \
  "docs/GIU_INSTITUTIONAL_VALIDATION_PROTOCOL.md" \
  "docs/INSTITUTION_POLICY_PORTABILITY.md" \
  "docs/ITC2007_BENCHMARK_PROTOCOL.md" \
  "docs/ITC2019_PUBLIC_CORPUS.md" \
  "paper/novelty_review.md" \
  "paper/novelty_review.json" \
  "reports/hardening_ledger.json" \
  "reports/itc2007_adaptive_seeding_ablation_2026-08-11.json" \
  "reports/itc2007_breadth_21_rescue_seed17_2026-08-11.json" \
  "reports/itc2007_fixed_time_room_dive_breadth_final_v2_seed17_2026-08-11.json" \
  "output/itc2007-room-dive-breadth-seed17-counterbalanced-final-v2/matrix_index.json" \
  "config/critical_coverage_baseline.json" \
  "cover/critical-coverage.json" \
  "cover/critical-coverage.xml" \
  "cover/critical-coverage-ci-portable.json" \
  "cover/critical-coverage-ci-portable.xml" \
  "cover/critical-coverage-full-local.json" \
  "cover/critical-coverage-full-local.xml" \
  "cover/critical-coverage-source-manifest.json" \
  "data/external/cbctt-ea30189c5e3a/PROVENANCE.json" \
  "data/external/cbctt-ea30189c5e3a/PROVENANCE.sha256" \
  "data/external/cbctt-ea30189c5e3a/OFFICIAL_VALIDATOR_COMPATIBILITY.json" \
  "data/external/itc2019-mpp-c33d15797686/PROVENANCE.json" \
  "scripts/benchmark_itc2007.py" \
  "scripts/benchmark_itc2007_ablation.py" \
  "scripts/analyze_experiments.py" \
  "scripts/check_critical_coverage.py" \
  "scripts/import_external_benchmark.py" \
  "scripts/run_ci_checks.sh" \
  "web/package.json" \
  "web/package-lock.json" \
  "web/public/app-icon.png" \
  "web/src/react/components/AdminSetupWizard.tsx" \
  "web/src/react/components/OperationsPanel.tsx" \
  "web/src/react/solver_settings.ts" \
  "web/tsconfig.json" \
  "web/vite.config.ts" \
  "tests/conftest.py" \
  "tests/test_critical_coverage_gate.py" \
  "tests/test_cbctt.py" \
  "tests/test_cbctt_corpus.py" \
  "tests/test_experiment_statistics.py" \
  "tests/test_external_benchmarks.py" \
  "tests/test_giu_calibration.py" \
  "tests/test_institution_policy_readiness.py" \
  "tests/test_itc2007_benchmark_harness.py" \
  "tests/test_itc2007_ablation.py" \
  "tests/test_itc2019_corpus.py" \
  "tests/test_local_app_benchmark_summary.py" \
  "tests/test_release_artifacts.py" \
  "tests/test_room_proof_lineage.py" \
  "tests/test_web_solve_payload.py" \
  "scripts/run_experiments.py"; do
  if [[ ! -f "${ARTIFACT_DIR}/${required}" ]]; then
    echo "missing required artifact file: ${required}" >&2
    exit 1
  fi
done

if find "${ARTIFACT_DIR}" -type l -print -quit | grep -q .; then
  echo "release artifact must not contain symbolic links" >&2
  exit 1
fi

"${VERIFY_PYTHON}" - "${ARTIFACT_DIR}" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path, PurePosixPath


root = Path(sys.argv[1])
manifest = root / "SHA256SUMS"
pattern = re.compile(r"^([0-9a-f]{64})  (\./.+)$")
listed: set[str] = set()

for line_number, raw_line in enumerate(
    manifest.read_text(encoding="utf-8").splitlines(), start=1
):
    match = pattern.fullmatch(raw_line)
    if match is None:
        raise SystemExit(f"invalid SHA256SUMS row {line_number}")
    relative = match.group(2)[2:]
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise SystemExit(f"unsafe SHA256SUMS path on row {line_number}: {relative}")
    if relative == "SHA256SUMS":
        raise SystemExit("SHA256SUMS must not contain a self-referential checksum")
    if relative in listed:
        raise SystemExit(f"duplicate SHA256SUMS path: {relative}")
    listed.add(relative)

present = {
    path.relative_to(root).as_posix()
    for path in root.rglob("*")
    if path.is_file() and path != manifest
}
missing = sorted(listed - present)
unlisted = sorted(present - listed)
if missing:
    raise SystemExit(f"manifest lists missing files: {', '.join(missing)}")
if unlisted:
    raise SystemExit(f"artifact contains unlisted files: {', '.join(unlisted)}")
PY

(
  cd "${ARTIFACT_DIR}"
  sha256sum --check --strict --quiet SHA256SUMS
)

"${VERIFY_PYTHON}" - "${ARTIFACT_DIR}" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath


root = Path(sys.argv[1])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def metadata() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in (root / "release-metadata.txt").read_text(
        encoding="utf-8"
    ).splitlines():
        key, separator, value = raw_line.partition("=")
        if not separator or not key or key in values:
            raise SystemExit("release-metadata.txt is malformed")
        values[key] = value
    return values


def artifact_path(relative: str, *, context: str) -> Path:
    relative_path = PurePosixPath(relative)
    if relative_path.is_absolute() or not relative_path.parts or ".." in relative_path.parts:
        raise SystemExit(f"unsafe {context} path: {relative}")
    candidate = root.joinpath(*relative_path.parts)
    if not candidate.is_file():
        raise SystemExit(f"missing {context}: {relative}")
    return candidate


def canonical_payload_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


values = metadata()
ledger_path = root / "reports" / "hardening_ledger.json"
ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
gate = ledger.get("release_gate")
if not isinstance(gate, dict):
    raise SystemExit("hardening ledger has no release_gate object")
gate_status = gate.get("status")
open_requirements = gate.get("open_requirements")
if not isinstance(gate_status, str) or not gate_status:
    raise SystemExit("hardening ledger has no release gate status")
if not isinstance(open_requirements, list):
    raise SystemExit("hardening ledger open_requirements must be a list")
if gate_status not in {"GO", "NO-GO"}:
    raise SystemExit(f"unknown hardening-ledger release gate: {gate_status!r}")
if gate_status == "NO-GO" and not open_requirements:
    raise SystemExit("NO-GO hardening ledger must enumerate open requirements")
if gate_status == "GO" and open_requirements:
    raise SystemExit("GO hardening ledger must not enumerate open requirements")
external_blockers = ledger.get("external_blockers")
if not isinstance(external_blockers, list):
    raise SystemExit("hardening ledger external_blockers must be a list")
if gate_status == "GO" and external_blockers:
    raise SystemExit("GO hardening ledger cannot retain external blockers")
if gate_status == "GO":
    raise SystemExit(
        "bundled external-quality and institutional evidence still requires NO-GO"
    )

expected = {
    "schema_version": "2",
    "artifact_kind": "research_release_candidate_bundle",
    "research_release_gate": gate_status,
    "open_requirement_count": str(len(open_requirements)),
    "external_readiness_claimed": "false",
    "verification_scope": (
        "required-file-presence,manifest-completeness,nested-matrix-replay,"
        "coverage-source-binding,paper-freshness,sha256-consistency,"
        "gate-consistency"
    ),
    "compiled_paper_source": "paper/main.pdf",
    "hardening_ledger_sha256": sha256(ledger_path),
    "rescue_report_sha256": sha256(
        root / "reports/itc2007_breadth_21_rescue_seed17_2026-08-11.json"
    ),
    "final_v2_report_sha256": sha256(
        root
        / "reports/itc2007_fixed_time_room_dive_breadth_final_v2_seed17_2026-08-11.json"
    ),
    "final_v2_matrix_sha256": sha256(
        root
        / "output/itc2007-room-dive-breadth-seed17-counterbalanced-final-v2/matrix_index.json"
    ),
    "coverage_source_manifest_sha256": sha256(
        root / "cover/critical-coverage-source-manifest.json"
    ),
}
for key, expected_value in expected.items():
    if values.get(key) != expected_value:
        raise SystemExit(
            f"release metadata mismatch for {key}: "
            f"expected {expected_value!r}, found {values.get(key)!r}"
        )

paper_status = values.get("compiled_paper_status")
paper_sha256 = values.get("compiled_paper_sha256")
pdf = root / "paper" / "main.pdf"
if paper_status != "included_fresh":
    raise SystemExit("release candidate must include a fresh canonical paper/main.pdf")
pdf_bytes = pdf.read_bytes()
if not pdf_bytes.startswith(b"%PDF-") or b"%%EOF" not in pdf_bytes[-1024:]:
    raise SystemExit("included canonical paper/main.pdf is malformed")
if paper_sha256 != sha256(pdf):
    raise SystemExit("compiled paper checksum does not match release metadata")
paper_sources = [
    path
    for path in (root / "paper").rglob("*")
    if path.is_file() and path.suffix.lower() in {".tex", ".bib"}
]
if not paper_sources:
    raise SystemExit("release bundle has no TeX/Bib paper sources")
newer_sources = sorted(
    path.relative_to(root).as_posix()
    for path in paper_sources
    if path.stat().st_mtime_ns > pdf.stat().st_mtime_ns
)
if newer_sources:
    raise SystemExit(
        "canonical paper/main.pdf is stale inside the bundle: "
        + ", ".join(newer_sources[:5])
    )

artifact_readme = (root / "ARTIFACT_README.md").read_text(encoding="utf-8")
if f"Research release gate: {gate_status}" not in artifact_readme:
    raise SystemExit("artifact README does not disclose the hardening-ledger gate")
if "External readiness claimed: no" not in artifact_readme:
    raise SystemExit("artifact README does not preserve the external-readiness boundary")

results_status_path = root / "paper" / "results_status.json"
results_status = json.loads(results_status_path.read_text(encoding="utf-8"))
replacement = results_status.get("replacement_evidence")
if not isinstance(replacement, dict):
    raise SystemExit("paper/results_status.json has no replacement_evidence object")
analysis_relative = "paper/evidence/generated_feasibility_50x3_2026-08-11_analysis.json"
if replacement.get("analysis") != analysis_relative:
    raise SystemExit("results_status.json does not select the current 50x3 analysis")
if replacement.get("publication_gate") != "PASS":
    raise SystemExit("results_status.json replacement publication gate is not PASS")

selected_relative = "paper/evidence/selected_post_incumbent_quality_2026-08-13.json"
selected_status = results_status.get("post_incumbent_quality_evidence")
if not isinstance(selected_status, dict) or selected_status.get("path") != selected_relative:
    raise SystemExit("results_status.json does not select the post-incumbent ledger")
if selected_status.get("fresh_paired_matrix_required_for_general_superiority") is not True:
    raise SystemExit("post-incumbent status omits the fresh-matrix boundary")
selected = json.loads((root / selected_relative).read_text(encoding="utf-8"))
if selected.get("schema_version") != "planora.selected-post-incumbent-quality.v1":
    raise SystemExit("unexpected selected post-incumbent evidence schema")
claim_boundary = selected.get("claim_boundary")
component_order = selected.get("component_order")
selected_rows = selected.get("results")
if not isinstance(claim_boundary, dict) or not isinstance(component_order, dict):
    raise SystemExit("selected post-incumbent evidence lacks claim metadata")
if not isinstance(selected_rows, list) or len(selected_rows) != 5:
    raise SystemExit("selected post-incumbent evidence must contain five results")
if selected_status.get("selected_results") != len(selected_rows):
    raise SystemExit("results status and selected post-incumbent ledger disagree")
required_exclusions = {
    "an end-to-end equal-budget comparison",
    "a fresh paired benchmark matrix",
    "runtime superiority over CPSolver",
    "general superiority across ITC-2007",
}
if not required_exclusions.issubset(set(claim_boundary.get("not_supported") or [])):
    raise SystemExit("selected post-incumbent ledger weakens its claim boundary")

seen_selected: set[tuple[str, str]] = set()
for row in selected_rows:
    if not isinstance(row, dict):
        raise SystemExit("selected post-incumbent evidence contains a malformed row")
    identity = (str(row.get("family")), str(row.get("instance")))
    if identity in seen_selected:
        raise SystemExit("selected post-incumbent evidence contains a duplicate case")
    seen_selected.add(identity)
    result = row.get("post_incumbent")
    comparator = row.get("retained_cpsolver")
    implementation = row.get("implementation")
    if not all(isinstance(value, dict) for value in (result, comparator, implementation)):
        raise SystemExit("selected post-incumbent row lacks result/comparator/source data")
    score = result.get("score")
    comparator_score = comparator.get("score")
    wall_seconds = result.get("wall_seconds")
    budget_seconds = result.get("budget_seconds")
    if (
        not isinstance(score, int)
        or not isinstance(comparator_score, int)
        or score >= comparator_score
        or result.get("hard_violations") != 0
        or result.get("deadline_overrun_seconds") != 0.0
        or not isinstance(wall_seconds, (int, float))
        or not isinstance(budget_seconds, (int, float))
        or wall_seconds < 0
        or wall_seconds > budget_seconds
    ):
        raise SystemExit(f"invalid selected post-incumbent result: {identity}")
    components = result.get("components")
    expected_components = component_order.get(identity[0])
    if not isinstance(components, list) or len(components) != len(expected_components or []):
        raise SystemExit(f"selected post-incumbent component shape mismatch: {identity}")
    implementation_path = PurePosixPath(str(implementation.get("path")))
    if implementation_path.is_absolute() or ".." in implementation_path.parts:
        raise SystemExit(f"unsafe selected implementation path: {implementation_path}")
    implementation_file = root.joinpath(*implementation_path.parts)
    current_sha256 = str(implementation.get("current_sha256"))
    proof_sha256 = str(implementation.get("proof_sha256"))
    if not implementation_file.is_file() or sha256(implementation_file) != current_sha256:
        raise SystemExit(f"selected implementation hash mismatch: {implementation_path}")
    proof_matches = implementation.get("proof_source_matches_current_checkout")
    if not isinstance(proof_matches, bool) or proof_matches != (proof_sha256 == current_sha256):
        raise SystemExit(f"selected proof/current source boundary mismatch: {identity}")

analysis_path = root / analysis_relative
analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
publication_gate = analysis.get("publication_gate")
if not isinstance(publication_gate, dict) or publication_gate.get("status") != "PASS":
    raise SystemExit("current 50x3 analysis publication gate is not PASS")
minimum_effective = replacement.get("minimum_effective_instances_per_condition")
if not isinstance(minimum_effective, int) or minimum_effective < 30:
    raise SystemExit("replacement evidence does not require at least 30 effective instances")
if publication_gate.get("minimum_unique_effective_instances_per_condition") != minimum_effective:
    raise SystemExit("results status and current analysis disagree on the effective-instance gate")

conditions = analysis.get("conditions")
if not isinstance(conditions, list) or not conditions:
    raise SystemExit("current analysis has no conditions")
condition_effective: dict[str, int] = {}
for condition in conditions:
    if not isinstance(condition, dict):
        raise SystemExit("current analysis contains a malformed condition")
    room_mode = condition.get("room_mode")
    effective = condition.get("unique_effective_instances")
    if not isinstance(room_mode, str) or not isinstance(effective, int):
        raise SystemExit("current analysis condition lacks room mode or effective count")
    if condition.get("effective_instance_gate") != "PASS" or effective < minimum_effective:
        raise SystemExit(f"current analysis condition has not passed: {room_mode}")
    if condition.get("fallback_runs") != 0:
        raise SystemExit(f"current analysis condition contains fallback runs: {room_mode}")
    condition_effective[room_mode] = effective
if replacement.get("effective_instances") != condition_effective:
    raise SystemExit("results status effective counts do not match the current analysis")

raw_shards = replacement.get("raw_shards")
analysis_sources = analysis.get("evidence_sources")
if not isinstance(raw_shards, list) or not isinstance(analysis_sources, list):
    raise SystemExit("replacement evidence or analysis has no raw-shard descriptors")
if raw_shards != analysis_sources:
    raise SystemExit("results status and current analysis raw-shard descriptors differ")
expected_shards = {
    "paper/evidence/generated_feasibility_30x3_2026-08-11.jsonl",
    "paper/evidence/generated_feasibility_supplement_31_50_2026-08-11.jsonl",
}
observed_shards: set[str] = set()
for descriptor in raw_shards:
    if not isinstance(descriptor, dict):
        raise SystemExit("raw-shard descriptor is malformed")
    relative = descriptor.get("path")
    expected_sha256 = descriptor.get("sha256")
    expected_rows = descriptor.get("rows")
    if not isinstance(relative, str):
        raise SystemExit("raw-shard descriptor has no path")
    relative_path = PurePosixPath(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise SystemExit(f"unsafe raw-shard path: {relative}")
    if relative in observed_shards:
        raise SystemExit(f"duplicate raw-shard descriptor: {relative}")
    observed_shards.add(relative)
    shard_path = root.joinpath(*relative_path.parts)
    if not shard_path.is_file():
        raise SystemExit(f"missing raw shard: {relative}")
    if not isinstance(expected_sha256, str) or sha256(shard_path) != expected_sha256:
        raise SystemExit(f"raw-shard checksum mismatch: {relative}")
    rows = [
        line
        for line in shard_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not isinstance(expected_rows, int) or len(rows) != expected_rows:
        raise SystemExit(f"raw-shard row-count mismatch: {relative}")
    for row_number, row in enumerate(rows, start=1):
        try:
            json.loads(row)
        except json.JSONDecodeError as error:
            raise SystemExit(
                f"invalid JSONL row in {relative}:{row_number}: {error.msg}"
            ) from error
if observed_shards != expected_shards:
    raise SystemExit("replacement evidence does not identify the two current raw shards")

historical_analysis = json.loads(
    (root / "paper/evidence/generated_feasibility_30x3_2026-08-11_analysis.json").read_text(
        encoding="utf-8"
    )
)
if historical_analysis.get("publication_gate", {}).get("status") != "NO-GO":
    raise SystemExit("historical 30x3 analysis is not marked NO-GO")

index_path = root / "output" / "benchmark-evidence-index.txt"
if not index_path.is_file():
    raise SystemExit("missing benchmark evidence index")
indexed = [line for line in index_path.read_text(encoding="utf-8").splitlines() if line]
if len(indexed) != len(set(indexed)):
    raise SystemExit("benchmark evidence index contains duplicate directories")
if values.get("benchmark_evidence_directory_count") != str(len(indexed)):
    raise SystemExit("benchmark evidence count does not match release metadata")
actual = sorted(
    path.name
    for path in (root / "output").glob("itc2007-*")
    if path.is_dir()
)
if indexed != actual:
    raise SystemExit("benchmark evidence index does not match bundled directories")


def load_json_object(path: Path, *, context: str) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"{context} must be a JSON object")
    return value


def load_jsonl_objects(path: Path, *, context: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise SystemExit(f"{context} row {row_number} is not a JSON object")
        rows.append(value)
    return rows


def indexed_output_directory(relative: str, *, context: str) -> Path:
    relative_path = PurePosixPath(relative)
    if (
        relative_path.is_absolute()
        or ".." in relative_path.parts
        or len(relative_path.parts) != 2
        or relative_path.parts[0] != "output"
        or relative_path.parts[1] not in indexed
    ):
        raise SystemExit(f"{context} is not a bundled benchmark directory: {relative}")
    return root.joinpath(*relative_path.parts)


for directory_name in indexed:
    if Path(directory_name).name != directory_name or not directory_name.startswith("itc2007-"):
        raise SystemExit(f"unsafe benchmark evidence directory: {directory_name}")
    directory = root / "output" / directory_name
    triplet = tuple(directory / name for name in ("manifest.json", "results.jsonl", "summary.json"))
    triplet_presence = tuple(path.is_file() for path in triplet)
    if any(triplet_presence) and not all(triplet_presence):
        raise SystemExit(f"partial benchmark evidence triplet: {directory_name}")
    has_triplet = all(triplet_presence)
    legacy_matrix = directory / "matrix_index.json"
    current_matrix = directory / "matrix-index.json"
    if not has_triplet and not legacy_matrix.is_file() and not current_matrix.is_file():
        raise SystemExit(f"incomplete benchmark evidence: {directory_name}")
    if has_triplet:
        load_json_object(triplet[0], context=f"{directory_name} manifest")
        rows = load_jsonl_objects(triplet[1], context=f"{directory_name} results")
        summary = load_json_object(triplet[2], context=f"{directory_name} summary")
        if summary.get("complete") is not True:
            raise SystemExit(f"benchmark evidence is not complete: {directory_name}")
        for count_key in ("record_count", "completed_runs", "planned_runs"):
            count = summary.get(count_key)
            if not isinstance(count, int) or isinstance(count, bool) or count != len(rows):
                raise SystemExit(
                    f"benchmark evidence count mismatch for {directory_name}: {count_key}"
                )
    if current_matrix.is_file():
        if not has_triplet:
            raise SystemExit(
                f"content-addressed matrix has no complete evidence triplet: {directory_name}"
            )
        matrix = load_json_object(current_matrix, context=f"{directory_name} matrix index")
        if matrix.get("schema_version") != "planora.itc2007-factorial-ablation-index.v1":
            raise SystemExit(f"unexpected matrix-index schema: {directory_name}")
        if matrix.get("complete") is not True:
            raise SystemExit(f"matrix-index is not complete: {directory_name}")
        artifacts = matrix.get("artifacts")
        if not isinstance(artifacts, list):
            raise SystemExit(f"matrix-index artifacts are malformed: {directory_name}")
        expected_paths: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise SystemExit(f"matrix-index artifact row is malformed: {directory_name}")
            relative = artifact.get("path")
            if not isinstance(relative, str):
                raise SystemExit(f"matrix-index artifact has no path: {directory_name}")
            path = PurePosixPath(relative)
            if path.is_absolute() or not path.parts or ".." in path.parts:
                raise SystemExit(f"unsafe matrix-index artifact path: {relative}")
            if relative in expected_paths:
                raise SystemExit(f"duplicate matrix-index artifact path: {relative}")
            expected_paths.add(relative)
            candidate = directory.joinpath(*path.parts)
            if not candidate.is_file():
                raise SystemExit(f"matrix-index artifact is missing: {relative}")
            if candidate.stat().st_size != artifact.get("bytes"):
                raise SystemExit(f"matrix-index artifact size mismatch: {relative}")
            if sha256(candidate) != artifact.get("sha256"):
                raise SystemExit(f"matrix-index artifact hash mismatch: {relative}")
        observed_paths = {
            path.relative_to(directory).as_posix()
            for path in directory.rglob("*")
            if path.is_file()
            and path != current_matrix
        }
        if observed_paths != expected_paths:
            raise SystemExit(f"matrix-index artifact set mismatch: {directory_name}")
        if matrix.get("artifact_count") != len(artifacts):
            raise SystemExit(f"matrix-index artifact count mismatch: {directory_name}")
        if matrix.get("artifact_set_sha256") != canonical_payload_sha256(artifacts):
            raise SystemExit(f"matrix-index artifact-set digest mismatch: {directory_name}")
        if has_triplet:
            result_count = len(load_jsonl_objects(triplet[1], context="matrix results"))
            if matrix.get("record_count") != result_count:
                raise SystemExit(f"matrix-index result count mismatch: {directory_name}")

adaptive_report = json.loads(
    (root / "reports/itc2007_adaptive_seeding_ablation_2026-08-11.json").read_text(
        encoding="utf-8"
    )
)
if adaptive_report.get("evidence_status") != "bounded_engineering_pilot":
    raise SystemExit("adaptive-seeding evidence is not marked as a bounded pilot")
for arm_name in ("baseline", "candidate"):
    arm = adaptive_report.get(arm_name)
    if not isinstance(arm, dict):
        raise SystemExit(f"adaptive-seeding report has no {arm_name} result")
    artifact_relative = arm.get("artifact_directory")
    if not isinstance(artifact_relative, str):
        raise SystemExit(f"adaptive-seeding {arm_name} result has no artifact directory")
    indexed_output_directory(
        artifact_relative, context=f"adaptive-seeding {arm_name} evidence"
    )
    agreement = arm.get("official_validator_agreement")
    if not isinstance(agreement, dict):
        raise SystemExit(f"adaptive-seeding {arm_name} result has no validator agreement")
    if agreement.get("validator_errors") != 0:
        raise SystemExit(f"adaptive-seeding {arm_name} result has validator errors")

rescue_report_path = root / "reports/itc2007_breadth_21_rescue_seed17_2026-08-11.json"
rescue_report = load_json_object(rescue_report_path, context="ITC-2007 rescue report")
if (
    rescue_report.get("evidence_status")
    != "single_seed_external_breadth_gate_with_immutable_competitor_reuse"
):
    raise SystemExit("ITC-2007 rescue evidence has an unexpected status")
rescue_validation = rescue_report.get("validation")
if not isinstance(rescue_validation, dict):
    raise SystemExit("ITC-2007 rescue evidence has no validation summary")
expected_rescue_validation = {
    "planora_records": 21,
    "planora_produced_solutions": 21,
    "planora_officially_feasible": 21,
    "planora_zero_hard_violations": 21,
    "planora_internal_external_score_matches": 21,
    "planora_validator_errors": 0,
    "immutable_cpsolver_records": 21,
    "immutable_cpsolver_produced_solutions": 21,
    "immutable_cpsolver_officially_feasible": 21,
    "immutable_cpsolver_zero_hard_violations": 21,
    "immutable_cpsolver_reported_external_score_matches": 21,
    "immutable_cpsolver_validator_errors": 0,
}
for key, expected_value in expected_rescue_validation.items():
    if rescue_validation.get(key) != expected_value:
        raise SystemExit(f"ITC-2007 rescue validation mismatch: {key}")
rescue_verdict = rescue_report.get("verdict")
rescue_pair = rescue_report.get("paired_result")
if not isinstance(rescue_verdict, dict) or not isinstance(rescue_pair, dict):
    raise SystemExit("ITC-2007 rescue evidence lacks verdict or paired result")
if (
    rescue_verdict.get("external_quality_gate") != "failed"
    or rescue_verdict.get("superiority_claim") != "not_supported"
    or rescue_pair.get("planora_wins") != 0
    or rescue_pair.get("cpsolver_wins") != 21
):
    raise SystemExit("ITC-2007 rescue evidence does not preserve the quality NO-GO")
rescue_artifacts = rescue_report.get("artifacts")
if not isinstance(rescue_artifacts, dict):
    raise SystemExit("ITC-2007 rescue evidence has no artifacts")
for artifact_name in ("planora", "immutable_cpsolver_source"):
    artifact = rescue_artifacts.get(artifact_name)
    if not isinstance(artifact, dict) or not isinstance(artifact.get("directory"), str):
        raise SystemExit(f"ITC-2007 rescue evidence lacks {artifact_name}")
    artifact_directory = indexed_output_directory(
        str(artifact["directory"]), context=f"rescue {artifact_name}"
    )
    for file_name, hash_key in (
        ("manifest.json", "manifest_sha256"),
        ("results.jsonl", "results_sha256"),
        ("summary.json", "summary_sha256"),
    ):
        if sha256(artifact_directory / file_name) != artifact.get(hash_key):
            raise SystemExit(f"ITC-2007 rescue {artifact_name} {file_name} hash mismatch")

final_report_path = (
    root / "reports/itc2007_fixed_time_room_dive_breadth_final_v2_seed17_2026-08-11.json"
)
final_report = load_json_object(final_report_path, context="final-v2 room-dive report")
if (
    final_report.get("evidence_status")
    != "complete_counterbalanced_single_seed_strict_deadline_gate_passed"
):
    raise SystemExit("final-v2 room-dive report has an unexpected status")
final_validation = final_report.get("official_validation")
if not isinstance(final_validation, dict):
    raise SystemExit("final-v2 room-dive report has no official validation")
for key in (
    "external_objective_total_matches",
    "hard_zero",
    "internal_external_component_matches",
    "officially_feasible",
    "records",
    "validator_clean",
):
    if final_validation.get(key) != 42:
        raise SystemExit(f"final-v2 official-validation mismatch: {key}")
final_disposition = final_report.get("release_disposition")
external_comparison = final_report.get("external_comparison")
if not isinstance(final_disposition, dict) or not isinstance(external_comparison, dict):
    raise SystemExit("final-v2 report lacks release disposition or external comparison")
ranking = external_comparison.get("ranking")
if (
    final_disposition.get("superiority_claim_supported") is not False
    or not str(final_disposition.get("external_quality_gate", "")).startswith("failed:")
    or not isinstance(ranking, dict)
    or ranking.get("on_wins") != 0
    or ranking.get("cpsolver_wins") != 21
):
    raise SystemExit("final-v2 report does not preserve the external-quality NO-GO")

final_artifacts = final_report.get("artifacts")
if not isinstance(final_artifacts, dict):
    raise SystemExit("final-v2 report has no artifact map")
final_matrix_relative = final_artifacts.get("matrix_index")
expected_final_matrix = (
    "output/itc2007-room-dive-breadth-seed17-counterbalanced-final-v2/matrix_index.json"
)
if final_matrix_relative != expected_final_matrix:
    raise SystemExit("final-v2 report does not select the required final matrix")
final_matrix_path = artifact_path(expected_final_matrix, context="final-v2 matrix index")
if sha256(final_matrix_path) != final_artifacts.get("matrix_index_sha256"):
    raise SystemExit("final-v2 report/index checksum mismatch")
final_matrix_root = indexed_output_directory(
    "output/itc2007-room-dive-breadth-seed17-counterbalanced-final-v2",
    context="final-v2 matrix root",
)
matrix = load_json_object(final_matrix_path, context="final-v2 matrix index")
if matrix.get("evidence_status") != "complete_counterbalanced_single_seed_strict_deadline_ablation":
    raise SystemExit("final-v2 matrix index has an unexpected status")
if matrix.get("raw_root") != "output/itc2007-room-dive-breadth-seed17-counterbalanced-final-v2":
    raise SystemExit("final-v2 matrix index has an unexpected raw root")
final_configuration = final_report.get("configuration")
source_stability = final_report.get("source_stability")
if not isinstance(final_configuration, dict) or not isinstance(source_stability, dict):
    raise SystemExit("final-v2 report lacks configuration or source stability")
for key in ("seed", "strategy", "workers"):
    if matrix.get(key) != final_configuration.get(key):
        raise SystemExit(f"final-v2 report/index configuration mismatch: {key}")
if matrix.get("source_sha256") != source_stability.get("planora_source_sha256"):
    raise SystemExit("final-v2 report/index source checksum mismatch")
gate_summary = matrix.get("gate_summary")
if not isinstance(gate_summary, dict):
    raise SystemExit("final-v2 matrix index has no gate summary")
for key in (
    "expected_records",
    "hard_zero",
    "internal_external_matches",
    "officially_feasible",
    "source_snapshot_matches",
    "strict_total_deadline_zero_overrun",
    "summary_source_stable",
):
    if gate_summary.get(key) != 42:
        raise SystemExit(f"final-v2 matrix gate mismatch: {key}")
matrix_records = matrix.get("records")
if not isinstance(matrix_records, list) or len(matrix_records) != 42:
    raise SystemExit("final-v2 matrix must contain exactly 42 records")
expected_children = {
    f"comp{instance:02d}-{variant}"
    for instance in range(1, 22)
    for variant in ("off", "on")
}
observed_children: set[str] = set()
execution_indices: set[int] = set()
for record in matrix_records:
    if not isinstance(record, dict):
        raise SystemExit("final-v2 matrix contains a malformed record")
    relative = record.get("directory")
    if not isinstance(relative, str):
        raise SystemExit("final-v2 matrix record has no directory")
    relative_path = PurePosixPath(relative)
    if (
        relative_path.is_absolute()
        or ".." in relative_path.parts
        or len(relative_path.parts) != 3
        or relative_path.parts[:2]
        != ("output", "itc2007-room-dive-breadth-seed17-counterbalanced-final-v2")
    ):
        raise SystemExit(f"unsafe final-v2 nested directory: {relative}")
    child_name = relative_path.parts[2]
    if child_name in observed_children:
        raise SystemExit(f"duplicate final-v2 nested directory: {child_name}")
    observed_children.add(child_name)
    execution_index = record.get("matrix_execution_index")
    if not isinstance(execution_index, int):
        raise SystemExit(f"final-v2 record has no execution index: {child_name}")
    execution_indices.add(execution_index)
    instance = record.get("instance")
    variant = record.get("variant")
    if child_name != f"{instance}-{variant}" or variant not in {"off", "on"}:
        raise SystemExit(f"final-v2 record identity mismatch: {child_name}")
    if (
        record.get("feasible") is not True
        or record.get("hard_violations") != 0
        or record.get("internal_external_match") is not True
        or record.get("source_snapshot_match") is not True
        or record.get("summary_source_stable") is not True
        or record.get("solve_deadline_overrun_seconds") != 0.0
    ):
        raise SystemExit(f"final-v2 record fails a hard evidence gate: {child_name}")
    child = final_matrix_root / child_name
    manifest_path = child / "manifest.json"
    results_path = child / "results.jsonl"
    summary_path = child / "summary.json"
    for path, hash_key in (
        (manifest_path, "manifest_sha256"),
        (results_path, "results_sha256"),
        (summary_path, "summary_sha256"),
    ):
        if not path.is_file() or sha256(path) != record.get(hash_key):
            raise SystemExit(f"final-v2 nested artifact hash mismatch: {child_name}/{path.name}")
    nested_rows = load_jsonl_objects(results_path, context=f"{child_name} results")
    nested_summary = load_json_object(summary_path, context=f"{child_name} summary")
    if len(nested_rows) != 1 or any(
        nested_summary.get(key) != value
        for key, value in (
            ("complete", True),
            ("record_count", 1),
            ("completed_runs", 1),
            ("planned_runs", 1),
            ("source_stable", True),
        )
    ):
        raise SystemExit(f"final-v2 nested run is incomplete: {child_name}")
    nested = nested_rows[0]
    if (
        nested.get("instance_id") != instance
        or nested.get("feasible") is not True
        or nested.get("hard_violations") != 0
        or nested.get("source_snapshot_match") is not True
        or nested.get("official_objective") != record.get("official_objective")
        or nested.get("official_components") != record.get("official_components")
    ):
        raise SystemExit(f"final-v2 nested result disagrees with its index: {child_name}")
    solutions = list(child.rglob("solution.out"))
    workers = list(child.rglob("worker.json"))
    if len(solutions) != 1 or sha256(solutions[0]) != record.get("solution_sha256"):
        raise SystemExit(f"final-v2 solution hash mismatch: {child_name}")
    if len(workers) != 1 or sha256(workers[0]) != record.get("worker_sha256"):
        raise SystemExit(f"final-v2 worker hash mismatch: {child_name}")
    expected_child_files = {
        "manifest.json",
        "results.jsonl",
        "summary.json",
        f"runs/{instance}/seed-17/planora/solution.out",
        f"runs/{instance}/seed-17/planora/stderr.log",
        f"runs/{instance}/seed-17/planora/stdout.log",
        f"runs/{instance}/seed-17/planora/validator.log",
        f"runs/{instance}/seed-17/planora/worker.json",
    }
    observed_child_files = {
        path.relative_to(child).as_posix() for path in child.rglob("*") if path.is_file()
    }
    if observed_child_files != expected_child_files:
        raise SystemExit(f"final-v2 nested artifact set mismatch: {child_name}")
if observed_children != expected_children or execution_indices != set(range(1, 43)):
    raise SystemExit("final-v2 matrix record set or execution order is incomplete")
observed_matrix_entries = {
    path.name for path in final_matrix_root.iterdir() if path.is_dir() or path.is_file()
}
if observed_matrix_entries != expected_children | {"matrix_index.json"}:
    raise SystemExit("final-v2 matrix root contains unindexed artifacts")

coverage_json_path = root / "cover/critical-coverage.json"
coverage_xml_path = root / "cover/critical-coverage.xml"
coverage_manifest_path = root / "cover/critical-coverage-source-manifest.json"
with (root / "pyproject.toml").open("rb") as handle:
    project_configuration = tomllib.load(handle)
try:
    configured_coverage_rows = project_configuration["tool"]["coverage"]["report"][
        "include"
    ]
except (KeyError, TypeError) as error:
    raise SystemExit("pyproject.toml has no critical coverage include scope") from error
if not isinstance(configured_coverage_rows, list) or not configured_coverage_rows:
    raise SystemExit("pyproject.toml critical coverage include scope is empty")
configured_coverage_sources: set[str] = set()
for relative in configured_coverage_rows:
    if not isinstance(relative, str) or not relative:
        raise SystemExit("pyproject.toml critical coverage scope contains a non-path")
    relative_path = PurePosixPath(relative)
    if (
        relative_path.is_absolute()
        or ".." in relative_path.parts
        or any(character in relative for character in "*?[")
        or relative_path.suffix != ".py"
    ):
        raise SystemExit(f"unsafe critical coverage scope path: {relative}")
    if relative in configured_coverage_sources:
        raise SystemExit(f"duplicate critical coverage scope path: {relative}")
    configured_coverage_sources.add(relative)
    artifact_path(relative, context="configured critical coverage source")
coverage = load_json_object(coverage_json_path, context="critical coverage JSON")
coverage_files = coverage.get("files")
if not isinstance(coverage_files, dict) or not coverage_files:
    raise SystemExit("critical coverage JSON has no covered source files")
if set(coverage_files) != configured_coverage_sources:
    raise SystemExit(
        "critical coverage JSON does not exactly match the pyproject.toml include scope"
    )
coverage_manifest = load_json_object(
    coverage_manifest_path, context="critical coverage source manifest"
)
if (
    coverage_manifest.get("schema_version")
    != "planora.critical-coverage-source-manifest.v1"
):
    raise SystemExit("unexpected critical coverage source-manifest schema")
for key, expected_path, actual_path in (
    ("coverage_json", "cover/critical-coverage.json", coverage_json_path),
    ("coverage_xml", "cover/critical-coverage.xml", coverage_xml_path),
):
    descriptor = coverage_manifest.get(key)
    if not isinstance(descriptor, dict) or descriptor.get("path") != expected_path:
        raise SystemExit(f"coverage source manifest has an invalid {key} descriptor")
    if descriptor.get("sha256") != sha256(actual_path):
        raise SystemExit(f"coverage source manifest {key} hash mismatch")
    if descriptor.get("bytes") != actual_path.stat().st_size:
        raise SystemExit(f"coverage source manifest {key} size mismatch")
source_rows = coverage_manifest.get("source_files")
if not isinstance(source_rows, list) or not source_rows:
    raise SystemExit("coverage source manifest has no source rows")
source_paths: set[str] = set()
for row in source_rows:
    if not isinstance(row, dict) or not isinstance(row.get("path"), str):
        raise SystemExit("coverage source manifest contains a malformed source row")
    relative = str(row["path"])
    if relative in source_paths:
        raise SystemExit(f"duplicate coverage source-manifest path: {relative}")
    source_paths.add(relative)
    source = artifact_path(relative, context="covered source file")
    if source.stat().st_size != row.get("bytes") or sha256(source) != row.get("sha256"):
        raise SystemExit(f"covered source does not match coverage manifest: {relative}")
if source_paths != configured_coverage_sources:
    raise SystemExit(
        "coverage source manifest does not exactly match the pyproject.toml include scope"
    )
if coverage_manifest.get("source_file_count") != len(source_rows):
    raise SystemExit("coverage source-manifest file count mismatch")
if coverage_manifest.get("source_set_sha256") != canonical_payload_sha256(source_rows):
    raise SystemExit("coverage source-manifest aggregate digest mismatch")

baseline_path = root / "config/critical_coverage_baseline.json"
baseline = load_json_object(baseline_path, context="critical coverage baseline")
baseline_files = baseline.get("files")
if not isinstance(baseline_files, dict) or set(baseline_files) != configured_coverage_sources:
    raise SystemExit(
        "critical coverage baseline does not exactly match the pyproject.toml include scope"
    )
baseline_categories = baseline.get("categories")
if not isinstance(baseline_categories, dict) or not baseline_categories:
    raise SystemExit("critical coverage baseline has no categories")
categorized_coverage_sources: set[str] = set()
for category_name, category in baseline_categories.items():
    if not isinstance(category, dict):
        raise SystemExit(f"critical coverage category is malformed: {category_name}")
    category_files = category.get("files")
    if not isinstance(category_files, list) or not category_files:
        raise SystemExit(f"critical coverage category has no files: {category_name}")
    for relative in category_files:
        if not isinstance(relative, str):
            raise SystemExit(
                f"critical coverage category contains a non-path: {category_name}"
            )
        categorized_coverage_sources.add(relative)
if categorized_coverage_sources != configured_coverage_sources:
    raise SystemExit(
        "critical coverage categories do not exactly match the pyproject.toml include scope"
    )
measurement = baseline.get("measurement")
if not isinstance(measurement, dict):
    raise SystemExit("critical coverage baseline has no measurement object")
for measurement_key, expected_path in (
    ("full_local", "cover/critical-coverage-full-local.json"),
    ("ci_portable", "cover/critical-coverage-ci-portable.json"),
):
    descriptor = measurement.get(measurement_key)
    if not isinstance(descriptor, dict) or descriptor.get("report") != expected_path:
        raise SystemExit(f"critical coverage baseline has no {measurement_key} report")
    report_path = artifact_path(expected_path, context=f"{measurement_key} coverage report")
    if descriptor.get("report_sha256") != sha256(report_path):
        raise SystemExit(f"{measurement_key} coverage report hash mismatch")
    report = load_json_object(report_path, context=f"{measurement_key} coverage report")
    if report.get("meta", {}).get("branch_coverage") is not True:
        raise SystemExit(f"{measurement_key} coverage report lacks branch coverage")
for xml_relative in (
    "cover/critical-coverage.xml",
    "cover/critical-coverage-full-local.xml",
    "cover/critical-coverage-ci-portable.xml",
):
    try:
        xml_root = ET.parse(artifact_path(xml_relative, context="coverage XML")).getroot()
    except ET.ParseError as error:
        raise SystemExit(f"malformed coverage XML {xml_relative}: {error}") from error
    if xml_root.tag != "coverage":
        raise SystemExit(f"unexpected coverage XML root: {xml_relative}")

cbctt_root = root / "data/external/cbctt-ea30189c5e3a"
cbctt_provenance_path = cbctt_root / "PROVENANCE.json"
cbctt_sidecar = (cbctt_root / "PROVENANCE.sha256").read_text(encoding="utf-8").strip()
if cbctt_sidecar != sha256(cbctt_provenance_path):
    raise SystemExit("CB-CTT provenance sidecar mismatch")
cbctt_provenance = load_json_object(cbctt_provenance_path, context="CB-CTT provenance")
if cbctt_provenance.get("schema_version") != "planora.cbctt-external-corpus.v2":
    raise SystemExit("unexpected CB-CTT provenance schema")
cbctt_corpus = cbctt_provenance.get("corpus")
cbctt_instances = cbctt_provenance.get("instances")
if not isinstance(cbctt_corpus, dict) or not isinstance(cbctt_instances, list):
    raise SystemExit("CB-CTT provenance lacks corpus or instance evidence")
if (
    cbctt_corpus.get("distinct_instance_files") != 34
    or cbctt_corpus.get("distinct_sha256_contents") != 34
    or cbctt_corpus.get("source_manifest_sha256")
    != "83d108b89322d46e2ca385652ca6dca4fa9cf569ea5df7bed9e24b4884e47747"
    or cbctt_corpus.get("projection_set_sha256")
    != "e98b15921969d234ec5324ab039762d1a7abcfb143a45f331c1469dc0b79a2e8"
    or len(cbctt_instances) != 34
):
    raise SystemExit("CB-CTT provenance does not identify the pinned 34-instance corpus")
cbctt_projection_hashes = {
    str(row.get("projected_sha256"))
    for row in cbctt_instances
    if isinstance(row, dict)
}
if len(cbctt_projection_hashes) != 34:
    raise SystemExit("CB-CTT provenance does not contain 34 distinct projections")
cbctt_validator = load_json_object(
    cbctt_root / "OFFICIAL_VALIDATOR_COMPATIBILITY.json",
    context="CB-CTT official-validator compatibility",
)
validator_instances = cbctt_validator.get("instances")
if (
    cbctt_validator.get("all_compatible") is not True
    or cbctt_validator.get("checked_instances") != 34
    or cbctt_validator.get("compatible_instances") != 34
    or not isinstance(validator_instances, list)
    or len(validator_instances) != 34
    or "not feasible-solver evidence" not in str(cbctt_validator.get("claim_boundary", ""))
):
    raise SystemExit("CB-CTT validator evidence is incomplete or overclaims its scope")
validator_projection_hashes = {
    str(row.get("projected_sha256"))
    for row in validator_instances
    if isinstance(row, dict)
    and row.get("compatible") is True
    and row.get("returncode") == 0
    and row.get("expected") == row.get("observed")
}
if validator_projection_hashes != cbctt_projection_hashes:
    raise SystemExit("CB-CTT validator evidence and provenance projections disagree")

itc2019_compact_path = root / "paper/evidence/itc2019_public_mirror_validation_2026-08-11.json"
itc2019_full_path = root / "data/external/itc2019-mpp-c33d15797686/PROVENANCE.json"
itc2019_compact = load_json_object(itc2019_compact_path, context="ITC-2019 compact evidence")
itc2019_full = load_json_object(itc2019_full_path, context="ITC-2019 full provenance")
if itc2019_compact.get("schema_version") != "planora.itc2019-public-mirror-evidence.v1":
    raise SystemExit("unexpected compact ITC-2019 evidence schema")
if itc2019_full.get("schema_version") != "planora.itc2019-public-corpus.v1":
    raise SystemExit("unexpected full ITC-2019 provenance schema")
compact_source = itc2019_compact.get("source")
full_source = itc2019_full.get("source")
if not isinstance(compact_source, dict) or not isinstance(full_source, dict):
    raise SystemExit("ITC-2019 evidence lacks source descriptors")
if (
    compact_source.get("commit") != full_source.get("commit")
    or compact_source.get("root_tree") != full_source.get("root_tree")
    or compact_source.get("source_manifest_sha256")
    != full_source.get("source_manifest_sha256")
    or compact_source.get("full_ignored_cache_provenance_sha256")
    != sha256(itc2019_full_path)
):
    raise SystemExit("compact and full ITC-2019 provenance disagree")
full_corpus = itc2019_full.get("corpus")
full_parsing = itc2019_full.get("problem_parsing")
full_solutions = itc2019_full.get("solution_validation")
compact_parsing = itc2019_compact.get("problem_parsing")
compact_solutions = itc2019_compact.get("solution_validation")
compact_boundary = itc2019_compact.get("claim_boundary")
if not all(
    isinstance(value, dict)
    for value in (
        full_corpus,
        full_parsing,
        full_solutions,
        compact_parsing,
        compact_solutions,
        compact_boundary,
    )
):
    raise SystemExit("ITC-2019 evidence lacks required validation summaries")
if (
    full_corpus.get("problem_files") != 36
    or full_corpus.get("solution_files") != 18
    or full_parsing.get("structural_xml_passed") != 36
    or full_parsing.get("semantic_passed") != 34
    or full_parsing.get("semantic_rejected") != 2
    or full_solutions.get("solution_xml_parsed") != 18
    or full_solutions.get("locally_valid_for_implemented_scope") != 12
    or full_solutions.get("locally_invalid_for_implemented_scope") != 6
    or compact_parsing.get("structural_xml_passed") != 36
    or compact_parsing.get("strict_semantic_passed") != 34
    or compact_parsing.get("strict_semantic_rejected") != 2
    or compact_solutions.get("solution_xml_parsed") != 18
    or compact_solutions.get("locally_valid_for_implemented_scope") != 12
    or compact_solutions.get("locally_invalid_for_implemented_scope") != 6
    or compact_boundary.get("official_validator_agreement")
    != "not_run_authenticated_website_upload_unavailable"
):
    raise SystemExit("ITC-2019 evidence is incomplete or crosses its official-validator boundary")
PY

"${VERIFY_PYTHON}" "${ARTIFACT_DIR}/scripts/check_critical_coverage.py" \
  --coverage-json "${ARTIFACT_DIR}/cover/critical-coverage.json" \
  --baseline "${ARTIFACT_DIR}/config/critical_coverage_baseline.json"

RELEASE_GATE_STATUS="$(
  awk -F= '$1 == "research_release_gate" { print substr($0, index($0, "=") + 1) }' \
    "${ARTIFACT_DIR}/release-metadata.txt"
)"
echo "Verified release-candidate required contents and internal checksums: ${ARTIFACT_DIR}"
echo "Research release gate: ${RELEASE_GATE_STATUS}; external readiness is not claimed"
