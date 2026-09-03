from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from benchmarks.itc2019_corpus import (
    ITC2019_PUBLIC_DEFAULT_CACHE,
    fetch_itc2019_public_corpus,
    verify_cached_itc2019_public_corpus,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch or verify the pinned ITC-2019 XML mirror from the public "
            "MPPTimetables finalist repository, then run Planora's fail-closed "
            "semantic parser and explicitly scoped local solution validator."
        )
    )
    parser.add_argument(
        "--cache-directory",
        type=Path,
        default=ITC2019_PUBLIC_DEFAULT_CACHE,
        help="Ignored local cache (repository-local caches must be under data/).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=60.0,
        help="Per-request GitHub timeout.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Bounded number of parallel content downloads.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Do not access the network; verify and reanalyze the existing cache.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Optionally copy the full machine-readable report to this path.",
    )
    args = parser.parse_args(argv)

    if args.verify_only:
        report = verify_cached_itc2019_public_corpus(args.cache_directory)
    else:
        report = fetch_itc2019_public_corpus(
            args.cache_directory,
            timeout_seconds=args.timeout_seconds,
            workers=args.workers,
        )
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    problem = report["problem_parsing"]
    solution = report["solution_validation"]
    summary = {
        "cache_directory": report["cache_directory"],
        "source_commit": report["source"]["commit"],
        "source_manifest_sha256": report["source"]["source_manifest_sha256"],
        "problem_files": report["corpus"]["problem_files"],
        "problem_structural_xml_passed": problem["structural_xml_passed"],
        "problem_semantic_passed": problem["semantic_passed"],
        "problem_semantic_rejected": problem["semantic_rejected"],
        "solution_files": report["corpus"]["solution_files"],
        "solution_xml_parsed": solution["solution_xml_parsed"],
        "solutions_locally_valid_for_implemented_scope": solution[
            "locally_valid_for_implemented_scope"
        ],
        "solutions_locally_invalid_for_implemented_scope": solution[
            "locally_invalid_for_implemented_scope"
        ],
        "official_validator": report["validation_scope"]["official_validator"],
        "mode": "verify-only" if args.verify_only else "fetch-and-verify",
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
