# Planora User Manual

## Core Workflow

1. Generate or import a scenario.
2. Solve the timetable.
3. Open `Project > Analyze > Show Conflicts` if hard conflicts remain.
4. Use `Project > Repair > Fix Current Conflicts` to freeze unaffected activities and repair only the conflict neighborhood.
5. Use `Improve` for soft-score improvement.
6. Use `Focus` before Improve to target one soft term such as `same_kind_week`, `thin_day`, or `stud_gaps`.
7. Export reports from `Export` or `Project > Reports`.

## CSV Import Choices

Use `Project > Import > Import Timetable CSV (create scenario)` for raw timetable data such as:

```text
week,day,slot,course,major,room
```

This creates groups, courses, rooms, activities, synthetic staff if needed, and an initial schedule.

Use `Project > Import > Load Schedule (CSV)` or `Import Schedule Wizard (CSV)` only when an instance already exists and the CSV contains scheduler activity IDs.

## Repair Tools

`Fix Current Conflicts` extracts activity IDs from hard-conflict messages, unlocks those activities, freezes the rest of the timetable, and starts a targeted solve.

`Focused CP-SAT Polish` uses the current `Focus` term to identify a small set of responsible activities, freezes everything else, and runs a bounded CP-SAT polish pass.

## Quality Tools

`Project > Analyze > Score Breakdown` shows total soft penalty, top penalty drivers, and all modeled penalty terms.

After manual `Improve`, the app shows a before/after report with global penalty delta, moved activities, and changed penalty terms.
