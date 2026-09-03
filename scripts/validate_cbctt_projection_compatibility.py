from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from benchmarks.cbctt_corpus import (
    CBCTT_DEFAULT_CACHE,
    validate_cbctt_projection_compatibility,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check cached CB-CTT four-term projections against the official "
            "ITC-2007 validator using an independently predictable empty solution."
        )
    )
    parser.add_argument("--validator", type=Path, required=True)
    parser.add_argument(
        "--cache-directory",
        type=Path,
        default=CBCTT_DEFAULT_CACHE,
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "JSON evidence path; defaults to OFFICIAL_VALIDATOR_COMPATIBILITY.json "
            "inside the ignored cache."
        ),
    )
    args = parser.parse_args(argv)

    report = validate_cbctt_projection_compatibility(
        args.validator,
        args.cache_directory,
        timeout_seconds=args.timeout_seconds,
    )
    output = args.output or (
        args.cache_directory / "OFFICIAL_VALIDATOR_COMPATIBILITY.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "all_compatible": report["all_compatible"],
                "checked_instances": report["checked_instances"],
                "output": str(output.resolve()),
                "projection_set_sha256": report["projection_set_sha256"],
                "validator_command_manifest_sha256": report[
                    "validator_command_manifest_sha256"
                ],
                "validator_sha256": report["validator_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
