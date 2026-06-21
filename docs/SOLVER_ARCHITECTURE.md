# Solver Architecture

## Hybrid Strategy

Planora uses a hybrid scheduling strategy:

- CP-SAT handles hard feasibility and bounded exact search.
- Greedy rooming can decouple room assignment for large instances.
- Local search improves soft quality after a feasible schedule exists.
- Focused CP-SAT polish freezes most of the timetable and optimizes a small neighborhood.

## CP-SAT Phase

The CP model chooses activity starts and, in strict mode, rooms. It enforces:

- group no-overlap
- staff no-overlap
- room no-overlap when CP rooming is enabled
- availability
- locks
- selected institutional hard rules

When an objective is enabled, the CP model minimizes weighted soft penalties and can expose objective value, best bound, and gap.

## Local Search Phase

Local search starts from a feasible schedule. It evaluates moves by soft penalty:

- student free days
- Mon-Fri free days
- gaps
- thin days
- single-slot days
- late starts
- active days
- staff free day
- week-to-week stability
- room consistency
- same-kind-in-week repetition

Focused improvement temporarily boosts one term's weight during local search.

## Neighborhood CP-SAT

For large instances, global CP-SAT optimization can become too large. The project therefore supports neighborhood solving:

1. identify affected activities
2. freeze unaffected activities as locks
3. solve the smaller model
4. restore the user's original lock settings afterward

This is used for conflict repair and focused CP-SAT polish.

## Scaling Rule

Use global CP-SAT for feasibility and verification on small/medium instances. Use greedy rooming plus local search or neighborhood CP-SAT for SS23-scale data.
