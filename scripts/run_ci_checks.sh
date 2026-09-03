#!/usr/bin/env bash
set -euo pipefail

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
export QT_OPENGL="${QT_OPENGL:-software}"
export PYTHONPATH="."
export PYTHONHASHSEED="${PYTHONHASHSEED:-0}"
export TT_CP_WORKERS="${TT_CP_WORKERS:-4}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python || command -v python3)}"

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "No python interpreter found on PATH" >&2
  exit 1
fi

# Compile only project sources (avoid traversing virtualenv and caches).
"${PYTHON_BIN}" -m compileall -q api core product services ui utils tests main.py scripts
"${PYTHON_BIN}" -m ruff check api core product services ui utils tests main.py scripts

# Coverage wraps each ordinary test exactly once. The real-time SLA test runs
# without tracing because tracing changes the behavior being measured.
COVERAGE_ARGS=(
  --cov=api
  --cov=core
  --cov=services
  --cov=utils
  --cov-branch
  --cov-context=test
  --cov-config=pyproject.toml
  --cov-report=
)
RELEASE_ARTIFACT_FILE="tests/test_release_artifacts.py"
mapfile -t ORDINARY_TEST_FILES < <(
  find tests -type f -name 'test_*.py' ! -path "${RELEASE_ARTIFACT_FILE}" -print | sort
)
if [[ ${#ORDINARY_TEST_FILES[@]} -eq 0 ]]; then
  echo "No ordinary test files found" >&2
  exit 1
fi

mkdir -p cover
"${PYTHON_BIN}" -m coverage erase

# Phase 1: quick feedback tests. The marker slice is still part of this phase.
timeout 20m "${PYTHON_BIN}" -m pytest -q \
  -m "timing_sensitive" \
  "${ORDINARY_TEST_FILES[@]}"
timeout 20m "${PYTHON_BIN}" -m pytest -q \
  -m "not slow and not timing_sensitive" \
  "${COVERAGE_ARGS[@]}" \
  "${ORDINARY_TEST_FILES[@]}"

# Phase 2: slower integration and UI tests.
timeout 25m "${PYTHON_BIN}" -m pytest -q \
  -m "slow and not timing_sensitive" \
  --cov-append \
  "${COVERAGE_ARGS[@]}" \
  "${ORDINARY_TEST_FILES[@]}"

"${PYTHON_BIN}" -m coverage report
"${PYTHON_BIN}" -m coverage json -o cover/critical-coverage.json
"${PYTHON_BIN}" -m coverage xml -o cover/critical-coverage.xml

# Bind the generated coverage reports to the exact covered source bytes. The
# release verifier replays this manifest inside the frozen bundle, preventing a
# green but stale coverage report from being paired with later source edits.
"${PYTHON_BIN}" - <<'PY'
from __future__ import annotations

import hashlib
import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


root = Path.cwd().resolve()
json_path = root / "cover" / "critical-coverage.json"
xml_path = root / "cover" / "critical-coverage.xml"
output_path = root / "cover" / "critical-coverage-source-manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


coverage = json.loads(json_path.read_text(encoding="utf-8"))
raw_files = coverage.get("files")
if not isinstance(raw_files, dict) or not raw_files:
    raise SystemExit("coverage JSON has no covered source files")
with (root / "pyproject.toml").open("rb") as handle:
    project_configuration = tomllib.load(handle)
configured_files = project_configuration["tool"]["coverage"]["report"]["include"]
if not isinstance(configured_files, list) or not configured_files:
    raise SystemExit("pyproject.toml critical coverage include scope is empty")
if set(raw_files) != set(configured_files) or len(configured_files) != len(set(configured_files)):
    raise SystemExit(
        "coverage JSON does not exactly match the pyproject.toml include scope"
    )

source_files: list[dict[str, object]] = []
for relative in sorted(raw_files):
    relative_path = PurePosixPath(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise SystemExit(f"unsafe covered source path: {relative}")
    source = root.joinpath(*relative_path.parts)
    if not source.is_file():
        raise SystemExit(f"covered source file is missing: {relative}")
    source_files.append(
        {
            "path": relative,
            "sha256": sha256(source),
            "bytes": source.stat().st_size,
        }
    )

canonical_sources = json.dumps(
    source_files,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")
payload = {
    "schema_version": "planora.critical-coverage-source-manifest.v1",
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "coverage_json": {
        "path": "cover/critical-coverage.json",
        "sha256": sha256(json_path),
        "bytes": json_path.stat().st_size,
    },
    "coverage_xml": {
        "path": "cover/critical-coverage.xml",
        "sha256": sha256(xml_path),
        "bytes": xml_path.stat().st_size,
    },
    "source_files": source_files,
    "source_file_count": len(source_files),
    "source_set_sha256": hashlib.sha256(canonical_sources).hexdigest(),
}

# Detect source/report changes that race manifest construction.
for row in source_files:
    source = root.joinpath(*PurePosixPath(str(row["path"])).parts)
    if source.stat().st_size != row["bytes"] or sha256(source) != row["sha256"]:
        raise SystemExit(f"covered source changed while manifesting: {row['path']}")
if payload["coverage_json"]["sha256"] != sha256(json_path):
    raise SystemExit("coverage JSON changed while manifesting")
if payload["coverage_xml"]["sha256"] != sha256(xml_path):
    raise SystemExit("coverage XML changed while manifesting")

temporary = output_path.with_name(f".{output_path.name}.tmp")
temporary.write_text(
    json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n",
    encoding="utf-8",
)
temporary.replace(output_path)
PY

"${PYTHON_BIN}" scripts/check_critical_coverage.py \
  --coverage-json cover/critical-coverage.json \
  --baseline config/critical_coverage_baseline.json

# This contract consumes the reports above, so it is intentionally verified
# once after coverage generation instead of participating in its own input.
timeout 5m "${PYTHON_BIN}" -m pytest -q "${RELEASE_ARTIFACT_FILE}"
