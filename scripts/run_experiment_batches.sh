#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

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

# Batch A: reliability/runtime across room modes with more seeds.
"${PYTHON_BIN}" scripts/run_experiments.py \
  --modes small_demo,block_profs,mixed_large,target_case \
  --seeds 1,2,3 \
  --room-modes cp_rooms,greedy \
  --use-objective 1 \
  --retry-without-objective 1 \
  --cp-rooms-fallback-to-greedy 1 \
  --strict-seconds 20 \
  --time-limit 60 \
  --workers 4 \
  --ls-iters 0 \
  --out paper/results_baseline_expanded.jsonl

"${PYTHON_BIN}" scripts/jsonl_to_latex_table.py \
  --in paper/results_baseline_expanded.jsonl \
  --out paper/sections/07_experiments_table.tex \
  --aggregate

"${PYTHON_BIN}" scripts/jsonl_to_latex_table.py \
  --in paper/results_baseline_expanded.jsonl \
  --out paper/sections/07_experiments_runs.tex

# Batch B: local-search quality run (greedy mode for speed/reproducibility).
"${PYTHON_BIN}" scripts/run_experiments.py \
  --modes small_demo,block_profs,mixed_large,target_case \
  --seeds 1,2,3 \
  --room-mode greedy \
  --use-objective 1 \
  --retry-without-objective 1 \
  --cp-rooms-fallback-to-greedy 1 \
  --strict-seconds 20 \
  --time-limit 60 \
  --workers 4 \
  --ls-iters 150 \
  --ls-seconds 8 \
  --out paper/results_ls_expanded.jsonl

"${PYTHON_BIN}" scripts/jsonl_to_latex_ls_table.py \
  --in paper/results_ls_expanded.jsonl \
  --out paper/sections/07_experiments_ls_table.tex

echo "Wrote:"
echo "  paper/results_baseline_expanded.jsonl"
echo "  paper/results_ls_expanded.jsonl"
echo "  paper/sections/07_experiments_table.tex"
echo "  paper/sections/07_experiments_runs.tex"
echo "  paper/sections/07_experiments_ls_table.tex"
