#!/usr/bin/env bash
set -euo pipefail

SKIP_TESTS=0
SKIP_PACKAGE=0
PYTHON_BIN="${PYTHON_BIN:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-tests)
      SKIP_TESTS=1
      shift
      ;;
    --skip-package)
      SKIP_PACKAGE=1
      shift
      ;;
    --python)
      PYTHON_BIN="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

resolve_python() {
  if [[ -n "$PYTHON_BIN" ]]; then
    if [[ -x "$PYTHON_BIN" ]]; then
      echo "$PYTHON_BIN"
      return
    fi
    if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
      command -v "$PYTHON_BIN"
      return
    fi
    echo "Requested python not found: $PYTHON_BIN" >&2
    exit 1
  fi

  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    echo "$ROOT_DIR/.venv/bin/python"
    return
  fi

  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi

  if command -v python >/dev/null 2>&1; then
    command -v python
    return
  fi

  echo "No Python interpreter found." >&2
  exit 1
}

PY="$(resolve_python)"

if [[ ! -x "$ROOT_DIR/.venv/bin/python" && -z "${PYTHON_BIN}" ]]; then
  BUILD_VENV="$ROOT_DIR/.packaging-venv"
  if [[ ! -x "$BUILD_VENV/bin/python" ]]; then
    echo "No .venv found. Creating isolated build env at $BUILD_VENV ..."
    "$PY" -m venv "$BUILD_VENV"
  fi
  PY="$BUILD_VENV/bin/python"
fi

echo "[1/4] Installing build dependencies..."
echo "Using Python: $PY"
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -r requirements-dev.txt pyinstaller

if [[ "$SKIP_TESTS" -eq 0 ]]; then
  echo "[2/4] Running smoke tests..."
  QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q tests/test_ui_smoke.py tests/test_ui_admin_features.py
else
  echo "[2/4] Skipping tests (--skip-tests)."
fi

echo "[3/4] Building desktop executable (PyInstaller)..."
rm -rf build dist/Scheduler dist/Scheduler.app

PYI_ARGS=(
  -m PyInstaller
  --noconfirm
  --clean
  --windowed
  --onedir
  --name Scheduler
  --add-data "app_icon.png:."
  --add-data "README.md:."
  --add-data "LICENSE:."
  --collect-binaries ortools
  --collect-data ortools
  --hidden-import ortools.sat.python.cp_model_helper
  --hidden-import ortools.util.python.sorted_interval_list
  --exclude-module pytest
  --exclude-module torch
  --exclude-module torchvision
  --exclude-module onnx
  --exclude-module onnxruntime
  --exclude-module tensorflow
  --exclude-module matplotlib
  --exclude-module IPython
  ui/app.py
)
"$PY" "${PYI_ARGS[@]}"

if [[ "$SKIP_PACKAGE" -eq 1 ]]; then
  echo "[4/4] Skipping package archive (--skip-package)."
  echo "Portable app folder: $ROOT_DIR/dist/Scheduler"
  exit 0
fi

echo "[4/4] Building platform archive..."
OS_NAME="$(uname -s)"
if [[ "$OS_NAME" == "Darwin" ]]; then
  OUT="$ROOT_DIR/dist/Scheduler-macos-v1.0.zip"
  rm -f "$OUT"
  if [[ -d "$ROOT_DIR/dist/Scheduler.app" ]]; then
    (cd "$ROOT_DIR/dist" && zip -qry "$(basename "$OUT")" Scheduler.app)
  else
    (cd "$ROOT_DIR/dist" && zip -qry "$(basename "$OUT")" Scheduler)
  fi
  echo "macOS package built at: $OUT"
elif [[ "$OS_NAME" == "Linux" ]]; then
  OUT="$ROOT_DIR/dist/Scheduler-linux-v1.0.tar.gz"
  rm -f "$OUT"
  tar -czf "$OUT" -C "$ROOT_DIR/dist" Scheduler
  echo "Linux package built at: $OUT"
else
  echo "Unsupported OS for package archive: $OS_NAME" >&2
  exit 1
fi
