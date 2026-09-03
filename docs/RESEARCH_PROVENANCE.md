# Research provenance and clean-room reuse

Planora deliberately reuses established optimization knowledge without copying
competitor implementations.  The machine-readable policy and operator ledger
live in `config/research_operator_provenance.json`; the focused checker is
`scripts/check_research_provenance.py`.

## The boundary

Public papers, official benchmark specifications, official validators, and
aggregate black-box results may inform the work.  Competitor source, bytecode,
decompiled or translated control flow, move traces, and entity-level solution
assignments may not be used to construct a Planora-native result.

A comparator solution can be passed through a Planora operator only as a
diagnostic ablation.  Such an experiment answers whether the operator can
repair that residual basin.  It is never a Planora-native benchmark result and
never enters production tuning as an entity-level move template.

Every production selector must be derived from the problem representation and
the independently scored current incumbent.  Benchmark names, instance IDs,
competitor scores, and target thresholds are forbidden decision inputs.

## What is established

The following are prior art, not Planora inventions:

- single relocation, interchange, Kempe, ejection, and compactness moves;
- variable-neighborhood, iterated, adaptive, and large-neighborhood search;
- CP or MIP exact repair inside a local-search neighborhood;
- fixed-time room assignment, matching, room dives, and time/room
  decomposition;
- Hall and Benders room-feasibility reasoning;
- feature-conditioned tuning and adaptive neighborhood sizing;
- assignment lower bounds and primal-dual optimality certificates.

Planora cites these families and independently implements only the behavior it
needs.  A matching concept or a CP neighborhood is not made novel by a new
name.

## The research hypothesis

The defensible contribution under study is a systems and orchestration
hypothesis:

> Representation-derived residual diagnosis selects bounded exact
> neighborhoods, alternates them with deterministic inexpensive repair, and
> admits a result only through mutation-safe independent validation under one
> caller-owned deadline.

Candidate differentiators are the residual representations, cross-component
root ordering, rebuild policy after accepted moves, total-objective acceptance
of useful component tradeoffs, and the fail-closed evidence boundary.  Each is
an empirical hypothesis until its ledger ablations are run on held-out
instances.

The room-support feedback path follows the same boundary.  Room-majority
guidance and room-stability penalties are established ideas.  Planora's
current experimental factor is a deterministic proxy that counts distinct
courses forced away from their incumbent-majority room after resolving each
period-room collision.  It is an opt-in selection signal, not the official
room-stability objective and not a new neighborhood.  The compatibility
event-collision proxy remains the default until a held-out paired ablation is
complete; every accepted schedule is still decided by the official objective
and independent hard validation.

## Required workflow

Before a new operator is used for a research claim:

- register its source file, established primitives, closest primary sources,
  Planora-specific contribution, prohibited claims, and required ablations;
- run `python scripts/check_research_provenance.py`;
- demonstrate that no decision depends on benchmark IDs or comparator targets;
- compare against neutral ordering and relevant component operators;
- compare the event-collision and fragmented-course room-support proxies at
  fixed work quotas, including the unsuccessful higher-weight condition;
- preserve independent hard validation, canonical scoring, absolute deadline
  accounting, and exact-incumbent rollback;
- classify comparator-seeded runs as diagnostic rather than native evidence.

The ledger is not a patent search, proof of priority, or complete systematic
review.  It is a reproducible engineering control that prevents known prior
art from being relabeled and keeps future novelty claims falsifiable.
