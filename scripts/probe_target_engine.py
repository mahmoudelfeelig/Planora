from __future__ import annotations

import os
import pickle
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from main import normalize_instance_for_spec, stamp_instance_time
from utils.generator import generate_instance


def main() -> int:
    root = ROOT
    inst = generate_instance("target_case")
    normalize_instance_for_spec(inst)
    stamp_instance_time(inst, "08:30", 90, 0)

    with tempfile.TemporaryDirectory() as temp_dir:
        in_path = Path(temp_dir) / "inst.pkl"
        out_path = Path(temp_dir) / "res.pkl"
        in_path.write_bytes(pickle.dumps(inst))

        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(root),
                "TT_ROOM_MODE": os.getenv("TT_ROOM_MODE", "cp_rooms"),
                "TT_TIME_LIMIT": os.getenv("TT_TIME_LIMIT", "20"),
                "TT_CP_WORKERS": os.getenv("TT_CP_WORKERS", "1"),
                "TT_USE_OBJECTIVE": os.getenv("TT_USE_OBJECTIVE", "1"),
                "TT_OBJECTIVE_PROFILE": os.getenv("TT_OBJECTIVE_PROFILE", "quality_first"),
                "TT_PHASED_SOLVE": os.getenv("TT_PHASED_SOLVE", "1"),
            }
        )
        started = time.perf_counter()
        proc = subprocess.run(
            [
                sys.executable,
                str(root / "core" / "engine_cli.py"),
                str(in_path),
                str(out_path),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=float(os.getenv("PROBE_TIMEOUT_SECONDS", "60")),
        )
        elapsed = time.perf_counter() - started
        print(f"return={proc.returncode} elapsed={elapsed:.2f}s")
        if proc.stdout:
            print(proc.stdout[-4000:])
        if proc.stderr:
            print(proc.stderr[-4000:], file=sys.stderr)
        print(f"result_exists={out_path.exists()}")
        if out_path.exists():
            result = pickle.loads(out_path.read_bytes())
            print(f"status={result.get('status')}")
            print(f"activities={len(result.get('schedule') or {})}")
            print(f"meta={result.get('meta')}")
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
