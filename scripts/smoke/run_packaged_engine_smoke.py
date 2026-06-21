from __future__ import annotations

import argparse
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.generator import generate_instance  # noqa: E402
from utils.io import schedule_from_rows  # noqa: E402
from utils.specs import validate_schedule_against_instance  # noqa: E402


def _run_engine(engine_exe: Path, in_path: Path, out_path: Path) -> None:
    cmd = [str(engine_exe), str(in_path), str(out_path)]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Engine smoke failed with code {completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test a packaged Planora solver worker")
    parser.add_argument("--engine-exe", required=True, help="Path to SchedulerEngine executable")
    args = parser.parse_args(argv)

    engine_exe = Path(args.engine_exe).resolve()
    if not engine_exe.exists():
        raise FileNotFoundError(f"Engine executable not found: {engine_exe}")

    inst = generate_instance("small_demo")
    with tempfile.TemporaryDirectory(prefix="planora-engine-smoke-") as tmp_dir:
        tmp = Path(tmp_dir)
        in_path = tmp / "instance.pkl"
        out_path = tmp / "result.pkl"
        in_path.write_bytes(pickle.dumps(inst))
        _run_engine(engine_exe, in_path, out_path)
        if not out_path.exists():
            raise RuntimeError("Smoke test failed: result pickle was not produced.")
        payload = pickle.loads(out_path.read_bytes())
        status = int(payload.get("status", -999))
        if status not in (0, 4):
            raise RuntimeError(f"Engine smoke returned non-feasible status {status}: {payload}")
        schedule = payload.get("schedule") or {}
        if not isinstance(schedule, dict) or not schedule:
            raise RuntimeError("Engine smoke returned an empty schedule.")
        errors = validate_schedule_against_instance(inst, schedule, strict_rooms=True)
        if errors:
            raise RuntimeError("Engine smoke produced invalid schedule:\n" + "\n".join(errors[:20]))
    print(f"Packaged engine smoke passed: {engine_exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
