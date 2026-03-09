# Feature Checklist

This file separates what the scheduler already supports from what would make it a stronger general-purpose product.

Legend:
- `[x]` implemented in the current codebase
- `[ ]` not implemented yet / recommended backlog item

## Core Solve Engine

- [x] CP-SAT feasibility solver for timetable construction
- [x] Strict room assignment mode (`cp_rooms`) inside CP
- [x] Fast room assignment mode (`greedy`) after CP timing
- [x] Optional CP soft-objective mode
- [x] Objective-off retry path when objective search fails
- [x] Strict-to-greedy fallback path for feasibility recovery
- [x] Phased solve flow: feasibility-first then bounded improvement
- [x] Worker-count control for CP solving
- [x] Solver time-limit control
- [x] Local-search improver with iteration and time budgets
- [x] Hard-conflict rejection of invalid solver/improver outputs
- [x] Incremental re-solve that recompiles only affected activities/resources
- [x] Persistent solve cache for repeated near-identical scenarios
- [x] Portfolio solve mode that generates and ranks multiple candidate schedules
- [x] Service/backend wrapper around the solver engine
- [x] Stable solve/improve request/result contract dataclasses
- [x] Rule registry so new constraints can compile through one shared definition point

## Hard Constraints

- [x] Group no-overlap enforcement
- [x] Staff no-overlap enforcement
- [x] Staff availability enforcement by day
- [x] Staff availability enforcement by week
- [x] Room capacity eligibility checks
- [x] Room-type eligibility checks
- [x] Specialized-lab tag matching
- [x] Room availability enforcement
- [x] Week-1 lectures-only rule
- [x] Staff daily load-cap enforcement
- [x] Staff weekly load-cap enforcement
- [x] Block-professor rule enforcement
- [x] Locked activity time constraints
- [x] Locked activity room constraints
- [x] Post-edit/post-import schedule validation
- [x] Travel-time buffers between buildings/campuses
- [x] Building-level availability and closure windows
- [x] Institution-defined blackout dates / holidays / exam weeks
- [x] Resource-precedence rules (activity A must happen before B)
- [x] Generic reusable rule-definition registry

## Soft Constraints And Quality

- [x] Free-day optimization
- [x] Mon-Fri free-day optimization
- [x] Gap minimization
- [x] Active-day minimization
- [x] Late-start penalty handling
- [x] Thin-day / single-slot-day penalties
- [x] Week-to-week stability penalties
- [x] Same-kind weekly distribution penalties
- [x] Room-consistency pressure
- [x] Editable soft weights in the UI
- [x] Constraint templates for hard/soft rule presets
- [x] Fairness dashboard for groups and staff
- [x] Total-score display and score-delta previews in the UI
- [x] Objective profiles such as `fast feasible`, `balanced`, `quality-first`
- [x] Per-rule penalty contribution breakdown for each schedule
- [x] Explainable ranking of why one solution is better than another
- [x] SLA-style optimization targets per institution/department
- [x] Rule metadata with descriptions and compile-time defaults

## Scenario Generation And Modeling

- [x] Built-in generation modes (`small_demo`, `block_profs`, `mixed_large`, `target_case`, `custom`)
- [x] Custom program count
- [x] Custom groups-per-program settings
- [x] Per-program group overrides
- [x] Custom courses-per-program settings
- [x] Program-level course overrides
- [x] Editable program names
- [x] Editable course names
- [x] Course-ID based configuration
- [x] Lecture/tutorial/lab count inference from entered counts
- [x] Lab-only / lecture-only / tutorial-only course support via counts
- [x] Staff mapping editor
- [x] Staff course ownership mapping
- [x] Staff day availability configuration
- [x] Staff week availability configuration
- [x] Room editor with room types and specialization tags
- [x] Numeric and categorical room-capacity modes
- [x] Save local custom-generator settings
- [x] Export custom-generator configuration to JSON
- [x] Import custom-generator configuration from JSON
- [x] Custom teaching days / weeks / slots-per-day in custom generation
- [x] Arbitrary term lengths beyond the fixed academic pattern
- [x] Versioned product scenario model separate from the solver instance
- [x] Product-to-solver compile step foundation
- [x] Date-driven product calendar contract (foundation; partial lowering today)
- [x] Campus/building metadata on room resources
- [x] Multiple campuses/buildings/floors in the base model
- [x] Generic resource types beyond room/staff/group/course
- [x] Reusable institutional templates with branding + rules + imports

## Scheduler Workspace UI

- [x] Desktop UI with dedicated scheduler workspace
- [x] Empty timetable shown immediately after generation
- [x] Default maximized application startup
- [x] View by Group
- [x] View by Staff
- [x] View by Room
- [x] View by All
- [x] Week selector
- [x] Entity selector
- [x] Scrollable schedule workspace
- [x] Color coding for conflicts / manual changes / move previews
- [x] Tooltips across controls, settings, fairness items, and actions
- [x] Progress display while solving/improving
- [x] Stop-improving control
- [x] Fully non-blocking UI during every solve/improve/edit-analysis path
- [x] Virtualized large tables/views for bigger institutions
- [x] Search/filter bar across activities, staff, rooms, and conflicts
- [x] Keyboard shortcuts and command palette
- [x] Optional web/desktop frontend split with stable backend contract

## Manual Editing And Admin Actions

- [x] Quick edit for selected activity
- [x] Hold activity for move planning
- [x] Hover-based held-target preview
- [x] Move held activity to selected slot
- [x] Swap held and selected activities
- [x] Force move despite conflicts
- [x] Conflict-aware move dialog
- [x] Move-conflict resolution workflow
- [x] Toggle time lock
- [x] Toggle room lock
- [x] Clear all locks
- [x] Explain move / explain blockers
- [x] Show held targets
- [x] Release held activity
- [x] Jump from conflict list to activity
- [x] Solve-conflicts action from conflict inspector
- [x] Auto-repair disruption workflow
- [x] Preserve/reapply locks around repair flows
- [x] Bulk-edit selected activities
- [x] Multi-select note/week/lock actions from timetable selections
- [x] Rule-safe drag-and-drop editing
- [x] Approval-required overrides for dangerous edits
- [x] Admin notes/comments attached to activities

## History, Branching, And Comparison

- [x] Undo
- [x] Redo
- [x] Undo 5
- [x] Redo 5
- [x] Revert to base solution
- [x] History tab
- [x] Snapshot save/load
- [x] Snapshot folder access
- [x] Sandbox branch start
- [x] Sandbox compare
- [x] Sandbox apply
- [x] Sandbox discard
- [x] Schedule compare report generation
- [x] Audit log path exposure
- [x] Named branches with metadata and merge assistance
- [x] Publish/freeze workflow with release candidates
- [x] Multi-user change history and attribution
- [x] Protected baseline with approval gates

## Imports, Exports, And Interoperability

- [x] Save project snapshots (JSON/PKL)
- [x] Load project snapshots (JSON/PKL)
- [x] Service-backed project save/load flow
- [x] Product-scenario JSON save/load flow
- [x] Load raw instance files
- [x] Load schedule CSV
- [x] CSV import wizard with custom header mapping
- [x] CSV schedule export
- [x] DOCX export
- [x] PDF export
- [x] Summary report export
- [x] ICS export by group
- [x] ICS export by staff
- [x] ICS export by room
- [x] Calendar feed export with manifest
- [x] Saved import/export templates per institution
- [x] REST/GraphQL API for integration
- [x] SIS/ERP/LMS connectors
- [x] Outlook / Google Calendar sync integration
- [x] Database-backed persistence instead of file-only persistence
- [x] Versioned legacy project/save payloads

## Diagnostics And Explainability

- [x] Feasibility explanation helpers
- [x] No-feasible-schedule diagnostics
- [x] Conflict inspector
- [x] Human-readable conflict explanations
- [x] Move-conflict explanation text
- [x] Attempt/fallback diagnostics from solver worker
- [x] Fairness metrics for groups
- [x] Fairness metrics for staff
- [x] Rooming diagnostics tests and validations
- [x] Unsat-core-like rule diagnosis for infeasible scenarios
- [x] “Why not this slot?” explainer for arbitrary candidate placements
- [x] Per-entity heatmaps for overload, gaps, and instability
- [x] Schedule quality report suitable for external stakeholders

## Packaging, Delivery, And Operations

- [x] Windows packaging script
- [x] Windows installer via Inno Setup
- [x] Dedicated packaged solver worker executable
- [x] Unix packaging script
- [x] Portable distribution artifacts
- [x] Release artifact freezing script
- [x] CI checks for Python/tests
- [x] Paper build workflow
- [x] Extensive pytest regression coverage
- [x] Auto-update channel for desktop releases
- [x] Crash-report collection with user opt-in
- [x] Structured runtime logs and support bundles
- [x] Telemetry/analytics with explicit opt-in
- [x] About screen in the app
- [x] Benchmark corpus with solve thresholds and score guards (foundation)

## Productization And Brand Layer

- [x] Product icon / app icon
- [x] Named installer and release packaging
- [x] Product name system (stable app name, short name, owner line)
- [x] About dialog with owner and version
- [x] Consistent visual brand kit (logo variants, palette, typography, screenshots)
- [x] Branded export templates (PDF/DOCX/report headers)
- [x] Custom domain / site / documentation portal
- [x] Trademark filing workflow / brand protection checklist
- [x] White-label institution profile support
