# Android release readiness — 2026-09-03

## Result

The Android client passes the local release-readiness gate for code quality, packaging, device behavior, responsive design, and hosted-backend reachability. The app is ready for an upload-key-signed internal test build. Store publication still requires the owner's Play upload key and store-console submission.

## Verified build and quality gates

- Kotlin and Compose production sources compile in debug and release variants.
- Fourteen JVM tests pass with no failures or skips.
- Nineteen device tests pass on a clean Android 16 AVD; one live-login test is intentionally skipped because production credentials were not supplied.
- Android lint reports zero issues.
- Debug APK, instrumentation APK, optimized unsigned release APK, and optimized release AAB build successfully offline.
- Thirty-seven backend security and operational tests pass. One unrelated pre-existing analytics request test currently times out on Windows; the two new email rendering/MIME tests pass independently.
- The hosted `https://planora.elfeel.me/api/ready` endpoint reports ready with database schema version 7.

## Performance snapshot

Measured on the isolated `PlanoraAudit` Android 16 AVD using a locally signed copy of the optimized release APK:

- Current release cold-start median: 3,611 ms across five clean launches.
- Current release cold-start range: 2,696–4,919 ms.
- Optimized unsigned release APK: 1,735,141 bytes; release AAB: approximately 3.9 MB.

These emulator measurements are a regression snapshot, not a substitute for Play Console Android vitals on representative physical devices. The median remains below Android vitals' 5-second excessive cold-start threshold.

## Visual and interaction coverage

The device suite exercises login, visible native registration, secure hosted-access explanation, first-run guide, home, schedule, review, projects, Tools, CSV mapping, server-approved manual moves, settings, dark theme, compact landscape, and expanded layouts. The final captures were compared alongside the web light and dark references. Navigation, primary schedule actions, overflow actions, inputs, selections, and core flows are exercised rather than treated as static mockups.

The final visual evidence is stored in `android/artifacts/audit-2026-09-03`. Detailed comparison notes are in `android/design-qa.md`.

## Release boundary

Release builds are locked to the hosted HTTPS API and contain no server credentials. Tokens are stored through the Android Keystore-backed encrypted store. The generated release artifacts remain unsigned when release-key properties are absent; this is intentional and prevents an untrusted repository key from becoming the production identity.

The only unexecuted production proof is a real authenticated login and solve against the hosted service, because no production account credentials were provided to the test run. The contract, unauthenticated production path, capabilities handling, complete fake-gateway workflows, and credential-rotation behavior are covered.
