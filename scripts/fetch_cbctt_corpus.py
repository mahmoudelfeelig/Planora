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
    fetch_cbctt_corpus,
    verify_cached_cbctt_corpus,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch and verify the pinned, non-vendored CB-CTT external corpus "
            "from Software Heritage, then generate explicit lossy ITC-2007 "
            "four-term projections."
        )
    )
    parser.add_argument(
        "--cache-directory",
        type=Path,
        default=CBCTT_DEFAULT_CACHE,
        help="Ignored local cache (repository-local paths must be under data/).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="Per-request Software Heritage timeout.",
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
        help="Do not access the network; verify the existing cache and projections.",
    )
    args = parser.parse_args(argv)

    if args.verify_only:
        report = verify_cached_cbctt_corpus(args.cache_directory)
    else:
        report = fetch_cbctt_corpus(
            args.cache_directory,
            timeout_seconds=args.timeout_seconds,
            workers=args.workers,
        )
    summary = {
        "cache_directory": report["cache_directory"],
        "distinct_instance_files": (
            report.get("distinct_instance_files")
            or report["corpus"]["distinct_instance_files"]
        ),
        "families": report.get("families") or report["corpus"]["families"],
        "source_manifest_sha256": (
            report.get("source_manifest_sha256")
            or report["corpus"]["source_manifest_sha256"]
        ),
        "projection_set_sha256": (
            report.get("projection_set_sha256")
            or report["corpus"]["projection_set_sha256"]
        ),
        "mode": "verify-only" if args.verify_only else "fetch-and-project",
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
