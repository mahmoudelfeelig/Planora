# ITC-2019 competitor source custody

This directory contains immutable upstream source archives pinned by repository URL,
full commit identity, byte size, and SHA-256 in `source-inventory.json`.

`source-custody-policy.json` selects the expected archive root, upstream root-license
evidence, and files that reveal toolchain intent. The policy does not prescribe or
authorize a build. The custody verifier reads tar members without extracting them,
rejects unsafe or ambiguous member forms, and derives a deterministic digest from
the complete sorted root-relative member-identity list. License and toolchain records
are exact identities of members already covered by that complete tree digest.

The generated `source-custody-manifest.json` is limited to immutable vendored source
archive custody. It does not attest a compiler, runtime, package-manager resolution,
dependency closure, build recipe, build receipt, executable, container image, solver
run, resource parity, output validity, solution quality, or comparative performance.
Its `build_ready`, `claim_grade_ready`, and `performance_claims_authorized` values must
remain exactly `false`.

Build readiness remains blocked until every solver has an independently reviewed,
offline and digest-pinned toolchain/dependency closure, deterministic build recipe,
adapter, successful build receipt, and immutable produced-image digest bound through
the existing competitor-provenance verifier and final live replay.
