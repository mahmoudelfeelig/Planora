# ITC-2007 benchmark and course-orbit ablation

Planora now has a validator-backed ITC-2007 Curriculum-Based Course
Timetabling benchmark path. The harness runs each solver in a fresh process,
pins one CPU and one solver worker, exports the official `.out` format, invokes
the official C++ validator, and stores JSONL records plus a manifest and
summary. It records end-to-end and worker wall/CPU time, official objective
components, solver bounds when they are meaningful, seeds, dependency
versions, instance and validator hashes, and a per-file source snapshot.

The source guard hashes every Python file under `benchmarks`, `core`,
`services`, and `utils`. A changed file during a matrix marks the current row
as mismatched, leaves the summary incomplete, and stops the run. Benchmark
output directories must be new so evidence is never silently overwritten.

## Course-lecture symmetry

The official format identifies course placements rather than individual
lecture occurrences. If a course has `k` lectures, its synthetic Planora
activity labels therefore create up to `k!` equivalent representatives. The
optional formulation adds

```text
start[a_1] < start[a_2] < ... < start[a_k]
```

for each verified course orbit. Strictness is valid because all lectures of an
ITC course share a unary teacher/group resource and therefore cannot start
together. Before adding the cut, the solver checks metadata, complete start and
room domains, activity resources, locks, clusters, precedence, and distribution
relations. An enriched course that is no longer interchangeable is skipped.

Official `.out` imports are canonicalized using the same order. On the
officially feasible comp01 CPSolver schedule, canonicalization preserved the
exact row multiset, zero hard violations, and official score 5 while producing
strict order for all 30 courses.

## Clean comp01 pilot

The clean ablation used comp01, seeds 17/23/31, a configured 10-second solver
budget, one worker, CPU 0, the `research_adaptive` strategy, and the official
validator binary with SHA-256
`6b991efa2195ed59f9e514532d9add65b4790791bd6de054ce6f5cbdc19546b3`.
Both variants used the identical Planora source snapshot
`0f044498a7bc42215b8a41f6f519d45829eda692fa41d38e848dbe37bcea0262`.
Every run was officially feasible with zero hard violations, and every internal
score matched the validator.

| Seed | Symmetry off | Symmetry on | On minus off |
| ---: | ---: | ---: | ---: |
| 17 | 503 | 485 | -18 |
| 23 | 365 | 644 | +279 |
| 31 | 327 | 256 | -71 |
| Mean | 398.33 | 461.67 | +63.33 |
| Median | 365 | 485 | +120 |

Lower is better. The cut improved two seeds but regressed one sharply, worsened
the mean and median official objective, and increased median end-to-end wall
time from 12.79 to 13.35 seconds. This is a negative or inconclusive engineering
pilot, not evidence of an optimization win. The cut is consequently default
off and remains available only as an explicit research ablation.

The machine-readable evidence is in
`paper/evidence/itc2007_comp01_symmetry_ablation_2026-08-11.json`. Raw artifacts
are in `output/itc2007-ablation-comp01-symmetry-off-idle-10s` and
`output/itc2007-ablation-comp01-symmetry-on-idle-10s`.

## Reproduction

Symmetry off:

```bash
.venv/bin/python scripts/benchmark_itc2007.py run --instances /tmp/planora-itc2007-cpsolver/data/ctt/comp01.ctt --seeds 17 23 31 --time-limit-seconds 10 --validator /tmp/planora-itc2007-validator --cpsolver-root /tmp/planora-itc2007-cpsolver --classes /tmp/planora-itc2007-build/classes --output-directory output/itc2007-ablation-comp01-symmetry-off-idle-10s --repo-root /mnt/d/Stuff/Projects/Sites/Planora --python-command /mnt/d/Stuff/Projects/Sites/Planora/.venv/bin/python --workers 1 --cpu 0 --strategy research_adaptive --itc2007-course-symmetry off --solvers planora
```

Symmetry on:

```bash
.venv/bin/python scripts/benchmark_itc2007.py run --instances /tmp/planora-itc2007-cpsolver/data/ctt/comp01.ctt --seeds 17 23 31 --time-limit-seconds 10 --validator /tmp/planora-itc2007-validator --cpsolver-root /tmp/planora-itc2007-cpsolver --classes /tmp/planora-itc2007-build/classes --output-directory output/itc2007-ablation-comp01-symmetry-on-idle-10s --repo-root /mnt/d/Stuff/Projects/Sites/Planora --python-command /mnt/d/Stuff/Projects/Sites/Planora/.venv/bin/python --workers 1 --cpu 0 --strategy research_adaptive --itc2007-course-symmetry on --solvers planora
```

## Claim boundary and next gate

The earlier Planora-versus-CPSolver comp01 artifact remains useful engineering
evidence: under its older source snapshot and seed 17, both schedules were
officially feasible and scored 568 versus 5. It is not a headline result, uses
only one seed, and must not be combined with this ablation as if the source were
identical.

A paper-grade claim requires all 21 ITC-2007 instances, a predeclared seed set,
counterbalanced variant/solver order, identical hardware and limits, official
validation, paired statistical analysis, and no source drift. Until that gate
passes, no superiority claim is supported.

## Official-aware adaptive seeding

A second bounded pilot tested the adaptive neighborhood policy while course
symmetry remained off. The prior policy cold-started all certificate arms even
when no certificate existed; those arms silently fell back to random singleton
seeds. On comp01 with zero certificates, the first three rounds were therefore
`certificate:12`, `certificate:24`, and `certificate:48` with empty lineage.

The retained policy exposes only context-eligible families to UCB. Its ITC
penalty arm attributes support directly from room-capacity overflow, missing
working days, isolated curriculum lectures, and minority-room stability. Trace
rows record the eligible families and typed support for each selected seed.

The same-source pilot used source snapshot
`40f536f895a1d94db9f69401c2f937b4905222e0e11beb5e584a7ab7c7205c30`,
comp01, seeds 17/23/31, 10 seconds, one worker, CPU 0, course symmetry off, and
the official validator.

| Seed | Prior policy | Official-aware policy | New minus prior |
| ---: | ---: | ---: | ---: |
| 17 | 503 | 479 | -24 |
| 23 | 409 | 390 | -19 |
| 31 | 327 | 262 | -65 |
| Mean | 413 | 377 | -36 |
| Median | 409 | 390 | -19 |

The candidate improved all three paired seeds and reduced mean official cost by
8.72 percent. Median end-to-end wall time fell from 13.55 to 13.17 seconds. Its
median CPU time increased by about 13.1 percent, so this is a fixed-wall quality
gain, not a CPU-efficiency claim. All six schedules were officially feasible,
had zero hard violations, matched internal scoring, and passed the source-drift
guard. Imported ITC-2007 instances therefore enable this policy by default,
while an explicit harness switch preserves the baseline ablation.

Machine-readable evidence and exact commands are in
`reports/itc2007_adaptive_seeding_ablation_2026-08-11.json`. The result remains
a one-instance engineering gate; the 21-instance paper gate above is unchanged.

## Single-seed 21-instance external breadth gate

The retained adaptive policy was then compared with the CPSolver/UniTime
ITC-2007 entry on comp01 through comp21. The run used seed 17, a configured
10-second solver budget, one worker, CPU 0, course symmetry off, and
counterbalanced first position by instance. All 42 solver records matched the
same 66-file Planora source snapshot
`7b92d74fdbdd62c7f3eef9dd8faefb2268719b2d7401fbf53d10ac13751913d9`.

CPSolver produced officially feasible schedules on 21/21 instances; Planora
did so on 17/21. CPSolver won all 21 feasibility-first comparisons and had the
lower official objective on all 17 common-feasible instances, giving Planora 0
wins, 0 ties, and 21 losses. All 38 produced schedules passed the official
validator with zero hard violations. Planora's internal official score matched
the external validator on all 17 of its schedules.

Across the 17 common-feasible instances, Planora's official objectives summed
to 15,435 versus 2,940 for CPSolver, a 5.25 ratio of sums. Among the 16 pairs
with a positive CPSolver denominator, the median Planora/CPSolver score ratio
was 7.52. Comp11 is excluded from that ratio statistic because CPSolver scored
zero while Planora scored 661. Median fresh-process wall time was 13.30 seconds
for Planora and 10.68 seconds for CPSolver; these measurements include Python
or JVM startup but exclude the later validator process.

The four Planora failures were comp07, comp19, comp20, and comp21. Each stopped
after the approximately three-second initial feasibility slice returned
`UNKNOWN`; none used the remaining adaptive budget. On the common-feasible
instances, weighted room-capacity cost was 3,592 for Planora versus 116 for
CPSolver. Those observations make incumbent construction, full-budget
feasibility fallback, and capacity-aware room assignment the next material
optimization targets.

This breadth result rejects a Planora-superiority claim at the tested
configuration. It is still only one disclosed seed, so it is not a statistical
superiority study and does not replace the replicated paper gate. Exact rows,
timing accounting, hashes, command, and claim boundary are in
`reports/itc2007_breadth_21_seed17_2026-08-11.json`; raw evidence is in
`output/itc2007-breadth-21-candidate-vs-cpsolver-10s-seed17`.

## Strict-budget feasibility rescue follow-up

The first breadth gate exposed a budget-stranding defect: comp07, comp19,
comp20, and comp21 returned `UNKNOWN` after the three-second initial
feasibility slice and never used the seven-second adaptive allocation because
no incumbent existed. The retained rescue does not change the 30/70 split. If
the initial phase has no completely validated incumbent, it spends the
remaining search allocation on the same objective-free, validator-compatible
feasibility path with a deterministic base-seed-plus-one diversification. It
accepts only a complete strict-room schedule. A bounded finalization reserve
keeps extraction, validation, quality scoring, and result construction inside
the shared total deadline.

The source-hashed full-corpus rerun used source snapshot
`38ab6a3b36d66779a6772e30c369bcec18f467ab914f7a391556c518a2a899d4`.
Planora produced 21/21 officially feasible schedules, compared with 17/21 in
the pre-rescue artifact. All had zero hard violations and exact internal versus
external score agreement. `solve_instance` elapsed time ranged from 7.48 to
9.83 seconds, with zero deadline overrun on all 21 runs.

For the external comparison, the report reuses only the immutable 21 CPSolver
rows from the preceding breadth artifact. The two manifests match on instance
hashes, seed, 10-second limit, one worker, CPU 0, hardware, platform, validator,
and CPSolver classes. This reuse is explicitly not an interleaved or replicated
competitor rerun.

Planora still recorded 0 wins, 0 ties, and 21 losses. Its total official score
was 20,170 versus 3,586 for CPSolver, a 5.62 ratio of sums. The largest
component disparity remains weighted room capacity, 4,885 versus 135, a 36.19
ratio. The feasibility release blocker is resolved for this gate; the external
quality gate remains failed, and no superiority claim is supported.

Exact scores, old-versus-rescue comparison, component sums, timing
distributions, artifact hashes, compatibility checks, and commands are in
`reports/itc2007_breadth_21_rescue_seed17_2026-08-11.json`. The new raw Planora
artifact is `output/itc2007-breadth-21-planora-rescue-seed17-10s`.

## Fixed-time room-dive breadth gate

The default-off fixed-time room dive was evaluated as a counterbalanced
single-seed engineering ablation after a three-seed comp01 pilot. The breadth
gate used comp01 through comp21, seed 17, 10 configured solver seconds, one
worker, CPU 0, `research_adaptive`, course symmetry off, and official-aware
adaptive seeding on. Odd-numbered instances ran OFF then ON; even-numbered
instances ran ON then OFF. Every variant-instance case used a fresh process
and a fresh immutable output directory.

All 42 schedules were officially feasible with zero hard violations. Internal
and external official components matched exactly for all 42 records, and all
records matched source snapshot
`0a72cc1e8a029720cf3536c4ee3401cd92b9c79f711322c4638dea8520bdc19d`.
ON was better on 5 instances, tied on 14, and worse on 2. Its official
objective sum was 19,711 versus 20,360 for OFF, a 3.19 percent reduction.

That quality result does not pass the release gate. OFF had zero total
`solve_instance` deadline overruns, while ON exceeded the shared 10-second
deadline on comp06, comp07, comp10, comp16, comp19, comp20, and comp21. The
largest overrun was 303.0 milliseconds. Every dive reported zero dive-local
overrun, demonstrating that local phase accounting alone is insufficient;
admission and finalization must be governed by the shared total deadline.

Only comp01 and comp05 accepted an improved room assignment, reducing their
within-run official objectives by 246 and 157 respectively. The other paired
changes occurred before the dive: comp13, comp18, and comp21 improved upstream,
while comp02 and comp12 regressed upstream by 5 and 2. In both regressions the
dive retained the incumbent, so these are time-limited upstream divergence,
not harmful candidate acceptance.

The compatible immutable CPSolver rows still won all 21 comparisons. Their
objective sum was 3,586 versus Planora ON's 19,711. This ablation therefore
supports neither enabling room dive by default nor a superiority claim.

Machine-readable audit evidence, per-instance attribution, compatibility
checks, timing distributions, and the exact command template are in
`reports/itc2007_fixed_time_room_dive_breadth_seed17_2026-08-11.json`. The raw
42-case evidence and content-hashed index are under
`output/itc2007-room-dive-breadth-seed17-counterbalanced-v1`.

## Deadline correction and final room-dive breadth rerun

The failed breadth result above remains immutable negative evidence. Its local
room-dive deadlines did not reserve time for outer result completion, so seven
ON cases exceeded the shared `solve_instance` deadline even though every dive
reported zero local overrun. The retained correction subtracts both later
reserves from the adaptive allocation, admits a room dive only when the shared
deadline covers its full 0.50-second reserve plus a 0.25-second completion
reserve, and caps the dive at the earlier of its local deadline and the shared
deadline minus completion reserve. The fixed 0.50-second finalization reserve
is identical in OFF and ON.

A targeted rerun first covered the seven former failures. All seven schedules
were officially feasible, had zero hard violations, matched internal scoring,
and stayed within the strict total deadline. Every dive was explicitly skipped
because only 0.644 to 0.726 seconds remained, less than the combined 0.75-second
admission requirement. The targeted evidence is in
`reports/itc2007_fixed_time_room_dive_deadline_gate_v2_2026-08-11.json`.

The final counterbalanced breadth rerun then repeated all 42 OFF/ON cases on
source snapshot
`a63732de42d9e0053ea196f46a410024b85c006e4cc6d7f91e5529f3bd1294cb`.
All 42 were officially feasible, had zero hard violations, matched the
internal four-component score exactly, passed the source guard, and recorded
zero strict-total deadline overrun. Maximum `solve_instance` elapsed time was
9.854 seconds for OFF and 9.705 seconds for ON.

ON was better on 3 instances, tied on 18, and worse on none. Its objective sum
was 19,870 versus 20,457 for OFF, a 2.87 percent reduction. Weighted component
deltas were -50 curriculum compactness, -55 minimum working days, -517 room
capacity, and +35 room stability. This aggregate comparison must be separated
from the dive's direct effect: 13 dives were admitted, only comp01 accepted an
improvement, 12 attempts retained their incumbents, and 8 were skipped before
setup/search/validation. The sole accepted candidate changed comp01 from 499
to 253, a direct 246-point gain driven by -261 room capacity and +15 room
stability. Comp13's 50-point gain occurred upstream before a failed dive, and
comp20's 291-point gain came from an upstream rescue incumbent while the dive
was skipped.

Median solver-subprocess wall time was 13.811 seconds for OFF and 14.079 seconds
for ON; median solver-subprocess CPU time was 9.998 and 10.398 seconds. These
measurements include process startup but exclude the later official-validator
subprocess. Median in-process `solve_instance` elapsed time was 9.138 seconds
for OFF and 9.462 seconds for ON.

The immutable CPSolver rows pass the exact manifest compatibility gate for
instances and hashes, seed, configured time, worker count, CPU affinity,
hardware, platform, Python and OR-Tools versions, validator, CPSolver revision,
and compiled classes. CPSolver still won all 21 official-objective comparisons:
3,586 total versus 19,870 for Planora ON, a 5.54 ratio. Room capacity remains
the largest multiplicative component gap at 4,576 versus 135, while curriculum
compactness is the largest absolute gap at 8,180 versus 2,268.

The corrected opt-in path therefore passes this single-seed feasibility,
parity, provenance, and strict-deadline engineering gate. It remains default
off: only one admitted dive directly improved its incumbent, two paired gains
were upstream time-limited divergence, and CPSolver won every external quality
comparison. This is not a replicated superiority study and supports no
superiority claim.

The consolidated report is
`reports/itc2007_fixed_time_room_dive_breadth_final_v2_seed17_2026-08-11.json`.
Raw case artifacts and the content-hashed index are under
`output/itc2007-room-dive-breadth-seed17-counterbalanced-final-v2`.
