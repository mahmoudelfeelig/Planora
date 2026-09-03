#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-v1.0}"
if [[ ! "${VERSION}" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "release version must contain only letters, digits, dot, underscore, or hyphen" >&2
  exit 2
fi
RELEASE_ROOT="${PLANORA_RELEASE_ROOT:-${ROOT_DIR}/release}"
OUT_DIR="${RELEASE_ROOT}/${VERSION}"
PAPER_OUT_DIR="${OUT_DIR}/paper"
COMPILED_PAPER="${ROOT_DIR}/paper/main.pdf"
RESCUE_REPORT_REL="reports/itc2007_breadth_21_rescue_seed17_2026-08-11.json"
FINAL_V2_REPORT_REL="reports/itc2007_fixed_time_room_dive_breadth_final_v2_seed17_2026-08-11.json"
FINAL_V2_MATRIX_REL="output/itc2007-room-dive-breadth-seed17-counterbalanced-final-v2/matrix_index.json"
COVERAGE_SOURCE_MANIFEST_REL="cover/critical-coverage-source-manifest.json"
CBCTT_PROVENANCE_REL="data/external/cbctt-ea30189c5e3a/PROVENANCE.json"
CBCTT_PROVENANCE_SIDECAR_REL="data/external/cbctt-ea30189c5e3a/PROVENANCE.sha256"
CBCTT_VALIDATOR_REL="data/external/cbctt-ea30189c5e3a/OFFICIAL_VALIDATOR_COMPATIBILITY.json"
ITC2019_PROVENANCE_REL="data/external/itc2019-mpp-c33d15797686/PROVENANCE.json"

if [[ -e "${OUT_DIR}" || -L "${OUT_DIR}" ]]; then
  echo "release artifact already exists; refusing to overwrite immutable snapshot: ${OUT_DIR}" >&2
  exit 2
fi

# A research release candidate is not source-only. Check the canonical PDF and
# every newly required evidence input before creating the immutable output
# directory, so a failed preflight does not leave a poisoned partial snapshot.
if [[ ! -f "${COMPILED_PAPER}" ]]; then
  echo "canonical paper/main.pdf is required for a release candidate" >&2
  exit 1
fi
if [[ "$(head -c 5 "${COMPILED_PAPER}")" != "%PDF-" ]]; then
  echo "canonical paper/main.pdf is malformed" >&2
  exit 1
fi
if ! tail -c 1024 "${COMPILED_PAPER}" | grep -a -q '%%EOF'; then
  echo "canonical paper/main.pdf has no PDF end marker" >&2
  exit 1
fi
STALE_PAPER_SOURCE="$(
  find "${ROOT_DIR}/paper" -type f \( -name '*.tex' -o -name '*.bib' \) \
    -newer "${COMPILED_PAPER}" -print -quit
)"
if [[ -n "${STALE_PAPER_SOURCE}" ]]; then
  echo "canonical paper/main.pdf is older than ${STALE_PAPER_SOURCE#${ROOT_DIR}/}" >&2
  exit 1
fi

for required_input in \
  "${RESCUE_REPORT_REL}" \
  "${FINAL_V2_REPORT_REL}" \
  "${FINAL_V2_MATRIX_REL}" \
  "${COVERAGE_SOURCE_MANIFEST_REL}" \
  "${CBCTT_PROVENANCE_REL}" \
  "${CBCTT_PROVENANCE_SIDECAR_REL}" \
  "${CBCTT_VALIDATOR_REL}" \
  "${ITC2019_PROVENANCE_REL}" \
  "paper/evidence/itc2007_support_proxy_comp10_2026-08-13.json" \
  "paper/evidence/selected_post_incumbent_quality_2026-08-13.json" \
  "paper/evidence/itc2019_public_mirror_validation_2026-08-11.json"; do
  if [[ ! -f "${ROOT_DIR}/${required_input}" ]]; then
    echo "required release input is missing: ${required_input}" >&2
    exit 1
  fi
done

mkdir -p "${PAPER_OUT_DIR}"

cd "${ROOT_DIR}"

GIT_SHA="$(git rev-parse HEAD)"
GIT_SHA_SHORT="$(git rev-parse --short HEAD)"
GIT_DIRTY="false"
if [[ -n "$(git status --porcelain)" ]]; then
  GIT_DIRTY="true"
fi
GENERATED_AT_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  else
    PYTHON_BIN="$(command -v python)"
  fi
fi

{
  echo "release_version=${VERSION}"
  echo "generated_at_utc=${GENERATED_AT_UTC}"
  echo "git_sha=${GIT_SHA}"
  echo "git_sha_short=${GIT_SHA_SHORT}"
  echo "git_dirty=${GIT_DIRTY}"
  echo "python_bin=${PYTHON_BIN}"
  "${PYTHON_BIN}" --version
  echo
  echo "[platform]"
  uname -a
  echo
  echo "[packages]"
  PIP_NO_CACHE_DIR=1 "${PYTHON_BIN}" -m pip freeze
} > "${OUT_DIR}/environment.txt"

# Preserve the source tree expected by \input and \bibliography instead of
# flattening basenames into paper/. This makes the frozen paper compilable.
while IFS= read -r rel; do
  mkdir -p "${OUT_DIR}/$(dirname "${rel}")"
  cp -p "${ROOT_DIR}/${rel}" "${OUT_DIR}/${rel}"
done < <(
  cd "${ROOT_DIR}"
  find paper -type f \
    \( -name '*.tex' -o -name '*.bib' -o -name '*.jsonl' -o -name '*.json' -o -name '*.csv' -o -name '*.md' \) \
    ! -path 'paper/build/*' \
    | sort
)

# The LaTeX build writes paper/main.pdf. It is the only compiled-paper input;
# never substitute an older output/pdf copy. Preserve source mtimes so the
# independent verifier can replay the freshness comparison inside the bundle.
COMPILED_PAPER_STATUS="included_fresh"
cp -p "${COMPILED_PAPER}" "${PAPER_OUT_DIR}/main.pdf"

while IFS= read -r rel; do
  mkdir -p "${OUT_DIR}/$(dirname "${rel}")"
  cp "${ROOT_DIR}/${rel}" "${OUT_DIR}/${rel}"
done < <(
  cd "${ROOT_DIR}"
  find api benchmarks connectors core product services ui utils \
    -type f -name '*.py' \
    ! -path '*/__pycache__/*' \
    ! -path '*/.ruff_cache/*' \
    | sort
)

# Preserve the administrator web client, static assets, top-level institutional
# guidance, and machine-readable audit reports.
while IFS= read -r rel; do
  mkdir -p "${OUT_DIR}/$(dirname "${rel}")"
  cp "${ROOT_DIR}/${rel}" "${OUT_DIR}/${rel}"
done < <(
  cd "${ROOT_DIR}"
  {
    find web/src -type f \
      \( -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.css' -o -name '*.d.ts' \)
    find web/public -type f
    find docs -maxdepth 1 -type f -name '*.md' ! -name '*.local.md'
    find reports -maxdepth 1 -type f -name '*.json'
  } | sort
)

# Preserve completed local benchmark evidence exactly as generated. A regular
# harness run has a complete top-level summary. Matrix runs may instead use a
# legacy nested matrix_index.json or the current content-addressed
# matrix-index.json. In-progress matrices fail the completeness check and are
# not packaged. Their presence never promotes a benchmark claim.
if [[ -d "${ROOT_DIR}/output" ]]; then
  shopt -s nullglob
  for evidence_dir in "${ROOT_DIR}"/output/itc2007-*; do
    [[ -d "${evidence_dir}" ]] || continue
    evidence_complete="false"
    if [[ -f "${evidence_dir}/manifest.json" \
      && -f "${evidence_dir}/results.jsonl" \
      && -f "${evidence_dir}/summary.json" ]] \
      && "${PYTHON_BIN}" -c \
        'import json, sys; raise SystemExit(0 if json.load(open(sys.argv[1], encoding="utf-8")).get("complete") is True else 1)' \
        "${evidence_dir}/summary.json"; then
      evidence_complete="true"
    elif [[ -f "${evidence_dir}/manifest.json" \
      && -f "${evidence_dir}/results.jsonl" \
      && -f "${evidence_dir}/summary.json" \
      && -f "${evidence_dir}/matrix-index.json" ]] \
      && "${PYTHON_BIN}" -c \
        'import json, sys; raise SystemExit(0 if json.load(open(sys.argv[1], encoding="utf-8")).get("complete") is True else 1)' \
        "${evidence_dir}/matrix-index.json"; then
      evidence_complete="true"
    elif [[ -f "${evidence_dir}/matrix_index.json" ]] \
      && "${PYTHON_BIN}" -c \
        'import json, sys; value=str(json.load(open(sys.argv[1], encoding="utf-8")).get("evidence_status", "")); raise SystemExit(0 if value.startswith("complete_") else 1)' \
        "${evidence_dir}/matrix_index.json"; then
      evidence_complete="true"
    fi
    if [[ "${evidence_complete}" != "true" ]]; then
      echo "warning: skipping incomplete benchmark evidence: ${evidence_dir#${ROOT_DIR}/}" >&2
      continue
    fi
    while IFS= read -r source; do
      rel="${source#${ROOT_DIR}/}"
      mkdir -p "${OUT_DIR}/$(dirname "${rel}")"
      cp "${source}" "${OUT_DIR}/${rel}"
    done < <(
      find "${evidence_dir}" -type f | sort
    )
  done
  shopt -u nullglob
fi

for rel in \
  "main.py" \
  "README.md" \
  "FEATURES.MD" \
  "SPECS.md" \
  "LICENSE" \
  "pyproject.toml" \
  "requirements.txt" \
  "requirements-dev.txt" \
  "scripts/run_experiments.py" \
  "scripts/analyze_experiments.py" \
  "scripts/check_critical_coverage.py" \
  "scripts/run_ci_checks.sh" \
  "scripts/run_disruption_experiments.py" \
  "scripts/import_external_benchmark.py" \
  "scripts/benchmark_itc2007.py" \
  "scripts/benchmark_itc2007_ablation.py" \
  "scripts/benchmark_local_app.py" \
  "scripts/calibrate_giu_preset.py" \
  "scripts/fetch_cbctt_corpus.py" \
  "scripts/fetch_itc2019_public_corpus.py" \
  "scripts/validate_cbctt_projection_compatibility.py" \
  "docs/CBCTT_EXTERNAL_CORPUS.md" \
  "docs/GIU_INSTITUTIONAL_VALIDATION_PROTOCOL.md" \
  "docs/INSTITUTION_POLICY_PORTABILITY.md" \
  "docs/ITC2019_PUBLIC_CORPUS.md" \
  "reports/hardening_ledger.json" \
  "reports/itc2007_adaptive_seeding_ablation_2026-08-11.json" \
  "${RESCUE_REPORT_REL}" \
  "${FINAL_V2_REPORT_REL}" \
  "config/critical_coverage_baseline.json" \
  "cover/critical-coverage.json" \
  "cover/critical-coverage.xml" \
  "cover/critical-coverage-ci-portable.json" \
  "cover/critical-coverage-ci-portable.xml" \
  "cover/critical-coverage-full-local.json" \
  "cover/critical-coverage-full-local.xml" \
  "${COVERAGE_SOURCE_MANIFEST_REL}" \
  "${CBCTT_PROVENANCE_REL}" \
  "${CBCTT_PROVENANCE_SIDECAR_REL}" \
  "${CBCTT_VALIDATOR_REL}" \
  "${ITC2019_PROVENANCE_REL}" \
  "web/package.json" \
  "web/package-lock.json" \
  "web/eslint.config.js" \
  "web/playwright.config.ts" \
  "web/tsconfig.json" \
  "web/vite.config.ts" \
  "web/index.html" \
  "tests/conftest.py" \
  "tests/test_critical_coverage_gate.py" \
  "tests/test_adaptive_lns.py" \
  "tests/test_cbctt.py" \
  "tests/test_cbctt_corpus.py" \
  "tests/test_experiment_statistics.py" \
  "tests/test_external_benchmarks.py" \
  "tests/test_giu_calibration.py" \
  "tests/test_institution_policy_readiness.py" \
  "tests/test_itc2007_benchmark_harness.py" \
  "tests/test_itc2007_ablation.py" \
  "tests/test_itc2007_interchange.py" \
  "tests/test_itc2019_corpus.py" \
  "tests/test_local_app_benchmark_summary.py" \
  "tests/test_release_artifacts.py" \
  "tests/test_research_reproducibility.py" \
  "tests/test_room_decomposition.py" \
  "tests/test_room_proof_lineage.py" \
  "tests/test_web_solve_payload.py" \
  "scripts/freeze_release_artifacts.sh" \
  "scripts/verify_release_artifact.sh"; do
  if [[ -f "${ROOT_DIR}/${rel}" ]]; then
    mkdir -p "${OUT_DIR}/$(dirname "${rel}")"
    cp "${ROOT_DIR}/${rel}" "${OUT_DIR}/${rel}"
  fi
done

# Record the benchmark-evidence directories even when there are none. The
# verifier uses this index to distinguish an explicitly empty evidence set
# from an incomplete copy.
mkdir -p "${OUT_DIR}/output"
find "${OUT_DIR}/output" -mindepth 1 -maxdepth 1 -type d -name 'itc2007-*' \
  -printf '%f\n' | sort > "${OUT_DIR}/output/benchmark-evidence-index.txt"

HARDENING_LEDGER="${OUT_DIR}/reports/hardening_ledger.json"
RELEASE_GATE_STATUS="$(
  "${PYTHON_BIN}" -c \
    'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["release_gate"]["status"])' \
    "${HARDENING_LEDGER}"
)"
RELEASE_GATE_OPEN_COUNT="$(
  "${PYTHON_BIN}" -c \
    'import json, sys; print(len(json.load(open(sys.argv[1], encoding="utf-8"))["release_gate"]["open_requirements"]))' \
    "${HARDENING_LEDGER}"
)"
COMPILED_PAPER_SHA256="$(sha256sum "${PAPER_OUT_DIR}/main.pdf" | cut -d ' ' -f 1)"
HARDENING_LEDGER_SHA256="$(sha256sum "${HARDENING_LEDGER}" | cut -d ' ' -f 1)"
BENCHMARK_EVIDENCE_COUNT="$(wc -l < "${OUT_DIR}/output/benchmark-evidence-index.txt")"
RESCUE_REPORT_SHA256="$(sha256sum "${OUT_DIR}/${RESCUE_REPORT_REL}" | cut -d ' ' -f 1)"
FINAL_V2_REPORT_SHA256="$(sha256sum "${OUT_DIR}/${FINAL_V2_REPORT_REL}" | cut -d ' ' -f 1)"
FINAL_V2_MATRIX_SHA256="$(sha256sum "${OUT_DIR}/${FINAL_V2_MATRIX_REL}" | cut -d ' ' -f 1)"
COVERAGE_SOURCE_MANIFEST_SHA256="$(sha256sum "${OUT_DIR}/${COVERAGE_SOURCE_MANIFEST_REL}" | cut -d ' ' -f 1)"

{
  echo "schema_version=2"
  echo "artifact_kind=research_release_candidate_bundle"
  echo "research_release_gate=${RELEASE_GATE_STATUS}"
  echo "open_requirement_count=${RELEASE_GATE_OPEN_COUNT}"
  echo "external_readiness_claimed=false"
  echo "verification_scope=required-file-presence,manifest-completeness,nested-matrix-replay,coverage-source-binding,paper-freshness,sha256-consistency,gate-consistency"
  echo "compiled_paper_source=paper/main.pdf"
  echo "compiled_paper_status=${COMPILED_PAPER_STATUS}"
  echo "compiled_paper_sha256=${COMPILED_PAPER_SHA256}"
  echo "hardening_ledger_sha256=${HARDENING_LEDGER_SHA256}"
  echo "benchmark_evidence_directory_count=${BENCHMARK_EVIDENCE_COUNT}"
  echo "rescue_report_sha256=${RESCUE_REPORT_SHA256}"
  echo "final_v2_report_sha256=${FINAL_V2_REPORT_SHA256}"
  echo "final_v2_matrix_sha256=${FINAL_V2_MATRIX_SHA256}"
  echo "coverage_source_manifest_sha256=${COVERAGE_SOURCE_MANIFEST_SHA256}"
} > "${OUT_DIR}/release-metadata.txt"

{
  echo "# Research release-candidate artifact ${VERSION}"
  echo
  echo "- Generated: ${GENERATED_AT_UTC}"
  echo "- Commit: ${GIT_SHA}"
  echo "- Python: ${PYTHON_BIN}"
  echo "- Research release gate: ${RELEASE_GATE_STATUS}"
  echo "- Open requirements: ${RELEASE_GATE_OPEN_COUNT}"
  echo "- External readiness claimed: no"
  echo "- Compiled paper: ${COMPILED_PAPER_STATUS} (canonical source: paper/main.pdf)"
  echo
  echo "Checksum verification establishes internal bundle consistency and required-content presence only."
  echo "SHA256SUMS is not signed and does not establish source authenticity."
  echo "It is not a production-readiness, institutional-approval, official-validator, or publication-performance attestation."
  echo
  echo "## Included Files"
  find "${OUT_DIR}" -type f | sed "s#${OUT_DIR}/##" | sort
} > "${OUT_DIR}/ARTIFACT_README.md"

(
  cd "${OUT_DIR}"
  find . -type f ! -path './SHA256SUMS' -print0 | sort -z | xargs -0 sha256sum
) > "${OUT_DIR}/SHA256SUMS"

PYTHON_BIN="${PYTHON_BIN}" "${ROOT_DIR}/scripts/verify_release_artifact.sh" "${OUT_DIR}"
echo "Wrote integrity-verified research release-candidate bundle to: ${OUT_DIR}"
