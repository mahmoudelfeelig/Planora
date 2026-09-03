# Android design QA

## Comparison inputs

- Source: `web/artifacts/screenshots/web-blueprint-light.png` at 1280 x 900 and `web/artifacts/screenshots/web-blueprint-dark.png` at 1280 x 900.
- Implementation: the fresh device captures under `android/artifacts/audit-2026-09-03`, including phone screens at 1280 x 2856, the expanded schedule at 2856 x 1280, and compact landscape at 2856 x 1200.
- Implementation surface: `android/app/src/main/java/com/planora/mobile/ui/PlanoraApp.kt` and the theme/assets under `android/app/src/main`.
- State: signed-in schedule review for the Engineering review project, with Algorithms selected in the timetable. Light, dark, portrait, compact landscape, and expanded/tablet layouts were compared.

## QA history

- The first device capture was rejected because Android system UI from an emulator dialog contaminated the screenshot. The Compose root was recaptured directly.
- The first dark comparison exposed bottom-navigation icons with insufficient contrast. Icon tint now resolves through the active Material content color and the dark state was recaptured.
- The compact landscape comparison exposed an overcrowded action row with trailing actions clipped beyond the viewport. Save, export, and rebuild now live in a visible overflow menu in compact layouts; validate, improve, and solve-mode selection remain directly available.
- Registration, Tools, CSV mapping, project management, and manual-move states were added to the current device capture set. Settings cards were normalized to full width after the first expanded feature capture exposed inconsistent card sizing.
- The final pass placed each web reference and its Android implementation captures together in the same visual comparison input.

## Final review

- Brand: passed. The source elephant mark, navy/slate foundation, pale blue surfaces, blue actions, muted outlines, and schedule event colors carry through both themes.
- Hierarchy: passed. Project context, status, validation and scheduling actions, mode controls, timetable, and navigation remain clear at each viewport.
- Layout: passed. Phone content scrolls without overlap; compact landscape actions fit without hidden controls; expanded layouts expose navigation, timetable, and inspector concurrently.
- Typography and controls: passed. Text remains legible, touch targets remain appropriately sized, selection states are visible, and destructive/session actions are separated from primary schedule actions.
- Theme and accessibility: passed. Light and dark palettes retain readable contrast, including selected and unselected bottom-navigation icons.
- Native adaptation: passed. The Android UI preserves the web/desktop design language without copying desktop-only density or interaction patterns onto a phone.

Final result: passed
