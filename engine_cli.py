import sys
import pickle
from pathlib import Path
from typing import Dict, Any

from ortools.sat.python import cp_model
from domain import Instance
from solver_cp_sat import TimetableSolver


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: engine_cli.py instance.pkl result.pkl", file=sys.stderr)
        return 1

    inst_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    if not inst_path.exists():
        print(f"Instance file not found: {inst_path}", file=sys.stderr)
        return 2

    with inst_path.open("rb") as f:
        inst = pickle.load(f)
    if not isinstance(inst, Instance):
        print("Loaded object is not an Instance", file=sys.stderr)
        return 3

    solver_model = TimetableSolver(inst)
    cp_solver, status = solver_model.solve(time_limit_seconds=60)

    result: Dict[str, Any] = {
        "status": int(status),
        "objective": 0.0,
        "schedule": {},
    }

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        result["objective"] = float(cp_solver.ObjectiveValue())
        result["schedule"] = solver_model.extract_solution(cp_solver)

    with out_path.open("wb") as f:
        pickle.dump(result, f)

    return 0


if __name__ == "__main__":
    sys.exit(main())
