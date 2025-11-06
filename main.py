from ortools.sat.python import cp_model
from generator import generate_instance
from solver_cp_sat import TimetableSolver
from metaheuristics import LocalSearchImprover


def main():
    # Choose mode: "small_demo", "block_profs", "labs_only", "mixed_large", "random"
    inst = generate_instance(mode="small_demo")

    solver_model = TimetableSolver(inst)
    cp_solver, status = solver_model.solve(time_limit_seconds=60)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("No feasible schedule found; CP-SAT status:", status)
        return

    schedule = solver_model.extract_solution(cp_solver)
    print(f"Found schedule with objective {cp_solver.ObjectiveValue()}")

    # Optional: run local-search penalty evaluation
    ls = LocalSearchImprover(inst, solver_model)
    penalty = ls.compute_soft_penalty(schedule)
    print("Approximate soft penalty from local search evaluator:", penalty)

    # Simple textual dump per activity
    for a_id, info in sorted(schedule.items()):
        print(
            f"A{a_id}: week {info['week']} {info['day']} slot {info['slot']} "
            f"dur {info['duration']} room {info['room_id']} staff {info['staff_id']} "
            f"course {info['course_id']} kind {info['kind']} groups {info['group_ids']}"
        )


if __name__ == "__main__":
    main()
