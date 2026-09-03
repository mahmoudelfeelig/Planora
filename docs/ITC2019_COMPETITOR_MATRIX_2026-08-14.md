# ITC-2019 open-source competitor matrix

## Scope

The controlled matrix ran the exact 30 competition instance names shown on the
authenticated ITC-2019 Results page against four pinned implementations:
Planora, Gashi simulated annealing, UniTime/CPSolver, and the Lemos MaxSAT
finalist. It used one seed, one repetition, one worker, one host, one CPU
affinity, and a nominal ten-second solver budget, for 120 planned and 120
recorded runs.

This is a descriptive same-host quality comparison under nominal solver
budgets. The upstream programs expose different timeout and memory mechanisms,
so the matrix does not support an equal-wall runtime, speed, or general
superiority claim.

## Outcome

Only three of the 120 runs emitted complete locally valid solutions within the
bounded process window, all from CPSolver:

| Instance | Local total | Official competition best | Outcome |
|---|---:|---:|---|
| `mary-spr17` | 18,390 | 14,910 | worse |
| `lums-spr18` | 282 | 95 | worse |
| `nbi-spr18` | 35,608 | 18,014 | worse |

The missing coverage is attributable to solver outcomes, not omitted matrix
rows:

| Solver | Valid | Timed out | Outputs written | Invalid outputs |
|---|---:|---:|---:|---:|
| Planora | 0/30 | 25 | 0 | 0 |
| Gashi SA | 0/30 | 3 | 27 | 27 |
| UniTime/CPSolver | 3/30 | 27 | 5 | 2 |
| Lemos MaxSAT | 0/30 | 27 | 4 | 4 |

This distribution is why simply relabeling or resuming the old report cannot
create publication-scale effective coverage.

All three emitted solutions were uploaded through the authenticated official
ITC-2019 validator. The official total and all four component values agreed
with Planora's independent scorer for 3/3. Official-selection completeness is
still false because the other 117 conditions produced no complete valid output
to upload.

A separate controlled `lums-sum17` smoke remains the strongest four-way parity
point. Planora, Gashi, CPSolver, and MaxSAT each produced total 4, and all four
authenticated official-validator uploads agreed component by component. That
single-instance parity is not a broad competitor win.

## Current release gate

The competitor runner and authenticated validator workflow have since been
hardened around manifest-derived run identities, atomic checkpoints, bound
output hashes, resumable official-validation evidence, and explicit unseeded
MaxSAT trial identities. Those changes make the next matrix auditable; they do
not retroactively make the ten-second run publication-scale evidence.

A fresh diagnostic on the current engine confirms the boundary. The small
`lums-sum17` case still reaches an independently valid optimum of 4 in 3.60
seconds with one worker. On `lums-spr18`, neither the exact factorized model nor
an experimental required-component seed produced a complete schedule at the
tested short budget. The experimental path was therefore rejected and the
exact fail-closed model retained.

The next publication run is gated on a pre-registered feasibility pilot that
produces complete, independently valid outputs across representative small,
medium, and large competition instances. Only after that pilot passes should
the full 30-instance matrix run. Increasing the same ineffective ten-second
condition across 120 cells would add cost without increasing evidentiary
coverage.

Equal-wall and equal-memory speed claims remain prohibited. The current harness
supports same-host nominal-budget quality comparison because the four upstream
solvers still use materially different timeout and memory mechanisms. A future
speed study requires one common external wall controller and one verified
memory limit applied to every complete solver process; sampled RSS or solver
specific heap flags are not equivalent controls.

## Evidence

- `output/itc2019-open-source-competition-30-seed17-10s-20260813/report.json`
- `output/itc2019-open-source-competition-30-seed17-10s-20260813/comparison-summary.json`
- `paper/evidence/itc2019_official_results_page_2026-08-13.json`
- `output/itc2019-host-competitor-smoke-10s/report.json`
