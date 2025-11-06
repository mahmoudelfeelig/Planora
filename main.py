from ortools.sat.python import cp_model
from generator import generate_instance
from solver_cp_sat import TimetableSolver
from metaheuristics import LocalSearchImprover


def main():
    # modes: "small_demo", "block_profs", "labs_only", "mixed_large", "random"
    inst = generate_instance(mode="mixed_large")

    solver_model = TimetableSolver(inst)
    cp_solver, status = solver_model.solve(time_limit_seconds=120)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("No feasible schedule; status:", status)
        return

    schedule = solver_model.extract_solution(cp_solver)
    print("CP-SAT objective:", cp_solver.ObjectiveValue())

    ls = LocalSearchImprover(inst, solver_model)
    approx_penalty = ls.compute_soft_penalty(schedule)
    print("Approx soft penalty (local evaluator):", approx_penalty)

    # dump some of the schedule
    for a_id, info in sorted(schedule.items())[:200]:
        print(
            f"A{a_id}: week {info['week']} {info['day']} "
            f"slot {info['slot']} dur {info['duration']} "
            f"room {info['room_id']} staff {info['staff_id']} "
            f"course {info['course_id']} kind {info['kind']} "
            f"groups {info['group_ids']}"
        )


if __name__ == "__main__":
    main()
