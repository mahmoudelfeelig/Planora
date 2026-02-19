#!/usr/bin/env bash
set -euo pipefail

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
export PYTHONPATH="."
PYTHON_BIN="${PYTHON_BIN:-$(command -v python || command -v python3)}"

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "No python interpreter found on PATH" >&2
  exit 1
fi

# Compile only project sources (avoid traversing virtualenv and caches).
"${PYTHON_BIN}" -m compileall -q core ui utils tests main.py scripts

# Phase 1: quick feedback tests.
timeout 20m "${PYTHON_BIN}" -m pytest -q -m "not slow"

# Phase 2: slower integration and UI tests.
timeout 25m "${PYTHON_BIN}" -m pytest -q -m "slow"
