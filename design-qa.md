# Planora Academic Blueprint design QA

Reference: `/mnt/c/Users/mahmo/.codex/attachments/cba8563f-f167-4e81-9057-57b10c1a9717/image-1.png`

Latest populated evidence:

- Web light: `web/artifacts/screenshots/web-blueprint-light.png`
- Web dark: `web/artifacts/screenshots/web-blueprint-dark.png`
- Desktop light: `/tmp/planora-desktop-blueprint-light.png`
- Desktop dark: `/tmp/planora-desktop-blueprint-dark.png`
- Android portrait: `android/artifacts/screenshots/planora-schedule-portrait.png`
- Android expanded: `android/artifacts/screenshots/planora-schedule-landscape.png`

## Comparison

Web, desktop, and Android now use the reference's core academic-planning composition: a restrained navy shell, cool-white planning surfaces, an academic-data browser, a dominant weekly timetable, and a selected-class inspector. The existing Planora elephant remains the product mark rather than introducing a new visual asset. Web and Android's expanded layout follow the reference's day-column/time-row grid. Desktop retains its established day-row/slot-column interaction model so its mature move and repair flows remain stable, while adopting the same hierarchy, contrast, and course-card language.

The final reference-versus-web comparison was reviewed as one combined image at `/tmp/planora-reference-web-themes.png`, with the supplied reference above the current light and dark workspace states. The refreshed web view preserves the reference's compact three-pane planning density while improving legibility at 1280 pixels: all six day columns are visible, selected classes have a strong focus outline, status colors meet the surrounding contrast, and the timetable scrolls internally instead of widening the page. Desktop light and dark captures were inspected separately for clipped controls, weak text, washed-out cards, ambiguous selection states, and stale table colors after a live theme switch.

The normal information architecture is shared across the three clients: Schedule, Data, Review, Projects, and an advanced/settings surface. The public planning path contains Demo timetable, Spring 2023 university, and Import your data, plus Fast, Balanced, and Quality. Research generators and raw solver controls remain outside the normal workflow.

The five-step, non-technical tutorial is first-run and replayable in all three clients and is sourced from the shared UI contract. The focused browser flow verified focus trapping, data selection, schedule build, populated timetable rendering, class selection, suggestions, keyboard schedule movement, dismissible notifications, every primary authenticated view, responsive inspector visibility, document-level scroll containment, and measured 4.5:1-or-better representative text contrast in both themes. The focused desktop flow verified construction, busy-state controls, data generation, outer timetable scrolling, theme persistence/switching, shared-backend solve, populated timetable rendering, and selected-class inspector content. Android device flows verified the tutorial, portrait schedule, expanded three-pane workspace, Validate/Improve/Publish actions, and the recommended planning mode.

## Final defect pass

- P0: none found.
- P1: none found. The false single-theme desktop style, web dark-mode contrast failures, theme-transition contrast flash, non-dismissible notifications, and page-level schedule overflow were corrected.
- P2: none blocking this design acceptance. Long resource lists, inspectors, and dense timetables scroll inside their own panes by design. Motion is limited to meaningful hover, view, and notification feedback and is removed when reduced motion is requested.

## Verification

- Web production build: passed (`npm run build` in the final Docker image; 47 modules transformed).
- Final Edge acceptance: 2 tests passed in 7.2 seconds. The authenticated test covers tutorial focus containment, Data, solve, class selection, keyboard movement, closeable toasts, Review, Projects, Advanced, return to Schedule, 820-pixel responsiveness, internal scrolling, and immediate light/dark contrast. The second test covers the public accessibility contract.
- Desktop compile: passed for the modified Python UI modules.
- Desktop focused UI smoke: 6 tests passed in 14.82 seconds, including external timetable scrolling and live light/dark switching.
- Populated desktop solve: passed through the shared backend client with 182 activities and zero hard conflicts in the captured draft.
- Android unit tests, lint, app APK, and instrumentation APK: passed in the final 85-task Gradle gate.
- Android device UI acceptance: passed, 3 tests on the API 33 emulator after the final color and typography change.
- Android live shared-backend acceptance: passed login -> capabilities -> demo preset -> solve -> validate -> improve against the current API, including preservation of the complete opaque instance document.

final result: passed
