# Security lifecycle scan — 2026-08-13

## Decision

The repository completed a source-based defensive security scan plus focused adversarial regression cycle. The result is a repository-local approved equivalent to the unavailable formal desktop scan runner. It is not a penetration test of a deployed environment and does not certify infrastructure outside this checkout.

## Scope and method

The review covered the HTTP boundary, authentication and recovery tokens, tenant isolation, solver admission, imported project metadata, calendar export, subprocess/environment handling, and known dangerous input classes. It combined independent source review, direct reproductions, red-before-green regressions, fail-closed code changes, and a focused 74-test security suite. Browser-facing authentication and public routes were subsequently exercised in Edge.

## Resolved findings

| Severity | Finding | Resolution |
|---|---|---|
| High | Six-digit verification and reset codes were not bound tightly enough to the target email and lacked a per-token attempt ceiling. | Short codes are now email- and token-kind-bound, persist failed attempts, and lock after five failures. Opaque link tokens retain their separate flow. |
| High | User-controlled room mapping regexes could trigger catastrophic backtracking. | Matching is limited to bounded literal substrings or shell wildcards; regex metacharacters and patterns over 128 characters are rejected. |
| High | Threaded HTTP reads, requests, and SSE streams were insufficiently bounded. | Request sizes, socket I/O, global connections, solver concurrency, per-tenant solver admission, SSE concurrency, and SSE duration are bounded. |
| High | Synchronous solver calls could bypass job admission and accept unbounded remote budgets. | Remote solve/improve workers, wall budgets, iterations, and secondary budgets are capped server-side, with shared admission semaphores. |
| Medium | Imported project metadata could restore runtime settings and template-store paths. | Those fields are source-bound and are no longer restored from imported projects. |
| Medium | ICS text fields were not escaped and folded safely. | Calendar names, UIDs, summaries, locations, and descriptions are escaped and folded to the line-length boundary. |
| Low | Authentication responses exposed account existence differences. | Login checks are generic and duplicate registration uses a production-shaped generic response. |

## Negative findings retained

The review did not find unsafe pickle or YAML loading, shell-enabled subprocess calls, permissive wildcard CORS, plaintext password storage, direct SQL interpolation in the inspected persistence paths, or a cross-tenant object access bypass in the reviewed handlers.

## Residual boundaries

Deployed TLS termination, reverse-proxy limits, SMTP delivery, database backup access, host firewalling, dependency supply-chain state, and production secrets remain deployment responsibilities. A future release should run the same regression corpus against the deployed image and its reverse proxy. The repository scan does not replace an authorized production penetration test.

## Verification

- Focused security suite: 74 passed; 2 live-socket tests skipped because this environment denies socket binding.
- Ruff checks passed on the security-touched modules and tests.
- Browser acceptance: 8 Edge tests passed across desktop and mobile after fixing focus visibility and two WCAG AA contrast failures.
