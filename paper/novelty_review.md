# Systematic novelty review

Status: broad mathematical and algorithmic novelty claims falsified; a narrow verification-aware systems hypothesis remains; scoped fixed-time-room mathematical-certificate replay passed adversarial review; the compact ITC-2007 arm set remains a default-off empirical candidate
Last searched: 2026-08-13
Scope: university course timetabling, time-room decomposition, fixed-time room assignment, room-stability coupling, Hall and Benders cuts, matching certificates, exact conditional room neighborhoods, exact-repair large-neighborhood search, instance-feature tuning, neighborhood-size policies, and recent 2024--2026 CB-CTT local search.

## Review protocol

This review treats each proposed contribution as a claim to falsify. It compares mathematical constructions and observable algorithmic behavior, not the terminology used by Planora or by prior authors.

The search covered primary papers and official records from publisher pages, PATAT proceedings, institutional author repositories, arXiv, SSRN, DBLP, Crossref, and the official ITC-2007 and ITC-2019 sites. The structured recent-work pass was run on 2026-08-11:

| Source | Executed query and screen | Result used in this review |
|---|---|---|
| DBLP publication API | Exact phrase `"curriculum-based course timetabling"`, all 39 returned records; publication years 2024--2026 screened manually | Two indexed records were in range: Steiner--Pferschy--Schaerf and Nguyen. Nguyen directly overlaps the local-search claim; Steiner et al. concerns a different exact institutional model and was excluded from that claim. |
| Crossref REST API | Title query `curriculum-based course timetabling local search`, date filter 2024-01-01 through 2026-08-11, first 100 relevance-ranked records screened | Ceschia et al. and Nguyen were included. Records about sports, examination, train, school, or unrelated scheduling were excluded. The low-precision result count was not treated as a corpus size. |
| SSRN | Exact title, DOI, and `LectureKick` searches for SSRN 6485691 | The primary abstract and record were accessible. The PDF endpoint was bot-blocked, so only claims stated in the primary abstract are used; the work is a non-peer-reviewed preprint. |
| Publisher and author repositories | Exact-title and DOI searches for each overlapping method | Primary manuscripts or publisher records were inspected for the method-level claims in the source matrix. |

The targeted queries included:

- `partial transversal polytope time varying eligibility`
- `start dependent room eligibility Hall inequality scheduling`
- `course timetabling fixed periods exact room assignment bipartite matching`
- `room stability bipartite matching course timetabling complexity`
- `classroom assignment room stability NP-hard weighted bipartite matching`
- `course room stability one period matching timetabling`
- `Benders cuts large neighborhood search certificate neighborhood`
- `assignment problem primal dual certificate Hungarian algorithm potentials`
- `verifiable integer programming proof certificates VIPR`
- `adaptive large neighborhood search curriculum based course timetabling`
- `curriculum based course timetabling neighborhood size adaptive`
- `curriculum-based course timetabling 2024 local search`
- `curriculum-based course timetabling 2025 local search`
- `curriculum-based course timetabling 2026 local search`
- `Revisiting Local Search for Curriculum-Based Course Timetabling LectureKick`

Included records are primary research papers, official competition descriptions, or official solver/proof-system documentation whose method directly overlaps a proposed Planora contribution. Surveys were used only to discover primary work. Duplicate preprint and version-of-record entries were collapsed. Studies were excluded from a claim when they addressed another timetabling variant without overlapping the claimed mechanism, described only a user interface, or lacked enough primary text to establish the method.

This is a reproducible adversarial search, not a database-complete PRISMA review. Subscription-only Scopus and Web of Science searches were unavailable, the Crossref query was relevance-ranked rather than exhaustive, the SSRN full text was inaccessible, and this was a single-reviewer screen. These limits prohibit a priority or “first” claim. They do not rescue claims already anticipated by the primary sources below.

## Adversarial source matrix

| Targeted claim | Closest primary evidence | What the source establishes | Adversarial disposition |
|---|---|---|---|
| Hall cuts for time-first, room-second timetabling | Lach and Lübbecke, [primary PDF](https://page.math.tu-berlin.de/~lach/publications/wea08.pdf), [DOI 10.1007/978-3-540-68552-4_18](https://doi.org/10.1007/978-3-540-68552-4_18) | Models arbitrary course-room eligibility as a bipartite graph, gives the partial-transversal/Hall system, separates it by flow, and solves the room stage by a sequence of minimum-weight matchings. | Decomposition, Hall feasibility cuts, and exact matching recovery are established. |
| Start-dependent room-domain Hall formula | Lach and Lübbecke, same source | The polyhedral result applies to an arbitrary bipartite graph; the origin of an edge is immaterial. Expanding the left side to start alternatives yields the Planora formula as an instance of the same system. | **Falsified as a new mathematical inequality family.** |
| Course-timetabling room infeasibility cuts | Bagger, Sørensen, and Stidsen, [primary preprint](https://orbit.dtu.dk/files/138514884/BendersDecomposition.pdf), [DOI 10.1016/j.cor.2017.10.009](https://doi.org/10.1016/j.cor.2017.10.009) | Separates time scheduling from room allocation and connects them with Benders feasibility cuts derived by maximum-flow/minimum-cut reasoning. | Time/room Benders certificates and cuts are established. |
| Polynomial fixed-time room assignment | Carter and Tovey, [DOI 10.1287/opre.40.1.S28](https://doi.org/10.1287/opre.40.1.S28); Phillips et al., [primary manuscript](https://eprints.lancs.ac.uk/id/eprint/75294/1/roomAssignmentv13.pdf), [DOI 10.1016/j.cor.2014.07.012](https://doi.org/10.1016/j.cor.2014.07.012) | Identifies easy and hard classroom-assignment cases. With independent unit-period events and additive edge costs, each period is a polynomial assignment/weighted-bipartite-matching problem. | **Falsified as a new oracle or complexity result.** Planora's eligible additive projection is an implementation of this established tractable case. |
| Room-stability complexity boundary | Carter and Tovey, same source; Phillips et al., same source | Cross-period requirements destroy independent-period structure: contiguous room stability is NP-hard even for two periods, and course room stability creates general cross-period coupling. | The full stability-aware fixed-time room problem is not globally solved merely by independent Hungarian blocks. |
| Exact room resolution inside time neighborhoods | Lü and Hao, [primary PDF](https://leria-info.univ-angers.fr/~jinkao.hao/papers/AIMSA08.pdf), [DOI 10.1007/978-3-540-85776-1_22](https://doi.org/10.1007/978-3-540-85776-1_22); Lü, Hao, and Glover, [primary PDF](https://leria-info.univ-angers.fr/~jinkao.hao/papers/JoH2010.pdf), [DOI 10.1007/s10732-010-9128-0](https://doi.org/10.1007/s10732-010-9128-0) | After period or Kempe moves, room assignment is restored with an exact bipartite-matching algorithm. Conditional on all other periods, Planora's one-period stability contribution is an additive edge cost, so its exact block again reduces to weighted assignment. | **Falsified as a new optimization primitive.** The bounded search did not locate the identical sweep order and evidence envelope; those remain implementation choices, not a new matching method. |
| Fixed-time room reoptimization or “room dive” | Burke, Mareček, Parkes, and Rudová, [arXiv manuscript](https://arxiv.org/abs/0903.1095), [DOI 10.1016/j.cor.2009.02.023](https://doi.org/10.1016/j.cor.2009.02.023); Phillips et al., same source | Prior work explicitly studies decomposition/reformulation/diving and exact classroom assignment after fixing time decisions. | **Falsified as a new algorithmic primitive.** |
| Benders- or certificate-guided large-neighborhood search | Trick and Yildiz, [DOI 10.1002/nav.20482](https://doi.org/10.1002/nav.20482); Maher, [DOI 10.1007/s10732-021-09467-z](https://doi.org/10.1007/s10732-021-09467-z) | Benders cuts have already been used to guide large-neighborhood selection, and later work explicitly couples Benders decomposition with enhanced LNS. These papers are adjacent optimization domains, not CB-CTT priority evidence. | **Falsified as a general mechanism claim.** A CB-CTT-specific typed-evidence integration would still need empirical differentiation. |
| Explanation-guided exact repair | Prud'homme, Lorca, and Jussien, [DOI 10.1007/s10601-014-9166-6](https://doi.org/10.1007/s10601-014-9166-6); Cambazard et al., [DOI 10.1007/s10479-010-0737-7](https://doi.org/10.1007/s10479-010-0737-7) | Explanation-based LNS and CP/local-search hybrids for course timetabling predate Planora. | **Falsified as a generic search principle.** The exact evidence schema and institutional portability remain systems questions. |
| Primal/dual matching certificate | Kuhn, [DOI 10.1002/nav.3800020109](https://doi.org/10.1002/nav.3800020109); Carpaneto and Toth, [DOI 10.1016/0166-218X(87)90016-3](https://doi.org/10.1016/0166-218X(87)90016-3) | The Hungarian method and later assignment algorithms are primal-dual. A feasible assignment plus dual-feasible potentials with equal objectives is a standard optimality witness. | **Falsified as new certificate mathematics.** Serialization, source binding, tamper rejection, and deadline-safe acceptance may be systems work. |
| General independently verifiable optimization certificate | Cheung, Gleixner, and Steffy, [primary manuscript](https://arxiv.org/abs/1611.08832), [DOI 10.1007/978-3-319-59250-3_13](https://doi.org/10.1007/978-3-319-59250-3_13); Szeider, [DOI 10.4230/LIPIcs.CP.2026.52](https://doi.org/10.4230/LIPIcs.CP.2026.52) | VIPR-style work defines self-contained certificates checked independently of the producing solver; the 2026 work reconstructs exact rational certificates from a black-box ILP solver. | Planora may claim separate replay of its serialized mathematical certificate only within the audited scope below. It must not call the whole result independently verified, a general solver proof, or a formal proof. |
| Instance-feature-driven solver tuning | Bellio et al., [arXiv manuscript](https://arxiv.org/abs/1409.7186), [DOI 10.1016/j.cor.2015.07.002](https://doi.org/10.1016/j.cor.2015.07.002) | Uses statistically designed feature-based parameter tuning for simulated annealing on CB-CTT and sets parameters for unseen instances from their features. | Feature-based or corpus-conditioned configuration is established. |
| Adaptive CB-CTT LNS/operator selection | Kiefer, Hartl, and Schnell, [DOI 10.1007/s10479-016-2151-2](https://doi.org/10.1007/s10479-016-2151-2) | Uses several destroy and repair operators and selects them from their prior performance on the instance. | Adaptive operator selection for CB-CTT is established. |
| Adaptive neighborhood size | Nagata, [DOI 10.1016/j.cor.2017.09.014](https://doi.org/10.1016/j.cor.2017.09.014) | Explicitly changes random partial-neighborhood size during course-timetabling search to control exploration and exploitation. [Ropke and Pisinger](https://doi.org/10.1287/trsc.1050.0135), [Hendel](https://doi.org/10.1007/s12532-021-00209-7), and [Cai, Kadıoğlu, and Dilkina](https://doi.org/10.24963/ijcai.2025/286) establish the broader adaptive operator/family-selection background. | **Falsified as a new adaptive-size mechanism.** Planora's current compact set is static, not online adaptation. |
| Recent CB-CTT neighborhood innovation and tuning | Ceschia, Da Ros, Di Gaspero, and Schaerf, [SSRN record](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6485691), [DOI 10.2139/ssrn.6485691](https://doi.org/10.2139/ssrn.6485691) | The 2026 preprint reports a literature-wide neighborhood analysis, LectureKick, soft-constraint sampling biases, a cooling cut-off, large-artificial-dataset tuning, and evaluation under ITC-2007 competition limits. | Any claim that small fixed destroy-set pruning is itself an eye-opening new local-search idea is untenable. This preprint is a mandatory comparator, with its non-peer-reviewed status disclosed. |
| Recent CP-SAT, adaptive VND, and exact room-flow hybrid | Nguyen, [official conference record](https://www.scitepress.org/PublishedPapers/2026/144377/), [DOI 10.5220/0014437700004052](https://doi.org/10.5220/0014437700004052) | Combines CP-SAT initialization, VND, stagnation-conditioned penalty perturbation, Kempe moves, and min-cost max-flow room assignment on ITC-2007. | The generic “CP-SAT plus adaptive local search plus exact room assignment” combination is established by recent primary work. |

## Why the contextual Hall formula is not a new inequality family

At a witness slot \(q\), construct an option-expanded bipartite graph

\[
G_q=(V_q\cup\mathcal R,E_q),\qquad
V_q=\{(a,t):q\in I(a,t)\},
\]

and connect option vertex \((a,t)\) to room \(r\) exactly when \(r\in D(a,t)\). The selected start literals are an incidence vector of a partial transversal of this graph, with additional at-most-one structure between alternatives of the same activity.

For a witnessed room set \(R\), let

\[
U=\{(a,t)\in V_q:D(a,t)\subseteq R\}=\Gamma^{-1}(R).
\]

The established partial-transversal inequality gives

\[
x(U)\leq |\Gamma(U)|\leq |R|.
\]

The implementation reviewed during the first adversarial pass used the weaker right-hand side \(|R|\). The post-review implementation reconstructs the complete counted option set and uses \(|\Gamma(U)|\). This closes a cut-strength defect but does not create a new polyhedral class. Exact reconstruction of \(D(a,t)\) across duration, closures, demand, locks, and linked activities, plus conservative fallback to an incumbent nogood, is useful engineering rather than a new inequality theorem.

## Fixed-time room oracle claim audit

“Oracle” is a software component name here, not a claim of a new mathematical oracle.

For the admitted fixed-time, unit-duration, additively scored structural class, a period decomposes into a rectangular minimum-cost assignment. The per-period primal/dual certificate and Hall infeasibility witness therefore use established matching theory. Summing exact per-period capacity optima supplies a valid capacity lower bound.

Room stability couples assignments across periods and is NP-hard in general. Planora's repeated exact one-period matching updates are best described as **stability-aware block-coordinate descent with exact conditional blocks**. When a complete sweep accepts no improving block, the defensible statement is one-period coordinatewise local optimality for the represented fixed-time room objective. Multiple starts can improve the incumbent but do not strengthen that local certificate. A global-optimality statement is defensible only when the accepted room objective equals a valid replayed lower bound, and it applies only to the admitted fixed-time room subproblem, never to the full timetable.

The potentially useful systems contribution is the combination of structural eligibility checks, exact additive projections, unsigned replay data, stability-aware exact blocks, fixed-time digests, strict deadlines, canonical objective parity, full schedule validation, and fail-closed acceptance. Every mathematical optimization primitive in that list has close prior art. No source found in this bounded search packages precisely the same dispatcher and evidence contract, but absence of a match is not evidence of priority.

A separate checker for the serialized fixed-time room result now exists, and its mathematical tamper-fuzz review found no false accepts. The approved claim is deliberately exact: **“For eligible fixed-time room-assignment results with status `improved` or `no_improvement`, the serialized mathematical certificate was JSON-round-tripped and replayed by a separate checker implementation.”** The replay reconstructs the candidate, fixed starts, eligibility on claim-bearing paths, room domains and costs, canonical objective parity, per-period Hungarian primal/dual/edge/digest certificates, capacity and stability lower bounds, global-optimality equality, one-period local-optimality conditions, no-worsening/status flags, and Hall witnesses.

The whole result is not independently verified. The unsigned payload does not independently establish deadlines or timing, selected-start/sweep/accepted-block trajectory, method or complexity provenance, source identity, or causality for nonclaim statuses. It is not formal verification, a solver-independent proof of the full search, or a substitute for an official benchmark validator. The unqualified label `independently_replayed` remains prohibited.

## Compact ITC-2007 arm-policy claim audit

The current compact policy selects the fixed set `(12, 24)` instead of `(12, 24, 48)` only for imported ITC-2007 instances, only when an explicit flag is enabled, and leaves explicit user configurations unchanged. It remains default off.

That is a **static corpus-conditioned configuration candidate**. It does not learn online, change size from reward feedback, or establish transfer to other institutions. Calling it “adaptive,” “learned,” “generally faster,” or “novel neighborhood selection” would be misleading. Kiefer et al., Nagata, Bellio et al., and Ceschia et al. already cover stronger forms of adaptive selection, dynamic size control, feature-conditioned tuning, and systematically tuned CB-CTT neighborhoods.

The four-instance diagnostic that motivated the compact set is hypothesis generation only. A publication claim requires a preregistered baseline-versus-compact comparison on at least 30 unique effective external instances, multiple repeated seeds reported as repeats rather than new instances, official-validator agreement for every ITC-2007 output, source hashes, strict deadline accounting, and a held-out or nested calibration/evaluation split. Without that evidence, the setting is an ablation arm, not a product default or research contribution.

## Post-review implementation reassessment

The earlier Hall/certificate-lineage gaps have been materially addressed in the checkout: versioned domain evidence, deterministic SHA-256 integrity identifiers, separate replay paths, certificate-derived neighborhood lineage, and fail-closed contextual-cut insertion exist. These identifiers provide integrity links, not authentication, signatures, timestamps, or authorship.

The new fixed-time room path adds structurally gated assignment projections, primal/dual matching payloads, Hall witnesses, stability-aware exact conditional sweeps, objective and fixed-time digests, canonical rescoring, schedule validation, and deadline rejection. The compact ITC-2007 arm selector records requested, configured, and effective sizes plus its selection reason and remains explicitly opt-in.

These changes create testable systems hypotheses. They do not revive the falsified novelty claims, prove performance superiority, or establish independent verification of the whole result. The checker has passed only the scoped mathematical-certificate replay claim above, and the compact arm candidate still lacks the required publication-scale held-out ablation.

The later room-support feedback experiment adds no new move family.  It offers
an opt-in deterministic proxy that counts distinct fragmented courses after a
period-room collision projection, while retaining the established official
room-stability term as the only acceptance authority.  On retained native
incumbents it improved `comp10` from 109 to 96 and `comp06` from
168 to 155 under bounded post-incumbent calls; the higher scalar weight alone
made `comp10` worse (102), and the 96 result still trails the retained
CPSolver score 82.  These are mechanism and ablation observations, not an
end-to-end or superiority result.  Publication wording must therefore be
``distinct-course room-support proxy selected for controlled ablation,'' not
``new room-stability objective,'' ``learned policy,'' or ``new neighborhood.''

The selected post-incumbent ledger adds a different, equally narrow
observation. Representation-derived portfolios improved retained
Planora-native incumbents below retained CPSolver artifacts on four CTT cases
and Exam set~1. The calls exclude parsing and incumbent construction, the
cases were selected after diagnosis, comparator runtime is unmatched, and two
CTT rows bind earlier implementation hashes after a default-preserving API
extension. The permitted description is therefore ``selected post-incumbent
basin-repair evidence.'' It is not a replicated matrix, equal-budget result,
end-to-end speed result, or general competitor-superiority claim.

## Required wording corrections

| Avoid | Evidence-supported wording |
|---|---|
| “We introduce a novel contextual Hall inequality.” | “We instantiate and dynamically separate an established Hall inequality on a start-option-expanded room graph, reconstructing effective room domains and falling back safely when preconditions cannot be established.” |
| “The first Hall cut for start-dependent room domains.” | “A start-dependent application of the established partial-transversal/Hall system; no priority claim is made.” |
| “A novel fixed-time room oracle.” | “A structurally gated fixed-time room optimizer using established assignment and block-coordinate ideas, with explicit evidence and acceptance boundaries.” |
| “The room oracle proves the schedule globally optimal.” | “For an admitted fixed-time room subproblem, the result is coordinatewise locally optimal after a complete non-improving sweep, or globally optimal only when its room objective equals the stated valid lower bound.” |
| “Proof-carrying,” “formally verified,” or “the whole result is independently replayed.” | “For eligible fixed-time room-assignment results with status `improved` or `no_improvement`, the serialized mathematical certificate was JSON-round-tripped and replayed by a separate checker implementation.” Keep the exclusions above adjacent to this sentence. |
| “A novel adaptive compact-arm policy.” | “A default-off, corpus-conditioned compact neighborhood-set candidate selected for controlled ablation.” |
| “The compact policy is generally faster.” | “The compact candidate reduced wasted large-neighborhood work in a small diagnostic; generalization is unestablished pending held-out evaluation.” |
| “CP-SAT plus adaptive local search and exact room assignment is novel.” | “A verification-aware integration of established exact and local-search components.” |
| “A novel room-stability neighborhood or exact proxy.” | “An opt-in deterministic distinct-course room-support proxy used only for candidate selection; official score and validation retain acceptance authority.” |
| “Digitally signed or end-to-end machine-checked proof trace.” | “Content-addressed integrity lineage and a scoped replay transcript.” |

## Operator-level clean-room control

The review now has an executable companion at
`config/research_operator_provenance.json`.  It registers each current
ITC-2007 optimization module, the established primitives it uses, closest
primary sources, the narrower Planora-specific hypothesis, prohibited claims,
and the ablations that could falsify that hypothesis.  The focused checker
`scripts/check_research_provenance.py` rejects an unregistered optimizer,
unknown source references, unsafe implementation paths, benchmark instance
fingerprints, and comparator/target-score identifiers in operator decisions.

This is a provenance and claim-discipline control, not evidence that the
registered composition is novel.  Comparator outputs may inform aggregate
component diagnosis and black-box evaluation, but their assignments and move
traces may not construct a Planora-native result.  A comparator-seeded repair
is classified as diagnostic even when it improves the comparator.  A retained
Planora incumbent can support a native post-incumbent quality result but not an
end-to-end runtime claim.  Only a source- and input-stable current run whose
entire solve fits the stated deadline may become an end-to-end candidate.

The present research hypothesis is therefore narrower than the individual
operators: representation-derived residual diagnosis, cross-component root
ordering, rebuild-after-acceptance, total-objective tradeoff acceptance, and a
single fail-closed validation/deadline boundary may together improve useful
search while making evidence harder to misclassify.  The ledger marks all of
these as unestablished until held-out, operator-level ablations are complete.

## Narrow defensible contribution

The strongest research hypothesis is a **verification-aware structural optimization layer for a portable university scheduler**: it detects a tractable fixed-time room structure; computes exact additive assignment projections and explicit witnesses; performs stability-aware exact conditional improvement; binds evidence to the instance, objective, and fixed starts; and accepts a result only after deadline, objective-parity, and full-schedule checks. This may be evaluated together with the existing effective-domain Hall lineage and exact-repair telemetry as an auditable systems integration.

This is not presently an established contribution. To survive peer review, ablations must show a material improvement in time to an externally validated solution, objective quality, failure detection, or reproducibility over simpler matching, full CP room diving, and competitive CB-CTT solvers. The compact arm set is an experimental factor inside that evaluation, not part of the novelty claim.

## Required falsification and ablation

- Compare the standard \(|\Gamma(U)|\) Hall separation against exact-incumbent nogoods and the historical witnessed-room right-hand side where they differ.
- Compare fixed-time-room conditions separately: no post-optimizer, additive matching only, stability-aware coordinate blocks, existing full CP room dive, and the combined dispatcher. Report eligibility rate and direct accepted gains, not only condition-level score differences.
- Preserve the adversarial mutation suite for matching certificates, lower bounds, local claims, and Hall witnesses; report checker time separately; and use only the approved scoped replay sentence. Add new fields to the claim only after equivalent tamper tests.
- Evaluate `(12, 24, 48)` versus `(12, 24)` on at least 30 unique effective external instances under identical single-worker budgets. Use a held-out or nested calibration/evaluation split; do not count seeds as unique instances.
- Include the strongest available comparable methods and explicitly discuss the 2026 LectureKick preprint and the 2026 CP-SAT/VND/min-cost-flow hybrid. Do not infer superiority from incomparable hardware, budgets, validators, or result tables.
- Validate every ITC-2007 schedule with the official validator and require exact component agreement. Keep ITC-2019 claims local-only until the official distribution/objective validator is available.
- Report source and instance hashes, failed and invalid runs, timeouts, strict deadline overruns, confidence intervals, paired effect sizes, and all prespecified exclusions.
- Separate domain reconstruction, certificate generation, hashing, checking, model setup, search, canonical scoring, and validation time.
- Repeat the room-oracle and compact-arm conditions over multiple solver seeds while retaining the unique-instance count and family-stratified results.
- Compare event-collision and distinct-fragmented-course feedback under the same fixed work checkpoints, include the failed higher-weight condition, and report post-incumbent timing separately from end-to-end solve time.

## Current verdict

The contextual Hall formula, weighted room matching, Hall infeasibility witness, primal/dual assignment certificate, fixed-time room reoptimization, exact room recovery inside local-search moves, Benders-guided LNS, explanation-guided repair, adaptive operator/size selection, and instance-feature tuning all have direct prior art. Broad mathematical and algorithmic novelty claims are falsified.

A narrow systems paper may still be defensible around the limitation-aware, verification-oriented integration and its empirical effect in a heterogeneous institutional scheduler. The required language is “we implement and evaluate a structurally gated, evidence-producing integration,” not “we introduce the first,” “novel oracle,” “proof-carrying,” “adaptive compact policy,” or “state of the art.” The scoped mathematical-certificate replay claim has passed; performance and generalization claims remain gated by publication-scale external validation.
