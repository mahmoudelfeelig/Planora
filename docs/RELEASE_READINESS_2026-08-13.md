# Release and research readiness — 2026-08-13

## Closed in this checkout

- Python, the HTTP API, the browser, the desktop worker, and the CLI now route solve/improve work through `planora-solver-service-v1` with shared interactive defaults.
- A real product-sized demo completed solve in about 0.59 seconds and improve in about 2.11 seconds, with hard-feasible output and the same backend identity on both paths.
- The fresh ITC-2007 matrix contains two complete 42-row source-frozen passes across all 21 competition instances. Pass A produced Planora/CPSolver/tie counts 9/10/2; the redundant pass B produced 14/7/0. All 84 rows were officially feasible. Fourteen instance winners were stable and seven changed, so the lower Planora mean in both passes does not justify a deterministic superiority claim.
- The fixed ITC-2019 public coverage matrix executed 30 conditions at ten seconds. One condition (`lums-sum17`) produced an independently validated optimal score 4; the remaining 29 explicitly returned UNKNOWN, deadline, or scale-gate outcomes. This closes execution coverage, not publication-grade effective coverage.
- The authorized Edge acceptance passed on desktop and mobile for home, FAQ, privacy, and authentication flows, including keyboard focus, labels, alt text, horizontal overflow, reduced motion, and WCAG AA text contrast.
- The repository-local formal security equivalent completed its finding/remediation/regression cycle.
- The SS23-calibrated 3,888-activity proxy completed 5/5 valid measured runs in each transport. Median end-to-end time was 17.668 seconds embedded, 28.080 seconds with a fresh API process, and 6.234 seconds through a persistent HTTP service; see `docs/PERFORMANCE_3888_2026-08-14.md`.
- Desktop, web, and Android now consume the same `planora.ui.v1` scenario/mode contract and `planora-solver-service-v1` solve/improve backend. The normal catalog is Demo, Spring 2023, and Import; low-level generators and solver controls remain under Advanced.
- The current desktop/web Academic Blueprint visual acceptance passed with populated schedules, and the Android phone/expanded Compose flows passed unit, lint, assembly, device, and screenshot review.
- A 2026 GIU planning extrapolation and a ready-to-sign institutional packet are present. The extrapolation is a sensitivity scenario derived from repository data, not a claim about current institutional reality.

## External authority gates that remain open

- Authenticated ITC-2019 validation is now operational. The four-way `lums-sum17` smoke agreed 4/4, and all three valid outputs from the fresh 30-instance competitor matrix agreed 3/3. The 30-instance selection is not complete because 117 ten-second conditions emitted no complete valid output.
- GIU institutional sign-off must be completed by the named GIU roles. Repository maintainers cannot manufacture or substitute those signatures.

## Evidence locations

- `output/itc2007-fresh-competitor-matrix-20260813-pass-a/`
- `output/itc2007-fresh-competitor-matrix-20260813-pass-b/`
- `paper/evidence/itc2007_fresh_redundant_matrix_2026-08-13.json`
- `output/itc2019-publication-30-10s-pass-a/`
- `paper/evidence/itc2019_official_validator_attempt_2026-08-13.json`
- `paper/evidence/giu_extrapolated_planning_scenario.json`
- `docs/GIU_SIGN_OFF_PACKET.md`
- `reports/security/security_lifecycle_scan_2026-08-13.md`
- `web/test-results/`
- `output/performance/giu-proxy-3888-e2e-20260814.json`
- `output/performance/giu-proxy-3888-http-warm-20260814.json`
- `output/itc2019-open-source-competition-30-seed17-10s-20260813/`
- `android/app/build/outputs/apk/debug/app-debug.apk`

## Final local verification on 2026-08-14

The final checkout completed two consecutive full invocations of
`scripts/run_ci_checks.sh` with no intervening source or evidence edits. Each
pass completed compile and Ruff checks, 2 timing-sensitive tests, 1,151
ordinary tests, 57 slow integration/UI tests, all critical coverage ratchets,
and 10 release-artifact tests. The same two live-socket tests were skipped in
both passes because this execution environment prohibits socket binding; real
HTTP behavior was separately exercised by the containerized performance and
browser-acceptance workflows. Solver line coverage was 81.87% against the
unchanged 81.79% ratchet.

The production web image was rebuilt from the final source. Explicit desktop
and mobile Playwright accessibility acceptance passed 2/2 after correcting the
academic-theme muted-text contrast token. The canonical 23-page paper PDF was
rebuilt with TeX Live and visually inspected from complete-page renders. The
Android unit, lint, assembly, instrumentation, device-flow, and live shared-API
checks remain green from the frozen Android implementation.

The final release gate remains intentionally fail-closed: local engineering, authenticated validator access, and bounded comparison evidence are ready for handoff, while complete ITC-2019 effective coverage and GIU institutional authorization remain open.
