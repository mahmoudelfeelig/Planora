#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-v1.0}"
OUT_DIR="${ROOT_DIR}/release/${VERSION}"
PAPER_OUT_DIR="${OUT_DIR}/paper"

mkdir -p "${PAPER_OUT_DIR}"

cd "${ROOT_DIR}"

GIT_SHA="$(git rev-parse HEAD)"
GIT_SHA_SHORT="$(git rev-parse --short HEAD)"
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
  echo "python_bin=${PYTHON_BIN}"
  "${PYTHON_BIN}" --version
  echo
  echo "[platform]"
  uname -a
  echo
  echo "[packages]"
  "${PYTHON_BIN}" -m pip freeze
} > "${OUT_DIR}/environment.txt"

for rel in \
  "paper/main.tex" \
  "paper/metadata.tex" \
  "paper/refs.bib" \
  "paper/results.jsonl" \
  "paper/results_baseline_expanded.jsonl" \
  "paper/results_ls_expanded.jsonl" \
  "paper/sections/07_experiments.tex" \
  "paper/sections/07_experiments_table.tex" \
  "paper/sections/07_experiments_runs.tex" \
  "paper/sections/07_experiments_ls_table.tex"; do
  if [[ -f "${ROOT_DIR}/${rel}" ]]; then
    cp "${ROOT_DIR}/${rel}" "${PAPER_OUT_DIR}/$(basename "${rel}")"
  fi
done

{
  echo "# Release ${VERSION}"
  echo
  echo "- Generated: ${GENERATED_AT_UTC}"
  echo "- Commit: ${GIT_SHA}"
  echo "- Python: ${PYTHON_BIN}"
  echo
  echo "## Included Files"
  find "${OUT_DIR}" -type f | sed "s#${ROOT_DIR}/##" | sort
} > "${OUT_DIR}/README.md"

(
  cd "${OUT_DIR}"
  find . -type f -print0 | sort -z | xargs -0 sha256sum
) > "${OUT_DIR}/SHA256SUMS"

echo "Wrote release artifact bundle to: ${OUT_DIR}"
