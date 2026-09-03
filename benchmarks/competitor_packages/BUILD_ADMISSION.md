# ITC-2019 competitor offline-build admission

This lane specifies the evidence that must exist before the reviewed Gashi,
UniTime CPSolver, or Lemos source archives may enter an offline build. It binds
the exact reviewed source-custody implementation, tests, policy, documentation,
manifest, inventory, provenance verifier, benchmark harness, and custody binding.

The policy records each immutable source archive and the required toolchain and
dependency closure, deterministic no-network recipe, solver adapter and output
contract, build-receipt schema, produced-artifact digest replay, license review,
and matched-resource review. Planned evidence paths are declarations only. No
file at one of those paths is trusted merely because it appears there.

Version 1 is deliberately fail-closed. Every admission status is
`REQUIRED_NOT_PRESENT_OR_INDEPENDENTLY_REVIEWED`; `build_ready`,
`claim_grade_ready`, and `performance_claims_authorized` are always `false`.
Actual builds require a successor reviewed schema that attests real evidence,
two clean-root deterministic build receipts per solver, immutable produced image
digests, and independent review. Editing this policy cannot authorize a build.

Verification only hashes regular single-name files, parses strict JSON, checks
the reviewed bindings, and replays file identities. It rejects path traversal,
symlinks or reparse points, hard links, duplicate JSON members, non-standard JSON
constants, digest or size tampering, archive-input drift, and stored-manifest
drift. It does not download, extract, compile, build, create images, or execute a
competitor.

Run the safe replay with:

```powershell
.\.venv\Scripts\python.exe -B -m benchmarks.itc2019_competitor_build_admission
```
