# Planora for Android

Planora's Android client is a single-module Kotlin and Jetpack Compose app. UI code depends on the typed `PlanoraGateway` domain boundary; Retrofit DTOs, bearer authentication, and endpoint details remain in the data layer.

## Server contract

The client requires `planora.ui.v1` from `GET /capabilities`. The server owns the scenario catalog (`demo`, `spring_2023`, `import`) and solve-mode catalog (`fast`, `balanced`, `quality`). Scenario creation, solving, improving, and saving are routed through session and job APIs rather than duplicating solver logic on-device.

For compatibility with the currently hosted pre-contract response, the client also accepts the legacy string-valued `shared_backend` field and exposes its existing `small_demo` and `ss23_uni_like` presets under the same plain-language labels. The fallback is enabled only when the server advertises the required preset, solve, and improve actions.

Release builds always use the hosted API at `https://planora.elfeel.me/api`. The release endpoint cannot be changed in the app. Users sign in with the same Planora account they use on the web and desktop clients; no server credential or shared secret is packaged in the APK.

## Web feature parity

The Android navigation keeps the everyday timetable flow in the bottom bar and places the wider web workspace under **Tools**. The native client includes:

- email/password sign-in, registration, email-code confirmation, forgotten-password recovery, and password reset;
- organization switching, invite redemption, password changes, and active-session revocation;
- server presets, CSV file import with custom column mapping, and Fast, Balanced, or Quality planning modes;
- hosted solve, validate, cancellable improve jobs, CSV export, and server-approved manual class moves;
- project list, save, open, rename, and delete operations with tenant and legacy-project safeguards;
- advanced solver overrides, fairness/utilization insights, and the shared platform-parity manifest;
- permission-gated user, group, membership, scoped-role, schedule-identity, and invite administration;
- global-admin system status, audit/analytics filtering and CSV export, and SMTP test delivery;
- light, dark, and system themes, the walkthrough, elephant branding, and direct Privacy/FAQ access.

Optional web analytics are not emitted by the Android client, so the web-only analytics-consent cookie has no native equivalent. Solver execution remains on the hosted service; the APK contains no local solver or backend secret.

Debug builds default to the same hosted API and allow an endpoint override for local development:

```shell
./gradlew :app:assembleDebug -PPLANORA_API_BASE_URL=http://10.0.2.2:8787
```

Only debug builds permit cleartext connections to `localhost`, `127.0.0.1`, and the Android emulator host `10.0.2.2`. Remote debug endpoints must use HTTPS.

## Branding

The launcher and Android 12+ splash reuse the transparent Planora elephant artwork over Planora navy. The adaptive icon keeps its background and foreground in separate layers and includes a monochrome alpha-mask layer for themed launchers. Window and splash backgrounds follow the light or dark system theme.

## Verify

With JDK 17 and Android SDK 36 installed, run the checks that do not require a device:

```shell
./gradlew --offline :app:testDebugUnitTest
./gradlew --offline :app:lintDebug
./gradlew --offline :app:assembleDebug :app:assembleDebugAndroidTest
./gradlew --offline :app:bundleRelease
```

With an emulator or device running:

```shell
./gradlew --offline :app:connectedDebugAndroidTest
```

Device-flow screenshots are written to `/sdcard/Download` by the instrumentation suite. The latest generated captures are also available under `app/build/reports/visual-audit`; the full verification snapshot is recorded in `release-readiness-2026-09-03.md`.

The Android CI workflow runs unit tests, lint, builds the debug and instrumentation APKs, and produces an unsigned release bundle for packaging verification.

## Release signing

Release signing is activated only when all four values below are supplied either as Gradle properties or environment variables:

```text
PLANORA_RELEASE_STORE_FILE=/absolute/path/to/planora-upload.jks
PLANORA_RELEASE_STORE_PASSWORD=<secret>
PLANORA_RELEASE_KEY_ALIAS=<upload-key-alias>
PLANORA_RELEASE_KEY_PASSWORD=<secret>
```

Keep these values outside the repository, for example in the user-level Gradle properties file or a protected CI secret store. Keystores and signing-property files are ignored by `android/.gitignore`.

When the values are absent, `bundleRelease` intentionally creates an unsigned bundle so CI can validate resource shrinking and R8. That artifact is not suitable for Play upload. A distributable bundle must be signed with the upload key and then submitted through the Play App Signing boundary.
