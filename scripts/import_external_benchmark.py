from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from benchmarks.itc2007 import load_itc2007_instance
from benchmarks.itc2019 import inspect_itc2019_xml
from utils.generator import write_instance


def main() -> int:
    parser = argparse.ArgumentParser(description="Import or inspect an external timetabling benchmark.")
    parser.add_argument("family", choices=["itc2007", "itc2019"])
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if args.family == "itc2007":
        write_instance(load_itc2007_instance(args.source), args.out)
    else:
        inspection = inspect_itc2019_xml(args.source)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(inspection.to_dict(), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
